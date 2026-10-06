from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from uuid import UUID, uuid4

from orchestwin.projects.code_changes import (
    LOCALE_PATTERN,
    MAX_LOCALE_LENGTH,
    normalize_commit,
    normalize_path,
    normalized_block,
    normalized_line,
)


class ProposalSection(StrEnum):
    REQUIREMENTS = "REQUIREMENTS"
    DESIGN = "DESIGN"
    TESTS = "TESTS"


class ProposalStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"
    SKIPPED = "SKIPPED"


MAX_PROPOSALS: Final = 12
MAX_PROPOSALS_PER_SECTION: Final = 6
MAX_TITLE_LENGTH: Final = 200
MAX_REQUEST_LENGTH: Final = MappingProxyType(
    {ProposalSection.REQUIREMENTS: 2000, ProposalSection.DESIGN: 1000, ProposalSection.TESTS: 600}
)
MAX_ANY_REQUEST_LENGTH: Final = max(MAX_REQUEST_LENGTH.values())
MAX_RATIONALE_LENGTH: Final = 400
MAX_SUMMARY_LENGTH: Final = 600
MAX_EXCERPT_LENGTH: Final = 1500
MAX_EXCERPT_LINES: Final = 15
MAX_ORIGIN_FILES: Final = 20
MAX_NOTE_LENGTH: Final = 300
MAX_COMMITS: Final = 50
MAX_CONTEXT_DIFF_TOTAL: Final = 96_000
MAX_PROPOSAL_NUMBER: Final = 999_999
PROPOSAL_CODE_PREFIX: Final = "ALN"
PROPOSAL_CODE_PATTERN: Final = r"^ALN-[0-9]{3,6}$"
_PROPOSAL_CODE: Final = re.compile(PROPOSAL_CODE_PATTERN)
_LOCALE: Final = re.compile(LOCALE_PATTERN)
_REQUIREMENT_CODE: Final = re.compile(r"REQ-[0-9]{3,6}")
_SCREEN_CODE: Final = re.compile(r"SCR-[0-9]{3,6}")
_CRITERION_CODE: Final = re.compile(r"AC-[0-9]{3,6}")
_ALTERNATIVE_CODE: Final = re.compile(r"DES-[0-9]{3,6}")
_PLACEHOLDER_ID: Final = UUID(int=0)


class ProposalAlreadyDecided(Exception):
    def __init__(self, proposal: str, status: ProposalStatus) -> None:
        super().__init__(proposal)
        self.proposal = proposal
        self.status = status


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


def _codes(values: object, pattern: re.Pattern[str], label: str) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{label} must be a tuple")
    for value in values:
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise ValueError(f"{label} holds an invalid code")
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must not repeat a code")


def proposal_code(number: int) -> str:
    _count(number, "proposal number", minimum=1)
    if number > MAX_PROPOSAL_NUMBER:
        raise ValueError(f"proposal number exceeds {MAX_PROPOSAL_NUMBER}")
    return f"{PROPOSAL_CODE_PREFIX}-{number:03d}"


def proposal_number(code: object) -> int | None:
    if not isinstance(code, str) or _PROPOSAL_CODE.fullmatch(code.upper()) is None:
        return None
    number = int(code.split("-", 1)[1])
    if number < 1 or proposal_code(number) != code.upper():
        return None
    return number


def normalize_title(value: object) -> str:
    return normalized_line(value, label="proposal title", maximum=MAX_TITLE_LENGTH)


def normalize_request(value: object, section: ProposalSection) -> str:
    return normalized_block(
        value, label=f"{section.value.lower()} request", maximum=MAX_REQUEST_LENGTH[section]
    )


def normalize_rationale(value: object) -> str:
    return normalized_line(value, label="proposal rationale", maximum=MAX_RATIONALE_LENGTH)


def normalize_summary(value: object) -> str:
    return normalized_line(value, label="alignment summary", maximum=MAX_SUMMARY_LENGTH)


def normalize_excerpt(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("origin excerpt must be a text")
    if "\x00" in value:
        raise ValueError("origin excerpt must not contain a null character")
    lines = [line.rstrip() for line in value.splitlines()]
    while lines and not lines[0]:
        del lines[0]
    while lines and not lines[-1]:
        del lines[-1]
    if not lines:
        raise ValueError("origin excerpt must not be empty")
    if len(lines) > MAX_EXCERPT_LINES:
        raise ValueError(f"origin excerpt holds at most {MAX_EXCERPT_LINES} lines")
    excerpt = "\n".join(lines)
    if len(excerpt) > MAX_EXCERPT_LENGTH:
        raise ValueError(f"origin excerpt exceeds {MAX_EXCERPT_LENGTH} characters")
    return excerpt


def normalize_note(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("decision note must be a text")
    if not value.strip():
        return None
    return normalized_block(value, label="decision note", maximum=MAX_NOTE_LENGTH)


def normalize_locale(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) > MAX_LOCALE_LENGTH
        or _LOCALE.fullmatch(value) is None
    ):
        raise ValueError("run locale must be a language tag such as it-IT")
    return value


def normalize_commits(values: object) -> tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, Iterable):
        raise ValueError("run commits must be a sequence of hashes")
    commits = tuple(normalize_commit(item, label="run commit") for item in values)
    if not 1 <= len(commits) <= MAX_COMMITS:
        raise ValueError(f"a run holds between 1 and {MAX_COMMITS} commits")
    if len(set(commits)) != len(commits):
        raise ValueError("run commits must not repeat")
    return commits


def normalize_files(values: object) -> tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, Iterable):
        raise ValueError("origin files must be a sequence of paths")
    files = tuple(normalize_path(item) for item in values)
    if not 1 <= len(files) <= MAX_ORIGIN_FILES:
        raise ValueError(f"an origin names between 1 and {MAX_ORIGIN_FILES} files")
    if len(set(files)) != len(files):
        raise ValueError("origin files must not repeat")
    return files


@dataclass(frozen=True, slots=True)
class ProposalSubjects:
    requirements: tuple[str, ...] = ()
    screens: tuple[str, ...] = ()
    criteria: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _codes(self.requirements, _REQUIREMENT_CODE, "subject requirements")
        _codes(self.screens, _SCREEN_CODE, "subject screens")
        _codes(self.criteria, _CRITERION_CODE, "subject criteria")

    def to_snapshot(self) -> dict[str, list[str]]:
        return {
            "requirements": list(self.requirements),
            "screens": list(self.screens),
            "criteria": list(self.criteria),
        }


def proposal_subjects_from_snapshot(payload: Mapping[str, object]) -> ProposalSubjects:
    if not isinstance(payload, Mapping):
        raise ValueError("proposal subjects must be an object")
    return ProposalSubjects(
        requirements=tuple(payload["requirements"]),
        screens=tuple(payload["screens"]),
        criteria=tuple(payload["criteria"]),
    )


@dataclass(frozen=True, slots=True)
class ProposalOrigin:
    commits: tuple[str, ...]
    files: tuple[str, ...]
    excerpt: str

    def __post_init__(self) -> None:
        if normalize_commits(self.commits) != self.commits:
            raise ValueError("origin commits must be normalized")
        if normalize_files(self.files) != self.files:
            raise ValueError("origin files must be normalized")
        if normalize_excerpt(self.excerpt) != self.excerpt:
            raise ValueError("origin excerpt must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        return {"commits": list(self.commits), "files": list(self.files), "excerpt": self.excerpt}


def proposal_origin_from_snapshot(payload: Mapping[str, object]) -> ProposalOrigin:
    if not isinstance(payload, Mapping):
        raise ValueError("proposal origin must be an object")
    return ProposalOrigin(
        commits=tuple(payload["commits"]),
        files=tuple(payload["files"]),
        excerpt=payload["excerpt"],
    )


def _content(
    section: object,
    title: object,
    request: object,
    rationale: object,
    subjects: object,
    origin: object,
) -> None:
    if not isinstance(section, ProposalSection):
        raise ValueError("proposal section must be a ProposalSection")
    if normalize_title(title) != title:
        raise ValueError("proposal title must be normalized")
    if normalize_request(request, section) != request:
        raise ValueError("proposal request must be normalized")
    if normalize_rationale(rationale) != rationale:
        raise ValueError("proposal rationale must be normalized")
    if not isinstance(subjects, ProposalSubjects):
        raise ValueError("proposal subjects must be a ProposalSubjects")
    if not isinstance(origin, ProposalOrigin):
        raise ValueError("proposal origin must be a ProposalOrigin")


@dataclass(frozen=True, slots=True)
class ProposedUpdate:
    section: ProposalSection
    title: str
    request: str
    rationale: str
    subjects: ProposalSubjects
    origin: ProposalOrigin

    def __post_init__(self) -> None:
        _content(self.section, self.title, self.request, self.rationale, self.subjects, self.origin)


def create_proposed_update(
    *,
    section: ProposalSection | str,
    title: str,
    request: str,
    rationale: str,
    origin: ProposalOrigin,
    subjects: ProposalSubjects | None = None,
) -> ProposedUpdate:
    chosen = ProposalSection(str(section))
    return ProposedUpdate(
        section=chosen,
        title=normalize_title(title),
        request=normalize_request(request, chosen),
        rationale=normalize_rationale(rationale),
        subjects=ProposalSubjects() if subjects is None else subjects,
        origin=origin,
    )


@dataclass(frozen=True, slots=True)
class AlignmentProposal:
    id: UUID
    run_id: UUID
    project_id: UUID
    owner_user_id: UUID
    number: int
    section: ProposalSection
    title: str
    request: str
    rationale: str
    subjects: ProposalSubjects
    origin: ProposalOrigin
    status: ProposalStatus
    created_at: datetime
    decided_at: datetime | None = None
    decision_note: str | None = None
    applied_text: str | None = None
    applied_diff_id: UUID | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("proposal ID", self.id),
            ("run ID", self.run_id),
            ("project ID", self.project_id),
            ("owner ID", self.owner_user_id),
        ):
            _uuid(value, label)
        proposal_code(self.number)
        _content(self.section, self.title, self.request, self.rationale, self.subjects, self.origin)
        if not isinstance(self.status, ProposalStatus):
            raise ValueError("proposal status must be a ProposalStatus")
        _aware(self.created_at, "proposal timestamp")
        if (self.status is ProposalStatus.PROPOSED) != (self.decided_at is None):
            raise ValueError("a proposal has a decision time exactly when it is applied or skipped")
        if self.decided_at is not None:
            _aware(self.decided_at, "decision timestamp")
        if normalize_note(self.decision_note) != self.decision_note:
            raise ValueError("decision note must be normalized")
        if self.decision_note is not None and self.status is ProposalStatus.PROPOSED:
            raise ValueError("a decision note belongs to a decided proposal")
        if self.status is not ProposalStatus.APPLIED and (
            self.applied_text is not None or self.applied_diff_id is not None
        ):
            raise ValueError("the applied text and diff belong to an APPLIED proposal")
        if (
            self.applied_text is not None
            and normalize_request(self.applied_text, self.section) != self.applied_text
        ):
            raise ValueError("applied text must be normalized")
        if self.applied_diff_id is not None:
            _uuid(self.applied_diff_id, "applied diff ID")

    @property
    def code(self) -> str:
        return proposal_code(self.number)

    @property
    def waiting(self) -> bool:
        return self.status is ProposalStatus.PROPOSED

    def with_number(self, number: int) -> AlignmentProposal:
        return replace(self, number=number)

    def with_decision(
        self,
        *,
        status: ProposalStatus,
        decided_at: datetime,
        note: str | None = None,
        applied_text: str | None = None,
        applied_diff_id: UUID | None = None,
    ) -> AlignmentProposal:
        if not self.waiting:
            raise ProposalAlreadyDecided(self.code, self.status)
        if not isinstance(status, ProposalStatus) or status is ProposalStatus.PROPOSED:
            raise ValueError("a decision applies or skips the proposal")
        if status is not ProposalStatus.APPLIED and (
            applied_text is not None or applied_diff_id is not None
        ):
            raise ValueError("a skipped proposal carries no applied text or diff")
        return replace(
            self,
            status=status,
            decided_at=decided_at,
            decision_note=normalize_note(note),
            applied_text=None
            if applied_text is None
            else normalize_request(applied_text, self.section),
            applied_diff_id=applied_diff_id,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "code": self.code,
            "section": self.section.value,
            "title": self.title,
            "request": self.request,
            "rationale": self.rationale,
            "subjects": self.subjects.to_snapshot(),
            "origin": self.origin.to_snapshot(),
            "status": self.status.value,
            "created_at": _timestamp(self.created_at),
            "decided_at": None if self.decided_at is None else _timestamp(self.decided_at),
            "decision_note": self.decision_note,
            "applied_text": self.applied_text,
            "applied_diff_id": None if self.applied_diff_id is None else str(self.applied_diff_id),
        }


def _optional_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


def _optional_time(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


def proposal_from_snapshot(
    payload: Mapping[str, object],
    *,
    project_id: UUID | None = None,
    owner_user_id: UUID | None = None,
) -> AlignmentProposal:
    number = proposal_number(payload["code"])
    if number is None or payload["code"] != proposal_code(number):
        raise ValueError("proposal code must use the ALN-NNN format")
    return AlignmentProposal(
        id=UUID(str(payload["id"])),
        run_id=UUID(str(payload["run_id"])),
        project_id=_PLACEHOLDER_ID if project_id is None else project_id,
        owner_user_id=_PLACEHOLDER_ID if owner_user_id is None else owner_user_id,
        number=number,
        section=ProposalSection(str(payload["section"])),
        title=payload["title"],
        request=payload["request"],
        rationale=payload["rationale"],
        subjects=proposal_subjects_from_snapshot(payload["subjects"]),
        origin=proposal_origin_from_snapshot(payload["origin"]),
        status=ProposalStatus(str(payload["status"])),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        decided_at=_optional_time(payload["decided_at"]),
        decision_note=payload["decision_note"],
        applied_text=payload["applied_text"],
        applied_diff_id=_optional_uuid(payload["applied_diff_id"]),
    )


def waiting_proposals(proposals: Iterable[AlignmentProposal]) -> tuple[AlignmentProposal, ...]:
    return tuple(item for item in proposals if item.waiting)


@dataclass(frozen=True, slots=True)
class KnowledgeAlignmentRun:
    id: UUID
    project_id: UUID
    owner_user_id: UUID
    from_commit: str | None
    to_commit: str
    commits: tuple[str, ...]
    locale: str
    requirements_version_number: int
    design_version_number: int
    alternative_code: str
    summary: str
    created_at: datetime
    cost_microusd: int = 0
    generation_ids: tuple[UUID, ...] = ()
    proposals: tuple[AlignmentProposal, ...] = ()

    def __post_init__(self) -> None:
        for label, value in (
            ("run ID", self.id),
            ("project ID", self.project_id),
            ("owner ID", self.owner_user_id),
        ):
            _uuid(value, label)
        if normalize_commits(self.commits) != self.commits:
            raise ValueError("run commits must be normalized")
        if normalize_commit(self.to_commit, label="run end commit") != self.to_commit:
            raise ValueError("run end commit must be lower case")
        if self.to_commit != self.commits[-1]:
            raise ValueError("a run ends with the last of its commits")
        if self.from_commit is not None:
            if normalize_commit(self.from_commit, label="run start commit") != self.from_commit:
                raise ValueError("run start commit must be lower case")
            if self.from_commit in self.commits:
                raise ValueError("a run starts before its first commit")
        normalize_locale(self.locale)
        _count(self.requirements_version_number, "requirements version number", minimum=1)
        _count(self.design_version_number, "design version number", minimum=1)
        if (
            not isinstance(self.alternative_code, str)
            or _ALTERNATIVE_CODE.fullmatch(self.alternative_code) is None
        ):
            raise ValueError("alternative code must use the DES-NNN format")
        if normalize_summary(self.summary) != self.summary:
            raise ValueError("run summary must be normalized")
        _aware(self.created_at, "run timestamp")
        _count(self.cost_microusd, "run cost")
        if not isinstance(self.generation_ids, tuple) or not all(
            isinstance(item, UUID) for item in self.generation_ids
        ):
            raise ValueError("generation IDs must be a tuple of UUID")
        if len(set(self.generation_ids)) != len(self.generation_ids):
            raise ValueError("generation IDs must not repeat")
        if not isinstance(self.proposals, tuple) or not all(
            isinstance(item, AlignmentProposal) for item in self.proposals
        ):
            raise ValueError("run proposals must be a tuple of AlignmentProposal")
        if len(self.proposals) > MAX_PROPOSALS:
            raise ValueError(f"a run holds at most {MAX_PROPOSALS} proposals")
        for section in ProposalSection:
            if sum(item.section is section for item in self.proposals) > MAX_PROPOSALS_PER_SECTION:
                raise ValueError(
                    f"a run holds at most {MAX_PROPOSALS_PER_SECTION} proposals per section"
                )
        for item in self.proposals:
            if (item.run_id, item.project_id, item.owner_user_id) != (
                self.id,
                self.project_id,
                self.owner_user_id,
            ):
                raise ValueError("every proposal belongs to its run")
        numbers = [item.number for item in self.proposals]
        if numbers != sorted(set(numbers)):
            raise ValueError("proposal numbers must be unique and ascending")

    @property
    def waiting(self) -> tuple[AlignmentProposal, ...]:
        return waiting_proposals(self.proposals)

    def reference_snapshot(self) -> dict[str, object]:
        return {
            "requirements_version_number": self.requirements_version_number,
            "design_version_number": self.design_version_number,
            "alternative_code": self.alternative_code,
        }

    def renumbered(self, first_number: int) -> KnowledgeAlignmentRun:
        return replace(
            self,
            proposals=tuple(
                item.with_number(first_number + index) for index, item in enumerate(self.proposals)
            ),
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "from_commit": self.from_commit,
            "to_commit": self.to_commit,
            "commits": list(self.commits),
            "locale": self.locale,
            "requirements_version_number": self.requirements_version_number,
            "design_version_number": self.design_version_number,
            "alternative_code": self.alternative_code,
            "summary": self.summary,
            "created_at": _timestamp(self.created_at),
            "cost_microusd": self.cost_microusd,
            "generation_ids": [str(item) for item in self.generation_ids],
            "proposals": [item.to_snapshot() for item in self.proposals],
        }


def create_run(
    *,
    project_id: UUID,
    owner_user_id: UUID,
    from_commit: str | None,
    commits: Iterable[str],
    locale: str,
    requirements_version_number: int,
    design_version_number: int,
    alternative_code: str,
    summary: str,
    created_at: datetime,
    proposals: Iterable[ProposedUpdate],
    to_commit: str | None = None,
    cost_microusd: int = 0,
    generation_ids: Iterable[UUID] = (),
    run_id: UUID | None = None,
    first_number: int = 1,
) -> KnowledgeAlignmentRun:
    identifier = uuid4() if run_id is None else run_id
    reviewed = normalize_commits(commits)
    updates = tuple(proposals)
    if not all(isinstance(item, ProposedUpdate) for item in updates):
        raise ValueError("run proposals must be ProposedUpdate items")
    return KnowledgeAlignmentRun(
        id=identifier,
        project_id=project_id,
        owner_user_id=owner_user_id,
        from_commit=None
        if from_commit is None
        else normalize_commit(from_commit, label="run start commit"),
        to_commit=reviewed[-1]
        if to_commit is None
        else normalize_commit(to_commit, label="run end commit"),
        commits=reviewed,
        locale=normalize_locale(locale),
        requirements_version_number=requirements_version_number,
        design_version_number=design_version_number,
        alternative_code=alternative_code,
        summary=normalize_summary(summary),
        created_at=created_at,
        cost_microusd=cost_microusd,
        generation_ids=tuple(generation_ids),
        proposals=tuple(
            AlignmentProposal(
                id=uuid4(),
                run_id=identifier,
                project_id=project_id,
                owner_user_id=owner_user_id,
                number=first_number + index,
                section=item.section,
                title=item.title,
                request=item.request,
                rationale=item.rationale,
                subjects=item.subjects,
                origin=item.origin,
                status=ProposalStatus.PROPOSED,
                created_at=created_at,
            )
            for index, item in enumerate(updates)
        ),
    )


def run_from_snapshot(
    payload: Mapping[str, object], *, owner_user_id: UUID | None = None
) -> KnowledgeAlignmentRun:
    project_id = UUID(str(payload["project_id"]))
    owner = _PLACEHOLDER_ID if owner_user_id is None else owner_user_id
    return KnowledgeAlignmentRun(
        id=UUID(str(payload["id"])),
        project_id=project_id,
        owner_user_id=owner,
        from_commit=payload["from_commit"],
        to_commit=payload["to_commit"],
        commits=tuple(payload["commits"]),
        locale=payload["locale"],
        requirements_version_number=payload["requirements_version_number"],
        design_version_number=payload["design_version_number"],
        alternative_code=payload["alternative_code"],
        summary=payload["summary"],
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        cost_microusd=payload["cost_microusd"],
        generation_ids=tuple(UUID(str(item)) for item in payload["generation_ids"]),
        proposals=tuple(
            proposal_from_snapshot(item, project_id=project_id, owner_user_id=owner)
            for item in payload["proposals"]
        ),
    )


__all__ = [
    "MAX_ANY_REQUEST_LENGTH",
    "MAX_COMMITS",
    "MAX_CONTEXT_DIFF_TOTAL",
    "MAX_EXCERPT_LENGTH",
    "MAX_EXCERPT_LINES",
    "MAX_NOTE_LENGTH",
    "MAX_ORIGIN_FILES",
    "MAX_PROPOSALS",
    "MAX_PROPOSALS_PER_SECTION",
    "MAX_PROPOSAL_NUMBER",
    "MAX_RATIONALE_LENGTH",
    "MAX_REQUEST_LENGTH",
    "MAX_SUMMARY_LENGTH",
    "MAX_TITLE_LENGTH",
    "PROPOSAL_CODE_PATTERN",
    "PROPOSAL_CODE_PREFIX",
    "AlignmentProposal",
    "KnowledgeAlignmentRun",
    "ProposalAlreadyDecided",
    "ProposalOrigin",
    "ProposalSection",
    "ProposalStatus",
    "ProposalSubjects",
    "ProposedUpdate",
    "create_proposed_update",
    "create_run",
    "normalize_commits",
    "normalize_excerpt",
    "normalize_files",
    "normalize_locale",
    "normalize_note",
    "normalize_rationale",
    "normalize_request",
    "normalize_summary",
    "normalize_title",
    "proposal_code",
    "proposal_from_snapshot",
    "proposal_number",
    "proposal_origin_from_snapshot",
    "proposal_subjects_from_snapshot",
    "run_from_snapshot",
    "waiting_proposals",
]
