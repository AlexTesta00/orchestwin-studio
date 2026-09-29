from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from orchestwin.artifacts.design_discussion import (
    MAX_REACTION_REASON_LENGTH,
    MAX_STATEMENT_LENGTH,
    DiscussionProposalTarget,
    DiscussionStance,
    ReactionVerdict,
    TwinReaction,
    create_discussion_round,
)
from orchestwin.artifacts.design_evaluation import design_review_view
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.models.output_language import written_in_another_language
from orchestwin.models.twin_discussion import (
    ANSWER_OUTPUT_LENGTH,
    ARGUMENT_OUTPUT_LENGTH,
    FOLLOW_UP_INSTRUCTION,
    HOSTED_FOLLOW_UP_INSTRUCTION,
    HOSTED_STATEMENT_INSTRUCTION,
    HOSTED_SYNTHESIS_INSTRUCTION,
    NAMES_INSTEAD_OF_CODES,
    POSITION_OUTPUT_LENGTH,
    PROPOSAL_OUTPUT_LENGTH,
    QUESTION_OUTPUT_LENGTH,
    REASON_OUTPUT_LENGTH,
    STATEMENT_INSTRUCTION,
    STATEMENT_OUTPUT_TOKENS,
    SUBJECT_OUTPUT_LENGTH,
    SYNTHESIS_INSTRUCTION,
    SYNTHESIS_OUTPUT_TOKENS,
    bind_statement,
    bind_synthesis,
    complete_sentences,
    discussion_findings,
    known_observations,
    moderate_discussion,
    repeats_previous_statement,
    screen_titles,
    speak_as_twin,
    statement_context,
    statement_instruction,
    statement_output_type,
    synthesis_context,
    synthesis_output_type,
    twin_keys,
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
from orchestwin.twins.user_twins import UserTwinField
from src.test.python.artifacts import design_fixtures
from src.test.python.models.test_proposal_evidence import audited_generator
from src.test.python.twins.test_user_modeling_persistence import observation, twin_version

SECOND_TWIN_ID = UUID("00000000-0000-4000-8000-000000000032")
THIRD_TWIN_ID = UUID("00000000-0000-4000-8000-000000000033")
RUN_ID = UUID("00000000-0000-4000-8000-000000000901")
NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
STATIC_MOCKUP = (
    "The mockup is static and its sample values, such as names, numbers or texts introduced "
    "by a word like example, only illustrate the content: never object that a value is an "
    "example, that it is not real or that it does not update. Never invent research"
)
OWNER_ANSWER = (
    "answer_to_owner answers the owner's note directly, in at most 60 words, when owner_note is "
    "present, and is null otherwise"
)
NAMES = "In every text call the other twins by their names in participants, never by their keys"
LANGUAGE = (
    "Write every text in the language of locale, including each reason, answer_to_owner and "
    "every proposal, even when parts of design or of the other texts are written in another "
    "language."
)
STATEMENT_FIELDS = [
    "answer_to_owner",
    "argument",
    "confidence",
    "grounded_on",
    "proposals",
    "reactions",
    "stance",
]
STATEMENT = {
    "answer_to_owner": None,
    "argument": "  Il modulo   è chiaro, ma per me la ricerca è lenta. ",
    "confidence": 0.754,
    "grounded_on": ["user_twin.goals", "user_twin.goals", "user_twin.frustrations"],
    "proposals": ["Mostrare la ricerca in alto.", " Mostrare la ricerca  in alto. "],
    "reactions": [],
    "stance": "CONCERN",
}
OPENING = {
    "answer_to_owner": None,
    "argument": "Di notte cerco le prenotazioni in fretta e il flusso guidato mi basta.",
    "confidence": 0.6,
    "grounded_on": ["user_twin.context_of_use"],
    "proposals": [],
    "reactions": [],
    "stance": "SUPPORT",
}
REPLY = {
    "answer_to_owner": None,
    "argument": "Dopo Receptionist Twin accetto la ricerca in alto, ma di notte il flusso resti breve.",
    "confidence": 0.6,
    "grounded_on": ["user_twin.context_of_use"],
    "proposals": ["Mostrare la ricerca in alto."],
    "reactions": [{"reason": "Anche io cerco in fretta.", "twin": "T1", "verdict": "PARTLY"}],
    "stance": "SUPPORT",
}
NOTE = "Ditemi se il riepilogo finale vi basta."
ANSWER = "Sì, il riepilogo mi basta se resta leggibile di notte."
CUT_SENTENCE = "Come T2, trovo chiaro il modulo."
LOCAL_SHA256 = (
    "496ed38226bd2a77775a8239bfc72c1afa1d249ed04379ff1ba59fa3423c2b4e",
    "17c23d194f2d7a2f0b2cf6abdd8e41de9973af483f62d5b869af12d9d8364ba1",
    "b7b97c50ed75c23395d1f731a36295d94ad8c0396690e5194f604538b7456298",
)
TITLES_NOT_CODES = (
    "In every text name a screen by its title between quotation marks, an element by the text "
    "that it shows and a workflow by its name: never write a code such as SCR-004, ELM-012 or "
    "FLOW-002."
)
ENGLISH_REASON = (
    "T2 prioritizes accuracy and sharing, which aligns with my need for reliable calculations "
    "but conflicts with my focus on speed and simplicity."
)


def point(subject, verdict, *positions):
    return {
        "positions": [
            {"position": position, "twin": f"T{index}"}
            for index, position in enumerate(positions, 1)
        ],
        "subject": subject,
        "verdict": verdict,
    }


SYNTHESIS = {
    "discussion_points": [
        point("Il flusso è chiaro.", "AGREEMENT", "Il flusso è chiaro.", "Mi è chiaro."),
        point(
            "Velocità della ricerca",
            "DISAGREEMENT",
            "La ricerca è troppo lenta.",
            "La ricerca va bene.",
        ),
    ],
    "proposals": [
        {"supported_by": ["T1", "T2"], "target": "DESIGN", "text": "Mostrare la ricerca in alto."},
        {"supported_by": ["T2"], "target": "REQUIREMENTS", "text": "Rispondere entro un secondo."},
    ],
    "questions_for_owner": ["Serve la ricerca vocale?"],
}


def named_twin(twin_id, name):
    base = twin_version()
    profile = replace(base.profile, name=name)
    return replace(
        base,
        id=UUID(int=twin_id.int + 1000),
        twin_id=twin_id,
        profile=profile,
        content_hash=profile.content_hash,
    )


def twins(count=2):
    return (
        twin_version(),
        named_twin(SECOND_TWIN_ID, "Night Auditor Twin"),
        named_twin(THIRD_TWIN_ID, "Housekeeping Twin"),
    )[:count]


def validated(output_type, payload):
    return output_type.model_validate_json(json.dumps(payload))


def parse_statement(payload, keys, speaker, *, later=False, note=False):
    reacting = tuple(key for key in keys if key != speaker) if later else ()
    observed = tuple(known_observations(keys[speaker].profile))
    return validated(statement_output_type(observed, reacting, note), payload)


def parse_synthesis(payload, keys):
    return validated(synthesis_output_type(tuple(keys)), payload)


def thought_order(instruction, *phrases):
    positions = [instruction.index(phrase) for phrase in phrases]
    return positions == sorted(positions)


def first_round(keys):
    statements = (
        bind_statement(
            parse_statement(STATEMENT, keys, "T1"),
            speaker="T1",
            keys=keys,
            generation_id=UUID(int=1),
        ),
        bind_statement(
            parse_statement(OPENING, keys, "T2"),
            speaker="T2",
            keys=keys,
            generation_id=UUID(int=2),
        ),
    )
    return create_discussion_round(
        ordinal=1,
        owner_note=None,
        statements=statements,
        synthesis=bind_synthesis(
            parse_synthesis(SYNTHESIS, keys), keys=keys, generation_id=UUID(int=3)
        ),
        created_at=NOW,
    )


def finding(finding_id, twin_id, summary):
    return create_synthetic_finding(
        finding_id=finding_id,
        twin_id=twin_id,
        twin_version=1,
        artifact_id=design_fixtures.PROTOTYPE_ID,
        artifact_version=1,
        location="SCR-001 Create reservation",
        summary=summary,
        rationale="Simulated rationale.",
        criterion=SyntheticFindingCriterion.COMPREHENSIBILITY,
        severity=SyntheticFindingSeverity.MAJOR,
        epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
        evidence_refs=(f"artifact:{design_fixtures.PROTOTYPE_ID}:v1",),
        confidence=0.6,
        recommended_action="Add a hint.",
        requires_human_validation=True,
        model_config_ref="config-1",
        prompt_version_ref="prompt-1",
    )


class RecordingGenerator:
    def __init__(self, payload, max_output_tokens=512):
        self.payload = payload
        self.calls = []
        self.configuration = SimpleNamespace(max_output_tokens=max_output_tokens)

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return validated(kwargs["output_type"], self.payload)


def later_context(keys, speaker, previous, owner_note=None):
    return statement_context(
        project_id=design_fixtures.PROJECT_ID,
        locale="it-IT",
        ordinal=2,
        owner_note=owner_note,
        keys=keys,
        speaker=speaker,
        design={},
        findings=(),
        previous=previous,
    )


def test_twin_keys_follow_the_twin_order_and_only_known_observations_are_shown():
    first, second = twins()
    keys = twin_keys((first, second))
    assert list(keys) == ["T1", "T2"]
    assert keys["T1"] is first and keys["T2"] is second
    observed = known_observations(first.profile)
    assert observed["user_twin.role"] == {
        "value": "Hotel receptionist",
        "epistemic_status": "USER_PROVIDED",
    }
    assert observed["user_twin.goals"]["value"] == ["Known goals"]
    assert len(observed) == len(UserTwinField) - 1
    assert all(set(item) == {"value", "epistemic_status"} for item in observed.values())
    inferred = ProfileObservation(
        observation_key="user_twin.frustrations",
        value=ObservationValue.from_items(("Too many clicks",)),
        epistemic_status=EpistemicStatus.MODEL_INFERRED,
        confidence=ConfidenceScore(0.4),
        provenance=ObservationProvenance.from_references(
            (EvidenceReference(source_kind=EvidenceSourceKind.MODEL_OUTPUT, source_id="model"),)
        ),
        human_validation=HumanValidationRequirement.REQUIRED,
        rationale="Inferred from the brief.",
    )
    profile = SimpleNamespace(
        observations=(
            observation("user_twin.role", ObservationValue.from_text("Night auditor")),
            observation("user_twin.goals", ObservationValue.unknown()),
            observation("user_twin.pain_points", ObservationValue.abstained("Not stated.")),
            inferred,
        )
    )
    assert known_observations(profile) == {
        "user_twin.role": {"value": "Night auditor", "epistemic_status": "USER_PROVIDED"},
        "user_twin.frustrations": {
            "value": ["Too many clicks"],
            "epistemic_status": "MODEL_INFERRED",
        },
    }


def test_findings_keep_the_run_order_without_dismissed_or_foreign_twins():
    first, second = twins()
    keys = twin_keys((first, second))
    run = SimpleNamespace(
        id=RUN_ID,
        findings=(
            finding("UTF-001", first.twin_id, "Il campo nome non ha un esempio."),
            finding("UTF-002", first.twin_id, "Il pulsante di salvataggio è nascosto."),
            finding("UTF-001", second.twin_id, "La conferma non mostra il passo successivo."),
            finding("UTF-001", THIRD_TWIN_ID, "Un twin che non partecipa."),
        ),
    )
    dismissed = frozenset({(RUN_ID, first.twin_id, "UTF-002")})
    assert discussion_findings(run, keys, dismissed) == [
        {
            "twin": "T1",
            "location": "SCR-001 Create reservation",
            "summary": "Il campo nome non ha un esempio.",
            "severity": "major",
            "criterion": "comprehensibility",
        },
        {
            "twin": "T2",
            "location": "SCR-001 Create reservation",
            "summary": "La conferma non mostra il passo successivo.",
            "severity": "major",
            "criterion": "comprehensibility",
        },
    ]
    assert len(discussion_findings(run, keys)) == 3
    assert discussion_findings(None, keys) == []


def test_first_round_statement_context_shows_the_speaker_the_design_and_the_findings():
    first, second = twins()
    keys = twin_keys((first, second))
    version = design_fixtures.design_version()
    view = design_review_view(version)
    findings = [
        {
            "twin": "T1",
            "location": "SCR-001",
            "summary": "Il campo nome non ha un esempio.",
            "severity": "major",
            "criterion": "comprehensibility",
        }
    ]
    context = statement_context(
        project_id=version.project_id,
        locale="it-IT",
        ordinal=1,
        owner_note="Pensate ai turni di notte.",
        keys=keys,
        speaker="T2",
        design=view,
        findings=findings,
        previous=None,
    )
    assert context == {
        "project_id": str(version.project_id),
        "purpose": "TWIN_STATEMENT",
        "locale": "it-IT",
        "round": 1,
        "owner_note": "Pensate ai turni di notte.",
        "participants": {"T1": "Receptionist Twin", "T2": "Night Auditor Twin"},
        "speaker": "T2",
        "user_twin": {
            "twin_id": str(SECOND_TWIN_ID),
            "name": "Night Auditor Twin",
            "observations": known_observations(second.profile),
        },
        "design": view,
        "findings": findings,
        "previous_round": None,
        "your_previous_position": None,
    }
    assert "provenance" not in json.dumps(context["user_twin"])


def test_later_rounds_hide_the_speaker_own_text_and_show_the_others_and_the_synthesis():
    keys = twin_keys(twins())
    previous = first_round(keys)
    context = later_context(keys, "T1", previous, owner_note="Rispondete alla nota.")
    synthesis_view = {
        "agreements": ["Il flusso è chiaro."],
        "conflicts": [
            {
                "topic": "Velocità della ricerca",
                "positions": [
                    {"twin": "T1", "position": "La ricerca è troppo lenta."},
                    {"twin": "T2", "position": "La ricerca va bene."},
                ],
            }
        ],
        "proposals": [
            {
                "code": "PRP-001",
                "text": "Mostrare la ricerca in alto.",
                "target": "DESIGN",
                "supported_by": ["T1", "T2"],
            },
            {
                "code": "PRP-002",
                "text": "Rispondere entro un secondo.",
                "target": "REQUIREMENTS",
                "supported_by": ["T2"],
            },
        ],
        "questions_for_owner": ["Serve la ricerca vocale?"],
    }
    assert context["previous_round"] == {
        "statements": [
            {
                "twin": "T2",
                "name": "Night Auditor Twin",
                "stance": "SUPPORT",
                "statement": OPENING["argument"],
                "proposals": [],
            },
        ],
        "synthesis": synthesis_view,
    }
    assert context["your_previous_position"] == {
        "stance": "CONCERN",
        "proposals": ["Mostrare la ricerca in alto."],
    }
    assert context["owner_note"] == "Rispondete alla nota."
    assert "per me la ricerca è lenta" not in json.dumps(context, ensure_ascii=False)
    other = later_context(keys, "T2", previous)
    assert [item["twin"] for item in other["previous_round"]["statements"]] == ["T1"]
    assert other["your_previous_position"] == {"stance": "SUPPORT", "proposals": []}
    reply = bind_statement(
        parse_statement({**REPLY, "answer_to_owner": ANSWER}, keys, "T2", later=True, note=True),
        speaker="T2",
        keys=keys,
        generation_id=UUID(int=12),
        previous=previous.statements[1].statement,
        others=(previous.statements[0].statement,),
        owner_note="Think about night shifts.",
    )
    moderated = synthesis_context(
        project_id=design_fixtures.PROJECT_ID,
        locale="en-US",
        ordinal=2,
        owner_note="Think about night shifts.",
        keys=keys,
        statements=(previous.statements[0], reply),
    )
    assert moderated == {
        "project_id": str(design_fixtures.PROJECT_ID),
        "purpose": "DISCUSSION_SYNTHESIS",
        "locale": "en-US",
        "round": 2,
        "owner_note": "Think about night shifts.",
        "participants": {"T1": "Receptionist Twin", "T2": "Night Auditor Twin"},
        "statements": [
            {
                "twin": "T1",
                "name": "Receptionist Twin",
                "stance": "CONCERN",
                "argument": "Il modulo è chiaro, ma per me la ricerca è lenta.",
                "proposals": ["Mostrare la ricerca in alto."],
                "replies_to": [],
                "reactions": [],
            },
            {
                "twin": "T2",
                "name": "Night Auditor Twin",
                "stance": "SUPPORT",
                "argument": REPLY["argument"],
                "proposals": ["Mostrare la ricerca in alto."],
                "replies_to": ["T1"],
                "reactions": [
                    {"twin": "T1", "verdict": "PARTLY", "reason": "Anche io cerco in fretta."}
                ],
                "answer_to_owner": ANSWER,
            },
        ],
    }
    opening = synthesis_context(
        project_id=design_fixtures.PROJECT_ID,
        locale="it-IT",
        ordinal=1,
        owner_note=None,
        keys=keys,
        statements=previous.statements,
    )
    assert "previous_synthesis" not in opening
    assert all("answer_to_owner" not in item for item in opening["statements"])
    assert "Serve la ricerca vocale?" not in json.dumps(moderated, ensure_ascii=False)


def test_statement_output_type_writes_the_answer_and_the_argument_before_the_verdicts():
    output_type = statement_output_type(("user_twin.goals", "user_twin.role"), ("T2", "T3"), True)
    assert list(output_type.model_fields) == STATEMENT_FIELDS == sorted(STATEMENT_FIELDS)
    schema = output_type.model_json_schema()
    properties, definitions = schema["properties"], schema["$defs"]
    assert list(properties) == STATEMENT_FIELDS
    assert schema["required"] == STATEMENT_FIELDS
    assert (properties["argument"]["minLength"], properties["argument"]["maxLength"]) == (1, 700)
    assert (properties["confidence"]["minimum"], properties["confidence"]["maximum"]) == (0, 1)
    assert properties["grounded_on"]["items"]["enum"] == ["user_twin.goals", "user_twin.role"]
    assert (properties["grounded_on"]["minItems"], properties["grounded_on"]["maxItems"]) == (1, 2)
    assert properties["proposals"]["maxItems"] == 3
    assert properties["proposals"]["items"]["maxLength"] == 300
    answer = properties["answer_to_owner"]
    assert (answer["type"], answer["minLength"], answer["maxLength"]) == ("string", 1, 500)
    assert (ARGUMENT_OUTPUT_LENGTH, ANSWER_OUTPUT_LENGTH, REASON_OUTPUT_LENGTH) == (700, 500, 400)
    assert (PROPOSAL_OUTPUT_LENGTH, POSITION_OUTPUT_LENGTH) == (300, 300)
    assert (SUBJECT_OUTPUT_LENGTH, QUESTION_OUTPUT_LENGTH) == (200, 300)
    reactions = properties["reactions"]
    assert (reactions["minItems"], reactions["maxItems"]) == (2, 2)
    assert [item["$ref"] for item in reactions["prefixItems"]] == [
        "#/$defs/TwinReactionT2",
        "#/$defs/TwinReactionT3",
    ]
    for key in ("T2", "T3"):
        entry = definitions[f"TwinReaction{key}"]
        assert list(entry["properties"]) == ["reason", "twin", "verdict"]
        assert entry["required"] == ["reason", "twin", "verdict"]
        assert entry["properties"]["twin"]["const"] == key
        assert entry["properties"]["verdict"]["enum"] == ["AGREE", "PARTLY", "DISAGREE"]
        reason = entry["properties"]["reason"]
        assert (reason["minLength"], reason["maxLength"]) == (1, 400)
    assert properties["stance"]["enum"] == ["SUPPORT", "CONCERN", "OBJECTION"]
    keys = tuple(field.observation_key for field in UserTwinField)
    grounded = statement_output_type(keys, (), False).model_json_schema()["properties"]
    assert grounded["grounded_on"]["maxItems"] == 4
    opening = statement_output_type(("user_twin.goals",), (), False)
    opening_properties = opening.model_json_schema()["properties"]
    assert list(opening_properties) == STATEMENT_FIELDS
    assert opening_properties["reactions"]["maxItems"] == 0
    assert opening_properties["answer_to_owner"]["type"] == "null"
    assert "minLength" not in opening_properties["answer_to_owner"]
    assert not {"replies_to", "about_others"} & set(opening.model_fields)
    valid = {**OPENING, "grounded_on": ["user_twin.goals"]}
    parsed_opening = validated(opening, valid)
    assert (parsed_opening.reactions, parsed_opening.answer_to_owner) == ([], None)
    missing_answer = {key: value for key, value in valid.items() if key != "answer_to_owner"}
    for payload in (
        {**valid, "reactions": [REPLY["reactions"][0]]},
        {**valid, "answer_to_owner": ANSWER},
        missing_answer,
        {**valid, "grounded_on": ["user_twin.role"]},
        {**valid, "grounded_on": []},
        {**valid, "argument": ""},
        {**valid, "argument": "x" * 701},
        {**valid, "confidence": 1.5},
        {**valid, "proposals": ["Uno.", "Due.", "Tre.", "Quattro."]},
        {**valid, "stance": "NEUTRAL"},
        {**valid, "about_others": []},
        {**valid, "replies_to": []},
    ):
        with pytest.raises(ValidationError):
            validated(opening, payload)
    second = {"reason": "Concordo.", "twin": "T2", "verdict": "AGREE"}
    third = {"reason": "Non per me.", "twin": "T3", "verdict": "DISAGREE"}
    answered = {
        **valid,
        "grounded_on": ["user_twin.role"],
        "reactions": [second, third],
        "answer_to_owner": ANSWER,
    }
    parsed = validated(output_type, answered)
    assert [(item.twin, item.verdict) for item in parsed.reactions] == [
        ("T2", "AGREE"),
        ("T3", "DISAGREE"),
    ]
    assert parsed.answer_to_owner == ANSWER
    for changes in (
        {"reactions": [third, second]},
        {"reactions": [second]},
        {"reactions": [second, third, third]},
        {"reactions": [second, {**third, "verdict": "MAYBE"}]},
        {"reactions": [second, {**third, "reason": ""}]},
        {"reactions": [second, {**third, "reason": "x" * 401}]},
        {"reactions": [second, {"twin": "T3", "verdict": "AGREE"}]},
        {"answer_to_owner": None},
        {"answer_to_owner": ""},
        {"answer_to_owner": "x" * 501},
    ):
        with pytest.raises(ValidationError):
            validated(output_type, {**answered, **changes})
    with pytest.raises(ValueError, match="known profile observation"):
        statement_output_type((), (), False)


def test_synthesis_output_type_lists_discussion_points_with_a_position_per_twin():
    output_type = synthesis_output_type(("T1", "T2", "T3"))
    fields = ["discussion_points", "proposals", "questions_for_owner"]
    assert list(output_type.model_fields) == fields == sorted(fields)
    schema = output_type.model_json_schema()
    properties, definitions = schema["properties"], schema["$defs"]
    assert properties["discussion_points"]["maxItems"] == 8
    assert properties["proposals"]["maxItems"] == 5
    assert properties["questions_for_owner"]["maxItems"] == 4
    assert properties["questions_for_owner"]["items"]["maxLength"] == 300
    discussed = definitions["DiscussionPointOutput"]["properties"]
    assert list(discussed) == ["positions", "subject", "verdict"]
    positions = discussed["positions"]
    assert (positions["minItems"], positions["maxItems"]) == (3, 3)
    assert [item["$ref"] for item in positions["prefixItems"]] == [
        "#/$defs/DiscussionPositionT1",
        "#/$defs/DiscussionPositionT2",
        "#/$defs/DiscussionPositionT3",
    ]
    assert (discussed["subject"]["minLength"], discussed["subject"]["maxLength"]) == (1, 200)
    assert discussed["verdict"]["enum"] == ["AGREEMENT", "DISAGREEMENT"]
    for key in ("T1", "T2", "T3"):
        entry = definitions[f"DiscussionPosition{key}"]
        assert list(entry["properties"]) == ["position", "twin"]
        assert entry["required"] == ["position", "twin"]
        assert entry["properties"]["twin"]["const"] == key
        assert entry["properties"]["position"]["anyOf"] == [
            {"maxLength": 300, "minLength": 1, "type": "string"},
            {"type": "null"},
        ]
    proposal = definitions["DiscussionProposalOutput"]["properties"]
    assert list(proposal) == ["supported_by", "target", "text"]
    assert (proposal["supported_by"]["minItems"], proposal["supported_by"]["maxItems"]) == (1, 3)
    assert proposal["target"]["enum"] == ["BRIEF", "REQUIREMENTS", "DESIGN"]
    assert proposal["text"]["maxLength"] == 300
    single = synthesis_output_type(("T1",)).model_json_schema()
    alone = single["$defs"]["DiscussionPointOutput"]["properties"]
    assert alone["verdict"]["const"] == "AGREEMENT"
    assert (alone["positions"]["minItems"], alone["positions"]["maxItems"]) == (1, 1)
    complete = point("Velocità della ricerca", "DISAGREEMENT", "Lenta.", None, "Veloce.")
    valid = {**SYNTHESIS, "discussion_points": [complete]}
    parsed = validated(output_type, valid).discussion_points[0].positions
    assert [(item.twin, item.position) for item in parsed] == [
        ("T1", "Lenta."),
        ("T2", None),
        ("T3", "Veloce."),
    ]
    first, second, third = complete["positions"]
    for payload in (
        {**valid, "discussion_points": [point("Ricerca", "DISAGREEMENT", "Lenta.", "Veloce.")]},
        {**valid, "discussion_points": [{**complete, "positions": [second, first, third]}]},
        {**valid, "discussion_points": [{**complete, "verdict": "CONFLICT"}]},
        {**valid, "discussion_points": [{**complete, "subject": ""}]},
        {**valid, "discussion_points": [{**complete, "subject": "x" * 201}]},
        {**valid, "discussion_points": [point("Ricerca", "AGREEMENT", "Lenta.", "", "Sì.")]},
        {**valid, "discussion_points": [complete] * 9},
        {**valid, "agreements": []},
        {**valid, "proposals": [{**SYNTHESIS["proposals"][0], "supported_by": []}]},
        {**valid, "proposals": [{**SYNTHESIS["proposals"][0], "supported_by": ["T9"]}]},
        {**valid, "questions_for_owner": ["Uno?", "Due?", "Tre?", "Quattro?", "Cinque?"]},
    ):
        with pytest.raises(ValidationError):
            validated(output_type, payload)
    with pytest.raises(ValidationError):
        validated(
            synthesis_output_type(("T1",)),
            {**SYNTHESIS, "discussion_points": [point("Ricerca", "DISAGREEMENT", "Lenta.")]},
        )
    with pytest.raises(ValueError, match="participant"):
        synthesis_output_type(())


def test_speaking_and_moderating_use_the_twin_discussion_task_with_their_contracts(tmp_path):
    keys = twin_keys(twins())
    version = design_fixtures.design_version()
    context = statement_context(
        project_id=version.project_id,
        locale="it-IT",
        ordinal=1,
        owner_note=None,
        keys=keys,
        speaker="T1",
        design=design_review_view(version),
        findings=(),
        previous=None,
    )
    generator, transport = audited_generator(tmp_path, STATEMENT)
    output = asyncio.run(speak_as_twin(generator, context=context))
    payload = transport.calls[0]["payload"]
    assert payload["metadata"]["orchestwin_task_id"] == "proposal-twin-discussion-v1"
    assert payload["metadata"]["orchestwin_prompt_version_ref"] == "proposal-twin-discussion-v5"
    assert payload["response_format"]["json_schema"]["name"] == "proposal-twin-discussion-v5"
    assert payload["max_tokens"] == STATEMENT_OUTPUT_TOKENS == 1024
    instruction = payload["messages"][0]["content"]
    assert instruction.endswith(STATEMENT_INSTRUCTION)
    assert "never claim to be a real person" in instruction
    assert "at most 90 words" in instruction
    assert "in round 1 reactions is empty" in instruction
    assert "with a reason in at most 40 words" in instruction
    assert "the requirements or the design, each in at most 30 words" in instruction
    assert "in at most 60 words" in instruction
    assert "about_others" not in STATEMENT_INSTRUCTION
    assert OWNER_ANSWER in instruction
    assert NAMES in instruction
    assert STATIC_MOCKUP in instruction
    assert f"Speak in the first person, in the language of locale. {LANGUAGE}" in instruction
    assert thought_order(
        STATEMENT_INSTRUCTION,
        "First, when owner_note is present",
        "Then argument is your statement",
        "Then proposals lists up to three",
        "At the end, from round 2",
    )
    sent = json.loads(payload["messages"][1]["content"])
    assert sent["context"]["purpose"] == "TWIN_STATEMENT"
    assert sent["context"]["speaker"] == "T1"
    schema = payload["response_format"]["json_schema"]["schema"]
    assert list(schema["properties"]) == STATEMENT_FIELDS
    assert schema["properties"]["reactions"]["maxItems"] == 0
    assert schema["properties"]["answer_to_owner"]["type"] == "null"
    statement = bind_statement(output, speaker="T1", keys=keys, generation_id=UUID(int=1))
    generator, transport = audited_generator(tmp_path, SYNTHESIS)
    moderated = asyncio.run(
        moderate_discussion(
            generator,
            context=synthesis_context(
                project_id=version.project_id,
                locale="it-IT",
                ordinal=1,
                owner_note=None,
                keys=keys,
                statements=(statement,),
            ),
        )
    )
    payload = transport.calls[0]["payload"]
    assert payload["metadata"]["orchestwin_task_id"] == "proposal-twin-discussion-v1"
    assert payload["metadata"]["orchestwin_prompt_version_ref"] == "proposal-twin-discussion-v6"
    assert payload["response_format"]["json_schema"]["name"] == "proposal-twin-discussion-v6"
    assert payload["max_tokens"] == SYNTHESIS_OUTPUT_TOKENS == 2048
    moderation = payload["messages"][0]["content"]
    assert "neutral moderator" in moderation
    assert (
        "verdict is DISAGREEMENT only when twins want different or incompatible things, and "
        "AGREEMENT when they say the same thing, even with different words"
    ) in moderation
    assert "a point needs the positions of at least two twins" in moderation
    assert "stays in proposals" in moderation
    assert "previous_synthesis" not in SYNTHESIS_INSTRUCTION
    assert "Summarise only the statements of this round" in moderation
    assert (
        "in the language of locale. Write every text in the language of locale, including each "
        "subject, position, proposal and question, even when parts of the statements are "
        "written in another language. discussion_points"
    ) in moderation
    assert "proposals comes only from the proposals and the statements of this round" in moderation
    assert "keys appear only in twin and supported_by" in moderation
    assert "every twin in the order of participants" in moderation
    assert "or null when it said nothing about it" in moderation
    for limit in (
        "said about the point in at most 35 words",
        "the point as a short sentence in at most 20 words",
        "text states the change in at most 30 words",
        "only the owner can take, each in at most 35 words",
    ):
        assert limit in moderation
    sent_schema = payload["response_format"]["json_schema"]["schema"]
    assert list(sent_schema["properties"]) == [
        "discussion_points",
        "proposals",
        "questions_for_owner",
    ]
    sent_point = sent_schema["$defs"]["DiscussionPointOutput"]["properties"]
    assert list(sent_point) == ["positions", "subject", "verdict"]
    assert len(sent_point["positions"]["prefixItems"]) == 2
    assert [item.supported_by for item in moderated.proposals] == [["T1", "T2"], ["T2"]]
    assert [item.verdict for item in moderated.discussion_points] == ["AGREEMENT", "DISAGREEMENT"]


def test_the_discussion_leaves_schema_errors_to_its_own_attempts():
    keys = twin_keys(twins())
    speaker = RecordingGenerator({**REPLY, "answer_to_owner": ANSWER})
    context = later_context(keys, "T2", first_round(keys), owner_note="Rispondete.")
    asyncio.run(speak_as_twin(speaker, context=context))
    moderator = RecordingGenerator(SYNTHESIS, max_output_tokens=4096)
    asyncio.run(
        moderate_discussion(
            moderator,
            context=synthesis_context(
                project_id=design_fixtures.PROJECT_ID,
                locale="it-IT",
                ordinal=1,
                owner_note=None,
                keys=keys,
                statements=(),
            ),
        )
    )
    assert [call["retry_schema_errors"] for call in (*speaker.calls, *moderator.calls)] == [
        False,
        False,
    ]


def test_later_statements_use_the_follow_up_instruction_and_budgets_stay_bounded():
    keys = twin_keys(twins())
    context = later_context(keys, "T2", first_round(keys), owner_note="Rispondete.")
    generator = RecordingGenerator({**REPLY, "answer_to_owner": ANSWER})
    asyncio.run(speak_as_twin(generator, context=context))
    moderator = RecordingGenerator(SYNTHESIS, max_output_tokens=4096)
    asyncio.run(
        moderate_discussion(
            moderator,
            context=synthesis_context(
                project_id=design_fixtures.PROJECT_ID,
                locale="it-IT",
                ordinal=1,
                owner_note=None,
                keys=keys,
                statements=(),
            ),
        )
    )
    [call] = generator.calls
    assert (call["task"], call["max_output_tokens"]) == ("twin-discussion", 512)
    assert call["instruction"] == FOLLOW_UP_INSTRUCTION
    for phrase in (
        "You have already spoken",
        "Do not repeat your earlier statement and do not repeat what another twin said",
        "Think in this order. First, " + OWNER_ANSWER,
        "Then proposals lists only the changes",
        "At the end, reactions gives, for each other twin in the order of participants",
        "the note is a request of the owner that you must address explicitly. Then argument",
        "what you now accept, what you still object to and why from your profile",
        "merging or dropping the ones already covered",
        "verdict is AGREE, PARTLY or DISAGREE",
        "reason explains it from your profile in at most 40 words",
        "that you still ask for, each in at most 30 words",
        "says in at most 90 words",
        "in at most 60 words",
        NAMES,
        STATIC_MOCKUP,
    ):
        assert phrase in FOLLOW_UP_INSTRUCTION
    assert "about_others" not in FOLLOW_UP_INSTRUCTION
    assert f"first person, in the language of locale. {LANGUAGE}" in FOLLOW_UP_INSTRUCTION
    assert thought_order(
        FOLLOW_UP_INSTRUCTION,
        "First, answer_to_owner answers",
        "Then argument says",
        "Then proposals lists only",
        "At the end, reactions gives",
    )
    properties = call["output_type"].model_json_schema()["properties"]
    assert list(properties) == STATEMENT_FIELDS
    reactions = properties["reactions"]
    assert (reactions["minItems"], reactions["maxItems"]) == (1, 1)
    assert [item["$ref"] for item in reactions["prefixItems"]] == ["#/$defs/TwinReactionT1"]
    assert properties["answer_to_owner"]["type"] == "string"
    [call] = moderator.calls
    assert (call["task"], call["max_output_tokens"]) == ("twin-discussion", 2048)
    alone = twin_keys(twins(1))
    single = RecordingGenerator({**STATEMENT, "argument": "Ora il modulo mi sembra chiaro."})
    lone_round = create_discussion_round(
        ordinal=1,
        owner_note=None,
        statements=(first_round(keys).statements[0],),
        synthesis=bind_synthesis(
            parse_synthesis({**SYNTHESIS, "discussion_points": [], "proposals": []}, alone),
            keys=alone,
            generation_id=UUID(int=3),
        ),
        created_at=NOW,
    )
    asyncio.run(speak_as_twin(single, context=later_context(alone, "T1", lone_round)))
    [call] = single.calls
    assert call["instruction"] == FOLLOW_UP_INSTRUCTION
    lone = call["output_type"].model_json_schema()["properties"]
    assert lone["reactions"]["maxItems"] == 0
    assert lone["answer_to_owner"]["type"] == "null"


def test_bind_statement_maps_reactions_to_twins_and_derives_the_replies():
    keys = twin_keys(twins(3))
    answered = {
        **STATEMENT,
        "reactions": [
            {"reason": "  Anche io   cerco in fretta. ", "twin": "T2", "verdict": "AGREE"},
            {"reason": "Il mio turno è diverso.", "twin": "T3", "verdict": "DISAGREE"},
        ],
    }
    statement = bind_statement(
        parse_statement(answered, keys, "T1", later=True),
        speaker="T1",
        keys=keys,
        generation_id=UUID(int=5),
        previous="Nel primo turno ho parlato della lentezza del salvataggio.",
    )
    assert statement.twin_id == keys["T1"].twin_id
    assert (statement.twin_version, statement.twin_name) == (1, "Receptionist Twin")
    assert statement.stance is DiscussionStance.CONCERN
    assert statement.statement == "Il modulo è chiaro, ma per me la ricerca è lenta."
    assert statement.reactions == (
        TwinReaction(SECOND_TWIN_ID, ReactionVerdict.AGREE, "Anche io cerco in fretta."),
        TwinReaction(THIRD_TWIN_ID, ReactionVerdict.DISAGREE, "Il mio turno è diverso."),
    )
    assert statement.replies_to == (SECOND_TWIN_ID, THIRD_TWIN_ID)
    assert statement.proposals == ("Mostrare la ricerca in alto.",)
    assert statement.grounded_on == ("user_twin.goals", "user_twin.frustrations")
    assert statement.confidence == 0.75
    assert statement.model_generation_id == UUID(int=5)
    snapshot = statement.to_snapshot()
    assert snapshot["reactions"] == [
        {"twin_id": str(SECOND_TWIN_ID), "verdict": "AGREE", "reason": "Anche io cerco in fretta."},
        {"twin_id": str(THIRD_TWIN_ID), "verdict": "DISAGREE", "reason": "Il mio turno è diverso."},
    ]
    opening = bind_statement(
        parse_statement(STATEMENT, keys, "T1"), speaker="T1", keys=keys, generation_id=UUID(int=6)
    )
    assert (opening.reactions, opening.replies_to, opening.owner_answer) == ((), (), None)
    assert not {"reactions", "answer_to_owner"} & set(opening.to_snapshot())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {
                "reactions": [
                    SimpleNamespace(reason="Sì.", twin="T2", verdict="AGREE"),
                    SimpleNamespace(reason="No.", twin="T2", verdict="DISAGREE"),
                ]
            },
            "each twin once",
        ),
        ({"reactions": [SimpleNamespace(reason="Io.", twin="T1", verdict="AGREE")]}, "itself"),
        (
            {"reactions": [SimpleNamespace(reason="Chi?", twin="T9", verdict="AGREE")]},
            "unknown discussion participant",
        ),
        (
            {"reactions": [SimpleNamespace(reason="Forse.", twin="T2", verdict="MAYBE")]},
            "MAYBE",
        ),
        (
            {"reactions": [SimpleNamespace(reason="   ", twin="T2", verdict="AGREE")]},
            "must not be empty",
        ),
        ({"argument": "   "}, "must not be empty"),
        ({"proposals": ["  "]}, "must not be empty"),
        ({"grounded_on": []}, "grounding"),
        ({"stance": "NEUTRAL"}, "NEUTRAL"),
        ({"answer_to_owner": ANSWER}, "requires the owner's note"),
    ],
)
def test_bind_statement_rejects_inconsistent_outputs(changes, message):
    keys = twin_keys(twins(3))
    output = SimpleNamespace(**{**STATEMENT, **changes})
    with pytest.raises(ValueError, match=message):
        bind_statement(output, speaker="T1", keys=keys, generation_id=UUID(int=5))


def test_the_owner_note_needs_an_answer_that_does_not_repeat_it():
    keys = twin_keys(twins())
    answered = bind_statement(
        parse_statement({**STATEMENT, "answer_to_owner": f"  {ANSWER} "}, keys, "T1", note=True),
        speaker="T1",
        keys=keys,
        generation_id=UUID(int=5),
        owner_note=NOTE,
    )
    assert answered.owner_answer == ANSWER
    assert answered.to_snapshot()["answer_to_owner"] == ANSWER
    for answer, message in (
        (None, "the owner's note needs an answer"),
        ("   ", "must not be empty"),
        (NOTE, "the answer repeats the owner's note"),
        (NOTE.upper().replace(".", "!"), "the answer repeats the owner's note"),
    ):
        with pytest.raises(ValueError, match=message):
            bind_statement(
                SimpleNamespace(**{**STATEMENT, "answer_to_owner": answer}),
                speaker="T1",
                keys=keys,
                generation_id=UUID(int=5),
                owner_note=NOTE,
            )
    with pytest.raises(ValueError, match="requires the owner's note"):
        bind_statement(
            parse_statement({**STATEMENT, "answer_to_owner": ANSWER}, keys, "T1", note=True),
            speaker="T1",
            keys=keys,
            generation_id=UUID(int=5),
        )


def test_a_statement_that_copies_another_twin_is_rejected():
    keys = twin_keys(twins(3))
    theirs = "Night Auditor Twin ha ragione: di notte il modulo breve basta a tutti."
    for argument in (theirs, "T2 ha ragione: di notte il modulo breve basta a tutti!"):
        with pytest.raises(ValueError, match="the statement repeats another twin"):
            bind_statement(
                SimpleNamespace(**{**STATEMENT, "argument": argument}),
                speaker="T1",
                keys=keys,
                generation_id=UUID(int=5),
                previous="Nel primo turno ho parlato solo della ricerca lenta.",
                others=("Il flusso guidato mi basta.", theirs),
            )
    own = bind_statement(
        SimpleNamespace(**{**STATEMENT, "argument": "Io resto sulla ricerca lenta al banco."}),
        speaker="T1",
        keys=keys,
        generation_id=UUID(int=5),
        others=(theirs,),
    )
    assert own.statement == "Io resto sulla ricerca lenta al banco."


def test_keys_become_names_in_every_generated_text_unless_the_text_would_not_fit():
    keys = twin_keys(twins(3))
    statement = bind_statement(
        parse_statement(
            {
                **STATEMENT,
                "reactions": [
                    {"reason": "Come dice T2, di notte serve.", "twin": "T2", "verdict": "AGREE"},
                    {"reason": "T3 non usa il banco.", "twin": "T3", "verdict": "PARTLY"},
                ],
                "answer_to_owner": "Sì: T2 e io vogliamo il riepilogo.",
                "argument": "Concordo con T2 (T21 e PT2 no) ma non con T3.",
                "proposals": ["Chiedere a T3 un modulo breve."],
            },
            keys,
            "T1",
            later=True,
            note=True,
        ),
        speaker="T1",
        keys=keys,
        generation_id=UUID(int=5),
        owner_note=NOTE,
    )
    assert statement.statement == (
        "Concordo con Night Auditor Twin (T21 e PT2 no) ma non con Housekeeping Twin."
    )
    assert [item.reason for item in statement.reactions] == [
        "Come dice Night Auditor Twin, di notte serve.",
        "Housekeeping Twin non usa il banco.",
    ]
    assert statement.owner_answer == "Sì: Night Auditor Twin e io vogliamo il riepilogo."
    assert statement.proposals == ("Chiedere a Housekeeping Twin un modulo breve.",)
    crowded = "T2 " + "x" * (MAX_STATEMENT_LENGTH - 5)
    assert len(crowded) == MAX_STATEMENT_LENGTH - 2
    assert len(crowded.replace("T2", keys["T2"].profile.name)) > MAX_STATEMENT_LENGTH
    kept = bind_statement(
        SimpleNamespace(**{**STATEMENT, "argument": crowded}),
        speaker="T1",
        keys=keys,
        generation_id=UUID(int=5),
    )
    assert kept.statement == crowded
    reason = "T2 " + "x" * (REASON_OUTPUT_LENGTH - 4) + "."
    assert len(reason) == REASON_OUTPUT_LENGTH
    at_bound = bind_statement(
        parse_statement(
            {
                **STATEMENT,
                "reactions": [
                    {"reason": reason, "twin": "T2", "verdict": "AGREE"},
                    {"reason": "Non usa il banco.", "twin": "T3", "verdict": "PARTLY"},
                ],
            },
            keys,
            "T1",
            later=True,
        ),
        speaker="T1",
        keys=keys,
        generation_id=UUID(int=5),
    )
    widened = at_bound.reactions[0].reason
    assert widened == reason.replace("T2", "Night Auditor Twin")
    assert REASON_OUTPUT_LENGTH < len(widened) <= MAX_REACTION_REASON_LENGTH
    synthesis = bind_synthesis(
        parse_synthesis(
            {
                "discussion_points": [
                    point("T1 e T2 vogliono la ricerca in alto.", "AGREEMENT", "Sì.", "Sì.", None),
                    point("Ricerca per T3", "DISAGREEMENT", "Come T2.", None, "No, come T1."),
                ],
                "proposals": [
                    {"supported_by": ["T1", "T2"], "target": "DESIGN", "text": "Chiedere a T3."}
                ],
                "questions_for_owner": ["T3 lavora di notte?"],
            },
            keys,
        ),
        keys=keys,
        generation_id=UUID(int=9),
    )
    assert synthesis.agreements == (
        "Receptionist Twin e Night Auditor Twin vogliono la ricerca in alto.",
    )
    assert synthesis.conflicts[0].topic == "Ricerca per Housekeeping Twin"
    assert [position for _, position in synthesis.conflicts[0].positions] == [
        "Come Night Auditor Twin.",
        "No, come Receptionist Twin.",
    ]
    assert synthesis.proposals[0].text == "Chiedere a Housekeeping Twin."
    assert synthesis.questions_for_owner == ("Housekeeping Twin lavora di notte?",)


def test_complete_sentences_keeps_a_text_up_to_its_last_complete_sentence():
    assert complete_sentences("Il modulo è chiaro. Ma la ricerca") == "Il modulo è chiaro."
    assert complete_sentences("Davvero?! Sì! Poi però la ricer") == "Davvero?! Sì!"
    assert complete_sentences("Forse… e poi la") == "Forse…"
    for text in (
        "Il modulo è chiaro. La ricerca è lenta.",
        "Il modulo è chiaro. La ricerca è lenta…",
        "Costa 1.2 euro e la ricerca",
        "Nessuna frase completa",
        "… e poi la ricerca",
    ):
        assert complete_sentences(text) == text


@pytest.mark.parametrize(
    ("opening", "ending", "shortened", "cut"),
    [
        (CUT_SENTENCE, "", 0, True),
        (CUT_SENTENCE, " ", 0, True),
        (CUT_SENTENCE, ".", 0, False),
        (CUT_SENTENCE[:-1], "", 0, False),
        (CUT_SENTENCE, "", 1, False),
    ],
)
def test_a_generated_text_cut_at_its_bound_ends_at_its_last_complete_sentence(
    opening, ending, shortened, cut
):
    keys = twin_keys(twins(3))

    def generated(bound):
        return f"{opening} " + "x" * (bound - shortened - len(opening) - 1 - len(ending)) + ending

    def expected(bound):
        text = CUT_SENTENCE if cut else generated(bound)
        return text.replace("T2", "Night Auditor Twin")

    assert len(generated(ARGUMENT_OUTPUT_LENGTH)) == ARGUMENT_OUTPUT_LENGTH - shortened
    statement = bind_statement(
        parse_statement(
            {
                **STATEMENT,
                "reactions": [
                    {"reason": generated(REASON_OUTPUT_LENGTH), "twin": "T2", "verdict": "AGREE"},
                    {"reason": "Non usa il banco.", "twin": "T3", "verdict": "PARTLY"},
                ],
                "answer_to_owner": generated(ANSWER_OUTPUT_LENGTH),
                "argument": generated(ARGUMENT_OUTPUT_LENGTH),
                "proposals": [generated(PROPOSAL_OUTPUT_LENGTH)],
            },
            keys,
            "T1",
            later=True,
            note=True,
        ),
        speaker="T1",
        keys=keys,
        generation_id=UUID(int=5),
        owner_note=NOTE,
    )
    assert statement.statement == expected(ARGUMENT_OUTPUT_LENGTH)
    assert statement.reactions[0].reason == expected(REASON_OUTPUT_LENGTH)
    assert statement.owner_answer == expected(ANSWER_OUTPUT_LENGTH)
    assert statement.proposals == (expected(PROPOSAL_OUTPUT_LENGTH),)
    synthesis = bind_synthesis(
        parse_synthesis(
            {
                "discussion_points": [
                    point(generated(SUBJECT_OUTPUT_LENGTH), "AGREEMENT", "Sì.", "Sì.", None),
                    point(
                        "Ricerca", "DISAGREEMENT", generated(POSITION_OUTPUT_LENGTH), "No.", None
                    ),
                ],
                "proposals": [
                    {
                        "supported_by": ["T1"],
                        "target": "DESIGN",
                        "text": generated(PROPOSAL_OUTPUT_LENGTH),
                    }
                ],
                "questions_for_owner": [generated(QUESTION_OUTPUT_LENGTH)],
            },
            keys,
        ),
        keys=keys,
        generation_id=UUID(int=9),
    )
    assert synthesis.agreements == (expected(SUBJECT_OUTPUT_LENGTH),)
    assert synthesis.conflicts[0].positions[0][1] == expected(POSITION_OUTPUT_LENGTH)
    assert synthesis.proposals[0].text == expected(PROPOSAL_OUTPUT_LENGTH)
    assert synthesis.questions_for_owner == (expected(QUESTION_OUTPUT_LENGTH),)


def test_the_repetition_guard_compares_lower_cased_word_sets():
    earlier = "alfa beta gamma delta epsilon zeta eta theta iota"
    assert not repeats_previous_statement(earlier, None)
    assert repeats_previous_statement(earlier, earlier)
    assert repeats_previous_statement(
        "Alfa, BETA gamma: delta epsilon zeta eta theta iota!", earlier
    )
    assert repeats_previous_statement("alfa beta gamma delta epsilon zeta eta theta kappa", earlier)
    assert not repeats_previous_statement(
        "alfa beta gamma delta epsilon zeta eta kappa lambda", earlier
    )
    assert not repeats_previous_statement("...", "!!!")
    keys = twin_keys(twins())
    previous = first_round(keys).statements[0].statement
    for argument in (previous, f"{previous} Oggi.", previous.upper()):
        with pytest.raises(ValueError, match="the statement repeats the previous round"):
            bind_statement(
                parse_statement({**STATEMENT, "argument": argument}, keys, "T1"),
                speaker="T1",
                keys=keys,
                generation_id=UUID(int=7),
                previous=previous,
            )
    changed = bind_statement(
        parse_statement(
            {**STATEMENT, "argument": "Dopo la nota del titolare accetto il riepilogo finale."},
            keys,
            "T1",
        ),
        speaker="T1",
        keys=keys,
        generation_id=UUID(int=8),
        previous=previous,
    )
    assert changed.statement == "Dopo la nota del titolare accetto il riepilogo finale."


@pytest.mark.parametrize(
    "changes",
    [
        {"argument": "The guided form works for me, but the search is slow at the desk."},
        {"answer_to_owner": "Yes, the summary is enough for me when the form stays short."},
        {
            "reactions": [
                {"reason": ENGLISH_REASON, "twin": "T2", "verdict": "PARTLY"},
                {"reason": "Il mio turno è diverso.", "twin": "T3", "verdict": "DISAGREE"},
            ]
        },
    ],
)
def test_bind_statement_rejects_a_text_written_in_another_language(changes):
    keys = twin_keys(twins(3))
    output = parse_statement(
        {
            **STATEMENT,
            "answer_to_owner": ANSWER,
            "reactions": [
                {"reason": "Anche io cerco in fretta.", "twin": "T2", "verdict": "AGREE"},
                {"reason": "Il mio turno è diverso.", "twin": "T3", "verdict": "DISAGREE"},
            ],
            **changes,
        },
        keys,
        "T1",
        later=True,
        note=True,
    )

    def bound(locale):
        return bind_statement(
            output,
            speaker="T1",
            keys=keys,
            generation_id=UUID(int=5),
            owner_note=NOTE,
            locale=locale,
        )

    for locale in ("it-IT", "it_IT", "IT"):
        with pytest.raises(
            ValueError, match="the text is not written in the language of the project"
        ):
            bound(locale)
    for locale in (None, "fr-FR", "de"):
        assert bound(locale).model_generation_id == UUID(int=5)


def test_the_language_is_judged_on_the_texts_that_name_the_twins():
    keys = twin_keys(
        (
            twin_version(),
            named_twin(SECOND_TWIN_ID, "Responsabile della sala"),
            named_twin(THIRD_TWIN_ID, "Addetta alla cassa"),
        )
    )
    keyed = "T2 and T3 want the same flow here."
    assert written_in_another_language(keyed, "it-IT")
    statement = bind_statement(
        parse_statement(
            {
                **STATEMENT,
                "reactions": [
                    {"reason": keyed, "twin": "T2", "verdict": "AGREE"},
                    {"reason": "Il mio turno è diverso.", "twin": "T3", "verdict": "DISAGREE"},
                ],
            },
            keys,
            "T1",
            later=True,
        ),
        speaker="T1",
        keys=keys,
        generation_id=UUID(int=5),
        locale="it-IT",
    )
    assert statement.reactions[0].reason == (
        "Responsabile della sala and Addetta alla cassa want the same flow here."
    )
    english = SimpleNamespace(
        **{
            **STATEMENT,
            "argument": "The guided form works for me, but the search is slow at the desk.",
        }
    )
    kept = bind_statement(
        english, speaker="T1", keys=keys, generation_id=UUID(int=6), locale="en-US"
    )
    assert kept.statement == english.argument
    with pytest.raises(ValueError, match="the text is not written in the language of the project"):
        bind_statement(english, speaker="T1", keys=keys, generation_id=UUID(int=6), locale="it-IT")


def test_bind_synthesis_maps_verdicts_to_agreements_and_conflicts():
    keys = twin_keys(twins())
    payload = {
        **SYNTHESIS,
        "discussion_points": [
            *SYNTHESIS["discussion_points"],
            point(" Il flusso   è chiaro. ", "AGREEMENT", "Chiaro.", "Chiaro anche per me."),
        ],
    }
    synthesis = bind_synthesis(parse_synthesis(payload, keys), keys=keys, generation_id=UUID(int=9))
    first, second = keys["T1"].twin_id, keys["T2"].twin_id
    assert synthesis.agreements == ("Il flusso è chiaro.",)
    assert [item.topic for item in synthesis.conflicts] == ["Velocità della ricerca"]
    assert synthesis.conflicts[0].positions == (
        (first, "La ricerca è troppo lenta."),
        (second, "La ricerca va bene."),
    )
    assert [item.code for item in synthesis.proposals] == ["PRP-001", "PRP-002"]
    assert [item.target for item in synthesis.proposals] == [
        DiscussionProposalTarget.DESIGN,
        DiscussionProposalTarget.REQUIREMENTS,
    ]
    assert [item.supported_by for item in synthesis.proposals] == [(first, second), (second,)]
    assert synthesis.questions_for_owner == ("Serve la ricerca vocale?",)
    assert synthesis.model_generation_id == UUID(int=9)
    assert set(synthesis.to_snapshot()) == {
        "agreements",
        "conflicts",
        "proposals",
        "questions_for_owner",
        "model_generation_id",
    }


def test_bind_synthesis_keeps_only_the_twins_that_took_a_position():
    keys = twin_keys(twins(3))
    payload = {
        **SYNTHESIS,
        "discussion_points": [
            point("Velocità della ricerca", "DISAGREEMENT", "Troppo lenta.", None, "Va bene.")
        ],
    }
    synthesis = bind_synthesis(parse_synthesis(payload, keys), keys=keys, generation_id=UUID(int=9))
    first, third = keys["T1"].twin_id, keys["T3"].twin_id
    assert synthesis.conflicts[0].positions == ((first, "Troppo lenta."), (third, "Va bene."))
    assert synthesis.to_snapshot()["conflicts"] == [
        {
            "topic": "Velocità della ricerca",
            "positions": [
                {"twin_id": str(first), "position": "Troppo lenta."},
                {"twin_id": str(third), "position": "Va bene."},
            ],
        }
    ]


def test_bind_synthesis_keeps_the_first_agreements_and_conflicts_within_the_limits():
    keys = twin_keys(twins())
    agreed = [point(f"Accordo {index}.", "AGREEMENT", "Sì.", "Sì.") for index in range(1, 8)]
    agreed.insert(1, point("Accordo 1.", "AGREEMENT", "Sì.", "Anche per me."))
    synthesis = bind_synthesis(
        parse_synthesis({**SYNTHESIS, "discussion_points": agreed}, keys),
        keys=keys,
        generation_id=UUID(int=9),
    )
    assert synthesis.agreements == tuple(f"Accordo {index}." for index in range(1, 6))
    assert synthesis.conflicts == ()
    disputed = [
        point(f"Tema {index}", "DISAGREEMENT", "Voglio A.", "Voglio B.") for index in range(1, 5)
    ]
    points = [
        point("Tema solo mio", "DISAGREEMENT", "Voglio C.", None),
        *disputed,
        point("Tema 6", "DISAGREEMENT", "Voglio D.", "Voglio E."),
        point("Accordo finale.", "AGREEMENT", "Sì.", "Sì."),
    ]
    synthesis = bind_synthesis(
        parse_synthesis({**SYNTHESIS, "discussion_points": points}, keys),
        keys=keys,
        generation_id=UUID(int=9),
    )
    assert [item.topic for item in synthesis.conflicts] == ["Tema 1", "Tema 2", "Tema 3", "Tema 4"]
    assert synthesis.agreements == ("Accordo finale.",)


def test_bind_synthesis_leaves_out_the_points_raised_by_one_twin():
    keys = twin_keys(twins())
    points = [
        point("Icona per gli ospiti recenti", "DISAGREEMENT", "La chiedo io.", None),
        point("Pulsante per rimuovere un ospite", "DISAGREEMENT", None, "Lo chiedo io."),
        point("Nessuno ne ha parlato", "DISAGREEMENT", None, None),
        point("Accordo di uno solo.", "AGREEMENT", "Sì.", None),
        point("Messaggio di conferma.", "AGREEMENT", "Va chiarito.", "Va chiarito."),
    ]
    synthesis = bind_synthesis(
        parse_synthesis({**SYNTHESIS, "discussion_points": points}, keys),
        keys=keys,
        generation_id=UUID(int=9),
    )
    assert synthesis.conflicts == ()
    assert synthesis.agreements == ("Messaggio di conferma.",)
    assert [item.code for item in synthesis.proposals] == ["PRP-001", "PRP-002"]
    alone = twin_keys(twins(1))
    single = SimpleNamespace(
        discussion_points=[
            SimpleNamespace(
                subject="Il flusso è chiaro.",
                verdict="AGREEMENT",
                positions=(SimpleNamespace(position="Chiaro.", twin="T1"),),
            )
        ],
        proposals=[],
        questions_for_owner=[],
    )
    assert bind_synthesis(single, keys=alone, generation_id=UUID(int=9)).agreements == (
        "Il flusso è chiaro.",
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"discussion_points": [point("  ", "AGREEMENT", "Sì.", "Sì.")]},
            "must not be empty",
        ),
        (
            {"discussion_points": [point("Ricerca", "DISAGREEMENT", "Lenta.", " ")]},
            "must not be empty",
        ),
        (
            {"proposals": [{**SYNTHESIS["proposals"][0], "supported_by": ["T1", "T1"]}]},
            "distinct supporting twins",
        ),
        ({"proposals": [{**SYNTHESIS["proposals"][0], "text": "   "}]}, "must not be empty"),
        (
            {"proposals": [SYNTHESIS["proposals"][0], SYNTHESIS["proposals"][0]]},
            "must be distinct",
        ),
        ({"questions_for_owner": ["  "]}, "must not be empty"),
    ],
)
def test_bind_synthesis_rejects_inconsistent_outputs(changes, message):
    keys = twin_keys(twins())
    output = parse_synthesis({**SYNTHESIS, **changes}, keys)
    with pytest.raises(ValueError, match=message):
        bind_synthesis(output, keys=keys, generation_id=UUID(int=9))


def test_bind_synthesis_rejects_repeated_twins_unknown_verdicts_and_outside_twins():
    keys = twin_keys(twins())

    def output(points=(), proposals=()):
        return SimpleNamespace(
            discussion_points=list(points), proposals=list(proposals), questions_for_owner=[]
        )

    repeated = SimpleNamespace(
        subject="Ricerca",
        verdict="DISAGREEMENT",
        positions=(
            SimpleNamespace(position="Troppo lenta.", twin="T1"),
            SimpleNamespace(position="Va bene.", twin="T1"),
        ),
    )
    unknown = SimpleNamespace(subject="Ricerca", verdict="CONFLICT", positions=())
    outside = SimpleNamespace(supported_by=["T7"], target="DESIGN", text="Una modifica.")
    for built, message in (
        (output([repeated]), "names each twin once"),
        (output([unknown]), "unknown discussion point verdict"),
        (output(proposals=[outside]), "unknown discussion participant"),
    ):
        with pytest.raises(ValueError, match=message):
            bind_synthesis(built, keys=keys, generation_id=UUID(int=9))


def opening_context(keys, speaker, design=None):
    return statement_context(
        project_id=design_fixtures.PROJECT_ID,
        locale="it-IT",
        ordinal=1,
        owner_note=None,
        keys=keys,
        speaker=speaker,
        design={} if design is None else design,
        findings=(),
        previous=None,
    )


def moderation_context(keys, statements=(), screens=()):
    return synthesis_context(
        project_id=design_fixtures.PROJECT_ID,
        locale="it-IT",
        ordinal=1,
        owner_note=None,
        keys=keys,
        statements=statements,
        screens=screens,
    )


def discussion_instructions(**options):
    keys = twin_keys(twins())
    opening = RecordingGenerator(STATEMENT)
    later = RecordingGenerator({**REPLY, "answer_to_owner": ANSWER})
    moderator = RecordingGenerator(SYNTHESIS, max_output_tokens=4096)
    asyncio.run(speak_as_twin(opening, context=opening_context(keys, "T1"), **options))
    asyncio.run(
        speak_as_twin(
            later,
            context=later_context(keys, "T2", first_round(keys), owner_note="Rispondete."),
            **options,
        )
    )
    asyncio.run(moderate_discussion(moderator, context=moderation_context(keys), **options))
    return [generator.calls[0]["instruction"] for generator in (opening, later, moderator)]


@pytest.mark.parametrize("options", [{}, {"hosted": False}])
def test_the_local_route_keeps_the_three_instructions_of_the_discussion_byte_for_byte(options):
    sent = discussion_instructions(**options)
    assert sent == [STATEMENT_INSTRUCTION, FOLLOW_UP_INSTRUCTION, SYNTHESIS_INSTRUCTION]
    assert tuple(hashlib.sha256(text.encode("utf-8")).hexdigest() for text in sent) == (
        LOCAL_SHA256
    )
    assert all(NAMES_INSTEAD_OF_CODES not in text for text in sent)


def test_the_hosted_route_adds_the_titles_sentence_once_to_every_instruction_of_the_discussion():
    sent = discussion_instructions(hosted=True)
    local = (STATEMENT_INSTRUCTION, FOLLOW_UP_INSTRUCTION, SYNTHESIS_INSTRUCTION)
    assert NAMES_INSTEAD_OF_CODES == TITLES_NOT_CODES
    assert sent == [
        HOSTED_STATEMENT_INSTRUCTION,
        HOSTED_FOLLOW_UP_INSTRUCTION,
        HOSTED_SYNTHESIS_INSTRUCTION,
    ]
    assert sent == [f"{text} {TITLES_NOT_CODES}" for text in local]
    assert all(text.count(TITLES_NOT_CODES) == 1 for text in sent)
    assert [
        statement_instruction(opening=opening, hosted=hosted)
        for hosted in (False, True)
        for opening in (True, False)
    ] == [
        STATEMENT_INSTRUCTION,
        FOLLOW_UP_INSTRUCTION,
        HOSTED_STATEMENT_INSTRUCTION,
        HOSTED_FOLLOW_UP_INSTRUCTION,
    ]


def test_the_contexts_of_the_discussion_carry_the_titles_of_the_screens_next_to_their_codes():
    keys = twin_keys(twins())
    view = design_review_view(design_fixtures.design_version())
    titles = screen_titles(view)
    assert titles == [
        {"code": "SCR-001", "title": "Create reservation"},
        {"code": "SCR-002", "title": "Reservation confirmation"},
    ]
    assert screen_titles(opening_context(keys, "T1", view)["design"]) == titles
    statements = first_round(keys).statements
    plain = moderation_context(keys, statements)
    titled = moderation_context(keys, statements, titles)
    assert list(plain) == [
        "project_id",
        "purpose",
        "locale",
        "round",
        "owner_note",
        "participants",
        "statements",
    ]
    assert list(titled) == [*list(plain)[:-1], "screens", "statements"]
    assert titled["screens"] == titles
    assert {key: value for key, value in titled.items() if key != "screens"} == plain
