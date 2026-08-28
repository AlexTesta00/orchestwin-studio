"""Capability-honest execution profile contracts for JVM source snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final, Protocol, runtime_checkable

from orchestwin.artifacts.jvm_sources import JvmSourceRevisionReference
from orchestwin.jvm_execution.detection import (
    JvmDetectionSnapshot,
    JvmDetectionStatus,
    detect_jvm_project,
)
from orchestwin.jvm_execution.plans import (
    JvmExecutionPlanBundle,
    create_jvm_execution_plan_bundle,
)
from orchestwin.jvm_execution.policy import (
    JvmToolchainDeclaration,
    JvmToolchainValidationStatus,
    policy_for,
    validate_toolchain,
)
from orchestwin.jvm_execution.runner_contracts import JvmContainerRunnerContract
from orchestwin.jvm_execution.targets import (
    JvmTargetSelection,
    JvmValidationScope,
    jvm_scope_for,
)
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionTarget,
)

_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")


class JvmProfileValidationStatus(StrEnum):
    """Outcome of binding source detection and toolchain policy to one profile."""

    READY_FOR_VALIDATION = "READY_FOR_VALIDATION"
    INVALID = "INVALID"


class JvmProfileIssueCode(StrEnum):
    """Stable reasons a source snapshot cannot use one JVM profile."""

    DETECTION_NOT_SELECTED = "DETECTION_NOT_SELECTED"
    TARGET_MISMATCH = "TARGET_MISMATCH"
    TOOLCHAIN_POLICY_FAILED = "TOOLCHAIN_POLICY_FAILED"
    SOURCE_LAYOUT_MISSING = "SOURCE_LAYOUT_MISSING"
    SOURCE_CONTENT_UNAVAILABLE = "SOURCE_CONTENT_UNAVAILABLE"
    ENTRYPOINT_MISSING = "ENTRYPOINT_MISSING"


@dataclass(frozen=True, slots=True, order=True)
class JvmProfileValidationIssue:
    """One deterministic profile issue tied to an inspectable subject."""

    code: JvmProfileIssueCode
    subject: str
    message: str

    def __post_init__(self) -> None:
        _validate_normalized_text(self.subject, label="JVM profile issue subject")
        _validate_normalized_text(self.message, label="JVM profile issue message")

    def to_snapshot(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "subject": self.subject,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class JvmProfileValidation:
    """Exact structural decision without an implicit Level D promotion."""

    target: ExecutionTarget
    profile_id: str
    profile_version: str
    validation_scope_hash: str
    capability_status: ExecutionCapabilityStatus
    validation_evidence_refs: tuple[str, ...]
    inventory_content_hash: str
    selection: JvmTargetSelection
    toolchain_policy_hash: str
    toolchain_validation_hash: str
    status: JvmProfileValidationStatus
    issues: tuple[JvmProfileValidationIssue, ...]

    def __post_init__(self) -> None:
        baseline = jvm_scope_for(self.target)
        if self.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D:
            scope = replace(
                baseline,
                capability_status=ExecutionCapabilityStatus.VALIDATED_LEVEL_D,
                validation_evidence_refs=self.validation_evidence_refs,
            )
        else:
            scope = baseline
            if self.validation_evidence_refs:
                raise ValueError("non-validated JVM profile must not claim evidence")
        self.selection.validate_against(baseline)
        if self.profile_id != scope.profile_id or self.profile_version != scope.profile_version:
            raise ValueError("JVM profile validation identity differs from its scope")
        if self.validation_scope_hash != scope.content_hash:
            raise ValueError("JVM profile validation scope hash is stale")
        if self.capability_status is not scope.capability_status:
            raise ValueError("JVM profile validation capability status is inconsistent")
        for value, label in (
            (self.inventory_content_hash, "JVM profile inventory hash"),
            (self.toolchain_policy_hash, "JVM profile policy hash"),
            (self.toolchain_validation_hash, "JVM profile toolchain validation hash"),
        ):
            _validate_sha256(value, label=label)
        _require_canonical_text(
            self.validation_evidence_refs,
            label="JVM profile validation evidence",
        )
        ordered = tuple(
            sorted(self.issues, key=lambda issue: (issue.code.value, issue.subject, issue.message))
        )
        if self.issues != ordered or len(self.issues) != len(set(self.issues)):
            raise ValueError("JVM profile issues must be canonical and unique")
        if self.status is JvmProfileValidationStatus.READY_FOR_VALIDATION:
            if self.issues:
                raise ValueError("ready JVM profile decision must be issue-free")
        elif not self.issues:
            raise ValueError("invalid JVM profile decision requires issues")

    @property
    def is_ready(self) -> bool:
        """Return structural readiness, not a public Level D capability claim."""
        return self.status is JvmProfileValidationStatus.READY_FOR_VALIDATION

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
            "validation_evidence_refs": list(self.validation_evidence_refs),
            "inventory_content_hash": self.inventory_content_hash,
            "selection": self.selection.to_snapshot(),
            "toolchain_policy_hash": self.toolchain_policy_hash,
            "toolchain_validation_hash": self.toolchain_validation_hash,
            "status": self.status.value,
            "issues": [issue.to_snapshot() for issue in self.issues],
        }


@dataclass(frozen=True, slots=True)
class JvmProfileContract:
    """Execution binding of source, runner, canonical plan, and profile validation."""

    validation: JvmProfileValidation
    source_revision: JvmSourceRevisionReference
    runner: JvmContainerRunnerContract
    execution_plan: JvmExecutionPlanBundle

    def __post_init__(self) -> None:
        if not self.validation.is_ready:
            raise ValueError("JVM profile contract requires a ready profile decision")
        if self.execution_plan.target_selection != self.validation.selection:
            raise ValueError("JVM profile contract plan targets another selection")
        if self.runner.build_system is not self.validation.selection.build_system:
            raise ValueError("JVM profile contract runner uses another build system")
        if self.runner.capability_status is not self.validation.capability_status:
            raise ValueError("JVM profile and runner capability status must agree")
        if self.runner.validation_evidence_refs != self.validation.validation_evidence_refs:
            raise ValueError("JVM profile and runner evidence references must agree")
        if any(
            phase.command_plan.profile_id != self.validation.profile_id
            or phase.command_plan.profile_version != self.validation.profile_version
            for phase in self.execution_plan.phases
        ):
            raise ValueError("JVM profile contract plan identity differs from validation")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self._content_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {**self._content_snapshot(), "content_hash": self.content_hash}

    def _content_snapshot(self) -> dict[str, object]:
        return {
            "validation": self.validation.to_snapshot(),
            "source_revision": self.source_revision.to_snapshot(),
            "runner": self.runner.to_safe_snapshot(),
            "execution_plan": self.execution_plan.to_snapshot(),
        }


@runtime_checkable
class JvmExecutionProfile(Protocol):
    """Public behavior shared by Java, Kotlin, Scala, and evidence-backed wrappers."""

    @property
    def scope(self) -> JvmValidationScope: ...

    @property
    def expected_runner_id(self) -> str: ...

    def validate(
        self,
        snapshot: JvmDetectionSnapshot,
        declaration: JvmToolchainDeclaration,
    ) -> JvmProfileValidation: ...

    def create_contract(
        self,
        snapshot: JvmDetectionSnapshot,
        declaration: JvmToolchainDeclaration,
        *,
        source_revision: JvmSourceRevisionReference,
        runner: JvmContainerRunnerContract,
    ) -> JvmProfileContract: ...


@dataclass(frozen=True, slots=True)
class BaseJvmExecutionProfile:
    """Deterministic implementation reused by the three fixed JVM profiles."""

    target: ExecutionTarget
    runner_id: str
    source_root: str
    source_suffix: str
    entrypoint_markers: tuple[str, ...]

    def __post_init__(self) -> None:
        scope = jvm_scope_for(self.target)
        if self.runner_id not in {"jvm.gradle", "jvm.sbt"}:
            raise ValueError("JVM profile runner identity is unsupported")
        if not self.source_root.endswith("/") or self.source_root.startswith("/"):
            raise ValueError("JVM profile source root must be relative and normalized")
        if not self.source_suffix.startswith("."):
            raise ValueError("JVM profile source suffix must begin with a dot")
        _require_canonical_text(self.entrypoint_markers, label="JVM entrypoint markers")
        if not self.entrypoint_markers:
            raise ValueError("JVM profile requires entrypoint markers")
        expected_runner = "jvm.sbt" if scope.build_system.value == "SBT" else "jvm.gradle"
        if self.runner_id != expected_runner:
            raise ValueError("JVM profile runner does not match the build system")

    @property
    def scope(self) -> JvmValidationScope:
        return jvm_scope_for(self.target)

    @property
    def expected_runner_id(self) -> str:
        return self.runner_id

    def validate(
        self,
        snapshot: JvmDetectionSnapshot,
        declaration: JvmToolchainDeclaration,
    ) -> JvmProfileValidation:
        issues: set[JvmProfileValidationIssue] = set()
        detection = detect_jvm_project(snapshot)
        if detection.status is not JvmDetectionStatus.SELECTED:
            detail = (
                "; ".join(detection.conflicting_indicators)
                if detection.conflicting_indicators
                else detection.status.value
            )
            issues.add(
                JvmProfileValidationIssue(
                    code=JvmProfileIssueCode.DETECTION_NOT_SELECTED,
                    subject="project-detection",
                    message=f"JVM project detection did not select this profile: {detail}",
                )
            )
        elif detection.selected is None or detection.selected.selection.target is not self.target:
            selected = (
                "none" if detection.selected is None else detection.selected.selection.target.value
            )
            issues.add(
                JvmProfileValidationIssue(
                    code=JvmProfileIssueCode.TARGET_MISMATCH,
                    subject="target",
                    message=f"Detected target {selected} does not match {self.target.value}.",
                )
            )

        policy = policy_for(self.target)
        toolchain = validate_toolchain(policy, declaration)
        if toolchain.status is JvmToolchainValidationStatus.INVALID:
            for issue in toolchain.issues:
                issues.add(
                    JvmProfileValidationIssue(
                        code=JvmProfileIssueCode.TOOLCHAIN_POLICY_FAILED,
                        subject=f"{issue.code.value}:{issue.subject}",
                        message=issue.message,
                    )
                )

        source_paths = tuple(
            path
            for path in snapshot.included_paths
            if path.startswith(self.source_root)
            and PurePosixPath(path).suffix.casefold() == self.source_suffix
        )
        if not source_paths:
            issues.add(
                JvmProfileValidationIssue(
                    code=JvmProfileIssueCode.SOURCE_LAYOUT_MISSING,
                    subject=self.source_root,
                    message="The validated single-module JVM source root is missing.",
                )
            )
        else:
            text_by_path = snapshot.text_by_path()
            unavailable = tuple(path for path in source_paths if path not in text_by_path)
            if unavailable:
                for path in unavailable:
                    issues.add(
                        JvmProfileValidationIssue(
                            code=JvmProfileIssueCode.SOURCE_CONTENT_UNAVAILABLE,
                            subject=path,
                            message="Entrypoint validation requires the UTF-8 source content.",
                        )
                    )
            elif not any(
                marker in text_by_path[path]
                for path in source_paths
                for marker in self.entrypoint_markers
            ):
                issues.add(
                    JvmProfileValidationIssue(
                        code=JvmProfileIssueCode.ENTRYPOINT_MISSING,
                        subject=self.source_root,
                        message="No deterministic application entrypoint was found.",
                    )
                )

        canonical = tuple(
            sorted(issues, key=lambda issue: (issue.code.value, issue.subject, issue.message))
        )
        return create_profile_validation(
            scope=self.scope,
            snapshot=snapshot,
            selection=policy.selection,
            policy_hash=policy.content_hash,
            toolchain_validation_hash=hashlib.sha256(
                _canonical_json(toolchain.to_snapshot())
            ).hexdigest(),
            issues=canonical,
        )

    def create_contract(
        self,
        snapshot: JvmDetectionSnapshot,
        declaration: JvmToolchainDeclaration,
        *,
        source_revision: JvmSourceRevisionReference,
        runner: JvmContainerRunnerContract,
    ) -> JvmProfileContract:
        validation = self.validate(snapshot, declaration)
        if not validation.is_ready:
            raise ValueError("JVM profile contract cannot be created from invalid input")
        if runner.runner_id != self.expected_runner_id:
            raise ValueError("JVM profile received an unexpected runner identity")
        return JvmProfileContract(
            validation=validation,
            source_revision=source_revision,
            runner=runner,
            execution_plan=create_jvm_execution_plan_bundle(validation.selection),
        )


def create_profile_validation(
    *,
    scope: JvmValidationScope,
    snapshot: JvmDetectionSnapshot,
    selection: JvmTargetSelection,
    policy_hash: str,
    toolchain_validation_hash: str,
    issues: Iterable[JvmProfileValidationIssue],
) -> JvmProfileValidation:
    """Canonicalize one profile-specific structural validation result."""
    canonical = tuple(
        sorted(set(issues), key=lambda issue: (issue.code.value, issue.subject, issue.message))
    )
    return JvmProfileValidation(
        target=scope.target,
        profile_id=scope.profile_id,
        profile_version=scope.profile_version,
        validation_scope_hash=scope.content_hash,
        capability_status=scope.capability_status,
        validation_evidence_refs=scope.validation_evidence_refs,
        inventory_content_hash=snapshot.inventory_content_hash,
        selection=selection,
        toolchain_policy_hash=policy_hash,
        toolchain_validation_hash=toolchain_validation_hash,
        status=(
            JvmProfileValidationStatus.INVALID
            if canonical
            else JvmProfileValidationStatus.READY_FOR_VALIDATION
        ),
        issues=canonical,
    )


def _validate_sha256(value: str, *, label: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")


def _validate_normalized_text(value: str, *, label: str) -> None:
    if not value or value != " ".join(value.split()):
        raise ValueError(f"{label} must be normalized")


def _require_canonical_text(values: tuple[str, ...], *, label: str) -> None:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{label} must be canonical and unique")
    for value in values:
        _validate_normalized_text(value, label=label)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
