"""Cross-check the revised Sprint 12 formal web cases and JVM technical matrix."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from orchestwin.evaluation.case_studies import load_case_study_definition

_FORMAL_CASE_FILES = (
    "web-calculator-v1.json",
    "hotel-management-web-v1.json",
    "weather-comparison-web-v1.json",
)
_EXPECTED_FORMAL_IDS = (
    "web-calculator",
    "hotel-management-web",
    "weather-comparison-web",
)
_EXPECTED_WEB_TECHNOLOGIES = {
    "HTML",
    "CSS",
    "JavaScript",
    "Node.js",
    "Vue",
    "Express",
}
_EXPECTED_JVM_LANGUAGES = {"Java", "Kotlin", "Scala"}
_FORBIDDEN_MOBILE_TOKENS = (
    "android",
    "flutter",
    "jetpack",
    "compose",
    "apk",
    "adb",
    "emulator",
)


@dataclass(frozen=True, slots=True)
class EvaluationMatrixSummary:
    """Validated scope summary used by CI and thesis evidence capture."""

    formal_case_ids: tuple[str, ...]
    formal_execution_profiles: tuple[str, ...]
    covered_web_technologies: tuple[str, ...]
    jvm_languages: tuple[str, ...]
    jvm_profiles: tuple[str, ...]
    mobile_platforms_in_scope: bool

    def to_snapshot(self) -> dict[str, object]:
        return {
            "formal_case_ids": list(self.formal_case_ids),
            "formal_execution_profiles": list(self.formal_execution_profiles),
            "covered_web_technologies": list(self.covered_web_technologies),
            "jvm_languages": list(self.jvm_languages),
            "jvm_profiles": list(self.jvm_profiles),
            "mobile_platforms_in_scope": self.mobile_platforms_in_scope,
        }


def verify_sprint12_evaluation_matrix(repo_root: Path) -> EvaluationMatrixSummary:
    """Verify that formal cases exercise generic Web profiles and JVM stays a fixture matrix."""
    case_dir = repo_root / "experiments" / "case-studies"
    cases = tuple(load_case_study_definition(case_dir / name) for name in _FORMAL_CASE_FILES)
    case_ids = tuple(case.case_id for case in cases)
    if case_ids != _EXPECTED_FORMAL_IDS:
        raise ValueError("formal case-study IDs do not match the frozen Sprint 12 scope")
    if any(not case.execution_profile.startswith("WEB_") for case in cases):
        raise ValueError("all three formal Sprint 12 cases must use generic Web profiles")
    covered_web = {technology for case in cases for technology in case.technologies}
    if covered_web != _EXPECTED_WEB_TECHNOLOGIES:
        raise ValueError("formal cases do not cover the frozen Web technology set")

    jvm_path = case_dir / "jvm-validation-v1.json"
    jvm_payload = json.loads(jvm_path.read_text(encoding="utf-8"))
    if jvm_payload["formal_case_study"] is not False:
        raise ValueError("JVM language validation must remain a technical fixture matrix")
    languages = {item["language"] for item in jvm_payload["fixtures"]}
    if languages != _EXPECTED_JVM_LANGUAGES:
        raise ValueError("JVM fixture matrix must cover Java, Kotlin, and Scala")
    profiles = tuple(item["execution_profile"] for item in jvm_payload["fixtures"])

    inspected = [
        case_dir / "definitions-of-done-v1.json",
        *(case_dir / name for name in _FORMAL_CASE_FILES),
        jvm_path,
    ]
    raw = "\n".join(path.read_text(encoding="utf-8") for path in inspected).lower()
    found = [token for token in _FORBIDDEN_MOBILE_TOKENS if token in raw]
    if found:
        raise ValueError(f"stale mobile scope remains in Sprint 12 definitions: {found}")

    return EvaluationMatrixSummary(
        formal_case_ids=case_ids,
        formal_execution_profiles=tuple(case.execution_profile for case in cases),
        covered_web_technologies=tuple(sorted(covered_web)),
        jvm_languages=tuple(sorted(languages)),
        jvm_profiles=profiles,
        mobile_platforms_in_scope=False,
    )
