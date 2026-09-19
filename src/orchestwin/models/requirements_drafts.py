"""Semantic requirements drafts; the application owns identities and evidence bindings."""

from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from orchestwin.models.proposal_generation import wire_value
from orchestwin.projects import requirements as req
from orchestwin.projects import requirements_quality as quality
from orchestwin.projects.requirements_primitives import (
    RequirementSourceKind,
    RequirementSourceReference,
)
from orchestwin.projects.requirements_specifications import create_requirements_specification

Text = Annotated[str, Field(min_length=1, max_length=2000)]
Title = Annotated[str, Field(min_length=1, max_length=200)]
Links = Annotated[tuple[str, ...], Field(min_length=1)]


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str


class RequirementDraft(Draft):
    code: str = Field(pattern=r"^REQ-[0-9]{3,}$")
    title: Title
    statement: Text
    kind: req.RequirementKind
    priority: req.RequirementPriority
    sources: Links
    twins: tuple[str, ...]


class StoryDraft(Draft):
    code: str = Field(pattern=r"^USR-[0-9]{3,}$")
    twin: str
    goal: Text
    benefit: Text
    requirements: Links


class CriterionDraft(Draft):
    code: str = Field(pattern=r"^AC-[0-9]{3,}$")
    statement: Text
    verification_method: quality.VerificationMethod
    requirements: Links
    stories: tuple[str, ...]


class ScenarioDraft(Draft):
    code: str = Field(pattern=r"^SCN-[0-9]{3,}$")
    title: Title
    twin: str
    preconditions: tuple[Text, ...]
    trigger: Text
    steps: Annotated[tuple[Text, ...], Field(min_length=1)]
    expected_outcome: Text
    requirements: Links
    criteria: Links


class RiskDraft(Draft):
    code: str = Field(pattern=r"^RSK-[0-9]{3,}$")
    summary: Text
    likelihood: quality.RiskLikelihood
    impact: quality.RiskImpact
    mitigation: Text
    requirements: tuple[str, ...]
    sources: Links


class DoneDraft(Draft):
    code: str = Field(pattern=r"^DOD-[0-9]{3,}$")
    statement: Text
    verification_method: quality.VerificationMethod
    applicability: quality.DefinitionOfDoneApplicability
    condition: Text | None
    requirements: tuple[str, ...]


class RequirementsDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    requirements: Annotated[tuple[RequirementDraft, ...], Field(min_length=1)]
    user_stories: Annotated[tuple[StoryDraft, ...], Field(min_length=1)]
    acceptance_criteria: Annotated[tuple[CriterionDraft, ...], Field(min_length=1)]
    scenarios: Annotated[tuple[ScenarioDraft, ...], Field(min_length=1)]
    risks: tuple[RiskDraft, ...]
    definition_of_done: Annotated[tuple[DoneDraft, ...], Field(min_length=1)]


def requirements_context(request):
    sources, evidence = {}, {}
    brief = request.brief
    for name, value in wire_value(brief).items():
        if name in {"reference", "unknown_fields"} or name in brief.unknown_fields:
            continue
        values = (
            [(name, value)]
            if isinstance(value, str)
            else (
                [(f"{name}[{i}]", item) for i, item in enumerate(value)]
                if isinstance(value, list)
                else []
            )
        )
        for locator, content in values:
            key = f"brief:{locator}"
            evidence[key] = content
            sources[key] = RequirementSourceReference(
                kind=RequirementSourceKind.PROJECT_BRIEF,
                source_id=str(brief.reference.artifact_id),
                source_version=brief.reference.version_number,
                content_hash=brief.reference.content_hash,
                locator=locator,
            )
    twins = {}
    for i, twin in enumerate(request.user_modeling.user_twins, 1):
        key = f"T{i}"
        twins[key] = twin.reference
        for observation in twin.observations:
            source = f"{key}:{observation.observation_key}"
            evidence[source] = {
                "value": wire_value(observation.value),
                "epistemic_status": observation.epistemic_status.value,
                "rationale": observation.rationale,
            }
            sources[source] = RequirementSourceReference(
                kind=RequirementSourceKind.USER_TWIN,
                source_id=str(twin.reference.twin_id),
                source_version=twin.reference.version_number,
                content_hash=twin.reference.content_hash,
                locator=observation.observation_key,
            )
    return (
        {
            "project_id": str(request.project_id),
            "governed_request_hash": request.content_hash,
            "evidence": evidence,
            "twins": wire_value(twins),
            "brief_reference": wire_value(brief.reference),
            "user_modeling_reference": wire_value(request.user_modeling.reference),
        },
        sources,
        twins,
    )


def bind_requirements(draft, request, sources, twins):
    """Resolve only explicit model-chosen links; never infer missing semantic content."""
    groups = (
        draft.requirements,
        draft.user_stories,
        draft.acceptance_criteria,
        draft.scenarios,
        draft.risks,
        draft.definition_of_done,
    )
    codes = [item.code for group in groups for item in group]
    if len(codes) != len(set(codes)):
        raise ValueError("duplicate draft codes")
    ids = {code: uuid4() for code in codes}

    def links(values):
        return tuple(ids[value] for value in values)

    try:
        requirements = [
            req.create_requirement(
                requirement_id=ids[x.code],
                code=x.code,
                title=x.title,
                statement=x.statement,
                kind=x.kind,
                priority=x.priority,
                sources=[sources[s] for s in x.sources],
                user_twin_references=[twins[t] for t in x.twins],
            )
            for x in draft.requirements
        ]
        stories = [
            req.create_user_story(
                story_id=ids[x.code],
                code=x.code,
                user_twin_reference=twins[x.twin],
                goal=x.goal,
                benefit=x.benefit,
                requirement_ids=links(x.requirements),
            )
            for x in draft.user_stories
        ]
        criteria = [
            quality.create_acceptance_criterion(
                criterion_id=ids[x.code],
                code=x.code,
                statement=x.statement,
                verification_method=x.verification_method,
                requirement_ids=links(x.requirements),
                user_story_ids=links(x.stories),
            )
            for x in draft.acceptance_criteria
        ]
        scenarios = [
            quality.create_usage_scenario(
                scenario_id=ids[x.code],
                code=x.code,
                title=x.title,
                actor=twins[x.twin],
                preconditions=x.preconditions,
                trigger=x.trigger,
                steps=x.steps,
                expected_outcome=x.expected_outcome,
                requirement_ids=links(x.requirements),
                acceptance_criterion_ids=links(x.criteria),
            )
            for x in draft.scenarios
        ]
        risks = [
            quality.create_project_risk(
                risk_id=ids[x.code],
                code=x.code,
                summary=x.summary,
                likelihood=x.likelihood,
                impact=x.impact,
                mitigation=x.mitigation,
                requirement_ids=links(x.requirements),
                sources=[sources[s] for s in x.sources],
            )
            for x in draft.risks
        ]
        done = [
            quality.create_definition_of_done_item(
                item_id=ids[x.code],
                code=x.code,
                statement=x.statement,
                verification_method=x.verification_method,
                applicability=x.applicability,
                condition=x.condition,
                requirement_ids=links(x.requirements),
            )
            for x in draft.definition_of_done
        ]
    except KeyError as error:
        raise ValueError("unknown draft reference") from error
    return create_requirements_specification(
        project_id=request.project_id,
        project_brief_reference=request.brief.reference,
        agent_team_reference=request.team.reference,
        user_modeling_reference=request.user_modeling.reference,
        catalog_version=request.catalog_version,
        catalog_content_hash=request.catalog_content_hash,
        user_twin_references=request.user_modeling.user_twin_references,
        requirements=requirements,
        user_stories=stories,
        acceptance_criteria=criteria,
        scenarios=scenarios,
        risks=risks,
        definition_of_done=done,
    )
