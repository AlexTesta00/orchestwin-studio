from __future__ import annotations

import pytest

from orchestwin.evaluation.case_launch_inputs import (
    REQUIRED_FORMAL_GATES,
    FormalCaseLaunchInput,
    FormalGateType,
    formal_case_launch_input_hash,
    validate_launch_input_against_definition,
)


def _launch(**overrides: object) -> FormalCaseLaunchInput:
    payload: dict[str, object] = {
        "schema_version": 1,
        "case_id": "web-calculator",
        "case_version": 1,
        "case_content_hash": "a" * 64,
        "title": "Accessible Web Calculator",
        "definition_path": "experiments/case-studies/web-calculator-v1.json",
        "project_mode": "GREENFIELD",
        "owner_request": "Create a small calculator.",
        "execution_profile": "WEB_STATIC",
        "technologies": ("HTML", "CSS", "JavaScript"),
        "user_twin_roles": ("novice end user",),
        "constraints": ("No external runtime service",),
        "required_gates": REQUIRED_FORMAL_GATES,
        "network_policy": "No external provider network during runtime.",
        "operator_instructions": ("Use the normal governed workflow.",),
    }
    payload.update(overrides)
    snapshot = {
        "schema_version": payload["schema_version"],
        "case_id": payload["case_id"],
        "case_version": payload["case_version"],
        "case_content_hash": payload["case_content_hash"],
        "title": payload["title"],
        "definition_path": payload["definition_path"],
        "project_mode": payload["project_mode"],
        "owner_request": payload["owner_request"],
        "execution_profile": payload["execution_profile"],
        "technologies": list(payload["technologies"]),
        "user_twin_roles": list(payload["user_twin_roles"]),
        "constraints": list(payload["constraints"]),
        "required_gates": [gate.value for gate in payload["required_gates"]],
        "network_policy": payload["network_policy"],
        "operator_instructions": list(payload["operator_instructions"]),
    }
    return FormalCaseLaunchInput(**payload, content_hash=formal_case_launch_input_hash(snapshot))


def test_launch_input_preserves_complete_gate_sequence_and_supported_stack() -> None:
    launch = _launch()

    assert launch.required_gates == REQUIRED_FORMAL_GATES
    assert launch.required_gates[0] is FormalGateType.PROJECT_BRIEF
    assert launch.required_gates[-1] is FormalGateType.FINAL_OUTPUT
    assert launch.technologies == ("HTML", "CSS", "JavaScript")
    assert launch.to_snapshot()["content_hash"] == launch.content_hash


def test_launch_input_rejects_stale_mobile_or_php_scope() -> None:
    with pytest.raises(ValueError, match="unsupported technologies"):
        _launch(technologies=("HTML", "PHP"))

    with pytest.raises(ValueError, match="stale mobile scope"):
        _launch(operator_instructions=("Open the Android emulator.",))


def test_launch_definition_validator_detects_drift() -> None:
    launch = _launch()
    definition = {
        "case_id": "web-calculator",
        "version": 1,
        "title": "Accessible Web Calculator",
        "family": "WEB",
        "execution_profile": "WEB_STATIC",
        "technologies": ["HTML", "CSS", "JavaScript"],
        "project_brief": "Create a small calculator.",
        "user_twin_roles": ["novice end user"],
        "constraints": ["No external runtime service"],
        "definition_of_done": [],
    }
    # This fixture deliberately uses a placeholder case hash, so drift is detected.
    with pytest.raises(ValueError, match="case content hash"):
        validate_launch_input_against_definition(launch, definition)
