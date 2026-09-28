from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import replace
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from uuid import UUID

import pytest

from orchestwin.agents.catalog import AGENT_CATALOG_CONTENT_HASH, AGENT_CATALOG_VERSION
from orchestwin.knowledge.twin_import import TwinImportError, imported_twin_ids
from orchestwin.knowledge.twin_import_service import (
    ImportableTwin,
    TwinImportService,
    TwinImportSource,
    TwinImportStatus,
    _summary,
)
from orchestwin.knowledge.twin_import_sources import DEFAULT_CANDIDATE_LIMIT, TwinImportCandidate
from orchestwin.knowledge.twins import portable_twin_documents
from orchestwin.projects.brief_gate import project_brief_artifact_reference
from orchestwin.projects.briefs import ProjectBriefVersion
from orchestwin.twins.application import GovernedUserModelingContext
from orchestwin.twins.epistemics import ObservationValue
from orchestwin.twins.persistence.repositories import VersionAppendStatus
from orchestwin.twins.user_modeling_gate import user_modeling_artifact_reference
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinField,
    VersionedArtifactReference,
)
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)
from src.test.python.knowledge.knowledge_fixtures import PROJECT_NAME, approved_gate
from src.test.python.knowledge.test_twin_import import (
    OWNER_ID,
    SOURCE_PROJECT_ID,
    TARGET_MEMBERS,
    TARGET_PROJECT_ID,
    Member,
    crowded_members,
    folder_document,
    modeling,
    target_snapshot,
)
from src.test.python.twins.test_user_modeling_application import brief_version
from src.test.python.twins.test_user_modeling_gate import BRIEF_REFERENCE, TEAM_REFERENCE

NOW = datetime(2026, 9, 27, 22, 30, tzinfo=UTC)
STRANGER_ID = UUID("00000000-0000-4000-8000-00000000f000")
UNKNOWN_ID = UUID("00000000-0000-4000-8000-00000000f0ff")
TARGET_BRIEF_VERSION_ID = UUID("00000000-0000-4000-8000-00000000b012")
SOURCE_SNAPSHOT_ID = UUID("00000000-0000-4000-8000-00000000e031")
TARGET_TEAM = VersionedArtifactReference(
    artifact_id=UUID("00000000-0000-4000-8000-00000000b022"),
    version_number=1,
    content_hash="7" * 64,
)
IDS = tuple(UUID(f"00000000-0000-4000-8000-00000000f{index:03d}") for index in range(1, 11))
RECEPTIONIST = Member(
    persona_id=UUID("00000000-0000-4000-8000-00000000e110"),
    twin_id=UUID("00000000-0000-4000-8000-00000000e100"),
    name="Receptionist Twin",
    role="Receptionist",
)
AUDITOR = Member(
    persona_id=UUID("00000000-0000-4000-8000-00000000e210"),
    twin_id=UUID("00000000-0000-4000-8000-00000000e200"),
    name="Night Auditor Twin",
    role="Night auditor",
)
SOURCE_PROJECT_NAME = "Hotel Operations Studio"
CANDIDATES = (
    TwinImportCandidate(
        project_id=SOURCE_PROJECT_ID,
        project_name=SOURCE_PROJECT_NAME,
        snapshot_version_number=1,
        approved_at=NOW,
        twin_names=("Night Auditor Twin", "Receptionist Twin"),
    ),
)
GOALS = ObservationValue.from_items(
    ("Check guests in", "Answer the phone", "Balance the till", "Hand over the shift")
)


def source_snapshot() -> UserModelingSnapshotVersion:
    return modeling(
        SOURCE_PROJECT_ID,
        (RECEPTIONIST, AUDITOR),
        snapshot_id=SOURCE_SNAPSHOT_ID,
        brief=BRIEF_REFERENCE,
        team=TEAM_REFERENCE,
    )


def source_gate(source: UserModelingSnapshotVersion) -> HumanGate:
    return approved_gate(
        source, HumanGateType.USER_MODELING, user_modeling_artifact_reference(source), 3000
    )


def pending_gate(source: UserModelingSnapshotVersion) -> HumanGate:
    draft = create_human_gate(
        gate_id=UUID(int=3100),
        project_id=source.project_id,
        owner_user_id=OWNER_ID,
        gate_type=HumanGateType.USER_MODELING,
        artifact=user_modeling_artifact_reference(source),
        created_at=NOW,
    )
    return transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=NOW,
        event_id=UUID(int=3101),
    ).gate


def target_brief() -> ProjectBriefVersion:
    return replace(brief_version(), id=TARGET_BRIEF_VERSION_ID, project_id=TARGET_PROJECT_ID)


def target_context(**changes) -> GovernedUserModelingContext:
    brief = target_brief()
    values = {
        "project_id": TARGET_PROJECT_ID,
        "brief_version": brief,
        "brief_gate": approved_gate(
            brief, HumanGateType.PROJECT_BRIEF, project_brief_artifact_reference(brief), 6000
        ),
        "team_reference": TARGET_TEAM,
        "approved_team_reference": TARGET_TEAM,
        "catalog_version": AGENT_CATALOG_VERSION,
        "catalog_content_hash": AGENT_CATALOG_CONTENT_HASH,
    }
    values.update(changes)
    return GovernedUserModelingContext(**values)


def ready_target(members=TARGET_MEMBERS, **changes) -> UserModelingSnapshotVersion:
    values = {
        "brief": target_context().brief_reference,
        "team": TARGET_TEAM,
        "catalog_version": AGENT_CATALOG_VERSION,
        "catalog_hash": AGENT_CATALOG_CONTENT_HASH,
    }
    values.update(changes)
    return target_snapshot(members, **values)


class Governance:
    def __init__(self, context: GovernedUserModelingContext | None) -> None:
        self.context = context

    async def load_current(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> GovernedUserModelingContext | None:
        if owner_user_id != OWNER_ID or project_id != TARGET_PROJECT_ID:
            return None
        return self.context


class Projects:
    def __init__(self, brief: ProjectBriefVersion | None) -> None:
        self.brief = brief

    async def current_brief(
        self, *, project_id: UUID, owner_user_id: UUID
    ) -> ProjectBriefVersion | None:
        if owner_user_id != OWNER_ID or project_id != SOURCE_PROJECT_ID:
            return None
        return self.brief


class Store:
    def __init__(self, target: UserModelingSnapshotVersion | None) -> None:
        self.snapshots = [] if target is None else [target]
        self.personas: list[object] = []
        self.twins: list[object] = []
        self.refusals: dict[str, VersionAppendStatus] = {}
        self.concurrent: UserModelingSnapshotVersion | None = None
        self.reads = 0
        self.units = 0
        self.commits = 0

    @property
    def current(self) -> UserModelingSnapshotVersion | None:
        return self.snapshots[-1] if self.snapshots else None


class Repository:
    def __init__(self, unit: UnitOfWork, kind: str) -> None:
        self.unit = unit
        self.kind = kind

    async def append(self, version: object) -> VersionAppendStatus:
        status = self.unit.store.refusals.get(self.kind, VersionAppendStatus.APPENDED)
        if status is VersionAppendStatus.APPENDED:
            self.unit.staged[self.kind].append(version)
        return status


class Snapshots(Repository):
    async def current(self, *, project_id: UUID) -> UserModelingSnapshotVersion | None:
        store = self.unit.store
        store.reads += 1
        if self.unit.owner_user_id != OWNER_ID or project_id != TARGET_PROJECT_ID:
            return None
        if store.concurrent is not None and store.reads > 1:
            return store.concurrent
        return store.current


class UnitOfWork:
    def __init__(self, store: Store, owner_user_id: UUID) -> None:
        self.store = store
        self.owner_user_id = owner_user_id
        self.staged: dict[str, list[object]] = {"personas": [], "twins": [], "snapshots": []}
        self.personas = Repository(self, "personas")
        self.twins = Repository(self, "twins")
        self.snapshots = Snapshots(self, "snapshots")

    async def __aenter__(self) -> UnitOfWork:
        self.store.units += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.staged = {"personas": [], "twins": [], "snapshots": []}

    async def commit(self) -> None:
        self.store.personas.extend(self.staged["personas"])
        self.store.twins.extend(self.staged["twins"])
        self.store.snapshots.extend(self.staged["snapshots"])
        self.store.commits += 1


class Queries:
    def __init__(self, store: Store, source: UserModelingSnapshotVersion | None) -> None:
        self.store = store
        self.source = source

    async def current_snapshot(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> UserModelingSnapshotVersion | None:
        if owner_user_id != OWNER_ID:
            return None
        if project_id == SOURCE_PROJECT_ID:
            return self.source
        if project_id == TARGET_PROJECT_ID:
            return self.store.current
        return None


class Gates:
    def __init__(self, gate: HumanGate | None) -> None:
        self.gate = gate

    async def current_gate(self, *, project_id: UUID, owner_user_id: UUID) -> HumanGate | None:
        if owner_user_id != OWNER_ID or project_id != SOURCE_PROJECT_ID:
            return None
        return self.gate


class Candidates:
    def __init__(self, listing: tuple[TwinImportCandidate, ...]) -> None:
        self.listing = listing
        self.calls: list[dict[str, object]] = []

    async def list(
        self,
        *,
        owner_user_id: UUID,
        exclude_project_id: UUID,
        limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> tuple[TwinImportCandidate, ...]:
        self.calls.append(
            {"owner_user_id": owner_user_id, "exclude_project_id": exclude_project_id}
        )
        return self.listing


class Harness:
    def __init__(
        self,
        *,
        target: UserModelingSnapshotVersion | None,
        context: GovernedUserModelingContext | None,
        source: UserModelingSnapshotVersion | None,
        gate: HumanGate | None,
        brief: ProjectBriefVersion | None,
        candidates: tuple[TwinImportCandidate, ...] | None,
        injected: bool,
    ) -> None:
        self.store = Store(target)
        self.before = list(self.store.snapshots)
        self.gate = gate
        self.candidates = None if candidates is None else Candidates(candidates)
        identifiers = iter(IDS)
        dependencies = {
            "governance": Governance(context),
            "uow_factory": self.unit_of_work,
            "project_service": Projects(brief),
            "user_modeling_queries": Queries(self.store, source),
            "user_modeling_gates": Gates(gate),
        }
        if self.candidates is not None:
            dependencies["candidates"] = self.candidates
        if injected:
            dependencies["clock"] = lambda: NOW
            dependencies["uuid_factory"] = lambda: next(identifiers)
        self.service = TwinImportService(**dependencies)

    def unit_of_work(self, *, owner_user_id: UUID) -> UnitOfWork:
        return UnitOfWork(self.store, owner_user_id)

    def nothing_written(self) -> bool:
        return (
            self.store.personas == []
            and self.store.twins == []
            and self.store.snapshots == self.before
            and self.store.commits == 0
        )


def arrange(**changes) -> Harness:
    source = changes.pop("source", source_snapshot())
    values = {
        "target": ready_target(),
        "context": target_context(),
        "source": source,
        "gate": None if source is None else source_gate(source),
        "brief": brief_version(),
        "candidates": CANDIDATES,
        "injected": True,
    }
    values.update(changes)
    return Harness(**values)


def run(coroutine: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coroutine)


def failure(coroutine: Coroutine[Any, Any, Any]) -> TwinImportError:
    with pytest.raises(TwinImportError) as raised:
        asyncio.run(coroutine)
    return raised.value


def offered(harness: Harness, **changes) -> Coroutine[Any, Any, tuple[TwinImportCandidate, ...]]:
    values = {"owner_user_id": OWNER_ID, "project_id": TARGET_PROJECT_ID}
    values.update(changes)
    return harness.service.sources(**values)


def summarized(*, context: ObservationValue, goals: ObservationValue) -> str | None:
    version = source_snapshot().snapshot.twin_versions[0]
    values = {
        UserTwinField.CONTEXT_OF_USE.observation_key: context,
        UserTwinField.GOALS.observation_key: goals,
    }
    profile = replace(
        version.profile,
        observations=tuple(
            replace(item, value=values.get(item.observation_key, item.value))
            for item in version.profile.observations
        ),
    )
    return _summary(replace(version, profile=profile, content_hash=profile.content_hash))


def listed(harness: Harness, **changes) -> Coroutine[Any, Any, TwinImportSource]:
    values = {
        "owner_user_id": OWNER_ID,
        "project_id": TARGET_PROJECT_ID,
        "source_project_id": SOURCE_PROJECT_ID,
    }
    values.update(changes)
    return harness.service.source(**values)


def from_project(harness: Harness, **changes):
    values = {
        "owner_user_id": OWNER_ID,
        "project_id": TARGET_PROJECT_ID,
        "source_project_id": SOURCE_PROJECT_ID,
        "twin_id": RECEPTIONIST.twin_id,
    }
    values.update(changes)
    return harness.service.import_from_project(**values)


def from_document(harness: Harness, document: object, **changes):
    values = {"owner_user_id": OWNER_ID, "project_id": TARGET_PROJECT_ID, "document": document}
    values.update(changes)
    return harness.service.import_document(**values)


def test_sources_offer_the_other_projects_of_the_owner_whose_twins_are_approved():
    harness = arrange()

    result = run(offered(harness))

    assert result == CANDIDATES
    assert harness.candidates.calls == [
        {"owner_user_id": OWNER_ID, "exclude_project_id": TARGET_PROJECT_ID}
    ]
    assert harness.store.units == 0
    assert harness.nothing_written()


def test_sources_refuse_a_target_the_owner_does_not_own_before_reading_other_projects():
    harness = arrange()

    assert failure(offered(harness, owner_user_id=STRANGER_ID)).code == "PROJECT_NOT_FOUND"
    assert failure(offered(harness, project_id=UNKNOWN_ID)).code == "PROJECT_NOT_FOUND"
    assert harness.candidates.calls == []


def test_sources_are_unavailable_when_no_candidate_query_is_configured():
    harness = arrange(candidates=None)

    assert failure(offered(harness)).code == "TWIN_IMPORT_SOURCES_UNAVAILABLE"
    assert failure(offered(harness, owner_user_id=STRANGER_ID)).code == (
        "TWIN_IMPORT_SOURCES_UNAVAILABLE"
    )


def test_source_lists_the_approved_twins_of_another_project_with_what_blocks_each_import():
    harness = arrange()
    receptionist, auditor = source_snapshot().snapshot.twin_versions

    result = run(listed(harness))

    assert result == TwinImportSource(
        project_id=SOURCE_PROJECT_ID,
        project_name=SOURCE_PROJECT_NAME,
        snapshot_version_number=1,
        approved_at=harness.gate.updated_at,
        twins=(
            ImportableTwin(
                twin_id=RECEPTIONIST.twin_id,
                name="Receptionist Twin",
                version_number=1,
                content_hash=receptionist.content_hash,
                validation_status="PROJECT_GROUNDED_UT",
                summary="Known context_of_use",
                issue=None,
            ),
            ImportableTwin(
                twin_id=AUDITOR.twin_id,
                name="Night Auditor Twin",
                version_number=1,
                content_hash=auditor.content_hash,
                validation_status="PROJECT_GROUNDED_UT",
                summary="Known context_of_use",
                issue="TWIN_NAME_ALREADY_USED",
            ),
        ),
    )
    assert harness.store.units == 0
    assert harness.nothing_written()


@pytest.mark.parametrize(
    ("context", "goals", "summary"),
    [
        (
            ObservationValue.from_text("Front desk of a small hotel at night"),
            GOALS,
            "Front desk of a small hotel at night",
        ),
        (
            ObservationValue.unknown(),
            GOALS,
            "Check guests in; Answer the phone; Balance the till",
        ),
        (
            ObservationValue.abstained("The brief does not say where the twin works."),
            ObservationValue.from_items(("Check guests in",)),
            "Check guests in",
        ),
        (
            ObservationValue.from_text("  receptionist   TWIN "),
            GOALS,
            "Check guests in; Answer the phone; Balance the till",
        ),
        (ObservationValue.unknown(), ObservationValue.unknown(), None),
        (
            ObservationValue.from_text("Receptionist twin"),
            ObservationValue.from_items(("RECEPTIONIST TWIN",)),
            None,
        ),
    ],
)
def test_the_summary_of_a_twin_says_where_it_works_or_what_it_wants_and_never_repeats_its_name(
    context, goals, summary
):
    assert summarized(context=context, goals=goals) == summary


@pytest.mark.parametrize(
    ("changes", "issue"),
    [
        ({"brief_gate": None}, "BRIEF_APPROVAL_REQUIRED"),
        ({"approved_team_reference": None}, "TEAM_APPROVAL_REQUIRED"),
        (
            {
                "team_reference": None,
                "approved_team_reference": None,
                "catalog_version": None,
                "catalog_content_hash": None,
            },
            "TEAM_APPROVAL_REQUIRED",
        ),
    ],
)
def test_source_marks_every_twin_with_the_governance_blocker_of_the_target(changes, issue):
    result = run(listed(arrange(context=target_context(**changes))))

    assert [twin.issue for twin in result.twins] == [issue, issue]


@pytest.mark.parametrize(
    ("target", "issues"),
    [
        (lambda: None, ["USER_TWINS_REQUIRED", "USER_TWINS_REQUIRED"]),
        (target_snapshot, ["USER_TWINS_OUTDATED", "USER_TWINS_OUTDATED"]),
        (lambda: ready_target(crowded_members(8)), ["TWIN_LIMIT_REACHED", "TWIN_LIMIT_REACHED"]),
        (lambda: ready_target(crowded_members(1)), [None, None]),
    ],
)
def test_source_marks_every_twin_with_the_state_of_the_target_twins(target, issues):
    result = run(listed(arrange(target=target())))

    assert [twin.issue for twin in result.twins] == issues


def test_source_marks_a_twin_that_was_already_imported():
    harness = arrange()
    run(from_project(harness))

    result = run(listed(harness))

    assert [twin.issue for twin in result.twins] == [
        "TWIN_ALREADY_IMPORTED",
        "TWIN_NAME_ALREADY_USED",
    ]


def test_source_refuses_a_target_or_a_source_the_owner_does_not_own():
    harness = arrange()

    assert failure(listed(harness, owner_user_id=STRANGER_ID)).code == "PROJECT_NOT_FOUND"
    assert failure(listed(harness, project_id=UNKNOWN_ID)).code == "PROJECT_NOT_FOUND"
    assert failure(listed(harness, source_project_id=UNKNOWN_ID)).code == (
        "SOURCE_PROJECT_NOT_FOUND"
    )
    assert failure(listed(arrange(brief=None))).code == "SOURCE_PROJECT_NOT_FOUND"


@pytest.mark.parametrize(
    "changes",
    [
        lambda: {"source": None},
        lambda: {"gate": None},
        lambda: {"gate": pending_gate(source_snapshot())},
        lambda: {
            "gate": source_gate(
                modeling(
                    SOURCE_PROJECT_ID,
                    (RECEPTIONIST,),
                    snapshot_id=UUID("00000000-0000-4000-8000-00000000e030"),
                    brief=BRIEF_REFERENCE,
                    team=TEAM_REFERENCE,
                )
            )
        },
    ],
)
def test_twins_can_come_only_from_a_snapshot_approved_by_its_current_gate(changes):
    harness = arrange(**changes())

    assert failure(listed(harness)).code == "SOURCE_TWINS_NOT_APPROVED"
    assert failure(from_project(harness)).code == "SOURCE_TWINS_NOT_APPROVED"
    assert harness.nothing_written()


def test_import_from_project_writes_the_persona_the_twin_and_the_next_snapshot_in_one_commit():
    harness = arrange()
    before = harness.store.current

    result = run(from_project(harness))

    imported = result.imported
    assert result.status is TwinImportStatus.IMPORTED
    assert (
        imported.persona_version.persona_id,
        imported.persona_version.id,
        imported.twin_version.twin_id,
        imported.twin_version.id,
        imported.snapshot_version.id,
    ) == IDS[:5]
    for version in (imported.persona_version, imported.twin_version, imported.snapshot_version):
        assert (version.created_by_user_id, version.created_at) == (OWNER_ID, NOW)
    assert imported.origin.project_id == SOURCE_PROJECT_ID
    assert imported.origin.project_name == SOURCE_PROJECT_NAME
    assert imported.origin.twin_id == RECEPTIONIST.twin_id
    assert imported.twin_version.profile.name == "Receptionist Twin"
    assert imported.snapshot_version.based_on_version_number == before.version_number
    assert harness.store.personas == [imported.persona_version]
    assert harness.store.twins == [imported.twin_version]
    assert harness.store.snapshots == [before, imported.snapshot_version]
    assert harness.store.commits == 1
    assert imported_twin_ids(harness.store.current) == {RECEPTIONIST.twin_id: IDS[2]}


def test_import_from_project_requires_the_twin_in_the_source_snapshot():
    harness = arrange()

    assert failure(from_project(harness, twin_id=UNKNOWN_ID)).code == "SOURCE_TWIN_NOT_FOUND"
    assert failure(from_project(harness, source_project_id=UNKNOWN_ID)).code == (
        "SOURCE_PROJECT_NOT_FOUND"
    )
    assert failure(from_project(harness, owner_user_id=STRANGER_ID)).code == (
        "SOURCE_PROJECT_NOT_FOUND"
    )
    assert harness.store.units == 0
    assert harness.nothing_written()


def test_import_document_accepts_a_twin_document_of_an_exported_knowledge_folder():
    harness = arrange()

    result = run(from_document(harness, folder_document()))

    assert result.imported.origin.project_name == PROJECT_NAME
    assert result.imported.twin_version.twin_id == IDS[2]
    assert harness.store.snapshots[-1] == result.imported.snapshot_version
    assert harness.store.commits == 1


@pytest.mark.parametrize(
    ("change", "code", "location"),
    [
        (
            lambda document: document.update(kind="orchestwin.user-persona"),
            "TWIN_DOCUMENT_UNSUPPORTED",
            "kind",
        ),
        (
            lambda document: document["origin"].update(project_name="   "),
            "TWIN_DOCUMENT_INVALID",
            "origin.project_name",
        ),
    ],
)
def test_an_invalid_document_is_refused_with_its_location_before_the_target_is_read(
    change, code, location
):
    harness = arrange()
    document = folder_document()
    change(document)

    error = failure(from_document(harness, document))

    assert (error.code, error.detail) == (code, location)
    assert harness.store.units == 0
    assert harness.nothing_written()


@pytest.mark.parametrize(
    ("context", "code"),
    [
        (lambda: None, "PROJECT_NOT_FOUND"),
        (lambda: target_context(brief_gate=None), "BRIEF_APPROVAL_REQUIRED"),
        (lambda: target_context(approved_team_reference=None), "TEAM_APPROVAL_REQUIRED"),
        (
            lambda: target_context(
                team_reference=None,
                approved_team_reference=None,
                catalog_version=None,
                catalog_content_hash=None,
            ),
            "TEAM_APPROVAL_REQUIRED",
        ),
    ],
)
def test_the_target_needs_an_approved_brief_and_team_before_anything_is_written(context, code):
    harness = arrange(context=context())

    assert failure(from_document(harness, folder_document())).code == code
    assert failure(from_project(harness)).code == code
    assert harness.store.units == 0
    assert harness.nothing_written()


@pytest.mark.parametrize(
    ("target", "code"),
    [
        (lambda: None, "USER_TWINS_REQUIRED"),
        (target_snapshot, "USER_TWINS_OUTDATED"),
        (lambda: ready_target(crowded_members(8)), "TWIN_LIMIT_REACHED"),
        (
            lambda: ready_target((replace(TARGET_MEMBERS[0], name=" receptionist twin"),)),
            "TWIN_NAME_ALREADY_USED",
        ),
    ],
)
def test_an_import_refused_by_the_target_twins_writes_nothing(target, code):
    harness = arrange(target=target())

    assert failure(from_document(harness, folder_document())).code == code
    assert harness.nothing_written()


def test_a_twin_of_the_target_itself_cannot_be_imported_into_it():
    harness = arrange()
    own = harness.store.current
    document = portable_twin_documents(
        project_id=TARGET_PROJECT_ID,
        project_name="Hotel front desk",
        modeling=own,
        modeling_gate=approved_gate(
            own, HumanGateType.USER_MODELING, user_modeling_artifact_reference(own), 7000
        ),
    )[0].document

    assert failure(from_document(harness, document)).code == "TWIN_BELONGS_TO_PROJECT"
    assert harness.nothing_written()


def test_the_same_twin_cannot_be_imported_twice():
    harness = arrange()
    run(from_document(harness, folder_document()))
    written = list(harness.store.snapshots)

    assert failure(from_document(harness, folder_document())).code == "TWIN_ALREADY_IMPORTED"
    assert harness.store.snapshots == written
    assert (len(harness.store.personas), len(harness.store.twins)) == (1, 1)
    assert harness.store.commits == 1


def test_a_snapshot_written_by_someone_else_during_the_import_cancels_it():
    harness = arrange()
    harness.store.concurrent = ready_target(
        TARGET_MEMBERS[:1], snapshot_id=UUID("00000000-0000-4000-8000-00000000b039")
    )

    assert failure(from_document(harness, folder_document())).code == "CONTEXT_CHANGED"
    assert harness.nothing_written()


@pytest.mark.parametrize("kind", ["personas", "twins", "snapshots"])
def test_a_refused_append_cancels_the_whole_import(kind):
    harness = arrange()
    harness.store.refusals[kind] = VersionAppendStatus.CONTEXT_NOT_FOUND

    assert failure(from_document(harness, folder_document())).code == "PERSISTENCE_REJECTED"
    assert harness.nothing_written()


def test_without_injected_identities_and_clock_the_import_uses_random_ids_and_utc_time():
    harness = arrange(injected=False)

    imported = run(from_document(harness, folder_document())).imported

    identities = {
        imported.persona_version.persona_id,
        imported.persona_version.id,
        imported.twin_version.twin_id,
        imported.twin_version.id,
        imported.snapshot_version.id,
    }
    assert len(identities) == 5
    assert identities.isdisjoint(IDS)
    assert imported.snapshot_version.created_at.utcoffset().total_seconds() == 0
