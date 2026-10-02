from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from orchestwin.models.proposal_evidence import evidence_application
from orchestwin.models.requirements import (
    RequirementsProposalIssueCode,
    RequirementsProposalPort,
    RequirementsProposalStatus,
)
from orchestwin.projects.requirements_application import (
    GovernedRequirementsContext,
    RequirementsGovernancePort,
    requirements_governance_issue,
    specification_matches_context,
)
from orchestwin.projects.requirements_revision_application import (
    RequirementsRevisionIssueCode,
    RequirementsRevisionResult,
    RequirementsRevisionStatus,
    RequirementsRevisionUnitOfWorkFactory,
)
from orchestwin.projects.requirements_revisions import (
    RequirementsDiffProposalIssueCode,
    RequirementsSpecificationDiff,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecification,
    RequirementsSpecificationVersion,
)


class RequirementsChangeStatus(StrEnum):
    CREATED = "CREATED"
    REJECTED = "REJECTED"


class RequirementsChangeIssueCode(StrEnum):
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    BRIEF_APPROVAL_REQUIRED = "BRIEF_APPROVAL_REQUIRED"
    TEAM_APPROVAL_REQUIRED = "TEAM_APPROVAL_REQUIRED"
    USER_MODELING_APPROVAL_REQUIRED = "USER_MODELING_APPROVAL_REQUIRED"
    SPECIFICATION_NOT_FOUND = "REQUIREMENTS_SPECIFICATION_NOT_FOUND"
    REVISION_PENDING = "REQUIREMENTS_REVISION_PENDING"
    UNCHANGED = "REQUIREMENTS_UNCHANGED"
    CONTEXT_CHANGED = "REQUIREMENTS_CONTEXT_CHANGED"
    PROPOSAL_REJECTED = "PROPOSAL_REJECTED"
    INVALID_PROPOSAL = "INVALID_PROPOSAL"
    PERSISTENCE_REJECTED = "PERSISTENCE_REJECTED"


@dataclass(frozen=True, slots=True)
class RequirementsChangeResult:
    status: RequirementsChangeStatus
    revision: RequirementsRevisionResult | None = None
    issue: RequirementsChangeIssueCode | None = None
    proposal_issue: RequirementsProposalIssueCode | None = None


class RequirementsRevisionProposer(Protocol):
    async def propose_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        proposed_specification: RequirementsSpecification,
    ) -> RequirementsRevisionResult: ...


_REVISION_ISSUES = {
    RequirementsRevisionIssueCode.SPECIFICATION_NOT_FOUND: (
        RequirementsChangeIssueCode.SPECIFICATION_NOT_FOUND
    ),
    RequirementsRevisionIssueCode.DIFF_ALREADY_PENDING: RequirementsChangeIssueCode.REVISION_PENDING,
    RequirementsRevisionIssueCode.CONTEXT_CHANGED: RequirementsChangeIssueCode.CONTEXT_CHANGED,
    RequirementsRevisionIssueCode.PERSISTENCE_REJECTED: (
        RequirementsChangeIssueCode.PERSISTENCE_REJECTED
    ),
}
_DIFF_ISSUES = {
    RequirementsDiffProposalIssueCode.NO_CHANGES: RequirementsChangeIssueCode.UNCHANGED,
    RequirementsDiffProposalIssueCode.CONTEXT_CHANGED: RequirementsChangeIssueCode.CONTEXT_CHANGED,
}


class LocalRequirementsChangeService:
    def __init__(
        self,
        *,
        proposal_evidence_store=None,
        governance: RequirementsGovernancePort,
        proposals: RequirementsProposalPort,
        uow_factory: RequirementsRevisionUnitOfWorkFactory,
        revisions: RequirementsRevisionProposer,
    ) -> None:
        self._proposal_evidence_store = proposal_evidence_store
        self._governance = governance
        self._proposals = proposals
        self._uow_factory = uow_factory
        self._revisions = revisions

    @evidence_application
    async def request_change(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        owner_request: str,
        include_journeys: bool = False,
    ) -> RequirementsChangeResult:
        context = await self._governance.load_current(
            owner_user_id=owner_user_id,
            project_id=project_id,
        )
        issue = requirements_governance_issue(context)

        if issue is not None:
            return _rejected(RequirementsChangeIssueCode(issue.value))

        if context is None:
            raise RuntimeError("ready requirements context cannot be None")

        current, pending = await self._current(
            owner_user_id=owner_user_id,
            project_id=project_id,
        )

        if current is None:
            return _rejected(RequirementsChangeIssueCode.SPECIFICATION_NOT_FOUND)

        if pending is not None:
            return _rejected(RequirementsChangeIssueCode.REVISION_PENDING)

        if not specification_matches_context(current.specification, context):
            return _rejected(RequirementsChangeIssueCode.CONTEXT_CHANGED)

        proposal = await self._proposals.propose(
            replace(
                context.to_proposal_request(),
                current_specification=current.specification,
                owner_request=owner_request,
                include_journeys=include_journeys,
            )
        )

        if proposal.status is not RequirementsProposalStatus.PROPOSED:
            return _rejected(
                RequirementsChangeIssueCode.PROPOSAL_REJECTED,
                proposal_issue=proposal.issue,
            )

        specification = proposal.specification

        if specification is None or not specification_matches_context(specification, context):
            return _rejected(RequirementsChangeIssueCode.INVALID_PROPOSAL)

        if not await self._unchanged(
            owner_user_id=owner_user_id,
            project_id=project_id,
            context=context,
            current=current,
        ):
            return _rejected(RequirementsChangeIssueCode.CONTEXT_CHANGED)

        if specification.content_hash == current.content_hash:
            return _rejected(RequirementsChangeIssueCode.UNCHANGED)

        revision = await self._revisions.propose_revision(
            owner_user_id=owner_user_id,
            project_id=project_id,
            proposed_specification=specification,
        )

        if revision.status is RequirementsRevisionStatus.CREATED and revision.diff is not None:
            return RequirementsChangeResult(
                status=RequirementsChangeStatus.CREATED,
                revision=revision,
            )

        return _rejected(_revision_issue(revision), revision=revision)

    async def _current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[RequirementsSpecificationVersion | None, RequirementsSpecificationDiff | None]:
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            current = await unit.specifications.current(project_id=project_id)

            if current is None:
                return None, None

            return current, await unit.diffs.current_proposed(
                project_id=project_id,
                base_version_id=current.id,
            )

    async def _unchanged(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        context: GovernedRequirementsContext,
        current: RequirementsSpecificationVersion,
    ) -> bool:
        latest = await self._governance.load_current(
            owner_user_id=owner_user_id,
            project_id=project_id,
        )

        if (
            latest is None
            or requirements_governance_issue(latest) is not None
            or latest.fingerprint != context.fingerprint
        ):
            return False

        version, _ = await self._current(
            owner_user_id=owner_user_id,
            project_id=project_id,
        )

        return (
            version is not None
            and version.id == current.id
            and version.content_hash == current.content_hash
        )


def _revision_issue(revision: RequirementsRevisionResult) -> RequirementsChangeIssueCode:
    if revision.issue in _REVISION_ISSUES:
        return _REVISION_ISSUES[revision.issue]

    return _DIFF_ISSUES.get(revision.proposal_issue, RequirementsChangeIssueCode.INVALID_PROPOSAL)


def _rejected(
    issue: RequirementsChangeIssueCode,
    *,
    proposal_issue: RequirementsProposalIssueCode | None = None,
    revision: RequirementsRevisionResult | None = None,
) -> RequirementsChangeResult:
    return RequirementsChangeResult(
        status=RequirementsChangeStatus.REJECTED,
        revision=revision,
        issue=issue,
        proposal_issue=proposal_issue,
    )


__all__ = [
    "LocalRequirementsChangeService",
    "RequirementsChangeIssueCode",
    "RequirementsChangeResult",
    "RequirementsChangeStatus",
    "RequirementsRevisionProposer",
]
