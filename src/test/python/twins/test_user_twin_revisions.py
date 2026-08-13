"""Tests for owner-reviewed immutable User Twin profile revisions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
    ObservationValue,
    ProfileObservation,
)
from orchestwin.twins.persistence.repositories import (
    VersionAppendStatus,
)
from orchestwin.twins.personas import (
    PersonaField,
    PersonaProfileVersion,
    create_owner_provided_persona,
)
from orchestwin.twins.revision_application import (
    LocalUserTwinProfileRevisionService,
    ProfileRevisionApplicationIssueCode,
    ProfileRevisionApplicationStatus,
    ProfileRevisionDecision,
)
from orchestwin.twins.revision_persistence import (
    DiffPersistenceStatus,
)
from orchestwin.twins.revisions import (
    ProfileDiffProposalIssueCode,
    ProfileDiffProposalStatus,
    UserTwinProfileDiff,
    UserTwinProfileDiffStatus,
    propose_user_twin_profile_diff,
)
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinField,
    UserTwinLifecycleStatus,
    UserTwinProfileVersion,
    VersionedArtifactReference,
    create_project_grounded_user_twin,
    create_user_modeling_snapshot,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
PERSONA_ID = UUID("00000000-0000-4000-8000-000000000020")
PERSONA_VERSION_ID = UUID("00000000-0000-4000-8000-000000000021")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000030")
TWIN_VERSION_ID = UUID("00000000-0000-4000-8000-000000000031")
SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000000040")

CREATED_AT = datetime(
    2026,
    8,
    13,
    12,
    0,
    tzinfo=UTC,
)
DECIDED_AT = datetime(
    2026,
    8,
    13,
    13,
    0,
    tzinfo=UTC,
)

BRIEF_REFERENCE = VersionedArtifactReference(
    artifact_id=UUID("00000000-0000-4000-8000-000000000050"),
    version_number=3,
    content_hash="b" * 64,
)

TEAM_REFERENCE = VersionedArtifactReference(
    artifact_id=UUID("00000000-0000-4000-8000-000000000060"),
    version_number=2,
    content_hash="c" * 64,
)

CATALOG_HASH = "d" * 64

_LIST_FIELDS = frozenset(
    {
        UserTwinField.EXPERTISE,
        UserTwinField.GOALS,
        UserTwinField.RECURRING_TASKS,
        UserTwinField.INFORMATION_NEEDS,
        UserTwinField.DECISION_CRITERIA,
        UserTwinField.PREFERRED_VOCABULARY,
        UserTwinField.FRUSTRATIONS,
        UserTwinField.PAIN_POINTS,
        UserTwinField.TRUST_CONCERNS,
        UserTwinField.ACCESSIBILITY_NEEDS,
        UserTwinField.OPERATIONAL_CONSTRAINTS,
        UserTwinField.ASSUMPTIONS,
    }
)


def project_evidence(
    locator: str,
) -> EvidenceReference:
    """Create Project Brief evidence."""
    return EvidenceReference(
        source_kind=(EvidenceSourceKind.PROJECT_BRIEF),
        source_id=str(BRIEF_REFERENCE.artifact_id),
        source_version=(BRIEF_REFERENCE.version_number),
        content_hash=(BRIEF_REFERENCE.content_hash),
        locator=locator,
    )


def owner_evidence(
    field: UserTwinField,
) -> EvidenceReference:
    """Create explicit owner-input evidence."""
    return EvidenceReference(
        source_kind=(EvidenceSourceKind.OWNER_INPUT),
        source_id=str(OWNER_ID),
        source_version=1,
        locator=field.observation_key,
        summary=("Owner supplied this profile revision."),
    )


def human_review_evidence(
    field: UserTwinField,
) -> EvidenceReference:
    """Create explicit human-review evidence."""
    return EvidenceReference(
        source_kind=(EvidenceSourceKind.HUMAN_REVIEW),
        source_id=str(OWNER_ID),
        source_version=1,
        locator=field.observation_key,
        summary=("Owner reviewed and validated this observation."),
    )


def base_observation(
    key: str,
    value: ObservationValue,
) -> ProfileObservation:
    """Create one user-provided base observation."""
    return ProfileObservation(
        observation_key=key,
        value=value,
        epistemic_status=(EpistemicStatus.USER_PROVIDED),
        confidence=ConfidenceScore(1.0),
        provenance=(ObservationProvenance.from_references((project_evidence(key),))),
        human_validation=(HumanValidationRequirement.NOT_REQUIRED),
    )


def owner_replacement(
    field: UserTwinField,
    value: ObservationValue,
) -> ProfileObservation:
    """Create one valid owner-supplied replacement."""
    return ProfileObservation(
        observation_key=(field.observation_key),
        value=value,
        epistemic_status=(EpistemicStatus.USER_PROVIDED),
        confidence=ConfidenceScore(1.0),
        provenance=(ObservationProvenance.from_references((owner_evidence(field),))),
        human_validation=(HumanValidationRequirement.NOT_REQUIRED),
    )


def human_validated_replacement(
    field: UserTwinField,
    value: ObservationValue,
) -> ProfileObservation:
    """Create one owner-reviewed replacement."""
    return ProfileObservation(
        observation_key=(field.observation_key),
        value=value,
        epistemic_status=(EpistemicStatus.HUMAN_VALIDATED),
        confidence=ConfidenceScore(0.9),
        provenance=(ObservationProvenance.from_references((human_review_evidence(field),))),
        human_validation=(HumanValidationRequirement.NOT_REQUIRED),
    )


def persona_version() -> PersonaProfileVersion:
    """Create one confirmed persona."""
    profile = create_owner_provided_persona(
        name="Hotel Receptionist",
        observations=(
            base_observation(
                PersonaField.ROLE.observation_key,
                ObservationValue.from_text("Hotel receptionist"),
            ),
            base_observation(
                PersonaField.SUMMARY.observation_key,
                ObservationValue.from_text("Front-desk staff."),
            ),
            base_observation(
                PersonaField.GOALS.observation_key,
                ObservationValue.from_items(("Serve guests efficiently",)),
            ),
            base_observation(
                PersonaField.CONTEXT_OF_USE.observation_key,
                ObservationValue.from_text("Hotel front desk"),
            ),
        ),
    )

    return PersonaProfileVersion(
        id=PERSONA_VERSION_ID,
        project_id=PROJECT_ID,
        persona_id=PERSONA_ID,
        version_number=1,
        profile=profile,
        content_hash=profile.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def twin_observations() -> tuple[
    ProfileObservation,
    ...,
]:
    """Create every required User Twin observation."""
    observations: list[ProfileObservation] = []

    for field in UserTwinField:
        if field is UserTwinField.AGE_RANGE:
            continue

        if field is UserTwinField.ROLE:
            value = ObservationValue.from_text("Hotel receptionist")
        elif field in _LIST_FIELDS:
            value = ObservationValue.from_items((f"Known {field.value}",))
        else:
            value = ObservationValue.from_text(f"Known {field.value}")

        observations.append(
            base_observation(
                field.observation_key,
                value,
            )
        )

    return tuple(observations)


def base_snapshot_version() -> UserModelingSnapshotVersion:
    """Create one project-grounded authoritative snapshot."""
    persona = persona_version()

    twin_profile = create_project_grounded_user_twin(
        name="Receptionist Twin",
        persona_version=persona,
        project_brief_reference=(BRIEF_REFERENCE),
        agent_team_reference=(TEAM_REFERENCE),
        catalog_version=1,
        catalog_content_hash=(CATALOG_HASH),
        observations=(twin_observations()),
    )

    twin = UserTwinProfileVersion(
        id=TWIN_VERSION_ID,
        project_id=PROJECT_ID,
        twin_id=TWIN_ID,
        version_number=1,
        profile=twin_profile,
        content_hash=(twin_profile.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )

    snapshot = create_user_modeling_snapshot(
        project_id=PROJECT_ID,
        project_brief_reference=(BRIEF_REFERENCE),
        agent_team_reference=(TEAM_REFERENCE),
        catalog_version=1,
        catalog_content_hash=(CATALOG_HASH),
        persona_versions=(persona,),
        twin_versions=(twin,),
    )

    return UserModelingSnapshotVersion(
        id=SNAPSHOT_ID,
        project_id=PROJECT_ID,
        version_number=1,
        snapshot=snapshot,
        content_hash=(snapshot.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def test_profile_diff_records_exact_before_and_after_state() -> None:
    """Represent a profile change explicitly rather than mutating the twin."""
    base = base_snapshot_version()

    replacement = owner_replacement(
        UserTwinField.GOALS,
        ObservationValue.from_items(
            (
                "Serve guests efficiently",
                "Reduce booking errors",
            )
        ),
    )

    result = propose_user_twin_profile_diff(
        base_snapshot_version=base,
        twin_id=TWIN_ID,
        replacements={UserTwinField.GOALS: (replacement)},
        diff_id=UUID(int=1000),
        created_by_user_id=OWNER_ID,
        created_at=DECIDED_AT,
    )

    assert result.status is (ProfileDiffProposalStatus.CREATED)
    assert result.diff is not None

    operation = result.diff.operations[0]

    assert operation.field is UserTwinField.GOALS
    assert operation.before is not None
    assert operation.after == replacement

    assert base.version_number == 1


def test_owner_revision_rejects_model_inference_as_new_owner_fact() -> None:
    """Do not relabel model-generated knowledge through owner revision."""
    base = base_snapshot_version()

    invalid = ProfileObservation(
        observation_key=(UserTwinField.GOALS.observation_key),
        value=(ObservationValue.from_items(("Invented goal",))),
        epistemic_status=(EpistemicStatus.MODEL_INFERRED),
        confidence=ConfidenceScore(0.5),
        provenance=(
            ObservationProvenance.from_references(
                (
                    EvidenceReference(
                        source_kind=(EvidenceSourceKind.MODEL_OUTPUT),
                        source_id="model",
                    ),
                )
            )
        ),
        human_validation=(HumanValidationRequirement.REQUIRED),
        rationale="Model suggestion.",
    )

    result = propose_user_twin_profile_diff(
        base_snapshot_version=base,
        twin_id=TWIN_ID,
        replacements={UserTwinField.GOALS: invalid},
        diff_id=UUID(int=1001),
        created_by_user_id=OWNER_ID,
        created_at=DECIDED_AT,
    )

    assert result.status is (ProfileDiffProposalStatus.REJECTED)
    assert result.issue is (ProfileDiffProposalIssueCode.INVALID_REPLACEMENT)


class MemoryDiffRepository:
    """Minimal in-memory profile-diff persistence."""

    def __init__(self) -> None:
        """Create empty diff storage."""
        self.values: dict[
            UUID,
            UserTwinProfileDiff,
        ] = {}

    async def create(
        self,
        diff: UserTwinProfileDiff,
    ) -> DiffPersistenceStatus:
        """Persist one proposed diff."""
        self.values[diff.id] = diff
        return DiffPersistenceStatus.CREATED

    async def get(
        self,
        *,
        project_id: UUID,
        diff_id: UUID,
    ) -> UserTwinProfileDiff | None:
        """Read one diff."""
        value = self.values.get(diff_id)

        if value is None or value.project_id != project_id:
            return None

        return value

    async def current_proposed(
        self,
        *,
        project_id: UUID,
        base_snapshot_version_id: UUID,
        twin_id: UUID,
    ) -> UserTwinProfileDiff | None:
        """Read a pending diff for an exact base snapshot."""
        for diff in self.values.values():
            if (
                diff.project_id == project_id
                and diff.base_snapshot_version_id == base_snapshot_version_id
                and diff.twin_id == twin_id
                and diff.status is UserTwinProfileDiffStatus.PROPOSED
            ):
                return diff

        return None

    async def history(
        self,
        *,
        project_id: UUID,
        twin_id: UUID,
    ) -> tuple[
        UserTwinProfileDiff,
        ...,
    ]:
        """Return matching diff history."""
        return tuple(
            diff
            for diff in self.values.values()
            if (diff.project_id == project_id and diff.twin_id == twin_id)
        )

    async def save_decision(
        self,
        diff: UserTwinProfileDiff,
    ) -> DiffPersistenceStatus:
        """Persist decision metadata."""
        self.values[diff.id] = diff
        return DiffPersistenceStatus.UPDATED


class MemorySnapshotRepository:
    """Minimal snapshot repository."""

    def __init__(
        self,
        initial: UserModelingSnapshotVersion,
    ) -> None:
        """Seed one snapshot."""
        self.values = [initial]

    async def current(
        self,
        *,
        project_id: UUID,
    ) -> UserModelingSnapshotVersion | None:
        """Return latest project snapshot."""
        matching = [version for version in self.values if version.project_id == project_id]

        if not matching:
            return None

        return max(
            matching,
            key=lambda version: version.version_number,
        )

    async def append(
        self,
        version: UserModelingSnapshotVersion,
    ) -> VersionAppendStatus:
        """Append snapshot."""
        self.values.append(version)
        return VersionAppendStatus.APPENDED


class MemoryTwinRepository:
    """Minimal User Twin repository."""

    def __init__(
        self,
        initial: UserTwinProfileVersion,
    ) -> None:
        """Seed one User Twin."""
        self.values = [initial]

    async def append(
        self,
        version: UserTwinProfileVersion,
    ) -> VersionAppendStatus:
        """Append a twin revision."""
        self.values.append(version)
        return VersionAppendStatus.APPENDED


class DummyPersonaRepository:
    """Unused C10 persona repository placeholder."""


class MemoryUow:
    """Minimal User Modeling UoW for revision tests."""

    def __init__(
        self,
        *,
        snapshots: MemorySnapshotRepository,
        twins: MemoryTwinRepository,
        diffs: MemoryDiffRepository,
    ) -> None:
        """Store shared repositories."""
        self.snapshots = snapshots
        self.twins = twins
        self.diffs = diffs
        self.personas = DummyPersonaRepository()
        self._completed = False

    async def __aenter__(
        self,
    ) -> MemoryUow:
        """Enter fake transaction."""
        self._completed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        """Leave fake transaction."""
        del exc_type
        del exc_value
        del traceback

    async def commit(self) -> None:
        """Mark fake transaction committed."""
        self._completed = True

    async def rollback(self) -> None:
        """Mark fake transaction rolled back."""
        self._completed = True


class MemoryUowFactory:
    """Reuse the same in-memory repositories across UoWs."""

    def __init__(
        self,
        base: UserModelingSnapshotVersion,
    ) -> None:
        """Seed repositories."""
        self.snapshots = MemorySnapshotRepository(base)
        self.twins = MemoryTwinRepository(base.snapshot.twin_versions[0])
        self.diffs = MemoryDiffRepository()

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> MemoryUow:
        """Create owner-scoped fake UoW."""
        assert owner_user_id == OWNER_ID

        return MemoryUow(
            snapshots=self.snapshots,
            twins=self.twins,
            diffs=self.diffs,
        )


class DeterministicUuidFactory:
    """Return deterministic UUIDs."""

    def __init__(self) -> None:
        """Initialize sequence."""
        self.next_value = 10_000

    def __call__(self) -> UUID:
        """Return next UUID."""
        value = UUID(int=self.next_value)
        self.next_value += 1
        return value


def revision_clock() -> datetime:
    """Return deterministic revision time."""
    return DECIDED_AT


def test_owner_approval_creates_new_twin_and_snapshot_versions() -> None:
    """Approve diff atomically into immutable User Twin/snapshot revisions."""
    base = base_snapshot_version()
    factory = MemoryUowFactory(base)

    service = LocalUserTwinProfileRevisionService(
        uow_factory=factory,
        uuid_factory=(DeterministicUuidFactory()),
        clock=revision_clock,
    )

    replacement = human_validated_replacement(
        UserTwinField.GOALS,
        ObservationValue.from_items(
            (
                "Known goals",
                "Reduce booking errors",
            )
        ),
    )

    async def scenario():
        proposed = await service.propose_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            twin_id=TWIN_ID,
            replacements={UserTwinField.GOALS: (replacement)},
        )

        assert proposed.diff is not None

        decided = await service.decide_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            diff_id=proposed.diff.id,
            decision=(ProfileRevisionDecision.APPROVE),
        )

        return proposed, decided

    proposed, decided = asyncio.run(scenario())

    assert proposed.status is (ProfileRevisionApplicationStatus.CREATED)
    assert decided.status is (ProfileRevisionApplicationStatus.APPLIED)

    assert decided.diff is not None
    assert decided.diff.status is (UserTwinProfileDiffStatus.APPROVED)

    assert decided.twin_version is not None
    assert decided.twin_version.twin_id == TWIN_ID
    assert decided.twin_version.version_number == 2
    assert decided.twin_version.based_on_version_number == 1

    assert (
        decided.twin_version.profile.validation_status
        is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT
    )

    changed = decided.twin_version.profile.observation_for(UserTwinField.GOALS)

    assert changed == replacement
    assert changed.epistemic_status is EpistemicStatus.HUMAN_VALIDATED

    assert decided.snapshot_version is not None
    assert decided.snapshot_version.version_number == 2
    assert decided.snapshot_version.based_on_version_number == 1

    assert base.version_number == 1
    assert base.snapshot.twin_versions[0].version_number == 1


def test_rejected_diff_does_not_create_new_profile_versions() -> None:
    """Persist rejection metadata without changing User Modeling state."""
    base = base_snapshot_version()
    factory = MemoryUowFactory(base)

    service = LocalUserTwinProfileRevisionService(
        uow_factory=factory,
        uuid_factory=(DeterministicUuidFactory()),
        clock=revision_clock,
    )

    async def scenario():
        proposed = await service.propose_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            twin_id=TWIN_ID,
            replacements={
                UserTwinField.GOALS: (
                    owner_replacement(
                        UserTwinField.GOALS,
                        ObservationValue.from_items(("Different goal",)),
                    )
                )
            },
        )

        assert proposed.diff is not None

        return await service.decide_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            diff_id=proposed.diff.id,
            decision=(ProfileRevisionDecision.REJECT),
            reason=("The proposed change is not representative of this user group."),
        )

    result = asyncio.run(scenario())

    assert result.status is (ProfileRevisionApplicationStatus.APPLIED)
    assert result.diff is not None
    assert result.diff.status is (UserTwinProfileDiffStatus.REJECTED)

    assert result.twin_version is None
    assert result.snapshot_version is None

    assert len(factory.twins.values) == 1
    assert len(factory.snapshots.values) == 1


def test_stale_diff_cannot_modify_newer_snapshot() -> None:
    """Reject approval when the authoritative snapshot has moved forward."""
    base = base_snapshot_version()
    factory = MemoryUowFactory(base)

    service = LocalUserTwinProfileRevisionService(
        uow_factory=factory,
        uuid_factory=(DeterministicUuidFactory()),
        clock=revision_clock,
    )

    async def scenario():
        proposed = await service.propose_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            twin_id=TWIN_ID,
            replacements={
                UserTwinField.GOALS: (
                    owner_replacement(
                        UserTwinField.GOALS,
                        ObservationValue.from_items(("Stale change",)),
                    )
                )
            },
        )

        assert proposed.diff is not None

        newer = UserModelingSnapshotVersion(
            id=UUID(int=9000),
            project_id=PROJECT_ID,
            version_number=2,
            based_on_version_number=1,
            snapshot=base.snapshot,
            content_hash=(base.snapshot.content_hash),
            created_by_user_id=OWNER_ID,
            created_at=DECIDED_AT,
        )

        factory.snapshots.values.append(newer)

        return await service.decide_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            diff_id=proposed.diff.id,
            decision=(ProfileRevisionDecision.APPROVE),
        )

    result = asyncio.run(scenario())

    assert result.status is (ProfileRevisionApplicationStatus.REJECTED)
    assert result.issue is (ProfileRevisionApplicationIssueCode.CONTEXT_CHANGED)

    assert len(factory.twins.values) == 1
