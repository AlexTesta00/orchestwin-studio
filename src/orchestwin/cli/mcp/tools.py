from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs, jobs
from orchestwin.cli.api import twin_chat
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.flows.review import review_locale
from orchestwin.cli.flows.twin_conversation import model_failure
from orchestwin.cli.flows.twin_selection import OBSERVATION_PREFIX, Twin, matching, twins_from
from orchestwin.cli.mcp import knowledge
from orchestwin.cli.mcp.knowledge import FolderProblem, Knowledge
from orchestwin.cli.mcp.protocol import (
    RpcError,
    invalid_arguments,
    tool_failure,
    tool_result,
    unknown_tool,
)
from orchestwin.cli.messages import known, text
from orchestwin.cli.project import KNOWLEDGE_FOLDER, ProjectFolder

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.project import ProjectLink

PROJECT_STATE: Final = "project_state"
LIST_TWINS: Final = "list_twins"
GET_TWIN: Final = "get_twin"
GET_REQUIREMENTS: Final = "get_requirements"
GET_DESIGN: Final = "get_design"
GET_FEEDBACK: Final = "get_feedback"
ASK_TWIN: Final = "ask_twin"
REVIEW_CHANGES: Final = "review_changes"
TEXT: Final = "text"
TWIN: Final = "twin"
COUNT: Final = "count"
CODES: Final = "codes"
COMMIT: Final = "commit"
REVISION: Final = "revision"
HASH_PATTERN: Final = "^[0-9a-fA-F]{7,64}$"
REVISION_PATTERN: Final = "^(?:[0-9a-fA-F]{7,64}|HEAD)$"
HEAD: Final = "HEAD"
CODE_LENGTH: Final = 20
INVALID_KEYS: Final[Mapping[str, str]] = MappingProxyType(
    {
        TEXT: "mcp.argument_text",
        TWIN: "mcp.argument_twin",
        COUNT: "mcp.argument_count",
        CODES: "mcp.argument_codes",
        COMMIT: "mcp.argument_commit",
        REVISION: "mcp.argument_revision",
    }
)
SPEND_REQUIRED: Final = "SPEND_REQUIRED"
PROJECT_NOT_LINKED: Final = "PROJECT_NOT_LINKED"
STAGE_NOT_APPROVED: Final = "STAGE_NOT_APPROVED"
TWIN_NOT_FOUND: Final = "TWIN_NOT_FOUND"
TWIN_AMBIGUOUS: Final = "TWIN_AMBIGUOUS"
TWINS_NOT_APPROVED: Final = "TWINS_NOT_APPROVED"
SCREEN_NOT_FOUND: Final = "SCREEN_NOT_FOUND"
NO_GIT_REPOSITORY: Final = "NO_GIT_REPOSITORY"
NO_COMMIT: Final = "NO_COMMIT"
COMMIT_NOT_FOUND: Final = "COMMIT_NOT_FOUND"
INTERRUPTED: Final = "GENERATION_INTERRUPTED"
REVIEW_EXISTS: Final = "CODE_CHANGE_REVIEW_EXISTS"
ANSWER_FAILED_KEY: Final = "mcp.errors.TWIN_ANSWER_FAILED"
TWIN_CHAT: Final = "TWIN_CHAT"
CODE_CHANGE_REVIEW: Final = "CODE_CHANGE_REVIEW"
CODE_ALIGNMENT: Final = "CODE_ALIGNMENT"
DECIDE_WITH: Final = "ut align"
OPEN_TASK: Final = "OPEN"
REVIEW_LIMIT_SECONDS: Final = 900.0
COMMIT_LOOKBACK: Final = 50
SHORT_COMMIT: Final = 7
FAILURE_STATUS: Final = 400
INIT_COMMAND: Final = "`ut init`"
DESIGN_COMMAND: Final = "`ut design`"
ITALIAN: Final = "it"
ENGLISH: Final = "en"
TEXT_VALUE: Final = "TEXT"
ITEMS_VALUE: Final = "ITEMS"


class ToolError(Exception):
    def __init__(
        self,
        code: str,
        /,
        *,
        key: str | None = None,
        extra: Mapping[str, object] | None = None,
        **values: object,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.key = key
        self.extra: Mapping[str, object] = MappingProxyType(dict(extra or {}))
        self.values: Mapping[str, object] = MappingProxyType(dict(values))


@dataclass(frozen=True, slots=True)
class Session:
    context: CommandContext
    project: ProjectFolder
    link: ProjectLink
    language: str

    def knowledge(self) -> Knowledge:
        return knowledge.load(self.project.root / self.link.knowledge_folder)


@dataclass(frozen=True, slots=True)
class Parameter:
    name: str
    kind: str
    description: str
    required: bool = False
    minimum: int = 1
    maximum: int = 200
    default: int | None = None

    def schema(self, context: CommandContext) -> dict[str, object]:
        description = context.text(self.description)
        if self.kind == COUNT:
            return {
                "type": "integer",
                "minimum": self.minimum,
                "maximum": self.maximum,
                "default": self.default,
                "description": description,
            }
        if self.kind == CODES:
            return {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": CODE_LENGTH},
                "maxItems": self.maximum,
                "description": description,
            }
        if self.kind == COMMIT:
            return {"type": "string", "pattern": HASH_PATTERN, "description": description}
        if self.kind == REVISION:
            return {"type": "string", "pattern": REVISION_PATTERN, "description": description}
        return {
            "type": "string",
            "minLength": self.minimum,
            "maxLength": self.maximum,
            "description": description,
        }

    def parse(self, raw: object, tool: str) -> object:
        if self.kind == COUNT:
            return self._count(raw, tool)
        if self.kind == CODES:
            return self._codes(raw, tool)
        if self.kind == TWIN and _whole(raw):
            raw = str(raw)
        if not isinstance(raw, str):
            raise self.invalid(tool)
        value = " ".join(raw.split())
        if self.kind == REVISION and value.upper() == HEAD:
            return None
        if self.kind in (COMMIT, REVISION):
            if re.fullmatch(HASH_PATTERN, value) is None:
                raise self.invalid(tool)
            return value.lower()
        if not self.minimum <= len(value) <= self.maximum:
            raise self.invalid(tool)
        return value

    def invalid(self, tool: str) -> RpcError:
        return invalid_arguments(
            INVALID_KEYS[self.kind],
            tool=tool,
            name=self.name,
            minimum=self.minimum,
            maximum=self.maximum,
            length=CODE_LENGTH,
        )

    def _count(self, raw: object, tool: str) -> int:
        if isinstance(raw, float) and raw.is_integer():
            raw = int(raw)
        if not _whole(raw) or not self.minimum <= raw <= self.maximum:
            raise self.invalid(tool)
        return raw

    def _codes(self, raw: object, tool: str) -> tuple[str, ...]:
        if not isinstance(raw, list) or len(raw) > self.maximum:
            raise self.invalid(tool)
        codes: list[str] = []
        for item in raw:
            code = "".join(item.split()).upper() if isinstance(item, str) else ""
            if not 1 <= len(code) <= CODE_LENGTH:
                raise self.invalid(tool)
            codes.append(code)
        return tuple(codes)


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    title: str
    description: str
    run: Callable[[Session, Mapping[str, object]], dict[str, object]]
    parameters: tuple[Parameter, ...] = ()
    paid: bool = False

    def input_schema(self, context: CommandContext) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {item.name: item.schema(context) for item in self.parameters},
            "required": [item.name for item in self.parameters if item.required],
            "additionalProperties": False,
        }

    def listed(self, context: CommandContext, *, spend: bool) -> dict[str, object]:
        key = self.description
        if self.name == REVIEW_CHANGES and review_estimate(1) is None:
            key = "mcp.describe_review_changes_plain"
        description = context.text(key, **prices(context.language))
        if self.paid and not spend:
            description = f"{description} {context.text('mcp.describe_disabled')}"
        return {
            "name": self.name,
            "title": context.text(self.title),
            "description": description,
            "inputSchema": self.input_schema(context),
            "annotations": {
                "readOnlyHint": not self.paid,
                "destructiveHint": False,
                "idempotentHint": not self.paid,
                "openWorldHint": self.paid,
            },
        }

    def arguments(self, raw: object) -> dict[str, object]:
        given = {} if raw is None else raw
        if not isinstance(given, dict):
            raise invalid_arguments("mcp.argument_object", tool=self.name)
        names = {item.name for item in self.parameters}
        for name in given:
            if name not in names:
                raise invalid_arguments("mcp.argument_unknown", tool=self.name, name=str(name))
        values: dict[str, object] = {}
        for item in self.parameters:
            found = given.get(item.name)
            if found is None:
                if item.required:
                    raise invalid_arguments("mcp.argument_missing", tool=self.name, name=item.name)
                values[item.name] = item.default
            else:
                values[item.name] = item.parse(found, self.name)
        return values


class Tools:
    def __init__(self, context: CommandContext, *, spend: bool) -> None:
        self._context = context
        self._spend = spend

    def definitions(self) -> list[dict[str, object]]:
        return [tool.listed(self._context, spend=self._spend) for tool in TOOLS]

    def call(self, name: object, arguments: object) -> dict[str, object]:
        tool = TOOLS_BY_NAME.get(name) if isinstance(name, str) else None
        if tool is None:
            raise unknown_tool(name, [item.name for item in TOOLS])
        values = tool.arguments(arguments)
        session: Session | None = None
        try:
            session = open_session(self._context)
            if tool.paid and not self._spend:
                raise ToolError(SPEND_REQUIRED, tool=tool.name, extra={"tool": tool.name})
            document = tool.run(session, values)
        except (ToolError, FolderProblem, CliError) as error:
            if isinstance(error, CliError) and error.code == INTERRUPTED:
                raise KeyboardInterrupt from None
            return self._failure(error, session)
        return tool_result(document)

    def _failure(
        self, error: ToolError | FolderProblem | CliError, session: Session | None
    ) -> dict[str, object]:
        language = self._context.language if session is None else session.language
        if isinstance(error, FolderProblem):
            folder = KNOWLEDGE_FOLDER if session is None else session.link.knowledge_folder
            path = error.values.get("path")
            values = {**error.values, "path": f"{folder}/{path}" if path else f"{folder}/"}
            return tool_failure(error.code, sentence(error.code, None, values, language))
        if isinstance(error, ToolError):
            written = sentence(error.code, error.key, error.values, language)
            return failure_with(tool_failure(error.code, written), error.extra)
        status = error.http_status if isinstance(error, ApiFailure) else None
        written = sentence(error.code, None, error.values, language, http_status=status)
        return tool_failure(error.code, written)


def open_session(context: CommandContext) -> Session:
    project = ProjectFolder.find(context.directory)
    if project is None:
        raise ToolError(PROJECT_NOT_LINKED)
    link = project.link()
    return Session(
        context=context,
        project=project,
        link=link,
        language=project_language(link.language, context.language),
    )


def project_language(value: str | None, fallback: str) -> str:
    chosen = value if value and value.strip() else fallback
    return ITALIAN if chosen.strip().lower().startswith(ITALIAN) else ENGLISH


def sentence(
    code: str,
    key: str | None,
    values: Mapping[str, object],
    language: str,
    *,
    http_status: int | None = None,
) -> str:
    candidates = [] if key is None else [key]
    reason = values.get("reason")
    if isinstance(reason, str) and reason:
        candidates.extend((f"mcp.errors.{code}.{reason}", f"errors.{code}.{reason}"))
    candidates.extend((f"mcp.errors.{code}", f"errors.{code}"))
    chosen = next((candidate for candidate in candidates if known(candidate)), None)
    filled = dict(values)
    if chosen is None:
        chosen = "errors.UNKNOWN" if http_status is None else "errors.API_FAILURE"
        filled = {**filled, "code": code, "http_status": http_status}
    written = text(chosen, language, **filled)
    return written if code in written else f"{written} ({code})"


def failure_with(result: dict[str, object], extra: Mapping[str, object]) -> dict[str, object]:
    if not extra:
        return result
    structured = result["structuredContent"]
    return {**result, "structuredContent": {**structured, **extra}}


def prices(language: str) -> dict[str, str]:
    chat = costs.estimate([TWIN_CHAT])
    values = {"amount": costs.amount_text(chat, language)}
    if review_estimate(1) is not None:
        values["review"] = costs.amount_text(costs.estimate([CODE_CHANGE_REVIEW]), language)
        values["alignment"] = costs.amount_text(costs.estimate([CODE_ALIGNMENT]), language)
    return values


def review_estimate(twins: int) -> costs.Estimate | None:
    if CODE_CHANGE_REVIEW not in costs.ESTIMATES or CODE_ALIGNMENT not in costs.ESTIMATES:
        return None
    return costs.estimate([CODE_CHANGE_REVIEW] * max(twins, 0) + [CODE_ALIGNMENT])


def stage_name(stage: str, language: str) -> str:
    return text(f"common.stage_{stage}", language)


def stage_command(stage: str) -> str:
    return DESIGN_COMMAND if stage == "design" else INIT_COMMAND


def stage_missing(session: Session, stage: str) -> ToolError:
    return ToolError(
        STAGE_NOT_APPROVED,
        stage=stage_name(stage, session.language),
        command=stage_command(stage),
        extra={"stage": stage},
    )


def project_state(session: Session, values: Mapping[str, object]) -> dict[str, object]:
    link = session.link
    document: dict[str, object] = {
        "project": {
            "id": link.project_id,
            "name": link.project_name,
            "mode": link.mode,
            "language": link.language,
            "studio": link.studio,
        },
        "folder": None,
        "reference": None,
        "aligned": None,
        "pending_changes": [],
        "open_tasks": [],
    }
    try:
        found = session.knowledge()
    except FolderProblem as problem:
        if problem.code != knowledge.FOLDER_MISSING:
            raise
        return {**document, "next": text("mcp.next_no_folder", session.language)}
    state = found.state()
    changes = [] if state is None else knowledge.mappings(state.get("changes"))
    aligned = None if state is None else _mapping_or_none(state.get("aligned"))
    pending = pending_changes(changes, aligned)
    tasks = (
        []
        if state is None
        else [
            dict(task)
            for task in knowledge.mappings(state.get("tasks"))
            if task.get("status") == OPEN_TASK
        ]
    )
    return {
        **document,
        "folder": {
            "schema_version": found.schema_version,
            "version_number": found.version_number,
            "approved_stages": list(found.approved),
            "pending_stage": found.pending,
            "complete": found.complete,
        },
        "reference": None if state is None else _mapping_or_none(state.get("reference")),
        "aligned": aligned,
        "pending_changes": pending,
        "open_tasks": tasks,
        "next": next_step(session.language, found, state, changes, pending, tasks, aligned),
    }


def pending_changes(
    changes: Sequence[Mapping[str, object]], aligned: Mapping[str, object] | None
) -> list[dict[str, object]]:
    commit = None if aligned is None else aligned.get("commit")
    found: list[dict[str, object]] = []
    for change in changes:
        if commit is not None and change.get("commit") == commit:
            break
        review = change.get("review")
        decision = change.get("decision")
        files = change.get("files")
        found.append(
            {
                "commit": change.get("commit"),
                "committed_at": change.get("committed_at"),
                "message": knowledge.first_line(change.get("message")),
                "files": len(files) if isinstance(files, list) else 0,
                "verdict": review.get("verdict") if isinstance(review, Mapping) else None,
                "decision": decision.get("kind") if isinstance(decision, Mapping) else None,
            }
        )
    return found


def next_step(
    language: str,
    found: Knowledge,
    state: Mapping[str, object] | None,
    changes: Sequence[Mapping[str, object]],
    pending: Sequence[Mapping[str, object]],
    tasks: Sequence[Mapping[str, object]],
    aligned: Mapping[str, object] | None,
) -> str:
    if found.pending is not None:
        return text(
            "mcp.next_stage",
            language,
            stage=stage_name(found.pending, language),
            command=stage_command(found.pending),
        )
    if state is None:
        return text("mcp.next_no_state", language)
    undecided = [item for item in pending if item.get("decision") is None]
    if undecided:
        return text("mcp.next_pending", language, count=len(undecided))
    if tasks:
        codes = ", ".join(str(task.get("code") or "-") for task in tasks)
        return text("mcp.next_tasks", language, count=len(tasks), codes=codes)
    if aligned is not None:
        commit = str(aligned.get("commit") or "")[:SHORT_COMMIT]
        return text("mcp.next_aligned", language, commit=commit)
    if changes:
        return text("mcp.next_undecided", language)
    return text("mcp.next_start", language)


def list_twins(session: Session, values: Mapping[str, object]) -> dict[str, object]:
    return {
        "twins": [
            {
                "number": twin.number,
                "twin_id": twin.twin_id,
                "name": twin.name,
                "role": twin.role,
                "wants": twin.wants,
            }
            for twin in folder_twins(session)
        ]
    }


def get_twin(session: Session, values: Mapping[str, object]) -> dict[str, object]:
    twin = pick(folder_twins(session), str(values["twin"]))
    observations: dict[str, object] = {}
    for item in twin.observations:
        key = item.get("observation_key")
        if isinstance(key, str) and key.startswith(OBSERVATION_PREFIX):
            observations[key.removeprefix(OBSERVATION_PREFIX)] = {
                "value": observation_value(item),
                "status": item.get("epistemic_status"),
            }
    return {
        "twin": {
            "number": twin.number,
            "twin_id": twin.twin_id,
            "name": twin.name,
            "role": twin.role,
            "goals": list(twin.values("goals")),
            "frustrations": list(twin.values("frustrations")),
            "pain_points": list(twin.values("pain_points")),
            "context_of_use": list(twin.values("context_of_use")),
            "observations": observations,
        }
    }


def get_requirements(session: Session, values: Mapping[str, object]) -> dict[str, object]:
    document = session.knowledge().stage("requirements")
    if document is None:
        raise stage_missing(session, "requirements")
    view = knowledge.requirements_view(document)
    codes = values.get("codes")
    if not isinstance(codes, tuple) or not codes:
        return view
    selected, unknown = knowledge.select_codes(view, codes)
    return {**selected, "unknown_codes": unknown}


def get_design(session: Session, values: Mapping[str, object]) -> dict[str, object]:
    document = session.knowledge().stage("design")
    if document is None:
        raise stage_missing(session, "design")
    view = knowledge.design_view(document)
    chosen = view.chosen
    screens = [] if chosen is None else list(view.screens)
    wanted = values.get("screen")
    if isinstance(wanted, str):
        found = next((item for item in screens if item.code.upper() == wanted.upper()), None)
        if found is None:
            codes = [item.code for item in screens]
            raise ToolError(
                SCREEN_NOT_FOUND,
                screen=wanted,
                screens=", ".join(codes) or "-",
                extra={"screens": codes},
            )
        listed = [
            {
                **screen_entry(found),
                "transitions": [move.document() for move in view.moves(found.code)],
            }
        ]
    else:
        listed = [screen_entry(item) for item in screens]
    return {
        "version_number": view.version_number,
        "chosen": None
        if chosen is None
        else {
            "code": chosen.get("code"),
            "title": chosen.get("title"),
            "summary": chosen.get("summary"),
            "workflows": [
                {"code": flow.get("code"), "steps": _texts(flow.get("steps"))}
                for flow in knowledge.mappings(chosen.get("workflows"))
            ],
            "screens": listed,
        },
        "alternatives": [
            {"code": item.get("code"), "title": item.get("title"), "chosen": item is chosen}
            for item in view.alternatives
        ],
    }


def get_feedback(session: Session, values: Mapping[str, object]) -> dict[str, object]:
    found = session.knowledge()
    runs = found.change_runs()
    commit = values.get("commit")
    if isinstance(commit, str):
        runs = [run for run in runs if str(run.get("commit") or "").lower().startswith(commit)]
    limit = values.get("limit")
    count = limit if isinstance(limit, int) else len(runs)
    return {"runs": [dict(run) for run in runs[:count]], "design_reviews": found.design_reviews()}


def ask_twin(session: Session, values: Mapping[str, object]) -> dict[str, object]:
    project_id = session.link.project_id
    client = session.context.client()
    if not twin_chat.approved(twin_chat.readiness(client, project_id)):
        raise ToolError(TWINS_NOT_APPROVED)
    snapshot = twin_chat.current_snapshot(client, project_id)
    if snapshot is None:
        raise ToolError(TWINS_NOT_APPROVED)
    twin = pick(twins_from(twin_chat.twin_versions(snapshot)), str(values["twin"]))
    question = str(values["question"])
    existing = twin_chat.turns(
        twin_chat.conversation(client, project_id, twin.twin_id), twin.version_id
    )
    try:
        recorded = twin_chat.ask(
            client, project_id, twin.twin_id, question, expected_turn_count=len(existing)
        )
    except ApiFailure as failure:
        if model_failure(failure):
            raise ToolError(
                failure.code, key=ANSWER_FAILED_KEY, name=twin.name, code=failure.code
            ) from None
        raise
    turns = twin_chat.turns(recorded)
    last: Mapping[str, object] = turns[-1] if turns else {}
    estimate = costs.estimate([TWIN_CHAT])
    return {
        "twin": twin.name,
        "reply": twin_chat.turn_reply(last),
        "insights": [dict(item) for item in knowledge.mappings(last.get("insights"))],
        "estimated_usd": [estimate.low_usd, estimate.high_usd],
    }


def review_changes(session: Session, values: Mapping[str, object]) -> dict[str, object]:
    from orchestwin.cli.api import changes as changes_api
    from orchestwin.cli.flows import changes as git

    context = session.context
    link = session.link
    root = git.repository_root(context, session.project.root)
    if root is None:
        raise ToolError(NO_GIT_REPOSITORY, folder=str(session.project.root))
    wanted = values.get("commit")
    commit = find_commit(context, git, root, wanted if isinstance(wanted, str) else None)
    client = context.client()
    body = git.change_body(commit, git.diff_of(context, root, commit))
    status, document = changes_api.record(client, link.project_id, body)
    if status >= FAILURE_STATUS:
        raise changes_api.failure(status, document)
    result = jobs.generate(
        context,
        client,
        link.project_id,
        changes_api.review_path(link.project_id, commit.hash),
        changes_api.review_body(review_locale(link.language or context.language), False),
        label=context.text("mcp.label_review", commit=commit.hash[:SHORT_COMMIT]),
        limit_seconds=REVIEW_LIMIT_SECONDS,
    )
    reused = changes_api.code_of(result.body) == changes_api.REVIEW_EXISTS
    if reused:
        run = latest_run(changes_api.reviews(client, link.project_id, commit.hash))
    elif result.status_code >= FAILURE_STATUS:
        raise changes_api.failure(result.status_code, result.body)
    else:
        run = reviewed_run(result.body, result.status_code)
    answer: dict[str, object] = {**run, "reused": reused, "decide_with": DECIDE_WITH}
    estimate = review_estimate(len(knowledge.mappings(run.get("critiques"))))
    if estimate is not None:
        answer["estimated_usd"] = [estimate.low_usd, estimate.high_usd]
    return answer


def find_commit(context: CommandContext, git: ModuleType, root: Path, wanted: str | None) -> object:
    full = git.head(context, root) if wanted is None else git.resolve(context, root, wanted)
    if full is None and wanted is None:
        raise ToolError(NO_COMMIT)
    parent = None if full is None else git.resolve(context, root, f"{full}^")
    found = (
        None
        if full is None
        else next(
            (
                commit
                for commit in git.commits_after(context, root, parent, limit=COMMIT_LOOKBACK)
                if commit.hash == full
            ),
            None,
        )
    )
    if found is None:
        raise ToolError(COMMIT_NOT_FOUND, commit=wanted or HEAD, limit=COMMIT_LOOKBACK)
    return found


def latest_run(runs: Sequence[Mapping[str, object]]) -> Mapping[str, object]:
    found = knowledge.mappings(list(runs))
    if not found:
        raise ApiFailure(REVIEW_EXISTS, http_status=409)
    return found[0]


def reviewed_run(body: object, status: int) -> Mapping[str, object]:
    run = body.get("run") if isinstance(body, Mapping) else None
    if not isinstance(run, Mapping):
        raise ApiFailure("API_FAILURE", http_status=status)
    return run


def folder_twins(session: Session) -> tuple[Twin, ...]:
    twins = session.knowledge().twins()
    if twins is None:
        raise stage_missing(session, "twins")
    return twins


def pick(twins: Sequence[Twin], value: str) -> Twin:
    found = matching(twins, value)
    if len(found) == 1:
        return found[0]
    listed = found or twins
    roster = [{"number": twin.number, "name": twin.name} for twin in listed]
    names = "; ".join(f"{twin.number}. {twin.name}" for twin in listed) or "-"
    code = TWIN_AMBIGUOUS if found else TWIN_NOT_FOUND
    raise ToolError(code, value=value, twins=names, extra={"twins": roster})


def observation_value(item: Mapping[str, object]) -> object:
    value = item.get("value")
    if not isinstance(value, Mapping):
        return None
    if value.get("kind") == TEXT_VALUE:
        found = value.get("text")
        return found.strip() if isinstance(found, str) and found.strip() else None
    if value.get("kind") == ITEMS_VALUE:
        return _texts(value.get("items"))
    return None


def screen_entry(screen: knowledge.Screen) -> dict[str, object]:
    return {"code": screen.code, "title": screen.title, "elements": list(screen.elements)}


def _texts(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _mapping_or_none(value: object) -> dict[str, object] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


TWIN_PARAMETER: Final = Parameter(TWIN, TWIN, "mcp.parameter_twin", required=True)
TOOLS: Final = (
    Tool(
        PROJECT_STATE,
        "mcp.title_project_state",
        "mcp.describe_project_state",
        project_state,
    ),
    Tool(LIST_TWINS, "mcp.title_list_twins", "mcp.describe_list_twins", list_twins),
    Tool(
        GET_TWIN,
        "mcp.title_get_twin",
        "mcp.describe_get_twin",
        get_twin,
        (TWIN_PARAMETER,),
    ),
    Tool(
        GET_REQUIREMENTS,
        "mcp.title_get_requirements",
        "mcp.describe_get_requirements",
        get_requirements,
        (Parameter(CODES, CODES, "mcp.parameter_codes", maximum=50),),
    ),
    Tool(
        GET_DESIGN,
        "mcp.title_get_design",
        "mcp.describe_get_design",
        get_design,
        (Parameter("screen", TEXT, "mcp.parameter_screen", maximum=CODE_LENGTH),),
    ),
    Tool(
        GET_FEEDBACK,
        "mcp.title_get_feedback",
        "mcp.describe_get_feedback",
        get_feedback,
        (
            Parameter(COMMIT, COMMIT, "mcp.parameter_feedback_commit"),
            Parameter("limit", COUNT, "mcp.parameter_limit", maximum=20, default=3),
        ),
    ),
    Tool(
        ASK_TWIN,
        "mcp.title_ask_twin",
        "mcp.describe_ask_twin",
        ask_twin,
        (
            TWIN_PARAMETER,
            Parameter(
                "question",
                TEXT,
                "mcp.parameter_question",
                required=True,
                maximum=twin_chat.QUESTION_LIMIT,
            ),
        ),
        paid=True,
    ),
    Tool(
        REVIEW_CHANGES,
        "mcp.title_review_changes",
        "mcp.describe_review_changes",
        review_changes,
        (Parameter(COMMIT, REVISION, "mcp.parameter_review_commit"),),
        paid=True,
    ),
)
TOOLS_BY_NAME: Final[Mapping[str, Tool]] = MappingProxyType({tool.name: tool for tool in TOOLS})
