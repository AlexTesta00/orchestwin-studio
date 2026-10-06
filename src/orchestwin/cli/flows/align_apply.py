from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs, jobs
from orchestwin.cli.api import alignment as alignment_api
from orchestwin.cli.api import design as design_api
from orchestwin.cli.api import requirements as requirements_api
from orchestwin.cli.console import Choice, selected_choice
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.flows import (
    align_knowledge,
    design_choice,
    design_state,
    init_requirements,
    test_plan,
    verify_decision,
    verify_review,
)
from orchestwin.cli.flows.verify_decision import (
    ENDING_CODES,
    ENDING_STATUSES,
    UNRECORDABLE,
    edit_request,
    report,
)

if TYPE_CHECKING:
    from orchestwin.cli.commands.init import Journey
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.verify_review import Titles, Workspace

APPLY: Final = "apply"
EDIT: Final = "edit"
SKIP: Final = "skip"
LATER: Final = "later"
ORDER: Final = (APPLY, EDIT, SKIP, LATER)
LABELS: Final[Mapping[str, str]] = {
    APPLY: "align.choice_apply",
    EDIT: "align.choice_edit",
    SKIP: "align.choice_skip",
    LATER: "align.choice_later",
}
ATTEMPTS: Final = 5
REQUIREMENTS_STAGE: Final = "requirements"
SPENDING_REFUSED: Final = "SPENDING_REFUSED"


@dataclass(slots=True)
class Outcome:
    applied: int = 0
    skipped: int = 0
    approved: bool = False
    status: int = 0


def decide_all(
    context: CommandContext,
    workspace: Workspace,
    proposals: Sequence[Mapping[str, object]],
    *,
    names: Titles,
    lines: Mapping[str, str],
    show: bool,
) -> Outcome:
    outcome = Outcome()
    for proposal in alignment_api.by_section(proposals):
        if alignment_api.status_of(proposal) != alignment_api.PROPOSED:
            continue
        decide_one(context, workspace, proposal, outcome, names=names, lines=lines, show=show)
    return outcome


def decide_one(
    context: CommandContext,
    workspace: Workspace,
    proposal: Mapping[str, object],
    outcome: Outcome,
    *,
    names: Titles,
    lines: Mapping[str, str],
    show: bool,
) -> None:
    console = context.console
    code = alignment_api.code_of(proposal)
    if show:
        align_knowledge.show_proposal(context, proposal, names, lines)
    console.write()
    console.heading(
        context.text(
            "align.decision_heading", code=code, title=alignment_api.text_of(proposal, "title")
        )
    )
    choice = menu(context, [Choice(key, context.text(LABELS[key])) for key in ORDER])
    if choice.key == LATER:
        console.say("align.decided_later")
        return
    if choice.key == SKIP:
        skip(context, workspace, proposal, outcome)
        return
    text = None
    if choice.key == EDIT:
        section = alignment_api.section_of(proposal)
        limit = alignment_api.MAX_REQUEST.get(
            section, alignment_api.MAX_REQUEST[alignment_api.TESTS]
        )
        text = edit_request(
            context,
            alignment_api.text_of(proposal, "request"),
            heading="align.request_heading",
            limit=limit,
        )
        if text is None:
            console.say("align.decided_later")
            return
    apply(context, workspace, proposal, text, outcome)


def menu(context: CommandContext, options: Sequence[Choice]) -> Choice:
    console = context.console
    console.say("align.decision_question")
    for number, option in enumerate(options, start=1):
        console.write(f"  {number}. {option.label}")
    default = str(len(options))
    for _ in range(ATTEMPTS):
        selected = selected_choice(console.ask("common.choose_prompt", default=default), options)
        if selected is not None:
            return selected
        console.say("common.choice_invalid")
    raise CliError("ANSWER_NOT_VALID")


def skip(
    context: CommandContext,
    workspace: Workspace,
    proposal: Mapping[str, object],
    outcome: Outcome,
) -> None:
    console = context.console
    code = alignment_api.code_of(proposal)
    reason = console.ask("align.skip_reason", required=False)
    try:
        alignment_api.skip(workspace.client, workspace.project_id, code, reason)
    except ApiFailure as failure:
        if failure.code != alignment_api.PROPOSAL_DECIDED:
            raise
        console.say("align.already_decided", code=code)
        return
    outcome.skipped += 1
    console.say("align.skipped", code=code)


def apply(
    context: CommandContext,
    workspace: Workspace,
    proposal: Mapping[str, object],
    text: str | None,
    outcome: Outcome,
) -> None:
    console = context.console
    code = alignment_api.code_of(proposal)
    section = alignment_api.section_of(proposal)
    body = alignment_api.apply_body(verify_review.locale(context, workspace.project), text)
    if section == alignment_api.TESTS:
        apply_tests(context, workspace, code, body, outcome)
        return
    operation = alignment_api.APPLY_OPERATIONS.get(section)
    if operation is None:
        raise ApiFailure("API_FAILURE", http_status=200)
    try:
        costs.confirm_spending(context, workspace.client, [operation])
    except CliError as error:
        if error.code != SPENDING_REFUSED:
            raise
        report(context, error, "align")
        console.say("align.decided_later")
        outcome.status = error.status
        return
    result = jobs.generate(
        context,
        workspace.client,
        workspace.project_id,
        alignment_api.apply_path(workspace.project_id, code),
        body,
        label=context.text("align.apply_label", code=code),
        limit_seconds=align_knowledge.LIMIT_SECONDS,
    )
    if result.status_code >= 400:
        refused(context, workspace, code, result.status_code, result.body, operation, outcome)
        return
    answer = result.body if isinstance(result.body, Mapping) else {}
    decided = alignment_api.proposal_of(answer)
    revision = answer.get("revision")
    outcome.applied += 1
    console.say("align.applied", code=code)
    if section == alignment_api.REQUIREMENTS:
        requirements_follow_up(context, workspace, revision, outcome)
    else:
        design_follow_up(context, workspace, decided, revision, outcome)


def refused(
    context: CommandContext,
    workspace: Workspace,
    code: str,
    status: int,
    body: object,
    operation: str,
    outcome: Outcome,
) -> None:
    console = context.console
    failure = verify_review.failure_of(status, body)
    if failure.code == alignment_api.PROPOSAL_DECIDED:
        console.say("align.already_decided", code=code)
        return
    if alignment_api.pending_code(failure.code):
        console.say("align.revision_pending")
        return
    if alignment_api.unchanged_code(failure.code):
        console.say("align.unchanged")
        return
    error = align_knowledge.refusal(context, workspace, status, body, operation)
    if error.status in UNRECORDABLE or error.code in ENDING_CODES:
        raise error
    report(context, error, "align")
    console.say("align.decided_later")
    outcome.status = error.status


def apply_tests(
    context: CommandContext,
    workspace: Workspace,
    code: str,
    body: Mapping[str, object],
    outcome: Outcome,
) -> None:
    console = context.console
    try:
        answer = alignment_api.apply(workspace.client, workspace.project_id, code, body)
    except ApiFailure as failure:
        if failure.code != alignment_api.PROPOSAL_DECIDED:
            raise
        console.say("align.already_decided", code=code)
        return
    decided = alignment_api.proposal_of(answer)
    request = alignment_api.text_of(decided, "applied_text") or alignment_api.text_of(
        decided, "request"
    )
    test_plan.mark_redo(
        workspace.project, [{"code": code, "request": request}], written_at=now_text(context)
    )
    outcome.applied += 1
    console.say("align.applied", code=code)
    console.say("align.tests_marked")


def requirements_follow_up(
    context: CommandContext,
    workspace: Workspace,
    revision: object,
    outcome: Outcome,
) -> None:
    from orchestwin.cli.commands.init import Journey

    console = context.console
    client, project, project_id = workspace.client, workspace.project, workspace.project_id
    diff = revision.get("diff") if isinstance(revision, Mapping) else None
    if not isinstance(diff, Mapping):
        raise ApiFailure("API_FAILURE", http_status=200)
    version = requirements_api.current(client, project_id) or {}
    journey = Journey(context, client, project, script=None, until=None, idea=None)
    try:
        updated = init_requirements.decide(journey, diff, version)
    except CliError as error:
        if error.code in ENDING_CODES or error.status in UNRECORDABLE:
            raise
        report(context, error, "init")
        console.say("align.revision_left")
        outcome.status = error.status
        return
    if updated.get("id") == version.get("id"):
        return
    number = updated.get("version_number") or "-"
    if not console.confirm("align.requirements_approve", default=True, version=number):
        console.say("align.requirements_left", version=number)
        return
    approve_requirements(context, workspace, journey, updated, outcome)


def approve_requirements(
    context: CommandContext,
    workspace: Workspace,
    journey: Journey,
    updated: Mapping[str, object],
    outcome: Outcome,
) -> None:
    client, project_id = workspace.client, workspace.project_id
    try:
        gate = journey.approve(
            lambda: requirements_api.submit_gate(client, project_id),
            lambda: requirements_api.decide_gate(client, project_id),
            step=REQUIREMENTS_STAGE,
        )
    except CliError as error:
        if error.status in ENDING_STATUSES or error.code in ENDING_CODES:
            raise
        report(context, error, "init")
        outcome.status = error.status
        return
    journey.conclude(REQUIREMENTS_STAGE, updated, gate)
    outcome.approved = True
    verify_decision.realign_design(context, workspace)
    verify_decision.recheck_hint(context, workspace)


def design_follow_up(
    context: CommandContext,
    workspace: Workspace,
    decided: Mapping[str, object],
    revision: object,
    outcome: Outcome,
) -> None:
    console = context.console
    client, project_id = workspace.client, workspace.project_id
    payload = revision if isinstance(revision, Mapping) else {}
    align_knowledge.show_changes(context, alignment_api.texts(payload.get("changes")))
    diff_id = diff_id_of(decided, payload)
    if diff_id is None:
        raise ApiFailure("API_FAILURE", http_status=200)
    if not console.confirm("align.design_approve", default=True):
        console.say("align.design_left")
        return
    try:
        answer = design_api.decide_revision(client, project_id, diff_id)
    except ApiFailure as failure:
        if failure.status in UNRECORDABLE:
            raise
        report(context, failure, "design")
        console.say("align.design_left")
        outcome.status = failure.status
        return
    version = answer.get("version")
    number = version.get("version_number") if isinstance(version, Mapping) else None
    console.say("align.design_revised", version="-" if number is None else number)
    approve_design(context, workspace, outcome)


def approve_design(context: CommandContext, workspace: Workspace, outcome: Outcome) -> None:
    client, project = workspace.client, workspace.project
    fresh = design_state.read_state(client, project)
    if fresh.chosen is None or fresh.version is None or fresh.approved:
        return
    try:
        approval = design_choice.approve(context, client, project, fresh)
    except CliError as error:
        if error.status in ENDING_STATUSES or error.code in ENDING_CODES:
            raise
        report(context, error, "design")
        outcome.status = error.status
        return
    if approval == 0:
        outcome.approved = True
        verify_decision.recheck_hint(context, workspace)
        return
    outcome.status = outcome.status or approval


def diff_id_of(decided: Mapping[str, object], payload: Mapping[str, object]) -> str | None:
    found = decided.get("applied_diff_id")
    if isinstance(found, str) and found:
        return found
    inner = payload.get("revision")
    diff = inner.get("diff") if isinstance(inner, Mapping) else None
    identifier = diff.get("id") if isinstance(diff, Mapping) else None
    return identifier if isinstance(identifier, str) and identifier else None


def now_text(context: CommandContext) -> str:
    return context.environment.now().isoformat(timespec="seconds")
