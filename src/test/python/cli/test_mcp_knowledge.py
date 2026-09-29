from __future__ import annotations

import copy
import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from orchestwin.cli import folder as local_folder
from orchestwin.cli.mcp import knowledge
from orchestwin.cli.mcp.knowledge import FolderProblem
from orchestwin.cli.project import ProjectFolder
from src.test.python.knowledge.knowledge_fixtures import (
    ALIGNED_COMMIT,
    CHANGE_RUN,
    PENDING_COMMIT,
    RECEPTION_TWIN,
    VOLUNTEER_TWIN,
    real_documents,
    schema_two_files,
    state_sources,
)

from .support.folders import partial_archive, state_archive, valid_archive, valid_files
from .support.terminal import link_folder

STAGES = ("brief", "team", "twins", "requirements", "design")
RECEPTION = "Addetti all'accoglienza"
VOLUNTEERS = "Organizzatori volontari"


def linked(tmp_path: Path, *, language: str | None = "it") -> ProjectFolder:
    return link_folder(tmp_path / "project", language=language)


def with_archive(tmp_path: Path, archive: bytes, *, language: str | None = "it") -> ProjectFolder:
    project = linked(tmp_path, language=language)
    local_folder.unpack(archive, project.knowledge)
    return project


def with_files(
    tmp_path: Path, files: Mapping[str, str], *, language: str | None = "it"
) -> ProjectFolder:
    project = linked(tmp_path, language=language)
    write_files(project.knowledge, files)
    return project


def state_folder(tmp_path: Path, *, language: str | None = "it") -> ProjectFolder:
    return with_archive(tmp_path, state_archive(state=state_sources()), language=language)


def schema_two_folder(tmp_path: Path, *, language: str | None = "it") -> ProjectFolder:
    return with_files(tmp_path, schema_two_files(valid_files()), language=language)


def write_files(folder: Path, files: Mapping[str, str]) -> None:
    for name, content in files.items():
        path = folder.joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))


def edit_json(path: Path, change: Callable[[dict], None]) -> None:
    document = json.loads(path.read_bytes().decode("utf-8"))
    change(document)
    path.write_bytes(json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8"))


def manifest_bytes(**values: object) -> bytes:
    return json.dumps({"kind": "orchestwin.knowledge-folder", **values}).encode("utf-8")


def test_a_schema_three_folder_gives_its_stages_its_state_and_its_twins(tmp_path: Path) -> None:
    project = state_folder(tmp_path)

    found = knowledge.load(project.knowledge)
    state = found.state()
    twins = found.twins()

    assert (found.schema_version, found.version_number) == (3, 1)
    assert found.approved == STAGES
    assert found.pending is None
    assert found.complete is True
    assert state is not None
    assert state["kind"] == "orchestwin.project-state"
    assert state["aligned"]["commit"] == ALIGNED_COMMIT
    assert [change["commit"] for change in state["changes"]] == [PENDING_COMMIT, ALIGNED_COMMIT]
    assert [run["id"] for run in found.change_runs()] == [CHANGE_RUN]
    assert found.design_reviews() == 0
    assert twins is not None
    assert [(twin.number, twin.twin_id, twin.name) for twin in twins] == [
        (1, RECEPTION_TWIN, RECEPTION),
        (2, VOLUNTEER_TWIN, VOLUNTEERS),
    ]


@pytest.mark.parametrize(
    ("through", "pending"),
    [("brief", "team"), ("team", "twins"), ("twins", "requirements"), ("requirements", "design")],
)
def test_a_partial_folder_holds_only_the_approved_stages(
    tmp_path: Path, through: str, pending: str
) -> None:
    project = with_archive(tmp_path, partial_archive(through=through))

    found = knowledge.load(project.knowledge)
    state = found.state()

    assert found.approved == STAGES[: STAGES.index(through) + 1]
    assert found.pending == pending
    assert found.complete is False
    assert found.stage(pending) is None
    assert found.stage(through) is not None
    assert state is not None
    assert (state["changes"], state["aligned"], state["tasks"]) == ([], None, [])
    assert found.change_runs() == []
    assert found.design_reviews() == 0
    assert (found.twins() is None) is (through in ("brief", "team"))


def test_a_schema_two_folder_has_the_five_stages_and_no_state(tmp_path: Path) -> None:
    project = schema_two_folder(tmp_path)

    found = knowledge.load(project.knowledge)
    twins = found.twins()

    assert found.schema_version == 2
    assert found.approved == STAGES
    assert found.complete is True
    assert found.state() is None
    assert found.change_runs() == []
    assert found.design_reviews() == 0
    assert twins is not None
    assert [twin.name for twin in twins] == [RECEPTION, VOLUNTEERS]


def test_a_folder_without_a_manifest_is_missing(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()

    with pytest.raises(FolderProblem) as nothing:
        knowledge.load(tmp_path / "nothing")
    with pytest.raises(FolderProblem) as empty:
        knowledge.load(tmp_path / "empty")

    assert (nothing.value.code, dict(nothing.value.values)) == ("FOLDER_MISSING", {})
    assert empty.value.code == "FOLDER_MISSING"


@pytest.mark.parametrize(
    ("content", "code", "values"),
    [
        (b"{", "FOLDER_UNREADABLE", {"path": "orchestwin.json"}),
        (b"[]", "FOLDER_UNREADABLE", {"path": "orchestwin.json"}),
        (b"\xff\xfe{}", "FOLDER_UNREADABLE", {"path": "orchestwin.json"}),
        (
            b'{"kind": "orchestwin.knowledge-folder", "schema_version": NaN}',
            "FOLDER_UNREADABLE",
            {"path": "orchestwin.json"},
        ),
        (
            json.dumps({"kind": "other", "schema_version": 3}).encode("utf-8"),
            "FOLDER_SCHEMA_UNSUPPORTED",
            {"version": "3"},
        ),
        (manifest_bytes(schema_version=4), "FOLDER_SCHEMA_UNSUPPORTED", {"version": "4"}),
        (manifest_bytes(schema_version=1), "FOLDER_SCHEMA_UNSUPPORTED", {"version": "1"}),
        (manifest_bytes(schema_version="3"), "FOLDER_SCHEMA_UNSUPPORTED", {"version": "3"}),
        (manifest_bytes(schema_version=True), "FOLDER_SCHEMA_UNSUPPORTED", {"version": "True"}),
    ],
)
def test_a_manifest_that_cannot_be_used_is_refused(
    tmp_path: Path, content: bytes, code: str, values: dict[str, str]
) -> None:
    folder = tmp_path / "orchestwin"
    folder.mkdir()
    (folder / "orchestwin.json").write_bytes(content)

    with pytest.raises(FolderProblem) as refused:
        knowledge.load(folder)

    assert (refused.value.code, dict(refused.value.values)) == (code, values)


def test_a_stage_document_outside_the_folder_is_never_read(tmp_path: Path) -> None:
    project = state_folder(tmp_path)
    (project.root / "secret.json").write_bytes(b'{"snapshot": {"twin_versions": []}}')
    edit_json(
        project.knowledge / "orchestwin.json",
        lambda manifest: manifest["stages"]["twins"].update(document="../secret.json"),
    )

    found = knowledge.load(project.knowledge)
    with pytest.raises(FolderProblem) as refused:
        found.twins()

    assert (refused.value.code, dict(refused.value.values)) == (
        "FOLDER_UNREADABLE",
        {"path": "../secret.json"},
    )


def test_a_schema_three_folder_without_its_state_cannot_be_read(tmp_path: Path) -> None:
    project = state_folder(tmp_path)
    (project.knowledge / "state" / "state.json").unlink()
    (project.knowledge / "twins" / "feedback" / "changes.json").write_bytes(b"[1]")

    found = knowledge.load(project.knowledge)
    with pytest.raises(FolderProblem) as state:
        found.state()
    with pytest.raises(FolderProblem) as runs:
        found.change_runs()

    assert dict(state.value.values) == {"path": "state/state.json"}
    assert dict(runs.value.values) == {"path": "twins/feedback/changes.json"}


def test_a_state_document_of_another_kind_cannot_be_read(tmp_path: Path) -> None:
    project = state_folder(tmp_path)
    edit_json(
        project.knowledge / "state" / "state.json",
        lambda state: state.update(kind="orchestwin.change-reviews"),
    )

    with pytest.raises(FolderProblem) as refused:
        knowledge.load(project.knowledge).state()

    assert refused.value.code == "FOLDER_UNREADABLE"


@pytest.mark.parametrize(
    "relative",
    [
        "",
        "/state/state.md",
        "../outside.md",
        "state/../../outside.md",
        "state\\state.md",
        "C:state.md",
        "state//state.md",
        "./state/state.md",
        "state/./state.md",
        "state/state.md\0",
    ],
)
def test_paths_that_could_leave_the_folder_are_refused(tmp_path: Path, relative: str) -> None:
    assert knowledge.inside(tmp_path, relative) is None


def test_a_path_inside_the_folder_is_kept(tmp_path: Path) -> None:
    assert knowledge.inside(tmp_path, "state/state.md") == tmp_path / "state" / "state.md"


def test_every_markdown_file_of_the_folder_is_listed(tmp_path: Path) -> None:
    project = state_folder(tmp_path)
    write_files(project.knowledge, {"notes/extra.md": "# Extra\n", "notes/extra.txt": "no\n"})

    found = knowledge.markdown_files(project.knowledge)

    assert found == sorted(found)
    assert all(path.endswith(".md") for path in found)
    assert {
        "ORCHESTWIN.md",
        "brief/brief.md",
        "state/state.md",
        "twins/feedback/feedback.md",
        "notes/extra.md",
    } <= set(found)
    assert knowledge.markdown_files(tmp_path / "missing") == []


def test_only_markdown_files_inside_the_folder_are_read(tmp_path: Path) -> None:
    project = state_folder(tmp_path)
    (project.root / "outside.md").write_bytes(b"# Outside\n")
    expected = (project.knowledge / "state" / "state.md").read_bytes().decode("utf-8")

    assert knowledge.markdown_text(project.knowledge, "state/state.md") == expected
    assert knowledge.markdown_text(project.knowledge, "orchestwin.json") is None
    assert knowledge.markdown_text(project.knowledge, "../outside.md") is None
    assert knowledge.markdown_text(project.knowledge, "missing.md") is None
    assert knowledge.markdown_text(project.knowledge, "brief") is None


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need privileges on Windows")
def test_a_symbolic_link_is_never_listed_nor_read(tmp_path: Path) -> None:
    project = state_folder(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_bytes(b"# Outside\n")
    (project.knowledge / "link.md").symlink_to(outside)

    assert "link.md" not in knowledge.markdown_files(project.knowledge)
    assert knowledge.markdown_text(project.knowledge, "link.md") is None


def test_the_requirements_view_names_every_item_by_its_code() -> None:
    view = knowledge.requirements_view(real_documents()["requirements"])

    assert view["version_number"] == 2
    assert [item["code"] for item in view["requirements"]] == [
        f"REQ-00{number}" for number in range(1, 8)
    ]
    assert view["requirements"][0] == {
        "code": "REQ-001",
        "title": "Aggiunta ospite",
        "statement": "Inserire il nome di un ospite e aggiungerlo alla lista",
        "kind": "FUNCTIONAL",
        "priority": "MUST",
    }
    assert [(item["code"], item["requirement_codes"]) for item in view["user_stories"]] == [
        ("USR-001", ["REQ-004", "REQ-002"]),
        ("USR-002", ["REQ-001", "REQ-003"]),
    ]
    assert view["user_stories"][1]["goal"] == "Aggiungere ospiti per nome"
    assert view["acceptance_criteria"] == [
        {
            "code": "AC-001",
            "statement": "L'applicazione deve consentire l'inserimento di un nome ospite e la "
            "sua visualizzazione immediata nella lista.",
            "requirement_codes": ["REQ-001", "REQ-002"],
            "verification_method": "DEMONSTRATION",
        }
    ]


@pytest.mark.parametrize(
    ("codes", "requirements", "stories", "criteria", "unknown"),
    [
        (["REQ-001"], ["REQ-001"], ["USR-002"], ["AC-001"], []),
        (["REQ-004"], ["REQ-004"], ["USR-001"], [], []),
        (["REQ-006"], ["REQ-006"], [], [], []),
        (["USR-001"], [], ["USR-001"], [], []),
        (["AC-001", "XYZ-1", "xyz-1"], [], [], ["AC-001"], ["XYZ-1"]),
        (["req-003", "REQ-002"], ["REQ-002", "REQ-003"], ["USR-001", "USR-002"], ["AC-001"], []),
    ],
)
def test_codes_select_their_items_and_what_cites_the_requirements(
    codes: list[str],
    requirements: list[str],
    stories: list[str],
    criteria: list[str],
    unknown: list[str],
) -> None:
    view = knowledge.requirements_view(real_documents()["requirements"])

    selected, missing = knowledge.select_codes(view, codes)

    assert [item["code"] for item in selected["requirements"]] == requirements
    assert [item["code"] for item in selected["user_stories"]] == stories
    assert [item["code"] for item in selected["acceptance_criteria"]] == criteria
    assert selected["version_number"] == 2
    assert missing == unknown


def test_the_design_view_reads_the_chosen_alternative_its_screens_and_transitions() -> None:
    view = knowledge.design_view(real_documents()["design"])
    screen = view.screen("scr-002")

    assert view.version_number == 4
    assert view.chosen is not None
    assert view.chosen["code"] == "DES-002"
    assert [item["code"] for item in view.alternatives] == ["DES-001", "DES-002"]
    assert [(item.code, item.title) for item in view.screens] == [
        ("SCR-001", "Lista Ospiti"),
        ("SCR-002", "Aggiungi Ospite"),
        ("SCR-003", "Conferma Aggiunta"),
    ]
    assert screen is not None
    assert screen.elements == ("AGGIUNGI OSPITE", "Nome ospite", "Conferma", "Annulla")
    assert [move.code for move in view.moves("SCR-002")] == [
        "TRN-001",
        "TRN-002",
        "TRN-003",
        "TRN-004",
    ]
    assert view.moves("SCR-002")[0].document() == {
        "code": "TRN-001",
        "from": "SCR-001",
        "to": "SCR-002",
        "trigger": "Aggiungi ospite",
        "outcome": "Aggiungi ospite",
    }
    assert view.screen("SCR-009") is None


def test_without_a_prototype_the_screens_come_from_the_generated_mockup() -> None:
    document = copy.deepcopy(real_documents()["design"])
    package = document["package"]
    package["prototype"] = None
    package["generated_mockup"] = {
        "mockup": {
            "screens": [
                {"code": "SCR-001", "title": "Calcolo", "state": "DEFAULT", "markup": "<main/>"},
                {"code": None, "title": "Senza codice", "state": "DEFAULT", "markup": ""},
            ]
        },
        "requirement_ids_by_code": {},
    }

    view = knowledge.design_view(document)

    assert [(item.code, item.title, item.elements) for item in view.screens] == [
        ("SCR-001", "Calcolo", ())
    ]
    assert view.transitions == ()


def test_a_design_without_a_choice_has_no_chosen_alternative() -> None:
    document = copy.deepcopy(real_documents()["design"])
    document["package"]["owner_selected_alternative_id"] = None

    assert knowledge.design_view(document).chosen is None


def test_first_lines_and_labels_are_plain_texts() -> None:
    assert knowledge.first_line("\n  Controllo del nome \n\nSeconda riga") == "Controllo del nome"
    assert knowledge.first_line("   \n ") is None
    assert knowledge.first_line(None) is None
    assert knowledge.label({"accessible_name": None, "content": " Nome   ospite "}) == (
        "Nome ospite"
    )
    assert knowledge.label({"accessible_name": "Conferma", "content": "OK"}) == "Conferma"
    assert knowledge.label({"accessible_name": " ", "content": "  "}) is None


def test_a_valid_archive_reads_like_the_state_archive_without_changes(tmp_path: Path) -> None:
    project = with_archive(tmp_path, valid_archive())

    found = knowledge.load(project.knowledge)
    state = found.state()

    assert found.complete is True
    assert state is not None
    assert (state["aligned"], state["changes"], state["tasks"]) == (None, [], [])
