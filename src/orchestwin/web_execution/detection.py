"""Deterministic structural detection for the five Sprint 08 Web targets."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final

from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.sandbox.source_inventory import SourceTreeInventory
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebProjectLayout,
    WebTargetSelection,
    web_scope_for,
)

_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_PACKAGE_FILES: Final = ("package.json", "frontend/package.json", "backend/package.json")
_COMPOSER_FILES: Final = ("composer.json",)
_NON_NPM_LOCKFILES: Final = frozenset({"bun.lock", "bun.lockb", "pnpm-lock.yaml", "yarn.lock"})
_CONFLICTING_DEPENDENCIES: Final = {
    "@angular/core": "angular",
    "@nestjs/core": "nestjs",
    "fastify": "fastify",
    "koa": "koa",
    "next": "nextjs",
    "nuxt": "nuxt",
    "react": "react",
}
_CONFLICTING_COMPOSER_PACKAGES: Final = {
    "laravel/framework": "laravel",
    "symfony/framework-bundle": "symfony",
}


class WebDetectionStatus(StrEnum):
    """Capability-neutral result of deterministic source inspection."""

    SELECTED = "SELECTED"
    HUMAN_DECISION_REQUIRED = "HUMAN_DECISION_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class WebTextFile:
    """UTF-8 source content bound to the digest recorded by the source inventory."""

    normalized_path: str
    content: str
    sha256_digest: str

    def __post_init__(self) -> None:
        _validate_relative_path(self.normalized_path)
        if not _SHA256_PATTERN.fullmatch(self.sha256_digest):
            raise ValueError("Web text file digest must be lowercase SHA-256")
        actual_digest = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if actual_digest != self.sha256_digest:
            raise ValueError("Web text file content does not match its inventory digest")


@dataclass(frozen=True, slots=True)
class WebDetectionSnapshot:
    """Minimal inspectable source material required for stack detection."""

    inventory_content_hash: str
    included_paths: tuple[str, ...]
    text_files: tuple[WebTextFile, ...]

    def __post_init__(self) -> None:
        if not _SHA256_PATTERN.fullmatch(self.inventory_content_hash):
            raise ValueError("Web detection inventory hash must be lowercase SHA-256")
        _require_canonical_paths(self.included_paths)
        ordered_files = tuple(sorted(self.text_files, key=lambda item: item.normalized_path))
        if self.text_files != ordered_files:
            raise ValueError("Web detection text files must use canonical path order")
        file_paths = tuple(item.normalized_path for item in self.text_files)
        if len(file_paths) != len(set(file_paths)):
            raise ValueError("Web detection text file paths must be unique")
        if not set(file_paths) <= set(self.included_paths):
            raise ValueError("Web detection text files must belong to the source inventory")

    def text_by_path(self) -> Mapping[str, str]:
        """Return a fresh immutable-by-convention path-to-content projection."""
        return {item.normalized_path: item.content for item in self.text_files}


@dataclass(frozen=True, slots=True)
class WebDetectionCandidate:
    """One deterministic target candidate and its inspectable match score."""

    selection: WebTargetSelection
    match_score: int
    positive_indicators: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.match_score, bool) or not 1 <= self.match_score <= 100:
            raise ValueError("Web detection match score must be from one to 100")
        _require_canonical_text(self.positive_indicators, label="positive indicators")
        if not self.positive_indicators:
            raise ValueError("Web detection candidate requires positive indicators")
        self.selection.validate_against(web_scope_for(self.selection.target))

    def to_snapshot(self) -> dict[str, object]:
        return {
            "selection": self.selection.to_snapshot(),
            "match_score": self.match_score,
            "positive_indicators": list(self.positive_indicators),
        }


@dataclass(frozen=True, slots=True)
class WebDetectionResult:
    """Deterministic detection result without an unearned capability promotion."""

    inventory_content_hash: str
    status: WebDetectionStatus
    candidates: tuple[WebDetectionCandidate, ...]
    selected: WebDetectionCandidate | None
    conflicting_indicators: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _SHA256_PATTERN.fullmatch(self.inventory_content_hash):
            raise ValueError("Web detection result requires a valid inventory hash")
        ordered = tuple(
            sorted(
                self.candidates,
                key=lambda item: (-item.match_score, item.selection.target.value),
            )
        )
        if self.candidates != ordered:
            raise ValueError("Web detection candidates must use deterministic ranking order")
        if len({candidate.selection.target for candidate in self.candidates}) != len(
            self.candidates
        ):
            raise ValueError("Web detection candidates must have unique targets")
        _require_canonical_text(
            self.conflicting_indicators,
            label="conflicting indicators",
        )
        if self.status is WebDetectionStatus.SELECTED:
            if self.selected is None or self.selected not in self.candidates:
                raise ValueError("selected Web detection requires one ranked candidate")
            if self.conflicting_indicators:
                raise ValueError("selected Web detection must not hide conflicts")
        elif self.selected is not None:
            raise ValueError("non-selected Web detection must not expose a selected target")
        if self.status is WebDetectionStatus.UNSUPPORTED and self.candidates:
            raise ValueError("unsupported Web detection must not contain candidates")
        if self.status is WebDetectionStatus.HUMAN_DECISION_REQUIRED and not (
            self.conflicting_indicators or len(self.candidates) > 1
        ):
            raise ValueError("human decision requires conflicts or multiple candidates")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "inventory_content_hash": self.inventory_content_hash,
            "status": self.status.value,
            "candidates": [candidate.to_snapshot() for candidate in self.candidates],
            "selected": None if self.selected is None else self.selected.to_snapshot(),
            "conflicting_indicators": list(self.conflicting_indicators),
        }


def create_web_detection_snapshot(
    inventory: SourceTreeInventory,
    *,
    text_content_by_path: Mapping[str, str],
) -> WebDetectionSnapshot:
    """Bind caller-supplied UTF-8 content to the exact source inventory digests."""
    included = {
        entry.normalized_path: entry.sha256_digest
        for entry in inventory.included_entries
        if entry.sha256_digest is not None
    }
    text_files: list[WebTextFile] = []
    for path, content in sorted(text_content_by_path.items()):
        expected_digest = included.get(path)
        if expected_digest is None:
            raise ValueError("Web detection text content is absent from the source inventory")
        text_files.append(
            WebTextFile(
                normalized_path=path,
                content=content,
                sha256_digest=expected_digest,
            )
        )
    return WebDetectionSnapshot(
        inventory_content_hash=inventory.content_hash,
        included_paths=tuple(sorted(included)),
        text_files=tuple(text_files),
    )


def detect_web_project(snapshot: WebDetectionSnapshot) -> WebDetectionResult:
    """Detect one Web family from structural indicators and parsed manifests."""
    paths = frozenset(snapshot.included_paths)
    text_by_path = snapshot.text_by_path()
    conflicts = set(_detect_path_conflicts(paths))
    package_manifests, manifest_conflicts = _parse_package_manifests(text_by_path)
    conflicts.update(manifest_conflicts)
    composer_manifest, composer_conflicts = _parse_composer_manifest(text_by_path)
    conflicts.update(composer_conflicts)

    candidates: list[WebDetectionCandidate] = []
    composed = _composed_candidate(paths, text_by_path, package_manifests)
    if composed is not None:
        candidates.append(composed)
    root_package = package_manifests.get("package.json")
    if root_package is not None:
        vue = _vue_candidate(paths, text_by_path, root_package)
        express = _express_candidate(paths, text_by_path, root_package)
        if vue is not None:
            candidates.append(vue)
        if express is not None:
            candidates.append(express)
    php = _php_candidate(paths, composer_manifest)
    if php is not None:
        candidates.append(php)
    static = _static_candidate(paths, package_manifests, composer_manifest)
    if static is not None:
        candidates.append(static)

    ranked = tuple(
        sorted(
            _deduplicate_candidates(candidates),
            key=lambda item: (-item.match_score, item.selection.target.value),
        )
    )
    canonical_conflicts = tuple(sorted(conflicts))
    if canonical_conflicts or len(ranked) > 1:
        status = WebDetectionStatus.HUMAN_DECISION_REQUIRED
        selected = None
    elif ranked:
        status = WebDetectionStatus.SELECTED
        selected = ranked[0]
    else:
        status = WebDetectionStatus.UNSUPPORTED
        selected = None
    return WebDetectionResult(
        inventory_content_hash=snapshot.inventory_content_hash,
        status=status,
        candidates=ranked,
        selected=selected,
        conflicting_indicators=canonical_conflicts,
    )


def _composed_candidate(
    paths: frozenset[str],
    text_by_path: Mapping[str, str],
    packages: Mapping[str, Mapping[str, object]],
) -> WebDetectionCandidate | None:
    frontend = packages.get("frontend/package.json")
    backend = packages.get("backend/package.json")
    if frontend is None or backend is None:
        return None
    if not _has_dependency(frontend, "vue") or not _has_dependency(frontend, "vite"):
        return None
    if not _has_dependency(backend, "express"):
        return None
    frontend_language = _detect_language("frontend", paths, text_by_path, frontend)
    backend_language = _detect_language("backend", paths, text_by_path, backend)
    if frontend_language is None or backend_language is None:
        return None
    configuration = WebLanguageConfiguration(
        frontend=frontend_language,
        backend=backend_language,
    )
    scope = web_scope_for(ExecutionTarget.WEB_VUE_NODE)
    if not scope.supports(configuration):
        return None
    indicators = (
        "backend/package.json declares express",
        "frontend/package.json declares vite",
        "frontend/package.json declares vue",
    )
    return WebDetectionCandidate(
        selection=WebTargetSelection(
            target=ExecutionTarget.WEB_VUE_NODE,
            language_configuration=configuration,
            layout=WebProjectLayout.FRONTEND_BACKEND,
        ),
        match_score=100,
        positive_indicators=indicators,
    )


def _vue_candidate(
    paths: frozenset[str],
    text_by_path: Mapping[str, str],
    package: Mapping[str, object],
) -> WebDetectionCandidate | None:
    if not _has_dependency(package, "vue") or not _has_dependency(package, "vite"):
        return None
    if _has_dependency(package, "express"):
        return None
    language = _detect_language(".", paths, text_by_path, package)
    if language is None:
        return None
    configuration = WebLanguageConfiguration(frontend=language, backend=None)
    return WebDetectionCandidate(
        selection=WebTargetSelection(
            target=ExecutionTarget.WEB_VUE,
            language_configuration=configuration,
            layout=WebProjectLayout.SINGLE_ROOT,
        ),
        match_score=90,
        positive_indicators=(
            "package.json declares vite",
            "package.json declares vue",
        ),
    )


def _express_candidate(
    paths: frozenset[str],
    text_by_path: Mapping[str, str],
    package: Mapping[str, object],
) -> WebDetectionCandidate | None:
    if not _has_dependency(package, "express") or _has_dependency(package, "vue"):
        return None
    language = _detect_language(".", paths, text_by_path, package)
    if language is None:
        return None
    configuration = WebLanguageConfiguration(frontend=None, backend=language)
    return WebDetectionCandidate(
        selection=WebTargetSelection(
            target=ExecutionTarget.WEB_NODE_EXPRESS,
            language_configuration=configuration,
            layout=WebProjectLayout.SINGLE_ROOT,
        ),
        match_score=85,
        positive_indicators=("package.json declares express",),
    )


def _php_candidate(
    paths: frozenset[str],
    composer_manifest: Mapping[str, object] | None,
) -> WebDetectionCandidate | None:
    php_paths = tuple(path for path in paths if PurePosixPath(path).suffix.lower() == ".php")
    if not php_paths or not any(path.startswith("public/") for path in php_paths):
        return None
    indicators = ["public directory contains PHP source"]
    if composer_manifest is not None:
        indicators.append("composer.json is present")
    return WebDetectionCandidate(
        selection=WebTargetSelection(
            target=ExecutionTarget.WEB_PHP,
            language_configuration=WebLanguageConfiguration(
                frontend=None,
                backend=WebImplementationLanguage.PHP,
            ),
            layout=WebProjectLayout.SINGLE_ROOT,
        ),
        match_score=80,
        positive_indicators=tuple(sorted(indicators)),
    )


def _static_candidate(
    paths: frozenset[str],
    package_manifests: Mapping[str, Mapping[str, object]],
    composer_manifest: Mapping[str, object] | None,
) -> WebDetectionCandidate | None:
    if "index.html" not in paths or package_manifests or composer_manifest is not None:
        return None
    if any(PurePosixPath(path).suffix.lower() in {".php", ".ts", ".tsx", ".vue"} for path in paths):
        return None
    return WebDetectionCandidate(
        selection=WebTargetSelection(
            target=ExecutionTarget.WEB_STATIC,
            language_configuration=WebLanguageConfiguration(
                frontend=WebImplementationLanguage.STATIC_ASSETS,
                backend=None,
            ),
            layout=WebProjectLayout.SINGLE_ROOT,
        ),
        match_score=70,
        positive_indicators=("index.html is present without a framework manifest",),
    )


def _parse_package_manifests(
    text_by_path: Mapping[str, str],
) -> tuple[dict[str, Mapping[str, object]], set[str]]:
    manifests: dict[str, Mapping[str, object]] = {}
    conflicts: set[str] = set()
    for path in _PACKAGE_FILES:
        content = text_by_path.get(path)
        if content is None:
            continue
        payload = _json_object(content, label=path)
        manifests[path] = payload
        dependencies = _dependency_names(payload)
        for dependency, framework in _CONFLICTING_DEPENDENCIES.items():
            if dependency in dependencies:
                conflicts.add(f"{path} declares unsupported framework {framework}")
    return manifests, conflicts


def _parse_composer_manifest(
    text_by_path: Mapping[str, str],
) -> tuple[Mapping[str, object] | None, set[str]]:
    content = next(
        (text_by_path.get(path) for path in _COMPOSER_FILES if path in text_by_path),
        None,
    )
    if content is None:
        return None, set()
    payload = _json_object(content, label="composer.json")
    dependencies = _composer_dependency_names(payload)
    conflicts = {
        f"composer.json declares unsupported framework {framework}"
        for dependency, framework in _CONFLICTING_COMPOSER_PACKAGES.items()
        if dependency in dependencies
    }
    return payload, conflicts


def _detect_path_conflicts(paths: frozenset[str]) -> tuple[str, ...]:
    conflicts = {
        f"unsupported package-manager lockfile {path}"
        for path in paths
        if PurePosixPath(path).name in _NON_NPM_LOCKFILES
    }
    if "wp-config.php" in paths or any(path.startswith("wp-content/") for path in paths):
        conflicts.add("WordPress project indicators are outside the validated PHP scope")
    return tuple(sorted(conflicts))


def _detect_language(
    root: str,
    paths: frozenset[str],
    text_by_path: Mapping[str, str],
    package: Mapping[str, object],
) -> WebImplementationLanguage | None:
    prefix = "" if root == "." else f"{root}/"
    rooted_paths = tuple(path for path in paths if not prefix or path.startswith(prefix))
    has_typescript = (
        f"{prefix}tsconfig.json" in paths
        or "typescript" in _dependency_names(package)
        or any(PurePosixPath(path).suffix.lower() in {".ts", ".tsx"} for path in rooted_paths)
        or any(
            path.endswith(".vue") and 'lang="ts"' in text_by_path.get(path, "")
            for path in rooted_paths
        )
    )
    has_javascript = any(
        PurePosixPath(path).suffix.lower() in {".cjs", ".js", ".jsx", ".mjs"}
        for path in rooted_paths
    )
    if has_typescript:
        return WebImplementationLanguage.TYPESCRIPT
    if has_javascript or any(path.endswith(".vue") for path in rooted_paths):
        return WebImplementationLanguage.JAVASCRIPT
    return None


def _dependency_names(package: Mapping[str, object]) -> frozenset[str]:
    names: set[str] = set()
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        value = package.get(section)
        if isinstance(value, dict):
            names.update(str(key) for key in value)
    return frozenset(names)


def _composer_dependency_names(package: Mapping[str, object]) -> frozenset[str]:
    names: set[str] = set()
    for section in ("require", "require-dev"):
        value = package.get(section)
        if isinstance(value, dict):
            names.update(str(key) for key in value)
    return frozenset(names)


def _has_dependency(package: Mapping[str, object], name: str) -> bool:
    return name in _dependency_names(package)


def _json_object(content: str, *, label: str) -> Mapping[str, object]:
    try:
        value = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} must contain valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _deduplicate_candidates(
    candidates: list[WebDetectionCandidate],
) -> tuple[WebDetectionCandidate, ...]:
    by_target: dict[ExecutionTarget, WebDetectionCandidate] = {}
    for candidate in candidates:
        existing = by_target.get(candidate.selection.target)
        if existing is None or candidate.match_score > existing.match_score:
            by_target[candidate.selection.target] = candidate
    return tuple(by_target.values())


def _validate_relative_path(path: str) -> None:
    if (
        not path
        or path != path.strip()
        or "\\" in path
        or path.startswith("/")
        or PurePosixPath(path).is_absolute()
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise ValueError("Web source path must be a normalized relative POSIX path")


def _require_canonical_paths(paths: tuple[str, ...]) -> None:
    if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
        raise ValueError("Web detection paths must be canonical and unique")
    for path in paths:
        _validate_relative_path(path)


def _require_canonical_text(values: tuple[str, ...], *, label: str) -> None:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"Web detection {label} must be canonical and unique")
    if any(not value or value != " ".join(value.split()) for value in values):
        raise ValueError(f"Web detection {label} must contain normalized values")
