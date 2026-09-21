"""Exercise real gates, service, browser decoder and executor with explicit I/O doubles."""

import asyncio
import json
from dataclasses import replace
from uuid import uuid4

import pytest

from orchestwin.web_execution.static_inspections import (
    InspectionError,
    InspectionPlan,
    InspectionState,
)
from orchestwin.workflow.gates import HumanGateAction, HumanGateStatus

from .static_inspection_support import approve, prepare, setup_service


def test_prepare_persists_pending_gate_and_never_executes(tmp_path):
    service, store, backend, args = setup_service(tmp_path)
    result = asyncio.run(prepare(service, backend, args))
    assert result["state"] == "PENDING"
    assert result["gate"]["status"] == "PENDING_APPROVAL"
    assert result["gate"]["type"] == "HIGH_IMPACT_OPERATION"
    assert result["full_profile_execution"] is False
    assert "files" not in result["plan"]["job"]
    assert len(store.events) == 1 and backend.calls == []
    assert store.events[0].kind.value == "SUBMIT"


def test_prepare_is_idempotent_for_exact_input(tmp_path):
    service, store, backend, args = setup_service(tmp_path)

    async def scenario():
        a = await prepare(service, backend, args)
        b = await prepare(service, backend, args)
        assert a == b
        assert len(store.records) == len(store.events) == 1
        with pytest.raises(InspectionError, match="ID_CONFLICT"):
            await service.prepare(**args, revision_id=uuid4(), scenarios=backend.job.scenarios)

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["owner", "project", "archive"])
def test_other_owner_project_or_archived_project_is_not_accessible(tmp_path, change):
    service, store, backend, args = setup_service(tmp_path)
    asyncio.run(prepare(service, backend, args))
    if change == "owner":
        args["owner_user_id"] = uuid4()
    if change == "project":
        args["project_id"] = uuid4()
    if change == "archive":
        store.active = False
    with pytest.raises(InspectionError) as raised:
        asyncio.run(service.get(**args))
    assert raised.value.status_code == 404
    assert backend.calls == []


def test_unapproved_plan_cannot_execute(tmp_path):
    service, store, backend, args = setup_service(tmp_path)
    prepared = asyncio.run(prepare(service, backend, args))
    with pytest.raises(InspectionError, match="APPROVAL_REQUIRED"):
        asyncio.run(service.execute(**args, expected_hash=prepared["plan"]["plan_content_hash"]))
    assert store.records[args["request_id"]].state is InspectionState.PENDING
    assert backend.calls == []


@pytest.mark.parametrize(
    "action",
    [
        HumanGateAction.REJECT,
        HumanGateAction.REQUEST_REVISION,
        HumanGateAction.PAUSE,
        HumanGateAction.CANCEL,
    ],
)
def test_non_approval_decisions_never_execute(tmp_path, action):
    service, store, backend, args = setup_service(tmp_path)

    async def scenario():
        prepared = await prepare(service, backend, args)
        expected = prepared["plan"]["plan_content_hash"]
        await service.decide(
            **args,
            expected_hash=expected,
            expected_event_sequence=1,
            action=action,
            reason="Owner review of this exact job.",
        )
        with pytest.raises(InspectionError, match="APPROVAL_REQUIRED"):
            await service.execute(**args, expected_hash=expected)

    asyncio.run(scenario())
    assert backend.calls == [] and len(store.events) == 2


def test_pause_resume_does_not_approve(tmp_path):
    service, _store, backend, args = setup_service(tmp_path)

    async def scenario():
        prepared = await prepare(service, backend, args)
        expected = prepared["plan"]["plan_content_hash"]
        await service.decide(
            **args, expected_hash=expected, expected_event_sequence=1, action=HumanGateAction.PAUSE
        )
        result = await service.decide(
            **args, expected_hash=expected, expected_event_sequence=2, action=HumanGateAction.RESUME
        )
        assert result["gate"]["status"] == "PENDING_APPROVAL"

    asyncio.run(scenario())
    assert backend.calls == []


def test_decision_requires_exact_hash_sequence_and_rejection_reason(tmp_path):
    service, store, backend, args = setup_service(tmp_path)

    async def scenario():
        prepared = await prepare(service, backend, args)
        expected = prepared["plan"]["plan_content_hash"]
        for digest, seq, action, code in [
            ("e" * 64, 1, HumanGateAction.APPROVE, "PLAN_CHANGED"),
            (expected, 99, HumanGateAction.APPROVE, "STATE_CONFLICT"),
            (expected, 1, HumanGateAction.REJECT, "REASON_REQUIRED"),
            (expected, 1, HumanGateAction.SUBMIT, "ACTION_INVALID"),
        ]:
            with pytest.raises(InspectionError, match=code):
                await service.decide(
                    **args, expected_hash=digest, expected_event_sequence=seq, action=action
                )
        assert len(store.events) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("failed_assertion", [False, True])
def test_approved_inspection_executes_once_and_preserves_assertions(tmp_path, failed_assertion):
    service, store, backend, args = setup_service(tmp_path)
    backend.assertions_fail = failed_assertion

    async def scenario():
        expected = await approve(service, backend, args)
        result = await service.execute(**args, expected_hash=expected)
        assert result["state"] == "COMPLETED"
        assert result["result"]["assertion_status"] == ("FAILED" if failed_assertion else "PASSED")
        assert result["result"]["cleanup_confirmed"] is True
        assert result["result"]["level_d_validated"] is False
        replay = await service.execute(**args, expected_hash=expected)
        assert replay == result and backend.calls == [args["request_id"]]
        assert [event.kind.value for event in store.events] == ["SUBMIT", "APPROVE"]

    asyncio.run(scenario())


@pytest.mark.parametrize("stale", ["architecture", "source_hash", "revision", "runtime", "gate"])
def test_stale_approval_is_rejected_before_execution(tmp_path, stale):
    service, store, backend, args = setup_service(tmp_path)

    async def scenario():
        expected = await approve(service, backend, args)
        if stale == "architecture":
            store.context = replace(
                store.context,
                architecture=replace(store.context.architecture, content_hash="e" * 64),
            )
        elif stale == "source_hash":
            store.context = replace(
                store.context, revision={**store.context.revision, "content_hash": "e" * 64}
            )
        elif stale == "revision":
            store.context = replace(
                store.context, revision={**store.context.revision, "id": str(uuid4())}
            )
        elif stale == "runtime":
            backend.changed_binding = True
        else:
            store.latest = None
        with pytest.raises(InspectionError):
            await service.execute(**args, expected_hash=expected)
        assert (
            backend.calls == []
            and store.records[args["request_id"]].state is InspectionState.PENDING
        )

    asyncio.run(scenario())


def test_claim_is_committed_before_execution_and_concurrent_retry_is_blocked(tmp_path):
    service, store, backend, args = setup_service(tmp_path)

    async def scenario():
        expected = await approve(service, backend, args)
        backend.release = asyncio.Event()
        first = asyncio.create_task(service.execute(**args, expected_hash=expected))
        await backend.started.wait()
        assert store.records[args["request_id"]].state is InspectionState.RUNNING
        with pytest.raises(InspectionError, match="ALREADY_RUNNING"):
            await service.execute(**args, expected_hash=expected)
        backend.release.set()
        assert (await first)["state"] == "COMPLETED"
        assert len(backend.calls) == 1

    asyncio.run(scenario())


def test_database_claim_failure_never_launches(tmp_path):
    service, store, backend, args = setup_service(tmp_path)

    async def scenario():
        expected = await approve(service, backend, args)
        store.fail_update = True
        with pytest.raises(InspectionError, match="UPDATE_FAILED"):
            await service.execute(**args, expected_hash=expected)
        assert store.records[args["request_id"]].state is InspectionState.PENDING

    asyncio.run(scenario())
    assert backend.calls == []


@pytest.mark.parametrize("failure", ["start", "cleanup"])
def test_failed_runtime_is_not_a_pass_or_a_retry(tmp_path, failure):
    service, _store, backend, args = setup_service(tmp_path)
    backend.fail = failure

    async def scenario():
        expected = await approve(service, backend, args)
        result = await service.execute(**args, expected_hash=expected)
        assert result["state"] == "FAILED"
        assert result["result"]["execution_status"] == "FAILED"
        assert (await service.execute(**args, expected_hash=expected)) == result

    asyncio.run(scenario())
    assert len(backend.calls) == 1


def test_recovery_imports_finished_evidence_without_reexecuting(tmp_path):
    service, store, backend, args = setup_service(tmp_path)
    backend.cancel_after_evidence = True

    async def scenario():
        expected = await approve(service, backend, args)
        with pytest.raises(asyncio.CancelledError):
            await service.execute(**args, expected_hash=expected)
        assert store.records[args["request_id"]].state is InspectionState.RUNNING
        recovered = await service.recover(**args, expected_hash=expected)
        assert recovered["state"] == "COMPLETED"
        assert recovered["result"]["assertion_status"] == "PASSED"
        assert backend.calls == [args["request_id"]]

    asyncio.run(scenario())


def test_recovery_without_evidence_does_not_mark_complete(tmp_path):
    service, store, backend, args = setup_service(tmp_path)

    async def scenario():
        expected = await approve(service, backend, args)
        from datetime import UTC, datetime

        record = store.records[args["request_id"]]
        store.records[record.id] = replace(
            record, state=InspectionState.RUNNING, started_at=datetime.now(UTC)
        )
        with pytest.raises(ValueError):
            await service.recover(**args, expected_hash=expected)
        assert store.records[record.id].state is InspectionState.RUNNING

    asyncio.run(scenario())
    assert backend.calls == []


def test_plan_restoration_verifies_all_bytes_and_public_view_omits_sources(tmp_path):
    service, store, backend, args = setup_service(tmp_path)
    asyncio.run(prepare(service, backend, args))
    plan = store.records[args["request_id"]].plan
    from orchestwin.web_execution.static_browser_jobs import canonical_bytes

    restored = InspectionPlan.from_json(canonical_bytes(plan.snapshot()).decode())
    assert restored == plan
    raw = plan.snapshot()
    raw["job"]["files"][0]["content_base64"] = "Zm9yZ2Vk"
    with pytest.raises((InspectionError, ValueError)):
        InspectionPlan.from_json(canonical_bytes(raw).decode())
    public = json.dumps(plan.public_snapshot())
    assert "content_base64" not in public and "storage_key" not in public


def test_pending_gate_and_iteration_limit_are_not_bypassed(tmp_path):
    service, store, backend, args = setup_service(tmp_path)

    async def scenario():
        prepared = await prepare(service, backend, args)
        other = {**args, "request_id": uuid4()}
        with pytest.raises(InspectionError, match="REQUIRES_DECISION"):
            await prepare(service, backend, other)
        gate = store.gates[store.latest]
        store.gates[gate.id] = replace(gate, status=HumanGateStatus.REJECTED, iteration=3)
        with pytest.raises(InspectionError, match="ITERATION_LIMIT"):
            await prepare(service, backend, other)
        assert len(store.records) == 1
        assert prepared["state"] == "PENDING"

    asyncio.run(scenario())


def test_owner_can_cancel_a_pending_plan_after_source_changes(tmp_path):
    service, store, backend, args = setup_service(tmp_path)

    async def scenario():
        prepared = await prepare(service, backend, args)
        old = store.context
        store.context = replace(old, revision={**old.revision, "content_hash": "f" * 64})
        cancelled = await service.decide(
            **args,
            expected_hash=prepared["plan"]["plan_content_hash"],
            expected_event_sequence=prepared["gate"]["event_sequence"],
            action=HumanGateAction.CANCEL,
        )
        assert cancelled["gate"]["status"] == "CANCELLED"
        assert backend.calls == []

    asyncio.run(scenario())


def test_unconfirmed_cleanup_prevents_another_inspection(tmp_path):
    from datetime import UTC, datetime

    from orchestwin.web_execution.static_browser_jobs import canonical_bytes

    service, store, backend, args = setup_service(tmp_path)

    async def scenario():
        await approve(service, backend, args)
        previous = store.records[args["request_id"]]
        now = datetime.now(UTC)
        store.records[previous.id] = replace(
            previous,
            state=InspectionState.FAILED,
            started_at=now,
            finished_at=now,
            result_json=canonical_bytes({"cleanup_confirmed": False}).decode(),
        )
        with pytest.raises(InspectionError, match="CLEANUP_REQUIRES_OPERATOR"):
            await prepare(service, backend, {**args, "request_id": uuid4()})
        assert backend.calls == []

    asyncio.run(scenario())
