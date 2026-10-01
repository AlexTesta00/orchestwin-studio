from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.api.user_modeling import (
    UserModelingApiDependencies,
    UserModelingSnapshotVersionPayload,
    create_user_modeling_router,
)
from orchestwin.config import ApplicationSettings
from orchestwin.twins.archetypes import ArchetypeFailure, ArchetypeIssue
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
    ObservationValue,
    ObservationValueKind,
    ProfileObservation,
)
from orchestwin.twins.user_modeling_gate import user_modeling_artifact_reference
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinField,
    UserTwinProfileVersion,
    VersionedArtifactReference,
    create_project_grounded_user_twin,
    create_user_modeling_snapshot,
)
from orchestwin.workflow.gates import (
    HumanGateAction,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)
from src.test.python.twins.test_archetypes import (
    NOW,
    OWNER,
    PROJECT,
    MemoryStore,
    create,
    data,
    run,
)

PREFIX = f"/api/v1/projects/{PROJECT}/user-modeling"
BODY = {
    "name": "Reception staff",
    "description": "Checks reservations at the front desk.",
    "role": "Receptionist",
    "goals": ["Check today's reservations"],
    "context": "Hotel front desk",
}


async def owner():
    return SimpleNamespace(id=OWNER)


def app_for(service=None):
    app = create_app(
        ApplicationSettings(_env_file=None),
        runtime=ApplicationRuntime(archetype_service=service),
        auth_settings=AuthApiSettings(_env_file=None),
    )
    app.dependency_overrides[current_user_dependency] = owner
    return app


def test_standard_app_registers_and_injects_archetype_contract():
    store = MemoryStore()
    service = store.service()
    app = app_for(service)
    assert app.state.archetype_service is service
    paths = app.openapi()["paths"]
    template = "/api/v1/projects/{project_id}/user-modeling/archetypes"
    assert set(paths[template]) == {"get", "post"}
    assert set(paths[template + "/{persona_id}"]) == {"patch", "delete"}
    assert "ArchetypePayload" in app.openapi()["components"]["schemas"]
    with TestClient(app) as client:
        response = client.post(PREFIX + "/archetypes", json=BODY)
        assert response.status_code == 201
        first = response.json()
        assert set(first) == {
            "persona_id",
            "version_id",
            "version_number",
            "name",
            "description",
            "role",
            "goals",
            "context",
            "source",
            "confirmation_status",
            "archived",
        }
        assert first["confirmation_status"] == "CONFIRMED"
        assert client.get(PREFIX + "/archetypes").json() == [first]
        path = PREFIX + "/archetypes/" + first["persona_id"]
        same = client.patch(path, json=BODY | {"based_on_version_number": 1})
        assert same.status_code == 200 and same.json() == first
        edited = client.patch(
            path, json=BODY | {"name": "Night staff", "based_on_version_number": 1}
        )
        assert edited.status_code == 200
        assert edited.json()["persona_id"] == first["persona_id"]
        assert edited.json()["version_number"] == 2
        stale = client.request("DELETE", path, json={"based_on_version_number": 1})
        assert stale.status_code == 409
        assert stale.json() == {"detail": {"code": "ARCHETYPE_VERSION_CONFLICT"}}
        archived = client.request("DELETE", path, json={"based_on_version_number": 2})
        assert archived.status_code == 200 and archived.json()["archived"]
        assert archived.json()["version_number"] == 3
        assert client.get(PREFIX + "/archetypes").json() == []
    assert len(store.versions) == 3


def test_authentication_precedes_archetype_service_access():
    service = SimpleNamespace(list_current=AsyncMock())
    app = app_for(service)
    app.state.identity_service = SimpleNamespace(current_user=AsyncMock())
    app.dependency_overrides.clear()
    with TestClient(app) as client:
        assert client.get(PREFIX + "/archetypes").status_code == 401
    service.list_current.assert_not_awaited()


def test_authenticated_owner_cannot_read_a_foreign_project():
    store = MemoryStore()
    app = app_for(store.service())
    with TestClient(app) as client:
        response = client.get(f"/api/v1/projects/{uuid4()}/user-modeling/archetypes")
    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "PROJECT_NOT_FOUND"}}


def test_missing_service_is_explicitly_unavailable():
    with TestClient(app_for()) as client:
        response = client.get(PREFIX + "/archetypes")
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "ARCHETYPE_SERVICE_UNAVAILABLE"}}


@pytest.mark.parametrize("issue", list(ArchetypeIssue))
def test_domain_failures_preserve_only_the_public_error_code(issue):
    service = SimpleNamespace(list_current=AsyncMock(side_effect=ArchetypeFailure(issue)))
    with TestClient(app_for(service)) as client:
        response = client.get(PREFIX + "/archetypes")
    expected = (
        404
        if issue in {ArchetypeIssue.PROJECT_NOT_FOUND, ArchetypeIssue.ARCHETYPE_NOT_FOUND}
        else 409
    )
    assert response.status_code == expected
    assert response.json() == {"detail": {"code": issue.value}}


@pytest.mark.parametrize(
    "changes",
    [
        {"name": " "},
        {"description": " "},
        {"role": ""},
        {"context": ""},
        {"name": "a" * 201},
        {"description": "a" * 4001},
        {"role": "a" * 4001},
        {"context": "a" * 4001},
        {"goals": ["a" * 2001]},
        {"goals": [" x", "x "]},
        {"goals": [False]},
        {"goals": "a"},
        {"name": 5},
        {"extra": "forbidden"},
    ],
)
def test_invalid_manual_input_is_422_before_any_transaction(changes):
    store = MemoryStore()
    with TestClient(app_for(store.service())) as client:
        response = client.post(PREFIX + "/archetypes", json=BODY | changes)
    assert response.status_code == 422
    assert store.events == []


@pytest.mark.parametrize("base", [0, -1, True, 1.5, "1", None])
@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_invalid_base_version_is_rejected_before_service_access(base, method):
    store = MemoryStore()
    with TestClient(app_for(store.service())) as client:
        response = client.request(
            method,
            PREFIX + f"/archetypes/{uuid4()}",
            json=({} if method == "DELETE" else BODY) | {"based_on_version_number": base},
        )
    assert response.status_code == 422 and store.events == []


def test_unknown_optional_historical_fields_are_returned_without_mutating_the_profile():
    store = MemoryStore()
    historical = create(store, goals=(), context=None)
    before = historical.to_snapshot()
    with TestClient(app_for(store.service())) as client:
        response = client.get(PREFIX + "/archetypes")
    assert response.status_code == 200
    assert response.json()[0]["goals"] == [] and response.json()[0]["context"] is None
    assert historical.to_snapshot() == before


def snapshot(persona):
    reference = VersionedArtifactReference(
        artifact_id=uuid4(), version_number=1, content_hash="a" * 64
    )
    team = VersionedArtifactReference(artifact_id=uuid4(), version_number=1, content_hash="b" * 64)
    optional = {
        UserTwinField.AGE_RANGE,
        UserTwinField.DESCRIPTION,
        UserTwinField.REPRESENTS,
        UserTwinField.DOES_NOT_REPRESENT,
        UserTwinField.EVIDENCE_GAPS,
    }
    observations = []
    for field in UserTwinField:
        if field in optional:
            continue
        value = {
            UserTwinField.ROLE: ObservationValue.from_text("Receptionist"),
            UserTwinField.GOALS: ObservationValue.from_items(("Check reservations",)),
            UserTwinField.CONTEXT_OF_USE: ObservationValue.from_text("Hotel front desk"),
            UserTwinField.INFORMATION_NEEDS: ObservationValue.from_items(("Reservation details",)),
        }.get(field, ObservationValue.unknown())
        observations.append(
            ProfileObservation(
                observation_key=field.observation_key,
                value=value,
                epistemic_status=EpistemicStatus.USER_PROVIDED,
                confidence=ConfidenceScore(
                    0.0 if value.kind is ObservationValueKind.UNKNOWN else 1.0
                ),
                provenance=ObservationProvenance.from_references(
                    (
                        EvidenceReference(
                            source_kind=EvidenceSourceKind.OWNER_INPUT,
                            source_id=str(OWNER),
                            locator=field.observation_key,
                        ),
                    )
                ),
                human_validation=HumanValidationRequirement.NOT_REQUIRED,
                rationale="The owner described this context.",
            )
        )
    profile = create_project_grounded_user_twin(
        name="Reception Twin",
        persona_version=persona,
        project_brief_reference=reference,
        agent_team_reference=team,
        catalog_version=1,
        catalog_content_hash="c" * 64,
        observations=observations,
    )
    twin = UserTwinProfileVersion(
        id=uuid4(),
        project_id=PROJECT,
        twin_id=uuid4(),
        version_number=1,
        profile=profile,
        content_hash=profile.content_hash,
        created_by_user_id=OWNER,
        created_at=NOW,
    )
    modeling = create_user_modeling_snapshot(
        project_id=PROJECT,
        project_brief_reference=reference,
        agent_team_reference=team,
        catalog_version=1,
        catalog_content_hash="c" * 64,
        persona_versions=(persona,),
        twin_versions=(twin,),
    )
    return UserModelingSnapshotVersion(
        id=uuid4(),
        project_id=PROJECT,
        version_number=1,
        snapshot=modeling,
        content_hash=modeling.content_hash,
        created_by_user_id=OWNER,
        created_at=NOW,
    )


def approved_gate(modeling):
    artifact = user_modeling_artifact_reference(modeling)
    gate = create_human_gate(
        gate_id=uuid4(),
        project_id=PROJECT,
        owner_user_id=OWNER,
        gate_type=HumanGateType.USER_MODELING,
        artifact=artifact,
        created_at=NOW,
    )
    submitted = transition_human_gate(
        gate, action=HumanGateAction.SUBMIT, actor_user_id=OWNER, occurred_at=NOW, event_id=uuid4()
    )
    return transition_human_gate(
        submitted.gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER,
        occurred_at=NOW,
        event_id=uuid4(),
    ).gate


def test_readiness_changes_after_manual_edit_while_history_view_keeps_exact_archetype():
    store = MemoryStore()
    first = create(store)
    modeling = snapshot(first)
    gate = approved_gate(modeling)
    queries = SimpleNamespace(
        current_snapshot=AsyncMock(return_value=modeling),
        snapshot_history=AsyncMock(return_value=(modeling,)),
        current_personas=AsyncMock(return_value=(first,)),
    )
    app = FastAPI()
    app.include_router(
        create_user_modeling_router(
            UserModelingApiDependencies(
                commands=object(),
                revisions=object(),
                gates=SimpleNamespace(current_gate=AsyncMock(return_value=gate)),
                queries=queries,
                owner_user_id_dependency=lambda: OWNER,
            )
        ),
        prefix="/api/v1",
    )
    before = modeling.to_snapshot()
    with TestClient(app) as client:
        ready = client.get(PREFIX + "/readiness").json()
        assert ready["archetypes_current"] and ready["approved_current_snapshot"]
        current = run(
            store.service().edit(
                owner_user_id=OWNER,
                project_id=PROJECT,
                persona_id=first.persona_id,
                based_on_version_number=1,
                data=data(description="New description for a night shift."),
            )
        )
        queries.current_personas.return_value = (current,)
        stale = client.get(PREFIX + "/readiness").json()
        assert stale["context_current"]
        assert not stale["archetypes_current"] and not stale["approved_current_snapshot"]
        assert stale["workflow_state"] != "READY_FOR_REQUIREMENTS_DEFINITION"
        history = client.get(PREFIX + "/snapshots").json()[0]
    twin = history["snapshot"]["twin_versions"][0]
    view = twin["view"]
    assert view["basis"] == "PROVISIONAL"
    assert view["persona"]["description"]["value"]["text"] == BODY["description"]
    assert view["persona"]["description"]["provenance"][0]["source_id"] == str(OWNER)
    assert view["persona"]["needs"]["rationale"] == "The owner described this context."
    assert view["does_not_represent"]["display_status"] == "UNKNOWN"
    assert modeling.to_snapshot() == before and "view" not in before["snapshot"]["twin_versions"][0]


def test_twin_view_and_persona_claims_are_typed_in_openapi():
    app = app_for()
    schemas = app.openapi()["components"]["schemas"]
    for field in ("description", "role"):
        assert {
            item["type"] for item in schemas["ArchetypePayload"]["properties"][field]["anyOf"]
        } == {"string", "null"}
    assert schemas["UserTwinVersionPayload"]["properties"]["view"]["$ref"].endswith(
        "TwinViewPayload"
    )
    assert set(schemas["PersonaViewPayload"]["properties"]) == {
        "description",
        "goals",
        "needs",
        "behaviours",
        "pain_points",
        "constraints",
        "contexts",
    }
    assert "archetypes_current" in schemas["UserModelingReadinessPayload"]["properties"]


def test_snapshot_payload_preserves_existing_fields_and_content_hash():
    modeling = snapshot(create(MemoryStore()))
    payload = UserModelingSnapshotVersionPayload.from_domain(modeling)
    assert payload.content_hash == modeling.content_hash
    assert (
        payload.snapshot.twin_versions[0].content_hash
        == modeling.snapshot.twin_versions[0].content_hash
    )
    assert payload.snapshot.persona_versions[0].id == modeling.snapshot.persona_versions[0].id
