from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.agents.catalog import AGENT_CATALOG_CONTENT_HASH, AGENT_CATALOG_VERSION
from orchestwin.projects.brief_gate import project_brief_artifact_reference
from orchestwin.projects.briefs import ProjectBriefVersion, create_project_brief
from orchestwin.twins.application import GovernedUserModelingContext
from orchestwin.twins.persistence.snapshots import (
    user_modeling_snapshot_version_from_record,
    user_modeling_snapshot_version_to_record,
    user_twin_version_from_record,
    user_twin_version_to_record,
)
from orchestwin.twins.realignment import (
    UserModelingRealignment,
    realigned_user_modeling,
    user_modeling_is_aligned,
)
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    VersionedArtifactReference,
    create_user_modeling_snapshot,
)
from orchestwin.workflow.gates import HumanGate, HumanGateType
from src.test.python.knowledge.knowledge_fixtures import approved_gate
from src.test.python.knowledge.test_twin_import import OWNER_ID, Member, modeling
from src.test.python.projects.test_requirements_realignment import next_snapshot, revised
from src.test.python.twins.test_user_modeling_gate import CATALOG_HASH

PROJECT_ID = UUID("00000000-0000-4000-8000-00000000e000")
OTHER_PROJECT_ID = UUID("00000000-0000-4000-8000-00000000e001")
FIRST_SNAPSHOT_ID = UUID("00000000-0000-4000-8000-00000000e031")
SECOND_SNAPSHOT_ID = UUID("00000000-0000-4000-8000-00000000e032")
REALIGNED_SNAPSHOT_ID = UUID("00000000-0000-4000-8000-00000000e033")
FIRST_TEAM = VersionedArtifactReference(
    artifact_id=UUID("00000000-0000-4000-8000-00000000e020"),
    version_number=1,
    content_hash="4" * 64,
)
SECOND_TEAM = VersionedArtifactReference(
    artifact_id=UUID("00000000-0000-4000-8000-00000000e021"),
    version_number=2,
    content_hash="6" * 64,
)
RECEPTIONIST = Member(
    persona_id=UUID("00000000-0000-4000-8000-00000000e110"),
    twin_id=UUID("00000000-0000-4000-8000-00000000e100"),
    name="Receptionist Twin",
    role="Receptionist",
)
AUDITOR = Member(
    persona_id=UUID("00000000-0000-4000-8000-00000000e210"),
    twin_id=UUID("00000000-0000-4000-8000-00000000e200"),
    name="Night Auditor Twin",
    role="Night auditor",
)
REALIGNED_TWIN_VERSION_IDS = {
    RECEPTIONIST.twin_id: UUID("00000000-0000-4000-8000-00000000e151"),
    AUDITOR.twin_id: UUID("00000000-0000-4000-8000-00000000e251"),
}
BRIEF_WRITTEN_AT = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)
REALIGNED_AT = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def brief_version(number: int = 1) -> ProjectBriefVersion:
    brief = create_project_brief(
        name="Hotel Front Desk",
        problem=f"Guests wait too long at the front desk, draft {number}.",
        goals=("Check guests in within two minutes",),
        target_users=("Receptionist", "Night auditor"),
    )
    return ProjectBriefVersion(
        id=UUID(f"00000000-0000-4000-8000-00000000e01{number}"),
        project_id=PROJECT_ID,
        version_number=number,
        schema_version=brief.SCHEMA_VERSION,
        brief=brief,
        content_hash=brief.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=BRIEF_WRITTEN_AT,
    )


def reference_of(version: ProjectBriefVersion) -> VersionedArtifactReference:
    return VersionedArtifactReference(
        artifact_id=version.id,
        version_number=version.version_number,
        content_hash=version.content_hash,
    )


def approved_brief(version: ProjectBriefVersion) -> HumanGate:
    return approved_gate(
        version, HumanGateType.PROJECT_BRIEF, project_brief_artifact_reference(version), 7000
    )


def governed_context(
    *,
    brief: ProjectBriefVersion | None = None,
    team: VersionedArtifactReference | None = FIRST_TEAM,
    brief_approved: bool = True,
    team_approved: bool = True,
    catalog_version: int = AGENT_CATALOG_VERSION,
    catalog_hash: str = AGENT_CATALOG_CONTENT_HASH,
) -> GovernedUserModelingContext:
    version = brief_version() if brief is None else brief
    return GovernedUserModelingContext(
        project_id=PROJECT_ID,
        brief_version=version,
        brief_gate=approved_brief(version) if brief_approved else None,
        team_reference=team,
        approved_team_reference=team if team_approved else None,
        catalog_version=None if team is None else catalog_version,
        catalog_content_hash=None if team is None else catalog_hash,
    )


def first_snapshot(
    *, project_id: UUID = PROJECT_ID, catalog_hash: str = AGENT_CATALOG_CONTENT_HASH
) -> UserModelingSnapshotVersion:
    return modeling(
        project_id,
        (RECEPTIONIST, AUDITOR),
        snapshot_id=FIRST_SNAPSHOT_ID,
        brief=reference_of(brief_version()),
        team=FIRST_TEAM,
        catalog_hash=catalog_hash,
    )


def revised_snapshot() -> UserModelingSnapshotVersion:
    first = first_snapshot()
    receptionist, auditor = first.snapshot.twin_versions
    return next_snapshot(
        first,
        personas=first.snapshot.persona_versions,
        twins=(revised(receptionist, name="Front Desk Twin"), auditor),
        snapshot_id=SECOND_SNAPSHOT_ID,
    )


def realign(
    snapshot: UserModelingSnapshotVersion,
    *,
    brief: ProjectBriefVersion | None = None,
    team: VersionedArtifactReference = FIRST_TEAM,
    catalog_hash: str = AGENT_CATALOG_CONTENT_HASH,
    twin_version_ids: dict[UUID, UUID] | None = None,
    created_at: datetime = REALIGNED_AT,
) -> UserModelingRealignment:
    return realigned_user_modeling(
        snapshot,
        brief_reference=reference_of(brief_version() if brief is None else brief),
        team_reference=team,
        catalog_version=AGENT_CATALOG_VERSION,
        catalog_content_hash=catalog_hash,
        twin_version_ids=(
            REALIGNED_TWIN_VERSION_IDS if twin_version_ids is None else twin_version_ids
        ),
        snapshot_version_id=REALIGNED_SNAPSHOT_ID,
        created_by_user_id=OWNER_ID,
        created_at=created_at,
    )


def test_twins_are_aligned_only_with_the_brief_team_and_catalog_they_are_anchored_to():
    snapshot = first_snapshot()

    assert user_modeling_is_aligned(snapshot, governed_context())
    assert user_modeling_is_aligned(
        snapshot, governed_context(brief_approved=False, team_approved=False)
    )
    for context in (
        governed_context(team=SECOND_TEAM),
        governed_context(brief=brief_version(2)),
        governed_context(catalog_version=2),
        governed_context(catalog_hash="e" * 64),
        governed_context(team=None),
        replace(governed_context(), brief_version=None, brief_gate=None),
    ):
        assert not user_modeling_is_aligned(snapshot, context)
    assert not user_modeling_is_aligned(
        first_snapshot(project_id=OTHER_PROJECT_ID), governed_context()
    )


@pytest.mark.parametrize(
    ("brief_number", "team"),
    [(1, SECOND_TEAM), (2, FIRST_TEAM), (2, SECOND_TEAM)],
    ids=["new-team", "new-brief", "new-brief-and-team"],
)
def test_re_anchoring_keeps_every_twin_and_moves_only_its_anchors(brief_number, team):
    base = revised_snapshot()
    brief = brief_version(brief_number)

    realignment = realign(base, brief=brief, team=team)

    version = realignment.snapshot_version
    snapshot = version.snapshot
    assert realignment.twin_versions == snapshot.twin_versions
    for before, after in zip(base.snapshot.twin_versions, realignment.twin_versions, strict=True):
        assert (after.id, after.twin_id, after.project_id) == (
            REALIGNED_TWIN_VERSION_IDS[before.twin_id],
            before.twin_id,
            before.project_id,
        )
        assert (after.version_number, after.based_on_version_number) == (
            before.version_number + 1,
            before.version_number,
        )
        assert (after.created_by_user_id, after.created_at) == (OWNER_ID, REALIGNED_AT)
        assert after.profile.project_brief_reference == reference_of(brief)
        assert after.profile.agent_team_reference == team
        assert (
            replace(
                after.profile,
                project_brief_reference=before.profile.project_brief_reference,
                agent_team_reference=before.profile.agent_team_reference,
            )
            == before.profile
        )
        assert after.content_hash == after.profile.content_hash
        assert after.content_hash != before.content_hash
    assert [twin.profile.name for twin in snapshot.twin_versions] == [
        "Front Desk Twin",
        "Night Auditor Twin",
    ]
    assert [twin.version_number for twin in snapshot.twin_versions] == [3, 2]
    assert snapshot.persona_versions == base.snapshot.persona_versions
    assert (version.id, version.project_id) == (REALIGNED_SNAPSHOT_ID, PROJECT_ID)
    assert (version.version_number, version.based_on_version_number) == (3, 2)
    assert (version.created_by_user_id, version.created_at) == (OWNER_ID, REALIGNED_AT)
    assert version.content_hash == snapshot.content_hash
    assert version.content_hash != base.content_hash
    assert (snapshot.project_brief_reference, snapshot.agent_team_reference) == (
        reference_of(brief),
        team,
    )
    assert (snapshot.catalog_version, snapshot.catalog_content_hash) == (
        AGENT_CATALOG_VERSION,
        AGENT_CATALOG_CONTENT_HASH,
    )
    assert user_modeling_is_aligned(version, governed_context(brief=brief, team=team))
    assert not user_modeling_is_aligned(base, governed_context(brief=brief, team=team))


def test_the_re_anchored_snapshot_passes_the_domain_validation_and_the_stored_form():
    realignment = realign(revised_snapshot(), team=SECOND_TEAM)
    version = realignment.snapshot_version
    snapshot = version.snapshot

    rebuilt = create_user_modeling_snapshot(
        project_id=snapshot.project_id,
        project_brief_reference=snapshot.project_brief_reference,
        agent_team_reference=snapshot.agent_team_reference,
        catalog_version=snapshot.catalog_version,
        catalog_content_hash=snapshot.catalog_content_hash,
        persona_versions=reversed(snapshot.persona_versions),
        twin_versions=reversed(snapshot.twin_versions),
    )

    assert rebuilt == snapshot
    assert (
        user_modeling_snapshot_version_from_record(
            user_modeling_snapshot_version_to_record(version)
        )
        == version
    )
    for twin in realignment.twin_versions:
        assert user_twin_version_from_record(user_twin_version_to_record(twin)) == twin


def test_re_anchoring_also_takes_the_current_catalog():
    base = first_snapshot(catalog_hash=CATALOG_HASH)

    realignment = realign(base)

    assert realignment.snapshot_version.snapshot.catalog_content_hash == AGENT_CATALOG_CONTENT_HASH
    assert [twin.profile.catalog_content_hash for twin in realignment.twin_versions] == [
        AGENT_CATALOG_CONTENT_HASH,
        AGENT_CATALOG_CONTENT_HASH,
    ]
    assert [twin.profile.agent_team_reference for twin in realignment.twin_versions] == [
        FIRST_TEAM,
        FIRST_TEAM,
    ]
    assert user_modeling_is_aligned(realignment.snapshot_version, governed_context())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({}, "already anchored"),
        (
            {"team": SECOND_TEAM, "twin_version_ids": {RECEPTIONIST.twin_id: UUID(int=1)}},
            "one new version identifier",
        ),
        (
            {
                "team": SECOND_TEAM,
                "twin_version_ids": {
                    **REALIGNED_TWIN_VERSION_IDS,
                    UUID("00000000-0000-4000-8000-00000000e300"): UUID(int=3),
                },
            },
            "one new version identifier",
        ),
        (
            {
                "team": SECOND_TEAM,
                "twin_version_ids": {
                    RECEPTIONIST.twin_id: UUID(int=1),
                    AUDITOR.twin_id: UUID(int=1),
                },
            },
            "must be unique",
        ),
        ({"team": SECOND_TEAM, "created_at": datetime(2026, 10, 1, 9, 0)}, "timezone-aware"),
    ],
    ids=["same-anchors", "missing-twin", "unknown-twin", "repeated-identifier", "naive-time"],
)
def test_a_re_anchoring_without_new_anchors_or_with_wrong_identifiers_is_refused(changes, message):
    with pytest.raises(ValueError, match=message):
        realign(first_snapshot(), **changes)
