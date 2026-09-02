"""Grouped deterministic dataset splits and publication-blocking leakage checks."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    canonical_uuid_tuple,
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.training.dataset_examples import DatasetUseRestriction, EvaluatorDatasetExample
from orchestwin.training.deduplication import dataset_training_payload_hash


class DatasetSplit(StrEnum):
    """Frozen evaluator-dataset partitions."""

    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    INTERNAL_TEST = "INTERNAL_TEST"
    EXCLUDED = "EXCLUDED"


class DatasetSplitExclusionReason(StrEnum):
    """Why a complete project/scenario group cannot enter training partitions."""

    FORMAL_CASE_STUDY = "FORMAL_CASE_STUDY"
    EXTERNAL_EXPERT_SAMPLE = "EXTERNAL_EXPERT_SAMPLE"
    EXCLUDED_PROJECT = "EXCLUDED_PROJECT"
    EXCLUDED_SCENARIO_FAMILY = "EXCLUDED_SCENARIO_FAMILY"


class DatasetLeakageCode(StrEnum):
    """Publication-blocking split defects."""

    GROUP_CROSSES_SPLITS = "GROUP_CROSSES_SPLITS"
    PAYLOAD_CROSSES_SPLITS = "PAYLOAD_CROSSES_SPLITS"
    RESERVED_EXAMPLE_IN_ACTIVE_SPLIT = "RESERVED_EXAMPLE_IN_ACTIVE_SPLIT"


@dataclass(frozen=True, slots=True)
class DatasetSplitPolicy:
    """Versioned grouped split policy using deterministic hash buckets."""

    policy_id: str
    version_number: int
    seed: int
    train_percent: int
    validation_percent: int
    internal_test_percent: int
    excluded_project_ids: tuple[UUID, ...] = ()
    excluded_scenario_family_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized_id = normalize_required_text(
            self.policy_id,
            label="dataset split policy ID",
            maximum_length=256,
        )
        if normalized_id != self.policy_id:
            raise ValueError("dataset split policy ID must be normalized")
        validate_positive_integer(
            self.version_number,
            label="dataset split policy version number",
        )
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("dataset split seed must be a non-negative integer")
        percentages = (
            self.train_percent,
            self.validation_percent,
            self.internal_test_percent,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in percentages
        ):
            raise ValueError("dataset split percentages must be positive integers")
        if sum(percentages) != 100:
            raise ValueError("dataset split percentages must sum to 100")

        canonical_projects = canonical_uuid_tuple(
            self.excluded_project_ids,
            label="excluded dataset projects",
            require_items=False,
        )
        if canonical_projects != self.excluded_project_ids:
            raise ValueError("excluded dataset project IDs must use canonical order")

        family_ids = normalize_text_items(
            self.excluded_scenario_family_ids,
            label="excluded dataset scenario family ID",
            maximum_item_length=256,
            require_items=False,
        )
        canonical_family_ids = tuple(sorted(family_ids))
        if family_ids != self.excluded_scenario_family_ids or family_ids != canonical_family_ids:
            raise ValueError("excluded scenario family IDs must be normalized and canonical")

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())

    def to_snapshot(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "version_number": self.version_number,
            "seed": self.seed,
            "train_percent": self.train_percent,
            "validation_percent": self.validation_percent,
            "internal_test_percent": self.internal_test_percent,
            "excluded_project_ids": [str(value) for value in self.excluded_project_ids],
            "excluded_scenario_family_ids": list(self.excluded_scenario_family_ids),
        }


@dataclass(frozen=True, slots=True)
class DatasetSplitAssignment:
    """One stable assignment tied to its project/scenario group."""

    example: EvaluatorDatasetExample
    group_key: str
    split: DatasetSplit
    bucket: int | None
    exclusion_reason: DatasetSplitExclusionReason | None
    payload_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        normalized_key = normalize_required_text(
            self.group_key,
            label="dataset split group key",
            maximum_length=512,
        )
        if normalized_key != self.group_key:
            raise ValueError("dataset split group key must be normalized")
        excluded = self.split is DatasetSplit.EXCLUDED
        if excluded != (self.exclusion_reason is not None):
            raise ValueError("dataset split exclusion reason is inconsistent")
        if excluded != (self.bucket is None):
            raise ValueError("dataset split bucket is inconsistent")
        if self.bucket is not None and not 0 <= self.bucket <= 99:
            raise ValueError("dataset split bucket must be between zero and 99")
        validate_sha256(self.payload_hash, label="dataset split payload hash")
        validate_sha256(self.content_hash, label="dataset split assignment content hash")
        if self.content_hash != snapshot_content_hash(self._hash_snapshot()):
            raise ValueError("dataset split assignment content hash is inconsistent")

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.example.example_id, self.example.content_hash)

    def _hash_snapshot(self) -> dict[str, object]:
        return {
            "example_id": self.example.example_id,
            "example_content_hash": self.example.content_hash,
            "group_key": self.group_key,
            "split": self.split.value,
            "bucket": self.bucket,
            "exclusion_reason": (
                None if self.exclusion_reason is None else self.exclusion_reason.value
            ),
            "payload_hash": self.payload_hash,
        }

    def to_snapshot(self) -> dict[str, object]:
        return {**self._hash_snapshot(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class DatasetLeakageIssue:
    """One deterministic split defect that blocks dataset publication."""

    code: DatasetLeakageCode
    key: str
    example_ids: tuple[str, ...]
    splits: tuple[DatasetSplit, ...]

    def __post_init__(self) -> None:
        normalized = normalize_required_text(
            self.key,
            label="dataset leakage issue key",
            maximum_length=512,
        )
        if normalized != self.key:
            raise ValueError("dataset leakage issue key must be normalized")
        if self.example_ids != tuple(sorted(set(self.example_ids))):
            raise ValueError("dataset leakage example IDs must be unique and canonical")
        if self.splits != tuple(sorted(set(self.splits), key=lambda split: split.value)):
            raise ValueError("dataset leakage splits must be unique and canonical")

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.code.value, self.key)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "key": self.key,
            "example_ids": list(self.example_ids),
            "splits": [split.value for split in self.splits],
        }


@dataclass(frozen=True, slots=True)
class DatasetSplitResult:
    """Complete split manifest plus leakage report."""

    policy: DatasetSplitPolicy
    assignments: tuple[DatasetSplitAssignment, ...]
    leakage_issues: tuple[DatasetLeakageIssue, ...]
    content_hash: str

    def __post_init__(self) -> None:
        expected_assignments = tuple(
            sorted(self.assignments, key=lambda assignment: assignment.sort_key)
        )
        if self.assignments != expected_assignments:
            raise ValueError("dataset split assignments must use canonical order")
        expected_issues = tuple(sorted(self.leakage_issues, key=lambda issue: issue.sort_key))
        if self.leakage_issues != expected_issues:
            raise ValueError("dataset leakage issues must use canonical order")
        validate_sha256(self.content_hash, label="dataset split result content hash")
        if self.content_hash != snapshot_content_hash(
            {
                "policy_content_hash": self.policy.content_hash,
                "assignments": [assignment.to_snapshot() for assignment in self.assignments],
                "leakage_issues": [issue.to_snapshot() for issue in self.leakage_issues],
            }
        ):
            raise ValueError("dataset split result content hash is inconsistent")

    @property
    def publishable(self) -> bool:
        return not self.leakage_issues

    def examples_for(self, split: DatasetSplit) -> tuple[EvaluatorDatasetExample, ...]:
        return tuple(
            assignment.example for assignment in self.assignments if assignment.split is split
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "policy": self.policy.to_snapshot(),
            "publishable": self.publishable,
            "counts": {split.value: len(self.examples_for(split)) for split in DatasetSplit},
            "assignments": [assignment.to_snapshot() for assignment in self.assignments],
            "leakage_issues": [issue.to_snapshot() for issue in self.leakage_issues],
            "content_hash": self.content_hash,
        }


def default_dataset_split_policy() -> DatasetSplitPolicy:
    return DatasetSplitPolicy(
        policy_id="project-scenario-grouped-split",
        version_number=1,
        seed=20261013,
        train_percent=80,
        validation_percent=10,
        internal_test_percent=10,
    )


def split_dataset_examples(
    examples: Iterable[EvaluatorDatasetExample],
    *,
    policy: DatasetSplitPolicy,
) -> DatasetSplitResult:
    """Assign complete project/scenario groups and detect cross-split leakage."""
    canonical_examples = tuple(
        sorted(
            tuple(examples),
            key=lambda example: (example.example_id, example.content_hash),
        )
    )
    groups: dict[str, list[EvaluatorDatasetExample]] = defaultdict(list)
    for example in canonical_examples:
        groups[_group_key(example)].append(example)

    assignments: list[DatasetSplitAssignment] = []
    for group_key in sorted(groups):
        group_examples = tuple(groups[group_key])
        split, bucket, exclusion_reason = _group_assignment(
            group_examples,
            policy=policy,
        )
        for example in group_examples:
            payload_hash = dataset_training_payload_hash(example)
            hash_snapshot = {
                "example_id": example.example_id,
                "example_content_hash": example.content_hash,
                "group_key": group_key,
                "split": split.value,
                "bucket": bucket,
                "exclusion_reason": (None if exclusion_reason is None else exclusion_reason.value),
                "payload_hash": payload_hash,
            }
            assignments.append(
                DatasetSplitAssignment(
                    example=example,
                    group_key=group_key,
                    split=split,
                    bucket=bucket,
                    exclusion_reason=exclusion_reason,
                    payload_hash=payload_hash,
                    content_hash=snapshot_content_hash(hash_snapshot),
                )
            )

    canonical_assignments = tuple(sorted(assignments, key=lambda assignment: assignment.sort_key))
    leakage_issues = _detect_leakage(canonical_assignments)
    result_hash = snapshot_content_hash(
        {
            "policy_content_hash": policy.content_hash,
            "assignments": [assignment.to_snapshot() for assignment in canonical_assignments],
            "leakage_issues": [issue.to_snapshot() for issue in leakage_issues],
        }
    )
    return DatasetSplitResult(
        policy=policy,
        assignments=canonical_assignments,
        leakage_issues=leakage_issues,
        content_hash=result_hash,
    )


def _group_key(example: EvaluatorDatasetExample) -> str:
    return f"{example.project_id}:{example.scenario_family_id}"


def _group_assignment(
    examples: tuple[EvaluatorDatasetExample, ...],
    *,
    policy: DatasetSplitPolicy,
) -> tuple[DatasetSplit, int | None, DatasetSplitExclusionReason | None]:
    project_id = examples[0].project_id
    family_id = examples[0].scenario_family_id
    restrictions = {example.use_restriction for example in examples}
    if DatasetUseRestriction.FORMAL_CASE_STUDY in restrictions:
        return DatasetSplit.EXCLUDED, None, DatasetSplitExclusionReason.FORMAL_CASE_STUDY
    if DatasetUseRestriction.EXTERNAL_EXPERT_SAMPLE in restrictions:
        return DatasetSplit.EXCLUDED, None, DatasetSplitExclusionReason.EXTERNAL_EXPERT_SAMPLE
    if project_id in policy.excluded_project_ids:
        return DatasetSplit.EXCLUDED, None, DatasetSplitExclusionReason.EXCLUDED_PROJECT
    if family_id in policy.excluded_scenario_family_ids:
        return DatasetSplit.EXCLUDED, None, DatasetSplitExclusionReason.EXCLUDED_SCENARIO_FAMILY

    bucket = _group_bucket(policy.seed, project_id, family_id)
    if bucket < policy.train_percent:
        return DatasetSplit.TRAIN, bucket, None
    if bucket < policy.train_percent + policy.validation_percent:
        return DatasetSplit.VALIDATION, bucket, None
    return DatasetSplit.INTERNAL_TEST, bucket, None


def _group_bucket(seed: int, project_id: UUID, family_id: str) -> int:
    payload = f"{seed}:{project_id}:{family_id}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % 100


def _detect_leakage(
    assignments: tuple[DatasetSplitAssignment, ...],
) -> tuple[DatasetLeakageIssue, ...]:
    issues: list[DatasetLeakageIssue] = []
    active_assignments = tuple(
        assignment for assignment in assignments if assignment.split is not DatasetSplit.EXCLUDED
    )

    by_group: dict[str, list[DatasetSplitAssignment]] = defaultdict(list)
    by_payload: dict[str, list[DatasetSplitAssignment]] = defaultdict(list)
    for assignment in active_assignments:
        by_group[assignment.group_key].append(assignment)
        by_payload[assignment.payload_hash].append(assignment)
        if assignment.example.use_restriction is not DatasetUseRestriction.NONE:
            issues.append(
                DatasetLeakageIssue(
                    code=DatasetLeakageCode.RESERVED_EXAMPLE_IN_ACTIVE_SPLIT,
                    key=assignment.example.example_id,
                    example_ids=(assignment.example.example_id,),
                    splits=(assignment.split,),
                )
            )

    for group_key, group_assignments in by_group.items():
        splits = tuple(
            sorted(
                {assignment.split for assignment in group_assignments},
                key=lambda split: split.value,
            )
        )
        if len(splits) > 1:
            issues.append(
                DatasetLeakageIssue(
                    code=DatasetLeakageCode.GROUP_CROSSES_SPLITS,
                    key=group_key,
                    example_ids=tuple(
                        sorted(assignment.example.example_id for assignment in group_assignments)
                    ),
                    splits=splits,
                )
            )

    for payload_hash, payload_assignments in by_payload.items():
        splits = tuple(
            sorted(
                {assignment.split for assignment in payload_assignments},
                key=lambda split: split.value,
            )
        )
        if len(splits) > 1:
            issues.append(
                DatasetLeakageIssue(
                    code=DatasetLeakageCode.PAYLOAD_CROSSES_SPLITS,
                    key=payload_hash,
                    example_ids=tuple(
                        sorted(assignment.example.example_id for assignment in payload_assignments)
                    ),
                    splits=splits,
                )
            )

    return tuple(sorted(issues, key=lambda issue: issue.sort_key))
