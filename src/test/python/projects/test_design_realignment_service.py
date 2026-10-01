from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import TracebackType
from uuid import UUID

import pytest

from orchestwin.artifacts.design_gate import (
    design_artifact_reference,
    design_gate_is_currently_approved,
)
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.design_realignment import realign_design
from orchestwin.projects.design_application import DesignVersionAppendStatus
from orchestwin.projects.design_realignment_service import (
    DesignAlignment,
    DesignRealignment,
    DesignRealignmentFailure,
    DesignRealignmentService,
)
from orchestwin.projects.requirements_gate import requirements_artifact_reference
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGate,
    HumanGateAction,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)
from src.test.python.artifacts.test_design_realignment import (
    AUDITOR,
    FRONT_DESK,
    OWNER_ID,
    PROJECT_ID,
    design_version,
    first_requirements,
    requirements_with_another_twin,
    requirements_with_revised_twins,
    requirements_without_a_cited_requirement,
    reworded_requirements,
)

STRANGER_ID = UUID("00000000-0000-4000-8000-00000000f000")
GATED_AT = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
REALIGNED_ID = UUID("00000000-0000-4000-8000-00000000e0f1")
MISSING_CODES = ("REQ-002", "USR-002", "AC-002")


def approved_gate(gate_type: HumanGateType, artifact: GateArtifactReference) -> HumanGate:
    draft = create_human_gate(
        gate_id=UUID(int=4000),
        project_id=artifact.project_id,
        owner_user_id=OWNER_ID,
        gate_type=gate_type,
        artifact=artifact,
        created_at=GATED_AT,
    )
    submitted = transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=GATED_AT + timedelta(minutes=1),
        event_id=UUID(int=4001),
    )
    return transition_human_gate(
        submitted.gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=GATED_AT + timedelta(minutes=2),
        event_id=UUID(int=4002),
    ).gate


def approved(version: RequirementsSpecificationVersion) -> HumanGate:
    return approved_gate(HumanGateType.REQUIREMENTS, requirements_artifact_reference(version))


class Store:
    def __init__(self, versions: list[DesignPackageVersion]) -> None:
        self.versions = list(versions)
        self.pending_base: UUID | None = None
        self.refusal: DesignVersionAppendStatus | None = None
        self.diff_bases: list[UUID] = []
        self.locks = 0
        self.units = 0
        self.commits = 0

    @property
    def current(self) -> DesignPackageVersion | None:
        return self.versions[-1] if self.versions else None


class Packages:
    def __init__(self, unit: UnitOfWork) -> None:
        self.unit = unit

    def _owned(self, project_id: UUID) -> DesignPackageVersion | None:
        if self.unit.owner_user_id != OWNER_ID or project_id != PROJECT_ID:
            return None
        return self.unit.store.current

    async def current(self, *, project_id: UUID) -> DesignPackageVersion | None:
        return self._owned(project_id)

    async def get_current_owned_for_update(
        self, *, project_id: UUID, owner_user_id: UUID
    ) -> DesignPackageVersion | None:
        self.unit.store.locks += 1
        if owner_user_id != self.unit.owner_user_id:
            return None
        return self._owned(project_id)

    async def append(self, version: DesignPackageVersion) -> DesignVersionAppendStatus:
        status = self.unit.store.refusal or DesignVersionAppendStatus.APPENDED
        if status is DesignVersionAppendStatus.APPENDED:
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
        self.staged: list[DesignPackageVersion] = []
        self.packages = Packages(self)
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


class Requirements:
    def __init__(self, versions: list[RequirementsSpecificationVersion]) -> None:
        self.versions = list(versions)
        self.histories = 0

    def _owned(self, owner_user_id: UUID, project_id: UUID) -> bool:
        return owner_user_id == OWNER_ID and project_id == PROJECT_ID

    async def current(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> RequirementsSpecificationVersion | None:
        if not self._owned(owner_user_id, project_id) or not self.versions:
            return None
        return self.versions[-1]

    async def history(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> tuple[RequirementsSpecificationVersion, ...]:
        self.histories += 1
        if not self._owned(owner_user_id, project_id):
            return ()
        return tuple(self.versions)


class Gates:
    def __init__(self, gate: HumanGate | None) -> None:
        self.gate = gate

    async def current_gate(self, *, project_id: UUID, owner_user_id: UUID) -> HumanGate | None:
        if owner_user_id != OWNER_ID or project_id != PROJECT_ID:
            return None
        return self.gate


class Harness:
    def __init__(
        self,
        *,
        designs: list[DesignPackageVersion],
        requirements: list[RequirementsSpecificationVersion],
        gate: HumanGate | None,
        injected: bool = True,
    ) -> None:
        self.store = Store(designs)
        self.before = list(self.store.versions)
        self.requirements = Requirements(requirements)
        dependencies = {
            "uow_factory": self.unit_of_work,
            "requirements_queries": self.requirements,
            "requirements_gates": Gates(gate),
        }
        if injected:
            dependencies["clock"] = lambda: NOW
            dependencies["uuid_factory"] = lambda: REALIGNED_ID
        self.service = DesignRealignmentService(**dependencies)

    def unit_of_work(self, *, owner_user_id: UUID) -> UnitOfWork:
        return UnitOfWork(self.store, owner_user_id)

    def status(self, owner_user_id: UUID = OWNER_ID) -> DesignAlignment:
        return asyncio.run(self.service.status(owner_user_id=owner_user_id, project_id=PROJECT_ID))

    def realign(self, owner_user_id: UUID = OWNER_ID) -> DesignRealignment:
        return asyncio.run(self.service.realign(owner_user_id=owner_user_id, project_id=PROJECT_ID))

    def failure(self, owner_user_id: UUID = OWNER_ID) -> DesignRealignmentFailure:
        with pytest.raises(DesignRealignmentFailure) as raised:
            self.realign(owner_user_id)
        return raised.value

    def refusal(self, owner_user_id: UUID = OWNER_ID) -> str:
        return self.failure(owner_user_id).code

    def nothing_written(self) -> bool:
        return self.store.versions == self.before and self.store.commits == 0


def after_change(changed=reworded_requirements, **changes) -> Harness:
    current = changed()
    values = {
        "designs": [design_version()],
        "requirements": [first_requirements(), current],
        "gate": approved(current),
    }
    values.update(changes)
    return Harness(**values)


def aligned() -> Harness:
    first = first_requirements()
    return Harness(designs=[design_version()], requirements=[first], gate=approved(first))


def blocked(name: str) -> Harness:
    if name == "DESIGN_NOT_FOUND":
        return after_change(designs=[])
    if name == "REQUIREMENTS_APPROVAL_REQUIRED":
        return after_change(gate=approved(first_requirements()))
    if name == "ALREADY_ALIGNED":
        return aligned()
    if name == "REQUIREMENT_NO_LONGER_AVAILABLE":
        return after_change(requirements_without_a_cited_requirement)
    if name == "TWIN_SET_CHANGED":
        return after_change(requirements_with_another_twin)
    harness = after_change()
    harness.store.pending_base = harness.store.current.id
    return harness


BLOCKERS = (
    "DESIGN_NOT_FOUND",
    "REQUIREMENTS_APPROVAL_REQUIRED",
    "ALREADY_ALIGNED",
    "REQUIREMENT_NO_LONGER_AVAILABLE",
    "TWIN_SET_CHANGED",
    "DESIGN_REVISION_PENDING",
)


def test_status_reports_a_design_grounded_on_older_requirements_as_ready_to_realign():
    harness = after_change()

    assert harness.status() == DesignAlignment(
        aligned=False,
        issue=None,
        design_version_number=1,
        grounded_requirements_version_number=1,
        requirements_version_number=2,
        missing_codes=(),
        uncovered_codes=("REQ-003",),
    )
    assert harness.store.diff_bases == [harness.store.current.id]
    assert harness.store.locks == 0
    assert harness.requirements.histories == 0
    assert harness.nothing_written()


def test_status_reports_a_design_grounded_on_the_current_requirements_as_aligned():
    assert aligned().status() == DesignAlignment(
        aligned=True,
        issue="ALREADY_ALIGNED",
        design_version_number=1,
        grounded_requirements_version_number=1,
        requirements_version_number=1,
        missing_codes=(),
        uncovered_codes=("REQ-003",),
    )


def test_status_names_the_codes_that_the_current_requirements_no_longer_contain():
    harness = after_change(requirements_without_a_cited_requirement)

    assert harness.status() == DesignAlignment(
        aligned=False,
        issue="REQUIREMENT_NO_LONGER_AVAILABLE",
        design_version_number=1,
        grounded_requirements_version_number=1,
        requirements_version_number=2,
        missing_codes=MISSING_CODES,
        uncovered_codes=("REQ-003",),
    )
    assert harness.requirements.histories == 1


def test_missing_items_are_named_only_with_the_codes_of_the_grounded_requirements():
    harness = after_change(
        requirements_without_a_cited_requirement,
        requirements=[requirements_without_a_cited_requirement()],
    )

    alignment = harness.status()

    assert alignment.issue == "REQUIREMENT_NO_LONGER_AVAILABLE"
    assert alignment.missing_codes == ()
    assert harness.failure().missing_codes == ()


@pytest.mark.parametrize("name", BLOCKERS)
def test_status_names_what_blocks_the_realignment(name):
    assert blocked(name).status().issue == name


def test_status_without_a_design_or_for_another_owner_has_no_versions():
    assert blocked("DESIGN_NOT_FOUND").status() == DesignAlignment(
        aligned=False,
        issue="DESIGN_NOT_FOUND",
        design_version_number=None,
        grounded_requirements_version_number=None,
        requirements_version_number=2,
        missing_codes=(),
        uncovered_codes=(),
    )
    assert after_change().status(STRANGER_ID) == DesignAlignment(
        aligned=False,
        issue="DESIGN_NOT_FOUND",
        design_version_number=None,
        grounded_requirements_version_number=None,
        requirements_version_number=None,
        missing_codes=(),
        uncovered_codes=(),
    )


@pytest.mark.parametrize(
    "harness",
    [
        pytest.param(lambda: after_change(gate=None), id="no-gate"),
        pytest.param(lambda: after_change(requirements=[]), id="no-requirements"),
        pytest.param(
            lambda: after_change(
                requirements_without_a_cited_requirement, gate=approved(first_requirements())
            ),
            id="before-a-missing-requirement",
        ),
    ],
)
def test_gate_four_must_approve_the_latest_requirements_before_anything_else_is_checked(harness):
    assert harness().status().issue == "REQUIREMENTS_APPROVAL_REQUIRED"


def test_a_missing_design_is_reported_before_unapproved_requirements():
    assert after_change(designs=[], gate=None).status().issue == "DESIGN_NOT_FOUND"


def test_the_issue_of_the_content_is_reported_before_a_pending_revision():
    harness = after_change(requirements_with_another_twin)
    harness.store.pending_base = harness.store.current.id

    assert harness.status().issue == "TWIN_SET_CHANGED"


def test_a_revision_pending_on_an_older_version_does_not_block_the_realignment():
    harness = after_change()
    harness.store.pending_base = UUID("00000000-0000-4000-8000-00000000e0f9")

    assert harness.status().issue is None
    assert harness.realign().version.version_number == 2


def test_realign_writes_the_next_version_grounded_on_the_current_requirements():
    harness = after_change()
    written = harness.store.current
    current = reworded_requirements()

    realignment = harness.realign()
    version = realignment.version

    assert realignment == DesignRealignment(
        version=version, requirements_version_number=2, uncovered_codes=("REQ-003",)
    )
    assert version.id == REALIGNED_ID
    assert (version.version_number, version.based_on_version_number) == (2, 1)
    assert (version.created_by_user_id, version.created_at) == (OWNER_ID, NOW)
    assert version.package == realign_design(written.package, current)
    assert version.content_hash != written.content_hash
    assert harness.store.versions == [written, version]
    assert harness.store.commits == 1
    assert harness.store.locks == 1


def test_the_realigned_version_waits_for_its_own_approval():
    harness = after_change()
    written = harness.store.current
    gate = approved_gate(HumanGateType.DESIGN, design_artifact_reference(written))

    version = harness.realign().version

    assert design_gate_is_currently_approved(gate, written)
    assert not design_gate_is_currently_approved(gate, version)


def test_after_the_realignment_the_status_is_aligned_and_a_second_realignment_is_refused():
    harness = after_change()

    harness.realign()

    assert harness.status() == DesignAlignment(
        aligned=True,
        issue="ALREADY_ALIGNED",
        design_version_number=2,
        grounded_requirements_version_number=2,
        requirements_version_number=2,
        missing_codes=(),
        uncovered_codes=("REQ-003",),
    )
    assert harness.refusal() == "ALREADY_ALIGNED"
    assert harness.store.commits == 1


def test_realign_after_a_twin_realignment_points_the_design_to_the_new_twin_versions():
    harness = after_change(requirements_with_revised_twins)

    version = harness.realign().version

    assert version.package.grounding.user_twin_references == (FRONT_DESK, AUDITOR)
    assert {critique.user_twin_reference for critique in version.package.critiques} == {
        FRONT_DESK,
        AUDITOR,
    }


@pytest.mark.parametrize("name", BLOCKERS)
def test_realign_refuses_with_the_code_of_the_blocker_and_writes_nothing(name):
    harness = blocked(name)

    failure = harness.failure()

    assert failure.code == name
    assert failure.missing_codes == (
        MISSING_CODES if name == "REQUIREMENT_NO_LONGER_AVAILABLE" else ()
    )
    assert harness.nothing_written()


@pytest.mark.parametrize(
    "status",
    [
        DesignVersionAppendStatus.VERSION_CONFLICT,
        DesignVersionAppendStatus.CONTENT_CONFLICT,
        DesignVersionAppendStatus.PROJECT_NOT_FOUND,
    ],
)
def test_realign_refuses_an_append_the_repository_rejects(status):
    harness = after_change()
    harness.store.refusal = status

    assert harness.refusal() == "PERSISTENCE_REJECTED"
    assert harness.nothing_written()


def test_realign_for_another_owner_finds_no_design():
    harness = after_change()

    assert harness.refusal(STRANGER_ID) == "DESIGN_NOT_FOUND"
    assert harness.nothing_written()


def test_without_injected_identity_and_clock_the_realignment_uses_a_random_id_and_utc_time():
    harness = after_change(injected=False)

    version = harness.realign().version

    assert version.id not in {REALIGNED_ID, harness.before[0].id}
    assert version.created_at.utcoffset().total_seconds() == 0
