"""Exact, single-use Web operation approvals without Docker or database writes."""

import asyncio
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from orchestwin.web_execution.operation_governance import (
    WebGovernedOperation,
    WebOperationError,
    WebOperationScope,
    WebOperationState,
)
from orchestwin.web_execution.operation_persistence import record_from_row, record_values
from orchestwin.workflow.gates import HumanGateAction, HumanGateStatus

OWNER, PROJECT, SOURCE = UUID(int=1), UUID(int=2), UUID(int=3)
NOW = datetime(2026, 9, 12, tzinfo=UTC)


class MemoryScope(WebOperationScope):
    def __init__(self):
        self.owner_user_id, self.project_id = OWNER, PROJECT
        self.records, self.gates, self.events = {}, {}, []

    async def source_owned(self, source_revision_id):
        return source_revision_id == SOURCE

    async def get(self, operation_id):
        return self.records.get(operation_id)

    async def history(self, kind=None):
        return tuple(item for item in self.records.values() if kind is None or item.kind == kind)

    async def insert(self, operation):
        self.records[operation.id] = operation

    async def update(self, previous, updated):
        if self.records.get(previous.id) != previous:
            raise WebOperationError("WEB_OPERATION_STATE_CONFLICT")
        self.records[updated.id] = updated

    async def latest_gate(self):
        return next(reversed(self.gates.values()), None)

    async def load_gate(self, gate_id):
        return self.gates.get(gate_id)

    async def add_gate(self, gate, event):
        self.gates[gate.id] = gate
        self.events.append(event)

    async def save_gate(self, previous, updated, event):
        assert self.gates[previous.id] == previous
        self.gates[updated.id] = updated
        self.events.append(event)


async def proposed(scope, payload=None, **kwargs):
    return await scope.propose(
        source_revision_id=SOURCE,
        kind="EXECUTION",
        payload=payload or {"purpose": "PROFILE_VALIDATION", "source_hash": "a" * 64},
        **kwargs,
    )


async def approved(scope):
    operation = await proposed(scope)
    gate = await scope.gate(operation)
    return await scope.decide(
        operation,
        expected_hash=operation.content_hash,
        expected_event_sequence=gate.event_sequence,
        action=HumanGateAction.APPROVE,
    )


def test_distinct_operations_get_their_own_gate_budget_and_monotonic_sequence():
    async def scenario():
        scope = MemoryScope()
        gate_budgets = []
        for index in range(5):
            operation = await scope.propose(
                source_revision_id=SOURCE,
                kind="EXECUTION" if index % 2 == 0 else "REPAIR",
                payload={"index": index},
            )
            gate = await scope.gate(operation)
            assert gate.iteration == index + 1
            gate_budgets.append(gate.max_iterations - gate.iteration + 1)
            assert (await scope.latest_gate()).id == gate.id
            await scope.decide(
                operation,
                expected_hash=operation.content_hash,
                expected_event_sequence=gate.event_sequence,
                action=HumanGateAction.APPROVE,
            )
            running = await scope.claim(operation, expected_hash=operation.content_hash)
            await scope.finish(running, result={"index": index}, succeeded=True)
        assert len(scope.records) == 5
        assert gate_budgets == [3] * 5

    asyncio.run(scenario())


def test_payload_and_result_are_copied_and_hash_binding_is_immutable():
    payload = {"nested": {"values": [1, "two"]}}
    operation = WebGovernedOperation.create(
        project_id=PROJECT,
        owner_user_id=OWNER,
        source_revision_id=SOURCE,
        kind="EXECUTION",
        payload=payload,
        created_at=NOW,
    )
    before = operation.content_hash
    payload["nested"]["values"].append("untrusted mutation")
    operation.payload["nested"]["values"].append("another mutation")
    assert operation.payload == {"nested": {"values": [1, "two"]}}
    assert operation.content_hash == before
    assert record_from_row(record_values(operation)) == operation


def test_operation_hash_survives_postgresql_timestamp_timezone_normalization():
    operation = WebGovernedOperation.create(
        project_id=PROJECT,
        owner_user_id=OWNER,
        source_revision_id=SOURCE,
        kind="EXECUTION",
        payload={"plan": "x"},
        created_at=NOW.astimezone(timezone(timedelta(hours=2))),
    )
    row = record_values(operation)
    row["created_at"] = row["created_at"].astimezone(UTC)
    restored = record_from_row(row)
    assert restored.content_hash == operation.content_hash


@pytest.mark.parametrize(
    "field",
    ["content_hash", "payload_content_hash", "payload_json", "owner_user_id", "source_revision_id"],
)
def test_record_projection_or_payload_tampering_is_rejected(field):
    operation = WebGovernedOperation.create(
        project_id=PROJECT,
        owner_user_id=OWNER,
        source_revision_id=SOURCE,
        kind="REPAIR",
        payload={"change_set": "b" * 64},
        created_at=NOW,
    )
    row = record_values(operation)
    row[field] = "corrupt"
    with pytest.raises(WebOperationError, match="INTEGRITY"):
        record_from_row(row)


@pytest.mark.parametrize(
    "payload",
    [{"x": float("nan")}, {"x": float("inf")}, {"x": b"bytes"}, {"x": "a" * (4 * 1024 * 1024)}],
)
def test_non_json_or_over_budget_payloads_are_rejected(payload):
    with pytest.raises(WebOperationError):
        WebGovernedOperation.create(
            project_id=PROJECT,
            owner_user_id=OWNER,
            source_revision_id=SOURCE,
            kind="REPAIR",
            payload=payload,
            created_at=NOW,
        )


def test_propose_submits_exact_gate_and_cannot_claim_before_approval():
    async def scenario():
        scope = MemoryScope()
        operation = await proposed(scope)
        gate = await scope.gate(operation)
        assert gate.status is HumanGateStatus.PENDING_APPROVAL
        assert gate.artifact.artifact_id == operation.id
        assert gate.artifact.content_hash == operation.content_hash
        assert gate.artifact.version == 1
        assert gate.event_sequence == 1
        with pytest.raises(WebOperationError, match="APPROVAL_REQUIRED"):
            await scope.claim(operation, expected_hash=operation.content_hash)
        assert len(scope.events) == 1

    asyncio.run(scenario())


def test_exact_approval_is_single_use_and_terminal_state_prevents_replay():
    async def scenario():
        scope = MemoryScope()
        operation = await approved(scope)
        running = await scope.claim(operation, expected_hash=operation.content_hash)
        assert running.state is WebOperationState.RUNNING
        assert running.content_hash == operation.content_hash
        with pytest.raises(WebOperationError, match=r"STATE|CLAIM"):
            await scope.claim(operation, expected_hash=operation.content_hash)
        with pytest.raises(WebOperationError, match="RUNNING"):
            await proposed(scope)
        completed = await scope.finish(
            running,
            result={"attempt_id": str(UUID(int=4)), "cleanup_confirmed": True},
            succeeded=True,
        )
        assert completed.state is WebOperationState.COMPLETED
        assert completed.content_hash == operation.content_hash
        assert completed.started_at is not None and completed.finished_at >= completed.started_at
        assert record_from_row(record_values(completed)) == completed
        with pytest.raises(WebOperationError, match=r"STATE|CLAIM"):
            await scope.claim(completed, expected_hash=completed.content_hash)

    asyncio.run(scenario())


def test_approval_rejects_stale_hash_and_event_sequence_without_transition():
    async def scenario():
        scope = MemoryScope()
        operation = await proposed(scope)
        for expected_hash, sequence in [("f" * 64, 1), (operation.content_hash, 2)]:
            with pytest.raises(WebOperationError):
                await scope.decide(
                    operation,
                    expected_hash=expected_hash,
                    expected_event_sequence=sequence,
                    action=HumanGateAction.APPROVE,
                )
        assert (await scope.gate(operation)).status is HumanGateStatus.PENDING_APPROVAL
        assert len(scope.events) == 1

    asyncio.run(scenario())


def test_new_operation_cannot_silently_replace_pending_gate():
    async def scenario():
        scope = MemoryScope()
        await proposed(scope)
        with pytest.raises(WebOperationError, match="GATE"):
            await proposed(scope)
        assert len(scope.records) == 1

    asyncio.run(scenario())


def test_new_operation_stales_old_approved_gate_and_prevents_old_claim():
    async def scenario():
        scope = MemoryScope()
        first = await approved(scope)
        second = await proposed(scope, {"other": "plan"})
        assert (await scope.gate(first)).status is HumanGateStatus.STALE
        assert (await scope.snapshot(first))["gate_current"] is False
        assert (await scope.snapshot(second))["gate_current"] is True
        with pytest.raises(WebOperationError, match="GATE"):
            await scope.claim(first, expected_hash=first.content_hash)

    asyncio.run(scenario())


def test_cancel_before_execution_marks_failed_without_inventing_started_time():
    async def scenario():
        scope = MemoryScope()
        operation = await proposed(scope)
        cancelled = await scope.decide(
            operation,
            expected_hash=operation.content_hash,
            expected_event_sequence=1,
            action=HumanGateAction.CANCEL,
        )
        assert cancelled.state is WebOperationState.FAILED
        assert cancelled.started_at is None and cancelled.finished_at is not None
        assert cancelled.result["execution_started"] is False
        assert record_from_row(record_values(cancelled)) == cancelled
        with pytest.raises(WebOperationError):
            await scope.claim(cancelled, expected_hash=cancelled.content_hash)

    asyncio.run(scenario())


def test_failure_after_claim_remains_failed_and_result_is_immutable():
    async def scenario():
        scope = MemoryScope()
        operation = await approved(scope)
        running = await scope.claim(operation, expected_hash=operation.content_hash)
        failed = await scope.finish(
            running,
            result={"failure_code": "CANCELLED", "cleanup_confirmed": True},
            succeeded=False,
        )
        assert failed.state is WebOperationState.FAILED
        assert failed.started_at is not None
        with pytest.raises(WebOperationError):
            await scope.finish(failed, result={"passed": True}, succeeded=True)

    asyncio.run(scenario())


def test_foreign_source_cannot_create_gate_or_operation():
    async def scenario():
        scope = MemoryScope()
        with pytest.raises(WebOperationError, match="SOURCE"):
            await scope.propose(source_revision_id=UUID(int=99), kind="REPAIR", payload={"x": 1})
        assert not scope.events and not scope.records

    asyncio.run(scenario())
