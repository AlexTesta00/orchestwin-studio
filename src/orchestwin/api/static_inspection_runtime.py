"""Explicit opt-in configuration for owner-governed static browser inspections."""

from __future__ import annotations

from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from orchestwin.web_execution.static_inspection_backend import PersistedStaticBrowserBackend
from orchestwin.web_execution.static_inspection_persistence import SqlAlchemyInspectionStore
from orchestwin.web_execution.static_inspections import StaticInspectionService


class StaticInspectionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ORCHESTWIN_STATIC_BROWSER_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )
    enabled: bool = False
    repo_root: Path | None = None
    runner_manifest: Path | None = None
    evidence_root: Path | None = None

    @model_validator(mode="after")
    def require_paths_when_enabled(self):
        if self.enabled and any(
            value is None or not value.is_absolute()
            for value in (
                self.repo_root,
                self.runner_manifest,
                self.evidence_root,
            )
        ):
            raise ValueError("enabled static browser inspections require three absolute paths")
        return self


def build_static_inspection_service(session_factory, settings, *, configuration=None):
    config = configuration if configuration is not None else StaticInspectionSettings()
    if not config.enabled:
        return None
    backend = PersistedStaticBrowserBackend(
        repo_root=config.repo_root,
        runner_manifest=config.runner_manifest,
        evidence_root=config.evidence_root,
        content_root=settings.brownfield_workspace_root / "web-source-objects",
    )
    return StaticInspectionService(SqlAlchemyInspectionStore(session_factory), backend)
