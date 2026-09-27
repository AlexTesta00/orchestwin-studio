from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from orchestwin.artifacts.design_discussion import (
    DiscussionProposalTarget,
    DiscussionStance,
    create_discussion_round,
)
from orchestwin.artifacts.design_evaluation import design_review_view
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.models.twin_discussion import (
    STATEMENT_OUTPUT_TOKENS,
    SYNTHESIS_OUTPUT_TOKENS,
    bind_statement,
    bind_synthesis,
    discussion_findings,
    known_observations,
    moderate_discussion,
    speak_as_twin,
    statement_context,
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
STATEMENT = {
    "argument": "  Il modulo   è chiaro, ma per me la ricerca è lenta. ",
    "confidence": 0.754,
    "grounded_on": ["user_twin.goals", "user_twin.goals", "user_twin.frustrations"],
    "proposals": ["Mostrare la ricerca in alto.", " Mostrare la ricerca  in alto. "],
    "replies_to": [],
    "stance": "CONCERN",
}
REPLY = {
    "argument": "Sono d'accordo con Receptionist Twin: di notte cerco le prenotazioni in fretta.",
    "confidence": 0.6,
    "grounded_on": ["user_twin.context_of_use"],
    "proposals": [],
    "replies_to": ["T1"],
    "stance": "SUPPORT",
}
SYNTHESIS = {
    "agreements": ["Il flusso è chiaro.", " Il flusso   è chiaro."],
    "conflicts": [
        {
            "positions": [
                {"position": "La ricerca è troppo lenta.", "twin": "T1"},
                {"position": "La ricerca va bene.", "twin": "T2"},
            ],
            "topic": "Velocità della ricerca",
        }
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


def parse_statement(payload, keys, speaker, *, later=False):
    replies = tuple(key for key in keys if key != speaker) if later else ()
    observed = tuple(known_observations(keys[speaker].profile))
    return validated(statement_output_type(observed, replies), payload)


def parse_synthesis(payload, keys):
    return validated(synthesis_output_type(tuple(keys)), payload)


def disagreement(*positions, topic="Velocità della ricerca"):
    return {
        "positions": [
            {"position": position, "twin": f"T{index}"}
            for index, position in enumerate(positions, 1)
        ],
        "topic": topic,
    }


def first_round(keys):
    statements = (
        bind_statement(
            parse_statement(STATEMENT, keys, "T1"),
            speaker="T1",
            keys=keys,
            generation_id=UUID(int=1),
        ),
        bind_statement(
            parse_statement({**REPLY, "replies_to": []}, keys, "T2"),
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
    }
    assert "provenance" not in json.dumps(context["user_twin"])


def test_later_rounds_see_the_previous_round_and_the_synthesis_through_twin_keys():
    keys = twin_keys(twins())
    previous = first_round(keys)
    context = statement_context(
        project_id=design_fixtures.PROJECT_ID,
        locale="it-IT",
        ordinal=2,
        owner_note=None,
        keys=keys,
        speaker="T1",
        design={},
        findings=(),
        previous=previous,
    )
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
                "twin": "T1",
                "stance": "CONCERN",
                "statement": "Il modulo è chiaro, ma per me la ricerca è lenta.",
                "proposals": ["Mostrare la ricerca in alto."],
            },
            {
                "twin": "T2",
                "stance": "SUPPORT",
                "statement": REPLY["argument"],
                "proposals": [],
            },
        ],
        "synthesis": synthesis_view,
    }
    reply = bind_statement(
        parse_statement(REPLY, keys, "T2", later=True),
        speaker="T2",
        keys=keys,
        generation_id=UUID(int=12),
    )
    moderated = synthesis_context(
        project_id=design_fixtures.PROJECT_ID,
        locale="en-US",
        ordinal=2,
        owner_note="Think about night shifts.",
        keys=keys,
        statements=(previous.statements[0], reply),
        previous=previous,
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
            },
            {
                "twin": "T2",
                "name": "Night Auditor Twin",
                "stance": "SUPPORT",
                "argument": REPLY["argument"],
                "proposals": [],
                "replies_to": ["T1"],
            },
        ],
        "previous_synthesis": synthesis_view,
    }
    opening = synthesis_context(
        project_id=design_fixtures.PROJECT_ID,
        locale="it-IT",
        ordinal=1,
        owner_note=None,
        keys=keys,
        statements=previous.statements,
        previous=None,
    )
    assert opening["previous_synthesis"] is None


def test_statement_output_type_writes_the_argument_first_and_bounds_every_field():
    output_type = statement_output_type(("user_twin.goals", "user_twin.role"), ("T2", "T3"))
    fields = ["argument", "confidence", "grounded_on", "proposals", "replies_to", "stance"]
    assert list(output_type.model_fields) == fields == sorted(fields)
    properties = output_type.model_json_schema()["properties"]
    assert (properties["argument"]["minLength"], properties["argument"]["maxLength"]) == (1, 700)
    assert (properties["confidence"]["minimum"], properties["confidence"]["maximum"]) == (0, 1)
    assert properties["grounded_on"]["items"]["enum"] == ["user_twin.goals", "user_twin.role"]
    assert (properties["grounded_on"]["minItems"], properties["grounded_on"]["maxItems"]) == (1, 2)
    assert properties["proposals"]["maxItems"] == 3
    assert properties["proposals"]["items"]["maxLength"] == 300
    assert properties["replies_to"]["items"]["enum"] == ["T2", "T3"]
    assert properties["replies_to"]["maxItems"] == 2
    assert properties["stance"]["enum"] == ["SUPPORT", "CONCERN", "OBJECTION"]
    keys = tuple(field.observation_key for field in UserTwinField)
    assert (
        statement_output_type(keys, ()).model_json_schema()["properties"]["grounded_on"]["maxItems"]
        == 4
    )
    opening = statement_output_type(("user_twin.goals",), ())
    assert opening.model_json_schema()["properties"]["replies_to"]["maxItems"] == 0
    valid = {**REPLY, "grounded_on": ["user_twin.goals"], "replies_to": []}
    assert opening.model_validate(valid).replies_to == []
    for payload in (
        {**valid, "replies_to": ["T2"]},
        {**valid, "grounded_on": ["user_twin.role"]},
        {**valid, "grounded_on": []},
        {**valid, "argument": ""},
        {**valid, "argument": "x" * 701},
        {**valid, "confidence": 1.5},
        {**valid, "proposals": ["Uno.", "Due.", "Tre.", "Quattro."]},
        {**valid, "stance": "NEUTRAL"},
        {**valid, "extra": True},
    ):
        with pytest.raises(ValidationError):
            opening.model_validate(payload)
    with pytest.raises(ValueError, match="known profile observation"):
        statement_output_type((), ())


def test_synthesis_output_type_bounds_the_moderator_and_its_twin_keys():
    output_type = synthesis_output_type(("T1", "T2", "T3"))
    fields = ["agreements", "conflicts", "proposals", "questions_for_owner"]
    assert list(output_type.model_fields) == fields == sorted(fields)
    schema = output_type.model_json_schema()
    properties, definitions = schema["properties"], schema["$defs"]
    assert properties["agreements"]["maxItems"] == 5
    assert properties["agreements"]["items"]["maxLength"] == 300
    assert properties["conflicts"]["maxItems"] == 4
    assert properties["proposals"]["maxItems"] == 5
    assert properties["questions_for_owner"]["maxItems"] == 4
    assert properties["questions_for_owner"]["items"]["maxLength"] == 300
    conflict = definitions["DiscussionConflictOutput"]["properties"]
    assert list(conflict) == ["positions", "topic"]
    positions = conflict["positions"]
    assert (positions["minItems"], positions["maxItems"]) == (3, 3)
    assert [item["$ref"] for item in positions["prefixItems"]] == [
        "#/$defs/DiscussionPositionT1",
        "#/$defs/DiscussionPositionT2",
        "#/$defs/DiscussionPositionT3",
    ]
    assert conflict["topic"]["maxLength"] == 200
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
    assert single["properties"]["conflicts"]["maxItems"] == 0
    lone = single["$defs"]["DiscussionConflictOutput"]["properties"]["positions"]
    assert (lone["minItems"], lone["maxItems"], len(lone["prefixItems"])) == (1, 1, 1)
    complete = disagreement("La ricerca è troppo lenta.", None, "La ricerca va bene.")
    valid = {**SYNTHESIS, "conflicts": [complete]}
    parsed = validated(output_type, valid).conflicts[0].positions
    assert [(item.twin, item.position) for item in parsed] == [
        ("T1", "La ricerca è troppo lenta."),
        ("T2", None),
        ("T3", "La ricerca va bene."),
    ]
    first, second, third = complete["positions"]
    for payload in (
        {**valid, "conflicts": [disagreement("Troppo lenta.", "Va bene.")]},
        {**valid, "conflicts": [{**complete, "positions": [second, first, third]}]},
        {**valid, "conflicts": [{**complete, "positions": [first, second, third, third]}]},
        {**valid, "conflicts": [disagreement("Troppo lenta.", "", "Va bene.")]},
        {**valid, "conflicts": [disagreement("Troppo lenta.", "x" * 301, "Va bene.")]},
        {**valid, "conflicts": [{**complete, "positions": [first, {"twin": "T2"}, third]}]},
        {**valid, "proposals": [{**SYNTHESIS["proposals"][0], "supported_by": []}]},
        {**valid, "proposals": [{**SYNTHESIS["proposals"][0], "supported_by": ["T9"]}]},
        {**valid, "proposals": [{**SYNTHESIS["proposals"][0], "target": "CODE"}]},
        {**valid, "questions_for_owner": ["Uno?", "Due?", "Tre?", "Quattro?", "Cinque?"]},
    ):
        with pytest.raises(ValidationError):
            validated(output_type, payload)
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
    assert payload["metadata"]["orchestwin_prompt_version_ref"] == "proposal-twin-discussion-v1"
    assert payload["max_tokens"] == STATEMENT_OUTPUT_TOKENS == 1024
    instruction = payload["messages"][0]["content"]
    assert "never claim to be a real person" in instruction
    assert "at most 90 words" in instruction
    assert (
        "The mockup is static and its sample values, such as names, numbers or texts introduced "
        "by a word like example, only illustrate the content: never object that a value is an "
        "example, that it is not real or that it does not update. Never invent research"
    ) in instruction
    sent = json.loads(payload["messages"][1]["content"])
    assert sent["context"]["purpose"] == "TWIN_STATEMENT"
    assert sent["context"]["speaker"] == "T1"
    schema = payload["response_format"]["json_schema"]["schema"]
    assert list(schema["properties"]) == [
        "argument",
        "confidence",
        "grounded_on",
        "proposals",
        "replies_to",
        "stance",
    ]
    assert schema["properties"]["replies_to"]["maxItems"] == 0
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
                previous=None,
            ),
        )
    )
    payload = transport.calls[0]["payload"]
    assert payload["metadata"]["orchestwin_task_id"] == "proposal-twin-discussion-v1"
    assert payload["metadata"]["orchestwin_prompt_version_ref"] == "proposal-twin-discussion-v2"
    assert payload["response_format"]["json_schema"]["name"] == "proposal-twin-discussion-v2"
    assert payload["max_tokens"] == SYNTHESIS_OUTPUT_TOKENS == 2048
    moderation = payload["messages"][0]["content"]
    assert "neutral moderator" in moderation
    assert "when the twins say the same thing it is an agreement, never a conflict" in moderation
    assert "when there is no real disagreement conflicts is empty" in moderation
    assert "every twin in the order of participants" in moderation
    assert "or null when it said nothing about it" in moderation
    sent_schema = payload["response_format"]["json_schema"]["schema"]
    sent_positions = sent_schema["$defs"]["DiscussionConflictOutput"]["properties"]["positions"]
    assert (sent_positions["minItems"], sent_positions["maxItems"]) == (2, 2)
    assert len(sent_positions["prefixItems"]) == 2
    assert [item.supported_by for item in moderated.proposals] == [["T1", "T2"], ["T2"]]
    assert [item.twin for item in moderated.conflicts[0].positions] == ["T1", "T2"]


def test_output_budgets_never_exceed_the_configured_maximum():
    keys = twin_keys(twins())
    context = statement_context(
        project_id=design_fixtures.PROJECT_ID,
        locale="it-IT",
        ordinal=2,
        owner_note=None,
        keys=keys,
        speaker="T2",
        design={},
        findings=(),
        previous=first_round(keys),
    )
    generator = RecordingGenerator(REPLY)
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
                previous=None,
            ),
        )
    )
    [call] = generator.calls
    assert (call["task"], call["max_output_tokens"]) == ("twin-discussion", 512)
    replies = call["output_type"].model_json_schema()["properties"]["replies_to"]
    assert (replies["items"], replies["maxItems"]) == ({"const": "T1", "type": "string"}, 1)
    [call] = moderator.calls
    assert (call["task"], call["max_output_tokens"]) == ("twin-discussion", 2048)


def test_bind_statement_maps_keys_to_twins_and_normalizes_the_output():
    keys = twin_keys(twins(3))
    statement = bind_statement(
        parse_statement({**STATEMENT, "replies_to": ["T3", "T2"]}, keys, "T1", later=True),
        speaker="T1",
        keys=keys,
        generation_id=UUID(int=5),
    )
    assert statement.twin_id == keys["T1"].twin_id
    assert (statement.twin_version, statement.twin_name) == (1, "Receptionist Twin")
    assert statement.stance is DiscussionStance.CONCERN
    assert statement.statement == "Il modulo è chiaro, ma per me la ricerca è lenta."
    assert statement.replies_to == (THIRD_TWIN_ID, SECOND_TWIN_ID)
    assert statement.proposals == ("Mostrare la ricerca in alto.",)
    assert statement.grounded_on == ("user_twin.goals", "user_twin.frustrations")
    assert statement.confidence == 0.75
    assert statement.model_generation_id == UUID(int=5)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"replies_to": ["T2", "T2"]}, "each twin once"),
        ({"replies_to": ["T1"]}, "itself"),
        ({"replies_to": ["T9"]}, "unknown discussion participant"),
        ({"argument": "   "}, "must not be empty"),
        ({"proposals": ["  "]}, "must not be empty"),
        ({"grounded_on": []}, "grounding"),
        ({"stance": "NEUTRAL"}, "NEUTRAL"),
    ],
)
def test_bind_statement_rejects_inconsistent_outputs(changes, message):
    keys = twin_keys(twins(3))
    output = SimpleNamespace(**{**STATEMENT, **changes})
    with pytest.raises(ValueError, match=message):
        bind_statement(output, speaker="T1", keys=keys, generation_id=UUID(int=5))


def test_bind_synthesis_maps_keys_numbers_proposals_and_merges_repeated_texts():
    keys = twin_keys(twins())
    synthesis = bind_synthesis(
        parse_synthesis(SYNTHESIS, keys), keys=keys, generation_id=UUID(int=9)
    )
    first, second = keys["T1"].twin_id, keys["T2"].twin_id
    assert synthesis.agreements == ("Il flusso è chiaro.",)
    assert synthesis.conflicts[0].topic == "Velocità della ricerca"
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


def test_bind_synthesis_keeps_only_the_twins_that_took_a_position():
    keys = twin_keys(twins(3))
    payload = {**SYNTHESIS, "conflicts": [disagreement("Troppo lenta.", None, "Va bene.")]}
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


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"conflicts": [disagreement("Troppo lenta.", None)]}, "two distinct twins"),
        ({"conflicts": [disagreement(None, "Va bene.")]}, "two distinct twins"),
        ({"conflicts": [disagreement(None, None)]}, "two distinct twins"),
        (
            {"proposals": [{**SYNTHESIS["proposals"][0], "supported_by": ["T1", "T1"]}]},
            "distinct supporting twins",
        ),
        ({"proposals": [{**SYNTHESIS["proposals"][0], "text": "   "}]}, "must not be empty"),
        (
            {"proposals": [SYNTHESIS["proposals"][0], SYNTHESIS["proposals"][0]]},
            "must be distinct",
        ),
        ({"conflicts": [{**SYNTHESIS["conflicts"][0], "topic": " "}]}, "must not be empty"),
        ({"agreements": ["  "]}, "must not be empty"),
    ],
)
def test_bind_synthesis_rejects_inconsistent_outputs(changes, message):
    keys = twin_keys(twins())
    output = parse_synthesis({**SYNTHESIS, **changes}, keys)
    with pytest.raises(ValueError, match=message):
        bind_synthesis(output, keys=keys, generation_id=UUID(int=9))


def test_bind_synthesis_rejects_repeated_twins_and_twins_outside_the_discussion():
    keys = twin_keys(twins())
    outside = SimpleNamespace(
        agreements=[],
        conflicts=[],
        proposals=[SimpleNamespace(supported_by=["T7"], target="DESIGN", text="Una modifica.")],
        questions_for_owner=[],
    )
    with pytest.raises(ValueError, match="unknown discussion participant"):
        bind_synthesis(outside, keys=keys, generation_id=UUID(int=9))
    repeated = SimpleNamespace(
        agreements=[],
        conflicts=[
            SimpleNamespace(
                topic="Ricerca",
                positions=(
                    SimpleNamespace(position="Troppo lenta.", twin="T1"),
                    SimpleNamespace(position="Va bene.", twin="T1"),
                ),
            )
        ],
        proposals=[],
        questions_for_owner=[],
    )
    with pytest.raises(ValueError, match="two distinct twins"):
        bind_synthesis(repeated, keys=keys, generation_id=UUID(int=9))
