"""Reproducible end-to-end journey for the evaluator dataset foundation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from orchestwin.evaluation.findings import SyntheticFinding
from orchestwin.training.dataset_examples import (
    DatasetLanguage,
    DatasetUseRestriction,
    EvaluatorDatasetExample,
)
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
    TrainingDatasetStoreStatus,
    create_dataset_quality_report,
)
from orchestwin.training.splitting import (
    DatasetSplit,
    default_dataset_split_policy,
    split_dataset_examples,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000110901")
DATASET_ID = UUID("00000000-0000-4000-8000-000000110902")
REPORT_ID = UUID("00000000-0000-4000-8000-000000110903")
BUILT_AT = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def _run_build(
    candidates: Iterable[DatasetCandidate],
):
    filtering_policy = replace(
        default_dataset_filtering_policy(),
        reject_reserved_examples=False,
    )
    filtering = filter_dataset_candidates(candidates, policy=filtering_policy)
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
        if assignment.split is not DatasetSplit.EXCLUDED
    )
    manifest = build_dataset_manifest(
        dataset_id=DATASET_ID,
        owner_user_id=OWNER_ID,
        version_number=1,
        based_on=None,
        policy=DatasetBuildPolicy(
            policy_id="reproducible-evaluator-dataset",
            version_number=1,
            seed=20261013,
            required_languages=(DatasetLanguage.ENGLISH, DatasetLanguage.ITALIAN),
            minimum_examples_per_language=1,
            maximum_examples=100,
        ),
        examples=active,
        created_at=BUILT_AT,
    )
    quality = create_dataset_quality_report(
        report_id=REPORT_ID,
        manifest=manifest,
        filtering=filtering,
        deduplication=deduplication,
        split=split,
        created_at=BUILT_AT,
    )
    return filtering, deduplication, split, manifest, quality


def test_dataset_build_is_reproducible_and_preserves_every_quality_decision(
    example_factory: Callable[..., EvaluatorDatasetExample],
    finding_factory: Callable[..., SyntheticFinding],
) -> None:
    english = example_factory(example_id="UTE-000901", language=DatasetLanguage.ENGLISH)
    exact_duplicate = example_factory(
        example_id="UTE-000902",
        language=DatasetLanguage.ENGLISH,
    )
    italian = example_factory(
        example_id="UTE-000903",
        language=DatasetLanguage.ITALIAN,
        project_brief_summary="Una piccola interfaccia supporta un compito operativo urgente.",
        scenario="Un coordinatore corregge una scadenza non valida durante un turno intenso.",
        target_task="Correggere la validazione senza perdere i dati inseriti.",
        overall_summary="L'artefatto crea un attrito recuperabile ma importante.",
    )
    reserved = example_factory(
        example_id="UTE-000904",
        scenario_family_id="formal-case-reserved-family",
        use_restriction=DatasetUseRestriction.FORMAL_CASE_STUDY,
        scenario="A formally reserved case artifact remains outside all training partitions.",
        target_task="Preserve the external evaluation boundary.",
        overall_summary="This sample is tracked but excluded from training.",
    )
    invalid = example_factory(
        example_id="UTE-000905",
        findings=(finding_factory(evidence_refs=("unknown-evidence",)),),
    )
    candidates = tuple(
        DatasetCandidate(
            candidate_id=f"candidate-{index:03d}",
            example=example,
            generation_request_hash=None,
            producer_ref="journey-fixture-v1",
        )
        for index, example in enumerate(
            (english, exact_duplicate, italian, reserved, invalid),
            start=1,
        )
    )

    first = _run_build(candidates)
    second = _run_build(reversed(candidates))

    assert first == second
    filtering, deduplication, split, manifest, quality = first
    assert len(filtering.decisions) == 5
    assert len(filtering.accepted) == 4
    assert len(filtering.rejected) == 1
    assert len(deduplication.duplicates) == 1
    assert len(split.examples_for(DatasetSplit.EXCLUDED)) == 1
    assert split.publishable is True
    assert [entry.example_id for entry in manifest.entries] == [
        "UTE-000901",
        "UTE-000903",
    ]
    assert quality.candidate_count == 5
    assert quality.accepted_count == 4
    assert quality.duplicate_count == 1
    assert quality.excluded_count == 1
    assert quality.leakage_issue_count == 0
    assert quality.publishable is True

    repository = InMemoryTrainingDatasetRepository(owner_user_id=OWNER_ID)
    created = asyncio.run(repository.append(manifest, quality))
    repeated = asyncio.run(repository.append(manifest, quality))

    assert created.status is TrainingDatasetStoreStatus.CREATED
    assert repeated.status is TrainingDatasetStoreStatus.ALREADY_PRESENT
    assert created.dataset == repeated.dataset
