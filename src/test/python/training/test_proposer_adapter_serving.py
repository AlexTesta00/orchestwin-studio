"""Explicit proposer LoRA selection cannot leak into the evaluator or baseline."""

import hashlib
import importlib.util
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from orchestwin.models.real_runtime import _proposal_adapter_matches
from src.test.python.models.test_proposal_serving import server_module, state_and_payload


def adapted_state(tmp_path, *, evaluator=False):
    state, payload = state_and_payload(tmp_path, temperature=0.0 if evaluator else 0.6)
    identity = replace(
        state["identity"], adapter_id="selected-test-adapter", adapter_sha256="a" * 64
    )
    state.update(
        identity=identity,
        shared_adapter_loaded=True,
        evaluator=evaluator,
        adapter_name="default" if evaluator else "proposer",
        completed_generation_count=0,
    )
    payload["metadata"]["expected_model_identity"] = identity.to_snapshot()
    if evaluator:
        payload["metadata"]["orchestwin_task_id"] = "user-twin-evaluation-v1"
    model = state["model"]
    model.active_adapters = ["default"]
    model.peft_config = {"default": object(), "proposer": object()}
    model.switches = []
    model.frozen = True

    def select(name):
        model.switches.append(name)
        model.active_adapters = [name]
        model.frozen = False

    def freeze(value):
        model.frozen = not value

    model.set_adapter = select
    model.requires_grad_ = freeze
    return state, payload


@pytest.mark.parametrize("failure", [False, True])
def test_proposer_named_adapter_is_selected_and_restored_on_success_or_failure(tmp_path, failure):
    module = server_module()
    state, payload = adapted_state(tmp_path)
    model = state["model"]
    original = model.generate.return_value

    def generate(**kwargs):
        assert model.active_adapters == ["proposer"]
        assert model.frozen is True
        if failure:
            raise RuntimeError("GPU failure")
        return original

    model.generate.side_effect = generate
    if failure:
        with pytest.raises(RuntimeError, match="GPU failure"):
            module.completion(state, payload)
    else:
        response = module.completion(state, payload)
        report = response["orchestwin_serving"]
        assert report["adapter_active"] is True
        assert report["adapter_name"] == "proposer"
        assert report["adapter_role"] == "proposal"
        assert response["model_identity"] == state["identity"].to_snapshot()
        assert _proposal_adapter_matches(
            SimpleNamespace(identity=state["identity"]), module.health_snapshot(state)
        )
    assert model.switches == ["proposer", "default"]
    assert model.active_adapters == ["default"]
    assert model.frozen is True


def test_evaluator_selects_default_and_restores_preceding_proposer(tmp_path, monkeypatch):
    module = server_module()
    state, payload = adapted_state(tmp_path, evaluator=True)
    model = state["model"]
    model.active_adapters = ["proposer"]
    original = model.generate.return_value

    def generate(**kwargs):
        assert model.active_adapters == ["default"] and model.frozen
        return original

    monkeypatch.setattr(
        "orchestwin.models.strict_evaluator_json.check_evaluator_schema", lambda schema: None
    )
    model.generate.side_effect = generate
    response = module.completion(state, payload)
    assert response["orchestwin_serving"]["adapter_role"] == "evaluator"
    assert model.switches == ["default", "proposer"]
    assert model.frozen and model.active_adapters == ["proposer"]


@pytest.mark.parametrize(
    "mutation", ["missing", "wrong-role", "undeclared", "not-loaded", "identity-only"]
)
def test_adapter_conflicts_reject_before_generation(tmp_path, mutation):
    module = server_module()
    state, payload = adapted_state(tmp_path)
    if mutation == "missing":
        state["model"].peft_config.pop("proposer")
    elif mutation == "wrong-role":
        state["adapter_name"] = "default"
    elif mutation == "undeclared":
        state["identity"] = replace(state["identity"], adapter_id=None, adapter_sha256=None)
        payload["metadata"]["expected_model_identity"] = state["identity"].to_snapshot()
    elif mutation == "not-loaded":
        state["shared_adapter_loaded"] = False
    else:
        state["adapter_name"] = None
    with pytest.raises(ValueError, match="ADAPTER"):
        module.completion(state, payload)
    state["model"].generate.assert_not_called()


def test_failed_adapter_restoration_is_not_reported_as_success(tmp_path):
    module = server_module()
    state, payload = adapted_state(tmp_path)
    select = state["model"].set_adapter

    def broken_restore(name):
        if name == "proposer":
            select(name)

    state["model"].set_adapter = broken_restore
    with pytest.raises(ValueError, match="ADAPTER_RESTORATION_FAILED"):
        module.completion(state, payload)


@pytest.mark.parametrize(
    "loaded,active,name,role,adapted,expected",
    [
        (False, False, None, None, False, True),
        (True, False, None, None, False, True),
        (True, True, "proposer", "proposal", True, True),
        (True, True, "default", "evaluator", True, False),
        (True, True, "proposer", "proposal", False, False),
        (True, False, "proposer", "proposal", True, False),
        (False, True, "proposer", "proposal", True, False),
        (True, True, None, "proposal", True, False),
    ],
)
def test_readiness_requires_declared_adapter_and_correct_role(
    tmp_path, loaded, active, name, role, adapted, expected
):
    state, _ = state_and_payload(tmp_path)
    identity = state["identity"]
    if adapted:
        identity = replace(identity, adapter_id="candidate", adapter_sha256="b" * 64)
    health = dict(
        adapter_loaded=loaded, adapter_active=active, adapter_name=name, adapter_role=role
    )
    assert _proposal_adapter_matches(SimpleNamespace(identity=identity), health) is expected


def adapter_files(tmp_path, **changes):
    path = tmp_path / "adapter"
    path.mkdir()
    (path / "adapter_model.safetensors").write_bytes(b"synthetic hash-verification fixture")
    (path / "adapter_config.json").write_text(
        json.dumps(
            dict(
                base_model_name_or_path=server_module().MODEL,
                peft_type="LORA",
                task_type="CAUSAL_LM",
                **changes,
            )
        )
    )
    return path, *(
        hashlib.sha256((path / name).read_bytes()).hexdigest()
        for name in ("adapter_model.safetensors", "adapter_config.json")
    )


def test_optional_adapter_defaults_to_unadapted_and_requires_both_hashes(tmp_path):
    module = server_module()
    assert module.verify_proposer_adapter(None, None, None) == {}
    path, weights, config = adapter_files(tmp_path)
    assert module.verify_proposer_adapter(path, weights, config) == {
        "adapter_model.safetensors": weights,
        "adapter_config.json": config,
    }
    with pytest.raises(ValueError, match="PATH_AND_HASHES_REQUIRED"):
        module.verify_proposer_adapter(path, weights, None)
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        module.verify_proposer_adapter(path, "0" * 64, config)


def test_adapter_cannot_claim_a_different_base_revision(tmp_path):
    module = server_module()
    path, weights, config = adapter_files(tmp_path, revision="a" * 40)
    with pytest.raises(ValueError, match="BASE_OR_TYPE_MISMATCH"):
        module.verify_proposer_adapter(path, weights, config)


@pytest.mark.parametrize("task", ["web-source", "web-repair", "jvm-source", "jvm-repair"])
def test_source_endpoint_accepts_only_its_advertised_tasks(tmp_path, task):
    module = server_module()
    state, payload = adapted_state(tmp_path)
    state["supported_tasks"] = sorted(module.SOURCE_TASKS)
    payload["metadata"]["orchestwin_task_id"] = f"proposal-{task}-v1"
    response = module.completion(state, payload)
    assert response["model_identity"] == state["identity"].to_snapshot()
    assert module.health_snapshot(state)["supported_tasks"] == sorted(module.SOURCE_TASKS)
    assert state["model"].active_adapters == ["default"]


@pytest.mark.parametrize(
    "task", ["team", "personas", "user-twins", "requirements", "design", "architecture"]
)
def test_source_endpoint_rejects_other_proposals_before_inference(tmp_path, task):
    module = server_module()
    state, payload = adapted_state(tmp_path)
    state["supported_tasks"] = sorted(module.SOURCE_TASKS)
    payload["metadata"]["orchestwin_task_id"] = f"proposal-{task}-v1"
    with pytest.raises(ValueError, match="TASK_REJECTED"):
        module.completion(state, payload)
    state["model"].generate.assert_not_called()
    assert state["model"].switches == []


def test_source_endpoint_rejects_deterministic_generation(tmp_path):
    module = server_module()
    state, payload = adapted_state(tmp_path)
    state["supported_tasks"] = sorted(module.SOURCE_TASKS)
    payload["metadata"]["orchestwin_task_id"] = "proposal-web-source-v1"
    payload["temperature"] = 0.0
    with pytest.raises(ValueError, match="SAMPLED_SOURCE_PROPOSAL_REQUIRED"):
        module.completion(state, payload)
    state["model"].generate.assert_not_called()


@pytest.mark.parametrize(
    "sequence,output",
    [
        (1023, 128),
        (131073, 8192),
        (32768, 127),
        (32768, 16385),
        (8192, 8192),
        (8192, 10000),
        (True, 128),
    ],
)
def test_context_limits_reject_invalid_or_exhausted_budgets(sequence, output):
    with pytest.raises(ValueError, match="MODEL_CONTEXT_LIMITS_INVALID"):
        server_module().context_limits(sequence, output)


def test_standalone_source_startup_pins_model_context_output_and_capabilities(
    tmp_path, monkeypatch
):
    module = server_module()
    output = tmp_path / "source-session"
    revision = "b2cff646eb4bb1d68355c01b18ae02e7cf42d120"
    repository = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "serve_proposal_model.py",
            "--output-directory",
            str(output),
            "--port",
            "8790",
            "--source-only",
            "--model-repository",
            repository,
            "--model-revision",
            revision,
            "--max-sequence-length",
            "32768",
            "--max-output-tokens",
            "8192",
            "--generation-timeout-seconds",
            "540",
        ],
    )
    state, payload = state_and_payload(tmp_path)
    state["model"].config = SimpleNamespace(vocab_size=100)
    captured = []

    def load(selected_repository, selected_revision):
        assert (selected_repository, selected_revision) == (repository, revision)
        assert (module.MAX_SEQUENCE, module.MAX_OUTPUT) == (32768, 8192)
        return state["torch"], state["model"], state["tokenizer"], {}

    def server(address, handler):
        captured.append(handler[0])
        return SimpleNamespace(server_port=address[1], serve_forever=Mock(), server_close=Mock())

    monkeypatch.setattr(module, "load_model", load)
    monkeypatch.setattr(module.os, "chdir", Mock())
    monkeypatch.setattr(
        module, "build_schema_processor_factory", Mock(return_value=state["schema_processor"])
    )
    monkeypatch.setattr(module, "handler_for", lambda selected, token: (selected, token))
    monkeypatch.setattr(module, "ThreadingHTTPServer", server)
    module.main()
    runtime = json.loads((output / "runtime.json").read_text())
    evidence = json.loads((output / "loader.json").read_text())
    assert runtime["timeout_seconds"] == 600
    assert runtime["max_output_tokens"] == 8192
    assert evidence["max_sequence"] == 32768
    assert evidence["supported_tasks"] == sorted(module.SOURCE_TASKS)
    assert evidence["adapter_loaded"] is False
    health = module.health_snapshot(captured[0])
    assert health["model_identity"] == runtime["identity"]
    assert health["max_sequence_length"] == 32768 and health["max_output_tokens"] == 8192
    payload["model"] = captured[0]["model_name"]
    payload["metadata"].update(
        expected_model_identity=runtime["identity"], orchestwin_task_id="proposal-web-source-v1"
    )
    completion = module.completion(captured[0], payload)
    assert completion["orchestwin_serving"]["max_sequence_length"] == 32768
    assert completion["orchestwin_serving"]["max_output_tokens"] == 8192


def studio_module(monkeypatch):
    folder = Path(__file__).resolve().parents[4] / "environments/training"
    monkeypatch.syspath_prepend(str(folder))
    spec = importlib.util.spec_from_file_location(
        "studio_source_serving_test", folder / "serve_studio_models.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("adapted", [False, True])
def test_shared_default_plan_preserves_existing_baseline_and_benchmark(monkeypatch, adapted):
    module = studio_module(monkeypatch)
    plan = module.endpoint_plan(8787, 8788, proposer_adapter=adapted)
    assert len(plan) == 2
    assert plan[0][2] == ("proposer" if adapted else None)
    assert plan[1][2] == "default"


@pytest.mark.parametrize(
    "port,adapted", [(8787, True), (8788, True), (0, True), (65536, True), (8790, False)]
)
def test_shared_source_plan_rejects_invalid_ports_and_missing_adapter(monkeypatch, port, adapted):
    module = studio_module(monkeypatch)
    with pytest.raises(ValueError):
        module.endpoint_plan(8787, 8788, port, proposer_adapter=adapted)


def test_shared_source_plan_keeps_proposals_unadapted_and_roles_distinct(monkeypatch):
    module = studio_module(monkeypatch)
    assert module.endpoint_plan(8787, 8788, 8790, proposer_adapter=True) == [
        ("proposal", 8787, None, sorted(module.serving.TASKS)),
        ("evaluator", 8788, "default", ["user-twin-evaluation"]),
        ("source", 8790, "proposer", sorted(module.serving.SOURCE_TASKS)),
    ]


@pytest.mark.parametrize("dedicated", [False, True])
def test_shared_launcher_writes_consistent_source_identity_and_separate_credentials(
    tmp_path, monkeypatch, dedicated
):
    """Exercise startup composition with synthetic loaders; no model/GPU inference."""
    from orchestwin.models.real_runtime import build_real_model_runtime

    # The generated manifest is the only configuration under test, including in CI.
    for name in tuple(os.environ):
        if name.startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    module = studio_module(monkeypatch)
    output = tmp_path / "session"
    args = [
        "serve_studio_models.py",
        "--adapter",
        str(tmp_path / "evaluator"),
        "--weights-sha256",
        "a" * 64,
        "--config-sha256",
        "b" * 64,
        "--output",
        str(output),
    ]
    if dedicated:
        args += [
            "--proposer-adapter",
            str(tmp_path / "proposer"),
            "--proposer-weights-sha256",
            "c" * 64,
            "--proposer-config-sha256",
            "d" * 64,
            "--source-proposal-port",
            "8790",
        ]
    monkeypatch.setattr(sys, "argv", args)
    monkeypatch.setattr(
        module,
        "verify_adapter",
        lambda *args: {"adapter_model.safetensors": "a" * 64, "adapter_config.json": "b" * 64},
    )
    monkeypatch.setattr(
        module.serving,
        "verify_proposer_adapter",
        lambda path, *args: (
            {"adapter_model.safetensors": "c" * 64, "adapter_config.json": "d" * 64} if path else {}
        ),
    )
    model = SimpleNamespace(
        peft_config={"default": object()},
        active_adapters=["default"],
        config=SimpleNamespace(vocab_size=100),
        requires_grad_=Mock(),
    )
    model.load_adapter = lambda *args, **kwargs: model.peft_config.update(
        {kwargs["adapter_name"]: object()}
    )
    model.set_adapter = lambda name: setattr(model, "active_adapters", [name])
    monkeypatch.setattr(module.serving, "load_model", lambda: (object(), model, object(), {}))
    monkeypatch.setattr(module, "inference_model", lambda base, *args, **kwargs: base)
    monkeypatch.setattr(module, "configure_interactive_generation", Mock())
    monkeypatch.setattr(module.serving, "build_schema_processor_factory", Mock())
    monkeypatch.setitem(
        sys.modules, "peft", SimpleNamespace(PeftModel=SimpleNamespace(from_pretrained=Mock()))
    )
    monkeypatch.setitem(
        sys.modules,
        "unsloth",
        SimpleNamespace(FastLanguageModel=SimpleNamespace(for_inference=Mock())),
    )
    monkeypatch.setitem(
        sys.modules, "unsloth.models.llama", SimpleNamespace(KV_CACHE_INCREMENT=256)
    )
    monkeypatch.setattr(module.os, "chdir", Mock())
    monkeypatch.setattr(module.serving, "handler_for", lambda state, token: (state, token))
    servers = []

    def server(address, handler):
        item = SimpleNamespace(
            server_port=address[1],
            state=handler[0],
            token=handler[1],
            serve_forever=Mock(),
            shutdown=Mock(),
            server_close=Mock(),
        )
        servers.append(item)
        return item

    monkeypatch.setattr(module, "ThreadingHTTPServer", server)
    monkeypatch.setattr(module.threading, "Thread", lambda **kwargs: SimpleNamespace(start=Mock()))
    monkeypatch.setattr(
        module.threading,
        "Event",
        lambda: SimpleNamespace(wait=lambda _: (output / "stop.request").touch()),
    )
    module.main()
    manifest = json.loads((output / "models.json").read_text())
    runtime = build_real_model_runtime(output / "models.json")
    assert runtime.proposal_configuration.identity.adapter_id is None
    assert len(servers) == (3 if dedicated else 2)
    assert ("source_proposal_config_file" in manifest) is dedicated
    assert (runtime.sources.generator is runtime.team.generator) is (not dedicated)
    if dedicated:
        source = runtime.source_proposal_configuration
        assert source.identity.adapter_id.startswith("interactive-source-")
        assert source.token_file.read_text() == servers[2].token
        assert servers[2].token != servers[0].token
        assert _proposal_adapter_matches(source, module.serving.health_snapshot(servers[2].state))
        assert servers[0].state["slot"] is servers[1].state["slot"] is servers[2].state["slot"]
    for item in servers:
        item.shutdown.assert_called_once()
        item.server_close.assert_called_once()
