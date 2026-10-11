from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from orchestwin.knowledge.schema_models.base import (
    _BY_VALUE,
    _OPTIONAL,
    CatalogReference,
    Sha256,
    UserTwinReference,
    Uuid,
    _code,
    _Record,
    _Version,
)
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
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"schema_version": {"const": 1}}},
                    "then": {
                        "not": {
                            "anyOf": [
                                {"required": ["needs"]},
                                {"required": ["journeys"]},
                                *(
                                    {
                                        "properties": {
                                            name: {"contains": {"required": ["need_ids"]}}
                                        },
                                        "required": [name],
                                    }
                                    for name in ("requirements", "user_stories")
                                ),
                                {
                                    "properties": {
                                        "scenarios": {
                                            "contains": {
                                                "anyOf": [
                                                    {"required": [field]}
                                                    for field in (
                                                        "context",
                                                        "goal",
                                                        "criticalities",
                                                        "sources",
                                                    )
                                                ]
                                            }
                                        }
                                    },
                                    "required": ["scenarios"],
                                },
                            ]
                        }
                    },
                }
            ]
        }
    )

    schema_version: Literal[1] = Field(
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

    @model_validator(mode="before")
    @classmethod
    def _legacy_has_no_chain(cls, value: object) -> object:
        if (
            isinstance(value, Mapping)
            and value.get("schema_version") == 1
            and (
                "needs" in value
                or "journeys" in value
                or any(
                    "need_ids" in item
                    for name in ("requirements", "user_stories")
                    for item in value.get(name, ())
                    if isinstance(item, Mapping)
                )
                or any(
                    set(item) & {"context", "goal", "criticalities", "sources"}
                    for item in value.get("scenarios", ())
                    if isinstance(item, Mapping)
                )
            )
        ):
            raise ValueError("schema 1 cannot contain needs or enriched scenarios")
        return value


class UserNeed(_Record):
    id: Uuid
    code: str = Field(pattern=_code("NED"))
    title: str = Field(min_length=1, max_length=200)
    statement: str = Field(min_length=1, max_length=2000)
    scenario_ids: list[Uuid] = Field(min_length=1)
    sources: list[RequirementSource] = Field(min_length=1)


class Requirement2(Requirement):
    need_ids: list[Uuid] = Field(min_length=1)


class UserStory2(UserStory):
    need_ids: list[Uuid] = Field(min_length=1)


class UsageScenario2(UsageScenario):
    context: str = Field(min_length=1, max_length=2000)
    goal: str = Field(min_length=1, max_length=2000)
    criticalities: list[Annotated[str, Field(min_length=1, max_length=2000)]]
    sources: list[RequirementSource] = Field(min_length=1)


class JourneyPhase(_Record):
    title: str = Field(min_length=1, max_length=200)
    action: str = Field(min_length=1, max_length=2000)
    touchpoint: Annotated[str, Field(min_length=1, max_length=2000)] | None
    criticalities: list[Annotated[str, Field(min_length=1, max_length=2000)]]
    need_ids: list[Uuid] = Field(min_length=1)


class UserJourney(_Record):
    id: Uuid
    code: str = Field(pattern=_code("JRN"))
    title: str = Field(min_length=1, max_length=200)
    scenario_id: Uuid
    phases: list[JourneyPhase] = Field(min_length=1, max_length=32)
    sources: list[RequirementSource] = Field(min_length=1)


class RequirementsSpecificationSnapshot2(RequirementsSpecificationSnapshot):
    schema_version: Literal[REQUIREMENTS_SPECIFICATION_SCHEMA_VERSION]
    needs: list[UserNeed] = Field(min_length=1)
    requirements: list[Requirement2]
    user_stories: list[UserStory2]
    scenarios: list[UsageScenario2]
    journeys: Annotated[list[UserJourney], _OPTIONAL] = Field(default_factory=list, min_length=1)
