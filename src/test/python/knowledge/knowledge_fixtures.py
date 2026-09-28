from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from orchestwin.agents.team_gate import agent_team_artifact_reference
from orchestwin.artifacts.design_discussion import DiscussionStatus
from orchestwin.artifacts.design_finding_validations import (
    FindingDecision,
    create_finding_validation,
)
from orchestwin.artifacts.design_gate import design_artifact_reference
from orchestwin.knowledge.layout import STAGES
from orchestwin.knowledge.sources import KnowledgeFeedback, KnowledgeSources, knowledge_feedback
from orchestwin.knowledge.stage_documents import stage_versions
from orchestwin.projects.brief_gate import project_brief_artifact_reference
from orchestwin.projects.requirements_gate import requirements_artifact_reference
from orchestwin.twins.user_modeling_gate import user_modeling_artifact_reference
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)
from src.test.python.artifacts.design_fixtures import (
    OWNER_ID,
    PROJECT_ID,
    design_version,
    requirements_version,
)
from src.test.python.artifacts.test_design_discussion import (
    discussion,
    discussion_round,
    reacting_round,
)
from src.test.python.artifacts.test_design_evaluation import TWIN_A, TWIN_B, evaluate, template
from src.test.python.projects.test_insight_applications import application
from src.test.python.twins.test_user_modeling_gate import snapshot_version
from src.test.python.workflow.test_governed_project_setup import build_ready_project

NOW = datetime(2026, 9, 27, 18, 0, tzinfo=UTC)
PUBLISHED_AT = datetime(2026, 9, 27, 20, 0, tzinfo=UTC)
PROJECT_NAME = "Lista ospiti workshop"
RUN_ONE = UUID("00000000-0000-4000-8000-000000000901")
RUN_TWO = UUID("00000000-0000-4000-8000-000000000902")
REAL_PROJECT_ID = UUID("0eacaaec-d4e5-4357-b670-dc7fd5005542")
REAL_PROJECT_DATA = Path(__file__).parent / "data" / "guest_list"


def approved_gate(version, gate_type: HumanGateType, reference, base: int) -> HumanGate:
    draft = create_human_gate(
        gate_id=UUID(int=base),
        project_id=version.project_id,
        owner_user_id=OWNER_ID,
        gate_type=gate_type,
        artifact=reference,
        created_at=NOW,
    )
    submitted = transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=NOW + timedelta(minutes=1),
        event_id=UUID(int=base + 1),
    )
    approved = transition_human_gate(
        submitted.gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=NOW + timedelta(minutes=2),
        event_id=UUID(int=base + 2),
    )
    return approved.gate


def evaluation_runs():
    design = design_version()
    first = evaluate(
        design,
        {
            TWIN_A: (
                template("UTF-001", "SCR-001 Guest name", "The field lacks help."),
                template("UTF-002", "SCR-001 Save", "The action is unclear."),
            ),
            TWIN_B: (template("UTF-001", "SCR-001 Save", "The button is small."),),
        },
        run_id=RUN_ONE,
        clock=NOW,
    )
    second = evaluate(
        design,
        {TWIN_A: (template("UTF-001", "SCR-001 Guest name", "The label is short."),)},
        run_id=RUN_TWO,
        clock=NOW + timedelta(hours=1),
    )
    return first, second


def validations():
    common = {"project_id": PROJECT_ID, "owner_user_id": OWNER_ID}
    return (
        create_finding_validation(
            evaluation_run_id=RUN_ONE,
            twin_id=TWIN_A,
            finding_id="UTF-001",
            sequence_number=1,
            decision=FindingDecision.OWNER_DISMISSED,
            note="Not relevant",
            decided_at=NOW + timedelta(minutes=10),
            **common,
        ),
        create_finding_validation(
            evaluation_run_id=RUN_ONE,
            twin_id=TWIN_A,
            finding_id="UTF-001",
            sequence_number=2,
            decision=FindingDecision.OWNER_CONFIRMED,
            note=None,
            decided_at=NOW + timedelta(minutes=20),
            **common,
        ),
        create_finding_validation(
            evaluation_run_id=RUN_ONE,
            twin_id=TWIN_B,
            finding_id="UTF-001",
            sequence_number=1,
            decision=FindingDecision.OWNER_DISMISSED,
            note=None,
            decided_at=NOW + timedelta(minutes=30),
            **common,
        ),
    )


def discussions():
    design = design_version()
    shared = {
        "project_id": PROJECT_ID,
        "owner_user_id": OWNER_ID,
        "design_version_id": design.id,
        "design_version_number": design.version_number,
        "design_content_hash": design.content_hash,
    }
    approved = discussion(
        id=UUID(int=7001),
        rounds=(
            discussion_round(note="Concentratevi sul compito principale."),
            reacting_round(),
        ),
        **shared,
    )
    approved = approved.decided(
        DiscussionStatus.APPROVED, approved.rounds[-1].created_at + timedelta(minutes=5)
    )
    closed = discussion(id=UUID(int=7002), **shared)
    closed = closed.decided(
        DiscussionStatus.CLOSED, closed.rounds[-1].created_at + timedelta(minutes=5)
    )
    return approved, closed, discussion(id=UUID(int=7003), **shared)


def applications():
    return (
        application(
            application_id=UUID(int=8001),
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            source_twin_id=TWIN_A,
        ),
    )


def feedback() -> KnowledgeFeedback:
    return knowledge_feedback(
        runs=reversed(evaluation_runs()),
        validations=validations(),
        discussions=discussions(),
        applications=applications(),
    )


def sources(*, with_feedback: bool = True, **changes) -> KnowledgeSources:
    scenario = build_ready_project()
    modeling = snapshot_version()
    requirements = requirements_version()
    design = design_version()
    values = {
        "project_id": PROJECT_ID,
        "project_name": PROJECT_NAME,
        "brief": scenario.brief_version,
        "brief_gate": approved_gate(
            scenario.brief_version,
            HumanGateType.PROJECT_BRIEF,
            project_brief_artifact_reference(scenario.brief_version),
            1000,
        ),
        "team": scenario.team_version,
        "team_gate": approved_gate(
            scenario.team_version,
            HumanGateType.AGENT_TEAM,
            agent_team_artifact_reference(scenario.team_version),
            2000,
        ),
        "modeling": modeling,
        "modeling_gate": approved_gate(
            modeling,
            HumanGateType.USER_MODELING,
            user_modeling_artifact_reference(modeling),
            3000,
        ),
        "requirements": requirements,
        "requirements_gate": approved_gate(
            requirements,
            HumanGateType.REQUIREMENTS,
            requirements_artifact_reference(requirements),
            4000,
        ),
        "design": design,
        "design_gate": approved_gate(
            design, HumanGateType.DESIGN, design_artifact_reference(design), 5000
        ),
        "feedback": feedback() if with_feedback else KnowledgeFeedback(),
    }
    values.update(changes)
    return KnowledgeSources(**values)


def real_documents() -> dict[str, dict[str, object]]:
    return {
        stage: json.loads((REAL_PROJECT_DATA / f"{stage}.json").read_text(encoding="utf-8"))
        for stage in STAGES
    }


def sources_of(versions, *, project_id: UUID, **changes) -> KnowledgeSources:
    values = {
        "project_id": project_id,
        "project_name": PROJECT_NAME,
        "brief": versions["brief"],
        "brief_gate": approved_gate(
            versions["brief"],
            HumanGateType.PROJECT_BRIEF,
            project_brief_artifact_reference(versions["brief"]),
            1000,
        ),
        "team": versions["team"],
        "team_gate": approved_gate(
            versions["team"],
            HumanGateType.AGENT_TEAM,
            agent_team_artifact_reference(versions["team"]),
            2000,
        ),
        "modeling": versions["twins"],
        "modeling_gate": approved_gate(
            versions["twins"],
            HumanGateType.USER_MODELING,
            user_modeling_artifact_reference(versions["twins"]),
            3000,
        ),
        "requirements": versions["requirements"],
        "requirements_gate": approved_gate(
            versions["requirements"],
            HumanGateType.REQUIREMENTS,
            requirements_artifact_reference(versions["requirements"]),
            4000,
        ),
        "design": versions["design"],
        "design_gate": approved_gate(
            versions["design"],
            HumanGateType.DESIGN,
            design_artifact_reference(versions["design"]),
            5000,
        ),
        "feedback": KnowledgeFeedback(),
    }
    values.update(changes)
    return KnowledgeSources(**values)


def real_sources(**changes) -> KnowledgeSources:
    return sources_of(stage_versions(real_documents()), project_id=REAL_PROJECT_ID, **changes)
