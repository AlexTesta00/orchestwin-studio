"""End-to-end scope verification for the revised Sprint 12 evaluation matrix."""

from __future__ import annotations

from pathlib import Path

from orchestwin.evaluation.matrix_validation import verify_sprint12_evaluation_matrix

_REPO_ROOT = Path(__file__).resolve().parents[4]


def test_revised_sprint12_matrix_is_web_formal_cases_plus_jvm_language_fixtures() -> None:
    summary = verify_sprint12_evaluation_matrix(_REPO_ROOT)

    assert summary.formal_case_ids == (
        "web-calculator",
        "hotel-management-web",
        "weather-comparison-web",
    )
    assert summary.formal_execution_profiles == (
        "WEB_STATIC",
        "WEB_VUE_NODE",
        "WEB_VUE_NODE",
    )
    assert set(summary.covered_web_technologies) == {
        "HTML",
        "CSS",
        "JavaScript",
        "Node.js",
        "Vue",
        "Express",
    }
    assert summary.jvm_languages == ("Java", "Kotlin", "Scala")
    assert summary.jvm_profiles == ("JVM_JAVA", "JVM_KOTLIN", "JVM_SCALA")
    assert summary.mobile_platforms_in_scope is False
