"""Offline smoke data/configuration contracts; no weights or GPU are required."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.training.benchmark_measurement_v2 import measurement_policy_snapshot
from orchestwin.training.benchmark_suite_files import load_frozen_evaluator_benchmark_suite
from orchestwin.training.model_candidate_matrix_files import load_frozen_model_candidate_matrix
from orchestwin.training.qlora_smoke_fixtures import (
    SMOKE_FIXTURE_PATH,
    SMOKE_FIXTURE_SHA256,
    SmokePreparationError,
    load_smoke_fixtures,
    validate_smoke_payload,
)
from orchestwin.training.qlora_smoke_preparation import prepare_qlora_smoke

ROOT = Path(__file__).resolve().parents[4]
CANDIDATE = "model-candidate-qwen3-4b-instruct-2507"
WHEN = datetime(2026, 9, 5, 11, tzinfo=UTC)


def payload():
    return json.loads((ROOT / SMOKE_FIXTURE_PATH).read_text(encoding="utf-8"))


def reanalysis(tmp_path):
    """Minimal fixture for provenance binding, not a claim of an actual GPU run."""
    matrix = load_frozen_model_candidate_matrix(ROOT)
    suite = load_frozen_evaluator_benchmark_suite(ROOT)
    candidate = matrix.candidate(CANDIDATE)
    policy = measurement_policy_snapshot()
    report = {
        "schema_version": 2,
        "report_id": "user-twin-evaluator-model-spike-reanalysis-v2",
        "candidate_matrix_content_hash": matrix.content_hash,
        "benchmark_suite_content_hash": suite.content_hash,
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
                "candidate_id": candidate.candidate_id,
                "model_repository": candidate.repository_id,
                "requested_revision": candidate.revision,
                "process_status": "SUCCEEDED",
                "runner_status": "COMPLETED",
                "observed_identity": {"observed_model_revision": candidate.revision},
            }
        ],
    }
    report["content_hash"] = snapshot_content_hash(report)
    path = tmp_path / "inputs" / "reanalysis.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(report), encoding="utf-8")
    return path


def prepare(tmp_path, **kwargs):
    source = kwargs.pop("reanalysis_path", None)
    if source is None:
        source = reanalysis(tmp_path)
    return prepare_qlora_smoke(
        repository_root=ROOT,
        reanalysis_path=source,
        candidate_id=kwargs.pop("candidate_id", CANDIDATE),
        output_root=kwargs.pop("output_root", tmp_path / "prepared"),
        created_at=kwargs.pop("created_at", WHEN),
        **kwargs,
    )


def test_frozen_fixture_has_grouped_bilingual_splits_and_no_benchmark_examples():
    fixtures = load_smoke_fixtures(ROOT)
    assert len(fixtures.samples) == 20
    assert {split: len(fixtures.for_split(split)) for split in ("train", "validation")} == {
        "train": 16,
        "validation": 4,
    }
    for split, per_language in (("train", 8), ("validation", 2)):
        assert [
            sum(item.language == lang for item in fixtures.for_split(split))
            for lang in ("en", "it")
        ] == [per_language, per_language]
    assert fixtures.leakage_report["benchmark_sample_reuse"] is False
    assert fixtures.leakage_report["semantic_leakage_proven_absent"] is False
    actual_digest = hashlib.sha256((ROOT / SMOKE_FIXTURE_PATH).read_bytes()).hexdigest()
    assert actual_digest == SMOKE_FIXTURE_SHA256


@pytest.mark.parametrize(
    "change",
    [
        "empirical",
        "human_flag",
        "unknown_reference",
        "markdown",
        "missing_summary",
        "extra_property",
        "duplicate_id",
        "abstention_finding",
        "benchmark_reference",
        "cross_split_translation",
        "real_user_data",
        "unknown_top_key",
        "profile_approved",
    ],
)
def test_fixture_rejects_invalid_supervision_and_false_provenance(change):
    data = payload()
    sample = data["samples"][0]
    finding = sample["expected_output"]["findings"][0]
    if change == "empirical":
        finding["epistemic_status"] = "EMPIRICALLY_SUPPORTED"
    elif change == "human_flag":
        finding["requires_human_validation"] = False
    elif change == "unknown_reference":
        finding["evidence_refs"] = ["UNKNOWN"]
    elif change == "markdown":
        sample["expected_output"] = "```json\n{}\n```"
    elif change == "missing_summary":
        finding.pop("summary")
    elif change == "extra_property":
        finding["unapproved"] = True
    elif change == "duplicate_id":
        data["samples"][1]["sample_id"] = sample["sample_id"]
    elif change == "abstention_finding":
        sample["expected_output"]["abstained"] = True
    elif change == "benchmark_reference":
        sample["input"]["evidence"][0]["reference_id"] = "REQ-EN-001-A"
    elif change == "cross_split_translation":
        sample["split"] = "validation"
    elif change == "real_user_data":
        data["real_user_data"] = True
    elif change == "unknown_top_key":
        data["teacher_approved"] = True
    elif change == "profile_approved":
        sample["input"]["profile_status"] = "OWNER_APPROVED_UT"
    with pytest.raises((SmokePreparationError, ValueError)):
        validate_smoke_payload(data, load_frozen_evaluator_benchmark_suite(ROOT))


def test_fixture_rejects_reuse_of_actual_benchmark_scenario():
    data = payload()
    suite = load_frozen_evaluator_benchmark_suite(ROOT)
    data["samples"][0]["input"]["scenario"] = suite.tasks[0].scenario
    with pytest.raises(SmokePreparationError, match="benchmark"):
        validate_smoke_payload(data, suite)


def test_prompt_completion_has_schema_and_no_target_inside_prompt():
    fixtures = load_smoke_fixtures(ROOT)
    for sample in fixtures.samples:
        row = sample.training_record()
        assert set(row) == {"prompt", "completion"}
        assert [item["role"] for item in row["prompt"]] == ["system", "user"]
        assert row["completion"][0]["role"] == "assistant"
        user = json.loads(row["prompt"][1]["content"])
        assert "output_schema" in user and "expected_output" not in user
        assert "findings" not in user
        assert json.loads(row["completion"][0]["content"]) == json.loads(sample.output_json)
        assert "one finding" in row["prompt"][0]["content"]


def test_preparation_uses_existing_configuration_and_does_not_authorize_training(tmp_path):
    path = prepare(tmp_path)
    record = json.loads(path.read_text())
    assert record["status"] == "PREPARED_NOT_AUTHORIZED"
    assert record["training_executed"] is False
    assert record["model_selected"] is False
    assert record["tokenization_status"] == "NOT_RUN"
    assert record["owner_fixture_review"] == "PENDING"
    assert not (path.parent / "request.json").exists()
    config = json.loads((path.parent / "configuration.json").read_text())
    assert config["optimization"]["max_steps"] == 8
    assert config["optimization"]["per_device_train_batch_size"] == 1
    assert config["optimization"]["gradient_accumulation_steps"] == 2
    assert config["optimization"]["max_sequence_length"] == 1536
    assert config["adapter"]["rank"] == 8
    assert config["adapter"]["alpha"] == 16
    assert config["adapter"]["dropout"] == 0
    assert config["quantization"]["quantization_type"] == "nf4"
    assert config["base_model_revision"] == "abcc171021d4f320b2e7f47c6f0deca67ded870c"
    for name, count in (("train.jsonl", 16), ("validation.jsonl", 4)):
        rows = (path.parent / name).read_text().splitlines()
        assert len(rows) == count
        assert all(set(json.loads(row)) == {"prompt", "completion"} for row in rows)
    for name, digest in record["file_sha256"].items():
        assert hashlib.sha256((path.parent / name).read_bytes()).hexdigest() == digest
    assert set(record["file_sha256"]) == {
        "configuration.json",
        "dataset-manifest.json",
        "train.jsonl",
        "validation.jsonl",
        "reanalysis-source.json",
    }


def test_preparation_is_deterministic_and_keeps_inputs_unchanged(tmp_path):
    source = reanalysis(tmp_path)
    before = source.read_bytes()
    a = prepare(tmp_path, reanalysis_path=source, output_root=tmp_path / "a")
    b = prepare(tmp_path, reanalysis_path=source, output_root=tmp_path / "b")
    assert {p.name: p.read_bytes() for p in a.parent.iterdir()} == {
        p.name: p.read_bytes() for p in b.parent.iterdir()
    }
    assert source.read_bytes() == before


def test_existing_destination_is_not_overwritten(tmp_path):
    target = tmp_path / "prepared"
    target.mkdir()
    with pytest.raises(SmokePreparationError, match="absent"):
        prepare(tmp_path, output_root=target)
    assert list(target.iterdir()) == []


@pytest.mark.parametrize(
    "mutation",
    ["hash", "revision", "selection", "failure", "policy", "duplicate"],
)
def test_invalid_reanalysis_is_rejected_before_outputs_exist(tmp_path, mutation):
    path = reanalysis(tmp_path)
    report = json.loads(path.read_text())
    if mutation == "hash":
        report["content_hash"] = "f" * 64
    else:
        if mutation == "revision":
            report["candidates"][0]["observed_identity"]["observed_model_revision"] = "f" * 40
        elif mutation == "selection":
            report["selection_status"] = "SELECTED"
        elif mutation == "failure":
            report["candidates"][0]["runner_status"] = "PARTIAL"
        elif mutation == "policy":
            report["policy"]["raw_text_repair"] = "STRIP_MARKDOWN"
        elif mutation == "duplicate":
            report["candidates"].append(copy.deepcopy(report["candidates"][0]))
        report.pop("content_hash")
        report["content_hash"] = snapshot_content_hash(report)
    path.write_text(canonical_json(report), encoding="utf-8")
    with pytest.raises(SmokePreparationError):
        prepare(tmp_path, reanalysis_path=path)
    assert not (tmp_path / "prepared").exists()


def test_candidate_is_explicit_and_must_be_in_the_frozen_matrix(tmp_path):
    with pytest.raises(SmokePreparationError, match="candidate"):
        prepare(tmp_path, candidate_id="model-candidate-not-authorized")


def test_timestamp_must_be_timezone_aware(tmp_path):
    with pytest.raises(SmokePreparationError, match="timezone"):
        prepare(tmp_path, created_at=datetime(2026, 9, 5))


def test_destination_cannot_be_inside_reanalysis_or_source_trees(tmp_path):
    source_dir = tmp_path / "input"
    source_dir.mkdir()
    source = reanalysis(source_dir)
    with pytest.raises(SmokePreparationError, match="protected"):
        prepare(tmp_path, reanalysis_path=source, output_root=source.parent / "nested")
    with pytest.raises(SmokePreparationError, match="protected"):
        prepare(tmp_path, output_root=ROOT / "src" / "forbidden-smoke-output")


def test_symlink_source_is_rejected(tmp_path):
    source = reanalysis(tmp_path)
    link = tmp_path / "symlink.json"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("symbolic links are unavailable")
    with pytest.raises(SmokePreparationError, match="symbolic"):
        prepare(tmp_path, reanalysis_path=link)


def test_cli_runs_without_external_packages_or_gpu(tmp_path):
    source = reanalysis(tmp_path)
    environment = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "environments/training/prepare_qlora_smoke.py"),
            "--candidate-id",
            CANDIDATE,
            "--reanalysis",
            str(source),
            "--created-at",
            WHEN.isoformat(),
            "--output-root",
            str(tmp_path / "cli"),
        ],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "qlora_smoke_preparation: PASSED (training not authorized)" in completed.stdout
    assert not (tmp_path / "cli" / "request.json").exists()


def test_output_parent_traversal_is_rejected(tmp_path):
    with pytest.raises(SmokePreparationError, match="parent traversal"):
        prepare(tmp_path, output_root=tmp_path / "unused" / ".." / "output")


def test_repository_control_directories_are_protected(tmp_path):
    with pytest.raises(SmokePreparationError, match="protected"):
        prepare(tmp_path, output_root=ROOT / ".git" / "smoke-output")


def test_output_parent_symlink_is_rejected(tmp_path):
    folder = tmp_path / "actual"
    folder.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(folder, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are unavailable")
    with pytest.raises(SmokePreparationError, match="symbolic"):
        prepare(tmp_path, output_root=link / "output")


def test_frozen_fixture_bytes_cannot_be_replaced(tmp_path):
    path = tmp_path / SMOKE_FIXTURE_PATH
    path.parent.mkdir(parents=True)
    path.write_bytes((ROOT / SMOKE_FIXTURE_PATH).read_bytes() + b" ")
    with pytest.raises(SmokePreparationError, match="digest"):
        load_smoke_fixtures(tmp_path)


def test_validation_rows_are_not_training_translations():
    fixture = load_smoke_fixtures(ROOT)
    train_groups = {row.scenario_family_id for row in fixture.for_split("train")}
    validation_groups = {row.scenario_family_id for row in fixture.for_split("validation")}
    assert not train_groups & validation_groups
    for split in ("train", "validation"):
        assert any(json.loads(row.output_json)["abstained"] for row in fixture.for_split(split))
        assert any(json.loads(row.output_json)["findings"] for row in fixture.for_split(split))


def test_configuration_reference_matches_the_smoke_manifest(tmp_path):
    path = prepare(tmp_path)
    configuration = json.loads((path.parent / "configuration.json").read_bytes())
    manifest = json.loads((path.parent / "dataset-manifest.json").read_bytes())
    reference = configuration["dataset_reference"]
    expected_reference = {
        key: manifest[key] for key in ("dataset_id", "version_number", "content_hash")
    }
    assert reference == expected_reference
    assert manifest["manifest_kind"] == "QLORA_SMOKE_FIXTURE_DATASET"
    assert manifest["purpose"] == "PIPELINE_SMOKE_ONLY"
    expected_manifest_hash = manifest.pop("content_hash")
    assert snapshot_content_hash(manifest) == expected_manifest_hash


def test_new_timestamp_does_not_change_the_semantic_training_configuration(tmp_path):
    source = reanalysis(tmp_path)
    paths = [
        prepare(tmp_path, reanalysis_path=source, output_root=tmp_path / name, created_at=when)
        for name, when in (("first", WHEN), ("second", WHEN.replace(hour=12)))
    ]
    configs = [json.loads((path.parent / "configuration.json").read_bytes()) for path in paths]
    assert configs[0]["content_hash"] == configs[1]["content_hash"]
    assert configs[0]["created_at"] != configs[1]["created_at"]
    assert (paths[0].parent / "train.jsonl").read_bytes() == (
        paths[1].parent / "train.jsonl"
    ).read_bytes()
