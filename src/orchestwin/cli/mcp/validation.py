from __future__ import annotations

import hashlib
import json


def verify_records(document, evidence):
    project = document.get("project_id")
    hypotheses = document.get("hypotheses", [])
    outcomes = document.get("outcomes", [])
    if not isinstance(hypotheses, list) or not isinstance(outcomes, list):
        return False
    known = {}
    for item in [*hypotheses, *outcomes]:
        if not isinstance(item, dict) or item.get("project_id") != project:
            return False
        values = {key: value for key, value in item.items() if key != "content_hash"}
        digest = hashlib.sha256(
            json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        if item.get("content_hash") != digest:
            return False
    for item in hypotheses:
        key = (item.get("id"), item.get("version_number"), item.get("content_hash"))
        if key in known or not (item.get("question") or item.get("task")):
            return False
        known[key] = item
    sources = {
        (item.get("id"), item.get("version"), item.get("content_hash")): item
        for item in evidence.get("evidence", [])
    }
    ids = set()
    for item in outcomes:
        key = (
            item.get("hypothesis_id"),
            item.get("hypothesis_version_number"),
            item.get("hypothesis_content_hash"),
        )
        source = sources.get(
            (
                item.get("evidence_id"),
                item.get("evidence_version"),
                item.get("evidence_content_hash"),
            )
        )
        citation = item.get("citation", {})
        if (
            key not in known
            or source is None
            or item.get("id") in ids
            or item.get("owner_user_id") != known[key].get("owner_user_id")
            or citation.get("source_id") != item.get("evidence_id")
            or citation.get("source_version") != item.get("evidence_version")
            or citation.get("content_hash") != item.get("evidence_content_hash")
            or citation.get("end", 0) > source.get("character_count", 0)
        ):
            return False
        if item.get("session_kind") == "HUMAN_SESSION" and (
            source.get("source_kind") != "EMPIRICAL_RESEARCH"
            or source.get("empirical") is not True
            or not all(
                source.get(field, "").strip() for field in ("context", "method", "limitations")
            )
        ):
            return False
        if item.get("session_kind") == "SYNTHETIC_EXERCISE" and (
            source.get("empirical") is not False or not source.get("limitations", "").strip()
        ):
            return False
        ids.add(item.get("id"))
    return True
