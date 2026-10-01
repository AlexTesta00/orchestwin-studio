from __future__ import annotations

import json

import pytest

from orchestwin.knowledge.documents import twin_markdown
from orchestwin.knowledge.folder import build_knowledge_folder
from orchestwin.knowledge.layout import TWIN_DOCUMENT_KIND, twin_slug
from orchestwin.knowledge.twins import PortableTwin, portable_twins

from .knowledge_fixtures import PROJECT_NAME, PUBLISHED_AT, partial_sources, sources


def test_every_twin_gets_a_self_contained_document_with_its_persona_and_origin() -> None:
    package = sources()
    snapshot = package.modeling.snapshot.to_snapshot()

    twins = portable_twins(package)

    assert len(twins) == len(snapshot["twin_versions"])
    for twin, version in zip(twins, snapshot["twin_versions"], strict=True):
        reference = version["profile"]["persona_reference"]
        assert twin.slug == twin_slug(version["profile"]["name"], version["twin_id"])
        assert twin.document_path == f"twins/{twin.slug}/twin.json"
        assert twin.text_path == f"twins/{twin.slug}/twin.md"
        assert twin.document["schema_version"] == 3
        assert twin.document["kind"] == TWIN_DOCUMENT_KIND
        assert twin.document["slug"] == twin.slug
        assert twin.document["twin"] == version
        assert twin.document["persona"]["persona_id"] == reference["persona_id"]
        assert twin.document["persona"]["version_number"] == reference["version_number"]
        assert twin.document["persona"]["content_hash"] == reference["content_hash"]
        assert twin.document["origin"] == {
            "project_id": str(package.project_id),
            "project_name": PROJECT_NAME,
            "user_modeling": {
                "version_id": str(package.modeling.id),
                "version_number": package.modeling.version_number,
                "content_hash": package.modeling.content_hash,
            },
            "approved_at": package.modeling_gate.updated_at.isoformat(),
        }


def test_twin_summary_is_the_manifest_entry_of_the_twin() -> None:
    twin = portable_twins(sources())[0]
    version = twin.document["twin"]

    assert twin.summary() == {
        "twin_id": version["twin_id"],
        "name": version["profile"]["name"],
        "slug": twin.slug,
        "version_number": version["version_number"],
        "content_hash": version["content_hash"],
        "validation_status": version["profile"]["validation_status"],
        "persona_id": twin.document["persona"]["persona_id"],
        "document": twin.document_path,
        "text": twin.text_path,
    }


def test_twin_files_of_the_folder_are_the_portable_documents() -> None:
    package = sources()
    folder = build_knowledge_folder(package, version_number=1, created_at=PUBLISHED_AT)

    for twin in portable_twins(package):
        assert json.loads(folder.files[twin.document_path]) == twin.document
        assert folder.files[twin.text_path] == twin_markdown(twin.document)


def test_twin_text_states_identity_origin_persona_and_observations() -> None:
    twin = portable_twins(sources())[0]
    version = twin.document["twin"]
    profile = version["profile"]

    text = twin_markdown(twin.document)

    assert text.startswith(f"# {profile['name']}\n")
    assert (
        f"User twin version {version['version_number']}, content hash `{version['content_hash']}`, "
        f"of the project {PROJECT_NAME}. Validation status"
    ) in text
    assert version["twin_id"] not in text
    assert twin.document["origin"]["project_id"] not in text
    assert f"Validation status {profile['validation_status']}" in text
    assert "A user twin is a model of a kind of user, not a person" in text
    assert "## Persona" in text
    assert "## Profile" in text
    assert "| Observation | Value | Epistemic status | Confidence | Validation |" in text
    for observation in profile["observations"]:
        assert f"| {observation['observation_key']} |" in text


def test_twin_without_its_persona_in_the_snapshot_is_rejected() -> None:
    twin = portable_twins(sources())[0]
    orphan = {
        **twin.document["twin"],
        "profile": {
            **twin.document["twin"]["profile"],
            "persona_reference": {
                **twin.document["twin"]["profile"]["persona_reference"],
                "version_number": 99,
            },
        },
    }

    class Modeling:
        id = "x"
        version_number = 1
        content_hash = "0" * 64

        class snapshot:
            @staticmethod
            def to_snapshot():
                return {"persona_versions": [twin.document["persona"]], "twin_versions": [orphan]}

    class Package:
        project_id = "p"
        project_name = "n"
        modeling = Modeling
        modeling_gate = sources().modeling_gate

    with pytest.raises(ValueError, match="persona version outside its snapshot"):
        portable_twins(Package)


def test_portable_twin_is_a_value() -> None:
    first, second = portable_twins(sources())[0], portable_twins(sources())[0]

    assert isinstance(first, PortableTwin)
    assert first == second


@pytest.mark.parametrize("through", ["brief", "team"])
def test_a_folder_before_the_approved_twins_has_no_portable_twin(through: str) -> None:
    package = partial_sources(through)

    assert portable_twins(package) == ()
    assert portable_twins(partial_sources("twins"))
