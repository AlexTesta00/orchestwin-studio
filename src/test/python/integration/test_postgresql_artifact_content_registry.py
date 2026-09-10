"""PostgreSQL integration tests for authorized evaluator artifact metadata."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from orchestwin.evaluation.artifact_content_registry import (
    ArtifactContentRegistryStoreStatus,
    AuthorizedEvaluationArtifactRecord,
)
from orchestwin.evaluation.artifact_content_registry_persistence import (
    SqlAlchemyAuthorizedEvaluationArtifactRegistry,
)
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    EvaluationArtifactReference,
)
from orchestwin.identity.application import (
    AuthenticationStatus,
    LocalIdentityApplicationService,
)
from orchestwin.identity.passwords import Argon2PasswordService
from orchestwin.identity.persistence import (
    SqlAlchemyIdentityUnitOfWorkFactory,
)
from orchestwin.identity.tokens import (
    AccessTokenSettings,
    JwtAccessTokenService,
)
from orchestwin.persistence import (
    create_database_runtime,
    load_database_settings,
)
from orchestwin.projects.application import (
    LocalProjectApplicationService,
)
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.persistence import (
    SqlAlchemyProjectUnitOfWorkFactory,
)
from orchestwin.workflow.run_persistence import (
    SqlAlchemyWorkflowRunRepository,
    WorkflowRunStoreStatus,
)
from orchestwin.workflow.runs import create_workflow_run

pytestmark = pytest.mark.integration

WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000087001")
OTHER_WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000087002")
OTHER_PROJECT_ID = UUID("00000000-0000-4000-8000-000000087003")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000087004")

NOW = datetime(2026, 9, 10, 14, 0, tzinfo=UTC)


async def _truncate(runtime) -> None:
    async with runtime.engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users CASCADE"))


async def _create_scope(runtime):
    identity = LocalIdentityApplicationService(
        unit_of_work_factory=(SqlAlchemyIdentityUnitOfWorkFactory(runtime.session_factory)),
        password_service=Argon2PasswordService(),
        access_token_service=JwtAccessTokenService(
            AccessTokenSettings(
                jwt_secret=SecretStr(
                    "artifact-registry-integration-secret-with-more-than-32-characters"
                ),
                access_token_leeway_seconds=0,
                _env_file=None,
            )
        ),
    )

    projects = LocalProjectApplicationService(
        unit_of_work_factory=(SqlAlchemyProjectUnitOfWorkFactory(runtime.session_factory))
    )

    owner_result = await identity.register(
        email="artifact-registry-owner@example.com",
        password="correct horse battery staple",
    )

    foreign_result = await identity.register(
        email="artifact-registry-foreign@example.com",
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
        display_name="Authorized artifact registry fixture",
        mode=ProjectMode.GREENFIELD_GENERATION,
    )

    workflow = create_workflow_run(
        project_id=project.id,
        owner_user_id=owner.id,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        run_id=WORKFLOW_RUN_ID,
        created_at=NOW,
    )

    async with runtime.session_factory.begin() as session:
        repository = SqlAlchemyWorkflowRunRepository(
            session,
            owner_user_id=owner.id,
        )

        stored = await repository.create(workflow)

        assert stored.status is WorkflowRunStoreStatus.CREATED

    return owner, foreign, project


def _reference(
    content: bytes,
) -> EvaluationArtifactReference:
    digest = hashlib.sha256(content).hexdigest()

    return EvaluationArtifactReference(
        artifact_id=ARTIFACT_ID,
        version_number=1,
        kind=EvaluationArtifactKind.DOM_SNAPSHOT,
        media_type="text/html",
        sha256_digest=digest,
        size_bytes=len(content),
        storage_key=f"sha256/{digest[:2]}/{digest}",
        location="browser:postgresql/final-dom",
    )


def test_postgresql_registry_is_owner_project_workflow_scoped() -> None:
    async def scenario() -> None:
        settings = load_database_settings(env_file=None)
        runtime = create_database_runtime(settings)

        try:
            await _truncate(runtime)

            owner, foreign, project = await _create_scope(runtime)

            reference = _reference(b"<!doctype html><button>Confirm</button>")

            record = AuthorizedEvaluationArtifactRecord(
                owner_user_id=owner.id,
                project_id=project.id,
                workflow_run_id=WORKFLOW_RUN_ID,
                reference=reference,
            )

            async with runtime.session_factory.begin() as session:
                registry = SqlAlchemyAuthorizedEvaluationArtifactRegistry(session)

                created = await registry.append(record)
                repeated = await registry.append(record)

                assert created is ArtifactContentRegistryStoreStatus.CREATED
                assert repeated is ArtifactContentRegistryStoreStatus.ALREADY_PRESENT

            async with runtime.session_factory() as session:
                registry = SqlAlchemyAuthorizedEvaluationArtifactRegistry(session)

                exact = await registry.resolve_owned(
                    owner_user_id=owner.id,
                    project_id=project.id,
                    workflow_run_id=WORKFLOW_RUN_ID,
                    artifact_id=ARTIFACT_ID,
                    version_number=1,
                )

                wrong_owner = await registry.resolve_owned(
                    owner_user_id=foreign.id,
                    project_id=project.id,
                    workflow_run_id=WORKFLOW_RUN_ID,
                    artifact_id=ARTIFACT_ID,
                    version_number=1,
                )

                wrong_project = await registry.resolve_owned(
                    owner_user_id=owner.id,
                    project_id=OTHER_PROJECT_ID,
                    workflow_run_id=WORKFLOW_RUN_ID,
                    artifact_id=ARTIFACT_ID,
                    version_number=1,
                )

                wrong_workflow = await registry.resolve_owned(
                    owner_user_id=owner.id,
                    project_id=project.id,
                    workflow_run_id=OTHER_WORKFLOW_RUN_ID,
                    artifact_id=ARTIFACT_ID,
                    version_number=1,
                )

                assert exact == reference
                assert wrong_owner is None
                assert wrong_project is None
                assert wrong_workflow is None

        finally:
            await runtime.dispose()

    asyncio.run(
        scenario(),
        loop_factory=asyncio.SelectorEventLoop,
    )


def test_postgresql_registry_rejects_metadata_conflict() -> None:
    async def scenario() -> None:
        settings = load_database_settings(env_file=None)
        runtime = create_database_runtime(settings)

        try:
            await _truncate(runtime)

            owner, _, project = await _create_scope(runtime)

            original = AuthorizedEvaluationArtifactRecord(
                owner_user_id=owner.id,
                project_id=project.id,
                workflow_run_id=WORKFLOW_RUN_ID,
                reference=_reference(b"<!doctype html><button>Original</button>"),
            )

            conflicting = AuthorizedEvaluationArtifactRecord(
                owner_user_id=owner.id,
                project_id=project.id,
                workflow_run_id=WORKFLOW_RUN_ID,
                reference=_reference(b"<!doctype html><button>Conflicting</button>"),
            )

            async with runtime.session_factory.begin() as session:
                registry = SqlAlchemyAuthorizedEvaluationArtifactRegistry(session)

                assert await registry.append(original) is ArtifactContentRegistryStoreStatus.CREATED

                assert (
                    await registry.append(conflicting)
                    is ArtifactContentRegistryStoreStatus.CONTENT_CONFLICT
                )

            async with runtime.session_factory() as session:
                registry = SqlAlchemyAuthorizedEvaluationArtifactRegistry(session)

                resolved = await registry.resolve_owned(
                    owner_user_id=owner.id,
                    project_id=project.id,
                    workflow_run_id=WORKFLOW_RUN_ID,
                    artifact_id=ARTIFACT_ID,
                    version_number=1,
                )

                assert resolved == original.reference

        finally:
            await runtime.dispose()

    asyncio.run(
        scenario(),
        loop_factory=asyncio.SelectorEventLoop,
    )
