from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash

EVIDENCE_PURPOSE = "TWIN_EVIDENCE_UPDATE"
RETENTION_POLICY = "EVIDENCE_MINIMIZED"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_LABEL = re.compile(r"[A-Z][A-Z0-9_]{0,63}")


def evidence_request_context(request) -> dict:
    try:
        payload = json.loads(request.input_payload_json)
        context = payload.get("context", {})
    except (AttributeError, TypeError, ValueError):
        return {}
    if not isinstance(context, dict):
        return {}
    nested = context.get("request")
    return nested if isinstance(nested, dict) else context


def minimizes_evidence_request(request) -> bool:
    return evidence_request_context(request).get("purpose") == EVIDENCE_PURPOSE


def _reference(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _digest(value):
    return value if isinstance(value, str) and _DIGEST.fullmatch(value) else None


def _label(value):
    return value if isinstance(value, str) and _LABEL.fullmatch(value) else None


def _count(value):
    return value if type(value) is int and value >= 0 else None


@dataclass(frozen=True, slots=True)
class MinimizedEvidenceRequest:
    request_id: UUID
    task_id: str
    content_hash: str
    input_payload_json: str
    snapshot: dict

    def to_snapshot(self):
        return dict(self.snapshot)


def minimize_evidence_request(request):
    if isinstance(request, MinimizedEvidenceRequest) or not minimizes_evidence_request(request):
        return request
    context = evidence_request_context(request)
    evidence = context.get("evidence", {})
    twin = context.get("user_twin", {})
    minimal_context = {
        "project_id": _reference(context.get("project_id")),
        "purpose": EVIDENCE_PURPOSE,
        "evidence": {
            "source_id": _reference(evidence.get("id", evidence.get("source_id"))),
            "source_version": _count(evidence.get("version", evidence.get("source_version"))),
            "content_hash": _digest(evidence.get("content_hash")),
            "character_count": _count(evidence.get("character_count")),
            "byte_count": _count(evidence.get("byte_count")),
        },
        "user_twin": {
            "twin_id": _reference(twin.get("twin_id")),
            "version_number": _count(twin.get("version_number")),
            "content_hash": _digest(twin.get("content_hash")),
        },
    }
    payload = canonical_json({"context": minimal_context})
    schema = request.output_schema
    snapshot = {
        "schema_version": request.schema_version,
        "request_id": str(request.request_id),
        "task_id": request.task_id,
        "expected_identity": request.expected_identity.to_snapshot(),
        "output_schema": {
            "schema_id": schema.schema_id,
            "version_number": schema.version_number,
            "content_hash": schema.content_hash,
        },
        "system_instruction_sha256": hashlib.sha256(
            request.system_instruction.encode("utf-8")
        ).hexdigest(),
        "input_payload_sha256": hashlib.sha256(
            request.input_payload_json.encode("utf-8")
        ).hexdigest(),
        "input_payload_json": payload,
        "prompt_version_ref": request.prompt_version_ref,
        "temperature": float(request.temperature),
        "max_output_tokens": request.max_output_tokens,
        "timeout_seconds": request.timeout_seconds,
        "content_hash": request.content_hash,
        "retention_policy": RETENTION_POLICY,
    }
    return MinimizedEvidenceRequest(
        request.request_id, request.task_id, request.content_hash, payload, snapshot
    )


def _usage(values):
    if not isinstance(values, Mapping):
        return {}
    return {
        key: value
        for key in (
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "latency_milliseconds",
            "cache_read_input_tokens",
            "cache_write_input_tokens",
            "cost_microusd",
        )
        if (value := _count(values.get(key))) is not None
    }


def _provider_result(payload):
    result = {
        "provider_kind": _label(payload.get("provider_kind")),
        "status": _label(payload.get("status")),
        "success": None,
        "failure": None,
    }
    if _label(payload.get("output_mode")):
        result["output_mode"] = payload["output_mode"]
    success = payload.get("success")
    if isinstance(success, Mapping):
        result["success"] = {
            "usage": _usage(success.get("usage")),
            "finish_reason": _label(success.get("finish_reason")),
            "content_hash": _digest(success.get("content_hash")),
            "payload_json_sha256": _digest(success.get("payload_json_sha256")),
        }
        if isinstance(success.get("payload_json"), str):
            result["success"]["payload_json_sha256"] = hashlib.sha256(
                success["payload_json"].encode("utf-8")
            ).hexdigest()
    failure = payload.get("failure")
    if isinstance(failure, Mapping):
        result["failure"] = {
            "code": _label(failure.get("code")),
            "retryable": failure.get("retryable") is True,
            "provider_status_code": _count(failure.get("provider_status_code")),
            "usage": _usage(failure.get("usage")),
        }
    return result


def minimize_evidence_event(kind: str, payload: Mapping) -> dict:
    minimal = {"retention_policy": RETENTION_POLICY}
    if kind == "PROVIDER_RESULT":
        minimal = {**_provider_result(payload), **minimal}
    if kind == "HTTP_REQUEST":
        digest = _digest(payload.get("payload_sha256"))
        minimal.update(
            payload_sha256=digest or snapshot_content_hash(payload.get("payload", {})),
            payload_retained=False,
        )
    if kind == "HTTP_RESPONSE":
        for key in ("status_code", "elapsed_milliseconds", "body_size_bytes"):
            if (value := _count(payload.get(key))) is not None:
                minimal[key] = value
        minimal.update(
            body_sha256=_digest(payload.get("body_sha256")),
            body_retained=False,
            withheld_reason="CREDENTIAL_REFLECTION"
            if payload.get("withheld_reason") == "CREDENTIAL_REFLECTION"
            else RETENTION_POLICY,
        )
    if kind == "ADAPTER_ACCEPTED":
        generated = payload.get("generated_content_hashes", {})
        minimal["generated_content_hashes"] = {
            key: [item for item in values if _digest(item)]
            for key, values in generated.items()
            if _label(key) and isinstance(values, (list, tuple))
        }
        minimal["result_hash"] = (
            snapshot_content_hash(payload["result"])
            if "result" in payload
            else _digest(payload.get("result_hash"))
        )
        result = payload.get("result", {})
        evidence = result.get("evidence", {}) if isinstance(result, Mapping) else {}
        for key, value in (
            ("twin_update_id", result.get("id") if isinstance(result, Mapping) else None),
            ("twin_id", result.get("twin_id") if isinstance(result, Mapping) else None),
            ("source_id", evidence.get("source_id")),
        ):
            if (reference := _reference(value)) is not None:
                minimal[key] = reference
        if (version := _count(evidence.get("source_version"))) is not None:
            minimal["source_version"] = version
        if (digest := _digest(evidence.get("content_hash"))) is not None:
            minimal["content_hash"] = digest
        rejected = _count(payload.get("rejected_changes", evidence.get("rejected_changes")))
        if rejected is not None:
            minimal["rejected_changes"] = rejected
        changes = result.get("observations") if isinstance(result, Mapping) else None
        count = (
            len(changes)
            if isinstance(changes, (list, tuple))
            else _count(payload.get("accepted_changes"))
        )
        if count is not None:
            minimal["accepted_changes"] = count
    for key in ("status", "code", "issue", "role"):
        if (value := _label(payload.get(key))) is not None:
            minimal[key] = value
    for key in (
        "update_id",
        "twin_update_id",
        "research_evidence_id",
        "source_id",
        "twin_id",
        "generation_id",
    ):
        if (value := _reference(payload.get(key))) is not None:
            minimal[key] = value
    for key in ("content_hash", "request_hash", "input_hash", "schema_hash", "instruction_hash"):
        if (value := _digest(payload.get(key))) is not None:
            minimal[key] = value
    for key in ("accepted_changes", "rejected_changes", "source_version"):
        if (value := _count(payload.get(key))) is not None:
            minimal[key] = value
    return minimal
