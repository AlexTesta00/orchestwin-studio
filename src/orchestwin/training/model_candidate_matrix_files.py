"""Strict loading of the frozen live model candidate preflight matrix."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final
from urllib.parse import urlsplit

from orchestwin.projects.requirements_primitives import snapshot_content_hash
from orchestwin.training.benchmark_suite_files import FROZEN_BENCHMARK_SUITE_CONTENT_HASH

MODEL_CANDIDATE_MATRIX_SCHEMA_VERSION: Final = 1
FROZEN_MODEL_CANDIDATE_SOURCE_MANIFEST_PATH: Final = Path(
    "experiments/model-spike/model-candidate-matrix-v1.sources.json"
)
FROZEN_MODEL_CANDIDATE_MATRIX_PATH: Final = Path(
    "experiments/model-spike/model-candidate-matrix-v1.json"
)
FROZEN_MODEL_CANDIDATE_SOURCE_MANIFEST_SHA256: Final = (
    "abb34ec051c833d24b3f311ac4c75af9112620ae6475c9ba911f569578c48c80"
)
FROZEN_MODEL_CANDIDATE_SOURCE_MANIFEST_CONTENT_HASH: Final = (
    "36b6269757b419d454dc673c4b067c42c96401e39e53505080eb2891a5502fe6"
)
FROZEN_MODEL_CANDIDATE_MATRIX_SHA256: Final = (
    "8ceb306ff2a6b6a04087897de15cf1a83e41af620163493af1663599a1ef8101"
)
FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH: Final = (
    "fe95f38476c85967d17c4cc542e5bd4fb8ad96c98965394597232e9f21a3c1ea"
)

_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
_MAX_ARTIFACT_BYTES: Final = 2_000_000
_MATRIX_ID: Final = "user-twin-evaluator-live-model-matrix-v1"
_SOURCE_MANIFEST_ID: Final = "user-twin-evaluator-model-candidate-sources-v1"
_CANDIDATE_ID_PATTERN: Final = re.compile(r"model-candidate-[a-z0-9][a-z0-9-]{2,95}")
_REPOSITORY_PATTERN: Final = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
)
_REVISION_PATTERN: Final = re.compile(r"[0-9a-f]{40,64}")
_IDENTIFIER_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,255}")
_CLAIM_PATTERN: Final = re.compile(r"[A-Z][A-Z0-9_]{2,127}")
_EXPECTED_CANDIDATE_IDS: Final = {
    "model-candidate-granite-3-3-2b-instruct",
    "model-candidate-qwen3-4b-instruct-2507",
    "model-candidate-smollm3-3b",
}
_EXPECTED_SOURCE_IDS: Final = {
    "granite-3-3-2b-instruct-upstream",
    "phi-4-mini-instruct-upstream",
    "qwen3-4b-instruct-2507-upstream",
    "smollm3-3b-upstream",
}
_EXPECTED_SCREENED_OUT_IDS: Final = {"model-candidate-phi-4-mini-instruct"}
_EXPECTED_METHOD_BOUNDARY = (
    "The matrix is a preflight shortlist and does not select a model.",
    "Upstream declarations require local capture and SHA-256 evidence before ranking.",
    "Italian and English protocol quality must be measured with the frozen benchmark suite.",
    "QLoRA, adapter export, adapter load, latency, and memory remain unobserved.",
    "User Twin outputs remain simulated design hypotheses, not empirical user evidence.",
)


class FrozenModelCandidateArtifactError(ValueError):
    """Raised when a frozen candidate artifact is missing, changed, or malformed."""


class CandidateArtifactCaptureStatus(StrEnum):
    """Whether exact upstream bytes have been captured and hashed locally."""

    PENDING_LOCAL_DIGEST = "PENDING_LOCAL_DIGEST"


class CandidateAvailabilityStatus(StrEnum):
    """Availability known before the first authorized download probe."""

    PENDING_DOWNLOAD_PROBE = "PENDING_DOWNLOAD_PROBE"


class CandidateLicenseReviewStatus(StrEnum):
    """License status before exact local evidence and owner review."""

    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class CandidateServingEvidenceStatus(StrEnum):
    """Serving evidence state before a local endpoint is exercised."""

    DOCUMENTED_NOT_LOCALLY_OBSERVED = "DOCUMENTED_NOT_LOCALLY_OBSERVED"


class CandidateChatTemplateControlMode(StrEnum):
    """Explicit model-family control used to keep the spike in non-thinking mode."""

    DEFAULT_NON_THINKING = "DEFAULT_NON_THINKING"
    TEMPLATE_ARGUMENT_FALSE = "TEMPLATE_ARGUMENT_FALSE"


class CandidateMatrixDecisionStatus(StrEnum):
    """Governance state of the frozen preflight shortlist."""

    NO_MODEL_SELECTED = "NO_MODEL_SELECTED"


class CandidateMatrixEvidenceStatus(StrEnum):
    """Evidence maturity before download, inference, training, and serving probes."""

    PREFLIGHT_ONLY = "PREFLIGHT_ONLY"


class ScreenedOutModelReason(StrEnum):
    """Stable hard constraints applied before expensive local probes."""

    REMOTE_CODE_REQUIRED = "REMOTE_CODE_REQUIRED"


@dataclass(frozen=True, slots=True)
class FrozenCandidateSourceReference:
    """Exact upstream reference whose bytes still require local capture."""

    source_id: str
    candidate_id: str
    repository_id: str
    revision: str
    repository_tree_reference: str
    model_card_reference: str
    license_reference: str
    declared_claims: tuple[str, ...]
    capture_status: CandidateArtifactCaptureStatus

    def __post_init__(self) -> None:
        _validate_identifier(self.source_id, label="candidate source ID")
        _validate_candidate_id(self.candidate_id)
        _validate_repository(self.repository_id, label="candidate source repository")
        _validate_revision(self.revision, label="candidate source revision")
        for value, label in (
            (self.repository_tree_reference, "candidate repository tree reference"),
            (self.model_card_reference, "candidate model-card reference"),
            (self.license_reference, "candidate license reference"),
        ):
            _validate_pinned_hugging_face_reference(value, revision=self.revision, label=label)
        if not self.declared_claims:
            raise ValueError("candidate source claims must not be empty")
        if self.declared_claims != tuple(sorted(set(self.declared_claims))):
            raise ValueError("candidate source claims must use canonical order")
        if any(_CLAIM_PATTERN.fullmatch(value) is None for value in self.declared_claims):
            raise ValueError("candidate source claims must use uppercase identifiers")

    @property
    def sort_key(self) -> str:
        return self.source_id

    def to_snapshot(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "candidate_id": self.candidate_id,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "repository_tree_reference": self.repository_tree_reference,
            "model_card_reference": self.model_card_reference,
            "license_reference": self.license_reference,
            "declared_claims": list(self.declared_claims),
            "capture_status": self.capture_status.value,
        }


@dataclass(frozen=True, slots=True)
class FrozenCandidateSourceManifest:
    """Content-addressed upstream references supporting the preflight matrix."""

    manifest_id: str
    captured_at: datetime
    sources: tuple[FrozenCandidateSourceReference, ...]
    methodological_constraints: tuple[str, ...]
    content_hash: str
    schema_version: int = MODEL_CANDIDATE_MATRIX_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_CANDIDATE_MATRIX_SCHEMA_VERSION:
            raise ValueError("unsupported candidate source manifest schema")
        if self.manifest_id != _SOURCE_MANIFEST_ID:
            raise ValueError("unexpected candidate source manifest identity")
        _validate_aware_datetime(self.captured_at, label="candidate source capture timestamp")
        if self.sources != tuple(sorted(self.sources, key=lambda item: item.sort_key)):
            raise ValueError("candidate sources must use canonical order")
        if {item.source_id for item in self.sources} != _EXPECTED_SOURCE_IDS:
            raise ValueError("candidate source identities changed")
        if len({item.candidate_id for item in self.sources}) != len(self.sources):
            raise ValueError("candidate source targets must be unique")
        if self.methodological_constraints != _EXPECTED_METHOD_BOUNDARY:
            raise ValueError("candidate source methodological constraints changed")
        _validate_sha256(self.content_hash, label="candidate source manifest hash")
        if self.content_hash != snapshot_content_hash(self._semantic_snapshot()):
            raise ValueError("candidate source manifest content hash is inconsistent")

    def _semantic_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "captured_at": self.captured_at.isoformat(),
            "sources": [item.to_snapshot() for item in self.sources],
            "methodological_constraints": list(self.methodological_constraints),
        }

    def to_snapshot(self) -> dict[str, object]:
        return {**self._semantic_snapshot(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class FrozenModelSelectionConstraints:
    """Hard preflight constraints applied before any model is measured."""

    minimum_parameter_count_millions: int
    maximum_parameter_count_millions: int
    benchmark_languages: tuple[str, ...]
    instruct_tuned_required: bool
    declared_permissive_license_required: bool
    load_in_4bit_required: bool
    trust_remote_code_allowed: bool
    maximum_local_gpu_memory_mb: int
    required_serving_runtime_id: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.minimum_parameter_count_millions, "minimum model parameter count"),
            (self.maximum_parameter_count_millions, "maximum model parameter count"),
            (self.maximum_local_gpu_memory_mb, "maximum local GPU memory"),
        ):
            _validate_positive_integer(value, label=label)
        if self.minimum_parameter_count_millions != 2_000:
            raise ValueError("frozen minimum parameter count changed")
        if self.maximum_parameter_count_millions != 4_000:
            raise ValueError("frozen maximum parameter count changed")
        if self.maximum_parameter_count_millions < self.minimum_parameter_count_millions:
            raise ValueError("maximum parameter count must not be below the minimum")
        if self.benchmark_languages != ("en", "it"):
            raise ValueError("frozen candidate matrix must benchmark English and Italian")
        if not self.instruct_tuned_required:
            raise ValueError("frozen candidate matrix requires instruct-tuned models")
        if not self.declared_permissive_license_required:
            raise ValueError("frozen candidate matrix requires a declared permissive license")
        if not self.load_in_4bit_required:
            raise ValueError("frozen candidate matrix requires four-bit loading")
        if self.trust_remote_code_allowed:
            raise ValueError("frozen candidate matrix forbids remote code execution")
        if self.maximum_local_gpu_memory_mb != 8_192:
            raise ValueError("frozen candidate matrix targets the observed 8 GB GPU")
        if self.required_serving_runtime_id != "openai-compatible-local":
            raise ValueError("frozen candidate matrix serving requirement changed")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "minimum_parameter_count_millions": self.minimum_parameter_count_millions,
            "maximum_parameter_count_millions": self.maximum_parameter_count_millions,
            "benchmark_languages": list(self.benchmark_languages),
            "instruct_tuned_required": self.instruct_tuned_required,
            "declared_permissive_license_required": (self.declared_permissive_license_required),
            "load_in_4bit_required": self.load_in_4bit_required,
            "trust_remote_code_allowed": self.trust_remote_code_allowed,
            "maximum_local_gpu_memory_mb": self.maximum_local_gpu_memory_mb,
            "required_serving_runtime_id": self.required_serving_runtime_id,
        }


@dataclass(frozen=True, slots=True)
class FrozenModelSpikeGeneration:
    """One identical deterministic generation configuration for every candidate."""

    max_sequence_length: int
    max_output_tokens: int
    repetitions: int
    seed: int
    load_in_4bit: bool
    trust_remote_code: bool

    def __post_init__(self) -> None:
        expected = (4_096, 1_024, 1, 20_260_904, True, False)
        observed = (
            self.max_sequence_length,
            self.max_output_tokens,
            self.repetitions,
            self.seed,
            self.load_in_4bit,
            self.trust_remote_code,
        )
        if observed != expected:
            raise ValueError("frozen model-spike generation settings changed")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "max_sequence_length": self.max_sequence_length,
            "max_output_tokens": self.max_output_tokens,
            "repetitions": self.repetitions,
            "seed": self.seed,
            "load_in_4bit": self.load_in_4bit,
            "trust_remote_code": self.trust_remote_code,
        }


@dataclass(frozen=True, slots=True)
class CandidateLicensePreflight:
    """Upstream license declaration that is not yet final license evidence."""

    declared_license_id: str
    review_status: CandidateLicenseReviewStatus
    allows_adapter_redistribution: bool | None
    allows_weight_redistribution: bool | None
    attribution_required: bool | None
    artifact_path: str
    capture_status: CandidateArtifactCaptureStatus
    source_id: str

    def __post_init__(self) -> None:
        if self.declared_license_id != "Apache-2.0":
            raise ValueError("shortlisted candidates must declare Apache-2.0")
        if any(
            value is not None
            for value in (
                self.allows_adapter_redistribution,
                self.allows_weight_redistribution,
                self.attribution_required,
            )
        ):
            raise ValueError("redistribution conclusions require captured license evidence")
        _validate_relative_path(self.artifact_path, label="candidate license artifact path")
        _validate_identifier(self.source_id, label="candidate license source ID")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "declared_license_id": self.declared_license_id,
            "review_status": self.review_status.value,
            "allows_adapter_redistribution": self.allows_adapter_redistribution,
            "allows_weight_redistribution": self.allows_weight_redistribution,
            "attribution_required": self.attribution_required,
            "artifact_path": self.artifact_path,
            "capture_status": self.capture_status.value,
            "source_id": self.source_id,
        }


@dataclass(frozen=True, slots=True)
class CandidateArtifactCapturePlan:
    """Small exact files that must be hashed before final candidate construction."""

    model_card_path: str
    tokenizer_vocabulary_paths: tuple[str, ...]
    tokenizer_configuration_path: str
    capture_status: CandidateArtifactCaptureStatus

    def __post_init__(self) -> None:
        _validate_relative_path(self.model_card_path, label="candidate model-card path")
        _validate_relative_path(
            self.tokenizer_configuration_path,
            label="candidate tokenizer configuration path",
        )
        if not self.tokenizer_vocabulary_paths:
            raise ValueError("candidate tokenizer vocabulary paths must not be empty")
        if self.tokenizer_vocabulary_paths != tuple(sorted(set(self.tokenizer_vocabulary_paths))):
            raise ValueError("candidate tokenizer vocabulary paths must use canonical order")
        for value in self.tokenizer_vocabulary_paths:
            _validate_relative_path(value, label="candidate tokenizer vocabulary path")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "model_card_path": self.model_card_path,
            "tokenizer_vocabulary_paths": list(self.tokenizer_vocabulary_paths),
            "tokenizer_configuration_path": self.tokenizer_configuration_path,
            "capture_status": self.capture_status.value,
        }


@dataclass(frozen=True, slots=True)
class CandidateChatTemplateControl:
    """Model-family-specific control needed for comparable non-thinking outputs."""

    mode: CandidateChatTemplateControlMode
    argument_name: str | None
    argument_value: bool | None
    system_prefix: str | None

    def __post_init__(self) -> None:
        if self.mode is CandidateChatTemplateControlMode.DEFAULT_NON_THINKING:
            if any(
                value is not None
                for value in (self.argument_name, self.argument_value, self.system_prefix)
            ):
                raise ValueError("default non-thinking control cannot carry template overrides")
            return
        if (
            self.argument_name not in {"enable_thinking", "thinking"}
            or self.argument_value is not False
            or self.system_prefix is not None
        ):
            raise ValueError("template-argument control must pass one approved false flag")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "argument_name": self.argument_name,
            "argument_value": self.argument_value,
            "system_prefix": self.system_prefix,
        }


@dataclass(frozen=True, slots=True)
class CandidateServingPreflight:
    """Documented serving path that still requires a local endpoint probe."""

    runtime_id: str
    runtime_family: str
    status: CandidateServingEvidenceStatus
    source_id: str

    def __post_init__(self) -> None:
        if self.runtime_id != "openai-compatible-local":
            raise ValueError("candidate serving runtime ID changed")
        if self.runtime_family != "vllm":
            raise ValueError("candidate serving runtime family changed")
        _validate_identifier(self.source_id, label="candidate serving source ID")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "runtime_id": self.runtime_id,
            "runtime_family": self.runtime_family,
            "status": self.status.value,
            "source_id": self.source_id,
        }


@dataclass(frozen=True, slots=True)
class FrozenModelCandidatePreflight:
    """One exact-revision candidate awaiting local evidence capture and measurement."""

    candidate_id: str
    family_id: str
    repository_id: str
    revision: str
    tokenizer_repository_id: str
    tokenizer_revision: str
    declared_parameter_count_millions: int
    declared_context_limit_tokens: int
    benchmark_languages: tuple[str, ...]
    instruct_tuned: bool
    availability_status: CandidateAvailabilityStatus
    license: CandidateLicensePreflight
    artifact_capture: CandidateArtifactCapturePlan
    chat_template_control: CandidateChatTemplateControl
    serving: CandidateServingPreflight
    source_id: str

    def __post_init__(self) -> None:
        _validate_candidate_id(self.candidate_id)
        _validate_identifier(self.family_id, label="candidate family ID")
        _validate_repository(self.repository_id, label="candidate repository")
        _validate_revision(self.revision, label="candidate revision")
        _validate_repository(self.tokenizer_repository_id, label="candidate tokenizer repository")
        _validate_revision(self.tokenizer_revision, label="candidate tokenizer revision")
        _validate_positive_integer(
            self.declared_parameter_count_millions,
            label="declared candidate parameter count",
        )
        _validate_positive_integer(
            self.declared_context_limit_tokens,
            label="declared candidate context limit",
        )
        if self.benchmark_languages != ("en", "it"):
            raise ValueError("every candidate must be evaluated in English and Italian")
        if not self.instruct_tuned:
            raise ValueError("shortlisted model candidates must be instruct-tuned")
        if self.tokenizer_repository_id != self.repository_id:
            raise ValueError("matrix v1 requires model-bundled tokenizers")
        if self.tokenizer_revision != self.revision:
            raise ValueError("matrix v1 requires matching model and tokenizer revisions")
        _validate_identifier(self.source_id, label="candidate source ID")
        if {self.license.source_id, self.serving.source_id} != {self.source_id}:
            raise ValueError("candidate evidence references must use one exact source")

    @property
    def sort_key(self) -> str:
        return self.candidate_id

    def to_snapshot(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "family_id": self.family_id,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "tokenizer_repository_id": self.tokenizer_repository_id,
            "tokenizer_revision": self.tokenizer_revision,
            "declared_parameter_count_millions": self.declared_parameter_count_millions,
            "declared_context_limit_tokens": self.declared_context_limit_tokens,
            "benchmark_languages": list(self.benchmark_languages),
            "instruct_tuned": self.instruct_tuned,
            "availability_status": self.availability_status.value,
            "license": self.license.to_snapshot(),
            "artifact_capture": self.artifact_capture.to_snapshot(),
            "chat_template_control": self.chat_template_control.to_snapshot(),
            "serving": self.serving.to_snapshot(),
            "source_id": self.source_id,
        }


@dataclass(frozen=True, slots=True)
class FrozenScreenedOutModelCandidate:
    """One candidate rejected before expensive probing by an explicit hard constraint."""

    candidate_id: str
    repository_id: str
    revision: str
    reason_code: ScreenedOutModelReason
    reason: str
    source_id: str

    def __post_init__(self) -> None:
        _validate_candidate_id(self.candidate_id)
        _validate_repository(self.repository_id, label="screened-out repository")
        _validate_revision(self.revision, label="screened-out revision")
        _validate_normalized_text(self.reason, label="screened-out reason")
        _validate_identifier(self.source_id, label="screened-out source ID")

    @property
    def sort_key(self) -> str:
        return self.candidate_id

    def to_snapshot(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "reason_code": self.reason_code.value,
            "reason": self.reason,
            "source_id": self.source_id,
        }


@dataclass(frozen=True, slots=True)
class FrozenModelCandidateMatrix:
    """Content-addressed, unranked candidate matrix preceding every live run."""

    matrix_id: str
    frozen_at: datetime
    benchmark_suite_content_hash: str
    source_manifest_sha256: str
    decision_status: CandidateMatrixDecisionStatus
    evidence_status: CandidateMatrixEvidenceStatus
    selection_constraints: FrozenModelSelectionConstraints
    generation: FrozenModelSpikeGeneration
    candidates: tuple[FrozenModelCandidatePreflight, ...]
    screened_out: tuple[FrozenScreenedOutModelCandidate, ...]
    content_hash: str
    schema_version: int = MODEL_CANDIDATE_MATRIX_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_CANDIDATE_MATRIX_SCHEMA_VERSION:
            raise ValueError("unsupported model candidate matrix schema")
        if self.matrix_id != _MATRIX_ID:
            raise ValueError("unexpected model candidate matrix identity")
        _validate_aware_datetime(self.frozen_at, label="model candidate matrix timestamp")
        if self.benchmark_suite_content_hash != FROZEN_BENCHMARK_SUITE_CONTENT_HASH:
            raise ValueError("model candidate matrix benchmark identity changed")
        _validate_sha256(self.source_manifest_sha256, label="candidate source manifest digest")
        if self.candidates != tuple(sorted(self.candidates, key=lambda item: item.sort_key)):
            raise ValueError("model candidates must use canonical order")
        if {item.candidate_id for item in self.candidates} != _EXPECTED_CANDIDATE_IDS:
            raise ValueError("frozen model candidate identities changed")
        if len({item.family_id for item in self.candidates}) != len(self.candidates):
            raise ValueError("frozen matrix must preserve model-family diversity")
        if len({item.repository_id for item in self.candidates}) != len(self.candidates):
            raise ValueError("frozen matrix candidate repositories must be unique")
        if self.screened_out != tuple(sorted(self.screened_out, key=lambda item: item.sort_key)):
            raise ValueError("screened-out candidates must use canonical order")
        if {item.candidate_id for item in self.screened_out} != _EXPECTED_SCREENED_OUT_IDS:
            raise ValueError("screened-out candidate identities changed")
        for candidate in self.candidates:
            if not (
                self.selection_constraints.minimum_parameter_count_millions
                <= candidate.declared_parameter_count_millions
                <= self.selection_constraints.maximum_parameter_count_millions
            ):
                raise ValueError("candidate parameter count is outside the frozen range")
            if candidate.benchmark_languages != self.selection_constraints.benchmark_languages:
                raise ValueError("candidate benchmark languages differ from matrix constraints")
            if candidate.serving.runtime_id != (
                self.selection_constraints.required_serving_runtime_id
            ):
                raise ValueError("candidate serving path differs from matrix constraints")
        _validate_sha256(self.content_hash, label="model candidate matrix content hash")
        if self.content_hash != snapshot_content_hash(self._semantic_snapshot()):
            raise ValueError("model candidate matrix content hash is inconsistent")

    def _semantic_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "matrix_id": self.matrix_id,
            "frozen_at": self.frozen_at.isoformat(),
            "benchmark_suite_content_hash": self.benchmark_suite_content_hash,
            "source_manifest_sha256": self.source_manifest_sha256,
            "decision_status": self.decision_status.value,
            "evidence_status": self.evidence_status.value,
            "selection_constraints": self.selection_constraints.to_snapshot(),
            "generation": self.generation.to_snapshot(),
            "candidates": [item.to_snapshot() for item in self.candidates],
            "screened_out": [item.to_snapshot() for item in self.screened_out],
        }

    def to_snapshot(self) -> dict[str, object]:
        return {**self._semantic_snapshot(), "content_hash": self.content_hash}

    def candidate(self, candidate_id: str) -> FrozenModelCandidatePreflight:
        return next(item for item in self.candidates if item.candidate_id == candidate_id)


def load_frozen_model_candidate_source_manifest(
    repository_root: Path | None = None,
) -> FrozenCandidateSourceManifest:
    """Load and verify the exact upstream-reference manifest used for matrix v1."""
    root = _REPOSITORY_ROOT if repository_root is None else repository_root.resolve()
    payload, digest = _load_json_artifact(
        root / FROZEN_MODEL_CANDIDATE_SOURCE_MANIFEST_PATH,
        label="model candidate source manifest",
    )
    if digest != FROZEN_MODEL_CANDIDATE_SOURCE_MANIFEST_SHA256:
        raise FrozenModelCandidateArtifactError("model candidate source manifest digest changed")
    manifest = _parse_source_manifest(payload)
    if manifest.content_hash != FROZEN_MODEL_CANDIDATE_SOURCE_MANIFEST_CONTENT_HASH:
        raise FrozenModelCandidateArtifactError(
            "model candidate source manifest content identity changed"
        )
    if manifest.to_snapshot() != payload:
        raise FrozenModelCandidateArtifactError(
            "model candidate source manifest is not a canonical snapshot"
        )
    return manifest


def load_frozen_model_candidate_matrix(
    repository_root: Path | None = None,
) -> FrozenModelCandidateMatrix:
    """Load and cross-check the exact unranked matrix used for the live spike."""
    root = _REPOSITORY_ROOT if repository_root is None else repository_root.resolve()
    manifest = load_frozen_model_candidate_source_manifest(root)
    payload, digest = _load_json_artifact(
        root / FROZEN_MODEL_CANDIDATE_MATRIX_PATH,
        label="model candidate matrix",
    )
    if digest != FROZEN_MODEL_CANDIDATE_MATRIX_SHA256:
        raise FrozenModelCandidateArtifactError("model candidate matrix digest changed")
    matrix = _parse_matrix(payload)
    if matrix.source_manifest_sha256 != FROZEN_MODEL_CANDIDATE_SOURCE_MANIFEST_SHA256:
        raise FrozenModelCandidateArtifactError(
            "model candidate matrix references a different source manifest"
        )
    if matrix.content_hash != FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH:
        raise FrozenModelCandidateArtifactError("model candidate matrix content identity changed")
    _validate_source_links(matrix, manifest)
    if matrix.to_snapshot() != payload:
        raise FrozenModelCandidateArtifactError(
            "model candidate matrix is not a canonical snapshot"
        )
    return matrix


def model_candidate_artifact_sha256(path: Path) -> str:
    """Calculate the file identity used by frozen candidate artifacts."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_source_manifest(payload: Mapping[str, object]) -> FrozenCandidateSourceManifest:
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "manifest_id",
            "captured_at",
            "sources",
            "methodological_constraints",
            "content_hash",
        },
        label="model candidate source manifest",
    )
    sources = tuple(
        sorted(
            (
                _parse_source(item, index=index)
                for index, item in enumerate(_required_list(payload, "sources"))
            ),
            key=lambda item: item.sort_key,
        )
    )
    return FrozenCandidateSourceManifest(
        schema_version=_required_integer(payload, "schema_version"),
        manifest_id=_required_string(payload, "manifest_id"),
        captured_at=_required_datetime(payload, "captured_at"),
        sources=sources,
        methodological_constraints=_string_tuple(payload, "methodological_constraints"),
        content_hash=_required_string(payload, "content_hash"),
    )


def _parse_source(value: object, *, index: int) -> FrozenCandidateSourceReference:
    payload = _required_mapping(value, label=f"model candidate source {index}")
    _require_exact_keys(
        payload,
        {
            "source_id",
            "candidate_id",
            "repository_id",
            "revision",
            "repository_tree_reference",
            "model_card_reference",
            "license_reference",
            "declared_claims",
            "capture_status",
        },
        label=f"model candidate source {index}",
    )
    return FrozenCandidateSourceReference(
        source_id=_required_string(payload, "source_id"),
        candidate_id=_required_string(payload, "candidate_id"),
        repository_id=_required_string(payload, "repository_id"),
        revision=_required_string(payload, "revision"),
        repository_tree_reference=_required_string(payload, "repository_tree_reference"),
        model_card_reference=_required_string(payload, "model_card_reference"),
        license_reference=_required_string(payload, "license_reference"),
        declared_claims=_string_tuple(payload, "declared_claims"),
        capture_status=CandidateArtifactCaptureStatus(_required_string(payload, "capture_status")),
    )


def _parse_matrix(payload: Mapping[str, object]) -> FrozenModelCandidateMatrix:
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "matrix_id",
            "frozen_at",
            "benchmark_suite_content_hash",
            "source_manifest_sha256",
            "decision_status",
            "evidence_status",
            "selection_constraints",
            "generation",
            "candidates",
            "screened_out",
            "content_hash",
        },
        label="model candidate matrix",
    )
    candidates = tuple(
        sorted(
            (
                _parse_candidate(item, index=index)
                for index, item in enumerate(_required_list(payload, "candidates"))
            ),
            key=lambda item: item.sort_key,
        )
    )
    screened_out = tuple(
        sorted(
            (
                _parse_screened_out(item, index=index)
                for index, item in enumerate(_required_list(payload, "screened_out"))
            ),
            key=lambda item: item.sort_key,
        )
    )
    return FrozenModelCandidateMatrix(
        schema_version=_required_integer(payload, "schema_version"),
        matrix_id=_required_string(payload, "matrix_id"),
        frozen_at=_required_datetime(payload, "frozen_at"),
        benchmark_suite_content_hash=_required_string(payload, "benchmark_suite_content_hash"),
        source_manifest_sha256=_required_string(payload, "source_manifest_sha256"),
        decision_status=CandidateMatrixDecisionStatus(_required_string(payload, "decision_status")),
        evidence_status=CandidateMatrixEvidenceStatus(_required_string(payload, "evidence_status")),
        selection_constraints=_parse_constraints(
            _required_mapping(
                payload.get("selection_constraints"),
                label="model candidate selection constraints",
            )
        ),
        generation=_parse_generation(
            _required_mapping(payload.get("generation"), label="model spike generation")
        ),
        candidates=candidates,
        screened_out=screened_out,
        content_hash=_required_string(payload, "content_hash"),
    )


def _parse_constraints(payload: Mapping[str, object]) -> FrozenModelSelectionConstraints:
    _require_exact_keys(
        payload,
        {
            "minimum_parameter_count_millions",
            "maximum_parameter_count_millions",
            "benchmark_languages",
            "instruct_tuned_required",
            "declared_permissive_license_required",
            "load_in_4bit_required",
            "trust_remote_code_allowed",
            "maximum_local_gpu_memory_mb",
            "required_serving_runtime_id",
        },
        label="model candidate selection constraints",
    )
    return FrozenModelSelectionConstraints(
        minimum_parameter_count_millions=_required_integer(
            payload, "minimum_parameter_count_millions"
        ),
        maximum_parameter_count_millions=_required_integer(
            payload, "maximum_parameter_count_millions"
        ),
        benchmark_languages=_string_tuple(payload, "benchmark_languages"),
        instruct_tuned_required=_required_boolean(payload, "instruct_tuned_required"),
        declared_permissive_license_required=_required_boolean(
            payload, "declared_permissive_license_required"
        ),
        load_in_4bit_required=_required_boolean(payload, "load_in_4bit_required"),
        trust_remote_code_allowed=_required_boolean(payload, "trust_remote_code_allowed"),
        maximum_local_gpu_memory_mb=_required_integer(payload, "maximum_local_gpu_memory_mb"),
        required_serving_runtime_id=_required_string(payload, "required_serving_runtime_id"),
    )


def _parse_generation(payload: Mapping[str, object]) -> FrozenModelSpikeGeneration:
    _require_exact_keys(
        payload,
        {
            "max_sequence_length",
            "max_output_tokens",
            "repetitions",
            "seed",
            "load_in_4bit",
            "trust_remote_code",
        },
        label="model spike generation",
    )
    return FrozenModelSpikeGeneration(
        max_sequence_length=_required_integer(payload, "max_sequence_length"),
        max_output_tokens=_required_integer(payload, "max_output_tokens"),
        repetitions=_required_integer(payload, "repetitions"),
        seed=_required_integer(payload, "seed"),
        load_in_4bit=_required_boolean(payload, "load_in_4bit"),
        trust_remote_code=_required_boolean(payload, "trust_remote_code"),
    )


def _parse_candidate(value: object, *, index: int) -> FrozenModelCandidatePreflight:
    payload = _required_mapping(value, label=f"model candidate {index}")
    _require_exact_keys(
        payload,
        {
            "candidate_id",
            "family_id",
            "repository_id",
            "revision",
            "tokenizer_repository_id",
            "tokenizer_revision",
            "declared_parameter_count_millions",
            "declared_context_limit_tokens",
            "benchmark_languages",
            "instruct_tuned",
            "availability_status",
            "license",
            "artifact_capture",
            "chat_template_control",
            "serving",
            "source_id",
        },
        label=f"model candidate {index}",
    )
    return FrozenModelCandidatePreflight(
        candidate_id=_required_string(payload, "candidate_id"),
        family_id=_required_string(payload, "family_id"),
        repository_id=_required_string(payload, "repository_id"),
        revision=_required_string(payload, "revision"),
        tokenizer_repository_id=_required_string(payload, "tokenizer_repository_id"),
        tokenizer_revision=_required_string(payload, "tokenizer_revision"),
        declared_parameter_count_millions=_required_integer(
            payload, "declared_parameter_count_millions"
        ),
        declared_context_limit_tokens=_required_integer(payload, "declared_context_limit_tokens"),
        benchmark_languages=_string_tuple(payload, "benchmark_languages"),
        instruct_tuned=_required_boolean(payload, "instruct_tuned"),
        availability_status=CandidateAvailabilityStatus(
            _required_string(payload, "availability_status")
        ),
        license=_parse_license(
            _required_mapping(payload.get("license"), label=f"model candidate {index} license")
        ),
        artifact_capture=_parse_artifact_capture(
            _required_mapping(
                payload.get("artifact_capture"),
                label=f"model candidate {index} artifact capture",
            )
        ),
        chat_template_control=_parse_chat_template_control(
            _required_mapping(
                payload.get("chat_template_control"),
                label=f"model candidate {index} chat-template control",
            )
        ),
        serving=_parse_serving(
            _required_mapping(
                payload.get("serving"),
                label=f"model candidate {index} serving evidence",
            )
        ),
        source_id=_required_string(payload, "source_id"),
    )


def _parse_license(payload: Mapping[str, object]) -> CandidateLicensePreflight:
    _require_exact_keys(
        payload,
        {
            "declared_license_id",
            "review_status",
            "allows_adapter_redistribution",
            "allows_weight_redistribution",
            "attribution_required",
            "artifact_path",
            "capture_status",
            "source_id",
        },
        label="candidate license preflight",
    )
    return CandidateLicensePreflight(
        declared_license_id=_required_string(payload, "declared_license_id"),
        review_status=CandidateLicenseReviewStatus(_required_string(payload, "review_status")),
        allows_adapter_redistribution=_optional_boolean(payload, "allows_adapter_redistribution"),
        allows_weight_redistribution=_optional_boolean(payload, "allows_weight_redistribution"),
        attribution_required=_optional_boolean(payload, "attribution_required"),
        artifact_path=_required_string(payload, "artifact_path"),
        capture_status=CandidateArtifactCaptureStatus(_required_string(payload, "capture_status")),
        source_id=_required_string(payload, "source_id"),
    )


def _parse_artifact_capture(payload: Mapping[str, object]) -> CandidateArtifactCapturePlan:
    _require_exact_keys(
        payload,
        {
            "model_card_path",
            "tokenizer_vocabulary_paths",
            "tokenizer_configuration_path",
            "capture_status",
        },
        label="candidate artifact capture plan",
    )
    return CandidateArtifactCapturePlan(
        model_card_path=_required_string(payload, "model_card_path"),
        tokenizer_vocabulary_paths=_string_tuple(payload, "tokenizer_vocabulary_paths"),
        tokenizer_configuration_path=_required_string(payload, "tokenizer_configuration_path"),
        capture_status=CandidateArtifactCaptureStatus(_required_string(payload, "capture_status")),
    )


def _parse_chat_template_control(
    payload: Mapping[str, object],
) -> CandidateChatTemplateControl:
    _require_exact_keys(
        payload,
        {"mode", "argument_name", "argument_value", "system_prefix"},
        label="candidate chat-template control",
    )
    return CandidateChatTemplateControl(
        mode=CandidateChatTemplateControlMode(_required_string(payload, "mode")),
        argument_name=_optional_string(payload, "argument_name"),
        argument_value=_optional_boolean(payload, "argument_value"),
        system_prefix=_optional_string(payload, "system_prefix"),
    )


def _parse_serving(payload: Mapping[str, object]) -> CandidateServingPreflight:
    _require_exact_keys(
        payload,
        {"runtime_id", "runtime_family", "status", "source_id"},
        label="candidate serving preflight",
    )
    return CandidateServingPreflight(
        runtime_id=_required_string(payload, "runtime_id"),
        runtime_family=_required_string(payload, "runtime_family"),
        status=CandidateServingEvidenceStatus(_required_string(payload, "status")),
        source_id=_required_string(payload, "source_id"),
    )


def _parse_screened_out(value: object, *, index: int) -> FrozenScreenedOutModelCandidate:
    payload = _required_mapping(value, label=f"screened-out model candidate {index}")
    _require_exact_keys(
        payload,
        {"candidate_id", "repository_id", "revision", "reason_code", "reason", "source_id"},
        label=f"screened-out model candidate {index}",
    )
    return FrozenScreenedOutModelCandidate(
        candidate_id=_required_string(payload, "candidate_id"),
        repository_id=_required_string(payload, "repository_id"),
        revision=_required_string(payload, "revision"),
        reason_code=ScreenedOutModelReason(_required_string(payload, "reason_code")),
        reason=_required_string(payload, "reason"),
        source_id=_required_string(payload, "source_id"),
    )


def _validate_source_links(
    matrix: FrozenModelCandidateMatrix,
    manifest: FrozenCandidateSourceManifest,
) -> None:
    by_source = {item.source_id: item for item in manifest.sources}
    for candidate in matrix.candidates:
        source = by_source.get(candidate.source_id)
        if source is None:
            raise FrozenModelCandidateArtifactError("candidate source reference is missing")
        if (
            source.candidate_id != candidate.candidate_id
            or source.repository_id != candidate.repository_id
            or source.revision != candidate.revision
        ):
            raise FrozenModelCandidateArtifactError(
                "candidate and upstream source identities differ"
            )
    for candidate in matrix.screened_out:
        source = by_source.get(candidate.source_id)
        if source is None:
            raise FrozenModelCandidateArtifactError("screened-out source reference is missing")
        if (
            source.candidate_id != candidate.candidate_id
            or source.repository_id != candidate.repository_id
            or source.revision != candidate.revision
        ):
            raise FrozenModelCandidateArtifactError(
                "screened-out candidate and source identities differ"
            )


def _load_json_artifact(path: Path, *, label: str) -> tuple[dict[str, object], str]:
    if path.is_symlink() or not path.is_file():
        raise FrozenModelCandidateArtifactError(f"{label} must be a regular file")
    raw = path.read_bytes()
    if len(raw) > _MAX_ARTIFACT_BYTES:
        raise FrozenModelCandidateArtifactError(f"{label} exceeds the configured size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FrozenModelCandidateArtifactError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise FrozenModelCandidateArtifactError(f"{label} must contain a JSON object")
    return payload, hashlib.sha256(raw).hexdigest()


def _validate_pinned_hugging_face_reference(
    value: str,
    *,
    revision: str,
    label: str,
) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.netloc != "huggingface.co":
        raise ValueError(f"{label} must use an HTTPS huggingface.co URL")
    if revision not in parsed.path:
        raise ValueError(f"{label} must contain the exact repository revision")
    if "/main" in parsed.path or "/refs/" in parsed.path:
        raise ValueError(f"{label} cannot use a mutable repository reference")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{label} cannot contain query or fragment components")


def _validate_relative_path(value: str, *, label: str) -> None:
    if "\\" in value:
        raise ValueError(f"{label} must use POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must be a safe relative path")


def _validate_candidate_id(value: str) -> None:
    if _CANDIDATE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("model candidate ID must use model-candidate-<slug>")


def _validate_repository(value: str, *, label: str) -> None:
    if _REPOSITORY_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must use owner/repository syntax")


def _validate_revision(value: str, *, label: str) -> None:
    if _REVISION_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be an exact lowercase hexadecimal revision")


def _validate_identifier(value: str, *, label: str) -> None:
    if _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a normalized identifier")


def _validate_normalized_text(value: str, *, label: str) -> None:
    if not value or value.strip() != value or " ".join(value.split()) != value:
        raise ValueError(f"{label} must be normalized")


def _validate_positive_integer(value: int, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")


def _validate_sha256(value: str, *, label: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{label} must use lowercase SHA-256")


def _validate_aware_datetime(value: datetime, *, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _required_mapping(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise FrozenModelCandidateArtifactError(f"{label} must be a JSON object")
    return value


def _required_list(values: Mapping[str, object], key: str) -> list[object]:
    value = values.get(key)
    if not isinstance(value, list):
        raise FrozenModelCandidateArtifactError(f"{key} must be a JSON array")
    return value


def _required_string(values: Mapping[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value or value.strip() != value:
        raise FrozenModelCandidateArtifactError(f"{key} must be a normalized string")
    return value


def _optional_string(values: Mapping[str, object], key: str) -> str | None:
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value or value.strip() != value:
        raise FrozenModelCandidateArtifactError(f"{key} must be null or a normalized string")
    return value


def _required_integer(values: Mapping[str, object], key: str) -> int:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise FrozenModelCandidateArtifactError(f"{key} must be an integer")
    return value


def _required_boolean(values: Mapping[str, object], key: str) -> bool:
    value = values.get(key)
    if not isinstance(value, bool):
        raise FrozenModelCandidateArtifactError(f"{key} must be a boolean")
    return value


def _optional_boolean(values: Mapping[str, object], key: str) -> bool | None:
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise FrozenModelCandidateArtifactError(f"{key} must be null or a boolean")
    return value


def _required_datetime(values: Mapping[str, object], key: str) -> datetime:
    raw = _required_string(values, key)
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as error:
        raise FrozenModelCandidateArtifactError(f"{key} must use ISO-8601") from error
    _validate_aware_datetime(value, label=key)
    return value


def _string_tuple(values: Mapping[str, object], key: str) -> tuple[str, ...]:
    items = _required_list(values, key)
    if not all(isinstance(item, str) and item and item.strip() == item for item in items):
        raise FrozenModelCandidateArtifactError(f"{key} must contain normalized strings")
    return tuple(items)


def _require_exact_keys(
    values: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    if set(values) != expected:
        raise FrozenModelCandidateArtifactError(f"{label} fields do not match schema version 1")
