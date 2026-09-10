"""Explicit v1/v2 session compatibility; real local HTTP, no model execution."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import threading
from pathlib import Path

import pytest

from orchestwin.models.final_evaluator_session import (
    ADAPTER_SHA256,
    IDENTITY_FIELDS,
    MODEL_NAME,
    REVISION,
    SERVING_BASE_COMMIT,
    FinalEvaluatorSessionError,
    check_final_health,
    content_hash,
    load_final_session,
    session_http,
)
from orchestwin.models.strict_evaluator_json import canonical_bytes

RESTART_BASE_COMMIT = "2bfe813da9b78d9b309951b85d6dcdc0e9f14d50"
RESTART_POLICY = "EXPLICIT_COMMIT_AND_COMMITTED_FILES_V1"
RESTART_RUNTIME_ID = "s67-final-evaluator-serving-v2"
RESTART_SERVER_PATH = "environments/training/serve_final_evaluator.py"
REPO_ROOT = Path(__file__).resolve().parents[4]
TOKEN = "d" * 64


def record(path, value):
    # All records and the token in this file are synthetic test data.
    bound = {**value, "content_hash": content_hash(value)}
    path.write_bytes(canonical_bytes(bound))
    return bound


def values(*, legacy=False, port=43123):
    commit = SERVING_BASE_COMMIT if legacy else "b" * 40
    configuration = {
        "platform_commit": commit,
        "model_name": MODEL_NAME,
        "adapter_sha256": ADAPTER_SHA256,
    }
    identity = dict(IDENTITY_FIELDS)
    ready = {
        "status": "FINAL_EVALUATOR_SERVING_READY",
        "platform_commit": commit,
        "model_name": MODEL_NAME,
        "host": "127.0.0.1",
        "port": port,
        "credential_file": "access-token.secret",
        "authenticated_health_verified": True,
        "training_executed": False,
        "formal_run_started": False,
    }
    if not legacy:
        identity["runtime_id"] = RESTART_RUNTIME_ID
        ready["serving_contract_version"] = 2
        configuration["serving_contract_version"] = 2
        configuration["runtime_id"] = RESTART_RUNTIME_ID
        files = []
        for path, key in (
            (RESTART_SERVER_PATH, "operator_script_sha256"),
            ("environments/training/run_model_spike.py", "prompt_builder_sha256"),
            ("environments/training/uv.lock", "training_lock_sha256"),
        ):
            raw = ("test-only:" + path).encode()
            digest = hashlib.sha256(raw).hexdigest()
            blob = (
                "5cbd0c6d2c832630aa2f357eae9b8c8ebcc7e25f"
                if "run_model_spike" in path
                else "c" * 40
            )
            files.append({"path": path, "git_blob": blob, "sha256": digest, "size_bytes": len(raw)})
            configuration[key] = digest
        configuration["source_verification"] = {
            "commit": commit,
            "base_commit": RESTART_BASE_COMMIT,
            "tree": "e" * 40,
            "policy": RESTART_POLICY,
            "files": files,
        }
    ready["model_identity"] = identity
    return ready, configuration


def save(tmp_path, ready, config):
    bound = record(tmp_path / "configuration.json", config)
    ready = copy.deepcopy(ready)
    ready["model_identity"]["configuration_sha256"] = bound["content_hash"]
    record(tmp_path / "ready.json", ready)
    (tmp_path / "access-token.secret").write_text(TOKEN + "\n", encoding="ascii")
    return load_final_session(tmp_path / "ready.json")


@pytest.mark.parametrize("legacy", [True, False])
def test_both_explicit_session_versions_are_supported(tmp_path, legacy):
    session = save(tmp_path, *values(legacy=legacy))
    assert session.identity["runtime_id"] == (
        IDENTITY_FIELDS["runtime_id"] if legacy else RESTART_RUNTIME_ID
    )
    assert session.identity["adapter_sha256"] == ADAPTER_SHA256
    assert TOKEN not in repr(session)
    session.assert_unchanged()


@pytest.mark.parametrize("marker", ["stopped.json", "failure.json"])
def test_stopped_sessions_are_not_reactivated(tmp_path, marker):
    session = save(tmp_path, *values())
    (tmp_path / marker).write_text("{}")
    with pytest.raises(FinalEvaluatorSessionError, match="FINAL_SESSION_TERMINATED"):
        session.assert_unchanged()


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown-runtime",
        "wrong-ready-version",
        "wrong-config-version",
        "wrong-base",
        "wrong-commit",
        "wrong-tree",
        "wrong-policy",
        "wrong-loader",
        "wrong-source-sha",
        "source-missing",
        "source-duplicate",
        "wrong-model",
        "wrong-adapter",
        "wrong-legacy-commit",
    ],
)
def test_rehashed_incompatible_session_is_rejected(tmp_path, mutation):
    ready, config = values(legacy=mutation == "wrong-legacy-commit")
    source = config.get("source_verification", {})
    if mutation == "unknown-runtime":
        ready["model_identity"]["runtime_id"] = "unsupported-runtime"
    elif mutation == "wrong-ready-version":
        ready["serving_contract_version"] = 1
    elif mutation == "wrong-config-version":
        config["serving_contract_version"] = 1
    elif mutation == "wrong-base":
        source["base_commit"] = "a" * 40
    elif mutation == "wrong-commit":
        source["commit"] = "a" * 40
    elif mutation == "wrong-tree":
        source["tree"] = "not-a-tree"
    elif mutation == "wrong-policy":
        source["policy"] = "SKIP_SOURCE_CHECKS"
    elif mutation == "wrong-loader":
        source["files"][1]["git_blob"] = "a" * 40
    elif mutation == "wrong-source-sha":
        source["files"][0]["sha256"] = "a" * 64
    elif mutation == "source-missing":
        source["files"].pop()
    elif mutation == "source-duplicate":
        source["files"][0] = source["files"][1]
    elif mutation == "wrong-model":
        ready["model_identity"]["base_model_revision"] = "a" * 40
    elif mutation == "wrong-adapter":
        ready["model_identity"]["adapter_sha256"] = "a" * 64
    else:
        config["platform_commit"] = "a" * 40
    with pytest.raises(FinalEvaluatorSessionError):
        save(tmp_path, ready, config)


def test_changed_session_token_requires_reconfiguration(tmp_path):
    session = save(tmp_path, *values())
    (tmp_path / "access-token.secret").write_text("a" * 64 + "\n")
    with pytest.raises(FinalEvaluatorSessionError, match="CHANGED_RECONFIGURE"):
        session.assert_unchanged()


def test_counter_is_session_local_not_restored_from_previous_run(tmp_path):
    session = save(tmp_path, *values())
    assert "completed_generation_count" not in session.identity
    assert (
        session.identity["configuration_sha256"]
        == json.loads((tmp_path / "configuration.json").read_bytes())["content_hash"]
    )


def test_new_serving_handler_and_backend_share_real_authenticated_health(tmp_path, monkeypatch):
    import sys

    name = "orchestwin_restart_backend_http_test"
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / RESTART_SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)

    class State:
        def __init__(self):
            self.identity = {}

        def snapshot(self):
            return {
                "status": "FINAL_EVALUATOR_READY",
                "model_name": MODEL_NAME,
                "model_identity": self.identity,
                "completed_generation_count": 0,
                "load_observation": {
                    "base_revision_observed": REVISION,
                    "active_adapters": ["default"],
                    "load_in_4bit_observed": True,
                    "trainable_parameters": 0,
                },
                "fallback_policy": "FAIL_CLOSED_NO_BASE_FALLBACK",
                "training_executed": False,
                "benchmark_reexecuted": False,
            }

        def generate(self, _payload):
            raise AssertionError("No inference authorized by health test")

    state = State()
    server = module.LocalServer(("127.0.0.1", 0), module.handler_for(state, TOKEN))
    try:
        session = save(tmp_path, *values(port=server.server_port))
        state.identity = session.identity
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            observed = check_final_health(session)
            assert observed["model_identity"] == session.identity
            assert observed["completed_generation_count"] == 0
            assert module.http_health(server.server_port, None)[0] == 401
            assert TOKEN not in json.dumps(observed)
            response = session_http(session, "GET", "/health", timeout=5)
            assert response.status_code == 200
        finally:
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()
    finally:
        server.server_close()
