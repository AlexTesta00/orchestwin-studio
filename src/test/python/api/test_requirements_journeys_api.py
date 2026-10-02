from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from orchestwin.api.requirements import (
    JourneyPhasePayload,
    RequirementsArtifactEnvelope,
    RequirementsChangeRequest,
    RequirementsSpecificationPayload,
    UserJourneyPayload,
)
from orchestwin.projects.requirements_change_application import (
    RequirementsChangeIssueCode,
    RequirementsChangeResult,
    RequirementsChangeStatus,
)
from orchestwin.projects.requirements_revisions import RequirementsArtifactKind
from src.test.python.api.test_requirements_api import client_fixture, path, specification_version
from src.test.python.api.test_requirements_change_api import (
    CALL,
    CHANGES,
    OWNER_REQUEST,
    ScriptedChanges,
    application,
)
from src.test.python.projects.test_requirements_journeys import journey_specification


def test_journey_api_roundtrip_preserves_order_optional_touchpoint_and_sources():
    specification = journey_specification()
    payload = RequirementsSpecificationPayload.from_domain(specification)
    decoded = RequirementsSpecificationPayload.model_validate_json(payload.model_dump_json())
    assert decoded.to_domain() == specification
    journey = decoded.journeys[0]
    assert (
        UserJourneyPayload.model_validate_json(journey.model_dump_json()).to_domain()
        == specification.journeys[0]
    )
    assert journey.phases[0].touchpoint is None
    assert (
        JourneyPhasePayload.from_domain(specification.journeys[0].phases[1]).to_domain()
        == specification.journeys[0].phases[1]
    )


def test_journey_envelope_requires_the_selected_payload():
    journey = journey_specification().journeys[0]
    envelope = RequirementsArtifactEnvelope.from_domain(journey)
    assert envelope.kind is RequirementsArtifactKind.JOURNEY
    assert envelope.journey.to_domain() == journey
    assert RequirementsArtifactEnvelope.model_validate_json(envelope.model_dump_json()) == envelope
    with pytest.raises(ValidationError, match="selected payload"):
        RequirementsArtifactEnvelope(
            kind=RequirementsArtifactKind.NEED, journey=UserJourneyPayload.from_domain(journey)
        )


@pytest.mark.parametrize("value", ("true", "false", 1, 0, None, [], {}))
def test_include_journeys_api_flag_is_strict_boolean(value):
    with pytest.raises(ValidationError):
        RequirementsChangeRequest(request=OWNER_REQUEST, include_journeys=value)


@pytest.mark.parametrize("explicit_false", (False, True))
def test_default_and_false_journey_flags_keep_legacy_service_signature(explicit_false):
    class LegacyService:
        def __init__(self):
            self.calls = []

        async def request_change(self, *, owner_user_id, project_id, owner_request):
            self.calls.append(
                {
                    "owner_user_id": owner_user_id,
                    "project_id": project_id,
                    "owner_request": owner_request,
                }
            )
            return RequirementsChangeResult(
                status=RequirementsChangeStatus.REJECTED,
                issue=RequirementsChangeIssueCode.UNCHANGED,
            )

    service = LegacyService()
    body = {"request": OWNER_REQUEST}
    if explicit_false:
        body["include_journeys"] = False
    with TestClient(application(service)) as client:
        response = client.post(CHANGES, json=body)
    assert response.status_code == 409
    assert service.calls == [CALL]


def test_explicit_journey_flag_is_forwarded_on_the_existing_route():
    service = ScriptedChanges(
        RequirementsChangeResult(
            status=RequirementsChangeStatus.REJECTED, issue=RequirementsChangeIssueCode.UNCHANGED
        )
    )
    with TestClient(application(service)) as client:
        response = client.post(CHANGES, json={"request": OWNER_REQUEST, "include_journeys": True})
    assert response.status_code == 409
    assert service.calls == [{**CALL, "include_journeys": True}]


def test_current_endpoint_returns_journey_content_without_creating_a_revision():
    client, _generation, queries, revisions, _gates = client_fixture()
    version = specification_version()
    specification = journey_specification(version.specification)
    queries.version = replace(
        version, specification=specification, content_hash=specification.content_hash
    )
    with client:
        response = client.get(path("/current"))
    assert response.status_code == 200
    returned = RequirementsSpecificationPayload.model_validate(
        response.json()["specification"]
    ).to_domain()
    assert returned == specification
    assert revisions.proposed is None
