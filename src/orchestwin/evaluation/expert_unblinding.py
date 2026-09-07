"""Post-collection decoding of blinded expert ratings using the separate identity key."""

from __future__ import annotations

from dataclasses import dataclass

from orchestwin.evaluation.expert_blinding import BlindingKey, ModelVariant
from orchestwin.evaluation.expert_rating_validation import ExpertRatingValidationSummary
from orchestwin.evaluation.expert_ratings import ExpertPairRating, ExpertRubricScore


@dataclass(frozen=True, slots=True)
class DecodedExpertPairRating:
    """One expert judgment decoded only after the blinded collection is complete."""

    pair_id: str
    reviewer_id: str
    base_scores: tuple[ExpertRubricScore, ...]
    adapter_scores: tuple[ExpertRubricScore, ...]
    preferred_variant: ModelVariant | None
    comments: str
    is_expert_judgment: bool
    is_target_user_evidence: bool
    real_user_behavior_validated: bool

    def to_snapshot(self) -> dict[str, object]:
        return {
            "pair_id": self.pair_id,
            "reviewer_id": self.reviewer_id,
            "base_scores": [item.to_snapshot() for item in self.base_scores],
            "adapter_scores": [item.to_snapshot() for item in self.adapter_scores],
            "preferred_variant": (
                None if self.preferred_variant is None else self.preferred_variant.value
            ),
            "comments": self.comments,
            "is_expert_judgment": self.is_expert_judgment,
            "is_target_user_evidence": self.is_target_user_evidence,
            "real_user_behavior_validated": self.real_user_behavior_validated,
        }


def decode_expert_ratings_after_collection(
    ratings: tuple[ExpertPairRating, ...],
    keys: tuple[BlindingKey, ...],
    *,
    validation: ExpertRatingValidationSummary,
) -> tuple[DecodedExpertPairRating, ...]:
    """Decode A/B aliases only after a complete blinded rating collection is verified."""
    if not validation.complete:
        raise ValueError("expert identities cannot be decoded before collection is complete")
    if validation.rating_count != len(ratings):
        raise ValueError("expert rating validation summary does not match supplied ratings")
    key_by_pair: dict[str, BlindingKey] = {}
    for key in keys:
        if key.pair_id in key_by_pair:
            raise ValueError("duplicate blinding key for the same pair")
        if {key.candidate_a_variant, key.candidate_b_variant} != {
            ModelVariant.BASE,
            ModelVariant.ADAPTER,
        }:
            raise ValueError("every blinding key must map one BASE and one ADAPTER candidate")
        key_by_pair[key.pair_id] = key

    rating_pair_ids = {rating.pair_id for rating in ratings}
    if set(key_by_pair) != rating_pair_ids:
        raise ValueError("blinding key set does not exactly match the rated pair set")

    decoded: list[DecodedExpertPairRating] = []
    for rating in ratings:
        key = key_by_pair[rating.pair_id]
        score_by_variant = {
            key.candidate_a_variant: rating.candidate_a.scores,
            key.candidate_b_variant: rating.candidate_b.scores,
        }
        preferred_variant = None
        if rating.preference.value == "A":
            preferred_variant = key.candidate_a_variant
        elif rating.preference.value == "B":
            preferred_variant = key.candidate_b_variant
        decoded.append(
            DecodedExpertPairRating(
                pair_id=rating.pair_id,
                reviewer_id=rating.reviewer_id,
                base_scores=score_by_variant[ModelVariant.BASE],
                adapter_scores=score_by_variant[ModelVariant.ADAPTER],
                preferred_variant=preferred_variant,
                comments=rating.comments,
                is_expert_judgment=True,
                is_target_user_evidence=False,
                real_user_behavior_validated=False,
            )
        )
    return tuple(sorted(decoded, key=lambda item: (item.pair_id, item.reviewer_id)))
