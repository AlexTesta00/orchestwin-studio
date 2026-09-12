"""Owner-scoped repair API transactions with real immutable source content."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from orchestwin.api import web_repair_runtime as sut
from orchestwin.api.web_execution import (
    WebApiCommandStatus,
    WebRepairChangeCommand,
    WebRepairProposalApplyCommand,
    WebRepairProposalCreateCommand,
)
from orchestwin.artifacts.web_change_sets import WebSourceChangeOperation
from orchestwin.artifacts.web_source_persistence import (
    WebSourceRevisionAppendResult,
    WebSourceRevisionAppendStatus,
)
from orchestwin.artifacts.web_source_plans import FileSystemWebSourceContentStore
from orchestwin.artifacts.web_sources import (
    WebSourceOrigin,
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
    create_web_source_revision,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.attempt_persistence import web_execution_attempt_to_record
from orchestwin.web_execution.attempts import WebExecutionAttempt, WebExecutionAttemptTrigger
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.repair_records import (
    web_repair_proposal_from_snapshot,
    web_repair_proposal_to_snapshot,
)
from orchestwin.web_execution.reports import (
    WebEvidenceReference,
    WebExecutionReport,
    WebFailureCategory,
    WebPhaseResult,
    WebPhaseResultStatus,
)
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebProjectLayout,
)
from orchestwin.workflow.gates import GateArtifactReference, HumanGateStatus, HumanGateType

OWNER, PROJECT, EXECUTION = UUID(int=74101), UUID(int=74102), UUID(int=74103)
NOW = datetime(2026, 9, 12, tzinfo=UTC)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def execution(base):
    phases = tuple(
        WebPhaseResult(
            phase=phase,
            status=(
                WebPhaseResultStatus.FAILED
                if phase is WebExecutionPhase.TEST
                else WebPhaseResultStatus.NOT_RUN
            ),
            command_plan_hashes=(),
            started_at=NOW if phase is WebExecutionPhase.TEST else None,
            completed_at=NOW if phase is WebExecutionPhase.TEST else None,
            exit_codes=(1,) if phase is WebExecutionPhase.TEST else (),
            stdout_refs=(
                (WebEvidenceReference("fixture/test.stdout", "f" * 64, 12, "text/plain"),)
                if phase is WebExecutionPhase.TEST
                else ()
            ),
            stderr_refs=(),
            artifact_refs=(),
            findings=(),
            failure_category=WebFailureCategory.TEST if phase is WebExecutionPhase.TEST else None,
            failure_code="TEST_FAILED" if phase is WebExecutionPhase.TEST else None,
            normalized_summary="Expected calculator result was not observed.",
        )
        for phase in WebExecutionPhase
    )
    return WebExecutionAttempt(
        id=EXECUTION,
        project_id=PROJECT,
        created_by_user_id=OWNER,
        attempt_number=1,
        previous_attempt_id=None,
        source_revision=base.reference,
        profile_validation_content_hash="a" * 64,
        execution_plan_content_hash="b" * 64,
        trigger=WebExecutionAttemptTrigger.INITIAL,
        executed_phases=(WebExecutionPhase.TEST,),
        report=WebExecutionReport(
            source_revision_content_hash=base.content_hash,
            source_tree_hash=base.source_tree_hash,
            profile_id="web.static",
            profile_version="1.0.0",
            runner_image_digest="c" * 64,
            policy_content_hash="d" * 64,
            phase_results=phases,
        ),
        started_at=NOW,
        completed_at=NOW,
    )


class FakeScope:
    def __init__(self, env, owner_user_id, project_id):
        self.env, self.session = env, env.session
        self.owner_user_id, self.project_id = owner_user_id, project_id

    async def __aenter__(self):
        await self.env.lock.acquire()
        if self.owner_user_id != OWNER or self.project_id != PROJECT:
            self.env.lock.release()
            raise HTTPException(404)
        self.before = copy.deepcopy(self.env.operations)
        self.before_sources = list(self.env.sources)
        self.env.events.append("lock")
        return self

    async def __aexit__(self, kind, value, traceback):
        if kind is not None:
            self.env.operations = self.before
            self.env.sources[:] = self.before_sources
            self.env.events.append("rollback")
        else:
            self.env.events.append("commit")
        self.env.lock.release()

    async def history(self, *, kind=None):
        return tuple(op for op in self.env.operations.values() if kind is None or op.kind == kind)

    async def get(self, operation_id):
        return self.env.operations.get(operation_id)

    async def propose(self, *, source_revision_id, kind, payload):
        operation = SimpleNamespace(
            id=uuid4(),
            project_id=PROJECT,
            owner_user_id=OWNER,
            source_revision_id=source_revision_id,
            kind=kind,
            payload=copy.deepcopy(payload),
            content_hash=digest(payload),
            state="PROPOSED",
            result=None,
        )
        self.env.operations[operation.id] = operation
        self.env.events.append("propose")
        return operation

    async def gate(self, operation):
        return self.env.gates.get(operation.id)

    async def claim(self, operation, *, expected_hash):
        assert expected_hash == operation.content_hash
        assert operation.state == "PROPOSED"
        self.env.events.append("claim")
        operation = copy.copy(operation)
        operation.state = "CLAIMED"
        self.env.operations[operation.id] = operation
        return operation

    async def finish(self, operation, *, result, succeeded):
        assert succeeded
        self.env.events.append("finish")
        operation = copy.copy(operation)
        operation.state = "SUCCEEDED"
        operation.result = result
        self.env.operations[operation.id] = operation
        return operation

    async def snapshot(self, operation):
        return {
            "id": str(operation.id),
            "content_hash": operation.content_hash,
            "kind": operation.kind,
            "payload": copy.deepcopy(operation.payload),
            "result": operation.result,
            "status": operation.state,
        }


@pytest.fixture
def environment(monkeypatch, tmp_path):
    content_root = tmp_path / "objects"
    content_store = FileSystemWebSourceContentStore(content_root)
    base = create_web_source_revision(
        revision_id=uuid4(),
        project_id=PROJECT,
        created_by_user_id=OWNER,
        version_number=1,
        based_on=None,
        target=ExecutionTarget.WEB_STATIC,
        language_configuration=WebLanguageConfiguration(
            frontend=WebImplementationLanguage.STATIC_ASSETS, backend=None
        ),
        layout=WebProjectLayout.SINGLE_ROOT,
        origin=WebSourceOrigin.DETERMINISTIC_FIXTURE,
        files=(
            content_store.store(
                normalized_path="index.html", content=b"<p>broken</p>", media_type="text/html"
            ),
        ),
        provenance_references=(
            WebSourceProvenanceReference(
                kind=WebSourceProvenanceKind.SOURCE_PLAN,
                reference_id="source-plan:fixture",
                version_number=1,
                content_hash="e" * 64,
            ),
        ),
        created_at=NOW,
    )
    attempt = execution(base)
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    row = web_execution_attempt_to_record(attempt)
    session.execute = AsyncMock(return_value=MagicMock())
    session.execute.return_value.mappings.return_value.one_or_none.return_value = row
    env = SimpleNamespace(
        session=session,
        base=base,
        attempt=attempt,
        sources=[base],
        attempts=[attempt],
        operations={},
        gates={},
        events=[],
        lock=asyncio.Lock(),
        content_root=content_root,
        content_store=content_store,
        append_status=WebSourceRevisionAppendStatus.APPENDED,
    )

    async def append(revision):
        env.events.append("append")
        if env.append_status is not WebSourceRevisionAppendStatus.APPENDED:
            return WebSourceRevisionAppendResult(env.append_status, None)
        assert revision.based_on == env.sources[-1].reference
        env.sources.append(revision)
        return WebSourceRevisionAppendResult(WebSourceRevisionAppendStatus.APPENDED, revision)

    def source_repository(supplied_session, *, owner_user_id):
        assert supplied_session is session and owner_user_id == OWNER
        return SimpleNamespace(
            current=AsyncMock(side_effect=lambda **_: env.sources[-1]),
            history=AsyncMock(side_effect=lambda **_: tuple(env.sources)),
            append=AsyncMock(side_effect=append),
        )

    def attempt_repository(supplied_session, *, owner_user_id):
        assert supplied_session is session and owner_user_id == OWNER
        return SimpleNamespace(
            current=AsyncMock(side_effect=lambda **_: env.attempts[-1]),
            history=AsyncMock(side_effect=lambda **_: tuple(env.attempts)),
        )

    monkeypatch.setattr(sut, "SqlAlchemyWebSourceRevisionRepository", source_repository)
    monkeypatch.setattr(sut, "SqlAlchemyWebExecutionAttemptRepository", attempt_repository)
    env.operation_store = SimpleNamespace(scope=lambda **values: FakeScope(env, **values))
    env.service = sut.SqlAlchemyWebRepairApiService(
        lambda: session, operation_store=env.operation_store, content_root=content_root
    )
    return env


def command(env, **changes):
    values = dict(
        base_revision_content_hash=env.base.content_hash,
        failure_signature_digest=env.attempt.report.failure_signatures()[0].digest,
        changes=(
            WebRepairChangeCommand(
                WebSourceChangeOperation.REPLACE, "index.html", "<p>fixed</p>", "text/html"
            ),
        ),
        rationale="Correct the observed calculator failure.",
    )
    values.update(changes)
    return WebRepairProposalCreateCommand(**values)


async def propose(env, value=None):
    return await env.service.create_repair_proposal(
        owner_user_id=OWNER, execution_id=EXECUTION, command=value or command(env)
    )


def approve(env, operation):
    gate = SimpleNamespace(
        id=uuid4(),
        project_id=PROJECT,
        owner_user_id=OWNER,
        gate_type=HumanGateType.HIGH_IMPACT_OPERATION,
        status=HumanGateStatus.APPROVED,
        artifact=GateArtifactReference(
            project_id=PROJECT,
            gate_type=HumanGateType.HIGH_IMPACT_OPERATION,
            artifact_id=operation.id,
            version=1,
            content_hash=operation.content_hash,
        ),
    )
    env.gates[operation.id] = gate
    return gate


async def apply(env, operation, **changes):
    values = dict(
        base_revision_content_hash=env.base.content_hash,
        proposal_content_hash=operation.content_hash,
        approval_id=env.gates[operation.id].id if operation.id in env.gates else None,
    )
    values.update(changes)
    return await env.service.apply_repair_proposal(
        owner_user_id=OWNER,
        execution_id=EXECUTION,
        proposal_id=operation.id,
        command=WebRepairProposalApplyCommand(**values),
    )


def test_proposal_persists_exact_failure_and_content_references_without_modifying_source(
    environment,
):
    env = environment
    result = asyncio.run(propose(env))
    assert result.status is WebApiCommandStatus.REPAIR_PROPOSED
    operation = next(iter(env.operations.values()))
    assert operation.kind == "REPAIR" and operation.source_revision_id == env.base.id
    assert operation.payload["execution_id"] == str(EXECUTION)
    assert operation.payload["execution_content_hash"] == env.attempt.content_hash
    proposal = web_repair_proposal_from_snapshot(operation.payload["proposal"])
    assert proposal.base_revision == env.base.reference
    assert proposal.failure_signature in env.attempt.report.failure_signatures()
    assert proposal.attempt_number == proposal.identical_failure_occurrences == 1
    assert env.content_store.read(proposal.change_set.changes[0].storage_key) == b"<p>fixed</p>"
    assert env.sources == [env.base]
    assert "<p>fixed</p>" not in json.dumps(result.snapshot)
    assert result.snapshot["id"] == str(operation.id)
    assert result.snapshot["proposal_content_hash"] == operation.content_hash


def test_apply_requires_gate7_even_for_ordinary_source_change(environment):
    env = environment
    asyncio.run(propose(env))
    result = asyncio.run(apply(env, next(iter(env.operations.values()))))
    assert result.status is WebApiCommandStatus.APPROVAL_REQUIRED
    assert env.sources == [env.base]
    assert "claim" not in env.events


def test_approved_apply_appends_immutable_revision_atomically_and_returns_domain_rerun(environment):
    env = environment
    asyncio.run(propose(env))
    operation = next(iter(env.operations.values()))
    approve(env, operation)
    original_hash = env.base.content_hash
    result = asyncio.run(apply(env, operation))
    assert result.status is WebApiCommandStatus.REPAIR_APPLIED
    assert len(env.sources) == 2 and env.sources[0].content_hash == original_hash
    assert env.sources[1].based_on == env.base.reference
    assert env.sources[1].origin is WebSourceOrigin.REPAIR_CHANGE_SET
    assert env.content_store.read(env.base.files[0].storage_key) == b"<p>broken</p>"
    assert env.sources[1].related_failure_signature == command(env).failure_signature_digest
    assert result.snapshot["required_rerun_phases"][0] == "VALIDATE"
    assert "PREPARE_WORKSPACE" not in result.snapshot["required_rerun_phases"]
    assert result.snapshot["source_revision"]["id"] == str(env.sources[1].id)
    assert env.events[-5:] == ["lock", "claim", "append", "finish", "commit"]


@pytest.mark.parametrize("field", ["base_revision_content_hash", "failure_signature_digest"])
def test_create_refuses_stale_base_or_unobserved_failure_before_storing_content(environment, field):
    env = environment
    result = asyncio.run(propose(env, command(env, **{field: "f" * 64})))
    assert result.status is WebApiCommandStatus.CONFLICT
    assert not env.operations and env.sources == [env.base]


@pytest.mark.parametrize("field", ["status", "owner", "hash", "id"])
def test_wrong_gate_does_not_claim_approval(environment, field):
    env = environment
    asyncio.run(propose(env))
    operation = next(iter(env.operations.values()))
    gate = approve(env, operation)
    changes = {}
    if field == "status":
        gate.status = HumanGateStatus.PENDING_APPROVAL
    elif field == "owner":
        gate.owner_user_id = uuid4()
    elif field == "hash":
        gate.artifact = replace(gate.artifact, content_hash="f" * 64)
    else:
        changes["approval_id"] = uuid4()
    assert (
        asyncio.run(apply(env, operation, **changes)).status
        is WebApiCommandStatus.APPROVAL_REQUIRED
    )
    assert "claim" not in env.events and len(env.sources) == 1


def test_failed_append_rolls_back_claim_and_operation_result(environment):
    env = environment
    asyncio.run(propose(env))
    operation = next(iter(env.operations.values()))
    approve(env, operation)
    env.append_status = WebSourceRevisionAppendStatus.VERSION_CONFLICT
    result = asyncio.run(apply(env, operation))
    assert result.status is WebApiCommandStatus.CONFLICT
    assert env.operations[operation.id].state == "PROPOSED"
    assert env.events[-1] == "rollback" and len(env.sources) == 1


def test_missing_owned_attempt_has_no_repair_disclosure_or_writes(environment):
    env = environment
    env.session.execute.return_value.mappings.return_value.one_or_none.return_value = None
    result = asyncio.run(propose(env))
    assert result.status is WebApiCommandStatus.NOT_FOUND
    assert not env.events
    compiled = env.session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "archived_at IS NULL" in str(compiled)
    assert OWNER in compiled.params.values() and EXECUTION in compiled.params.values()


def test_proposal_serializer_rejects_tampering_and_false_integer_after_rehash(environment):
    env = environment
    asyncio.run(propose(env))
    snapshot = next(iter(env.operations.values())).payload["proposal"]
    assert web_repair_proposal_to_snapshot(web_repair_proposal_from_snapshot(snapshot)) == snapshot
    changed = copy.deepcopy(snapshot)
    changed["change_set"]["changes"][0]["content_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        web_repair_proposal_from_snapshot(changed)
    changed = copy.deepcopy(snapshot)
    changed["attempt_number"] = True
    changed["content_hash"] = digest({k: v for k, v in changed.items() if k != "content_hash"})
    with pytest.raises(ValueError):
        web_repair_proposal_from_snapshot(changed)


@pytest.mark.parametrize("when", ["create", "apply"])
def test_newer_attempt_invalidates_repair_base_even_when_source_is_unchanged(environment, when):
    env = environment
    if when == "apply":
        asyncio.run(propose(env))
        operation = next(iter(env.operations.values()))
        approve(env, operation)
    env.attempts.append(
        replace(
            env.attempt,
            id=uuid4(),
            attempt_number=2,
            previous_attempt_id=EXECUTION,
            trigger=WebExecutionAttemptTrigger.MANUAL_RERUN,
        )
    )
    result = asyncio.run(propose(env) if when == "create" else apply(env, operation))
    assert result.status is WebApiCommandStatus.CONFLICT
    assert result.message == "WEB_REPAIR_STALE_EXECUTION"
    assert "claim" not in env.events and len(env.sources) == 1


def test_concurrent_apply_claims_exact_approval_once_and_keeps_linear_lineage(environment):
    env = environment

    async def scenario():
        await propose(env)
        operation = next(iter(env.operations.values()))
        approve(env, operation)
        return await asyncio.gather(apply(env, operation), apply(env, operation))

    results = asyncio.run(scenario())
    assert sorted(result.status for result in results) == sorted(
        [WebApiCommandStatus.REPAIR_APPLIED, WebApiCommandStatus.CONFLICT]
    )
    assert len(env.sources) == 2 and env.events.count("claim") == env.events.count("append") == 1


def test_proposal_count_limit_is_read_from_persisted_project_operations(environment):
    env = environment

    async def scenario():
        for _ in range(5):
            assert (await propose(env)).status is WebApiCommandStatus.REPAIR_PROPOSED
        return await propose(env)

    result = asyncio.run(scenario())
    assert result.status is WebApiCommandStatus.CONFLICT
    assert result.message == "WEB_REPAIR_PAUSED_NEEDS_HUMAN"
    assert len(env.operations) == 5


def test_repeated_actual_failure_stops_repair_despite_no_prior_proposal(environment):
    env = environment
    first = replace(env.attempt, id=uuid4())
    second = replace(
        env.attempt,
        id=uuid4(),
        attempt_number=2,
        previous_attempt_id=first.id,
        trigger=WebExecutionAttemptTrigger.MANUAL_RERUN,
    )
    env.attempt = replace(
        env.attempt,
        attempt_number=3,
        previous_attempt_id=second.id,
        trigger=WebExecutionAttemptTrigger.MANUAL_RERUN,
    )
    env.attempts[:] = [first, second, env.attempt]
    env.session.execute.return_value.mappings.return_value.one_or_none.return_value = (
        web_execution_attempt_to_record(env.attempt)
    )
    result = asyncio.run(propose(env))
    assert result.status is WebApiCommandStatus.CONFLICT
    assert result.message == "WEB_REPAIR_PAUSED_NEEDS_HUMAN" and not env.operations


@pytest.mark.parametrize(
    "change", ["content", "media", "path", "delete_all", "unchanged", "collision"]
)
def test_unsafe_unbounded_or_semantically_invalid_changes_never_persist_proposal(
    environment, change
):
    env = environment
    choices = {
        "content": (
            WebRepairChangeCommand(
                WebSourceChangeOperation.REPLACE, "index.html", "é" * 524289, "text/html"
            ),
        ),
        "media": (
            WebRepairChangeCommand(
                WebSourceChangeOperation.ADD, "run.exe", "bytes", "application/octet-stream"
            ),
        ),
        "path": (
            WebRepairChangeCommand(
                WebSourceChangeOperation.ADD, "../escape.js", "text", "text/plain"
            ),
        ),
        "delete_all": (
            WebRepairChangeCommand(WebSourceChangeOperation.DELETE, "index.html", None, None),
        ),
        "unchanged": (
            WebRepairChangeCommand(
                WebSourceChangeOperation.REPLACE, "index.html", "<p>broken</p>", "text/html"
            ),
        ),
        "collision": (
            WebRepairChangeCommand(
                WebSourceChangeOperation.ADD, "index.html/nested", "text", "text/plain"
            ),
        ),
    }
    result = asyncio.run(propose(env, command(env, changes=choices[change])))
    assert result.status is WebApiCommandStatus.INVALID
    assert not env.operations and env.sources == [env.base]


def test_missing_or_corrupt_repair_content_prevents_claim_and_append(environment):
    env = environment
    asyncio.run(propose(env))
    operation = next(iter(env.operations.values()))
    approve(env, operation)
    change = operation.payload["proposal"]["change_set"]["changes"][0]
    (env.content_root / change["storage_key"]).write_bytes(b"tampered")
    result = asyncio.run(apply(env, operation))
    assert result.status is WebApiCommandStatus.CONFLICT
    assert "claim" not in env.events and env.sources == [env.base]


def test_retained_base_content_must_exist_before_new_revision_can_be_claimed(environment):
    env = environment
    retained = env.content_store.store(
        normalized_path="retained.js", content=b"const ready = true;", media_type="text/javascript"
    )
    env.base = replace(env.base, files=(*env.base.files, retained))
    env.sources[:] = [env.base]
    env.attempt = execution(env.base)
    env.attempts[:] = [env.attempt]
    env.session.execute.return_value.mappings.return_value.one_or_none.return_value = (
        web_execution_attempt_to_record(env.attempt)
    )
    asyncio.run(propose(env))
    operation = next(iter(env.operations.values()))
    approve(env, operation)
    (env.content_root / retained.storage_key).unlink()
    result = asyncio.run(apply(env, operation))
    assert result.status is WebApiCommandStatus.CONFLICT
    assert "claim" not in env.events and env.sources == [env.base]


def test_list_keeps_verified_proposal_after_application_and_refuses_corruption(environment):
    env = environment
    asyncio.run(propose(env))
    operation = next(iter(env.operations.values()))
    approve(env, operation)
    assert asyncio.run(apply(env, operation)).status is WebApiCommandStatus.REPAIR_APPLIED
    items = asyncio.run(env.service.repair_proposals(owner_user_id=OWNER, execution_id=EXECUTION))
    assert len(items) == 1 and items[0]["id"] == str(operation.id)
    assert items[0]["result"]["source_revision"]["id"] == str(env.sources[1].id)
    env.operations[operation.id].payload["proposal"]["attempt_number"] += 1
    with pytest.raises(HTTPException) as caught:
        asyncio.run(env.service.repair_proposals(owner_user_id=OWNER, execution_id=EXECUTION))
    assert caught.value.status_code == 409


def test_high_impact_change_requires_same_gate_and_returns_full_domain_rerun(environment):
    env = environment
    value = command(
        env,
        changes=(
            WebRepairChangeCommand(
                WebSourceChangeOperation.ADD, "package.json", "{}", "application/json"
            ),
        ),
    )
    assert asyncio.run(propose(env, value)).status is WebApiCommandStatus.REPAIR_PROPOSED
    operation = next(iter(env.operations.values()))
    assert asyncio.run(apply(env, operation)).status is WebApiCommandStatus.APPROVAL_REQUIRED
    approve(env, operation)
    result = asyncio.run(apply(env, operation))
    assert result.status is WebApiCommandStatus.REPAIR_APPLIED
    assert result.snapshot["required_rerun_phases"] == [phase.value for phase in WebExecutionPhase]


def test_finish_failure_rolls_back_new_source_and_single_use_claim(environment, monkeypatch):
    env = environment
    asyncio.run(propose(env))
    operation = next(iter(env.operations.values()))
    approve(env, operation)

    async def fail(*args, **kwargs):
        raise sut.WebOperationError("WEB_OPERATION_RESULT_CONFLICT")

    monkeypatch.setattr(FakeScope, "finish", fail)
    result = asyncio.run(apply(env, operation))
    assert result.status is WebApiCommandStatus.CONFLICT
    assert env.events[-1] == "rollback" and env.sources == [env.base]
    assert env.operations[operation.id].state == "PROPOSED"


def test_create_refuses_redirected_content_subdirectory(environment, monkeypatch):
    env = environment
    content_hash = hashlib.sha256(b"<p>fixed</p>").hexdigest()
    redirect = env.content_root / "sha256" / content_hash[:2]
    path_type = type(redirect)
    original = path_type.is_junction
    monkeypatch.setattr(path_type, "is_junction", lambda path: path == redirect or original(path))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(propose(env))
    assert caught.value.status_code == 503
    assert not env.operations and env.sources == [env.base]


@pytest.mark.parametrize("kind", ["unknown", "content_key", "change_size", "failure_hash"])
def test_verified_serializer_rejects_rehashed_noncanonical_nested_metadata(environment, kind):
    env = environment
    asyncio.run(propose(env))
    value = copy.deepcopy(next(iter(env.operations.values())).payload["proposal"])
    if kind == "unknown":
        value["unexpected"] = "ignored?"
    elif kind == "content_key":
        value["change_set"]["changes"][0]["storage_key"] = "sha256/ff/" + "f" * 64
    elif kind == "change_size":
        value["change_set"]["changes"][0]["size_bytes"] = True
    else:
        value["failure_signature"]["digest"] = "f" * 64
    change_set = value["change_set"]
    change_set["content_hash"] = digest(
        {k: v for k, v in change_set.items() if k != "content_hash"}
    )
    value["content_hash"] = digest({k: v for k, v in value.items() if k != "content_hash"})
    with pytest.raises(ValueError):
        web_repair_proposal_from_snapshot(value)
