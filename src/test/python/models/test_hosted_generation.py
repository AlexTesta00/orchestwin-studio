from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict, Field

from orchestwin.models.anthropic_hosted import build_anthropic_adapter
from orchestwin.models.generation_budget import GenerationBudget, estimated_cost_microusd
from orchestwin.models.hosted_schema import HOSTED_TASK_REQUEST
from orchestwin.models.model_proposals import ModelTeamProposalAdapter
from orchestwin.models.proposal_evidence import _SCOPE, ProposalEvidenceScope
from orchestwin.models.proposal_generation import ProposalGenerationError, ProposalGenerator
from orchestwin.models.structured_generation import (
    StructuredGenerationFinishReason,
    StructuredGenerationProviderKind,
    StructuredGenerationUsage,
    create_structured_generation_success,
    successful_structured_generation_result,
)
from src.test.python.models import test_fake_team_proposal_adapter as team_fixtures
from src.test.python.models.test_hosted_support import (
    TEST_KEY,
    FakeAnthropicClient,
    SpendingEvidence,
    message,
    providers,
)
from src.test.python.models.test_proposal_evidence import Command

BUDGET = GenerationBudget(1_500_000, 10_000_000, 60_000_000)


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assessment: str = Field(min_length=1, max_length=40)


class ScriptedPort:
    def __init__(self, *, kind=None, finish=StructuredGenerationFinishReason.STOP, **usage):
        self.kind, self.finish, self.requests, self.options = kind, finish, [], []
        self.usage = {"input_tokens": 100, "output_tokens": 50, **usage}

    async def generate(self, request, **options):
        self.requests.append(request)
        self.options.append(options)
        success = create_structured_generation_success(
            payload={"assessment": "Clear."},
            actual_identity=request.expected_identity,
            usage=StructuredGenerationUsage(latency_milliseconds=3, **self.usage),
            finish_reason=self.finish,
            provider_request_id="scripted",
        )
        kind = self.kind or StructuredGenerationProviderKind.ANTHROPIC_HOSTED
        return successful_structured_generation_result(provider_kind=kind, success=success)


def _generate(generator, *, store=None, max_output_tokens=None, project_id=None):
    async def run():
        options = {} if max_output_tokens is None else {"max_output_tokens": max_output_tokens}
        call = generator.generate(
            task="team",
            context={"project_id": str(project_id or uuid4())},
            output_type=Review,
            instruction="Review the design.",
            **options,
        )
        if store is None:
            return await call
        token = _SCOPE.set(ProposalEvidenceScope(store, uuid4(), project_id or uuid4()))
        try:
            return await call
        finally:
            _SCOPE.reset(token)

    return asyncio.run(run())


def hosted(port, entry="design", budget=BUDGET):
    return ProposalGenerator(providers().hosted_model(entry), port, budget)


def test_a_hosted_generation_is_accepted_and_uses_the_hosted_request_values():
    port = ScriptedPort()
    store = SpendingEvidence()
    output = _generate(hosted(port), store=store)
    assert output == Review(assessment="Clear.")
    [request] = port.requests
    configuration = providers().hosted_model("design")
    assert request.expected_identity == configuration.identity
    assert request.temperature == 1.0
    assert request.timeout_seconds == 1200
    assert request.max_output_tokens == 8192
    assert len(store.reads) == 2
    assert [kind for kind, _, _ in store.events[request.request_id]] == ["PROVIDER_RESULT"]


def test_the_result_kind_must_be_the_kind_of_the_configuration():
    port = ScriptedPort(kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL)
    with pytest.raises(ProposalGenerationError, match="IDENTITY_MISMATCH"):
        _generate(hosted(port), store=SpendingEvidence())
    openai_kind = ScriptedPort(kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_HOSTED)
    with pytest.raises(ProposalGenerationError, match="IDENTITY_MISMATCH"):
        _generate(hosted(openai_kind), store=SpendingEvidence())


@pytest.mark.parametrize(
    "usage,finish,accepted",
    [
        ({"output_tokens": 8192 + 16_000}, StructuredGenerationFinishReason.STOP, True),
        ({"output_tokens": 8192 + 16_001}, StructuredGenerationFinishReason.STOP, False),
        ({"output_tokens": 9000}, StructuredGenerationFinishReason.STOP, True),
        ({"output_tokens": 0}, StructuredGenerationFinishReason.STOP, False),
        ({"input_tokens": 0}, StructuredGenerationFinishReason.STOP, False),
        (
            {"input_tokens": 0, "cache_read_input_tokens": 90},
            StructuredGenerationFinishReason.STOP,
            True,
        ),
        (
            {"input_tokens": 0, "cache_write_input_tokens": 90},
            StructuredGenerationFinishReason.STOP,
            True,
        ),
        ({}, StructuredGenerationFinishReason.LENGTH, False),
    ],
)
def test_completeness_counts_the_reasoning_allowance(usage, finish, accepted):
    generator = hosted(ScriptedPort(finish=finish, **usage))
    if accepted:
        assert _generate(generator, store=SpendingEvidence()).assessment == "Clear."
    else:
        with pytest.raises(ProposalGenerationError, match="INCOMPLETE_OUTPUT"):
            _generate(generator, store=SpendingEvidence())


def test_the_window_uses_the_characters_per_token_of_the_entry():
    configuration = providers().hosted_model("design")
    narrow = replace(
        configuration,
        entry=configuration.entry.model_copy(update={"context_window_tokens": 8192 + 16_000}),
    )
    port = ScriptedPort()
    store = SpendingEvidence()
    with pytest.raises(ProposalGenerationError, match="CONTEXT_BUDGET_EXCEEDED"):
        _generate(ProposalGenerator(narrow, port, BUDGET), store=store)
    assert port.requests == [] and store.requests == {} and store.reads == []


def test_the_budget_refuses_before_any_provider_evidence_or_call():
    port = ScriptedPort()
    store = SpendingEvidence(project=9_999_999)
    with pytest.raises(ProposalGenerationError) as failure:
        _generate(hosted(port), store=store)
    assert failure.value.code == "GENERATION_BUDGET_EXCEEDED"
    assert failure.value.request is not None
    assert port.requests == [] and store.requests == {} and store.events == {}
    expensive = ScriptedPort()
    with pytest.raises(ProposalGenerationError, match="GENERATION_BUDGET_EXCEEDED"):
        _generate(hosted(expensive), store=SpendingEvidence(), max_output_tokens=64_000)
    assert expensive.requests == []


def test_without_an_evidence_scope_a_hosted_call_is_refused():
    port = ScriptedPort()
    with pytest.raises(ProposalGenerationError, match="GENERATION_BUDGET_UNAVAILABLE"):
        _generate(hosted(port))
    assert port.requests == []
    assert _generate(hosted(ScriptedPort(), budget=None)).assessment == "Clear."


def test_a_team_proposal_runs_end_to_end_on_the_anthropic_adapter():
    configuration = providers().hosted_model("general")
    output = {"rationale": "A compact team fits the brief.", "suggestions": []}
    client = FakeAnthropicClient(message(output, model="claude-sonnet-5"))
    generator = ProposalGenerator(
        configuration,
        build_anthropic_adapter(configuration, client=client, api_key=TEST_KEY),
        BUDGET,
    )
    request = team_fixtures.build_request()
    store = SpendingEvidence()
    result = asyncio.run(
        Command(store, lambda: ModelTeamProposalAdapter(generator).propose(request)).run(
            owner_user_id=uuid4(), project_id=uuid4()
        )
    )
    assert result.proposal.provider_id == generator.provider_id
    [generation_id] = store.requests
    events = store.events[generation_id]
    assert [kind for kind, _, _ in events] == [
        "HTTP_REQUEST",
        "HTTP_RESPONSE",
        "PROVIDER_RESULT",
        "ADAPTER_ACCEPTED",
        "APPLICATION_RESULT",
    ]
    usage = events[2][1]["success"]["usage"]
    assert usage["cost_microusd"] == 1200 * 2 + 900 * 10 + 20 + 125
    [call] = client.messages.calls
    assert call["model"] == "claude-sonnet-5"
    assert call["max_tokens"] == 8192 + 8000
    assert "temperature" not in call and "thinking" not in call
    content = call["messages"][0]["content"]
    assert content.startswith("<input>\n") and content.endswith(HOSTED_TASK_REQUEST)
    payload = content.removeprefix("<input>\n").split("\n</input>\n\n")[0]
    assert json.loads(payload)["context"]["brief_version"]
    assert TEST_KEY not in repr(store.events)


def test_a_different_served_model_is_rejected_by_the_generator():
    configuration = providers().hosted_model("design")
    client = FakeAnthropicClient(message({"assessment": "Clear."}, model="claude-opus-5"))
    generator = ProposalGenerator(
        configuration,
        build_anthropic_adapter(configuration, client=client, api_key=TEST_KEY),
        BUDGET,
    )
    with pytest.raises(ProposalGenerationError, match="IDENTITY_MISMATCH"):
        _generate(generator, store=SpendingEvidence())


def test_the_estimate_depends_on_the_prices_and_allowance_of_the_entry():
    port = ScriptedPort()
    _generate(hosted(port), store=SpendingEvidence())
    request = port.requests[0]
    design = estimated_cost_microusd(request, providers().hosted_model("design"))
    general = estimated_cost_microusd(request, providers().hosted_model("general"))
    assert design > general > 0
