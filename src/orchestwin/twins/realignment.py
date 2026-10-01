from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from orchestwin.twins.application import GovernedUserModelingContext
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinProfileVersion,
    VersionedArtifactReference,
    create_user_modeling_snapshot,
)


@dataclass(frozen=True, slots=True)
class UserModelingRealignment:
    twin_versions: tuple[UserTwinProfileVersion, ...]
    snapshot_version: UserModelingSnapshotVersion


def user_modeling_is_aligned(
    snapshot_version: UserModelingSnapshotVersion,
    context: GovernedUserModelingContext,
) -> bool:
    snapshot = snapshot_version.snapshot
    return (
        context.brief_version is not None
        and snapshot_version.project_id == context.project_id
        and snapshot.project_brief_reference == context.brief_reference
        and snapshot.agent_team_reference == context.team_reference
        and snapshot.catalog_version == context.catalog_version
        and snapshot.catalog_content_hash == context.catalog_content_hash
    )


def _reanchored_twin(
    version: UserTwinProfileVersion,
    *,
    version_id: UUID,
    brief_reference: VersionedArtifactReference,
    team_reference: VersionedArtifactReference,
    catalog_version: int,
    catalog_content_hash: str,
    created_by_user_id: UUID,
    created_at: datetime,
) -> UserTwinProfileVersion:
    profile = replace(
        version.profile,
        project_brief_reference=brief_reference,
        agent_team_reference=team_reference,
        catalog_version=catalog_version,
        catalog_content_hash=catalog_content_hash,
    )
    return UserTwinProfileVersion(
        id=version_id,
        project_id=version.project_id,
        twin_id=version.twin_id,
        version_number=version.version_number + 1,
        based_on_version_number=version.version_number,
        profile=profile,
        content_hash=profile.content_hash,
        created_by_user_id=created_by_user_id,
        created_at=created_at,
    )


def realigned_user_modeling(
    snapshot_version: UserModelingSnapshotVersion,
    *,
    brief_reference: VersionedArtifactReference,
    team_reference: VersionedArtifactReference,
    catalog_version: int,
    catalog_content_hash: str,
    twin_version_ids: Mapping[UUID, UUID],
    snapshot_version_id: UUID,
    created_by_user_id: UUID,
    created_at: datetime,
) -> UserModelingRealignment:
    snapshot = snapshot_version.snapshot
    if (
        snapshot.project_brief_reference == brief_reference
        and snapshot.agent_team_reference == team_reference
        and snapshot.catalog_version == catalog_version
        and snapshot.catalog_content_hash == catalog_content_hash
    ):
        raise ValueError("the User Modeling snapshot is already anchored to this context")
    twin_ids = {version.twin_id for version in snapshot.twin_versions}
    if set(twin_version_ids) != twin_ids:
        raise ValueError("every User Twin of the snapshot requires one new version identifier")
    if len(set(twin_version_ids.values())) != len(twin_ids):
        raise ValueError("new User Twin version identifiers must be unique")
    twin_versions = tuple(
        _reanchored_twin(
            version,
            version_id=twin_version_ids[version.twin_id],
            brief_reference=brief_reference,
            team_reference=team_reference,
            catalog_version=catalog_version,
            catalog_content_hash=catalog_content_hash,
            created_by_user_id=created_by_user_id,
            created_at=created_at,
        )
        for version in snapshot.twin_versions
    )
    realigned = create_user_modeling_snapshot(
        project_id=snapshot_version.project_id,
        project_brief_reference=brief_reference,
        agent_team_reference=team_reference,
        catalog_version=catalog_version,
        catalog_content_hash=catalog_content_hash,
        persona_versions=snapshot.persona_versions,
        twin_versions=twin_versions,
    )
    return UserModelingRealignment(
        twin_versions=twin_versions,
        snapshot_version=UserModelingSnapshotVersion(
            id=snapshot_version_id,
            project_id=snapshot_version.project_id,
            version_number=snapshot_version.version_number + 1,
            based_on_version_number=snapshot_version.version_number,
            snapshot=realigned,
            content_hash=realigned.content_hash,
            created_by_user_id=created_by_user_id,
            created_at=created_at,
        ),
    )


__all__ = [
    "UserModelingRealignment",
    "realigned_user_modeling",
    "user_modeling_is_aligned",
]
