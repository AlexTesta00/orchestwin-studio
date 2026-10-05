from __future__ import annotations

import base64
import hashlib
from contextlib import suppress
from dataclasses import replace
from importlib.resources import files
from itertools import product
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.design_mockups import create_design_mockup_router
from orchestwin.artifacts import visual_fonts
from orchestwin.artifacts.generated_mockup_document import mockup_document
from orchestwin.artifacts.generated_mockup_styles import GeneratedMockupError, parse_style_sheet
from orchestwin.artifacts.mockup_html import generated_mockup_html, mockup_html
from orchestwin.artifacts.visual_catalog import (
    FONTS,
    NEUTRAL_VISUAL_CHOICES,
    DesignTone,
    FontFamily,
    resolve_visual_tokens,
)
from orchestwin.artifacts.visual_directions import HABITUAL_AXES, DirectionType
from orchestwin.artifacts.visual_fonts import (
    BODY_FONTS,
    BUNDLED_FONTS,
    FONT_DIRECTORY,
    FONT_FILE_HASHES,
    FONT_PACKAGE,
    HEADING_FONTS,
    MONO_FALLBACK,
    bundled_families,
    bundled_font_tokens,
    font_faces,
)
from orchestwin.artifacts.visual_language import _plain_css_value, create_visual_language
from orchestwin.artifacts.why_mockups import mockup_document_hashes
from orchestwin.models.generated_mockup_instructions import (
    CONSTANT_INSTRUCTION,
    DIRECTED_TOKENS_SENTENCE,
    DIRECTION_AXIS_SENTENCES,
)
from src.test.python.api.test_design_review_pins import PATH, client, scenario_run
from src.test.python.models import test_generated_mockup_support as mockups

from . import design_fixtures
from .test_design_package_extension import fixture_package
from .test_generated_mockup_document import assert_safe, style_of
from .test_visual_directions import directed_package, direction

EXPECTED_FONTS = {
    "Geist": ("geist", (400, 600, 800)),
    "Geist Mono": ("geist-mono", (400, 600)),
    "IBM Plex Mono": ("ibm-plex-mono", (400, 600)),
    "Libre Franklin": ("libre-franklin", (400, 700, 900)),
    "Lexend Zetta": ("lexend-zetta", (500, 800)),
}
GEIST_MONO = '"Geist Mono", ui-monospace, Consolas, monospace'
IBM_PLEX_MONO = '"IBM Plex Mono", ui-monospace, Consolas, monospace'
MIXED_TOKENS = {
    "--vl-font-mono": GEIST_MONO,
    "--vl-font-body": '"Libre Franklin", Arial, Helvetica, sans-serif',
    "--vl-font-heading": '"Geist", "Century Gothic", Avenir, sans-serif',
    "--vl-color-text": "#1b1f24",
}
MAXIMUM_FONT_DIRECTORY = 200_000
MAXIMUM_FACES = 150_000
TONES = (DesignTone.ESSENTIAL, DesignTone.PLAYFUL, DesignTone.TECHNICAL)


def encoded(family: str, weight: int) -> str:
    name = f"{EXPECTED_FONTS[family][0]}-{weight}.woff2"
    content = (files(FONT_PACKAGE) / FONT_DIRECTORY / name).read_bytes()
    return base64.b64encode(content).decode("ascii")


def face(family: str, weight: int) -> str:
    return (
        f'@font-face{{font-family:"{family}";font-style:normal;font-weight:{weight};'
        f"font-display:swap;src:url(data:font/woff2;base64,{encoded(family, weight)}) "
        'format("woff2")}'
    )


def family_choices():
    for tone, heading, body in product(TONES, FontFamily, FontFamily):
        with suppress(ValueError):
            yield replace(
                NEUTRAL_VISUAL_CHOICES, tone=tone, heading_family=heading, body_family=body
            )


def selected_language(package):
    return next(
        item.visual_language
        for item in package.alternatives
        if item.id == package.owner_selected_alternative_id
    )


def test_the_bundled_fonts_are_the_five_families_and_weights_of_the_contract() -> None:
    assert {family: (font.package, font.weights) for family, font in BUNDLED_FONTS.items()} == (
        EXPECTED_FONTS
    )
    assert list(BUNDLED_FONTS) == list(EXPECTED_FONTS)
    assert all(font.family == family for family, font in BUNDLED_FONTS.items())
    assert {font.licence for font in BUNDLED_FONTS.values()} == {"OFL-1.1"}
    assert dict(HEADING_FONTS) == {
        FontFamily.GEOMETRIC_SANS: "Geist",
        FontFamily.GROTESQUE_SANS: "Libre Franklin",
        FontFamily.DISPLAY_HEAVY: "Libre Franklin",
        FontFamily.WIDE_SANS: "Lexend Zetta",
    }
    assert dict(BODY_FONTS) == {
        FontFamily.GEOMETRIC_SANS: "Geist",
        FontFamily.GROTESQUE_SANS: "Libre Franklin",
    }
    assert all(FONTS[family].body_safe for family in BODY_FONTS)
    assert set(HEADING_FONTS.values()) | {"Geist Mono", "IBM Plex Mono"} == set(BUNDLED_FONTS)
    assert MONO_FALLBACK == "ui-monospace, Consolas, monospace"
    for table in (BUNDLED_FONTS, HEADING_FONTS, BODY_FONTS, FONT_FILE_HASHES):
        with pytest.raises(TypeError):
            table["Geist"] = "changed"


def test_every_font_file_is_found_through_the_package_with_its_hash_and_its_licence() -> None:
    directory = files(FONT_PACKAGE) / FONT_DIRECTORY
    names = {name for font in BUNDLED_FONTS.values() for name in font.file_names}
    licences = {font.licence_file for font in BUNDLED_FONTS.values()}
    sizes = []

    assert (
        Path(str(directory)).resolve() == (Path(visual_fonts.__file__).parent / "fonts").resolve()
    )
    assert set(FONT_FILE_HASHES) == names
    assert (len(names), len(licences)) == (12, 5)
    assert {item.name for item in directory.iterdir()} == names | licences
    for name in sorted(names):
        content = (directory / name).read_bytes()
        assert content.startswith(b"wOF2"), name
        assert hashlib.sha256(content).hexdigest() == FONT_FILE_HASHES[name], name
        sizes.append(len(content))
    for name in sorted(licences):
        text = (directory / name).read_text(encoding="utf-8")
        assert "SIL Open Font License, Version 1.1" in text, name
        sizes.append(len(text.encode("utf-8")))
    assert sum(sizes) < MAXIMUM_FONT_DIRECTORY


def test_the_bundled_tokens_prepend_the_family_to_the_catalog_stack() -> None:
    headings, bodies = set(), set()
    for choices in family_choices():
        catalog = resolve_visual_tokens(choices)
        heading = HEADING_FONTS.get(choices.heading_family)
        body = BODY_FONTS.get(choices.body_family)
        expected = {}
        if heading is not None:
            expected["--vl-font-heading"] = f'"{heading}", {FONTS[choices.heading_family].stack}'
        if body is not None:
            expected["--vl-font-body"] = f'"{body}", {FONTS[choices.body_family].stack}'
        expected["--vl-font-mono"] = GEIST_MONO if "Geist" in (heading, body) else IBM_PLEX_MONO

        tokens = bundled_font_tokens(choices, catalog)

        assert tokens == expected, (choices.heading_family, choices.body_family)
        assert all(_plain_css_value(value) for value in tokens.values())
        assert bundled_families(catalog) == ()
        assert font_faces(catalog) == ""
        headings.add(choices.heading_family)
        bodies.add(choices.body_family)
    assert headings == set(FontFamily)
    assert bodies == {family for family in FontFamily if FONTS[family].body_safe} | {
        FontFamily.MONOSPACE
    }


def test_the_bundled_tokens_need_the_catalog_stack_they_extend() -> None:
    geometric = replace(NEUTRAL_VISUAL_CHOICES, heading_family=FontFamily.GEOMETRIC_SANS)

    assert bundled_font_tokens(NEUTRAL_VISUAL_CHOICES, {}) == {"--vl-font-mono": IBM_PLEX_MONO}
    with pytest.raises(ValueError, match="--vl-font-heading"):
        bundled_font_tokens(geometric, {"--vl-font-body": "serif"})


def test_the_bundled_families_are_read_from_the_start_of_the_font_tokens() -> None:
    assert bundled_families(MIXED_TOKENS) == ("Geist", "Geist Mono", "Libre Franklin")
    assert bundled_families(dict(reversed(MIXED_TOKENS.items()))) == bundled_families(MIXED_TOKENS)
    assert bundled_families(
        {
            "--vl-font-heading": '"Lexend Zetta", Verdana, sans-serif',
            "--vl-font-body": '"Lexend Zetta", Verdana, sans-serif',
            "--vl-font-mono": IBM_PLEX_MONO,
        }
    ) == ("IBM Plex Mono", "Lexend Zetta")
    for value in ('Arial, "Geist"', "Geist, sans-serif", '"Geist Sans", serif', '"geist", serif'):
        assert bundled_families({"--vl-font-heading": value}) == (), value
    assert bundled_families({"--vl-size-body": '"Geist"', "--vl-font-other": '"Geist"'}) == ()
    assert bundled_families({}) == ()


def test_the_faces_embed_every_weight_of_every_named_family_in_a_stable_order() -> None:
    expected = "".join(
        face(family, weight)
        for family, weight in (
            ("Geist", 400),
            ("Geist", 600),
            ("Geist", 800),
            ("Geist Mono", 400),
            ("Geist Mono", 600),
            ("Libre Franklin", 400),
            ("Libre Franklin", 700),
            ("Libre Franklin", 900),
        )
    )

    assert font_faces(MIXED_TOKENS) == expected
    assert font_faces(dict(reversed(MIXED_TOKENS.items()))) == expected
    assert font_faces({"--vl-font-mono": IBM_PLEX_MONO}) == (
        face("IBM Plex Mono", 400) + face("IBM Plex Mono", 600)
    )
    assert font_faces({}) == ""


def test_every_font_file_is_read_once() -> None:
    visual_fonts._font_data.cache_clear()
    try:
        font_faces(MIXED_TOKENS)
        first = visual_fonts._font_data.cache_info()
        font_faces(MIXED_TOKENS)
        second = visual_fonts._font_data.cache_info()
    finally:
        visual_fonts._font_data.cache_clear()

    assert (first.misses, first.currsize) == (8, 8)
    assert second.misses == first.misses
    assert second.hits == first.hits + 8


def test_a_font_file_that_does_not_match_its_hash_is_refused(monkeypatch) -> None:
    visual_fonts._font_data.cache_clear()
    changed = MappingProxyType({**FONT_FILE_HASHES, "lexend-zetta-500.woff2": "0" * 64})
    monkeypatch.setattr(visual_fonts, "FONT_FILE_HASHES", changed)
    try:
        with pytest.raises(RuntimeError, match=r"lexend-zetta-500\.woff2"):
            font_faces({"--vl-font-heading": '"Lexend Zetta", Verdana, sans-serif'})
        assert font_faces({"--vl-font-mono": GEIST_MONO}).count("@font-face{") == 2
    finally:
        visual_fonts._font_data.cache_clear()


def test_every_combination_of_families_adds_a_bounded_style_to_the_document() -> None:
    sizes = {}
    for heading, body in product((*HEADING_FONTS, None), (*BODY_FONTS, None)):
        choices = replace(
            NEUTRAL_VISUAL_CHOICES,
            heading_family=heading or FontFamily.SYSTEM_UI,
            body_family=body or FontFamily.SYSTEM_UI,
        )
        tokens = {**resolve_visual_tokens(choices)}
        tokens.update(bundled_font_tokens(choices, tokens))
        sizes[bundled_families(tokens)] = len(font_faces(tokens))

    assert set(sizes) == {
        ("IBM Plex Mono",),
        ("Geist", "Geist Mono"),
        ("IBM Plex Mono", "Libre Franklin"),
        ("IBM Plex Mono", "Lexend Zetta"),
        ("Geist", "Geist Mono", "Libre Franklin"),
        ("Geist", "Geist Mono", "Lexend Zetta"),
        ("IBM Plex Mono", "Libre Franklin", "Lexend Zetta"),
    }
    assert all(0 < size < MAXIMUM_FACES for size in sizes.values())


def test_the_directed_instruction_names_the_monospace_token_that_the_validator_accepts() -> None:
    caps = DIRECTION_AXIS_SENTENCES["type"][DirectionType.CAPS_LABELS]
    labelled = create_visual_language(
        choices=NEUTRAL_VISUAL_CHOICES,
        product_name="Catalog",
        rationale="Labels and figures",
        direction=direction(axes=replace(HABITUAL_AXES, type=DirectionType.CAPS_LABELS)),
    )
    sheet = "td{font-family:var(--vl-font-mono);font-variant-numeric:tabular-nums}"

    assert "are set in var(--vl-font-mono) with tabular figures" in caps
    assert "monospace" not in caps
    assert (
        "--vl-line-height-heading, --vl-font-mono and, when the direction needs them,"
        in DIRECTED_TOKENS_SENTENCE
    )
    assert "--vl-font-mono" not in CONSTANT_INSTRUCTION
    assert labelled.token_values["--vl-font-mono"] == IBM_PLEX_MONO
    assert parse_style_sheet(sheet, token_names=labelled.token_values).rules
    with pytest.raises(GeneratedMockupError) as error:
        parse_style_sheet(sheet, token_names=resolve_visual_tokens(NEUTRAL_VISUAL_CHOICES))
    assert error.value.code == "STYLES_CUSTOM_PROPERTY"


def test_the_dossier_file_and_the_why_hashes_of_a_directed_design_carry_its_fonts() -> None:
    plain = fixture_package()
    directed = directed_package(plain)
    language = selected_language(directed)
    mockup = directed.generated_mockup.mockup
    faces = font_faces(language.token_values)

    html = mockup_html(design_fixtures.design_version(package=directed), language="it")
    hashes = mockup_document_hashes(directed)

    assert faces.count("@font-face{") >= 2
    assert html == generated_mockup_html(directed, language="it")
    assert html == mockup_document(mockup, tokens=language.token_values, language="it")
    assert style_of(html).startswith(faces + ":root{")
    assert_safe(html)
    assert "@font-face" not in mockup_html(design_fixtures.design_version(package=plain))
    assert set(hashes) == {screen.code for screen in mockup.screens}
    for screen in mockup.screens:
        document = mockup_document(
            mockup, tokens=language.token_values, language="it", entry_screen=screen.code
        )
        assert hashes[screen.code] == hashlib.sha256(document.encode("utf-8")).hexdigest()
        assert hashes[screen.code] != mockup_document_hashes(plain)[screen.code]


def web_document(package) -> str:
    application = FastAPI()
    application.state.application_runtime = mockups.runtime(
        versions=mockups.DesignVersions(package)
    )
    application.include_router(create_design_mockup_router(), prefix="/api/v1")
    application.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(
        id=mockups.OWNER_ID
    )
    response = TestClient(application).get(
        f"/api/v1/projects/{mockups.PROJECT_ID}/design/mockups/document",
        params={"alternative_id": str(mockups.GUIDED_ID), "source": "applied"},
    )
    assert response.status_code == 200, response.json()
    return response.json()["html"]


def test_the_web_document_route_serves_the_fonts_of_a_directed_design() -> None:
    plain = mockups.applied_package()
    directed = directed_package(plain)
    faces = font_faces(selected_language(directed).token_values)

    html = web_document(directed)

    assert faces
    assert style_of(html).startswith(faces + ":root{")
    assert_safe(html)
    assert "@font-face" not in web_document(plain)


def test_the_review_document_route_serves_the_fonts_of_a_directed_design(monkeypatch) -> None:
    version = design_fixtures.design_version(package=directed_package(fixture_package()))
    faces = font_faces(selected_language(version.package).token_values)
    http = client(monkeypatch, runs=(scenario_run(version),), versions=(version,))

    response = http.get(f"{PATH}/document")

    assert response.status_code == 200
    html = response.json()["html"]
    assert faces
    assert style_of(html).startswith(faces + ":root{")
    assert html.count('class="ot-pin"') >= 1
    assert_safe(html)
