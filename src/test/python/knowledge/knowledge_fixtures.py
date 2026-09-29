from __future__ import annotations

import json
from collections.abc import Mapping
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
from orchestwin.knowledge.folder import file_digests, folder_content_hash, json_text
from orchestwin.knowledge.layout import (
    FEEDBACK_CHANGES,
    FEEDBACK_TEXT,
    KNOWLEDGE_INDEX,
    KNOWLEDGE_MANIFEST,
    SCHEMA_FOLDER,
    STAGES,
    STATE_DOCUMENT,
    STATE_TEXT,
    schema_document,
)
from orchestwin.knowledge.schema import schema_name_for_path
from orchestwin.knowledge.sources import KnowledgeFeedback, KnowledgeSources, knowledge_feedback
from orchestwin.knowledge.stage_documents import stage_versions
from orchestwin.knowledge.state import ProjectStateSources
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


STAGE_GATES = {
    "brief": ("brief", HumanGateType.PROJECT_BRIEF, project_brief_artifact_reference, 1000),
    "team": ("team", HumanGateType.AGENT_TEAM, agent_team_artifact_reference, 2000),
    "twins": ("modeling", HumanGateType.USER_MODELING, user_modeling_artifact_reference, 3000),
    "requirements": (
        "requirements",
        HumanGateType.REQUIREMENTS,
        requirements_artifact_reference,
        4000,
    ),
    "design": ("design", HumanGateType.DESIGN, design_artifact_reference, 5000),
}
ALIGNED_COMMIT = "9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d0e"
PENDING_COMMIT = "4f2a9c1e7b3d5a8f0c6e2b9d1a7f3c5e8b0d2a46"
FIRST_COMMIT = "0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c"
CHANGE_RUN = "00000000-0000-4000-8000-00000000d001"
RECEPTION_TWIN = "e98bf864-69ba-4198-85f9-d4e932c54a3d"
VOLUNTEER_TWIN = "f921405b-21d5-4ef6-b99c-fe0dcb1033b5"
SCHEMA_ID = "urn:orchestwin:knowledge-folder"
OLDER_DOCUMENTS = frozenset({"twin", "reviews", "discussions", "insights"})


def sources_of(versions, *, project_id: UUID, **changes) -> KnowledgeSources:
    values: dict[str, object] = {
        "project_id": project_id,
        "project_name": PROJECT_NAME,
        "feedback": KnowledgeFeedback(),
    }
    for stage, version in versions.items():
        name, gate_type, reference, base = STAGE_GATES[stage]
        values[name] = version
        values[f"{name}_gate"] = approved_gate(version, gate_type, reference(version), base)
    values.update(changes)
    return KnowledgeSources(**values)


def real_sources(**changes) -> KnowledgeSources:
    return sources_of(stage_versions(real_documents()), project_id=REAL_PROJECT_ID, **changes)


def partial_sources(through: str, **changes) -> KnowledgeSources:
    kept = STAGES[: STAGES.index(through) + 1]
    versions = {
        stage: version
        for stage, version in stage_versions(real_documents()).items()
        if stage in kept
    }
    return sources_of(versions, project_id=REAL_PROJECT_ID, **changes)


def change_run() -> dict[str, object]:
    return {
        "id": CHANGE_RUN,
        "commit": PENDING_COMMIT,
        "reviewed_at": "2026-09-28T11:30:00+00:00",
        "locale": "it-IT",
        "reference": {
            "requirements_version_number": 2,
            "design_version_number": 4,
            "alternative_code": "DES-002",
        },
        "critiques": [
            {
                "twin_id": RECEPTION_TWIN,
                "twin_name": "Addetti all'accoglienza",
                "verdict": "CONCERN",
                "summary": "Il messaggio per il nome vuoto compare solo dopo il salvataggio.",
                "findings": [
                    {
                        "severity": "MEDIUM",
                        "text": "Il campo del nome non spiega che cosa manca.",
                        "about": {
                            "requirement": "REQ-003",
                            "screen": "SCR-002",
                            "file": "src/app.js",
                        },
                        "action": "Mostrare il messaggio accanto al campo del nome.",
                    },
                    {
                        "severity": "LOW",
                        "text": "Il pulsante di conferma è piccolo sul tablet.",
                        "about": {"requirement": None, "screen": "SCR-002", "file": None},
                        "action": None,
                    },
                ],
            },
            {
                "twin_id": VOLUNTEER_TWIN,
                "twin_name": "Organizzatori volontari",
                "verdict": "FINE",
                "summary": "La lista si aggiorna subito e resta leggibile.",
                "findings": [
                    {
                        "severity": "LOW",
                        "text": "Il numero progressivo potrebbe essere più evidente.",
                        "about": {"requirement": "REQ-002", "screen": "SCR-001", "file": None},
                        "action": "Rendere il numero in grassetto.",
                    }
                ],
            },
        ],
        "alignment": {
            "status": "CODE_DRIFT",
            "summary": "Il controllo del nome vuoto non segue il requisito REQ-003.",
            "affected": {"requirements": ["REQ-003"], "screens": ["SCR-002"]},
            "design_request": None,
            "requirements_request": None,
            "code_tasks": ["Mostrare il messaggio di errore accanto al campo del nome."],
        },
        "cost_microusd": 650000,
    }


def schema_two_files(files: Mapping[str, str]) -> dict[str, str]:
    dropped = {
        KNOWLEDGE_INDEX,
        KNOWLEDGE_MANIFEST,
        STATE_DOCUMENT,
        STATE_TEXT,
        FEEDBACK_CHANGES,
        schema_document("state"),
        schema_document("changes"),
    }
    older: dict[str, str] = {}
    for path, text in files.items():
        if path in dropped:
            continue
        if path.startswith(f"{SCHEMA_FOLDER}/"):
            text = text.replace(f"{SCHEMA_ID}:3:", f"{SCHEMA_ID}:2:")
        elif path == FEEDBACK_TEXT:
            text = text.split("\n## Critiques on the code changes", 1)[0]
        elif schema_name_for_path(path) in OLDER_DOCUMENTS:
            text = json_text({**json.loads(text), "schema_version": 2})
        older[path] = text
    manifest = json.loads(files[KNOWLEDGE_MANIFEST])
    manifest["schema_version"] = 2
    for key in ("progress", "state"):
        del manifest[key]
    for key in ("changes", "change_reviews"):
        del manifest["feedback"][key]
    for name in ("state", "changes"):
        del manifest["schemas"][name]
    manifest["files"] = file_digests(older)
    manifest["package"]["content_hash"] = folder_content_hash(older)
    return {
        **older,
        KNOWLEDGE_MANIFEST: json_text(manifest),
        KNOWLEDGE_INDEX: files[KNOWLEDGE_INDEX],
    }


def state_sources() -> ProjectStateSources:
    return ProjectStateSources(
        aligned={
            "commit": ALIGNED_COMMIT,
            "decided_at": "2026-09-28T10:00:00+00:00",
            "requirements_version_number": 2,
            "design_version_number": 4,
        },
        changes=(
            {
                "commit": PENDING_COMMIT,
                "parent": ALIGNED_COMMIT,
                "committed_at": "2026-09-28T11:00:00+00:00",
                "author": "Alex Testa",
                "message": "Controllo del nome vuoto\n\nIl messaggio compare dopo il salvataggio.",
                "files": [
                    {"path": "src/app.js", "kind": "MODIFIED", "added": 12, "removed": 3},
                    {"path": "src/messages.js", "kind": "ADDED", "added": 20, "removed": 0},
                ],
                "recorded_at": "2026-09-28T11:05:00+00:00",
                "review": {
                    "run_id": CHANGE_RUN,
                    "reviewed_at": "2026-09-28T11:30:00+00:00",
                    "verdict": "CODE_DRIFT",
                    "summary": "Il controllo del nome vuoto non segue il requisito REQ-003.",
                },
                "decision": {
                    "kind": "CODE_TASKS",
                    "decided_at": "2026-09-28T11:40:00+00:00",
                    "note": None,
                },
            },
            {
                "commit": ALIGNED_COMMIT,
                "parent": FIRST_COMMIT,
                "committed_at": "2026-09-28T09:30:00+00:00",
                "author": None,
                "message": "Prima versione della lista ospiti",
                "files": [{"path": "index.html", "kind": "ADDED", "added": 40, "removed": 0}],
                "recorded_at": "2026-09-28T09:35:00+00:00",
                "review": None,
                "decision": {
                    "kind": "ALIGNED",
                    "decided_at": "2026-09-28T10:00:00+00:00",
                    "note": "Primo punto allineato.",
                },
            },
        ),
        runs=(change_run(),),
        tasks=(
            {
                "code": "TSK-001",
                "text": "Mostrare il messaggio di errore accanto al campo del nome.",
                "about": {"requirements": ["REQ-003"], "screens": ["SCR-002"]},
                "from_commit": PENDING_COMMIT,
                "created_at": "2026-09-28T11:40:00+00:00",
                "status": "OPEN",
            },
        ),
    )
