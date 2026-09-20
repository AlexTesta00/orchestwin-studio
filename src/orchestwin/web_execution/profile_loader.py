"""Load verified durable Web evidence into a consistent capability snapshot.

This read-only service does not generate validation evidence, contact runners,
or compose execution APIs. Each load evaluates the complete stored history.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.web_execution.profile_registry import (
    WebExecutionProfileRegistry,
    create_sprint08_web_profile_registry,
    evaluate_sprint08_web_profile_promotions,
)
from orchestwin.web_execution.validation_evidence import (
    WebProfilePromotionDecision,
    WebProfileValidationEvidenceCatalog,
)
from orchestwin.web_execution.validation_evidence_persistence import (
    SqlAlchemyWebValidationEvidenceUnitOfWork,
    WebValidationEvidenceUnitOfWork,
)


@dataclass(frozen=True, slots=True)
class LoadedWebProfileCatalog:
    """Profiles and diagnostics derived from the same immutable evidence catalog."""

    catalog: WebProfileValidationEvidenceCatalog
    registry: WebExecutionProfileRegistry = field(init=False)
    promotion_decisions: tuple[WebProfilePromotionDecision, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "registry", create_sprint08_web_profile_registry(evidence_catalog=self.catalog)
        )
        object.__setattr__(
            self, "promotion_decisions", evaluate_sprint08_web_profile_promotions(self.catalog)
        )

    def promotion_for(
        self, profile_id: str, profile_version: str
    ) -> WebProfilePromotionDecision | None:
        """Inspect eligibility, missing evidence and issues for one exact profile."""
        return next(
            (
                decision
                for decision in self.promotion_decisions
                if decision.profile_id == profile_id and decision.profile_version == profile_version
            ),
            None,
        )


class WebProfileCatalogLoader:
    """Read once per load; propagate storage failures without cached capability."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], WebValidationEvidenceUnitOfWork],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def load(self) -> LoadedWebProfileCatalog:
        """Return a complete snapshot only after persistence has verified all records."""
        async with self._unit_of_work_factory() as unit:
            records = await unit.evidence.history()
        return LoadedWebProfileCatalog(WebProfileValidationEvidenceCatalog(records=records))


def build_web_profile_catalog_loader(
    session_factory: async_sessionmaker[AsyncSession],
) -> WebProfileCatalogLoader:
    """Compose the production PostgreSQL reader without opening a connection."""
    return WebProfileCatalogLoader(
        unit_of_work_factory=partial(SqlAlchemyWebValidationEvidenceUnitOfWork, session_factory)
    )
