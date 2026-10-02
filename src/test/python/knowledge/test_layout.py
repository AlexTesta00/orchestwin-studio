from __future__ import annotations

from uuid import UUID

import pytest

from orchestwin.knowledge import state
from orchestwin.knowledge.layout import (
    FEEDBACK_CHANGES,
    FEEDBACK_FOLDER,
    FEEDBACK_LEARNING,
    KNOWLEDGE_SCHEMA_VERSION,
    SCHEMA_FILE_NAMES,
    STAGE_LABELS,
    STAGE_PAYLOAD_KEYS,
    STAGES,
    STATE_DOCUMENT,
    STATE_FOLDER,
    STATE_TEXT,
    SUPPORTED_SCHEMA_VERSIONS,
    present_stages,
    schema_document,
    stage_document,
    stage_present,
    stage_text,
    table_document,
    twin_document,
    twin_slug,
    twin_text,
)

TWIN_ID = UUID("3fe4f1ad-84e2-4ab3-a6d8-b3ab4f8083b6")


def test_the_folder_has_five_stages_with_labels_and_payload_keys() -> None:
    assert KNOWLEDGE_SCHEMA_VERSION == 3
    assert SUPPORTED_SCHEMA_VERSIONS == (2, 3)
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


def test_the_paths_of_the_development_state_are_the_shared_ones() -> None:
    assert (STATE_FOLDER, STATE_DOCUMENT, STATE_TEXT) == (
        "state",
        "state/state.json",
        "state/state.md",
    )
    assert FEEDBACK_CHANGES == "twins/feedback/changes.json"
    assert STATE_DOCUMENT is state.STATE_DOCUMENT
    assert STATE_TEXT is state.STATE_TEXT
    assert FEEDBACK_CHANGES is state.FEEDBACK_CHANGES


def test_what_the_twins_learned_has_its_document_and_a_schema_named_after_it() -> None:
    assert FEEDBACK_LEARNING == "twins/feedback/learned.json"
    assert FEEDBACK_LEARNING is state.FEEDBACK_LEARNING
    assert SCHEMA_FILE_NAMES == {"learning": "learned"}
    assert schema_document("learning") == "schema/learned.schema.json"
    assert schema_document("tests") == "schema/tests.schema.json"


@pytest.mark.parametrize(
    ("stages", "present"),
    [
        ({"brief": {}}, ("brief",)),
        ({"brief": {}, "team": {}, "twins": {}}, ("brief", "team", "twins")),
        ({stage: {} for stage in reversed(STAGES)}, STAGES),
        ({"design": {}, "brief": {}}, ("brief", "design")),
        ({"brief": {}, "team": None, "twins": "x"}, ("brief",)),
        ({}, ()),
    ],
)
def test_present_stages_follow_the_stage_order_of_the_manifest(
    stages: dict[str, object], present: tuple[str, ...]
) -> None:
    manifest = {"stages": stages}

    assert present_stages(manifest) == present
    assert [stage for stage in STAGES if stage_present(manifest, stage)] == list(present)


def test_a_manifest_without_stages_holds_none() -> None:
    assert present_stages({}) == ()
    assert present_stages({"stages": ["brief"]}) == ()
    assert stage_present({"stages": {"brief": {}}}, "roadmap") is False


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
