"""Freeze the revised Sprint 12 evaluation scope before formal runs."""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCOPE_PATH = _REPO_ROOT / "experiments" / "case-studies" / "definitions-of-done-v1.json"
_FORBIDDEN_MOBILE_TOKENS = (
    "android",
    "flutter",
    "jetpack",
    "compose",
    "apk",
    "adb",
    "emulator",
)


def test_sprint12_scope_is_frozen_to_web_and_jvm_technologies() -> None:
    payload = json.loads(_SCOPE_PATH.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["sprint"] == 12
    assert payload["formal_case_ids"] == [
        "web-calculator",
        "hotel-management-web",
        "weather-comparison-web",
    ]
    assert payload["technical_validation_families"] == [
        "JVM_JAVA",
        "JVM_KOTLIN",
        "JVM_SCALA",
    ]
    assert payload["evaluation_supported_technologies"] == [
        "HTML",
        "CSS",
        "JavaScript",
        "Node.js",
        "Vue",
        "Express",
        "Java",
        "Kotlin",
        "Scala",
    ]
    assert payload["mobile_platforms_in_scope"] is False
    assert payload["native_mobile_artifacts_required"] is False


def test_sprint12_scope_contains_no_stale_mobile_profile_language() -> None:
    raw = _SCOPE_PATH.read_text(encoding="utf-8").lower()

    assert all(token not in raw for token in _FORBIDDEN_MOBILE_TOKENS)
    assert len(json.loads(raw)["global_definition_of_done"]) == 6
