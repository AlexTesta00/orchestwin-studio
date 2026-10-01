from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest

from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
    ObservationValue,
    ObservationValueKind,
    ProfileObservation,
)
from orchestwin.twins.lifecycle import (
    UserTwinLifecycleIssueCode,
    UserTwinOwnerApprovalStatus,
    effective_user_twin_lifecycle,
    promote_user_twin_lifecycle,
)
from orchestwin.twins.persistence.snapshots import (
    persona_profile_from_snapshot,
    persona_version_from_record,
    persona_version_to_record,
    user_modeling_snapshot_version_from_record,
    user_modeling_snapshot_version_to_record,
    user_twin_version_from_record,
    user_twin_version_to_record,
)
from orchestwin.twins.personas import (
    PersonaConfirmationStatus,
    PersonaField,
    create_proto_persona,
    reject_proto_persona,
)
from orchestwin.twins.representation import (
    ArchetypeInput,
    ReadableClaimStatus,
    TwinBasis,
    active_archetype,
    archetype_payload,
    archetype_profile,
    archive_archetype_profile,
    observation_display_status,
    snapshot_matches_archetypes,
    twin_view,
)
from orchestwin.twins.user_twins import (
    ConfirmedPersonaReference,
    UserTwinField,
    UserTwinLifecycleStatus,
)
from src.test.python.twins.test_user_modeling_persistence import (
    persona_version,
    snapshot_version,
    twin_version,
)

DECLARATION_FIELDS = (
    UserTwinField.DESCRIPTION,
    UserTwinField.REPRESENTS,
    UserTwinField.DOES_NOT_REPRESENT,
    UserTwinField.EVIDENCE_GAPS,
)


def claim(
    status=EpistemicStatus.MODEL_INFERRED,
    source=EvidenceSourceKind.MODEL_OUTPUT,
    value=None,
    field=UserTwinField.GOALS,
):
    return ProfileObservation(
        observation_key=field.observation_key,
        value=ObservationValue.from_items(("Read the amounts",)) if value is None else value,
        epistemic_status=status,
        confidence=ConfidenceScore(0.7),
        provenance=ObservationProvenance.from_references(
            (
                EvidenceReference(
                    source_kind=source,
                    source_id="research-session-12"
                    if source is EvidenceSourceKind.EMPIRICAL_RESEARCH
                    else "profile-input-12",
                    locator=field.observation_key,
                ),
            )
        ),
        human_validation=HumanValidationRequirement.REQUIRED,
        rationale="This statement needs review against the cited source.",
    )


def with_claims(*observations):
    base = twin_version()
    existing = {item.observation_key: item for item in base.profile.observations}
    existing.update({item.observation_key: item for item in observations})
    profile = replace(
        base.profile,
        observations=tuple(
            existing[field.observation_key]
            for field in UserTwinField
            if field.observation_key in existing
        ),
    )
    return replace(base, profile=profile, content_hash=profile.content_hash)


def with_profile(profile, *, version_number=1, version_id=None):
    base = persona_version()
    return replace(
        base,
        id=base.id if version_id is None else version_id,
        profile=profile,
        content_hash=profile.content_hash,
        version_number=version_number,
        based_on_version_number=None if version_number == 1 else version_number - 1,
    )


def test_historical_json_records_and_references_keep_their_exact_hashes():
    persona = persona_version()
    twin = twin_version()
    snapshot = snapshot_version()
    assert (
        persona.content_hash == "a4838831c7670edce0f58c719e6ecc122e07967ab5721f4d0369f363862153e8"
    )
    assert twin.content_hash == "567288ec28d01cbfca8713af176ab84e8fd13b7a6254ca30e84d6ea599be57f6"
    assert (
        snapshot.content_hash == "09b56b0974e27d11054f5d33583e7c151557ac6378f9bc64e0c4f5d4be1cfbd9"
    )
    assert "archived" not in persona.profile.to_snapshot()
    assert not any(twin.profile.observation_for(field) for field in DECLARATION_FIELDS)
    assert persona_version_from_record(persona_version_to_record(persona)) == persona
    assert user_twin_version_from_record(user_twin_version_to_record(twin)) == twin
    assert (
        user_modeling_snapshot_version_from_record(
            user_modeling_snapshot_version_to_record(snapshot)
        )
        == snapshot
    )
    assert ConfirmedPersonaReference.from_version(persona).to_snapshot() == {
        "persona_id": str(persona.persona_id),
        "version_number": 1,
        "content_hash": persona.content_hash,
        "source": "OWNER_PROVIDED",
        "kind": "PERSONA",
        "confirmation_status": "CONFIRMED",
    }


def test_archive_round_trips_without_mutating_the_previous_profile():
    original = persona_version()
    archived = archive_archetype_profile(original.profile)
    assert archived.archived
    assert archived.to_snapshot()["archived"] is True
    assert not archived.ready_for_twin_creation
    assert not original.profile.archived
    assert "archived" not in original.profile.to_snapshot()
    assert archive_archetype_profile(archived) == archived
    assert persona_profile_from_snapshot(archived.to_snapshot()) == archived
    version = with_profile(archived, version_number=2, version_id=UUID(int=312))
    assert persona_version_from_record(persona_version_to_record(version)) == version
    assert not active_archetype(version)
    with pytest.raises(ValueError, match="confirmed persona"):
        ConfirmedPersonaReference.from_version(version)


@pytest.mark.parametrize("flag", [None, 0, 1, "false", []])
def test_archive_flag_requires_a_boolean(flag):
    with pytest.raises(TypeError, match="boolean"):
        replace(persona_version().profile, archived=flag)


def test_canonical_default_archive_flag_is_omitted():
    historical = persona_version().profile.to_snapshot()
    assert not persona_profile_from_snapshot(historical).archived
    with pytest.raises(ValueError, match="canonical"):
        persona_profile_from_snapshot({**historical, "archived": False})


def test_archetype_input_normalizes_text_and_retains_owner_provenance():
    data = ArchetypeInput(
        "  Reception   staff ",
        " Staff\nhandling arrivals ",
        " Receptionist ",
        (" Read  amounts ", "Serve\nguests"),
        " Front  desk ",
    )
    assert data == ArchetypeInput(
        "Reception staff",
        "Staff handling arrivals",
        "Receptionist",
        ("Read amounts", "Serve guests"),
        "Front desk",
    )
    with pytest.raises(FrozenInstanceError):
        data.name = "Other"
    profile = archetype_profile(data, source_id=" owner-12 ")
    assert profile.ready_for_twin_creation
    for item in profile.observations:
        assert item.epistemic_status is EpistemicStatus.USER_PROVIDED
        assert observation_display_status(item) is ReadableClaimStatus.HYPOTHESIZED
        assert item.provenance.references == (
            EvidenceReference(
                source_kind=EvidenceSourceKind.OWNER_INPUT,
                source_id="owner-12",
                locator=item.observation_key,
            ),
        )


@pytest.mark.parametrize(
    ("field", "maximum"), [("name", 200), ("description", 4000), ("role", 4000), ("context", 4000)]
)
def test_archetype_text_limits_match_profile_values(field, maximum):
    fields = {"name": "Staff", "description": "Reception staff", "role": "Receptionist"}
    fields[field] = "a" * maximum
    archetype_profile(ArchetypeInput(**fields), source_id="owner")
    fields[field] += "a"
    with pytest.raises(ValueError, match="maximum length"):
        ArchetypeInput(**fields)
    fields[field] = " \n "
    with pytest.raises(ValueError, match="empty"):
        ArchetypeInput(**fields)


@pytest.mark.parametrize("goals", [(" ",), ("a" * 2001,), ("Read amounts", "Read  amounts")])
def test_archetype_goals_reject_empty_oversized_and_normalized_duplicates(goals):
    with pytest.raises(ValueError):
        ArchetypeInput("Staff", "Reception staff", "Receptionist", goals)


def test_empty_goals_and_missing_context_remain_unknown_in_profile_and_form():
    data = ArchetypeInput("Staff", "Reception staff", "Receptionist")
    profile = archetype_profile(data, source_id="owner")
    for field in (PersonaField.GOALS, PersonaField.CONTEXT_OF_USE):
        item = profile.observation_for(field)
        assert item.value.kind is ObservationValueKind.UNKNOWN
        assert observation_display_status(item) is ReadableClaimStatus.UNKNOWN
        assert item.confidence.value == 0
    payload = archetype_payload(with_profile(profile))
    assert payload == {
        "persona_id": str(persona_version().persona_id),
        "version_id": str(persona_version().id),
        "version_number": 1,
        "name": "Staff",
        "description": "Reception staff",
        "role": "Receptionist",
        "goals": [],
        "context": None,
        "source": "OWNER_PROVIDED",
        "confirmation_status": "CONFIRMED",
        "archived": False,
    }
    assert profile.observation_for(PersonaField.GOALS).value.kind is ObservationValueKind.UNKNOWN


@pytest.mark.parametrize("source", list(EvidenceSourceKind))
@pytest.mark.parametrize("status", list(EpistemicStatus))
def test_readable_status_uses_real_source_kind_and_never_owner_approval(status, source):
    item = claim(status, source)
    expected = ReadableClaimStatus.HYPOTHESIZED
    if status is EpistemicStatus.MODEL_INFERRED:
        expected = ReadableClaimStatus.INFERRED
    elif status is EpistemicStatus.CONTESTED:
        expected = ReadableClaimStatus.CONTESTED
    elif status in {EpistemicStatus.EMPIRICALLY_SUPPORTED, EpistemicStatus.HUMAN_VALIDATED} and (
        source is EvidenceSourceKind.EMPIRICAL_RESEARCH
    ):
        expected = ReadableClaimStatus.EVIDENCED
    assert observation_display_status(item) is expected


@pytest.mark.parametrize("status", [EpistemicStatus.USER_PROVIDED, EpistemicStatus.MODEL_INFERRED])
@pytest.mark.parametrize(
    "value", [ObservationValue.unknown(), ObservationValue.abstained("No study")]
)
def test_unknown_and_abstention_take_precedence_over_claim_status(status, value):
    assert observation_display_status(claim(status, value=value)) is ReadableClaimStatus.UNKNOWN


@pytest.mark.parametrize(
    "value", [ObservationValue.unknown(), ObservationValue.abstained("No study")]
)
def test_contested_claim_requires_a_substantive_value(value):
    with pytest.raises(ValueError, match="substantive value"):
        claim(EpistemicStatus.CONTESTED, value=value)


def test_contested_claim_requires_rationale_and_human_validation():
    contested = claim(EpistemicStatus.CONTESTED)
    with pytest.raises(ValueError, match="rationale"):
        replace(contested, rationale=None)
    with pytest.raises(ValueError, match="human validation"):
        replace(contested, human_validation=HumanValidationRequirement.NOT_REQUIRED)


def test_owner_gate_and_human_review_do_not_create_an_empirical_basis():
    base = twin_version()
    before = base.profile.canonical_json()
    assert (
        effective_user_twin_lifecycle(
            base.profile, owner_approval=UserTwinOwnerApprovalStatus.APPROVED
        )
        is UserTwinLifecycleStatus.OWNER_APPROVED_UT
    )
    assert twin_view(base)["basis"] == TwinBasis.PROVISIONAL.value
    reviewed = with_claims(claim(EpistemicStatus.HUMAN_VALIDATED, EvidenceSourceKind.HUMAN_REVIEW))
    assert twin_view(reviewed)["basis"] == TwinBasis.PROVISIONAL.value
    assert reviewed.profile.validation_status is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT
    assert base.profile.canonical_json() == before


def test_empirical_basis_keeps_unsupported_gaps_visible_and_mismatch_provisional():
    supported = claim(EpistemicStatus.EMPIRICALLY_SUPPORTED, EvidenceSourceKind.EMPIRICAL_RESEARCH)
    view = twin_view(with_claims(supported))
    assert view["basis"] == TwinBasis.EVIDENCE_BASED.value
    assert view["empirically_supported_fields"] == ["goals"]
    assert "goals" not in view["unsupported_fields"]
    assert "does_not_represent" in view["unsupported_fields"]
    mismatch = claim(
        EpistemicStatus.EMPIRICALLY_SUPPORTED,
        EvidenceSourceKind.PROJECT_BRIEF,
        field=UserTwinField.INFORMATION_NEEDS,
    )
    assert twin_view(with_claims(supported, mismatch))["basis"] == TwinBasis.PROVISIONAL.value


def test_human_validated_empirical_claim_has_readable_support_without_lifecycle_promotion():
    item = claim(EpistemicStatus.HUMAN_VALIDATED, EvidenceSourceKind.EMPIRICAL_RESEARCH)
    twin = with_claims(item)
    view = twin_view(twin)
    assert view["persona"]["goals"]["display_status"] == "EVIDENCED"
    assert "goals" not in view["unsupported_fields"]
    assert view["empirically_supported_fields"] == []
    assert view["basis"] == "PROVISIONAL"
    assert twin.profile.validation_status is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT


def test_contested_claim_remains_non_empirical_even_with_a_research_reference():
    supported = claim(EpistemicStatus.EMPIRICALLY_SUPPORTED, EvidenceSourceKind.EMPIRICAL_RESEARCH)
    contested = claim(
        EpistemicStatus.CONTESTED,
        EvidenceSourceKind.EMPIRICAL_RESEARCH,
        field=UserTwinField.INFORMATION_NEEDS,
    )
    twin = with_claims(supported, contested)
    grounded = promote_user_twin_lifecycle(
        twin.profile,
        target_status=UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT,
        owner_approval=UserTwinOwnerApprovalStatus.APPROVED,
    )
    result = promote_user_twin_lifecycle(
        grounded.profile,
        target_status=UserTwinLifecycleStatus.EMPIRICALLY_VALIDATED_UT,
        owner_approval=UserTwinOwnerApprovalStatus.APPROVED,
    )
    assert result.issue is UserTwinLifecycleIssueCode.EMPIRICAL_COVERAGE_INCOMPLETE
    assert twin_view(twin)["persona"]["needs"]["display_status"] == "CONTESTED"


def test_persona_view_and_why_preserve_exact_values_rationales_and_provenance():
    item = claim()
    twin = with_claims(item)
    before = twin.profile.canonical_json()
    view = twin_view(twin, persona_version())
    assert view["persona"]["goals"] == {
        "observation_key": item.observation_key,
        "value": item.value.to_snapshot(),
        "display_status": "INFERRED",
        "rationale": item.rationale,
        "provenance": item.provenance.to_snapshot(),
    }
    summary = persona_version().profile.observation_for(PersonaField.SUMMARY)
    assert view["persona"]["description"]["value"] == summary.value.to_snapshot()
    assert view["persona"]["description"]["provenance"] == summary.provenance.to_snapshot()
    assert list(view["persona"]) == [
        "description",
        "goals",
        "needs",
        "behaviours",
        "pain_points",
        "constraints",
        "contexts",
    ]
    assert twin.profile.canonical_json() == before


def test_absent_declarations_are_unknown_and_do_not_invent_exclusions():
    view = twin_view(twin_version())
    for key, field in (
        ("represents", UserTwinField.REPRESENTS),
        ("does_not_represent", UserTwinField.DOES_NOT_REPRESENT),
        ("evidence_gaps", UserTwinField.EVIDENCE_GAPS),
    ):
        assert view[key] == {
            "observation_key": field.observation_key,
            "value": ObservationValue.unknown().to_snapshot(),
            "display_status": "UNKNOWN",
            "rationale": None,
            "provenance": [],
        }
    assert view["persona"]["description"]["display_status"] == "UNKNOWN"


@pytest.mark.parametrize("change", ["project", "persona", "version", "hash", "archived"])
def test_historical_description_fallback_requires_the_exact_cited_persona(change):
    persona = persona_version()
    if change == "project":
        persona = replace(persona, project_id=UUID(int=913))
    elif change == "persona":
        persona = replace(persona, persona_id=UUID(int=913))
    elif change == "version":
        persona = replace(persona, version_number=2, based_on_version_number=1)
    else:
        profile = (
            archive_archetype_profile(persona.profile)
            if change == "archived"
            else replace(persona.profile, name="Another archetype")
        )
        persona = replace(persona, profile=profile, content_hash=profile.content_hash)
    view = twin_view(twin_version(), persona)
    assert view["persona"]["description"]["display_status"] == "UNKNOWN"
    assert view["persona"]["description"]["provenance"] == []


@pytest.mark.parametrize("field", DECLARATION_FIELDS)
@pytest.mark.parametrize("kind", ["value", "unknown", "abstained"])
def test_optional_declarations_accept_their_shapes_and_round_trip(field, kind):
    value = (
        ObservationValue.from_text("Reception staff")
        if field is UserTwinField.DESCRIPTION
        else ObservationValue.from_items(("Reception staff",))
    )
    if kind == "unknown":
        value = ObservationValue.unknown()
    elif kind == "abstained":
        value = ObservationValue.abstained("No supporting study")
    twin = with_claims(claim(value=value, field=field))
    assert user_twin_version_from_record(user_twin_version_to_record(twin)) == twin


@pytest.mark.parametrize("field", DECLARATION_FIELDS)
def test_optional_declarations_reject_the_wrong_value_shape(field):
    value = (
        ObservationValue.from_items(("Reception staff",))
        if field is UserTwinField.DESCRIPTION
        else ObservationValue.from_text("Reception staff")
    )
    with pytest.raises(ValueError, match="does not support"):
        with_claims(claim(value=value, field=field))


def test_snapshot_roster_requires_active_confirmed_exact_versions():
    snapshot = snapshot_version()
    current = persona_version()
    assert snapshot_matches_archetypes(snapshot, (current,))
    assert not snapshot_matches_archetypes(snapshot, ())
    assert not snapshot_matches_archetypes(snapshot, (current, current))
    assert not snapshot_matches_archetypes(
        snapshot, (replace(current, version_number=2, based_on_version_number=1),)
    )
    assert not snapshot_matches_archetypes(snapshot, (replace(current, id=UUID(int=913)),))
    archived = with_profile(archive_archetype_profile(current.profile))
    assert not snapshot_matches_archetypes(snapshot, (archived,))
    proposed = create_proto_persona(
        name="Second archetype", observations=current.profile.observations
    )
    pending = replace(with_profile(proposed), persona_id=UUID(int=913), id=UUID(int=914))
    assert active_archetype(pending)
    assert not snapshot_matches_archetypes(snapshot, (current, pending))
    rejected = reject_proto_persona(proposed, reason="Outside the project").profile
    rejected_version = replace(with_profile(rejected), persona_id=pending.persona_id, id=pending.id)
    assert not active_archetype(rejected_version)
    assert snapshot_matches_archetypes(snapshot, (current, rejected_version))
    assert snapshot_matches_archetypes(snapshot, (current, archived))
    assert current.profile.confirmation_status is PersonaConfirmationStatus.CONFIRMED
