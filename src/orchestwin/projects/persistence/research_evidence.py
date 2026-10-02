from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.projects.research_evidence import (
    MAX_PROJECT_EVIDENCE_BYTES,
    MAX_PROJECT_EVIDENCE_VERSIONS,
    EvidenceStatus,
    EvidenceVersion,
    ResearchEvidenceError,
    evidence_content_hash,
    normalize_evidence_text,
)
from orchestwin.twins.epistemics import EvidenceSourceKind
from orchestwin.twins.user_twins import UserTwinField

VERSIONS = sa.table(
    "research_evidence_versions",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("version", sa.Integer()),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("code", sa.String(12)),
    sa.column("metadata", postgresql.JSONB()),
    sa.column("byte_count", sa.Integer()),
    sa.column("retired_at", sa.DateTime(timezone=True)),
    sa.column("retired_reason", sa.String(300)),
)
TEXTS = sa.table(
    "research_evidence_texts",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("version", sa.Integer()),
    sa.column("text", sa.Text()),
)
CHANGES = sa.table(
    "research_evidence_changes",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("twin_id", postgresql.UUID(as_uuid=True)),
    sa.column("twin_version", sa.Integer()),
    sa.column("update_id", postgresql.UUID(as_uuid=True)),
    sa.column("source_id", postgresql.UUID(as_uuid=True)),
    sa.column("source_version", sa.Integer()),
    sa.column("field", sa.String(64)),
    sa.column("change", postgresql.JSONB()),
    sa.column("before", postgresql.JSONB()),
    sa.column("after", postgresql.JSONB()),
    sa.column("retired_at", sa.DateTime(timezone=True)),
)


def evidence_version_from_row(row: Mapping[str, object]) -> EvidenceVersion:
    data = row["metadata"]
    return EvidenceVersion(
        id=row["id"],
        code=row["code"],
        version=row["version"],
        title=data["title"],
        source_kind=EvidenceSourceKind(data["source_kind"]),
        source_ref=data["source_ref"],
        context=data["context"],
        method=data["method"],
        collected_at=data["collected_at"],
        limitations=data["limitations"],
        empirical=data["empirical"],
        content_hash=data["content_hash"],
        character_count=data["character_count"],
        byte_count=row["byte_count"],
        created_at=datetime.fromisoformat(data["created_at"]),
        status=EvidenceStatus.RETIRED if row["retired_at"] is not None else EvidenceStatus.ACTIVE,
        retired_at=row["retired_at"],
        retired_reason=row["retired_reason"],
        text_available=row.get("text_present") is not None,
        imported_from=data.get("imported_from"),
    )


def evidence_citation_from_row(row: Mapping[str, object]) -> dict[str, object]:
    origin = row["change"].get("imported_from")
    return {
        "twin_id": str(row["twin_id"]),
        "twin_version": row["twin_version"],
        "field": row["field"],
        "effect": row["change"]["effect"],
        "citation": row["change"]["citation"],
        "status": "ACTIVE" if row["retired_at"] is None else "RETIRED",
        **({"imported_from": origin} if origin is not None else {}),
    }


class SqlAlchemyResearchEvidenceRepository:
    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self.session = session
        self.owner_user_id = owner_user_id

    def _owned(self, project_id: UUID):
        return sa.select(ProjectRecord.id).where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == self.owner_user_id,
            ProjectRecord.archived_at.is_(None),
        )

    async def owned(self, project_id: UUID, *, lock: bool = False) -> bool:
        statement = self._owned(project_id)
        if lock:
            statement = statement.with_for_update()
        return (await self.session.scalar(statement)) is not None

    def _versions(self, project_id: UUID):
        return (
            sa.select(*VERSIONS.c, TEXTS.c.id.label("text_present"))
            .select_from(
                VERSIONS.outerjoin(
                    TEXTS,
                    sa.and_(VERSIONS.c.id == TEXTS.c.id, VERSIONS.c.version == TEXTS.c.version),
                )
            )
            .where(
                VERSIONS.c.project_id == project_id, VERSIONS.c.owner_user_id == self.owner_user_id
            )
        )

    async def list(
        self, project_id: UUID, *, all_versions: bool = False
    ) -> tuple[EvidenceVersion, ...]:
        rows = (
            (
                await self.session.execute(
                    self._versions(project_id).order_by(VERSIONS.c.code, VERSIONS.c.version)
                )
            )
            .mappings()
            .all()
        )
        result = tuple(evidence_version_from_row(row) for row in rows)
        if all_versions:
            return result
        latest = {item.id: item for item in result}
        return tuple(
            item
            for item in latest.values()
            if item.status is EvidenceStatus.ACTIVE and item.text_available
        )

    async def get(
        self, project_id: UUID, source_id: UUID, version: int | None = None
    ) -> EvidenceVersion | None:
        query = self._versions(project_id).where(VERSIONS.c.id == source_id)
        if version is not None:
            query = query.where(VERSIONS.c.version == version)
        row = (
            (await self.session.execute(query.order_by(VERSIONS.c.version.desc()).limit(1)))
            .mappings()
            .one_or_none()
        )
        return None if row is None else evidence_version_from_row(row)

    async def text(self, project_id: UUID, source_id: UUID, version: int) -> str | None:
        query = (
            sa.select(TEXTS.c.text)
            .join(
                VERSIONS,
                sa.and_(TEXTS.c.id == VERSIONS.c.id, TEXTS.c.version == VERSIONS.c.version),
            )
            .where(
                VERSIONS.c.project_id == project_id,
                VERSIONS.c.owner_user_id == self.owner_user_id,
                TEXTS.c.id == source_id,
                TEXTS.c.version == version,
            )
        )
        return await self.session.scalar(query)

    async def insert(
        self,
        project_id: UUID,
        *,
        metadata: Mapping[str, object],
        text: str,
        source_id: UUID | None = None,
    ) -> EvidenceVersion:
        if not await self.owned(project_id, lock=True):
            raise ResearchEvidenceError("PROJECT_NOT_FOUND")
        text = normalize_evidence_text(text)
        existing = await self.list(project_id, all_versions=True)
        previous = None if source_id is None else await self.get(project_id, source_id)
        if source_id is not None and previous is None:
            raise ResearchEvidenceError("EVIDENCE_NOT_FOUND")
        if previous is not None and previous.status is EvidenceStatus.RETIRED:
            raise ResearchEvidenceError("EVIDENCE_RETIRED")
        present_bytes = sum(item.byte_count for item in existing if item.text_available)
        if (
            len(existing) >= MAX_PROJECT_EVIDENCE_VERSIONS
            or present_bytes + len(text.encode("utf-8")) > MAX_PROJECT_EVIDENCE_BYTES
        ):
            raise ResearchEvidenceError("EVIDENCE_LIMIT")
        number = max((int(item.code[4:]) for item in existing), default=0) + 1
        evidence = EvidenceVersion(
            id=uuid4() if previous is None else previous.id,
            code=f"EVD-{number:03}" if previous is None else previous.code,
            version=1 if previous is None else previous.version + 1,
            title=metadata["title"],
            source_kind=EvidenceSourceKind(metadata["source_kind"]),
            source_ref=metadata["source_ref"],
            context=metadata["context"],
            method=metadata["method"],
            collected_at=metadata["collected_at"],
            limitations=metadata["limitations"],
            empirical=metadata["empirical"],
            content_hash=evidence_content_hash(text),
            character_count=len(text),
            byte_count=len(text.encode("utf-8")),
            created_at=datetime.now(UTC),
        )
        await self.session.execute(
            sa.insert(VERSIONS).values(
                id=evidence.id,
                version=evidence.version,
                project_id=project_id,
                owner_user_id=self.owner_user_id,
                code=evidence.code,
                metadata=evidence.to_snapshot(),
                byte_count=evidence.byte_count,
            )
        )
        await self.session.execute(
            sa.insert(TEXTS).values(id=evidence.id, version=evidence.version, text=text)
        )
        return evidence

    async def retire(
        self, project_id: UUID, source_id: UUID, *, reason: str, occurred_at: datetime
    ) -> EvidenceVersion:
        evidence = await self.get(project_id, source_id)
        if evidence is None:
            raise ResearchEvidenceError("EVIDENCE_NOT_FOUND")
        await self.session.execute(
            sa.update(VERSIONS)
            .where(
                VERSIONS.c.project_id == project_id,
                VERSIONS.c.owner_user_id == self.owner_user_id,
                VERSIONS.c.id == source_id,
                VERSIONS.c.retired_at.is_(None),
            )
            .values(retired_at=occurred_at, retired_reason=reason)
        )
        return replace(
            evidence,
            status=EvidenceStatus.RETIRED,
            retired_at=evidence.retired_at or occurred_at,
            retired_reason=evidence.retired_reason or reason,
        )

    async def delete_text(self, project_id: UUID, source_id: UUID) -> EvidenceVersion:
        evidence = await self.get(project_id, source_id)
        if evidence is None:
            raise ResearchEvidenceError("EVIDENCE_NOT_FOUND")
        active = await self.session.scalar(
            sa.select(VERSIONS.c.id)
            .where(
                VERSIONS.c.project_id == project_id,
                VERSIONS.c.owner_user_id == self.owner_user_id,
                VERSIONS.c.id == source_id,
                VERSIONS.c.retired_at.is_(None),
            )
            .limit(1)
        )
        if active is not None:
            raise ResearchEvidenceError("EVIDENCE_RETIRE_REQUIRED")
        await self.session.execute(sa.delete(TEXTS).where(TEXTS.c.id == source_id))
        return replace(evidence, text_available=False)

    async def associate_text(
        self, project_id: UUID, source_id: UUID, version: int, text: str
    ) -> EvidenceVersion:
        if not await self.owned(project_id, lock=True):
            raise ResearchEvidenceError("PROJECT_NOT_FOUND")
        evidence = await self.get(project_id, source_id, version)
        if evidence is None:
            raise ResearchEvidenceError("EVIDENCE_NOT_FOUND")
        if evidence.status is not EvidenceStatus.ACTIVE:
            raise ResearchEvidenceError("EVIDENCE_RETIRED")
        text = normalize_evidence_text(text)
        if (
            evidence_content_hash(text) != evidence.content_hash
            or len(text) != evidence.character_count
            or len(text.encode("utf-8")) != evidence.byte_count
        ):
            raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
        if evidence.text_available:
            return evidence
        existing = await self.list(project_id, all_versions=True)
        if (
            sum(item.byte_count for item in existing if item.text_available) + evidence.byte_count
            > MAX_PROJECT_EVIDENCE_BYTES
        ):
            raise ResearchEvidenceError("EVIDENCE_LIMIT")
        await self.session.execute(
            sa.insert(TEXTS).values(id=evidence.id, version=evidence.version, text=text)
        )
        return replace(evidence, text_available=True)

    async def changes(
        self, project_id: UUID, *, twin_id: UUID | None = None
    ) -> tuple[Mapping[str, object], ...]:
        query = sa.select(*CHANGES.c).where(
            CHANGES.c.project_id == project_id, CHANGES.c.owner_user_id == self.owner_user_id
        )
        if twin_id is not None:
            query = query.where(CHANGES.c.twin_id == twin_id)
        return tuple(
            (await self.session.execute(query.order_by(CHANGES.c.twin_version, CHANGES.c.id)))
            .mappings()
            .all()
        )

    async def dossier(self, project_id: UUID) -> dict[str, object]:
        evidence = await self.list(project_id, all_versions=True)
        changes = await self.changes(project_id)
        return {
            "kind": "orchestwin.research-evidence",
            "schema_version": 1,
            "project_id": str(project_id),
            "evidence": [item.to_snapshot() for item in evidence],
            "citations": [evidence_citation_from_row(row) for row in changes],
        }

    async def import_dossier(
        self, project_id: UUID, payload: Mapping[str, object], modeling_snapshot=None
    ) -> None:
        if not await self.owned(project_id, lock=True):
            raise ResearchEvidenceError("PROJECT_NOT_FOUND")
        incoming = payload.get("evidence", ())
        if (
            len(incoming) + len(await self.list(project_id, all_versions=True))
            > MAX_PROJECT_EVIDENCE_VERSIONS
        ):
            raise ResearchEvidenceError("EVIDENCE_LIMIT")
        for item in incoming:
            await self.session.execute(
                sa.insert(VERSIONS).values(
                    id=UUID(str(item["id"])),
                    version=item["version"],
                    project_id=project_id,
                    owner_user_id=self.owner_user_id,
                    code=item["code"],
                    metadata=dict(item),
                    byte_count=item["byte_count"],
                    retired_at=None
                    if item.get("retired_at") is None
                    else datetime.fromisoformat(item["retired_at"]),
                    retired_reason=item.get("retired_reason"),
                )
            )
        snapshot = getattr(modeling_snapshot, "snapshot", modeling_snapshot)
        twins = {} if snapshot is None else {item.twin_id: item for item in snapshot.twin_versions}
        for item in payload.get("citations", ()):
            twin_id = UUID(str(item["twin_id"]))
            twin = twins.get(twin_id)
            observation = (
                None if twin is None else twin.profile.observation_for(UserTwinField(item["field"]))
            )
            citation = item["citation"]
            current_reference = observation is not None and any(
                reference.source_id == str(citation["source_id"])
                and reference.source_version == citation["source_version"]
                and reference.content_hash == citation["content_hash"]
                for reference in observation.provenance.references
            )
            await self.session.execute(
                sa.insert(CHANGES).values(
                    id=uuid4(),
                    project_id=project_id,
                    owner_user_id=self.owner_user_id,
                    twin_id=twin_id,
                    twin_version=item["twin_version"],
                    update_id=None,
                    source_id=UUID(str(citation["source_id"])),
                    source_version=citation["source_version"],
                    field=item["field"],
                    change={
                        "effect": item["effect"],
                        "field": item["field"],
                        "citation": citation,
                        **(
                            {"value": observation.value.to_snapshot()}
                            if observation is not None
                            else {"historical_only": True}
                        ),
                        **(
                            {"imported_from": item["imported_from"]}
                            if item.get("imported_from") is not None
                            else {}
                        ),
                    },
                    before=None,
                    after=observation.to_snapshot()
                    if observation is not None
                    else {"kind": "historical-citation", "profile_available": False},
                    retired_at=datetime.now(UTC)
                    if item.get("status") == "RETIRED" or not current_reference
                    else None,
                )
            )
