"""Append-only PostgreSQL proposal observations and atomic artifact bindings."""

from __future__ import annotations

import base64
import hashlib
import json
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.models.proposal_evidence import ProposalEvidenceError, evidence_snapshot
from orchestwin.persistence.orm import OrmBase
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash

GENERATIONS = sa.Table(
    "model_proposal_generations",
    OrmBase.metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column(
        "project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    ),
    sa.Column(
        "owner_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    ),
    sa.Column("task_id", sa.String(64), nullable=False),
    sa.Column("request_content_hash", sa.String(64), nullable=False),
    sa.Column("snapshot_json", sa.Text(), nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
)
EVENTS = sa.Table(
    "model_proposal_generation_events",
    OrmBase.metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column(
        "generation_id",
        sa.Uuid(),
        sa.ForeignKey(GENERATIONS.c.id, ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("snapshot_json", sa.Text(), nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("raw_body", sa.LargeBinary()),
    sa.UniqueConstraint("generation_id", "kind"),
)
LINKS = sa.Table(
    "model_proposal_artifact_links",
    OrmBase.metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column(
        "generation_id",
        sa.Uuid(),
        sa.ForeignKey(GENERATIONS.c.id, ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("artifact_kind", sa.String(24), nullable=False),
    sa.Column("artifact_version_id", sa.Uuid(), nullable=False),
    sa.Column("version_number", sa.Integer(), nullable=False),
    sa.Column("artifact_content_hash", sa.String(64), nullable=False),
    sa.Column("relation", sa.String(24), nullable=False),
    sa.Column("snapshot_json", sa.Text(), nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.UniqueConstraint("generation_id", "artifact_kind", "artifact_version_id"),
)


def _owned(owner_user_id, project_id):
    return (ProjectRecord.id == project_id, ProjectRecord.owner_user_id == owner_user_id)


def _owned_generation(owner_user_id, project_id, generation_id=None):
    query = (
        sa.select(GENERATIONS)
        .join(ProjectRecord, ProjectRecord.id == GENERATIONS.c.project_id)
        .where(
            *_owned(owner_user_id, project_id),
            GENERATIONS.c.owner_user_id == owner_user_id,
        )
    )
    return query if generation_id is None else query.where(GENERATIONS.c.id == generation_id)


def _verify(record):
    payload = json.loads(record["snapshot_json"])
    if (
        canonical_json(payload) != record["snapshot_json"]
        or snapshot_content_hash(payload) != record["content_hash"]
    ):
        raise ProposalEvidenceError("PROPOSAL_EVIDENCE_HASH_MISMATCH")
    return payload


class SqlAlchemyProposalEvidenceStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sessions = session_factory

    async def latest_design_mockup(
        self,
        *,
        owner_user_id,
        project_id,
        design_content_hash,
        alternative_id,
    ):
        """Recover the newest accepted visual draft for this exact design context."""
        from sqlalchemy.dialects.postgresql import JSONB

        context = sa.func.model_source_context(GENERATIONS.c.snapshot_json)
        event = sa.cast(EVENTS.c.snapshot_json, JSONB)
        query = (
            sa.select(
                EVENTS,
                GENERATIONS.c.snapshot_json.label("request_snapshot_json"),
                GENERATIONS.c.content_hash.label("request_evidence_hash"),
            )
            .join(GENERATIONS, GENERATIONS.c.id == EVENTS.c.generation_id)
            .join(ProjectRecord, ProjectRecord.id == GENERATIONS.c.project_id)
            .where(
                *_owned(owner_user_id, project_id),
                GENERATIONS.c.owner_user_id == owner_user_id,
                EVENTS.c.kind == "ADAPTER_ACCEPTED",
                context.op("->>")("purpose") == "DESIGN_MOCKUP",
                context.op("->>")("design_content_hash") == design_content_hash,
                context.op("->")("alternative").op("->>")("id") == str(alternative_id),
            )
            .order_by(event["recorded_at"].astext.desc())
            .limit(1)
        )
        async with self._sessions() as session:
            row = (await session.execute(query)).mappings().first()
            if row is None:
                return None
            _verify(
                {
                    "snapshot_json": row["request_snapshot_json"],
                    "content_hash": row["request_evidence_hash"],
                }
            )
            snapshot = _verify(row)
            return snapshot["payload"]["result"]

    async def begin(self, *, owner_user_id, project_id, request):
        context = json.loads(request.input_payload_json)["context"]
        if "request" in context:
            context = context["request"]
        requested_project = (
            context["brief_version"]["project_id"]
            if request.task_id == "proposal-team-v1"
            else context["project_id"]
        )
        if requested_project != str(project_id):
            raise ProposalEvidenceError("GENERATION_PROJECT_MISMATCH")
        snapshot, digest = evidence_snapshot(
            {
                "generation_id": str(request.request_id),
                "project_id": str(project_id),
                "owner_user_id": str(owner_user_id),
                "request": request.to_snapshot(),
            }
        )
        try:
            async with self._sessions() as session, session.begin():
                if (
                    await session.scalar(
                        sa.select(ProjectRecord.id).where(
                            *_owned(owner_user_id, project_id), ProjectRecord.archived_at.is_(None)
                        )
                    )
                    is None
                ):
                    raise ProposalEvidenceError("GENERATION_PROJECT_NOT_OWNED")
                await session.execute(
                    sa.insert(GENERATIONS).values(
                        id=request.request_id,
                        project_id=project_id,
                        owner_user_id=owner_user_id,
                        task_id=request.task_id,
                        request_content_hash=request.content_hash,
                        snapshot_json=canonical_json(snapshot),
                        content_hash=digest,
                    )
                )
        except sa.exc.SQLAlchemyError as error:
            raise ProposalEvidenceError("GENERATION_EVIDENCE_WRITE_FAILED") from error

    async def append(
        self, *, generation_id, owner_user_id, project_id, kind, payload, raw_body=None
    ):
        snapshot, digest = evidence_snapshot(
            {
                "generation_id": str(generation_id),
                "kind": kind,
                "payload": payload,
                "raw_body_sha256": None
                if raw_body is None
                else hashlib.sha256(raw_body).hexdigest(),
            }
        )
        try:
            async with self._sessions() as session, session.begin():
                row = (
                    (
                        await session.execute(
                            _owned_generation(owner_user_id, project_id, generation_id)
                        )
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    raise ProposalEvidenceError("GENERATION_NOT_OWNED")
                _verify(row)
                await session.execute(
                    sa.insert(EVENTS).values(
                        id=uuid4(),
                        generation_id=generation_id,
                        kind=kind,
                        snapshot_json=canonical_json(snapshot),
                        content_hash=digest,
                        raw_body=raw_body,
                    )
                )
        except sa.exc.SQLAlchemyError as error:
            raise ProposalEvidenceError("GENERATION_EVIDENCE_WRITE_FAILED") from error

    async def list_owned(self, *, owner_user_id, project_id, limit=50, before=None):
        if not 1 <= limit <= 100:
            raise ValueError("generation list limit must be between 1 and 100")
        async with self._sessions() as session:
            if (
                await session.scalar(
                    sa.select(ProjectRecord.id).where(*_owned(owner_user_id, project_id))
                )
                is None
            ):
                return None
            query = _owned_generation(owner_user_id, project_id)
            if before is not None:
                query = query.where(GENERATIONS.c.id < before)
            rows = (
                (await session.execute(query.order_by(GENERATIONS.c.id.desc()).limit(limit)))
                .mappings()
                .all()
            )
            return [
                {
                    "generation_id": str(row["id"]),
                    "task_id": row["task_id"],
                    "request_content_hash": row["request_content_hash"],
                    "content_hash": row["content_hash"],
                    "recorded_at": _verify(row)["recorded_at"],
                }
                for row in rows
            ]

    async def get_owned(self, *, owner_user_id, project_id, generation_id):
        async with self._sessions() as session, session.begin():
            # One consistent view of independently committed observations and atomic links.
            await session.execute(
                sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            row = (
                (await session.execute(_owned_generation(owner_user_id, project_id, generation_id)))
                .mappings()
                .first()
            )
            if row is None:
                return None
            request = _verify(row)
            events = (
                (
                    await session.execute(
                        sa.select(EVENTS).where(EVENTS.c.generation_id == generation_id)
                    )
                )
                .mappings()
                .all()
            )
            links = (
                (
                    await session.execute(
                        sa.select(LINKS).where(LINKS.c.generation_id == generation_id)
                    )
                )
                .mappings()
                .all()
            )
            observations = []
            for event in events:
                snapshot = _verify(event)
                raw = event["raw_body"]
                if snapshot["raw_body_sha256"] != (
                    None if raw is None else hashlib.sha256(raw).hexdigest()
                ):
                    raise ProposalEvidenceError("RAW_RESPONSE_HASH_MISMATCH")
                observations.append(
                    {
                        **snapshot,
                        "content_hash": event["content_hash"],
                        "raw_body_base64": None
                        if raw is None
                        else base64.b64encode(raw).decode("ascii"),
                    }
                )
            observations.sort(key=lambda item: (item["recorded_at"], item["kind"]))
            artifact_links = [
                {**_verify(link), "content_hash": link["content_hash"]} for link in links
            ]
            artifact_links.sort(
                key=lambda item: (item["artifact"]["kind"], item["artifact"]["version_id"])
            )
            kinds = {item["kind"] for item in observations}
            state = (
                "ARTIFACTS_LINKED"
                if artifact_links
                else "MODEL_REJECTED"
                if "ADAPTER_REJECTED" in kinds
                else "MODEL_ACCEPTED_WITHOUT_PUBLICATION"
                if "ADAPTER_ACCEPTED" in kinds
                else "INCOMPLETE"
            )
            return {
                "request": request,
                "content_hash": row["content_hash"],
                "observations": observations,
                "artifact_links": artifact_links,
                "publication_state": state,
            }


class SqlAlchemyProposalEvidenceBindings:
    """Uses the caller's artifact transaction; never commits independently."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def bind(self, scope, references):
        try:
            await self._session.flush()
            row = (
                (
                    await self._session.execute(
                        _owned_generation(
                            scope.owner_user_id,
                            scope.project_id,
                            scope.request.request_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ProposalEvidenceError("GENERATION_NOT_OWNED")
            _verify(row)
            for reference in references:
                snapshot, digest = evidence_snapshot(
                    {
                        "generation_id": str(scope.request.request_id),
                        "artifact": reference,
                    }
                )
                await self._session.execute(
                    sa.insert(LINKS).values(
                        id=uuid4(),
                        generation_id=scope.request.request_id,
                        artifact_kind=reference["kind"],
                        artifact_version_id=UUID(reference["version_id"]),
                        version_number=reference["version_number"],
                        artifact_content_hash=reference["content_hash"],
                        relation=reference["relation"],
                        snapshot_json=canonical_json(snapshot),
                        content_hash=digest,
                    )
                )
        except sa.exc.SQLAlchemyError as error:
            raise ProposalEvidenceError("ATOMIC_EVIDENCE_BINDING_FAILED") from error
