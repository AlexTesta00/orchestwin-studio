"""Tests for versioned deterministic dataset manifests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.training.dataset_examples import DatasetLanguage, EvaluatorDatasetExample
from orchestwin.training.dataset_manifests import (
    DatasetBuildPolicy,
    build_dataset_manifest,
)

DATASET_ID = UUID("00000000-0000-4000-8000-000000113001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000113002")
BUILT_AT = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)


def _policy(**overrides: object) -> DatasetBuildPolicy:
    values: dict[str, object] = {
        "policy_id": "evaluator-dataset-v1",
        "version_number": 1,
        "seed": 20261013,
        "required_languages": (DatasetLanguage.ENGLISH, DatasetLanguage.ITALIAN),
        "minimum_examples_per_language": 1,
        "maximum_examples": 100,
    }
    values.update(overrides)
    return DatasetBuildPolicy(**values)  # type: ignore[arg-type]


def _examples(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> tuple[EvaluatorDatasetExample, ...]:
    return (
        example_factory(example_id="UTE-000001", language=DatasetLanguage.ENGLISH),
        example_factory(
            example_id="UTE-000002",
            language=DatasetLanguage.ITALIAN,
            project_brief_summary="Una piccola interfaccia supporta un compito operativo urgente.",
            scenario="Un coordinatore corregge una scadenza non valida durante un turno intenso.",
            target_task="Correggere la validazione senza perdere i dati inseriti.",
            overall_summary="L'artefatto crea un attrito recuperabile ma importante.",
        ),
    )


def test_manifest_is_canonical_and_reproducible_across_input_order(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    examples = _examples(example_factory)
    first = build_dataset_manifest(
        dataset_id=DATASET_ID,
        owner_user_id=OWNER_ID,
        version_number=1,
        based_on=None,
        policy=_policy(),
        examples=examples,
        created_at=BUILT_AT,
    )
    second = build_dataset_manifest(
        dataset_id=DATASET_ID,
        owner_user_id=OWNER_ID,
        version_number=1,
        based_on=None,
        policy=_policy(),
        examples=reversed(examples),
        created_at=BUILT_AT.replace(hour=10),
    )

    assert [entry.example_id for entry in first.entries] == ["UTE-000001", "UTE-000002"]
    assert first.examples_digest == second.examples_digest
    assert first.content_hash == second.content_hash
    assert first.to_snapshot()["created_at"] != second.to_snapshot()["created_at"]


def test_manifest_identity_changes_when_versioned_policy_changes(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    examples = _examples(example_factory)
    first = build_dataset_manifest(
        dataset_id=DATASET_ID,
        owner_user_id=OWNER_ID,
        version_number=1,
        based_on=None,
        policy=_policy(),
        examples=examples,
        created_at=BUILT_AT,
    )
    second = build_dataset_manifest(
        dataset_id=DATASET_ID,
        owner_user_id=OWNER_ID,
        version_number=1,
        based_on=None,
        policy=_policy(version_number=2, seed=20261014),
        examples=examples,
        created_at=BUILT_AT,
    )

    assert first.policy.content_hash != second.policy.content_hash
    assert first.content_hash != second.content_hash


def test_manifest_rejects_duplicate_ids_missing_language_coverage_and_bad_lineage(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    english = example_factory(example_id="UTE-000001", language=DatasetLanguage.ENGLISH)

    with pytest.raises(ValueError, match="example IDs must be unique"):
        build_dataset_manifest(
            dataset_id=DATASET_ID,
            owner_user_id=OWNER_ID,
            version_number=1,
            based_on=None,
            policy=replace(_policy(), required_languages=(DatasetLanguage.ENGLISH,)),
            examples=(english, english),
            created_at=BUILT_AT,
        )

    with pytest.raises(ValueError, match="language coverage"):
        build_dataset_manifest(
            dataset_id=DATASET_ID,
            owner_user_id=OWNER_ID,
            version_number=1,
            based_on=None,
            policy=_policy(),
            examples=(english,),
            created_at=BUILT_AT,
        )

    first = build_dataset_manifest(
        dataset_id=DATASET_ID,
        owner_user_id=OWNER_ID,
        version_number=1,
        based_on=None,
        policy=replace(_policy(), required_languages=(DatasetLanguage.ENGLISH,)),
        examples=(english,),
        created_at=BUILT_AT,
    )
    with pytest.raises(ValueError, match="preceding version"):
        build_dataset_manifest(
            dataset_id=DATASET_ID,
            owner_user_id=OWNER_ID,
            version_number=3,
            based_on=first.reference,
            policy=replace(_policy(), required_languages=(DatasetLanguage.ENGLISH,)),
            examples=(english,),
            created_at=BUILT_AT,
        )
