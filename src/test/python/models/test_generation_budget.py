from __future__ import annotations

import asyncio
from datetime import date
from math import ceil
from uuid import uuid4

import pytest

from orchestwin.models.generation_budget import (
    GENERATION_BUDGET_EXCEEDED,
    GENERATION_BUDGET_UNAVAILABLE,
    GenerationBudget,
    cost_microusd,
    estimated_cost_microusd,
    prompt_characters,
    provider_result_cost_microusd,
    usage_cost_microusd,
)
from orchestwin.models.hosted_configuration import ModelPrices
from orchestwin.models.hosted_schema import hosted_user_message
from orchestwin.models.proposal_evidence import _SCOPE, ProposalEvidenceScope
from orchestwin.models.structured_generation import (
    StructuredGenerationFailureCode,
    StructuredGenerationProviderKind,
    StructuredGenerationUsage,
    failed_structured_generation_result,
)
from src.test.python.models.test_hosted_support import (
    SpendingEvidence,
    providers,
    structured_request,
)
from src.test.python.models.test_proposal_evidence import MemoryEvidence

PRICES = ModelPrices(input="4.00", output="20.00", cache_read="0.20", cache_write="5.00")
CEILINGS = GenerationBudget(
    per_generation_microusd=1_500_000,
    per_project_microusd=10_000_000,
    total_microusd=60_000_000,
    period_start=date(2026, 9, 1),
)


def test_cost_is_the_sum_of_every_token_class_at_its_price_per_million():
    assert cost_microusd(input_tokens=1_000_000, output_tokens=0, prices=PRICES) == 4_000_000
    assert (
        cost_microusd(
            input_tokens=1000,
            output_tokens=2000,
            cache_read_input_tokens=3000,
            cache_write_input_tokens=4000,
            prices=PRICES,
        )
        == 1000 * 4 + 2000 * 20 + 600 + 4000 * 5
    )
    usage = StructuredGenerationUsage(
        input_tokens=10,
        output_tokens=20,
        latency_milliseconds=5,
        cache_read_input_tokens=30,
        cache_write_input_tokens=40,
    )
    assert usage_cost_microusd(usage, PRICES) == 40 + 400 + 6 + 200


@pytest.mark.parametrize("tokens,expected", [(1, 1), (2, 1), (3, 2), (4, 2), (5, 3)])
def test_fractions_of_a_micro_dollar_round_half_up(tokens, expected):
    prices = ModelPrices(input="0.5000", output="0", cache_read="0", cache_write="0")
    assert cost_microusd(input_tokens=tokens, output_tokens=0, prices=prices) == expected


def test_the_estimate_is_the_largest_possible_cost_of_the_call():
    configuration = providers().hosted_model("design")
    request = structured_request(configuration, max_output_tokens=4096)
    characters = prompt_characters(request)
    assert characters == len(request.system_instruction) + len(
        hosted_user_message(request.input_payload_json)
    )
    expected = ceil(characters / 3.0) * 4 + (4096 + 16_000) * 20
    assert estimated_cost_microusd(request, configuration) == expected
    note = "The previous answer was not one complete JSON object; answer again."
    assert prompt_characters(request, note) == characters + len(note) + 1
    assert estimated_cost_microusd(request, configuration, note) >= expected


def _refusal(budget, request, configuration, store=None, project_id=None):
    async def run():
        if store is None:
            return await budget.refusal(request=request, configuration=configuration)
        token = _SCOPE.set(ProposalEvidenceScope(store, uuid4(), project_id or uuid4()))
        try:
            return await budget.refusal(request=request, configuration=configuration)
        finally:
            _SCOPE.reset(token)

    return asyncio.run(run())


def test_a_call_that_alone_exceeds_the_ceiling_is_refused_without_reading_the_store():
    configuration = providers().hosted_model("design")
    request = structured_request(configuration, max_output_tokens=64_000)
    assert estimated_cost_microusd(request, configuration) > CEILINGS.per_generation_microusd
    store = SpendingEvidence()
    assert _refusal(CEILINGS, request, configuration, store) == GENERATION_BUDGET_EXCEEDED
    assert store.reads == []


def test_the_project_and_the_total_ceilings_use_the_amounts_already_spent():
    configuration = providers().hosted_model("design")
    request = structured_request(configuration)
    estimate = estimated_cost_microusd(request, configuration)
    project = uuid4()
    within = SpendingEvidence(project=10_000_000 - estimate, total=60_000_000 - estimate)
    assert _refusal(CEILINGS, request, configuration, within, project) is None
    assert within.reads == [(project, None), (None, date(2026, 9, 1))]
    project_full = SpendingEvidence(project=10_000_000 - estimate + 1, total=0)
    assert _refusal(CEILINGS, request, configuration, project_full) == GENERATION_BUDGET_EXCEEDED
    assert len(project_full.reads) == 1
    total_full = SpendingEvidence(project=0, total=60_000_000 - estimate + 1)
    assert _refusal(CEILINGS, request, configuration, total_full) == GENERATION_BUDGET_EXCEEDED


def test_spending_that_cannot_be_read_refuses_the_hosted_call():
    configuration = providers().hosted_model("general")
    request = structured_request(configuration)
    assert _refusal(CEILINGS, request, configuration) == GENERATION_BUDGET_UNAVAILABLE
    assert (
        _refusal(CEILINGS, request, configuration, MemoryEvidence())
        == GENERATION_BUDGET_UNAVAILABLE
    )


def _hosted_success_snapshot(cost):
    return {
        "provider_kind": "ANTHROPIC_HOSTED",
        "status": "SUCCEEDED",
        "success": {"usage": {"input_tokens": 1, "output_tokens": 1, "cost_microusd": cost}},
        "failure": None,
    }


def test_recorded_costs_are_summed_from_successes_and_failures_and_local_results_cost_nothing():
    usage = StructuredGenerationUsage(input_tokens=5, output_tokens=6, latency_milliseconds=7)
    local = failed_structured_generation_result(
        provider_kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL,
        code=StructuredGenerationFailureCode.TIMEOUT,
        message="Synthetic timeout.",
        retryable=True,
        usage=usage,
    ).to_snapshot()
    assert "cost_microusd" not in local["failure"]["usage"]
    assert provider_result_cost_microusd(local) == 0
    assert usage.to_snapshot() == {
        "input_tokens": 5,
        "output_tokens": 6,
        "latency_milliseconds": 7,
    }
    assert provider_result_cost_microusd(_hosted_success_snapshot(398_736)) == 398_736
    refused = failed_structured_generation_result(
        provider_kind=StructuredGenerationProviderKind.ANTHROPIC_HOSTED,
        code=StructuredGenerationFailureCode.PROVIDER_REFUSED,
        message="Declined.",
        retryable=False,
        usage=StructuredGenerationUsage(
            input_tokens=5, output_tokens=6, latency_milliseconds=7, cost_microusd=250
        ),
    ).to_snapshot()
    assert provider_result_cost_microusd(refused) == 250
    no_answer = failed_structured_generation_result(
        provider_kind=StructuredGenerationProviderKind.ANTHROPIC_HOSTED,
        code=StructuredGenerationFailureCode.TIMEOUT,
        message="Timeout.",
        retryable=True,
    ).to_snapshot()
    assert "usage" not in no_answer["failure"]
    assert provider_result_cost_microusd(no_answer) == 0
    assert provider_result_cost_microusd({"success": {"usage": {"cost_microusd": True}}}) == 0


def test_the_report_follows_the_usage_and_budget_contract():
    assert CEILINGS.report(1_250_000) == {
        "currency": "USD",
        "per_generation_microusd": 1_500_000,
        "per_project_microusd": 10_000_000,
        "total_microusd": 60_000_000,
        "spent_total_microusd": 1_250_000,
        "remaining_total_microusd": 58_750_000,
        "period_start": "2026-09-01",
    }
    assert CEILINGS.report(61_000_000)["remaining_total_microusd"] == 0
    assert CEILINGS.report(None)["remaining_total_microusd"] is None


def test_ceilings_come_from_the_configuration_and_must_be_ordered():
    budget = GenerationBudget.from_settings(providers().budget)
    assert budget == GenerationBudget(1_500_000, 10_000_000, 60_000_000, None)
    for values in ((0, 1, 2), (3, 2, 4), (1, 3, 2), (1.5, 2, 3), (True, 2, 3)):
        with pytest.raises(ValueError):
            GenerationBudget(*values)
