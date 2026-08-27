"""Evidence-gated promotion of exact Sprint 08 Web profile versions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus
from orchestwin.web_execution.browser_evidence import WebBrowserRouteSpec
from orchestwin.web_execution.detection import WebDetectionSnapshot
from orchestwin.web_execution.lockfiles import WebDependencyLockReport
from orchestwin.web_execution.profile_contracts import (
    WebExecutionProfile,
    WebProfileContract,
    WebProfileRunnerSet,
    WebProfileValidation,
)
from orchestwin.web_execution.targets import (
    WebLanguageConfiguration,
    WebTargetSelection,
    WebValidationScope,
    promote_web_validation_scope,
)

_IDENTIFIER_PATTERN: Final = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:[._:/-][A-Za-z0-9]+)*$")
_VERSION_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_PROFILE_LEVEL_KINDS: Final = frozenset(
    {
        "CONTRACT_TESTS",
        "RUNNER_BUILD",
        "CI_VERIFICATION",
        "ENVIRONMENT_MANIFEST",
        "KNOWN_LIMITATIONS",
        "REPRODUCIBILITY",
    }
)
_CONFIGURATION_LEVEL_KINDS: Final = frozenset(
    {
        "VALID_FIXTURE_RUN",
        "FAILURE_REPAIR_RERUN",
        "BROWSER_EVIDENCE",
    }
)


class WebProfileValidationEvidenceKind(StrEnum):
    """Evidence families required before one exact profile can claim Level D."""

    CONTRACT_TESTS = "CONTRACT_TESTS"
    VALID_FIXTURE_RUN = "VALID_FIXTURE_RUN"
    FAILURE_REPAIR_RERUN = "FAILURE_REPAIR_RERUN"
    BROWSER_EVIDENCE = "BROWSER_EVIDENCE"
    RUNNER_BUILD = "RUNNER_BUILD"
    CI_VERIFICATION = "CI_VERIFICATION"
    ENVIRONMENT_MANIFEST = "ENVIRONMENT_MANIFEST"
    KNOWN_LIMITATIONS = "KNOWN_LIMITATIONS"
    REPRODUCIBILITY = "REPRODUCIBILITY"


class WebProfilePromotionStatus(StrEnum):
    """Typed capability decision without silently filling missing evidence."""

    ELIGIBLE = "ELIGIBLE"
    INCOMPLETE = "INCOMPLETE"
    STALE = "STALE"
    CONFLICTING = "CONFLICTING"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class WebProfileValidationEvidence:
    """One immutable evidence reference bound to exact profile and runner identities."""

    evidence_id: str
    kind: WebProfileValidationEvidenceKind
    profile_id: str
    profile_version: str
    baseline_scope_hash: str
    language_configuration: WebLanguageConfiguration | None
    execution_runner_image_digest: str
    browser_runner_image_digest: str | None
    artifact_content_hash: str
    reference: str
    recorded_at: datetime
    passed: bool

    def __post_init__(self) -> None:
        for value, label in (
            (self.evidence_id, "Web validation evidence ID"),
            (self.profile_id, "Web validation profile ID"),
            (self.reference, "Web validation evidence reference"),
        ):
            if _IDENTIFIER_PATTERN.fullmatch(value) is None:
                raise ValueError(f"{label} must be a normalized portable identifier")
        if _VERSION_PATTERN.fullmatch(self.profile_version) is None:
            raise ValueError("Web validation profile version must be normalized")
        for value, label in (
            (self.baseline_scope_hash, "Web validation baseline scope hash"),
            (
                self.execution_runner_image_digest,
                "Web validation execution runner digest",
            ),
            (self.artifact_content_hash, "Web validation artifact hash"),
        ):
            _validate_sha256(value, label=label)
        if self.browser_runner_image_digest is not None:
            _validate_sha256(
                self.browser_runner_image_digest,
                label="Web validation browser runner digest",
            )
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("Web validation evidence timestamp must be timezone-aware")
        if not isinstance(self.passed, bool):
            raise TypeError("Web validation evidence passed marker must be a boolean")
        if self.kind.value in _PROFILE_LEVEL_KINDS:
            if self.language_configuration is not None:
                raise ValueError("profile-level Web evidence must not select one language")
        elif self.kind.value in _CONFIGURATION_LEVEL_KINDS:
            if self.language_configuration is None:
                raise ValueError("configuration-level Web evidence requires a language")
        else:
            raise ValueError("unsupported Web validation evidence kind")

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
            "language_configuration": (
                None
                if self.language_configuration is None
                else self.language_configuration.to_snapshot()
            ),
            "execution_runner_image_digest": self.execution_runner_image_digest,
            "browser_runner_image_digest": self.browser_runner_image_digest,
            "artifact_content_hash": self.artifact_content_hash,
            "reference": self.reference,
            "recorded_at": self.recorded_at.isoformat(),
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class WebProfileValidationEvidenceCatalog:
    """Canonical immutable collection of externally recorded validation references."""

    records: tuple[WebProfileValidationEvidence, ...]

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.records, key=_evidence_sort_key))
        if self.records != ordered:
            raise ValueError("Web profile validation evidence must use canonical order")
        ids = tuple(record.evidence_id for record in self.records)
        if len(ids) != len(set(ids)):
            raise ValueError("Web profile validation evidence IDs must be unique")

    def for_scope(
        self,
        scope: WebValidationScope,
    ) -> tuple[WebProfileValidationEvidence, ...]:
        return tuple(
            record
            for record in self.records
            if record.profile_id == scope.profile_id
            and record.profile_version == scope.profile_version
        )


@dataclass(frozen=True, slots=True)
class WebProfilePromotionDecision:
    """Inspectable promotion result and exact missing or conflicting requirements."""

    profile_id: str
    profile_version: str
    baseline_scope_hash: str
    status: WebProfilePromotionStatus
    evidence_refs: tuple[str, ...]
    missing_requirements: tuple[str, ...]
    issue_messages: tuple[str, ...]
    execution_runner_image_digest: str | None
    browser_runner_image_digest: str | None

    def __post_init__(self) -> None:
        _validate_sha256(
            self.baseline_scope_hash,
            label="Web promotion baseline scope hash",
        )
        _require_canonical_text(self.evidence_refs, label="Web promotion evidence refs")
        _require_canonical_text(
            self.missing_requirements,
            label="Web promotion missing requirements",
        )
        _require_canonical_text(
            self.issue_messages,
            label="Web promotion issue messages",
        )
        if self.execution_runner_image_digest is not None:
            _validate_sha256(
                self.execution_runner_image_digest,
                label="Web promotion execution runner digest",
            )
        if self.browser_runner_image_digest is not None:
            _validate_sha256(
                self.browser_runner_image_digest,
                label="Web promotion browser runner digest",
            )
        if self.status is WebProfilePromotionStatus.ELIGIBLE:
            if (
                not self.evidence_refs
                or self.missing_requirements
                or self.issue_messages
                or self.execution_runner_image_digest is None
            ):
                raise ValueError("eligible Web promotion requires complete consistent evidence")
        elif not self.missing_requirements and not self.issue_messages:
            raise ValueError("ineligible Web promotion requires an inspectable reason")

    @property
    def is_eligible(self) -> bool:
        return self.status is WebProfilePromotionStatus.ELIGIBLE


@dataclass(frozen=True, slots=True)
class EvidenceBackedWebExecutionProfile:
    """Profile adapter exposing Level D only after one eligible evidence decision."""

    base_profile: WebExecutionProfile
    promotion: WebProfilePromotionDecision

    def __post_init__(self) -> None:
        if not self.promotion.is_eligible:
            raise ValueError("evidence-backed Web profile requires an eligible decision")
        scope = self.base_profile.scope
        if (
            scope.profile_id != self.promotion.profile_id
            or scope.profile_version != self.promotion.profile_version
            or scope.content_hash != self.promotion.baseline_scope_hash
        ):
            raise ValueError("Web promotion decision targets another profile scope")

    @property
    def scope(self) -> WebValidationScope:
        return promote_web_validation_scope(
            self.base_profile.scope,
            validation_evidence_refs=self.promotion.evidence_refs,
        )

    def validate(
        self,
        snapshot: WebDetectionSnapshot,
        *,
        selection: WebTargetSelection,
        lock_report: WebDependencyLockReport,
    ) -> WebProfileValidation:
        base = self.base_profile.validate(
            snapshot,
            selection=selection,
            lock_report=lock_report,
        )
        return WebProfileValidation(
            target=base.target,
            profile_id=base.profile_id,
            profile_version=base.profile_version,
            validation_scope_hash=self.scope.content_hash,
            capability_status=ExecutionCapabilityStatus.VALIDATED_LEVEL_D,
            validation_evidence_refs=self.scope.validation_evidence_refs,
            inventory_content_hash=base.inventory_content_hash,
            selection=base.selection,
            lock_report_content_hash=base.lock_report_content_hash,
            status=base.status,
            issues=base.issues,
        )

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
    ) -> WebProfileContract:
        if runners.execution_runner_image_digest != (self.promotion.execution_runner_image_digest):
            raise ValueError("Web contract runner digest differs from validation evidence")
        if runners.browser_runner_image_digest != self.promotion.browser_runner_image_digest:
            raise ValueError("Web browser runner digest differs from validation evidence")
        base_contract = self.base_profile.create_contract(
            snapshot,
            selection=selection,
            lock_report=lock_report,
            source_revision_content_hash=source_revision_content_hash,
            source_tree_hash=source_tree_hash,
            runners=runners,
            declared_routes=declared_routes,
        )
        validation = self.validate(
            snapshot,
            selection=selection,
            lock_report=lock_report,
        )
        return WebProfileContract(
            validation=validation,
            source_revision_content_hash=base_contract.source_revision_content_hash,
            source_tree_hash=base_contract.source_tree_hash,
            runners=base_contract.runners,
            execution_plan=base_contract.execution_plan,
            health_checks=base_contract.health_checks,
            browser_evidence_request=base_contract.browser_evidence_request,
        )


def evaluate_web_profile_promotion(
    scope: WebValidationScope,
    *,
    catalog: WebProfileValidationEvidenceCatalog,
) -> WebProfilePromotionDecision:
    """Require exact evidence kinds, variant coverage, and consistent runner digests."""
    records = catalog.for_scope(scope)
    if not records:
        return _ineligible_decision(
            scope,
            status=WebProfilePromotionStatus.INCOMPLETE,
            missing_requirements=("evidence:any",),
        )

    stale = tuple(record for record in records if record.baseline_scope_hash != scope.content_hash)
    if stale:
        return _ineligible_decision(
            scope,
            status=WebProfilePromotionStatus.STALE,
            issue_messages=("Recorded evidence targets a stale validation scope hash.",),
        )
    failed = tuple(record for record in records if not record.passed)
    if failed:
        return _ineligible_decision(
            scope,
            status=WebProfilePromotionStatus.FAILED,
            issue_messages=("At least one required validation record is not passing.",),
        )
    unexpected_configurations = tuple(
        record
        for record in records
        if record.language_configuration is not None
        and record.language_configuration not in scope.language_configurations
    )
    if unexpected_configurations:
        return _ineligible_decision(
            scope,
            status=WebProfilePromotionStatus.CONFLICTING,
            issue_messages=(
                "Validation records contain a language configuration outside the scope.",
            ),
        )

    execution_digests = {record.execution_runner_image_digest for record in records}
    browser_digests = {record.browser_runner_image_digest for record in records}
    expected_browser_values = 1
    if len(execution_digests) != 1 or len(browser_digests) != expected_browser_values:
        return _ineligible_decision(
            scope,
            status=WebProfilePromotionStatus.CONFLICTING,
            issue_messages=("Validation records contain conflicting runner identities.",),
        )
    execution_digest = next(iter(execution_digests))
    browser_digest = next(iter(browser_digests))
    if scope.requires_browser_evidence and browser_digest is None:
        return _ineligible_decision(
            scope,
            status=WebProfilePromotionStatus.INCOMPLETE,
            missing_requirements=("runner:browser",),
        )
    if not scope.requires_browser_evidence and browser_digest is not None:
        return _ineligible_decision(
            scope,
            status=WebProfilePromotionStatus.CONFLICTING,
            issue_messages=("API-only profile evidence contains an unexpected browser runner.",),
        )

    missing = _missing_requirements(scope, records=records)
    if missing:
        return _ineligible_decision(
            scope,
            status=WebProfilePromotionStatus.INCOMPLETE,
            missing_requirements=missing,
        )
    references = tuple(sorted({record.reference for record in records}))
    return WebProfilePromotionDecision(
        profile_id=scope.profile_id,
        profile_version=scope.profile_version,
        baseline_scope_hash=scope.content_hash,
        status=WebProfilePromotionStatus.ELIGIBLE,
        evidence_refs=references,
        missing_requirements=(),
        issue_messages=(),
        execution_runner_image_digest=execution_digest,
        browser_runner_image_digest=browser_digest,
    )


def promote_web_profile_if_eligible(
    profile: WebExecutionProfile,
    *,
    catalog: WebProfileValidationEvidenceCatalog,
) -> WebExecutionProfile:
    decision = evaluate_web_profile_promotion(profile.scope, catalog=catalog)
    if not decision.is_eligible:
        return profile
    return EvidenceBackedWebExecutionProfile(
        base_profile=profile,
        promotion=decision,
    )


def _missing_requirements(
    scope: WebValidationScope,
    *,
    records: tuple[WebProfileValidationEvidence, ...],
) -> tuple[str, ...]:
    missing: set[str] = set()
    kinds = {record.kind for record in records if record.language_configuration is None}
    for kind_name in _PROFILE_LEVEL_KINDS:
        kind = WebProfileValidationEvidenceKind(kind_name)
        if kind not in kinds:
            missing.add(f"profile:{kind.value}")

    for configuration in scope.language_configurations:
        configuration_records = tuple(
            record for record in records if record.language_configuration == configuration
        )
        required = {
            WebProfileValidationEvidenceKind.VALID_FIXTURE_RUN,
            WebProfileValidationEvidenceKind.FAILURE_REPAIR_RERUN,
        }
        if scope.requires_browser_evidence:
            required.add(WebProfileValidationEvidenceKind.BROWSER_EVIDENCE)
        observed = {record.kind for record in configuration_records}
        configuration_label = _configuration_label(configuration)
        for kind in required - observed:
            missing.add(f"configuration:{configuration_label}:{kind.value}")
    return tuple(sorted(missing))


def _configuration_label(configuration: WebLanguageConfiguration) -> str:
    frontend = "NONE" if configuration.frontend is None else configuration.frontend.value
    backend = "NONE" if configuration.backend is None else configuration.backend.value
    return f"{frontend}+{backend}"


def _ineligible_decision(
    scope: WebValidationScope,
    *,
    status: WebProfilePromotionStatus,
    missing_requirements: tuple[str, ...] = (),
    issue_messages: tuple[str, ...] = (),
) -> WebProfilePromotionDecision:
    return WebProfilePromotionDecision(
        profile_id=scope.profile_id,
        profile_version=scope.profile_version,
        baseline_scope_hash=scope.content_hash,
        status=status,
        evidence_refs=(),
        missing_requirements=tuple(sorted(missing_requirements)),
        issue_messages=tuple(sorted(issue_messages)),
        execution_runner_image_digest=None,
        browser_runner_image_digest=None,
    )


def _evidence_sort_key(record: WebProfileValidationEvidence) -> tuple[str, ...]:
    configuration = (
        ""
        if record.language_configuration is None
        else _configuration_label(record.language_configuration)
    )
    return (
        record.profile_id,
        record.profile_version,
        record.kind.value,
        configuration,
        record.evidence_id,
    )


def _validate_sha256(value: str, *, label: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")


def _require_canonical_text(values: tuple[str, ...], *, label: str) -> None:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{label} must be canonical and unique")
    if any(not value or value != value.strip() for value in values):
        raise ValueError(f"{label} must contain normalized values")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
