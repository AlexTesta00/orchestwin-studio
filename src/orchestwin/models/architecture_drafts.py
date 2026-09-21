"""Compact architecture proposals; UUIDs and approved scope are application-owned."""

from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orchestwin.artifacts import architecture as domain
from orchestwin.artifacts import test_plans as plans
from orchestwin.artifacts.architecture_packages import (
    create_architecture_grounding,
    create_architecture_planning_package,
)
from orchestwin.models.design_drafts import requirement_code_map, requirements_view
from orchestwin.models.proposal_generation import wire_value
from orchestwin.models.requirements_drafts import Draft, Links, Text, Title
from orchestwin.projects.requirements_quality import RiskImpact, RiskLikelihood


class ComponentDraft(Draft):
    code: str = Field(pattern=r"^CMP-[0-9]{3,}$")
    name: Title
    kind: domain.ArchitectureComponentKind
    responsibility: Text
    technology: Title
    interfaces: tuple[Text, ...]
    requirement_ids: Links
    assumptions: tuple[Text, ...]


class ConnectionDraft(Draft):
    code: str = Field(pattern=r"^CON-[0-9]{3,}$")
    source_component_id: str
    target_component_id: str
    kind: domain.ArchitectureConnectionKind
    description: Text
    data_flows: tuple[Text, ...]
    requirement_ids: Links


class DecisionDraft(Draft):
    code: str = Field(pattern=r"^ADR-[0-9]{3,}$")
    title: Title
    context: Text
    decision: Text
    consequences: Annotated[tuple[Text, ...], Field(min_length=1)]
    alternatives_considered: Annotated[tuple[Text, ...], Field(min_length=1)]
    requirement_ids: Links


class EntityDraft(Draft):
    code: str = Field(pattern=r"^ENT-[0-9]{3,}$")
    name: Title
    description: Text
    fields: Annotated[tuple[Text, ...], Field(min_length=1)]
    owning_component_id: str
    requirement_ids: Links


class ApiDraft(Draft):
    code: str = Field(pattern=r"^API-[0-9]{3,}$")
    method: domain.ApiMethod
    path: str
    summary: Text
    owning_component_id: str
    request_schema: Title | None
    response_schema: Title
    requirement_ids: Links
    acceptance_criterion_ids: Links


class ArchitectureRiskDraft(Draft):
    code: str = Field(pattern=r"^ARK-[0-9]{3,}$")
    summary: Text
    likelihood: RiskLikelihood
    impact: RiskImpact
    mitigation: Text
    component_ids: Links
    requirement_ids: Links


class EnvironmentDraft(Draft):
    code: str = Field(pattern=r"^ENV-[0-9]{3,}$")
    name: Title
    kind: plans.TestEnvironmentKind
    description: Text
    configuration: tuple[Text, ...]


class TestCaseDraft(Draft):
    code: str = Field(pattern=r"^TST-[0-9]{3,}$")
    title: Title
    objective: Text
    level: plans.TestLevel
    automation: plans.TestAutomation
    priority: plans.TestPriority
    preconditions: tuple[Text, ...]
    steps: Annotated[tuple[Text, ...], Field(min_length=1)]
    expected_results: Annotated[tuple[Text, ...], Field(min_length=1)]
    requirement_ids: Links
    acceptance_criterion_ids: Links
    architecture_component_ids: Links
    environment_ids: Links


class QualityGateDraft(Draft):
    code: str = Field(pattern=r"^QGT-[0-9]{3,}$")
    title: Title
    criterion: Text
    required_test_case_ids: Links
    minimum_pass_rate: int = Field(ge=0, le=100)
    blocking: bool


class ArchitectureStructureDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: Title
    style: domain.ArchitectureStyle
    summary: Text
    components: Annotated[tuple[ComponentDraft, ...], Field(min_length=1)]
    environments: Annotated[tuple[EnvironmentDraft, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_codes(self):
        codes = [x.code for x in (*self.components, *self.environments)]
        if len(codes) != len(set(codes)):
            raise ValueError("duplicate architecture structure codes")
        return self


class ArchitectureDetailsDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    connections: tuple[ConnectionDraft, ...] = Field(
        description="Links between distinct declared components only. For one component use []."
    )
    decisions: Annotated[tuple[DecisionDraft, ...], Field(min_length=1)]
    data_entities: tuple[EntityDraft, ...]
    api_operations: tuple[ApiDraft, ...]
    risks: tuple[ArchitectureRiskDraft, ...]
    quality_attributes: Annotated[tuple[Text, ...], Field(min_length=1)]
    deployment_view: Annotated[tuple[Text, ...], Field(min_length=1)]
    test_strategy: Text
    test_cases: Annotated[tuple[TestCaseDraft, ...], Field(min_length=1)]
    quality_gates: Annotated[tuple[QualityGateDraft, ...], Field(min_length=1)]
    fixtures: tuple[Text, ...]
    assumptions: tuple[Text, ...]
    open_questions: tuple[Text, ...]


class ArchitectureDraft(ArchitectureStructureDraft, ArchitectureDetailsDraft):
    """Complete validated composition of two unchanged model outputs."""


def architecture_context(request):
    package = request.design.version.package
    selected = next(
        x for x in package.alternatives if x.id == package.owner_selected_alternative_id
    )
    return {
        "project_id": str(request.project_id),
        "governed_request_hash": request.content_hash,
        "requirements": requirements_view(request.requirements.version),
        "approved_design_reference": wire_value(request.design.reference),
        "selected_design": {
            key: value
            for key, value in wire_value(selected).items()
            if key
            not in {
                "user_twin_references",
                "requirement_ids",
                "user_story_ids",
                "acceptance_criterion_ids",
            }
        },
        "prototype": wire_value(package.prototype),
    }


def bind_architecture(draft, request):
    grounding = create_architecture_grounding(request.design.version)
    ids = requirement_code_map(request.requirements.version.specification)
    groups = (
        draft.components,
        draft.connections,
        draft.decisions,
        draft.data_entities,
        draft.api_operations,
        draft.risks,
        draft.environments,
        draft.test_cases,
        draft.quality_gates,
    )
    codes = [x.code for group in groups for x in group]
    if len(codes) != len(set(codes)) or set(codes) & ids.keys():
        raise ValueError("duplicate architecture codes")
    ids.update({code: uuid4() for code in codes})

    def materialize(factory, item, identity_name, **bound):
        # Only reference fields use the validated code map. All semantic text is model output.
        values = item.model_dump()
        for key, value in tuple(values.items()):
            if key.endswith("_ids"):
                values[key] = tuple(ids[code] for code in value)
            elif key.endswith("_id"):
                values[key] = ids[value]
        return factory(**values, **{identity_name: ids[item.code]}, **bound)

    try:
        components = [
            materialize(domain.create_architecture_component, x, "component_id")
            for x in draft.components
        ]
        architecture = domain.create_software_architecture(
            architecture_id=uuid4(),
            code="ARC-001",
            title=draft.title,
            style=draft.style,
            summary=draft.summary,
            selected_design_alternative_id=grounding.owner_selected_alternative_id,
            prototype_id=grounding.prototype_id,
            requirement_ids=grounding.requirement_ids,
            acceptance_criterion_ids=grounding.acceptance_criterion_ids,
            components=components,
            connections=[
                materialize(domain.create_architecture_connection, x, "connection_id")
                for x in draft.connections
            ],
            decisions=[
                materialize(domain.create_architecture_decision, x, "decision_id")
                for x in draft.decisions
            ],
            data_entities=[
                materialize(domain.create_architecture_data_entity, x, "entity_id")
                for x in draft.data_entities
            ],
            api_operations=[
                materialize(domain.create_architecture_api_operation, x, "operation_id")
                for x in draft.api_operations
            ],
            risks=[materialize(domain.create_architecture_risk, x, "risk_id") for x in draft.risks],
            quality_attributes=draft.quality_attributes,
            deployment_view=draft.deployment_view,
            assumptions=draft.assumptions,
            open_questions=draft.open_questions,
        )
        test_plan = plans.create_test_plan(
            plan_id=uuid4(),
            code="TPL-001",
            title=draft.title,
            strategy=draft.test_strategy,
            architecture_id=architecture.id,
            selected_design_alternative_id=grounding.owner_selected_alternative_id,
            requirement_ids=grounding.requirement_ids,
            acceptance_criterion_ids=grounding.acceptance_criterion_ids,
            architecture_component_ids=[x.id for x in components],
            environments=[
                materialize(plans.create_test_environment, x, "environment_id")
                for x in draft.environments
            ],
            test_cases=[
                materialize(
                    plans.create_planned_test_case,
                    x,
                    "test_case_id",
                    design_alternative_ids=(grounding.owner_selected_alternative_id,),
                )
                for x in draft.test_cases
            ],
            quality_gates=[
                materialize(plans.create_quality_gate, x, "gate_id") for x in draft.quality_gates
            ],
            fixtures=draft.fixtures,
            assumptions=draft.assumptions,
            open_questions=draft.open_questions,
        )
    except KeyError as error:
        raise ValueError("unknown architecture reference") from error
    return create_architecture_planning_package(
        project_id=request.project_id,
        grounding=grounding,
        architecture=architecture,
        test_plan=test_plan,
        open_questions=draft.open_questions,
    )
