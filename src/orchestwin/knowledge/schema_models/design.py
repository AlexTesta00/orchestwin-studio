from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import ConfigDict, Field, model_validator

from orchestwin.artifacts.design import (
    MAX_CRITIQUE_QUOTE_LENGTH,
    MAX_CRITIQUE_VERDICT_LENGTH,
    DesignApproach,
    DesignCritiqueKind,
)
from orchestwin.artifacts.design_packages import (
    DESIGN_PACKAGE_SCHEMA_VERSION,
    MAX_OWNER_ASSERTION_LENGTH,
    MAX_OWNER_ASSERTIONS,
)
from orchestwin.artifacts.generated_mockups import (
    MAX_MARKUP_LENGTH,
    MAX_SCREENS,
    MAX_STYLES_LENGTH,
    MAX_TITLE_LENGTH,
    MIN_SCREENS,
    MOCKUP_CONTRACT_VERSION,
)
from orchestwin.artifacts.prototypes import (
    PrototypeElementKind,
    PrototypeScreenState,
    PrototypeViewport,
)
from orchestwin.artifacts.references import ArtifactKind
from orchestwin.artifacts.visual_directions import (
    MAX_DIRECTION_CONCEPT_LENGTH,
    MAX_DIRECTION_NAME_LENGTH,
    MAX_DIRECTION_RULE_LENGTH,
    MAX_DIRECTION_RULES,
    MIN_DIRECTION_RULES,
    DirectionColour,
    DirectionDensity,
    DirectionLayout,
    DirectionShape,
    DirectionType,
)
from orchestwin.knowledge.schema_models.base import (
    _BY_VALUE,
    _OPTIONAL,
    CatalogReference,
    EvidenceReference,
    Sha256,
    UserTwinReference,
    Uuid,
    _code,
    _Confidence,
    _Record,
    _Version,
)
from orchestwin.twins.epistemics import EpistemicStatus, HumanValidationRequirement

_MOCKUP_SCREEN_CODE_PATTERN: Final = r"^SCR-[0-9]{3}$"
_MARKUP_REQUIREMENT_CODE_PATTERN: Final = r"^[A-Z]{2,5}-[0-9]{3}$"
_MAX_DIRECTION_TYPICALITY: Final = 100
_MIN_DIRECTION_CANDIDATES: Final = 2
_MAX_DIRECTION_CANDIDATES: Final = 20

_Verdict = Annotated[str, Field(min_length=1, max_length=MAX_CRITIQUE_VERDICT_LENGTH)]
_Quote = Annotated[str, Field(min_length=1, max_length=MAX_CRITIQUE_QUOTE_LENGTH)]
_OwnerAssertion = Annotated[str, Field(min_length=1, max_length=MAX_OWNER_ASSERTION_LENGTH)]
_OwnerAssertions = Annotated[
    list[_OwnerAssertion], Field(min_length=1, max_length=MAX_OWNER_ASSERTIONS)
]
_DirectionName = Annotated[str, Field(min_length=1, max_length=MAX_DIRECTION_NAME_LENGTH)]
_DirectionConcept = Annotated[str, Field(min_length=1, max_length=MAX_DIRECTION_CONCEPT_LENGTH)]
_DirectionRule = Annotated[str, Field(min_length=1, max_length=MAX_DIRECTION_RULE_LENGTH)]
_MarkupRequirementCode = Annotated[str, Field(pattern=_MARKUP_REQUIREMENT_CODE_PATTERN)]


class DesignContextReference(_Record):
    kind: Annotated[ArtifactKind, _BY_VALUE] = Field(description="Kind of the referenced artifact.")
    artifact_id: Uuid = Field(description="Identifier of the referenced version.")
    version_number: _Version = Field(description="Version number of the referenced artifact.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the referenced artifact.")


class DesignGrounding(_Record):
    requirements_reference: DesignContextReference = Field(
        description="Approved requirements version the design is grounded on."
    )
    agent_team_reference: DesignContextReference = Field(
        description="Approved agent team version that produced the design."
    )
    user_modeling_reference: DesignContextReference = Field(
        description="Approved user modeling version the design is grounded on."
    )
    catalog: CatalogReference = Field(description="Agent catalog in use.")
    requirement_ids: list[Uuid] = Field(description="Requirements the design may reference.")
    user_story_ids: list[Uuid] = Field(description="User stories the design may reference.")
    acceptance_criterion_ids: list[Uuid] = Field(
        description="Acceptance criteria the design may reference."
    )
    user_twin_references: list[UserTwinReference] = Field(
        description="User twin versions the design serves."
    )


class DesignWorkflow(_Record):
    id: Uuid = Field(description="Stable identifier of the workflow.")
    code: str = Field(
        pattern=_code("FLOW"), description="Human-readable code of the workflow, like FLOW-001."
    )
    title: str = Field(description="Short title of the workflow.")
    steps: list[str] = Field(description="Ordered steps of the workflow.")
    requirement_ids: list[Uuid] = Field(description="Requirements the workflow covers.")
    user_story_ids: list[Uuid] = Field(description="User stories the workflow covers.")


class TwinFit(_Record):
    twin_id: Uuid = Field(description="User twin the statement is about.")
    name: str = Field(description="Display name of that user twin.")
    statement: str = Field(description="Why the visual language suits that user twin.")


class DirectionAxes(_Record):
    model_config = ConfigDict(extra="forbid", strict=True)

    layout: Annotated[DirectionLayout, _BY_VALUE] = Field(
        description="How every screen is composed, such as panels, bands or an editorial page."
    )
    shape: Annotated[DirectionShape, _BY_VALUE] = Field(
        description="Language of the shapes of panels and controls: corners, borders and shadows."
    )
    type: Annotated[DirectionType, _BY_VALUE] = Field(
        description="Type scale of the screens and where the hierarchy of the text comes from."
    )
    colour: Annotated[DirectionColour, _BY_VALUE] = Field(
        description="How the colours of the palette are used on the screens."
    )
    density: Annotated[DirectionDensity, _BY_VALUE] = Field(
        description="How much space surrounds the content and how large the controls are."
    )


class VisualDirection(_Record):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: _DirectionName = Field(description="Name of the art direction, in two or three words.")
    concept: _DirectionConcept = Field(
        description="Idea of the direction and why it suits the people and the domain of the project."
    )
    rules: list[_DirectionRule] = Field(
        min_length=MIN_DIRECTION_RULES,
        max_length=MAX_DIRECTION_RULES,
        description=(
            "Rules for the screens of the alternative, concrete enough that a person can check them "
            "by looking at the result."
        ),
    )
    axes: DirectionAxes = Field(
        description="Value of the direction on each of the five axes of the vocabulary of directions."
    )
    typicality: int = Field(
        ge=0,
        le=_MAX_DIRECTION_TYPICALITY,
        description=(
            "Estimate of the model, from 0 to 100, of how likely a designer asked the same question "
            "would propose this direction."
        ),
    )
    candidates: int = Field(
        ge=_MIN_DIRECTION_CANDIDATES,
        le=_MAX_DIRECTION_CANDIDATES,
        description=(
            "Number of candidate directions the model proposed, among which the Studio chose the "
            "two directions furthest from each other."
        ),
    )
    vocabulary_version: _Version = Field(
        description="Version of the vocabulary of directions that defines the axes and their values."
    )


class VisualLanguage(_Record):
    catalog_version: _Version = Field(description="Version of the visual catalog in use.")
    catalog_content_hash: Sha256 = Field(description="SHA-256 digest of the visual catalog.")
    choices: dict[str, str] = Field(
        description=(
            "Chosen value for every dimension of the visual catalog, such as hue_family or "
            "navigation; an open object that maps a dimension name to a value."
        )
    )
    product_name: str = Field(description="Product name shown in the mockup.")
    rationale: str = Field(description="Why this visual language was chosen.")
    palette: dict[str, str] = Field(
        description=(
            "Resolved colour of every palette role, such as primary or background; an open object "
            "that maps a role name to a lowercase hexadecimal colour."
        )
    )
    tokens: dict[str, str] = Field(
        description=(
            "CSS custom properties derived from the choices, such as --vl-color-primary; an open "
            "object that maps a property name to its CSS value."
        )
    )
    twin_fit: list[TwinFit] = Field(
        description="How the visual language suits each user twin, at most once per twin."
    )
    direction: Annotated[VisualDirection | None, _OPTIONAL] = Field(
        default=None,
        description=(
            "Art direction of the alternative, proposed by the model and chosen by the Studio so "
            "that the two alternatives differ; left out when the alternative has none."
        ),
    )


class DesignAlternative(_Record):
    id: Uuid = Field(description="Stable identifier of the design alternative.")
    code: str = Field(
        pattern=_code("DES"), description="Human-readable code of the alternative, like DES-001."
    )
    approach: Annotated[Annotated[DesignApproach, _BY_VALUE] | None, _OPTIONAL] = Field(
        default=None,
        description="High-level strategy of the alternative, left out when it has none.",
    )
    title: str = Field(description="Short title of the alternative.")
    summary: str = Field(description="Summary of the alternative.")
    rationale: str = Field(description="Why the alternative answers the requirements.")
    requirement_ids: list[Uuid] = Field(description="Requirements the alternative covers.")
    user_story_ids: list[Uuid] = Field(description="User stories the alternative covers.")
    acceptance_criterion_ids: list[Uuid] = Field(
        description="Acceptance criteria the alternative covers."
    )
    user_twin_references: list[UserTwinReference] = Field(
        description="User twins the alternative is designed for."
    )
    workflows: list[DesignWorkflow] = Field(description="Workflows of the alternative.")
    information_architecture: list[str] = Field(
        description="Main areas of the information architecture."
    )
    accessibility_considerations: list[str] = Field(description="Accessibility decisions.")
    security_considerations: list[str] = Field(description="Security and privacy decisions.")
    advantages: list[str] = Field(description="Strengths of the alternative.")
    trade_offs: list[str] = Field(description="Costs and weaknesses of the alternative.")
    assumptions: list[str] = Field(description="Assumptions the alternative relies on.")
    open_questions: list[str] = Field(description="Questions still open for the alternative.")
    visual_language: Annotated[VisualLanguage | None, _OPTIONAL] = Field(
        default=None,
        description="Visual language of the alternative, left out when it has none.",
    )


class DesignCritique(_Record):
    model_config = ConfigDict(
        json_schema_extra={"dependentRequired": {"quote": ["verdict"], "verdict": ["quote"]}}
    )

    id: Uuid = Field(description="Stable identifier of the critique.")
    code: str = Field(
        pattern=_code("CRQ"), description="Human-readable code of the critique, like CRQ-001."
    )
    kind: Annotated[DesignCritiqueKind, _BY_VALUE] = Field(
        description="Kind of critique; every critique is synthetic user twin feedback."
    )
    design_alternative_id: Uuid = Field(description="Design alternative that is criticized.")
    user_twin_reference: UserTwinReference = Field(description="User twin that wrote the critique.")
    strengths: list[str] = Field(description="What works for the user twin.")
    concerns: list[str] = Field(description="What worries the user twin.")
    unmet_needs: list[str] = Field(description="Needs of the user twin left unanswered.")
    accessibility_observations: list[str] = Field(description="Accessibility remarks.")
    trust_concerns: list[str] = Field(description="Reasons the user twin might not trust it.")
    questions: list[str] = Field(description="Questions the user twin asks.")
    suggested_changes: list[str] = Field(description="Changes the user twin suggests.")
    provenance: list[EvidenceReference] = Field(description="Sources the critique relies on.")
    confidence: _Confidence = Field(description="Model confidence, between 0 and 1.")
    epistemic_status: Annotated[EpistemicStatus, _BY_VALUE] = Field(
        description="Epistemic status of the critique, a model inference."
    )
    human_validation: Annotated[HumanValidationRequirement, _BY_VALUE] = Field(
        description="Whether a person still has to validate the critique."
    )
    rationale: str = Field(description="Reasoning behind the critique.")
    verdict: Annotated[_Verdict | None, _OPTIONAL] = Field(
        default=None,
        description=(
            "Short verdict of the user twin on the alternative, written together with quote; "
            "both are left out when the twin gave none."
        ),
    )
    quote: Annotated[_Quote | None, _OPTIONAL] = Field(
        default=None,
        description=(
            "Sentence in which the user twin states the verdict in its own words, written "
            "together with verdict; both are left out when the twin gave none."
        ),
    )

    @model_validator(mode="after")
    def _verdict_with_quote(self) -> DesignCritique:
        if (self.verdict is None) != (self.quote is None):
            raise ValueError("verdict and quote are written together or both left out")
        return self


class PrototypeElement(_Record):
    id: Uuid = Field(description="Stable identifier of the element.")
    code: str = Field(
        pattern=_code("ELM"), description="Human-readable code of the element, like ELM-001."
    )
    kind: Annotated[PrototypeElementKind, _BY_VALUE] = Field(
        description="Trusted primitive used to render the element."
    )
    content: str = Field(description="Visible content of the element.")
    accessible_name: str | None = Field(
        description="Accessible name, required for interactive elements, otherwise possibly null."
    )
    requirement_ids: list[Uuid] = Field(description="Requirements the element traces to.")
    user_story_ids: list[Uuid] = Field(description="User stories the element traces to.")
    acceptance_criterion_ids: list[Uuid] = Field(
        description="Acceptance criteria the element traces to."
    )
    field_name: str | None = Field(
        description="Form field name of an input or select element, otherwise null."
    )
    required: bool = Field(description="True when an input element must be filled in.")
    options: list[str] = Field(description="Choices of a select element, otherwise empty.")


class PrototypeScreen(_Record):
    id: Uuid = Field(description="Stable identifier of the screen.")
    code: str = Field(
        pattern=_code("SCR"), description="Human-readable code of the screen, like SCR-001."
    )
    title: str = Field(description="Title of the screen.")
    state: Annotated[PrototypeScreenState, _BY_VALUE] = Field(
        description="Representative state the screen shows."
    )
    elements: list[PrototypeElement] = Field(description="Elements of the screen, in order.")
    requirement_ids: list[Uuid] = Field(description="Requirements the screen traces to.")
    user_story_ids: list[Uuid] = Field(description="User stories the screen traces to.")
    acceptance_criterion_ids: list[Uuid] = Field(
        description="Acceptance criteria the screen traces to."
    )


class PrototypeTransition(_Record):
    id: Uuid = Field(description="Stable identifier of the transition.")
    code: str = Field(
        pattern=_code("TRN"), description="Human-readable code of the transition, like TRN-001."
    )
    source_screen_id: Uuid = Field(description="Screen the transition starts from.")
    trigger_element_id: Uuid = Field(
        description="Interactive element of the source screen that triggers the transition."
    )
    target_screen_id: Uuid = Field(description="Screen the transition leads to.")
    outcome: str = Field(description="What happens when the transition runs.")


class DeclarativePrototype(_Record):
    id: Uuid = Field(description="Stable identifier of the mockup.")
    code: str = Field(
        pattern=_code("PRT"), description="Human-readable code of the mockup, like PRT-001."
    )
    title: str = Field(description="Title of the mockup.")
    design_alternative_id: Uuid = Field(
        description="Owner-selected design alternative the mockup represents."
    )
    entry_screen_id: Uuid = Field(description="Screen shown first.")
    screens: list[PrototypeScreen] = Field(description="Screens in code order.")
    transitions: list[PrototypeTransition] = Field(description="Transitions in code order.")
    supported_viewports: list[Annotated[PrototypeViewport, _BY_VALUE]] = Field(
        description="Viewports the mockup supports, in alphabetical order."
    )


class DesignConcern(_Record):
    id: Uuid = Field(description="Stable identifier of the concern.")
    code: str = Field(
        pattern=_code("DRK"), description="Human-readable code of the concern, like DRK-001."
    )
    summary: str = Field(description="What the concern is about.")
    mitigation: str = Field(description="How the concern is mitigated.")
    requirement_ids: list[Uuid] = Field(description="Requirements the concern affects.")
    design_alternative_ids: list[Uuid] = Field(
        description="Design alternatives the concern affects."
    )


class GeneratedMockupScreen(_Record):
    code: str = Field(
        pattern=_MOCKUP_SCREEN_CODE_PATTERN,
        description="Code of the screen, SCR-001 for the first and then without gaps.",
    )
    title: str = Field(
        min_length=1, max_length=MAX_TITLE_LENGTH, description="Title of the screen."
    )
    state: Annotated[PrototypeScreenState, _BY_VALUE] = Field(
        description="Representative state the screen shows."
    )
    markup: str = Field(
        max_length=MAX_MARKUP_LENGTH,
        description=(
            "HTML fragment of the screen in the stored form of the mockup contract: only the "
            "allowed elements and attributes, links only to #SCR-nnn of this mockup, no script, "
            "no style attribute, no event handler and no address of another origin."
        ),
    )


class GeneratedMockup(_Record):
    contract_version: Literal[MOCKUP_CONTRACT_VERSION] = Field(
        description="Version of the contract of the generated mockup."
    )
    design_alternative_id: Uuid = Field(
        description="Owner-selected design alternative the mockup represents."
    )
    title: str = Field(
        min_length=1, max_length=MAX_TITLE_LENGTH, description="Title of the mockup."
    )
    styles: str = Field(
        max_length=MAX_STYLES_LENGTH,
        description=(
            "CSS of the mockup without comments; colours and fonts come only from the --vl-* "
            "tokens of the visual language of the alternative."
        ),
    )
    screens: list[GeneratedMockupScreen] = Field(
        min_length=MIN_SCREENS, max_length=MAX_SCREENS, description="Screens in code order."
    )


class BoundGeneratedMockup(_Record):
    mockup: GeneratedMockup = Field(
        description="Mockup generated as HTML and CSS and validated by the Studio."
    )
    requirement_ids_by_code: dict[_MarkupRequirementCode, Uuid] = Field(
        json_schema_extra={"additionalProperties": False},
        description=(
            "Identifier of every requirement code that the data-req attributes of the markup "
            "name, keyed by code in code order."
        ),
    )


class DesignPackageSnapshot(_Record):
    schema_version: Literal[DESIGN_PACKAGE_SCHEMA_VERSION] = Field(
        description="Version of the design package format."
    )
    project_id: Uuid = Field(description="Project the design belongs to.")
    grounding: DesignGrounding = Field(description="Approved inputs the design is grounded on.")
    alternatives: list[DesignAlternative] = Field(description="Design alternatives in code order.")
    critiques: list[DesignCritique] = Field(
        description="One synthetic critique for every pair of alternative and user twin."
    )
    recommended_alternative_id: Uuid | None = Field(
        description="Alternative recommended by the designer agent, or null."
    )
    owner_selected_alternative_id: Uuid | None = Field(
        description="Alternative selected by the owner, or null before the selection."
    )
    prototype: DeclarativePrototype | None = Field(
        description="Declarative mockup of the selected alternative, or null when there is none."
    )
    concerns: list[DesignConcern] = Field(description="Design concerns in code order.")
    open_questions: list[str] = Field(description="Questions still open for the whole design.")
    generated_mockup: Annotated[BoundGeneratedMockup | None, _OPTIONAL] = Field(
        default=None,
        description=(
            "Mockup generated for the owner-selected alternative, bound to the identifiers of "
            "the requirements it names; the prototype is derived from it. Left out when the "
            "mockup is only the declarative prototype."
        ),
    )
    owner_assertions: Annotated[_OwnerAssertions | None, _OPTIONAL] = Field(
        default=None,
        description=(
            "Statements of the owner that the design must respect, in the order the owner gave "
            "them; left out when there is none."
        ),
    )
