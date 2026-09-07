"""Deterministic scenario families and generation plans for dataset diversity."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    snapshot_content_hash,
    validate_positive_integer,
)
from orchestwin.training.dataset_examples import DatasetLanguage, DatasetUseRestriction
from orchestwin.training.generation import DatasetGenerationRequest


class DatasetTargetPlatform(StrEnum):
    """Artifact families represented in evaluator scenarios, not capability claims."""

    WEB = "WEB"
    JVM = "JVM"
    MOBILE_DESIGN_ONLY = "MOBILE_DESIGN_ONLY"
    CROSS_PLATFORM = "CROSS_PLATFORM"


class ScenarioRiskDimension(StrEnum):
    """Diversity dimensions required by the dataset protocol."""

    ACCESSIBILITY = "ACCESSIBILITY"
    TIME_PRESSURE = "TIME_PRESSURE"
    TRUST = "TRUST"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"
    STAKEHOLDER_CONFLICT = "STAKEHOLDER_CONFLICT"
    DETERMINISTIC_FAILURE = "DETERMINISTIC_FAILURE"
    BROWNFIELD = "BROWNFIELD"


@dataclass(frozen=True, slots=True)
class ScenarioFamily:
    """One reusable project-independent family of evaluator scenarios."""

    family_id: str
    platform: DatasetTargetPlatform
    domain_tag: str
    role_tag: str
    dimensions: tuple[ScenarioRiskDimension, ...]
    base_context: str
    use_restriction: DatasetUseRestriction = DatasetUseRestriction.NONE

    def __post_init__(self) -> None:
        for value, label, maximum_length in (
            (self.family_id, "scenario family ID", 256),
            (self.domain_tag, "scenario domain tag", 128),
            (self.role_tag, "scenario role tag", 128),
            (self.base_context, "scenario family base context", 4_000),
        ):
            normalized = normalize_required_text(
                value,
                label=label,
                maximum_length=maximum_length,
            )
            if normalized != value:
                raise ValueError(f"{label} must be normalized")

        if not self.dimensions:
            raise ValueError("scenario family dimensions must not be empty")
        if len(self.dimensions) != len(set(self.dimensions)):
            raise ValueError("scenario family dimensions must be unique")
        order = {dimension: index for index, dimension in enumerate(ScenarioRiskDimension)}
        expected_dimensions = tuple(sorted(self.dimensions, key=order.__getitem__))
        if self.dimensions != expected_dimensions:
            raise ValueError("scenario family dimensions must use canonical order")

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return (self.family_id, self.platform.value, self.role_tag)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "family_id": self.family_id,
            "platform": self.platform.value,
            "domain_tag": self.domain_tag,
            "role_tag": self.role_tag,
            "dimensions": [dimension.value for dimension in self.dimensions],
            "base_context": self.base_context,
            "use_restriction": self.use_restriction.value,
        }


@dataclass(frozen=True, slots=True)
class ScenarioGenerationPlan:
    """One deterministic language-specific variant request."""

    plan_id: str
    family: ScenarioFamily
    language: DatasetLanguage
    variant_number: int
    seed: int
    request_id: str
    scenario_instruction: str
    content_hash: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.plan_id, "scenario generation plan ID"),
            (self.request_id, "scenario generation request ID"),
            (self.scenario_instruction, "scenario generation instruction"),
        ):
            normalized = normalize_required_text(value, label=label, maximum_length=4_000)
            if normalized != value:
                raise ValueError(f"{label} must be normalized")
        validate_positive_integer(
            self.variant_number,
            label="scenario generation variant number",
        )
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("scenario generation seed must be a non-negative integer")
        expected_hash = scenario_generation_plan_hash(
            plan_id=self.plan_id,
            family=self.family,
            language=self.language,
            variant_number=self.variant_number,
            seed=self.seed,
            request_id=self.request_id,
            scenario_instruction=self.scenario_instruction,
        )
        if self.content_hash != expected_hash:
            raise ValueError("scenario generation plan content hash is inconsistent")

    @property
    def sort_key(self) -> tuple[str, str, int]:
        return (self.family.family_id, self.language.value, self.variant_number)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "family": self.family.to_snapshot(),
            "language": self.language.value,
            "variant_number": self.variant_number,
            "seed": self.seed,
            "request_id": self.request_id,
            "scenario_instruction": self.scenario_instruction,
            "content_hash": self.content_hash,
        }

    def to_generation_request(
        self,
        *,
        context_hash: str,
        allowed_evidence_refs: tuple[str, ...],
        prompt_version_ref: str,
        model_configuration_ref: str,
    ) -> DatasetGenerationRequest:
        """Translate the plan into the provider-independent generation contract."""
        return DatasetGenerationRequest(
            request_id=self.request_id,
            scenario_family_id=self.family.family_id,
            language=self.language,
            target_count=1,
            seed=self.seed,
            context_hash=context_hash,
            allowed_evidence_refs=tuple(sorted(allowed_evidence_refs)),
            prompt_version_ref=prompt_version_ref,
            model_configuration_ref=model_configuration_ref,
        )


def default_scenario_families() -> tuple[ScenarioFamily, ...]:
    """Return generic families spanning the required risk and artifact dimensions."""
    definitions = (
        (
            "generic-web-accessibility",
            DatasetTargetPlatform.WEB,
            "public-service",
            "occasional-user",
            (ScenarioRiskDimension.ACCESSIBILITY,),
            "An occasional user completes a primary task with keyboard and assistive technology.",
        ),
        (
            "generic-jvm-time-pressure",
            DatasetTargetPlatform.JVM,
            "operations",
            "expert-operator",
            (ScenarioRiskDimension.TIME_PRESSURE,),
            "An expert operator must recover from an error while handling an urgent workflow.",
        ),
        (
            "generic-web-trust",
            DatasetTargetPlatform.WEB,
            "decision-support",
            "responsible-reviewer",
            (ScenarioRiskDimension.TRUST,),
            "A reviewer evaluates a recommendation whose rationale and uncertainty are incomplete.",
        ),
        (
            "generic-cross-insufficient-evidence",
            DatasetTargetPlatform.CROSS_PLATFORM,
            "generic",
            "domain-user",
            (ScenarioRiskDimension.INSUFFICIENT_EVIDENCE,),
            "The supplied artifact description omits information needed for a defensible finding.",
        ),
        (
            "generic-cross-contradictory-evidence",
            DatasetTargetPlatform.CROSS_PLATFORM,
            "generic",
            "domain-user",
            (ScenarioRiskDimension.CONTRADICTORY_EVIDENCE,),
            "Two approved sources disagree about the user's preferred workflow and constraints.",
        ),
        (
            "generic-web-stakeholder-conflict",
            DatasetTargetPlatform.WEB,
            "collaborative-work",
            "coordinating-stakeholder",
            (ScenarioRiskDimension.STAKEHOLDER_CONFLICT,),
            "Two stakeholder roles prioritize speed and oversight "
            "differently in the same workflow.",
        ),
        (
            "generic-jvm-deterministic-failure",
            DatasetTargetPlatform.JVM,
            "developer-tooling",
            "technical-user",
            (ScenarioRiskDimension.DETERMINISTIC_FAILURE,),
            "A deterministic test failure contradicts a fluent positive "
            "description of the feature.",
        ),
        (
            "generic-brownfield-recovery",
            DatasetTargetPlatform.CROSS_PLATFORM,
            "brownfield",
            "maintainer",
            (ScenarioRiskDimension.BROWNFIELD,),
            "A maintainer reviews an incomplete legacy workflow with inferred requirements.",
        ),
        (
            "generic-mobile-design-accessibility",
            DatasetTargetPlatform.MOBILE_DESIGN_ONLY,
            "mobile-interface",
            "occasional-user",
            (ScenarioRiskDimension.ACCESSIBILITY,),
            "A mobile design artifact is reviewed without implying "
            "validated device execution support.",
        ),
    )
    families = tuple(
        ScenarioFamily(
            family_id=family_id,
            platform=platform,
            domain_tag=domain_tag,
            role_tag=role_tag,
            dimensions=dimensions,
            base_context=base_context,
        )
        for family_id, platform, domain_tag, role_tag, dimensions, base_context in definitions
    )
    return tuple(sorted(families, key=lambda family: family.sort_key))


def create_scenario_generation_plans(
    *,
    families: Iterable[ScenarioFamily],
    languages: Iterable[DatasetLanguage],
    variants_per_language: int,
    seed: int,
) -> tuple[ScenarioGenerationPlan, ...]:
    """Expand families into a stable, reproducible plan matrix."""
    validate_positive_integer(
        variants_per_language,
        label="scenario variants per language",
    )
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("scenario plan seed must be a non-negative integer")

    canonical_families = tuple(sorted(tuple(families), key=lambda family: family.sort_key))
    family_ids = tuple(family.family_id for family in canonical_families)
    if len(family_ids) != len(set(family_ids)):
        raise ValueError("scenario family IDs must be unique")

    canonical_languages = tuple(sorted(tuple(languages), key=lambda language: language.value))
    if not canonical_languages:
        raise ValueError("scenario plan languages must not be empty")
    if len(canonical_languages) != len(set(canonical_languages)):
        raise ValueError("scenario plan languages must be unique")

    combinations = tuple(
        (family, language, variant_number)
        for family in canonical_families
        for language in canonical_languages
        for variant_number in range(1, variants_per_language + 1)
    )
    plans: list[ScenarioGenerationPlan] = []
    for index, (family, language, variant_number) in enumerate(combinations, start=1):
        plan_id = f"SGP-{index:06d}"
        request_id = f"dataset-{family.family_id}-{language.value}-variant-{variant_number:03d}"
        derived_seed = _derived_seed(
            seed=seed,
            family_id=family.family_id,
            language=language,
            variant_number=variant_number,
        )
        scenario_instruction = (
            f"Create variant {variant_number} for {family.base_context} "
            f"Respond in language {language.value}. Preserve the family's dimensions: "
            + ", ".join(dimension.value for dimension in family.dimensions)
            + "."
        )
        content_hash = scenario_generation_plan_hash(
            plan_id=plan_id,
            family=family,
            language=language,
            variant_number=variant_number,
            seed=derived_seed,
            request_id=request_id,
            scenario_instruction=scenario_instruction,
        )
        plans.append(
            ScenarioGenerationPlan(
                plan_id=plan_id,
                family=family,
                language=language,
                variant_number=variant_number,
                seed=derived_seed,
                request_id=request_id,
                scenario_instruction=scenario_instruction,
                content_hash=content_hash,
            )
        )
    return tuple(plans)


def scenario_generation_plan_hash(
    *,
    plan_id: str,
    family: ScenarioFamily,
    language: DatasetLanguage,
    variant_number: int,
    seed: int,
    request_id: str,
    scenario_instruction: str,
) -> str:
    return snapshot_content_hash(
        {
            "plan_id": plan_id,
            "family": family.to_snapshot(),
            "language": language.value,
            "variant_number": variant_number,
            "seed": seed,
            "request_id": request_id,
            "scenario_instruction": scenario_instruction,
        }
    )


def _derived_seed(
    *,
    seed: int,
    family_id: str,
    language: DatasetLanguage,
    variant_number: int,
) -> int:
    payload = f"{seed}:{family_id}:{language.value}:{variant_number}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
