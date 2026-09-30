from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from orchestwin.knowledge.state import (
    LEARNING_SOURCES,
    MAX_LEARNED_OBSERVATIONS,
    MAX_UPDATE_OBSERVATIONS,
    UPDATE_DECISIONS,
    UPDATE_STATUSES,
)
from orchestwin.projects.twin_learning import (
    KeptObservation,
    LearnedObservation,
    LearningSource,
    ObservationDraft,
    ProposedObservation,
    RetiredObservation,
    TwinLearning,
    TwinUpdate,
    UpdateDecision,
    UpdateDecisionKind,
    UpdateStatus,
    build_twin_learning,
    development_version,
    learned_observations,
    learned_view,
    normalize_learning_reason,
    normalize_statement,
    observation_code,
    observation_number,
    requested_observation_number,
    statement_key,
    twin_learning_from_snapshot,
    twin_update_from_snapshot,
)

TWIN = UUID("00000000-0000-4000-8000-000000000030")
OTHER_TWIN = UUID("00000000-0000-4000-8000-000000000b02")
UPDATE = UUID("00000000-0000-4000-8000-000000000d01")
NOW = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
STATEMENT = "Chi lavora alla reception registra gli ospiti mentre parla al telefono."
BASIS = "Tre critiche sulla registrazione degli ospiti e un compito aperto dal proprietario."


def owner_observation(number=1, **values):
    arguments = {
        "twin_id": TWIN,
        "number": number,
        "statement": f"Osservazione del proprietario numero {number}.",
        "source": LearningSource.OWNER,
        "added_in_version": number,
        "approved_at": NOW + timedelta(minutes=number),
    }
    arguments.update(values)
    return LearnedObservation(**arguments)


def critique_observation(number=1, **values):
    arguments = {
        "twin_id": TWIN,
        "number": number,
        "statement": STATEMENT,
        "source": LearningSource.TWIN_CRITIQUE,
        "added_in_version": 1,
        "approved_at": NOW,
        "basis": BASIS,
        "requirement": "REQ-001",
        "screen": "SCR-001",
        "update_id": UPDATE,
    }
    arguments.update(values)
    return LearnedObservation(**arguments)


def proposal(index=0, **values):
    arguments = {
        "index": index,
        "statement": f"Il gruppo registra gli ospiti in piedi, caso numero {index}.",
        "basis": BASIS,
        "requirement": "REQ-001",
        "screen": None,
        "contradicts_profile": None,
    }
    arguments.update(values)
    return ProposedObservation(**arguments)


def twin_update(**values):
    arguments = {
        "id": UPDATE,
        "twin_id": TWIN,
        "twin_name": "Receptionist Twin",
        "created_at": NOW,
        "locale": "it-IT",
        "status": UpdateStatus.PROPOSED,
        "base_profile_version": 1,
        "base_development_version": 2,
        "comment": "Ho capito che il mio gruppo lavora sempre con il telefono in mano.",
        "observations": (proposal(0), proposal(1), proposal(2)),
        "material_changes": 3,
        "material_tests": 1,
        "generation_ids": (UUID(int=0xE301),),
        "cost_microusd": 152_000,
    }
    arguments.update(values)
    return TwinUpdate(**arguments)


def test_the_enumerations_match_the_shared_contract():
    assert tuple(item.value for item in LearningSource) == LEARNING_SOURCES
    assert tuple(item.value for item in UpdateStatus) == UPDATE_STATUSES
    assert tuple(item.value for item in UpdateDecisionKind) == UPDATE_DECISIONS


@pytest.mark.parametrize(
    ("number", "code"),
    [(1, "OBS-001"), (42, "OBS-042"), (1234, "OBS-1234"), (999_999, "OBS-999999")],
)
def test_observation_codes_continue_one_sequence_of_three_or_more_digits(number, code):
    assert observation_code(number) == code
    assert observation_number(code) == number


@pytest.mark.parametrize("number", [0, -1, 1_000_000, True, 1.0, "1"])
def test_an_observation_number_is_a_positive_integer_within_six_digits(number):
    with pytest.raises(ValueError):
        observation_code(number)


@pytest.mark.parametrize("code", ["OBS-1", "obs-001", "OBS-0001", "TSK-001", "OBS-0000001", 7])
def test_a_stored_observation_code_is_written_exactly(code):
    with pytest.raises(ValueError):
        observation_number(code)


@pytest.mark.parametrize(
    ("value", "number"),
    [
        ("OBS-007", 7),
        ("obs-007", 7),
        ("Obs-0012", 12),
        ("OBS-000", None),
        ("OBS-7", None),
        ("TSK-001", None),
        ("OBS-1234567", None),
        ("", None),
    ],
)
def test_a_requested_observation_code_is_read_without_case(value, number):
    assert requested_observation_number(value) == number


def test_statements_and_reasons_are_collapsed_and_bounded():
    assert normalize_statement("  Il  gruppo\n usa il telefono. ") == "Il gruppo usa il telefono."
    assert normalize_statement("x" * 400) == "x" * 400
    for value in ("   ", "x" * 401, None, 3, "a\x00b"):
        with pytest.raises(ValueError):
            normalize_statement(value)
    assert normalize_learning_reason(None) is None
    assert normalize_learning_reason("   ") is None
    assert normalize_learning_reason("  Non   serve più. ") == "Non serve più."
    assert normalize_learning_reason("x" * 300) == "x" * 300
    for value in ("x" * 301, 5):
        with pytest.raises(ValueError):
            normalize_learning_reason(value)
    assert statement_key("  Il  Gruppo\tUSA il telefono ") == "il gruppo usa il telefono"


def test_a_learned_observation_has_the_shape_of_the_contract():
    learned = critique_observation(contradicts_profile="Il profilo dice che lavora seduto.")
    assert learned.code == "OBS-001"
    assert learned.active
    assert learned.to_snapshot() == {
        "code": "OBS-001",
        "statement": STATEMENT,
        "basis": BASIS,
        "source": "TWIN_CRITIQUE",
        "about": {"requirement": "REQ-001", "screen": "SCR-001"},
        "contradicts_profile": "Il profilo dice che lavora seduto.",
        "added_in_version": 1,
        "approved_at": "2026-09-30T09:00:00+00:00",
        "update_id": str(UPDATE),
    }
    written = owner_observation(
        approved_at=datetime(2026, 9, 30, 11, 0, tzinfo=timezone(timedelta(hours=2)))
    )
    assert written.to_snapshot()["approved_at"] == "2026-09-30T09:00:00+00:00"
    assert written.to_snapshot()["basis"] is None
    assert written.to_snapshot()["update_id"] is None
    assert written.learned_view() == {
        "code": "OBS-001",
        "statement": "Osservazione del proprietario numero 1.",
        "source": "OWNER",
    }


@pytest.mark.parametrize(
    "values",
    [
        {"source": LearningSource.OWNER},
        {"update_id": None},
        {"basis": None},
        {"statement": "  Non   normalizzata."},
        {"statement": "x" * 401},
        {"basis": "x" * 301},
        {"contradicts_profile": ""},
        {"requirement": "REQ-1"},
        {"screen": "req-001"},
        {"number": 0},
        {"added_in_version": 0},
        {"approved_at": datetime(2026, 9, 30, 9, 0)},
        {"source": "OWNER"},
        {"twin_id": str(TWIN)},
        {"update_id": str(UPDATE)},
        {"retired_in_version": 2},
        {"retired_at": NOW},
        {"retired_in_version": 1, "retired_at": NOW},
        {"retire_reason": "Non serve."},
        {"retired_in_version": 2, "retired_at": NOW, "retire_reason": "  "},
    ],
)
def test_every_rule_of_a_learned_observation_is_validated(values):
    with pytest.raises(ValueError):
        critique_observation(**values)


def test_an_observation_written_by_the_owner_has_no_basis_and_no_update():
    with pytest.raises(ValueError):
        owner_observation(basis=BASIS)
    with pytest.raises(ValueError):
        owner_observation(update_id=UPDATE)


def test_a_retired_observation_keeps_its_version_its_time_and_its_reason():
    learned = critique_observation(added_in_version=2)
    retired = learned.retire(version=5, retired_at=NOW + timedelta(days=1), reason="Superata.")
    assert not retired.active
    assert (retired.retired_in_version, retired.retire_reason) == (5, "Superata.")
    assert retired.retirement() == RetiredObservation(
        number=1,
        statement=STATEMENT,
        retired_in_version=5,
        retired_at=NOW + timedelta(days=1),
        reason="Superata.",
    )
    assert retired.retirement().to_snapshot() == {
        "code": "OBS-001",
        "statement": STATEMENT,
        "retired_in_version": 5,
        "retired_at": "2026-10-01T09:00:00+00:00",
        "reason": "Superata.",
    }
    with pytest.raises(ValueError):
        retired.retire(version=6, retired_at=NOW)
    with pytest.raises(ValueError):
        learned.retirement()
    with pytest.raises(ValueError):
        learned.retire(version=2, retired_at=NOW)
    for values in (
        {"retired_in_version": 1},
        {"reason": "  "},
        {"retired_at": datetime(2026, 1, 1)},
    ):
        with pytest.raises(ValueError):
            replace(retired.retirement(), **values)


def test_the_development_version_counts_the_updates_the_observations_and_the_retirements():
    assert development_version(()) == 0
    first = owner_observation(1)
    second = critique_observation(2, added_in_version=2)
    retired = owner_observation(3, added_in_version=3).retire(version=4, retired_at=NOW)
    assert development_version((first, second)) == 2
    assert development_version((first, second, retired)) == 4


def test_learned_observations_are_numbered_from_the_first_free_number_in_one_version():
    drafts = (
        ObservationDraft(statement=STATEMENT, basis=BASIS, requirement="REQ-001"),
        ObservationDraft(statement="Il gruppo stampa la ricevuta per ogni ospite.", basis=BASIS),
    )
    added = learned_observations(
        drafts,
        twin_id=TWIN,
        first_number=7,
        version=3,
        approved_at=NOW,
        source=LearningSource.TWIN_CRITIQUE,
        update_id=UPDATE,
    )
    assert [item.code for item in added] == ["OBS-007", "OBS-008"]
    assert {item.added_in_version for item in added} == {3}
    assert added[0].requirement == "REQ-001"
    with pytest.raises(ValueError):
        ObservationDraft(statement="  Non normalizzata")
    with pytest.raises(ValueError):
        ObservationDraft(statement=STATEMENT, screen="SCR-1")


def test_the_entry_of_a_twin_lists_the_active_observations_oldest_first_and_the_retired_ones():
    records = (
        critique_observation(4, added_in_version=3, statement="Il gruppo usa il tablet."),
        owner_observation(1),
        owner_observation(2, added_in_version=2).retire(
            version=5, retired_at=NOW + timedelta(days=2), reason="Superata."
        ),
        critique_observation(3, added_in_version=3).retire(version=4, retired_at=NOW),
        replace(owner_observation(9), twin_id=OTHER_TWIN),
    )
    entry = build_twin_learning(
        twin_id=TWIN, twin_name="  Receptionist   Twin ", profile_version_number=2, records=records
    )
    assert entry.twin_name == "Receptionist Twin"
    assert entry.label == "2.5"
    assert [item.code for item in entry.observations] == ["OBS-001", "OBS-004"]
    assert [item.code for item in entry.retired] == ["OBS-003", "OBS-002"]
    assert entry.learned_view() == [
        {
            "code": "OBS-001",
            "statement": "Osservazione del proprietario numero 1.",
            "source": "OWNER",
        },
        {"code": "OBS-004", "statement": "Il gruppo usa il tablet.", "source": "TWIN_CRITIQUE"},
    ]
    assert learned_view(records[:4]) == entry.learned_view()
    snapshot = entry.to_snapshot()
    assert list(snapshot) == [
        "twin_id",
        "twin_name",
        "profile_version_number",
        "development_version_number",
        "label",
        "observations",
        "retired",
    ]
    assert snapshot["retired"][1] == {
        "code": "OBS-002",
        "statement": "Osservazione del proprietario numero 2.",
        "retired_in_version": 5,
        "retired_at": "2026-10-02T09:00:00+00:00",
        "reason": "Superata.",
    }
    assert twin_learning_from_snapshot(snapshot) == entry
    empty = build_twin_learning(
        twin_id=TWIN, twin_name="Receptionist Twin", profile_version_number=1
    )
    assert empty.to_snapshot() == {
        "twin_id": str(TWIN),
        "twin_name": "Receptionist Twin",
        "profile_version_number": 1,
        "development_version_number": 0,
        "label": "1.0",
        "observations": [],
        "retired": [],
    }


def learning(**values):
    arguments = {
        "twin_id": TWIN,
        "twin_name": "Receptionist Twin",
        "profile_version_number": 1,
        "development_version_number": 2,
        "observations": (owner_observation(1), owner_observation(2, added_in_version=2)),
    }
    arguments.update(values)
    return TwinLearning(**arguments)


@pytest.mark.parametrize(
    "values",
    [
        {"development_version_number": 3},
        {"development_version_number": 1},
        {"observations": (owner_observation(2, added_in_version=2), owner_observation(1))},
        {"observations": (owner_observation(1), owner_observation(1))},
        {"observations": (replace(owner_observation(1), twin_id=OTHER_TWIN),)},
        {
            "observations": (
                owner_observation(1),
                owner_observation(2, added_in_version=2).retire(version=3, retired_at=NOW),
            )
        },
        {
            "retired": (
                RetiredObservation(
                    number=1, statement="Uguale.", retired_in_version=2, retired_at=NOW
                ),
            )
        },
        {
            "retired": (
                RetiredObservation(
                    number=5, statement="Dopo.", retired_in_version=2, retired_at=NOW
                ),
                RetiredObservation(
                    number=4, statement="Prima.", retired_in_version=1 + 1, retired_at=NOW
                ),
            ),
            "development_version_number": 2,
        },
        {"profile_version_number": 0},
        {"twin_name": " Receptionist Twin"},
        {"observations": [owner_observation(1)]},
    ],
)
def test_every_rule_of_the_entry_of_a_twin_is_validated(values):
    with pytest.raises(ValueError):
        learning(**values)


def test_a_twin_holds_at_most_twenty_active_observations():
    observations = tuple(owner_observation(number, added_in_version=1) for number in range(1, 22))
    with pytest.raises(ValueError):
        learning(observations=observations, development_version_number=1)
    assert (
        len(
            learning(
                observations=observations[:MAX_LEARNED_OBSERVATIONS], development_version_number=1
            ).observations
        )
        == 20
    )


def test_the_parser_of_an_entry_refuses_a_wrong_label():
    snapshot = learning().to_snapshot()
    assert twin_learning_from_snapshot(snapshot) == learning()
    with pytest.raises(ValueError):
        twin_learning_from_snapshot({**snapshot, "label": "1.3"})


def test_an_update_has_the_exact_shape_of_the_contract():
    update = twin_update(
        observations=(
            proposal(0, contradicts_profile="Il profilo dice che lavora seduto.", screen="SCR-002"),
        )
    )
    assert update.pending
    assert update.to_snapshot() == {
        "id": str(UPDATE),
        "twin_id": str(TWIN),
        "twin_name": "Receptionist Twin",
        "created_at": "2026-09-30T09:00:00+00:00",
        "locale": "it-IT",
        "status": "PROPOSED",
        "base": {"profile_version_number": 1, "development_version_number": 2},
        "comment": "Ho capito che il mio gruppo lavora sempre con il telefono in mano.",
        "observations": [
            {
                "index": 0,
                "statement": "Il gruppo registra gli ospiti in piedi, caso numero 0.",
                "basis": BASIS,
                "about": {"requirement": "REQ-001", "screen": "SCR-002"},
                "contradicts_profile": "Il profilo dice che lavora seduto.",
            }
        ],
        "material": {"changes": 3, "tests": 1},
        "decision": None,
        "cost_microusd": 152_000,
    }
    assert twin_update_from_snapshot(update.to_snapshot()) == replace(update, generation_ids=())


def test_an_empty_update_proposes_nothing_and_needs_no_decision():
    empty = twin_update(status=UpdateStatus.EMPTY, observations=())
    assert not empty.pending
    assert empty.to_snapshot()["observations"] == []
    assert twin_update_from_snapshot(empty.to_snapshot()) == replace(empty, generation_ids=())
    with pytest.raises(ValueError):
        empty.decided(UpdateDecisionKind.REJECT, decided_at=NOW)


def decision(kept=(0, 2), reason=None):
    return UpdateDecision(decided_at=NOW + timedelta(hours=1), kept=kept, reason=reason)


@pytest.mark.parametrize(
    "values",
    [
        {"status": UpdateStatus.EMPTY},
        {"observations": ()},
        {"observations": (proposal(1),)},
        {"observations": (proposal(0), proposal(0))},
        {
            "observations": (
                proposal(0),
                proposal(1, statement=" ".join(proposal(0).statement.upper().split())),
            )
        },
        {"observations": [proposal(0)]},
        {"decision": decision()},
        {"status": UpdateStatus.APPROVED},
        {"status": UpdateStatus.APPROVED, "decision": decision(kept=())},
        {"status": UpdateStatus.REJECTED, "decision": decision()},
        {"status": UpdateStatus.APPROVED, "decision": decision(kept=(3,))},
        {"material_changes": 0, "material_tests": 0},
        {"material_changes": 9},
        {"material_tests": 5},
        {"comment": ""},
        {"comment": "x" * 601},
        {"locale": "italiano"},
        {"base_profile_version": 0},
        {"base_development_version": -1},
        {"created_at": datetime(2026, 9, 30, 9, 0)},
        {"generation_ids": (UUID(int=1), UUID(int=1))},
        {"cost_microusd": -1},
        {"twin_name": "x" * 201},
        {"status": "PROPOSED"},
    ],
)
def test_every_rule_of_an_update_is_validated(values):
    with pytest.raises(ValueError):
        twin_update(**values)


def test_an_update_proposes_at_most_six_observations():
    most = tuple(proposal(index) for index in range(MAX_UPDATE_OBSERVATIONS))
    assert len(twin_update(observations=most).observations) == MAX_UPDATE_OBSERVATIONS
    with pytest.raises(ValueError):
        proposal(MAX_UPDATE_OBSERVATIONS)


@pytest.mark.parametrize("index", [-1, MAX_UPDATE_OBSERVATIONS, True])
def test_a_proposed_observation_has_an_index_of_the_proposal(index):
    with pytest.raises(ValueError):
        proposal(index)


def test_a_decision_keeps_distinct_indexes_and_a_normalized_reason():
    for values in ({"kept": (1, 1)}, {"kept": (-1,)}, {"reason": " Nessuna. "}, {"kept": [0]}):
        with pytest.raises(ValueError):
            UpdateDecision(decided_at=NOW, **values)
    assert UpdateDecision(decided_at=NOW, kept=(0,), reason="Utile.").to_snapshot() == {
        "decided_at": "2026-09-30T09:00:00+00:00",
        "kept": [0],
        "reason": "Utile.",
    }


def test_an_update_is_approved_with_the_kept_indexes_or_rejected_once():
    update = twin_update()
    approved = update.decided(
        UpdateDecisionKind.APPROVE,
        kept=(2, 0),
        reason="Utili.",
        decided_at=NOW + timedelta(hours=1),
    )
    assert approved.status is UpdateStatus.APPROVED
    assert approved.to_snapshot()["decision"] == {
        "decided_at": "2026-09-30T10:00:00+00:00",
        "kept": [0, 2],
        "reason": "Utili.",
    }
    assert twin_update_from_snapshot(approved.to_snapshot()) == replace(approved, generation_ids=())
    rejected = update.decided(UpdateDecisionKind.REJECT, decided_at=NOW)
    assert (rejected.status, rejected.decision.kept, rejected.decision.reason) == (
        UpdateStatus.REJECTED,
        (),
        None,
    )
    for decided in (approved, rejected):
        assert not decided.pending
        with pytest.raises(ValueError):
            decided.decided(UpdateDecisionKind.REJECT, decided_at=NOW)
    with pytest.raises(ValueError):
        update.decided(UpdateDecisionKind.APPROVE, kept=(), decided_at=NOW)
    with pytest.raises(ValueError):
        update.decided(UpdateDecisionKind.REJECT, kept=(1,), decided_at=NOW)
    with pytest.raises(ValueError):
        update.decided(UpdateDecisionKind.APPROVE, kept=(7,), decided_at=NOW)
    with pytest.raises(ValueError):
        update.decided("APPROVE", kept=(0,), decided_at=NOW)


def test_the_kept_observations_take_the_edited_statement_in_the_order_of_the_proposal():
    update = twin_update(
        observations=(
            proposal(0),
            proposal(1, screen="SCR-002", contradicts_profile="Il profilo dice altro."),
            proposal(2),
        )
    )
    drafts = update.kept_drafts(
        (
            KeptObservation(index=1, statement="Il gruppo preferisce la tastiera."),
            KeptObservation(index=0),
        )
    )
    assert drafts == (
        ObservationDraft(
            statement=proposal(0).statement, basis=BASIS, requirement="REQ-001", screen=None
        ),
        ObservationDraft(
            statement="Il gruppo preferisce la tastiera.",
            basis=BASIS,
            requirement="REQ-001",
            screen="SCR-002",
            contradicts_profile="Il profilo dice altro.",
        ),
    )
    with pytest.raises(ValueError):
        update.kept_drafts((KeptObservation(index=3),))
    for values in ({"index": -1}, {"index": 0, "statement": " Non normalizzata"}):
        with pytest.raises(ValueError):
            KeptObservation(**values)
