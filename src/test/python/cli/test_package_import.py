from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from orchestwin.cli import folder as knowledge
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows.package_import import swap_problem
from orchestwin.cli.http import UrlTransport
from orchestwin.cli.project import ProjectFolder

from .support.fake_studio import FakeProject, FakeStudio
from .support.folders import valid_archive, valid_files
from .support.terminal import TEST_PASSWORD, Run, link_folder, run_ut
from .support.transports import NoNetwork

EMAIL = "owner@example.com"
IMPORTS = "/project-imports"


def sign_in(tmp_path: Path, studio: FakeStudio) -> None:
    studio.add_account(EMAIL, TEST_PASSWORD)
    run = run_ut(
        ["login", "--studio", studio.address, "--email", EMAIL, "--password-stdin"],
        tmp_path,
        transport=UrlTransport(),
        answers=[TEST_PASSWORD],
    )
    assert run.status == 0, run.errors


def ut(tmp_path: Path, *arguments: str, answers: Sequence[str] = ()) -> Run:
    return run_ut(list(arguments), tmp_path, transport=UrlTransport(), answers=answers)


def offline(tmp_path: Path, *arguments: str, answers: Sequence[str] = ()) -> Run:
    return run_ut(list(arguments), tmp_path, transport=NoNetwork(), answers=answers)


def zipped(files: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def valid_bytes() -> dict[str, bytes]:
    return {name: content.encode("utf-8") for name, content in valid_files().items()}


def projects(tmp_path: Path, studio: FakeStudio) -> list[FakeProject]:
    run = ut(tmp_path, "status", "--all", "--json")
    assert run.status == 0, run.errors
    return [studio.project(str(item["id"])) for item in json.loads(run.output)["projects"]]


def test_a_zip_imported_where_nothing_is_linked_links_the_folder(tmp_path: Path) -> None:
    archive = tmp_path / "cartella.zip"
    archive.write_bytes(valid_archive())
    folder = tmp_path / "project"
    with FakeStudio(language="it") as studio:
        sign_in(tmp_path, studio)
        run = ut(tmp_path, "--lang", "it", "package", "import", str(archive), answers=["s"])
        link = ProjectFolder(folder).link()
        created = studio.project(link.project_id)
        name, stage = created.name, created.stage
        address = studio.address

    assert (run.status, run.errors) == (0, "")
    assert run.output.splitlines() == [
        f"Questa cartella ({folder}) non è collegata a un progetto. Dopo l'importazione la "
        "collego al nuovo progetto e metto la cartella di conoscenza in orchestwin/? [S/n] ",
        "Importo nello Studio il progetto «Calcolo mancia»...",
        "Importo nello Studio il progetto «Calcolo mancia»: fatto in 0 s.",
        "Nello Studio c'è il nuovo progetto «Calcolo mancia», creato dalla versione 1 della "
        "cartella di conoscenza di «Calcolo mancia».",
        "La catena Perché? è stata ricalcolata dai dati importati e verificata.",
        "La sintesi informativa learned.json non contiene snapshot completi e non ripristina osservazioni di sviluppo.",
        "Passi importati da approvare di nuovo prima di andare avanti: 5.",
        "Ho collegato questa cartella al nuovo progetto e ho messo la cartella di conoscenza in "
        "orchestwin/. Approva i passi importati con `ut init`, poi il design con `ut design`.",
    ]
    assert name == "Calcolo mancia"
    assert stage == "BRIEF"
    assert (link.studio, link.api_prefix, link.project_name) == (
        address,
        "/api/v1",
        "Calcolo mancia",
    )
    assert (link.mode, link.language, link.created_at) == (
        "DESIGN_ONLY",
        "it",
        "2026-09-29T09:00:00+00:00",
    )
    assert knowledge.verify(folder / "orchestwin").package_version == 1
    assert (folder / "orchestwin" / ".gitattributes").read_bytes() == b"* -text\n"


def test_a_folder_imported_where_another_project_is_linked_keeps_the_link(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source" / "orchestwin"
    knowledge.unpack(valid_archive(project_name="Lista ospiti"), source)
    with FakeStudio(language="en") as studio:
        sign_in(tmp_path, studio)
        existing = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="brief")
        link_folder(
            tmp_path / "project",
            project_id=existing.id,
            name=existing.name,
            studio=studio.address,
        )
        run = ut(
            tmp_path,
            "package",
            "import",
            str(Path("..") / "source" / "orchestwin"),
            "--name",
            "  Copy   of the list ",
        )
        names = [project.name for project in projects(tmp_path, studio)]
        bodies = [request.body for request in studio.requests if request.path.endswith(IMPORTS)]

    assert run.status == 0
    assert run.output.splitlines()[-5:] == [
        'The Studio has the new project "Copy of the list", created from version 1 of the '
        'knowledge folder of "Lista ospiti".',
        "The Why? chain was rebuilt from imported data and verified.",
        "The informative learned.json projection lacks complete snapshots and does not restore development observations.",
        "Imported steps to approve again before going on: 5.",
        'This folder stays linked to the project "Calcolo mancia" and was not touched: the new '
        'project "Copy of the list" is in the Studio, where you can open it.',
    ]
    assert "not linked to a project" not in run.output
    assert sorted(names) == ["Calcolo mancia", "Copy of the list"]
    assert len(bodies) == 1
    assert b'filename="orchestwin.zip"' in bodies[0]
    assert b"Copy of the list" in bodies[0]
    assert ProjectFolder(tmp_path / "project").link().project_id == existing.id
    assert not (tmp_path / "project" / "orchestwin").exists()


def test_the_offer_to_link_can_be_declined(tmp_path: Path) -> None:
    archive = tmp_path / "cartella.zip"
    archive.write_bytes(valid_archive())
    with FakeStudio(language="en") as studio:
        sign_in(tmp_path, studio)
        run = ut(tmp_path, "package", "import", str(archive), answers=["n"])
        names = [project.name for project in projects(tmp_path, studio)]

    assert run.status == 0
    assert run.output.splitlines()[-1] == (
        'This folder was not linked: open the project "Calcolo mancia" in the Studio to '
        "approve the imported steps."
    )
    assert names == ["Calcolo mancia"]
    assert ProjectFolder.find(tmp_path / "project") is None
    assert not (tmp_path / "project" / "orchestwin").exists()


def test_the_folder_of_a_clone_is_imported_and_linked_where_it_is(tmp_path: Path) -> None:
    folder = tmp_path / "project"
    knowledge.unpack(valid_archive(), folder / "orchestwin")
    (folder / "orchestwin" / ".gitattributes").unlink()
    with FakeStudio(language="en") as studio:
        sign_in(tmp_path, studio)
        run = ut(tmp_path, "package", "import", "orchestwin", answers=["y"])

    assert run.status == 0
    assert "Replace the folder anyway?" not in run.output
    assert ProjectFolder.find(folder) is not None
    assert knowledge.verify(folder / "orchestwin").package_version == 1
    assert (folder / "orchestwin" / ".gitattributes").exists()


def test_a_tampered_archive_sends_no_request(tmp_path: Path) -> None:
    files = valid_bytes()
    files["brief/brief.md"] += b"Aggiunto a mano.\n"
    archive = tmp_path / "cartella.zip"
    archive.write_bytes(zipped(files))

    english = offline(tmp_path, "package", "import", str(archive))
    italian = offline(tmp_path, "--lang", "it", "package", "import", str(archive))

    assert english.status == 7
    assert english.output == ""
    assert english.errors == (
        f"{archive} cannot be imported: the file brief/brief.md was changed or added after the "
        "publication (FOLDER_TAMPERED). Use the folder as the Studio published it, or its .zip "
        "file. No request was sent.\n"
    )
    assert italian.status == 7
    assert italian.errors.endswith("Nessuna richiesta è partita.\n")


def test_a_folder_with_line_endings_changed_by_git_is_explained(tmp_path: Path) -> None:
    source = tmp_path / "source"
    knowledge.unpack(valid_archive(), source)
    path = source / "requirements" / "requirements.md"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

    run = offline(tmp_path, "--lang", "it", "package", "import", str(source))

    assert run.status == 7
    assert run.errors == (
        f"{source} non si può importare: il file requirements/requirements.md ha i fine riga di "
        "Windows, forse cambiati da git (FOLDER_TAMPERED). Usa il file .zip originale, oppure "
        "scarica di nuovo la cartella con `ut package pull` nel suo progetto. Nessuna "
        "richiesta è partita.\n"
    )


def test_files_that_are_not_a_knowledge_folder_are_refused(tmp_path: Path) -> None:
    not_zip = tmp_path / "notes.zip"
    not_zip.write_bytes(b"these are notes, not an archive")
    partial = tmp_path / "partial.zip"
    files = valid_bytes()
    del files["design/design.json"]
    partial.write_bytes(zipped(files))

    garbage = offline(tmp_path, "package", "import", str(not_zip))
    missing = offline(tmp_path, "package", "import", str(partial))
    nowhere = offline(tmp_path, "package", "import", "nowhere.zip")

    assert garbage.status == 7
    assert garbage.errors == (
        f"{not_zip} is not the zip archive of a knowledge folder (FOLDER_ARCHIVE_INVALID). No "
        "request was sent.\n"
    )
    assert missing.status == 7
    assert "the file design/design.json is missing (FOLDER_DOCUMENT_MISSING)" in missing.errors
    assert nowhere.status == 1
    assert nowhere.errors == (
        f"{tmp_path / 'project' / 'nowhere.zip'} cannot be found. Give a knowledge folder, for "
        "example orchestwin, or its .zip file.\n"
    )


def test_an_archive_over_the_limits_sends_no_request(tmp_path: Path) -> None:
    large = tmp_path / "large.zip"
    with large.open("wb") as stream:
        stream.truncate(17 * 1024 * 1024)
    crowded = tmp_path / "crowded.zip"
    crowded.write_bytes(zipped({f"extra/{index:03d}.md": b"x" for index in range(401)}))

    english = offline(tmp_path, "package", "import", str(large))
    italian = offline(tmp_path, "--lang", "it", "package", "import", str(large))
    many = offline(tmp_path, "package", "import", str(crowded))

    assert english.status == 7
    assert english.errors == (
        f"{large} takes 17.0 MB: the Studio accepts at most 16 MB. No request was sent.\n"
    )
    assert italian.status == 7
    assert italian.errors == (
        f"{large} occupa 17,0 MB: lo Studio accetta al massimo 16 MB. Nessuna richiesta è "
        "partita.\n"
    )
    assert many.status == 7
    assert many.errors == (
        f"{crowded} contains too many files for the Studio (files: 401; at most 400). No "
        "request was sent.\n"
    )


def test_a_name_that_is_too_long_sends_no_request(tmp_path: Path) -> None:
    archive = tmp_path / "cartella.zip"
    archive.write_bytes(valid_archive())

    run = offline(tmp_path, "package", "import", str(archive), "--name", "n" * 121)

    assert run.status == 1
    assert run.errors == (
        "The name of the project is not valid: write it with at most 120 characters.\n"
    )


def test_a_folder_changed_by_hand_here_cancels_the_import(tmp_path: Path) -> None:
    archive = tmp_path / "cartella.zip"
    archive.write_bytes(valid_archive())
    here = tmp_path / "project" / "orchestwin"
    here.mkdir(parents=True)
    (here / "notes.md").write_bytes(b"Mie note.\n")

    run = offline(tmp_path, "package", "import", str(archive), answers=["y", "n"])

    assert run.status == 1
    assert run.output.splitlines()[1:] == [
        "The folder orchestwin/ is no longer as the Studio published it: the first file that "
        "differs is orchestwin.json (FOLDER_DOCUMENT_MISSING). If it is replaced, the changes "
        "made by hand are lost.",
        "Replace the folder anyway? [y/N] ",
        "Nothing was imported: the folder orchestwin/ was left as it was.",
    ]
    assert (here / "notes.md").read_bytes() == b"Mie note.\n"
    assert ProjectFolder.find(tmp_path / "project") is None


def test_a_refusal_of_the_studio_leaves_the_folder_unlinked(tmp_path: Path) -> None:
    archive = tmp_path / "cartella.zip"
    archive.write_bytes(valid_archive())
    with FakeStudio(language="en") as studio:
        sign_in(tmp_path, studio)
        studio.fail_next(
            "POST",
            IMPORTS,
            status=503,
            body={"detail": {"code": "PROJECT_IMPORT_SERVICE_UNAVAILABLE", "location": None}},
        )
        busy = ut(tmp_path, "package", "import", str(archive), answers=["y"])
        studio.fail_next(
            "POST",
            IMPORTS,
            status=413,
            body={"detail": {"code": "FOLDER_ARCHIVE_TOO_LARGE", "location": None}},
        )
        large = ut(tmp_path, "--lang", "it", "package", "import", str(archive), answers=["s"])

    assert busy.status == 1
    assert busy.output.splitlines()[1:] == [
        'Importing the project "Calcolo mancia" into the Studio...',
        'Importing the project "Calcolo mancia" into the Studio: not completed after 0 s.',
    ]
    assert busy.errors == "The Studio cannot import projects right now. Try again later.\n"
    assert large.status == 1
    assert large.output.splitlines()[1:] == [
        "Importo nello Studio il progetto «Calcolo mancia»...",
        "Importo nello Studio il progetto «Calcolo mancia»: non completato dopo 0 s.",
    ]
    assert large.errors == (
        "Lo Studio ha rifiutato l'archivio perché è troppo grande: il limite è 16 MB "
        "(FOLDER_ARCHIVE_TOO_LARGE).\n"
    )
    assert ProjectFolder.find(tmp_path / "project") is None
    assert not (tmp_path / "project" / "orchestwin").exists()


def test_a_folder_that_cannot_be_unpacked_after_the_import_keeps_the_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "cartella.zip"
    archive.write_bytes(valid_archive())
    here = tmp_path / "project" / "orchestwin"
    knowledge.unpack(valid_archive(), here)

    def locked(source: Path, destination: Path) -> None:
        raise PermissionError(13, "The file is in use", str(source))

    with FakeStudio(language="en") as studio:
        sign_in(tmp_path, studio)
        monkeypatch.setattr(knowledge, "_rename", locked)
        run = ut(tmp_path, "package", "import", str(archive), answers=["y"])

    assert run.status == 1
    assert run.errors == (
        "This folder is now linked to the new project, but the knowledge folder could not be "
        f"put in orchestwin/: perhaps one of its files is open in another program ({here}). No "
        "new import is needed: approve the imported steps with `ut init`, then the design with "
        "`ut design`, and `ut package publish` will download the folder.\n"
    )
    assert ProjectFolder(tmp_path / "project").link().project_name == "Calcolo mancia"
    assert knowledge.verify(here).package_version == 1


def test_a_failed_swap_names_a_file_only_when_it_is_inside_the_folder(tmp_path: Path) -> None:
    folder = tmp_path / "project" / "orchestwin"
    inside = CliError(
        "FOLDER_SWAP_FAILED",
        values={"folder": str(folder), "path": str(folder / "design" / "mockup.html")},
    )
    itself = CliError("FOLDER_SWAP_FAILED", values={"folder": str(folder), "path": str(folder)})
    staging = CliError(
        "FOLDER_SWAP_FAILED",
        values={"folder": str(folder), "path": str(folder.parent / ".orchestwin.new-1")},
    )
    other = CliError("FOLDER_NOT_VERIFIED", values={"code": "FOLDER_TAMPERED", "path": "x"})

    assert swap_problem(inside) is inside
    assert swap_problem(other) is other
    for error in (itself, staging):
        changed = swap_problem(error)
        assert (changed.code, changed.status) == ("FOLDER_SWAP_FAILED", 1)
        assert changed.values == {**error.values, "reason": "FOLDER_IN_USE"}
        assert swap_problem(changed) is changed


def test_the_import_needs_the_sign_in_after_the_checks(tmp_path: Path) -> None:
    archive = tmp_path / "cartella.zip"
    archive.write_bytes(valid_archive())

    run = offline(tmp_path, "package", "import", str(archive), answers=["n"])

    assert run.status == 3
    assert run.errors == (
        "You are not signed in to the Studio http://127.0.0.1:8000. Sign in with `ut login`.\n"
    )
