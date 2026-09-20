"""Tests for binding metric JSON pointers to immutable observed source manifests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.evaluation.case_metric_bindings import (
    METRIC_FIELD_TYPES,
    CaseMetricBinding,
    create_case_metric_binding_set,
)
from orchestwin.evaluation.case_metric_provenance import verify_metric_binding_provenance
from orchestwin.evaluation.case_source_manifest import capture_observed_evidence_manifest

WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000035001")
NOW = datetime(2026, 9, 7, 18, 30, tzinfo=UTC)


def _binding_set():
    return create_case_metric_binding_set(
        case_id="web-calculator",
        workflow_run_id=WORKFLOW_RUN_ID,
        bindings=tuple(
            CaseMetricBinding(
                field=field,
                value_type=value_type,
                source_path="metrics.json",
                json_pointer=f"/metrics/{field}",
            )
            for field, value_type in METRIC_FIELD_TYPES.items()
        ),
    )


def test_metric_provenance_requires_manifested_unchanged_sources(tmp_path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "metrics.json").write_text(json.dumps({"metrics": {}}), encoding="utf-8")
    manifest = capture_observed_evidence_manifest(
        evidence_root=evidence,
        case_id="web-calculator",
        workflow_run_id=WORKFLOW_RUN_ID,
        relative_paths=("metrics.json",),
        captured_at=NOW,
    )

    summary = verify_metric_binding_provenance(
        evidence_root=evidence, binding_set=_binding_set(), manifest=manifest
    )

    assert summary.metric_source_paths == ("metrics.json",)
    assert summary.evidence_manifest_hash == manifest.content_hash

    (evidence / "metrics.json").write_text('{"changed":true}', encoding="utf-8")
    with pytest.raises(ValueError, match="changed after capture"):
        verify_metric_binding_provenance(
            evidence_root=evidence, binding_set=_binding_set(), manifest=manifest
        )


def test_metric_provenance_rejects_unmanifested_metric_sources(tmp_path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "metrics.json").write_text("{}", encoding="utf-8")
    (evidence / "other.json").write_text("{}", encoding="utf-8")
    manifest = capture_observed_evidence_manifest(
        evidence_root=evidence,
        case_id="web-calculator",
        workflow_run_id=WORKFLOW_RUN_ID,
        relative_paths=("other.json",),
        captured_at=NOW,
    )
    with pytest.raises(ValueError, match="absent from observed evidence manifest"):
        verify_metric_binding_provenance(
            evidence_root=evidence, binding_set=_binding_set(), manifest=manifest
        )
