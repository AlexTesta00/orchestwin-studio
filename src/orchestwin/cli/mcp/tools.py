from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs, jobs
from orchestwin.cli.api import twin_chat
from orchestwin.cli.context import CommandContext
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.flows import code_order
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

    from orchestwin.cli.project import ProjectLink

PROJECT_STATE: Final = "project_state"
LIST_TWINS: Final = "list_twins"
GET_TWIN: Final = "get_twin"
GET_REQUIREMENTS: Final = "get_requirements"
GET_DESIGN: Final = "get_design"
GET_FEEDBACK: Final = "get_feedback"
ASK_TWIN: Final = "ask_twin"
REVIEW_CHANGES: Final = "review_changes"
GET_TEST_RESULTS: Final = "get_test_results"
RUN_TESTS: Final = "run_tests"
GET_TASKS: Final = "get_tasks"
GET_EVIDENCE: Final = "get_evidence"
TEXT: Final = "text"
TWIN: Final = "twin"
COUNT: Final = "count"
CODES: Final = "codes"
COMMIT: Final = "commit"
REVISION: Final = "revision"
CRITERIA: Final = "criteria"
APPLICATION: Final = "application"
BROWSER: Final = "browser"
FLAG: Final = "flag"
REVIEW: Final = "review"
NEW_PLAN: Final = "new_plan"
STATUS: Final = "status"
OPEN_TASKS: Final = "open"
ALL_TASKS: Final = "all"
TASK_FILTERS: Final = (OPEN_TASKS, ALL_TASKS)
HASH_PATTERN: Final = "^[0-9a-fA-F]{7,64}$"
REVISION_PATTERN: Final = "^(?:[0-9a-fA-F]{7,64}|HEAD)$"
HEAD: Final = "HEAD"
CODE_LENGTH: Final = 20
APPLICATION_FIELDS: Final = ("kind", "address")
APPLICATION_KINDS: Final = ("URL", "STATIC")
ALL_BROWSERS: Final = "all"
BROWSER_CHOICES: Final = ("chrome", "firefox", ALL_BROWSERS)
ADDRESS_LENGTH: Final = 500
CRITERIA_LIMIT: Final = 20
TEST_RESULTS_LIMIT: Final = 20
INVALID_KEYS: Final[Mapping[str, str]] = MappingProxyType(
    {
        TEXT: "mcp.argument_text",
        TWIN: "mcp.argument_twin",
        COUNT: "mcp.argument_count",
        CODES: "mcp.argument_codes",
        COMMIT: "mcp.argument_commit",
        REVISION: "mcp.argument_revision",
        CRITERIA: "mcp.argument_criteria",
        APPLICATION: "mcp.argument_application",
        BROWSER: "mcp.argument_browser",
        FLAG: "mcp.argument_flag",
        STATUS: "mcp.argument_status",
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
TEST_PLAN: Final = "TEST_PLAN"
TEST_REVIEW: Final = "TEST_REVIEW"
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

    @property
    def knowledge_root(self) -> Path:
        return self.project.root / self.link.knowledge_folder

    def knowledge(self) -> Knowledge:
        return knowledge.load(self.knowledge_root)


@dataclass(frozen=True, slots=True)
class Parameter:
    name: str
    kind: str
    description: str
    required: bool = False
    minimum: int = 1
    maximum: int = 200
    default: int | str | None = None

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
        if self.kind == CRITERIA:
            return {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": CODE_LENGTH},
                "minItems": self.minimum,
                "maxItems": self.maximum,
                "description": description,
            }
        if self.kind == APPLICATION:
            return {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(APPLICATION_KINDS)},
                    "address": {"type": "string", "minLength": 1, "maxLength": self.maximum},
                },
                "required": list(APPLICATION_FIELDS),
                "additionalProperties": False,
                "description": description,
            }
        if self.kind == BROWSER:
            return {"type": "string", "enum": list(BROWSER_CHOICES), "description": description}
        if self.kind == STATUS:
            return {
                "type": "string",
                "enum": list(TASK_FILTERS),
                "default": self.default,
                "description": description,
            }
        if self.kind == FLAG:
            return {"type": "boolean", "default": self.default, "description": description}
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
        if self.kind == CRITERIA:
            return self._criteria(raw, tool)
        if self.kind == APPLICATION:
            return self._application(raw, tool)
        if self.kind == FLAG:
            if not isinstance(raw, bool):
                raise self.invalid(tool)
            return raw
        if self.kind == TWIN and _whole(raw):
            raw = str(raw)
        if not isinstance(raw, str):
            raise self.invalid(tool)
        value = " ".join(raw.split())
        if self.kind in (BROWSER, STATUS):
            choices = BROWSER_CHOICES if self.kind == BROWSER else TASK_FILTERS
            if value.lower() not in choices:
                raise self.invalid(tool)
            return value.lower()
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

    def _criteria(self, raw: object, tool: str) -> tuple[str, ...]:
        codes = self._codes(raw, tool)
        if len(codes) < self.minimum:
            raise self.invalid(tool)
        return tuple(dict.fromkeys(codes))

    def _application(self, raw: object, tool: str) -> dict[str, str]:
        if not isinstance(raw, dict) or set(raw) != set(APPLICATION_FIELDS):
            raise self.invalid(tool)
        kind, address = raw["kind"], raw["address"]
        if not isinstance(kind, str) or not isinstance(address, str):
            raise self.invalid(tool)
        kind, address = kind.strip().upper(), address.strip()
        if kind not in APPLICATION_KINDS or not 1 <= len(address) <= self.maximum:
            raise self.invalid(tool)
        return {"kind": kind, "address": address}


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
        figures = acceptance_prices(context.language) if self.name == RUN_TESTS else None
        if figures is not None:
            estimate = context.text("mcp.describe_run_tests_estimate", **figures)
            description = f"{description} {estimate}"
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
            return self._failure(error, session, tool.name)
        return tool_result(document)

    def _failure(
        self, error: ToolError | FolderProblem | CliError, session: Session | None, tool: str
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
        written = sentence(
            error.code,
            f"mcp.errors.{tool}.{error.code}",
            error.values,
            language,
            http_status=status,
        )
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
        language=project_language(project, context.language),
    )


def project_language(project: ProjectFolder | None, fallback: str) -> str:
    chosen = fallback if project is None else code_order.project_language(project, fallback)
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


def acceptance_prices(language: str) -> dict[str, str] | None:
    if TEST_PLAN not in costs.ESTIMATES or TEST_REVIEW not in costs.ESTIMATES:
        return None
    return {
        "plan": costs.amount_text(costs.estimate([TEST_PLAN]), language),
        "review": costs.amount_text(costs.estimate([TEST_REVIEW]), language),
    }


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
        "stale_reviews": 0,
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
        "stale_reviews": found.stale_reviews(),
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
    found = session.knowledge()
    twins = folder_twins(session, found)
    learned = learned_entries(found)
    return {
        "twins": [
            {
                "number": twin.number,
                "twin_id": twin.twin_id,
                "name": twin.name,
                "role": twin.role,
                "wants": twin.wants,
                "label": twin_label(twin, learned.get(twin.twin_id)),
                "learned_observations": learned_count(learned.get(twin.twin_id)),
            }
            for twin in twins
        ]
    }


def get_twin(session: Session, values: Mapping[str, object]) -> dict[str, object]:
    found = session.knowledge()
    twin = pick(folder_twins(session, found), str(values["twin"]))
    entry = learned_entries(found).get(twin.twin_id)
    observations: dict[str, object] = {}
    for item in twin.observations:
        key = item.get("observation_key")
        if isinstance(key, str) and key.startswith(OBSERVATION_PREFIX):
            observations[key.removeprefix(OBSERVATION_PREFIX)] = {
                "value": observation_value(item),
                "status": item.get("epistemic_status"),
            }
    result = {
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
        },
        "learned": None if entry is None else _plain(entry),
    }
    evidence = found.evidence()
    if evidence is not None:
        result["evidence"] = {
            "citations": [
                _plain(item)
                for item in knowledge.mappings(evidence.get("citations"))
                if item.get("twin_id") == twin.twin_id
            ],
            "sources": [_plain(item) for item in knowledge.mappings(evidence.get("evidence"))],
        }
        for item in twin.observations:
            key = item.get("observation_key")
            if isinstance(key, str) and key.startswith(OBSERVATION_PREFIX):
                observations[key.removeprefix(OBSERVATION_PREFIX)]["provenance"] = _plain(
                    item.get("provenance", [])
                )
    return result


def get_evidence(session: Session, values: Mapping[str, object]) -> dict[str, object]:
    document = session.knowledge().evidence()
    if document is None:
        return {"evidence": [], "citations": [], "original_text_included": False}
    sources = knowledge.mappings(document.get("evidence"))
    code = values.get("code")
    if isinstance(code, str):
        sources = [
            item for item in sources if str(item.get("code", "")).casefold() == code.casefold()
        ]
    keys = {(item.get("id"), item.get("version")) for item in sources}
    citations = [
        item
        for item in knowledge.mappings(document.get("citations"))
        if (
            item.get("citation", {}).get("source_id"),
            item.get("citation", {}).get("source_version"),
        )
        in keys
    ]
    return {
        "evidence": [_plain(item) for item in sources],
        "citations": [_plain(item) for item in citations],
        "original_text_included": False,
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
        changes_api.review_body(review_locale(session.language), False),
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


def get_test_results(session: Session, values: Mapping[str, object]) -> dict[str, object]:
    runs = knowledge.test_runs(session.knowledge_root)
    limit = values.get("limit")
    count = limit if isinstance(limit, int) else 1
    return {"runs": [_plain(run) for run in runs[:count]]}


def get_tasks(session: Session, values: Mapping[str, object]) -> dict[str, object]:
    tasks = knowledge.tasks(session.knowledge_root)
    every = values.get(STATUS) == ALL_TASKS
    return {"tasks": [_plain(task) for task in tasks if every or task.get("status") == OPEN_TASK]}


def run_tests(session: Session, values: Mapping[str, object]) -> dict[str, object]:
    from orchestwin.cli.flows import test_run

    browser = values.get(BROWSER)
    criteria = values.get(CRITERIA)
    request = test_run.TestRequest(
        application=values.get(APPLICATION),
        browsers=(browser,) if isinstance(browser, str) else (ALL_BROWSERS,),
        criteria=criteria if isinstance(criteria, tuple) else (),
        new_plan=values.get(NEW_PLAN) is True,
        review=values.get(REVIEW) is not False,
    )
    outcome = test_run.execute(spending_context(session.context), request)
    return {
        "run": _plain(outcome.run),
        "critiques": [_plain(item) for item in outcome.critiques],
        "report": str(outcome.report),
        "folder": str(outcome.folder),
    }


def spending_context(context: CommandContext) -> CommandContext:
    return CommandContext(
        context.environment,
        context.console,
        language=context.language,
        assume_yes=True,
        debug=context.debug,
        directory=context.directory,
        sessions=context.sessions,
    )


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


def folder_twins(session: Session, found: Knowledge | None = None) -> tuple[Twin, ...]:
    twins = (session.knowledge() if found is None else found).twins()
    if twins is None:
        raise stage_missing(session, "twins")
    return twins


def learned_entries(found: Knowledge) -> dict[str, Mapping[str, object]]:
    return {
        entry["twin_id"]: entry
        for entry in found.learning()
        if isinstance(entry.get("twin_id"), str)
    }


def twin_label(twin: Twin, entry: Mapping[str, object] | None) -> str | None:
    label = None if entry is None else entry.get("label")
    if isinstance(label, str) and label.strip():
        return label
    return None if twin.version_number is None else str(twin.version_number)


def learned_count(entry: Mapping[str, object] | None) -> int:
    return 0 if entry is None else len(knowledge.mappings(entry.get("observations")))


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


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


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
    Tool(
        GET_TEST_RESULTS,
        "mcp.title_get_test_results",
        "mcp.describe_get_test_results",
        get_test_results,
        (
            Parameter(
                "limit", COUNT, "mcp.parameter_test_limit", maximum=TEST_RESULTS_LIMIT, default=1
            ),
        ),
    ),
    Tool(
        RUN_TESTS,
        "mcp.title_run_tests",
        "mcp.describe_run_tests",
        run_tests,
        (
            Parameter(
                APPLICATION, APPLICATION, "mcp.parameter_application", maximum=ADDRESS_LENGTH
            ),
            Parameter(BROWSER, BROWSER, "mcp.parameter_browser"),
            Parameter(CRITERIA, CRITERIA, "mcp.parameter_criteria", maximum=CRITERIA_LIMIT),
            Parameter(REVIEW, FLAG, "mcp.parameter_review", default=True),
            Parameter(NEW_PLAN, FLAG, "mcp.parameter_new_plan", default=False),
        ),
        paid=True,
    ),
    Tool(
        GET_TASKS,
        "mcp.title_get_tasks",
        "mcp.describe_get_tasks",
        get_tasks,
        (Parameter(STATUS, STATUS, "mcp.parameter_task_status", default=OPEN_TASKS),),
    ),
    Tool(
        GET_EVIDENCE,
        "mcp.title_get_evidence",
        "mcp.describe_get_evidence",
        get_evidence,
        (Parameter("code", TEXT, "mcp.parameter_evidence_code", maximum=CODE_LENGTH),),
    ),
)
TOOLS_BY_NAME: Final[Mapping[str, Tool]] = MappingProxyType({tool.name: tool for tool in TOOLS})
