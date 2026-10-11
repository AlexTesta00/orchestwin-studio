from collections.abc import Awaitable, Callable, Mapping
from typing import Final
from uuid import UUID

from orchestwin.models.proposal_evidence import current_proposal_evidence, retain_adapter_result
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.projects.requirements_primitives import snapshot_content_hash

INVALID_PROVIDER_OUTPUT: Final = "INVALID_PROVIDER_OUTPUT"
GENERATION_ATTEMPTS: Final = 2
RETRYABLE_CODES: Final = frozenset(
    {INVALID_PROVIDER_OUTPUT, "INCOMPLETE_OUTPUT", "RESPONSE_SCHEMA_ERROR"}
)


async def record_accepted(scope, result: object, kind: str, content_hash: str) -> None:
    await scope.event(
        "ADAPTER_ACCEPTED",
        {
            "result": result,
            "generated_content_hashes": {kind: [content_hash]},
            **(
                {"related_generations": list(scope.related_generations)}
                if scope.related_generations
                else {}
            ),
        },
    )


async def accept_generation(kind: str, snapshot: dict[str, object]) -> None:
    scope = current_proposal_evidence()
    if scope is None or scope.request is None:
        return
    await record_accepted(scope, snapshot, kind, snapshot_content_hash(snapshot))


async def retire_generation(role: str, code: str, reference: Mapping[str, str]) -> None:
    scope = current_proposal_evidence()
    if scope is None or scope.request is None:
        return
    await scope.event("APPLICATION_RESULT", {"status": code, **reference})
    scope.retire(role=role, code=code)


async def attempt_generation(
    generation: Callable[[], Awaitable[object]],
    bind: Callable[[object], object],
    *,
    role: str,
    rejected: str,
    reference: Mapping[str, str],
    exhausted: str,
):
    for attempt in range(1, GENERATION_ATTEMPTS + 1):
        try:
            output = await generation()
            try:
                return bind(output)
            except (TypeError, ValueError) as error:
                await retain_adapter_result(error=error, reason=str(error))
                raise ProposalGenerationError(INVALID_PROVIDER_OUTPUT) from error
        except ProposalGenerationError as error:
            if attempt == GENERATION_ATTEMPTS or error.code not in RETRYABLE_CODES:
                raise
            await retire_generation(role, rejected, reference)
    raise RuntimeError(exhausted)


def current_generation_ids() -> tuple[UUID, ...]:
    scope = current_proposal_evidence()
    if scope is None:
        return ()
    identifiers = [UUID(str(item["generation_id"])) for item in scope.related_generations]
    if scope.request is not None:
        identifiers.append(scope.request.request_id)
    return tuple(dict.fromkeys(identifiers))
