"""Per-invocation proposal evidence and application publication boundaries.

Context variables isolate concurrent application commands. SQL adapters persist
observations in short transactions; artifact links join the artifact transaction.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import wraps
from typing import Protocol
from uuid import UUID

from orchestwin.projects.requirements_primitives import snapshot_content_hash


class ProposalEvidenceError(RuntimeError):
    """Evidence could not be retained; publication must stop."""


class ProposalEvidenceStore(Protocol):
    async def begin(self, *, owner_user_id: UUID, project_id: UUID, request) -> None: ...
    async def append(
        self,
        *,
        generation_id: UUID,
        owner_user_id: UUID,
        project_id: UUID,
        kind: str,
        payload: dict,
        raw_body: bytes | None = None,
    ) -> None: ...


@dataclass
class ProposalEvidenceScope:
    store: ProposalEvidenceStore
    owner_user_id: UUID
    project_id: UUID
    request: object | None = None
    result: object | None = None
    accepted_hashes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    observed_events: set[str] = field(default_factory=set)
    related_generations: list[dict] = field(default_factory=list)

    async def begin(self, request):
        if self.request is not None:
            raise ProposalEvidenceError("ONE_GENERATION_PER_COMMAND_REQUIRED")
        await self.store.begin(
            owner_user_id=self.owner_user_id, project_id=self.project_id, request=request
        )
        self.request = request

    async def event(self, kind, payload, *, raw_body=None):
        if self.request is None:
            return
        if kind in self.observed_events:
            raise ProposalEvidenceError("DUPLICATE_GENERATION_EVENT")
        await self.store.append(
            generation_id=self.request.request_id,
            owner_user_id=self.owner_user_id,
            project_id=self.project_id,
            kind=kind,
            payload=payload,
            raw_body=raw_body,
        )
        self.observed_events.add(kind)

    def retire(self, *, role, code):
        self.related_generations.append(
            {
                "role": role,
                "generation_id": str(self.request.request_id),
                "request_hash": self.request.content_hash,
                "code": code,
            }
        )
        self.request = None
        self.result = None
        self.accepted_hashes = {}
        self.observed_events = set()


_SCOPE: ContextVar[ProposalEvidenceScope | None] = ContextVar(
    "proposal_evidence_scope", default=None
)


def current_proposal_evidence():
    return _SCOPE.get()


@contextmanager
def child_proposal_evidence():
    """One independent invocation, retaining its parent application scope."""
    parent = current_proposal_evidence()
    if parent is None or parent.request is None:
        raise ProposalEvidenceError("SOURCE_PARENT_EVIDENCE_REQUIRED")
    child = ProposalEvidenceScope(parent.store, parent.owner_user_id, parent.project_id)
    token = _SCOPE.set(child)
    try:
        yield child
    finally:
        _SCOPE.reset(token)


def evidence_application(function):
    """Capture application disposition, including stale context and rollback errors."""

    @wraps(function)
    async def recorded(self, *args, **kwargs):
        store = self._proposal_evidence_store
        if store is None:
            return await function(self, *args, **kwargs)
        scope = ProposalEvidenceScope(store, kwargs["owner_user_id"], kwargs["project_id"])
        token = _SCOPE.set(scope)
        try:
            try:
                result = await function(self, *args, **kwargs)
            except BaseException as error:
                if not isinstance(error, ProposalEvidenceError):
                    await scope.event(
                        "APPLICATION_RESULT",
                        {
                            "status": "FAILED",
                            "code": getattr(error, "code", type(error).__name__),
                        },
                    )
                raise
            await scope.event(
                "APPLICATION_RESULT",
                {
                    "status": result.status.value,
                    "issue": getattr(getattr(result, "issue", None), "value", None),
                },
            )
            return result
        finally:
            _SCOPE.reset(token)

    return recorded


async def begin_model_generation(request):
    scope = current_proposal_evidence()
    if scope is not None:
        await scope.begin(request)


async def retain_provider_result(result):
    scope = current_proposal_evidence()
    if scope is not None:
        await scope.event("PROVIDER_RESULT", result.to_snapshot())
        scope.result = result


def _generated_hashes(result):
    if getattr(result, "source_binding", None) is not None:
        return {result.kind: (snapshot_content_hash(result.source_binding),)}
    if getattr(result, "proposal", None) is not None:
        return {"AGENT_TEAM": (result.proposal.content_hash,)}
    if getattr(result, "specification", None) is not None:
        return {"REQUIREMENTS": (result.specification.content_hash,)}
    if getattr(result, "package", None) is not None:
        kind = "DESIGN" if hasattr(result.package, "alternatives") else "ARCHITECTURE"
        return {kind: (result.package.content_hash,)}
    proposals = getattr(result, "proposals", ())
    if proposals:
        kind = "PERSONA" if hasattr(proposals[0], "candidate_ordinal") else "USER_TWIN"
        return {kind: tuple(item.profile.content_hash for item in proposals)}
    return {}


MAX_REJECTION_REASON_CHARACTERS = 200


def bounded_rejection_reason(reason):
    if not isinstance(reason, str):
        return None
    text = "".join(
        character
        for character in " ".join(reason.split())
        if character.isascii() and character.isprintable()
    )
    return text[:MAX_REJECTION_REASON_CHARACTERS] or None


async def retain_adapter_result(result=None, *, error=None, reason=None):
    scope = current_proposal_evidence()
    if scope is None or scope.request is None:
        return
    if error is not None:
        if not isinstance(error, ProposalEvidenceError):
            bounded = bounded_rejection_reason(reason)
            await scope.event(
                "ADAPTER_REJECTED",
                {
                    "code": getattr(error, "code", type(error).__name__),
                    **({"reason": bounded} if bounded else {}),
                },
            )
        return
    from orchestwin.models.proposal_generation import wire_value

    hashes = _generated_hashes(result)
    if not hashes or scope.result is None or scope.result.success is None:
        raise ProposalEvidenceError("ACCEPTED_MODEL_OUTPUT_REQUIRED")
    await scope.event(
        "ADAPTER_ACCEPTED",
        {
            "result": wire_value(result),
            "generated_content_hashes": hashes,
            **(
                {"related_generations": scope.related_generations}
                if scope.related_generations
                else {}
            ),
            **(
                {"source_binding": result.source_binding}
                if hasattr(result, "source_binding")
                else {}
            ),
        },
    )
    scope.accepted_hashes = hashes


def generation_output_reference():
    scope = current_proposal_evidence()
    if (
        scope is None
        or scope.request is None
        or scope.result is None
        or scope.result.success is None
    ):
        return None
    return (
        f"generation:{scope.request.request_id}",
        hashlib.sha256(scope.result.success.payload_json.encode("utf-8")).hexdigest(),
    )


async def bind_model_artifacts(unit, kind, versions, *, relation="GENERATED"):
    scope = current_proposal_evidence()
    if scope is None or scope.request is None:
        return
    if not scope.accepted_hashes:
        raise ProposalEvidenceError("ACCEPTED_MODEL_OUTPUT_REQUIRED")
    if not hasattr(unit, "proposal_evidence"):
        raise ProposalEvidenceError("ATOMIC_EVIDENCE_BINDING_REQUIRED")
    references = []
    for version in versions:
        if (
            version.project_id != scope.project_id
            or version.created_by_user_id != scope.owner_user_id
        ):
            raise ProposalEvidenceError("ARTIFACT_OWNER_MISMATCH")
        if relation != "ASSEMBLED" and version.content_hash not in scope.accepted_hashes.get(
            kind, ()
        ):
            raise ProposalEvidenceError("ARTIFACT_CONTENT_MISMATCH")
        if relation == "ASSEMBLED" and (
            kind != "USER_MODELING" or "USER_TWIN" not in scope.accepted_hashes
        ):
            raise ProposalEvidenceError("ASSEMBLED_ARTIFACT_MISMATCH")
        references.append(
            {
                "kind": kind,
                "version_id": str(version.id),
                "version_number": version.version_number,
                "content_hash": version.content_hash,
                "relation": relation,
            }
        )
    await unit.proposal_evidence.bind(scope, references)


class AuditedProposalTransport:
    """Keep exact HTTP bytes before schema validation; never retain auth headers."""

    def __init__(self, transport):
        self.transport = transport

    async def post_json(self, **kwargs):
        scope = current_proposal_evidence()
        if scope is None:
            return await self.transport.post_json(**kwargs)
        if scope.request is None:
            raise ProposalEvidenceError("REQUEST_EVIDENCE_REQUIRED")
        await scope.event("HTTP_REQUEST", {"payload": kwargs["payload"]})
        try:
            response = await self.transport.post_json(**kwargs)
        except BaseException as error:
            if not isinstance(error, ProposalEvidenceError):
                await scope.event("TRANSPORT_ERROR", {"code": type(error).__name__})
            raise
        authorization = kwargs.get("headers", {}).get("Authorization", "")
        credential = authorization.removeprefix("Bearer ").encode("utf-8")
        reflected = bool(credential and credential in response.body)
        await scope.event(
            "HTTP_RESPONSE",
            {
                "status_code": response.status_code,
                "elapsed_milliseconds": response.elapsed_milliseconds,
                "body_sha256": hashlib.sha256(response.body).hexdigest(),
                "body_size_bytes": len(response.body),
                "body_retained": not reflected,
                "withheld_reason": "CREDENTIAL_REFLECTION" if reflected else None,
            },
            raw_body=None if reflected else response.body,
        )
        if reflected:
            raise ProposalEvidenceError("PROVIDER_REFLECTED_CREDENTIAL")
        return response


def evidence_snapshot(payload):
    """Canonical audit envelope with explicit time and content hash."""
    snapshot = {"schema_version": 1, "recorded_at": datetime.now(UTC).isoformat(), **payload}
    return snapshot, snapshot_content_hash(snapshot)
