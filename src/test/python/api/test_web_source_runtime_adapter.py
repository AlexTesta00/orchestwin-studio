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

    env.service.source_revision = AsyncMock(return_value=snapshot)
    read_scope = dict(owner_user_id=OWNER, project_id=PROJECT, revision_id=REVISION)
    _, files = asyncio.run(env.service.source_files(**read_scope))
    assert files == [("index.html", "text/html", b"<h1>Test</h1>")]
    env.service.source_revision.assert_awaited_once_with(**read_scope)

    # A same-size substitution must not be exposed as the immutable revision.
    env.service._content_store = SimpleNamespace(read=lambda key: b"<h1>Oops</h1>")
    with pytest.raises(HTTPException) as failure:
        asyncio.run(env.service.source_files(**read_scope))
    assert failure.value.status_code == 503

    env.service.source_revision = AsyncMock(return_value=None)
    env.service._content_store = SimpleNamespace(read=Mock(side_effect=AssertionError))
    assert asyncio.run(env.service.source_files(**read_scope)) is None


@pytest.fixture
def design_reference_environment(environment, monkeypatch):
    env = environment
    design_id = UUID(int=55005)
    env.design = SimpleNamespace(
        id=design_id,
        project_id=PROJECT,
        version_number=2,
        content_hash="b" * 64,
        package=SimpleNamespace(
            prototype=SimpleNamespace(to_snapshot=lambda: {"title": "Approved prototype"})
        ),
    )
    env.architecture.package = SimpleNamespace(
        grounding=SimpleNamespace(
            design_package_reference=SimpleNamespace(
                artifact_id=design_id, version_number=2, content_hash="b" * 64
            )
        )
    )
    env.arch_repository.get = AsyncMock(return_value=env.architecture)
    env.design_repository = SimpleNamespace(
        get=AsyncMock(return_value=env.design), current=AsyncMock(return_value=env.design)
    )
    monkeypatch.setattr(
        sut, "SqlAlchemyDesignPackageRepository", Mock(return_value=env.design_repository)
    )
    env.source_snapshot = {
        "id": str(REVISION),
        "version_number": 4,
        "content_hash": "c" * 64,
        "origin": "OWNER_EDIT",
        "provenance_references": [
            {
                "kind": "ARCHITECTURE",
                "reference_id": f"architecture:{ARCHITECTURE}",
                "version_number": 1,
                "content_hash": HASH,
            }
        ],
    }
    env.service.source_revision = AsyncMock(return_value=env.source_snapshot)
    return env


def design_reference(env):
    return asyncio.run(
        env.service.source_design_reference(
            owner_user_id=OWNER, project_id=PROJECT, revision_id=REVISION
        )
    )


def test_source_design_reference_reads_exact_ancestor_not_newer_design(
    design_reference_environment,
):
    env = design_reference_environment
    env.design_repository.current.return_value = SimpleNamespace(
        id=UUID(int=55006), version_number=3, content_hash="d" * 64
    )
    result = design_reference(env)
    assert result["source"]["origin"] == "OWNER_EDIT"
    assert result["source"]["revision_id"] == str(REVISION)
    assert result["design"] == {
        "artifact_id": str(env.design.id),
        "version_number": 2,
        "content_hash": "b" * 64,
    }
    assert result["prototype"] == {"title": "Approved prototype"}
    assert result["current_design"]["version_number"] == 3
    assert result["design_status"] == "STALE"
    assert result["visual_conformance"] == "NOT_ASSESSED"
    env.arch_repository.get.assert_awaited_once_with(project_id=PROJECT, version_id=ARCHITECTURE)
    env.design_repository.get.assert_awaited_once_with(project_id=PROJECT, version_id=env.design.id)
    sut.SqlAlchemyArchitecturePackageRepository.assert_called_once_with(
        env.session, owner_user_id=OWNER
    )
    sut.SqlAlchemyDesignPackageRepository.assert_called_once_with(env.session, owner_user_id=OWNER)


@pytest.mark.parametrize("has_current", [True, False])
def test_source_design_reference_current_status_and_missing_prototype(
    design_reference_environment, has_current
):
    env = design_reference_environment
    env.design.package.prototype = None
    if not has_current:
        env.design_repository.current.return_value = None
    result = design_reference(env)
    assert result["prototype"] is None
    assert result["design_status"] == ("CURRENT" if has_current else "UNAVAILABLE")


def test_source_design_reference_does_not_resolve_unowned_source(design_reference_environment):
    env = design_reference_environment
    env.service.source_revision.return_value = None
    assert design_reference(env) is None
    env.service.source_revision.assert_awaited_once_with(
        owner_user_id=OWNER, project_id=PROJECT, revision_id=REVISION
    )
    env.factory.assert_not_called()


@pytest.mark.parametrize("failure", ["missing", "duplicate", "wrong-prefix", "invalid-uuid"])
def test_source_design_reference_rejects_ambiguous_or_malformed_ancestry(
    design_reference_environment, failure
):
    env = design_reference_environment
    references = env.source_snapshot["provenance_references"]
    if failure == "missing":
        references.clear()
    elif failure == "duplicate":
        references.append(dict(references[0]))
    elif failure == "wrong-prefix":
        references[0]["reference_id"] = f"design:{ARCHITECTURE}"
    else:
        references[0]["reference_id"] = "architecture:invalid"
    with pytest.raises(HTTPException) as failure:
        design_reference(env)
    assert failure.value.status_code == 409
    assert failure.value.detail["code"] == "WEB_SOURCE_DESIGN_REFERENCE_INVALID"
    env.factory.assert_not_called()


@pytest.mark.parametrize("artifact", ["architecture", "design"])
@pytest.mark.parametrize(
    "mismatch", ["missing", "id", "project_id", "version_number", "content_hash"]
)
def test_source_design_reference_refuses_mismatched_historical_artifacts(
    design_reference_environment, artifact, mismatch
):
    env = design_reference_environment
    item = getattr(env, artifact)
    if mismatch == "missing":
        repository = env.arch_repository if artifact == "architecture" else env.design_repository
        repository.get.return_value = None
    else:
        setattr(
            item,
            mismatch,
            {
                "id": UUID(int=999),
                "project_id": UUID(int=999),
                "version_number": 99,
                "content_hash": "e" * 64,
            }[mismatch],
        )
    with pytest.raises(HTTPException) as failure:
        design_reference(env)
    assert failure.value.status_code == 409
    assert failure.value.detail["code"] == "WEB_SOURCE_DESIGN_REFERENCE_UNAVAILABLE"
    env.design_repository.current.assert_not_awaited()


@pytest.fixture
def owner_edit_environment(environment, monkeypatch, tmp_path):
    env = environment
    monkeypatch.setattr(sut, "create_web_source_plan", _REAL_PLAN_FACTORY)
    monkeypatch.setattr(sut, "validate_web_source_plan", _REAL_VALIDATOR)
    monkeypatch.setattr(sut, "create_web_source_revision", _REAL_REVISION_FACTORY)
    env.service._content_root = tmp_path / "owner-edit-objects"
    env.service._content_store = _REAL_STORE(env.service._content_root)
    monkeypatch.setattr(sut, "bind_source_publication", AsyncMock(side_effect=AssertionError))
    original = env.service._content_store.store(
        normalized_path="index.html", content=b"<h1>Original</h1>", media_type="text/html"
    )
    env.base = _REAL_REVISION_FACTORY(
        revision_id=REVISION,
        project_id=PROJECT,
        created_by_user_id=OWNER,
        version_number=1,
        based_on=None,
        target=ExecutionTarget.WEB_STATIC,
        language_configuration=sut.WebLanguageConfiguration(
            frontend=WebImplementationLanguage.STATIC_ASSETS, backend=None
        ),
        layout=WebProjectLayout.SINGLE_ROOT,
        origin=sut.WebSourceOrigin.GENERATED_PLAN,
        files=(original,),
        provenance_references=(
            sut.WebSourceProvenanceReference(
                sut.WebSourceProvenanceKind.ARCHITECTURE, f"architecture:{ARCHITECTURE}", 1, HASH
            ),
        ),
        created_at=NOW,
    )
    env.revisions.current.return_value = env.base

    async def append(revision):
        env.revisions.current.return_value = revision
        return SimpleNamespace(status=sut.WebSourceRevisionAppendStatus.APPENDED, revision=revision)

    env.revisions.append.side_effect = append
    return env


def edit_command(env, **changes):
    return SimpleNamespace(
        **{
            "base_revision_content_hash": env.base.content_hash,
            "rationale": "Correct the calculator controls after owner review.",
            "files": (WebSourcePlanFileCommand("index.html", "<h1>Corrected</h1>", "text/html"),),
            **changes,
        }
    )


def edit(env, command=None, revision_id=REVISION):
    return asyncio.run(
        env.service.edit_source_revision(
            owner_user_id=OWNER,
            project_id=PROJECT,
            revision_id=revision_id,
            command=command or edit_command(env),
        )
    )


@pytest.fixture
def owner_mockup_environment(owner_edit_environment, monkeypatch):
    from orchestwin.api.design_mockups import MockupResult, MockupStatus, _payload
    from orchestwin.models.design_mockups import MockupDraft, bind_mockup
    from src.test.python.artifacts import design_fixtures
    from src.test.python.models.test_design_mockups import draft_value

    env = owner_edit_environment
    base_design = design_fixtures.design_version()
    prototype = bind_mockup(
        MockupDraft.model_validate(draft_value()),
        base_design.package.alternatives[0],
        design_fixtures.requirements_version(),
    )
    package = replace(
        base_design.package,
        owner_selected_alternative_id=base_design.package.alternatives[0].id,
        prototype=prototype,
    )
    env.mockup_id = UUID(int=55020)
    env.design = SimpleNamespace(
        id=base_design.id,
        content_hash=base_design.content_hash,
        version_number=2,
        project_id=PROJECT,
        package=base_design.package,
    )
    env.design_repository = SimpleNamespace(
        current=AsyncMock(return_value=env.design), get=AsyncMock(return_value=env.design)
    )
    env.architecture.package = SimpleNamespace(
        grounding=SimpleNamespace(
            design_package_reference=SimpleNamespace(
                artifact_id=env.design.id, version_number=2, content_hash=env.design.content_hash
            )
        )
    )
    env.arch_repository.get = AsyncMock(return_value=env.architecture)
    monkeypatch.setattr(
        sut, "SqlAlchemyDesignPackageRepository", Mock(return_value=env.design_repository)
    )
    env.mockup_result = _payload(
        MockupResult(
            MockupStatus.GENERATED, env.mockup_id, base_design.id, base_design.content_hash, package
        )
    )
    context = {
        "project_id": str(PROJECT),
        "purpose": "DESIGN_MOCKUP",
        "design_version_id": str(base_design.id),
        "design_content_hash": base_design.content_hash,
        "alternative": {"id": str(package.owner_selected_alternative_id)},
    }
    env.mockup_evidence = {
        "request": {
            "generation_id": str(env.mockup_id),
            "project_id": str(PROJECT),
            "owner_user_id": str(OWNER),
            "request": {"input_payload_json": sut.canonical_json({"context": context})},
        },
        "observations": [
            {
                "kind": "ADAPTER_ACCEPTED",
                "payload": {
                    "result": env.mockup_result,
                    "generated_content_hashes": {"DESIGN": [package.content_hash]},
                },
            }
        ],
    }
    env.evidence_store = SimpleNamespace(get_owned=AsyncMock(return_value=env.mockup_evidence))
    monkeypatch.setattr(
        sut, "SqlAlchemyProposalEvidenceStore", Mock(return_value=env.evidence_store)
    )
    env.mockup_html = """<section data-design-screen="SCR-001">
      <label for="name">Nome</label><input id="name" name="name" required data-design-element="ELM-001">
      <button data-design-element="ELM-002" data-design-target="SCR-002">Continua</button></section>
      <section data-design-screen="SCR-002"><p>Esempio di prenotazione confermata</p>
      <a href="#" data-design-element="ELM-004" data-design-target="SCR-001">Indietro</a></section>"""
    return env


def mockup_edit_command(env, **changes):
    return edit_command(
        env,
        **{
            "mockup_generation_id": env.mockup_id,
            "files": (WebSourcePlanFileCommand("index.html", env.mockup_html, "text/html"),),
            **changes,
        },
    )


def test_owner_edit_binds_exact_mockup_and_retrieves_it_after_current_design_changes(
    owner_mockup_environment,
):
    env = owner_mockup_environment
    result = edit(env, mockup_edit_command(env))
    assert result.status is sut.WebApiCommandStatus.SOURCE_REVISION_CREATED
    reference = result.snapshot["owner_edit"]["visual_reference"]
    assert reference["generation_id"] == str(env.mockup_id)
    assert reference["prototype_id"] == env.mockup_result["package"]["prototype"]["id"]
    env.evidence_store.get_owned.assert_awaited_once_with(
        owner_user_id=OWNER, project_id=PROJECT, generation_id=env.mockup_id
    )
    env.service.source_revision = AsyncMock(return_value=result.snapshot)
    env.design_repository.current.return_value = SimpleNamespace(
        id=UUID(int=99), version_number=3, content_hash="f" * 64
    )
    response = design_reference(env)
    assert response["owner_mockup"]["generation_id"] == str(env.mockup_id)
    assert response["owner_mockup"]["prototype"] == env.mockup_result["package"]["prototype"]
    assert response["structure_contract"] == "VERIFIED"
    assert response["visual_conformance"] == "NOT_ASSESSED"
    assert response["design_status"] == "STALE"


@pytest.mark.parametrize(
    "failure", ["unowned", "owner", "project", "generation", "hash", "not-mockup", "prototype"]
)
def test_owner_edit_rejects_unowned_or_forged_mockup_before_writing(
    owner_mockup_environment, failure
):
    env = owner_mockup_environment
    if failure == "unowned":
        env.evidence_store.get_owned.return_value = None
    elif failure in {"owner", "project", "generation"}:
        env.mockup_evidence["request"][
            {"owner": "owner_user_id", "project": "project_id", "generation": "generation_id"}[
                failure
            ]
        ] = str(UUID(int=99))
    elif failure == "hash":
        env.mockup_evidence["observations"][0]["payload"]["generated_content_hashes"]["DESIGN"] = [
            "f" * 64
        ]
    elif failure == "not-mockup":
        env.mockup_evidence["request"]["request"]["input_payload_json"] = sut.canonical_json(
            {"context": {"purpose": "OTHER"}}
        )
    else:
        env.mockup_result["package"]["prototype"]["screens"][0]["elements"][0]["required"] = False
    with pytest.raises(HTTPException) as failure:
        edit(env, mockup_edit_command(env))
    assert failure.value.detail["code"] == "WEB_SOURCE_MOCKUP_REFERENCE_INVALID"
    env.revisions.append.assert_not_called()


def test_owner_edit_rejects_mockup_based_on_stale_design(owner_mockup_environment):
    env = owner_mockup_environment
    env.design.content_hash = "f" * 64
    result = edit(env, mockup_edit_command(env))
    assert result.message == "WEB_SOURCE_MOCKUP_CONTEXT_CHANGED"
    env.revisions.append.assert_not_called()


def test_owner_edit_requires_selected_mockup_fields_before_binding(owner_mockup_environment):
    env = owner_mockup_environment
    env.mockup_html = env.mockup_html.replace(" required ", " ")
    result = edit(env, mockup_edit_command(env))
    assert result.message == "SOURCE_DESIGN_STRUCTURE_MISMATCH"
    env.revisions.append.assert_not_called()


def test_source_design_reference_rejects_tampered_mockup_binding(owner_mockup_environment):
    env = owner_mockup_environment
    result = edit(env, mockup_edit_command(env))
    result.snapshot["owner_edit"]["visual_reference"]["prototype_content_hash"] = "f" * 64
    env.service.source_revision = AsyncMock(return_value=result.snapshot)
    with pytest.raises(HTTPException) as failure:
        design_reference(env)
    assert failure.value.detail["code"] == "WEB_SOURCE_MOCKUP_REFERENCE_INVALID"


def test_following_owner_edit_retains_mockup_and_enforces_structure(owner_mockup_environment):
    env = owner_mockup_environment
    first = edit(env, mockup_edit_command(env))
    result = edit(
        env,
        edit_command(env, base_revision_content_hash=first.snapshot["content_hash"]),
        revision_id=UUID(first.snapshot["id"]),
    )
    assert result.message == "SOURCE_DESIGN_STRUCTURE_MISMATCH"
    result = edit(
        env,
        edit_command(
            env,
            base_revision_content_hash=first.snapshot["content_hash"],
            files=(
                WebSourcePlanFileCommand(
                    "index.html", env.mockup_html + "<!-- reviewed -->", "text/html"
                ),
            ),
        ),
        revision_id=UUID(first.snapshot["id"]),
    )
    assert result.status is sut.WebApiCommandStatus.SOURCE_REVISION_CREATED
    assert (
        result.snapshot["owner_edit"]["visual_reference"]
        == first.snapshot["owner_edit"]["visual_reference"]
    )


def test_owner_edit_appends_exact_lineage_and_verifiable_rationale_without_model_claim(
    owner_edit_environment,
):
    env = owner_edit_environment
    before = env.base.to_snapshot()
    result = edit(env)
    snapshot = result.snapshot
    assert result.status is sut.WebApiCommandStatus.SOURCE_REVISION_CREATED
    assert snapshot["origin"] == "OWNER_EDIT" and snapshot["version_number"] == 2
    assert snapshot["based_on"] == env.base.reference.to_snapshot()
    assert snapshot["related_failure_signature"] is None
    assert "model_generation_id" not in snapshot
    assert snapshot["owner_edit"]["rationale"] == edit_command(env).rationale
    assert snapshot["owner_edit"]["base_revision"] == env.base.reference.to_snapshot()
    assert env.base.to_snapshot() == before
    assert env.service._content_store.read(env.base.files[0].storage_key) == b"<h1>Original</h1>"
    persisted = env.revisions.append.call_args.args[0]
    assert "owner_edit" not in persisted.to_snapshot()
    assert env.service._api_snapshot(persisted) == snapshot
    owner_ref = next(
        ref
        for ref in persisted.provenance_references
        if ref.kind is sut.WebSourceProvenanceKind.OWNER_DECISION
    )
    assert owner_ref.reference_id == f"source-edit:{persisted.id}"
    assert owner_ref.version_number == 2
    sut.bind_source_publication.assert_not_called()
    query = env.session.scalar.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "FOR UPDATE" in str(query) and OWNER in query.params.values()


@pytest.mark.parametrize("mismatch", ["hash", "revision"])
def test_owner_edit_stale_base_never_appends(owner_edit_environment, mismatch):
    env = owner_edit_environment
    result = (
        edit(env, edit_command(env, base_revision_content_hash="b" * 64))
        if mismatch == "hash"
        else edit(env, revision_id=UUID(int=1))
    )
    assert result.status is sut.WebApiCommandStatus.CONFLICT
    assert result.message == "WEB_SOURCE_EDIT_STALE_BASE"
    env.revisions.append.assert_not_called()


def test_owner_edit_cannot_read_or_modify_another_owners_project(owner_edit_environment):
    env = owner_edit_environment
    env.session.scalar.return_value = None
    assert edit(env).status is sut.WebApiCommandStatus.NOT_FOUND
    env.revisions.current.assert_not_called()
    env.revisions.append.assert_not_called()


@pytest.mark.parametrize("mismatch", ["approval", "version", "architecture", "owner", "project"])
def test_owner_edit_requires_exact_current_approved_architecture(owner_edit_environment, mismatch):
    env = owner_edit_environment
    if mismatch == "approval":
        env.gate.status = sut.HumanGateStatus.PENDING_APPROVAL
    elif mismatch == "version":
        env.gate.artifact = replace(env.gate.artifact, version=2)
    elif mismatch == "architecture":
        env.architecture.content_hash = "b" * 64
        env.gate.artifact = replace(env.gate.artifact, content_hash="b" * 64)
    elif mismatch == "owner":
        env.gate.owner_user_id = UUID(int=1)
    else:
        env.architecture.project_id = UUID(int=1)
    assert edit(env).status is sut.WebApiCommandStatus.APPROVAL_REQUIRED
    env.revisions.append.assert_not_called()


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "../outside.html",
        "C:/bad.html",
        "index.html:stream",
        "node_modules/x.js",
        "script.js",
    ],
)
def test_owner_edit_rejects_unsafe_paths_or_missing_entry(owner_edit_environment, path):
    env = owner_edit_environment
    result = edit(
        env, edit_command(env, files=(WebSourcePlanFileCommand(path, "content", "text/plain"),))
    )
    assert result.status is sut.WebApiCommandStatus.INVALID
    env.revisions.append.assert_not_called()


def test_owner_edit_rejects_invalid_javascript_without_writing_or_execution(
    owner_edit_environment, monkeypatch
):
    env = owner_edit_environment
    checker = Mock(side_effect=sut.ProposalGenerationError("SOURCE_JAVASCRIPT_SYNTAX_INVALID"))
    monkeypatch.setattr(sut, "validate_source_syntax", checker)
    store = Mock(wraps=env.service._content_store.store)
    monkeypatch.setattr(env.service._content_store, "store", store)
    result = edit(env)
    assert result.status is sut.WebApiCommandStatus.INVALID
    assert result.message == "SOURCE_JAVASCRIPT_SYNTAX_INVALID"
    store.assert_not_called()
    env.revisions.append.assert_not_called()


def test_owner_edit_parser_unavailable_returns_503(owner_edit_environment, monkeypatch):
    env = owner_edit_environment
    monkeypatch.setattr(
        sut,
        "validate_source_syntax",
        Mock(side_effect=sut.ProposalGenerationError("SOURCE_JAVASCRIPT_PARSER_UNAVAILABLE")),
    )
    with pytest.raises(HTTPException) as error:
        edit(env)
    assert error.value.status_code == 503
    env.revisions.append.assert_not_called()


def test_owner_edit_noop_is_not_a_new_revision(owner_edit_environment):
    env = owner_edit_environment
    result = edit(
        env,
        edit_command(
            env, files=(WebSourcePlanFileCommand("index.html", "<h1>Original</h1>", "text/html"),)
        ),
    )
    assert result.status is sut.WebApiCommandStatus.CONFLICT
    assert result.message == "WEB_SOURCE_EDIT_UNCHANGED"
    env.revisions.append.assert_not_called()


def test_owner_edit_audit_tampering_is_not_exposed_as_verified(owner_edit_environment, monkeypatch):
    env = owner_edit_environment
    edit(env)
    revision = env.revisions.append.call_args.args[0]
    monkeypatch.setattr(env.service._content_store, "read", lambda _: b'{"rationale":"forged"}')
    with pytest.raises(HTTPException) as error:
        env.service._api_snapshot(revision)
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "WEB_SOURCE_EDIT_AUDIT_UNAVAILABLE"


def test_owner_edit_preserves_audit_on_each_successive_revision(owner_edit_environment):
    env = owner_edit_environment
    first = edit(env).snapshot
    v2 = env.revisions.current.return_value
    second = edit(
        env,
        edit_command(
            env,
            base_revision_content_hash=v2.content_hash,
            files=(WebSourcePlanFileCommand("index.html", "<h1>Third</h1>", "text/html"),),
        ),
        revision_id=v2.id,
    ).snapshot
    assert second["version_number"] == 3 and second["based_on"] == v2.reference.to_snapshot()
    assert env.service._api_snapshot(v2) == first
