from __future__ import annotations

import json
import os
import re
from dataclasses import FrozenInstanceError, replace
from types import MappingProxyType

import pytest

from orchestwin.artifacts.visual_catalog import (
    HEADING_CASES,
    NEUTRAL_VISUAL_CHOICES,
    PALETTE_ROLES,
    HeadingCase,
    resolve_visual_tokens,
)
from orchestwin.artifacts.visual_color import colour_distance, is_hex_colour
from orchestwin.artifacts.visual_directions import (
    VISUAL_DIRECTIONS_VERSION,
    DirectionAxes,
    VisualDirection,
    visual_direction_from_snapshot,
    visual_directions_snapshot,
)
from orchestwin.artifacts.visual_fonts import BundledFamily
from orchestwin.artifacts.visual_language import _TOKEN_NAME, _plain_css_value
from orchestwin.models.design_systems import (
    APPLE_HIG,
    DESIGN_SYSTEM_ENV,
    DESIGN_SYSTEMS,
    MAX_DESIGN_SYSTEM_INSTRUCTION_LENGTH,
    NEUTRAL_ROLES,
    SYSTEM_ALTERNATIVE_CODE,
    SYSTEM_COLOUR_TOLERANCE,
    SYSTEM_DIRECTION_CANDIDATES,
    DesignSystem,
    SystemDirection,
    context_design_system,
    design_system,
    design_system_view,
    is_system_colour,
    system_direction,
)
from orchestwin.models.model_proposals import ModelDesignAdapter
from orchestwin.models.real_runtime import build_real_model_runtime

from .final_session_support import make_session
from .test_hosted_runtime import ClientFactory, gateway_fetch, write_manifest
from .test_hosted_support import ANTHROPIC_KEY_ENV, GATEWAY_KEY, GATEWAY_KEY_ENV, TEST_KEY
from .test_model_proposals import make_generator

TOKENS = {
    "--vl-size-display": "40px",
    "--vl-size-display-narrow": "34px",
    "--vl-size-title": "28px",
    "--vl-size-body": "17px",
    "--vl-size-label": "13px",
    "--vl-line-height": "1.47",
    "--vl-line-height-heading": "1.2",
    "--vl-space": "8px",
    "--vl-radius-control": "12px",
    "--vl-radius-panel": "20px",
    "--vl-shadow": "0 1px 2px rgba(0,0,0,.08), 0 8px 24px rgba(0,0,0,.08)",
    "--vl-section-gap": "24px",
    "--vl-heading-weight": "700",
    "--vl-heading-transform": "none",
    "--vl-heading-variant": "normal",
    "--vl-heading-tracking": "-0.01em",
    "--vl-content-width": "1100px",
}
COLOURS = {
    "blue": "#0088ff",
    "green": "#34c759",
    "indigo": "#6155f5",
    "orange": "#ff8d28",
    "pink": "#ff2d55",
    "purple": "#cb30e0",
    "red": "#ff383c",
    "teal": "#00c3d0",
    "yellow": "#ffcc00",
}
LIGHT = {
    "background": "#f2f2f7",
    "surface": "#ffffff",
    "surface_alt": "#e5e5ea",
    "border": "#c6c6c8",
    "text": "#000000",
    "text_muted": "#636366",
}
DARK = {
    "background": "#000000",
    "surface": "#1c1c1e",
    "surface_alt": "#2c2c2e",
    "border": "#38383a",
    "text": "#ffffff",
    "text_muted": "#98989f",
}
PALETTE_TEXT = (
    "A design system is active, context.design_system names it, and DES-003 follows it in its "
    "direction, its palette and its type pair; for DES-003 the system prevails over the paragraph "
    "above. The primary and the accent of DES-003 are two different colours of "
    "context.design_system.colours, each written exactly as it is listed there, blue included; "
    "its background, surface, surface_alt, border, text and text_muted are the neutral colours of "
    "the system, #f2f2f7, #ffffff, #e5e5ea, #c6c6c8, #000000 and #636366 in the light modes and "
    "#000000, #1c1c1e, #2c2c2e, #38383a, #ffffff and #98989f in the dark modes; its type_pair is "
    "Geist for the heading and Geist for the body. The Studio refuses any other primary, accent "
    "or type pair for DES-003. The other two alternatives follow only their own directions and "
    "the paragraph above, never the colours or the type pair of the system, and the primaries of "
    "the three alternatives differ clearly from each other."
)
DIRECTION = {
    "name": "Apple Human Interface Guidelines",
    "concept": (
        "The interface of a native Apple app: content first, grouped lists on a quiet background, "
        "glass bars and one prominent capsule action on every view. It suits people who expect "
        "the calm and familiar behaviour of the apps on their own phone."
    ),
    "rules": [
        "Every screen opens with a large title aligned to the leading edge, under a glass bar "
        "with a back chevron and at most two icon actions.",
        "Content sits in rounded grouped sections on the grouped background, with rows of at "
        "least 44 pixels and thin separators inset to the text.",
        "The one prominent action of a view is a filled capsule in the primary colour; colour "
        "appears only on interactive elements and on the current selection.",
    ],
    "axes": {
        "layout": "PANELS",
        "shape": "SOFT_FILL",
        "type": "EVEN",
        "colour": "ACCENT_ONLY",
        "density": "COMFORTABLE",
    },
    "typicality": 50,
    "candidates": 2,
    "vocabulary_version": VISUAL_DIRECTIONS_VERSION,
}
GLASS = (
    "Bars are glass: color-mix(in srgb, var(--vl-color-surface) 72%, transparent) with "
    "backdrop-filter: saturate(180%) blur(20px); no glass inside content."
)
TEXT_COLOURS = (
    "var(--vl-color-primary) only on interactive elements and selection, var(--vl-color-danger) "
    "only for destructive actions, var(--vl-color-text) text with var(--vl-color-text-muted) "
    "secondary lines, never colour alone."
)
ROUNDED = (
    "Corners are generously rounded everywhere: cards, pictures, fields and sheets use the panel "
    "radius, buttons and chips are capsules."
)
FLAT = "No gradients, textures or ornaments;"
KNOWN_TOKENS = set(resolve_visual_tokens(NEUTRAL_VISUAL_CHOICES)) | {
    name
    for values in visual_directions_snapshot()["tokens"].values()
    for tokens in values.values()
    for name in tokens
}


@pytest.fixture
def clean(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def legacy_manifest(root):
    generator, _ = make_generator(root, {})
    generator.configuration.token_file.write_text("proposal-secret-" + "t" * 40, encoding="ascii")
    proposal = root / "proposal.json"
    proposal.write_text(generator.configuration.model_dump_json(), encoding="utf-8")
    final = make_session(root / "final")
    path = root / "models.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "proposal_config_file": str(proposal),
                "final_evaluator_ready_file": str(final.ready_path),
            }
        ),
        encoding="utf-8",
    )
    return path


def test_the_module_names_the_variable_and_the_apple_system():
    assert DESIGN_SYSTEM_ENV == "ORCHESTWIN_DESIGN_SYSTEM"
    assert APPLE_HIG.identifier == "apple-hig"
    assert APPLE_HIG.name == "Apple Human Interface Guidelines"
    assert isinstance(APPLE_HIG, DesignSystem)
    assert isinstance(DESIGN_SYSTEMS, MappingProxyType)
    assert dict(DESIGN_SYSTEMS) == {"apple-hig": APPLE_HIG}
    assert design_system("apple-hig") is APPLE_HIG
    assert design_system(None) is None


@pytest.mark.parametrize("identifier", ["material-you", "", "Apple-HIG", " apple-hig", "apple"])
def test_an_unknown_design_system_is_refused(identifier):
    with pytest.raises(ValueError, match=r"^unknown design system, expected one of: apple-hig$"):
        design_system(identifier)


def test_the_instruction_is_short_english_and_names_colours_only_by_their_tokens():
    text = APPLE_HIG.instruction

    assert MAX_DESIGN_SYSTEM_INSTRUCTION_LENGTH == 2800
    assert len(text) <= MAX_DESIGN_SYSTEM_INSTRUCTION_LENGTH
    assert text.isascii()
    assert text == " ".join(text.split())
    assert text.startswith("This system prevails over the look described above")
    assert "Design system" not in text and APPLE_HIG.name not in text
    assert re.search(r"#[0-9A-Fa-f]{3,8}\b", text) is None
    assert re.search(r"\b(?:rgba?|hsla?)\(", text) is None
    assert "Token values" not in text and "Palette" not in text
    assert text.count(GLASS) == 1
    assert text.count(TEXT_COLOURS) == 1
    assert "a capsule filled with var(--vl-color-primary)" in text
    assert "its semibold label in var(--vl-color-on-primary)" in text
    assert text.count(ROUNDED) == 1
    assert text.count(FLAT) == 1
    assert f"capsules have a 999px radius and targets are at least 44x44px. {ROUNDED}" in text
    assert f"{ROUNDED} {FLAT}" in text
    assert text.endswith("Dark mode mirrors light, no shadows. Honour prefers-reduced-motion.")
    assert set(re.findall(r"var\((--vl-[a-z0-9-]+)\)", text)) <= KNOWN_TOKENS


def test_the_tokens_are_the_values_of_the_guidelines_and_plain_css_values():
    assert isinstance(APPLE_HIG.tokens, MappingProxyType)
    assert dict(APPLE_HIG.tokens) == TOKENS
    assert set(APPLE_HIG.tokens) <= KNOWN_TOKENS
    for name, value in APPLE_HIG.tokens.items():
        assert _TOKEN_NAME.fullmatch(name), name
        assert _plain_css_value(value), value


def test_the_headings_are_in_sentence_case_whatever_the_catalog_chose():
    transform, variant, _ = HEADING_CASES[HeadingCase.SENTENCE]
    uppercase = replace(NEUTRAL_VISUAL_CHOICES, heading_case=HeadingCase.UPPERCASE)
    catalog = resolve_visual_tokens(uppercase)

    assert (catalog["--vl-heading-transform"], catalog["--vl-heading-variant"]) != (
        transform,
        variant,
    )
    assert APPLE_HIG.tokens["--vl-heading-transform"] == transform == "none"
    assert APPLE_HIG.tokens["--vl-heading-variant"] == variant == "normal"
    assert {**catalog, **APPLE_HIG.tokens}["--vl-heading-transform"] == "none"


def test_the_colours_are_lowercase_hex_values_and_blue_comes_first():
    assert isinstance(APPLE_HIG.system_colours, MappingProxyType)
    assert dict(APPLE_HIG.system_colours) == COLOURS
    assert next(iter(APPLE_HIG.system_colours)) == "blue"
    assert all(is_hex_colour(value) for value in APPLE_HIG.system_colours.values())
    assert tuple(LIGHT) == NEUTRAL_ROLES
    assert set(NEUTRAL_ROLES) < set(PALETTE_ROLES)
    for neutral, expected in ((APPLE_HIG.neutral_light, LIGHT), (APPLE_HIG.neutral_dark, DARK)):
        assert isinstance(neutral, MappingProxyType)
        assert dict(neutral) == expected
        assert tuple(neutral) == NEUTRAL_ROLES
        assert all(is_hex_colour(value) for value in neutral.values())


def test_the_type_pair_is_a_bundled_family():
    assert APPLE_HIG.font_pair == ("Geist", "Geist")
    assert all(BundledFamily(family) is BundledFamily.GEIST for family in APPLE_HIG.font_pair)


def test_the_system_has_one_fixed_direction_for_the_third_alternative():
    direction = system_direction(APPLE_HIG)

    assert SYSTEM_ALTERNATIVE_CODE == "DES-003"
    assert SYSTEM_DIRECTION_CANDIDATES == 2
    assert isinstance(APPLE_HIG.direction, SystemDirection)
    assert isinstance(direction, VisualDirection)
    assert direction.to_snapshot() == DIRECTION
    assert direction.name == APPLE_HIG.name
    assert direction.axes == DirectionAxes(
        layout="PANELS", shape="SOFT_FILL", type="EVEN", colour="ACCENT_ONLY", density="COMFORTABLE"
    )
    assert direction == system_direction(design_system("apple-hig"))
    assert visual_direction_from_snapshot(direction.to_snapshot()) == direction
    for text in (direction.concept, *direction.rules):
        assert text.isascii() and text == " ".join(text.split())
        assert re.search(r"#[0-9A-Fa-f]{3,8}\b|var\(|px\b", text) is None
    with pytest.raises(FrozenInstanceError):
        APPLE_HIG.direction.typicality = 10


def test_the_view_names_the_system_its_alternative_its_colours_and_its_fonts():
    view = design_system_view(APPLE_HIG)

    assert view == {
        "name": "Apple Human Interface Guidelines",
        "alternative_code": "DES-003",
        "colours": COLOURS,
        "font_pair": {"heading": "Geist", "body": "Geist"},
    }
    assert "allowed_axes" not in view
    assert json.loads(json.dumps(view)) == view
    view["colours"]["blue"] = "#000000"
    view["font_pair"]["body"] = "Lora"
    assert APPLE_HIG.system_colours["blue"] == "#0088ff"
    assert design_system_view(APPLE_HIG)["font_pair"] == {"heading": "Geist", "body": "Geist"}


def test_the_context_finds_the_system_by_the_name_of_its_view():
    assert context_design_system({}) is None
    assert context_design_system({"design_system": None}) is None
    assert context_design_system({"design_system": design_system_view(APPLE_HIG)}) is APPLE_HIG
    assert context_design_system({"design_system": {"name": APPLE_HIG.name}}) is APPLE_HIG
    for view in ({"name": "Material You"}, {}, "apple-hig", [APPLE_HIG.name]):
        with pytest.raises(ValueError, match=r"^the context names an unknown design system$"):
            context_design_system({"design_system": view})


def test_the_palette_sentence_governs_only_the_alternative_of_the_system():
    text = APPLE_HIG.palette_text

    assert text == PALETTE_TEXT
    assert all(value in text for value in (*LIGHT.values(), *DARK.values()))
    assert text.count(SYSTEM_ALTERNATIVE_CODE) == 4
    assert "DES-001" not in text and "DES-002" not in text
    assert "The other two alternatives follow only their own directions" in text
    assert "the primaries of the three alternatives differ clearly" in text
    assert not hasattr(APPLE_HIG, "directions_text")
    assert not hasattr(APPLE_HIG, "direction_axes")


def test_a_system_colour_is_recognised_within_the_tolerance():
    assert SYSTEM_COLOUR_TOLERANCE == 0.02
    assert all(is_system_colour(APPLE_HIG, value) for value in COLOURS.values())
    assert colour_distance("#0089ff", "#0088ff") <= SYSTEM_COLOUR_TOLERANCE
    assert is_system_colour(APPLE_HIG, "#0089ff")
    for value in ("#0091ff", "#007aff", "#2f7d5b", "#ffffff", "#000000"):
        assert not is_system_colour(APPLE_HIG, value), value


def test_the_design_system_is_frozen_and_hashable():
    with pytest.raises(FrozenInstanceError):
        APPLE_HIG.name = "Material You"
    with pytest.raises(TypeError):
        APPLE_HIG.tokens["--vl-space"] = "4px"
    with pytest.raises(TypeError):
        APPLE_HIG.system_colours["blue"] = "#000000"
    assert hash(APPLE_HIG) == hash(design_system("apple-hig"))


def test_the_design_adapter_takes_the_design_system_only_by_name(tmp_path):
    generator, _ = make_generator(tmp_path, {})

    assert ModelDesignAdapter(generator).design_system is None
    assert ModelDesignAdapter(generator, design_system=APPLE_HIG).design_system is APPLE_HIG
    with pytest.raises(TypeError):
        ModelDesignAdapter(generator, APPLE_HIG)


def test_the_hosted_runtime_gives_the_design_system_to_the_design_adapter(clean, monkeypatch):
    monkeypatch.setenv(ANTHROPIC_KEY_ENV, TEST_KEY)
    (clean / ".env").write_text(f"{GATEWAY_KEY_ENV}={GATEWAY_KEY}\n", encoding="utf-8")
    path, _ = write_manifest(clean)

    def built(**options):
        return build_real_model_runtime(
            path,
            env_file=".env",
            anthropic_client_factory=ClientFactory(),
            openai_model_fetch=gateway_fetch,
            **options,
        )

    plain, system = built(), built(design_system=APPLE_HIG)

    assert plain.design.proposal_port.design_system is None
    assert system.design.proposal_port.design_system is APPLE_HIG
    assert system.design.proposal_port.generator is system.team.generator


def test_the_local_runtime_gives_the_design_system_to_the_design_adapter(clean):
    path = legacy_manifest(clean)

    plain = build_real_model_runtime(path)
    system = build_real_model_runtime(path, design_system=APPLE_HIG)

    assert type(system.design.proposal_port) is ModelDesignAdapter
    assert plain.design.proposal_port.design_system is None
    assert system.design.proposal_port.design_system is APPLE_HIG
