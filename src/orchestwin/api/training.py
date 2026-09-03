"""Owner-scoped read resources for datasets, training runs, and model adapters."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount
from orchestwin.training.adapter_artifacts import ContentAddressedAdapterRegistry
from orchestwin.training.persistence import (
    TrainingDatasetQualityReportRecord,
    TrainingDatasetVersionRecord,
)
from orchestwin.training.training_run_persistence import SqlAlchemyTrainingRunRepository


class TrainingApiService(Protocol):
    """Read-only application boundary preserving authenticated owner scope."""

    async def datasets(
        self,
        *,
        owner_user_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]: ...

    async def dataset(
        self,
        *,
        owner_user_id: UUID,
        dataset_id: UUID,
        version_number: int,
    ) -> dict[str, JsonValue] | None: ...

    async def training_runs(
        self,
        *,
        owner_user_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]: ...

    async def training_run(
        self,
        *,
        owner_user_id: UUID,
        training_run_id: UUID,
    ) -> dict[str, JsonValue] | None: ...

    async def adapters(
        self,
        *,
        owner_user_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]: ...

    async def adapter(
        self,
        *,
        owner_user_id: UUID,
        adapter_id: UUID,
    ) -> dict[str, JsonValue] | None: ...


class SqlAlchemyTrainingApiService:
    """PostgreSQL and content-addressed registry query adapter."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        adapter_registry: ContentAddressedAdapterRegistry,
    ) -> None:
        self._session_factory = session_factory
        self._adapter_registry = adapter_registry

    async def datasets(
        self,
        *,
        owner_user_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        async with self._session_factory() as session:
            records = (
                await session.scalars(
                    select(TrainingDatasetVersionRecord)
                    .where(TrainingDatasetVersionRecord.owner_user_id == owner_user_id)
                    .order_by(
                        TrainingDatasetVersionRecord.created_at,
                        TrainingDatasetVersionRecord.dataset_id,
                        TrainingDatasetVersionRecord.version_number,
                    )
                )
            ).all()
            reports = (
                await session.scalars(
                    select(TrainingDatasetQualityReportRecord).where(
                        TrainingDatasetQualityReportRecord.owner_user_id == owner_user_id
                    )
                )
            ).all()
        report_by_version = {
            (report.dataset_id, report.dataset_version_number): report for report in reports
        }
        return tuple(
            _dataset_snapshot(
                record,
                report_by_version.get((record.dataset_id, record.version_number)),
            )
            for record in records
        )

    async def dataset(
        self,
        *,
        owner_user_id: UUID,
        dataset_id: UUID,
        version_number: int,
    ) -> dict[str, JsonValue] | None:
        async with self._session_factory() as session:
            record = await session.scalar(
                select(TrainingDatasetVersionRecord).where(
                    TrainingDatasetVersionRecord.dataset_id == dataset_id,
                    TrainingDatasetVersionRecord.version_number == version_number,
                    TrainingDatasetVersionRecord.owner_user_id == owner_user_id,
                )
            )
            if record is None:
                return None
            report = await session.scalar(
                select(TrainingDatasetQualityReportRecord).where(
                    TrainingDatasetQualityReportRecord.dataset_id == dataset_id,
                    TrainingDatasetQualityReportRecord.dataset_version_number == version_number,
                    TrainingDatasetQualityReportRecord.owner_user_id == owner_user_id,
                )
            )
        return _dataset_snapshot(record, report)

    async def training_runs(
        self,
        *,
        owner_user_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        async with self._session_factory() as session:
            repository = SqlAlchemyTrainingRunRepository(
                session,
                owner_user_id=owner_user_id,
            )
            runs = await repository.history()
        return tuple(cast(dict[str, JsonValue], run.to_snapshot()) for run in runs)

    async def training_run(
        self,
        *,
        owner_user_id: UUID,
        training_run_id: UUID,
    ) -> dict[str, JsonValue] | None:
        async with self._session_factory() as session:
            repository = SqlAlchemyTrainingRunRepository(
                session,
                owner_user_id=owner_user_id,
            )
            run = await repository.get_owned(run_id=training_run_id)
        return None if run is None else cast(dict[str, JsonValue], run.to_snapshot())

    async def adapters(
        self,
        *,
        owner_user_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        manifests = await asyncio.to_thread(
            self._adapter_registry.history_for_owner,
            owner_user_id=owner_user_id,
        )
        return tuple(cast(dict[str, JsonValue], item.to_snapshot()) for item in manifests)

    async def adapter(
        self,
        *,
        owner_user_id: UUID,
        adapter_id: UUID,
    ) -> dict[str, JsonValue] | None:
        manifest = await asyncio.to_thread(
            self._adapter_registry.get_owned,
            owner_user_id=owner_user_id,
            adapter_id=adapter_id,
        )
        return (
            None
            if manifest is None
            else cast(
                dict[str, JsonValue],
                manifest.to_snapshot(),
            )
        )


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrainingSnapshotResponse(ApiModel):
    snapshot: dict[str, JsonValue]


class TrainingSnapshotListResponse(ApiModel):
    items: tuple[dict[str, JsonValue], ...]


def training_api_service_dependency(request: Request) -> TrainingApiService:
    service = getattr(request.app.state, "training_api_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "TRAINING_API_SERVICE_UNAVAILABLE"},
        )
    return service


def create_training_router() -> APIRouter:
    """Create authenticated, read-only training and adapter resource routes."""
    router = APIRouter(tags=["training"])

    @router.get(
        "/datasets",
        response_model=TrainingSnapshotListResponse,
        operation_id="listTrainingDatasets",
    )
    async def list_datasets(
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[TrainingApiService, Depends(training_api_service_dependency)],
    ) -> TrainingSnapshotListResponse:
        return TrainingSnapshotListResponse(items=await service.datasets(owner_user_id=user.id))

    @router.get(
        "/datasets/{dataset_id}/versions/{version_number}",
        response_model=TrainingSnapshotResponse,
        operation_id="getTrainingDatasetVersion",
    )
    async def get_dataset(
        dataset_id: UUID,
        version_number: int,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[TrainingApiService, Depends(training_api_service_dependency)],
    ) -> TrainingSnapshotResponse:
        if version_number < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "INVALID_DATASET_VERSION"},
            )
        snapshot = await service.dataset(
            owner_user_id=user.id,
            dataset_id=dataset_id,
            version_number=version_number,
        )
        return TrainingSnapshotResponse(
            snapshot=_required(snapshot, code="TRAINING_DATASET_NOT_FOUND")
        )

    @router.get(
        "/training-runs",
        response_model=TrainingSnapshotListResponse,
        operation_id="listTrainingRuns",
    )
    async def list_training_runs(
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[TrainingApiService, Depends(training_api_service_dependency)],
    ) -> TrainingSnapshotListResponse:
        return TrainingSnapshotListResponse(
            items=await service.training_runs(owner_user_id=user.id)
        )

    @router.get(
        "/training-runs/{training_run_id}",
        response_model=TrainingSnapshotResponse,
        operation_id="getTrainingRun",
    )
    async def get_training_run(
        training_run_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[TrainingApiService, Depends(training_api_service_dependency)],
    ) -> TrainingSnapshotResponse:
        snapshot = await service.training_run(
            owner_user_id=user.id,
            training_run_id=training_run_id,
        )
        return TrainingSnapshotResponse(snapshot=_required(snapshot, code="TRAINING_RUN_NOT_FOUND"))

    @router.get(
        "/model-adapters",
        response_model=TrainingSnapshotListResponse,
        operation_id="listModelAdapters",
    )
    async def list_adapters(
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[TrainingApiService, Depends(training_api_service_dependency)],
    ) -> TrainingSnapshotListResponse:
        return TrainingSnapshotListResponse(items=await service.adapters(owner_user_id=user.id))

    @router.get(
        "/model-adapters/{adapter_id}",
        response_model=TrainingSnapshotResponse,
        operation_id="getModelAdapter",
    )
    async def get_adapter(
        adapter_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[TrainingApiService, Depends(training_api_service_dependency)],
    ) -> TrainingSnapshotResponse:
        snapshot = await service.adapter(
            owner_user_id=user.id,
            adapter_id=adapter_id,
        )
        return TrainingSnapshotResponse(
            snapshot=_required(snapshot, code="MODEL_ADAPTER_NOT_FOUND")
        )

    return router


def _required(
    value: dict[str, JsonValue] | None,
    *,
    code: str,
) -> dict[str, JsonValue]:
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": code},
        )
    return value


def _dataset_snapshot(
    record: TrainingDatasetVersionRecord,
    report: TrainingDatasetQualityReportRecord | None,
) -> dict[str, JsonValue]:
    return {
        "manifest": _json_object(record.manifest_snapshot_json),
        "quality_report": (None if report is None else _json_object(report.report_snapshot_json)),
    }


def _json_object(value: str) -> dict[str, JsonValue]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict) or not all(isinstance(key, str) for key in parsed):
        raise ValueError("stored training snapshot must contain a JSON object")
    return cast(dict[str, JsonValue], parsed)
