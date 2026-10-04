from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import replace

import pytest

from orchestwin.api.design import DesignPackagePayload
from orchestwin.artifacts.design_serialization import design_package_from_snapshot
from orchestwin.artifacts.visual_catalog import (
    FONTS,
    NEUTRAL_VISUAL_CHOICES,
    PALETTE_ROLES,
    VISUAL_CATALOG_CONTENT_HASH,
    VISUAL_CATALOG_VERSION,
    VISUAL_DIMENSION_NAMES,
    VISUAL_DIMENSIONS,
    ColorMode,
    DesignTone,
    FontFamily,
    HueFamily,
    LayoutArchetype,
    NavigationPattern,
    VisualChoices,
    resolve_palette,
    resolve_visual_tokens,
)
from orchestwin.artifacts.visual_directions import DirectionLayout, direction_tokens
from orchestwin.artifacts.visual_fonts import bundled_families, bundled_font_tokens
from orchestwin.artifacts.visual_language import (
    MAX_PRODUCT_NAME_LENGTH,
    MAX_TOKEN_VALUE_LENGTH,
    VisualLanguage,
    create_visual_language,
    visual_language_from_snapshot,
)

from . import design_fixtures
from .test_visual_directions import directed_language, directed_package, direction

STORED_LANGUAGE_HASH = "026e86df07466c1186c4a46bd2c95d133d928a381ef5dd53927a722cf82dc219"
STORED_NEUTRAL_LANGUAGE_HASH = "56267ebe50ae8713d8253ec3e6f7ca3145ae4fa333b37641711a1dc586c3699a"

CATALOG_BASES = (
    NEUTRAL_VISUAL_CHOICES,
    replace(
        NEUTRAL_VISUAL_CHOICES,
        archetype=LayoutArchetype.LIST_DETAIL,
        navigation=NavigationPattern.SIDE_RAIL,
    ),
    replace(NEUTRAL_VISUAL_CHOICES, color_mode=ColorMode.DARK),
    replace(NEUTRAL_VISUAL_CHOICES, tone=DesignTone.PLAYFUL),
    replace(NEUTRAL_VISUAL_CHOICES, tone=DesignTone.TECHNICAL),
)
UNREADABLE_BODY_FAMILIES = (FontFamily.MODERN_SERIF, FontFamily.DISPLAY_HEAVY, FontFamily.SCRIPT)


def catalog_variants() -> list[VisualChoices]:
    variants: list[VisualChoices] = []
    for base in CATALOG_BASES:
        for name, values in VISUAL_DIMENSIONS.items():
            for value in values:
                with suppress(ValueError):
                    variants.append(replace(base, **{name: value}))
    return variants


def with_token(name: str, value: str) -> VisualLanguage:
    return replace(design_fixtures.visual_language(), tokens=((name, value),))


def test_visual_language_resolves_palette_and_tokens_from_the_catalog():
    language = design_fixtures.visual_language()
    choices = language.choices
    assert language.catalog_version == VISUAL_CATALOG_VERSION
    assert language.catalog_content_hash == VISUAL_CATALOG_CONTENT_HASH
    assert language.palette_roles == resolve_palette(
        choices.hue_family,
        choices.color_scheme,
        choices.color_mode,
        choices.saturation,
        choices.surface_tone,
    )
    assert tuple(language.palette_roles) == PALETTE_ROLES
    assert language.token_values["--vl-color-primary"] == language.palette_roles["primary"]
    assert language.product_name == "Reservation desk"
    assert len(language.content_hash) == 64


def test_visual_language_normalizes_text_and_rejects_bad_values():
    language = create_visual_language(
        choices=design_fixtures.visual_language().choices,
        product_name="  Reservation   desk ",
        rationale=" Calm\n and clear ",
    )
    assert language.product_name == "Reservation desk"
    assert language.rationale == "Calm and clear"
    with pytest.raises(ValueError, match="visual product name exceeds"):
        create_visual_language(
            choices=language.choices,
            product_name="x" * (MAX_PRODUCT_NAME_LENGTH + 1),
            rationale="Fine",
        )
    with pytest.raises(ValueError, match="must be normalized"):
        replace(language, product_name=" Reservation desk")
    with pytest.raises(ValueError, match="every role exactly once"):
        replace(language, palette=language.palette[:-1])
    with pytest.raises(ValueError, match="lowercase hex"):
        replace(language, palette=(("background", "#FFFFFF"), *language.palette[1:]))
    with pytest.raises(ValueError, match="CSS custom properties"):
        replace(language, tokens=(("color", "#ffffff"),))
    with pytest.raises(ValueError, match="unique"):
        replace(language, tokens=(("--vl-a", "1"), ("--vl-a", "2")))
    with pytest.raises(ValueError, match="content hash"):
        replace(language, catalog_content_hash="abc")


@pytest.mark.parametrize(
    "value",
    [
        "url(//host/x)",
        "red;background:url(x)",
        "expression(alert(1))",
        "var(--vl-x)",
        "rgb(1,2,3",
        "x" * (MAX_TOKEN_VALUE_LENGTH + 1),
        "calc(1px + 2px)",
        "image-set(x 1x)",
        "rgb(rgb(1, 2, 3))",
        "xrgb(1, 2, 3)",
        "rgba (0, 0, 0, 0.5)",
        "red)",
        '"Segoe UI, sans-serif',
        "#a1b2c3 !important",
        "red\nblue",
        " 16px",
        "",
    ],
)
def test_visual_tokens_reject_values_that_are_not_plain_css(value: str) -> None:
    with pytest.raises(ValueError, match="plain CSS values"):
        with_token("--vl-color-primary", value)


@pytest.mark.parametrize(
    "name", ["--vl-x:y", "--vl-X", "--vl-", "--vl-a--b", "--vl-a-", "--vl-a\n"]
)
def test_visual_tokens_reject_names_that_are_not_plain_custom_properties(name: str) -> None:
    with pytest.raises(ValueError, match="named CSS custom properties"):
        with_token(name, "16px")


@pytest.mark.parametrize(
    "value",
    [
        "#a1b2c3",
        "0 1px 2px rgba(0, 0, 0, 0.06)",
        'system-ui, -apple-system, "Segoe UI", sans-serif',
        "1.6",
        "52px",
        "hsl(210, 40%, 50%)",
        "x" * MAX_TOKEN_VALUE_LENGTH,
    ],
)
def test_visual_tokens_accept_plain_css_values(value: str) -> None:
    assert with_token("--vl-color-primary", value).token_values == {"--vl-color-primary": value}


def test_every_token_the_catalog_resolves_is_a_plain_css_value() -> None:
    variants = catalog_variants()
    stacks: set[str] = set()

    for choices in variants:
        language = create_visual_language(
            choices=choices, product_name="Catalog", rationale="Every catalog value"
        )
        assert language.token_values == resolve_visual_tokens(choices)
        stacks.update(
            (language.token_values["--vl-font-heading"], language.token_values["--vl-font-body"])
        )

    covered = {
        (name, getattr(choices, name)) for choices in variants for name in VISUAL_DIMENSION_NAMES
    }
    every_value = {(name, value) for name, values in VISUAL_DIMENSIONS.items() for value in values}
    assert every_value - covered == {("body_family", family) for family in UNREADABLE_BODY_FAMILIES}
    assert stacks == {spec.stack for spec in FONTS.values()}


def test_visual_language_snapshot_round_trips_and_rejects_non_canonical_payloads():
    language = design_fixtures.visual_language()
    snapshot = language.to_snapshot()
    assert set(snapshot) == {
        "catalog_version",
        "catalog_content_hash",
        "choices",
        "product_name",
        "rationale",
        "palette",
        "tokens",
        "twin_fit",
    }
    assert snapshot["twin_fit"][0]["name"] == "Hotel Receptionist Twin"
    restored = visual_language_from_snapshot(snapshot)
    assert restored == language
    assert isinstance(restored, VisualLanguage)
    with pytest.raises(ValueError, match="requires tokens"):
        visual_language_from_snapshot(
            {key: value for key, value in snapshot.items() if key != "tokens"}
        )
    with pytest.raises(ValueError, match="not canonical"):
        visual_language_from_snapshot({**snapshot, "extra": 1})
    with pytest.raises(ValueError, match="unknown visual choice"):
        visual_language_from_snapshot(
            {**snapshot, "choices": {**snapshot["choices"], "hue_family": "NEON"}}
        )
    with pytest.raises(ValueError, match="version must be an integer"):
        visual_language_from_snapshot({**snapshot, "catalog_version": "1"})
    with pytest.raises(ValueError, match="strings to strings"):
        visual_language_from_snapshot({**snapshot, "palette": {"background": 1}})
    with pytest.raises(ValueError, match="must be a mapping"):
        visual_language_from_snapshot({**snapshot, "choices": []})


def test_visual_language_tolerates_reordered_keys_as_postgres_jsonb_returns_them():
    language = design_fixtures.visual_language()
    snapshot = language.to_snapshot()
    shuffled = {
        **snapshot,
        "palette": dict(
            sorted(snapshot["palette"].items(), key=lambda item: (len(item[0]), item[0]))
        ),
        "tokens": dict(
            sorted(snapshot["tokens"].items(), key=lambda item: (len(item[0]), item[0]))
        ),
    }
    restored = visual_language_from_snapshot(shuffled)
    assert restored == language
    assert tuple(role for role, _ in restored.palette) == PALETTE_ROLES
    assert restored.content_hash == language.content_hash


def test_alternatives_carry_the_visual_language_only_when_present():
    without = design_fixtures.design_alternative(index=1)
    with_language = design_fixtures.design_alternative(index=2)
    assert without.visual_language is None
    assert "visual_language" not in without.to_snapshot()
    assert (
        with_language.to_snapshot()["visual_language"]
        == with_language.visual_language.to_snapshot()
    )
    assert with_language.content_hash != replace(with_language, visual_language=None).content_hash


def test_design_package_round_trips_with_and_without_visual_language():
    package = design_fixtures.design_package()
    snapshot = package.to_snapshot()
    alternatives = {item["code"]: item for item in snapshot["alternatives"]}
    assert "visual_language" not in alternatives["DES-001"]
    assert (
        alternatives["DES-002"]["visual_language"]["choices"]["hue_family"]
        == HueFamily.EMERALD.value
    )
    restored = design_package_from_snapshot(snapshot)
    assert restored == package
    assert restored.content_hash == package.content_hash
    legacy = {
        **snapshot,
        "alternatives": [
            {key: value for key, value in item.items() if key != "visual_language"}
            for item in snapshot["alternatives"]
        ],
    }
    legacy_package = design_package_from_snapshot(legacy)
    assert all(item.visual_language is None for item in legacy_package.alternatives)
    explicit_null = {
        **snapshot,
        "alternatives": [{**item, "visual_language": None} for item in snapshot["alternatives"]],
    }
    with pytest.raises(ValueError, match="not canonical"):
        design_package_from_snapshot(explicit_null)


def test_api_payload_round_trips_the_visual_language_and_strips_absent_ones():
    package = design_fixtures.design_package()
    payload = DesignPackagePayload.from_domain(package)
    first, second = payload.alternatives
    assert first.visual_language is None
    assert second.visual_language is not None
    assert second.visual_language.choices.archetype.value == "DASHBOARD"
    assert second.visual_language.palette["primary"].startswith("#")
    assert payload.to_domain() == package
    assert payload.model_dump(mode="json")["alternatives"][0]["visual_language"] is None


def test_a_language_without_a_direction_keeps_its_snapshot_tokens_and_hash() -> None:
    language = design_fixtures.visual_language()
    neutral = create_visual_language(
        choices=NEUTRAL_VISUAL_CHOICES, product_name="Catalog", rationale="Every catalog value"
    )
    snapshot = language.to_snapshot()

    assert (language.direction, neutral.direction) == (None, None)
    assert language.content_hash == STORED_LANGUAGE_HASH
    assert neutral.content_hash == STORED_NEUTRAL_LANGUAGE_HASH
    assert "direction" not in snapshot
    assert list(snapshot)[-1] == "twin_fit"
    assert neutral.token_values == resolve_visual_tokens(NEUTRAL_VISUAL_CHOICES)
    assert (
        create_visual_language(
            choices=NEUTRAL_VISUAL_CHOICES,
            product_name="Catalog",
            rationale="Every catalog value",
            direction=None,
        )
        == neutral
    )
    assert visual_language_from_snapshot(json.loads(language.canonical_json())) == language
    with pytest.raises(ValueError, match="not canonical"):
        visual_language_from_snapshot({**snapshot, "direction": None})


def test_a_language_with_a_direction_carries_it_last_and_round_trips() -> None:
    plain = design_fixtures.visual_language()
    value = direction()
    language = directed_language(plain, value)
    snapshot = language.to_snapshot()
    restored = visual_language_from_snapshot(json.loads(language.canonical_json()))

    assert language.direction == value
    assert list(snapshot)[-1] == "direction"
    assert snapshot["direction"] == value.to_snapshot()
    assert {key: item for key, item in snapshot.items() if key not in {"direction", "tokens"}} == {
        key: item for key, item in plain.to_snapshot().items() if key != "tokens"
    }
    assert language.token_values == {
        **plain.token_values,
        **direction_tokens(value, plain.token_values),
        **bundled_font_tokens(plain.choices, plain.token_values),
    }
    assert visual_language_from_snapshot(snapshot) == language
    assert restored == language
    assert restored.content_hash == language.content_hash
    assert language.content_hash != plain.content_hash
    with pytest.raises(ValueError, match="visual direction must be a VisualDirection"):
        replace(plain, direction=value.to_snapshot())
    with pytest.raises(ValueError, match="visual direction snapshot must be a mapping"):
        visual_language_from_snapshot({**snapshot, "direction": []})
    with pytest.raises(ValueError, match="needs 3 to 5 rules"):
        visual_language_from_snapshot(
            {**snapshot, "direction": {**snapshot["direction"], "rules": []}}
        )


def test_a_package_with_a_direction_round_trips_through_snapshot_and_api_payload() -> None:
    package = directed_package(design_fixtures.design_package())
    payload = DesignPackagePayload.from_domain(package)
    dumped = payload.model_dump(mode="json")
    language = next(
        item.visual_language for item in payload.alternatives if item.visual_language is not None
    )
    stored = next(
        item["visual_language"]
        for item in dumped["alternatives"]
        if item["visual_language"] is not None
    )

    assert language.direction is not None
    assert language.direction.axes.layout is DirectionLayout.EDITORIAL
    assert stored["direction"] == direction().to_snapshot()
    assert payload.to_domain() == package
    assert DesignPackagePayload.model_validate(dumped).to_domain() == package
    assert DesignPackagePayload.model_validate(dumped).to_domain().content_hash == (
        package.content_hash
    )
    assert design_package_from_snapshot(json.loads(package.canonical_json())) == package
    assert package.content_hash != design_fixtures.design_package().content_hash


def test_only_a_language_with_a_direction_names_the_bundled_fonts() -> None:
    choices = replace(
        NEUTRAL_VISUAL_CHOICES,
        heading_family=FontFamily.GEOMETRIC_SANS,
        body_family=FontFamily.GROTESQUE_SANS,
    )
    plain = create_visual_language(choices=choices, product_name="Catalog", rationale="Fonts")
    language = create_visual_language(
        choices=choices, product_name="Catalog", rationale="Fonts", direction=direction()
    )
    catalog = resolve_visual_tokens(choices)
    restored = visual_language_from_snapshot(json.loads(language.canonical_json()))

    assert plain.token_values == catalog
    assert bundled_families(plain.token_values) == ()
    assert language.token_values == {
        **catalog,
        **direction_tokens(direction(), catalog),
        "--vl-font-heading": f'"Geist", {FONTS[FontFamily.GEOMETRIC_SANS].stack}',
        "--vl-font-body": f'"Libre Franklin", {FONTS[FontFamily.GROTESQUE_SANS].stack}',
        "--vl-font-mono": '"Geist Mono", ui-monospace, Consolas, monospace',
    }
    assert bundled_families(language.token_values) == ("Geist", "Geist Mono", "Libre Franklin")
    assert restored == language
    assert restored.content_hash == language.content_hash
