from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from orchestwin.twins.application import (
    GroundedSnapshotGenerationResult,
    UserModelingApplicationIssueCode,
    UserModelingApplicationStatus,
    _governance_issue,
)
from orchestwin.twins.epistemics import (
    EvidenceReference,
    EvidenceSourceKind,
    ObservationProvenance,
    ProfileObservation,
)
from orchestwin.twins.limits import MAX_USER_TWINS, MIN_USER_TWINS
from orchestwin.twins.persistence.repositories import VersionAppendStatus
from orchestwin.twins.representation import active_archetype
from orchestwin.twins.user_twins import (
    ConfirmedPersonaReference,
    UserModelingSnapshotVersion,
    UserTwinField,
    UserTwinLifecycleStatus,
    UserTwinProfile,
    UserTwinProfileVersion,
    create_user_modeling_snapshot,
)


@dataclass(frozen=True, slots=True)
class OwnerTwinInput:
    persona_id: UUID
    name: str
    observations: tuple[ProfileObservation, ...]

    def __post_init__(self) -> None:
        keys = tuple(value.observation_key for value in self.observations)
        if len(keys) != len(set(keys)):
            raise ValueError("OWNER_TWIN_DUPLICATE_FIELD")
        if set(keys) - {field.observation_key for field in UserTwinField}:
            raise ValueError("OWNER_TWIN_UNKNOWN_FIELD")


def owner_observations(data: OwnerTwinInput, *, owner_user_id) -> tuple[ProfileObservation, ...]:
    values = {observation.observation_key: observation for observation in data.observations}
    ordered = []
    for field in UserTwinField:
        observation = values.get(field.observation_key)
        if observation is None:
            continue
        provenance = ObservationProvenance.from_references(
            dict.fromkeys(
                (
                    *observation.provenance.references,
                    EvidenceReference(
                        source_kind=EvidenceSourceKind.OWNER_INPUT,
                        source_id="owner-provided-profile",
                        locator=f"{owner_user_id}/{field.observation_key}",
                    ),
                )
            )
        )
        ordered.append(replace(observation, provenance=provenance))
    return tuple(ordered)


class OwnerUserModelingService:
    def __init__(self, *, governance_port, uow_factory, uuid_factory=uuid4, clock=None) -> None:
        self._governance = governance_port
        self._uow_factory = uow_factory
        self._uuid_factory = uuid_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def create(
        self, *, owner_user_id, project_id, profiles: tuple[OwnerTwinInput, ...]
    ) -> GroundedSnapshotGenerationResult:
        context = await self._governance.load_current(
            owner_user_id=owner_user_id, project_id=project_id
        )
        issue = _governance_issue(context)
        if issue is not None:
            return self._rejected(issue)
        if context is None:
            raise RuntimeError("ready User Modeling context is missing")
        persona_ids = tuple(profile.persona_id for profile in profiles)
        if not MIN_USER_TWINS <= len(profiles) <= MAX_USER_TWINS or len(persona_ids) != len(
            set(persona_ids)
        ):
            return self._rejected(UserModelingApplicationIssueCode.INVALID_PROPOSAL)
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            if not await unit.lock_project(project_id=project_id):
                return self._rejected(UserModelingApplicationIssueCode.PROJECT_NOT_FOUND)
            if await unit.has_pending_revision(project_id=project_id):
                return self._rejected(UserModelingApplicationIssueCode.USER_TWIN_REVISION_PENDING)
            if await unit.snapshots.current(project_id=project_id) is not None:
                return self._rejected(UserModelingApplicationIssueCode.SNAPSHOT_ALREADY_EXISTS)
            current = await self._governance.load_current(
                owner_user_id=owner_user_id, project_id=project_id
            )
            if (
                current is None
                or _governance_issue(current) is not None
                or current.fingerprint != context.fingerprint
            ):
                return self._rejected(UserModelingApplicationIssueCode.CONTEXT_CHANGED)
            personas = tuple(
                persona
                for persona in await unit.personas.list_current(project_id=project_id)
                if active_archetype(persona)
            )
            if not personas:
                return self._rejected(UserModelingApplicationIssueCode.PERSONAS_REQUIRED)
            if any(not persona.profile.ready_for_twin_creation for persona in personas):
                return self._rejected(
                    UserModelingApplicationIssueCode.PERSONA_CONFIRMATION_REQUIRED
                )
            by_id = {persona.persona_id: persona for persona in personas}
            if set(persona_ids) != set(by_id):
                return self._rejected(UserModelingApplicationIssueCode.INVALID_PROPOSAL)
            created_at = self._clock()
            try:
                twins = tuple(
                    UserTwinProfileVersion(
                        id=self._uuid_factory(),
                        project_id=project_id,
                        twin_id=self._uuid_factory(),
                        version_number=1,
                        profile=(
                            profile := UserTwinProfile(
                                name=data.name,
                                persona_reference=ConfirmedPersonaReference.from_version(
                                    by_id[data.persona_id]
                                ),
                                project_brief_reference=context.brief_reference,
                                agent_team_reference=context.team_reference,
                                catalog_version=context.catalog_version,
                                catalog_content_hash=context.catalog_content_hash,
                                validation_status=UserTwinLifecycleStatus.PROJECT_GROUNDED_UT,
                                observations=owner_observations(data, owner_user_id=owner_user_id),
                            )
                        ),
                        content_hash=profile.content_hash,
                        created_by_user_id=owner_user_id,
                        created_at=created_at,
                    )
                    for data in profiles
                )
                snapshot = create_user_modeling_snapshot(
                    project_id=project_id,
                    project_brief_reference=context.brief_reference,
                    agent_team_reference=context.team_reference,
                    catalog_version=context.catalog_version,
                    catalog_content_hash=context.catalog_content_hash,
                    persona_versions=personas,
                    twin_versions=twins,
                )
            except (TypeError, ValueError):
                return self._rejected(UserModelingApplicationIssueCode.INVALID_PROPOSAL)
            for twin in twins:
                status = await unit.twins.append(twin)
                if status is not VersionAppendStatus.APPENDED:
                    return self._rejected(UserModelingApplicationIssueCode.PERSISTENCE_REJECTED)
            version = UserModelingSnapshotVersion(
                id=self._uuid_factory(),
                project_id=project_id,
                version_number=1,
                based_on_version_number=None,
                snapshot=snapshot,
                content_hash=snapshot.content_hash,
                created_by_user_id=owner_user_id,
                created_at=created_at,
            )
            if await unit.snapshots.append(version) is not VersionAppendStatus.APPENDED:
                return self._rejected(UserModelingApplicationIssueCode.PERSISTENCE_REJECTED)
            await unit.commit()
        return GroundedSnapshotGenerationResult(
            status=UserModelingApplicationStatus.CREATED,
            snapshot_version=version,
            twin_versions=twins,
        )

    @staticmethod
    def _rejected(issue) -> GroundedSnapshotGenerationResult:
        return GroundedSnapshotGenerationResult(
            status=UserModelingApplicationStatus.REJECTED, issue=issue
        )
