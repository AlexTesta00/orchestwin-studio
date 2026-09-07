"""Tests for the repository-owned model-spike benchmark artifacts."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from orchestwin.training.benchmark_suite_files import (
    FROZEN_BENCHMARK_SOURCE_MANIFEST_PATH,
    FROZEN_BENCHMARK_SOURCE_MANIFEST_SHA256,
    FROZEN_BENCHMARK_SUITE_CONTENT_HASH,
    FROZEN_BENCHMARK_SUITE_PATH,
    FROZEN_BENCHMARK_SUITE_SHA256,
    FrozenBenchmarkArtifactError,
    benchmark_artifact_sha256,
    load_frozen_benchmark_source_manifest,
    load_frozen_evaluator_benchmark_suite,
)
from orchestwin.training.benchmark_tasks import BenchmarkTaskCategory
from orchestwin.training.dataset_examples import DatasetLanguage

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def test_frozen_suite_loads_with_exact_file_and_content_identity() -> None:
    suite = load_frozen_evaluator_benchmark_suite()

    assert suite.suite_id == "evaluator-benchmark-protocol-v1"
    assert suite.version_number == 1
    assert suite.content_hash == FROZEN_BENCHMARK_SUITE_CONTENT_HASH
    assert suite.source_manifest_sha256 == FROZEN_BENCHMARK_SOURCE_MANIFEST_SHA256
    assert (
        benchmark_artifact_sha256(REPOSITORY_ROOT / FROZEN_BENCHMARK_SUITE_PATH)
        == FROZEN_BENCHMARK_SUITE_SHA256
    )
    assert (
        benchmark_artifact_sha256(REPOSITORY_ROOT / FROZEN_BENCHMARK_SOURCE_MANIFEST_PATH)
        == FROZEN_BENCHMARK_SOURCE_MANIFEST_SHA256
    )


def test_suite_balances_every_protocol_category_across_both_languages() -> None:
    suite = load_frozen_evaluator_benchmark_suite()
    combinations = Counter((task.language, task.category) for task in suite.tasks)

    assert len(suite.tasks) == 12
    assert combinations == Counter(
        {
            (language, category): 1
            for language in DatasetLanguage
            for category in BenchmarkTaskCategory
        }
    )


def test_suite_preserves_abstention_role_and_context_expectations() -> None:
    suite = load_frozen_evaluator_benchmark_suite()

    abstention_tasks = [
        task for task in suite.tasks if task.category is BenchmarkTaskCategory.ABSTENTION
    ]
    role_tasks = [
        task for task in suite.tasks if task.category is BenchmarkTaskCategory.ROLE_ADHERENCE
    ]
    context_tasks = [
        task for task in suite.tasks if task.category is BenchmarkTaskCategory.CONTEXT_HANDLING
    ]

    assert all(task.expected.should_abstain for task in abstention_tasks)
    assert all(task.expected.maximum_findings == 0 for task in abstention_tasks)
    assert all(task.expected.required_role_terms for task in role_tasks)
    assert all(len(task.expected.required_evidence_refs) == 2 for task in context_tasks)
    assert all(
        set(task.expected.required_evidence_refs).issubset(task.expected.allowed_evidence_refs)
        for task in suite.tasks
    )


def test_suite_excludes_formal_cases_and_keeps_expected_labels_out_of_inputs() -> None:
    suite = load_frozen_evaluator_benchmark_suite()
    forbidden_case_terms = {
        "calculator",
        "calcolatrice",
        "hotel",
        "albergo",
        "weather",
        "meteo",
    }

    for task in suite.tasks:
        model_visible_text = " ".join(
            (
                task.profile_summary,
                task.scenario,
                task.target_task,
                task.artifact_summary,
                *(item.text for item in task.evidence),
            )
        ).casefold()
        assert not any(term in model_visible_text for term in forbidden_case_terms)
        assert "expected_criteria" not in model_visible_text
        assert "expected_severities" not in model_visible_text


def test_source_manifest_records_methodological_inputs_and_claim_boundaries() -> None:
    manifest = load_frozen_benchmark_source_manifest()
    sources = {item["source_id"]: item for item in manifest["sources"]}
    boundaries = manifest["methodological_boundaries"]

    assert set(sources) == {
        "agentic-ucd-user-twins-paper-2026",
        "fine-tuning-and-dataset-plan",
        "synthetic-finding-schema",
        "user-twin-protocol",
    }
    assert all(len(item["sha256"]) == 64 for item in sources.values())
    assert any("not empirical evidence" in boundary for boundary in boundaries)
    assert any("must abstain" in boundary for boundary in boundaries)
    assert any("formal evaluation cases" in boundary for boundary in boundaries)


def test_loader_rejects_tampered_suite_and_source_manifest(tmp_path: Path) -> None:
    for relative_path in (
        FROZEN_BENCHMARK_SOURCE_MANIFEST_PATH,
        FROZEN_BENCHMARK_SUITE_PATH,
    ):
        source = REPOSITORY_ROOT / relative_path
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    suite_path = tmp_path / FROZEN_BENCHMARK_SUITE_PATH
    payload = json.loads(suite_path.read_text(encoding="utf-8"))
    payload["suite_id"] = "evaluator-benchmark-tampered"
    suite_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FrozenBenchmarkArtifactError, match="suite file digest changed"):
        load_frozen_evaluator_benchmark_suite(tmp_path)

    shutil.copyfile(REPOSITORY_ROOT / FROZEN_BENCHMARK_SUITE_PATH, suite_path)
    source_path = tmp_path / FROZEN_BENCHMARK_SOURCE_MANIFEST_PATH
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    source_payload["manifest_id"] = "tampered"
    source_path.write_text(json.dumps(source_payload), encoding="utf-8")

    with pytest.raises(FrozenBenchmarkArtifactError, match="source manifest digest changed"):
        load_frozen_evaluator_benchmark_suite(tmp_path)
