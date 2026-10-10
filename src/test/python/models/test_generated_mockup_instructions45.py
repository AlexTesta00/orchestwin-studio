from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from functools import partial
from uuid import UUID

import pytest

from orchestwin.artifacts.visual_catalog import BackgroundTreatment
from orchestwin.artifacts.visual_directions import DirectionType
from orchestwin.models.design_change import MAX_TARGET_LABEL_LENGTH
from orchestwin.models.design_drafts import requirements_language, requirements_view
from orchestwin.models.design_systems import (
    APPLE_HIG,
    MAX_DESIGN_SYSTEM_INSTRUCTION_LENGTH,
    design_system_view,
)
from orchestwin.models.generated_mockup_drafts import (
    MAX_CHANGE_LENGTH,
    MAX_CHANGES,
    GeneratedIterationDraft,
)
from orchestwin.models.generated_mockup_instructions import (
    BACKGROUND_SENTENCES,
    BEFORE_YOU_ANSWER,
    CHANGES_SENTENCE,
    CONSTANT_INSTRUCTION,
    CONSTANT_SECTIONS,
    DESIGN_ITERATION,
    DESIGN_MOCKUP_HTML,
    DESIGN_SYSTEM_HEADING,
    DIRECTED_BEFORE_YOU_ANSWER,
    DIRECTED_INSTRUCTION,
    DIRECTED_PATTERNS_TO_AVOID,
    DIRECTED_SECTIONS,
    DIRECTION_AXIS_SENTENCES,
    ITERATION_SENTENCE,
    LOOK_OF_A_FINISHED_PRODUCT,
    PATTERNS_TO_AVOID,
    REDRAW_SENTENCE,
    REFERENCE_SENTENCE,
    RETRY_SENTENCE,
    RETRY_WITH_ANSWER_SENTENCE,
    TECHNICAL_CONTRACT,
    attribute_line,
    design_section,
    design_system_section,
    mockup_context,
    mockup_instruction,
    target_sentence,
)
from orchestwin.models.proposal_generation import ProposalGenerator
from src.test.python.artifacts.test_visual_directions import directed_package, direction
from src.test.python.models.test_generated_mockup_instructions import (
    DASHBOARD_ID,
    GENERATOR_PREFIX_LENGTH,
    MAXIMUM_SYSTEM_INSTRUCTION,
    DraftPort,
    chosen,
    directed_instruction,
    instruction,
    longest_axes,
)
from src.test.python.models.test_generated_mockup_support import (
    GUIDED_ID,
    PROJECT_ID,
    applied_package,
    iteration_payload,
    package,
    providers,
    requirements_version,
    version,
)

REFERENCE = {
    "note": "Mi piacciono le tessere con i numeri grandi e la foto in testa.",
    "screens": [
        {"code": "REF-001", "file": "reference-001.png", "label": "palestra.png"},
        {"code": "REF-002", "file": "reference-002.png", "label": "banca.png"},
    ],
}
RESOURCES = {
    "icons": ["arrow-right", "calendar", "search", "user"],
    "tones": ["primary", "accent", "neutral", "success", "danger"],
}
LOOK_HEADING = "The look of a finished product"
UNBROKEN_LABELS = (
    "; a button, a pill or a tab never wraps its label: give it `white-space: nowrap` and the "
    "room it needs, and let the row wrap instead."
)
NAMED_IN_BOTH_VARIANTS = (
    "`<svg data-icon='name' aria-hidden='true'></svg>`",
    "`<svg data-picture='name' data-tone='primary' aria-hidden='true'></svg>`",
    "`data-icon`",
    "`data-picture`",
    "`data-tone`",
    "`resources.icons`",
    "`stroke-dasharray` and `stroke-dashoffset`",
    "4.5:1",
    "`var(--vl-shadow)`",
    "never set `outline: none`",
)
SOBER_PHRASES = (
    "sober gradient",
    "not from decoration",
    "Decorative page backgrounds",
    "Every screen is an application screen",
    "Panels share one radius",
    "Icons are small inline SVG drawings",
)
PLACEHOLDERS_ENTRY = (
    "- Placeholders: an `svg` with `data-icon` or `data-picture` is empty, has no `viewBox` and "
    "names an icon of `resources.icons`; it carries `aria-hidden='true'` when it is decorative, or "
    "`role='img'` with an `aria-label` when it stands for content; `data-tone` (`primary`, "
    "`accent`, `neutral`, `success` or `danger`) goes with `data-picture` only. Any other `svg` is "
    "a drawing of your own made of the shapes above, and carries `aria-hidden='true'`."
)
CONTRAST_THRESHOLDS = (
    "The Studio rejects text under 4.5:1 against its background (3:1 at 24 pixels, or at 19 "
    "pixels in bold) and a field or button border under 3:1 against the page; when it can, it "
    "replaces the colour with the token that passes and tells the owner."
)
FOCUS_ENTRY = (
    "- Focus: the Studio outlines the focused control in the primary colour; never set "
    "`outline: none`."
)
SHADOWS = (
    "Shadows are `var(--vl-shadow)` or a `box-shadow` whose colour is a `color-mix` of a token "
    "with `transparent`."
)
GRADIENT_BACKGROUND = (
    "The page opens on a flat tinted field (the soft primary tint or the alternate surface), part "
    "of the design."
)
FLAT_COLOUR = (
    "Colour is flat: no gradient anywhere, not on fields, pictures, buttons or text; depth comes "
    "from tints, from the surfaces and from one soft shadow."
)
FLAT_PICTURES = (
    "the Studio fills it with a flat tinted picture in the colours of the design around the icon "
    "`name`."
)
ROUNDED_CORNERS = (
    "Corners are generously rounded: the panel radius on cards, panels and pictures, the control "
    "radius on fields and buttons, capsules for chips and pills;"
)
ANY_GRADIENT = (
    "- A gradient of any kind; success, danger or accent colours as decoration; grey text on grey."
)
RETIRED_GRADIENTS = (
    "atmospheric",
    "radial gradient",
    "A gradient on text",
    "a gradient between two tokens",
    "Radii are large",
)
LIMITED_CHANGES = "one to eight short texts in {name}, of at most 250 characters each"
FROM_A_DISTANCE = (
    "one focal point, a picture, a chart or a field of colour where the domain calls for it"
)
BRIEF_PLAN = (
    "Plan briefly: the answer itself is the place where the screens are written, do not draft "
    "them twice."
)
PLAIN_BOUND = 26_000
WORST_TARGET = {
    "screen_code": "SCR-002",
    "element_code": "ELM-012",
    "label": '"' * MAX_TARGET_LABEL_LENGTH,
}


def every_sentence():
    return {
        "current_mockup": applied_package().generated_mockup.mockup,
        "previous_answer": iteration_payload(),
        "rejection": {"code": "X", "reasons": []},
        "reference": REFERENCE,
        "target": WORST_TARGET,
        "redraw": {"screens": []},
    }


def context_options(**options):
    return {
        "project_id": PROJECT_ID,
        "purpose": DESIGN_MOCKUP_HTML,
        "command_id": UUID(int=1),
        "version": version(package()),
        "alternative": chosen(GUIDED_ID),
        "requirements": requirements_version(),
        **options,
    }


def test_the_look_of_a_finished_product_follows_the_interface_in_both_variants():
    heading, lines = LOOK_OF_A_FINISHED_PRODUCT
    assert heading == LOOK_HEADING
    assert len(lines) == 11
    for line in lines:
        assert line == " ".join(line.split())
        assert line.startswith("- ")
        assert line.endswith(".")
    assert lines[9].startswith("- Finish the details: ")
    assert lines[9].endswith(UNBROKEN_LABELS)
    assert CONSTANT_SECTIONS[2] is LOOK_OF_A_FINISHED_PRODUCT
    assert DIRECTED_SECTIONS[2] is LOOK_OF_A_FINISHED_PRODUCT
    section = f"{heading}: " + " ".join(lines)
    for constant in (CONSTANT_INSTRUCTION, DIRECTED_INSTRUCTION):
        assert constant.count(section) == 1
        assert (
            constant.index("A finished interface: ")
            < constant.index(section)
            < constant.index("Patterns to avoid: ")
        )
    for identifier in (GUIDED_ID, DASHBOARD_ID):
        for text in (instruction(identifier), directed_instruction(identifier)):
            assert text.count(section) == 1


@pytest.mark.parametrize("words", NAMED_IN_BOTH_VARIANTS)
def test_both_variants_name_the_placeholders_the_charts_the_shadows_and_the_contrast(words):
    assert words in CONSTANT_INSTRUCTION
    assert words in DIRECTED_INSTRUCTION


def test_the_technical_contract_places_the_placeholders_and_the_focus():
    lines = TECHNICAL_CONTRACT[1]
    attributes = lines.index(attribute_line())
    assert lines[attributes + 1] == PLACEHOLDERS_ENTRY
    contrast = next(index for index, line in enumerate(lines) if line.startswith("- Contrast:"))
    assert CONTRAST_THRESHOLDS in lines[contrast]
    assert lines[contrast].endswith("`danger` on `background`, `surface` and `danger-soft`.")
    assert lines[contrast + 1] == FOCUS_ENTRY
    assert lines[contrast + 2].startswith("- Size:")
    styles = next(line for line in lines if line.startswith("- Styles:"))
    assert styles.count(SHADOWS) == 1
    assert "Shadows are `var(--vl-shadow)`. " not in styles


@pytest.mark.parametrize("phrase", SOBER_PHRASES)
def test_no_sentence_of_sobriety_is_left(phrase):
    for text in (
        CONSTANT_INSTRUCTION,
        DIRECTED_INSTRUCTION,
        instruction(),
        instruction(DASHBOARD_ID),
        directed_instruction(),
        directed_instruction(DASHBOARD_ID),
    ):
        assert phrase not in text


def test_the_look_asks_for_flat_colour_and_generously_rounded_corners():
    lines = LOOK_OF_A_FINISHED_PRODUCT[1]
    assert lines[3].startswith("- Surfaces live on levels: ")
    assert lines[3].count(ROUNDED_CORNERS) == 1
    assert lines[4].startswith("- Colour has fields and accents: ")
    assert lines[4].endswith(f"the current item. {FLAT_COLOUR}")
    assert lines[6].startswith("- Pictures: ")
    assert lines[6].count(FLAT_PICTURES) == 1
    assert PATTERNS_TO_AVOID[1][1] == ANY_GRADIENT
    assert DIRECTED_PATTERNS_TO_AVOID[1][1] == ANY_GRADIENT
    for text in (CONSTANT_INSTRUCTION, DIRECTED_INSTRUCTION):
        for words in (ROUNDED_CORNERS, FLAT_COLOUR, FLAT_PICTURES, ANY_GRADIENT):
            assert text.count(words) == 1, words


@pytest.mark.parametrize("phrase", RETIRED_GRADIENTS)
def test_no_sentence_asks_for_a_gradient_any_more(phrase):
    for text in (
        CONSTANT_INSTRUCTION,
        DIRECTED_INSTRUCTION,
        instruction(),
        instruction(DASHBOARD_ID),
        directed_instruction(),
        directed_instruction(DASHBOARD_ID),
        *BACKGROUND_SENTENCES.values(),
    ):
        assert phrase not in text


def test_a_gradient_background_is_a_flat_tinted_field_of_the_design():
    assert BACKGROUND_SENTENCES[BackgroundTreatment.GRADIENT] == GRADIENT_BACKGROUND
    assert all("sober" not in sentence for sentence in BACKGROUND_SENTENCES.values())
    assert all("gradient" not in sentence for sentence in BACKGROUND_SENTENCES.values())
    guided = chosen(GUIDED_ID, directed_package(package()))
    visual = guided.visual_language
    alternative = replace(
        guided,
        visual_language=replace(
            visual, choices=replace(visual.choices, background=BackgroundTreatment.GRADIENT)
        ),
    )
    text = mockup_instruction(
        alternative,
        requirements=requirements_version(),
        language={"code": "it", "name": "Italian"},
        context={},
    )
    assert text.count(GRADIENT_BACKGROUND) == 1
    assert "sober gradient" not in text


def test_both_sections_before_the_answer_look_at_the_screens_from_a_distance():
    for section in (BEFORE_YOU_ANSWER, DIRECTED_BEFORE_YOU_ANSWER):
        [text] = section[1]
        assert text.startswith("Read your screens as the person who will use them")
        assert "from a distance" in text
        assert FROM_A_DISTANCE in text
        assert "icons on its actions and statuses" in text
        assert "unfinished page" in text
        assert text.endswith(f"Correct what fails, then answer. {BRIEF_PLAN}")


def test_the_reference_sentence_follows_the_design_section_only_with_a_reference():
    requirements = requirements_version()
    language = requirements_language(requirements_view(requirements))
    current = applied_package().generated_mockup.mockup
    retry = {"code": "X", "reasons": []}
    schema = {"code": "RESPONSE_SCHEMA_ERROR", "reasons": []}
    directed = chosen(GUIDED_ID, directed_package(package()))
    cases = (
        ({}, ""),
        ({"rejection": schema}, f" {RETRY_SENTENCE}"),
        ({"current_mockup": current}, f" {ITERATION_SENTENCE}"),
        (
            {"current_mockup": current, "previous_answer": iteration_payload(), "rejection": retry},
            f" {ITERATION_SENTENCE}",
        ),
    )
    for options, follower in cases:
        iterating = "current_mockup" in options
        for build, alternative in (
            (instruction, chosen(GUIDED_ID)),
            (directed_instruction, directed),
        ):
            plain = build(**options)
            referenced = build(**options, reference=REFERENCE)
            section = design_section(
                alternative, requirements=requirements, language=language, iteration=iterating
            )
            assert REFERENCE_SENTENCE not in plain
            assert referenced.count(REFERENCE_SENTENCE) == 1
            assert referenced.replace(f" {REFERENCE_SENTENCE}", "", 1) == plain
            assert f"{section} {REFERENCE_SENTENCE}{follower}" in referenced
            if not follower:
                assert referenced.endswith(REFERENCE_SENTENCE)


def test_a_redraw_with_a_reference_keeps_the_order_of_the_sentences():
    current = applied_package().generated_mockup.mockup
    target = {"screen_code": "SCR-002"}
    text = instruction(
        current_mockup=current,
        target=target,
        redraw={"screens": []},
        reference=REFERENCE,
        previous_answer=iteration_payload(),
        rejection={"code": "X", "reasons": []},
    )
    assert (
        text.index(REFERENCE_SENTENCE)
        < text.index(ITERATION_SENTENCE)
        < text.index(target_sentence(target))
        < text.index(REDRAW_SENTENCE)
        < text.index(CHANGES_SENTENCE.format(name="Italian"))
    )
    assert text.endswith(RETRY_WITH_ANSWER_SENTENCE)


def test_the_reference_sentence_names_what_to_take_and_what_never_to_take():
    assert " ".join(REFERENCE_SENTENCE.split()) == REFERENCE_SENTENCE
    for phrase in (
        "listed in `reference.screens` of the context with a `code`, a `file` and a `label`",
        "read every `file` with the Read tool before you answer",
        "`reference.note`, when present, says what the owner likes in them",
        "the level of finish, the rhythm of the spacing, the richness of the composition",
        "never their content, their brand, their text, their photographs or their composition",
        "the art direction of this design still decides the layout, the shapes, the type",
    ):
        assert phrase in REFERENCE_SENTENCE, phrase


def test_the_resources_and_the_reference_reach_the_context_only_when_given():
    plain = mockup_context(**context_options())
    given = mockup_context(**context_options(reference=REFERENCE, resources=RESOURCES))
    assert "reference" not in plain
    assert "resources" not in plain
    assert mockup_context(**context_options(reference=None, resources=None)) == plain
    assert given["reference"] == REFERENCE
    assert given["reference"] is not REFERENCE
    assert given["resources"] == RESOURCES
    assert given["resources"] is not RESOURCES
    assert list(given)[: len(plain)] == list(plain)
    assert list(given)[len(plain) :] == ["reference", "resources"]
    assert {key: value for key, value in given.items() if key in plain} == plain
    for key, value in (("reference", REFERENCE), ("resources", RESOURCES)):
        alone = mockup_context(**context_options(**{key: value}))
        assert set(alone) - set(plain) == {key}


def test_the_resources_change_the_context_but_not_the_instruction():
    assert instruction(resources=RESOURCES) == instruction()
    assert directed_instruction(resources=RESOURCES) == directed_instruction()
    current = applied_package().generated_mockup.mockup
    assert instruction(current_mockup=current, resources=RESOURCES) == instruction(
        current_mockup=current
    )


def test_the_changes_sentence_asks_for_at_most_250_characters_each():
    assert LIMITED_CHANGES in CHANGES_SENTENCE
    assert MAX_CHANGE_LENGTH > 250
    assert MAX_CHANGES == 8
    iteration = instruction(current_mockup=applied_package().generated_mockup.mockup)
    assert iteration.count(LIMITED_CHANGES.format(name="Italian")) == 1
    assert "of at most 250 characters" not in instruction()


def test_an_even_type_keeps_the_display_size_for_the_entry_screen():
    sentence = DIRECTION_AXIS_SENTENCES["type"][DirectionType.EVEN]
    assert sentence.startswith("Type: the scale is restrained. ")
    assert "The title of the entry screen may use var(--vl-size-display);" in sentence
    assert "the titles of the other screens use var(--vl-size-title)" in sentence
    assert "the titles of the groups the body size in the heading weight" in sentence
    assert sentence.endswith("more than from size.")


def test_the_longest_directed_instruction_with_a_reference_keeps_the_bound():
    assert MAXIMUM_SYSTEM_INSTRUCTION == 30_000
    value = direction(axes=longest_axes())
    current = applied_package().generated_mockup.mockup
    retry = {"code": "X", "reasons": []}
    for identifier in (GUIDED_ID, DASHBOARD_ID):
        for system, bound in ((None, PLAIN_BOUND), (APPLE_HIG, MAXIMUM_SYSTEM_INSTRUCTION)):
            text = directed_instruction(
                identifier,
                value,
                current_mockup=current,
                previous_answer=iteration_payload(),
                rejection=retry,
                reference=REFERENCE,
                design_system=system,
            )
            assert text.count(REFERENCE_SENTENCE) == 1
            assert len(text) + GENERATOR_PREFIX_LENGTH < bound, len(text)


def test_the_design_system_fits_in_the_room_that_the_longest_instruction_leaves():
    value = direction(axes=longest_axes())
    section = design_system_section(APPLE_HIG)
    heading = f"{DESIGN_SYSTEM_HEADING}{APPLE_HIG.name}: "
    widest = len(heading) + MAX_DESIGN_SYSTEM_INSTRUCTION_LENGTH

    assert len(section) <= widest
    assert widest + 1 < MAXIMUM_SYSTEM_INSTRUCTION - PLAIN_BOUND
    for identifier in (GUIDED_ID, DASHBOARD_ID):
        for build in (
            partial(instruction, identifier),
            partial(directed_instruction, identifier, value),
        ):
            plain = build(**every_sentence())
            governed = build(**every_sentence(), design_system=APPLE_HIG)
            assert len(governed) == len(plain) + 1 + len(section)
            assert len(plain) + GENERATOR_PREFIX_LENGTH < PLAIN_BOUND, len(plain)
            assert len(governed) + GENERATOR_PREFIX_LENGTH < MAXIMUM_SYSTEM_INSTRUCTION


def test_the_context_carries_the_view_of_the_design_system_only_when_given():
    plain = mockup_context(**context_options())
    given = mockup_context(**context_options(design_system=APPLE_HIG))
    everything = mockup_context(
        **context_options(reference=REFERENCE, resources=RESOURCES, design_system=APPLE_HIG)
    )

    assert "design_system" not in plain
    assert mockup_context(**context_options(design_system=None)) == plain
    assert given["design_system"] == design_system_view(APPLE_HIG)
    assert list(given) == [*plain, "design_system"]
    assert {key: value for key, value in given.items() if key != "design_system"} == plain
    assert list(everything)[len(plain) :] == ["reference", "resources", "design_system"]
    assert json.loads(json.dumps(given["design_system"])) == given["design_system"]


def test_the_section_of_the_design_system_follows_the_section_of_the_design():
    requirements = requirements_version()
    language = requirements_language(requirements_view(requirements))
    current = applied_package().generated_mockup.mockup
    retry = {"code": "X", "reasons": []}
    directed = chosen(GUIDED_ID, directed_package(package()))
    section = design_system_section(APPLE_HIG)
    cases = (
        {},
        {"rejection": retry},
        {"reference": REFERENCE},
        {"current_mockup": current},
        {
            "current_mockup": current,
            "previous_answer": iteration_payload(),
            "rejection": retry,
            "reference": REFERENCE,
        },
    )

    assert DESIGN_SYSTEM_HEADING == "Design system: "
    assert section == f"Design system: {APPLE_HIG.name}: {APPLE_HIG.instruction}"
    for options in cases:
        iterating = "current_mockup" in options
        for build, alternative in (
            (instruction, chosen(GUIDED_ID)),
            (directed_instruction, directed),
        ):
            plain = build(**options)
            governed = build(**options, design_system=APPLE_HIG)
            design = design_section(
                alternative, requirements=requirements, language=language, iteration=iterating
            )
            assert governed.count(APPLE_HIG.instruction) == 1
            assert governed.count(f"{DESIGN_SYSTEM_HEADING}{APPLE_HIG.name}") == 1
            assert f"{design} {section}" in governed
            assert governed.replace(f" {section}", "", 1) == plain
            assert build(**options, design_system=None) == plain
    assert instruction(design_system=APPLE_HIG).endswith(f" {section}")


def test_the_section_of_the_design_system_comes_before_the_reference_and_the_iteration():
    text = instruction(**every_sentence(), design_system=APPLE_HIG)

    assert (
        text.index(design_system_section(APPLE_HIG))
        < text.index(REFERENCE_SENTENCE)
        < text.index(ITERATION_SENTENCE)
        < text.index(target_sentence(WORST_TARGET))
        < text.index(REDRAW_SENTENCE)
        < text.index(CHANGES_SENTENCE.format(name="Italian"))
    )
    assert text.endswith(RETRY_WITH_ANSWER_SENTENCE)


def test_an_unknown_design_system_in_the_context_is_refused():
    requirements = requirements_version()

    with pytest.raises(ValueError, match=r"^the context names an unknown design system$"):
        mockup_instruction(
            chosen(GUIDED_ID),
            requirements=requirements,
            language=requirements_language(requirements_view(requirements)),
            context={"design_system": {"name": "Material You"}},
        )


def test_the_real_generator_accepts_the_longest_instruction_with_the_design_system():
    port = DraftPort(iteration_payload())
    generator = ProposalGenerator(providers().hosted_model("design"), port, None)
    requirements = requirements_version()
    applied = directed_package(applied_package(), direction(axes=longest_axes()))
    dashboard = chosen(DASHBOARD_ID, applied)
    context = mockup_context(
        project_id=PROJECT_ID,
        purpose=DESIGN_ITERATION,
        command_id=UUID(int=1),
        version=version(applied),
        alternative=dashboard,
        requirements=requirements,
        current_mockup=applied.generated_mockup.mockup,
        owner_request="Mostra la sede di ritiro.",
        target=WORST_TARGET,
        assertions=(),
        previous_answer=iteration_payload(),
        rejection={"code": "X", "reasons": []},
        redraw={"screens": []},
        reference=REFERENCE,
        resources=RESOURCES,
        design_system=APPLE_HIG,
    )
    output = asyncio.run(
        generator.generate(
            task="design",
            context=context,
            output_type=GeneratedIterationDraft,
            instruction=mockup_instruction(
                dashboard,
                requirements=requirements,
                language=requirements_language(requirements_view(requirements)),
                context=context,
            ),
            max_output_tokens=48_000,
            retry_schema_errors=False,
        )
    )
    assert isinstance(output, GeneratedIterationDraft)
    [request] = port.requests
    sent = json.loads(request.input_payload_json)["context"]
    assert sent["design_system"] == design_system_view(APPLE_HIG)
    assert request.system_instruction.count(design_system_section(APPLE_HIG)) == 1
    assert request.system_instruction.endswith(RETRY_WITH_ANSWER_SENTENCE)
    assert PLAIN_BOUND < len(request.system_instruction) < MAXIMUM_SYSTEM_INSTRUCTION


def test_the_real_generator_sends_the_reference_and_the_resources_in_the_context():
    port = DraftPort(iteration_payload())
    generator = ProposalGenerator(providers().hosted_model("design"), port, None)
    requirements = requirements_version()
    applied = directed_package(applied_package(), direction(axes=longest_axes()))
    guided = chosen(GUIDED_ID, applied)
    context = mockup_context(
        project_id=PROJECT_ID,
        purpose=DESIGN_ITERATION,
        command_id=UUID(int=1),
        version=version(applied),
        alternative=guided,
        requirements=requirements,
        current_mockup=applied.generated_mockup.mockup,
        owner_request="Mostra la sede di ritiro.",
        assertions=(),
        previous_answer=iteration_payload(),
        rejection={"code": "X", "reasons": []},
        reference=REFERENCE,
        resources=RESOURCES,
    )
    output = asyncio.run(
        generator.generate(
            task="design",
            context=context,
            output_type=GeneratedIterationDraft,
            instruction=mockup_instruction(
                guided,
                requirements=requirements,
                language=requirements_language(requirements_view(requirements)),
                context=context,
            ),
            max_output_tokens=48_000,
            retry_schema_errors=False,
        )
    )
    assert isinstance(output, GeneratedIterationDraft)
    [request] = port.requests
    sent = json.loads(request.input_payload_json)["context"]
    assert sent["reference"] == REFERENCE
    assert sent["resources"] == RESOURCES
    assert request.system_instruction.count(REFERENCE_SENTENCE) == 1
    assert request.system_instruction.endswith(RETRY_WITH_ANSWER_SENTENCE)
    assert len(request.system_instruction) < MAXIMUM_SYSTEM_INSTRUCTION
