from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from orchestwin.cli import messages
from orchestwin.cli.api import changes as changes_api
from orchestwin.cli.commands import status as status_command
from orchestwin.cli.flows import code_run
from orchestwin.cli.folder import StateSummary
from orchestwin.cli.project import ProjectFolder

from .support.terminal import PROJECT_ID, START, command_context, link_folder, run_ut, terminal
from .support.transports import ScriptedTransport
from .test_status_command import (
    ALIGNED,
    BASE,
    LATEST_RUN,
    PACKAGE_STEP,
    alignment_document,
    expect_studio,
    gate,
    knowledge_document,
    signed_in_folder,
    version,
)

DESIGN_READINESS = f"{BASE}/design/readiness"
MOMENT = "2026-10-06T22:45:00+00:00"
BEHIND = {
    "en": "Code: aligned with design version 3; the design is at version 6: "
    "`ut align --from-design` brings the code up to the current design.",
    "it": "Codice: allineato al design versione 3; il design è alla versione 6: "
    "`ut align --from-design` porta il codice al design attuale.",
}
CURRENT = {
    "en": "Code: aligned with design version 6.",
    "it": "Codice: allineato al design versione 6.",
}
DEVELOPMENT_LINES = ("Development:", "Sviluppo:")
CODE_LINES = ("Code:", "Codice:")


def aligned_point(design: object) -> dict[str, object]:
    return {
        "commit": ALIGNED,
        "decided_at": "2026-09-29T08:00:00+00:00",
        "requirements_version_number": 1,
        "design_version_number": design,
    }


def design_ready(number: int) -> dict[str, object]:
    identifier = f"design-{number}"
    return {
        "status": "READY_FOR_ARCHITECTURE_PLANNING",
        "version": version(identifier, number, "hd"),
        "gate": gate(identifier, "hd"),
    }


def studio(
    *,
    design: int,
    aligned: dict[str, object] | None,
    knowledge: dict[str, object] | None = None,
) -> ScriptedTransport:
    transport = expect_studio(
        ScriptedTransport(),
        **PACKAGE_STEP,
        alignment={**alignment_document(), "aligned": aligned},
        knowledge=knowledge,
    )
    for item in transport.expected:
        if item.path == DESIGN_READINESS:
            item.body = design_ready(design)
    return transport


def point(project: ProjectFolder, number: int) -> None:
    code_run.write_design_point(
        project,
        version=number,
        folder="20260929-090000",
        reason=code_run.CODE_RUN_REASON,
        moment=START,
    )


def status_lines(
    tmp_path: Path, transport: ScriptedTransport, language: str = "en", *options: str
) -> list[str]:
    run = run_ut(["--lang", language, "status", *options], tmp_path, transport=transport)
    assert run.status == 0, run.errors
    return run.output.splitlines()


def status_json(tmp_path: Path, transport: ScriptedTransport, *options: str) -> Any:
    run = run_ut(["status", *options, "--json"], tmp_path, transport=transport)
    assert run.status == 0, run.errors
    return json.loads(run.output)


def local_date(moment: str) -> str:
    return datetime.fromisoformat(moment).astimezone().strftime("%Y-%m-%d %H:%M")


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_design_ahead_of_the_aligned_point_names_the_alignment_from_the_design(
    tmp_path: Path, language: str
) -> None:
    signed_in_folder(tmp_path)
    text = studio(design=6, aligned=aligned_point(3))
    as_json = studio(design=6, aligned=aligned_point(3))

    lines = status_lines(tmp_path, text, language)
    document = status_json(tmp_path, as_json)

    position = lines.index(BEHIND[language])
    assert lines[position - 1].startswith(DEVELOPMENT_LINES)
    assert lines[position + 1].startswith(("Spent", "Spesa"))
    assert BEHIND[language] == messages.text(
        "status.code_design_behind", language, aligned=3, current=6
    )
    assert document["alignment"]["aligned_design_version"] == 3
    assert document["alignment"]["current_design_version"] == 6
    text.assert_done()
    as_json.assert_done()


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_code_aligned_with_the_current_design_says_so(tmp_path: Path, language: str) -> None:
    signed_in_folder(tmp_path)
    text = studio(design=6, aligned=aligned_point(6))
    as_json = studio(design=6, aligned=aligned_point(6))

    lines = status_lines(tmp_path, text, language)
    document = status_json(tmp_path, as_json)

    position = lines.index(CURRENT[language])
    assert lines[position - 1].startswith(DEVELOPMENT_LINES)
    assert not any("--from-design" in line for line in lines)
    assert CURRENT[language] == messages.text("status.code_design_current", language, aligned=6)
    assert document["alignment"]["aligned_design_version"] == 6
    assert document["alignment"]["current_design_version"] == 6
    text.assert_done()
    as_json.assert_done()


@pytest.mark.parametrize(
    ("recorded", "verified", "expected"),
    [(5, 3, 5), (2, 3, 3), (6, None, 6)],
)
def test_the_point_of_the_last_agent_run_and_the_point_of_verify_give_the_higher(
    tmp_path: Path, recorded: int, verified: int | None, expected: int
) -> None:
    project = signed_in_folder(tmp_path)
    point(project, recorded)
    text = studio(design=6, aligned=aligned_point(verified))
    as_json = studio(design=6, aligned=aligned_point(verified))

    lines = status_lines(tmp_path, text)
    document = status_json(tmp_path, as_json)

    key = "status.code_design_behind" if expected < 6 else "status.code_design_current"
    assert messages.text(key, "en", aligned=expected, current=6) in lines
    assert document["alignment"]["aligned_design_version"] == expected
    assert document["alignment"]["current_design_version"] == 6
    text.assert_done()
    as_json.assert_done()


@pytest.mark.parametrize(
    "aligned",
    [
        None,
        {"commit": ALIGNED, "decided_at": "2026-09-29T08:00:00+00:00"},
        aligned_point(True),
        aligned_point("3"),
        aligned_point(0),
    ],
)
def test_without_a_point_there_is_no_code_line_and_the_json_has_null(
    tmp_path: Path, aligned: dict[str, object] | None
) -> None:
    signed_in_folder(tmp_path)
    text = studio(design=6, aligned=aligned)
    as_json = studio(design=6, aligned=aligned)

    lines = status_lines(tmp_path, text)
    document = status_json(tmp_path, as_json)

    assert any(line.startswith("Development:") for line in lines)
    assert not any(line.startswith(CODE_LINES) for line in lines)
    assert document["alignment"]["aligned_design_version"] is None
    assert document["alignment"]["current_design_version"] == 6
    text.assert_done()
    as_json.assert_done()


def test_without_the_development_the_json_has_no_design_keys(tmp_path: Path) -> None:
    project = signed_in_folder(tmp_path)
    point(project, 5)
    transport = expect_studio(ScriptedTransport(), **{**PACKAGE_STEP, "routes": False})

    document = status_json(tmp_path, transport)

    assert document["alignment"] is None
    transport.assert_done()


def folder_manifest(project: ProjectFolder, *, design: int) -> None:
    stages = ("brief", "team", "twins", "requirements", "design")
    project.knowledge.mkdir(parents=True)
    manifest = {
        "schema_version": 3,
        "package": {"version_number": 7, "content_hash": "c"},
        "project": {"id": PROJECT_ID, "name": "Calcolo mancia"},
        "stages": {
            stage: {
                "version_number": design if stage == "design" else 1,
                "gate": {"status": "APPROVED"},
            }
            for stage in stages
        },
        "progress": {"approved": list(stages), "pending": None, "complete": True},
        "state": {"changes": 4, "pending_changes": 1, "aligned_commit": ALIGNED, "open_tasks": 0},
        "files": {},
    }
    (project.knowledge / "orchestwin.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize("language", ["en", "it"])
def test_offline_the_folder_and_the_point_of_the_agent_give_the_code_line(
    tmp_path: Path, language: str
) -> None:
    project = link_folder(tmp_path / "project")
    folder_manifest(project, design=6)
    point(project, 3)

    lines = status_lines(tmp_path, ScriptedTransport(), language, "--offline")
    document = status_json(tmp_path, ScriptedTransport(), "--offline")

    position = lines.index(BEHIND[language])
    assert lines[position - 1].startswith(DEVELOPMENT_LINES)
    assert document["source"] == "folder"
    assert document["alignment"]["aligned_design_version"] == 3
    assert document["alignment"]["current_design_version"] == 6


def test_offline_without_the_point_of_the_agent_there_is_no_code_line(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    folder_manifest(project, design=6)

    lines = status_lines(tmp_path, ScriptedTransport(), "en", "--offline")
    document = status_json(tmp_path, ScriptedTransport(), "--offline")

    assert any(line.startswith("Development:") for line in lines)
    assert not any(line.startswith(CODE_LINES) for line in lines)
    assert document["alignment"]["aligned_design_version"] is None
    assert document["alignment"]["current_design_version"] == 6


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_knowledge_line_shows_the_local_time_of_the_moment_of_the_studio(
    tmp_path: Path, language: str
) -> None:
    signed_in_folder(tmp_path)
    latest = {**LATEST_RUN, "created_at": MOMENT}
    knowledge = {**knowledge_document(waiting=2), "latest_run": latest}
    text = studio(design=6, aligned=aligned_point(6), knowledge=knowledge)
    as_json = studio(design=6, aligned=aligned_point(6), knowledge=knowledge)

    lines = status_lines(tmp_path, text, language)
    document = status_json(tmp_path, as_json)

    expected = messages.text(
        "status.knowledge", language, commit="4f2a9c1", date=local_date(MOMENT), count=2
    )
    position = lines.index(expected)
    assert lines[position - 1].startswith(CODE_LINES)
    assert document["knowledge_alignment"]["latest_run"]["created_at"] == MOMENT
    text.assert_done()
    as_json.assert_done()


def test_local_moment_converts_only_the_moments_with_a_zone() -> None:
    local = datetime.fromisoformat(MOMENT).astimezone().isoformat()

    assert status_command.local_moment(MOMENT) == local
    assert status_command.local_moment("2026-10-06T22:45:00Z") == local
    assert status_command.local_moment(f" {MOMENT} ") == local
    assert status_command.local_moment("2026-10-06T22:45:00") == "2026-10-06T22:45:00"
    assert status_command.local_moment("not a moment") == "not a moment"
    assert status_command.local_moment("") == ""


@pytest.mark.parametrize(
    ("aligned", "expected"),
    [
        (aligned_point(3), 3),
        (aligned_point(True), None),
        (aligned_point("3"), None),
        ({"commit": ALIGNED}, None),
        (None, None),
    ],
)
def test_the_design_version_of_the_aligned_point_of_the_studio(
    aligned: dict[str, object] | None, expected: int | None
) -> None:
    document = {**alignment_document(), "aligned": aligned}

    assert changes_api.aligned_design_version(document) == expected


def test_the_development_carries_the_design_version_of_the_aligned_point(tmp_path: Path) -> None:
    signed_in_folder(tmp_path)
    transport = ScriptedTransport()
    transport.expect(
        "GET", f"{BASE}/alignment", body={**alignment_document(), "aligned": aligned_point(3)}
    )
    transport.expect("GET", f"{BASE}/code-changes", body={"items": [{"commit": ALIGNED}]})
    client = command_context(terminal(tmp_path, transport=transport).environment).client()

    found = changes_api.development(client, PROJECT_ID)

    assert found == changes_api.Development(
        StateSummary(changes=1, pending_changes=1, aligned_commit=ALIGNED, open_tasks=1), 0, 3
    )
    transport.assert_done()
