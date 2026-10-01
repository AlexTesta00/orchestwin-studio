from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import anthropic
import httpx2

from orchestwin.models.claude_code_cli import SYSTEM_PROMPT_OPTION, ProcessOutcome
from orchestwin.models.hosted_configuration import (
    ProvidersConfiguration,
    parse_providers_configuration,
)
from orchestwin.models.structured_generation import (
    create_structured_generation_request,
    create_structured_json_schema,
)
from src.test.python.models.test_proposal_evidence import MemoryEvidence

REPOSITORY = Path(__file__).resolve().parents[4]
EXAMPLE_PROVIDERS = REPOSITORY / "scripts" / "model-providers.example.json"
CLAUDE_CODE_EXAMPLE = REPOSITORY / "scripts" / "model-providers.claude-code.example.json"
CLAUDE_CODE_PRICES = {"input": "0", "output": "0", "cache_read": "0", "cache_write": "0"}
CLAUDE_VERSION_LINE = b"2.1.286 (Claude Code)\n"
CLAUDE_AUTH_STATUS = {
    "loggedIn": True,
    "authMethod": "claude.ai",
    "apiProvider": "firstParty",
    "email": "owner@example.com",
    "subscriptionType": "max",
}
CLAUDE_USAGE = {
    "input_tokens": 1200,
    "output_tokens": 900,
    "cache_creation_input_tokens": 50,
    "cache_read_input_tokens": 100,
    "output_tokens_details": {"thinking_tokens": 300},
}
CLAUDE_MODEL_USAGE = {
    "claude-opus-5-5": {
        "inputTokens": 1350,
        "outputTokens": 900,
        "maxOutputTokens": 128_000,
        "contextWindow": 1_000_000,
    },
    "claude-haiku-4-5-20251001": {
        "inputTokens": 400,
        "outputTokens": 20,
        "maxOutputTokens": 64_000,
        "contextWindow": 200_000,
    },
}
TEST_KEY = "test-key-not-real-anthropic-0001"
GATEWAY_KEY = "test-key-not-real-gateway-0002"
ANTHROPIC_KEY_ENV = "ORCHESTWIN_ANTHROPIC_API_KEY"
GATEWAY_KEY_ENV = "ORCHESTWIN_GATEWAY_API_KEY"
PRICES = {"input": "4.00", "output": "20.00", "cache_read": "0.20", "cache_write": "5.00"}
REVIEW_SCHEMA = {
    "additionalProperties": False,
    "properties": {
        "assessment": {"maxLength": 40, "minLength": 1, "title": "Assessment", "type": "string"},
        "score": {"maximum": 1, "minimum": 0, "title": "Score", "type": "number"},
        "tags": {
            "items": {"enum": ["accessible", "fast"], "type": "string"},
            "maxItems": 2,
            "title": "Tags",
            "type": "array",
        },
    },
    "required": ["assessment", "score", "tags"],
    "title": "Review",
    "type": "object",
}
VALID_REVIEW = {"assessment": "Clear flow.", "score": 0.8, "tags": ["fast"]}


def model_entry(entry_id, provider, model, **changes):
    entry = {
        "id": entry_id,
        "provider": provider,
        "model": model,
        "effort": "high",
        "context_window_tokens": 1_000_000,
        "max_output_tokens": 64_000,
        "reasoning_allowance_tokens": 16_000,
        "timeout_seconds": 1200,
        "characters_per_token": 3.0,
        "prices": dict(PRICES),
    }
    entry.update(changes)
    return entry


def providers_document():
    return {
        "schema_version": 1,
        "providers": [
            {"id": "anthropic", "kind": "ANTHROPIC_HOSTED", "api_key_env": ANTHROPIC_KEY_ENV},
            {
                "id": "gateway",
                "kind": "OPENAI_COMPATIBLE_HOSTED",
                "api_key_env": GATEWAY_KEY_ENV,
                "base_url": "https://llm.example.com",
            },
        ],
        "models": [
            model_entry("design", "anthropic", "claude-opus-5-5"),
            model_entry(
                "general",
                "anthropic",
                "claude-sonnet-5",
                effort="medium",
                max_output_tokens=32_000,
                reasoning_allowance_tokens=8_000,
                timeout_seconds=600,
                prices={
                    "input": "2.00",
                    "output": "10.00",
                    "cache_read": "0.20",
                    "cache_write": "2.50",
                },
            ),
            model_entry(
                "review",
                "gateway",
                "example-model-1",
                effort=None,
                max_output_tokens=16_000,
                reasoning_allowance_tokens=0,
                timeout_seconds=300,
                characters_per_token=4.0,
            ),
        ],
        "routes": {
            "default": "general",
            "tasks": {"design": "design"},
            "purposes": {"DESIGN_TWIN_REVIEW": "review"},
        },
        "budget": {"per_generation_usd": "1.50", "per_project_usd": "10.00", "total_usd": "60.00"},
    }


def providers(document=None) -> ProvidersConfiguration:
    source = providers_document() if document is None else document
    return parse_providers_configuration(json.dumps(source).encode("utf-8"))


def changed(document, change):
    updated = copy.deepcopy(document)
    change(updated)
    return updated


def structured_request(configuration, schema_payload=None, *, max_output_tokens=4096):
    payload = REVIEW_SCHEMA if schema_payload is None else schema_payload
    schema = create_structured_json_schema(
        schema_id="proposal-team-v1", version_number=1, schema_payload=payload
    )
    return create_structured_generation_request(
        request_id=uuid4(),
        task_id="proposal-team-v1",
        expected_identity=configuration.identity,
        output_schema=schema,
        system_instruction="Produce one JSON object.",
        input_payload={"context": {"project_id": str(uuid4())}, "output_schema": payload},
        allowed_evidence_refs=(),
        prompt_version_ref="proposal-team-v1",
        temperature=configuration.temperature,
        max_output_tokens=max_output_tokens,
        timeout_seconds=configuration.timeout_seconds,
    )


def message(
    payload=None,
    *,
    stop_reason="end_turn",
    model="claude-opus-5-5",
    usage=None,
    text=None,
    message_id="msg_synthetic_0001",
):
    body = json.dumps(VALID_REVIEW if payload is None else payload)
    return anthropic.types.Message.model_validate(
        {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [
                {"type": "thinking", "thinking": "", "signature": "synthetic-signature"},
                {"type": "text", "text": body if text is None else text},
            ],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": usage
            or {
                "input_tokens": 1200,
                "output_tokens": 900,
                "cache_read_input_tokens": 100,
                "cache_creation_input_tokens": 50,
            },
        }
    )


def status_error(error_type, status, body=None):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    content = body if body is not None else {"type": "error", "error": {"type": "api_error"}}
    response = httpx2.Response(status, request=request, json=content)
    return error_type("synthetic provider error", response=response, body=content)


def connection_error(error_type=anthropic.APIConnectionError):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return error_type(request=request)


class FakeStream:
    def __init__(self, outcome):
        self.outcome = outcome

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get_final_message(self):
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if callable(self.outcome):
            return await self.outcome()
        return self.outcome


class FakeMessages:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(self.outcomes.pop(0))


class FakeModels:
    def __init__(self, infos):
        self.infos = dict(infos)
        self.calls = []

    async def retrieve(self, model_id, **kwargs):
        self.calls.append((model_id, kwargs))
        outcome = self.infos[model_id]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeAnthropicClient:
    def __init__(self, *outcomes, models=None):
        self.messages = FakeMessages(outcomes)
        self.models = FakeModels(models or {})
        self.closed = False

    async def close(self):
        self.closed = True


def model_info(model_id, *, max_input_tokens=1_000_000, max_tokens=128_000):
    return anthropic.types.ModelInfo.model_validate(
        {
            "id": model_id,
            "type": "model",
            "display_name": model_id,
            "created_at": "2026-09-01T00:00:00Z",
            "max_input_tokens": max_input_tokens,
            "max_tokens": max_tokens,
        }
    )


class SpendingEvidence(MemoryEvidence):
    def __init__(self, *, project=0, total=0, fail=None):
        super().__init__(fail)
        self.project, self.total, self.reads = project, total, []

    async def spent_microusd(self, *, project_id=None, since=None):
        self.reads.append((project_id, since))
        return self.project if project_id is not None else self.total


def run(coroutine):
    return asyncio.run(coroutine)


def claude_code_document(executable=None):
    return {
        "schema_version": 1,
        "providers": [{"id": "claude-code", "kind": "CLAUDE_CODE_CLI", "executable": executable}],
        "models": [
            model_entry(
                "design",
                "claude-code",
                "claude-opus-5-5",
                reasoning_allowance_tokens=64_000,
                prices=dict(CLAUDE_CODE_PRICES),
            ),
            model_entry(
                "general",
                "claude-code",
                "claude-opus-5-5",
                effort="medium",
                reasoning_allowance_tokens=64_000,
                timeout_seconds=900,
                prices=dict(CLAUDE_CODE_PRICES),
            ),
        ],
        "routes": {"default": "general", "tasks": {"design": "design"}, "purposes": {}},
        "budget": {"per_generation_usd": "1.50", "per_project_usd": "10.00", "total_usd": "60.00"},
    }


def claude_answer(
    payload=None,
    *,
    strict=True,
    stop_reason=None,
    subtype="success",
    is_error=False,
    api_error_status=None,
    result=None,
    usage=None,
    model_usage=None,
    session_id="session-synthetic-0001",
):
    output = VALID_REVIEW if payload is None else payload
    document = {
        "type": "result",
        "subtype": subtype,
        "is_error": is_error,
        "api_error_status": api_error_status,
        "duration_ms": 18_000,
        "duration_api_ms": 17_500,
        "num_turns": 2 if strict else 1,
        "result": result if result is not None else ("Done." if strict else json.dumps(output)),
        "stop_reason": stop_reason or ("tool_use" if strict else "end_turn"),
        "session_id": session_id,
        "total_cost_usd": 0.4213,
        "usage": dict(CLAUDE_USAGE) if usage is None else usage,
        "modelUsage": copy.deepcopy(CLAUDE_MODEL_USAGE) if model_usage is None else model_usage,
        "uuid": "00000000-0000-4000-8000-00000000c1a0",
    }
    if strict:
        document["structured_output"] = output
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def finished(stdout=b"", *, status=0, stderr=b""):
    return ProcessOutcome(status=status, stdout=stdout, stderr=stderr)


@dataclass(frozen=True)
class ClaudeCall:
    arguments: list
    stdin: bytes
    environment: dict
    working_directory: Path
    timeout_seconds: float
    system: str | None


class FakeClaudeRunner:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def __call__(self, arguments, stdin, environment, working_directory, timeout_seconds):
        words = list(arguments)
        system = None
        if SYSTEM_PROMPT_OPTION in words:
            prompt_file = Path(words[words.index(SYSTEM_PROMPT_OPTION) + 1])
            if prompt_file.is_file():
                system = prompt_file.read_bytes().decode("utf-8")
        self.calls.append(
            ClaudeCall(words, stdin, dict(environment), working_directory, timeout_seconds, system)
        )
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return await outcome()
        return outcome


def readiness_runner(auth=None, *, version=CLAUDE_VERSION_LINE):
    status = CLAUDE_AUTH_STATUS if auth is None else auth
    return FakeClaudeRunner(finished(version), finished(json.dumps(status).encode("utf-8")))
