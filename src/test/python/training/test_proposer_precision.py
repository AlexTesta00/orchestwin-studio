"""Explicit serving precision stays bound to loader evidence and runtime identity."""

import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from orchestwin.projects.requirements_primitives import snapshot_content_hash
from src.test.python.models.test_proposal_serving import server_module, state_and_payload


@pytest.mark.parametrize("precision", ["4bit", "bf16"])
def test_standalone_precision_is_explicit_in_loader_health_and_responses(
    tmp_path, monkeypatch, precision
):
    module = server_module()
    output = tmp_path / "session"
    argv = ["serve_proposal_model.py", "--output-directory", str(output), "--source-only"]
    if precision == "bf16":
        argv += ["--precision", "bf16", "--port", "8791"]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.chdir(tmp_path)
    state, payload = state_and_payload(tmp_path)
    state["model"].config = SimpleNamespace(vocab_size=100)
    observed = {"precision": precision, "test_double": True}
    loaded = []

    def load(repository, revision, **kwargs):
        loaded.append(kwargs)
        assert (repository, revision) == (module.MODEL, module.REVISION)
        return state["torch"], state["model"], state["tokenizer"], observed

    served = []

    def server(address, handler):
        served.append(handler)
        return SimpleNamespace(server_port=address[1], serve_forever=Mock(), server_close=Mock())

    monkeypatch.setattr(module, "load_model", load)
    monkeypatch.setattr(
        module, "build_schema_processor_factory", lambda *_: state["schema_processor"]
    )
    monkeypatch.setattr(module, "handler_for", lambda current, _token: current)
    monkeypatch.setattr(module, "ThreadingHTTPServer", server)
    module.main()

    configuration = json.loads((output / "loader.json").read_text())
    runtime = json.loads((output / "runtime.json").read_text())
    assert loaded == ([{}] if precision == "4bit" else [{"precision": "bf16"}])
    assert configuration["precision"] == precision
    assert configuration["load_in_4bit"] is (precision == "4bit")
    assert configuration["loader_evidence"] == observed
    assert runtime["identity"]["configuration_sha256"] == snapshot_content_hash(configuration)
    changed = {**configuration, "precision": "bf16" if precision == "4bit" else "4bit"}
    assert snapshot_content_hash(changed) != runtime["identity"]["configuration_sha256"]
    assert module.health_snapshot(served[0])["precision"] == precision
    payload["model"] = served[0]["model_name"]
    payload["metadata"].update(
        expected_model_identity=runtime["identity"], orchestwin_task_id="proposal-web-source-v1"
    )
    assert module.completion(served[0], payload)["orchestwin_serving"]["precision"] == precision


def test_server_passes_bf16_to_exact_offline_loader(monkeypatch):
    module = server_module()
    repository, revision = "Qwen/coder", "b" * 40
    loader = SimpleNamespace(
        _load_model=Mock(
            return_value=(
                object(),
                SimpleNamespace(),
                object(),
                {"observed_model_revision": revision},
            )
        )
    )
    spec = SimpleNamespace(name="test-loader", loader=SimpleNamespace(exec_module=Mock()))
    monkeypatch.setattr(
        module,
        "importlib",
        SimpleNamespace(
            util=SimpleNamespace(
                spec_from_file_location=Mock(return_value=spec),
                module_from_spec=Mock(return_value=loader),
            )
        ),
    )
    monkeypatch.setattr(module, "sys", SimpleNamespace(modules={}))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    module.load_model(repository, revision, precision="bf16")
    request = loader._load_model.call_args.args[0]
    assert request["model_repository"] == repository
    assert request["model_revision"] == request["tokenizer_revision"] == revision
    assert loader._load_model.call_args.kwargs == {"network_authorized": False, "precision": "bf16"}


def test_cli_rejects_unknown_precision_before_loading(tmp_path, monkeypatch):
    module = server_module()
    monkeypatch.setattr(
        sys, "argv", ["server", "--output-directory", str(tmp_path), "--precision", "auto"]
    )
    load = Mock()
    monkeypatch.setattr(module, "load_model", load)
    with pytest.raises(SystemExit) as stopped:
        module.main()
    assert stopped.value.code == 2
    load.assert_not_called()
