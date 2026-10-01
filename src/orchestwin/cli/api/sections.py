from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import projects as project_api
from orchestwin.cli.errors import ApiFailure

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient

BRIEF: Final = "BRIEF"
TEAM: Final = "TEAM"
USER_TWINS: Final = "USER_TWINS"
REQUIREMENTS: Final = "REQUIREMENTS"
DESIGN: Final = "DESIGN"
PACKAGE: Final = "PACKAGE"
SECTION_KEYS: Final = (BRIEF, TEAM, USER_TWINS, REQUIREMENTS, DESIGN, PACKAGE)
ALIGNABLE: Final = (USER_TWINS, REQUIREMENTS, DESIGN)
UPSTREAM: Final = (TEAM, *ALIGNABLE)
NOT_STARTED: Final = "NOT_STARTED"
IN_PROGRESS: Final = "IN_PROGRESS"
FINE: Final = "FINE"
UPDATE_AVAILABLE: Final = "UPDATE_AVAILABLE"
TO_UPDATE: Final = "TO_UPDATE"
STATES: Final = (NOT_STARTED, IN_PROGRESS, FINE, UPDATE_AVAILABLE, TO_UPDATE)
BRIEF_CHANGED: Final = "BRIEF_CHANGED"
PERSPECTIVES_CHANGED: Final = "PERSPECTIVES_CHANGED"
USER_TWINS_CHANGED: Final = "USER_TWINS_CHANGED"
REQUIREMENTS_CHANGED: Final = "REQUIREMENTS_CHANGED"
FOLDER_BEHIND: Final = "FOLDER_BEHIND"
BEHIND_REASONS: Final = (
    BRIEF_CHANGED,
    PERSPECTIVES_CHANGED,
    USER_TWINS_CHANGED,
    REQUIREMENTS_CHANGED,
    FOLDER_BEHIND,
)
TWINS_LEARNED: Final = "TWINS_LEARNED"
REQUIREMENTS_NOT_COVERED: Final = "REQUIREMENTS_NOT_COVERED"
EVALUATION_MISSING: Final = "EVALUATION_MISSING"
MATERIAL_REASONS: Final = (TWINS_LEARNED, REQUIREMENTS_NOT_COVERED, EVALUATION_MISSING)
REQUIREMENT_NO_LONGER_AVAILABLE: Final = "REQUIREMENT_NO_LONGER_AVAILABLE"
TWIN_SET_CHANGED: Final = "TWIN_SET_CHANGED"
TWIN_NO_LONGER_AVAILABLE: Final = "TWIN_NO_LONGER_AVAILABLE"
REVISION_PENDING: Final = "REVISION_PENDING"
UPSTREAM_NOT_READY: Final = "UPSTREAM_NOT_READY"
PREPARE_AGAIN: Final = "PREPARE_AGAIN"
BLOCKS: Final = (
    REQUIREMENT_NO_LONGER_AVAILABLE,
    TWIN_SET_CHANGED,
    TWIN_NO_LONGER_AVAILABLE,
    REVISION_PENDING,
    UPSTREAM_NOT_READY,
    PREPARE_AGAIN,
)
PENDING_SUFFIX: Final = "_REVISION_PENDING"
ALIGNED: Final = "ALIGNED"
PARTIAL: Final = "PARTIAL"
NOTHING_TO_ALIGN: Final = "NOTHING_TO_ALIGN"
GESTURE_STATUSES: Final = (ALIGNED, PARTIAL, NOTHING_TO_ALIGN)
BLOCKED: Final = "BLOCKED"
SKIPPED: Final = "SKIPPED"
OUTCOMES: Final = (ALIGNED, BLOCKED, SKIPPED)
PROJECT_CODES: Final = frozenset({"PROJECT_NOT_FOUND", "project_not_found"})
MISSING_ROUTE: Final = frozenset({404, 405})
STAGE_OF: Final[Mapping[str, str]] = MappingProxyType(
    {code: stage for stage, code in project_api.STAGE_CODES.items()}
)


@dataclass(frozen=True, slots=True)
class Section:
    key: str
    state: str
    version_number: int | None = None
    reasons: tuple[str, ...] = ()
    blocked: str | None = None
    codes: tuple[str, ...] = ()

    @property
    def stage(self) -> str:
        return STAGE_OF.get(self.key, self.key.lower())

    @property
    def behind(self) -> bool:
        return self.state == TO_UPDATE


@dataclass(frozen=True, slots=True)
class Alignment:
    available: bool = False
    sections: tuple[str, ...] = ()
    uncovered_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Sections:
    first_pass_complete: bool
    sections: tuple[Section, ...]
    alignment: Alignment
    document: Mapping[str, object]

    def section(self, key: str) -> Section | None:
        return next((item for item in self.sections if item.key == key), None)

    def behind(self, keys: Sequence[str] = UPSTREAM) -> tuple[Section, ...]:
        return tuple(item for item in self.sections if item.key in keys and item.behind)

    def in_progress(self) -> Section | None:
        return next((item for item in self.sections if item.state == IN_PROGRESS), None)

    def reasons(self, key: str) -> tuple[str, ...]:
        found = self.section(key)
        return () if found is None else found.reasons


@dataclass(frozen=True, slots=True)
class Result:
    key: str
    outcome: str
    issue: str | None = None
    version_number: int | None = None
    codes: tuple[str, ...] = ()

    @property
    def stage(self) -> str:
        return STAGE_OF.get(self.key, self.key.lower())


@dataclass(frozen=True, slots=True)
class Gesture:
    status: str
    results: tuple[Result, ...]
    sections: Sections | None

    @property
    def aligned(self) -> tuple[Result, ...]:
        return tuple(item for item in self.results if item.outcome == ALIGNED)

    @property
    def blocked(self) -> tuple[Result, ...]:
        return tuple(item for item in self.results if item.outcome == BLOCKED)


def sections_path(project_id: str) -> str:
    return f"/projects/{project_id}/sections"


def alignment_path(project_id: str) -> str:
    return f"{sections_path(project_id)}/alignment"


def sections(client: StudioClient, project_id: str) -> Sections | None:
    try:
        document = client.get(sections_path(project_id))
    except ApiFailure as failure:
        if missing_route(failure):
            return None
        raise
    found = sections_of(document)
    if found is None:
        raise ApiFailure("API_FAILURE", http_status=200, detail=document)
    return found


def align(client: StudioClient, project_id: str) -> Gesture | None:
    try:
        document = client.post(alignment_path(project_id))
    except ApiFailure as failure:
        if missing_route(failure):
            return None
        raise
    found = gesture_of(document)
    if found is None:
        raise ApiFailure("API_FAILURE", http_status=200, detail=document)
    return found


def missing_route(failure: ApiFailure) -> bool:
    return failure.http_status in MISSING_ROUTE and failure.code not in PROJECT_CODES


def sections_of(document: object) -> Sections | None:
    if not isinstance(document, Mapping):
        return None
    items = document.get("sections")
    if not isinstance(items, list):
        return None
    found = tuple(section for item in items if (section := section_of(item)) is not None)
    alignment = document.get("alignment")
    alignment = alignment if isinstance(alignment, Mapping) else {}
    return Sections(
        first_pass_complete=document.get("first_pass_complete") is True,
        sections=found,
        alignment=Alignment(
            available=alignment.get("available") is True,
            sections=_texts(alignment.get("sections")),
            uncovered_codes=_texts(alignment.get("uncovered_codes")),
        ),
        document=document,
    )


def section_of(item: object) -> Section | None:
    if not isinstance(item, Mapping):
        return None
    key = item.get("key")
    state = item.get("state")
    if not isinstance(key, str) or not key or not isinstance(state, str) or not state:
        return None
    blocked = item.get("blocked")
    return Section(
        key=key,
        state=state,
        version_number=_integer(item.get("version_number")),
        reasons=_texts(item.get("reasons")),
        blocked=blocked if isinstance(blocked, str) and blocked else None,
        codes=_texts(item.get("codes")),
    )


def gesture_of(document: object) -> Gesture | None:
    if not isinstance(document, Mapping):
        return None
    status = document.get("status")
    items = document.get("results")
    if not isinstance(status, str) or not status or not isinstance(items, list):
        return None
    return Gesture(
        status=status,
        results=tuple(result for item in items if (result := result_of(item)) is not None),
        sections=sections_of(document.get("sections")),
    )


def result_of(item: object) -> Result | None:
    if not isinstance(item, Mapping):
        return None
    key = item.get("key")
    outcome = item.get("outcome")
    if not isinstance(key, str) or not key or not isinstance(outcome, str) or not outcome:
        return None
    issue = item.get("issue")
    return Result(
        key=key,
        outcome=outcome,
        issue=issue if isinstance(issue, str) and issue else None,
        version_number=_integer(item.get("version_number")),
        codes=_texts(item.get("codes")),
    )


def block_of(issue: str | None) -> str | None:
    if issue is None:
        return None
    if issue in BLOCKS:
        return issue
    if issue.endswith(PENDING_SUFFIX):
        return REVISION_PENDING
    return None


def _texts(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
