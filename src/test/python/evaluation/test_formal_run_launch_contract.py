from __future__ import annotations

import json
from pathlib import Path


def test_formal_run_launch_contract_freezes_revised_scope() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    path = repo_root / "experiments" / "case-studies" / "formal-run-launch-contract-v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["formal_case_family"] == "WEB"
    assert payload["formal_case_ids"] == [
        "web-calculator",
        "hotel-management-web",
        "weather-comparison-web",
    ]
    assert payload["project_mode"] == "GREENFIELD"
    assert payload["required_gate_sequence"] == [
        "PROJECT_BRIEF",
        "AGENT_TEAM",
        "USER_MODELING",
        "REQUIREMENTS",
        "DESIGN",
        "ARCHITECTURE",
        "HIGH_IMPACT_OPERATION",
        "FINAL_OUTPUT",
    ]
    assert set(payload["supported_technologies"]) == {
        "HTML",
        "CSS",
        "JavaScript",
        "Node.js",
        "Vue",
        "Express",
        "Java",
        "Kotlin",
        "Scala",
    }
    assert payload["forbidden_technologies"] == ["PHP"]
    assert payload["owner_gates_must_not_be_bypassed"] is True
    assert payload["launch_inputs_are_configuration_not_results"] is True
    assert payload["actual_case_results_require_observed_evidence"] is True
    assert payload["permanent_claim_flags"] == {
        "real_user_behavior_validated": False,
        "empirical_user_evidence_created": False,
    }


def test_formal_run_launch_contract_contains_no_stale_mobile_scope_in_case_ids() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    path = repo_root / "experiments" / "case-studies" / "formal-run-launch-contract-v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    joined = " ".join(payload["formal_case_ids"]).lower()
    for token in ("android", "flutter", "apk", "emulator"):
        assert token not in joined
