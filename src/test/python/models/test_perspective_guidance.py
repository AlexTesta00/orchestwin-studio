from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from orchestwin.agents.catalog import AgentIdentifier
from orchestwin.agents.perspectives import GuidanceStage, perspective_guidance
from orchestwin.models.design_drafts import (
    HOSTED_DESIGN_CONTRACT_VERSION,
    HostedDesignDraft,
    design_context,
    hosted_design_context,
)
from orchestwin.models.model_proposals import (
    HOSTED_PERSPECTIVES_INSTRUCTION,
    HOSTED_SCHEMA_INSTRUCTION,
    ModelDesignAdapter,
    ModelRequirementsAdapter,
    design_instruction,
    hosted_design_instruction,
)
from orchestwin.models.planning_schema import constrain_planning_schema
from orchestwin.models.proposal_generation import (
    DESIGN_CONTRACT_VERSIONS,
    ProposalGenerationError,
    ProposalGenerator,
)
from orchestwin.models.requirements_drafts import (
    RequirementsDraft,
    requirements_context,
    requirements_view,
)
from orchestwin.models.structured_generation import (
    StructuredGenerationFailureCode,
    StructuredGenerationProviderKind,
    failed_structured_generation_result,
)
from orchestwin.projects.requirements_primitives import canonical_json

from . import test_fake_design as design_fixtures
from . import test_fake_requirements as requirements_fixtures
from .test_hosted_schema import CapturePort
from .test_hosted_support import providers
from .test_model_proposals import make_generator
from .test_requirements_change_proposals import (
    OWNER_REQUEST,
    adapter_call,
    baseline_instruction,
    generated_specification,
    sha256,
)

DEFINITION_SENTENCES = (
    "context.perspectives lists the perspectives chosen for this project, each with its "
    "considerations. Apply a consideration where this project needs it, inside the "
    "requirements, the acceptance criteria and the risks that you write anyway: a "
    "consideration never justifies an item that the project does not need and never an "
    "item beyond context.limits."
)
DESIGN_SENTENCE = (
    "context.perspectives lists the perspectives chosen for this project, each with its "
    "considerations: take them into account in every alternative and in the critiques, without "
    "adding screens or functions that no requirement asks for."
)
PROPORTION_END = "Every statement is one sentence, two at most."
CONTEXT_BEFORE_PERSPECTIVES_SHA256 = (
    "6d0e77fa081a8423a0b8bd99648a720b1acdbd16856a1b4c775bc9aa0197579d"
)
INSTRUCTION_BEFORE_PERSPECTIVES_SHA256 = (
    "ff47349a99fa3617618bddd322bc713f859888673f69ddeb13f554ed79fb9080"
)
HOSTED_INSTRUCTION_BEFORE_PERSPECTIVES_SHA256 = (
    "2d745b9d2e17c67c841c58f9b8bb0c49ea6ca402ad21e380821e03b9fc4058f9"
)
EVERY_AGENT = tuple(AgentIdentifier)
MINIMUM_TEAM = (
    AgentIdentifier.WORKFLOW_ORCHESTRATOR,
    AgentIdentifier.INTAKE_CLARIFICATION_AGENT,
    AgentIdentifier.TEAM_SELECTOR,
    AgentIdentifier.HUMAN_GATE_CONTROLLER,
    AgentIdentifier.ARTIFACT_MANAGER,
    AgentIdentifier.SANDBOX_CONTROLLER,
    AgentIdentifier.REQUIREMENTS_ANALYST,
    AgentIdentifier.UX_RESEARCHER_USER_MODELER,
    AgentIdentifier.UX_UI_DESIGNER,
    AgentIdentifier.SOFTWARE_ARCHITECT,
    AgentIdentifier.QA_TEST_ENGINEER,
    AgentIdentifier.ACCESSIBILITY_REVIEWER,
)
FIVE_PERSPECTIVES = [
    ("UX", 2),
    ("ACCESSIBILITY", 2),
    ("SOFTWARE_ENGINEERING", 6),
    ("PRODUCT", 2),
    ("SECURITY", 2),
]
UX_DEFINITION = [
    "Write each user story and scenario from the point of view of one twin: the goal, the "
    "context of use and the moment where that person may get stuck.",
    "Each functional requirement serves a need of a twin or of the brief and says what the "
    "person sees after acting.",
]
UX_DESIGN = [
    "Each alternative lets every twin reach their main goal in few steps, shows the result of "
    "each action and lets the person undo or correct a mistake.",
    "The alternatives differ in how the person works, not only in how they look.",
]


class HostedCapturePort:
    def __init__(self):
        self.requests = []

    async def generate(self, request, **options):
        self.requests.append(request)
        return failed_structured_generation_result(
            provider_kind=StructuredGenerationProviderKind.ANTHROPIC_HOSTED,
            code=StructuredGenerationFailureCode.PROVIDER_ERROR,
            message="Captured before inference.",
            retryable=False,
        )


def with_team(request, agent_ids):
    return replace(request, team=replace(request.team, selected_agent_ids=agent_ids))


def requirements_request(agent_ids):
    return with_team(requirements_fixtures.proposal_request(), agent_ids)


def design_request(agent_ids):
    return with_team(design_fixtures.proposal_request(), agent_ids)


def counted(guidance):
    return [(item["perspective"], len(item["considerations"])) for item in guidance]


def without_perspectives(context):
    return {key: value for key, value in context.items() if key != "perspectives"}


def captured(adapter_type, request, configuration, port):
    with pytest.raises(ProposalGenerationError, match="PROVIDER_ERROR"):
        asyncio.run(adapter_type(ProposalGenerator(configuration, port)).propose(request))
    [sent] = port.requests
    return sent, json.loads(sent.input_payload_json)["context"]


def local_configuration(tmp_path):
    generator, _ = make_generator(tmp_path, {})
    return generator.configuration


def instruction_for(agent_ids):
    request = requirements_request(agent_ids)
    _, sources, twins = requirements_context(request)
    call, _, _ = adapter_call(request, requirements_view(generated_specification(), sources, twins))
    return call["instruction"]


def test_every_specialist_brings_the_five_perspectives_right_after_the_limits():
    context, _, _ = requirements_context(requirements_request(EVERY_AGENT))
    keys = list(context)

    assert keys[keys.index("limits") + 1] == "perspectives"
    assert context["perspectives"] == perspective_guidance(EVERY_AGENT, GuidanceStage.DEFINITION)
    assert counted(context["perspectives"]) == FIVE_PERSPECTIVES
    assert context["perspectives"][0]["considerations"] == UX_DEFINITION


def test_the_minimum_team_brings_four_perspectives_and_not_security():
    context, _, _ = requirements_context(requirements_request(MINIMUM_TEAM))

    assert counted(context["perspectives"]) == [
        ("UX", 2),
        ("ACCESSIBILITY", 2),
        ("SOFTWARE_ENGINEERING", 2),
        ("PRODUCT", 2),
    ]
    assert context["perspectives"] == perspective_guidance(MINIMUM_TEAM, GuidanceStage.DEFINITION)


def test_the_change_context_carries_the_same_perspectives():
    request = requirements_request(EVERY_AGENT)
    change = replace(
        request, current_specification=generated_specification(), owner_request=OWNER_REQUEST
    )
    base, _, _ = requirements_context(request)
    context, _, _ = requirements_context(change)

    assert context["purpose"] == "REQUIREMENTS_CHANGE"
    assert context["perspectives"] == base["perspectives"]
    assert counted(context["perspectives"]) == FIVE_PERSPECTIVES


def test_the_context_of_today_moved_only_by_its_perspectives():
    context, _, _ = requirements_context(requirements_fixtures.proposal_request())

    assert counted(context["perspectives"]) == [("PRODUCT", 2)]
    assert sha256(canonical_json(without_perspectives(context))) == (
        CONTEXT_BEFORE_PERSPECTIVES_SHA256
    )


def test_the_instruction_names_the_perspectives_once_right_after_the_proportion():
    instruction = baseline_instruction()

    assert instruction.count(DEFINITION_SENTENCES) == 1
    assert instruction.count("context.perspectives") == 1
    assert (
        f"{PROPORTION_END} {DEFINITION_SENTENCES} Keep criteria concrete and testable."
        in instruction
    )
    assert sha256(instruction.replace(f" {DEFINITION_SENTENCES}", "")) == (
        INSTRUCTION_BEFORE_PERSPECTIVES_SHA256
    )
    assert instruction_for(MINIMUM_TEAM) == instruction_for(EVERY_AGENT) == instruction


def test_the_planning_schemas_ignore_the_perspectives():
    requirements, _, _ = requirements_context(requirements_request(EVERY_AGENT))
    design = hosted_design_context(design_context(design_request(EVERY_AGENT))[0], EVERY_AGENT)

    for draft_type, context, task in (
        (RequirementsDraft, requirements, "requirements"),
        (HostedDesignDraft, design, "design"),
    ):
        guided = draft_type.model_json_schema()
        plain = draft_type.model_json_schema()
        constrain_planning_schema(guided, context, task)
        constrain_planning_schema(plain, without_perspectives(context), task)
        assert guided == plain


def test_the_model_receives_the_perspectives_in_contract_five_with_the_same_schema(tmp_path):
    configuration = local_configuration(tmp_path)
    every, sent = captured(
        ModelRequirementsAdapter, requirements_request(EVERY_AGENT), configuration, CapturePort()
    )
    minimum, _ = captured(
        ModelRequirementsAdapter, requirements_request(MINIMUM_TEAM), configuration, CapturePort()
    )

    assert sent["perspectives"] == perspective_guidance(EVERY_AGENT, GuidanceStage.DEFINITION)
    assert every.output_schema.canonical_schema_json == minimum.output_schema.canonical_schema_json
    assert every.output_schema.schema_id == "proposal-requirements-v5"
    assert every.output_schema.version_number == 5
    assert every.prompt_version_ref == "proposal-requirements-v5"
    assert every.task_id == "proposal-requirements-v1"
    assert every.system_instruction.count(DEFINITION_SENTENCES) == 1


def test_the_hosted_design_receives_the_design_guidance_in_contract_one_hundred_four():
    sent, context = captured(
        ModelDesignAdapter,
        design_request(EVERY_AGENT),
        providers().hosted_model("design"),
        HostedCapturePort(),
    )

    assert context["purpose"] == "DESIGN_ALTERNATIVES_HOSTED"
    assert context["perspectives"] == perspective_guidance(EVERY_AGENT, GuidanceStage.DESIGN)
    assert counted(context["perspectives"]) == FIVE_PERSPECTIVES
    assert context["perspectives"][0]["considerations"] == UX_DESIGN
    assert DESIGN_CONTRACT_VERSIONS["DESIGN_ALTERNATIVES_HOSTED"] == 104
    assert HOSTED_DESIGN_CONTRACT_VERSION == 104
    assert sent.output_schema.schema_id == "proposal-design-v104"
    assert sent.output_schema.version_number == 104
    assert sent.prompt_version_ref == "proposal-design-v104"
    assert sent.task_id == "proposal-design-v1"
    assert sent.system_instruction.count(DESIGN_SENTENCE) == 1


def test_the_local_design_keeps_its_context_its_instruction_and_its_contract(tmp_path):
    request = design_request(EVERY_AGENT)
    sent, context = captured(
        ModelDesignAdapter, request, local_configuration(tmp_path), CapturePort()
    )

    assert "perspectives" not in context
    assert "perspectives" not in design_context(request)[0]
    assert "context.perspectives" not in sent.system_instruction
    assert sent.output_schema.schema_id == "proposal-design-v11"
    assert sent.prompt_version_ref == "proposal-design-v11"


def test_only_the_hosted_design_instruction_names_the_perspectives():
    context, twins = design_context(design_fixtures.proposal_request())
    hosted = hosted_design_instruction(hosted_design_context(context, EVERY_AGENT))
    local = design_instruction("/".join(twins), context["language"])

    assert HOSTED_PERSPECTIVES_INSTRUCTION == DESIGN_SENTENCE
    assert hosted.count(DESIGN_SENTENCE) == 1
    assert f"without quotation marks. {DESIGN_SENTENCE} {HOSTED_SCHEMA_INSTRUCTION}" in hosted
    assert sha256(hosted.replace(f" {DESIGN_SENTENCE}", "")) == (
        HOSTED_INSTRUCTION_BEFORE_PERSPECTIVES_SHA256
    )
    assert "context.perspectives" not in local
