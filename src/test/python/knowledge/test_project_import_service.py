from __future__ import annotations

import asyncio
import hashlib
import io
import json
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from functools import cache
from uuid import UUID, uuid4

import pytest

from orchestwin.knowledge.archive import KnowledgeArchiveError, VerifiedFolder, read_verified_folder
from orchestwin.knowledge.folder import build_knowledge_folder, folder_archive, json_text
from orchestwin.knowledge.layout import KNOWLEDGE_MANIFEST, STAGES
from orchestwin.knowledge.project_import_service import (
    ProjectImportError,
    ProjectImportService,
    archive_failure,
    import_display_name,
    import_record,
    import_source_name,
    imported_project_mode,
    imported_stage_versions,
    planned_import,
    verified_archive,
)
from orchestwin.projects.domain import ProjectMode

from .knowledge_fixtures import PUBLISHED_AT, REAL_PROJECT_ID, real_sources

NEW_PROJECT = UUID("11111111-1111-4111-8111-111111111111")
NEW_BRIEF = UUID("22222222-2222-4222-8222-222222222222")
NEW_OWNER = UUID("33333333-3333-4333-8333-333333333333")
RECORD_ID = UUID("44444444-4444-4444-8444-444444444444")
IMPORTED_AT = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
FOLDER_NAME = "Lista ospiti workshop"


@cache
def archive_content() -> bytes:
    folder = build_knowledge_folder(real_sources(), version_number=1, created_at=PUBLISHED_AT)
    return folder_archive(folder).content


def verified() -> VerifiedFolder:
    return read_verified_folder(archive_content())


def repacked(changes: dict[str, str]) -> bytes:
    with zipfile.ZipFile(io.BytesIO(archive_content())) as source:
        files = {name: source.read(name).decode("utf-8") for name in source.namelist()}
    files.update(changes)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for name, text in files.items():
            target.writestr(name, text)
    return buffer.getvalue()


def renamed(folder: VerifiedFolder, name: str) -> VerifiedFolder:
    manifest = json.loads(json.dumps(folder.manifest))
    manifest["project"]["name"] = name
    return VerifiedFolder(manifest=manifest, documents=folder.documents, files=folder.files)


def manifest_named(name: str) -> bytes:
    manifest = json.loads(json.dumps(verified().manifest))
    manifest["project"]["name"] = name
    return repacked({KNOWLEDGE_MANIFEST: json_text(manifest)})


def edited(folder: VerifiedFolder, change) -> VerifiedFolder:
    documents = json.loads(json.dumps(folder.documents))
    change(documents)
    return VerifiedFolder(manifest=folder.manifest, documents=documents, files=folder.files)


def plan(folder: VerifiedFolder | None = None, **changes):
    values = {
        "project_id": NEW_PROJECT,
        "brief_version_id": NEW_BRIEF,
        "owner_user_id": NEW_OWNER,
        "created_at": IMPORTED_AT,
    }
    values.update(changes)
    return planned_import(verified() if folder is None else folder, **values)


def failure(action) -> ProjectImportError:
    with pytest.raises(ProjectImportError) as error:
        action()
    return error.value


def test_given_display_name_is_normalized_and_preferred_to_the_folder_name() -> None:
    assert import_display_name("  Nuova   lista\tospiti \n", FOLDER_NAME) == "Nuova lista ospiti"
    assert import_display_name("x" * 120, FOLDER_NAME) == "x" * 120


@pytest.mark.parametrize("given", [None, "", "   \n\t"])
def test_missing_or_blank_display_name_falls_back_to_the_folder_name(given: str | None) -> None:
    assert import_display_name(given, FOLDER_NAME) == FOLDER_NAME
    assert import_display_name(given, "  Lista   ospiti  ") == "Lista ospiti"


def test_long_folder_name_is_cut_at_the_limit_without_a_trailing_space() -> None:
    spaced = import_display_name(None, "a" * 119 + " " + "b" * 30)
    solid = import_display_name(None, "c" * 150)

    assert spaced == "a" * 119
    assert solid == "c" * 120


def test_names_that_break_the_project_rules_are_rejected() -> None:
    too_long = failure(lambda: import_display_name("x" * 121, FOLDER_NAME))
    unnamed = failure(lambda: import_display_name(None, " \t "))

    assert (too_long.code, too_long.detail) == ("PROJECT_NAME_INVALID", "display_name")
    assert (unnamed.code, unnamed.detail) == ("PROJECT_NAME_INVALID", "display_name")
    assert import_display_name("Progetto importato", " \t ") == "Progetto importato"


def test_project_mode_follows_the_imported_team_proposal() -> None:
    folder = verified()

    def mode(value):
        def change(documents) -> None:
            documents["team"]["proposal"]["project_mode"] = value

        return edited(folder, change)

    def missing(documents) -> None:
        del documents["team"]["proposal"]["project_mode"]

    assert imported_project_mode(folder) is ProjectMode.GREENFIELD_GENERATION
    assert imported_project_mode(mode("BROWNFIELD_ASSESSMENT")) is ProjectMode.BROWNFIELD_ASSESSMENT
    for broken in (mode("LEGACY_MIGRATION"), mode(None), edited(folder, missing)):
        error = failure(lambda broken=broken: imported_project_mode(broken))
        assert (error.code, error.detail) == ("FOLDER_DOCUMENT_INVALID", "team: project_mode")


def test_archive_failures_keep_their_code_and_detail() -> None:
    empty = failure(lambda: verified_archive(b""))
    tampered = failure(lambda: verified_archive(repacked({"brief/brief.md": "Altro testo\n"})))
    unsupported = archive_failure(KnowledgeArchiveError("FOLDER_SCHEMA_UNSUPPORTED"))

    assert (empty.code, empty.detail) == ("FOLDER_ARCHIVE_INVALID", None)
    assert (tampered.code, tampered.detail) == ("FOLDER_TAMPERED", "brief/brief.md")
    assert (unsupported.code, unsupported.detail) == ("FOLDER_SCHEMA_UNSUPPORTED", None)
    assert str(tampered) == "FOLDER_TAMPERED: brief/brief.md"
    assert verified_archive(archive_content()).manifest == verified().manifest


def test_plan_failures_are_reported_as_folder_errors() -> None:
    folder = verified()

    def foreign_team(documents) -> None:
        documents["team"]["proposal"]["project_id"] = str(uuid4())

    def outdated_team(documents) -> None:
        documents["team"]["proposal"]["brief_version"]["id"] = str(uuid4())

    def renumbered(documents) -> None:
        documents["requirements"]["specification"]["requirements"][0]["code"] = "REQ-999"

    escaped = failure(lambda: plan(edited(folder, foreign_team)))
    inconsistent = failure(lambda: plan(edited(folder, outdated_team)))
    refused = failure(lambda: plan(edited(folder, renumbered)))

    assert escaped.code == "FOLDER_DOCUMENT_INVALID"
    assert isinstance(escaped.__cause__, KnowledgeArchiveError)
    assert isinstance(escaped.__cause__.__cause__, ValueError)
    assert (inconsistent.code, inconsistent.detail) == ("FOLDER_INCONSISTENT", "TEAM_OUTDATED")
    assert refused.code == "FOLDER_DOCUMENT_INVALID"
    assert refused.detail.startswith("requirements: ")
    with pytest.raises(ValueError, match="timezone-aware"):
        plan(folder, created_at=datetime(2026, 9, 28, 9, 0))


@pytest.mark.parametrize("name", ["", "n" * 201])
def test_folder_whose_name_cannot_be_recorded_is_refused(name: str) -> None:
    error = failure(lambda: import_source_name(renamed(verified(), name)))

    assert (error.code, error.detail) == (
        "FOLDER_DOCUMENT_INVALID",
        "orchestwin.json: project.name",
    )
    assert import_source_name(renamed(verified(), "n" * 200)) == "n" * 200
    assert import_source_name(renamed(verified(), " ")) == " "


def test_import_record_names_the_origin_and_every_stage_as_version_one() -> None:
    content = archive_content()
    imported = plan()

    record = import_record(
        imported,
        record_id=RECORD_ID,
        owner_user_id=NEW_OWNER,
        content=content,
        imported_at=IMPORTED_AT,
    )
    snapshot = record.to_snapshot()

    assert record.id == RECORD_ID
    assert record.project_id == NEW_PROJECT
    assert record.owner_user_id == NEW_OWNER
    assert record.origin == imported.origin
    assert record.source_project_id == REAL_PROJECT_ID
    assert record.source_project_name == FOLDER_NAME
    assert record.package_version == 1
    assert record.archive_hash == hashlib.sha256(content).hexdigest()
    assert record.archive_size == len(content)
    assert record.imported_at == IMPORTED_AT
    assert record.stage_versions == imported_stage_versions(imported)
    assert record.stage_versions == {
        "brief": {
            "version_id": str(NEW_BRIEF),
            "version_number": 1,
            "content_hash": imported.brief.content_hash,
        },
        "team": {
            "version_id": str(imported.team.id),
            "version_number": 1,
            "content_hash": imported.team.content_hash,
        },
        "twins": {
            "version_id": str(imported.modeling.id),
            "version_number": 1,
            "content_hash": imported.modeling.content_hash,
        },
        "requirements": {
            "version_id": str(imported.requirements.id),
            "version_number": 1,
            "content_hash": imported.requirements.content_hash,
        },
        "design": {
            "version_id": str(imported.design.id),
            "version_number": 1,
            "content_hash": imported.design.content_hash,
        },
    }
    assert list(snapshot["stage_versions"]) == list(STAGES)
    assert snapshot["source_project_id"] == str(REAL_PROJECT_ID)
    assert snapshot["imported_at"] == "2026-09-28T09:00:00+00:00"
    assert json.loads(json.dumps(snapshot)) == snapshot


def test_record_needs_every_stage_and_an_aware_time() -> None:
    record = import_record(
        plan(),
        record_id=RECORD_ID,
        owner_user_id=NEW_OWNER,
        content=archive_content(),
        imported_at=IMPORTED_AT,
    )
    partial = {stage: entry for stage, entry in record.stage_versions.items() if stage != "design"}
    unnumbered = {
        **record.stage_versions,
        "design": {"version_id": str(uuid4()), "content_hash": "0" * 64},
    }

    for changes in (
        {"stage_versions": partial},
        {"stage_versions": unnumbered},
        {"imported_at": datetime(2026, 9, 28, 9, 0)},
    ):
        with pytest.raises(ValueError):
            replace(record, **changes)


def test_refused_archives_names_and_clocks_never_open_a_database_session() -> None:
    opened: list[bool] = []

    def session_factory():
        opened.append(True)
        raise AssertionError("the import must not reach the database")

    def importing(content: bytes, display_name: str | None = None, clock=lambda: IMPORTED_AT):
        service = ProjectImportService(session_factory=session_factory, clock=clock)
        return asyncio.run(
            service.import_archive(
                owner_user_id=NEW_OWNER, content=content, display_name=display_name
            )
        )

    empty = failure(lambda: importing(b""))
    tampered = failure(lambda: importing(repacked({"design/design.md": "Altro testo\n"})))
    too_long = failure(lambda: importing(archive_content(), "x" * 121))
    unrecordable = failure(lambda: importing(manifest_named("n" * 201), "x" * 121))
    unnamed = failure(lambda: importing(manifest_named(" \t "), None))
    with pytest.raises(ValueError, match="timezone-aware"):
        importing(archive_content(), clock=lambda: datetime(2026, 9, 28, 9, 0))

    assert empty.code == "FOLDER_ARCHIVE_INVALID"
    assert (tampered.code, tampered.detail) == ("FOLDER_TAMPERED", "design/design.md")
    assert (too_long.code, too_long.detail) == ("PROJECT_NAME_INVALID", "display_name")
    assert (unrecordable.code, unrecordable.detail) == (
        "FOLDER_DOCUMENT_INVALID",
        "orchestwin.json: project.name",
    )
    assert (unnamed.code, unnamed.detail) == ("PROJECT_NAME_INVALID", "display_name")
    assert opened == []
