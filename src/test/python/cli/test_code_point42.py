from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orchestwin.cli.flows import code_run
from orchestwin.cli.flows.code_run import (
    aligned_design_version,
    design_point_version,
    ensure_code_folder,
    read_design_point,
    write_design_point,
)
from orchestwin.cli.project import ProjectFolder

from .support.terminal import START, link_folder

POINT_KEYS = ["schema_version", "design_version_number", "recorded_at", "folder", "reason"]


def project_in(tmp_path: Path) -> ProjectFolder:
    return link_folder(tmp_path / "project")


def point_path(project: ProjectFolder) -> Path:
    return project.root / ".orchestwin" / "code" / "design.json"


def put(project: ProjectFolder, content: bytes) -> None:
    path = point_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def point(version: object, **changes: object) -> dict[str, object]:
    return {
        "schema_version": 1,
        "design_version_number": version,
        "recorded_at": "2026-09-29T09:00:00+00:00",
        "folder": "20260929-090000",
        "reason": "CODE_RUN",
        **changes,
    }


def without(document: dict[str, object], key: str) -> dict[str, object]:
    return {name: value for name, value in document.items() if name != key}


def test_the_names_shared_with_the_other_commands() -> None:
    assert code_run.DESIGN_POINT_NAME == "design.json"
    assert (code_run.CODE_KIND, code_run.DESIGN_KIND) == ("code", "design")
    assert (
        code_run.CODE_RUN_REASON,
        code_run.DESIGN_RUN_REASON,
        code_run.NO_CODE_CHANGES_REASON,
    ) == ("CODE_RUN", "DESIGN_RUN", "NO_CODE_CHANGES")
    assert code_run.SCHEMA_VERSION == 1


def test_the_code_folder_and_its_ignore_file_are_made_once(tmp_path: Path) -> None:
    project = project_in(tmp_path)
    code = project.root / ".orchestwin" / "code"
    missing = code.exists()

    first = ensure_code_folder(project)
    written = (code / ".gitignore").read_bytes()
    (code / ".gitignore").write_bytes(b"kept\n")
    second = ensure_code_folder(project)

    assert missing is False
    assert first == second == code
    assert code.is_dir()
    assert written == b"*\n"
    assert (code / ".gitignore").read_bytes() == b"kept\n"
    assert sorted(path.name for path in code.iterdir()) == [".gitignore"]


def test_the_design_point_is_written_in_the_ignored_code_folder(tmp_path: Path) -> None:
    project = project_in(tmp_path)
    moment = datetime(2026, 10, 6, 11, 0, 5, tzinfo=timezone(timedelta(hours=2)))

    path = write_design_point(
        project,
        version=4,
        folder="20261006-090005",
        reason=code_run.CODE_RUN_REASON,
        moment=moment,
    )
    content = path.read_bytes()
    document = json.loads(content.decode("utf-8"))

    assert path == point_path(project)
    assert (path.parent / ".gitignore").read_bytes() == b"*\n"
    assert list(document) == POINT_KEYS
    assert document == {
        "schema_version": 1,
        "design_version_number": 4,
        "recorded_at": "2026-10-06T09:00:05+00:00",
        "folder": "20261006-090005",
        "reason": "CODE_RUN",
    }
    assert b"\r" not in content and content.endswith(b"}\n")
    assert read_design_point(project) == document
    assert design_point_version(project) == 4


def test_a_later_point_replaces_the_earlier_one_and_may_name_no_folder(tmp_path: Path) -> None:
    project = project_in(tmp_path)
    write_design_point(
        project,
        version=4,
        folder="20260929-090000",
        reason=code_run.CODE_RUN_REASON,
        moment=START,
    )

    write_design_point(
        project,
        version=6,
        folder=None,
        reason=code_run.NO_CODE_CHANGES_REASON,
        moment=START + timedelta(minutes=5),
    )

    assert read_design_point(project) == {
        "schema_version": 1,
        "design_version_number": 6,
        "recorded_at": "2026-09-29T09:05:00+00:00",
        "folder": None,
        "reason": "NO_CODE_CHANGES",
    }
    assert design_point_version(project) == 6


@pytest.mark.parametrize(
    "document",
    [
        None,
        [],
        "design",
        point(4, schema_version=2),
        point(4, schema_version=0),
        point(4, schema_version="1"),
        point(4, schema_version=True),
        without(point(4), "schema_version"),
        point("4"),
        point(4.0),
        point(None),
        point(True),
        point(False),
        point(0),
        point(-1),
        point(-4),
        without(point(4), "design_version_number"),
    ],
)
def test_a_design_point_that_does_not_read_is_left_aside(tmp_path: Path, document: object) -> None:
    project = project_in(tmp_path)
    put(project, json.dumps(document).encode("utf-8"))

    assert read_design_point(project) is None
    assert design_point_version(project) is None
    assert aligned_design_version(project, None) is None
    assert aligned_design_version(project, 7) == 7


@pytest.mark.parametrize("content", [None, b"", b"{not json", b"\xff\xfe{}"])
def test_a_missing_or_broken_design_point_reads_as_none(
    tmp_path: Path, content: bytes | None
) -> None:
    project = project_in(tmp_path)
    if content is not None:
        put(project, content)

    assert read_design_point(project) is None
    assert design_point_version(project) is None


@pytest.mark.parametrize(
    ("written", "verified", "expected"),
    [
        (3, None, 3),
        (None, 5, 5),
        (3, 5, 5),
        (6, 5, 6),
        (4, 4, 4),
        (None, None, None),
    ],
)
def test_the_aligned_design_version_is_the_higher_of_the_two_points(
    tmp_path: Path, written: int | None, verified: int | None, expected: int | None
) -> None:
    project = project_in(tmp_path)
    if written is not None:
        write_design_point(
            project,
            version=written,
            folder=None,
            reason=code_run.DESIGN_RUN_REASON,
            moment=START,
        )

    assert aligned_design_version(project, verified) == expected


@pytest.mark.parametrize("verified", [0, -3, True])
def test_a_verified_point_that_is_not_a_version_counts_as_missing(
    tmp_path: Path, verified: int
) -> None:
    project = project_in(tmp_path)
    alone = aligned_design_version(project, verified)
    write_design_point(
        project, version=2, folder=None, reason=code_run.DESIGN_RUN_REASON, moment=START
    )

    assert alone is None
    assert aligned_design_version(project, verified) == 2
