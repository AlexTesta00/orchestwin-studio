from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Annotated, Final, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    Strict,
    ValidationError,
    model_validator,
)
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue
from pydantic_core import core_schema

from orchestwin.agents.catalog import AgentIdentifier
from orchestwin.agents.proposals import TeamProposalRevisionKind
from orchestwin.agents.selection_rules import (
    TeamRoleConstraintKind,
    TeamSelectionIssueCode,
    TeamSelectionReasonCode,
)
from orchestwin.artifacts.design import (
    MAX_CRITIQUE_QUOTE_LENGTH,
    MAX_CRITIQUE_VERDICT_LENGTH,
    DesignApproach,
    DesignCritiqueKind,
)
from orchestwin.artifacts.design_discussion import (
    PROPOSAL_CODE_PREFIX,
    DiscussionProposalTarget,
    DiscussionStance,
    DiscussionStatus,
    ReactionVerdict,
)
from orchestwin.artifacts.design_evaluation import DESIGN_EVALUATION_SCHEMA_VERSION
from orchestwin.artifacts.design_finding_validations import FindingDecision
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
from orchestwin.evaluation.artifacts import EvaluationArtifactModality
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
)
from orchestwin.knowledge.diagrams import DiagramKind
from orchestwin.knowledge.feedback import DISCUSSIONS_KIND, INSIGHTS_KIND, REVIEWS_KIND
from orchestwin.knowledge.layout import (
    FEEDBACK_CHANGES,
    FEEDBACK_DISCUSSIONS,
    FEEDBACK_FOLDER,
    FEEDBACK_INSIGHTS,
    FEEDBACK_REVIEWS,
    KNOWLEDGE_FOLDER_KIND,
    KNOWLEDGE_INDEX,
    KNOWLEDGE_MANIFEST,
    KNOWLEDGE_SCHEMA_VERSION,
    STAGES,
    STATE_DOCUMENT,
    SUPPORTED_SCHEMA_VERSIONS,
    TWIN_DOCUMENT_KIND,
    TWIN_FOLDER,
    schema_document,
    stage_document,
    twin_document,
)
from orchestwin.knowledge.state import (
    CHANGE_REVIEWS_KIND,
    CRITIQUE_VERDICTS,
    DECISIONS,
    FILE_KINDS,
    MAX_ACTION_LENGTH,
    MAX_AUTHOR_LENGTH,
    MAX_COMMIT_LENGTH,
    MAX_DESIGN_REQUEST_LENGTH,
    MAX_FILES,
    MAX_FINDING_LENGTH,
    MAX_FINDINGS,
    MAX_MESSAGE_LENGTH,
    MAX_MODEL_TASKS,
    MAX_NOTE_LENGTH,
    MAX_PATH_LENGTH,
    MAX_REQUIREMENTS_REQUEST_LENGTH,
    MAX_SUMMARY_LENGTH,
    MAX_TASK_LENGTH,
    MIN_COMMIT_LENGTH,
    SEVERITIES,
    STATE_KIND,
    TASK_STATUSES,
    VERDICTS,
)
from orchestwin.models.team_proposals import (
    TEAM_PROPOSAL_SCHEMA_VERSION,
    TeamProposalJustificationKind,
    TeamProposalMemberSource,
    TeamProposalProviderKind,
)
from orchestwin.projects.briefs import BriefField, ProjectBrief
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.insight_applications import InsightSourceKind, InsightTarget
from orchestwin.projects.requirements import RequirementKind, RequirementPriority
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementSourceKind,
)
from orchestwin.projects.requirements_quality import (
    DefinitionOfDoneApplicability,
    RiskImpact,
    RiskLikelihood,
    RiskReviewStatus,
    VerificationMethod,
)
from orchestwin.projects.requirements_specifications import (
    REQUIREMENTS_SPECIFICATION_SCHEMA_VERSION,
)
from orchestwin.twins.epistemics import (
    EpistemicStatus,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationValueKind,
)
from orchestwin.twins.personas import (
    PERSONA_PROFILE_SCHEMA_VERSION,
    PersonaConfirmationStatus,
    PersonaKind,
    PersonaSource,
)
from orchestwin.twins.user_twins import (
    USER_MODELING_SNAPSHOT_SCHEMA_VERSION,
    USER_TWIN_PROFILE_SCHEMA_VERSION,
    UserTwinLifecycleStatus,
)
from orchestwin.workflow.gates import HumanGateStatus, HumanGateType

SCHEMA_NAMES: Final = (
    "manifest",
    "brief",
    "team",
    "twins",
    "twin",
    "requirements",
    "design",
    "reviews",
    "discussions",
    "insights",
    "state",
    "changes",
)
SCHEMA_DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"
MAX_DOCUMENT_DEPTH: Final = 64
_SCHEMA_ID_PREFIX: Final = f"urn:orchestwin:knowledge-folder:{KNOWLEDGE_SCHEMA_VERSION}"
_FINDING_CONFIDENCE_SEMANTICS: Final = "MODEL_SELF_ASSESSMENT_UNLESS_CALIBRATED"
_BRIEF_SCHEMA_VERSION: Final = ProjectBrief.SCHEMA_VERSION

_UUID_PATTERN: Final = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_SHA256_PATTERN: Final = r"^[0-9a-f]{64}$"
_TIMESTAMP_PATTERN: Final = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?"
    r"(Z|[+-][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{1,6})?)?)$"
)
_OBSERVATION_KEY_PATTERN: Final = r"^[a-z][a-z0-9_.-]{0,127}$"
_TWIN_OBSERVATION_KEY_PATTERN: Final = r"^user_twin\.[a-z_]+$"
_JUSTIFICATION_CODE_PATTERN: Final = r"^[A-Z][A-Z0-9_]{0,127}$"
_IDENTIFIER_KIND_PATTERN: Final = r"^[A-Z][A-Z_]*$"
_ANY_CODE_PATTERN: Final = r"^[A-Z]+-[0-9]{3,6}$"
_SLUG_PATTERN: Final = r"^[a-z0-9]+(-[a-z0-9]+)*$"
_SCHEMA_PATH_PATTERN: Final = r"^schema/[a-z]+\.schema\.json$"
_MOCKUP_SCREEN_CODE_PATTERN: Final = r"^SCR-[0-9]{3}$"
_MARKUP_REQUIREMENT_CODE_PATTERN: Final = r"^[A-Z]{2,5}-[0-9]{3}$"
_COMMIT_PATTERN: Final = rf"^[0-9a-f]{{{MIN_COMMIT_LENGTH},{MAX_COMMIT_LENGTH}}}$"
_LOCALE_PATTERN: Final = r"^[a-z]{2,3}(-[A-Z]{2})?$"
_STAGE_ORDER: Final = {"twins": ["team"], "requirements": ["twins"], "design": ["requirements"]}
_MANIFEST_VERSION_RULES: Final = {
    "allOf": [
        {
            "if": {"properties": {"schema_version": {"const": 2}}, "required": ["schema_version"]},
            "then": {"properties": {"stages": {"required": list(STAGES)}}},
        },
        {
            "if": {"properties": {"schema_version": {"const": 3}}, "required": ["schema_version"]},
            "then": {
                "required": ["progress", "state"],
                "properties": {"feedback": {"required": ["changes", "change_reviews"]}},
            },
        },
    ]
}
_DESIGN_ADDITIONS: Final = {
    "DesignCritique": ("verdict", "quote"),
    "DesignPackageSnapshot": ("generated_mockup", "owner_assertions"),
}
_DESIGN_ADDITION_KEYWORDS: Final = {"DesignCritique": ("dependentRequired",)}
_DEFINITION_PREFIX: Final = "#/$defs/"


def _code(prefix: str) -> str:
    return rf"^{prefix}-[0-9]{{3,6}}$"


def _never_null(value: object) -> object:
    if value is None:
        raise ValueError("an optional property is left out when it has no value, never null")
    return value


type Uuid = Annotated[
    str,
    Field(
        pattern=_UUID_PATTERN,
        description="Canonical lowercase UUID in the 8-4-4-4-12 hexadecimal form.",
    ),
]
type Sha256 = Annotated[
    str,
    Field(
        pattern=_SHA256_PATTERN,
        description="SHA-256 digest written as 64 lowercase hexadecimal characters.",
    ),
]
type Timestamp = Annotated[
    str,
    Field(
        pattern=_TIMESTAMP_PATTERN,
        description=(
            "Timezone-aware ISO 8601 date and time as written by Python's datetime.isoformat, "
            "for example 2026-09-27T18:00:00+00:00."
        ),
    ),
]
type CommitHash = Annotated[
    str,
    Field(
        pattern=_COMMIT_PATTERN,
        description=(
            f"Hash of a git commit written as {MIN_COMMIT_LENGTH} to {MAX_COMMIT_LENGTH} "
            "lowercase hexadecimal characters."
        ),
    ),
]

_BY_VALUE: Final = Strict(False)
_OPTIONAL: Final = BeforeValidator(_never_null)
_Version = Annotated[int, Field(ge=1)]
_Count = Annotated[int, Field(ge=0)]
_Confidence = Annotated[float, Field(ge=0, le=1)]
_AnyCode = Annotated[str, Field(pattern=_ANY_CODE_PATTERN)]
_BriefFieldName = Annotated[BriefField, _BY_VALUE]
_Verdict = Annotated[str, Field(min_length=1, max_length=MAX_CRITIQUE_VERDICT_LENGTH)]
_Quote = Annotated[str, Field(min_length=1, max_length=MAX_CRITIQUE_QUOTE_LENGTH)]
_OwnerAssertion = Annotated[str, Field(min_length=1, max_length=MAX_OWNER_ASSERTION_LENGTH)]
_OwnerAssertions = Annotated[
    list[_OwnerAssertion], Field(min_length=1, max_length=MAX_OWNER_ASSERTIONS)
]
_MarkupRequirementCode = Annotated[str, Field(pattern=_MARKUP_REQUIREMENT_CODE_PATTERN)]
_RequirementCode = Annotated[str, Field(pattern=_code("REQ"))]
_ScreenCode = Annotated[str, Field(pattern=_code("SCR"))]
_TaskCode = Annotated[str, Field(pattern=_code("TSK"))]
_AlternativeCode = Annotated[str, Field(pattern=_code("DES"))]
_Summary = Annotated[str, Field(max_length=MAX_SUMMARY_LENGTH)]
_TaskText = Annotated[str, Field(min_length=1, max_length=MAX_TASK_LENGTH)]
_ChangedPath = Annotated[str, Field(min_length=1, max_length=MAX_PATH_LENGTH)]


class KnowledgeSchemaError(Exception):
    def __init__(
        self,
        *,
        code: str,
        document: str,
        location: str = "",
        message: str = "",
        path: str | None = None,
    ) -> None:
        subject = document if path is None else f"{document} ({path})"
        where = f"{subject} at {location}" if location else subject
        super().__init__(f"{code}: {where}: {message}" if message else f"{code}: {where}")
        self.code = code
        self.document = document
        self.location = location
        self.message = message
        self.path = path


class _KnowledgeJsonSchema(GenerateJsonSchema):
    def default_schema(self, schema: core_schema.WithDefaultSchema) -> JsonSchemaValue:
        inner = schema["schema"]
        while inner["type"] in {"function-before", "nullable"}:
            inner = inner["schema"]
        return self.generate_inner(inner)

    def field_title_should_be_set(self, schema: object) -> bool:
        return False


class _Record(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)


class CatalogReference(_Record):
    version: _Version = Field(description="Version of the fixed agent catalog that was used.")
    content_hash: Sha256 = Field(description="SHA-256 digest of that agent catalog.")


class ArtifactReference(_Record):
    artifact_id: Uuid = Field(description="Identifier of the referenced artifact version.")
    version_number: _Version = Field(description="Version number of the referenced artifact.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the referenced artifact content.")


class ApprovedVersionReference(_Record):
    version_id: Uuid = Field(description="Identifier of the approved version.")
    version_number: _Version = Field(description="Version number of the approved artifact.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the approved artifact content.")


class UserTwinReference(_Record):
    twin_id: Uuid = Field(description="Stable identifier of the user twin across its versions.")
    version_number: _Version = Field(description="Version of the user twin that is referenced.")
    content_hash: Sha256 = Field(description="SHA-256 digest of that user twin version.")
    name: str = Field(description="Display name of the user twin at that version.")


class EvidenceReference(_Record):
    source_kind: Annotated[EvidenceSourceKind, _BY_VALUE] = Field(
        description="Category of the source that supports the statement."
    )
    source_id: str = Field(description="Identifier of the source, such as an artifact identifier.")
    source_version: _Version | None = Field(
        description="Version of the source, or null when the source has no version."
    )
    content_hash: Sha256 | None = Field(
        description="SHA-256 digest of the source content, or null when it is not known."
    )
    locator: str | None = Field(
        description="Position inside the source, such as a field name, or null."
    )
    summary: str | None = Field(description="Short summary of what the source says, or null.")


class ObservationValue(_Record):
    kind: Annotated[ObservationValueKind, _BY_VALUE] = Field(
        description="Shape of the value: one text, a list of items, unknown or an abstention."
    )
    text: str | None = Field(description="The value when kind is TEXT, otherwise null.")
    items: list[str] = Field(description="The values when kind is ITEMS, otherwise empty.")
    reason: str | None = Field(
        description="Why the model abstained when kind is ABSTAINED, otherwise null."
    )


class ProfileObservation(_Record):
    observation_key: str = Field(
        pattern=_OBSERVATION_KEY_PATTERN,
        description="Stable key of the profile field, such as persona.goals or user_twin.goals.",
    )
    value: ObservationValue = Field(description="Observed value of the profile field.")
    epistemic_status: Annotated[EpistemicStatus, _BY_VALUE] = Field(
        description="How the value is known, from owner input to unsupported assumption."
    )
    confidence: _Confidence = Field(description="Confidence in the value, between 0 and 1.")
    provenance: list[EvidenceReference] = Field(
        description="Sources that support the value, in the order they were given."
    )
    human_validation: Annotated[HumanValidationRequirement, _BY_VALUE] = Field(
        description="Whether a person still has to validate the value."
    )
    rationale: str | None = Field(
        description="Reasoning behind an inferred or assumed value, or null."
    )


class PersonaProfile(_Record):
    schema_version: Literal[PERSONA_PROFILE_SCHEMA_VERSION] = Field(
        description="Version of the persona profile format."
    )
    name: str = Field(description="Display name of the persona.")
    source: Annotated[PersonaSource, _BY_VALUE] = Field(
        description="Whether the owner provided the persona or the system proposed it."
    )
    kind: Annotated[PersonaKind, _BY_VALUE] = Field(
        description="Whether the profile is an owner persona or a proto-persona."
    )
    confirmation_status: Annotated[PersonaConfirmationStatus, _BY_VALUE] = Field(
        description="Owner confirmation state of the persona."
    )
    rejection_reason: str | None = Field(
        description="Why the owner rejected the persona, or null when it was not rejected."
    )
    observations: list[ProfileObservation] = Field(
        description="Fields of the persona with their epistemic metadata."
    )


class PersonaVersion(_Record):
    id: Uuid = Field(description="Identifier of this persona version.")
    project_id: Uuid = Field(description="Project the persona belongs to.")
    persona_id: Uuid = Field(description="Stable identifier of the persona across its versions.")
    version_number: _Version = Field(description="Version number of the persona.")
    based_on_version_number: _Version | None = Field(
        description="Version that this version revises, or null for the first version."
    )
    content_hash: Sha256 = Field(description="SHA-256 digest of the persona profile.")
    profile: PersonaProfile = Field(description="Content of the persona at this version.")
    created_by_user_id: Uuid = Field(description="User who created this version.")
    created_at: Timestamp = Field(description="When this version was created.")


class PersonaReference(_Record):
    persona_id: Uuid = Field(description="Stable identifier of the persona.")
    version_number: _Version = Field(description="Confirmed persona version the twin uses.")
    content_hash: Sha256 = Field(description="SHA-256 digest of that persona version.")
    source: Annotated[PersonaSource, _BY_VALUE] = Field(
        description="Whether the owner provided the persona or the system proposed it."
    )
    kind: Annotated[PersonaKind, _BY_VALUE] = Field(
        description="Whether the persona is an owner persona or a proto-persona."
    )
    confirmation_status: Annotated[PersonaConfirmationStatus, _BY_VALUE] = Field(
        description="Confirmation state of the persona, always confirmed for a twin."
    )


class UserTwinProfile(_Record):
    schema_version: Literal[USER_TWIN_PROFILE_SCHEMA_VERSION] = Field(
        description="Version of the user twin profile format."
    )
    name: str = Field(description="Display name of the user twin.")
    persona_reference: PersonaReference = Field(
        description="Confirmed persona version the twin is grounded on."
    )
    project_brief_reference: ArtifactReference = Field(
        description="Approved project brief version the twin was built from."
    )
    agent_team_reference: ArtifactReference = Field(
        description="Approved agent team version the twin was built with."
    )
    catalog: CatalogReference = Field(description="Agent catalog used when the twin was built.")
    validation_status: Annotated[UserTwinLifecycleStatus, _BY_VALUE] = Field(
        description="Lifecycle and validation state of the twin."
    )
    requires_human_validation: bool = Field(
        description="True when at least one observation still needs human validation."
    )
    observations: list[ProfileObservation] = Field(
        description="Fields of the twin, such as role, goals and frustrations, in canonical order."
    )


class UserTwinVersion(_Record):
    id: Uuid = Field(description="Identifier of this user twin version.")
    project_id: Uuid = Field(description="Project the user twin belongs to.")
    twin_id: Uuid = Field(description="Stable identifier of the user twin across its versions.")
    version_number: _Version = Field(description="Version number of the user twin.")
    based_on_version_number: _Version | None = Field(
        description="Version that this version revises, or null for the first version."
    )
    content_hash: Sha256 = Field(description="SHA-256 digest of the user twin profile.")
    profile: UserTwinProfile = Field(description="Content of the user twin at this version.")
    created_by_user_id: Uuid = Field(description="User who created this version.")
    created_at: Timestamp = Field(description="When this version was created.")


class UserModelingSnapshot(_Record):
    schema_version: Literal[USER_MODELING_SNAPSHOT_SCHEMA_VERSION] = Field(
        description="Version of the user modeling snapshot format."
    )
    project_id: Uuid = Field(description="Project the personas and twins belong to.")
    project_brief_reference: ArtifactReference = Field(
        description="Approved project brief version every twin was built from."
    )
    agent_team_reference: ArtifactReference = Field(
        description="Approved agent team version every twin was built with."
    )
    catalog: CatalogReference = Field(description="Agent catalog shared by every twin.")
    persona_versions: list[PersonaVersion] = Field(
        description="One confirmed persona version for each twin, ordered by persona identifier."
    )
    twin_versions: list[UserTwinVersion] = Field(
        description="User twin versions ordered by twin identifier."
    )


class BriefFieldValues(_Record):
    name: str | None = Field(description="Project name, or null when not provided.")
    description: str | None = Field(
        description="Short description of the project, or null when not provided."
    )
    problem: str | None = Field(
        description="Problem the project solves, or null when not provided."
    )
    goals: list[str] | None = Field(description="Project goals, or null when not provided.")
    target_users: list[str] | None = Field(
        description="Intended users of the product, or null when not provided."
    )
    domain: str | None = Field(
        description="Application domain of the project, or null when not provided."
    )
    technical_constraints: list[str] | None = Field(
        description="Technical constraints, or null when not provided."
    )
    temporal_constraints: str | None = Field(
        description="Deadlines and time constraints, or null when not provided."
    )
    budget: str | None = Field(description="Budget of the project, or null when not provided.")
    functional_requirements: list[str] | None = Field(
        description="Functional requirements stated by the owner, or null when not provided."
    )
    non_functional_requirements: list[str] | None = Field(
        description="Non-functional requirements stated by the owner, or null when not provided."
    )
    risks: list[str] | None = Field(
        description="Risks known to the owner, or null when not provided."
    )
    stakeholders: list[str] | None = Field(
        description="Stakeholders of the project, or null when not provided."
    )
    available_artifacts: list[str] | None = Field(
        description="Existing material the project can reuse, or null when not provided."
    )
    definition_of_done: list[str] | None = Field(
        description="Owner's conditions for calling the project done, or null when not provided."
    )


class BriefSnapshot(_Record):
    schema_version: Literal[_BRIEF_SCHEMA_VERSION] = Field(
        description="Version of the project brief format."
    )
    fields: BriefFieldValues = Field(
        description="Owner's answer for every brief field; a field is null when not provided."
    )
    unknown_fields: list[_BriefFieldName] = Field(
        description="Fields the owner explicitly marked as unknown, in alphabetical order."
    )


class ProposalProvider(_Record):
    kind: Annotated[TeamProposalProviderKind, _BY_VALUE] = Field(
        description="Kind of adapter that produced the proposal."
    )
    provider_id: str = Field(description="Identifier of the adapter that produced the proposal.")
    provider_version: _Version = Field(description="Version of that adapter.")


class BriefVersionReference(_Record):
    id: Uuid = Field(description="Identifier of the approved project brief version.")
    version_number: _Version = Field(description="Version number of the project brief.")
    content_hash: Sha256 = Field(description="SHA-256 digest of that project brief version.")


class RuleEvidence(_Record):
    fields: list[_BriefFieldName] = Field(
        description="Brief fields whose text activated the rule, in brief order."
    )
    terms: list[str] = Field(
        description="Normalized terms found in those fields, in alphabetical order."
    )


class SelectionReason(_Record):
    code: Annotated[TeamSelectionReasonCode, _BY_VALUE] = Field(
        description="Deterministic selection rule that produced the constraint."
    )
    evidence: RuleEvidence = Field(
        description="Brief evidence that activated the rule, empty for rules that always apply."
    )


class RoleConstraint(_Record):
    agent_id: Annotated[AgentIdentifier, _BY_VALUE] = Field(
        description="Catalog agent the constraint applies to."
    )
    kind: Annotated[TeamRoleConstraintKind, _BY_VALUE] = Field(
        description="Whether the agent is mandatory, optional, impossible or in conflict."
    )
    owner_editable: bool = Field(description="True when the owner may add or remove the agent.")
    reasons: list[SelectionReason] = Field(
        description="Rules behind the constraint, empty for an optional agent."
    )


class SelectionIssue(_Record):
    code: Annotated[TeamSelectionIssueCode, _BY_VALUE] = Field(
        description="Kind of contradiction that the owner has to resolve."
    )
    agent_id: Annotated[AgentIdentifier, _BY_VALUE] = Field(
        description="Catalog agent affected by the contradiction."
    )


class TeamConstraints(_Record):
    catalog_version: _Version = Field(description="Version of the fixed agent catalog.")
    catalog_content_hash: Sha256 = Field(description="SHA-256 digest of the agent catalog.")
    project_mode: Annotated[ProjectMode, _BY_VALUE] = Field(
        description="Intake mode of the project the constraints were computed for."
    )
    role_constraints: list[RoleConstraint] = Field(
        description="One constraint for every catalog agent, in catalog order."
    )
    issues: list[SelectionIssue] = Field(
        description="Contradictions between brief signals, empty when there is none."
    )


class MemberJustification(_Record):
    kind: Annotated[TeamProposalJustificationKind, _BY_VALUE] = Field(
        description="Whether the justification is a deterministic rule or a written rationale."
    )
    code: str = Field(
        pattern=_JUSTIFICATION_CODE_PATTERN,
        description="Stable uppercase code of the justification.",
    )
    evidence_fields: list[_BriefFieldName] = Field(
        description="Brief fields that support the justification, in brief order."
    )
    evidence_terms: list[str] = Field(
        description="Normalized terms that support the justification, in alphabetical order."
    )
    statement: str | None = Field(
        description="Rationale written by the proposer or the owner, null for a rule."
    )


class TeamMember(_Record):
    agent_id: Annotated[AgentIdentifier, _BY_VALUE] = Field(
        description="Catalog agent selected for the team."
    )
    source: Annotated[TeamProposalMemberSource, _BY_VALUE] = Field(
        description="Whether a rule, the proposer or the owner put the agent in the team."
    )
    justifications: list[MemberJustification] = Field(
        description="Reasons for including the agent."
    )


class TeamProposalSnapshot(_Record):
    schema_version: Literal[TEAM_PROPOSAL_SCHEMA_VERSION] = Field(
        description="Version of the agent team proposal format."
    )
    provider: ProposalProvider = Field(description="Adapter that produced the proposal.")
    project_id: Uuid = Field(description="Project the team belongs to.")
    project_mode: Annotated[ProjectMode, _BY_VALUE] = Field(
        description="Intake mode of the project."
    )
    brief_version: BriefVersionReference = Field(
        description="Approved project brief version the proposal answers."
    )
    catalog: CatalogReference = Field(description="Agent catalog the members come from.")
    constraints: TeamConstraints = Field(
        description="Deterministic role constraints derived from the brief."
    )
    constraints_content_hash: Sha256 = Field(description="SHA-256 digest of the role constraints.")
    members: list[TeamMember] = Field(description="Selected agents, in catalog order.")


class RequirementsContextReference(_Record):
    kind: Annotated[RequirementsContextKind, _BY_VALUE] = Field(
        description="Which governed input the reference points to."
    )
    artifact_id: Uuid = Field(description="Identifier of the referenced version.")
    version_number: _Version = Field(description="Version number of the referenced input.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the referenced input.")


class RequirementsContext(_Record):
    project_brief: RequirementsContextReference = Field(
        description="Approved project brief version the requirements are grounded on."
    )
    agent_team: RequirementsContextReference = Field(
        description="Approved agent team version that produced the requirements."
    )
    user_modeling: RequirementsContextReference = Field(
        description="Approved user modeling version the requirements are grounded on."
    )
    catalog: CatalogReference = Field(description="Agent catalog in use.")


class RequirementSource(_Record):
    kind: Annotated[RequirementSourceKind, _BY_VALUE] = Field(
        description="Category of the source that supports the item."
    )
    source_id: str = Field(description="Identifier of the source.")
    source_version: _Version | None = Field(
        description="Version of the source, or null when the source has no version."
    )
    content_hash: Sha256 | None = Field(
        description="SHA-256 digest of the source content, or null when it is not known."
    )
    locator: str | None = Field(
        description="Position inside the source, such as a brief field, or null."
    )


class Requirement(_Record):
    id: Uuid = Field(description="Stable identifier of the requirement.")
    code: str = Field(
        pattern=_code("REQ"), description="Human-readable code of the requirement, like REQ-001."
    )
    title: str = Field(description="Short title of the requirement.")
    statement: str = Field(description="Full statement of the requirement.")
    kind: Annotated[RequirementKind, _BY_VALUE] = Field(
        description="Whether the requirement is functional, non-functional or a constraint."
    )
    priority: Annotated[RequirementPriority, _BY_VALUE] = Field(
        description="MoSCoW priority of the requirement."
    )
    sources: list[RequirementSource] = Field(description="Sources the requirement comes from.")
    user_twin_references: list[UserTwinReference] = Field(
        description="User twins whose needs the requirement serves."
    )


class UserStory(_Record):
    id: Uuid = Field(description="Stable identifier of the user story.")
    code: str = Field(
        pattern=_code("USR"), description="Human-readable code of the user story, like USR-001."
    )
    user_twin_reference: UserTwinReference = Field(description="User twin the story is told for.")
    goal: str = Field(description="What the user wants to do.")
    benefit: str = Field(description="Why the user wants it.")
    requirement_ids: list[Uuid] = Field(description="Requirements the story belongs to.")


class AcceptanceCriterion(_Record):
    id: Uuid = Field(description="Stable identifier of the acceptance criterion.")
    code: str = Field(
        pattern=_code("AC"), description="Human-readable code of the criterion, like AC-001."
    )
    statement: str = Field(description="Verifiable condition the product must meet.")
    verification_method: Annotated[VerificationMethod, _BY_VALUE] = Field(
        description="How the condition is verified."
    )
    requirement_ids: list[Uuid] = Field(description="Requirements the criterion verifies.")
    user_story_ids: list[Uuid] = Field(description="User stories the criterion verifies.")


class UsageScenario(_Record):
    id: Uuid = Field(description="Stable identifier of the scenario.")
    code: str = Field(
        pattern=_code("SCN"), description="Human-readable code of the scenario, like SCN-001."
    )
    title: str = Field(description="Short title of the scenario.")
    actor: UserTwinReference = Field(description="User twin who plays the scenario.")
    preconditions: list[str] = Field(description="Conditions true before the scenario starts.")
    trigger: str = Field(description="Event that starts the scenario.")
    steps: list[str] = Field(description="Ordered steps of the scenario.")
    expected_outcome: str = Field(description="Result expected at the end of the scenario.")
    requirement_ids: list[Uuid] = Field(description="Requirements the scenario exercises.")
    acceptance_criterion_ids: list[Uuid] = Field(
        description="Acceptance criteria the scenario exercises."
    )


class ProjectRisk(_Record):
    id: Uuid = Field(description="Stable identifier of the risk.")
    code: str = Field(
        pattern=_code("RSK"), description="Human-readable code of the risk, like RSK-001."
    )
    summary: str = Field(description="What could go wrong.")
    likelihood: Annotated[RiskLikelihood, _BY_VALUE] = Field(description="How likely the risk is.")
    impact: Annotated[RiskImpact, _BY_VALUE] = Field(description="How severe the risk would be.")
    mitigation: str = Field(description="How the risk is reduced.")
    requirement_ids: list[Uuid] = Field(description="Requirements affected by the risk.")
    sources: list[RequirementSource] = Field(description="Sources the risk comes from.")
    review_status: Annotated[RiskReviewStatus, _BY_VALUE] = Field(
        description="Owner review state of the risk."
    )


class DefinitionOfDoneItem(_Record):
    id: Uuid = Field(description="Stable identifier of the item.")
    code: str = Field(
        pattern=_code("DOD"), description="Human-readable code of the item, like DOD-001."
    )
    statement: str = Field(description="Completion condition of the project.")
    verification_method: Annotated[VerificationMethod, _BY_VALUE] = Field(
        description="How the condition is verified."
    )
    applicability: Annotated[DefinitionOfDoneApplicability, _BY_VALUE] = Field(
        description="Whether the condition always applies or only under a condition."
    )
    condition: str | None = Field(
        description="When a conditional item applies, or null for a required item."
    )
    requirement_ids: list[Uuid] = Field(description="Requirements the item refers to.")


class RequirementsSpecificationSnapshot(_Record):
    schema_version: Literal[REQUIREMENTS_SPECIFICATION_SCHEMA_VERSION] = Field(
        description="Version of the requirements specification format."
    )
    project_id: Uuid = Field(description="Project the specification belongs to.")
    context: RequirementsContext = Field(
        description="Approved inputs the specification is grounded on."
    )
    user_twin_references: list[UserTwinReference] = Field(
        description="User twin versions the specification serves."
    )
    requirements: list[Requirement] = Field(description="Requirements in code order.")
    user_stories: list[UserStory] = Field(description="User stories in code order.")
    acceptance_criteria: list[AcceptanceCriterion] = Field(
        description="Acceptance criteria in code order."
    )
    scenarios: list[UsageScenario] = Field(description="Usage scenarios in code order.")
    risks: list[ProjectRisk] = Field(description="Project risks in code order.")
    definition_of_done: list[DefinitionOfDoneItem] = Field(
        description="Definition of done items in code order."
    )


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


class _StageDocument(_Record):
    id: Uuid = Field(description="Identifier of the approved version.")
    project_id: Uuid = Field(description="Project the version belongs to.")
    version_number: _Version = Field(description="Version number of the stage artifact.")
    content_hash: Sha256 = Field(
        description="SHA-256 digest of the stage content approved at the human gate."
    )
    created_by_user_id: Uuid = Field(description="User who created the version.")
    created_at: Timestamp = Field(description="When the version was created.")


class _RevisedStageDocument(_StageDocument):
    based_on_version_number: Annotated[_Version | None, _OPTIONAL] = Field(
        default=None,
        description="Earlier version that this version revises, left out when there is none.",
    )


class BriefDocument(_StageDocument):
    brief: BriefSnapshot = Field(description="Content of the approved project brief.")


class TeamDocument(_RevisedStageDocument):
    revision_kind: Annotated[TeamProposalRevisionKind, _BY_VALUE] = Field(
        description="Whether the proposer generated the version or the owner edited it."
    )
    proposal: TeamProposalSnapshot = Field(description="Content of the approved team proposal.")


class TwinsDocument(_RevisedStageDocument):
    snapshot: UserModelingSnapshot = Field(
        description="Content of the approved user modeling: personas and user twins."
    )


class RequirementsDocument(_RevisedStageDocument):
    specification: RequirementsSpecificationSnapshot = Field(
        description="Content of the approved requirements specification."
    )


class DesignDocument(_RevisedStageDocument):
    package: DesignPackageSnapshot = Field(description="Content of the approved design package.")


class TwinOrigin(_Record):
    project_id: Uuid = Field(description="Project the twin comes from.")
    project_name: str = Field(description="Name of that project.")
    user_modeling: ApprovedVersionReference = Field(
        description="Approved user modeling version that contains the twin."
    )
    approved_at: Timestamp = Field(description="When the owner approved that user modeling.")


class TwinDocument(_Record):
    schema_version: Literal[SUPPORTED_SCHEMA_VERSIONS] = Field(
        description="Version of the knowledge folder format."
    )
    kind: Literal[TWIN_DOCUMENT_KIND] = Field(description="Kind of document, a portable user twin.")
    slug: str = Field(
        pattern=_SLUG_PATTERN, description="Folder name of the twin inside the twins folder."
    )
    origin: TwinOrigin = Field(description="Project and approval the twin comes from.")
    persona: PersonaVersion = Field(description="Confirmed persona version the twin is built on.")
    twin: UserTwinVersion = Field(description="The approved user twin version.")


class EvaluatorConfiguration(_Record):
    evaluator_id: str = Field(description="Identifier of the evaluator.")
    evaluator_version: str = Field(description="Version of the evaluator.")
    model_config_ref: str = Field(description="Reference to the model configuration in use.")
    prompt_version_ref: str = Field(description="Reference to the prompt version in use.")


class SyntheticFinding(_Record):
    finding_id: str = Field(
        pattern=_code("UTF"),
        description="Code of the finding inside the response of its twin, like UTF-001.",
    )
    twin_id: Uuid = Field(description="User twin that produced the finding.")
    twin_version: _Version = Field(description="Version of that user twin.")
    artifact_id: Uuid = Field(description="Artifact the finding is about.")
    artifact_version: _Version = Field(description="Version of that artifact.")
    location: str = Field(description="Place in the artifact the finding refers to.")
    summary: str = Field(description="One-line summary of the finding.")
    rationale: str = Field(description="Reasoning behind the finding.")
    criterion: Annotated[SyntheticFindingCriterion, _BY_VALUE] = Field(
        description="User-centred design criterion the finding is about."
    )
    severity: Annotated[SyntheticFindingSeverity, _BY_VALUE] = Field(
        description="Impact of the finding on the user twin."
    )
    epistemic_status: Annotated[SyntheticFindingEpistemicStatus, _BY_VALUE] = Field(
        description="Epistemic status of the finding at the weakest defensible level."
    )
    evidence_refs: list[str] = Field(description="Evidence the finding cites, in order.")
    confidence: _Confidence = Field(description="Model confidence, between 0 and 1.")
    confidence_semantics: Literal[_FINDING_CONFIDENCE_SEMANTICS] = Field(
        description="States that the confidence is a model self-assessment, not calibrated."
    )
    recommended_action: str = Field(description="Change the user twin recommends.")
    requires_human_validation: bool = Field(
        description="True when a person has to validate the finding."
    )
    model_config_ref: str = Field(description="Reference to the model configuration in use.")
    prompt_version_ref: str = Field(description="Reference to the prompt version in use.")
    is_simulated_feedback: Literal[True] = Field(
        description="Always true: the finding is simulated feedback, not empirical evidence."
    )
    content_hash: Sha256 = Field(description="SHA-256 digest of the finding content.")


class TwinEvaluationResponse(_Record):
    evaluation_run_id: Uuid = Field(description="Review run the response belongs to.")
    artifact_bundle_id: Uuid = Field(description="Artifact bundle the twin inspected.")
    artifact_bundle_hash: Sha256 = Field(description="SHA-256 digest of that artifact bundle.")
    twin_id: Uuid = Field(description="User twin that answered.")
    twin_version: _Version = Field(description="Version of that user twin.")
    evaluator: EvaluatorConfiguration = Field(description="Evaluator that produced the answer.")
    findings: list[SyntheticFinding] = Field(description="Findings of the twin, in code order.")
    summary: str = Field(description="Overall judgement of the twin.")
    evidence_gaps: list[str] = Field(description="Evidence the twin missed, in alphabetical order.")
    is_simulated_feedback: Literal[True] = Field(
        description="Always true: the response is simulated feedback, not empirical evidence."
    )
    completed_at: Timestamp = Field(description="When the twin completed the response.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the response content.")
    disclaimer: str = Field(description="Methodological disclaimer shown next to the response.")


class EvaluationBundle(_Record):
    id: Uuid = Field(description="Identifier of the artifact bundle.")
    project_id: Uuid = Field(description="Project the bundle belongs to.")
    workflow_run_id: Uuid = Field(description="Design version the bundle was built from.")
    scenario: dict[str, object] = Field(
        description=(
            "Task given to the twins with its name, locale and expected outcomes; an open object."
        )
    )
    artifacts: list[dict[str, object]] = Field(
        description=(
            "Exact artifacts the twins inspected, each with kind, modality, media type, digest "
            "and location; open objects."
        )
    )
    modalities: list[Annotated[EvaluationArtifactModality, _BY_VALUE]] = Field(
        description="Distinct modalities of the artifacts, in alphabetical order."
    )
    is_multimodal: bool = Field(description="True when the artifacts span several modalities.")
    created_at: Timestamp = Field(description="When the bundle was created.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the bundle content.")


class EvaluationRun(_Record):
    schema_version: Literal[DESIGN_EVALUATION_SCHEMA_VERSION] = Field(
        description="Version of the review run format."
    )
    id: Uuid = Field(description="Identifier of the review run.")
    project_id: Uuid = Field(description="Project the run belongs to.")
    owner_user_id: Uuid = Field(description="Owner who started the run.")
    design_version_id: Uuid = Field(description="Design version that was reviewed.")
    design_version_number: _Version = Field(description="Version number of that design.")
    design_content_hash: Sha256 = Field(description="SHA-256 digest of that design version.")
    alternative_id: Uuid = Field(description="Selected design alternative that was reviewed.")
    alternative_code: str = Field(
        pattern=_code("DES"), description="Code of that design alternative, like DES-001."
    )
    bundle: EvaluationBundle = Field(description="Exact artifacts the twins inspected.")
    responses: list[TwinEvaluationResponse] = Field(
        description="One response for every reviewing twin."
    )
    started_at: Timestamp = Field(description="When the run started.")
    completed_at: Timestamp = Field(description="When the run completed.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the run content.")


class OwnerFindingDecision(_Record):
    evaluation_run_id: Uuid = Field(description="Review run that contains the finding.")
    twin_id: Uuid = Field(description="User twin that produced the finding.")
    finding_id: str = Field(pattern=_code("UTF"), description="Code of the finding, like UTF-001.")
    sequence_number: _Version = Field(
        description="Order of this decision among the decisions on the same finding."
    )
    project_id: Uuid = Field(description="Project the decision belongs to.")
    owner_user_id: Uuid = Field(description="Owner who decided.")
    decision: Annotated[FindingDecision, _BY_VALUE] = Field(
        description="Whether the owner confirmed or dismissed the finding."
    )
    note: str | None = Field(description="Owner's note on the decision, or null.")
    decided_at: Timestamp = Field(description="When the owner decided.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the decision content.")


class ReviewsDocument(_Record):
    schema_version: Literal[SUPPORTED_SCHEMA_VERSIONS] = Field(
        description="Version of the knowledge folder format."
    )
    kind: Literal[REVIEWS_KIND] = Field(description="Kind of document, the twin reviews.")
    project_id: Uuid = Field(description="Project the reviews belong to.")
    design: ApprovedVersionReference = Field(
        description="Approved design version exported in the same folder."
    )
    runs: list[EvaluationRun] = Field(description="Review runs in the order they started.")
    decisions: list[OwnerFindingDecision] = Field(
        description="Every owner decision on the findings of those runs."
    )


class TwinReaction(_Record):
    twin_id: Uuid = Field(description="User twin whose statement is answered.")
    verdict: Annotated[ReactionVerdict, _BY_VALUE] = Field(
        description="Whether the speaker agrees with that statement."
    )
    reason: str = Field(description="Why the speaker reacts that way.")


class TwinStatement(_Record):
    twin_id: Uuid = Field(description="User twin that speaks.")
    twin_version: _Version = Field(description="Version of that user twin.")
    twin_name: str = Field(description="Display name of that user twin.")
    stance: Annotated[DiscussionStance, _BY_VALUE] = Field(
        description="Position of the twin on the alternative."
    )
    statement: str = Field(description="What the twin says.")
    replies_to: list[Uuid] = Field(description="User twins the statement answers.")
    proposals: list[str] = Field(description="Changes the twin proposes.")
    grounded_on: list[Annotated[str, Field(pattern=_TWIN_OBSERVATION_KEY_PATTERN)]] = Field(
        description="Observation keys of the twin profile the statement relies on."
    )
    confidence: _Confidence = Field(description="Model confidence, between 0 and 1.")
    model_generation_id: Uuid = Field(description="Model generation that produced the statement.")
    reactions: Annotated[list[TwinReaction] | None, _OPTIONAL] = Field(
        default=None,
        description="Reactions to the statements of other twins, left out when there is none.",
    )
    answer_to_owner: Annotated[str | None, _OPTIONAL] = Field(
        default=None,
        description="Answer to the owner's note of the round, left out when there is none.",
    )


class ConflictPosition(_Record):
    twin_id: Uuid = Field(description="User twin that holds the position.")
    position: str = Field(description="Position of that twin on the topic.")


class SynthesisConflict(_Record):
    topic: str = Field(description="Topic the twins disagree on.")
    positions: list[ConflictPosition] = Field(description="Position of each twin involved.")


class SynthesisProposal(_Record):
    code: str = Field(
        pattern=_code(PROPOSAL_CODE_PREFIX),
        description="Code of the proposal inside its round, like PRP-001.",
    )
    text: str = Field(description="Proposed change.")
    target: Annotated[DiscussionProposalTarget, _BY_VALUE] = Field(
        description="Artifact the change applies to."
    )
    supported_by: list[Uuid] = Field(description="User twins that support the proposal.")


class DiscussionSynthesis(_Record):
    agreements: list[str] = Field(description="Points the twins agree on.")
    conflicts: list[SynthesisConflict] = Field(description="Points the twins disagree on.")
    proposals: list[SynthesisProposal] = Field(description="Changes proposed in the round.")
    questions_for_owner: list[str] = Field(description="Questions the twins ask the owner.")
    model_generation_id: Uuid = Field(description="Model generation that wrote the synthesis.")


class DiscussionRound(_Record):
    ordinal: _Version = Field(description="Position of the round, starting at 1.")
    owner_note: str | None = Field(description="Note the owner gave the twins, or null.")
    created_at: Timestamp = Field(description="When the round was held.")
    statements: list[TwinStatement] = Field(description="One statement for every twin.")
    synthesis: DiscussionSynthesis = Field(description="Synthesis of the round.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the round content.")


class DesignDiscussion(_Record):
    id: Uuid = Field(description="Identifier of the discussion.")
    project_id: Uuid = Field(description="Project the discussion belongs to.")
    owner_user_id: Uuid = Field(description="Owner who opened the discussion.")
    design_version_id: Uuid = Field(description="Design version that was discussed.")
    design_version_number: _Version = Field(description="Version number of that design.")
    design_content_hash: Sha256 = Field(description="SHA-256 digest of that design version.")
    alternative_id: Uuid = Field(description="Design alternative that was discussed.")
    alternative_code: str = Field(
        pattern=_code("DES"), description="Code of that design alternative, like DES-001."
    )
    status: Annotated[DiscussionStatus, _BY_VALUE] = Field(
        description="State of the discussion; exported discussions are approved."
    )
    created_at: Timestamp = Field(description="When the discussion was opened.")
    decided_at: Timestamp | None = Field(
        description="When the owner decided on the discussion, or null while it is open."
    )
    max_rounds: _Version = Field(description="Largest number of rounds a discussion can hold.")
    rounds: list[DiscussionRound] = Field(description="Rounds in order.")


class DiscussionsDocument(_Record):
    schema_version: Literal[SUPPORTED_SCHEMA_VERSIONS] = Field(
        description="Version of the knowledge folder format."
    )
    kind: Literal[DISCUSSIONS_KIND] = Field(description="Kind of document, the twin discussions.")
    project_id: Uuid = Field(description="Project the discussions belong to.")
    design: ApprovedVersionReference = Field(
        description="Approved design version exported in the same folder."
    )
    discussions: list[DesignDiscussion] = Field(
        description="Approved discussions in the order they were opened."
    )


class InsightApplication(_Record):
    id: Uuid = Field(description="Identifier of the application.")
    project_id: Uuid = Field(description="Project the application belongs to.")
    owner_user_id: Uuid = Field(description="Owner who applied the insight.")
    source_kind: Annotated[InsightSourceKind, _BY_VALUE] = Field(
        description="Kind of twin feedback the insight comes from."
    )
    source_id: str = Field(description="Identifier of that feedback.")
    source_twin_id: Uuid | None = Field(
        description="User twin the insight comes from, or null when it has no single twin."
    )
    text: str = Field(description="Text that was applied.")
    target: Annotated[InsightTarget, _BY_VALUE] = Field(
        description="Artifact the insight was applied to."
    )
    target_field: _BriefFieldName | None = Field(
        description="Brief field that received the insight, or null outside the brief."
    )
    target_version_id: Uuid = Field(description="Version created by the application.")
    target_version_number: _Version = Field(description="Version number of that version.")
    target_code: str | None = Field(
        description="Code of the requirement or design item created, or null for the brief."
    )
    created_at: Timestamp = Field(description="When the insight was applied.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the application content.")


class InsightsDocument(_Record):
    schema_version: Literal[SUPPORTED_SCHEMA_VERSIONS] = Field(
        description="Version of the knowledge folder format."
    )
    kind: Literal[INSIGHTS_KIND] = Field(description="Kind of document, the applied insights.")
    project_id: Uuid = Field(description="Project the applications belong to.")
    applications: list[InsightApplication] = Field(
        description="Applied insights in the order they were applied."
    )


class DesignVersionReference(ApprovedVersionReference):
    alternative_code: _AlternativeCode | None = Field(
        description="Code of the alternative the owner selected, like DES-002, or null."
    )


class DevelopmentReference(_Record):
    requirements: ApprovedVersionReference | None = Field(
        description=(
            "Approved requirements version the code is expected to implement, or null while "
            "the requirements are not approved."
        )
    )
    design: DesignVersionReference | None = Field(
        description=(
            "Approved design version the code is expected to implement, or null while the design "
            "is not approved."
        )
    )


class AlignedPoint(_Record):
    commit: CommitHash = Field(description="Commit that the owner decided is the aligned point.")
    decided_at: Timestamp = Field(description="When the owner decided it.")
    requirements_version_number: _Version | None = Field(
        description="Requirements version approved at that moment, or null when none was."
    )
    design_version_number: _Version | None = Field(
        description="Design version approved at that moment, or null when none was."
    )


class ChangedFile(_Record):
    path: _ChangedPath = Field(description="Path of the file in the repository after the commit.")
    kind: Literal[FILE_KINDS] = Field(
        description="Whether the commit added, modified, deleted or renamed the file."
    )
    added: _Count = Field(description="Number of lines the commit added to the file.")
    removed: _Count = Field(description="Number of lines the commit removed from the file.")


class ChangeReviewSummary(_Record):
    run_id: Uuid = Field(description="Latest review run of the change.")
    reviewed_at: Timestamp = Field(description="When that run completed.")
    verdict: Literal[VERDICTS] = Field(description="Alignment status decided by the model.")
    summary: _Summary = Field(description="Summary of the verdict.")


class ChangeDecision(_Record):
    kind: Literal[DECISIONS] = Field(description="What the owner decided about the change.")
    decided_at: Timestamp = Field(description="When the owner decided.")
    note: Annotated[str, Field(max_length=MAX_NOTE_LENGTH)] | None = Field(
        description="Owner's note on the decision, or null."
    )


class RecordedChange(_Record):
    commit: CommitHash = Field(description="Full hash of the commit.")
    parent: CommitHash | None = Field(
        description="Hash of the parent commit, or null for the first commit."
    )
    committed_at: Timestamp = Field(description="When the commit was made.")
    author: Annotated[str, Field(min_length=1, max_length=MAX_AUTHOR_LENGTH)] | None = Field(
        description="Author of the commit, or null when it is not known."
    )
    message: str = Field(
        min_length=1,
        max_length=MAX_MESSAGE_LENGTH,
        description=f"First {MAX_MESSAGE_LENGTH} characters of the commit message.",
    )
    files: list[ChangedFile] = Field(
        max_length=MAX_FILES, description="Files the commit changed; the diff is never exported."
    )
    recorded_at: Timestamp = Field(description="When the Studio recorded the change.")
    review: ChangeReviewSummary | None = Field(
        description="Verdict of the latest review run of the change, or null before any review."
    )
    decision: ChangeDecision | None = Field(
        description="Current decision of the owner on the change, or null before any decision."
    )


class CodeSubjects(_Record):
    requirements: list[_RequirementCode] = Field(
        description="Codes of the requirements concerned, like REQ-003."
    )
    screens: list[_ScreenCode] = Field(description="Codes of the screens concerned, like SCR-002.")


class CodeTask(_Record):
    code: _TaskCode = Field(description="Code of the task, like TSK-001.")
    text: _TaskText = Field(description="What the code should do.")
    about: CodeSubjects = Field(description="Requirements and screens the task is about.")
    from_commit: CommitHash = Field(description="Commit whose decision created the task.")
    created_at: Timestamp = Field(description="When the task was created.")
    status: Literal[TASK_STATUSES] = Field(
        description="OPEN until a later change is decided aligned, then DONE."
    )


class StateDocument(_Record):
    schema_version: Literal[KNOWLEDGE_SCHEMA_VERSION] = Field(
        description="Version of the knowledge folder format."
    )
    kind: Literal[STATE_KIND] = Field(description="Kind of document, the development state.")
    project_id: Uuid = Field(description="Project the development belongs to.")
    reference: DevelopmentReference = Field(
        description="Approved requirements and design versions the code is expected to implement."
    )
    aligned: AlignedPoint | None = Field(
        description="Newest change the owner decided is aligned, or null before any."
    )
    changes: list[RecordedChange] = Field(description="Recorded changes, newest first.")
    tasks: list[CodeTask] = Field(description="Tasks for the code, open and done.")


class RunReference(_Record):
    requirements_version_number: _Version = Field(
        description="Approved requirements version the change was reviewed against."
    )
    design_version_number: _Version = Field(
        description="Approved design version the change was reviewed against."
    )
    alternative_code: _AlternativeCode | None = Field(
        description="Code of the selected design alternative, like DES-002, or null."
    )


class FindingSubject(_Record):
    requirement: _RequirementCode | None = Field(
        description="Code of the requirement the finding is about, or null."
    )
    screen: _ScreenCode | None = Field(
        description="Code of the screen the finding is about, or null."
    )
    file: _ChangedPath | None = Field(description="Path of the file the finding is about, or null.")


class CritiqueFinding(_Record):
    severity: Literal[SEVERITIES] = Field(description="How much the finding matters to the twin.")
    text: str = Field(max_length=MAX_FINDING_LENGTH, description="What the twin found.")
    about: FindingSubject = Field(description="Requirement, screen and file the finding is about.")
    action: Annotated[str, Field(max_length=MAX_ACTION_LENGTH)] | None = Field(
        description="What the twin suggests doing, or null."
    )


class ChangeCritique(_Record):
    twin_id: Uuid = Field(description="User twin that criticized the change.")
    twin_name: str = Field(min_length=1, description="Display name of that user twin.")
    verdict: Literal[CRITIQUE_VERDICTS] = Field(
        description="Whether the change is fine for the twin, worries it or departs from the design."
    )
    summary: _Summary = Field(description="Critique of the twin, in the language of the project.")
    findings: list[CritiqueFinding] = Field(
        max_length=MAX_FINDINGS, description="Findings of the twin, most important first."
    )


class AlignmentVerdict(_Record):
    status: Literal[VERDICTS] = Field(description="Alignment status decided by the model.")
    summary: _Summary = Field(description="Why the model decided that status.")
    affected: CodeSubjects = Field(description="Requirements and screens the change affects.")
    design_request: Annotated[str, Field(max_length=MAX_DESIGN_REQUEST_LENGTH)] | None = Field(
        description="Design change request an owner could send, or null."
    )
    requirements_request: (
        Annotated[str, Field(max_length=MAX_REQUIREMENTS_REQUEST_LENGTH)] | None
    ) = Field(description="Requirements change request an owner could send, or null.")
    code_tasks: list[Annotated[str, Field(max_length=MAX_TASK_LENGTH)]] = Field(
        max_length=MAX_MODEL_TASKS,
        description="Tasks the model proposes for the code; tasks only once the owner decides.",
    )


class ChangeReviewRun(_Record):
    id: Uuid = Field(description="Identifier of the review run.")
    commit: CommitHash = Field(description="Commit that was reviewed.")
    reviewed_at: Timestamp = Field(description="When the run completed.")
    locale: str = Field(pattern=_LOCALE_PATTERN, description="Locale of the run, like it-IT.")
    reference: RunReference = Field(
        description="Approved versions the change was reviewed against."
    )
    critiques: list[ChangeCritique] = Field(description="One critique for every approved twin.")
    alignment: AlignmentVerdict = Field(description="Alignment verdict of the model.")
    cost_microusd: _Count = Field(
        description="Cost of the generations of the run, in microdollars."
    )


class ChangeReviewsDocument(_Record):
    schema_version: Literal[KNOWLEDGE_SCHEMA_VERSION] = Field(
        description="Version of the knowledge folder format."
    )
    kind: Literal[CHANGE_REVIEWS_KIND] = Field(
        description="Kind of document, the twin critiques on the code changes."
    )
    project_id: Uuid = Field(description="Project the review runs belong to.")
    runs: list[ChangeReviewRun] = Field(description="Review runs, newest first.")


class FolderGenerator(_Record):
    name: str = Field(description="Name of the application that wrote the folder.")
    mermaid_version: str = Field(description="Mermaid version the diagrams are written for.")


class PackageVersion(_Record):
    version_number: _Version = Field(
        description="Version of the knowledge folder of the project, starting at 1."
    )
    content_hash: Sha256 = Field(
        description="SHA-256 digest of the folder content, excluding orchestwin.json and the index."
    )
    created_at: Timestamp = Field(description="When the folder was exported.")


class ProjectIdentity(_Record):
    id: Uuid = Field(description="Identifier of the project.")
    name: str = Field(description="Name of the project.")
    language: str | None = Field(
        description=(
            "ISO 639-1 code of the dominant language of the requirements, or of the brief while "
            "the requirements do not show one, or null."
        )
    )


class GateArtifact(_Record):
    artifact_id: Uuid = Field(description="Version governed by the gate.")
    version: _Version = Field(description="Version number governed by the gate.")
    content_hash: Sha256 = Field(description="SHA-256 digest governed by the gate.")


class GateRecord(_Record):
    id: Uuid = Field(description="Identifier of the human gate.")
    gate_type: Annotated[HumanGateType, _BY_VALUE] = Field(description="Kind of human gate.")
    status: Annotated[HumanGateStatus, _BY_VALUE] = Field(
        description="State of the gate; exported stages are approved."
    )
    iteration: _Version = Field(description="Iteration of the gate, starting at 1.")
    updated_at: Timestamp = Field(description="When the gate last changed state.")
    artifact: GateArtifact = Field(description="Exact artifact version the gate governs.")


class StageEntry(_Record):
    label: str = Field(description="Readable name of the stage.")
    version_id: Uuid = Field(description="Identifier of the approved version.")
    version_number: _Version = Field(description="Version number of the approved artifact.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the approved artifact.")
    document: str = Field(description="Path of the JSON document of the stage.")
    text: str = Field(description="Path of the Markdown text of the stage.")
    gate: GateRecord = Field(description="Human gate that approved the stage.")


class StageEntries(_Record):
    model_config = ConfigDict(json_schema_extra={"dependentRequired": _STAGE_ORDER})

    brief: StageEntry = Field(description="Approved project brief.")
    team: Annotated[StageEntry | None, _OPTIONAL] = Field(
        default=None, description="Approved agent team, left out while it is not approved."
    )
    twins: Annotated[StageEntry | None, _OPTIONAL] = Field(
        default=None, description="Approved user modeling, left out while it is not approved."
    )
    requirements: Annotated[StageEntry | None, _OPTIONAL] = Field(
        default=None,
        description="Approved requirements specification, left out while it is not approved.",
    )
    design: Annotated[StageEntry | None, _OPTIONAL] = Field(
        default=None, description="Approved design package, left out while it is not approved."
    )

    @model_validator(mode="after")
    def _approved_in_order(self) -> StageEntries:
        given = [getattr(self, stage) is not None for stage in STAGES]
        if given != sorted(given, reverse=True):
            raise ValueError("a stage is present only when every stage before it is present")
        return self


class TwinSummary(_Record):
    twin_id: Uuid = Field(description="Stable identifier of the user twin.")
    name: str = Field(description="Display name of the user twin.")
    slug: str = Field(
        pattern=_SLUG_PATTERN, description="Folder name of the twin inside the twins folder."
    )
    version_number: _Version = Field(description="Approved version of the user twin.")
    content_hash: Sha256 = Field(description="SHA-256 digest of that version.")
    validation_status: Annotated[UserTwinLifecycleStatus, _BY_VALUE] = Field(
        description="Lifecycle and validation state of the twin."
    )
    persona_id: Uuid = Field(description="Persona the twin is built on.")
    document: str = Field(description="Path of the portable JSON document of the twin.")
    text: str = Field(description="Path of the Markdown text of the twin.")


class ViewFile(_Record):
    path: str = Field(description="Path of the file inside the folder.")
    title: str = Field(description="Readable title of the file.")


class ViewDiagram(_Record):
    key: str = Field(description="Stable key of the diagram.")
    kind: Annotated[DiagramKind, _BY_VALUE] = Field(description="Kind of Mermaid diagram.")
    subject: str | None = Field(
        description="Code of the item the diagram is about, or null for a whole-stage diagram."
    )
    title: str = Field(description="Readable title of the diagram.")
    path: str = Field(description="Path of the Mermaid file inside the folder.")


class StageViews(_Record):
    text: list[ViewFile] = Field(description="Markdown documents of the stage.")
    tables: list[ViewFile] = Field(description="CSV tables of the stage.")
    diagrams: list[ViewDiagram] = Field(description="Mermaid diagrams of the stage.")
    mockups: list[ViewFile] = Field(description="Static HTML mockups of the stage.")


class FolderViews(_Record):
    requirements: Annotated[StageViews | None, _OPTIONAL] = Field(
        default=None,
        description="Views of the requirements, left out while the requirements are not approved.",
    )
    design: Annotated[StageViews | None, _OPTIONAL] = Field(
        default=None, description="Views of the design, left out while the design is not approved."
    )


class FeedbackSummary(_Record):
    folder: str = Field(description="Folder that holds the twin feedback.")
    text: str | None = Field(
        description="Path of the Markdown summary of the feedback, or null without the design."
    )
    reviews_document: str | None = Field(
        description="Path of the reviews document, or null without the design."
    )
    discussions_document: str | None = Field(
        description="Path of the discussions document, or null without the design."
    )
    insights_document: str | None = Field(
        description="Path of the applied insights document, or null without the design."
    )
    reviews: _Count = Field(description="Number of review runs.")
    findings: _Count = Field(description="Number of findings across the review runs.")
    decisions: _Count = Field(description="Number of findings with a current owner decision.")
    discussions: _Count = Field(description="Number of approved discussions.")
    insights: _Count = Field(description="Number of applied insights.")
    changes: Annotated[str | None, _OPTIONAL] = Field(
        default=None,
        description=(
            "Path of the document of the twin critiques on the code changes; left out by "
            "folders of schema 2."
        ),
    )
    change_reviews: Annotated[_Count | None, _OPTIONAL] = Field(
        default=None,
        description="Number of review runs on the code changes; left out by folders of schema 2.",
    )


class ProgressEntry(_Record):
    approved: list[Literal[STAGES]] = Field(
        description="Approved stages the folder holds, in stage order."
    )
    pending: Literal[STAGES] | None = Field(
        description="First stage that is not approved yet, or null when every stage is approved."
    )
    complete: bool = Field(description="True when the five stages are approved.")


class StateEntry(_Record):
    document: str = Field(description="Path of the JSON document of the development state.")
    text: str = Field(description="Path of the Markdown text of the development state.")
    changes: _Count = Field(description="Number of recorded changes.")
    pending_changes: _Count = Field(description="Number of changes after the aligned point.")
    aligned_commit: CommitHash | None = Field(
        description="Commit of the aligned point, or null before any."
    )
    open_tasks: _Count = Field(description="Number of open tasks for the code.")


class StableIdentifier(_Record):
    stage: Literal[STAGES] = Field(description="Stage the item belongs to.")
    kind: str = Field(
        pattern=_IDENTIFIER_KIND_PATTERN,
        description="Kind of item, such as REQUIREMENT, USER_STORY or PROTOTYPE_SCREEN.",
    )
    scope: _AnyCode | None = Field(
        description="Code of the enclosing item for nested items, or null."
    )
    code: _AnyCode = Field(description="Human-readable code of the item, unique in its scope.")
    id: Uuid = Field(description="Stable identifier of the item.")


class KnowledgeManifest(_Record):
    model_config = ConfigDict(json_schema_extra=_MANIFEST_VERSION_RULES)

    schema_version: Literal[SUPPORTED_SCHEMA_VERSIONS] = Field(
        description=(
            "Version of the knowledge folder format: 3 holds the approved stages so far and the "
            "development state, 2 holds the five stages."
        )
    )
    kind: Literal[KNOWLEDGE_FOLDER_KIND] = Field(
        description="Kind of document, a knowledge folder."
    )
    manifest: Literal[KNOWLEDGE_MANIFEST] = Field(description="Path of this manifest.")
    index: Literal[KNOWLEDGE_INDEX] = Field(
        description="Path of the Markdown index that explains the folder."
    )
    generator: FolderGenerator = Field(description="Application that wrote the folder.")
    package: PackageVersion = Field(description="Version and digest of the folder.")
    project: ProjectIdentity = Field(description="Project the folder describes.")
    stages: StageEntries = Field(
        description=(
            "Approved version of every approved stage; a stage appears only after the stages "
            "before it."
        )
    )
    progress: Annotated[ProgressEntry | None, _OPTIONAL] = Field(
        default=None,
        description="Approved stages and the next one; left out by folders of schema 2.",
    )
    state: Annotated[StateEntry | None, _OPTIONAL] = Field(
        default=None,
        description=(
            "Where the development state is and a summary of it; left out by folders of schema 2."
        ),
    )
    twins: list[TwinSummary] = Field(description="Portable user twins of the folder.")
    views: FolderViews = Field(
        description="Texts, tables, diagrams and mockups of the approved requirements and design."
    )
    feedback: FeedbackSummary = Field(description="Where the twin feedback is and how much.")
    identifiers: list[StableIdentifier] = Field(
        description="Code and identifier of every approved requirement and design item."
    )
    schemas: dict[str, Annotated[str, Field(pattern=_SCHEMA_PATH_PATTERN)]] = Field(
        description="Path of the JSON Schema of every document kind, keyed by schema name."
    )
    files: dict[str, Sha256] = Field(
        description="SHA-256 digest of every file, except orchestwin.json and the index."
    )

    @model_validator(mode="after")
    def _fits_its_version(self) -> KnowledgeManifest:
        if self.schema_version == 2:
            if any(getattr(self.stages, stage) is None for stage in STAGES):
                raise ValueError("a folder of schema 2 holds the five stages")
            return self
        if self.progress is None or self.state is None:
            raise ValueError("a folder of schema 3 states its progress and its development state")
        if self.feedback.changes is None or self.feedback.change_reviews is None:
            raise ValueError("a folder of schema 3 states where its change critiques are")
        return self


_MODELS: Final = {
    "manifest": KnowledgeManifest,
    "brief": BriefDocument,
    "team": TeamDocument,
    "twins": TwinsDocument,
    "twin": TwinDocument,
    "requirements": RequirementsDocument,
    "design": DesignDocument,
    "reviews": ReviewsDocument,
    "discussions": DiscussionsDocument,
    "insights": InsightsDocument,
    "state": StateDocument,
    "changes": ChangeReviewsDocument,
}
_WRITTEN_BY: Final = "OrchesTwin Studio writes it when it exports the knowledge folder."
_SCHEMA_TEXTS: Final = {
    "manifest": (
        "Knowledge folder manifest",
        f"Machine-readable index of a knowledge folder, stored in {KNOWLEDGE_MANIFEST} at the "
        "folder root: approved stages, progress, development state, user twins, views, twin "
        "feedback, stable identifiers, schemas and the SHA-256 digest of every file. "
        f"{_WRITTEN_BY}",
    ),
    "brief": (
        "Approved project brief",
        "The project brief approved at the project brief gate, stored in "
        f"{stage_document('brief')}. {_WRITTEN_BY}",
    ),
    "team": (
        "Approved agent team",
        "The agent team proposal approved at the agent team gate with its deterministic role "
        f"constraints, stored in {stage_document('team')}. {_WRITTEN_BY}",
    ),
    "twins": (
        "Approved user modeling",
        "The confirmed personas and the user twins approved at the user modeling gate, stored in "
        f"{stage_document('twins')}. {_WRITTEN_BY}",
    ),
    "twin": (
        "Portable user twin",
        "One approved user twin with its persona and its origin, stored in "
        f"{twin_document('<slug>')} so that it can travel alone, for example into another "
        "project. OrchesTwin Studio writes one for every twin when it exports the knowledge "
        "folder.",
    ),
    "requirements": (
        "Approved requirements specification",
        "The requirements, user stories, acceptance criteria, scenarios, risks and definition of "
        f"done approved at the requirements gate, stored in {stage_document('requirements')}. "
        f"{_WRITTEN_BY}",
    ),
    "design": (
        "Approved design package",
        "The design alternatives, the synthetic twin critiques, the owner's selection, the "
        "declarative mockup and the design concerns approved at the design gate, stored in "
        f"{stage_document('design')}. {_WRITTEN_BY}",
    ),
    "reviews": (
        "Twin reviews of the design",
        "The simulated reviews in which the user twins inspected the mockup of a selected design "
        f"alternative, with their findings and the owner's decisions, stored in {FEEDBACK_REVIEWS}; "
        f"every finding is a model inference, not empirical evidence. {_WRITTEN_BY}",
    ),
    "discussions": (
        "Approved twin discussions",
        "The discussions among the user twins about a design alternative that the owner approved, "
        f"round by round, stored in {FEEDBACK_DISCUSSIONS}. {_WRITTEN_BY}",
    ),
    "insights": (
        "Applied twin insights",
        "The twin feedback that the owner applied to the brief, the requirements or the design, "
        f"stored in {FEEDBACK_INSIGHTS}. {_WRITTEN_BY}",
    ),
    "state": (
        "Development state",
        "The development of the project outside the Studio, stored in "
        f"{STATE_DOCUMENT}: the approved requirements and design versions the code is expected "
        "to implement, the commits recorded in the Studio with their latest verdict and the "
        "owner's decision, the aligned point and the tasks for the code. The diff of a commit is "
        f"never exported. {_WRITTEN_BY}",
    ),
    "changes": (
        "Twin critiques on the code changes",
        "The review runs in which every approved user twin criticized a recorded commit and the "
        f"model gave one alignment verdict, stored in {FEEDBACK_CHANGES}; every critique is a "
        f"model inference, not empirical evidence. {_WRITTEN_BY}",
    ),
}
_DOCUMENT_PATHS: Final = {
    KNOWLEDGE_MANIFEST: "manifest",
    **{stage_document(stage): stage for stage in STAGES},
    FEEDBACK_REVIEWS: "reviews",
    FEEDBACK_DISCUSSIONS: "discussions",
    FEEDBACK_INSIGHTS: "insights",
    STATE_DOCUMENT: "state",
    FEEDBACK_CHANGES: "changes",
}


def has_design_additions(package: Mapping[str, object]) -> bool:
    critiques = package.get("critiques") or ()
    return (
        package.get("generated_mockup") is not None
        or bool(package.get("owner_assertions"))
        or any(
            isinstance(item, Mapping)
            and (item.get("verdict") is not None or item.get("quote") is not None)
            for item in critiques
        )
    )


def _referenced_definitions(node: object) -> set[str]:
    found: set[str] = set()
    pending = [node]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            reference = current.get("$ref")
            if isinstance(reference, str) and reference.startswith(_DEFINITION_PREFIX):
                found.add(reference.removeprefix(_DEFINITION_PREFIX))
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)
    return found


def _without_design_additions(schema: dict[str, object]) -> dict[str, object]:
    stripped = deepcopy(schema)
    definitions = stripped["$defs"]
    for model, fields in _DESIGN_ADDITIONS.items():
        for field in fields:
            del definitions[model]["properties"][field]
    for model, keywords in _DESIGN_ADDITION_KEYWORDS.items():
        for keyword in keywords:
            del definitions[model][keyword]
    kept = _referenced_definitions(
        {key: value for key, value in stripped.items() if key != "$defs"}
    )
    pending = list(kept)
    while pending:
        for name in _referenced_definitions(definitions[pending.pop()]) - kept:
            kept.add(name)
            pending.append(name)
    stripped["$defs"] = {name: value for name, value in definitions.items() if name in kept}
    return stripped


def _published_schema(name: str, *, design_additions: bool) -> dict[str, object]:
    title, description = _SCHEMA_TEXTS[name]
    schema = _MODELS[name].model_json_schema(schema_generator=_KnowledgeJsonSchema)
    if name == "design" and not design_additions:
        schema = _without_design_additions(schema)
    return {
        **schema,
        "$schema": SCHEMA_DIALECT,
        "$id": f"{_SCHEMA_ID_PREFIX}:{name}",
        "title": title,
        "description": description,
    }


def knowledge_schemas(*, design_additions: bool = False) -> dict[str, dict[str, object]]:
    return {
        name: _published_schema(name, design_additions=design_additions) for name in SCHEMA_NAMES
    }


def schema_files(*, design_additions: bool = False) -> dict[str, str]:
    return {
        schema_document(name): json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
        for name, schema in knowledge_schemas(design_additions=design_additions).items()
    }


def schema_name_for_path(path: str) -> str | None:
    known = _DOCUMENT_PATHS.get(path)
    if known is not None:
        return known
    parts = path.split("/")
    if (
        len(parts) == 3
        and parts[1]
        and path == twin_document(parts[1])
        and f"{TWIN_FOLDER}/{parts[1]}" != FEEDBACK_FOLDER
    ):
        return "twin"
    return None


def _location(parts: tuple[int | str, ...]) -> str:
    location = ""
    for part in parts:
        if isinstance(part, int):
            location += f"[{part}]"
        else:
            location += f".{part}" if location else part
    return location


def within_depth(value: object, limit: int = MAX_DOCUMENT_DEPTH) -> bool:
    level = [value]
    for _ in range(limit):
        following: list[object] = []
        for item in level:
            if isinstance(item, dict):
                following.extend(item.values())
            elif isinstance(item, list):
                following.extend(item)
        if not following:
            return True
        level = following
    return False


def _nested_too_deeply(name: str, path: str) -> KnowledgeSchemaError:
    return KnowledgeSchemaError(
        code="DOCUMENT_INVALID",
        document=name,
        message="the document is nested too deeply",
        path=path,
    )


def _validate(name: str, payload: object, path: str | None) -> None:
    model = _MODELS.get(name)
    if model is None:
        raise KnowledgeSchemaError(
            code="UNKNOWN_SCHEMA",
            document=name,
            message=f"no knowledge folder schema is named {name!r}",
            path=path,
        )
    try:
        model.model_validate(payload)
    except ValidationError as error:
        first = error.errors(include_url=False)[0]
        raise KnowledgeSchemaError(
            code="DOCUMENT_INVALID",
            document=name,
            location=_location(first["loc"]),
            message=first["msg"],
            path=path,
        ) from error


def validate_document(name: str, payload: object) -> None:
    _validate(name, payload, None)


def validate_files(files: Mapping[str, str]) -> None:
    for path in sorted(files):
        name = schema_name_for_path(path)
        if name is None:
            continue
        try:
            payload = json.loads(files[path])
        except RecursionError as error:
            raise _nested_too_deeply(name, path) from error
        except (TypeError, ValueError) as error:
            raise KnowledgeSchemaError(
                code="DOCUMENT_NOT_JSON", document=name, message=str(error), path=path
            ) from error
        if not within_depth(payload):
            raise _nested_too_deeply(name, path)
        _validate(name, payload, path)


__all__ = [
    "MAX_DOCUMENT_DEPTH",
    "SCHEMA_DIALECT",
    "SCHEMA_NAMES",
    "KnowledgeSchemaError",
    "has_design_additions",
    "knowledge_schemas",
    "schema_files",
    "schema_name_for_path",
    "validate_document",
    "validate_files",
    "within_depth",
]
