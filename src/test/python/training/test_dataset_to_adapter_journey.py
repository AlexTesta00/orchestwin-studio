"""Credential-free reproducibility journey from dataset to blinded adapter evidence."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from orchestwin.evaluation.ablation_fixtures import (
    AblationCondition,
    create_blinded_ablation_pair,
    create_model_ablation_output,
    freeze_ablation_fixture,
    freeze_ablation_fixture_set,
)
from orchestwin.models.adapter_policy import (
    ExactIdentityStructuredGateway,
    StructuredGenerationRoute,
)
from orchestwin.models.fake_structured import (
    FakeDeterministicStructuredAdapter,
    create_fake_success_fixture,
)
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationProviderKind,
    StructuredGenerationStatus,
    create_structured_generation_request,
    create_structured_json_schema,
)
from orchestwin.projects.requirements_primitives import canonical_json
from orchestwin.training.adapter_artifacts import (
    AdapterRegistrationStatus,
    ContentAddressedAdapterRegistry,
    create_adapter_artifact_manifest,
    inspect_adapter_directory,
)
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
from orchestwin.training.qlora_configurations import (
    LoraBiasMode,
    QloraCheckpointPolicy,
    QloraComputeDtype,
    QloraOptimizationConfiguration,
    QloraOptimizer,
    QloraPrecision,
    QloraQuantizationConfiguration,
    QloraQuantizationType,
    QloraScheduler,
    create_lora_adapter_configuration,
    create_qlora_training_configuration,
)
from orchestwin.training.splitting import (
    DatasetSplit,
    default_dataset_split_policy,
    split_dataset_examples,
)
from orchestwin.training.training_run_persistence import (
    InMemoryTrainingRunRepository,
    TrainingRunStoreStatus,
)
from orchestwin.training.unsloth_adapter import (
    QloraTrainingStatus,
    UnslothProcessInvocation,
    UnslothProcessResult,
    UnslothQloraTrainingAdapter,
    UnslothTrainingRequest,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000131001")
DATASET_ID = UUID("00000000-0000-4000-8000-000000131002")
QUALITY_REPORT_ID = UUID("00000000-0000-4000-8000-000000131003")
CONFIGURATION_ID = UUID("00000000-0000-4000-8000-000000131004")
TRAINING_RUN_ID = UUID("00000000-0000-4000-8000-000000131005")
ADAPTER_ID = UUID("00000000-0000-4000-8000-000000131006")
FIXTURE_SET_ID = UUID("00000000-0000-4000-8000-000000131007")
PAIR_ID = UUID("00000000-0000-4000-8000-000000131008")
BUILT_AT = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)


def _build_dataset(
    example_factory: Callable[..., EvaluatorDatasetExample],
):
    examples = (
        example_factory(
            example_id="UTE-001301",
            language=DatasetLanguage.ENGLISH,
        ),
        example_factory(
            example_id="UTE-001302",
            language=DatasetLanguage.ITALIAN,
            project_brief_summary=(
                "Una piccola interfaccia supporta un compito operativo urgente."
            ),
            scenario=("Un coordinatore corregge una scadenza non valida durante un turno intenso."),
            target_task="Correggere la validazione senza perdere i dati inseriti.",
            overall_summary="L'artefatto crea un attrito recuperabile ma importante.",
        ),
    )
    filtering = filter_dataset_candidates(
        tuple(
            DatasetCandidate(
                candidate_id=f"journey-candidate-{index}",
                example=example,
                generation_request_hash=None,
                producer_ref="dataset-to-adapter-journey-v1",
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
            policy_id="dataset-to-adapter-journey",
            version_number=1,
            seed=3407,
            required_languages=(DatasetLanguage.ENGLISH, DatasetLanguage.ITALIAN),
            minimum_examples_per_language=1,
            maximum_examples=20,
        ),
        examples=active,
        created_at=BUILT_AT,
    )
    quality = create_dataset_quality_report(
        report_id=QUALITY_REPORT_ID,
        manifest=manifest,
        filtering=filtering,
        deduplication=deduplication,
        split=split,
        created_at=BUILT_AT,
    )
    return active, manifest, quality


def _configuration(manifest):
    return create_qlora_training_configuration(
        configuration_id=CONFIGURATION_ID,
        candidate_id="selected-small-instruct",
        base_model_repository="example/selected-small-instruct",
        base_model_revision="a" * 40,
        tokenizer_repository="example/selected-small-instruct",
        tokenizer_revision="b" * 40,
        dataset_reference=manifest.reference,
        quantization=QloraQuantizationConfiguration(
            quantization_type=QloraQuantizationType.NF4,
            compute_dtype=QloraComputeDtype.BFLOAT16,
            double_quantization=True,
        ),
        adapter=create_lora_adapter_configuration(
            rank=16,
            alpha=32,
            dropout=0.0,
            target_modules=("q_proj", "k_proj", "v_proj"),
            bias=LoraBiasMode.NONE,
            use_rslora=False,
        ),
        optimization=QloraOptimizationConfiguration(
            max_sequence_length=2048,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=16,
            learning_rate=0.0002,
            weight_decay=0.01,
            warmup_ratio=0.03,
            max_steps=20,
            num_train_epochs=None,
            optimizer=QloraOptimizer.ADAMW_8BIT,
            scheduler=QloraScheduler.LINEAR,
            precision=QloraPrecision.BF16,
            gradient_checkpointing=True,
            gradient_clip_norm=1.0,
            logging_steps=1,
        ),
        checkpoints=QloraCheckpointPolicy(
            save_steps=10,
            evaluation_steps=5,
            save_total_limit=2,
            load_best_model_at_end=True,
            metric_for_best_model="eval_loss",
            greater_is_better=False,
            early_stopping_patience=2,
        ),
        seed=3407,
        created_at=BUILT_AT,
    )


def _write_dataset_inputs(root: Path, examples: tuple[EvaluatorDatasetExample, ...]) -> None:
    dataset_directory = root / "datasets"
    dataset_directory.mkdir(parents=True)
    ordered = tuple(sorted(examples, key=lambda item: item.example_id))
    train_content = "".join(f"{canonical_json(example.to_snapshot())}\n" for example in ordered)
    validation_content = f"{canonical_json(ordered[-1].to_snapshot())}\n"
    (dataset_directory / "train.jsonl").write_text(train_content, encoding="utf-8")
    (dataset_directory / "validation.jsonl").write_text(
        validation_content,
        encoding="utf-8",
    )


@dataclass
class _SuccessfulTrainingProcess:
    """Create deterministic local adapter bytes instead of invoking a GPU runtime."""

    async def run(self, invocation: UnslothProcessInvocation) -> UnslothProcessResult:
        request_index = invocation.arguments.index("--request") + 1
        result_index = invocation.arguments.index("--result") + 1
        request_path = Path(invocation.arguments[request_index])
        result_path = Path(invocation.arguments[result_index])
        request_payload = json.loads(request_path.read_text(encoding="utf-8"))

        adapter_directory = result_path.parent / "outputs" / "adapter"
        adapter_directory.mkdir(parents=True)
        (adapter_directory / "adapter_config.json").write_text(
            canonical_json(
                {
                    "base_model_name_or_path": request_payload["configuration"][
                        "base_model_repository"
                    ],
                    "peft_type": "LORA",
                    "r": 16,
                }
            ),
            encoding="utf-8",
        )
        (adapter_directory / "adapter_model.safetensors").write_bytes(
            b"orchestwin-deterministic-adapter-fixture-v1"
        )
        _, adapter_sha256 = inspect_adapter_directory(adapter_directory)
        result_path.write_text(
            canonical_json(
                {
                    "request_sha256": request_payload["request_sha256"],
                    "status": "SUCCEEDED",
                    "started_at": BUILT_AT.isoformat(),
                    "completed_at": BUILT_AT.replace(minute=2).isoformat(),
                    "duration_milliseconds": 120_000,
                    "peak_gpu_memory_mb": 6_400,
                    "metrics": [
                        {"name": "eval_loss", "value": 0.41, "step": 20},
                        {"name": "train_loss", "value": 0.37, "step": 20},
                    ],
                    "checkpoints": [],
                    "adapter_relative_path": "outputs/adapter",
                    "adapter_sha256": adapter_sha256,
                    "failure_kind": None,
                    "failure_message": None,
                }
            ),
            encoding="utf-8",
        )
        return UnslothProcessResult(
            exit_code=0,
            stdout="deterministic smoke training completed",
            stderr="",
            duration_milliseconds=120_000,
            timed_out=False,
            interrupted=False,
        )


def _schema():
    return create_structured_json_schema(
        schema_id="orchestwin-user-twin-evaluation",
        version_number=1,
        schema_payload={
            "type": "object",
            "required": ["overall_summary", "findings", "evidence_gaps", "abstained"],
        },
    )


def _identity(*, configuration, adapter_manifest=None) -> ModelRuntimeIdentity:
    return ModelRuntimeIdentity(
        provider_id="local-openai",
        runtime_id="local-evaluator-v1",
        base_model_repository=configuration.base_model_repository,
        base_model_revision=configuration.base_model_revision,
        tokenizer_revision=configuration.tokenizer_revision,
        configuration_sha256=configuration.content_hash,
        adapter_id=(None if adapter_manifest is None else str(adapter_manifest.adapter_id)),
        adapter_sha256=(None if adapter_manifest is None else adapter_manifest.adapter_sha256),
    )


def _generation_request(*, request_id: UUID, fixture, identity):
    return create_structured_generation_request(
        request_id=request_id,
        task_id="dataset-to-adapter-ablation",
        expected_identity=identity,
        output_schema=fixture.output_schema,
        system_instruction=(
            "Return simulated User Twin feedback using only the supplied evidence."
        ),
        input_payload=json.loads(fixture.input_payload_json),
        allowed_evidence_refs=fixture.allowed_evidence_refs,
        prompt_version_ref=fixture.prompt_version_ref,
        temperature=0.0,
        max_output_tokens=512,
        timeout_seconds=60,
    )


def test_dataset_to_adapter_journey_preserves_exact_reproducibility_identity(
    tmp_path: Path,
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    examples, manifest, quality = _build_dataset(example_factory)
    repeated_examples, repeated_manifest, repeated_quality = _build_dataset(example_factory)
    assert examples == repeated_examples
    assert manifest == repeated_manifest
    assert quality == repeated_quality
    assert quality.publishable is True

    dataset_repository = InMemoryTrainingDatasetRepository(owner_user_id=OWNER_ID)
    dataset_created = asyncio.run(dataset_repository.append(manifest, quality))
    assert dataset_created.status is TrainingDatasetStoreStatus.CREATED

    configuration = _configuration(manifest)
    input_root = tmp_path / "inputs"
    _write_dataset_inputs(input_root, examples)
    environment = tmp_path / "environment"
    environment.mkdir()
    (environment / "run_qlora.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    request = UnslothTrainingRequest(
        run_id=TRAINING_RUN_ID,
        owner_user_id=OWNER_ID,
        configuration=configuration,
        train_dataset_path="datasets/train.jsonl",
        validation_dataset_path="datasets/validation.jsonl",
        output_directory="outputs",
        package_lock_sha256="c" * 64,
        environment_sha256="d" * 64,
        requested_at=BUILT_AT,
    )
    workspace_root = tmp_path / "workspaces"
    trainer = UnslothQloraTrainingAdapter(
        process_port=_SuccessfulTrainingProcess(),
        training_environment_directory=environment,
        input_artifact_root=input_root,
        workspace_root=workspace_root,
        timeout_seconds=600,
    )

    outcome = asyncio.run(trainer.train(request))
    assert outcome.status is QloraTrainingStatus.SUCCEEDED
    assert outcome.dataset_reference == manifest.reference
    assert outcome.configuration_sha256 == configuration.content_hash

    training_repository = InMemoryTrainingRunRepository(
        owner_user_id=OWNER_ID,
        dataset_references=frozenset(
            {
                (
                    manifest.dataset_id,
                    manifest.version_number,
                    manifest.content_hash,
                )
            }
        ),
    )
    stored_result = asyncio.run(training_repository.append(outcome))
    assert stored_result.status is TrainingRunStoreStatus.APPENDED
    assert stored_result.training_run is not None
    assert stored_result.training_run.adapter_sha256 == outcome.adapter_sha256

    source_adapter = workspace_root / str(TRAINING_RUN_ID) / "outputs" / "adapter"
    adapter_files, adapter_sha256 = inspect_adapter_directory(source_adapter)
    adapter_manifest = create_adapter_artifact_manifest(
        adapter_id=ADAPTER_ID,
        outcome=outcome,
        configuration=configuration,
        license_spdx="Apache-2.0",
        files=adapter_files,
        adapter_sha256=adapter_sha256,
        created_at=BUILT_AT.replace(minute=3),
    )
    registry = ContentAddressedAdapterRegistry(tmp_path / "adapter-registry")
    registration = registry.register(
        source_directory=source_adapter,
        manifest=adapter_manifest,
    )
    assert registration.status is AdapterRegistrationStatus.REGISTERED
    assert (
        registry.get_owned(
            owner_user_id=OWNER_ID,
            adapter_id=ADAPTER_ID,
        )
        == adapter_manifest
    )

    held_out = example_factory(
        example_id="UTE-001399",
        project_id=UUID("00000000-0000-4000-8000-000000131099"),
        scenario_family_id="held-out-accessibility-recovery",
        use_restriction=DatasetUseRestriction.EXTERNAL_EXPERT_SAMPLE,
    )
    fixture = freeze_ablation_fixture(
        fixture_id="ABL-0131",
        example=held_out,
        output_schema=_schema(),
        prompt_version_ref="ut-eval-v5",
    )
    training_family_keys = tuple(
        sorted({f"{example.project_id}:{example.scenario_family_id}" for example in examples})
    )
    fixture_set = freeze_ablation_fixture_set(
        fixture_set_id=FIXTURE_SET_ID,
        version_number=1,
        seed=3407,
        fixtures=(fixture,),
        training_example_hashes=(example.content_hash for example in examples),
        training_family_keys=training_family_keys,
        frozen_at=BUILT_AT.replace(minute=4),
    )
    assert fixture_set.fixtures == (fixture,)

    base_identity = _identity(configuration=configuration)
    adapter_identity = _identity(
        configuration=configuration,
        adapter_manifest=adapter_manifest,
    )
    base_request = _generation_request(
        request_id=UUID("00000000-0000-4000-8000-000000131010"),
        fixture=fixture,
        identity=base_identity,
    )
    adapter_request = _generation_request(
        request_id=UUID("00000000-0000-4000-8000-000000131011"),
        fixture=fixture,
        identity=adapter_identity,
    )
    base_payload = {
        "overall_summary": "Base-model simulated feedback.",
        "findings": [],
        "evidence_gaps": ["Target-user validation is unavailable."],
        "abstained": True,
    }
    adapter_payload = {
        "overall_summary": "Adapter simulated feedback with explicit uncertainty.",
        "findings": [],
        "evidence_gaps": ["Target-user validation is unavailable."],
        "abstained": True,
    }
    gateway = ExactIdentityStructuredGateway(
        routes=(
            StructuredGenerationRoute(
                identity=base_identity,
                provider_kind=StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
                port=FakeDeterministicStructuredAdapter(
                    identity=base_identity,
                    fixtures=(
                        create_fake_success_fixture(
                            task_id=base_request.task_id,
                            payload=base_payload,
                            expected_request_hash=base_request.content_hash,
                        ),
                    ),
                ),
            ),
            StructuredGenerationRoute(
                identity=adapter_identity,
                provider_kind=StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
                port=FakeDeterministicStructuredAdapter(
                    identity=adapter_identity,
                    fixtures=(
                        create_fake_success_fixture(
                            task_id=adapter_request.task_id,
                            payload=adapter_payload,
                            expected_request_hash=adapter_request.content_hash,
                        ),
                    ),
                ),
            ),
        )
    )
    base_result = asyncio.run(gateway.generate(base_request))
    adapter_result = asyncio.run(gateway.generate(adapter_request))
    assert base_result.status is StructuredGenerationStatus.SUCCEEDED
    assert adapter_result.status is StructuredGenerationStatus.SUCCEEDED
    assert adapter_result.success is not None
    assert adapter_result.success.actual_identity.adapter_sha256 == adapter_sha256

    base_output = create_model_ablation_output(
        fixture=fixture,
        condition=AblationCondition.BASE,
        result=base_result,
    )
    adapted_output = create_model_ablation_output(
        fixture=fixture,
        condition=AblationCondition.ADAPTER,
        result=adapter_result,
    )
    pair, assignment = create_blinded_ablation_pair(
        pair_id=PAIR_ID,
        fixture=fixture,
        base_output=base_output,
        adapter_output=adapted_output,
        seed=3407,
    )
    assert "condition" not in json.dumps(pair.to_public_snapshot())
    assert assignment.adapter_identity_hash == adapter_identity.content_hash
    assert adapter_manifest.dataset_reference == manifest.reference
    assert adapter_manifest.training_configuration_sha256 == configuration.content_hash
