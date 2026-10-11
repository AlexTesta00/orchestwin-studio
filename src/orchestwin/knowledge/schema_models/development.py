from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import Field

from orchestwin.knowledge.layout import KNOWLEDGE_SCHEMA_VERSION
from orchestwin.knowledge.schema_models.base import (
    _OPTIONAL,
    ApprovedVersionReference,
    CommitHash,
    Timestamp,
    Uuid,
    _AlternativeCode,
    _code,
    _Count,
    _CriterionCode,
    _OwnerNote,
    _Record,
    _RequirementCode,
    _ScreenCode,
    _Summary,
    _TwinName,
    _Version,
)
from orchestwin.knowledge.state import (
    CHANGE_REVIEWS_KIND,
    CRITIQUE_VERDICTS,
    DECISIONS,
    FILE_KINDS,
    MAX_ACTION_LENGTH,
    MAX_AUTHOR_LENGTH,
    MAX_DESIGN_REQUEST_LENGTH,
    MAX_FILES,
    MAX_FINDING_LENGTH,
    MAX_FINDINGS,
    MAX_MESSAGE_LENGTH,
    MAX_MODEL_TASKS,
    MAX_NOTE_LENGTH,
    MAX_PATH_LENGTH,
    MAX_REQUIREMENTS_REQUEST_LENGTH,
    MAX_TASK_LENGTH,
    SEVERITIES,
    STATE_KIND,
    TASK_ORIGINS,
    TASK_STATUSES,
    VERDICTS,
)

_LOCALE_PATTERN: Final = r"^[a-z]{2,3}(-[A-Z]{2})?$"

_TaskCode = Annotated[str, Field(pattern=_code("TSK"))]
_TaskText = Annotated[str, Field(min_length=1, max_length=MAX_TASK_LENGTH)]
_ChangedPath = Annotated[str, Field(min_length=1, max_length=MAX_PATH_LENGTH)]


class DesignVersionReference(ApprovedVersionReference):
    alternative_code: _AlternativeCode | None = Field(
        description="Code of the alternative the owner selected, like DES-002, or null."
    )


class DevelopmentReference(_Record):
    requirements: ApprovedVersionReference | None = Field(
        description=(
            "Approved requirements version the code is expected to implement, or null while "
            "the requirements are not approved."
        )
    )
    design: DesignVersionReference | None = Field(
        description=(
            "Approved design version the code is expected to implement, or null while the design "
            "is not approved."
        )
    )


class AlignedPoint(_Record):
    commit: CommitHash = Field(description="Commit that the owner decided is the aligned point.")
    decided_at: Timestamp = Field(description="When the owner decided it.")
    requirements_version_number: _Version | None = Field(
        description="Requirements version approved at that moment, or null when none was."
    )
    design_version_number: _Version | None = Field(
        description="Design version approved at that moment, or null when none was."
    )


class ChangedFile(_Record):
    path: _ChangedPath = Field(description="Path of the file in the repository after the commit.")
    kind: Literal[FILE_KINDS] = Field(
        description="Whether the commit added, modified, deleted or renamed the file."
    )
    added: _Count = Field(description="Number of lines the commit added to the file.")
    removed: _Count = Field(description="Number of lines the commit removed from the file.")


class RunReference(_Record):
    requirements_version_number: _Version = Field(
        description="Approved requirements version the change was reviewed against."
    )
    design_version_number: _Version = Field(
        description="Approved design version the change was reviewed against."
    )
    alternative_code: _AlternativeCode | None = Field(
        description="Code of the selected design alternative, like DES-002, or null."
    )


class ChangeReviewSummary(_Record):
    run_id: Uuid = Field(description="Latest review run of the change.")
    reviewed_at: Timestamp = Field(description="When that run completed.")
    verdict: Literal[VERDICTS] = Field(description="Alignment status decided by the model.")
    summary: _Summary = Field(description="Summary of the verdict.")
    reference: RunReference | None = Field(
        default=None,
        description=(
            "Approved versions that run was made against, or null when the Studio did not "
            "record them; left out by folders published before the reviews could become stale."
        ),
    )
    stale: Annotated[bool | None, _OPTIONAL] = Field(
        default=None,
        description=(
            "True when the reference differs from the requirements version, the design version "
            "or the selected alternative approved in this folder, so that the twins should "
            "review the change again; false without a reference or without an approved design; "
            "left out by folders published before the reviews could become stale."
        ),
    )


class ChangeDecision(_Record):
    kind: Literal[DECISIONS] = Field(description="What the owner decided about the change.")
    decided_at: Timestamp = Field(description="When the owner decided.")
    note: Annotated[str, Field(max_length=MAX_NOTE_LENGTH)] | None = Field(
        description="Owner's note on the decision, or null."
    )


class RecordedChange(_Record):
    commit: CommitHash = Field(description="Full hash of the commit.")
    parent: CommitHash | None = Field(
        description="Hash of the parent commit, or null for the first commit."
    )
    committed_at: Timestamp = Field(description="When the commit was made.")
    author: Annotated[str, Field(min_length=1, max_length=MAX_AUTHOR_LENGTH)] | None = Field(
        description="Author of the commit, or null when it is not known."
    )
    message: str = Field(
        min_length=1,
        max_length=MAX_MESSAGE_LENGTH,
        description=f"First {MAX_MESSAGE_LENGTH} characters of the commit message.",
    )
    files: list[ChangedFile] = Field(
        max_length=MAX_FILES, description="Files the commit changed; the diff is never exported."
    )
    recorded_at: Timestamp = Field(description="When the Studio recorded the change.")
    review: ChangeReviewSummary | None = Field(
        description="Verdict of the latest review run of the change, or null before any review."
    )
    decision: ChangeDecision | None = Field(
        description="Current decision of the owner on the change, or null before any decision."
    )


class CodeSubjects(_Record):
    requirements: list[_RequirementCode] = Field(
        description="Codes of the requirements concerned, like REQ-003."
    )
    screens: list[_ScreenCode] = Field(description="Codes of the screens concerned, like SCR-002.")


class TaskSubjects(CodeSubjects):
    criteria: Annotated[list[_CriterionCode] | None, _OPTIONAL] = Field(
        default=None,
        description=(
            "Codes of the acceptance criteria concerned, like AC-007; left out by folders "
            "published before the tasks had an origin."
        ),
    )


class TaskOrigin(_Record):
    kind: Literal[TASK_ORIGINS] = Field(
        description=(
            "CODE_CHANGE for a task that comes from the review of a commit, TEST_RUN for one "
            "that comes from a run of the acceptance tests, OWNER for one the owner wrote."
        )
    )
    commit: CommitHash | None = Field(
        description="Commit whose review the task comes from, or null."
    )
    test_run_id: Uuid | None = Field(
        description="Run of the acceptance tests whose review the task comes from, or null."
    )
    twin_id: Uuid | None = Field(
        description=(
            "User twin whose finding became the task, or null for a task that comes from the "
            "alignment verdict or from the owner."
        )
    )
    twin_name: _TwinName | None = Field(
        description="Display name of that user twin when the task was created, or null."
    )
    finding: Annotated[str, Field(max_length=MAX_FINDING_LENGTH)] | None = Field(
        description="Text of that finding, copied when the task was created, or null."
    )


class CodeTask(_Record):
    code: _TaskCode = Field(description="Code of the task, like TSK-001.")
    text: _TaskText = Field(description="What the code should do.")
    about: TaskSubjects = Field(
        description="Requirements, screens and acceptance criteria the task is about."
    )
    origin: Annotated[TaskOrigin | None, _OPTIONAL] = Field(
        default=None,
        description=(
            "Where the task comes from; left out by folders published before the tasks had an "
            "origin, whose tasks all come from the decision on from_commit."
        ),
    )
    from_commit: CommitHash | None = Field(
        description=(
            "Commit whose review the task comes from, the same as origin.commit, or null for a "
            "task that does not come from a commit."
        )
    )
    created_at: Timestamp = Field(description="When the task was created.")
    status: Literal[TASK_STATUSES] = Field(
        description=(
            "OPEN while the task waits; DONE once a later change is decided aligned or the owner "
            "closes it; DROPPED once the owner decides that it is no longer wanted."
        )
    )
    closed_at: Timestamp | None = Field(
        default=None,
        description=(
            "When the task became DONE or DROPPED, or null; left out by folders published before "
            "the tasks had an origin."
        ),
    )
    note: _OwnerNote | None = Field(
        default=None,
        description=(
            "Owner's note at the last change of status, or null; left out by folders published "
            "before the tasks had an origin."
        ),
    )


class StateDocument(_Record):
    schema_version: Literal[KNOWLEDGE_SCHEMA_VERSION] = Field(
        description="Version of the knowledge folder format."
    )
    kind: Literal[STATE_KIND] = Field(description="Kind of document, the development state.")
    project_id: Uuid = Field(description="Project the development belongs to.")
    reference: DevelopmentReference = Field(
        description="Approved requirements and design versions the code is expected to implement."
    )
    aligned: AlignedPoint | None = Field(
        description="Newest change the owner decided is aligned, or null before any."
    )
    changes: list[RecordedChange] = Field(description="Recorded changes, newest first.")
    tasks: list[CodeTask] = Field(description="Tasks for the code: open, done and dropped.")


class FindingSubject(_Record):
    requirement: _RequirementCode | None = Field(
        description="Code of the requirement the finding is about, or null."
    )
    screen: _ScreenCode | None = Field(
        description="Code of the screen the finding is about, or null."
    )
    file: _ChangedPath | None = Field(description="Path of the file the finding is about, or null.")


class CritiqueFinding(_Record):
    severity: Literal[SEVERITIES] = Field(description="How much the finding matters to the twin.")
    text: str = Field(max_length=MAX_FINDING_LENGTH, description="What the twin found.")
    about: FindingSubject = Field(description="Requirement, screen and file the finding is about.")
    action: Annotated[str, Field(max_length=MAX_ACTION_LENGTH)] | None = Field(
        description="What the twin suggests doing, or null."
    )


class ChangeCritique(_Record):
    twin_id: Uuid = Field(description="User twin that criticized the change.")
    twin_name: str = Field(min_length=1, description="Display name of that user twin.")
    verdict: Literal[CRITIQUE_VERDICTS] = Field(
        description="Whether the change is fine for the twin, worries it or departs from the design."
    )
    summary: _Summary = Field(description="Critique of the twin, in the language of the project.")
    findings: list[CritiqueFinding] = Field(
        max_length=MAX_FINDINGS, description="Findings of the twin, most important first."
    )


class AlignmentVerdict(_Record):
    status: Literal[VERDICTS] = Field(description="Alignment status decided by the model.")
    summary: _Summary = Field(description="Why the model decided that status.")
    affected: CodeSubjects = Field(description="Requirements and screens the change affects.")
    design_request: Annotated[str, Field(max_length=MAX_DESIGN_REQUEST_LENGTH)] | None = Field(
        description="Design change request an owner could send, or null."
    )
    requirements_request: (
        Annotated[str, Field(max_length=MAX_REQUIREMENTS_REQUEST_LENGTH)] | None
    ) = Field(description="Requirements change request an owner could send, or null.")
    code_tasks: list[Annotated[str, Field(max_length=MAX_TASK_LENGTH)]] = Field(
        max_length=MAX_MODEL_TASKS,
        description="Tasks the model proposes for the code; tasks only once the owner decides.",
    )


class ChangeReviewRun(_Record):
    id: Uuid = Field(description="Identifier of the review run.")
    commit: CommitHash = Field(description="Commit that was reviewed.")
    reviewed_at: Timestamp = Field(description="When the run completed.")
    locale: str = Field(pattern=_LOCALE_PATTERN, description="Locale of the run, like it-IT.")
    reference: RunReference = Field(
        description="Approved versions the change was reviewed against."
    )
    critiques: list[ChangeCritique] = Field(description="One critique for every approved twin.")
    alignment: AlignmentVerdict = Field(description="Alignment verdict of the model.")
    cost_microusd: _Count = Field(
        description="Cost of the generations of the run, in microdollars."
    )


class ChangeReviewsDocument(_Record):
    schema_version: Literal[KNOWLEDGE_SCHEMA_VERSION] = Field(
        description="Version of the knowledge folder format."
    )
    kind: Literal[CHANGE_REVIEWS_KIND] = Field(
        description="Kind of document, the twin critiques on the code changes."
    )
    project_id: Uuid = Field(description="Project the review runs belong to.")
    runs: list[ChangeReviewRun] = Field(description="Review runs, newest first.")
