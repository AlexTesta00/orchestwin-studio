from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import usage
from orchestwin.cli.errors import BUDGET_CODES, PAYMENT_REQUIRED, ApiFailure, CliError
from orchestwin.cli.shapes import is_whole

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext

THRESHOLD_USD: Final = 0.50


@dataclass(frozen=True, slots=True)
class Estimate:
    low_usd: float
    high_usd: float
    minutes: float


ESTIMATES: Final[Mapping[str, Estimate]] = MappingProxyType(
    {
        "BRIEF_DIALOGUE": Estimate(0.09, 0.09, 1.0),
        "TEAM_PROPOSAL": Estimate(0.02, 0.03, 0.2),
        "PERSONA_PROPOSAL": Estimate(0.05, 0.05, 0.3),
        "USER_TWIN_GENERATION": Estimate(0.12, 0.18, 0.6),
        "REQUIREMENTS_PROPOSAL": Estimate(0.20, 0.37, 2.0),
        "REQUIREMENTS_CHANGE": Estimate(0.30, 0.30, 2.0),
        "DESIGN_PROPOSAL": Estimate(0.31, 0.54, 3.0),
        "MOCKUP": Estimate(1.30, 1.60, 10.0),
        "ITERATION": Estimate(0.85, 1.33, 7.0),
        "DESIGN_EVALUATION": Estimate(0.27, 0.40, 1.5),
        "DESIGN_CHANGE_OPINION": Estimate(0.20, 0.35, 1.5),
        "DESIGN_CRITIQUE": Estimate(0.35, 0.60, 3.0),
        "TWIN_CHAT": Estimate(0.02, 0.05, 0.3),
        "CODE_CHANGE_REVIEW": Estimate(0.15, 0.25, 1.0),
        "CODE_ALIGNMENT": Estimate(0.15, 0.30, 1.0),
        "KNOWLEDGE_ALIGNMENT": Estimate(0.20, 0.40, 2.0),
        "DESIGN_CHANGE": Estimate(0.20, 0.50, 2.0),
        "TEST_PLAN": Estimate(0.15, 0.30, 2.0),
        "TEST_REVIEW": Estimate(0.10, 0.20, 1.0),
        "TWIN_UPDATE": Estimate(0.10, 0.25, 1.0),
    }
)


def estimate(operations: Sequence[str], *, minutes: float | None = None) -> Estimate:
    parts = [ESTIMATES[operation] for operation in operations]
    return Estimate(
        low_usd=round(sum(part.low_usd for part in parts), 2),
        high_usd=round(sum(part.high_usd for part in parts), 2),
        minutes=sum(part.minutes for part in parts) if minutes is None else minutes,
    )


def confirm_spending(
    context: CommandContext,
    client: StudioClient,
    operations: Sequence[str],
    *,
    minutes: float | None = None,
    ask: bool = True,
) -> None:
    total = estimate(operations, minutes=minutes)
    budget = usage.budget(client)
    if budget is None:
        return
    console = context.console
    duration = minutes_text(total.minutes)
    if usage.on_subscription(budget):
        console.say("costs.subscription", minutes=duration)
        return
    amount = amount_text(total, context.language)
    remaining = usage.remaining_usd(budget)
    if remaining is None:
        console.say("costs.estimate_no_credit", amount=amount, minutes=duration)
    else:
        console.say(
            "costs.estimate",
            amount=amount,
            minutes=duration,
            remaining=usd_text(remaining, context.language),
        )
        if total.high_usd > remaining:
            console.say("costs.over_credit")
    if total.high_usd <= THRESHOLD_USD:
        return
    if context.assume_yes:
        console.say("costs.assumed")
        return
    if not ask or not console.confirm("costs.confirm", default=True):
        raise CliError("SPENDING_REFUSED")


def say_estimate(
    context: CommandContext,
    client: StudioClient,
    operations: Sequence[str],
    *,
    subscription_key: str,
    estimate_key: str,
) -> None:
    total = estimate(operations)
    minutes = minutes_text(total.minutes)
    if uses_subscription(client):
        context.console.say(subscription_key, minutes=minutes)
        return
    context.console.say(estimate_key, amount=amount_text(total, context.language), minutes=minutes)


def budget_or_failure(
    context: CommandContext,
    client: StudioClient,
    project_id: str,
    failure: ApiFailure,
    operation: str,
) -> CliError:
    if failure.http_status == PAYMENT_REQUIRED or failure.code in BUDGET_CODES:
        return budget_error(context, client, project_id, failure.code, operation)
    return failure


def budget_error(
    context: CommandContext,
    client: StudioClient,
    project_id: str,
    code: str | None,
    operation: str,
) -> CliError:
    if code == "GENERATION_BUDGET_UNAVAILABLE":
        return CliError("GENERATION_BUDGET_UNAVAILABLE")
    reason, amount = ceiling(client, project_id, operation)
    if reason is None:
        return CliError("GENERATION_BUDGET_EXCEEDED")
    return CliError(
        "GENERATION_BUDGET_EXCEEDED",
        values={"reason": reason, "ceiling": usd_text(amount, context.language)},
    )


def ceiling(client: StudioClient, project_id: str, operation: str) -> tuple[str | None, float]:
    try:
        budget = usage.budget(client)
    except CliError:
        return None, 0.0
    if budget is None:
        return None, 0.0
    need = round(ESTIMATES[operation].high_usd * usage.MICRO_USD)
    total = budget.get("total_microusd")
    remaining = budget.get("remaining_total_microusd")
    if is_whole(total) and is_whole(remaining) and remaining < need:
        return "total", total / usage.MICRO_USD
    try:
        spent = usage.project_usage(client, project_id)
    except CliError:
        spent = None
    limit = budget.get("per_project_microusd")
    totals = spent.get("totals") if spent is not None else None
    used = totals.get("cost_microusd") if isinstance(totals, Mapping) else None
    if is_whole(limit) and is_whole(used) and limit - used < need:
        return "project", limit / usage.MICRO_USD
    single = budget.get("per_generation_microusd")
    if is_whole(single):
        return "generation", single / usage.MICRO_USD
    return None, 0.0


def uses_subscription(client: StudioClient) -> bool:
    try:
        return usage.on_subscription(usage.budget(client))
    except CliError:
        return False


def usd_text(value: float, language: str) -> str:
    text = f"{value:.2f}"
    return text.replace(".", ",") if language == "it" else text


def amount_text(total: Estimate, language: str) -> str:
    high = usd_text(total.high_usd, language)
    if math.isclose(total.low_usd, total.high_usd):
        return high
    return f"{usd_text(total.low_usd, language)}-{high}"


def minutes_text(minutes: float) -> str:
    return f"{max(math.ceil(minutes - 1e-9), 1)} min"
