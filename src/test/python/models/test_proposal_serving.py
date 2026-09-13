"""Proposal serving controls with an injected tensor/model double, no GPU."""

import importlib.util
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from .test_model_proposals import make_generator


def server_module():
    path = Path(__file__).resolve().parents[4] / "environments/training/serve_proposal_model.py"
    spec = importlib.util.spec_from_file_location("proposal_serving_contract_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def state_and_payload(tmp_path, *, tokens=(8, 9, 2), temperature=0.6):
    generator, _ = make_generator(tmp_path, {})

    class Tensor:
        shape = (1, 4)

        def to(self, _device):
            return self

    class Sequence:
        def __getitem__(self, _index):
            return tokens

    model = SimpleNamespace(device="test", generate=Mock(return_value=Sequence()))
    tokenizer = SimpleNamespace(
        pad_token_id=0,
        eos_token_id=2,
        apply_chat_template=Mock(return_value={"input_ids": Tensor()}),
        decode=Mock(return_value=' {"rationale":"Actual text","suggestions":[]} '),
    )
    state = {
        "model_name": "test-base",
        "identity": generator.configuration.identity,
        "torch": SimpleNamespace(inference_mode=nullcontext),
        "model": model,
        "tokenizer": tokenizer,
    }
    payload = {
        "model": state["model_name"],
        "metadata": {
            "expected_model_identity": state["identity"].to_snapshot(),
            "orchestwin_task_id": "proposal-team-v1",
        },
        "messages": [
            {"role": "system", "content": "Instruction"},
            {"role": "user", "content": "Context"},
        ],
        "max_tokens": 16,
        "temperature": temperature,
    }
    return state, payload


@pytest.mark.parametrize("temperature,sampling", [(0.0, False), (0.6, True)])
def test_serving_calls_generation_once_with_configured_sampling_and_keeps_raw_text(
    tmp_path, temperature, sampling
):
    module = server_module()
    state, payload = state_and_payload(tmp_path, temperature=temperature)
    response = module.completion(state, payload)
    state["model"].generate.assert_called_once()
    assert state["model"].generate.call_args.kwargs["do_sample"] is sampling
    assert state["model"].generate.call_args.kwargs["max_time"] == 120
    if sampling:
        assert state["model"].generate.call_args.kwargs["temperature"] == temperature
    assert response["choices"][0]["message"]["content"] == state["tokenizer"].decode.return_value
    assert response["choices"][0]["finish_reason"] == "stop"
    assert response["orchestwin_serving"]["output_repair_used"] is False
    assert response["orchestwin_serving"]["adapter_loaded"] is False


@pytest.mark.parametrize("mutation", ["task", "identity", "budget", "context"])
def test_serving_rejects_invalid_requests_before_generation(tmp_path, mutation):
    module = server_module()
    state, payload = state_and_payload(tmp_path)
    if mutation == "task":
        payload["metadata"]["orchestwin_task_id"] = "user-twin-evaluation-v1"
    elif mutation == "identity":
        payload["metadata"]["expected_model_identity"]["adapter_id"] = "foreign-adapter"
    elif mutation == "budget":
        payload["max_tokens"] = module.MAX_OUTPUT + 1
    else:
        module.MAX_SEQUENCE = 4
    with pytest.raises(ValueError):
        module.completion(state, payload)
    state["model"].generate.assert_not_called()


def test_serving_reports_truncation_instead_of_fabricating_completion(tmp_path):
    module = server_module()
    state, payload = state_and_payload(tmp_path, tokens=(8, 9, 10))
    response = module.completion(state, payload)
    assert response["choices"][0]["finish_reason"] == "length"
