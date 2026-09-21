from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.evaluation.case_api_capture import (
    build_core_case_api_requests,
    capture_case_api_snapshot,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000047001")
RUN_ID = UUID("00000000-0000-4000-8000-000000047002")
NOW = datetime(2026, 9, 7, 19, 0, tzinfo=UTC)


class FakeResponse:
    status = 200

    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self, amount: int = -1) -> bytes:
        return self.body if amount < 0 else self.body[:amount]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_core_capture_requests_are_read_only_owner_scoped_paths() -> None:
    requests = build_core_case_api_requests(project_id=PROJECT_ID, workflow_run_id=RUN_ID)

    assert [item.slug for item in requests] == [
        "workflow-run",
        "workflow-checkpoints",
        "web-source-revisions",
        "web-executions",
    ]
    assert all(item.path.startswith("/") for item in requests)
    assert str(PROJECT_ID) in requests[2].path
    assert str(RUN_ID) in requests[0].path


def test_api_capture_preserves_exact_json_without_persisting_token(tmp_path) -> None:
    seen_headers: dict[str, str] = {}
    body = json.dumps({"snapshot": {"status": "RUNNING"}}, separators=(",", ":")).encode()

    def opener(request):
        seen_headers.update(dict(request.header_items()))
        return FakeResponse(body)

    artifact = capture_case_api_snapshot(
        base_url="http://127.0.0.1:8000",
        access_token="secret-token",
        request=build_core_case_api_requests(project_id=PROJECT_ID, workflow_run_id=RUN_ID)[0],
        evidence_root=tmp_path,
        opener=opener,
        captured_at=NOW,
    )

    assert (tmp_path / artifact.relative_path).read_bytes() == body
    assert artifact.size_bytes == len(body)
    assert "secret-token" in seen_headers["Authorization"]
    assert "secret-token" not in json.dumps(artifact.to_snapshot())


def test_api_capture_refuses_to_overwrite_observed_evidence(tmp_path) -> None:
    request = build_core_case_api_requests(project_id=PROJECT_ID, workflow_run_id=RUN_ID)[0]

    def opener(_request):
        return FakeResponse(b"{}")

    capture_case_api_snapshot(
        base_url="http://127.0.0.1:8000",
        access_token="token",
        request=request,
        evidence_root=tmp_path,
        opener=opener,
        captured_at=NOW,
    )
    with pytest.raises(FileExistsError):
        capture_case_api_snapshot(
            base_url="http://127.0.0.1:8000",
            access_token="token",
            request=request,
            evidence_root=tmp_path,
            opener=opener,
            captured_at=NOW,
        )
