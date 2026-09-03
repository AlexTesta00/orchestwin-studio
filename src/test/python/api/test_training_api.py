"""API contract tests for owner-scoped training and adapter resources."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import JsonValue

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount

OWNER_ID = UUID("00000000-0000-4000-8000-000000128001")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000128002")
DATASET_ID = UUID("00000000-0000-4000-8000-000000128003")
RUN_ID = UUID("00000000-0000-4000-8000-000000128004")
ADAPTER_ID = UUID("00000000-0000-4000-8000-000000128005")
NOW = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)


def _user() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("training-owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


class _TrainingApiService:
    def __init__(self) -> None:
        self._dataset: dict[str, JsonValue] = {
            "manifest": {
                "dataset_id": str(DATASET_ID),
                "version_number": 1,
                "content_hash": "a" * 64,
            },
            "quality_report": {"publishable": True},
        }
        self._run: dict[str, JsonValue] = {
            "run_id": str(RUN_ID),
            "status": "SUCCEEDED",
            "process_log_relative_path": "process-log.json",
        }
        self._adapter: dict[str, JsonValue] = {
            "adapter_id": str(ADAPTER_ID),
            "adapter_sha256": "b" * 64,
            "license_spdx": "Apache-2.0",
        }

    async def datasets(
        self,
        *,
        owner_user_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        return (self._dataset,) if owner_user_id == OWNER_ID else ()

    async def dataset(
        self,
        *,
        owner_user_id: UUID,
        dataset_id: UUID,
        version_number: int,
    ) -> dict[str, JsonValue] | None:
        if owner_user_id == OWNER_ID and dataset_id == DATASET_ID and version_number == 1:
            return self._dataset
        return None

    async def training_runs(
        self,
        *,
        owner_user_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        return (self._run,) if owner_user_id == OWNER_ID else ()

    async def training_run(
        self,
        *,
        owner_user_id: UUID,
        training_run_id: UUID,
    ) -> dict[str, JsonValue] | None:
        return self._run if owner_user_id == OWNER_ID and training_run_id == RUN_ID else None

    async def adapters(
        self,
        *,
        owner_user_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        return (self._adapter,) if owner_user_id == OWNER_ID else ()

    async def adapter(
        self,
        *,
        owner_user_id: UUID,
        adapter_id: UUID,
    ) -> dict[str, JsonValue] | None:
        return self._adapter if owner_user_id == OWNER_ID and adapter_id == ADAPTER_ID else None


def _client(service: _TrainingApiService | None) -> TestClient:
    application = create_app(
        ApplicationSettings(
            environment=RuntimeEnvironment.TEST,
            api_prefix="/api/v1",
        ),
        runtime=ApplicationRuntime(training_api_service=service),
        auth_settings=AuthApiSettings(),
    )
    application.dependency_overrides[current_user_dependency] = _user
    return TestClient(application)


def test_training_resources_expose_owner_scoped_lists_and_exact_details() -> None:
    client = _client(_TrainingApiService())

    datasets = client.get("/api/v1/datasets")
    dataset = client.get(f"/api/v1/datasets/{DATASET_ID}/versions/1")
    runs = client.get("/api/v1/training-runs")
    run = client.get(f"/api/v1/training-runs/{RUN_ID}")
    adapters = client.get("/api/v1/model-adapters")
    adapter = client.get(f"/api/v1/model-adapters/{ADAPTER_ID}")

    assert datasets.status_code == 200
    assert datasets.json()["items"][0]["manifest"]["dataset_id"] == str(DATASET_ID)
    assert dataset.status_code == 200
    assert dataset.json()["snapshot"]["quality_report"]["publishable"] is True
    assert runs.status_code == 200
    assert runs.json()["items"][0]["run_id"] == str(RUN_ID)
    assert run.status_code == 200
    assert run.json()["snapshot"]["process_log_relative_path"] == "process-log.json"
    assert adapters.status_code == 200
    assert adapters.json()["items"][0]["adapter_sha256"] == "b" * 64
    assert adapter.status_code == 200
    assert adapter.json()["snapshot"]["license_spdx"] == "Apache-2.0"


def test_training_resources_do_not_disclose_unknown_or_cross_owner_identifiers() -> None:
    service = _TrainingApiService()
    client = _client(service)

    assert client.get(f"/api/v1/datasets/{OTHER_OWNER_ID}/versions/1").status_code == 404
    assert client.get(f"/api/v1/training-runs/{OTHER_OWNER_ID}").status_code == 404
    assert client.get(f"/api/v1/model-adapters/{OTHER_OWNER_ID}").status_code == 404
    assert client.get(f"/api/v1/datasets/{DATASET_ID}/versions/0").status_code == 422


def test_training_routes_fail_explicitly_when_the_service_is_not_configured() -> None:
    response = _client(None).get("/api/v1/training-runs")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "TRAINING_API_SERVICE_UNAVAILABLE"
