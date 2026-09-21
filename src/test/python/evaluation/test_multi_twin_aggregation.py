"""Tests for deterministic multi-twin aggregation without forced consensus."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.evaluation.aggregation import (
    MULTI_TWIN_AGGREGATION_DISCLAIMER,
    DeclaredFindingConflict,
    aggregate_synthetic_evaluation,
    finding_reference,
)
from orchestwin.evaluation.application import (
    SyntheticEvaluationRun,
    SyntheticEvaluationRunStatus,
    synthetic_evaluation_run_hash,
)
from orchestwin.evaluation.evaluator import (
    UserTwinEvaluationResponse,
    UserTwinEvaluatorConfiguration,
    user_twin_evaluation_response_hash,
)
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000021001")
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000021002")
EVALUATION_RUN_ID = UUID("00000000-0000-4000-8000-000000021003")
BUNDLE_ID = UUID("00000000-0000-4000-8000-000000021004")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000021005")
OWNER_ID = UUID("00000000-0000-4000-8000-000000021006")
TWIN_A = UUID("00000000-0000-4000-8000-000000021010")
TWIN_B = UUID("00000000-0000-4000-8000-000000021011")
NOW = datetime(2026, 8, 30, 20, 0, tzinfo=UTC)
CONFIGURATION = UserTwinEvaluatorConfiguration(
    evaluator_id="fake.user-twin-evaluator",
    evaluator_version="1.0.0",
    model_config_ref="fake-model-v1",
    prompt_version_ref="ut-eval-v1",
)


def _finding(
    finding_id: str,
    twin_id: UUID,
    *,
    summary: str,
    action: str,
    location: str = "screen:booking/action:confirm",
) -> object:
    return create_synthetic_finding(
        finding_id=finding_id,
        twin_id=twin_id,
        twin_version=1,
        artifact_id=ARTIFACT_ID,
        artifact_version=2,
        location=location,
        summary=summary,
        rationale="The approved role requires an actionable primary task.",
        criterion=SyntheticFindingCriterion.ACTIONABILITY,
        severity=SyntheticFindingSeverity.MAJOR,
        epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
        evidence_refs=("REQ-BOOKING-1",),
        confidence=0.7,
        recommended_action=action,
        requires_human_validation=True,
        model_config_ref="fake-model-v1",
        prompt_version_ref="ut-eval-v1",
    )


def _response(
    twin_id: UUID,
    findings: tuple,
    *,
    evidence_gaps: tuple[str, ...] = (),
) -> UserTwinEvaluationResponse:
    ordered_findings = tuple(sorted(findings, key=lambda item: item.finding_id))
    summary = f"Twin {twin_id.int} produced simulated feedback."
    ordered_gaps = tuple(sorted(evidence_gaps))
    return UserTwinEvaluationResponse(
        evaluation_run_id=EVALUATION_RUN_ID,
        artifact_bundle_id=BUNDLE_ID,
        artifact_bundle_hash="a" * 64,
        twin_id=twin_id,
        twin_version=1,
        evaluator=CONFIGURATION,
        findings=ordered_findings,
        summary=summary,
        evidence_gaps=ordered_gaps,
        completed_at=NOW,
        content_hash=user_twin_evaluation_response_hash(
            evaluation_run_id=EVALUATION_RUN_ID,
            artifact_bundle_id=BUNDLE_ID,
            artifact_bundle_hash="a" * 64,
            twin_id=twin_id,
            twin_version=1,
            evaluator=CONFIGURATION,
            findings=ordered_findings,
            summary=summary,
            evidence_gaps=ordered_gaps,
        ),
    )


def _run(responses: tuple[UserTwinEvaluationResponse, ...]) -> SyntheticEvaluationRun:
    ordered = tuple(sorted(responses, key=lambda item: item.twin_id.hex))
    return SyntheticEvaluationRun(
        id=EVALUATION_RUN_ID,
        project_id=PROJECT_ID,
        workflow_run_id=WORKFLOW_RUN_ID,
        owner_user_id=OWNER_ID,
        artifact_bundle_id=BUNDLE_ID,
        artifact_bundle_hash="a" * 64,
        evaluator=CONFIGURATION,
        status=SyntheticEvaluationRunStatus.COMPLETED,
        twin_evaluations=ordered,
        started_at=NOW,
        completed_at=NOW,
        content_hash=synthetic_evaluation_run_hash(
            run_id=EVALUATION_RUN_ID,
            project_id=PROJECT_ID,
            workflow_run_id=WORKFLOW_RUN_ID,
            owner_user_id=OWNER_ID,
            artifact_bundle_id=BUNDLE_ID,
            artifact_bundle_hash="a" * 64,
            evaluator=CONFIGURATION,
            status=SyntheticEvaluationRunStatus.COMPLETED,
            twin_evaluations=ordered,
        ),
    )


def test_aggregation_separates_shared_role_specific_and_explicit_conflicts() -> None:
    shared_summary = "The confirmation action is unclear under time pressure."
    shared_a = _finding(
        "UTF-211",
        TWIN_A,
        summary=shared_summary,
        action="Use an explicit confirmation label.",
    )
    shared_b = _finding(
        "UTF-212",
        TWIN_B,
        summary=shared_summary,
        action="Use an explicit confirmation label.",
    )
    role_specific = _finding(
        "UTF-213",
        TWIN_A,
        summary="The summary omits the assigned room.",
        action="Show the assigned room before confirmation.",
        location="screen:booking/summary",
    )
    conflict_a = _finding(
        "UTF-214",
        TWIN_A,
        summary="The primary action should remain immediately available.",
        action="Keep the action visible without another confirmation step.",
    )
    conflict_b = _finding(
        "UTF-215",
        TWIN_B,
        summary="The irreversible action needs an explicit safeguard.",
        action="Add a confirmation step before the reservation is committed.",
    )
    run = _run(
        (
            _response(TWIN_A, (shared_a, role_specific, conflict_a)),
            _response(
                TWIN_B,
                (shared_b, conflict_b),
                evidence_gaps=("No empirical time-on-task evidence is available.",),
            ),
        )
    )
    declaration = DeclaredFindingConflict(
        conflict_id="CONFLICT-BOOKING-CONFIRMATION",
        left_finding_id="UTF-214",
        right_finding_id="UTF-215",
        summary="Speed and error prevention imply different confirmation behavior.",
        owner_decision_question=(
            "Which confirmation behavior should be validated with receptionists?"
        ),
    )

    result = aggregate_synthetic_evaluation(run, declared_conflicts=(declaration,))

    assert result.shared_findings[0].finding_ids == ("UTF-211", "UTF-212")
    assert result.role_specific_findings[0].finding.finding_id == "UTF-213"
    assert result.direct_conflicts[0].declaration == declaration
    assert [item.finding_id for item in result.direct_conflicts[0].findings] == [
        "UTF-214",
        "UTF-215",
    ]
    assert result.evidence_gaps[0].twin_id == TWIN_B
    assert result.unresolved_trade_offs == (
        "CONFLICT-BOOKING-CONFIRMATION: Speed and error prevention imply different "
        "confirmation behavior.",
    )
    assert result.disclaimer == MULTI_TWIN_AGGREGATION_DISCLAIMER
    assert result.to_snapshot()["independent_human_sample_count"] == 0
    assert result.to_snapshot()["is_empirical_evidence"] is False


def test_aggregation_is_deterministic_and_generates_human_validation_questions() -> None:
    finding_a = _finding(
        "UTF-216",
        TWIN_A,
        summary="The confirmation action is unclear.",
        action="Use an explicit label.",
    )
    finding_b = _finding(
        "UTF-217",
        TWIN_B,
        summary="The confirmation action is unclear.",
        action="Use an explicit label.",
    )
    run = _run((_response(TWIN_A, (finding_a,)), _response(TWIN_B, (finding_b,))))

    first = aggregate_synthetic_evaluation(run)
    second = aggregate_synthetic_evaluation(run)

    assert first == second
    assert first.content_hash == second.content_hash
    assert [question.related_finding_ids for question in first.human_validation_questions] == [
        ("UTF-216",),
        ("UTF-217",),
    ]


def test_aggregation_rejects_unknown_or_same_twin_conflict_declarations() -> None:
    finding_a = _finding(
        "UTF-218",
        TWIN_A,
        summary="The action needs a concise label.",
        action="Use a shorter label.",
    )
    finding_b = _finding(
        "UTF-219",
        TWIN_A,
        summary="The action needs a concise label.",
        action="Use a longer explanatory label.",
    )
    run = _run((_response(TWIN_A, (finding_a, finding_b)),))

    unknown = DeclaredFindingConflict(
        conflict_id="CONFLICT-UNKNOWN",
        left_finding_id="UTF-218",
        right_finding_id="UTF-999",
        summary="One side is not part of the evaluation run.",
        owner_decision_question="Should this conflict be considered?",
    )
    with pytest.raises(ValueError, match="unknown finding"):
        aggregate_synthetic_evaluation(run, declared_conflicts=(unknown,))

    same_twin = DeclaredFindingConflict(
        conflict_id="CONFLICT-SAME-TWIN",
        left_finding_id="UTF-218",
        right_finding_id="UTF-219",
        summary="Two outputs from the same twin disagree.",
        owner_decision_question="Which output should be retained?",
    )
    with pytest.raises(ValueError, match="different User Twins"):
        aggregate_synthetic_evaluation(run, declared_conflicts=(same_twin,))


def test_independent_twins_may_reuse_local_ids_without_losing_findings():
    shared_a = _finding("UTF-001", TWIN_A, summary="Shared observation.", action="Check it.")
    separate_b = _finding(
        "UTF-001", TWIN_B, summary="Different role observation.", action="Review it."
    )
    shared_b = _finding("UTF-002", TWIN_B, summary="Shared observation.", action="Check it.")
    run = _run((_response(TWIN_A, (shared_a,)), _response(TWIN_B, (separate_b, shared_b))))
    before = run.to_snapshot()
    result = aggregate_synthetic_evaluation(run)
    assert result.shared_findings[0].findings == (shared_a, shared_b)
    assert result.role_specific_findings[0].finding == separate_b
    related = {
        ref
        for question in result.human_validation_questions
        for ref in question.related_finding_ids
    }
    assert related == {finding_reference(shared_a), finding_reference(separate_b), "UTF-002"}
    assert run.to_snapshot() == before


def test_conflicts_can_reference_two_independent_findings_with_the_same_local_id():
    left = _finding("UTF-001", TWIN_A, summary="Action needs a label.", action="Shorten it.")
    right = _finding("UTF-001", TWIN_B, summary="Action needs a label.", action="Explain it.")
    run = _run((_response(TWIN_A, (left,)), _response(TWIN_B, (right,))))
    refs = sorted((finding_reference(left), finding_reference(right)))
    declaration = DeclaredFindingConflict(
        "C-1", *refs, "Different recommendations.", "Which label supports the task?"
    )
    result = aggregate_synthetic_evaluation(run, declared_conflicts=(declaration,))
    assert len(result.direct_conflicts) == 1
    assert not result.shared_findings and not result.role_specific_findings
    assert result.human_validation_questions[0].related_finding_ids == tuple(refs)
    ambiguous = DeclaredFindingConflict(
        "C-2", "UTF-001", refs[0], "Ambiguous reference.", "Which finding is intended?"
    )
    with pytest.raises(ValueError, match="ambiguous local ID"):
        aggregate_synthetic_evaluation(run, declared_conflicts=(ambiguous,))
