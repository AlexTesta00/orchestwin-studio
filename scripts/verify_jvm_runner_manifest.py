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
_VERSION: Final = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_RUNNER_PATHS: Final = {
    "jvm.gradle": "infra/jvm-runners/Dockerfile.gradle",
    "jvm.sbt": "infra/jvm-runners/Dockerfile.sbt",
}


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate manifest key: {key}.")
        result[key] = value
    return result


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
        if not manifest_path.resolve().is_relative_to(root):
            raise ValueError("Manifest path must remain inside the repository.")
        payload = json.loads(
            manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object
        )
        if not isinstance(payload, dict):
            raise ValueError("Manifest must be a JSON object.")
    except (OSError, ValueError) as error:
        return RunnerManifestValidation(
            errors=(f"JVM runner manifest could not be read: {error}",),
            runner_ids=(),
            base_image_references=(),
        )

    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        errors.append("JVM runner manifest schema_version must equal 1.")
    sbt_distribution = payload.get("sbt_distribution")
    sbt_version: str | None = None
    sbt_sha256: str | None = None
    sbt_url: str | None = None
    if not isinstance(sbt_distribution, dict):
        errors.append("JVM runner manifest requires an sbt_distribution object.")
    else:
        version = sbt_distribution.get("version")
        url = sbt_distribution.get("url")
        checksum = sbt_distribution.get("sha256")
        if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
            errors.append("JVM sbt distribution requires a normalized version.")
        elif not isinstance(url, str) or (match := _SBT_RELEASE_URL.fullmatch(url)) is None:
            errors.append("JVM sbt distribution URL must be an official versioned release asset.")
        elif match.group("version") != version:
            errors.append("JVM sbt distribution URL and version differ.")
        else:
            sbt_version = version
            sbt_url = url
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
        if runner_id not in _RUNNER_PATHS:
            errors.append(f"Unknown JVM runner ID: {runner_id}.")
            continue
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
        if dockerfile_value != _RUNNER_PATHS[runner_id]:
            errors.append(f"Runner {runner_id} requires its repository-owned Dockerfile path.")
            continue
        dockerfile = (root / dockerfile_value).resolve()
        if not dockerfile.is_relative_to(root):
            errors.append(f"Runner {runner_id} Dockerfile must remain inside the repository.")
            continue
        try:
            dockerfile_text = dockerfile.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            errors.append(f"Runner {runner_id} Dockerfile could not be read: {error}.")
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

        instructions = _dockerfile_instructions(dockerfile_text, runner_id, errors=errors)
        dockerfile_references = _dockerfile_base_references(instructions, runner_id, errors=errors)
        if dockerfile_references != declared_references:
            errors.append(
                f"Runner {runner_id} Dockerfile FROM references differ from its manifest IDs."
            )
        if not _has_non_root_final_user(instructions):
            errors.append(f"Runner {runner_id} must declare a non-root final USER.")
        if runner_id == "jvm.sbt":
            declared_version = runner.get("sbt_distribution_version")
            if declared_version != sbt_version:
                errors.append(
                    "Runner jvm.sbt must reference the manifest sbt distribution version."
                )
            _validate_sbt_recipe(instructions, sbt_url, sbt_sha256, errors=errors)

    if set(runner_ids) != set(_RUNNER_PATHS) or len(runner_ids) != len(_RUNNER_PATHS):
        errors.append("JVM runner manifest must contain exactly jvm.gradle and jvm.sbt.")

    unused = set(image_references) - referenced_base_images
    if unused:
        errors.append(f"Unreferenced JVM base image IDs: {', '.join(sorted(unused))}.")

    return RunnerManifestValidation(
        errors=tuple(errors),
        runner_ids=tuple(sorted(runner_ids)),
        base_image_references=tuple(sorted(image_references.values())),
    )


def _dockerfile_instructions(
    text: str, runner_id: str, *, errors: list[str]
) -> tuple[tuple[str, str], ...]:
    """Parse the deliberately small, repository-owned Dockerfile syntax subset."""
    instructions: list[tuple[str, str]] = []
    continuation: list[str] = []
    for line in text.splitlines():
        normalized = line.strip()
        if not normalized or normalized.startswith("#"):
            if re.match(r"#\s*(syntax|escape)\s*=", normalized, re.IGNORECASE):
                errors.append(f"Runner {runner_id} must not override Dockerfile parsing.")
            continue
        if normalized.endswith("\\"):
            continuation.append(normalized[:-1].rstrip())
            continue
        combined = " ".join((*continuation, normalized))
        continuation.clear()
        parts = combined.split(maxsplit=1)
        if len(parts) != 2:
            errors.append(f"Runner {runner_id} contains a malformed Dockerfile instruction.")
            continue
        instructions.append((parts[0].upper(), parts[1]))
    if continuation:
        errors.append(f"Runner {runner_id} contains an incomplete Dockerfile continuation.")
    return tuple(instructions)


def _dockerfile_base_references(
    instructions: tuple[tuple[str, str], ...], runner_id: str, *, errors: list[str]
) -> set[str]:
    references: set[str] = set()
    for instruction, arguments in instructions:
        if instruction != "FROM":
            continue
        match = _FROM_REFERENCE.fullmatch(f"FROM {arguments}")
        if match is None:
            errors.append(f"Runner {runner_id} contains an unsupported FROM instruction.")
            continue
        reference = match.group(1)
        if _DIGEST_REFERENCE.fullmatch(reference) is None:
            errors.append(f"Runner {runner_id} contains an unpinned FROM reference.")
        references.add(reference)
    if not references:
        errors.append(f"Runner {runner_id} contains no FROM instruction.")
    return references


def _has_non_root_final_user(instructions: tuple[tuple[str, str], ...]) -> bool:
    final_user: str | None = None
    for instruction, arguments in instructions:
        if instruction == "FROM":
            final_user = None
        elif instruction == "USER":
            final_user = arguments.split(":", maxsplit=1)[0]
    return (
        final_user is not None
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", final_user) is not None
        and final_user.casefold() != "root"
        and set(final_user) != {"0"}
    )


def _validate_sbt_recipe(
    instructions: tuple[tuple[str, str], ...],
    url: str | None,
    checksum: str | None,
    *,
    errors: list[str],
) -> None:
    """Require one checked remote asset followed only by a local installation."""
    names = tuple(instruction for instruction, _ in instructions)
    if names != ("FROM", "ADD", "RUN", "USER", "WORKDIR", "ENTRYPOINT", "CMD"):
        errors.append(
            "Runner jvm.sbt requires the fixed installation sequence without ARG, "
            "extra downloads, or package-manager instructions."
        )
        return
    arguments = dict(instructions)
    if url is not None and checksum is not None:
        if arguments["ADD"] != f"--checksum=sha256:{checksum} {url} /tmp/sbt.tgz":
            errors.append("Runner jvm.sbt ADD must pin the exact manifest URL and checksum.")
        expected_install = (
            f'echo "{checksum}  /tmp/sbt.tgz" | sha256sum --check --strict '
            "&& tar --extract --gzip --file /tmp/sbt.tgz --directory /opt "
            "&& ln --symbolic /opt/sbt/bin/sbt /usr/local/bin/sbt "
            "&& rm --force /tmp/sbt.tgz"
        )
        if arguments["RUN"] != expected_install:
            errors.append(
                "Runner jvm.sbt RUN must only verify the manifest checksum and install "
                "the local archive; network and package-manager commands are forbidden."
            )
    if (
        arguments["USER"] != "65532:65532"
        or arguments["WORKDIR"] != "/workspace"
        or arguments["ENTRYPOINT"] != "[]"
        or arguments["CMD"] != '["sbt", "--script-version"]'
    ):
        errors.append("Runner jvm.sbt must retain its non-root workspace and probe contract.")


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
