"""Model-backed proposal ports with deterministic governance boundaries.

The model supplies semantic content. Catalog constraints, approved context and
human decision state remain authoritative application inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import wraps

from pydantic import BaseModel, ConfigDict, Field

from orchestwin.agents.catalog import AgentIdentifier
from orchestwin.agents.selection_rules import TeamRoleConstraintKind
from orchestwin.artifacts.architecture_packages import (
    ArchitecturePlanningPackage,
    create_architecture_grounding,
)
from orchestwin.artifacts.design_packages import DesignExplorationPackage, create_design_grounding
from orchestwin.models.architecture import (
    ArchitectureProposalProviderKind,
    ArchitectureProposalResult,
    ArchitectureProposalStatus,
)
from orchestwin.models.design import (
    DesignProposalProviderKind,
    DesignProposalResult,
    DesignProposalStatus,
)
from orchestwin.models.profile_drafts import UserTwinModelOutput
from orchestwin.models.proposal_evidence import (
    generation_output_reference,
    retain_adapter_result,
)
from orchestwin.models.proposal_generation import (
    ProposalGenerationError,
    ProposalGenerator,
    wire_value,
)
from orchestwin.models.requirements import (
    RequirementsProposalProviderKind,
    RequirementsProposalResult,
    RequirementsProposalStatus,
)
from orchestwin.models.team_proposals import (
    TEAM_PROPOSAL_SCHEMA_VERSION,
    AgentTeamProposal,
    ProposedTeamMember,
    TeamProposalGenerationResult,
    TeamProposalGenerationStatus,
    TeamProposalJustification,
    TeamProposalJustificationKind,
    TeamProposalMemberSource,
    TeamProposalProviderKind,
    deterministic_justification,
)
from orchestwin.models.user_modeling import (
    PersonaProposalResult,
    ProposedPersonaProfile,
    ProposedUserTwinProfile,
    UserModelingProposalProviderKind,
    UserModelingProposalStatus,
    UserTwinProposalResult,
)
from orchestwin.projects.requirements_specifications import RequirementsSpecification
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
    ProfileObservation,
)
from orchestwin.twins.user_twins import (
    MAX_PROJECT_USER_TWINS,
    ConfirmedPersonaReference,
    UserTwinLifecycleStatus,
    UserTwinProfile,
)


def _require(condition: bool):
    if not condition:
        raise ProposalGenerationError("INVALID_PROVIDER_OUTPUT")


def _model_boundary(function):
    @wraps(function)
    async def guarded(*args, **kwargs):
        try:
            result = await function(*args, **kwargs)
        except (ValueError, TypeError) as error:
            failure = ProposalGenerationError("INVALID_PROVIDER_OUTPUT")
            await retain_adapter_result(error=failure)
            raise failure from error
        except BaseException as error:
            await retain_adapter_result(error=error)
            raise
        await retain_adapter_result(result)
        return result

    return guarded


def _model_reference(generator, locator):
    generation = generation_output_reference()
    return EvidenceReference(
        source_kind=EvidenceSourceKind.MODEL_OUTPUT,
        source_id=generator.provider_id if generation is None else generation[0],
        source_version=1,
        locator=locator,
        content_hash=None if generation is None else generation[1],
    )


class _Suggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: AgentIdentifier
    rationale: str = Field(min_length=1, max_length=2000)


class TeamModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rationale: str = Field(min_length=1, max_length=2000)
    suggestions: list[_Suggestion] = Field(max_length=11)


@dataclass(frozen=True)
class PersonaModelOutput:
    proposals: tuple[ProposedPersonaProfile, ...]


class ModelTeamProposalAdapter:
    def __init__(self, generator: ProposalGenerator):
        self.generator = generator

    @_model_boundary
    async def propose(self, request):
        constraints = request.constraints
        if constraints.has_conflicts:
            return TeamProposalGenerationResult(
                status=TeamProposalGenerationStatus.BLOCKED_BY_CONSTRAINTS,
                issues=constraints.issues,
            )
        output = await self.generator.generate(
            task="team",
            context=request,
            output_type=TeamModelOutput,
            instruction=(
                "Explain the team selection and suggest only useful OPTIONAL roles from the "
                "supplied fixed catalog constraints. Mandatory roles are added by the application. "
                "Never suggest impossible, conflicting, mandatory or duplicate roles. "
                "Return suggestions=[] when no additional specialist is justified. "
                "Keep the overall rationale below 600 characters and each suggestion rationale "
                "below 400 characters. Explain optional-role choices in at most two short "
                "sentences; do not enumerate or reclassify mandatory roles."
            ),
        )
        suggestions = {item.agent_id: item for item in output.suggestions}
        _require(len(suggestions) == len(output.suggestions))
        allowed = {
            item.agent_id
            for item in constraints.role_constraints
            if item.kind is TeamRoleConstraintKind.OPTIONAL
        }
        _require(set(suggestions) <= allowed)
        members = []
        for constraint in constraints.role_constraints:
            if constraint.kind is TeamRoleConstraintKind.MANDATORY:
                members.append(
                    ProposedTeamMember(
                        agent_id=constraint.agent_id,
                        source=TeamProposalMemberSource.DETERMINISTIC_MANDATORY,
                        justifications=tuple(
                            deterministic_justification(reason) for reason in constraint.reasons
                        ),
                    )
                )
            elif constraint.agent_id in suggestions:
                members.append(
                    ProposedTeamMember(
                        agent_id=constraint.agent_id,
                        source=TeamProposalMemberSource.PROPOSER_SUGGESTED,
                        justifications=(
                            TeamProposalJustification(
                                kind=TeamProposalJustificationKind.PROPOSER_RATIONALE,
                                code="MODEL_RECOMMENDATION",
                                statement=suggestions[constraint.agent_id].rationale,
                            ),
                        ),
                    )
                )
        brief = request.brief_version
        try:
            proposal = AgentTeamProposal(
                schema_version=TEAM_PROPOSAL_SCHEMA_VERSION,
                provider_kind=TeamProposalProviderKind.MODEL_ADAPTER,
                provider_id=self.generator.provider_id,
                provider_version=1,
                project_id=brief.project_id,
                project_mode=request.project_mode,
                brief_version_id=brief.id,
                brief_version_number=brief.version_number,
                brief_content_hash=brief.content_hash,
                catalog_version=constraints.catalog_version,
                catalog_content_hash=constraints.catalog_content_hash,
                constraints=constraints,
                members=tuple(members),
            )
        except (ValueError, TypeError) as error:
            raise ProposalGenerationError("INVALID_PROVIDER_OUTPUT") from error
        return TeamProposalGenerationResult(
            status=TeamProposalGenerationStatus.PROPOSED, proposal=proposal
        )


class ModelRequirementsAdapter:
    def __init__(self, generator: ProposalGenerator):
        self.generator = generator

    @_model_boundary
    async def propose(self, request):
        _require(AgentIdentifier.REQUIREMENTS_ANALYST in request.team.selected_agent_ids)
        output = await self.generator.generate(
            task="requirements",
            context=request,
            output_type=RequirementsSpecification,
            instruction=(
                "Write requirements, user stories, acceptance criteria, scenarios, risks and "
                "Definition of Done grounded in the supplied brief and User Twins. "
                "Copy the exact project/context/catalog/twin references. Use unique UUIDs for "
                "new artifacts, canonical code ordering and internally resolving references. "
                "Do not invent source evidence or declare verification results."
            ),
        )
        _require(
            output.project_id == request.project_id
            and output.project_brief_reference == request.brief.reference
            and output.agent_team_reference == request.team.reference
            and output.user_modeling_reference == request.user_modeling.reference
            and output.catalog_version == request.catalog_version
            and output.catalog_content_hash == request.catalog_content_hash
            and output.user_twin_references == request.user_modeling.user_twin_references
        )
        # Domain validation resolves internal IDs; bind external evidence to this request too.
        from orchestwin.models.proposal_generation import wire_value
        from orchestwin.projects.requirements_primitives import RequirementSourceKind

        brief_fields = wire_value(request.brief)
        locators = {
            name
            for name, value in brief_fields.items()
            if isinstance(value, str) and value and name not in request.brief.unknown_fields
        }
        locators.update(
            f"{name}[{index}]"
            for name, values in brief_fields.items()
            if isinstance(values, list) and name != "unknown_fields"
            for index in range(len(values))
        )
        for item in (*output.requirements, *output.risks):
            for source in item.sources:
                if source.kind is RequirementSourceKind.PROJECT_BRIEF:
                    reference = request.brief.reference
                    _require(
                        source.source_id == str(reference.artifact_id)
                        and source.source_version == reference.version_number
                        and source.content_hash == reference.content_hash
                        and source.locator in locators
                    )
                elif source.kind is RequirementSourceKind.USER_TWIN:
                    _require(
                        any(
                            source.source_id == str(twin.twin_id)
                            and source.source_version == twin.version_number
                            and source.content_hash == twin.content_hash
                            and source.locator
                            in {item.observation_key for item in twin_input.observations}
                            for twin_input in request.user_modeling.user_twins
                            for twin in (twin_input.reference,)
                        )
                    )
                else:
                    _require(False)
        return RequirementsProposalResult(
            status=RequirementsProposalStatus.PROPOSED,
            provider_kind=RequirementsProposalProviderKind.MODEL_ADAPTER,
            provider_id=self.generator.provider_id,
            provider_version=1,
            specification=output,
        )


class ModelDesignAdapter:
    def __init__(self, generator: ProposalGenerator):
        self.generator = generator

    @_model_boundary
    async def propose(self, request):
        _require(AgentIdentifier.UX_UI_DESIGNER in request.team.selected_agent_ids)
        output = await self.generator.generate(
            task="design",
            context={
                "request": request,
                "grounding": create_design_grounding(request.requirements.version),
            },
            output_type=DesignExplorationPackage,
            instruction=(
                "Produce distinct traceable design alternatives and explicitly synthetic User Twin "
                "critiques. Copy the supplied grounding exactly. Include a recommendation, concerns "
                "and open questions. owner_selected_alternative_id and prototype must be null. "
                "Use unique UUIDs and canonical ordering; evidence references must resolve to "
                "the supplied observations. Never simulate an owner decision or empirical study."
            ),
        )
        _require(
            output.project_id == request.project_id
            and output.grounding == create_design_grounding(request.requirements.version)
            and output.owner_selected_alternative_id is None
            and output.prototype is None
        )
        critiques = []
        for critique in output.critiques:
            twin = next(
                item
                for item in request.user_modeling.user_twins
                if item.reference == critique.user_twin_reference
            )
            references = {
                reference
                for observation in twin.observations
                for reference in observation.provenance.references
            }
            _require(set(critique.provenance.references) <= references)
            critiques.append(
                replace(
                    critique,
                    provenance=ObservationProvenance.from_references(
                        (
                            *critique.provenance.references,
                            _model_reference(self.generator, critique.code),
                        )
                    ),
                )
            )
        output = replace(output, critiques=tuple(critiques))
        return DesignProposalResult(
            status=DesignProposalStatus.PROPOSED,
            provider_kind=DesignProposalProviderKind.MODEL_ADAPTER,
            provider_id=self.generator.provider_id,
            provider_version=1,
            package=output,
        )


class ModelArchitectureAdapter:
    def __init__(self, generator: ProposalGenerator):
        self.generator = generator

    @_model_boundary
    async def propose(self, request):
        _require(
            {AgentIdentifier.SOFTWARE_ARCHITECT, AgentIdentifier.QA_TEST_ENGINEER}
            <= set(request.team.selected_agent_ids)
            and request.design.ready_for_architecture
        )
        grounding = create_architecture_grounding(request.design.version)
        output = await self.generator.generate(
            task="architecture",
            context={"request": request, "grounding": grounding},
            output_type=ArchitecturePlanningPackage,
            instruction=(
                "Produce a concrete software architecture and planned tests for the approved "
                "design, prototype and requirements. Copy the supplied grounding exactly. "
                "Use unique UUIDs, canonical ordering and resolving component/test references. "
                "Tests are plans only; do not claim execution, passing checks or Level D evidence."
            ),
        )
        _require(output.project_id == request.project_id and output.grounding == grounding)
        return ArchitectureProposalResult(
            status=ArchitectureProposalStatus.PROPOSED,
            provider_kind=ArchitectureProposalProviderKind.MODEL_ADAPTER,
            provider_id=self.generator.provider_id,
            provider_version=1,
            package=output,
        )


class ModelUserModelingAdapter:
    def __init__(self, generator: ProposalGenerator):
        self.generator = generator

    def _profile(self, profile, available):
        """Only exact copied observations may retain pre-existing epistemic status."""
        references = {
            reference
            for observation in available
            for reference in observation.provenance.references
        }
        observations = []
        for observation in profile.observations:
            if observation in available:
                observations.append(observation)
                continue
            _require(
                observation.epistemic_status
                in {
                    EpistemicStatus.MODEL_INFERRED,
                    EpistemicStatus.UNSUPPORTED_ASSUMPTION,
                }
                and observation.human_validation is HumanValidationRequirement.REQUIRED
            )
            _require(set(observation.provenance.references) <= references)
            provenance = ObservationProvenance.from_references(
                (
                    *observation.provenance.references,
                    _model_reference(self.generator, observation.observation_key),
                )
            )
            observations.append(replace(observation, provenance=provenance))
        return replace(profile, observations=tuple(observations))

    @_model_boundary
    async def propose_personas(self, request):
        _require(
            1 <= len(request.candidates) <= MAX_PROJECT_USER_TWINS
            and all(item.project_id == request.project_id for item in request.candidates)
        )
        context = wire_value(request)
        for item, candidate in zip(context["candidates"], request.candidates, strict=True):
            item["candidate_content_hash"] = candidate.content_hash
        output = await self.generator.generate(
            task="personas",
            context=context,
            output_type=PersonaModelOutput,
            instruction=(
                "Propose one pending SYSTEM_PROPOSED PROTO_PERSONA per candidate, in input order, "
                "with exact candidate ordinal and candidate_content_hash copied from the input. "
                "Never calculate or invent hashes. Preserve the candidate role observation. "
                "Each profile MUST contain persona.role (TEXT), persona.summary (TEXT), "
                "persona.goals (ITEMS or UNKNOWN) and persona.context_of_use (TEXT or UNKNOWN), "
                "in exactly that order, with concise values. For UNKNOWN use reason=null, text=null "
                "and items=[]; explain uncertainty in rationale. Every new observation needs a nonempty rationale, confidence "
                "between 0 and 1, MODEL_INFERRED and human_validation=REQUIRED. "
                "New observations must be MODEL_INFERRED or UNSUPPORTED_ASSUMPTION and require "
                "human validation. Reuse only supplied evidence references; abstain when unknown. "
                "Do not create empirical, owner or human-review evidence."
            ),
        )
        _require(len(output.proposals) == len(request.candidates))
        proposals = []
        for proposed, candidate in zip(output.proposals, request.candidates, strict=True):
            _require(
                proposed.candidate_ordinal == candidate.ordinal
                and proposed.candidate_content_hash == candidate.content_hash
                and candidate.role_observation in proposed.profile.observations
            )
            proposals.append(
                replace(
                    proposed, profile=self._profile(proposed.profile, (candidate.role_observation,))
                )
            )
        return PersonaProposalResult(
            status=UserModelingProposalStatus.PROPOSED,
            provider_kind=UserModelingProposalProviderKind.MODEL_ADAPTER,
            provider_id=self.generator.provider_id,
            provider_version=1,
            proposals=tuple(proposals),
        )

    @_model_boundary
    async def propose_user_twins(self, request):
        personas = request.persona_versions
        _require(
            1 <= len(personas) <= MAX_PROJECT_USER_TWINS
            and len({item.persona_id for item in personas}) == len(personas)
            and all(
                item.project_id == request.project_id and item.profile.ready_for_twin_creation
                for item in personas
            )
        )
        context = wire_value(request)
        context["persona_references"] = [
            wire_value(ConfirmedPersonaReference.from_version(persona)) for persona in personas
        ]
        output = await self.generator.generate(
            task="user-twins",
            context=context,
            output_type=UserTwinModelOutput,
            instruction=(
                "Propose one User Twin content draft per confirmed persona, in input order. "
                "Return the exact persona_id, a name and observations. The application binds "
                "the exact project references, source provenance and MODEL_INFERRED status with "
                "required human review; do not output these metadata. Abstain when unknown; "
                "never invent empirical research or human approval. Required observation keys, in order: "
                "user_twin.role, user_twin.expertise, user_twin.goals, user_twin.recurring_tasks, "
                "user_twin.context_of_use, user_twin.information_needs, user_twin.decision_criteria, "
                "user_twin.preferred_vocabulary, user_twin.frustrations, user_twin.pain_points, "
                "user_twin.trust_concerns, user_twin.accessibility_needs, user_twin.operational_constraints, "
                "user_twin.technical_literacy, user_twin.risk_sensitivity, user_twin.assumptions. "
                "role must be TEXT; context_of_use, technical_literacy and risk_sensitivity use "
                "TEXT or UNKNOWN; other fields use ITEMS or UNKNOWN. Every inferred observation "
                "requires a concise rationale and confidence between 0 and 1. UNKNOWN uses "
                "reason=null, text=null and items=[]; explain uncertainty in rationale. Keep values and rationales very short."
            ),
        )
        _require(len(output.proposals) == len(personas))
        proposals = []
        for proposed, persona in zip(output.proposals, personas, strict=True):
            _require(proposed.persona_id == persona.persona_id)
            source = EvidenceReference(
                source_kind=EvidenceSourceKind.SYSTEM_ARTIFACT,
                source_id=f"persona:{persona.persona_id}",
                source_version=persona.version_number,
                content_hash=persona.content_hash,
                locator="profile",
                summary="Confirmed persona used as model context.",
            )
            profile = UserTwinProfile(
                name=proposed.name,
                persona_reference=ConfirmedPersonaReference.from_version(persona),
                project_brief_reference=request.project_brief_reference,
                agent_team_reference=request.agent_team_reference,
                catalog_version=request.catalog_version,
                catalog_content_hash=request.catalog_content_hash,
                validation_status=UserTwinLifecycleStatus.PROJECT_GROUNDED_UT,
                observations=tuple(
                    ProfileObservation(
                        observation_key=item.observation_key,
                        value=item.value,
                        confidence=ConfidenceScore(item.confidence),
                        rationale=item.rationale,
                        epistemic_status=EpistemicStatus.MODEL_INFERRED,
                        human_validation=HumanValidationRequirement.REQUIRED,
                        provenance=ObservationProvenance.from_references(
                            (source, _model_reference(self.generator, item.observation_key))
                        ),
                    )
                    for item in proposed.observations
                ),
            )
            proposals.append(
                ProposedUserTwinProfile(
                    persona_id=persona.persona_id,
                    persona_version_number=persona.version_number,
                    persona_content_hash=persona.content_hash,
                    profile=profile,
                )
            )
        return UserTwinProposalResult(
            status=UserModelingProposalStatus.PROPOSED,
            provider_kind=UserModelingProposalProviderKind.MODEL_ADAPTER,
            provider_id=self.generator.provider_id,
            provider_version=1,
            proposals=tuple(proposals),
        )
