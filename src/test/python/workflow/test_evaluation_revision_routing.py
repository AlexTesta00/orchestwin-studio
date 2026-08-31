"""Tests for bounded design, implementation, and evaluation revision routing."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from orchestwin.evaluation.aggregation import (
    MultiTwinEvaluationAggregation,
    multi_twin_aggregation_hash,
)
from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.revisions import (
    WorkflowRevisionDecision,
    WorkflowRevisionIssueCode,
    WorkflowRevisionRequest,
    WorkflowRevisionStatus,
    route_workflow_revision,
)
from orchestwin.workflow.routing import WorkflowOperationalLimits
from orchestwin.workflow.runs import (
    WorkflowArtifactReference,
    WorkflowIterationCounters,
    WorkflowRunStatus,
    WorkflowStage,
    create_workflow_run,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000022001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000022002")
RUN_ID = UUID("00000000-0000-4000-8000-000000022003")
EVALUATION_RUN_ID = UUID("00000000-0000-4000-8000-000000022004")
GATE_ID = UUID("00000000-0000-4000-8000-000000022005")
NOW = datetime(2026, 8, 30, 21, 0, tzinfo=UTC)
EVALUATION_HASH = "a" * 64


def _aggregation() -> MultiTwinEvaluationAggregation:
    content_hash = multi_twin_aggregation_hash(
        evaluation_run_id=EVALUATION_RUN_ID,
        evaluation_run_hash=EVALUATION_HASH,
        shared_findings=(),
        role_specific_findings=(),
        direct_conflicts=(),
        unresolved_trade_offs=(),
        evidence_gaps=(),
        human_validation_questions=(),
    )
    return MultiTwinEvaluationAggregation(
        evaluation_run_id=EVALUATION_RUN_ID,
        evaluation_run_hash=EVALUATION_HASH,
        shared_findings=(),
        role_specific_findings=(),
        direct_conflicts=(),
        unresolved_trade_offs=(),
        evidence_gaps=(),
        human_validation_questions=(),
        content_hash=content_hash,
    )


def _run(
    *,
    mode: ProjectMode = ProjectMode.GREENFIELD_GENERATION,
    counters: WorkflowIterationCounters | None = None,
):
    if counters is None:
        counters = WorkflowIterationCounters()
    draft = create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=mode,
        run_id=RUN_ID,
        created_at=NOW,
    )
    return replace(
        draft,
        current_stage=WorkflowStage.REVISION_DECISION,
        status=WorkflowRunStatus.RUNNING,
        artifact_references=(
            WorkflowArtifactReference(
                artifact_type="SYNTHETIC_EVALUATION",
                artifact_id=EVALUATION_RUN_ID,
                version_number=1,
                content_hash=EVALUATION_HASH,
            ),
        ),
        latest_evaluation_run_id=EVALUATION_RUN_ID,
        iteration_counters=counters,
        state_version=7,
        started_at=NOW,
        updated_at=NOW,
    )


def _request(
    decision: WorkflowRevisionDecision,
    **changes,
) -> WorkflowRevisionRequest:
    values = {
        "decision": decision,
        "expected_state_version": 7,
        "aggregation": _aggregation(),
        "occurred_at": NOW + timedelta(seconds=1),
        "failure_signature": None,
        "identical_failure": False,
        "high_impact_gate_id": None,
        "human_reason": None,
    }
    values.update(changes)
    return WorkflowRevisionRequest(**values)


def test_revision_routes_code_design_requirements_architecture_and_final_review() -> None:
    cases = (
        (
            WorkflowRevisionDecision.REPAIR_CODE,
            WorkflowStage.EXECUTION,
            {"failure_signature": "TEST_FAILURE:booking"},
        ),
        (
            WorkflowRevisionDecision.REVISE_DESIGN,
            WorkflowStage.DESIGN_EXPLORATION,
            {},
        ),
        (
            WorkflowRevisionDecision.REVISE_REQUIREMENTS,
            WorkflowStage.REQUIREMENTS,
            {},
        ),
        (
            WorkflowRevisionDecision.REVISE_ARCHITECTURE,
            WorkflowStage.ARCHITECTURE_AND_TEST_PLAN,
            {},
        ),
        (
            WorkflowRevisionDecision.MARK_FINAL_CANDIDATE,
            WorkflowStage.FINAL_REVIEW,
            {},
        ),
    )

    for decision, expected_stage, changes in cases:
        result = route_workflow_revision(_run(), _request(decision, **changes))
        assert result.status is WorkflowRevisionStatus.APPLIED
        assert result.run.current_stage is expected_stage
        assert result.run.status is WorkflowRunStatus.RUNNING
        assert result.run.state_version > 7

    brownfield = route_workflow_revision(
        _run(mode=ProjectMode.BROWNFIELD_ASSESSMENT),
        _request(WorkflowRevisionDecision.REVISE_DESIGN),
    )
    assert brownfield.run.current_stage is WorkflowStage.PATCH_PLANNING


def test_operational_limit_pauses_instead_of_manufacturing_a_route() -> None:
    run = _run(counters=WorkflowIterationCounters(design_cycle_count=1))
    result = route_workflow_revision(
        run,
        _request(WorkflowRevisionDecision.REVISE_DESIGN),
        limits=WorkflowOperationalLimits(design_cycles=1),
    )

    assert result.status is WorkflowRevisionStatus.PAUSED_NEEDS_HUMAN
    assert result.run.status is WorkflowRunStatus.PAUSED_NEEDS_HUMAN
    assert result.run.current_stage is WorkflowStage.REVISION_DECISION
    assert result.run.blocking_issues[0].code == "DESIGN_CYCLE_LIMIT"


def test_high_impact_and_human_routes_remain_explicit() -> None:
    missing_gate = route_workflow_revision(
        _run(),
        _request(WorkflowRevisionDecision.REQUEST_HIGH_IMPACT_APPROVAL),
    )
    assert missing_gate.issue is WorkflowRevisionIssueCode.HIGH_IMPACT_GATE_REQUIRED

    waiting = route_workflow_revision(
        _run(),
        _request(
            WorkflowRevisionDecision.REQUEST_HIGH_IMPACT_APPROVAL,
            high_impact_gate_id=GATE_ID,
        ),
    )
    assert waiting.status is WorkflowRevisionStatus.APPLIED
    assert waiting.run.status is WorkflowRunStatus.WAITING_FOR_HUMAN
    assert waiting.run.pending_gate_id == GATE_ID

    paused = route_workflow_revision(
        _run(),
        _request(
            WorkflowRevisionDecision.REQUEST_HUMAN_DECISION,
            human_reason="The conflicting User Twin recommendations require owner direction.",
        ),
    )
    assert paused.status is WorkflowRevisionStatus.PAUSED_NEEDS_HUMAN
    assert paused.run.blocking_issues[0].source.value == "HUMAN_DECISION"


def test_stale_state_or_evaluation_scope_is_rejected_without_mutation() -> None:
    run = _run()
    stale = route_workflow_revision(
        run,
        _request(
            WorkflowRevisionDecision.MARK_FINAL_CANDIDATE,
            expected_state_version=6,
        ),
    )
    assert stale.status is WorkflowRevisionStatus.REJECTED
    assert stale.issue is WorkflowRevisionIssueCode.STATE_VERSION_CONFLICT
    assert stale.run == run

    mismatched = replace(run, latest_evaluation_run_id=UUID(int=22999))
    wrong_evaluation = route_workflow_revision(
        mismatched,
        _request(WorkflowRevisionDecision.MARK_FINAL_CANDIDATE),
    )
    assert wrong_evaluation.issue is WorkflowRevisionIssueCode.EVALUATION_SCOPE_MISMATCH
    assert wrong_evaluation.run == mismatched
