"""Persistence adapters for User Modeling and User Twins."""

from orchestwin.twins.persistence.repositories import (
    PersonaVersionRepository,
    SqlAlchemyPersonaVersionRepository,
    SqlAlchemyUserModelingSnapshotRepository,
    SqlAlchemyUserTwinVersionRepository,
    UserModelingSnapshotRepository,
    UserTwinVersionRepository,
    VersionAppendStatus,
)
from orchestwin.twins.persistence.snapshots import (
    persona_version_from_record,
    persona_version_to_record,
    user_modeling_snapshot_version_from_record,
    user_modeling_snapshot_version_to_record,
    user_twin_version_from_record,
    user_twin_version_to_record,
)
from orchestwin.twins.persistence.uow import (
    SqlAlchemyUserModelingUnitOfWork,
    UserModelingUnitOfWork,
)

__all__ = [
    "PersonaVersionRepository",
    "SqlAlchemyPersonaVersionRepository",
    "SqlAlchemyUserModelingSnapshotRepository",
    "SqlAlchemyUserModelingUnitOfWork",
    "SqlAlchemyUserTwinVersionRepository",
    "UserModelingSnapshotRepository",
    "UserModelingUnitOfWork",
    "UserTwinVersionRepository",
    "VersionAppendStatus",
    "persona_version_from_record",
    "persona_version_to_record",
    "user_modeling_snapshot_version_from_record",
    "user_modeling_snapshot_version_to_record",
    "user_twin_version_from_record",
    "user_twin_version_to_record",
]
