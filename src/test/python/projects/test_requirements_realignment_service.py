from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID

import pytest

from orchestwin.projects.requirements_application import RequirementsVersionAppendStatus
from orchestwin.projects.requirements_realignment import (
    realign_requirements,
    snapshot_brief_reference,
    snapshot_reference,
    snapshot_team_reference,
)
from orchestwin.projects.requirements_realignment_service import (
    RequirementsAlignment,
    RequirementsRealignmentFailure,
    RequirementsRealignmentService,
)
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.twins.user_modeling_gate import user_modeling_artifact_reference
from orchestwin.twins.user_twins import UserModelingSnapshotVersion
from orchestwin.workflow.gates import HumanGate, HumanGateType
from src.test.python.knowledge.knowledge_fixtures import approved_gate
from src.test.python.knowledge.test_twin_import import OWNER_ID
from src.test.python.projects.test_requirements_realignment import (
    PROJECT_ID,
    REANCHORED_SNAPSHOT_ID,
    SECOND_SNAPSHOT_ID,
    first_snapshot,
    reanchored_snapshot,
    requirements_version,
    second_snapshot,
    snapshot_without_the_auditor,
)

STRANGER_ID = UUID("00000000-0000-4000-8000-00000000f000")
NOW = datetime(2026, 9, 27, 23, 0, tzinfo=UTC)
REALIGNED_ID = UUID("00000000-0000-4000-8000-00000000d0f1")


def approved(snapshot: UserModelingSnapshotVersion) -> HumanGate:
    return approved_gate(
        snapshot, HumanGateType.USER_MODELING, user_modeling_artifact_reference(snapshot), 4000
    )


class Store:
    def __init__(self, versions: list[RequirementsSpecificationVersion]) -> None:
        self.versions = list(versions)
        self.pending_base: UUID | None = None
        self.refusal: RequirementsVersionAppendStatus | None = None
        self.diff_bases: list[UUID] = []
        self.locks = 0
        self.units = 0
        self.commits = 0

    @property
    def current(self) -> RequirementsSpecificationVersion | None:
        return self.versions[-1] if self.versions else None


class Specifications:
    def __init__(self, unit: UnitOfWork) -> None:
        self.unit = unit

    def _owned(self, project_id: UUID) -> RequirementsSpecificationVersion | None:
        if self.unit.owner_user_id != OWNER_ID or project_id != PROJECT_ID:
            return None
        return self.unit.store.current

    async def current(self, *, project_id: UUID) -> RequirementsSpecificationVersion | None:
        return self._owned(project_id)

    async def get_current_owned_for_update(
        self, *, project_id: UUID, owner_user_id: UUID
    ) -> RequirementsSpecificationVersion | None:
        self.unit.store.locks += 1
        if owner_user_id != self.unit.owner_user_id:
            return None
        return self._owned(project_id)

    async def append(
        self, version: RequirementsSpecificationVersion
    ) -> RequirementsVersionAppendStatus:
        status = self.unit.store.refusal or RequirementsVersionAppendStatus.APPENDED
        if status is RequirementsVersionAppendStatus.APPENDED:
            self.unit.staged.append(version)
        return status


class Diffs:
    def __init__(self, unit: UnitOfWork) -> None:
        self.unit = unit

    async def current_proposed(self, *, project_id: UUID, base_version_id: UUID) -> object | None:
        self.unit.store.diff_bases.append(base_version_id)
        if project_id == PROJECT_ID and base_version_id == self.unit.store.pending_base:
            return object()
        return None


class UnitOfWork:
    def __init__(self, store: Store, owner_user_id: UUID) -> None:
        self.store = store
        self.owner_user_id = owner_user_id
        self.staged: list[RequirementsSpecificationVersion] = []
        self.specifications = Specifications(self)
        self.diffs = Diffs(self)

    async def __aenter__(self) -> UnitOfWork:
        self.store.units += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.staged = []

    async def commit(self) -> None:
        self.store.versions.extend(self.staged)
        self.store.commits += 1


class Queries:
    def __init__(self, snapshot: UserModelingSnapshotVersion | None) -> None:
        self.snapshot = snapshot

    async def current_snapshot(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> UserModelingSnapshotVersion | None:
        if owner_user_id != OWNER_ID or project_id != PROJECT_ID:
            return None
        return self.snapshot


class Gates:
    def __init__(self, gate: HumanGate | None) -> None:
        self.gate = gate

    async def current_gate(self, *, project_id: UUID, owner_user_id: UUID) -> HumanGate | None:
        if owner_user_id != OWNER_ID or project_id != PROJECT_ID:
            return None
        return self.gate


class Context:
    def __init__(self, current: bool) -> None:
        self.current = current
        self.calls: list[tuple[UUID, UUID, UUID]] = []

    async def snapshot_context_is_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        snapshot: UserModelingSnapshotVersion | None,
    ) -> bool:
        self.calls.append((owner_user_id, project_id, snapshot.id))
        return self.current


class Harness:
    def __init__(
        self,
        *,
        snapshot: UserModelingSnapshotVersion | None,
        gate: HumanGate | None,
        versions: list[RequirementsSpecificationVersion],
        injected: bool = True,
        current: bool | None = True,
    ) -> None:
        self.store = Store(versions)
        self.before = list(self.store.versions)
        self.context = None if current is None else Context(current)
        dependencies = {
            "uow_factory": self.unit_of_work,
            "user_modeling_queries": Queries(snapshot),
            "user_modeling_gates": Gates(gate),
            "user_modeling_context": self.context,
        }
        if injected:
            dependencies["clock"] = lambda: NOW
            dependencies["uuid_factory"] = lambda: REALIGNED_ID
        self.service = RequirementsRealignmentService(**dependencies)

    def unit_of_work(self, *, owner_user_id: UUID) -> UnitOfWork:
        return UnitOfWork(self.store, owner_user_id)

    def status(self, owner_user_id: UUID = OWNER_ID) -> RequirementsAlignment:
        return asyncio.run(self.service.status(owner_user_id=owner_user_id, project_id=PROJECT_ID))

    def realign(self, owner_user_id: UUID = OWNER_ID) -> RequirementsSpecificationVersion:
        return asyncio.run(self.service.realign(owner_user_id=owner_user_id, project_id=PROJECT_ID))

    def refusal(self, owner_user_id: UUID = OWNER_ID) -> str:
        with pytest.raises(RequirementsRealignmentFailure) as raised:
            self.realign(owner_user_id)
        return raised.value.code

    def nothing_written(self) -> bool:
        return self.store.versions == self.before and self.store.commits == 0


def after_revision(**changes) -> Harness:
    second = second_snapshot()
    values = {
        "snapshot": second,
        "gate": approved(second),
        "versions": [requirements_version(first_snapshot())],
    }
    values.update(changes)
    return Harness(**values)


def blocked(name: str) -> Harness:
    first = first_snapshot()
    second = second_snapshot()
    written = requirements_version(first)
    if name == "REQUIREMENTS_NOT_FOUND":
        return after_revision(versions=[])
    if name == "USER_TWINS_REQUIRED":
        return after_revision(snapshot=None, gate=None)
    if name == "USER_TWINS_APPROVAL_REQUIRED":
        return after_revision(gate=approved(first))
    if name == "REQUIREMENTS_ALREADY_ALIGNED":
        return after_revision(snapshot=first, gate=approved(first))
    if name == "TWIN_NO_LONGER_AVAILABLE":
        reduced = snapshot_without_the_auditor()
        return after_revision(snapshot=reduced, gate=approved(reduced))
    harness = after_revision(snapshot=second, gate=approved(second))
    harness.store.pending_base = written.id
    return harness


BLOCKERS = (
    "REQUIREMENTS_NOT_FOUND",
    "USER_TWINS_REQUIRED",
    "USER_TWINS_APPROVAL_REQUIRED",
    "REQUIREMENTS_ALREADY_ALIGNED",
    "TWIN_NO_LONGER_AVAILABLE",
    "REQUIREMENTS_REVISION_PENDING",
)


def test_status_reports_requirements_written_for_older_twins_as_ready_to_realign():
    harness = after_revision()

    assert harness.status() == RequirementsAlignment(
        aligned=False,
        issue=None,
        requirements_version_number=3,
        snapshot_version_number=2,
        twins_approved=True,
    )
    assert harness.store.diff_bases == [harness.store.current.id]
    assert harness.store.locks == 0
    assert harness.nothing_written()


def test_status_reports_requirements_written_for_the_current_twins_as_aligned():
    first = first_snapshot()
    harness = after_revision(snapshot=first, gate=approved(first))

    assert harness.status() == RequirementsAlignment(
        aligned=True,
        issue="REQUIREMENTS_ALREADY_ALIGNED",
        requirements_version_number=3,
        snapshot_version_number=1,
        twins_approved=True,
    )


@pytest.mark.parametrize("name", BLOCKERS)
def test_status_names_what_blocks_the_realignment(name):
    assert blocked(name).status().issue == name


def test_status_without_requirements_or_twins_has_no_versions_and_no_approval():
    assert blocked("REQUIREMENTS_NOT_FOUND").status() == RequirementsAlignment(
        aligned=False,
        issue="REQUIREMENTS_NOT_FOUND",
        requirements_version_number=None,
        snapshot_version_number=2,
        twins_approved=True,
    )
    assert blocked("USER_TWINS_REQUIRED").status() == RequirementsAlignment(
        aligned=False,
        issue="USER_TWINS_REQUIRED",
        requirements_version_number=3,
        snapshot_version_number=None,
        twins_approved=False,
    )
    assert blocked("USER_TWINS_APPROVAL_REQUIRED").status().twins_approved is False


def test_status_of_another_owner_finds_no_requirements_and_no_twins():
    assert after_revision().status(STRANGER_ID) == RequirementsAlignment(
        aligned=False,
        issue="REQUIREMENTS_NOT_FOUND",
        requirements_version_number=None,
        snapshot_version_number=None,
        twins_approved=False,
    )


def test_a_revision_pending_on_an_older_version_does_not_block_the_realignment():
    harness = after_revision()
    harness.store.pending_base = UUID("00000000-0000-4000-8000-00000000d040")

    assert harness.status().issue is None
    assert harness.realign().version_number == 4


def test_realign_writes_the_next_version_pointing_to_the_current_twins():
    harness = after_revision()
    written = harness.store.current
    second = second_snapshot()

    version = harness.realign()

    assert version.id == REALIGNED_ID
    assert (version.version_number, version.based_on_version_number) == (4, 3)
    assert (version.created_by_user_id, version.created_at) == (OWNER_ID, NOW)
    assert version.specification == realign_requirements(written.specification, second)
    assert version.specification.user_modeling_reference == snapshot_reference(second)
    assert harness.store.versions == [written, version]
    assert harness.store.commits == 1
    assert harness.store.locks == 1
    assert harness.status() == RequirementsAlignment(
        aligned=True,
        issue="REQUIREMENTS_ALREADY_ALIGNED",
        requirements_version_number=4,
        snapshot_version_number=2,
        twins_approved=True,
    )


@pytest.mark.parametrize("name", BLOCKERS)
def test_realign_refuses_with_the_code_of_the_blocker_and_writes_nothing(name):
    harness = blocked(name)

    assert harness.refusal() == name
    assert harness.nothing_written()


@pytest.mark.parametrize(
    "status",
    [
        RequirementsVersionAppendStatus.VERSION_CONFLICT,
        RequirementsVersionAppendStatus.CONTENT_CONFLICT,
        RequirementsVersionAppendStatus.PROJECT_NOT_FOUND,
    ],
)
def test_realign_refuses_an_append_the_repository_rejects(status):
    harness = after_revision()
    harness.store.refusal = status

    assert harness.refusal() == "PERSISTENCE_REJECTED"
    assert harness.nothing_written()


def test_realign_for_another_owner_finds_no_requirements():
    harness = after_revision()

    assert harness.refusal(STRANGER_ID) == "REQUIREMENTS_NOT_FOUND"
    assert harness.nothing_written()


def test_without_injected_identity_and_clock_the_realignment_uses_a_random_id_and_utc_time():
    harness = after_revision(injected=False)

    version = harness.realign()

    assert version.id not in {REALIGNED_ID, harness.before[0].id}
    assert version.created_at.utcoffset().total_seconds() == 0


def test_twins_approved_for_an_earlier_brief_or_team_are_not_approved_for_the_realignment():
    harness = after_revision(current=False)

    assert harness.status() == RequirementsAlignment(
        aligned=False,
        issue="USER_TWINS_APPROVAL_REQUIRED",
        requirements_version_number=3,
        snapshot_version_number=2,
        twins_approved=False,
    )
    assert harness.refusal() == "USER_TWINS_APPROVAL_REQUIRED"
    assert harness.nothing_written()
    assert harness.context.calls == [(OWNER_ID, PROJECT_ID, SECOND_SNAPSHOT_ID)] * 2


def test_the_context_of_the_twins_is_asked_only_when_gate_three_approves_them():
    harness = after_revision(gate=approved(first_snapshot()))

    assert harness.status().issue == "USER_TWINS_APPROVAL_REQUIRED"
    assert harness.context.calls == []


def test_without_the_context_of_the_twins_gate_three_alone_decides():
    harness = after_revision(current=None)

    assert harness.status().twins_approved is True
    assert harness.realign().version_number == 4


def test_requirements_written_for_an_earlier_brief_and_team_follow_the_re_anchored_twins():
    reanchored = reanchored_snapshot()
    harness = after_revision(snapshot=reanchored, gate=approved(reanchored))
    written = harness.store.current

    assert harness.status() == RequirementsAlignment(
        aligned=False,
        issue=None,
        requirements_version_number=3,
        snapshot_version_number=2,
        twins_approved=True,
    )

    version = harness.realign()

    specification = version.specification
    assert specification == realign_requirements(written.specification, reanchored)
    assert specification.project_brief_reference == snapshot_brief_reference(reanchored)
    assert specification.agent_team_reference == snapshot_team_reference(reanchored)
    assert specification.user_modeling_reference.artifact_id == REANCHORED_SNAPSHOT_ID
    assert [requirement.sources for requirement in specification.requirements] == [
        requirement.sources for requirement in written.specification.requirements
    ]
    assert harness.context.calls == [(OWNER_ID, PROJECT_ID, REANCHORED_SNAPSHOT_ID)] * 2
    assert harness.status().issue == "REQUIREMENTS_ALREADY_ALIGNED"
