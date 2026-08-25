"""Deterministic execution-profile detection and capability negotiation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from orchestwin.sandbox.execution_profile_registry import ExecutionProfileRegistry
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfile,
    ExecutionProfileDetection,
    ExecutionProfileProjectValidation,
    ExecutionProfileProjectValidationStatus,
    ExecutionProfileReference,
    ExecutionTarget,
)
from orchestwin.sandbox.source_inventory import SourceTreeInventory

_RUNNER_ID_PATTERN: Final = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*$")


class CapabilityNegotiationStatus(StrEnum):
    """Observable outcome of one deterministic negotiation attempt."""

    VALIDATED_LEVEL_D_SELECTED = "VALIDATED_LEVEL_D_SELECTED"
    EXPERIMENTAL_LEVEL_D_SELECTED = "EXPERIMENTAL_LEVEL_D_SELECTED"
    DESIGN_ONLY_LEVEL_C_SELECTED = "DESIGN_ONLY_LEVEL_C_SELECTED"
    HUMAN_DECISION_REQUIRED = "HUMAN_DECISION_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"


class CapabilityNegotiationIssueCode(StrEnum):
    """Stable reasons why automatic execution could not be selected."""

    NO_PROFILE_DETECTED = "NO_PROFILE_DETECTED"
    REQUESTED_TARGET_UNAVAILABLE = "REQUESTED_TARGET_UNAVAILABLE"
    PARTIAL_OR_CONFLICTING_DETECTION = "PARTIAL_OR_CONFLICTING_DETECTION"
    PROJECT_VALIDATION_FAILED = "PROJECT_VALIDATION_FAILED"
    RUNNER_UNAVAILABLE = "RUNNER_UNAVAILABLE"
    EXPERIMENTAL_APPROVAL_REQUIRED = "EXPERIMENTAL_APPROVAL_REQUIRED"
    AMBIGUOUS_PROFILE_MATCH = "AMBIGUOUS_PROFILE_MATCH"


@dataclass(frozen=True, slots=True)
class CapabilityNegotiationRequest:
    """Owner and runtime constraints supplied to capability negotiation."""

    requested_target: ExecutionTarget | None
    available_runners: tuple[str, ...]
    approved_experimental_profiles: tuple[ExecutionProfileReference, ...]

    def __post_init__(self) -> None:
        """Require canonical runner and approval sets for reproducible decisions."""
        if self.available_runners != tuple(sorted(set(self.available_runners))):
            raise ValueError("available execution runners must be canonical and unique")
        if any(_RUNNER_ID_PATTERN.fullmatch(value) is None for value in self.available_runners):
            raise ValueError("available execution runners must be portable identifiers")

        ordered_approvals = tuple(sorted(self.approved_experimental_profiles, key=_reference_key))
        if self.approved_experimental_profiles != ordered_approvals or len(
            self.approved_experimental_profiles
        ) != len(set(self.approved_experimental_profiles)):
            raise ValueError("approved experimental profile references must be canonical")

    def to_snapshot(self) -> dict[str, object]:
        """Return safe owner-policy and runner metadata."""
        return {
            "requested_target": (
                None if self.requested_target is None else self.requested_target.value
            ),
            "available_runners": list(self.available_runners),
            "approved_experimental_profiles": [
                reference.to_snapshot() for reference in self.approved_experimental_profiles
            ],
        }


@dataclass(frozen=True, slots=True)
class CapabilityCandidate:
    """One detected profile with visible validation, runner, and approval state."""

    profile_reference: ExecutionProfileReference
    capability_status: ExecutionCapabilityStatus
    detection: ExecutionProfileDetection
    validation: ExecutionProfileProjectValidation
    missing_runners: tuple[str, ...]
    experimental_approval_satisfied: bool
    structurally_unambiguous: bool
    selectable: bool

    def __post_init__(self) -> None:
        """Protect exact profile binding and candidate-selection semantics."""
        if self.detection.profile_reference != self.profile_reference:
            raise ValueError("capability candidate detection targets another profile")
        if self.validation.profile_reference != self.profile_reference:
            raise ValueError("capability candidate validation targets another profile")
        if self.missing_runners != tuple(sorted(set(self.missing_runners))):
            raise ValueError("capability candidate missing runners must be canonical")
        if not isinstance(self.experimental_approval_satisfied, bool):
            raise TypeError("experimental approval marker must be boolean")
        if not isinstance(self.structurally_unambiguous, bool):
            raise TypeError("structural ambiguity marker must be boolean")
        if not isinstance(self.selectable, bool):
            raise TypeError("capability candidate selectable marker must be boolean")

        if (
            self.capability_status is not ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D
            and self.experimental_approval_satisfied
        ):
            raise ValueError("only experimental candidates can satisfy experimental approval")

        if self.selectable and (self.missing_runners or not self.structurally_unambiguous):
            raise ValueError("selectable capability candidate must be structurally ready")
        if (
            self.selectable
            and self.capability_status is ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D
            and not self.experimental_approval_satisfied
        ):
            raise ValueError("selectable experimental candidate requires exact approval")

    def to_snapshot(self) -> dict[str, object]:
        """Return deterministic candidate evidence."""
        return {
            "profile_reference": self.profile_reference.to_snapshot(),
            "capability_status": self.capability_status.value,
            "detection": self.detection.to_snapshot(),
            "validation": self.validation.to_snapshot(),
            "missing_runners": list(self.missing_runners),
            "experimental_approval_satisfied": self.experimental_approval_satisfied,
            "structurally_unambiguous": self.structurally_unambiguous,
            "selectable": self.selectable,
        }


@dataclass(frozen=True, slots=True)
class CapabilityNegotiationIssue:
    """One inspectable reason for degradation, pause, or owner intervention."""

    code: CapabilityNegotiationIssueCode
    message: str
    profile_reference: ExecutionProfileReference | None = None

    def __post_init__(self) -> None:
        if not self.message or self.message != " ".join(self.message.split()):
            raise ValueError("capability negotiation issue message must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "message": self.message,
            "profile_reference": (
                None if self.profile_reference is None else self.profile_reference.to_snapshot()
            ),
        }


@dataclass(frozen=True, slots=True)
class CapabilityNegotiationResult:
    """Effective capability decision bound to exact registry and inventory digests."""

    registry_content_hash: str
    inventory_content_hash: str
    request: CapabilityNegotiationRequest
    status: CapabilityNegotiationStatus
    effective_capability_status: ExecutionCapabilityStatus
    selected_profile_reference: ExecutionProfileReference | None
    candidates: tuple[CapabilityCandidate, ...]
    issues: tuple[CapabilityNegotiationIssue, ...]
    requires_human_decision: bool

    def __post_init__(self) -> None:
        """Protect explicit degradation and selected-profile result shapes."""
        _validate_digest(self.registry_content_hash, label="execution profile registry hash")
        _validate_digest(self.inventory_content_hash, label="source inventory content hash")
        if self.candidates != tuple(sorted(self.candidates, key=_candidate_sort_key)):
            raise ValueError("capability candidates must use canonical ranking order")
        if not isinstance(self.requires_human_decision, bool):
            raise TypeError("capability human-decision marker must be boolean")

        selected_statuses = {
            CapabilityNegotiationStatus.VALIDATED_LEVEL_D_SELECTED,
            CapabilityNegotiationStatus.EXPERIMENTAL_LEVEL_D_SELECTED,
            CapabilityNegotiationStatus.DESIGN_ONLY_LEVEL_C_SELECTED,
        }
        if self.status in selected_statuses:
            if self.selected_profile_reference is None:
                raise ValueError("selected capability result requires a profile reference")
            if self.requires_human_decision:
                raise ValueError("selected capability result cannot require a human decision")
        elif self.selected_profile_reference is not None:
            raise ValueError("non-selected capability result must not expose a selected profile")

        if self.status is CapabilityNegotiationStatus.HUMAN_DECISION_REQUIRED and (
            not self.requires_human_decision or not self.issues
        ):
            raise ValueError("human-decision capability result requires issues")

        if self.status is CapabilityNegotiationStatus.UNSUPPORTED:
            if self.effective_capability_status is not (
                ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
            ):
                raise ValueError("unsupported capability must degrade explicitly to Level C")
            if not self.issues:
                raise ValueError("unsupported capability result requires an issue")

    def to_snapshot(self) -> dict[str, object]:
        """Return deterministic negotiation evidence for API, UI, and export."""
        return {
            "registry_content_hash": self.registry_content_hash,
            "inventory_content_hash": self.inventory_content_hash,
            "request": self.request.to_snapshot(),
            "status": self.status.value,
            "effective_capability_status": self.effective_capability_status.value,
            "selected_profile_reference": (
                None
                if self.selected_profile_reference is None
                else self.selected_profile_reference.to_snapshot()
            ),
            "candidates": [candidate.to_snapshot() for candidate in self.candidates],
            "issues": [issue.to_snapshot() for issue in self.issues],
            "requires_human_decision": self.requires_human_decision,
        }


def negotiate_execution_capability(
    inventory: SourceTreeInventory,
    *,
    registry: ExecutionProfileRegistry,
    request: CapabilityNegotiationRequest,
) -> CapabilityNegotiationResult:
    """Detect, validate, rank, and honestly degrade execution capability."""
    profiles = (
        registry.profiles
        if request.requested_target is None
        else registry.profiles_for_target(request.requested_target)
    )
    detected_candidates: list[CapabilityCandidate] = []
    for profile in profiles:
        detection = profile.detect(inventory)
        if detection.is_candidate:
            detected_candidates.append(
                _candidate(
                    profile,
                    detection=detection,
                    inventory=inventory,
                    request=request,
                )
            )
    candidates = tuple(sorted(detected_candidates, key=_candidate_sort_key))

    if not candidates:
        issue = CapabilityNegotiationIssue(
            code=(
                CapabilityNegotiationIssueCode.REQUESTED_TARGET_UNAVAILABLE
                if request.requested_target is not None
                else CapabilityNegotiationIssueCode.NO_PROFILE_DETECTED
            ),
            message=(
                "No registered profile matches the requested target and source structure."
                if request.requested_target is not None
                else "No registered execution profile matches the source structure."
            ),
        )
        return _result(
            inventory=inventory,
            registry=registry,
            request=request,
            status=CapabilityNegotiationStatus.UNSUPPORTED,
            effective=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
            selected=None,
            candidates=(),
            issues=(issue,),
            requires_human_decision=False,
        )

    structurally_ready = tuple(
        candidate for candidate in candidates if candidate.structurally_unambiguous
    )
    if not structurally_ready:
        issues = tuple(
            CapabilityNegotiationIssue(
                code=(
                    CapabilityNegotiationIssueCode.PROJECT_VALIDATION_FAILED
                    if candidate.validation.status
                    is ExecutionProfileProjectValidationStatus.INVALID
                    else CapabilityNegotiationIssueCode.PARTIAL_OR_CONFLICTING_DETECTION
                ),
                message=(
                    "Detected profile evidence is partial, conflicting, or structurally invalid."
                ),
                profile_reference=candidate.profile_reference,
            )
            for candidate in candidates
        )
        return _result(
            inventory=inventory,
            registry=registry,
            request=request,
            status=CapabilityNegotiationStatus.HUMAN_DECISION_REQUIRED,
            effective=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
            selected=None,
            candidates=candidates,
            issues=issues,
            requires_human_decision=True,
        )

    highest_confidence = structurally_ready[0].detection.confidence
    best = tuple(
        candidate
        for candidate in structurally_ready
        if candidate.detection.confidence == highest_confidence
    )
    if len(best) > 1:
        issue = CapabilityNegotiationIssue(
            code=CapabilityNegotiationIssueCode.AMBIGUOUS_PROFILE_MATCH,
            message="Multiple execution profiles have equally strong structural evidence.",
        )
        return _result(
            inventory=inventory,
            registry=registry,
            request=request,
            status=CapabilityNegotiationStatus.HUMAN_DECISION_REQUIRED,
            effective=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
            selected=None,
            candidates=candidates,
            issues=(issue,),
            requires_human_decision=True,
        )

    chosen = best[0]
    if chosen.missing_runners:
        issue = CapabilityNegotiationIssue(
            code=CapabilityNegotiationIssueCode.RUNNER_UNAVAILABLE,
            message="The selected profile requires runners that are not currently available.",
            profile_reference=chosen.profile_reference,
        )
        return _result(
            inventory=inventory,
            registry=registry,
            request=request,
            status=CapabilityNegotiationStatus.HUMAN_DECISION_REQUIRED,
            effective=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
            selected=None,
            candidates=candidates,
            issues=(issue,),
            requires_human_decision=True,
        )

    if chosen.capability_status is ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D:
        if not chosen.experimental_approval_satisfied:
            issue = CapabilityNegotiationIssue(
                code=CapabilityNegotiationIssueCode.EXPERIMENTAL_APPROVAL_REQUIRED,
                message="The experimental profile requires exact owner approval before use.",
                profile_reference=chosen.profile_reference,
            )
            return _result(
                inventory=inventory,
                registry=registry,
                request=request,
                status=CapabilityNegotiationStatus.HUMAN_DECISION_REQUIRED,
                effective=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
                selected=None,
                candidates=candidates,
                issues=(issue,),
                requires_human_decision=True,
            )
        return _selected_result(
            inventory=inventory,
            registry=registry,
            request=request,
            status=CapabilityNegotiationStatus.EXPERIMENTAL_LEVEL_D_SELECTED,
            candidate=chosen,
            candidates=candidates,
        )

    if chosen.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D:
        return _selected_result(
            inventory=inventory,
            registry=registry,
            request=request,
            status=CapabilityNegotiationStatus.VALIDATED_LEVEL_D_SELECTED,
            candidate=chosen,
            candidates=candidates,
        )

    return _selected_result(
        inventory=inventory,
        registry=registry,
        request=request,
        status=CapabilityNegotiationStatus.DESIGN_ONLY_LEVEL_C_SELECTED,
        candidate=chosen,
        candidates=candidates,
    )


def _candidate(
    profile: ExecutionProfile,
    *,
    detection: ExecutionProfileDetection,
    inventory: SourceTreeInventory,
    request: CapabilityNegotiationRequest,
) -> CapabilityCandidate:
    validation = profile.validate_project(inventory)
    missing_runners = tuple(
        sorted(set(profile.metadata.required_runners) - set(request.available_runners))
    )
    approved = (
        profile.metadata.capability_status is ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D
        and profile.metadata.reference in request.approved_experimental_profiles
    )
    structurally_unambiguous = (
        detection.confidence == 100
        and not detection.conflicting_indicators
        and not detection.missing_tools
        and not detection.requires_human_decision
        and validation.status
        in {
            ExecutionProfileProjectValidationStatus.VALID,
            ExecutionProfileProjectValidationStatus.DESIGN_ONLY,
        }
    )
    selectable = (
        structurally_unambiguous
        and not missing_runners
        and (
            profile.metadata.capability_status is not ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D
            or approved
        )
    )
    return CapabilityCandidate(
        profile_reference=profile.metadata.reference,
        capability_status=profile.metadata.capability_status,
        detection=detection,
        validation=validation,
        missing_runners=missing_runners,
        experimental_approval_satisfied=approved,
        structurally_unambiguous=structurally_unambiguous,
        selectable=selectable,
    )


def _selected_result(
    *,
    inventory: SourceTreeInventory,
    registry: ExecutionProfileRegistry,
    request: CapabilityNegotiationRequest,
    status: CapabilityNegotiationStatus,
    candidate: CapabilityCandidate,
    candidates: tuple[CapabilityCandidate, ...],
) -> CapabilityNegotiationResult:
    return _result(
        inventory=inventory,
        registry=registry,
        request=request,
        status=status,
        effective=candidate.capability_status,
        selected=candidate.profile_reference,
        candidates=candidates,
        issues=(),
        requires_human_decision=False,
    )


def _result(
    *,
    inventory: SourceTreeInventory,
    registry: ExecutionProfileRegistry,
    request: CapabilityNegotiationRequest,
    status: CapabilityNegotiationStatus,
    effective: ExecutionCapabilityStatus,
    selected: ExecutionProfileReference | None,
    candidates: tuple[CapabilityCandidate, ...],
    issues: tuple[CapabilityNegotiationIssue, ...],
    requires_human_decision: bool,
) -> CapabilityNegotiationResult:
    return CapabilityNegotiationResult(
        registry_content_hash=registry.content_hash,
        inventory_content_hash=inventory.content_hash,
        request=request,
        status=status,
        effective_capability_status=effective,
        selected_profile_reference=selected,
        candidates=candidates,
        issues=issues,
        requires_human_decision=requires_human_decision,
    )


def _candidate_sort_key(candidate: CapabilityCandidate) -> tuple[int, str, str, str]:
    return (
        -candidate.detection.confidence,
        candidate.profile_reference.profile_id,
        candidate.profile_reference.profile_version,
        candidate.profile_reference.content_hash,
    )


def _reference_key(reference: ExecutionProfileReference) -> tuple[str, str, str]:
    return (
        reference.profile_id,
        reference.profile_version,
        reference.content_hash,
    )


def _validate_digest(value: str, *, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be lowercase SHA-256")
