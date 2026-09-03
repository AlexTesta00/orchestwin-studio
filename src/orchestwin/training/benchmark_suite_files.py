"""Strict loading of the repository-owned frozen evaluator benchmark suite."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Final

from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingSeverity,
)
from orchestwin.training.benchmark_tasks import (
    BenchmarkEvidenceItem,
    BenchmarkExpectedEvaluation,
    BenchmarkMetricDefinition,
    BenchmarkMetricDirection,
    BenchmarkMetricId,
    BenchmarkTaskCategory,
    EvaluatorBenchmarkSuite,
    create_benchmark_suite,
    create_benchmark_task,
)
from orchestwin.training.dataset_examples import DatasetLanguage

FROZEN_BENCHMARK_SOURCE_MANIFEST_PATH: Final = Path(
    "experiments/model-spike/evaluator-benchmark-v1.sources.json"
)
FROZEN_BENCHMARK_SUITE_PATH: Final = Path("experiments/model-spike/evaluator-benchmark-v1.json")
FROZEN_BENCHMARK_SOURCE_MANIFEST_SHA256: Final = (
    "6303aa03dbf462be1aa96e49c3fe2158c804ec1879bce83930fef5c80ea2cfbc"
)
FROZEN_BENCHMARK_SUITE_SHA256: Final = (
    "68d4fb67a727e1ba48751bbe9a436c18857f1d2f71ef2ccc874a3299c5407e0c"
)
FROZEN_BENCHMARK_SUITE_CONTENT_HASH: Final = (
    "53b30e2961d56d6b35543566490461d83108102af6700e2655be0d98548e6795"
)

_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
_MAX_ARTIFACT_BYTES: Final = 2_000_000
_SOURCE_MANIFEST_ID: Final = "evaluator-benchmark-protocol-sources-v1"
_SOURCE_IDS: Final = {
    "agentic-ucd-user-twins-paper-2026",
    "fine-tuning-and-dataset-plan",
    "synthetic-finding-schema",
    "user-twin-protocol",
}


class FrozenBenchmarkArtifactError(ValueError):
    """Raised when a frozen benchmark artifact is missing, changed, or malformed."""


def load_frozen_evaluator_benchmark_suite(
    repository_root: Path | None = None,
) -> EvaluatorBenchmarkSuite:
    """Load and verify the exact suite that must precede candidate measurements."""
    root = _REPOSITORY_ROOT if repository_root is None else repository_root.resolve()
    source_payload, source_sha256 = _load_json_artifact(
        root / FROZEN_BENCHMARK_SOURCE_MANIFEST_PATH,
        label="benchmark source manifest",
    )
    if source_sha256 != FROZEN_BENCHMARK_SOURCE_MANIFEST_SHA256:
        raise FrozenBenchmarkArtifactError("benchmark source manifest digest changed")
    _validate_source_manifest(source_payload)

    suite_payload, suite_sha256 = _load_json_artifact(
        root / FROZEN_BENCHMARK_SUITE_PATH,
        label="benchmark suite",
    )
    if suite_sha256 != FROZEN_BENCHMARK_SUITE_SHA256:
        raise FrozenBenchmarkArtifactError("benchmark suite file digest changed")
    if _required_string(suite_payload, "source_manifest_sha256") != source_sha256:
        raise FrozenBenchmarkArtifactError(
            "benchmark suite does not reference the verified source manifest"
        )

    tasks = tuple(
        _parse_task(item, index=index)
        for index, item in enumerate(_required_list(suite_payload, "tasks"))
    )
    metrics = tuple(
        _parse_metric(item, index=index)
        for index, item in enumerate(_required_list(suite_payload, "metrics"))
    )
    suite = create_benchmark_suite(
        suite_id=_required_string(suite_payload, "suite_id"),
        version_number=_required_integer(suite_payload, "version_number"),
        tasks=tasks,
        source_manifest_sha256=source_sha256,
        frozen_at=_required_datetime(suite_payload, "frozen_at"),
        metrics=metrics,
    )
    if suite.content_hash != FROZEN_BENCHMARK_SUITE_CONTENT_HASH:
        raise FrozenBenchmarkArtifactError("benchmark suite content identity changed")
    if suite.to_snapshot() != suite_payload:
        raise FrozenBenchmarkArtifactError(
            "benchmark suite snapshot is not canonical or contains unexpected fields"
        )
    return suite


def load_frozen_benchmark_source_manifest(
    repository_root: Path | None = None,
) -> dict[str, object]:
    """Return the verified methodological-source manifest for experiment evidence."""
    root = _REPOSITORY_ROOT if repository_root is None else repository_root.resolve()
    payload, digest = _load_json_artifact(
        root / FROZEN_BENCHMARK_SOURCE_MANIFEST_PATH,
        label="benchmark source manifest",
    )
    if digest != FROZEN_BENCHMARK_SOURCE_MANIFEST_SHA256:
        raise FrozenBenchmarkArtifactError("benchmark source manifest digest changed")
    _validate_source_manifest(payload)
    return payload


def benchmark_artifact_sha256(path: Path) -> str:
    """Calculate the digest used by frozen benchmark artifact identities."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_artifact(path: Path, *, label: str) -> tuple[dict[str, object], str]:
    if path.is_symlink() or not path.is_file():
        raise FrozenBenchmarkArtifactError(f"{label} must be a regular file")
    raw = path.read_bytes()
    if len(raw) > _MAX_ARTIFACT_BYTES:
        raise FrozenBenchmarkArtifactError(f"{label} exceeds the configured size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FrozenBenchmarkArtifactError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise FrozenBenchmarkArtifactError(f"{label} must contain a JSON object")
    return payload, hashlib.sha256(raw).hexdigest()


def _validate_source_manifest(payload: Mapping[str, object]) -> None:
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "manifest_id",
            "sources",
            "methodological_boundaries",
        },
        label="benchmark source manifest",
    )
    if _required_integer(payload, "schema_version") != 1:
        raise FrozenBenchmarkArtifactError("unsupported benchmark source manifest schema")
    if _required_string(payload, "manifest_id") != _SOURCE_MANIFEST_ID:
        raise FrozenBenchmarkArtifactError("unexpected benchmark source manifest identity")

    source_ids: set[str] = set()
    for index, source in enumerate(_required_list(payload, "sources")):
        mapping = _required_mapping(source, label=f"benchmark source {index}")
        _require_exact_keys(
            mapping,
            {"source_id", "source_type", "reference", "sha256"},
            label=f"benchmark source {index}",
        )
        source_id = _required_string(mapping, "source_id")
        source_ids.add(source_id)
        _required_string(mapping, "source_type")
        _required_string(mapping, "reference")
        digest = _required_string(mapping, "sha256")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise FrozenBenchmarkArtifactError("benchmark source digest must use SHA-256")
    if source_ids != _SOURCE_IDS:
        raise FrozenBenchmarkArtifactError("benchmark methodological sources changed")

    boundaries = _required_list(payload, "methodological_boundaries")
    if len(boundaries) != 5 or not all(
        isinstance(item, str) and item.strip() == item and item for item in boundaries
    ):
        raise FrozenBenchmarkArtifactError("benchmark methodological boundaries are invalid")


def _parse_task(value: object, *, index: int):
    payload = _required_mapping(value, label=f"benchmark task {index}")
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "task_id",
            "version_number",
            "category",
            "language",
            "profile_summary",
            "scenario",
            "target_task",
            "artifact_summary",
            "evidence",
            "expected",
            "content_hash",
        },
        label=f"benchmark task {index}",
    )
    if _required_integer(payload, "schema_version") != 1:
        raise FrozenBenchmarkArtifactError("unsupported benchmark task schema")

    expected_payload = _required_mapping(
        payload.get("expected"),
        label=f"benchmark task {index} expected evaluation",
    )
    _require_exact_keys(
        expected_payload,
        {
            "should_abstain",
            "minimum_findings",
            "maximum_findings",
            "allowed_evidence_refs",
            "required_evidence_refs",
            "expected_criteria",
            "expected_severities",
            "required_role_terms",
            "forbidden_claim_fragments",
        },
        label=f"benchmark task {index} expected evaluation",
    )
    expected = BenchmarkExpectedEvaluation(
        should_abstain=_required_boolean(expected_payload, "should_abstain"),
        minimum_findings=_required_integer(expected_payload, "minimum_findings"),
        maximum_findings=_required_integer(expected_payload, "maximum_findings"),
        allowed_evidence_refs=_string_tuple(expected_payload, "allowed_evidence_refs"),
        required_evidence_refs=_string_tuple(expected_payload, "required_evidence_refs"),
        expected_criteria=tuple(
            SyntheticFindingCriterion(item)
            for item in _string_tuple(expected_payload, "expected_criteria")
        ),
        expected_severities=tuple(
            SyntheticFindingSeverity(item)
            for item in _string_tuple(expected_payload, "expected_severities")
        ),
        required_role_terms=_string_tuple(expected_payload, "required_role_terms"),
        forbidden_claim_fragments=_string_tuple(
            expected_payload,
            "forbidden_claim_fragments",
        ),
    )

    evidence = tuple(
        _parse_evidence(item, task_index=index, evidence_index=evidence_index)
        for evidence_index, item in enumerate(_required_list(payload, "evidence"))
    )
    task = create_benchmark_task(
        task_id=_required_string(payload, "task_id"),
        version_number=_required_integer(payload, "version_number"),
        category=BenchmarkTaskCategory(_required_string(payload, "category")),
        language=DatasetLanguage(_required_string(payload, "language")),
        profile_summary=_required_string(payload, "profile_summary"),
        scenario=_required_string(payload, "scenario"),
        target_task=_required_string(payload, "target_task"),
        artifact_summary=_required_string(payload, "artifact_summary"),
        evidence=evidence,
        expected=expected,
    )
    if task.content_hash != _required_string(payload, "content_hash"):
        raise FrozenBenchmarkArtifactError(f"benchmark task {task.task_id} digest changed")
    if task.to_snapshot() != payload:
        raise FrozenBenchmarkArtifactError(
            f"benchmark task {task.task_id} is not a canonical snapshot"
        )
    return task


def _parse_evidence(
    value: object,
    *,
    task_index: int,
    evidence_index: int,
) -> BenchmarkEvidenceItem:
    payload = _required_mapping(
        value,
        label=f"benchmark task {task_index} evidence {evidence_index}",
    )
    _require_exact_keys(
        payload,
        {"reference_id", "text"},
        label=f"benchmark task {task_index} evidence {evidence_index}",
    )
    return BenchmarkEvidenceItem(
        reference_id=_required_string(payload, "reference_id"),
        text=_required_string(payload, "text"),
    )


def _parse_metric(value: object, *, index: int) -> BenchmarkMetricDefinition:
    payload = _required_mapping(value, label=f"benchmark metric {index}")
    _require_exact_keys(
        payload,
        {"metric_id", "direction", "ranking_weight", "threshold"},
        label=f"benchmark metric {index}",
    )
    threshold = payload.get("threshold")
    if threshold is not None and (
        isinstance(threshold, bool) or not isinstance(threshold, (int, float))
    ):
        raise FrozenBenchmarkArtifactError("benchmark metric threshold must be numeric or null")
    return BenchmarkMetricDefinition(
        metric_id=BenchmarkMetricId(_required_string(payload, "metric_id")),
        direction=BenchmarkMetricDirection(_required_string(payload, "direction")),
        ranking_weight=_required_integer(payload, "ranking_weight"),
        threshold=None if threshold is None else float(threshold),
    )


def _required_mapping(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise FrozenBenchmarkArtifactError(f"{label} must be a JSON object")
    return value


def _required_list(values: Mapping[str, object], key: str) -> list[object]:
    value = values.get(key)
    if not isinstance(value, list):
        raise FrozenBenchmarkArtifactError(f"{key} must be a JSON array")
    return value


def _required_string(values: Mapping[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value or value.strip() != value:
        raise FrozenBenchmarkArtifactError(f"{key} must be a normalized string")
    return value


def _required_integer(values: Mapping[str, object], key: str) -> int:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise FrozenBenchmarkArtifactError(f"{key} must be an integer")
    return value


def _required_boolean(values: Mapping[str, object], key: str) -> bool:
    value = values.get(key)
    if not isinstance(value, bool):
        raise FrozenBenchmarkArtifactError(f"{key} must be a boolean")
    return value


def _required_datetime(values: Mapping[str, object], key: str) -> datetime:
    raw = _required_string(values, key)
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as error:
        raise FrozenBenchmarkArtifactError(f"{key} must use ISO-8601") from error
    if value.tzinfo is None or value.utcoffset() is None:
        raise FrozenBenchmarkArtifactError(f"{key} must be timezone-aware")
    return value


def _string_tuple(values: Mapping[str, object], key: str) -> tuple[str, ...]:
    items = _required_list(values, key)
    if not all(isinstance(item, str) and item and item.strip() == item for item in items):
        raise FrozenBenchmarkArtifactError(f"{key} must contain normalized strings")
    return tuple(items)


def _require_exact_keys(
    values: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    if set(values) != expected:
        raise FrozenBenchmarkArtifactError(f"{label} fields do not match the frozen schema")
