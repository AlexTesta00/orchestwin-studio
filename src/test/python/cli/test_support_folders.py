from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime

import pytest

from orchestwin.knowledge.archive import KnowledgeArchiveError, read_verified_folder, verify_folder
from orchestwin.knowledge.layout import KNOWLEDGE_MANIFEST, STAGES

from .support.folders import (
    ARCHIVE_PROJECT_ID,
    DEFAULT_PROJECT_NAME,
    valid_archive,
    valid_files,
    valid_folder,
)


def test_the_archive_passes_the_verification_of_the_studio() -> None:
    verified = read_verified_folder(valid_archive())

    assert verified.project_name == DEFAULT_PROJECT_NAME == "Calcolo mancia"
    assert verified.package_version == 1
    assert verified.project_id == ARCHIVE_PROJECT_ID
    assert set(verified.documents) == set(STAGES)


def test_the_name_and_the_version_reach_the_manifest() -> None:
    verified = read_verified_folder(
        valid_archive(project_name="Lista della spesa", version_number=3)
    )

    assert verified.project_name == "Lista della spesa"
    assert verified.package_version == 3


def test_the_files_are_the_entries_of_the_archive() -> None:
    with zipfile.ZipFile(io.BytesIO(valid_archive())) as archive:
        entries = {name: archive.read(name).decode("utf-8") for name in archive.namelist()}

    assert entries == valid_files()
    assert verify_folder(entries).package_version == 1


def test_the_same_arguments_give_the_same_bytes() -> None:
    assert valid_archive() == valid_archive()
    assert valid_archive(version_number=2) != valid_archive()


def test_versions_share_the_content_hash_and_differ_in_the_manifest() -> None:
    first = valid_folder()
    second = valid_folder(version_number=2)

    assert first.content_hash == second.content_hash
    assert first.files[KNOWLEDGE_MANIFEST] != second.files[KNOWLEDGE_MANIFEST]


def test_the_publication_time_is_written_in_the_manifest() -> None:
    moment = datetime(2026, 9, 29, 10, 30, tzinfo=UTC)

    manifest = json.loads(valid_folder(created_at=moment).files[KNOWLEDGE_MANIFEST])

    assert manifest["package"]["created_at"] == moment.isoformat()


def test_a_changed_file_fails_the_verification() -> None:
    files = valid_files()
    files["brief/brief.md"] = files["brief/brief.md"] + "\n"

    with pytest.raises(KnowledgeArchiveError) as failure:
        verify_folder(files)

    assert failure.value.code == "FOLDER_TAMPERED"
