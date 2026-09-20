"""Real API/database transactions with synthetic governance and model completions."""

import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.jvm_execution import JvmRepairProposalApplyCommand
from orchestwin.api.jvm_repair_runtime import SqlAlchemyJvmRepairApiService
from orchestwin.api.jvm_source_runtime import SqlAlchemyJvmSourceApiService
from orchestwin.api.services import ApplicationRuntime
from orchestwin.api.web_execution import WebRepairProposalApplyCommand
from orchestwin.api.web_repair_runtime import SqlAlchemyWebRepairApiService
from orchestwin.api.web_source_runtime import SqlAlchemyWebSourceApiService
from orchestwin.artifacts.architecture_packages import ArchitecturePackageVersion
from orchestwin.artifacts.architecture_persistence import SqlAlchemyArchitecturePackageRepository
from orchestwin.artifacts.design_persistence import SqlAlchemyDesignPackageRepository
from orchestwin.artifacts.jvm_source_persistence import SqlAlchemyJvmSourceRevisionRepository
from orchestwin.artifacts.web_source_persistence import SqlAlchemyWebSourceRevisionRepository
from orchestwin.config import ApplicationSettings
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.jvm_execution.attempt_persistence import SqlAlchemyJvmExecutionAttemptRepository
from orchestwin.jvm_execution.attempts import JvmExecutionAttempt, JvmExecutionAttemptTrigger
from orchestwin.jvm_execution.operation_persistence import SqlAlchemyJvmOperationStore
from orchestwin.jvm_execution.plans import JvmExecutionPhase
from orchestwin.jvm_execution.targets import jvm_scope_for
from orchestwin.models.proposal_evidence import ProposalEvidenceError
from orchestwin.models.proposal_evidence_persistence import (
    LINKS,
    SqlAlchemyProposalEvidenceBindings,
    SqlAlchemyProposalEvidenceStore,
)
from orchestwin.models.source_proposals import ModelSourceProposalAdapter
from orchestwin.persistence import create_database_runtime
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.projects.requirements_persistence import (
    SqlAlchemyRequirementsSpecificationRepository,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.attempt_persistence import SqlAlchemyWebExecutionAttemptRepository
from orchestwin.web_execution.operation_persistence import SqlAlchemyWebOperationStore
from orchestwin.workflow.gates import HumanGateType
from src.test.python.api import test_api_web_repair_runtime as web_fixture
from src.test.python.integration.test_postgresql_workflow_progression import (
    _approve_gate,
    _persist_pending_gate,
)
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.jvm_execution import attempt_support as jvm_fixture
from src.test.python.models.test_fake_architecture import proposal_request, propose
from src.test.python.models.test_proposal_evidence import audited_generator
from src.test.python.models.test_source_file_generation import source_sequence_generator

__all__ = ["database"]
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("ORCHESTWIN_PROPOSAL_EVIDENCE_TEST_DATABASE_URL"),
        reason="explicit disposable PostgreSQL required",
    ),
]
ROOT = Path(__file__).resolve().parents[4]
TARGETS = [
    ExecutionTarget.WEB_STATIC,
    ExecutionTarget.JVM_JAVA,
    ExecutionTarget.JVM_KOTLIN,
    ExecutionTarget.JVM_SCALA,
]


def artifacts():
    request = proposal_request()
    package = propose(request).package
    architecture = ArchitecturePackageVersion(
        id=uuid4(),
        project_id=request.project_id,
        version_number=1,
        package=package,
        content_hash=package.content_hash,
        created_by_user_id=request.requirements.version.created_by_user_id,
        created_at=datetime.now(UTC),
    )
    return request.requirements.version, request.design.version, architecture


async def seed(database_runtime, versions, *, approved=True):
    requirements, design, architecture = versions
    owner, project = architecture.created_by_user_id, architecture.project_id
    async with database_runtime.session_factory() as session, session.begin():
        session.add(
            UserRecord(
                id=owner,
                email_normalized=f"{owner}@synthetic.invalid",
                password_hash="NO_LOGIN_SYNTHETIC",
            )
        )
        await session.flush()
        session.add(
            ProjectRecord(
                id=project,
                owner_user_id=owner,
                display_name="Synthetic source generation",
                mode="GREENFIELD_GENERATION",
            )
        )
        await session.flush()
        for repository, version in (
            (SqlAlchemyRequirementsSpecificationRepository, requirements),
            (SqlAlchemyDesignPackageRepository, design),
            (SqlAlchemyArchitecturePackageRepository, architecture),
        ):
            assert (
                await repository(session, owner_user_id=owner).append(version)
            ).value == "APPENDED"
    await _persist_pending_gate(
        database_runtime,
        owner_id=owner,
        project_id=project,
        gate_id=uuid4(),
        gate_type=HumanGateType.ARCHITECTURE,
        artifact_id=architecture.id,
        artifact_hash=architecture.content_hash,
        occurred_at=datetime.now(UTC),
    )
    if approved:
        await _approve_gate(
            database_runtime,
            owner_id=owner,
            project_id=project,
            gate_type=HumanGateType.ARCHITECTURE,
            occurred_at=datetime.now(UTC),
        )
    return owner, project


def application(database_runtime, directory, generator):
    sessions = database_runtime.session_factory
    return ApplicationRuntime(
        database_runtime=database_runtime,
        real_model_runtime=SimpleNamespace(sources=ModelSourceProposalAdapter(generator)),
        proposal_evidence_store=SqlAlchemyProposalEvidenceStore(sessions),
        web_source_api_service=SqlAlchemyWebSourceApiService(
            sessions, content_root=directory / "web"
        ),
        jvm_source_api_service=SqlAlchemyJvmSourceApiService(
            sessions, content_root=directory / "jvm", repo_root=ROOT
        ),
        web_repair_api_service=SqlAlchemyWebRepairApiService(
            sessions,
            operation_store=SqlAlchemyWebOperationStore(sessions),
            content_root=directory / "web",
        ),
        jvm_repair_api_service=SqlAlchemyJvmRepairApiService(
            sessions,
            operation_store=SqlAlchemyJvmOperationStore(sessions),
            content_root=directory / "jvm",
            repo_root=ROOT,
        ),
    )


def source_output(target):
    path = {
        ExecutionTarget.WEB_STATIC: "index.html",
        ExecutionTarget.JVM_JAVA: "src/main/java/org/orchestwin/greeting/Main.java",
        ExecutionTarget.JVM_KOTLIN: "src/main/kotlin/org/orchestwin/calculator/Main.kt",
        ExecutionTarget.JVM_SCALA: "src/main/scala/org/orchestwin/greeting/Main.scala",
    }[target]
    content = {
        ExecutionTarget.WEB_STATIC: (
            '<!doctype html><title>Fixture</title><section data-design-screen="SCR-001">'
            '<input name="guest_name" required aria-label="Guest name" data-design-element="ELM-001">'
            '<button data-design-element="ELM-002" data-design-target="SCR-002">Save reservation</button>'
            '</section><section data-design-screen="SCR-002"><p>Reservation saved</p></section>'
        ),
        ExecutionTarget.JVM_JAVA: 'package org.orchestwin.greeting; public class Main { public static void main(String[] args) { System.out.println("Fixture"); } }',
        ExecutionTarget.JVM_KOTLIN: 'package org.orchestwin.calculator\nfun main() { println("Fixture") }',
        ExecutionTarget.JVM_SCALA: 'package org.orchestwin.greeting\nobject Main { def main(args: Array[String]): Unit = println("Fixture") }',
    }[target]
    test_path = (
        "app.test.cjs"
        if target is ExecutionTarget.WEB_STATIC
        else path.replace("src/main/", "src/test/").replace("Main.", "MainTest.")
    )
    test_files = [
        {
            "normalized_path": test_path,
            "media_type": "text/javascript"
            if target is ExecutionTarget.WEB_STATIC
            else "text/plain",
            "content": "// Synthetic test source; this fixture checks persistence only.",
        }
    ]
    if target is ExecutionTarget.WEB_STATIC:
        test_files.insert(
            0,
            {
                "normalized_path": "app.js",
                "media_type": "text/javascript",
                "content": "const synthetic = 'Fixture';",
            },
        )
    entry = {
        "normalized_path": path,
        "content": content,
        "media_type": "text/html" if target is ExecutionTarget.WEB_STATIC else "text/plain",
    }
    return {
        "rationale": "Implement the synthetic approved context.",
        "files": [*test_files, entry]
        if target is ExecutionTarget.WEB_STATIC
        else [entry, *test_files],
    }


def body(target, architecture):
    return {
        "target": target.value,
        "architecture_version_id": str(architecture.id),
        "architecture_content_hash": architecture.content_hash,
        **({"frontend_language": "STATIC_ASSETS"} if target is ExecutionTarget.WEB_STATIC else {}),
    }


def client_app(runtime, owner):
    app = create_app(
        ApplicationSettings(_env_file=None),
        runtime=runtime,
        auth_settings=AuthApiSettings(_env_file=None),
    )
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id=owner)
    return app


@pytest.mark.parametrize("target", TARGETS)
def test_generated_sources_use_governed_api_and_exact_atomic_link(database, tmp_path, target):
    versions = artifacts()
    generator, transport = source_sequence_generator(tmp_path, source_output(target))

    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project = await seed(db, versions)
            runtime = application(db, tmp_path, generator)
            platform = "web" if target is ExecutionTarget.WEB_STATIC else "jvm"
            app = client_app(runtime, owner)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://synthetic/api/v1"
            ) as client:
                response = await client.post(
                    f"/projects/{project}/source-generations/{platform}",
                    json=body(target, versions[2]),
                )
                assert response.status_code == 201, response.text
                snapshot = response.json()["snapshot"]
                generation = UUID(snapshot["model_generation_id"])
                evidence = await runtime.proposal_evidence_store.get_owned(
                    owner_user_id=owner, project_id=project, generation_id=generation
                )
                assert evidence["publication_state"] == "ARTIFACTS_LINKED"
                assert len(evidence["artifact_links"]) == 1
                link = evidence["artifact_links"][0]["artifact"]
                assert (
                    link["kind"] == platform.upper() + "_SOURCE"
                    and link["version_id"] == snapshot["id"]
                    and link["content_hash"] == snapshot["content_hash"]
                )
                accepted = next(
                    e for e in evidence["observations"] if e["kind"] == "ADAPTER_ACCEPTED"
                )
                assert accepted["payload"]["source_binding"]["files"] == snapshot["files"]
                assert len(evidence["source_children"]) == len(source_output(target)["files"])
                child = await runtime.proposal_evidence_store.get_owned(
                    owner_user_id=owner,
                    project_id=project,
                    generation_id=UUID(evidence["source_children"][0]["generation_id"]),
                )
                assert child["source_parent"]["parent_generation_id"] == str(generation)
                assert child["artifact_links"] == []
                assert (
                    await client.post(
                        f"/projects/{project}/source-generations/{platform}",
                        json=body(target, versions[2]),
                    )
                ).status_code == 409
                assert len(transport.calls) == 1 + len(source_output(target)["files"])
        finally:
            await db.dispose()

    run(scenario())


@pytest.mark.parametrize(
    "tamper",
    [
        "child_bytes",
        "aggregate_bytes",
        "binding_bytes",
        "missing_child",
        "child_hash",
        "child_reference",
    ],
)
def test_sql_rejects_source_lineage_tampering(database, tmp_path, monkeypatch, tamper):
    from copy import deepcopy

    versions = artifacts()
    generator, _ = source_sequence_generator(tmp_path, source_output(ExecutionTarget.WEB_STATIC))
    original = SqlAlchemyProposalEvidenceStore.append

    async def altered(self, **kwargs):
        if kwargs["kind"] == "ADAPTER_ACCEPTED":
            payload = deepcopy(kwargs["payload"])
            if "source_file" in payload and tamper == "child_bytes":
                payload["source_file"]["content"] += "Injected bytes"
            elif "result" in payload:
                if tamper == "aggregate_bytes":
                    payload["result"]["output"]["files"][0]["content"] += "Injected bytes"
                elif tamper == "binding_bytes":
                    payload["source_binding"]["files"][0]["sha256_digest"] = "a" * 64
                elif tamper == "missing_child":
                    payload["result"]["generation_steps"] = []
                elif tamper == "child_hash":
                    payload["result"]["generation_steps"][0]["request_hash"] = "b" * 64
                elif tamper == "child_reference":
                    payload["result"]["generation_steps"][0]["generation_id"] = str(uuid4())
            kwargs["payload"] = payload
        return await original(self, **kwargs)

    monkeypatch.setattr(SqlAlchemyProposalEvidenceStore, "append", altered)

    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project = await seed(db, versions)
            runtime = application(db, tmp_path, generator)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client_app(runtime, owner)),
                base_url="http://synthetic/api/v1",
            ) as client:
                response = await client.post(
                    f"/projects/{project}/source-generations/web",
                    json=body(ExecutionTarget.WEB_STATIC, versions[2]),
                )
                assert response.status_code == 503, response.text
            assert (
                await runtime.web_source_api_service.source_revision_history(
                    owner_user_id=owner, project_id=project
                )
                == ()
            )
            async with db.session_factory() as session:
                assert await session.scalar(sa.select(sa.func.count()).select_from(LINKS)) == 0
        finally:
            await db.dispose()

    run(scenario())


@pytest.mark.parametrize(
    "field", ["parent_generation_id", "parent_request_hash", "manifest_hash", "ordinal", "file"]
)
def test_sql_rejects_file_request_with_wrong_manifest(database, tmp_path, monkeypatch, field):
    import json
    from dataclasses import fields

    from orchestwin.models.structured_generation import create_structured_generation_request

    versions = artifacts()
    generator, transport = source_sequence_generator(
        tmp_path, source_output(ExecutionTarget.WEB_STATIC)
    )
    original = SqlAlchemyProposalEvidenceStore.begin

    async def altered(self, **kwargs):
        request = kwargs["request"]
        payload = json.loads(request.input_payload_json)
        step = payload["context"].get("source_step")
        if step:
            step[field] = {
                "parent_generation_id": str(uuid4()),
                "parent_request_hash": "f" * 64,
                "manifest_hash": "e" * 64,
                "ordinal": 9,
                "file": {**step["file"], "normalized_path": "other.html"},
            }[field]
            parameters = {
                f.name: getattr(request, f.name)
                for f in fields(request)
                if f.name not in {"schema_version", "content_hash", "input_payload_json"}
            }
            # Recompute valid request/snapshot hashes: only the relational guard can reject this.
            kwargs["request"] = create_structured_generation_request(
                **parameters, input_payload=payload
            )
        return await original(self, **kwargs)

    monkeypatch.setattr(SqlAlchemyProposalEvidenceStore, "begin", altered)

    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project = await seed(db, versions)
            runtime = application(db, tmp_path, generator)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client_app(runtime, owner)),
                base_url="http://synthetic/api/v1",
            ) as client:
                response = await client.post(
                    f"/projects/{project}/source-generations/web",
                    json=body(ExecutionTarget.WEB_STATIC, versions[2]),
                )
            assert response.status_code == 503, response.text
            assert len(transport.calls) == 1
            assert (
                await runtime.web_source_api_service.source_revision_history(
                    owner_user_id=owner, project_id=project
                )
                == ()
            )
            rows = await runtime.proposal_evidence_store.list_owned(
                owner_user_id=owner, project_id=project
            )
            assert len(rows) == 1
        finally:
            await db.dispose()

    run(scenario())


async def failed_attempt(db, owner, project, target):
    """Persist explicitly synthetic failure reports, never production execution evidence."""
    web = target is ExecutionTarget.WEB_STATIC
    sources = (
        SqlAlchemyWebSourceRevisionRepository if web else SqlAlchemyJvmSourceRevisionRepository
    )
    attempts = (
        SqlAlchemyWebExecutionAttemptRepository if web else SqlAlchemyJvmExecutionAttemptRepository
    )
    async with db.session_factory() as session, session.begin():
        base = await sources(session, owner_user_id=owner).current(project_id=project)
        if web:
            template = web_fixture.execution(
                SimpleNamespace(
                    reference=replace(base.reference, project_id=web_fixture.PROJECT),
                    content_hash=base.content_hash,
                    source_tree_hash=base.source_tree_hash,
                )
            )
            attempt = replace(
                template,
                id=uuid4(),
                project_id=project,
                created_by_user_id=owner,
                source_revision=base.reference,
            )
        else:
            bundle, report = jvm_fixture.execution_report(
                target, failure_phase=JvmExecutionPhase.TEST
            )
            scope = jvm_scope_for(target)
            attempt = JvmExecutionAttempt(
                id=uuid4(),
                project_id=project,
                created_by_user_id=owner,
                attempt_number=1,
                previous_attempt_id=None,
                source_revision=base.reference,
                profile_id=scope.profile_id,
                profile_version=scope.profile_version,
                profile_validation_content_hash="d" * 64,
                execution_plan_content_hash=bundle.content_hash,
                runner_id="synthetic.fixture",
                runner_version="1.0.0",
                runner_image_digest="e" * 64,
                policy_content_hash="f" * 64,
                trigger=JvmExecutionAttemptTrigger.INITIAL,
                executed_phases=tuple(JvmExecutionPhase),
                report=report,
                started_at=jvm_fixture.STARTED_AT,
                completed_at=jvm_fixture.COMPLETED_AT,
            )
        assert (
            await attempts(session, owner_user_id=owner).append(attempt)
        ).status.value == "APPENDED"
    signature = (
        attempt.report.failure_signatures()[0].digest
        if web
        else attempt.report.failure_signatures[0].signature
    )
    return attempt, {
        "base_revision_content_hash": base.content_hash,
        "failure_signature_digest": signature,
    }


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("failure", [None, "stale", "signature", "different_bytes", "missing_logs"])
def test_generated_repairs_remain_pending_and_exact(
    database, tmp_path, monkeypatch, target, failure
):
    versions = artifacts()
    output = source_output(target)
    generator, _ = source_sequence_generator(tmp_path, output)

    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project = await seed(db, versions)
            runtime = application(db, tmp_path, generator)
            platform = "web" if target is ExecutionTarget.WEB_STATIC else "jvm"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client_app(runtime, owner)),
                base_url="http://synthetic/api/v1",
            ) as client:
                initial = await client.post(
                    f"/projects/{project}/source-generations/{platform}",
                    json=body(target, versions[2]),
                )
                assert initial.status_code == 201, initial.text
                attempt, request_body = await failed_attempt(db, owner, project, target)
                repair_output = {
                    "rationale": "Repair the recorded synthetic failure.",
                    "changes": [
                        {
                            **output["files"][0],
                            "operation": "REPLACE",
                            "content": output["files"][0]["content"].replace("Fixture", "Repaired"),
                            "media_type": (
                                output["files"][0]["media_type"]
                                if platform == "web"
                                else "application/octet-stream"
                            ),
                        }
                    ],
                }
                repair_directory = tmp_path / "repair"
                repair_directory.mkdir()
                repair_generator, transport = audited_generator(repair_directory, repair_output)
                runtime.real_model_runtime.sources = ModelSourceProposalAdapter(repair_generator)
                service = getattr(runtime, platform + "_repair_api_service")
                if failure == "stale":
                    request_body["base_revision_content_hash"] = "f" * 64
                elif failure == "signature":
                    request_body["failure_signature_digest"] = "f" * 64
                elif failure == "missing_logs":
                    setattr(
                        runtime,
                        platform + "_execution_start_api_service",
                        SimpleNamespace(
                            backend=SimpleNamespace(evidence_root=tmp_path / "missing-evidence")
                        ),
                    )
                elif failure == "different_bytes":
                    original = service.create_repair_proposal

                    async def changed(**kwargs):
                        command = kwargs["command"]
                        kwargs["command"] = replace(
                            command, changes=(replace(command.changes[0], content="Other bytes"),)
                        )
                        return await original(**kwargs)

                    monkeypatch.setattr(service, "create_repair_proposal", changed)
                response = await client.post(
                    f"/projects/{project}/repair-generations/{platform}/{attempt.id}",
                    json=request_body,
                )
                assert response.status_code == (
                    201 if failure is None else 503 if failure == "different_bytes" else 409
                ), response.text
                assert len(transport.calls) == (
                    0 if failure in ("stale", "signature", "missing_logs") else 1
                )
                if transport.calls:
                    import json

                    recorded_context = json.loads(
                        transport.calls[0]["payload"]["messages"][1]["content"]
                    )["context"]
                    grounding = recorded_context["approved_context"]
                    assert grounding["status"] == "EXACT_SOURCE_ARCHITECTURE"
                    for name, version in zip(
                        ("requirements", "design", "architecture"), versions, strict=True
                    ):
                        assert grounding[name]["reference"]["id"] == str(version.id)
                        assert grounding[name]["reference"]["content_hash"] == version.content_hash
                    failed_phase = next(
                        phase
                        for phase in attempt.report.phase_results
                        if phase.phase.value == recorded_context["failure_signature"]["phase"]
                    )
                    assert recorded_context["recorded_failure"]["findings"] == [
                        finding.to_snapshot() for finding in failed_phase.findings
                    ]
                    assert (
                        recorded_context["recorded_failure"]["failure_code"]
                        == failed_phase.failure_code
                    )
                proposals = await service.repair_proposals(
                    owner_user_id=owner, execution_id=attempt.id
                )
                if failure:
                    assert proposals == ()
                else:
                    assert len(proposals) == 1
                    snapshot = response.json()["snapshot"]
                    assert snapshot["state"] == "PENDING"
                    assert snapshot["gate"]["status"] == "PENDING_APPROVAL"
                    apply_command = (
                        WebRepairProposalApplyCommand
                        if platform == "web"
                        else JvmRepairProposalApplyCommand
                    )
                    denied = await service.apply_repair_proposal(
                        owner_user_id=owner,
                        execution_id=attempt.id,
                        proposal_id=UUID(snapshot["id"]),
                        command=apply_command(
                            base_revision_content_hash=request_body["base_revision_content_hash"],
                            proposal_content_hash=snapshot["content_hash"],
                            approval_id=None,
                        ),
                    )
                    assert denied.status.value == "APPROVAL_REQUIRED"
                    evidence = await runtime.proposal_evidence_store.get_owned(
                        owner_user_id=owner,
                        project_id=project,
                        generation_id=UUID(snapshot["model_generation_id"]),
                    )
                    assert evidence["publication_state"] == "ARTIFACTS_LINKED"
                    assert (
                        evidence["artifact_links"][0]["artifact"]["content_hash"]
                        == snapshot["content_hash"]
                    )
                    accepted = next(
                        e for e in evidence["observations"] if e["kind"] == "ADAPTER_ACCEPTED"
                    )["payload"]["source_binding"]
                    assert (
                        accepted["changes"]
                        == snapshot["payload"]["proposal"]["change_set"]["changes"]
                    )
                    assert accepted["execution_content_hash"] == attempt.content_hash
                repository = (
                    SqlAlchemyWebSourceRevisionRepository
                    if platform == "web"
                    else SqlAlchemyJvmSourceRevisionRepository
                )
                async with db.session_factory() as session:
                    history = await repository(session, owner_user_id=owner).history(
                        project_id=project
                    )
                assert len(history) == 1
        finally:
            await db.dispose()

    run(scenario())


@pytest.mark.parametrize(
    "failure", ["approval", "foreign", "stale", "link_write", "different_bytes"]
)
def test_source_admission_and_atomic_rollback(database, tmp_path, monkeypatch, failure):
    versions = artifacts()
    generator, transport = source_sequence_generator(
        tmp_path, source_output(ExecutionTarget.WEB_STATIC)
    )

    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project = await seed(db, versions, approved=failure != "approval")
            runtime = application(db, tmp_path, generator)
            request_body = body(ExecutionTarget.WEB_STATIC, versions[2])
            if failure == "stale":
                request_body["architecture_content_hash"] = "f" * 64
            if failure == "link_write":
                monkeypatch.setattr(
                    SqlAlchemyProposalEvidenceBindings,
                    "bind",
                    AsyncMock(side_effect=ProposalEvidenceError("ATOMIC_EVIDENCE_BINDING_FAILED")),
                )
            if failure == "different_bytes":
                original = runtime.web_source_api_service.create_source_revision
                from dataclasses import replace

                async def changed(**kwargs):
                    command = kwargs["command"]
                    kwargs["command"] = replace(
                        command, files=(replace(command.files[0], content="Different bytes"),)
                    )
                    return await original(**kwargs)

                runtime.web_source_api_service.create_source_revision = changed
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(
                    app=client_app(runtime, uuid4() if failure == "foreign" else owner)
                ),
                base_url="http://synthetic/api/v1",
            ) as client:
                response = await client.post(
                    f"/projects/{project}/source-generations/web", json=request_body
                )
                assert response.status_code in (404, 409, 503), response.text
            assert len(transport.calls) == (
                1 + len(source_output(ExecutionTarget.WEB_STATIC)["files"])
                if failure in ("link_write", "different_bytes")
                else 0
            )
            assert (
                await runtime.web_source_api_service.source_revision_history(
                    owner_user_id=owner, project_id=project
                )
                == ()
            )
            async with db.session_factory() as session:
                assert await session.scalar(sa.select(sa.func.count()).select_from(LINKS)) == 0
            if transport.calls:
                rows = await runtime.proposal_evidence_store.list_owned(
                    owner_user_id=owner, project_id=project
                )
                evidence = await runtime.proposal_evidence_store.get_owned(
                    owner_user_id=owner,
                    project_id=project,
                    generation_id=UUID(rows[0]["generation_id"]),
                )
                assert evidence["publication_state"] == "MODEL_ACCEPTED_WITHOUT_PUBLICATION"
        finally:
            await db.dispose()

    run(scenario())
