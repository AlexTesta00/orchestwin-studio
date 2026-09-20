from __future__ import annotations

from pathlib import Path

from orchestwin.evaluation.case_launch_inputs import (
    REQUIRED_FORMAL_GATES,
    load_formal_case_launch_input,
)


def test_weather_formal_run_input_is_frozen_and_governed() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    launch = load_formal_case_launch_input(
        repo_root / "experiments" / "case-studies" / "run-inputs" / "weather-comparison-web-v1.json"
    )

    assert launch.case_id == "weather-comparison-web"
    assert launch.execution_profile == "WEB_VUE_NODE"
    assert launch.technologies == ("HTML", "CSS", "JavaScript", "Vue", "Node.js", "Express")
    assert launch.user_twin_roles == ("general weather-information user",)
    assert launch.required_gates == REQUIRED_FORMAL_GATES
    assert launch.project_mode == "GREENFIELD"
    assert launch.content_hash
