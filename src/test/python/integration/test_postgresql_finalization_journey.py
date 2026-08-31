"""PostgreSQL integration coverage for checkpointed Gate 8 finalization."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from orchestwin.artifacts.export_archive import assemble_final_export_archive
from orchestwin.artifacts.export_manifest import (
    ExportArtifactCategory,
    FinalExportEntry,
    FinalExportOmission,
    create_final_export_manifest,
)
from orchestwin.artifacts.export_persistence import (
    SqlAlchemyExportBundleRepository,
    StoredExportBundle,
)
from orchestwin.identity.application import AuthenticationStatus, LocalIdentityApplicationService
from orchestwin.identity.passwords import Argon2PasswordService
from orchestwin.identity.persistence import SqlAlchemyIdentityUnitOfWorkFactory
from orchestwin.identity.tokens import AccessTokenSettings, JwtAccessTokenService
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.persistence.migrate import create_alembic_config
from orchestwin.projects.application import LocalProjectApplicationService
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.persistence import SqlAlchemyProjectUnitOfWorkFactory
from orchestwin.projects.requirements_primitives import canonical_json
from orchestwin.workflow.checkpoints import create_workflow_checkpoint
from orchestwin.workflow.final_approval import (
    decide_final_output_gate,
    enter_final_approval_stage,
    resume_after_final_output_approval,
    submit_final_review_for_approval,
)
from orchestwin.workflow.final_review import (
    AcceptedFinalLimitation,
    FinalReviewCheck,
    FinalReviewCheckKind,
    FinalReviewCheckStatus,
    HumanValidationStatus,
    create_final_review_assessment,
)
from orchestwin.workflow.final_review_persistence import SqlAlchemyFinalReviewRepository
from orchestwin.workflow.gates import HumanGateAction
from orchestwin.workflow.routing import start_workflow_run
from orchestwin.workflow.run_persistence import (
    SqlAlchemyWorkflowRunRepository,
    WorkflowRunStoreStatus,
)
from orchestwin.workflow.runs import WorkflowStage, create_workflow_run

pytestmark = pytest.mark.integration

RUN_ID = UUID("95000000-0000-4000-8000-000000000101")
CHECKPOINT_ID = UUID("95000000-0000-4000-8000-000000000102")
REVIEW_ID = UUID("95000000-0000-4000-8000-000000000103")
GATE_ID = UUID("95000000-0000-4000-8000-000000000104")
SUBMIT_EVENT_ID = UUID("95000000-0000-4000-8000-000000000105")
APPROVE_EVENT_ID = UUID("95000000-0000-4000-8000-000000000106")
MANIFEST_ID = UUID("95000000-0000-4000-8000-000000000107")
EXPORT_ID = UUID("95000000-0000-4000-8000-000000000108")
BASE_TIME = datetime(2026, 8, 31, 5, 30, tzinfo=UTC)
LIMITATION_ID = "LIMIT-POSTGRESQL-FIXTURE"


async def _truncate_application_data(runtime) -> None:
    async with runtime.engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users CASCADE"))


async def _mutation_is_rejected(runtime, statement: str, identifier: UUID) -> bool:
    try:
        async with runtime.session_factory.begin() as session:
            await session.execute(text(statement), {"identifier": identifier})
    except DBAPIError:
        return True
    return False


async def _create_owner_foreign_and_project(runtime):
    identity = LocalIdentityApplicationService(
        unit_of_work_factory=SqlAlchemyIdentityUnitOfWorkFactory(runtime.session_factory),
        password_service=Argon2PasswordService(),
        access_token_service=JwtAccessTokenService(
            AccessTokenSettings(
                jwt_secret=SecretStr(
                    "finalization-integration-jwt-secret-with-more-than-32-characters"
                ),
                access_token_leeway_seconds=0,
                _env_file=None,
            )
        ),
    )
    projects = LocalProjectApplicationService(
        unit_of_work_factory=SqlAlchemyProjectUnitOfWorkFactory(runtime.session_factory)
    )
    owner_result = await identity.register(
        email="sprint-ten-final-owner@example.com",
        password="correct horse battery staple",
    )
    foreign_result = await identity.register(
        email="sprint-ten-final-foreign@example.com",
        password="another correct battery staple",
    )
    assert owner_result.status is AuthenticationStatus.AUTHENTICATED
    assert foreign_result.status is AuthenticationStatus.AUTHENTICATED
    assert owner_result.authenticated is not None
    assert foreign_result.authenticated is not None
    owner = owner_result.authenticated.user
    foreign = foreign_result.authenticated.user
    project = await projects.create(
        owner_user_id=owner.id,
        display_name="Sprint 10 checkpointed finalization fixture",
        mode=ProjectMode.GREENFIELD_GENERATION,
    )
    return owner, foreign, project


def _checks() -> tuple[FinalReviewCheck, ...]:
    return tuple(
        sorted(
            (
                FinalReviewCheck(
                    check_id=f"PG-FINAL-{index:02d}",
                    kind=kind,
                    status=FinalReviewCheckStatus.SATISFIED,
                    summary=f"PostgreSQL fixture verified {kind.value}.",
                    evidence_refs=(f"postgresql:{kind.value.lower()}",),
                    blocking=True,
                )
                for index, kind in enumerate(FinalReviewCheckKind, start=1)
            ),
            key=lambda item: item.sort_key,
        )
    )


def _omissions() -> tuple[FinalExportOmission, ...]:
    return tuple(
        FinalExportOmission(
            category=category,
            reason="The focused PostgreSQL fixture records this category as omitted.",
            accepted_limitation_id=LIMITATION_ID,
        )
        for category in ExportArtifactCategory
        if category is not ExportArtifactCategory.FINAL_REVIEW
    )


async def _run_finalization_scenario() -> None:
    settings = load_database_settings(env_file=None)
    runtime = create_database_runtime(settings)
    try:
        await _truncate_application_data(runtime)
        owner, foreign, project = await _create_owner_foreign_and_project(runtime)
        draft = create_workflow_run(
            project_id=project.id,
            owner_user_id=owner.id,
            project_mode=ProjectMode.GREENFIELD_GENERATION,
            run_id=RUN_ID,
            created_at=BASE_TIME,
        )
        running = start_workflow_run(
            draft,
            occurred_at=BASE_TIME + timedelta(seconds=1),
        ).run
        final_review_run = replace(
            running,
            current_stage=WorkflowStage.FINAL_REVIEW,
            updated_at=BASE_TIME + timedelta(seconds=2),
        )
        checkpointed = create_workflow_checkpoint(
            final_review_run,
            created_at=BASE_TIME + timedelta(seconds=2),
            checkpoint_id=CHECKPOINT_ID,
        )
        review = create_final_review_assessment(
            checkpointed.run,
            checks=_checks(),
            accepted_limitations=(
                AcceptedFinalLimitation(
                    LIMITATION_ID,
                    "This focused fixture omits non-finalization package categories.",
                    "The omission is explicit and does not imply empirical validation.",
                ),
            ),
            human_validation_status=HumanValidationStatus.PLANNED,
            review_id=REVIEW_ID,
            created_at=BASE_TIME + timedelta(seconds=3),
        )
        submitted = submit_final_review_for_approval(
            review,
            gate_id=GATE_ID,
            event_id=SUBMIT_EVENT_ID,
            occurred_at=BASE_TIME + timedelta(seconds=4),
        )
        waiting = enter_final_approval_stage(
            checkpointed.run,
            gate=submitted.gate,
            occurred_at=BASE_TIME + timedelta(seconds=4),
        )
        approved = decide_final_output_gate(
            submitted.gate,
            current_review=review,
            action=HumanGateAction.APPROVE,
            actor_user_id=owner.id,
            occurred_at=BASE_TIME + timedelta(seconds=5),
            event_id=APPROVE_EVENT_ID,
        )
        resume_after_final_output_approval(
            waiting,
            gate=approved.gate,
            occurred_at=BASE_TIME + timedelta(seconds=6),
        )

        review_content = canonical_json(review.to_snapshot()).encode("utf-8")
        entry = FinalExportEntry(
            path="reports/final-review.json",
            category=ExportArtifactCategory.FINAL_REVIEW,
            artifact_id=review.id,
            artifact_version=review.version_number,
            content_hash=hashlib.sha256(review_content).hexdigest(),
            media_type="application/json",
            size_bytes=len(review_content),
            required=True,
        )
        manifest = create_final_export_manifest(
            review,
            approved_gate=approved.gate,
            approval_event_id=APPROVE_EVENT_ID,
            entries=(entry,),
            omissions=_omissions(),
            manifest_id=MANIFEST_ID,
            created_at=BASE_TIME + timedelta(seconds=7),
        )
        archive = assemble_final_export_archive(
            manifest,
            content_by_path={entry.path: review_content},
            archive_id=EXPORT_ID,
            created_at=BASE_TIME + timedelta(seconds=8),
        )
        stored_export = StoredExportBundle.from_archive(
            archive,
            storage_ref=f"sha256/{archive.archive_hash[:2]}/{archive.archive_hash}.zip",
        )

        async with runtime.session_factory.begin() as session:
            runs = SqlAlchemyWorkflowRunRepository(session, owner_user_id=owner.id)
            assert (await runs.create(draft)).status is WorkflowRunStoreStatus.CREATED
            assert (
                await runs.save_checkpoint(previous_run=draft, creation=checkpointed)
            ).status is WorkflowRunStoreStatus.UPDATED
            await SqlAlchemyFinalReviewRepository(session).append(review)
            await SqlAlchemyExportBundleRepository(session).append(stored_export)

        async with runtime.session_factory() as session:
            owner_review = await SqlAlchemyFinalReviewRepository(session).get_owned(
                review_id=REVIEW_ID,
                owner_user_id=owner.id,
            )
            owner_export = await SqlAlchemyExportBundleRepository(session).get_owned(
                export_id=EXPORT_ID,
                owner_user_id=owner.id,
            )
            foreign_review = await SqlAlchemyFinalReviewRepository(session).get_owned(
                review_id=REVIEW_ID,
                owner_user_id=foreign.id,
            )
            foreign_export = await SqlAlchemyExportBundleRepository(session).get_owned(
                export_id=EXPORT_ID,
                owner_user_id=foreign.id,
            )

        assert owner_review == review
        assert owner_export == stored_export
        assert foreign_review is None
        assert foreign_export is None
        assert await _mutation_is_rejected(
            runtime,
            "UPDATE final_reviews SET ready_for_gate8 = false WHERE id = :identifier",
            REVIEW_ID,
        )
        assert await _mutation_is_rejected(
            runtime,
            "UPDATE export_bundles SET archive_size_bytes = 1 WHERE id = :identifier",
            EXPORT_ID,
        )

        async with runtime.engine.connect() as connection:
            database_revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        scripts = ScriptDirectory.from_config(
            create_alembic_config(settings.url.get_secret_value())
        )
        assert scripts.get_current_head() == "0028_export_bundles"
        assert database_revision == "0028_export_bundles"
    finally:
        await _truncate_application_data(runtime)
        await runtime.dispose()


def test_postgresql_checkpointed_final_review_gate8_and_export() -> None:
    """Persist the final checkpoint, review, and deterministic export end to end."""
    asyncio.run(
        _run_finalization_scenario(),
        loop_factory=asyncio.SelectorEventLoop,
    )
