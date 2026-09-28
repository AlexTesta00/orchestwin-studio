from __future__ import annotations

from uuid import UUID

import pytest

from orchestwin.knowledge.layout import (
    FEEDBACK_FOLDER,
    KNOWLEDGE_SCHEMA_VERSION,
    STAGE_LABELS,
    STAGE_PAYLOAD_KEYS,
    STAGES,
    schema_document,
    stage_document,
    stage_text,
    table_document,
    twin_document,
    twin_slug,
    twin_text,
)

TWIN_ID = UUID("3fe4f1ad-84e2-4ab3-a6d8-b3ab4f8083b6")


def test_the_folder_has_five_stages_with_labels_and_payload_keys() -> None:
    assert KNOWLEDGE_SCHEMA_VERSION == 2
    assert STAGES == ("brief", "team", "twins", "requirements", "design")
    assert set(STAGE_LABELS) == set(STAGES) == set(STAGE_PAYLOAD_KEYS)


def test_paths_follow_the_documented_layout() -> None:
    assert stage_document("design") == "design/design.json"
    assert stage_text("design") == "design/design.md"
    assert schema_document("manifest") == "schema/manifest.schema.json"
    assert table_document("requirements", "user-stories") == "requirements/tables/user-stories.csv"
    assert twin_document("ada-3fe4f1ad") == "twins/ada-3fe4f1ad/twin.json"
    assert twin_text("ada-3fe4f1ad") == "twins/ada-3fe4f1ad/twin.md"
    assert FEEDBACK_FOLDER == "twins/feedback"


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Addetti all'accoglienza", "addetti-all-accoglienza-3fe4f1ad"),
        ("  Perché   È così?  ", "perche-e-cosi-3fe4f1ad"),
        ("Organizzatori / volontari (2026)", "organizzatori-volontari-2026-3fe4f1ad"),
        ("日本語", "twin-3fe4f1ad"),
        ("feedback", "feedback-3fe4f1ad"),
    ],
)
def test_twin_slug_is_ascii_and_ends_with_the_identity_of_the_twin(name: str, slug: str) -> None:
    assert twin_slug(name, TWIN_ID) == slug
    assert twin_slug(name, str(TWIN_ID)) == slug


def test_twin_slug_bounds_long_names_without_a_trailing_separator() -> None:
    slug = twin_slug("Responsabile " * 12, TWIN_ID)

    assert slug.endswith("-3fe4f1ad")
    assert len(slug) <= 48 + 9
    assert "--" not in slug


def test_twins_with_the_same_name_get_different_slugs() -> None:
    other = UUID("9fe4f1ad-84e2-4ab3-a6d8-b3ab4f8083b6")

    assert twin_slug("Ada", TWIN_ID) != twin_slug("Ada", other)
