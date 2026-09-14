"""Verified, bounded raw failure excerpts alongside immutable normalized findings."""

import hashlib
import re
from pathlib import Path

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
        digest = reference.sha256_digest
        if (
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            or reference.storage_key != f"sha256/{digest[:2]}/{digest}"
            or not 0 <= reference.size_bytes <= MAX_LOG_BYTES
        ):
            raise ValueError("REPAIR_LOG_REFERENCE_INVALID")
        raw = read_regular_file(
            evidence_root / reference.storage_key, maximum_bytes=reference.size_bytes
        )
        if len(raw) != reference.size_bytes or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("REPAIR_LOG_CONTENT_MISMATCH")
        # A UTF-8 boundary can fall inside the byte budget; expose only complete characters.
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
