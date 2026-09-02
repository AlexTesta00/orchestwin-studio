"""Tests for deterministic scenario-family expansion."""

from __future__ import annotations

from orchestwin.training.dataset_examples import DatasetLanguage, DatasetUseRestriction
from orchestwin.training.scenarios import (
    DatasetTargetPlatform,
    ScenarioRiskDimension,
    create_scenario_generation_plans,
    default_scenario_families,
)


def test_default_families_cover_required_diversity_without_formal_case_reuse() -> None:
    families = default_scenario_families()

    dimensions = {dimension for family in families for dimension in family.dimensions}
    platforms = {family.platform for family in families}

    assert dimensions == set(ScenarioRiskDimension)
    assert {
        DatasetTargetPlatform.WEB,
        DatasetTargetPlatform.JVM,
        DatasetTargetPlatform.MOBILE_DESIGN_ONLY,
        DatasetTargetPlatform.CROSS_PLATFORM,
    } <= platforms
    assert all(family.use_restriction is DatasetUseRestriction.NONE for family in families)
    assert all(
        excluded not in family.family_id
        for family in families
        for excluded in ("calculator", "hotel", "weather")
    )


def test_plan_matrix_is_stable_across_input_order_and_has_unique_seeds() -> None:
    families = default_scenario_families()[:2]
    languages = (DatasetLanguage.ENGLISH, DatasetLanguage.ITALIAN)

    first = create_scenario_generation_plans(
        families=families,
        languages=languages,
        variants_per_language=2,
        seed=20261013,
    )
    second = create_scenario_generation_plans(
        families=reversed(families),
        languages=reversed(languages),
        variants_per_language=2,
        seed=20261013,
    )

    assert first == second
    assert len(first) == 8
    assert len({plan.seed for plan in first}) == len(first)
    assert [plan.plan_id for plan in first] == [f"SGP-{index:06d}" for index in range(1, 9)]


def test_plan_translates_to_provider_independent_generation_request() -> None:
    plan = create_scenario_generation_plans(
        families=(default_scenario_families()[0],),
        languages=(DatasetLanguage.ITALIAN,),
        variants_per_language=1,
        seed=7,
    )[0]

    request = plan.to_generation_request(
        context_hash="a" * 64,
        allowed_evidence_refs=("source-b", "source-a"),
        prompt_version_ref="dataset-teacher-v1",
        model_configuration_ref="teacher-model-v1",
    )

    assert request.request_id == plan.request_id
    assert request.scenario_family_id == plan.family.family_id
    assert request.language is DatasetLanguage.ITALIAN
    assert request.allowed_evidence_refs == ("source-a", "source-b")
    assert request.seed == plan.seed
