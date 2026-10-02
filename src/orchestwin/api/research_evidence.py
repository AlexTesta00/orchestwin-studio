from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount
from orchestwin.projects.evidence_application import (
    append_evidence_profiles,
    evidence_profile,
    withdrawn_observation,
)
from orchestwin.projects.persistence.research_evidence import (
    CHANGES,
    SqlAlchemyResearchEvidenceRepository,
    evidence_citation_from_row,
)
from orchestwin.projects.persistence.twin_learning import UPDATES, SqlAlchemyTwinLearningRepository
from orchestwin.projects.research_evidence import ResearchEvidenceError
from orchestwin.projects.twin_learning import UpdateDecisionKind, UpdateStatus
from orchestwin.twins.epistemics import EvidenceSourceKind
from orchestwin.twins.persistence.repositories import SqlAlchemyUserModelingSnapshotRepository
from orchestwin.twins.persistence.uow import SqlAlchemyUserModelingUnitOfWork
from orchestwin.twins.user_modeling_gate import user_modeling_gate_is_currently_approved
from orchestwin.workflow.gates import HumanGateType
from orchestwin.workflow.persistence.repositories import SqlAlchemyHumanGateRepository


def research_evidence_refusal(error: ResearchEvidenceError) -> HTTPException:
    code = error.code
    status = (
        404
        if code in {"EVIDENCE_NOT_FOUND", "PROJECT_NOT_FOUND"}
        else 422
        if code in {"EVIDENCE_LIMIT", "EVIDENCE_INVALID_TEXT", "EVIDENCE_ACKNOWLEDGEMENT_REQUIRED"}
        else 409
    )
    detail = {"code": code}
    if code == "EVIDENCE_LIMIT":
        detail["message"] = "The evidence limit was exceeded. Split the text into parts."
    return HTTPException(status, detail=detail)


class EvidenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    source_kind: EvidenceSourceKind = EvidenceSourceKind.OWNER_INPUT
    source_ref: str = Field(default="", max_length=1000)
    context: str = Field(default="", max_length=2000)
    method: str = Field(default="", max_length=1000)
    collected_at: str | None = Field(default=None, max_length=200)
    limitations: str = Field(default="", max_length=2000)
    empirical: bool = False
    text: str
    acknowledged: bool = False

    @field_validator("title")
    @classmethod
    def normalized_title(cls, value):
        title = " ".join(value.split())
        if not title:
            raise ValueError("an evidence source requires a title")
        return title

    @model_validator(mode="after")
    def declared_nature(self):
        if (self.source_kind is EvidenceSourceKind.EMPIRICAL_RESEARCH) != self.empirical:
            raise ValueError("empirical nature must match the declared source kind")
        if self.empirical and (not self.method.strip() or not self.limitations.strip()):
            raise ValueError("empirical evidence requires method and limitations")
        return self


class EvidenceRetireBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=300)


class EvidenceDeleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acknowledged: bool = False


class EvidenceAssociateBody(EvidenceDeleteBody):
    version: int = Field(ge=1)
    text: str


class ResearchEvidenceApplication:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def sessions(self):
        database = getattr(self.runtime, "database_runtime", None)
        if database is None:
            raise HTTPException(503, detail={"code": "DATABASE_UNAVAILABLE"})
        return database.session_factory

    async def citations(self, repository, project_id: UUID, *, source_id: UUID | None = None):
        rows = await repository.changes(project_id)
        return [
            evidence_citation_from_row(row)
            for row in rows
            if source_id is None or row["source_id"] == source_id
        ]

    async def list(self, *, owner_user_id: UUID, project_id: UUID, all_versions: bool = False):
        async with self.sessions()() as session:
            repository = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=owner_user_id)
            if not await repository.owned(project_id):
                raise ResearchEvidenceError("PROJECT_NOT_FOUND")
            evidence = await repository.list(project_id, all_versions=all_versions)
            return {
                "project_id": str(project_id),
                "evidence": [item.to_snapshot() for item in evidence],
                "citations": await self.citations(repository, project_id),
            }

    async def get(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        source_id: UUID,
        version: int | None = None,
        include_text: bool = False,
    ):
        async with self.sessions()() as session:
            repository = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=owner_user_id)
            if not await repository.owned(project_id):
                raise ResearchEvidenceError("PROJECT_NOT_FOUND")
            evidence = await repository.get(project_id, source_id, version)
            if evidence is None:
                raise ResearchEvidenceError("EVIDENCE_NOT_FOUND")
            result = {
                **evidence.to_snapshot(),
                "citations": await self.citations(repository, project_id, source_id=source_id),
            }
            if include_text:
                text = await repository.text(project_id, source_id, evidence.version)
                if text is None:
                    raise ResearchEvidenceError("EVIDENCE_TEXT_UNAVAILABLE")
                result["text"] = text
            return result

    async def insert(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        body: EvidenceBody,
        source_id: UUID | None = None,
    ):
        if not body.acknowledged:
            raise ResearchEvidenceError("EVIDENCE_ACKNOWLEDGEMENT_REQUIRED")
        async with self.sessions()() as session, session.begin():
            repository = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=owner_user_id)
            evidence = await repository.insert(
                project_id,
                metadata=body.model_dump(exclude={"text", "acknowledged"}),
                text=body.text,
                source_id=source_id,
            )
            if source_id is not None:
                learning = SqlAlchemyTwinLearningRepository(session, owner_user_id=owner_user_id)
                pending = (
                    (
                        await session.execute(
                            sa.select(UPDATES.c.id).where(
                                UPDATES.c.project_id == project_id,
                                UPDATES.c.owner_user_id == owner_user_id,
                                UPDATES.c.status == "PROPOSED",
                                UPDATES.c.evidence["source_id"].astext == str(source_id),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for update_id in pending:
                    await learning.decide_update(
                        project_id,
                        update_id,
                        UpdateDecisionKind.REJECT,
                        decided_at=datetime.now(UTC),
                        reason="The evidence source has a new version.",
                    )
        return {
            "status": "EVIDENCE_ADDED" if source_id is None else "EVIDENCE_REVISED",
            "evidence": evidence.to_snapshot(),
        }

    async def retire(
        self, *, owner_user_id: UUID, project_id: UUID, source_id: UUID, body: EvidenceRetireBody
    ):
        occurred_at = datetime.now(UTC)
        review_required = False
        async with self.sessions()() as session, session.begin():
            repository = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=owner_user_id)
            if not await repository.owned(project_id, lock=True):
                raise ResearchEvidenceError("PROJECT_NOT_FOUND")
            records = await repository.changes(project_id)
            active = [
                row
                for row in records
                if row["source_id"] == source_id and row["retired_at"] is None
            ]
            affected = {row["twin_id"] for row in active}
            profiles = {}
            if affected:
                current = await SqlAlchemyUserModelingSnapshotRepository(
                    session, owner_user_id=owner_user_id
                ).current(project_id=project_id)
                gate = await SqlAlchemyHumanGateRepository(session).get_latest_owned_for_update(
                    project_id=project_id,
                    owner_user_id=owner_user_id,
                    gate_type=HumanGateType.USER_MODELING,
                )
                pending_revision = await SqlAlchemyUserModelingUnitOfWork(
                    session, owner_user_id=owner_user_id
                ).has_pending_manual_revision(project_id=project_id)
                review_required = (
                    current is None
                    or pending_revision
                    or not user_modeling_gate_is_currently_approved(gate, current)
                )
                if current is None:
                    affected = set()
                for twin in () if current is None else current.snapshot.twin_versions:
                    if twin.twin_id not in affected:
                        continue
                    fields = {row["field"] for row in active if row["twin_id"] == twin.twin_id}
                    grouped = defaultdict(list)
                    for row in records:
                        if row["twin_id"] == twin.twin_id and row["field"] in fields:
                            grouped[row["field"]].append(row)
                    observations = [
                        withdrawn_observation(
                            observation,
                            grouped[observation.observation_key.removeprefix("user_twin.")],
                            source_id=source_id,
                        )
                        for observation in twin.profile.observations
                        if observation.observation_key.removeprefix("user_twin.") in fields
                    ]
                    profiles[twin.twin_id] = evidence_profile(twin.profile, observations)
                if profiles:
                    await append_evidence_profiles(
                        session,
                        owner_user_id=owner_user_id,
                        current=current,
                        profiles=profiles,
                        occurred_at=occurred_at,
                        approve=not review_required,
                    )
            evidence = await repository.retire(
                project_id, source_id, reason=" ".join(body.reason.split()), occurred_at=occurred_at
            )
            await session.execute(
                sa.update(CHANGES)
                .where(
                    CHANGES.c.project_id == project_id,
                    CHANGES.c.owner_user_id == owner_user_id,
                    CHANGES.c.source_id == source_id,
                    CHANGES.c.retired_at.is_(None),
                )
                .values(retired_at=occurred_at)
            )
            learning = SqlAlchemyTwinLearningRepository(session, owner_user_id=owner_user_id)
            pending = (
                (
                    await session.execute(
                        sa.select(UPDATES.c.id).where(
                            UPDATES.c.project_id == project_id,
                            UPDATES.c.owner_user_id == owner_user_id,
                            UPDATES.c.status == UpdateStatus.PROPOSED.value,
                            sa.or_(
                                UPDATES.c.evidence["source_id"].astext == str(source_id),
                                UPDATES.c.twin_id.in_(profiles),
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for update_id in pending:
                await learning.decide_update(
                    project_id,
                    update_id,
                    UpdateDecisionKind.REJECT,
                    decided_at=occurred_at,
                    reason="Evidence was withdrawn.",
                )
        return {
            "status": "EVIDENCE_RETIRED",
            "evidence": evidence.to_snapshot(),
            "affected_twins": [str(item) for item in sorted(profiles, key=str)],
            **(
                {
                    "review_required": True,
                    "message": "The evidence was retired. Review the pending twin profile before approving it.",
                }
                if review_required
                else {}
            ),
        }

    async def delete_text(
        self, *, owner_user_id: UUID, project_id: UUID, source_id: UUID, body: EvidenceDeleteBody
    ):
        if not body.acknowledged:
            raise ResearchEvidenceError("EVIDENCE_ACKNOWLEDGEMENT_REQUIRED")
        async with self.sessions()() as session, session.begin():
            repository = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=owner_user_id)
            if not await repository.owned(project_id, lock=True):
                raise ResearchEvidenceError("PROJECT_NOT_FOUND")
            evidence = await repository.delete_text(project_id, source_id)
        return {"status": "EVIDENCE_TEXT_DELETED", "evidence": evidence.to_snapshot()}

    async def associate_text(
        self, *, owner_user_id: UUID, project_id: UUID, source_id: UUID, body: EvidenceAssociateBody
    ):
        if not body.acknowledged:
            raise ResearchEvidenceError("EVIDENCE_ACKNOWLEDGEMENT_REQUIRED")
        async with self.sessions()() as session, session.begin():
            repository = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=owner_user_id)
            evidence = await repository.associate_text(
                project_id, source_id, body.version, body.text
            )
        return {"status": "EVIDENCE_TEXT_REASSOCIATED", "evidence": evidence.to_snapshot()}


def create_research_evidence_router() -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}", tags=["research-evidence"])

    def application(request: Request):
        return ResearchEvidenceApplication(request.app.state.application_runtime)

    async def run(awaitable):
        try:
            return await awaitable
        except ResearchEvidenceError as error:
            raise research_evidence_refusal(error) from error

    @router.get("/evidence")
    async def list_evidence(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        all: bool = False,
    ):
        return await run(
            application(request).list(
                owner_user_id=user.id, project_id=project_id, all_versions=all
            )
        )

    @router.post("/evidence", status_code=201)
    async def add_evidence(
        project_id: UUID,
        body: EvidenceBody,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        return await run(
            application(request).insert(owner_user_id=user.id, project_id=project_id, body=body)
        )

    @router.get("/evidence/{evidence_id}")
    async def get_evidence(
        project_id: UUID,
        evidence_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        version: int | None = None,
        text: bool = False,
    ):
        return await run(
            application(request).get(
                owner_user_id=user.id,
                project_id=project_id,
                source_id=evidence_id,
                version=version,
                include_text=text,
            )
        )

    @router.post("/evidence/{evidence_id}/versions", status_code=201)
    async def revise_evidence(
        project_id: UUID,
        evidence_id: UUID,
        body: EvidenceBody,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        return await run(
            application(request).insert(
                owner_user_id=user.id, project_id=project_id, source_id=evidence_id, body=body
            )
        )

    @router.post("/evidence/{evidence_id}/retire")
    async def retire_evidence(
        project_id: UUID,
        evidence_id: UUID,
        body: EvidenceRetireBody,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        return await run(
            application(request).retire(
                owner_user_id=user.id, project_id=project_id, source_id=evidence_id, body=body
            )
        )

    @router.delete("/evidence/{evidence_id}/text")
    async def delete_evidence_text(
        project_id: UUID,
        evidence_id: UUID,
        body: EvidenceDeleteBody,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        return await run(
            application(request).delete_text(
                owner_user_id=user.id, project_id=project_id, source_id=evidence_id, body=body
            )
        )

    @router.put("/evidence/{evidence_id}/text")
    async def associate_evidence_text(
        project_id: UUID,
        evidence_id: UUID,
        body: EvidenceAssociateBody,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        return await run(
            application(request).associate_text(
                owner_user_id=user.id, project_id=project_id, source_id=evidence_id, body=body
            )
        )

    return router
