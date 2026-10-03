from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlencode

from orchestwin.cli.errors import ApiFailure


def records(client, project_id):
    document = client.get(f"/projects/{project_id}/workflow-inputs", optional=True)
    if document is None:
        return None
    from orchestwin.workflow_inputs import WorkflowInputError, validate_workflow_records

    try:
        result = validate_workflow_records(document)
    except WorkflowInputError as error:
        raise ApiFailure(error.code, http_status=200) from error
    if result["project_id"] != project_id:
        raise ApiFailure("WORKFLOW_PROJECT_MISMATCH", http_status=200)
    return result


def state(client, project_id):
    document = client.get(f"/projects/{project_id}/provided-prototypes/state", optional=True)
    if document is None:
        return None
    if not isinstance(document, Mapping) or document.get("source") not in {
        "PROVIDED_PROTOTYPE",
        "EXPLORATION",
        "NONE",
    }:
        raise ApiFailure("API_FAILURE", http_status=200)
    if document["source"] == "PROVIDED_PROTOTYPE":
        from orchestwin.workflow_inputs import WorkflowInputError, workflow_records

        prototype = document.get("prototype")
        try:
            workflow_records(project_id, prototypes=[prototype])
        except (TypeError, WorkflowInputError) as error:
            raise ApiFailure("API_FAILURE", http_status=200) from error
    return document


def guard(client, project_id, code):
    source = state(client, project_id)
    if source is not None and source["source"] == "PROVIDED_PROTOTYPE":
        raise ApiFailure(code, http_status=409)
    return source


def document(client, project_id, prototype_id, *, entry_screen="SCR-001"):
    query = urlencode({"entry_screen": entry_screen})
    found = client.get(
        f"/projects/{project_id}/provided-prototypes/{prototype_id}/document?{query}"
    )
    if not isinstance(found, Mapping) or not isinstance(found.get("html"), str):
        raise ApiFailure("API_FAILURE", http_status=200)
    return found
