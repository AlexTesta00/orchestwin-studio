from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from orchestwin.evaluation.field_scope_prompt import (
    FIELD_SCOPE_PROMPT_VERSION,
    field_scope_instruction,
)
from orchestwin.evaluation.model_evaluator import (
    ModelGatewayEvaluationError,
    ModelGatewayUserTwinEvaluator,
    _output_schema_payload,
    _system_instruction,
)
from orchestwin.models.structured_generation import StructuredGenerationFinishReason

from .test_model_evaluator import _evaluator, _identity, _Port, _request, _valid_payload


def test_original_default_prompt_and_version_remain_unchanged():
    gateway = _evaluator(_Port(_identity(), _valid_payload()))
    assert gateway.system_instruction == _system_instruction()
    assert gateway.configuration.prompt_version_ref == "ut-eval-v6"


def test_field_scope_prompt_names_levels_without_forcing_abstention():
    value = field_scope_instruction(_system_instruction(), _output_schema_payload())
    assert (
        "severity and requires_human_validation are properties of each individual object" in value
    )
    assert "these serialization rules do not dictate a positive finding or an abstention" in value
    assert FIELD_SCOPE_PROMPT_VERSION == "s12-local-inference-contract-v2-field-scope"


@pytest.mark.parametrize("field", ["severity", "requires_human_validation"])
def test_root_fields_rejected_by_real_evaluator(field):
    value = _valid_payload()
    value[field] = True
    with pytest.raises(ModelGatewayEvaluationError):
        asyncio.run(_evaluator(_Port(_identity(), value)).evaluate(_request()))


def test_nested_additional_property_rejected():
    value = _valid_payload()
    value["findings"][0]["unexpected"] = True
    with pytest.raises(ModelGatewayEvaluationError):
        asyncio.run(_evaluator(_Port(_identity(), value)).evaluate(_request()))


def test_truncated_valid_json_is_not_success():
    class LengthPort(_Port):
        async def generate(self, request):
            result = await super().generate(request)
            from orchestwin.models.structured_generation import create_structured_generation_success

            success = create_structured_generation_success(
                payload=json.loads(result.success.payload_json),
                actual_identity=self.identity,
                usage=result.success.usage,
                finish_reason=StructuredGenerationFinishReason.LENGTH,
                provider_request_id="truncated-test",
            )
            return replace(result, success=success)

    with pytest.raises(ModelGatewayEvaluationError):
        asyncio.run(_evaluator(LengthPort(_identity(), _valid_payload())).evaluate(_request()))


def test_custom_prompt_used_in_actual_generation_request():
    port = _Port(_identity(), _valid_payload())
    base = _evaluator(port)
    prompt = field_scope_instruction(_system_instruction(), _output_schema_payload())
    gateway = ModelGatewayUserTwinEvaluator(
        configuration=replace(base.configuration, prompt_version_ref=FIELD_SCOPE_PROMPT_VERSION),
        model_identity=_identity(),
        generation_port=port,
        request_id_factory=base._request_id_factory,
        clock=base._clock,
        system_instruction=prompt,
    )
    asyncio.run(gateway.evaluate(_request()))
    assert port.request.system_instruction == prompt
    assert port.request.prompt_version_ref == FIELD_SCOPE_PROMPT_VERSION
    assert json.loads(port.request.output_schema.canonical_schema_json) == _output_schema_payload()
