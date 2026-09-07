"""Descriptive-only aggregation for decoded university-instructor expert ratings."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import Final

from orchestwin.evaluation.expert_blinding import ModelVariant
from orchestwin.evaluation.expert_unblinding import DecodedExpertPairRating

EXPERT_EVIDENCE_DISCLAIMER: Final = (
    "Expert judgments are descriptive evidence from university instructors; they are not "
    "target-user empirical validation and do not establish real-user behavior."
)


@dataclass(frozen=True, slots=True)
class ExpertRubricDescriptiveResult:
    """Paired descriptive summary for one frozen rubric item."""

    rubric_item: str
    sample_count: int
    base_mean: float
    adapter_mean: float
    mean_delta_adapter_minus_base: float

    def to_snapshot(self) -> dict[str, object]:
        return {
            "rubric_item": self.rubric_item,
            "sample_count": self.sample_count,
            "base_mean": self.base_mean,
            "adapter_mean": self.adapter_mean,
            "mean_delta_adapter_minus_base": self.mean_delta_adapter_minus_base,
        }


@dataclass(frozen=True, slots=True)
class ExpertDescriptiveSummary:
    """Descriptive aggregate with explicit non-user-evidence provenance."""

    rating_count: int
    pair_count: int
    base_preference_count: int
    adapter_preference_count: int
    tie_count: int
    rubric_results: tuple[ExpertRubricDescriptiveResult, ...]
    overall_base_mean: float
    overall_adapter_mean: float
    overall_mean_delta_adapter_minus_base: float
    disclaimer: str
    is_expert_judgment: bool
    is_target_user_evidence: bool
    real_user_behavior_validated: bool

    def to_snapshot(self) -> dict[str, object]:
        return {
            "rating_count": self.rating_count,
            "pair_count": self.pair_count,
            "base_preference_count": self.base_preference_count,
            "adapter_preference_count": self.adapter_preference_count,
            "tie_count": self.tie_count,
            "rubric_results": [item.to_snapshot() for item in self.rubric_results],
            "overall_base_mean": self.overall_base_mean,
            "overall_adapter_mean": self.overall_adapter_mean,
            "overall_mean_delta_adapter_minus_base": (self.overall_mean_delta_adapter_minus_base),
            "disclaimer": self.disclaimer,
            "is_expert_judgment": self.is_expert_judgment,
            "is_target_user_evidence": self.is_target_user_evidence,
            "real_user_behavior_validated": self.real_user_behavior_validated,
        }


def aggregate_decoded_expert_ratings(
    ratings: tuple[DecodedExpertPairRating, ...],
) -> ExpertDescriptiveSummary:
    """Aggregate paired ratings descriptively without inferential or causal claims."""
    if not ratings:
        raise ValueError("at least one decoded expert rating is required")

    first_items = tuple(item.rubric_item for item in ratings[0].base_scores)
    if not first_items:
        raise ValueError("decoded expert ratings must contain rubric scores")
    for rating in ratings:
        base_items = tuple(item.rubric_item for item in rating.base_scores)
        adapter_items = tuple(item.rubric_item for item in rating.adapter_scores)
        if base_items != first_items or adapter_items != first_items:
            raise ValueError("decoded expert ratings must use the same ordered rubric")

    rubric_results: list[ExpertRubricDescriptiveResult] = []
    all_base: list[int] = []
    all_adapter: list[int] = []
    for index, rubric_item in enumerate(first_items):
        base_values = [rating.base_scores[index].score for rating in ratings]
        adapter_values = [rating.adapter_scores[index].score for rating in ratings]
        deltas = [adapter - base for base, adapter in zip(base_values, adapter_values, strict=True)]
        all_base.extend(base_values)
        all_adapter.extend(adapter_values)
        rubric_results.append(
            ExpertRubricDescriptiveResult(
                rubric_item=rubric_item,
                sample_count=len(ratings),
                base_mean=fmean(base_values),
                adapter_mean=fmean(adapter_values),
                mean_delta_adapter_minus_base=fmean(deltas),
            )
        )

    base_preferences = sum(rating.preferred_variant is ModelVariant.BASE for rating in ratings)
    adapter_preferences = sum(
        rating.preferred_variant is ModelVariant.ADAPTER for rating in ratings
    )
    tie_count = sum(rating.preferred_variant is None for rating in ratings)
    return ExpertDescriptiveSummary(
        rating_count=len(ratings),
        pair_count=len({rating.pair_id for rating in ratings}),
        base_preference_count=base_preferences,
        adapter_preference_count=adapter_preferences,
        tie_count=tie_count,
        rubric_results=tuple(rubric_results),
        overall_base_mean=fmean(all_base),
        overall_adapter_mean=fmean(all_adapter),
        overall_mean_delta_adapter_minus_base=fmean(
            [adapter - base for base, adapter in zip(all_base, all_adapter, strict=True)]
        ),
        disclaimer=EXPERT_EVIDENCE_DISCLAIMER,
        is_expert_judgment=True,
        is_target_user_evidence=False,
        real_user_behavior_validated=False,
    )
