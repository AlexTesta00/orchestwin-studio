"""Evidence-gated promotion of exact Java, Kotlin, and Scala JVM profiles."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final

from orchestwin.artifacts.jvm_sources import JvmSourceRevisionReference
from orchestwin.jvm_execution.detection import JvmDetectionSnapshot
from orchestwin.jvm_execution.policy import JvmToolchainDeclaration
from orchestwin.jvm_execution.profile_contracts import (
    JvmExecutionProfile,
    JvmProfileContract,
    JvmProfileValidation,
)
from orchestwin.jvm_execution.runner_contracts import JvmContainerRunnerContract
from orchestwin.jvm_execution.targets import (
    JvmValidationScope,
    promote_jvm_validation_scope,
)
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus

_IDENTIFIER_PATTERN: Final = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:[._/-][A-Za-z0-9]+)*$")
_REFERENCE_PATTERN: Final = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_VERSION_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_MINIMUM_REPRODUCIBILITY_RECORDS: Final = 2


class JvmProfileValidationEvidenceKind(StrEnum):
    """Evidence families required before one exact JVM profile can claim Level D."""

    CONTRACT_TESTS = "CONTRACT_TESTS"
    RUNNER_IMAGE = "RUNNER_IMAGE"
    RUNNER_BUILD_RECIPE = "RUNNER_BUILD_RECIPE"
    TOOLCHAIN_MANIFEST = "TOOLCHAIN_MANIFEST"
    SOURCE_FIXTURE = "SOURCE_FIXTURE"
    VALIDATE_REPORT = "VALIDATE_REPORT"
    SETUP_REPORT = "SETUP_REPORT"
    STATIC_CHECK_REPORT = "STATIC_CHECK_REPORT"
    BUILD_REPORT = "BUILD_REPORT"
    TEST_REPORT = "TEST_REPORT"
    RUN_REPORT = "RUN_REPORT"
    ARTIFACT_INVENTORY = "ARTIFACT_INVENTORY"
    FAILURE_MATRIX = "FAILURE_MATRIX"
    REPAIR_RERUN = "REPAIR_RERUN"
    REPRODUCIBILITY = "REPRODUCIBILITY"
    KNOWN_LIMITATIONS = "KNOWN_LIMITATIONS"


_REQUIRED_KINDS: Final = frozenset(
    kind
    for kind in JvmProfileValidationEvidenceKind
    if kind is not JvmProfileValidationEvidenceKind.REPRODUCIBILITY
)


class JvmProfilePromotionStatus(StrEnum):
    """Typed capability decision without inferring absent evidence."""

    ELIGIBLE = "ELIGIBLE"
    INCOMPLETE = "INCOMPLETE"
    STALE = "STALE"
    CONFLICTING = "CONFLICTING"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class JvmProfileValidationEvidence:
    """One immutable record bound to exact profile and environment identities."""

    evidence_id: str
    kind: JvmProfileValidationEvidenceKind
    profile_id: str
    profile_version: str
    baseline_scope_hash: str
    runner_image_digest: str
    runner_build_recipe_hash: str
    toolchain_manifest_hash: str
    fixture_bundle_hash: str
    environment_fingerprint: str
    artifact_content_hash: str
    reference: str
    recorded_at: datetime
    passed: bool

    def __post_init__(self) -> None:
        for value, label in (
            (self.evidence_id, "JVM validation evidence ID"),
            (self.profile_id, "JVM validation profile ID"),
        ):
            if _IDENTIFIER_PATTERN.fullmatch(value) is None:
                raise ValueError(f"{label} must be a normalized portable identifier")
        if _VERSION_PATTERN.fullmatch(self.profile_version) is None:
            raise ValueError("JVM validation profile version must be normalized")
        if _REFERENCE_PATTERN.fullmatch(self.reference) is None:
            raise ValueError("JVM validation evidence reference must be a portable URI")
        for value, label in (
            (self.baseline_scope_hash, "JVM validation baseline scope hash"),
            (self.runner_image_digest, "JVM validation runner digest"),
            (self.runner_build_recipe_hash, "JVM validation runner recipe hash"),
            (self.toolchain_manifest_hash, "JVM validation toolchain manifest hash"),
            (self.fixture_bundle_hash, "JVM validation fixture bundle hash"),
            (self.environment_fingerprint, "JVM validation environment fingerprint"),
            (self.artifact_content_hash, "JVM validation artifact hash"),
        ):
            _validate_sha256(value, label=label)
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("JVM validation evidence timestamp must be timezone-aware")
        if not isinstance(self.passed, bool):
            raise TypeError("JVM validation evidence passed marker must be a boolean")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind.value,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "baseline_scope_hash": self.baseline_scope_hash,
            "runner_image_digest": self.runner_image_digest,
            "runner_build_recipe_hash": self.runner_build_recipe_hash,
            "toolchain_manifest_hash": self.toolchain_manifest_hash,
            "fixture_bundle_hash": self.fixture_bundle_hash,
            "environment_fingerprint": self.environment_fingerprint,
            "artifact_content_hash": self.artifact_content_hash,
            "reference": self.reference,
            "recorded_at": self.recorded_at.isoformat(),
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class JvmProfileValidationEvidenceCatalog:
    """Canonical immutable collection of externally recorded JVM evidence."""

    records: tuple[JvmProfileValidationEvidence, ...]

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.records, key=_evidence_sort_key))
        if self.records != ordered:
            raise ValueError("JVM profile validation evidence must use canonical order")
        identifiers = tuple(record.evidence_id for record in self.records)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("JVM profile validation evidence IDs must be unique")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_snapshot())).hexdigest()

    def for_scope(
        self,
        scope: JvmValidationScope,
    ) -> tuple[JvmProfileValidationEvidence, ...]:
        return tuple(
            record
            for record in self.records
            if record.profile_id == scope.profile_id
            and record.profile_version == scope.profile_version
        )

    def to_snapshot(self) -> dict[str, object]:
        return {"records": [record.to_snapshot() for record in self.records]}


@dataclass(frozen=True, slots=True)
class JvmProfilePromotionDecision:
    """Inspectable promotion result and exact unmet or conflicting requirements."""

    profile_id: str
    profile_version: str
    baseline_scope_hash: str
    status: JvmProfilePromotionStatus
    evidence_refs: tuple[str, ...]
    missing_requirements: tuple[str, ...]
    issue_messages: tuple[str, ...]
    runner_image_digest: str | None
    runner_build_recipe_hash: str | None
    toolchain_manifest_hash: str | None
    fixture_bundle_hash: str | None
    environment_fingerprint: str | None

    def __post_init__(self) -> None:
        if _IDENTIFIER_PATTERN.fullmatch(self.profile_id) is None:
            raise ValueError("JVM promotion profile ID must be normalized")
        if _VERSION_PATTERN.fullmatch(self.profile_version) is None:
            raise ValueError("JVM promotion profile version must be normalized")
        _validate_sha256(
            self.baseline_scope_hash,
            label="JVM promotion baseline scope hash",
        )
        _require_canonical_text(self.evidence_refs, label="JVM promotion evidence refs")
        _require_canonical_text(
            self.missing_requirements,
            label="JVM promotion missing requirements",
        )
        _require_canonical_text(
            self.issue_messages,
            label="JVM promotion issue messages",
        )
        identities = (
            (self.runner_image_digest, "JVM promotion runner digest"),
            (self.runner_build_recipe_hash, "JVM promotion runner recipe hash"),
            (self.toolchain_manifest_hash, "JVM promotion toolchain manifest hash"),
            (self.fixture_bundle_hash, "JVM promotion fixture bundle hash"),
            (self.environment_fingerprint, "JVM promotion environment fingerprint"),
        )
        for value, label in identities:
            if value is not None:
                _validate_sha256(value, label=label)

        if self.status is JvmProfilePromotionStatus.ELIGIBLE:
            if (
                not self.evidence_refs
                or self.missing_requirements
                or self.issue_messages
                or any(value is None for value, _ in identities)
            ):
                raise ValueError("eligible JVM promotion requires complete consistent evidence")
        elif (
            (not self.missing_requirements and not self.issue_messages)
            or self.evidence_refs
            or any(value is not None for value, _ in identities)
        ):
            raise ValueError("ineligible JVM promotion must expose only its blocking reasons")

    @property
    def is_eligible(self) -> bool:
        return self.status is JvmProfilePromotionStatus.ELIGIBLE

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "baseline_scope_hash": self.baseline_scope_hash,
            "status": self.status.value,
            "evidence_refs": list(self.evidence_refs),
            "missing_requirements": list(self.missing_requirements),
            "issue_messages": list(self.issue_messages),
            "runner_image_digest": self.runner_image_digest,
            "runner_build_recipe_hash": self.runner_build_recipe_hash,
            "toolchain_manifest_hash": self.toolchain_manifest_hash,
            "fixture_bundle_hash": self.fixture_bundle_hash,
            "environment_fingerprint": self.environment_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class EvidenceBackedJvmExecutionProfile:
    """Profile adapter exposing Level D only after one eligible evidence decision."""

    base_profile: JvmExecutionProfile
    promotion: JvmProfilePromotionDecision

    def __post_init__(self) -> None:
        if not self.promotion.is_eligible:
            raise ValueError("evidence-backed JVM profile requires an eligible decision")
        scope = self.base_profile.scope
        if (
            scope.profile_id != self.promotion.profile_id
            or scope.profile_version != self.promotion.profile_version
            or scope.content_hash != self.promotion.baseline_scope_hash
        ):
            raise ValueError("JVM promotion decision targets another profile scope")

    @property
    def scope(self) -> JvmValidationScope:
        return promote_jvm_validation_scope(
            self.base_profile.scope,
            validation_evidence_refs=self.promotion.evidence_refs,
        )

    @property
    def expected_runner_id(self) -> str:
        return self.base_profile.expected_runner_id

    def validate(
        self,
        snapshot: JvmDetectionSnapshot,
        declaration: JvmToolchainDeclaration,
    ) -> JvmProfileValidation:
        base = self.base_profile.validate(snapshot, declaration)
        return replace(
            base,
            validation_scope_hash=self.scope.content_hash,
            capability_status=ExecutionCapabilityStatus.VALIDATED_LEVEL_D,
            validation_evidence_refs=self.scope.validation_evidence_refs,
        )

    def create_contract(
        self,
        snapshot: JvmDetectionSnapshot,
        declaration: JvmToolchainDeclaration,
        *,
        source_revision: JvmSourceRevisionReference,
        runner: JvmContainerRunnerContract,
    ) -> JvmProfileContract:
        if runner.image.digest != self.promotion.runner_image_digest:
            raise ValueError("JVM contract runner digest differs from validation evidence")
        base_contract = self.base_profile.create_contract(
            snapshot,
            declaration,
            source_revision=source_revision,
            runner=runner,
        )
        promoted_runner = replace(
            base_contract.runner,
            capability_status=ExecutionCapabilityStatus.VALIDATED_LEVEL_D,
            validation_evidence_refs=self.scope.validation_evidence_refs,
        )
        return JvmProfileContract(
            validation=self.validate(snapshot, declaration),
            source_revision=base_contract.source_revision,
            runner=promoted_runner,
            execution_plan=base_contract.execution_plan,
        )


def evaluate_jvm_profile_promotion(
    scope: JvmValidationScope,
    *,
    catalog: JvmProfileValidationEvidenceCatalog,
) -> JvmProfilePromotionDecision:
    """Require complete evidence families and consistent immutable identities."""
    if scope.capability_status is not ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C:
        raise ValueError("JVM promotion evaluation requires a design-only baseline scope")
    records = catalog.for_scope(scope)
    if not records:
        return _ineligible_decision(
            scope,
            status=JvmProfilePromotionStatus.INCOMPLETE,
            missing_requirements=("evidence:any",),
        )

    if any(record.baseline_scope_hash != scope.content_hash for record in records):
        return _ineligible_decision(
            scope,
            status=JvmProfilePromotionStatus.STALE,
            issue_messages=("Recorded evidence targets a stale JVM validation scope hash.",),
        )
    if any(not record.passed for record in records):
        return _ineligible_decision(
            scope,
            status=JvmProfilePromotionStatus.FAILED,
            issue_messages=("At least one JVM validation record is not passing.",),
        )

    conflicting_fields = _conflicting_identity_fields(records)
    if conflicting_fields:
        return _ineligible_decision(
            scope,
            status=JvmProfilePromotionStatus.CONFLICTING,
            issue_messages=tuple(
                f"JVM validation records disagree on {field}." for field in conflicting_fields
            ),
        )

    missing = _missing_requirements(records)
    if missing:
        return _ineligible_decision(
            scope,
            status=JvmProfilePromotionStatus.INCOMPLETE,
            missing_requirements=missing,
        )

    first = records[0]
    return JvmProfilePromotionDecision(
        profile_id=scope.profile_id,
        profile_version=scope.profile_version,
        baseline_scope_hash=scope.content_hash,
        status=JvmProfilePromotionStatus.ELIGIBLE,
        evidence_refs=tuple(sorted({record.reference for record in records})),
        missing_requirements=(),
        issue_messages=(),
        runner_image_digest=first.runner_image_digest,
        runner_build_recipe_hash=first.runner_build_recipe_hash,
        toolchain_manifest_hash=first.toolchain_manifest_hash,
        fixture_bundle_hash=first.fixture_bundle_hash,
        environment_fingerprint=first.environment_fingerprint,
    )


def promote_jvm_profile_if_eligible(
    profile: JvmExecutionProfile,
    *,
    catalog: JvmProfileValidationEvidenceCatalog,
) -> JvmExecutionProfile:
    """Return the unchanged Level C profile when evidence is not sufficient."""
    decision = evaluate_jvm_profile_promotion(profile.scope, catalog=catalog)
    if not decision.is_eligible:
        return profile
    return EvidenceBackedJvmExecutionProfile(
        base_profile=profile,
        promotion=decision,
    )


def _missing_requirements(
    records: tuple[JvmProfileValidationEvidence, ...],
) -> tuple[str, ...]:
    observed = {record.kind for record in records}
    missing = {f"profile:{kind.value}" for kind in _REQUIRED_KINDS - observed}
    reproducibility_hashes = {
        record.artifact_content_hash
        for record in records
        if record.kind is JvmProfileValidationEvidenceKind.REPRODUCIBILITY
    }
    if len(reproducibility_hashes) < _MINIMUM_REPRODUCIBILITY_RECORDS:
        missing.add(
            "profile:REPRODUCIBILITY:"
            f"{_MINIMUM_REPRODUCIBILITY_RECORDS - len(reproducibility_hashes)}-additional"
        )
    return tuple(sorted(missing))


def _conflicting_identity_fields(
    records: tuple[JvmProfileValidationEvidence, ...],
) -> tuple[str, ...]:
    fields = {
        "runner image digest": {record.runner_image_digest for record in records},
        "runner build recipe": {record.runner_build_recipe_hash for record in records},
        "toolchain manifest": {record.toolchain_manifest_hash for record in records},
        "fixture bundle": {record.fixture_bundle_hash for record in records},
        "environment fingerprint": {record.environment_fingerprint for record in records},
    }
    return tuple(sorted(name for name, values in fields.items() if len(values) != 1))


def _ineligible_decision(
    scope: JvmValidationScope,
    *,
    status: JvmProfilePromotionStatus,
    missing_requirements: tuple[str, ...] = (),
    issue_messages: tuple[str, ...] = (),
) -> JvmProfilePromotionDecision:
    return JvmProfilePromotionDecision(
        profile_id=scope.profile_id,
        profile_version=scope.profile_version,
        baseline_scope_hash=scope.content_hash,
        status=status,
        evidence_refs=(),
        missing_requirements=tuple(sorted(missing_requirements)),
        issue_messages=tuple(sorted(issue_messages)),
        runner_image_digest=None,
        runner_build_recipe_hash=None,
        toolchain_manifest_hash=None,
        fixture_bundle_hash=None,
        environment_fingerprint=None,
    )


def _evidence_sort_key(record: JvmProfileValidationEvidence) -> tuple[str, ...]:
    return (
        record.profile_id,
        record.profile_version,
        record.kind.value,
        record.evidence_id,
    )


def _validate_sha256(value: str, *, label: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")


def _require_canonical_text(values: tuple[str, ...], *, label: str) -> None:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{label} must be canonical and unique")
    if any(not value or value != " ".join(value.split()) for value in values):
        raise ValueError(f"{label} must contain normalized values")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
