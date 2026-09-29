from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

import pytest

from orchestwin.cli.errors import CliError
from orchestwin.cli.project import (
    ProjectFolder,
    ProjectLink,
    json_bytes,
    write_atomically,
)

from .support.terminal import PROJECT_ID, START

NAME = "Caff" + chr(0x00E8) + " al banco"


def link(**changes: object) -> ProjectLink:
    values: dict[str, object] = {
        "studio": "http://127.0.0.1:8000",
        "api_prefix": "/api/v1",
        "project_id": PROJECT_ID,
        "project_name": NAME,
        "mode": "DESIGN_ONLY",
        "language": None,
        "created_at": "2026-09-29T09:00:00+00:00",
    }
    values.update(changes)
    return ProjectLink(**values)


def test_create_writes_the_link_byte_for_byte(tmp_path: Path) -> None:
    root = tmp_path / "tip"

    project = ProjectFolder.create(root, link())

    assert project.root == root
    expected = (
        "{\n"
        '  "schema_version": 1,\n'
        '  "studio": "http://127.0.0.1:8000",\n'
        '  "api_prefix": "/api/v1",\n'
        f'  "project_id": "{PROJECT_ID}",\n'
        f'  "project_name": "{NAME}",\n'
        '  "mode": "DESIGN_ONLY",\n'
        '  "language": null,\n'
        '  "created_at": "2026-09-29T09:00:00+00:00",\n'
        '  "knowledge_folder": "orchestwin"\n'
        "}\n"
    )
    assert (root / ".orchestwin" / "project.json").read_bytes() == expected.encode("utf-8")
    assert (root / ".orchestwin" / ".gitignore").read_bytes() == b"previews/\n"
    assert project.link() == link()
    assert project.knowledge == root / "orchestwin"
    assert project.previews == root / ".orchestwin" / "previews"
    assert sorted(path.name for path in (root / ".orchestwin").iterdir()) == [
        ".gitignore",
        "project.json",
    ]


def test_find_walks_up_to_the_linked_folder(tmp_path: Path) -> None:
    root = tmp_path / "tip"
    ProjectFolder.create(root, link())
    inner = root / "src" / "app"
    inner.mkdir(parents=True)

    found = ProjectFolder.find(inner)

    assert found is not None
    assert found.root == root
    assert ProjectFolder.find(tmp_path) is None


@pytest.mark.parametrize("inside", ["", "nested/deeper"])
def test_a_folder_inside_a_linked_one_cannot_be_linked_again(tmp_path: Path, inside: str) -> None:
    root = tmp_path / "tip"
    ProjectFolder.create(root, link())

    with pytest.raises(CliError) as caught:
        ProjectFolder.create(root / inside if inside else root, link(project_id="other"))

    assert caught.value.code == "PROJECT_ALREADY_LINKED"
    assert caught.value.status == 1
    assert caught.value.values["root"] == str(root)
    assert ProjectFolder(root).link().project_id == PROJECT_ID


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "GREENFIELD_GENERATION"},
        {"project_id": ""},
        {"knowledge_folder": "../elsewhere"},
        {"knowledge_folder": "a/b"},
    ],
)
def test_a_link_that_is_not_valid_is_refused(tmp_path: Path, changes: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="link"):
        ProjectFolder.create(tmp_path / "tip", link(**changes))

    assert not (tmp_path / "tip" / ".orchestwin" / "project.json").exists()


def test_update_link_rewrites_the_file(tmp_path: Path) -> None:
    project = ProjectFolder.create(tmp_path / "tip", link())

    updated = project.update_link(mode="DESIGN_AND_CODE", language="it")

    assert updated == link(mode="DESIGN_AND_CODE", language="it")
    assert project.link() == updated
    with pytest.raises(TypeError):
        project.update_link(colour="blue")
    with pytest.raises(ValueError, match="link"):
        project.update_link(mode="OTHER")


@pytest.mark.parametrize(
    "content",
    [
        b"{",
        b"[]",
        b'{"schema_version": 2}',
        json.dumps({"schema_version": 1, "studio": "x"}).encode(),
    ],
)
def test_a_broken_link_is_reported(tmp_path: Path, content: bytes) -> None:
    project = ProjectFolder.create(tmp_path / "tip", link())
    path = tmp_path / "tip" / ".orchestwin" / "project.json"
    path.write_bytes(content)

    with pytest.raises(CliError) as caught:
        project.link()

    assert caught.value.code == "PROJECT_LINK_INVALID"
    assert caught.value.status == 6
    assert caught.value.values["path"] == str(path)


def test_a_link_without_the_folder_name_uses_the_default(tmp_path: Path) -> None:
    project = ProjectFolder.create(tmp_path / "tip", link())
    path = tmp_path / "tip" / ".orchestwin" / "project.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    del document["knowledge_folder"]
    path.write_text(json.dumps(document), encoding="utf-8")

    assert project.link().knowledge_folder == "orchestwin"


def test_steps_are_saved_and_read_back_in_order(tmp_path: Path) -> None:
    project = ProjectFolder.create(tmp_path / "tip", link())
    brief = {"id": "b1", "version_number": 2, "brief": {"name": NAME}}
    gate = {"id": "g1", "status": "APPROVED"}

    path = project.save_step("twins", {"id": "s1", "version_number": 1}, None, START)
    project.save_step("brief", brief, gate, START)

    assert path == tmp_path / "tip" / ".orchestwin" / "steps" / "twins.json"
    expected = json_bytes(
        {
            "schema_version": 1,
            "stage": "brief",
            "saved_at": "2026-09-29T09:00:00+00:00",
            "version": brief,
            "gate": gate,
        }
    )
    written = (tmp_path / "tip" / ".orchestwin" / "steps" / "brief.json").read_bytes()
    assert written == expected
    assert NAME.encode("utf-8") in written
    assert b"\r\n" not in written
    assert project.step("brief") == json.loads(expected)
    assert project.step("design") is None
    assert list(project.steps()) == ["brief", "twins"]


def test_a_broken_step_is_left_out(tmp_path: Path) -> None:
    project = ProjectFolder.create(tmp_path / "tip", link())
    project.save_step("team", {"version_number": 1}, None, START)
    (tmp_path / "tip" / ".orchestwin" / "steps" / "team.json").write_bytes(b"{broken")

    assert project.step("team") is None
    assert project.steps() == {}


def test_an_unknown_stage_is_refused(tmp_path: Path) -> None:
    project = ProjectFolder.create(tmp_path / "tip", link())

    with pytest.raises(ValueError, match="stage"):
        project.save_step("package", {}, None, START)
    with pytest.raises(ValueError, match="stage"):
        project.step("architecture")


def test_an_atomic_write_leaves_only_the_file(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "file.json"

    write_atomically(target, b"first\n")
    write_atomically(target, b"second\n")

    assert target.read_bytes() == b"second\n"
    assert [path.name for path in target.parent.iterdir()] == ["file.json"]


def test_json_bytes_keeps_the_order_and_accepts_read_only_mappings() -> None:
    content = json_bytes({"b": 1, "a": MappingProxyType({"z": NAME})})

    assert content == ('{\n  "b": 1,\n  "a": {\n    "z": "' + NAME + '"\n  }\n}\n').encode()
    with pytest.raises(TypeError):
        json_bytes({"when": START})
