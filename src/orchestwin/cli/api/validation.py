from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlencode

from orchestwin.cli.errors import ApiFailure
from orchestwin.cli.jobs import reply_body


def _read(client, path, kind):
    reply = client.request("GET", path)
    document = reply_body(reply)
    if reply.status >= 400:
        detail = document.get("detail") if isinstance(document, Mapping) else None
        code = detail.get("code") if isinstance(detail, Mapping) else detail
        raise ApiFailure(code if isinstance(code, str) else "API_FAILURE", http_status=reply.status)
    if not isinstance(document, Mapping) or document.get("kind") != kind:
        raise ApiFailure("API_FAILURE", http_status=reply.status)
    return document


def overview(client, project_id):
    return _read(client, f"/projects/{project_id}/validation", "orchestwin.human-validation")


def walkthrough(client, project_id, scenario_key, *, alternative_id=None, document_hash=None):
    query = {"scenario_key": scenario_key}
    if alternative_id is not None:
        query["alternative_id"] = alternative_id
    if document_hash is not None:
        query["document_hash"] = document_hash
    return _read(
        client,
        f"/projects/{project_id}/validation/walkthrough?{urlencode(query)}",
        "orchestwin.scenario-walkthrough",
    )
