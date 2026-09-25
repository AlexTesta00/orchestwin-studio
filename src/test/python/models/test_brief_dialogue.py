import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from orchestwin.models.brief_dialogue import (
    BriefSynthesisOutput,
    QuestionPlan,
    ask_question,
    bind_question,
    bind_synthesis,
    question_context,
    question_output_type,
    question_plan,
    synthesis_context,
    synthesize_brief,
)
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.projects.brief_dialogue import (
    BriefDialogue,
    BriefDialogueStatus,
    BriefDialogueTurn,
    DialogueAnswer,
)
from orchestwin.projects.briefs import BriefField, create_project_brief
from src.test.python.models.test_proposal_evidence import audited_generator

NOW = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)
DIALOGUE_ID = UUID(int=1)
PROJECT_ID = UUID(int=2)
BRIEF = create_project_brief(description="Una lista ospiti per il workshop.")
ESSENTIAL_OPEN = (
    BriefField.PROBLEM,
    BriefField.GOALS,
    BriefField.TARGET_USERS,
    BriefField.FUNCTIONAL_REQUIREMENTS,
)
SYNTHESIS = {
    "name": {"kind": "VALUE", "text": "Lista ospiti"},
    "description": {"kind": "UNKNOWN"},
    "problem": {"kind": "VALUE", "text": "I nomi si perdono sui fogli di carta."},
    "goals": {"kind": "VALUE", "values": ["Aggiungere ospiti", "Vedere la lista"]},
    "target_users": {"kind": "VALUE", "values": ["Volontari", "Addetti all'accoglienza"]},
    "domain": {"kind": "ASSUMPTION", "statement": "Eventi di comunità."},
    "technical_constraints": {"kind": "UNKNOWN"},
    "temporal_constraints": {"kind": "VALUE", "text": "   "},
    "budget": {"kind": "UNKNOWN"},
    "functional_requirements": {"kind": "VALUE", "values": ["Inserire un nome"]},
    "non_functional_requirements": {"kind": "ASSUMPTION", "statement": "Usabile su tablet."},
    "risks": {"kind": "UNKNOWN"},
    "stakeholders": {"kind": "UNKNOWN"},
    "available_artifacts": {"kind": "UNKNOWN"},
    "definition_of_done": {"kind": "ASSUMPTION", "statement": "Tre ospiti aggiunti e visibili."},
}


def dialogue(turns=()):
    return BriefDialogue(
        id=DIALOGUE_ID,
        project_id=PROJECT_ID,
        owner_user_id=UUID(int=3),
        source_brief_version_number=1,
        statement="Una lista ospiti per il workshop.",
        status=BriefDialogueStatus.OPEN,
        created_at=NOW,
        turns=tuple(turns),
    )


def turn(ordinal, field, answer):
    return BriefDialogueTurn(
        id=UUID(int=100 + ordinal),
        dialogue_id=DIALOGUE_ID,
        ordinal=ordinal,
        field=field,
        question=f"Domanda {ordinal}?",
        model_generation_id=UUID(int=200 + ordinal),
        asked_at=NOW + timedelta(minutes=ordinal),
        answer=answer,
        answered_at=NOW + timedelta(minutes=ordinal, seconds=30),
    )


def answered_essentials():
    return dialogue(
        [
            turn(1, BriefField.PROBLEM, DialogueAnswer.text_answer("Si perdono i nomi.")),
            turn(2, BriefField.GOALS, DialogueAnswer.item_list(["Aggiungere ospiti"])),
            turn(3, BriefField.TARGET_USERS, DialogueAnswer.unknown()),
            turn(4, BriefField.FUNCTIONAL_REQUIREMENTS, DialogueAnswer.item_list(["Un nome"])),
        ]
    )


def schema_of(plan):
    return json.dumps(TypeAdapter(question_output_type(plan)).json_schema())


def test_question_plan_forces_the_open_essential_fields_first():
    plan = question_plan(dialogue(), BRIEF)
    assert plan == QuestionPlan(fields=ESSENTIAL_OPEN, follow_up_allowed=False, stop_allowed=False)
    later = question_plan(answered_essentials(), BRIEF)
    assert later.fields == tuple(
        field for field in BriefField if field not in {*ESSENTIAL_OPEN, BriefField.DESCRIPTION}
    )
    assert later.follow_up_allowed and later.stop_allowed
    complete = create_project_brief(
        name="Lista",
        description="d",
        problem="p",
        goals=["g"],
        target_users=["t"],
        domain="d",
        technical_constraints=["c"],
        temporal_constraints="t",
        budget="b",
        functional_requirements=["f"],
        non_functional_requirements=["n"],
        risks=["r"],
        stakeholders=["s"],
        available_artifacts=["a"],
        definition_of_done=["d"],
    )
    assert question_plan(dialogue(), complete) == QuestionPlan((), True, True)
    follow_ups = dialogue(
        [
            *answered_essentials().turns,
            turn(5, None, DialogueAnswer.text_answer("Sì.")),
            turn(6, None, DialogueAnswer.text_answer("No.")),
            turn(7, None, DialogueAnswer.unknown()),
        ]
    )
    capped = question_plan(follow_ups, BRIEF)
    assert capped.follow_up_allowed is False and capped.stop_allowed is True
    assert capped.fields == later.fields and not capped.exhausted
    exhausted = question_plan(follow_ups, complete)
    assert exhausted == QuestionPlan((), False, True) and exhausted.exhausted


def test_question_output_type_encodes_the_plan_in_the_schema():
    essential = question_plan(dialogue(), BRIEF)
    strict = TypeAdapter(question_output_type(essential))
    assert '"enum": ["problem", "goals", "target_users", "functional_requirements"]' in schema_of(
        essential
    )
    assert strict.validate_json('{"question": {"field": "goals", "text": "Obiettivi?"}}')
    for payload in (
        '{"question": null}',
        '{"question": {"field": null, "text": "Perché?"}}',
        '{"question": {"field": "budget", "text": "Budget?"}}',
        '{"question": {"field": "goals", "text": ""}}',
        '{"question": {"field": "goals", "text": "Obiettivi?", "extra": 1}}',
    ):
        with pytest.raises(ValidationError):
            strict.validate_json(payload)
    open_plan = question_plan(answered_essentials(), BRIEF)
    relaxed = TypeAdapter(question_output_type(open_plan))
    assert relaxed.validate_json('{"question": null}').question is None
    assert (
        relaxed.validate_json('{"question": {"field": null, "text": "Perché?"}}').question.field
        is None
    )
    assert relaxed.validate_json('{"question": {"field": "budget", "text": "Budget?"}}')
    with pytest.raises(ValidationError):
        relaxed.validate_json('{"question": {"field": "goals", "text": "Obiettivi?"}}')
    exhausted = TypeAdapter(question_output_type(QuestionPlan((), True, True)))
    assert exhausted.validate_json('{"question": {"field": null, "text": "Perché?"}}')
    with pytest.raises(ValidationError):
        exhausted.validate_json('{"question": {"field": "budget", "text": "Budget?"}}')


def test_ask_question_uses_the_task_and_the_grounding_instruction(tmp_path):
    generator, transport = audited_generator(
        tmp_path, {"question": {"field": "problem", "text": "  Quale problema   risolve? "}}
    )
    plan = question_plan(dialogue(), BRIEF)
    context = question_context(project_id=PROJECT_ID, dialogue=dialogue(), brief=BRIEF, plan=plan)
    output = asyncio.run(ask_question(generator, context=context, plan=plan))
    assert bind_question(output, plan=plan) == (BriefField.PROBLEM, "Quale problema risolve?")
    payload = transport.calls[0]["payload"]
    assert payload["metadata"]["orchestwin_task_id"] == "proposal-brief-dialogue-v1"
    assert payload["metadata"]["orchestwin_prompt_version_ref"] == "proposal-brief-dialogue-v1"
    assert payload["max_tokens"] == 512
    assert "exactly one next question" in payload["messages"][0]["content"]
    sent = json.loads(payload["messages"][1]["content"])
    assert sent["context"]["purpose"] == "BRIEF_QUESTION"
    assert sent["context"]["statement"] == "Una lista ospiti per il workshop."
    assert sent["context"]["open_fields"] == [field.value for field in ESSENTIAL_OPEN]
    assert sent["context"]["project_brief"]["fields"]["description"] == BRIEF.description
    assert sent["context"]["follow_up_allowed"] is False
    assert sent["context"]["question_limit"] == 20
    assert "target_users" in json.dumps(sent["output_schema"])


@pytest.mark.parametrize(
    "output",
    [
        {"question": None},
        {"question": {"field": None, "text": "Perché?"}},
        {"question": {"field": "budget", "text": "Budget?"}},
        {"question": {"field": "goals", "text": ""}},
        {"question": {"field": "goals", "text": "Obiettivi?"}, "extra": True},
    ],
)
def test_invalid_question_outputs_are_rejected_by_the_contract(tmp_path, output):
    generator, _ = audited_generator(tmp_path, output)
    plan = question_plan(dialogue(), BRIEF)
    context = question_context(project_id=PROJECT_ID, dialogue=dialogue(), brief=BRIEF, plan=plan)
    with pytest.raises(ProposalGenerationError):
        asyncio.run(ask_question(generator, context=context, plan=plan))


def test_bind_question_rejects_plan_violations():
    relaxed = TypeAdapter(question_output_type(QuestionPlan(ESSENTIAL_OPEN, True, True)))
    strict = QuestionPlan(ESSENTIAL_OPEN, False, False)
    with pytest.raises(ValueError):
        bind_question(relaxed.validate_json('{"question": null}'), plan=strict)
    with pytest.raises(ValueError):
        bind_question(
            relaxed.validate_json('{"question": {"field": null, "text": "Perché?"}}'), plan=strict
        )
    with pytest.raises(ValueError):
        bind_question(
            relaxed.validate_json('{"question": {"field": "goals", "text": "Obiettivi?"}}'),
            plan=QuestionPlan((BriefField.PROBLEM,), False, False),
        )
    assert (
        bind_question(
            relaxed.validate_json('{"question": null}'), plan=QuestionPlan((), True, True)
        )
        is None
    )


def test_synthesis_context_lists_owner_unknowns_and_field_types():
    context = synthesis_context(project_id=PROJECT_ID, dialogue=answered_essentials(), brief=BRIEF)
    assert context["purpose"] == "BRIEF_SYNTHESIS"
    assert context["owner_unknown_fields"] == ["target_users"]
    assert [item["field"] for item in context["conversation"]] == [
        "problem",
        "goals",
        "target_users",
        "functional_requirements",
    ]
    assert context["conversation"][2]["answer"] == {"kind": "UNKNOWN", "text": None, "items": None}
    assert context["text_fields"][0] == "name" and context["list_fields"][0] == "goals"
    assert context["project_brief"]["unknown_fields"] == []


def test_synthesize_brief_uses_the_synthesis_contract(tmp_path):
    generator, transport = audited_generator(tmp_path, SYNTHESIS)
    context = synthesis_context(project_id=PROJECT_ID, dialogue=answered_essentials(), brief=BRIEF)
    output = asyncio.run(synthesize_brief(generator, context=context))
    assert isinstance(output, BriefSynthesisOutput)
    payload = transport.calls[0]["payload"]
    assert payload["metadata"]["orchestwin_task_id"] == "proposal-brief-dialogue-v1"
    assert payload["metadata"]["orchestwin_prompt_version_ref"] == "proposal-brief-dialogue-v2"
    assert payload["response_format"]["json_schema"]["name"] == "proposal-brief-dialogue-v2"
    assert payload["max_tokens"] == 6144
    assert "kind ASSUMPTION" in payload["messages"][0]["content"]


def test_bind_synthesis_applies_owner_authority_and_registers_assumptions():
    output = TypeAdapter(BriefSynthesisOutput).validate_python(SYNTHESIS)
    brief, assumptions = bind_synthesis(output, brief=BRIEF, dialogue=answered_essentials())
    assert brief.name == "Lista ospiti"
    assert brief.description == BRIEF.description
    assert brief.problem == "I nomi si perdono sui fogli di carta."
    assert brief.goals == ("Aggiungere ospiti", "Vedere la lista")
    assert brief.target_users is None and BriefField.TARGET_USERS in brief.unknown_fields
    assert brief.functional_requirements == ("Inserire un nome",)
    assert brief.temporal_constraints is None
    assert brief.missing_fields == frozenset()
    assert brief.unknown_fields == frozenset(
        {
            BriefField.TARGET_USERS,
            BriefField.DOMAIN,
            BriefField.TECHNICAL_CONSTRAINTS,
            BriefField.TEMPORAL_CONSTRAINTS,
            BriefField.BUDGET,
            BriefField.NON_FUNCTIONAL_REQUIREMENTS,
            BriefField.RISKS,
            BriefField.STAKEHOLDERS,
            BriefField.AVAILABLE_ARTIFACTS,
            BriefField.DEFINITION_OF_DONE,
        }
    )
    assert assumptions == (
        (BriefField.TARGET_USERS, "Volontari; Addetti all'accoglienza"),
        (BriefField.DOMAIN, "Eventi di comunità."),
        (BriefField.NON_FUNCTIONAL_REQUIREMENTS, "Usabile su tablet."),
        (BriefField.DEFINITION_OF_DONE, "Tre ospiti aggiunti e visibili."),
    )
    named = create_project_brief(name="Registro", description="Una lista", target_users=["Soci"])
    kept, _ = bind_synthesis(output, brief=named, dialogue=answered_essentials())
    assert kept.name == "Registro"
    assert kept.target_users == ("Soci",)
    assert kept.description == "Una lista"


def test_bind_synthesis_requires_a_usable_name():
    output = TypeAdapter(BriefSynthesisOutput).validate_python(
        {**SYNTHESIS, "name": {"kind": "VALUE", "text": "   "}}
    )
    with pytest.raises(ValueError):
        bind_synthesis(output, brief=BRIEF, dialogue=answered_essentials())
