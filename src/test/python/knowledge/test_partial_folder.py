from __future__ import annotations

import asyncio
import io
import json
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from orchestwin.knowledge.archive import KnowledgeArchiveError, read_verified_folder, verify_folder
from orchestwin.knowledge.folder import (
    KnowledgeFolder,
    build_knowledge_folder,
    file_digests,
    folder_archive,
    folder_content_hash,
    json_text,
)
from orchestwin.knowledge.layout import (
    FEEDBACK_CHANGES,
    FEEDBACK_LEARNING,
    FEEDBACK_TESTS,
    FEEDBACK_TEXT,
    KNOWLEDGE_INDEX,
    KNOWLEDGE_MANIFEST,
    STAGE_LABELS,
    STAGES,
    STATE_DOCUMENT,
    STATE_TEXT,
    schema_document,
    stage_document,
)
from orchestwin.knowledge.project_import import plan_project_import
from orchestwin.knowledge.project_import_service import (
    ProjectImportError,
    ProjectImportService,
    complete_folder,
)
from orchestwin.knowledge.schema import (
    SCHEMA_NAMES,
    schema_files,
    schema_name_for_path,
    validate_files,
)
from orchestwin.knowledge.tables import TABLE_COLUMNS
from orchestwin.knowledge.twins import portable_twins

from .knowledge_fixtures import (
    PUBLISHED_AT,
    REAL_PROJECT_ID,
    development_sources,
    files_before_learning,
    files_before_tests,
    partial_sources,
    real_sources,
    schema_two_files,
    state_sources,
)

NEW_PROJECT = UUID("11111111-1111-4111-8111-111111111111")
NEW_BRIEF = UUID("22222222-2222-4222-8222-222222222222")
NEW_OWNER = UUID("33333333-3333-4333-8333-333333333333")
IMPORTED_AT = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
PARTIAL = ("brief", "team", "twins", "requirements")
COMMON_FILES = frozenset(
    {
        KNOWLEDGE_INDEX,
        KNOWLEDGE_MANIFEST,
        STATE_DOCUMENT,
        STATE_TEXT,
        FEEDBACK_CHANGES,
        FEEDBACK_TESTS,
        *schema_files(),
    }
)
OTHER_PROJECT = "99999999-9999-4999-8999-999999999999"
OVERVIEW_LABELS = (
    ("- Progetto", "brief"),
    ("- Per chi è", "twins"),
    ("- Cosa deve fare", "requirements"),
    ("- Design scelto", "design"),
    ("- Come si verifica", "requirements"),
)
REQUIREMENT_DIAGRAMS = (
    "requirements/diagrams/use-cases.mmd",
    "requirements/diagrams/requirements.mmd",
    "requirements/diagrams/traceability.mmd",
)
DESIGN_ONLY = (
    "design/design.json",
    "design/design.md",
    "design/critiques.md",
    "design/mockups.md",
    "design/mockup.html",
    "twins/feedback/feedback.md",
    "twins/feedback/reviews.json",
    "twins/feedback/discussions.json",
    "twins/feedback/insights.json",
)


def stage_files(stage: str) -> set[str]:
    files = {stage_document(stage), f"{stage}/{stage}.md"}
    if stage == "twins":
        files.add(FEEDBACK_LEARNING)
        for twin in portable_twins(partial_sources("twins")):
            files.update((twin.document_path, twin.text_path))
    if stage == "requirements":
        files.update(path for path in TABLE_COLUMNS if path.startswith("requirements/"))
        files.update(REQUIREMENT_DIAGRAMS)
    return files


def partial_folder(through: str, **changes) -> KnowledgeFolder:
    return build_knowledge_folder(
        partial_sources(through, **changes), version_number=1, created_at=PUBLISHED_AT
    )


def resealed(
    files: Mapping[str, str], change: Callable[[dict[str, object]], None] | None = None
) -> dict[str, str]:
    content = {
        path: text
        for path, text in files.items()
        if path not in {KNOWLEDGE_INDEX, KNOWLEDGE_MANIFEST}
    }
    manifest = json.loads(files[KNOWLEDGE_MANIFEST])
    manifest["files"] = file_digests(content)
    manifest["package"]["content_hash"] = folder_content_hash(content)
    if change is not None:
        change(manifest)
    return {**content, KNOWLEDGE_MANIFEST: json_text(manifest)}


def archive_of(files: Mapping[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.writestr(name, files[name])
    return buffer.getvalue()


def refusal(files: Mapping[str, str]) -> KnowledgeArchiveError:
    with pytest.raises(KnowledgeArchiveError) as caught:
        verify_folder(files)
    return caught.value


def plan(folder):
    return plan_project_import(
        folder,
        project_id=NEW_PROJECT,
        brief_version_id=NEW_BRIEF,
        owner_user_id=NEW_OWNER,
        created_at=IMPORTED_AT,
    )


@pytest.mark.parametrize("through", PARTIAL)
def test_a_partial_folder_holds_only_the_approved_stages_and_the_state(through: str) -> None:
    present = STAGES[: STAGES.index(through) + 1]

    folder = partial_folder(through)

    expected = set(COMMON_FILES).union(*(stage_files(stage) for stage in present))
    assert set(folder.files) == expected
    assert not set(DESIGN_ONLY) & set(folder.files)
    for stage in STAGES[len(present) :]:
        assert [path for path in folder.files if path.startswith(f"{stage}/")] == (
            [FEEDBACK_CHANGES, FEEDBACK_TESTS] if stage == "twins" else []
        )


@pytest.mark.parametrize("through", PARTIAL)
def test_the_manifest_of_a_partial_folder_states_its_progress(through: str) -> None:
    present = STAGES[: STAGES.index(through) + 1]
    pending = STAGES[len(present)]

    manifest = partial_folder(through).manifest

    assert manifest["schema_version"] == 3
    assert list(manifest["stages"]) == list(present)
    assert manifest["progress"] == {
        "approved": list(present),
        "pending": pending,
        "complete": False,
    }
    assert manifest["state"] == {
        "document": STATE_DOCUMENT,
        "text": STATE_TEXT,
        "changes": 0,
        "pending_changes": 0,
        "stale_reviews": 0,
        "aligned_commit": None,
        "open_tasks": 0,
    }
    assert list(manifest["views"]) == (["requirements"] if "requirements" in present else [])
    learned = (
        {"learned": FEEDBACK_LEARNING, "learned_observations": 0} if "twins" in present else {}
    )
    assert manifest["feedback"] == {
        "folder": "twins/feedback",
        "text": None,
        "reviews_document": None,
        "discussions_document": None,
        "insights_document": None,
        "reviews": 0,
        "findings": 0,
        "decisions": 0,
        "discussions": 0,
        "insights": 0,
        "changes": FEEDBACK_CHANGES,
        "change_reviews": 0,
        "tests": FEEDBACK_TESTS,
        "test_runs": 0,
        **learned,
    }
    assert bool(manifest["twins"]) is ("twins" in present)
    assert {entry["stage"] for entry in manifest["identifiers"]} == (
        {"requirements"} if "requirements" in present else set()
    )
    assert manifest["project"]["language"] == "it"
    assert manifest["schemas"] == {name: schema_document(name) for name in SCHEMA_NAMES}


@pytest.mark.parametrize("through", PARTIAL)
def test_the_index_of_a_partial_folder_names_the_next_step(through: str) -> None:
    present = STAGES[: STAGES.index(through) + 1]
    index = partial_folder(through).files[KNOWLEDGE_INDEX]
    headings = [line for line in index.splitlines() if line.startswith("## ")]

    assert (
        f"This folder holds {len(present)} of 5 approved steps; "
        f"next: {STAGE_LABELS[STAGES[len(present)]]}."
    ) in index
    assert "Build against `requirements/requirements.md` and `design/design.md`" not in index
    assert ("## User twins" in headings) is ("twins" in present)
    assert ("## Views" in headings) is ("requirements" in present)
    assert "## Development state" in headings
    assert "## Latest critiques on the code" in headings
    learning = ["## What the twins learned"] if "twins" in present else []
    assert headings[-3 - len(learning) :] == [
        "## Acceptance tests",
        *learning,
        "## Schema",
        "## Files",
    ]
    assert "The feedback of the twins on the design comes into this folder" in index
    assert "`design/design.json`" not in index
    assert f"`{stage_document(through)}`" in index


@pytest.mark.parametrize("through", [*PARTIAL, "design"])
def test_the_overview_of_a_folder_holds_a_line_for_each_approved_step(through: str) -> None:
    present = STAGES[: STAGES.index(through) + 1]
    folder = partial_folder(through)

    index = folder.files[KNOWLEDGE_INDEX]
    overview = index.split("\n## In breve\n\n", 1)[1].split("\n\n", 1)[0].splitlines()

    assert index.index("## In breve") < index.index("## What this folder is")
    assert [line.split(":", 1)[0] for line in overview if line.startswith("- ")] == [
        label for label, stage in OVERVIEW_LABELS if stage in present
    ]
    assert overview[0] == (
        "- Progetto: Lista ospiti workshop. Una pagina web per gestire la lista degli ospiti di "
        "un workshop di comunita."
    )
    if "twins" not in present:
        assert overview == overview[:1]
    assert verify_folder(folder.files).present_stages == present


def test_the_index_of_a_folder_up_to_the_requirements_points_to_them() -> None:
    index = partial_folder("requirements").files[KNOWLEDGE_INDEX]

    assert (
        "- The requirements are approved in `requirements/requirements.md`, with stable codes "
        "(REQ-001, USR-001, AC-001); the design comes into this folder once the owner approves "
        "it, and only then is the scope complete."
    ) in index
    assert "| requirements | text | `requirements/requirements.md` | Requirements |" in index


def test_the_index_of_a_folder_of_the_brief_says_that_the_scope_is_not_approved() -> None:
    index = partial_folder("brief").files[KNOWLEDGE_INDEX]

    assert "- The scope is not approved yet: the requirements and the design come into" in index
    assert "Judge every change from the point of view of the user twins" not in index


@pytest.mark.parametrize("through", PARTIAL)
def test_a_partial_folder_passes_verification(through: str) -> None:
    folder = partial_folder(through)
    present = STAGES[: STAGES.index(through) + 1]

    verified = read_verified_folder(folder_archive(folder).content)

    assert verified.schema_version == 3
    assert verified.present_stages == present
    assert verified.pending_stage == STAGES[len(present)]
    assert verified.complete is False
    assert set(verified.documents) == set(present)
    assert verified.content_hash == folder.content_hash
    validate_files(folder.files)
    for path, text in folder.files.items():
        name = schema_name_for_path(path)
        if name is not None:
            schema = Draft202012Validator(json.loads(folder.files[schema_document(name)]))
            assert [error.message for error in schema.iter_errors(json.loads(text))] == [], path


@pytest.mark.parametrize("through", PARTIAL)
def test_a_partial_folder_cannot_be_imported(through: str) -> None:
    verified = verify_folder(partial_folder(through).files)
    pending = STAGES[STAGES.index(through) + 1]

    with pytest.raises(KnowledgeArchiveError) as planned:
        plan(verified)
    with pytest.raises(ProjectImportError) as checked:
        complete_folder(verified)

    assert (planned.value.code, planned.value.detail) == ("FOLDER_INCOMPLETE", pending)
    assert (checked.value.code, checked.value.detail) == ("FOLDER_INCOMPLETE", pending)


def test_a_partial_archive_never_reaches_the_database() -> None:
    opened: list[bool] = []

    def session_factory():
        opened.append(True)
        raise AssertionError("the import must not reach the database")

    service = ProjectImportService(session_factory=session_factory, clock=lambda: IMPORTED_AT)
    content = folder_archive(partial_folder("brief")).content

    with pytest.raises(ProjectImportError) as caught:
        asyncio.run(service.import_archive(owner_user_id=NEW_OWNER, content=content))

    assert (caught.value.code, caught.value.detail) == ("FOLDER_INCOMPLETE", "team")
    assert opened == []


def test_a_complete_folder_with_a_development_state_imports_without_it() -> None:
    folder = build_knowledge_folder(
        real_sources(state=state_sources()), version_number=1, created_at=PUBLISHED_AT
    )
    verified = verify_folder(folder.files)

    imported = plan(verified)

    assert complete_folder(verified) is verified
    assert imported.origin.schema_version == 3
    assert imported.project_id == NEW_PROJECT
    assert set(verified.documents) == set(STAGES)


def test_a_folder_of_schema_two_still_verifies_and_imports() -> None:
    current = build_knowledge_folder(real_sources(), version_number=2, created_at=PUBLISHED_AT)
    older = schema_two_files(current.files)

    verified = verify_folder(older)
    imported = plan(verified)

    manifest = json.loads(older[KNOWLEDGE_MANIFEST])
    assert verified.schema_version == 2
    assert verified.present_stages == STAGES
    assert verified.complete is True
    assert "progress" not in manifest and "state" not in manifest
    assert STATE_DOCUMENT not in older and FEEDBACK_CHANGES not in older
    assert FEEDBACK_TESTS not in older and "tests" not in manifest["feedback"]
    assert '"urn:orchestwin:knowledge-folder:2:manifest"' in older[schema_document("manifest")]
    assert json.loads(older["twins/feedback/reviews.json"])["schema_version"] == 2
    assert "Critiques on the code changes" not in older["twins/feedback/feedback.md"]
    assert imported.origin.schema_version == 2
    assert verified.documents["design"] == json.loads(current.files[stage_document("design")])
    assert read_verified_folder(archive_of(older)).schema_version == 2


def test_a_folder_of_schema_two_without_a_stage_is_invalid() -> None:
    older = schema_two_files(
        build_knowledge_folder(real_sources(), version_number=1, created_at=PUBLISHED_AT).files
    )
    trimmed = {path: text for path, text in older.items() if not path.startswith("design/")}

    def without_design(manifest: dict[str, object]) -> None:
        del manifest["stages"]["design"]
        del manifest["views"]["design"]

    refused = refusal(resealed(trimmed, without_design))

    assert (refused.code, refused.detail) == ("FOLDER_DOCUMENT_INVALID", KNOWLEDGE_MANIFEST)


@pytest.mark.parametrize("version", [1, 4, "3", None, True])
def test_folders_of_other_schema_versions_are_not_supported(version: object) -> None:
    files = partial_folder("brief").files

    refused = refusal(resealed(files, lambda manifest: manifest.update(schema_version=version)))

    assert refused.code == "FOLDER_SCHEMA_UNSUPPORTED"


def test_a_folder_of_schema_three_needs_its_progress_and_its_state() -> None:
    files = partial_folder("team").files

    for key in ("progress", "state"):
        refused = refusal(resealed(files, lambda manifest, key=key: manifest.pop(key)))
        assert (refused.code, refused.detail) == ("FOLDER_DOCUMENT_INVALID", KNOWLEDGE_MANIFEST)


@pytest.mark.parametrize("path", [STATE_DOCUMENT, STATE_TEXT, FEEDBACK_CHANGES])
def test_a_folder_of_schema_three_without_a_state_file_is_refused(path: str) -> None:
    files = {name: text for name, text in partial_folder("team").files.items() if name != path}

    refused = refusal(resealed(files))

    assert (refused.code, refused.detail) == ("FOLDER_DOCUMENT_MISSING", path)


@pytest.mark.parametrize("path", [STATE_DOCUMENT, FEEDBACK_CHANGES])
def test_a_state_document_of_another_project_is_refused(path: str) -> None:
    files = dict(partial_folder("team").files)
    document = json.loads(files[path])
    document["project_id"] = "99999999-9999-4999-8999-999999999999"
    files[path] = json_text(document)

    refused = refusal(resealed(files))

    assert (refused.code, refused.detail) == ("FOLDER_TAMPERED", path)


def test_a_stage_document_of_a_stage_that_is_not_approved_is_refused() -> None:
    complete = build_knowledge_folder(real_sources(), version_number=1, created_at=PUBLISHED_AT)
    files = {**partial_folder("brief").files, "team/team.json": complete.files["team/team.json"]}

    refused = refusal(resealed(files))

    assert (refused.code, refused.detail) == ("FOLDER_TAMPERED", "team/team.json")


def test_a_manifest_that_skips_a_stage_is_invalid() -> None:
    files = partial_folder("twins").files

    refused = refusal(resealed(files, lambda manifest: manifest["stages"].pop("team")))

    assert (refused.code, refused.detail) == (
        "FOLDER_DOCUMENT_INVALID",
        f"{KNOWLEDGE_MANIFEST}: stages",
    )


def test_the_project_of_a_partial_folder_is_the_project_of_its_documents() -> None:
    verified = verify_folder(partial_folder("brief").files)

    assert verified.project_id == str(REAL_PROJECT_ID)
    assert verified.documents["brief"]["project_id"] == str(REAL_PROJECT_ID)


@pytest.mark.parametrize("through", [*PARTIAL, "design"])
def test_a_folder_published_before_the_acceptance_tests_still_verifies(through: str) -> None:
    current = partial_folder(through, state=state_sources())
    earlier = files_before_tests(current.files)

    verified = read_verified_folder(archive_of(earlier))

    manifest = json.loads(earlier[KNOWLEDGE_MANIFEST])
    assert verified.schema_version == 3
    assert verified.present_stages == STAGES[: STAGES.index(through) + 1]
    assert "tests" not in manifest["feedback"] and "test_runs" not in manifest["feedback"]
    assert "tests" not in manifest["schemas"]
    assert FEEDBACK_TESTS not in earlier and schema_document("tests") not in earlier
    assert FEEDBACK_LEARNING not in earlier and "learned" not in manifest["feedback"]
    assert "## Verifica dei criteri" not in earlier[STATE_TEXT]
    assert "Critiques on the acceptance tests" not in earlier.get(FEEDBACK_TEXT, "")
    assert verified.content_hash == folder_content_hash(earlier) != current.content_hash


def test_a_complete_folder_published_before_the_acceptance_tests_still_imports() -> None:
    earlier = files_before_tests(partial_folder("design", state=state_sources()).files)

    imported = plan(verify_folder(earlier))

    assert imported.origin.schema_version == 3
    assert imported.project_id == NEW_PROJECT


def test_a_complete_folder_with_test_runs_imports_the_same_project_as_without_them() -> None:
    folder = partial_folder("design", state=state_sources())

    tested = plan(verify_folder(folder.files))
    untested = plan(verify_folder(files_before_tests(folder.files)))

    assert json.loads(folder.files[FEEDBACK_TESTS])["runs"]
    assert tested.origin.package_content_hash != untested.origin.package_content_hash
    assert replace(tested, origin=untested.origin) == untested


def test_a_folder_that_announces_the_test_runs_needs_their_document() -> None:
    files = dict(partial_folder("team").files)
    del files[FEEDBACK_TESTS]

    refused = refusal(resealed(files))

    assert (refused.code, refused.detail) == ("FOLDER_DOCUMENT_MISSING", FEEDBACK_TESTS)


def test_a_test_document_of_another_project_is_refused() -> None:
    files = dict(partial_folder("design", state=state_sources()).files)
    files[FEEDBACK_TESTS] = json_text(
        {**json.loads(files[FEEDBACK_TESTS]), "project_id": OTHER_PROJECT}
    )

    refused = refusal(resealed(files))

    assert (refused.code, refused.detail) == ("FOLDER_TAMPERED", FEEDBACK_TESTS)


@pytest.mark.parametrize(
    ("keys", "value", "location"),
    [
        (("results", 0, "browser"), "safari", "runs[0].results[0].browser"),
        (("summary", "passed"), -1, "runs[0].summary.passed"),
        (
            ("results", 1, "steps", 1, "screenshot"),
            "../outside.png",
            "runs[0].results[1].steps[1].screenshot",
        ),
        (
            ("critiques", 0, "findings", 0, "about", "criterion"),
            "REQ-003",
            "runs[0].critiques[0].findings[0].about.criterion",
        ),
    ],
)
def test_a_test_document_that_breaks_its_schema_is_refused(
    keys: tuple[str | int, ...], value: object, location: str
) -> None:
    files = dict(partial_folder("design", state=state_sources()).files)
    document = json.loads(files[FEEDBACK_TESTS])
    target = document["runs"][0]
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    files[FEEDBACK_TESTS] = json_text(document)

    refused = refusal(resealed(files))

    assert (refused.code, refused.detail) == ("FOLDER_DOCUMENT_INVALID", f"tests: {location}")


def test_a_test_document_that_the_manifest_does_not_announce_is_refused() -> None:
    def unannounced(manifest: dict[str, object]) -> None:
        del manifest["feedback"]["tests"]
        del manifest["feedback"]["test_runs"]

    refused = refusal(resealed(partial_folder("team").files, unannounced))

    assert (refused.code, refused.detail) == ("FOLDER_TAMPERED", FEEDBACK_TESTS)


@pytest.mark.parametrize("key", ["tests", "test_runs"])
def test_the_manifest_announces_the_test_runs_together_with_their_count(key: str) -> None:
    files = partial_folder("team").files

    refused = refusal(resealed(files, lambda manifest: manifest["feedback"].pop(key)))

    assert (refused.code, refused.detail) == (
        "FOLDER_DOCUMENT_INVALID",
        f"{KNOWLEDGE_MANIFEST}: feedback",
    )


@pytest.mark.parametrize("through", STAGES)
def test_a_folder_published_before_the_twins_learned_still_verifies(through: str) -> None:
    current = partial_folder(through, state=development_sources())
    earlier = files_before_learning(current.files)

    verified = read_verified_folder(archive_of(earlier))

    manifest = json.loads(earlier[KNOWLEDGE_MANIFEST])
    state = json.loads(earlier[STATE_DOCUMENT])
    assert verified.schema_version == 3
    assert verified.present_stages == STAGES[: STAGES.index(through) + 1]
    assert "stale_reviews" not in manifest["state"]
    assert "learned" not in manifest["feedback"]
    assert "learned_observations" not in manifest["feedback"]
    assert "learning" not in manifest["schemas"]
    assert manifest["feedback"]["tests"] == FEEDBACK_TESTS
    assert FEEDBACK_LEARNING not in earlier and schema_document("learning") not in earlier
    assert [task["code"] for task in state["tasks"]] == ["TSK-001", "TSK-002"]
    assert all(set(task) == set(state_sources().tasks[0]) for task in state["tasks"])
    assert all(set(task["about"]) == {"requirements", "screens"} for task in state["tasks"])
    assert all(
        set(change["review"]) == {"run_id", "reviewed_at", "verdict", "summary"}
        for change in state["changes"]
        if change["review"] is not None
    )
    assert "## Cosa hanno imparato i twin" not in earlier[STATE_TEXT]
    assert "## Learned during development" not in earlier.get(FEEDBACK_TEXT, "")
    assert verified.content_hash == folder_content_hash(earlier) != current.content_hash


def test_a_complete_folder_published_before_the_twins_learned_still_imports() -> None:
    folder = partial_folder("design", state=development_sources())

    learned = plan(verify_folder(folder.files))
    earlier = plan(verify_folder(files_before_learning(folder.files)))

    assert json.loads(folder.files[FEEDBACK_LEARNING])["twins"][0]["observations"]
    assert learned.origin.package_content_hash != earlier.origin.package_content_hash
    assert replace(learned, origin=earlier.origin) == earlier
    assert "learning" not in verify_folder(folder.files).documents


def test_a_folder_that_announces_what_the_twins_learned_needs_its_document() -> None:
    files = dict(partial_folder("twins", state=development_sources()).files)
    del files[FEEDBACK_LEARNING]

    refused = refusal(resealed(files))

    assert (refused.code, refused.detail) == ("FOLDER_DOCUMENT_MISSING", FEEDBACK_LEARNING)


def test_a_learning_document_of_another_project_is_refused() -> None:
    files = dict(partial_folder("design", state=development_sources()).files)
    files[FEEDBACK_LEARNING] = json_text(
        {**json.loads(files[FEEDBACK_LEARNING]), "project_id": OTHER_PROJECT}
    )

    refused = refusal(resealed(files))

    assert (refused.code, refused.detail) == ("FOLDER_TAMPERED", FEEDBACK_LEARNING)


@pytest.mark.parametrize(
    ("keys", "value", "location"),
    [
        (("label",), "1", "twins[0].label"),
        (("development_version_number",), -1, "twins[0].development_version_number"),
        (("observations", 0, "code"), "OBS-1", "twins[0].observations[0].code"),
        (("observations", 0, "source"), "MODEL", "twins[0].observations[0].source"),
        (("observations", 1, "statement"), "", "twins[0].observations[1].statement"),
        (("retired", 0, "reason"), "x" * 301, "twins[0].retired[0].reason"),
    ],
)
def test_a_learning_document_that_breaks_its_schema_is_refused(
    keys: tuple[str | int, ...], value: object, location: str
) -> None:
    files = dict(partial_folder("design", state=development_sources()).files)
    document = json.loads(files[FEEDBACK_LEARNING])
    target = document["twins"][0]
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    files[FEEDBACK_LEARNING] = json_text(document)

    refused = refusal(resealed(files))

    assert (refused.code, refused.detail) == ("FOLDER_DOCUMENT_INVALID", f"learning: {location}")


def test_a_learning_document_that_the_manifest_does_not_announce_is_refused() -> None:
    def unannounced(manifest: dict[str, object]) -> None:
        del manifest["feedback"]["learned"]
        del manifest["feedback"]["learned_observations"]

    refused = refusal(resealed(partial_folder("twins").files, unannounced))

    assert (refused.code, refused.detail) == ("FOLDER_TAMPERED", FEEDBACK_LEARNING)


def test_a_learning_document_in_a_folder_without_the_twins_is_refused() -> None:
    files = {
        **partial_folder("team").files,
        FEEDBACK_LEARNING: partial_folder("twins").files[FEEDBACK_LEARNING],
    }

    refused = refusal(resealed(files))

    assert (refused.code, refused.detail) == ("FOLDER_TAMPERED", FEEDBACK_LEARNING)


@pytest.mark.parametrize("key", ["learned", "learned_observations"])
def test_the_manifest_announces_what_the_twins_learned_together_with_its_count(key: str) -> None:
    files = partial_folder("twins").files

    refused = refusal(resealed(files, lambda manifest: manifest["feedback"].pop(key)))

    assert (refused.code, refused.detail) == (
        "FOLDER_DOCUMENT_INVALID",
        f"{KNOWLEDGE_MANIFEST}: feedback",
    )


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("state", "stale_reviews", -1),
        ("state", "stale_reviews", None),
        ("feedback", "learned", "twins/feedback/learning.json"),
        ("feedback", "learned_observations", None),
    ],
)
def test_the_new_manifest_keys_are_checked_when_they_are_present(
    section: str, key: str, value: object
) -> None:
    files = partial_folder("twins").files

    refused = refusal(resealed(files, lambda manifest: manifest[section].update({key: value})))

    assert (refused.code, refused.detail) == (
        "FOLDER_DOCUMENT_INVALID",
        f"{KNOWLEDGE_MANIFEST}: {section}.{key}",
    )
