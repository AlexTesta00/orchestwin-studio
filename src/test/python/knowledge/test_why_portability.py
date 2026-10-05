from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from orchestwin.agents.perspectives import perspective_views
from orchestwin.knowledge.archive import verify_folder
from orchestwin.knowledge.folder import build_knowledge_folder
from orchestwin.knowledge.project_import import plan_documents, plan_project_import
from orchestwin.knowledge.why import WHY_DOCUMENT, normalized_why
from orchestwin.why import build_why_document, explain_why
from src.test.python.knowledge.knowledge_fixtures import PUBLISHED_AT, real_sources
from src.test.python.knowledge.why_fixtures import current_feedback_sources


@pytest.mark.parametrize("feedback", [False, True, "claim"])
def test_import_rebuilds_the_exported_chain_after_identity_and_hash_remapping(feedback):
    sources = (
        current_feedback_sources(claim_reference=feedback == "claim")
        if feedback
        else real_sources()
    )
    folder = build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)
    owner = uuid4()
    moment = datetime.now(UTC)
    imported = plan_project_import(
        verify_folder(folder.files),
        project_id=uuid4(),
        brief_version_id=uuid4(),
        owner_user_id=owner,
        created_at=moment,
    )
    expected = json.loads(folder.files[WHY_DOCUMENT])
    derived = build_why_document(
        project_id=str(imported.project_id),
        stages=plan_documents(imported, owner_user_id=owner, created_at=moment),
        evidence=imported.research_evidence,
        evaluations=[
            {
                "runs": [item.to_snapshot() for item in imported.evaluations],
                "decisions": [item.to_snapshot() for item in imported.finding_decisions],
            }
        ],
    )

    assert normalized_why(
        expected, identities=imported.identities, hashes=imported.hashes
    ) == normalized_why(derived)
    assert "LEARNED_PROJECTION_NOT_RESTORED" in imported.import_limits
    if feedback:
        assert len(imported.evaluations) == 1
        assert imported.finding_decisions[0].decision.value == "OWNER_CONFIRMED"
        assert imported.evaluations[0].findings[0].requires_human_validation is True
        finding = next(node for node in derived["nodes"] if node["kind"] == "SYNTHETIC_FINDING")
        assert finding["current"] is True
        if feedback == "claim":
            assert any(
                link["source"] == finding["key"] and link["kind"] == "GROUNDED_IN"
                for link in derived["links"]
            )


def test_import_declares_a_missing_historical_feedback_context_before_persistence():
    sources = current_feedback_sources()
    folder = build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)
    verified = verify_folder(folder.files)
    reviews = json.loads(verified.files["twins/feedback/reviews.json"])
    reviews["runs"][0]["design_version_id"] = str(uuid4())
    verified.files["twins/feedback/reviews.json"] = json.dumps(reviews)

    imported = plan_project_import(
        verified,
        project_id=uuid4(),
        brief_version_id=uuid4(),
        owner_user_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    assert imported.evaluations == imported.finding_decisions == ()
    assert "FEEDBACK_CONTEXT_NOT_RESTORED" in imported.import_limits
    assert imported.omitted_sections[0]["evaluation_run_id"] == reviews["runs"][0]["id"]
    assert imported.omitted_sections[0]["references"]


def feedback_document(*, runs=None):
    sources = current_feedback_sources()
    folder = build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)
    return build_why_document(
        project_id=str(sources.project_id),
        stages={
            stage: json.loads(folder.files[f"{stage}/{stage}.json"])
            for stage in ("brief", "team", "twins", "requirements", "design")
        },
        evidence=json.loads(folder.files["twins/evidence.json"])
        if "twins/evidence.json" in folder.files
        else None,
        evaluations=runs if runs is not None else [sources.feedback.runs[0].to_snapshot()],
    )


def test_real_feedback_snapshots_compute_the_same_current_state_with_runtime_annotations():
    sources = current_feedback_sources()
    run = sources.feedback.runs[0].to_snapshot()
    annotated = {**run, "current": False}

    assert feedback_document(runs=[annotated]) == feedback_document(runs=[run])
    finding = next(
        node for node in feedback_document()["nodes"] if node["kind"] == "SYNTHETIC_FINDING"
    )
    assert finding["current"] is True


def test_latest_feedback_uses_completion_time_and_exact_design_context():
    run = current_feedback_sources().feedback.runs[0].to_snapshot()
    earlier = {
        **run,
        "id": str(uuid4()),
        "started_at": "2030-01-01T00:00:00Z",
        "completed_at": "2020-01-01T00:00:00Z",
    }
    document = feedback_document(runs=[run, earlier])
    findings = [node for node in document["nodes"] if node["kind"] == "SYNTHETIC_FINDING"]

    assert sum(node["current"] for node in findings) == 1
    assert (
        next(node for node in findings if node["current"])["declared_context"][
            "evaluation_reference"
        ]["artifact_id"]
        == run["id"]
    )
    assert document == feedback_document(runs=[earlier, run])
    latest = {
        **run,
        "id": str(uuid4()),
        "completed_at": "2031-01-01T00:00:00Z",
        "design_content_hash": "f" * 64,
        "current": True,
    }
    assert not any(
        node["current"]
        for node in feedback_document(runs=[run, latest])["nodes"]
        if node["kind"] == "SYNTHETIC_FINDING"
    )


def test_unanchored_finding_keeps_exact_context_and_declares_missing_claim():
    document = feedback_document()
    finding = next(node for node in document["nodes"] if node["kind"] == "SYNTHETIC_FINDING")
    targets = {
        link["target"]
        for link in document["links"]
        if link["source"] == finding["key"] and link["kind"] == "CONTEXT"
    }

    assert {node["kind"] for node in document["nodes"] if node["key"] in targets} == {
        "DESIGN_PACKAGE",
        "DESIGN_ALTERNATIVE",
    }
    assert "MISSING_CLAIM" in {gap["code"] for gap in finding["gaps"]}
    assert not any(
        link["source"] == finding["key"] and link["kind"] == "GROUNDED_IN"
        for link in document["links"]
    )
    answer = explain_why(document, finding["key"])
    assert answer["target"]["validation_required"] is True
    assert "MISSING_CLAIM" in answer["summary"]["stop_reasons"]


def test_normalization_ignores_only_explicit_visual_derivation_and_retains_reference_versions():
    document = feedback_document()
    changed = deepcopy(document)
    document["nodes"][0]["declared_context"]["mockup"] = {
        "visual_derived": True,
        "document_hashes": {"screen": "a" * 64},
    }
    changed["nodes"][0]["declared_context"]["mockup"] = {
        "visual_derived": True,
        "document_hashes": {"screen": "b" * 64},
    }

    assert normalized_why(document) == normalized_why(changed)
    document["nodes"][0]["declared_context"]["mockup"]["visual_derived"] = False
    changed["nodes"][0]["declared_context"]["mockup"]["visual_derived"] = False
    assert normalized_why(document) != normalized_why(changed)
    changed = deepcopy(document)
    changed["nodes"][0]["reference"]["version_number"] += 1
    assert normalized_why(document, remap_versions=False) != normalized_why(
        changed, remap_versions=False
    )


def test_declared_perspectives_match_the_exact_generation_team_without_becoming_rationale():
    sources = current_feedback_sources()
    proposal = sources.team.proposal
    active = {
        view.key.value
        for view in perspective_views(proposal.constraints, proposal.selected_agent_ids)
        if view.applied
    }
    document = feedback_document()
    requirement = next(
        node
        for node in document["nodes"]
        if node["kind"] == "REQUIREMENT" and "MISSING_NEED" in {gap["code"] for gap in node["gaps"]}
    )

    assert {item["key"] for item in requirement["declared_context"]["perspectives"]} == active
    assert requirement["declared_context"]["team_reference"]["artifact_id"] == str(sources.team.id)
    assert not any(
        link["source"] == requirement["key"] and link["kind"] == "MOTIVATED_BY"
        for link in document["links"]
    )


def test_legacy_import_without_feedback_declares_the_omission():
    sources = real_sources()
    folder = build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)
    verified = verify_folder(folder.files)
    verified.manifest.pop("why")
    verified.files.pop("twins/feedback/reviews.json")

    imported = plan_project_import(
        verified,
        project_id=uuid4(),
        brief_version_id=uuid4(),
        owner_user_id=uuid4(),
        created_at=datetime.now(UTC),
    )

    assert "LEGACY_FEEDBACK_CONTEXT_MISSING" in imported.import_limits
    assert imported.evaluations == ()


def test_portable_claim_keeps_the_original_observation_value():
    sources = current_feedback_sources()
    twin = sources.modeling.snapshot.twin_versions[0]
    observation = next(
        item for item in twin.profile.observations if item.observation_key == "user_twin.goals"
    )
    document = feedback_document()
    claim = next(
        node
        for node in document["nodes"]
        if node["kind"] == "USER_TWIN_CLAIM"
        and node["reference"]["artifact_id"] == str(twin.twin_id)
        and node["title"] == "goals"
    )

    assert claim["declared_context"]["observation_value"] == observation.value.to_snapshot()
    changed = deepcopy(document)
    next(node for node in changed["nodes"] if node["key"] == claim["key"])["declared_context"][
        "observation_value"
    ] = {"kind": "UNKNOWN"}
    assert normalized_why(document) != normalized_why(changed)
