"""Model-authored design content with application-bound references and review state."""

import re
from typing import Annotated, Final
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from orchestwin.agents.perspectives import GuidanceStage, perspective_guidance
from orchestwin.artifacts import design as domain
from orchestwin.artifacts.design_packages import (
    create_design_concern,
    create_design_exploration_package,
    create_design_grounding,
)
from orchestwin.artifacts.visual_catalog import (
    ARCHETYPES,
    VISUAL_DIMENSION_NAMES,
    VISUAL_DIMENSIONS,
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
from orchestwin.models.planning_schema import HOSTED_DESIGN_PURPOSE
from orchestwin.models.proposal_generation import wire_value
from orchestwin.models.requirements_drafts import Draft, Links, Text, Title
from orchestwin.twins.epistemics import ConfidenceScore, ObservationProvenance

TITLE_LENGTH: Final = 200
TEXT_LENGTH: Final = 2000
HOSTED_DESIGN_CONTRACT_VERSION: Final = 107
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
    "on_accessibility",
    "trust_concerns",
    "questions",
    "suggested_changes",
)
CRITIQUE_DOMAIN_FIELDS: Final = {"on_accessibility": "accessibility_observations"}
VERDICT_LIMITS: Final = {
    "verdict": domain.MAX_CRITIQUE_VERDICT_LENGTH,
    "quote": domain.MAX_CRITIQUE_QUOTE_LENGTH,
}
CATALOG_IDS: Final = frozenset(item.value for enum in VISUAL_DIMENSIONS.values() for item in enum)
UNCHOSEN_CATALOG_VALUES: Final = "the design names catalog values that were not chosen"
_KEY_TOKEN: Final = re.compile(r"\bT[1-9]\d?\b")
_CATALOG_TOKEN: Final = re.compile(r"\b[A-Z][A-Z]+(?:_[A-Z]+)*\b")
_ALTERNATIVE_CODE: Final = re.compile(r"\bDES-[0-9]{3,}\b")
_SENTENCE_BREAK: Final = re.compile(r"(?<=[.!?…])\s+")


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
    visual_rationale: Text

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
    as_twin: str
    observation_keys: Links
    strengths: Annotated[tuple[Text, ...], Field(min_length=1)]
    concerns: Annotated[tuple[Text, ...], Field(min_length=1)]
    unmet_needs: tuple[Text, ...]
    on_accessibility: tuple[Text, ...]
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


class HostedCritiqueDraft(CritiqueDraft):
    quote: Annotated[str, Field(min_length=1, max_length=domain.MAX_CRITIQUE_QUOTE_LENGTH)]
    verdict: Annotated[str, Field(min_length=1, max_length=domain.MAX_CRITIQUE_VERDICT_LENGTH)]


class HostedDesignDraft(DesignDraft):
    critiques: Annotated[tuple[HostedCritiqueDraft, ...], Field(min_length=2)]


def hosted_design_context(context, selected_agent_ids):
    return {
        **context,
        "purpose": HOSTED_DESIGN_PURPOSE,
        "perspectives": perspective_guidance(selected_agent_ids, GuidanceStage.DESIGN),
    }


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
    if spec.schema_version == 2:
        codes.update(
            {
                str(item.id): item.code
                for group in (spec.scenarios, spec.needs, spec.journeys)
                for item in group
            }
        )
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

    view = {
        "reference": {
            "id": str(version.id),
            "version": version.version_number,
            "content_hash": version.content_hash,
        },
        "requirements": compact([item.to_snapshot() for item in spec.requirements]),
        "stories": compact([item.to_snapshot() for item in spec.user_stories]),
        "criteria": compact([item.to_snapshot() for item in spec.acceptance_criteria]),
        "scenarios": compact([item.to_snapshot() for item in spec.scenarios]),
        "risks": compact([item.to_snapshot() for item in spec.risks]),
        "definition_of_done": compact([item.to_snapshot() for item in spec.definition_of_done]),
    }
    if spec.schema_version == 2:
        view["schema_version"] = 2
        view["needs"] = compact([item.to_snapshot() for item in spec.needs])
        if spec.journeys:
            view["journeys"] = compact([item.to_snapshot() for item in spec.journeys])
    return view


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
        for group in (*LANGUAGE_GROUPS, "needs")
        for text in _strings(view.get(group, []))
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


def map_draft_texts(draft, single, items):
    everyone = tuple(x.code for x in draft.alternatives)
    alternatives = tuple(
        x.model_copy(
            update={
                "title": single(x.title, (x.code,), TITLE_LENGTH),
                "summary": single(x.summary, (x.code,), TEXT_LENGTH),
                "rationale": single(x.rationale, (x.code,), TEXT_LENGTH),
                **{
                    key: items(AlternativeDraft, key, getattr(x, key), (x.code,))
                    for key in ALTERNATIVE_TEXT_LISTS
                },
                "workflows": tuple(
                    w.model_copy(
                        update={
                            "title": single(w.title, (x.code,), TITLE_LENGTH),
                            "steps": tuple(
                                single(step, (x.code,), TEXT_LENGTH) for step in w.steps
                            ),
                        }
                    )
                    for w in x.workflows
                ),
                "visual": x.visual.model_copy(
                    update={
                        "visual_rationale": single(
                            x.visual.visual_rationale, (x.code,), MAX_VISUAL_RATIONALE_LENGTH
                        ),
                        "twin_fit": tuple(
                            item.model_copy(
                                update={
                                    "statement": single(
                                        item.statement, (x.code,), MAX_TWIN_FIT_LENGTH
                                    )
                                }
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
                "rationale": single(x.rationale, (x.alternative,), TEXT_LENGTH),
                **{
                    key: items(CritiqueDraft, key, getattr(x, key), (x.alternative,))
                    for key in CRITIQUE_TEXT_LISTS
                },
                **_verdict_texts(x, single),
            }
        )
        for x in draft.critiques
    )
    concerns = tuple(
        x.model_copy(
            update={
                "summary": single(x.summary, x.alternatives, TEXT_LENGTH),
                "mitigation": single(x.mitigation, x.alternatives, TEXT_LENGTH),
            }
        )
        for x in draft.concerns
    )
    return draft.model_copy(
        update={
            "alternatives": alternatives,
            "critiques": critiques,
            "concerns": concerns,
            "open_questions": items(DesignDraft, "open_questions", draft.open_questions, everyone),
        }
    )


def verdict_values(critique):
    if not isinstance(critique, HostedCritiqueDraft):
        return {}
    return {"verdict": critique.verdict, "quote": critique.quote}


def _verdict_texts(critique, single):
    return {
        key: single(value, (critique.alternative,), VERDICT_LIMITS[key])
        for key, value in verdict_values(critique).items()
    }


def named_draft(draft, names):
    return map_draft_texts(
        draft,
        lambda text, owners, maximum: named_text(text, names, maximum),
        lambda model, field, texts, owners: tuple(named_text(text, names) for text in texts),
    )


def catalog_ids(text):
    return {token for token in _CATALOG_TOKEN.findall(text) if token in CATALOG_IDS}


def chosen_catalog_ids(draft):
    return {
        x.code: frozenset(str(getattr(x.visual, name)) for name in VISUAL_DIMENSION_NAMES)
        for x in draft.alternatives
    }


def consistent_text(text, owners, chosen):
    sentences = _SENTENCE_BREAK.split(text.strip())
    kept = [
        sentence
        for sentence in sentences
        if catalog_ids(sentence)
        <= frozenset().union(
            *(
                chosen.get(code, frozenset())
                for code in (*owners, *_ALTERNATIVE_CODE.findall(sentence))
            )
        )
    ]
    return text if len(kept) == len(sentences) else " ".join(kept)


def schema_minimum(model, field):
    return max(
        (getattr(item, "min_length", 0) for item in model.model_fields[field].metadata),
        default=0,
    )


def consistent_draft(draft):
    chosen = chosen_catalog_ids(draft)

    def single(text, owners, maximum):
        consistent = consistent_text(text, owners, chosen)
        if not consistent:
            raise ValueError(UNCHOSEN_CATALOG_VALUES)
        return consistent

    def items(model, field, texts, owners):
        kept = tuple(
            consistent
            for consistent in (consistent_text(text, owners, chosen) for text in texts)
            if consistent
        )
        if len(kept) < schema_minimum(model, field):
            raise ValueError(UNCHOSEN_CATALOG_VALUES)
        return kept

    return map_draft_texts(draft, single, items)


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
        yield x.visual.visual_rationale
        yield from (item.statement for item in x.visual.twin_fit)
    for x in draft.critiques:
        yield x.rationale
        for key in CRITIQUE_TEXT_LISTS:
            yield from getattr(x, key)
        yield from verdict_values(x).values()
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


def bind_design(draft, request, twins, model_reference, *, directions=None, exploration=None):
    ids = requirement_code_map(request.requirements.version.specification)
    records = [*draft.alternatives, *draft.critiques, *draft.concerns]
    codes = [item.code for item in records]
    if len(set(codes)) != len(codes) or set(codes) & ids.keys():
        raise ValueError("duplicate design codes")
    if directions is not None and {x.code for x in draft.alternatives} - set(directions):
        raise ValueError("unknown design reference")
    ids.update({code: uuid4() for code in codes})
    draft = named_draft(draft, {key: twin.reference.name for key, twin in twins.items()})
    require_draft_language(
        draft, requirements_language(requirements_view(request.requirements.version))
    )
    draft = consistent_draft(draft)
    languages = {
        x.code: create_visual_language(
            choices=x.visual.choices(),
            product_name=x.visual.product_name,
            rationale=x.visual.visual_rationale,
            twin_fit=_twin_fit(x, twins),
            direction=None if directions is None else directions[x.code],
        )
        for x in draft.alternatives
    }
    require_distinct_visual_choices([languages[x.code].choices for x in draft.alternatives])
    if exploration is None:
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
            twin = twins[x.as_twin]
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
                        CRITIQUE_DOMAIN_FIELDS.get(key, key): getattr(x, key)
                        for key in CRITIQUE_TEXT_LISTS
                    },
                    **verdict_values(x),
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
