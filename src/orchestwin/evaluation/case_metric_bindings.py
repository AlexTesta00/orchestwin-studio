"""JSON-pointer bindings from formal case metrics to actual observed evidence files."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from uuid import UUID

_BINDING_KIND = "JSON_POINTER_EVIDENCE"


class MetricValueType(StrEnum):
    """Strict JSON value types accepted for one CaseStudyMeasurement field."""

    INTEGER = "INTEGER"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"


METRIC_FIELD_TYPES: dict[str, MetricValueType] = {
    "gates_completed": MetricValueType.INTEGER,
    "gates_total": MetricValueType.INTEGER,
    "artifacts_completed": MetricValueType.INTEGER,
    "artifacts_total": MetricValueType.INTEGER,
    "requirements_satisfied": MetricValueType.INTEGER,
    "requirements_total": MetricValueType.INTEGER,
    "criteria_satisfied": MetricValueType.INTEGER,
    "criteria_total": MetricValueType.INTEGER,
    "traceability_links_present": MetricValueType.INTEGER,
    "traceability_links_required": MetricValueType.INTEGER,
    "tests_passed": MetricValueType.INTEGER,
    "tests_total": MetricValueType.INTEGER,
    "repair_successes": MetricValueType.INTEGER,
    "repair_attempts": MetricValueType.INTEGER,
    "build_succeeded": MetricValueType.BOOLEAN,
    "final_runtime_succeeded": MetricValueType.BOOLEAN,
    "elapsed_seconds": MetricValueType.NUMBER,
    "model_calls": MetricValueType.INTEGER,
    "input_tokens": MetricValueType.INTEGER,
    "output_tokens": MetricValueType.INTEGER,
    "estimated_cost_usd": MetricValueType.NUMBER,
}


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _validate_relative_json_path(value: str) -> None:
    if not value or value != " ".join(value.split()) or "\\" in value:
        raise ValueError("metric binding source path must be normalized POSIX relative text")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("metric binding source path must remain inside the evidence root")
    if path.suffix.lower() != ".json":
        raise ValueError("metric binding source must be a JSON evidence file")


def _validate_pointer(value: str) -> None:
    if not value.startswith("/") or value == "/":
        raise ValueError("metric binding JSON pointer must be a non-root RFC 6901 pointer")


@dataclass(frozen=True, slots=True)
class CaseMetricBinding:
    """One raw metric field read directly from a JSON pointer in observed evidence."""

    field: str
    value_type: MetricValueType
    source_path: str
    json_pointer: str

    def __post_init__(self) -> None:
        expected = METRIC_FIELD_TYPES.get(self.field)
        if expected is None:
            raise ValueError(f"unsupported formal case metric field: {self.field}")
        if self.value_type is not expected:
            raise ValueError(f"metric field {self.field} requires {expected.value}")
        _validate_relative_json_path(self.source_path)
        _validate_pointer(self.json_pointer)

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return (self.field, self.source_path, self.json_pointer)

    def to_snapshot(self) -> dict[str, str]:
        return {
            "field": self.field,
            "type": self.value_type.value,
            "source_path": self.source_path,
            "json_pointer": self.json_pointer,
        }


@dataclass(frozen=True, slots=True)
class CaseMetricBindingSet:
    """Complete immutable binding set for one real OrchesTwin workflow run."""

    schema_version: int
    binding_kind: str
    case_id: str
    workflow_run_id: UUID
    bindings: tuple[CaseMetricBinding, ...]
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.binding_kind != _BINDING_KIND:
            raise ValueError("unsupported formal case metric binding schema")
        if not self.case_id or self.case_id != " ".join(self.case_id.split()):
            raise ValueError("metric binding case ID must be normalized")
        ordered = tuple(sorted(self.bindings, key=lambda item: item.sort_key))
        if self.bindings != ordered:
            raise ValueError("metric bindings must use canonical field order")
        fields = tuple(binding.field for binding in self.bindings)
        if len(fields) != len(set(fields)):
            raise ValueError("metric bindings must contain each field exactly once")
        if set(fields) != set(METRIC_FIELD_TYPES):
            missing = sorted(set(METRIC_FIELD_TYPES) - set(fields))
            extra = sorted(set(fields) - set(METRIC_FIELD_TYPES))
            raise ValueError(
                f"metric binding field set is incomplete: missing={missing}, extra={extra}"
            )
        if self.content_hash != _hash(self.to_snapshot(include_hash=False)):
            raise ValueError("metric binding content hash is inconsistent")

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "schema_version": self.schema_version,
            "binding_kind": self.binding_kind,
            "case_id": self.case_id,
            "workflow_run_id": str(self.workflow_run_id),
            "bindings": [binding.to_snapshot() for binding in self.bindings],
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def create_case_metric_binding_set(
    *,
    case_id: str,
    workflow_run_id: UUID,
    bindings: tuple[CaseMetricBinding, ...],
) -> CaseMetricBindingSet:
    """Create one complete canonically ordered binding set."""
    ordered = tuple(sorted(bindings, key=lambda item: item.sort_key))
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "binding_kind": _BINDING_KIND,
        "case_id": case_id,
        "workflow_run_id": str(workflow_run_id),
        "bindings": [binding.to_snapshot() for binding in ordered],
    }
    return CaseMetricBindingSet(
        schema_version=1,
        binding_kind=_BINDING_KIND,
        case_id=case_id,
        workflow_run_id=workflow_run_id,
        bindings=ordered,
        content_hash=_hash(snapshot),
    )


def write_case_metric_binding_set(path: Path, binding_set: CaseMetricBindingSet) -> None:
    """Persist an immutable binding set without overwriting an existing capture recipe."""
    if path.exists():
        raise FileExistsError(f"metric binding file already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"{json.dumps(binding_set.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


def load_case_metric_binding_set(path: Path) -> CaseMetricBindingSet:
    """Load and revalidate one complete metric binding set."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CaseMetricBindingSet(
        schema_version=payload["schema_version"],
        binding_kind=payload["binding_kind"],
        case_id=payload["case_id"],
        workflow_run_id=UUID(payload["workflow_run_id"]),
        bindings=tuple(
            sorted(
                (
                    CaseMetricBinding(
                        field=item["field"],
                        value_type=MetricValueType(item["type"]),
                        source_path=item["source_path"],
                        json_pointer=item["json_pointer"],
                    )
                    for item in payload["bindings"]
                ),
                key=lambda item: item.sort_key,
            )
        ),
        content_hash=payload["content_hash"],
    )


def resolve_json_pointer(document: object, pointer: str) -> object:
    """Resolve a strict RFC 6901 pointer from one parsed JSON document."""
    _validate_pointer(pointer)
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise ValueError(f"JSON pointer token not found: {token}")
            current = current[token]
            continue
        if isinstance(current, list):
            if not token.isdigit() or (token.startswith("0") and token != "0"):
                raise ValueError(f"JSON pointer list token is invalid: {token}")
            index = int(token)
            if index >= len(current):
                raise ValueError(f"JSON pointer list index is out of range: {index}")
            current = current[index]
            continue
        raise ValueError("JSON pointer traversed through a scalar value")
    return current


def _resolve_source_file(evidence_root: Path, source_path: str) -> Path:
    if evidence_root.is_symlink():
        raise ValueError("formal evidence root must not be a symlink")
    root = evidence_root.resolve(strict=True)
    relative = PurePosixPath(source_path)
    current = evidence_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"metric source must not use symlinks: {source_path}")
    try:
        path = (evidence_root / Path(*relative.parts)).resolve(strict=True)
    except FileNotFoundError as error:
        raise ValueError(f"metric source evidence is missing: {source_path}") from error
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"metric source is not a file inside the evidence root: {source_path}")
    if path.stat().st_size < 1:
        raise ValueError(f"metric source evidence is empty: {source_path}")
    return path


def _validate_value(value: object, value_type: MetricValueType, *, field: str) -> object:
    if value_type is MetricValueType.BOOLEAN:
        if not isinstance(value, bool):
            raise ValueError(f"metric field {field} must resolve to a boolean")
        return value
    if value_type is MetricValueType.INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"metric field {field} must resolve to an integer")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"metric field {field} must resolve to a number")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"metric field {field} must resolve to a finite number")
    return numeric


def resolve_metric_binding_value(evidence_root: Path, binding: CaseMetricBinding) -> object:
    """Read one metric value from the actual JSON source selected by its binding."""
    path = _resolve_source_file(evidence_root, binding.source_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    value = resolve_json_pointer(document, binding.json_pointer)
    return _validate_value(value, binding.value_type, field=binding.field)


def resolve_case_metric_values(
    evidence_root: Path,
    binding_set: CaseMetricBindingSet,
) -> dict[str, object]:
    """Resolve every required raw measurement value directly from observed JSON files."""
    return {
        binding.field: resolve_metric_binding_value(evidence_root, binding)
        for binding in binding_set.bindings
    }
