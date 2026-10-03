from __future__ import annotations

from copy import deepcopy

from orchestwin.artifacts.provided_prototypes import provided_prototype_from_snapshot
from orchestwin.workflow_inputs import PROVIDED_PROTOTYPE_LIMITS, validate_workflow_records


def add_workflow_why(builder, records):
    if not records or not (records.get("decisions") or records.get("prototypes")):
        return None
    records = validate_workflow_records(records)
    latest = {item["target"]: item["sequence"] for item in records["decisions"]}
    for item in records["decisions"]:
        current = latest[item["target"]] == item["sequence"]
        node = builder.node(
            "WORKFLOW_DECISION",
            f"GAP-{item['sequence']:03}",
            item["reason"],
            {
                "artifact_id": item["id"],
                "version_number": item["sequence"],
                "content_hash": item["content_hash"],
            },
            current=current,
            data={"rationale": item["reason"]},
            rationale_origin="OWNER",
        )
        node["declared_context"].update(
            {"workflow_decision": deepcopy(item), "origin": "OWNER_INPUT"}
        )
        if current and item["action"] == "DECLARE_MISSING":
            builder.gap(node, "DECLARED_MISSING", item["target"], item["target"])
        for target, reference in item["base_context"].items():
            stage = {
                "BRIEF": "brief",
                "TEAM": "team",
                "USER_TWINS": "twins",
                "REQUIREMENTS": "requirements",
            }.get(target)
            if stage:
                builder.stage_context(node, reference, stage)
    versions = {}
    for item in records["prototypes"]:
        versions[item["id"]] = max(versions.get(item["id"], 0), item["version_number"])
    for item in records["prototypes"]:
        prototype = provided_prototype_from_snapshot(item)
        node = builder.node(
            "PROVIDED_PROTOTYPE",
            item["code"],
            item["title"],
            {
                "artifact_id": item["id"],
                "version_number": item["version_number"],
                "content_hash": item["content_hash"],
            },
            current=versions[item["id"]] == item["version_number"],
        )
        node["declared_context"].update(
            {
                "provided_prototype": deepcopy(item),
                "origin": "OWNER_INPUT",
                "limits": list(PROVIDED_PROTOTYPE_LIMITS),
            }
        )
        builder.stage_context(node, item["definition_reference"], "requirements")
        for code in PROVIDED_PROTOTYPE_LIMITS:
            builder.gap(node, code, item["code"], "design")
        used = dict(prototype.mockup.requirement_ids_by_code)
        for existing in tuple(builder.nodes.values()):
            if (
                existing["kind"] != "REQUIREMENT"
                or existing["reference"]["content_hash"]
                != item["definition_reference"]["content_hash"]
            ):
                continue
            if (
                used.get(existing["code"]) is not None
                and str(used[existing["code"]]) == existing["reference"]["artifact_id"]
            ):
                builder.link(node, existing, "TRACES_TO")
            else:
                builder.gap(node, "MISSING_REQUIREMENT_ANCHOR", existing["code"], "design")
    return records
