"""Final thesis curriculum must match the exact evaluator inference contract."""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import islice
from pathlib import Path

from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
)
from orchestwin.training.benchmarking import _benchmark_system_instruction
from orchestwin.training.dataset_examples import DatasetLanguage
from orchestwin.training.splitting import DatasetSplit
from orchestwin.training.thesis_training_campaign import (
    BASE_MODEL_REPOSITORY,
    BASE_MODEL_REVISION,
    BENCHMARK_RESPONSE_CONTRACT,
    FAMILIES,
    LANGUAGES,
    MINIMUM_INTERNAL_TEST_EXAMPLES,
    MINIMUM_TRAIN_EXAMPLES,
    MINIMUM_VALIDATION_EXAMPLES,
    PROJECT_VARIANT_COUNT,
    SUPERVISION_MODES,
    TARGET_ABSTENTION_FRACTION,
    TARGET_TOTAL_EXAMPLES,
    SupervisionMode,
    benchmark_aligned_system_instruction,
    benchmark_aligned_training_projection,
    build_campaign_dataset,
    campaign_snapshot,
    expected_example_count,
    final_qlora_policy_snapshot,
    iter_campaign_examples,
    selection_decision_snapshot,
    supervision_mode,
    training_projection_contract_snapshot,
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
    assert campaign["supervision_mode_target_fraction"] == 0.25
    assert campaign["supervision_modes"] == [mode.value for mode in SUPERVISION_MODES]
    assert "not empirical evidence" in campaign["methodological_notice"]


def test_supervision_modes_are_orthogonal_to_scenario_family():
    assert tuple(supervision_mode(index) for index in range(1, 5)) == (
        SupervisionMode.GROUNDED_INFERENCE,
        SupervisionMode.USER_PROVIDED,
        SupervisionMode.UNSUPPORTED_HYPOTHESIS,
        SupervisionMode.ABSTAIN,
    )
    examples = tuple(islice(iter_campaign_examples(), 24 * 2 * 8))
    by_family: dict[str, Counter[str]] = defaultdict(Counter)
    for example in examples:
        if example.expected_output.abstained:
            mode = SupervisionMode.ABSTAIN.value
        else:
            status = example.expected_output.findings[0].epistemic_status
            mode = {
                SyntheticFindingEpistemicStatus.MODEL_INFERRED: (
                    SupervisionMode.GROUNDED_INFERENCE.value
                ),
                SyntheticFindingEpistemicStatus.USER_PROVIDED: (
                    SupervisionMode.USER_PROVIDED.value
                ),
                SyntheticFindingEpistemicStatus.UNSUPPORTED_ASSUMPTION: (
                    SupervisionMode.UNSUPPORTED_HYPOTHESIS.value
                ),
            }[status]
        by_family[example.scenario_family_id][mode] += 1
    assert len(by_family) == 24
    assert all(
        set(counts) == {mode.value for mode in SUPERVISION_MODES} for counts in by_family.values()
    )


def test_projection_matches_frozen_model_visible_benchmark_contract():
    examples = tuple(islice(iter_campaign_examples(), 16))
    seen_reference_ids: set[str] = set()
    for example in examples:
        projection = benchmark_aligned_training_projection(example)
        assert projection["system_instruction"] == _benchmark_system_instruction(example.language)
        user = projection["user_payload"]
        assert set(user) == {
            "task_id",
            "input",
            "allowed_evidence_refs",
            "output_schema",
            "response_contract",
        }
        assert user["response_contract"] == list(BENCHMARK_RESPONSE_CONTRACT)
        assert set(user["input"]) == {
            "language",
            "profile_summary",
            "scenario",
            "target_task",
            "artifact_summary",
            "evidence",
            "evaluation_criteria",
            "methodological_notice",
        }
        assert all(set(item) == {"reference_id", "text"} for item in user["input"]["evidence"])
        assert user["allowed_evidence_refs"] == sorted(
            item["reference_id"] for item in user["input"]["evidence"]
        )
        seen_reference_ids.update(user["allowed_evidence_refs"])

        target = projection["target"]
        assert set(target) == {
            "overall_summary",
            "role_statement",
            "findings",
            "evidence_gaps",
            "abstained",
        }
        assert "disclaimer" not in target
        for finding in target["findings"]:
            assert set(finding) == {
                "finding_id",
                "summary",
                "rationale",
                "criterion",
                "severity",
                "epistemic_status",
                "evidence_refs",
                "recommended_action",
                "requires_human_validation",
            }
            assert "confidence" not in finding
            assert "content_hash" not in finding
            assert "twin_id" not in finding
            assert set(finding["evidence_refs"]).issubset(user["allowed_evidence_refs"])
    assert len(seen_reference_ids) > 20


def test_projection_contract_records_exact_strict_schema():
    contract = training_projection_contract_snapshot()
    schema = contract["output_schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "overall_summary",
        "findings",
        "evidence_gaps",
        "abstained",
    }
    assert schema["properties"]["findings"]["items"]["additionalProperties"] is False
    assert contract["response_contract"] == list(BENCHMARK_RESPONSE_CONTRACT)


def test_examples_cover_grounded_user_provided_unsupported_and_abstention():
    examples = tuple(islice(iter_campaign_examples(), 24 * 2 * 4))
    modes = Counter()
    refs = set()
    for example in examples:
        refs.update(item.reference_id for item in example.evidence)
        if example.expected_output.abstained:
            modes[SupervisionMode.ABSTAIN.value] += 1
            assert example.expected_output.findings == ()
            assert example.expected_output.evidence_gaps
            continue
        finding = example.expected_output.findings[0]
        if finding.epistemic_status is SyntheticFindingEpistemicStatus.MODEL_INFERRED:
            modes[SupervisionMode.GROUNDED_INFERENCE.value] += 1
            assert len(finding.evidence_refs) == 2
            assert finding.requires_human_validation is True
        elif finding.epistemic_status is SyntheticFindingEpistemicStatus.USER_PROVIDED:
            modes[SupervisionMode.USER_PROVIDED.value] += 1
            assert len(finding.evidence_refs) == 1
            assert finding.requires_human_validation is False
        elif finding.epistemic_status is SyntheticFindingEpistemicStatus.UNSUPPORTED_ASSUMPTION:
            modes[SupervisionMode.UNSUPPORTED_HYPOTHESIS.value] += 1
            assert finding.evidence_refs == ()
            assert finding.requires_human_validation is True
            assert example.expected_output.evidence_gaps
        else:
            raise AssertionError(f"unexpected status: {finding.epistemic_status}")
    assert set(modes) == {mode.value for mode in SUPERVISION_MODES}
    assert len(refs) > len(examples)


def test_full_24k_campaign_is_publishable_balanced_and_meets_split_minima():
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
    assert quality["supervision_mode_counts"] == {
        "ABSTAIN": 6_000,
        "GROUNDED_INFERENCE": 6_000,
        "UNSUPPORTED_HYPOTHESIS": 6_000,
        "USER_PROVIDED": 6_000,
    }
    assert quality["evidence_reference_id_count"] >= 48_000
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


def test_materializer_uses_projection_and_never_enables_training_gate():
    root = Path(__file__).resolve().parents[4]
    source = (root / "environments/training/materialize_thesis_dataset.py").read_text(
        encoding="utf-8"
    )
    assert "benchmark_aligned_training_projection(example)" in source
    assert 'TRAINING_GATE = "ORCHESTWIN_FINAL_QLORA_ALLOW_TRAINING"' in source
    assert 'os.environ.get(TRAINING_GATE) == "1"' in source
    assert 'ORCHESTWIN_FINAL_QLORA_ALLOW_TRAINING", "1"' not in source
    assert "training_executed" in source
    assert "training_authorized" in source


def test_benchmark_system_instruction_copy_has_no_drift():
    assert benchmark_aligned_system_instruction(DatasetLanguage.ENGLISH) == (
        _benchmark_system_instruction(DatasetLanguage.ENGLISH)
    )
    assert benchmark_aligned_system_instruction(DatasetLanguage.ITALIAN) == (
        _benchmark_system_instruction(DatasetLanguage.ITALIAN)
    )
