from __future__ import annotations

from pathlib import Path

import pytest

from orchestwin.agents.catalog import all_agent_catalog_entries
from orchestwin.agents.perspectives import (
    ASPECT_AGENT_IDS,
    ASPECT_ORDER,
    PERSPECTIVE_AGENT_IDS,
    PERSPECTIVE_ORDER,
    PerspectiveStanding,
)
from orchestwin.agents.team_gate import TeamEditIssueCode
from orchestwin.cli.api import brief, modeling, requirements, team
from orchestwin.cli.client import StudioClient
from orchestwin.cli.commands import init as init_command
from orchestwin.cli.commands.init import Journey, code_of
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows import init_requirements
from orchestwin.cli.messages import known
from orchestwin.projects import brief_dialogue
from orchestwin.projects.briefs import LIST_FIELDS, TEXT_FIELDS, BriefField
from orchestwin.projects.requirements import RequirementKind, RequirementPriority
from orchestwin.projects.requirements_quality import VerificationMethod
from orchestwin.projects.requirements_revisions import (
    RequirementsArtifactKind,
    RequirementsDiffOperationKind,
)

from .support.terminal import PROJECT_ID, command_context, link_folder, store_session, terminal
from .support.transports import API, ScriptedTransport

BASE = f"{API}/projects/{PROJECT_ID}"


def client(tmp_path: Path, transport: ScriptedTransport) -> StudioClient:
    store_session(tmp_path)
    bundle = terminal(tmp_path, transport=transport)
    return command_context(bundle.environment).client()


def journey(tmp_path: Path, transport: ScriptedTransport, *, language: str = "en") -> Journey:
    store_session(tmp_path)
    folder = link_folder(tmp_path / "project")
    bundle = terminal(tmp_path, transport=transport)
    context = command_context(bundle.environment, language=language)
    return Journey(context, context.client(), folder, script=None, until=None, idea=None)


def test_the_brief_constants_follow_the_domain() -> None:
    assert tuple(field.value for field in BriefField) == brief.FIELDS
    assert {field.value for field in TEXT_FIELDS} == brief.TEXT_FIELDS
    assert {field.value for field in LIST_FIELDS} == brief.LIST_FIELDS
    assert tuple(field.value for field in brief_dialogue.ESSENTIAL_FIELDS) == brief.ESSENTIAL_FIELDS
    assert brief.QUESTION_LIMIT == brief_dialogue.MAX_DIALOGUE_QUESTIONS
    assert brief.MAX_STATEMENT == brief_dialogue.MAX_STATEMENT_CHARACTERS
    assert brief.MAX_ANSWER == brief_dialogue.MAX_ANSWER_CHARACTERS
    assert brief.MAX_ITEM == brief_dialogue.MAX_ANSWER_ITEM_CHARACTERS
    assert brief.MAX_ITEMS == brief_dialogue.MAX_ANSWER_ITEMS


def test_the_team_constants_follow_the_catalog() -> None:
    entries = all_agent_catalog_entries()
    assert tuple(entry.agent_id.value for entry in entries) == team.AGENTS
    assert tuple(code.value for code in TeamEditIssueCode) == team.EDIT_ISSUES
    platform = {entry.agent_id.value for entry in entries if entry.is_always_present}
    assert platform.isdisjoint(agent for agents in team.UNIT_AGENTS.values() for agent in agents)


def test_the_perspective_constants_follow_the_domain() -> None:
    assert tuple(item.value for item in PERSPECTIVE_ORDER) == team.PERSPECTIVES
    assert tuple(item.value for item in ASPECT_ORDER) == team.ASPECTS
    assert tuple(item.value for item in PerspectiveStanding) == team.STANDINGS
    units = {
        key.value: tuple(agent.value for agent in agents)
        for key, agents in PERSPECTIVE_AGENT_IDS.items()
    }
    units.update({key.value: (agent.value,) for key, agent in ASPECT_AGENT_IDS.items()})
    assert units == dict(team.UNIT_AGENTS)
    assert list(team.UNIT_AGENTS) == [*team.PERSPECTIVES, *team.ASPECTS]
    named = (team.REQUIRED, team.OPTIONAL, team.EXCLUDED, team.CONTESTED)
    assert named == team.STANDINGS[1:]
    assert team.DESIGNER in team.UNIT_AGENTS["UX"]


def test_the_requirements_constants_follow_the_domain() -> None:
    assert tuple(item.value for item in RequirementPriority) == requirements.PRIORITIES
    assert tuple(item.value for item in RequirementKind) == requirements.KINDS
    assert tuple(item.value for item in RequirementsArtifactKind) == requirements.ARTIFACT_KINDS
    assert tuple(item.value for item in RequirementsDiffOperationKind) == requirements.OPERATIONS
    assert tuple(item.value for item in VerificationMethod) == init_requirements.VERIFICATIONS


def test_every_key_built_at_run_time_exists() -> None:
    keys = [
        *(f"init.field_{field}" for field in brief.FIELDS),
        *(f"init.question_{field}" for field in ("problem", "target_users", "goals")),
        "init.question_functional_requirements",
        *(f"init.perspective_{key.lower()}" for key in team.PERSPECTIVES),
        *(f"init.perspective_{key.lower()}_line" for key in team.PERSPECTIVES),
        *(f"init.aspect_{key.lower()}" for key in team.ASPECTS),
        *(f"init.aspect_{key.lower()}_line" for key in team.ASPECTS),
        *(f"init.standing_{standing.lower()}" for standing in team.STANDINGS),
        "init.standing_optional_applied",
        *(f"init.team_issue_{code.lower()}" for code in team.EDIT_ISSUES),
        *(f"init.priority_{item.lower()}" for item in requirements.PRIORITIES),
        *(f"init.kind_{item.lower()}" for item in requirements.KINDS),
        *(f"init.artifact_{item.lower()}" for item in requirements.ARTIFACT_KINDS),
        *(f"init.change_{item.lower()}" for item in requirements.OPERATIONS),
        *(f"init.verify_{item.lower()}" for item in init_requirements.VERIFICATIONS),
        *(f"common.stage_{stage}" for stage in init_command.STAGES),
        *init_command.MODE_KEYS.values(),
        *(
            f"init.errors.GENERATION_BUDGET_EXCEEDED.{reason}"
            for reason in ("total", "project", "generation")
        ),
        *(
            f"init.errors.ANSWERS_FILE_INVALID.{reason}"
            for reason in (
                "unreadable",
                "not_json",
                "not_object",
                "unknown_key",
                "choice",
                "text",
                "texts",
                "object",
                "missing",
            )
        ),
        "init.errors.SPENDING_REFUSED.answers",
        "init.errors.TOO_MANY_GENERATIONS",
    ]

    assert [key for key in keys if not known(key)] == []


def test_the_brief_calls_send_the_bodies_of_the_studio(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    for path in (
        "brief-dialogue",
        "brief-dialogue/answers",
        "brief-dialogue/questions",
        "brief-dialogue/synthesis",
        "brief-dialogue/close",
        "brief-assumptions/accept-all",
        "brief-assumptions/a-1/accept",
        "brief-assumptions/a-2/reject",
        "gates/project-brief/submit",
        "gates/project-brief/decisions",
    ):
        transport.expect("POST", f"{BASE}/{path}", status=201, body={"status": "OK"})
    studio = client(tmp_path, transport)

    assert brief.start(studio, PROJECT_ID, "Idea") == (201, {"status": "OK"})
    brief.answer(studio, PROJECT_ID, brief.list_answer(["A", "B"]), 2)
    brief.ask_next(studio, PROJECT_ID, 3)
    brief.synthesize(studio, PROJECT_ID, 4)
    brief.close(studio, PROJECT_ID, 5)
    brief.accept_all(studio, PROJECT_ID)
    brief.accept(studio, PROJECT_ID, "a-1")
    brief.reject(studio, PROJECT_ID, "a-2", "No")
    brief.submit_gate(studio, PROJECT_ID)
    brief.decide_gate(studio, PROJECT_ID)

    assert [request.json() for request in transport.sent] == [
        {"statement": "Idea"},
        {"kind": "ITEM_LIST", "items": ["A", "B"], "expected_turn_count": 2},
        {"expected_turn_count": 3},
        {"expected_turn_count": 4},
        {"expected_turn_count": 5},
        {},
        {},
        {"reason": "No"},
        None,
        {"action": "APPROVE"},
    ]
    transport.assert_done()


def test_reads_of_the_brief_answer_none_when_the_studio_has_nothing(tmp_path: Path) -> None:
    missing = {"detail": "project_not_found"}
    transport = (
        ScriptedTransport()
        .expect("GET", f"{BASE}/brief-versions/current", status=404, body=missing)
        .expect("GET", f"{BASE}/brief-dialogue", status=404, body={"detail": {"code": "X"}})
        .expect("GET", f"{BASE}/gates/project-brief/current", status=404, body=missing)
        .expect("GET", f"{BASE}/brief-assumptions", body=[{"id": "a", "status": "PROPOSED"}, 3])
    )
    studio = client(tmp_path, transport)

    assert brief.current(studio, PROJECT_ID) is None
    assert brief.dialogue(studio, PROJECT_ID) is None
    assert brief.gate(studio, PROJECT_ID) is None
    assert brief.assumptions(studio, PROJECT_ID) == [{"id": "a", "status": "PROPOSED"}]
    transport.assert_done()


def test_the_request_body_keeps_the_brief_and_applies_the_changes() -> None:
    content = {
        "name": "Mancia",
        "description": "Idea",
        "goals": ["A"],
        "domain": None,
        "unknown_fields": ["domain", "budget"],
        "provided_fields": ["name", "description", "goals"],
        "missing_fields": [],
    }

    body = brief.request_body(content, {"domain": "Bar", "goals": ("B", "C")}, ["name"])

    assert list(body) == [*brief.FIELDS, "unknown_fields"]
    assert (body["domain"], body["goals"], body["name"]) == ("Bar", ["B", "C"], None)
    assert body["description"] == "Idea"
    assert body["unknown_fields"] == ["budget", "name"]


def test_the_open_essential_points_count_the_pending_question() -> None:
    state = {
        "snapshot": {"essential_fields": ["description", "problem", "goals"], "turns": []},
        "progress": {"open_essential_fields": ["goals"]},
    }

    assert brief.open_essential(state) == ["goals"]
    assert brief.open_essential(state, {"field": "problem"}) == ["goals", "problem"]
    assert brief.open_essential(state, {"field": "domain"}) == ["goals"]
    assert brief.open_essential(state, {"field": None}) == ["goals"]


def test_the_team_edit_sends_the_whole_selection_in_catalog_order(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect(
        "PATCH", f"{BASE}/team-proposals/current", status=201, body={"status": "UPDATED"}
    )
    studio = client(tmp_path, transport)

    team.edit(
        studio,
        PROJECT_ID,
        ["QA_TEST_ENGINEER", "WORKFLOW_ORCHESTRATOR", "MOBILE_ENGINEER", "QA_TEST_ENGINEER"],
    )

    assert transport.sent[0].json() == {
        "selected_agent_ids": ["WORKFLOW_ORCHESTRATOR", "MOBILE_ENGINEER", "QA_TEST_ENGINEER"],
    }
    transport.assert_done()


def test_a_unit_is_switched_by_adding_or_removing_its_agent() -> None:
    chosen = ["WORKFLOW_ORCHESTRATOR", "SOFTWARE_ARCHITECT", "QA_TEST_ENGINEER", "LATER_AGENT"]

    assert team.switched(chosen, "SECURITY_REVIEWER") == [
        "WORKFLOW_ORCHESTRATOR",
        "SOFTWARE_ARCHITECT",
        "QA_TEST_ENGINEER",
        "SECURITY_REVIEWER",
        "LATER_AGENT",
    ]
    assert team.switched(chosen, "QA_TEST_ENGINEER") == [
        "WORKFLOW_ORCHESTRATOR",
        "SOFTWARE_ARCHITECT",
        "LATER_AGENT",
    ]
    assert [team.unit_of(agent) for agent in ("UX_UI_DESIGNER", "BACKEND_ENGINEER")] == [
        "UX",
        "SERVICES",
    ]
    assert team.unit_of("TEAM_SELECTOR") is None


def test_the_team_reads_are_tolerant(tmp_path: Path) -> None:
    transport = (
        ScriptedTransport()
        .expect("GET", f"{BASE}/team-proposals/current", status=404, body={"detail": "x"})
        .expect("GET", f"{BASE}/readiness", body={"status": "TEAM_PROPOSAL_REQUIRED"})
        .expect("GET", f"{BASE}/gates/agent-team/current", status=404, body={"detail": "x"})
    )
    studio = client(tmp_path, transport)

    assert team.current(studio, PROJECT_ID) is None
    assert team.readiness(studio, PROJECT_ID) == "TEAM_PROPOSAL_REQUIRED"
    assert team.gate(studio, PROJECT_ID) is None
    engineering = {
        "key": "SOFTWARE_ENGINEERING",
        "editable": False,
        "agent_id": None,
        "aspects": [
            {"key": "WEB", "editable": True, "agent_id": None},
            {"key": "MOBILE", "editable": True, "agent_id": "MOBILE_ENGINEER"},
            {"key": "SERVICES", "editable": "yes", "agent_id": "BACKEND_ENGINEER"},
            4,
        ],
    }
    security = {"key": "SECURITY", "editable": True, "agent_id": "SECURITY_REVIEWER"}
    proposal = {
        "selected_agent_ids": ["QA_TEST_ENGINEER", "UNKNOWN_AGENT", 3],
        "perspectives": [engineering, {"key": 7}, "UX", {**security, "aspects": "none"}],
    }
    assert team.selected(proposal) == ["QA_TEST_ENGINEER", "UNKNOWN_AGENT"]
    assert team.selected({"selected_agent_ids": "QA_TEST_ENGINEER"}) == []
    views = team.perspectives(proposal)
    assert views is not None
    assert [view["key"] for view in views] == ["SOFTWARE_ENGINEERING", "SECURITY"]
    assert [aspect["key"] for aspect in team.aspects(views[0])] == ["WEB", "MOBILE", "SERVICES"]
    assert team.aspects(views[1]) == []
    assert [unit["key"] for unit in team.switchable(views)] == ["MOBILE", "SECURITY"]
    for older in ({}, {"perspectives": None}, {"perspectives": []}, {"perspectives": [1]}):
        assert team.perspectives(older) is None
    transport.assert_done()


def test_the_modeling_calls(tmp_path: Path) -> None:
    modeling_base = f"{BASE}/user-modeling"
    transport = (
        ScriptedTransport()
        .expect("POST", f"{modeling_base}/personas/p-1/decision", body={"status": "APPLIED"})
        .expect("POST", f"{modeling_base}/personas/p-2/decision", body={"status": "APPLIED"})
        .expect("POST", f"{modeling_base}/gate/submit", body={"outcome": "APPLIED"})
        .expect("POST", f"{modeling_base}/gate/decision", body={"outcome": "APPLIED"})
        .expect("GET", f"{modeling_base}/readiness", body={"workflow_state": modeling.READY})
    )
    studio = client(tmp_path, transport)

    modeling.decide(studio, PROJECT_ID, "p-1", modeling.CONFIRM)
    modeling.decide(studio, PROJECT_ID, "p-2", modeling.REJECT, "Wrong")
    modeling.submit_gate(studio, PROJECT_ID)
    modeling.decide_gate(studio, PROJECT_ID)
    readiness = modeling.readiness(studio, PROJECT_ID)

    assert [request.json() for request in transport.sent[:4]] == [
        {"decision": "CONFIRM"},
        {"decision": "REJECT", "reason": "Wrong"},
        None,
        {"action": "APPROVE"},
    ]
    assert not modeling.approved(readiness)
    assert modeling.approved({**readiness, "approved_current_snapshot": True})
    assert (
        modeling.proposals_path(PROJECT_ID)
        == f"/projects/{PROJECT_ID}/user-modeling/personas/proposals"
    )
    assert modeling.generation_path(PROJECT_ID).endswith("/user-modeling/snapshots/generate")
    transport.assert_done()


def test_observations_are_read_by_their_kind() -> None:
    version = {
        "profile": {
            "name": "Anna",
            "confirmation_status": "PENDING_CONFIRMATION",
            "observations": [
                {"observation_key": "persona.summary", "value": {"kind": "TEXT", "text": "Hi"}},
                {"observation_key": "persona.goals", "value": {"kind": "ITEMS", "items": ["A"]}},
                {"observation_key": "persona.context_of_use", "value": {"kind": "UNKNOWN"}},
            ],
        },
        "snapshot": {"twin_versions": [{"twin_id": "t"}, "x"]},
    }

    assert modeling.observation(version, "persona.summary") == "Hi"
    assert modeling.observation(version, "persona.goals") == ["A"]
    assert modeling.observation(version, "persona.context_of_use") is None
    assert modeling.observation(version, "persona.role") is None
    assert (modeling.name(version), modeling.confirmation(version)) == (
        "Anna",
        modeling.PENDING,
    )
    assert modeling.twins(version) == [{"twin_id": "t"}]


def test_the_requirements_calls(tmp_path: Path) -> None:
    requirements_base = f"{BASE}/requirements"
    transport = (
        ScriptedTransport()
        .expect("POST", f"{requirements_base}/revisions/d-1/decision", body={"status": "APPLIED"})
        .expect("POST", f"{requirements_base}/revisions/d-2/decision", body={"status": "APPLIED"})
        .expect("POST", f"{requirements_base}/gate/submit", body={"status": "SUBMITTED"})
        .expect("POST", f"{requirements_base}/gate/decision", body={"status": "APPLIED"})
        .expect("GET", f"{requirements_base}/revisions", body=[{"id": "d-1"}, "x"])
    )
    studio = client(tmp_path, transport)

    requirements.decide(studio, PROJECT_ID, "d-1", requirements.APPROVE)
    requirements.decide(studio, PROJECT_ID, "d-2", requirements.REJECT, "No")
    requirements.submit_gate(studio, PROJECT_ID)
    requirements.decide_gate(studio, PROJECT_ID)

    assert [request.json() for request in transport.sent] == [
        {"decision": "APPROVE"},
        {"decision": "REJECT", "reason": "No"},
        None,
        {"action": "APPROVE"},
    ]
    assert requirements.revisions(studio, PROJECT_ID) == [{"id": "d-1"}]
    assert requirements.change_body("More") == {"request": "More"}
    transport.assert_done()


def test_the_pending_revision_is_the_proposed_one_of_the_current_version() -> None:
    version = {"id": "v-2"}
    items = [
        {"id": "d-1", "status": "PROPOSED", "base_version_id": "v-1"},
        {"id": "d-2", "status": "REJECTED", "base_version_id": "v-2"},
        {"id": "d-3", "status": "PROPOSED", "base_version_id": "v-2"},
    ]

    assert requirements.pending_revision(items, version) == items[2]
    assert requirements.pending_revision(items[:2], version) is None
    envelope = {"kind": "USER_STORY", "user_story": {"goal": "Pay"}, "requirement": None}
    assert requirements.artifact(envelope) == {"goal": "Pay"}
    assert requirements.artifact({"kind": "OTHER"}) is None


@pytest.mark.parametrize(
    ("document", "code"),
    [
        ({"detail": {"code": "TIMEOUT", "stage": "MODEL_PROPOSAL"}}, "TIMEOUT"),
        ({"detail": "invalid_team_proposal"}, "invalid_team_proposal"),
        ({"status": "BLOCKED_BY_CONSTRAINTS", "version": None}, "BLOCKED_BY_CONSTRAINTS"),
        ({"outcome": "STALE", "gate": None}, "STALE"),
        ("Internal Server Error", None),
        ({"detail": [{"loc": ["body"]}]}, None),
    ],
)
def test_the_code_of_an_answer(document: object, code: str | None) -> None:
    assert code_of(document) == code


BUDGET = {
    "currency": "USD",
    "per_generation_microusd": 2_000_000,
    "per_project_microusd": 20_000_000,
    "total_microusd": 60_000_000,
    "spent_total_microusd": 0,
    "remaining_total_microusd": 60_000_000,
    "period_start": None,
}


@pytest.mark.parametrize(
    ("budget", "spent", "reason", "sentence"),
    [
        (
            {**BUDGET, "remaining_total_microusd": 100_000},
            0,
            "total",
            "The Studio reached its overall spending ceiling (60.00 USD)",
        ),
        (
            BUDGET,
            19_900_000,
            "project",
            "This project reached its spending ceiling (20.00 USD)",
        ),
        (
            BUDGET,
            0,
            "generation",
            "This generation would go over the spending ceiling of a single generation (2.00 USD)",
        ),
    ],
)
def test_the_spending_ceiling_that_was_reached_is_named(
    tmp_path: Path, budget: dict[str, object], spent: int, reason: str, sentence: str
) -> None:
    transport = ScriptedTransport().expect("GET", f"{API}/model-runtime/budget", body=budget)
    if reason != "total":
        usage = {"items": [], "totals": {"cost_microusd": spent}}
        transport.expect("GET", f"{BASE}/model-usage", body=usage)
    found = journey(tmp_path, transport)

    error = found.budget_error("GENERATION_BUDGET_EXCEEDED", "REQUIREMENTS_PROPOSAL")

    assert (error.code, error.status, error.values["reason"]) == (
        "GENERATION_BUDGET_EXCEEDED",
        5,
        reason,
    )
    found.console.error(f"init.errors.GENERATION_BUDGET_EXCEEDED.{reason}", **error.values)
    assert sentence in found.console.environment.stderr.getvalue()
    transport.assert_done()


def test_a_budget_that_cannot_be_read_gives_the_general_sentence(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect(
        "GET",
        f"{API}/model-runtime/budget",
        status=503,
        body={"detail": {"code": "GENERATION_BUDGET_NOT_CONFIGURED"}},
    )
    found = journey(tmp_path, transport)

    error = found.budget_error("GENERATION_BUDGET_EXCEEDED", "TEAM_PROPOSAL")
    unavailable = found.budget_error("GENERATION_BUDGET_UNAVAILABLE", "TEAM_PROPOSAL")

    assert (error.code, dict(error.values)) == ("GENERATION_BUDGET_EXCEEDED", {})
    assert unavailable.code == "GENERATION_BUDGET_UNAVAILABLE"


def test_a_gate_refused_by_the_studio_is_named(tmp_path: Path) -> None:
    found = journey(tmp_path, ScriptedTransport())

    refused = found.gate_refused(409, {"status": "ITERATION_LIMIT_REACHED"}, "team")
    stale = found.gate_refused(409, {"detail": {"code": "ARTIFACT_STALE"}}, "twins")
    missing = found.gate_refused(
        409, {"status": "BRIEF_INCOMPLETE", "missing_fields": ["budget", "risks"]}, "brief"
    )

    assert (refused.code, dict(refused.values)) == (
        "GATE_REFUSED",
        {"step": "Perspectives", "code": "ITERATION_LIMIT_REACHED"},
    )
    assert (stale.code, stale.values["code"]) == ("STATE_CHANGED", "ARTIFACT_STALE")
    assert missing.code == "BRIEF_INCOMPLETE"
    assert missing.values["fields"] == "Budget, Risks"


def test_the_operations_of_the_spending_notice() -> None:
    assert init_command.operations(0, None, None) == [
        "BRIEF_DIALOGUE",
        "TEAM_PROPOSAL",
        "PERSONA_PROPOSAL",
        "USER_TWIN_GENERATION",
        "REQUIREMENTS_PROPOSAL",
    ]
    assert init_command.operations(1, "team", None) == ["TEAM_PROPOSAL"]
    assert init_command.operations(2, "brief", None) == []


def test_a_command_without_a_session_is_refused_before_any_request(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    context = command_context(terminal(tmp_path, transport=transport).environment)

    with pytest.raises(CliError) as caught:
        init_command.require_sign_in(context, context.client())

    assert (caught.value.code, caught.value.status) == ("NOT_SIGNED_IN", 3)
    assert transport.sent == []


def test_a_generation_already_running_is_followed_instead_of_a_new_one(tmp_path: Path) -> None:
    job = {
        "job_id": "job-1",
        "kind": "REQUEST",
        "operation": "REQUIREMENTS_PROPOSAL",
        "status": "RUNNING",
        "stage": "GENERATING",
        "attempt": 1,
        "response": None,
    }
    done = {
        **job,
        "status": "SUCCEEDED",
        "stage": None,
        "response": {"status_code": 201, "body": {"status": "CREATED", "version": {"id": "v"}}},
    }
    transport = (
        ScriptedTransport()
        .expect("GET", f"{BASE}/generation-jobs?status=RUNNING", body={"items": [job]})
        .expect("POST", f"{BASE}/requirements/proposals", status=202, body=job)
        .expect("GET", f"{BASE}/generation-jobs/job-1", body=done)
    )
    found = journey(tmp_path, transport)

    status, document = found.job(
        requirements.proposals_path(PROJECT_ID),
        operation="REQUIREMENTS_PROPOSAL",
        label="Writing the requirements",
    )

    assert (status, document) == (201, {"status": "CREATED", "version": {"id": "v"}})
    assert transport.requests("POST")[0].header("prefer") == "respond-async"
    assert (
        "Writing the requirements: a generation of this step is already running in the Studio; "
        "following it instead of starting another one."
        in found.console.environment.stdout.getvalue()
    )
    transport.assert_done()


@pytest.mark.parametrize(
    ("status", "last"),
    [
        (502, "Composing the brief: not completed after 0 s."),
        (409, "Composing the brief: not completed after 0 s."),
        (201, "Composing the brief: done in 0 s."),
    ],
)
def test_the_last_line_of_a_synchronous_step_says_how_it_ended(
    tmp_path: Path, status: int, last: str
) -> None:
    found = journey(tmp_path, ScriptedTransport())

    answer = found.waiting("Composing the brief", lambda: (status, {"detail": {"code": "X"}}))

    assert answer == (status, {"detail": {"code": "X"}})
    assert found.console.environment.stdout.getvalue().splitlines()[-1] == last
