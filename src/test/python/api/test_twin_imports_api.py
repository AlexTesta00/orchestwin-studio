from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from starlette.types import Message

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.twin_imports import (
    MAX_TWIN_IMPORT_BODY_SIZE,
    create_twin_import_router,
    twin_import_request,
)
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.knowledge.twin_import import ImportedTwin, TwinImportError
from orchestwin.knowledge.twin_import_service import (
    ImportableTwin,
    TwinImportResult,
    TwinImportSource,
    TwinImportStatus,
)
from orchestwin.knowledge.twin_import_sources import TwinImportCandidate
from src.test.python.knowledge.test_twin_import import (
    OWNER_ID,
    SOURCE_PROJECT_ID,
    TARGET_PROJECT_ID,
    folder_document,
    imported_twin,
)

NOW = datetime(2026, 9, 27, 23, 30, tzinfo=UTC)
APPROVED_AT = datetime(2026, 9, 27, 18, 2, tzinfo=UTC)
EARLIER_APPROVED_AT = datetime(2026, 9, 25, 9, 15, tzinfo=UTC)
PATH = f"/api/v1/projects/{TARGET_PROJECT_ID}/user-modeling/twin-imports"
SOURCES_PATH = f"{PATH}/sources"
SOURCE_PATH = f"{PATH}/sources/{SOURCE_PROJECT_ID}"
OTHER_PROJECT_ID = UUID("00000000-0000-4000-8000-00000000c000")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000030")
OTHER_TWIN_ID = UUID("00000000-0000-4000-8000-000000000130")
FROM_PROJECT = {"source_project_id": str(SOURCE_PROJECT_ID), "twin_id": str(TWIN_ID)}
JSON_HEADERS = {"Content-Type": "application/json"}
CHUNK_SIZE = 256 * 1024
NOT_FOUND = ("PROJECT_NOT_FOUND", "SOURCE_PROJECT_NOT_FOUND", "SOURCE_TWIN_NOT_FOUND")
INVALID = ("TWIN_DOCUMENT_INVALID", "TWIN_DOCUMENT_UNSUPPORTED")
UNAVAILABLE = ("TWIN_IMPORT_SOURCES_UNAVAILABLE",)
CONFLICTS = (
    "BRIEF_APPROVAL_REQUIRED",
    "TEAM_APPROVAL_REQUIRED",
    "SOURCE_TWINS_NOT_APPROVED",
    "USER_TWINS_REQUIRED",
    "USER_TWINS_OUTDATED",
    "TWIN_BELONGS_TO_PROJECT",
    "TWIN_ALREADY_IMPORTED",
    "TWIN_LIMIT_REACHED",
    "TWIN_NAME_ALREADY_USED",
    "CONTEXT_CHANGED",
    "PERSISTENCE_REJECTED",
)


def user() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeTwinImportService:
    def __init__(self, *, error: TwinImportError | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.result = TwinImportResult(status=TwinImportStatus.IMPORTED, imported=imported_twin())
        self.listing = TwinImportSource(
            project_id=SOURCE_PROJECT_ID,
            project_name="Hotel Operations Studio",
            snapshot_version_number=2,
            approved_at=APPROVED_AT,
            twins=(
                ImportableTwin(
                    twin_id=TWIN_ID,
                    name="Receptionist Twin",
                    version_number=1,
                    content_hash="a" * 64,
                    validation_status="PROJECT_GROUNDED_UT",
                    summary="Receptionist",
                    issue=None,
                ),
                ImportableTwin(
                    twin_id=OTHER_TWIN_ID,
                    name="Night Auditor Twin",
                    version_number=3,
                    content_hash="b" * 64,
                    validation_status="PROJECT_GROUNDED_UT",
                    summary=None,
                    issue="TWIN_NAME_ALREADY_USED",
                ),
            ),
        )
        self.candidates = (
            TwinImportCandidate(
                project_id=SOURCE_PROJECT_ID,
                project_name="Hotel Operations Studio",
                snapshot_version_number=2,
                approved_at=APPROVED_AT,
                twin_names=("Night Auditor Twin", "Receptionist Twin"),
            ),
            TwinImportCandidate(
                project_id=OTHER_PROJECT_ID,
                project_name="Spa Bookings",
                snapshot_version_number=1,
                approved_at=EARLIER_APPROVED_AT,
                twin_names=("Therapist Twin",),
            ),
        )

    def _answer(self, name: str, **arguments: object) -> None:
        self.calls.append((name, arguments))
        if self.error is not None:
            raise self.error

    async def sources(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> tuple[TwinImportCandidate, ...]:
        self._answer("sources", owner_user_id=owner_user_id, project_id=project_id)
        return self.candidates

    async def source(
        self, *, owner_user_id: UUID, project_id: UUID, source_project_id: UUID
    ) -> TwinImportSource:
        self._answer(
            "source",
            owner_user_id=owner_user_id,
            project_id=project_id,
            source_project_id=source_project_id,
        )
        return self.listing

    async def import_from_project(
        self, *, owner_user_id: UUID, project_id: UUID, source_project_id: UUID, twin_id: UUID
    ) -> TwinImportResult:
        self._answer(
            "import_from_project",
            owner_user_id=owner_user_id,
            project_id=project_id,
            source_project_id=source_project_id,
            twin_id=twin_id,
        )
        return self.result

    async def import_document(
        self, *, owner_user_id: UUID, project_id: UUID, document: object
    ) -> TwinImportResult:
        self._answer(
            "import_document", owner_user_id=owner_user_id, project_id=project_id, document=document
        )
        return self.result


def client(service: FakeTwinImportService | None) -> TestClient:
    application = FastAPI()
    application.include_router(create_twin_import_router(), prefix="/api/v1")
    application.state.twin_import_service = service
    application.dependency_overrides[current_user_dependency] = user
    return TestClient(application)


def sized_body(size: int) -> bytes:
    document = {**folder_document(), "annotations": ""}
    document["annotations"] = "x" * (size - len(json.dumps({"document": document}).encode()))
    return json.dumps({"document": document}).encode()


def created(imported: ImportedTwin) -> dict[str, object]:
    twin = imported.twin_version
    persona = imported.persona_version
    snapshot = imported.snapshot_version
    return {
        "status": "TWIN_IMPORTED",
        "twin": {
            "twin_id": str(twin.twin_id),
            "version_id": str(twin.id),
            "version_number": 1,
            "name": "Receptionist Twin",
            "content_hash": twin.content_hash,
            "validation_status": "PROJECT_GROUNDED_UT",
        },
        "persona": {
            "persona_id": str(persona.persona_id),
            "version_id": str(persona.id),
            "version_number": 1,
            "name": persona.profile.name,
        },
        "snapshot": {
            "version_id": str(snapshot.id),
            "version_number": 2,
            "content_hash": snapshot.content_hash,
            "twin_count": 3,
        },
        "origin": imported.origin.to_snapshot(),
        "gate_approval_required": True,
    }


def test_the_sources_list_the_other_projects_that_can_give_a_twin():
    service = FakeTwinImportService()

    response = client(service).get(SOURCES_PATH)

    assert response.status_code == 200
    assert response.json() == {
        "sources": [
            {
                "project_id": str(SOURCE_PROJECT_ID),
                "project_name": "Hotel Operations Studio",
                "snapshot_version_number": 2,
                "approved_at": "2026-09-27T18:02:00Z",
                "twin_names": ["Night Auditor Twin", "Receptionist Twin"],
            },
            {
                "project_id": str(OTHER_PROJECT_ID),
                "project_name": "Spa Bookings",
                "snapshot_version_number": 1,
                "approved_at": "2026-09-25T09:15:00Z",
                "twin_names": ["Therapist Twin"],
            },
        ]
    }
    assert service.calls == [
        ("sources", {"owner_user_id": OWNER_ID, "project_id": TARGET_PROJECT_ID})
    ]


def test_the_sources_answer_an_empty_list_when_no_other_project_has_approved_twins():
    service = FakeTwinImportService()
    service.candidates = ()

    response = client(service).get(SOURCES_PATH)

    assert response.status_code == 200
    assert response.json() == {"sources": []}


def test_the_source_lists_its_twins_with_what_blocks_each_import():
    service = FakeTwinImportService()

    response = client(service).get(SOURCE_PATH)

    assert response.status_code == 200
    assert response.json() == {
        "project_id": str(SOURCE_PROJECT_ID),
        "project_name": "Hotel Operations Studio",
        "snapshot_version_number": 2,
        "approved_at": "2026-09-27T18:02:00Z",
        "twins": [
            {
                "twin_id": str(TWIN_ID),
                "name": "Receptionist Twin",
                "version_number": 1,
                "content_hash": "a" * 64,
                "validation_status": "PROJECT_GROUNDED_UT",
                "summary": "Receptionist",
                "issue": None,
            },
            {
                "twin_id": str(OTHER_TWIN_ID),
                "name": "Night Auditor Twin",
                "version_number": 3,
                "content_hash": "b" * 64,
                "validation_status": "PROJECT_GROUNDED_UT",
                "summary": None,
                "issue": "TWIN_NAME_ALREADY_USED",
            },
        ],
    }
    assert service.calls == [
        (
            "source",
            {
                "owner_user_id": OWNER_ID,
                "project_id": TARGET_PROJECT_ID,
                "source_project_id": SOURCE_PROJECT_ID,
            },
        )
    ]


def test_importing_a_twin_of_another_project_answers_created_with_the_new_versions():
    service = FakeTwinImportService()

    response = client(service).post(PATH, json=FROM_PROJECT)

    assert response.status_code == 201
    assert response.json() == created(service.result.imported)
    assert service.calls == [
        (
            "import_from_project",
            {
                "owner_user_id": OWNER_ID,
                "project_id": TARGET_PROJECT_ID,
                "source_project_id": SOURCE_PROJECT_ID,
                "twin_id": TWIN_ID,
            },
        )
    ]


def test_importing_a_twin_document_hands_the_whole_document_to_the_service():
    service = FakeTwinImportService()
    document = folder_document()
    document["annotations"] = "note " * 60_000

    response = client(service).post(PATH, json={"document": document})

    assert len(json.dumps(document)) > 300_000
    assert response.status_code == 201
    assert response.json() == created(service.result.imported)
    assert service.calls == [
        (
            "import_document",
            {"owner_user_id": OWNER_ID, "project_id": TARGET_PROJECT_ID, "document": document},
        )
    ]


@pytest.mark.parametrize(
    "body",
    [
        json.dumps({}),
        json.dumps({"source_project_id": str(SOURCE_PROJECT_ID)}),
        json.dumps({"twin_id": str(TWIN_ID)}),
        json.dumps({**FROM_PROJECT, "document": {}}),
        json.dumps({**FROM_PROJECT, "note": "please"}),
        json.dumps({"source_project_id": "project-a", "twin_id": str(TWIN_ID)}),
        json.dumps({"source_project_id": str(SOURCE_PROJECT_ID), "twin_id": 7}),
        json.dumps({"document": ["twin"]}),
        json.dumps({"document": None}),
        json.dumps({"document": {}, "source_project_id": str(SOURCE_PROJECT_ID)}),
        json.dumps([{"document": {}}]),
        json.dumps("document"),
        "{not json",
        "",
    ],
)
def test_a_request_that_is_not_exactly_one_of_the_two_forms_is_refused(body):
    service = FakeTwinImportService()

    response = client(service).post(
        PATH, content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "TWIN_IMPORT_REQUEST_INVALID"}}
    assert service.calls == []


def test_a_body_at_the_size_limit_is_read_and_one_byte_more_is_refused():
    service = FakeTwinImportService()
    api = client(service)
    largest = sized_body(MAX_TWIN_IMPORT_BODY_SIZE)
    oversized = sized_body(MAX_TWIN_IMPORT_BODY_SIZE + 1)

    accepted = api.post(PATH, content=largest, headers=JSON_HEADERS)
    refused = api.post(PATH, content=oversized, headers=JSON_HEADERS)

    assert (len(largest), len(oversized)) == (1024 * 1024, 1024 * 1024 + 1)
    assert accepted.status_code == 201
    assert refused.status_code == 413
    assert refused.json() == {"detail": {"code": "TWIN_IMPORT_TOO_LARGE"}}
    assert [name for name, _ in service.calls] == ["import_document"]


def test_a_body_without_a_declared_length_stops_being_read_past_the_limit():
    chunks = [b" " * CHUNK_SIZE] * 8
    delivered: list[bytes] = []

    async def receive() -> Message:
        delivered.append(chunks[len(delivered)])
        more = len(delivered) < len(chunks)
        return {"type": "http.request", "body": delivered[-1], "more_body": more}

    request = Request({"type": "http", "method": "POST", "headers": []}, receive)

    with pytest.raises(HTTPException) as refused:
        asyncio.run(twin_import_request(request))

    assert refused.value.status_code == 413
    assert refused.value.detail == {"code": "TWIN_IMPORT_TOO_LARGE"}
    assert len(delivered) * CHUNK_SIZE == MAX_TWIN_IMPORT_BODY_SIZE + CHUNK_SIZE


def test_a_document_nested_beyond_the_depth_limit_is_an_invalid_request():
    service = FakeTwinImportService()
    depth = 100
    body = '{"document": ' + '{"a": ' * depth + "0" + "}" * (depth + 1)

    response = client(service).post(PATH, content=body, headers=JSON_HEADERS)

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "TWIN_IMPORT_REQUEST_INVALID"}}
    assert service.calls == []


def test_a_document_nested_beyond_the_parser_limit_is_an_invalid_request():
    service = FakeTwinImportService()
    depth = 100_000
    body = '{"document": ' + '{"a": ' * depth + "0" + "}" * (depth + 1)

    response = client(service).post(PATH, content=body, headers=JSON_HEADERS)

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "TWIN_IMPORT_REQUEST_INVALID"}}
    assert service.calls == []


@pytest.mark.parametrize(
    ("code", "status"),
    [
        *((code, 404) for code in NOT_FOUND),
        *((code, 422) for code in INVALID),
        *((code, 409) for code in CONFLICTS),
        *((code, 503) for code in UNAVAILABLE),
    ],
)
def test_every_failure_keeps_its_code_and_uses_a_distinct_status(code, status):
    api = client(FakeTwinImportService(error=TwinImportError(code)))

    for response in (
        api.get(SOURCES_PATH),
        api.get(SOURCE_PATH),
        api.post(PATH, json=FROM_PROJECT),
        api.post(PATH, json={"document": folder_document()}),
    ):
        assert response.status_code == status
        assert response.json() == {"detail": {"code": code}}


def test_a_document_failure_names_its_location_when_it_is_known():
    located = client(
        FakeTwinImportService(error=TwinImportError("TWIN_DOCUMENT_INVALID", "twin.content_hash"))
    ).post(PATH, json={"document": {}})
    unlocated = client(
        FakeTwinImportService(error=TwinImportError("TWIN_DOCUMENT_INVALID", ""))
    ).post(PATH, json={"document": {}})

    assert located.status_code == 422
    assert located.json() == {
        "detail": {"code": "TWIN_DOCUMENT_INVALID", "location": "twin.content_hash"}
    }
    assert unlocated.json() == {"detail": {"code": "TWIN_DOCUMENT_INVALID"}}


def test_twin_imports_are_unavailable_without_the_service():
    api = client(None)

    for response in (
        api.get(SOURCES_PATH),
        api.get(SOURCE_PATH),
        api.post(PATH, json=FROM_PROJECT),
    ):
        assert response.status_code == 503
        assert response.json() == {"detail": {"code": "TWIN_IMPORT_SERVICE_UNAVAILABLE"}}


def test_project_identifiers_in_the_path_must_be_uuids():
    service = FakeTwinImportService()
    api = client(service)
    foreign = "/api/v1/projects/project-b/user-modeling/twin-imports"

    for response in (
        api.get(f"{foreign}/sources"),
        api.get(f"{foreign}/sources/{SOURCE_PROJECT_ID}"),
        api.get(f"{PATH}/sources/project-a"),
        api.post(foreign, json=FROM_PROJECT),
    ):
        assert response.status_code == 422
    assert service.calls == []


def test_the_twin_import_routes_are_documented_in_openapi():
    document = client(FakeTwinImportService()).app.openapi()
    paths = document["paths"]
    schemas = document["components"]["schemas"]
    sources = paths["/api/v1/projects/{project_id}/user-modeling/twin-imports/sources"]["get"]
    source = paths[
        "/api/v1/projects/{project_id}/user-modeling/twin-imports/sources/{source_project_id}"
    ]["get"]
    create = paths["/api/v1/projects/{project_id}/user-modeling/twin-imports"]["post"]

    assert sources["operationId"] == "listTwinImportSources"
    assert source["operationId"] == "getTwinImportSource"
    assert create["operationId"] == "importUserTwin"
    assert sources["tags"] == source["tags"] == create["tags"] == ["user-modeling"]
    assert sources["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/TwinImportSourcesPayload"
    }
    assert schemas["TwinImportCandidatePayload"]["required"] == [
        "project_id",
        "project_name",
        "snapshot_version_number",
        "approved_at",
        "twin_names",
    ]
    assert schemas["TwinImportSourcesPayload"]["additionalProperties"] is False
    assert schemas["TwinImportCandidatePayload"]["additionalProperties"] is False
    assert "201" in create["responses"]
    forms = create["requestBody"]["content"]["application/json"]["schema"]["oneOf"]
    assert [form["required"] for form in forms] == [["source_project_id", "twin_id"], ["document"]]
    assert all(form["additionalProperties"] is False for form in forms)
