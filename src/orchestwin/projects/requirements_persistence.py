from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from types import TracebackType
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.projects.requirements import (
    Requirement,
    RequirementKind,
    RequirementPriority,
    UserStory,
)
from orchestwin.projects.requirements_application import (
    RequirementsVersionAppendStatus,
)
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementsContextReference,
    RequirementSourceKind,
    RequirementSourceReference,
    UserTwinVersionReference,
)
from orchestwin.projects.requirements_quality import (
    AcceptanceCriterion,
    DefinitionOfDoneApplicability,
    DefinitionOfDoneItem,
    ProjectRisk,
    RiskImpact,
    RiskLikelihood,
    RiskReviewStatus,
    UsageScenario,
    VerificationMethod,
)
from orchestwin.projects.requirements_revision_application import (
    RequirementsDiffPersistenceStatus,
)
from orchestwin.projects.requirements_revisions import (
    REQUIREMENTS_DIFF_SCHEMA_VERSION,
    RequirementsArtifactKind,
    RequirementsDiffOperation,
    RequirementsDiffOperationKind,
    RequirementsDiffStatus,
    RequirementsSpecificationDiff,
)
from orchestwin.projects.requirements_specifications import (
    REQUIREMENTS_SPECIFICATION_SCHEMA_VERSION,
    RequirementsSpecification,
    RequirementsSpecificationVersion,
)
from orchestwin.projects.requirements_traceability import (
    build_requirements_traceability,
    summarize_requirements_coverage,
)

_UUID = postgresql.UUID(as_uuid=True)

PROJECTS = sa.table(
    "projects",
    sa.column("id", _UUID),
    sa.column("owner_user_id", _UUID),
)

SPECIFICATIONS = sa.table(
    "requirements_specification_versions",
    sa.column("id", _UUID),
    sa.column("project_id", _UUID),
    sa.column("version_number", sa.Integer()),
    sa.column("based_on_version_number", sa.Integer()),
    sa.column("schema_version", sa.Integer()),
    sa.column("content_hash", sa.String(64)),
    sa.column("specification_snapshot", postgresql.JSONB()),
    sa.column("traceability_hash", sa.String(64)),
    sa.column("traceability_snapshot", postgresql.JSONB()),
    sa.column("coverage_snapshot", postgresql.JSONB()),
    sa.column("created_by_user_id", _UUID),
    sa.column("created_at", sa.DateTime(timezone=True)),
)

DIFFS = sa.table(
    "requirements_specification_diffs",
    sa.column("id", _UUID),
    sa.column("project_id", _UUID),
    sa.column("base_version_id", _UUID),
    sa.column("base_version_number", sa.Integer()),
    sa.column("base_content_hash", sa.String(64)),
    sa.column("proposed_content_hash", sa.String(64)),
    sa.column("proposal_hash", sa.String(64)),
    sa.column("diff_snapshot", postgresql.JSONB()),
    sa.column("status", sa.String(16)),
    sa.column("created_by_user_id", _UUID),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("decided_by_user_id", _UUID),
    sa.column("decided_at", sa.DateTime(timezone=True)),
    sa.column("decision_reason", sa.Text()),
    sa.column("applied_specification_version_id", _UUID),
)


class SqlAlchemyRequirementsSpecificationRepository:
    """Append-only owner-scoped requirements specification repository."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        """Bind specification access to one authenticated owner."""
        self._session = session
        self._owner_user_id = owner_user_id

    async def current(
        self,
        *,
        project_id: UUID,
    ) -> RequirementsSpecificationVersion | None:
        """Return the latest owner-scoped specification version."""
        return await self._current(project_id=project_id, for_update=False)

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> RequirementsSpecificationVersion | None:
        """Lock and return the current specification for Gate 4."""
        if owner_user_id != self._owner_user_id:
            return None

        return await self._current(project_id=project_id, for_update=True)

    async def get(
        self,
        *,
        project_id: UUID,
        version_id: UUID,
    ) -> RequirementsSpecificationVersion | None:
        """Return one exact owner-scoped specification version."""
        statement = _owned_specification_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).where(SPECIFICATIONS.c.id == version_id)
        row = (await self._session.execute(statement)).mappings().one_or_none()

        return None if row is None else specification_version_from_record(row)

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[RequirementsSpecificationVersion, ...]:
        """Return immutable specification history in version order."""
        statement = _owned_specification_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).order_by(SPECIFICATIONS.c.version_number.asc())
        rows = (await self._session.execute(statement)).mappings().all()

        return tuple(specification_version_from_record(row) for row in rows)

    async def append(
        self,
        version: RequirementsSpecificationVersion,
    ) -> RequirementsVersionAppendStatus:
        """Append one version after locking its current project baseline."""
        if version.created_by_user_id != self._owner_user_id:
            return RequirementsVersionAppendStatus.PROJECT_NOT_FOUND

        if not await _project_is_owned(
            self._session,
            project_id=version.project_id,
            owner_user_id=self._owner_user_id,
        ):
            return RequirementsVersionAppendStatus.PROJECT_NOT_FOUND

        current = await self._current(project_id=version.project_id, for_update=True)

        if current is None:
            if version.version_number != 1 or version.based_on_version_number is not None:
                return RequirementsVersionAppendStatus.VERSION_CONFLICT
        else:
            if (
                version.version_number != current.version_number + 1
                or version.based_on_version_number != current.version_number
            ):
                return RequirementsVersionAppendStatus.VERSION_CONFLICT

            if version.content_hash == current.content_hash:
                return RequirementsVersionAppendStatus.CONTENT_CONFLICT

        try:
            await self._session.execute(
                sa.insert(SPECIFICATIONS).values(**specification_version_to_record(version))
            )
        except IntegrityError:
            return RequirementsVersionAppendStatus.VERSION_CONFLICT

        return RequirementsVersionAppendStatus.APPENDED

    async def _current(
        self,
        *,
        project_id: UUID,
        for_update: bool,
    ) -> RequirementsSpecificationVersion | None:
        """Read the latest specification with optional row locking."""
        statement = (
            _owned_specification_select(
                project_id=project_id,
                owner_user_id=self._owner_user_id,
            )
            .order_by(SPECIFICATIONS.c.version_number.desc())
            .limit(1)
        )

        if for_update:
            statement = statement.with_for_update()

        row = (await self._session.execute(statement)).mappings().one_or_none()

        return None if row is None else specification_version_from_record(row)


class SqlAlchemyRequirementsDiffRepository:
    """Owner-scoped repository for reviewable requirements diffs."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        """Bind diff access to one authenticated owner."""
        self._session = session
        self._owner_user_id = owner_user_id

    async def create(
        self,
        diff: RequirementsSpecificationDiff,
    ) -> RequirementsDiffPersistenceStatus:
        """Persist a proposed diff against an exact owned base version."""
        if diff.created_by_user_id != self._owner_user_id:
            return RequirementsDiffPersistenceStatus.PROJECT_NOT_FOUND

        if not await _project_is_owned(
            self._session,
            project_id=diff.project_id,
            owner_user_id=self._owner_user_id,
        ):
            return RequirementsDiffPersistenceStatus.PROJECT_NOT_FOUND

        if not await _base_version_exists(self._session, diff):
            return RequirementsDiffPersistenceStatus.CONTEXT_NOT_FOUND

        try:
            await self._session.execute(sa.insert(DIFFS).values(**diff_to_record(diff)))
        except IntegrityError:
            return RequirementsDiffPersistenceStatus.CONFLICT

        return RequirementsDiffPersistenceStatus.CREATED

    async def get(
        self,
        *,
        project_id: UUID,
        diff_id: UUID,
    ) -> RequirementsSpecificationDiff | None:
        """Return one exact owner-scoped requirements diff."""
        statement = _owned_diff_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).where(DIFFS.c.id == diff_id)
        row = (await self._session.execute(statement)).mappings().one_or_none()

        return None if row is None else diff_from_record(row)

    async def current_proposed(
        self,
        *,
        project_id: UUID,
        base_version_id: UUID,
    ) -> RequirementsSpecificationDiff | None:
        """Return the proposed diff for an exact base version."""
        statement = (
            _owned_diff_select(
                project_id=project_id,
                owner_user_id=self._owner_user_id,
            )
            .where(
                DIFFS.c.base_version_id == base_version_id,
                DIFFS.c.status == RequirementsDiffStatus.PROPOSED.value,
            )
            .limit(1)
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()

        return None if row is None else diff_from_record(row)

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[RequirementsSpecificationDiff, ...]:
        """Return requirements diff history in creation order."""
        statement = _owned_diff_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).order_by(DIFFS.c.created_at.asc(), DIFFS.c.id.asc())
        rows = (await self._session.execute(statement)).mappings().all()

        return tuple(diff_from_record(row) for row in rows)

    async def save_decision(
        self,
        diff: RequirementsSpecificationDiff,
    ) -> RequirementsDiffPersistenceStatus:
        """Update only decision metadata of one proposed diff."""
        if diff.status is RequirementsDiffStatus.PROPOSED:
            raise ValueError("cannot persist a decision while requirements diff is PROPOSED")

        if diff.decided_by_user_id != self._owner_user_id:
            return RequirementsDiffPersistenceStatus.CONFLICT

        statement = (
            sa.update(DIFFS)
            .where(
                DIFFS.c.id == diff.id,
                DIFFS.c.project_id == diff.project_id,
                DIFFS.c.status == RequirementsDiffStatus.PROPOSED.value,
                _owned_project_exists(
                    project_id=diff.project_id,
                    owner_user_id=self._owner_user_id,
                ),
            )
            .values(
                status=diff.status.value,
                decided_by_user_id=diff.decided_by_user_id,
                decided_at=diff.decided_at,
                decision_reason=diff.decision_reason,
                applied_specification_version_id=(diff.applied_specification_version_id),
            )
            .returning(DIFFS.c.id)
        )
        updated_id = (await self._session.execute(statement)).scalar_one_or_none()

        if updated_id is None:
            return RequirementsDiffPersistenceStatus.CONFLICT

        return RequirementsDiffPersistenceStatus.UPDATED


class SqlAlchemyRequirementsUnitOfWork:
    """SQLAlchemy transaction coordinator for requirements persistence."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        """Create owner-scoped repositories over one shared session."""
        self._session = session
        self._completed = False
        self.specifications = SqlAlchemyRequirementsSpecificationRepository(
            session,
            owner_user_id=owner_user_id,
        )
        self.diffs = SqlAlchemyRequirementsDiffRepository(
            session,
            owner_user_id=owner_user_id,
        )

    async def __aenter__(self) -> SqlAlchemyRequirementsUnitOfWork:
        """Return this transactional boundary."""
        self._completed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Rollback a transaction that was not explicitly committed."""
        del exc_type, exc_value, traceback

        if not self._completed:
            await self.rollback()

    async def commit(self) -> None:
        """Commit the shared SQLAlchemy transaction."""
        await self._session.commit()
        self._completed = True

    async def rollback(self) -> None:
        """Rollback the shared SQLAlchemy transaction."""
        await self._session.rollback()
        self._completed = True


class SqlAlchemyRequirementsUnitOfWorkFactory:
    """Create owner-scoped requirements Units of Work."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Store the shared async session factory."""
        self._session_factory = session_factory

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> SqlAlchemyRequirementsUnitOfWork:
        """Create one Unit of Work with a fresh async session."""
        return SqlAlchemyRequirementsUnitOfWork(
            self._session_factory(),
            owner_user_id=owner_user_id,
        )


def specification_version_to_record(
    version: RequirementsSpecificationVersion,
) -> dict[str, object]:
    """Convert one specification version to database values."""
    traceability = build_requirements_traceability(version)
    coverage = summarize_requirements_coverage(version)

    return {
        "id": version.id,
        "project_id": version.project_id,
        "version_number": version.version_number,
        "based_on_version_number": version.based_on_version_number,
        "schema_version": REQUIREMENTS_SPECIFICATION_SCHEMA_VERSION,
        "content_hash": version.content_hash,
        "specification_snapshot": version.specification.to_snapshot(),
        "traceability_hash": traceability.content_hash,
        "traceability_snapshot": traceability.to_snapshot(),
        "coverage_snapshot": coverage.to_snapshot(),
        "created_by_user_id": version.created_by_user_id,
        "created_at": version.created_at,
    }


def specification_version_from_record(
    record: Mapping[str, object],
) -> RequirementsSpecificationVersion:
    """Reconstruct and validate one persisted specification version."""
    schema_version = _integer(
        _required(record, "schema_version"),
        label="requirements schema version",
    )

    if schema_version != REQUIREMENTS_SPECIFICATION_SCHEMA_VERSION:
        raise ValueError("unsupported requirements specification schema")

    snapshot = _mapping(
        _required(record, "specification_snapshot"),
        label="requirements specification snapshot",
    )
    specification = specification_from_snapshot(snapshot)
    version = RequirementsSpecificationVersion(
        id=_uuid(_required(record, "id"), label="requirements version ID"),
        project_id=_uuid(
            _required(record, "project_id"),
            label="requirements project ID",
        ),
        version_number=_integer(
            _required(record, "version_number"),
            label="requirements version number",
        ),
        based_on_version_number=_optional_integer(
            record.get("based_on_version_number"),
            label="requirements base version number",
        ),
        specification=specification,
        content_hash=_string(
            _required(record, "content_hash"),
            label="requirements content hash",
        ),
        created_by_user_id=_uuid(
            _required(record, "created_by_user_id"),
            label="requirements creator ID",
        ),
        created_at=_datetime(
            _required(record, "created_at"),
            label="requirements creation timestamp",
        ),
    )
    traceability = build_requirements_traceability(version)
    coverage = summarize_requirements_coverage(version)

    if traceability.content_hash != _string(
        _required(record, "traceability_hash"),
        label="requirements traceability hash",
    ):
        raise ValueError("persisted requirements traceability hash does not match")

    if traceability.to_snapshot() != dict(
        _mapping(
            _required(record, "traceability_snapshot"),
            label="requirements traceability snapshot",
        )
    ):
        raise ValueError("persisted requirements traceability snapshot is not canonical")

    if coverage.to_snapshot() != dict(
        _mapping(
            _required(record, "coverage_snapshot"),
            label="requirements coverage snapshot",
        )
    ):
        raise ValueError("persisted requirements coverage snapshot is not canonical")

    return version


def specification_from_snapshot(
    payload: Mapping[str, object],
) -> RequirementsSpecification:
    """Reconstruct one complete canonical requirements specification."""
    if (
        _integer(
            _required(payload, "schema_version"),
            label="requirements snapshot schema version",
        )
        != REQUIREMENTS_SPECIFICATION_SCHEMA_VERSION
    ):
        raise ValueError("unsupported requirements specification snapshot")

    context = _mapping(_required(payload, "context"), label="requirements context")
    catalog = _mapping(_required(context, "catalog"), label="requirements catalog")
    specification = RequirementsSpecification(
        project_id=_uuid(
            _required(payload, "project_id"),
            label="requirements project ID",
        ),
        project_brief_reference=_context_reference_from_snapshot(
            _mapping(
                _required(context, "project_brief"),
                label="requirements Project Brief reference",
            )
        ),
        agent_team_reference=_context_reference_from_snapshot(
            _mapping(
                _required(context, "agent_team"),
                label="requirements Agent Team reference",
            )
        ),
        user_modeling_reference=_context_reference_from_snapshot(
            _mapping(
                _required(context, "user_modeling"),
                label="requirements User Modeling reference",
            )
        ),
        catalog_version=_integer(
            _required(catalog, "version"),
            label="requirements catalog version",
        ),
        catalog_content_hash=_string(
            _required(catalog, "content_hash"),
            label="requirements catalog hash",
        ),
        user_twin_references=tuple(
            _user_twin_reference_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "user_twin_references"),
                label="requirements User Twin references",
            )
        ),
        requirements=tuple(
            _requirement_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "requirements"),
                label="requirements collection",
            )
        ),
        user_stories=tuple(
            _user_story_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "user_stories"),
                label="user-story collection",
            )
        ),
        acceptance_criteria=tuple(
            _criterion_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "acceptance_criteria"),
                label="acceptance-criterion collection",
            )
        ),
        scenarios=tuple(
            _scenario_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "scenarios"),
                label="scenario collection",
            )
        ),
        risks=tuple(
            _risk_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "risks"),
                label="risk collection",
            )
        ),
        definition_of_done=tuple(
            _done_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "definition_of_done"),
                label="Definition of Done collection",
            )
        ),
    )

    if specification.to_snapshot() != dict(payload):
        raise ValueError("persisted requirements specification snapshot is not canonical")

    return specification


def diff_to_record(
    diff: RequirementsSpecificationDiff,
) -> dict[str, object]:
    """Convert one requirements diff to database values."""
    return {
        "id": diff.id,
        "project_id": diff.project_id,
        "base_version_id": diff.base_version_id,
        "base_version_number": diff.base_version_number,
        "base_content_hash": diff.base_content_hash,
        "proposed_content_hash": diff.proposed_specification.content_hash,
        "proposal_hash": diff.proposal_hash,
        "diff_snapshot": diff.proposal_snapshot(),
        "status": diff.status.value,
        "created_by_user_id": diff.created_by_user_id,
        "created_at": diff.created_at,
        "decided_by_user_id": diff.decided_by_user_id,
        "decided_at": diff.decided_at,
        "decision_reason": diff.decision_reason,
        "applied_specification_version_id": diff.applied_specification_version_id,
    }


def diff_from_record(
    record: Mapping[str, object],
) -> RequirementsSpecificationDiff:
    """Reconstruct and validate one persisted requirements diff."""
    payload = _mapping(
        _required(record, "diff_snapshot"),
        label="requirements diff snapshot",
    )

    if (
        _integer(
            _required(payload, "schema_version"),
            label="requirements diff schema version",
        )
        != REQUIREMENTS_DIFF_SCHEMA_VERSION
    ):
        raise ValueError("unsupported requirements diff schema")

    base = _mapping(_required(payload, "base_version"), label="requirements base version")
    proposed = specification_from_snapshot(
        _mapping(
            _required(payload, "proposed_specification"),
            label="proposed requirements specification",
        )
    )
    operations = tuple(
        _operation_from_snapshot(item)
        for item in _mapping_sequence(
            _required(payload, "operations"),
            label="requirements diff operations",
        )
    )
    diff = RequirementsSpecificationDiff(
        id=_uuid(_required(payload, "id"), label="requirements diff ID"),
        project_id=_uuid(
            _required(payload, "project_id"),
            label="requirements diff project ID",
        ),
        base_version_id=_uuid(
            _required(base, "id"),
            label="requirements base version ID",
        ),
        base_version_number=_integer(
            _required(base, "version_number"),
            label="requirements base version number",
        ),
        base_content_hash=_string(
            _required(base, "content_hash"),
            label="requirements base content hash",
        ),
        proposed_specification=proposed,
        operations=operations,
        created_by_user_id=_uuid(
            _required(payload, "created_by_user_id"),
            label="requirements diff creator ID",
        ),
        created_at=_datetime(
            _required(payload, "created_at"),
            label="requirements diff creation timestamp",
        ),
        status=RequirementsDiffStatus(
            _string(_required(record, "status"), label="requirements diff status")
        ),
        decided_by_user_id=_optional_uuid(
            record.get("decided_by_user_id"),
            label="requirements diff decision actor",
        ),
        decided_at=_optional_datetime(
            record.get("decided_at"),
            label="requirements diff decision timestamp",
        ),
        decision_reason=_optional_string(
            record.get("decision_reason"),
            label="requirements diff decision reason",
        ),
        applied_specification_version_id=_optional_uuid(
            record.get("applied_specification_version_id"),
            label="applied requirements version ID",
        ),
    )

    if diff.proposed_specification.content_hash != _string(
        _required(record, "proposed_content_hash"),
        label="proposed requirements content hash",
    ):
        raise ValueError("persisted proposed requirements hash does not match")

    if diff.proposal_hash != _string(
        _required(record, "proposal_hash"),
        label="requirements diff proposal hash",
    ):
        raise ValueError("persisted requirements diff proposal hash does not match")

    if diff.proposal_snapshot() != dict(payload):
        raise ValueError("persisted requirements diff snapshot is not canonical")

    return diff


def _context_reference_from_snapshot(
    payload: Mapping[str, object],
) -> RequirementsContextReference:
    return RequirementsContextReference(
        kind=RequirementsContextKind(
            _string(_required(payload, "kind"), label="requirements context kind")
        ),
        artifact_id=_uuid(
            _required(payload, "artifact_id"),
            label="requirements context artifact ID",
        ),
        version_number=_integer(
            _required(payload, "version_number"),
            label="requirements context version number",
        ),
        content_hash=_string(
            _required(payload, "content_hash"),
            label="requirements context content hash",
        ),
    )


def _source_from_snapshot(
    payload: Mapping[str, object],
) -> RequirementSourceReference:
    return RequirementSourceReference(
        kind=RequirementSourceKind(
            _string(_required(payload, "kind"), label="requirement source kind")
        ),
        source_id=_string(
            _required(payload, "source_id"),
            label="requirement source ID",
        ),
        source_version=_optional_integer(
            payload.get("source_version"),
            label="requirement source version",
        ),
        content_hash=_optional_string(
            payload.get("content_hash"),
            label="requirement source hash",
        ),
        locator=_optional_string(
            payload.get("locator"),
            label="requirement source locator",
        ),
    )


def _user_twin_reference_from_snapshot(
    payload: Mapping[str, object],
) -> UserTwinVersionReference:
    return UserTwinVersionReference(
        twin_id=_uuid(_required(payload, "twin_id"), label="User Twin ID"),
        version_number=_integer(
            _required(payload, "version_number"),
            label="User Twin version number",
        ),
        content_hash=_string(
            _required(payload, "content_hash"),
            label="User Twin content hash",
        ),
        name=_string(_required(payload, "name"), label="User Twin name"),
    )


def _requirement_from_snapshot(payload: Mapping[str, object]) -> Requirement:
    return Requirement(
        id=_uuid(_required(payload, "id"), label="requirement ID"),
        code=_string(_required(payload, "code"), label="requirement code"),
        title=_string(_required(payload, "title"), label="requirement title"),
        statement=_string(
            _required(payload, "statement"),
            label="requirement statement",
        ),
        kind=RequirementKind(_string(_required(payload, "kind"), label="requirement kind")),
        priority=RequirementPriority(
            _string(_required(payload, "priority"), label="requirement priority")
        ),
        sources=tuple(
            _source_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "sources"),
                label="requirement sources",
            )
        ),
        user_twin_references=tuple(
            _user_twin_reference_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "user_twin_references"),
                label="requirement User Twin references",
            )
        ),
    )


def _user_story_from_snapshot(payload: Mapping[str, object]) -> UserStory:
    return UserStory(
        id=_uuid(_required(payload, "id"), label="user-story ID"),
        code=_string(_required(payload, "code"), label="user-story code"),
        user_twin_reference=_user_twin_reference_from_snapshot(
            _mapping(
                _required(payload, "user_twin_reference"),
                label="user-story User Twin reference",
            )
        ),
        goal=_string(_required(payload, "goal"), label="user-story goal"),
        benefit=_string(_required(payload, "benefit"), label="user-story benefit"),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="user-story requirement IDs",
        ),
    )


def _criterion_from_snapshot(payload: Mapping[str, object]) -> AcceptanceCriterion:
    return AcceptanceCriterion(
        id=_uuid(_required(payload, "id"), label="acceptance-criterion ID"),
        code=_string(
            _required(payload, "code"),
            label="acceptance-criterion code",
        ),
        statement=_string(
            _required(payload, "statement"),
            label="acceptance-criterion statement",
        ),
        verification_method=VerificationMethod(
            _string(
                _required(payload, "verification_method"),
                label="acceptance-criterion verification method",
            )
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="acceptance-criterion requirement IDs",
        ),
        user_story_ids=_uuid_sequence(
            _required(payload, "user_story_ids"),
            label="acceptance-criterion user-story IDs",
        ),
    )


def _scenario_from_snapshot(payload: Mapping[str, object]) -> UsageScenario:
    return UsageScenario(
        id=_uuid(_required(payload, "id"), label="scenario ID"),
        code=_string(_required(payload, "code"), label="scenario code"),
        title=_string(_required(payload, "title"), label="scenario title"),
        actor=_user_twin_reference_from_snapshot(
            _mapping(_required(payload, "actor"), label="scenario actor")
        ),
        preconditions=_string_sequence(
            _required(payload, "preconditions"),
            label="scenario preconditions",
        ),
        trigger=_string(_required(payload, "trigger"), label="scenario trigger"),
        steps=_string_sequence(_required(payload, "steps"), label="scenario steps"),
        expected_outcome=_string(
            _required(payload, "expected_outcome"),
            label="scenario expected outcome",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="scenario requirement IDs",
        ),
        acceptance_criterion_ids=_uuid_sequence(
            _required(payload, "acceptance_criterion_ids"),
            label="scenario acceptance-criterion IDs",
        ),
    )


def _risk_from_snapshot(payload: Mapping[str, object]) -> ProjectRisk:
    return ProjectRisk(
        id=_uuid(_required(payload, "id"), label="risk ID"),
        code=_string(_required(payload, "code"), label="risk code"),
        summary=_string(_required(payload, "summary"), label="risk summary"),
        likelihood=RiskLikelihood(
            _string(_required(payload, "likelihood"), label="risk likelihood")
        ),
        impact=RiskImpact(_string(_required(payload, "impact"), label="risk impact")),
        mitigation=_string(
            _required(payload, "mitigation"),
            label="risk mitigation",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="risk requirement IDs",
        ),
        sources=tuple(
            _source_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "sources"),
                label="risk sources",
            )
        ),
        review_status=RiskReviewStatus(
            _string(_required(payload, "review_status"), label="risk review status")
        ),
    )


def _done_from_snapshot(payload: Mapping[str, object]) -> DefinitionOfDoneItem:
    return DefinitionOfDoneItem(
        id=_uuid(_required(payload, "id"), label="Definition of Done ID"),
        code=_string(
            _required(payload, "code"),
            label="Definition of Done code",
        ),
        statement=_string(
            _required(payload, "statement"),
            label="Definition of Done statement",
        ),
        verification_method=VerificationMethod(
            _string(
                _required(payload, "verification_method"),
                label="Definition of Done verification method",
            )
        ),
        applicability=DefinitionOfDoneApplicability(
            _string(
                _required(payload, "applicability"),
                label="Definition of Done applicability",
            )
        ),
        condition=_optional_string(
            payload.get("condition"),
            label="Definition of Done condition",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="Definition of Done requirement IDs",
        ),
    )


def _operation_from_snapshot(
    payload: Mapping[str, object],
) -> RequirementsDiffOperation:
    kind = RequirementsArtifactKind(
        _string(_required(payload, "artifact_kind"), label="diff artifact kind")
    )
    before_payload = payload.get("before")
    after_payload = payload.get("after")

    return RequirementsDiffOperation(
        artifact_kind=kind,
        operation=RequirementsDiffOperationKind(
            _string(_required(payload, "operation"), label="diff operation kind")
        ),
        artifact_id=_uuid(
            _required(payload, "artifact_id"),
            label="diff artifact ID",
        ),
        before=(
            None
            if before_payload is None
            else _artifact_from_snapshot(
                kind,
                _mapping(before_payload, label="diff before artifact"),
            )
        ),
        after=(
            None
            if after_payload is None
            else _artifact_from_snapshot(
                kind,
                _mapping(after_payload, label="diff after artifact"),
            )
        ),
    )


def _artifact_from_snapshot(
    kind: RequirementsArtifactKind,
    payload: Mapping[str, object],
):
    if kind is RequirementsArtifactKind.REQUIREMENT:
        return _requirement_from_snapshot(payload)

    if kind is RequirementsArtifactKind.USER_STORY:
        return _user_story_from_snapshot(payload)

    if kind is RequirementsArtifactKind.ACCEPTANCE_CRITERION:
        return _criterion_from_snapshot(payload)

    if kind is RequirementsArtifactKind.SCENARIO:
        return _scenario_from_snapshot(payload)

    if kind is RequirementsArtifactKind.RISK:
        return _risk_from_snapshot(payload)

    return _done_from_snapshot(payload)


def _owned_specification_select(
    *,
    project_id: UUID,
    owner_user_id: UUID,
):
    return sa.select(SPECIFICATIONS).where(
        SPECIFICATIONS.c.project_id == project_id,
        _owned_project_exists(
            project_id=project_id,
            owner_user_id=owner_user_id,
        ),
    )


def _owned_diff_select(
    *,
    project_id: UUID,
    owner_user_id: UUID,
):
    return sa.select(DIFFS).where(
        DIFFS.c.project_id == project_id,
        _owned_project_exists(
            project_id=project_id,
            owner_user_id=owner_user_id,
        ),
    )


def _owned_project_exists(
    *,
    project_id: UUID,
    owner_user_id: UUID,
):
    return sa.exists(
        sa.select(sa.literal(1)).where(
            PROJECTS.c.id == project_id,
            PROJECTS.c.owner_user_id == owner_user_id,
        )
    )


async def _project_is_owned(
    session: AsyncSession,
    *,
    project_id: UUID,
    owner_user_id: UUID,
) -> bool:
    statement = sa.select(
        _owned_project_exists(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )
    )

    return bool((await session.execute(statement)).scalar_one())


async def _base_version_exists(
    session: AsyncSession,
    diff: RequirementsSpecificationDiff,
) -> bool:
    statement = sa.select(
        sa.exists(
            sa.select(sa.literal(1)).where(
                SPECIFICATIONS.c.id == diff.base_version_id,
                SPECIFICATIONS.c.project_id == diff.project_id,
                SPECIFICATIONS.c.version_number == diff.base_version_number,
                SPECIFICATIONS.c.content_hash == diff.base_content_hash,
            )
        )
    )

    return bool((await session.execute(statement)).scalar_one())


def _required(values: Mapping[str, object], key: str) -> object:
    if key not in values:
        raise ValueError(f"missing persisted requirements field: {key}")

    return values[key]


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")

    return value


def _sequence(value: object, *, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError(f"{label} must be a sequence")

    return value


def _mapping_sequence(
    value: object,
    *,
    label: str,
) -> tuple[Mapping[str, object], ...]:
    return tuple(_mapping(item, label=label) for item in _sequence(value, label=label))


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")

    return value


def _optional_string(value: object, *, label: str) -> str | None:
    return None if value is None else _string(value, label=label)


def _integer(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")

    return value


def _optional_integer(value: object, *, label: str) -> int | None:
    return None if value is None else _integer(value, label=label)


def _uuid(value: object, *, label: str) -> UUID:
    if isinstance(value, UUID):
        return value

    if isinstance(value, str):
        return UUID(value)

    raise ValueError(f"{label} must be a UUID")


def _optional_uuid(value: object, *, label: str) -> UUID | None:
    return None if value is None else _uuid(value, label=label)


def _datetime(value: object, *, label: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value)
    else:
        raise ValueError(f"{label} must be a timestamp")

    if result.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")

    return result


def _optional_datetime(value: object, *, label: str) -> datetime | None:
    return None if value is None else _datetime(value, label=label)


def _uuid_sequence(value: object, *, label: str) -> tuple[UUID, ...]:
    return tuple(_uuid(item, label=label) for item in _sequence(value, label=label))


def _string_sequence(value: object, *, label: str) -> tuple[str, ...]:
    return tuple(_string(item, label=label) for item in _sequence(value, label=label))


__all__ = [
    "SqlAlchemyRequirementsDiffRepository",
    "SqlAlchemyRequirementsSpecificationRepository",
    "SqlAlchemyRequirementsUnitOfWork",
    "SqlAlchemyRequirementsUnitOfWorkFactory",
    "diff_from_record",
    "diff_to_record",
    "specification_from_snapshot",
    "specification_version_from_record",
    "specification_version_to_record",
]
