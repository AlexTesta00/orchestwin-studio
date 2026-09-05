"""CPU/offline tokenization contracts; fake tokenizers never attest real measurements."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import orchestwin.training.qlora_smoke_tokenization as smoke_tokenization
from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.training.benchmark_measurement_v2 import measurement_policy_snapshot
from orchestwin.training.benchmark_suite_files import load_frozen_evaluator_benchmark_suite
from orchestwin.training.model_candidate_matrix_files import load_frozen_model_candidate_matrix
from orchestwin.training.model_source_evidence import (
    ModelSourceCaptureMode,
    create_captured_model_source_evidence,
    serialize_captured_model_source_evidence,
)
from orchestwin.training.qlora_smoke_preparation import prepare_qlora_smoke
from orchestwin.training.qlora_smoke_tokenization import (
    SmokeTokenizationError,
    audit_tokenized_record,
    load_smoke_preparation,
    tokenize_prepared_smoke,
)

ROOT = Path(__file__).resolve().parents[4]
CANDIDATE = "model-candidate-qwen3-4b-instruct-2507"


def prepare(tmp_path):
    """Synthetic provenance fixture; not an assertion of a real GPU benchmark."""
    matrix = load_frozen_model_candidate_matrix(ROOT)
    candidate = matrix.candidate(CANDIDATE)
    policy = measurement_policy_snapshot()
    report = {
        "schema_version": 2,
        "report_id": "user-twin-evaluator-model-spike-reanalysis-v2",
        "candidate_matrix_content_hash": matrix.content_hash,
        "benchmark_suite_content_hash": load_frozen_evaluator_benchmark_suite(ROOT).content_hash,
        "policy": policy,
        "policy_content_hash": snapshot_content_hash(policy),
        "input_inventory": [],
        "input_inventory_content_hash": snapshot_content_hash({"files": []}),
        "source_plan_content_hash": "a" * 64,
        "source_batch_content_hash": "b" * 64,
        "environment_sha256": "c" * 64,
        "package_lock_sha256": "fcd551c5c136ba0c6266d131b41a10ae48b13477dc7269f786a29f7db14d073b",
        "selection_status": "NO_MODEL_SELECTED",
        "ready_for_owner_selection": False,
        "live_inference_executed": False,
        "original_reports_replaced": False,
        "post_hoc": True,
        "candidates": [
            {
                "candidate_id": CANDIDATE,
                "model_repository": candidate.repository_id,
                "requested_revision": candidate.revision,
                "process_status": "SUCCEEDED",
                "runner_status": "COMPLETED",
                "observed_identity": {"observed_model_revision": candidate.revision},
            }
        ],
    }
    report["content_hash"] = snapshot_content_hash(report)
    source = tmp_path / "input" / "reanalysis.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(canonical_json(report).encode())
    return prepare_qlora_smoke(
        repository_root=ROOT,
        reanalysis_path=source,
        candidate_id=CANDIDATE,
        output_root=tmp_path / "prepared",
        created_at=WHEN,
    )


WHEN = datetime(2026, 9, 5, 11, 30, tzinfo=UTC)
TEMPLATE = "unit-test-chat-template"


class FakeTokenizer:
    """An inspectable word codec, not a proxy for Qwen token counts."""

    is_fast = True
    eos_token = "\x03"
    eos_token_id = 1
    pad_token_id = 0
    bos_token_id = None
    chat_template = TEMPLATE

    def __init__(self):
        self.vocabulary = {self.eos_token: 1}
        self.calls = []

    def get_chat_template(self):
        return self.chat_template

    def __call__(self, text, *, add_special_tokens, truncation, padding):
        assert add_special_tokens is False and truncation is False and padding is False
        words = re.findall(r"\x03|\n|[^\S\n]+|[^\s\x03]+", text)
        ids = [self.vocabulary.setdefault(word, len(self.vocabulary) + 1) for word in words]
        return {"input_ids": ids}

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, **kwargs):
        self.calls.append((copy.deepcopy(messages), tokenize, add_generation_prompt, kwargs))
        text = "".join(
            f"<{message['role']}>\n{message['content']}"
            + (self.eos_token if message["role"] == "assistant" else "")
            + "\n"
            for message in messages
        )
        if add_generation_prompt:
            text += "<assistant>\n"
        if tokenize:
            return self(text, add_special_tokens=False, truncation=False, padding=False)[
                "input_ids"
            ]
        return text


def record():
    return {
        "prompt": [
            {"role": "system", "content": "Use JSON"},
            {"role": "user", "content": "Inspect this example"},
        ],
        "completion": [{"role": "assistant", "content": '{"ok":true}'}],
    }


def sources(tmp_path):
    candidate = load_frozen_model_candidate_matrix(ROOT).candidate(CANDIDATE)
    files = {
        "README.md": b"Fictional source for unit tests only",
        "LICENSE": b"Fictional license evidence for unit tests only",
        "tokenizer.json": b"{}",
        "tokenizer_config.json": canonical_json(
            {
                "chat_template": TEMPLATE,
                "tokenizer_class": "Qwen2Tokenizer",
                "eos_token": "\x03",
                "pad_token": "<pad>",
            }
        ).encode(),
    }
    evidence = create_captured_model_source_evidence(
        candidate=candidate,
        captured_files=files,
        capture_mode=ModelSourceCaptureMode.CACHE_ONLY,
        captured_at=WHEN,
        resolved_revision=candidate.revision,
    )
    root = tmp_path / "sources"
    (root / "files").mkdir(parents=True)
    for name, raw in files.items():
        (root / "files" / name).write_bytes(raw)
    path = root / "evidence.json"
    path.write_bytes(serialize_captured_model_source_evidence(evidence))
    return path


def inputs(tmp_path):
    prepared = prepare(tmp_path).parent
    evidence = sources(tmp_path)
    return prepared, evidence


def execute(tmp_path, *, loader=None, **kwargs):
    prepared, evidence = inputs(tmp_path)
    return tokenize_prepared_smoke(
        repository_root=ROOT,
        preparation_root=prepared,
        source_evidence_path=evidence,
        output_root=tmp_path / "tokenized",
        created_at=WHEN,
        tokenizer_loader=loader or (lambda _: FakeTokenizer()),
        **kwargs,
    )


def test_completion_mask_excludes_prompt_and_keeps_complete_answer_and_eos():
    tokenizer = FakeTokenizer()
    observation, row = audit_tokenized_record(
        record(),
        tokenizer=tokenizer,
        max_length=1536,
        template_kwargs={},
    )
    assert observation["issues"] == []
    prefix = observation["prompt_tokens"]
    assert row["completion_mask"] == [0] * prefix + [1] * observation["completion_tokens"]
    assert row["attention_mask"] == [1] * len(row["input_ids"])
    assert 1 in row["input_ids"][prefix:]
    assert observation["proposed_ignored_label_count"] == prefix
    assert observation["training_collator_verified"] is False
    assert tokenizer.calls[0][2] is True
    assert tokenizer.calls[1][2] is False


def test_overflow_is_reported_without_truncating_or_exporting_training_row():
    observation, row = audit_tokenized_record(
        record(),
        tokenizer=FakeTokenizer(),
        max_length=2,
        template_kwargs={},
    )
    assert "SEQUENCE_OVERFLOW" in observation["issues"]
    assert observation["total_tokens"] > 2
    assert row is None


def test_template_control_is_applied_to_prompt_and_completed_conversation():
    tokenizer = FakeTokenizer()
    audit_tokenized_record(
        record(), tokenizer=tokenizer, max_length=1536, template_kwargs={"enable_thinking": False}
    )
    assert all(call[3] == {"enable_thinking": False} for call in tokenizer.calls)


@pytest.mark.parametrize("kind", ["text_prefix", "token_prefix", "native", "no_eos", "no_pad"])
def test_invalid_token_boundaries_are_blocked(kind):
    class Broken(FakeTokenizer):
        def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, **kwargs):
            value = super().apply_chat_template(
                messages, tokenize=tokenize, add_generation_prompt=add_generation_prompt, **kwargs
            )
            if kind == "text_prefix" and not tokenize and not add_generation_prompt:
                return "changed" + value
            if kind == "native" and tokenize:
                return [*value, 999]  # FIXED: replaced value + [999]
            return value

        def __call__(self, text, **kwargs):
            value = super().__call__(text, **kwargs)
            if kind == "token_prefix" and self.eos_token in text:
                value["input_ids"][0] = 999
            if kind == "no_eos":
                value["input_ids"] = [999 if v == 1 else v for v in value["input_ids"]]
            return value

    tokenizer = Broken()
    if kind == "no_pad":
        tokenizer.pad_token_id = None
    observation, row = audit_tokenized_record(
        record(), tokenizer=tokenizer, max_length=1536, template_kwargs={}
    )
    assert observation["issues"]
    assert row is None


def test_preparation_files_are_regenerated_and_verified(tmp_path):
    prepared, _ = inputs(tmp_path)
    loaded = load_smoke_preparation(ROOT, prepared)
    assert len(loaded.records) == 20
    assert loaded.configuration["optimization"]["max_steps"] == 8


def test_reproduction_temp_root_canonicalizes_an_os_level_symlink_alias(tmp_path, monkeypatch):
    actual_temp = tmp_path / "actual-temp"
    actual_temp.mkdir()
    alias_temp = tmp_path / "temp-alias"
    try:
        alias_temp.symlink_to(actual_temp, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are unavailable")

    monkeypatch.setattr(
        smoke_tokenization.tempfile,
        "gettempdir",
        lambda: str(alias_temp),
    )

    assert smoke_tokenization._canonical_system_temp_root() == actual_temp.resolve(strict=True)

    prepared = prepare(tmp_path / "work").parent
    loaded = load_smoke_preparation(ROOT, prepared)

    assert len(loaded.records) == 20
    assert loaded.configuration["optimization"]["max_steps"] == 8


@pytest.mark.parametrize(
    "filename",
    [
        "preparation.json",
        "train.jsonl",
        "validation.jsonl",
        "configuration.json",
        "dataset-manifest.json",
    ],
)
def test_changed_preparation_is_rejected_before_tokenizer_load(tmp_path, filename):
    prepared, evidence = inputs(tmp_path)
    (prepared / filename).write_bytes((prepared / filename).read_bytes() + b" ")
    with pytest.raises((SmokeTokenizationError, ValueError)):
        tokenize_prepared_smoke(
            repository_root=ROOT,
            preparation_root=prepared,
            source_evidence_path=evidence,
            output_root=tmp_path / "out",
            created_at=WHEN,
            tokenizer_loader=lambda _: pytest.fail("Tokenizer must not be loaded"),
        )
    assert not (tmp_path / "out").exists()


def test_rehashed_but_changed_dataset_is_rejected_by_frozen_fixture_reproduction(tmp_path):
    prepared, _ = inputs(tmp_path)
    file = prepared / "train.jsonl"
    rows = file.read_text().splitlines()
    row = json.loads(rows[0])
    row["prompt"][0]["content"] = "Invent references"
    rows[0] = canonical_json(row)
    file.write_bytes(("\n".join(rows) + "\n").encode())
    meta_path = prepared / "preparation.json"
    meta = json.loads(meta_path.read_text())
    meta["file_sha256"]["train.jsonl"] = hashlib.sha256(file.read_bytes()).hexdigest()
    meta.pop("content_hash")
    meta["content_hash"] = snapshot_content_hash(meta)
    meta_path.write_text(canonical_json(meta))
    with pytest.raises(SmokeTokenizationError):
        load_smoke_preparation(ROOT, prepared)


def test_tokenizer_files_are_verified_and_only_two_copied_to_loader(tmp_path):
    paths = []

    def loader(root):
        paths.append(root)
        assert sorted(p.name for p in root.iterdir()) == ["tokenizer.json", "tokenizer_config.json"]
        return FakeTokenizer()

    path = execute(tmp_path, loader=loader)
    report = json.loads(path.read_text())
    assert report["status"] == "TOKENIZATION_VERIFIED_NOT_AUTHORIZED"
    assert report["summary"]["sample_count"] == 20
    assert report["training_executed"] is False
    assert report["training_authorization"] == "NOT_GRANTED"
    assert report["owner_fixture_review"] == "PENDING"
    assert report["network_authorized"] is False
    assert report["model_weights_loaded"] is False
    assert report["tokenizer"]["revision_evidence"] == "CAPTURED_SNAPSHOT_FILES_SHA256"
    assert not paths[0].exists()
    assert (path.parent / "review.md").is_file()
    assert len((path.parent / "tokenized-train.jsonl").read_text().splitlines()) == 16
    assert len((path.parent / "tokenized-validation.jsonl").read_text().splitlines()) == 4


@pytest.mark.parametrize("kind", ["tamper", "wrong_revision", "auto_map", "template_mismatch"])
def test_invalid_tokenizer_evidence_or_behavior_is_rejected(tmp_path, kind):
    prepared, evidence = inputs(tmp_path)
    if kind == "tamper":
        (evidence.parent / "files/tokenizer.json").write_bytes(b"changed")
    elif kind == "wrong_revision":
        data = json.loads(evidence.read_text())
        data["resolved_revision"] = "a" * 40
        evidence.write_text(canonical_json(data))
    elif kind == "auto_map":
        # This should be rejected even after a consistent evidence recapture.
        files = {p.name: p.read_bytes() for p in (evidence.parent / "files").iterdir()}
        config = json.loads(files["tokenizer_config.json"])
        config["auto_map"] = {"AutoTokenizer": "evil.Code"}
        files["tokenizer_config.json"] = canonical_json(config).encode()
        (evidence.parent / "files/tokenizer_config.json").write_bytes(
            files["tokenizer_config.json"]
        )
        candidate = load_frozen_model_candidate_matrix(ROOT).candidate(CANDIDATE)
        value = create_captured_model_source_evidence(
            candidate=candidate,
            captured_files=files,
            capture_mode=ModelSourceCaptureMode.CACHE_ONLY,
            captured_at=WHEN,
            resolved_revision=candidate.revision,
        )
        evidence.write_bytes(serialize_captured_model_source_evidence(value))

    def loader(_):
        tokenizer = FakeTokenizer()
        if kind == "template_mismatch":
            tokenizer.chat_template = "other"
        return tokenizer

    with pytest.raises((SmokeTokenizationError, ValueError)):
        tokenize_prepared_smoke(
            repository_root=ROOT,
            preparation_root=prepared,
            source_evidence_path=evidence,
            output_root=tmp_path / "out",
            created_at=WHEN,
            tokenizer_loader=loader,
        )
    assert not (tmp_path / "out").exists()


def test_existing_output_and_input_directories_are_not_overwritten(tmp_path):
    prepared, evidence = inputs(tmp_path)
    for output in (prepared, evidence.parent, prepared / "nested"):
        with pytest.raises(SmokeTokenizationError):
            tokenize_prepared_smoke(
                repository_root=ROOT,
                preparation_root=prepared,
                source_evidence_path=evidence,
                output_root=output,
                created_at=WHEN,
                tokenizer_loader=lambda _: FakeTokenizer(),
            )


def test_report_determinism_and_no_source_mutation(tmp_path):
    prepared, evidence = inputs(tmp_path)
    before = {
        str(p): p.read_bytes()
        for root in (prepared, evidence.parent)
        for p in root.rglob("*")
        if p.is_file()
    }
    reports = []
    for i in range(2):
        path = tokenize_prepared_smoke(
            repository_root=ROOT,
            preparation_root=prepared,
            source_evidence_path=evidence,
            output_root=tmp_path / f"out{i}",
            created_at=WHEN,
            tokenizer_loader=lambda _: FakeTokenizer(),
        )
        reports.append(path.read_bytes())
    assert reports[0] == reports[1]
    assert all(Path(p).read_bytes() == raw for p, raw in before.items())


def test_linked_input_is_rejected(tmp_path):
    prepared, _ = inputs(tmp_path)  # FIXED: evidence renamed to _
    link = tmp_path / "linked"
    try:
        link.symlink_to(prepared, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links unavailable")
    with pytest.raises(SmokeTokenizationError):
        load_smoke_preparation(ROOT, link)


def test_help_runs_without_third_party_packages():
    process = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "environments/training/tokenize_qlora_smoke.py"),
            "--help",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert "--source-evidence" in process.stdout


def test_production_adapter_is_local_only_and_never_loads_a_model():
    import ast

    tree = ast.parse((ROOT / "environments/training/tokenize_qlora_smoke.py").read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "from_pretrained"
    ]
    assert len(calls) == 1
    assert isinstance(calls[0].func.value, ast.Name)
    assert calls[0].func.value.id == "AutoTokenizer"
    keywords = {item.arg: ast.literal_eval(item.value) for item in calls[0].keywords}
    assert keywords == {"local_files_only": True, "trust_remote_code": False, "use_fast": True}


def test_blocked_report_preserves_all_observations_but_exports_no_training_rows(tmp_path):
    class WithoutEOS(FakeTokenizer):
        eos_token_id = 999999

    path = execute(tmp_path, loader=lambda _: WithoutEOS())
    report = json.loads(path.read_text())
    assert report["status"] == "TOKENIZATION_BLOCKED"
    assert len(report["observations"]) == 20
    assert not list(path.parent.glob("tokenized-*.jsonl"))
    assert (path.parent / "review.md").is_file()


def test_changed_sources_during_loading_are_detected(tmp_path):
    prepared, evidence = inputs(tmp_path)

    def loader(_):
        (prepared / "train.jsonl").write_bytes(b"changed")
        return FakeTokenizer()

    with pytest.raises(SmokeTokenizationError, match="changed during tokenization"):
        tokenize_prepared_smoke(
            repository_root=ROOT,
            preparation_root=prepared,
            source_evidence_path=evidence,
            output_root=tmp_path / "out",
            created_at=WHEN,
            tokenizer_loader=loader,
        )
    assert not (tmp_path / "out").exists()


def test_naive_timestamp_and_source_tree_outputs_are_rejected(tmp_path):
    prepared, evidence = inputs(tmp_path)
    for timestamp, output in (
        (WHEN.replace(tzinfo=None), tmp_path / "out"),
        (WHEN, ROOT / "src/new-tokenization-artifacts"),
    ):
        with pytest.raises(SmokeTokenizationError):
            tokenize_prepared_smoke(
                repository_root=ROOT,
                preparation_root=prepared,
                source_evidence_path=evidence,
                output_root=output,
                created_at=timestamp,
                tokenizer_loader=lambda _: FakeTokenizer(),
            )


def test_cli_tokenizer_adapter_sets_cpu_offline_flags_and_only_loads_local_files(
    tmp_path,
    monkeypatch,
):
    import importlib.util
    import types

    path = ROOT / "environments/training/tokenize_qlora_smoke.py"
    spec = importlib.util.spec_from_file_location("tokenizer_smoke_cli_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    observed = []

    class FakeAuto:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            import os

            observed.append((path, kwargs))
            assert os.environ["HF_HUB_OFFLINE"] == "1"
            assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
            assert os.environ["USE_TORCH"] == "0"
            return object()

    monkeypatch.setitem(sys.modules, "transformers", types.SimpleNamespace(AutoTokenizer=FakeAuto))
    import os

    for key in (
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
        "USE_TORCH",
        "USE_TF",
        "USE_FLAX",
        "HF_HUB_DISABLE_TELEMETRY",
    ):
        monkeypatch.setenv(key, os.environ.get(key, ""))
    module._load_local_tokenizer(tmp_path)
    assert observed == [
        (
            str(tmp_path),
            {
                "local_files_only": True,
                "trust_remote_code": False,
                "use_fast": True,
            },
        )
    ]


def test_different_ids_on_repeated_encoding_are_blocked():
    class Unstable(FakeTokenizer):
        def __init__(self):
            super().__init__()
            self.count = 0

        def __call__(self, text, **kwargs):
            value = super().__call__(text, **kwargs)
            self.count += 1
            if self.count == 4:
                value["input_ids"][0] += 999
            return value

    observation, row = audit_tokenized_record(
        record(), tokenizer=Unstable(), max_length=1536, template_kwargs={}
    )
    assert "TOKENIZATION_NOT_DETERMINISTIC" in observation["issues"]
    assert row is None
