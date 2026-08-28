"""Contract tests for deterministic Java, Kotlin, and Scala generation fixtures."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from orchestwin.jvm_execution.detection import (
    JvmDetectionSnapshot,
    JvmDetectionStatus,
    JvmTextFile,
    detect_jvm_project,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget

_FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "jvm_execution"
_EXPECTED_TARGETS = {
    "jvm-java-greeting": ExecutionTarget.JVM_JAVA,
    "jvm-kotlin-calculator": ExecutionTarget.JVM_KOTLIN,
    "jvm-scala-greeting": ExecutionTarget.JVM_SCALA,
}
_GENERATED_DIRECTORY_NAMES = frozenset({".gradle", "build", "target"})


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _belongs_to_generated_directory(path: Path, directory: Path) -> bool:
    relative_parts = path.relative_to(directory).parts[:-1]
    return any(part in _GENERATED_DIRECTORY_NAMES for part in relative_parts)


def _fixture_files(directory: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in directory.rglob("*")
            if path.is_file() and not _belongs_to_generated_directory(path, directory)
        )
    )


def _source_files(directory: Path) -> tuple[Path, ...]:
    return tuple(path for path in _fixture_files(directory) if path.name != "fixture.json")


def _source_content_hash(directory: Path) -> str:
    inventory = []
    for path in _source_files(directory):
        content = path.read_bytes()
        inventory.append(
            {
                "path": path.relative_to(directory).as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
        )
    encoded = json.dumps(
        inventory,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _detection_snapshot(directory: Path) -> JvmDetectionSnapshot:
    files = _source_files(directory)
    relative_paths = tuple(path.relative_to(directory).as_posix() for path in files)
    text_files: list[JvmTextFile] = []
    for path, relative_path in zip(files, relative_paths, strict=True):
        content_bytes = path.read_bytes()
        try:
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            continue
        text_files.append(
            JvmTextFile(
                normalized_path=relative_path,
                content=content,
                sha256_digest=hashlib.sha256(content_bytes).hexdigest(),
            )
        )
    inventory_hash = hashlib.sha256("\n".join(relative_paths).encode("utf-8")).hexdigest()
    return JvmDetectionSnapshot(
        inventory_content_hash=inventory_hash,
        included_paths=relative_paths,
        text_files=tuple(text_files),
    )


def test_matrix_declares_one_kotlin_formal_case_and_two_technical_fixtures() -> None:
    matrix = _load_json(_FIXTURE_ROOT / "matrix.json")

    assert matrix["fixtures"] == [
        "jvm-java-greeting",
        "jvm-kotlin-calculator",
        "jvm-scala-greeting",
    ]
    assert matrix["formal_case"] == "jvm-kotlin-calculator"
    assert matrix["capability_status"] == "DESIGN_ONLY_LEVEL_C"
    assert matrix["execution_attested"] is False
    assert matrix["runner_build_attested"] is False
    assert matrix["fixture_execution_attested"] is False

    roles = {
        fixture_id: _load_json(_FIXTURE_ROOT / fixture_id / "fixture.json")["role"]
        for fixture_id in matrix["fixtures"]
    }
    assert roles == {
        "jvm-java-greeting": "TECHNICAL_FIXTURE",
        "jvm-kotlin-calculator": "FORMAL_CASE_A",
        "jvm-scala-greeting": "TECHNICAL_FIXTURE",
    }


def test_each_fixture_has_a_stable_hash_and_deterministic_target() -> None:
    for fixture_id, expected_target in _EXPECTED_TARGETS.items():
        directory = _FIXTURE_ROOT / fixture_id
        manifest = _load_json(directory / "fixture.json")
        result = detect_jvm_project(_detection_snapshot(directory))

        assert manifest["target"] == expected_target.value
        assert manifest["source_content_hash"] == _source_content_hash(directory)
        assert manifest["execution_attested"] is False
        assert manifest["attestation_boundary"] == "SOURCE_CONTRACT_ONLY"
        assert manifest["dependency_verification_complete"] is False
        assert result.status is JvmDetectionStatus.SELECTED
        assert result.selected is not None
        assert result.selected.selection.target is expected_target


def test_generated_build_state_is_excluded_from_fixture_contract(tmp_path: Path) -> None:
    directory = tmp_path / "fixture"
    source = directory / "src" / "main" / "kotlin" / "Main.kt"
    source.parent.mkdir(parents=True)
    source.write_text("fun main() = Unit\n", encoding="utf-8")

    gradle_probe = directory / ".gradle" / "file-system.probe"
    gradle_probe.parent.mkdir(parents=True)
    gradle_probe.write_bytes(b"\x03\xdc@?\xfa^3\x9er\x00\x00\x00\x00\x00\x00\x00\x00")

    build_output = directory / "build" / "classes" / "Main.class"
    build_output.parent.mkdir(parents=True)
    build_output.write_bytes(b"\xca\xfe\xba\xbe")

    target_output = directory / "target" / "scala-3.3.8" / "classes" / "Main.class"
    target_output.parent.mkdir(parents=True)
    target_output.write_bytes(b"\xca\xfe\xba\xbe")

    assert _source_files(directory) == (source,)


def test_kotlin_repair_fixture_is_bounded_to_one_changed_source_file() -> None:
    repair_root = _FIXTURE_ROOT / "repairs" / "kotlin-calculator"
    manifest = _load_json(repair_root / "repair.json")
    normalized_path = str(manifest["normalized_path"])
    before = repair_root / "before" / normalized_path
    after = repair_root / "after" / normalized_path

    assert manifest["fixture_id"] == "jvm-kotlin-calculator"
    assert manifest["failure_code"] == "KOTLIN_UNRESOLVED_REFERENCE"
    assert manifest["execution_attested"] is False
    assert before.is_file()
    assert after.is_file()
    assert before.read_bytes() != after.read_bytes()
    assert "missingOperand" in before.read_text(encoding="utf-8")
    assert "left + right" in after.read_text(encoding="utf-8")
    before_paths = [
        path.relative_to(repair_root / "before").as_posix()
        for path in _source_files(repair_root / "before")
    ]
    assert before_paths == [normalized_path]
    after_paths = [
        path.relative_to(repair_root / "after").as_posix()
        for path in _source_files(repair_root / "after")
    ]
    assert after_paths == [normalized_path]


def test_fixture_package_contains_no_mobile_target_material() -> None:
    for path in _fixture_files(_FIXTURE_ROOT):
        relative = path.relative_to(_FIXTURE_ROOT).as_posix().casefold()
        assert "android" not in relative
        assert b"android" not in path.read_bytes().lower()
