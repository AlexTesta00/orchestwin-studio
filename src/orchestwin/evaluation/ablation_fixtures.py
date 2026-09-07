"""Frozen, leakage-checked, blinded base-versus-adapter evaluation fixtures."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationResult,
    StructuredGenerationStatus,
    StructuredJsonSchema,
)
from orchestwin.projects.requirements_primitives import (
    canonical_json,
    normalize_required_text,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.training.dataset_examples import (
    SIMULATED_FEEDBACK_DISCLAIMER,
    DatasetLanguage,
    DatasetUseRestriction,
    EvaluatorDatasetExample,
)

ABLATION_FIXTURE_SCHEMA_VERSION: Final = 1
_MAX_IDENTIFIER_LENGTH: Final = 256
_MAX_PAYLOAD_LENGTH: Final = 1_000_000


class AblationCondition(StrEnum):
    """Private experimental condition retained outside blinded packages."""

    BASE = "BASE"
    ADAPTER = "ADAPTER"


@dataclass(frozen=True, slots=True)
class FrozenAblationFixture:
    """One held-out model input with no supervised target in its visible payload."""

    fixture_id: str
    source_example_id: str
    source_example_hash: str
    project_id: UUID
    scenario_family_id: str
    language: DatasetLanguage
    input_payload_json: str
    allowed_evidence_refs: tuple[str, ...]
    output_schema: StructuredJsonSchema
    prompt_version_ref: str
    content_hash: str
    schema_version: int = ABLATION_FIXTURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ABLATION_FIXTURE_SCHEMA_VERSION:
            raise ValueError("unsupported ablation fixture schema version")
        for value, label in (
            (self.fixture_id, "ablation fixture ID"),
            (self.source_example_id, "ablation source example ID"),
            (self.scenario_family_id, "ablation scenario family ID"),
            (self.prompt_version_ref, "ablation prompt version"),
        ):
            normalized = normalize_required_text(
                value,
                label=label,
                maximum_length=_MAX_IDENTIFIER_LENGTH,
            )
            if normalized != value:
                raise ValueError(f"{label} must be normalized")
        validate_sha256(self.source_example_hash, label="ablation source example hash")
        validate_sha256(self.content_hash, label="ablation fixture content hash")
        _require_canonical_json_object(self.input_payload_json)
        payload = json.loads(self.input_payload_json)
        if "expected_output" in payload:
            raise ValueError("frozen ablation input must not expose the supervised target")
        if self.allowed_evidence_refs != tuple(sorted(set(self.allowed_evidence_refs))):
            raise ValueError("ablation evidence references must be canonical and unique")
        if self.content_hash != frozen_ablation_fixture_hash(
            fixture_id=self.fixture_id,
            source_example_id=self.source_example_id,
            source_example_hash=self.source_example_hash,
            project_id=self.project_id,
            scenario_family_id=self.scenario_family_id,
            language=self.language,
            input_payload_json=self.input_payload_json,
            allowed_evidence_refs=self.allowed_evidence_refs,
            output_schema=self.output_schema,
            prompt_version_ref=self.prompt_version_ref,
            schema_version=self.schema_version,
        ):
            raise ValueError("ablation fixture content hash is inconsistent")

    @property
    def family_key(self) -> str:
        return f"{self.project_id}:{self.scenario_family_id}"

    def to_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "fixture_id": self.fixture_id,
            "source_example_id": self.source_example_id,
            "source_example_hash": self.source_example_hash,
            "project_id": str(self.project_id),
            "scenario_family_id": self.scenario_family_id,
            "language": self.language.value,
            "input_payload_json": self.input_payload_json,
            "allowed_evidence_refs": list(self.allowed_evidence_refs),
            "output_schema": self.output_schema.to_snapshot(),
            "prompt_version_ref": self.prompt_version_ref,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class FrozenAblationFixtureSet:
    """Versioned held-out inputs plus reproducible leakage-control evidence."""

    fixture_set_id: UUID
    version_number: int
    seed: int
    fixtures: tuple[FrozenAblationFixture, ...]
    training_example_hashes_digest: str
    training_family_keys_digest: str
    frozen_at: datetime
    content_hash: str
    schema_version: int = ABLATION_FIXTURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ABLATION_FIXTURE_SCHEMA_VERSION:
            raise ValueError("unsupported ablation fixture-set schema version")
        validate_positive_integer(self.version_number, label="ablation fixture-set version")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("ablation fixture-set seed must be a non-negative integer")
        if not self.fixtures:
            raise ValueError("ablation fixture set must not be empty")
        if len({item.fixture_id for item in self.fixtures}) != len(self.fixtures):
            raise ValueError("ablation fixture IDs must be unique")
        if len({item.content_hash for item in self.fixtures}) != len(self.fixtures):
            raise ValueError("ablation fixture contents must be unique")
        expected_order = tuple(
            sorted(
                self.fixtures,
                key=lambda item: _seeded_order_key(self.seed, item.content_hash),
            )
        )
        if self.fixtures != expected_order:
            raise ValueError("ablation fixtures must use deterministic seeded order")
        for value, label in (
            (self.training_example_hashes_digest, "training example exclusion digest"),
            (self.training_family_keys_digest, "training family exclusion digest"),
            (self.content_hash, "ablation fixture-set content hash"),
        ):
            validate_sha256(value, label=label)
        if self.frozen_at.tzinfo is None or self.frozen_at.utcoffset() is None:
            raise ValueError("ablation fixture-set timestamp must be timezone-aware")
        expected_hash = frozen_ablation_fixture_set_hash(
            fixture_set_id=self.fixture_set_id,
            version_number=self.version_number,
            seed=self.seed,
            fixtures=self.fixtures,
            training_example_hashes_digest=self.training_example_hashes_digest,
            training_family_keys_digest=self.training_family_keys_digest,
            frozen_at=self.frozen_at,
            schema_version=self.schema_version,
        )
        if self.content_hash != expected_hash:
            raise ValueError("ablation fixture-set content hash is inconsistent")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "fixture_set_id": str(self.fixture_set_id),
            "version_number": self.version_number,
            "seed": self.seed,
            "fixtures": [item.to_snapshot() for item in self.fixtures],
            "training_example_hashes_digest": self.training_example_hashes_digest,
            "training_family_keys_digest": self.training_family_keys_digest,
            "frozen_at": self.frozen_at.isoformat(),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class ModelAblationOutput:
    """Unblinded exact generation output retained in the private evidence package."""

    fixture_hash: str
    condition: AblationCondition
    runtime_identity: ModelRuntimeIdentity
    payload_json: str
    generation_result_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.fixture_hash, "ablation output fixture hash"),
            (self.generation_result_hash, "ablation generation result hash"),
            (self.content_hash, "ablation output content hash"),
        ):
            validate_sha256(value, label=label)
        _require_canonical_json_object(self.payload_json)
        has_adapter = self.runtime_identity.adapter_id is not None
        if (self.condition is AblationCondition.ADAPTER) != has_adapter:
            raise ValueError("ablation output condition is inconsistent with model identity")
        if self.content_hash != model_ablation_output_hash(
            fixture_hash=self.fixture_hash,
            condition=self.condition,
            runtime_identity=self.runtime_identity,
            payload_json=self.payload_json,
            generation_result_hash=self.generation_result_hash,
        ):
            raise ValueError("ablation output content hash is inconsistent")

    def to_private_snapshot(self) -> dict[str, object]:
        return {
            "fixture_hash": self.fixture_hash,
            "condition": self.condition.value,
            "runtime_identity": self.runtime_identity.to_snapshot(),
            "payload_json": self.payload_json,
            "generation_result_hash": self.generation_result_hash,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class BlindedAblationPair:
    """Public expert package containing no base/adapter identity or condition label."""

    pair_id: UUID
    fixture_id: str
    fixture_hash: str
    output_a_json: str
    output_b_json: str
    randomization_hash: str
    disclaimer: str
    content_hash: str

    def __post_init__(self) -> None:
        validate_sha256(self.fixture_hash, label="blinded pair fixture hash")
        validate_sha256(self.randomization_hash, label="blinded pair randomization hash")
        validate_sha256(self.content_hash, label="blinded pair content hash")
        _require_canonical_json_object(self.output_a_json)
        _require_canonical_json_object(self.output_b_json)
        if self.disclaimer != SIMULATED_FEEDBACK_DISCLAIMER:
            raise ValueError("blinded pair must preserve the simulated-feedback disclaimer")
        expected_hash = blinded_ablation_pair_hash(
            pair_id=self.pair_id,
            fixture_id=self.fixture_id,
            fixture_hash=self.fixture_hash,
            output_a_json=self.output_a_json,
            output_b_json=self.output_b_json,
            randomization_hash=self.randomization_hash,
            disclaimer=self.disclaimer,
        )
        if self.content_hash != expected_hash:
            raise ValueError("blinded ablation pair content hash is inconsistent")

    def to_public_snapshot(self) -> dict[str, object]:
        return {
            "pair_id": str(self.pair_id),
            "fixture_id": self.fixture_id,
            "fixture_hash": self.fixture_hash,
            "output_a_json": self.output_a_json,
            "output_b_json": self.output_b_json,
            "randomization_hash": self.randomization_hash,
            "disclaimer": self.disclaimer,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class AblationPairAssignment:
    """Private condition key stored separately from the blinded expert package."""

    pair_id: UUID
    fixture_hash: str
    output_a_condition: AblationCondition
    output_b_condition: AblationCondition
    base_identity_hash: str
    adapter_identity_hash: str
    randomization_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        if self.output_a_condition is self.output_b_condition:
            raise ValueError("ablation pair assignments require both experimental conditions")
        for value, label in (
            (self.fixture_hash, "ablation assignment fixture hash"),
            (self.base_identity_hash, "ablation base identity hash"),
            (self.adapter_identity_hash, "ablation adapter identity hash"),
            (self.randomization_hash, "ablation assignment randomization hash"),
            (self.content_hash, "ablation assignment content hash"),
        ):
            validate_sha256(value, label=label)
        expected_hash = snapshot_content_hash(
            {
                "pair_id": str(self.pair_id),
                "fixture_hash": self.fixture_hash,
                "output_a_condition": self.output_a_condition.value,
                "output_b_condition": self.output_b_condition.value,
                "base_identity_hash": self.base_identity_hash,
                "adapter_identity_hash": self.adapter_identity_hash,
                "randomization_hash": self.randomization_hash,
            }
        )
        if self.content_hash != expected_hash:
            raise ValueError("ablation pair assignment content hash is inconsistent")

    def to_private_snapshot(self) -> dict[str, object]:
        return {
            "pair_id": str(self.pair_id),
            "fixture_hash": self.fixture_hash,
            "output_a_condition": self.output_a_condition.value,
            "output_b_condition": self.output_b_condition.value,
            "base_identity_hash": self.base_identity_hash,
            "adapter_identity_hash": self.adapter_identity_hash,
            "randomization_hash": self.randomization_hash,
            "content_hash": self.content_hash,
        }


def freeze_ablation_fixture(
    *,
    fixture_id: str,
    example: EvaluatorDatasetExample,
    output_schema: StructuredJsonSchema,
    prompt_version_ref: str,
) -> FrozenAblationFixture:
    """Freeze one expert-sample example without exposing its expected output."""
    if example.use_restriction is not DatasetUseRestriction.EXTERNAL_EXPERT_SAMPLE:
        raise ValueError("ablation fixtures must come from the external expert sample")
    input_payload = {
        "project_id": str(example.project_id),
        "project_brief_reference": example.project_brief_reference.to_snapshot(),
        "project_brief_summary": example.project_brief_summary,
        "user_twin_reference": example.user_twin_reference.to_snapshot(),
        "user_twin_profile": json.loads(example.user_twin_profile_json),
        "scenario": example.scenario,
        "target_task": example.target_task,
        "artifact": example.artifact.to_snapshot(),
        "evidence": [item.to_snapshot() for item in example.evidence],
        "rubric": example.rubric.to_snapshot(),
        "required_disclaimer": SIMULATED_FEEDBACK_DISCLAIMER,
    }
    input_payload_json = canonical_json(input_payload)
    allowed_evidence_refs = tuple(sorted(item.reference_id for item in example.evidence))
    content_hash = frozen_ablation_fixture_hash(
        fixture_id=fixture_id,
        source_example_id=example.example_id,
        source_example_hash=example.content_hash,
        project_id=example.project_id,
        scenario_family_id=example.scenario_family_id,
        language=example.language,
        input_payload_json=input_payload_json,
        allowed_evidence_refs=allowed_evidence_refs,
        output_schema=output_schema,
        prompt_version_ref=prompt_version_ref,
        schema_version=ABLATION_FIXTURE_SCHEMA_VERSION,
    )
    return FrozenAblationFixture(
        fixture_id=fixture_id,
        source_example_id=example.example_id,
        source_example_hash=example.content_hash,
        project_id=example.project_id,
        scenario_family_id=example.scenario_family_id,
        language=example.language,
        input_payload_json=input_payload_json,
        allowed_evidence_refs=allowed_evidence_refs,
        output_schema=output_schema,
        prompt_version_ref=prompt_version_ref,
        content_hash=content_hash,
    )


def freeze_ablation_fixture_set(
    *,
    fixture_set_id: UUID,
    version_number: int,
    seed: int,
    fixtures: Iterable[FrozenAblationFixture],
    training_example_hashes: Iterable[str],
    training_family_keys: Iterable[str],
    frozen_at: datetime,
) -> FrozenAblationFixtureSet:
    """Freeze deterministic order and reject record- or family-level leakage."""
    values = tuple(fixtures)
    training_hashes = tuple(sorted(set(training_example_hashes)))
    training_families = tuple(sorted(set(training_family_keys)))
    for value in training_hashes:
        validate_sha256(value, label="training exclusion example hash")
    fixture_hashes = {item.source_example_hash for item in values}
    leaked_hashes = fixture_hashes.intersection(training_hashes)
    if leaked_hashes:
        raise ValueError("ablation fixture set overlaps training example content")
    fixture_families = {item.family_key for item in values}
    leaked_families = fixture_families.intersection(training_families)
    if leaked_families:
        raise ValueError("ablation fixture set overlaps a training project/scenario family")
    ordered = tuple(sorted(values, key=lambda item: _seeded_order_key(seed, item.content_hash)))
    hash_digest = snapshot_content_hash({"training_example_hashes": list(training_hashes)})
    family_digest = snapshot_content_hash({"training_family_keys": list(training_families)})
    content_hash = frozen_ablation_fixture_set_hash(
        fixture_set_id=fixture_set_id,
        version_number=version_number,
        seed=seed,
        fixtures=ordered,
        training_example_hashes_digest=hash_digest,
        training_family_keys_digest=family_digest,
        frozen_at=frozen_at,
        schema_version=ABLATION_FIXTURE_SCHEMA_VERSION,
    )
    return FrozenAblationFixtureSet(
        fixture_set_id=fixture_set_id,
        version_number=version_number,
        seed=seed,
        fixtures=ordered,
        training_example_hashes_digest=hash_digest,
        training_family_keys_digest=family_digest,
        frozen_at=frozen_at,
        content_hash=content_hash,
    )


def create_model_ablation_output(
    *,
    fixture: FrozenAblationFixture,
    condition: AblationCondition,
    result: StructuredGenerationResult,
) -> ModelAblationOutput:
    """Bind a successful exact-identity generation to one frozen fixture."""
    if result.status is not StructuredGenerationStatus.SUCCEEDED or result.success is None:
        raise ValueError("ablation output requires a successful structured generation result")
    content_hash = model_ablation_output_hash(
        fixture_hash=fixture.content_hash,
        condition=condition,
        runtime_identity=result.success.actual_identity,
        payload_json=result.success.payload_json,
        generation_result_hash=result.content_hash,
    )
    return ModelAblationOutput(
        fixture_hash=fixture.content_hash,
        condition=condition,
        runtime_identity=result.success.actual_identity,
        payload_json=result.success.payload_json,
        generation_result_hash=result.content_hash,
        content_hash=content_hash,
    )


def create_blinded_ablation_pair(
    *,
    pair_id: UUID,
    fixture: FrozenAblationFixture,
    base_output: ModelAblationOutput,
    adapter_output: ModelAblationOutput,
    seed: int,
) -> tuple[BlindedAblationPair, AblationPairAssignment]:
    """Blind output order and return the condition key as a separate private artifact."""
    if base_output.condition is not AblationCondition.BASE:
        raise ValueError("base output has the wrong ablation condition")
    if adapter_output.condition is not AblationCondition.ADAPTER:
        raise ValueError("adapter output has the wrong ablation condition")
    if base_output.fixture_hash != fixture.content_hash or adapter_output.fixture_hash != (
        fixture.content_hash
    ):
        raise ValueError("ablation outputs must reference the same frozen fixture")
    _require_same_base(base_output.runtime_identity, adapter_output.runtime_identity)
    randomization_hash = snapshot_content_hash(
        {
            "pair_id": str(pair_id),
            "fixture_hash": fixture.content_hash,
            "seed": seed,
        }
    )
    adapter_first = int(randomization_hash[-1], 16) % 2 == 1
    output_a = adapter_output if adapter_first else base_output
    output_b = base_output if adapter_first else adapter_output
    pair_hash = blinded_ablation_pair_hash(
        pair_id=pair_id,
        fixture_id=fixture.fixture_id,
        fixture_hash=fixture.content_hash,
        output_a_json=output_a.payload_json,
        output_b_json=output_b.payload_json,
        randomization_hash=randomization_hash,
        disclaimer=SIMULATED_FEEDBACK_DISCLAIMER,
    )
    pair = BlindedAblationPair(
        pair_id=pair_id,
        fixture_id=fixture.fixture_id,
        fixture_hash=fixture.content_hash,
        output_a_json=output_a.payload_json,
        output_b_json=output_b.payload_json,
        randomization_hash=randomization_hash,
        disclaimer=SIMULATED_FEEDBACK_DISCLAIMER,
        content_hash=pair_hash,
    )
    assignment_values = {
        "pair_id": str(pair_id),
        "fixture_hash": fixture.content_hash,
        "output_a_condition": output_a.condition.value,
        "output_b_condition": output_b.condition.value,
        "base_identity_hash": base_output.runtime_identity.content_hash,
        "adapter_identity_hash": adapter_output.runtime_identity.content_hash,
        "randomization_hash": randomization_hash,
    }
    assignment = AblationPairAssignment(
        pair_id=pair_id,
        fixture_hash=fixture.content_hash,
        output_a_condition=output_a.condition,
        output_b_condition=output_b.condition,
        base_identity_hash=base_output.runtime_identity.content_hash,
        adapter_identity_hash=adapter_output.runtime_identity.content_hash,
        randomization_hash=randomization_hash,
        content_hash=snapshot_content_hash(assignment_values),
    )
    return pair, assignment


def frozen_ablation_fixture_hash(
    *,
    fixture_id: str,
    source_example_id: str,
    source_example_hash: str,
    project_id: UUID,
    scenario_family_id: str,
    language: DatasetLanguage,
    input_payload_json: str,
    allowed_evidence_refs: tuple[str, ...],
    output_schema: StructuredJsonSchema,
    prompt_version_ref: str,
    schema_version: int,
) -> str:
    return snapshot_content_hash(
        {
            "schema_version": schema_version,
            "fixture_id": fixture_id,
            "source_example_id": source_example_id,
            "source_example_hash": source_example_hash,
            "project_id": str(project_id),
            "scenario_family_id": scenario_family_id,
            "language": language.value,
            "input_payload": json.loads(input_payload_json),
            "allowed_evidence_refs": list(allowed_evidence_refs),
            "output_schema": output_schema.to_snapshot(),
            "prompt_version_ref": prompt_version_ref,
        }
    )


def frozen_ablation_fixture_set_hash(
    *,
    fixture_set_id: UUID,
    version_number: int,
    seed: int,
    fixtures: tuple[FrozenAblationFixture, ...],
    training_example_hashes_digest: str,
    training_family_keys_digest: str,
    frozen_at: datetime,
    schema_version: int,
) -> str:
    return snapshot_content_hash(
        {
            "schema_version": schema_version,
            "fixture_set_id": str(fixture_set_id),
            "version_number": version_number,
            "seed": seed,
            "fixtures": [item.to_snapshot() for item in fixtures],
            "training_example_hashes_digest": training_example_hashes_digest,
            "training_family_keys_digest": training_family_keys_digest,
            "frozen_at": frozen_at.isoformat(),
        }
    )


def model_ablation_output_hash(
    *,
    fixture_hash: str,
    condition: AblationCondition,
    runtime_identity: ModelRuntimeIdentity,
    payload_json: str,
    generation_result_hash: str,
) -> str:
    return snapshot_content_hash(
        {
            "fixture_hash": fixture_hash,
            "condition": condition.value,
            "runtime_identity": runtime_identity.to_snapshot(),
            "payload": json.loads(payload_json),
            "generation_result_hash": generation_result_hash,
        }
    )


def blinded_ablation_pair_hash(
    *,
    pair_id: UUID,
    fixture_id: str,
    fixture_hash: str,
    output_a_json: str,
    output_b_json: str,
    randomization_hash: str,
    disclaimer: str,
) -> str:
    return snapshot_content_hash(
        {
            "pair_id": str(pair_id),
            "fixture_id": fixture_id,
            "fixture_hash": fixture_hash,
            "output_a": json.loads(output_a_json),
            "output_b": json.loads(output_b_json),
            "randomization_hash": randomization_hash,
            "disclaimer": disclaimer,
        }
    )


def _seeded_order_key(seed: int, content_hash: str) -> tuple[str, str]:
    digest = hashlib.sha256(f"{seed}:{content_hash}".encode()).hexdigest()
    return digest, content_hash


def _require_same_base(
    base_identity: ModelRuntimeIdentity,
    adapter_identity: ModelRuntimeIdentity,
) -> None:
    if base_identity.adapter_id is not None or adapter_identity.adapter_id is None:
        raise ValueError("ablation identities must be base and the same base plus adapter")
    base_values = (
        base_identity.provider_id,
        base_identity.runtime_id,
        base_identity.base_model_repository,
        base_identity.base_model_revision,
        base_identity.tokenizer_revision,
    )
    adapter_values = (
        adapter_identity.provider_id,
        adapter_identity.runtime_id,
        adapter_identity.base_model_repository,
        adapter_identity.base_model_revision,
        adapter_identity.tokenizer_revision,
    )
    if base_values != adapter_values:
        raise ValueError("ablation conditions must use the same base model and tokenizer")


def _require_canonical_json_object(value: str) -> None:
    if not value or len(value) > _MAX_PAYLOAD_LENGTH:
        raise ValueError("ablation JSON payload has an invalid length")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("ablation JSON payload must be valid") from error
    if not isinstance(parsed, dict) or canonical_json(parsed) != value:
        raise ValueError("ablation JSON payload must be a canonical object")
