from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.artifacts import design_evaluation as module
from orchestwin.artifacts.design_evaluation import (
    DesignEvaluationError,
    compare_design_evaluations,
    create_design_evaluation_run,
    design_evaluation_run_from_snapshot,
    evaluation_bundle,
    evaluation_document,
    finding_similarity,
)
from orchestwin.artifacts.prototypes import create_prototype_element, create_prototype_screen
from orchestwin.evaluation.artifact_content import MAX_VIEW_BYTES, prepare_artifact_content
from orchestwin.evaluation.artifacts import EvaluationArtifactKind
from orchestwin.evaluation.evaluator import (
    EvaluationUserTwinProfile,
    FakeSyntheticFindingTemplate,
    FakeUserTwinEvaluator,
    UserTwinEvaluationRequest,
    UserTwinEvaluatorConfiguration,
)
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

from . import design_fixtures

NOW = datetime(2026, 9, 25, 20, 0, tzinfo=UTC)
RUN_ID = UUID("00000000-0000-4000-8000-000000000901")
TWIN_A = UUID("00000000-0000-4000-8000-000000000911")
TWIN_B = UUID("00000000-0000-4000-8000-000000000912")
CONFIGURATION = UserTwinEvaluatorConfiguration(
    evaluator_id="fake-design-evaluator",
    evaluator_version="1",
    model_config_ref="config-1",
    prompt_version_ref="prompt-1",
)


def twin_profile(twin_id: UUID, name: str) -> EvaluationUserTwinProfile:
    snapshot = '{"name": "' + name + '"}'
    return EvaluationUserTwinProfile(
        twin_id=twin_id,
        version_number=1,
        name=name,
        lifecycle_status=next(iter(UserTwinLifecycleStatus)),
        content_hash=hashlib.sha256(snapshot.encode("utf-8")).hexdigest(),
        snapshot_json=snapshot,
    )


def template(
    finding_id: str,
    location: str,
    summary: str,
    criterion=SyntheticFindingCriterion.COMPREHENSIBILITY,
):
    return FakeSyntheticFindingTemplate(
        finding_id=finding_id,
        artifact_kind=EvaluationArtifactKind.DOM_SNAPSHOT,
        location=location,
        summary=summary,
        rationale="Simulated rationale.",
        criterion=criterion,
        severity=SyntheticFindingSeverity.MODERATE,
        epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
        evidence_refs=(f"artifact:{design_fixtures.PROTOTYPE_ID}:v1",),
        confidence=0.6,
        recommended_action="Add a visible label.",
        requires_human_validation=True,
    )


def relocated(finding, location):
    return create_synthetic_finding(
        finding_id=finding.finding_id,
        twin_id=finding.twin_id,
        twin_version=finding.twin_version,
        artifact_id=finding.artifact_id,
        artifact_version=finding.artifact_version,
        location=location,
        summary=finding.summary,
        rationale=finding.rationale,
        criterion=finding.criterion,
        severity=finding.severity,
        epistemic_status=finding.epistemic_status,
        evidence_refs=finding.evidence_refs,
        confidence=finding.confidence,
        recommended_action=finding.recommended_action,
        requires_human_validation=finding.requires_human_validation,
        model_config_ref=finding.model_config_ref,
        prompt_version_ref=finding.prompt_version_ref,
    )


async def evaluate_async(version, templates_by_twin, *, run_id=RUN_ID, clock=NOW):
    document = evaluation_document(version)
    bundle = evaluation_bundle(version, document, locale="it-IT", created_at=clock)
    evaluator = FakeUserTwinEvaluator(
        configuration=CONFIGURATION,
        templates_by_twin=templates_by_twin,
        summaries_by_twin={TWIN_A: "Summary A.", TWIN_B: "Summary B."},
        clock=lambda: clock,
    )
    responses = []
    for twin_id, name in ((TWIN_A, "Ada"), (TWIN_B, "Bruno")):
        request = UserTwinEvaluationRequest(
            evaluation_run_id=run_id,
            project_id=version.project_id,
            workflow_run_id=version.id,
            artifact_bundle=bundle,
            twin=twin_profile(twin_id, name),
            evidence=(),
            requested_at=clock,
        )
        prepared = prepare_artifact_content(
            request,
            selected=((document.reference.artifact_id, document.reference.version_number),),
            read_content=document.read,
        )
        responses.append(await evaluator.evaluate(prepared.request))
    return create_design_evaluation_run(
        run_id=run_id,
        owner_user_id=design_fixtures.OWNER_ID,
        version=version,
        bundle=bundle,
        responses=responses,
        started_at=clock,
        completed_at=clock + timedelta(seconds=5),
    )


def evaluate(version, templates_by_twin, *, run_id=RUN_ID, clock=NOW):
    return asyncio.run(evaluate_async(version, templates_by_twin, run_id=run_id, clock=clock))


def test_evaluation_document_is_a_compact_html_dom_snapshot():
    version = design_fixtures.design_version()
    document = evaluation_document(version)
    text = document.content.decode("utf-8")
    assert len(document.content) <= MAX_VIEW_BYTES
    assert text.startswith("<!doctype html>")
    assert "<style" not in text and "<script" not in text
    assert "Create reservation" in text and 'name="guest_name" required' in text
    assert document.reference.kind is EvaluationArtifactKind.DOM_SNAPSHOT
    assert document.reference.artifact_id == version.package.prototype.id
    assert document.reference.location == "design/mockup.html"
    assert document.read(document.reference.storage_key, MAX_VIEW_BYTES) == document.content
    with pytest.raises(DesignEvaluationError, match="EVALUATION_DOCUMENT_UNAVAILABLE"):
        document.read("sha256/00/" + "0" * 64, MAX_VIEW_BYTES)


def test_evaluation_document_requires_a_selected_prototype_and_bounds_its_size(monkeypatch):
    version = design_fixtures.design_version()
    bare = design_fixtures.design_version(
        package=replace(version.package, owner_selected_alternative_id=None, prototype=None)
    )
    with pytest.raises(DesignEvaluationError, match="DESIGN_PROTOTYPE_REQUIRED"):
        evaluation_document(bare)
    prototype = version.package.prototype
    first = prototype.screens[0]
    long_elements = tuple(
        create_prototype_element(
            element_id=UUID(int=700 + index),
            code=f"ELM-{index + 101:03d}",
            kind=first.elements[0].kind,
            content=("parola " * 500).strip(),
            accessible_name="x" * 3000,
            requirement_ids=first.elements[0].requirement_ids,
            field_name=f"field_{index}",
            required=False,
        )
        for index in range(12)
    )
    screen = create_prototype_screen(
        screen_id=first.id,
        code=first.code,
        title=first.title,
        state=first.state,
        elements=long_elements,
        requirement_ids=first.requirement_ids,
        user_story_ids=first.user_story_ids,
    )
    heavy = design_fixtures.design_version(
        package=replace(
            version.package,
            prototype=replace(prototype, screens=(screen, prototype.screens[1]), transitions=()),
        )
    )
    monkeypatch.setattr(module, "_CONTENT_STEPS", (None,))
    with pytest.raises(DesignEvaluationError, match="EVALUATION_DOCUMENT_TOO_LARGE"):
        evaluation_document(heavy)


def test_evaluation_bundle_describes_the_design_version_and_its_scenario():
    version = design_fixtures.design_version()
    document = evaluation_document(version)
    bundle = evaluation_bundle(version, document, locale="it-IT", created_at=NOW)
    assert bundle.project_id == version.project_id
    assert bundle.workflow_run_id == version.id
    assert [item.kind for item in bundle.artifacts] == [
        EvaluationArtifactKind.DESIGN_SPECIFICATION,
        EvaluationArtifactKind.DOM_SNAPSHOT,
    ]
    assert bundle.scenario.task == "Create a reservation"
    assert bundle.scenario.expected_outcomes == ("Review availability.", "Save the reservation.")
    assert bundle.scenario.name == "Guided reservation flow"
    again = evaluation_bundle(
        version, document, locale="it-IT", created_at=NOW, bundle_id=bundle.id
    )
    assert again.content_hash == bundle.content_hash


def test_evaluation_run_collects_twin_responses_and_round_trips():
    version = design_fixtures.design_version()
    run = evaluate(
        version,
        {
            TWIN_A: (
                template("UTF-001", "SCR-001 Guest name", "The guest name field lacks help text."),
            ),
            TWIN_B: (
                template("UTF-002", "SCR-002 status", "The confirmation hides the next step."),
            ),
        },
    )
    assert run.design_version_id == version.id
    assert run.alternative_code == "DES-001"
    assert [item.twin_id for item in run.responses] == sorted([TWIN_A, TWIN_B], key=str)
    assert len(run.findings) == 2
    assert all(
        f"artifact:{version.package.prototype.id}:v{version.version_number}"
        in finding.evidence_refs
        for finding in run.findings
    )
    snapshot = run.to_snapshot()
    assert snapshot["schema_version"] == 1
    assert design_evaluation_run_from_snapshot(snapshot) == run
    with pytest.raises(ValueError, match=r"hash is inconsistent|not canonical"):
        design_evaluation_run_from_snapshot({**snapshot, "alternative_code": "DES-009"})
    with pytest.raises(ValueError, match="hash is inconsistent"):
        replace(run, alternative_code="DES-002")
    with pytest.raises(ValueError, match="complete after it starts"):
        replace(
            replace(run, completed_at=NOW - timedelta(seconds=1)),
            content_hash=run.content_hash,
        )


def test_comparison_separates_resolved_persisting_and_new_findings():
    version = design_fixtures.design_version()
    base = evaluate(
        version,
        {
            TWIN_A: (
                template("UTF-001", "SCR-001 Guest name", "The guest name field lacks help text."),
                template("UTF-002", "SCR-001 Save", "The save button label is vague."),
            ),
            TWIN_B: (
                template("UTF-003", "SCR-002 status", "The confirmation hides the next step."),
            ),
        },
    )
    head = evaluate(
        version,
        {
            TWIN_A: (
                template(
                    "UTF-001", "SCR-001 guest name", "The guest name field still lacks help text."
                ),
                template("UTF-004", "SCR-001 Dates", "The date fields need a format hint."),
            ),
            TWIN_B: (),
        },
        run_id=UUID("00000000-0000-4000-8000-000000000902"),
        clock=NOW + timedelta(minutes=10),
    )
    comparison = compare_design_evaluations(base, head)
    snapshot = comparison.to_snapshot()
    assert snapshot["counts"] == {
        "base": 3,
        "head": 2,
        "resolved": 2,
        "persisting": 1,
        "introduced": 1,
    }
    assert [item.finding_id for item in comparison.resolved] == ["UTF-002", "UTF-003"]
    assert comparison.persisting[0][0].location == "SCR-001 Guest name"
    assert comparison.introduced[0].finding_id == "UTF-004"
    first, second = base.findings[0], head.findings[0]
    assert finding_similarity(first, second) == 1.0
    assert finding_similarity(first, base.findings[2]) == 0.0
    assert 0.0 < finding_similarity(first, relocated(second, "elsewhere")) < 1.0
