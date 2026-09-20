"""Frozen contract tests for the governed Sprint 12 formal case campaign."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
CAMPAIGN_PATH = REPO_ROOT / "experiments" / "case-studies" / "case-execution-campaign-v1.json"


def test_formal_case_campaign_requires_observed_governed_execution() -> None:
    payload = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["campaign_id"] == "s12-formal-web-cases-v1"
    assert payload["formal_case_ids"] == [
        "web-calculator",
        "hotel-management-web",
        "weather-comparison-web",
    ]
    assert payload["execution_mode"] == "GOVERNED_ORCHESTWIN_WORKFLOW"
    assert payload["execution_phases"] == [
        "PREFLIGHT",
        "WORKFLOW",
        "BUILD",
        "TEST",
        "RUNTIME",
        "SYNTHETIC_EVALUATION",
        "EXPORT",
        "FINALIZE",
    ]
    assert all(payload["comparison_policy"].values())
    assert all(payload["evidence_policy"].values())
    assert payload["permanent_claim_flags"] == {
        "real_user_behavior_validated": False,
        "empirical_user_evidence_created": False,
    }


def test_formal_case_campaign_contains_no_stale_mobile_scope() -> None:
    raw = CAMPAIGN_PATH.read_text(encoding="utf-8").lower()

    for forbidden in ("android", "flutter", "jetpack", "compose", "apk", "adb", "emulator"):
        assert forbidden not in raw
