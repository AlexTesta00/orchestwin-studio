"""Verified, bounded raw failure excerpts alongside immutable normalized findings."""

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

from orchestwin.jvm_execution.workspaces import read_regular_file

MAX_LOG_BYTES = 8 * 1024 * 1024
EXCERPT_BYTES = 3072
MAX_EXCERPTS = 2


def failure_log_context(phase, evidence_root: Path | None):
    """Read only references from an already owner-verified failed attempt.

    Excerpts are a model input, not a replacement for complete retained logs.
    A configured store must verify bytes before any excerpt is exposed.
    """
    if evidence_root is None:
        return {"status": "STORE_NOT_CONFIGURED", "excerpts": []}
    excerpts = []
    references = [
        (stream, reference)
        for stream in ("stdout", "stderr")
        for reference in getattr(phase, stream + "_refs")
    ]
    for stream, reference in references[:MAX_EXCERPTS]:
        raw = _verified_bytes(reference, evidence_root, MAX_LOG_BYTES)
        text = raw.decode("utf-8")
        prefix = raw[:EXCERPT_BYTES].decode("utf-8", errors="ignore")
        excerpts.append(
            {
                "stream": stream,
                "reference": reference.to_snapshot(),
                "start_byte": 0,
                "end_byte": len(prefix.encode("utf-8")),
                "truncated": prefix != text,
                "text": prefix,
            }
        )
    return {
        "status": "VERIFIED_EXCERPTS",
        "excerpts": excerpts,
        "omitted_reference_count": max(0, len(references) - MAX_EXCERPTS),
    }


def _verified_bytes(reference, evidence_root, maximum_bytes):
    digest = reference.sha256_digest
    if (
        not re.fullmatch(r"[0-9a-f]{64}", digest)
        or reference.storage_key != f"sha256/{digest[:2]}/{digest}"
        or not 0 <= reference.size_bytes <= maximum_bytes
    ):
        raise ValueError("REPAIR_LOG_REFERENCE_INVALID")
    raw = read_regular_file(
        evidence_root / reference.storage_key, maximum_bytes=reference.size_bytes
    )
    if len(raw) != reference.size_bytes or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("REPAIR_LOG_CONTENT_MISMATCH")
    return raw


_BUNDLE_KEYS = {"content_hash", "normalized_findings", "request", "routes", "status"}
_SCREEN_TAG = re.compile(r"<[a-zA-Z][^>]*\sdata-design-screen=\"([^\"]+)\"[^>]*>")
_HIDDEN_ATTRIBUTE = re.compile(r"\shidden(?:\s|=|>|/)")
MAX_BUNDLE_BYTES = 256 * 1024
MAX_DOM_BYTES = 1024 * 1024


def _bundle(phase, evidence_root):
    for reference in getattr(phase, "artifact_refs", ()):
        if reference.media_type != "application/json" or reference.size_bytes > MAX_BUNDLE_BYTES:
            continue
        try:
            value = json.loads(_verified_bytes(reference, evidence_root, MAX_BUNDLE_BYTES))
        except (UnicodeDecodeError, ValueError):
            continue
        if (
            isinstance(value, dict)
            and set(value) == _BUNDLE_KEYS
            and isinstance(value["routes"], list)
        ):
            return value
    return None


def _screens(document):
    visible, hidden = [], []
    for match in _SCREEN_TAG.finditer(document):
        target = hidden if _HIDDEN_ATTRIBUTE.search(match.group(0)) else visible
        if match.group(1) not in target:
            target.append(match.group(1))
    return visible, hidden


def browser_final_state(phase, evidence_root: Path | None):
    if evidence_root is None:
        return {"status": "STORE_NOT_CONFIGURED", "routes": []}
    bundle = _bundle(phase, evidence_root)
    if bundle is None:
        return {"status": "NOT_AVAILABLE", "routes": []}
    routes = []
    for route in bundle["routes"]:
        snapshot = route.get("dom_snapshot_ref")
        if not isinstance(route, dict) or not isinstance(snapshot, dict):
            continue
        reference = SimpleNamespace(**snapshot)
        document = _verified_bytes(reference, evidence_root, MAX_DOM_BYTES).decode("utf-8")
        visible, hidden = _screens(document)
        routes.append(
            {
                "route_id": route.get("route", {}).get("route_id"),
                "final_path": route.get("final_path"),
                "visible_screens": visible,
                "hidden_screens": hidden,
            }
        )
    return {"status": "VERIFIED", "routes": routes}
