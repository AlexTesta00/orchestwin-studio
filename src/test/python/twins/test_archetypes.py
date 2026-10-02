from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from orchestwin.twins import runtime as runtime_module
from orchestwin.twins.archetypes import ArchetypeFailure, ArchetypeIssue, ArchetypeService
from orchestwin.twins.persistence.repositories import VersionAppendStatus
from orchestwin.twins.representation import ArchetypeInput
from orchestwin.twins.runtime import (
    ManagedArchetypeUnitOfWork,
    ManagedUserModelingUnitOfWork,
    build_archetype_service,
)

OWNER = UUID("00000000-0000-4000-8000-000000310001")
PROJECT = UUID("00000000-0000-4000-8000-000000310002")
NOW = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


def run(coroutine):
    return asyncio.run(coroutine)


def data(**changes):
    values = {
        "name": "Reception staff",
        "description": "Checks reservations at the front desk.",
        "role": "Receptionist",
        "goals": ("Check today's reservations",),
        "context": "Hotel front desk",
    }
    return ArchetypeInput(**(values | changes))


class MemoryStore:
    def __init__(self):
        self.versions = []
        self.pending = False
        self.append_status = VersionAppendStatus.APPENDED
        self.commits = 0
        self.events = []

    def __call__(self, *, owner_user_id):
        return MemoryUnit(self, owner_user_id)

    def service(self):
        return ArchetypeService(uow_factory=self, clock=lambda: NOW)


class MemoryUnit:
    def __init__(self, store, owner):
        self.store = store
        self.owner = owner
        self.personas = self
        self.versions = list(store.versions)
        self.locked = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.store.events.append("exit")

    async def lock_project(self, *, project_id):
        self.store.events.append("lock")
        self.locked = project_id == PROJECT and self.owner == OWNER
        return self.locked

    async def has_pending_revision(self, *, project_id):
        assert self.locked and project_id == PROJECT
        self.store.events.append("pending")
        return self.store.pending

    async def list_current(self, *, project_id):
        assert self.locked and project_id == PROJECT
        self.store.events.append("list")
        current = {version.persona_id: version for version in self.versions}
        return tuple(current.values())

    async def current(self, *, project_id, persona_id):
        versions = await self.list_current(project_id=project_id)
        return next((version for version in versions if version.persona_id == persona_id), None)

    async def append(self, version):
        assert self.locked
        self.store.events.append("append")
        if self.store.append_status is VersionAppendStatus.APPENDED:
            self.versions.append(version)
        return self.store.append_status

    async def commit(self):
        self.store.versions = list(self.versions)
        self.store.commits += 1
        self.store.events.append("commit")


def create(store, **changes):
    return run(
        store.service().create(owner_user_id=OWNER, project_id=PROJECT, data=data(**changes))
    )


def test_manual_creation_is_confirmed_and_has_no_twin_or_model_dependency():
    store = MemoryStore()
    version = create(store)
    assert version.version_number == 1
    assert version.based_on_version_number is None
    assert version.profile.source.value == "OWNER_PROVIDED"
    assert version.profile.confirmation_status.value == "CONFIRMED"
    assert version.profile.ready_for_twin_creation
    assert not version.profile.archived
    assert store.events == ["lock", "list", "pending", "append", "commit", "exit"]
    assert run(store.service().list_current(owner_user_id=OWNER, project_id=PROJECT)) == (version,)


def test_edit_preserves_identity_and_archive_preserves_complete_history():
    store = MemoryStore()
    first = create(store)
    second = run(
        store.service().edit(
            owner_user_id=OWNER,
            project_id=PROJECT,
            persona_id=first.persona_id,
            based_on_version_number=1,
            data=data(name="Night reception staff"),
        )
    )
    archived = run(
        store.service().archive(
            owner_user_id=OWNER,
            project_id=PROJECT,
            persona_id=first.persona_id,
            based_on_version_number=2,
        )
    )
    assert first.persona_id == second.persona_id == archived.persona_id
    assert len({first.id, second.id, archived.id}) == 3
    assert [(v.version_number, v.based_on_version_number) for v in store.versions] == [
        (1, None),
        (2, 1),
        (3, 2),
    ]
    assert first.profile.name == "Reception staff"
    assert not first.profile.archived and not second.profile.archived
    assert archived.profile.archived and not archived.profile.ready_for_twin_creation
    assert run(store.service().list_current(owner_user_id=OWNER, project_id=PROJECT)) == ()


def test_identical_normalized_edit_keeps_version_and_does_not_commit():
    store = MemoryStore()
    first = create(store)
    store.pending = True
    same = run(
        store.service().edit(
            owner_user_id=OWNER,
            project_id=PROJECT,
            persona_id=first.persona_id,
            based_on_version_number=1,
            data=data(name="  Reception   staff  "),
        )
    )
    assert same is first
    assert store.versions == [first]
    assert store.commits == 1


@pytest.mark.parametrize("operation", ["list_current", "create", "edit", "archive"])
@pytest.mark.parametrize("foreign", ["owner", "project"])
def test_foreign_projects_are_rejected_before_reading_or_writing(operation, foreign):
    store = MemoryStore()
    first = create(store)
    store.events.clear()
    arguments = {
        "owner_user_id": uuid4() if foreign == "owner" else OWNER,
        "project_id": uuid4() if foreign == "project" else PROJECT,
    }
    if operation in {"create", "edit"}:
        arguments["data"] = data(name="Other")
    if operation in {"edit", "archive"}:
        arguments.update(persona_id=first.persona_id, based_on_version_number=1)
    with pytest.raises(ArchetypeFailure) as error:
        run(getattr(store.service(), operation)(**arguments))
    assert error.value.issue is ArchetypeIssue.PROJECT_NOT_FOUND
    assert store.events == ["lock", "exit"]
    assert store.versions == [first]


def test_limit_counts_active_archetypes_and_archiving_releases_a_slot():
    store = MemoryStore()
    versions = [create(store, name=f"Role {number}") for number in range(8)]
    with pytest.raises(ArchetypeFailure) as error:
        create(store, name="Ninth")
    assert error.value.issue is ArchetypeIssue.ARCHETYPE_LIMIT_REACHED
    run(
        store.service().archive(
            owner_user_id=OWNER,
            project_id=PROJECT,
            persona_id=versions[0].persona_id,
            based_on_version_number=1,
        )
    )
    create(store, name="Replacement")
    assert len(run(store.service().list_current(owner_user_id=OWNER, project_id=PROJECT))) == 8


@pytest.mark.parametrize("operation", ["create", "edit", "archive"])
def test_pending_twin_revision_blocks_mutations_without_removing_it(operation):
    store = MemoryStore()
    first = create(store)
    store.pending = True
    arguments = {"owner_user_id": OWNER, "project_id": PROJECT}
    if operation in {"create", "edit"}:
        arguments["data"] = data(name="Changed")
    if operation in {"edit", "archive"}:
        arguments.update(persona_id=first.persona_id, based_on_version_number=1)
    with pytest.raises(ArchetypeFailure) as error:
        run(getattr(store.service(), operation)(**arguments))
    assert error.value.issue is ArchetypeIssue.USER_TWIN_REVISION_PENDING
    assert store.pending and store.versions == [first]


@pytest.mark.parametrize("operation", ["edit", "archive"])
@pytest.mark.parametrize("state", ["missing", "stale", "archived"])
def test_unavailable_or_stale_versions_fail_without_appending(operation, state):
    store = MemoryStore()
    first = create(store)
    if state == "archived":
        run(
            store.service().archive(
                owner_user_id=OWNER,
                project_id=PROJECT,
                persona_id=first.persona_id,
                based_on_version_number=1,
            )
        )
    arguments = {
        "owner_user_id": OWNER,
        "project_id": PROJECT,
        "persona_id": uuid4() if state == "missing" else first.persona_id,
        "based_on_version_number": 1 if state == "missing" else 2,
    }
    if operation == "edit":
        arguments["data"] = data(name="Changed")
    before = list(store.versions)
    with pytest.raises(ArchetypeFailure) as error:
        run(getattr(store.service(), operation)(**arguments))
    assert (
        error.value.issue
        is {
            "missing": ArchetypeIssue.ARCHETYPE_NOT_FOUND,
            "stale": ArchetypeIssue.ARCHETYPE_VERSION_CONFLICT,
            "archived": ArchetypeIssue.ARCHETYPE_ALREADY_ARCHIVED,
        }[state]
    )
    assert store.versions == before


def test_refused_persistence_does_not_commit():
    store = MemoryStore()
    store.append_status = VersionAppendStatus.CONTEXT_NOT_FOUND
    with pytest.raises(ArchetypeFailure) as error:
        create(store)
    assert error.value.issue is ArchetypeIssue.PERSISTENCE_REJECTED
    assert store.versions == [] and store.commits == 0


def test_runtime_lock_is_owner_scoped_and_pending_query_reads_all_project_proposals():
    session = AsyncMock()
    session.scalar.side_effect = [object(), uuid4()]
    unit = ManagedUserModelingUnitOfWork(session, owner_user_id=OWNER)
    assert run(unit.lock_project(project_id=PROJECT))
    assert run(unit.has_pending_revision(project_id=PROJECT))
    statements = [call.args[0] for call in session.scalar.call_args_list]
    lock = statements[0].compile(dialect=postgresql.dialect())
    assert "FOR UPDATE" in str(lock)
    assert OWNER in lock.params.values() and PROJECT in lock.params.values()
    pending = statements[1].compile(dialect=postgresql.dialect())
    assert "PROPOSED" in pending.params.values()
    assert OWNER in pending.params.values() and PROJECT in pending.params.values()


def test_runtime_lock_and_pending_query_return_false_for_no_owned_rows():
    session = AsyncMock()
    session.scalar.return_value = None
    unit = ManagedUserModelingUnitOfWork(session, owner_user_id=OWNER)
    assert not run(unit.lock_project(project_id=PROJECT))
    assert not run(unit.has_pending_revision(project_id=PROJECT))


def test_runtime_current_personas_excludes_archived_without_rewriting_versions(monkeypatch):
    store = MemoryStore()
    active = create(store)
    second = create(store, name="Night reception staff")
    archived = run(
        store.service().archive(
            owner_user_id=OWNER,
            project_id=PROJECT,
            persona_id=second.persona_id,
            based_on_version_number=1,
        )
    )
    before = tuple(version.to_snapshot() for version in store.versions)
    repository = SimpleNamespace(list_current=AsyncMock(return_value=(active, archived)))
    monkeypatch.setattr(
        runtime_module, "SqlAlchemyPersonaVersionRepository", lambda *args, **kwargs: repository
    )
    session = AsyncMock()
    service = runtime_module.SqlAlchemyUserModelingQueryService(lambda: session)
    actual = run(service.current_personas(owner_user_id=OWNER, project_id=PROJECT))
    assert actual == (active,)
    repository.list_current.assert_awaited_once_with(project_id=PROJECT)
    assert tuple(version.to_snapshot() for version in store.versions) == before


def test_runtime_builder_opens_no_session_until_a_command_runs():
    sessions = AsyncMock()
    service = build_archetype_service(sessions)
    assert isinstance(service, ArchetypeService)
    sessions.assert_not_called()


def test_database_failure_is_hidden_and_session_is_rolled_back_and_closed():
    session = AsyncMock()
    failure = IntegrityError("test private statement", {"test": "private input"}, ValueError())

    async def failing():
        async with ManagedArchetypeUnitOfWork(session, owner_user_id=OWNER):
            raise failure

    with pytest.raises(ArchetypeFailure) as error:
        run(failing())
    assert str(error.value) == "PERSISTENCE_REJECTED"
    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()
