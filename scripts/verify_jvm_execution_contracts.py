"""Verify pinned JVM runner and deterministic fixture contracts without executing projects."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

_SHA256_REFERENCE = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
_ALLOWED_TARGETS = ("JVM_JAVA", "JVM_KOTLIN", "JVM_SCALA")
_ALLOWED_RUNNERS = ("jvm.gradle", "jvm.sbt")
GENERATED_FIXTURE_DIRECTORY_NAMES: Final = frozenset(
    {
        ".bsp",
        ".gradle",
        ".idea",
        ".kotlin",
        ".metals",
        ".scala-build",
        ".settings",
        ".vscode",
        "__pycache__",
        "bin",
        "build",
        "out",
        "target",
    }
)
GENERATED_FIXTURE_FILE_NAMES: Final = frozenset(
    {
        ".classpath",
        ".ds_store",
        ".factorypath",
        ".project",
        "desktop.ini",
        "thumbs.db",
    }
)


class ContractError(ValueError):
    """Raised when repository-owned JVM verification metadata is inconsistent."""


def _object(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    return value


def _sequence(value: object, *, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ContractError(f"{label} must be a sequence")
    return value


def _json(path: Path) -> Mapping[str, object]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), label=str(path))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"could not read valid JSON from {path}") from error


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ContractError(f"could not read {path}") from error


def is_generated_fixture_path(path: Path, root: Path) -> bool:
    """Return whether a fixture path is tooling or build state rather than source input."""
    relative = path.relative_to(root)
    normalized_parts = tuple(part.casefold() for part in relative.parts)
    return normalized_parts[-1] in GENERATED_FIXTURE_FILE_NAMES or any(
        part in GENERATED_FIXTURE_DIRECTORY_NAMES for part in normalized_parts[:-1]
    )


def _fixture_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and not is_generated_fixture_path(path, root)
        )
    )


def _has_non_root_final_user(dockerfile: str) -> bool:
    users = [
        line.split(None, 1)[1].strip().casefold()
        for line in dockerfile.splitlines()
        if line.strip().casefold().startswith("user ")
    ]
    return bool(users) and users[-1] not in {"root", "0", "0:0"}


def verify_repository(repository_root: Path) -> dict[str, object]:
    """Validate exact runner identities, fixture roles, and capability-honest attestations."""
    root = repository_root.resolve()
    runner_root = root / "infra" / "jvm-runners"
    fixture_root = root / "src" / "test" / "fixtures" / "jvm_execution"
    lock = _json(runner_root / "images.lock.json")
    matrix = _json(fixture_root / "validation-matrix.json")

    if lock.get("schema_version") != 1:
        raise ContractError("JVM runner lock schema version must be one")
    images = _sequence(lock.get("base_images"), label="JVM base images")
    image_references: dict[str, str] = {}
    for raw_image in images:
        image = _object(raw_image, label="JVM base image")
        image_id = str(image.get("image_id", ""))
        reference = str(image.get("reference", ""))
        if not image_id or image_id in image_references:
            raise ContractError("JVM base image IDs must be non-empty and unique")
        if _SHA256_REFERENCE.fullmatch(reference) is None:
            raise ContractError(f"JVM base image {image_id} is not pinned by SHA-256")
        image_references[image_id] = reference

    runners = _sequence(lock.get("runners"), label="JVM runners")
    runner_ids: list[str] = []
    for raw_runner in runners:
        runner = _object(raw_runner, label="JVM runner")
        runner_id = str(runner.get("runner_id", ""))
        if runner_id in runner_ids or runner_id not in _ALLOWED_RUNNERS:
            raise ContractError("JVM runner IDs must match the closed Gradle/sbt set")
        if runner.get("capability_status") != "DESIGN_ONLY_LEVEL_C":
            raise ContractError("unattested JVM runner must remain DESIGN_ONLY_LEVEL_C")
        if runner.get("built_image_reference") is not None:
            raise ContractError("repository contract must not fabricate a built JVM image digest")
        base_ids = tuple(
            str(item) for item in _sequence(runner.get("base_image_ids"), label="base IDs")
        )
        if not base_ids or not set(base_ids) <= set(image_references):
            raise ContractError("JVM runner references an unknown base image")
        dockerfile_path = root / str(runner.get("dockerfile_path", ""))
        dockerfile = _read(dockerfile_path)
        expected_references = [image_references[image_id] for image_id in base_ids]
        if not any(reference in dockerfile for reference in expected_references):
            raise ContractError(f"{runner_id} Dockerfile does not use its pinned base image")
        if not _has_non_root_final_user(dockerfile):
            raise ContractError(f"{runner_id} Dockerfile must run as a non-root user")
        runner_ids.append(runner_id)
    if tuple(sorted(runner_ids)) != tuple(sorted(_ALLOWED_RUNNERS)):
        raise ContractError("both Gradle and sbt runner contracts are required")

    shapes = _object(matrix.get("validated_project_shapes"), label="validated project shapes")
    if tuple(sorted(shapes)) != _ALLOWED_TARGETS:
        raise ContractError("validation matrix must contain exactly Java, Kotlin, and Scala")
    if matrix.get("formal_case") != {
        "fixture_id": "jvm-kotlin-calculator",
        "target": "JVM_KOTLIN",
        "role": "FORMAL_CASE_A",
    }:
        raise ContractError("Kotlin/JVM must remain the single formal case A")
    if any(
        matrix.get(field) is not False
        for field in (
            "runner_build_attested",
            "fixture_execution_attested",
            "general_llm_generation_attested",
            "mobile_target_material_present",
        )
    ):
        raise ContractError("JVM matrix contains an unsupported execution or mobile attestation")

    fixture_ids = (
        "jvm-java-greeting",
        "jvm-kotlin-calculator",
        "jvm-scala-greeting",
    )
    fixture_files = _fixture_files(fixture_root)
    for fixture_id in fixture_ids:
        fixture = _json(fixture_root / fixture_id / "fixture.json")
        if fixture.get("execution_attested") is not False:
            raise ContractError(f"{fixture_id} must not claim execution evidence")
        if fixture.get("attestation_boundary") != "SOURCE_CONTRACT_ONLY":
            raise ContractError(f"{fixture_id} must declare SOURCE_CONTRACT_ONLY")
    for path in fixture_files:
        relative = path.relative_to(fixture_root).as_posix().casefold()
        content = path.read_bytes().lower()
        if "android" in relative or b"android" in content:
            raise ContractError(f"mobile target material is outside Sprint 09: {relative}")

    gradle_versions = {
        _read(fixture_root / fixture_id / "gradle/wrapper/gradle-wrapper.properties")
        for fixture_id in ("jvm-java-greeting", "jvm-kotlin-calculator")
    }
    if len(gradle_versions) != 1 or "gradle-9.5.0-bin.zip" not in next(iter(gradle_versions)):
        raise ContractError("Java and Kotlin fixtures must use the exact Gradle 9.5.0 wrapper")
    if "sbt.version=1.12.14" not in _read(
        fixture_root / "jvm-scala-greeting" / "project/build.properties"
    ):
        raise ContractError("Scala fixture must use the exact sbt 1.12.14 launcher")

    return {
        "base_images": len(images),
        "runners": len(runners),
        "targets": len(shapes),
        "fixtures": len(fixture_ids),
        "fixture_files": len(fixture_files),
        "capability_status": "DESIGN_ONLY_LEVEL_C",
        "execution_attested": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args(argv)
    try:
        report = verify_repository(arguments.repository_root)
    except ContractError as error:
        print(f"JVM execution contract verification failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
