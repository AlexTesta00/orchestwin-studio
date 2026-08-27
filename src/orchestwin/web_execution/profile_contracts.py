"""Shared contracts and pure validation helpers for Sprint 08 Web profiles."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final, Protocol, runtime_checkable

from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionTarget,
)
from orchestwin.web_execution.browser_evidence import (
    WebBrowserEvidenceRequest,
    WebBrowserRouteSpec,
    create_web_browser_evidence_request,
)
from orchestwin.web_execution.detection import (
    WebDetectionSnapshot,
    WebDetectionStatus,
    detect_web_project,
)
from orchestwin.web_execution.lockfiles import WebDependencyLockReport
from orchestwin.web_execution.plans import (
    WebExecutionPlanBundle,
    create_structured_web_phase_plans,
)
from orchestwin.web_execution.runtime_evidence import WebHealthCheckSpec
from orchestwin.web_execution.targets import (
    WebTargetSelection,
    WebValidationScope,
    web_scope_for,
)

_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")


class WebProfileValidationStatus(StrEnum):
    """Structural readiness without implying public Level D validation."""

    READY_FOR_VALIDATION = "READY_FOR_VALIDATION"
    INVALID = "INVALID"


class WebProfileIssueCode(StrEnum):
    """Stable structural reasons a Web profile cannot plan a validation run."""

    INVENTORY_MISMATCH = "INVENTORY_MISMATCH"
    SELECTION_MISMATCH = "SELECTION_MISMATCH"
    DETECTION_NOT_SELECTED = "DETECTION_NOT_SELECTED"
    DETECTED_TARGET_MISMATCH = "DETECTED_TARGET_MISMATCH"
    DEPENDENCY_LOCKS_INVALID = "DEPENDENCY_LOCKS_INVALID"
    REQUIRED_PATH_MISSING = "REQUIRED_PATH_MISSING"
    REQUIRED_DEPENDENCY_MISSING = "REQUIRED_DEPENDENCY_MISSING"
    REQUIRED_SCRIPT_MISSING = "REQUIRED_SCRIPT_MISSING"
    FORBIDDEN_DEPENDENCY = "FORBIDDEN_DEPENDENCY"
    ENTRYPOINT_MISSING = "ENTRYPOINT_MISSING"
    LANGUAGE_MISMATCH = "LANGUAGE_MISMATCH"
    CONTENT_UNAVAILABLE = "CONTENT_UNAVAILABLE"
    INVALID_MANIFEST = "INVALID_MANIFEST"
    UNSUPPORTED_PROJECT = "UNSUPPORTED_PROJECT"


@dataclass(frozen=True, slots=True, order=True)
class WebProfileIssue:
    """One inspectable profile issue tied to an optional project path."""

    code: WebProfileIssueCode
    path: str | None
    message: str

    def __post_init__(self) -> None:
        if self.path is not None:
            _validate_relative_path(self.path)
        _validate_normalized_text(self.message, label="Web profile issue message")

    def to_snapshot(self) -> dict[str, str | None]:
        return {
            "code": self.code.value,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class WebProfileValidation:
    """Structural decision bound to profile, inventory, selection, and lock inputs."""

    target: ExecutionTarget
    profile_id: str
    profile_version: str
    validation_scope_hash: str
    capability_status: ExecutionCapabilityStatus
    inventory_content_hash: str
    selection: WebTargetSelection
    lock_report_content_hash: str
    status: WebProfileValidationStatus
    issues: tuple[WebProfileIssue, ...]

    def __post_init__(self) -> None:
        scope = web_scope_for(self.target)
        if self.status is WebProfileValidationStatus.READY_FOR_VALIDATION:
            self.selection.validate_against(scope)
        if self.profile_id != scope.profile_id or self.profile_version != scope.profile_version:
            raise ValueError("Web profile validation identity does not match its scope")
        if self.validation_scope_hash != scope.content_hash:
            raise ValueError("Web profile validation scope hash is stale")
        if self.capability_status is not scope.capability_status:
            raise ValueError("Web profile validation capability status is inconsistent")
        _validate_sha256(
            self.inventory_content_hash,
            label="Web profile inventory hash",
        )
        _validate_sha256(
            self.lock_report_content_hash,
            label="Web profile lock report hash",
        )
        ordered = tuple(
            sorted(
                self.issues,
                key=lambda issue: (issue.code.value, issue.path or "", issue.message),
            )
        )
        if self.issues != ordered or len(self.issues) != len(set(self.issues)):
            raise ValueError("Web profile issues must be canonical and unique")
        if self.status is WebProfileValidationStatus.READY_FOR_VALIDATION:
            if self.issues:
                raise ValueError("ready Web profile validation must be issue-free")
        elif not self.issues:
            raise ValueError("invalid Web profile validation requires issues")

    @property
    def is_ready(self) -> bool:
        """Return structural readiness, not a public Level D capability claim."""
        return self.status is WebProfileValidationStatus.READY_FOR_VALIDATION

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self._content_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {**self._content_snapshot(), "content_hash": self.content_hash}

    def _content_snapshot(self) -> dict[str, object]:
        return {
            "target": self.target.value,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "validation_scope_hash": self.validation_scope_hash,
            "capability_status": self.capability_status.value,
            "inventory_content_hash": self.inventory_content_hash,
            "selection": self.selection.to_snapshot(),
            "lock_report_content_hash": self.lock_report_content_hash,
            "status": self.status.value,
            "issues": [issue.to_snapshot() for issue in self.issues],
        }


@dataclass(frozen=True, slots=True)
class WebProfileRunnerSet:
    """Exact built runner digests required by one profile contract."""

    execution_runner_image_digest: str
    browser_runner_image_digest: str | None

    def __post_init__(self) -> None:
        _validate_sha256(
            self.execution_runner_image_digest,
            label="Web execution runner image digest",
        )
        if self.browser_runner_image_digest is not None:
            _validate_sha256(
                self.browser_runner_image_digest,
                label="Web browser runner image digest",
            )

    def to_snapshot(self) -> dict[str, str | None]:
        return {
            "execution_runner_image_digest": self.execution_runner_image_digest,
            "browser_runner_image_digest": self.browser_runner_image_digest,
        }


@dataclass(frozen=True, slots=True)
class WebProfileContract:
    """Complete profile plan for an exact source revision and runner set."""

    validation: WebProfileValidation
    source_revision_content_hash: str
    source_tree_hash: str
    runners: WebProfileRunnerSet
    execution_plan: WebExecutionPlanBundle
    health_checks: tuple[WebHealthCheckSpec, ...]
    browser_evidence_request: WebBrowserEvidenceRequest | None

    def __post_init__(self) -> None:
        if not self.validation.is_ready:
            raise ValueError("Web profile contract requires a ready validation")
        for value, label in (
            (self.source_revision_content_hash, "Web profile source revision hash"),
            (self.source_tree_hash, "Web profile source tree hash"),
        ):
            _validate_sha256(value, label=label)
        if self.execution_plan.inventory_content_hash != (self.validation.inventory_content_hash):
            raise ValueError("Web profile plan targets another source inventory")
        if self.execution_plan.selection != self.validation.selection:
            raise ValueError("Web profile plan selection differs from validation")
        if (
            self.execution_plan.profile_id != self.validation.profile_id
            or self.execution_plan.profile_version != self.validation.profile_version
        ):
            raise ValueError("Web profile plan identity differs from validation")
        check_ids = tuple(check.check_id for check in self.health_checks)
        if self.health_checks != tuple(
            sorted(self.health_checks, key=lambda check: check.check_id)
        ) or len(check_ids) != len(set(check_ids)):
            raise ValueError("Web profile health checks must be canonical and unique")
        scope = web_scope_for(self.validation.selection.target)
        if scope.requires_browser_evidence:
            request = self.browser_evidence_request
            if request is None or self.runners.browser_runner_image_digest is None:
                raise ValueError("user-interface Web profile requires a browser runner")
            if (
                request.source_revision_content_hash != self.source_revision_content_hash
                or request.source_tree_hash != self.source_tree_hash
                or request.runner_image_digest != self.runners.browser_runner_image_digest
            ):
                raise ValueError("browser request is not bound to the profile contract")
        elif self.browser_evidence_request is not None:
            raise ValueError("API-only Web profile must not create browser evidence")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self._content_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {**self._content_snapshot(), "content_hash": self.content_hash}

    def _content_snapshot(self) -> dict[str, object]:
        return {
            "validation": self.validation.to_snapshot(),
            "source_revision_content_hash": self.source_revision_content_hash,
            "source_tree_hash": self.source_tree_hash,
            "runners": self.runners.to_snapshot(),
            "execution_plan": self.execution_plan.to_snapshot(),
            "health_checks": [check.to_snapshot() for check in self.health_checks],
            "browser_evidence_request": (
                None
                if self.browser_evidence_request is None
                else self.browser_evidence_request.to_snapshot()
            ),
        }


@runtime_checkable
class WebExecutionProfile(Protocol):
    """Rich Web profile contract used by generation and governed execution."""

    @property
    def scope(self) -> WebValidationScope: ...

    def validate(
        self,
        snapshot: WebDetectionSnapshot,
        *,
        selection: WebTargetSelection,
        lock_report: WebDependencyLockReport,
    ) -> WebProfileValidation: ...

    def create_contract(
        self,
        snapshot: WebDetectionSnapshot,
        *,
        selection: WebTargetSelection,
        lock_report: WebDependencyLockReport,
        source_revision_content_hash: str,
        source_tree_hash: str,
        runners: WebProfileRunnerSet,
        declared_routes: tuple[WebBrowserRouteSpec, ...] = (),
    ) -> WebProfileContract: ...


def common_profile_issues(
    snapshot: WebDetectionSnapshot,
    *,
    selection: WebTargetSelection,
    lock_report: WebDependencyLockReport,
    expected_target: ExecutionTarget,
) -> list[WebProfileIssue]:
    """Validate exact inventory, selection, detection, and dependency inputs."""
    issues: list[WebProfileIssue] = []
    if lock_report.inventory_content_hash != snapshot.inventory_content_hash:
        issues.append(
            WebProfileIssue(
                code=WebProfileIssueCode.INVENTORY_MISMATCH,
                path=None,
                message="Dependency lock report targets another source inventory.",
            )
        )
    scope = web_scope_for(expected_target)
    try:
        selection.validate_against(scope)
    except ValueError:
        issues.append(
            WebProfileIssue(
                code=WebProfileIssueCode.SELECTION_MISMATCH,
                path=None,
                message="Selected target, language, or layout is outside this profile.",
            )
        )
    detection = detect_web_project(snapshot)
    if detection.status is not WebDetectionStatus.SELECTED or detection.selected is None:
        issues.append(
            WebProfileIssue(
                code=WebProfileIssueCode.DETECTION_NOT_SELECTED,
                path=None,
                message="Deterministic stack detection did not select one unambiguous target.",
            )
        )
    elif detection.selected.selection != selection:
        issues.append(
            WebProfileIssue(
                code=WebProfileIssueCode.DETECTED_TARGET_MISMATCH,
                path=None,
                message="Selected Web profile differs from deterministic stack detection.",
            )
        )
    if not lock_report.is_valid:
        issues.append(
            WebProfileIssue(
                code=WebProfileIssueCode.DEPENDENCY_LOCKS_INVALID,
                path=None,
                message="Deterministic dependency lock validation failed.",
            )
        )
    return issues


def create_profile_validation(
    *,
    snapshot: WebDetectionSnapshot,
    selection: WebTargetSelection,
    lock_report: WebDependencyLockReport,
    scope: WebValidationScope,
    issues: Iterable[WebProfileIssue],
) -> WebProfileValidation:
    """Canonicalize one profile-specific structural validation result."""
    canonical_issues = tuple(
        sorted(
            set(issues),
            key=lambda issue: (issue.code.value, issue.path or "", issue.message),
        )
    )
    return WebProfileValidation(
        target=scope.target,
        profile_id=scope.profile_id,
        profile_version=scope.profile_version,
        validation_scope_hash=scope.content_hash,
        capability_status=scope.capability_status,
        inventory_content_hash=snapshot.inventory_content_hash,
        selection=selection,
        lock_report_content_hash=lock_report.content_hash,
        status=(
            WebProfileValidationStatus.INVALID
            if canonical_issues
            else WebProfileValidationStatus.READY_FOR_VALIDATION
        ),
        issues=canonical_issues,
    )


def create_profile_contract(
    *,
    validation: WebProfileValidation,
    snapshot: WebDetectionSnapshot,
    lock_report: WebDependencyLockReport,
    source_revision_content_hash: str,
    source_tree_hash: str,
    runners: WebProfileRunnerSet,
    health_checks: Iterable[WebHealthCheckSpec],
    browser_base_url: str | None,
    declared_routes: tuple[WebBrowserRouteSpec, ...],
) -> WebProfileContract:
    """Create one exact plan only for a structurally ready profile."""
    if not validation.is_ready:
        raise ValueError("invalid Web profile cannot create an execution contract")
    execution_plan = create_structured_web_phase_plans(
        snapshot,
        selection=validation.selection,
        lock_report=lock_report,
    )
    browser_request: WebBrowserEvidenceRequest | None = None
    if browser_base_url is not None:
        if runners.browser_runner_image_digest is None:
            raise ValueError("browser evidence requires a pinned browser runner digest")
        browser_request = create_web_browser_evidence_request(
            source_revision_content_hash=source_revision_content_hash,
            source_tree_hash=source_tree_hash,
            runner_image_digest=runners.browser_runner_image_digest,
            base_url=browser_base_url,
            declared_routes=declared_routes,
        )
    return WebProfileContract(
        validation=validation,
        source_revision_content_hash=source_revision_content_hash,
        source_tree_hash=source_tree_hash,
        runners=runners,
        execution_plan=execution_plan,
        health_checks=tuple(sorted(health_checks, key=lambda check: check.check_id)),
        browser_evidence_request=browser_request,
    )


def require_paths(
    snapshot: WebDetectionSnapshot,
    *paths: str,
) -> tuple[WebProfileIssue, ...]:
    """Return one issue for every exact required path absent from the snapshot."""
    available = frozenset(snapshot.included_paths)
    return tuple(
        WebProfileIssue(
            code=WebProfileIssueCode.REQUIRED_PATH_MISSING,
            path=path,
            message="A required Web profile path is missing.",
        )
        for path in paths
        if path not in available
    )


def require_any_path(
    snapshot: WebDetectionSnapshot,
    *,
    candidates: tuple[str, ...],
    code: WebProfileIssueCode = WebProfileIssueCode.ENTRYPOINT_MISSING,
    message: str = "No supported Web profile entrypoint was found.",
) -> tuple[WebProfileIssue, ...]:
    """Require at least one exact path from an explicitly bounded candidate set."""
    if any(path in snapshot.included_paths for path in candidates):
        return ()
    return (WebProfileIssue(code=code, path=None, message=message),)


def paths_with_suffix(
    snapshot: WebDetectionSnapshot,
    *,
    root: str,
    suffix: str,
) -> tuple[str, ...]:
    """Return canonical included files below one root with an exact suffix."""
    prefix = "" if root == "." else f"{root}/"
    return tuple(
        path
        for path in snapshot.included_paths
        if path.startswith(prefix) and PurePosixPath(path).suffix.casefold() == suffix
    )


def json_object(
    snapshot: WebDetectionSnapshot,
    path: str,
) -> tuple[Mapping[str, object] | None, WebProfileIssue | None]:
    """Parse one required UTF-8 JSON object without accepting absent content."""
    content = snapshot.text_by_path().get(path)
    if content is None:
        return None, WebProfileIssue(
            code=WebProfileIssueCode.CONTENT_UNAVAILABLE,
            path=path,
            message="Web profile validation requires the UTF-8 manifest content.",
        )
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None, WebProfileIssue(
            code=WebProfileIssueCode.INVALID_MANIFEST,
            path=path,
            message="Web profile manifest must contain valid JSON.",
        )
    if not isinstance(payload, dict):
        return None, WebProfileIssue(
            code=WebProfileIssueCode.INVALID_MANIFEST,
            path=path,
            message="Web profile manifest must contain a JSON object.",
        )
    return payload, None


def dependency_names(manifest: Mapping[str, object]) -> frozenset[str]:
    """Return declared production and development package names."""
    names: set[str] = set()
    for field in ("dependencies", "devDependencies"):
        values = manifest.get(field)
        if isinstance(values, dict):
            names.update(key.casefold() for key in values if isinstance(key, str))
    return frozenset(names)


def dependency_issues(
    *,
    manifest: Mapping[str, object],
    path: str,
    required: frozenset[str],
    forbidden: frozenset[str],
) -> tuple[WebProfileIssue, ...]:
    """Validate required and forbidden package declarations."""
    names = dependency_names(manifest)
    issues = [
        WebProfileIssue(
            code=WebProfileIssueCode.REQUIRED_DEPENDENCY_MISSING,
            path=path,
            message=f"Required dependency {name} is missing from the manifest.",
        )
        for name in sorted(required - names)
    ]
    issues.extend(
        WebProfileIssue(
            code=WebProfileIssueCode.FORBIDDEN_DEPENDENCY,
            path=path,
            message=f"Dependency {name} is outside this validated Web profile.",
        )
        for name in sorted(forbidden & names)
    )
    return tuple(issues)


def script_issues(
    *,
    manifest: Mapping[str, object],
    path: str,
    required: frozenset[str],
) -> tuple[WebProfileIssue, ...]:
    """Require every command-plan script to be declared explicitly."""
    scripts = manifest.get("scripts")
    available = (
        frozenset(key for key in scripts if isinstance(key, str))
        if isinstance(scripts, dict)
        else frozenset()
    )
    return tuple(
        WebProfileIssue(
            code=WebProfileIssueCode.REQUIRED_SCRIPT_MISSING,
            path=path,
            message=f"Required npm script {name} is missing from the manifest.",
        )
        for name in sorted(required - available)
    )


def _validate_relative_path(path: str) -> None:
    pure = PurePosixPath(path)
    if (
        not path
        or path != path.strip()
        or pure.is_absolute()
        or "\\" in path
        or pure.as_posix() != path
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError("Web profile path must be normalized and relative")


def _validate_sha256(value: str, *, label: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")


def _validate_normalized_text(value: str, *, label: str) -> None:
    if not value or value != " ".join(value.split()):
        raise ValueError(f"{label} must be normalized")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
