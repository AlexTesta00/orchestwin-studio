"""Admission checks for real source generation; no database or inference fixtures."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.api.source_generation import (
    ModelSourceApplication,
    SourceGenerationBody,
    _bounded_context,
    _selection,
)
from orchestwin.config import ApplicationSettings


@pytest.mark.parametrize("authenticated", [False, True])
@pytest.mark.parametrize("repair", [False, True])
def test_missing_authentication_or_real_runtime_never_falls_back(authenticated, repair):
    app = create_app(
        ApplicationSettings(_env_file=None),
        runtime=ApplicationRuntime(identity_service=SimpleNamespace()),
        auth_settings=AuthApiSettings(_env_file=None),
    )
    if authenticated:
        app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id=uuid4())
    request = (
        {"base_revision_content_hash": "a" * 64, "failure_signature_digest": "b" * 64}
        if repair
        else {
            "target": "WEB_STATIC",
            "frontend_language": "STATIC_ASSETS",
            "architecture_version_id": str(uuid4()),
            "architecture_content_hash": "a" * 64,
        }
    )
    route = f"repair-generations/web/{uuid4()}" if repair else "source-generations/web"

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture/api/v1"
        ) as client:
            response = await client.post(f"/projects/{uuid4()}/{route}", json=request)
            assert response.status_code == (503 if authenticated else 401), response.text

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "platform,options",
    [
        ("web", {"target": "JVM_JAVA"}),
        ("web", {"target": "WEB_STATIC", "backend_language": "JAVASCRIPT"}),
        ("jvm", {"target": "WEB_STATIC"}),
        ("jvm", {"target": "JVM_KOTLIN", "frontend_language": "STATIC_ASSETS"}),
    ],
)
def test_invalid_target_configuration_is_an_admission_error(platform, options):
    body = SourceGenerationBody(
        architecture_version_id=uuid4(), architecture_content_hash="a" * 64, **options
    )
    with pytest.raises(HTTPException) as error:
        _selection(platform, body)
    assert error.value.status_code == 422


def test_oversized_context_is_rejected_without_truncating():
    with pytest.raises(HTTPException) as error:
        _bounded_context({"requirements": "x" * 131072})
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "SOURCE_CONTEXT_LIMIT_EXCEEDED"


def test_complete_approved_context_can_exceed_the_old_byte_limit():
    context = {"requirements": "x" * 20000, "architecture": "y" * 20000}
    assert _bounded_context(context) is context


def test_real_source_cannot_publish_without_an_evidence_store():
    with pytest.raises(HTTPException) as error:
        ModelSourceApplication(ApplicationRuntime(real_model_runtime=SimpleNamespace()))
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "SOURCE_EVIDENCE_STORE_NOT_CONFIGURED"
