"""PostgreSQL integration test for Sprint 02 identity and projects."""

from __future__ import annotations

import asyncio

import pytest
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError

from orchestwin.identity.application import (
    AuthenticationStatus,
    LocalIdentityApplicationService,
)
from orchestwin.identity.passwords import (
    Argon2PasswordService,
)
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
from orchestwin.persistence.migrate import (
    create_alembic_config,
)
from orchestwin.projects.application import (
    LocalProjectApplicationService,
)
from orchestwin.projects.briefs import (
    BriefField,
    create_project_brief,
)
from orchestwin.projects.domain import (
    ProjectMode,
)
from orchestwin.projects.persistence import (
    ProjectBriefVersionRecord,
    SqlAlchemyProjectUnitOfWorkFactory,
)
from orchestwin.projects.repository import (
    BriefVersionCreationStatus,
)

pytestmark = pytest.mark.integration


async def truncate_application_tables(
    runtime,
) -> None:
    """Reset mutable application data without removing migrations."""
    async with runtime.engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE "
                "brief_assumptions, "
                "clarification_rounds, "
                "project_brief_versions, "
                "projects, "
                "auth_sessions, "
                "users "
                "CASCADE"
            )
        )


async def run_integration_scenario() -> None:
    """Exercise identity, ownership, versioning, and DB immutability."""
    database_settings = load_database_settings(env_file=None)
    runtime = create_database_runtime(database_settings)

    try:
        await truncate_application_tables(runtime)

        identity = LocalIdentityApplicationService(
            unit_of_work_factory=(SqlAlchemyIdentityUnitOfWorkFactory(runtime.session_factory)),
            password_service=(Argon2PasswordService()),
            access_token_service=(
                JwtAccessTokenService(
                    AccessTokenSettings(
                        jwt_secret=SecretStr(
                            "integration-test-jwt-secret-with-more-than-32-characters"
                        ),
                        access_token_leeway_seconds=0,
                        _env_file=None,
                    )
                )
            ),
        )
        projects = LocalProjectApplicationService(
            unit_of_work_factory=(SqlAlchemyProjectUnitOfWorkFactory(runtime.session_factory))
        )

        owner_result = await identity.register(
            email="owner@example.com",
            password=("correct horse battery staple"),
        )
        other_result = await identity.register(
            email="other@example.com",
            password=("another correct battery staple"),
        )

        assert owner_result.status is (AuthenticationStatus.AUTHENTICATED)
        assert other_result.status is (AuthenticationStatus.AUTHENTICATED)
        assert owner_result.authenticated is not None
        assert other_result.authenticated is not None

        owner = owner_result.authenticated.user
        other = other_result.authenticated.user

        project = await projects.create(
            owner_user_id=owner.id,
            display_name="Integration project",
            mode=(ProjectMode.GREENFIELD_GENERATION),
        )

        assert (
            await projects.get(
                project_id=project.id,
                owner_user_id=owner.id,
            )
            is not None
        )
        assert (
            await projects.get(
                project_id=project.id,
                owner_user_id=other.id,
            )
            is None
        )

        brief = create_project_brief(
            name="Integration project",
            goals=[
                "Verify PostgreSQL persistence",
            ],
            unknown_fields=[BriefField.BUDGET],
        )
        version_result = await projects.create_brief_version(
            project_id=project.id,
            owner_user_id=owner.id,
            brief=brief,
        )

        assert version_result.status is (BriefVersionCreationStatus.CREATED)
        assert version_result.version is not None
        assert version_result.version.version_number == 1

        current = await projects.current_brief(
            project_id=project.id,
            owner_user_id=owner.id,
        )

        assert current is not None
        assert current.brief == brief

        mutation_rejected = False

        try:
            async with runtime.session_factory.begin() as session:
                await session.execute(
                    update(ProjectBriefVersionRecord)
                    .where(ProjectBriefVersionRecord.id == current.id)
                    .values(content_hash="0" * 64)
                )
        except DBAPIError:
            mutation_rejected = True

        assert mutation_rejected is True

        async with runtime.engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))

        scripts = ScriptDirectory.from_config(
            create_alembic_config(database_settings.url.get_secret_value())
        )
        expected_head = scripts.get_current_head()

        assert revision == expected_head
    finally:
        await truncate_application_tables(runtime)
        await runtime.dispose()


def test_postgresql_identity_and_projects_main_path() -> None:
    """Verify the persistence path on PostgreSQL."""
    asyncio.run(
        run_integration_scenario(),
        loop_factory=asyncio.SelectorEventLoop,
    )
