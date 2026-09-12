"""Explicitly configured production Web services; composition performs no I/O."""

from dataclasses import dataclass

from orchestwin.api.governed_web_context import GovernedWebSettings, WebExecutionBackend
from orchestwin.api.governed_web_execution_runtime import SqlAlchemyGovernedWebExecutionApiService
from orchestwin.api.web_execution_read_runtime import SqlAlchemyWebExecutionReadApiService
from orchestwin.api.web_repair_runtime import SqlAlchemyWebRepairApiService
from orchestwin.web_execution.operation_persistence import SqlAlchemyWebOperationStore
from orchestwin.web_execution.profile_loader import build_web_profile_catalog_loader


@dataclass(frozen=True)
class GovernedWebServices:
    start: SqlAlchemyGovernedWebExecutionApiService
    reads: SqlAlchemyWebExecutionReadApiService
    repairs: SqlAlchemyWebRepairApiService
    operations: SqlAlchemyWebOperationStore


def build_governed_web_services(session_factory, settings, *, configuration=None):
    config = configuration if configuration is not None else GovernedWebSettings()
    sources = settings.brownfield_workspace_root / "web-source-objects"
    backend = WebExecutionBackend(
        config=config,
        content_root=sources,
        evidence_root=settings.sandbox_evidence_storage_root,
        resources=settings.sandbox_resource_limits,
    )
    operations = SqlAlchemyWebOperationStore(session_factory)
    start = SqlAlchemyGovernedWebExecutionApiService(
        session_factory,
        operation_store=operations,
        backend=backend,
        catalog_loader=build_web_profile_catalog_loader(session_factory),
    )
    return GovernedWebServices(
        start=start,
        reads=start.reads,
        operations=operations,
        repairs=SqlAlchemyWebRepairApiService(
            session_factory, operation_store=operations, content_root=sources
        ),
    )
