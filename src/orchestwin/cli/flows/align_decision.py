from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs
from orchestwin.cli.api import changes as changes_api
from orchestwin.cli.api import requirements as requirements_api
from orchestwin.cli.api import sections as sections_api
from orchestwin.cli.api import tasks as tasks_api
from orchestwin.cli.commands import sections as sections_command
from orchestwin.cli.console import Choice, selected_choice
from orchestwin.cli.errors import (
    INTERRUPTED_STATUS,
    SIGN_IN_STATUS,
    UNREACHABLE_STATUS,
    ApiFailure,
    CliError,
)
from orchestwin.cli.flows import changes as git
from orchestwin.cli.flows import (
    design_change,
    design_choice,
    design_state,
    init_requirements,
    task_selection,
)
from orchestwin.cli.flows.align_review import project_text
from orchestwin.cli.flows.design_state import bullets, wrapped
from orchestwin.cli.flows.publish import publish_and_pull

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.align_review import Workspace
    from orchestwin.cli.flows.task_selection import Candidate

ATTEMPTS: Final = 5
DROP: Final = "-"
REQUIREMENTS_STAGE: Final = "requirements"
REQUIREMENTS_OPERATION: Final = "REQUIREMENTS_CHANGE"
LATER: Final = "later"
MARK: Final = "aligned"
TASKS: Final = "tasks"
MODEL_TASKS: Final = "model_tasks"
DESIGN: Final = "design"
REQUIREMENTS: Final = "requirements"
LABELS: Final[Mapping[str, str]] = {
    LATER: "align.choice_later",
    TASKS: "align.choice_tasks",
    MODEL_TASKS: "align.choice_model_tasks",
    DESIGN: "align.choice_design_follow",
    REQUIREMENTS: "align.choice_requirements_follow",
}
OWN_LABELS: Final[Mapping[tuple[str, str], str]] = {
    (DESIGN, changes_api.DESIGN_OUTDATED): "align.choice_design",
    (REQUIREMENTS, changes_api.REQUIREMENTS_OUTDATED): "align.choice_requirements",
}
MENUS: Final[Mapping[str, tuple[str, ...]]] = {
    changes_api.ALIGNED: (MARK, TASKS, DESIGN, REQUIREMENTS, LATER),
    changes_api.DESIGN_OUTDATED: (DESIGN, MARK, TASKS, REQUIREMENTS, LATER),
    changes_api.REQUIREMENTS_OUTDATED: (REQUIREMENTS, MARK, TASKS, DESIGN, LATER),
    changes_api.CODE_DRIFT: (MODEL_TASKS, MARK, DESIGN, REQUIREMENTS, LATER),
}
NOT_STARTED: Final = frozenset(
    {
        "SPENDING_REFUSED",
        "CHANGE_EMPTY",
        "CHANGE_TOO_LONG",
        "CHANGE_NOT_VALID",
        "RULE_NOT_VALID",
        "TOO_MANY_NEW_RULES",
        "TOO_MANY_RULES",
    }
)
UNRECORDABLE: Final = frozenset({SIGN_IN_STATUS, UNREACHABLE_STATUS})
ENDING_STATUSES: Final = frozenset({SIGN_IN_STATUS, UNREACHABLE_STATUS, INTERRUPTED_STATUS})
INPUT_CLOSED: Final = "INPUT_CLOSED"
ENDING_CODES: Final = frozenset({INPUT_CLOSED, "ANSWER_NOT_VALID"})
PUBLISHED_AFTER: Final = frozenset({changes_api.ALIGNED, changes_api.CODE_TASKS})


@dataclass(frozen=True, slots=True)
class Chosen:
    texts: tuple[str, ...] = ()
    findings: tuple[Mapping[str, object], ...] = ()
    before: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Reviewed:
    commit: str
    line: str
    run: Mapping[str, object]

    @property
    def verdict(self) -> str | None:
        return changes_api.run_status(self.run)

    @property
    def alignment(self) -> Mapping[str, object]:
        return changes_api.run_alignment(self.run)


def decide(context: CommandContext, workspace: Workspace, items: Sequence[Reviewed]) -> int:
    if not items:
        return 0
    newest = items[-1]
    kind, status = decide_one(context, workspace, newest)
    recorded = {kind} if kind is not None else set()
    if kind is not None:
        for item in items[:-1]:
            if item.verdict != newest.verdict:
                other, other_status = decide_one(context, workspace, item)
                if other is not None:
                    recorded.add(other)
                status = status or other_status
                continue
            note = project_text(
                context, workspace, "align.covered_note", commit=git.short(newest.commit)
            )
            record(workspace, item.commit, changes_api.DISMISSED, note=note)
            context.console.say(
                "align.dismissed",
                commit=git.short(item.commit),
                newest=git.short(newest.commit),
            )
    if recorded & PUBLISHED_AFTER:
        refresh_folder(context, workspace)
    return status


def decide_one(
    context: CommandContext, workspace: Workspace, item: Reviewed
) -> tuple[str | None, int]:
    console = context.console
    console.write()
    console.heading(
        context.text("align.decision_heading", commit=git.short(item.commit), line=item.line)
    )
    keys = MENUS.get(item.verdict or "", MENUS[changes_api.ALIGNED])
    choice = menu(context, [Choice(key, context.text(_label(key, item.verdict))) for key in keys])
    if choice.key == LATER:
        console.say("align.decided_later")
        return None, 0
    if choice.key == MARK:
        record(workspace, item.commit, changes_api.ALIGNED)
        console.say("align.decided_aligned", commit=git.short(item.commit))
        return changes_api.ALIGNED, 0
    if choice.key == DESIGN:
        return design_branch(context, workspace, item)
    if choice.key == REQUIREMENTS:
        return requirements_branch(context, workspace, item)
    proposed = [_text(task) for task in _list(item.alignment.get("code_tasks"))]
    proposed = [task for task in proposed if task]
    verdict: tuple[Candidate, ...] = ()
    if choice.key == MODEL_TASKS and proposed:
        texts = edit_tasks(context, proposed)
    else:
        texts = ask_tasks(context)
        verdict = task_selection.verdict_candidates(proposed)
    chosen = choose_tasks(
        context, workspace, item, verdict, room=changes_api.MAX_TASKS - len(texts)
    )
    texts = [*texts, *chosen.texts]
    if not texts and not chosen.findings:
        console.say("align.tasks_none")
        return None, 0
    answer = record(
        workspace, item.commit, changes_api.CODE_TASKS, tasks=texts, findings=chosen.findings
    )
    console.say("align.decided_tasks", count=len(texts) + len(chosen.findings))
    created = created_tasks(answer, chosen.before)
    if created:
        console.items(
            [f"{tasks_api.task_code(task)}: {tasks_api.task_text(task)}" for task in created]
        )
    return changes_api.CODE_TASKS, 0


def choose_tasks(
    context: CommandContext,
    workspace: Workspace,
    item: Reviewed,
    verdict: Sequence[Candidate],
    *,
    room: int,
) -> Chosen:
    console = context.console
    document = changes_api.alignment(workspace.client, workspace.project_id)
    tasks = changes_api.open_tasks(document)
    before = frozenset(tasks_api.task_code(task) for task in tasks)
    if room <= 0:
        return Chosen(before=before)
    findings = task_selection.candidates_of_review(item.commit, item.run, tasks)
    candidates = (*verdict, *findings)
    if not candidates:
        return Chosen(before=before)
    console.say("align.findings_intro_verdict" if verdict else "align.findings_intro")
    key = "align.findings_question_verdict" if verdict else "align.findings_question"
    try:
        picked = task_selection.choose(
            context, candidates, question_key=key, default=verdict, limit=room
        )
    except CliError as error:
        if error.code != INPUT_CLOSED:
            raise
        picked = tuple(verdict[:room])
    return Chosen(
        texts=tuple(candidate.text for candidate in picked if candidate.verdict),
        findings=tuple(
            candidate.source
            for candidate in picked
            if not candidate.verdict and candidate.source is not None
        ),
        before=before,
    )


def created_tasks(
    answer: Mapping[str, object], before: frozenset[str]
) -> list[Mapping[str, object]]:
    alignment = answer.get("alignment")
    found = changes_api.open_tasks(alignment) if isinstance(alignment, Mapping) else []
    return [task for task in found if tasks_api.task_code(task) not in before]


def recheck_hint(context: CommandContext, workspace: Workspace) -> None:
    try:
        document = changes_api.alignment(workspace.client, workspace.project_id)
    except ApiFailure:
        return
    say_recheck(context, workspace, changes_api.stale_count(document))


def say_recheck(context: CommandContext, workspace: Workspace, count: int) -> None:
    if count <= 0 or workspace.hinted[-1:] == [count]:
        return
    workspace.hinted.append(count)
    context.console.say("align.recheck_hint", count=count)


def design_branch(
    context: CommandContext, workspace: Workspace, item: Reviewed
) -> tuple[str | None, int]:
    console = context.console
    request = edit_request(
        context,
        _text(item.alignment.get("design_request")),
        heading="align.design_request",
        limit=changes_api.MAX_DESIGN_REQUEST,
    )
    if request is None:
        console.say("align.request_none")
        return None, 0
    client, project = workspace.client, workspace.project
    state = design_state.read_state(client, project)
    reason = design_change.unavailable(state)
    if reason is not None:
        console.say(reason)
        console.say("align.design_not_started")
        return None, 1
    before = state.version_number
    try:
        status = design_change.change(context, client, project, state, request, ())
    except CliError as error:
        if error.status in UNRECORDABLE:
            raise
        if not started(error):
            report(context, error, "design")
            console.say("align.decided_later")
            return None, error.status
        report(context, error, "design")
        record(workspace, item.commit, changes_api.DESIGN_CHANGE, note=request)
        console.say("align.decided_design", commit=git.short(item.commit))
        return changes_api.DESIGN_CHANGE, error.status
    record(workspace, item.commit, changes_api.DESIGN_CHANGE, note=request)
    console.say("align.decided_design", commit=git.short(item.commit))
    fresh = design_state.read_state(client, project)
    number = fresh.version_number
    if number is None or number == before or fresh.chosen is None or fresh.approved:
        return changes_api.DESIGN_CHANGE, status
    if not console.confirm("align.design_approve", default=True, version=number):
        console.say("align.design_left", version=number)
        return changes_api.DESIGN_CHANGE, status
    try:
        approval = design_choice.approve(context, client, project, fresh)
    except CliError as error:
        if error.status in ENDING_STATUSES or error.code in ENDING_CODES:
            raise
        report(context, error, "design")
        return changes_api.DESIGN_CHANGE, error.status
    if approval == 0:
        recheck_hint(context, workspace)
    return changes_api.DESIGN_CHANGE, status or approval


def requirements_branch(
    context: CommandContext, workspace: Workspace, item: Reviewed
) -> tuple[str | None, int]:
    from orchestwin.cli.commands.init import Journey

    console = context.console
    request = edit_request(
        context,
        _text(item.alignment.get("requirements_request")),
        heading="align.requirements_request",
        limit=changes_api.MAX_REQUIREMENTS_REQUEST,
    )
    if request is None:
        console.say("align.request_none")
        return None, 0
    client, project, project_id = workspace.client, workspace.project, workspace.project_id
    version = requirements_api.current(client, project_id)
    if version is None:
        console.say("align.requirements_missing")
        return None, 1
    try:
        costs.confirm_spending(context, client, [REQUIREMENTS_OPERATION])
    except CliError as error:
        if error.code != "SPENDING_REFUSED":
            raise
        report(context, error, "align")
        console.say("align.decided_later")
        return None, error.status
    journey = Journey(context, client, project, script=None, until=None, idea=None)
    try:
        status, document = journey.job(
            requirements_api.change_path(project_id),
            requirements_api.change_body(request),
            operation=REQUIREMENTS_OPERATION,
            label=context.text("init.change_label"),
            passthrough=(requirements_api.UNCHANGED,),
        )
        if status >= 400:
            console.say("init.change_unchanged")
            updated = version
        else:
            diff = document.get("diff") if isinstance(document, Mapping) else None
            if not isinstance(diff, Mapping):
                raise ApiFailure("API_FAILURE", http_status=status, detail=document)
            updated = init_requirements.decide(journey, diff, version)
    except CliError as error:
        if error.code in ENDING_CODES or error.status in UNRECORDABLE:
            raise
        report(context, error, "init")
        console.say("align.decided_later")
        return None, error.status
    if updated.get("id") == version.get("id"):
        console.say("align.decided_later")
        return None, 0
    record(workspace, item.commit, changes_api.REQUIREMENTS_CHANGE, note=request)
    console.say("align.decided_requirements", commit=git.short(item.commit))
    number = updated.get("version_number") or "-"
    if not console.confirm("align.requirements_approve", default=True, version=number):
        console.say("align.requirements_left", version=number)
        return changes_api.REQUIREMENTS_CHANGE, 0
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
        return changes_api.REQUIREMENTS_CHANGE, error.status
    journey.conclude(REQUIREMENTS_STAGE, updated, gate)
    realign_design(context, workspace)
    recheck_hint(context, workspace)
    return changes_api.REQUIREMENTS_CHANGE, 0


def realign_design(context: CommandContext, workspace: Workspace) -> None:
    console = context.console
    try:
        gesture = sections_api.align(workspace.client, workspace.project_id)
    except CliError as error:
        if error.status in ENDING_STATUSES:
            raise
        console.say("align.design_realign_failed", code=str(error.values.get("code", error.code)))
        return
    if gesture is None:
        console.say("align.design_not_realigned")
        return
    after = gesture.sections
    for result in gesture.results:
        if result.outcome == sections_api.SKIPPED:
            continue
        if result.outcome == sections_api.ALIGNED and result.key == sections_api.DESIGN:
            number = result.version_number
            console.say("align.design_realigned", version="-" if number is None else number)
            continue
        console.write(sections_command.result_line(context, after, result))
    for line in sections_command.after_lines(
        context, after, gesture.aligned, covered=False, evaluation="sections.evaluation_missing"
    ):
        console.write(line)
    if not gesture.aligned:
        return
    if after is not None and after.behind():
        console.say("sections.folder_waits")
        return
    refresh_folder(context, workspace)


def menu(context: CommandContext, options: Sequence[Choice]) -> Choice:
    console = context.console
    console.say("align.decision_question")
    for number, option in enumerate(options, start=1):
        console.write(f"  {number}. {option.label}")
    for _ in range(ATTEMPTS):
        selected = selected_choice(console.ask("common.choose_prompt", default="1"), options)
        if selected is not None:
            return selected
        console.say("common.choice_invalid")
    raise CliError("ANSWER_NOT_VALID")


def edit_request(context: CommandContext, proposal: str, *, heading: str, limit: int) -> str | None:
    console = context.console
    if not proposal:
        return write_request(context, limit=limit)
    console.say(heading)
    wrapped(context, context.text("align.quoted", text=proposal), indent="  ")
    for _ in range(ATTEMPTS):
        answer = " ".join(console.ask("align.request_keep", required=False).split())
        text = answer or proposal
        if len(text) <= limit:
            return text
        console.say("align.request_too_long", limit=limit)
    raise CliError("ANSWER_NOT_VALID")


def write_request(context: CommandContext, *, limit: int) -> str | None:
    console = context.console
    for _ in range(ATTEMPTS):
        lines = [line.strip() for line in console.ask_text("align.request_write").splitlines()]
        text = "\n".join(line for line in lines if line)
        if not text:
            return None
        if len(text) <= limit:
            return text
        console.say("align.request_too_long", limit=limit)
    raise CliError("ANSWER_NOT_VALID")


def ask_tasks(context: CommandContext) -> list[str]:
    console = context.console
    console.say("align.tasks_intro", limit=changes_api.MAX_TASKS)
    texts: list[str] = []
    refused = 0
    while len(texts) < changes_api.MAX_TASKS:
        try:
            line = console.read_line()
        except CliError as error:
            if error.code == "INPUT_CLOSED" and texts:
                break
            raise
        text = " ".join(line.split())
        if not text:
            break
        if len(text) > changes_api.MAX_TASK_LENGTH:
            refused += 1
            if refused >= ATTEMPTS:
                raise CliError("ANSWER_NOT_VALID")
            console.say("align.task_too_long", limit=changes_api.MAX_TASK_LENGTH)
            continue
        texts.append(text)
    return texts


def edit_tasks(context: CommandContext, proposed: Sequence[str]) -> list[str]:
    console = context.console
    console.say("align.model_tasks_intro")
    kept: list[str] = []
    for number, text in enumerate(proposed[: changes_api.MAX_TASKS], start=1):
        bullets(context, [context.text("align.model_task", number=number, text=text)])
        for _ in range(ATTEMPTS):
            answer = " ".join(console.ask("align.model_task_edit", required=False).split())
            if answer == DROP:
                break
            chosen = answer or text
            if len(chosen) <= changes_api.MAX_TASK_LENGTH:
                kept.append(chosen)
                break
            console.say("align.task_too_long", limit=changes_api.MAX_TASK_LENGTH)
        else:
            raise CliError("ANSWER_NOT_VALID")
    return kept


def record(
    workspace: Workspace,
    commit: str,
    kind: str,
    *,
    note: str | None = None,
    tasks: Sequence[str] = (),
    findings: Sequence[Mapping[str, object]] = (),
) -> Mapping[str, object]:
    return changes_api.decide(
        workspace.client,
        workspace.project_id,
        commit,
        kind,
        note=note,
        tasks=tasks,
        findings=findings,
    )


def refresh_folder(context: CommandContext, workspace: Workspace) -> None:
    console = context.console
    try:
        found = publish_and_pull(context, workspace.client, workspace.project)
    except CliError as error:
        if error.status in ENDING_STATUSES:
            raise
        if isinstance(error, ApiFailure) and error.http_status == 409:
            console.say("align.folder_refused", code=error.code)
        else:
            console.say("align.folder_not_updated", code=str(error.values.get("code", error.code)))
        return
    console.say("align.folder_updated", version=found.version_number)


def started(error: CliError) -> bool:
    return error.code not in NOT_STARTED and error.code not in ENDING_CODES


def report(context: CommandContext, error: CliError, command: str) -> None:
    from orchestwin.cli.main import report_error

    if error.code in ENDING_CODES:
        raise error
    report_error(context.console, error, command)


def _label(key: str, verdict: str | None) -> str:
    if key == MARK:
        return (
            "align.choice_mark_aligned"
            if verdict in (None, changes_api.ALIGNED) or verdict not in MENUS
            else "align.choice_aligned_anyway"
        )
    return OWN_LABELS.get((key, verdict or ""), LABELS[key])


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""
