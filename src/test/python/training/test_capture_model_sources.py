"""Tests for the bounded exact-revision Hugging Face source capture adapter."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

from orchestwin.training.model_candidate_matrix_files import (
    load_frozen_model_candidate_matrix,
)
from orchestwin.training.model_source_evidence import (
    ModelSourceCaptureMode,
    ModelSourceFileRole,
    expected_candidate_source_roles,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPOSITORY_ROOT / "environments" / "training" / "capture_model_sources.py"
CAPTURED_AT = datetime(2026, 9, 4, 13, 0, tzinfo=UTC)


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("capture_model_sources", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeDownloader:
    def __init__(self, root: Path, revision: str) -> None:
        self.root = root
        self.revision = revision
        self.calls: list[dict[str, object]] = []

    def __call__(self, **values: object) -> str:
        self.calls.append(values)
        filename = values["filename"]
        assert isinstance(filename, str)
        path = self.root / "models--test" / "snapshots" / self.revision / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"captured:{filename}\n".encode())
        return str(path)


def test_capture_downloads_only_frozen_small_paths_and_writes_regular_copies(
    tmp_path: Path,
) -> None:
    module = _module()
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)
    candidate = matrix.candidate("model-candidate-qwen3-4b-instruct-2507")
    downloader = _FakeDownloader(tmp_path / "cache", candidate.revision)

    evidence, evidence_path = module.capture_candidate_sources(
        candidate=candidate,
        output_root=tmp_path / "output",
        downloader=downloader,
        network_authorized=False,
        cache_dir=tmp_path / "cache",
        captured_at=CAPTURED_AT,
    )

    assert evidence.capture_mode is ModelSourceCaptureMode.CACHE_ONLY
    assert [call["filename"] for call in downloader.calls] == sorted(
        expected_candidate_source_roles(candidate)
    )
    assert all(call["local_files_only"] is True for call in downloader.calls)
    assert all(call["revision"] == candidate.revision for call in downloader.calls)
    assert all("token" not in call for call in downloader.calls)
    assert evidence_path.is_file() and not evidence_path.is_symlink()
    payload = json.loads(evidence_path.read_text())
    assert payload == evidence.to_snapshot()
    for file in evidence.files:
        copied = evidence_path.parent / "files" / file.relative_path
        assert copied.is_file() and not copied.is_symlink()


def test_network_authorization_is_explicit_and_recorded(tmp_path: Path) -> None:
    module = _module()
    candidate = load_frozen_model_candidate_matrix(REPOSITORY_ROOT).candidates[0]
    downloader = _FakeDownloader(tmp_path / "cache", candidate.revision)

    evidence, _ = module.capture_candidate_sources(
        candidate=candidate,
        output_root=tmp_path / "output",
        downloader=downloader,
        network_authorized=True,
        cache_dir=None,
        captured_at=CAPTURED_AT,
    )

    assert evidence.capture_mode is ModelSourceCaptureMode.NETWORK_AUTHORIZED
    assert all(call["local_files_only"] is False for call in downloader.calls)
    readme = evidence.file_for_role(ModelSourceFileRole.MODEL_CARD)
    assert ModelSourceFileRole.LICENSE in readme.roles


def test_capture_rejects_wrong_snapshot_revision(tmp_path: Path) -> None:
    module = _module()
    candidate = load_frozen_model_candidate_matrix(REPOSITORY_ROOT).candidates[0]
    downloader = _FakeDownloader(tmp_path / "cache", "f" * 40)

    with pytest.raises(module.ModelSourceCaptureFailure, match="frozen exact revision"):
        module.capture_candidate_sources(
            candidate=candidate,
            output_root=tmp_path / "output",
            downloader=downloader,
            network_authorized=False,
            cache_dir=None,
            captured_at=CAPTURED_AT,
        )


def test_capture_rejects_non_file_and_oversized_source(tmp_path: Path) -> None:
    module = _module()
    candidate = load_frozen_model_candidate_matrix(REPOSITORY_ROOT).candidates[0]

    def directory_downloader(**values: object) -> str:
        path = tmp_path / "cache" / "snapshots" / candidate.revision / str(values["filename"])
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    first_path = sorted(expected_candidate_source_roles(candidate))[0]
    with pytest.raises(module.ModelSourceCaptureFailure, match="not a regular file"):
        module._capture_file(
            candidate=candidate,
            relative_path=first_path,
            downloader=directory_downloader,
            network_authorized=False,
            cache_dir=None,
        )


def test_script_help_does_not_import_hugging_face_runtime() -> None:
    source = SCRIPT_PATH.read_text()

    assert "from huggingface_hub import hf_hub_download" in source
    assert source.index("def _load_hugging_face_downloader") < source.index(
        "from huggingface_hub import hf_hub_download"
    )
    assert "snapshot_download" not in source
    assert "trust_remote_code" not in source
