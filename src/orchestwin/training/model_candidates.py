"""Immutable model-spike candidates with inspectable license and serving evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from orchestwin.projects.requirements_primitives import (
    normalize_optional_text,
    normalize_required_text,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.training.dataset_examples import DatasetLanguage

MODEL_CANDIDATE_SCHEMA_VERSION: Final = 1

_REVISION_PATTERN: Final = re.compile(r"[0-9a-f]{40,64}")
_REPOSITORY_PATTERN: Final = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
)
_CANDIDATE_ID_PATTERN: Final = re.compile(r"model-candidate-[a-z0-9][a-z0-9-]{2,95}")
_MAX_TEXT_LENGTH: Final = 1_000
_MAX_IDENTIFIER_LENGTH: Final = 256
_MAX_URL_LENGTH: Final = 2_048


class ModelCandidateAvailability(StrEnum):
    """Observed availability of one exact model revision."""

    AVAILABLE = "AVAILABLE"
    REQUIRES_ACCESS = "REQUIRES_ACCESS"
    UNAVAILABLE = "UNAVAILABLE"


class ModelLicenseCompatibility(StrEnum):
    """Compatibility of the captured license with the intended public artifacts."""

    COMPATIBLE = "COMPATIBLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INCOMPATIBLE = "INCOMPATIBLE"


@dataclass(frozen=True, slots=True)
class ModelLicenseEvidence:
    """Versioned evidence used to assess model and adapter redistribution rights."""

    license_id: str
    source_url: str
    source_revision: str
    document_sha256: str
    compatibility: ModelLicenseCompatibility
    allows_adapter_redistribution: bool
    allows_weight_redistribution: bool
    attribution_required: bool
    captured_at: datetime
    notes: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.license_id, "model license ID"),
            (self.source_url, "model license source URL"),
        ):
            maximum = _MAX_URL_LENGTH if label.endswith("URL") else _MAX_IDENTIFIER_LENGTH
            if normalize_required_text(value, label=label, maximum_length=maximum) != value:
                raise ValueError(f"{label} must be normalized")
        if not self.source_url.startswith("https://"):
            raise ValueError("model license source URL must use HTTPS")
        _validate_revision(self.source_revision, label="model license source revision")
        validate_sha256(self.document_sha256, label="model license document digest")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("model license evidence timestamp must be timezone-aware")
        normalized_notes = normalize_optional_text(
            self.notes,
            label="model license notes",
            maximum_length=_MAX_TEXT_LENGTH,
        )
        if normalized_notes != self.notes:
            raise ValueError("model license notes must be normalized")
        if (
            self.compatibility is ModelLicenseCompatibility.COMPATIBLE
            and not self.allows_adapter_redistribution
        ):
            raise ValueError("compatible model license evidence must allow adapter redistribution")

    @property
    def content_hash(self) -> str:
        """Return a digest over the exact captured license assessment."""
        return snapshot_content_hash(self.to_snapshot())

    def to_snapshot(self) -> dict[str, object]:
        return {
            "license_id": self.license_id,
            "source_url": self.source_url,
            "source_revision": self.source_revision,
            "document_sha256": self.document_sha256,
            "compatibility": self.compatibility.value,
            "allows_adapter_redistribution": self.allows_adapter_redistribution,
            "allows_weight_redistribution": self.allows_weight_redistribution,
            "attribution_required": self.attribution_required,
            "captured_at": self.captured_at.isoformat(),
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class ModelTokenizerIdentity:
    """Exact tokenizer revision and the files that define its behavior."""

    repository_id: str
    revision: str
    vocabulary_sha256: str
    configuration_sha256: str

    def __post_init__(self) -> None:
        _validate_repository(self.repository_id, label="tokenizer repository")
        _validate_revision(self.revision, label="tokenizer revision")
        validate_sha256(self.vocabulary_sha256, label="tokenizer vocabulary digest")
        validate_sha256(self.configuration_sha256, label="tokenizer configuration digest")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "repository_id": self.repository_id,
            "revision": self.revision,
            "vocabulary_sha256": self.vocabulary_sha256,
            "configuration_sha256": self.configuration_sha256,
        }


@dataclass(frozen=True, slots=True)
class ModelQuantizationPath:
    """Exact quantization path exercised by the feasibility spike."""

    implementation: str
    format_name: str
    bit_width: int
    compute_dtype: str
    double_quantization: bool

    def __post_init__(self) -> None:
        for value, label in (
            (self.implementation, "quantization implementation"),
            (self.format_name, "quantization format"),
            (self.compute_dtype, "quantization compute dtype"),
        ):
            if (
                normalize_required_text(
                    value,
                    label=label,
                    maximum_length=_MAX_IDENTIFIER_LENGTH,
                )
                != value
            ):
                raise ValueError(f"{label} must be normalized")
        if isinstance(self.bit_width, bool) or self.bit_width not in {4, 8, 16}:
            raise ValueError("quantization bit width must be 4, 8, or 16")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "implementation": self.implementation,
            "format_name": self.format_name,
            "bit_width": self.bit_width,
            "compute_dtype": self.compute_dtype,
            "double_quantization": self.double_quantization,
        }


@dataclass(frozen=True, slots=True)
class ModelServingCompatibility:
    """Evidence for one exact local serving runtime and version."""

    runtime_id: str
    runtime_version: str
    compatible: bool
    evidence_reference: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.runtime_id, "serving runtime ID"),
            (self.runtime_version, "serving runtime version"),
            (self.evidence_reference, "serving compatibility evidence reference"),
        ):
            if (
                normalize_required_text(
                    value,
                    label=label,
                    maximum_length=_MAX_IDENTIFIER_LENGTH,
                )
                != value
            ):
                raise ValueError(f"{label} must be normalized")
        validate_sha256(self.evidence_sha256, label="serving compatibility evidence digest")

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.runtime_id, self.runtime_version)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "runtime_id": self.runtime_id,
            "runtime_version": self.runtime_version,
            "compatible": self.compatible,
            "evidence_reference": self.evidence_reference,
            "evidence_sha256": self.evidence_sha256,
        }


@dataclass(frozen=True, slots=True)
class ModelBenchmarkCandidate:
    """One exact, content-addressed model candidate admitted to the spike."""

    candidate_id: str
    repository_id: str
    revision: str
    model_card_sha256: str
    parameter_count_millions: int
    context_limit_tokens: int
    languages: tuple[DatasetLanguage, ...]
    instruct_tuned: bool
    availability: ModelCandidateAvailability
    tokenizer: ModelTokenizerIdentity
    quantization: ModelQuantizationPath
    license_evidence: ModelLicenseEvidence
    serving_compatibility: tuple[ModelServingCompatibility, ...]
    created_at: datetime
    content_hash: str
    schema_version: int = MODEL_CANDIDATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if _CANDIDATE_ID_PATTERN.fullmatch(self.candidate_id) is None:
            raise ValueError("model candidate ID must use model-candidate-<slug>")
        _validate_repository(self.repository_id, label="model repository")
        _validate_revision(self.revision, label="model revision")
        validate_sha256(self.model_card_sha256, label="model card digest")
        validate_positive_integer(
            self.parameter_count_millions,
            label="model parameter count in millions",
        )
        validate_positive_integer(self.context_limit_tokens, label="model context limit")
        if self.schema_version != MODEL_CANDIDATE_SCHEMA_VERSION:
            raise ValueError("unsupported model candidate schema version")
        if not self.languages:
            raise ValueError("model candidate languages must not be empty")
        if len(self.languages) != len(set(self.languages)):
            raise ValueError("model candidate languages must be unique")
        if self.languages != tuple(sorted(self.languages, key=lambda value: value.value)):
            raise ValueError("model candidate languages must use canonical order")
        compatibilities = self.serving_compatibility
        if not compatibilities:
            raise ValueError("model candidate requires serving compatibility evidence")
        if len({item.sort_key for item in compatibilities}) != len(compatibilities):
            raise ValueError("serving compatibility evidence must be unique")
        if compatibilities != tuple(sorted(compatibilities, key=lambda item: item.sort_key)):
            raise ValueError("serving compatibility evidence must use canonical order")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("model candidate timestamp must be timezone-aware")
        validate_sha256(self.content_hash, label="model candidate content hash")
        expected = model_candidate_hash(
            candidate_id=self.candidate_id,
            repository_id=self.repository_id,
            revision=self.revision,
            model_card_sha256=self.model_card_sha256,
            parameter_count_millions=self.parameter_count_millions,
            context_limit_tokens=self.context_limit_tokens,
            languages=self.languages,
            instruct_tuned=self.instruct_tuned,
            availability=self.availability,
            tokenizer=self.tokenizer,
            quantization=self.quantization,
            license_evidence=self.license_evidence,
            serving_compatibility=self.serving_compatibility,
            created_at=self.created_at,
            schema_version=self.schema_version,
        )
        if self.content_hash != expected:
            raise ValueError("model candidate content hash is inconsistent")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "model_card_sha256": self.model_card_sha256,
            "parameter_count_millions": self.parameter_count_millions,
            "context_limit_tokens": self.context_limit_tokens,
            "languages": [language.value for language in self.languages],
            "instruct_tuned": self.instruct_tuned,
            "availability": self.availability.value,
            "tokenizer": self.tokenizer.to_snapshot(),
            "quantization": self.quantization.to_snapshot(),
            "license_evidence": self.license_evidence.to_snapshot(),
            "serving_compatibility": [item.to_snapshot() for item in self.serving_compatibility],
            "created_at": self.created_at.isoformat(),
            "content_hash": self.content_hash,
        }


def create_model_benchmark_candidate(
    *,
    candidate_id: str,
    repository_id: str,
    revision: str,
    model_card_sha256: str,
    parameter_count_millions: int,
    context_limit_tokens: int,
    languages: tuple[DatasetLanguage, ...],
    instruct_tuned: bool,
    availability: ModelCandidateAvailability,
    tokenizer: ModelTokenizerIdentity,
    quantization: ModelQuantizationPath,
    license_evidence: ModelLicenseEvidence,
    serving_compatibility: tuple[ModelServingCompatibility, ...],
    created_at: datetime,
) -> ModelBenchmarkCandidate:
    """Create a canonical candidate and bind it to its complete evidence snapshot."""
    canonical_languages = tuple(sorted(set(languages), key=lambda value: value.value))
    canonical_serving = tuple(sorted(serving_compatibility, key=lambda item: item.sort_key))
    content_hash = model_candidate_hash(
        candidate_id=candidate_id,
        repository_id=repository_id,
        revision=revision,
        model_card_sha256=model_card_sha256,
        parameter_count_millions=parameter_count_millions,
        context_limit_tokens=context_limit_tokens,
        languages=canonical_languages,
        instruct_tuned=instruct_tuned,
        availability=availability,
        tokenizer=tokenizer,
        quantization=quantization,
        license_evidence=license_evidence,
        serving_compatibility=canonical_serving,
        created_at=created_at,
        schema_version=MODEL_CANDIDATE_SCHEMA_VERSION,
    )
    return ModelBenchmarkCandidate(
        candidate_id=candidate_id,
        repository_id=repository_id,
        revision=revision,
        model_card_sha256=model_card_sha256,
        parameter_count_millions=parameter_count_millions,
        context_limit_tokens=context_limit_tokens,
        languages=canonical_languages,
        instruct_tuned=instruct_tuned,
        availability=availability,
        tokenizer=tokenizer,
        quantization=quantization,
        license_evidence=license_evidence,
        serving_compatibility=canonical_serving,
        created_at=created_at,
        content_hash=content_hash,
    )


def model_candidate_hash(
    *,
    candidate_id: str,
    repository_id: str,
    revision: str,
    model_card_sha256: str,
    parameter_count_millions: int,
    context_limit_tokens: int,
    languages: tuple[DatasetLanguage, ...],
    instruct_tuned: bool,
    availability: ModelCandidateAvailability,
    tokenizer: ModelTokenizerIdentity,
    quantization: ModelQuantizationPath,
    license_evidence: ModelLicenseEvidence,
    serving_compatibility: tuple[ModelServingCompatibility, ...],
    created_at: datetime,
    schema_version: int,
) -> str:
    """Hash semantic candidate content independently from storage identity."""
    return snapshot_content_hash(
        {
            "schema_version": schema_version,
            "candidate_id": candidate_id,
            "repository_id": repository_id,
            "revision": revision,
            "model_card_sha256": model_card_sha256,
            "parameter_count_millions": parameter_count_millions,
            "context_limit_tokens": context_limit_tokens,
            "languages": [language.value for language in languages],
            "instruct_tuned": instruct_tuned,
            "availability": availability.value,
            "tokenizer": tokenizer.to_snapshot(),
            "quantization": quantization.to_snapshot(),
            "license_evidence": license_evidence.to_snapshot(),
            "serving_compatibility": [item.to_snapshot() for item in serving_compatibility],
            "created_at": created_at.isoformat(),
        }
    )


def _validate_repository(value: str, *, label: str) -> None:
    if _REPOSITORY_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must use owner/repository format")


def _validate_revision(value: str, *, label: str) -> None:
    if _REVISION_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be an exact lowercase hexadecimal revision")
