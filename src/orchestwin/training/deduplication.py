"""Versioned exact and lexical near-duplicate detection for dataset examples."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.training.dataset_examples import EvaluatorDatasetExample

_TOKEN_PATTERN = re.compile(r"[^\W_]+", flags=re.UNICODE)


class DatasetDuplicateKind(StrEnum):
    """Reason an example was removed from the canonical dataset."""

    EXACT = "EXACT"
    NEAR = "NEAR"


@dataclass(frozen=True, slots=True)
class DatasetDeduplicationPolicy:
    """Versioned deterministic lexical-similarity policy."""

    policy_id: str
    version_number: int
    near_duplicate_threshold: float
    minimum_token_count: int

    def __post_init__(self) -> None:
        normalized = normalize_required_text(
            self.policy_id,
            label="dataset deduplication policy ID",
            maximum_length=256,
        )
        if normalized != self.policy_id:
            raise ValueError("dataset deduplication policy ID must be normalized")
        validate_positive_integer(
            self.version_number,
            label="dataset deduplication policy version number",
        )
        if isinstance(self.near_duplicate_threshold, bool) or not isinstance(
            self.near_duplicate_threshold,
            int | float,
        ):
            raise ValueError("near-duplicate threshold must be numeric")
        if not 0 < float(self.near_duplicate_threshold) <= 1:
            raise ValueError("near-duplicate threshold must be greater than zero and at most one")
        validate_positive_integer(
            self.minimum_token_count,
            label="dataset deduplication minimum token count",
        )

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())

    def to_snapshot(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "version_number": self.version_number,
            "near_duplicate_threshold": float(self.near_duplicate_threshold),
            "minimum_token_count": self.minimum_token_count,
        }


@dataclass(frozen=True, slots=True)
class DatasetDeduplicationDecision:
    """One keep or duplicate decision retaining its comparison evidence."""

    example: EvaluatorDatasetExample
    payload_hash: str
    kept: bool
    duplicate_of_example_id: str | None
    duplicate_kind: DatasetDuplicateKind | None
    similarity: float | None
    content_hash: str

    def __post_init__(self) -> None:
        validate_sha256(self.payload_hash, label="dataset example payload hash")
        duplicate = not self.kept
        if duplicate != (self.duplicate_of_example_id is not None):
            raise ValueError("deduplication decision duplicate reference is inconsistent")
        if duplicate != (self.duplicate_kind is not None):
            raise ValueError("deduplication decision kind is inconsistent")
        if duplicate != (self.similarity is not None):
            raise ValueError("deduplication decision similarity is inconsistent")
        if self.similarity is not None and not 0 <= self.similarity <= 1:
            raise ValueError("deduplication similarity must be between zero and one")
        validate_sha256(self.content_hash, label="deduplication decision content hash")
        expected_hash = snapshot_content_hash(self._hash_snapshot())
        if self.content_hash != expected_hash:
            raise ValueError("deduplication decision content hash is inconsistent")

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.example.example_id, self.example.content_hash)

    def _hash_snapshot(self) -> dict[str, object]:
        return {
            "example_id": self.example.example_id,
            "example_content_hash": self.example.content_hash,
            "payload_hash": self.payload_hash,
            "kept": self.kept,
            "duplicate_of_example_id": self.duplicate_of_example_id,
            "duplicate_kind": None if self.duplicate_kind is None else self.duplicate_kind.value,
            "similarity": self.similarity,
        }

    def to_snapshot(self) -> dict[str, object]:
        return {**self._hash_snapshot(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class DatasetDeduplicationResult:
    """Complete deterministic deduplication ledger."""

    policy: DatasetDeduplicationPolicy
    decisions: tuple[DatasetDeduplicationDecision, ...]
    content_hash: str

    def __post_init__(self) -> None:
        expected = tuple(sorted(self.decisions, key=lambda decision: decision.sort_key))
        if self.decisions != expected:
            raise ValueError("deduplication decisions must use canonical order")
        validate_sha256(self.content_hash, label="deduplication result content hash")
        expected_hash = snapshot_content_hash(
            {
                "policy_content_hash": self.policy.content_hash,
                "decisions": [decision.to_snapshot() for decision in self.decisions],
            }
        )
        if self.content_hash != expected_hash:
            raise ValueError("deduplication result content hash is inconsistent")

    @property
    def kept(self) -> tuple[EvaluatorDatasetExample, ...]:
        return tuple(decision.example for decision in self.decisions if decision.kept)

    @property
    def duplicates(self) -> tuple[DatasetDeduplicationDecision, ...]:
        return tuple(decision for decision in self.decisions if not decision.kept)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "policy": self.policy.to_snapshot(),
            "input_count": len(self.decisions),
            "kept_count": len(self.kept),
            "duplicate_count": len(self.duplicates),
            "decisions": [decision.to_snapshot() for decision in self.decisions],
            "content_hash": self.content_hash,
        }


def default_dataset_deduplication_policy() -> DatasetDeduplicationPolicy:
    return DatasetDeduplicationPolicy(
        policy_id="lexical-payload-deduplication",
        version_number=1,
        near_duplicate_threshold=0.92,
        minimum_token_count=12,
    )


def deduplicate_dataset_examples(
    examples: Iterable[EvaluatorDatasetExample],
    *,
    policy: DatasetDeduplicationPolicy,
) -> DatasetDeduplicationResult:
    """Keep the canonical first example and record every exact or near duplicate."""
    canonical_examples = tuple(
        sorted(
            tuple(examples),
            key=lambda example: (example.example_id, example.content_hash),
        )
    )
    kept_examples: list[EvaluatorDatasetExample] = []
    kept_payload_hashes: dict[str, str] = {}
    kept_tokens: dict[str, frozenset[str]] = {}
    decisions: list[DatasetDeduplicationDecision] = []

    for example in canonical_examples:
        payload_hash = dataset_training_payload_hash(example)
        tokens = dataset_training_tokens(example)
        duplicate_of: EvaluatorDatasetExample | None = None
        duplicate_kind: DatasetDuplicateKind | None = None
        similarity: float | None = None

        for kept in kept_examples:
            if kept_payload_hashes[kept.example_id] == payload_hash:
                duplicate_of = kept
                duplicate_kind = DatasetDuplicateKind.EXACT
                similarity = 1.0
                break

        if duplicate_of is None and len(tokens) >= policy.minimum_token_count:
            candidates: list[tuple[float, EvaluatorDatasetExample]] = []
            for kept in kept_examples:
                comparison_tokens = kept_tokens[kept.example_id]
                if len(comparison_tokens) < policy.minimum_token_count:
                    continue
                score = _jaccard_similarity(tokens, comparison_tokens)
                if score >= policy.near_duplicate_threshold:
                    candidates.append((score, kept))
            if candidates:
                best_score, duplicate_of = sorted(
                    candidates,
                    key=lambda item: (-item[0], item[1].example_id),
                )[0]
                duplicate_kind = DatasetDuplicateKind.NEAR
                similarity = round(best_score, 6)

        kept = duplicate_of is None
        if kept:
            kept_examples.append(example)
            kept_payload_hashes[example.example_id] = payload_hash
            kept_tokens[example.example_id] = tokens

        decision_snapshot = {
            "example_id": example.example_id,
            "example_content_hash": example.content_hash,
            "payload_hash": payload_hash,
            "kept": kept,
            "duplicate_of_example_id": (None if duplicate_of is None else duplicate_of.example_id),
            "duplicate_kind": None if duplicate_kind is None else duplicate_kind.value,
            "similarity": similarity,
        }
        decisions.append(
            DatasetDeduplicationDecision(
                example=example,
                payload_hash=payload_hash,
                kept=kept,
                duplicate_of_example_id=(None if duplicate_of is None else duplicate_of.example_id),
                duplicate_kind=duplicate_kind,
                similarity=similarity,
                content_hash=snapshot_content_hash(decision_snapshot),
            )
        )

    canonical_decisions = tuple(decisions)
    result_hash = snapshot_content_hash(
        {
            "policy_content_hash": policy.content_hash,
            "decisions": [decision.to_snapshot() for decision in canonical_decisions],
        }
    )
    return DatasetDeduplicationResult(
        policy=policy,
        decisions=canonical_decisions,
        content_hash=result_hash,
    )


def dataset_training_payload_hash(example: EvaluatorDatasetExample) -> str:
    """Hash model-visible supervised content independently from record identities."""
    return snapshot_content_hash(_training_payload_snapshot(example))


def dataset_training_tokens(example: EvaluatorDatasetExample) -> frozenset[str]:
    """Return normalized lexical tokens for versioned near-duplicate comparison."""
    payload = _training_payload_snapshot(example)
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return frozenset(_TOKEN_PATTERN.findall(normalized))


def _training_payload_snapshot(example: EvaluatorDatasetExample) -> dict[str, object]:
    return {
        "language": example.language.value,
        "project_brief_summary": example.project_brief_summary,
        "user_twin_profile": json.loads(example.user_twin_profile_json),
        "scenario": example.scenario,
        "target_task": example.target_task,
        "artifact": {
            "media_type": example.artifact.media_type,
            "description": example.artifact.description,
        },
        "evidence": [
            {
                "kind": item.kind.value,
                "content_hash": item.content_hash,
                "locator": item.locator,
                "is_target_user_empirical_evidence": item.is_target_user_empirical_evidence,
                "is_human_validation_activity": item.is_human_validation_activity,
            }
            for item in example.evidence
        ],
        "rubric": example.rubric.to_snapshot(),
        "expected_output": example.expected_output.to_snapshot(),
    }


def _jaccard_similarity(
    first: frozenset[str],
    second: frozenset[str],
) -> float:
    union = first | second
    if not union:
        return 1.0
    return len(first & second) / len(union)
