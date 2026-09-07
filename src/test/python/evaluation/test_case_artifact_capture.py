"""Tests for content-addressing actual formal case evidence files."""

from __future__ import annotations

import hashlib
import json

import pytest

from orchestwin.evaluation.case_artifact_capture import (
    capture_case_study_evidence,
    load_case_study_evidence_map,
)
from orchestwin.evaluation.case_studies import CaseStudyEvidenceKind


def test_capture_hashes_existing_non_empty_evidence_files(tmp_path) -> None:
    evidence_root = tmp_path / "evidence"
    (evidence_root / "tests").mkdir(parents=True)
    content = b'{"passed":12,"failed":0}\n'
    (evidence_root / "tests" / "report.json").write_bytes(content)
    map_path = tmp_path / "evidence-map.json"
    map_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "kind": "TEST_REPORT",
                        "relative_path": "tests/report.json",
                        "criterion_ids": ["CALC-003"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    entries = load_case_study_evidence_map(map_path)
    references = capture_case_study_evidence(evidence_root, entries)

    assert references[0].kind is CaseStudyEvidenceKind.TEST_REPORT
    assert references[0].sha256_digest == hashlib.sha256(content).hexdigest()
    assert references[0].size_bytes == len(content)
    assert references[0].criterion_ids == ("CALC-003",)


def test_capture_rejects_missing_empty_or_escaping_evidence(tmp_path) -> None:
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    (evidence_root / "empty.json").write_bytes(b"")

    empty_map = tmp_path / "empty-map.json"
    empty_map.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "kind": "TEST_REPORT",
                        "relative_path": "empty.json",
                        "criterion_ids": ["CALC-003"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="empty"):
        capture_case_study_evidence(evidence_root, load_case_study_evidence_map(empty_map))

    escaping_map = tmp_path / "escaping-map.json"
    escaping_map.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "kind": "TEST_REPORT",
                        "relative_path": "../outside.json",
                        "criterion_ids": ["CALC-003"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="inside the evidence root"):
        load_case_study_evidence_map(escaping_map)
