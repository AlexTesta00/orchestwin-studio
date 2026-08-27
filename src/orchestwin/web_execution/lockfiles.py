"""Deterministic npm and Composer lockfile policies for validated Web scopes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.detection import WebDetectionSnapshot
from orchestwin.web_execution.targets import WebTargetSelection

_NPM_CONFLICTING_LOCKFILES = frozenset({"bun.lock", "bun.lockb", "pnpm-lock.yaml", "yarn.lock"})


class WebDependencyEcosystem(StrEnum):
    """Dependency systems admitted by the Sprint 08 baseline."""

    NONE = "NONE"
    NPM = "NPM"
    COMPOSER = "COMPOSER"


class WebLockfileValidationStatus(StrEnum):
    """Result of validating deterministic dependency inputs."""

    VALID = "VALID"
    INVALID = "INVALID"
    NOT_REQUIRED = "NOT_REQUIRED"


class WebLockfileIssueCode(StrEnum):
    """Stable reasons why deterministic setup cannot proceed."""

    MANIFEST_MISSING = "MANIFEST_MISSING"
    LOCKFILE_MISSING = "LOCKFILE_MISSING"
    CONTENT_UNAVAILABLE = "CONTENT_UNAVAILABLE"
    INVALID_JSON = "INVALID_JSON"
    UNSUPPORTED_LOCKFILE_VERSION = "UNSUPPORTED_LOCKFILE_VERSION"
    CONFLICTING_PACKAGE_MANAGER = "CONFLICTING_PACKAGE_MANAGER"
    COMPOSER_SCRIPTS_ENABLED = "COMPOSER_SCRIPTS_ENABLED"
    COMPOSER_PLUGINS_ENABLED = "COMPOSER_PLUGINS_ENABLED"
    LOCKFILE_SHAPE_INVALID = "LOCKFILE_SHAPE_INVALID"


@dataclass(frozen=True, slots=True)
class WebLockfileIssue:
    """One inspectable ecosystem-policy violation."""

    code: WebLockfileIssueCode
    message: str
    path: str | None

    def __post_init__(self) -> None:
        if not self.message or self.message != " ".join(self.message.split()):
            raise ValueError("Web lockfile issue message must be normalized")

    def to_snapshot(self) -> dict[str, str | None]:
        return {"code": self.code.value, "message": self.message, "path": self.path}


@dataclass(frozen=True, slots=True)
class WebDependencyRootReport:
    """Lockfile policy result for one project root."""

    root: str
    ecosystem: WebDependencyEcosystem
    status: WebLockfileValidationStatus
    manifest_path: str | None
    lockfile_path: str | None
    manifest_sha256: str | None
    lockfile_sha256: str | None
    issues: tuple[WebLockfileIssue, ...]

    def __post_init__(self) -> None:
        if self.status is WebLockfileValidationStatus.VALID:
            if self.issues or self.manifest_path is None or self.lockfile_path is None:
                raise ValueError("valid Web dependency report requires both deterministic inputs")
        elif self.status is WebLockfileValidationStatus.NOT_REQUIRED:
            if self.ecosystem is not WebDependencyEcosystem.NONE or self.issues:
                raise ValueError("not-required Web dependency report must be an empty NONE scope")
        elif not self.issues:
            raise ValueError("invalid Web dependency report requires issues")

    @property
    def content_hash(self) -> str:
        payload = {
            "root": self.root,
            "ecosystem": self.ecosystem.value,
            "status": self.status.value,
            "manifest_path": self.manifest_path,
            "lockfile_path": self.lockfile_path,
            "manifest_sha256": self.manifest_sha256,
            "lockfile_sha256": self.lockfile_sha256,
            "issues": [issue.to_snapshot() for issue in self.issues],
        }
        return hashlib.sha256(_canonical_json(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class WebDependencyLockReport:
    """Complete lockfile decision bound to one source inventory hash."""

    inventory_content_hash: str
    roots: tuple[WebDependencyRootReport, ...]

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.roots, key=lambda report: report.root))
        if self.roots != ordered or len({report.root for report in self.roots}) != len(self.roots):
            raise ValueError("Web dependency roots must be canonical and unique")
        if not self.roots:
            raise ValueError("Web dependency lock report requires at least one root")

    @property
    def is_valid(self) -> bool:
        return all(
            root.status
            in {WebLockfileValidationStatus.VALID, WebLockfileValidationStatus.NOT_REQUIRED}
            for root in self.roots
        )

    @property
    def content_hash(self) -> str:
        payload = {
            "inventory_content_hash": self.inventory_content_hash,
            "roots": [
                {
                    "root": root.root,
                    "ecosystem": root.ecosystem.value,
                    "status": root.status.value,
                    "content_hash": root.content_hash,
                }
                for root in self.roots
            ],
        }
        return hashlib.sha256(_canonical_json(payload)).hexdigest()


def validate_web_dependency_locks(
    snapshot: WebDetectionSnapshot,
    *,
    selection: WebTargetSelection,
) -> WebDependencyLockReport:
    """Validate the exact npm or Composer inputs required by one selected target."""
    if selection.target is ExecutionTarget.WEB_STATIC:
        reports = (
            WebDependencyRootReport(
                root=".",
                ecosystem=WebDependencyEcosystem.NONE,
                status=WebLockfileValidationStatus.NOT_REQUIRED,
                manifest_path=None,
                lockfile_path=None,
                manifest_sha256=None,
                lockfile_sha256=None,
                issues=(),
            ),
        )
    elif selection.target is ExecutionTarget.WEB_PHP:
        reports = (_validate_composer_root(snapshot, root="."),)
    elif selection.target is ExecutionTarget.WEB_VUE_NODE:
        reports = tuple(
            sorted(
                (
                    _validate_npm_root(snapshot, root="frontend"),
                    _validate_npm_root(snapshot, root="backend"),
                ),
                key=lambda report: report.root,
            )
        )
    else:
        reports = (_validate_npm_root(snapshot, root="."),)
    return WebDependencyLockReport(
        inventory_content_hash=snapshot.inventory_content_hash,
        roots=reports,
    )


def _validate_npm_root(
    snapshot: WebDetectionSnapshot,
    *,
    root: str,
) -> WebDependencyRootReport:
    prefix = "" if root == "." else f"{root}/"
    manifest_path = f"{prefix}package.json"
    lockfile_path = f"{prefix}package-lock.json"
    paths = frozenset(snapshot.included_paths)
    text_files = {item.normalized_path: item for item in snapshot.text_files}
    issues: list[WebLockfileIssue] = []

    if manifest_path not in paths:
        issues.append(
            WebLockfileIssue(
                WebLockfileIssueCode.MANIFEST_MISSING,
                "npm validation requires package.json.",
                manifest_path,
            )
        )
    if lockfile_path not in paths:
        issues.append(
            WebLockfileIssue(
                WebLockfileIssueCode.LOCKFILE_MISSING,
                "npm validation requires package-lock.json.",
                lockfile_path,
            )
        )
    for path in paths:
        if _belongs_to_root(path, root=root) and PurePosixPath(path).name in (
            _NPM_CONFLICTING_LOCKFILES
        ):
            issues.append(
                WebLockfileIssue(
                    WebLockfileIssueCode.CONFLICTING_PACKAGE_MANAGER,
                    "Only npm is inside the validated Web dependency scope.",
                    path,
                )
            )

    manifest_payload, manifest_issue = _json_file(text_files, manifest_path)
    if manifest_issue is not None and manifest_path in paths:
        issues.append(manifest_issue)
    lock_payload, lock_issue = _json_file(text_files, lockfile_path)
    if lock_issue is not None and lockfile_path in paths:
        issues.append(lock_issue)
    if lock_payload is not None:
        lock_version = lock_payload.get("lockfileVersion")
        if isinstance(lock_version, bool) or lock_version not in {2, 3}:
            issues.append(
                WebLockfileIssue(
                    WebLockfileIssueCode.UNSUPPORTED_LOCKFILE_VERSION,
                    "npm lockfileVersion must be 2 or 3.",
                    lockfile_path,
                )
            )
        if not isinstance(lock_payload.get("packages"), dict):
            issues.append(
                WebLockfileIssue(
                    WebLockfileIssueCode.LOCKFILE_SHAPE_INVALID,
                    "npm lockfile requires a packages object.",
                    lockfile_path,
                )
            )
    del manifest_payload
    return _root_report(
        root=root,
        ecosystem=WebDependencyEcosystem.NPM,
        manifest_path=manifest_path,
        lockfile_path=lockfile_path,
        text_files=text_files,
        issues=issues,
    )


def _validate_composer_root(
    snapshot: WebDetectionSnapshot,
    *,
    root: str,
) -> WebDependencyRootReport:
    prefix = "" if root == "." else f"{root}/"
    manifest_path = f"{prefix}composer.json"
    lockfile_path = f"{prefix}composer.lock"
    paths = frozenset(snapshot.included_paths)
    text_files = {item.normalized_path: item for item in snapshot.text_files}
    issues: list[WebLockfileIssue] = []

    if manifest_path not in paths:
        issues.append(
            WebLockfileIssue(
                WebLockfileIssueCode.MANIFEST_MISSING,
                "Composer validation requires composer.json.",
                manifest_path,
            )
        )
    if lockfile_path not in paths:
        issues.append(
            WebLockfileIssue(
                WebLockfileIssueCode.LOCKFILE_MISSING,
                "Composer validation requires composer.lock.",
                lockfile_path,
            )
        )
    manifest_payload, manifest_issue = _json_file(text_files, manifest_path)
    if manifest_issue is not None and manifest_path in paths:
        issues.append(manifest_issue)
    lock_payload, lock_issue = _json_file(text_files, lockfile_path)
    if lock_issue is not None and lockfile_path in paths:
        issues.append(lock_issue)

    if manifest_payload is not None:
        scripts = manifest_payload.get("scripts")
        if isinstance(scripts, dict) and scripts:
            issues.append(
                WebLockfileIssue(
                    WebLockfileIssueCode.COMPOSER_SCRIPTS_ENABLED,
                    "Composer scripts must be disabled in the validated baseline.",
                    manifest_path,
                )
            )
        config = manifest_payload.get("config")
        allow_plugins = config.get("allow-plugins") if isinstance(config, dict) else None
        plugins_disabled = allow_plugins is False or (
            isinstance(allow_plugins, dict)
            and all(value is False for value in allow_plugins.values())
        )
        if not plugins_disabled:
            issues.append(
                WebLockfileIssue(
                    WebLockfileIssueCode.COMPOSER_PLUGINS_ENABLED,
                    "Composer plugins must be explicitly disabled.",
                    manifest_path,
                )
            )
    if lock_payload is not None and not (
        isinstance(lock_payload.get("packages"), list)
        and isinstance(lock_payload.get("packages-dev"), list)
        and isinstance(lock_payload.get("content-hash"), str)
    ):
        issues.append(
            WebLockfileIssue(
                WebLockfileIssueCode.LOCKFILE_SHAPE_INVALID,
                "Composer lockfile requires package arrays and a content hash.",
                lockfile_path,
            )
        )

    return _root_report(
        root=root,
        ecosystem=WebDependencyEcosystem.COMPOSER,
        manifest_path=manifest_path,
        lockfile_path=lockfile_path,
        text_files=text_files,
        issues=issues,
    )


def _root_report(
    *,
    root: str,
    ecosystem: WebDependencyEcosystem,
    manifest_path: str,
    lockfile_path: str,
    text_files: Mapping[str, object],
    issues: list[WebLockfileIssue],
) -> WebDependencyRootReport:
    manifest_file = text_files.get(manifest_path)
    lockfile_file = text_files.get(lockfile_path)
    manifest_digest = getattr(manifest_file, "sha256_digest", None)
    lockfile_digest = getattr(lockfile_file, "sha256_digest", None)
    return WebDependencyRootReport(
        root=root,
        ecosystem=ecosystem,
        status=(
            WebLockfileValidationStatus.INVALID if issues else WebLockfileValidationStatus.VALID
        ),
        manifest_path=manifest_path,
        lockfile_path=lockfile_path,
        manifest_sha256=manifest_digest,
        lockfile_sha256=lockfile_digest,
        issues=tuple(issues),
    )


def _json_file(
    text_files: Mapping[str, object],
    path: str,
) -> tuple[Mapping[str, object] | None, WebLockfileIssue | None]:
    file = text_files.get(path)
    if file is None:
        return None, WebLockfileIssue(
            WebLockfileIssueCode.CONTENT_UNAVAILABLE,
            "Lockfile validation requires the UTF-8 file content.",
            path,
        )
    content = getattr(file, "content", None)
    if not isinstance(content, str):
        return None, WebLockfileIssue(
            WebLockfileIssueCode.CONTENT_UNAVAILABLE,
            "Lockfile validation requires the UTF-8 file content.",
            path,
        )
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None, WebLockfileIssue(
            WebLockfileIssueCode.INVALID_JSON,
            "Dependency manifest or lockfile must contain valid JSON.",
            path,
        )
    if not isinstance(payload, dict):
        return None, WebLockfileIssue(
            WebLockfileIssueCode.INVALID_JSON,
            "Dependency manifest or lockfile must contain a JSON object.",
            path,
        )
    return payload, None


def _belongs_to_root(path: str, *, root: str) -> bool:
    if root == ".":
        return "/" not in path
    return path.startswith(f"{root}/") and "/" not in path[len(root) + 1 :]


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
