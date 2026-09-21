"""Tests for immutable and mobile-free formal case-study contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestwin.evaluation.case_studies import (
    CaseStudyEvidenceKind,
    EvaluationFamily,
    case_study_content_hash,
    load_case_study_definition,
)


def _payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "case_id": "contract-smoke",
        "version": 1,
        "title": "Contract smoke case",
        "family": "WEB",
        "execution_profile": "WEB_STATIC",
        "technologies": ["HTML", "CSS", "JavaScript"],
        "project_brief": "Create a deterministic static web interaction.",
        "user_twin_roles": ["novice end user"],
        "constraints": ["No network dependency"],
        "definition_of_done": [
            {
                "criterion_id": "SMOKE-001",
                "description": "The interaction passes its deterministic tests.",
                "evidence": ["TEST_REPORT", "RUNTIME_REPORT"],
            }
        ],
    }


def test_loader_computes_a_stable_hash_when_json_omits_it(tmp_path: Path) -> None:
    payload = _payload()
    path = tmp_path / "case.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    case = load_case_study_definition(path)

    assert case.family is EvaluationFamily.WEB
    assert case.definition_of_done[0].evidence == (
        CaseStudyEvidenceKind.TEST_REPORT,
        CaseStudyEvidenceKind.RUNTIME_REPORT,
    )
    assert case.content_hash == case_study_content_hash(payload)
    assert case.to_snapshot()["content_hash"] == case.content_hash


def test_loader_rejects_stale_mobile_scope(tmp_path: Path) -> None:
    payload = _payload()
    payload["project_brief"] = "Create an Android interaction."
    path = tmp_path / "case.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="stale mobile scope"):
        load_case_study_definition(path)


def test_loader_rejects_a_family_profile_mismatch(tmp_path: Path) -> None:
    payload = _payload()
    payload["family"] = "JVM"
    path = tmp_path / "case.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="JVM case studies require"):
        load_case_study_definition(path)
