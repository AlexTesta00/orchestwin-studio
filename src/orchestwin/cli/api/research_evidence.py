from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final
from urllib.parse import urlencode

from orchestwin.cli.errors import USAGE_STATUS, ApiFailure, CliError
from orchestwin.cli.jobs import reply_body

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient

DOCUMENT: Final = "twins/evidence.json"
KIND: Final = "orchestwin.research-evidence"
SOURCE_KINDS: Final = (
    "PROJECT_BRIEF",
    "OWNER_INPUT",
    "EMPIRICAL_RESEARCH",
    "HUMAN_REVIEW",
    "MODEL_OUTPUT",
    "SYSTEM_ARTIFACT",
)
MAX_CHARACTERS: Final = 24_000
MAX_BYTES: Final = 32_768
_CODE: Final = re.compile(r"EVD-([0-9]{3,6})", re.IGNORECASE)


def path(project_id: str, source_id: str | None = None) -> str:
    base = f"/projects/{project_id}/evidence"
    return base if source_id is None else f"{base}/{source_id}"


def entries(document: object) -> list[Mapping[str, object]]:
    values = document.get("evidence") if isinstance(document, Mapping) else None
    return (
        [item for item in values if isinstance(item, Mapping)] if isinstance(values, list) else []
    )


def overview(client: StudioClient, project_id: str, *, every: bool = False) -> Mapping:
    return request(client, "GET", path(project_id), query={"all": str(every).lower()})


def selected(document: object, code: str) -> Mapping[str, object]:
    match = _CODE.fullmatch(code.strip())
    normal = None if match is None else f"EVD-{match.group(1)}"
    candidates = [item for item in entries(document) if item.get("code") == normal]
    if not candidates:
        raise CliError("EVIDENCE_NOT_FOUND", status=USAGE_STATUS)
    return max(candidates, key=lambda item: int(item.get("version", 0)))


def request(
    client: StudioClient,
    method: str,
    route: str,
    *,
    body: Mapping | None = None,
    query: Mapping[str, str] | None = None,
) -> Mapping[str, object]:
    if query:
        route = f"{route}?{urlencode(query)}"
    reply = client.request(method, route, body=body)
    document = reply_body(reply)
    if reply.status >= 400:
        detail = document.get("detail") if isinstance(document, Mapping) else None
        code = detail.get("code") if isinstance(detail, Mapping) else detail
        raise ApiFailure(code if isinstance(code, str) else "API_FAILURE", http_status=reply.status)
    if not isinstance(document, Mapping):
        raise ApiFailure("API_FAILURE", http_status=reply.status)
    return document
