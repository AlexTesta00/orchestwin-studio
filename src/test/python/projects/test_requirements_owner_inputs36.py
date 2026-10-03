import asyncio
from dataclasses import replace

import pytest

from orchestwin.models.fake_requirements import FakeDeterministicRequirementsAdapter
from orchestwin.projects.owner_requirements import OwnerRequirementsService, owner_specification
from orchestwin.projects.requirements_application import (
    RequirementsGenerationIssueCode,
    RequirementsGenerationStatus,
)
from orchestwin.projects.requirements_primitives import RequirementSourceKind
from src.test.python.projects.test_requirements_application import (
    CREATED_AT,
    OWNER_ID,
    PROJECT_ID,
    VERSION_ID,
    FakeGovernance,
    InMemorySpecifications,
    InMemoryUnitOfWork,
    governed_context,
)
from src.test.python.projects.test_requirements_needs import enriched_specification
from src.test.python.projects.test_requirements_specifications import build_specification


class LockedUnit(InMemoryUnitOfWork):
    async def lock_project(self, *, project_id):
        assert project_id == PROJECT_ID
        self.locked = True
        return True


def command_fixture():
    context = governed_context()
    generated = asyncio.run(
        FakeDeterministicRequirementsAdapter().propose(context.to_proposal_request())
    ).specification
    specification = enriched_specification(generated)
    repository = InMemorySpecifications()
    unit = LockedUnit(repository)
    governance = FakeGovernance(context)
    service = OwnerRequirementsService(
        governance_port=governance,
        uow_factory=lambda **_: unit,
        uuid_factory=lambda: VERSION_ID,
        clock=lambda: CREATED_AT,
    )
    return context, specification, repository, unit, governance, service


def test_owner_definition_is_complete_version_one_with_inspectable_owner_sources():
    _, specification, repository, unit, _, service = command_fixture()
    original = specification.to_snapshot()
    result = asyncio.run(
        service.create(owner_user_id=OWNER_ID, project_id=PROJECT_ID, specification=specification)
    )
    assert result.status is RequirementsGenerationStatus.CREATED
    assert unit.locked and unit.committed
    assert repository.versions == [result.version]
    assert specification.to_snapshot() == original
    supplied = result.version.specification
    assert supplied.schema_version == 2
    assert supplied.journeys == ()
    assert all(
        any(source.kind is RequirementSourceKind.OWNER_INPUT for source in artifact.sources)
        for collection in (
            supplied.requirements,
            supplied.scenarios,
            supplied.needs,
            supplied.risks,
        )
        for artifact in collection
    )
    assert result.version.version_number == 1
    assert result.version.based_on_version_number is None
    assert owner_specification(supplied, owner_user_id=OWNER_ID) == supplied
    duplicate = asyncio.run(
        service.create(owner_user_id=OWNER_ID, project_id=PROJECT_ID, specification=specification)
    )
    assert duplicate.issue is RequirementsGenerationIssueCode.SPECIFICATION_ALREADY_EXISTS


@pytest.mark.parametrize("case", ("legacy", "gate", "context", "stale"))
def test_owner_definition_refuses_missing_approval_or_inexact_context_without_writes(case):
    context, specification, repository, unit, governance, service = command_fixture()
    expected = RequirementsGenerationIssueCode.INVALID_PROPOSAL
    if case == "legacy":
        specification = build_specification()
    elif case == "gate":
        governance._contexts = [replace(context, user_modeling_gate=None)]
        expected = RequirementsGenerationIssueCode.USER_MODELING_APPROVAL_REQUIRED
    elif case == "context":
        specification = replace(
            specification,
            project_brief_reference=replace(
                specification.project_brief_reference, version_number=2
            ),
        )
    else:
        governance._contexts = [context, replace(context, team_gate=None)]
        expected = RequirementsGenerationIssueCode.CONTEXT_CHANGED
    result = asyncio.run(
        service.create(owner_user_id=OWNER_ID, project_id=PROJECT_ID, specification=specification)
    )
    assert result.issue is expected
    assert not repository.versions
    assert not unit.committed


def test_historical_definition_hash_is_unchanged_and_schema_one_is_not_a_manual_escape():
    legacy = build_specification()
    assert legacy.content_hash == "cb85823113b3ff2dbe48569c13c0f8080b14085830a04e73de081aec8f083e47"
    with pytest.raises(ValueError, match="OWNER_SPECIFICATION_SCHEMA_2_REQUIRED"):
        owner_specification(legacy, owner_user_id=OWNER_ID)
