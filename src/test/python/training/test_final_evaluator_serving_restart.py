"""Restart source checks use real Git; weights and inference are never loaded."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SERVER_PATH = "environments/training/serve_final_evaluator.py"
REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def serving(monkeypatch):
    name = "orchestwin_restart_test_serving"
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    import sys

    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def git(root, *arguments):
    return subprocess.check_output(
        ("git", "-C", str(root), *arguments), text=True, stderr=subprocess.PIPE
    ).strip()


@pytest.fixture
def committed_source(tmp_path, monkeypatch, serving):
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "--quiet")
    git(root, "config", "user.name", "Restart Test")
    git(root, "config", "user.email", "restart@example.invalid")
    git(root, "config", "core.autocrlf", "false")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "config", "core.hooksPath", str(tmp_path / "no-hooks"))
    git(root, "checkout", "-b", serving.BRANCH)
    for relative, body in (
        (SERVER_PATH, b'"""Test-only tracked serving source."""\n'),
        (serving.SPIKE_REL, b'"""Test-only pinned loader."""\n'),
        (serving.LOCK_REL, b"version = 1\n"),
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    git(root, "add", ".")
    git(root, "commit", "-m", "test: seed source snapshot", "--quiet")
    commit = git(root, "rev-parse", "HEAD")
    monkeypatch.setattr(serving, "RESTART_BASE_COMMIT", commit)
    monkeypatch.setattr(
        serving, "SPIKE_GIT_BLOB", git(root, "rev-parse", f"HEAD:{serving.SPIKE_REL}")
    )
    monkeypatch.setattr(serving, "__file__", str(root / SERVER_PATH))
    return root, commit


def test_exact_commit_and_three_runtime_files_are_recorded(serving, committed_source):
    root, commit = committed_source
    value = serving.check_repository(root, commit)
    assert value["commit"] == commit
    assert value["tree"] == git(root, "rev-parse", "HEAD^{tree}")
    assert value["base_commit"] == commit
    assert {entry["path"] for entry in value["files"]} == {
        SERVER_PATH,
        serving.SPIKE_REL,
        serving.LOCK_REL,
    }
    for entry in value["files"]:
        assert entry["sha256"] == hashlib.sha256((root / entry["path"]).read_bytes()).hexdigest()


@pytest.mark.parametrize("expected", [None, "", "main", "HEAD", "x" * 40, "a" * 64])
def test_explicit_full_sha_required(serving, committed_source, expected):
    root, _commit = committed_source
    with pytest.raises(serving.ServingError, match="EXPECTED_COMMIT_REQUIRED"):
        serving.check_repository(root, expected)


def test_different_commit_is_not_silently_selected(serving, committed_source):
    root, _commit = committed_source
    with pytest.raises(serving.ServingError, match="UNEXPECTED_HEAD"):
        serving.check_repository(root, "f" * 40)


def test_dirty_source_blocks_before_any_loader(serving, committed_source):
    root, commit = committed_source
    (root / "unexpected.txt").write_text("local edit")
    with pytest.raises(serving.ServingError, match="WORKING_TREE_NOT_CLEAN"):
        serving.check_repository(root, commit)


def test_untracked_or_external_launcher_is_refused(serving, committed_source, monkeypatch):
    root, commit = committed_source
    monkeypatch.setattr(serving, "__file__", str(root.parent / "external.py"))
    with pytest.raises(serving.ServingError, match="USE_REPOSITORY_SERVING_SCRIPT"):
        serving.check_repository(root, commit)


def test_detached_head_is_not_accepted(serving, committed_source):
    root, commit = committed_source
    git(root, "checkout", "--detach", commit)
    with pytest.raises(serving.ServingError, match="UNEXPECTED_BRANCH"):
        serving.check_repository(root, commit)


def test_unrelated_descendant_can_be_authorized_explicitly(serving, committed_source):
    root, base = committed_source
    (root / "application-change.txt").write_text("unrelated backend change")
    git(root, "add", ".")
    git(root, "commit", "-m", "test: later application snapshot", "--quiet")
    commit = git(root, "rev-parse", "HEAD")
    assert commit != base
    assert serving.check_repository(root, commit)["base_commit"] == base


def test_changed_committed_loader_is_still_rejected(serving, committed_source):
    root, _base = committed_source
    (root / serving.SPIKE_REL).write_text('"""Changed loader."""\n')
    git(root, "add", ".")
    git(root, "commit", "-m", "test: changed loader", "--quiet")
    with pytest.raises(serving.ServingError, match="FROZEN_PROMPT_LOADER_CHANGED"):
        serving.check_repository(root, git(root, "rev-parse", "HEAD"))


def test_commit_outside_restart_lineage_is_rejected(serving, committed_source, monkeypatch):
    root, commit = committed_source
    monkeypatch.setattr(serving, "RESTART_BASE_COMMIT", "f" * 40)
    with pytest.raises(serving.ServingError, match="GIT_CHECK_FAILED"):
        serving.check_repository(root, commit)


def test_config_uses_actual_source_not_legacy_commit(serving, committed_source):
    root, commit = committed_source
    source = serving.check_repository(root, commit)
    config = serving.build_configuration(
        source,
        {"torch": "test-only"},
        {"adapter_sha256": serving.ADAPTER_DIGEST},
        {"quantization": {"load_in_4bit": True}},
    )
    assert config["platform_commit"] == commit
    assert config["serving_contract_version"] == 2
    assert config["runtime_id"] == "s67-final-evaluator-serving-v2"
    assert config["adapter_sha256"] == serving.ADAPTER_DIGEST
    assert config["source_verification"] == source


def test_pattern_is_forwarded_unchanged_to_model_prompt(serving):
    schema = {"type": "string", "pattern": r"^UTF-[0-9]{3,6}$"}
    payload = {
        "model": serving.MODEL_NAME,
        "temperature": 0,
        "max_tokens": 1024,
        "messages": [
            {"role": "system", "content": "Technical synthetic evaluation."},
            {"role": "user", "content": '{"verified_artifact_content":{}}'},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "strict": True,
                "schema": schema,
            },
        },
        "metadata": {
            "expected_model_identity": {"test": True},
            "orchestwin_task_id": "user-twin-evaluation-v1",
            "orchestwin_prompt_version_ref": "s12-verified-artifact-content-v2-finding-id-pattern",
            "allowed_evidence_refs": [],
        },
    }
    parsed = serving.parse_request(payload, {"test": True})
    assert json.loads(parsed["schema_json"]) == schema
    assert parsed["max_tokens"] == 1024


def test_no_benchmark_or_training_entrypoint_is_invoked():
    tree = ast.parse((REPO_ROOT / SERVER_PATH).read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    attribute_calls = {node.func.attr for node in calls if isinstance(node.func, ast.Attribute)}
    assert "train" not in attribute_calls
    assert "fit" not in attribute_calls
    assert "load_frozen_evaluator_benchmark_suite" not in attribute_calls
    assert "score_benchmark_result" not in attribute_calls


def test_terminal_session_health_is_refused_before_http(serving, tmp_path, monkeypatch):
    (tmp_path / "stopped.json").write_text("{}")
    calls = []
    monkeypatch.setattr(serving, "http_health", lambda *_args: calls.append(True))
    with pytest.raises(serving.ServingError, match="FINAL_SESSION_TERMINATED"):
        serving.check_ready(tmp_path / "ready.json")
    assert calls == []


def test_model_identity_and_limits_remain_frozen(serving):
    assert serving.MODEL == "Qwen/Qwen3-4B-Instruct-2507"
    assert serving.REVISION == "abcc171021d4f320b2e7f47c6f0deca67ded870c"
    assert (
        serving.ADAPTER_DIGEST == "82e051affb54f7fdced4c85780f8724fcc8f47063e27997bb6f5624421422664"
    )
    assert serving.LORA_PARAMETERS == 33030144
    assert serving.MAX_SEQUENCE == 4096
    assert serving.MAX_TOKENS == 1024
