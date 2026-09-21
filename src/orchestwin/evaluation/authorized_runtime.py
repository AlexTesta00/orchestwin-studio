"""Compose owner-authorized verified-content User Twin evaluation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from orchestwin.evaluation.artifact_content import (
    VerifiedArtifactContext,
)
from orchestwin.evaluation.artifact_content_registry import (
    AuthorizedEvaluationArtifactRegistry,
    RegistryBackedArtifactContentSource,
)
from orchestwin.evaluation.artifact_content_resolution import (
    OwnerScopedArtifactContentResolver,
)
from orchestwin.evaluation.authorized_content_application import (
    AuthorizedArtifactContentEvaluationService,
)
from orchestwin.evaluation.authorized_run_application import (
    AuthorizedIndependentUserTwinEvaluationService,
)
from orchestwin.evaluation.evaluator import (
    UserTwinEvaluatorPort,
)


class VerifiedContentFinalEvaluatorRuntime(Protocol):
    """Runtime able to create one evaluator for one verified context."""

    def create_evaluator(
        self,
        *,
        verified_content: VerifiedArtifactContext,
    ) -> UserTwinEvaluatorPort:
        """Create an isolated evaluator bound to verified content."""


def build_authorized_independent_evaluation_service(
    *,
    registry: AuthorizedEvaluationArtifactRegistry,
    read_content: Callable[[str, int], bytes],
    final_evaluator_runtime: (VerifiedContentFinalEvaluatorRuntime | None),
    identifier_provider: Callable[[], UUID],
    clock: Callable[[], datetime],
) -> AuthorizedIndependentUserTwinEvaluationService | None:
    """Compose the final evaluator behind owner-scoped authorization.

    Construction itself performs no artifact read and no model
    generation. A disabled final evaluator exposes no evaluation
    service.
    """
    if final_evaluator_runtime is None:
        return None

    source = RegistryBackedArtifactContentSource(
        registry=registry,
        read_content=read_content,
    )

    resolver = OwnerScopedArtifactContentResolver(source)

    authorized_evaluation = AuthorizedArtifactContentEvaluationService(
        resolver=resolver,
        evaluator_factory=(final_evaluator_runtime.create_evaluator),
    )

    return AuthorizedIndependentUserTwinEvaluationService(
        authorized_evaluation_service=(authorized_evaluation),
        identifier_provider=identifier_provider,
        clock=clock,
    )


__all__ = [
    "VerifiedContentFinalEvaluatorRuntime",
    "build_authorized_independent_evaluation_service",
]
