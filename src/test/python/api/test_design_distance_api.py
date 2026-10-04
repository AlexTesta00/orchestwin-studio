from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.design import DesignPackagePayload
from orchestwin.api.design_distance import DesignDistancePayload, create_design_distance_router
from orchestwin.api.services import ApplicationRuntime
from orchestwin.artifacts.design_distance import design_distance_report
from orchestwin.config import ApplicationSettings, LogLevel, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.models.generated_mockup_drafts import bind_generated_mockup
from src.test.python.artifacts.test_visual_directions import axes, directed_language, direction
from src.test.python.models.test_generated_mockup_support import (
    DASHBOARD,
    DASHBOARD_ID,
    GUIDED,
    GUIDED_ID,
    OWNER_ID,
    PROJECT_ID,
    STRANGER_ID,
    DesignVersions,
    MemoryMockupStore,
    ScriptedMockupGenerator,
    applied_package,
    draft,
    package,
    requirements_version,
    runtime,
)

NOW = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
PREFIX = "/api/v1"
DISTANCE = f"{PREFIX}/projects/{PROJECT_ID}/design/distance"
TEMPLATE = f"{PREFIX}/projects/{{project_id}}/design/distance"
DIRECTIONS = {
    GUIDED_ID: direction(
        name="Registro stampato",
        axes=axes("EDITORIAL", "SQUARE_RULES", "DISPLAY", "INK", "SPACIOUS"),
    ),
    DASHBOARD_ID: direction(
        name="Banco di lavoro", axes=axes("WORKBENCH", "PILL", "CAPS_LABELS", "TINTED", "SPACIOUS")
    ),
}


class KeptMockups(MemoryMockupStore):
    def __init__(self, results=None):
        super().__init__()
        self.results = dict(results or {})
        self.reads = []

    async def latest_design_mockup(
        self, *, owner_user_id, project_id, design_content_hashes, alternative_id, purposes
    ):
        self.reads.append(alternative_id)
        result = self.results.get(alternative_id)
        if (
            result is None
            or (owner_user_id, project_id) != (OWNER_ID, PROJECT_ID)
            or result["design_content_hash"] not in tuple(design_content_hashes)
        ):
            return None
        return result


def user(identifier=OWNER_ID):
    return UserAccount(
        id=identifier,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def client_for(runtime_value, *, identity=OWNER_ID):
    application = FastAPI()
    application.state.application_runtime = runtime_value
    application.include_router(create_design_distance_router(), prefix=PREFIX)
    application.dependency_overrides[current_user_dependency] = lambda: user(identity)
    return TestClient(application)


def directed(package_value):
    return replace(
        package_value,
        alternatives=tuple(
            replace(
                item,
                visual_language=directed_language(item.visual_language, DIRECTIONS[item.id]),
            )
            for item in package_value.alternatives
        ),
    )


def kept_result(version, alternative_id=DASHBOARD_ID, name=DASHBOARD):
    chosen = next(item for item in version.package.alternatives if item.id == alternative_id)
    binding = bind_generated_mockup(
        draft(name), alternative=chosen, requirements=requirements_version(), language="it"
    )
    stored = replace(
        version.package,
        owner_selected_alternative_id=alternative_id,
        prototype=binding.prototype,
        generated_mockup=binding.mockup,
    )
    result = {
        "status": "MOCKUP_GENERATED",
        "generation_id": str(uuid4()),
        "design_version_id": str(version.id),
        "design_content_hash": version.content_hash,
        "package": DesignPackagePayload.from_domain(stored).model_dump(mode="json"),
        "approach": "Le schermate seguono il lavoro della volontaria al banco.",
        "changes": [],
        "warnings": [],
        "cost_microusd": 0,
    }
    return result, binding.mockup.mockup


def wire(report):
    return json.loads(json.dumps(report))


def test_a_design_without_mockups_answers_an_unknown_verdict() -> None:
    versions = DesignVersions(package())
    store = KeptMockups()
    generator = ScriptedMockupGenerator()
    client = client_for(runtime(generator, store, versions))

    answer = client.get(DISTANCE)

    version = versions.versions[-1]
    body = answer.json()
    assert answer.status_code == 200
    assert body == wire(design_distance_report(version, {}))
    assert DesignDistancePayload.model_validate(body).model_dump(mode="json") == body
    assert body["design_version_id"] == str(version.id)
    assert body["design_content_hash"] == version.content_hash
    [pair] = body["pairs"]
    assert (pair["first"], pair["second"], pair["verdict"]) == ("DES-001", "DES-002", "UNKNOWN")
    assert pair["declared"]["axes_different"] is None
    assert pair["declared"]["choices_total"] == 22
    assert pair["styles"] == {"available": False, "score": None, "differences": []}
    assert pair["structure"] == {"available": False, "score": None, "differences": []}
    assert body["alternatives"] == [
        {"code": "DES-001", "direction": None, "adherence": {"available": False, "axes": {}}},
        {"code": "DES-002", "direction": None, "adherence": {"available": False, "axes": {}}},
    ]
    assert store.reads == [GUIDED_ID, DASHBOARD_ID]


def test_two_kept_mockups_are_measured_with_the_tokens_of_their_alternatives() -> None:
    versions = DesignVersions(directed(applied_package()))
    version = versions.versions[-1]
    result, dashboard = kept_result(version)
    store = KeptMockups({DASHBOARD_ID: result})
    generator = ScriptedMockupGenerator()
    client = client_for(runtime(generator, store, versions))

    answer = client.get(DISTANCE)

    applied = version.package.generated_mockup.mockup
    expected = design_distance_report(version, {GUIDED_ID: applied, DASHBOARD_ID: dashboard})
    body = answer.json()
    assert answer.status_code == 200
    assert body == wire(expected)
    [pair] = body["pairs"]
    assert pair["styles"]["available"] is pair["structure"]["available"] is True
    assert pair["verdict"] in {"FAR", "CLOSE"}
    assert pair["declared"]["axes"] == ["layout", "shape", "type", "colour"]
    assert pair["declared"]["score"] == 80
    assert [item["direction"] for item in body["alternatives"]] == [
        "Registro stampato",
        "Banco di lavoro",
    ]
    assert all(item["adherence"]["available"] for item in body["alternatives"])
    assert store.reads == [DASHBOARD_ID]


def test_the_newest_kept_mockups_are_used_when_none_is_applied() -> None:
    versions = DesignVersions(directed(package()))
    version = versions.versions[-1]
    guided_result, guided = kept_result(version, GUIDED_ID, GUIDED)
    dashboard_result, dashboard = kept_result(version)
    store = KeptMockups({GUIDED_ID: guided_result, DASHBOARD_ID: dashboard_result})
    client = client_for(runtime(ScriptedMockupGenerator(), store, versions))

    answer = client.get(DISTANCE)

    assert answer.status_code == 200
    assert answer.json() == wire(
        design_distance_report(version, {GUIDED_ID: guided, DASHBOARD_ID: dashboard})
    )
    assert store.reads == [GUIDED_ID, DASHBOARD_ID]


def test_an_alternative_without_a_kept_mockup_has_no_mockup_in_the_report() -> None:
    versions = DesignVersions(directed(applied_package()))
    version = versions.versions[-1]
    client = client_for(
        SimpleNamespace(
            proposal_evidence_store=None,
            design_query_service=versions,
            real_model_runtime=None,
        )
    )

    answer = client.get(DISTANCE)

    body = answer.json()
    assert answer.status_code == 200
    assert body == wire(
        design_distance_report(version, {GUIDED_ID: version.package.generated_mockup.mockup})
    )
    assert body["pairs"][0]["verdict"] == "UNKNOWN"
    assert body["alternatives"][0]["adherence"]["available"] is True
    assert body["alternatives"][1]["adherence"] == {"available": False, "axes": {}}


def test_a_project_without_a_design_answers_the_design_not_found_problem() -> None:
    versions = DesignVersions(package())
    client = client_for(runtime(ScriptedMockupGenerator(), KeptMockups(), versions))

    answer = client.get(f"{PREFIX}/projects/{uuid4()}/design/distance")

    assert answer.status_code == 404
    assert answer.json() == {"detail": {"code": "DESIGN_PACKAGE_NOT_FOUND"}}


def test_another_owner_cannot_read_the_distance() -> None:
    versions = DesignVersions(directed(applied_package()))
    version = versions.versions[-1]
    result, _dashboard = kept_result(version)
    store = KeptMockups({DASHBOARD_ID: result})
    client = client_for(runtime(ScriptedMockupGenerator(), store, versions), identity=STRANGER_ID)

    answer = client.get(DISTANCE)

    assert answer.status_code == 404
    assert answer.json() == {"detail": {"code": "DESIGN_PACKAGE_NOT_FOUND"}}
    assert store.reads == []


def test_reading_the_distance_writes_nothing_and_calls_no_provider() -> None:
    versions = DesignVersions(directed(applied_package()))
    version = versions.versions[-1]
    result, _dashboard = kept_result(version)
    store = KeptMockups({DASHBOARD_ID: result})
    generator = ScriptedMockupGenerator()
    client = client_for(runtime(generator, store, versions))

    first = client.get(DISTANCE)
    second = client.get(DISTANCE)
    refused = [client.post(DISTANCE), client.put(DISTANCE), client.delete(DISTANCE)]

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert [item.status_code for item in refused] == [405, 405, 405]
    assert generator.calls == []
    assert store.requests == {}
    assert store.events == {}
    assert store.reads == [DASHBOARD_ID, DASHBOARD_ID]
    assert versions.versions == [version]


def test_the_application_serves_the_distance_next_to_the_design_routes() -> None:
    settings = ApplicationSettings(
        application_name="OrchesTwin Design Distance Test",
        environment=RuntimeEnvironment.TEST,
        debug=False,
        log_level=LogLevel.INFO,
        api_prefix=PREFIX,
        _env_file=None,
    )
    versions = DesignVersions(package())
    served = create_app(
        settings,
        runtime=ApplicationRuntime(design_query_service=versions, proposal_evidence_store=None),
        auth_settings=AuthApiSettings(_env_file=None),
    )
    empty = create_app(
        settings, runtime=ApplicationRuntime(), auth_settings=AuthApiSettings(_env_file=None)
    )
    for application in (served, empty):
        application.dependency_overrides[current_user_dependency] = user

    operation = served.openapi()["paths"][TEMPLATE]
    with TestClient(served) as client:
        answer = client.get(DISTANCE)
    with TestClient(empty) as client:
        unavailable = client.get(DISTANCE)

    assert set(operation) == {"get"}
    assert operation["get"]["operationId"] == "getDesignDistance"
    assert operation["get"]["tags"] == ["design"]
    assert answer.status_code == 200
    assert answer.json() == wire(design_distance_report(versions.versions[-1], {}))
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": {"code": "DESIGN_QUERY_UNAVAILABLE"}}


def test_the_response_model_mirrors_the_report_of_the_contract() -> None:
    application = FastAPI()
    application.include_router(create_design_distance_router(), prefix=PREFIX)
    schemas = application.openapi()["components"]["schemas"]

    assert set(schemas["DesignDistancePayload"]["properties"]) == {
        "distance_version",
        "design_version_id",
        "design_content_hash",
        "pairs",
        "alternatives",
    }
    assert set(schemas["DistancePairPayload"]["properties"]) == {
        "first",
        "second",
        "declared",
        "styles",
        "structure",
        "verdict",
    }
    assert set(schemas["DeclaredDistancePayload"]["properties"]) == {
        "score",
        "axes_different",
        "axes",
        "choices_different",
        "choices_total",
        "primary_colour_distance",
    }
    for name in ("StyleDistancePayload", "StructureDistancePayload"):
        assert set(schemas[name]["properties"]) == {"available", "score", "differences"}
    assert set(schemas["AlternativeDistancePayload"]["properties"]) == {
        "code",
        "direction",
        "adherence",
    }
    assert set(schemas["DirectionAdherencePayload"]["properties"]) == {"available", "axes"}
    assert schemas["DistanceVerdict"]["enum"] == ["FAR", "CLOSE", "UNKNOWN"]
    assert schemas["AdherenceStatus"]["enum"] == ["FOLLOWED", "NOT_FOLLOWED", "NOT_CHECKED"]
