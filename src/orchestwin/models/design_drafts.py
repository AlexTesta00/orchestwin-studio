"""Model-authored design content with application-bound references and review state."""

import re
from typing import Annotated, Final
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
from orchestwin.artifacts.visual_exploration import (
    require_explored_choices,
    visual_exploration,
)
from orchestwin.artifacts.visual_language import (
    MAX_PRODUCT_NAME_LENGTH,
    MAX_TWIN_FIT_LENGTH,
    MAX_VISUAL_RATIONALE_LENGTH,
    create_twin_fit,
    create_visual_language,
)
from orchestwin.models.output_language import (
    LANGUAGE_NAMES,
    MIN_JUDGED_WORDS,
    dominant_language,
    word_count,
    written_in_another_language,
)
from orchestwin.models.proposal_generation import wire_value
from orchestwin.models.requirements_drafts import Draft, Links, Text, Title
from orchestwin.twins.epistemics import ConfidenceScore, ObservationProvenance

TITLE_LENGTH: Final = 200
TEXT_LENGTH: Final = 2000
LANGUAGE_GROUPS: Final = ("requirements", "stories", "criteria", "scenarios")
LANGUAGE_MIN_WORDS: Final = 4
ALTERNATIVE_TEXT_LISTS: Final = (
    "information_architecture",
    "accessibility_considerations",
    "security_considerations",
    "advantages",
    "trade_offs",
    "assumptions",
    "open_questions",
)
CRITIQUE_TEXT_LISTS: Final = (
    "strengths",
    "concerns",
    "unmet_needs",
    "accessibility_observations",
    "trust_concerns",
    "questions",
    "suggested_changes",
)
_KEY_TOKEN: Final = re.compile(r"\bT[1-9]\d?\b")


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


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def requirements_language(view):
    code = dominant_language(
        text
        for group in LANGUAGE_GROUPS
        for text in _strings(view[group])
        if word_count(text) >= LANGUAGE_MIN_WORDS
    )
    return None if code is None else {"code": code, "name": LANGUAGE_NAMES[code]}


def design_context(request):
    twins = {f"T{i}": twin for i, twin in enumerate(request.user_modeling.user_twins, 1)}
    requirements = requirements_view(request.requirements.version)
    return {
        "project_id": str(request.project_id),
        "governed_request_hash": request.content_hash,
        "language": requirements_language(requirements),
        "requirements": requirements,
        "visual_exploration": {
            code: {name: list(values) for name, values in dimensions.items()}
            for code, dimensions in visual_exploration(request.project_id).items()
        },
        "twins": {
            key: {
                "name": twin.reference.name,
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


def named_text(text, names, maximum=TEXT_LENGTH):
    named = _KEY_TOKEN.sub(lambda match: names.get(match[0], match[0]), text)
    return text if len(named) > maximum else named


def named_draft(draft, names):
    def text(value, maximum=TEXT_LENGTH):
        return named_text(value, names, maximum)

    def texts(values):
        return tuple(text(value) for value in values)

    alternatives = tuple(
        x.model_copy(
            update={
                "title": text(x.title, TITLE_LENGTH),
                "summary": text(x.summary),
                "rationale": text(x.rationale),
                **{key: texts(getattr(x, key)) for key in ALTERNATIVE_TEXT_LISTS},
                "workflows": tuple(
                    w.model_copy(
                        update={"title": text(w.title, TITLE_LENGTH), "steps": texts(w.steps)}
                    )
                    for w in x.workflows
                ),
                "visual": x.visual.model_copy(
                    update={
                        "approach_rationale": text(
                            x.visual.approach_rationale, MAX_VISUAL_RATIONALE_LENGTH
                        ),
                        "twin_fit": tuple(
                            item.model_copy(
                                update={"statement": text(item.statement, MAX_TWIN_FIT_LENGTH)}
                            )
                            for item in x.visual.twin_fit
                        ),
                    }
                ),
            }
        )
        for x in draft.alternatives
    )
    critiques = tuple(
        x.model_copy(
            update={
                "rationale": text(x.rationale),
                **{key: texts(getattr(x, key)) for key in CRITIQUE_TEXT_LISTS},
            }
        )
        for x in draft.critiques
    )
    concerns = tuple(
        x.model_copy(update={"summary": text(x.summary), "mitigation": text(x.mitigation)})
        for x in draft.concerns
    )
    return draft.model_copy(
        update={
            "alternatives": alternatives,
            "critiques": critiques,
            "concerns": concerns,
            "open_questions": texts(draft.open_questions),
        }
    )


def draft_texts(draft):
    for x in draft.alternatives:
        yield x.title
        yield x.summary
        yield x.rationale
        for key in ALTERNATIVE_TEXT_LISTS:
            yield from getattr(x, key)
        for w in x.workflows:
            yield w.title
            yield from w.steps
        yield x.visual.approach_rationale
        yield from (item.statement for item in x.visual.twin_fit)
    for x in draft.critiques:
        yield x.rationale
        for key in CRITIQUE_TEXT_LISTS:
            yield from getattr(x, key)
    for x in draft.concerns:
        yield x.summary
        yield x.mitigation
    yield from draft.open_questions


def require_draft_language(draft, language):
    if language is None:
        return
    judged = [text for text in draft_texts(draft) if word_count(text) >= MIN_JUDGED_WORDS]
    other = sum(written_in_another_language(text, language["code"]) for text in judged)
    if 2 * other > len(judged):
        raise ValueError("the design is not written in the language of the requirements")


def bind_design(draft, request, twins, model_reference):
    ids = requirement_code_map(request.requirements.version.specification)
    records = [*draft.alternatives, *draft.critiques, *draft.concerns]
    codes = [item.code for item in records]
    if len(set(codes)) != len(codes) or set(codes) & ids.keys():
        raise ValueError("duplicate design codes")
    ids.update({code: uuid4() for code in codes})
    draft = named_draft(draft, {key: twin.reference.name for key, twin in twins.items()})
    require_draft_language(
        draft, requirements_language(requirements_view(request.requirements.version))
    )
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
    exploration = visual_exploration(request.project_id)
    for x in draft.alternatives:
        require_explored_choices(x.code, languages[x.code].choices, exploration)
    for x in draft.alternatives:
        _require_archetype_fit(x, languages[x.code].choices)

    def links(values):
        return tuple(ids[value] for value in values)

    try:
        alternatives = [
            domain.create_design_alternative(
                alternative_id=ids[x.code],
                code=x.code,
                approach=None,
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
                **{key: getattr(x, key) for key in ALTERNATIVE_TEXT_LISTS},
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
                    **{key: getattr(x, key) for key in CRITIQUE_TEXT_LISTS},
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
