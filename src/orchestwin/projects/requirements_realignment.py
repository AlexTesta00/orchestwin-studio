from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementsContextReference,
    UserTwinVersionReference,
    canonical_user_twin_references,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecification,
    RequirementsSpecificationVersion,
)
from orchestwin.twins.user_twins import UserModelingSnapshotVersion, VersionedArtifactReference


class RequirementsRealignmentIssue(StrEnum):
    ALREADY_ALIGNED = "REQUIREMENTS_ALREADY_ALIGNED"
    CONTEXT_CHANGED = "REQUIREMENTS_CONTEXT_CHANGED"
    PROJECT_MISMATCH = "REQUIREMENTS_PROJECT_MISMATCH"
    TWIN_NO_LONGER_AVAILABLE = "TWIN_NO_LONGER_AVAILABLE"


class RequirementsRealignmentError(Exception):
    def __init__(self, issue: RequirementsRealignmentIssue) -> None:
        super().__init__(issue.value)
        self.issue = issue
        self.code = issue.value


def snapshot_twin_references(
    snapshot: UserModelingSnapshotVersion,
) -> tuple[UserTwinVersionReference, ...]:
    return canonical_user_twin_references(
        (
            UserTwinVersionReference(
                twin_id=version.twin_id,
                version_number=version.version_number,
                content_hash=version.content_hash,
                name=version.profile.name,
            )
            for version in snapshot.snapshot.twin_versions
        ),
        require_items=True,
    )


def snapshot_reference(snapshot: UserModelingSnapshotVersion) -> RequirementsContextReference:
    return RequirementsContextReference(
        kind=RequirementsContextKind.USER_MODELING,
        artifact_id=snapshot.id,
        version_number=snapshot.version_number,
        content_hash=snapshot.content_hash,
    )


def _context_reference(
    kind: RequirementsContextKind, reference: VersionedArtifactReference
) -> RequirementsContextReference:
    return RequirementsContextReference(
        kind=kind,
        artifact_id=reference.artifact_id,
        version_number=reference.version_number,
        content_hash=reference.content_hash,
    )


def snapshot_brief_reference(snapshot: UserModelingSnapshotVersion) -> RequirementsContextReference:
    return _context_reference(
        RequirementsContextKind.PROJECT_BRIEF, snapshot.snapshot.project_brief_reference
    )


def snapshot_team_reference(snapshot: UserModelingSnapshotVersion) -> RequirementsContextReference:
    return _context_reference(
        RequirementsContextKind.AGENT_TEAM, snapshot.snapshot.agent_team_reference
    )


def referenced_twin_ids(specification: RequirementsSpecification) -> frozenset[UUID]:
    return frozenset(
        (
            *(
                reference.twin_id
                for requirement in specification.requirements
                for reference in requirement.user_twin_references
            ),
            *(story.user_twin_reference.twin_id for story in specification.user_stories),
            *(scenario.actor.twin_id for scenario in specification.scenarios),
        )
    )


def requirements_are_aligned(
    specification: RequirementsSpecification,
    snapshot: UserModelingSnapshotVersion,
) -> bool:
    modeling = snapshot.snapshot
    return (
        specification.project_brief_reference == snapshot_brief_reference(snapshot)
        and specification.agent_team_reference == snapshot_team_reference(snapshot)
        and specification.catalog_version == modeling.catalog_version
        and specification.catalog_content_hash == modeling.catalog_content_hash
        and specification.user_modeling_reference == snapshot_reference(snapshot)
        and specification.user_twin_references == snapshot_twin_references(snapshot)
    )


def realignment_issue(
    specification: RequirementsSpecification,
    snapshot: UserModelingSnapshotVersion,
) -> RequirementsRealignmentIssue | None:
    if specification.project_id != snapshot.project_id:
        return RequirementsRealignmentIssue.PROJECT_MISMATCH
    if requirements_are_aligned(specification, snapshot):
        return RequirementsRealignmentIssue.ALREADY_ALIGNED
    available = {version.twin_id for version in snapshot.snapshot.twin_versions}
    if not referenced_twin_ids(specification) <= available:
        return RequirementsRealignmentIssue.TWIN_NO_LONGER_AVAILABLE
    return None


def realign_requirements(
    specification: RequirementsSpecification,
    snapshot: UserModelingSnapshotVersion,
) -> RequirementsSpecification:
    issue = realignment_issue(specification, snapshot)
    if issue is not None:
        raise RequirementsRealignmentError(issue)
    references = snapshot_twin_references(snapshot)
    current = {reference.twin_id: reference for reference in references}
    return replace(
        specification,
        project_brief_reference=snapshot_brief_reference(snapshot),
        agent_team_reference=snapshot_team_reference(snapshot),
        catalog_version=snapshot.snapshot.catalog_version,
        catalog_content_hash=snapshot.snapshot.catalog_content_hash,
        user_modeling_reference=snapshot_reference(snapshot),
        user_twin_references=references,
        requirements=tuple(
            replace(
                requirement,
                user_twin_references=canonical_user_twin_references(
                    (current[reference.twin_id] for reference in requirement.user_twin_references),
                    require_items=False,
                ),
            )
            for requirement in specification.requirements
        ),
        user_stories=tuple(
            replace(story, user_twin_reference=current[story.user_twin_reference.twin_id])
            for story in specification.user_stories
        ),
        scenarios=tuple(
            replace(scenario, actor=current[scenario.actor.twin_id])
            for scenario in specification.scenarios
        ),
    )


def realigned_requirements_version(
    version: RequirementsSpecificationVersion,
    snapshot: UserModelingSnapshotVersion,
    *,
    version_id: UUID,
    created_by_user_id: UUID,
    created_at: datetime,
) -> RequirementsSpecificationVersion:
    specification = realign_requirements(version.specification, snapshot)
    return RequirementsSpecificationVersion(
        id=version_id,
        project_id=version.project_id,
        version_number=version.version_number + 1,
        based_on_version_number=version.version_number,
        specification=specification,
        content_hash=specification.content_hash,
        created_by_user_id=created_by_user_id,
        created_at=created_at,
    )


__all__ = [
    "RequirementsRealignmentError",
    "RequirementsRealignmentIssue",
    "realign_requirements",
    "realigned_requirements_version",
    "realignment_issue",
    "referenced_twin_ids",
    "requirements_are_aligned",
    "snapshot_brief_reference",
    "snapshot_reference",
    "snapshot_team_reference",
    "snapshot_twin_references",
]
