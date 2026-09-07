"""Cross-cutting integrity checks for the governed Sprint 12 formal case execution path."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from orchestwin.evaluation.case_campaign import (
    CaseCampaignPhase,
    build_formal_case_campaign_plan,
)
from orchestwin.evaluation.pipeline_validation import verify_sprint12_evidence_pipeline


@dataclass(frozen=True, slots=True)
class Sprint12CaseExecutionPipelineSummary:
    """Inspectable readiness summary before real formal case results are materialized."""

    campaign_id: str
    formal_case_ids: tuple[str, ...]
    required_execution_profiles: tuple[str, ...]
    phases: tuple[str, ...]
    actual_files_only: bool
    observed_measurements_only: bool
    owner_gates_must_not_be_bypassed: bool
    jvm_validation_is_separate_fixture_matrix: bool
    mobile_platforms_in_scope: bool
    real_user_behavior_validated: bool
    empirical_user_evidence_created: bool

    def to_snapshot(self) -> dict[str, object]:
        return {
            "campaign_id": self.campaign_id,
            "formal_case_ids": list(self.formal_case_ids),
            "required_execution_profiles": list(self.required_execution_profiles),
            "phases": list(self.phases),
            "actual_files_only": self.actual_files_only,
            "observed_measurements_only": self.observed_measurements_only,
            "owner_gates_must_not_be_bypassed": self.owner_gates_must_not_be_bypassed,
            "jvm_validation_is_separate_fixture_matrix": (
                self.jvm_validation_is_separate_fixture_matrix
            ),
            "mobile_platforms_in_scope": self.mobile_platforms_in_scope,
            "real_user_behavior_validated": self.real_user_behavior_validated,
            "empirical_user_evidence_created": self.empirical_user_evidence_created,
        }


def verify_sprint12_case_execution_pipeline(
    repo_root: Path,
    *,
    platform_commit: str,
) -> Sprint12CaseExecutionPipelineSummary:
    """Verify that real case capture is generic, evidence-backed, and within revised scope."""
    evidence_summary = verify_sprint12_evidence_pipeline(repo_root)
    campaign = build_formal_case_campaign_plan(repo_root, platform_commit=platform_commit)
    formal_case_ids = tuple(case.case_id for case in campaign.cases)
    if formal_case_ids != evidence_summary.formal_case_ids:
        raise ValueError(
            "case execution campaign and frozen evidence pipeline disagree on case IDs"
        )
    if campaign.phases != tuple(CaseCampaignPhase):
        raise ValueError("case execution campaign phases differ from the governed phase contract")
    if not campaign.actual_files_only or not campaign.observed_measurements_only:
        raise ValueError("case execution pipeline permits non-observed formal evidence")
    if not campaign.owner_gates_must_not_be_bypassed:
        raise ValueError("case execution pipeline permits bypassing owner gates")

    jvm_payload = json.loads(
        (repo_root / "experiments" / "case-studies" / "jvm-validation-v1.json").read_text(
            encoding="utf-8"
        )
    )
    jvm_separate = jvm_payload["formal_case_study"] is False
    if not jvm_separate:
        raise ValueError(
            "JVM technical validation must remain separate from the three formal cases"
        )

    required_profiles = tuple(sorted({case.execution_profile for case in campaign.cases}))
    return Sprint12CaseExecutionPipelineSummary(
        campaign_id=campaign.campaign_id,
        formal_case_ids=formal_case_ids,
        required_execution_profiles=required_profiles,
        phases=tuple(phase.value for phase in campaign.phases),
        actual_files_only=campaign.actual_files_only,
        observed_measurements_only=campaign.observed_measurements_only,
        owner_gates_must_not_be_bypassed=campaign.owner_gates_must_not_be_bypassed,
        jvm_validation_is_separate_fixture_matrix=jvm_separate,
        mobile_platforms_in_scope=evidence_summary.mobile_platforms_in_scope,
        real_user_behavior_validated=campaign.real_user_behavior_validated,
        empirical_user_evidence_created=campaign.empirical_user_evidence_created,
    )
