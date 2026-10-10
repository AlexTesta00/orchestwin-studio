from __future__ import annotations

import asyncio
import json
import math
from uuid import uuid4

import pytest
from pydantic import ValidationError

from orchestwin.artifacts.visual_catalog import (
    MODES,
    PALETTE_ROLES,
    ColorMode,
    resolve_visual_tokens,
)
from orchestwin.artifacts.visual_color import (
    contrast_ratio,
    hex_to_oklab,
    hue_difference,
    oklch_to_hex,
)
from orchestwin.artifacts.visual_directions import direction_tokens
from orchestwin.artifacts.visual_fonts import BundledFamily, bundled_font_tokens
from orchestwin.models import design_drafts
from orchestwin.models.design_directions import DIRECTIONS_ROLE, DIRECTIONS_SELECTED
from orchestwin.models.design_drafts import (
    FONT_CHARACTERS,
    HOSTED_DESIGN_CONTRACT_VERSION,
    DesignDraft,
    HostedAlternativeDraft,
    HostedDesignDraft,
    HostedVisualLanguageDraft,
    PaletteDraft,
    TypePairDraft,
    design_context,
    font_design_context,
    palette_adjustments,
)
from orchestwin.models.model_proposals import (
    HOSTED_PALETTE_INSTRUCTION,
    PALETTE_ADJUSTED,
    PALETTE_ROLE,
    ModelDesignAdapter,
    design_instruction,
    hosted_design_instruction,
)
from orchestwin.models.planning_schema import constrain_planning_schema
from orchestwin.models.proposal_generation import DESIGN_CONTRACT_VERSIONS, ProposalGenerationError

from .test_design_directions import (
    DIRECTIONS_ANSWER,
    ScriptedPort,
    alternatives_answer,
    hosted_context,
    hosted_generator,
    selected_directions,
    sent_context,
)
from .test_design_drafts import bind, draft, hosted, palette_of, visual
from .test_fake_design import proposal_request
from .test_proposal_evidence import Command, MemoryEvidence

FONT_LINES = {
    "Source Sans 3": (
        "humanist sans, friendly and legible, for long interfaces and public services."
    ),
    "Geist": "geometric sans, neutral and technical, for tools and dashboards.",
    "Libre Franklin": "grotesque sans, American newspaper voice, sturdy at every size.",
    "Nunito": "soft rounded sans, warm and playful, for everyday and family products.",
    "Archivo Narrow": "condensed sans, compact and urgent, for timetables and signage.",
    "Lexend Zetta": "very wide sans, for short headings only, loud and modern.",
    "Source Serif 4": "transitional serif, calm and bookish, pairs with Source Sans 3.",
    "Lora": "contemporary serif with calligraphic roots, elegant on screen.",
    "Playfair Display": "high contrast display serif, fashion and editorial, headings only.",
    "Zilla Slab": "slab serif, solid and friendly, for titles and figures.",
    "Bricolage Grotesque": "expressive heavy grotesque, for display headings with personality.",
    "Caveat": "handwritten script, for the product name and one title at most.",
    "Geist Mono": "monospace, for figures and codes; never for the body.",
    "IBM Plex Mono": "monospace, for figures and codes; never for the body.",
}


@pytest.fixture
def unrestricted(monkeypatch):
    monkeypatch.setattr(design_drafts, "visual_exploration", lambda project_id: {})


def oklch(colour: str) -> tuple[float, float, float]:
    lightness, a, b = hex_to_oklab(colour)
    return lightness, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def dark(mode: str) -> bool:
    return MODES[ColorMode(mode)].dark


def with_palette(design: HostedDesignDraft, index: int, **colours: str) -> HostedDesignDraft:
    payload = design.model_dump(mode="json")
    payload["alternatives"][index]["visual"]["palette"].update(colours)
    return HostedDesignDraft.model_validate(payload)


def answer(request, chosen, index=None, **colours: str) -> dict:
    payload = alternatives_answer(request, chosen)
    if index is not None:
        payload["alternatives"][index]["visual"]["palette"].update(colours)
    return payload


def proposed(store, generator, request):
    return asyncio.run(
        Command(store, lambda: ModelDesignAdapter(generator).propose(request)).run(
            owner_user_id=uuid4(), project_id=request.project_id
        )
    )


def test_the_palette_and_the_type_pair_drafts_follow_the_contract():
    schema = PaletteDraft.model_json_schema()
    valid = palette_of(visual().model_dump(mode="json"))

    assert tuple(PaletteDraft.model_fields) == PALETTE_ROLES
    assert schema["required"] == list(PALETTE_ROLES)
    assert {item["pattern"] for item in schema["properties"].values()} == {"^#[0-9a-f]{6}$"}
    assert PaletteDraft.model_validate(valid).model_dump() == valid
    for invalid in (
        {**valid, "primary": "#2F7D5B"},
        {**valid, "primary": "#2f7d5"},
        {**valid, "glow": "#ffffff"},
        {key: value for key, value in valid.items() if key != "border"},
    ):
        with pytest.raises(ValidationError):
            PaletteDraft.model_validate(invalid)
    pair = TypePairDraft.model_json_schema()
    assert pair["required"] == ["heading", "body"]
    assert pair["$defs"]["BundledFamily"]["enum"] == [family.value for family in BundledFamily]
    assert TypePairDraft(heading="Lora", body="Source Sans 3").heading is BundledFamily.LORA
    with pytest.raises(ValidationError):
        TypePairDraft(heading="Comic Sans", body="Lora")
    with pytest.raises(ValidationError):
        TypePairDraft(heading="Lora", body="Lora", weight="700")


def test_the_hosted_alternatives_require_both_and_keep_the_names_that_the_planning_binds():
    request = proposal_request()
    schema = HostedDesignDraft.model_json_schema()
    definitions = schema["$defs"]
    local = json.dumps(DesignDraft.model_json_schema())

    assert (HostedAlternativeDraft.__name__, HostedVisualLanguageDraft.__name__) == (
        "AlternativeDraft",
        "VisualLanguageDraft",
    )
    assert {"PaletteDraft", "TypePairDraft", "BundledFamily"} <= set(definitions)
    assert definitions["AlternativeDraft"]["properties"]["visual"] == {
        "$ref": "#/$defs/VisualLanguageDraft"
    }
    assert {"palette", "type_pair"} <= set(definitions["VisualLanguageDraft"]["required"])
    assert "palette" not in local and "type_pair" not in local and "BundledFamily" not in local
    constrain_planning_schema(schema, font_design_context(hosted_context(request)), "design")
    branches = schema["properties"]["alternatives"]["prefixItems"]
    assert [item["allOf"][0] for item in branches] == [{"$ref": "#/$defs/AlternativeDraft"}] * 2
    fits = definitions["VisualLanguageDraft"]["properties"]["twin_fit"]["prefixItems"]
    assert len(fits) == len(request.user_modeling.user_twins)
    payload = hosted(draft(design_context(request)[0])).model_dump(mode="json")
    del payload["alternatives"][0]["visual"]["type_pair"]
    with pytest.raises(ValidationError, match="type_pair"):
        HostedDesignDraft.model_validate(payload)


def test_the_contract_of_the_alternatives_moves_to_one_hundred_twelve():
    versions = list(DESIGN_CONTRACT_VERSIONS.values())

    assert DESIGN_CONTRACT_VERSIONS["DESIGN_ALTERNATIVES_HOSTED"] == 112
    assert HOSTED_DESIGN_CONTRACT_VERSION == 112
    assert len(set(versions)) == len(versions)


def test_the_context_gives_each_bundled_family_the_line_of_its_character():
    context = font_design_context({"purpose": "DESIGN_ALTERNATIVES_HOSTED"})

    assert set(FONT_CHARACTERS) == set(BundledFamily)
    assert context == {"purpose": "DESIGN_ALTERNATIVES_HOSTED", "fonts": FONT_LINES}


def test_the_paragraph_names_the_roles_the_mode_the_correction_and_the_fonts():
    request = proposal_request()
    context = font_design_context(hosted_context(request))
    instruction = hosted_design_instruction(context)

    for role in PALETTE_ROLES:
        assert role in HOSTED_PALETTE_INSTRUCTION, role
    for words in (
        "fifteen roles",
        "never the usual blue",
        "follows color_mode",
        "the Studio moves only its lightness and keeps its hue",
        "context.fonts",
        "where the direction asks for it",
    ):
        assert words in HOSTED_PALETTE_INSTRUCTION, words
    assert instruction.endswith(f" {HOSTED_PALETTE_INSTRUCTION}")
    assert instruction.count(HOSTED_PALETTE_INSTRUCTION) == 1
    assert HOSTED_PALETTE_INSTRUCTION not in design_instruction("T1/T2", context["language"])


def test_binding_moves_a_failing_colour_keeps_its_hue_and_reports_the_role(unrestricted):
    request = proposal_request()
    context, _ = design_context(request)
    base = hosted(draft(context))
    light_green = oklch_to_hex(0.82, 0.14, 140)
    written = with_palette(base, 0, primary=light_green)

    package = bind(request, written)

    language = package.alternatives[0].visual_language
    roles = language.palette_roles
    before, after = oklch(light_green), oklch(roles["primary"])
    assert palette_adjustments(written, package) == {"DES-001": ("primary",)}
    assert palette_adjustments(base, bind(request, base)) == {}
    assert after[0] < before[0]
    assert hue_difference(before[2], after[2]) <= 1.0
    assert contrast_ratio(roles["on_primary"], roles["primary"]) >= 4.5
    assert contrast_ratio(roles["primary"], roles["background"]) >= 3.0
    assert language.token_values["--vl-color-primary"] == roles["primary"]
    assert {key: value for key, value in roles.items() if key != "primary"} == {
        key: value
        for key, value in written.alternatives[0].visual.palette.model_dump().items()
        if key != "primary"
    }


def test_binding_refuses_a_palette_against_the_colour_mode(unrestricted):
    request = proposal_request()
    context, _ = design_context(request)
    base = hosted(draft(context))
    assert base.alternatives[1].visual.color_mode is ColorMode.DARK

    with pytest.raises(ValueError, match=r"^palette does not match the colour mode$"):
        bind(request, with_palette(base, 1, background="#f7f7f2"))


def test_binding_refuses_primaries_that_are_too_close(unrestricted):
    request = proposal_request()
    context, _ = design_context(request)
    base = hosted(draft(context))
    _, chroma, hue = oklch(base.alternatives[0].visual.palette.primary)
    close = oklch_to_hex(0.75, chroma, hue + 10)

    with pytest.raises(ValueError, match="clearly different primary colours"):
        bind(request, with_palette(base, 1, primary=close))
    assert bind(request, base).alternatives[1].visual_language.palette_roles["primary"] == (
        base.alternatives[1].visual.palette.primary
    )


def test_the_local_draft_binds_the_catalog_palette_and_tokens_of_today(unrestricted):
    request = proposal_request()
    context, _ = design_context(request)
    local = draft(context)

    package = bind(request, local)

    assert palette_adjustments(local, package) == {}
    for item in package.alternatives:
        language = item.visual_language
        assert language.token_values == resolve_visual_tokens(language.choices)
        assert language.palette_roles == palette_of(language.choices.to_snapshot())


def test_the_hosted_route_sends_the_fonts_asks_for_contract_112_and_binds_the_palettes():
    request = proposal_request()
    chosen = selected_directions(request)
    payload = answer(request, chosen)
    port = ScriptedPort(DIRECTIONS_ANSWER, payload)

    result = asyncio.run(ModelDesignAdapter(hosted_generator(port)).propose(request))

    directions, design = port.requests
    schema = json.loads(design.output_schema.canonical_schema_json)
    assert directions.prompt_version_ref == "proposal-design-v110"
    assert (
        design.prompt_version_ref,
        design.output_schema.schema_id,
        design.output_schema.version_number,
    ) == ("proposal-design-v112", "proposal-design-v112", 112)
    assert "fonts" not in sent_context(directions)
    assert sent_context(design)["fonts"] == FONT_LINES
    assert design.system_instruction.endswith(HOSTED_PALETTE_INSTRUCTION)
    assert {"palette", "type_pair"} <= set(schema["$defs"]["VisualLanguageDraft"]["required"])
    for item, drafted in zip(result.package.alternatives, payload["alternatives"], strict=True):
        language = item.visual_language
        catalog = resolve_visual_tokens(language.choices)
        pair = (drafted["visual"]["type_pair"]["heading"], drafted["visual"]["type_pair"]["body"])
        assert language.palette_roles == drafted["visual"]["palette"]
        assert language.direction == chosen[item.code]
        assert language.token_values == {
            **catalog,
            **direction_tokens(chosen[item.code], catalog),
            **bundled_font_tokens(language.choices, catalog, pair),
        }


def test_an_adjusted_palette_is_recorded_next_to_the_selected_directions():
    request = proposal_request()
    chosen = selected_directions(request)
    mode = answer(request, chosen)["alternatives"][0]["visual"]["color_mode"]
    muted = "#3a3d44" if dark(mode) else "#c8c8c8"
    adjusted = hosted_generator(
        ScriptedPort(DIRECTIONS_ANSWER, answer(request, chosen, 0, text_muted=muted))
    )
    plain = hosted_generator(ScriptedPort(DIRECTIONS_ANSWER, answer(request, chosen)))
    store, untouched = MemoryEvidence(), MemoryEvidence()

    result = proposed(store, adjusted, request)
    proposed(untouched, plain, request)

    directions, design = store.requests
    events = store.events[design]
    selected = {
        "role": DIRECTIONS_ROLE,
        "generation_id": str(directions),
        "request_hash": store.requests[directions][0].content_hash,
        "code": DIRECTIONS_SELECTED,
    }
    assert [kind for kind, _, _ in events] == [
        "PROVIDER_RESULT",
        "ADAPTER_ACCEPTED",
        "APPLICATION_RESULT",
    ]
    assert events[1][1]["related_generations"] == [
        selected,
        {
            "role": PALETTE_ROLE,
            "generation_id": str(design),
            "request_hash": store.requests[design][0].content_hash,
            "code": PALETTE_ADJUSTED,
            "palette_roles": {"DES-001": ["text_muted"]},
        },
    ]
    assert result.package.alternatives[0].visual_language.palette_roles["text_muted"] != muted
    _, kept = untouched.requests
    related = untouched.events[kept][1][1]["related_generations"]
    assert [(item["role"], item["code"]) for item in related] == [
        (DIRECTIONS_ROLE, DIRECTIONS_SELECTED)
    ]


def test_a_palette_against_the_colour_mode_makes_the_proposal_invalid_with_its_reason():
    request = proposal_request()
    chosen = selected_directions(request)
    mode = answer(request, chosen)["alternatives"][1]["visual"]["color_mode"]
    background = "#f7f7f2" if dark(mode) else "#101418"
    generator = hosted_generator(
        ScriptedPort(DIRECTIONS_ANSWER, answer(request, chosen, 1, background=background))
    )
    store = MemoryEvidence()

    with pytest.raises(ProposalGenerationError, match="INVALID_PROVIDER_OUTPUT"):
        proposed(store, generator, request)

    _, design = store.requests
    assert [(kind, payload) for kind, payload, _ in store.events[design]][1:] == [
        (
            "ADAPTER_REJECTED",
            {"code": "INVALID_PROVIDER_OUTPUT", "reason": "palette does not match the colour mode"},
        ),
        ("APPLICATION_RESULT", {"status": "FAILED", "code": "INVALID_PROVIDER_OUTPUT"}),
    ]
