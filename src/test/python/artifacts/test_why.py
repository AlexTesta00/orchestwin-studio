from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.projects.evidence_application import apply_evidence_change, withdrawn_observation
from orchestwin.projects.requirements_primitives import (
    RequirementSourceKind,
    RequirementSourceReference,
    UserTwinVersionReference,
)
from orchestwin.projects.research_evidence import EvidenceEffect, EvidenceStatus
from orchestwin.twins.epistemics import EvidenceReference, EvidenceSourceKind, ObservationProvenance
from orchestwin.twins.representation import observation_display_status
from orchestwin.twins.user_twins import UserTwinField
from orchestwin.why import WhyError, build_why_document, explain_why
from src.test.python.artifacts.design_fixtures import design_version, requirements_version
from src.test.python.projects.test_requirements_needs import enriched_specification
from src.test.python.projects.test_research_evidence import change, source
from src.test.python.projects.test_research_evidence import record as evidence_record
from src.test.python.twins.test_user_modeling_persistence import snapshot_version


def chain(*, effect=EvidenceEffect.SUPPORTS, retired=False, text_available=True):
    modeling = snapshot_version()
    twin = modeling.snapshot.twin_versions[0]
    original = twin.profile.observation_for(UserTwinField.GOALS)
    evidence = source("Synthetic quote\nè exact", empirical=True)
    changed = change(
        evidence, "Synthetic quote\nè exact", UserTwinField.GOALS, original.value, effect
    )
    observation = apply_evidence_change(
        original, changed, evidence, rationale="Synthetic model interpretation."
    )
    profile = replace(
        twin.profile,
        observations=tuple(
            observation if item.observation_key == observation.observation_key else item
            for item in twin.profile.observations
        ),
    )
    twin = replace(twin, profile=profile, content_hash=profile.content_hash)
    snapshot = replace(modeling.snapshot, twin_versions=(twin,))
    modeling = replace(modeling, snapshot=snapshot, content_hash=snapshot.content_hash)
    legacy = requirements_version()
    specification = enriched_specification(legacy.specification)
    twin_ref = UserTwinVersionReference(
        twin.twin_id, twin.version_number, twin.content_hash, twin.profile.name
    )
    origin = RequirementSourceReference(
        RequirementSourceKind.USER_TWIN,
        str(twin.twin_id),
        twin.version_number,
        twin.content_hash,
        "user_twin.goals",
    )
    specification = replace(
        specification,
        user_twin_references=(twin_ref,),
        requirements=tuple(
            replace(item, sources=(origin,), user_twin_references=(twin_ref,))
            for item in specification.requirements
        ),
        user_stories=tuple(
            replace(item, user_twin_reference=twin_ref) for item in specification.user_stories
        ),
        needs=tuple(replace(item, sources=(origin,)) for item in specification.needs),
        scenarios=tuple(
            replace(item, actor=twin_ref, sources=(origin,)) for item in specification.scenarios
        ),
    )
    requirements = replace(
        legacy, specification=specification, content_hash=specification.content_hash
    )
    citation = {
        "twin_id": str(twin.twin_id),
        "twin_version": twin.version_number,
        "field": "goals",
        "effect": effect.value,
        "citation": changed.citation.to_snapshot(),
        "status": "RETIRED" if retired else "ACTIVE",
    }
    evidence = replace(
        evidence,
        status=EvidenceStatus.RETIRED if retired else EvidenceStatus.ACTIVE,
        text_available=text_available,
        retired_at=evidence.created_at if retired else None,
    )
    stages = {"twins": modeling.to_snapshot(), "requirements": requirements.to_snapshot()}
    dossier = {"evidence": [evidence.to_snapshot()], "citations": [citation]}
    return stages, dossier, twin, observation


def claim_code(twin, field="goals"):
    return f"UT-{twin.twin_id.hex[:8].upper()}-v{twin.version_number}:user_twin.{field}"


def test_semantic_chain_reaches_exact_claim_and_citation_without_scenario_cycle():
    stages, evidence, twin, observation = chain()
    original = deepcopy((stages, evidence))
    document = build_why_document(project_id="synthetic-project", stages=stages, evidence=evidence)
    answer = explain_why(document, "REQ-001")
    assert answer["summary"]["complete_to_twin"]
    assert answer["summary"]["complete_to_evidence"]
    assert answer["summary"]["all_paths_complete"]
    assert {item["kind"] for item in answer["upstream"]} >= {"NEED", "SCENARIO", "USER_TWIN_CLAIM"}
    scenario = next(item for item in document["nodes"] if item["kind"] == "SCENARIO")
    assert not any(
        link["source"] == scenario["key"]
        and next(node for node in document["nodes"] if node["key"] == link["target"])["kind"]
        in {"REQUIREMENT", "ACCEPTANCE_CRITERION"}
        for link in document["links"]
    )
    target = explain_why(document, claim_code(twin))["target"]
    assert target["display_status"] == observation_display_status(observation).value
    assert target["citations"][0]["citation"] == evidence["citations"][0]["citation"]
    assert target["reference"]["content_hash"] == twin.content_hash
    assert (stages, evidence) == original
    assert (
        build_why_document(project_id="synthetic-project", stages=stages, evidence=evidence)
        == document
    )


def test_absent_original_body_keeps_exact_active_citation_complete():
    stages, evidence, twin, _ = chain(text_available=False)
    answer = explain_why(
        build_why_document(project_id="p", stages=stages, evidence=evidence), claim_code(twin)
    )
    assert answer["summary"]["complete_to_evidence"]
    assert answer["summary"]["all_paths_complete"]
    assert "SOURCE_TEXT_UNAVAILABLE" in answer["limits"]


def test_retired_source_is_readable_history_without_active_support():
    stages, evidence, twin, _ = chain(retired=True, text_available=False)
    answer = explain_why(
        build_why_document(project_id="p", stages=stages, evidence=evidence), claim_code(twin)
    )
    assert answer["summary"]["complete_to_twin"]
    assert not answer["summary"]["complete_to_evidence"]
    assert "SOURCE_RETIRED" in answer["summary"]["stop_reasons"]
    assert answer["target"]["citations"][0]["citation"] == evidence["citations"][0]["citation"]


def test_a_source_on_goals_does_not_support_another_field_or_twin_actor_only():
    stages, evidence, twin, _ = chain()
    document = build_why_document(project_id="p", stages=stages, evidence=evidence)
    assert not explain_why(document, claim_code(twin, "pain_points"))["summary"][
        "complete_to_evidence"
    ]
    stages["requirements"]["specification"]["scenarios"][0]["sources"] = []
    scenario = explain_why(
        build_why_document(project_id="p", stages=stages, evidence=evidence), "SCN-001"
    )
    assert scenario["summary"]["complete_to_twin"]
    assert not scenario["summary"]["complete_to_evidence"]


def test_contradiction_remains_contested_and_requires_real_people():
    stages, evidence, twin, _ = chain(effect=EvidenceEffect.CONTRADICTS)
    answer = explain_why(
        build_why_document(project_id="p", stages=stages, evidence=evidence), claim_code(twin)
    )
    assert answer["target"]["display_status"] == "CONTESTED"
    assert answer["target"]["validation_required"]
    assert not answer["summary"]["complete_to_evidence"]
    assert "MISSING_SOURCE" in answer["summary"]["stop_reasons"]
    assert answer["human_validation"]


def test_complete_branch_does_not_hide_another_missing_empirical_reference():
    stages, evidence, twin, observation = chain()
    missing = EvidenceReference(
        EvidenceSourceKind.EMPIRICAL_RESEARCH, str(UUID(int=8934)), 1, "c" * 64, "user_twin.goals"
    )
    observation = replace(
        observation,
        provenance=ObservationProvenance.from_references(
            (*observation.provenance.references, missing)
        ),
    )
    payload = stages["twins"]["snapshot"]["twin_versions"][0]
    payload["profile"]["observations"] = [
        observation.to_snapshot()
        if item["observation_key"] == observation.observation_key
        else item
        for item in payload["profile"]["observations"]
    ]
    answer = explain_why(
        build_why_document(project_id="p", stages=stages, evidence=evidence), claim_code(twin)
    )
    assert answer["summary"]["complete_to_evidence"]
    assert not answer["summary"]["all_paths_complete"]
    assert any(gap["related_code"] == str(UUID(int=8934)) for gap in answer["gaps"])


def test_persona_alias_uses_one_claim_and_exact_persona_fallback_origin():
    modeling = snapshot_version()
    twin = modeling.snapshot.twin_versions[0]
    document = build_why_document(project_id="p", stages={"twins": modeling.to_snapshot()})
    base = claim_code(twin).split(":", 1)[0]
    assert explain_why(document, f"{base}:persona.needs") == explain_why(
        document, claim_code(twin, "information_needs")
    )
    description = explain_why(document, claim_code(twin, "description"))["target"]
    persona = modeling.snapshot.persona_versions[0]
    assert (
        description["declared_context"]["observation_reference"]["content_hash"]
        == persona.content_hash
    )
    assert (
        len([node for node in document["nodes"] if node["code"] == claim_code(twin, "description")])
        == 1
    )


def test_reused_twin_in_two_snapshots_deduplicates_citations():
    stages, evidence, twin, _ = chain()
    historical = deepcopy(stages["twins"])
    current = deepcopy(historical)
    current.update(id=str(UUID(int=999)), version_number=2, content_hash="b" * 64)
    stages["twins"] = [historical, current]
    document = build_why_document(project_id="p", stages=stages, evidence=evidence)
    assert len(explain_why(document, claim_code(twin))["target"]["citations"]) == 1


def test_nonfunctional_legacy_requirement_declares_exact_generation_perspectives():
    version = requirements_version().to_snapshot()
    team_reference = version["specification"]["context"]["agent_team"]
    team = {
        "id": team_reference["artifact_id"],
        "version_number": team_reference["version_number"],
        "content_hash": team_reference["content_hash"],
        "proposal": {"selected_agent_ids": ["REQUIREMENTS_ANALYST", "SECURITY_REVIEWER"]},
    }
    current = {
        "id": str(UUID(int=987)),
        "version_number": 2,
        "content_hash": "9" * 64,
        "proposal": {"selected_agent_ids": ["ACCESSIBILITY_REVIEWER"]},
    }
    document = build_why_document(
        project_id="p", stages={"requirements": version, "team": [team, current]}
    )
    answer = explain_why(document, "REQ-001")
    assert {view["key"] for view in answer["declared_context"]["perspectives"]} == {
        "PRODUCT",
        "SECURITY",
    }
    assert answer["target"]["rationale"] is None
    assert "MISSING_NEED" in answer["summary"]["stop_reasons"]
    assert not any(node["kind"] == "AGENT_TEAM" for node in answer["upstream"])


def test_historical_duplicate_code_requires_an_exact_selector():
    version = requirements_version().to_snapshot()
    historical = deepcopy(version)
    historical.update(id=str(UUID(int=899)), version_number=2, content_hash="f" * 64)
    document = build_why_document(project_id="p", stages={"requirements": [version, historical]})
    with pytest.raises(WhyError) as caught:
        explain_why(document, "REQ-001")
    assert caught.value.code == "WHY_CODE_AMBIGUOUS"
    assert len(caught.value.candidates) == 2
    assert not explain_why(document, caught.value.candidates[0])["target"]["current"]


@pytest.mark.parametrize("code", ["", "REQ 001", " REQ-001", "REQ-001\n", "../secret?x"])
def test_invalid_selector_is_rejected(code):
    with pytest.raises(WhyError) as caught:
        explain_why({"project_id": "p", "nodes": []}, code)
    assert caught.value.code == "WHY_CODE_INVALID"


def test_mockup_elements_and_alternatives_are_visible_before_choice_and_when_outdated():
    version = design_version().to_snapshot()
    document = build_why_document(
        project_id="p",
        stages={"design": version},
        sections={"sections": [{"key": "DESIGN", "state": "TO_UPDATE"}]},
    )
    kinds = {node["kind"] for node in document["nodes"]}
    assert {"DESIGN_ALTERNATIVE", "DESIGN_SELECTION", "PROTOTYPE_ELEMENT"} <= kinds
    element = next(node for node in document["nodes"] if node["kind"] == "PROTOTYPE_ELEMENT")
    assert element["current"]
    assert "CONTEXT_OUTDATED" in explain_why(document, element["key"])["limits"]
    version["package"].update(prototype=None, owner_selected_alternative_id=None)
    unchosen = build_why_document(project_id="p", stages={"design": version})
    assert len([node for node in unchosen["nodes"] if node["kind"] == "DESIGN_ALTERNATIVE"]) == 2


def test_missing_version_does_not_replace_a_historical_claim_with_current():
    stages, evidence, twin, _ = chain()
    source_ref = stages["requirements"]["specification"]["requirements"][0]["sources"][0]
    source_ref["source_version"] = 9
    answer = explain_why(
        build_why_document(project_id="p", stages=stages, evidence=evidence), "REQ-001"
    )
    assert any(gap["code"] == "MISSING_CLAIM" for gap in answer["gaps"])
    assert not answer["summary"]["all_paths_complete"]
    assert twin.version_number == 1


def test_withdrawn_system_rationale_is_not_attributed_to_remaining_value_provenance():
    stages, evidence, twin, observation = chain()
    empirical = source("Synthetic source", empirical=True)
    change_record = change(empirical, "Synthetic source", UserTwinField.GOALS, observation.value)
    withdrawn = withdrawn_observation(
        observation,
        (evidence_record(empirical, change_record, observation, observation),),
        source_id=empirical.id,
    )
    profile = replace(
        twin.profile,
        observations=tuple(
            withdrawn if item.observation_key == withdrawn.observation_key else item
            for item in twin.profile.observations
        ),
    )
    changed_twin = replace(twin, profile=profile, content_hash=profile.content_hash)
    stages["twins"]["snapshot"]["twin_versions"] = [changed_twin.to_snapshot()]
    answer = explain_why(
        build_why_document(project_id="p", stages=stages, evidence=evidence),
        claim_code(changed_twin),
    )
    assert answer["target"]["rationale"]["origin"] == "UNKNOWN"
    assert answer["target"]["declared_context"]["provenance"] == withdrawn.provenance.to_snapshot()


def test_imported_citation_keeps_original_twin_version_with_attested_mapping():
    stages, evidence, twin, _ = chain()
    citation = evidence["citations"][0]
    citation["twin_version"] = 7
    citation["imported_from"] = {"twin_version": 7, "mapped_twin_version": 1}
    document = build_why_document(project_id="p", stages=stages, evidence=evidence)
    answer = explain_why(document, claim_code(twin))
    assert answer["summary"]["complete_to_evidence"]
    assert answer["target"]["citations"][0]["twin_version"] == 7
    citation["citation"]["content_hash"] = "b" * 64
    changed = explain_why(
        build_why_document(project_id="p", stages=stages, evidence=evidence), claim_code(twin)
    )
    assert not changed["summary"]["complete_to_evidence"]


def test_imported_citation_without_mapping_is_historical_and_does_not_fill_current_claim():
    stages, evidence, twin, _ = chain()
    evidence["citations"][0]["twin_version"] = 7
    evidence["citations"][0]["imported_from"] = {"twin_version": 7}
    answer = explain_why(
        build_why_document(project_id="p", stages=stages, evidence=evidence), claim_code(twin)
    )
    assert not answer["summary"]["complete_to_evidence"]


def test_synthetic_finding_anchors_and_owner_decision_remain_synthetic():
    from src.test.python.artifacts.test_design_evaluation import stored_run

    run = stored_run("SCR-001/ELM-001").to_snapshot()
    decision = {
        "evaluation_run_id": run["id"],
        "twin_id": run["responses"][0]["twin_id"],
        "finding_id": "UTF-001",
        "sequence_number": 1,
        "decision": "OWNER_CONFIRMED",
    }
    document = build_why_document(
        project_id="p",
        stages={"design": design_version().to_snapshot()},
        evaluations=[{"runs": [run], "decisions": [decision]}],
    )
    answer = explain_why(document, "UTF-001")
    assert answer["target"]["display_status"] == "INFERRED"
    assert answer["target"]["validation_required"]
    assert answer["target"]["declared_context"]["owner_decision"] == decision
    assert any(node["kind"] == "PROTOTYPE_ELEMENT" for node in answer["upstream"])
    another = deepcopy(run)
    another["id"] = str(UUID(int=3434))
    document = build_why_document(project_id="p", stages={}, evaluations=[run, another])
    with pytest.raises(WhyError, match="WHY_CODE_AMBIGUOUS"):
        explain_why(document, "UTF-001")


def test_generated_mockup_selector_metadata_matches_the_existing_renderer():
    import hashlib

    from orchestwin.artifacts.generated_mockup_document import mockup_document
    from orchestwin.artifacts.why_mockups import mockup_document_hashes
    from src.test.python.artifacts.test_design_evaluation import generated_version

    version = generated_version()
    package = version.package
    hashes = mockup_document_hashes(package)
    screen = package.generated_mockup.mockup.screens[0]
    alternative = next(
        item
        for item in package.alternatives
        if item.id == package.generated_mockup.design_alternative_id
    )
    expected = mockup_document(
        package.generated_mockup.mockup,
        tokens=alternative.visual_language.token_values,
        language="it",
        entry_screen=screen.code,
    )
    assert hashes[screen.code] == hashlib.sha256(expected.encode("utf-8")).hexdigest()
    envelope = {**version.to_snapshot(), "mockup_document_hashes": hashes}
    document = build_why_document(project_id="p", stages={"design": envelope})
    element = next(node for node in document["nodes"] if node["kind"] == "PROTOTYPE_ELEMENT")
    assert element["declared_context"]["mockup"]["document_hashes"] == hashes
    assert element["declared_context"]["mockup"]["alternative_id"] == str(alternative.id)


def test_cyclic_input_graph_is_finite_and_does_not_attest_all_paths():
    stages, evidence, _, _ = chain()
    document = build_why_document(project_id="p", stages=stages, evidence=evidence)
    requirement = next(node for node in document["nodes"] if node["kind"] == "REQUIREMENT")
    need = next(node for node in document["nodes"] if node["kind"] == "NEED")
    document["links"].append(
        {"source": need["key"], "target": requirement["key"], "kind": "GROUNDED_IN"}
    )
    answer = explain_why(document, "REQ-001")
    assert answer["summary"]["complete_to_evidence"]
    assert not answer["summary"]["all_paths_complete"]
    assert answer["summary"]["upstream_count"] <= len(document["nodes"])
