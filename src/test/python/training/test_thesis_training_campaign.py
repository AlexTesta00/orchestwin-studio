"""Final thesis campaign must stay broad, reproducible, leak-free, and epistemically bounded."""

from __future__ import annotations

from itertools import islice

from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingSeverity,
)
from orchestwin.training.dataset_examples import DatasetLanguage
from orchestwin.training.splitting import DatasetSplit
from orchestwin.training.thesis_training_campaign import (
    BASE_MODEL_REPOSITORY,
    BASE_MODEL_REVISION,
    FAMILIES,
    LANGUAGES,
    MINIMUM_INTERNAL_TEST_EXAMPLES,
    MINIMUM_TRAIN_EXAMPLES,
    MINIMUM_VALIDATION_EXAMPLES,
    PROJECT_VARIANT_COUNT,
    TARGET_ABSTENTION_FRACTION,
    TARGET_TOTAL_EXAMPLES,
    build_campaign_dataset,
    campaign_snapshot,
    expected_example_count,
    final_qlora_policy_snapshot,
    iter_campaign_examples,
    selection_decision_snapshot,
    validate_campaign_dataset,
)


def test_selection_chooses_exact_qwen_base_but_rejects_smoke_adapter_as_final():
    decision = selection_decision_snapshot()
    assert decision["status"] == "OWNER_APPROVED_FOR_FINAL_THESIS_TRAINING"
    assert decision["base_model_repository"] == "Qwen/Qwen3-4B-Instruct-2507"
    assert decision["base_model_revision"] == ("abcc171021d4f320b2e7f47c6f0deca67ded870c")
    assert decision["base_selected_for_training"] is True
    assert decision["smoke_adapter_selected_as_final"] is False
    assert decision["smoke_adapter_quality_improvement_claimed"] is False
    assert decision["local_openai_compatible_smoke_serving_observed"] is True
    assert decision["vllm_serving_observed"] is False
    assert decision["redistribution_authorized"] is False
    assert decision["empirical_user_validation_claimed"] is False
    assert decision["evidence_archive_sha256"]["s62_local_serving"] == (
        "1f9da4019246400894b245b8feb17c89bae16ee209439ff42b8595e85ed3ba14"
    )


def test_campaign_is_large_bilingual_and_general_purpose_for_evaluator_role():
    campaign = campaign_snapshot()
    assert expected_example_count() == TARGET_TOTAL_EXAMPLES == 24_000
    assert PROJECT_VARIANT_COUNT == 500
    assert len(FAMILIES) == 24
    assert LANGUAGES == (DatasetLanguage.ENGLISH, DatasetLanguage.ITALIAN)
    assert len(campaign["domains"]) >= 20
    assert len(campaign["roles"]) >= 20
    assert len(campaign["platforms"]) == 4
    assert len(campaign["risks"]) == 8
    assert set(campaign["criteria"]) == {item.value for item in SyntheticFindingCriterion}
    assert set(campaign["severities"]) == {item.value for item in SyntheticFindingSeverity}
    assert campaign["target_abstention_fraction"] == 0.25
    assert "not empirical evidence" in campaign["methodological_notice"]


def test_examples_are_content_addressed_bilingual_and_keep_epistemic_boundary():
    sample = tuple(islice(iter_campaign_examples(), 48))
    assert len(sample) == 48
    assert len({example.example_id for example in sample}) == 48
    assert len({example.content_hash for example in sample}) == 48
    assert {example.language for example in sample} == {
        DatasetLanguage.ENGLISH,
        DatasetLanguage.ITALIAN,
    }
    assert all(example.source_kind.value == "SYNTHETIC_GENERATED" for example in sample)
    assert all(example.generation_ref for example in sample)
    assert all(
        example.user_twin_profile_json.find("DESIGN_HYPOTHESIS_NOT_REAL_USER") >= 0
        for example in sample
    )
    for example in sample:
        if example.expected_output.abstained:
            assert example.expected_output.findings == ()
            assert example.expected_output.evidence_gaps
        else:
            assert len(example.expected_output.findings) == 1
            finding = example.expected_output.findings[0]
            assert finding.requires_human_validation is True
            assert finding.evidence_refs == ("EVID-001", "EVID-002")


def test_full_24k_campaign_is_publishable_and_meets_split_minima():
    examples, split = build_campaign_dataset()
    quality = validate_campaign_dataset(examples, split)

    assert len(examples) == 24_000
    assert split.publishable is True
    assert split.leakage_issues == ()

    train = len(split.examples_for(DatasetSplit.TRAIN))
    validation = len(split.examples_for(DatasetSplit.VALIDATION))
    internal = len(split.examples_for(DatasetSplit.INTERNAL_TEST))
    assert train >= MINIMUM_TRAIN_EXAMPLES
    assert validation >= MINIMUM_VALIDATION_EXAMPLES
    assert internal >= MINIMUM_INTERNAL_TEST_EXAMPLES
    assert train + validation + internal == 24_000

    assert quality["language_counts"] == {"en": 12_000, "it": 12_000}
    assert quality["abstention_fraction"] == TARGET_ABSTENTION_FRACTION
    assert quality["leakage_issue_count"] == 0
    assert quality["publishable"] is True
    assert quality["methodological_status"] == (
        "SYNTHETIC_DESIGN_HYPOTHESES_NOT_EMPIRICAL_USER_DATA"
    )


def test_final_qlora_policy_matches_4060_feasibility_without_authorizing_training():
    policy = final_qlora_policy_snapshot()
    assert policy["base_model_repository"] == BASE_MODEL_REPOSITORY
    assert policy["base_model_revision"] == BASE_MODEL_REVISION
    assert policy["quantization"]["load_in_4bit"] is True
    assert policy["quantization"]["quantization_type"] == "nf4"
    assert policy["lora"]["rank"] == 16
    assert policy["lora"]["alpha"] == 32
    assert policy["optimization"]["max_sequence_length"] == 1536
    assert policy["optimization"]["per_device_train_batch_size"] == 1
    assert policy["optimization"]["gradient_accumulation_steps"] == 4
    assert policy["optimization"]["num_train_epochs"] == 1.0
    assert policy["optimization"]["precision"] == "bf16"
    assert policy["single_gpu_only"] is True
    assert policy["expected_gpu_class"] == "RTX-4060-8GB"
    assert policy["authorization_required_before_training"] is True


def test_materializer_never_enables_training_gate():
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    source = (root / "environments/training/materialize_thesis_dataset.py").read_text(
        encoding="utf-8"
    )
    assert 'TRAINING_GATE = "ORCHESTWIN_FINAL_QLORA_ALLOW_TRAINING"' in source
    assert 'os.environ.get(TRAINING_GATE) == "1"' in source
    assert 'ORCHESTWIN_FINAL_QLORA_ALLOW_TRAINING", "1"' not in source
    assert "training_executed" in source
    assert "training_authorized" in source
