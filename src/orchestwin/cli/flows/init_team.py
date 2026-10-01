from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import brief as brief_api
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
ALWAYS: Final = "ALWAYS"
PERSPECTIVE_INDENT: Final = "  "
ASPECT_INDENT: Final = "      "


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
            options = [Choice("approve", journey.text("init.team_approve"))]
            if team_api.perspectives(team) is not None:
                options.append(Choice("change", journey.text("init.team_change")))
            options.append(Choice("stop", journey.text("init.team_stop")))
            action = journey.console.choose("init.team_choice", options).key
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
        issues = team_api.issues(document)
        names = _unique(agent_name(journey, str(issue.get("agent_id"))) for issue in issues)
        sentences = [sentence for issue in issues if (sentence := contradiction(journey, issue))]
        raise CliError(
            "TEAM_BLOCKED",
            values={
                "names": ", ".join(names),
                "details": "".join(f" {sentence}" for sentence in sentences),
            },
        )
    version = team_api.version(document)
    if version is None:
        raise ApiFailure("API_FAILURE", http_status=status, detail=document)
    return version


def show(journey: Journey, team: Mapping[str, object]) -> None:
    journey.console.write()
    journey.say("init.team_heading", version=_number(team) or "-")
    journey.say("init.team_intro")
    views = team_api.perspectives(team)
    if views is None:
        journey.say("init.team_outdated")
        return
    for perspective in views:
        journey.console.write(PERSPECTIVE_INDENT + unit_line(journey, perspective))
        for aspect in team_api.aspects(perspective):
            journey.console.write(ASPECT_INDENT + unit_line(journey, aspect))


def change(journey: Journey, team: Mapping[str, object]) -> Mapping[str, object]:
    units = team_api.switchable(team_api.perspectives(team) or [])
    if not units:
        journey.say("init.team_nothing")
        return team
    journey.say("init.team_switch_intro")
    for number, unit in enumerate(units, start=1):
        journey.console.write(f"  {number}. {_mark(unit)} {_described(journey, unit)}")
    numbers = _numbers(journey, len(units))
    if not numbers:
        journey.say("init.team_unchanged")
        return team
    wanted = team_api.selected(team)
    for number in numbers:
        wanted = team_api.switched(wanted, str(units[number - 1]["agent_id"]))
    status, document = team_api.edit(journey.client, journey.project_id, wanted)
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


def contradiction(journey: Journey, issue: Mapping[str, object]) -> str | None:
    excluded = _reason_words(journey, issue.get("impossible_reasons"))
    required = _reason_words(journey, issue.get("mandatory_reasons"))
    if not excluded or not required:
        return None
    return journey.text(
        "init.team_blocked",
        name=agent_name(journey, str(issue.get("agent_id"))),
        excluded=excluded,
        required=required,
    )


def unit_line(journey: Journey, unit: Mapping[str, object]) -> str:
    name = unit_name(journey, str(unit.get("key")))
    return f"{_mark(unit)} {name}: {standing(journey, unit)}"


def standing(journey: Journey, unit: Mapping[str, object]) -> str:
    value = str(unit.get("standing"))
    applied = unit.get("applied") is True
    requested = words(journey, unit.get("requested"))
    excluded = words(journey, unit.get("excluded"))
    if value == team_api.OPTIONAL and applied:
        label = journey.text("init.standing_optional_applied")
    elif value == ALWAYS and not applied:
        label = journey.text("init.standing_always_missing")
    elif value in team_api.STANDINGS:
        label = journey.text(f"init.standing_{value.lower()}")
    else:
        label = value.lower().replace("_", " ")
    shown: list[str] = []
    if value == team_api.REQUIRED:
        shown = [requested]
    elif value == team_api.EXCLUDED:
        shown = [excluded]
    elif value == team_api.CONTESTED:
        shown = [
            journey.text("init.team_asks", words=requested) if requested else "",
            journey.text("init.team_rules_out", words=excluded) if excluded else "",
        ]
    detail = "; ".join(item for item in shown if item)
    return f"{label} ({detail})" if detail else label


def words(journey: Journey, evidence: object) -> str:
    if not isinstance(evidence, Mapping):
        return ""
    terms = _unique(_texts(evidence.get("terms")))
    if not terms:
        return ""
    quoted = ", ".join(journey.text("init.team_term", term=term) for term in terms)
    fields = _unique(_texts(evidence.get("fields")))
    if not fields:
        return quoted
    labels = ", ".join(_field_label(journey, field) for field in fields)
    return journey.text("init.team_evidence", terms=quoted, fields=labels)


def unit_name(journey: Journey, key: str) -> str:
    if key in team_api.PERSPECTIVES:
        return journey.text(f"init.perspective_{key.lower()}")
    if key in team_api.ASPECTS:
        return journey.text(f"init.aspect_{key.lower()}")
    return key.lower().replace("_", " ")


def unit_description(journey: Journey, key: str) -> str:
    if key in team_api.PERSPECTIVES:
        return journey.text(f"init.perspective_{key.lower()}_line")
    if key in team_api.ASPECTS:
        return journey.text(f"init.aspect_{key.lower()}_line")
    return ""


def agent_name(journey: Journey, agent: str) -> str:
    key = team_api.unit_of(agent)
    return unit_name(journey, agent if key is None else key)


def _described(journey: Journey, unit: Mapping[str, object]) -> str:
    key = str(unit.get("key"))
    name = unit_name(journey, key)
    description = unit_description(journey, key)
    return f"{name}: {description}" if description else name


def _mark(unit: Mapping[str, object]) -> str:
    return "[x]" if unit.get("applied") is True else "[ ]"


def _reason_words(journey: Journey, reasons: object) -> str:
    if not isinstance(reasons, list):
        return ""
    proofs = [
        proof
        for item in reasons
        if isinstance(item, Mapping) and isinstance(proof := item.get("evidence"), Mapping)
    ]
    merged = {
        "terms": [term for proof in proofs for term in _texts(proof.get("terms"))],
        "fields": [field for proof in proofs for field in _texts(proof.get("fields"))],
    }
    return words(journey, merged)


def _field_label(journey: Journey, field: str) -> str:
    if field in brief_api.FIELDS:
        return journey.text(f"init.field_{field}")
    return field.replace("_", " ")


def _texts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _edited(journey: Journey, status: int, document: object) -> Mapping[str, object]:
    if status >= 400:
        raise journey.refused(status, document)
    version = team_api.version(document)
    if version is None:
        raise ApiFailure("API_FAILURE", http_status=status, detail=document)
    return version


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


def _number(version: Mapping[str, object] | None) -> int | None:
    value = None if version is None else version.get("version_number")
    return value if isinstance(value, int) and not isinstance(value, bool) else None
