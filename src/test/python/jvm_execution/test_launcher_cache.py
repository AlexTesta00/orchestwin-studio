"""The Gradle seed helper copies pinned bytes without trusting a previous cache."""

from __future__ import annotations

import hashlib
import io
import os
from dataclasses import FrozenInstanceError
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from orchestwin.jvm_execution import launcher_cache
from orchestwin.jvm_execution.launcher_cache import (
    GradleWrapperCacheSeedError,
    seed_gradle_wrapper_cache,
)

_ATTEMPT = UUID("d881a232-50d4-4ce3-bef7-986e00c63c85")
_RELATIVE_HOME = f".orchestwin/jvm/{_ATTEMPT.hex}/gradle"
_RELATIVE_ZIP = (
    f"{_RELATIVE_HOME}/wrapper/dists/gradle-9.5.0-bin/"
    "bvnork1r7n8i6kp5cnkibsc9q/gradle-9.5.0-bin.zip"
)


@pytest.fixture
def example(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, bytes]:
    """Small synthetic bytes exercise copying; they are not execution evidence."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    distribution = tmp_path / "distribution.zip"
    raw = b"synthetic pinned distribution bytes\x00\xff\r\n"
    distribution.write_bytes(raw)
    monkeypatch.setattr(
        launcher_cache, "GRADLE_DISTRIBUTION_SHA256", hashlib.sha256(raw).hexdigest()
    )
    return workspace, distribution, raw


def test_production_distribution_pin_and_url_cache_key_match_gradle_9_5() -> None:
    assert launcher_cache.GRADLE_DISTRIBUTION_IMAGE_PATH == "/opt/orchestwin/gradle-9.5.0-bin.zip"
    assert launcher_cache.GRADLE_DISTRIBUTION_SHA256 == (
        "553c78f50dafcd54d65b9a444649057857469edf836431389695608536d6b746"
    )
    assert launcher_cache.GRADLE_DISTRIBUTION_MAX_BYTES == 512 * 1024 * 1024
    value = int.from_bytes(
        hashlib.md5(
            launcher_cache.GRADLE_DISTRIBUTION_URL.encode(), usedforsecurity=False
        ).digest(),
        "big",
    )
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    encoded = ""
    while value:
        value, remainder = divmod(value, 36)
        encoded = digits[remainder] + encoded
    assert encoded == "bvnork1r7n8i6kp5cnkibsc9q"


def test_copies_exact_bytes_and_returns_an_immutable_relative_receipt(example) -> None:
    workspace, distribution, raw = example

    receipt = seed_gradle_wrapper_cache(
        workspace_root=workspace, attempt_id=_ATTEMPT, distribution_path=distribution
    )

    assert receipt.attempt_id == _ATTEMPT
    assert receipt.destination_relative == _RELATIVE_ZIP
    assert receipt.gradle_user_home_relative == _RELATIVE_HOME
    assert receipt.distribution_sha256 == hashlib.sha256(raw).hexdigest()
    assert receipt.distribution_url == launcher_cache.GRADLE_DISTRIBUTION_URL
    assert receipt.size_bytes == len(raw)
    assert (workspace / receipt.destination_relative).read_bytes() == raw
    assert distribution.read_bytes() == raw
    assert tuple(path for path in workspace.rglob("*") if path.is_file()) == (
        workspace / _RELATIVE_ZIP,
    )
    with pytest.raises(FrozenInstanceError):
        receipt.size_bytes = 1  # type: ignore[misc]


def test_attempts_receive_distinct_caches_and_reseeding_fails(example) -> None:
    workspace, distribution, raw = example
    first = seed_gradle_wrapper_cache(
        workspace_root=workspace, attempt_id=_ATTEMPT, distribution_path=distribution
    )
    second = seed_gradle_wrapper_cache(
        workspace_root=workspace, attempt_id=uuid4(), distribution_path=distribution
    )

    with pytest.raises(GradleWrapperCacheSeedError, match="already exists"):
        seed_gradle_wrapper_cache(
            workspace_root=workspace, attempt_id=_ATTEMPT, distribution_path=distribution
        )

    assert first.destination_relative != second.destination_relative
    assert (workspace / first.destination_relative).read_bytes() == raw
    assert (workspace / second.destination_relative).read_bytes() == raw


@pytest.mark.parametrize("existing", ["empty", "zip", "marker", "file"])
def test_existing_wrapper_cache_is_never_reused_or_overwritten(example, existing: str) -> None:
    workspace, distribution, _ = example
    wrapper = workspace / _RELATIVE_HOME / "wrapper"
    wrapper.parent.mkdir(parents=True)
    if existing == "file":
        wrapper.write_bytes(b"keep file")
    else:
        wrapper.mkdir()
        if existing != "empty":
            (wrapper / ("previous.zip" if existing == "zip" else "previous.zip.ok")).write_bytes(
                b"keep previous cache"
            )
    before = {path: path.read_bytes() for path in workspace.rglob("*") if path.is_file()}

    with pytest.raises(GradleWrapperCacheSeedError, match="already exists"):
        seed_gradle_wrapper_cache(
            workspace_root=workspace, attempt_id=_ATTEMPT, distribution_path=distribution
        )

    assert before == {path: path.read_bytes() for path in workspace.rglob("*") if path.is_file()}
    assert wrapper.exists()


def test_checksum_mismatch_rolls_back_only_new_outputs(example) -> None:
    workspace, distribution, _ = example
    keep = workspace / "keep.txt"
    keep.write_bytes(b"existing source")
    distribution.write_bytes(b"corrupted distribution")

    with pytest.raises(GradleWrapperCacheSeedError, match="SHA-256 differs"):
        seed_gradle_wrapper_cache(
            workspace_root=workspace, attempt_id=_ATTEMPT, distribution_path=distribution
        )

    assert list(workspace.iterdir()) == [keep]
    assert keep.read_bytes() == b"existing source"


@pytest.mark.parametrize("input_name", ["workspace_root", "distribution_path"])
@pytest.mark.parametrize("invalid", ["relative", "parent-traversal"])
def test_inputs_require_absolute_canonical_paths(example, input_name: str, invalid: str) -> None:
    workspace, distribution, _ = example
    arguments = {"workspace_root": workspace, "distribution_path": distribution}
    original = arguments[input_name]
    arguments[input_name] = (
        Path(original.name)
        if invalid == "relative"
        else original.parent / ".." / original.parent.name / original.name
    )

    with pytest.raises(GradleWrapperCacheSeedError, match="absolute canonical path"):
        seed_gradle_wrapper_cache(attempt_id=_ATTEMPT, **arguments)

    assert not (workspace / ".orchestwin").exists()


@pytest.mark.parametrize("invalid", [None, "d881a23250d44ce3bef7986e00c63c85", 42])
def test_attempt_id_must_be_a_uuid(example, invalid: object) -> None:
    workspace, distribution, _ = example

    with pytest.raises(GradleWrapperCacheSeedError, match="must be a UUID"):
        seed_gradle_wrapper_cache(
            workspace_root=workspace, attempt_id=invalid, distribution_path=distribution
        )

    assert not (workspace / ".orchestwin").exists()


@pytest.mark.parametrize("invalid", ["directory", "missing", "empty"])
def test_distribution_source_must_be_a_nonempty_regular_file(example, invalid: str) -> None:
    workspace, distribution, _ = example
    distribution.unlink()
    if invalid == "directory":
        distribution.mkdir()
    elif invalid == "empty":
        distribution.touch()

    with pytest.raises(GradleWrapperCacheSeedError):
        seed_gradle_wrapper_cache(
            workspace_root=workspace, attempt_id=_ATTEMPT, distribution_path=distribution
        )

    assert not (workspace / ".orchestwin").exists()


def test_declared_oversize_is_rejected_before_creating_cache(example, monkeypatch) -> None:
    workspace, distribution, raw = example
    monkeypatch.setattr(launcher_cache, "GRADLE_DISTRIBUTION_MAX_BYTES", len(raw) - 1)

    with pytest.raises(GradleWrapperCacheSeedError, match="byte limit"):
        seed_gradle_wrapper_cache(
            workspace_root=workspace, attempt_id=_ATTEMPT, distribution_path=distribution
        )

    assert not (workspace / ".orchestwin").exists()


@pytest.mark.parametrize("exceeds_limit", [False, True])
def test_source_growth_during_copy_fails_and_removes_partial_cache(
    example, monkeypatch, exceeds_limit: bool
) -> None:
    workspace, distribution, raw = example
    original_copy = launcher_cache._copy_distribution
    monkeypatch.setattr(
        launcher_cache, "GRADLE_DISTRIBUTION_MAX_BYTES", len(raw) if exceeds_limit else len(raw) * 2
    )

    def append_then_copy(source, target):
        with distribution.open("ab") as mutator:
            mutator.write(b"extra")
        return original_copy(source, target)

    monkeypatch.setattr(launcher_cache, "_copy_distribution", append_then_copy)
    with pytest.raises(
        GradleWrapperCacheSeedError,
        match="byte limit" if exceeds_limit else "changed while copying",
    ):
        seed_gradle_wrapper_cache(
            workspace_root=workspace, attempt_id=_ATTEMPT, distribution_path=distribution
        )

    assert not (workspace / ".orchestwin").exists()


def test_streaming_uses_bounded_reads_and_accepts_the_exact_limit(monkeypatch) -> None:
    raw = b"1234567890"
    monkeypatch.setattr(launcher_cache, "GRADLE_DISTRIBUTION_MAX_BYTES", len(raw))
    monkeypatch.setattr(launcher_cache, "_COPY_CHUNK_BYTES", 3)
    reads: list[int] = []

    class RecordingSource(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    output = io.BytesIO()
    digest, size = launcher_cache._copy_distribution(RecordingSource(raw), output)

    assert output.getvalue() == raw
    assert size == len(raw)
    assert digest == hashlib.sha256(raw).hexdigest()
    assert all(0 < requested <= 3 for requested in reads)
    assert len(reads) > 1


def _symlink_or_skip(link: Path, target: Path, *, directory: bool) -> None:
    if os.name == "nt" and directory:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
        return
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        pytest.skip(f"Filesystem symlinks unavailable: {error}")


@pytest.mark.parametrize("redirect", ["source", "source-parent", "workspace", "cache-parent"])
def test_redirected_paths_are_rejected_without_writing_outside_workspace(example, redirect) -> None:
    workspace, distribution, _ = example
    outside = workspace.parent / "outside"
    outside.mkdir()
    arguments = {"workspace_root": workspace, "distribution_path": distribution}
    if redirect == "source":
        linked_source = outside / "distribution.zip"
        _symlink_or_skip(linked_source, distribution, directory=False)
        arguments["distribution_path"] = linked_source
    elif redirect == "source-parent":
        linked_parent = outside / "redirect"
        _symlink_or_skip(linked_parent, distribution.parent, directory=True)
        arguments["distribution_path"] = linked_parent / distribution.name
    elif redirect == "workspace":
        linked_workspace = outside / "workspace"
        _symlink_or_skip(linked_workspace, workspace, directory=True)
        arguments["workspace_root"] = linked_workspace
    else:
        _symlink_or_skip(workspace / ".orchestwin", outside, directory=True)

    with pytest.raises(GradleWrapperCacheSeedError, match="filesystem redirects"):
        seed_gradle_wrapper_cache(attempt_id=_ATTEMPT, **arguments)

    assert not (outside / "jvm").exists()
    assert not (workspace / _RELATIVE_ZIP).exists()


def test_windows_junction_detection_fails_closed_without_following_it(example, monkeypatch) -> None:
    workspace, distribution, _ = example
    junction = workspace / ".orchestwin"
    junction.mkdir()
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda path: path == junction or original(path))

    with pytest.raises(GradleWrapperCacheSeedError, match="filesystem redirects"):
        seed_gradle_wrapper_cache(
            workspace_root=workspace, attempt_id=_ATTEMPT, distribution_path=distribution
        )

    assert list(junction.iterdir()) == []


def test_failed_copy_preserves_preexisting_runtime_directories(example, monkeypatch) -> None:
    workspace, distribution, _ = example
    parent = workspace / _RELATIVE_HOME
    parent.mkdir(parents=True)
    keep = parent / "keep"
    keep.write_bytes(b"existing runtime metadata")

    def fail_mid_copy(source, target):
        target.write(source.read(2))
        raise OSError("simulated storage failure")

    monkeypatch.setattr(launcher_cache, "_copy_distribution", fail_mid_copy)
    with pytest.raises(GradleWrapperCacheSeedError, match="could not read or seed"):
        seed_gradle_wrapper_cache(
            workspace_root=workspace, attempt_id=_ATTEMPT, distribution_path=distribution
        )

    assert parent.is_dir()
    assert list(parent.iterdir()) == [keep]
    assert keep.read_bytes() == b"existing runtime metadata"


def test_failure_cleanup_does_not_remove_foreign_files_in_the_new_cache(
    example, monkeypatch
) -> None:
    workspace, distribution, _ = example
    foreign = workspace / _RELATIVE_ZIP
    foreign = foreign.with_name("foreign.txt")

    def fail_with_foreign_output(source, target):
        target.write(source.read(2))
        foreign.write_bytes(b"another writer owns this")
        raise OSError("simulated storage failure")

    monkeypatch.setattr(launcher_cache, "_copy_distribution", fail_with_foreign_output)
    with pytest.raises(GradleWrapperCacheSeedError):
        seed_gradle_wrapper_cache(
            workspace_root=workspace, attempt_id=_ATTEMPT, distribution_path=distribution
        )

    assert foreign.read_bytes() == b"another writer owns this"
    assert not (workspace / _RELATIVE_ZIP).exists()
