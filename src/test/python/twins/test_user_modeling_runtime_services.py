"""Regression tests for persisted User Modeling composition and resource ownership."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from orchestwin.models.user_modeling_runtime import UserModelingRuntimeMode
from orchestwin.twins import runtime as module
from orchestwin.twins.application import (
    GovernedUserModelingContext,
    UserModelingApplicationIssueCode,
)
from orchestwin.workflow.gates import GateArtifactReference, HumanGateStatus, HumanGateType

OWNER = UUID("00000000-0000-4000-8000-000000053001")
PROJECT = UUID("00000000-0000-4000-8000-000000053002")
OTHER = UUID("00000000-0000-4000-8000-000000053003")
ARTIFACT = UUID("00000000-0000-4000-8000-000000053004")


class Session:
    def __init__(self):
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.close = AsyncMock()
        self.scalar = AsyncMock(return_value=object())

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        await self.close()


def run(coroutine):
    return asyncio.run(coroutine)


def test_composition_opens_no_session_and_retains_current_provider():
    def forbidden():
        raise AssertionError("composition must not open a session")

    result = module.build_user_modeling_services(forbidden)
    assert result.runtime_mode is UserModelingRuntimeMode.FAKE_DETERMINISTIC
    assert isinstance(result.commands, module.LocalUserModelingApplicationService)
    assert isinstance(result.revisions, module.LocalUserTwinProfileRevisionService)
    assert isinstance(result.gates, module.LocalUserModelingGateService)
    assert isinstance(result.queries, module.SqlAlchemyUserModelingQueryService)


@pytest.mark.parametrize("commit", [False, True])
def test_command_uow_closes_session_and_rolls_back_uncommitted_work(commit):
    session = Session()

    async def scenario():
        unit = module.ManagedUserModelingUnitOfWork(session, owner_user_id=OWNER)
        async with unit:
            if commit:
                await unit.commit()

    run(scenario())
    assert session.commit.await_count == int(commit)
    assert session.rollback.await_count == int(not commit)
    session.close.assert_awaited_once()


def test_command_uow_closes_session_after_failure():
    session = Session()

    async def scenario():
        async with module.ManagedUserModelingUnitOfWork(session, owner_user_id=OWNER):
            raise RuntimeError("command failed")

    with pytest.raises(RuntimeError, match="command failed"):
        run(scenario())
    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()


@pytest.mark.parametrize("fail", [False, True])
def test_gate_uow_commits_only_success_and_always_closes(fail):
    session = Session()

    async def scenario():
        async with module.SqlAlchemyUserModelingGateUnitOfWork(session):
            if fail:
                raise RuntimeError("gate failed")

    if fail:
        with pytest.raises(RuntimeError, match="gate failed"):
            run(scenario())
    else:
        run(scenario())
    assert session.commit.await_count == int(not fail)
    assert session.rollback.await_count == int(fail)
    session.close.assert_awaited_once()


def test_gate_commit_failure_rolls_back_and_closes():
    session = Session()
    session.commit.side_effect = RuntimeError("commit failed")

    async def scenario():
        async with module.SqlAlchemyUserModelingGateUnitOfWork(session):
            pass

    with pytest.raises(RuntimeError, match="commit failed"):
        run(scenario())
    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()


def test_snapshot_lock_is_scoped_to_owner_and_active_project(monkeypatch):
    session = Session()
    snapshots = SimpleNamespace(current=AsyncMock(return_value="snapshot"))
    seen = []

    def repository(actual_session, *, owner_user_id):
        seen.append((actual_session, owner_user_id))
        return snapshots

    monkeypatch.setattr(module, "SqlAlchemyUserModelingSnapshotRepository", repository)
    result = run(
        module.LockedUserModelingSnapshotQuery(session).get_current_owned_for_update(
            project_id=PROJECT,
            owner_user_id=OWNER,
        )
    )
    assert result == "snapshot"
    statement = session.scalar.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "FOR UPDATE" in str(compiled)
    assert "archived_at IS NULL" in str(compiled)
    assert OWNER in compiled.params.values()
    assert PROJECT in compiled.params.values()
    assert seen == [(session, OWNER)]
    snapshots.current.assert_awaited_once_with(project_id=PROJECT)


def test_missing_or_foreign_project_does_not_read_snapshot(monkeypatch):
    session = Session()
    session.scalar.return_value = None

    def forbidden(*_args, **_kwargs):
        raise AssertionError("foreign project must be rejected first")

    monkeypatch.setattr(module, "SqlAlchemyUserModelingSnapshotRepository", forbidden)
    assert (
        run(
            module.LockedUserModelingSnapshotQuery(session).get_current_owned_for_update(
                project_id=PROJECT,
                owner_user_id=OTHER,
            )
        )
        is None
    )


@pytest.mark.parametrize(
    "method,repo_method,extra",
    [
        ("current_snapshot", "current", {}),
        ("snapshot_history", "history", {}),
        ("get_diff", "get", {"diff_id": ARTIFACT}),
    ],
)
def test_queries_use_owned_repositories_and_short_lived_sessions(
    monkeypatch,
    method,
    repo_method,
    extra,
):
    session = Session()
    call = AsyncMock(return_value="result")
    repository = SimpleNamespace(**{repo_method: call})
    seen = []

    def factory(actual_session, *, owner_user_id):
        seen.append((actual_session, owner_user_id))
        return repository

    name = (
        "SqlAlchemyUserTwinProfileDiffRepository"
        if method == "get_diff"
        else "SqlAlchemyUserModelingSnapshotRepository"
    )
    monkeypatch.setattr(module, name, factory)
    service = module.SqlAlchemyUserModelingQueryService(lambda: session)
    assert (
        run(
            getattr(service, method)(
                owner_user_id=OWNER,
                project_id=PROJECT,
                **extra,
            )
        )
        == "result"
    )
    assert seen == [(session, OWNER)]
    call.assert_awaited_once_with(project_id=PROJECT, **extra)
    session.close.assert_awaited_once()


def test_owned_project_without_a_brief_returns_approval_blocker():
    context = GovernedUserModelingContext(
        project_id=PROJECT,
        brief_version=None,
        brief_gate=None,
        team_reference=None,
        approved_team_reference=None,
        catalog_version=None,
        catalog_content_hash=None,
    )
    governance = SimpleNamespace(load_current=AsyncMock(return_value=context))
    proposals = SimpleNamespace(propose_personas=AsyncMock())

    def forbidden(**_kwargs):
        raise AssertionError("must not open a write transaction before approval")

    service = module.LocalUserModelingApplicationService(
        governance=governance,
        proposals=proposals,
        uow_factory=forbidden,
    )
    result = run(service.propose_personas(owner_user_id=OWNER, project_id=PROJECT))
    assert result.issue is UserModelingApplicationIssueCode.BRIEF_APPROVAL_REQUIRED
    proposals.propose_personas.assert_not_awaited()


@pytest.mark.parametrize(
    "gate_status,gate_version,gate_hash,approved",
    [
        (HumanGateStatus.APPROVED, 2, "a" * 64, True),
        (HumanGateStatus.PENDING_APPROVAL, 2, "a" * 64, False),
        (HumanGateStatus.STALE, 2, "a" * 64, False),
        (HumanGateStatus.APPROVED, 1, "a" * 64, False),
        (HumanGateStatus.APPROVED, 2, "b" * 64, False),
    ],
)
def test_governance_requires_exact_approved_team_version(
    monkeypatch,
    gate_status,
    gate_version,
    gate_hash,
    approved,
):
    session = Session()
    brief = SimpleNamespace(project_id=PROJECT)
    team = SimpleNamespace(
        id=ARTIFACT,
        project_id=PROJECT,
        version_number=2,
        content_hash="a" * 64,
        proposal=SimpleNamespace(catalog_version=1, catalog_content_hash="c" * 64),
    )
    gate = SimpleNamespace(
        status=gate_status,
        artifact=GateArtifactReference(
            project_id=PROJECT,
            gate_type=HumanGateType.AGENT_TEAM,
            artifact_id=ARTIFACT,
            version=gate_version,
            content_hash=gate_hash,
        ),
    )
    projects = SimpleNamespace(get_owned=AsyncMock(return_value=object()))
    briefs = SimpleNamespace(get_current_owned=AsyncMock(return_value=brief))
    teams = SimpleNamespace(get_current_owned=AsyncMock(return_value=team))
    gates = SimpleNamespace(get_latest_owned_for_update=AsyncMock(side_effect=[None, gate]))
    for name, repo in (
        ("SqlAlchemyProjectRepository", projects),
        ("SqlAlchemyProjectBriefRepository", briefs),
        ("SqlAlchemyTeamProposalVersionRepository", teams),
        ("SqlAlchemyHumanGateRepository", gates),
    ):
        monkeypatch.setattr(module, name, lambda _session, repo=repo: repo)
    context = run(
        module.SqlAlchemyUserModelingGovernanceAdapter(
            lambda: session,
        ).load_current(owner_user_id=OWNER, project_id=PROJECT)
    )
    assert context is not None
    assert (context.approved_team_reference == context.team_reference) is approved
    for repo, method in (
        (projects, "get_owned"),
        (briefs, "get_current_owned"),
        (teams, "get_current_owned"),
    ):
        getattr(repo, method).assert_awaited_once_with(owner_user_id=OWNER, project_id=PROJECT)
    session.close.assert_awaited_once()


def test_foreign_governance_is_rejected_before_loading_artifacts(monkeypatch):
    session = Session()
    projects = SimpleNamespace(get_owned=AsyncMock(return_value=None))
    monkeypatch.setattr(module, "SqlAlchemyProjectRepository", lambda _session: projects)

    def forbidden(_session):
        raise AssertionError("do not inspect another owner's Brief")

    monkeypatch.setattr(module, "SqlAlchemyProjectBriefRepository", forbidden)
    context = run(
        module.SqlAlchemyUserModelingGovernanceAdapter(
            lambda: session,
        ).load_current(owner_user_id=OTHER, project_id=PROJECT)
    )
    assert context is None
    session.close.assert_awaited_once()


def test_empty_brief_context_has_no_fabricated_fingerprint():
    context = GovernedUserModelingContext(
        project_id=PROJECT,
        brief_version=None,
        brief_gate=None,
        team_reference=None,
        approved_team_reference=None,
        catalog_version=None,
        catalog_content_hash=None,
    )
    with pytest.raises(ValueError, match="no current Project Brief"):
        _ = context.fingerprint
    with pytest.raises(ValueError, match="no current Project Brief"):
        _ = context.brief_reference
