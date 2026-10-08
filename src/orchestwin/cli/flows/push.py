from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import brief as brief_api
from orchestwin.cli.api import design as design_api
from orchestwin.cli.api import modeling as modeling_api
from orchestwin.cli.api import packages
from orchestwin.cli.api import requirements as requirements_api
from orchestwin.cli.api import team as team_api
from orchestwin.cli.commands import twins as twins_command
from orchestwin.cli.errors import USAGE_STATUS, ApiFailure, CliError
from orchestwin.cli.flows import align_apply, init_requirements, init_team, verify_decision
from orchestwin.cli.flows import publish as publish_flow
from orchestwin.cli.flows.package_import import local_folder
from orchestwin.cli.flows.twin_selection import OBSERVATION_PREFIX
from orchestwin.cli.flows.verify_review import Workspace
from orchestwin.cli.project import json_bytes, write_atomically

if TYPE_CHECKING:
    from pathlib import Path

    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.commands.init import Journey
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.folder import FolderSummary
    from orchestwin.cli.project import ProjectFolder

COMMAND: Final = "push"
STAGES: Final = ("brief", "team", "twins", "requirements", "design")
PUSHABLE: Final[Mapping[str, str]] = {
    "brief/brief.json": "brief",
    "team/team.json": "team",
    "twins/twins.json": "twins",
    "requirements/requirements.json": "requirements",
    "design/design.json": "design",
}
DOCUMENTS: Final[Mapping[str, str]] = {stage: path for path, stage in PUSHABLE.items()}
CONTENT_KEYS: Final[Mapping[str, str]] = {
    "brief": "brief",
    "team": "proposal",
    "twins": "snapshot",
    "requirements": "specification",
    "design": "package",
}
EXCLUDED: Final = frozenset({knowledge.MANIFEST_NAME, knowledge.GITATTRIBUTES})
STEP: Final = "pushable"
DERIVED: Final = "derived"
UNKNOWN: Final = "unknown"
KINDS: Final = (STEP, DERIVED, UNKNOWN)
CHANGED: Final = "changed"
ADDED: Final = "added"
DELETED: Final = "deleted"
FILE_KEYS: Final[Mapping[str, str]] = {
    STEP: "push.file_pushable",
    DERIVED: "push.file_derived",
    UNKNOWN: "push.file_unknown",
}
CHANGE_KEYS: Final[Mapping[str, str]] = {
    CHANGED: "push.change_changed",
    ADDED: "push.change_added",
    DELETED: "push.change_deleted",
}
SIGNS: Final[Mapping[str, str]] = {ADDED: "+", DELETED: "-", CHANGED: "~"}
DESIGN_SIGNS: Final[Mapping[str, str]] = {"ADD": "+", "REMOVE": "-"}
DESIGN_KEYS: Final[Mapping[str, str]] = {
    "ALTERNATIVE": "alternatives",
    "CRITIQUE": "critiques",
    "CRITIQUE_VERDICT": "critiques",
    "CONCERN": "concerns",
    "PROTOTYPE": "prototype",
    "SELECTION": "owner_selected_alternative_id",
    "OPEN_QUESTIONS": "open_questions",
    "GENERATED_MOCKUP": "generated_mockup",
    "GENERATED_SCREEN": "generated_mockup",
    "GENERATED_STYLES": "generated_mockup",
    "OWNER_ASSERTION": "owner_assertions",
    "OWNER_ASSERTION_ORDER": "owner_assertions",
}
DESIGN_PACKAGE: Final = "package"
IDENTITY_KEYS: Final = ("code", "agent_id", "twin_id", "id")
LABEL_KEYS: Final = ("code", "title", "text")
CONTEXT_REFERENCES: Final = (
    ("project_brief", "project_brief_reference"),
    ("agent_team", "agent_team_reference"),
    ("user_modeling", "user_modeling_reference"),
)
TWIN_LIST: Final = "twin_versions"
PENDING: Final = "DIFF_ALREADY_PENDING"
NO_CHANGES: Final = "NO_CHANGES"
REJECT: Final = "REJECT"
UNCHANGED_STATUS: Final = 200
INVALID_STATUS: Final = 422
REFUSED_STATUS: Final = 1
PUSH_FOLDER: Final = "push"
LATEST_NAME: Final = "latest.json"
SCHEMA_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class FileChange:
    path: str
    change: str
    kind: str

    @property
    def stage(self) -> str | None:
        return PUSHABLE.get(self.path)


@dataclass(frozen=True, slots=True)
class Document:
    stage: str
    content: Mapping[str, object]
    previous: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class TwinChange:
    twin_id: str
    name: str
    replacements: tuple[Mapping[str, object], ...] = ()
    ignored: tuple[str, ...] = ()
    added: bool = False


@dataclass(slots=True)
class Pushed:
    sent: list[str] = field(default_factory=list)
    status: int = 0

    def keep(self, context: CommandContext, name: str) -> None:
        context.console.say("push.stage_kept", stage=name)
        self.status = self.status or REFUSED_STATUS

    def fail(self, status: int) -> None:
        self.status = self.status or status


def run(context: CommandContext, *, dry_run: bool, stage: str | None) -> int:
    console = context.console
    project = context.project()
    if project is None:
        raise CliError("PROJECT_NOT_LINKED")
    link = project.link()
    client = context.client()
    local = local_folder(project.knowledge)
    if not local.exists:
        raise CliError("FOLDER_MISSING", values={"path": f"{link.knowledge_folder}/"})
    if local.summary is None:
        raise local.problem or knowledge.not_verified(
            project.knowledge, "FOLDER_DOCUMENT_MISSING", knowledge.MANIFEST_NAME
        )
    number = local.summary.version_number
    latest = packages.latest(client, link.project_id)
    if latest is None:
        raise CliError("FOLDER_NOT_PUBLISHED")
    newest = latest.get("version_number")
    if isinstance(newest, int) and not isinstance(newest, bool) and newest > number:
        raise CliError("PUSH_FOLDER_BEHIND", values={"local": number, "studio": newest})
    base = published_files(client, project, link.project_id, number)
    here = knowledge.read_files(project.knowledge)
    changes = compared(base, here)
    documents = report(context, changes, base, here, number, stage)
    if not documents:
        console.say("push.nothing")
        return 0
    if dry_run:
        console.say("push.dry_run_done")
        return 0
    pushed = Pushed()
    try:
        send(context, project, client, documents, number, pushed)
    finally:
        if pushed.sent:
            kept = restore(project, changes, here, pushed.sent)
            if kept:
                console.say("push.files_kept", files=", ".join(kept))
    return pushed.status


def published_files(
    client: StudioClient, project: ProjectFolder, project_id: str, number: int
) -> Mapping[str, str]:
    reply = packages.archive(client, project_id, number)
    expected = reply.headers.get(publish_flow.HASH_HEADER, "").strip().lower()
    if not expected or hashlib.sha256(reply.content).hexdigest() != expected:
        raise knowledge.not_verified(
            project.knowledge,
            "ARCHIVE_HASH_MISMATCH",
            f"{packages.packages_path(project_id)}/{number}/archive",
        )
    return knowledge.verify_archive(reply.content).files


def compared(base: Mapping[str, str], here: Mapping[str, str]) -> list[FileChange]:
    found: list[FileChange] = []
    for path in sorted((set(base) | set(here)) - EXCLUDED):
        before, after = base.get(path), here.get(path)
        if before is not None and after is not None and _lines(before) == _lines(after):
            continue
        change = ADDED if before is None else DELETED if after is None else CHANGED
        kind = STEP if path in PUSHABLE else DERIVED if before is not None else UNKNOWN
        found.append(FileChange(path, change, kind))
    return found


def report(
    context: CommandContext,
    changes: Sequence[FileChange],
    base: Mapping[str, str],
    here: Mapping[str, str],
    number: int,
    wanted: str | None,
) -> dict[str, Document]:
    console = context.console
    counts = {kind: sum(1 for item in changes if item.kind == kind) for kind in KINDS}
    console.say(
        "push.summary",
        version=number,
        pushable=counts[STEP],
        derived=counts[DERIVED],
        unknown=counts[UNKNOWN],
    )
    documents: dict[str, Document] = {}
    for item in changes:
        stage = item.stage
        console.say(
            FILE_KEYS[item.kind],
            path=item.path,
            change=context.text(CHANGE_KEYS[item.change]),
            stage="" if stage is None else stage_name(context, stage),
        )
        if stage is None or (wanted is not None and stage != wanted):
            continue
        document = Document(
            stage,
            content_of(stage, item.path, here.get(item.path)),
            None if item.path not in base else content_of(stage, item.path, base[item.path]),
        )
        show_document(context, document)
        if sendable(context, document):
            documents[stage] = document
    if counts[DERIVED]:
        console.say("push.derived_hint")
    return {stage: documents[stage] for stage in STAGES if stage in documents}


def content_of(stage: str, path: str, text: str | None) -> Mapping[str, object]:
    key = CONTENT_KEYS[stage]
    invalid = CliError(
        "PUSH_DOCUMENT_INVALID", status=USAGE_STATUS, values={"path": path, "key": key}
    )
    if text is None:
        raise invalid
    try:
        document = json.loads(text)
    except (ValueError, RecursionError):
        raise invalid from None
    content = document.get(key) if isinstance(document, dict) else None
    if not isinstance(content, dict):
        raise invalid
    return content


def show_document(context: CommandContext, document: Document) -> None:
    console = context.console
    if document.stage == "twins":
        show_twins(context, document)
        return
    content, previous = document.content, document.previous
    if document.stage == "brief":
        for sign, what in differences(
            brief_view(content), None if previous is None else brief_view(previous)
        ):
            console.say("push.diff_line", sign=sign, what=what)
        ignored = brief_body(content)[1]
        if ignored:
            console.say("push.brief_fields_ignored", fields=", ".join(ignored))
        return
    for sign, what in differences(content, previous):
        console.say("push.diff_line", sign=sign, what=what)


def show_twins(context: CommandContext, document: Document) -> None:
    console = context.console
    for change in twin_changes(context, document.content, document.previous):
        if change.added:
            console.say("push.diff_line", sign=SIGNS[ADDED], what=change.name)
            continue
        labels = [
            twins_command.field_label(context, f"{OBSERVATION_PREFIX}{item.get('field')}")
            for item in change.replacements
        ]
        if labels:
            console.say(
                "push.diff_line", sign=SIGNS[CHANGED], what=f"{change.name}: {', '.join(labels)}"
            )
        if change.ignored:
            console.say(
                "push.twin_fields_ignored", name=change.name, fields=", ".join(change.ignored)
            )


def sendable(context: CommandContext, document: Document) -> bool:
    content, previous = document.content, document.previous
    if document.stage == "brief":
        return previous is None or brief_body(content)[0] != brief_body(previous)[0]
    if document.stage == "team":
        agents = member_agents(content)
        return bool(agents) and (previous is None or agents != member_agents(previous))
    if document.stage == "twins":
        return previous is None or any(
            change.replacements for change in twin_changes(context, content, previous)
        )
    return content != previous


def differences(
    new: Mapping[str, object], old: Mapping[str, object] | None
) -> list[tuple[str, str]]:
    before = {} if old is None else old
    found: list[tuple[str, str]] = []
    for key in [*new, *(name for name in before if name not in new)]:
        if key not in before:
            found.append((SIGNS[ADDED], key))
        elif key not in new:
            found.append((SIGNS[DELETED], key))
        elif new[key] != before[key]:
            found.extend(item_changes(key, before[key], new[key]) or [(SIGNS[CHANGED], key)])
    return found


def item_changes(key: str, old: object, new: object) -> list[tuple[str, str]]:
    before, after = identified(old), identified(new)
    if before is None or after is None:
        return []
    found: list[tuple[str, str]] = []
    for identity, item in after.items():
        if identity not in before:
            found.append((SIGNS[ADDED], f"{key} {identity}"))
        elif before[identity] != item:
            found.append((SIGNS[CHANGED], f"{key} {identity}"))
    found.extend(
        (SIGNS[DELETED], f"{key} {identity}") for identity in before if identity not in after
    )
    return found


def identified(value: object) -> dict[str, object] | None:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        return None
    if not value:
        return {}
    for name in IDENTITY_KEYS:
        keys = [item.get(name) for item in value]
        if all(isinstance(key, str) and key for key in keys) and len(set(keys)) == len(keys):
            return dict(zip((str(key) for key in keys), value, strict=True))
    return None


def brief_view(content: Mapping[str, object]) -> dict[str, object]:
    fields = content.get("fields")
    view = dict(fields) if isinstance(fields, Mapping) else {}
    view["unknown_fields"] = content.get("unknown_fields")
    return view


def brief_body(content: Mapping[str, object]) -> tuple[dict[str, object], list[str]]:
    fields = content.get("fields")
    values = fields if isinstance(fields, Mapping) else {}
    body: dict[str, object] = {name: values.get(name) for name in brief_api.FIELDS}
    marked = content.get("unknown_fields")
    unknown = [
        name
        for name in (marked if isinstance(marked, list) else [])
        if isinstance(name, str) and name in brief_api.FIELDS
    ]
    body["unknown_fields"] = sorted({name for name in unknown if body.get(name) in (None, "", [])})
    ignored = [str(name) for name in values if name not in brief_api.FIELDS]
    return body, ignored


def member_agents(content: Mapping[str, object]) -> list[str]:
    members = content.get("members")
    if not isinstance(members, list):
        return []
    return team_api.ordered(
        str(item["agent_id"])
        for item in members
        if isinstance(item, Mapping) and isinstance(item.get("agent_id"), str)
    )


def grounded(package: Mapping[str, object], current: Mapping[str, object]) -> dict[str, object]:
    grounding = _mapping(current.get("package")).get("grounding")
    if not isinstance(grounding, Mapping):
        return dict(package)
    return {**package, "grounding": grounding}


def api_specification(specification: Mapping[str, object]) -> dict[str, object]:
    body = {key: value for key, value in specification.items() if key != "context"}
    governed = specification.get("context")
    if not isinstance(governed, Mapping):
        return body
    for name, key in CONTEXT_REFERENCES:
        body[key] = governed.get(name)
    catalog = governed.get("catalog")
    catalog = catalog if isinstance(catalog, Mapping) else {}
    body["catalog_version"] = catalog.get("version")
    body["catalog_content_hash"] = catalog.get("content_hash")
    return body


def twin_changes(
    context: CommandContext,
    content: Mapping[str, object],
    previous: Mapping[str, object] | None,
) -> list[TwinChange]:
    now = twins_by_id(content)
    if previous is None:
        return [
            TwinChange(twin_id, twin_name(twin, twin_id), added=True)
            for twin_id, twin in now.items()
        ]
    before = twins_by_id(previous)
    found: list[TwinChange] = []
    for twin_id, twin in now.items():
        base = before.get(twin_id)
        name = twin_name(twin if base is None else base, twin_id)
        if base is None:
            found.append(TwinChange(twin_id, name, ignored=(label(context, TWIN_LIST),)))
            continue
        replacements, ignored = twin_fields(context, twin, base)
        if replacements or ignored:
            found.append(TwinChange(twin_id, name, tuple(replacements), tuple(ignored)))
    found.extend(
        TwinChange(twin_id, twin_name(base, twin_id), ignored=(label(context, TWIN_LIST),))
        for twin_id, base in before.items()
        if twin_id not in now
    )
    other = [label(context, key) for key in changed_keys(content, previous, skip=TWIN_LIST)]
    if other:
        found.append(TwinChange("", stage_name(context, "twins"), ignored=tuple(other)))
    return found


def twin_fields(
    context: CommandContext, twin: Mapping[str, object], base: Mapping[str, object]
) -> tuple[list[dict[str, object]], list[str]]:
    profile, before = _mapping(twin.get("profile")), _mapping(base.get("profile"))
    ignored = [label(context, key) for key in changed_keys(twin, base, skip="profile")]
    ignored.extend(
        label(context, key) for key in changed_keys(profile, before, skip="observations")
    )
    now, then = observations_of(profile), observations_of(before)
    replacements: list[dict[str, object]] = []
    for key in [*now, *(name for name in then if name not in now)]:
        if now.get(key) == then.get(key):
            continue
        name = key.removeprefix(OBSERVATION_PREFIX)
        if key in now and key.startswith(OBSERVATION_PREFIX) and name in twins_command.FIELDS:
            replacements.append(replacement(name, now[key]))
        else:
            ignored.append(label(context, key))
    return replacements, ignored


def changed_keys(new: Mapping[str, object], old: Mapping[str, object], *, skip: str) -> list[str]:
    return [
        key
        for key in [*new, *(name for name in old if name not in new)]
        if key != skip and new.get(key) != old.get(key)
    ]


def replacement(name: str, observation: Mapping[str, object]) -> dict[str, object]:
    return {
        "field": name,
        **{key: observation[key] for key in modeling_api.REPLACEMENT_KEYS if key in observation},
    }


def owner_profiles(content: Mapping[str, object]) -> list[dict[str, object]]:
    profiles: list[dict[str, object]] = []
    for twin in twins_by_id(content).values():
        profile = _mapping(twin.get("profile"))
        persona = _mapping(profile.get("persona_reference"))
        profiles.append(
            {
                "persona_id": persona.get("persona_id"),
                "name": profile.get("name"),
                "observations": [
                    replacement(key.removeprefix(OBSERVATION_PREFIX), observation)
                    for key, observation in observations_of(profile).items()
                    if key.startswith(OBSERVATION_PREFIX)
                    and key.removeprefix(OBSERVATION_PREFIX) in twins_command.FIELDS
                ],
            }
        )
    return profiles


def twins_by_id(snapshot: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    items = snapshot.get(TWIN_LIST)
    return {
        str(item["twin_id"]): item
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, Mapping) and isinstance(item.get("twin_id"), str)
    }


def observations_of(profile: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    items = profile.get("observations")
    return {
        str(item["observation_key"]): item
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, Mapping) and isinstance(item.get("observation_key"), str)
    }


def twin_name(twin: Mapping[str, object], fallback: str) -> str:
    name = _mapping(twin.get("profile")).get("name")
    return name if isinstance(name, str) and name.strip() else fallback


def label(context: CommandContext, key: str) -> str:
    return twins_command.field_label(context, key)


def stage_name(context: CommandContext, stage: str) -> str:
    return context.text(f"common.stage_{stage}")


def send(
    context: CommandContext,
    project: ProjectFolder,
    client: StudioClient,
    documents: Mapping[str, Document],
    number: int,
    pushed: Pushed,
) -> None:
    from orchestwin.cli.commands.init import Journey

    console = context.console
    workspace = Workspace(project, client, project.link().project_id, project.root, {})
    journey = Journey(context, client, project, script=None, until=None, idea=None)
    for stage, document in documents.items():
        name = stage_name(context, stage)
        console.write()
        if not context.assume_yes and not console.confirm(
            "push.send_stage", default=True, stage=name
        ):
            pushed.keep(context, name)
            continue
        SENDERS[stage](context, workspace, journey, document, pushed)
    if not pushed.sent:
        return
    found = refreshed(context, workspace, number)
    console.write()
    console.say(
        "push.done",
        stages=", ".join(stage_name(context, stage) for stage in pushed.sent),
        version=found.version_number,
        files=found.file_count,
    )
    write_latest(context, project, number, found.version_number, pushed.sent)


def restore(
    project: ProjectFolder,
    changes: Sequence[FileChange],
    here: Mapping[str, str],
    sent: Sequence[str],
) -> list[str]:
    kept: list[str] = []
    for item in changes:
        text = here.get(item.path)
        if text is None or item.kind == DERIVED or (item.kind == STEP and item.stage in sent):
            continue
        target = project.knowledge.joinpath(*item.path.split("/"))
        if target.is_file() and same_content(item, target.read_bytes(), text):
            continue
        write_atomically(target, text.encode("utf-8"))
        kept.append(item.path)
    return kept


def same_content(item: FileChange, written: bytes, text: str) -> bool:
    try:
        found = written.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if _lines(found) == _lines(text):
        return True
    stage = item.stage
    if stage is None:
        return False
    key = CONTENT_KEYS[stage]
    try:
        old, new = json.loads(found), json.loads(text)
    except (ValueError, RecursionError):
        return False
    return isinstance(old, dict) and isinstance(new, dict) and old.get(key) == new.get(key)


def send_brief(
    context: CommandContext,
    workspace: Workspace,
    journey: Journey,
    document: Document,
    pushed: Pushed,
) -> None:
    name = stage_name(context, "brief")
    client, project_id = workspace.client, workspace.project_id
    if not approves(context, name):
        pushed.keep(context, name)
        return
    status, answer = brief_api.create(client, project_id, brief_body(document.content)[0])
    if status >= 400 or not isinstance(answer, Mapping):
        raise refusal(status, answer)
    if status == UNCHANGED_STATUS:
        context.console.say("push.stage_unchanged", stage=name)
        return
    pushed.sent.append("brief")
    conclude(
        context,
        workspace,
        journey,
        "brief",
        answer,
        pushed,
        (
            lambda: brief_api.submit_gate(client, project_id),
            lambda: brief_api.decide_gate(client, project_id),
        ),
    )


def send_team(
    context: CommandContext,
    workspace: Workspace,
    journey: Journey,
    document: Document,
    pushed: Pushed,
) -> None:
    name = stage_name(context, "team")
    client, project_id = workspace.client, workspace.project_id
    selected = member_agents(document.content)
    current = team_api.current(client, project_id)
    if not approves(context, name):
        pushed.keep(context, name)
        return
    if current is None:
        status, answer = team_api.owner_proposal(client, project_id, selected)
    else:
        status, answer = team_api.edit(client, project_id, selected)
    if status == INVALID_STATUS and team_api.issues(answer):
        init_team.refusals(journey, answer)
        pushed.keep(context, name)
        return
    if status >= 400:
        raise refusal(status, answer)
    version = team_api.version(answer)
    if version is None:
        raise ApiFailure("API_FAILURE", http_status=status, detail=answer)
    if status == UNCHANGED_STATUS:
        context.console.say("push.stage_unchanged", stage=name)
        return
    pushed.sent.append("team")
    conclude(
        context,
        workspace,
        journey,
        "team",
        version,
        pushed,
        (
            lambda: team_api.submit_gate(client, project_id),
            lambda: team_api.decide_gate(client, project_id),
        ),
    )


def send_twins(
    context: CommandContext,
    workspace: Workspace,
    journey: Journey,
    document: Document,
    pushed: Pushed,
) -> None:
    console = context.console
    name = stage_name(context, "twins")
    client, project_id = workspace.client, workspace.project_id
    gate = (
        lambda: modeling_api.submit_gate(client, project_id),
        lambda: modeling_api.decide_gate(client, project_id),
    )
    current = modeling_api.snapshot(client, project_id)
    if current is None:
        if not approves(context, name):
            pushed.keep(context, name)
            return
        status, answer = modeling_api.owner_profiles(
            client, project_id, owner_profiles(document.content)
        )
        if status >= 400:
            raise refusal(status, answer)
        snapshot = _mapping(_mapping(answer).get("snapshot_version")) or (
            modeling_api.snapshot(client, project_id) or {}
        )
        pushed.sent.append("twins")
        conclude(context, workspace, journey, "twins", snapshot, pushed, gate)
        return
    base = document.previous if document.previous is not None else _mapping(current.get("snapshot"))
    changes = [
        change for change in twin_changes(context, document.content, base) if change.replacements
    ]
    if not changes:
        console.say("push.stage_unchanged", stage=name)
        return
    approved = 0
    for change in changes:
        status, answer = modeling_api.propose_revision(
            client, project_id, change.twin_id, change.replacements
        )
        if status >= 400:
            raise pending_or(refusal(status, answer), name)
        diff = _mapping(_mapping(answer).get("diff"))
        diff_id = diff.get("id")
        if not isinstance(diff_id, str):
            raise ApiFailure("API_FAILURE", http_status=status, detail=answer)
        show_twin_diff(context, diff)
        if not approves(context, change.name):
            decided = modeling_api.decide_revision(
                client, project_id, diff_id, REJECT, context.text("push.reject_reason")
            )
            if decided[0] >= 400:
                raise refusal(*decided)
            pushed.keep(context, change.name)
            continue
        decided = modeling_api.decide_revision(client, project_id, diff_id, modeling_api.APPROVE)
        if decided[0] >= 400:
            raise refusal(*decided)
        approved += 1
    if not approved:
        return
    pushed.sent.append("twins")
    snapshot = modeling_api.snapshot(client, project_id) or {}
    conclude(context, workspace, journey, "twins", snapshot, pushed, gate)


def send_requirements(
    context: CommandContext,
    workspace: Workspace,
    journey: Journey,
    document: Document,
    pushed: Pushed,
) -> None:
    name = stage_name(context, "requirements")
    client, project_id = workspace.client, workspace.project_id
    specification = api_specification(document.content)
    if requirements_api.current(client, project_id) is None:
        if not approves(context, name):
            pushed.keep(context, name)
            return
        status, answer = requirements_api.owner_specification(client, project_id, specification)
        if status >= 400:
            raise refusal(status, answer)
        follow_requirements(context, workspace, journey, _mapping(answer).get("version"), pushed)
        return
    try:
        answer = requirements_api.propose_revision(client, project_id, specification)
    except ApiFailure as failure:
        raise pending_or(failure, name) from None
    diff = _mapping(answer.get("diff"))
    diff_id = str(diff.get("id"))
    init_requirements.show_diff(journey, diff)
    if not approves(context, name):
        status, refused = requirements_api.decide(
            client, project_id, diff_id, requirements_api.REJECT, context.text("push.reject_reason")
        )
        if status >= 400:
            raise refusal(status, refused)
        pushed.keep(context, name)
        return
    status, decided = requirements_api.decide(client, project_id, diff_id, requirements_api.APPROVE)
    if status >= 400:
        raise refusal(status, decided)
    follow_requirements(context, workspace, journey, _mapping(decided).get("version"), pushed)


def send_design(
    context: CommandContext,
    workspace: Workspace,
    journey: Journey,
    document: Document,
    pushed: Pushed,
) -> None:
    console = context.console
    name = stage_name(context, "design")
    client, project_id = workspace.client, workspace.project_id
    current = design_api.current(client, project_id)
    if current is None:
        raise CliError("PUSH_DESIGN_MISSING")
    try:
        answer = design_api.propose_revision(
            client, project_id, grounded(document.content, current)
        )
    except ApiFailure as failure:
        if failure.code == NO_CHANGES:
            console.say("push.stage_unchanged", stage=name)
            return
        raise pending_or(failure, name) from None
    diff = _mapping(answer.get("diff"))
    diff_id = str(diff.get("id"))
    show_design_diff(context, diff)
    if not approves(context, name):
        client.post(
            f"{design_api.design_path(project_id)}/revisions/{diff_id}/decision",
            {"decision": REJECT, "reason": context.text("push.reject_reason")},
        )
        pushed.keep(context, name)
        return
    design_api.decide_revision(client, project_id, diff_id)
    pushed.sent.append("design")
    outcome = align_apply.Outcome()
    align_apply.approve_design(context, workspace, outcome)
    pushed.fail(outcome.status)


SENDERS: Final[
    Mapping[str, Callable[[CommandContext, Workspace, Journey, Document, Pushed], None]]
] = {
    "brief": send_brief,
    "team": send_team,
    "twins": send_twins,
    "requirements": send_requirements,
    "design": send_design,
}


def follow_requirements(
    context: CommandContext,
    workspace: Workspace,
    journey: Journey,
    version: object,
    pushed: Pushed,
) -> None:
    found = _mapping(version) or requirements_api.current(workspace.client, workspace.project_id)
    if not found:
        raise ApiFailure("API_FAILURE", http_status=200)
    pushed.sent.append("requirements")
    outcome = align_apply.Outcome()
    align_apply.approve_requirements(context, workspace, journey, found, outcome)
    pushed.fail(outcome.status)


def conclude(
    context: CommandContext,
    workspace: Workspace,
    journey: Journey,
    stage: str,
    version: Mapping[str, object],
    pushed: Pushed,
    gate: tuple[Callable[[], tuple[int, object]], Callable[[], tuple[int, object]]],
) -> None:
    try:
        approval = journey.approve(gate[0], gate[1], step=stage)
    except CliError as error:
        if (
            error.status in verify_decision.ENDING_STATUSES
            or error.code in verify_decision.ENDING_CODES
        ):
            raise
        verify_decision.report(context, error, COMMAND)
        pushed.fail(error.status)
        return
    journey.conclude(stage, version, approval)
    verify_decision.realign_design(context, workspace)


def show_twin_diff(context: CommandContext, diff: Mapping[str, object]) -> None:
    for operation in _mappings(diff.get("operations")):
        after = _mapping(operation.get("after"))
        what = label(context, f"{OBSERVATION_PREFIX}{operation.get('field')}")
        context.console.say(
            "push.diff_line",
            sign=SIGNS[ADDED] if operation.get("before") is None else SIGNS[CHANGED],
            what=f"{what}: {twins_command.value_text(context, after)}",
        )


def show_design_diff(context: CommandContext, diff: Mapping[str, object]) -> None:
    changes = _mappings(diff.get("changes"))
    context.console.say("init.change_heading", count=len(changes))
    for change in changes:
        context.console.say(
            "push.diff_line",
            sign=DESIGN_SIGNS.get(str(change.get("kind")), SIGNS[CHANGED]),
            what=design_label(change),
        )


def design_label(change: Mapping[str, object]) -> str:
    kind = str(change.get("artifact_kind"))
    key = DESIGN_KEYS.get(kind, DESIGN_PACKAGE)
    for side in ("after", "before"):
        value = _mapping(change.get(side))
        for name in LABEL_KEYS:
            text = value.get(name)
            if isinstance(text, str) and text.strip():
                return f"{key} {' '.join(text.split())}"
    return key


def approves(context: CommandContext, name: str) -> bool:
    return context.console.confirm("push.approve_stage", default=False, stage=name)


def refusal(status: int, answer: object) -> ApiFailure:
    from orchestwin.cli.commands.init import code_of

    return ApiFailure(code_of(answer) or "API_FAILURE", http_status=status, detail=answer)


def pending_or(failure: ApiFailure, name: str) -> CliError:
    if failure.code == PENDING:
        return CliError("PUSH_REVISION_PENDING", values={"stage": name})
    return failure


def refreshed(context: CommandContext, workspace: Workspace, number: int) -> FolderSummary:
    found = knowledge.summary(workspace.project.knowledge)
    if found is not None and found.version_number != number:
        return found
    return publish_flow.publish_and_pull(context, workspace.client, workspace.project)


def write_latest(
    context: CommandContext,
    project: ProjectFolder,
    number: int,
    version: int,
    stages: Sequence[str],
) -> Path:
    path = latest_file(project)
    document = {
        "schema_version": SCHEMA_VERSION,
        "pushed_at": context.environment.now().isoformat(timespec="seconds"),
        "from_version": number,
        "to_version": version,
        "stages": list(stages),
        "files": [DOCUMENTS[stage] for stage in stages],
    }
    write_atomically(path, json_bytes(document))
    return path


def latest_file(project: ProjectFolder) -> Path:
    return project.local / PUSH_FOLDER / LATEST_NAME


def _lines(text: str) -> str:
    return text.replace("\r\n", "\n")


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mappings(value: object) -> list[Mapping[str, object]]:
    items: Iterable[object] = value if isinstance(value, list) else []
    return [item for item in items if isinstance(item, Mapping)]
