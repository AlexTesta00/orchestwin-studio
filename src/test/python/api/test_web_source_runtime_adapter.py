"""Unit tests for admission, ownership and transactions in the Web source adapter."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from orchestwin.api import web_source_runtime as sut
from orchestwin.api.web_execution import WebSourcePlanFileCommand, WebSourceProvenanceCommand
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.targets import WebImplementationLanguage, WebProjectLayout

OWNER = UUID(int=55001)
PROJECT = UUID(int=55002)
ARCHITECTURE = UUID(int=55003)
REVISION = UUID(int=55004)
NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
HASH = "a" * 64

_REAL_PLAN_FACTORY = sut.create_web_source_plan
_REAL_VALIDATOR = sut.validate_web_source_plan
_REAL_REVISION_FACTORY = sut.create_web_source_revision
_REAL_STORE = sut.FileSystemWebSourceContentStore


def command(**changes):
    values = dict(
        target=ExecutionTarget.WEB_STATIC,
        frontend_language=WebImplementationLanguage.STATIC_ASSETS,
        backend_language=None,
        layout=WebProjectLayout.SINGLE_ROOT,
        rationale="Store an approved source plan.",
        files=(WebSourcePlanFileCommand("index.html", "<h1>Test</h1>", "text/html"),),
        provenance_references=(
            WebSourceProvenanceCommand(
                sut.WebSourceProvenanceKind.ARCHITECTURE,
                f"architecture:{ARCHITECTURE}",
                1,
                HASH,
            ),
        ),
    )
    values.update(changes)
    return sut.WebSourceRevisionCreateCommand(**values)


@pytest.fixture
def environment(monkeypatch, tmp_path):
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock()
    transaction.__aexit__ = AsyncMock(return_value=False)
    session.begin.return_value = transaction
    session.scalar = AsyncMock(
        return_value=SimpleNamespace(mode=sut.ProjectMode.GREENFIELD_GENERATION.value)
    )
    factory = Mock(return_value=session)
    artifact = sut.GateArtifactReference(
        project_id=PROJECT,
        gate_type=sut.HumanGateType.ARCHITECTURE,
        artifact_id=ARCHITECTURE,
        version=1,
        content_hash=HASH,
    )
    gate = SimpleNamespace(
        project_id=PROJECT,
        owner_user_id=OWNER,
        gate_type=sut.HumanGateType.ARCHITECTURE,
        status=sut.HumanGateStatus.APPROVED,
        artifact=artifact,
    )
    architecture = SimpleNamespace(
        id=ARCHITECTURE, project_id=PROJECT, version_number=1, content_hash=HASH
    )
    arch_repository = SimpleNamespace(
        get_current_owned_for_update=AsyncMock(return_value=architecture)
    )
    gate_repository = SimpleNamespace(get_latest_owned_for_update=AsyncMock(return_value=gate))
    revision = SimpleNamespace(
        to_snapshot=Mock(return_value={"id": str(REVISION), "version_number": 1})
    )
    revisions = SimpleNamespace(
        current=AsyncMock(return_value=None),
        append=AsyncMock(
            return_value=SimpleNamespace(
                status=sut.WebSourceRevisionAppendStatus.APPENDED,
                revision=revision,
            )
        ),
    )
    store = SimpleNamespace(store=Mock(return_value=SimpleNamespace(storage_key="sha256/test")))
    monkeypatch.setattr(
        sut, "SqlAlchemyArchitecturePackageRepository", Mock(return_value=arch_repository)
    )
    monkeypatch.setattr(sut, "SqlAlchemyHumanGateRepository", Mock(return_value=gate_repository))
    monkeypatch.setattr(sut, "SqlAlchemyWebSourceRevisionRepository", Mock(return_value=revisions))
    monkeypatch.setattr(sut, "FileSystemWebSourceContentStore", Mock(return_value=store))
    # The adapter unit tests exercise sequencing, not duplicate domain validation.
    plan_factory = Mock(side_effect=lambda **values: SimpleNamespace(**values))
    validator = Mock(return_value=SimpleNamespace(is_accepted=True))
    revision_factory = Mock(return_value=revision)
    monkeypatch.setattr(sut, "create_web_source_plan", plan_factory)
    monkeypatch.setattr(sut, "validate_web_source_plan", validator)
    monkeypatch.setattr(sut, "create_web_source_revision", revision_factory)
    service = sut.SqlAlchemyWebSourceApiService(factory, content_root=tmp_path / "objects")
    return SimpleNamespace(
        session=session,
        transaction=transaction,
        factory=factory,
        service=service,
        gate=gate,
        architecture=architecture,
        revisions=revisions,
        store=store,
        arch_repository=arch_repository,
        gate_repository=gate_repository,
        plan_factory=plan_factory,
        validator=validator,
        revision_factory=revision_factory,
        revision=revision,
    )


def create(env, value=None):
    return asyncio.run(
        env.service.create_source_revision(
            owner_user_id=OWNER, project_id=PROJECT, command=command() if value is None else value
        )
    )


def test_accepts_only_after_exact_architecture_gate_and_stores_source_bytes(environment):
    env = environment
    result = create(env)
    assert result.status is sut.WebApiCommandStatus.SOURCE_REVISION_CREATED
    assert result.snapshot == {"id": str(REVISION), "version_number": 1}
    assert "execution has not been performed" in result.message
    env.store.store.assert_called_once_with(
        normalized_path="index.html", content=b"<h1>Test</h1>", media_type="text/html"
    )
    env.revisions.append.assert_awaited_once_with(env.revision)
    values = env.revision_factory.call_args.kwargs
    assert values["created_by_user_id"] == OWNER
    assert values["project_id"] == PROJECT
    assert values["based_on"] is None and values["version_number"] == 1
    assert values["origin"] is sut.WebSourceOrigin.GENERATED_PLAN
    assert values["created_at"].utcoffset() is not None
    env.transaction.__aexit__.assert_awaited_once_with(None, None, None)
    env.session.__aexit__.assert_awaited_once_with(None, None, None)


def test_owner_is_supplied_to_both_governance_queries(environment):
    env = environment
    create(env)
    env.arch_repository.get_current_owned_for_update.assert_awaited_once_with(
        project_id=PROJECT, owner_user_id=OWNER
    )
    env.gate_repository.get_latest_owned_for_update.assert_awaited_once_with(
        project_id=PROJECT, owner_user_id=OWNER, gate_type=sut.HumanGateType.ARCHITECTURE
    )
    query = env.session.scalar.call_args.args[0]
    compiled = query.compile(dialect=postgresql.dialect())
    assert "FOR UPDATE" in str(compiled)
    assert "archived_at IS NULL" in str(compiled)
    assert OWNER in compiled.params.values() and PROJECT in compiled.params.values()


@pytest.mark.parametrize("resource", ["project", "architecture", "gate"])
def test_missing_or_unowned_resource_never_writes(environment, resource):
    env = environment
    if resource == "project":
        env.session.scalar.return_value = None
    elif resource == "architecture":
        env.arch_repository.get_current_owned_for_update.return_value = None
    else:
        env.gate_repository.get_latest_owned_for_update.return_value = None
    result = create(env)
    expected = (
        sut.WebApiCommandStatus.NOT_FOUND
        if resource == "project"
        else sut.WebApiCommandStatus.APPROVAL_REQUIRED
    )
    assert result.status is expected
    assert result.snapshot is None
    env.store.store.assert_not_called()
    env.revisions.append.assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    ["status", "owner", "project", "type", "version", "hash", "artifact", "architecture_project"],
)
def test_wrong_or_stale_gate_never_admits_a_source_plan(environment, change):
    env = environment
    if change == "status":
        env.gate.status = sut.HumanGateStatus.PENDING_APPROVAL
    elif change == "owner":
        env.gate.owner_user_id = UUID(int=55901)
    elif change == "project":
        env.gate.project_id = UUID(int=55902)
    elif change == "type":
        env.gate.gate_type = sut.HumanGateType.DESIGN
    elif change == "architecture_project":
        env.architecture.project_id = UUID(int=55903)
    else:
        fields = {
            "version": {"version": 2},
            "hash": {"content_hash": "b" * 64},
            "artifact": {"artifact_id": UUID(int=55904)},
        }
        env.gate.artifact = replace(env.gate.artifact, **fields[change])
    assert create(env).status is sut.WebApiCommandStatus.APPROVAL_REQUIRED
    env.store.store.assert_not_called()
    env.revisions.append.assert_not_awaited()


@pytest.mark.parametrize(
    "field,value",
    [
        ("reference_id", "source-plan-1"),
        ("version_number", 2),
        ("content_hash", "b" * 64),
        ("kind", sut.WebSourceProvenanceKind.SOURCE_PLAN),
    ],
)
def test_unverified_provenance_cannot_be_written(environment, field, value):
    original = command().provenance_references[0]
    modified = replace(original, **{field: value})
    result = create(environment, command(provenance_references=(modified,)))
    assert result.status is sut.WebApiCommandStatus.CONFLICT
    environment.store.store.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"target": ExecutionTarget.WEB_PHP},
        {"frontend_language": WebImplementationLanguage.TYPESCRIPT},
        {"backend_language": WebImplementationLanguage.PHP},
        {"provenance_references": ()},
        {"files": (WebSourcePlanFileCommand("C:/file.html", "test", "text/html"),)},
        {"files": (WebSourcePlanFileCommand("index.html:stream", "test", "text/html"),)},
        {"files": (WebSourcePlanFileCommand("../outside.html", "test", "text/html"),)},
    ],
)
def test_outside_scope_or_invalid_plan_does_not_open_a_session(environment, changes):
    assert create(environment, command(**changes)).status is sut.WebApiCommandStatus.INVALID
    environment.factory.assert_not_called()
    environment.store.store.assert_not_called()


def test_failed_domain_validation_does_not_open_a_session(environment):
    environment.validator.return_value.is_accepted = False
    assert create(environment).status is sut.WebApiCommandStatus.INVALID
    environment.factory.assert_not_called()


def test_brownfield_uses_its_own_existing_intake_path(environment):
    environment.session.scalar.return_value.mode = sut.ProjectMode.BROWNFIELD_ASSESSMENT.value
    assert create(environment).status is sut.WebApiCommandStatus.CONFLICT
    environment.store.store.assert_not_called()


def test_second_initial_revision_does_not_overwrite_or_create_another_version(environment):
    environment.revisions.current.return_value = environment.revision
    assert create(environment).status is sut.WebApiCommandStatus.CONFLICT
    environment.store.store.assert_not_called()
    environment.revisions.append.assert_not_awaited()


def test_storage_error_is_redacted_and_rolls_back(environment):
    environment.store.store.side_effect = OSError("private-path-and-secret")
    with pytest.raises(HTTPException) as error:
        create(environment)
    assert error.value.status_code == 503
    assert "private-path-and-secret" not in str(error.value.detail)
    assert environment.transaction.__aexit__.call_args.args[0] is HTTPException
    environment.revisions.append.assert_not_awaited()


def test_append_conflict_raises_out_of_transaction_instead_of_committing(environment):
    environment.revisions.append.return_value = SimpleNamespace(
        status=sut.WebSourceRevisionAppendStatus.VERSION_CONFLICT, revision=None
    )
    with pytest.raises(HTTPException) as error:
        create(environment)
    assert error.value.status_code == 409
    assert environment.transaction.__aexit__.call_args.args[0] is HTTPException
    assert environment.session.__aexit__.await_count == 1


def test_commit_failure_is_not_reported_as_source_created(environment):
    environment.transaction.__aexit__.side_effect = RuntimeError("commit-failed")
    with pytest.raises(RuntimeError, match="commit-failed"):
        create(environment)
    assert environment.session.__aexit__.await_count == 1


def test_storage_parent_redirection_is_rejected_before_writes(environment, monkeypatch):
    monkeypatch.setattr(sut.Path, "is_junction", lambda _self: True)
    with pytest.raises(HTTPException) as error:
        create(environment)
    assert error.value.status_code == 503
    environment.store.store.assert_not_called()


def test_source_query_binds_owner_project_and_archive_filter():
    compiled = sut._owned_sources(owner_user_id=OWNER, project_id=PROJECT).compile(
        dialect=postgresql.dialect()
    )
    sql = str(compiled)
    assert "projects.owner_user_id" in sql and "projects.archived_at IS NULL" in sql
    assert "web_source_revisions.created_by_user_id" in sql
    assert OWNER in compiled.params.values() and PROJECT in compiled.params.values()


def test_history_rehydrates_records_and_closes_read_session(environment, monkeypatch):
    env = environment
    rows = [{"revision_snapshot": "first"}, {"revision_snapshot": "second"}]
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    env.session.execute = AsyncMock(return_value=result)
    decoder = Mock(return_value=env.revision)
    monkeypatch.setattr(sut, "web_source_revision_from_record", decoder)
    snapshots = asyncio.run(
        env.service.source_revision_history(owner_user_id=OWNER, project_id=PROJECT)
    )
    assert snapshots == ({"id": str(REVISION), "version_number": 1},) * 2
    assert [call.args[0] for call in decoder.call_args_list] == rows
    env.session.begin.assert_not_called()
    assert env.session.__aexit__.await_count == 1


def test_exact_revision_query_returns_none_when_no_owned_row_exists(environment):
    env = environment
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = None
    env.session.execute = AsyncMock(return_value=result)
    value = asyncio.run(
        env.service.source_revision(owner_user_id=OWNER, project_id=PROJECT, revision_id=REVISION)
    )
    assert value is None
    compiled = env.session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert REVISION in compiled.params.values()
    assert env.session.__aexit__.await_count == 1


def test_corrupt_persisted_revision_is_not_returned_as_valid(environment, monkeypatch):
    env = environment
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = {"content_hash": "bad"}
    env.session.execute = AsyncMock(return_value=result)
    monkeypatch.setattr(
        sut, "web_source_revision_from_record", Mock(side_effect=ValueError("corrupt"))
    )
    with pytest.raises(ValueError, match="corrupt"):
        asyncio.run(
            env.service.source_revision(
                owner_user_id=OWNER, project_id=PROJECT, revision_id=REVISION
            )
        )
    assert env.session.__aexit__.await_count == 1


@pytest.mark.parametrize(
    "path", [".env", ".git/config", "node_modules/package.json", "credentials.json"]
)
def test_real_domain_rejects_prohibited_source_paths(environment, monkeypatch, path):
    monkeypatch.setattr(sut, "create_web_source_plan", _REAL_PLAN_FACTORY)
    monkeypatch.setattr(sut, "validate_web_source_plan", _REAL_VALIDATOR)
    result = create(
        environment, command(files=(WebSourcePlanFileCommand(path, "test", "text/plain"),))
    )
    assert result.status is sut.WebApiCommandStatus.INVALID
    environment.factory.assert_not_called()
    environment.store.store.assert_not_called()


def test_real_domain_stores_readable_content_addressed_bytes(environment, monkeypatch, tmp_path):
    import hashlib

    env = environment
    monkeypatch.setattr(sut, "create_web_source_plan", _REAL_PLAN_FACTORY)
    monkeypatch.setattr(sut, "validate_web_source_plan", _REAL_VALIDATOR)
    monkeypatch.setattr(sut, "create_web_source_revision", _REAL_REVISION_FACTORY)
    store = _REAL_STORE(tmp_path / "real-objects")
    env.service._content_store = store
    env.service._content_root = tmp_path / "real-objects"

    async def append(revision):
        return SimpleNamespace(status=sut.WebSourceRevisionAppendStatus.APPENDED, revision=revision)

    env.revisions.append.side_effect = append
    result = create(env)
    assert result.status is sut.WebApiCommandStatus.SOURCE_REVISION_CREATED
    snapshot = result.snapshot
    assert snapshot["origin"] == "GENERATED_PLAN"
    assert snapshot["version_number"] == 1 and snapshot["based_on"] is None
    item = snapshot["files"][0]
    assert item["sha256_digest"] == hashlib.sha256(b"<h1>Test</h1>").hexdigest()
    assert store.read(item["storage_key"]) == b"<h1>Test</h1>"
    assert "content" not in item
    assert snapshot["provenance_references"][0]["reference_id"] == f"architecture:{ARCHITECTURE}"
