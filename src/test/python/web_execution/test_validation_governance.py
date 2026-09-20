"""The validation harness reuses owner-scoped Unit7 services and durable facts."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from orchestwin.api.web_execution import WebExecutionStartCommand
from orchestwin.artifacts.web_source_persistence import InMemoryWebSourceRevisionRepository
from orchestwin.artifacts.web_sources import WebSourceOrigin
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.attempts import WebExecutionAttemptTrigger
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.static_browser_jobs import content_hash
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebProjectLayout,
    WebTargetSelection,
)
from orchestwin.web_execution.validation_fixtures import FixtureFile, RepositoryValidationFixture
from orchestwin.web_execution.validation_governance import (
    ValidationGovernance,
    WebValidationGovernanceError,
)
from orchestwin.workflow.web_execution import WebExecutionPurpose

NOW = datetime(2026, 9, 12, tzinfo=UTC)


def fixture_source():
    files = (FixtureFile("app.js", b"console.log('valid');\n", "text/javascript"),)
    return RepositoryValidationFixture(
        fixture_id="static",
        profile_id="web.static",
        profile_version="1.0.0",
        selection=WebTargetSelection(
            ExecutionTarget.WEB_STATIC,
            WebLanguageConfiguration(WebImplementationLanguage.STATIC_ASSETS, None),
            WebProjectLayout.SINGLE_ROOT,
        ),
        files=files,
        failure_path="app.js",
        failure_content=b"console.error('LEVEL_D_NEGATIVE_CONTROL');\n",
        expected_failure_phase=WebExecutionPhase.BROWSER_EVIDENCE,
        expected_failure_marker="LEVEL_D_NEGATIVE_CONTROL",
        browser_routes=(),
        browser_interactions=(),
        fixture_bundle_hash=content_hash([row.to_snapshot() for row in files]),
    )


class Sessions:
    def __init__(self, owner):
        self.owner = owner
        self.user_active = True
        self.active = 0
        self.commits = 0
        self.rollbacks = 0
        self.projects = {}
        self.queries = []

    @asynccontextmanager
    async def __call__(self):
        assert self.active == 0, "a size-one pool cannot supply a nested session"
        self.active += 1
        try:
            yield Session(self)
        finally:
            self.active -= 1


class Session:
    def __init__(self, database):
        self.database = database

    @asynccontextmanager
    async def begin(self):
        old_projects = self.database.projects.copy()
        try:
            yield
        except BaseException:
            self.database.projects = old_projects
            self.database.rollbacks += 1
            raise
        else:
            self.database.commits += 1

    async def scalar(self, statement):
        self.database.queries.append(statement)
        compiled = statement.compile()
        sql = str(compiled)
        identifier = compiled.params.get("id_1")
        if "FROM users" in sql:
            assert "users.is_active IS true" in sql
            return (
                self.database.owner
                if self.database.user_active and identifier == self.database.owner
                else None
            )
        assert "FROM projects" in sql
        return self.database.projects.get(identifier)

    def add(self, row):
        assert isinstance(row, ProjectRecord), "the harness must never invent an owner"
        self.database.projects[row.id] = row

    async def flush(self):
        pass


@pytest.fixture
def setup(tmp_path, monkeypatch):
    owner, project, source = uuid4(), uuid4(), uuid4()
    sessions = Sessions(owner)
    repository = InMemoryWebSourceRevisionRepository(
        owner_user_id=owner, project_ids=frozenset({project})
    )
    monkeypatch.setattr(
        "orchestwin.web_execution.validation_governance.SqlAlchemyWebSourceRevisionRepository",
        lambda session, *, owner_user_id: repository,
    )
    execution = SimpleNamespace(prepare_execution=AsyncMock(), start_execution=AsyncMock())
    repairs = SimpleNamespace(create_repair_proposal=AsyncMock(), apply_repair_proposal=AsyncMock())
    reads = SimpleNamespace(browser_evidence=AsyncMock(return_value=None))
    operations = SimpleNamespace()
    driver = ValidationGovernance(
        sessions,
        operation_store=operations,
        execution_service=execution,
        repair_service=repairs,
        read_service=reads,
        content_root=tmp_path / "objects",
    )
    return SimpleNamespace(
        driver=driver,
        sessions=sessions,
        repository=repository,
        owner=owner,
        project=project,
        source=source,
        execution=execution,
        repairs=repairs,
        reads=reads,
        operations=operations,
        content_root=tmp_path / "objects",
    )


async def seed(setup, **changes):
    return await setup.driver.seed_fixture(
        **dict(
            owner_user_id=setup.owner,
            project_id=setup.project,
            source_id=setup.source,
            created_at=NOW,
            fixture=fixture_source(),
        )
        | changes
    )


def test_seed_creates_real_cas_source_and_project_once(setup):
    async def scenario():
        source = await seed(setup)
        assert await seed(setup) == source
        assert source.origin is WebSourceOrigin.DETERMINISTIC_FIXTURE
        assert source.version_number == 1 and source.based_on is None
        assert source.id == setup.source and source.created_by_user_id == setup.owner
        assert source.source_tree_hash == fixture_source().source_tree_hash()
        assert source.provenance_references[0].content_hash == fixture_source().fixture_bundle_hash
        assert len(await setup.repository.history(project_id=setup.project)) == 1
        assert len(setup.sessions.projects) == 1
        assert setup.sessions.commits == 2
        for entry in source.files:
            assert (setup.content_root / entry.storage_key).read_bytes() == fixture_source().files[
                0
            ].content
        assert any(statement._for_update_arg is not None for statement in setup.sessions.queries)
        setup.execution.start_execution.assert_not_awaited()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change", ["owner-missing", "inactive", "foreign-project", "archived-project"]
)
def test_seed_rejects_unavailable_owner_or_project_before_cas(setup, change):
    if change in {"owner-missing", "inactive"}:
        setup.sessions.user_active = False
    else:
        setup.sessions.projects[setup.project] = ProjectRecord(
            id=setup.project,
            owner_user_id=uuid4() if change == "foreign-project" else setup.owner,
            display_name="Other",
            mode="GREENFIELD_GENERATION",
            current_brief_version=0,
            archived_at=NOW if change == "archived-project" else None,
        )
    with pytest.raises(WebValidationGovernanceError):
        asyncio.run(seed(setup))
    assert not setup.content_root.exists()
    assert setup.sessions.rollbacks == 1


@pytest.mark.parametrize(
    "changes",
    [{"defective": True}, {"source_id": uuid4()}, {"created_at": NOW + timedelta(seconds=1)}],
)
def test_seed_conflict_does_not_append_or_replace_a_revision(setup, changes):
    async def scenario():
        original = await seed(setup)
        with pytest.raises(WebValidationGovernanceError):
            await seed(setup, **changes)
        assert await setup.repository.history(project_id=setup.project) == (original,)

    asyncio.run(scenario())


def test_defective_fixture_preserves_the_declared_failure_bytes(setup):
    source = asyncio.run(seed(setup, defective=True))
    assert source.source_tree_hash == fixture_source().source_tree_hash(defective=True)
    assert (
        setup.content_root / source.files[0].storage_key
    ).read_bytes() == fixture_source().failure_content


def test_corrupt_existing_cas_fails_idempotent_seed(setup):
    async def scenario():
        source = await seed(setup)
        (setup.content_root / source.files[0].storage_key).write_bytes(b"changed")
        with pytest.raises(WebValidationGovernanceError):
            await seed(setup)

    asyncio.run(scenario())


def command(source):
    return WebExecutionStartCommand(
        source_revision_id=source,
        profile_id="web.static",
        profile_version="1.0.0",
        policy_content_hash="1" * 64,
        execution_runner_image_digest="2" * 64,
        browser_runner_image_digest="3" * 64,
        purpose=WebExecutionPurpose.PROFILE_VALIDATION,
        trigger=WebExecutionAttemptTrigger.INITIAL,
        authorization_id=None,
        rerun_phases=None,
        declared_routes=(),
    )


@pytest.mark.parametrize("method", ["prepare_execution", "start_execution"])
def test_execution_wrappers_delegate_the_exact_command_after_releasing_owner_session(setup, method):
    async def scenario():
        request = command(setup.source)
        sentinel = object()

        async def delegate(**kwargs):
            assert setup.sessions.active == 0
            assert kwargs == dict(
                owner_user_id=setup.owner, project_id=setup.project, command=request
            )
            return sentinel

        getattr(setup.execution, method).side_effect = delegate
        result = await getattr(setup.driver, method)(
            owner_user_id=setup.owner, project_id=setup.project, command=request
        )
        assert result is sentinel

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["prepare_execution", "start_execution"])
def test_inactive_owner_never_reaches_execution_service(setup, method):
    setup.sessions.user_active = False
    with pytest.raises(WebValidationGovernanceError):
        asyncio.run(
            getattr(setup.driver, method)(
                owner_user_id=setup.owner, project_id=setup.project, command=command(setup.source)
            )
        )
    getattr(setup.execution, method).assert_not_awaited()


def test_owner_project_execution_is_not_a_validation_harness_operation(setup):
    with pytest.raises(WebValidationGovernanceError):
        asyncio.run(
            setup.driver.prepare_execution(
                owner_user_id=setup.owner,
                project_id=setup.project,
                command=replace(command(setup.source), purpose=WebExecutionPurpose.OWNER_PROJECT),
            )
        )
    setup.execution.prepare_execution.assert_not_awaited()


def test_source_history_reuses_owner_repository_and_preserves_domain_objects(setup):
    async def scenario():
        source = await seed(setup)
        assert await setup.driver.source_history(
            owner_user_id=setup.owner, project_id=setup.project
        ) == (source,)

    asyncio.run(scenario())


async def stored_proof(setup, monkeypatch, *, kind="EXECUTION", stale=False):
    from orchestwin.web_execution.operation_governance import (
        WebGovernedOperation,
        WebOperationState,
        operation_json,
    )
    from orchestwin.workflow.gates import (
        HumanGateAction,
        HumanGateEvent,
        HumanGateEventKind,
        HumanGateStatus,
        create_human_gate,
        transition_human_gate,
    )
    from src.test.python.web_execution.test_attempt_persistence import create_attempt

    source = await seed(setup)
    operation = WebGovernedOperation.create(
        project_id=setup.project,
        owner_user_id=setup.owner,
        source_revision_id=source.id,
        kind=kind,
        payload={"purpose": "PROFILE_VALIDATION"},
        created_at=NOW + timedelta(seconds=1),
    )
    attempt = create_attempt(attempt_id=operation.id)
    attempt = replace(
        attempt,
        project_id=setup.project,
        created_by_user_id=setup.owner,
        source_revision=source.reference,
        report=replace(
            attempt.report,
            source_revision_content_hash=source.content_hash,
            source_tree_hash=source.source_tree_hash,
        ),
        started_at=NOW + timedelta(seconds=4),
        completed_at=NOW + timedelta(seconds=5),
    )
    operation = replace(
        operation,
        state=WebOperationState.COMPLETED,
        started_at=attempt.started_at,
        finished_at=NOW + timedelta(seconds=6),
        result_json=operation_json(
            {
                "execution_id": str(attempt.id),
                "attempt_content_hash": attempt.content_hash,
                "report_status": attempt.report.status.value,
            }
        ),
    )
    gate = create_human_gate(
        project_id=setup.project,
        owner_user_id=setup.owner,
        gate_type=operation.artifact.gate_type,
        artifact=operation.artifact,
        gate_id=operation.gate_id,
        created_at=operation.created_at,
    )
    events = []
    for offset, action in ((2, HumanGateAction.SUBMIT), (3, HumanGateAction.APPROVE)):
        transition = transition_human_gate(
            gate,
            action=action,
            actor_user_id=setup.owner,
            occurred_at=NOW + timedelta(seconds=offset),
        )
        gate = transition.gate
        events.append(transition.event)
    if stale:
        event = HumanGateEvent(
            id=uuid4(),
            gate_id=gate.id,
            sequence_number=3,
            kind=HumanGateEventKind.ARTIFACT_SUPERSEDED,
            previous_status=HumanGateStatus.APPROVED,
            resulting_status=HumanGateStatus.STALE,
            artifact=replace(gate.artifact, artifact_id=uuid4(), content_hash="7" * 64),
            occurred_at=NOW + timedelta(seconds=7),
            actor_user_id=None,
        )
        events.append(event)
        gate = replace(
            gate, status=HumanGateStatus.STALE, event_sequence=3, updated_at=event.occurred_at
        )
    data = SimpleNamespace(
        source=source, attempt=attempt, operation=operation, gate=gate, events=events
    )

    @asynccontextmanager
    async def scope(**kwargs):
        assert kwargs == dict(owner_user_id=setup.owner, project_id=setup.project)
        async with setup.sessions() as session:
            yield SimpleNamespace(
                session=session,
                get=AsyncMock(return_value=data.operation),
                gate=AsyncMock(return_value=data.gate),
                history=AsyncMock(return_value=(data.operation,)),
                decide=setup.operations.decide,
                snapshot=AsyncMock(return_value={"id": str(data.operation.id)}),
            )

    setup.operations.scope = scope
    setup.operations.decide = AsyncMock(return_value=operation)
    monkeypatch.setattr(
        "orchestwin.web_execution.validation_governance.SqlAlchemyHumanGateRepository",
        lambda session: SimpleNamespace(
            list_events_owned=AsyncMock(side_effect=lambda **kwargs: tuple(data.events))
        ),
    )
    monkeypatch.setattr(
        "orchestwin.web_execution.validation_governance.SqlAlchemyWebExecutionAttemptRepository",
        lambda session, **kwargs: SimpleNamespace(
            history=AsyncMock(side_effect=lambda **kwargs: (data.attempt,))
        ),
    )
    return data


@pytest.mark.parametrize("stale", [False, True])
def test_harvest_rehydrates_actual_attempt_and_historical_approval_without_nested_session(
    setup, monkeypatch, stale
):
    async def scenario():
        data = await stored_proof(setup, monkeypatch, stale=stale)
        manifest = {"preserved": "read-service-verified-manifest"}

        async def read_browser(**kwargs):
            assert setup.sessions.active == 0
            assert kwargs == dict(owner_user_id=setup.owner, execution_id=data.attempt.id)
            return manifest

        setup.reads.browser_evidence.side_effect = read_browser
        result = await setup.driver.harvest_attempt(
            owner_user_id=setup.owner, project_id=setup.project, attempt_id=data.attempt.id
        )
        assert result.source == data.source and result.attempt == data.attempt
        assert result.operation == data.operation and result.gate == data.gate
        assert result.approval_event == data.events[1]
        assert result.browser_manifest is manifest
        setup.operations.decide.assert_not_awaited()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    [
        "missing-event",
        "wrong-actor",
        "after-claim",
        "sequence-gap",
        "wrong-artifact",
        "wrong-source",
        "wrong-result",
        "corrupt-cas",
    ],
)
def test_harvest_rejects_missing_or_mismatched_persisted_proof(setup, monkeypatch, change):
    async def scenario():
        from orchestwin.web_execution.operation_governance import operation_json

        data = await stored_proof(setup, monkeypatch)
        if change == "missing-event":
            data.events.pop()
        elif change == "wrong-actor":
            data.events[1] = replace(data.events[1], actor_user_id=uuid4())
        elif change == "after-claim":
            data.events[1] = replace(data.events[1], occurred_at=NOW + timedelta(seconds=5))
        elif change == "sequence-gap":
            data.events[1] = replace(data.events[1], sequence_number=3)
        elif change == "wrong-artifact":
            data.events[1] = replace(
                data.events[1], artifact=replace(data.gate.artifact, content_hash="9" * 64)
            )
        elif change == "wrong-source":
            data.operation = replace(data.operation, source_revision_id=uuid4())
        elif change == "wrong-result":
            data.operation = replace(
                data.operation, result_json=operation_json({"execution_id": str(uuid4())})
            )
        else:
            (setup.content_root / data.source.files[0].storage_key).write_bytes(b"changed")
        with pytest.raises(WebValidationGovernanceError):
            await setup.driver.harvest_attempt(
                owner_user_id=setup.owner, project_id=setup.project, attempt_id=data.attempt.id
            )
        setup.reads.browser_evidence.assert_not_awaited()

    asyncio.run(scenario())


def test_repair_proof_reads_the_same_persisted_approval_history(setup, monkeypatch):
    async def scenario():
        data = await stored_proof(setup, monkeypatch, kind="REPAIR", stale=True)
        assert await setup.driver.harvest_repair(
            owner_user_id=setup.owner, project_id=setup.project, operation_id=data.operation.id
        ) == (data.operation, data.gate, data.events[1])
        setup.operations.decide.assert_not_awaited()

    asyncio.run(scenario())


def test_explicit_approval_forwards_exact_operator_hash_and_sequence(setup, monkeypatch):
    async def scenario():
        data = await stored_proof(setup, monkeypatch)
        provided_hash = "8" * 64
        await setup.driver.approve(
            owner_user_id=setup.owner,
            project_id=setup.project,
            operation_id=data.operation.id,
            expected_hash=provided_hash,
            expected_event_sequence=17,
        )
        kwargs = setup.operations.decide.await_args.kwargs
        assert kwargs["expected_hash"] == provided_hash
        assert kwargs["expected_event_sequence"] == 17
        assert kwargs["action"].value == "APPROVE"
        setup.execution.start_execution.assert_not_awaited()

    asyncio.run(scenario())


def test_operation_history_returns_persisted_domain_objects(setup, monkeypatch):
    async def scenario():
        data = await stored_proof(setup, monkeypatch)
        assert await setup.driver.operation_history(
            owner_user_id=setup.owner, project_id=setup.project
        ) == (data.operation,)

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["create_repair_proposal", "apply_repair_proposal"])
def test_repair_wrappers_only_delegate_after_owner_check(setup, method):
    async def scenario():
        request = object()
        expected = dict(owner_user_id=setup.owner, execution_id=uuid4(), command=request)
        if method == "apply_repair_proposal":
            expected["proposal_id"] = uuid4()

        async def delegate(**kwargs):
            assert setup.sessions.active == 0
            assert kwargs == expected
            return "actual service result"

        getattr(setup.repairs, method).side_effect = delegate
        assert await getattr(setup.driver, method)(**expected) == "actual service result"

    asyncio.run(scenario())
