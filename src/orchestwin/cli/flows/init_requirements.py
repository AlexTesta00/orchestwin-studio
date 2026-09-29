from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs
from orchestwin.cli.api import requirements as requirements_api
from orchestwin.cli.api.projects import approves
from orchestwin.cli.console import Choice
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.flows.answers import APPROVE

if TYPE_CHECKING:
    from orchestwin.cli.commands.init import Journey

STAGE: Final = "requirements"
OPERATION: Final = "REQUIREMENTS_PROPOSAL"
CHANGE_OPERATION: Final = "REQUIREMENTS_CHANGE"
ATTEMPTS: Final = 5
VERIFICATIONS: Final = (
    "AUTOMATED_TEST",
    "MANUAL_REVIEW",
    "INSPECTION",
    "DEMONSTRATION",
    "ANALYSIS",
)


@dataclass(frozen=True, slots=True)
class RequirementsState:
    approved: bool
    version: Mapping[str, object] | None
    gate: Mapping[str, object] | None

    @property
    def number(self) -> int | None:
        return _number(self.version)


def read(journey: Journey) -> RequirementsState:
    readiness = requirements_api.readiness(journey.client, journey.project_id)
    version = _mapping(readiness.get("version"))
    gate = _mapping(readiness.get("gate"))
    approved = (
        readiness.get("status") == requirements_api.READY
        and version is not None
        and gate is not None
        and approves(gate, version)
    )
    if approved and version is not None and gate is not None:
        journey.keep(STAGE, version, gate)
    return RequirementsState(approved=approved, version=version, gate=gate)


def run(journey: Journey, state: RequirementsState) -> bool:
    version = state.version
    if version is None:
        journey.say("init.requirements_wait")
        _, document = journey.job(
            requirements_api.proposals_path(journey.project_id),
            operation=OPERATION,
            label=journey.text("init.requirements_label"),
        )
        version = _mapping(document.get("version") if isinstance(document, Mapping) else None)
        version = version or requirements_api.current(journey.client, journey.project_id)
        if version is None:
            raise journey.changed("REQUIREMENTS_SPECIFICATION_NOT_FOUND")
    waiting = requirements_api.pending_revision(
        requirements_api.revisions(journey.client, journey.project_id), version
    )
    if waiting is not None:
        journey.say("init.change_waiting")
        version = decide(journey, waiting, version)
    planned = list(journey.script.changes) if journey.script is not None else []
    while True:
        summary(journey, version)
        request: str | None = None
        if journey.script is not None:
            if planned:
                action, request = "change", planned.pop(0)
            else:
                action = "approve" if journey.script.requirements == APPROVE else "stop"
        else:
            action = journey.console.choose(
                "init.requirements_choice",
                [
                    Choice("approve", journey.text("init.requirements_approve")),
                    Choice("read", journey.text("init.requirements_read")),
                    Choice("change", journey.text("init.requirements_change")),
                    Choice("stop", journey.text("init.requirements_stop")),
                ],
            ).key
        if action == "stop":
            journey.say("init.requirements_left")
            return False
        if action == "read":
            everything(journey, version)
            continue
        if action == "change":
            version = change(journey, version, request)
            continue
        gate = journey.approve(
            lambda: requirements_api.submit_gate(journey.client, journey.project_id),
            lambda: requirements_api.decide_gate(journey.client, journey.project_id),
            step=STAGE,
        )
        journey.conclude(STAGE, version, gate)
        return True


def change(
    journey: Journey, version: Mapping[str, object], request: str | None
) -> Mapping[str, object]:
    if request is None:
        request = _request(journey)
        if request is None:
            journey.say("init.change_cancelled")
            return version
        costs.confirm_spending(journey.context, journey.client, [CHANGE_OPERATION])
    else:
        journey.say("init.change_scripted", request=request)
    status, document = journey.job(
        requirements_api.change_path(journey.project_id),
        requirements_api.change_body(request),
        operation=CHANGE_OPERATION,
        label=journey.text("init.change_label"),
        passthrough=(requirements_api.UNCHANGED,),
    )
    if status >= 400:
        journey.say("init.change_unchanged")
        return version
    diff = _mapping(document.get("diff") if isinstance(document, Mapping) else None)
    if diff is None:
        raise ApiFailure("API_FAILURE", http_status=status, detail=document)
    return decide(journey, diff, version)


def decide(
    journey: Journey, diff: Mapping[str, object], version: Mapping[str, object]
) -> Mapping[str, object]:
    show_diff(journey, diff)
    if journey.script is not None:
        apply = True
    else:
        apply = journey.console.confirm("init.change_apply", default=True)
    status, document = requirements_api.decide(
        journey.client,
        journey.project_id,
        str(diff.get("id")),
        requirements_api.APPROVE if apply else requirements_api.REJECT,
        None if apply else journey.text("init.change_reason"),
    )
    if status >= 400:
        raise journey.refused(status, document)
    if not apply:
        journey.say("init.change_discarded", version=_number(version) or "-")
        return version
    found = _mapping(document.get("version") if isinstance(document, Mapping) else None)
    found = found or requirements_api.current(journey.client, journey.project_id) or version
    journey.say("init.change_applied", version=_number(found) or "-")
    return found


def summary(journey: Journey, version: Mapping[str, object]) -> None:
    items = requirements_api.entries(version, "requirements")
    journey.console.write()
    journey.say(
        "init.requirements_heading",
        version=_number(version) or "-",
        requirements=len(items),
        stories=len(requirements_api.entries(version, "user_stories")),
        criteria=len(requirements_api.entries(version, "acceptance_criteria")),
    )
    journey.console.table(
        [
            journey.text("init.column_code"),
            journey.text("init.column_title"),
            journey.text("init.column_priority"),
        ],
        [
            [str(item.get("code") or ""), str(item.get("title") or ""), _priority(journey, item)]
            for item in items
        ],
    )


def everything(journey: Journey, version: Mapping[str, object]) -> None:
    console = journey.console
    console.write()
    console.heading(journey.text("init.all_requirements"))
    for item in requirements_api.entries(version, "requirements"):
        console.write(
            journey.text(
                "init.requirement_line",
                code=item.get("code") or "",
                title=item.get("title") or "",
                priority=_priority(journey, item),
                kind=_kind(journey, item),
            )
        )
        console.write(f"  {item.get('statement') or ''}")
    console.write()
    console.heading(journey.text("init.all_stories"))
    for item in requirements_api.entries(version, "user_stories"):
        twin = item.get("user_twin_reference")
        name = twin.get("name") if isinstance(twin, Mapping) else None
        console.write(
            journey.text(
                "init.story_line",
                code=item.get("code") or "",
                twin=name or journey.text("init.story_someone"),
                goal=item.get("goal") or "",
                benefit=item.get("benefit") or "",
            )
        )
    console.write()
    console.heading(journey.text("init.all_criteria"))
    for item in requirements_api.entries(version, "acceptance_criteria"):
        console.write(f"{item.get('code') or ''} {item.get('statement') or ''}")
        method = item.get("verification_method")
        if method in VERIFICATIONS:
            console.write(
                "  "
                + journey.text(
                    "init.criterion_check",
                    method=journey.text(f"init.verify_{str(method).lower()}"),
                )
            )


def show_diff(journey: Journey, diff: Mapping[str, object]) -> None:
    operations = requirements_api.operations(diff)
    journey.console.write()
    journey.say("init.change_heading", count=len(operations))
    for operation in operations:
        kind = str(operation.get("artifact_kind"))
        action = str(operation.get("operation"))
        envelope = operation.get("before") if action == "REMOVE" else operation.get("after")
        artifact = requirements_api.artifact(envelope) or {}
        what = (
            journey.text(f"init.artifact_{kind.lower()}")
            if kind in requirements_api.ARTIFACT_KINDS
            else kind
        )
        verb_key = (
            f"init.change_{action.lower()}"
            if action in requirements_api.OPERATIONS
            else "init.change_other"
        )
        journey.console.write(
            "  "
            + journey.text(
                verb_key,
                what=what,
                code=operation.get("display_code") or "",
                text=_describe(artifact),
            )
        )


def _describe(artifact: Mapping[str, object]) -> str:
    title = artifact.get("title")
    for key in ("statement", "goal", "summary", "expected_outcome"):
        value = artifact.get(key)
        if isinstance(value, str) and value:
            return f"{title}: {value}" if isinstance(title, str) and title else value
    return title if isinstance(title, str) else ""


def _request(journey: Journey) -> str | None:
    for _ in range(ATTEMPTS):
        lines = [
            line.strip() for line in journey.console.ask_text("init.change_request").splitlines()
        ]
        text = "\n".join(line for line in lines if line)
        if not text:
            return None
        if len(text) <= requirements_api.MAX_REQUEST:
            return text
        journey.say("init.answer_too_long", limit=requirements_api.MAX_REQUEST)
    raise CliError("ANSWER_NOT_VALID")


def _priority(journey: Journey, item: Mapping[str, object]) -> str:
    value = item.get("priority")
    if value in requirements_api.PRIORITIES:
        return journey.text(f"init.priority_{str(value).lower()}")
    return str(value or "")


def _kind(journey: Journey, item: Mapping[str, object]) -> str:
    value = item.get("kind")
    if value in requirements_api.KINDS:
        return journey.text(f"init.kind_{str(value).lower()}")
    return str(value or "")


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _number(version: Mapping[str, object] | None) -> int | None:
    value = None if version is None else version.get("version_number")
    return value if isinstance(value, int) and not isinstance(value, bool) else None
