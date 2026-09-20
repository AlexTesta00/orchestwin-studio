"""A phase receives verified, disposable files without altering the prepared source."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestwin.web_execution import phase_workspace
from orchestwin.web_execution.detection import WebDetectionSnapshot, WebTextFile
from orchestwin.web_execution.phase_workspace import prepare_phase_workspace
from orchestwin.web_execution.workspaces import PreparedWebWorkspace, WebWorkspaceError


def source(tmp_path: Path, files: dict[str, bytes] | None = None):
    contents = files or {
        "Z.html": b"<!doctype html><title>Original</title>",
        "assets/main.js": b"console.log('original');\n",
        "assets/pixel.bin": b"\xff\x00\x80",
    }
    original = tmp_path / "prepared"
    original.mkdir()
    entries = []
    text_files = []
    for name, content in sorted(contents.items(), key=lambda item: (item[0].casefold(), item[0])):
        path = original / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o644)
        digest = hashlib.sha256(content).hexdigest()
        entries.append(
            {"normalized_path": name, "sha256_digest": digest, "size_bytes": len(content)}
        )
        if not name.endswith(".bin"):
            text_files.append(WebTextFile(name, content.decode("utf-8"), digest))
    tree_hash = hashlib.sha256(
        json.dumps(
            {"files": entries}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    prepared = PreparedWebWorkspace(
        path=original,
        source_revision_id="00000000-0000-0000-0000-000000000101",
        source_revision_content_hash="a" * 64,
        source_tree_hash=tree_hash,
        file_count=len(contents),
        total_size_bytes=sum(map(len, contents.values())),
    )
    snapshot = WebDetectionSnapshot(
        inventory_content_hash="b" * 64,
        included_paths=tuple(sorted(contents)),
        text_files=tuple(sorted(text_files, key=lambda entry: entry.normalized_path)),
    )
    return prepared, snapshot, contents


def clone(prepared, snapshot, tmp_path):
    return prepare_phase_workspace(prepared, snapshot, workspaces_root=tmp_path / "phases")


def test_clone_is_independent_reverified_and_removed_idempotently(tmp_path: Path) -> None:
    prepared, snapshot, contents = source(tmp_path)
    original_modes = {name: (prepared.path / name).stat().st_mode for name in contents}
    first = clone(prepared, snapshot, tmp_path)
    second = clone(prepared, snapshot, tmp_path)
    assert first.path.is_absolute()
    assert first.path != second.path != prepared.path
    assert first.source_revision_content_hash == prepared.source_revision_content_hash
    assert first.source_tree_hash == prepared.source_tree_hash
    for name, content in contents.items():
        assert (first.path / name).read_bytes() == content
        assert not os.path.samefile(first.path / name, prepared.path / name)
    (first.path / "Z.html").write_bytes(b"changed")
    (first.path / "generated").mkdir()
    (first.path / "generated/result.txt").write_text("result", encoding="utf-8")
    first.close()
    first.close()
    assert not first.path.exists()
    assert not first.path.parent.exists()
    assert second.path.is_dir()
    for name, content in contents.items():
        assert (prepared.path / name).read_bytes() == content
        assert (second.path / name).read_bytes() == content
        assert (prepared.path / name).stat().st_mode == original_modes[name]
    second.close()
    assert list((tmp_path / "phases").iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions are enforced on Linux runners")
def test_parent_is_private_and_only_clone_contents_are_runner_writable(tmp_path: Path) -> None:
    prepared, snapshot, contents = source(tmp_path)
    phase = clone(prepared, snapshot, tmp_path)
    assert stat.S_IMODE(phase.path.parent.stat().st_mode) == 0o700
    for path in (phase.path, *phase.path.rglob("*")):
        assert stat.S_IMODE(path.stat().st_mode) == (0o777 if path.is_dir() else 0o666)
    assert all(stat.S_IMODE((prepared.path / name).stat().st_mode) == 0o644 for name in contents)
    phase.close()


@pytest.mark.parametrize("change", ["missing", "extra", "snapshot_missing", "binary_changed"])
def test_rejects_changed_file_inventory_or_binary_before_creating_output(
    tmp_path: Path, change: str
) -> None:
    prepared, snapshot, _ = source(tmp_path)
    if change == "missing":
        (prepared.path / "assets/pixel.bin").unlink()
    elif change == "extra":
        (prepared.path / "extra.txt").write_bytes(b"extra")
    elif change == "snapshot_missing":
        snapshot = replace(
            snapshot,
            included_paths=tuple(p for p in snapshot.included_paths if p != "assets/pixel.bin"),
        )
    else:
        (prepared.path / "assets/pixel.bin").write_bytes(b"\xfe\x00\x80")
    with pytest.raises(WebWorkspaceError, match="WEB_"):
        clone(prepared, snapshot, tmp_path)
    assert not (tmp_path / "phases").exists()


def test_rejects_detection_text_from_a_different_source(tmp_path: Path) -> None:
    prepared, snapshot, _ = source(tmp_path)
    replacement = "<!doctype html><title>Different</title>"
    altered = WebTextFile("Z.html", replacement, hashlib.sha256(replacement.encode()).hexdigest())
    snapshot = replace(snapshot, text_files=(altered, *snapshot.text_files[1:]))
    with pytest.raises(WebWorkspaceError, match="TEXT_MISMATCH"):
        clone(prepared, snapshot, tmp_path)
    assert not (tmp_path / "phases").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("file_count", 2),
        ("file_count", True),
        ("total_size_bytes", 1),
        ("total_size_bytes", True),
        ("source_tree_hash", "c" * 64),
        ("source_revision_content_hash", "invalid"),
    ],
)
def test_rejects_inconsistent_prepared_metadata(tmp_path: Path, field: str, value: object) -> None:
    prepared, snapshot, _ = source(tmp_path)
    with pytest.raises(WebWorkspaceError, match="WEB_"):
        clone(replace(prepared, **{field: value}), snapshot, tmp_path)
    assert not (tmp_path / "phases").exists()


@pytest.mark.parametrize("budget", ["file", "total", "count"])
def test_enforces_real_source_read_budgets(tmp_path: Path, budget: str) -> None:
    if budget == "file":
        files = {"large.bin": b"\x00" * (1048576 + 1)}
    elif budget == "total":
        files = {f"{i:03}.bin": b"\x00" * 1048576 for i in range(21)}
    else:
        files = {f"{i:04}.bin": b"" for i in range(1001)}
    prepared, snapshot, _ = source(tmp_path, files)
    if budget == "total":
        prepared = replace(prepared, total_size_bytes=20 * 1048576)
    with pytest.raises(WebWorkspaceError, match="WEB_"):
        clone(prepared, snapshot, tmp_path)
    assert not (tmp_path / "phases").exists()


def test_accepts_exact_per_file_and_total_byte_limits(tmp_path: Path) -> None:
    files = {f"{i:03}.bin": b"\x00" * 1048576 for i in range(20)}
    prepared, snapshot, _ = source(tmp_path, files)
    phase = clone(prepared, snapshot, tmp_path)
    assert sum(path.stat().st_size for path in phase.path.iterdir()) == 20971520
    phase.close()


@pytest.mark.parametrize("protected", [".env", ".git/config", "node_modules/dependency.js"])
def test_rejects_protected_files_even_when_present_in_snapshot(
    tmp_path: Path, protected: str
) -> None:
    prepared, snapshot, _ = source(tmp_path, {protected: b"protected"})
    with pytest.raises(WebWorkspaceError, match="PATH_INVALID"):
        clone(prepared, snapshot, tmp_path)
    assert not (tmp_path / "phases").exists()


@pytest.mark.parametrize("kind", ["reparse", "special"])
def test_rejects_reparse_and_special_source_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    prepared, snapshot, _ = source(tmp_path)
    target = prepared.path / "assets/pixel.bin"
    real_lstat = Path.lstat

    def changed_lstat(path, *args, **kwargs):
        metadata = real_lstat(path, *args, **kwargs)
        if path != target:
            return metadata
        return SimpleNamespace(
            st_mode=metadata.st_mode if kind == "reparse" else stat.S_IFIFO,
            st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT if kind == "reparse" else 0,
        )

    monkeypatch.setattr(Path, "lstat", changed_lstat)
    with pytest.raises(WebWorkspaceError, match="WEB_"):
        clone(prepared, snapshot, tmp_path)
    assert not (tmp_path / "phases").exists()


@pytest.mark.parametrize("location", ["same", "child", "parent"])
def test_rejects_source_and_output_root_overlap(tmp_path: Path, location: str) -> None:
    prepared, snapshot, _ = source(tmp_path)
    output = {
        "same": prepared.path,
        "child": prepared.path / "phases",
        "parent": prepared.path.parent,
    }[location]
    with pytest.raises(WebWorkspaceError, match="ROOTS_OVERLAP"):
        prepare_phase_workspace(prepared, snapshot, workspaces_root=output)


def directory_link_or_skip(link: Path, target: Path) -> None:
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
        return
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Creating symlinks is unavailable: {error}")


def test_rejects_redirected_output_ancestor(tmp_path: Path) -> None:
    prepared, snapshot, _ = source(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    directory_link_or_skip(tmp_path / "redirect", outside)
    with pytest.raises(WebWorkspaceError, match="REDIRECTED_PATH"):
        prepare_phase_workspace(prepared, snapshot, workspaces_root=tmp_path / "redirect/phases")
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("location", ["root", "nested"])
def test_rejects_redirected_prepared_source(tmp_path: Path, location: str) -> None:
    prepared, snapshot, _ = source(tmp_path)
    target = prepared.path if location == "root" else prepared.path / "assets"
    moved = tmp_path / "moved-source"
    target.rename(moved)
    directory_link_or_skip(target, moved)
    with pytest.raises(WebWorkspaceError, match="REDIRECTED_PATH"):
        clone(prepared, snapshot, tmp_path)
    assert not (tmp_path / "phases").exists()
    assert moved.is_dir()


def test_close_removes_generated_links_without_following_them(tmp_path: Path) -> None:
    prepared, snapshot, _ = source(tmp_path)
    phase = clone(prepared, snapshot, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel").write_bytes(b"keep")
    directory_link_or_skip(phase.path / "generated-link", outside)
    phase.close()
    assert (outside / "sentinel").read_bytes() == b"keep"
    assert not phase.path.parent.exists()


def test_close_rejects_replacement_of_owned_root(tmp_path: Path) -> None:
    prepared, snapshot, _ = source(tmp_path)
    phase = clone(prepared, snapshot, tmp_path)
    moved = phase.path.with_name("moved")
    phase.path.rename(moved)
    phase.path.mkdir()
    (phase.path / "sentinel").write_bytes(b"keep")
    with pytest.raises(WebWorkspaceError, match="OWNERSHIP"):
        phase.close()
    assert (phase.path / "sentinel").read_bytes() == b"keep"
    assert moved.is_dir()


def test_close_rejects_replacement_of_owned_parent(tmp_path: Path) -> None:
    prepared, snapshot, _ = source(tmp_path)
    phase = clone(prepared, snapshot, tmp_path)
    moved = phase.path.parent.with_name("moved-parent")
    phase.path.parent.rename(moved)
    phase.path.mkdir(parents=True)
    (phase.path / "sentinel").write_bytes(b"keep")
    with pytest.raises(WebWorkspaceError, match="OWNERSHIP"):
        phase.close()
    assert (phase.path / "sentinel").read_bytes() == b"keep"
    assert moved.is_dir()


def test_close_rejects_redirected_owned_root(tmp_path: Path) -> None:
    prepared, snapshot, _ = source(tmp_path)
    phase = clone(prepared, snapshot, tmp_path)
    moved = phase.path.with_name("moved")
    phase.path.rename(moved)
    directory_link_or_skip(phase.path, prepared.path)
    with pytest.raises(WebWorkspaceError, match="REDIRECTED_PATH"):
        phase.close()
    assert prepared.path.is_dir()
    assert moved.is_dir()


def test_missing_source_failure_does_not_expose_a_host_path(tmp_path: Path) -> None:
    prepared, snapshot, _ = source(tmp_path)
    prepared = replace(prepared, path=tmp_path / "sensitive-location")
    with pytest.raises(WebWorkspaceError, match=r"^WEB_PHASE_WORKSPACE_PREPARATION_FAILED$"):
        clone(prepared, snapshot, tmp_path)
    assert not (tmp_path / "phases").exists()


def test_copy_failure_removes_the_partial_owned_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared, snapshot, contents = source(tmp_path)
    original_open = Path.open

    def fail_second_copy(path, *args, **kwargs):
        if "workspace" in path.parts and path.name == "pixel.bin":
            raise OSError("private host path must not escape")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_second_copy)
    with pytest.raises(WebWorkspaceError, match=r"^WEB_PHASE_WORKSPACE_PREPARATION_FAILED$"):
        clone(prepared, snapshot, tmp_path)
    assert list((tmp_path / "phases").iterdir()) == []
    assert all((prepared.path / name).read_bytes() == content for name, content in contents.items())


def test_all_bytes_are_captured_before_the_first_output_is_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared, snapshot, contents = source(tmp_path)
    original_mkdtemp = phase_workspace.tempfile.mkdtemp

    def mutate_after_capture(*args, **kwargs):
        (prepared.path / "Z.html").write_bytes(b"external change after verified capture")
        return original_mkdtemp(*args, **kwargs)

    monkeypatch.setattr(phase_workspace.tempfile, "mkdtemp", mutate_after_capture)
    phase = clone(prepared, snapshot, tmp_path)
    assert all((phase.path / name).read_bytes() == content for name, content in contents.items())
    phase.close()
