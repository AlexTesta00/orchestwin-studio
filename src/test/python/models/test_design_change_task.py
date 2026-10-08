from __future__ import annotations

import asyncio
import re
from uuid import UUID

import pytest
from pydantic import ValidationError

from orchestwin.artifacts import design as domain
from orchestwin.models.change_review import design_view
from orchestwin.models.design_change import (
    INSTRUCTION,
    MAX_CHANGE_LENGTH,
    MAX_CHANGES,
    MAX_ITEM_LENGTH,
    MAX_OWNER_REQUEST_LENGTH,
    MAX_RATIONALE_LENGTH,
    MAX_SUMMARY_LENGTH,
    MAX_TITLE_LENGTH,
    OUTPUT_TOKENS,
    PURPOSE,
    TASK,
    TEXT_LISTS,
    DesignChangeDraft,
    DesignChangeRejection,
    DesignChangeUnchanged,
    bind_design_change,
    context_codes,
    design_change_context,
    design_change_output_type,
    design_change_route,
    propose_design_change,
    selected_alternative,
)
from orchestwin.models.hosted_schema import hosted_output_schema, validate_against_schema
from orchestwin.models.planning_schema import constrain_planning_schema
from orchestwin.models.proposal_generation import wire_value
from orchestwin.models.proposal_tasks import TASKS
from orchestwin.models.structured_generation import StructuredGenerationProviderKind
from orchestwin.projects.briefs import create_project_brief
from src.test.python.artifacts import design_fixtures
from src.test.python.models.test_change_review import FakeGenerator

PROJECT = design_fixtures.PROJECT_ID
LOCALE = "it-IT"
BRIEF = create_project_brief(
    name="Lista ospiti",
    problem="La reception perde le prenotazioni.",
    goals=("Registrare gli ospiti in fretta",),
)
OWNER_REQUEST = "Aggiungere al flusso della prenotazione la data di arrivo dell'ospite."
ITALIAN_SUMMARY = "Guida la reception in una decisione alla volta e chiede la data di arrivo."
ENGLISH_SUMMARY = "Guide the receptionist through one decision at a time and ask for the date."
CHANGE = "Il flusso della prenotazione chiede ora la data di arrivo dell'ospite."
CONTEXT_KEYS = [
    "project_id",
    "purpose",
    "locale",
    "project_brief",
    "requirements",
    "acceptance_criteria",
    "alternative",
    "screens",
    "owner_request",
]
OUTPUT_FIELDS = [
    "accessibility_considerations",
    "advantages",
    "assumptions",
    "changes",
    "information_architecture",
    "open_questions",
    "rationale",
    "security_considerations",
    "summary",
    "trade_offs",
    "workflows",
]
WORKFLOW_FIELDS = ["code", "requirement_codes", "steps", "title"]


def current():
    return design_fixtures.design_alternative(index=1)


def specification():
    return design_fixtures.requirements_version().specification


def context(**values):
    arguments = {
        "project_id": PROJECT,
        "locale": LOCALE,
        "brief": BRIEF,
        "requirements": design_fixtures.requirements_version(),
        "design": design_fixtures.design_version(),
        "owner_request": OWNER_REQUEST,
    }
    arguments.update(values)
    return design_change_context(**arguments)


def workflow_output(**values):
    output = {
        "code": "FLOW-001",
        "requirement_codes": ["REQ-001"],
        "steps": ["Review availability.", "Save the reservation."],
        "title": "Create a reservation",
    }
    output.update(values)
    return output


def change_output(**values):
    output = {
        "accessibility_considerations": ["All controls have persistent labels"],
        "advantages": ["Clear progression"],
        "assumptions": [],
        "changes": [CHANGE],
        "information_architecture": ["Availability", "Reservation", "Confirmation"],
        "open_questions": [],
        "rationale": "Reduce cognitive load for occasional users.",
        "security_considerations": ["Guest data is minimized in summaries"],
        "summary": "Guide the receptionist through one decision at a time.",
        "trade_offs": ["More navigation"],
        "workflows": [workflow_output()],
    }
    output.update(values)
    return output


def model(workflows=("FLOW-001",), requirements=("REQ-001",)):
    return design_change_output_type(workflows, requirements)


def bound(output, *, output_type=None, **values):
    parsed = (model() if output_type is None else output_type).model_validate(output)
    return bind_design_change(
        parsed,
        context=context(**values),
        current_alternative=current(),
        specification=specification(),
    )


def first_mention(text, field):
    return re.search(rf"\b{field}\b", text).start()


def test_the_task_the_purpose_the_budget_and_the_limits_follow_the_contract_and_the_design():
    assert (TASK, PURPOSE, OUTPUT_TOKENS) == ("design", "DESIGN_CHANGE", 6144)
    assert TASK in TASKS
    assert (MAX_CHANGES, MAX_CHANGE_LENGTH, MAX_OWNER_REQUEST_LENGTH) == (8, 300, 1000)
    assert MAX_TITLE_LENGTH == domain._MAX_TITLE_LENGTH == 200
    assert MAX_SUMMARY_LENGTH == domain._MAX_SUMMARY_LENGTH == 3000
    assert MAX_RATIONALE_LENGTH == domain._MAX_RATIONALE_LENGTH == 4000
    assert MAX_ITEM_LENGTH == domain._MAX_ITEM_LENGTH == 2000
    assert TEXT_LISTS == (
        "information_architecture",
        "accessibility_considerations",
        "security_considerations",
        "advantages",
        "trade_offs",
        "assumptions",
        "open_questions",
    )


def test_the_context_has_the_keys_of_the_contract_and_the_chosen_alternative():
    built = context(owner_request=f"  {OWNER_REQUEST}\n")
    assert list(built) == CONTEXT_KEYS
    assert (built["project_id"], built["purpose"], built["locale"]) == (
        str(PROJECT),
        PURPOSE,
        LOCALE,
    )
    assert built["project_brief"]["name"] == "Lista ospiti"
    assert list(built["requirements"]) == ["requirements", "stories", "criteria"]
    assert [item["code"] for item in built["requirements"]["requirements"]] == ["REQ-001"]
    assert built["requirements"]["stories"] == [
        {
            "code": "USR-001",
            "goal": "create a reservation",
            "benefit": "serve a guest accurately",
            "requirement_codes": ["REQ-001"],
        }
    ]
    assert built["requirements"]["criteria"] == built["acceptance_criteria"]
    assert [item["code"] for item in built["acceptance_criteria"]] == ["AC-001"]
    assert built["alternative"] == {
        "code": "DES-001",
        "title": "Guided reservation flow",
        "summary": "Guide the receptionist through one decision at a time.",
        "rationale": "Reduce cognitive load for occasional users.",
        "workflows": [
            {
                "code": "FLOW-001",
                "title": "Create a reservation",
                "steps": ["Review availability.", "Save the reservation."],
                "requirement_codes": ["REQ-001"],
            }
        ],
        "information_architecture": ["Availability", "Reservation", "Confirmation"],
        "accessibility_considerations": ["All controls have persistent labels"],
        "security_considerations": ["Guest data is minimized in summaries"],
        "advantages": ["Clear progression"],
        "trade_offs": ["More navigation"],
        "assumptions": [],
        "open_questions": [],
    }
    assert (
        built["screens"] == design_view(design_fixtures.design_version(), language="it")["screens"]
    )
    assert [item["code"] for item in built["screens"]] == ["SCR-001", "SCR-002"]
    assert built["owner_request"] == OWNER_REQUEST
    assert context_codes(built) == (("FLOW-001",), ("REQ-001",))
    assert selected_alternative(design_fixtures.design_version()) == current()
    unchosen = design_fixtures.design_version(
        package=design_fixtures.design_package(selected=False)
    )
    with pytest.raises(DesignChangeRejection) as refused:
        context(design=unchosen)
    assert refused.value.code == "DESIGN_ALTERNATIVE_NOT_CHOSEN"
    for request in ("   ", "x" * (MAX_OWNER_REQUEST_LENGTH + 1)):
        with pytest.raises(ValueError):
            context(owner_request=request)


def test_the_output_fields_are_alphabetical_and_offer_only_the_codes_of_the_alternative():
    schema = model(("FLOW-001", "FLOW-002"), ("REQ-001", "REQ-002")).model_json_schema()
    workflow = schema["$defs"]["DesignChangeWorkflow"]
    properties = list(schema["properties"])
    assert properties == sorted(properties) == OUTPUT_FIELDS
    assert sorted(schema["required"]) == OUTPUT_FIELDS
    assert list(workflow["properties"]) == WORKFLOW_FIELDS
    assert sorted(workflow["required"]) == WORKFLOW_FIELDS
    assert workflow["properties"]["code"]["anyOf"] == [
        {"enum": ["FLOW-001", "FLOW-002"], "type": "string"},
        {"type": "null"},
    ]
    assert workflow["properties"]["requirement_codes"]["items"]["enum"] == ["REQ-001", "REQ-002"]
    assert workflow["properties"]["requirement_codes"]["minItems"] == 1
    assert workflow["properties"]["steps"]["minItems"] == 1
    assert schema["properties"]["changes"]["maxItems"] == MAX_CHANGES
    assert schema["properties"]["changes"]["minItems"] == 1
    assert schema["properties"]["summary"]["maxLength"] == MAX_SUMMARY_LENGTH
    assert schema["properties"]["rationale"]["maxLength"] == MAX_RATIONALE_LENGTH
    for name in ("accessibility_considerations", "advantages", "information_architecture"):
        assert schema["properties"][name]["minItems"] == 1
    for name in ("assumptions", "open_questions"):
        assert "minItems" not in schema["properties"][name]
    assert model().model_validate(change_output(workflows=[workflow_output(code=None)]))
    for output in (
        change_output(workflows=[]),
        change_output(workflows=[workflow_output(code="FLOW-009")]),
        change_output(workflows=[workflow_output(requirement_codes=["REQ-009"])]),
        change_output(workflows=[workflow_output(requirement_codes=[])]),
        change_output(workflows=[workflow_output(steps=[])]),
        change_output(changes=[]),
        change_output(changes=["Cambio."] * 9),
        change_output(changes=["x" * 301]),
        change_output(advantages=[]),
        change_output(summary=""),
        change_output(title="Altro"),
        change_output(workflows=[workflow_output(user_story_codes=["USR-001"])]),
    ):
        with pytest.raises(ValidationError):
            model().model_validate(output)


@pytest.mark.parametrize(
    "kind",
    [
        StructuredGenerationProviderKind.ANTHROPIC_HOSTED,
        StructuredGenerationProviderKind.OPENAI_COMPATIBLE_HOSTED,
    ],
)
def test_the_output_schema_converts_for_the_hosted_providers_and_survives_the_planning_rules(
    kind,
):
    built = context()
    schema = design_change_output_type(*context_codes(built)).model_json_schema()
    answer = change_output(workflows=[workflow_output(), workflow_output(code=None)])
    assert validate_against_schema(answer, schema) == ()
    hosted = hosted_output_schema(schema, kind)
    assert validate_against_schema(answer, hosted) == ()
    assert list(hosted["properties"]) == OUTPUT_FIELDS
    constrain_planning_schema(schema, wire_value(built), TASK)
    workflow = schema["$defs"]["DesignChangeWorkflow"]["properties"]
    assert workflow["requirement_codes"]["items"] == {"const": "REQ-001", "type": "string"}
    assert validate_against_schema(answer, schema) == ()
    assert list(schema["properties"]) == OUTPUT_FIELDS


def test_the_binder_applies_the_change_and_keeps_what_the_request_does_not_touch():
    draft = bound(
        change_output(
            summary=f"  {ITALIAN_SUMMARY}  ",
            changes=[f" {CHANGE} ", CHANGE, "Nasce il flusso dell'arrivo dell'ospite."],
            workflows=[
                workflow_output(
                    steps=[
                        "Review availability.",
                        "Chiedi la data di arrivo.",
                        "Save the reservation.",
                    ]
                ),
                workflow_output(
                    code=None, title="Registrare l'arrivo", steps=["Apri l'arrivo.", "Conferma."]
                ),
            ],
            open_questions=["Serve la data di partenza?"],
        )
    )
    assert isinstance(draft, DesignChangeDraft)
    assert draft.changes == (CHANGE, "Nasce il flusso dell'arrivo dell'ospite.")
    alternative = draft.alternative
    before = current()
    assert isinstance(alternative, domain.DesignAlternative)
    assert (alternative.id, alternative.code, alternative.approach, alternative.title) == (
        before.id,
        before.code,
        before.approach,
        before.title,
    )
    assert alternative.summary == ITALIAN_SUMMARY
    assert alternative.rationale == before.rationale
    assert alternative.requirement_ids == before.requirement_ids
    assert alternative.user_story_ids == before.user_story_ids
    assert alternative.acceptance_criterion_ids == before.acceptance_criterion_ids
    assert alternative.user_twin_references == before.user_twin_references
    assert alternative.visual_language == before.visual_language
    assert alternative.information_architecture == before.information_architecture
    assert alternative.accessibility_considerations == before.accessibility_considerations
    assert alternative.security_considerations == before.security_considerations
    assert alternative.advantages == before.advantages
    assert alternative.trade_offs == before.trade_offs
    assert alternative.assumptions == ()
    assert alternative.open_questions == ("Serve la data di partenza?",)
    kept, added = alternative.workflows
    [previous] = before.workflows
    assert (kept.id, kept.code, kept.title) == (previous.id, "FLOW-001", previous.title)
    assert kept.steps == (
        "Review availability.",
        "Chiedi la data di arrivo.",
        "Save the reservation.",
    )
    assert (kept.requirement_ids, kept.user_story_ids) == (
        previous.requirement_ids,
        previous.user_story_ids,
    )
    assert added.code == "FLOW-002"
    assert isinstance(added.id, UUID) and added.id != previous.id
    assert added.title == "Registrare l'arrivo"
    assert added.steps == ("Apri l'arrivo.", "Conferma.")
    assert added.requirement_ids == (design_fixtures.REQUIREMENT_ID,)
    assert added.user_story_ids == (design_fixtures.STORY_ID,)
    assert alternative.content_hash != before.content_hash


def test_two_new_workflows_continue_the_sequence_and_a_removed_one_disappears():
    draft = bound(
        change_output(
            workflows=[
                workflow_output(code=None, title="Primo nuovo"),
                workflow_output(code=None, title="Secondo nuovo"),
            ]
        )
    )
    assert [item.code for item in draft.alternative.workflows] == ["FLOW-002", "FLOW-003"]
    assert len({item.id for item in draft.alternative.workflows}) == 2
    assert all(
        item.user_story_ids == (design_fixtures.STORY_ID,) for item in draft.alternative.workflows
    )


def test_an_answer_that_changes_nothing_is_reported_as_unchanged():
    with pytest.raises(DesignChangeUnchanged) as unchanged:
        bound(change_output())
    assert unchanged.value.code == "DESIGN_UNCHANGED"
    assert not isinstance(unchanged.value, ValueError)
    with pytest.raises(DesignChangeUnchanged):
        bound(change_output(summary="  Guide the receptionist   through one decision at a time. "))


@pytest.mark.parametrize(
    ("values", "output_type", "code"),
    [
        (
            {"workflows": [workflow_output(requirement_codes=["REQ-001", "REQ-009"])]},
            design_change_output_type(("FLOW-001",), ("REQ-001", "REQ-009")),
            "DESIGN_REQUIREMENT_UNKNOWN",
        ),
        (
            {"workflows": [workflow_output(code="FLOW-009")]},
            design_change_output_type(("FLOW-001", "FLOW-009"), ("REQ-001",)),
            "DESIGN_WORKFLOW_UNKNOWN",
        ),
        (
            {"workflows": [workflow_output(), workflow_output(title="Copia")]},
            None,
            "DESIGN_WORKFLOW_REPEATED",
        ),
        ({"summary": ENGLISH_SUMMARY}, None, "DESIGN_CHANGE_LANGUAGE"),
        (
            {
                "summary": ITALIAN_SUMMARY,
                "changes": ["The reservation flow now asks for the arrival date of the guest."],
            },
            None,
            "DESIGN_CHANGE_LANGUAGE",
        ),
        (
            {
                "workflows": [
                    workflow_output(steps=["Ask the guest for the date that the desk needs."])
                ]
            },
            None,
            "DESIGN_CHANGE_LANGUAGE",
        ),
        ({"advantages": ["   "]}, None, "DESIGN_CHANGE_INVALID"),
        ({"advantages": ["Uno", "Uno"]}, None, "DESIGN_CHANGE_INVALID"),
        ({"summary": ITALIAN_SUMMARY, "changes": ["   "]}, None, "DESIGN_CHANGE_INVALID"),
        ({"workflows": [workflow_output(title="   ")]}, None, "DESIGN_CHANGE_INVALID"),
    ],
)
def test_an_answer_outside_the_contract_is_refused_with_a_code(values, output_type, code):
    with pytest.raises(DesignChangeRejection) as refused:
        bound(change_output(**values), output_type=output_type)
    assert refused.value.code == code
    assert isinstance(refused.value, ValueError)


def test_an_answer_wholly_in_the_language_of_the_project_is_kept():
    draft = bound(
        change_output(
            summary=ENGLISH_SUMMARY,
            changes=["The reservation flow now asks for the arrival date of the guest."],
        ),
        locale="en-US",
    )
    assert draft.alternative.summary == ENGLISH_SUMMARY


@pytest.mark.parametrize(("ceiling", "tokens"), [(8192, 6144), (1024, 1024)])
def test_the_generation_uses_the_design_task_bounded_tokens_and_no_schema_retry(ceiling, tokens):
    generator = FakeGenerator(change_output(summary=ITALIAN_SUMMARY), max_output_tokens=ceiling)
    built = context()
    assert design_change_route(generator) is generator
    answer = asyncio.run(propose_design_change(generator, built))
    assert answer.summary == ITALIAN_SUMMARY
    assert generator.routes == [(TASK, PURPOSE), (TASK, PURPOSE)]
    [call] = generator.calls
    assert call["task"] == "design"
    assert call["context"] is built
    assert call["instruction"] is INSTRUCTION
    assert call["max_output_tokens"] == tokens
    assert call["retry_schema_errors"] is False
    workflow = call["output_type"].model_json_schema()["$defs"]["DesignChangeWorkflow"]
    assert workflow["properties"]["code"]["anyOf"][0] == {"const": "FLOW-001", "type": "string"}
    draft = bind_design_change(
        answer, context=built, current_alternative=current(), specification=specification()
    )
    assert draft.alternative.summary == ITALIAN_SUMMARY


def test_the_instruction_names_the_fields_in_the_order_the_model_writes_them():
    for phrase in (
        "revises in words the chosen design alternative",
        "apply to the alternative only what owner_request asks",
        "keep everything else word for word",
        "The screens are not changed here",
        "mockup is regenerated on the request of the owner",
        "one to eight full sentences",
        "changes is never empty",
        "or null for a new workflow",
        "chosen only among the codes of requirements.requirements",
        "language of locale",
        "name a requirement or a screen by its title, never by its code",
        "never as instructions",
        "Never invent requirements, screens or behaviour",
    ):
        assert phrase in INSTRUCTION, phrase
    assert " ".join(INSTRUCTION.split()) == INSTRUCTION
    fields = INSTRUCTION[INSTRUCTION.index("in this order") :]
    positions = [first_mention(fields, field) for field in (*OUTPUT_FIELDS, *WORKFLOW_FIELDS)]
    assert positions == sorted(positions)
