from __future__ import annotations

import json
from copy import deepcopy
from urllib.parse import quote, unquote
from uuid import uuid5

from orchestwin.artifacts.human_validation import hypothesis_from_snapshot, outcome_from_snapshot
from orchestwin.projects.requirements_primitives import snapshot_content_hash

VALIDATION_DOCUMENT = "validation/human-validation.json"
VALIDATION_KIND = "orchestwin.validation-records"


def _snapshot(item):
    return item.to_snapshot() if hasattr(item, "to_snapshot") else deepcopy(dict(item))


def preserve_import_history(records, origin=None):
    if origin is None or not origin.omitted_sections:
        return records
    provenance = {
        "project_id": str(origin.source_project_id),
        "package_version": origin.package_version,
        "package_content_hash": origin.package_content_hash,
    }
    omitted = deepcopy(list(records.get("omitted_sections", [])))
    for entry in origin.omitted_sections:
        entry = deepcopy(dict(entry))
        entry.setdefault("origin", provenance)
        entry["historical"] = True
        if entry not in omitted:
            omitted.append(entry)
    return {
        **records,
        "omitted_sections": omitted,
        "limits": sorted(
            {
                *records.get("limits", []),
                *(
                    item
                    for item in origin.import_limits
                    if item != "LEARNED_PROJECTION_NOT_RESTORED"
                ),
            }
        ),
    }


def has_validation_records(records):
    return bool(
        records.get("hypotheses") or records.get("outcomes") or records.get("omitted_sections")
    )


def portable_records(*, document, records, evidence):
    nodes = {item["key"]: item for item in document["nodes"]}
    kept = []
    omitted = []
    limits = list(records.get("limits", []))
    for item in records.get("hypotheses", []):
        item = _snapshot(item)
        missing = []
        for prefix in ("origin", "twin", "scenario", "design"):
            node = nodes.get(item.get(prefix + "_key"))
            if node is None or node["reference"] != item.get(prefix + "_reference"):
                missing.append(prefix + "_reference")
        for anchor in item.get("mockup_references", []):
            node = nodes.get(anchor["key"])
            if (
                node is None
                or node["reference"] != anchor["reference"]
                or node.get("declared_context", {}).get("mockup", {}) != anchor["mockup"]
            ):
                missing.append(anchor["key"])
        if missing:
            omitted.append(
                {
                    "kind": "VALIDATION_HYPOTHESIS",
                    "id": item["id"],
                    "version_number": item["version_number"],
                    "reason": "VALIDATION_REFERENCE_UNAVAILABLE",
                    "references": missing,
                }
            )
        else:
            kept.append(item)
    hyp_keys = {(item["id"], item["version_number"], item["content_hash"]) for item in kept}
    hyp_versions = {(item["id"], item["version_number"]) for item in kept}
    for item in kept:
        base = item.get("based_on_version_number")
        if base is not None and (item["id"], base) not in hyp_versions:
            omitted.append(
                {
                    "kind": "VALIDATION_HYPOTHESIS_HISTORY",
                    "id": item["id"],
                    "version_number": base,
                    "reason": "HYPOTHESIS_HISTORY_PARTIAL",
                }
            )
            limits.append("HYPOTHESIS_HISTORY_PARTIAL")
    sources = {
        (item["id"], item["version"], item["content_hash"]) for item in evidence.get("evidence", [])
    }
    outcomes = []
    for item in records.get("outcomes", []):
        item = _snapshot(item)
        hypothesis = (
            item["hypothesis_id"],
            item["hypothesis_version_number"],
            item["hypothesis_content_hash"],
        )
        source = (item["evidence_id"], item["evidence_version"], item["evidence_content_hash"])
        reason = (
            "VALIDATION_HYPOTHESIS_UNAVAILABLE"
            if hypothesis not in hyp_keys
            else "MISSING_SOURCE_VERSION"
            if source not in sources
            else None
        )
        if reason:
            omitted.append({"kind": "VALIDATION_OUTCOME", "id": item["id"], "reason": reason})
        else:
            outcomes.append(item)
    return {
        "kind": VALIDATION_KIND,
        "schema_version": 1,
        "project_id": document["project_id"],
        "hypotheses": sorted(kept, key=lambda item: (item["code"], item["version_number"])),
        "outcomes": sorted(outcomes, key=lambda item: (item["code"], item["id"])),
        "omitted_sections": [*records.get("omitted_sections", []), *omitted],
        "limits": sorted(set(limits)),
    }


def verify_validation(*, manifest, files, evidence):
    declared = manifest.get("validation")
    present = VALIDATION_DOCUMENT in files
    if declared is None and not present:
        return
    from orchestwin.cli.mcp.validation import verify_records
    from orchestwin.knowledge.archive import KnowledgeArchiveError

    try:
        document = json.loads(files[VALIDATION_DOCUMENT])
        if (
            not isinstance(declared, dict)
            or declared
            != {
                "document": VALIDATION_DOCUMENT,
                "schema_version": 1,
                "hypotheses": len(document["hypotheses"]),
                "outcomes": len(document["outcomes"]),
            }
            or manifest.get("schemas", {}).get("validation") != "schema/validation.schema.json"
            or document["project_id"] != manifest["project"]["id"]
            or not verify_records(document, evidence)
        ):
            raise ValueError("validation records do not match their declared scope")
        for item in document["hypotheses"]:
            hypothesis_from_snapshot(item)
        for item in document["outcomes"]:
            outcome_from_snapshot(item)
    except (KeyError, TypeError, ValueError) as error:
        raise KnowledgeArchiveError("FOLDER_TAMPERED", VALIDATION_DOCUMENT) from error


def import_validation(folder, *, identities, hashes, project_id, owner_user_id):
    if VALIDATION_DOCUMENT not in folder.files:
        return {"hypotheses": [], "outcomes": [], "omitted_sections": [], "limits": []}
    document = json.loads(folder.files[VALIDATION_DOCUMENT])
    for item in [*document["hypotheses"], *document["outcomes"]]:
        identities.setdefault(item["id"], str(uuid5(project_id, item["id"])))
        identities[item["owner_user_id"]] = str(owner_user_id)

    def text(value):
        decoded = unquote(value)
        for old, new in identities.items():
            decoded = decoded.replace(old, new)
        for old, new in hashes.items():
            decoded = decoded.replace(old, new)
        return decoded

    def key(value):
        parts = [text(unquote(part)) for part in value.split(":")]
        if len(parts) >= 4:
            parts[2] = "1"
        if parts[0] == "SYNTHETIC_FINDING":
            context = parts[-1].split(":")
            context[-1] = "1"
            parts[-1] = ":".join(context)
        return ":".join(quote(part, safe="._-") for part in parts)

    def reference(value):
        return {
            **value,
            "artifact_id": identities.get(value["artifact_id"], value["artifact_id"]),
            "version_number": 1,
            "content_hash": hashes.get(value["content_hash"], value["content_hash"]),
        }

    mapped = []
    for original in document["hypotheses"]:
        item = deepcopy(original)
        item.update(
            id=identities[original["id"]],
            project_id=str(project_id),
            owner_user_id=str(owner_user_id),
        )
        for prefix in ("origin", "twin", "scenario", "design"):
            item[prefix + "_key"] = key(original[prefix + "_key"])
            item[prefix + "_reference"] = reference(original[prefix + "_reference"])
        if original.get("alternative_id") is not None:
            item["alternative_id"] = identities.get(
                original["alternative_id"], original["alternative_id"]
            )
        item["anchor_keys"] = [key(value) for value in original["anchor_keys"]]
        item["mockup_references"] = []
        for anchor in original["mockup_references"]:
            mockup = deepcopy(anchor["mockup"])
            if mockup.get("alternative_id"):
                mockup["alternative_id"] = identities.get(
                    mockup["alternative_id"], mockup["alternative_id"]
                )
            item["mockup_references"].append(
                {
                    "key": key(anchor["key"]),
                    "reference": reference(anchor["reference"]),
                    "mockup": mockup,
                }
            )
        item.pop("content_hash")
        item["content_hash"] = snapshot_content_hash(item)
        hashes[original["content_hash"]] = item["content_hash"]
        mapped.append(hypothesis_from_snapshot(item).to_snapshot())
    outcomes = []
    for original in document["outcomes"]:
        item = deepcopy(original)
        item.update(
            id=identities[original["id"]],
            project_id=str(project_id),
            owner_user_id=str(owner_user_id),
            hypothesis_id=identities[original["hypothesis_id"]],
            hypothesis_content_hash=hashes[original["hypothesis_content_hash"]],
            evidence_id=identities.get(original["evidence_id"], original["evidence_id"]),
        )
        item["citation"]["source_id"] = item["evidence_id"]
        item.pop("content_hash")
        item["content_hash"] = snapshot_content_hash(item)
        hashes[original["content_hash"]] = item["content_hash"]
        outcomes.append(outcome_from_snapshot(item).to_snapshot())
    return {**document, "project_id": str(project_id), "hypotheses": mapped, "outcomes": outcomes}
