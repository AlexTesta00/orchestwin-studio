from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from orchestwin.cli.api import team as team_api
from orchestwin.cli.commands.init import Journey
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows import init_team
from orchestwin.cli.messages import text

from .support.fake_studio import FakeStudio
from .support.terminal import (
    PROJECT_ID,
    command_context,
    link_folder,
    run_ut,
    store_session,
    terminal,
)
from .support.transports import API, ScriptedTransport
from .test_init_command import (
    IDEA,
    NAME,
    brief_answers,
    fake_project,
    posted,
    saved_stages,
    saved_step,
    sign_in,
    start,
    ut,
)

UNTIL_TEAM = ("--until", "team")
BEFORE_TEAM = [*start()[:-1], *brief_answers()]
PROPOSALS = "/projects/{project_id}/team-proposals"
BASE = f"{API}/projects/{PROJECT_ID}"
DESIGNER = "UX_UI_DESIGNER"
ACCESSIBILITY = "ACCESSIBILITY_REVIEWER"
PLATFORM = [
    "WORKFLOW_ORCHESTRATOR",
    "INTAKE_CLARIFICATION_AGENT",
    "TEAM_SELECTOR",
    "HUMAN_GATE_CONTROLLER",
    "ARTIFACT_MANAGER",
    "SANDBOX_CONTROLLER",
]
NOTE = (
    "Note: the approved team of this project has no UX/UI designer, so the design "
    "alternatives cannot be prepared until the team has it."
)


def name(agent: str, language: str = "en") -> str:
    return text(f"init.agent_{agent.lower()}", language)


def members_of_kind(team: Mapping[str, object], kind: str) -> list[str]:
    rules = team_api.constraints(team)
    return [
        agent
        for agent in team_api.ordered(rules)
        if rules[agent].get("kind") == kind and agent not in team_api.PLATFORM_AGENTS
    ]


def proposed_team(studio: FakeStudio, tmp_path: Path) -> Mapping[str, object]:
    run = ut(tmp_path, *UNTIL_TEAM, answers=[*BEFORE_TEAM, "3"])
    assert run.status == 0, run.errors
    team = fake_project(studio, tmp_path).current("team")
    assert team is not None
    return team


def test_the_team_is_changed_by_switching_specialists(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        team = proposed_team(studio, tmp_path)
        options = members_of_kind(team, "OPTIONAL")
        chosen = team_api.selected(team)
        added = next(agent for agent in options if agent not in chosen)
        removed = next((agent for agent in options if agent in chosen), None)
        toggles = [added] if removed is None else [removed, added]
        numbers = " ".join(str(options.index(agent) + 1) for agent in toggles)

        run = ut(tmp_path, *UNTIL_TEAM, answers=["2", numbers, "Screen readers matter", "1"])

        assert run.status == 0, run.errors
        expected = team_api.ordered([*(agent for agent in chosen if agent != removed), added])
        assert posted(studio, "/team-proposals/current") == [
            {
                "selected_agent_ids": expected,
                "owner_rationales": [{"agent_id": added, "statement": "Screen readers matter"}],
            }
        ]
        current = fake_project(studio, tmp_path).current("team")
        assert current["version_number"] == 2
        assert saved_step(tmp_path, "team")["version"] == current
    lines = run.output.splitlines()
    role = text(f"init.agent_{added.lower()}_role", "en")
    assert f"  {options.index(added) + 1}. [ ] {name(added)}: {role}" in lines
    fixed = ", ".join(name(agent) for agent in members_of_kind(team, "MANDATORY"))
    assert f"Always in the team, because they are mandatory members: {fixed}." in lines
    assert "Team updated (version 2)." in lines
    assert "     Why: added by you: Screen readers matter" in lines
    assert 'Step "Team" approved (version 2). Saved in .orchestwin/steps/team.json.' in lines


def test_the_proposed_team_says_why_each_specialist_is_there(tmp_path: Path) -> None:
    with FakeStudio(language="it") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, *UNTIL_TEAM, answers=[*BEFORE_TEAM, "1"], language="it")

        team = fake_project(studio, tmp_path).current("team")
    lines = run.output.splitlines()
    specialists = [
        agent for agent in team_api.selected(team) if agent not in team_api.PLATFORM_AGENTS
    ]
    assert run.status == 0, run.errors
    assert f"La squadra (versione 1). Specialisti: {len(specialists)}." in lines
    assert "     Perché: serve sempre per scrivere requisiti chiari" in lines
    assert sum(line.startswith("     Perché: ") for line in lines) == len(specialists)
    assert any(line.startswith("Sempre presenti, per far funzionare lo Studio:") for line in lines)


def test_numbers_that_are_not_valid_are_asked_again(tmp_path: Path) -> None:
    answers = [*BEFORE_TEAM, "2", "99", "two", "", "1"]
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, *UNTIL_TEAM, answers=answers)

        assert run.status == 0, run.errors
        assert posted(studio, "/team-proposals/current") == []
        team = fake_project(studio, tmp_path).current("team")
        assert team["version_number"] == 1
    count = len(members_of_kind(team, "OPTIONAL"))
    assert run.output.count(f"Write only numbers from 1 to {count}, separated by spaces.") == 2
    assert "The team does not change." in run.output


def test_a_change_refused_by_the_studio_says_why(tmp_path: Path) -> None:
    refusal = {
        "status": "REJECTED",
        "version": None,
        "issues": [{"code": "MANDATORY_AGENT_MISSING", "agent_id": "QA_TEST_ENGINEER"}],
        "events": [],
    }
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        team = proposed_team(studio, tmp_path)
        options = members_of_kind(team, "OPTIONAL")
        added = next(agent for agent in options if agent not in team_api.selected(team))
        studio.fail_next("PATCH", PROPOSALS + "/current", status=422, body=refusal)

        number = str(options.index(added) + 1)
        run = ut(tmp_path, *UNTIL_TEAM, answers=["2", number, "Data behind the page", "1"])

        assert run.status == 0, run.errors
        assert fake_project(studio, tmp_path).current("team")["version_number"] == 1
    assert (
        "Quality specialist cannot be removed: it is a mandatory member of the team." in run.output
    )


def test_a_failed_team_proposal_is_tried_again_after_asking(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        studio.fail_next("POST", PROPOSALS, status=502, body={"detail": "invalid_team_proposal"})

        run = ut(tmp_path, *UNTIL_TEAM, answers=[*BEFORE_TEAM, "y", "1"])

        assert run.status == 0, run.errors
        assert fake_project(studio, tmp_path).approved("team")
    assert (
        "Proposing the team: the model did not give a valid result (invalid_team_proposal)."
        in run.output
    )
    assert "Try once more? It is a new generation, about 0.02-0.03 USD. [Y/n]" in run.output


def test_a_failed_team_proposal_without_a_second_try(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        studio.fail_next("POST", PROPOSALS, status=502, body={"detail": "invalid_team_proposal"})

        run = ut(tmp_path, *UNTIL_TEAM, answers=[*BEFORE_TEAM, "n"])

        assert run.status == 1
        assert saved_stages(tmp_path) == ["brief"]
    assert (
        "Proposing the team: the generation did not succeed (invalid_team_proposal)." in run.errors
    )


def test_a_spending_ceiling_reached_names_the_ceiling(tmp_path: Path) -> None:
    with FakeStudio(language="en", budget_usd=0.1) as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, answers=[*start(), *brief_answers()])

        assert run.status == 5
        assert saved_stages(tmp_path) == ["brief"]
        assert fake_project(studio, tmp_path).current("team") is None
    assert "The estimate is above the credit left" in run.output
    assert (
        "The Studio reached its overall spending ceiling (0.10 USD): the generation did not "
        "start. Whoever runs the Studio can raise it" in run.errors
    )


def test_a_team_blocked_by_the_brief_names_the_roles(tmp_path: Path) -> None:
    blocked = {
        "status": "BLOCKED_BY_CONSTRAINTS",
        "version": None,
        "issues": [
            {
                "code": "CONTRADICTORY_ROLE_SIGNALS",
                "agent_id": "MOBILE_ENGINEER",
                "mandatory_reasons": [],
                "impossible_reasons": [],
            }
        ],
    }
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        studio.fail_next("POST", PROPOSALS, status=409, body=blocked)

        run = ut(tmp_path, *UNTIL_TEAM, answers=BEFORE_TEAM)

    assert run.status == 1
    assert "the brief both asks for and excludes these roles: Mobile developer." in run.errors


def test_an_answers_file_can_stop_at_the_team(tmp_path: Path) -> None:
    script = tmp_path / "answers.json"
    script.write_text(json.dumps({"name": NAME, "idea": IDEA, "team": "STOP"}), encoding="utf-8")
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, "--answers", str(script), yes=True)

        assert run.status == 0, run.errors
        assert saved_stages(tmp_path) == ["brief"]
        assert fake_project(studio, tmp_path).current("team")["version_number"] == 1
    assert "The team stays waiting for your approval." in run.output


RULES = {
    "REQUIREMENTS_ANALYST": ("MANDATORY", "CORE_REQUIREMENTS_DISCIPLINE"),
    "UX_RESEARCHER_USER_MODELER": ("MANDATORY", "CORE_USER_CENTERED_DESIGN"),
    DESIGNER: ("MANDATORY", "CORE_USER_CENTERED_DESIGN"),
    "SOFTWARE_ARCHITECT": ("MANDATORY", "CORE_ARCHITECTURE_DISCIPLINE"),
    "FRONTEND_ENGINEER": ("MANDATORY", "WEB_DELIVERY_SIGNAL"),
    "MOBILE_ENGINEER": ("OPTIONAL", None),
    "QA_TEST_ENGINEER": ("MANDATORY", "CORE_QUALITY_DISCIPLINE"),
    ACCESSIBILITY: ("MANDATORY", "CORE_ACCESSIBILITY_DISCIPLINE"),
}
SPECIALISTS = [agent for agent, (kind, _) in RULES.items() if kind == "MANDATORY"]
WITHOUT_DESIGNER = [agent for agent in SPECIALISTS if agent != DESIGNER]


def rule(agent: str, kind: str, code: str | None) -> dict[str, object]:
    reasons = [] if code is None else [{"code": code, "evidence": {"fields": [], "terms": []}}]
    return {
        "agent_id": agent,
        "kind": kind,
        "owner_editable": kind == "OPTIONAL",
        "reasons": reasons,
    }


def team_version(
    number: int,
    specialists: list[str],
    *,
    rules: Mapping[str, tuple[str, str | None]] = RULES,
    justifications: Mapping[str, list[dict[str, object]]] | None = None,
) -> dict[str, object]:
    return {
        "id": f"team-{number}",
        "version_number": number,
        "content_hash": f"team-hash-{number}",
        "selected_agent_ids": [*PLATFORM, *specialists],
        "role_constraints": [
            *(rule(agent, "MANDATORY", "CATALOG_ALWAYS_PRESENT") for agent in PLATFORM),
            *(rule(agent, kind, code) for agent, (kind, code) in rules.items()),
        ],
        "constraint_issues": [],
        "members": [
            {"agent_id": agent, "justifications": (justifications or {}).get(agent, [])}
            for agent in specialists
        ],
    }


def gate(version: Mapping[str, object], status: str) -> dict[str, object]:
    return {
        "id": f"gate-{version['id']}",
        "status": status,
        "artifact": {"artifact_id": version["id"], "content_hash": version["content_hash"]},
    }


def expect_approval(transport: ScriptedTransport, version: Mapping[str, object]) -> None:
    transport.expect(
        "POST",
        f"{BASE}/gates/agent-team/submit",
        status=201,
        body={"status": "SUBMITTED", "gate": gate(version, "PENDING_APPROVAL"), "events": []},
    )
    transport.expect(
        "POST",
        f"{BASE}/gates/agent-team/decisions",
        body={"status": "APPLIED", "gate": gate(version, "APPROVED"), "event": None},
    )


def team_step(
    tmp_path: Path, transport: ScriptedTransport, answers: list[str], version: dict[str, object]
) -> tuple[bool, Journey]:
    store_session(tmp_path)
    folder = link_folder(tmp_path / "project")
    bundle = terminal(tmp_path, transport=transport, answers=answers)
    context = command_context(bundle.environment)
    journey = Journey(context, context.client(), folder, script=None, until=None, idea=None)
    state = init_team.TeamState(
        approved=False, readiness="TEAM_APPROVAL_REQUIRED", version=version, gate=None
    )
    return init_team.run(journey, state), journey


def printed(journey: Journey) -> str:
    return journey.console.environment.stdout.getvalue()


def test_the_mandatory_specialists_are_among_the_fixed_ones(tmp_path: Path) -> None:
    version = team_version(1, SPECIALISTS)
    transport = ScriptedTransport()
    expect_approval(transport, version)

    approved, journey = team_step(tmp_path, transport, ["2", "", "1"], version)

    assert approved
    assert transport.requests("PATCH") == []
    lines = printed(journey).splitlines()
    assert (
        "Always in the team, because they are mandatory members: Needs analyst, User "
        "researcher, UX/UI designer, Product architect, Interface developer, Quality "
        "specialist, Accessibility specialist." in lines
    )
    assert "  1. [ ] Mobile developer: Builds the experience for phones and tablets." in lines
    assert "     Why: Accessibility is part of every project" in lines
    assert "     Why: always needed to design around the users" in lines
    assert not journey.designer_note
    transport.assert_done()


def test_a_reason_code_that_the_command_does_not_know_is_shown_as_it_is(
    tmp_path: Path,
) -> None:
    rules = {
        **RULES,
        "SOFTWARE_ARCHITECT": ("MANDATORY", "ANOTHER_NEW_RULE"),
        "QA_TEST_ENGINEER": ("MANDATORY", "BRAND_NEW_RULE"),
    }
    unknown = {
        "SOFTWARE_ARCHITECT": [
            {"kind": "DETERMINISTIC_RULE", "code": "ANOTHER_NEW_RULE", "statement": None}
        ]
    }
    version = team_version(1, SPECIALISTS, rules=rules, justifications=unknown)
    transport = ScriptedTransport()
    expect_approval(transport, version)

    approved, journey = team_step(tmp_path, transport, ["1"], version)

    assert approved
    lines = printed(journey).splitlines()
    architect = lines.index(
        "  4. Product architect: Checks that requirements and design hold together."
    )
    quality = lines.index(
        "  6. Quality specialist: Writes how to check each requirement before calling it done."
    )
    assert lines[architect + 1] == "     Why: ANOTHER_NEW_RULE"
    assert lines[quality + 1] == "     Why: BRAND_NEW_RULE"
    transport.assert_done()


@pytest.mark.parametrize(("specialists", "noted"), [(WITHOUT_DESIGNER, True), (SPECIALISTS, False)])
def test_approving_a_team_remembers_whether_it_has_the_designer(
    tmp_path: Path, specialists: list[str], noted: bool
) -> None:
    version = team_version(1, specialists)
    transport = ScriptedTransport()
    expect_approval(transport, version)

    approved, journey = team_step(tmp_path, transport, ["1"], version)

    assert approved
    assert journey.designer_note is noted
    assert NOTE not in printed(journey)
    transport.assert_done()


def test_a_failed_team_proposal_ends_its_progress_as_not_completed(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect(
        "POST", f"{BASE}/team-proposals", status=502, body={"detail": "invalid_team_proposal"}
    )
    store_session(tmp_path)
    folder = link_folder(tmp_path / "project")
    bundle = terminal(tmp_path, transport=transport, answers=["n"])
    context = command_context(bundle.environment)
    journey = Journey(context, context.client(), folder, script=None, until=None, idea=None)
    state = init_team.TeamState(
        approved=False, readiness="TEAM_PROPOSAL_REQUIRED", version=None, gate=None
    )

    with pytest.raises(CliError) as caught:
        init_team.run(journey, state)

    assert caught.value.code == "GENERATION_FAILED"
    lines = printed(journey).splitlines()
    ended = lines.index("Proposing the team: not completed after 0 s.")
    assert lines[ended - 1] == "Proposing the team..."
    assert lines[ended + 1] == (
        "Proposing the team: the model did not give a valid result (invalid_team_proposal)."
    )
    assert "Proposing the team: done in" not in printed(journey)
    transport.assert_done()


def expect_approved_path(transport: ScriptedTransport, team: Mapping[str, object]) -> None:
    brief = {"id": "brief-1", "version_number": 1, "content_hash": "brief-hash", "brief": {}}
    snapshot = {"id": "snapshot-1", "version_number": 1, "content_hash": "snapshot-hash"}
    requirements = {"id": "spec-1", "version_number": 1, "content_hash": "spec-hash"}
    transport.expect(
        "GET", BASE, body={"id": PROJECT_ID, "display_name": NAME, "current_stage": "DESIGN"}
    )
    transport.expect("GET", f"{BASE}/brief-versions/current", body=brief)
    transport.expect("GET", f"{BASE}/gates/project-brief/current", body=gate(brief, "APPROVED"))
    transport.expect("GET", f"{BASE}/team-proposals/current", body=team)
    transport.expect("GET", f"{BASE}/readiness", body={"status": "READY_FOR_MAIN_WORKFLOW"})
    transport.expect("GET", f"{BASE}/gates/agent-team/current", body=gate(team, "APPROVED"))
    transport.expect(
        "GET",
        f"{BASE}/user-modeling/readiness",
        body={
            "workflow_state": "READY_FOR_REQUIREMENTS_DEFINITION",
            "approved_current_snapshot": True,
            "snapshot_version_number": 1,
        },
    )
    transport.expect("GET", f"{BASE}/user-modeling/snapshots/current", body=snapshot)
    transport.expect("GET", f"{BASE}/user-modeling/gate", body=gate(snapshot, "APPROVED"))
    transport.expect(
        "GET",
        f"{BASE}/requirements/readiness",
        body={
            "status": "READY_FOR_DESIGN_EXPLORATION",
            "version": requirements,
            "gate": gate(requirements, "APPROVED"),
        },
    )
    transport.expect(
        "POST",
        f"{BASE}/knowledge-packages",
        status=409,
        body={"detail": {"code": "DESIGN_APPROVAL_REQUIRED"}},
    )


@pytest.mark.parametrize(("specialists", "noted"), [(WITHOUT_DESIGNER, True), (SPECIALISTS, False)])
def test_a_team_approved_before_without_the_designer_is_noted_once_at_the_end(
    tmp_path: Path, specialists: list[str], noted: bool
) -> None:
    store_session(tmp_path)
    link_folder(tmp_path / "project")
    transport = ScriptedTransport()
    expect_approved_path(transport, team_version(1, specialists))

    run = run_ut(["init"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    assert run.output.count(NOTE) == (1 if noted else 0)
    lines = run.output.splitlines()
    if noted:
        design = next(index for index, line in enumerate(lines) if "`ut design`: it" in line)
        assert lines[design + 1].startswith(NOTE)
        assert lines[design + 1].endswith(
            "The team is changed and approved again in the web Studio."
        )
    transport.assert_done()
