"""Opt-in configuration must not create resources or invent runner observations."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from orchestwin.api.static_inspection_runtime import (
    StaticInspectionSettings,
    build_static_inspection_service,
)
from orchestwin.web_execution.static_inspections import InspectionError


def test_disabled_configuration_has_no_required_runtime_paths(monkeypatch):
    for name in ("ENABLED", "REPO_ROOT", "RUNNER_MANIFEST", "EVIDENCE_ROOT"):
        monkeypatch.delenv("ORCHESTWIN_STATIC_BROWSER_" + name, raising=False)
    config = StaticInspectionSettings(_env_file=None)
    assert config.enabled is False
    assert build_static_inspection_service(None, None, configuration=config) is None


@pytest.mark.parametrize("missing", ["repo_root", "runner_manifest", "evidence_root"])
def test_enabled_requires_explicit_absolute_paths(tmp_path, missing):
    values = dict(
        enabled=True,
        repo_root=tmp_path / "repo",
        runner_manifest=tmp_path / "manifest.json",
        evidence_root=tmp_path / "evidence",
        _env_file=None,
    )
    values[missing] = None
    with pytest.raises(ValidationError):
        StaticInspectionSettings(**values)


def test_builder_is_lazy_and_does_not_read_or_create_evidence(tmp_path):
    config = StaticInspectionSettings(
        enabled=True,
        repo_root=tmp_path / "repo",
        runner_manifest=tmp_path / "manifest.json",
        evidence_root=tmp_path / "evidence",
        _env_file=None,
    )
    service = build_static_inspection_service(
        object(),
        SimpleNamespace(brownfield_workspace_root=tmp_path / "sources"),
        configuration=config,
    )
    assert service is not None
    assert list(tmp_path.iterdir()) == []


def test_evidence_inside_repo_is_rejected_without_making_directories(tmp_path):
    root = tmp_path / "repo"
    config = StaticInspectionSettings(
        enabled=True,
        repo_root=root,
        runner_manifest=tmp_path / "manifest.json",
        evidence_root=root / "evidence",
        _env_file=None,
    )
    with pytest.raises(InspectionError, match="EVIDENCE_MUST_BE_EXTERNAL"):
        build_static_inspection_service(
            object(), SimpleNamespace(brownfield_workspace_root=tmp_path), configuration=config
        )
    assert not root.exists()
