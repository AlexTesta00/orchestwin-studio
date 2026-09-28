from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest

from orchestwin.knowledge import archive as module
from orchestwin.knowledge.archive import (
    MAX_DOCUMENT_DEPTH,
    KnowledgeArchiveError,
    read_folder_archive,
    read_verified_folder,
    safe_path,
    verify_folder,
    within_depth,
)
from orchestwin.knowledge.folder import build_knowledge_folder, folder_archive, json_text
from orchestwin.knowledge.layout import KNOWLEDGE_INDEX, KNOWLEDGE_MANIFEST

from .knowledge_fixtures import PUBLISHED_AT, REAL_PROJECT_ID, real_sources


def folder():
    return build_knowledge_folder(real_sources(), version_number=3, created_at=PUBLISHED_AT)


def packed(files: dict[str, bytes | str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def failure(action) -> KnowledgeArchiveError:
    with pytest.raises(KnowledgeArchiveError) as error:
        action()
    return error.value


def test_published_archive_reads_back_as_the_same_verified_folder() -> None:
    built = folder()

    verified = read_verified_folder(folder_archive(built).content)

    assert dict(verified.files) == built.files
    assert verified.manifest == built.manifest
    assert verified.project_id == str(REAL_PROJECT_ID)
    assert verified.project_name == "Lista ospiti workshop"
    assert verified.package_version == 3
    assert verified.content_hash == built.content_hash
    assert set(verified.documents) == {"brief", "team", "twins", "requirements", "design"}
    assert verified.documents["design"] == json.loads(built.files["design/design.json"])


@pytest.mark.parametrize(
    ("name", "safe"),
    [
        ("brief/brief.md", True),
        ("twins/ada-3fe4f1ad/twin.json", True),
        ("ORCHESTWIN.md", True),
        ("", False),
        ("/etc/passwd", False),
        ("../outside.md", False),
        ("brief/../../outside.md", False),
        ("brief//brief.md", False),
        ("brief/./brief.md", False),
        ("brief\\brief.md", False),
        ("C:/Users/owner/brief.md", False),
        ("brief/brief.md ", False),
        ("brief/ brief.md", False),
        ("brief/br\0ief.md", False),
        ("a" * 241, False),
    ],
)
def test_only_plain_relative_paths_are_safe(name: str, safe: bool) -> None:
    assert safe_path(name) is safe


@pytest.mark.parametrize("content", [b"", b"not a zip", b"PK\x05\x06" + bytes(18)])
def test_empty_or_broken_archives_are_rejected(content: bytes) -> None:
    assert failure(lambda: read_folder_archive(content)).code == "FOLDER_ARCHIVE_INVALID"


def test_archives_with_unsafe_duplicate_or_binary_entries_are_rejected() -> None:
    unsafe = failure(lambda: read_folder_archive(packed({"../outside.md": "x"})))
    binary = failure(lambda: read_folder_archive(packed({"brief/brief.md": b"\xff\xfe\x00"})))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive, pytest.warns(UserWarning):
        archive.writestr("brief/brief.md", "one")
        archive.writestr("brief/brief.md", "two")
    duplicate = failure(lambda: read_folder_archive(buffer.getvalue()))

    assert (unsafe.code, unsafe.detail) == ("FOLDER_ARCHIVE_INVALID", "../outside.md")
    assert (binary.code, binary.detail) == ("FOLDER_ARCHIVE_INVALID", "brief/brief.md")
    assert (duplicate.code, duplicate.detail) == ("FOLDER_ARCHIVE_INVALID", "duplicate entries")


def test_size_limits_stop_large_archives_and_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    content = packed({"brief/brief.md": "x" * 400, "team/team.md": "y" * 400})

    monkeypatch.setattr(module, "MAX_ARCHIVE_SIZE", len(content) - 1)
    too_big = failure(lambda: read_folder_archive(content))
    monkeypatch.setattr(module, "MAX_ARCHIVE_SIZE", len(content))
    monkeypatch.setattr(module, "MAX_ENTRY_SIZE", 399)
    big_entry = failure(lambda: read_folder_archive(content))
    monkeypatch.setattr(module, "MAX_ENTRY_SIZE", 400)
    monkeypatch.setattr(module, "MAX_FOLDER_SIZE", 799)
    big_folder = failure(lambda: read_folder_archive(content))
    monkeypatch.setattr(module, "MAX_FOLDER_SIZE", 800)
    monkeypatch.setattr(module, "MAX_ARCHIVE_ENTRIES", 1)
    many = failure(lambda: read_folder_archive(content))
    monkeypatch.setattr(module, "MAX_ARCHIVE_ENTRIES", 2)

    assert {too_big.code, big_entry.code, big_folder.code} == {"FOLDER_ARCHIVE_TOO_LARGE"}
    assert (many.code, many.detail) == ("FOLDER_ARCHIVE_INVALID", "entries")
    assert read_folder_archive(content) == {
        "brief/brief.md": "x" * 400,
        "team/team.md": "y" * 400,
    }


def test_directories_inside_the_archive_are_ignored() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("brief/", "")
        archive.writestr("brief/brief.md", "text")

    assert read_folder_archive(buffer.getvalue()) == {"brief/brief.md": "text"}


def test_folder_without_manifest_or_with_a_broken_one_is_rejected() -> None:
    files = folder().files
    missing = {path: text for path, text in files.items() if path != KNOWLEDGE_MANIFEST}
    broken = {**files, KNOWLEDGE_MANIFEST: "{"}
    listed = {**files, KNOWLEDGE_MANIFEST: "[]"}
    manifest = json.loads(files[KNOWLEDGE_MANIFEST])
    del manifest["package"]
    incomplete = {**files, KNOWLEDGE_MANIFEST: json_text(manifest)}

    assert failure(lambda: verify_folder(missing)).code == "FOLDER_DOCUMENT_MISSING"
    assert failure(lambda: verify_folder(broken)).code == "FOLDER_DOCUMENT_INVALID"
    assert failure(lambda: verify_folder(listed)).code == "FOLDER_DOCUMENT_INVALID"
    rejected = failure(lambda: verify_folder(incomplete))
    assert rejected.code == "FOLDER_DOCUMENT_INVALID"
    assert rejected.detail == f"{KNOWLEDGE_MANIFEST}: package"


def test_json_nested_beyond_the_depth_limit_is_an_invalid_document() -> None:
    files = folder().files
    manifest = json.loads(files[KNOWLEDGE_MANIFEST])
    nested: object = 0
    for _ in range(MAX_DOCUMENT_DEPTH):
        nested = {"a": nested}
    shallow = nested["a"]

    refused = failure(
        lambda: verify_folder({**files, KNOWLEDGE_MANIFEST: json_text({**manifest, "x": nested})})
    )

    assert (refused.code, refused.detail) == ("FOLDER_DOCUMENT_INVALID", KNOWLEDGE_MANIFEST)
    assert within_depth(shallow) is True
    assert within_depth(nested) is False
    assert within_depth([[1, 2], {"a": [3]}], limit=4) is True
    assert within_depth([[1, 2], {"a": [3]}], limit=3) is False


def test_json_nested_beyond_the_parser_limit_is_an_invalid_document() -> None:
    files = folder().files
    nested = "[" * 100_000 + "]" * 100_000
    path = "requirements/requirements.json"
    manifest = json.loads(files[KNOWLEDGE_MANIFEST])
    manifest["files"][path] = hashlib.sha256(nested.encode("utf-8")).hexdigest()
    listed = {**files, path: nested, KNOWLEDGE_MANIFEST: json_text(manifest)}

    in_manifest = failure(lambda: verify_folder({**files, KNOWLEDGE_MANIFEST: nested}))
    in_document = failure(lambda: verify_folder(listed))

    assert (in_manifest.code, in_manifest.detail) == ("FOLDER_DOCUMENT_INVALID", KNOWLEDGE_MANIFEST)
    assert in_document.code == "FOLDER_DOCUMENT_INVALID"
    assert in_document.detail.startswith("requirements")


@pytest.mark.parametrize(("key", "value"), [("schema_version", 1), ("kind", "something.else")])
def test_folders_of_another_schema_or_kind_are_not_supported(key: str, value: object) -> None:
    files = folder().files
    manifest = {**json.loads(files[KNOWLEDGE_MANIFEST]), key: value}

    rejected = failure(lambda: verify_folder({**files, KNOWLEDGE_MANIFEST: json_text(manifest)}))

    assert rejected.code in {"FOLDER_SCHEMA_UNSUPPORTED", "FOLDER_DOCUMENT_INVALID"}


def test_changed_missing_and_added_files_are_detected() -> None:
    files = folder().files
    changed = {**files, "requirements/requirements.md": files["requirements/requirements.md"] + "x"}
    missing = {path: text for path, text in files.items() if path != "design/mockup.html"}
    added = {**files, "design/extra.md": "not listed"}

    edited = failure(lambda: verify_folder(changed))
    removed = failure(lambda: verify_folder(missing))
    extra = failure(lambda: verify_folder(added))

    assert (edited.code, edited.detail) == ("FOLDER_TAMPERED", "requirements/requirements.md")
    assert (removed.code, removed.detail) == ("FOLDER_DOCUMENT_MISSING", "design/mockup.html")
    assert (extra.code, extra.detail) == ("FOLDER_TAMPERED", "design/extra.md")


def test_index_is_not_part_of_the_verified_content() -> None:
    files = folder().files

    verified = verify_folder({**files, KNOWLEDGE_INDEX: "# Notes of the team\n"})

    assert verified.files[KNOWLEDGE_INDEX] == "# Notes of the team\n"


def test_stage_document_that_disagrees_with_the_manifest_is_detected() -> None:
    files = folder().files
    manifest = json.loads(files[KNOWLEDGE_MANIFEST])
    manifest["stages"]["design"]["content_hash"] = "f" * 64

    rejected = failure(lambda: verify_folder({**files, KNOWLEDGE_MANIFEST: json_text(manifest)}))

    assert (rejected.code, rejected.detail) == ("FOLDER_TAMPERED", "design/design.json")


def test_document_that_breaks_its_schema_is_reported_with_its_location() -> None:
    files = folder().files
    path = "requirements/requirements.json"
    document = json.loads(files[path])
    document["specification"]["requirements"][0]["kind"] = "OPTIONAL"
    text = json_text(document)
    manifest = json.loads(files[KNOWLEDGE_MANIFEST])
    manifest["files"][path] = __import__("hashlib").sha256(text.encode("utf-8")).hexdigest()

    rejected = failure(
        lambda: verify_folder({**files, path: text, KNOWLEDGE_MANIFEST: json_text(manifest)})
    )

    assert rejected.code == "FOLDER_DOCUMENT_INVALID"
    assert rejected.detail.startswith("requirements: ")
    assert "kind" in rejected.detail
