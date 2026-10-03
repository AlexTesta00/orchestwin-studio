from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.agents.owner_inputs import OwnerTeamInputError, owner_team_proposal
from orchestwin.agents.proposals import (
    TeamProposalApplicationResult,
    TeamProposalApplicationStatus,
    TeamProposalRevisionKind,
    TeamProposalVersion,
)
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.requirements import RequirementsSpecificationPayload
from orchestwin.api.teams import create_team_router
from orchestwin.api.user_modeling import ProfileObservationPayload, create_user_modeling_router
from orchestwin.projects.requirements_application import (
    RequirementsGenerationResult,
    RequirementsGenerationStatus,
)
from orchestwin.twins.user_twins import UserTwinField
from src.test.python.agents.test_team_owner_inputs36 import selection, supplied_context
from src.test.python.agents.test_team_proposal_application import NOW, OWNER_ID, PROJECT_ID
from src.test.python.api.test_requirements_api import client_fixture as requirements_client
from src.test.python.api.test_requirements_api import path, specification_version
from src.test.python.api.test_user_modeling_api import build_dependencies, project_path
from src.test.python.projects.test_requirements_needs import enriched_specification
from src.test.python.twins.test_twin_owner_inputs36 import command_fixture as twin_fixture


def test_owner_team_http_create_is_owner_scoped_and_returns_explicit_origin():
    context = supplied_context()
    selected, rationales = selection(context)
    proposal = owner_team_proposal(context, selected, rationales)
    version = TeamProposalVersion(
        id=PROJECT_ID,
        project_id=PROJECT_ID,
        version_number=1,
        proposal=proposal,
        revision_kind=TeamProposalRevisionKind.OWNER_PROVIDED,
        created_by_user_id=OWNER_ID,
        created_at=NOW,
    )
    service = AsyncMock()
    service.create.return_value = TeamProposalApplicationResult(
        status=TeamProposalApplicationStatus.CREATED,
        version=version,
        issues=proposal.constraints.issues,
    )
    app = FastAPI()
    app.state.owner_team_inputs = service
    app.include_router(create_team_router())
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id=OWNER_ID)
    payload = {
        "selected_agent_ids": [value.value for value in selected],
        "owner_rationales": [
            {"agent_id": value.agent_id.value, "statement": value.statement} for value in rationales
        ],
    }
    with TestClient(app) as client:
        response = client.post(f"/projects/{PROJECT_ID}/team/owner-proposals", json=payload)
        assert response.status_code == 201
        assert response.json()["version"]["revision_kind"] == "OWNER_PROVIDED"
        assert service.create.call_args.kwargs["owner_user_id"] == OWNER_ID
        service.create.side_effect = OwnerTeamInputError("TEAM_PROPOSAL_ALREADY_EXISTS")
        duplicate = client.post(f"/projects/{PROJECT_ID}/team/owner-proposals", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "TEAM_PROPOSAL_ALREADY_EXISTS"
    service.generate.assert_not_called()


def test_owner_definition_http_requires_complete_schema_two_and_never_queues_generation():
    client, generation, _, _, _ = requirements_client()
    version = specification_version()
    specification = enriched_specification(version.specification)
    version = replace(version, specification=specification, content_hash=specification.content_hash)
    service = AsyncMock()
    service.create.return_value = RequirementsGenerationResult(
        status=RequirementsGenerationStatus.CREATED, version=version
    )
    client.app.state.owner_requirements = service
    payload = RequirementsSpecificationPayload.from_domain(specification).model_dump(mode="json")
    with client:
        supplied = client.post(path("/owner-specifications"), json={"specification": payload})
        assert supplied.status_code == 201
        assert service.create.call_args.kwargs["specification"] == specification
        payload["requirements"][0]["need_ids"] = []
        invalid = client.post(path("/owner-specifications"), json={"specification": payload})
        legacy = RequirementsSpecificationPayload.from_domain(
            specification_version().specification
        ).model_dump(mode="json")
        refused = client.post(path("/owner-specifications"), json={"specification": legacy})
    assert invalid.status_code == 422
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "OWNER_SPECIFICATION_SCHEMA_2_REQUIRED"
    assert service.create.await_count == 1
    assert generation.calls == []


def test_owner_profiles_http_preserves_epistemics_and_does_not_request_a_model():
    data, _, _, _, _, service = twin_fixture()
    dependencies, commands, _, _, _ = build_dependencies()
    app = FastAPI()
    app.include_router(create_user_modeling_router(replace(dependencies, owner_inputs=service)))
    observations = []
    for observation in data.observations:
        payload = ProfileObservationPayload.from_domain(observation).model_dump(mode="json")
        key = payload.pop("observation_key")
        payload["field"] = next(
            field.value for field in UserTwinField if field.observation_key == key
        )
        observations.append(payload)
    payload = {
        "profiles": [
            {"persona_id": str(data.persona_id), "name": data.name, "observations": observations}
        ]
    }
    with TestClient(app) as client:
        response = client.post(project_path("/owner-profiles"), json=payload)
        assert response.status_code == 201
        snapshot = response.json()["snapshot_version"]
        assert snapshot["version_number"] == 1
        assert snapshot["snapshot"]["twin_count"] == 1
        duplicate = client.post(project_path("/owner-profiles"), json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "SNAPSHOT_ALREADY_EXISTS"
    assert commands.snapshot_calls == []
    assert commands.proposal_calls == []
