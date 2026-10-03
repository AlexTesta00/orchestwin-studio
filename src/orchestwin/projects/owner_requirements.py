from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from orchestwin.projects.requirements_application import (
    RequirementsGenerationIssueCode,
    RequirementsGenerationResult,
    RequirementsGenerationStatus,
    RequirementsVersionAppendStatus,
    requirements_governance_issue,
    specification_matches_context,
)
from orchestwin.projects.requirements_primitives import (
    RequirementSourceKind,
    RequirementSourceReference,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecification,
    RequirementsSpecificationVersion,
)


def owner_specification(
    specification: RequirementsSpecification, *, owner_user_id
) -> RequirementsSpecification:
    if specification.schema_version != 2:
        raise ValueError("OWNER_SPECIFICATION_SCHEMA_2_REQUIRED")
    updates = {}
    for collection in (
        "requirements",
        "scenarios",
        "risks",
        "needs",
        "journeys",
    ):
        artifacts = []
        for artifact in getattr(specification, collection):
            source = RequirementSourceReference(
                kind=RequirementSourceKind.OWNER_INPUT,
                source_id="owner-provided-definition",
                locator=f"{owner_user_id}/{collection}/{artifact.code}",
            )
            sources = tuple(
                sorted(set((*artifact.sources, source)), key=lambda item: item.sort_key)
            )
            artifacts.append(replace(artifact, sources=sources))
        updates[collection] = tuple(artifacts)
    return replace(specification, **updates)


class OwnerRequirementsService:
    def __init__(self, *, governance_port, uow_factory, uuid_factory=uuid4, clock=None) -> None:
        self._governance = governance_port
        self._uow_factory = uow_factory
        self._uuid_factory = uuid_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def create(
        self, *, owner_user_id, project_id, specification: RequirementsSpecification
    ) -> RequirementsGenerationResult:
        context = await self._governance.load_current(
            owner_user_id=owner_user_id, project_id=project_id
        )
        issue = requirements_governance_issue(context)
        if issue is not None:
            return self._rejected(issue)
        if (
            context is None
            or specification.schema_version != 2
            or not specification_matches_context(specification, context)
        ):
            return self._rejected(RequirementsGenerationIssueCode.INVALID_PROPOSAL)
        supplied = owner_specification(specification, owner_user_id=owner_user_id)
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            if not await unit.lock_project(project_id=project_id):
                return self._rejected(RequirementsGenerationIssueCode.PROJECT_NOT_FOUND)
            if await unit.specifications.current(project_id=project_id) is not None:
                return self._rejected(RequirementsGenerationIssueCode.SPECIFICATION_ALREADY_EXISTS)
            load_current = getattr(unit, "load_current_context", self._governance.load_current)
            current = await load_current(owner_user_id=owner_user_id, project_id=project_id)
            if (
                current is None
                or requirements_governance_issue(current) is not None
                or current.fingerprint != context.fingerprint
            ):
                return self._rejected(RequirementsGenerationIssueCode.CONTEXT_CHANGED)
            version = RequirementsSpecificationVersion(
                id=self._uuid_factory(),
                project_id=project_id,
                version_number=1,
                based_on_version_number=None,
                specification=supplied,
                content_hash=supplied.content_hash,
                created_by_user_id=owner_user_id,
                created_at=self._clock(),
            )
            appended = await unit.specifications.append(version)
            if appended is not RequirementsVersionAppendStatus.APPENDED:
                return RequirementsGenerationResult(
                    status=RequirementsGenerationStatus.REJECTED,
                    issue=RequirementsGenerationIssueCode.PERSISTENCE_REJECTED,
                    persistence_status=appended,
                )
            await unit.commit()
        return RequirementsGenerationResult(
            status=RequirementsGenerationStatus.CREATED, version=version
        )

    @staticmethod
    def _rejected(issue) -> RequirementsGenerationResult:
        return RequirementsGenerationResult(
            status=RequirementsGenerationStatus.REJECTED, issue=issue
        )
