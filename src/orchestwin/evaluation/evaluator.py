"""Provider-independent User Twin evaluator port and deterministic fake adapter."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from orchestwin.evaluation.artifacts import (
    EvaluationArtifactBundle,
    EvaluationArtifactKind,
    EvaluationArtifactReference,
)
from orchestwin.evaluation.findings import (
    SyntheticFinding,
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.evaluation.validation import EvaluationEvidenceReference
from orchestwin.projects.requirements_primitives import (
    canonical_json,
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.twins.user_twins import (
    UserTwinLifecycleStatus,
    UserTwinProfileVersion,
)

_MAX_IDENTIFIER_LENGTH = 256
_MAX_NAME_LENGTH = 200
_MAX_SUMMARY_LENGTH = 4_000
_MAX_EVIDENCE_GAP_LENGTH = 1_000

SYNTHETIC_EVALUATION_DISCLAIMER = (
    "This is simulated feedback based on the available profile, evidence, and project "
    "artifacts. It is a design hypothesis and not empirical evidence of real-user behavior."
)


@dataclass(frozen=True, slots=True)
class UserTwinEvaluatorConfiguration:
    """Versioned evaluator identity independent from one model provider SDK."""

    evaluator_id: str
    evaluator_version: str
    model_config_ref: str
    prompt_version_ref: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.evaluator_id, "User Twin evaluator ID"),
            (self.evaluator_version, "User Twin evaluator version"),
            (self.model_config_ref, "User Twin evaluator model configuration reference"),
            (self.prompt_version_ref, "User Twin evaluator prompt version reference"),
        ):
            normalized = normalize_required_text(
                value,
                label=label,
                maximum_length=_MAX_IDENTIFIER_LENGTH,
            )
            if normalized != value or any(character.isspace() for character in value):
                raise ValueError(f"{label} must be a normalized identifier")

    def to_snapshot(self) -> dict[str, str]:
        return {
            "evaluator_id": self.evaluator_id,
            "evaluator_version": self.evaluator_version,
            "model_config_ref": self.model_config_ref,
            "prompt_version_ref": self.prompt_version_ref,
        }


@dataclass(frozen=True, slots=True)
class EvaluationUserTwinProfile:
    """Exact immutable User Twin version supplied to one evaluator invocation."""

    twin_id: UUID
    version_number: int
    name: str
    lifecycle_status: UserTwinLifecycleStatus
    content_hash: str
    snapshot_json: str

    def __post_init__(self) -> None:
        validate_positive_integer(
            self.version_number,
            label="evaluation User Twin version",
        )
        normalized_name = normalize_required_text(
            self.name,
            label="evaluation User Twin name",
            maximum_length=_MAX_NAME_LENGTH,
        )
        if normalized_name != self.name:
            raise ValueError("evaluation User Twin name must be normalized")
        validate_sha256(
            self.content_hash,
            label="evaluation User Twin content hash",
        )
        if not self.snapshot_json:
            raise ValueError("evaluation User Twin snapshot must not be empty")
        if hashlib.sha256(self.snapshot_json.encode("utf-8")).hexdigest() != self.content_hash:
            raise ValueError("evaluation User Twin snapshot must match its content hash")

    @classmethod
    def from_version(cls, version: UserTwinProfileVersion) -> EvaluationUserTwinProfile:
        """Create an evaluator-safe snapshot from one stored User Twin version."""
        return cls(
            twin_id=version.twin_id,
            version_number=version.version_number,
            name=version.profile.name,
            lifecycle_status=version.profile.validation_status,
            content_hash=version.content_hash,
            snapshot_json=version.profile.canonical_json(),
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "twin_id": str(self.twin_id),
            "version_number": self.version_number,
            "name": self.name,
            "lifecycle_status": self.lifecycle_status.value,
            "content_hash": self.content_hash,
            "snapshot_json": self.snapshot_json,
        }


@dataclass(frozen=True, slots=True)
class UserTwinEvaluationRequest:
    """Exact authorized context for one independent User Twin evaluation."""

    evaluation_run_id: UUID
    project_id: UUID
    workflow_run_id: UUID
    artifact_bundle: EvaluationArtifactBundle
    twin: EvaluationUserTwinProfile
    evidence: tuple[EvaluationEvidenceReference, ...]
    requested_at: datetime

    def __post_init__(self) -> None:
        if self.artifact_bundle.project_id != self.project_id:
            raise ValueError("evaluation request project must match the artifact bundle")
        if self.artifact_bundle.workflow_run_id != self.workflow_run_id:
            raise ValueError("evaluation request workflow run must match the artifact bundle")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("evaluation request timestamp must be timezone-aware")
        ordered_evidence = tuple(sorted(self.evidence, key=lambda item: item.sort_key))
        if ordered_evidence != self.evidence:
            raise ValueError("evaluation request evidence must use canonical order")
        identifiers = tuple(reference.reference_id for reference in self.evidence)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("evaluation request evidence references must be unique")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "evaluation_run_id": str(self.evaluation_run_id),
            "project_id": str(self.project_id),
            "workflow_run_id": str(self.workflow_run_id),
            "artifact_bundle": self.artifact_bundle.to_snapshot(),
            "twin": self.twin.to_snapshot(),
            "evidence": [reference.to_snapshot() for reference in self.evidence],
            "requested_at": self.requested_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class UserTwinEvaluationResponse:
    """Structured result of one isolated evaluator invocation."""

    evaluation_run_id: UUID
    artifact_bundle_id: UUID
    artifact_bundle_hash: str
    twin_id: UUID
    twin_version: int
    evaluator: UserTwinEvaluatorConfiguration
    findings: tuple[SyntheticFinding, ...]
    summary: str
    evidence_gaps: tuple[str, ...]
    completed_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        validate_positive_integer(
            self.twin_version,
            label="evaluation response User Twin version",
        )
        validate_sha256(
            self.artifact_bundle_hash,
            label="evaluation response artifact bundle hash",
        )
        normalized_summary = normalize_required_text(
            self.summary,
            label="User Twin evaluation summary",
            maximum_length=_MAX_SUMMARY_LENGTH,
        )
        gaps = normalize_text_items(
            self.evidence_gaps,
            label="User Twin evaluation evidence gap",
            maximum_item_length=_MAX_EVIDENCE_GAP_LENGTH,
            require_items=False,
        )
        canonical_gaps = tuple(sorted(gaps))
        if normalized_summary != self.summary or gaps != canonical_gaps:
            raise ValueError("User Twin evaluation response text must be normalized and canonical")
        if canonical_gaps != self.evidence_gaps:
            raise ValueError("User Twin evaluation evidence gaps must use canonical order")
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("evaluation completion timestamp must be timezone-aware")
        ordered_findings = tuple(sorted(self.findings, key=lambda item: item.finding_id))
        if ordered_findings != self.findings:
            raise ValueError("User Twin evaluation findings must use canonical ID order")
        finding_ids = tuple(finding.finding_id for finding in self.findings)
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("User Twin evaluation finding IDs must be unique")
        if any(
            finding.twin_id != self.twin_id or finding.twin_version != self.twin_version
            for finding in self.findings
        ):
            raise ValueError("User Twin evaluation findings must match the evaluated twin version")
        validate_sha256(
            self.content_hash,
            label="User Twin evaluation response content hash",
        )
        if self.content_hash != user_twin_evaluation_response_hash(
            evaluation_run_id=self.evaluation_run_id,
            artifact_bundle_id=self.artifact_bundle_id,
            artifact_bundle_hash=self.artifact_bundle_hash,
            twin_id=self.twin_id,
            twin_version=self.twin_version,
            evaluator=self.evaluator,
            findings=self.findings,
            summary=self.summary,
            evidence_gaps=self.evidence_gaps,
        ):
            raise ValueError("User Twin evaluation response content hash is inconsistent")

    @property
    def disclaimer(self) -> str:
        return SYNTHETIC_EVALUATION_DISCLAIMER

    def semantic_snapshot(self) -> dict[str, object]:
        return _response_semantic_snapshot(
            evaluation_run_id=self.evaluation_run_id,
            artifact_bundle_id=self.artifact_bundle_id,
            artifact_bundle_hash=self.artifact_bundle_hash,
            twin_id=self.twin_id,
            twin_version=self.twin_version,
            evaluator=self.evaluator,
            findings=self.findings,
            summary=self.summary,
            evidence_gaps=self.evidence_gaps,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            **self.semantic_snapshot(),
            "completed_at": self.completed_at.isoformat(),
            "content_hash": self.content_hash,
            "disclaimer": self.disclaimer,
        }


class UserTwinEvaluatorPort(Protocol):
    """Provider-independent asynchronous synthetic evaluator boundary."""

    @property
    def configuration(self) -> UserTwinEvaluatorConfiguration: ...

    async def evaluate(
        self,
        request: UserTwinEvaluationRequest,
    ) -> UserTwinEvaluationResponse: ...


@dataclass(frozen=True, slots=True)
class FakeSyntheticFindingTemplate:
    """Deterministic fixture output used by the fake evaluator adapter."""

    finding_id: str
    artifact_kind: EvaluationArtifactKind
    location: str
    summary: str
    rationale: str
    criterion: SyntheticFindingCriterion
    severity: SyntheticFindingSeverity
    epistemic_status: SyntheticFindingEpistemicStatus
    evidence_refs: tuple[str, ...]
    confidence: float
    recommended_action: str
    requires_human_validation: bool


class FakeUserTwinEvaluator:
    """Deterministic evaluator requiring neither network access nor credentials."""

    def __init__(
        self,
        *,
        configuration: UserTwinEvaluatorConfiguration,
        templates_by_twin: Mapping[UUID, tuple[FakeSyntheticFindingTemplate, ...]],
        summaries_by_twin: Mapping[UUID, str],
        evidence_gaps_by_twin: Mapping[UUID, tuple[str, ...]] | None = None,
        clock: Callable[[], datetime],
    ) -> None:
        self._configuration = configuration
        self._templates_by_twin = dict(templates_by_twin)
        self._summaries_by_twin = dict(summaries_by_twin)
        self._evidence_gaps_by_twin = dict(evidence_gaps_by_twin or {})
        self._clock = clock
        self.requests: list[UserTwinEvaluationRequest] = []

    @property
    def configuration(self) -> UserTwinEvaluatorConfiguration:
        return self._configuration

    async def evaluate(
        self,
        request: UserTwinEvaluationRequest,
    ) -> UserTwinEvaluationResponse:
        self.requests.append(request)
        templates = self._templates_by_twin.get(request.twin.twin_id, ())
        summary = self._summaries_by_twin.get(
            request.twin.twin_id,
            "No deterministic synthetic finding was configured for this User Twin.",
        )
        artifacts_by_kind: dict[EvaluationArtifactKind, EvaluationArtifactReference] = {}
        for artifact in request.artifact_bundle.artifacts:
            artifacts_by_kind.setdefault(artifact.kind, artifact)

        allowed_evidence = {reference.reference_id for reference in request.evidence}
        findings: list[SyntheticFinding] = []
        for template in templates:
            artifact = artifacts_by_kind.get(template.artifact_kind)
            if artifact is None:
                raise ValueError(
                    "fake evaluator template requires an artifact kind absent from the bundle"
                )
            unknown_references = set(template.evidence_refs) - allowed_evidence
            if unknown_references:
                raise ValueError("fake evaluator template cites unauthorized evidence")
            findings.append(
                create_synthetic_finding(
                    finding_id=template.finding_id,
                    twin_id=request.twin.twin_id,
                    twin_version=request.twin.version_number,
                    artifact_id=artifact.artifact_id,
                    artifact_version=artifact.version_number,
                    location=template.location,
                    summary=template.summary,
                    rationale=template.rationale,
                    criterion=template.criterion,
                    severity=template.severity,
                    epistemic_status=template.epistemic_status,
                    evidence_refs=template.evidence_refs,
                    confidence=template.confidence,
                    recommended_action=template.recommended_action,
                    requires_human_validation=template.requires_human_validation,
                    model_config_ref=self.configuration.model_config_ref,
                    prompt_version_ref=self.configuration.prompt_version_ref,
                )
            )
        ordered_findings = tuple(sorted(findings, key=lambda item: item.finding_id))
        evidence_gaps = tuple(sorted(self._evidence_gaps_by_twin.get(request.twin.twin_id, ())))
        completed_at = self._clock()
        return UserTwinEvaluationResponse(
            evaluation_run_id=request.evaluation_run_id,
            artifact_bundle_id=request.artifact_bundle.id,
            artifact_bundle_hash=request.artifact_bundle.content_hash,
            twin_id=request.twin.twin_id,
            twin_version=request.twin.version_number,
            evaluator=self.configuration,
            findings=ordered_findings,
            summary=summary,
            evidence_gaps=evidence_gaps,
            completed_at=completed_at,
            content_hash=user_twin_evaluation_response_hash(
                evaluation_run_id=request.evaluation_run_id,
                artifact_bundle_id=request.artifact_bundle.id,
                artifact_bundle_hash=request.artifact_bundle.content_hash,
                twin_id=request.twin.twin_id,
                twin_version=request.twin.version_number,
                evaluator=self.configuration,
                findings=ordered_findings,
                summary=summary,
                evidence_gaps=evidence_gaps,
            ),
        )


def user_twin_evaluation_response_hash(
    *,
    evaluation_run_id: UUID,
    artifact_bundle_id: UUID,
    artifact_bundle_hash: str,
    twin_id: UUID,
    twin_version: int,
    evaluator: UserTwinEvaluatorConfiguration,
    findings: tuple[SyntheticFinding, ...],
    summary: str,
    evidence_gaps: tuple[str, ...],
) -> str:
    """Hash the structured evaluator output independently from completion time."""
    return snapshot_content_hash(
        _response_semantic_snapshot(
            evaluation_run_id=evaluation_run_id,
            artifact_bundle_id=artifact_bundle_id,
            artifact_bundle_hash=artifact_bundle_hash,
            twin_id=twin_id,
            twin_version=twin_version,
            evaluator=evaluator,
            findings=findings,
            summary=summary,
            evidence_gaps=evidence_gaps,
        )
    )


def _response_semantic_snapshot(
    *,
    evaluation_run_id: UUID,
    artifact_bundle_id: UUID,
    artifact_bundle_hash: str,
    twin_id: UUID,
    twin_version: int,
    evaluator: UserTwinEvaluatorConfiguration,
    findings: tuple[SyntheticFinding, ...],
    summary: str,
    evidence_gaps: tuple[str, ...],
) -> dict[str, object]:
    return {
        "evaluation_run_id": str(evaluation_run_id),
        "artifact_bundle_id": str(artifact_bundle_id),
        "artifact_bundle_hash": artifact_bundle_hash,
        "twin_id": str(twin_id),
        "twin_version": twin_version,
        "evaluator": evaluator.to_snapshot(),
        "findings": [finding.to_snapshot() for finding in findings],
        "summary": summary,
        "evidence_gaps": list(evidence_gaps),
        "is_simulated_feedback": True,
    }


def canonical_profile_snapshot(payload: Mapping[str, object]) -> tuple[str, str]:
    """Return canonical JSON and digest for tests and provider adapters."""
    snapshot = canonical_json(dict(payload))
    return snapshot, hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
