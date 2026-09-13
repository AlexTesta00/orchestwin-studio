"""Owner-authenticated proposal audit resources and fail-closed responses."""

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings
from orchestwin.models.proposal_evidence import ProposalEvidenceError
from src.test.python.api.test_training_api import OWNER_ID, _user

PROJECT, GENERATION = uuid4(), uuid4()
PATH = f"/api/v1/projects/{PROJECT}/model-generations"


class Store:
    async def list_owned(self, *, owner_user_id, project_id, limit, before):
        assert limit <= 100
        if owner_user_id == OWNER_ID and project_id == PROJECT:
            return [{"generation_id": str(GENERATION)}]

    async def get_owned(self, *, owner_user_id, project_id, generation_id):
        if owner_user_id == OWNER_ID and project_id == PROJECT and generation_id == GENERATION:
            return {
                "publication_state": "MODEL_REJECTED",
                "observations": [{"kind": "HTTP_RESPONSE", "raw_body_base64": "e30="}],
                "artifact_links": [],
            }


def client(store, user=True):
    app = create_app(
        ApplicationSettings(api_prefix="/api/v1"),
        runtime=ApplicationRuntime(proposal_evidence_store=store, identity_service=object()),
    )
    if user:
        app.dependency_overrides[current_user_dependency] = _user
    return TestClient(app)


def test_owner_can_read_rejected_raw_evidence_and_bounded_history():
    http = client(Store())
    assert http.get(PATH).json()["generations"][0]["generation_id"] == str(GENERATION)
    detail = http.get(f"{PATH}/{GENERATION}")
    assert detail.status_code == 200
    assert detail.json()["observations"][0]["raw_body_base64"] == "e30="
    assert detail.json()["publication_state"] == "MODEL_REJECTED"
    assert http.get(PATH + "?limit=101").status_code == 422
    assert http.get(PATH + "?before=invalid").status_code == 422


def test_anonymous_foreign_owner_and_unknown_id_cannot_read_evidence():
    assert client(Store(), user=False).get(PATH).status_code == 401
    http = client(Store())
    assert http.get(f"{PATH}/{uuid4()}").status_code == 404
    http.app.dependency_overrides[current_user_dependency] = lambda: replace(_user(), id=uuid4())
    assert http.get(PATH).status_code == 404
    assert http.get(f"{PATH}/{GENERATION}").status_code == 404


def test_missing_store_is_explicitly_unavailable():
    assert client(None).get(PATH).status_code == 503


def test_corrupted_evidence_fails_closed_without_returning_partial_data():
    class Broken(Store):
        async def get_owned(self, **kwargs):
            raise ProposalEvidenceError("PROPOSAL_EVIDENCE_HASH_MISMATCH")

    result = client(Broken()).get(f"{PATH}/{GENERATION}")
    assert result.status_code == 503
    assert result.json() == {
        "detail": {"code": "PROPOSAL_EVIDENCE_HASH_MISMATCH", "stage": "MODEL_PROPOSAL_EVIDENCE"}
    }


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_evidence_routes_are_read_only(method):
    assert getattr(client(Store()), method)(f"{PATH}/{GENERATION}").status_code == 405
