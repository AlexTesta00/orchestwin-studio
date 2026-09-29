from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import team as team_api
from orchestwin.cli.api.projects import approves
from orchestwin.cli.console import Choice
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.flows.answers import APPROVE

if TYPE_CHECKING:
    from orchestwin.cli.commands.init import Journey

STAGE: Final = "team"
OPERATION: Final = "TEAM_PROPOSAL"
ATTEMPTS: Final = 5
OWNER_RATIONALE: Final = "OWNER_RATIONALE"


@dataclass(frozen=True, slots=True)
class TeamState:
    approved: bool
    readiness: str | None
    version: Mapping[str, object] | None
    gate: Mapping[str, object] | None

    @property
    def number(self) -> int | None:
        return _number(self.version)


def read(journey: Journey) -> TeamState:
    version = team_api.current(journey.client, journey.project_id)
    readiness = team_api.readiness(journey.client, journey.project_id)
    gate = None if version is None else team_api.gate(journey.client, journey.project_id)
    approved = (
        version is not None
        and gate is not None
        and readiness == team_api.READY
        and approves(gate, version)
    )
    if approved and version is not None and gate is not None:
        journey.keep(STAGE, version, gate)
        journey.designer_note = not has_designer(version)
    return TeamState(approved=approved, readiness=readiness, version=version, gate=gate)


def run(journey: Journey, state: TeamState) -> bool:
    if state.readiness is not None and state.readiness.startswith("BRIEF_"):
        raise journey.changed(state.readiness)
    team = state.version
    if team is None or state.readiness not in {team_api.APPROVAL_REQUIRED, team_api.READY}:
        team = propose(journey)
    while True:
        show(journey, team)
        if journey.script is not None:
            action = "approve" if journey.script.team == APPROVE else "stop"
        else:
            action = journey.console.choose(
                "init.team_choice",
                [
                    Choice("approve", journey.text("init.team_approve")),
                    Choice("change", journey.text("init.team_change")),
                    Choice("stop", journey.text("init.team_stop")),
                ],
            ).key
        if action == "stop":
            journey.say("init.team_left")
            return False
        if action == "change":
            team = change(journey, team)
            continue
        gate = journey.approve(
            lambda: team_api.submit_gate(journey.client, journey.project_id),
            lambda: team_api.decide_gate(journey.client, journey.project_id),
            step=STAGE,
        )
        journey.conclude(STAGE, team, gate)
        journey.designer_note = not has_designer(team)
        return True


def propose(journey: Journey) -> Mapping[str, object]:
    label = journey.text("init.team_label")
    status, document = journey.generate(
        lambda: journey.waiting(
            label, lambda: team_api.propose(journey.client, journey.project_id)
        ),
        operation=OPERATION,
        label=label,
        passthrough=(team_api.BLOCKED,),
    )
    if status >= 400:
        agents = [str(issue.get("agent_id")) for issue in team_api.issues(document)]
        raise CliError(
            "TEAM_BLOCKED",
            values={"agents": ", ".join(agent_name(journey, agent) for agent in agents)},
        )
    version = team_api.version(document)
    if version is None:
        raise ApiFailure("API_FAILURE", http_status=status, detail=document)
    return version


def show(journey: Journey, team: Mapping[str, object]) -> None:
    chosen = team_api.selected(team)
    specialists = [agent for agent in chosen if agent not in team_api.PLATFORM_AGENTS]
    platform = [agent for agent in chosen if agent in team_api.PLATFORM_AGENTS]
    journey.console.write()
    journey.say("init.team_heading", version=_number(team) or "-", count=len(specialists))
    for number, agent in enumerate(specialists, start=1):
        journey.console.write(
            f"  {number}. {agent_name(journey, agent)}: {agent_role(journey, agent)}"
        )
        journey.console.write(
            "     " + journey.text("init.team_why", reason=reason(journey, team, agent))
        )
    if platform:
        journey.say(
            "init.team_platform",
            names=", ".join(agent_name(journey, agent) for agent in platform),
        )


def change(journey: Journey, team: Mapping[str, object]) -> Mapping[str, object]:
    chosen = team_api.selected(team)
    rules = team_api.constraints(team)
    switchable = [
        agent
        for agent in team_api.ordered(rules)
        if rules[agent].get("kind") == team_api.OPTIONAL and agent not in team_api.PLATFORM_AGENTS
    ]
    fixed = [
        agent
        for agent in team_api.ordered(rules)
        if rules[agent].get("kind") == team_api.MANDATORY and agent not in team_api.PLATFORM_AGENTS
    ]
    excluded = [
        agent
        for agent in team_api.ordered(rules)
        if rules[agent].get("kind") in team_api.EXCLUDED_KINDS
    ]
    if fixed:
        journey.say(
            "init.team_fixed", names=", ".join(agent_name(journey, agent) for agent in fixed)
        )
    if excluded:
        journey.say(
            "init.team_excluded",
            names=", ".join(agent_name(journey, agent) for agent in excluded),
        )
    if not switchable:
        journey.say("init.team_nothing")
        return team
    journey.say("init.team_switch_intro")
    for number, agent in enumerate(switchable, start=1):
        mark = "x" if agent in chosen else " "
        journey.console.write(
            f"  {number}. [{mark}] {agent_name(journey, agent)}: {agent_role(journey, agent)}"
        )
    numbers = _numbers(journey, len(switchable))
    if not numbers:
        journey.say("init.team_unchanged")
        return team
    wanted = set(chosen)
    for number in numbers:
        wanted ^= {switchable[number - 1]}
    added = [agent for agent in team_api.ordered(wanted) if agent not in chosen]
    rationales = {agent: _rationale(journey, agent) for agent in added}
    status, document = team_api.edit(
        journey.client, journey.project_id, team_api.ordered(wanted), rationales
    )
    if status == 422 and team_api.issues(document):
        refusals(journey, document)
        return team
    version = _edited(journey, status, document)
    if isinstance(document, Mapping) and document.get("status") == team_api.UNCHANGED:
        journey.say("init.team_unchanged")
    else:
        journey.say("init.team_updated", version=_number(version) or "-")
    return version


def has_designer(team: Mapping[str, object]) -> bool:
    return team_api.DESIGNER in team_api.selected(team)


def refusals(journey: Journey, document: object) -> None:
    for issue in team_api.issues(document):
        code = str(issue.get("code"))
        name = agent_name(journey, str(issue.get("agent_id")))
        if code in team_api.EDIT_ISSUES:
            journey.say(f"init.team_issue_{code.lower()}", name=name)
        else:
            journey.say("init.team_issue", name=name, code=code)


def _edited(journey: Journey, status: int, document: object) -> Mapping[str, object]:
    if status >= 400:
        raise journey.refused(status, document)
    version = team_api.version(document)
    if version is None:
        raise ApiFailure("API_FAILURE", http_status=status, detail=document)
    return version


def reason(journey: Journey, team: Mapping[str, object], agent: str) -> str:
    member = team_api.members(team).get(agent, {})
    justifications = member.get("justifications")
    items = [item for item in justifications or [] if isinstance(item, Mapping)]
    for item in items:
        statement = item.get("statement")
        if isinstance(statement, str) and statement:
            if item.get("kind") == OWNER_RATIONALE:
                return journey.text("init.team_owner_reason", reason=statement)
            return statement
    codes = [str(item["code"]) for item in items if isinstance(item.get("code"), str)]
    codes.extend(team_api.reason_codes(team_api.constraints(team).get(agent, {})))
    for code in codes:
        if code in team_api.REASON_CODES:
            return journey.text(f"init.reason_{code.lower()}")
    if codes:
        return codes[0]
    return journey.text("init.reason_unknown")


def agent_name(journey: Journey, agent: str) -> str:
    if agent in team_api.AGENTS:
        return journey.text(f"init.agent_{agent.lower()}")
    return agent


def agent_role(journey: Journey, agent: str) -> str:
    if agent in team_api.AGENTS:
        return journey.text(f"init.agent_{agent.lower()}_role")
    return ""


def _numbers(journey: Journey, count: int) -> list[int]:
    for _ in range(ATTEMPTS):
        line = journey.console.ask("init.team_switch", required=False)
        tokens = line.replace(",", " ").split()
        if not tokens:
            return []
        if all(token.isdecimal() and 1 <= int(token) <= count for token in tokens):
            return sorted({int(token) for token in tokens})
        journey.say("init.team_switch_invalid", count=count)
    raise CliError("ANSWER_NOT_VALID")


def _rationale(journey: Journey, agent: str) -> str:
    for _ in range(ATTEMPTS):
        text = " ".join(
            journey.console.ask("init.team_add_reason", name=agent_name(journey, agent)).split()
        )
        if len(text) <= team_api.MAX_RATIONALE:
            return text
        journey.say("init.answer_too_long", limit=team_api.MAX_RATIONALE)
    raise CliError("ANSWER_NOT_VALID")


def _number(version: Mapping[str, object] | None) -> int | None:
    value = None if version is None else version.get("version_number")
    return value if isinstance(value, int) and not isinstance(value, bool) else None
