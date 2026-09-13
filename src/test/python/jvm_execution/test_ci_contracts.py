"""Tests for the repository-owned JVM runner and fixture CI verifier."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.verify_jvm_execution_contracts import (
    ContractError,
    main,
    verify_generated_gradle_wrapper,
    verify_repository,
)

_REPOSITORY_ROOT = Path(__file__).parents[4]
_GRADLE_FIXTURES = ("jvm-java-greeting", "jvm-kotlin-calculator")
_LAUNCHER_PATHS = ("gradlew", "gradlew.bat", "gradle/wrapper/gradle-wrapper.jar")


def _copy_contract_tree(target: Path) -> Path:
    repository = target / "repository"
    for relative in (
        Path("infra/jvm-runners"),
        Path("src/test/fixtures/jvm_execution"),
    ):
        source = _REPOSITORY_ROOT / relative
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
    return repository


def test_repository_jvm_contracts_are_pinned_bounded_and_capability_honest() -> None:
    report = verify_repository(_REPOSITORY_ROOT)

    assert report == {
        "base_images": 2,
        "runners": 2,
        "targets": 3,
        "fixtures": 3,
        "fixture_files": report["fixture_files"],
        "capability_status": "DESIGN_ONLY_LEVEL_C",
        "execution_attested": False,
    }
    assert isinstance(report["fixture_files"], int)
    assert report["fixture_files"] > 0


def test_verifier_rejects_an_unearned_runner_attestation(tmp_path: Path) -> None:
    repository = _copy_contract_tree(tmp_path)
    lock_path = repository / "infra/jvm-runners/images.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["runners"][0]["capability_status"] = "VALIDATED_LEVEL_D"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")

    with pytest.raises(ContractError, match="must remain DESIGN_ONLY_LEVEL_C"):
        verify_repository(repository)


def test_verifier_rejects_new_source_input_until_fixture_contract_is_updated(
    tmp_path: Path,
) -> None:
    repository = _copy_contract_tree(tmp_path)
    undeclared = (
        repository
        / "src/test/fixtures/jvm_execution/jvm-kotlin-calculator/src/main/kotlin/Extra.kt"
    )
    undeclared.parent.mkdir(parents=True, exist_ok=True)
    undeclared.write_text("fun extra() = Unit\n", encoding="utf-8")

    with pytest.raises(ContractError, match="undeclared source-like contract inputs"):
        verify_repository(repository)


def test_verifier_rejects_mobile_material_in_the_jvm_fixture_package(tmp_path: Path) -> None:
    repository = _copy_contract_tree(tmp_path)
    forbidden = (
        repository / "src/test/fixtures/jvm_execution/jvm-kotlin-calculator/AndroidManifest.xml"
    )
    forbidden.write_text("<manifest />", encoding="utf-8")

    with pytest.raises(ContractError, match="mobile target material"):
        verify_repository(repository)


@pytest.mark.parametrize("fixture_id", _GRADLE_FIXTURES)
@pytest.mark.parametrize("relative", _LAUNCHER_PATHS)
def test_verifier_rejects_modified_gradle_launcher_bytes(
    tmp_path: Path, fixture_id: str, relative: str
) -> None:
    repository = _copy_contract_tree(tmp_path)
    launcher = repository / "src/test/fixtures/jvm_execution" / fixture_id / relative
    raw = launcher.read_bytes()
    launcher.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])

    with pytest.raises(ContractError, match="Gradle launcher differs from its lock"):
        verify_repository(repository)


@pytest.mark.parametrize("relative", _LAUNCHER_PATHS)
def test_verifier_rejects_missing_gradle_launcher_files(tmp_path: Path, relative: str) -> None:
    repository = _copy_contract_tree(tmp_path)
    launcher = repository / "src/test/fixtures/jvm_execution/jvm-java-greeting" / relative
    launcher.unlink()

    with pytest.raises(ContractError, match="Gradle launcher file is missing or unsafe"):
        verify_repository(repository)


@pytest.mark.parametrize("relative", _LAUNCHER_PATHS)
def test_verifier_requires_launchers_to_be_in_the_source_contract(
    tmp_path: Path, relative: str
) -> None:
    repository = _copy_contract_tree(tmp_path)
    manifest_path = repository / "src/test/fixtures/jvm_execution/jvm-java-greeting/fixture.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_paths"].remove(relative)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ContractError, match="undeclared source-like contract inputs"):
        verify_repository(repository)


@pytest.mark.parametrize("fixture_id", _GRADLE_FIXTURES)
@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_verifier_requires_an_explicit_complete_launcher_marker(
    tmp_path: Path, fixture_id: str, value: object
) -> None:
    repository = _copy_contract_tree(tmp_path)
    manifest_path = repository / "src/test/fixtures/jvm_execution" / fixture_id / "fixture.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["launcher_complete"] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ContractError, match="must declare its complete Gradle launcher"):
        verify_repository(repository)


@pytest.mark.parametrize(
    "mutation", ["missing-checksum", "wrong-checksum", "version-drift", "duplicate-checksum"]
)
def test_verifier_rejects_unpinned_or_ambiguous_wrapper_properties(
    tmp_path: Path, mutation: str
) -> None:
    repository = _copy_contract_tree(tmp_path)
    properties_path = (
        repository
        / "src/test/fixtures/jvm_execution/jvm-kotlin-calculator"
        / "gradle/wrapper/gradle-wrapper.properties"
    )
    properties = properties_path.read_text(encoding="utf-8")
    checksum = next(
        line for line in properties.splitlines() if line.startswith("distributionSha256Sum=")
    )
    if mutation == "missing-checksum":
        properties = properties.replace(checksum, "")
    elif mutation == "wrong-checksum":
        properties = properties.replace(checksum, "distributionSha256Sum=" + "0" * 64)
    elif mutation == "version-drift":
        properties = properties.replace("gradle-9.5.0-bin.zip", "gradle-9.5.1-bin.zip")
    else:
        properties += "\n" + checksum + "\n"
    properties_path.write_text(properties, encoding="utf-8")

    with pytest.raises(ContractError, match="Gradle wrapper properties"):
        verify_repository(repository)


@pytest.mark.parametrize(
    "mutation",
    [
        "schema-bool",
        "version-drift",
        "distribution-url",
        "checksum-url",
        "wrapper-checksum-url",
        "checksum-shape",
        "missing-file",
        "duplicate-file",
        "unsafe-path",
        "file-checksum-shape",
        "file-size-bool",
        "file-size-zero",
        "file-size-excessive",
        "generator-image",
        "generator-wrong-pinned-image",
        "generator-online-command",
        "generator-shell-string",
        "generator-empty-token",
    ],
)
def test_verifier_rejects_invalid_gradle_launcher_provenance(tmp_path: Path, mutation: str) -> None:
    repository = _copy_contract_tree(tmp_path)
    lock_path = repository / "infra/jvm-runners/gradle-wrapper.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if mutation == "schema-bool":
        lock["schema_version"] = True
    elif mutation == "version-drift":
        lock["gradle_version"] = "9.5.1"
    elif mutation == "distribution-url":
        lock["distribution"]["url"] = "https://example.invalid/gradle-9.5.0-bin.zip"
    elif mutation == "checksum-url":
        lock["distribution"]["checksum_url"] = "https://example.invalid/checksum"
    elif mutation == "wrapper-checksum-url":
        lock["wrapper_checksum_url"] = "https://example.invalid/wrapper-checksum"
    elif mutation == "checksum-shape":
        lock["distribution"]["sha256"] = "G" * 64
    elif mutation == "missing-file":
        lock["files"].pop()
    elif mutation == "duplicate-file":
        lock["files"].append(lock["files"][0])
    elif mutation == "unsafe-path":
        lock["files"][0]["path"] = "../gradlew"
    elif mutation == "file-checksum-shape":
        lock["files"][0]["sha256"] = "g" * 64
    elif mutation == "file-size-bool":
        lock["files"][0]["size_bytes"] = True
    elif mutation == "file-size-zero":
        lock["files"][0]["size_bytes"] = 0
    elif mutation == "file-size-excessive":
        lock["files"][0]["size_bytes"] = 1024 * 1024 + 1
    elif mutation == "generator-image":
        lock["generator"]["image_reference"] = "gradle:latest"
    elif mutation == "generator-wrong-pinned-image":
        lock["generator"]["image_reference"] = "example.invalid/gradle@sha256:" + "a" * 64
    elif mutation == "generator-online-command":
        lock["generator"]["command"].remove("--offline")
    elif mutation == "generator-shell-string":
        lock["generator"]["command"] = "gradle wrapper"
    else:
        lock["generator"]["command"] = ["gradle", ""]
    lock_path.write_text(json.dumps(lock), encoding="utf-8")

    with pytest.raises(ContractError, match="Gradle"):
        verify_repository(repository)


def _copy_generated_launchers(target: Path) -> Path:
    generated_root = target / "generated"
    fixture_root = _REPOSITORY_ROOT / "src/test/fixtures/jvm_execution/jvm-java-greeting"
    for relative in _LAUNCHER_PATHS:
        destination = generated_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture_root / relative, destination)
    return generated_root


def test_generated_wrapper_verification_accepts_exact_launcher_bytes_without_properties(
    tmp_path: Path,
) -> None:
    generated_root = _copy_generated_launchers(tmp_path)

    verify_generated_gradle_wrapper(_REPOSITORY_ROOT, generated_root)
    assert (
        main(
            [
                "--repository-root",
                str(_REPOSITORY_ROOT),
                "--generated-wrapper-root",
                str(generated_root),
            ]
        )
        == 0
    )


@pytest.mark.parametrize("mutation", ["modified", "missing"])
def test_generated_wrapper_verification_rejects_modified_or_missing_launchers(
    tmp_path: Path, mutation: str
) -> None:
    generated_root = _copy_generated_launchers(tmp_path)
    wrapper = generated_root / "gradle/wrapper/gradle-wrapper.jar"
    if mutation == "modified":
        wrapper.write_bytes(wrapper.read_bytes() + b"untrusted trailing bytes")
    else:
        wrapper.unlink()

    with pytest.raises(ContractError, match="Gradle launcher"):
        verify_generated_gradle_wrapper(_REPOSITORY_ROOT, generated_root)
    assert (
        main(
            [
                "--repository-root",
                str(_REPOSITORY_ROOT),
                "--generated-wrapper-root",
                str(generated_root),
            ]
        )
        == 1
    )


def test_generated_wrapper_verification_rejects_a_redirected_parent_directory(
    tmp_path: Path,
) -> None:
    generated_root = _copy_generated_launchers(tmp_path)
    redirected_root = tmp_path / "redirected"
    redirected_root.mkdir()
    for relative in ("gradlew", "gradlew.bat"):
        shutil.copyfile(generated_root / relative, redirected_root / relative)
    try:
        (redirected_root / "gradle").symlink_to(generated_root / "gradle", target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Directory symlinks are unavailable: {error}")

    with pytest.raises(ContractError, match="Gradle launcher file is missing or unsafe"):
        verify_generated_gradle_wrapper(_REPOSITORY_ROOT, redirected_root)
