"""Capture repository-owned executable fixtures without installing or executing them."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from orchestwin.api.web_execution import WebBrowserRouteCommand
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.browser_automation import _json, _read, _safe_path
from orchestwin.web_execution.detection import WebDetectionSnapshot, WebTextFile
from orchestwin.web_execution.lockfiles import validate_web_dependency_locks
from orchestwin.web_execution.phase_browser_evidence import WebBrowserInteraction
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.profile_registry import create_sprint08_web_profile_registry
from orchestwin.web_execution.static_browser_jobs import (
    BrowserAction,
    content_hash,
)
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebProjectLayout,
    WebTargetSelection,
)

FIXTURE_ROOT = "src/test/fixtures/web_level_d"
FIXTURE_IDS = (
    "static",
    "vue-js",
    "vue-ts",
    "express-js",
    "express-ts",
    "php",
    "vue-node-js",
    "vue-node-ts",
)
_GENERATED = {"node_modules", "vendor", "dist", ".git", ".vite", "coverage"}
_MEDIA = {
    ".html": "text/html",
    ".css": "text/css",
    ".json": "application/json",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".svg": "image/svg+xml",
}


@dataclass(frozen=True, slots=True)
class FixtureFile:
    path: str
    content: bytes
    media_type: str

    def to_snapshot(self):
        return {
            "normalized_path": self.path,
            "sha256_digest": hashlib.sha256(self.content).hexdigest(),
            "size_bytes": len(self.content),
        }


@dataclass(frozen=True, slots=True)
class RepositoryValidationFixture:
    fixture_id: str
    profile_id: str
    profile_version: str
    selection: WebTargetSelection
    files: tuple[FixtureFile, ...]
    failure_path: str
    failure_content: bytes
    expected_failure_phase: WebExecutionPhase
    expected_failure_marker: str
    browser_routes: tuple[WebBrowserRouteCommand, ...]
    browser_interactions: tuple[WebBrowserInteraction, ...]
    fixture_bundle_hash: str

    def source_files(self, *, defective=False):
        return tuple(
            replace(item, content=self.failure_content)
            if defective and item.path == self.failure_path
            else item
            for item in self.files
        )

    def source_tree_hash(self, *, defective=False):
        return content_hash(
            {"files": [item.to_snapshot() for item in self.source_files(defective=defective)]}
        )

    @property
    def repair_content(self):
        return next(item.content for item in self.files if item.path == self.failure_path)


def load_repository_validation_fixtures(repo_root: Path):
    """Require the complete exact version/configuration matrix and real lock contents."""
    root = Path(repo_root) / FIXTURE_ROOT
    matrix = _json(_read(root / "matrix.json"))
    if (
        not isinstance(matrix, dict)
        or set(matrix) != {"schema_version", "fixtures"}
        or matrix["schema_version"] != 1
    ):
        raise ValueError("WEB_VALIDATION_MATRIX_INVALID")
    rows = matrix["fixtures"]
    if not isinstance(rows, list) or len(rows) != len(FIXTURE_IDS):
        raise ValueError("WEB_VALIDATION_MATRIX_INCOMPLETE")
    registry = create_sprint08_web_profile_registry()
    fixtures = []
    coverage = set()
    for row in rows:
        fixture_id = row["id"]
        if fixture_id not in FIXTURE_IDS or row["source_dir"] != fixture_id:
            raise ValueError("WEB_VALIDATION_FIXTURE_PATH_INVALID")
        source_root = root / fixture_id
        _safe_path(source_root)
        files = []
        for path in sorted(source_root.rglob("*")):
            relative = path.relative_to(source_root)
            if any(part in _GENERATED for part in relative.parts):
                continue
            _safe_path(path)
            if path.is_file():
                data = _read(path, limit=1024 * 1024)
                data.decode("utf-8")
                files.append(
                    FixtureFile(relative.as_posix(), data, _MEDIA.get(path.suffix, "text/plain"))
                )
        if (
            not files
            or len(files) > 1000
            or sum(len(item.content) for item in files) > 20 * 1024 * 1024
        ):
            raise ValueError("WEB_VALIDATION_FIXTURE_BUDGET_INVALID")
        language = row["language_configuration"]
        selection = WebTargetSelection(
            ExecutionTarget(row["target"]),
            WebLanguageConfiguration(
                *(
                    None if language[side] is None else WebImplementationLanguage(language[side])
                    for side in ("frontend", "backend")
                )
            ),
            WebProjectLayout(row["layout"]),
        )
        profile = registry.find(row["profile_id"], row["profile_version"])
        if profile is None:
            raise ValueError("WEB_VALIDATION_PROFILE_UNKNOWN")
        selection.validate_against(profile.scope)
        key = (
            profile.scope.profile_id,
            profile.scope.profile_version,
            selection.language_configuration,
        )
        if key in coverage:
            raise ValueError("WEB_VALIDATION_CONFIGURATION_DUPLICATED")
        coverage.add(key)
        failure, repair = row["failure_change"], row["repair"]
        file_map = {item.path: item for item in files}
        if (
            failure["path"] != repair["path"]
            or failure["path"] not in file_map
            or repair["content"].encode("utf-8") != file_map[failure["path"]].content
            or failure["content"] == repair["content"]
            or row["expected_failure_marker"] != "LEVEL_D_NEGATIVE_CONTROL"
        ):
            raise ValueError("WEB_VALIDATION_REPAIR_MUST_RESTORE_FIXTURE")
        phase = WebExecutionPhase(row["expected_failure_phase"])
        expected = (
            WebExecutionPhase.BROWSER_EVIDENCE
            if selection.target is ExecutionTarget.WEB_STATIC
            else WebExecutionPhase.TEST
        )
        if phase is not expected:
            raise ValueError("WEB_VALIDATION_FAILURE_PHASE_INVALID")
        for item in files:
            if PurePosixPath(item.path).name == "package-lock.json":
                lock = _json(item.content)
                dependencies = [value for name, value in lock.get("packages", {}).items() if name]
                if not dependencies or any(not value.get("integrity") for value in dependencies):
                    raise ValueError("WEB_VALIDATION_NPM_LOCK_NOT_RESOLVED")
            if item.path == "composer.lock":
                lock = _json(item.content)
                if not lock.get("packages-dev") or len(lock.get("content-hash", "")) != 32:
                    raise ValueError("WEB_VALIDATION_COMPOSER_LOCK_NOT_RESOLVED")
        fixture = RepositoryValidationFixture(
            fixture_id,
            row["profile_id"],
            row["profile_version"],
            selection,
            tuple(files),
            failure["path"],
            failure["content"].encode("utf-8"),
            phase,
            row["expected_failure_marker"],
            tuple(WebBrowserRouteCommand(**route) for route in row["browser_routes"]),
            tuple(
                WebBrowserInteraction(
                    route_id=plan["route_id"],
                    actions=tuple(BrowserAction(**action) for action in plan["actions"]),
                )
                for plan in row["browser_interactions"]
            ),
            content_hash({"definition": row, "files": [item.to_snapshot() for item in files]}),
        )
        for defective in (False, True):
            source_files = fixture.source_files(defective=defective)
            snapshot = WebDetectionSnapshot(
                fixture.source_tree_hash(defective=defective),
                tuple(item.path for item in source_files),
                tuple(
                    WebTextFile(
                        item.path,
                        item.content.decode("utf-8"),
                        hashlib.sha256(item.content).hexdigest(),
                    )
                    for item in source_files
                ),
            )
            locks = validate_web_dependency_locks(snapshot, selection=selection)
            validation = profile.validate(snapshot, selection=selection, lock_report=locks)
            if not validation.is_ready:
                raise ValueError(
                    f"WEB_VALIDATION_FIXTURE_CONTRACT_INVALID:{fixture_id}:{validation.to_snapshot()}"
                )
        fixtures.append(fixture)
    expected_coverage = {
        (profile.scope.profile_id, profile.scope.profile_version, language)
        for profile in registry.profiles
        for language in profile.scope.language_configurations
    }
    if coverage != expected_coverage or {item.fixture_id for item in fixtures} != set(FIXTURE_IDS):
        raise ValueError("WEB_VALIDATION_MATRIX_INCOMPLETE")
    return tuple(sorted(fixtures, key=lambda item: item.fixture_id))
