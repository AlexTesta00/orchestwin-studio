"""Validate pinned Sprint 08 Web runner definitions before Docker builds."""

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


@dataclass(frozen=True, slots=True)
class RunnerManifestValidation:
    errors: tuple[str, ...]
    runner_ids: tuple[str, ...]
    base_image_references: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.errors


def validate_web_runner_manifest(repository_root: Path) -> RunnerManifestValidation:
    """Validate manifest identity, Dockerfile pins, and capability-honest defaults."""
    root = repository_root.resolve()
    manifest_path = root / "infra" / "web-runners" / "images.lock.json"
    errors: list[str] = []
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return RunnerManifestValidation(
            errors=(f"Runner manifest could not be read: {error}",),
            runner_ids=(),
            base_image_references=(),
        )

    if payload.get("schema_version") != 1:
        errors.append("Runner manifest schema_version must equal 1.")

    base_images = payload.get("base_images")
    runners = payload.get("runners")
    if not isinstance(base_images, list) or not isinstance(runners, list):
        return RunnerManifestValidation(
            errors=tuple((*errors, "Runner manifest requires base_images and runners arrays.")),
            runner_ids=(),
            base_image_references=(),
        )

    image_references: dict[str, str] = {}
    for image in base_images:
        if not isinstance(image, dict):
            errors.append("Each base image entry must be an object.")
            continue
        image_id = image.get("image_id")
        reference = image.get("reference")
        if not isinstance(image_id, str) or not image_id:
            errors.append("Each base image requires a normalized image_id.")
            continue
        if image_id in image_references:
            errors.append(f"Duplicate base image ID: {image_id}.")
            continue
        if not isinstance(reference, str) or _DIGEST_REFERENCE.fullmatch(reference) is None:
            errors.append(f"Base image {image_id} is not pinned by a SHA-256 digest.")
            continue
        if ":latest" in reference.casefold():
            errors.append(f"Base image {image_id} must not use the latest tag.")
        image_references[image_id] = reference

    runner_ids: list[str] = []
    referenced_base_images: set[str] = set()
    for runner in runners:
        if not isinstance(runner, dict):
            errors.append("Each runner entry must be an object.")
            continue
        runner_id = runner.get("runner_id")
        dockerfile_value = runner.get("dockerfile_path")
        if not isinstance(runner_id, str) or not runner_id:
            errors.append("Each runner requires a normalized runner_id.")
            continue
        runner_ids.append(runner_id)
        if runner_ids.count(runner_id) > 1:
            errors.append(f"Duplicate runner ID: {runner_id}.")
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

    unused = set(image_references) - referenced_base_images
    if unused:
        errors.append(f"Unreferenced base image IDs: {', '.join(sorted(unused))}.")

    return RunnerManifestValidation(
        errors=tuple(errors),
        runner_ids=tuple(sorted(runner_ids)),
        base_image_references=tuple(sorted(image_references.values())),
    )


def _dockerfile_base_references(
    dockerfile: Path,
    *,
    errors: list[str],
) -> set[str]:
    references: set[str] = set()
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        normalized = line.strip()
        match = _FROM_REFERENCE.fullmatch(normalized)
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
    result = validate_web_runner_manifest(arguments.repository_root)
    if not result.is_valid:
        for error in result.errors:
            print(f"ERROR: {error}")
        return 1
    print(
        "Validated Web runner manifest: "
        f"{len(result.runner_ids)} runners, "
        f"{len(result.base_image_references)} pinned base images."
    )
    for runner_id in result.runner_ids:
        print(f"RUNNER: {runner_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
