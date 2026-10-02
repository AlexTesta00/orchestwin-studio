from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid4

from orchestwin.knowledge.state import (
    MAX_ACTION_LENGTH,
    MAX_AUTHOR_LENGTH,
    MAX_COMMIT_LENGTH,
    MAX_DESIGN_REQUEST_LENGTH,
    MAX_DIFF_LENGTH,
    MAX_FILES,
    MAX_FINDING_LENGTH,
    MAX_FINDINGS,
    MAX_MESSAGE_LENGTH,
    MAX_MODEL_TASKS,
    MAX_NOTE_LENGTH,
    MAX_PATH_LENGTH,
    MAX_REQUIREMENTS_REQUEST_LENGTH,
    MAX_SUMMARY_LENGTH,
    MAX_TASK_LENGTH,
    MAX_TASK_NOTE_LENGTH,
    MIN_COMMIT_LENGTH,
    review_is_stale,
)
from orchestwin.twins.limits import MAX_USER_TWINS

COMMIT_PATTERN: Final = rf"^[0-9a-f]{{{MIN_COMMIT_LENGTH},{MAX_COMMIT_LENGTH}}}$"
LOCALE_PATTERN: Final = r"^[a-z]{2,3}(-[A-Z]{2})?$"
MAX_LOCALE_LENGTH: Final = 20
MAX_TWIN_NAME_LENGTH: Final = 200
MAX_TASK_NUMBER: Final = 999_999
TASK_CODE_PREFIX: Final = "TSK"
TASK_CODE_PATTERN: Final = r"^TSK-[0-9]{3,6}$"
TASK_CUT_MARK: Final = "…"
_COMMIT: Final = re.compile(COMMIT_PATTERN)
_LOCALE: Final = re.compile(LOCALE_PATTERN)
_TASK_CODE: Final = re.compile(TASK_CODE_PATTERN)
_REQUIREMENT_CODE: Final = re.compile(r"REQ-[0-9]{3,6}")
_SCREEN_CODE: Final = re.compile(r"SCR-[0-9]{3,6}")
_CRITERION_CODE: Final = re.compile(r"AC-[0-9]{3,6}")
_ALTERNATIVE_CODE: Final = re.compile(r"DES-[0-9]{3,6}")
_PLACEHOLDER_ID: Final = UUID(int=0)


class ChangedFileKind(StrEnum):
    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"
    RENAMED = "RENAMED"


class AlignmentStatus(StrEnum):
    ALIGNED = "ALIGNED"
    CODE_DRIFT = "CODE_DRIFT"
    DESIGN_OUTDATED = "DESIGN_OUTDATED"
    REQUIREMENTS_OUTDATED = "REQUIREMENTS_OUTDATED"


class DecisionKind(StrEnum):
    ALIGNED = "ALIGNED"
    DESIGN_CHANGE = "DESIGN_CHANGE"
    REQUIREMENTS_CHANGE = "REQUIREMENTS_CHANGE"
    CODE_TASKS = "CODE_TASKS"
    DISMISSED = "DISMISSED"


class CritiqueVerdict(StrEnum):
    FINE = "FINE"
    CONCERN = "CONCERN"
    DRIFT = "DRIFT"


class FindingSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TaskStatus(StrEnum):
    OPEN = "OPEN"
    DONE = "DONE"
    DROPPED = "DROPPED"


class TaskOrigin(StrEnum):
    CODE_CHANGE = "CODE_CHANGE"
    TEST_RUN = "TEST_RUN"
    OWNER = "OWNER"


class CodeChangeAmbiguous(LookupError):
    def __init__(self, prefix: str) -> None:
        super().__init__(prefix)
        self.prefix = prefix


def _aware(value: object, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be a timezone-aware timestamp")


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _uuid(value: object, label: str) -> None:
    if not isinstance(value, UUID):
        raise ValueError(f"{label} must be a UUID")


def _count(value: object, label: str, *, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer of at least {minimum}")


def _control_free(value: str) -> bool:
    return all(ord(character) >= 32 and ord(character) != 127 for character in value)


def normalized_line(value: object, *, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} is required")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters")
    if not _control_free(normalized):
        raise ValueError(f"{label} must not contain control characters")
    return normalized


def normalized_block(value: object, *, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} is required")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters")
    if "\x00" in normalized:
        raise ValueError(f"{label} must not contain a null character")
    return normalized


def normalize_commit(value: object, *, label: str = "commit") -> str:
    if not isinstance(value, str) or _COMMIT.fullmatch(value.lower()) is None:
        raise ValueError(
            f"{label} must hold {MIN_COMMIT_LENGTH} to {MAX_COMMIT_LENGTH} hexadecimal characters"
        )
    return value.lower()


def commit_prefix(value: str) -> str | None:
    try:
        return normalize_commit(value)
    except ValueError:
        return None


def normalize_author(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("commit author must be a text")
    if not value.strip():
        return None
    return normalized_line(value, label="commit author", maximum=MAX_AUTHOR_LENGTH)


def normalize_message(value: object) -> str:
    return normalized_block(value, label="commit message", maximum=MAX_MESSAGE_LENGTH)


def normalize_path(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("changed file path must not be empty")
    if len(value) > MAX_PATH_LENGTH:
        raise ValueError(f"changed file path exceeds {MAX_PATH_LENGTH} characters")
    if not _control_free(value):
        raise ValueError("changed file path must not contain control characters")
    return value


def normalize_diff(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("commit diff must be a text")
    if len(value) > MAX_DIFF_LENGTH:
        raise ValueError(f"commit diff exceeds {MAX_DIFF_LENGTH} characters")
    if "\x00" in value:
        raise ValueError("commit diff must not contain a null character")
    return value


def normalize_note(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("decision note must be a text")
    if not value.strip():
        return None
    return normalized_block(value, label="decision note", maximum=MAX_NOTE_LENGTH)


def normalize_task_text(value: object) -> str:
    return normalized_line(value, label="code task", maximum=MAX_TASK_LENGTH)


def normalize_task_note(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("task note must be a text")
    if not value.strip():
        return None
    return normalized_line(value, label="task note", maximum=MAX_TASK_NOTE_LENGTH)


def finding_task_text(text: str, action: str | None = None) -> str:
    chosen = " ".join((action if action and action.strip() else text).split())
    if len(chosen) > MAX_TASK_LENGTH:
        chosen = chosen[: MAX_TASK_LENGTH - len(TASK_CUT_MARK)].rstrip() + TASK_CUT_MARK
    return normalize_task_text(chosen)


def code_task_code(number: int) -> str:
    _count(number, "code task number", minimum=1)
    if number > MAX_TASK_NUMBER:
        raise ValueError(f"code task number exceeds {MAX_TASK_NUMBER}")
    return f"{TASK_CODE_PREFIX}-{number:03d}"


def task_number(code: object) -> int | None:
    if not isinstance(code, str) or _TASK_CODE.fullmatch(code.upper()) is None:
        return None
    number = int(code.split("-", 1)[1])
    if number < 1 or code_task_code(number) != code.upper():
        return None
    return number


def _codes(values: object, pattern: re.Pattern[str], label: str) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{label} must be a tuple")
    for value in values:
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise ValueError(f"{label} holds an invalid code")
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must not repeat a code")


def _normalized(value: object, *, label: str, maximum: int) -> None:
    if normalized_line(value, label=label, maximum=maximum) != value:
        raise ValueError(f"{label} must be normalized")


def _optional_normalized(value: object, *, label: str, maximum: int) -> None:
    if value is not None:
        _normalized(value, label=label, maximum=maximum)


@dataclass(frozen=True, slots=True)
class ChangedFile:
    path: str
    kind: ChangedFileKind
    added: int
    removed: int

    def __post_init__(self) -> None:
        if normalize_path(self.path) != self.path:
            raise ValueError("changed file path must be normalized")
        if not isinstance(self.kind, ChangedFileKind):
            raise ValueError("changed file kind must be a ChangedFileKind")
        _count(self.added, "added lines")
        _count(self.removed, "removed lines")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "path": self.path,
            "kind": self.kind.value,
            "added": self.added,
            "removed": self.removed,
        }


def changed_file_from_snapshot(payload: Mapping[str, object]) -> ChangedFile:
    return ChangedFile(
        path=str(payload["path"]),
        kind=ChangedFileKind(str(payload["kind"])),
        added=payload["added"],
        removed=payload["removed"],
    )


@dataclass(frozen=True, slots=True)
class ChangeDecision:
    kind: DecisionKind
    decided_at: datetime
    note: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DecisionKind):
            raise ValueError("decision kind must be a DecisionKind")
        _aware(self.decided_at, "decision timestamp")
        if normalize_note(self.note) != self.note:
            raise ValueError("decision note must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "decided_at": _timestamp(self.decided_at),
            "note": self.note,
        }


def _reference(requirements_version: object, design_version: object, alternative: object) -> None:
    _count(requirements_version, "requirements version number", minimum=1)
    _count(design_version, "design version number", minimum=1)
    if not isinstance(alternative, str) or _ALTERNATIVE_CODE.fullmatch(alternative) is None:
        raise ValueError("alternative code must use the DES-NNN format")


@dataclass(frozen=True, slots=True)
class ChangeReviewSummary:
    run_id: UUID
    reviewed_at: datetime
    verdict: AlignmentStatus
    summary: str
    requirements_version_number: int
    design_version_number: int
    alternative_code: str

    def __post_init__(self) -> None:
        _uuid(self.run_id, "review run ID")
        _aware(self.reviewed_at, "review timestamp")
        if not isinstance(self.verdict, AlignmentStatus):
            raise ValueError("review verdict must be an AlignmentStatus")
        _normalized(self.summary, label="review summary", maximum=MAX_SUMMARY_LENGTH)
        _reference(
            self.requirements_version_number, self.design_version_number, self.alternative_code
        )

    def reference_snapshot(self) -> dict[str, object]:
        return {
            "requirements_version_number": self.requirements_version_number,
            "design_version_number": self.design_version_number,
            "alternative_code": self.alternative_code,
        }

    def stale(self, current: Mapping[str, object] | None) -> bool:
        return review_is_stale(self.reference_snapshot(), current)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "run_id": str(self.run_id),
            "reviewed_at": _timestamp(self.reviewed_at),
            "verdict": self.verdict.value,
            "summary": self.summary,
            "reference": self.reference_snapshot(),
        }

    def to_answer(self, current: Mapping[str, object] | None) -> dict[str, object]:
        return {**self.to_snapshot(), "stale": self.stale(current)}


@dataclass(frozen=True, slots=True)
class AlignedPoint:
    commit: str
    decided_at: datetime
    requirements_version_number: int | None
    design_version_number: int | None

    def __post_init__(self) -> None:
        normalize_commit(self.commit)
        _aware(self.decided_at, "aligned point timestamp")
        for label, value in (
            ("aligned requirements version", self.requirements_version_number),
            ("aligned design version", self.design_version_number),
        ):
            if value is not None:
                _count(value, label, minimum=1)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "commit": self.commit,
            "decided_at": _timestamp(self.decided_at),
            "requirements_version_number": self.requirements_version_number,
            "design_version_number": self.design_version_number,
        }


@dataclass(frozen=True, slots=True)
class CodeChange:
    id: UUID
    project_id: UUID
    owner_user_id: UUID
    commit: str
    parent: str | None
    committed_at: datetime
    author: str | None
    message: str
    files: tuple[ChangedFile, ...]
    recorded_at: datetime
    diff: str | None = None
    decision: ChangeDecision | None = None
    aligned_requirements_version: int | None = None
    aligned_design_version: int | None = None
    review: ChangeReviewSummary | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("code change ID", self.id),
            ("project ID", self.project_id),
            ("owner ID", self.owner_user_id),
        ):
            _uuid(value, label)
        if normalize_commit(self.commit) != self.commit:
            raise ValueError("commit must be lower case")
        if self.parent is not None:
            if normalize_commit(self.parent, label="parent commit") != self.parent:
                raise ValueError("parent commit must be lower case")
            if self.parent == self.commit:
                raise ValueError("a commit cannot be its own parent")
        _aware(self.committed_at, "commit timestamp")
        _aware(self.recorded_at, "record timestamp")
        if normalize_author(self.author) != self.author:
            raise ValueError("commit author must be normalized")
        if normalize_message(self.message) != self.message:
            raise ValueError("commit message must be normalized")
        if not isinstance(self.files, tuple) or not all(
            isinstance(item, ChangedFile) for item in self.files
        ):
            raise ValueError("changed files must be a tuple of ChangedFile")
        if len(self.files) > MAX_FILES:
            raise ValueError(f"a code change holds at most {MAX_FILES} files")
        if self.diff is not None:
            normalize_diff(self.diff)
        if self.decision is not None and not isinstance(self.decision, ChangeDecision):
            raise ValueError("decision must be a ChangeDecision")
        versions = (self.aligned_requirements_version, self.aligned_design_version)
        for value in versions:
            if value is not None:
                _count(value, "aligned version", minimum=1)
        if not self.aligned and versions != (None, None):
            raise ValueError("aligned versions belong to an ALIGNED decision only")
        if self.review is not None and not isinstance(self.review, ChangeReviewSummary):
            raise ValueError("review must be a ChangeReviewSummary")

    @property
    def aligned(self) -> bool:
        return self.decision is not None and self.decision.kind is DecisionKind.ALIGNED

    def aligned_point(self) -> AlignedPoint:
        if not self.aligned:
            raise ValueError("only an ALIGNED change is an aligned point")
        return AlignedPoint(
            commit=self.commit,
            decided_at=self.decision.decided_at,
            requirements_version_number=self.aligned_requirements_version,
            design_version_number=self.aligned_design_version,
        )

    def with_decision(
        self,
        decision: ChangeDecision,
        *,
        requirements_version: int | None = None,
        design_version: int | None = None,
    ) -> CodeChange:
        aligned = decision.kind is DecisionKind.ALIGNED
        return replace(
            self,
            decision=decision,
            aligned_requirements_version=requirements_version if aligned else None,
            aligned_design_version=design_version if aligned else None,
        )

    def with_review(self, review: ChangeReviewSummary | None) -> CodeChange:
        return replace(self, review=review)

    def _snapshot(self, review: dict[str, object] | None, include_diff: bool) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "commit": self.commit,
            "parent": self.parent,
            "committed_at": _timestamp(self.committed_at),
            "author": self.author,
            "message": self.message,
            "files": [item.to_snapshot() for item in self.files],
            "recorded_at": _timestamp(self.recorded_at),
            "review": review,
            "decision": None if self.decision is None else self.decision.to_snapshot(),
        }
        if include_diff:
            if self.diff is None:
                raise ValueError("the diff of this code change was not loaded")
            snapshot["diff"] = self.diff
        return snapshot

    def to_snapshot(self, *, include_diff: bool = False) -> dict[str, object]:
        review = None if self.review is None else self.review.to_snapshot()
        return self._snapshot(review, include_diff)

    def to_answer(
        self, current: Mapping[str, object] | None, *, include_diff: bool = False
    ) -> dict[str, object]:
        review = None if self.review is None else self.review.to_answer(current)
        return self._snapshot(review, include_diff)


def create_code_change(
    *,
    project_id: UUID,
    owner_user_id: UUID,
    commit: str,
    parent: str | None,
    committed_at: datetime,
    author: str | None,
    message: str,
    files: Iterable[ChangedFile],
    diff: str,
    recorded_at: datetime,
    change_id: UUID | None = None,
) -> CodeChange:
    return CodeChange(
        id=uuid4() if change_id is None else change_id,
        project_id=project_id,
        owner_user_id=owner_user_id,
        commit=normalize_commit(commit),
        parent=None if parent is None else normalize_commit(parent, label="parent commit"),
        committed_at=committed_at,
        author=normalize_author(author),
        message=normalize_message(message),
        files=tuple(files),
        diff=normalize_diff(diff),
        recorded_at=recorded_at,
    )


def aligned_change(changes: Sequence[CodeChange]) -> CodeChange | None:
    return next((change for change in changes if change.aligned), None)


def pending_changes(changes: Sequence[CodeChange]) -> tuple[CodeChange, ...]:
    pending = []
    for change in changes:
        if change.aligned:
            break
        pending.append(change)
    return tuple(pending)


@dataclass(frozen=True, slots=True)
class CritiqueFinding:
    severity: FindingSeverity
    text: str
    requirement: str | None = None
    screen: str | None = None
    file: str | None = None
    action: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.severity, FindingSeverity):
            raise ValueError("finding severity must be a FindingSeverity")
        _normalized(self.text, label="finding text", maximum=MAX_FINDING_LENGTH)
        if self.requirement is not None:
            _codes((self.requirement,), _REQUIREMENT_CODE, "finding requirement")
        if self.screen is not None:
            _codes((self.screen,), _SCREEN_CODE, "finding screen")
        if self.file is not None and normalize_path(self.file) != self.file:
            raise ValueError("finding file must be normalized")
        _optional_normalized(self.action, label="finding action", maximum=MAX_ACTION_LENGTH)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "severity": self.severity.value,
            "text": self.text,
            "about": {"requirement": self.requirement, "screen": self.screen, "file": self.file},
            "action": self.action,
        }


def critique_finding_from_snapshot(payload: Mapping[str, object]) -> CritiqueFinding:
    about = payload["about"]
    if not isinstance(about, Mapping):
        raise ValueError("finding about must be an object")
    return CritiqueFinding(
        severity=FindingSeverity(str(payload["severity"])),
        text=payload["text"],
        requirement=about["requirement"],
        screen=about["screen"],
        file=about["file"],
        action=payload["action"],
    )


@dataclass(frozen=True, slots=True)
class TwinCritique:
    twin_id: UUID
    twin_name: str
    verdict: CritiqueVerdict
    summary: str
    findings: tuple[CritiqueFinding, ...] = ()

    def __post_init__(self) -> None:
        _uuid(self.twin_id, "critique twin ID")
        _normalized(self.twin_name, label="critique twin name", maximum=MAX_TWIN_NAME_LENGTH)
        if not isinstance(self.verdict, CritiqueVerdict):
            raise ValueError("critique verdict must be a CritiqueVerdict")
        _normalized(self.summary, label="critique summary", maximum=MAX_SUMMARY_LENGTH)
        if not isinstance(self.findings, tuple) or not all(
            isinstance(item, CritiqueFinding) for item in self.findings
        ):
            raise ValueError("critique findings must be a tuple of CritiqueFinding")
        if len(self.findings) > MAX_FINDINGS:
            raise ValueError(f"a critique holds at most {MAX_FINDINGS} findings")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "twin_id": str(self.twin_id),
            "twin_name": self.twin_name,
            "verdict": self.verdict.value,
            "summary": self.summary,
            "findings": [item.to_snapshot() for item in self.findings],
        }


def twin_critique_from_snapshot(payload: Mapping[str, object]) -> TwinCritique:
    return TwinCritique(
        twin_id=UUID(str(payload["twin_id"])),
        twin_name=payload["twin_name"],
        verdict=CritiqueVerdict(str(payload["verdict"])),
        summary=payload["summary"],
        findings=tuple(critique_finding_from_snapshot(item) for item in payload["findings"]),
    )


@dataclass(frozen=True, slots=True)
class AlignmentVerdict:
    status: AlignmentStatus
    summary: str
    affected_requirements: tuple[str, ...] = ()
    affected_screens: tuple[str, ...] = ()
    design_request: str | None = None
    requirements_request: str | None = None
    code_tasks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, AlignmentStatus):
            raise ValueError("alignment status must be an AlignmentStatus")
        _normalized(self.summary, label="alignment summary", maximum=MAX_SUMMARY_LENGTH)
        _codes(self.affected_requirements, _REQUIREMENT_CODE, "affected requirements")
        _codes(self.affected_screens, _SCREEN_CODE, "affected screens")
        _optional_normalized(
            self.design_request, label="design request", maximum=MAX_DESIGN_REQUEST_LENGTH
        )
        _optional_normalized(
            self.requirements_request,
            label="requirements request",
            maximum=MAX_REQUIREMENTS_REQUEST_LENGTH,
        )
        if not isinstance(self.code_tasks, tuple):
            raise ValueError("code tasks must be a tuple")
        for task in self.code_tasks:
            _normalized(task, label="code task", maximum=MAX_TASK_LENGTH)
        if len(self.code_tasks) > MAX_MODEL_TASKS:
            raise ValueError(f"a verdict proposes at most {MAX_MODEL_TASKS} code tasks")
        if len(set(self.code_tasks)) != len(self.code_tasks):
            raise ValueError("code tasks must not repeat")
        outdated_design = self.status is AlignmentStatus.DESIGN_OUTDATED
        if outdated_design != (self.design_request is not None):
            raise ValueError("a design request is given exactly when the design is outdated")
        outdated_requirements = self.status is AlignmentStatus.REQUIREMENTS_OUTDATED
        if outdated_requirements != (self.requirements_request is not None):
            raise ValueError(
                "a requirements request is given exactly when the requirements are outdated"
            )
        if self.status is AlignmentStatus.CODE_DRIFT and not self.code_tasks:
            raise ValueError("a code drift needs at least one code task")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "summary": self.summary,
            "affected": {
                "requirements": list(self.affected_requirements),
                "screens": list(self.affected_screens),
            },
            "design_request": self.design_request,
            "requirements_request": self.requirements_request,
            "code_tasks": list(self.code_tasks),
        }


def alignment_verdict_from_snapshot(payload: Mapping[str, object]) -> AlignmentVerdict:
    affected = payload["affected"]
    if not isinstance(affected, Mapping):
        raise ValueError("affected codes must be an object")
    return AlignmentVerdict(
        status=AlignmentStatus(str(payload["status"])),
        summary=payload["summary"],
        affected_requirements=tuple(affected["requirements"]),
        affected_screens=tuple(affected["screens"]),
        design_request=payload["design_request"],
        requirements_request=payload["requirements_request"],
        code_tasks=tuple(payload["code_tasks"]),
    )


@dataclass(frozen=True, slots=True)
class ChangeReviewRun:
    id: UUID
    change_id: UUID
    project_id: UUID
    owner_user_id: UUID
    commit: str
    reviewed_at: datetime
    locale: str
    requirements_version_number: int
    design_version_number: int
    alternative_code: str
    critiques: tuple[TwinCritique, ...]
    alignment: AlignmentVerdict
    generation_ids: tuple[UUID, ...] = ()
    cost_microusd: int = 0

    def __post_init__(self) -> None:
        for label, value in (
            ("review run ID", self.id),
            ("code change ID", self.change_id),
            ("project ID", self.project_id),
            ("owner ID", self.owner_user_id),
        ):
            _uuid(value, label)
        if normalize_commit(self.commit) != self.commit:
            raise ValueError("review commit must be lower case")
        _aware(self.reviewed_at, "review timestamp")
        if (
            not isinstance(self.locale, str)
            or len(self.locale) > MAX_LOCALE_LENGTH
            or _LOCALE.fullmatch(self.locale) is None
        ):
            raise ValueError("review locale must be a language tag such as it-IT")
        _reference(
            self.requirements_version_number, self.design_version_number, self.alternative_code
        )
        if not isinstance(self.critiques, tuple) or not all(
            isinstance(item, TwinCritique) for item in self.critiques
        ):
            raise ValueError("critiques must be a tuple of TwinCritique")
        if not 1 <= len(self.critiques) <= MAX_USER_TWINS:
            raise ValueError(f"a review holds between 1 and {MAX_USER_TWINS} critiques")
        twins = [item.twin_id for item in self.critiques]
        if len(set(twins)) != len(twins):
            raise ValueError("a review holds one critique per twin")
        if not isinstance(self.alignment, AlignmentVerdict):
            raise ValueError("alignment must be an AlignmentVerdict")
        if not isinstance(self.generation_ids, tuple) or not all(
            isinstance(item, UUID) for item in self.generation_ids
        ):
            raise ValueError("generation IDs must be a tuple of UUID")
        if len(set(self.generation_ids)) != len(self.generation_ids):
            raise ValueError("generation IDs must not repeat")
        _count(self.cost_microusd, "review cost")

    def reference_snapshot(self) -> dict[str, object]:
        return {
            "requirements_version_number": self.requirements_version_number,
            "design_version_number": self.design_version_number,
            "alternative_code": self.alternative_code,
        }

    def summary(self) -> ChangeReviewSummary:
        return ChangeReviewSummary(
            run_id=self.id,
            reviewed_at=self.reviewed_at,
            verdict=self.alignment.status,
            summary=self.alignment.summary,
            requirements_version_number=self.requirements_version_number,
            design_version_number=self.design_version_number,
            alternative_code=self.alternative_code,
        )

    def findings_of(self, twin_id: UUID) -> tuple[str, ...]:
        critique = next((item for item in self.critiques if item.twin_id == twin_id), None)
        return () if critique is None else tuple(item.text for item in critique.findings)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "commit": self.commit,
            "reviewed_at": _timestamp(self.reviewed_at),
            "locale": self.locale,
            "reference": self.reference_snapshot(),
            "critiques": [item.to_snapshot() for item in self.critiques],
            "alignment": self.alignment.to_snapshot(),
            "cost_microusd": self.cost_microusd,
        }


def _task_origin(
    origin: object,
    *,
    change_id: object,
    commit: object,
    test_run_id: object,
    twin_id: object,
    twin_name: object,
    finding: object,
) -> None:
    if not isinstance(origin, TaskOrigin):
        raise ValueError("task origin must be a TaskOrigin")
    if origin is TaskOrigin.CODE_CHANGE:
        _uuid(change_id, "task change ID")
        if normalize_commit(commit, label="task commit") != commit:
            raise ValueError("task commit must be lower case")
        if test_run_id is not None:
            raise ValueError("a task from a code change names no test run")
    elif origin is TaskOrigin.TEST_RUN:
        _uuid(test_run_id, "task test run ID")
        if change_id is not None or commit is not None:
            raise ValueError("a task from a test run names no code change")
        if twin_id is None:
            raise ValueError("a task from a test run comes from a finding of a twin")
    elif (change_id, commit, test_run_id, twin_id) != (None, None, None, None):
        raise ValueError("a task written by the owner names no change, run or twin")
    twin = (twin_id, twin_name, finding)
    if twin == (None, None, None):
        return
    if None in twin:
        raise ValueError("a task from a finding names the twin and the finding")
    _uuid(twin_id, "task twin ID")
    _normalized(twin_name, label="task twin name", maximum=MAX_TWIN_NAME_LENGTH)
    _normalized(finding, label="task finding", maximum=MAX_FINDING_LENGTH)


def _task_about(requirements: object, screens: object, criteria: object) -> None:
    _codes(requirements, _REQUIREMENT_CODE, "code task requirements")
    _codes(screens, _SCREEN_CODE, "code task screens")
    _codes(criteria, _CRITERION_CODE, "code task criteria")


def _source_key(
    origin: TaskOrigin,
    change_id: UUID | None,
    test_run_id: UUID | None,
    twin_id: UUID | None,
    finding: str | None,
) -> tuple[object, ...] | None:
    if twin_id is None or finding is None:
        return None
    subject = change_id if origin is TaskOrigin.CODE_CHANGE else test_run_id
    return origin, subject, twin_id, finding


@dataclass(frozen=True, slots=True)
class TaskSource:
    origin: TaskOrigin
    text: str
    change_id: UUID | None = None
    commit: str | None = None
    test_run_id: UUID | None = None
    twin_id: UUID | None = None
    twin_name: str | None = None
    finding: str | None = None
    requirements: tuple[str, ...] = ()
    screens: tuple[str, ...] = ()
    criteria: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _task_origin(
            self.origin,
            change_id=self.change_id,
            commit=self.commit,
            test_run_id=self.test_run_id,
            twin_id=self.twin_id,
            twin_name=self.twin_name,
            finding=self.finding,
        )
        if normalize_task_text(self.text) != self.text:
            raise ValueError("code task text must be normalized")
        _task_about(self.requirements, self.screens, self.criteria)

    @property
    def key(self) -> tuple[object, ...] | None:
        return _source_key(
            self.origin, self.change_id, self.test_run_id, self.twin_id, self.finding
        )


@dataclass(frozen=True, slots=True)
class CodeTask:
    id: UUID
    project_id: UUID
    owner_user_id: UUID
    number: int
    text: str
    created_at: datetime
    origin: TaskOrigin = TaskOrigin.CODE_CHANGE
    from_change_id: UUID | None = None
    from_commit: str | None = None
    test_run_id: UUID | None = None
    twin_id: UUID | None = None
    twin_name: str | None = None
    finding: str | None = None
    status: TaskStatus = TaskStatus.OPEN
    requirements: tuple[str, ...] = ()
    screens: tuple[str, ...] = ()
    criteria: tuple[str, ...] = ()
    closed_at: datetime | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("code task ID", self.id),
            ("project ID", self.project_id),
            ("owner ID", self.owner_user_id),
        ):
            _uuid(value, label)
        code_task_code(self.number)
        if normalize_task_text(self.text) != self.text:
            raise ValueError("code task text must be normalized")
        _aware(self.created_at, "code task timestamp")
        _task_origin(
            self.origin,
            change_id=self.from_change_id,
            commit=self.from_commit,
            test_run_id=self.test_run_id,
            twin_id=self.twin_id,
            twin_name=self.twin_name,
            finding=self.finding,
        )
        if not isinstance(self.status, TaskStatus):
            raise ValueError("code task status must be a TaskStatus")
        _task_about(self.requirements, self.screens, self.criteria)
        if (self.status is TaskStatus.OPEN) != (self.closed_at is None):
            raise ValueError("a code task has a closing time exactly when it is done or dropped")
        if self.closed_at is not None:
            _aware(self.closed_at, "code task closing time")
        if normalize_task_note(self.note) != self.note:
            raise ValueError("code task note must be normalized")

    @classmethod
    def from_source(
        cls,
        source: TaskSource,
        *,
        task_id: UUID,
        project_id: UUID,
        owner_user_id: UUID,
        number: int,
        created_at: datetime,
    ) -> CodeTask:
        return cls(
            id=task_id,
            project_id=project_id,
            owner_user_id=owner_user_id,
            number=number,
            text=source.text,
            created_at=created_at,
            origin=source.origin,
            from_change_id=source.change_id,
            from_commit=source.commit,
            test_run_id=source.test_run_id,
            twin_id=source.twin_id,
            twin_name=source.twin_name,
            finding=source.finding,
            requirements=source.requirements,
            screens=source.screens,
            criteria=source.criteria,
        )

    @property
    def code(self) -> str:
        return code_task_code(self.number)

    @property
    def open(self) -> bool:
        return self.status is TaskStatus.OPEN

    @property
    def source_key(self) -> tuple[object, ...] | None:
        return _source_key(
            self.origin, self.from_change_id, self.test_run_id, self.twin_id, self.finding
        )

    def with_status(self, status: TaskStatus, *, at: datetime, note: str | None = None) -> CodeTask:
        if status is self.status:
            return replace(self, note=note)
        closed_at = None if status is TaskStatus.OPEN else at
        return replace(self, status=status, closed_at=closed_at, note=note)

    def done(self, closed_at: datetime) -> CodeTask:
        return self.with_status(TaskStatus.DONE, at=closed_at)

    def about_snapshot(self) -> dict[str, list[str]]:
        return {
            "requirements": list(self.requirements),
            "screens": list(self.screens),
            "criteria": list(self.criteria),
        }

    def to_snapshot(self) -> dict[str, object]:
        return {
            "code": self.code,
            "text": self.text,
            "about": self.about_snapshot(),
            "origin": {
                "kind": self.origin.value,
                "commit": self.from_commit,
                "test_run_id": None if self.test_run_id is None else str(self.test_run_id),
                "twin_id": None if self.twin_id is None else str(self.twin_id),
                "twin_name": self.twin_name,
                "finding": self.finding,
            },
            "from_commit": self.from_commit,
            "created_at": _timestamp(self.created_at),
            "status": self.status.value,
            "closed_at": None if self.closed_at is None else _timestamp(self.closed_at),
            "note": self.note,
        }


def _optional_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


def _optional_time(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


def code_task_from_snapshot(
    payload: Mapping[str, object],
    *,
    task_id: UUID | None = None,
    project_id: UUID | None = None,
    owner_user_id: UUID | None = None,
    change_id: UUID | None = None,
) -> CodeTask:
    about = payload["about"]
    origin = payload["origin"]
    if not isinstance(about, Mapping) or not isinstance(origin, Mapping):
        raise ValueError("task about and origin must be objects")
    if payload["from_commit"] != origin["commit"]:
        raise ValueError("a task names the commit of its origin")
    number = task_number(payload["code"])
    if number is None or payload["code"] != code_task_code(number):
        raise ValueError("task code must use the TSK-NNN format")
    kind = TaskOrigin(str(origin["kind"]))
    return CodeTask(
        id=_PLACEHOLDER_ID if task_id is None else task_id,
        project_id=_PLACEHOLDER_ID if project_id is None else project_id,
        owner_user_id=_PLACEHOLDER_ID if owner_user_id is None else owner_user_id,
        number=number,
        text=payload["text"],
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        origin=kind,
        from_change_id=(_PLACEHOLDER_ID if change_id is None else change_id)
        if kind is TaskOrigin.CODE_CHANGE
        else None,
        from_commit=origin["commit"],
        test_run_id=_optional_uuid(origin["test_run_id"]),
        twin_id=_optional_uuid(origin["twin_id"]),
        twin_name=origin["twin_name"],
        finding=origin["finding"],
        status=TaskStatus(str(payload["status"])),
        requirements=tuple(about["requirements"]),
        screens=tuple(about["screens"]),
        criteria=tuple(about["criteria"]),
        closed_at=_optional_time(payload["closed_at"]),
        note=payload["note"],
    )


__all__ = [
    "COMMIT_PATTERN",
    "LOCALE_PATTERN",
    "MAX_LOCALE_LENGTH",
    "MAX_TASK_NUMBER",
    "MAX_TWIN_NAME_LENGTH",
    "TASK_CODE_PATTERN",
    "TASK_CODE_PREFIX",
    "TASK_CUT_MARK",
    "AlignedPoint",
    "AlignmentStatus",
    "AlignmentVerdict",
    "ChangeDecision",
    "ChangeReviewRun",
    "ChangeReviewSummary",
    "ChangedFile",
    "ChangedFileKind",
    "CodeChange",
    "CodeChangeAmbiguous",
    "CodeTask",
    "CritiqueFinding",
    "CritiqueVerdict",
    "DecisionKind",
    "FindingSeverity",
    "TaskOrigin",
    "TaskSource",
    "TaskStatus",
    "TwinCritique",
    "aligned_change",
    "alignment_verdict_from_snapshot",
    "changed_file_from_snapshot",
    "code_task_code",
    "code_task_from_snapshot",
    "commit_prefix",
    "create_code_change",
    "critique_finding_from_snapshot",
    "finding_task_text",
    "normalize_author",
    "normalize_commit",
    "normalize_diff",
    "normalize_message",
    "normalize_note",
    "normalize_path",
    "normalize_task_note",
    "normalize_task_text",
    "normalized_block",
    "normalized_line",
    "pending_changes",
    "task_number",
    "twin_critique_from_snapshot",
]
