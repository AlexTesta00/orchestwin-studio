from __future__ import annotations

import json
from copy import deepcopy
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.agents.persistence.repositories import SqlAlchemyTeamProposalVersionRepository
from orchestwin.artifacts.design_evaluation_persistence import SqlAlchemyDesignEvaluationRepository
from orchestwin.artifacts.design_finding_validation_persistence import (
    SqlAlchemyFindingValidationRepository,
)
from orchestwin.artifacts.design_persistence import SqlAlchemyDesignPackageRepository
from orchestwin.artifacts.design_serialization import design_package_from_snapshot
from orchestwin.artifacts.human_validation_persistence import SqlAlchemyHumanValidationRepository
from orchestwin.artifacts.why_mockups import mockup_document_hashes
from orchestwin.models.proposal_evidence_persistence import (
    DESIGN_MOCKUP_PURPOSES,
    EVENTS,
    GENERATIONS,
)
from orchestwin.projects.persistence.briefs import SqlAlchemyProjectBriefRepository
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.projects.persistence.research_evidence import SqlAlchemyResearchEvidenceRepository
from orchestwin.projects.requirements_persistence import (
    SqlAlchemyRequirementsSpecificationRepository,
)
from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.projects.sections import project_sections
from orchestwin.projects.sections_service import SqlAlchemySectionReads
from orchestwin.twins.persistence.repositories import SqlAlchemyUserModelingSnapshotRepository
from orchestwin.why import build_why_document, explain_why


def _envelope(version, stage):
    payload = {
        "brief": lambda: version.brief.to_snapshot(),
        "team": lambda: version.proposal.to_snapshot(),
        "twins": lambda: version.snapshot.to_snapshot(),
        "requirements": lambda: version.specification.to_snapshot(),
        "design": lambda: version.package.to_snapshot(),
    }[stage]()
    wrapper = {
        "brief": "brief",
        "team": "proposal",
        "twins": "snapshot",
        "requirements": "specification",
        "design": "package",
    }[stage]
    result = {
        "id": str(version.id),
        "project_id": str(version.project_id),
        "version_number": version.version_number,
        "content_hash": version.content_hash,
        wrapper: payload,
    }
    if stage == "design":
        result["mockup_document_hashes"] = mockup_document_hashes(version.package)
    return result


def _verified_snapshot(text, digest):
    payload = json.loads(text)
    if canonical_json(payload) != text or snapshot_content_hash(payload) != digest:
        raise ValueError("WHY_STORED_SNAPSHOT_INVALID")
    return payload


def _mockup_package(payload):
    payload = deepcopy(payload)
    for alternative in payload.get("alternatives", ()):
        for key in ("approach", "visual_language"):
            if alternative.get(key) is None:
                alternative.pop(key, None)
    for critique in payload.get("critiques", ()):
        for key in ("verdict", "quote"):
            if critique.get(key) is None:
                critique.pop(key, None)
    if payload.get("generated_mockup") is None:
        payload.pop("generated_mockup", None)
    if not payload.get("owner_assertions"):
        payload.pop("owner_assertions", None)
    return design_package_from_snapshot(payload)


class SqlAlchemyWhyQueryService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def _mockups(self, session, *, owner_user_id, project_id, versions):
        from sqlalchemy.dialects.postgresql import JSONB

        context = sa.func.model_source_context(GENERATIONS.c.snapshot_json)
        event = sa.cast(EVENTS.c.snapshot_json, JSONB)
        query = (
            sa.select(
                EVENTS.c.snapshot_json,
                EVENTS.c.content_hash,
                GENERATIONS.c.snapshot_json.label("request_json"),
                GENERATIONS.c.content_hash.label("request_hash"),
            )
            .join(GENERATIONS, GENERATIONS.c.id == EVENTS.c.generation_id)
            .join(ProjectRecord, ProjectRecord.id == GENERATIONS.c.project_id)
            .where(
                ProjectRecord.id == project_id,
                ProjectRecord.owner_user_id == owner_user_id,
                ProjectRecord.archived_at.is_(None),
                GENERATIONS.c.owner_user_id == owner_user_id,
                EVENTS.c.kind == "ADAPTER_ACCEPTED",
                context.op("->>")("purpose").in_(DESIGN_MOCKUP_PURPOSES),
            )
            .order_by(event["recorded_at"].astext, EVENTS.c.id)
        )
        rows = (await session.execute(query)).mappings().all()
        exact_versions = {(str(version.id), version.content_hash): version for version in versions}
        mockups = []
        for row in rows:
            _verified_snapshot(row["request_json"], row["request_hash"])
            snapshot = _verified_snapshot(row["snapshot_json"], row["content_hash"])
            result = snapshot.get("payload", {}).get("result", {})
            version = exact_versions.get(
                (str(result.get("design_version_id")), result.get("design_content_hash"))
            )
            if version is None or not isinstance(result.get("package"), dict):
                continue
            package = _mockup_package(result["package"])
            if package.prototype is None:
                continue
            alternative = next(
                (
                    item
                    for item in package.alternatives
                    if item.id == package.prototype.design_alternative_id
                ),
                None,
            )
            mockups.append(
                {
                    "id": str(result.get("generation_id", snapshot["generation_id"])),
                    "version_number": version.version_number,
                    "content_hash": package.content_hash,
                    "current": False,
                    "package": package.to_snapshot(),
                    "prototype": package.prototype.to_snapshot(),
                    "mockup_document_hashes": mockup_document_hashes(package),
                    "alternative": {} if alternative is None else alternative.to_snapshot(),
                    "base_reference": {
                        "artifact_id": str(version.id),
                        "version_number": version.version_number,
                        "content_hash": version.content_hash,
                    },
                    "audit_reference": {
                        "generation_id": snapshot["generation_id"],
                        "content_hash": row["content_hash"],
                        "request_content_hash": row["request_hash"],
                    },
                }
            )
        latest = {}
        for mockup in mockups:
            latest[str(mockup["alternative"].get("id"))] = mockup
        if versions:
            for mockup in latest.values():
                mockup["current"] = mockup["base_reference"]["artifact_id"] == str(versions[-1].id)
        return mockups

    async def current(
        self, *, owner_user_id: UUID, project_id: UUID, validation_context: bool = False
    ) -> dict | None:
        async with self._session_factory() as session:
            owned = await session.scalar(
                sa.select(ProjectRecord.id).where(
                    ProjectRecord.id == project_id,
                    ProjectRecord.owner_user_id == owner_user_id,
                    ProjectRecord.archived_at.is_(None),
                )
            )
            if owned is None:
                return None
            facts = await SqlAlchemySectionReads(self._session_factory).facts(
                owner_user_id=owner_user_id,
                project_id=project_id,
            )
            return await self.in_session(
                session,
                owner_user_id=owner_user_id,
                project_id=project_id,
                sections=None if facts is None else project_sections(facts).to_snapshot(),
                validation_context=validation_context,
            )

    async def in_session(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        sections=None,
        validation_context: bool = False,
    ) -> dict | None:
        owned = await session.scalar(
            sa.select(ProjectRecord.id).where(
                ProjectRecord.id == project_id,
                ProjectRecord.owner_user_id == owner_user_id,
                ProjectRecord.archived_at.is_(None),
            )
        )
        if owned is None:
            return None
        brief = await SqlAlchemyProjectBriefRepository(session).list_owned_versions(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )
        team = await SqlAlchemyTeamProposalVersionRepository(session).list_owned_versions(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )
        modeling = await SqlAlchemyUserModelingSnapshotRepository(
            session,
            owner_user_id=owner_user_id,
        ).history(project_id=project_id)
        requirements = await SqlAlchemyRequirementsSpecificationRepository(
            session,
            owner_user_id=owner_user_id,
        ).history(project_id=project_id)
        design = await SqlAlchemyDesignPackageRepository(
            session,
            owner_user_id=owner_user_id,
        ).history(project_id=project_id)
        evidence = await SqlAlchemyResearchEvidenceRepository(
            session,
            owner_user_id=owner_user_id,
        ).dossier(project_id)
        evaluations = await SqlAlchemyDesignEvaluationRepository(
            session,
            owner_user_id=owner_user_id,
        ).list(project_id=project_id, limit=2_147_483_647)
        decisions = await SqlAlchemyFindingValidationRepository(
            session,
            owner_user_id=owner_user_id,
        ).current(project_id=project_id)
        mockups = await self._mockups(
            session, owner_user_id=owner_user_id, project_id=project_id, versions=design
        )
        evaluation_snapshots = [run.to_snapshot() for run in evaluations]
        records = await SqlAlchemyHumanValidationRepository(
            session, owner_user_id=owner_user_id
        ).records(project_id=project_id)
        return build_why_document(
            project_id=str(project_id),
            stages={
                stage: [_envelope(version, stage) for version in values]
                for stage, values in (
                    ("brief", brief),
                    ("team", team),
                    ("twins", modeling),
                    ("requirements", requirements),
                    ("design", design),
                )
            },
            evidence=evidence,
            evaluations=[
                {
                    "runs": evaluation_snapshots,
                    "decisions": [item.to_snapshot() for item in decisions],
                }
            ],
            mockups=mockups,
            sections=sections,
            hypotheses=records["hypotheses"],
            outcomes=records["outcomes"],
            validation_context=validation_context,
        )

    async def explain(self, *, owner_user_id: UUID, project_id: UUID, code: str) -> dict | None:
        document = await self.current(owner_user_id=owner_user_id, project_id=project_id)
        return None if document is None else explain_why(document, code)


__all__ = ["SqlAlchemyWhyQueryService"]
