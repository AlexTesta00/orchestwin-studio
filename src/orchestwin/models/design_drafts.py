"""Model-authored design content with application-bound references and review state."""

from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from orchestwin.artifacts import design as domain
from orchestwin.artifacts.design_packages import (
    create_design_concern,
    create_design_exploration_package,
    create_design_grounding,
)
from orchestwin.artifacts.visual_catalog import (
    ARCHETYPES,
    VISUAL_DIMENSION_NAMES,
    BackgroundTreatment,
    BorderWeight,
    ButtonStyle,
    ColorMode,
    ColorScheme,
    CornerStyle,
    Density,
    DesignTone,
    Elevation,
    Emphasis,
    FontFamily,
    HeaderStyle,
    HeadingCase,
    HeadingWeight,
    HueFamily,
    InputStyle,
    LayoutArchetype,
    NavigationPattern,
    Saturation,
    SurfaceTone,
    TypeScale,
    VisualChoices,
    require_distinct_visual_choices,
)
from orchestwin.artifacts.visual_language import (
    MAX_PRODUCT_NAME_LENGTH,
    MAX_TWIN_FIT_LENGTH,
    create_twin_fit,
    create_visual_language,
)
from orchestwin.models.proposal_generation import wire_value
from orchestwin.models.requirements_drafts import Draft, Links, Text, Title
from orchestwin.twins.epistemics import ConfidenceScore, ObservationProvenance


class WorkflowDraft(Draft):
    code: str = Field(pattern=r"^FLOW-[0-9]{3,}$")
    title: Title
    steps: Annotated[tuple[Text, ...], Field(min_length=1)]
    requirements: Links
    stories: Links


class TwinFitDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    twin: str
    statement: Annotated[str, Field(min_length=1, max_length=MAX_TWIN_FIT_LENGTH)]


class VisualLanguageDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    approach_rationale: Text
    archetype: LayoutArchetype
    background: BackgroundTreatment
    body_family: FontFamily
    borders: BorderWeight
    buttons: ButtonStyle
    color_mode: ColorMode
    color_scheme: ColorScheme
    corners: CornerStyle
    density: Density
    elevation: Elevation
    emphasis: Emphasis
    header: HeaderStyle
    heading_case: HeadingCase
    heading_family: FontFamily
    heading_weight: HeadingWeight
    hue_family: HueFamily
    inputs: InputStyle
    navigation: NavigationPattern
    product_name: Annotated[str, Field(min_length=1, max_length=MAX_PRODUCT_NAME_LENGTH)]
    saturation: Saturation
    surface_tone: SurfaceTone
    tone: DesignTone
    twin_fit: Annotated[tuple[TwinFitDraft, ...], Field(min_length=1)]
    type_scale: TypeScale

    def choices(self) -> VisualChoices:
        return VisualChoices(**{name: getattr(self, name) for name in VISUAL_DIMENSION_NAMES})


class AlternativeDraft(Draft):
    code: str = Field(pattern=r"^DES-[0-9]{3,}$")
    approach: domain.DesignApproach
    title: Title
    summary: Text
    rationale: Text
    requirements: Links
    stories: Links
    criteria: Links
    twins: Links
    workflows: Annotated[tuple[WorkflowDraft, ...], Field(min_length=1)]
    information_architecture: Annotated[tuple[Text, ...], Field(min_length=1)]
    accessibility_considerations: Annotated[tuple[Text, ...], Field(min_length=1)]
    security_considerations: Annotated[tuple[Text, ...], Field(min_length=1)]
    advantages: Annotated[tuple[Text, ...], Field(min_length=1)]
    trade_offs: Annotated[tuple[Text, ...], Field(min_length=1)]
    assumptions: tuple[Text, ...]
    open_questions: tuple[Text, ...]
    visual: VisualLanguageDraft


class CritiqueDraft(Draft):
    code: str = Field(pattern=r"^CRQ-[0-9]{3,}$")
    alternative: str
    twin: str
    observation_keys: Links
    strengths: Annotated[tuple[Text, ...], Field(min_length=1)]
    concerns: Annotated[tuple[Text, ...], Field(min_length=1)]
    unmet_needs: tuple[Text, ...]
    accessibility_observations: tuple[Text, ...]
    trust_concerns: tuple[Text, ...]
    questions: tuple[Text, ...]
    suggested_changes: tuple[Text, ...]
    confidence: float = Field(ge=0, le=1)
    rationale: Text


class ConcernDraft(Draft):
    code: str = Field(pattern=r"^DRK-[0-9]{3,}$")
    summary: Text
    mitigation: Text
    requirements: tuple[str, ...]
    alternatives: tuple[str, ...]


class DesignDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    alternatives: Annotated[tuple[AlternativeDraft, ...], Field(min_length=2, max_length=4)]
    critiques: Annotated[tuple[CritiqueDraft, ...], Field(min_length=2)]
    recommendation: str
    concerns: tuple[ConcernDraft, ...]
    open_questions: tuple[Text, ...]


def requirement_code_map(spec):
    return {
        x.code: x.id
        for group in (spec.requirements, spec.user_stories, spec.acceptance_criteria)
        for x in group
    }


def requirements_view(version):
    """Semantic view of an exact immutable requirements version, without repeated hashes."""
    spec = version.specification
    codes = {str(value): key for key, value in requirement_code_map(spec).items()}
    twins = {str(ref.twin_id): f"T{i}" for i, ref in enumerate(spec.user_twin_references, 1)}

    def compact(value):
        if isinstance(value, str):
            return codes.get(value, value)
        if isinstance(value, list):
            return [compact(item) for item in value]
        if isinstance(value, dict):
            if "twin_id" in value:
                return twins[value["twin_id"]]
            return {
                key: compact(item) for key, item in value.items() if key not in {"id", "sources"}
            }
        return value

    return {
        "reference": {
            "id": str(version.id),
            "version": version.version_number,
            "content_hash": version.content_hash,
        },
        "requirements": compact(wire_value(spec.requirements)),
        "stories": compact(wire_value(spec.user_stories)),
        "criteria": compact(wire_value(spec.acceptance_criteria)),
        "scenarios": compact(wire_value(spec.scenarios)),
        "risks": compact(wire_value(spec.risks)),
        "definition_of_done": compact(wire_value(spec.definition_of_done)),
    }


def design_context(request):
    twins = {f"T{i}": twin for i, twin in enumerate(request.user_modeling.user_twins, 1)}
    return {
        "project_id": str(request.project_id),
        "governed_request_hash": request.content_hash,
        "requirements": requirements_view(request.requirements.version),
        "twins": {
            key: {
                "reference": wire_value(twin.reference),
                "observations": {
                    item.observation_key: {
                        "value": wire_value(item.value),
                        "epistemic_status": item.epistemic_status.value,
                        "rationale": item.rationale,
                    }
                    for item in twin.observations
                },
            }
            for key, twin in twins.items()
        },
    }, twins


def _twin_fit(alternative, twins):
    keys = [item.twin for item in alternative.visual.twin_fit]
    if sorted(keys) != sorted(twins):
        raise ValueError("visual twin fit must cover every twin exactly once")
    return tuple(
        create_twin_fit(reference=twins[item.twin].reference, statement=item.statement)
        for item in alternative.visual.twin_fit
    )


def _require_archetype_fit(alternative, choices):
    spec = ARCHETYPES[choices.archetype]
    if max(len(w.steps) for w in alternative.workflows) < spec.minimum_workflow_steps:
        raise ValueError(
            f"{choices.archetype.value} requires a workflow with at least "
            f"{spec.minimum_workflow_steps} steps"
        )
    if len(alternative.information_architecture) < spec.minimum_information_areas:
        raise ValueError(
            f"{choices.archetype.value} requires at least {spec.minimum_information_areas} "
            "information architecture areas"
        )


def bind_design(draft, request, twins, model_reference):
    ids = requirement_code_map(request.requirements.version.specification)
    records = [*draft.alternatives, *draft.critiques, *draft.concerns]
    codes = [item.code for item in records]
    if len(set(codes)) != len(codes) or set(codes) & ids.keys():
        raise ValueError("duplicate design codes")
    ids.update({code: uuid4() for code in codes})
    languages = {
        x.code: create_visual_language(
            choices=x.visual.choices(),
            product_name=x.visual.product_name,
            rationale=x.visual.approach_rationale,
            twin_fit=_twin_fit(x, twins),
        )
        for x in draft.alternatives
    }
    require_distinct_visual_choices([languages[x.code].choices for x in draft.alternatives])
    for x in draft.alternatives:
        _require_archetype_fit(x, languages[x.code].choices)

    def links(values):
        return tuple(ids[value] for value in values)

    try:
        alternatives = [
            domain.create_design_alternative(
                alternative_id=ids[x.code],
                code=x.code,
                approach=x.approach,
                visual_language=languages[x.code],
                title=x.title,
                summary=x.summary,
                rationale=x.rationale,
                requirement_ids=links(x.requirements),
                user_story_ids=links(x.stories),
                acceptance_criterion_ids=links(x.criteria),
                user_twin_references=[twins[t].reference for t in x.twins],
                workflows=[
                    domain.create_design_workflow(
                        workflow_id=uuid4(),
                        code=w.code,
                        title=w.title,
                        steps=w.steps,
                        requirement_ids=links(w.requirements),
                        user_story_ids=links(w.stories),
                    )
                    for w in x.workflows
                ],
                **{
                    key: getattr(x, key)
                    for key in (
                        "information_architecture",
                        "accessibility_considerations",
                        "security_considerations",
                        "advantages",
                        "trade_offs",
                        "assumptions",
                        "open_questions",
                    )
                },
            )
            for x in draft.alternatives
        ]
        critiques = []
        for x in draft.critiques:
            twin = twins[x.twin]
            observations = {item.observation_key: item for item in twin.observations}
            references = {
                ref for key in x.observation_keys for ref in observations[key].provenance.references
            }
            critiques.append(
                domain.create_synthetic_design_critique(
                    critique_id=ids[x.code],
                    code=x.code,
                    design_alternative_id=ids[x.alternative],
                    user_twin_reference=twin.reference,
                    confidence=ConfidenceScore(x.confidence),
                    rationale=x.rationale,
                    provenance=ObservationProvenance.from_references(
                        (*references, model_reference(x.code)),
                    ),
                    **{
                        key: getattr(x, key)
                        for key in (
                            "strengths",
                            "concerns",
                            "unmet_needs",
                            "accessibility_observations",
                            "trust_concerns",
                            "questions",
                            "suggested_changes",
                        )
                    },
                )
            )
        concerns = [
            create_design_concern(
                concern_id=ids[x.code],
                code=x.code,
                summary=x.summary,
                mitigation=x.mitigation,
                requirement_ids=links(x.requirements),
                design_alternative_ids=links(x.alternatives),
            )
            for x in draft.concerns
        ]
        recommendation = ids[draft.recommendation]
    except KeyError as error:
        raise ValueError("unknown design reference") from error
    return create_design_exploration_package(
        project_id=request.project_id,
        grounding=create_design_grounding(request.requirements.version),
        alternatives=alternatives,
        critiques=critiques,
        recommended_alternative_id=recommendation,
        concerns=concerns,
        open_questions=draft.open_questions,
    )
