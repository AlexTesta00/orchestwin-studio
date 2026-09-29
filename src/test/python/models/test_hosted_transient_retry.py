from __future__ import annotations

import asyncio
import json
from functools import partial
from uuid import uuid4

import anthropic
import pytest

from orchestwin.models.anthropic_hosted import build_anthropic_adapter
from orchestwin.models.generation_budget import GenerationBudget
from orchestwin.models.generation_routing import RoutingProposalGenerator
from orchestwin.models.hosted_configuration import ModelRoutes
from orchestwin.models.model_proposals import ModelTeamProposalAdapter
from orchestwin.models.openai_compatible import OpenAICompatibleHttpResponse
from orchestwin.models.openai_hosted import build_openai_hosted_adapter
from orchestwin.models.proposal_evidence import _SCOPE, ProposalEvidenceScope
from orchestwin.models.proposal_generation import (
    PROVIDER_RETRY,
    TRANSIENT_RETRY_SECONDS,
    ProposalGenerationError,
    ProposalGenerator,
)
from orchestwin.models.structured_generation import (
    StructuredGenerationFailureCode,
    StructuredGenerationProviderKind,
    StructuredGenerationUsage,
    failed_structured_generation_result,
)
from src.test.python.models import test_fake_team_proposal_adapter as team_fixtures
from src.test.python.models.test_hosted_generation import Review
from src.test.python.models.test_hosted_support import (
    GATEWAY_KEY,
    TEST_KEY,
    FakeAnthropicClient,
    SpendingEvidence,
    connection_error,
    message,
    providers,
    status_error,
)
from src.test.python.models.test_model_proposals import make_generator
from src.test.python.models.test_proposal_evidence import Command

Code = StructuredGenerationFailureCode
BUDGET = GenerationBudget(1_500_000, 10_000_000, 60_000_000)
VALID = {"assessment": "Clear."}
TOO_LONG = {"assessment": "x" * 41}
TEAM_OUTPUT = {"rationale": "A compact team fits the brief.", "suggestions": []}
OVERLOADED = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
SLOW_DOWN = {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}
BILLING = {"type": "error", "error": {"type": "billing_error", "message": "no credit"}}
GRAMMAR_TOO_LARGE = {
    "type": "error",
    "error": {"type": "invalid_request_error", "message": "The compiled grammar is too large."},
}
RETIRED_KINDS = ["HTTP_REQUEST", "HTTP_RESPONSE", "PROVIDER_RESULT", "APPLICATION_RESULT"]
ANSWERED_KINDS = ["HTTP_REQUEST", "HTTP_RESPONSE", "PROVIDER_RESULT"]


class Pauses:
    def __init__(self):
        self.calls = []

    async def __call__(self, seconds):
        self.calls.append(seconds)


def overloaded():
    return status_error(anthropic.OverloadedError, 529, OVERLOADED)


def overloaded_in_stream():
    return status_error(anthropic.APIStatusError, 200, OVERLOADED)


def rate_limited():
    return status_error(anthropic.RateLimitError, 429, SLOW_DOWN)


def grammar_rejected():
    return status_error(anthropic.BadRequestError, 400, GRAMMAR_TOO_LARGE)


def anthropic_generator(*outcomes, entry="design", budget=BUDGET):
    configuration = providers().hosted_model(entry)
    client = FakeAnthropicClient(*outcomes)
    pauses = Pauses()
    port = build_anthropic_adapter(configuration, client=client, api_key=TEST_KEY)
    return ProposalGenerator(configuration, port, budget, pause=pauses), client, pauses


def run(generator, store, **options):
    scope = ProposalEvidenceScope(store, uuid4(), uuid4())

    async def call():
        token = _SCOPE.set(scope)
        try:
            return await generator.generate(
                task="team",
                context={"project_id": "p"},
                output_type=Review,
                instruction="Review the design.",
                **options,
            )
        finally:
            _SCOPE.reset(token)

    return asyncio.run(call()), scope


def failing(generator, store, code, **options):
    with pytest.raises(ProposalGenerationError) as failure:
        run(generator, store, **options)
    assert failure.value.code == code
    return failure.value


def kinds(store):
    return [[kind for kind, _, _ in events] for events in store.events.values()]


def results(store):
    return [
        next(payload for kind, payload, _ in events if kind == "PROVIDER_RESULT")
        for events in store.events.values()
    ]


def usage(**tokens):
    return StructuredGenerationUsage(
        **{"input_tokens": 0, "output_tokens": 0, "latency_milliseconds": 15_000, **tokens}
    )


class FailingPort:
    def __init__(self, *failures):
        self.failures = list(failures)
        self.requests = []

    async def generate(self, request, **options):
        self.requests.append(request)
        code, retryable, spent = self.failures.pop(0)
        return failed_structured_generation_result(
            provider_kind=StructuredGenerationProviderKind.ANTHROPIC_HOSTED,
            code=code,
            message="The hosted model provider failed.",
            retryable=retryable,
            usage=spent,
            output_mode=options.get("output_mode"),
        )


class GatewayTransport:
    def __init__(self, *statuses):
        self.statuses = list(statuses)
        self.calls = []

    async def post_json(self, **kwargs):
        self.calls.append(kwargs)
        status = self.statuses.pop(0)
        if status != 200:
            return OpenAICompatibleHttpResponse(status, b'{"error": {"message": "busy"}}', 3)
        body = {
            "id": "chatcmpl-1",
            "model": "example-model-1",
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(VALID)}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
        }
        return OpenAICompatibleHttpResponse(200, json.dumps(body).encode(), 5)


def test_the_pause_lasts_ten_seconds_and_waits_for_real_by_default():
    assert TRANSIENT_RETRY_SECONDS == 10.0
    assert PROVIDER_RETRY == "PROVIDER_RETRY"
    configuration = providers().hosted_model("design")
    port = build_anthropic_adapter(configuration, client=FakeAnthropicClient(), api_key=TEST_KEY)
    assert ProposalGenerator(configuration, port).pause is asyncio.sleep


@pytest.mark.parametrize("outcome", [overloaded, overloaded_in_stream])
def test_an_overloaded_provider_is_asked_once_more_after_the_pause(outcome):
    generator, client, pauses = anthropic_generator(outcome(), message(VALID))
    store = SpendingEvidence()
    output, scope = run(generator, store)
    assert output == Review(assessment="Clear.")
    assert pauses.calls == [10.0]
    first_call, second_call = client.messages.calls
    assert first_call == second_call
    assert kinds(store) == [RETIRED_KINDS, ANSWERED_KINDS]
    first_id, second_id = store.requests
    assert first_id != second_id
    failed, accepted = results(store)
    assert failed["failure"]["code"] == "PROVIDER_UNAVAILABLE"
    assert failed["failure"]["retryable"] is True and "usage" not in failed["failure"]
    assert accepted["status"] == "SUCCEEDED"
    assert store.events[first_id][-1][1] == {
        "status": "PROVIDER_UNAVAILABLE",
        "role": "PROVIDER_RETRY",
    }
    assert scope.related_generations == [
        {
            "role": "PROVIDER_RETRY",
            "generation_id": str(first_id),
            "request_hash": store.requests[first_id][0].content_hash,
            "code": "PROVIDER_UNAVAILABLE",
        }
    ]
    assert scope.request.request_id == second_id
    assert len(store.reads) == 4


@pytest.mark.parametrize(
    "second, code",
    [(overloaded, "PROVIDER_UNAVAILABLE"), (rate_limited, "RATE_LIMITED")],
)
def test_a_second_transient_failure_reaches_the_caller(second, code):
    generator, client, pauses = anthropic_generator(overloaded(), second(), message(VALID))
    store = SpendingEvidence()
    failure = failing(generator, store, code)
    assert len(client.messages.calls) == 2 and pauses.calls == [10.0]
    first_id, second_id = store.requests
    assert failure.request.request_id == second_id
    assert failure.result.failure.code.value == code
    assert failure.result.failure.retryable is True
    assert kinds(store) == [RETIRED_KINDS, ANSWERED_KINDS]
    assert store.events[first_id][-1][1]["role"] == "PROVIDER_RETRY"


def test_a_rate_limited_provider_is_asked_once_more():
    generator, client, pauses = anthropic_generator(rate_limited(), message(VALID))
    store = SpendingEvidence()
    output, scope = run(generator, store)
    assert output.assessment == "Clear."
    assert len(client.messages.calls) == 2 and pauses.calls == [10.0]
    first_id, _second_id = store.requests
    assert store.events[first_id][-1][1] == {"status": "RATE_LIMITED", "role": "PROVIDER_RETRY"}
    assert [item["code"] for item in scope.related_generations] == ["RATE_LIMITED"]


@pytest.mark.parametrize("status, code", [(429, "RATE_LIMITED"), (503, "PROVIDER_UNAVAILABLE")])
def test_the_openai_compatible_provider_is_asked_once_more(status, code):
    configuration = providers().hosted_model("review")
    transport = GatewayTransport(status, 200)
    pauses = Pauses()
    port = build_openai_hosted_adapter(configuration, api_key=GATEWAY_KEY, transport=transport)
    generator = ProposalGenerator(configuration, port, BUDGET, pause=pauses)
    output, scope = run(generator, SpendingEvidence())
    assert output.assessment == "Clear."
    assert len(transport.calls) == 2 and pauses.calls == [10.0]
    assert transport.calls[0]["payload"] == transport.calls[1]["payload"]
    assert [(item["role"], item["code"]) for item in scope.related_generations] == [
        ("PROVIDER_RETRY", code)
    ]


@pytest.mark.parametrize(
    "outcome, code",
    [
        (partial(status_error, anthropic.AuthenticationError, 401), "AUTHENTICATION_FAILED"),
        (partial(status_error, anthropic.APIStatusError, 402, BILLING), "PROVIDER_ERROR"),
        (partial(status_error, anthropic.DeadlineExceededError, 504), "TIMEOUT"),
        (partial(status_error, anthropic.InternalServerError, 504), "TIMEOUT"),
        (partial(connection_error, anthropic.APITimeoutError), "TIMEOUT"),
    ],
)
def test_other_failures_of_the_provider_are_not_asked_again(outcome, code):
    generator, client, pauses = anthropic_generator(outcome(), message(VALID))
    store = SpendingEvidence()
    failure = failing(generator, store, code)
    assert len(client.messages.calls) == 1 and pauses.calls == []
    assert len(store.requests) == 1 and kinds(store)[0][-1] == "PROVIDER_RESULT"
    assert failure.result.failure.code.value == code


@pytest.mark.parametrize(
    "code, retryable, spent, retried",
    [
        (Code.PROVIDER_UNAVAILABLE, True, None, True),
        (Code.RATE_LIMITED, True, None, True),
        (Code.RATE_LIMITED, True, usage(), True),
        (Code.PROVIDER_UNAVAILABLE, False, None, False),
        (Code.RATE_LIMITED, False, None, False),
        (Code.PROVIDER_UNAVAILABLE, True, usage(input_tokens=1200), False),
        (Code.RATE_LIMITED, True, usage(output_tokens=40), False),
        (Code.PROVIDER_UNAVAILABLE, True, usage(cache_read_input_tokens=100), False),
        (Code.PROVIDER_UNAVAILABLE, True, usage(cost_microusd=20), False),
        (Code.TIMEOUT, True, None, False),
        (Code.PROVIDER_ERROR, True, None, False),
        (Code.INCOMPLETE_OUTPUT, False, usage(input_tokens=90, output_tokens=24_192), False),
    ],
)
def test_only_an_unbilled_retryable_unavailability_or_rate_limit_is_asked_again(
    code, retryable, spent, retried
):
    port = FailingPort((code, retryable, spent), (code, retryable, spent))
    pauses = Pauses()
    generator = ProposalGenerator(providers().hosted_model("design"), port, BUDGET, pause=pauses)
    store = SpendingEvidence()
    failing(generator, store, code.value)
    assert len(port.requests) == (2 if retried else 1)
    assert pauses.calls == ([10.0] if retried else [])
    assert len(store.requests) == len(port.requests)


def test_a_caller_can_turn_the_transient_retry_off():
    generator, client, pauses = anthropic_generator(overloaded(), message(VALID))
    store = SpendingEvidence()
    failing(generator, store, "PROVIDER_UNAVAILABLE", retry_transient_failures=False)
    assert len(client.messages.calls) == 1 and pauses.calls == []
    assert kinds(store) == [ANSWERED_KINDS]
    routed, routed_client, routed_pauses = anthropic_generator(overloaded(), message(VALID))
    router = RoutingProposalGenerator({"general": routed}, ModelRoutes(default="general"))
    failing(router, SpendingEvidence(), "PROVIDER_UNAVAILABLE", retry_transient_failures=False)
    assert len(routed_client.messages.calls) == 1 and routed_pauses.calls == []


def test_the_budget_is_checked_again_before_the_second_request():
    class Rising(SpendingEvidence):
        async def spent_microusd(self, *, project_id=None, since=None):
            self.reads.append((project_id, since))
            if project_id is not None and len(self.reads) > 2:
                return 9_999_000
            return 0

    generator, client, pauses = anthropic_generator(overloaded(), message(VALID))
    store = Rising()
    failure = failing(generator, store, "GENERATION_BUDGET_EXCEEDED")
    assert len(client.messages.calls) == 1 and pauses.calls == [10.0]
    assert len(store.requests) == 1 and len(store.reads) == 3
    assert failure.result is None
    [first_id] = store.requests
    assert failure.request.request_id != first_id
    assert store.events[first_id][-1][1] == {
        "status": "PROVIDER_UNAVAILABLE",
        "role": "PROVIDER_RETRY",
    }


def test_a_retried_generation_is_still_negotiated_and_answered_again_after_a_schema_error():
    generator, client, pauses = anthropic_generator(
        overloaded(), grammar_rejected(), message(TOO_LONG), message(VALID)
    )
    store = SpendingEvidence()
    output, scope = run(generator, store)
    assert output.assessment == "Clear."
    assert len(client.messages.calls) == 4 and pauses.calls == [10.0]
    assert [item["role"] for item in scope.related_generations] == [
        "PROVIDER_RETRY",
        "SCHEMA_NEGOTIATION",
        "SCHEMA_RETRY",
    ]
    assert [item["output_mode"] for item in results(store)] == [
        "STRICT",
        "STRICT",
        "PROMPTED",
        "PROMPTED",
    ]


def test_a_transient_failure_after_a_schema_retry_sends_the_same_request_again():
    generator, client, pauses = anthropic_generator(
        message(TOO_LONG), rate_limited(), message(VALID)
    )
    output, scope = run(generator, SpendingEvidence())
    assert output.assessment == "Clear."
    first, second, third = client.messages.calls
    assert second == third and second != first
    assert [item["role"] for item in scope.related_generations] == [
        "SCHEMA_RETRY",
        "PROVIDER_RETRY",
    ]
    assert pauses.calls == [10.0]


def test_a_team_proposal_survives_an_overloaded_provider_and_names_the_retired_generation():
    configuration = providers().hosted_model("general")
    client = FakeAnthropicClient(
        overloaded_in_stream(), message(TEAM_OUTPUT, model="claude-sonnet-5")
    )
    pauses = Pauses()
    generator = ProposalGenerator(
        configuration,
        build_anthropic_adapter(configuration, client=client, api_key=TEST_KEY),
        BUDGET,
        pause=pauses,
    )
    request = team_fixtures.build_request()
    store = SpendingEvidence()
    result = asyncio.run(
        Command(store, lambda: ModelTeamProposalAdapter(generator).propose(request)).run(
            owner_user_id=uuid4(), project_id=uuid4()
        )
    )
    assert result.proposal.provider_id == generator.provider_id
    assert pauses.calls == [10.0]
    first_id, second_id = store.requests
    assert kinds(store) == [
        RETIRED_KINDS,
        [*ANSWERED_KINDS, "ADAPTER_ACCEPTED", "APPLICATION_RESULT"],
    ]
    accepted = store.events[second_id][3][1]
    assert accepted["related_generations"] == [
        {
            "role": "PROVIDER_RETRY",
            "generation_id": str(first_id),
            "request_hash": store.requests[first_id][0].content_hash,
            "code": "PROVIDER_UNAVAILABLE",
        }
    ]
    assert store.events[first_id][1][1]["status_code"] == 200
    assert TEST_KEY not in repr(store.events)


def test_the_local_route_never_waits_and_never_asks_again(tmp_path):
    local, transport = make_generator(tmp_path, VALID, status=503)
    pauses = Pauses()
    generator = ProposalGenerator(local.configuration, local.port, pause=pauses)
    with pytest.raises(ProposalGenerationError) as failure:
        asyncio.run(
            generator.generate(
                task="team",
                context={"project_id": "p"},
                output_type=Review,
                instruction="Review.",
            )
        )
    assert failure.value.code == "PROVIDER_UNAVAILABLE"
    assert failure.value.result.failure.retryable is True
    assert len(transport.calls) == 1 and pauses.calls == []
