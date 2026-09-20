"""Prepare operator metadata inside an existing formal case-study evidence workspace."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from orchestwin.evaluation.case_gate_journal import create_gate_journal, write_gate_journal
from orchestwin.evaluation.case_launch_inputs import FormalCaseLaunchInput

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _hash(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FormalCaseOperatorSession:
    """Identity-only session metadata; it never represents a successful case result."""

    schema_version: int
    case_id: str
    project_id: UUID
    workflow_run_id: UUID
    launch_input_hash: str
    prepared_at: datetime
    status: str
    owner_gates_required: bool
    observed_result_available: bool
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported operator session schema version")
        if _SHA256.fullmatch(self.launch_input_hash) is None:
            raise ValueError("operator session launch hash must be a lowercase SHA-256 digest")
        if self.prepared_at.tzinfo is None:
            raise ValueError("operator session timestamp must be timezone-aware")
        if self.status != "PREPARED":
            raise ValueError("a newly initialized operator session must be PREPARED")
        if not self.owner_gates_required:
            raise ValueError("formal operator sessions must preserve owner gates")
        if self.observed_result_available:
            raise ValueError("preparing a session must not fabricate an observed result")
        if _SHA256.fullmatch(self.content_hash) is None:
            raise ValueError("operator session content hash must be a lowercase SHA-256 digest")
        if self.content_hash != _hash(self.to_snapshot(include_hash=False)):
            raise ValueError("operator session content hash is inconsistent")

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "project_id": str(self.project_id),
            "workflow_run_id": str(self.workflow_run_id),
            "launch_input_hash": self.launch_input_hash,
            "prepared_at": self.prepared_at.isoformat(),
            "status": self.status,
            "owner_gates_required": self.owner_gates_required,
            "observed_result_available": self.observed_result_available,
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def initialize_case_operator_session(
    *,
    workspace_root: Path,
    launch: FormalCaseLaunchInput,
    project_id: UUID,
    workflow_run_id: UUID,
    prepared_at: datetime,
) -> FormalCaseOperatorSession:
    """Attach launch and gate-capture metadata to a workspace created by Sprint 12 C27."""
    for name in ("evidence", "raw", "final"):
        directory = workspace_root / name
        if not directory.exists() or not directory.is_dir():
            raise ValueError(f"formal workspace is missing required directory: {name}")
    raw_dir = workspace_root / "raw"
    launch_path = raw_dir / "launch-input.json"
    journal_path = raw_dir / "gate-journal.json"
    session_path = raw_dir / "operator-session.json"
    collisions = [path for path in (launch_path, journal_path, session_path) if path.exists()]
    if collisions:
        raise FileExistsError(f"formal operator session already initialized: {collisions[0]}")

    launch_path.write_text(
        json.dumps(launch.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_gate_journal(
        journal_path,
        create_gate_journal(case_id=launch.case_id, workflow_run_id=workflow_run_id),
    )
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "case_id": launch.case_id,
        "project_id": str(project_id),
        "workflow_run_id": str(workflow_run_id),
        "launch_input_hash": launch.content_hash,
        "prepared_at": prepared_at.isoformat(),
        "status": "PREPARED",
        "owner_gates_required": True,
        "observed_result_available": False,
    }
    session = FormalCaseOperatorSession(
        schema_version=1,
        case_id=launch.case_id,
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        launch_input_hash=launch.content_hash,
        prepared_at=prepared_at,
        status="PREPARED",
        owner_gates_required=True,
        observed_result_available=False,
        content_hash=_hash(snapshot),
    )
    session_path.write_text(
        json.dumps(session.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return session
