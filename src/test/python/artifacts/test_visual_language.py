from __future__ import annotations

from dataclasses import replace

import pytest

from orchestwin.api.design import DesignPackagePayload
from orchestwin.artifacts.design_serialization import design_package_from_snapshot
from orchestwin.artifacts.visual_catalog import (
    PALETTE_ROLES,
    VISUAL_CATALOG_CONTENT_HASH,
    VISUAL_CATALOG_VERSION,
    HueFamily,
    resolve_palette,
)
from orchestwin.artifacts.visual_language import (
    MAX_PRODUCT_NAME_LENGTH,
    VisualLanguage,
    create_visual_language,
    visual_language_from_snapshot,
)

from . import design_fixtures


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
    with pytest.raises(ValueError, match="every role"):
        replace(language, palette=language.palette[:-1])
    with pytest.raises(ValueError, match="lowercase hex"):
        replace(language, palette=(("background", "#FFFFFF"), *language.palette[1:]))
    with pytest.raises(ValueError, match="CSS custom properties"):
        replace(language, tokens=(("color", "#ffffff"),))
    with pytest.raises(ValueError, match="unique"):
        replace(language, tokens=(("--vl-a", "1"), ("--vl-a", "2")))
    with pytest.raises(ValueError, match="content hash"):
        replace(language, catalog_content_hash="abc")


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
    }
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
