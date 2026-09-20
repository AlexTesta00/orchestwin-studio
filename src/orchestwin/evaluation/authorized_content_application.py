"""Application boundary for owner-authorized verified-content evaluation."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from orchestwin.evaluation.artifact_content import VerifiedArtifactContext
from orchestwin.evaluation.artifact_content_resolution import (
    OwnerScopedArtifactContentResolver,
)
from orchestwin.evaluation.evaluator import (
    UserTwinEvaluationRequest,
    UserTwinEvaluationResponse,
    UserTwinEvaluatorPort,
)


class VerifiedContentEvaluatorFactory(Protocol):
    """Create one isolated evaluator bound to verified artifact content."""

    def __call__(
        self,
        *,
        verified_content: VerifiedArtifactContext,
    ) -> UserTwinEvaluatorPort:
        """Return an evaluator for exactly one prepared verified context."""


class AuthorizedArtifactContentEvaluationService:
    """Authorize and verify artifact bytes before evaluator construction."""

    def __init__(
        self,
        *,
        resolver: OwnerScopedArtifactContentResolver,
        evaluator_factory: VerifiedContentEvaluatorFactory,
    ) -> None:
        self._resolver = resolver
        self._evaluator_factory = evaluator_factory

    async def evaluate(
        self,
        *,
        owner_user_id: UUID,
        request: UserTwinEvaluationRequest,
        selected: tuple[tuple[UUID, int], ...],
    ) -> UserTwinEvaluationResponse:
        """Evaluate only after owner scope and artifact bytes are verified."""
        prepared = await self._resolver.prepare(
            owner_user_id=owner_user_id,
            request=request,
            selected=selected,
        )

        evaluator = self._evaluator_factory(
            verified_content=prepared.content,
        )

        response = await evaluator.evaluate(prepared.request)

        # Preserve the verified-content citation invariant independently of
        # the concrete evaluator implementation.
        prepared.content.validate_response(response)

        return response


__all__ = [
    "AuthorizedArtifactContentEvaluationService",
    "VerifiedContentEvaluatorFactory",
]
