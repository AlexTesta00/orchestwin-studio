from __future__ import annotations

import json
import re
from collections.abc import Mapping
from urllib.parse import unquote

from orchestwin.why import build_why_document

WHY_DOCUMENT = "traceability/why.json"


def folder_why(
    *, project_id: str, documents: Mapping[str, Mapping], files: Mapping[str, str]
) -> dict:
    def read(path):
        return json.loads(files[path]) if path in files else {}

    reviews = read("twins/feedback/reviews.json")
    return build_why_document(
        project_id=project_id,
        stages=documents,
        evidence=read("twins/evidence.json"),
        evaluations=[reviews] if reviews else [],
        learning=read("twins/feedback/learned.json"),
    )


def verify_why(*, project_id: str, documents: Mapping, files: Mapping[str, str]) -> None:
    if WHY_DOCUMENT in files:
        exported = json.loads(files[WHY_DOCUMENT])
        if exported != folder_why(project_id=project_id, documents=documents, files=files):
            from orchestwin.knowledge.archive import KnowledgeArchiveError

            raise KnowledgeArchiveError("FOLDER_TAMPERED", WHY_DOCUMENT)


def normalized_why(document, *, identities=None, hashes=None, remap_versions=True):
    identities = identities or {}
    hashes = hashes or {}
    twin_versions = {
        (node["reference"]["artifact_id"], node["reference"]["version_number"])
        for node in document["nodes"]
        if node["kind"] == "USER_TWIN"
    }
    research_ids = {
        node["reference"]["artifact_id"]
        for node in document["nodes"]
        if node["kind"] == "RESEARCH_EVIDENCE"
    }

    def text(value):
        if remap_versions:
            for twin_id, twin_version in twin_versions:
                value = re.sub(
                    rf"(user-twin:{re.escape(twin_id)}:v){twin_version}(?=#user_twin\.[a-z_]+)",
                    r"\g<1>1",
                    value,
                )
        for old, new in identities.items():
            value = value.replace(old, new)
            value = value.replace(
                "UT-" + old.replace("-", "")[:8].upper(), "UT-" + new.replace("-", "")[:8].upper()
            )
        for old, new in hashes.items():
            value = value.replace(old, new)
        return value

    keys = {}
    for node in document["nodes"]:
        parts = unquote(node["key"]).split(":")
        if remap_versions and node["kind"] != "RESEARCH_EVIDENCE":
            parts[2] = "1" if node["reference"]["version_number"] is not None else ""
        if remap_versions and node["kind"] == "SYNTHETIC_FINDING":
            parts[-1] = "1"
        keys[node["key"]] = text(":".join(parts))

    def visit(value, key=None, source=False):
        if isinstance(value, Mapping):
            source = (
                source
                or "quote" in value
                or ("source_kind" in value and "code" in value)
                or value.get("source_id") in research_ids
            )
            value = dict(value)
            if (
                remap_versions
                and not source
                and "source_version" in value
                and (value.get("content_hash") in hashes or value.get("source_id") in identities)
            ):
                value["source_version"] = 1
            return {
                name: visit(item, name, source)
                for name, item in value.items()
                if name not in {"imported_from", "text_available"}
                and not (name == "document_hashes" and value.get("visual_derived") is True)
            }
        if isinstance(value, list):
            values = [visit(item, key, source) for item in value]
            return sorted(
                values, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False)
            )
        if isinstance(value, str):
            if key == "quote" or (source and key == "content_hash"):
                return value
            if key in {"key", "node_key", "source", "target"} and value in keys:
                return keys[value]
            value = text(value)
            if remap_versions and key in {"code", "related_code"}:
                value = re.sub(r"(?<=-v)[0-9]+", "1", value)
            return value
        if (
            remap_versions
            and key in {"version_number", "version"}
            and not source
            and value is not None
        ):
            return 1
        return value

    nodes = []
    for node in document["nodes"]:
        normalized = visit(node, source=node["kind"] == "RESEARCH_EVIDENCE")
        normalized["gaps"] = [
            gap for gap in normalized["gaps"] if gap["code"] != "SOURCE_TEXT_UNAVAILABLE"
        ]
        nodes.append(normalized)
    return {
        **document,
        "project_id": text(document["project_id"]),
        "nodes": sorted(nodes, key=lambda item: json.dumps(item, sort_keys=True)),
        "links": visit(document["links"]),
        "omitted_sections": sorted(document["omitted_sections"]),
    }
