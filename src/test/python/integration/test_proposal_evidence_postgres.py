"""Opt-in disposable PostgreSQL checks with explicitly synthetic completions."""

import asyncio
import base64
import json
import os
import selectors
import sys
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from pydantic import SecretStr

from orchestwin.agents.persistence.models import TeamProposalVersionRecord
from orchestwin.agents.persistence.repositories import SqlAlchemyTeamProposalVersionRepository
from orchestwin.agents.persistence.unit_of_work import SqlAlchemyTeamProposalUnitOfWorkFactory
from orchestwin.agents.proposals import LocalTeamProposalApplicationService
from orchestwin.artifacts.architecture_packages import ArchitecturePackageVersion
from orchestwin.artifacts.architecture_persistence import SqlAlchemyArchitecturePackageRepository
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.design_persistence import SqlAlchemyDesignPackageRepository
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.models.proposal_evidence import (
    ProposalEvidenceError,
    bind_model_artifacts,
    current_proposal_evidence,
)
from orchestwin.models.proposal_evidence_persistence import (
    EVENTS,
    GENERATIONS,
    LINKS,
    SqlAlchemyProposalEvidenceBindings,
    SqlAlchemyProposalEvidenceStore,
)
from orchestwin.persistence import create_database_runtime
from orchestwin.persistence.config import DatabaseSettings
from orchestwin.projects.persistence.models import ProjectBriefVersionRecord, ProjectRecord
from orchestwin.projects.requirements_persistence import (
    SqlAlchemyRequirementsSpecificationRepository,
)
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.twins.persistence.repositories import (
    SqlAlchemyPersonaVersionRepository,
    SqlAlchemyUserTwinVersionRepository,
)
from orchestwin.twins.personas import PersonaProfileVersion
from orchestwin.twins.user_twins import UserTwinProfileVersion
from orchestwin.workflow.gates import HumanGateType
from src.test.python.integration.postgres_isolation import isolated_postgres_settings
from src.test.python.integration.test_postgresql_workflow_progression import (
    _approve_gate,
    _persist_pending_gate,
)
from src.test.python.models.test_proposal_evidence import Command, audited_generator, stage_case

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("ORCHESTWIN_PROPOSAL_EVIDENCE_TEST_DATABASE_URL"),
        reason="explicit disposable proposal evidence database required",
    ),
]


def run(coroutine):
    if sys.platform == "win32":
        return asyncio.run(
            coroutine, loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
        )
    return asyncio.run(coroutine)


@pytest.fixture
def database():
    settings = DatabaseSettings(
        url=SecretStr(os.environ["ORCHESTWIN_PROPOSAL_EVIDENCE_TEST_DATABASE_URL"]), _env_file=None
    )
    with isolated_postgres_settings(settings) as scoped:
        yield scoped


async def seed(runtime, request, *, team=False):
    owner = request.brief_version.created_by_user_id if team else uuid4()
    project = request.brief_version.project_id if team else request.project_id
    now = datetime.now(UTC)
    async with runtime.session_factory() as session, session.begin():
        session.add(
            UserRecord(
                id=owner,
                email_normalized=f"{owner}@synthetic.example",
                password_hash="UNUSABLE_SYNTHETIC_TEST_ACCOUNT",
            )
        )
        await session.flush()
        session.add(
            ProjectRecord(
                id=project,
                owner_user_id=owner,
                display_name="Synthetic proposal persistence test",
                mode="GREENFIELD_GENERATION",
                current_brief_version=1 if team else None,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        if team:
            brief = request.brief_version
            session.add(
                ProjectBriefVersionRecord(
                    id=brief.id,
                    project_id=project,
                    version_number=1,
                    schema_version=brief.schema_version,
                    content=brief.brief.to_snapshot(),
                    content_hash=brief.content_hash,
                    created_by_user_id=owner,
                    created_at=brief.created_at,
                )
            )
    if team:
        await _persist_pending_gate(
            runtime,
            owner_id=owner,
            project_id=project,
            gate_id=uuid4(),
            gate_type=HumanGateType.PROJECT_BRIEF,
            artifact_id=request.brief_version.id,
            artifact_hash=request.brief_version.content_hash,
            occurred_at=now,
        )
        await _approve_gate(
            runtime,
            owner_id=owner,
            project_id=project,
            gate_type=HumanGateType.PROJECT_BRIEF,
            occurred_at=datetime.now(UTC),
        )
    return owner, project


def make_version(result, kind, owner, project):
    common = dict(
        id=uuid4(),
        project_id=project,
        version_number=1,
        created_by_user_id=owner,
        created_at=datetime.now(UTC),
    )
    if kind == "PERSONA":
        return PersonaProfileVersion(
            **common,
            persona_id=uuid4(),
            profile=result.proposals[0].profile,
            content_hash=result.proposals[0].profile.content_hash,
        )
    if kind == "USER_TWIN":
        return UserTwinProfileVersion(
            **common,
            twin_id=uuid4(),
            profile=result.proposals[0].profile,
            content_hash=result.proposals[0].profile.content_hash,
        )
    field = "specification" if kind == "REQUIREMENTS" else "package"
    value = getattr(result, field)
    cls = {
        "REQUIREMENTS": RequirementsSpecificationVersion,
        "DESIGN": DesignPackageVersion,
        "ARCHITECTURE": ArchitecturePackageVersion,
    }[kind]
    return cls(
        **common, based_on_version_number=None, content_hash=value.content_hash, **{field: value}
    )


async def publish(runtime, result, kind, owner, project):
    scope = current_proposal_evidence()
    async with runtime.session_factory() as session, session.begin():
        if kind == "AGENT_TEAM":
            persisted = await SqlAlchemyTeamProposalVersionRepository(
                session
            ).create_generated_owned(
                project_id=project, owner_user_id=owner, proposal=result.proposal
            )
            version = persisted.version
        else:
            version = make_version(result, kind, owner, project)
            repository = {
                "PERSONA": SqlAlchemyPersonaVersionRepository,
                "USER_TWIN": SqlAlchemyUserTwinVersionRepository,
                "REQUIREMENTS": SqlAlchemyRequirementsSpecificationRepository,
                "DESIGN": SqlAlchemyDesignPackageRepository,
                "ARCHITECTURE": SqlAlchemyArchitecturePackageRepository,
            }[kind](session, owner_user_id=owner)
            assert (await repository.append(version)).value == "APPENDED"
        await bind_model_artifacts(
            SimpleNamespace(proposal_evidence=SqlAlchemyProposalEvidenceBindings(session)),
            kind,
            (version,),
        )
    return scope.request.request_id, version


@pytest.mark.parametrize(
    "stage", ["team", "personas", "user-twins", "requirements", "design", "architecture"]
)
def test_each_generated_artifact_has_exact_durable_owner_scoped_link(database, tmp_path, stage):
    request, output, adapter, method, kind = stage_case(stage)
    generator, _ = audited_generator(tmp_path, output)
    saved = {}

    async def scenario():
        runtime = create_database_runtime(database)
        try:
            owner, project = await seed(runtime, request, team=stage == "team")
            store = SqlAlchemyProposalEvidenceStore(runtime.session_factory)
            if stage == "user-twins":
                async with runtime.session_factory() as session, session.begin():
                    persona = replace(request.persona_versions[0], created_by_user_id=owner)
                    previous = replace(
                        persona, id=uuid4(), version_number=1, based_on_version_number=None
                    )
                    assert (
                        await SqlAlchemyPersonaVersionRepository(
                            session, owner_user_id=owner
                        ).append(previous)
                    ).value == "APPENDED"
                    assert (
                        await SqlAlchemyPersonaVersionRepository(
                            session, owner_user_id=owner
                        ).append(persona)
                    ).value == "APPENDED"

            async def operation():
                result = await getattr(adapter(generator), method)(request)
                saved["id"], saved["version"] = await publish(runtime, result, kind, owner, project)
                return result

            await Command(store, operation).run(owner_user_id=owner, project_id=project)
            saved.update(owner=owner, project=project)
            assert (
                await store.get_owned(
                    owner_user_id=uuid4(), project_id=project, generation_id=saved["id"]
                )
                is None
            )
            assert await store.list_owned(owner_user_id=uuid4(), project_id=project) is None
        finally:
            await runtime.dispose()

    run(scenario())

    async def reload():
        runtime = create_database_runtime(database)
        try:
            store = SqlAlchemyProposalEvidenceStore(runtime.session_factory)
            document = await store.get_owned(
                owner_user_id=saved["owner"], project_id=saved["project"], generation_id=saved["id"]
            )
            assert document["publication_state"] == "ARTIFACTS_LINKED"
            link = document["artifact_links"][0]["artifact"]
            assert link["version_id"] == str(saved["version"].id)
            assert link["content_hash"] == saved["version"].content_hash and link["kind"] == kind
            raw = next(e for e in document["observations"] if e["kind"] == "HTTP_RESPONSE")
            assert (
                json.loads(base64.b64decode(raw["raw_body_base64"]))["id"] == "synthetic-completion"
            )
            assert len(document["observations"]) == 5
        finally:
            await runtime.dispose()

    run(reload())


@pytest.mark.parametrize(
    "failure", ["rollback_after_link", "wrong_artifact_id", "wrong_artifact_hash"]
)
def test_artifact_and_link_rollback_together_but_model_evidence_survives(
    database, tmp_path, failure
):
    request, output, adapter, _method, _ = stage_case("team")
    generator, _ = audited_generator(tmp_path, output)

    async def scenario():
        runtime = create_database_runtime(database)
        try:
            owner, project = await seed(runtime, request, team=True)
            store = SqlAlchemyProposalEvidenceStore(runtime.session_factory)

            async def operation():
                result = await adapter(generator).propose(request)
                scope = current_proposal_evidence()
                async with runtime.session_factory() as session, session.begin():
                    version = (
                        await SqlAlchemyTeamProposalVersionRepository(
                            session
                        ).create_generated_owned(
                            project_id=project, owner_user_id=owner, proposal=result.proposal
                        )
                    ).version
                    reference = {
                        "kind": "AGENT_TEAM",
                        "version_id": str(
                            uuid4() if failure == "wrong_artifact_id" else version.id
                        ),
                        "version_number": version.version_number,
                        "content_hash": "f" * 64
                        if failure == "wrong_artifact_hash"
                        else version.content_hash,
                        "relation": "GENERATED",
                    }
                    await SqlAlchemyProposalEvidenceBindings(session).bind(scope, [reference])
                    raise RuntimeError("synthetic transaction failure")

            with pytest.raises((ProposalEvidenceError, RuntimeError)):
                await Command(store, operation).run(owner_user_id=owner, project_id=project)
            async with runtime.session_factory() as session:
                assert (
                    await session.scalar(
                        sa.select(sa.func.count()).select_from(TeamProposalVersionRecord)
                    )
                    == 0
                )
                assert await session.scalar(sa.select(sa.func.count()).select_from(LINKS)) == 0
            rows = await store.list_owned(owner_user_id=owner, project_id=project)
            evidence = await store.get_owned(
                owner_user_id=owner,
                project_id=project,
                generation_id=UUID(rows[0]["generation_id"]),
            )
            assert evidence["publication_state"] == "MODEL_ACCEPTED_WITHOUT_PUBLICATION"
            assert any(e["kind"] == "HTTP_RESPONSE" for e in evidence["observations"])
        finally:
            await runtime.dispose()

    run(scenario())


def test_actual_team_service_binds_in_transaction_and_records_unchanged_generation(
    database, tmp_path
):
    request, output, adapter, _, _ = stage_case("team")
    generator, _ = audited_generator(tmp_path, output)

    async def scenario():
        runtime = create_database_runtime(database)
        try:
            owner, project = await seed(runtime, request, team=True)
            store = SqlAlchemyProposalEvidenceStore(runtime.session_factory)
            service = LocalTeamProposalApplicationService(
                unit_of_work_factory=SqlAlchemyTeamProposalUnitOfWorkFactory(
                    runtime.session_factory
                ),
                proposal_port=adapter(generator),
                proposal_evidence_store=store,
            )
            first = await service.generate(project_id=project, owner_user_id=owner)
            second = await service.generate(project_id=project, owner_user_id=owner)
            assert first.status.value == "CREATED" and second.status.value == "UNCHANGED"
            assert first.version == second.version
            async with runtime.session_factory() as session:
                assert set(await session.scalars(sa.select(LINKS.c.relation))) == {
                    "GENERATED",
                    "MATCHED_EXISTING",
                }
            for table in (GENERATIONS, EVENTS, LINKS):
                for statement in (
                    sa.update(table).values(content_hash="0" * 64),
                    sa.delete(table),
                    sa.text(f"TRUNCATE {table.name} CASCADE"),
                ):
                    with pytest.raises(sa.exc.DBAPIError):
                        async with runtime.session_factory() as session, session.begin():
                            await session.execute(statement)
        finally:
            await runtime.dispose()

    run(scenario())


def test_archive_during_inference_retains_output_without_publishing_stale_context(
    database, tmp_path
):
    request, output, adapter, _, _ = stage_case("team")
    generator, transport = audited_generator(tmp_path, output)
    original_post = transport.post_json

    async def scenario():
        runtime = create_database_runtime(database)
        try:
            owner, project = await seed(runtime, request, team=True)
            store = SqlAlchemyProposalEvidenceStore(runtime.session_factory)

            async def archive_after_inference(**kwargs):
                response = await original_post(**kwargs)
                async with runtime.session_factory() as session, session.begin():
                    await session.execute(
                        sa.update(ProjectRecord)
                        .where(ProjectRecord.id == project)
                        .values(archived_at=datetime.now(UTC))
                    )
                return response

            transport.post_json = archive_after_inference
            service = LocalTeamProposalApplicationService(
                unit_of_work_factory=SqlAlchemyTeamProposalUnitOfWorkFactory(
                    runtime.session_factory
                ),
                proposal_port=adapter(generator),
                proposal_evidence_store=store,
            )
            result = await service.generate(owner_user_id=owner, project_id=project)
            assert result.status.value == "CONTEXT_CHANGED"
            rows = await store.list_owned(owner_user_id=owner, project_id=project)
            evidence = await store.get_owned(
                owner_user_id=owner,
                project_id=project,
                generation_id=UUID(rows[0]["generation_id"]),
            )
            assert evidence["publication_state"] == "MODEL_ACCEPTED_WITHOUT_PUBLICATION"
            assert evidence["observations"][-1]["payload"]["status"] == "CONTEXT_CHANGED"
            assert len(evidence["observations"]) == 5
            assert evidence["artifact_links"] == []
        finally:
            await runtime.dispose()

    run(scenario())


def test_database_rejects_missing_identity_and_corrupt_snapshot_hash(database, tmp_path):
    from orchestwin.projects.requirements_primitives import snapshot_content_hash

    request, output, adapter, _, _ = stage_case("team")
    generator, _ = audited_generator(tmp_path, output)

    async def scenario():
        runtime = create_database_runtime(database)
        try:
            owner, project = await seed(runtime, request, team=True)
            store = SqlAlchemyProposalEvidenceStore(runtime.session_factory)
            await Command(store, lambda: adapter(generator).propose(request)).run(
                owner_user_id=owner, project_id=project
            )
            async with runtime.session_factory() as session:
                row = dict((await session.execute(sa.select(GENERATIONS))).mappings().one())
            for changed in (
                {"content_hash": "0" * 64},
                {"snapshot_json": "{}", "content_hash": snapshot_content_hash({})},
            ):
                with pytest.raises(sa.exc.DBAPIError):
                    async with runtime.session_factory() as session, session.begin():
                        await session.execute(
                            sa.insert(GENERATIONS).values(**{**row, "id": uuid4(), **changed})
                        )
        finally:
            await runtime.dispose()

    run(scenario())


@pytest.mark.parametrize("fail_snapshot_binding", [False, True])
def test_actual_twin_service_binds_complete_snapshot_atomically(
    database, tmp_path, monkeypatch, fail_snapshot_binding
):
    from orchestwin.agents.selection_rules import determine_team_constraints
    from orchestwin.models.fake_team_proposals import FakeDeterministicTeamProposalAdapter
    from orchestwin.models.team_proposals import TeamProposalRequest
    from orchestwin.twins.application import LocalUserModelingApplicationService
    from orchestwin.twins.runtime import ManagedUserModelingUnitOfWorkFactory
    from orchestwin.twins.user_twins import VersionedArtifactReference
    from src.test.python.twins import test_user_modeling_application as modeling

    context = modeling.ready_context()
    team_request = stage_case("team")[0]
    team_request = TeamProposalRequest(
        team_request.project_mode,
        context.brief_version,
        determine_team_constraints(
            project_mode=team_request.project_mode, brief=context.brief_version.brief
        ),
    )
    request, output, adapter, _, _ = stage_case("user-twins")
    original_bind = SqlAlchemyProposalEvidenceBindings.bind

    async def fail_assembled(repository, scope, references):
        if fail_snapshot_binding and references[0]["relation"] == "ASSEMBLED":
            raise ProposalEvidenceError("SYNTHETIC_SNAPSHOT_BINDING_FAILURE")
        await original_bind(repository, scope, references)

    monkeypatch.setattr(SqlAlchemyProposalEvidenceBindings, "bind", fail_assembled)

    async def scenario():
        runtime = create_database_runtime(database)
        try:
            owner, project = await seed(runtime, team_request, team=True)
            proposed = await FakeDeterministicTeamProposalAdapter().propose(team_request)
            async with runtime.session_factory() as session, session.begin():
                team = (
                    await SqlAlchemyTeamProposalVersionRepository(session).create_generated_owned(
                        project_id=project, owner_user_id=owner, proposal=proposed.proposal
                    )
                ).version
                persona = replace(request.persona_versions[0], created_by_user_id=owner)
                repo = SqlAlchemyPersonaVersionRepository(session, owner_user_id=owner)
                await repo.append(
                    replace(persona, id=uuid4(), version_number=1, based_on_version_number=None)
                )
                await repo.append(persona)
            team_ref = VersionedArtifactReference(team.id, team.version_number, team.content_hash)
            governed = replace(context, team_reference=team_ref, approved_team_reference=team_ref)
            generator, _ = audited_generator(tmp_path, output)
            store = SqlAlchemyProposalEvidenceStore(runtime.session_factory)
            service = LocalUserModelingApplicationService(
                governance=modeling.FakeGovernancePort([governed]),
                proposals=adapter(generator),
                uow_factory=ManagedUserModelingUnitOfWorkFactory(runtime.session_factory),
                proposal_evidence_store=store,
            )
            if fail_snapshot_binding:
                with pytest.raises(
                    ProposalEvidenceError, match="SYNTHETIC_SNAPSHOT_BINDING_FAILURE"
                ):
                    await service.generate_grounded_snapshot(
                        owner_user_id=owner, project_id=project
                    )
            else:
                result = await service.generate_grounded_snapshot(
                    owner_user_id=owner, project_id=project
                )
                assert result.status.value == "CREATED"
            rows = await store.list_owned(owner_user_id=owner, project_id=project)
            evidence = await store.get_owned(
                owner_user_id=owner,
                project_id=project,
                generation_id=UUID(rows[0]["generation_id"]),
            )
            assert evidence["publication_state"] == (
                "MODEL_ACCEPTED_WITHOUT_PUBLICATION"
                if fail_snapshot_binding
                else "ARTIFACTS_LINKED"
            )
            assert {link["artifact"]["kind"] for link in evidence["artifact_links"]} == (
                set() if fail_snapshot_binding else {"USER_TWIN", "USER_MODELING"}
            )
            async with runtime.session_factory() as session:
                for table in ("user_twin_profile_versions", "user_modeling_snapshot_versions"):
                    assert await session.scalar(sa.text(f"SELECT count(*) FROM {table}")) == (
                        0 if fail_snapshot_binding else 1
                    )
        finally:
            await runtime.dispose()

    run(scenario())


@pytest.mark.skipif(
    not os.environ.get("ORCHESTWIN_PROPOSAL_EVIDENCE_REAL_CONFIG"),
    reason="separately opted-in real local inference engineering probe",
)
def test_real_model_retention_probe(database):
    """Real inference and database, synthetic gate fixture: not a thesis case."""
    from pathlib import Path

    from orchestwin.models.model_proposals import ModelTeamProposalAdapter
    from orchestwin.models.proposal_generation import (
        ProposalGenerationError,
        build_proposal_generator,
    )

    output = Path(os.environ["ORCHESTWIN_PROPOSAL_EVIDENCE_REAL_OUTPUT"])
    output.mkdir(exist_ok=False)
    request = stage_case("team")[0]
    generator = build_proposal_generator(
        Path(os.environ["ORCHESTWIN_PROPOSAL_EVIDENCE_REAL_CONFIG"])
    )
    saved = {}

    async def scenario():
        runtime = create_database_runtime(database)
        try:
            owner, project = await seed(runtime, request, team=True)
            store = SqlAlchemyProposalEvidenceStore(runtime.session_factory)
            service = LocalTeamProposalApplicationService(
                unit_of_work_factory=SqlAlchemyTeamProposalUnitOfWorkFactory(
                    runtime.session_factory
                ),
                proposal_port=ModelTeamProposalAdapter(generator),
                proposal_evidence_store=store,
            )
            try:
                result = await service.generate(owner_user_id=owner, project_id=project)
                outcome = result.status.value
            except ProposalGenerationError as error:
                outcome = error.code
            rows = await store.list_owned(owner_user_id=owner, project_id=project)
            assert len(rows) == 1
            generation_id = UUID(rows[0]["generation_id"])
            evidence = await store.get_owned(
                owner_user_id=owner, project_id=project, generation_id=generation_id
            )
            (output / "evidence.json").write_text(
                json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            assert any(e["kind"] == "HTTP_RESPONSE" for e in evidence["observations"])
            assert bool(evidence["artifact_links"]) == (outcome == "CREATED")
            saved.update(
                owner=owner,
                project=project,
                generation_id=generation_id,
                evidence=evidence,
                outcome=outcome,
            )
            if outcome == "CREATED":
                (output / "proposal.json").write_text(
                    json.dumps(result.version.proposal.to_snapshot(), indent=2), encoding="utf-8"
                )
        finally:
            await runtime.dispose()

    run(scenario())

    async def reload():
        runtime = create_database_runtime(database)
        try:
            evidence = await SqlAlchemyProposalEvidenceStore(runtime.session_factory).get_owned(
                owner_user_id=saved["owner"],
                project_id=saved["project"],
                generation_id=saved["generation_id"],
            )
            assert evidence == saved["evidence"]
        finally:
            await runtime.dispose()

    run(reload())
    (output / "report.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scope": "REAL_MODEL_AND_POSTGRES_ENGINEERING_PROBE_SYNTHETIC_GOVERNANCE",
                "formal_case": False,
                "model_outcome": saved["outcome"],
                "generation_id": str(saved["generation_id"]),
                "identity": generator.configuration.identity.to_snapshot(),
                "publication_state": saved["evidence"]["publication_state"],
                "retention_survives_runtime_restart": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
