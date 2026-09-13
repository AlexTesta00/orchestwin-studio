"""Tests for the repository-owned JVM runner and fixture CI verifier."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.verify_jvm_execution_contracts import (
    ContractError,
    fixture_source_content_hash,
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


@pytest.mark.parametrize(
    "mutation",
    [
        "checksum",
        "seed-permissions",
        "script-permissions",
        "extra-run",
        "directory-not-traversable",
        "directory-writable",
        "missing-directory-permissions",
        "chmod-extra-command",
        "extra-from",
        "argument",
        "url",
        "parser",
    ],
)
def test_gradle_recipe_rejects_unpinned_or_inaccessible_seed_and_additional_instructions(
    tmp_path: Path, mutation: str
) -> None:
    repository = _copy_contract_tree(tmp_path)
    path = repository / "infra/jvm-runners/Dockerfile.gradle"
    text = path.read_text(encoding="utf-8")
    if mutation == "checksum":
        lock = json.loads((repository / "infra/jvm-runners/gradle-wrapper.lock.json").read_text())
        text = text.replace(lock["distribution"]["sha256"], "0" * 64)
    elif mutation == "seed-permissions":
        text = text.replace("--chmod=0444", "--chmod=0400", 1)
    elif mutation == "script-permissions":
        text = text.replace("COPY --chmod=0444", "COPY --chmod=0400")
    elif mutation == "extra-run":
        text += "\nRUN apt-get update\n"
    elif mutation == "directory-not-traversable":
        text = text.replace("RUN chmod 0555", "RUN chmod 0444")
    elif mutation == "directory-writable":
        text = text.replace("RUN chmod 0555", "RUN chmod 0777")
    elif mutation == "missing-directory-permissions":
        text = text.replace("RUN chmod 0555 /opt/orchestwin", "")
    elif mutation == "chmod-extra-command":
        text = text.replace(
            "RUN chmod 0555 /opt/orchestwin",
            "RUN chmod 0555 /opt/orchestwin && curl https://example.com",
        )
    elif mutation == "extra-from":
        text += "\n" + text.splitlines()[0] + "\nUSER gradle\n"
    elif mutation == "argument":
        text += "\nARG UNVERIFIED=1\n"
    elif mutation == "url":
        text = text.replace("https://services.gradle.org/", "https://example.com/")
    else:
        text = "# escape=`\n" + text
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ContractError, match="Gradle runner recipe"):
        verify_repository(repository)


def test_gradle_recipe_requires_its_resolver_script_source(tmp_path: Path) -> None:
    repository = _copy_contract_tree(tmp_path)
    (repository / "infra/jvm-runners/resolve-dependencies.gradle.kts").unlink()
    with pytest.raises(ContractError, match="missing or unsafe"):
        verify_repository(repository)


_VALID_VERIFICATION_XML = """<?xml version="1.0" encoding="UTF-8"?>
<verification-metadata xmlns="https://schema.gradle.org/dependency-verification">
  <configuration>
    <verify-metadata>true</verify-metadata>
    <verify-signatures>false</verify-signatures>
  </configuration>
  <components>
    <component group="org.example" name="test-fixture" version="1.0">
      <artifact name="test-fixture-1.0.jar">
        <sha256 value="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" origin="Synthetic unit test only"/>
      </artifact>
    </component>
  </components>
</verification-metadata>
"""


def _set_verification_metadata(repository: Path, payload: str) -> Path:
    root = repository / "src/test/fixtures/jvm_execution/jvm-java-greeting"
    manifest_path = root / "fixture.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = root / "gradle/verification-metadata.xml"
    metadata.write_text(payload, encoding="utf-8")
    manifest["source_paths"] = sorted(
        {*manifest["source_paths"], "gradle/verification-metadata.xml"}
    )
    manifest["dependency_verification_complete"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest["source_content_hash"] = fixture_source_content_hash(root)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return metadata


def test_declared_sha256_metadata_is_validated_without_claiming_execution(tmp_path: Path) -> None:
    repository = _copy_contract_tree(tmp_path)
    _set_verification_metadata(repository, _VALID_VERIFICATION_XML)
    report = verify_repository(repository)
    assert report["execution_attested"] is False
    assert report["capability_status"] == "DESIGN_ONLY_LEVEL_C"


@pytest.mark.parametrize(
    "mutation",
    [
        "malformed",
        "namespace",
        "metadata-disabled",
        "signatures-enabled",
        "trusted-artifacts",
        "ignored-keys",
        "sha1",
        "bad-checksum",
        "missing-checksum",
        "also-trust",
        "duplicate-component",
        "duplicate-artifact",
        "empty-components",
        "dtd",
        "verify-attribute",
    ],
)
def test_verification_metadata_rejects_bypasses_even_when_fixture_hash_is_recomputed(
    tmp_path: Path, mutation: str
) -> None:
    repository = _copy_contract_tree(tmp_path)
    text = _VALID_VERIFICATION_XML
    if mutation == "malformed":
        text = text[:-10]
    elif mutation == "namespace":
        text = text.replace("https://schema.gradle.org/", "https://example.com/")
    elif mutation == "metadata-disabled":
        text = text.replace("<verify-metadata>true", "<verify-metadata>false")
    elif mutation == "signatures-enabled":
        text = text.replace("<verify-signatures>false", "<verify-signatures>true")
    elif mutation in {"trusted-artifacts", "ignored-keys"}:
        text = text.replace("</configuration>", f"<{mutation}/></configuration>")
    elif mutation == "sha1":
        text = text.replace("sha256", "sha1")
    elif mutation == "bad-checksum":
        text = text.replace("a" * 64, "g" * 64)
    elif mutation == "missing-checksum":
        text = text.replace('value="' + "a" * 64 + '"', "")
    elif mutation == "also-trust":
        text = text.replace("/>", '><also-trust value="' + "b" * 64 + '"/></sha256>')
    elif mutation == "duplicate-component":
        component = text[text.index("    <component ") : text.index("  </components>")]
        text = text.replace("  </components>", component + "  </components>")
    elif mutation == "duplicate-artifact":
        artifact = text[text.index("      <artifact ") : text.index("    </component>")]
        text = text.replace("    </component>", artifact + "    </component>")
    elif mutation == "empty-components":
        start, end = text.index("    <component "), text.index("  </components>")
        text = text[:start] + text[end:]
    elif mutation == "dtd":
        text = text.replace(
            "<verification-metadata",
            '<!DOCTYPE verification-metadata [<!ENTITY trusted "true">]><verification-metadata',
            1,
        )
    else:
        text = text.replace("<artifact name=", '<artifact verify="false" name=')
    _set_verification_metadata(repository, text)
    with pytest.raises(ContractError, match="dependency verification metadata"):
        verify_repository(repository)


def test_verification_metadata_cannot_be_modified_outside_the_fixture_hash(tmp_path: Path) -> None:
    repository = _copy_contract_tree(tmp_path)
    metadata = _set_verification_metadata(repository, _VALID_VERIFICATION_XML)
    metadata.write_text(_VALID_VERIFICATION_XML.replace("a" * 64, "b" * 64), encoding="utf-8")
    with pytest.raises(ContractError, match="source content hash differs"):
        verify_repository(repository)


def test_complete_verification_requires_metadata_in_the_source_manifest(tmp_path: Path) -> None:
    repository = _copy_contract_tree(tmp_path)
    metadata = _set_verification_metadata(repository, _VALID_VERIFICATION_XML)
    root = metadata.parents[1]
    metadata.unlink()
    manifest_path = root / "fixture.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_paths"].remove("gradle/verification-metadata.xml")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(
        ContractError, match="dependency verification metadata must be a declared source"
    ):
        verify_repository(repository)
