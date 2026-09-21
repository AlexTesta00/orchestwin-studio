"""Tests for the frozen hotel-management formal case."""

from __future__ import annotations

from pathlib import Path

from orchestwin.evaluation.case_studies import load_case_study_definition

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CASE_PATH = _REPO_ROOT / "experiments" / "case-studies" / "hotel-management-web-v1.json"


def test_hotel_case_is_a_javascript_vue_node_express_application() -> None:
    case = load_case_study_definition(_CASE_PATH)

    assert case.case_id == "hotel-management-web"
    assert case.execution_profile == "WEB_VUE_NODE"
    assert case.technologies == (
        "HTML",
        "CSS",
        "JavaScript",
        "Vue",
        "Node.js",
        "Express",
    )
    assert case.user_twin_roles == ("receptionist", "hotel manager")
    assert len(case.definition_of_done) == 8
