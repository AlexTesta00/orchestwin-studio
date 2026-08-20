"""Tests for owner-controlled immutable Design Package revisions."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

from orchestwin.artifacts.design_revisions import (
    DesignArtifactKind,
    DesignChangeKind,
    DesignPackageDiffStatus,
    DesignRevisionDecision,
    DesignRevisionDecisionStatus,
    DesignRevisionIssueCode,
    DesignRevisionProposalStatus,
    decide_design_revision,
    propose_design_revision,
)

from .design_fixtures import (
    ALTERNATIVE_ONE_ID,
    CREATED_AT,
    OWNER_ID,
    design_package,
    design_version,
)

DIFF_ID = UUID("00000000-0000-4000-8000-000000000501")
VERSION_TWO_ID = UUID("00000000-0000-4000-8000-000000000502")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000000503")


def proposed_diff():
    """Create one selection-and-prototype revision from an unselected base."""
    base = design_version(package=design_package(selected=False))
    proposed = design_package(selected=True)
    result = propose_design_revision(
        diff_id=DIFF_ID,
        owner_user_id=OWNER_ID,
        base_version=base,
        proposed_package=proposed,
        created_at=CREATED_AT + timedelta(minutes=1),
    )

    assert result.status is DesignRevisionProposalStatus.CREATED
    assert result.diff is not None

    return base, result.diff


def test_revision_exposes_selection_and_prototype_before_after_changes() -> None:
    """Create an explicit diff rather than mutating the base package."""
    base, diff = proposed_diff()

    assert base.package.owner_selected_alternative_id is None
    assert base.package.prototype is None
    assert diff.proposed_package.owner_selected_alternative_id == ALTERNATIVE_ONE_ID
    assert diff.proposed_package.prototype is not None
    assert tuple((change.artifact_kind, change.kind) for change in diff.changes) == (
        (DesignArtifactKind.PROTOTYPE, DesignChangeKind.ADD),
        (DesignArtifactKind.SELECTION, DesignChangeKind.REPLACE),
    )
    assert diff.status is DesignPackageDiffStatus.PROPOSED


def test_approved_diff_creates_version_two_without_mutating_version_one() -> None:
    """Materialize N+1 only after an explicit owner approval."""
    base, diff = proposed_diff()
    decision = decide_design_revision(
        diff=diff,
        current_version=base,
        decision=DesignRevisionDecision.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=CREATED_AT + timedelta(minutes=2),
        resulting_version_id=VERSION_TWO_ID,
    )

    assert decision.status is DesignRevisionDecisionStatus.APPLIED
    assert decision.version is not None
    assert decision.version.id == VERSION_TWO_ID
    assert decision.version.version_number == 2
    assert decision.version.based_on_version_number == 1
    assert decision.version.package.ready_for_gate is True
    assert decision.diff.status is DesignPackageDiffStatus.APPROVED
    assert decision.diff.applied_version_id == VERSION_TWO_ID
    assert base.package.ready_for_gate is False


def test_rejection_requires_reason_and_creates_no_version() -> None:
    """Keep rejected proposals auditable without materializing package content."""
    base, diff = proposed_diff()
    missing_reason = decide_design_revision(
        diff=diff,
        current_version=base,
        decision=DesignRevisionDecision.REJECT,
        actor_user_id=OWNER_ID,
        occurred_at=CREATED_AT + timedelta(minutes=2),
    )

    assert missing_reason.status is DesignRevisionDecisionStatus.REJECTED
    assert missing_reason.issue is DesignRevisionIssueCode.REASON_REQUIRED

    rejected = decide_design_revision(
        diff=diff,
        current_version=base,
        decision=DesignRevisionDecision.REJECT,
        actor_user_id=OWNER_ID,
        occurred_at=CREATED_AT + timedelta(minutes=2),
        reason="The owner wants a different prototype direction.",
    )

    assert rejected.status is DesignRevisionDecisionStatus.APPLIED
    assert rejected.version is None
    assert rejected.diff.status is DesignPackageDiffStatus.REJECTED
    assert rejected.diff.decision_reason == ("The owner wants a different prototype direction.")


def test_stale_or_foreign_owner_decision_is_rejected() -> None:
    """Reject decisions outside the exact current version and owner scope."""
    base, diff = proposed_diff()
    stale = replace(
        base,
        id=UUID("00000000-0000-4000-8000-000000000599"),
    )

    stale_result = decide_design_revision(
        diff=diff,
        current_version=stale,
        decision=DesignRevisionDecision.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=CREATED_AT + timedelta(minutes=2),
        resulting_version_id=VERSION_TWO_ID,
    )
    foreign_owner = decide_design_revision(
        diff=diff,
        current_version=base,
        decision=DesignRevisionDecision.APPROVE,
        actor_user_id=OTHER_OWNER_ID,
        occurred_at=CREATED_AT + timedelta(minutes=2),
        resulting_version_id=VERSION_TWO_ID,
    )

    assert stale_result.issue is DesignRevisionIssueCode.BASE_VERSION_STALE
    assert foreign_owner.issue is DesignRevisionIssueCode.ACTOR_NOT_OWNER


def test_revision_rejects_context_and_stable_code_changes() -> None:
    """Keep owner revisions inside one governed baseline with stable identities."""
    base = design_version()
    changed_context = replace(
        base.package,
        grounding=replace(
            base.package.grounding,
            catalog_content_hash="e" * 64,
        ),
    )
    changed_code = replace(
        base.package,
        alternatives=(
            base.package.alternatives[1],
            replace(base.package.alternatives[0], code="DES-099"),
        ),
    )

    context_result = propose_design_revision(
        diff_id=DIFF_ID,
        owner_user_id=OWNER_ID,
        base_version=base,
        proposed_package=changed_context,
        created_at=CREATED_AT + timedelta(minutes=1),
    )
    identifier_result = propose_design_revision(
        diff_id=DIFF_ID,
        owner_user_id=OWNER_ID,
        base_version=base,
        proposed_package=changed_code,
        created_at=CREATED_AT + timedelta(minutes=1),
    )

    assert context_result.issue is DesignRevisionIssueCode.CONTEXT_CHANGED
    assert identifier_result.issue is DesignRevisionIssueCode.IDENTIFIER_CHANGED
