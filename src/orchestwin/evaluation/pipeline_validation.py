"""Static integrity verification for the Sprint 12 case-study evidence pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from orchestwin.evaluation.matrix_validation import verify_sprint12_evaluation_matrix


@dataclass(frozen=True, slots=True)
class Sprint12EvidencePipelineSummary:
    """Inspectable scope and protocol summary without fabricated run results."""

    formal_case_ids: tuple[str, ...]
    case_run_contract_version: int
    expert_protocol_id: str
    expert_pair_count: int
    expert_rating_count: int
    reviewer_count: int
    ratings_per_reviewer: int
    mobile_platforms_in_scope: bool
    frozen_training_feedback_allowed: bool
    expert_judgment_is_target_user_evidence: bool
    real_user_behavior_validated: bool
    empirical_user_evidence_created: bool

    def to_snapshot(self) -> dict[str, object]:
        return {
            "formal_case_ids": list(self.formal_case_ids),
            "case_run_contract_version": self.case_run_contract_version,
            "expert_protocol_id": self.expert_protocol_id,
            "expert_pair_count": self.expert_pair_count,
            "expert_rating_count": self.expert_rating_count,
            "reviewer_count": self.reviewer_count,
            "ratings_per_reviewer": self.ratings_per_reviewer,
            "mobile_platforms_in_scope": self.mobile_platforms_in_scope,
            "frozen_training_feedback_allowed": self.frozen_training_feedback_allowed,
            "expert_judgment_is_target_user_evidence": (
                self.expert_judgment_is_target_user_evidence
            ),
            "real_user_behavior_validated": self.real_user_behavior_validated,
            "empirical_user_evidence_created": self.empirical_user_evidence_created,
        }


def verify_sprint12_evidence_pipeline(repo_root: Path) -> Sprint12EvidencePipelineSummary:
    """Verify frozen contracts before any real case run or external expert collection."""
    matrix = verify_sprint12_evaluation_matrix(repo_root)
    case_dir = repo_root / "experiments" / "case-studies"
    run_contract = json.loads((case_dir / "case-run-contract-v1.json").read_text(encoding="utf-8"))
    expert_protocol = json.loads(
        (case_dir / "expert-evaluation-protocol-v1.json").read_text(encoding="utf-8")
    )

    if run_contract["schema_version"] != 1:
        raise ValueError("unexpected case-study run contract version")
    claim_flags = run_contract["permanent_claim_flags"]
    if claim_flags != {
        "real_user_behavior_validated": False,
        "empirical_user_evidence_created": False,
    }:
        raise ValueError("case-study run contract weakens permanent evidence boundaries")

    reviewers = tuple(expert_protocol["reviewer_aliases"])
    if len(reviewers) != 4 or len(reviewers) != len(set(reviewers)):
        raise ValueError("expert protocol requires four unique reviewer aliases")
    pair_count = expert_protocol["pair_count"]
    ratings_per_pair = expert_protocol["ratings_per_pair"]
    ratings_per_reviewer = expert_protocol["ratings_per_reviewer"]
    rating_count = pair_count * ratings_per_pair
    if rating_count != ratings_per_reviewer * len(reviewers):
        raise ValueError("expert protocol rating allocation is not balanced")
    if pair_count != 60 or ratings_per_pair != 2 or ratings_per_reviewer != 30:
        raise ValueError("expert protocol does not match the frozen Sprint 12 design")

    blinding = expert_protocol["blinding"]
    if not all(blinding.values()):
        raise ValueError("expert protocol requires complete identity blinding controls")
    collection = expert_protocol["collection"]
    if not collection["same_rubric_for_all_pairs"]:
        raise ValueError("expert protocol requires the same rubric for all pairs")
    if not collection["raw_ratings_preserved"] or not collection["raw_comments_preserved"]:
        raise ValueError("expert protocol must preserve raw ratings and comments")
    if collection["prompt_or_model_tuning_after_collection_starts"]:
        raise ValueError("expert protocol must freeze prompts and model variants during collection")

    interpretation = expert_protocol["interpretation"]
    forbidden_true = (
        "expert_judgment_is_target_user_evidence",
        "real_user_behavior_validated",
        "empirical_user_evidence_created",
        "frozen_training_feedback_allowed",
    )
    if any(interpretation[key] for key in forbidden_true):
        raise ValueError("expert protocol weakens Sprint 12 evidence or training boundaries")
    if not interpretation["descriptive_analysis_only"]:
        raise ValueError("Sprint 12 expert analysis must remain descriptive")

    return Sprint12EvidencePipelineSummary(
        formal_case_ids=matrix.formal_case_ids,
        case_run_contract_version=run_contract["schema_version"],
        expert_protocol_id=expert_protocol["protocol_id"],
        expert_pair_count=pair_count,
        expert_rating_count=rating_count,
        reviewer_count=len(reviewers),
        ratings_per_reviewer=ratings_per_reviewer,
        mobile_platforms_in_scope=matrix.mobile_platforms_in_scope,
        frozen_training_feedback_allowed=interpretation["frozen_training_feedback_allowed"],
        expert_judgment_is_target_user_evidence=(
            interpretation["expert_judgment_is_target_user_evidence"]
        ),
        real_user_behavior_validated=interpretation["real_user_behavior_validated"],
        empirical_user_evidence_created=interpretation["empirical_user_evidence_created"],
    )
