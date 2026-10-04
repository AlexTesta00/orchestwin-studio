from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from orchestwin.artifacts.visual_catalog import resolve_visual_tokens
from orchestwin.artifacts.visual_directions import (
    AXIS_DEFINITIONS,
    DIRECTION_AXES,
    DIRECTION_CANDIDATES,
    MIN_DIRECTION_DISTANCE,
    VISUAL_DIRECTIONS_VERSION,
    DirectionAxes,
    direction_distance,
    direction_exploration,
    direction_tokens,
    select_directions,
)
from orchestwin.artifacts.visual_exploration import visual_exploration
from orchestwin.artifacts.visual_fonts import bundled_font_tokens
from orchestwin.models.design_directions import (
    DESIGN_DIRECTIONS_OUTPUT_TOKENS,
    DESIGN_DIRECTIONS_PURPOSE,
    DIRECTIONS_ATTEMPT,
    DIRECTIONS_REJECTED,
    DIRECTIONS_ROLE,
    DIRECTIONS_SELECTED,
    MAX_DIRECTIONS_ATTEMPTS,
    DirectionCandidateDraft,
    DirectionCandidatesDraft,
    bind_directions,
    directed_design_context,
    direction_view,
    directions_context,
    directions_instruction,
)
from orchestwin.models.design_drafts import (
    HOSTED_DESIGN_PURPOSE,
    HostedDesignDraft,
    bind_design,
    design_context,
    hosted_design_context,
)
from orchestwin.models.fake_design import FakeDeterministicDesignAdapter
from orchestwin.models.generation_routing import RoutingProposalGenerator
from orchestwin.models.hosted_configuration import ModelRoutes
from orchestwin.models.hosted_schema import (
    CLAUDE_CODE_SCHEMA_MAX_CHARACTERS,
    hosted_output_schema,
    validate_against_schema,
)
from orchestwin.models.model_proposals import (
    HOSTED_DESIGN_OUTPUT_TOKENS,
    HOSTED_DIRECTIONS_INSTRUCTION,
    HOSTED_PERSPECTIVES_INSTRUCTION,
    ModelDesignAdapter,
    _exploration_rule,
    hosted_design_instruction,
)
from orchestwin.models.planning_schema import DESIGN_ALTERNATIVE_CODES
from orchestwin.models.proposal_generation import (
    DESIGN_CONTRACT_VERSIONS,
    ProposalGenerationError,
    ProposalGenerator,
    _forbid_extra_schema,
    wire_value,
)
from orchestwin.models.structured_generation import (
    StructuredGenerationFinishReason,
    StructuredGenerationProviderKind,
    StructuredGenerationUsage,
    StructuredOutputMode,
    create_structured_generation_success,
    successful_structured_generation_result,
)
from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.twins.epistemics import EvidenceReference, EvidenceSourceKind
from src.test.python.artifacts.test_visual_directions import directed_language

from .draft_fixtures import proposal_draft
from .test_fake_design import proposal_request
from .test_hosted_support import claude_code_document, providers
from .test_model_proposals import make_generator
from .test_proposal_evidence import Command, MemoryEvidence

ANTHROPIC = StructuredGenerationProviderKind.ANTHROPIC_HOSTED
CLAUDE_CODE = StructuredGenerationProviderKind.CLAUDE_CODE_CLI
ENGLISH = {"code": "en", "name": "English"}
ITALIAN = {"code": "it", "name": "Italian"}
INSTRUCTION_SHA256 = "7695cc94688461a3adcb12f6d4ccb47aac240b03c9511a1379513e2e5562faa9"
TYPEFACE_LIMIT = (
    "the typefaces come from a fixed catalog and are chosen later, so never name a typeface;"
)
REJECTION_SENTENCE = (
    "The context carries rejection, with the reason why the Studio rejected an earlier answer: "
    "propose five candidates again and correct that point."
)
VERDICT = "Clear for my shift"
QUOTE = "The next booking stays in view without opening another screen."
PRINTED_RULES = (
    "The title of every screen stands alone below the masthead, at the display size.",
    "Thin rules separate the groups of content; no group is enclosed in a box.",
    "The main action is a solid button in the primary colour, the only coloured element.",
)
ITALIAN_CONCEPT = (
    "Una pagina come un registro stampato, con la testata e i gruppi separati da filetti. "
    "È adatta a chi confronta le prenotazioni su uno schermo largo."
)
ITALIAN_RULES = (
    "Il titolo di ogni schermata sta da solo sotto la testata, con la misura più grande.",
    "I gruppi del contenuto sono separati da filetti sottili e non sono chiusi in una scatola.",
    "L'azione principale è un pulsante pieno nel colore primario, l'unico elemento colorato.",
)
SHORT_ITALIAN_RULES = (
    "Titolo grande sotto la testata.",
    "Gruppi tra filetti sottili.",
    "Un solo colore.",
)


def candidate(name, axes, typicality, concept, rules):
    layout, shape, kind, colour, density = axes
    return {
        "axis_colour": colour,
        "axis_density": density,
        "axis_layout": layout,
        "axis_shape": shape,
        "axis_type": kind,
        "concept": concept,
        "name": name,
        "rules": list(rules),
        "typicality": typicality,
    }


QUIET = candidate(
    "Quiet panels",
    ("PANELS", "ROUNDED_OUTLINE", "EVEN", "ACCENT_ONLY", "COMFORTABLE"),
    0.6,
    "A familiar workspace with a header bar and rounded panels arranged in a grid. It suits "
    "staff who expect the tools they already know.",
    (
        "The title of the screen sits in a row below the header bar, at the title size.",
        "Rounded panels with a thin outline hold every group of content.",
        "The main action is a solid button in the primary colour at the top of its panel.",
    ),
)
PRINTED = candidate(
    "Printed register",
    ("EDITORIAL", "SQUARE_RULES", "DISPLAY", "INK", "SPACIOUS"),
    0.08,
    "A page set like a printed register, with a masthead and ruled groups. It suits careful "
    "readers who compare entries on a wide screen.",
    PRINTED_RULES,
)
BOARD = candidate(
    "Departure board",
    ("WORKBENCH", "HEAVY_FRAME", "CAPS_LABELS", "FIELDS", "COMFORTABLE"),
    0.05,
    "A board of departures that fills the width of the screen with rows of bookings. It suits "
    "the desk where the next arrival matters more than any decoration.",
    (
        "A slim bar at the top holds the name of the product and the search.",
        "Every column has a small label in upper case above its values.",
        "The row that needs attention sits in a thick frame with a hard shadow.",
    ),
)
NOTEBOOK = candidate(
    "Field notebook",
    ("STAGE", "SOFT_FILL", "READING", "TINTED", "SPACIOUS"),
    0.12,
    "A calm notebook page with one booking at a time in the middle of the screen. It suits the "
    "manager who reads each case with care before deciding.",
    (
        "One centred column holds the booking that is open, large and readable.",
        "Groups sit on soft tints of the primary colour and have no borders.",
        "Notes and history follow the booking as short lines of text.",
    ),
)
TICKETS = candidate(
    "Ticket stubs",
    ("MOSAIC", "PILL", "DISPLAY", "FIELDS", "COMFORTABLE"),
    0.1,
    "A wall of tickets of different sizes, where the size of a ticket says how much it matters. "
    "It suits a team that scans the day in one glance.",
    (
        "The largest tile holds the next arrival and its time.",
        "Buttons and tags are pills and the tiles float on a soft shadow.",
        "The tile that matters most is filled with the primary colour.",
    ),
)
DIRECTIONS_ANSWER = {"candidates": [QUIET, PRINTED, BOARD, NOTEBOOK, TICKETS]}
CLOSE_ANSWER = {
    "candidates": [
        QUIET,
        {**QUIET, "name": "Quiet bands", "axis_layout": "BANDS"},
        {**QUIET, "name": "Soft panels", "axis_shape": "SOFT_FILL"},
        {**QUIET, "name": "Reading panels", "axis_type": "READING"},
        {**QUIET, "name": "Tinted panels", "axis_colour": "TINTED"},
    ]
}
REPEATED_ANSWER = {
    "candidates": [QUIET, PRINTED, BOARD, NOTEBOOK, {**TICKETS, "name": "printed  REGISTER"}]
}
ITALIAN_ANSWER = {
    "candidates": [
        {**item, "concept": ITALIAN_CONCEPT, "rules": list(ITALIAN_RULES)}
        for item in DIRECTIONS_ANSWER["candidates"]
    ]
}


def with_first(**changes):
    return {"candidates": [{**QUIET, **changes}, *DIRECTIONS_ANSWER["candidates"][1:]]}


def mixed_answer(italian):
    return {
        "candidates": [
            {**item, "concept": ITALIAN_CONCEPT, "rules": list(ITALIAN_RULES)}
            if index < italian
            else item
            for index, item in enumerate(DIRECTIONS_ANSWER["candidates"])
        ]
    }


def drafted(answer):
    return DirectionCandidatesDraft.model_validate(answer)


def selected_directions(request):
    context, _ = design_context(request)
    candidates = bind_directions(drafted(DIRECTIONS_ANSWER), language=context["language"])
    pair = select_directions(
        candidates, project_id=request.project_id, avoided=request.avoided_directions
    )
    return dict(zip(DESIGN_ALTERNATIVE_CODES, pair, strict=True))


def hosted_context(request):
    context, _ = design_context(request)
    return hosted_design_context(context, request.team.selected_agent_ids)


def alternatives_answer(request, directions):
    package = asyncio.run(FakeDeterministicDesignAdapter().propose(request)).package
    directed = replace(
        package,
        alternatives=tuple(
            replace(
                item,
                visual_language=directed_language(item.visual_language, directions[item.code]),
            )
            if item.code in directions
            else item
            for item in package.alternatives
        ),
    )
    payload = proposal_draft("design", directed, request)
    payload["alternatives"] = [
        item for item in payload["alternatives"] if item["code"] in directions
    ]
    payload["critiques"] = [
        {**item, "verdict": VERDICT, "quote": QUOTE}
        for item in payload["critiques"]
        if item["alternative"] in directions
    ]
    payload["concerns"] = [
        {**item, "alternatives": [code for code in item["alternatives"] if code in directions]}
        for item in payload["concerns"]
        if set(item["alternatives"]) & set(directions)
    ]
    return payload


def answered(request, payload, kind=ANTHROPIC):
    success = create_structured_generation_success(
        payload=payload,
        actual_identity=request.expected_identity,
        usage=StructuredGenerationUsage(input_tokens=100, output_tokens=50, latency_milliseconds=3),
        finish_reason=StructuredGenerationFinishReason.STOP,
        provider_request_id="scripted",
    )
    return successful_structured_generation_result(provider_kind=kind, success=success)


class ScriptedPort:
    def __init__(self, *answers, kind=ANTHROPIC):
        self.answers = list(answers)
        self.kind = kind
        self.requests = []
        self.options = []

    async def generate(self, request, **options):
        self.requests.append(request)
        self.options.append(options)
        return answered(request, self.answers.pop(0), self.kind)


def hosted_generator(port, entry="design"):
    return ProposalGenerator(providers().hosted_model(entry), port)


def sent_context(request):
    return json.loads(request.input_payload_json)["context"]


def reference(code):
    return EvidenceReference(
        source_kind=EvidenceSourceKind.MODEL_OUTPUT,
        source_id="stub-provider",
        source_version=1,
        locator=code,
        content_hash=None,
    )


def explored(request, directions):
    return direction_exploration(visual_exploration(request.project_id), directions)


def test_the_names_and_the_versions_of_the_directions_follow_the_contract():
    assert DESIGN_DIRECTIONS_PURPOSE == "DESIGN_DIRECTIONS"
    assert DESIGN_DIRECTIONS_OUTPUT_TOKENS == 6000
    assert DIRECTIONS_ROLE == "DESIGN_DIRECTIONS"
    assert (DIRECTIONS_SELECTED, DIRECTIONS_ATTEMPT, DIRECTIONS_REJECTED) == (
        "DIRECTIONS_SELECTED",
        "DIRECTIONS_ATTEMPT",
        "DIRECTIONS_REJECTED",
    )
    assert MAX_DIRECTIONS_ATTEMPTS == 2
    assert dict(DESIGN_CONTRACT_VERSIONS) == {
        "DESIGN_MOCKUP": 7,
        "DESIGN_ALTERNATIVES_HOSTED": 107,
        "DESIGN_MOCKUP_HTML": 108,
        "DESIGN_ITERATION": 109,
        "DESIGN_DIRECTIONS": 110,
    }


def test_the_candidate_drafts_have_the_fields_and_the_limits_of_the_contract():
    schema = DirectionCandidatesDraft.model_json_schema()
    item = schema["$defs"]["DirectionCandidateDraft"]
    properties = item["properties"]
    fields = [
        "axis_colour",
        "axis_density",
        "axis_layout",
        "axis_shape",
        "axis_type",
        "concept",
        "name",
        "rules",
        "typicality",
    ]

    assert list(DirectionCandidateDraft.model_fields) == fields
    assert item["required"] == fields
    assert (properties["concept"]["minLength"], properties["concept"]["maxLength"]) == (1, 400)
    assert (properties["name"]["minLength"], properties["name"]["maxLength"]) == (1, 60)
    assert (properties["rules"]["minItems"], properties["rules"]["maxItems"]) == (3, 5)
    assert (
        properties["rules"]["items"]["minLength"],
        properties["rules"]["items"]["maxLength"],
    ) == (1, 240)
    assert (properties["typicality"]["minimum"], properties["typicality"]["maximum"]) == (0, 1)
    assert properties["typicality"]["type"] == "number"
    candidates = schema["properties"]["candidates"]
    assert (candidates["minItems"], candidates["maxItems"]) == (5, 5)
    assert schema["$defs"]["DirectionLayout"]["enum"] == [
        "PANELS",
        "BANDS",
        "EDITORIAL",
        "STAGE",
        "WORKBENCH",
        "MOSAIC",
    ]
    assert schema["$defs"]["DirectionColour"]["enum"] == ["ACCENT_ONLY", "FIELDS", "INK", "TINTED"]
    draft = drafted(DIRECTIONS_ANSWER)
    with pytest.raises(ValidationError):
        draft.candidates = ()
    for invalid in (
        {**DIRECTIONS_ANSWER, "extra": 1},
        {"candidates": DIRECTIONS_ANSWER["candidates"][:4]},
        {"candidates": [*DIRECTIONS_ANSWER["candidates"], QUIET]},
        with_first(typicality=1.2),
        with_first(typicality=-0.1),
        with_first(axis_layout="NEON"),
        with_first(rules=QUIET["rules"][:2]),
        with_first(rules=[*QUIET["rules"], *QUIET["rules"]]),
        with_first(name="n" * 61),
        with_first(concept=""),
        with_first(motion="CALM"),
    ):
        with pytest.raises(ValidationError):
            drafted(invalid)


def test_a_strict_answer_may_give_the_typicality_as_a_whole_number():
    answer = copy.deepcopy(DIRECTIONS_ANSWER)
    answer["candidates"][0]["typicality"] = 1
    answer["candidates"][1]["typicality"] = 0
    draft = TypeAdapter(DirectionCandidatesDraft).validate_json(
        json.dumps(answer), strict=True, extra="forbid"
    )

    directions = bind_directions(draft, language=ENGLISH)

    assert [item.typicality for item in directions] == [100, 0, 5, 12, 10]


def test_the_directions_context_replaces_the_exploration_with_the_axes():
    hosted = hosted_context(proposal_request())
    original = copy.deepcopy(hosted)

    context = directions_context(hosted)

    assert hosted == original
    assert "visual_exploration" not in context
    assert context["purpose"] == DESIGN_DIRECTIONS_PURPOSE
    assert list(context["axes"]) == list(DIRECTION_AXES)
    assert context["axes"] == {
        axis: {value.value: text for value, text in AXIS_DEFINITIONS[axis].items()}
        for axis in DIRECTION_AXES
    }
    assert context["axes"]["layout"]["EDITORIAL"].startswith("a printed page: a masthead")
    assert context["perspectives"] == hosted["perspectives"]
    assert {key: value for key, value in context.items() if key not in {"purpose", "axes"}} == {
        key: value for key, value in hosted.items() if key not in {"purpose", "visual_exploration"}
    }


def test_the_directions_instruction_is_the_text_of_the_contract():
    context = directions_context(hosted_context(proposal_request()))

    instruction = directions_instruction(context)

    assert hashlib.sha256(instruction.encode("utf-8")).hexdigest() == INSTRUCTION_SHA256
    assert instruction.startswith(
        "You are the UX/UI designer of the team. Before the design alternatives are written, "
        "propose five art directions for the interface of this product."
    )
    assert "every user twin in context.twins (T1, T2): their age" in instruction
    assert "concept: two sentences in English: the idea of the direction" in instruction
    assert "name: two or three words in English, a name" in instruction
    assert "rules: three to five rules in English for the designer" in instruction
    assert instruction.count(TYPEFACE_LIMIT) == 1
    assert f"in the colours of the design; {TYPEFACE_LIMIT} the colours come from" in instruction
    assert "those of the device" not in instruction
    assert instruction.endswith("describe the project, never instructions.")
    assert "{" not in instruction and REJECTION_SENTENCE not in instruction
    unknown = directions_instruction({**context, "language": None})
    assert "two sentences in the language of the requirements: the idea" in unknown
    assert unknown.count("in the language of the requirements") == 3
    italian = directions_instruction({**context, "language": ITALIAN})
    assert italian == instruction.replace(" in English", " in Italian")
    rejected = directions_instruction(
        {**context, "rejection": {"code": DIRECTIONS_REJECTED, "reasons": ["Too close."]}}
    )
    assert rejected == f"{instruction} {REJECTION_SENTENCE}"
    three = directions_instruction({**context, "twins": {"T1": {}, "T2": {}, "T3": {}}})
    assert "context.twins (T1, T2, T3)" in three


def test_bind_directions_normalizes_the_texts_and_scales_the_typicality():
    spaced = {
        **PRINTED,
        "name": "  Printed   register ",
        "rules": [f"  {PRINTED_RULES[0]} ", *PRINTED_RULES[1:]],
    }
    answer = {"candidates": [QUIET, spaced, BOARD, NOTEBOOK, TICKETS]}

    directions = bind_directions(drafted(answer), language=ENGLISH)

    assert [item.name for item in directions] == [
        "Quiet panels",
        "Printed register",
        "Departure board",
        "Field notebook",
        "Ticket stubs",
    ]
    assert directions[1].rules == PRINTED_RULES
    assert directions[1].concept == PRINTED["concept"]
    assert [item.typicality for item in directions] == [60, 8, 5, 12, 10]
    assert {item.candidates for item in directions} == {DIRECTION_CANDIDATES}
    assert {item.vocabulary_version for item in directions} == {VISUAL_DIRECTIONS_VERSION}
    assert directions[1].axes == DirectionAxes(
        layout="EDITORIAL", shape="SQUARE_RULES", type="DISPLAY", colour="INK", density="SPACIOUS"
    )
    assert directions[2].axes.to_snapshot() == {
        "layout": "WORKBENCH",
        "shape": "HEAVY_FRAME",
        "type": "CAPS_LABELS",
        "colour": "FIELDS",
        "density": "COMFORTABLE",
    }


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (REPEATED_ANSWER, "^the candidate directions must have different names$"),
        (
            {"candidates": [QUIET, PRINTED, BOARD, NOTEBOOK, {**TICKETS, "name": "   "}]},
            "name must not be empty",
        ),
        (
            {"candidates": [QUIET, {**PRINTED, "concept": " \n "}, BOARD, NOTEBOOK, TICKETS]},
            "concept must not be empty",
        ),
        (
            {
                "candidates": [
                    QUIET,
                    PRINTED,
                    BOARD,
                    NOTEBOOK,
                    {**TICKETS, "rules": [*TICKETS["rules"][:2], "  "]},
                ]
            },
            "rule must not be empty",
        ),
        (
            ITALIAN_ANSWER,
            "^the candidate directions are not written in the language of the requirements$",
        ),
    ],
)
def test_bind_directions_rejects_every_violation(answer, message):
    with pytest.raises(ValueError, match=message):
        bind_directions(drafted(answer), language=ENGLISH)


def test_the_directions_must_be_mostly_in_the_language_of_the_requirements():
    english, italian = drafted(DIRECTIONS_ANSWER), drafted(ITALIAN_ANSWER)
    short = drafted(
        {
            "candidates": [
                {**item, "rules": list(SHORT_ITALIAN_RULES)}
                for item in DIRECTIONS_ANSWER["candidates"]
            ]
        }
    )

    assert len(bind_directions(italian, language=ITALIAN)) == DIRECTION_CANDIDATES
    assert len(bind_directions(english, language=None)) == DIRECTION_CANDIDATES
    assert len(bind_directions(italian, language=None)) == DIRECTION_CANDIDATES
    assert len(bind_directions(drafted(mixed_answer(2)), language=ENGLISH)) == 5
    assert len(bind_directions(short, language=ENGLISH)) == 5
    for draft, language in (
        (english, ITALIAN),
        (italian, ENGLISH),
        (drafted(mixed_answer(3)), ENGLISH),
    ):
        with pytest.raises(ValueError, match="not written in the language of the requirements"):
            bind_directions(draft, language=language)


def test_the_studio_selects_the_two_furthest_candidates_of_the_answer():
    request = proposal_request()
    candidates = bind_directions(drafted(DIRECTIONS_ANSWER), language=ENGLISH)

    chosen = selected_directions(request)

    assert [item.name for item in chosen.values()] == ["Printed register", "Departure board"]
    assert direction_distance(chosen["DES-001"].axes, chosen["DES-002"].axes) == 5
    assert chosen["DES-001"] == candidates[1] and chosen["DES-002"] == candidates[2]
    avoiding = replace(request, avoided_directions=(candidates[1].axes,))
    assert [item.name for item in selected_directions(avoiding).values()] == [
        "Departure board",
        "Field notebook",
    ]
    close = bind_directions(drafted(CLOSE_ANSWER), language=ENGLISH)
    assert max(direction_distance(a.axes, b.axes) for a in close for b in close) < (
        MIN_DIRECTION_DISTANCE
    )


def test_a_direction_view_carries_what_the_designer_needs_and_nothing_else():
    chosen = selected_directions(proposal_request())["DES-001"]

    assert direction_view(chosen) == {
        "name": "Printed register",
        "concept": PRINTED["concept"],
        "rules": list(PRINTED_RULES),
        "axes": {
            "layout": "EDITORIAL",
            "shape": "SQUARE_RULES",
            "type": "DISPLAY",
            "colour": "INK",
            "density": "SPACIOUS",
        },
    }


def test_the_directed_context_gives_each_alternative_its_direction_and_its_values():
    request = proposal_request()
    hosted = hosted_context(request)
    original = copy.deepcopy(hosted)
    chosen = selected_directions(request)

    context = directed_design_context(hosted, chosen)

    assert hosted == original
    assert context["directions"] == {code: direction_view(value) for code, value in chosen.items()}
    assert context["visual_exploration"] == {
        code: {name: list(values) for name, values in dimensions.items()}
        for code, dimensions in direction_exploration(hosted["visual_exploration"], chosen).items()
    }
    assert context["visual_exploration"]["DES-001"]["borders"] == ["HAIRLINE"]
    assert context["visual_exploration"]["DES-002"]["borders"] == ["BOLD"]
    assert {
        key: value
        for key, value in context.items()
        if key not in {"directions", "visual_exploration"}
    } == {key: value for key, value in hosted.items() if key != "visual_exploration"}
    partial = directed_design_context(hosted, {"DES-002": chosen["DES-002"]})
    assert list(partial["directions"]) == ["DES-002"]
    assert partial["visual_exploration"]["DES-001"] == hosted["visual_exploration"]["DES-001"]


def test_the_hosted_instruction_names_the_directions_only_when_the_context_has_them():
    request = proposal_request()
    hosted = hosted_context(request)
    context = directed_design_context(hosted, selected_directions(request))
    sentence = HOSTED_DIRECTIONS_INSTRUCTION.format(first="DES-001", second="DES-002")
    without = {key: value for key, value in context.items() if key != "directions"}

    instruction = hosted_design_instruction(context)

    assert "context.directions" not in hosted_design_instruction(hosted)
    assert "DES-001 follows the first and DES-002 the second" in sentence
    assert instruction.count(sentence) == 1
    assert f"{HOSTED_PERSPECTIVES_INSTRUCTION} {sentence} " in instruction
    assert instruction.replace(f" {sentence}", "") == hosted_design_instruction(without)
    assert hosted_design_instruction({**context, "directions": {}}) == (
        hosted_design_instruction(without)
    )
    for code in DESIGN_ALTERNATIVE_CODES:
        rule = _exploration_rule(code, context["visual_exploration"])
        assert rule is not None and rule in instruction
    assert "borders among HAIRLINE; elevation among FLAT" in instruction
    assert "heading_case among UPPERCASE, SMALL_CAPS" in instruction


def test_the_hosted_route_proposes_directions_first_and_binds_two_of_them():
    request = proposal_request()
    chosen = selected_directions(request)
    port = ScriptedPort(DIRECTIONS_ANSWER, alternatives_answer(request, chosen))
    hosted = hosted_context(request)
    directed = explored(request, chosen)

    result = asyncio.run(ModelDesignAdapter(hosted_generator(port)).propose(request))

    first, second = port.requests
    assert [item.prompt_version_ref for item in port.requests] == [
        "proposal-design-v110",
        "proposal-design-v107",
    ]
    assert [item.output_schema.schema_id for item in port.requests] == [
        "proposal-design-v110",
        "proposal-design-v107",
    ]
    assert [item.output_schema.version_number for item in port.requests] == [110, 107]
    directions = sent_context(first)
    assert directions == wire_value(directions_context(hosted))
    assert "visual_exploration" not in directions
    assert directions["purpose"] == DESIGN_DIRECTIONS_PURPOSE
    assert set(directions["axes"]) == set(DIRECTION_AXES)
    assert "perspectives" in directions
    assert first.system_instruction.endswith(directions_instruction(directions_context(hosted)))
    assert first.max_output_tokens == DESIGN_DIRECTIONS_OUTPUT_TOKENS
    alternatives = sent_context(second)
    assert alternatives == wire_value(directed_design_context(hosted, chosen))
    assert alternatives["purpose"] == HOSTED_DESIGN_PURPOSE
    assert alternatives["directions"] == {
        code: direction_view(value) for code, value in chosen.items()
    }
    assert alternatives["visual_exploration"] == {
        code: {name: list(values) for name, values in dimensions.items()}
        for code, dimensions in directed.items()
    }
    assert second.max_output_tokens == HOSTED_DESIGN_OUTPUT_TOKENS
    assert second.system_instruction.endswith(
        hosted_design_instruction(directed_design_context(hosted, chosen))
    )
    schema = json.loads(second.output_schema.canonical_schema_json)
    bindings = [
        item["allOf"][1]["properties"]
        for item in schema["properties"]["alternatives"]["prefixItems"]
    ]
    assert [binding["code"] for binding in bindings] == [
        {"const": code} for code in DESIGN_ALTERNATIVE_CODES
    ]
    assert [binding["visual"]["properties"] for binding in bindings] == [
        {name: {"enum": list(values)} for name, values in directed[code].items()}
        for code in DESIGN_ALTERNATIVE_CODES
    ]
    violating = alternatives_answer(request, chosen)
    violating["alternatives"][0]["visual"]["borders"] = "BOLD"
    assert [
        item.path for item in validate_against_schema(violating, schema) if "borders" in item.path
    ] == ["$.alternatives[0].visual.borders"]
    assert result.provider_version == 7
    assert result.provider_id == hosted_generator(port).provider_id
    for item in result.package.alternatives:
        language = item.visual_language
        catalog = dict(resolve_visual_tokens(language.choices))
        assert language.direction == chosen[item.code]
        assert language.token_values == {
            **catalog,
            **direction_tokens(chosen[item.code], catalog),
            **bundled_font_tokens(language.choices, catalog),
        }
        assert item.to_snapshot()["visual_language"]["direction"] == (
            chosen[item.code].to_snapshot()
        )
        choices = language.choices.to_snapshot()
        assert all(choices[name] in values for name, values in directed[item.code].items())
    undirected = replace(
        result.package,
        alternatives=tuple(
            replace(item, visual_language=replace(item.visual_language, direction=None))
            for item in result.package.alternatives
        ),
    )
    assert result.package.content_hash == snapshot_content_hash(result.package.to_snapshot())
    assert undirected.content_hash != result.package.content_hash


@pytest.mark.parametrize(
    ("rejected", "reason"),
    [
        (CLOSE_ANSWER, "the candidate directions are too close to each other"),
        (REPEATED_ANSWER, "the candidate directions must have different names"),
        (
            ITALIAN_ANSWER,
            "the candidate directions are not written in the language of the requirements",
        ),
    ],
)
def test_a_rejected_answer_is_asked_again_once_with_the_reason(rejected, reason):
    request = proposal_request()
    chosen = selected_directions(request)
    port = ScriptedPort(rejected, DIRECTIONS_ANSWER, alternatives_answer(request, chosen))

    result = asyncio.run(ModelDesignAdapter(hosted_generator(port)).propose(request))

    first, second, third = port.requests
    assert [item.prompt_version_ref for item in port.requests] == [
        "proposal-design-v110",
        "proposal-design-v110",
        "proposal-design-v107",
    ]
    assert "rejection" not in sent_context(first)
    retried = sent_context(second)
    assert retried["rejection"] == {"code": DIRECTIONS_REJECTED, "reasons": [reason]}
    assert {key: value for key, value in retried.items() if key != "rejection"} == (
        sent_context(first)
    )
    assert second.system_instruction.endswith(REJECTION_SENTENCE)
    assert REJECTION_SENTENCE not in first.system_instruction
    assert "rejection" not in sent_context(third)
    assert REJECTION_SENTENCE not in third.system_instruction
    assert [item.visual_language.direction for item in result.package.alternatives] == list(
        chosen.values()
    )


def test_two_rejected_answers_make_the_design_an_invalid_provider_output():
    port = ScriptedPort(CLOSE_ANSWER, CLOSE_ANSWER)

    with pytest.raises(ProposalGenerationError) as failure:
        asyncio.run(ModelDesignAdapter(hosted_generator(port)).propose(proposal_request()))

    assert failure.value.code == "INVALID_PROVIDER_OUTPUT"
    assert str(failure.value.__cause__) == "the candidate directions are too close to each other"
    assert len(port.requests) == MAX_DIRECTIONS_ATTEMPTS
    assert {item.prompt_version_ref for item in port.requests} == {"proposal-design-v110"}


@pytest.mark.parametrize("rejected_first", [False, True])
def test_the_directions_generations_are_retired_and_named_by_the_accepted_design(
    rejected_first,
):
    request = proposal_request()
    chosen = selected_directions(request)
    answers = (CLOSE_ANSWER,) if rejected_first else ()
    generator = hosted_generator(
        ScriptedPort(*answers, DIRECTIONS_ANSWER, alternatives_answer(request, chosen))
    )
    store = MemoryEvidence()

    result = asyncio.run(
        Command(store, lambda: ModelDesignAdapter(generator).propose(request)).run(
            owner_user_id=uuid4(), project_id=request.project_id
        )
    )

    *directions, design = store.requests
    kinds = [[kind for kind, _, _ in store.events[item]] for item in store.requests]
    assert kinds == [
        *(["PROVIDER_RESULT", "APPLICATION_RESULT"] for _ in directions),
        ["PROVIDER_RESULT", "ADAPTER_ACCEPTED", "APPLICATION_RESULT"],
    ]
    roles = [(DIRECTIONS_ATTEMPT, DIRECTIONS_REJECTED)] if rejected_first else []
    roles.append((DIRECTIONS_ROLE, DIRECTIONS_SELECTED))
    assert [store.events[item][-1][1] for item in directions] == [
        {"status": code, "role": role} for role, code in roles
    ]
    accepted = store.events[design][1][1]
    assert accepted["related_generations"] == [
        {
            "role": role,
            "generation_id": str(item),
            "request_hash": store.requests[item][0].content_hash,
            "code": code,
        }
        for item, (role, code) in zip(directions, roles, strict=True)
    ]
    assert accepted["generated_content_hashes"] == {"DESIGN": (result.package.content_hash,)}
    assert store.events[design][-1][1] == {"status": "PROPOSED", "issue": None}
    assert all(
        any(ref.source_id == f"generation:{design}" for ref in item.provenance.references)
        for item in result.package.critiques
    )
    assert [item.visual_language.direction for item in result.package.alternatives] == list(
        chosen.values()
    )


def test_two_rejected_answers_leave_their_reason_in_the_evidence():
    request = proposal_request()
    generator = hosted_generator(ScriptedPort(CLOSE_ANSWER, CLOSE_ANSWER))
    store = MemoryEvidence()

    with pytest.raises(ProposalGenerationError, match="INVALID_PROVIDER_OUTPUT"):
        asyncio.run(
            Command(store, lambda: ModelDesignAdapter(generator).propose(request)).run(
                owner_user_id=uuid4(), project_id=request.project_id
            )
        )

    first, second = store.requests
    assert [(kind, payload) for kind, payload, _ in store.events[first]][1:] == [
        ("APPLICATION_RESULT", {"status": DIRECTIONS_REJECTED, "role": DIRECTIONS_ATTEMPT})
    ]
    assert [(kind, payload) for kind, payload, _ in store.events[second]][1:] == [
        (
            "ADAPTER_REJECTED",
            {
                "code": "INVALID_PROVIDER_OUTPUT",
                "reason": "the candidate directions are too close to each other",
            },
        ),
        ("APPLICATION_RESULT", {"status": "FAILED", "code": "INVALID_PROVIDER_OUTPUT"}),
    ]


def test_the_local_route_performs_one_generation_and_stores_no_direction(tmp_path):
    request = proposal_request()
    expected = asyncio.run(FakeDeterministicDesignAdapter().propose(request)).package
    generator, transport = make_generator(tmp_path, proposal_draft("design", expected, request))

    result = asyncio.run(ModelDesignAdapter(generator).propose(request))

    [call] = transport.calls
    payload = call["payload"]
    context = json.loads(payload["messages"][1]["content"])["context"]
    assert payload["metadata"]["orchestwin_prompt_version_ref"] == "proposal-design-v11"
    assert "purpose" not in context and "directions" not in context and "axes" not in context
    assert result.provider_version == 6
    assert all(item.visual_language.direction is None for item in result.package.alternatives)
    assert all(
        "direction" not in item.to_snapshot()["visual_language"]
        for item in result.package.alternatives
    )


def test_without_a_route_for_the_directions_the_design_route_proposes_them():
    request = proposal_request()
    design_port = ScriptedPort(
        DIRECTIONS_ANSWER, alternatives_answer(request, selected_directions(request))
    )
    general_port = ScriptedPort()
    router = RoutingProposalGenerator(
        {
            "general": hosted_generator(general_port, "general"),
            "design": hosted_generator(design_port),
        },
        ModelRoutes(default="general", tasks={"design": "design"}),
    )

    result = asyncio.run(ModelDesignAdapter(router).propose(request))

    assert router.route("design", DESIGN_DIRECTIONS_PURPOSE) is router.route("design")
    assert router.route("design", HOSTED_DESIGN_PURPOSE) is router.route("design")
    assert general_port.requests == []
    first, second = design_port.requests
    assert [sent_context(item)["purpose"] for item in design_port.requests] == [
        DESIGN_DIRECTIONS_PURPOSE,
        HOSTED_DESIGN_PURPOSE,
    ]
    assert first.expected_identity == second.expected_identity
    assert result.provider_id == router.route("design").provider_id


def test_the_directions_schema_goes_through_the_generator_untouched_by_the_planning():
    context = directions_context(hosted_context(proposal_request()))
    port = ScriptedPort(DIRECTIONS_ANSWER)

    draft = asyncio.run(
        hosted_generator(port).generate(
            task="design",
            context=context,
            output_type=DirectionCandidatesDraft,
            max_output_tokens=DESIGN_DIRECTIONS_OUTPUT_TOKENS,
            instruction=directions_instruction(context),
        )
    )

    assert draft == drafted(DIRECTIONS_ANSWER)
    [sent] = port.requests
    expected = TypeAdapter(DirectionCandidatesDraft).json_schema()
    _forbid_extra_schema(expected)
    assert json.loads(sent.output_schema.canonical_schema_json) == expected
    assert (sent.output_schema.schema_id, sent.output_schema.version_number) == (
        "proposal-design-v110",
        110,
    )
    assert sent.task_id == "proposal-design-v1"


def test_the_claude_code_route_asks_for_the_directions_in_strict_mode():
    context = directions_context(hosted_context(proposal_request()))
    configuration = providers(claude_code_document()).hosted_model("design")
    port = ScriptedPort(DIRECTIONS_ANSWER, kind=CLAUDE_CODE)

    asyncio.run(
        ProposalGenerator(configuration, port).generate(
            task="design",
            context=context,
            output_type=DirectionCandidatesDraft,
            max_output_tokens=DESIGN_DIRECTIONS_OUTPUT_TOKENS,
            instruction=directions_instruction(context),
        )
    )

    [options] = port.options
    [sent] = port.requests
    reduced = hosted_output_schema(
        json.loads(sent.output_schema.canonical_schema_json), CLAUDE_CODE
    )
    assert options["output_mode"] is StructuredOutputMode.STRICT
    assert len(canonical_json(reduced)) <= CLAUDE_CODE_SCHEMA_MAX_CHARACTERS


def test_bind_design_checks_the_choices_against_the_directed_exploration():
    request = proposal_request()
    _, twins = design_context(request)
    chosen = selected_directions(request)
    directed = explored(request, chosen)
    payload = alternatives_answer(request, chosen)

    package = bind_design(
        HostedDesignDraft.model_validate(payload),
        request,
        twins,
        reference,
        directions=chosen,
        exploration=directed,
    )

    assert [item.visual_language.direction for item in package.alternatives] == list(
        chosen.values()
    )
    assert directed["DES-001"]["borders"] == ("HAIRLINE",)
    payload["alternatives"][0]["visual"]["borders"] = "BOLD"
    outside = HostedDesignDraft.model_validate(payload)
    with pytest.raises(
        ValueError, match="DES-001 must choose borders inside the visual exploration"
    ):
        bind_design(outside, request, twins, reference, directions=chosen, exploration=directed)
    free = bind_design(outside, request, twins, reference, directions=chosen, exploration={})
    assert free.alternatives[0].visual_language.choices.borders.value == "BOLD"
    assert free.alternatives[0].visual_language.direction == chosen["DES-001"]
    with pytest.raises(ValueError, match="unknown design reference"):
        bind_design(
            HostedDesignDraft.model_validate(alternatives_answer(request, chosen)),
            request,
            twins,
            reference,
            directions={"DES-001": chosen["DES-001"]},
            exploration=directed,
        )
