"""Provider-independent ports and deterministic adapters for dataset generation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.training.dataset_examples import (
    DatasetExampleSourceKind,
    DatasetLanguage,
    EvaluatorDatasetExample,
)


class DatasetGenerationFailureKind(StrEnum):
    """Typed expected failures at the generation boundary."""

    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    POLICY_REJECTED = "POLICY_REJECTED"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


@dataclass(frozen=True, slots=True)
class DatasetGenerationRequest:
    """Complete deterministic request sent through the generation port."""

    request_id: str
    scenario_family_id: str
    language: DatasetLanguage
    target_count: int
    seed: int
    context_hash: str
    allowed_evidence_refs: tuple[str, ...]
    prompt_version_ref: str
    model_configuration_ref: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.request_id, "dataset generation request ID"),
            (self.scenario_family_id, "dataset generation scenario family ID"),
            (self.prompt_version_ref, "dataset generation prompt version reference"),
            (self.model_configuration_ref, "dataset generation model configuration reference"),
        ):
            normalized = normalize_required_text(
                value,
                label=label,
                maximum_length=512,
            )
            if normalized != value:
                raise ValueError(f"{label} must be normalized")

        validate_positive_integer(
            self.target_count,
            label="dataset generation target count",
        )
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("dataset generation seed must be a non-negative integer")
        validate_sha256(
            self.context_hash,
            label="dataset generation context hash",
        )
        references = normalize_text_items(
            self.allowed_evidence_refs,
            label="dataset generation allowed evidence reference",
            maximum_item_length=512,
            require_items=False,
        )
        canonical_references = tuple(sorted(references))
        if references != self.allowed_evidence_refs or references != canonical_references:
            raise ValueError("allowed evidence references must be normalized and canonical")

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())

    def to_snapshot(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "scenario_family_id": self.scenario_family_id,
            "language": self.language.value,
            "target_count": self.target_count,
            "seed": self.seed,
            "context_hash": self.context_hash,
            "allowed_evidence_refs": list(self.allowed_evidence_refs),
            "prompt_version_ref": self.prompt_version_ref,
            "model_configuration_ref": self.model_configuration_ref,
        }


@dataclass(frozen=True, slots=True)
class DatasetGenerationUsage:
    """Provider-neutral accounting units for one generation request."""

    input_units: int
    output_units: int

    def __post_init__(self) -> None:
        for value, label in (
            (self.input_units, "dataset generation input units"),
            (self.output_units, "dataset generation output units"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{label} must be a non-negative integer")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "input_units": self.input_units,
            "output_units": self.output_units,
        }


@dataclass(frozen=True, slots=True)
class DatasetGenerationMetadata:
    """Inspectable adapter and configuration identity for generated candidates."""

    adapter_id: str
    model_configuration_ref: str
    prompt_version_ref: str
    seed: int
    request_hash: str
    candidate_hashes: tuple[str, ...]
    usage: DatasetGenerationUsage

    def __post_init__(self) -> None:
        for value, label in (
            (self.adapter_id, "dataset generation adapter ID"),
            (self.model_configuration_ref, "generation metadata model reference"),
            (self.prompt_version_ref, "generation metadata prompt reference"),
        ):
            normalized = normalize_required_text(value, label=label, maximum_length=512)
            if normalized != value:
                raise ValueError(f"{label} must be normalized")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("generation metadata seed must be a non-negative integer")
        validate_sha256(self.request_hash, label="generation metadata request hash")
        for candidate_hash in self.candidate_hashes:
            validate_sha256(candidate_hash, label="generation metadata candidate hash")
        if self.candidate_hashes != tuple(sorted(self.candidate_hashes)):
            raise ValueError("generation metadata candidate hashes must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "adapter_id": self.adapter_id,
            "model_configuration_ref": self.model_configuration_ref,
            "prompt_version_ref": self.prompt_version_ref,
            "seed": self.seed,
            "request_hash": self.request_hash,
            "candidate_hashes": list(self.candidate_hashes),
            "usage": self.usage.to_snapshot(),
        }


@dataclass(frozen=True, slots=True)
class DatasetGenerationFailure:
    """Expected boundary failure without hidden retry or fallback."""

    kind: DatasetGenerationFailureKind
    message: str
    retryable: bool

    def __post_init__(self) -> None:
        normalized = normalize_required_text(
            self.message,
            label="dataset generation failure message",
            maximum_length=2_000,
        )
        if normalized != self.message:
            raise ValueError("dataset generation failure message must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "message": self.message,
            "retryable": self.retryable,
        }


@dataclass(frozen=True, slots=True)
class DatasetGenerationResult:
    """Success or typed failure returned by a dataset generator."""

    request_hash: str
    candidates: tuple[EvaluatorDatasetExample, ...]
    metadata: DatasetGenerationMetadata | None
    failure: DatasetGenerationFailure | None

    def __post_init__(self) -> None:
        validate_sha256(self.request_hash, label="dataset generation result request hash")
        successful = self.failure is None
        if successful != (self.metadata is not None):
            raise ValueError("dataset generation result metadata shape is inconsistent")
        if self.failure is not None and self.candidates:
            raise ValueError("failed dataset generation cannot return candidates")
        if self.metadata is not None:
            expected_hashes = tuple(sorted(candidate.content_hash for candidate in self.candidates))
            if self.metadata.request_hash != self.request_hash:
                raise ValueError("generation metadata must belong to the result request")
            if self.metadata.candidate_hashes != expected_hashes:
                raise ValueError("generation metadata candidate hashes are inconsistent")

    @property
    def succeeded(self) -> bool:
        return self.failure is None


class DatasetExampleGenerator(Protocol):
    """Port for generating structured dataset candidates."""

    async def generate(self, request: DatasetGenerationRequest) -> DatasetGenerationResult: ...


class DeterministicDatasetExampleGenerator:
    """Repository-owned fake adapter requiring no network, credentials, or GPU."""

    def __init__(
        self,
        *,
        adapter_id: str,
        candidates: tuple[EvaluatorDatasetExample, ...],
        failures_by_request_id: dict[str, DatasetGenerationFailure] | None = None,
    ) -> None:
        self._adapter_id = normalize_required_text(
            adapter_id,
            label="deterministic dataset generator adapter ID",
            maximum_length=512,
        )
        self._candidates = tuple(sorted(candidates, key=lambda candidate: candidate.example_id))
        self._failures_by_request_id = dict(failures_by_request_id or {})
        self.requests: list[DatasetGenerationRequest] = []

    async def generate(self, request: DatasetGenerationRequest) -> DatasetGenerationResult:
        self.requests.append(request)
        failure = self._failures_by_request_id.get(request.request_id)
        if failure is not None:
            return DatasetGenerationResult(
                request_hash=request.content_hash,
                candidates=(),
                metadata=None,
                failure=failure,
            )

        matching = tuple(
            candidate
            for candidate in self._candidates
            if candidate.scenario_family_id == request.scenario_family_id
            and candidate.language is request.language
        )
        selected = matching[: request.target_count]
        if len(selected) != request.target_count:
            return DatasetGenerationResult(
                request_hash=request.content_hash,
                candidates=(),
                metadata=None,
                failure=DatasetGenerationFailure(
                    DatasetGenerationFailureKind.MODEL_UNAVAILABLE,
                    "The deterministic adapter has no complete response for this request.",
                    False,
                ),
            )

        for candidate in selected:
            if candidate.source_kind is not DatasetExampleSourceKind.SYNTHETIC_GENERATED:
                raise ValueError("deterministic generator candidates must be synthetic")
            if candidate.generation_ref != request.request_id:
                raise ValueError("generated candidate must reference the exact request ID")
            candidate_refs = {item.reference_id for item in candidate.evidence}
            if not candidate_refs.issubset(set(request.allowed_evidence_refs)):
                raise ValueError("generated candidate uses evidence outside the request allowlist")

        candidate_hashes = tuple(sorted(candidate.content_hash for candidate in selected))
        metadata = DatasetGenerationMetadata(
            adapter_id=self._adapter_id,
            model_configuration_ref=request.model_configuration_ref,
            prompt_version_ref=request.prompt_version_ref,
            seed=request.seed,
            request_hash=request.content_hash,
            candidate_hashes=candidate_hashes,
            usage=DatasetGenerationUsage(
                input_units=len(request.allowed_evidence_refs),
                output_units=len(selected),
            ),
        )
        return DatasetGenerationResult(
            request_hash=request.content_hash,
            candidates=selected,
            metadata=metadata,
            failure=None,
        )
