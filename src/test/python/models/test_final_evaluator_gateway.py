from __future__ import annotations

import asyncio
import json
from uuid import UUID

import pytest

from orchestwin.evaluation.field_scope_prompt import FIELD_SCOPE_PROMPT_VERSION
from orchestwin.models.final_evaluator_gateway import (
    FinalEvaluatorGenerationPort,
    model_visible_messages,
    validate_final_completion,
)
from orchestwin.models.final_evaluator_session import SessionHttpResponse, content_hash
from orchestwin.models.openai_compatible import OpenAICompatibleLocalConfig, _request_payload
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationStatus,
    create_structured_generation_request,
    create_structured_json_schema,
)

from .final_session_support import make_session
from .test_strict_evaluator_json import GOOD, SCHEMA


def request_for(session):
    return create_structured_generation_request(
        request_id=UUID(int=7301),
        task_id="user-twin-evaluation-v1",
        expected_identity=ModelRuntimeIdentity(**session.identity),
        output_schema=create_structured_json_schema(
            schema_id="evaluator-test", version_number=1, schema_payload=SCHEMA
        ),
        system_instruction="Use only supplied evidence and the required JSON object.",
        input_payload={"notice": "Synthetic transport fixture, not a model result."},
        allowed_evidence_refs=("E-001",),
        prompt_version_ref=FIELD_SCOPE_PROMPT_VERSION,
        temperature=0.0,
        max_output_tokens=1024,
        timeout_seconds=90,
    )


def completion(session, request):
    return {
        "id": "fixture-transport-response",
        "model": "ut-evaluator-s67-final",
        "model_identity": session.identity,
        "choices": [
            {"finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(GOOD)}}
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
        "orchestwin_serving": {
            "output_repair_used": False,
            "model_visible_messages_sha256": content_hash(
                {"messages": model_visible_messages(request)}
            ),
        },
    }


def test_metadata_is_built_by_repository_client(tmp_path):
    session = make_session(tmp_path)
    request = request_for(session)
    config = OpenAICompatibleLocalConfig(
        base_url=session.base_url,
        model_name="ut-evaluator-s67-final",
        expected_identity=request.expected_identity,
    )
    wire = _request_payload(config, request)
    assert wire["metadata"]["orchestwin_task_id"] == request.task_id
    assert wire["metadata"]["orchestwin_prompt_version_ref"] == FIELD_SCOPE_PROMPT_VERSION
    assert wire["metadata"]["allowed_evidence_refs"] == ["E-001"]
    assert wire["metadata"]["orchestwin_request_hash"] == request.content_hash


@pytest.mark.parametrize(
    "failure", ["extra_root", "identity", "prompt", "repair", "length", "usage", "duplicate"]
)
def test_raw_completion_contract_rejected(tmp_path, failure):
    session = make_session(tmp_path)
    request = request_for(session)
    value = completion(session, request)
    if failure == "extra_root":
        value["choices"][0]["message"]["content"] = json.dumps({**GOOD, "severity": "minor"})
    elif failure == "identity":
        value["model_identity"]["adapter_id"] = "other"
    elif failure == "prompt":
        value["orchestwin_serving"]["model_visible_messages_sha256"] = "0" * 64
    elif failure == "repair":
        value["orchestwin_serving"]["output_repair_used"] = True
    elif failure == "length":
        value["choices"][0]["finish_reason"] = "length"
    elif failure == "usage":
        value["usage"]["total_tokens"] = 1
    elif failure == "duplicate":
        value["choices"][0]["message"]["content"] = '{"findings":[],"findings":[]}'
    with pytest.raises(ValueError):
        validate_final_completion(json.dumps(value).encode(), request, session)


def test_one_exchange_and_no_output_repair(tmp_path):
    session = make_session(tmp_path)
    request = request_for(session)
    calls = []
    raw = json.dumps(completion(session, request)).encode()

    def exchange(_session, method, path, body, timeout):
        calls.append((method, path, json.loads(body), timeout))
        return SessionHttpResponse(200, raw, 25)

    result = asyncio.run(FinalEvaluatorGenerationPort(session, exchange=exchange).generate(request))
    assert result.status is StructuredGenerationStatus.SUCCEEDED
    assert json.loads(result.success.payload_json) == GOOD
    assert len(calls) == 1
    assert calls[0][2]["metadata"]["allowed_evidence_refs"] == ["E-001"]


def test_invalid_output_fails_without_retry(tmp_path):
    session = make_session(tmp_path)
    request = request_for(session)
    calls = []

    def exchange(*_args):
        calls.append(True)
        return SessionHttpResponse(200, b"{}", 1)

    result = asyncio.run(FinalEvaluatorGenerationPort(session, exchange=exchange).generate(request))
    assert result.status is StructuredGenerationStatus.FAILED
    assert result.failure.retryable is False
    assert len(calls) == 1
