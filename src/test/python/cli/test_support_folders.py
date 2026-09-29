from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime

import pytest

from orchestwin.knowledge.archive import KnowledgeArchiveError, read_verified_folder, verify_folder
from orchestwin.knowledge.layout import KNOWLEDGE_MANIFEST, STAGES
from orchestwin.knowledge.state import ProjectStateSources
from src.test.python.knowledge.knowledge_fixtures import state_sources

from .support.folders import (
    ARCHIVE_PROJECT_ID,
    DEFAULT_PROJECT_NAME,
    partial_archive,
    state_archive,
    valid_archive,
    valid_files,
    valid_folder,
)

EMPTY_STATE = {
    "document": "state/state.json",
    "text": "state/state.md",
    "changes": 0,
    "pending_changes": 0,
    "aligned_commit": None,
    "open_tasks": 0,
}
STATE_FILES = {"state/state.json", "state/state.md", "twins/feedback/changes.json"}


def entries(content: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return {name: archive.read(name).decode("utf-8") for name in archive.namelist()}


def test_the_archive_passes_the_verification_of_the_studio() -> None:
    verified = read_verified_folder(valid_archive())

    assert verified.project_name == DEFAULT_PROJECT_NAME == "Calcolo mancia"
    assert verified.package_version == 1
    assert verified.project_id == ARCHIVE_PROJECT_ID
    assert set(verified.documents) == set(STAGES)
    assert verified.manifest["schema_version"] == 3
    assert verified.manifest["progress"] == {
        "approved": list(STAGES),
        "pending": None,
        "complete": True,
    }
    assert verified.manifest["state"] == EMPTY_STATE


def test_the_name_and_the_version_reach_the_manifest() -> None:
    verified = read_verified_folder(
        valid_archive(project_name="Lista della spesa", version_number=3)
    )

    assert verified.project_name == "Lista della spesa"
    assert verified.package_version == 3


def test_the_files_are_the_entries_of_the_archive() -> None:
    files = entries(valid_archive())

    assert files == valid_files()
    assert set(files) >= STATE_FILES
    assert verify_folder(files).package_version == 1


def test_the_same_arguments_give_the_same_bytes() -> None:
    assert valid_archive() == valid_archive()
    assert valid_archive(version_number=2) != valid_archive()
    assert partial_archive(through="team") == partial_archive(through="team")
    assert state_archive(state=ProjectStateSources()) == valid_archive()


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


@pytest.mark.parametrize("through", STAGES[:-1])
def test_a_partial_archive_holds_the_stages_up_to_the_named_one(through: str) -> None:
    present = list(STAGES[: STAGES.index(through) + 1])

    content = partial_archive(through=through, project_name="Lista della spesa", version_number=2)
    verified = read_verified_folder(content)
    files = entries(content)

    assert (verified.project_name, verified.package_version, verified.project_id) == (
        "Lista della spesa",
        2,
        ARCHIVE_PROJECT_ID,
    )
    assert verified.manifest["schema_version"] == 3
    assert set(verified.manifest["stages"]) == set(verified.documents) == set(present)
    assert verified.manifest["progress"] == {
        "approved": present,
        "pending": STAGES[len(present)],
        "complete": False,
    }
    assert verified.manifest["state"] == EMPTY_STATE
    assert set(files) >= STATE_FILES
    assert {f"{stage}/{stage}.json" for stage in STAGES} & set(files) == {
        f"{stage}/{stage}.json" for stage in present
    }
    assert not any(name.startswith("design/") for name in files)


def test_a_state_archive_carries_the_development_state() -> None:
    state = state_sources()

    content = state_archive(project_name="Lista della spesa", version_number=4, state=state)
    verified = read_verified_folder(content)
    files = entries(content)
    document = json.loads(files["state/state.json"])
    reviews = json.loads(files["twins/feedback/changes.json"])

    assert verified.manifest["progress"]["complete"] is True
    assert verified.manifest["state"] == {
        **EMPTY_STATE,
        "changes": 2,
        "pending_changes": 1,
        "aligned_commit": state.aligned["commit"],
        "open_tasks": 1,
    }
    assert verified.manifest["feedback"]["change_reviews"] == 1
    assert document["aligned"] == state.aligned
    assert document["changes"] == list(state.changes)
    assert document["tasks"] == list(state.tasks)
    assert reviews["runs"] == list(state.runs)
    assert content != valid_archive(project_name="Lista della spesa", version_number=4)
