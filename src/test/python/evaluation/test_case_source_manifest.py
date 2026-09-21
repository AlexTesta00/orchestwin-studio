"""Tests for content-addressing the actual files used by formal metric harvesting."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.evaluation.case_source_manifest import (
    capture_observed_evidence_manifest,
    load_observed_evidence_manifest,
    verify_observed_evidence_manifest,
    write_observed_evidence_manifest,
)

WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000034001")
NOW = datetime(2026, 9, 7, 18, 20, tzinfo=UTC)


def test_manifest_hashes_actual_files_and_detects_later_mutation(tmp_path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "a.json").write_text('{"value":1}\n', encoding="utf-8")
    (evidence / "b.txt").write_text("observed evidence\n", encoding="utf-8")
    manifest = capture_observed_evidence_manifest(
        evidence_root=evidence,
        case_id="web-calculator",
        workflow_run_id=WORKFLOW_RUN_ID,
        relative_paths=("b.txt", "a.json"),
        captured_at=NOW,
    )
    path = tmp_path / "manifest.json"
    write_observed_evidence_manifest(path, manifest)

    loaded = load_observed_evidence_manifest(path)
    verify_observed_evidence_manifest(evidence, loaded)
    assert tuple(source.relative_path for source in loaded.sources) == ("a.json", "b.txt")

    (evidence / "a.json").write_text('{"value":2}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="changed after capture"):
        verify_observed_evidence_manifest(evidence, loaded)


def test_manifest_rejects_symlink_sources(tmp_path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    external = tmp_path / "external.json"
    external.write_text("{}", encoding="utf-8")

    linked = evidence / "linked.json"
    try:
        linked.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable in this test environment")

    with pytest.raises(ValueError, match="must not use symlinks"):
        capture_observed_evidence_manifest(
            evidence_root=evidence,
            case_id="web-calculator",
            workflow_run_id=WORKFLOW_RUN_ID,
            relative_paths=("linked.json",),
            captured_at=NOW,
        )
