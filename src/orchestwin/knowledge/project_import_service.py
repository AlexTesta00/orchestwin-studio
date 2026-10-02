from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.agents.persistence.repositories import SqlAlchemyTeamProposalVersionRepository
from orchestwin.agents.proposals import TeamProposalVersionCreationStatus
from orchestwin.artifacts.design_evaluation_persistence import (
    DesignEvaluationWriteStatus,
    SqlAlchemyDesignEvaluationRepository,
)
from orchestwin.artifacts.design_finding_validation_persistence import (
    FindingValidationWriteStatus,
    SqlAlchemyFindingValidationRepository,
)
from orchestwin.artifacts.design_persistence import SqlAlchemyDesignPackageRepository
from orchestwin.knowledge.archive import KnowledgeArchiveError, VerifiedFolder, read_verified_folder
from orchestwin.knowledge.project_import import (
    IMPORTED_VERSION_NUMBER,
    ProjectImportPlan,
    plan_documents,
    plan_project_import,
    require_complete,
)
from orchestwin.knowledge.project_import_persistence import (
    SOURCE_NAME_LIMIT,
    ProjectImportRecord,
    SqlAlchemyProjectImportRepository,
)
from orchestwin.projects.briefs import ProjectBriefVersion
from orchestwin.projects.design_application import DesignVersionAppendStatus
from orchestwin.projects.domain import Project, ProjectMode, create_project
from orchestwin.projects.persistence.briefs import SqlAlchemyProjectBriefRepository
from orchestwin.projects.persistence.repositories import SqlAlchemyProjectRepository
from orchestwin.projects.requirements_application import RequirementsVersionAppendStatus
from orchestwin.projects.requirements_persistence import (
    SqlAlchemyRequirementsSpecificationRepository,
)
from orchestwin.twins.persistence.repositories import (
    SqlAlchemyPersonaVersionRepository,
    SqlAlchemyUserModelingSnapshotRepository,
    SqlAlchemyUserTwinVersionRepository,
    VersionAppendStatus,
)

PROJECT_NAME_LIMIT: Final = 120
FOLDER_DOCUMENT_INVALID: Final = "FOLDER_DOCUMENT_INVALID"
PROJECT_NAME_INVALID: Final = "PROJECT_NAME_INVALID"
PROJECT_IMPORT_REJECTED: Final = "PROJECT_IMPORT_REJECTED"
DISPLAY_NAME_LOCATION: Final = "display_name"
PROJECT_MODE_LOCATION: Final = "team: project_mode"
SOURCE_NAME_LOCATION: Final = "orchestwin.json: project.name"


class ProjectImportError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code if detail is None else f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ProjectImportResult:
    project: Project
    record: ProjectImportRecord
    plan: ProjectImportPlan
    brief_version: ProjectBriefVersion
    why_verified: bool = False
    import_limits: tuple[str, ...] = ()


def archive_failure(error: KnowledgeArchiveError) -> ProjectImportError:
    return ProjectImportError(error.code, error.detail)


def verified_archive(content: bytes) -> VerifiedFolder:
    try:
        return read_verified_folder(content)
    except KnowledgeArchiveError as error:
        raise archive_failure(error) from error


def complete_folder(folder: VerifiedFolder) -> VerifiedFolder:
    try:
        require_complete(folder)
    except KnowledgeArchiveError as error:
        raise archive_failure(error) from error
    return folder


def import_source_name(folder: VerifiedFolder) -> str:
    name = folder.project_name
    if not 1 <= len(name) <= SOURCE_NAME_LIMIT:
        raise ProjectImportError(FOLDER_DOCUMENT_INVALID, SOURCE_NAME_LOCATION)
    return name


def import_display_name(display_name: str | None, folder_name: str) -> str:
    given = " ".join((display_name or "").split())
    if given:
        if len(given) > PROJECT_NAME_LIMIT:
            raise ProjectImportError(PROJECT_NAME_INVALID, DISPLAY_NAME_LOCATION)
        return given
    fallback = " ".join(folder_name.split())[:PROJECT_NAME_LIMIT].rstrip()
    if not fallback:
        raise ProjectImportError(PROJECT_NAME_INVALID, DISPLAY_NAME_LOCATION)
    return fallback


def imported_project_mode(folder: VerifiedFolder) -> ProjectMode:
    try:
        return ProjectMode(folder.documents["team"]["proposal"]["project_mode"])
    except (KeyError, TypeError, ValueError) as error:
        raise ProjectImportError(FOLDER_DOCUMENT_INVALID, PROJECT_MODE_LOCATION) from error


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("project import timestamp must be timezone-aware")
    return moment


def planned_import(
    folder: VerifiedFolder,
    *,
    project_id: UUID,
    brief_version_id: UUID,
    owner_user_id: UUID,
    created_at: datetime,
) -> ProjectImportPlan:
    moment = _aware(created_at)
    try:
        plan = plan_project_import(
            folder,
            project_id=project_id,
            brief_version_id=brief_version_id,
            owner_user_id=owner_user_id,
            created_at=moment,
        )
    except KnowledgeArchiveError as error:
        raise archive_failure(error) from error
    except (KeyError, TypeError, ValueError) as error:
        raise ProjectImportError(FOLDER_DOCUMENT_INVALID, str(error) or None) from error
    return plan


def imported_stage_versions(plan: ProjectImportPlan) -> dict[str, dict[str, object]]:
    versions = {
        "brief": (plan.brief_version_id, plan.brief.content_hash),
        "team": (plan.team.id, plan.team.content_hash),
        "twins": (plan.modeling.id, plan.modeling.content_hash),
        "requirements": (plan.requirements.id, plan.requirements.content_hash),
        "design": (plan.design.id, plan.design.content_hash),
    }
    return {
        stage: {
            "version_id": str(version_id),
            "version_number": IMPORTED_VERSION_NUMBER,
            "content_hash": content_hash,
        }
        for stage, (version_id, content_hash) in versions.items()
    }


def import_record(
    plan: ProjectImportPlan,
    *,
    record_id: UUID,
    owner_user_id: UUID,
    content: bytes,
    imported_at: datetime,
) -> ProjectImportRecord:
    origin = plan.origin
    return ProjectImportRecord(
        id=record_id,
        project_id=plan.project_id,
        owner_user_id=owner_user_id,
        source_project_id=origin.project_id,
        source_project_name=origin.project_name,
        package_version=origin.package_version,
        package_content_hash=origin.package_content_hash,
        schema_version=origin.schema_version,
        archive_hash=hashlib.sha256(content).hexdigest(),
        archive_size=len(content),
        stage_versions=imported_stage_versions(plan),
        imported_at=imported_at,
    )


async def _attempt[T](stage: str, operation: Awaitable[T]) -> T:
    try:
        return await operation
    except (DataError, IntegrityError, ValueError) as error:
        raise ProjectImportError(PROJECT_IMPORT_REJECTED, stage) from error


def _require(stage: str, accepted: bool) -> None:
    if not accepted:
        raise ProjectImportError(PROJECT_IMPORT_REJECTED, stage)


async def _write_import(
    session: AsyncSession,
    *,
    project: Project,
    plan: ProjectImportPlan,
    record: ProjectImportRecord,
) -> tuple[Project, ProjectBriefVersion]:
    owner = project.owner_user_id
    imported_at = record.imported_at
    projects = SqlAlchemyProjectRepository(session)
    await _attempt("project", projects.add(project))

    briefs = SqlAlchemyProjectBriefRepository(
        session, clock=lambda: imported_at, uuid_factory=lambda: plan.brief_version_id
    )
    brief = await _attempt(
        "brief",
        briefs.create_owned_version(
            project_id=project.id,
            owner_user_id=owner,
            created_by_user_id=owner,
            brief=plan.brief,
        ),
    )
    _require(
        "brief",
        brief.created
        and brief.version is not None
        and brief.version.id == plan.brief_version_id
        and brief.version.version_number == IMPORTED_VERSION_NUMBER
        and brief.version.content_hash == plan.brief.content_hash,
    )

    teams = SqlAlchemyTeamProposalVersionRepository(
        session, clock=lambda: imported_at, uuid_factory=lambda: plan.team.id
    )
    team = await _attempt(
        "team",
        teams.create_generated_owned(
            project_id=project.id, owner_user_id=owner, proposal=plan.team.proposal
        ),
    )
    _require(
        "team",
        team.status is TeamProposalVersionCreationStatus.CREATED
        and team.version is not None
        and team.version.id == plan.team.id
        and team.version.version_number == IMPORTED_VERSION_NUMBER
        and team.version.content_hash == plan.team.content_hash,
    )

    personas = SqlAlchemyPersonaVersionRepository(session, owner_user_id=owner)
    for persona in plan.personas:
        status = await _attempt("twins", personas.append(persona))
        _require("twins", status is VersionAppendStatus.APPENDED)
    twins = SqlAlchemyUserTwinVersionRepository(session, owner_user_id=owner)
    for twin in plan.twins:
        status = await _attempt("twins", twins.append(twin))
        _require("twins", status is VersionAppendStatus.APPENDED)
    snapshots = SqlAlchemyUserModelingSnapshotRepository(session, owner_user_id=owner)
    status = await _attempt("twins", snapshots.append(plan.modeling))
    _require("twins", status is VersionAppendStatus.APPENDED)

    requirements = SqlAlchemyRequirementsSpecificationRepository(session, owner_user_id=owner)
    appended = await _attempt("requirements", requirements.append(plan.requirements))
    _require("requirements", appended is RequirementsVersionAppendStatus.APPENDED)

    designs = SqlAlchemyDesignPackageRepository(session, owner_user_id=owner)
    designed = await _attempt("design", designs.append(plan.design))
    _require("design", designed is DesignVersionAppendStatus.APPENDED)

    imports = SqlAlchemyProjectImportRepository(session, owner_user_id=owner)
    await _attempt("import", imports.add(record))
    if plan.research_evidence is not None:
        from orchestwin.projects.persistence.research_evidence import (
            SqlAlchemyResearchEvidenceRepository,
        )

        evidence = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=owner)
        await _attempt(
            "evidence", evidence.import_dossier(project.id, plan.research_evidence, plan.modeling)
        )

    evaluations = SqlAlchemyDesignEvaluationRepository(session, owner_user_id=owner)
    for run in plan.evaluations:
        status = await _attempt("feedback", evaluations.create(run))
        _require("feedback", status is DesignEvaluationWriteStatus.WRITTEN)
    validations = SqlAlchemyFindingValidationRepository(session, owner_user_id=owner)
    for item in sorted(
        plan.finding_decisions, key=lambda value: (*map(str, value.key), value.sequence_number)
    ):
        result = await _attempt(
            "feedback",
            validations.append(
                project_id=project.id,
                evaluation_run_id=item.evaluation_run_id,
                twin_id=item.twin_id,
                finding_id=item.finding_id,
                decision=item.decision,
                note=item.note,
                decided_at=item.decided_at,
            ),
        )
        _require(
            "feedback",
            result.status is FindingValidationWriteStatus.WRITTEN and result.validation == item,
        )

    stored = await projects.get_owned(project_id=project.id, owner_user_id=owner)
    _require(
        "project",
        stored is not None and stored.current_brief_version == IMPORTED_VERSION_NUMBER,
    )
    return stored, brief.version


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ProjectImportService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime] = _utc_now,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._uuid_factory = uuid_factory

    async def import_archive(
        self,
        *,
        owner_user_id: UUID,
        content: bytes,
        display_name: str | None = None,
    ) -> ProjectImportResult:
        folder = complete_folder(verified_archive(content))
        source_name = import_source_name(folder)
        mode = imported_project_mode(folder)
        imported_at = _aware(self._clock())
        project_id = self._uuid_factory()
        plan = planned_import(
            folder,
            project_id=project_id,
            brief_version_id=self._uuid_factory(),
            owner_user_id=owner_user_id,
            created_at=imported_at,
        )
        project = create_project(
            owner_user_id=owner_user_id,
            display_name=import_display_name(display_name, source_name),
            mode=mode,
            project_id=project_id,
            created_at=imported_at,
        )
        record = import_record(
            plan,
            record_id=self._uuid_factory(),
            owner_user_id=owner_user_id,
            content=content,
            imported_at=imported_at,
        )
        async with self._session_factory() as session, session.begin():
            stored, brief_version = await _write_import(
                session, project=project, plan=plan, record=record
            )
            try:
                await verify_imported_why(
                    session,
                    folder=folder,
                    plan=plan,
                    owner_user_id=owner_user_id,
                    created_at=imported_at,
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ProjectImportError("FOLDER_WHY_MISMATCH", "stored derivation") from error
        return ProjectImportResult(
            project=stored,
            record=record,
            plan=plan,
            brief_version=brief_version,
            why_verified="why" in folder.manifest,
            import_limits=plan.import_limits,
        )

    async def origin(self, *, owner_user_id: UUID, project_id: UUID) -> ProjectImportRecord | None:
        async with self._session_factory() as session:
            repository = SqlAlchemyProjectImportRepository(session, owner_user_id=owner_user_id)
            return await repository.for_project(project_id)


async def verify_imported_why(session, *, folder, plan, owner_user_id, created_at):
    from orchestwin.knowledge.why import WHY_DOCUMENT, folder_why, normalized_why
    from orchestwin.projects.persistence.research_evidence import (
        SqlAlchemyResearchEvidenceRepository,
    )
    from orchestwin.why import build_why_document

    await session.flush()
    scope = {"project_id": plan.project_id}
    owner_scope = {**scope, "owner_user_id": owner_user_id, "version_number": 1}
    versions = {
        "brief": await SqlAlchemyProjectBriefRepository(session).get_owned_version(**owner_scope),
        "team": await SqlAlchemyTeamProposalVersionRepository(session).get_owned_version(
            **owner_scope
        ),
        "twins": await SqlAlchemyUserModelingSnapshotRepository(
            session, owner_user_id=owner_user_id
        ).current(**scope),
        "requirements": await SqlAlchemyRequirementsSpecificationRepository(
            session, owner_user_id=owner_user_id
        ).current(**scope),
        "design": await SqlAlchemyDesignPackageRepository(
            session, owner_user_id=owner_user_id
        ).current(**scope),
    }
    if any(value is None for value in versions.values()):
        raise ProjectImportError("FOLDER_WHY_MISMATCH", "stored stage missing")
    wrappers = {
        "brief": "brief",
        "team": "proposal",
        "twins": "snapshot",
        "requirements": "specification",
        "design": "package",
    }
    documents = {
        stage: {
            "id": str(version.id),
            "project_id": str(version.project_id),
            "version_number": version.version_number,
            "content_hash": version.content_hash,
            wrappers[stage]: getattr(version, wrappers[stage]).to_snapshot(),
        }
        for stage, version in versions.items()
    }
    evidence = await SqlAlchemyResearchEvidenceRepository(
        session, owner_user_id=owner_user_id
    ).dossier(plan.project_id)
    evaluations = await SqlAlchemyDesignEvaluationRepository(
        session, owner_user_id=owner_user_id
    ).list(project_id=plan.project_id, limit=2_147_483_647)
    decisions = await SqlAlchemyFindingValidationRepository(
        session, owner_user_id=owner_user_id
    ).current(project_id=plan.project_id)
    expected = build_why_document(
        project_id=str(plan.project_id),
        stages=plan_documents(plan, owner_user_id=owner_user_id, created_at=created_at),
        evidence=plan.research_evidence,
        evaluations=[
            {
                "runs": [item.to_snapshot() for item in plan.evaluations],
                "decisions": [item.to_snapshot() for item in plan.finding_decisions],
            }
        ],
    )
    actual = build_why_document(
        project_id=str(plan.project_id),
        stages=documents,
        evidence=evidence,
        evaluations=[
            {
                "runs": [item.to_snapshot() for item in evaluations],
                "decisions": [item.to_snapshot() for item in decisions],
            }
        ],
    )
    if normalized_why(expected, remap_versions=False) != normalized_why(
        actual, remap_versions=False
    ):
        raise ProjectImportError("FOLDER_WHY_MISMATCH", "stored derivation")
    if WHY_DOCUMENT in folder.files:
        original = folder_why(
            project_id=folder.project_id, documents=folder.documents, files=folder.files
        )
        if normalized_why(
            original, identities=plan.identities, hashes=plan.hashes
        ) != normalized_why(actual):
            raise ProjectImportError("FOLDER_WHY_MISMATCH", "exported derivation")


__all__ = [
    "FOLDER_DOCUMENT_INVALID",
    "PROJECT_IMPORT_REJECTED",
    "PROJECT_NAME_INVALID",
    "PROJECT_NAME_LIMIT",
    "ProjectImportError",
    "ProjectImportResult",
    "ProjectImportService",
    "archive_failure",
    "complete_folder",
    "import_display_name",
    "import_record",
    "import_source_name",
    "imported_project_mode",
    "imported_stage_versions",
    "planned_import",
    "verified_archive",
]
