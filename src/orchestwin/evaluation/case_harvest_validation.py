"""Cross-case validation of the observed-evidence harvesting layer for Sprint 12."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from orchestwin.evaluation.case_metric_bindings import METRIC_FIELD_TYPES
from orchestwin.evaluation.matrix_validation import verify_sprint12_evaluation_matrix


@dataclass(frozen=True, slots=True)
class Sprint12HarvestContractSummary:
    """Thesis-safe summary of what the evidence harvester can and cannot claim."""

    formal_case_ids: tuple[str, ...]
    metric_field_count: int
    binding_kind: str
    source_truth: str
    actual_file_values_required: bool
    fabricated_values_allowed: bool
    case_specific_logic_allowed: bool
    mobile_platforms_in_scope: bool
    real_user_behavior_validated: bool
    empirical_user_evidence_created: bool

    def to_snapshot(self) -> dict[str, object]:
        return {
            "formal_case_ids": list(self.formal_case_ids),
            "metric_field_count": self.metric_field_count,
            "binding_kind": self.binding_kind,
            "source_truth": self.source_truth,
            "actual_file_values_required": self.actual_file_values_required,
            "fabricated_values_allowed": self.fabricated_values_allowed,
            "case_specific_logic_allowed": self.case_specific_logic_allowed,
            "mobile_platforms_in_scope": self.mobile_platforms_in_scope,
            "real_user_behavior_validated": self.real_user_behavior_validated,
            "empirical_user_evidence_created": self.empirical_user_evidence_created,
        }


def verify_sprint12_case_harvest_contract(repo_root: Path) -> Sprint12HarvestContractSummary:
    """Verify the generic harvester remains aligned with frozen scope and evidence boundaries."""
    matrix = verify_sprint12_evaluation_matrix(repo_root)
    contract = json.loads(
        (
            repo_root / "experiments" / "case-studies" / "observed-metric-bindings-contract-v1.json"
        ).read_text(encoding="utf-8")
    )
    contract_fields = {item["field"] for item in contract["required_fields"]}
    if contract_fields != set(METRIC_FIELD_TYPES):
        raise ValueError("metric-binding contract differs from the executable harvester fields")
    if not contract["values_must_be_read_from_source"]:
        raise ValueError("formal metric harvesting must read values from actual evidence files")
    if contract["fabricated_values_allowed"] or contract["case_specific_logic_allowed"]:
        raise ValueError("formal metric harvesting permits fabricated or case-specific logic")
    return Sprint12HarvestContractSummary(
        formal_case_ids=matrix.formal_case_ids,
        metric_field_count=len(METRIC_FIELD_TYPES),
        binding_kind=contract["binding_kind"],
        source_truth=contract["source_truth"],
        actual_file_values_required=contract["values_must_be_read_from_source"],
        fabricated_values_allowed=contract["fabricated_values_allowed"],
        case_specific_logic_allowed=contract["case_specific_logic_allowed"],
        mobile_platforms_in_scope=matrix.mobile_platforms_in_scope,
        real_user_behavior_validated=False,
        empirical_user_evidence_created=False,
    )
