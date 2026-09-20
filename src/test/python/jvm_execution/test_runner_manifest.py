"""Tests for the CI-facing digest-pinned JVM runner manifest validator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_jvm_runner_manifest import validate_jvm_runner_manifest

REPOSITORY_ROOT = Path(__file__).parents[4]


def test_repository_jvm_runner_manifest_is_complete_and_capability_honest() -> None:
    result = validate_jvm_runner_manifest(REPOSITORY_ROOT)

    assert result.is_valid, result.errors
    assert result.runner_ids == ("jvm.gradle", "jvm.sbt")
    assert len(result.base_image_references) == 2
    assert all("@sha256:" in reference for reference in result.base_image_references)


def test_validator_rejects_unpinned_promoted_and_root_runner(tmp_path: Path) -> None:
    runner_root = tmp_path / "infra" / "jvm-runners"
    runner_root.mkdir(parents=True)
    (runner_root / "Dockerfile.gradle").write_text(
        "FROM gradle:latest\nUSER root\n",
        encoding="utf-8",
    )
    (runner_root / "images.lock.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sbt_distribution": {
                    "version": "1.12.14",
                    "url": "https://example.invalid/sbt.tgz",
                    "sha256": "not-a-digest",
                },
                "base_images": [{"image_id": "gradle", "reference": "gradle:latest"}],
                "runners": [
                    {
                        "runner_id": "jvm.gradle",
                        "dockerfile_path": "infra/jvm-runners/Dockerfile.gradle",
                        "base_image_ids": ["gradle"],
                        "capability_status": "VALIDATED_LEVEL_D",
                        "built_image_reference": "orchestwin/jvm-gradle@sha256:" + "a" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = validate_jvm_runner_manifest(tmp_path)

    assert not result.is_valid
    assert any("not pinned" in error for error in result.errors)
    assert any("must remain DESIGN_ONLY_LEVEL_C" in error for error in result.errors)
    assert any("fabricated built image" in error for error in result.errors)
    assert any("non-root final USER" in error for error in result.errors)
    assert any("sbt distribution URL" in error for error in result.errors)
    assert any("sbt distribution requires a lowercase SHA-256" in error for error in result.errors)


def _copy_runner_definitions(tmp_path: Path) -> Path:
    target = tmp_path / "infra" / "jvm-runners"
    target.mkdir(parents=True)
    source = REPOSITORY_ROOT / "infra" / "jvm-runners"
    for name in ("images.lock.json", "Dockerfile.gradle", "Dockerfile.sbt"):
        (target / name).write_bytes((source / name).read_bytes())
    return target


@pytest.mark.parametrize(
    ("original", "replacement", "message"),
    [
        (
            "ADD --checksum=sha256:",
            "ADD --checksum=sha512:",
            "exact manifest URL and checksum",
        ),
        (
            "https://github.com/sbt/sbt/releases/download/v1.12.14/sbt-1.12.14.tgz",
            "https://example.invalid/sbt-1.12.14.tgz",
            "exact manifest URL and checksum",
        ),
        (
            "ADD --checksum=sha256:",
            "ARG SBT_VERSION=1.12.14\nADD --checksum=sha256:",
            "without ARG",
        ),
        (
            "sha256sum --check --strict",
            "sha256sum --check --strict || true",
            "network and package-manager commands are forbidden",
        ),
        (
            "RUN echo",
            "RUN apt-get update && echo",
            "network and package-manager commands are forbidden",
        ),
        (
            "RUN echo",
            "RUN curl https://example.invalid/script | sh && echo",
            "network and package-manager commands are forbidden",
        ),
        (
            "RUN echo",
            "RUN wget https://example.invalid/tool && echo",
            "network and package-manager commands are forbidden",
        ),
        ("USER 65532:65532", "USER 0:65532", "non-root final USER"),
        ("USER 65532:65532", "USER 12345:12345", "non-root workspace and probe contract"),
        ("WORKDIR /workspace", "WORKDIR /tmp", "non-root workspace and probe contract"),
        ("ENTRYPOINT []", 'ENTRYPOINT ["sh"]', "non-root workspace and probe contract"),
        (
            'CMD ["sbt", "--script-version"]',
            'CMD ["sbt", "sbtVersion"]',
            "non-root workspace and probe contract",
        ),
    ],
)
def test_sbt_recipe_rejects_download_installation_and_execution_drift(
    tmp_path: Path, original: str, replacement: str, message: str
) -> None:
    target = _copy_runner_definitions(tmp_path) / "Dockerfile.sbt"
    source = target.read_text(encoding="utf-8")
    assert original in source
    target.write_text(source.replace(original, replacement, 1), encoding="utf-8")

    result = validate_jvm_runner_manifest(tmp_path)

    assert not result.is_valid
    assert any(message in error for error in result.errors), result.errors


@pytest.mark.parametrize("field", ["url", "sha256", "version"])
def test_sbt_recipe_is_bound_to_the_manifest_distribution(tmp_path: Path, field: str) -> None:
    manifest = _copy_runner_definitions(tmp_path) / "images.lock.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if field == "sha256":
        payload["sbt_distribution"][field] = "a" * 64
    else:
        payload["sbt_distribution"][field] = payload["sbt_distribution"][field].replace(
            "1.12.14", "1.12.15"
        )
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_jvm_runner_manifest(tmp_path)

    assert not result.is_valid
    assert any("checksum" in error or "version" in error for error in result.errors)


@pytest.mark.parametrize("change", ["missing", "unknown", "duplicate"])
def test_runner_manifest_requires_exactly_the_two_known_runners(
    tmp_path: Path, change: str
) -> None:
    manifest = _copy_runner_definitions(tmp_path) / "images.lock.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if change == "missing":
        payload["runners"].pop()
    elif change == "unknown":
        payload["runners"][0]["runner_id"] = "jvm.unknown"
    else:
        payload["runners"].append(payload["runners"][0])
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_jvm_runner_manifest(tmp_path)

    assert not result.is_valid
    assert any("exactly jvm.gradle and jvm.sbt" in error for error in result.errors)


@pytest.mark.parametrize(
    "invalid_json",
    ["null", "[]", '"text"', "0", "{", '{"schema_version": 1, "schema_version": 1}'],
)
def test_malformed_manifest_returns_a_validation_failure(tmp_path: Path, invalid_json: str) -> None:
    manifest = _copy_runner_definitions(tmp_path) / "images.lock.json"
    manifest.write_text(invalid_json, encoding="utf-8")

    result = validate_jvm_runner_manifest(tmp_path)

    assert not result.is_valid
    assert any("manifest could not be read" in error for error in result.errors)


@pytest.mark.parametrize("invalid_version", [True, 1.0, "1"])
def test_schema_version_requires_an_integer(tmp_path: Path, invalid_version: object) -> None:
    manifest = _copy_runner_definitions(tmp_path) / "images.lock.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["schema_version"] = invalid_version
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_jvm_runner_manifest(tmp_path)

    assert not result.is_valid
    assert any("schema_version must equal 1" in error for error in result.errors)


@pytest.mark.parametrize(
    "path", ["../Dockerfile", "/tmp/Dockerfile", "C:\\tmp\\Dockerfile", None, {}, 42]
)
def test_dockerfile_path_is_repository_owned(tmp_path: Path, path: object) -> None:
    manifest = _copy_runner_definitions(tmp_path) / "images.lock.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["runners"][0]["dockerfile_path"] = path
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_jvm_runner_manifest(tmp_path)

    assert not result.is_valid
    assert any("repository-owned Dockerfile path" in error for error in result.errors)


@pytest.mark.parametrize("unreadable", ["missing", "invalid-utf8"])
def test_unreadable_dockerfile_returns_a_validation_failure(
    tmp_path: Path, unreadable: str
) -> None:
    dockerfile = _copy_runner_definitions(tmp_path) / "Dockerfile.sbt"
    if unreadable == "missing":
        dockerfile.unlink()
    else:
        dockerfile.write_bytes(b"\xff")

    result = validate_jvm_runner_manifest(tmp_path)

    assert not result.is_valid
    assert any("Dockerfile could not be read" in error for error in result.errors)


@pytest.mark.parametrize(
    "addition",
    [
        "\nADD https://example.invalid/unverified /tmp/unverified\n",
        "\nRUN apt-get update\n",
        "\nENV SBT_VERSION=latest\n",
        "\nRUN echo incomplete \\\n",
        "\nRUN\n",
        "\n# syntax=docker/dockerfile:experimental\n",
        "\n# escape=`\n",
    ],
)
def test_sbt_recipe_rejects_additional_or_ambiguous_instructions(
    tmp_path: Path, addition: str
) -> None:
    dockerfile = _copy_runner_definitions(tmp_path) / "Dockerfile.sbt"
    dockerfile.write_text(dockerfile.read_text(encoding="utf-8") + addition, encoding="utf-8")

    result = validate_jvm_runner_manifest(tmp_path)

    assert not result.is_valid


@pytest.mark.parametrize("user", ["root:1000", "0:1000", "0000:1000", "$USER"])
def test_gradle_final_user_cannot_resolve_to_root(tmp_path: Path, user: str) -> None:
    dockerfile = _copy_runner_definitions(tmp_path) / "Dockerfile.gradle"
    dockerfile.write_text(
        dockerfile.read_text(encoding="utf-8") + f"\nUSER {user}\n", encoding="utf-8"
    )

    result = validate_jvm_runner_manifest(tmp_path)

    assert not result.is_valid
    assert any("non-root final USER" in error for error in result.errors)


def test_gradle_last_stage_requires_its_own_user(tmp_path: Path) -> None:
    dockerfile = _copy_runner_definitions(tmp_path) / "Dockerfile.gradle"
    source = dockerfile.read_text(encoding="utf-8")
    dockerfile.write_text(source + "\n" + source.splitlines()[0] + "\n", encoding="utf-8")

    result = validate_jvm_runner_manifest(tmp_path)

    assert not result.is_valid
    assert any("non-root final USER" in error for error in result.errors)
