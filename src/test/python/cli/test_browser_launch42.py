from __future__ import annotations

import json
import os
import tempfile
from itertools import pairwise
from pathlib import Path

import pytest

from orchestwin.cli.browser import BrowserError, BrowserProgram, open_page
from orchestwin.cli.browser.discovery import FIREFOX_FAMILY, MOZILLA_FIREFOX
from orchestwin.cli.browser.launch import (
    FIREFOX_PORT_FILE,
    PROFILE_FOLDER,
    SNAP_LINK_STEPS,
    SNAP_SCRIPT_BYTES,
    Launched,
    snap_program,
    temporary_parent,
    wait_for_endpoint,
)

from .support.browsers import BIDI, FakeProcess, ScriptedBrowser
from .support.terminal import command_context, terminal
from .support.transports import NoNetwork

SNAP_FIREFOX = "/snap/bin/firefox"
SNAP_BINARY = "/snap/firefox/current/usr/lib/firefox/firefox"
SNAP_MISSING = "/snap/orchestwin-missing/current"
WRAPPER = b'#!/bin/sh\nexec /snap/bin/firefox "$@"\n'
BINARY = b"\x7fELF\x02\x01\x01\x00\xff\xfe\x00\x00"
PORT_DOCUMENT = json.dumps({"ws_host": "127.0.0.1", "ws_port": 9222})


class Unresolvable(Path):
    def resolve(self, strict: bool = False) -> Path:
        raise OSError("the links of this path cannot be followed")


def firefox(path: Path) -> BrowserProgram:
    return BrowserProgram("firefox", FIREFOX_FAMILY, path, MOZILLA_FIREFOX)


def written(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def linked(link: Path, target: str, *, as_written: bool = False) -> Path:
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not let the tests create a symbolic link")
    if as_written and Path(os.readlink(link)) != Path(target):
        pytest.skip("this system does not keep the target of a link as it was written")
    return link


def resolved(path: Path) -> str:
    try:
        return path.resolve().as_posix()
    except OSError:
        return ""


def started(tmp_path: Path, process: FakeProcess) -> Launched:
    profile = tmp_path / "browser" / PROFILE_FOLDER
    profile.mkdir(parents=True)
    return Launched(firefox(tmp_path / "firefox"), process, profile.parent, profile)


@pytest.mark.parametrize("location", [SNAP_FIREFOX, SNAP_BINARY])
def test_a_program_under_the_snap_folder_is_a_snap(location: str) -> None:
    assert snap_program(firefox(Path(location))) is True


def test_a_script_that_starts_the_snap_is_a_snap(tmp_path: Path) -> None:
    script = written(tmp_path / "usr" / "bin" / "firefox", WRAPPER)

    assert snap_program(firefox(script)) is True


@pytest.mark.parametrize(
    ("size", "expected"),
    [(SNAP_SCRIPT_BYTES, True), (SNAP_SCRIPT_BYTES + 1, False), (1 << 20, False)],
)
def test_only_a_short_script_can_lead_to_the_snap(
    tmp_path: Path, size: int, expected: bool
) -> None:
    script = written(tmp_path / "firefox", WRAPPER + b"#" * (size - len(WRAPPER)))

    assert script.stat().st_size == size
    assert snap_program(firefox(script)) is expected


@pytest.mark.parametrize(
    "content",
    [
        b'#!/bin/sh\n\xff\xfe exec /snap/bin/firefox "$@"\n',
        b'exec /snap/bin/firefox "$@"\n',
        b'#!/bin/sh\nexec /usr/lib/firefox/firefox "$@"\n',
        BINARY,
        b"",
    ],
    ids=["not-utf-8", "no-script-mark", "no-snap", "binary", "empty"],
)
def test_a_file_that_is_not_a_short_script_naming_the_snap_is_not_a_snap(
    tmp_path: Path, content: bytes
) -> None:
    program = written(tmp_path / "firefox", content)

    assert snap_program(firefox(program)) is False


def test_a_missing_program_or_a_folder_is_not_a_snap(tmp_path: Path) -> None:
    folder = tmp_path / "firefox"
    folder.mkdir()

    assert snap_program(firefox(tmp_path / "missing")) is False
    assert snap_program(firefox(folder)) is False


def test_a_program_in_a_folder_linked_inside_the_snap_folder_is_a_snap(tmp_path: Path) -> None:
    program = linked(tmp_path / "opt" / "firefox", SNAP_MISSING) / "firefox"
    if not resolved(program).startswith("/snap/"):
        pytest.skip("this system does not resolve the link inside /snap/")

    assert snap_program(firefox(program)) is True


def test_a_program_that_resolves_to_the_snap_launcher_is_a_snap(tmp_path: Path) -> None:
    launcher = written(tmp_path / "usr" / "bin" / "snap", BINARY)
    other = written(tmp_path / "usr" / "lib" / "firefox", BINARY)
    through_launcher = linked(tmp_path / "bin" / "firefox", str(launcher))
    through_other = linked(tmp_path / "bin" / "browser", str(other))

    assert snap_program(firefox(through_launcher)) is True
    assert snap_program(firefox(through_other)) is False


def test_a_link_written_towards_the_snap_folder_is_a_snap(tmp_path: Path) -> None:
    link = linked(tmp_path / "firefox", SNAP_FIREFOX, as_written=True)

    assert snap_program(firefox(link)) is True
    assert snap_program(firefox(Unresolvable(link))) is True


def test_a_link_to_itself_is_not_a_snap(tmp_path: Path) -> None:
    loop = linked(tmp_path / "firefox", "firefox")

    assert snap_program(firefox(loop)) is False
    assert snap_program(firefox(Unresolvable(loop))) is False


@pytest.mark.parametrize(
    ("links", "expected"),
    [(SNAP_LINK_STEPS, True), (SNAP_LINK_STEPS + 1, False)],
)
def test_the_links_are_followed_from_the_folder_of_each_link_for_eight_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, links: int, expected: bool
) -> None:
    steps = [tmp_path / f"step-{index}" / "firefox" for index in range(links)]
    targets = {step: Path("..", after.parent.name, after.name) for step, after in pairwise(steps)}
    targets[steps[-1]] = Path(SNAP_FIREFOX)
    real_readlink = os.readlink

    def readlink(path: str | os.PathLike[str]) -> str:
        target = targets.get(Path(path))
        return real_readlink(path) if target is None else str(target)

    monkeypatch.setattr(os, "readlink", readlink)

    assert snap_program(firefox(steps[0])) is expected


def test_a_program_whose_links_cannot_be_followed_is_judged_by_its_content(tmp_path: Path) -> None:
    script = written(tmp_path / "bin" / "firefox", WRAPPER)
    plain = written(tmp_path / "lib" / "firefox", BINARY)

    assert snap_program(firefox(Unresolvable(script))) is True
    assert snap_program(firefox(Unresolvable(plain))) is False


def test_the_profile_of_a_snap_goes_in_the_home_folder(tmp_path: Path) -> None:
    environment = terminal(tmp_path, transport=NoNetwork()).environment
    script = written(tmp_path / "usr" / "bin" / "firefox", WRAPPER)
    plain = written(tmp_path / "opt" / "firefox" / "firefox", BINARY)

    assert temporary_parent(environment, firefox(Path(SNAP_FIREFOX))) == environment.home
    assert temporary_parent(environment, firefox(script)) == environment.home
    assert temporary_parent(environment, firefox(plain)) is None


def test_firefox_behind_a_snap_script_starts_with_its_profile_in_the_home_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temporary = tmp_path / "temp"
    temporary.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temporary))
    script = written(tmp_path / "usr" / "bin" / "firefox", WRAPPER)

    with ScriptedBrowser(protocol=BIDI) as browser:
        bundle = terminal(tmp_path, transport=NoNetwork(), start_process=browser)
        page = open_page(command_context(bundle.environment), firefox(script), language="it-IT")
        profile = browser.calls[0].profile
        page.close()

    assert browser.calls[0].arguments[0] == str(script)
    assert profile.parent.parent == bundle.environment.home
    assert profile.parent.name.startswith("orchestwin-browser-")
    assert not profile.parent.exists()
    assert list(temporary.iterdir()) == []


def test_a_firefox_that_never_writes_its_port_file_is_given_sixty_seconds(tmp_path: Path) -> None:
    bundle = terminal(tmp_path, transport=NoNetwork())
    launched = started(tmp_path, FakeProcess())

    with pytest.raises(BrowserError) as caught:
        wait_for_endpoint(bundle.environment, launched)

    assert (caught.value.code, caught.value.program, caught.value.detail) == (
        "BROWSER_NOT_STARTED",
        MOZILLA_FIREFOX,
        "no answer within 60 seconds",
    )
    assert bundle.clock.slept == pytest.approx(60.0, abs=0.2)


def test_a_firefox_that_answers_after_forty_five_seconds_is_waited_for(tmp_path: Path) -> None:
    bundle = terminal(tmp_path, transport=NoNetwork())
    port_file = tmp_path / "browser" / PROFILE_FOLDER / FIREFOX_PORT_FILE

    def ready(polls: int) -> None:
        if polls == 450:
            port_file.write_text(PORT_DOCUMENT, encoding="utf-8")

    launched = started(tmp_path, FakeProcess(on_poll=ready))

    assert wait_for_endpoint(bundle.environment, launched) == "ws://127.0.0.1:9222/session"
    assert bundle.clock.slept == pytest.approx(45.0, abs=0.2)
