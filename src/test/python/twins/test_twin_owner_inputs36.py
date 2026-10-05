import asyncio
from dataclasses import replace

import pytest

from orchestwin.twins.application import (
    UserModelingApplicationIssueCode,
    UserModelingApplicationStatus,
)
from orchestwin.twins.epistemics import (
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    ObservationProvenance,
)
from orchestwin.twins.owner_inputs import OwnerTwinInput, OwnerUserModelingService
from orchestwin.twins.representation import TwinBasis, twin_view
from orchestwin.twins.user_twins import UserTwinLifecycleStatus
from src.test.python.twins.test_user_modeling_application import (
    CREATED_AT,
    OWNER_ID,
    PROJECT_ID,
    DeterministicUuidFactory,
    FakeGovernancePort,
    MemoryStore,
    MemoryUowFactory,
    TransactionTracker,
    changed_team_context,
    ready_context,
)
from src.test.python.twins.test_user_twins import complete_twin_observations, persona_version


def command_fixture():
    persona = persona_version()
    observations = tuple(
        replace(
            value,
            epistemic_status=EpistemicStatus.USER_PROVIDED,
            provenance=ObservationProvenance.from_references(
                (
                    EvidenceReference(
                        source_kind=EvidenceSourceKind.OWNER_INPUT,
                        source_id=str(OWNER_ID),
                        locator=value.observation_key,
                    ),
                )
            ),
        )
        for value in complete_twin_observations()
    )
    data = OwnerTwinInput(persona.persona_id, "Reception supplied profile", observations)
    store = MemoryStore()
    store.personas[(PROJECT_ID, persona.persona_id)] = [persona]
    tracker = TransactionTracker()
    context = ready_context()
    governance = FakeGovernancePort([context])
    service = OwnerUserModelingService(
        governance_port=governance,
        uow_factory=MemoryUowFactory(store=store, tracker=tracker),
        uuid_factory=DeterministicUuidFactory(),
        clock=lambda: CREATED_AT,
    )
    return data, store, tracker, context, governance, service


def test_initial_owner_twin_is_grounded_and_provisional_without_synthetic_generation():
    data, store, tracker, _, _, service = command_fixture()
    original = data.observations
    result = asyncio.run(
        service.create(owner_user_id=OWNER_ID, project_id=PROJECT_ID, profiles=(data,))
    )
    assert result.status is UserModelingApplicationStatus.CREATED
    assert tracker.commits == 1 and tracker.locks == 1
    twin = result.twin_versions[0]
    assert twin.profile.validation_status is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT
    assert twin_view(twin)["basis"] == TwinBasis.PROVISIONAL.value
    assert data.observations == original
    assert all(
        value.provenance.references[-1].source_id == "owner-provided-profile"
        for value in twin.profile.observations
    )
    assert store.snapshots[PROJECT_ID] == [result.snapshot_version]
    duplicate = asyncio.run(
        service.create(owner_user_id=OWNER_ID, project_id=PROJECT_ID, profiles=(data,))
    )
    assert duplicate.issue is UserModelingApplicationIssueCode.SNAPSHOT_ALREADY_EXISTS


@pytest.mark.parametrize("case", ("missing", "partial", "duplicate", "pending", "stale", "other"))
def test_initial_owner_twin_rejects_incomplete_or_unapproved_context_before_writes(case):
    data, store, tracker, context, governance, service = command_fixture()
    profiles = (data,)
    owner = OWNER_ID
    expected = UserModelingApplicationIssueCode.INVALID_PROPOSAL
    if case == "missing":
        store.personas.clear()
        expected = UserModelingApplicationIssueCode.PERSONAS_REQUIRED
    elif case == "partial":
        profiles = (replace(data, observations=data.observations[:1]),)
    elif case == "duplicate":
        profiles = (data, data)
    elif case == "pending":
        tracker.pending_revision = True
        expected = UserModelingApplicationIssueCode.USER_TWIN_REVISION_PENDING
    elif case == "stale":
        governance.set_contexts([context, changed_team_context(context)])
        expected = UserModelingApplicationIssueCode.CONTEXT_CHANGED
    else:
        owner = PROJECT_ID
        expected = UserModelingApplicationIssueCode.PROJECT_NOT_FOUND
    result = asyncio.run(
        service.create(owner_user_id=owner, project_id=PROJECT_ID, profiles=profiles)
    )
    assert result.issue is expected
    assert not store.twins and not store.snapshots
    assert tracker.commits == 0
