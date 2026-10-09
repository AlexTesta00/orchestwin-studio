from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs
from orchestwin.cli.api import design as design_api
from orchestwin.cli.api import sections as sections_api
from orchestwin.cli.api import workflow_inputs
from orchestwin.cli.commands import sections as sections_command
from orchestwin.cli.console import Choice
from orchestwin.cli.errors import (
    INTERRUPTED_STATUS,
    NOT_LINKED_STATUS,
    NOT_VERIFIED_STATUS,
    SIGN_IN_STATUS,
    UNREACHABLE_STATUS,
    USAGE_STATUS,
    ApiFailure,
    CliError,
)
from orchestwin.cli.flows import (
    design_change,
    design_choice,
    design_critique,
    design_generate,
    design_recovery,
    design_state,
    previews,
    provided_design,
    review,
)

if TYPE_CHECKING:
    from orchestwin.cli.api.sections import Sections
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.design_state import Alternative, DesignState
    from orchestwin.cli.project import ProjectFolder

NAME = "design"
SHOW: Final = "show"
OPEN: Final = "open"
CHOOSE: Final = "choose"
CHANGE: Final = "change"
REVIEW: Final = "review"
APPROVE: Final = "approve"
REGENERATE: Final = design_recovery.REGENERATE
UPDATE: Final = design_recovery.UPDATE
RESTORE: Final = "restore"
CRITIQUE: Final = "critique"
ACTIONS: Final = (SHOW, OPEN, CHOOSE, CHANGE, REVIEW, APPROVE, REGENERATE, RESTORE, CRITIQUE)
WITH_VALUE: Final = frozenset({OPEN, CHOOSE, CHANGE, RESTORE})
RESTORE_CURRENT: Final = "DESIGN_RESTORE_CURRENT"
VERSION_NOT_FOUND: Final = "DESIGN_VERSION_NOT_FOUND"
RESTORE_BLOCKED: Final = "DESIGN_RESTORE_BLOCKED"
RESTORE_CODES: Final = frozenset({RESTORE_CURRENT, VERSION_NOT_FOUND})
RESTORE_BLOCKS: Final = frozenset({"REQUIREMENT_NO_LONGER_AVAILABLE", "TWIN_SET_CHANGED"})
MOCKUPS: Final = "mockups"
APPLY: Final = "apply"
LEAVE: Final = "leave"
EVERY_SCREEN: Final = "*"
HARD_CODES: Final = frozenset(
    {
        "INPUT_CLOSED",
        "ANSWER_NOT_VALID",
        "SESSION_FILE_LOCKED",
        "GENERATION_STILL_RUNNING",
        "GENERATION_INTERRUPTED",
    }
)
HARD_STATUSES: Final = frozenset(
    {SIGN_IN_STATUS, UNREACHABLE_STATUS, NOT_LINKED_STATUS, NOT_VERIFIED_STATUS, INTERRUPTED_STATUS}
)
HARD_HTTP: Final = frozenset({401, 403, 404})


@dataclass(frozen=True, slots=True)
class Followed:
    reveal: bool
    displayed: bool
    explained: bool


@dataclass(frozen=True, slots=True)
class Options:
    rules: tuple[str, ...] = ()
    aim: design_change.Aim | None = None
    reviewing: bool = True
    elements: bool = False
    screen: str | None = None
    version: int | None = None
    image: str | None = None
    url: str | None = None
    redraw: int | None = None


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "action", nargs="?", choices=ACTIONS, metavar="ACTION", help="design.option_action"
    )
    parser.add_argument("value", nargs="?", metavar="VALUE", help="design.option_value")
    parser.add_argument("--rule", action="append", metavar="TEXT", help="design.option_rule")
    parser.add_argument("--screen", metavar="SCREEN", help="design.option_screen")
    parser.add_argument("--element", metavar="ELEMENT", help="design.option_element")
    parser.add_argument("--no-review", action="store_true", help="design.option_no_review")
    parser.add_argument(
        "--elements",
        nargs="?",
        const=EVERY_SCREEN,
        metavar="SCREEN",
        help="design.option_elements",
    )
    parser.add_argument("--image", metavar="FILE", help="design.option_image")
    parser.add_argument("--url", metavar="ADDRESS", help="design.option_url")
    parser.add_argument(
        "--redraw",
        nargs="?",
        const=design_critique.LATEST,
        metavar="N",
        help="design.option_redraw",
    )


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    action = arguments.action
    value = arguments.value
    rules = list(arguments.rule or [])
    console = context.console
    aimed = arguments.screen is not None or arguments.element is not None
    if rules and action != CHANGE:
        console.error("design.usage_rule")
        return USAGE_STATUS
    if (aimed or arguments.no_review) and action != CHANGE:
        console.error("design.usage_target")
        return USAGE_STATUS
    if arguments.elements is not None and action != SHOW:
        console.error("design.usage_elements")
        return USAGE_STATUS
    critiqued = [
        item for item in (arguments.image, arguments.url, arguments.redraw) if item is not None
    ]
    if critiqued and (action != CRITIQUE or len(critiqued) > 1):
        console.error("design.usage_critique")
        return USAGE_STATUS
    if value is not None and action not in WITH_VALUE:
        console.error("design.usage_value", action=action or NAME)
        return USAGE_STATUS
    if action == CHOOSE and not value:
        console.error("design.usage_code")
        return USAGE_STATUS
    if action == RESTORE and not value:
        console.error("design.usage_restore")
        return USAGE_STATUS
    options = Options(
        rules=tuple(rules),
        aim=design_change.aim_of(arguments.screen, arguments.element),
        reviewing=not arguments.no_review,
        elements=arguments.elements is not None,
        screen=None
        if arguments.elements in (None, EVERY_SCREEN)
        else design_change.screen_code(arguments.elements),
        version=restore_number(value) if action == RESTORE else None,
        image=arguments.image,
        url=arguments.url,
        redraw=None
        if arguments.redraw is None
        else design_critique.critique_number(arguments.redraw),
    )
    project = context.project()
    client = context.client()
    source = (
        None if action == CRITIQUE else workflow_inputs.state(client, project.link().project_id)
    )
    if source is not None and source["source"] == "PROVIDED_PROTOTYPE":
        return provided_design.perform(context, client, project, source, action, value)
    if action is None:
        return guided(context, client, project)
    try:
        return perform(context, client, project, action, value, options)
    except CliError as error:
        if error.code != design_generate.CONTEXT_CHANGED:
            raise
        report_changed(context, client, project, error)
        design_state.show_summary(context, design_state.read_state(client, project))
        return error.status


def perform(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    action: str,
    value: str | None,
    options: Options,
) -> int:
    if action == CRITIQUE:
        return design_critique.run(
            context, client, project, image=options.image, url=options.url, redraw=options.redraw
        )
    state = design_state.read_state(client, project)
    prices = design_generate.Prices(client)
    if state.kind == design_state.REQUIREMENTS_PENDING:
        if action in (SHOW, OPEN):
            heading(context, state)
        say_requirements(context, client, project)
        return 1
    if action == REVIEW:
        recovery = design_recovery.read(client, project, state)
        if recovery.action is not None:
            design_recovery.explain(context, recovery, error=True)
            return 1
        return review.run_review(context, client, project)
    if action == SHOW:
        if options.elements:
            return show_elements(context, client, state, prices, options.screen)
        return show(context, client, project, state, prices)
    if action == OPEN:
        heading(context, state)
        return open_previews(context, project, state, value, prices)
    if blocked(context, state, prices):
        return 1
    recovery = design_recovery.read(client, project, state)
    if action == REGENERATE:
        return 0 if regenerate(context, client, project, state, prices, recovery) is not None else 1
    if recovery.action is not None:
        design_recovery.explain(context, recovery, error=True)
        return 1
    console = context.console
    if action == CHOOSE:
        alternative = find(state, value or "")
        return design_choice.choose(context, client, project, state, alternative, prices)
    if action == CHANGE:
        if prices.modelless(state):
            console.say("design.no_model_change")
            return 1
        return design_change.change(
            context,
            client,
            project,
            state,
            value,
            options.rules,
            aim=options.aim,
            reviewing=options.reviewing,
        )
    if action == RESTORE:
        return restore(context, client, project, state, options.version)
    if state.chosen is None and prices.modelless(state):
        console.say("design.no_model_approve")
        return 1
    return design_choice.approve(context, client, project, state)


def show(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    state: DesignState,
    prices: design_generate.Prices,
) -> int:
    console = context.console
    heading(context, state)
    kind = state.kind
    if kind == design_state.NO_DESIGN:
        say_no_design(context, prices)
        return 0
    if kind == design_state.JOB_RUNNING:
        console.say("design.show_running", names=running_names(context, state))
    modelless = prices.modelless(state)
    state = design_state.with_distance(client, state)
    describe(context, client, project, state, everything=True, modelless=modelless)
    recovery = design_recovery.read(client, project, state)
    if recovery.action is not None:
        design_recovery.explain(context, recovery)
        return 0
    key = next_key(state, prices, modelless)
    if key is not None:
        console.say(key)
    return 0


def next_key(state: DesignState, prices: design_generate.Prices, modelless: bool) -> str | None:
    kind = state.kind
    changeable = design_change.unavailable(state) is None
    if kind == design_state.CHOSEN:
        return "design.next_chosen" if changeable else "design.next_chosen_approve"
    if kind == design_state.APPROVED:
        return "design.next_approved" if changeable else None
    if modelless:
        return None
    if kind == design_state.NO_MOCKUPS and not prices.shown():
        return "design.next_no_mockups_plain"
    if kind == design_state.MOCKUPS_READY and not state.generated:
        return "design.next_choose"
    return f"design.next_{kind.lower()}"


def show_elements(
    context: CommandContext,
    client: StudioClient,
    state: DesignState,
    prices: design_generate.Prices,
    wanted: str | None,
) -> int:
    console = context.console
    heading(context, state)
    if state.kind == design_state.JOB_RUNNING:
        console.say("design.show_running", names=running_names(context, state))
    chosen = state.chosen
    if state.version is None:
        say_no_design(context, prices)
        return 1
    if chosen is None:
        console.say("design.elements_needs_choice")
        return 1
    document = design_state.chosen_mockup(client, state)
    if document is None:
        console.say("design.elements_no_mockup")
        return 1
    screens = design_state.document_screens(document)
    shown = screens if wanted is None else (design_change.find_screen(context, screens, wanted),)
    if not any(screen.elements for screen in screens):
        console.say("design.elements_none")
        return 0
    console.write()
    console.heading(context.text("design.elements_heading", code=chosen.code, title=chosen.title))
    columns = [
        context.text("design.column_code"),
        context.text("design.column_kind"),
        context.text("design.column_text"),
    ]
    for screen in shown:
        console.write(
            context.text("design.elements_screen", code=screen.code, title=screen.title or "-")
        )
        if screen.elements:
            console.table(
                columns, [[item.code, item.kind, item.text or "-"] for item in screen.elements]
            )
        else:
            console.say("design.elements_screen_none")
        console.write()
    example = next((screen for screen in shown if screen.elements), None)
    if example is not None:
        console.say("design.elements_next", screen=example.code, element=example.elements[0].code)
    return 0


def open_previews(
    context: CommandContext,
    project: ProjectFolder,
    state: DesignState,
    value: str | None,
    prices: design_generate.Prices,
) -> int:
    console = context.console
    if state.version is None:
        say_no_design(context, prices)
        return 1
    if not state.generated:
        design_state.show_alternatives(context, state)
        design_state.show_verdicts(context, state)
        design_state.say_without_previews(context, state, modelless=prices.modelless(state))
        return 1
    alternative = None if value is None else find(state, value)
    if alternative is not None and alternative.id not in state.documents:
        if prices.shown():
            console.say("design.open_missing", code=alternative.code)
        else:
            console.say("design.open_missing_plain", code=alternative.code)
        return 1
    index = previews.write_previews(context, project, state)
    console.say("design.previews_written", path=str(index.parent))
    target = index if alternative is None else index.parent / previews.file_name(alternative)
    previews.open_page(context, target)
    return 0


def restore_number(value: str | None) -> int:
    text = (value or "").strip()
    if not (text.isascii() and text.isdigit()) or int(text) < 1:
        raise CliError(
            "DESIGN_RESTORE_NUMBER_INVALID", status=USAGE_STATUS, values={"value": value or ""}
        )
    return int(text)


def restore(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    state: DesignState,
    number: int | None,
) -> int:
    console = context.console
    current = state.version_number
    if number is None or current is None:
        console.error("design.usage_restore")
        return USAGE_STATUS
    numbers = sorted(
        found
        for item in design_api.history(client, state.project_id)
        if isinstance(found := item.get("version_number"), int) and not isinstance(found, bool)
    )
    values = {"version": number, "versions": ", ".join(map(str, numbers)) or "-"}
    if number == current:
        raise CliError(RESTORE_CURRENT, values=values)
    if number not in numbers:
        raise CliError(VERSION_NOT_FOUND, values=values)
    console.say("design.restore_about", version=number, next=current + 1)
    if not context.assume_yes and not console.confirm(
        "design.restore_confirm", default=True, version=number
    ):
        console.say("design.restore_cancelled", version=number)
        return 1
    try:
        version = design_api.restore(
            client, state.project_id, number, review.review_locale(context.language)
        )
    except ApiFailure as failure:
        if failure.code in RESTORE_CODES:
            raise CliError(failure.code, values=values) from None
        if failure.code in RESTORE_BLOCKS:
            raise CliError(RESTORE_BLOCKED, values={**values, "reason": failure.code}) from None
        design_generate.raise_failure(failure)
    fresh = design_state.read_state(client, project)
    if fresh.generated and fresh.documents:
        index = previews.write_previews(context, project, fresh)
        console.say("design.previews_written", path=str(index.parent))
    console.say(
        "design.restored" if version.get("ready_for_gate") is True else "design.restored_choose",
        version=version.get("version_number"),
        restored=number,
    )
    return 0


def guided(context: CommandContext, client: StudioClient, project: ProjectFolder) -> int:
    console = context.console
    first = True
    described = False
    reveal = False
    followed = False
    explained = False
    while True:
        state = design_state.read_state(client, project)
        prices = design_generate.Prices(client)
        if first:
            heading(context, state)
            first = False
        kind = state.kind
        if kind == design_state.REQUIREMENTS_PENDING:
            say_requirements(context, client, project)
            return 1
        if kind == design_state.NO_DESIGN:
            if followed:
                if explained:
                    return 1
                if prices.shown():
                    console.say("design.proposal_missing")
                else:
                    console.say("design.proposal_missing_plain")
                return 1
            try:
                reveal = design_generate.start_design(context, client, project, state, prices)
                described = True
            except CliError as error:
                if error.code != design_generate.CONTEXT_CHANGED:
                    raise
                report_changed(context, client, project, error)
            continue
        if kind == design_state.JOB_RUNNING:
            followed = True
            try:
                outcome = continue_running(context, client, project, state, prices)
            except CliError as error:
                if error.code != design_generate.CONTEXT_CHANGED:
                    raise
                report_changed(context, client, project, error)
            else:
                reveal = reveal or outcome.reveal
                described = described or outcome.displayed
                explained = explained or outcome.explained
            continue
        recovery = design_recovery.read(client, project, state)
        priced = prices.shown()
        subscription = prices.subscription()
        modelless = prices.modelless(state)
        try:
            if reveal and state.documents:
                index = previews.write_previews(context, project, state)
                console.say("design.previews_written", path=str(index.parent))
                previews.open_page(context, index)
            reveal = False
            if described:
                design_state.show_summary(context, state)
            else:
                describe(context, client, project, state, everything=False, modelless=modelless)
                described = True
            design_recovery.explain(context, recovery)
            options = menu(
                context, state, priced, modelless, subscription=subscription, recovery=recovery
            )
            if len(options) == 1:
                return 0
            console.write()
            choice = console.choose("design.menu", options)
            if choice.key == LEAVE:
                return 0
            reveal = act(context, client, project, state, choice.key, prices)
        except CliError as error:
            if not recoverable(error):
                raise
            if error.code == design_generate.CONTEXT_CHANGED:
                report_changed(context, client, project, error)
            else:
                report(context, error)


def describe(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    state: DesignState,
    *,
    everything: bool,
    modelless: bool = False,
) -> None:
    design_state.show_state(context, state, everything=everything, modelless=modelless)
    if state.review is not None and state.version is not None:
        review.show_review(context, state.review, state.version)
    if state.pending_change is not None:
        say_pending(context, state)
    if state.kind == design_state.APPROVED:
        design_state.show_folder(context, client, project, state)


def act(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    state: DesignState,
    key: str,
    prices: design_generate.Prices,
) -> bool:
    console = context.console
    if key == REGENERATE:
        recovery = design_recovery.read(client, project, state)
        return regenerate(context, client, project, state, prices, recovery) or False
    if key == UPDATE:
        recovery = design_recovery.read(client, project, state)
        if recovery.action == UPDATE and recovery.sections is not None:
            sections_command.update(context, client, project, recovery.sections)
        else:
            design_recovery.explain(context, recovery)
        return False
    if key != OPEN:
        recovery = design_recovery.read(client, project, state)
        if recovery.action is not None:
            design_recovery.explain(context, recovery, error=True)
            return False
    if key == MOCKUPS:
        return design_generate.draw_missing(context, client, state, prices)
    if key == OPEN:
        open_previews(context, project, state, None, prices)
    elif key == CHOOSE:
        alternative = ask_alternative(context, state)
        design_choice.choose(context, client, project, state, alternative, prices)
    elif key == CHANGE:
        text = console.ask_text("design.change_ask")
        if not text.strip():
            console.say("design.change_cancelled")
            return False
        rules = console.ask_text("design.rules_ask")
        lines = [line for line in rules.splitlines() if line.strip()]
        design_change.change(context, client, project, state, text, lines)
    elif key == REVIEW:
        review.run_review(context, client, project)
    elif key == APPROVE:
        design_choice.approve(context, client, project, state)
    elif key == APPLY:
        design_change.apply_pending(context, client, project, state)
    return False


def regenerate(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    state: DesignState,
    prices: design_generate.Prices,
    recovery: design_recovery.Recovery,
) -> bool | None:
    blocker = design_recovery.regeneration_block(
        recovery.sections, state
    ) or design_recovery.pending_revision(client, state)
    if blocker is not None:
        design_recovery.explain(
            context,
            design_recovery.Recovery(recovery.sections, design_recovery.BLOCKED, blocker),
            error=True,
        )
        return None
    if prices.modelless(state):
        context.console.say("design.no_model_regenerate")
        return None
    context.console.say("design.regenerate_explicit")
    return design_generate.start_design(
        context,
        client,
        project,
        state,
        prices,
        route=design_api.regenerations_path(state.project_id),
    )


def continue_running(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    state: DesignState,
    prices: design_generate.Prices,
) -> Followed:
    reveal = False
    displayed = False
    explained = False
    for outcome in design_generate.follow_running(context, client, state):
        operation = outcome.tracked.operation
        if operation == "MOCKUP":
            design_generate.report_mockup(context, state, outcome, prices)
            reveal = reveal or outcome.status == design_generate.SUCCEEDED
        elif operation == "ITERATION":
            design_change.finish_followed(context, client, project, state, outcome)
            displayed = True
        elif operation == review.REVIEW:
            if state.version is not None and outcome.status == design_generate.SUCCEEDED:
                review.show_review(context, review.finished_run(outcome), state.version)
                displayed = True
            else:
                design_generate.report_job(context, outcome)
        elif outcome.status != design_generate.SUCCEEDED:
            explained = design_generate.report_job(context, outcome) or explained
    return Followed(reveal=reveal, displayed=displayed, explained=explained)


def menu(
    context: CommandContext,
    state: DesignState,
    priced: bool,
    modelless: bool = False,
    *,
    subscription: bool = False,
    recovery: design_recovery.Recovery | None = None,
) -> list[Choice]:
    text = context.text
    kind = state.kind
    waiting = kind in (design_state.NO_MOCKUPS, design_state.MOCKUPS_READY)
    reviewable = not modelless or state.capabilities.static_check
    options: list[Choice] = []
    if state.generated and state.documents:
        options.append(Choice(OPEN, text("design.menu_open")))
    if recovery is not None and recovery.action is not None:
        if recovery.action == REGENERATE and not modelless:
            operations = ["DESIGN_PROPOSAL"]
            minutes = None
            if state.generated:
                operations.extend(["MOCKUP", "MOCKUP"])
                minutes = (
                    costs.ESTIMATES["DESIGN_PROPOSAL"].minutes + costs.ESTIMATES["MOCKUP"].minutes
                )
            label = with_estimate(
                context,
                priced,
                text("design.menu_regenerate"),
                operations,
                minutes=minutes,
                subscription=subscription,
            )
            options.append(Choice(REGENERATE, label))
        elif recovery.action == UPDATE:
            options.append(Choice(UPDATE, text("design.menu_update_sections")))
        options.append(Choice(LEAVE, text("design.menu_leave")))
        return options
    if waiting and state.choosable() and not modelless:
        label = with_estimate(
            context,
            priced,
            text("design.menu_choose"),
            [review.REVIEW],
            subscription=subscription,
        )
        options.append(Choice(CHOOSE, label))
    missing = state.missing_mockups()
    if waiting and missing:
        codes = ", ".join(item.code for item in missing)
        label = with_estimate(
            context,
            priced,
            text("design.menu_mockups", codes=codes),
            ["MOCKUP"] * len(missing),
            minutes=costs.ESTIMATES["MOCKUP"].minutes,
            subscription=subscription,
        )
        options.append(Choice(MOCKUPS, label))
    if state.pending_change is not None:
        options.append(Choice(APPLY, text("design.menu_apply", request=pending_request(state))))
    if (
        kind in (design_state.CHOSEN, design_state.APPROVED)
        and design_change.unavailable(state) is None
    ):
        label = with_estimate(
            context,
            priced,
            text("design.menu_change"),
            [design_change.ITERATION, review.REVIEW],
            subscription=subscription,
        )
        options.append(Choice(CHANGE, label))
    if kind == design_state.CHOSEN:
        if state.review is None and reviewable:
            label = with_estimate(
                context,
                priced,
                text("design.menu_review"),
                [review.REVIEW],
                subscription=subscription,
            )
            options.append(Choice(REVIEW, label))
        options.append(Choice(APPROVE, text("design.menu_approve")))
        if state.choosable() and not modelless:
            label = with_estimate(
                context,
                priced,
                text("design.menu_choose_other"),
                [review.REVIEW],
                subscription=subscription,
            )
            options.append(Choice(CHOOSE, label))
    options.append(Choice(LEAVE, text("design.menu_leave")))
    return options


def with_estimate(
    context: CommandContext,
    priced: bool,
    label: str,
    operations: Sequence[str],
    *,
    minutes: float | None = None,
    subscription: bool = False,
) -> str:
    if not priced and not subscription:
        return label
    estimate = design_generate.estimate_text(
        context, operations, minutes=minutes, subscription=subscription
    )
    return context.text("design.priced", label=label, estimate=estimate)


def ask_alternative(context: CommandContext, state: DesignState) -> Alternative:
    options = [
        Choice(item.code, context.text("design.choice_label", code=item.code, title=item.title))
        for item in state.choosable()
    ]
    picked = context.console.choose("design.choose_which", options)
    return find(state, picked.key)


def find(state: DesignState, value: str) -> Alternative:
    alternative = state.find(value)
    if alternative is None:
        codes = ", ".join(item.code for item in state.alternatives) or "-"
        raise CliError(
            "DESIGN_CODE_UNKNOWN", status=USAGE_STATUS, values={"code": value, "codes": codes}
        )
    return alternative


def blocked(context: CommandContext, state: DesignState, prices: design_generate.Prices) -> bool:
    console = context.console
    kind = state.kind
    if kind == design_state.NO_DESIGN:
        say_no_design(context, prices)
    elif kind == design_state.JOB_RUNNING:
        console.say("design.wait_running", names=running_names(context, state))
    else:
        return False
    return True


def say_no_design(context: CommandContext, prices: design_generate.Prices) -> None:
    if prices.shown():
        context.console.say("design.no_design_yet")
    else:
        context.console.say("design.no_design_yet_plain")


def say_requirements(context: CommandContext, client: StudioClient, project: ProjectFolder) -> None:
    console = context.console
    found = design_sections(client, project)
    definition = None if found is None else found.section(sections_api.REQUIREMENTS)
    if found is None or definition is None or not definition.behind:
        console.say("design.requirements_pending")
        return
    lines = [] if found.alignment.available else sections_command.blocked_lines(context, found)
    if lines:
        console.say("design.definition_blocked", blocked=" ".join(lines))
    else:
        console.say("design.definition_behind")


def running_names(context: CommandContext, state: DesignState) -> str:
    return ", ".join(design_generate.track(context, state, job).name for job in state.running)


def pending_request(state: DesignState) -> str:
    request = None if state.pending_change is None else state.pending_change.get("request")
    return request if isinstance(request, str) and request else "-"


def say_pending(context: CommandContext, state: DesignState) -> None:
    context.console.say("design.pending_change", request=pending_request(state))


def heading(context: CommandContext, state: DesignState) -> None:
    context.console.heading(context.text("design.heading", project=state.project_name))


def recoverable(error: CliError) -> bool:
    if error.code in HARD_CODES or error.status in HARD_STATUSES:
        return False
    return not (isinstance(error, ApiFailure) and error.http_status in HARD_HTTP)


def report(context: CommandContext, error: CliError) -> None:
    from orchestwin.cli.main import report_error

    report_error(context.console, error, NAME)


def report_changed(
    context: CommandContext, client: StudioClient, project: ProjectFolder, error: CliError
) -> None:
    console = context.console
    found = design_sections(client, project)
    design = None if found is None else found.section(sections_api.DESIGN)
    if found is None or design is None or not design.behind:
        console.error("design.errors.DESIGN_CONTEXT_CHANGED", **error.values)
    elif design.blocked is None:
        console.error("design.behind")
    else:
        blocked = sections_command.blocked_text(
            context,
            design.stage,
            sections_api.block_of(design.blocked),
            design.blocked,
            design.codes,
            None,
        )
        console.error("design.behind_blocked", blocked=blocked)


def design_sections(client: StudioClient, project: ProjectFolder) -> Sections | None:
    return sections_api.sections(client, project.link().project_id)
