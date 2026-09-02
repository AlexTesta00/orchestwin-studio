"""PostgreSQL integration journey for immutable evaluator dataset metadata."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError

from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.persistence.migrate import create_alembic_config
from orchestwin.training.dataset_examples import (
    DatasetArtifactSnapshot,
    DatasetEvidenceKind,
    DatasetEvidenceReference,
    DatasetExampleSourceKind,
    DatasetLanguage,
    DatasetUseRestriction,
    DatasetUserTwinReference,
    DatasetVersionedArtifactReference,
    create_evaluator_dataset_example,
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
    SqlAlchemyTrainingDatasetRepository,
    TrainingDatasetStoreStatus,
    TrainingDatasetVersionRecord,
    create_dataset_quality_report,
)
from orchestwin.training.splitting import (
    DatasetSplit,
    default_dataset_split_policy,
    split_dataset_examples,
)
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

pytestmark = pytest.mark.integration

OWNER_ID = UUID("00000000-0000-4000-8000-000000111901")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000111902")
DATASET_ID = UUID("00000000-0000-4000-8000-000000111903")
REPORT_ID = UUID("00000000-0000-4000-8000-000000111904")
BRIEF_ID = UUID("00000000-0000-4000-8000-000000111905")
TWIN_ID = UUID("00000000-0000-4000-8000-000000111906")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000111907")
CREATED_AT = datetime(2026, 10, 13, 12, 30, tzinfo=UTC)


async def _truncate(runtime) -> None:
    async with runtime.engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE training_dataset_quality_reports, "
                "training_dataset_versions, users CASCADE"
            )
        )


def _example(example_id: str, language: DatasetLanguage):
    evidence = (
        DatasetEvidenceReference(
            reference_id="REQ-NFR-012",
            kind=DatasetEvidenceKind.REQUIREMENT,
            source_id="requirements-v4",
            source_version=4,
            content_hash="a" * 64,
            locator="non_functional_requirements[11]",
        ),
        DatasetEvidenceReference(
            reference_id="ut-profile-v3.operational_constraints[0]",
            kind=DatasetEvidenceKind.USER_TWIN_PROFILE,
            source_id=str(TWIN_ID),
            source_version=3,
            content_hash="b" * 64,
            locator="operational_constraints[0]",
        ),
    )
    finding = create_synthetic_finding(
        finding_id="UTF-001",
        twin_id=TWIN_ID,
        twin_version=3,
        artifact_id=ARTIFACT_ID,
        artifact_version=5,
        location="screen:task/field:deadline",
        summary="The recovery instruction is not visible near the invalid field.",
        rationale="The approved profile requires concise guidance during time-sensitive work.",
        criterion=SyntheticFindingCriterion.ACTIONABILITY,
        severity=SyntheticFindingSeverity.MAJOR,
        epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
        evidence_refs=("REQ-NFR-012", "ut-profile-v3.operational_constraints[0]"),
        confidence=0.72,
        recommended_action="Explain the accepted value and retain keyboard focus.",
        requires_human_validation=True,
        model_config_ref="model-policy-v2",
        prompt_version_ref="ut-eval-v4",
    )
    italian = language is DatasetLanguage.ITALIAN
    return create_evaluator_dataset_example(
        example_id=example_id,
        project_id=PROJECT_ID,
        scenario_family_id="generic-operations-time-pressure",
        language=language,
        source_kind=DatasetExampleSourceKind.RESEARCHER_CURATED,
        use_restriction=DatasetUseRestriction.NONE,
        project_brief_reference=DatasetVersionedArtifactReference(
            artifact_id=BRIEF_ID,
            version_number=2,
            content_hash="c" * 64,
        ),
        project_brief_summary=(
            "Una piccola interfaccia supporta un compito operativo urgente."
            if italian
            else "A small operations interface supports a time-sensitive task."
        ),
        user_twin_reference=DatasetUserTwinReference(
            twin_id=TWIN_ID,
            version_number=3,
            content_hash="d" * 64,
            lifecycle_status=UserTwinLifecycleStatus.OWNER_APPROVED_UT,
        ),
        user_twin_profile={
            "name": "Operations coordinator",
            "role": "Coordinates a time-sensitive operational workflow",
            "validation_status": "OWNER_APPROVED_UT",
        },
        scenario=(
            "Un coordinatore corregge una scadenza non valida durante un turno intenso."
            if italian
            else "A coordinator corrects an invalid deadline during a busy shift."
        ),
        target_task=(
            "Correggere la validazione senza perdere i dati inseriti."
            if italian
            else "Recover from validation without losing entered data."
        ),
        artifact=DatasetArtifactSnapshot(
            reference=DatasetVersionedArtifactReference(
                artifact_id=ARTIFACT_ID,
                version_number=5,
                content_hash="e" * 64,
            ),
            media_type="application/vnd.orchestwin.interface-summary+json",
            description="A form shows an error only at the top of the page.",
        ),
        evidence=evidence,
        rubric_id="ut-evaluator-core",
        rubric_version=1,
        rubric_criteria=(
            SyntheticFindingCriterion.ACTIONABILITY,
            SyntheticFindingCriterion.TASK_ALIGNMENT,
        ),
        output_schema_ref="synthetic-finding.schema.json@1",
        overall_summary=(
            "L'artefatto crea un attrito recuperabile ma importante."
            if italian
            else "The artifact creates recoverable but important task friction."
        ),
        findings=(finding,),
        evidence_gaps=(),
        abstained=False,
    )


def _build():
    examples = (
        _example("UTE-001901", DatasetLanguage.ENGLISH),
        _example("UTE-001902", DatasetLanguage.ITALIAN),
    )
    filtering = filter_dataset_candidates(
        tuple(
            DatasetCandidate(
                candidate_id=f"postgres-candidate-{index}",
                example=example,
                generation_request_hash=None,
                producer_ref="postgres-fixture-v1",
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
        if assignment.split is not DatasetSplit.EXCLUDED
    )
    manifest = build_dataset_manifest(
        dataset_id=DATASET_ID,
        owner_user_id=OWNER_ID,
        version_number=1,
        based_on=None,
        policy=DatasetBuildPolicy(
            policy_id="postgres-dataset-build",
            version_number=1,
            seed=20261013,
            required_languages=(DatasetLanguage.ENGLISH, DatasetLanguage.ITALIAN),
            minimum_examples_per_language=1,
            maximum_examples=10,
        ),
        examples=active,
        created_at=CREATED_AT,
    )
    report = create_dataset_quality_report(
        report_id=REPORT_ID,
        manifest=manifest,
        filtering=filtering,
        deduplication=deduplication,
        split=split,
        created_at=CREATED_AT,
    )
    return manifest, report


async def _run_scenario() -> None:
    settings = load_database_settings(env_file=None)
    runtime = create_database_runtime(settings)
    try:
        await _truncate(runtime)
        async with runtime.session_factory.begin() as session:
            session.add(
                UserRecord(
                    id=OWNER_ID,
                    email_normalized="training-owner@example.com",
                    password_hash="integration-test-password-hash",
                    is_active=True,
                )
            )

        manifest, report = _build()
        async with runtime.session_factory.begin() as session:
            repository = SqlAlchemyTrainingDatasetRepository(
                session,
                owner_user_id=OWNER_ID,
            )
            created = await repository.append(manifest, report)
            repeated = await repository.append(manifest, report)
            assert created.status is TrainingDatasetStoreStatus.CREATED
            assert repeated.status is TrainingDatasetStoreStatus.ALREADY_PRESENT

        async with runtime.session_factory() as session:
            repository = SqlAlchemyTrainingDatasetRepository(
                session,
                owner_user_id=OWNER_ID,
            )
            stored = await repository.get_owned(
                dataset_id=DATASET_ID,
                version_number=1,
            )
            assert stored is not None
            assert stored.content_hash == manifest.content_hash
            assert stored.publishable is True

        mutation_rejected = False
        try:
            async with runtime.session_factory.begin() as session:
                await session.execute(
                    update(TrainingDatasetVersionRecord)
                    .where(
                        TrainingDatasetVersionRecord.dataset_id == DATASET_ID,
                        TrainingDatasetVersionRecord.version_number == 1,
                    )
                    .values(content_hash="0" * 64)
                )
        except DBAPIError:
            mutation_rejected = True
        assert mutation_rejected is True

        async with runtime.engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        scripts = ScriptDirectory.from_config(
            create_alembic_config(settings.url.get_secret_value())
        )
        assert revision == scripts.get_current_head()
    finally:
        await _truncate(runtime)
        await runtime.dispose()


def test_postgresql_training_dataset_journey() -> None:
    asyncio.run(_run_scenario(), loop_factory=asyncio.SelectorEventLoop)
