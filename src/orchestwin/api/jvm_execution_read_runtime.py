"""Owner-scoped SELECT-only JVM histories and verified persisted snapshots."""

from fastapi import HTTPException
from sqlalchemy import select

from orchestwin.artifacts.jvm_source_persistence import SqlAlchemyJvmSourceRevisionRepository
from orchestwin.jvm_execution.attempt_persistence import (
    JVM_EXECUTION_ATTEMPTS,
    jvm_execution_attempt_from_record,
)
from orchestwin.jvm_execution.source_policy import SOURCE_POLICY_HASH, SOURCE_POLICY_SCOPE
from orchestwin.projects.persistence.models import ProjectRecord


def _owned_attempts(owner):
    attempts, projects = JVM_EXECUTION_ATTEMPTS, ProjectRecord.__table__
    return (
        select(attempts)
        .join(projects, projects.c.id == attempts.c.project_id)
        .where(
            projects.c.owner_user_id == owner,
            projects.c.archived_at.is_(None),
            attempts.c.created_by_user_id == owner,
        )
    )


def _snapshot(row):
    try:
        return jvm_execution_attempt_from_record(row).to_snapshot()
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            409, detail={"code": "JVM_EXECUTION_EVIDENCE_INTEGRITY_FAILED"}
        ) from None


class SqlAlchemyJvmExecutionReadApiService:
    def __init__(self, session_factory, *, catalog_loader):
        self.sessions = session_factory
        self.catalog_loader = catalog_loader

    async def profiles(self, *, owner_user_id):
        loaded = await self.catalog_loader.load()
        return tuple(
            {
                **profile.scope.to_snapshot(),
                "runtime_source_policy": {
                    "scope": SOURCE_POLICY_SCOPE,
                    "content_hash": SOURCE_POLICY_HASH,
                },
            }
            for profile in loaded.registry.profiles
        )

    async def source_revision_history(self, *, owner_user_id, project_id):
        try:
            async with self.sessions() as session:
                revisions = await SqlAlchemyJvmSourceRevisionRepository(
                    session, owner_user_id=owner_user_id
                ).history(project_id=project_id)
                return tuple(revision.to_snapshot() for revision in revisions)
        except (KeyError, TypeError, ValueError):
            raise HTTPException(
                409, detail={"code": "JVM_SOURCE_EVIDENCE_INTEGRITY_FAILED"}
            ) from None

    async def source_revision(self, *, owner_user_id, project_id, revision_id):
        history = await self.source_revision_history(
            owner_user_id=owner_user_id, project_id=project_id
        )
        return next((item for item in history if item["id"] == str(revision_id)), None)

    async def execution_history(self, *, owner_user_id, project_id):
        async with self.sessions() as session:
            rows = await session.execute(
                _owned_attempts(owner_user_id)
                .where(JVM_EXECUTION_ATTEMPTS.c.project_id == project_id)
                .order_by(JVM_EXECUTION_ATTEMPTS.c.attempt_number.asc())
            )
            return tuple(_snapshot(row) for row in rows.mappings().all())

    async def execution(self, *, owner_user_id, execution_id):
        async with self.sessions() as session:
            row = (
                (
                    await session.execute(
                        _owned_attempts(owner_user_id).where(
                            JVM_EXECUTION_ATTEMPTS.c.id == execution_id
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _snapshot(row)

    async def execution_report(self, *, owner_user_id, execution_id):
        snapshot = await self.execution(owner_user_id=owner_user_id, execution_id=execution_id)
        return None if snapshot is None else snapshot["report"]
