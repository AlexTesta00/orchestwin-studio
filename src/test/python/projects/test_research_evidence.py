from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from orchestwin.api.research_evidence import EvidenceBody
from orchestwin.api.twin_learning import TwinUpdateRequest
from orchestwin.api.validation import request_validation_error
from orchestwin.projects import evidence_application
from orchestwin.projects.evidence_application import (
    apply_evidence_change,
    evidence_profile,
    withdrawn_observation,
)
from orchestwin.projects.persistence.research_evidence import (
    SqlAlchemyResearchEvidenceRepository,
    evidence_citation_from_row,
)
from orchestwin.projects.research_evidence import (
    EvidenceChange,
    EvidenceCitation,
    EvidenceEffect,
    EvidenceUpdateSource,
    EvidenceVersion,
    ResearchEvidenceError,
    evidence_content_hash,
    normalize_evidence_text,
)
from orchestwin.projects.sections import SectionReason, project_sections, requirements_actor_codes
from orchestwin.projects.twin_learning import (
    ProposedObservation,
    UpdateStatus,
    twin_update_from_snapshot,
)
from orchestwin.twins.epistemics import (
    EpistemicStatus,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationValue,
)
from orchestwin.twins.lifecycle import assess_empirical_grounding
from orchestwin.twins.persistence.repositories import VersionAppendStatus
from orchestwin.twins.user_modeling_gate import user_modeling_gate_is_currently_approved
from orchestwin.twins.user_twins import UserTwinField, UserTwinLifecycleStatus
from orchestwin.workflow.gates import HumanGateStatus
from src.test.python.projects.test_sections import TWIN_A, TWIN_B, aligned, twin, user_twins
from src.test.python.projects.test_twin_learning import twin_update
from src.test.python.twins.test_lifecycle import (
    human_validated_observation,
    twin_profile,
    user_observation,
)
from src.test.python.twins.test_user_modeling_gate import snapshot_version

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


def test_repeated_evidence_updates_reuse_gate_history_and_renew_the_approved_revision_budget(
    monkeypatch,
):
    class Versions:
        async def append(self, version):
            return VersionAppendStatus.APPENDED

    class Gates:
        def __init__(self):
            self.latest = None
            self.events = []
            self.iterations = []

        async def get_latest_owned_for_update(self, **scope):
            return self.latest

        async def save_transition(self, *, previous_gate, updated_gate, event):
            assert self.latest == previous_gate
            self.latest = updated_gate
            self.events.append(event)

        async def list_events_owned(self, *, gate_id, **scope):
            return tuple(event for event in self.events if event.gate_id == gate_id)

        async def add_with_event(self, *, gate, event):
            assert gate.iteration not in self.iterations
            self.iterations.append(gate.iteration)
            self.latest = gate
            self.events.append(event)

    gates = Gates()
    monkeypatch.setattr(
        evidence_application, "SqlAlchemyUserTwinVersionRepository", lambda *args, **kw: Versions()
    )
    monkeypatch.setattr(
        evidence_application,
        "SqlAlchemyUserModelingSnapshotRepository",
        lambda *args, **kw: Versions(),
    )
    monkeypatch.setattr(
        evidence_application, "SqlAlchemyHumanGateRepository", lambda *args, **kw: gates
    )

    async def scenario():
        current = snapshot_version()
        original_personas = current.snapshot.persona_versions
        for iteration in range(1, 8):
            twin = current.snapshot.twin_versions[0]
            current = await evidence_application.append_evidence_profiles(
                object(),
                owner_user_id=current.created_by_user_id,
                current=current,
                profiles={twin.twin_id: replace(twin.profile, name=f"Synthetic Twin {iteration}")},
                occurred_at=NOW,
            )
            assert gates.latest.status is HumanGateStatus.APPROVED
            assert gates.latest.iteration == iteration
            assert gates.latest.max_iterations == iteration + 2
            assert user_modeling_gate_is_currently_approved(gates.latest, current)
            assert current.snapshot.persona_versions == original_personas
        assert gates.iterations == list(range(1, 8))
        assert len(gates.events) == 20

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", [{"title": "x" * 201}, {"empirical": True}])
def test_invalid_evidence_response_does_not_echo_text_or_source_metadata(invalid):
    payload = {
        "title": "Synthetic private marker",
        "context": "Synthetic context marker",
        "text": "Synthetic text marker",
        **invalid,
    }
    with pytest.raises(ValidationError) as caught:
        EvidenceBody.model_validate(payload)
    error = RequestValidationError(caught.value.errors(), body=payload)
    request = Request(
        {"type": "http", "path": "/api/v1/projects/synthetic/evidence", "headers": []}
    )
    response = asyncio.run(request_validation_error(request, error))
    assert response.status_code == 422
    body = json.loads(response.body)
    assert body["detail"] == "invalid_request"
    assert all(set(issue) == {"loc", "type"} for issue in body["errors"])
    assert "Synthetic" not in response.body.decode("utf-8")
    assert "input" not in body


def source(text="Synthetic source passage", *, empirical=False):
    return EvidenceVersion(
        id=uuid4(),
        code="EVD-001",
        version=1,
        title="Synthetic technical fixture",
        source_kind=EvidenceSourceKind.EMPIRICAL_RESEARCH
        if empirical
        else EvidenceSourceKind.OWNER_INPUT,
        source_ref="synthetic.invalid/source",
        context="This fixture is not empirical research.",
        method="Synthetic method metadata",
        collected_at=None,
        limitations="No interviews, participants or empirical results.",
        empirical=empirical,
        content_hash=evidence_content_hash(text),
        character_count=len(text),
        byte_count=len(text.encode("utf-8")),
        created_at=NOW,
    )


def change(source, text, field, value, effect=EvidenceEffect.SUPPORTS):
    return EvidenceChange(
        effect=effect,
        field=field,
        value=value,
        citation=EvidenceCitation(
            source.id,
            source.version,
            source.content_hash,
            text,
            0,
            len(text),
            1,
            text.count("\n") + 1,
        ),
    )


def record(source, change, before, after, version=1, *, retired=False):
    return {
        "source_id": source.id,
        "twin_version": version,
        "change": {
            **change.to_snapshot(),
            "empirical_interpretation": source.empirical
            and change.effect is not EvidenceEffect.CONTRADICTS,
        },
        "before": None if before is None else before.to_snapshot(),
        "after": after.to_snapshot(),
        "retired_at": NOW if retired else None,
    }


def original(field=UserTwinField.ROLE, value="Synthetic operator"):
    return user_observation(
        field.observation_key,
        ObservationValue.from_text(value)
        if isinstance(value, str)
        else ObservationValue.from_items(value),
    )


def test_line_endings_are_normalized_once_before_hash_without_changing_other_text():
    raw = "  Ω\r\nA  e\u0301\rB\n"
    stored = normalize_evidence_text(raw)
    assert stored == "  Ω\nA  e\u0301\nB\n"
    assert normalize_evidence_text(stored) == stored
    assert evidence_content_hash(stored) != evidence_content_hash(raw)
    assert evidence_content_hash(stored) != evidence_content_hash(stored.replace("e\u0301", "é"))


@pytest.mark.parametrize(
    "text",
    ["", "\x00text", "x" * 24_001, "Ω" * 17_000, "\ud800"],
    ids=["empty", "nul", "character_limit", "byte_limit", "invalid_unicode"],
)
def test_invalid_or_oversized_documents_are_rejected_without_retaining_the_text(text):
    with pytest.raises(ResearchEvidenceError) as raised:
        normalize_evidence_text(text)
    assert text not in str(raised.value) if text else raised.value.code == "EVIDENCE_INVALID_TEXT"


def test_studio_citation_verifies_exact_unicode_interval_lines_and_hash():
    text = "Ω\nCopied\npassage\nend"
    quote = "Copied\npassage"
    citation = EvidenceCitation(
        uuid4(), 1, evidence_content_hash(text), quote, 2, 2 + len(quote), 2, 3
    )
    assert citation.verify(text)
    assert not citation.verify(text.replace("passage", "passagé"))
    assert not replace(citation, start_line=1).verify(text)
    assert EvidenceCitation.from_snapshot(citation.to_snapshot()) == citation


@pytest.mark.parametrize(
    "empirical,expected",
    [(False, EpistemicStatus.MODEL_INFERRED), (True, EpistemicStatus.EMPIRICALLY_SUPPORTED)],
)
def test_owner_approval_of_source_support_does_not_imply_empirical_or_human_validation(
    empirical, expected
):
    before = original()
    evidence = source("The synthetic operator uses the tool.", empirical=empirical)
    update = change(
        evidence, "The synthetic operator uses the tool.", UserTwinField.ROLE, before.value
    )
    after = apply_evidence_change(
        before, update, evidence, rationale="Synthetic interpretation for a technical check."
    )
    assert after.epistemic_status is expected
    assert after.human_validation is HumanValidationRequirement.REQUIRED
    profile = evidence_profile(twin_profile({UserTwinField.ROLE: before}), (after,))
    assert profile.validation_status is (
        UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT
        if empirical
        else UserTwinLifecycleStatus.PROJECT_GROUNDED_UT
    )
    assert profile.validation_status is not UserTwinLifecycleStatus.EMPIRICALLY_VALIDATED_UT
    assert (
        UserTwinField.ROLE in assess_empirical_grounding(profile).non_empirical_substantive_fields
    ) is (not empirical)


def test_unchanged_support_preserves_existing_independent_human_validation_and_its_withdrawal():
    before = human_validated_observation(UserTwinField.ROLE)
    evidence = source(before.value.text)
    proposal = change(evidence, before.value.text, UserTwinField.ROLE, before.value)
    after = apply_evidence_change(
        before, proposal, evidence, rationale="Additional technical source."
    )
    assert after.value == before.value
    assert after.epistemic_status is EpistemicStatus.HUMAN_VALIDATED
    assert after.human_validation is before.human_validation
    assert all(
        reference in after.provenance.references for reference in before.provenance.references
    )
    withdrawn = withdrawn_observation(
        after, (record(evidence, proposal, before, after),), source_id=evidence.id
    )
    assert withdrawn.epistemic_status is EpistemicStatus.HUMAN_VALIDATED
    assert withdrawn.human_validation is HumanValidationRequirement.NOT_REQUIRED


@pytest.mark.parametrize(
    "effect,statement",
    [
        (EvidenceEffect.SUPPORTS, "Owner corrected the interpretation"),
        (EvidenceEffect.ADDS, None),
        (EvidenceEffect.CONTRADICTS, None),
    ],
)
def test_evidence_changes_do_not_reuse_human_validation_of_changed_or_contested_claims(
    effect, statement
):
    before = human_validated_observation(UserTwinField.ROLE)
    evidence = source(before.value.text)
    proposal = change(evidence, before.value.text, UserTwinField.ROLE, before.value, effect)
    after = apply_evidence_change(
        before, proposal, evidence, statement=statement, rationale="Synthetic interpretation."
    )
    assert after.epistemic_status is not EpistemicStatus.HUMAN_VALIDATED
    assert after.human_validation is HumanValidationRequirement.REQUIRED


def test_a_human_validation_label_without_independent_review_is_not_preserved_by_model_support():
    before = replace(
        original(),
        epistemic_status=EpistemicStatus.HUMAN_VALIDATED,
        human_validation=HumanValidationRequirement.NOT_REQUIRED,
    )
    evidence = source(before.value.text)
    after = apply_evidence_change(
        before,
        change(evidence, before.value.text, UserTwinField.ROLE, before.value),
        evidence,
        rationale="Synthetic interpretation.",
    )
    assert after.epistemic_status is EpistemicStatus.MODEL_INFERRED
    assert after.human_validation is HumanValidationRequirement.REQUIRED


@pytest.mark.parametrize("missing", ["twin", "field"])
def test_import_retains_historical_citations_without_inventing_missing_profiles(missing):
    class Session:
        def __init__(self):
            self.rows = []

        async def execute(self, statement):
            self.rows.append(statement.compile().params)

    session = Session()
    repository = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=uuid4())
    evidence = source("Synthetic historical passage")
    quote = change(
        evidence,
        "Synthetic historical passage",
        UserTwinField.ROLE,
        ObservationValue.from_text("Synthetic old role"),
    ).citation.to_snapshot()
    twin_id, project_id = uuid4(), uuid4()
    origin = {
        "project_id": str(uuid4()),
        "twin_id": str(twin_id),
        "twin_version": 7,
        "status": "ACTIVE",
    }
    payload = {
        "evidence": [],
        "citations": [
            {
                "twin_id": str(twin_id),
                "twin_version": 7,
                "field": "role",
                "effect": "SUPPORTS",
                "citation": quote,
                "status": "ACTIVE",
                "imported_from": origin,
            }
        ],
    }

    async def owned(*args, **kwargs):
        return True

    async def listed(*args, **kwargs):
        return ()

    repository.owned, repository.list = owned, listed
    snapshot = SimpleNamespace(
        twin_versions=()
        if missing == "twin"
        else (
            SimpleNamespace(
                twin_id=twin_id,
                profile=SimpleNamespace(observation_for=lambda field: None),
            ),
        )
    )
    asyncio.run(repository.import_dossier(project_id, payload, snapshot))
    assert len(session.rows) == 1
    stored = session.rows[0]
    assert stored["retired_at"] is not None
    assert stored["after"] == {"kind": "historical-citation", "profile_available": False}
    assert stored["before"] is None
    assert "value" not in stored["change"]
    exported = evidence_citation_from_row(stored)
    assert exported["citation"] == quote
    assert exported["twin_id"] == str(twin_id)
    assert exported["twin_version"] == 7
    assert exported["status"] == "RETIRED"
    assert exported["imported_from"] == origin


def test_partial_list_support_does_not_evidence_unquoted_claims_or_erase_them():
    before = original(UserTwinField.GOALS, ("Inspect result", "Share result"))
    evidence = source("Inspect result", empirical=True)
    proposal = change(evidence, "Inspect result", UserTwinField.GOALS, before.value)
    after = apply_evidence_change(
        before, proposal, evidence, rationale="Only the first item is mentioned."
    )
    assert after.value.items == before.value.items
    assert after.epistemic_status is EpistemicStatus.MODEL_INFERRED
    corrected = apply_evidence_change(
        before,
        proposal,
        evidence,
        statement="The owner corrected the interpretation.",
        rationale="Original interpretation.",
    )
    assert corrected.value == before.value
    assert corrected.rationale == "The owner corrected the interpretation."


def test_adding_corrected_information_preserves_existing_items_and_contesting_keeps_value():
    before = original(UserTwinField.GOALS, ("Inspect result",))
    evidence = source("Share result")
    added = change(
        evidence,
        "Share result",
        UserTwinField.GOALS,
        ObservationValue.from_items(("Share result",)),
        EvidenceEffect.ADDS,
    )
    after = apply_evidence_change(
        before,
        added,
        evidence,
        statement="Share only reviewed result",
        rationale="A synthetic addition.",
    )
    assert after.value.items == ("Inspect result", "Share only reviewed result")
    contested = apply_evidence_change(
        after,
        change(
            evidence, "Share result", UserTwinField.GOALS, after.value, EvidenceEffect.CONTRADICTS
        ),
        evidence,
        statement="Corrected interpretation",
        rationale="A synthetic contradiction.",
    )
    assert contested.value == after.value
    assert contested.epistemic_status is EpistemicStatus.CONTESTED


def test_withdrawing_unique_support_returns_the_claim_to_an_assumption():
    before = original()
    evidence = source("Synthetic operator", empirical=True)
    proposal = change(evidence, "Synthetic operator", UserTwinField.ROLE, before.value)
    after = apply_evidence_change(before, proposal, evidence, rationale="Technical support.")
    withdrawn = withdrawn_observation(
        after, (record(evidence, proposal, before, after),), source_id=evidence.id
    )
    assert withdrawn.value == before.value
    assert withdrawn.epistemic_status is EpistemicStatus.UNSUPPORTED_ASSUMPTION
    assert all(item.source_id != str(evidence.id) for item in withdrawn.provenance.references)
    profile = evidence_profile(twin_profile({UserTwinField.ROLE: after}), (withdrawn,))
    assert profile.validation_status is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT


def test_withdrawing_one_of_two_independent_supports_preserves_other_evidence():
    before = original()
    first = source("Synthetic operator", empirical=True)
    second = source("Synthetic operator", empirical=True)
    a = change(first, "Synthetic operator", UserTwinField.ROLE, before.value)
    supported = apply_evidence_change(before, a, first, rationale="First synthetic support.")
    b = change(second, "Synthetic operator", UserTwinField.ROLE, supported.value)
    twice = apply_evidence_change(supported, b, second, rationale="Second synthetic support.")
    withdrawn = withdrawn_observation(
        twice,
        (record(first, a, before, supported), record(second, b, supported, twice, 2)),
        source_id=first.id,
    )
    assert withdrawn.epistemic_status is EpistemicStatus.EMPIRICALLY_SUPPORTED
    assert any(item.source_id == str(second.id) for item in withdrawn.provenance.references)


@pytest.mark.parametrize("retire_addition", [False, True])
def test_withdrawing_list_sources_recalculates_coverage_on_current_claims(retire_addition):
    before = original(UserTwinField.GOALS, ("Inspect result",))
    first = source("Inspect result", empirical=True)
    second = source("Share result")
    a = change(first, "Inspect result", UserTwinField.GOALS, before.value)
    supported = apply_evidence_change(before, a, first, rationale="First support.")
    b = change(
        second,
        "Share result",
        UserTwinField.GOALS,
        ObservationValue.from_items(("Share result",)),
        EvidenceEffect.ADDS,
    )
    expanded = apply_evidence_change(supported, b, second, rationale="Technical addition.")
    withdrawn = withdrawn_observation(
        expanded,
        (record(first, a, before, supported), record(second, b, supported, expanded, 2)),
        source_id=second.id if retire_addition else first.id,
    )
    assert withdrawn.value.items == ("Inspect result", "Share result")
    assert withdrawn.epistemic_status is EpistemicStatus.MODEL_INFERRED


def test_withdrawing_contradiction_restores_remaining_independent_support():
    before = original()
    first = source("Synthetic operator", empirical=True)
    second = source("A synthetic contradictory passage")
    a = change(first, "Synthetic operator", UserTwinField.ROLE, before.value)
    supported = apply_evidence_change(before, a, first, rationale="Technical support.")
    b = change(
        second,
        "A synthetic contradictory passage",
        UserTwinField.ROLE,
        before.value,
        EvidenceEffect.CONTRADICTS,
    )
    contested = apply_evidence_change(supported, b, second, rationale="Technical contradiction.")
    withdrawn = withdrawn_observation(
        contested,
        (record(first, a, before, supported), record(second, b, supported, contested, 2)),
        source_id=second.id,
    )
    assert withdrawn.epistemic_status is EpistemicStatus.EMPIRICALLY_SUPPORTED


def test_new_nonempirical_support_preserves_existing_independent_empirical_support():
    before = original()
    first = source("Synthetic operator", empirical=True)
    supported = apply_evidence_change(
        before,
        change(first, "Synthetic operator", UserTwinField.ROLE, before.value),
        first,
        rationale="Synthetic empirical-kind fixture.",
    )
    second = source("Synthetic operator")
    after = apply_evidence_change(
        supported,
        change(second, "Synthetic operator", UserTwinField.ROLE, supported.value),
        second,
        rationale="Owner input is not empirical research.",
    )
    assert after.epistemic_status is EpistemicStatus.EMPIRICALLY_SUPPORTED


def test_new_support_does_not_silently_discard_existing_contestation():
    before = original()
    first = source("A synthetic contradictory passage")
    contested = apply_evidence_change(
        before,
        change(
            first,
            "A synthetic contradictory passage",
            UserTwinField.ROLE,
            before.value,
            EvidenceEffect.CONTRADICTS,
        ),
        first,
        rationale="Synthetic contradiction.",
    )
    second = source("Synthetic operator", empirical=True)
    after = apply_evidence_change(
        contested,
        change(second, "Synthetic operator", UserTwinField.ROLE, contested.value),
        second,
        rationale="Support does not withdraw the other source.",
    )
    assert after.epistemic_status is EpistemicStatus.CONTESTED
    withdrawn = withdrawn_observation(
        after,
        (
            record(
                first,
                change(
                    first,
                    "A synthetic contradictory passage",
                    UserTwinField.ROLE,
                    before.value,
                    EvidenceEffect.CONTRADICTS,
                ),
                before,
                contested,
            ),
            record(
                second,
                change(second, "Synthetic operator", UserTwinField.ROLE, contested.value),
                contested,
                after,
                2,
            ),
        ),
        source_id=first.id,
    )
    assert withdrawn.epistemic_status is EpistemicStatus.EMPIRICALLY_SUPPORTED


def test_support_contestation_new_support_and_selective_retirement_keep_independent_sources():
    base = original()
    a = source("Synthetic operator", empirical=True)
    b = source("A synthetic contradictory passage")
    c = source("Synthetic operator", empirical=True)
    first_change = change(a, "Synthetic operator", UserTwinField.ROLE, base.value)
    first = apply_evidence_change(base, first_change, a, rationale="First independent support.")
    contradiction = change(
        b,
        "A synthetic contradictory passage",
        UserTwinField.ROLE,
        base.value,
        EvidenceEffect.CONTRADICTS,
    )
    contested = apply_evidence_change(
        first, contradiction, b, rationale="Independent contradiction."
    )
    second_change = change(c, "Synthetic operator", UserTwinField.ROLE, base.value)
    second = apply_evidence_change(
        contested, second_change, c, rationale="Second independent support."
    )
    assert second.epistemic_status is EpistemicStatus.CONTESTED
    records = [
        record(a, first_change, base, first),
        record(b, contradiction, first, contested, 2),
        record(c, second_change, contested, second, 3),
    ]
    no_contradiction = withdrawn_observation(second, records, source_id=b.id)
    assert no_contradiction.epistemic_status is EpistemicStatus.EMPIRICALLY_SUPPORTED
    records[1] = {**records[1], "retired_at": NOW}
    one_support = withdrawn_observation(no_contradiction, records, source_id=a.id)
    assert one_support.epistemic_status is EpistemicStatus.EMPIRICALLY_SUPPORTED
    records[0] = {**records[0], "retired_at": NOW}
    unsupported = withdrawn_observation(one_support, records, source_id=c.id)
    assert unsupported.epistemic_status is EpistemicStatus.UNSUPPORTED_ASSUMPTION


def test_evidence_update_snapshots_round_trip_and_legacy_payload_does_not_change():
    legacy = twin_update()
    assert "evidence" not in legacy.to_snapshot()
    assert all("evidence" not in item for item in legacy.to_snapshot()["observations"])
    evidence = source()
    proposal = ProposedObservation(
        0,
        "Synthetic claim",
        "Synthetic interpretation",
        evidence=change(
            evidence,
            "Synthetic source passage",
            UserTwinField.ROLE,
            ObservationValue.from_text("Synthetic role"),
            EvidenceEffect.ADDS,
        ),
    )
    update = replace(
        legacy,
        observations=(proposal,),
        material_changes=0,
        material_tests=0,
        evidence=EvidenceUpdateSource(evidence.id, evidence.version, evidence.content_hash, 2),
    )
    assert twin_update_from_snapshot(update.to_snapshot()) == replace(update, generation_ids=())
    empty = replace(update, observations=(), status=UpdateStatus.EMPTY)
    assert empty.to_snapshot()["evidence"]["rejected_changes"] == 2
    assert TwinUpdateRequest().model_dump(mode="json") == {"locale": "it-IT"}


def test_changed_twin_names_linked_scenarios_needs_requirements_and_unapproved_design():
    facts = aligned(user_twins=user_twins(2, twins=frozenset({twin(TWIN_A, 2), twin(TWIN_B)})))
    codes = {
        TWIN_A: {"scenarios": ("SCN-001",), "needs": ("NED-001",), "requirements": ("REQ-001",)},
        TWIN_B: {"scenarios": ("SCN-002",), "needs": (), "requirements": ("REQ-002",)},
    }
    facts = replace(
        facts,
        requirements=replace(facts.requirements, actor_codes=codes),
        design=replace(facts.design, approved=False),
    )
    result = project_sections(facts).to_snapshot()
    by_key = {item["key"]: item for item in result["sections"]}
    assert by_key["DESIGN"]["state"] == "IN_PROGRESS"
    assert SectionReason.USER_TWINS_CHANGED.value in by_key["DESIGN"]["reasons"]
    assert (
        by_key["REQUIREMENTS"]["affected_codes"]
        == by_key["DESIGN"]["affected_codes"]
        == {"scenarios": ["SCN-001"], "needs": ["NED-001"], "requirements": ["REQ-001"]}
    )
    assert by_key["PACKAGE"]["affected_codes"]["requirements"] == ["REQ-001"]


def test_actor_links_follow_scenarios_to_needs_and_requirements():
    scenario_id, need_id, requirement_id = uuid4(), uuid4(), uuid4()
    specification = SimpleNamespace(
        user_twin_references=(SimpleNamespace(twin_id=TWIN_A),),
        scenarios=(
            SimpleNamespace(
                id=scenario_id,
                code="SCN-001",
                actor=SimpleNamespace(twin_id=TWIN_A),
                requirement_ids=(requirement_id,),
            ),
        ),
        needs=(SimpleNamespace(id=need_id, code="NED-001", scenario_ids=(scenario_id,)),),
        requirements=(
            SimpleNamespace(
                id=requirement_id, code="REQ-001", need_ids=(need_id,), user_twin_references=()
            ),
        ),
    )
    assert requirements_actor_codes(specification)[TWIN_A] == {
        "scenarios": ("SCN-001",),
        "needs": ("NED-001",),
        "requirements": ("REQ-001",),
    }
