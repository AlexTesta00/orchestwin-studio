from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from uuid import uuid5

from orchestwin.artifacts.provided_prototypes import provided_prototype_from_snapshot
from orchestwin.workflow_inputs import (
    WorkflowInputError,
    decision_content_hash,
    workflow_records,
)

DECISIONS_DOCUMENT = "workflow/decisions.json"
PROTOTYPES_DOCUMENT = "design/provided-prototypes.json"


def has_workflow_inputs(records):
    return bool(records and (records.get("decisions") or records.get("prototypes")))


def records_from_files(*, project_id, files):
    decisions = (
        json.loads(files[DECISIONS_DOCUMENT])["decisions"] if DECISIONS_DOCUMENT in files else []
    )
    prototypes = (
        json.loads(files[PROTOTYPES_DOCUMENT])["prototypes"] if PROTOTYPES_DOCUMENT in files else []
    )
    for item in prototypes:
        provided_prototype_from_snapshot(item)
    return workflow_records(project_id, decisions, prototypes)


def read_workflow_inputs(package):
    from orchestwin.knowledge.archive import KnowledgeArchiveError

    manifest, files = package.manifest, package.files
    declared = manifest.get("workflow_inputs")
    if declared is None:
        if DECISIONS_DOCUMENT in files or PROTOTYPES_DOCUMENT in files:
            raise KnowledgeArchiveError("FOLDER_TAMPERED", DECISIONS_DOCUMENT)
        return workflow_records(manifest["project"]["id"])
    try:
        if not isinstance(declared, Mapping) or set(declared) - {
            "schema_version",
            "decisions_document",
            "prototypes_document",
            "limits",
            "approved_prototype",
        }:
            raise WorkflowInputError("WORKFLOW_RECORDS_INVALID")
        if (
            type(declared.get("schema_version")) is not int
            or declared.get("schema_version") != 1
            or declared.get("decisions_document") != DECISIONS_DOCUMENT
            or declared.get("prototypes_document") != PROTOTYPES_DOCUMENT
        ):
            raise WorkflowInputError("WORKFLOW_RECORDS_INVALID")
        if DECISIONS_DOCUMENT not in files or PROTOTYPES_DOCUMENT not in files:
            raise WorkflowInputError("WORKFLOW_RECORDS_INVALID")
        records = records_from_files(project_id=manifest["project"]["id"], files=files)
        if records["limits"] != declared.get("limits") or not has_workflow_inputs(records):
            raise WorkflowInputError("WORKFLOW_RECORDS_INVALID")
        approved = declared.get("approved_prototype")
        portable = json.loads(files[PROTOTYPES_DOCUMENT])
        if approved != portable.get("approved_prototype"):
            raise WorkflowInputError("WORKFLOW_REFERENCE_INVALID")
        if approved is not None:
            if (
                set(approved) != {"artifact_id", "version_number", "content_hash", "gate_status"}
                or approved["gate_status"] != "APPROVED"
            ):
                raise WorkflowInputError("WORKFLOW_REFERENCE_INVALID")
            prototype = next(
                (
                    item
                    for item in records["prototypes"]
                    if (
                        item["id"] == approved["artifact_id"]
                        and item["version_number"] == approved["version_number"]
                        and item["content_hash"] == approved["content_hash"]
                    )
                ),
                None,
            )
            definition = manifest.get("stages", {}).get("requirements", {})
            if prototype is None or prototype["definition_reference"] != {
                "artifact_id": definition.get("version_id"),
                "version_number": definition.get("version_number"),
                "content_hash": definition.get("content_hash"),
            }:
                raise WorkflowInputError("WORKFLOW_REFERENCE_INVALID")
        return records
    except (WorkflowInputError, KeyError, TypeError, ValueError) as error:
        raise KnowledgeArchiveError(
            "FOLDER_DOCUMENT_INVALID", f"workflow inputs: {error}"
        ) from error


def export_workflow_files(sources):
    from orchestwin.knowledge.folder import json_text

    records = sources.workflow_inputs
    if not has_workflow_inputs(records):
        return {}
    prototypes = {"prototypes": records["prototypes"]}
    state = sources.provided_design
    if state.get("source") == "PROVIDED_PROTOTYPE" and state.get("approved") is True:
        item = state["prototype"]
        prototypes["approved_prototype"] = {
            "artifact_id": item["id"],
            "version_number": item["version_number"],
            "content_hash": item["content_hash"],
            "gate_status": "APPROVED",
        }
    return {
        DECISIONS_DOCUMENT: json_text({"decisions": records["decisions"]}),
        PROTOTYPES_DOCUMENT: json_text(prototypes),
    }


def workflow_manifest(files):
    if DECISIONS_DOCUMENT not in files:
        return None
    prototypes = json.loads(files[PROTOTYPES_DOCUMENT])
    from orchestwin.workflow_inputs import PROVIDED_PROTOTYPE_LIMITS

    entry = {
        "schema_version": 1,
        "decisions_document": DECISIONS_DOCUMENT,
        "prototypes_document": PROTOTYPES_DOCUMENT,
        "limits": list(PROVIDED_PROTOTYPE_LIMITS if prototypes["prototypes"] else ()),
    }
    if "approved_prototype" in prototypes:
        entry["approved_prototype"] = prototypes["approved_prototype"]
    return entry


def import_workflow_inputs(folder, *, project_id, identities, hashes):
    records = read_workflow_inputs(folder)
    if not has_workflow_inputs(records):
        return None
    for item in (*records["decisions"], *records["prototypes"]):
        identities.setdefault(item["id"], str(uuid5(project_id, item["id"])))
    prototype_ids = {item["id"] for item in records["prototypes"]}

    def rewrite(value, key=None):
        if isinstance(value, Mapping):
            result = {
                name: rewrite(item, name) for name, item in value.items() if name != "content_hash"
            }
            if "artifact_id" in value and "version_number" in value and "content_hash" in value:
                result["content_hash"] = hashes.get(value["content_hash"], value["content_hash"])
                if value["artifact_id"] in identities and value["artifact_id"] not in prototype_ids:
                    result["version_number"] = 1
            return result
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if isinstance(value, str):
            return identities.get(value, value)
        return value

    decisions, prototypes = [], []
    for item in (*records["prototypes"], *records["decisions"]):
        is_prototype = "mockup" in item
        result = rewrite(item)
        result["project_id"] = str(project_id)
        origin_key = "original_reference" if is_prototype else "origin_reference"
        result[origin_key] = deepcopy(
            item.get(origin_key)
            or {
                "artifact_id" if is_prototype else "id": item["id"],
                "project_id": item["project_id"],
                "version_number" if is_prototype else "sequence": item["version_number"]
                if is_prototype
                else item["sequence"],
                "content_hash": item["content_hash"],
            }
        )
        result["content_hash"] = decision_content_hash(result)
        hashes[item["content_hash"]] = result["content_hash"]
        if is_prototype:
            provided_prototype_from_snapshot(result)
            prototypes.append(result)
        else:
            decisions.append(result)
    return workflow_records(project_id, decisions, prototypes)
