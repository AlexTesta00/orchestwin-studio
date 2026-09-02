"""Deterministic quality filtering with a complete candidate decision ledger."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.training.dataset_examples import (
    DatasetLanguage,
    DatasetUseRestriction,
    EvaluatorDatasetExample,
)
from orchestwin.training.dataset_validation import (
    DatasetValidationReport,
    validate_dataset_example,
)


class DatasetCandidateDecisionStatus(StrEnum):
    """Final quality-filter outcome for one candidate."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DatasetCandidateRejectionCode(StrEnum):
    """Stable top-level reasons for rejecting generated or curated candidates."""

    VALIDATION_FAILED = "VALIDATION_FAILED"
    PROMPT_INJECTION_CONTENT = "PROMPT_INJECTION_CONTENT"
    LANGUAGE_NOT_ALLOWED = "LANGUAGE_NOT_ALLOWED"
    RESERVED_FOR_EVALUATION = "RESERVED_FOR_EVALUATION"
    DUPLICATE_CANDIDATE_ID = "DUPLICATE_CANDIDATE_ID"


@dataclass(frozen=True, slots=True)
class DatasetCandidate:
    """One traceable candidate before quality filtering."""

    candidate_id: str
    example: EvaluatorDatasetExample
    generation_request_hash: str | None
    producer_ref: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.candidate_id, "dataset candidate ID"),
            (self.producer_ref, "dataset candidate producer reference"),
        ):
            normalized = normalize_required_text(value, label=label, maximum_length=512)
            if normalized != value:
                raise ValueError(f"{label} must be normalized")
        if self.generation_request_hash is not None:
            validate_sha256(
                self.generation_request_hash,
                label="dataset candidate generation request hash",
            )

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.candidate_id, self.example.content_hash)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "example_id": self.example.example_id,
            "example_content_hash": self.example.content_hash,
            "generation_request_hash": self.generation_request_hash,
            "producer_ref": self.producer_ref,
        }


@dataclass(frozen=True, slots=True)
class DatasetFilteringPolicy:
    """Versioned language, reservation, and injection quality controls."""

    policy_id: str
    version_number: int
    allowed_languages: tuple[DatasetLanguage, ...]
    reject_reserved_examples: bool
    forbidden_output_phrases: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized_id = normalize_required_text(
            self.policy_id,
            label="dataset filtering policy ID",
            maximum_length=256,
        )
        if normalized_id != self.policy_id:
            raise ValueError("dataset filtering policy ID must be normalized")
        validate_positive_integer(
            self.version_number,
            label="dataset filtering policy version number",
        )
        if not self.allowed_languages:
            raise ValueError("dataset filtering policy languages must not be empty")
        expected_languages = tuple(sorted(set(self.allowed_languages), key=lambda item: item.value))
        if self.allowed_languages != expected_languages:
            raise ValueError("dataset filtering policy languages must be unique and canonical")

        phrases = normalize_text_items(
            self.forbidden_output_phrases,
            label="dataset forbidden output phrase",
            maximum_item_length=256,
            require_items=False,
        )
        canonical_phrases = tuple(sorted(phrase.casefold() for phrase in phrases))
        normalized_phrases = tuple(phrase.casefold() for phrase in self.forbidden_output_phrases)
        if normalized_phrases != canonical_phrases:
            raise ValueError("forbidden output phrases must be lowercase and canonical")

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())

    def to_snapshot(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "version_number": self.version_number,
            "allowed_languages": [language.value for language in self.allowed_languages],
            "reject_reserved_examples": self.reject_reserved_examples,
            "forbidden_output_phrases": list(self.forbidden_output_phrases),
        }


@dataclass(frozen=True, slots=True)
class DatasetCandidateDecision:
    """One accepted or rejected candidate with all supporting evidence."""

    candidate: DatasetCandidate
    status: DatasetCandidateDecisionStatus
    rejection_codes: tuple[DatasetCandidateRejectionCode, ...]
    validation_report: DatasetValidationReport
    content_hash: str

    def __post_init__(self) -> None:
        rejected = self.status is DatasetCandidateDecisionStatus.REJECTED
        if rejected != bool(self.rejection_codes):
            raise ValueError("dataset candidate decision status and rejection codes disagree")
        expected_codes = tuple(sorted(set(self.rejection_codes), key=lambda code: code.value))
        if self.rejection_codes != expected_codes:
            raise ValueError("dataset candidate rejection codes must be unique and canonical")
        validate_sha256(self.content_hash, label="dataset candidate decision content hash")
        expected_hash = snapshot_content_hash(
            {
                "candidate": self.candidate.to_snapshot(),
                "status": self.status.value,
                "rejection_codes": [code.value for code in self.rejection_codes],
                "validation_report_hash": self.validation_report.content_hash,
            }
        )
        if self.content_hash != expected_hash:
            raise ValueError("dataset candidate decision content hash is inconsistent")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.to_snapshot(),
            "status": self.status.value,
            "rejection_codes": [code.value for code in self.rejection_codes],
            "validation_report": self.validation_report.to_snapshot(),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class DatasetFilteringResult:
    """Complete ordered ledger proving that no candidate was silently dropped."""

    policy: DatasetFilteringPolicy
    decisions: tuple[DatasetCandidateDecision, ...]
    content_hash: str

    def __post_init__(self) -> None:
        expected = tuple(sorted(self.decisions, key=lambda item: item.candidate.sort_key))
        if self.decisions != expected:
            raise ValueError("dataset filtering decisions must use canonical order")
        validate_sha256(self.content_hash, label="dataset filtering result content hash")
        expected_hash = snapshot_content_hash(
            {
                "policy_content_hash": self.policy.content_hash,
                "decisions": [decision.to_snapshot() for decision in self.decisions],
            }
        )
        if self.content_hash != expected_hash:
            raise ValueError("dataset filtering result content hash is inconsistent")

    @property
    def accepted(self) -> tuple[EvaluatorDatasetExample, ...]:
        return tuple(
            decision.candidate.example
            for decision in self.decisions
            if decision.status is DatasetCandidateDecisionStatus.ACCEPTED
        )

    @property
    def rejected(self) -> tuple[DatasetCandidateDecision, ...]:
        return tuple(
            decision
            for decision in self.decisions
            if decision.status is DatasetCandidateDecisionStatus.REJECTED
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "policy": self.policy.to_snapshot(),
            "candidate_count": len(self.decisions),
            "accepted_count": len(self.accepted),
            "rejected_count": len(self.rejected),
            "decisions": [decision.to_snapshot() for decision in self.decisions],
            "content_hash": self.content_hash,
        }


def default_dataset_filtering_policy() -> DatasetFilteringPolicy:
    """Return the repository-owned default quality policy."""
    return DatasetFilteringPolicy(
        policy_id="evaluator-dataset-quality",
        version_number=1,
        allowed_languages=(DatasetLanguage.ENGLISH, DatasetLanguage.ITALIAN),
        reject_reserved_examples=True,
        forbidden_output_phrases=(
            "developer message",
            "ignore all previous instructions",
            "ignore previous instructions",
            "reveal the system prompt",
            "system prompt",
        ),
    )


def filter_dataset_candidates(
    candidates: Iterable[DatasetCandidate],
    *,
    policy: DatasetFilteringPolicy,
) -> DatasetFilteringResult:
    """Validate and classify every supplied candidate exactly once."""
    canonical_candidates = tuple(sorted(tuple(candidates), key=lambda item: item.sort_key))
    duplicate_ids = {
        candidate_id
        for candidate_id in {candidate.candidate_id for candidate in canonical_candidates}
        if sum(candidate.candidate_id == candidate_id for candidate in canonical_candidates) > 1
    }

    decisions: list[DatasetCandidateDecision] = []
    for candidate in canonical_candidates:
        report = validate_dataset_example(candidate.example)
        rejection_codes: set[DatasetCandidateRejectionCode] = set()
        if not report.accepted:
            rejection_codes.add(DatasetCandidateRejectionCode.VALIDATION_FAILED)
        if candidate.example.language not in policy.allowed_languages:
            rejection_codes.add(DatasetCandidateRejectionCode.LANGUAGE_NOT_ALLOWED)
        if (
            policy.reject_reserved_examples
            and candidate.example.use_restriction is not DatasetUseRestriction.NONE
        ):
            rejection_codes.add(DatasetCandidateRejectionCode.RESERVED_FOR_EVALUATION)
        if candidate.candidate_id in duplicate_ids:
            rejection_codes.add(DatasetCandidateRejectionCode.DUPLICATE_CANDIDATE_ID)
        if _contains_forbidden_output(candidate.example, policy.forbidden_output_phrases):
            rejection_codes.add(DatasetCandidateRejectionCode.PROMPT_INJECTION_CONTENT)

        canonical_codes = tuple(sorted(rejection_codes, key=lambda code: code.value))
        status = (
            DatasetCandidateDecisionStatus.ACCEPTED
            if not canonical_codes
            else DatasetCandidateDecisionStatus.REJECTED
        )
        decision_hash = snapshot_content_hash(
            {
                "candidate": candidate.to_snapshot(),
                "status": status.value,
                "rejection_codes": [code.value for code in canonical_codes],
                "validation_report_hash": report.content_hash,
            }
        )
        decisions.append(
            DatasetCandidateDecision(
                candidate=candidate,
                status=status,
                rejection_codes=canonical_codes,
                validation_report=report,
                content_hash=decision_hash,
            )
        )

    canonical_decisions = tuple(decisions)
    result_hash = snapshot_content_hash(
        {
            "policy_content_hash": policy.content_hash,
            "decisions": [decision.to_snapshot() for decision in canonical_decisions],
        }
    )
    return DatasetFilteringResult(
        policy=policy,
        decisions=canonical_decisions,
        content_hash=result_hash,
    )


def _contains_forbidden_output(
    example: EvaluatorDatasetExample,
    forbidden_phrases: tuple[str, ...],
) -> bool:
    output_text = " ".join(
        (
            example.expected_output.overall_summary,
            *example.expected_output.evidence_gaps,
            *(
                text
                for finding in example.expected_output.findings
                for text in (
                    finding.summary,
                    finding.rationale,
                    finding.recommended_action,
                )
            ),
        )
    ).casefold()
    return any(phrase in output_text for phrase in forbidden_phrases)
