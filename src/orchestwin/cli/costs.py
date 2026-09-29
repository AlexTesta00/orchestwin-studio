from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import usage
from orchestwin.cli.errors import CliError

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
        "TWIN_CHAT": Estimate(0.02, 0.05, 0.3),
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
    amount = amount_text(total, context.language)
    duration = minutes_text(total.minutes)
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
