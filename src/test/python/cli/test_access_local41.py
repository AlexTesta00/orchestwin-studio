from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from orchestwin.cli.flows import test_run as run_flow
from orchestwin.cli.http import UrlTransport
from orchestwin.cli.project import ProjectFolder

from .support.fake_studio import LOCAL_OWNER, LOCAL_OWNER_EMAIL, FakeStudio
from .support.processes import FakeCommit, FakeFile, ScriptedProcesses, script_repository
from .support.terminal import (
    PROJECT_ID,
    PROJECT_NAME,
    TEST_PASSWORD,
    Run,
    link_folder,
    read_session,
    run_ut,
    store_session,
)
from .support.transports import API, ScriptedTransport
from .test_test_command import ADDRESS, HIDDEN, TEXTS
from .test_test_run_flow import FakeSite

LOCAL = "http://127.0.0.1:8000"
REMOTE = "https://studio.example.test"
MODE_PATH = f"{API}/auth/mode"
LOCAL_MODE = {"access_mode": "LOCAL_OWNER", "registration_open": False}
STATUS_KEYS = {
    "schema_version",
    "kind",
    "source",
    "reason",
    "studio",
    "project",
    "current_stage",
    "next_action",
    "next_command",
    "steps",
    "knowledge_folder",
    "spending",
    "alignment",
    "tests",
    "learning",
    "sections",
    "knowledge_alignment",
}
SIGN_IN_PATHS = (f"{API}/auth/login", f"{API}/auth/refresh", f"{API}/auth/logout")
COMMIT = FakeCommit(
    "1" * 40,
    "Add the amount field",
    files=(FakeFile("src/app.js", added=1, removed=1),),
    diff="diff --git a/src/app.js b/src/app.js\n@@ -1 +1 @@\n-const tip = 0;\n+const tip = 1;\n",
)


def ut(tmp_path: Path, *arguments: str, language: str = "en", answers: Sequence[str] = ()) -> Run:
    return run_ut(
        ["--lang", language, *arguments], tmp_path, transport=UrlTransport(), answers=answers
    )


def paths(studio: FakeStudio) -> list[str]:
    return [request.path for request in studio.requests]


def authorizations(studio: FakeStudio) -> set[str | None]:
    return {request.headers.get("authorization") for request in studio.requests}


def test_status_lists_the_projects_of_a_local_studio_without_authorization(
    tmp_path: Path,
) -> None:
    transport = ScriptedTransport().expect("GET", MODE_PATH, body=LOCAL_MODE)
    transport.expect(
        "GET",
        f"{API}/projects",
        body=[
            {
                "id": PROJECT_ID,
                "display_name": PROJECT_NAME,
                "current_stage": "USER_TWINS",
                "next_action": "CONFIRM_TWINS",
            }
        ],
    )

    run = run_ut(["status"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    assert run.output.splitlines()[0] == f"Projects in the Studio {LOCAL}"
    assert PROJECT_NAME in run.output
    assert [request.path for request in transport.sent] == [MODE_PATH, f"{API}/projects"]
    assert [request.header("authorization") for request in transport.sent] == [None, None]
    transport.assert_done()


def test_a_studio_without_the_route_of_the_access_mode_keeps_the_sign_in(tmp_path: Path) -> None:
    link_folder(tmp_path / "project")
    missing = {"detail": "Not Found"}
    asked = ScriptedTransport().expect("GET", MODE_PATH, status=404, body=missing)
    started = ScriptedTransport().expect("GET", MODE_PATH, status=404, body=missing)

    status = run_ut(["status", "--json"], tmp_path, transport=asked)
    init = run_ut(
        ["init", "--project", PROJECT_ID],
        tmp_path,
        transport=started,
        working_directory=tmp_path / "other",
    )

    document = json.loads(status.output)
    assert (document["source"], document["reason"]) == ("folder", "not_signed_in")
    assert init.status == 3
    assert "ut login" in init.errors
    assert init.output == ""
    for transport in (asked, started):
        assert [request.path for request in transport.sent] == [MODE_PATH]
        transport.assert_done()


def test_a_studio_of_another_computer_is_never_asked_without_a_sign_in(tmp_path: Path) -> None:
    link_folder(tmp_path / "project", studio=REMOTE)
    transport = ScriptedTransport()

    status = run_ut(["status", "--json"], tmp_path, transport=transport)
    package = run_ut(["package"], tmp_path, transport=transport)
    tasks = run_ut(["tasks"], tmp_path, transport=transport)
    init = run_ut(["init"], tmp_path, transport=transport)

    document = json.loads(status.output)
    assert (document["source"], document["reason"]) == ("folder", "not_signed_in")
    assert package.status == 0
    assert (
        f"In the Studio: unknown, you are not signed in to {REMOTE}. Sign in with `ut login`."
        in package.output.splitlines()
    )
    assert tasks.status == 3
    assert tasks.errors == (
        f"You are not signed in to the Studio {REMOTE}. Sign in with `ut login`.\n"
    )
    assert init.status == 3
    assert transport.sent == []


def test_a_studio_with_accounts_still_asks_the_sign_in(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        link_folder(tmp_path / "project", studio=studio.address)
        status = ut(tmp_path, "status", "--json")
        login = run_ut(
            ["login", "--studio", studio.address, "--email", "person@example.com"],
            tmp_path,
            transport=UrlTransport(),
            secrets=[TEST_PASSWORD],
        )
        sent = paths(studio)

    document = json.loads(status.output)
    assert (document["source"], document["reason"]) == ("folder", "not_signed_in")
    assert login.status == 3
    assert login.errors == "Sign-in refused: the e-mail or the password is not correct.\n"
    assert sent == [MODE_PATH, f"{API}/health", MODE_PATH, f"{API}/auth/login"]


def test_init_links_a_project_of_the_local_studio_without_a_sign_in(tmp_path: Path) -> None:
    with FakeStudio(language="en", access_mode=LOCAL_OWNER) as studio:
        seeded = studio.seed_project(
            owner=LOCAL_OWNER_EMAIL, name=PROJECT_NAME, through="requirements"
        )
        store_session(tmp_path, studio=studio.address, access_token=None, refresh_token=None)
        run = ut(tmp_path, "init", "--project", seeded.id, "--mode", "design")
        address = studio.address
        sent = paths(studio)
        headers = authorizations(studio)
        versions = seeded.knowledge_versions()

    assert run.status == 0, run.errors
    folder = ProjectFolder.find(tmp_path / "project")
    assert folder is not None
    assert (folder.link().project_id, folder.link().studio) == (seeded.id, address)
    assert (
        f'The project "{PROJECT_NAME}" already has the steps Brief, Perspectives, User Twin and '
        "Definition approved." in run.output.splitlines()
    )
    assert len(versions) == 1
    assert MODE_PATH in sent
    assert not set(SIGN_IN_PATHS) & set(sent)
    assert headers == {None}


def test_status_package_and_tasks_of_the_local_studio_need_no_sign_in(tmp_path: Path) -> None:
    with FakeStudio(language="en", access_mode=LOCAL_OWNER) as studio:
        seeded = studio.seed_project(owner=LOCAL_OWNER_EMAIL, name=PROJECT_NAME, through="design")
        link_folder(tmp_path / "project", project_id=seeded.id, studio=studio.address)
        text = ut(tmp_path, "status")
        italian = ut(tmp_path, "status", language="it")
        as_json = ut(tmp_path, "status", "--json")
        package = ut(tmp_path, "package")
        tasks = ut(tmp_path, "tasks")
        address = studio.address
        sent = paths(studio)
        headers = authorizations(studio)

    assert text.status == 0, text.errors
    assert text.output.splitlines()[:3] == [
        PROJECT_NAME,
        "=" * len(PROJECT_NAME),
        f"Studio: {address} (local, no sign-in)",
    ]
    assert italian.output.splitlines()[2] == f"Studio: {address} (locale, senza accesso)"
    document = json.loads(as_json.output)
    assert set(document) == STATUS_KEYS
    assert (document["source"], document["reason"], document["studio"]) == (
        "studio",
        None,
        address,
    )
    assert package.status == 0, package.errors
    assert "not signed in" not in package.output
    assert tasks.status == 0, tasks.errors
    assert "not signed in" not in tasks.output
    assert not set(SIGN_IN_PATHS) & set(sent)
    assert headers == {None}


def test_login_and_logout_on_the_local_studio_ask_and_keep_nothing(tmp_path: Path) -> None:
    with FakeStudio(language="en", access_mode=LOCAL_OWNER) as studio:
        address = studio.address
        login = ut(tmp_path, "login", "--studio", address)
        logout = ut(tmp_path, "logout", "--studio", address, language="it")
        sent = paths(studio)

    assert login.status == 0, login.errors
    assert login.output == (
        f"The Studio {address} is local and needs no sign-in: the commands work without "
        "`ut login`.\n"
    )
    assert logout.status == 0, logout.errors
    assert logout.output == f"Lo Studio {address} è locale: non c'è un accesso da chiudere.\n"
    assert read_session(tmp_path, address) is None
    assert sent == [f"{API}/health", MODE_PATH, MODE_PATH]


def test_ut_test_runs_on_the_local_studio_without_a_sign_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = FakeSite(title="Tip calculator", text=TEXTS["en"], hidden_text=HIDDEN["en"])
    programs = site.programs(tmp_path / "programs", ("chrome", "firefox"))

    def finder(
        environment: object, *, names: Sequence[str] = ("chrome", "firefox"), **_: object
    ) -> tuple:
        return tuple(programs[name] for name in names)

    monkeypatch.setattr(run_flow, "open_page", site.open_page)
    monkeypatch.setattr(run_flow, "find_browsers", finder)
    with FakeStudio(language="en", access_mode=LOCAL_OWNER) as studio:
        seeded = studio.seed_project(owner=LOCAL_OWNER_EMAIL, name=PROJECT_NAME, through="design")
        link_folder(tmp_path / "project", project_id=seeded.id, studio=studio.address)
        published = ut(tmp_path, "package", "publish")
        run = ut(tmp_path, "test", "--url", ADDRESS, "--no-review")
        runs = seeded.test_runs()
        sent = paths(studio)
        headers = authorizations(studio)
        assert studio.errors == []

    assert published.status == 0, published.errors
    assert run.status == 0, run.errors
    assert "not signed in" not in run.errors
    assert len(runs) == 1
    assert MODE_PATH in sent
    assert not set(SIGN_IN_PATHS) & set(sent)
    assert headers == {None}


def test_ut_verify_reads_the_local_studio_without_a_sign_in(tmp_path: Path) -> None:
    with FakeStudio(language="en", access_mode=LOCAL_OWNER) as studio:
        seeded = studio.seed_project(owner=LOCAL_OWNER_EMAIL, name=PROJECT_NAME, through="design")
        link_folder(tmp_path / "project", project_id=seeded.id, studio=studio.address)
        processes = script_repository(ScriptedProcesses(), tmp_path / "project", (COMMIT,))
        run = run_ut(
            ["--lang", "en", "verify", "--dry-run"],
            tmp_path,
            transport=UrlTransport(),
            processes=processes,
        )
        sent = paths(studio)
        headers = authorizations(studio)
        assert studio.errors == []

    assert run.status == 0, run.errors
    assert f'Alignment of "{PROJECT_NAME}"' in run.output.splitlines()
    assert "Trial without spending (--dry-run). Commits the twins would review: 1." in (
        run.output.splitlines()
    )
    assert MODE_PATH in sent
    assert not set(SIGN_IN_PATHS) & set(sent)
    assert headers == {None}
