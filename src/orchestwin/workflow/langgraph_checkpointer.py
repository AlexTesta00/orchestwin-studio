"""Owner-scoped LangGraph checkpoint adapter for durable workflow recovery."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol, cast
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    SerializerProtocol,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.workflow.langgraph_persistence import (
    LangGraphCheckpointRecord,
    LangGraphWriteRecord,
)
from orchestwin.workflow.runs import WorkflowRun

_MAX_CHECKPOINT_NAMESPACE_LENGTH = 256
_MAX_CHECKPOINT_ID_LENGTH = 64
_MAX_TASK_ID_LENGTH = 128
_MAX_TASK_PATH_LENGTH = 512
_MAX_CHANNEL_LENGTH = 256


@dataclass(frozen=True, slots=True)
class StoredLangGraphCheckpoint:
    """One serialized graph checkpoint scoped to an exact workflow run."""

    run_id: UUID
    project_id: UUID
    owner_user_id: UUID
    checkpoint_namespace: str
    checkpoint_id: str
    parent_checkpoint_id: str | None
    checkpoint_type: str
    checkpoint_blob: bytes
    metadata_type: str
    metadata_blob: bytes

    def __post_init__(self) -> None:
        _validate_bounded_text(
            self.checkpoint_namespace,
            label="LangGraph checkpoint namespace",
            maximum_length=_MAX_CHECKPOINT_NAMESPACE_LENGTH,
            allow_empty=True,
        )
        _validate_bounded_text(
            self.checkpoint_id,
            label="LangGraph checkpoint id",
            maximum_length=_MAX_CHECKPOINT_ID_LENGTH,
        )
        if self.parent_checkpoint_id is not None:
            _validate_bounded_text(
                self.parent_checkpoint_id,
                label="LangGraph parent checkpoint id",
                maximum_length=_MAX_CHECKPOINT_ID_LENGTH,
            )
        _validate_serialized_value(
            self.checkpoint_type,
            self.checkpoint_blob,
            label="LangGraph checkpoint",
        )
        _validate_serialized_value(
            self.metadata_type,
            self.metadata_blob,
            label="LangGraph checkpoint metadata",
        )


@dataclass(frozen=True, slots=True)
class StoredLangGraphWrite:
    """One serialized pending write associated with a graph checkpoint."""

    run_id: UUID
    project_id: UUID
    owner_user_id: UUID
    checkpoint_namespace: str
    checkpoint_id: str
    task_id: str
    write_index: int
    task_path: str
    channel: str
    value_type: str
    value_blob: bytes

    def __post_init__(self) -> None:
        _validate_bounded_text(
            self.checkpoint_namespace,
            label="LangGraph checkpoint namespace",
            maximum_length=_MAX_CHECKPOINT_NAMESPACE_LENGTH,
            allow_empty=True,
        )
        _validate_bounded_text(
            self.checkpoint_id,
            label="LangGraph checkpoint id",
            maximum_length=_MAX_CHECKPOINT_ID_LENGTH,
        )
        _validate_bounded_text(
            self.task_id,
            label="LangGraph task id",
            maximum_length=_MAX_TASK_ID_LENGTH,
        )
        _validate_bounded_text(
            self.task_path,
            label="LangGraph task path",
            maximum_length=_MAX_TASK_PATH_LENGTH,
            allow_empty=True,
        )
        _validate_bounded_text(
            self.channel,
            label="LangGraph write channel",
            maximum_length=_MAX_CHANNEL_LENGTH,
        )
        _validate_serialized_value(
            self.value_type,
            self.value_blob,
            label="LangGraph pending write",
        )

    @property
    def identity(self) -> tuple[UUID, str, str, str, int]:
        """Return the storage identity used by LangGraph write de-duplication."""
        return (
            self.run_id,
            self.checkpoint_namespace,
            self.checkpoint_id,
            self.task_id,
            self.write_index,
        )


class LangGraphCheckpointStore(Protocol):
    """Serialized storage port used by the LangGraph checkpoint adapter."""

    async def get_checkpoint(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_user_id: UUID,
        checkpoint_namespace: str,
        checkpoint_id: str | None,
    ) -> StoredLangGraphCheckpoint | None: ...

    async def list_checkpoints(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_user_id: UUID,
        checkpoint_namespace: str | None,
    ) -> tuple[StoredLangGraphCheckpoint, ...]: ...

    async def put_checkpoint(self, checkpoint: StoredLangGraphCheckpoint) -> None: ...

    async def list_writes(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_user_id: UUID,
        checkpoint_namespace: str,
        checkpoint_id: str,
    ) -> tuple[StoredLangGraphWrite, ...]: ...

    async def put_write(
        self,
        write: StoredLangGraphWrite,
        *,
        replace_existing: bool,
    ) -> None: ...

    async def delete_run(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> None: ...


class InMemoryLangGraphCheckpointStore:
    """Deterministic serialized graph-checkpoint store for ordinary tests."""

    def __init__(self) -> None:
        self._checkpoints: dict[
            tuple[UUID, UUID, UUID, str, str],
            StoredLangGraphCheckpoint,
        ] = {}
        self._writes: dict[
            tuple[UUID, str, str, str, int],
            StoredLangGraphWrite,
        ] = {}

    async def get_checkpoint(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_user_id: UUID,
        checkpoint_namespace: str,
        checkpoint_id: str | None,
    ) -> StoredLangGraphCheckpoint | None:
        candidates = await self.list_checkpoints(
            run_id=run_id,
            project_id=project_id,
            owner_user_id=owner_user_id,
            checkpoint_namespace=checkpoint_namespace,
        )
        if checkpoint_id is None:
            return candidates[0] if candidates else None
        return next(
            (item for item in candidates if item.checkpoint_id == checkpoint_id),
            None,
        )

    async def list_checkpoints(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_user_id: UUID,
        checkpoint_namespace: str | None,
    ) -> tuple[StoredLangGraphCheckpoint, ...]:
        candidates = (
            checkpoint
            for key, checkpoint in self._checkpoints.items()
            if key[0] == run_id
            and key[1] == project_id
            and key[2] == owner_user_id
            and (checkpoint_namespace is None or key[3] == checkpoint_namespace)
        )
        return tuple(
            sorted(
                candidates,
                key=lambda item: (item.checkpoint_namespace, item.checkpoint_id),
                reverse=True,
            )
        )

    async def put_checkpoint(self, checkpoint: StoredLangGraphCheckpoint) -> None:
        key = (
            checkpoint.run_id,
            checkpoint.project_id,
            checkpoint.owner_user_id,
            checkpoint.checkpoint_namespace,
            checkpoint.checkpoint_id,
        )
        existing = self._checkpoints.get(key)
        if existing is not None and existing != checkpoint:
            raise ValueError("LangGraph checkpoint identity already contains different data")
        self._checkpoints[key] = checkpoint

    async def list_writes(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_user_id: UUID,
        checkpoint_namespace: str,
        checkpoint_id: str,
    ) -> tuple[StoredLangGraphWrite, ...]:
        return tuple(
            sorted(
                (
                    write
                    for write in self._writes.values()
                    if write.run_id == run_id
                    and write.project_id == project_id
                    and write.owner_user_id == owner_user_id
                    and write.checkpoint_namespace == checkpoint_namespace
                    and write.checkpoint_id == checkpoint_id
                ),
                key=lambda item: (item.task_id, item.write_index),
            )
        )

    async def put_write(
        self,
        write: StoredLangGraphWrite,
        *,
        replace_existing: bool,
    ) -> None:
        existing = self._writes.get(write.identity)
        if existing is not None and (existing == write or not replace_existing):
            return
        self._writes[write.identity] = write

    async def delete_run(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> None:
        checkpoint_keys = [
            key for key in self._checkpoints if key[:3] == (run_id, project_id, owner_user_id)
        ]
        for key in checkpoint_keys:
            del self._checkpoints[key]
        write_keys = [
            key
            for key, write in self._writes.items()
            if write.run_id == run_id
            and write.project_id == project_id
            and write.owner_user_id == owner_user_id
        ]
        for key in write_keys:
            del self._writes[key]


class SqlAlchemyLangGraphCheckpointStore:
    """PostgreSQL serialized graph store bound to one application transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_checkpoint(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_user_id: UUID,
        checkpoint_namespace: str,
        checkpoint_id: str | None,
    ) -> StoredLangGraphCheckpoint | None:
        statement = select(LangGraphCheckpointRecord).where(
            LangGraphCheckpointRecord.run_id == run_id,
            LangGraphCheckpointRecord.project_id == project_id,
            LangGraphCheckpointRecord.owner_user_id == owner_user_id,
            LangGraphCheckpointRecord.checkpoint_namespace == checkpoint_namespace,
        )
        if checkpoint_id is None:
            statement = statement.order_by(LangGraphCheckpointRecord.checkpoint_id.desc()).limit(1)
        else:
            statement = statement.where(LangGraphCheckpointRecord.checkpoint_id == checkpoint_id)
        record = await self._session.scalar(statement)
        return None if record is None else _checkpoint_record_to_stored(record)

    async def list_checkpoints(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_user_id: UUID,
        checkpoint_namespace: str | None,
    ) -> tuple[StoredLangGraphCheckpoint, ...]:
        statement = select(LangGraphCheckpointRecord).where(
            LangGraphCheckpointRecord.run_id == run_id,
            LangGraphCheckpointRecord.project_id == project_id,
            LangGraphCheckpointRecord.owner_user_id == owner_user_id,
        )
        if checkpoint_namespace is not None:
            statement = statement.where(
                LangGraphCheckpointRecord.checkpoint_namespace == checkpoint_namespace
            )
        records = await self._session.scalars(
            statement.order_by(
                LangGraphCheckpointRecord.checkpoint_namespace.desc(),
                LangGraphCheckpointRecord.checkpoint_id.desc(),
            )
        )
        return tuple(_checkpoint_record_to_stored(record) for record in records.all())

    async def put_checkpoint(self, checkpoint: StoredLangGraphCheckpoint) -> None:
        existing = await self.get_checkpoint(
            run_id=checkpoint.run_id,
            project_id=checkpoint.project_id,
            owner_user_id=checkpoint.owner_user_id,
            checkpoint_namespace=checkpoint.checkpoint_namespace,
            checkpoint_id=checkpoint.checkpoint_id,
        )
        if existing is not None:
            if existing != checkpoint:
                raise ValueError("LangGraph checkpoint identity already contains different data")
            return
        self._session.add(_stored_checkpoint_to_record(checkpoint))
        await self._session.flush()

    async def list_writes(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_user_id: UUID,
        checkpoint_namespace: str,
        checkpoint_id: str,
    ) -> tuple[StoredLangGraphWrite, ...]:
        records = await self._session.scalars(
            select(LangGraphWriteRecord)
            .where(
                LangGraphWriteRecord.run_id == run_id,
                LangGraphWriteRecord.project_id == project_id,
                LangGraphWriteRecord.owner_user_id == owner_user_id,
                LangGraphWriteRecord.checkpoint_namespace == checkpoint_namespace,
                LangGraphWriteRecord.checkpoint_id == checkpoint_id,
            )
            .order_by(
                LangGraphWriteRecord.task_id,
                LangGraphWriteRecord.write_index,
            )
        )
        return tuple(_write_record_to_stored(record) for record in records.all())

    async def put_write(
        self,
        write: StoredLangGraphWrite,
        *,
        replace_existing: bool,
    ) -> None:
        record = await self._session.scalar(
            select(LangGraphWriteRecord).where(
                LangGraphWriteRecord.run_id == write.run_id,
                LangGraphWriteRecord.checkpoint_namespace == write.checkpoint_namespace,
                LangGraphWriteRecord.checkpoint_id == write.checkpoint_id,
                LangGraphWriteRecord.task_id == write.task_id,
                LangGraphWriteRecord.write_index == write.write_index,
                LangGraphWriteRecord.project_id == write.project_id,
                LangGraphWriteRecord.owner_user_id == write.owner_user_id,
            )
        )
        if record is not None:
            existing = _write_record_to_stored(record)
            if existing == write or not replace_existing:
                return
            record.task_path = write.task_path
            record.channel = write.channel
            record.value_type = write.value_type
            record.value_blob = write.value_blob
        else:
            self._session.add(_stored_write_to_record(write))
        await self._session.flush()

    async def delete_run(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> None:
        await self._session.execute(
            delete(LangGraphWriteRecord).where(
                LangGraphWriteRecord.run_id == run_id,
                LangGraphWriteRecord.project_id == project_id,
                LangGraphWriteRecord.owner_user_id == owner_user_id,
            )
        )
        await self._session.execute(
            delete(LangGraphCheckpointRecord).where(
                LangGraphCheckpointRecord.run_id == run_id,
                LangGraphCheckpointRecord.project_id == project_id,
                LangGraphCheckpointRecord.owner_user_id == owner_user_id,
            )
        )
        await self._session.flush()


class RunScopedLangGraphCheckpointer(BaseCheckpointSaver[str]):
    """Async LangGraph checkpointer restricted to one exact owned workflow run."""

    def __init__(
        self,
        store: LangGraphCheckpointStore,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_user_id: UUID,
        serde: SerializerProtocol | None = None,
        authoritative_run: WorkflowRun | None = None,
        authoritative_checkpoint_id: str | None = None,
    ) -> None:
        super().__init__(serde=serde)
        if (authoritative_run is None) != (authoritative_checkpoint_id is None):
            raise ValueError(
                "authoritative workflow run and graph checkpoint id must be supplied together"
            )
        if authoritative_run is not None and (
            authoritative_run.id != run_id
            or authoritative_run.project_id != project_id
            or authoritative_run.owner_user_id != owner_user_id
        ):
            raise ValueError("authoritative workflow run does not match checkpointer scope")
        if authoritative_checkpoint_id is not None:
            _validate_bounded_text(
                authoritative_checkpoint_id,
                label="authoritative LangGraph checkpoint id",
                maximum_length=_MAX_CHECKPOINT_ID_LENGTH,
            )
        self._store = store
        self._run_id = run_id
        self._project_id = project_id
        self._owner_user_id = owner_user_id
        self._authoritative_run = authoritative_run
        self._authoritative_checkpoint_id = authoritative_checkpoint_id

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        configurable = self._validated_configurable(config)
        namespace = _checkpoint_namespace(configurable)
        requested_id = _optional_text(configurable.get("checkpoint_id"))
        stored = await self._store.get_checkpoint(
            run_id=self._run_id,
            project_id=self._project_id,
            owner_user_id=self._owner_user_id,
            checkpoint_namespace=namespace,
            checkpoint_id=requested_id,
        )
        if stored is None:
            return None
        writes = await self._store.list_writes(
            run_id=self._run_id,
            project_id=self._project_id,
            owner_user_id=self._owner_user_id,
            checkpoint_namespace=stored.checkpoint_namespace,
            checkpoint_id=stored.checkpoint_id,
        )
        checkpoint = cast(
            Checkpoint,
            self.serde.loads_typed((stored.checkpoint_type, stored.checkpoint_blob)),
        )
        if (
            self._authoritative_run is not None
            and stored.checkpoint_id == self._authoritative_checkpoint_id
        ):
            checkpoint = reconcile_checkpoint_with_authoritative_run(
                checkpoint,
                authoritative_run=self._authoritative_run,
            )
        metadata = cast(
            CheckpointMetadata,
            self.serde.loads_typed((stored.metadata_type, stored.metadata_blob)),
        )
        return CheckpointTuple(
            config=_checkpoint_config(
                self._run_id,
                stored.checkpoint_namespace,
                stored.checkpoint_id,
            ),
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=(
                _checkpoint_config(
                    self._run_id,
                    stored.checkpoint_namespace,
                    stored.parent_checkpoint_id,
                )
                if stored.parent_checkpoint_id is not None
                else None
            ),
            pending_writes=[
                (
                    write.task_id,
                    write.channel,
                    self.serde.loads_typed((write.value_type, write.value_blob)),
                )
                for write in writes
            ],
        )

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        if limit is not None and limit <= 0:
            return
        namespace: str | None = None
        requested_id: str | None = None
        if config is not None:
            configurable = self._validated_configurable(config)
            namespace = _checkpoint_namespace(configurable)
            requested_id = _optional_text(configurable.get("checkpoint_id"))
        before_id: str | None = None
        if before is not None:
            before_configurable = self._validated_configurable(before)
            before_namespace = _checkpoint_namespace(before_configurable)
            if namespace is not None and before_namespace != namespace:
                raise ValueError("LangGraph before cursor namespace does not match")
            namespace = before_namespace
            before_id = get_checkpoint_id(before)

        stored_checkpoints = await self._store.list_checkpoints(
            run_id=self._run_id,
            project_id=self._project_id,
            owner_user_id=self._owner_user_id,
            checkpoint_namespace=namespace,
        )
        yielded = 0
        for stored in stored_checkpoints:
            if requested_id is not None and stored.checkpoint_id != requested_id:
                continue
            if before_id is not None and stored.checkpoint_id >= before_id:
                continue
            item = await self.aget_tuple(
                _checkpoint_config(
                    self._run_id,
                    stored.checkpoint_namespace,
                    stored.checkpoint_id,
                )
            )
            if item is None:
                continue
            if filter and not all(item.metadata.get(key) == value for key, value in filter.items()):
                continue
            yield item
            yielded += 1
            if limit is not None and yielded >= limit:
                return

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        del new_versions
        configurable = self._validated_configurable(config)
        namespace = _checkpoint_namespace(configurable)
        checkpoint_id = _required_text(checkpoint.get("id"), label="LangGraph checkpoint id")
        _validate_bounded_text(
            checkpoint_id,
            label="LangGraph checkpoint id",
            maximum_length=_MAX_CHECKPOINT_ID_LENGTH,
        )
        parent_id = _optional_text(configurable.get("checkpoint_id"))
        checkpoint_type, checkpoint_blob = self.serde.dumps_typed(checkpoint)
        metadata_type, metadata_blob = self.serde.dumps_typed(
            get_checkpoint_metadata(config, metadata)
        )
        await self._store.put_checkpoint(
            StoredLangGraphCheckpoint(
                run_id=self._run_id,
                project_id=self._project_id,
                owner_user_id=self._owner_user_id,
                checkpoint_namespace=namespace,
                checkpoint_id=checkpoint_id,
                parent_checkpoint_id=parent_id,
                checkpoint_type=checkpoint_type,
                checkpoint_blob=checkpoint_blob,
                metadata_type=metadata_type,
                metadata_blob=metadata_blob,
            )
        )
        return _checkpoint_config(self._run_id, namespace, checkpoint_id)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        configurable = self._validated_configurable(config)
        namespace = _checkpoint_namespace(configurable)
        checkpoint_id = _required_text(
            configurable.get("checkpoint_id"),
            label="LangGraph pending-write checkpoint id",
        )
        _validate_bounded_text(
            checkpoint_id,
            label="LangGraph pending-write checkpoint id",
            maximum_length=_MAX_CHECKPOINT_ID_LENGTH,
        )
        _validate_bounded_text(
            task_id,
            label="LangGraph task id",
            maximum_length=_MAX_TASK_ID_LENGTH,
        )
        _validate_bounded_text(
            task_path,
            label="LangGraph task path",
            maximum_length=_MAX_TASK_PATH_LENGTH,
            allow_empty=True,
        )

        for index, (channel, value) in enumerate(writes):
            _validate_bounded_text(
                channel,
                label="LangGraph write channel",
                maximum_length=_MAX_CHANNEL_LENGTH,
            )
            write_index = WRITES_IDX_MAP.get(channel, index)
            value_type, value_blob = self.serde.dumps_typed(value)
            await self._store.put_write(
                StoredLangGraphWrite(
                    run_id=self._run_id,
                    project_id=self._project_id,
                    owner_user_id=self._owner_user_id,
                    checkpoint_namespace=namespace,
                    checkpoint_id=checkpoint_id,
                    task_id=task_id,
                    write_index=write_index,
                    task_path=task_path,
                    channel=channel,
                    value_type=value_type,
                    value_blob=value_blob,
                ),
                replace_existing=write_index < 0,
            )

    async def adelete_thread(self, thread_id: str) -> None:
        self._validate_thread_id(thread_id)
        await self._store.delete_run(
            run_id=self._run_id,
            project_id=self._project_id,
            owner_user_id=self._owner_user_id,
        )

    def _validated_configurable(self, config: RunnableConfig) -> Mapping[str, Any]:
        configurable = config.get("configurable")
        if not isinstance(configurable, Mapping):
            raise ValueError("LangGraph checkpoint config requires configurable values")
        self._validate_thread_id(_required_text(configurable.get("thread_id"), label="thread id"))
        return configurable

    def _validate_thread_id(self, thread_id: str) -> None:
        if thread_id != str(self._run_id):
            raise ValueError("LangGraph thread id does not match the bound workflow run")


def reconcile_checkpoint_with_authoritative_run(
    checkpoint: Checkpoint,
    *,
    authoritative_run: WorkflowRun,
) -> Checkpoint:
    """Overlay only checkpoint-sequence persistence metadata on a matching graph run."""
    channel_values = checkpoint.get("channel_values")
    if not isinstance(channel_values, dict):
        raise ValueError("LangGraph checkpoint channel values are invalid")
    graph_run = channel_values.get("run")
    if not isinstance(graph_run, WorkflowRun):
        raise ValueError("LangGraph checkpoint does not contain a typed workflow run")
    if (
        graph_run.id != authoritative_run.id
        or graph_run.project_id != authoritative_run.project_id
        or graph_run.owner_user_id != authoritative_run.owner_user_id
    ):
        raise ValueError("LangGraph checkpoint run does not match application scope")

    if graph_run != authoritative_run:
        if authoritative_run.checkpoint_sequence != graph_run.checkpoint_sequence + 1:
            raise ValueError("application and LangGraph checkpoint sequences are incompatible")
        if (
            replace(
                authoritative_run,
                checkpoint_sequence=graph_run.checkpoint_sequence,
            )
            != graph_run
        ):
            raise ValueError("application and LangGraph workflow states are inconsistent")

    return cast(
        Checkpoint,
        {
            **checkpoint,
            "channel_values": {
                **channel_values,
                "run": authoritative_run,
            },
        },
    )


def _checkpoint_config(
    run_id: UUID,
    namespace: str,
    checkpoint_id: str,
) -> RunnableConfig:
    return {
        "configurable": {
            "thread_id": str(run_id),
            "checkpoint_ns": namespace,
            "checkpoint_id": checkpoint_id,
        }
    }


def _checkpoint_namespace(configurable: Mapping[str, Any]) -> str:
    value = configurable.get("checkpoint_ns", "")
    if not isinstance(value, str):
        raise ValueError("LangGraph checkpoint namespace must be a string")
    _validate_bounded_text(
        value,
        label="LangGraph checkpoint namespace",
        maximum_length=_MAX_CHECKPOINT_NAMESPACE_LENGTH,
        allow_empty=True,
    )
    return value


def _required_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("optional LangGraph identifier must be a non-empty string")
    return value


def _validate_bounded_text(
    value: str,
    *,
    label: str,
    maximum_length: int,
    allow_empty: bool = False,
) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    if not allow_empty and not value:
        raise ValueError(f"{label} must not be empty")
    if len(value) > maximum_length:
        raise ValueError(f"{label} exceeds its maximum length")
    if value != value.strip():
        raise ValueError(f"{label} must be normalized")


def _validate_serialized_value(value_type: str, value_blob: bytes, *, label: str) -> None:
    _validate_bounded_text(
        value_type,
        label=f"{label} type",
        maximum_length=64,
    )
    if not isinstance(value_blob, bytes):
        raise ValueError(f"{label} blob must be bytes")


def _checkpoint_record_to_stored(
    record: LangGraphCheckpointRecord,
) -> StoredLangGraphCheckpoint:
    return StoredLangGraphCheckpoint(
        run_id=record.run_id,
        project_id=record.project_id,
        owner_user_id=record.owner_user_id,
        checkpoint_namespace=record.checkpoint_namespace,
        checkpoint_id=record.checkpoint_id,
        parent_checkpoint_id=record.parent_checkpoint_id,
        checkpoint_type=record.checkpoint_type,
        checkpoint_blob=record.checkpoint_blob,
        metadata_type=record.metadata_type,
        metadata_blob=record.metadata_blob,
    )


def _stored_checkpoint_to_record(
    checkpoint: StoredLangGraphCheckpoint,
) -> LangGraphCheckpointRecord:
    return LangGraphCheckpointRecord(
        run_id=checkpoint.run_id,
        project_id=checkpoint.project_id,
        owner_user_id=checkpoint.owner_user_id,
        checkpoint_namespace=checkpoint.checkpoint_namespace,
        checkpoint_id=checkpoint.checkpoint_id,
        parent_checkpoint_id=checkpoint.parent_checkpoint_id,
        checkpoint_type=checkpoint.checkpoint_type,
        checkpoint_blob=checkpoint.checkpoint_blob,
        metadata_type=checkpoint.metadata_type,
        metadata_blob=checkpoint.metadata_blob,
    )


def _write_record_to_stored(record: LangGraphWriteRecord) -> StoredLangGraphWrite:
    return StoredLangGraphWrite(
        run_id=record.run_id,
        project_id=record.project_id,
        owner_user_id=record.owner_user_id,
        checkpoint_namespace=record.checkpoint_namespace,
        checkpoint_id=record.checkpoint_id,
        task_id=record.task_id,
        write_index=record.write_index,
        task_path=record.task_path,
        channel=record.channel,
        value_type=record.value_type,
        value_blob=record.value_blob,
    )


def _stored_write_to_record(write: StoredLangGraphWrite) -> LangGraphWriteRecord:
    return LangGraphWriteRecord(
        run_id=write.run_id,
        project_id=write.project_id,
        owner_user_id=write.owner_user_id,
        checkpoint_namespace=write.checkpoint_namespace,
        checkpoint_id=write.checkpoint_id,
        task_id=write.task_id,
        write_index=write.write_index,
        task_path=write.task_path,
        channel=write.channel,
        value_type=write.value_type,
        value_blob=write.value_blob,
    )
