from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.projects.requirements import (
    RequirementKind,
    RequirementPriority,
    create_requirement,
    create_user_story,
)
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementsContextReference,
    RequirementSourceKind,
    RequirementSourceReference,
    UserTwinVersionReference,
)
from orchestwin.projects.requirements_quality import (
    DefinitionOfDoneApplicability,
    RiskImpact,
    RiskLikelihood,
    VerificationMethod,
    create_acceptance_criterion,
    create_definition_of_done_item,
    create_project_risk,
    create_usage_scenario,
)
from orchestwin.projects.requirements_realignment import (
    RequirementsRealignmentError,
    RequirementsRealignmentIssue,
    realign_requirements,
    realigned_requirements_version,
    realignment_issue,
    referenced_twin_ids,
    requirements_are_aligned,
    snapshot_reference,
    snapshot_twin_references,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecification,
    RequirementsSpecificationVersion,
    create_requirements_specification,
)
from orchestwin.twins.personas import PersonaProfileVersion
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinProfileVersion,
    VersionedArtifactReference,
    create_user_modeling_snapshot,
)
from src.test.python.knowledge.test_twin_import import (
    OWNER_ID,
    Member,
    modeling,
    persona_of,
    twin_of,
)
from src.test.python.twins.test_user_modeling_gate import CATALOG_HASH

PROJECT_ID = UUID("00000000-0000-4000-8000-00000000d000")
OTHER_PROJECT_ID = UUID("00000000-0000-4000-8000-00000000d001")
FIRST_SNAPSHOT_ID = UUID("00000000-0000-4000-8000-00000000d031")
SECOND_SNAPSHOT_ID = UUID("00000000-0000-4000-8000-00000000d032")
THIRD_SNAPSHOT_ID = UUID("00000000-0000-4000-8000-00000000d033")
REQUIREMENTS_VERSION_ID = UUID("00000000-0000-4000-8000-00000000d041")
REALIGNED_VERSION_ID = UUID("00000000-0000-4000-8000-00000000d042")
CHECK_IN = UUID("00000000-0000-4000-8000-00000000d501")
NIGHT_REPORT = UUID("00000000-0000-4000-8000-00000000d502")
AUDIT_LOG = UUID("00000000-0000-4000-8000-00000000d503")
STORY_IDS = (
    UUID("00000000-0000-4000-8000-00000000d511"),
    UUID("00000000-0000-4000-8000-00000000d512"),
)
CRITERION_IDS = (
    UUID("00000000-0000-4000-8000-00000000d521"),
    UUID("00000000-0000-4000-8000-00000000d522"),
)
SCENARIO_IDS = (
    UUID("00000000-0000-4000-8000-00000000d531"),
    UUID("00000000-0000-4000-8000-00000000d532"),
)
RISK_ID = UUID("00000000-0000-4000-8000-00000000d541")
DONE_ID = UUID("00000000-0000-4000-8000-00000000d551")
WRITTEN_AT = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)
REVISED_AT = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)
REALIGNED_AT = datetime(2026, 9, 27, 22, 0, tzinfo=UTC)
BRIEF = VersionedArtifactReference(
    artifact_id=UUID("00000000-0000-4000-8000-00000000d010"),
    version_number=2,
    content_hash="3" * 64,
)
OTHER_BRIEF = VersionedArtifactReference(
    artifact_id=UUID("00000000-0000-4000-8000-00000000d011"),
    version_number=3,
    content_hash="5" * 64,
)
TEAM = VersionedArtifactReference(
    artifact_id=UUID("00000000-0000-4000-8000-00000000d020"),
    version_number=1,
    content_hash="4" * 64,
)
OTHER_TEAM = VersionedArtifactReference(
    artifact_id=UUID("00000000-0000-4000-8000-00000000d021"),
    version_number=2,
    content_hash="6" * 64,
)
RECEPTIONIST = Member(
    persona_id=UUID("00000000-0000-4000-8000-00000000d110"),
    twin_id=UUID("00000000-0000-4000-8000-00000000d100"),
    name="Receptionist Twin",
    role="Receptionist",
)
AUDITOR = Member(
    persona_id=UUID("00000000-0000-4000-8000-00000000d210"),
    twin_id=UUID("00000000-0000-4000-8000-00000000d200"),
    name="Night Auditor Twin",
    role="Night auditor",
)
CONCIERGE = Member(
    persona_id=UUID("00000000-0000-4000-8000-00000000d310"),
    twin_id=UUID("00000000-0000-4000-8000-00000000d300"),
    name="Concierge Twin",
    role="Concierge",
)


def context(
    kind: RequirementsContextKind, reference: VersionedArtifactReference
) -> RequirementsContextReference:
    return RequirementsContextReference(
        kind=kind,
        artifact_id=reference.artifact_id,
        version_number=reference.version_number,
        content_hash=reference.content_hash,
    )


def specification(snapshot: UserModelingSnapshotVersion) -> RequirementsSpecification:
    modeling_snapshot = snapshot.snapshot
    references = snapshot_twin_references(snapshot)
    first, last = references[0], references[-1]
    brief = modeling_snapshot.project_brief_reference
    brief_source = RequirementSourceReference(
        kind=RequirementSourceKind.PROJECT_BRIEF,
        source_id=str(brief.artifact_id),
        source_version=brief.version_number,
        content_hash=brief.content_hash,
        locator="functional_requirements[0]",
    )
    twin_source = RequirementSourceReference(
        kind=RequirementSourceKind.USER_TWIN,
        source_id=str(first.twin_id),
        source_version=first.version_number,
        content_hash=first.content_hash,
        locator="user_twin.goals",
    )
    requirements = (
        create_requirement(
            requirement_id=CHECK_IN,
            code="REQ-001",
            title="Check guests in",
            statement="The system must check guests in at the front desk.",
            kind=RequirementKind.FUNCTIONAL,
            priority=RequirementPriority.MUST,
            sources=(brief_source, twin_source),
            user_twin_references=references,
        ),
        create_requirement(
            requirement_id=NIGHT_REPORT,
            code="REQ-002",
            title="Print the night report",
            statement="The system must print the night audit report.",
            kind=RequirementKind.FUNCTIONAL,
            priority=RequirementPriority.SHOULD,
            sources=(brief_source,),
            user_twin_references=(last,),
        ),
        create_requirement(
            requirement_id=AUDIT_LOG,
            code="REQ-003",
            title="Keep an audit log",
            statement="The system must keep an audit log of every change.",
            kind=RequirementKind.NON_FUNCTIONAL,
            priority=RequirementPriority.COULD,
            sources=(brief_source,),
        ),
    )
    stories = (
        create_user_story(
            story_id=STORY_IDS[0],
            code="USR-001",
            user_twin_reference=first,
            goal="check a guest in",
            benefit="the room is ready on arrival",
            requirement_ids=(CHECK_IN,),
        ),
        create_user_story(
            story_id=STORY_IDS[1],
            code="USR-002",
            user_twin_reference=last,
            goal="print the night report",
            benefit="the day closes with correct totals",
            requirement_ids=(NIGHT_REPORT,),
        ),
    )
    criteria = (
        create_acceptance_criterion(
            criterion_id=CRITERION_IDS[0],
            code="AC-001",
            statement="A checked-in guest has a room.",
            verification_method=VerificationMethod.AUTOMATED_TEST,
            requirement_ids=(CHECK_IN,),
            user_story_ids=(STORY_IDS[0],),
        ),
        create_acceptance_criterion(
            criterion_id=CRITERION_IDS[1],
            code="AC-002",
            statement="The night report lists every payment.",
            verification_method=VerificationMethod.MANUAL_REVIEW,
            requirement_ids=(NIGHT_REPORT,),
            user_story_ids=(STORY_IDS[1],),
        ),
    )
    scenarios = (
        create_usage_scenario(
            scenario_id=SCENARIO_IDS[0],
            code="SCN-001",
            title="Check in a guest",
            actor=first,
            preconditions=("The room is clean.",),
            trigger="A guest arrives.",
            steps=("Find the booking.", "Assign the room."),
            expected_outcome="The guest receives the key.",
            requirement_ids=(CHECK_IN,),
            acceptance_criterion_ids=(CRITERION_IDS[0],),
        ),
        create_usage_scenario(
            scenario_id=SCENARIO_IDS[1],
            code="SCN-002",
            title="Close the day",
            actor=last,
            preconditions=(),
            trigger="Midnight passes.",
            steps=("Print the report.",),
            expected_outcome="The report is filed.",
            requirement_ids=(NIGHT_REPORT,),
            acceptance_criterion_ids=(CRITERION_IDS[1],),
        ),
    )
    risks = (
        create_project_risk(
            risk_id=RISK_ID,
            code="RSK-001",
            summary="Double bookings at peak times.",
            likelihood=RiskLikelihood.POSSIBLE,
            impact=RiskImpact.HIGH,
            mitigation="Lock the room while it is being assigned.",
            requirement_ids=(CHECK_IN,),
            sources=(brief_source,),
        ),
    )
    done = (
        create_definition_of_done_item(
            item_id=DONE_ID,
            code="DOD-001",
            statement="Every acceptance test passes.",
            verification_method=VerificationMethod.AUTOMATED_TEST,
            applicability=DefinitionOfDoneApplicability.REQUIRED,
            requirement_ids=(CHECK_IN, NIGHT_REPORT, AUDIT_LOG),
        ),
    )
    return create_requirements_specification(
        project_id=snapshot.project_id,
        project_brief_reference=context(RequirementsContextKind.PROJECT_BRIEF, brief),
        agent_team_reference=context(
            RequirementsContextKind.AGENT_TEAM, modeling_snapshot.agent_team_reference
        ),
        user_modeling_reference=snapshot_reference(snapshot),
        catalog_version=modeling_snapshot.catalog_version,
        catalog_content_hash=modeling_snapshot.catalog_content_hash,
        user_twin_references=references,
        requirements=requirements,
        user_stories=stories,
        acceptance_criteria=criteria,
        scenarios=scenarios,
        risks=risks,
        definition_of_done=done,
    )


def requirements_version(
    snapshot: UserModelingSnapshotVersion,
    *,
    version_id: UUID = REQUIREMENTS_VERSION_ID,
    version_number: int = 3,
    owner_id: UUID = OWNER_ID,
    created_at: datetime = WRITTEN_AT,
) -> RequirementsSpecificationVersion:
    value = specification(snapshot)
    return RequirementsSpecificationVersion(
        id=version_id,
        project_id=snapshot.project_id,
        version_number=version_number,
        based_on_version_number=None if version_number == 1 else version_number - 1,
        specification=value,
        content_hash=value.content_hash,
        created_by_user_id=owner_id,
        created_at=created_at,
    )


def first_snapshot() -> UserModelingSnapshotVersion:
    return modeling(
        PROJECT_ID, (RECEPTIONIST, AUDITOR), snapshot_id=FIRST_SNAPSHOT_ID, brief=BRIEF, team=TEAM
    )


def next_snapshot(
    previous: UserModelingSnapshotVersion,
    *,
    personas: Sequence[PersonaProfileVersion],
    twins: Sequence[UserTwinProfileVersion],
    snapshot_id: UUID,
) -> UserModelingSnapshotVersion:
    snapshot = create_user_modeling_snapshot(
        project_id=previous.project_id,
        project_brief_reference=previous.snapshot.project_brief_reference,
        agent_team_reference=previous.snapshot.agent_team_reference,
        catalog_version=previous.snapshot.catalog_version,
        catalog_content_hash=previous.snapshot.catalog_content_hash,
        persona_versions=personas,
        twin_versions=twins,
    )
    return UserModelingSnapshotVersion(
        id=snapshot_id,
        project_id=previous.project_id,
        version_number=previous.version_number + 1,
        based_on_version_number=previous.version_number,
        snapshot=snapshot,
        content_hash=snapshot.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=REVISED_AT,
    )


def revised(version: UserTwinProfileVersion, *, name: str) -> UserTwinProfileVersion:
    profile = replace(version.profile, name=name)
    return UserTwinProfileVersion(
        id=UUID(int=version.id.int + 1),
        project_id=version.project_id,
        twin_id=version.twin_id,
        version_number=version.version_number + 1,
        based_on_version_number=version.version_number,
        profile=profile,
        content_hash=profile.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=REVISED_AT,
    )


def concierge() -> tuple[PersonaProfileVersion, UserTwinProfileVersion]:
    persona = persona_of(PROJECT_ID, CONCIERGE)
    return persona, twin_of(
        PROJECT_ID,
        CONCIERGE,
        persona,
        brief=BRIEF,
        team=TEAM,
        catalog_version=1,
        catalog_hash=CATALOG_HASH,
    )


def second_snapshot() -> UserModelingSnapshotVersion:
    first = first_snapshot()
    receptionist, auditor = first.snapshot.twin_versions
    persona, twin = concierge()
    return next_snapshot(
        first,
        personas=(*first.snapshot.persona_versions, persona),
        twins=(revised(receptionist, name="Front Desk Twin"), auditor, twin),
        snapshot_id=SECOND_SNAPSHOT_ID,
    )


def snapshot_without_the_auditor() -> UserModelingSnapshotVersion:
    first = first_snapshot()
    receptionist_persona = first.snapshot.persona_versions[0]
    receptionist = first.snapshot.twin_versions[0]
    persona, twin = concierge()
    return next_snapshot(
        first,
        personas=(receptionist_persona, persona),
        twins=(receptionist, twin),
        snapshot_id=THIRD_SNAPSHOT_ID,
    )


def regenerated_snapshot(
    *,
    brief: VersionedArtifactReference = BRIEF,
    team: VersionedArtifactReference = TEAM,
) -> UserModelingSnapshotVersion:
    return modeling(
        PROJECT_ID, (RECEPTIONIST, AUDITOR), snapshot_id=THIRD_SNAPSHOT_ID, brief=brief, team=team
    )


def test_requirements_written_for_the_current_twins_are_aligned():
    first = first_snapshot()
    written = specification(first)

    assert requirements_are_aligned(written, first)
    assert realignment_issue(written, first) is RequirementsRealignmentIssue.ALREADY_ALIGNED
    assert not requirements_are_aligned(written, second_snapshot())


def test_the_snapshot_references_describe_every_current_twin_in_canonical_order():
    second = second_snapshot()
    front_desk = second.snapshot.twin_versions[0]

    references = snapshot_twin_references(second)

    assert [reference.twin_id for reference in references] == [
        RECEPTIONIST.twin_id,
        AUDITOR.twin_id,
        CONCIERGE.twin_id,
    ]
    assert references[0] == UserTwinVersionReference(
        twin_id=RECEPTIONIST.twin_id,
        version_number=2,
        content_hash=front_desk.content_hash,
        name="Front Desk Twin",
    )
    assert snapshot_reference(second) == RequirementsContextReference(
        kind=RequirementsContextKind.USER_MODELING,
        artifact_id=SECOND_SNAPSHOT_ID,
        version_number=2,
        content_hash=second.content_hash,
    )
    assert referenced_twin_ids(specification(first_snapshot())) == frozenset(
        {RECEPTIONIST.twin_id, AUDITOR.twin_id}
    )


def test_requirements_of_another_brief_team_catalog_or_project_cannot_be_realigned():
    written = specification(first_snapshot())
    second = second_snapshot()

    for requirements, snapshot in (
        (written, regenerated_snapshot(brief=OTHER_BRIEF)),
        (written, regenerated_snapshot(team=OTHER_TEAM)),
        (replace(written, catalog_version=2), second),
        (replace(written, catalog_content_hash="e" * 64), second),
        (replace(written, project_id=OTHER_PROJECT_ID), second),
    ):
        assert (
            realignment_issue(requirements, snapshot)
            is RequirementsRealignmentIssue.CONTEXT_CHANGED
        )


def test_requirements_that_mention_a_twin_removed_from_the_snapshot_cannot_be_realigned():
    written = specification(first_snapshot())

    issue = realignment_issue(written, snapshot_without_the_auditor())

    assert issue is RequirementsRealignmentIssue.TWIN_NO_LONGER_AVAILABLE


def test_requirements_can_be_realigned_after_a_twin_revision_and_a_new_twin():
    assert realignment_issue(specification(first_snapshot()), second_snapshot()) is None


def test_realignment_points_every_twin_reference_to_the_current_version_of_the_same_twin():
    second = second_snapshot()
    current = {reference.twin_id: reference for reference in snapshot_twin_references(second)}

    realigned = realign_requirements(specification(first_snapshot()), second)

    assert realigned.user_modeling_reference == snapshot_reference(second)
    assert realigned.user_twin_references == snapshot_twin_references(second)
    assert [requirement.user_twin_references for requirement in realigned.requirements] == [
        (current[RECEPTIONIST.twin_id], current[AUDITOR.twin_id]),
        (current[AUDITOR.twin_id],),
        (),
    ]
    assert [story.user_twin_reference for story in realigned.user_stories] == [
        current[RECEPTIONIST.twin_id],
        current[AUDITOR.twin_id],
    ]
    assert [scenario.actor for scenario in realigned.scenarios] == [
        current[RECEPTIONIST.twin_id],
        current[AUDITOR.twin_id],
    ]
    assert current[RECEPTIONIST.twin_id].name == "Front Desk Twin"
    assert current[CONCIERGE.twin_id] in realigned.user_twin_references
    assert CONCIERGE.twin_id not in referenced_twin_ids(realigned)


def test_realignment_keeps_every_other_part_of_the_requirements_unchanged():
    written = specification(first_snapshot())

    realigned = realign_requirements(written, second_snapshot())

    assert [requirement.sources for requirement in realigned.requirements] == [
        requirement.sources for requirement in written.requirements
    ]
    assert realigned.requirements[0].sources[1].kind is RequirementSourceKind.USER_TWIN
    assert realigned.requirements[0].sources[1].source_version == 1
    for mine, theirs in zip(realigned.requirements, written.requirements, strict=True):
        assert replace(mine, user_twin_references=theirs.user_twin_references) == theirs
    for mine, theirs in zip(realigned.user_stories, written.user_stories, strict=True):
        assert replace(mine, user_twin_reference=theirs.user_twin_reference) == theirs
    for mine, theirs in zip(realigned.scenarios, written.scenarios, strict=True):
        assert replace(mine, actor=theirs.actor) == theirs
    assert (
        replace(
            realigned,
            user_modeling_reference=written.user_modeling_reference,
            user_twin_references=written.user_twin_references,
            requirements=written.requirements,
            user_stories=written.user_stories,
            scenarios=written.scenarios,
        )
        == written
    )


def test_the_realigned_version_continues_the_requirements_lineage_with_a_new_hash():
    written = requirements_version(first_snapshot())
    second = second_snapshot()

    version = realigned_requirements_version(
        written,
        second,
        version_id=REALIGNED_VERSION_ID,
        created_by_user_id=OWNER_ID,
        created_at=REALIGNED_AT,
    )

    assert version.id == REALIGNED_VERSION_ID
    assert version.project_id == written.project_id
    assert (version.version_number, version.based_on_version_number) == (4, 3)
    assert (version.created_by_user_id, version.created_at) == (OWNER_ID, REALIGNED_AT)
    assert version.specification == realign_requirements(written.specification, second)
    assert version.content_hash == version.specification.content_hash
    assert version.content_hash != written.content_hash
    assert requirements_are_aligned(version.specification, second)
    assert (
        realignment_issue(version.specification, second)
        is RequirementsRealignmentIssue.ALREADY_ALIGNED
    )


@pytest.mark.parametrize(
    ("snapshot_factory", "issue"),
    [
        (first_snapshot, RequirementsRealignmentIssue.ALREADY_ALIGNED),
        (
            lambda: regenerated_snapshot(brief=OTHER_BRIEF),
            RequirementsRealignmentIssue.CONTEXT_CHANGED,
        ),
        (snapshot_without_the_auditor, RequirementsRealignmentIssue.TWIN_NO_LONGER_AVAILABLE),
    ],
)
def test_realignment_is_refused_with_the_code_of_its_issue(snapshot_factory, issue):
    written = requirements_version(first_snapshot())

    with pytest.raises(RequirementsRealignmentError) as raised:
        realigned_requirements_version(
            written,
            snapshot_factory(),
            version_id=REALIGNED_VERSION_ID,
            created_by_user_id=OWNER_ID,
            created_at=REALIGNED_AT,
        )

    assert raised.value.issue is issue
    assert raised.value.code == issue.value
    assert str(raised.value) == issue.value
