from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from orchestwin.cli.api.replies import mapping_answer, refusal
from orchestwin.cli.jobs import reply_body

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient


def explain(client: StudioClient, project_id: str, code: str) -> Mapping[str, object]:
    path = f"/projects/{project_id}/artifacts/why?{urlencode({'code': code})}"
    reply = client.request("GET", path)
    if reply.status >= 400:
        document = reply_body(reply)
        detail = document.get("detail") if isinstance(document, Mapping) else None
        values = {"candidates": detail.get("candidates", [])} if isinstance(detail, Mapping) else {}
        raise refusal(reply.status, document, values)
    return mapping_answer(reply, kind="orchestwin.why-answer")
