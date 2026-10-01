from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Final, Protocol

from orchestwin.models.hosted_configuration import (
    BudgetSettings,
    HostedModelConfiguration,
    ModelPrices,
)
from orchestwin.models.hosted_schema import hosted_user_message
from orchestwin.models.proposal_evidence import current_proposal_evidence
from orchestwin.models.structured_generation import (
    StructuredGenerationRequest,
    StructuredGenerationUsage,
)

BUDGET_CURRENCY: Final = "USD"
GENERATION_BUDGET_EXCEEDED: Final = "GENERATION_BUDGET_EXCEEDED"
GENERATION_BUDGET_UNAVAILABLE: Final = "GENERATION_BUDGET_UNAVAILABLE"


class SpentAmountReader(Protocol):
    async def spent_microusd(
        self, *, project_id: object | None = None, since: date | None = None
    ) -> int: ...


def cost_microusd(
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int = 0,
    cache_write_input_tokens: int = 0,
    prices: ModelPrices,
) -> int:
    total = (
        Decimal(input_tokens) * prices.input_per_million
        + Decimal(output_tokens) * prices.output_per_million
        + Decimal(cache_read_input_tokens) * prices.cache_read_per_million
        + Decimal(cache_write_input_tokens) * prices.cache_write_per_million
    )
    return int(total.to_integral_value(rounding=ROUND_HALF_UP))


def usage_cost_microusd(usage: StructuredGenerationUsage, prices: ModelPrices) -> int:
    return cost_microusd(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_input_tokens=usage.cache_read_input_tokens,
        cache_write_input_tokens=usage.cache_write_input_tokens,
        prices=prices,
    )


def prompt_characters(request: StructuredGenerationRequest, retry_note: str | None = None) -> int:
    message = hosted_user_message(request.input_payload_json, retry_note)
    return len(request.system_instruction) + len(message)


def estimated_cost_microusd(
    request: StructuredGenerationRequest,
    configuration: HostedModelConfiguration,
    retry_note: str | None = None,
) -> int:
    return cost_microusd(
        input_tokens=configuration.estimated_prompt_tokens(prompt_characters(request, retry_note)),
        output_tokens=configuration.max_tokens(request.max_output_tokens),
        prices=configuration.prices,
    )


def provider_result_cost_microusd(result: Mapping[str, object]) -> int:
    total = 0
    for branch in ("success", "failure"):
        section = result.get(branch)
        usage = section.get("usage") if isinstance(section, Mapping) else None
        cost = usage.get("cost_microusd") if isinstance(usage, Mapping) else None
        if isinstance(cost, int) and not isinstance(cost, bool) and cost > 0:
            total += cost
    return total


@dataclass(frozen=True, slots=True)
class GenerationBudget:
    per_generation_microusd: int
    per_project_microusd: int
    total_microusd: int
    period_start: date | None = None

    def __post_init__(self) -> None:
        values = (self.per_generation_microusd, self.per_project_microusd, self.total_microusd)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ValueError("budget ceilings must be integers of micro USD")
        if not 0 < self.per_generation_microusd <= self.per_project_microusd <= self.total_microusd:
            raise ValueError("budget ceilings must be positive and ordered")

    @classmethod
    def from_settings(cls, settings: BudgetSettings) -> GenerationBudget:
        return cls(
            per_generation_microusd=settings.per_generation_microusd,
            per_project_microusd=settings.per_project_microusd,
            total_microusd=settings.total_microusd,
            period_start=settings.period_start,
        )

    async def refusal(
        self,
        *,
        request: StructuredGenerationRequest,
        configuration: HostedModelConfiguration,
        retry_note: str | None = None,
    ) -> str | None:
        estimate = estimated_cost_microusd(request, configuration, retry_note)
        if estimate == 0:
            return None
        if estimate > self.per_generation_microusd:
            return GENERATION_BUDGET_EXCEEDED
        scope = current_proposal_evidence()
        reader = getattr(getattr(scope, "store", None), "spent_microusd", None)
        if scope is None or reader is None:
            return GENERATION_BUDGET_UNAVAILABLE
        if await reader(project_id=scope.project_id) + estimate > self.per_project_microusd:
            return GENERATION_BUDGET_EXCEEDED
        if await reader(since=self.period_start) + estimate > self.total_microusd:
            return GENERATION_BUDGET_EXCEEDED
        return None

    def report(self, spent_total_microusd: int | None) -> dict[str, object]:
        remaining = (
            None
            if spent_total_microusd is None
            else max(self.total_microusd - spent_total_microusd, 0)
        )
        return {
            "currency": BUDGET_CURRENCY,
            "per_generation_microusd": self.per_generation_microusd,
            "per_project_microusd": self.per_project_microusd,
            "total_microusd": self.total_microusd,
            "spent_total_microusd": spent_total_microusd,
            "remaining_total_microusd": remaining,
            "period_start": None if self.period_start is None else self.period_start.isoformat(),
        }


__all__ = [
    "BUDGET_CURRENCY",
    "GENERATION_BUDGET_EXCEEDED",
    "GENERATION_BUDGET_UNAVAILABLE",
    "GenerationBudget",
    "SpentAmountReader",
    "cost_microusd",
    "estimated_cost_microusd",
    "prompt_characters",
    "provider_result_cost_microusd",
    "usage_cost_microusd",
]
