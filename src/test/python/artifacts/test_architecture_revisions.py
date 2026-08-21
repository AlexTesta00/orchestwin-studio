"""Tests for owner-controlled immutable Architecture Package revisions."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

from orchestwin.artifacts.architecture_revisions import (
    ArchitectureArtifactKind,
    ArchitectureChangeKind,
    ArchitecturePackageDiffStatus,
    ArchitectureRevisionDecision,
    ArchitectureRevisionDecisionStatus,
    ArchitectureRevisionIssueCode,
    ArchitectureRevisionProposalStatus,
    decide_architecture_revision,
    propose_architecture_revision,
)

from .architecture_fixtures import (
    ARCHITECTURE_CREATED_AT,
    OWNER_ID,
    architecture_version,
)

DIFF_ID = UUID("00000000-0000-4000-8000-000000000801")
VERSION_TWO_ID = UUID("00000000-0000-4000-8000-000000000802")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000000803")


def revised_package():
    """Create a valid package revision with architecture and review changes."""
    base = architecture_version()
    revised_architecture = replace(
        base.package.architecture,
        summary=(
            "A refined client-server architecture with explicit ownership and "
            "deterministic verification boundaries."
        ),
    )

    return replace(
        base.package,
        architecture=revised_architecture,
        open_questions=(
            *base.package.open_questions,
            "Which database adapter should be selected after capability negotiation?",
        ),
    )


def proposed_diff():
    """Create one explicit replacement diff against version one."""
    base = architecture_version()
    result = propose_architecture_revision(
        diff_id=DIFF_ID,
        owner_user_id=OWNER_ID,
        base_version=base,
        proposed_package=revised_package(),
        created_at=ARCHITECTURE_CREATED_AT + timedelta(minutes=1),
    )

    assert result.status is ArchitectureRevisionProposalStatus.CREATED
    assert result.diff is not None

    return base, result.diff


def test_revision_exposes_explicit_architecture_and_question_changes() -> None:
    """Represent owner edits as reviewable replacements, not in-place mutation."""
    base, diff = proposed_diff()

    assert diff.status is ArchitecturePackageDiffStatus.PROPOSED
    assert base.package.architecture.summary != diff.proposed_package.architecture.summary
    assert tuple((change.artifact_kind, change.kind) for change in diff.changes) == (
        (ArchitectureArtifactKind.ARCHITECTURE, ArchitectureChangeKind.REPLACE),
        (ArchitectureArtifactKind.OPEN_QUESTIONS, ArchitectureChangeKind.REPLACE),
    )


def test_approved_diff_creates_version_two_without_mutating_version_one() -> None:
    """Materialize N+1 only after an explicit owner approval."""
    base, diff = proposed_diff()
    decision = decide_architecture_revision(
        diff=diff,
        current_version=base,
        decision=ArchitectureRevisionDecision.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=ARCHITECTURE_CREATED_AT + timedelta(minutes=2),
        resulting_version_id=VERSION_TWO_ID,
    )

    assert decision.status is ArchitectureRevisionDecisionStatus.APPLIED
    assert decision.version is not None
    assert decision.version.id == VERSION_TWO_ID
    assert decision.version.version_number == 2
    assert decision.version.based_on_version_number == 1
    assert decision.version.package == diff.proposed_package
    assert decision.diff.status is ArchitecturePackageDiffStatus.APPROVED
    assert decision.diff.applied_version_id == VERSION_TWO_ID
    assert base.version_number == 1


def test_rejection_requires_reason_and_creates_no_version() -> None:
    """Keep rejected proposals auditable without materializing package content."""
    base, diff = proposed_diff()
    missing_reason = decide_architecture_revision(
        diff=diff,
        current_version=base,
        decision=ArchitectureRevisionDecision.REJECT,
        actor_user_id=OWNER_ID,
        occurred_at=ARCHITECTURE_CREATED_AT + timedelta(minutes=2),
    )

    assert missing_reason.status is ArchitectureRevisionDecisionStatus.REJECTED
    assert missing_reason.issue is ArchitectureRevisionIssueCode.REASON_REQUIRED

    rejected = decide_architecture_revision(
        diff=diff,
        current_version=base,
        decision=ArchitectureRevisionDecision.REJECT,
        actor_user_id=OWNER_ID,
        occurred_at=ARCHITECTURE_CREATED_AT + timedelta(minutes=2),
        reason="The owner wants a different component boundary.",
    )

    assert rejected.status is ArchitectureRevisionDecisionStatus.APPLIED
    assert rejected.version is None
    assert rejected.diff.status is ArchitecturePackageDiffStatus.REJECTED
    assert rejected.diff.decision_reason == "The owner wants a different component boundary."


def test_stale_or_foreign_owner_decision_is_rejected() -> None:
    """Reject decisions outside the exact current version and owner scope."""
    base, diff = proposed_diff()
    stale = replace(
        base,
        id=UUID("00000000-0000-4000-8000-000000000899"),
    )

    stale_result = decide_architecture_revision(
        diff=diff,
        current_version=stale,
        decision=ArchitectureRevisionDecision.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=ARCHITECTURE_CREATED_AT + timedelta(minutes=2),
        resulting_version_id=VERSION_TWO_ID,
    )
    foreign_owner = decide_architecture_revision(
        diff=diff,
        current_version=base,
        decision=ArchitectureRevisionDecision.APPROVE,
        actor_user_id=OTHER_OWNER_ID,
        occurred_at=ARCHITECTURE_CREATED_AT + timedelta(minutes=2),
        resulting_version_id=VERSION_TWO_ID,
    )

    assert stale_result.issue is ArchitectureRevisionIssueCode.BASE_VERSION_STALE
    assert foreign_owner.issue is ArchitectureRevisionIssueCode.ACTOR_NOT_OWNER


def test_revision_rejects_context_and_stable_code_changes() -> None:
    """Keep revisions inside one governed baseline with stable artifact identities."""
    base = architecture_version()
    changed_context = replace(
        base.package,
        grounding=replace(
            base.package.grounding,
            catalog_content_hash="e" * 64,
        ),
    )
    changed_code = replace(
        base.package,
        architecture=replace(base.package.architecture, code="ARC-099"),
    )

    context_result = propose_architecture_revision(
        diff_id=DIFF_ID,
        owner_user_id=OWNER_ID,
        base_version=base,
        proposed_package=changed_context,
        created_at=ARCHITECTURE_CREATED_AT + timedelta(minutes=1),
    )
    identifier_result = propose_architecture_revision(
        diff_id=DIFF_ID,
        owner_user_id=OWNER_ID,
        base_version=base,
        proposed_package=changed_code,
        created_at=ARCHITECTURE_CREATED_AT + timedelta(minutes=1),
    )

    assert context_result.issue is ArchitectureRevisionIssueCode.CONTEXT_CHANGED
    assert identifier_result.issue is ArchitectureRevisionIssueCode.IDENTIFIER_CHANGED
