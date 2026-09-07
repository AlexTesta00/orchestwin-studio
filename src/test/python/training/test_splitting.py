"""Tests for grouped dataset splits and leakage controls."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from orchestwin.training.dataset_examples import (
    DatasetUseRestriction,
    EvaluatorDatasetExample,
)
from orchestwin.training.splitting import (
    DatasetLeakageCode,
    DatasetSplit,
    DatasetSplitExclusionReason,
    DatasetSplitPolicy,
    default_dataset_split_policy,
    split_dataset_examples,
)


def test_project_scenario_variants_always_remain_in_the_same_split(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    examples = (
        example_factory(example_id="UTE-000001"),
        example_factory(
            example_id="UTE-000002",
            scenario="A second variant keeps the same project and scenario family.",
        ),
    )

    result = split_dataset_examples(
        reversed(examples),
        policy=default_dataset_split_policy(),
    )

    assert result.publishable is True
    assert len({assignment.group_key for assignment in result.assignments}) == 1
    assert len({assignment.split for assignment in result.assignments}) == 1
    assert len({assignment.bucket for assignment in result.assignments}) == 1


def test_formal_and_expert_groups_are_excluded_as_complete_groups(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    formal = example_factory(
        example_id="UTE-000010",
        scenario_family_id="reserved-formal-family",
        use_restriction=DatasetUseRestriction.FORMAL_CASE_STUDY,
    )
    same_group = example_factory(
        example_id="UTE-000011",
        scenario_family_id="reserved-formal-family",
        use_restriction=DatasetUseRestriction.NONE,
        scenario="A derived variant of the same reserved family.",
    )
    expert = example_factory(
        example_id="UTE-000012",
        scenario_family_id="reserved-expert-family",
        use_restriction=DatasetUseRestriction.EXTERNAL_EXPERT_SAMPLE,
    )

    result = split_dataset_examples(
        (formal, same_group, expert),
        policy=default_dataset_split_policy(),
    )

    assert all(assignment.split is DatasetSplit.EXCLUDED for assignment in result.assignments)
    reasons = {assignment.exclusion_reason for assignment in result.assignments}
    assert DatasetSplitExclusionReason.FORMAL_CASE_STUDY in reasons
    assert DatasetSplitExclusionReason.EXTERNAL_EXPERT_SAMPLE in reasons
    assert result.publishable is True


def test_identical_payloads_in_different_active_splits_block_publication(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    policy = DatasetSplitPolicy(
        policy_id="test-grouped-split",
        version_number=1,
        seed=5,
        train_percent=34,
        validation_percent=33,
        internal_test_percent=33,
    )
    examples: list[EvaluatorDatasetExample] = []
    for index in range(1, 250):
        project_id = UUID(f"00000000-0000-4000-8000-{index:012d}")
        examples.append(
            example_factory(
                example_id=f"UTE-{index:06d}",
                project_id=project_id,
                scenario_family_id=f"family-{index:03d}",
            )
        )
        result = split_dataset_examples(examples, policy=policy)
        active_splits = {assignment.split for assignment in result.assignments}
        if len(active_splits) > 1:
            break
    else:
        raise AssertionError("test data did not reach two deterministic split buckets")

    assert result.publishable is False
    assert DatasetLeakageCode.PAYLOAD_CROSSES_SPLITS in {
        issue.code for issue in result.leakage_issues
    }


def test_split_assignments_are_stable_across_input_order(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    examples = tuple(
        example_factory(
            example_id=f"UTE-{index:06d}",
            project_id=UUID(f"00000000-0000-4000-8000-{index:012d}"),
            scenario_family_id=f"family-{index:03d}",
            scenario=f"Distinct scenario variant number {index} with dedicated workflow context.",
        )
        for index in range(1, 8)
    )
    policy = default_dataset_split_policy()

    forward = split_dataset_examples(examples, policy=policy)
    reverse = split_dataset_examples(reversed(examples), policy=policy)

    assert forward == reverse
