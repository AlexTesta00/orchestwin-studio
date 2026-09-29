from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from orchestwin.cli.errors import CliError
from orchestwin.cli.project import ProjectFolder

from .support.terminal import (
    PROJECT_ID,
    START,
    TEST_EMAIL,
    command_context,
    environment,
    link_folder,
    read_session,
    run_ut,
    store_session,
    terminal,
)
from .support.transports import API, NoNetwork, ScriptedTransport, reply


def test_the_environment_lives_in_the_temporary_folder(tmp_path: Path) -> None:
    built = environment(
        tmp_path,
        transport=NoNetwork(),
        variables={"COLUMNS": "100"},
        platform="darwin",
        interactive=True,
        language="it",
    )

    assert built.home == tmp_path / "home"
    assert built.home.is_dir()
    assert built.working_directory == tmp_path / "project"
    assert built.working_directory.is_dir()
    assert built.variables == {
        "ORCHESTWIN_CONFIG_DIR": str(tmp_path / "config"),
        "COLUMNS": "100",
    }
    assert (built.platform, built.interactive, built.system_language) == ("darwin", True, "it")
    assert built.now() == START


def test_the_clock_moves_only_when_asked(tmp_path: Path) -> None:
    bundle = terminal(tmp_path, transport=NoNetwork(), start=START + timedelta(hours=1))
    first = bundle.environment.monotonic()

    bundle.environment.sleep(2.5)
    bundle.environment.sleep(0)
    bundle.clock.advance(10)

    assert bundle.environment.monotonic() - first == 12.5
    assert bundle.environment.now() == START + timedelta(hours=1, seconds=12.5)
    assert bundle.clock.slept == 2.5


def test_answers_and_secrets_run_out(tmp_path: Path) -> None:
    bundle = terminal(tmp_path, transport=NoNetwork(), answers=["one"], secrets=["two"])

    assert bundle.environment.stdin.readline() == "one\n"
    assert bundle.environment.stdin.readline() == ""
    assert bundle.environment.read_secret("Password: ") == "two"
    with pytest.raises(EOFError):
        bundle.environment.read_secret("Password: ")
    assert bundle.secrets.prompts == ["Password: ", "Password: "]


def test_the_browser_is_recorded(tmp_path: Path) -> None:
    bundle = terminal(tmp_path, transport=NoNetwork())

    assert bundle.environment.open_browser("file:///preview/index.html") is True
    assert bundle.browser.opened == ["file:///preview/index.html"]


def test_run_ut_gives_status_output_and_errors(tmp_path: Path) -> None:
    run = run_ut(["status", "--offline"], tmp_path, transport=NoNetwork())

    assert run.status == 6
    assert run.output == ""
    assert "not linked" in run.errors
    assert run.opened == ()
    assert run.slept == 0


def test_a_request_that_was_not_expected_fails_the_test(tmp_path: Path) -> None:
    store_session(tmp_path)

    with pytest.raises(pytest.fail.Exception, match="unexpected request: GET /api/v1/projects"):
        run_ut(["status"], tmp_path, transport=ScriptedTransport())


def test_the_scripted_transport_answers_in_any_order_and_reports_what_is_left() -> None:
    transport = ScriptedTransport()
    transport.expect("GET", f"{API}/a", body={"a": 1})
    transport.expect("POST", f"{API}/b", status=201, body=b"raw", headers={"X-Test": "yes"})
    transport.expect("GET", f"{API}/c", unreachable=True, sent=True)
    transport.expect("GET", f"{API}/never")

    created = transport.send(
        "POST", f"http://127.0.0.1:1{API}/b", headers={"Accept": "*/*"}, body=b"{}", timeout=1.0
    )
    first = transport.send("GET", f"http://127.0.0.1:1{API}/a", headers={}, body=None, timeout=1.0)
    with pytest.raises(CliError) as caught:
        transport.send("GET", f"http://127.0.0.1:1{API}/c", headers={}, body=None, timeout=1.0)

    assert (created.status, created.content, created.headers["x-test"]) == (201, b"raw", "yes")
    assert first.json() == {"a": 1}
    assert caught.value.values["sent"] is True
    assert transport.sent[0].header("ACCEPT") == "*/*"
    assert transport.sent[0].json() == {}
    assert [request.path for request in transport.requests("GET")] == [f"{API}/a", f"{API}/c"]
    with pytest.raises(pytest.fail.Exception, match="never"):
        transport.assert_done()


def test_replies_are_built_from_json_bytes_or_nothing() -> None:
    assert reply(200, {"a": 1}).headers["content-type"] == "application/json"
    assert reply(204).content == b""
    assert reply(200, b"PK").content == b"PK"


def test_the_helpers_store_a_session_and_link_a_folder(tmp_path: Path) -> None:
    stored = store_session(tmp_path)
    project = link_folder(tmp_path / "project")

    assert read_session(tmp_path) == stored
    assert read_session(tmp_path, "https://studio.example.test") is None
    assert stored.email == TEST_EMAIL
    assert isinstance(project, ProjectFolder)
    assert project.link().project_id == PROJECT_ID
    context = command_context(environment(tmp_path, transport=NoNetwork()), language="it")
    assert context.project() is not None
    assert context.language == "it"
    assert context.client().studio.origin == "http://127.0.0.1:8000"
