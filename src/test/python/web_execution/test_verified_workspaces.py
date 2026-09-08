"""Materialize real files with integrity and portable-path checks, without a runner."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest

from orchestwin.web_execution.workspaces import WebWorkspaceError, materialize_web_source_snapshot

REVISION_ID = str(UUID(int=5701))


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def seal(snapshot):
    snapshot["source_tree_hash"] = digest(
        {
            "files": [
                {key: item[key] for key in ("normalized_path", "sha256_digest", "size_bytes")}
                for item in snapshot["files"]
            ]
        }
    )
    snapshot["content_hash"] = digest(
        {
            key: value
            for key, value in snapshot.items()
            if key not in {"source_tree_hash", "content_hash"}
        }
    )
    return snapshot


def example(tmp_path: Path, paths=("index.html", "assets/main.js")):
    root = tmp_path / "objects"
    entries = []
    for path in sorted(paths, key=lambda value: (value.casefold(), value)):
        content = ("contents of " + path).encode()
        sha = hashlib.sha256(content).hexdigest()
        key = f"sha256/{sha[:2]}/{sha}"
        target = root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        entries.append(
            {
                "normalized_path": path,
                "sha256_digest": sha,
                "size_bytes": len(content),
                "storage_key": key,
                "media_type": "text/plain",
            }
        )
    snapshot = seal(
        {
            "id": REVISION_ID,
            "project_id": str(UUID(int=5702)),
            "created_by_user_id": str(UUID(int=5703)),
            "version_number": 1,
            "based_on": None,
            "target_selection": {
                "target": "WEB_STATIC",
                "language_configuration": {"frontend": "STATIC_ASSETS", "backend": None},
                "layout": "SINGLE_ROOT",
            },
            "validation_scope_hash": "a" * 64,
            "origin": "GENERATED_PLAN",
            "files": entries,
            "provenance_references": [
                {
                    "kind": "ARCHITECTURE",
                    "reference_id": "architecture:a",
                    "version_number": 1,
                    "content_hash": "b" * 64,
                }
            ],
            "related_failure_signature": None,
            "created_at": "2026-09-08T00:00:00+00:00",
        }
    )
    return root, snapshot


def restore(root, snapshot, output):
    return materialize_web_source_snapshot(snapshot, content_root=root, workspaces_root=output)


def test_restores_exact_bytes_and_uses_distinct_workspaces(tmp_path: Path) -> None:
    root, snapshot = example(tmp_path)
    one = restore(root, snapshot, tmp_path / "workspaces")
    two = restore(root, snapshot, tmp_path / "workspaces")
    assert one.path != two.path
    assert one.source_tree_hash == snapshot["source_tree_hash"]
    assert one.source_revision_id == REVISION_ID
    assert one.file_count == 2
    assert (one.path / "index.html").read_bytes() == b"contents of index.html"
    assert (two.path / "assets/main.js").read_bytes() == b"contents of assets/main.js"
    assert one.total_size_bytes == sum(item["size_bytes"] for item in snapshot["files"])


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/absolute",
        "C:/escape",
        "foo:stream",
        "a\\b",
        "a/./b",
        "a//b",
        "a/../b",
        ".git/config",
        ".env",
        "NUL",
        "con.txt",
        "LPT1.log",
        "dir./file",
        "a. ",
        "a/COM2",
        "a\x00b",
        "node_modules/a.js",
    ],
)
def test_rejects_unsafe_paths_before_writing(tmp_path: Path, path: str) -> None:
    root, snapshot = example(tmp_path, ("valid.txt",))
    snapshot["files"][0]["normalized_path"] = path
    seal(snapshot)
    output = tmp_path / "output"
    with pytest.raises(WebWorkspaceError):
        restore(root, snapshot, output)
    assert not output.exists()


@pytest.mark.parametrize("kind", ["content", "tree", "blob", "missing", "size", "storage"])
def test_rejects_corruption_before_writing(tmp_path: Path, kind: str) -> None:
    root, snapshot = example(tmp_path)
    entry = snapshot["files"][0]
    if kind == "content":
        snapshot["origin"] = "UNTRUSTED_CHANGE"
    elif kind == "tree":
        snapshot["source_tree_hash"] = "0" * 64
    elif kind == "blob":
        (root / entry["storage_key"]).write_bytes(b"X" * entry["size_bytes"])
    elif kind == "missing":
        (root / entry["storage_key"]).unlink()
    elif kind == "size":
        entry["size_bytes"] += 1
        seal(snapshot)
    else:
        entry["storage_key"] = "../other"
        seal(snapshot)
    with pytest.raises(WebWorkspaceError):
        restore(root, snapshot, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_path_prefix_collision_is_rejected(tmp_path: Path) -> None:
    root, snapshot = example(tmp_path, ("a", "a/b"))
    with pytest.raises(WebWorkspaceError):
        restore(root, snapshot, tmp_path / "output")


def test_casefold_collision_is_rejected(tmp_path: Path) -> None:
    root, snapshot = example(tmp_path, ("a", "A"))
    with pytest.raises(WebWorkspaceError):
        restore(root, snapshot, tmp_path / "output")


def test_existing_workspaces_are_not_overwritten(tmp_path: Path) -> None:
    root, snapshot = example(tmp_path)
    old = tmp_path / "output" / "keep"
    old.mkdir(parents=True)
    (old / "important").write_text("preserve")
    restore(root, snapshot, tmp_path / "output")
    assert (old / "important").read_text() == "preserve"


def test_symlink_content_parent_is_rejected(tmp_path: Path) -> None:
    root, snapshot = example(tmp_path)
    link = tmp_path / "link"
    try:
        link.symlink_to(root, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem does not allow symlink creation")
    with pytest.raises(WebWorkspaceError):
        restore(link, snapshot, tmp_path / "output")


def test_input_snapshot_remains_unchanged(tmp_path: Path) -> None:
    root, snapshot = example(tmp_path)
    before = deepcopy(snapshot)
    restore(root, snapshot, tmp_path / "output")
    assert snapshot == before


def test_budget_rejected_without_reading_huge_blob(tmp_path: Path) -> None:
    root, snapshot = example(tmp_path)
    snapshot["files"][0]["size_bytes"] = 10**9
    seal(snapshot)
    with pytest.raises(WebWorkspaceError):
        restore(root, snapshot, tmp_path / "output")


def test_overlapping_roots_are_rejected(tmp_path: Path) -> None:
    root, snapshot = example(tmp_path)
    with pytest.raises(WebWorkspaceError):
        restore(root, snapshot, root / "output")
