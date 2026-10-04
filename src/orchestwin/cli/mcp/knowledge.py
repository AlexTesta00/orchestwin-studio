from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Final

from orchestwin.cli.api import twin_chat
from orchestwin.cli.flows.twin_selection import Twin, twins_from
from orchestwin.cli.folder import IGNORED_NAMES

MANIFEST: Final = "orchestwin.json"
FOLDER_KIND: Final = "orchestwin.knowledge-folder"
STATE_KIND: Final = "orchestwin.project-state"
SCHEMA_VERSIONS: Final = (2, 3)
STATE_SCHEMA: Final = 3
STAGES: Final = ("brief", "team", "twins", "requirements", "design")
STATE_DOCUMENT: Final = "state/state.json"
CHANGES_DOCUMENT: Final = "twins/feedback/changes.json"
REVIEWS_DOCUMENT: Final = "twins/feedback/reviews.json"
TESTS_DOCUMENT: Final = "twins/feedback/tests.json"
TESTS_KIND: Final = "orchestwin.test-reviews"
LEARNING_DOCUMENT: Final = "twins/feedback/learned.json"
LEARNING_KIND: Final = "orchestwin.twin-learning"
EVIDENCE_DOCUMENT: Final = "twins/evidence.json"
EVIDENCE_KIND: Final = "orchestwin.research-evidence"
VALIDATION_DOCUMENT: Final = "validation/human-validation.json"
WORKFLOW_DECISIONS_DOCUMENT: Final = "workflow/decisions.json"
PROVIDED_PROTOTYPES_DOCUMENT: Final = "design/provided-prototypes.json"
MARKDOWN_SUFFIX: Final = ".md"
FOLDER_MISSING: Final = "FOLDER_MISSING"
FOLDER_UNREADABLE: Final = "FOLDER_UNREADABLE"
FOLDER_SCHEMA_UNSUPPORTED: Final = "FOLDER_SCHEMA_UNSUPPORTED"
UNSAFE_CHARACTERS: Final = ("\\", ":", "\0")
UNSAFE_PARTS: Final = frozenset({"", ".", ".."})


class FolderProblem(Exception):
    def __init__(self, code: str, /, **values: object) -> None:
        super().__init__(code)
        self.code = code
        self.values: Mapping[str, object] = MappingProxyType(dict(values))


@dataclass(frozen=True, slots=True)
class Screen:
    identifier: str
    code: str
    title: str
    elements: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Transition:
    code: str
    source: str | None
    target: str | None
    trigger: str | None
    outcome: str | None

    def document(self) -> dict[str, object]:
        return {
            "code": self.code,
            "from": self.source,
            "to": self.target,
            "trigger": self.trigger,
            "outcome": self.outcome,
        }


@dataclass(frozen=True, slots=True)
class DesignView:
    version_number: int | None
    chosen: Mapping[str, object] | None
    alternatives: tuple[Mapping[str, object], ...]
    screens: tuple[Screen, ...]
    transitions: tuple[Transition, ...]

    def screen(self, code: str) -> Screen | None:
        wanted = code.strip().upper()
        return next((screen for screen in self.screens if screen.code.upper() == wanted), None)

    def moves(self, code: str) -> tuple[Transition, ...]:
        return tuple(
            transition
            for transition in self.transitions
            if code in (transition.source, transition.target)
        )


@dataclass(frozen=True, slots=True)
class Knowledge:
    root: Path
    manifest: Mapping[str, object]
    schema_version: int
    version_number: int | None
    approved: tuple[str, ...]
    pending: str | None

    @property
    def complete(self) -> bool:
        return self.pending is None

    def read(self, relative: str) -> object | None:
        path = inside(self.root, relative)
        if path is None:
            raise FolderProblem(FOLDER_UNREADABLE, path=relative)
        if not path.is_file():
            return None
        return _json(path, relative)

    def document(self, relative: str, *, required: bool = True) -> Mapping[str, object] | None:
        found = self.read(relative)
        if found is None and not required:
            return None
        if not isinstance(found, dict):
            raise FolderProblem(FOLDER_UNREADABLE, path=relative)
        return found

    def stage(self, stage: str) -> Mapping[str, object] | None:
        if stage not in self.approved:
            return None
        entry = _mapping(_mapping(self.manifest.get("stages")).get(stage))
        return self.document(_text(entry.get("document")) or f"{stage}/{stage}.json")

    def state(self) -> Mapping[str, object] | None:
        if self.schema_version < STATE_SCHEMA:
            return None
        relative = _text(_mapping(self.manifest.get("state")).get("document")) or STATE_DOCUMENT
        document = self.document(relative)
        if document is None or document.get("kind") != STATE_KIND:
            raise FolderProblem(FOLDER_UNREADABLE, path=relative)
        return document

    def change_runs(self) -> list[Mapping[str, object]]:
        if self.schema_version < STATE_SCHEMA:
            return []
        feedback = _mapping(self.manifest.get("feedback"))
        document = self.document(_text(feedback.get("changes")) or CHANGES_DOCUMENT)
        return [] if document is None else mappings(document.get("runs"))

    def test_runs(self) -> tuple[Mapping[str, object], ...]:
        if self.schema_version < STATE_SCHEMA:
            return ()
        declared = _text(_mapping(self.manifest.get("feedback")).get("tests"))
        relative = declared or TESTS_DOCUMENT
        document = self.document(relative, required=declared is not None)
        if document is None:
            return ()
        if document.get("kind") != TESTS_KIND:
            raise FolderProblem(FOLDER_UNREADABLE, path=relative)
        return tuple(mappings(document.get("runs")))

    def tasks(self) -> tuple[Mapping[str, object], ...]:
        state = self.state()
        return () if state is None else tuple(mappings(state.get("tasks")))

    def learning(self) -> tuple[Mapping[str, object], ...]:
        if self.schema_version < STATE_SCHEMA:
            return ()
        relative = _text(_mapping(self.manifest.get("feedback")).get("learned"))
        if relative is None:
            return ()
        document = self.document(relative)
        if document is None or document.get("kind") != LEARNING_KIND:
            raise FolderProblem(FOLDER_UNREADABLE, path=relative)
        return tuple(mappings(document.get("twins")))

    def stale_reviews(self) -> int:
        value = _mapping(self.manifest.get("state")).get("stale_reviews")
        return value if _integer(value) and value >= 0 else 0

    def evidence(self) -> Mapping[str, object] | None:
        declared = _mapping(self.manifest.get("research_evidence"))
        if not declared:
            return None
        document = self.document(EVIDENCE_DOCUMENT)
        if (
            document is None
            or document.get("kind") != EVIDENCE_KIND
            or document.get("schema_version") != 1
            or "text" in document
        ):
            raise FolderProblem(FOLDER_UNREADABLE, path=EVIDENCE_DOCUMENT)
        if any("text" in item for item in mappings(document.get("evidence"))):
            raise FolderProblem(FOLDER_UNREADABLE, path=EVIDENCE_DOCUMENT)
        return document

    def design_reviews(self) -> int:
        relative = _text(_mapping(self.manifest.get("feedback")).get("reviews_document"))
        if relative is None:
            if "design" not in self.approved:
                return 0
            relative = REVIEWS_DOCUMENT
        document = self.document(relative, required=False)
        return 0 if document is None else len(mappings(document.get("runs")))

    def twins(self) -> tuple[Twin, ...] | None:
        document = self.stage("twins")
        return None if document is None else twins_from(twin_chat.twin_versions(document))

    def workflow_inputs(self):
        from orchestwin.workflow_inputs import WorkflowInputError, workflow_records

        files = {}
        for relative in (WORKFLOW_DECISIONS_DOCUMENT, PROVIDED_PROTOTYPES_DOCUMENT):
            value = self.read(relative)
            if value is not None:
                files[relative] = json.dumps(value, ensure_ascii=False)
        if "workflow_inputs" not in self.manifest and not files:
            return workflow_records(_mapping(self.manifest.get("project")).get("id"))
        from orchestwin.knowledge.archive import KnowledgeArchiveError
        from orchestwin.knowledge.workflow_inputs import read_workflow_inputs

        try:
            return read_workflow_inputs(SimpleNamespace(manifest=self.manifest, files=files))
        except (ValueError, WorkflowInputError, KnowledgeArchiveError) as error:
            raise FolderProblem(FOLDER_UNREADABLE, path=WORKFLOW_DECISIONS_DOCUMENT) from error

    def approved_provided_prototype(self):
        records = self.workflow_inputs()
        declared = _mapping(self.manifest.get("workflow_inputs"))
        reference = _mapping(declared.get("approved_prototype"))
        if reference.get("gate_status") != "APPROVED":
            return None
        return next(
            (
                item
                for item in reversed(records["prototypes"])
                if (item["id"], item["version_number"], item["content_hash"])
                == (
                    reference.get("artifact_id"),
                    reference.get("version_number"),
                    reference.get("content_hash"),
                )
            ),
            None,
        )

    def why(
        self, *, project_id: str | None = None, validation_context=False
    ) -> Mapping[str, object]:
        from orchestwin.cli.mcp.verification import verify_files
        from orchestwin.why import build_why_document

        def invalid(relative):
            return FolderProblem(FOLDER_UNREADABLE, path=relative)

        verify_files(self.root, self.manifest, inside=inside, fail=invalid)
        identity = _mapping(self.manifest.get("project")).get("id")
        if not isinstance(identity, str) or (project_id is not None and identity != project_id):
            raise invalid(MANIFEST)
        stages = {stage: self.stage(stage) for stage in self.approved}
        for stage, document in stages.items():
            entry = _mapping(_mapping(self.manifest.get("stages")).get(stage))
            if (
                document is None
                or document.get("id") != entry.get("version_id")
                or document.get("content_hash") != entry.get("content_hash")
                or document.get("version_number") != entry.get("version_number")
            ):
                raise invalid(f"{stage}/{stage}.json")
        reviews = self.document(REVIEWS_DOCUMENT, required=False) or {}
        learning = self.document(LEARNING_DOCUMENT, required=False) or {}
        records = self.validation_records()
        workflow = self.workflow_inputs()
        result = build_why_document(
            project_id=identity,
            stages=stages,
            evidence=self.evidence(),
            evaluations=[reviews] if reviews else [],
            learning=learning,
            hypotheses=records["hypotheses"],
            outcomes=records["outcomes"],
            workflow_inputs=workflow,
        )
        declared = self.manifest.get("why")
        exported = self.document("traceability/why.json", required=False)
        if declared is not None:
            if (
                declared != {"document": "traceability/why.json", "schema_version": 1}
                or _mapping(self.manifest.get("schemas")).get("why") != "schema/why.schema.json"
                or exported != result
            ):
                raise invalid("traceability/why.json")
        elif exported is not None:
            raise invalid("traceability/why.json")
        if validation_context:
            result = build_why_document(
                project_id=identity,
                stages=stages,
                evidence=self.evidence(),
                evaluations=[reviews] if reviews else [],
                learning=learning,
                hypotheses=records["hypotheses"],
                outcomes=records["outcomes"],
                workflow_inputs=workflow,
                validation_context=True,
            )
        return result

    def why_limits(self) -> tuple[str, ...]:
        if "why" in self.manifest:
            return ()
        limits = ["LEGACY_DOSSIER"]
        if self.read(REVIEWS_DOCUMENT) is None:
            limits.append("LEGACY_FEEDBACK_CONTEXT_MISSING")
        return tuple(limits)

    def validation_records(self):
        declared = self.manifest.get("validation")
        document = self.document(VALIDATION_DOCUMENT, required=False)
        if declared is None and document is None:
            return {"hypotheses": [], "outcomes": [], "omitted_sections": [], "limits": []}
        if (
            not isinstance(declared, Mapping)
            or declared.get("document") != VALIDATION_DOCUMENT
            or declared.get("schema_version") != 1
            or document is None
            or document.get("kind") != "orchestwin.validation-records"
            or document.get("schema_version") != 1
            or document.get("project_id") != _mapping(self.manifest.get("project")).get("id")
            or declared.get("hypotheses") != len(document.get("hypotheses", []))
            or declared.get("outcomes") != len(document.get("outcomes", []))
        ):
            raise FolderProblem(FOLDER_UNREADABLE, path=VALIDATION_DOCUMENT)
        from orchestwin.cli.mcp.validation import verify_records

        if not verify_records(document, self.evidence() or {}):
            raise FolderProblem(FOLDER_UNREADABLE, path=VALIDATION_DOCUMENT)
        return document

    def validation(self, *, project_id=None):
        from orchestwin.validation import validation_overview

        document = self.why(project_id=project_id, validation_context=True)
        records = self.validation_records()
        answer = validation_overview(
            document=document,
            hypotheses=records["hypotheses"],
            outcomes=records["outcomes"],
            evidence=self.evidence(),
        )
        answer["omitted_sections"] = [*answer["omitted_sections"], *records["omitted_sections"]]
        answer["limits"] = sorted({*answer["limits"], *records["limits"], *self.why_limits()})
        return answer

    def walkthrough(
        self, scenario_key, *, project_id=None, alternative_id=None, document_hash=None
    ):
        from orchestwin.validation import ValidationError, scenario_walkthrough
        from orchestwin.workflow_inputs import PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE

        if self.approved_provided_prototype() is not None:
            raise ValidationError(PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE)

        answer = scenario_walkthrough(
            self.why(project_id=project_id, validation_context=True),
            scenario_key,
            alternative_id=alternative_id,
            document_hash=document_hash,
        )
        answer["limits"] = sorted({*answer["limits"], *self.why_limits()})
        return answer


def load(root: Path) -> Knowledge:
    path = root / MANIFEST
    if not path.is_file():
        raise FolderProblem(FOLDER_MISSING)
    manifest = _json(path, MANIFEST)
    if not isinstance(manifest, dict):
        raise FolderProblem(FOLDER_UNREADABLE, path=MANIFEST)
    version = manifest.get("schema_version")
    if (
        manifest.get("kind") != FOLDER_KIND
        or not _integer(version)
        or version not in SCHEMA_VERSIONS
    ):
        raise FolderProblem(FOLDER_SCHEMA_UNSUPPORTED, version=str(version))
    stages = _mapping(manifest.get("stages"))
    progress = manifest.get("progress")
    if version >= STATE_SCHEMA and isinstance(progress, Mapping):
        listed = progress.get("approved")
        names = (
            {item for item in listed if isinstance(item, str)}
            if isinstance(listed, list)
            else set()
        )
        approved = tuple(stage for stage in STAGES if stage in names)
        declared = progress.get("pending")
    else:
        approved = tuple(stage for stage in STAGES if isinstance(stages.get(stage), Mapping))
        declared = None
    pending = (
        declared
        if declared in STAGES and declared not in approved
        else next((stage for stage in STAGES if stage not in approved), None)
    )
    number = _mapping(manifest.get("package")).get("version_number")
    return Knowledge(
        root=root,
        manifest=manifest,
        schema_version=version,
        version_number=number if _integer(number) else None,
        approved=approved,
        pending=pending,
    )


def test_runs(root: Path) -> tuple[Mapping[str, object], ...]:
    return load(root).test_runs()


def tasks(root: Path) -> tuple[Mapping[str, object], ...]:
    return load(root).tasks()


def learning(root: Path) -> tuple[Mapping[str, object], ...]:
    return load(root).learning()


def requirements_view(document: Mapping[str, object]) -> dict[str, object]:
    specification = _mapping(document.get("specification"))
    groups = (
        "requirements",
        "user_stories",
        "acceptance_criteria",
        "scenarios",
        "needs",
        "journeys",
    )
    codes = {
        str(item.get("id")): code
        for group in groups
        for item in mappings(specification.get(group))
        if (code := _text(item.get("code")))
    }
    links = {
        "requirement_ids": "requirement_codes",
        "user_story_ids": "user_story_codes",
        "acceptance_criterion_ids": "acceptance_criterion_codes",
        "scenario_ids": "scenario_codes",
        "need_ids": "need_codes",
    }
    fields = {
        "requirements": ("code", "title", "statement", "kind", "priority"),
        "user_stories": ("code", "goal", "benefit"),
        "acceptance_criteria": ("code", "statement", "verification_method"),
        "scenarios": (
            "code",
            "title",
            "context",
            "goal",
            "preconditions",
            "trigger",
            "steps",
            "criticalities",
            "expected_outcome",
        ),
        "needs": ("code", "title", "statement"),
        "journeys": ("code", "title"),
    }
    view: dict[str, object] = {
        "version_number": _number(document.get("version_number")),
        "schema_version": specification.get("schema_version", 1),
    }
    for group in groups:
        entries = []
        for item in mappings(specification.get(group)):
            entry = {key: item[key] for key in fields[group] if key in item}
            for key, label in links.items():
                if key in item:
                    entry[label] = _codes(item[key], codes)
            for key in ("actor", "user_twin_reference", "user_twin_references", "sources"):
                if key in item:
                    entry[key] = item[key]
            if group == "journeys":
                entry["scenario_code"] = codes.get(str(item.get("scenario_id")))
                entry["phases"] = [
                    {
                        **{
                            key: phase[key]
                            for key in ("title", "action", "touchpoint", "criticalities")
                            if key in phase
                        },
                        "need_codes": _codes(phase.get("need_ids"), codes),
                    }
                    for phase in mappings(item.get("phases"))
                ]
                entry["need_codes"] = list(
                    dict.fromkeys(code for phase in entry["phases"] for code in phase["need_codes"])
                )
            entries.append(entry)
        if group != "journeys" or entries:
            view[group] = entries
    view["actors"] = requirement_actors(view)
    return view


def requirement_actors(view: Mapping[str, object]) -> list[Mapping[str, object]]:
    actors: dict[str, Mapping[str, object]] = {}
    for group in ("requirements", "user_stories", "scenarios"):
        for item in mappings(view.get(group)):
            references = mappings(item.get("user_twin_references"))
            for key in ("actor", "user_twin_reference"):
                actor = item.get(key)
                if isinstance(actor, Mapping):
                    references.append(actor)
            for actor in references:
                actors[str(actor.get("twin_id"))] = actor
    return list(actors.values())


def select_codes(
    view: Mapping[str, object], codes: Sequence[str]
) -> tuple[dict[str, object], list[str]]:
    groups = (
        "requirements",
        "user_stories",
        "acceptance_criteria",
        "scenarios",
        "needs",
        "journeys",
    )
    entries = {
        str(item.get("code")): item for group in groups for item in mappings(view.get(group))
    }
    wanted = {code.upper() for code in codes}
    selected = wanted & entries.keys()
    link_keys = (
        "requirement_codes",
        "user_story_codes",
        "acceptance_criterion_codes",
        "scenario_codes",
        "need_codes",
    )
    downstream = {
        "SCN": (("needs", "scenario_codes"),),
        "NED": (
            ("requirements", "need_codes"),
            ("user_stories", "need_codes"),
            ("journeys", "need_codes"),
        ),
        "REQ": (
            ("user_stories", "requirement_codes"),
            ("acceptance_criteria", "requirement_codes"),
        ),
        "USR": (("acceptance_criteria", "user_story_codes"),),
    }
    for prefix in ("SCN", "JRN", "NED", "REQ", "USR"):
        upstream = {code for code in selected if code.startswith(prefix + "-")}
        if prefix == "SCN":
            selected.update(
                str(item["code"])
                for item in mappings(view.get("journeys"))
                if item.get("scenario_code") in upstream
            )
        if prefix == "JRN":
            selected.update(
                linked
                for code in upstream
                for linked in entries[code].get("need_codes", [])
                if linked in entries
            )
        for group, key in downstream.get(prefix, ()):
            selected.update(
                str(item["code"])
                for item in mappings(view.get(group))
                if upstream & set(item.get(key, []))
            )
    while True:
        dependencies = {
            linked
            for code in selected
            for key in link_keys
            for linked in entries[code].get(key, [])
            if linked in entries
        }
        dependencies.update(
            linked for code in selected if (linked := entries[code].get("scenario_code")) in entries
        )
        expanded = selected | dependencies
        if expanded == selected:
            break
        selected = expanded
    result = {
        **view,
        **{
            group: [item for item in mappings(view.get(group)) if item.get("code") in selected]
            for group in groups
            if group in view
        },
    }
    result["actors"] = requirement_actors(result)
    return result, list(
        dict.fromkeys(code.upper() for code in codes if code.upper() not in entries)
    )


def design_view(document: Mapping[str, object]) -> DesignView:
    package = _mapping(document.get("package"))
    alternatives = tuple(mappings(package.get("alternatives")))
    selected = package.get("owner_selected_alternative_id")
    chosen = next(
        (
            item
            for item in alternatives
            if selected is not None and str(item.get("id")) == str(selected)
        ),
        None,
    )
    prototype = _mapping(package.get("prototype"))
    screens = _prototype_screens(prototype)
    if not screens:
        mockup = _mapping(_mapping(package.get("generated_mockup")).get("mockup"))
        screens = tuple(
            Screen(identifier="", code=code, title=_text(item.get("title")) or "", elements=())
            for item in mappings(mockup.get("screens"))
            if (code := _text(item.get("code")))
        )
    return DesignView(
        version_number=_number(document.get("version_number")),
        chosen=chosen,
        alternatives=alternatives,
        screens=screens,
        transitions=_transitions(prototype),
    )


def alternative_direction(alternative: Mapping[str, object]) -> Mapping[str, object] | None:
    direction = _mapping(alternative.get("visual_language")).get("direction")
    return direction if isinstance(direction, Mapping) else None


def markdown_files(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    found: list[str] = []
    for directory, children, names in os.walk(root):
        children.sort()
        for name in sorted(names):
            path = Path(directory) / name
            if (
                name in IGNORED_NAMES
                or not name.endswith(MARKDOWN_SUFFIX)
                or path.is_symlink()
                or not path.is_file()
            ):
                continue
            found.append(path.relative_to(root).as_posix())
    return sorted(found)


def markdown_text(root: Path, relative: str) -> str | None:
    if not relative.endswith(MARKDOWN_SUFFIX):
        return None
    path = inside(root, relative)
    if path is None or path.is_symlink() or not path.is_file():
        return None
    try:
        return path.read_bytes().decode("utf-8", "replace")
    except OSError:
        return None


def inside(root: Path, relative: str) -> Path | None:
    if not relative or any(character in relative for character in UNSAFE_CHARACTERS):
        return None
    parts = relative.split("/")
    if any(part in UNSAFE_PARTS for part in parts):
        return None
    candidate = root.joinpath(*parts)
    try:
        resolved = candidate.resolve()
        base = root.resolve()
    except (OSError, RuntimeError):
        return None
    return candidate if resolved.is_relative_to(base) else None


def mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def first_line(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return next((line.strip() for line in value.splitlines() if line.strip()), None)


def label(element: Mapping[str, object]) -> str | None:
    for name in ("accessible_name", "content"):
        found = element.get(name)
        if isinstance(found, str) and found.split():
            return " ".join(found.split())
    return None


def _prototype_screens(prototype: Mapping[str, object]) -> tuple[Screen, ...]:
    screens: list[Screen] = []
    for item in mappings(prototype.get("screens")):
        code = _text(item.get("code"))
        if code is None:
            continue
        labels = tuple(
            found for element in mappings(item.get("elements")) if (found := label(element))
        )
        screens.append(
            Screen(
                identifier=str(item.get("id") or ""),
                code=code,
                title=_text(item.get("title")) or "",
                elements=labels,
            )
        )
    return tuple(screens)


def _transitions(prototype: Mapping[str, object]) -> tuple[Transition, ...]:
    screens: dict[str, str] = {}
    elements: dict[str, str | None] = {}
    for item in mappings(prototype.get("screens")):
        code = _text(item.get("code"))
        if code is not None:
            screens[str(item.get("id"))] = code
        for element in mappings(item.get("elements")):
            elements[str(element.get("id"))] = label(element)
    found: list[Transition] = []
    for item in mappings(prototype.get("transitions")):
        code = _text(item.get("code"))
        if code is None:
            continue
        found.append(
            Transition(
                code=code,
                source=screens.get(str(item.get("source_screen_id"))),
                target=screens.get(str(item.get("target_screen_id"))),
                trigger=elements.get(str(item.get("trigger_element_id"))),
                outcome=_text(item.get("outcome")),
            )
        )
    return tuple(found)


def _json(path: Path, relative: str) -> object:
    try:
        return json.loads(path.read_bytes().decode("utf-8"), parse_constant=_refuse_constant)
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        raise FolderProblem(FOLDER_UNREADABLE, path=relative) from None


def _codes(value: object, codes: Mapping[str, str]) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [codes[str(item)] for item in value if str(item) in codes]


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _number(value: object) -> int | None:
    return value if _integer(value) else None


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _refuse_constant(value: str) -> object:
    raise ValueError(f"{value} is not JSON")
