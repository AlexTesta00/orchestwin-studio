"""Deterministic fake adapter for governed design proposals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid5

from orchestwin.agents.catalog import AgentIdentifier
from orchestwin.artifacts.design import (
    DesignAlternative,
    DesignApproach,
    DesignWorkflow,
    SyntheticDesignCritique,
    create_design_alternative,
    create_design_workflow,
    create_synthetic_design_critique,
)
from orchestwin.artifacts.design_packages import (
    DesignConcern,
    DesignExplorationPackage,
    create_design_concern,
    create_design_exploration_package,
    create_design_grounding,
)
from orchestwin.models.design import (
    DesignProposalIssueCode,
    DesignProposalProviderKind,
    DesignProposalRequest,
    DesignProposalResult,
    DesignProposalStatus,
    DesignUserTwinInput,
)
from orchestwin.projects.requirements import UserStory
from orchestwin.projects.requirements_primitives import UserTwinVersionReference
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    ObservationProvenance,
    ObservationValueKind,
    ProfileObservation,
)

FAKE_DESIGN_PROVIDER_ID: Final = "fake-deterministic-design"
FAKE_DESIGN_PROVIDER_VERSION: Final = 1

_FAKE_DESIGN_NAMESPACE: Final = UUID("f8b24be1-601c-4e35-90e6-996b8e27a0e7")
_MAX_TITLE_FRAGMENT_LENGTH: Final = 120
_MAX_CRITIQUE_CONTEXT_LENGTH: Final = 180


@dataclass(frozen=True, slots=True)
class _AlternativeTemplate:
    """Static content that keeps deterministic alternatives meaningfully distinct."""

    approach: DesignApproach
    title_prefix: str
    summary: str
    rationale: str
    information_architecture: tuple[str, ...]
    accessibility_considerations: tuple[str, ...]
    security_considerations: tuple[str, ...]
    advantages: tuple[str, ...]
    trade_offs: tuple[str, ...]
    open_question: str
    concern_summary: str
    concern_mitigation: str


_ALTERNATIVE_TEMPLATES: Final[tuple[_AlternativeTemplate, ...]] = (
    _AlternativeTemplate(
        approach=DesignApproach.GUIDED_WORKFLOW,
        title_prefix="Guided workflow",
        summary=(
            "Lead the user through an explicit sequence with progressive disclosure, "
            "review, and confirmation."
        ),
        rationale=(
            "Make task state and recovery points visible while reducing the amount of "
            "information presented at each step."
        ),
        information_architecture=(
            "Task entry",
            "Guided steps",
            "Review and confirmation",
        ),
        accessibility_considerations=(
            "Preserve a logical heading hierarchy and visible focus through every step.",
            "Announce progress, validation, and completion without relying on color alone.",
        ),
        security_considerations=(
            "Display only the project data required for the current guided step.",
            "Require explicit confirmation before committing a consequential action.",
        ),
        advantages=(
            "The current step and expected next action remain explicit.",
            "Progressive disclosure can reduce avoidable cognitive load.",
        ),
        trade_offs=(
            "Experienced users may need more navigation to complete frequent tasks.",
            "Interrupted workflows require clear save-and-resume behavior.",
        ),
        open_question=(
            "Which steps can be combined without hiding information needed for a safe decision?"
        ),
        concern_summary=("A guided flow may slow down users who repeatedly perform the same task."),
        concern_mitigation=(
            "Preserve keyboard-efficient navigation and evaluate optional shortcuts after owner "
            "selection."
        ),
    ),
    _AlternativeTemplate(
        approach=DesignApproach.DASHBOARD_FIRST,
        title_prefix="Operations dashboard",
        summary=(
            "Expose status, priorities, and contextual actions in one overview before the user "
            "opens a detailed task."
        ),
        rationale=(
            "Support rapid orientation and comparison when users coordinate several items or "
            "need to preserve operational context."
        ),
        information_architecture=(
            "Operational overview",
            "Priority work queue",
            "Contextual action panel",
            "Status and feedback",
        ),
        accessibility_considerations=(
            "Provide keyboard access and clear landmarks for every dashboard region.",
            "Expose status changes programmatically and never communicate priority by color alone.",
        ),
        security_considerations=(
            "Minimize sensitive details in overview summaries and reveal detail deliberately.",
            "Keep contextual actions scoped to the currently selected item.",
        ),
        advantages=(
            "Users can compare status and priorities without losing overview context.",
            "Frequent actions can remain available near the relevant information.",
        ),
        trade_offs=(
            "Higher information density may increase scanning and prioritization effort.",
            "Responsive layouts need an explicit strategy for smaller viewports.",
        ),
        open_question=(
            "Which status and priority information must remain visible before a task is opened?"
        ),
        concern_summary=(
            "A dashboard-first design may overload users when too many statuses compete for "
            "attention."
        ),
        concern_mitigation=(
            "Use a restrained default overview and validate prioritization rules before adding "
            "secondary information."
        ),
    ),
    _AlternativeTemplate(
        approach=DesignApproach.TASK_FOCUSED,
        title_prefix="Focused task workspace",
        summary=(
            "Center the interface on one primary task with inline guidance, validation, and a "
            "concise completion summary."
        ),
        rationale=(
            "Reduce competing navigation and keep the information required for the selected task "
            "close to the related action."
        ),
        information_architecture=(
            "Primary task workspace",
            "Inline guidance and validation",
            "Completion summary",
        ),
        accessibility_considerations=(
            "Keep labels, instructions, and errors persistently associated with their controls.",
            "Move focus predictably when validation or completion feedback appears.",
        ),
        security_considerations=(
            "Exclude unrelated sensitive context from the active task workspace.",
            "Avoid echoing protected values in validation and completion messages.",
        ),
        advantages=(
            "The primary task remains visually and semantically dominant.",
            "Inline feedback can shorten recovery from incomplete or invalid input.",
        ),
        trade_offs=(
            "Users may need additional navigation to understand wider project status.",
            "A narrowly focused workspace may hide useful cross-task dependencies.",
        ),
        open_question=(
            "Which surrounding context is essential enough to remain visible in the focused "
            "workspace?"
        ),
        concern_summary=(
            "A task-focused design may conceal dependencies outside the current workspace."
        ),
        concern_mitigation=(
            "Surface concise dependency notices and provide an explicit route to broader context."
        ),
    ),
)


class FakeDeterministicDesignAdapter:
    """Conservative local provider with no network or credential dependency."""

    async def propose(
        self,
        request: DesignProposalRequest,
    ) -> DesignProposalResult:
        """Produce deterministic alternatives and synthetic User Twin critiques."""
        if AgentIdentifier.UX_UI_DESIGNER not in request.team.selected_agent_ids:
            return _rejected(DesignProposalIssueCode.UX_DESIGNER_REQUIRED)

        if not _has_grounded_input(request):
            return _rejected(DesignProposalIssueCode.GROUNDED_INPUT_REQUIRED)

        try:
            package = _build_package(request)
        except ValueError:
            return _rejected(DesignProposalIssueCode.INVALID_PROVIDER_OUTPUT)

        return DesignProposalResult(
            status=DesignProposalStatus.PROPOSED,
            provider_kind=DesignProposalProviderKind.FAKE_DETERMINISTIC,
            provider_id=FAKE_DESIGN_PROVIDER_ID,
            provider_version=FAKE_DESIGN_PROVIDER_VERSION,
            package=package,
        )


def _has_grounded_input(request: DesignProposalRequest) -> bool:
    """Require concrete Requirements and at least one supported observation per twin."""
    specification = request.requirements.version.specification

    has_requirements_baseline = bool(
        specification.requirements
        and specification.user_stories
        and specification.acceptance_criteria
    )
    has_grounded_twins = all(
        any(_is_grounded_observation(observation) for observation in twin.observations)
        for twin in request.user_modeling.user_twins
    )

    return has_requirements_baseline and has_grounded_twins


def _is_grounded_observation(observation: ProfileObservation) -> bool:
    """Return whether an observation contains usable, non-assumptive profile content."""
    return (
        observation.value.kind in {ObservationValueKind.TEXT, ObservationValueKind.ITEMS}
        and observation.epistemic_status is not EpistemicStatus.UNSUPPORTED_ASSUMPTION
    )


def _build_package(request: DesignProposalRequest) -> DesignExplorationPackage:
    """Build a complete unselected Design Package from exact governed inputs."""
    request_hash = request.content_hash
    specification = request.requirements.version.specification
    requirement_ids = tuple(requirement.id for requirement in specification.requirements)
    user_story_ids = tuple(story.id for story in specification.user_stories)
    criterion_ids = tuple(criterion.id for criterion in specification.acceptance_criteria)
    twin_references = request.user_modeling.user_twin_references

    alternatives = tuple(
        _build_alternative(
            request_hash=request_hash,
            template=template,
            ordinal=ordinal,
            stories=specification.user_stories,
            requirement_ids=requirement_ids,
            user_story_ids=user_story_ids,
            criterion_ids=criterion_ids,
            twin_references=twin_references,
        )
        for ordinal, template in enumerate(_ALTERNATIVE_TEMPLATES, start=1)
    )

    critiques = tuple(
        _build_critique(
            request=request,
            request_hash=request_hash,
            template=template,
            alternative=alternative,
            twin=twin,
            ordinal=(alternative_index * len(request.user_modeling.user_twins) + twin_index + 1),
        )
        for alternative_index, (template, alternative) in enumerate(
            zip(_ALTERNATIVE_TEMPLATES, alternatives, strict=True)
        )
        for twin_index, twin in enumerate(request.user_modeling.user_twins)
    )

    concerns = tuple(
        _build_concern(
            request_hash=request_hash,
            template=template,
            alternative=alternative,
            ordinal=ordinal,
            requirement_ids=requirement_ids,
        )
        for ordinal, (template, alternative) in enumerate(
            zip(_ALTERNATIVE_TEMPLATES, alternatives, strict=True),
            start=1,
        )
    )

    return create_design_exploration_package(
        project_id=request.project_id,
        grounding=create_design_grounding(request.requirements.version),
        alternatives=alternatives,
        critiques=critiques,
        recommended_alternative_id=alternatives[0].id,
        concerns=concerns,
        open_questions=(
            "Which proposed direction should the owner select for declarative prototyping?",
            "Which trade-offs require validation with target users before implementation?",
        ),
    )


def _build_alternative(
    *,
    request_hash: str,
    template: _AlternativeTemplate,
    ordinal: int,
    stories: tuple[UserStory, ...],
    requirement_ids: tuple[UUID, ...],
    user_story_ids: tuple[UUID, ...],
    criterion_ids: tuple[UUID, ...],
    twin_references: tuple[UserTwinVersionReference, ...],
) -> DesignAlternative:
    """Create one traceable alternative from a distinct interaction strategy."""
    primary_goal = _bounded_fragment(
        stories[0].goal,
        maximum_length=_MAX_TITLE_FRAGMENT_LENGTH,
    )
    workflows = tuple(
        _build_workflow(
            request_hash=request_hash,
            template=template,
            story=story,
            ordinal=story_ordinal,
        )
        for story_ordinal, story in enumerate(stories, start=1)
    )

    return create_design_alternative(
        alternative_id=_artifact_id(
            request_hash,
            "alternative",
            template.approach.value,
        ),
        code=f"DES-{ordinal:03d}",
        approach=template.approach,
        title=f"{template.title_prefix}: {primary_goal}",
        summary=template.summary,
        rationale=template.rationale,
        requirement_ids=requirement_ids,
        user_story_ids=user_story_ids,
        acceptance_criterion_ids=criterion_ids,
        user_twin_references=twin_references,
        workflows=workflows,
        information_architecture=template.information_architecture,
        accessibility_considerations=template.accessibility_considerations,
        security_considerations=template.security_considerations,
        advantages=template.advantages,
        trade_offs=template.trade_offs,
        open_questions=(template.open_question,),
    )


def _build_workflow(
    *,
    request_hash: str,
    template: _AlternativeTemplate,
    story: UserStory,
    ordinal: int,
) -> DesignWorkflow:
    """Create one approach-specific workflow for an approved user story."""
    goal = _bounded_fragment(
        story.goal,
        maximum_length=_MAX_TITLE_FRAGMENT_LENGTH,
    )

    return create_design_workflow(
        workflow_id=_artifact_id(
            request_hash,
            "workflow",
            f"{template.approach.value}:{story.id}",
        ),
        code=f"FLOW-{ordinal:03d}",
        title=f"{template.title_prefix}: {goal}",
        steps=_workflow_steps(template.approach, story),
        requirement_ids=story.requirement_ids,
        user_story_ids=(story.id,),
    )


def _workflow_steps(
    approach: DesignApproach,
    story: UserStory,
) -> tuple[str, ...]:
    """Return visibly different task sequencing for each design approach."""
    if approach is DesignApproach.GUIDED_WORKFLOW:
        return (
            f"Open the guided sequence for {story.code}.",
            "Collect only the information required by the current step.",
            "Review linked requirements before confirming the outcome.",
        )

    if approach is DesignApproach.DASHBOARD_FIRST:
        return (
            "Review current status and priorities in the operational overview.",
            f"Open the contextual action panel for {story.code}.",
            "Complete the linked actions while preserving overview context.",
            "Return to the overview with updated status and feedback.",
        )

    return (
        f"Open the focused workspace for {story.code}.",
        "Complete the information required by the linked requirements.",
        "Resolve inline validation feedback in the same workspace.",
        "Confirm the expected outcome and review the completion summary.",
    )


def _build_critique(
    *,
    request: DesignProposalRequest,
    request_hash: str,
    template: _AlternativeTemplate,
    alternative: DesignAlternative,
    twin: DesignUserTwinInput,
    ordinal: int,
) -> SyntheticDesignCritique:
    """Create one explicitly synthetic critique for one alternative/twin pair."""
    context = _twin_context(twin)

    return create_synthetic_design_critique(
        critique_id=_artifact_id(
            request_hash,
            "critique",
            (f"{template.approach.value}:{twin.reference.twin_id}:{twin.reference.version_number}"),
        ),
        code=f"CRQ-{ordinal:03d}",
        design_alternative_id=alternative.id,
        user_twin_reference=twin.reference,
        strengths=(
            (
                f"The {template.approach.value.casefold().replace('_', ' ')} direction "
                "keeps every proposed workflow linked to approved requirements and user stories."
            ),
        ),
        concerns=(
            f"The main trade-off remains hypothetical for {twin.reference.name}: "
            f"{template.trade_offs[0]}",
        ),
        unmet_needs=_unmet_needs(twin),
        accessibility_observations=(template.accessibility_considerations[0],),
        trust_concerns=(
            "The proposal does not establish how real users will interpret or trust this design.",
        ),
        questions=(
            (
                f"During human validation, does this direction support {twin.reference.name} "
                f"without contradicting the approved profile context: {context}?"
            ),
        ),
        suggested_changes=(template.concern_mitigation,),
        provenance=_critique_provenance(
            request=request,
            twin=twin,
            alternative_code=alternative.code,
        ),
        confidence=ConfidenceScore(0.6),
        rationale=(
            "This deterministic critique translates approved User Twin observations into a "
            "design hypothesis. It is simulated feedback, not empirical evidence."
        ),
    )


def _unmet_needs(twin: DesignUserTwinInput) -> tuple[str, ...]:
    """Expose profile gaps without inventing missing user needs."""
    return tuple(
        (
            f"The approved profile does not provide concrete content for "
            f"{observation.observation_key}."
        )
        for observation in twin.observations
        if observation.value.kind
        in {
            ObservationValueKind.UNKNOWN,
            ObservationValueKind.ABSTAINED,
        }
    )


def _twin_context(twin: DesignUserTwinInput) -> str:
    """Return a bounded supported observation for a human-validation question."""
    observation = next(value for value in twin.observations if _is_grounded_observation(value))

    if observation.value.kind is ObservationValueKind.TEXT:
        content = observation.value.text or twin.reference.name
    else:
        content = observation.value.items[0]

    return _bounded_fragment(
        content,
        maximum_length=_MAX_CRITIQUE_CONTEXT_LENGTH,
    )


def _critique_provenance(
    *,
    request: DesignProposalRequest,
    twin: DesignUserTwinInput,
    alternative_code: str,
) -> ObservationProvenance:
    """Preserve User Twin evidence and add explicit fake-provider provenance."""
    references: list[EvidenceReference] = []

    for observation in twin.observations:
        for reference in observation.provenance.references:
            if reference not in references:
                references.append(reference)

    for reference, summary in (
        (request.requirements.reference, "Approved Requirements baseline used by design."),
        (request.team.reference, "Approved Agent Team used by design."),
        (request.user_modeling.reference, "Approved User Modeling state used by design."),
    ):
        evidence = EvidenceReference(
            source_kind=EvidenceSourceKind.SYSTEM_ARTIFACT,
            source_id=str(reference.artifact_id),
            source_version=reference.version_number,
            content_hash=reference.content_hash,
            locator=reference.kind.value.casefold(),
            summary=summary,
        )

        if evidence not in references:
            references.append(evidence)

    references.append(
        EvidenceReference(
            source_kind=EvidenceSourceKind.MODEL_OUTPUT,
            source_id=FAKE_DESIGN_PROVIDER_ID,
            source_version=FAKE_DESIGN_PROVIDER_VERSION,
            locator=(
                f"alternatives.{alternative_code}.user_twins."
                f"{twin.reference.twin_id}.v{twin.reference.version_number}"
            ),
            summary="Deterministic synthetic design critique generated from governed inputs.",
        )
    )

    return ObservationProvenance.from_references(references)


def _build_concern(
    *,
    request_hash: str,
    template: _AlternativeTemplate,
    alternative: DesignAlternative,
    ordinal: int,
    requirement_ids: tuple[UUID, ...],
) -> DesignConcern:
    """Create one explicit review concern for each design direction."""
    return create_design_concern(
        concern_id=_artifact_id(
            request_hash,
            "concern",
            template.approach.value,
        ),
        code=f"DRK-{ordinal:03d}",
        summary=template.concern_summary,
        mitigation=template.concern_mitigation,
        requirement_ids=requirement_ids,
        design_alternative_ids=(alternative.id,),
    )


def _bounded_fragment(
    value: str,
    *,
    maximum_length: int,
) -> str:
    """Keep supplied normalized text safe for bounded generated fields."""
    if len(value) <= maximum_length:
        return value

    return f"{value[: maximum_length - 3].rstrip()}..."


def _artifact_id(
    request_hash: str,
    artifact_kind: str,
    identity: str,
) -> UUID:
    """Derive a stable UUID from exact request content and logical identity."""
    return uuid5(
        _FAKE_DESIGN_NAMESPACE,
        f"{request_hash}:{artifact_kind}:{identity}",
    )


def _rejected(issue: DesignProposalIssueCode) -> DesignProposalResult:
    """Return one typed deterministic rejection."""
    return DesignProposalResult(
        status=DesignProposalStatus.REJECTED,
        provider_kind=DesignProposalProviderKind.FAKE_DETERMINISTIC,
        provider_id=FAKE_DESIGN_PROVIDER_ID,
        provider_version=FAKE_DESIGN_PROVIDER_VERSION,
        issue=issue,
    )


__all__ = [
    "FAKE_DESIGN_PROVIDER_ID",
    "FAKE_DESIGN_PROVIDER_VERSION",
    "FakeDeterministicDesignAdapter",
]
