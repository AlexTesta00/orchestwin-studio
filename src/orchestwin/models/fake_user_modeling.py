"""Deterministic fake adapter for User Modeling proposals."""

from __future__ import annotations

from dataclasses import replace
from typing import Final

from orchestwin.models.user_modeling import (
    PersonaProposalRequest,
    PersonaProposalResult,
    ProposedPersonaProfile,
    ProposedUserTwinProfile,
    UserModelingProposalIssueCode,
    UserModelingProposalProviderKind,
    UserModelingProposalStatus,
    UserTwinProposalRequest,
    UserTwinProposalResult,
)
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
    ObservationValue,
    ProfileObservation,
)
from orchestwin.twins.persona_candidates import (
    ProjectPersonaCandidate,
)
from orchestwin.twins.personas import (
    PersonaField,
    PersonaProfile,
    PersonaProfileVersion,
    create_proto_persona,
)
from orchestwin.twins.user_twins import (
    MAX_PROJECT_USER_TWINS,
    UserTwinField,
    UserTwinProfile,
    create_project_grounded_user_twin,
)

FAKE_USER_MODELING_PROVIDER_ID: Final = "fake-deterministic-user-modeling"
FAKE_USER_MODELING_PROVIDER_VERSION: Final = 1


class FakeDeterministicUserModelingAdapter:
    """Conservative local adapter with no network or model dependency."""

    async def propose_personas(
        self,
        request: PersonaProposalRequest,
    ) -> PersonaProposalResult:
        """Build inspectable proto-personas without behavioral invention."""
        issue = _persona_request_issue(request)

        if issue is not None:
            return _rejected_personas(issue)

        proposals = tuple(
            ProposedPersonaProfile(
                candidate_ordinal=(candidate.ordinal),
                candidate_content_hash=(candidate.content_hash),
                profile=(_build_proto_persona(candidate)),
            )
            for candidate in request.candidates
        )

        return PersonaProposalResult(
            status=(UserModelingProposalStatus.PROPOSED),
            provider_kind=(UserModelingProposalProviderKind.FAKE_DETERMINISTIC),
            provider_id=(FAKE_USER_MODELING_PROVIDER_ID),
            provider_version=(FAKE_USER_MODELING_PROVIDER_VERSION),
            proposals=proposals,
        )

    async def propose_user_twins(
        self,
        request: UserTwinProposalRequest,
    ) -> UserTwinProposalResult:
        """Build project-grounded twins from confirmed personas."""
        issue = _twin_request_issue(request)

        if issue is not None:
            return _rejected_twins(issue)

        proposals = tuple(
            ProposedUserTwinProfile(
                persona_id=(persona_version.persona_id),
                persona_version_number=(persona_version.version_number),
                persona_content_hash=(persona_version.content_hash),
                profile=(
                    _build_user_twin(
                        request=request,
                        persona_version=(persona_version),
                    )
                ),
            )
            for persona_version in request.persona_versions
        )

        return UserTwinProposalResult(
            status=(UserModelingProposalStatus.PROPOSED),
            provider_kind=(UserModelingProposalProviderKind.FAKE_DETERMINISTIC),
            provider_id=(FAKE_USER_MODELING_PROVIDER_ID),
            provider_version=(FAKE_USER_MODELING_PROVIDER_VERSION),
            proposals=proposals,
        )


def _persona_request_issue(
    request: PersonaProposalRequest,
) -> UserModelingProposalIssueCode | None:
    """Return the first expected persona-request problem."""
    if not request.candidates:
        return UserModelingProposalIssueCode.CANDIDATES_REQUIRED

    if len(request.candidates) > MAX_PROJECT_USER_TWINS:
        return UserModelingProposalIssueCode.CANDIDATE_LIMIT_EXCEEDED

    if any(candidate.project_id != request.project_id for candidate in request.candidates):
        return UserModelingProposalIssueCode.CANDIDATE_PROJECT_MISMATCH

    return None


def _twin_request_issue(
    request: UserTwinProposalRequest,
) -> UserModelingProposalIssueCode | None:
    """Return the first expected User Twin request problem."""
    personas = request.persona_versions

    if not personas:
        return UserModelingProposalIssueCode.PERSONAS_REQUIRED

    if len(personas) > MAX_PROJECT_USER_TWINS:
        return UserModelingProposalIssueCode.PERSONA_LIMIT_EXCEEDED

    if any(version.project_id != request.project_id for version in personas):
        return UserModelingProposalIssueCode.PERSONA_PROJECT_MISMATCH

    persona_ids = tuple(version.persona_id for version in personas)

    if len(persona_ids) != len(set(persona_ids)):
        return UserModelingProposalIssueCode.DUPLICATE_PERSONA

    if any(not version.profile.ready_for_twin_creation for version in personas):
        return UserModelingProposalIssueCode.PERSONA_NOT_CONFIRMED

    return None


def _build_proto_persona(
    candidate: ProjectPersonaCandidate,
) -> PersonaProfile:
    """Create one complete but conservative proto-persona."""
    return create_proto_persona(
        name=candidate.target_user,
        observations=(
            candidate.role_observation,
            _persona_summary(candidate),
            _persona_abstention(
                candidate,
                field=PersonaField.GOALS,
                reason=(
                    "The approved Project Brief "
                    "does not provide goal-specific "
                    "evidence for this target-user role."
                ),
            ),
            _persona_abstention(
                candidate,
                field=(PersonaField.CONTEXT_OF_USE),
                reason=(
                    "The approved Project Brief "
                    "does not provide sufficient "
                    "context-of-use evidence for "
                    "this target-user role."
                ),
            ),
        ),
    )


def _persona_summary(
    candidate: ProjectPersonaCandidate,
) -> ProfileObservation:
    """Create only a descriptive summary of the supplied role."""
    return ProfileObservation(
        observation_key=(PersonaField.SUMMARY.observation_key),
        value=(
            ObservationValue.from_text(
                f"Project-specific proto-persona for the target-user role {candidate.target_user}."
            )
        ),
        epistemic_status=(EpistemicStatus.MODEL_INFERRED),
        confidence=ConfidenceScore(1.0),
        provenance=(
            _candidate_provenance(
                candidate,
                locator=("persona.summary"),
            )
        ),
        human_validation=(HumanValidationRequirement.REQUIRED),
        rationale=(
            "The summary only reformulates "
            "the target-user role supplied "
            "in the approved Project Brief."
        ),
    )


def _persona_abstention(
    candidate: ProjectPersonaCandidate,
    *,
    field: PersonaField,
    reason: str,
) -> ProfileObservation:
    """Create one explicit proto-persona abstention."""
    return ProfileObservation(
        observation_key=(field.observation_key),
        value=(ObservationValue.abstained(reason)),
        epistemic_status=(EpistemicStatus.MODEL_INFERRED),
        confidence=ConfidenceScore(0.0),
        provenance=(
            _candidate_provenance(
                candidate,
                locator=(f"persona.{field.value}"),
            )
        ),
        human_validation=(HumanValidationRequirement.REQUIRED),
        rationale=(
            "The deterministic fake adapter "
            "abstains because no field-specific "
            "evidence is available."
        ),
    )


def _candidate_provenance(
    candidate: ProjectPersonaCandidate,
    *,
    locator: str,
) -> ObservationProvenance:
    """Combine exact Project Brief evidence with fake-output provenance."""
    return ObservationProvenance.from_references(
        (
            *candidate.role_observation.provenance.references,
            EvidenceReference(
                source_kind=(EvidenceSourceKind.MODEL_OUTPUT),
                source_id=(FAKE_USER_MODELING_PROVIDER_ID),
                source_version=(FAKE_USER_MODELING_PROVIDER_VERSION),
                locator=locator,
                summary=("Deterministic fake User Modeling output."),
            ),
        )
    )


def _build_user_twin(
    *,
    request: UserTwinProposalRequest,
    persona_version: PersonaProfileVersion,
) -> UserTwinProfile:
    """Create a grounded twin while abstaining beyond persona evidence."""
    persona = persona_version.profile

    role = persona.observation_for(PersonaField.ROLE)
    goals = persona.observation_for(PersonaField.GOALS)
    context = persona.observation_for(PersonaField.CONTEXT_OF_USE)
    age_range = persona.observation_for(PersonaField.AGE_RANGE)

    if role is None or goals is None or context is None:
        raise ValueError("confirmed persona is missing required grounding observations")

    transferred = {
        UserTwinField.ROLE: (
            _rekey_observation(
                role,
                UserTwinField.ROLE,
            )
        ),
        UserTwinField.GOALS: (
            _rekey_observation(
                goals,
                UserTwinField.GOALS,
            )
        ),
        UserTwinField.CONTEXT_OF_USE: (
            _rekey_observation(
                context,
                UserTwinField.CONTEXT_OF_USE,
            )
        ),
    }

    if age_range is not None:
        transferred[UserTwinField.AGE_RANGE] = _rekey_observation(
            age_range,
            UserTwinField.AGE_RANGE,
        )

    observations = tuple(
        transferred[field]
        if field in transferred
        else _twin_abstention(
            persona_version=(persona_version),
            field=field,
        )
        for field in UserTwinField
        if (field is not UserTwinField.AGE_RANGE or field in transferred)
    )

    return create_project_grounded_user_twin(
        name=(f"{persona.name} Twin"),
        persona_version=(persona_version),
        project_brief_reference=(request.project_brief_reference),
        agent_team_reference=(request.agent_team_reference),
        catalog_version=(request.catalog_version),
        catalog_content_hash=(request.catalog_content_hash),
        observations=observations,
    )


def _rekey_observation(
    observation: ProfileObservation,
    field: UserTwinField,
) -> ProfileObservation:
    """Transfer persona evidence without changing its epistemic meaning."""
    return replace(
        observation,
        observation_key=(field.observation_key),
    )


def _twin_abstention(
    *,
    persona_version: PersonaProfileVersion,
    field: UserTwinField,
) -> ProfileObservation:
    """Create one explicit abstention for unsupported twin information."""
    return ProfileObservation(
        observation_key=(field.observation_key),
        value=(
            ObservationValue.abstained(
                "The confirmed persona and "
                "approved project context do not "
                "provide sufficient evidence "
                f"for {field.value}."
            )
        ),
        epistemic_status=(EpistemicStatus.MODEL_INFERRED),
        confidence=ConfidenceScore(0.0),
        provenance=(
            ObservationProvenance.from_references(
                (
                    EvidenceReference(
                        source_kind=(EvidenceSourceKind.SYSTEM_ARTIFACT),
                        source_id=str(persona_version.id),
                        source_version=(persona_version.version_number),
                        content_hash=(persona_version.content_hash),
                        locator=("persona_profile"),
                        summary=("Confirmed persona version grounding the User Twin."),
                    ),
                    EvidenceReference(
                        source_kind=(EvidenceSourceKind.MODEL_OUTPUT),
                        source_id=(FAKE_USER_MODELING_PROVIDER_ID),
                        source_version=(FAKE_USER_MODELING_PROVIDER_VERSION),
                        locator=(f"user_twin.{field.value}"),
                        summary=("Deterministic fake User Modeling output."),
                    ),
                )
            )
        ),
        human_validation=(HumanValidationRequirement.REQUIRED),
        rationale=(
            "The deterministic fake adapter "
            "abstains instead of inventing "
            "unsupported User Twin attributes."
        ),
    )


def _rejected_personas(
    issue: UserModelingProposalIssueCode,
) -> PersonaProposalResult:
    """Return one rejected persona proposal response."""
    return PersonaProposalResult(
        status=(UserModelingProposalStatus.REJECTED),
        provider_kind=(UserModelingProposalProviderKind.FAKE_DETERMINISTIC),
        provider_id=(FAKE_USER_MODELING_PROVIDER_ID),
        provider_version=(FAKE_USER_MODELING_PROVIDER_VERSION),
        issue=issue,
    )


def _rejected_twins(
    issue: UserModelingProposalIssueCode,
) -> UserTwinProposalResult:
    """Return one rejected User Twin proposal response."""
    return UserTwinProposalResult(
        status=(UserModelingProposalStatus.REJECTED),
        provider_kind=(UserModelingProposalProviderKind.FAKE_DETERMINISTIC),
        provider_id=(FAKE_USER_MODELING_PROVIDER_ID),
        provider_version=(FAKE_USER_MODELING_PROVIDER_VERSION),
        issue=issue,
    )
