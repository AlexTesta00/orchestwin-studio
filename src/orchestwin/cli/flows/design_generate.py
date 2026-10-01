from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, NoReturn

from orchestwin.cli import costs, jobs
from orchestwin.cli.api import design as design_api
from orchestwin.cli.api import usage
from orchestwin.cli.client import api_failure
from orchestwin.cli.console import ProgressOutcome
from orchestwin.cli.errors import BUDGET_CODES, INTERRUPTED_STATUS, ApiFailure, CliError
from orchestwin.cli.flows import design_state
from orchestwin.cli.messages import known

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.design_state import Alternative, DesignState
    from orchestwin.cli.http import Reply
    from orchestwin.cli.project import ProjectFolder

BUSY_STATUS: Final = 429
BUSY_ATTEMPTS: Final = 8
BUSY_SECONDS: Final = 15.0
LIMIT_SECONDS: Final = 1800.0
ACCEPTED: Final = 202
MOCKUPS_AT_ONCE: Final = 2
SUCCEEDED: Final = "SUCCEEDED"
REJECTED: Final = "REJECTED"
FAILED: Final = "FAILED"
LOST: Final = "LOST"
UNREACHABLE: Final = "STUDIO_UNREACHABLE"
JOB_RUNNING_REASON: Final = "JOB_RUNNING"
CONTEXT_CHANGED: Final = "DESIGN_CONTEXT_CHANGED"
CONTEXT_CODES: Final = frozenset(
    {
        "DESIGN_CONTEXT_CHANGED",
        "CONTEXT_CHANGED",
        "IDENTIFIER_CHANGED",
        "BASE_VERSION_STALE",
        "DIFF_ALREADY_DECIDED",
        "DESIGN_PACKAGE_ALREADY_EXISTS",
        "ARTIFACT_STALE",
        "PACKAGE_NOT_FOUND",
        "DIFF_NOT_FOUND",
    }
)
CUT_CODES: Final = frozenset({"INCOMPLETE_OUTPUT", "TIMEOUT"})
PROPOSAL_REJECTED: Final = "PROPOSAL_REJECTED"
PROPOSAL_ISSUE: Final = "proposal_issue"
OPERATION_KEYS: Final = {
    "DESIGN_PROPOSAL": "design.job_proposal",
    "DESIGN_REGENERATION": "design.job_proposal",
    "DESIGN_EVALUATION": "design.job_review",
    "ITERATION": "design.job_change",
}


class Prices:
    def __init__(self, client: StudioClient) -> None:
        self._client = client
        self._runtime: design_api.ModelRuntime | None = None

    def runtime(self) -> design_api.ModelRuntime:
        if self._runtime is None:
            self._runtime = design_api.model_runtime(self._client)
        return self._runtime

    def shown(self) -> bool:
        return self.runtime().budget and not self.subscription()

    def subscription(self) -> bool:
        runtime = self.runtime()
        return runtime.budget and runtime.billing == usage.SUBSCRIPTION_BILLING

    def modelless(self, state: DesignState) -> bool:
        return state.version is not None and not state.generated and not self.runtime().model


@dataclass(frozen=True, slots=True)
class Tracked:
    job_id: str
    operation: str
    address: str
    name: str
    alternative_id: str | None
    job: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Outcome:
    tracked: Tracked
    job: Mapping[str, object] | None

    @property
    def status(self) -> str:
        if self.job is None or failure_code(self.job) == jobs.CANCELLED:
            return LOST
        status = self.job.get("status")
        if status == SUCCEEDED and self.response is not None and self.response[0] >= 400:
            return FAILED
        return status if isinstance(status, str) else FAILED

    @property
    def result(self) -> Mapping[str, object] | None:
        value = None if self.job is None else self.job.get("result")
        return value if self.status == SUCCEEDED and isinstance(value, Mapping) else None

    @property
    def response(self) -> tuple[int, object] | None:
        value = None if self.job is None else self.job.get("response")
        if not isinstance(value, Mapping):
            return None
        status = value.get("status_code")
        if not isinstance(status, int) or isinstance(status, bool):
            return None
        return status, value.get("body")

    @property
    def code(self) -> str | None:
        if self.job is None:
            return None
        code = failure_code(self.job)
        if code is not None:
            return code
        response = self.response
        if response is not None and response[0] >= 400:
            return failure_of(response[0], response[1]).code
        return None

    @property
    def reasons(self) -> tuple[str, ...]:
        return failure_reasons(self.job)


def retry_busy[T](context: CommandContext, send: Callable[[], T], status: Callable[[T], int]) -> T:
    attempt = 1
    outcome = send()
    while status(outcome) == BUSY_STATUS and attempt < BUSY_ATTEMPTS:
        context.console.say(
            "design.busy_wait",
            seconds=int(BUSY_SECONDS),
            attempt=attempt + 1,
            attempts=BUSY_ATTEMPTS,
        )
        context.environment.sleep(BUSY_SECONDS)
        attempt += 1
        outcome = send()
    return outcome


def generate(
    context: CommandContext,
    client: StudioClient,
    project_id: str,
    path: str,
    body: object | None = None,
    *,
    label: str,
    job_path: Callable[[str], str] | None = None,
) -> jobs.JobResult:
    return retry_busy(
        context,
        lambda: jobs.generate(
            context, client, project_id, path, body, label=label, job_path=job_path
        ),
        lambda result: result.status_code,
    )


def failure_of(status_code: int, body: object) -> ApiFailure:
    detail = body.get("detail") if isinstance(body, Mapping) else body
    code = failure_code(body) if isinstance(body, Mapping) else None
    if code is None and isinstance(detail, Mapping):
        found = detail.get("code")
        code = found if isinstance(found, str) and found else None
    if code is None and isinstance(detail, str) and detail:
        code = detail
    issue = detail.get(PROPOSAL_ISSUE) if isinstance(detail, Mapping) else None
    return ApiFailure(
        code or "API_FAILURE",
        http_status=status_code,
        detail=detail,
        values={"reason": issue} if isinstance(issue, str) and issue else None,
    )


def failure_key(failure: ApiFailure) -> str | None:
    reason = failure.values.get("reason")
    keys = [f"design.errors.{failure.code}"]
    if isinstance(reason, str) and reason:
        keys.insert(0, f"{keys[0]}.{reason}")
    return next((key for key in keys if known(key)), None)


def failure_code(job: Mapping[str, object]) -> str | None:
    failure = job.get("failure")
    code = failure.get("code") if isinstance(failure, Mapping) else None
    return code if isinstance(code, str) and code else None


def failure_reasons(job: Mapping[str, object] | None) -> tuple[str, ...]:
    failure = None if job is None else job.get("failure")
    reasons = failure.get("reasons") if isinstance(failure, Mapping) else None
    found: list[str] = []
    for item in reasons if isinstance(reasons, list) else []:
        detail = item.get("detail") if isinstance(item, Mapping) else None
        if isinstance(detail, str) and detail.strip():
            found.append(" ".join(detail.split()))
    return tuple(found)


def raise_failure(failure: ApiFailure) -> NoReturn:
    if failure.code in CONTEXT_CODES:
        raise CliError(CONTEXT_CHANGED, values={"code": failure.code}) from failure
    raise failure


def track(context: CommandContext, state: DesignState, job: Mapping[str, object]) -> Tracked:
    operation = str(job.get("operation") or "")
    job_id = str(job.get("job_id"))
    alternative_id = job.get("alternative_id")
    alternative_id = alternative_id if isinstance(alternative_id, str) else None
    project_id = state.project_id
    if operation == "MOCKUP":
        alternative = None if alternative_id is None else state.alternative_by_id(alternative_id)
        return Tracked(
            job_id=job_id,
            operation=operation,
            address=design_api.mockup_job_path(project_id, job_id),
            name=context.text("design.job_mockup", code=alternative.code if alternative else "-"),
            alternative_id=alternative_id,
            job=job,
        )
    address = (
        design_api.iteration_job_path(project_id, job_id)
        if operation == "ITERATION"
        else design_api.request_job_path(project_id, job_id)
    )
    return Tracked(
        job_id=job_id,
        operation=operation,
        address=address,
        name=context.text(OPERATION_KEYS.get(operation, "design.job_other")),
        alternative_id=alternative_id,
        job=job,
    )


def follow(
    context: CommandContext,
    client: StudioClient,
    tracked: Sequence[Tracked],
    *,
    label: str,
    limit_seconds: float = LIMIT_SECONDS,
) -> list[Outcome]:
    environment = context.environment
    started = environment.monotonic()
    latest = {item.job_id: item.job for item in tracked}
    finished: dict[str, Mapping[str, object] | None] = {
        item.job_id: item.job for item in tracked if item.job.get("status") != jobs.RUNNING
    }
    pending = [item for item in tracked if item.job_id not in finished]
    try:
        with context.console.progress(label) as progress:
            while pending:
                if environment.monotonic() - started >= limit_seconds:
                    raise CliError(
                        "GENERATION_STILL_RUNNING",
                        values={"label": label, "job_id": pending[0].job_id},
                    )
                progress.update(_detail(context, pending, latest))
                environment.sleep(jobs.POLL_SECONDS)
                for item in list(pending):
                    answer = _poll(client, item, label)
                    if answer is not None:
                        latest[item.job_id] = answer
                    if answer is None or answer.get("status") != jobs.RUNNING:
                        finished[item.job_id] = answer
                        pending.remove(item)
            outcomes = [Outcome(item, finished.get(item.job_id)) for item in tracked]
            if any(outcome.status != SUCCEEDED for outcome in outcomes):
                progress.set_outcome(ProgressOutcome.NOT_COMPLETED)
    except KeyboardInterrupt:
        job_id = next((item.job_id for item in [*pending, *tracked]), "-")
        raise CliError(
            "GENERATION_INTERRUPTED",
            status=INTERRUPTED_STATUS,
            values={"label": label, "job_id": job_id},
        ) from None
    return outcomes


def unreachable_while_running(error: CliError, label: str) -> CliError:
    return CliError(
        UNREACHABLE,
        status=error.status,
        values={**error.values, "reason": JOB_RUNNING_REASON, "label": label},
    )


def start_design(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    state: DesignState,
    prices: Prices,
) -> bool:
    console = context.console
    generated = state.generated
    if generated:
        console.say("design.about_design_and_mockups")
        minutes = costs.ESTIMATES["DESIGN_PROPOSAL"].minutes + costs.ESTIMATES["MOCKUP"].minutes
        costs.confirm_spending(
            context, client, ["DESIGN_PROPOSAL", "MOCKUP", "MOCKUP"], minutes=minutes
        )
    else:
        console.say("design.about_design")
        costs.confirm_spending(context, client, ["DESIGN_PROPOSAL"])
    result = generate(
        context,
        client,
        state.project_id,
        design_api.proposals_path(state.project_id),
        label=context.text("design.label_proposal"),
    )
    if result.status_code >= 400:
        raise_failure(failure_of(result.status_code, result.body))
    fresh = design_state.read_state(client, project)
    if fresh.version is None:
        raise ApiFailure("API_FAILURE", http_status=result.status_code)
    design_state.show_alternatives(context, fresh, mockups=False)
    design_state.show_verdicts(context, fresh)
    if not generated:
        design_state.say_without_previews(context, fresh, modelless=prices.modelless(fresh))
        return False
    draw(context, client, fresh, pair(fresh.alternatives), prices)
    return True


def pair(alternatives: Sequence[Alternative]) -> tuple[Alternative, ...]:
    if len(alternatives) <= MOCKUPS_AT_ONCE:
        return tuple(alternatives)
    recommended = next((item for item in alternatives if item.recommended), alternatives[0])
    other = next(item for item in alternatives if item.id != recommended.id)
    return tuple(item for item in alternatives if item.id in {recommended.id, other.id})


def draw_missing(
    context: CommandContext, client: StudioClient, state: DesignState, prices: Prices
) -> bool:
    missing = state.missing_mockups()
    if not missing:
        return False
    context.console.say("design.about_mockups", codes=", ".join(item.code for item in missing))
    costs.confirm_spending(
        context,
        client,
        ["MOCKUP"] * len(missing),
        minutes=costs.ESTIMATES["MOCKUP"].minutes,
    )
    draw(context, client, state, missing, prices)
    return True


def draw(
    context: CommandContext,
    client: StudioClient,
    state: DesignState,
    alternatives: Sequence[Alternative],
    prices: Prices,
) -> list[Outcome]:
    tracked: list[Tracked] = []
    started: list[Alternative] = []
    refused: list[tuple[Alternative, ApiFailure]] = []
    for alternative in alternatives:
        reply = _start_mockup(context, client, state, alternative)
        if reply.status == ACCEPTED:
            job = reply.json()
            if not isinstance(job, dict) or not isinstance(job.get("job_id"), str):
                raise ApiFailure("API_FAILURE", http_status=reply.status)
            tracked.append(
                track(
                    context, state, {**job, "operation": "MOCKUP", "alternative_id": alternative.id}
                )
            )
            started.append(alternative)
            continue
        failure = api_failure(reply)
        if failure.code in CONTEXT_CODES:
            raise_failure(failure)
        refused.append((alternative, failure))
    if not tracked:
        if refused:
            raise_failure(refused[0][1])
        return []
    for alternative, failure in refused:
        report_refusal(context, alternative, failure)
    key = "design.label_mockups" if len(tracked) > 1 else "design.label_mockup"
    label = context.text(key, code=started[0].code)
    outcomes = follow(context, client, tracked, label=label)
    for outcome in outcomes:
        report_mockup(context, state, outcome, prices)
    return outcomes


def follow_running(
    context: CommandContext, client: StudioClient, state: DesignState
) -> list[Outcome]:
    tracked = [track(context, state, job) for job in state.running]
    context.console.say("design.running", names=", ".join(item.name for item in tracked))
    return follow(context, client, tracked, label=context.text("design.label_running"))


def report_mockup(
    context: CommandContext, state: DesignState, outcome: Outcome, prices: Prices
) -> None:
    name = outcome.tracked.name
    if outcome.status == SUCCEEDED:
        context.console.say("design.mockup_ready", name=name)
        return
    report_job(context, outcome)
    code = outcome.code
    if code in BUDGET_CODES or code in CONTEXT_CODES:
        return
    alternative = (
        None
        if outcome.tracked.alternative_id is None
        else state.alternative_by_id(outcome.tracked.alternative_id)
    )
    if alternative is not None:
        say_again(context, alternative, prices)


def report_refusal(context: CommandContext, alternative: Alternative, failure: ApiFailure) -> None:
    name = context.text("design.job_mockup", code=alternative.code)
    if failure.code in BUDGET_CODES or failure.http_status == 402:
        context.console.say("design.job_budget", name=name, code=failure.code)
        return
    context.console.say(
        "design.job_refused", name=name, code=failure.code, http_status=failure.http_status
    )


def report_job(context: CommandContext, outcome: Outcome) -> bool:
    console = context.console
    name = outcome.tracked.name
    code = outcome.code or outcome.status
    status = outcome.status
    response = outcome.response
    refusal = None
    if code == PROPOSAL_REJECTED and response is not None:
        refusal = failure_of(*response)
    key = None if refusal is None else failure_key(refusal)
    if refusal is not None and key is not None:
        console.say(key, **refusal.values)
        return True
    if status == LOST:
        console.say("design.job_lost", name=name)
    elif code in BUDGET_CODES:
        console.say("design.job_budget", name=name, code=code)
    elif code in CONTEXT_CODES:
        console.say("design.job_context", name=name)
    elif code in CUT_CODES:
        console.say("design.job_cut", name=name, code=code)
    elif status == REJECTED:
        console.say("design.job_rejected", name=name, code=code)
        console.items(list(outcome.reasons))
    else:
        console.say("design.job_failed", name=name, code=code)
    return False


def say_again(context: CommandContext, alternative: Alternative, prices: Prices) -> None:
    estimate = costs.estimate(["MOCKUP"])
    if prices.subscription():
        context.console.say(
            "design.mockup_again_subscription",
            code=alternative.code,
            minutes=costs.minutes_text(estimate.minutes),
        )
        return
    if not prices.shown():
        context.console.say("design.mockup_again_plain", code=alternative.code)
        return
    context.console.say(
        "design.mockup_again",
        code=alternative.code,
        amount=costs.amount_text(estimate, context.language),
        minutes=costs.minutes_text(estimate.minutes),
    )


def estimate_text(
    context: CommandContext,
    operations: Sequence[str],
    *,
    minutes: float | None = None,
    subscription: bool = False,
) -> str:
    total = costs.estimate(operations, minutes=minutes)
    duration = costs.minutes_text(total.minutes)
    if subscription:
        return context.text("design.estimate_subscription", minutes=duration)
    return context.text(
        "design.estimate",
        amount=costs.amount_text(total, context.language),
        minutes=duration,
    )


def _start_mockup(
    context: CommandContext,
    client: StudioClient,
    state: DesignState,
    alternative: Alternative,
) -> Reply:
    version = state.version or {}
    return retry_busy(
        context,
        lambda: design_api.start_mockup(client, state.project_id, version, alternative.id),
        lambda reply: reply.status,
    )


def _poll(client: StudioClient, item: Tracked, label: str) -> Mapping[str, object] | None:
    try:
        answer = client.get(item.address, optional=True)
    except CliError as error:
        if error.code == UNREACHABLE:
            raise unreachable_while_running(error, label) from None
        raise
    if answer is None:
        return None
    if not isinstance(answer, dict) or not isinstance(answer.get("job_id"), str):
        raise ApiFailure("API_FAILURE", http_status=200)
    return answer


def _detail(
    context: CommandContext,
    pending: Sequence[Tracked],
    latest: Mapping[str, Mapping[str, object]],
) -> str:
    if len(pending) == 1:
        return jobs.stage_text(context, latest[pending[0].job_id])
    return "; ".join(
        f"{item.name}: {jobs.stage_text(context, latest[item.job_id])}" for item in pending
    )
