from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from orchestwin.knowledge.diagrams import MERMAID_VERSION
from orchestwin.knowledge.folder import (
    KNOWLEDGE_FOLDER_KIND,
    KnowledgeFolderError,
    build_knowledge_folder,
    content_files,
    folder_archive,
    folder_content_hash,
    identifiers,
    project_language,
    stage_document_payload,
)
from orchestwin.knowledge.layout import (
    KNOWLEDGE_INDEX,
    KNOWLEDGE_MANIFEST,
    STAGE_PAYLOAD_KEYS,
    STAGES,
    schema_document,
    stage_document,
)
from orchestwin.knowledge.schema import SCHEMA_NAMES, schema_files
from orchestwin.knowledge.state import ProjectStateSources
from orchestwin.knowledge.tables import TABLE_COLUMNS
from orchestwin.knowledge.twins import portable_twins

from .knowledge_fixtures import (
    PROJECT_NAME,
    PUBLISHED_AT,
    development_sources,
    real_sources,
    sources,
)
from .knowledge_fixtures import test_run as acceptance_run

STAGE_FILES = tuple(
    path for stage in STAGES for path in (f"{stage}/{stage}.json", f"{stage}/{stage}.md")
)
DESIGN_FILES = ("design/critiques.md", "design/mockups.md", "design/mockup.html")
FEEDBACK_FILES = (
    "twins/feedback/discussions.json",
    "twins/feedback/feedback.md",
    "twins/feedback/insights.json",
    "twins/feedback/reviews.json",
)
STATE_FILES = (
    "state/state.json",
    "state/state.md",
    "twins/feedback/changes.json",
    "twins/feedback/tests.json",
    "twins/feedback/learned.json",
)
DIAGRAM_FILES = (
    "requirements/diagrams/use-cases.mmd",
    "requirements/diagrams/requirements.mmd",
    "requirements/diagrams/traceability.mmd",
    "design/diagrams/des-001-workflows.mmd",
    "design/diagrams/des-002-workflows.mmd",
    "design/diagrams/screen-map.mmd",
    "design/diagrams/traceability.mmd",
)


def folder(package=None, **changes):
    return build_knowledge_folder(
        sources(**changes) if package is None else package,
        version_number=1,
        created_at=PUBLISHED_AT,
    )


def test_folder_holds_every_view_of_every_approved_stage() -> None:
    package = sources()
    twins = portable_twins(package)

    built = build_knowledge_folder(package, version_number=1, created_at=PUBLISHED_AT)

    assert built.entries == tuple(
        sorted(
            {
                KNOWLEDGE_INDEX,
                KNOWLEDGE_MANIFEST,
                *STAGE_FILES,
                *DESIGN_FILES,
                *FEEDBACK_FILES,
                *STATE_FILES,
                *DIAGRAM_FILES,
                *TABLE_COLUMNS,
                *schema_files(),
                *(path for twin in twins for path in (twin.document_path, twin.text_path)),
            }
        )
    )
    assert built.project_id == package.project_id
    assert built.project_name == PROJECT_NAME
    assert built.file_name == f"orchestwin-{package.project_id}-knowledge-v1.zip"


def test_stage_documents_are_the_exact_approved_snapshots() -> None:
    package = sources()
    built = folder(package)

    for stage in STAGES:
        version = package.version(stage)
        document = json.loads(built.files[stage_document(stage)])
        assert document == stage_document_payload(package, stage)
        assert document["id"] == str(version.id)
        assert document["version_number"] == version.version_number
        assert document["content_hash"] == version.content_hash
        assert document[STAGE_PAYLOAD_KEYS[stage]] == package.payload(stage)


def test_manifest_indexes_package_project_stages_twins_views_and_feedback() -> None:
    package = sources()
    built = folder(package)
    manifest = json.loads(built.files[KNOWLEDGE_MANIFEST])

    assert manifest == built.manifest
    assert manifest["schema_version"] == 3
    assert manifest["kind"] == KNOWLEDGE_FOLDER_KIND
    assert manifest["manifest"] == KNOWLEDGE_MANIFEST
    assert manifest["index"] == KNOWLEDGE_INDEX
    assert manifest["generator"] == {
        "name": "OrchesTwin Studio",
        "mermaid_version": MERMAID_VERSION,
    }
    assert manifest["package"] == {
        "version_number": 1,
        "content_hash": built.content_hash,
        "created_at": PUBLISHED_AT.isoformat(),
    }
    assert manifest["project"]["id"] == str(package.project_id)
    assert manifest["project"]["name"] == PROJECT_NAME
    assert sorted(manifest["stages"]) == sorted(STAGES)
    design = manifest["stages"]["design"]
    assert design["document"] == "design/design.json"
    assert design["text"] == "design/design.md"
    assert design["content_hash"] == package.design.content_hash
    assert design["gate"]["status"] == "APPROVED"
    assert design["gate"]["artifact"]["content_hash"] == package.design.content_hash
    assert manifest["twins"] == [twin.summary() for twin in portable_twins(package)]
    assert manifest["feedback"] == {
        "folder": "twins/feedback",
        "text": "twins/feedback/feedback.md",
        "reviews_document": "twins/feedback/reviews.json",
        "discussions_document": "twins/feedback/discussions.json",
        "insights_document": "twins/feedback/insights.json",
        "reviews": 2,
        "findings": 4,
        "decisions": 2,
        "discussions": 1,
        "insights": 1,
        "changes": "twins/feedback/changes.json",
        "change_reviews": 0,
        "tests": "twins/feedback/tests.json",
        "test_runs": 0,
        "learned": "twins/feedback/learned.json",
        "learned_observations": 0,
    }
    assert manifest["progress"] == {"approved": list(STAGES), "pending": None, "complete": True}
    assert manifest["state"] == {
        "document": "state/state.json",
        "text": "state/state.md",
        "changes": 0,
        "pending_changes": 0,
        "stale_reviews": 0,
        "aligned_commit": None,
        "open_tasks": 0,
    }
    assert manifest["schemas"] == {name: schema_document(name) for name in SCHEMA_NAMES}
    assert len(manifest["schemas"]) == 14
    assert manifest["schemas"]["tests"] == "schema/tests.schema.json"
    assert manifest["schemas"]["learning"] == "schema/learned.schema.json"


def test_manifest_lists_the_three_views_of_requirements_and_design() -> None:
    views = folder().manifest["views"]

    assert sorted(views) == ["design", "requirements"]
    assert views["requirements"]["text"] == [
        {"path": "requirements/requirements.md", "title": "Requirements"}
    ]
    assert [entry["path"] for entry in views["design"]["text"]] == [
        "design/design.md",
        "design/critiques.md",
        "design/mockups.md",
    ]
    assert [entry["path"] for stage in views.values() for entry in stage["tables"]] == sorted(
        TABLE_COLUMNS, key=lambda path: (path.startswith("design"), path)
    )
    assert {
        "path": "requirements/tables/user-stories.csv",
        "title": "User stories",
    } in views["requirements"]["tables"]
    assert [entry["path"] for stage in views.values() for entry in stage["diagrams"]] == list(
        DIAGRAM_FILES
    )
    assert views["requirements"]["diagrams"][0] == {
        "key": "requirements/use-cases",
        "kind": "USE_CASES",
        "subject": None,
        "title": "Use cases",
        "path": "requirements/diagrams/use-cases.mmd",
    }
    assert views["requirements"]["mockups"] == []
    assert [entry["path"] for entry in views["design"]["mockups"]] == ["design/mockup.html"]


def test_manifest_digests_cover_every_file_but_the_manifest_and_the_index() -> None:
    built = folder()

    assert set(built.manifest["files"]) == set(built.files) - {
        KNOWLEDGE_INDEX,
        KNOWLEDGE_MANIFEST,
    }
    for path, digest in built.manifest["files"].items():
        assert digest == hashlib.sha256(built.files[path].encode("utf-8")).hexdigest()
    assert list(built.manifest["files"]) == sorted(built.manifest["files"])


def test_identifiers_give_every_code_its_stage_kind_scope_and_identity() -> None:
    package = sources()
    entries = identifiers(package)
    design = package.payload("design")
    alternative = design["alternatives"][0]
    workflow = alternative["workflows"][0]
    screen = design["prototype"]["screens"][0]

    assert entries == folder(package).manifest["identifiers"]
    assert {
        "stage": "design",
        "kind": "DESIGN_WORKFLOW",
        "scope": alternative["code"],
        "code": workflow["code"],
        "id": workflow["id"],
    } in entries
    assert {
        "stage": "design",
        "kind": "PROTOTYPE_ELEMENT",
        "scope": screen["code"],
        "code": screen["elements"][0]["code"],
        "id": screen["elements"][0]["id"],
    } in entries
    assert {entry["kind"] for entry in entries if entry["stage"] == "requirements"} == {
        "REQUIREMENT",
        "USER_STORY",
        "ACCEPTANCE_CRITERION",
        "SCENARIO",
        "DEFINITION_OF_DONE",
    }
    keys = [(entry["kind"], entry["scope"], entry["code"]) for entry in entries]
    assert len(keys) == len(set(keys))


def test_content_hash_ignores_the_package_number_and_time_but_not_the_content() -> None:
    package = sources()
    first = build_knowledge_folder(package, version_number=1, created_at=PUBLISHED_AT)
    later = build_knowledge_folder(
        package, version_number=7, created_at=PUBLISHED_AT + timedelta(days=3)
    )
    without_feedback = folder(with_feedback=False)

    assert first.content_hash == later.content_hash == folder_content_hash(first.files)
    assert first.files[KNOWLEDGE_MANIFEST] != later.files[KNOWLEDGE_MANIFEST]
    assert first.files[KNOWLEDGE_INDEX] != later.files[KNOWLEDGE_INDEX]
    assert without_feedback.content_hash != first.content_hash
    assert folder_content_hash(content_files(package)) == first.content_hash


def test_folder_and_archive_are_reproducible() -> None:
    package = sources()
    built = build_knowledge_folder(package, version_number=1, created_at=PUBLISHED_AT)
    first = folder_archive(built)
    second = folder_archive(
        build_knowledge_folder(package, version_number=1, created_at=PUBLISHED_AT)
    )

    assert first == second
    assert first.archive_hash == hashlib.sha256(first.content).hexdigest()
    assert first.file_name.endswith("-knowledge-v1.zip")
    with zipfile.ZipFile(io.BytesIO(first.content)) as archive:
        assert tuple(archive.namelist()) == first.entries == tuple(sorted(first.entries))
        assert {item.date_time for item in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        assert archive.testzip() is None
        assert archive.read(KNOWLEDGE_MANIFEST).decode("utf-8") == built.files[KNOWLEDGE_MANIFEST]


def test_prebuilt_content_is_indexed_without_being_rebuilt() -> None:
    package = sources()
    content = content_files(package)

    built = build_knowledge_folder(
        package, version_number=2, created_at=PUBLISHED_AT, content=content
    )

    assert built.content_hash == folder_content_hash(content)
    assert {path: built.files[path] for path in content} == content
    assert KNOWLEDGE_MANIFEST not in content


def test_text_documents_embed_their_diagrams_and_name_their_tables() -> None:
    built = folder()
    requirements = built.files["requirements/requirements.md"]
    design = built.files["design/design.md"]

    assert "## Views" in requirements
    assert "- `tables/user-stories.csv`" in requirements
    assert "- `diagrams/use-cases.mmd`: Use cases" in requirements
    assert requirements.count("```mermaid") == 3
    assert "```mermaid\nusecase-beta\n" in requirements
    assert "```mermaid\nrequirementDiagram\n" in requirements
    assert design.count("```mermaid") == 4
    assert "```mermaid\nstateDiagram-v2\n" in design
    assert "- `tables/workflows.csv`" in design
    for path in DIAGRAM_FILES:
        source = built.files[path]
        document = requirements if path.startswith("requirements") else design
        assert source.rstrip("\n") in document


def test_index_explains_the_folder_to_people_and_coding_agents() -> None:
    built = folder()
    index = built.files[KNOWLEDGE_INDEX]
    twin = built.manifest["twins"][0]

    assert index.startswith(f"# OrchesTwin knowledge folder: {PROJECT_NAME}\n")
    assert f"Knowledge folder version 1 of project {built.project_id}" in index
    assert f"Content hash `{built.content_hash}`" in index
    headings = [line for line in index.splitlines() if line.startswith("## ")]
    assert headings == [
        "## What this folder is",
        "## How to use it",
        "## Approved stages",
        "## User twins",
        "## Views",
        "## Twin feedback",
        "## Development state",
        "## Latest critiques on the code",
        "## Acceptance tests",
        "## What the twins learned",
        "## Schema",
        "## Files",
    ]
    assert "This folder holds 5 of 5 approved steps; every step is approved." in index
    assert (
        "## Acceptance tests\n\nNo run of the acceptance tests is recorded yet: `ut test` runs "
        "them on the application and records the result in the Studio.\n"
    ) in index
    assert "| tests | `schema/tests.schema.json` |" in index
    assert "| learning | `schema/learned.schema.json` |" in index
    assert (
        "## What the twins learned\n\n- Receptionist Twin, version 1.0: it has learned nothing "
        "yet.\n\n`twins/feedback/learned.json` holds what the twins learned"
    ) in index
    assert "- Build against `requirements/requirements.md` and `design/design.md`" in index
    assert "- The state of the development is in `state/state.md` and `state/state.json`" in index
    assert "The Studio has recorded no change (commit) of the code yet." in index
    assert "## Latest critiques on the code\n\nNone yet.\n" in index
    assert "`twins/feedback/changes.json` holds 0 review runs of the twins" in index
    assert f"`{twin['document']}`" in index
    assert "| requirements | diagram | `requirements/diagrams/use-cases.mmd` | Use cases |" in index
    assert "| design | mockup | `design/mockup.html` |" in index
    assert (
        "2 reviews with 4 findings, 2 owner decisions, 1 approved discussion and 1 applied insight"
    ) in index
    assert "| manifest | `schema/manifest.schema.json` |" in index
    assert f"| brief/brief.md | {built.manifest['files']['brief/brief.md']} |" in index


def test_design_without_mockup_still_produces_a_complete_folder() -> None:
    package = sources()
    design = package.design
    bare = replace(design.package, prototype=None)
    version = replace(design, package=bare, content_hash=bare.content_hash)

    built = build_knowledge_folder(
        replace(package, design=version), version_number=1, created_at=PUBLISHED_AT
    )

    assert "design/diagrams/screen-map.mmd" not in built.files
    assert "design/tables/screens.csv" not in built.files
    assert "design/tables/transitions.csv" not in built.files
    assert "design/diagrams/traceability.mmd" in built.files
    assert all(entry["kind"] != "PROTOTYPE_SCREEN" for entry in built.manifest["identifiers"])


@pytest.mark.parametrize("number", [0, -1])
def test_package_numbers_start_from_one(number: int) -> None:
    with pytest.raises(KnowledgeFolderError) as error:
        build_knowledge_folder(sources(), version_number=number, created_at=PUBLISHED_AT)

    assert error.value.code == "INVALID_PACKAGE_VERSION"


def test_package_time_must_be_timezone_aware() -> None:
    with pytest.raises(KnowledgeFolderError) as error:
        build_knowledge_folder(sources(), version_number=1, created_at=datetime(2026, 9, 27, 20, 0))

    assert error.value.code == "INVALID_PACKAGE_TIMESTAMP"


def test_project_language_follows_the_requirement_texts() -> None:
    italian = {
        "requirements": [
            {"statement": "L'utente inserisce il nome di un ospite e lo aggiunge alla lista"},
            {"statement": "La lista mostra il numero progressivo e il nome di ogni ospite"},
        ],
        "user_stories": [{"goal": "Aggiungere gli ospiti per nome durante il workshop"}],
        "acceptance_criteria": [
            {"statement": "L'applicazione rifiuta i nomi vuoti con un messaggio visibile"}
        ],
    }
    empty = {"requirements": [], "user_stories": [], "acceptance_criteria": []}

    assert project_language(italian) == "it"
    assert project_language(empty) is None


def test_every_folder_carries_the_test_runs_and_they_change_the_content_hash() -> None:
    package = sources()
    empty = folder(package)
    tested = folder(replace(package, state=ProjectStateSources(tests=(acceptance_run(),))))

    assert json.loads(empty.files["twins/feedback/tests.json"]) == {
        "schema_version": 3,
        "kind": "orchestwin.test-reviews",
        "project_id": str(package.project_id),
        "runs": [],
    }
    assert json.loads(tested.files["twins/feedback/tests.json"])["runs"] == [acceptance_run()]
    assert tested.manifest["feedback"]["test_runs"] == 1
    assert tested.content_hash != empty.content_hash
    assert "## Critiques on the acceptance tests" in tested.files["twins/feedback/feedback.md"]


def test_what_the_twins_learned_changes_the_content_hash_but_never_the_twin_documents() -> None:
    package = real_sources()
    plain = folder(package)
    learned = folder(replace(package, state=development_sources()))
    twin_files = [
        path
        for path in plain.files
        if path.startswith("twins/") and not path.startswith("twins/feedback/")
    ]

    assert len(twin_files) == 6
    assert {path: learned.files[path] for path in twin_files} == {
        path: plain.files[path] for path in twin_files
    }
    assert learned.manifest["twins"] == plain.manifest["twins"]
    assert learned.manifest["stages"]["twins"] == plain.manifest["stages"]["twins"]
    assert (
        learned.files["twins/feedback/learned.json"] != plain.files["twins/feedback/learned.json"]
    )
    assert learned.content_hash != plain.content_hash
    assert "## Learned during development" in learned.files["twins/feedback/feedback.md"]
