"""FastAPI boundary for requirements specifications and Gate 4."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol, Self
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.clarification import (
    HumanGateEventResponse,
    HumanGateResponse,
)
from orchestwin.identity.domain import UserAccount
from orchestwin.projects.requirements import (
    Requirement,
    RequirementKind,
    RequirementPriority,
    UserStory,
)
from orchestwin.projects.requirements_application import (
    RequirementsGenerationIssueCode,
    RequirementsGenerationResult,
    RequirementsGenerationStatus,
)
from orchestwin.projects.requirements_gate import (
    RequirementsGateDecisionResult,
    RequirementsGateDecisionStatus,
    RequirementsGateSubmissionResult,
    RequirementsGateSubmissionStatus,
    RequirementsReadinessResult,
    RequirementsWorkflowReadiness,
)
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementsContextReference,
    RequirementSourceKind,
    RequirementSourceReference,
    UserTwinVersionReference,
    canonical_requirement_sources,
    canonical_user_twin_references,
    canonical_uuid_tuple,
)
from orchestwin.projects.requirements_quality import (
    AcceptanceCriterion,
    DefinitionOfDoneApplicability,
    DefinitionOfDoneItem,
    ProjectRisk,
    RiskImpact,
    RiskLikelihood,
    RiskReviewStatus,
    UsageScenario,
    VerificationMethod,
)
from orchestwin.projects.requirements_revision_application import (
    RequirementsRevisionDecision,
    RequirementsRevisionIssueCode,
    RequirementsRevisionResult,
    RequirementsRevisionStatus,
)
from orchestwin.projects.requirements_revisions import (
    RequirementsArtifact,
    RequirementsArtifactKind,
    RequirementsDiffOperation,
    RequirementsDiffOperationKind,
    RequirementsDiffStatus,
    RequirementsSpecificationDiff,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecification,
    RequirementsSpecificationVersion,
    create_requirements_specification,
)
from orchestwin.projects.requirements_traceability import (
    RequirementsCoverageSummary,
    RequirementsTraceability,
    TraceabilityLink,
    TraceabilityLinkKind,
    TraceabilityNode,
    TraceabilityNodeKind,
    TraceabilityNodeReference,
    build_requirements_traceability,
    summarize_requirements_coverage,
)
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateIssueCode,
)

REQUIREMENTS_API_PREFIX = "/projects/{project_id}/requirements"


class ApiModel(BaseModel):
    """Strict base model for requirements API contracts."""

    model_config = ConfigDict(
        extra="forbid",
    )


class RequirementsContextReferencePayload(ApiModel):
    """Exact governed artifact reference."""

    kind: RequirementsContextKind
    artifact_id: UUID
    version_number: int
    content_hash: str

    @classmethod
    def from_domain(
        cls,
        reference: RequirementsContextReference,
    ) -> RequirementsContextReferencePayload:
        """Map a context reference into the HTTP contract."""
        return cls(
            kind=reference.kind,
            artifact_id=reference.artifact_id,
            version_number=reference.version_number,
            content_hash=reference.content_hash,
        )

    def to_domain(self) -> RequirementsContextReference:
        """Convert this payload through domain validation."""
        return RequirementsContextReference(
            kind=self.kind,
            artifact_id=self.artifact_id,
            version_number=self.version_number,
            content_hash=self.content_hash,
        )


class RequirementSourcePayload(ApiModel):
    """Inspectable source supporting a requirements artifact."""

    kind: RequirementSourceKind
    source_id: str
    source_version: int | None = None
    content_hash: str | None = None
    locator: str | None = None

    @classmethod
    def from_domain(
        cls,
        source: RequirementSourceReference,
    ) -> RequirementSourcePayload:
        """Map one source reference."""
        return cls(
            kind=source.kind,
            source_id=source.source_id,
            source_version=source.source_version,
            content_hash=source.content_hash,
            locator=source.locator,
        )

    def to_domain(self) -> RequirementSourceReference:
        """Convert this source through domain validation."""
        return RequirementSourceReference(
            kind=self.kind,
            source_id=self.source_id,
            source_version=self.source_version,
            content_hash=self.content_hash,
            locator=self.locator,
        )


class UserTwinVersionReferencePayload(ApiModel):
    """Exact User Twin version used by requirements artifacts."""

    twin_id: UUID
    version_number: int
    content_hash: str
    name: str

    @classmethod
    def from_domain(
        cls,
        reference: UserTwinVersionReference,
    ) -> UserTwinVersionReferencePayload:
        """Map one exact User Twin reference."""
        return cls(
            twin_id=reference.twin_id,
            version_number=reference.version_number,
            content_hash=reference.content_hash,
            name=reference.name,
        )

    def to_domain(self) -> UserTwinVersionReference:
        """Convert this payload through domain validation."""
        return UserTwinVersionReference(
            twin_id=self.twin_id,
            version_number=self.version_number,
            content_hash=self.content_hash,
            name=self.name,
        )


class RequirementPayload(ApiModel):
    """Typed requirement HTTP contract."""

    id: UUID
    code: str
    title: str
    statement: str
    kind: RequirementKind
    priority: RequirementPriority
    sources: tuple[RequirementSourcePayload, ...]
    user_twin_references: tuple[
        UserTwinVersionReferencePayload,
        ...,
    ] = ()

    @classmethod
    def from_domain(cls, value: Requirement) -> RequirementPayload:
        """Map one domain requirement."""
        return cls(
            id=value.id,
            code=value.code,
            title=value.title,
            statement=value.statement,
            kind=value.kind,
            priority=value.priority,
            sources=tuple(RequirementSourcePayload.from_domain(source) for source in value.sources),
            user_twin_references=tuple(
                UserTwinVersionReferencePayload.from_domain(reference)
                for reference in value.user_twin_references
            ),
        )

    def to_domain(self) -> Requirement:
        """Convert this payload through requirement invariants."""
        return Requirement(
            id=self.id,
            code=self.code,
            title=self.title,
            statement=self.statement,
            kind=self.kind,
            priority=self.priority,
            sources=canonical_requirement_sources(
                (source.to_domain() for source in self.sources),
                require_items=True,
            ),
            user_twin_references=canonical_user_twin_references(
                (reference.to_domain() for reference in self.user_twin_references),
                require_items=False,
            ),
        )


class UserStoryPayload(ApiModel):
    """Typed User Story HTTP contract."""

    id: UUID
    code: str
    user_twin_reference: UserTwinVersionReferencePayload
    goal: str
    benefit: str
    requirement_ids: tuple[UUID, ...]

    @classmethod
    def from_domain(cls, value: UserStory) -> UserStoryPayload:
        """Map one domain User Story."""
        return cls(
            id=value.id,
            code=value.code,
            user_twin_reference=(
                UserTwinVersionReferencePayload.from_domain(value.user_twin_reference)
            ),
            goal=value.goal,
            benefit=value.benefit,
            requirement_ids=value.requirement_ids,
        )

    def to_domain(self) -> UserStory:
        """Convert this payload through User Story invariants."""
        return UserStory(
            id=self.id,
            code=self.code,
            user_twin_reference=self.user_twin_reference.to_domain(),
            goal=self.goal,
            benefit=self.benefit,
            requirement_ids=canonical_uuid_tuple(
                self.requirement_ids,
                label="user-story requirement IDs",
                require_items=True,
            ),
        )


class AcceptanceCriterionPayload(ApiModel):
    """Typed acceptance criterion HTTP contract."""

    id: UUID
    code: str
    statement: str
    verification_method: VerificationMethod
    requirement_ids: tuple[UUID, ...] = ()
    user_story_ids: tuple[UUID, ...] = ()

    @classmethod
    def from_domain(
        cls,
        value: AcceptanceCriterion,
    ) -> AcceptanceCriterionPayload:
        """Map one acceptance criterion."""
        return cls(
            id=value.id,
            code=value.code,
            statement=value.statement,
            verification_method=value.verification_method,
            requirement_ids=value.requirement_ids,
            user_story_ids=value.user_story_ids,
        )

    def to_domain(self) -> AcceptanceCriterion:
        """Convert this payload through criterion invariants."""
        return AcceptanceCriterion(
            id=self.id,
            code=self.code,
            statement=self.statement,
            verification_method=self.verification_method,
            requirement_ids=canonical_uuid_tuple(
                self.requirement_ids,
                label="acceptance-criterion requirement IDs",
                require_items=False,
            ),
            user_story_ids=canonical_uuid_tuple(
                self.user_story_ids,
                label="acceptance-criterion user-story IDs",
                require_items=False,
            ),
        )


class UsageScenarioPayload(ApiModel):
    """Typed usage scenario HTTP contract."""

    id: UUID
    code: str
    title: str
    actor: UserTwinVersionReferencePayload
    preconditions: tuple[str, ...]
    trigger: str
    steps: tuple[str, ...]
    expected_outcome: str
    requirement_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]

    @classmethod
    def from_domain(cls, value: UsageScenario) -> UsageScenarioPayload:
        """Map one usage scenario."""
        return cls(
            id=value.id,
            code=value.code,
            title=value.title,
            actor=UserTwinVersionReferencePayload.from_domain(value.actor),
            preconditions=value.preconditions,
            trigger=value.trigger,
            steps=value.steps,
            expected_outcome=value.expected_outcome,
            requirement_ids=value.requirement_ids,
            acceptance_criterion_ids=value.acceptance_criterion_ids,
        )

    def to_domain(self) -> UsageScenario:
        """Convert this payload through scenario invariants."""
        return UsageScenario(
            id=self.id,
            code=self.code,
            title=self.title,
            actor=self.actor.to_domain(),
            preconditions=self.preconditions,
            trigger=self.trigger,
            steps=self.steps,
            expected_outcome=self.expected_outcome,
            requirement_ids=canonical_uuid_tuple(
                self.requirement_ids,
                label="scenario requirement IDs",
                require_items=True,
            ),
            acceptance_criterion_ids=canonical_uuid_tuple(
                self.acceptance_criterion_ids,
                label="scenario acceptance-criterion IDs",
                require_items=True,
            ),
        )


class ProjectRiskPayload(ApiModel):
    """Typed project risk HTTP contract."""

    id: UUID
    code: str
    summary: str
    likelihood: RiskLikelihood
    impact: RiskImpact
    mitigation: str
    requirement_ids: tuple[UUID, ...]
    sources: tuple[RequirementSourcePayload, ...]
    review_status: RiskReviewStatus

    @classmethod
    def from_domain(cls, value: ProjectRisk) -> ProjectRiskPayload:
        """Map one project risk."""
        return cls(
            id=value.id,
            code=value.code,
            summary=value.summary,
            likelihood=value.likelihood,
            impact=value.impact,
            mitigation=value.mitigation,
            requirement_ids=value.requirement_ids,
            sources=tuple(RequirementSourcePayload.from_domain(source) for source in value.sources),
            review_status=value.review_status,
        )

    def to_domain(self) -> ProjectRisk:
        """Convert this payload through risk invariants."""
        return ProjectRisk(
            id=self.id,
            code=self.code,
            summary=self.summary,
            likelihood=self.likelihood,
            impact=self.impact,
            mitigation=self.mitigation,
            requirement_ids=canonical_uuid_tuple(
                self.requirement_ids,
                label="risk requirement IDs",
                require_items=True,
            ),
            sources=canonical_requirement_sources(
                (source.to_domain() for source in self.sources),
                require_items=True,
            ),
            review_status=self.review_status,
        )


class DefinitionOfDoneItemPayload(ApiModel):
    """Typed Definition of Done item HTTP contract."""

    id: UUID
    code: str
    statement: str
    verification_method: VerificationMethod
    applicability: DefinitionOfDoneApplicability
    condition: str | None = None
    requirement_ids: tuple[UUID, ...] = ()

    @classmethod
    def from_domain(
        cls,
        value: DefinitionOfDoneItem,
    ) -> DefinitionOfDoneItemPayload:
        """Map one Definition of Done item."""
        return cls(
            id=value.id,
            code=value.code,
            statement=value.statement,
            verification_method=value.verification_method,
            applicability=value.applicability,
            condition=value.condition,
            requirement_ids=value.requirement_ids,
        )

    def to_domain(self) -> DefinitionOfDoneItem:
        """Convert this payload through Definition of Done invariants."""
        return DefinitionOfDoneItem(
            id=self.id,
            code=self.code,
            statement=self.statement,
            verification_method=self.verification_method,
            applicability=self.applicability,
            condition=self.condition,
            requirement_ids=canonical_uuid_tuple(
                self.requirement_ids,
                label="Definition of Done requirement IDs",
                require_items=False,
            ),
        )


class RequirementsSpecificationPayload(ApiModel):
    """Complete typed requirements specification HTTP contract."""

    project_id: UUID
    project_brief_reference: RequirementsContextReferencePayload
    agent_team_reference: RequirementsContextReferencePayload
    user_modeling_reference: RequirementsContextReferencePayload
    catalog_version: int
    catalog_content_hash: str
    user_twin_references: tuple[UserTwinVersionReferencePayload, ...]
    requirements: tuple[RequirementPayload, ...]
    user_stories: tuple[UserStoryPayload, ...]
    acceptance_criteria: tuple[AcceptanceCriterionPayload, ...]
    scenarios: tuple[UsageScenarioPayload, ...]
    risks: tuple[ProjectRiskPayload, ...]
    definition_of_done: tuple[DefinitionOfDoneItemPayload, ...]

    @classmethod
    def from_domain(
        cls,
        specification: RequirementsSpecification,
    ) -> RequirementsSpecificationPayload:
        """Map a complete specification into the API contract."""
        return cls(
            project_id=specification.project_id,
            project_brief_reference=(
                RequirementsContextReferencePayload.from_domain(
                    specification.project_brief_reference
                )
            ),
            agent_team_reference=(
                RequirementsContextReferencePayload.from_domain(specification.agent_team_reference)
            ),
            user_modeling_reference=(
                RequirementsContextReferencePayload.from_domain(
                    specification.user_modeling_reference
                )
            ),
            catalog_version=specification.catalog_version,
            catalog_content_hash=specification.catalog_content_hash,
            user_twin_references=tuple(
                UserTwinVersionReferencePayload.from_domain(reference)
                for reference in specification.user_twin_references
            ),
            requirements=tuple(
                RequirementPayload.from_domain(value) for value in specification.requirements
            ),
            user_stories=tuple(
                UserStoryPayload.from_domain(value) for value in specification.user_stories
            ),
            acceptance_criteria=tuple(
                AcceptanceCriterionPayload.from_domain(value)
                for value in specification.acceptance_criteria
            ),
            scenarios=tuple(
                UsageScenarioPayload.from_domain(value) for value in specification.scenarios
            ),
            risks=tuple(ProjectRiskPayload.from_domain(value) for value in specification.risks),
            definition_of_done=tuple(
                DefinitionOfDoneItemPayload.from_domain(value)
                for value in specification.definition_of_done
            ),
        )

    def to_domain(self) -> RequirementsSpecification:
        """Convert this complete payload through aggregate validation."""
        return create_requirements_specification(
            project_id=self.project_id,
            project_brief_reference=self.project_brief_reference.to_domain(),
            agent_team_reference=self.agent_team_reference.to_domain(),
            user_modeling_reference=self.user_modeling_reference.to_domain(),
            catalog_version=self.catalog_version,
            catalog_content_hash=self.catalog_content_hash,
            user_twin_references=(reference.to_domain() for reference in self.user_twin_references),
            requirements=(value.to_domain() for value in self.requirements),
            user_stories=(value.to_domain() for value in self.user_stories),
            acceptance_criteria=(value.to_domain() for value in self.acceptance_criteria),
            scenarios=(value.to_domain() for value in self.scenarios),
            risks=(value.to_domain() for value in self.risks),
            definition_of_done=(value.to_domain() for value in self.definition_of_done),
        )


class RequirementsSpecificationVersionPayload(ApiModel):
    """One immutable requirements specification version."""

    id: UUID
    project_id: UUID
    version_number: int
    based_on_version_number: int | None
    content_hash: str
    created_by_user_id: UUID
    created_at: datetime
    specification: RequirementsSpecificationPayload

    @classmethod
    def from_domain(
        cls,
        version: RequirementsSpecificationVersion,
    ) -> RequirementsSpecificationVersionPayload:
        """Map one immutable specification version."""
        return cls(
            id=version.id,
            project_id=version.project_id,
            version_number=version.version_number,
            based_on_version_number=version.based_on_version_number,
            content_hash=version.content_hash,
            created_by_user_id=version.created_by_user_id,
            created_at=version.created_at,
            specification=RequirementsSpecificationPayload.from_domain(version.specification),
        )


class RequirementsArtifactEnvelope(ApiModel):
    """Typed wrapper for one heterogeneous diff artifact."""

    kind: RequirementsArtifactKind
    requirement: RequirementPayload | None = None
    user_story: UserStoryPayload | None = None
    acceptance_criterion: AcceptanceCriterionPayload | None = None
    scenario: UsageScenarioPayload | None = None
    risk: ProjectRiskPayload | None = None
    definition_of_done: DefinitionOfDoneItemPayload | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        """Require exactly the payload selected by artifact kind."""
        values = {
            RequirementsArtifactKind.REQUIREMENT: self.requirement,
            RequirementsArtifactKind.USER_STORY: self.user_story,
            RequirementsArtifactKind.ACCEPTANCE_CRITERION: (self.acceptance_criterion),
            RequirementsArtifactKind.SCENARIO: self.scenario,
            RequirementsArtifactKind.RISK: self.risk,
            RequirementsArtifactKind.DEFINITION_OF_DONE: (self.definition_of_done),
        }

        if values[self.kind] is None or sum(value is not None for value in values.values()) != 1:
            raise ValueError(
                "requirements artifact envelope must contain only its selected payload"
            )

        return self

    @classmethod
    def from_domain(
        cls,
        artifact: RequirementsArtifact,
    ) -> RequirementsArtifactEnvelope:
        """Wrap one heterogeneous requirements artifact."""
        if isinstance(artifact, Requirement):
            return cls(
                kind=RequirementsArtifactKind.REQUIREMENT,
                requirement=RequirementPayload.from_domain(artifact),
            )

        if isinstance(artifact, UserStory):
            return cls(
                kind=RequirementsArtifactKind.USER_STORY,
                user_story=UserStoryPayload.from_domain(artifact),
            )

        if isinstance(artifact, AcceptanceCriterion):
            return cls(
                kind=RequirementsArtifactKind.ACCEPTANCE_CRITERION,
                acceptance_criterion=AcceptanceCriterionPayload.from_domain(artifact),
            )

        if isinstance(artifact, UsageScenario):
            return cls(
                kind=RequirementsArtifactKind.SCENARIO,
                scenario=UsageScenarioPayload.from_domain(artifact),
            )

        if isinstance(artifact, ProjectRisk):
            return cls(
                kind=RequirementsArtifactKind.RISK,
                risk=ProjectRiskPayload.from_domain(artifact),
            )

        return cls(
            kind=RequirementsArtifactKind.DEFINITION_OF_DONE,
            definition_of_done=DefinitionOfDoneItemPayload.from_domain(artifact),
        )


class RequirementsDiffOperationPayload(ApiModel):
    """One explicit before/after requirements operation."""

    artifact_kind: RequirementsArtifactKind
    operation: RequirementsDiffOperationKind
    artifact_id: UUID
    display_code: str
    before: RequirementsArtifactEnvelope | None
    after: RequirementsArtifactEnvelope | None

    @classmethod
    def from_domain(
        cls,
        operation: RequirementsDiffOperation,
    ) -> RequirementsDiffOperationPayload:
        """Map one requirements diff operation."""
        return cls(
            artifact_kind=operation.artifact_kind,
            operation=operation.operation,
            artifact_id=operation.artifact_id,
            display_code=operation.display_code,
            before=(
                None
                if operation.before is None
                else RequirementsArtifactEnvelope.from_domain(operation.before)
            ),
            after=(
                None
                if operation.after is None
                else RequirementsArtifactEnvelope.from_domain(operation.after)
            ),
        )


class RequirementsSpecificationDiffPayload(ApiModel):
    """Reviewable persisted requirements specification diff."""

    id: UUID
    project_id: UUID
    base_version_id: UUID
    base_version_number: int
    base_content_hash: str
    proposed_content_hash: str
    proposal_hash: str
    status: RequirementsDiffStatus
    proposed_specification: RequirementsSpecificationPayload
    operations: tuple[RequirementsDiffOperationPayload, ...]
    created_by_user_id: UUID
    created_at: datetime
    decided_by_user_id: UUID | None
    decided_at: datetime | None
    decision_reason: str | None
    applied_specification_version_id: UUID | None

    @classmethod
    def from_domain(
        cls,
        diff: RequirementsSpecificationDiff,
    ) -> RequirementsSpecificationDiffPayload:
        """Map one persisted reviewable diff."""
        return cls(
            id=diff.id,
            project_id=diff.project_id,
            base_version_id=diff.base_version_id,
            base_version_number=diff.base_version_number,
            base_content_hash=diff.base_content_hash,
            proposed_content_hash=diff.proposed_specification.content_hash,
            proposal_hash=diff.proposal_hash,
            status=diff.status,
            proposed_specification=RequirementsSpecificationPayload.from_domain(
                diff.proposed_specification
            ),
            operations=tuple(
                RequirementsDiffOperationPayload.from_domain(operation)
                for operation in diff.operations
            ),
            created_by_user_id=diff.created_by_user_id,
            created_at=diff.created_at,
            decided_by_user_id=diff.decided_by_user_id,
            decided_at=diff.decided_at,
            decision_reason=diff.decision_reason,
            applied_specification_version_id=(diff.applied_specification_version_id),
        )


class TraceabilityNodeReferencePayload(ApiModel):
    """Stable traceability node reference."""

    kind: TraceabilityNodeKind
    artifact_id: UUID

    @classmethod
    def from_domain(
        cls,
        reference: TraceabilityNodeReference,
    ) -> TraceabilityNodeReferencePayload:
        """Map one traceability node reference."""
        return cls(
            kind=reference.kind,
            artifact_id=reference.artifact_id,
        )


class TraceabilityNodePayload(ApiModel):
    """One traceability graph node."""

    reference: TraceabilityNodeReferencePayload
    display_code: str

    @classmethod
    def from_domain(cls, node: TraceabilityNode) -> TraceabilityNodePayload:
        """Map one traceability node."""
        return cls(
            reference=TraceabilityNodeReferencePayload.from_domain(node.reference),
            display_code=node.display_code,
        )


class TraceabilityLinkPayload(ApiModel):
    """One typed traceability graph link."""

    kind: TraceabilityLinkKind
    source: TraceabilityNodeReferencePayload
    target: TraceabilityNodeReferencePayload

    @classmethod
    def from_domain(cls, link: TraceabilityLink) -> TraceabilityLinkPayload:
        """Map one traceability link."""
        return cls(
            kind=link.kind,
            source=TraceabilityNodeReferencePayload.from_domain(link.source),
            target=TraceabilityNodeReferencePayload.from_domain(link.target),
        )


class RequirementsTraceabilityPayload(ApiModel):
    """Complete typed requirements traceability graph."""

    project_id: UUID
    specification_version_id: UUID
    specification_version_number: int
    specification_content_hash: str
    content_hash: str
    nodes: tuple[TraceabilityNodePayload, ...]
    links: tuple[TraceabilityLinkPayload, ...]

    @classmethod
    def from_domain(
        cls,
        traceability: RequirementsTraceability,
    ) -> RequirementsTraceabilityPayload:
        """Map one complete traceability graph."""
        return cls(
            project_id=traceability.project_id,
            specification_version_id=traceability.specification_version_id,
            specification_version_number=traceability.specification_version_number,
            specification_content_hash=traceability.specification_content_hash,
            content_hash=traceability.content_hash,
            nodes=tuple(TraceabilityNodePayload.from_domain(node) for node in traceability.nodes),
            links=tuple(TraceabilityLinkPayload.from_domain(link) for link in traceability.links),
        )


class RequirementsCoveragePayload(ApiModel):
    """Requirements traceability coverage summary."""

    project_id: UUID
    specification_version_id: UUID
    requirement_count: int
    user_story_count: int
    acceptance_criterion_count: int
    requirement_ids_without_user_stories: tuple[UUID, ...]
    requirement_ids_without_acceptance_criteria: tuple[UUID, ...]
    user_story_ids_without_acceptance_criteria: tuple[UUID, ...]
    acceptance_criterion_ids_without_scenarios: tuple[UUID, ...]
    has_full_acceptance_coverage: bool

    @classmethod
    def from_domain(
        cls,
        coverage: RequirementsCoverageSummary,
    ) -> RequirementsCoveragePayload:
        """Map one deterministic coverage summary."""
        return cls(
            project_id=coverage.project_id,
            specification_version_id=coverage.specification_version_id,
            requirement_count=coverage.requirement_count,
            user_story_count=coverage.user_story_count,
            acceptance_criterion_count=coverage.acceptance_criterion_count,
            requirement_ids_without_user_stories=(coverage.requirement_ids_without_user_stories),
            requirement_ids_without_acceptance_criteria=(
                coverage.requirement_ids_without_acceptance_criteria
            ),
            user_story_ids_without_acceptance_criteria=(
                coverage.user_story_ids_without_acceptance_criteria
            ),
            acceptance_criterion_ids_without_scenarios=(
                coverage.acceptance_criterion_ids_without_scenarios
            ),
            has_full_acceptance_coverage=coverage.has_full_acceptance_coverage,
        )


class RequirementsGenerationPayload(ApiModel):
    """Result of generating the initial requirements specification."""

    status: RequirementsGenerationStatus
    version: RequirementsSpecificationVersionPayload | None
    issue: RequirementsGenerationIssueCode | None
    proposal_issue: str | None
    persistence_status: str | None

    @classmethod
    def from_domain(
        cls,
        result: RequirementsGenerationResult,
    ) -> RequirementsGenerationPayload:
        """Map a generation application result."""
        return cls(
            status=result.status,
            version=(
                None
                if result.version is None
                else RequirementsSpecificationVersionPayload.from_domain(result.version)
            ),
            issue=result.issue,
            proposal_issue=(None if result.proposal_issue is None else result.proposal_issue.value),
            persistence_status=(
                None if result.persistence_status is None else result.persistence_status.value
            ),
        )


class RequirementsRevisionRequest(ApiModel):
    """Complete proposed replacement specification."""

    specification: RequirementsSpecificationPayload


class RequirementsRevisionDecisionRequest(ApiModel):
    """Owner decision on one proposed requirements diff."""

    decision: RequirementsRevisionDecision
    reason: str | None = Field(
        default=None,
        max_length=2000,
    )


class RequirementsRevisionPayload(ApiModel):
    """Result of proposing or deciding a requirements revision."""

    status: RequirementsRevisionStatus
    diff: RequirementsSpecificationDiffPayload | None
    version: RequirementsSpecificationVersionPayload | None
    issue: RequirementsRevisionIssueCode | None
    proposal_issue: str | None
    diff_persistence_status: str | None
    version_persistence_status: str | None

    @classmethod
    def from_domain(
        cls,
        result: RequirementsRevisionResult,
    ) -> RequirementsRevisionPayload:
        """Map one revision application result."""
        return cls(
            status=result.status,
            diff=(
                None
                if result.diff is None
                else RequirementsSpecificationDiffPayload.from_domain(result.diff)
            ),
            version=(
                None
                if result.version is None
                else RequirementsSpecificationVersionPayload.from_domain(result.version)
            ),
            issue=result.issue,
            proposal_issue=(None if result.proposal_issue is None else result.proposal_issue.value),
            diff_persistence_status=(
                None
                if result.diff_persistence_status is None
                else result.diff_persistence_status.value
            ),
            version_persistence_status=(
                None
                if result.version_persistence_status is None
                else result.version_persistence_status.value
            ),
        )


class RequirementsGateDecisionRequest(ApiModel):
    """Owner decision for the current Requirements gate."""

    action: HumanGateAction
    reason: str | None = Field(
        default=None,
        max_length=2000,
    )

    @model_validator(mode="after")
    def reject_submit_action(self) -> Self:
        """Keep Gate 4 submission on its dedicated endpoint."""
        if self.action is HumanGateAction.SUBMIT:
            raise ValueError("SUBMIT must use the Requirements gate submission endpoint")

        return self


class RequirementsGateSubmissionPayload(ApiModel):
    """Result of submitting the current requirements version."""

    status: RequirementsGateSubmissionStatus
    gate: HumanGateResponse | None
    events: tuple[HumanGateEventResponse, ...]
    issue: HumanGateIssueCode | None

    @classmethod
    def from_domain(
        cls,
        result: RequirementsGateSubmissionResult,
    ) -> RequirementsGateSubmissionPayload:
        """Map one Gate 4 submission result."""
        return cls(
            status=result.status,
            gate=_gate_response(result.gate),
            events=tuple(HumanGateEventResponse.from_domain(event) for event in result.events),
            issue=result.issue,
        )


class RequirementsGateDecisionPayload(ApiModel):
    """Result of applying one Gate 4 owner decision."""

    status: RequirementsGateDecisionStatus
    gate: HumanGateResponse | None
    event: HumanGateEventResponse | None
    issue: HumanGateIssueCode | None

    @classmethod
    def from_domain(
        cls,
        result: RequirementsGateDecisionResult,
    ) -> RequirementsGateDecisionPayload:
        """Map one Gate 4 decision result."""
        return cls(
            status=result.status,
            gate=_gate_response(result.gate),
            event=_event_response(result.event),
            issue=result.issue,
        )


class RequirementsReadinessPayload(ApiModel):
    """Current readiness for design exploration."""

    status: RequirementsWorkflowReadiness
    version: RequirementsSpecificationVersionPayload | None
    gate: HumanGateResponse | None
    approved_current_specification: bool

    @classmethod
    def from_domain(
        cls,
        result: RequirementsReadinessResult,
    ) -> RequirementsReadinessPayload:
        """Map one Requirements readiness result."""
        return cls(
            status=result.status,
            version=(
                None
                if result.version is None
                else RequirementsSpecificationVersionPayload.from_domain(result.version)
            ),
            gate=_gate_response(result.gate),
            approved_current_specification=(
                result.status is RequirementsWorkflowReadiness.READY_FOR_DESIGN_EXPLORATION
            ),
        )


class RequirementsGenerationService(Protocol):
    """Requirements generation commands used by the API."""

    async def generate(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> RequirementsGenerationResult:
        """Generate the initial requirements specification."""


class RequirementsRevisionService(Protocol):
    """Owner-reviewed requirements revision commands."""

    async def propose_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        proposed_specification: RequirementsSpecification,
    ) -> RequirementsRevisionResult:
        """Propose one explicit specification diff."""

    async def decide_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
        decision: RequirementsRevisionDecision,
        reason: str | None = None,
    ) -> RequirementsRevisionResult:
        """Approve or reject one requirements diff."""


class RequirementsQueryService(Protocol):
    """Owner-scoped Requirements read boundary."""

    async def current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> RequirementsSpecificationVersion | None:
        """Return the current requirements version."""

    async def history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[RequirementsSpecificationVersion, ...]:
        """Return immutable requirements history."""

    async def get_diff(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
    ) -> RequirementsSpecificationDiff | None:
        """Return one exact requirements diff."""

    async def diff_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[RequirementsSpecificationDiff, ...]:
        """Return requirements diff history."""


class RequirementsGateService(Protocol):
    """Gate 4 commands and queries used by the API."""

    async def submit(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> RequirementsGateSubmissionResult:
        """Submit the exact current requirements version."""

    async def decide(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> RequirementsGateDecisionResult:
        """Apply one owner Gate 4 decision."""

    async def readiness(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> RequirementsReadinessResult:
        """Return current Requirements readiness."""

    async def current_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> HumanGate | None:
        """Return the current Gate 4."""

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        """Return Gate 4 event history."""


def _state_service[Service](
    request: Request,
    *,
    attribute: str,
    unavailable_detail: str,
) -> Service:
    """Read one explicitly configured application service."""
    service = getattr(
        request.app.state,
        attribute,
        None,
    )

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=unavailable_detail,
        )

    return service


def requirements_generation_service_dependency(
    request: Request,
) -> RequirementsGenerationService:
    """Return the configured requirements generation service."""
    return _state_service(
        request,
        attribute="requirements_generation_service",
        unavailable_detail="requirements_generation_service_unavailable",
    )


def requirements_revision_service_dependency(
    request: Request,
) -> RequirementsRevisionService:
    """Return the configured requirements revision service."""
    return _state_service(
        request,
        attribute="requirements_revision_service",
        unavailable_detail="requirements_revision_service_unavailable",
    )


def requirements_query_service_dependency(
    request: Request,
) -> RequirementsQueryService:
    """Return the configured requirements query service."""
    return _state_service(
        request,
        attribute="requirements_query_service",
        unavailable_detail="requirements_query_service_unavailable",
    )


def requirements_gate_service_dependency(
    request: Request,
) -> RequirementsGateService:
    """Return the configured requirements Gate 4 service."""
    return _state_service(
        request,
        attribute="requirements_gate_service",
        unavailable_detail="requirements_gate_service_unavailable",
    )


def create_requirements_router() -> APIRouter:
    """Create the owner-scoped Requirements and Gate 4 router."""
    router = APIRouter(
        prefix=REQUIREMENTS_API_PREFIX,
        tags=["requirements"],
    )

    @router.post(
        "/proposals",
        response_model=RequirementsGenerationPayload,
        status_code=status.HTTP_201_CREATED,
        operation_id="generateRequirementsSpecification",
    )
    async def generate_requirements_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            RequirementsGenerationService,
            Depends(requirements_generation_service_dependency),
        ],
    ) -> RequirementsGenerationPayload:
        result = await service.generate(
            owner_user_id=user.id,
            project_id=project_id,
        )
        _raise_generation_failure(result)

        return RequirementsGenerationPayload.from_domain(result)

    @router.get(
        "/current",
        response_model=RequirementsSpecificationVersionPayload,
        operation_id="getCurrentRequirementsSpecification",
    )
    async def current_requirements_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            RequirementsQueryService,
            Depends(requirements_query_service_dependency),
        ],
    ) -> RequirementsSpecificationVersionPayload:
        version = await service.current(
            owner_user_id=user.id,
            project_id=project_id,
        )

        if version is None:
            raise _not_found("REQUIREMENTS_SPECIFICATION_NOT_FOUND")

        return RequirementsSpecificationVersionPayload.from_domain(version)

    @router.get(
        "",
        response_model=tuple[RequirementsSpecificationVersionPayload, ...],
        operation_id="listRequirementsSpecifications",
    )
    async def requirements_history_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            RequirementsQueryService,
            Depends(requirements_query_service_dependency),
        ],
    ) -> tuple[RequirementsSpecificationVersionPayload, ...]:
        versions = await service.history(
            owner_user_id=user.id,
            project_id=project_id,
        )

        return tuple(
            RequirementsSpecificationVersionPayload.from_domain(version) for version in versions
        )

    @router.post(
        "/revisions",
        response_model=RequirementsRevisionPayload,
        status_code=status.HTTP_201_CREATED,
        operation_id="proposeRequirementsRevision",
    )
    async def propose_revision_endpoint(
        project_id: UUID,
        payload: RequirementsRevisionRequest,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            RequirementsRevisionService,
            Depends(requirements_revision_service_dependency),
        ],
    ) -> RequirementsRevisionPayload:
        if payload.specification.project_id != project_id:
            raise _unprocessable("REQUIREMENTS_PROJECT_MISMATCH")

        try:
            proposed = payload.specification.to_domain()
        except (TypeError, ValueError) as error:
            raise _unprocessable("INVALID_REQUIREMENTS_SPECIFICATION") from error

        result = await service.propose_revision(
            owner_user_id=user.id,
            project_id=project_id,
            proposed_specification=proposed,
        )
        _raise_revision_failure(result)

        return RequirementsRevisionPayload.from_domain(result)

    @router.get(
        "/revisions",
        response_model=tuple[RequirementsSpecificationDiffPayload, ...],
        operation_id="listRequirementsRevisions",
    )
    async def revision_history_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            RequirementsQueryService,
            Depends(requirements_query_service_dependency),
        ],
    ) -> tuple[RequirementsSpecificationDiffPayload, ...]:
        diffs = await service.diff_history(
            owner_user_id=user.id,
            project_id=project_id,
        )

        return tuple(RequirementsSpecificationDiffPayload.from_domain(diff) for diff in diffs)

    @router.get(
        "/revisions/{diff_id}",
        response_model=RequirementsSpecificationDiffPayload,
        operation_id="getRequirementsRevision",
    )
    async def get_revision_endpoint(
        project_id: UUID,
        diff_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            RequirementsQueryService,
            Depends(requirements_query_service_dependency),
        ],
    ) -> RequirementsSpecificationDiffPayload:
        diff = await service.get_diff(
            owner_user_id=user.id,
            project_id=project_id,
            diff_id=diff_id,
        )

        if diff is None:
            raise _not_found("REQUIREMENTS_DIFF_NOT_FOUND")

        return RequirementsSpecificationDiffPayload.from_domain(diff)

    @router.post(
        "/revisions/{diff_id}/decision",
        response_model=RequirementsRevisionPayload,
        operation_id="decideRequirementsRevision",
    )
    async def decide_revision_endpoint(
        project_id: UUID,
        diff_id: UUID,
        payload: RequirementsRevisionDecisionRequest,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            RequirementsRevisionService,
            Depends(requirements_revision_service_dependency),
        ],
    ) -> RequirementsRevisionPayload:
        result = await service.decide_revision(
            owner_user_id=user.id,
            project_id=project_id,
            diff_id=diff_id,
            decision=payload.decision,
            reason=payload.reason,
        )
        _raise_revision_failure(result)

        return RequirementsRevisionPayload.from_domain(result)

    @router.get(
        "/traceability",
        response_model=RequirementsTraceabilityPayload,
        operation_id="getRequirementsTraceability",
    )
    async def traceability_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            RequirementsQueryService,
            Depends(requirements_query_service_dependency),
        ],
    ) -> RequirementsTraceabilityPayload:
        version = await service.current(
            owner_user_id=user.id,
            project_id=project_id,
        )

        if version is None:
            raise _not_found("REQUIREMENTS_SPECIFICATION_NOT_FOUND")

        return RequirementsTraceabilityPayload.from_domain(build_requirements_traceability(version))

    @router.get(
        "/coverage",
        response_model=RequirementsCoveragePayload,
        operation_id="getRequirementsCoverage",
    )
    async def coverage_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            RequirementsQueryService,
            Depends(requirements_query_service_dependency),
        ],
    ) -> RequirementsCoveragePayload:
        version = await service.current(
            owner_user_id=user.id,
            project_id=project_id,
        )

        if version is None:
            raise _not_found("REQUIREMENTS_SPECIFICATION_NOT_FOUND")

        return RequirementsCoveragePayload.from_domain(summarize_requirements_coverage(version))

    @router.post(
        "/gate/submit",
        response_model=RequirementsGateSubmissionPayload,
        operation_id="submitRequirementsGate",
    )
    async def submit_gate_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            RequirementsGateService,
            Depends(requirements_gate_service_dependency),
        ],
    ) -> RequirementsGateSubmissionPayload:
        result = await service.submit(
            project_id=project_id,
            owner_user_id=user.id,
        )
        _raise_gate_submission_failure(result)

        return RequirementsGateSubmissionPayload.from_domain(result)

    @router.post(
        "/gate/decision",
        response_model=RequirementsGateDecisionPayload,
        operation_id="decideRequirementsGate",
    )
    async def decide_gate_endpoint(
        project_id: UUID,
        payload: RequirementsGateDecisionRequest,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            RequirementsGateService,
            Depends(requirements_gate_service_dependency),
        ],
    ) -> RequirementsGateDecisionPayload:
        result = await service.decide(
            project_id=project_id,
            owner_user_id=user.id,
            action=payload.action,
            reason=payload.reason,
        )
        _raise_gate_decision_failure(result)

        return RequirementsGateDecisionPayload.from_domain(result)

    @router.get(
        "/gate",
        response_model=HumanGateResponse,
        operation_id="getCurrentRequirementsGate",
    )
    async def current_gate_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            RequirementsGateService,
            Depends(requirements_gate_service_dependency),
        ],
    ) -> HumanGateResponse:
        gate = await service.current_gate(
            project_id=project_id,
            owner_user_id=user.id,
        )

        if gate is None:
            raise _not_found("REQUIREMENTS_GATE_NOT_FOUND")

        return HumanGateResponse.from_domain(gate)

    @router.get(
        "/gate/events",
        response_model=tuple[HumanGateEventResponse, ...],
        operation_id="listRequirementsGateEvents",
    )
    async def gate_events_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            RequirementsGateService,
            Depends(requirements_gate_service_dependency),
        ],
    ) -> tuple[HumanGateEventResponse, ...]:
        gate = await service.current_gate(
            project_id=project_id,
            owner_user_id=user.id,
        )

        if gate is None:
            raise _not_found("REQUIREMENTS_GATE_NOT_FOUND")

        events = await service.gate_events(
            project_id=project_id,
            owner_user_id=user.id,
            gate_id=gate.id,
        )

        return tuple(HumanGateEventResponse.from_domain(event) for event in events)

    @router.get(
        "/readiness",
        response_model=RequirementsReadinessPayload,
        operation_id="getRequirementsReadiness",
    )
    async def readiness_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            RequirementsGateService,
            Depends(requirements_gate_service_dependency),
        ],
    ) -> RequirementsReadinessPayload:
        result = await service.readiness(
            project_id=project_id,
            owner_user_id=user.id,
        )

        return RequirementsReadinessPayload.from_domain(result)

    return router


def _gate_response(gate: HumanGate | None) -> HumanGateResponse | None:
    """Map an optional human gate."""
    return None if gate is None else HumanGateResponse.from_domain(gate)


def _event_response(
    event: HumanGateEvent | None,
) -> HumanGateEventResponse | None:
    """Map an optional human gate event."""
    return None if event is None else HumanGateEventResponse.from_domain(event)


def _raise_generation_failure(result: RequirementsGenerationResult) -> None:
    """Translate expected generation failures into HTTP semantics."""
    if result.status is RequirementsGenerationStatus.CREATED:
        return

    if result.issue is RequirementsGenerationIssueCode.PROJECT_NOT_FOUND:
        raise _not_found("PROJECT_NOT_FOUND")

    raise _conflict(
        result.issue.value if result.issue is not None else "REQUIREMENTS_GENERATION_REJECTED"
    )


def _raise_revision_failure(result: RequirementsRevisionResult) -> None:
    """Translate expected revision failures into HTTP semantics."""
    if result.status in {
        RequirementsRevisionStatus.CREATED,
        RequirementsRevisionStatus.APPLIED,
        RequirementsRevisionStatus.NO_CHANGE,
    }:
        return

    if result.issue in {
        RequirementsRevisionIssueCode.SPECIFICATION_NOT_FOUND,
        RequirementsRevisionIssueCode.DIFF_NOT_FOUND,
    }:
        raise _not_found(
            result.issue.value if result.issue is not None else "REQUIREMENTS_NOT_FOUND"
        )

    raise _conflict(
        result.issue.value if result.issue is not None else "REQUIREMENTS_REVISION_REJECTED"
    )


def _raise_gate_submission_failure(
    result: RequirementsGateSubmissionResult,
) -> None:
    """Translate expected Gate 4 submission failures."""
    if result.status in {
        RequirementsGateSubmissionStatus.SUBMITTED,
        RequirementsGateSubmissionStatus.ALREADY_PENDING,
        RequirementsGateSubmissionStatus.ALREADY_APPROVED,
    }:
        return

    if result.status is RequirementsGateSubmissionStatus.SPECIFICATION_NOT_FOUND:
        raise _not_found("REQUIREMENTS_SPECIFICATION_NOT_FOUND")

    raise _conflict(result.status.value)


def _raise_gate_decision_failure(
    result: RequirementsGateDecisionResult,
) -> None:
    """Translate expected Gate 4 decision failures."""
    if result.status is RequirementsGateDecisionStatus.APPLIED:
        return

    if result.status in {
        RequirementsGateDecisionStatus.GATE_NOT_FOUND,
        RequirementsGateDecisionStatus.SPECIFICATION_NOT_FOUND,
    }:
        raise _not_found(result.status.value)

    raise _conflict(result.issue.value if result.issue is not None else result.status.value)


def _not_found(code: str) -> HTTPException:
    """Return one non-disclosing owner-scoped lookup error."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": code},
    )


def _conflict(code: str) -> HTTPException:
    """Return one typed state or governance conflict."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code},
    )


def _unprocessable(code: str) -> HTTPException:
    """Return one typed invalid-input response."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"code": code},
    )


__all__ = [
    "REQUIREMENTS_API_PREFIX",
    "RequirementsCoveragePayload",
    "RequirementsGenerationPayload",
    "RequirementsQueryService",
    "RequirementsReadinessPayload",
    "RequirementsRevisionPayload",
    "RequirementsSpecificationDiffPayload",
    "RequirementsSpecificationPayload",
    "RequirementsSpecificationVersionPayload",
    "RequirementsTraceabilityPayload",
    "create_requirements_router",
]
