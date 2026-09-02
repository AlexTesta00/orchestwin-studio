"""Tests for exact and near-duplicate dataset controls."""

from __future__ import annotations

from collections.abc import Callable

from orchestwin.training.dataset_examples import EvaluatorDatasetExample
from orchestwin.training.deduplication import (
    DatasetDeduplicationPolicy,
    DatasetDuplicateKind,
    deduplicate_dataset_examples,
    default_dataset_deduplication_policy,
)


def test_exact_payload_duplicates_are_removed_despite_different_record_ids(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    first = example_factory(example_id="UTE-000001")
    duplicate = example_factory(example_id="UTE-000002")

    result = deduplicate_dataset_examples(
        (duplicate, first),
        policy=default_dataset_deduplication_policy(),
    )

    assert result.kept == (first,)
    assert len(result.duplicates) == 1
    assert result.duplicates[0].example == duplicate
    assert result.duplicates[0].duplicate_of_example_id == first.example_id
    assert result.duplicates[0].duplicate_kind is DatasetDuplicateKind.EXACT
    assert result.duplicates[0].similarity == 1.0


def test_lexical_near_duplicates_use_a_versioned_threshold(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    first = example_factory(example_id="UTE-000010")
    near = example_factory(
        example_id="UTE-000011",
        scenario=("A coordinator corrects one invalid deadline during a busy operational shift."),
    )
    policy = DatasetDeduplicationPolicy(
        policy_id="test-near-deduplication",
        version_number=1,
        near_duplicate_threshold=0.85,
        minimum_token_count=5,
    )

    result = deduplicate_dataset_examples((first, near), policy=policy)

    assert result.kept == (first,)
    assert result.duplicates[0].duplicate_kind is DatasetDuplicateKind.NEAR
    assert result.duplicates[0].similarity is not None
    assert result.duplicates[0].similarity >= 0.85


def test_distinct_examples_are_kept_and_result_is_input_order_independent(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    first = example_factory(example_id="UTE-000020")
    distinct = example_factory(
        example_id="UTE-000021",
        scenario="A novice user compares two explanations before accepting a recommendation.",
        target_task="Understand uncertainty and choose whether to continue.",
        project_brief_summary="A decision-support interface explains uncertain recommendations.",
        overall_summary="The explanation needs a visible source and uncertainty statement.",
    )
    policy = default_dataset_deduplication_policy()

    forward = deduplicate_dataset_examples((first, distinct), policy=policy)
    reverse = deduplicate_dataset_examples((distinct, first), policy=policy)

    assert forward == reverse
    assert forward.kept == (first, distinct)
    assert forward.duplicates == ()
