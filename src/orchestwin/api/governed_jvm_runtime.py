"""JVM runtime composition performs no database, filesystem or Docker I/O."""

from dataclasses import dataclass

from orchestwin.api.governed_jvm_context import GovernedJvmSettings, JvmExecutionBackend
from orchestwin.api.governed_jvm_execution_runtime import SqlAlchemyGovernedJvmExecutionApiService
from orchestwin.api.jvm_execution_read_runtime import SqlAlchemyJvmExecutionReadApiService
from orchestwin.jvm_execution.operation_persistence import SqlAlchemyJvmOperationStore
from orchestwin.jvm_execution.profile_loader import build_jvm_profile_catalog_loader


@dataclass(frozen=True)
class GovernedJvmServices:
    start: SqlAlchemyGovernedJvmExecutionApiService
    reads: SqlAlchemyJvmExecutionReadApiService
    operations: SqlAlchemyJvmOperationStore


def build_governed_jvm_services(session_factory, settings, *, configuration=None):
    config = configuration if configuration is not None else GovernedJvmSettings()
    backend = JvmExecutionBackend(
        config=config,
        content_root=settings.brownfield_workspace_root / "jvm-source-objects",
        evidence_root=settings.sandbox_evidence_storage_root,
    )
    operations = SqlAlchemyJvmOperationStore(session_factory)
    catalog = build_jvm_profile_catalog_loader(session_factory)
    return GovernedJvmServices(
        start=SqlAlchemyGovernedJvmExecutionApiService(
            session_factory, operation_store=operations, backend=backend, catalog_loader=catalog
        ),
        reads=SqlAlchemyJvmExecutionReadApiService(session_factory, catalog_loader=catalog),
        operations=operations,
    )
