from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs, jobs
from orchestwin.cli.api import changes as changes_api
from orchestwin.cli.api import tasks as tasks_api
from orchestwin.cli.api import tests as tests_api
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.flows import publish, task_selection, test_plan, test_report, verify_review
from orchestwin.cli.shapes import squeezed as _text

if TYPE_CHECKING:
    from pathlib import Path

    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.test_report import Names
    from orchestwin.cli.flows.test_run import Browser, Execution, Prepared

COMMAND: Final = "test"
REVIEW_LIMIT_SECONDS: Final = 900.0
SPENDING_REFUSED: Final = "SPENDING_REFUSED"
INTERRUPTED: Final = "GENERATION_INTERRUPTED"
INPUT_CLOSED: Final = "INPUT_CLOSED"


def run_body(
    ready: Prepared,
    execution: Execution,
    browsers: Sequence[Browser],
    *,
    started: object,
    finished: object,
) -> dict[str, object]:
    wanted = set(ready.criteria)
    not_covered = [
        {
            "criterion": str(item["criterion"]),
            "reason": cut(_text(item.get("reason")), tests_api.MAX_REASON_LENGTH),
        }
        for item in execution.saved.not_covered()
        if _text(item.get("reason")) and (not wanted or item.get("criterion") in wanted)
    ]
    return {
        "plan_id": execution.saved.plan_id,
        "replan_ids": execution.saved.replan_ids,
        "started_at": _moment(started),
        "finished_at": _moment(finished),
        "application": ready.application.document(),
        "browsers": [browser.document() for browser in browsers],
        "results": [outcome.document() for outcome in execution.results][: tests_api.MAX_RESULTS],
        "not_covered": not_covered,
    }


def recorded_run(document: Mapping[str, object]) -> Mapping[str, object]:
    run = document.get("run")
    if not isinstance(run, Mapping) or not isinstance(run.get("id"), str):
        raise ApiFailure("API_FAILURE", http_status=201)
    return run


def write_files(
    context: CommandContext,
    ready: Prepared,
    folder: Path,
    run: Mapping[str, object],
    names: Names,
    labels: Mapping[str, str],
    first_attempt: Sequence[Mapping[str, object]],
    weak: Sequence[Mapping[str, object]] = (),
) -> Path:
    test_report.write_run(folder, run, first_attempt=first_attempt)
    test_report.write_latest(test_plan.tests_folder(ready.project), folder, run)
    return test_report.write_report(
        context,
        folder,
        run,
        project_name=ready.project_name,
        names=names,
        labels=labels,
        first_attempt=first_attempt,
        weak=weak,
    )


def review_run(
    context: CommandContext,
    ready: Prepared,
    run: Mapping[str, object],
    *,
    available: bool,
) -> Mapping[str, object] | None:
    console = context.console
    console.write()
    if not available:
        console.say("test.review_unavailable")
        return None
    try:
        return reviewed(context, ready, run)
    except CliError as error:
        if error.code == INTERRUPTED:
            raise
        if error.code == SPENDING_REFUSED:
            console.say("test.review_skipped")
        elif error.code == tests_api.NO_TEST_MODEL:
            console.say("test.review_unavailable")
        else:
            say_error(context, error)
        return None


def reviewed(
    context: CommandContext, ready: Prepared, run: Mapping[str, object]
) -> Mapping[str, object]:
    twins = verify_review.twins_count(ready.client, ready.project)
    context.console.say("test.reviewing", twins=twins)
    costs.confirm_spending(context, ready.client, [tests_api.REVIEW_OPERATION] * twins)
    run_id = str(run.get("id") or "")
    result = jobs.generate(
        context,
        ready.client,
        ready.project_id,
        tests_api.review_path(ready.project_id, run_id),
        tests_api.review_body(ready.locale),
        label=context.text("test.review_label"),
        limit_seconds=REVIEW_LIMIT_SECONDS,
    )
    if result.status_code < 400:
        return jobs.answer_member(result, "review")
    if tests_api.code_of(result.body) == tests_api.REVIEW_EXISTS:
        found = tests_api.reviews(ready.client, ready.project_id, run_id)
        if found:
            return found[0]
    raise test_plan.refusal(
        context,
        ready.client,
        ready.project_id,
        result.status_code,
        result.body,
        tests_api.REVIEW_OPERATION,
    )


def with_review(run: Mapping[str, object], review: Mapping[str, object]) -> dict[str, object]:
    cost = run.get("cost_microusd")
    added = review.get("cost_microusd")
    total = cost if isinstance(cost, int) and not isinstance(cost, bool) else 0
    if isinstance(added, int) and not isinstance(added, bool):
        total += added
    return {
        **run,
        "critiques": [dict(item) for item in tests_api.critiques_of(review)],
        "reviewed_at": review.get("reviewed_at"),
        "cost_microusd": total,
    }


def open_tasks(ready: Prepared) -> tuple[Mapping[str, object], ...]:
    try:
        document = changes_api.alignment(ready.client, ready.project_id)
    except CliError:
        return ()
    return tuple(changes_api.open_tasks(document))


def passed_tasks(
    context: CommandContext, run: Mapping[str, object], tasks: Sequence[Mapping[str, object]]
) -> None:
    passed = {
        str(item.get("code"))
        for item in tests_api.criteria_of(run)
        if item.get("status") == tests_api.PASSED and isinstance(item.get("code"), str)
    }
    if not passed:
        return
    for task in tasks:
        codes = [code for code in tasks_api.criteria_of(task) if code in passed]
        if tasks_api.is_open(task) and codes:
            code = tasks_api.task_code(task)
            context.console.say("test.task_maybe_done", task=code, criteria=", ".join(codes))


def offer_tasks(
    context: CommandContext,
    ready: Prepared,
    run: Mapping[str, object],
    tasks: Sequence[Mapping[str, object]],
) -> None:
    console = context.console
    candidates = task_selection.candidates_of_run(run, tasks)
    if not any(item.offered for item in candidates):
        return
    console.write()
    console.say("test.tasks_intro")
    try:
        chosen = task_selection.choose(context, candidates, question_key="test.tasks_question")
    except CliError as error:
        if error.code != INPUT_CLOSED:
            raise
        console.say("test.tasks_later")
        return
    if not chosen:
        console.say("test.tasks_none")
        return
    items = [tasks_api.finding_item(item.source) for item in chosen if item.source is not None]
    try:
        count, created = tasks_api.create_all(ready.client, ready.project_id, items)
    except CliError as error:
        console.say("test.tasks_failed", code=error_code(error))
        return
    console.say("test.tasks_created", count=count)
    console.items([f"{tasks_api.task_code(task)}: {tasks_api.task_text(task)}" for task in created])
    console.say("test.tasks_next")


def publish_folder(context: CommandContext, ready: Prepared) -> None:
    publish.publish_and_report(
        context,
        ready.client,
        ready.project,
        updated_key="test.folder_updated",
        failed_key="test.folder_not_updated",
        blank_line=True,
    )


def say_error(context: CommandContext, error: CliError) -> None:
    from orchestwin.cli.main import error_key

    key = error_key(error, COMMAND)
    if key is None:
        context.console.say("test.review_failed", code=error.code)
        return
    context.console.say(key, **error.values)


def error_code(error: CliError) -> str:
    inner = error.values.get("code")
    return str(inner) if isinstance(inner, str) and inner else error.code


def _moment(value: object) -> str:
    isoformat = getattr(value, "isoformat", None)
    return str(isoformat(timespec="seconds")) if callable(isoformat) else str(value)


def cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
