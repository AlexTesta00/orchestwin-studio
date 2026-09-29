from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Protocol


class GenerationRoutes(Protocol):
    default: str

    def targets(self) -> frozenset[str]: ...

    def resolve(self, task: str, purpose: str | None = None) -> str: ...


class RoutingProposalGenerator:
    def __init__(self, generators: Mapping[str, Any], routes: GenerationRoutes) -> None:
        if not routes.targets() <= set(generators):
            raise ValueError("every route requires a generator")
        self._generators = dict(generators)
        self._routes = routes

    @property
    def generators(self) -> Mapping[str, Any]:
        return MappingProxyType(self._generators)

    @property
    def routes(self) -> GenerationRoutes:
        return self._routes

    @property
    def default(self) -> Any:
        return self._generators[self._routes.default]

    @property
    def configuration(self) -> Any:
        return self.default.configuration

    @property
    def provider_id(self) -> str:
        return self.default.provider_id

    @property
    def port(self) -> Any:
        return self.default.port

    def route(self, task: str, purpose: str | None = None) -> Any:
        return self._generators[self._routes.resolve(task, purpose)]

    async def generate(self, *, task: str, context: Any, **options: Any) -> Any:
        purpose = context.get("purpose") if isinstance(context, Mapping) else None
        target = self.route(task, purpose if isinstance(purpose, str) else None)
        return await target.generate(task=task, context=context, **options)


__all__ = ["GenerationRoutes", "RoutingProposalGenerator"]
