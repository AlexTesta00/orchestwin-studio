"""Keep JVM technical validation separate from the three formal web cases."""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MATRIX_PATH = _REPO_ROOT / "experiments" / "case-studies" / "jvm-validation-v1.json"
_FORBIDDEN_MOBILE_TOKENS = (
    "android",
    "flutter",
    "jetpack",
    "compose",
    "apk",
    "adb",
    "emulator",
)


def test_jvm_validation_matrix_covers_java_kotlin_and_scala() -> None:
    payload = json.loads(_MATRIX_PATH.read_text(encoding="utf-8"))
    fixtures = payload["fixtures"]

    assert payload["family"] == "JVM"
    assert payload["formal_case_study"] is False
    assert [item["language"] for item in fixtures] == ["Java", "Kotlin", "Scala"]
    assert [item["execution_profile"] for item in fixtures] == [
        "JVM_JAVA",
        "JVM_KOTLIN",
        "JVM_SCALA",
    ]
    assert [item["build_tool"] for item in fixtures] == ["Gradle", "Gradle", "sbt"]
    for item in fixtures:
        assert (_REPO_ROOT / item["fixture_path"]).is_dir()


def test_jvm_validation_matrix_contains_no_stale_mobile_scope() -> None:
    raw = _MATRIX_PATH.read_text(encoding="utf-8").lower()

    assert all(token not in raw for token in _FORBIDDEN_MOBILE_TOKENS)
