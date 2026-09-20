"""Content-addressed observations of owner gate decisions during formal case runs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from uuid import UUID

from orchestwin.evaluation.case_launch_inputs import FormalGateType

_SHA256 = re.compile(r"[0-9a-f]{64}")
_ALLOWED_ACTIONS = frozenset(
    {"SUBMIT", "APPROVE", "REJECT", "REQUEST_REVISION", "PAUSE", "RESUME", "CANCEL"}
)
_ALLOWED_STATUSES = frozenset(
    {
        "DRAFT",
        "PENDING_APPROVAL",
        "APPROVED",
        "REJECTED",
        "REVISION_REQUESTED",
        "PAUSED",
        "CANCELLED",
        "STALE",
        "PAUSED_NEEDS_HUMAN",
    }
)


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _normalized_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if not normalized or normalized != value:
        raise ValueError("gate observation reason must be normalized")
    if len(value) > 2_000:
        raise ValueError("gate observation reason exceeds maximum length")
    return value


@dataclass(frozen=True, slots=True)
class ObservedGateDecision:
    """One owner transition copied from an observed OrchesTwin gate event snapshot."""

    gate_type: FormalGateType
    gate_id: UUID
    source_event_id: UUID
    sequence_number: int
    action: str
    resulting_status: str
    artifact_id: UUID
    artifact_version: int
    artifact_content_hash: str
    actor_user_id: UUID
    occurred_at: datetime
    source_snapshot_sha256: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.sequence_number < 1:
            raise ValueError("gate observation sequence number must be positive")
        if self.action not in _ALLOWED_ACTIONS:
            raise ValueError("gate observation action is unsupported")
        if self.resulting_status not in _ALLOWED_STATUSES:
            raise ValueError("gate observation resulting status is unsupported")
        if self.artifact_version < 1:
            raise ValueError("gate observation artifact version must be positive")
        for value, label in (
            (self.artifact_content_hash, "gate artifact hash"),
            (self.source_snapshot_sha256, "gate source snapshot hash"),
        ):
            if _SHA256.fullmatch(value) is None:
                raise ValueError(f"{label} must be a lowercase SHA-256 digest")
        if self.occurred_at.tzinfo is None:
            raise ValueError("gate observation timestamp must be timezone-aware")
        _normalized_optional(self.reason)

    @property
    def sort_key(self) -> tuple[str, int, str]:
        return (self.occurred_at.isoformat(), self.sequence_number, self.source_event_id.hex)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "gate_type": self.gate_type.value,
            "gate_id": str(self.gate_id),
            "source_event_id": str(self.source_event_id),
            "sequence_number": self.sequence_number,
            "action": self.action,
            "resulting_status": self.resulting_status,
            "artifact_id": str(self.artifact_id),
            "artifact_version": self.artifact_version,
            "artifact_content_hash": self.artifact_content_hash,
            "actor_user_id": str(self.actor_user_id),
            "occurred_at": self.occurred_at.isoformat(),
            "source_snapshot_sha256": self.source_snapshot_sha256,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class FormalCaseGateJournal:
    """Immutable gate-event journal that records evidence but does not control the workflow."""

    schema_version: int
    case_id: str
    workflow_run_id: UUID
    observations: tuple[ObservedGateDecision, ...]
    real_user_behavior_validated: bool
    empirical_user_evidence_created: bool
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported gate journal schema version")
        if not self.case_id or self.case_id != " ".join(self.case_id.split()):
            raise ValueError("gate journal case ID must be normalized")
        if self.observations != tuple(sorted(self.observations, key=lambda item: item.sort_key)):
            raise ValueError("gate journal observations must use canonical order")
        event_ids = tuple(item.source_event_id for item in self.observations)
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("gate journal source event IDs must be unique")
        if self.real_user_behavior_validated or self.empirical_user_evidence_created:
            raise ValueError("gate journal must preserve conservative user-evidence claims")
        if _SHA256.fullmatch(self.content_hash) is None:
            raise ValueError("gate journal content hash must be a lowercase SHA-256 digest")
        if self.content_hash != _hash(self.to_snapshot(include_hash=False)):
            raise ValueError("gate journal content hash is inconsistent")

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "workflow_run_id": str(self.workflow_run_id),
            "observations": [item.to_snapshot() for item in self.observations],
            "real_user_behavior_validated": self.real_user_behavior_validated,
            "empirical_user_evidence_created": self.empirical_user_evidence_created,
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def create_gate_journal(*, case_id: str, workflow_run_id: UUID) -> FormalCaseGateJournal:
    """Create an empty content-addressed journal before any owner gate is observed."""
    snapshot = {
        "schema_version": 1,
        "case_id": case_id,
        "workflow_run_id": str(workflow_run_id),
        "observations": [],
        "real_user_behavior_validated": False,
        "empirical_user_evidence_created": False,
    }
    return FormalCaseGateJournal(
        schema_version=1,
        case_id=case_id,
        workflow_run_id=workflow_run_id,
        observations=(),
        real_user_behavior_validated=False,
        empirical_user_evidence_created=False,
        content_hash=_hash(snapshot),
    )


def append_gate_decision(
    journal: FormalCaseGateJournal,
    decision: ObservedGateDecision,
) -> FormalCaseGateJournal:
    """Return a new journal containing one additional observed source event."""
    observations = tuple(sorted((*journal.observations, decision), key=lambda item: item.sort_key))
    snapshot = {
        "schema_version": journal.schema_version,
        "case_id": journal.case_id,
        "workflow_run_id": str(journal.workflow_run_id),
        "observations": [item.to_snapshot() for item in observations],
        "real_user_behavior_validated": False,
        "empirical_user_evidence_created": False,
    }
    return replace(journal, observations=observations, content_hash=_hash(snapshot))


def write_gate_journal(path: Path, journal: FormalCaseGateJournal) -> None:
    """Atomically persist the complete journal snapshot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(journal.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_gate_journal(path: Path) -> FormalCaseGateJournal:
    """Load a journal and re-run all integrity checks."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    observations = tuple(
        ObservedGateDecision(
            gate_type=FormalGateType(item["gate_type"]),
            gate_id=UUID(item["gate_id"]),
            source_event_id=UUID(item["source_event_id"]),
            sequence_number=item["sequence_number"],
            action=item["action"],
            resulting_status=item["resulting_status"],
            artifact_id=UUID(item["artifact_id"]),
            artifact_version=item["artifact_version"],
            artifact_content_hash=item["artifact_content_hash"],
            actor_user_id=UUID(item["actor_user_id"]),
            occurred_at=datetime.fromisoformat(item["occurred_at"]),
            source_snapshot_sha256=item["source_snapshot_sha256"],
            reason=item["reason"],
        )
        for item in payload["observations"]
    )
    return FormalCaseGateJournal(
        schema_version=payload["schema_version"],
        case_id=payload["case_id"],
        workflow_run_id=UUID(payload["workflow_run_id"]),
        observations=observations,
        real_user_behavior_validated=payload["real_user_behavior_validated"],
        empirical_user_evidence_created=payload["empirical_user_evidence_created"],
        content_hash=payload["content_hash"],
    )
