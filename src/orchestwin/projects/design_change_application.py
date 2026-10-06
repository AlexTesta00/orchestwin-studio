from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

from orchestwin.artifacts.design import DesignAlternative
from orchestwin.artifacts.design_evaluation import DesignEvaluationError
from orchestwin.artifacts.design_packages import (
    DesignExplorationPackage,
    DesignPackageVersion,
)
from orchestwin.artifacts.design_revision_application import (
    DesignRevisionApplicationIssueCode,
    DesignRevisionResult,
    DesignRevisionStatus,
    DesignRevisionUnitOfWorkFactory,
)
from orchestwin.artifacts.design_revisions import DesignPackageDiff, DesignRevisionIssueCode
from orchestwin.models.design_change import (
    PURPOSE,
    DesignChangeRejection,
    DesignChangeUnchanged,
    bind_design_change,
    design_change_context,
    propose_design_change,
)
from orchestwin.models.proposal_evidence import (
    current_proposal_evidence,
    evidence_application,
    retain_adapter_result,
)
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.projects.requirements_primitives import snapshot_content_hash

DEFAULT_LOCALE: Final = "it-IT"
CHANGE_ROLE: Final = "DESIGN_CHANGE"
CHANGE_REJECTED: Final = "DESIGN_CHANGE_REJECTED"
INVALID_PROVIDER_OUTPUT: Final = "INVALID_PROVIDER_OUTPUT"
GENERATION_ATTEMPTS: Final = 2
RETRYABLE_CODES: Final = frozenset(
    {INVALID_PROVIDER_OUTPUT, "INCOMPLETE_OUTPUT", "RESPONSE_SCHEMA_ERROR"}
)


class DesignChangeStatus(StrEnum):
    CREATED = "CREATED"
    REJECTED = "REJECTED"


class DesignChangeIssueCode(StrEnum):
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    SPECIFICATION_NOT_FOUND = "REQUIREMENTS_SPECIFICATION_NOT_FOUND"
    DESIGN_NOT_FOUND = "DESIGN_PACKAGE_NOT_FOUND"
    ALTERNATIVE_NOT_CHOSEN = "DESIGN_ALTERNATIVE_NOT_CHOSEN"
    REVISION_PENDING = "DESIGN_REVISION_PENDING"
    PROTOTYPE_REQUIRED = "DESIGN_PROTOTYPE_REQUIRED"
    MODEL_NOT_CONFIGURED = "DESIGN_CHANGE_MODEL_NOT_CONFIGURED"
    UNCHANGED = "DESIGN_UNCHANGED"
    CONTEXT_CHANGED = "DESIGN_CONTEXT_CHANGED"
    INVALID_PROPOSAL = "INVALID_PROPOSAL"
    PERSISTENCE_REJECTED = "PERSISTENCE_REJECTED"


@dataclass(frozen=True, slots=True)
class DesignChangeResult:
    status: DesignChangeStatus
    revision: DesignRevisionResult | None = None
    changes: tuple[str, ...] = ()
    issue: DesignChangeIssueCode | None = None


class DesignRevisionProposer(Protocol):
    async def propose_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        proposed_package: DesignExplorationPackage,
    ) -> DesignRevisionResult: ...


_REVISION_ISSUES = {
    DesignRevisionApplicationIssueCode.PACKAGE_NOT_FOUND: DesignChangeIssueCode.DESIGN_NOT_FOUND,
    DesignRevisionApplicationIssueCode.DIFF_ALREADY_PENDING: (
        DesignChangeIssueCode.REVISION_PENDING
    ),
    DesignRevisionApplicationIssueCode.CONTEXT_CHANGED: DesignChangeIssueCode.CONTEXT_CHANGED,
    DesignRevisionApplicationIssueCode.PERSISTENCE_REJECTED: (
        DesignChangeIssueCode.PERSISTENCE_REJECTED
    ),
}
_DOMAIN_ISSUES = {
    DesignRevisionIssueCode.NO_CHANGES: DesignChangeIssueCode.UNCHANGED,
    DesignRevisionIssueCode.CONTEXT_CHANGED: DesignChangeIssueCode.CONTEXT_CHANGED,
}


async def _retire(role: str, code: str, reference: Mapping[str, str]) -> None:
    scope = current_proposal_evidence()
    if scope is None or scope.request is None:
        return
    await scope.event("APPLICATION_RESULT", {"status": code, **reference})
    scope.retire(role=role, code=code)


async def _accept(kind: str, snapshot: dict[str, object]) -> None:
    scope = current_proposal_evidence()
    if scope is None or scope.request is None:
        return
    await scope.event(
        "ADAPTER_ACCEPTED",
        {
            "result": snapshot,
            "generated_content_hashes": {kind: [snapshot_content_hash(snapshot)]},
            **(
                {"related_generations": list(scope.related_generations)}
                if scope.related_generations
                else {}
            ),
        },
    )


def _chosen(package: DesignExplorationPackage) -> DesignAlternative | None:
    return next(
        (item for item in package.alternatives if item.id == package.owner_selected_alternative_id),
        None,
    )


def _with_alternative(
    package: DesignExplorationPackage, alternative: DesignAlternative
) -> DesignExplorationPackage:
    return replace(
        package,
        alternatives=tuple(
            alternative if item.id == alternative.id else item for item in package.alternatives
        ),
    )


def _revision_issue(revision: DesignRevisionResult) -> DesignChangeIssueCode:
    if revision.issue in _REVISION_ISSUES:
        return _REVISION_ISSUES[revision.issue]
    return _DOMAIN_ISSUES.get(revision.domain_issue, DesignChangeIssueCode.INVALID_PROPOSAL)


def _rejected(
    issue: DesignChangeIssueCode,
    *,
    revision: DesignRevisionResult | None = None,
    changes: tuple[str, ...] = (),
) -> DesignChangeResult:
    return DesignChangeResult(
        status=DesignChangeStatus.REJECTED, revision=revision, changes=changes, issue=issue
    )


class DesignChangeApplication:
    def __init__(
        self,
        *,
        proposal_evidence_store=None,
        generator=None,
        project_service,
        requirements_query_service,
        uow_factory: DesignRevisionUnitOfWorkFactory,
        revisions: DesignRevisionProposer,
    ) -> None:
        self._proposal_evidence_store = proposal_evidence_store
        self._generator = generator
        self._projects = project_service
        self._requirements = requirements_query_service
        self._uow_factory = uow_factory
        self._revisions = revisions

    @property
    def change_available(self) -> bool:
        return self._generator is not None and self._proposal_evidence_store is not None

    async def _current(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> tuple[DesignPackageVersion | None, DesignPackageDiff | None]:
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            current = await unit.packages.current(project_id=project_id)
            if current is None:
                return None, None
            return current, await unit.diffs.current_proposed(
                project_id=project_id, base_version_id=current.id
            )

    async def _draft(self, context, alternative, specification, reference):
        for attempt in range(1, GENERATION_ATTEMPTS + 1):
            try:
                output = await propose_design_change(self._generator, context)
                try:
                    return bind_design_change(
                        output,
                        context=context,
                        current_alternative=alternative,
                        specification=specification,
                    )
                except DesignChangeUnchanged:
                    return None
                except (TypeError, ValueError) as error:
                    await retain_adapter_result(error=error, reason=str(error))
                    raise ProposalGenerationError(INVALID_PROVIDER_OUTPUT) from error
            except ProposalGenerationError as error:
                if attempt == GENERATION_ATTEMPTS or error.code not in RETRYABLE_CODES:
                    raise
                await _retire(CHANGE_ROLE, CHANGE_REJECTED, reference)
        raise RuntimeError("design change attempts are exhausted")

    @evidence_application
    async def request_change(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        owner_request: str,
        locale: str = DEFAULT_LOCALE,
    ) -> DesignChangeResult:
        version = await self._projects.current_brief(
            project_id=project_id, owner_user_id=owner_user_id
        )
        if version is None:
            return _rejected(DesignChangeIssueCode.PROJECT_NOT_FOUND)
        current, pending = await self._current(owner_user_id=owner_user_id, project_id=project_id)
        if current is None:
            return _rejected(DesignChangeIssueCode.DESIGN_NOT_FOUND)
        alternative = _chosen(current.package)
        if alternative is None:
            return _rejected(DesignChangeIssueCode.ALTERNATIVE_NOT_CHOSEN)
        if pending is not None:
            return _rejected(DesignChangeIssueCode.REVISION_PENDING)
        requirements = await self._requirements.current(
            owner_user_id=owner_user_id, project_id=project_id
        )
        if requirements is None:
            return _rejected(DesignChangeIssueCode.SPECIFICATION_NOT_FOUND)
        if not self.change_available:
            return _rejected(DesignChangeIssueCode.MODEL_NOT_CONFIGURED)
        try:
            context = design_change_context(
                project_id=project_id,
                locale=locale,
                brief=version.brief,
                requirements=requirements,
                design=current,
                owner_request=owner_request,
            )
        except DesignEvaluationError:
            return _rejected(DesignChangeIssueCode.PROTOTYPE_REQUIRED)
        except DesignChangeRejection:
            return _rejected(DesignChangeIssueCode.ALTERNATIVE_NOT_CHOSEN)
        draft = await self._draft(
            context,
            alternative,
            requirements.specification,
            {"design_version_id": str(current.id)},
        )
        if draft is None:
            await _accept(PURPOSE, alternative.to_snapshot())
            return _rejected(DesignChangeIssueCode.UNCHANGED)
        try:
            proposed = _with_alternative(current.package, draft.alternative)
        except ValueError as error:
            await retain_adapter_result(error=error, reason=str(error))
            return _rejected(DesignChangeIssueCode.INVALID_PROPOSAL)
        await _accept(PURPOSE, draft.alternative.to_snapshot())
        revision = await self._revisions.propose_revision(
            owner_user_id=owner_user_id, project_id=project_id, proposed_package=proposed
        )
        if revision.status is DesignRevisionStatus.CREATED and revision.diff is not None:
            return DesignChangeResult(
                status=DesignChangeStatus.CREATED, revision=revision, changes=draft.changes
            )
        return _rejected(_revision_issue(revision), revision=revision, changes=draft.changes)


__all__ = [
    "CHANGE_REJECTED",
    "CHANGE_ROLE",
    "DEFAULT_LOCALE",
    "DesignChangeApplication",
    "DesignChangeIssueCode",
    "DesignChangeResult",
    "DesignChangeStatus",
    "DesignRevisionProposer",
]
