from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from orchestwin.cli.errors import ApiFailure
from orchestwin.cli.jobs import reply_body

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient


def explain(client: StudioClient, project_id: str, code: str) -> Mapping[str, object]:
    path = f"/projects/{project_id}/artifacts/why?{urlencode({'code': code})}"
    reply = client.request("GET", path)
    document = reply_body(reply)
    if reply.status >= 400:
        detail = document.get("detail") if isinstance(document, Mapping) else None
        error = detail.get("code") if isinstance(detail, Mapping) else detail
        values = {"candidates": detail.get("candidates", [])} if isinstance(detail, Mapping) else {}
        raise ApiFailure(
            error if isinstance(error, str) else "API_FAILURE",
            http_status=reply.status,
            values=values,
        )
    if not isinstance(document, Mapping) or document.get("kind") != "orchestwin.why-answer":
        raise ApiFailure("API_FAILURE", http_status=reply.status)
    return document
