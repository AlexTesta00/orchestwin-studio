"""Generic campaign planning for governed Sprint 12 formal case executions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from orchestwin.evaluation.case_studies import (
    CaseStudyDefinition,
    EvaluationFamily,
    load_case_study_definition,
)

_GIT_SHA1_PATTERN: Final = re.compile(r"[0-9a-f]{40}")
_CAMPAIGN_FILE: Final = "case-execution-campaign-v1.json"


class CaseCampaignPhase(StrEnum):
    """Governed phases shared by every formal case; no case-specific generator is encoded."""

    PREFLIGHT = "PREFLIGHT"
    WORKFLOW = "WORKFLOW"
    BUILD = "BUILD"
    TEST = "TEST"
    RUNTIME = "RUNTIME"
    SYNTHETIC_EVALUATION = "SYNTHETIC_EVALUATION"
    EXPORT = "EXPORT"
    FINALIZE = "FINALIZE"


def _hash(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CaseExecutionPlan:
    """One frozen case routed through an existing generic execution profile."""

    case_id: str
    case_version: int
    case_content_hash: str
    execution_profile: str
    technologies: tuple[str, ...]
    definition_path: str

    def to_snapshot(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "case_version": self.case_version,
            "case_content_hash": self.case_content_hash,
            "execution_profile": self.execution_profile,
            "technologies": list(self.technologies),
            "definition_path": self.definition_path,
        }


@dataclass(frozen=True, slots=True)
class FormalCaseCampaignPlan:
    """Immutable campaign plan pinned to one platform commit for comparable final runs."""

    schema_version: int
    campaign_id: str
    platform_commit: str
    phases: tuple[CaseCampaignPhase, ...]
    cases: tuple[CaseExecutionPlan, ...]
    actual_files_only: bool
    observed_measurements_only: bool
    owner_gates_must_not_be_bypassed: bool
    real_user_behavior_validated: bool
    empirical_user_evidence_created: bool
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported formal case campaign schema version")
        if _GIT_SHA1_PATTERN.fullmatch(self.platform_commit) is None:
            raise ValueError("campaign platform commit must be a lowercase 40-character Git SHA")
        if not self.cases:
            raise ValueError("formal case campaign must contain at least one case")
        case_ids = tuple(item.case_id for item in self.cases)
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("formal case campaign contains duplicate case IDs")
        if not self.actual_files_only or not self.observed_measurements_only:
            raise ValueError("formal case campaign must require observed evidence")
        if not self.owner_gates_must_not_be_bypassed:
            raise ValueError("formal case campaign must preserve owner approval gates")
        if self.real_user_behavior_validated or self.empirical_user_evidence_created:
            raise ValueError("formal case campaign must preserve conservative evidence claims")
        if self.content_hash != _hash(self.to_snapshot(include_hash=False)):
            raise ValueError("formal case campaign content hash is inconsistent")

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "schema_version": self.schema_version,
            "campaign_id": self.campaign_id,
            "platform_commit": self.platform_commit,
            "phases": [phase.value for phase in self.phases],
            "cases": [case.to_snapshot() for case in self.cases],
            "actual_files_only": self.actual_files_only,
            "observed_measurements_only": self.observed_measurements_only,
            "owner_gates_must_not_be_bypassed": self.owner_gates_must_not_be_bypassed,
            "real_user_behavior_validated": self.real_user_behavior_validated,
            "empirical_user_evidence_created": self.empirical_user_evidence_created,
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def _load_formal_definitions(
    case_dir: Path,
    formal_case_ids: tuple[str, ...],
) -> tuple[tuple[CaseStudyDefinition, Path], ...]:
    discovered: dict[str, Path] = {}
    for path in sorted(case_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        case_id = payload.get("case_id")
        if case_id in formal_case_ids:
            discovered[str(case_id)] = path
    missing = [case_id for case_id in formal_case_ids if case_id not in discovered]
    if missing:
        raise ValueError(f"formal case definitions are missing: {', '.join(missing)}")
    return tuple(
        (load_case_study_definition(discovered[case_id]), discovered[case_id])
        for case_id in formal_case_ids
    )


def build_formal_case_campaign_plan(
    repo_root: Path,
    *,
    platform_commit: str,
) -> FormalCaseCampaignPlan:
    """Build the generic campaign from frozen definitions without case-specific generation logic."""
    case_dir = repo_root / "experiments" / "case-studies"
    payload = json.loads((case_dir / _CAMPAIGN_FILE).read_text(encoding="utf-8"))
    if payload["schema_version"] != 1:
        raise ValueError("unsupported campaign definition version")
    formal_case_ids = tuple(payload["formal_case_ids"])
    loaded = _load_formal_definitions(case_dir, formal_case_ids)
    plans: list[CaseExecutionPlan] = []
    for definition, path in loaded:
        if definition.family is not EvaluationFamily.WEB:
            raise ValueError("formal Sprint 12 cases must use the Web execution family")
        plans.append(
            CaseExecutionPlan(
                case_id=definition.case_id,
                case_version=definition.version,
                case_content_hash=definition.content_hash,
                execution_profile=definition.execution_profile,
                technologies=definition.technologies,
                definition_path=path.relative_to(repo_root).as_posix(),
            )
        )
    phases = tuple(CaseCampaignPhase(item) for item in payload["execution_phases"])
    comparison = payload["comparison_policy"]
    evidence = payload["evidence_policy"]
    claims = payload["permanent_claim_flags"]
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "campaign_id": payload["campaign_id"],
        "platform_commit": platform_commit,
        "phases": [phase.value for phase in phases],
        "cases": [case.to_snapshot() for case in plans],
        "actual_files_only": evidence["actual_files_only"],
        "observed_measurements_only": evidence["observed_measurements_only"],
        "owner_gates_must_not_be_bypassed": comparison["owner_approval_gates_must_not_be_bypassed"],
        "real_user_behavior_validated": claims["real_user_behavior_validated"],
        "empirical_user_evidence_created": claims["empirical_user_evidence_created"],
    }
    return FormalCaseCampaignPlan(
        schema_version=1,
        campaign_id=payload["campaign_id"],
        platform_commit=platform_commit,
        phases=phases,
        cases=tuple(plans),
        actual_files_only=evidence["actual_files_only"],
        observed_measurements_only=evidence["observed_measurements_only"],
        owner_gates_must_not_be_bypassed=comparison["owner_approval_gates_must_not_be_bypassed"],
        real_user_behavior_validated=claims["real_user_behavior_validated"],
        empirical_user_evidence_created=claims["empirical_user_evidence_created"],
        content_hash=_hash(snapshot),
    )
