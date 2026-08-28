"""Validate pinned Sprint 09 JVM runner definitions before Docker builds."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_DIGEST_REFERENCE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$")
_FROM_REFERENCE: Final = re.compile(r"^FROM\s+([^\s]+)(?:\s+AS\s+\S+)?$", re.IGNORECASE)
_ALLOWED_CAPABILITY: Final = "DESIGN_ONLY_LEVEL_C"
_SBT_RELEASE_URL: Final = re.compile(
    r"^https://github\.com/sbt/sbt/releases/download/v(?P<version>[0-9.]+)/"
    r"sbt-(?P=version)\.tgz$"
)
_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RunnerManifestValidation:
    """Inspectable static-validation outcome for repository-owned runner files."""

    errors: tuple[str, ...]
    runner_ids: tuple[str, ...]
    base_image_references: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.errors


def validate_jvm_runner_manifest(repository_root: Path) -> RunnerManifestValidation:
    """Validate manifest identity, Dockerfile pins, and capability-honest defaults."""
    root = repository_root.resolve()
    manifest_path = root / "infra" / "jvm-runners" / "images.lock.json"
    errors: list[str] = []
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return RunnerManifestValidation(
            errors=(f"JVM runner manifest could not be read: {error}",),
            runner_ids=(),
            base_image_references=(),
        )

    if payload.get("schema_version") != 1:
        errors.append("JVM runner manifest schema_version must equal 1.")
    sbt_distribution = payload.get("sbt_distribution")
    sbt_version: str | None = None
    sbt_sha256: str | None = None
    if not isinstance(sbt_distribution, dict):
        errors.append("JVM runner manifest requires an sbt_distribution object.")
    else:
        version = sbt_distribution.get("version")
        url = sbt_distribution.get("url")
        checksum = sbt_distribution.get("sha256")
        if not isinstance(version, str) or not version:
            errors.append("JVM sbt distribution requires a normalized version.")
        elif not isinstance(url, str) or (match := _SBT_RELEASE_URL.fullmatch(url)) is None:
            errors.append("JVM sbt distribution URL must be an official versioned release asset.")
        elif match.group("version") != version:
            errors.append("JVM sbt distribution URL and version differ.")
        else:
            sbt_version = version
        if not isinstance(checksum, str) or _SHA256.fullmatch(checksum) is None:
            errors.append("JVM sbt distribution requires a lowercase SHA-256 checksum.")
        else:
            sbt_sha256 = checksum
    base_images = payload.get("base_images")
    runners = payload.get("runners")
    if not isinstance(base_images, list) or not isinstance(runners, list):
        return RunnerManifestValidation(
            errors=tuple((*errors, "JVM runner manifest requires base_images and runners arrays.")),
            runner_ids=(),
            base_image_references=(),
        )

    image_references: dict[str, str] = {}
    for image in base_images:
        if not isinstance(image, dict):
            errors.append("Each JVM base image entry must be an object.")
            continue
        image_id = image.get("image_id")
        reference = image.get("reference")
        if not isinstance(image_id, str) or not image_id:
            errors.append("Each JVM base image requires a normalized image_id.")
            continue
        if image_id in image_references:
            errors.append(f"Duplicate JVM base image ID: {image_id}.")
            continue
        if not isinstance(reference, str) or _DIGEST_REFERENCE.fullmatch(reference) is None:
            errors.append(f"JVM base image {image_id} is not pinned by a SHA-256 digest.")
            continue
        if ":latest" in reference.casefold():
            errors.append(f"JVM base image {image_id} must not use the latest tag.")
        image_references[image_id] = reference

    runner_ids: list[str] = []
    referenced_base_images: set[str] = set()
    for runner in runners:
        if not isinstance(runner, dict):
            errors.append("Each JVM runner entry must be an object.")
            continue
        runner_id = runner.get("runner_id")
        dockerfile_value = runner.get("dockerfile_path")
        if not isinstance(runner_id, str) or not runner_id:
            errors.append("Each JVM runner requires a normalized runner_id.")
            continue
        runner_ids.append(runner_id)
        if runner_ids.count(runner_id) > 1:
            errors.append(f"Duplicate JVM runner ID: {runner_id}.")
        if runner.get("capability_status") != _ALLOWED_CAPABILITY:
            errors.append(
                f"Runner {runner_id} must remain {_ALLOWED_CAPABILITY} before recorded validation."
            )
        if runner.get("built_image_reference") is not None:
            errors.append(
                f"Runner {runner_id} must not contain a fabricated built image reference."
            )
        if not isinstance(dockerfile_value, str) or not dockerfile_value:
            errors.append(f"Runner {runner_id} requires dockerfile_path.")
            continue
        dockerfile = root / dockerfile_value
        if not dockerfile.is_file():
            errors.append(f"Runner {runner_id} Dockerfile is missing: {dockerfile_value}.")
            continue

        declared_ids = runner.get("base_image_ids")
        if not isinstance(declared_ids, list) or not declared_ids:
            errors.append(f"Runner {runner_id} requires at least one base image ID.")
            continue
        declared_references: set[str] = set()
        for image_id in declared_ids:
            if not isinstance(image_id, str) or image_id not in image_references:
                errors.append(f"Runner {runner_id} references an unknown base image ID.")
                continue
            referenced_base_images.add(image_id)
            declared_references.add(image_references[image_id])

        dockerfile_references = _dockerfile_base_references(dockerfile, errors=errors)
        if dockerfile_references != declared_references:
            errors.append(
                f"Runner {runner_id} Dockerfile FROM references differ from its manifest IDs."
            )
        if not _has_non_root_final_user(dockerfile):
            errors.append(f"Runner {runner_id} must declare a non-root final USER.")
        if runner_id == "jvm.sbt":
            declared_version = runner.get("sbt_distribution_version")
            dockerfile_text = dockerfile.read_text(encoding="utf-8")
            if declared_version != sbt_version:
                errors.append(
                    "Runner jvm.sbt must reference the manifest sbt distribution version."
                )
            if sbt_version is not None and f"ARG SBT_VERSION={sbt_version}" not in dockerfile_text:
                errors.append("Runner jvm.sbt Dockerfile does not pin the manifest sbt version.")
            if sbt_sha256 is not None and f"ARG SBT_SHA256={sbt_sha256}" not in dockerfile_text:
                errors.append("Runner jvm.sbt Dockerfile does not pin the manifest sbt checksum.")

    unused = set(image_references) - referenced_base_images
    if unused:
        errors.append(f"Unreferenced JVM base image IDs: {', '.join(sorted(unused))}.")

    return RunnerManifestValidation(
        errors=tuple(errors),
        runner_ids=tuple(sorted(runner_ids)),
        base_image_references=tuple(sorted(image_references.values())),
    )


def _dockerfile_base_references(dockerfile: Path, *, errors: list[str]) -> set[str]:
    references: set[str] = set()
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        match = _FROM_REFERENCE.fullmatch(line.strip())
        if match is None:
            continue
        reference = match.group(1)
        if _DIGEST_REFERENCE.fullmatch(reference) is None:
            errors.append(
                f"Dockerfile {dockerfile.as_posix()} contains an unpinned FROM reference."
            )
        references.add(reference)
    if not references:
        errors.append(f"Dockerfile {dockerfile.as_posix()} contains no FROM instruction.")
    return references


def _has_non_root_final_user(dockerfile: Path) -> bool:
    final_user: str | None = None
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        normalized = line.strip()
        if normalized.upper().startswith("USER "):
            final_user = normalized.split(maxsplit=1)[1].strip()
    return final_user is not None and final_user.casefold() not in {"0", "root"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    result = validate_jvm_runner_manifest(arguments.repository_root)
    if not result.is_valid:
        for error in result.errors:
            print(f"ERROR: {error}")
        return 1
    print(
        "Validated JVM runner manifest: "
        f"{len(result.runner_ids)} runners, "
        f"{len(result.base_image_references)} pinned base images."
    )
    for runner_id in result.runner_ids:
        print(f"RUNNER: {runner_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
