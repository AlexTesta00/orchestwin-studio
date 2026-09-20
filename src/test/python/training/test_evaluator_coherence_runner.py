"""Request identity and compute boundaries for the development-only experiment."""

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

from orchestwin.models.structured_generation import ModelRuntimeIdentity
from orchestwin.training.evaluator_coherence import instruction
from orchestwin.training.scoped_interface_curriculum import example
from orchestwin.training.scoped_interface_fixtures import VARIANTS, scenario

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "coherence_runner", ROOT / "environments/training/run_evaluator_coherence.py"
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


@pytest.mark.parametrize(
    "previous_raw",
    ['{\n  "overall_summary": "#a: presente. "\n}\n', " \tbad  output\r\n"],
)
def test_hydration_preserves_every_original_user_byte_and_binds_attempt_identity(previous_raw):
    messages = example(scenario(41, "validation", 0), VARIANTS[0], "en")["messages"][:2]
    original = deepcopy(messages)
    messages[0]["content"] += instruction(messages)
    case = dict(id="first", messages=messages, source_id="original", cohort="development")
    identity = ModelRuntimeIdentity(
        provider_id="test-provider",
        runtime_id="test-runtime",
        base_model_repository="Qwen/Qwen3-4B-Instruct-2507",
        base_model_revision="a" * 40,
        tokenizer_revision="a" * 40,
        configuration_sha256="b" * 64,
    )
    first = runner.request_for(case, identity, "test-run")
    retained = deepcopy(case)
    retry_case = runner.repair_case(case, previous_raw, ["SUMMARY_SENTENCE_CONTRACT"])
    repair = runner.request_for(retry_case, identity, "test-run")
    assert runner.model_visible_messages(first) == messages
    assert runner.model_visible_messages(first)[1] == original[1]
    assert first.request_id != repair.request_id
    assert first.max_output_tokens == 2048 and first.timeout_seconds == 180
    assert case == retained
    assert runner.model_visible_messages(repair) == retry_case["messages"]
    assert runner.model_visible_messages(repair)[1] == original[1]
    assert retry_case["previous_raw_sha256"] == hashlib.sha256(previous_raw.encode()).hexdigest()
    assert retry_case["parent_id"] == case["id"]
    assert retry_case["prompt_version_ref"] == runner.REPAIR_PROMPT_VERSION
    assert repair.system_instruction == " ".join(repair.system_instruction.split())


@pytest.mark.parametrize("defect", ["stale", "pod", "directory", "stage", "deadline", "stop"])
def test_cloud_guard_rejects_unbound_expired_or_stopped_work(tmp_path, monkeypatch, defect):
    output = tmp_path / "outputs"
    output.mkdir()
    monkeypatch.setenv("RUNPOD_POD_ID", "owned")
    monkeypatch.setattr(runner.time, "time", lambda: 1000)
    guard = dict(stage="ARMED", pod_id="owned", updated_unix=990, run_directory=str(output))
    deadline = 2000
    if defect == "stale":
        guard["updated_unix"] = 800
    elif defect == "pod":
        guard["pod_id"] = "other"
    elif defect == "directory":
        guard["run_directory"] = "old-result"
    elif defect == "stage":
        guard["stage"] = "STOPPING"
    elif defect == "deadline":
        deadline = 1100
    else:
        (output / "STOP_REQUESTED").touch()
    runner.save(tmp_path / "guard.json", guard)
    with pytest.raises((ValueError, TimeoutError)):
        runner.ready_guard(tmp_path, output, deadline)


def test_modified_bundle_is_rejected_before_model_loading(tmp_path):
    (tmp_path / "cases.json").write_text("tampered")
    (tmp_path / "manifest.json").write_text(json.dumps({"files": {"cases.json": "a" * 64}}))
    with pytest.raises(ValueError, match="sealed operator or input changed"):
        runner.run(tmp_path, tmp_path / "unused-output")
    assert not (tmp_path / "unused-output").exists()
