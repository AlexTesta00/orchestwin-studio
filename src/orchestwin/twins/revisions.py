"""Immutable owner-reviewed User Twin profile revisions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.twins.epistemics import (
    EpistemicStatus,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ProfileObservation,
)
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinField,
    UserTwinLifecycleStatus,
    UserTwinProfile,
    UserTwinProfileVersion,
    create_user_modeling_snapshot,
)

USER_TWIN_PROFILE_DIFF_SCHEMA_VERSION: Final = 1

_SHA256_LENGTH: Final = 64

_FIELD_POSITION: Final = {field: position for position, field in enumerate(UserTwinField)}


class UserTwinProfileDiffStatus(StrEnum):
    """Lifecycle state of an explicit owner-reviewed profile diff."""

    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ProfileDiffProposalStatus(StrEnum):
    """Stable outcomes of diff proposal creation."""

    CREATED = "CREATED"
    REJECTED = "REJECTED"


class ProfileDiffProposalIssueCode(StrEnum):
    """Expected reasons a diff cannot be proposed."""

    TWIN_NOT_FOUND = "TWIN_NOT_FOUND"
    NO_CHANGES = "NO_CHANGES"
    INVALID_REPLACEMENT = "INVALID_REPLACEMENT"


class ProfileDiffDecisionStatus(StrEnum):
    """Stable outcomes of an owner diff decision."""

    APPLIED = "APPLIED"
    NO_CHANGE = "NO_CHANGE"
    REJECTED = "REJECTED"


class ProfileDiffDecisionIssueCode(StrEnum):
    """Expected reasons an owner decision cannot be applied."""

    ALREADY_DECIDED = "ALREADY_DECIDED"
    REASON_REQUIRED = "REASON_REQUIRED"


@dataclass(frozen=True, slots=True)
class ProfileDiffOperation:
    """One explicit replacement of a User Twin profile observation."""

    field: UserTwinField
    before: ProfileObservation | None
    after: ProfileObservation

    def __post_init__(self) -> None:
        """Protect field identity and owner-controlled epistemic provenance."""
        expected_key = self.field.observation_key

        if self.before is not None and self.before.observation_key != expected_key:
            raise ValueError("diff before observation must match its User Twin field")

        if self.after.observation_key != expected_key:
            raise ValueError("diff after observation must match its User Twin field")

        if self.before == self.after:
            raise ValueError("profile diff operation must change its observation")

        if self.after.human_validation is not HumanValidationRequirement.NOT_REQUIRED:
            raise ValueError(
                "owner-reviewed replacement must not require another human-validation step"
            )

        source_kinds = {reference.source_kind for reference in self.after.provenance.references}

        if self.after.epistemic_status is EpistemicStatus.USER_PROVIDED:
            if EvidenceSourceKind.OWNER_INPUT not in source_kinds:
                raise ValueError("USER_PROVIDED owner revisions require OWNER_INPUT evidence")

            return

        if self.after.epistemic_status is EpistemicStatus.HUMAN_VALIDATED:
            if EvidenceSourceKind.HUMAN_REVIEW not in source_kinds:
                raise ValueError("HUMAN_VALIDATED owner revisions require HUMAN_REVIEW evidence")

            return

        raise ValueError(
            "owner profile revisions may only create USER_PROVIDED or HUMAN_VALIDATED observations"
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return the deterministic representation of this operation."""
        return {
            "field": self.field.value,
            "before": (None if self.before is None else self.before.to_snapshot()),
            "after": self.after.to_snapshot(),
        }


@dataclass(frozen=True, slots=True)
class UserTwinProfileDiff:
    """Persisted proposal describing a reviewable User Twin revision."""

    id: UUID
    project_id: UUID

    base_snapshot_version_id: UUID
    base_snapshot_version_number: int
    base_snapshot_content_hash: str

    twin_id: UUID
    base_twin_version_id: UUID
    base_twin_version_number: int
    base_twin_content_hash: str

    operations: tuple[ProfileDiffOperation, ...]

    created_by_user_id: UUID
    created_at: datetime

    status: UserTwinProfileDiffStatus = UserTwinProfileDiffStatus.PROPOSED

    decided_by_user_id: UUID | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
    applied_snapshot_version_id: UUID | None = None

    def __post_init__(self) -> None:
        """Protect immutable proposal context and explicit decision metadata."""
        _positive_integer(
            self.base_snapshot_version_number,
            label="base snapshot version number",
        )
        _positive_integer(
            self.base_twin_version_number,
            label="base User Twin version number",
        )

        _require_sha256(
            self.base_snapshot_content_hash,
            label="base snapshot content hash",
        )
        _require_sha256(
            self.base_twin_content_hash,
            label="base User Twin content hash",
        )
        _aware(
            self.created_at,
            label="profile diff creation timestamp",
        )

        if not self.operations:
            raise ValueError("a User Twin profile diff requires at least one operation")

        fields = tuple(operation.field for operation in self.operations)

        if len(fields) != len(set(fields)):
            raise ValueError("a User Twin profile diff cannot contain duplicate fields")

        canonical_fields = tuple(
            sorted(
                fields,
                key=lambda field: _FIELD_POSITION[field],
            )
        )

        if fields != canonical_fields:
            raise ValueError("profile diff operations must use canonical User Twin field order")

        if self.status is UserTwinProfileDiffStatus.PROPOSED:
            if any(
                value is not None
                for value in (
                    self.decided_by_user_id,
                    self.decided_at,
                    self.decision_reason,
                    self.applied_snapshot_version_id,
                )
            ):
                raise ValueError("a proposed profile diff cannot contain decision metadata")

            return

        if self.decided_by_user_id is None or self.decided_at is None:
            raise ValueError("a decided profile diff requires actor and timestamp")

        _aware(
            self.decided_at,
            label="profile diff decision timestamp",
        )

        if self.decided_at < self.created_at:
            raise ValueError("profile diff decision cannot precede creation")

        if self.status is UserTwinProfileDiffStatus.REJECTED:
            normalized_reason = _normalized_optional_text(self.decision_reason)

            if normalized_reason is None:
                raise ValueError("a rejected profile diff requires a reason")

            if self.applied_snapshot_version_id is not None:
                raise ValueError("a rejected profile diff cannot reference an applied snapshot")

            object.__setattr__(
                self,
                "decision_reason",
                normalized_reason,
            )
            return

        if self.applied_snapshot_version_id is None:
            raise ValueError(
                "an approved profile diff must reference the resulting snapshot version"
            )

        object.__setattr__(
            self,
            "decision_reason",
            _normalized_optional_text(self.decision_reason),
        )

    def proposal_snapshot(self) -> dict[str, object]:
        """Return immutable proposal data excluding the later decision."""
        return {
            "schema_version": USER_TWIN_PROFILE_DIFF_SCHEMA_VERSION,
            "id": str(self.id),
            "project_id": str(self.project_id),
            "base_snapshot": {
                "version_id": str(self.base_snapshot_version_id),
                "version_number": (self.base_snapshot_version_number),
                "content_hash": (self.base_snapshot_content_hash),
            },
            "base_twin": {
                "twin_id": str(self.twin_id),
                "version_id": str(self.base_twin_version_id),
                "version_number": (self.base_twin_version_number),
                "content_hash": (self.base_twin_content_hash),
            },
            "operations": [operation.to_snapshot() for operation in self.operations],
            "created_by_user_id": str(self.created_by_user_id),
            "created_at": self.created_at.isoformat(),
        }

    @property
    def proposal_hash(self) -> str:
        """Return the hash of immutable diff proposal content."""
        return hashlib.sha256(
            json.dumps(
                self.proposal_snapshot(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        """Return proposal and decision metadata for API/audit use."""
        return {
            "proposal": self.proposal_snapshot(),
            "proposal_hash": self.proposal_hash,
            "status": self.status.value,
            "decision": {
                "decided_by_user_id": (
                    None if self.decided_by_user_id is None else str(self.decided_by_user_id)
                ),
                "decided_at": (None if self.decided_at is None else self.decided_at.isoformat()),
                "reason": self.decision_reason,
                "applied_snapshot_version_id": (
                    None
                    if self.applied_snapshot_version_id is None
                    else str(self.applied_snapshot_version_id)
                ),
            },
        }


@dataclass(frozen=True, slots=True)
class ProfileDiffProposalResult:
    """Typed result of constructing a profile diff."""

    status: ProfileDiffProposalStatus
    diff: UserTwinProfileDiff | None = None
    issue: ProfileDiffProposalIssueCode | None = None

    def __post_init__(self) -> None:
        """Protect success and rejection shapes."""
        created = self.status is ProfileDiffProposalStatus.CREATED

        if created != (self.diff is not None):
            raise ValueError("created profile diff results require exactly one diff")

        if created == (self.issue is not None):
            raise ValueError("rejected profile diff results require exactly one issue")


@dataclass(frozen=True, slots=True)
class ProfileDiffDecisionResult:
    """Typed result of approving or rejecting a diff."""

    status: ProfileDiffDecisionStatus
    diff: UserTwinProfileDiff
    issue: ProfileDiffDecisionIssueCode | None = None

    def __post_init__(self) -> None:
        """Associate issues only with rejected decisions."""
        rejected = self.status is ProfileDiffDecisionStatus.REJECTED

        if rejected != (self.issue is not None):
            raise ValueError("rejected profile diff decisions require exactly one issue")


@dataclass(frozen=True, slots=True)
class UserTwinProfileRevision:
    """New immutable User Twin and snapshot versions produced by approval."""

    twin_version: UserTwinProfileVersion
    snapshot_version: UserModelingSnapshotVersion


def propose_user_twin_profile_diff(
    *,
    base_snapshot_version: UserModelingSnapshotVersion,
    twin_id: UUID,
    replacements: Mapping[
        UserTwinField,
        ProfileObservation,
    ],
    diff_id: UUID,
    created_by_user_id: UUID,
    created_at: datetime,
) -> ProfileDiffProposalResult:
    """Build an explicit reviewable diff against one exact snapshot."""
    base_twin = _find_twin(
        base_snapshot_version,
        twin_id,
    )

    if base_twin is None:
        return ProfileDiffProposalResult(
            status=ProfileDiffProposalStatus.REJECTED,
            issue=ProfileDiffProposalIssueCode.TWIN_NOT_FOUND,
        )

    operations: list[ProfileDiffOperation] = []

    try:
        for field in sorted(
            replacements,
            key=lambda item: _FIELD_POSITION[item],
        ):
            after = replacements[field]
            before = base_twin.profile.observation_for(field)

            if before == after:
                continue

            operations.append(
                ProfileDiffOperation(
                    field=field,
                    before=before,
                    after=after,
                )
            )
    except ValueError:
        return ProfileDiffProposalResult(
            status=ProfileDiffProposalStatus.REJECTED,
            issue=(ProfileDiffProposalIssueCode.INVALID_REPLACEMENT),
        )

    if not operations:
        return ProfileDiffProposalResult(
            status=ProfileDiffProposalStatus.REJECTED,
            issue=ProfileDiffProposalIssueCode.NO_CHANGES,
        )

    operations_tuple = tuple(operations)

    try:
        _profile_with_operations(
            base_twin.profile,
            operations_tuple,
        )
    except ValueError:
        return ProfileDiffProposalResult(
            status=ProfileDiffProposalStatus.REJECTED,
            issue=(ProfileDiffProposalIssueCode.INVALID_REPLACEMENT),
        )

    diff = UserTwinProfileDiff(
        id=diff_id,
        project_id=(base_snapshot_version.project_id),
        base_snapshot_version_id=(base_snapshot_version.id),
        base_snapshot_version_number=(base_snapshot_version.version_number),
        base_snapshot_content_hash=(base_snapshot_version.content_hash),
        twin_id=twin_id,
        base_twin_version_id=(base_twin.id),
        base_twin_version_number=(base_twin.version_number),
        base_twin_content_hash=(base_twin.content_hash),
        operations=operations_tuple,
        created_by_user_id=(created_by_user_id),
        created_at=_aware(
            created_at,
            label="profile diff creation timestamp",
        ),
    )

    return ProfileDiffProposalResult(
        status=ProfileDiffProposalStatus.CREATED,
        diff=diff,
    )


def approve_user_twin_profile_diff(
    diff: UserTwinProfileDiff,
    *,
    actor_user_id: UUID,
    occurred_at: datetime,
    applied_snapshot_version_id: UUID,
    reason: str | None = None,
) -> ProfileDiffDecisionResult:
    """Approve one pending diff without yet mutating any profile."""
    if diff.status is UserTwinProfileDiffStatus.APPROVED:
        return ProfileDiffDecisionResult(
            status=ProfileDiffDecisionStatus.NO_CHANGE,
            diff=diff,
        )

    if diff.status is UserTwinProfileDiffStatus.REJECTED:
        return ProfileDiffDecisionResult(
            status=ProfileDiffDecisionStatus.REJECTED,
            diff=diff,
            issue=(ProfileDiffDecisionIssueCode.ALREADY_DECIDED),
        )

    decided = replace(
        diff,
        status=(UserTwinProfileDiffStatus.APPROVED),
        decided_by_user_id=actor_user_id,
        decided_at=_aware(
            occurred_at,
            label="profile diff approval timestamp",
        ),
        decision_reason=reason,
        applied_snapshot_version_id=(applied_snapshot_version_id),
    )

    return ProfileDiffDecisionResult(
        status=ProfileDiffDecisionStatus.APPLIED,
        diff=decided,
    )


def reject_user_twin_profile_diff(
    diff: UserTwinProfileDiff,
    *,
    actor_user_id: UUID,
    occurred_at: datetime,
    reason: str,
) -> ProfileDiffDecisionResult:
    """Reject one pending diff with an explicit owner reason."""
    if diff.status is UserTwinProfileDiffStatus.REJECTED:
        return ProfileDiffDecisionResult(
            status=ProfileDiffDecisionStatus.NO_CHANGE,
            diff=diff,
        )

    if diff.status is UserTwinProfileDiffStatus.APPROVED:
        return ProfileDiffDecisionResult(
            status=ProfileDiffDecisionStatus.REJECTED,
            diff=diff,
            issue=(ProfileDiffDecisionIssueCode.ALREADY_DECIDED),
        )

    normalized_reason = _normalized_optional_text(reason)

    if normalized_reason is None:
        return ProfileDiffDecisionResult(
            status=ProfileDiffDecisionStatus.REJECTED,
            diff=diff,
            issue=(ProfileDiffDecisionIssueCode.REASON_REQUIRED),
        )

    decided = replace(
        diff,
        status=(UserTwinProfileDiffStatus.REJECTED),
        decided_by_user_id=actor_user_id,
        decided_at=_aware(
            occurred_at,
            label="profile diff rejection timestamp",
        ),
        decision_reason=normalized_reason,
    )

    return ProfileDiffDecisionResult(
        status=ProfileDiffDecisionStatus.APPLIED,
        diff=decided,
    )


def materialize_approved_user_twin_profile_diff(
    *,
    base_snapshot_version: UserModelingSnapshotVersion,
    approved_diff: UserTwinProfileDiff,
    twin_version_id: UUID,
    created_by_user_id: UUID,
    created_at: datetime,
) -> UserTwinProfileRevision:
    """Create immutable User Twin and snapshot versions from an approved diff."""
    if approved_diff.status is not UserTwinProfileDiffStatus.APPROVED:
        raise ValueError("only an approved profile diff can create new versions")

    if (
        approved_diff.project_id != base_snapshot_version.project_id
        or approved_diff.base_snapshot_version_id != base_snapshot_version.id
        or approved_diff.base_snapshot_version_number != base_snapshot_version.version_number
        or approved_diff.base_snapshot_content_hash != base_snapshot_version.content_hash
    ):
        raise ValueError("approved profile diff does not match the supplied base snapshot")

    base_twin = _find_twin(
        base_snapshot_version,
        approved_diff.twin_id,
    )

    if base_twin is None:
        raise ValueError("approved profile diff references a User Twin missing from its snapshot")

    if (
        base_twin.id != approved_diff.base_twin_version_id
        or base_twin.version_number != approved_diff.base_twin_version_number
        or base_twin.content_hash != approved_diff.base_twin_content_hash
    ):
        raise ValueError("approved profile diff does not match the exact base User Twin version")

    if base_twin.profile.validation_status is not UserTwinLifecycleStatus.PROJECT_GROUNDED_UT:
        raise ValueError(
            "Sprint 04 owner revisions only support persisted PROJECT_GROUNDED_UT profiles"
        )

    for operation in approved_diff.operations:
        current = base_twin.profile.observation_for(operation.field)

        if current != operation.before:
            raise ValueError("profile diff before-state no longer matches the base User Twin")

    revised_profile = _profile_with_operations(
        base_twin.profile,
        approved_diff.operations,
    )

    timestamp = _aware(
        created_at,
        label="profile revision creation timestamp",
    )

    revised_twin = UserTwinProfileVersion(
        id=twin_version_id,
        project_id=base_twin.project_id,
        twin_id=base_twin.twin_id,
        version_number=(base_twin.version_number + 1),
        based_on_version_number=(base_twin.version_number),
        profile=revised_profile,
        content_hash=(revised_profile.content_hash),
        created_by_user_id=(created_by_user_id),
        created_at=timestamp,
    )

    revised_twins = tuple(
        revised_twin if version.twin_id == base_twin.twin_id else version
        for version in base_snapshot_version.snapshot.twin_versions
    )

    revised_snapshot = create_user_modeling_snapshot(
        project_id=(base_snapshot_version.project_id),
        project_brief_reference=(base_snapshot_version.snapshot.project_brief_reference),
        agent_team_reference=(base_snapshot_version.snapshot.agent_team_reference),
        catalog_version=(base_snapshot_version.snapshot.catalog_version),
        catalog_content_hash=(base_snapshot_version.snapshot.catalog_content_hash),
        persona_versions=(base_snapshot_version.snapshot.persona_versions),
        twin_versions=revised_twins,
    )

    snapshot_version_id = approved_diff.applied_snapshot_version_id

    if snapshot_version_id is None:
        raise ValueError("approved diff is missing its applied snapshot version ID")

    revised_snapshot_version = UserModelingSnapshotVersion(
        id=snapshot_version_id,
        project_id=(base_snapshot_version.project_id),
        version_number=(base_snapshot_version.version_number + 1),
        based_on_version_number=(base_snapshot_version.version_number),
        snapshot=revised_snapshot,
        content_hash=(revised_snapshot.content_hash),
        created_by_user_id=(created_by_user_id),
        created_at=timestamp,
    )

    return UserTwinProfileRevision(
        twin_version=revised_twin,
        snapshot_version=(revised_snapshot_version),
    )


def _profile_with_operations(
    profile: UserTwinProfile,
    operations: tuple[
        ProfileDiffOperation,
        ...,
    ],
) -> UserTwinProfile:
    """Apply operations to a temporary immutable profile value."""
    existing = {field: profile.observation_for(field) for field in UserTwinField}

    replacements = {operation.field: operation.after for operation in operations}

    observations = tuple(
        replacements.get(
            field,
            existing[field],
        )
        for field in UserTwinField
        if (
            replacements.get(
                field,
                existing[field],
            )
            is not None
        )
    )

    return replace(
        profile,
        observations=observations,
    )


def _find_twin(
    snapshot_version: UserModelingSnapshotVersion,
    twin_id: UUID,
) -> UserTwinProfileVersion | None:
    """Find one User Twin in an immutable User Modeling snapshot."""
    for version in snapshot_version.snapshot.twin_versions:
        if version.twin_id == twin_id:
            return version

    return None


def _positive_integer(
    value: int,
    *,
    label: str,
) -> None:
    """Require a positive non-boolean integer."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be positive")


def _require_sha256(
    value: str,
    *,
    label: str,
) -> None:
    """Require a lowercase SHA-256 digest."""
    if len(value) != _SHA256_LENGTH or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _aware(
    value: datetime,
    *,
    label: str,
) -> datetime:
    """Require a timezone-aware timestamp."""
    if value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")

    return value


def _normalized_optional_text(
    value: str | None,
) -> str | None:
    """Normalize optional human-entered text."""
    if value is None:
        return None

    normalized = " ".join(value.split())

    return normalized if normalized else None
