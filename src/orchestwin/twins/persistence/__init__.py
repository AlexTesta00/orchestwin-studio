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
from orchestwin.twins.revision_persistence import (
    DiffPersistenceStatus,
    SqlAlchemyUserTwinProfileDiffRepository,
    UserTwinProfileDiffRepository,
    diff_from_record,
    diff_to_record,
)

__all__ = [
    "DiffPersistenceStatus",
    "PersonaVersionRepository",
    "SqlAlchemyPersonaVersionRepository",
    "SqlAlchemyUserModelingSnapshotRepository",
    "SqlAlchemyUserModelingUnitOfWork",
    "SqlAlchemyUserTwinProfileDiffRepository",
    "SqlAlchemyUserTwinVersionRepository",
    "UserModelingSnapshotRepository",
    "UserModelingUnitOfWork",
    "UserTwinProfileDiffRepository",
    "UserTwinVersionRepository",
    "VersionAppendStatus",
    "diff_from_record",
    "diff_to_record",
    "persona_version_from_record",
    "persona_version_to_record",
    "user_modeling_snapshot_version_from_record",
    "user_modeling_snapshot_version_to_record",
    "user_twin_version_from_record",
    "user_twin_version_to_record",
]
