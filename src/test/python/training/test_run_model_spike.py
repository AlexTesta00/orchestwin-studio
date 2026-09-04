"""Contract tests for the isolated live model-spike runner."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from uuid import UUID

import pytest

from orchestwin.models.structured_generation import ModelRuntimeIdentity
from orchestwin.projects.requirements_primitives import snapshot_content_hash
from orchestwin.training.benchmark_suite_files import (
    FROZEN_BENCHMARK_SUITE_CONTENT_HASH,
    FROZEN_BENCHMARK_SUITE_SHA256,
    load_frozen_evaluator_benchmark_suite,
)
from orchestwin.training.benchmarking import create_benchmark_generation_request
from orchestwin.training.model_candidate_matrix_files import (
    FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH,
    FROZEN_MODEL_CANDIDATE_MATRIX_SHA256,
    load_frozen_model_candidate_matrix,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
RUNNER_PATH = REPOSITORY_ROOT / "environments" / "training" / "run_model_spike.py"
RUN_ID = UUID("00000000-0000-4000-8000-000000550001")
NOW = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)


def _runner() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "orchestwin_run_model_spike",
        RUNNER_PATH,
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _request_payload(module: ModuleType) -> dict[str, object]:
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)
    candidate = matrix.candidates[0]
    payload: dict[str, object] = {
        "schema_version": 1,
        "run_id": str(RUN_ID),
        "candidate_id": candidate.candidate_id,
        "candidate_matrix_sha256": FROZEN_MODEL_CANDIDATE_MATRIX_SHA256,
        "candidate_matrix_content_hash": FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH,
        "model_repository": candidate.repository_id,
        "model_revision": candidate.revision,
        "tokenizer_repository": candidate.tokenizer_repository_id,
        "tokenizer_revision": candidate.tokenizer_revision,
        "model_card_sha256": "b" * 64,
        "license_evidence_sha256": "c" * 64,
        "benchmark_suite_sha256": FROZEN_BENCHMARK_SUITE_SHA256,
        "benchmark_suite_content_hash": FROZEN_BENCHMARK_SUITE_CONTENT_HASH,
        "package_lock_sha256": "d" * 64,
        "environment_sha256": "e" * 64,
        "generation": matrix.generation.to_snapshot(),
        "requested_at": NOW.isoformat(),
    }
    payload["request_sha256"] = module._request_sha256(payload)
    return payload


def _write_request(tmp_path: Path, module: ModuleType, payload: dict[str, object]) -> Path:
    path = tmp_path / "request.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def test_direct_runner_uses_an_honest_provider_kind() -> None:
    module = _runner()

    assert (
        module.StructuredGenerationProviderKind.UNSLOTH_DIRECT_LOCAL.value == "UNSLOTH_DIRECT_LOCAL"
    )
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "StructuredGenerationProviderKind.UNSLOTH_DIRECT_LOCAL" in source


def test_runner_help_does_not_import_cuda_or_unsloth() -> None:
    completed = subprocess.run(
        [sys.executable, str(RUNNER_PATH), "--help"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0
    assert "frozen bilingual" in completed.stdout
    assert "Unsloth:" not in completed.stdout
    assert "CUDA" not in completed.stderr


def test_request_accepts_only_exact_identity_and_deterministic_generation(tmp_path: Path) -> None:
    module = _runner()
    payload = _request_payload(module)

    loaded = module._load_request(_write_request(tmp_path, module, payload))

    assert loaded == payload
    assert loaded["generation"]["load_in_4bit"] is True
    assert loaded["generation"]["trust_remote_code"] is False


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model_revision", "main", "exact lowercase commit revision"),
        ("candidate_id", "candidate-example", "model-candidate"),
        ("package_lock_sha256", "not-a-digest", "lowercase SHA-256"),
    ],
)
def test_request_rejects_unversioned_or_malformed_identity(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    module = _runner()
    payload = _request_payload(module)
    payload[field] = value
    payload["request_sha256"] = module._request_sha256(payload)

    with pytest.raises(module.ModelSpikeInputError, match=message):
        module._load_request(_write_request(tmp_path, module, payload))


def test_request_rejects_remote_code_sampling_and_credentials(tmp_path: Path) -> None:
    module = _runner()
    payload = _request_payload(module)
    generation = dict(payload["generation"])
    generation["trust_remote_code"] = True
    payload["generation"] = generation
    payload["request_sha256"] = module._request_sha256(payload)

    with pytest.raises(module.ModelSpikeInputError, match="forbids remote code"):
        module._load_request(_write_request(tmp_path, module, payload))

    payload = _request_payload(module)
    payload["hf_token"] = "secret"
    payload["request_sha256"] = module._request_sha256(payload)
    with pytest.raises(module.ModelSpikeInputError, match="fields do not match"):
        module._load_request(_write_request(tmp_path, module, payload))


def test_request_digest_detects_any_changed_generation_value(tmp_path: Path) -> None:
    module = _runner()
    payload = _request_payload(module)
    original_hash = payload["request_sha256"]
    generation = dict(payload["generation"])
    generation["seed"] = 99
    payload["generation"] = generation

    assert module._request_sha256(payload) != original_hash
    with pytest.raises(module.ModelSpikeInputError, match="digest is inconsistent"):
        module._load_request(_write_request(tmp_path, module, payload))


def test_model_visible_prompt_excludes_frozen_labels() -> None:
    module = _runner()
    suite = load_frozen_evaluator_benchmark_suite(REPOSITORY_ROOT)
    task = suite.tasks[0]
    identity = ModelRuntimeIdentity(
        provider_id="huggingface-local",
        runtime_id="unsloth-direct-inference-v1",
        base_model_repository="example/small-instruct",
        base_model_revision="a" * 40,
        tokenizer_revision="a" * 40,
        configuration_sha256="b" * 64,
    )
    generation_request = create_benchmark_generation_request(
        run_id=RUN_ID,
        task=task,
        model_identity=identity,
    )

    messages = module._create_chat_messages(generation_request)
    visible = json.dumps(messages, sort_keys=True).casefold()

    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert task.profile_summary.casefold() in visible
    assert task.evidence[0].reference_id.casefold() in visible
    assert "output_schema" in visible
    for forbidden in module._FORBIDDEN_PROMPT_LABELS:
        assert f'"{forbidden}"' not in visible


def test_request_is_resolved_only_against_the_frozen_candidate_matrix() -> None:
    module = _runner()
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)
    payload = _request_payload(module)

    candidate = module._resolve_frozen_candidate(payload, matrix)

    assert candidate.candidate_id == payload["candidate_id"]
    assert candidate.repository_id == payload["model_repository"]

    changed_identity = dict(payload)
    changed_identity["model_repository"] = "example/not-the-frozen-model"
    with pytest.raises(module.ModelSpikeInputError, match="identity differs"):
        module._resolve_frozen_candidate(changed_identity, matrix)

    changed_generation = dict(payload)
    changed_generation["generation"] = {
        **matrix.generation.to_snapshot(),
        "seed": matrix.generation.seed + 1,
    }
    with pytest.raises(module.ModelSpikeInputError, match="generation differs"):
        module._resolve_frozen_candidate(changed_generation, matrix)

    changed_matrix = dict(payload)
    changed_matrix["candidate_matrix_content_hash"] = "f" * 64
    with pytest.raises(module.ModelSpikeInputError, match="matrix content"):
        module._resolve_frozen_candidate(changed_matrix, matrix)


class _TemplateTensor:
    shape = (1, 8)

    def to(self, device: str) -> _TemplateTensor:
        assert device == "cuda"
        return self


class _TemplateTorch:
    @staticmethod
    def ones_like(value: object) -> _TemplateTensor:
        assert isinstance(value, _TemplateTensor)
        return _TemplateTensor()


class _CapturingTemplateTokenizer:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None

    def apply_chat_template(
        self,
        messages: list[dict[str, str]],
        **kwargs: object,
    ) -> dict[str, _TemplateTensor]:
        assert [message["role"] for message in messages] == ["system", "user"]
        self.kwargs = kwargs
        return {"input_ids": _TemplateTensor()}


@pytest.mark.parametrize(
    ("candidate_id", "expected_control"),
    [
        ("model-candidate-granite-3-3-2b-instruct", {"thinking": False}),
        ("model-candidate-qwen3-4b-instruct-2507", {}),
        ("model-candidate-smollm3-3b", {"enable_thinking": False}),
    ],
)
def test_chat_template_controls_are_applied_per_frozen_model_family(
    candidate_id: str,
    expected_control: dict[str, bool],
) -> None:
    module = _runner()
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)
    candidate = matrix.candidate(candidate_id)
    tokenizer = _CapturingTemplateTokenizer()

    inputs = module._prepare_inputs(
        tokenizer,
        (
            {"role": "system", "content": "System"},
            {"role": "user", "content": "User"},
        ),
        _TemplateTorch(),
        candidate.chat_template_control,
    )

    assert inputs["input_ids"].shape == (1, 8)
    assert tokenizer.kwargs is not None
    core_keys = {
        "tokenize",
        "add_generation_prompt",
        "return_tensors",
        "return_dict",
    }
    observed_control = {
        key: value for key, value in tokenizer.kwargs.items() if key not in core_keys
    }
    assert observed_control == expected_control


def test_strict_json_never_repairs_markdown_or_trailing_text() -> None:
    module = _runner()

    assert module._strict_json_object('{"abstained":true}') == {"abstained": True}
    assert module._strict_json_object('```json\n{"abstained":true}\n```') is None
    assert module._strict_json_object('{"abstained":true} explanation') is None
    assert module._strict_json_object('[{"abstained":true}]') is None


def test_invalid_json_is_measured_as_model_output_not_infrastructure_failure() -> None:
    module = _runner()
    task = load_frozen_evaluator_benchmark_suite(REPOSITORY_ROOT).tasks[0]

    score = module._invalid_json_score(task, latency_milliseconds=120)

    assert score.generation_status.value == "SUCCEEDED"
    assert score.schema_valid_rate == 0.0
    assert score.unsupported_claim_rate == 1.0
    assert score.latency_milliseconds == 120
    assert score.failure_code is None


def test_model_identity_hash_binds_runtime_generation_and_license_evidence() -> None:
    module = _runner()
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)
    candidate = matrix.candidates[0]
    first = _request_payload(module)
    second = _request_payload(module)
    second["license_evidence_sha256"] = "f" * 64
    second["request_sha256"] = module._request_sha256(second)

    first_identity = module._model_identity(first, candidate)
    second_identity = module._model_identity(second, candidate)

    assert first_identity.configuration_sha256 != second_identity.configuration_sha256
    assert first_identity.base_model_revision == candidate.revision
    assert first_identity.adapter_id is None


def test_result_digest_rejects_changed_observation() -> None:
    module = _runner()
    payload: dict[str, object] = {
        "schema_version": 1,
        "status": "COMPLETED",
        "tasks": [{"task_id": "bench-en-001", "score": 1.0}],
    }
    digest = module._result_sha256(payload)

    changed = dict(payload)
    changed["tasks"] = [{"task_id": "bench-en-001", "score": 0.0}]

    assert digest == snapshot_content_hash(payload)
    assert module._result_sha256(changed) != digest


def test_runtime_dependencies_are_loaded_only_inside_the_boundary() -> None:
    source = RUNNER_PATH.read_text(encoding="utf-8")
    prefix = source.split("def _load_runtime_dependencies", maxsplit=1)[0]

    assert "import torch" not in prefix
    assert "from unsloth import" not in prefix
    assert "from transformers import AutoTokenizer" not in prefix
    assert "ORCHESTWIN_MODEL_SPIKE_ALLOW_NETWORK" in source
    assert '"local_files_only": not network_authorized' in source
    assert "do_sample=False" in source


class _FakeCuda:
    @staticmethod
    def empty_cache() -> None:
        return None

    @staticmethod
    def reset_peak_memory_stats() -> None:
        return None

    @staticmethod
    def synchronize() -> None:
        return None

    @staticmethod
    def max_memory_reserved() -> int:
        return 2_048 * 1024 * 1024


class _FakeTorch:
    cuda = _FakeCuda()

    @staticmethod
    def inference_mode():
        return nullcontext()


class _FakeInputIds:
    shape = (1, 4)


class _FakeGeneratedIds:
    shape = (8,)


class _FakeSequences:
    def __getitem__(self, key: object) -> _FakeGeneratedIds:
        assert isinstance(key, tuple)
        return _FakeGeneratedIds()


class _FakeModel:
    def generate(self, **values: object) -> _FakeSequences:
        assert values["do_sample"] is False
        assert values["max_new_tokens"] == 1024
        return _FakeSequences()


class _FakeTokenizer:
    pad_token_id = 0
    eos_token_id = 1

    def __init__(self, raw_text: str) -> None:
        self.raw_text = raw_text

    def decode(self, _value: object, *, skip_special_tokens: bool) -> str:
        assert skip_special_tokens is True
        return self.raw_text


def test_fake_runtime_executes_every_frozen_task_and_writes_hashed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _runner()
    payload = _request_payload(module)
    suite = load_frozen_evaluator_benchmark_suite(REPOSITORY_ROOT)
    environment = {
        "environment_id": "orchestwin-unsloth-wsl2-v1",
        "gpu": {"status": "OBSERVED", "name": "NVIDIA GeForce RTX 4060"},
        "build_toolchain": {"status": "OBSERVED"},
    }
    raw_output = json.dumps(
        {
            "overall_summary": "Simulated role-specific feedback.",
            "role_statement": "I am evaluating from the represented role.",
            "evidence_gaps": [],
            "abstained": False,
            "findings": [],
        },
        sort_keys=True,
    )
    load_evidence = {
        "requested_model_revision": "a" * 40,
        "observed_model_revision": "a" * 40,
        "requested_tokenizer_revision": "a" * 40,
        "observed_tokenizer_revision": "a" * 40,
        "model_revision_observation": "MODEL_CONFIG_COMMIT_HASH",
        "tokenizer_revision_observation": "TOKENIZER_COMMIT_HASH",
        "model_load_duration_milliseconds": 100,
        "model_load_peak_gpu_memory_mb": 1024,
    }
    monkeypatch.setattr(
        module,
        "_verify_repository_evidence",
        lambda _request: (
            suite,
            environment,
            load_frozen_model_candidate_matrix(REPOSITORY_ROOT).candidates[0],
        ),
    )
    monkeypatch.setattr(
        module,
        "_load_model",
        lambda _request, network_authorized: (
            _FakeTorch(),
            _FakeModel(),
            _FakeTokenizer(raw_output),
            load_evidence,
        ),
    )
    monkeypatch.setattr(
        module,
        "_prepare_inputs",
        lambda _tokenizer, _messages, _torch, _control: {"input_ids": _FakeInputIds()},
    )
    result_path = tmp_path / "run" / "result.json"

    exit_code = module._run(payload, result_path)

    result = json.loads(result_path.read_text(encoding="utf-8"))
    result_digest = result.pop("result_sha256")
    assert exit_code == 0
    assert result["status"] == "COMPLETED"
    assert result["candidate_matrix"]["matrix_sha256"] == FROZEN_MODEL_CANDIDATE_MATRIX_SHA256
    assert result["candidate_matrix"]["chat_template_control"] == (
        load_frozen_model_candidate_matrix(REPOSITORY_ROOT)
        .candidates[0]
        .chat_template_control.to_snapshot()
    )
    assert result["benchmark"]["complete"] is True
    assert result["benchmark"]["observed_measurement_count"] == len(suite.tasks)
    assert len(result["tasks"]) == len(suite.tasks)
    assert len(result["benchmark_metrics"]) == 11
    assert result["resource_summary"]["successful_count"] == len(suite.tasks)
    assert result_digest == module._result_sha256(result)
    assert len(list((result_path.parent / "prompts").glob("*.json"))) == len(suite.tasks)
    assert len(list((result_path.parent / "raw").glob("*.txt"))) == len(suite.tasks)
    assert len(list((result_path.parent / "structured").glob("*.json"))) == len(suite.tasks)
