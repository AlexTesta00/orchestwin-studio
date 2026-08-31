"""API contracts for synthetic evaluation, Gate 8, and final exports."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import JsonValue

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.finalization import (
    CreateFinalExportCommand,
    DecideFinalApprovalCommand,
    FinalExportDownload,
    FinalizationApiCommandResult,
    FinalizationApiStatus,
    SubmitFinalReviewCommand,
)
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount

OWNER_ID = UUID("00000000-0000-4000-8000-000000027001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000027002")
EVALUATION_ID = UUID("00000000-0000-4000-8000-000000027003")
REVIEW_ID = UUID("00000000-0000-4000-8000-000000027004")
GATE_ID = UUID("00000000-0000-4000-8000-000000027005")
EXPORT_ID = UUID("00000000-0000-4000-8000-000000027006")
EVENT_ID = UUID("00000000-0000-4000-8000-000000027007")
NOW = datetime(2026, 8, 31, 3, 0, tzinfo=UTC)


def _user() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("final-owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


class _FinalizationService:
    def __init__(self) -> None:
        self.visible = True
        self.submission: SubmitFinalReviewCommand | None = None
        self.decision: DecideFinalApprovalCommand | None = None
        self.export_command: CreateFinalExportCommand | None = None

    async def evaluation_run(
        self,
        *,
        owner_user_id: UUID,
        evaluation_run_id: UUID,
    ) -> dict[str, JsonValue] | None:
        if not self.visible or owner_user_id != OWNER_ID or evaluation_run_id != EVALUATION_ID:
            return None
        return {"id": str(EVALUATION_ID), "simulated_feedback": True}

    async def evaluation_findings(
        self,
        *,
        owner_user_id: UUID,
        evaluation_run_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...] | None:
        if not self.visible or owner_user_id != OWNER_ID or evaluation_run_id != EVALUATION_ID:
            return None
        return ({"finding_id": "UTF-001", "origin": "MODEL_GENERATED"},)

    async def evaluation_aggregation(
        self,
        *,
        owner_user_id: UUID,
        evaluation_run_id: UUID,
    ) -> dict[str, JsonValue] | None:
        if not self.visible or owner_user_id != OWNER_ID or evaluation_run_id != EVALUATION_ID:
            return None
        return {"evaluation_run_id": str(EVALUATION_ID), "direct_conflicts": []}

    async def final_reviews(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        assert owner_user_id == OWNER_ID
        return (
            ({"id": str(REVIEW_ID), "ready_for_gate8": True},) if project_id == PROJECT_ID else ()
        )

    async def submit_final_review(
        self,
        *,
        owner_user_id: UUID,
        command: SubmitFinalReviewCommand,
    ) -> FinalizationApiCommandResult:
        assert owner_user_id == OWNER_ID
        self.submission = command
        return FinalizationApiCommandResult(
            FinalizationApiStatus.APPLIED,
            {"gate_id": str(command.gate_id), "status": "PENDING_APPROVAL"},
            "Final review submitted for owner approval.",
        )

    async def decide_final_approval(
        self,
        *,
        owner_user_id: UUID,
        command: DecideFinalApprovalCommand,
    ) -> FinalizationApiCommandResult:
        assert owner_user_id == OWNER_ID
        self.decision = command
        return FinalizationApiCommandResult(
            FinalizationApiStatus.APPLIED,
            {"gate_id": str(command.gate_id), "status": "APPROVED"},
            "Final approval decision applied.",
        )

    async def create_export(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        command: CreateFinalExportCommand,
    ) -> FinalizationApiCommandResult:
        assert owner_user_id == OWNER_ID
        assert project_id == PROJECT_ID
        self.export_command = command
        return FinalizationApiCommandResult(
            FinalizationApiStatus.CREATED,
            {"id": str(command.export_id), "archive_hash": "c" * 64},
            "Final export created.",
        )

    async def export(
        self,
        *,
        owner_user_id: UUID,
        export_id: UUID,
    ) -> dict[str, JsonValue] | None:
        if not self.visible or owner_user_id != OWNER_ID or export_id != EXPORT_ID:
            return None
        return {"id": str(EXPORT_ID), "archive_hash": "c" * 64}

    async def download_export(
        self,
        *,
        owner_user_id: UUID,
        export_id: UUID,
    ) -> FinalExportDownload | None:
        if not self.visible or owner_user_id != OWNER_ID or export_id != EXPORT_ID:
            return None
        return FinalExportDownload(
            filename="orchestwin-final-export.zip",
            content=b"PK deterministic fixture",
            content_hash=hashlib.sha256(b"PK deterministic fixture").hexdigest(),
        )


def _client(service: _FinalizationService | None) -> TestClient:
    application = create_app(
        ApplicationSettings(environment=RuntimeEnvironment.TEST, api_prefix="/api/v1"),
        runtime=ApplicationRuntime(finalization_api_service=service),
        auth_settings=AuthApiSettings(),
    )
    application.dependency_overrides[current_user_dependency] = _user
    return TestClient(application)


def _submit_body() -> dict[str, object]:
    return {
        "expected_version": 1,
        "expected_content_hash": "a" * 64,
        "gate_id": str(GATE_ID),
        "event_id": str(EVENT_ID),
        "occurred_at": NOW.isoformat(),
    }


def test_finalization_resources_preserve_owner_scope_and_methodological_labels() -> None:
    service = _FinalizationService()
    client = _client(service)

    evaluation = client.get(f"/api/v1/evaluation-runs/{EVALUATION_ID}")
    findings = client.get(f"/api/v1/evaluation-runs/{EVALUATION_ID}/findings")
    aggregation = client.get(f"/api/v1/evaluation-runs/{EVALUATION_ID}/aggregation")
    reviews = client.get(f"/api/v1/projects/{PROJECT_ID}/final-reviews")

    assert evaluation.status_code == 200
    assert evaluation.json()["snapshot"]["simulated_feedback"] is True
    assert findings.json()["items"][0]["origin"] == "MODEL_GENERATED"
    assert aggregation.json()["snapshot"]["direct_conflicts"] == []
    assert reviews.json()["items"][0]["ready_for_gate8"] is True


def test_gate8_and_export_commands_preserve_exact_versions() -> None:
    service = _FinalizationService()
    client = _client(service)

    submitted = client.post(f"/api/v1/final-reviews/{REVIEW_ID}/submit", json=_submit_body())
    decision = client.post(
        f"/api/v1/final-approval-requests/{GATE_ID}/decisions",
        json={
            "action": "APPROVE",
            "expected_review_id": str(REVIEW_ID),
            "expected_review_version": 1,
            "expected_review_hash": "a" * 64,
            "event_id": str(EVENT_ID),
            "occurred_at": NOW.isoformat(),
            "reason": None,
        },
    )
    exported = client.post(
        f"/api/v1/projects/{PROJECT_ID}/exports",
        json={
            "export_id": str(EXPORT_ID),
            "final_review_id": str(REVIEW_ID),
            "expected_review_version": 1,
            "expected_review_hash": "a" * 64,
            "final_approval_gate_id": str(GATE_ID),
            "final_approval_event_id": str(EVENT_ID),
            "occurred_at": NOW.isoformat(),
        },
    )

    assert submitted.status_code == 200
    assert decision.status_code == 200
    assert exported.status_code == 201
    assert service.submission is not None and service.submission.review_id == REVIEW_ID
    assert service.decision is not None and service.decision.expected_review_version == 1
    assert service.export_command is not None and service.export_command.export_id == EXPORT_ID


def test_export_download_uses_safe_headers_and_missing_resources_are_hidden() -> None:
    service = _FinalizationService()
    client = _client(service)

    response = client.get(f"/api/v1/exports/{EXPORT_ID}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == (
        'attachment; filename="orchestwin-final-export.zip"'
    )
    assert response.headers["x-content-type-options"] == "nosniff"

    service.visible = False
    missing = client.get(f"/api/v1/exports/{EXPORT_ID}")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "FINAL_EXPORT_NOT_FOUND"

    unavailable = _client(None).get(f"/api/v1/exports/{EXPORT_ID}")
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "FINALIZATION_API_SERVICE_UNAVAILABLE"
