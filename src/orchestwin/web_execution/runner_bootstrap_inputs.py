"""Bounded immutable inputs for the three explicit Web runner bootstrap recipes.

The locked browser recipe is separate from the historical binary-only recipe.
Image-lock identities select the upstream bases; observed image identity and
execution validation remain the responsibility of later operations.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from orchestwin.web_execution.browser_automation import AutomationError, validate_lock
from orchestwin.web_execution.runners import WebRunnerKind, load_web_runner_image_lock

_MAX_FILE_BYTES = 2 * 1024 * 1024
_LOCK_PATH = "infra/web-runners/images.lock.json"
_BROWSER_ROOT = "infra/web-runners/browser-locked"
_RECIPES = (
    (
        "NODE",
        "web.node",
        "infra/web-runners/Dockerfile.node",
        ("infra/web-runners/Dockerfile.node", "infra/web-runners/bin/static-server.mjs"),
    ),
    (
        "PHP",
        "web.php",
        "infra/web-runners/Dockerfile.php",
        ("infra/web-runners/Dockerfile.php", "infra/web-runners/bin/php-lint.php"),
    ),
    (
        "BROWSER",
        "web.browser",
        f"{_BROWSER_ROOT}/Dockerfile",
        (
            f"{_BROWSER_ROOT}/Dockerfile",
            f"{_BROWSER_ROOT}/package.json",
            f"{_BROWSER_ROOT}/package-lock.json",
        ),
    ),
)
_FROM = re.compile(
    r"FROM\s+([A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64})"
    r"(?:\s+AS\s+[A-Za-z][A-Za-z0-9._-]*)?",
    re.IGNORECASE,
)
_USER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*(?::[A-Za-z0-9_][A-Za-z0-9_.-]*)?")


@dataclass(frozen=True, slots=True)
class BootstrapRunnerRecipe:
    """Exact per-runner identity of pinned bases and captured recipe bytes."""

    kind: str
    runner_id: str
    version: str
    dockerfile_path: str
    base_image_references: tuple[str, ...]
    source_paths: tuple[str, ...]
    recipe_content_hash: str


@dataclass(frozen=True, slots=True)
class WebRunnerBootstrapInputs:
    """Only the allowlisted files can enter the temporary Docker build context."""

    sources: tuple[tuple[str, bytes], ...]
    runners: tuple[BootstrapRunnerRecipe, ...]
    content_hash: str


def load_bootstrap_inputs(root: Path) -> WebRunnerBootstrapInputs:
    """Capture and validate local inputs without starting Git, Docker or a shell."""
    root = Path(root).absolute()
    _safe_path(root)
    try:
        is_directory = root.is_dir()
    except OSError as error:
        raise ValueError("BOOTSTRAP_ROOT_UNREADABLE") from error
    if not is_directory:
        raise ValueError("BOOTSTRAP_ROOT_INVALID")
    paths = sorted({_LOCK_PATH, *(path for _, _, _, paths in _RECIPES for path in paths)})
    sources = {relative: _read(root / relative) for relative in paths}
    _json(sources[_LOCK_PATH])
    try:
        image_lock = load_web_runner_image_lock(root / _LOCK_PATH)
    except (OSError, TypeError, ValueError, KeyError) as error:
        raise ValueError("BOOTSTRAP_IMAGE_LOCK_INVALID") from error
    if _read(root / _LOCK_PATH) != sources[_LOCK_PATH]:
        raise ValueError("BOOTSTRAP_IMAGE_LOCK_CHANGED_DURING_READ")
    if len(image_lock.runners) != 3 or {
        (recipe.kind.value, recipe.runner_id) for recipe in image_lock.runners
    } != {(kind, runner_id) for kind, runner_id, _, _ in _RECIPES}:
        raise ValueError("BOOTSTRAP_RUNNER_SET_INVALID")
    _validate_browser_packages(sources)
    recipes = []
    for kind, runner_id, dockerfile_path, source_paths in _RECIPES:
        definition = image_lock.runner(WebRunnerKind(kind))
        if definition.dockerfile_path != dockerfile_path:
            raise ValueError("BOOTSTRAP_DOCKERFILE_PATH_LOCK_MISMATCH")
        if definition.capability_status.value != "DESIGN_ONLY_LEVEL_C":
            raise ValueError("BOOTSTRAP_IMAGE_LOCK_CAPABILITY_INVALID")
        references = tuple(
            sorted(
                image_lock.base_image(image_id).reference.value
                for image_id in definition.base_image_ids
            )
        )
        _validate_dockerfile(sources[dockerfile_path], references)
        ordered_paths = tuple(sorted(source_paths))
        recipe_hash = _hash(
            {
                "kind": kind,
                "runner_id": runner_id,
                "version": definition.version,
                "dockerfile_path": dockerfile_path,
                "base_image_references": references,
                "sources": _source_identities(sources, ordered_paths),
            }
        )
        recipes.append(
            BootstrapRunnerRecipe(
                kind=kind,
                runner_id=runner_id,
                version=definition.version,
                dockerfile_path=dockerfile_path,
                base_image_references=references,
                source_paths=ordered_paths,
                recipe_content_hash=recipe_hash,
            )
        )
    return WebRunnerBootstrapInputs(
        sources=tuple(sources.items()),
        runners=tuple(recipes),
        content_hash=_hash(
            {
                "sources": _source_identities(sources, tuple(paths)),
                "runner_recipe_hashes": [recipe.recipe_content_hash for recipe in recipes],
            }
        ),
    )


def _validate_dockerfile(content: bytes, expected_references: tuple[str, ...]) -> None:
    try:
        text = content.decode("utf-8")
    except UnicodeError:
        raise ValueError("BOOTSTRAP_DOCKERFILE_ENCODING_INVALID") from None
    observed: set[str] = set()
    final_user = None
    for line in text.splitlines():
        normalized = line.strip()
        if not normalized or normalized.startswith("#"):
            continue
        instruction = normalized.split(maxsplit=1)[0].upper()
        if instruction == "FROM":
            match = _FROM.fullmatch(normalized)
            if match is None or not re.fullmatch(r"[0-9a-f]{64}", match.group(1).rsplit(":", 1)[1]):
                raise ValueError("BOOTSTRAP_DOCKERFILE_BASE_NOT_PINNED")
            observed.add(match.group(1))
            final_user = None
        elif instruction == "USER":
            parts = normalized.split(maxsplit=1)
            final_user = parts[1] if len(parts) == 2 else ""
    if observed != set(expected_references):
        raise ValueError("BOOTSTRAP_DOCKERFILE_BASE_LOCK_MISMATCH")
    if final_user is None or _USER.fullmatch(final_user) is None:
        raise ValueError("BOOTSTRAP_DOCKERFILE_NONROOT_USER_REQUIRED")
    user = final_user.split(":", 1)[0]
    if user.casefold() == "root" or not user.strip("0"):
        raise ValueError("BOOTSTRAP_DOCKERFILE_NONROOT_USER_REQUIRED")


def _validate_browser_packages(sources: dict[str, bytes]) -> None:
    package = _json(sources[f"{_BROWSER_ROOT}/package.json"])
    lock = _json(sources[f"{_BROWSER_ROOT}/package-lock.json"])
    if not isinstance(package, dict) or not isinstance(lock, dict):
        raise ValueError("BOOTSTRAP_BROWSER_PACKAGE_INVALID")
    packages = lock.get("packages")
    root = packages.get("") if isinstance(packages, dict) else None
    if not isinstance(root, dict):
        raise ValueError("BOOTSTRAP_BROWSER_PACKAGE_INVALID")
    if any(
        not isinstance(package.get(key), str)
        or not package[key]
        or root.get(key) != package[key]
        or lock.get(key) != package[key]
        for key in ("name", "version")
    ):
        raise ValueError("BOOTSTRAP_BROWSER_PACKAGE_ROOT_MISMATCH")
    if package.get("dependencies") != root.get("dependencies") or any(
        key in package or key in root
        for key in ("devDependencies", "optionalDependencies", "peerDependencies", "workspaces")
    ):
        raise ValueError("BOOTSTRAP_BROWSER_PACKAGE_DEPENDENCIES_MISMATCH")
    try:
        validate_lock(lock)
    except AutomationError as error:
        raise ValueError("BOOTSTRAP_BROWSER_DEPENDENCY_LOCK_INVALID") from error


def _safe_path(path: Path) -> None:
    if ".." in path.parts:
        raise ValueError("BOOTSTRAP_INPUT_PATH_NOT_CANONICAL")
    try:
        for item in (path, *path.parents):
            if item.is_symlink() or item.is_junction():
                raise ValueError("BOOTSTRAP_INPUT_PATH_REDIRECTED")
    except OSError as error:
        raise ValueError("BOOTSTRAP_INPUT_PATH_UNREADABLE") from error


def _read(path: Path) -> bytes:
    _safe_path(path)
    try:
        if not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
            raise ValueError("BOOTSTRAP_INPUT_MISSING_OR_TOO_LARGE")
        with path.open("rb") as source:
            content = source.read(_MAX_FILE_BYTES + 1)
    except OSError as error:
        raise ValueError("BOOTSTRAP_INPUT_UNREADABLE") from error
    if len(content) > _MAX_FILE_BYTES:
        raise ValueError("BOOTSTRAP_INPUT_TOO_LARGE")
    return content


def _json(content: bytes) -> object:
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("BOOTSTRAP_JSON_DUPLICATE_KEY")
            result[key] = value
        return result

    def reject_constant(_constant):
        raise ValueError("BOOTSTRAP_JSON_NONFINITE_NUMBER")

    try:
        return json.loads(content, object_pairs_hook=object_pairs, parse_constant=reject_constant)
    except (UnicodeError, ValueError):
        raise ValueError("BOOTSTRAP_JSON_INVALID") from None


def _source_identities(
    sources: dict[str, bytes], paths: tuple[str, ...]
) -> list[dict[str, object]]:
    return [
        {
            "path": path,
            "sha256": hashlib.sha256(sources[path]).hexdigest(),
            "size_bytes": len(sources[path]),
        }
        for path in paths
    ]


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()
