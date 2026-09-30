from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api.tests import APPLICATION_KINDS, BROWSER_NAMES
from orchestwin.cli.project import json_bytes, read_json, write_atomically

if TYPE_CHECKING:
    from orchestwin.cli.project import ProjectFolder

SETTINGS_NAME: Final = "test.json"
SCHEMA_VERSION: Final = 1
ALL_BROWSERS: Final = "all"
BROWSER_CHOICES: Final = (*BROWSER_NAMES, ALL_BROWSERS)


@dataclass(frozen=True, slots=True)
class TestSettings:
    __test__ = False

    application: Mapping[str, str] | None = None
    browser: str = ALL_BROWSERS

    def document(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "application": None if self.application is None else dict(self.application),
            "browser": self.browser,
        }


def settings_path(project: ProjectFolder) -> Path:
    return project.local / SETTINGS_NAME


def read_settings(project: ProjectFolder) -> TestSettings | None:
    return settings_from(read_json(settings_path(project)))


def write_settings(project: ProjectFolder, settings: TestSettings) -> Path:
    path = settings_path(project)
    write_atomically(path, json_bytes(settings.document()))
    return path


def settings_from(document: object) -> TestSettings | None:
    if not isinstance(document, Mapping) or document.get("schema_version") != SCHEMA_VERSION:
        return None
    browser = document.get("browser", ALL_BROWSERS)
    if browser not in BROWSER_CHOICES:
        return None
    application = document.get("application")
    if application is None:
        return TestSettings(application=None, browser=str(browser))
    found = application_from(application)
    if found is None:
        return None
    return TestSettings(application=found, browser=str(browser))


def application_from(value: object) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    kind = value.get("kind")
    address = value.get("address")
    if kind not in APPLICATION_KINDS or not isinstance(address, str) or not address.strip():
        return None
    return {"kind": str(kind), "address": address.strip()}
