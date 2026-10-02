from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import modeling
from orchestwin.cli.commands import archetypes
from orchestwin.cli.console import Choice
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows.answers import APPROVE
from orchestwin.cli.views import personas

if TYPE_CHECKING:
    from orchestwin.cli.commands.init import Journey

STAGE: Final = "twins"
PERSONA_OPERATION: Final = "PERSONA_PROPOSAL"
TWIN_OPERATION: Final = "USER_TWIN_GENERATION"
ATTEMPTS: Final = 5
PERSONA_DETAILS: Final = (
    ("persona.role", "init.detail_role"),
    ("persona.summary", "init.detail_summary"),
    ("persona.goals", "init.detail_goals"),
    ("persona.frustrations", "init.detail_difficulties"),
    ("persona.pain_points", "init.detail_difficulties"),
    ("persona.context_of_use", "init.detail_context"),
)
TWIN_DETAILS: Final = (
    ("user_twin.role", "init.detail_role"),
    ("user_twin.goals", "init.detail_goals"),
    ("user_twin.frustrations", "init.detail_difficulties"),
    ("user_twin.pain_points", "init.detail_difficulties"),
    ("user_twin.context_of_use", "init.detail_context"),
)


@dataclass(frozen=True, slots=True)
class TwinsState:
    approved: bool
    readiness: Mapping[str, object]
    version: Mapping[str, object] | None
    gate: Mapping[str, object] | None

    @property
    def number(self) -> int | None:
        value = self.readiness.get("snapshot_version_number")
        return value if isinstance(value, int) and not isinstance(value, bool) else None


def read(journey: Journey) -> TwinsState:
    readiness = modeling.readiness(journey.client, journey.project_id)
    if not modeling.approved(readiness):
        return TwinsState(approved=False, readiness=readiness, version=None, gate=None)
    version = modeling.snapshot(journey.client, journey.project_id)
    gate = modeling.gate(journey.client, journey.project_id)
    if version is None or gate is None:
        return TwinsState(approved=False, readiness=readiness, version=version, gate=gate)
    journey.keep(STAGE, version, gate)
    return TwinsState(approved=True, readiness=readiness, version=version, gate=gate)


def run(journey: Journey, state: TwinsState) -> bool:
    snapshot = None
    if modeling.current_snapshot(state.readiness):
        snapshot = modeling.snapshot(journey.client, journey.project_id)
    if snapshot is None:
        personas = modeling.personas(journey.client, journey.project_id)
        if not personas:
            personas = propose(journey)
        decide(journey, personas)
        snapshot = generate(journey)
    for _ in range(ATTEMPTS):
        show(journey, snapshot)
        if journey.script is not None:
            action = "approve" if journey.script.twins == APPROVE else "stop"
        else:
            action = journey.console.choose(
                "init.twins_choice",
                [
                    Choice("approve", journey.text("init.twins_approve")),
                    Choice("stop", journey.text("init.twins_stop")),
                    Choice("manage", journey.text("init.twins_manage")),
                ],
            ).key
        if action == "manage":
            archetypes.manage(journey.context, journey.client, journey.project_id)
            readiness = modeling.readiness(journey.client, journey.project_id)
            if readiness.get("archetypes_current") is False:
                decide(journey, modeling.personas(journey.client, journey.project_id))
                snapshot = generate(journey)
            continue
        if action == "stop":
            journey.say("init.twins_left")
            return False
        gate = journey.approve(
            lambda: modeling.submit_gate(journey.client, journey.project_id),
            lambda: modeling.decide_gate(journey.client, journey.project_id),
            step=STAGE,
        )
        journey.conclude(STAGE, snapshot, gate)
        return True
    raise CliError("ANSWER_NOT_VALID")


def propose(journey: Journey) -> list[Mapping[str, object]]:
    _, document = journey.job(
        modeling.proposals_path(journey.project_id),
        operation=PERSONA_OPERATION,
        label=journey.text("init.profiles_label"),
    )
    versions = document.get("versions") if isinstance(document, Mapping) else None
    found = [item for item in versions or [] if isinstance(item, Mapping)]
    return found or modeling.personas(journey.client, journey.project_id)


def decide(journey: Journey, personas: Sequence[Mapping[str, object]]) -> None:
    total = len(personas)
    confirmed = sum(1 for item in personas if modeling.confirmation(item) == modeling.CONFIRMED)
    pending = sum(1 for item in personas if modeling.confirmation(item) == modeling.PENDING)
    if pending:
        journey.console.write()
        journey.say("init.profiles_intro", count=total)
    for number, persona in enumerate(personas, start=1):
        status = modeling.confirmation(persona)
        name = modeling.name(persona)
        if status != modeling.PENDING:
            key = (
                "init.profile_confirmed"
                if status == modeling.CONFIRMED
                else "init.profile_rejected"
            )
            journey.say(key, number=number, total=total, name=name)
            continue
        pending -= 1
        journey.console.write()
        journey.say("init.profile_heading", number=number, total=total, name=name)
        details(journey, persona, PERSONA_DETAILS)
        decision, reason = _choice(journey, last=confirmed == 0 and pending == 0)
        status_code, document = modeling.decide(
            journey.client, journey.project_id, str(persona.get("persona_id")), decision, reason
        )
        if status_code >= 400:
            raise journey.refused(status_code, document)
        if decision == modeling.CONFIRM:
            confirmed += 1
    if confirmed == 0:
        raise CliError("NO_PROFILE_CONFIRMED")


def generate(journey: Journey) -> Mapping[str, object]:
    _, document = journey.job(
        modeling.generation_path(journey.project_id),
        operation=TWIN_OPERATION,
        label=journey.text("init.twins_label"),
    )
    found = document.get("snapshot_version") if isinstance(document, Mapping) else None
    if isinstance(found, Mapping):
        return found
    current = modeling.snapshot(journey.client, journey.project_id)
    if current is None:
        raise journey.changed("USER_MODELING_SNAPSHOT_NOT_FOUND")
    return current


def show(journey: Journey, snapshot: Mapping[str, object]) -> None:
    twins = modeling.twins(snapshot)
    number = snapshot.get("version_number")
    journey.console.write()
    journey.say("init.twins_heading", count=len(twins), version=number or "-")
    views = personas.views_of(snapshot)
    for index, twin in enumerate(twins, start=1):
        journey.say("init.twin_heading", number=index, total=len(twins), name=modeling.name(twin))
        view = views[str(twin.get("twin_id"))]
        personas.show_claim(
            journey.context, "description", (view.get("persona") or {}).get("description") or {}
        )
        personas.show_declaration(journey.context, view)
        details(journey, twin, TWIN_DETAILS)


def details(
    journey: Journey, version: Mapping[str, object], keys: Sequence[tuple[str, str]]
) -> None:
    grouped: dict[str, list[str]] = {}
    for key, label in keys:
        value = modeling.observation(version, key)
        if isinstance(value, str) and value:
            grouped.setdefault(label, []).append(value)
        elif isinstance(value, list):
            grouped.setdefault(label, []).extend(value)
    for label, values in grouped.items():
        if values:
            journey.console.write(f"  {journey.text(label)}: {'; '.join(values)}")


def _choice(journey: Journey, *, last: bool) -> tuple[str, str | None]:
    if journey.script is not None:
        return modeling.CONFIRM, None
    for _ in range(ATTEMPTS):
        if journey.console.confirm("init.profile_confirm", default=True):
            return modeling.CONFIRM, None
        if last:
            journey.say("init.profile_needed")
            continue
        reason = journey.console.ask(
            "init.profile_reason", default=journey.text("init.profile_reason_default")
        )
        return modeling.REJECT, " ".join(reason.split())[: modeling.MAX_REASON]
    raise CliError("ANSWER_NOT_VALID")
