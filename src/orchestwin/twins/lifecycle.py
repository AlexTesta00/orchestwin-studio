"""User Twin lifecycle policy and empirical-grounding guards."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

from orchestwin.twins.epistemics import (
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    ObservationValueKind,
)
from orchestwin.twins.user_twins import (
    UserTwinField,
    UserTwinLifecycleStatus,
    UserTwinProfile,
)


class UserTwinOwnerApprovalStatus(StrEnum):
    """Whether the current User Modeling artifact has owner approval."""

    NOT_APPROVED = "NOT_APPROVED"
    APPROVED = "APPROVED"


class UserTwinLifecycleTransitionStatus(StrEnum):
    """Stable outcomes of one lifecycle transition request."""

    APPLIED = "APPLIED"
    NO_CHANGE = "NO_CHANGE"
    REJECTED = "REJECTED"


class UserTwinLifecycleIssueCode(StrEnum):
    """Stable reasons a lifecycle transition cannot be applied."""

    INVALID_TRANSITION = "INVALID_TRANSITION"
    OWNER_APPROVAL_IS_DERIVED = "OWNER_APPROVAL_IS_DERIVED"
    OWNER_APPROVAL_REQUIRED = "OWNER_APPROVAL_REQUIRED"
    EMPIRICAL_EVIDENCE_REQUIRED = "EMPIRICAL_EVIDENCE_REQUIRED"
    EMPIRICAL_EVIDENCE_MISMATCH = "EMPIRICAL_EVIDENCE_MISMATCH"
    EMPIRICAL_COVERAGE_INCOMPLETE = "EMPIRICAL_COVERAGE_INCOMPLETE"


_FIELD_BY_KEY: Final = {field.observation_key: field for field in UserTwinField}

_FIELD_POSITION: Final = {field: position for position, field in enumerate(UserTwinField)}

_SUBSTANTIVE_VALUE_KINDS: Final = frozenset(
    {
        ObservationValueKind.TEXT,
        ObservationValueKind.ITEMS,
    }
)

_NON_EMPIRICAL_CLAIM_STATUSES: Final = frozenset(
    {
        EpistemicStatus.HUMAN_VALIDATED,
        EpistemicStatus.MODEL_INFERRED,
        EpistemicStatus.UNSUPPORTED_ASSUMPTION,
    }
)


def _ordered_fields(
    fields: set[UserTwinField],
) -> tuple[
    UserTwinField,
    ...,
]:
    """Return unique User Twin fields in canonical declaration order."""
    return tuple(
        sorted(
            fields,
            key=lambda field: _FIELD_POSITION[field],
        )
    )


@dataclass(
    frozen=True,
    slots=True,
)
class EmpiricalGroundingAssessment:
    """Inspect empirical support and remaining non-empirical claims."""

    empirically_supported_fields: tuple[
        UserTwinField,
        ...,
    ]
    empirical_evidence_mismatch_fields: tuple[
        UserTwinField,
        ...,
    ]
    non_empirical_substantive_fields: tuple[
        UserTwinField,
        ...,
    ]
    empirical_evidence_reference_count: int

    @property
    def has_empirical_support(
        self,
    ) -> bool:
        """Return whether at least one field has valid empirical support."""
        return bool(self.empirically_supported_fields)

    @property
    def has_evidence_mismatch(
        self,
    ) -> bool:
        """Return whether an empirical label lacks empirical provenance."""
        return bool(self.empirical_evidence_mismatch_fields)

    @property
    def fully_empirically_covered(
        self,
    ) -> bool:
        """Return whether substantive non-user claims are empirical."""
        return (
            self.has_empirical_support
            and not self.has_evidence_mismatch
            and not (self.non_empirical_substantive_fields)
        )


@dataclass(
    frozen=True,
    slots=True,
)
class UserTwinLifecycleTransitionResult:
    """Typed result of one immutable lifecycle promotion."""

    status: UserTwinLifecycleTransitionStatus
    profile: UserTwinProfile
    issue: UserTwinLifecycleIssueCode | None = None

    def __post_init__(self) -> None:
        """Associate an issue exactly with rejected transitions."""
        rejected = self.status is UserTwinLifecycleTransitionStatus.REJECTED

        if rejected != (self.issue is not None):
            raise ValueError("rejected lifecycle transitions require exactly one issue")


def assess_empirical_grounding(
    profile: UserTwinProfile,
) -> EmpiricalGroundingAssessment:
    """Inspect empirical provenance and non-empirical substantive claims."""
    supported_fields: set[UserTwinField] = set()
    mismatch_fields: set[UserTwinField] = set()
    non_empirical_fields: set[UserTwinField] = set()
    empirical_references: set[EvidenceReference] = set()

    for observation in profile.observations:
        field = _FIELD_BY_KEY[observation.observation_key]

        if observation.epistemic_status is EpistemicStatus.EMPIRICALLY_SUPPORTED:
            observation_empirical_references = {
                reference
                for reference in observation.provenance.references
                if (reference.source_kind is EvidenceSourceKind.EMPIRICAL_RESEARCH)
            }

            if observation_empirical_references:
                supported_fields.add(field)
                empirical_references.update(observation_empirical_references)
            else:
                mismatch_fields.add(field)

        if (
            observation.value.kind in _SUBSTANTIVE_VALUE_KINDS
            and observation.epistemic_status in _NON_EMPIRICAL_CLAIM_STATUSES
        ):
            non_empirical_fields.add(field)

    return EmpiricalGroundingAssessment(
        empirically_supported_fields=(_ordered_fields(supported_fields)),
        empirical_evidence_mismatch_fields=(_ordered_fields(mismatch_fields)),
        non_empirical_substantive_fields=(_ordered_fields(non_empirical_fields)),
        empirical_evidence_reference_count=(len(empirical_references)),
    )


def effective_user_twin_lifecycle(
    profile: UserTwinProfile,
    *,
    owner_approval: (UserTwinOwnerApprovalStatus),
) -> UserTwinLifecycleStatus:
    """Derive owner approval without mutating the approved artifact."""
    if profile.validation_status in {
        UserTwinLifecycleStatus.PROJECT_GROUNDED_UT,
        UserTwinLifecycleStatus.OWNER_APPROVED_UT,
    }:
        if owner_approval is UserTwinOwnerApprovalStatus.APPROVED:
            return UserTwinLifecycleStatus.OWNER_APPROVED_UT

        return UserTwinLifecycleStatus.PROJECT_GROUNDED_UT

    return profile.validation_status


def promote_user_twin_lifecycle(
    profile: UserTwinProfile,
    *,
    target_status: (UserTwinLifecycleStatus),
    owner_approval: (UserTwinOwnerApprovalStatus) = (UserTwinOwnerApprovalStatus.NOT_APPROVED),
) -> UserTwinLifecycleTransitionResult:
    """Apply one policy-controlled immutable lifecycle promotion."""
    current_status = profile.validation_status

    if target_status is UserTwinLifecycleStatus.OWNER_APPROVED_UT:
        return _rejected(
            profile,
            UserTwinLifecycleIssueCode.OWNER_APPROVAL_IS_DERIVED,
        )

    if target_status is current_status:
        return UserTwinLifecycleTransitionResult(
            status=(UserTwinLifecycleTransitionStatus.NO_CHANGE),
            profile=profile,
        )

    if (
        current_status is UserTwinLifecycleStatus.PROTO_UT
        and target_status is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT
    ):
        return _applied(
            profile,
            target_status,
        )

    if (
        current_status
        in {
            UserTwinLifecycleStatus.PROJECT_GROUNDED_UT,
            UserTwinLifecycleStatus.OWNER_APPROVED_UT,
        }
        and target_status is UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT
    ):
        return _promote_to_empirically_grounded(
            profile,
            owner_approval=(owner_approval),
        )

    if (
        current_status is UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT
        and target_status is UserTwinLifecycleStatus.EMPIRICALLY_VALIDATED_UT
    ):
        return _promote_to_empirically_validated(
            profile,
            owner_approval=(owner_approval),
        )

    return _rejected(
        profile,
        UserTwinLifecycleIssueCode.INVALID_TRANSITION,
    )


def _promote_to_empirically_grounded(
    profile: UserTwinProfile,
    *,
    owner_approval: (UserTwinOwnerApprovalStatus),
) -> UserTwinLifecycleTransitionResult:
    """Promote a profile only when empirical grounding is inspectable."""
    if owner_approval is not UserTwinOwnerApprovalStatus.APPROVED:
        return _rejected(
            profile,
            UserTwinLifecycleIssueCode.OWNER_APPROVAL_REQUIRED,
        )

    assessment = assess_empirical_grounding(profile)

    if assessment.has_evidence_mismatch:
        return _rejected(
            profile,
            UserTwinLifecycleIssueCode.EMPIRICAL_EVIDENCE_MISMATCH,
        )

    if not assessment.has_empirical_support:
        return _rejected(
            profile,
            UserTwinLifecycleIssueCode.EMPIRICAL_EVIDENCE_REQUIRED,
        )

    return _applied(
        profile,
        UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT,
    )


def _promote_to_empirically_validated(
    profile: UserTwinProfile,
    *,
    owner_approval: (UserTwinOwnerApprovalStatus),
) -> UserTwinLifecycleTransitionResult:
    """Promote only when every substantive non-user claim is empirical."""
    if owner_approval is not UserTwinOwnerApprovalStatus.APPROVED:
        return _rejected(
            profile,
            UserTwinLifecycleIssueCode.OWNER_APPROVAL_REQUIRED,
        )

    assessment = assess_empirical_grounding(profile)

    if assessment.has_evidence_mismatch:
        return _rejected(
            profile,
            UserTwinLifecycleIssueCode.EMPIRICAL_EVIDENCE_MISMATCH,
        )

    if not assessment.has_empirical_support:
        return _rejected(
            profile,
            UserTwinLifecycleIssueCode.EMPIRICAL_EVIDENCE_REQUIRED,
        )

    if not (assessment.fully_empirically_covered):
        return _rejected(
            profile,
            UserTwinLifecycleIssueCode.EMPIRICAL_COVERAGE_INCOMPLETE,
        )

    return _applied(
        profile,
        UserTwinLifecycleStatus.EMPIRICALLY_VALIDATED_UT,
    )


def _applied(
    profile: UserTwinProfile,
    target_status: (UserTwinLifecycleStatus),
) -> UserTwinLifecycleTransitionResult:
    """Return a new profile with one approved persisted lifecycle state."""
    return UserTwinLifecycleTransitionResult(
        status=(UserTwinLifecycleTransitionStatus.APPLIED),
        profile=replace(
            profile,
            validation_status=(target_status),
        ),
    )


def _rejected(
    profile: UserTwinProfile,
    issue: UserTwinLifecycleIssueCode,
) -> UserTwinLifecycleTransitionResult:
    """Return one rejected transition without mutating the profile."""
    return UserTwinLifecycleTransitionResult(
        status=(UserTwinLifecycleTransitionStatus.REJECTED),
        profile=profile,
        issue=issue,
    )
