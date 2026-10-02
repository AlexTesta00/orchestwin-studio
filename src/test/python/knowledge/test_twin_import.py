from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.knowledge.twin_import import (
    PERSONA_ORIGIN_PREFIX,
    PROJECT_LOCATOR_PREFIX,
    TWIN_ORIGIN_PREFIX,
    ImportedTwin,
    TwinImportError,
    TwinImportIdentities,
    TwinImportTarget,
    TwinOrigin,
    import_issue,
    import_twin,
    imported_twin_ids,
    parse_twin_document,
    persona_origin_reference,
    twin_origin_chain,
    twin_origin_of,
    twin_origin_reference,
)
from orchestwin.knowledge.twins import portable_twin_documents, portable_twins
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationValue,
    ProfileObservation,
)
from orchestwin.twins.personas import (
    PersonaConfirmationStatus,
    PersonaField,
    PersonaKind,
    PersonaProfileVersion,
    PersonaSource,
    confirm_proto_persona,
    create_owner_provided_persona,
    create_proto_persona,
)
from orchestwin.twins.user_modeling_gate import user_modeling_artifact_reference
from orchestwin.twins.user_twins import (
    ConfirmedPersonaReference,
    UserModelingSnapshotVersion,
    UserTwinField,
    UserTwinLifecycleStatus,
    UserTwinProfileVersion,
    VersionedArtifactReference,
    create_project_grounded_user_twin,
    create_user_modeling_snapshot,
)
from orchestwin.workflow.gates import HumanGateType
from src.test.python.knowledge.knowledge_fixtures import PROJECT_NAME, approved_gate, sources
from src.test.python.twins.test_user_modeling_gate import (
    BRIEF_REFERENCE,
    CATALOG_HASH,
    TEAM_REFERENCE,
    observation,
    twin_observations,
)
from src.test.python.twins.test_user_modeling_gate import PROJECT_ID as SOURCE_PROJECT_ID

OWNER_ID = UUID("00000000-0000-4000-8000-00000000b001")
TARGET_PROJECT_ID = UUID("00000000-0000-4000-8000-00000000b000")
TARGET_SNAPSHOT_ID = UUID("00000000-0000-4000-8000-00000000b031")
CREATED_AT = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
IMPORTED_AT = datetime(2026, 9, 27, 21, 30, tzinfo=UTC)
TARGET_BRIEF = VersionedArtifactReference(
    artifact_id=UUID("00000000-0000-4000-8000-00000000b010"),
    version_number=3,
    content_hash="1" * 64,
)
TARGET_TEAM = VersionedArtifactReference(
    artifact_id=UUID("00000000-0000-4000-8000-00000000b020"),
    version_number=2,
    content_hash="2" * 64,
)
IDENTITIES = TwinImportIdentities(
    persona_id=UUID("00000000-0000-4000-8000-00000000b140"),
    persona_version_id=UUID("00000000-0000-4000-8000-00000000b141"),
    twin_id=UUID("00000000-0000-4000-8000-00000000b150"),
    twin_version_id=UUID("00000000-0000-4000-8000-00000000b151"),
    snapshot_version_id=UUID("00000000-0000-4000-8000-00000000b032"),
)
SECOND_IDENTITIES = TwinImportIdentities(
    persona_id=UUID("00000000-0000-4000-8000-00000000b160"),
    persona_version_id=UUID("00000000-0000-4000-8000-00000000b161"),
    twin_id=UUID("00000000-0000-4000-8000-00000000b170"),
    twin_version_id=UUID("00000000-0000-4000-8000-00000000b171"),
    snapshot_version_id=UUID("00000000-0000-4000-8000-00000000b033"),
)
PROPOSED_PROJECT_NAME = "Hotel housekeeping"
_INFERRED_KEYS = frozenset(
    {
        UserTwinField.FRUSTRATIONS.observation_key,
        UserTwinField.TRUST_CONCERNS.observation_key,
        UserTwinField.ASSUMPTIONS.observation_key,
    }
)


@dataclass(frozen=True, slots=True)
class Member:
    persona_id: UUID
    twin_id: UUID
    name: str
    role: str


TARGET_MEMBERS = (
    Member(
        persona_id=UUID("00000000-0000-4000-8000-00000000b110"),
        twin_id=UUID("00000000-0000-4000-8000-00000000b100"),
        name="Night Auditor Twin",
        role="Night auditor",
    ),
    Member(
        persona_id=UUID("00000000-0000-4000-8000-00000000b210"),
        twin_id=UUID("00000000-0000-4000-8000-00000000b200"),
        name="Concierge Twin",
        role="Concierge",
    ),
)
PROPOSED_MEMBER = Member(
    persona_id=UUID("00000000-0000-4000-8000-00000000a110"),
    twin_id=UUID("00000000-0000-4000-8000-00000000a100"),
    name="Housekeeper Twin",
    role="Housekeeper",
)


def successor(value: UUID) -> UUID:
    return UUID(int=value.int + 1)


def crowded_members(count: int) -> tuple[Member, ...]:
    return tuple(
        Member(
            persona_id=UUID(f"00000000-0000-4000-8000-0000000c{index:02d}10"),
            twin_id=UUID(f"00000000-0000-4000-8000-0000000c{index:02d}00"),
            name=f"Guest Twin {index}",
            role=f"Guest {index}",
        )
        for index in range(count)
    )


def profile_observation(
    item: ProfileObservation, *, role: str, inferred: bool
) -> ProfileObservation:
    if item.observation_key == UserTwinField.ROLE.observation_key:
        return replace(item, value=ObservationValue.from_text(role))
    if inferred and item.observation_key in _INFERRED_KEYS:
        return replace(
            item,
            epistemic_status=EpistemicStatus.MODEL_INFERRED,
            confidence=ConfidenceScore(0.6),
            human_validation=HumanValidationRequirement.REQUIRED,
            rationale="Inferred from the project brief.",
        )
    return item


def persona_of(
    project_id: UUID, member: Member, *, proposed: bool = False, owner_id: UUID = OWNER_ID
) -> PersonaProfileVersion:
    observations = (
        observation(PersonaField.ROLE.observation_key, ObservationValue.from_text(member.role)),
        observation(
            PersonaField.SUMMARY.observation_key,
            ObservationValue.from_text(f"{member.role} of a small hotel."),
        ),
        observation(
            PersonaField.GOALS.observation_key,
            ObservationValue.from_items(("Keep guests informed",)),
        ),
        observation(
            PersonaField.CONTEXT_OF_USE.observation_key,
            ObservationValue.from_text("Hotel front desk"),
        ),
    )
    profile = (
        confirm_proto_persona(
            create_proto_persona(name=member.role, observations=observations)
        ).profile
        if proposed
        else create_owner_provided_persona(name=member.role, observations=observations)
    )
    return PersonaProfileVersion(
        id=successor(member.persona_id),
        project_id=project_id,
        persona_id=member.persona_id,
        version_number=1,
        profile=profile,
        content_hash=profile.content_hash,
        created_by_user_id=owner_id,
        created_at=CREATED_AT,
    )


def twin_of(
    project_id: UUID,
    member: Member,
    persona: PersonaProfileVersion,
    *,
    brief: VersionedArtifactReference,
    team: VersionedArtifactReference,
    catalog_version: int,
    catalog_hash: str,
    inferred: bool = False,
    status: UserTwinLifecycleStatus = UserTwinLifecycleStatus.PROJECT_GROUNDED_UT,
    owner_id: UUID = OWNER_ID,
) -> UserTwinProfileVersion:
    profile = replace(
        create_project_grounded_user_twin(
            name=member.name,
            persona_version=persona,
            project_brief_reference=brief,
            agent_team_reference=team,
            catalog_version=catalog_version,
            catalog_content_hash=catalog_hash,
            observations=tuple(
                profile_observation(item, role=member.role, inferred=inferred)
                for item in twin_observations()
            ),
        ),
        validation_status=status,
    )
    return UserTwinProfileVersion(
        id=successor(member.twin_id),
        project_id=project_id,
        twin_id=member.twin_id,
        version_number=1,
        profile=profile,
        content_hash=profile.content_hash,
        created_by_user_id=owner_id,
        created_at=CREATED_AT,
    )


def modeling(
    project_id: UUID,
    members: Sequence[Member],
    *,
    snapshot_id: UUID,
    brief: VersionedArtifactReference,
    team: VersionedArtifactReference,
    catalog_version: int = 1,
    catalog_hash: str = CATALOG_HASH,
    proposed: bool = False,
    inferred: bool = False,
    status: UserTwinLifecycleStatus = UserTwinLifecycleStatus.PROJECT_GROUNDED_UT,
    owner_id: UUID = OWNER_ID,
) -> UserModelingSnapshotVersion:
    personas = tuple(
        persona_of(project_id, member, proposed=proposed, owner_id=owner_id) for member in members
    )
    twins = tuple(
        twin_of(
            project_id,
            member,
            persona,
            brief=brief,
            team=team,
            catalog_version=catalog_version,
            catalog_hash=catalog_hash,
            inferred=inferred,
            status=status,
            owner_id=owner_id,
        )
        for member, persona in zip(members, personas, strict=True)
    )
    snapshot = create_user_modeling_snapshot(
        project_id=project_id,
        project_brief_reference=brief,
        agent_team_reference=team,
        catalog_version=catalog_version,
        catalog_content_hash=catalog_hash,
        persona_versions=personas,
        twin_versions=twins,
    )
    return UserModelingSnapshotVersion(
        id=snapshot_id,
        project_id=project_id,
        version_number=1,
        snapshot=snapshot,
        content_hash=snapshot.content_hash,
        created_by_user_id=owner_id,
        created_at=CREATED_AT,
    )


def target_snapshot(
    members: Sequence[Member] = TARGET_MEMBERS, **changes
) -> UserModelingSnapshotVersion:
    values = {"snapshot_id": TARGET_SNAPSHOT_ID, "brief": TARGET_BRIEF, "team": TARGET_TEAM}
    values.update(changes)
    return modeling(TARGET_PROJECT_ID, members, **values)


def target(**changes) -> TwinImportTarget:
    values = {
        "project_id": TARGET_PROJECT_ID,
        "project_brief_reference": TARGET_BRIEF,
        "agent_team_reference": TARGET_TEAM,
        "catalog_version": 1,
        "catalog_content_hash": CATALOG_HASH,
    }
    values.update(changes)
    return TwinImportTarget(**values)


def folder_document() -> dict[str, object]:
    return portable_twins(sources(with_feedback=False, project_id=SOURCE_PROJECT_ID))[0].document


def proposed_source() -> UserModelingSnapshotVersion:
    return modeling(
        SOURCE_PROJECT_ID,
        (PROPOSED_MEMBER,),
        snapshot_id=UUID("00000000-0000-4000-8000-00000000a030"),
        brief=BRIEF_REFERENCE,
        team=TEAM_REFERENCE,
        proposed=True,
        inferred=True,
        status=UserTwinLifecycleStatus.OWNER_APPROVED_UT,
    )


def proposed_document() -> dict[str, object]:
    source = proposed_source()
    return portable_twin_documents(
        project_id=SOURCE_PROJECT_ID,
        project_name=PROPOSED_PROJECT_NAME,
        modeling=source,
        modeling_gate=approved_gate(
            source,
            HumanGateType.USER_MODELING,
            user_modeling_artifact_reference(source),
            9000,
        ),
    )[0].document


def imported_twin(
    document: Mapping[str, object] | None = None,
    *,
    current: UserModelingSnapshotVersion | None = None,
    identities: TwinImportIdentities = IDENTITIES,
) -> ImportedTwin:
    return import_twin(
        parse_twin_document(folder_document() if document is None else document),
        target=target(),
        current=target_snapshot() if current is None else current,
        identities=identities,
        created_by_user_id=OWNER_ID,
        created_at=IMPORTED_AT,
    )


def rejection(document: object) -> TwinImportError:
    with pytest.raises(TwinImportError) as raised:
        parse_twin_document(document)
    return raised.value


def test_a_twin_document_of_the_knowledge_folder_parses_into_its_origin_persona_and_twin():
    package = sources(with_feedback=False, project_id=SOURCE_PROJECT_ID)
    persona = package.modeling.snapshot.persona_versions[0]
    twin = package.modeling.snapshot.twin_versions[0]

    parsed = parse_twin_document(portable_twins(package)[0].document)

    assert parsed.persona == persona
    assert parsed.twin == twin
    assert parsed.origin == TwinOrigin(
        project_id=SOURCE_PROJECT_ID,
        project_name=PROJECT_NAME,
        twin_id=twin.twin_id,
        twin_version_number=twin.version_number,
        twin_content_hash=twin.content_hash,
        persona_id=persona.persona_id,
        persona_version_number=persona.version_number,
        persona_content_hash=persona.content_hash,
    )
    assert parsed.origin.to_snapshot() == {
        "project_id": str(SOURCE_PROJECT_ID),
        "project_name": PROJECT_NAME,
        "twin_id": str(twin.twin_id),
        "twin_version_number": twin.version_number,
        "twin_content_hash": twin.content_hash,
        "persona_id": str(persona.persona_id),
        "persona_version_number": persona.version_number,
        "persona_content_hash": persona.content_hash,
    }


def test_the_origin_project_name_is_whitespace_normalized():
    document = folder_document()
    document["origin"]["project_name"] = "  Lista   ospiti\n workshop "

    assert parse_twin_document(document).origin.project_name == PROJECT_NAME


def test_documents_of_another_kind_or_folder_format_are_not_supported():
    for key, value in (
        ("kind", "orchestwin.user-persona"),
        ("schema_version", 1),
        ("schema_version", 4),
        ("schema_version", True),
    ):
        error = rejection({**folder_document(), key: value})

        assert (error.code, error.detail) == ("TWIN_DOCUMENT_UNSUPPORTED", key)


@pytest.mark.parametrize("version", [2, 3])
def test_documents_of_the_folder_formats_two_and_three_are_accepted(version: int):
    document = {**folder_document(), "schema_version": version}

    parsed = parse_twin_document(document)

    assert folder_document()["schema_version"] == 3
    assert parsed == parse_twin_document(folder_document())


def test_a_document_without_its_kind_or_project_name_is_invalid():
    without_kind = {key: value for key, value in folder_document().items() if key != "kind"}
    unnamed = folder_document()
    unnamed["origin"] = {**unnamed["origin"], "project_name": "   "}

    assert rejection(without_kind).code == "TWIN_DOCUMENT_INVALID"
    assert (rejection(unnamed).code, rejection(unnamed).detail) == (
        "TWIN_DOCUMENT_INVALID",
        "origin.project_name",
    )


@pytest.mark.parametrize("document", [[], "twin.json", None, 7])
def test_a_document_that_is_not_an_object_is_rejected(document):
    assert rejection(document).code == "TWIN_DOCUMENT_INVALID"


def test_a_document_without_its_twin_is_rejected_at_that_location():
    document = folder_document()
    del document["twin"]

    error = rejection(document)

    assert (error.code, error.detail) == ("TWIN_DOCUMENT_INVALID", "twin")


def test_a_tampered_twin_is_rejected_because_its_hash_no_longer_matches():
    tampered_hash = folder_document()
    tampered_hash["twin"]["content_hash"] = "0" * 64
    tampered_profile = folder_document()
    tampered_profile["twin"]["profile"]["name"] = "Receptionist Twin Copy"

    for document in (tampered_hash, tampered_profile):
        error = rejection(document)

        assert error.code == "TWIN_DOCUMENT_INVALID"
        assert "hash" in error.detail


def test_a_persona_that_does_not_ground_the_twin_is_rejected():
    document = folder_document()
    document["persona"] = proposed_document()["persona"]

    error = rejection(document)

    assert (error.code, error.detail) == ("TWIN_DOCUMENT_INVALID", "persona")


def test_a_twin_attributed_to_another_project_than_its_origin_is_rejected():
    document = portable_twins(sources(with_feedback=False))[0].document

    error = rejection(document)

    assert document["origin"]["project_id"] != document["twin"]["project_id"]
    assert (error.code, error.detail) == ("TWIN_DOCUMENT_INVALID", "project")


def test_import_requires_a_current_snapshot_of_the_target_project():
    document = parse_twin_document(folder_document())
    foreign = modeling(
        UUID("00000000-0000-4000-8000-00000000e000"),
        TARGET_MEMBERS,
        snapshot_id=TARGET_SNAPSHOT_ID,
        brief=TARGET_BRIEF,
        team=TARGET_TEAM,
    )

    assert import_issue(document, target=target(), current=None) == "USER_TWINS_REQUIRED"
    assert import_issue(document, target=target(), current=foreign) == "USER_TWINS_REQUIRED"


@pytest.mark.parametrize(
    "changes",
    [
        {"project_brief_reference": BRIEF_REFERENCE},
        {"agent_team_reference": TEAM_REFERENCE},
        {"catalog_version": 2},
        {"catalog_content_hash": "e" * 64},
    ],
)
def test_import_requires_the_target_snapshot_to_match_the_current_brief_team_and_catalog(changes):
    document = parse_twin_document(folder_document())

    issue = import_issue(document, target=target(**changes), current=target_snapshot())

    assert issue == "USER_TWINS_OUTDATED"


def test_a_twin_cannot_be_imported_into_the_project_it_comes_from():
    document = parse_twin_document(proposed_document())
    own = target(
        project_id=SOURCE_PROJECT_ID,
        project_brief_reference=BRIEF_REFERENCE,
        agent_team_reference=TEAM_REFERENCE,
    )

    assert import_issue(document, target=own, current=proposed_source()) == (
        "TWIN_BELONGS_TO_PROJECT"
    )


def test_a_twin_already_imported_into_the_target_cannot_be_imported_again():
    first = imported_twin()
    document = parse_twin_document(folder_document())

    assert (
        import_issue(document, target=target(), current=first.snapshot_version)
        == "TWIN_ALREADY_IMPORTED"
    )
    with pytest.raises(TwinImportError) as raised:
        imported_twin(current=first.snapshot_version, identities=SECOND_IDENTITIES)
    assert raised.value.code == "TWIN_ALREADY_IMPORTED"


def test_a_target_that_already_has_eight_twins_accepts_no_other_twin():
    document = parse_twin_document(folder_document())

    assert (
        import_issue(document, target=target(), current=target_snapshot(crowded_members(7))) is None
    )
    assert (
        import_issue(document, target=target(), current=target_snapshot(crowded_members(8)))
        == "TWIN_LIMIT_REACHED"
    )


def test_a_twin_name_already_used_in_the_target_is_refused_ignoring_case_and_spacing():
    document = parse_twin_document(folder_document())
    clash = replace(TARGET_MEMBERS[0], name="receptionist   TWIN")

    issue = import_issue(
        document, target=target(), current=target_snapshot((clash, TARGET_MEMBERS[1]))
    )

    assert issue == "TWIN_NAME_ALREADY_USED"


def test_a_twin_of_another_project_can_be_imported_into_a_ready_target():
    document = parse_twin_document(folder_document())

    assert import_issue(document, target=target(), current=target_snapshot()) is None


def test_import_twin_raises_the_import_issue_and_requires_an_aware_timestamp():
    document = parse_twin_document(folder_document())

    with pytest.raises(TwinImportError) as raised:
        import_twin(
            document,
            target=target(),
            current=None,
            identities=IDENTITIES,
            created_by_user_id=OWNER_ID,
            created_at=IMPORTED_AT,
        )
    assert raised.value.code == "USER_TWINS_REQUIRED"
    with pytest.raises(ValueError, match="timezone-aware"):
        import_twin(
            document,
            target=target(),
            current=target_snapshot(),
            identities=IDENTITIES,
            created_by_user_id=OWNER_ID,
            created_at=IMPORTED_AT.replace(tzinfo=None),
        )


@pytest.mark.parametrize("document_factory", [folder_document, proposed_document])
def test_the_imported_persona_keeps_its_standing_and_gets_a_new_identity_in_the_target(
    document_factory,
):
    parsed = parse_twin_document(document_factory())
    source = parsed.persona

    persona = imported_twin(document_factory()).persona_version

    assert persona.id == IDENTITIES.persona_version_id
    assert persona.persona_id == IDENTITIES.persona_id != source.persona_id
    assert persona.project_id == TARGET_PROJECT_ID
    assert (persona.version_number, persona.based_on_version_number) == (1, None)
    assert (persona.created_by_user_id, persona.created_at) == (OWNER_ID, IMPORTED_AT)
    assert persona.profile.name == source.profile.name
    assert persona.profile.source is source.profile.source
    assert persona.profile.kind is source.profile.kind
    assert persona.profile.confirmation_status is source.profile.confirmation_status
    assert persona.profile.rejection_reason is None
    assert persona.content_hash == persona.profile.content_hash
    reference = persona_origin_reference(parsed.origin)
    for mine, theirs in zip(persona.profile.observations, source.profile.observations, strict=True):
        assert mine.provenance.references == (*theirs.provenance.references, reference)
        assert replace(mine, provenance=theirs.provenance) == theirs


def test_a_confirmed_proto_persona_stays_a_proto_persona_after_the_import():
    persona = imported_twin(proposed_document()).persona_version

    assert persona.profile.source is PersonaSource.SYSTEM_PROPOSED
    assert persona.profile.kind is PersonaKind.PROTO_PERSONA
    assert persona.profile.confirmation_status is PersonaConfirmationStatus.CONFIRMED


def test_the_persona_origin_reference_points_to_the_source_persona_and_project():
    origin = parse_twin_document(folder_document()).origin

    reference = persona_origin_reference(origin)

    assert reference.source_kind is EvidenceSourceKind.SYSTEM_ARTIFACT
    assert reference.source_id == f"{PERSONA_ORIGIN_PREFIX}{origin.persona_id}"
    assert reference.source_version == origin.persona_version_number
    assert reference.content_hash == origin.persona_content_hash
    assert reference.locator == f"{PROJECT_LOCATOR_PREFIX}{SOURCE_PROJECT_ID}"
    assert reference.summary == f"Imported from the project {PROJECT_NAME}"


def test_an_origin_summary_of_a_long_project_name_is_shortened():
    origin = replace(parse_twin_document(folder_document()).origin, project_name="Workshop " * 40)

    summary = twin_origin_reference(origin).summary

    assert len(summary) == 160
    assert summary.startswith("Imported from the project Workshop Workshop")
    assert summary.endswith("…")


def test_the_imported_twin_keeps_its_observations_and_is_grounded_in_the_target():
    parsed = parse_twin_document(proposed_document())
    source = parsed.twin

    imported = imported_twin(proposed_document())
    twin = imported.twin_version
    profile = twin.profile

    assert twin.id == IDENTITIES.twin_version_id
    assert twin.twin_id == IDENTITIES.twin_id != source.twin_id
    assert twin.project_id == TARGET_PROJECT_ID
    assert (twin.version_number, twin.based_on_version_number) == (1, None)
    assert (twin.created_by_user_id, twin.created_at) == (OWNER_ID, IMPORTED_AT)
    assert profile.name == source.profile.name
    assert profile.persona_reference == ConfirmedPersonaReference.from_version(
        imported.persona_version
    )
    assert profile.project_brief_reference == TARGET_BRIEF
    assert profile.agent_team_reference == TARGET_TEAM
    assert (profile.catalog_version, profile.catalog_content_hash) == (1, CATALOG_HASH)
    assert source.profile.validation_status is UserTwinLifecycleStatus.OWNER_APPROVED_UT
    assert profile.validation_status is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT
    assert profile.requires_human_validation is source.profile.requires_human_validation is True
    assert twin.content_hash == profile.content_hash
    origin = twin_origin_reference(parsed.origin)
    for mine, theirs in zip(profile.observations, source.profile.observations, strict=True):
        assert mine.observation_key == theirs.observation_key
        assert mine.value == theirs.value
        assert mine.epistemic_status is theirs.epistemic_status
        assert mine.confidence == theirs.confidence
        assert mine.human_validation is theirs.human_validation
        assert mine.rationale == theirs.rationale
        assert mine.provenance.references == (*theirs.provenance.references, origin)
        assert [
            reference
            for reference in mine.provenance.references
            if reference.source_id.startswith(TWIN_ORIGIN_PREFIX)
        ] == [origin]


def test_the_import_appends_the_next_snapshot_with_the_old_twins_unchanged_in_canonical_order():
    current = target_snapshot()
    parsed = parse_twin_document(folder_document())

    imported = imported_twin(current=current)
    version = imported.snapshot_version
    snapshot = version.snapshot

    assert imported.origin == parsed.origin
    assert version.id == IDENTITIES.snapshot_version_id
    assert version.project_id == TARGET_PROJECT_ID
    assert (version.version_number, version.based_on_version_number) == (2, 1)
    assert (version.created_by_user_id, version.created_at) == (OWNER_ID, IMPORTED_AT)
    assert version.content_hash == snapshot.content_hash
    assert snapshot.project_brief_reference == TARGET_BRIEF
    assert snapshot.agent_team_reference == TARGET_TEAM
    assert (snapshot.catalog_version, snapshot.catalog_content_hash) == (1, CATALOG_HASH)
    assert snapshot.twin_versions == (
        current.snapshot.twin_versions[0],
        imported.twin_version,
        current.snapshot.twin_versions[1],
    )
    assert snapshot.persona_versions == (
        current.snapshot.persona_versions[0],
        imported.persona_version,
        current.snapshot.persona_versions[1],
    )
    assert [item.twin_id.hex for item in snapshot.twin_versions] == sorted(
        item.twin_id.hex for item in snapshot.twin_versions
    )


def test_the_origin_of_an_imported_twin_can_be_read_back():
    parsed = parse_twin_document(folder_document())

    imported = imported_twin()

    assert imported_twin_ids(imported.snapshot_version) == {
        parsed.origin.twin_id: IDENTITIES.twin_id
    }
    assert imported_twin_ids(target_snapshot()) == {}
    assert imported_twin_ids(None) == {}
    assert twin_origin_of(imported.twin_version) == {
        "twin_id": str(parsed.origin.twin_id),
        "twin_version_number": parsed.origin.twin_version_number,
        "twin_content_hash": parsed.origin.twin_content_hash,
        "project_id": str(SOURCE_PROJECT_ID),
        "summary": f"Imported from the project {PROJECT_NAME}",
    }
    assert twin_origin_of(target_snapshot().snapshot.twin_versions[0]) is None


def test_two_different_twins_of_the_same_source_can_both_be_imported():
    first = imported_twin()

    second = imported_twin(
        proposed_document(), current=first.snapshot_version, identities=SECOND_IDENTITIES
    )

    assert second.snapshot_version.version_number == 3
    assert imported_twin_ids(second.snapshot_version) == {
        parse_twin_document(folder_document()).origin.twin_id: IDENTITIES.twin_id,
        PROPOSED_MEMBER.twin_id: SECOND_IDENTITIES.twin_id,
    }


def test_a_twin_imported_twice_in_a_row_names_its_direct_source_and_keeps_the_chain():
    first = imported_twin()
    snapshot = first.snapshot_version
    document = next(
        item.document
        for item in portable_twin_documents(
            project_id=TARGET_PROJECT_ID,
            project_name="Secondo progetto",
            modeling=snapshot,
            modeling_gate=approved_gate(
                snapshot,
                HumanGateType.USER_MODELING,
                user_modeling_artifact_reference(snapshot),
                9500,
            ),
        )
        if item.document["twin"]["twin_id"] == str(first.twin_version.twin_id)
    )
    third_project = UUID("00000000-0000-4000-8000-00000000c000")
    current = modeling(
        third_project,
        TARGET_MEMBERS,
        snapshot_id=UUID("00000000-0000-4000-8000-00000000c031"),
        brief=TARGET_BRIEF,
        team=TARGET_TEAM,
    )

    second = import_twin(
        parse_twin_document(document),
        target=target(project_id=third_project),
        current=current,
        identities=SECOND_IDENTITIES,
        created_by_user_id=OWNER_ID,
        created_at=IMPORTED_AT,
    )

    chain = twin_origin_chain(second.twin_version)
    assert [item["project_id"] for item in chain] == [
        str(SOURCE_PROJECT_ID),
        str(TARGET_PROJECT_ID),
    ]
    assert twin_origin_of(second.twin_version) == chain[-1]
    assert chain[-1]["twin_id"] == str(first.twin_version.twin_id)
    assert chain[-1]["summary"] == "Imported from the project Secondo progetto"
    assert set(imported_twin_ids(second.snapshot_version)) == {
        first.origin.twin_id,
        first.twin_version.twin_id,
    }
