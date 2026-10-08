from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from orchestwin.artifacts.design_evaluation import (
    anchor_finding,
    create_design_evaluation_run,
    design_evaluation_run_from_snapshot,
)
from orchestwin.evaluation.evaluator import (
    UserTwinEvaluationResponse,
    user_twin_evaluation_response_hash,
)
from orchestwin.knowledge.archive import verify_folder
from orchestwin.knowledge.folder import build_knowledge_folder
from orchestwin.knowledge.layout import STAGES
from orchestwin.knowledge.project_import import plan_documents, plan_project_import
from orchestwin.knowledge.project_import_persistence import _import_record, _record_values
from orchestwin.knowledge.project_import_service import import_record
from orchestwin.knowledge.sources import knowledge_feedback
from orchestwin.knowledge.why import importable_why, normalized_why
from orchestwin.why import build_why_document
from src.test.python.knowledge.knowledge_fixtures import PUBLISHED_AT
from src.test.python.knowledge.why_fixtures import current_feedback_sources

ANCHOR = "SCR-001/ELM-007"


def anchored_feedback_sources(element_code):
    sources = current_feedback_sources(claim_reference=True)
    [run] = sources.feedback.runs
    [response] = run.responses
    values = {
        "evaluation_run_id": response.evaluation_run_id,
        "artifact_bundle_id": response.artifact_bundle_id,
        "artifact_bundle_hash": response.artifact_bundle_hash,
        "twin_id": response.twin_id,
        "twin_version": response.twin_version,
        "evaluator": response.evaluator,
        "findings": tuple(anchor_finding(item, ANCHOR, element_code) for item in response.findings),
        "summary": response.summary,
        "evidence_gaps": response.evidence_gaps,
    }
    anchored = UserTwinEvaluationResponse(
        **values,
        completed_at=response.completed_at,
        content_hash=user_twin_evaluation_response_hash(**values),
    )
    anchored_run = create_design_evaluation_run(
        run_id=run.id,
        owner_user_id=run.owner_user_id,
        version=sources.design,
        bundle=run.bundle,
        responses=(anchored,),
        started_at=run.started_at,
        completed_at=run.completed_at,
    )
    return replace(
        sources,
        feedback=knowledge_feedback(runs=(anchored_run,), validations=sources.feedback.validations),
    )


def mixed_feedback_sources():
    sources = current_feedback_sources(claim_reference=True)
    previous = current_feedback_sources(
        sources=replace(sources, design=replace(sources.design, id=uuid4())),
        run_id=uuid4(),
    )
    return replace(
        sources,
        feedback=knowledge_feedback(
            runs=(*sources.feedback.runs, *previous.feedback.runs),
            validations=(*sources.feedback.validations, *previous.feedback.validations),
        ),
    )


@pytest.mark.parametrize("legacy", [False, True])
def test_history_is_exported_but_missing_context_is_explicitly_omitted_from_import(legacy):
    sources = mixed_feedback_sources()
    folder = build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)
    verified = verify_folder(folder.files)
    if legacy:
        verified.manifest.pop("why")
    owner, project, moment = uuid4(), uuid4(), datetime.now(UTC)
    plan = plan_project_import(
        verified,
        project_id=project,
        brief_version_id=uuid4(),
        owner_user_id=owner,
        created_at=moment,
    )
    exported = json.loads(folder.files["twins/feedback/reviews.json"])
    assert len(exported["runs"]) == len(exported["decisions"]) == 2
    assert len(plan.evaluations) == len(plan.finding_decisions) == 1
    assert plan.finding_decisions[0].decision == sources.feedback.validations[0].decision
    assert plan.finding_decisions[0].note == sources.feedback.validations[0].note
    assert plan.omitted_sections[0]["reason"] == "FEEDBACK_CONTEXT_NOT_RESTORED"
    omitted_id = plan.omitted_sections[0]["evaluation_run_id"]
    assert omitted_id not in {str(item.id) for item in plan.evaluations}
    assert json.loads(verified.files["twins/feedback/reviews.json"]) == exported
    rebuilt = build_why_document(
        project_id=str(project),
        stages=plan_documents(plan, owner_user_id=owner, created_at=moment),
        evaluations=[
            {
                "runs": [item.to_snapshot() for item in plan.evaluations],
                "decisions": [item.to_snapshot() for item in plan.finding_decisions],
            }
        ],
    )
    assert normalized_why(
        importable_why(verified, plan.omitted_sections),
        identities=plan.identities,
        hashes=plan.hashes,
    ) == normalized_why(rebuilt)


@pytest.mark.parametrize("element_code", [None, "ELM-007"])
def test_the_import_keeps_the_anchor_and_the_element_that_a_finding_names(element_code):
    sources = anchored_feedback_sources(element_code)
    folder = build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)
    verified = verify_folder(folder.files)
    owner, moment = uuid4(), datetime.now(UTC)
    plan = plan_project_import(
        verified,
        project_id=uuid4(),
        brief_version_id=uuid4(),
        owner_user_id=owner,
        created_at=moment,
    )
    [exported] = json.loads(folder.files["twins/feedback/reviews.json"])["runs"]
    [run] = plan.evaluations
    [before] = exported["responses"][0]["findings"]
    [after] = run.to_snapshot()["responses"][0]["findings"]
    assert (before["anchor_key"], before.get("element_code")) == (ANCHOR, element_code)
    assert (after["anchor_key"], after.get("element_code")) == (ANCHOR, element_code)
    assert set(after) == set(before)
    assert design_evaluation_run_from_snapshot(json.loads(json.dumps(run.to_snapshot()))) == run
    rebuilt = build_why_document(
        project_id=str(plan.project_id),
        stages=plan_documents(plan, owner_user_id=owner, created_at=moment),
        evaluations=[
            {
                "runs": [item.to_snapshot() for item in plan.evaluations],
                "decisions": [item.to_snapshot() for item in plan.finding_decisions],
            }
        ],
    )
    assert normalized_why(
        importable_why(verified, plan.omitted_sections),
        identities=plan.identities,
        hashes=plan.hashes,
    ) == normalized_why(rebuilt)


def planned_record(*, metadata):
    sources = mixed_feedback_sources() if metadata else current_feedback_sources()
    folder = build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)
    owner = uuid4()
    plan = plan_project_import(
        verify_folder(folder.files),
        project_id=uuid4(),
        brief_version_id=uuid4(),
        owner_user_id=owner,
        created_at=PUBLISHED_AT,
    )
    if not metadata:
        plan = replace(plan, import_limits=())
    return import_record(
        plan,
        record_id=uuid4(),
        owner_user_id=owner,
        content=b"anonymous synthetic fixture",
        imported_at=PUBLISHED_AT,
    )


@pytest.mark.parametrize("metadata", [False, True])
def test_import_metadata_roundtrip_preserves_strict_stage_versions_and_legacy_shape(metadata):
    record = planned_record(metadata=metadata)
    stored = _record_values(record)
    assert _import_record(stored) == record
    assert set(record.stage_versions) == set(STAGES)
    assert all(
        set(entry) == {"version_id", "version_number", "content_hash"}
        for entry in record.stage_versions.values()
    )
    if metadata:
        assert stored["stage_versions"]["_import_metadata"]["omitted_sections"]
        assert record.to_snapshot()["omitted_sections"]
    else:
        assert set(stored["stage_versions"]) == set(STAGES)
        assert "omitted_sections" not in record.to_snapshot()
        assert "import_limits" not in record.to_snapshot()


def test_import_metadata_cannot_weaken_the_five_stage_contract():
    record = planned_record(metadata=True)
    stored = _record_values(record)
    stored["stage_versions"]["extra_stage"] = dict(record.stage_versions["brief"])
    with pytest.raises(ValueError, match="every stage"):
        _import_record(stored)
