from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from orchestwin.agents.owner_inputs import OwnerTeamInputService
from orchestwin.agents.persistence.models import TeamProposalVersionRecord
from orchestwin.agents.persistence.repositories import (
    SqlAlchemyTeamProposalVersionRepository,
    SqlAlchemyTeamSelectionContextRepository,
)
from orchestwin.agents.persistence.unit_of_work import SqlAlchemyTeamProposalUnitOfWorkFactory
from orchestwin.agents.selection_rules import determine_team_constraints
from orchestwin.artifacts.why_runtime import SqlAlchemyWhyQueryService
from orchestwin.artifacts.workflow_inputs_persistence import (
    DECISIONS,
    SqlAlchemyWorkflowInputsRepository,
)
from orchestwin.artifacts.workflow_inputs_runtime import (
    SqlAlchemyWorkflowInputsService,
    latest_gate,
    reference,
)
from orchestwin.knowledge.archive import read_verified_folder
from orchestwin.knowledge.folder import build_knowledge_folder, folder_archive
from orchestwin.knowledge.project_import import plan_project_import
from orchestwin.knowledge.project_import_service import ProjectImportError, ProjectImportService
from orchestwin.knowledge.sources import KnowledgeSources
from orchestwin.models.fake_requirements import FakeDeterministicRequirementsAdapter
from orchestwin.persistence import create_database_runtime
from orchestwin.persistence.migrate import downgrade_database, upgrade_database
from orchestwin.projects.domain import ProjectMode, create_project
from orchestwin.projects.owner_requirements import OwnerRequirementsService
from orchestwin.projects.persistence.briefs import SqlAlchemyProjectBriefRepository
from orchestwin.projects.persistence.repositories import SqlAlchemyProjectRepository
from orchestwin.projects.requirements_application import RequirementsGenerationStatus
from orchestwin.projects.requirements_persistence import (
    SqlAlchemyRequirementsSpecificationRepository,
)
from orchestwin.projects.requirements_runtime import (
    ManagedRequirementsUnitOfWorkFactory,
    SqlAlchemyRequirementsGovernanceAdapter,
)
from orchestwin.twins.owner_inputs import OwnerTwinInput, OwnerUserModelingService
from orchestwin.twins.persistence.repositories import (
    SqlAlchemyPersonaVersionRepository,
    SqlAlchemyUserModelingSnapshotRepository,
)
from orchestwin.twins.runtime import (
    ManagedUserModelingUnitOfWorkFactory,
    SqlAlchemyUserModelingGovernanceAdapter,
)
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGateAction,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)
from orchestwin.workflow.persistence.repositories import SqlAlchemyHumanGateRepository
from orchestwin.workflow_inputs import WorkflowInputError
from src.test.python.artifacts.test_provided_prototypes36 import input_payload
from src.test.python.integration.postgres_isolation import (
    assert_reversible_migration,
    isolated_postgres_settings,
)
from src.test.python.integration.test_postgresql_project_import import archive_content, seed_users
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.knowledge.knowledge_fixtures import real_sources
from src.test.python.twins.test_user_twins import complete_twin_observations

__all__ = ["database"]
pytestmark = pytest.mark.integration
MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0070_workflow_inputs"
)
NOW = datetime(2026, 10, 3, 16, tzinfo=UTC)


def test_owner_definition_rechecks_context_in_its_locked_postgres_session(database):
    with isolated_postgres_settings(database, revision=MIGRATION.revision) as scoped:

        async def scenario():
            db = create_database_runtime(scoped)
            try:
                owner, project = uuid4(), uuid4()
                await seed_users(db, owner)
                async with db.session_factory() as session, session.begin():
                    await SqlAlchemyProjectRepository(session).add(
                        create_project(
                            owner_user_id=owner,
                            display_name="Synthetic supplied definition context",
                            mode=ProjectMode.GREENFIELD_GENERATION,
                            project_id=project,
                        )
                    )
                    created = await SqlAlchemyProjectBriefRepository(session).create_owned_version(
                        project_id=project,
                        owner_user_id=owner,
                        created_by_user_id=owner,
                        brief=real_sources().brief.brief,
                    )
                    brief = created.version
                    plan = plan_project_import(
                        read_verified_folder(archive_content()),
                        project_id=project,
                        brief_version_id=brief.id,
                        owner_user_id=owner,
                        created_at=NOW,
                    )
                    personas = SqlAlchemyPersonaVersionRepository(session, owner_user_id=owner)
                    for persona in plan.personas:
                        await personas.append(persona)

                async def approve(kind, version):
                    async with db.session_factory() as session, session.begin():
                        repository = SqlAlchemyHumanGateRepository(session)
                        draft = create_human_gate(
                            project_id=project,
                            owner_user_id=owner,
                            gate_type=kind,
                            artifact=GateArtifactReference(
                                project, kind, version.id, 1, version.content_hash
                            ),
                        )
                        submitted = transition_human_gate(
                            draft, action=HumanGateAction.SUBMIT, actor_user_id=owner
                        )
                        await repository.add_with_event(gate=submitted.gate, event=submitted.event)
                        approved = transition_human_gate(
                            submitted.gate, action=HumanGateAction.APPROVE, actor_user_id=owner
                        )
                        await repository.save_transition(
                            previous_gate=submitted.gate,
                            updated_gate=approved.gate,
                            event=approved.event,
                        )

                await approve(HumanGateType.PROJECT_BRIEF, brief)
                async with db.session_factory() as session:
                    context = await SqlAlchemyTeamSelectionContextRepository(
                        session
                    ).get_current_owned(project_id=project, owner_user_id=owner)
                constraints = determine_team_constraints(
                    project_mode=context.project_mode, brief=context.brief_version.brief
                )
                team = await OwnerTeamInputService(
                    unit_of_work_factory=SqlAlchemyTeamProposalUnitOfWorkFactory(db.session_factory)
                ).create(
                    project_id=project,
                    owner_user_id=owner,
                    selected_agent_ids=constraints.mandatory_agent_ids,
                )
                assert team.version.revision_kind.value == "OWNER_PROVIDED"
                await approve(HumanGateType.AGENT_TEAM, team.version)
                twins = await OwnerUserModelingService(
                    governance_port=SqlAlchemyUserModelingGovernanceAdapter(db.session_factory),
                    uow_factory=ManagedUserModelingUnitOfWorkFactory(db.session_factory),
                ).create(
                    owner_user_id=owner,
                    project_id=project,
                    profiles=tuple(
                        OwnerTwinInput(
                            persona.persona_id, persona.profile.name, complete_twin_observations()
                        )
                        for persona in plan.personas
                    ),
                )
                assert twins.snapshot_version is not None
                await approve(HumanGateType.USER_MODELING, twins.snapshot_version)
                governance = SqlAlchemyRequirementsGovernanceAdapter(db.session_factory)
                context = await governance.load_current(owner_user_id=owner, project_id=project)
                proposal = await FakeDeterministicRequirementsAdapter().propose(
                    context.to_proposal_request()
                )
                service = OwnerRequirementsService(
                    governance_port=governance,
                    uow_factory=ManagedRequirementsUnitOfWorkFactory(db.session_factory),
                )
                saved = await asyncio.wait_for(
                    service.create(
                        owner_user_id=owner,
                        project_id=project,
                        specification=proposal.specification,
                    ),
                    timeout=10,
                )
                assert saved.status is RequirementsGenerationStatus.CREATED
                assert saved.version.specification.schema_version == 2
                async with db.session_factory() as session:
                    reread = await SqlAlchemyRequirementsSpecificationRepository(
                        session, owner_user_id=owner
                    ).current(project_id=project)
                    assert reread == saved.version
                    assert (
                        await latest_gate(
                            session,
                            owner_user_id=owner,
                            project_id=project,
                            gate_type=HumanGateType.REQUIREMENTS,
                        )
                        is None
                    )
                await approve(HumanGateType.REQUIREMENTS, saved.version)
            finally:
                await db.dispose()

        run(scenario())


async def seed_approved_definition(db, owner):
    await seed_users(db, owner)
    result = await ProjectImportService(session_factory=db.session_factory).import_archive(
        owner_user_id=owner, content=archive_content()
    )
    plan, project = result.plan, result.project.id
    values = (
        (HumanGateType.PROJECT_BRIEF, plan.brief_version_id, plan.brief.content_hash),
        (HumanGateType.AGENT_TEAM, plan.team.id, plan.team.content_hash),
        (HumanGateType.USER_MODELING, plan.modeling.id, plan.modeling.content_hash),
        (HumanGateType.REQUIREMENTS, plan.requirements.id, plan.requirements.content_hash),
    )
    async with db.session_factory() as session, session.begin():
        repository = SqlAlchemyHumanGateRepository(session)
        for kind, identity, digest in values:
            gate = create_human_gate(
                project_id=project,
                owner_user_id=owner,
                gate_type=kind,
                artifact=GateArtifactReference(project, kind, identity, 1, digest),
                created_at=NOW,
            )
            submitted = transition_human_gate(
                gate, action=HumanGateAction.SUBMIT, actor_user_id=owner, occurred_at=NOW
            )
            await repository.add_with_event(gate=submitted.gate, event=submitted.event)
            approved = transition_human_gate(
                submitted.gate, action=HumanGateAction.APPROVE, actor_user_id=owner, occurred_at=NOW
            )
            await repository.save_transition(
                previous_gate=submitted.gate, updated_gate=approved.gate, event=approved.event
            )
    return result


def test_provided_prototype_real_gate_dossier_reread_and_rollback(database, monkeypatch):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, stranger = uuid4(), uuid4()
            seeded = await seed_approved_definition(db, owner)
            await seed_users(db, stranger)
            project = seeded.project.id
            service = SqlAlchemyWorkflowInputsService(db.session_factory, clock=lambda: NOW)
            payload = input_payload() | {
                "declared_origin": "Synthetic authoring fixture",
                "expected_definition_reference": reference(seeded.plan.requirements),
                "expected_version_number": 0,
            }
            saved = await service.save_prototype(
                owner_user_id=owner, project_id=project, request=payload
            )
            assert (await service.state(owner_user_id=owner, project_id=project))[
                "approved"
            ] is False
            with pytest.raises(WorkflowInputError, match="PROVIDED_PROTOTYPE_VERSION_CONFLICT"):
                await service.save_prototype(
                    owner_user_id=owner, project_id=project, request=payload
                )
            with pytest.raises(WorkflowInputError, match="PROJECT_NOT_FOUND"):
                await service.save_prototype(
                    owner_user_id=stranger, project_id=project, request=payload
                )
            submitted = await service.gate_action(
                owner_user_id=owner, project_id=project, action="SUBMIT"
            )
            assert submitted["status"] == "PENDING_APPROVAL"
            approved = await service.gate_action(
                owner_user_id=owner, project_id=project, action="APPROVE"
            )
            assert (
                approved["artifact"]["artifact_id"] == saved["id"]
                and approved["artifact"]["content_hash"] == saved["content_hash"]
            )
            state = await service.state(owner_user_id=owner, project_id=project)
            assert state["approved"] and state["source"] == "PROVIDED_PROTOTYPE"
            await service.declare(
                owner_user_id=owner,
                project_id=project,
                request={
                    "target": "EVALUATION",
                    "action": "DECLARE_MISSING",
                    "reason": "Synthetic software fixture; supplied prototype review unavailable in 36.",
                },
            )
            records = await service.records(owner_user_id=owner, project_id=project)
            scope = {"project_id": project, "owner_user_id": owner}
            async with db.session_factory() as session:
                values = {
                    "brief": await SqlAlchemyProjectBriefRepository(session).get_current_owned(
                        **scope
                    ),
                    "team": await SqlAlchemyTeamProposalVersionRepository(
                        session
                    ).get_current_owned(**scope),
                    "modeling": await SqlAlchemyUserModelingSnapshotRepository(
                        session, owner_user_id=owner
                    ).current(project_id=project),
                    "requirements": await SqlAlchemyRequirementsSpecificationRepository(
                        session, owner_user_id=owner
                    ).current(project_id=project),
                }
                for name, kind in (
                    ("brief", HumanGateType.PROJECT_BRIEF),
                    ("team", HumanGateType.AGENT_TEAM),
                    ("modeling", HumanGateType.USER_MODELING),
                    ("requirements", HumanGateType.REQUIREMENTS),
                ):
                    values[f"{name}_gate"] = await latest_gate(session, **scope, gate_type=kind)
            sources = KnowledgeSources(
                project_id=project,
                project_name="Synthetic supplied prototype fixture; no participants",
                workflow_inputs=records,
                provided_design=state,
                **values,
            )
            folder = build_knowledge_folder(sources, version_number=1, created_at=NOW)
            assert folder.manifest["progress"]["complete"] is False
            assert (
                folder.manifest["workflow_inputs"]["approved_prototype"]["content_hash"]
                == saved["content_hash"]
            )
            content = folder_archive(folder).content
            importer = ProjectImportService(session_factory=db.session_factory)
            imported = await importer.import_archive(owner_user_id=owner, content=content)
            actual = await service.records(owner_user_id=owner, project_id=imported.project.id)
            assert actual == imported.plan.workflow_inputs
            assert (
                actual["prototypes"][0]["original_reference"]["content_hash"]
                == saved["content_hash"]
            )
            assert (
                actual["decisions"][0]["base_context"]["DESIGN"]["content_hash"]
                == actual["prototypes"][0]["content_hash"]
            )
            why = await SqlAlchemyWhyQueryService(db.session_factory).current(
                owner_user_id=owner, project_id=imported.project.id
            )
            assert any(node["kind"] == "PROVIDED_PROTOTYPE" for node in why["nodes"])
            assert not (await service.state(owner_user_id=owner, project_id=imported.project.id))[
                "approved"
            ]
            async with db.session_factory() as session:
                before = await session.scalar(sa.text("SELECT count(*) FROM projects"))
            original = SqlAlchemyWorkflowInputsRepository.import_records

            async def fail_reread(self, **kwargs):
                await original(self, **kwargs)
                raise ValueError("Synthetic reread mismatch")

            monkeypatch.setattr(SqlAlchemyWorkflowInputsRepository, "import_records", fail_reread)
            with pytest.raises(ProjectImportError, match="PROJECT_IMPORT_REJECTED"):
                await importer.import_archive(owner_user_id=owner, content=content)
            async with db.session_factory() as session:
                assert await session.scalar(sa.text("SELECT count(*) FROM projects")) == before
        finally:
            await db.dispose()

    run(scenario())


def test_isolated_workflow_inputs_migration_is_reversible(database):
    assert_reversible_migration(database, MIGRATION)


def test_migration_preserves_both_historical_team_kinds_rows_and_hashes(database):
    with isolated_postgres_settings(database, revision=MIGRATION.down_revision) as scoped:

        async def scenario():
            db = create_database_runtime(scoped)
            try:
                owner = uuid4()
                await seed_users(db, owner)
                imported = await ProjectImportService(
                    session_factory=db.session_factory
                ).import_archive(owner_user_id=owner, content=archive_content())
                table = TeamProposalVersionRecord.__table__
                async with db.session_factory() as session, session.begin():
                    columns = [column.name for column in table.columns]
                    expressions = [
                        sa.literal(uuid4())
                        if name == "id"
                        else sa.literal(2)
                        if name == "version_number"
                        else sa.literal(1)
                        if name == "based_on_version_number"
                        else sa.literal("OWNER_EDITED")
                        if name == "revision_kind"
                        else table.c[name]
                        for name in columns
                    ]
                    await session.execute(
                        sa.insert(table).from_select(
                            columns,
                            sa.select(*expressions).where(
                                table.c.project_id == imported.project.id
                            ),
                        )
                    )

                async def snapshots():
                    async with db.session_factory() as session:
                        return {
                            name: (
                                await session.execute(
                                    sa.text(
                                        f"SELECT row_to_json(t)::text FROM {name} t WHERE project_id = :project ORDER BY id"
                                    ),
                                    {"project": imported.project.id},
                                )
                            )
                            .scalars()
                            .all()
                            for name in (
                                "team_proposals",
                                "project_brief_versions",
                                "user_modeling_snapshot_versions",
                                "requirements_specification_versions",
                                "design_package_versions",
                            )
                        }

                before = await snapshots()
                async with db.session_factory() as session:
                    assert set(
                        (
                            await session.scalars(
                                sa.select(table.c.revision_kind).where(
                                    table.c.project_id == imported.project.id
                                )
                            )
                        ).all()
                    ) == {"PROPOSER_GENERATED", "OWNER_EDITED"}
                await asyncio.to_thread(upgrade_database, scoped, revision=MIGRATION.revision)
                assert await snapshots() == before
                async with db.session_factory() as session:
                    assert (
                        await session.scalar(
                            sa.text(
                                "SELECT count(*) FROM pg_constraint WHERE conrelid = 'team_proposals'::regclass AND contype = 'c' AND convalidated AND pg_get_constraintdef(oid) LIKE '%OWNER_PROVIDED%'"
                            )
                        )
                        == 2
                    )
                await asyncio.to_thread(
                    downgrade_database, scoped, revision=MIGRATION.down_revision
                )
                assert await snapshots() == before
            finally:
                await db.dispose()

        run(scenario())


def test_declared_gap_is_owner_scoped_append_only_and_reread(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, stranger = uuid4(), uuid4()
            await seed_users(db, owner, stranger)
            imported = await ProjectImportService(
                session_factory=db.session_factory
            ).import_archive(owner_user_id=owner, content=archive_content())
            service = SqlAlchemyWorkflowInputsService(db.session_factory, clock=lambda: NOW)
            request = {
                "target": "EVIDENCE",
                "action": "DECLARE_MISSING",
                "reason": "Synthetic fixture; no participants.\r\nMissing evidence.",
            }
            saved = await service.declare(
                owner_user_id=owner, project_id=imported.project.id, request=request
            )
            assert saved["sequence"] == 1 and "\r" not in saved["reason"]
            assert (
                await service.records(owner_user_id=stranger, project_id=imported.project.id)
                is None
            )
            with pytest.raises(WorkflowInputError, match="PROJECT_NOT_FOUND"):
                await service.declare(
                    owner_user_id=stranger, project_id=imported.project.id, request=request
                )
            resolved = await service.declare(
                owner_user_id=owner,
                project_id=imported.project.id,
                request=request
                | {
                    "action": "RESOLVE_MISSING",
                    "reason": "Synthetic resolution; no new evidence implied.",
                },
            )
            records = await service.records(owner_user_id=owner, project_id=imported.project.id)
            assert records["decisions"] == [saved, resolved]
            async with db.session_factory() as session, session.begin():
                with pytest.raises(DBAPIError, match="append-only"):
                    async with session.begin_nested():
                        await session.execute(
                            sa.update(DECISIONS)
                            .where(DECISIONS.c.id == saved["id"])
                            .values(content_hash="a" * 64)
                        )
                repository = SqlAlchemyWorkflowInputsRepository(session, owner_user_id=owner)
                assert await repository.records(imported.project.id) == records
        finally:
            await db.dispose()

    run(scenario())


def test_owner_provided_team_constraint_accepts_no_base_and_preserves_on_downgrade(database):
    with isolated_postgres_settings(database, revision=MIGRATION.revision) as scoped:

        async def scenario():
            db = create_database_runtime(scoped)
            try:
                owner = uuid4()
                await seed_users(db, owner)
                imported = await ProjectImportService(
                    session_factory=db.session_factory
                ).import_archive(owner_user_id=owner, content=archive_content())
                table = TeamProposalVersionRecord.__table__
                identity = uuid4()
                columns = [column.name for column in table.columns]

                def statement(base):
                    values = {
                        "id": sa.literal(identity),
                        "version_number": sa.literal(2),
                        "based_on_version_number": sa.literal(base, type_=sa.Integer()),
                        "revision_kind": sa.literal("OWNER_PROVIDED"),
                    }
                    return sa.insert(table).from_select(
                        columns,
                        sa.select(*(values.get(name, table.c[name]) for name in columns)).where(
                            table.c.id == imported.plan.team.id
                        ),
                    )

                async with db.session_factory() as session, session.begin():
                    with pytest.raises(DBAPIError):
                        async with session.begin_nested():
                            await session.execute(statement(1))
                    await session.execute(statement(None))
                    saved_hash = await session.scalar(
                        sa.select(table.c.content_hash).where(table.c.id == identity)
                    )
                    assert saved_hash == imported.plan.team.content_hash
                with pytest.raises(RuntimeError, match="must be preserved before downgrade"):
                    await asyncio.to_thread(
                        downgrade_database, scoped, revision=MIGRATION.down_revision
                    )
                async with db.session_factory() as session:
                    assert (
                        await session.scalar(
                            sa.select(table.c.content_hash).where(table.c.id == identity)
                        )
                        == saved_hash
                    )
            finally:
                await db.dispose()

        run(scenario())
