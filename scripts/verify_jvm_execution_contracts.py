"""Verify pinned JVM runner and deterministic fixture contracts without executing projects."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Final

_SHA256_REFERENCE = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_TARGETS = ("JVM_JAVA", "JVM_KOTLIN", "JVM_SCALA")
_ALLOWED_RUNNERS = ("jvm.gradle", "jvm.sbt")
_GRADLE_VERSION = "9.5.0"
_GRADLE_DISTRIBUTION_URL = (
    f"https://services.gradle.org/distributions/gradle-{_GRADLE_VERSION}-bin.zip"
)
_GRADLE_LAUNCHER_PATHS = frozenset({"gradlew", "gradlew.bat", "gradle/wrapper/gradle-wrapper.jar"})
_GRADLE_FIXTURES = ("jvm-java-greeting", "jvm-kotlin-calculator")
_MAX_LAUNCHER_SIZE_BYTES = 1024 * 1024
_VERIFICATION_METADATA_PATH = "gradle/verification-metadata.xml"
_VERIFICATION_NAMESPACE = "https://schema.gradle.org/dependency-verification"
_MAX_VERIFICATION_METADATA_BYTES = 2 * 1024 * 1024
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


def declared_fixture_source_paths(root: Path) -> tuple[str, ...] | None:
    """Return an explicit fixture source allow-list when its manifest declares one."""
    manifest_path = root / "fixture.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return None
    manifest = _json(manifest_path)
    raw_paths = manifest.get("source_paths")
    if raw_paths is None:
        return None
    paths = _sequence(raw_paths, label=f"{root.name} source paths")
    normalized: list[str] = []
    for raw in paths:
        if not isinstance(raw, str) or not raw or "\\" in raw:
            raise ContractError(f"{root.name} source paths must use relative POSIX syntax")
        pure = PurePosixPath(raw)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise ContractError(f"{root.name} source path is unsafe: {raw}")
        value = pure.as_posix()
        if value == "fixture.json":
            raise ContractError(f"{root.name} source paths must not include fixture.json")
        normalized.append(value)
    result = tuple(normalized)
    if result != tuple(sorted(set(result))):
        raise ContractError(f"{root.name} source paths must be unique and sorted")
    return result


def is_generated_fixture_path(path: Path, root: Path) -> bool:
    """Return whether a path is outside an explicit fixture contract or known generated state."""
    relative = path.relative_to(root)
    relative_posix = relative.as_posix()
    declared = declared_fixture_source_paths(root)
    if declared is not None:
        return relative_posix != "fixture.json" and relative_posix not in declared
    normalized_parts = tuple(part.casefold() for part in relative.parts)
    return normalized_parts[-1] in GENERATED_FIXTURE_FILE_NAMES or any(
        part in GENERATED_FIXTURE_DIRECTORY_NAMES for part in normalized_parts[:-1]
    )


def fixture_source_content_hash(root: Path) -> str:
    """Hash only source files explicitly owned by one fixture manifest."""
    declared = declared_fixture_source_paths(root)
    if declared is None:
        raise ContractError(f"{root.name} must declare source_paths")
    inventory: list[dict[str, object]] = []
    for relative in declared:
        path = root.joinpath(*PurePosixPath(relative).parts)
        if path.is_symlink() or not path.is_file():
            raise ContractError(f"{root.name} declared source is missing: {relative}")
        raw = path.read_bytes()
        inventory.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
            }
        )
    encoded = json.dumps(
        inventory,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def undeclared_fixture_source_candidates(root: Path) -> tuple[str, ...]:
    """Detect source-like contract inputs added without updating source_paths."""
    declared = set(declared_fixture_source_paths(root) or ())
    build_inputs = {
        "build.gradle.kts",
        "settings.gradle.kts",
        "gradle.properties",
        "gradle/verification-metadata.xml",
        "gradle/wrapper/gradle-wrapper.properties",
        "build.sbt",
        "project/build.properties",
    } | _GRADLE_LAUNCHER_PATHS
    candidates: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in declared or relative == "fixture.json":
            continue
        parts = PurePosixPath(relative).parts
        source_tree = len(parts) >= 2 and parts[0] == "src" and parts[1] in {"main", "test"}
        if source_tree or relative in build_inputs:
            candidates.append(relative)
    return tuple(sorted(candidates))


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


def _gradle_launcher_lock(runner_root: Path, *, generator_image: str) -> Mapping[str, object]:
    lock = _json(runner_root / "gradle-wrapper.lock.json")
    if type(lock.get("schema_version")) is not int or lock.get("schema_version") != 1:
        raise ContractError("Gradle wrapper lock schema version must be one")
    if lock.get("gradle_version") != _GRADLE_VERSION:
        raise ContractError("Gradle wrapper lock must pin Gradle 9.5.0")
    distribution = _object(lock.get("distribution"), label="Gradle distribution")
    if distribution.get("url") != _GRADLE_DISTRIBUTION_URL:
        raise ContractError("Gradle distribution URL must match the exact official release")
    if distribution.get("checksum_url") != _GRADLE_DISTRIBUTION_URL + ".sha256":
        raise ContractError("Gradle distribution checksum URL must match the official release")
    if lock.get("wrapper_checksum_url") != (
        f"https://services.gradle.org/distributions/gradle-{_GRADLE_VERSION}-wrapper.jar.sha256"
    ):
        raise ContractError("Gradle wrapper checksum URL must match the official release")
    checksum = distribution.get("sha256")
    if not isinstance(checksum, str) or _SHA256.fullmatch(checksum) is None:
        raise ContractError("Gradle distribution checksum must be lowercase SHA-256")
    paths: set[str] = set()
    for raw_file in _sequence(lock.get("files"), label="Gradle launcher files"):
        file = _object(raw_file, label="Gradle launcher file")
        path = file.get("path")
        if not isinstance(path, str) or path not in _GRADLE_LAUNCHER_PATHS or path in paths:
            raise ContractError("Gradle launcher lock requires unique exact launcher paths")
        digest = file.get("sha256")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise ContractError("Gradle launcher checksum must be lowercase SHA-256")
        size = file.get("size_bytes")
        if type(size) is not int or not 0 < size <= _MAX_LAUNCHER_SIZE_BYTES:
            raise ContractError("Gradle launcher size must be a positive integer up to 1 MiB")
        paths.add(path)
    if paths != _GRADLE_LAUNCHER_PATHS:
        raise ContractError("Gradle launcher lock must contain the complete launcher")
    generator = _object(lock.get("generator"), label="Gradle launcher generator")
    image_reference = generator.get("image_reference")
    if not isinstance(image_reference, str) or _SHA256_REFERENCE.fullmatch(image_reference) is None:
        raise ContractError("Gradle launcher generator image must be pinned by SHA-256")
    if image_reference != generator_image:
        raise ContractError("Gradle launcher generator image must match the pinned Gradle base")
    command = _sequence(generator.get("command"), label="Gradle launcher generator command")
    if not command or any(
        not isinstance(part, str) or not part or any(char in part for char in "\x00\r\n")
        for part in command
    ):
        raise ContractError("Gradle launcher generator command must contain non-empty tokens")
    if tuple(command) != (
        "gradle",
        "--offline",
        "--no-daemon",
        "--console=plain",
        ":wrapper",
        "--gradle-version",
        _GRADLE_VERSION,
        "--distribution-type",
        "bin",
        "--gradle-distribution-sha256-sum",
        checksum,
        "--no-validate-url",
    ):
        raise ContractError(
            "Gradle launcher generator command must match the offline pinned recipe"
        )
    return lock


def _verify_gradle_launcher(
    fixture_directory: Path,
    fixture: Mapping[str, object],
    lock: Mapping[str, object],
) -> None:
    fixture_id = fixture_directory.name
    if fixture.get("launcher_complete") is not True:
        raise ContractError(f"{fixture_id} must declare its complete Gradle launcher")
    source_paths = set(declared_fixture_source_paths(fixture_directory) or ())
    required = _GRADLE_LAUNCHER_PATHS | {"gradle/wrapper/gradle-wrapper.properties"}
    if not required <= source_paths:
        raise ContractError(f"{fixture_id} source paths must include the complete Gradle launcher")
    _verify_gradle_launcher_files(fixture_directory, lock)
    properties_path = _confined_launcher_file(
        fixture_directory, "gradle/wrapper/gradle-wrapper.properties"
    )
    distribution = _object(lock.get("distribution"), label="Gradle distribution")
    expected_properties = {
        "distributionBase": "GRADLE_USER_HOME",
        "distributionPath": "wrapper/dists",
        "distributionUrl": _GRADLE_DISTRIBUTION_URL.replace(":", r"\:", 1),
        "distributionSha256Sum": distribution["sha256"],
        "networkTimeout": "10000",
        "validateDistributionUrl": "true",
        "zipStoreBase": "GRADLE_USER_HOME",
        "zipStorePath": "wrapper/dists",
    }
    properties: dict[str, str] = {}
    for line in _read(properties_path).splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "!")):
            continue
        key, separator, value = line.partition("=")
        if not separator or key in properties:
            raise ContractError(f"{fixture_id} Gradle wrapper properties must be unique and exact")
        properties[key] = value
    if properties != expected_properties:
        raise ContractError(
            f"{fixture_id} Gradle wrapper properties differ from the pinned contract"
        )


def _confined_launcher_file(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    path = root.joinpath(*parts)
    if not path.is_file() or any(
        component.is_symlink() or component.is_junction()
        for component in (root.joinpath(*parts[:index]) for index in range(len(parts) + 1))
    ):
        raise ContractError(f"{root.name} Gradle launcher file is missing or unsafe: {relative}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ContractError(f"{root.name} Gradle launcher file escapes its bundle: {relative}")
    return path


def _verify_gradle_launcher_files(root: Path, lock: Mapping[str, object]) -> None:
    for raw_file in _sequence(lock.get("files"), label="Gradle launcher files"):
        file = _object(raw_file, label="Gradle launcher file")
        relative = str(file["path"])
        path = _confined_launcher_file(root, relative)
        size = int(file["size_bytes"])
        try:
            with path.open("rb") as stream:
                raw = stream.read(size + 1)
        except OSError as error:
            raise ContractError(f"could not read Gradle launcher file: {relative}") from error
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != file["sha256"]:
            raise ContractError(f"{root.name} Gradle launcher differs from its lock: {relative}")


def _verify_gradle_recipe(
    runner_root: Path, *, generator_image: str, lock: Mapping[str, object]
) -> None:
    """Require a checked, world-readable distribution seed and fixed resolver script."""
    recipe = _read(_confined_launcher_file(runner_root, "Dockerfile.gradle"))
    if re.search(r"^\s*#\s*(?:syntax|escape)\s*=", recipe, re.MULTILINE | re.IGNORECASE):
        raise ContractError("Gradle runner recipe must not override Dockerfile parsing")
    instructions = tuple(
        line.strip()
        for line in recipe.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    distribution = _object(lock["distribution"], label="Gradle distribution")
    if instructions != (
        f"FROM {generator_image}",
        "USER root",
        f"ADD --checksum=sha256:{distribution['sha256']} --chmod=0444 "
        f"{distribution['url']} /opt/orchestwin/gradle-{_GRADLE_VERSION}-bin.zip",
        "COPY --chmod=0444 infra/jvm-runners/resolve-dependencies.gradle.kts "
        "/opt/orchestwin/resolve-dependencies.gradle.kts",
        "RUN chmod 0555 /opt/orchestwin",
        "USER gradle",
        "WORKDIR /workspace",
        "ENTRYPOINT []",
        'CMD ["gradle", "--version"]',
    ):
        raise ContractError("Gradle runner recipe differs from its pinned readable seed contract")
    resolver = _confined_launcher_file(runner_root, "resolve-dependencies.gradle.kts")
    if not 0 < resolver.stat().st_size <= _MAX_LAUNCHER_SIZE_BYTES:
        raise ContractError("Gradle dependency resolver script must be non-empty and bounded")


def _verify_gradle_dependency_metadata(root: Path, fixture: Mapping[str, object]) -> None:
    """Check strict checksum policy syntax; actual resolution remains a runtime observation."""
    complete = fixture.get("dependency_verification_complete")
    if type(complete) is not bool:
        raise ContractError(f"{root.name} dependency verification marker must be a boolean")
    if not complete:
        return
    if _VERIFICATION_METADATA_PATH not in (declared_fixture_source_paths(root) or ()):
        raise ContractError(
            f"{root.name} dependency verification metadata must be a declared source"
        )
    path = _confined_launcher_file(root, _VERIFICATION_METADATA_PATH)
    try:
        with path.open("rb") as stream:
            raw = stream.read(_MAX_VERIFICATION_METADATA_BYTES + 1)
        if len(raw) > _MAX_VERIFICATION_METADATA_BYTES:
            raise ContractError(f"{root.name} dependency verification metadata exceeds its limit")
        text = raw.decode("utf-8")
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.IGNORECASE):
            raise ContractError(
                f"{root.name} dependency verification metadata forbids DTD/entities"
            )
        document = ET.fromstring(text)
    except (OSError, UnicodeError, ET.ParseError) as error:
        raise ContractError(
            f"{root.name} dependency verification metadata must be valid XML"
        ) from error

    def tag(name: str) -> str:
        return f"{{{_VERIFICATION_NAMESPACE}}}{name}"

    def invalid() -> None:
        raise ContractError(
            f"{root.name} dependency verification metadata must enforce exact SHA-256"
        )

    schema = "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation"
    if document.tag != tag("verification-metadata") or set(document.attrib) - {schema}:
        invalid()
    if (
        schema in document.attrib
        and re.fullmatch(
            re.escape(_VERIFICATION_NAMESPACE)
            + r"\s+"
            + re.escape(_VERIFICATION_NAMESPACE)
            + r"/dependency-verification-1\.[0-3]\.xsd",
            document.attrib[schema],
        )
        is None
    ):
        invalid()
    if [child.tag for child in document] != [tag("configuration"), tag("components")]:
        invalid()
    configuration, components = document
    if configuration.attrib or components.attrib or not len(components):
        invalid()
    if [child.tag for child in configuration] != [tag("verify-metadata"), tag("verify-signatures")]:
        invalid()
    for element, expected in zip(configuration, ("true", "false"), strict=True):
        if element.attrib or len(element) or (element.text or "").strip() != expected:
            invalid()
    identities: set[tuple[str, str, str]] = set()
    for component in components:
        if component.tag != tag("component") or set(component.attrib) != {
            "group",
            "name",
            "version",
        }:
            invalid()
        identity = tuple(component.attrib[key] for key in ("group", "name", "version"))
        if identity in identities or not all(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,254}", value) for value in identity
        ):
            invalid()
        identities.add(identity)
        if not len(component):
            invalid()
        artifact_names: set[str] = set()
        for artifact in component:
            if artifact.tag != tag("artifact") or set(artifact.attrib) != {"name"}:
                invalid()
            name = artifact.attrib["name"]
            if (
                name in artifact_names
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,254}", name) is None
            ):
                invalid()
            artifact_names.add(name)
            if len(artifact) != 1 or artifact[0].tag != tag("sha256"):
                invalid()
            checksum = artifact[0]
            if (
                set(checksum.attrib) - {"value", "origin", "reason"}
                or _SHA256.fullmatch(checksum.attrib.get("value", "")) is None
                or len(checksum)
            ):
                invalid()
    for element in document.iter():
        if (
            element.tag not in {tag("verify-metadata"), tag("verify-signatures")}
            and (element.text or "").strip()
        ):
            invalid()
        if (element.tail or "").strip():
            invalid()


def verify_generated_gradle_wrapper(repository_root: Path, generated_root: Path) -> None:
    """Verify an isolated generated launcher against pinned repository provenance."""
    runner_root = repository_root.resolve() / "infra/jvm-runners"
    runner_lock = _json(runner_root / "images.lock.json")
    generator_images = [
        image.get("reference")
        for raw_image in _sequence(runner_lock.get("base_images"), label="JVM base images")
        if (image := _object(raw_image, label="JVM base image")).get("image_id")
        == f"gradle-{_GRADLE_VERSION}-jdk21-noble"
    ]
    if len(generator_images) != 1 or not isinstance(generator_images[0], str):
        raise ContractError("Gradle launcher requires the exact pinned Gradle base image")
    lock = _gradle_launcher_lock(runner_root, generator_image=generator_images[0])
    _verify_gradle_launcher_files(generated_root, lock)


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
        if runner_id == "jvm.gradle" and (
            runner.get("dockerfile_path") != "infra/jvm-runners/Dockerfile.gradle"
            or base_ids != (f"gradle-{_GRADLE_VERSION}-jdk21-noble",)
        ):
            raise ContractError("Gradle runner requires its exact Dockerfile and pinned base")
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
    generator_image = image_references.get(f"gradle-{_GRADLE_VERSION}-jdk21-noble")
    if generator_image is None:
        raise ContractError("Gradle launcher requires the exact pinned Gradle base image")
    gradle_lock = _gradle_launcher_lock(runner_root, generator_image=generator_image)
    _verify_gradle_recipe(runner_root, generator_image=generator_image, lock=gradle_lock)

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
        fixture_directory = fixture_root / fixture_id
        fixture = _json(fixture_directory / "fixture.json")
        undeclared = undeclared_fixture_source_candidates(fixture_directory)
        if undeclared:
            raise ContractError(
                f"{fixture_id} contains undeclared source-like contract inputs: "
                f"{', '.join(undeclared)}"
            )
        if fixture_id in _GRADLE_FIXTURES:
            _verify_gradle_launcher(fixture_directory, fixture, gradle_lock)
            _verify_gradle_dependency_metadata(fixture_directory, fixture)
        if fixture.get("source_content_hash") != fixture_source_content_hash(fixture_directory):
            raise ContractError(f"{fixture_id} source content hash differs from declared sources")
        if fixture.get("execution_attested") is not False:
            raise ContractError(f"{fixture_id} must not claim execution evidence")
        if fixture.get("attestation_boundary") != "SOURCE_CONTRACT_ONLY":
            raise ContractError(f"{fixture_id} must declare SOURCE_CONTRACT_ONLY")
    for path in fixture_files:
        relative = path.relative_to(fixture_root).as_posix().casefold()
        content = path.read_bytes().lower()
        if "android" in relative or b"android" in content:
            raise ContractError(f"mobile target material is outside Sprint 09: {relative}")

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
    parser.add_argument("--generated-wrapper-root", type=Path)
    arguments = parser.parse_args(argv)
    try:
        report = verify_repository(arguments.repository_root)
        if arguments.generated_wrapper_root is not None:
            verify_generated_gradle_wrapper(
                arguments.repository_root, arguments.generated_wrapper_root
            )
    except ContractError as error:
        print(f"JVM execution contract verification failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
