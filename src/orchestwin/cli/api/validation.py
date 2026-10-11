from __future__ import annotations

from urllib.parse import urlencode

from orchestwin.cli.api.replies import mapping_answer


def overview(client, project_id):
    reply = client.request("GET", f"/projects/{project_id}/validation")
    return mapping_answer(reply, kind="orchestwin.human-validation")


def walkthrough(client, project_id, scenario_key, *, alternative_id=None, document_hash=None):
    query = {"scenario_key": scenario_key}
    if alternative_id is not None:
        query["alternative_id"] = alternative_id
    if document_hash is not None:
        query["document_hash"] = document_hash
    path = f"/projects/{project_id}/validation/walkthrough?{urlencode(query)}"
    return mapping_answer(client.request("GET", path), kind="orchestwin.scenario-walkthrough")
