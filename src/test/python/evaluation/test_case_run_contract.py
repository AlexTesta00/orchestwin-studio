"""Freeze the formal Sprint 12 case-study run evidence contract."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
CONTRACT_PATH = REPO_ROOT / "experiments" / "case-studies" / "case-run-contract-v1.json"


def test_case_run_contract_freezes_reproducible_finalized_evidence() -> None:
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["record_kind"] == "FORMAL_CASE_STUDY_RUN"
    assert payload["final_statuses"] == ["ABORTED", "COMPLETED", "FAILED"]
    assert {
        "case_content_hash",
        "workflow_run_id",
        "platform_commit",
        "execution_profile",
        "environment_identity_hash",
        "evidence",
        "measurement",
        "content_hash",
    }.issubset(payload["required_fields"])
    assert payload["invariants"]["evidence_is_content_addressed"] is True
    assert payload["invariants"]["evidence_is_criterion_traceable"] is True
    assert payload["invariants"]["measurement_required_when_completed"] is True
    assert payload["invariants"]["finalized_record_is_immutable"] is True


def test_case_run_contract_keeps_synthetic_and_empirical_claims_separate() -> None:
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    assert payload["permanent_claim_flags"] == {
        "real_user_behavior_validated": False,
        "empirical_user_evidence_created": False,
    }
    raw = CONTRACT_PATH.read_text(encoding="utf-8").lower()
    for stale_token in ("android", "flutter", "jetpack", "apk", "adb", "emulator"):
        assert stale_token not in raw
