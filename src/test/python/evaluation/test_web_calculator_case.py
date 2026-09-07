"""Tests for the frozen static-web calculator formal case."""

from __future__ import annotations

from pathlib import Path

from orchestwin.evaluation.case_studies import EvaluationFamily, load_case_study_definition

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CASE_PATH = _REPO_ROOT / "experiments" / "case-studies" / "web-calculator-v1.json"


def test_web_calculator_case_uses_the_static_javascript_profile() -> None:
    case = load_case_study_definition(_CASE_PATH)

    assert case.case_id == "web-calculator"
    assert case.family is EvaluationFamily.WEB
    assert case.execution_profile == "WEB_STATIC"
    assert case.technologies == ("HTML", "CSS", "JavaScript")
    assert len(case.definition_of_done) == 8
    assert {item.criterion_id for item in case.definition_of_done} == {
        "CALC-001",
        "CALC-002",
        "CALC-003",
        "CALC-004",
        "CALC-005",
        "CALC-006",
        "CALC-007",
        "CALC-008",
    }
