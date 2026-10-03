from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.artifacts.human_validation import create_hypothesis, create_outcome
from orchestwin.artifacts.human_validation_persistence import SqlAlchemyHumanValidationRepository
from orchestwin.artifacts.why_runtime import SqlAlchemyWhyQueryService
from orchestwin.projects.persistence.research_evidence import SqlAlchemyResearchEvidenceRepository
from orchestwin.validation import ValidationError, scenario_walkthrough, validation_overview


class SqlAlchemyHumanValidationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        why_query_service=None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._why = why_query_service or SqlAlchemyWhyQueryService(session_factory)
        self._clock = clock or (lambda: datetime.now(UTC))

    async def records(self, *, owner_user_id: UUID, project_id: UUID) -> dict | None:
        async with self._session_factory() as session:
            repository = SqlAlchemyHumanValidationRepository(session, owner_user_id=owner_user_id)
            if not await repository.owned(project_id):
                return None
            return await repository.records(project_id=project_id)

    async def current(self, *, owner_user_id: UUID, project_id: UUID) -> dict | None:
        document = await self._why.current(
            owner_user_id=owner_user_id, project_id=project_id, validation_context=True
        )
        if document is None:
            return None
        records = {
            "hypotheses": [
                node["declared_context"]["hypothesis"]
                for node in document["nodes"]
                if node["kind"] == "VALIDATION_HYPOTHESIS"
            ],
            "outcomes": [
                node["declared_context"]["outcome"]
                for node in document["nodes"]
                if node["kind"] == "VALIDATION_OUTCOME"
            ],
        }
        return validation_overview(document=document, **records)

    async def walkthrough(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        scenario_key: str,
        alternative_id: str | None = None,
        document_hash: str | None = None,
    ) -> dict | None:
        document = await self._why.current(
            owner_user_id=owner_user_id, project_id=project_id, validation_context=True
        )
        return (
            None
            if document is None
            else scenario_walkthrough(
                document, scenario_key, alternative_id=alternative_id, document_hash=document_hash
            )
        )

    async def save_hypothesis(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        request: Mapping,
        hypothesis_id: UUID | None = None,
    ) -> dict:
        async with self._session_factory() as session, session.begin():
            repository = SqlAlchemyHumanValidationRepository(session, owner_user_id=owner_user_id)
            if not await repository.owned(project_id, lock=True):
                raise ValidationError("PROJECT_NOT_FOUND")
            previous = (
                None
                if hypothesis_id is None
                else await repository.hypothesis(project_id=project_id, hypothesis_id=hypothesis_id)
            )
            if hypothesis_id is not None and previous is None:
                raise ValidationError("HYPOTHESIS_NOT_FOUND")
            if previous is not None and (
                isinstance(request.get("based_on_version_number"), bool)
                or request.get("based_on_version_number") != previous.version_number
                or request.get("based_on_content_hash") != previous.content_hash
            ):
                raise ValidationError("HYPOTHESIS_VERSION_CONFLICT")
            document = await self._why.in_session(
                session, owner_user_id=owner_user_id, project_id=project_id, validation_context=True
            )
            if document is None:
                raise ValidationError("PROJECT_NOT_FOUND")
            record = create_hypothesis(
                document=document,
                project_id=project_id,
                owner_user_id=owner_user_id,
                request=request,
                code=previous.to_snapshot()["code"]
                if previous
                else await repository.next_code(project_id=project_id),
                created_at=self._clock(),
                hypothesis_id=hypothesis_id,
                version_number=previous.version_number + 1 if previous else 1,
                based_on_version_number=previous.version_number if previous else None,
            )
            await repository.append_hypothesis(record)
            return {
                "status": "HYPOTHESIS_REVISED" if previous else "HYPOTHESIS_SAVED",
                "hypothesis": record.to_snapshot(),
            }

    async def record_outcome(
        self, *, owner_user_id: UUID, project_id: UUID, request: Mapping
    ) -> dict:
        try:
            hypothesis_id, source_id = (
                UUID(str(request.get("hypothesis_id"))),
                UUID(str(request.get("evidence_id"))),
            )
        except (TypeError, ValueError):
            raise ValidationError("VALIDATION_INPUT_INVALID") from None
        source_version = request.get("evidence_version")
        if (
            isinstance(source_version, bool)
            or not isinstance(source_version, int)
            or source_version < 1
        ):
            raise ValidationError("VALIDATION_INPUT_INVALID")
        async with self._session_factory() as session, session.begin():
            repository = SqlAlchemyHumanValidationRepository(session, owner_user_id=owner_user_id)
            if not await repository.owned(project_id, lock=True):
                raise ValidationError("PROJECT_NOT_FOUND")
            hypothesis = await repository.hypothesis(
                project_id=project_id, hypothesis_id=hypothesis_id
            )
            if hypothesis is None:
                raise ValidationError("HYPOTHESIS_NOT_FOUND")
            if (
                request.get("hypothesis_version_number") != hypothesis.version_number
                or request.get("hypothesis_content_hash") != hypothesis.content_hash
            ):
                raise ValidationError("HYPOTHESIS_VERSION_CONFLICT")
            sources = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=owner_user_id)
            source = await sources.get(project_id, source_id, source_version)
            if source is None:
                raise ValidationError("VALIDATION_SOURCE_NOT_FOUND")
            current_source = await sources.get(project_id, source_id)
            if current_source is None or current_source.version != source_version:
                raise ValidationError("VALIDATION_CONTEXT_CHANGED")
            text = await sources.text(project_id, source_id, source_version)
            document = await self._why.in_session(
                session, owner_user_id=owner_user_id, project_id=project_id, validation_context=True
            )
            current_keys = {node["key"] for node in document["nodes"] if node.get("current", True)}
            snapshot = hypothesis.to_snapshot()
            if any(
                snapshot[field] not in current_keys
                for field in ("origin_key", "twin_key", "scenario_key", "design_key")
            ):
                raise ValidationError("VALIDATION_CONTEXT_CHANGED")
            record = create_outcome(
                hypothesis=hypothesis,
                source=source,
                text=text,
                project_id=project_id,
                owner_user_id=owner_user_id,
                request=request,
                code=await repository.next_code(project_id=project_id, outcome=True),
                recorded_at=self._clock(),
            )
            await repository.append_outcome(record)
            return {"status": "VALIDATION_OUTCOME_RECORDED", "outcome": record.to_snapshot()}


__all__ = ["SqlAlchemyHumanValidationService"]
