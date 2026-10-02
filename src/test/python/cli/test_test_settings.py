from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestwin.cli.flows import test_settings as settings_flow

from .support.terminal import link_folder


def test_the_settings_are_written_and_read_again(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    written = settings_flow.TestSettings(
        application={"kind": "STATIC", "address": "dist"}, browser="firefox"
    )

    path = settings_flow.write_settings(project, written)

    assert path == project.root / ".orchestwin" / "test.json"
    assert path.read_bytes().decode("utf-8") == (
        "{\n"
        '  "schema_version": 1,\n'
        '  "application": {\n'
        '    "kind": "STATIC",\n'
        '    "address": "dist"\n'
        "  },\n"
        '  "browser": "firefox"\n'
        "}\n"
    )
    assert settings_flow.read_settings(project) == written


def test_without_a_file_there_are_no_settings(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")

    assert settings_flow.read_settings(project) is None


@pytest.mark.parametrize(
    "document",
    [
        [],
        {"schema_version": 2, "application": None, "browser": "all"},
        {"schema_version": 1, "application": None, "browser": "safari"},
        {"schema_version": 1, "application": {"kind": "FILE", "address": "dist"}},
        {"schema_version": 1, "application": {"kind": "URL", "address": "  "}},
        {"schema_version": 1, "application": {"kind": "URL"}},
        {"schema_version": 1, "application": "dist"},
    ],
)
def test_settings_that_cannot_be_read_are_ignored(tmp_path: Path, document: object) -> None:
    project = link_folder(tmp_path / "project")
    settings_flow.settings_path(project).write_text(json.dumps(document), encoding="utf-8")

    assert settings_flow.read_settings(project) is None


def test_the_browser_defaults_to_every_browser_and_the_address_is_trimmed() -> None:
    found = settings_flow.settings_from(
        {"schema_version": 1, "application": {"kind": "URL", "address": " http://x.test/ "}}
    )
    empty = settings_flow.settings_from({"schema_version": 1, "application": None})

    assert found == settings_flow.TestSettings(
        application={"kind": "URL", "address": "http://x.test/"}, browser="all"
    )
    assert empty == settings_flow.TestSettings(application=None, browser="all")
    assert empty is not None
    assert empty.document() == {"schema_version": 1, "application": None, "browser": "all"}
    assert settings_flow.BROWSER_CHOICES == ("chrome", "firefox", "all")
