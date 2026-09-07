"""Tests for the frozen weather-comparison formal case."""

from __future__ import annotations

from pathlib import Path

from orchestwin.evaluation.case_studies import load_case_study_definition

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CASE_PATH = _REPO_ROOT / "experiments" / "case-studies" / "weather-comparison-web-v1.json"


def test_weather_case_uses_mocked_provider_comparison_on_the_web_profile() -> None:
    case = load_case_study_definition(_CASE_PATH)

    assert case.case_id == "weather-comparison-web"
    assert case.execution_profile == "WEB_VUE_NODE"
    assert case.technologies == (
        "HTML",
        "CSS",
        "JavaScript",
        "Vue",
        "Node.js",
        "Express",
    )
    assert any("mocked provider" in item.lower() for item in case.constraints)
    assert any("timestamp" in item.description.lower() for item in case.definition_of_done)
