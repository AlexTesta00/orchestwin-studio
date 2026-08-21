from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.projects.requirements import Requirement, UserStory
from orchestwin.projects.requirements_primitives import (
    canonical_json,
    normalize_optional_text,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.projects.requirements_quality import (
    AcceptanceCriterion,
    DefinitionOfDoneItem,
    ProjectRisk,
    UsageScenario,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecification,
    RequirementsSpecificationVersion,
)

REQUIREMENTS_DIFF_SCHEMA_VERSION: Final = 1
_MAX_DECISION_REASON_LENGTH: Final = 2000

type RequirementsArtifact = (
    Requirement
    | UserStory
    | AcceptanceCriterion
    | UsageScenario
    | ProjectRisk
    | DefinitionOfDoneItem
)


class RequirementsArtifactKind(StrEnum):
    """Artifact collections that can change in a specification diff."""

    REQUIREMENT = "REQUIREMENT"
    USER_STORY = "USER_STORY"
    ACCEPTANCE_CRITERION = "ACCEPTANCE_CRITERION"
    SCENARIO = "SCENARIO"
    RISK = "RISK"
    DEFINITION_OF_DONE = "DEFINITION_OF_DONE"


class RequirementsDiffOperationKind(StrEnum):
    """Supported immutable specification changes."""

    ADD = "ADD"
    REPLACE = "REPLACE"
    REMOVE = "REMOVE"


class RequirementsDiffStatus(StrEnum):
    """Lifecycle state of an owner-reviewed requirements diff."""

    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RequirementsDiffProposalStatus(StrEnum):
    """Stable outcomes of proposing a requirements diff."""

    CREATED = "CREATED"
    REJECTED = "REJECTED"


class RequirementsDiffProposalIssueCode(StrEnum):
    """Expected reasons a requirements diff cannot be proposed."""

    PROJECT_MISMATCH = "PROJECT_MISMATCH"
    CONTEXT_CHANGED = "CONTEXT_CHANGED"
    IDENTITY_CHANGED = "IDENTITY_CHANGED"
    NO_CHANGES = "NO_CHANGES"


class RequirementsDiffDecisionStatus(StrEnum):
    """Stable outcomes of deciding a requirements diff."""

    APPLIED = "APPLIED"
    NO_CHANGE = "NO_CHANGE"
    REJECTED = "REJECTED"


class RequirementsDiffDecisionIssueCode(StrEnum):
    """Expected reasons a requirements diff decision is rejected."""

    ALREADY_DECIDED = "ALREADY_DECIDED"
    REASON_REQUIRED = "REASON_REQUIRED"


_ARTIFACT_ORDER: Final = {kind: position for position, kind in enumerate(RequirementsArtifactKind)}


@dataclass(frozen=True, slots=True)
class RequirementsDiffOperation:
    """One explicit add, replacement, or removal in a specification."""

    artifact_kind: RequirementsArtifactKind
    operation: RequirementsDiffOperationKind
    artifact_id: UUID
    before: RequirementsArtifact | None = None
    after: RequirementsArtifact | None = None

    def __post_init__(self) -> None:
        """Protect operation shape and artifact identity."""
        before_kind = None if self.before is None else _artifact_kind(self.before)
        after_kind = None if self.after is None else _artifact_kind(self.after)

        if before_kind not in {None, self.artifact_kind} or after_kind not in {
            None,
            self.artifact_kind,
        }:
            raise ValueError("requirements diff artifacts must match their declared kind")

        for artifact in (self.before, self.after):
            if artifact is not None and artifact.id != self.artifact_id:
                raise ValueError("requirements diff artifacts must preserve their identity")

        if self.operation is RequirementsDiffOperationKind.ADD:
            valid = self.before is None and self.after is not None
        elif self.operation is RequirementsDiffOperationKind.REMOVE:
            valid = self.before is not None and self.after is None
        else:
            valid = (
                self.before is not None
                and self.after is not None
                and self.before.to_snapshot() != self.after.to_snapshot()
            )

        if not valid:
            raise ValueError("requirements diff operation has an invalid before/after shape")

    @property
    def display_code(self) -> str:
        """Return the stable readable code of the changed artifact."""
        artifact = self.after if self.after is not None else self.before

        if artifact is None:
            raise RuntimeError("validated diff operation requires one artifact")

        return artifact.code

    @property
    def sort_key(self) -> tuple[int, str, str, str]:
        """Return deterministic operation ordering metadata."""
        return (
            _ARTIFACT_ORDER[self.artifact_kind],
            self.display_code,
            self.artifact_id.hex,
            self.operation.value,
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic operation snapshot."""
        return {
            "artifact_kind": self.artifact_kind.value,
            "operation": self.operation.value,
            "artifact_id": str(self.artifact_id),
            "before": None if self.before is None else self.before.to_snapshot(),
            "after": None if self.after is None else self.after.to_snapshot(),
        }


@dataclass(frozen=True, slots=True)
class RequirementsSpecificationDiff:
    """Persisted proposal for replacing one exact specification version."""

    id: UUID
    project_id: UUID
    base_version_id: UUID
    base_version_number: int
    base_content_hash: str
    proposed_specification: RequirementsSpecification
    operations: tuple[RequirementsDiffOperation, ...]
    created_by_user_id: UUID
    created_at: datetime
    status: RequirementsDiffStatus = RequirementsDiffStatus.PROPOSED
    decided_by_user_id: UUID | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
    applied_specification_version_id: UUID | None = None

    def __post_init__(self) -> None:
        """Protect immutable proposal context and decision metadata."""
        validate_positive_integer(
            self.base_version_number,
            label="base requirements version number",
        )
        validate_sha256(
            self.base_content_hash,
            label="base requirements content hash",
        )
        _require_aware(
            self.created_at,
            label="requirements diff creation timestamp",
        )

        if self.proposed_specification.project_id != self.project_id:
            raise ValueError("proposed requirements must belong to the diff project")

        if not self.operations:
            raise ValueError("a requirements diff requires at least one operation")

        if self.operations != tuple(sorted(self.operations, key=lambda value: value.sort_key)):
            raise ValueError("requirements diff operations must use canonical order")

        operation_keys = tuple(
            (operation.artifact_kind, operation.artifact_id) for operation in self.operations
        )

        if len(operation_keys) != len(set(operation_keys)):
            raise ValueError("a requirements diff cannot change one artifact more than once")

        if self.status is RequirementsDiffStatus.PROPOSED:
            if any(
                value is not None
                for value in (
                    self.decided_by_user_id,
                    self.decided_at,
                    self.decision_reason,
                    self.applied_specification_version_id,
                )
            ):
                raise ValueError("a proposed requirements diff cannot contain decision metadata")

            return

        if self.decided_by_user_id is None or self.decided_at is None:
            raise ValueError("a decided requirements diff requires actor and timestamp")

        _require_aware(
            self.decided_at,
            label="requirements diff decision timestamp",
        )

        if self.decided_at < self.created_at:
            raise ValueError("requirements diff decision cannot precede creation")

        normalized_reason = normalize_optional_text(
            self.decision_reason,
            label="requirements diff decision reason",
            maximum_length=_MAX_DECISION_REASON_LENGTH,
        )

        if self.status is RequirementsDiffStatus.REJECTED:
            if normalized_reason is None:
                raise ValueError("a rejected requirements diff requires a reason")

            if self.applied_specification_version_id is not None:
                raise ValueError("a rejected requirements diff cannot reference an applied version")
        elif self.applied_specification_version_id is None:
            raise ValueError("an approved requirements diff must reference its applied version")

        object.__setattr__(self, "decision_reason", normalized_reason)

    def proposal_snapshot(self) -> dict[str, object]:
        """Return immutable proposal data excluding the later decision."""
        return {
            "schema_version": REQUIREMENTS_DIFF_SCHEMA_VERSION,
            "id": str(self.id),
            "project_id": str(self.project_id),
            "base_version": {
                "id": str(self.base_version_id),
                "version_number": self.base_version_number,
                "content_hash": self.base_content_hash,
            },
            "proposed_specification": self.proposed_specification.to_snapshot(),
            "proposed_content_hash": self.proposed_specification.content_hash,
            "operations": [operation.to_snapshot() for operation in self.operations],
            "created_by_user_id": str(self.created_by_user_id),
            "created_at": self.created_at.isoformat(),
        }

    @property
    def proposal_hash(self) -> str:
        """Return the hash of immutable diff proposal content."""
        return snapshot_content_hash(self.proposal_snapshot())

    def to_snapshot(self) -> dict[str, object]:
        """Return proposal and decision metadata for API and audit use."""
        return {
            "proposal": self.proposal_snapshot(),
            "proposal_hash": self.proposal_hash,
            "status": self.status.value,
            "decision": {
                "decided_by_user_id": (
                    None if self.decided_by_user_id is None else str(self.decided_by_user_id)
                ),
                "decided_at": None if self.decided_at is None else self.decided_at.isoformat(),
                "reason": self.decision_reason,
                "applied_specification_version_id": (
                    None
                    if self.applied_specification_version_id is None
                    else str(self.applied_specification_version_id)
                ),
            },
        }

    def canonical_json(self) -> str:
        """Serialize this complete diff deterministically."""
        return canonical_json(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class RequirementsDiffProposalResult:
    """Typed result of constructing a requirements diff."""

    status: RequirementsDiffProposalStatus
    diff: RequirementsSpecificationDiff | None = None
    issue: RequirementsDiffProposalIssueCode | None = None

    def __post_init__(self) -> None:
        """Protect created and rejected result shapes."""
        created = self.status is RequirementsDiffProposalStatus.CREATED

        if created != (self.diff is not None):
            raise ValueError("created requirements diff results require exactly one diff")

        if created == (self.issue is not None):
            raise ValueError("rejected requirements diff results require exactly one issue")


@dataclass(frozen=True, slots=True)
class RequirementsDiffDecisionResult:
    """Typed result of approving or rejecting a requirements diff."""

    status: RequirementsDiffDecisionStatus
    diff: RequirementsSpecificationDiff
    issue: RequirementsDiffDecisionIssueCode | None = None

    def __post_init__(self) -> None:
        """Associate issues only with rejected decisions."""
        rejected = self.status is RequirementsDiffDecisionStatus.REJECTED

        if rejected != (self.issue is not None):
            raise ValueError("rejected requirements diff decisions require exactly one issue")


def propose_requirements_diff(
    *,
    base_version: RequirementsSpecificationVersion,
    proposed_specification: RequirementsSpecification,
    diff_id: UUID,
    created_by_user_id: UUID,
    created_at: datetime,
) -> RequirementsDiffProposalResult:
    """Build one explicit reviewable diff against an exact base version."""
    if proposed_specification.project_id != base_version.project_id:
        return _proposal_rejection(RequirementsDiffProposalIssueCode.PROJECT_MISMATCH)

    if not _same_context(base_version.specification, proposed_specification):
        return _proposal_rejection(RequirementsDiffProposalIssueCode.CONTEXT_CHANGED)

    if not _identities_are_stable(base_version.specification, proposed_specification):
        return _proposal_rejection(RequirementsDiffProposalIssueCode.IDENTITY_CHANGED)

    operations = _diff_operations(base_version.specification, proposed_specification)

    if not operations:
        return _proposal_rejection(RequirementsDiffProposalIssueCode.NO_CHANGES)

    return RequirementsDiffProposalResult(
        status=RequirementsDiffProposalStatus.CREATED,
        diff=RequirementsSpecificationDiff(
            id=diff_id,
            project_id=base_version.project_id,
            base_version_id=base_version.id,
            base_version_number=base_version.version_number,
            base_content_hash=base_version.content_hash,
            proposed_specification=proposed_specification,
            operations=operations,
            created_by_user_id=created_by_user_id,
            created_at=_require_aware(
                created_at,
                label="requirements diff creation timestamp",
            ),
        ),
    )


def approve_requirements_diff(
    diff: RequirementsSpecificationDiff,
    *,
    actor_user_id: UUID,
    occurred_at: datetime,
    applied_specification_version_id: UUID,
    reason: str | None = None,
) -> RequirementsDiffDecisionResult:
    """Approve one pending diff without mutating the base version."""
    if diff.status is RequirementsDiffStatus.APPROVED:
        return RequirementsDiffDecisionResult(
            status=RequirementsDiffDecisionStatus.NO_CHANGE,
            diff=diff,
        )

    if diff.status is RequirementsDiffStatus.REJECTED:
        return RequirementsDiffDecisionResult(
            status=RequirementsDiffDecisionStatus.REJECTED,
            diff=diff,
            issue=RequirementsDiffDecisionIssueCode.ALREADY_DECIDED,
        )

    normalized_reason = (
        None
        if reason is None or not reason.split()
        else normalize_optional_text(
            reason,
            label="requirements diff approval reason",
            maximum_length=_MAX_DECISION_REASON_LENGTH,
        )
    )

    return RequirementsDiffDecisionResult(
        status=RequirementsDiffDecisionStatus.APPLIED,
        diff=replace(
            diff,
            status=RequirementsDiffStatus.APPROVED,
            decided_by_user_id=actor_user_id,
            decided_at=_require_aware(
                occurred_at,
                label="requirements diff approval timestamp",
            ),
            decision_reason=normalized_reason,
            applied_specification_version_id=applied_specification_version_id,
        ),
    )


def reject_requirements_diff(
    diff: RequirementsSpecificationDiff,
    *,
    actor_user_id: UUID,
    occurred_at: datetime,
    reason: str,
) -> RequirementsDiffDecisionResult:
    """Reject one pending diff with an explicit reason."""
    if diff.status is RequirementsDiffStatus.REJECTED:
        return RequirementsDiffDecisionResult(
            status=RequirementsDiffDecisionStatus.NO_CHANGE,
            diff=diff,
        )

    if diff.status is RequirementsDiffStatus.APPROVED:
        return RequirementsDiffDecisionResult(
            status=RequirementsDiffDecisionStatus.REJECTED,
            diff=diff,
            issue=RequirementsDiffDecisionIssueCode.ALREADY_DECIDED,
        )

    if not reason.split():
        normalized_reason = None
    else:
        normalized_reason = normalize_optional_text(
            reason,
            label="requirements diff rejection reason",
            maximum_length=_MAX_DECISION_REASON_LENGTH,
        )

    if normalized_reason is None:
        return RequirementsDiffDecisionResult(
            status=RequirementsDiffDecisionStatus.REJECTED,
            diff=diff,
            issue=RequirementsDiffDecisionIssueCode.REASON_REQUIRED,
        )

    return RequirementsDiffDecisionResult(
        status=RequirementsDiffDecisionStatus.APPLIED,
        diff=replace(
            diff,
            status=RequirementsDiffStatus.REJECTED,
            decided_by_user_id=actor_user_id,
            decided_at=_require_aware(
                occurred_at,
                label="requirements diff rejection timestamp",
            ),
            decision_reason=normalized_reason,
        ),
    )


def materialize_approved_requirements_diff(
    *,
    base_version: RequirementsSpecificationVersion,
    approved_diff: RequirementsSpecificationDiff,
    created_by_user_id: UUID,
    created_at: datetime,
) -> RequirementsSpecificationVersion:
    """Create the next immutable specification version from an approved diff."""
    if approved_diff.status is not RequirementsDiffStatus.APPROVED:
        raise ValueError("requirements diff must be approved before materialization")

    if (
        approved_diff.base_version_id != base_version.id
        or approved_diff.base_version_number != base_version.version_number
        or approved_diff.base_content_hash != base_version.content_hash
    ):
        raise ValueError("requirements diff does not match the supplied base version")

    version_id = approved_diff.applied_specification_version_id

    if version_id is None:
        raise ValueError("approved requirements diff requires an applied version ID")

    return RequirementsSpecificationVersion(
        id=version_id,
        project_id=base_version.project_id,
        version_number=base_version.version_number + 1,
        based_on_version_number=base_version.version_number,
        specification=approved_diff.proposed_specification,
        content_hash=approved_diff.proposed_specification.content_hash,
        created_by_user_id=created_by_user_id,
        created_at=_require_aware(
            created_at,
            label="requirements version creation timestamp",
        ),
    )


def _artifact_kind(artifact: RequirementsArtifact) -> RequirementsArtifactKind:
    """Return the collection kind of one typed requirements artifact."""
    if isinstance(artifact, Requirement):
        return RequirementsArtifactKind.REQUIREMENT

    if isinstance(artifact, UserStory):
        return RequirementsArtifactKind.USER_STORY

    if isinstance(artifact, AcceptanceCriterion):
        return RequirementsArtifactKind.ACCEPTANCE_CRITERION

    if isinstance(artifact, UsageScenario):
        return RequirementsArtifactKind.SCENARIO

    if isinstance(artifact, ProjectRisk):
        return RequirementsArtifactKind.RISK

    return RequirementsArtifactKind.DEFINITION_OF_DONE


def _collections(
    specification: RequirementsSpecification,
) -> tuple[tuple[RequirementsArtifactKind, tuple[RequirementsArtifact, ...]], ...]:
    """Return every revisable collection in deterministic kind order."""
    return (
        (RequirementsArtifactKind.REQUIREMENT, specification.requirements),
        (RequirementsArtifactKind.USER_STORY, specification.user_stories),
        (RequirementsArtifactKind.ACCEPTANCE_CRITERION, specification.acceptance_criteria),
        (RequirementsArtifactKind.SCENARIO, specification.scenarios),
        (RequirementsArtifactKind.RISK, specification.risks),
        (RequirementsArtifactKind.DEFINITION_OF_DONE, specification.definition_of_done),
    )


def _same_context(
    base: RequirementsSpecification,
    proposed: RequirementsSpecification,
) -> bool:
    """Keep owner revisions inside the exact governed input context."""
    return (
        proposed.project_id == base.project_id
        and proposed.project_brief_reference == base.project_brief_reference
        and proposed.agent_team_reference == base.agent_team_reference
        and proposed.user_modeling_reference == base.user_modeling_reference
        and proposed.catalog_version == base.catalog_version
        and proposed.catalog_content_hash == base.catalog_content_hash
        and proposed.user_twin_references == base.user_twin_references
    )


def _identities_are_stable(
    base: RequirementsSpecification,
    proposed: RequirementsSpecification,
) -> bool:
    """Prevent display codes from moving between stable identities."""
    for (base_kind, base_values), (proposed_kind, proposed_values) in zip(
        _collections(base),
        _collections(proposed),
        strict=True,
    ):
        if base_kind is not proposed_kind:
            return False

        base_by_id = {value.id: value for value in base_values}
        proposed_by_id = {value.id: value for value in proposed_values}
        base_by_code = {value.code: value.id for value in base_values}
        proposed_by_code = {value.code: value.id for value in proposed_values}

        for artifact_id in set(base_by_id).intersection(proposed_by_id):
            if base_by_id[artifact_id].code != proposed_by_id[artifact_id].code:
                return False

        for code in set(base_by_code).intersection(proposed_by_code):
            if base_by_code[code] != proposed_by_code[code]:
                return False

    return True


def _diff_operations(
    base: RequirementsSpecification,
    proposed: RequirementsSpecification,
) -> tuple[RequirementsDiffOperation, ...]:
    """Compute explicit operations across every specification collection."""
    operations: list[RequirementsDiffOperation] = []

    for (artifact_kind, base_values), (_, proposed_values) in zip(
        _collections(base),
        _collections(proposed),
        strict=True,
    ):
        base_by_id = {value.id: value for value in base_values}
        proposed_by_id = {value.id: value for value in proposed_values}

        for artifact_id in set(base_by_id).union(proposed_by_id):
            before = base_by_id.get(artifact_id)
            after = proposed_by_id.get(artifact_id)

            if before is None:
                operation = RequirementsDiffOperationKind.ADD
            elif after is None:
                operation = RequirementsDiffOperationKind.REMOVE
            elif before.to_snapshot() != after.to_snapshot():
                operation = RequirementsDiffOperationKind.REPLACE
            else:
                continue

            operations.append(
                RequirementsDiffOperation(
                    artifact_kind=artifact_kind,
                    operation=operation,
                    artifact_id=artifact_id,
                    before=before,
                    after=after,
                )
            )

    return tuple(sorted(operations, key=lambda value: value.sort_key))


def _proposal_rejection(
    issue: RequirementsDiffProposalIssueCode,
) -> RequirementsDiffProposalResult:
    """Return one typed proposal rejection."""
    return RequirementsDiffProposalResult(
        status=RequirementsDiffProposalStatus.REJECTED,
        issue=issue,
    )


def _require_aware(value: datetime, *, label: str) -> datetime:
    """Require one timezone-aware timestamp."""
    if value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")

    return value


__all__ = [
    "REQUIREMENTS_DIFF_SCHEMA_VERSION",
    "RequirementsArtifactKind",
    "RequirementsDiffDecisionIssueCode",
    "RequirementsDiffDecisionResult",
    "RequirementsDiffDecisionStatus",
    "RequirementsDiffOperation",
    "RequirementsDiffOperationKind",
    "RequirementsDiffProposalIssueCode",
    "RequirementsDiffProposalResult",
    "RequirementsDiffProposalStatus",
    "RequirementsDiffStatus",
    "RequirementsSpecificationDiff",
    "approve_requirements_diff",
    "materialize_approved_requirements_diff",
    "propose_requirements_diff",
    "reject_requirements_diff",
]
