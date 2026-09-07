from __future__ import annotations

from pathlib import Path

from orchestwin.evaluation.case_launch_inputs import (
    REQUIRED_FORMAL_GATES,
    load_formal_case_launch_input,
)


def test_hotel_formal_run_input_is_frozen_and_governed() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    launch = load_formal_case_launch_input(
        repo_root / "experiments" / "case-studies" / "run-inputs" / "hotel-management-web-v1.json"
    )

    assert launch.case_id == "hotel-management-web"
    assert launch.execution_profile == "WEB_VUE_NODE"
    assert launch.technologies == ("HTML", "CSS", "JavaScript", "Vue", "Node.js", "Express")
    assert launch.user_twin_roles == ("receptionist", "hotel manager")
    assert launch.required_gates == REQUIRED_FORMAL_GATES
    assert launch.project_mode == "GREENFIELD"
    assert launch.content_hash
