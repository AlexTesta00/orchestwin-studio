"""Immutable workspace requests that bind formal evidence to real OrchesTwin workflow runs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from orchestwin.evaluation.case_campaign import FormalCaseCampaignPlan

_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA1 = re.compile(r"[0-9a-f]{40}")


def _hash(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _validate_segment(value: str, *, label: str) -> None:
    if _SAFE_SEGMENT.fullmatch(value) is None:
        raise ValueError(f"{label} must be a safe path segment")


@dataclass(frozen=True, slots=True)
class CaseStudyRunRequest:
    """One immutable request binding a frozen case to an existing workflow-run identity."""

    schema_version: int
    campaign_id: str
    campaign_content_hash: str
    case_id: str
    case_version: int
    case_content_hash: str
    workflow_run_id: UUID
    platform_commit: str
    execution_profile: str
    requested_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported formal case run request schema version")
        _validate_segment(self.campaign_id, label="campaign ID")
        _validate_segment(self.case_id, label="case ID")
        if _SHA256.fullmatch(self.campaign_content_hash) is None:
            raise ValueError("campaign content hash must be a lowercase SHA-256 digest")
        if isinstance(self.case_version, bool) or self.case_version < 1:
            raise ValueError("formal case run request version must be positive")
        if _SHA256.fullmatch(self.case_content_hash) is None:
            raise ValueError("case content hash must be a lowercase SHA-256 digest")
        if _GIT_SHA1.fullmatch(self.platform_commit) is None:
            raise ValueError("run request platform commit must be a lowercase Git SHA")
        normalized_profile = " ".join(self.execution_profile.split())
        if not normalized_profile or normalized_profile != self.execution_profile:
            raise ValueError("run request execution profile must be normalized")
        if self.requested_at.tzinfo is None:
            raise ValueError("formal case run request timestamp must be timezone-aware")
        if _SHA256.fullmatch(self.content_hash) is None:
            raise ValueError("run request content hash must be a lowercase SHA-256 digest")
        if self.content_hash != _hash(self.to_snapshot(include_hash=False)):
            raise ValueError("formal case run request content hash is inconsistent")

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "schema_version": self.schema_version,
            "campaign_id": self.campaign_id,
            "campaign_content_hash": self.campaign_content_hash,
            "case_id": self.case_id,
            "case_version": self.case_version,
            "case_content_hash": self.case_content_hash,
            "workflow_run_id": str(self.workflow_run_id),
            "platform_commit": self.platform_commit,
            "execution_profile": self.execution_profile,
            "requested_at": self.requested_at.isoformat(),
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


@dataclass(frozen=True, slots=True)
class CaseStudyRunWorkspace:
    """Filesystem layout kept outside the source tree for one formal observed run."""

    root: Path
    request_path: Path
    evidence_dir: Path
    raw_dir: Path
    final_dir: Path


def _request_for_case(
    campaign: FormalCaseCampaignPlan,
    *,
    case_id: str,
    workflow_run_id: UUID,
    requested_at: datetime,
) -> CaseStudyRunRequest:
    matches = [case for case in campaign.cases if case.case_id == case_id]
    if len(matches) != 1:
        raise ValueError("formal case run request must reference exactly one campaign case")
    case = matches[0]
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "campaign_id": campaign.campaign_id,
        "campaign_content_hash": campaign.content_hash,
        "case_id": case.case_id,
        "case_version": case.case_version,
        "case_content_hash": case.case_content_hash,
        "workflow_run_id": str(workflow_run_id),
        "platform_commit": campaign.platform_commit,
        "execution_profile": case.execution_profile,
        "requested_at": requested_at.isoformat(),
    }
    return CaseStudyRunRequest(
        schema_version=1,
        campaign_id=campaign.campaign_id,
        campaign_content_hash=campaign.content_hash,
        case_id=case.case_id,
        case_version=case.case_version,
        case_content_hash=case.case_content_hash,
        workflow_run_id=workflow_run_id,
        platform_commit=campaign.platform_commit,
        execution_profile=case.execution_profile,
        requested_at=requested_at,
        content_hash=_hash(snapshot),
    )


def prepare_case_study_run_workspace(
    base_root: Path,
    campaign: FormalCaseCampaignPlan,
    *,
    case_id: str,
    workflow_run_id: UUID,
    requested_at: datetime,
) -> tuple[CaseStudyRunWorkspace, CaseStudyRunRequest]:
    """Create a new non-overwriting evidence workspace for an already-created workflow run."""
    request = _request_for_case(
        campaign,
        case_id=case_id,
        workflow_run_id=workflow_run_id,
        requested_at=requested_at,
    )
    root = base_root / campaign.campaign_id / case_id / str(workflow_run_id)
    if root.exists():
        raise FileExistsError(f"formal case run workspace already exists: {root}")
    evidence_dir = root / "evidence"
    raw_dir = root / "raw"
    final_dir = root / "final"
    for path in (evidence_dir, raw_dir, final_dir):
        path.mkdir(parents=True, exist_ok=False)
    request_path = root / "run-request.json"
    request_path.write_text(
        f"{json.dumps(request.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    return (
        CaseStudyRunWorkspace(
            root=root,
            request_path=request_path,
            evidence_dir=evidence_dir,
            raw_dir=raw_dir,
            final_dir=final_dir,
        ),
        request,
    )


def load_case_study_run_request(path: Path) -> CaseStudyRunRequest:
    """Load and revalidate an immutable formal case run request."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CaseStudyRunRequest(
        schema_version=payload["schema_version"],
        campaign_id=payload["campaign_id"],
        campaign_content_hash=payload["campaign_content_hash"],
        case_id=payload["case_id"],
        case_version=payload["case_version"],
        case_content_hash=payload["case_content_hash"],
        workflow_run_id=UUID(payload["workflow_run_id"]),
        platform_commit=payload["platform_commit"],
        execution_profile=payload["execution_profile"],
        requested_at=datetime.fromisoformat(payload["requested_at"]),
        content_hash=payload["content_hash"],
    )
