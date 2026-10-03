from copy import deepcopy
from dataclasses import replace

from orchestwin.projects.owner_requirements import owner_specification
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
)
from orchestwin.why import build_why_document, explain_why
from orchestwin.workflow_inputs import PROVIDED_PROTOTYPE_LIMITS, workflow_records
from src.test.python.knowledge.knowledge_fixtures import real_documents, real_sources
from src.test.python.knowledge.test_workflow_portability36 import workflow_sources
from src.test.python.projects.test_requirements_needs import enriched_specification


def test_why_supplied_prototype_preserves_real_bindings_origin_and_every_declared_limit():
    sources = workflow_sources()
    stages = {key: value for key, value in real_documents().items() if key != "design"}
    records = sources.workflow_inputs
    original = deepcopy((stages, records))
    document = build_why_document(
        project_id=str(sources.project_id), stages=stages, workflow_inputs=records
    )
    answer = explain_why(document, "PRT-001")
    target = answer["target"]
    assert target["kind"] == "PROVIDED_PROTOTYPE" and target["current"]
    assert target["declared_context"]["origin"] == "OWNER_INPUT"
    assert target["declared_context"]["provided_prototype"]["declared_origin"] == "Figma desktop"
    assert set(PROVIDED_PROTOTYPE_LIMITS).issubset(answer["limits"])
    traced = {node["code"] for node in answer["upstream"] if node["kind"] == "REQUIREMENT"}
    assert traced == {"REQ-001", "REQ-002"}
    assert any(
        gap["code"] == "MISSING_REQUIREMENT_ANCHOR" and gap["related_code"] == "REQ-003"
        for gap in target["gaps"]
    )
    assert not any(node["kind"] == "SYNTHETIC_FINDING" for node in document["nodes"])
    assert (stages, records) == original


def test_why_gap_resolution_keeps_both_owner_decisions_without_inventing_empirical_support():
    sources = workflow_sources(resolved=True)
    stages = {key: value for key, value in real_documents().items() if key != "design"}
    document = build_why_document(
        project_id=str(sources.project_id), stages=stages, workflow_inputs=sources.workflow_inputs
    )
    history = sorted(
        (node for node in document["nodes"] if node["kind"] == "WORKFLOW_DECISION"),
        key=lambda item: item["reference"]["version_number"],
    )
    assert len(history) == 2 and not history[0]["current"] and history[1]["current"]
    assert [item["rationale"]["origin"] for item in history] == ["OWNER", "OWNER"]
    assert not any(gap["code"] == "DECLARED_MISSING" for node in history for gap in node["gaps"])
    assert not any(node["kind"] == "RESEARCH_EVIDENCE" for node in document["nodes"])
    assert all(node["display_status"] != "EVIDENCED" for node in history)
    declared = workflow_sources()
    active = build_why_document(
        project_id=str(declared.project_id), stages=stages, workflow_inputs=declared.workflow_inputs
    )
    answer = explain_why(active, "GAP-001")
    assert answer["target"]["rationale"]["origin"] == "OWNER"
    assert "DECLARED_MISSING" in answer["limits"]


def test_why_prototype_versions_are_auditable_and_latest_does_not_depend_on_record_order():
    sources = workflow_sources(history=True)
    stages = {key: value for key, value in real_documents().items() if key != "design"}
    records = sources.workflow_inputs
    document = build_why_document(
        project_id=str(sources.project_id), stages=stages, workflow_inputs=records
    )
    nodes = sorted(
        (item for item in document["nodes"] if item["kind"] == "PROVIDED_PROTOTYPE"),
        key=lambda item: item["reference"]["version_number"],
    )
    assert [item["reference"]["version_number"] for item in nodes] == [1, 2]
    assert [item["current"] for item in nodes] == [False, True]
    assert nodes[0]["reference"]["content_hash"] != nodes[1]["reference"]["content_hash"]
    shuffled = workflow_records(
        sources.project_id, records["decisions"], reversed(records["prototypes"])
    )
    reordered = build_why_document(
        project_id=str(sources.project_id), stages=stages, workflow_inputs=shuffled
    )
    assert reordered["nodes"] == document["nodes"] and reordered["links"] == document["links"]


def test_owner_definition_rationale_and_owner_twin_claim_remain_inspectable_hypotheses():
    sources = real_sources()
    spec = owner_specification(
        replace(enriched_specification(), project_id=sources.project_id),
        owner_user_id=sources.brief.created_by_user_id,
    )
    requirements = replace(sources.requirements, specification=spec, content_hash=spec.content_hash)
    twin = sources.modeling.snapshot.twin_versions[0]
    observations = tuple(
        replace(
            item,
            epistemic_status=EpistemicStatus.USER_PROVIDED,
            confidence=ConfidenceScore(1),
            provenance=ObservationProvenance.from_references(
                (
                    EvidenceReference(
                        source_kind=EvidenceSourceKind.OWNER_INPUT,
                        source_id="owner-provided-profile",
                        locator=item.observation_key,
                    ),
                )
            ),
            human_validation=HumanValidationRequirement.NOT_REQUIRED,
            rationale="Supplied by the owner; field research is missing.",
        )
        for item in twin.profile.observations
    )
    profile = replace(twin.profile, observations=observations)
    twin = replace(twin, profile=profile, content_hash=profile.content_hash)
    snapshot = replace(
        sources.modeling.snapshot,
        twin_versions=(twin, *sources.modeling.snapshot.twin_versions[1:]),
    )
    modeling = replace(sources.modeling, snapshot=snapshot, content_hash=snapshot.content_hash)
    document = build_why_document(
        project_id=str(sources.project_id),
        stages={"twins": modeling.to_snapshot(), "requirements": requirements.to_snapshot()},
    )
    requirement_nodes = [node for node in document["nodes"] if node["kind"] == "REQUIREMENT"]
    assert requirement_nodes and all(
        node["rationale"]["origin"] == "OWNER"
        for node in requirement_nodes
        if node["rationale"] is not None
    )
    claims = [
        node
        for node in document["nodes"]
        if node["kind"] == "USER_TWIN_CLAIM"
        and node["reference"]["artifact_id"] == str(twin.twin_id)
        and node["code"].split(":", 1)[1] in {item.observation_key for item in observations}
        and node["rationale"] is not None
    ]
    assert claims and all(node["rationale"]["origin"] == "OWNER" for node in claims)
    assert all(node["display_status"] != "EVIDENCED" for node in claims)
    assert not any(node["kind"] == "RESEARCH_EVIDENCE" for node in document["nodes"])


def test_why_empty_workflow_input_has_identical_legacy_output():
    sources = real_sources()
    stages = real_documents()
    legacy = build_why_document(project_id=str(sources.project_id), stages=stages)
    explicit = build_why_document(
        project_id=str(sources.project_id),
        stages=stages,
        workflow_inputs=workflow_records(sources.project_id),
    )
    assert explicit == legacy and "workflow_records" not in legacy
