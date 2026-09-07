"""Tests for owner-scoped append-only dataset metadata persistence."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from orchestwin.training.dataset_examples import DatasetLanguage, EvaluatorDatasetExample
from orchestwin.training.dataset_manifests import DatasetBuildPolicy, build_dataset_manifest
from orchestwin.training.deduplication import (
    deduplicate_dataset_examples,
    default_dataset_deduplication_policy,
)
from orchestwin.training.filtering import (
    DatasetCandidate,
    default_dataset_filtering_policy,
    filter_dataset_candidates,
)
from orchestwin.training.persistence import (
    InMemoryTrainingDatasetRepository,
    SqlAlchemyTrainingDatasetRepository,
    TrainingDatasetStoreStatus,
    create_dataset_quality_report,
)
from orchestwin.training.splitting import default_dataset_split_policy, split_dataset_examples

OWNER_ID = UUID("00000000-0000-4000-8000-000000119001")
DATASET_ID = UUID("00000000-0000-4000-8000-000000119002")
REPORT_ID = UUID("00000000-0000-4000-8000-000000119003")
CREATED_AT = datetime(2026, 10, 13, 11, 0, tzinfo=UTC)


class _RecordingNestedTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> bool:
        return False


class _RecordingAsyncSession:
    def __init__(self) -> None:
        self._scalar_results: list[UUID | None] = [OWNER_ID, None]
        self.write_operations: list[tuple[str, str | None]] = []

    async def scalar(self, _statement: object) -> UUID | None:
        return self._scalar_results.pop(0)

    def begin_nested(self) -> _RecordingNestedTransaction:
        return _RecordingNestedTransaction()

    def add(self, record: object) -> None:
        self.write_operations.append(("add", type(record).__name__))

    async def flush(self) -> None:
        self.write_operations.append(("flush", None))


def _build(
    example_factory: Callable[..., EvaluatorDatasetExample],
):
    examples = (
        example_factory(example_id="UTE-000101", language=DatasetLanguage.ENGLISH),
        example_factory(
            example_id="UTE-000102",
            language=DatasetLanguage.ITALIAN,
            project_brief_summary="Una piccola interfaccia supporta un compito operativo urgente.",
            scenario="Un coordinatore corregge una scadenza non valida durante un turno intenso.",
            target_task="Correggere la validazione senza perdere i dati inseriti.",
            overall_summary="L'artefatto crea un attrito recuperabile ma importante.",
        ),
    )
    filtering = filter_dataset_candidates(
        tuple(
            DatasetCandidate(
                candidate_id=f"candidate-{index}",
                example=example,
                generation_request_hash=None,
                producer_ref="researcher-fixture-v1",
            )
            for index, example in enumerate(examples, start=1)
        ),
        policy=default_dataset_filtering_policy(),
    )
    deduplication = deduplicate_dataset_examples(
        filtering.accepted,
        policy=default_dataset_deduplication_policy(),
    )
    split = split_dataset_examples(
        deduplication.kept,
        policy=default_dataset_split_policy(),
    )
    active = tuple(
        assignment.example
        for assignment in split.assignments
        if assignment.split.value != "EXCLUDED"
    )
    manifest = build_dataset_manifest(
        dataset_id=DATASET_ID,
        owner_user_id=OWNER_ID,
        version_number=1,
        based_on=None,
        policy=DatasetBuildPolicy(
            policy_id="test-dataset-build",
            version_number=1,
            seed=20261013,
            required_languages=(DatasetLanguage.ENGLISH, DatasetLanguage.ITALIAN),
            minimum_examples_per_language=1,
            maximum_examples=10,
        ),
        examples=active,
        created_at=CREATED_AT,
    )
    quality = create_dataset_quality_report(
        report_id=REPORT_ID,
        manifest=manifest,
        filtering=filtering,
        deduplication=deduplication,
        split=split,
        created_at=CREATED_AT,
    )
    return manifest, quality


def test_in_memory_repository_is_owner_scoped_idempotent_and_conflict_aware(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    manifest, quality = _build(example_factory)
    repository = InMemoryTrainingDatasetRepository(owner_user_id=OWNER_ID)

    created = asyncio.run(repository.append(manifest, quality))
    repeated = asyncio.run(repository.append(manifest, quality))
    stored = asyncio.run(repository.get_owned(dataset_id=DATASET_ID, version_number=1))

    assert created.status is TrainingDatasetStoreStatus.CREATED
    assert repeated.status is TrainingDatasetStoreStatus.ALREADY_PRESENT
    assert created.dataset == repeated.dataset == stored
    assert stored is not None
    assert stored.publishable is True
    assert stored.example_count == 2


def test_repository_rejects_missing_owner_and_quality_scope_mismatch(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    manifest, quality = _build(example_factory)
    missing_owner = InMemoryTrainingDatasetRepository(
        owner_user_id=OWNER_ID,
        owner_exists=False,
    )
    other_owner = InMemoryTrainingDatasetRepository(
        owner_user_id=UUID("00000000-0000-4000-8000-000000119999")
    )

    assert (
        asyncio.run(missing_owner.append(manifest, quality)).status
        is TrainingDatasetStoreStatus.OWNER_NOT_FOUND
    )
    assert (
        asyncio.run(other_owner.append(manifest, quality)).status
        is TrainingDatasetStoreStatus.QUALITY_REPORT_MISMATCH
    )


def test_sqlalchemy_repository_flushes_dataset_before_quality_report(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    manifest, quality = _build(example_factory)
    session = _RecordingAsyncSession()
    repository = SqlAlchemyTrainingDatasetRepository(
        session,
        owner_user_id=OWNER_ID,
    )

    result = asyncio.run(repository.append(manifest, quality))

    assert result.status is TrainingDatasetStoreStatus.CREATED
    assert session.write_operations == [
        ("add", "TrainingDatasetVersionRecord"),
        ("flush", None),
        ("add", "TrainingDatasetQualityReportRecord"),
        ("flush", None),
    ]
