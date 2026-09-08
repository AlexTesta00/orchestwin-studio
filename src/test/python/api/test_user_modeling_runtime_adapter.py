"""Tests for the real Gate 3 bridge and existing bearer-authentication dependency."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.api.user_modeling import GateApiOutcome
from orchestwin.api.user_modeling_runtime import (
    UserModelingGateApiAdapter,
    create_runtime_user_modeling_router,
)
from orchestwin.twins.application import (
    PersonaProposalApplicationResult,
    UserModelingApplicationIssueCode,
    UserModelingApplicationStatus,
)
from orchestwin.twins.user_modeling_gate import (
    UserModelingGateDecisionResult,
    UserModelingGateDecisionStatus,
    UserModelingGateSubmissionResult,
    UserModelingGateSubmissionStatus,
)
from orchestwin.workflow.gates import HumanGateAction
from orchestwin.workflow.repository import HumanGateStateConflict

OWNER = UUID("00000000-0000-4000-8000-000000053101")
PROJECT = UUID("00000000-0000-4000-8000-000000053102")
OTHER = UUID("00000000-0000-4000-8000-000000053103")
PREFIX = f"/api/v1/projects/{PROJECT}/user-modeling"


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.mark.parametrize(
    "status,expected",
    [
        (UserModelingGateSubmissionStatus.SUBMITTED, GateApiOutcome.APPLIED),
        (UserModelingGateSubmissionStatus.ALREADY_PENDING, GateApiOutcome.NO_CHANGE),
        (UserModelingGateSubmissionStatus.ALREADY_APPROVED, GateApiOutcome.NO_CHANGE),
        (UserModelingGateSubmissionStatus.SNAPSHOT_NOT_FOUND, GateApiOutcome.NOT_FOUND),
        (UserModelingGateSubmissionStatus.NEW_SNAPSHOT_REQUIRED, GateApiOutcome.REJECTED),
        (UserModelingGateSubmissionStatus.GATE_BLOCKED, GateApiOutcome.REJECTED),
        (UserModelingGateSubmissionStatus.ITERATION_LIMIT_REACHED, GateApiOutcome.REJECTED),
        (UserModelingGateSubmissionStatus.TRANSITION_REJECTED, GateApiOutcome.REJECTED),
    ],
)
def test_submission_preserves_domain_outcomes(status, expected):
    event = object()
    result = UserModelingGateSubmissionResult(status=status, events=(event,))
    service = SimpleNamespace(submit=AsyncMock(return_value=result))
    actual = run(
        UserModelingGateApiAdapter(service).submit(
            owner_user_id=OWNER,
            project_id=PROJECT,
        )
    )
    assert actual.outcome is expected
    assert actual.events == (event,)
    service.submit.assert_awaited_once_with(owner_user_id=OWNER, project_id=PROJECT)


@pytest.mark.parametrize(
    "status,expected",
    [
        (UserModelingGateDecisionStatus.APPLIED, GateApiOutcome.APPLIED),
        (UserModelingGateDecisionStatus.ARTIFACT_STALE, GateApiOutcome.STALE),
        (UserModelingGateDecisionStatus.GATE_NOT_FOUND, GateApiOutcome.NOT_FOUND),
        (UserModelingGateDecisionStatus.SNAPSHOT_NOT_FOUND, GateApiOutcome.NOT_FOUND),
        (UserModelingGateDecisionStatus.REJECTED, GateApiOutcome.REJECTED),
    ],
)
def test_decisions_preserve_events_and_reasons(status, expected):
    event = object()
    result = UserModelingGateDecisionResult(status=status, event=event)
    service = SimpleNamespace(decide=AsyncMock(return_value=result))
    actual = run(
        UserModelingGateApiAdapter(service).decide(
            owner_user_id=OWNER,
            project_id=PROJECT,
            action=HumanGateAction.REQUEST_REVISION,
            reason="Needs review.",
        )
    )
    assert actual.outcome is expected
    assert actual.events == (event,)
    service.decide.assert_awaited_once_with(
        owner_user_id=OWNER,
        project_id=PROJECT,
        action=HumanGateAction.REQUEST_REVISION,
        reason="Needs review.",
    )


@pytest.mark.parametrize("method", ["submit", "decide"])
def test_concurrent_gate_mutation_is_not_reported_as_success(method):
    call = AsyncMock(side_effect=HumanGateStateConflict("changed"))
    service = SimpleNamespace(**{method: call})
    extra = {"action": HumanGateAction.APPROVE} if method == "decide" else {}
    result = run(
        getattr(UserModelingGateApiAdapter(service), method)(
            owner_user_id=OWNER,
            project_id=PROJECT,
            **extra,
        )
    )
    assert result.outcome is GateApiOutcome.STALE
    assert result.issue == "GATE_STATE_CONFLICT"


@pytest.mark.parametrize("has_gate", [False, True])
def test_gate_history_reads_only_the_owned_current_gate(has_gate):
    gate = SimpleNamespace(id=PROJECT) if has_gate else None
    service = SimpleNamespace(
        current_gate=AsyncMock(return_value=gate),
        gate_events=AsyncMock(return_value=("event",)),
    )
    result = run(
        UserModelingGateApiAdapter(service).gate_events(
            owner_user_id=OWNER,
            project_id=PROJECT,
        )
    )
    assert result == (("event",) if has_gate else ())
    if has_gate:
        service.gate_events.assert_awaited_once_with(
            owner_user_id=OWNER,
            project_id=PROJECT,
            gate_id=PROJECT,
        )
    else:
        service.gate_events.assert_not_awaited()


def bundle():
    return SimpleNamespace(
        commands=SimpleNamespace(
            propose_personas=AsyncMock(
                return_value=(
                    PersonaProposalApplicationResult(
                        status=UserModelingApplicationStatus.REJECTED,
                        issue=UserModelingApplicationIssueCode.BRIEF_APPROVAL_REQUIRED,
                    )
                )
            )
        ),
        revisions=object(),
        queries=SimpleNamespace(
            current_snapshot=AsyncMock(return_value=None),
            snapshot_history=AsyncMock(return_value=()),
        ),
        gates=SimpleNamespace(current_gate=AsyncMock(return_value=None)),
    )


def client_for(services):
    app = FastAPI()
    identity = SimpleNamespace(current_user=AsyncMock(return_value=SimpleNamespace(id=OWNER)))
    app.state.identity_service = identity
    app.include_router(create_runtime_user_modeling_router(services), prefix="/api/v1")
    return TestClient(app), identity


def test_unauthenticated_request_cannot_invoke_a_provider():
    services = bundle()
    client, identity = client_for(services)
    with client:
        response = client.post(PREFIX + "/personas/proposals")
    assert response.status_code == 401
    identity.current_user.assert_not_awaited()
    services.commands.propose_personas.assert_not_awaited()


def test_invalid_token_is_rejected_before_query():
    services = bundle()
    client, identity = client_for(services)
    identity.current_user.return_value = None
    with client:
        response = client.get(PREFIX + "/snapshots", headers={"Authorization": "Bearer bad"})
    assert response.status_code == 401
    services.queries.snapshot_history.assert_not_awaited()


def test_owner_scope_comes_from_token_not_query_argument():
    services = bundle()
    client, identity = client_for(services)
    with client:
        response = client.get(
            PREFIX + f"/snapshots?owner_user_id={OTHER}",
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 200
    assert response.json() == []
    identity.current_user.assert_awaited_once_with("test-token")
    services.queries.snapshot_history.assert_awaited_once_with(
        owner_user_id=OWNER,
        project_id=PROJECT,
    )


def test_missing_bundle_returns_503_instead_of_fake_content():
    client, _ = client_for(None)
    with client:
        response = client.get(PREFIX + "/snapshots", headers={"Authorization": "Bearer test"})
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "USER_MODELING_SERVICE_UNAVAILABLE"}}


def test_upstream_approval_blocker_remains_409():
    services = bundle()
    client, _ = client_for(services)
    with client:
        response = client.post(
            PREFIX + "/personas/proposals", headers={"Authorization": "Bearer test"}
        )
    assert response.status_code == 409
    assert "BRIEF_APPROVAL_REQUIRED" in response.text


def test_injected_bundles_are_not_shared_between_applications():
    first, second = bundle(), bundle()
    client_a, _ = client_for(first)
    client_b, _ = client_for(second)
    with client_a:
        assert (
            client_a.get(PREFIX + "/snapshots", headers={"Authorization": "Bearer a"}).status_code
            == 200
        )
    first.queries.snapshot_history.assert_awaited_once()
    second.queries.snapshot_history.assert_not_awaited()
    with client_b:
        assert (
            client_b.get(PREFIX + "/snapshots", headers={"Authorization": "Bearer b"}).status_code
            == 200
        )
    second.queries.snapshot_history.assert_awaited_once()
