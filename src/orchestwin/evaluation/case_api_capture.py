"""Capture owner-scoped OrchesTwin API snapshots as immutable formal-run evidence."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Final, Protocol
from urllib.parse import urlparse
from uuid import UUID

_MAX_RESPONSE_BYTES: Final = 10 * 1024 * 1024
_SAFE_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class _Response(Protocol):
    status: int

    def read(self, amount: int = -1) -> bytes: ...
    def __enter__(self): ...
    def __exit__(self, exc_type, exc, tb): ...


@dataclass(frozen=True, slots=True)
class CaseApiCaptureRequest:
    """One safe GET endpoint whose response is preserved verbatim as evidence."""

    slug: str
    path: str

    def __post_init__(self) -> None:
        if _SAFE_SLUG.fullmatch(self.slug) is None:
            raise ValueError("API capture slug must use lowercase kebab-case")
        if not self.path.startswith("/") or ".." in PurePosixPath(self.path).parts:
            raise ValueError("API capture path must be an absolute API path without traversal")
        parsed = urlparse(self.path)
        if parsed.scheme or parsed.netloc:
            raise ValueError("API capture path must not contain a host or scheme")


@dataclass(frozen=True, slots=True)
class CapturedApiArtifact:
    """Content-addressed response metadata; access tokens are intentionally absent."""

    slug: str
    request_path: str
    relative_path: str
    sha256_digest: str
    size_bytes: int
    captured_at: datetime

    def to_snapshot(self) -> dict[str, object]:
        return {
            "slug": self.slug,
            "request_path": self.request_path,
            "relative_path": self.relative_path,
            "sha256_digest": self.sha256_digest,
            "size_bytes": self.size_bytes,
            "captured_at": self.captured_at.isoformat(),
        }


def build_core_case_api_requests(
    *,
    project_id: UUID,
    workflow_run_id: UUID,
) -> tuple[CaseApiCaptureRequest, ...]:
    """Build the minimum stable read-only API evidence set for one Web formal run."""
    return (
        CaseApiCaptureRequest(
            slug="workflow-run",
            path=f"/runs/{workflow_run_id}",
        ),
        CaseApiCaptureRequest(
            slug="workflow-checkpoints",
            path=f"/runs/{workflow_run_id}/checkpoints",
        ),
        CaseApiCaptureRequest(
            slug="web-source-revisions",
            path=f"/projects/{project_id}/web-source-revisions",
        ),
        CaseApiCaptureRequest(
            slug="web-executions",
            path=f"/projects/{project_id}/web-executions",
        ),
    )


def _validate_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("API capture base URL must be an absolute HTTP(S) URL")
    if parsed.query or parsed.fragment:
        raise ValueError("API capture base URL must not contain query or fragment")
    return base_url.rstrip("/")


def _read_bounded(response: _Response) -> bytes:
    data = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(data) > _MAX_RESPONSE_BYTES:
        raise ValueError("API capture response exceeds the formal evidence size limit")
    if not data:
        raise ValueError("API capture response must not be empty")
    return data


def capture_case_api_snapshot(
    *,
    base_url: str,
    access_token: str,
    request: CaseApiCaptureRequest,
    evidence_root: Path,
    opener: Callable[[urllib.request.Request], _Response] = urllib.request.urlopen,
    captured_at: datetime | None = None,
) -> CapturedApiArtifact:
    """GET one API snapshot, validate JSON, and preserve the exact response bytes."""
    root = evidence_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not access_token or access_token != access_token.strip():
        raise ValueError("API capture access token must be supplied without surrounding whitespace")
    url = _validate_base_url(base_url) + request.path
    http_request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )
    try:
        with opener(http_request) as response:
            if response.status != 200:
                raise RuntimeError(f"API capture returned HTTP {response.status}")
            body = _read_bounded(response)
    except urllib.error.URLError as error:
        raise RuntimeError(f"API capture failed for {request.path}") from error
    try:
        json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("API capture response must be UTF-8 JSON") from error
    relative_path = f"api/{request.slug}.json"
    destination = root / "api" / f"{request.slug}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"API capture evidence already exists: {destination}")
    destination.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    timestamp = captured_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("API capture timestamp must be timezone-aware")
    return CapturedApiArtifact(
        slug=request.slug,
        request_path=request.path,
        relative_path=relative_path,
        sha256_digest=digest,
        size_bytes=len(body),
        captured_at=timestamp,
    )
