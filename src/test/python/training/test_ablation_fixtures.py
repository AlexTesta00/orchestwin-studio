"""Tests for frozen and blinded base-versus-adapter evaluation fixtures."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.evaluation.ablation_fixtures import (
    AblationCondition,
    create_blinded_ablation_pair,
    create_model_ablation_output,
    freeze_ablation_fixture,
    freeze_ablation_fixture_set,
)
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFinishReason,
    StructuredGenerationProviderKind,
    StructuredGenerationUsage,
    create_structured_generation_success,
    create_structured_json_schema,
    successful_structured_generation_result,
)
from orchestwin.training.dataset_examples import (
    DatasetLanguage,
    DatasetUseRestriction,
    EvaluatorDatasetExample,
)

FIXTURE_SET_ID = UUID("00000000-0000-4000-8000-000000129001")
PAIR_ID = UUID("00000000-0000-4000-8000-000000129002")
FROZEN_AT = datetime(2026, 10, 18, 14, 0, tzinfo=UTC)


def _schema():
    return create_structured_json_schema(
        schema_id="orchestwin-user-twin-evaluation",
        version_number=1,
        schema_payload={
            "type": "object",
            "required": ["overall_summary", "findings", "evidence_gaps", "abstained"],
        },
    )


def _fixture(example: EvaluatorDatasetExample, fixture_id: str = "ABL-0001"):
    return freeze_ablation_fixture(
        fixture_id=fixture_id,
        example=example,
        output_schema=_schema(),
        prompt_version_ref="ut-eval-v5",
    )


def _identity(*, adapter: bool, configuration: str) -> ModelRuntimeIdentity:
    return ModelRuntimeIdentity(
        provider_id="local-openai",
        runtime_id="local-evaluator-v1",
        base_model_repository="example/selected-small-instruct",
        base_model_revision="a" * 40,
        tokenizer_revision="b" * 40,
        configuration_sha256=configuration * 64,
        adapter_id="ut-evaluator-v1" if adapter else None,
        adapter_sha256="d" * 64 if adapter else None,
    )


def _result(identity: ModelRuntimeIdentity, summary: str):
    success = create_structured_generation_success(
        payload={
            "overall_summary": summary,
            "findings": [],
            "evidence_gaps": ["Target-user validation is unavailable."],
            "abstained": True,
        },
        actual_identity=identity,
        usage=StructuredGenerationUsage(120, 30, 50),
        finish_reason=StructuredGenerationFinishReason.STOP,
        provider_request_id="fixture-generation",
    )
    return successful_structured_generation_result(
        provider_kind=StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
        success=success,
    )


def test_fixture_freezes_only_held_out_inputs_without_expected_output(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    example = example_factory(use_restriction=DatasetUseRestriction.EXTERNAL_EXPERT_SAMPLE)

    fixture = _fixture(example)
    payload = json.loads(fixture.input_payload_json)

    assert fixture.source_example_hash == example.content_hash
    assert fixture.allowed_evidence_refs == (
        "REQ-NFR-012",
        "ut-profile-v3.operational_constraints[0]",
    )
    assert "expected_output" not in payload
    assert payload["required_disclaimer"].endswith("not empirical evidence of real-user behavior.")


def test_fixture_set_is_seeded_reproducible_and_records_exclusion_digests(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    first = _fixture(
        example_factory(use_restriction=DatasetUseRestriction.EXTERNAL_EXPERT_SAMPLE),
        "ABL-0001",
    )
    second = _fixture(
        example_factory(
            example_id="UTE-000002",
            language=DatasetLanguage.ITALIAN,
            project_id=UUID("00000000-0000-4000-8000-000000129010"),
            scenario_family_id="generic-accessibility-recovery",
            use_restriction=DatasetUseRestriction.EXTERNAL_EXPERT_SAMPLE,
        ),
        "ABL-0002",
    )
    arguments = {
        "fixture_set_id": FIXTURE_SET_ID,
        "version_number": 1,
        "seed": 3407,
        "fixtures": (second, first),
        "training_example_hashes": ("f" * 64,),
        "training_family_keys": ("training-project:training-family",),
        "frozen_at": FROZEN_AT,
    }

    one = freeze_ablation_fixture_set(**arguments)
    two = freeze_ablation_fixture_set(**arguments)

    assert one == two
    assert one.content_hash == two.content_hash
    assert {item.fixture_id for item in one.fixtures} == {"ABL-0001", "ABL-0002"}
    assert one.training_example_hashes_digest != one.training_family_keys_digest


def test_fixture_set_blocks_record_and_project_family_leakage(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    fixture = _fixture(
        example_factory(use_restriction=DatasetUseRestriction.EXTERNAL_EXPERT_SAMPLE)
    )

    with pytest.raises(ValueError, match="example content"):
        freeze_ablation_fixture_set(
            fixture_set_id=FIXTURE_SET_ID,
            version_number=1,
            seed=3407,
            fixtures=(fixture,),
            training_example_hashes=(fixture.source_example_hash,),
            training_family_keys=(),
            frozen_at=FROZEN_AT,
        )
    with pytest.raises(ValueError, match="project/scenario family"):
        freeze_ablation_fixture_set(
            fixture_set_id=FIXTURE_SET_ID,
            version_number=1,
            seed=3407,
            fixtures=(fixture,),
            training_example_hashes=(),
            training_family_keys=(fixture.family_key,),
            frozen_at=FROZEN_AT,
        )


def test_blinded_pair_separates_public_outputs_from_the_private_condition_key(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    fixture = _fixture(
        example_factory(use_restriction=DatasetUseRestriction.EXTERNAL_EXPERT_SAMPLE)
    )
    base = create_model_ablation_output(
        fixture=fixture,
        condition=AblationCondition.BASE,
        result=_result(_identity(adapter=False, configuration="c"), "Base output."),
    )
    adapted = create_model_ablation_output(
        fixture=fixture,
        condition=AblationCondition.ADAPTER,
        result=_result(_identity(adapter=True, configuration="e"), "Adapter output."),
    )

    pair, assignment = create_blinded_ablation_pair(
        pair_id=PAIR_ID,
        fixture=fixture,
        base_output=base,
        adapter_output=adapted,
        seed=3407,
    )

    public = pair.to_public_snapshot()
    private = assignment.to_private_snapshot()
    assert "condition" not in json.dumps(public)
    assert "runtime_identity" not in json.dumps(public)
    assert {private["output_a_condition"], private["output_b_condition"]} == {
        "BASE",
        "ADAPTER",
    }
    assert pair.randomization_hash == assignment.randomization_hash


def test_ablation_rejects_different_base_models_and_unrestricted_examples(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    unrestricted = example_factory(use_restriction=DatasetUseRestriction.NONE)
    with pytest.raises(ValueError, match="external expert sample"):
        _fixture(unrestricted)

    held_out = _fixture(
        example_factory(use_restriction=DatasetUseRestriction.EXTERNAL_EXPERT_SAMPLE)
    )
    base_identity = _identity(adapter=False, configuration="c")
    adapter_identity = ModelRuntimeIdentity(
        provider_id="local-openai",
        runtime_id="local-evaluator-v1",
        base_model_repository="example/different-model",
        base_model_revision="a" * 40,
        tokenizer_revision="b" * 40,
        configuration_sha256="e" * 64,
        adapter_id="ut-evaluator-v1",
        adapter_sha256="d" * 64,
    )
    base = create_model_ablation_output(
        fixture=held_out,
        condition=AblationCondition.BASE,
        result=_result(base_identity, "Base output."),
    )
    adapted = create_model_ablation_output(
        fixture=held_out,
        condition=AblationCondition.ADAPTER,
        result=_result(adapter_identity, "Adapter output."),
    )
    with pytest.raises(ValueError, match="same base model"):
        create_blinded_ablation_pair(
            pair_id=PAIR_ID,
            fixture=held_out,
            base_output=base,
            adapter_output=adapted,
            seed=3407,
        )
