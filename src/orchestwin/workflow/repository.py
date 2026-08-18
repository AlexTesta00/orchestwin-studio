"""Repository ports for persisted human gates and audit events."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateEvent,
    HumanGateType,
)


class HumanGateStateConflict(RuntimeError):
    """Raised when a persisted gate changed concurrently."""


class HumanGateRepository(Protocol):
    """Owner-scoped persistence operations for human gates."""

    async def add_with_event(
        self,
        *,
        gate: HumanGate,
        event: HumanGateEvent,
    ) -> HumanGate:
        """Persist a newly submitted gate and its first event."""

    async def get_latest_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_type: HumanGateType,
    ) -> HumanGate | None:
        """Lock and return the latest gate iteration for an owner."""

    async def save_transition(
        self,
        *,
        previous_gate: HumanGate,
        updated_gate: HumanGate,
        event: HumanGateEvent,
    ) -> HumanGate:
        """Persist one compare-and-set transition and append its event."""

    async def list_events_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        """Return the append-only event history for an owned gate."""
