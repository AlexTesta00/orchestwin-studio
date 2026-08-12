"""Application-service composition for the FastAPI boundary."""

from __future__ import annotations

import os
from dataclasses import dataclass

from orchestwin.identity.application import (
    IdentityApplicationService,
    LocalIdentityApplicationService,
)
from orchestwin.identity.passwords import (
    Argon2PasswordService,
)
from orchestwin.identity.persistence import (
    SqlAlchemyIdentityUnitOfWorkFactory,
)
from orchestwin.identity.tokens import (
    JwtAccessTokenService,
    load_access_token_settings,
)
from orchestwin.persistence import (
    DatabaseRuntime,
    create_database_runtime,
    load_database_settings,
)
from orchestwin.projects.application import (
    LocalProjectApplicationService,
    ProjectApplicationService,
)
from orchestwin.projects.brief_gate import (
    LocalProjectBriefGateService,
    ProjectBriefGateService,
)
from orchestwin.projects.clarification_application import (
    LocalProjectClarificationApplicationService,
    ProjectClarificationApplicationService,
)
from orchestwin.projects.persistence import (
    SqlAlchemyProjectBriefGateUnitOfWorkFactory,
    SqlAlchemyProjectClarificationUnitOfWorkFactory,
    SqlAlchemyProjectUnitOfWorkFactory,
)

DATABASE_URL_ENVIRONMENT = "ORCHESTWIN_DATABASE_URL"
JWT_SECRET_ENVIRONMENT = "ORCHESTWIN_AUTH_JWT_SECRET"


@dataclass(slots=True)
class ApplicationRuntime:
    """Process-level adapters owned by one FastAPI application."""

    identity_service: IdentityApplicationService | None = None
    project_service: ProjectApplicationService | None = None
    clarification_service: ProjectClarificationApplicationService | None = None
    brief_gate_service: ProjectBriefGateService | None = None
    database_runtime: DatabaseRuntime | None = None

    async def close(self) -> None:
        """Dispose process-level resources."""
        if self.database_runtime is not None:
            await self.database_runtime.dispose()


def create_default_runtime() -> ApplicationRuntime:
    """Create persistence-backed services when configuration exists."""
    database_url = os.getenv(DATABASE_URL_ENVIRONMENT)
    jwt_secret = os.getenv(JWT_SECRET_ENVIRONMENT)

    if not database_url or not jwt_secret:
        return ApplicationRuntime()

    database_runtime = create_database_runtime(load_database_settings())

    identity_service = LocalIdentityApplicationService(
        unit_of_work_factory=(
            SqlAlchemyIdentityUnitOfWorkFactory(database_runtime.session_factory)
        ),
        password_service=(Argon2PasswordService()),
        access_token_service=(JwtAccessTokenService(load_access_token_settings())),
    )

    project_service = LocalProjectApplicationService(
        unit_of_work_factory=(SqlAlchemyProjectUnitOfWorkFactory(database_runtime.session_factory))
    )
    clarification_service = LocalProjectClarificationApplicationService(
        unit_of_work_factory=(
            SqlAlchemyProjectClarificationUnitOfWorkFactory(database_runtime.session_factory)
        )
    )
    brief_gate_service = LocalProjectBriefGateService(
        unit_of_work_factory=(
            SqlAlchemyProjectBriefGateUnitOfWorkFactory(database_runtime.session_factory)
        )
    )

    return ApplicationRuntime(
        identity_service=identity_service,
        project_service=project_service,
        clarification_service=clarification_service,
        brief_gate_service=brief_gate_service,
        database_runtime=database_runtime,
    )
