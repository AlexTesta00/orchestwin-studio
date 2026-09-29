from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from orchestwin.cli import folder as knowledge
from orchestwin.cli.commands.package import moment_text
from orchestwin.cli.http import Reply, UrlTransport, unreachable
from orchestwin.cli.messages import known

from .support.fake_studio import FakeProject, FakeStudio
from .support.folders import valid_archive, valid_files
from .support.terminal import TEST_PASSWORD, Run, link_folder, run_ut, store_session
from .support.transports import NoNetwork

EMAIL = "owner@example.com"
WIDE = {"COLUMNS": "200"}
OS_FILES = (".DS_Store", "Thumbs.db", "desktop.ini")
EDITED = "brief/brief.md"
ARCHIVE = "/projects/{project_id}/knowledge-packages/{version_number}/archive"
PUBLISHING = {
    "it": "Preparo la cartella di conoscenza nello Studio",
    "en": "Preparing the knowledge folder in the Studio",
}
DOWNLOADING = {
    "it": "Scarico la cartella di conoscenza",
    "en": "Downloading the knowledge folder",
}
NOT_COMPLETED = {
    "it": "{label}: non completato dopo 0 s.",
    "en": "{label}: not completed after 0 s.",
}
DONE = {"it": "{label}: fatto in 0 s.", "en": "{label}: done in 0 s."}


class Offline:
    def __init__(self) -> None:
        self.attempts: list[str] = []

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> Reply:
        self.attempts.append(method)
        raise unreachable(url, sent=method != "GET")


def sign_in(tmp_path: Path, studio: FakeStudio) -> None:
    studio.add_account(EMAIL, TEST_PASSWORD)
    run = run_ut(
        ["login", "--studio", studio.address, "--email", EMAIL, "--password-stdin"],
        tmp_path,
        transport=UrlTransport(),
        answers=[TEST_PASSWORD],
    )
    assert run.status == 0, run.errors


def progress(label: str, outcome: Mapping[str, str], language: str = "en") -> list[str]:
    return [f"{label}...", outcome[language].format(label=label)]


def seeded(tmp_path: Path, studio: FakeStudio, *, through: str = "design") -> FakeProject:
    sign_in(tmp_path, studio)
    project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through=through)
    link_folder(
        tmp_path / "project", project_id=project.id, name=project.name, studio=studio.address
    )
    return project


def ut(tmp_path: Path, *arguments: str, answers: Sequence[str] = ()) -> Run:
    return run_ut(
        list(arguments), tmp_path, transport=UrlTransport(), answers=answers, variables=WIDE
    )


def offline(tmp_path: Path, *arguments: str) -> Run:
    return run_ut(list(arguments), tmp_path, transport=NoNetwork(), variables=WIDE)


def knowledge_folder(tmp_path: Path) -> Path:
    return tmp_path / "project" / "orchestwin"


def write_folder(folder: Path, files: Mapping[str, str]) -> None:
    for name, content in files.items():
        path = folder.joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))


def edit(folder: Path, name: str = EDITED) -> None:
    path = folder.joinpath(*name.split("/"))
    path.write_bytes(path.read_bytes() + b"Aggiunto a mano.\n")


def second_version(studio: FakeStudio, project: FakeProject, tmp_path: Path) -> None:
    studio.project(project.id).mark_knowledge_changed()
    assert ut(tmp_path, "package", "publish").status == 0


def table(output: str) -> list[list[str]]:
    lines = output.splitlines()
    rule = next(index for index, line in enumerate(lines) if re.fullmatch(r"[- ]+", line))
    rows = [re.split(r"\s{2,}", lines[rule - 1].strip())]
    rows.extend(re.split(r"\s{2,}", line.strip()) for line in lines[rule + 1 :] if line.strip())
    return rows


def test_the_ignored_names_cover_the_files_left_by_an_operating_system(tmp_path: Path) -> None:
    folder = tmp_path / "orchestwin"
    write_folder(folder, valid_files())
    for name in OS_FILES:
        (folder / name).write_bytes(b"\x00\x01 not text")
        (folder / "design" / name).write_bytes(b"\x00\x01 not text")

    assert {".gitattributes", *OS_FILES} <= knowledge.IGNORED_NAMES
    assert set(knowledge.read_files(folder)) == set(valid_files())
    assert knowledge.verify(folder).package_version == 1
    with zipfile.ZipFile(io.BytesIO(knowledge.pack(folder))) as archive:
        assert set(archive.namelist()) == set(valid_files())


def test_verify_accepts_a_good_folder_and_the_files_of_the_system(tmp_path: Path) -> None:
    link_folder(tmp_path / "project")
    folder = knowledge_folder(tmp_path)
    knowledge.unpack(valid_archive(), folder)
    for name in OS_FILES:
        (folder / name).write_bytes(b"\x00 system file")

    english = offline(tmp_path, "package", "verify")
    italian = offline(tmp_path, "--lang", "it", "package", "verify")

    summary = knowledge.summary(folder)
    assert summary is not None
    short = summary.content_hash[:12]
    assert (english.status, english.errors) == (0, "")
    assert english.output == (
        'The knowledge folder orchestwin/ passes the verification: version 1 of "Calcolo '
        f'mancia", content hash {short}. Files: {len(valid_files())}.\n'
    )
    assert italian.output == (
        "La cartella di conoscenza orchestwin/ supera la verifica: versione 1 di «Calcolo "
        f"mancia», impronta {short}. File: {len(valid_files())}.\n"
    )


def test_verify_names_the_file_changed_by_hand(tmp_path: Path) -> None:
    link_folder(tmp_path / "project")
    folder = knowledge_folder(tmp_path)
    knowledge.unpack(valid_archive(), folder)
    edit(folder)

    english = offline(tmp_path, "package", "verify")
    italian = offline(tmp_path, "--lang", "it", "package", "verify")

    assert english.status == 7
    assert english.output == ""
    assert english.errors == (
        "The knowledge folder orchestwin/ does not pass the verification: the file "
        "brief/brief.md was changed or added after the publication (FOLDER_TAMPERED). To go "
        "back to the published version download it again with `ut package pull`; the changes "
        "made by hand will be lost.\n"
    )
    assert italian.status == 7
    assert italian.errors.startswith(
        "La cartella di conoscenza orchestwin/ non supera la verifica: il file brief/brief.md "
        "è stato cambiato o aggiunto dopo la pubblicazione (FOLDER_TAMPERED)."
    )


def test_verify_explains_the_line_endings_changed_by_git(tmp_path: Path) -> None:
    link_folder(tmp_path / "project")
    folder = knowledge_folder(tmp_path)
    knowledge.unpack(valid_archive(), folder)
    path = folder / "brief" / "brief.md"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

    english = offline(tmp_path, "package", "verify")
    italian = offline(tmp_path, "--lang", "it", "package", "verify")

    assert english.status == 7
    assert english.errors == (
        "The file brief/brief.md of the knowledge folder orchestwin/ has Windows line endings: "
        "git probably changed them, as it can convert them on Windows when it saves or "
        "downloads files. The content is the same, but the content hash no longer matches "
        "(FOLDER_TAMPERED). Download the folder again with `ut package pull`: it comes with a "
        ".gitattributes file that stops git from changing them again.\n"
    )
    assert italian.status == 7
    assert italian.errors.startswith(
        "Il file brief/brief.md della cartella di conoscenza orchestwin/ ha i fine riga di "
        "Windows: probabilmente li ha cambiati git"
    )


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ("missing_file", "the file design/mockup.html is missing (FOLDER_DOCUMENT_MISSING)"),
        ("missing_folder", "There is no knowledge folder in orchestwin/ (FOLDER_MISSING)."),
        ("manifest", "orchestwin.json cannot be read as it should (FOLDER_DOCUMENT_INVALID)"),
    ],
)
def test_verify_explains_every_other_problem(tmp_path: Path, change: str, expected: str) -> None:
    link_folder(tmp_path / "project")
    folder = knowledge_folder(tmp_path)
    if change != "missing_folder":
        knowledge.unpack(valid_archive(), folder)
    if change == "missing_file":
        (folder / "design" / "mockup.html").unlink()
    if change == "manifest":
        (folder / "orchestwin.json").write_bytes(b"{not json")

    run = offline(tmp_path, "package", "verify")

    assert run.status == 7
    assert expected in run.errors


def test_verify_outside_a_linked_folder_checks_the_folder_here(tmp_path: Path) -> None:
    folder = tmp_path / "project" / "orchestwin"
    knowledge.unpack(valid_archive(), folder)

    found = offline(tmp_path, "package", "verify")
    empty = tmp_path / "empty"
    empty.mkdir()
    missing = run_ut(
        ["package", "verify"], tmp_path, transport=NoNetwork(), working_directory=empty
    )

    assert found.status == 0
    assert found.output.startswith("The knowledge folder orchestwin/ passes the verification")
    assert missing.status == 6


def test_the_state_before_anything_is_published(tmp_path: Path) -> None:
    with FakeStudio(language="it") as studio:
        seeded(tmp_path, studio)
        run = ut(tmp_path, "--lang", "it", "package")

    assert run.status == 0
    assert run.output.splitlines() == [
        "Cartella di conoscenza di «Calcolo mancia»",
        "==========================================",
        "In questa cartella (orchestwin/): non c'è ancora.",
        "Nello Studio: nessuna versione pubblicata.",
        "",
        "Quando i cinque passi sono approvati, pubblica la cartella con `ut package publish`.",
    ]


def test_publish_brings_the_approved_steps_before_the_design(tmp_path: Path) -> None:
    with FakeStudio(language="it") as studio:
        project = seeded(tmp_path, studio, through="requirements")
        run = ut(tmp_path, "--lang", "it", "package", "publish")
        versions = studio.project(project.id).knowledge_versions()

    assert run.status == 0, run.errors
    assert run.output.splitlines()[-1] == (
        "Pubblicata la versione 1 della cartella di conoscenza e scaricata in orchestwin/. "
        f"File: {versions[0]['file_count']}."
    )
    folder = knowledge.verify(knowledge_folder(tmp_path))
    assert folder.package_version == 1
    assert folder.manifest["progress"] == {
        "approved": ["brief", "team", "twins", "requirements"],
        "pending": "design",
        "complete": False,
    }
    summary = knowledge.summary(knowledge_folder(tmp_path))
    assert summary is not None
    assert summary.progress == ("brief", "team", "twins", "requirements")
    assert (summary.pending, summary.complete) == ("design", False)


def test_publish_names_the_step_that_is_missing(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        seeded(tmp_path, studio, through="twins")
        studio.fail_next(
            "POST",
            "/projects/{project_id}/knowledge-packages",
            status=409,
            body={"detail": {"code": "BRIEF_APPROVAL_REQUIRED"}},
        )
        brief = ut(tmp_path, "package", "publish")
        studio.fail_next(
            "POST",
            "/projects/{project_id}/knowledge-packages",
            status=409,
            body={"detail": {"code": "DESIGN_APPROVAL_REQUIRED"}},
        )
        design = ut(tmp_path, "--lang", "it", "package", "publish")

    assert brief.status == 1
    assert brief.output.splitlines() == progress(PUBLISHING["en"], NOT_COMPLETED)
    assert brief.errors == (
        "The knowledge folder cannot be published yet: the brief is not approved. "
        "Approve it with `ut init`, then try again.\n"
    )
    assert design.status == 1
    assert design.output.splitlines() == progress(PUBLISHING["it"], NOT_COMPLETED, "it")
    assert design.errors == (
        "La cartella di conoscenza non si può ancora pubblicare: il design non è approvato. "
        "Sceglilo e approvalo con `ut design`, poi riprova.\n"
    )
    assert not knowledge_folder(tmp_path).exists()


def test_publish_creates_a_version_and_then_says_nothing_changed(tmp_path: Path) -> None:
    with FakeStudio(language="it") as studio:
        project = seeded(tmp_path, studio)
        first = ut(tmp_path, "--lang", "it", "package", "publish")
        again = ut(tmp_path, "package", "publish")
        state = ut(tmp_path, "package")
        versions = studio.project(project.id).knowledge_versions()
        downloads = [request for request in studio.requests if request.path.endswith("/archive")]

    files = versions[0]["file_count"]
    assert first.status == 0
    assert first.output.splitlines() == [
        *progress(PUBLISHING["it"], DONE, "it"),
        *progress(DOWNLOADING["it"], DONE, "it"),
        "Pubblicata la versione 1 della cartella di conoscenza e scaricata in orchestwin/. "
        f"File: {files}.",
    ]
    assert knowledge.verify(knowledge_folder(tmp_path)).package_version == 1
    assert (knowledge_folder(tmp_path) / ".gitattributes").read_bytes() == b"* -text\n"
    assert again.status == 0
    assert again.output.splitlines()[-1] == (
        "Nothing changed since the last version: the knowledge folder in orchestwin/ is "
        "already up to date (version 1)."
    )
    assert len(versions) == 1
    assert len(downloads) == 1
    date = moment_text(versions[0]["created_at"])
    assert state.output.splitlines()[2:] == [
        f"In this folder (orchestwin/): version 1 of {date}, it passes the verification.",
        f"In the Studio: version 1 of {date}.",
        "",
        "The folder here is up to date. After new approvals in the Studio publish a new "
        "version with `ut package publish`.",
    ]


def test_publish_with_nothing_changed_downloads_a_missing_folder_again(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        project = seeded(tmp_path, studio)
        assert ut(tmp_path, "package", "publish").status == 0
        shutil.rmtree(knowledge_folder(tmp_path))
        run = ut(tmp_path, "--lang", "it", "package", "publish")
        versions = studio.project(project.id).knowledge_versions()

    assert run.status == 0
    assert len(versions) == 1
    assert run.output.splitlines()[-1] == (
        "Niente è cambiato dall'ultima versione pubblicata: ho scaricato di nuovo la versione 1 "
        f"in orchestwin/. File: {versions[0]['file_count']}."
    )
    assert knowledge.verify(knowledge_folder(tmp_path)).package_version == 1


def test_publish_asks_before_replacing_a_folder_changed_by_hand(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        project = seeded(tmp_path, studio)
        assert ut(tmp_path, "package", "publish").status == 0
        edit(knowledge_folder(tmp_path))
        studio.project(project.id).mark_knowledge_changed()
        kept = ut(tmp_path, "package", "publish", answers=["n"])
        edited = (knowledge_folder(tmp_path) / EDITED).read_bytes()
        studio.project(project.id).mark_knowledge_changed()
        replaced = ut(tmp_path, "--lang", "it", "package", "publish", answers=["s"])

    assert kept.status == 1
    assert kept.output.splitlines()[2:] == [
        "The folder orchestwin/ is no longer as the Studio published it: the first file that "
        "differs is brief/brief.md (FOLDER_TAMPERED). If it is replaced, the changes made by "
        "hand are lost.",
        "Replace the folder anyway? [y/N] ",
        "Version 2 is published in the Studio, but the folder orchestwin/ was left as it was. "
        "Download it when you want with `ut package pull`.",
    ]
    assert edited.endswith(b"Aggiunto a mano.\n")
    assert replaced.status == 0
    assert replaced.output.splitlines()[-1].startswith("Pubblicata la versione 3")
    assert knowledge.verify(knowledge_folder(tmp_path)).package_version == 3


def test_pull_downloads_the_latest_and_a_given_version(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        project = seeded(tmp_path, studio)
        assert ut(tmp_path, "package", "publish").status == 0
        second_version(studio, project, tmp_path)
        older = ut(tmp_path, "--lang", "it", "package", "pull", "--version", "1")
        state = ut(tmp_path, "package")
        history = ut(tmp_path, "--lang", "it", "package", "history")
        latest = ut(tmp_path, "package", "pull")
        versions = studio.project(project.id).knowledge_versions()

    files = versions[0]["file_count"]
    assert older.status == 0
    assert older.output.splitlines() == [
        *progress(DOWNLOADING["it"], DONE, "it"),
        f"Scaricata la versione 1 della cartella di conoscenza in orchestwin/. File: {files}.",
    ]
    assert "The folder here is older: update it to version 2 with `ut package pull`." in (
        state.output
    )
    assert table(history.output) == [
        ["Versione", "Data", "Impronta", "File"],
        [
            "2",
            moment_text(versions[1]["created_at"]),
            str(versions[1]["content_hash"])[:12],
            str(files),
        ],
        [
            "1 (qui)",
            moment_text(versions[0]["created_at"]),
            str(versions[0]["content_hash"])[:12],
            str(files),
        ],
    ]
    assert latest.status == 0
    assert latest.output.splitlines()[-1] == (
        f"Version 2 of the knowledge folder is downloaded into orchestwin/. Files: {files}."
    )
    assert knowledge.verify(knowledge_folder(tmp_path)).package_version == 2


def test_pull_of_a_version_that_does_not_exist(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        seeded(tmp_path, studio)
        nothing = ut(tmp_path, "package", "pull")
        assert ut(tmp_path, "package", "publish").status == 0
        english = ut(tmp_path, "package", "pull", "--version", "4")
        italian = ut(tmp_path, "--lang", "it", "package", "pull", "--version", "0")

    assert nothing.status == 1
    assert "has not published a knowledge folder for this project yet" in nothing.errors
    assert english.status == 1
    assert english.errors == (
        "Version 4 of the knowledge folder does not exist in the Studio: the latest is 1. See "
        "the versions with `ut package history`.\n"
    )
    assert italian.status == 1
    assert italian.errors.startswith("La versione 0 della cartella di conoscenza non esiste")


def test_pull_asks_before_replacing_a_folder_changed_by_hand(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        seeded(tmp_path, studio)
        assert ut(tmp_path, "package", "publish").status == 0
        folder = knowledge_folder(tmp_path)
        edit(folder)
        (folder / "notes.md").write_bytes(b"Mie note.\n")
        declined = ut(tmp_path, "--yes", "--lang", "it", "package", "pull", answers=["n"])
        closed = ut(tmp_path, "--yes", "package", "pull")
        still_there = (folder / "notes.md").exists()
        accepted = ut(tmp_path, "--yes", "package", "pull", answers=["yes"])

    assert declined.status == 1
    assert declined.output.splitlines() == [
        "La cartella orchestwin/ non è più come l'ha pubblicata lo Studio: il primo file "
        "diverso è brief/brief.md (FOLDER_TAMPERED). Se la sostituisco, le modifiche fatte a "
        "mano vanno perse.",
        "Sostituisco comunque la cartella? [s/N] ",
        "Non ho toccato la cartella orchestwin/.",
    ]
    assert closed.status == 1
    assert "The input closed while an answer was awaited" in closed.errors
    assert still_there
    assert accepted.status == 0
    assert not (folder / "notes.md").exists()
    assert knowledge.verify(folder).package_version == 1


def test_pull_over_line_endings_changed_by_git_asks_nothing(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        seeded(tmp_path, studio)
        assert ut(tmp_path, "package", "publish").status == 0
        path = knowledge_folder(tmp_path) / "brief" / "brief.md"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        state = ut(tmp_path, "package")
        run = ut(tmp_path, "package", "pull")

    assert "has Windows line endings, perhaps changed by git (FOLDER_TAMPERED)." in state.output
    assert "it comes with a .gitattributes file" in state.output
    assert run.status == 0
    assert "Replace the folder anyway?" not in run.output
    assert b"\r\n" not in path.read_bytes()


def test_a_folder_that_cannot_be_swapped_is_left_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def locked(source: Path, destination: Path) -> None:
        raise PermissionError(13, "The file is in use", str(source))

    with FakeStudio(language="en") as studio:
        project = seeded(tmp_path, studio)
        assert ut(tmp_path, "package", "publish").status == 0
        folder = knowledge_folder(tmp_path)
        before = knowledge.read_files(folder)
        monkeypatch.setattr(knowledge, "_rename", locked)
        pulled = ut(tmp_path, "package", "pull")
        studio.project(project.id).mark_knowledge_changed()
        published = ut(tmp_path, "--lang", "it", "package", "publish")

    assert pulled.status == 1
    assert pulled.output.splitlines() == progress(DOWNLOADING["en"], NOT_COMPLETED)
    assert pulled.errors == (
        f"The folder {folder} could not be replaced: perhaps one of its files is open in another "
        "program, for example an editor or a folder window. The previous version is still in "
        "place: close the program and launch the command again.\n"
    )
    assert published.status == 1
    assert published.output.splitlines() == [
        *progress(PUBLISHING["it"], DONE, "it"),
        *progress(DOWNLOADING["it"], NOT_COMPLETED, "it"),
    ]
    assert published.errors.startswith(f"Non ho potuto sostituire la cartella {folder}: forse")
    assert knowledge.read_files(folder) == before
    assert sorted(path.name for path in folder.parent.iterdir()) == [".orchestwin", "orchestwin"]


def test_a_download_that_fails_leaves_the_folder_and_never_says_done(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        seeded(tmp_path, studio)
        assert ut(tmp_path, "package", "publish").status == 0
        folder = knowledge_folder(tmp_path)
        before = knowledge.read_files(folder)
        studio.fail_next("GET", ARCHIVE, status=200, body=b"not the archive of the folder")
        damaged = ut(tmp_path, "package", "pull")
        studio.fail_next(
            "GET",
            ARCHIVE,
            status=503,
            body={"detail": {"code": "KNOWLEDGE_PACKAGE_SERVICE_UNAVAILABLE"}},
        )
        refused = ut(tmp_path, "--lang", "it", "package", "pull")

    assert damaged.status == 7
    assert damaged.output.splitlines() == progress(DOWNLOADING["en"], NOT_COMPLETED)
    assert "(ARCHIVE_HASH_MISMATCH: " in damaged.errors
    assert refused.status == 1
    assert refused.output.splitlines() == progress(DOWNLOADING["it"], NOT_COMPLETED, "it")
    assert refused.errors == (
        "Lo Studio non può preparare la cartella di conoscenza in questo momento. Riprova più "
        "tardi.\n"
    )
    assert knowledge.read_files(folder) == before


def test_a_file_named_by_the_system_is_shown_when_the_swap_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with FakeStudio(language="en") as studio:
        seeded(tmp_path, studio)
        assert ut(tmp_path, "package", "publish").status == 0
        folder = knowledge_folder(tmp_path)
        open_file = folder / "design" / "mockup.html"

        def locked(source: Path, destination: Path) -> None:
            raise PermissionError(13, "The file is in use", str(open_file))

        monkeypatch.setattr(knowledge, "_rename", locked)
        run = ut(tmp_path, "package", "pull")

    assert run.status == 1
    assert run.errors == (
        f"The folder {folder} could not be replaced: the file {open_file} is perhaps open in "
        "another program, for example an editor. The previous version is still in place: close "
        "the program and launch the command again.\n"
    )


def test_the_state_of_the_folder_when_the_studio_cannot_be_asked(tmp_path: Path) -> None:
    link_folder(tmp_path / "project")
    knowledge.unpack(valid_archive(), knowledge_folder(tmp_path))
    edit(knowledge_folder(tmp_path))

    signed_out = offline(tmp_path, "--lang", "it", "package")
    store_session(tmp_path)
    unreachable_run = run_ut(["package"], tmp_path, transport=Offline(), variables=WIDE)

    assert signed_out.status == 0
    assert signed_out.output.splitlines()[2:] == [
        "In questa cartella (orchestwin/): versione 1, ma non supera la verifica: il primo file "
        "diverso da quello pubblicato è brief/brief.md (FOLDER_TAMPERED).",
        "Nello Studio: non lo so, non hai eseguito l'accesso a http://127.0.0.1:8000. Accedi "
        "con `ut login`.",
        "",
        "Per tornare alla versione pubblicata scarica di nuovo la cartella con "
        "`ut package pull`: le modifiche fatte a mano andranno perse. Per vedere il problema "
        "lancia `ut package verify`.",
    ]
    assert unreachable_run.status == 0
    assert "In the Studio: unknown, the Studio http://127.0.0.1:8000 does not answer." in (
        unreachable_run.output
    )


def test_publish_and_pull_need_the_studio_and_never_send_a_publication_twice(
    tmp_path: Path,
) -> None:
    store_session(tmp_path)
    link_folder(tmp_path / "project")
    publishing = Offline()
    pulling = Offline()

    published = run_ut(["package", "publish"], tmp_path, transport=publishing)
    pulled = run_ut(["--lang", "it", "package", "pull"], tmp_path, transport=pulling)

    assert published.status == 4
    assert publishing.attempts == ["POST"]
    assert published.output.splitlines() == progress(PUBLISHING["en"], NOT_COMPLETED)
    assert published.errors == (
        "The Studio at http://127.0.0.1:8000 does not answer. Check that it is running, then "
        "try again.\n"
    )
    assert pulled.status == 4
    assert pulling.attempts == ["GET", "GET", "GET"]
    assert pulled.errors.startswith("Lo Studio all'indirizzo http://127.0.0.1:8000 non risponde.")
    assert not knowledge_folder(tmp_path).exists()


def test_history_without_versions_and_outside_the_studio(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        seeded(tmp_path, studio)
        empty = ut(tmp_path, "--lang", "it", "package", "history")
    link_folder(tmp_path / "other")
    signed_out = run_ut(
        ["package", "history"],
        tmp_path,
        transport=NoNetwork(),
        working_directory=tmp_path / "other",
    )

    assert empty.status == 0
    assert empty.output.splitlines()[-1] == (
        "Lo Studio non ha ancora pubblicato versioni della cartella di conoscenza. Pubblicane "
        "una con `ut package publish`."
    )
    assert signed_out.status == 3
    assert signed_out.errors.startswith("You are not signed in to the Studio")


def test_every_key_chosen_at_run_time_exists() -> None:
    from orchestwin.cli.commands import package as command
    from orchestwin.cli.flows import package_import

    keys = [
        *command.STUDIO_KEYS.values(),
        *command.VERIFY_KEYS.values(),
        *package_import.PROBLEM_KEYS.values(),
        "package.verify_line_endings",
        "package.verify_generic",
        "package.import_line_endings",
        "package.import_not_verified",
        *(
            f"package.advice_{name}"
            for name in (
                "publish_first",
                "download",
                "older",
                "newer",
                "different",
                "up_to_date",
                "restore",
                "line_endings",
            )
        ),
    ]

    assert [key for key in keys if not known(key)] == []


def test_dates_are_shown_in_utc_without_the_locale() -> None:
    assert moment_text("2026-09-29T08:00:05Z") == "2026-09-29 08:00 UTC"
    assert moment_text("2026-09-29T10:30:00+02:00") == "2026-09-29 08:30 UTC"
    assert moment_text("2026-09-29T08:00:00") == "2026-09-29 08:00 UTC"
    assert moment_text("yesterday") == "yesterday"
    assert moment_text(None) == "-"


def test_the_manifest_of_a_pulled_folder_matches_the_studio(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        project = seeded(tmp_path, studio)
        assert ut(tmp_path, "package", "publish").status == 0
        version = studio.project(project.id).knowledge_versions()[0]

    manifest = json.loads(
        (knowledge_folder(tmp_path) / "orchestwin.json").read_bytes().decode("utf-8")
    )
    assert manifest["package"]["content_hash"] == version["content_hash"]
    assert manifest["package"]["version_number"] == 1
