"""Proposal serving controls with an injected tensor/model double, no GPU."""

import importlib.util
import json
from contextlib import contextmanager, nullcontext
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


@pytest.mark.parametrize(
    "repository,revision",
    [("Qwen/other", None), (None, "a" * 40), ("Qwen/other", "main"), ("../local", "a" * 40)],
)
def test_alternate_model_requires_repository_and_immutable_revision(repository, revision):
    with pytest.raises(ValueError, match="EXACT_REVISION_REQUIRED"):
        server_module().selected_model(repository, revision)


def test_default_is_unchanged_and_alternate_identity_is_explicit():
    module = server_module()
    assert module.selected_model(None, None) == (module.MODEL, module.REVISION)
    assert module.selected_model("Qwen/coder", "b" * 40) == ("Qwen/coder", "b" * 40)


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
        "schema_processor": Mock(return_value=Mock(finish=Mock(return_value=True))),
    }
    payload = {
        "model": state["model_name"],
        "metadata": {
            "expected_model_identity": state["identity"].to_snapshot(),
            "orchestwin_task_id": "proposal-team-v1",
        },
        "messages": [
            {"role": "system", "content": "Instruction"},
            {
                "role": "user",
                "content": json.dumps({"context": {}, "output_schema": {"type": "object"}}),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"strict": True, "schema": {"type": "object"}},
        },
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
    assert state["model"].generate.call_args.kwargs["logits_processor"] == [
        state["schema_processor"].return_value
    ]
    if sampling:
        assert state["model"].generate.call_args.kwargs["temperature"] == temperature
    assert response["choices"][0]["message"]["content"] == state["tokenizer"].decode.return_value
    assert response["choices"][0]["finish_reason"] == "stop"
    assert response["orchestwin_serving"]["output_repair_used"] is False
    assert response["orchestwin_serving"]["adapter_loaded"] is False


def test_shared_model_disables_trained_adapter_only_during_proposals(tmp_path):
    module = server_module()
    state, payload = state_and_payload(tmp_path)
    active = [True]

    @contextmanager
    def disabled():
        active[0] = False
        try:
            yield
        finally:
            active[0] = True

    state["model"].disable_adapter = disabled
    original = state["model"].generate.return_value

    def generate(**_):
        assert active[0] is False
        return original

    state["model"].generate.side_effect = generate
    state.update(shared_adapter_loaded=True, evaluator=False)
    response = module.completion(state, payload)
    assert active[0] is True
    assert response["orchestwin_serving"]["adapter_loaded"] is True
    assert response["orchestwin_serving"]["adapter_active"] is False


@pytest.mark.parametrize("mutation", ["task", "identity", "budget", "context", "schema", "strict"])
def test_serving_rejects_invalid_requests_before_generation(tmp_path, mutation):
    module = server_module()
    state, payload = state_and_payload(tmp_path)
    if mutation == "task":
        payload["metadata"]["orchestwin_task_id"] = "user-twin-evaluation-v1"
    elif mutation == "identity":
        payload["metadata"]["expected_model_identity"]["adapter_id"] = "foreign-adapter"
    elif mutation == "budget":
        payload["max_tokens"] = module.MAX_OUTPUT + 1
    elif mutation == "context":
        module.MAX_SEQUENCE = 4
    elif mutation == "schema":
        payload["response_format"]["json_schema"]["schema"] = {"type": "string"}
    else:
        payload["response_format"]["json_schema"]["strict"] = False
    with pytest.raises(ValueError):
        module.completion(state, payload)
    state["model"].generate.assert_not_called()


def test_serving_reports_truncation_instead_of_fabricating_completion(tmp_path):
    module = server_module()
    state, payload = state_and_payload(tmp_path, tokens=(8, 9, 10))
    response = module.completion(state, payload)
    assert response["choices"][0]["finish_reason"] == "length"


@pytest.mark.parametrize("value", ["29", "541", "1.5", "unlimited"])
def test_generation_timeout_rejects_unbounded_or_invalid_operator_values(value):
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        server_module().generation_timeout(value)


def test_selected_deadline_is_applied_and_reported_without_accepting_truncation(tmp_path):
    module = server_module()
    state, payload = state_and_payload(tmp_path, tokens=(8, 9, 10))
    state.update(
        max_generation_seconds=module.generation_timeout("300"), completed_generation_count=0
    )
    response = module.completion(state, payload)
    assert state["model"].generate.call_args.kwargs["max_time"] == 300
    assert response["orchestwin_serving"]["generation_wall_time_budget_seconds"] == 300
    assert response["choices"][0]["finish_reason"] == "length"
    assert module.health_snapshot(state)["generation_watchdog"] == (
        "COOPERATIVE_300_SECONDS_NOT_HARD_GPU_PREEMPTION"
    )


def test_serving_does_not_accept_eos_without_complete_schema(tmp_path):
    module = server_module()
    state, payload = state_and_payload(tmp_path)
    state["schema_processor"].return_value.finish.return_value = False
    with pytest.raises(ValueError, match="SCHEMA_INCOMPLETE_AT_EOS"):
        module.completion(state, payload)


@pytest.mark.parametrize(
    "error,code",
    [
        (ValueError("CONTEXT_BUDGET_EXCEEDED"), "CONTEXT_BUDGET_EXCEEDED"),
        (ValueError("request text must never escape"), "REQUEST_REJECTED"),
        (KeyError("CONTEXT_BUDGET_EXCEEDED"), "REQUEST_REJECTED"),
    ],
)
def test_context_rejection_is_actionable_without_exposing_arbitrary_error_text(error, code):
    assert server_module().request_failure_code(error) == code
