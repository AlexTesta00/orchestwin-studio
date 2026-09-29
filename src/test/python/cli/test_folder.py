from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from orchestwin.cli import folder as module
from orchestwin.cli.errors import CliError
from orchestwin.cli.folder import (
    FOLDER_STAGES,
    INDEX_NAME,
    MANIFEST_NAME,
    StateSummary,
    pack,
    read_files,
    summary,
    unpack,
    verify,
    verify_archive,
)
from orchestwin.knowledge.folder import KnowledgeFolder, build_knowledge_folder, folder_archive
from orchestwin.knowledge.layout import KNOWLEDGE_INDEX, KNOWLEDGE_MANIFEST, STAGES

from ..knowledge.knowledge_fixtures import (
    ALIGNED_COMMIT,
    PUBLISHED_AT,
    partial_sources,
    real_sources,
    schema_two_files,
    state_sources,
)


@pytest.fixture(scope="module")
def built() -> KnowledgeFolder:
    return build_knowledge_folder(real_sources(), version_number=3, created_at=PUBLISHED_AT)


@pytest.fixture(scope="module")
def archive(built: KnowledgeFolder) -> bytes:
    return folder_archive(built).content


def unpacked(tmp_path: Path, archive: bytes) -> Path:
    target = tmp_path / "tip" / "orchestwin"
    unpack(archive, target)
    return target


def failure(action: object) -> CliError:
    with pytest.raises(CliError) as caught:
        action()
    return caught.value


def zipped(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as written:
        for name, content in files.items():
            written.writestr(name, content)
    return buffer.getvalue()


def test_the_names_match_the_layout_of_the_studio() -> None:
    assert MANIFEST_NAME == KNOWLEDGE_MANIFEST
    assert INDEX_NAME == KNOWLEDGE_INDEX
    assert FOLDER_STAGES == STAGES


def test_unpack_verify_and_pack_go_round(
    tmp_path: Path, built: KnowledgeFolder, archive: bytes
) -> None:
    target = unpacked(tmp_path, archive)

    for name, content in built.files.items():
        assert target.joinpath(*name.split("/")).read_bytes() == content.encode("utf-8")
    assert (target / ".gitattributes").read_bytes() == b"* -text\n"
    assert read_files(target) == built.files
    assert verify(target).content_hash == built.content_hash
    repacked = verify_archive(pack(target))
    assert dict(repacked.files) == built.files
    assert pack(target) == pack(target)
    assert sorted(path.name for path in target.parent.iterdir()) == ["orchestwin"]


def test_the_summary_reads_only_the_manifest(
    tmp_path: Path, built: KnowledgeFolder, archive: bytes
) -> None:
    target = unpacked(tmp_path, archive)
    (target / "brief" / "brief.md").write_text("changed by hand", encoding="utf-8")

    found = summary(target)

    assert found is not None
    assert found.project_name == "Lista ospiti workshop"
    assert found.version_number == 3
    assert found.content_hash == built.content_hash
    assert found.file_count == len(built.files)
    assert [stage.stage for stage in found.stages] == list(STAGES)
    assert all(stage.gate_status == "APPROVED" for stage in found.stages)
    assert found.stage("design") is not None
    assert found.stage("package") is None
    assert (found.schema_version, found.progress) == (3, FOLDER_STAGES)
    assert (found.pending, found.complete) == (None, True)
    assert found.state == StateSummary(
        changes=0, pending_changes=0, aligned_commit=None, open_tasks=0
    )


def test_the_summary_of_a_partial_folder_reads_the_progress_and_the_state(
    tmp_path: Path,
) -> None:
    partial = build_knowledge_folder(
        partial_sources("twins", state=state_sources()), version_number=2, created_at=PUBLISHED_AT
    )
    target = unpacked(tmp_path, folder_archive(partial).content)

    found = summary(target)

    assert found is not None
    assert found.schema_version == 3
    assert found.progress == ("brief", "team", "twins")
    assert (found.pending, found.complete) == ("requirements", False)
    assert found.state == StateSummary(
        changes=2, pending_changes=1, aligned_commit=ALIGNED_COMMIT, open_tasks=1
    )
    assert found.stage("twins") is not None and found.stage("twins").version_number == 1
    assert found.stage("requirements").version_number is None
    assert found.file_count == len(partial.files)


def test_a_schema_2_manifest_holds_the_five_stages_and_no_state(
    tmp_path: Path, built: KnowledgeFolder
) -> None:
    target = tmp_path / "older"
    for name, content in schema_two_files(built.files).items():
        path = target.joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))

    found = summary(target)

    assert found is not None
    assert found.schema_version == 2
    assert found.progress == FOLDER_STAGES
    assert (found.pending, found.complete, found.state) == (None, True, None)


def test_a_schema_3_manifest_without_its_progress_cannot_be_read(tmp_path: Path) -> None:
    manifest = {
        "schema_version": 3,
        "package": {"version_number": 1, "content_hash": "c"},
        "project": {"id": "p", "name": "n"},
        "stages": {},
        "progress": {"approved": ["brief", "anything"], "pending": None, "complete": True},
        "files": {},
    }
    (tmp_path / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

    error = failure(lambda: summary(tmp_path))

    assert (error.code, error.values["code"]) == ("FOLDER_NOT_VERIFIED", "FOLDER_DOCUMENT_INVALID")


def test_the_summary_of_a_missing_or_broken_manifest(tmp_path: Path) -> None:
    assert summary(tmp_path / "missing") is None
    assert summary(tmp_path) is None
    (tmp_path / MANIFEST_NAME).write_text("{", encoding="utf-8")

    error = failure(lambda: summary(tmp_path))

    assert error.code == "FOLDER_NOT_VERIFIED"
    assert error.values["code"] == "FOLDER_DOCUMENT_INVALID"
    assert error.values["path"] == MANIFEST_NAME


def test_a_new_version_replaces_the_old_folder(tmp_path: Path, archive: bytes) -> None:
    target = unpacked(tmp_path, archive)
    (target / "notes.txt").write_text("mine", encoding="utf-8")

    unpack(archive, target)

    assert not (target / "notes.txt").exists()
    assert sorted(path.name for path in target.parent.iterdir()) == ["orchestwin"]
    verify(target)


def test_a_tampered_file_is_named(tmp_path: Path, archive: bytes) -> None:
    target = unpacked(tmp_path, archive)
    (target / "design" / "design.md").write_text("tampered", encoding="utf-8")

    error = failure(lambda: verify(target))

    assert (error.code, error.status) == ("FOLDER_NOT_VERIFIED", 7)
    assert error.values["code"] == "FOLDER_TAMPERED"
    assert error.values["path"] == "design/design.md"
    assert "reason" not in error.values


def test_an_extra_file_is_named(tmp_path: Path, archive: bytes) -> None:
    target = unpacked(tmp_path, archive)
    (target / "extra.md").write_text("added", encoding="utf-8")

    error = failure(lambda: verify(target))

    assert error.values["code"] == "FOLDER_TAMPERED"
    assert error.values["path"] == "extra.md"


def test_windows_line_endings_are_recognised(tmp_path: Path, archive: bytes) -> None:
    target = unpacked(tmp_path, archive)
    for name in ("brief/brief.md", "brief/brief.json"):
        path = target.joinpath(*name.split("/"))
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

    error = failure(lambda: verify(target))

    assert error.values["reason"] == "LINE_ENDINGS"
    assert error.values["path"] in {"brief/brief.md", "brief/brief.json"}
    assert error.values["folder"] == str(target)


def test_line_endings_and_a_real_change_are_not_confused(tmp_path: Path, archive: bytes) -> None:
    target = unpacked(tmp_path, archive)
    path = target / "brief" / "brief.md"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n") + b"more\r\n")

    error = failure(lambda: verify(target))

    assert "reason" not in error.values


def test_a_missing_folder_and_a_file_that_is_not_text(tmp_path: Path) -> None:
    assert failure(lambda: verify(tmp_path / "nothing")).values["code"] == "FOLDER_MISSING"
    (tmp_path / "binary.bin").write_bytes(b"\xff\xfe\x00")

    error = failure(lambda: read_files(tmp_path))

    assert error.values["code"] == "FOLDER_DOCUMENT_INVALID"
    assert error.values["path"] == "binary.bin"


def test_an_archive_that_leaves_the_folder_writes_nothing(
    tmp_path: Path, built: KnowledgeFolder
) -> None:
    files = {name: content.encode("utf-8") for name, content in built.files.items()}
    files["../outside.txt"] = b"escape"
    target = tmp_path / "tip" / "orchestwin"

    error = failure(lambda: unpack(zipped(files), target))

    assert error.code == "FOLDER_NOT_VERIFIED"
    assert error.values["code"] == "FOLDER_ARCHIVE_INVALID"
    assert not (tmp_path / "tip" / "outside.txt").exists()
    assert not (tmp_path / "outside.txt").exists()
    assert not target.exists()


def test_an_archive_that_is_not_a_zip(tmp_path: Path) -> None:
    error = failure(lambda: unpack(b"not a zip", tmp_path / "orchestwin"))

    assert error.values["code"] == "FOLDER_ARCHIVE_INVALID"
    assert not (tmp_path / "orchestwin").exists()


def test_a_failed_swap_puts_the_old_folder_back(
    tmp_path: Path, archive: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = unpacked(tmp_path, archive)
    (target / "notes.txt").write_text("mine", encoding="utf-8")
    renames: list[tuple[str, str]] = []
    original = module._rename

    def fragile(source: Path, destination: Path) -> None:
        renames.append((source.name, destination.name))
        if len(renames) == 2:
            raise PermissionError(13, "in use", str(destination / "design" / "mockup.html"))
        original(source, destination)

    monkeypatch.setattr(module, "_rename", fragile)

    error = failure(lambda: unpack(archive, target))

    assert error.code == "FOLDER_SWAP_FAILED"
    assert error.values["folder"] == str(target)
    assert error.values["path"].endswith("mockup.html")
    assert (target / "notes.txt").read_text(encoding="utf-8") == "mine"
    assert sorted(path.name for path in target.parent.iterdir()) == ["orchestwin"]
    assert len(renames) == 3


def test_a_folder_that_cannot_be_moved_is_left_untouched(
    tmp_path: Path, archive: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = unpacked(tmp_path, archive)
    (target / "notes.txt").write_text("mine", encoding="utf-8")

    def locked(source: Path, destination: Path) -> None:
        raise PermissionError(13, "in use", str(source))

    monkeypatch.setattr(module, "_rename", locked)

    error = failure(lambda: unpack(archive, target))

    assert error.code == "FOLDER_SWAP_FAILED"
    assert (target / "notes.txt").exists()
    assert sorted(path.name for path in target.parent.iterdir()) == ["orchestwin"]
