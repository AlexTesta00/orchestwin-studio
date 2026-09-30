from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from orchestwin.cli.browser import BROWSER_NAMES, BrowserProgram, find_browsers
from orchestwin.cli.environment import Environment
from orchestwin.knowledge import state

from .support.terminal import environment
from .support.transports import NoNetwork


def machine(
    tmp_path: Path, *, platform: str, variables: Mapping[str, str] | None = None
) -> Environment:
    return environment(tmp_path, transport=NoNetwork(), platform=platform, variables=variables)


def install(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def nothing(command: str) -> str | None:
    return None


def test_the_names_match_the_constants_of_the_studio() -> None:
    assert BROWSER_NAMES == state.BROWSER_NAMES


def test_the_variables_win_when_they_point_to_a_file(tmp_path: Path) -> None:
    chrome = install(tmp_path / "custom" / "chrome.exe")
    firefox = install(tmp_path / "custom" / "firefox.exe")
    install(tmp_path / "programs" / "Google" / "Chrome" / "Application" / "chrome.exe")
    variables = {
        "ORCHESTWIN_CHROME": str(chrome),
        "ORCHESTWIN_FIREFOX": str(firefox),
        "ProgramFiles": str(tmp_path / "programs"),
    }

    found = find_browsers(machine(tmp_path, platform="win32", variables=variables))

    assert found == (
        BrowserProgram("chrome", "chromium", chrome, "Google Chrome"),
        BrowserProgram("firefox", "firefox", firefox, "Mozilla Firefox"),
    )


@pytest.mark.parametrize(
    ("relative", "label"),
    [
        (("Edge", "msedge.exe"), "Microsoft Edge"),
        (("bin", "microsoft-edge"), "Microsoft Edge"),
        (("chromium", "chrome.exe"), "Chromium"),
        (("tools", "chrome"), "Google Chrome"),
    ],
)
def test_the_label_of_a_chosen_program_follows_its_name(
    tmp_path: Path, relative: tuple[str, ...], label: str
) -> None:
    program = install(tmp_path.joinpath("chosen", *relative))

    found = find_browsers(
        machine(tmp_path, platform="linux", variables={"ORCHESTWIN_CHROME": str(program)}),
        names=("chrome",),
        which=nothing,
        system_root=tmp_path / "root",
    )

    assert found == (BrowserProgram("chrome", "chromium", program, label),)


def test_a_variable_that_points_nowhere_is_ignored(tmp_path: Path) -> None:
    installed = install(tmp_path / "programs" / "Mozilla Firefox" / "firefox.exe")
    variables = {
        "ORCHESTWIN_FIREFOX": str(tmp_path / "missing.exe"),
        "ORCHESTWIN_CHROME": "",
        "ProgramFiles": str(tmp_path / "programs"),
    }

    found = find_browsers(machine(tmp_path, platform="win32", variables=variables))

    assert found == (BrowserProgram("firefox", "firefox", installed, "Mozilla Firefox"),)


def test_windows_looks_in_the_three_program_folders_in_order(tmp_path: Path) -> None:
    local = tmp_path / "local"
    x86 = tmp_path / "x86"
    install(local / "Chromium" / "Application" / "chrome.exe")
    chrome = install(x86 / "Google" / "Chrome" / "Application" / "chrome.exe")
    install(local / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    firefox = install(x86 / "Mozilla Firefox" / "firefox.exe")
    variables = {
        "PROGRAMFILES": str(tmp_path / "programs"),
        "PROGRAMFILES(X86)": str(x86),
        "LOCALAPPDATA": str(local),
    }

    found = find_browsers(machine(tmp_path, platform="win32", variables=variables))

    assert found == (
        BrowserProgram("chrome", "chromium", chrome, "Google Chrome"),
        BrowserProgram("firefox", "firefox", firefox, "Mozilla Firefox"),
    )


def test_windows_takes_chromium_before_edge_and_edge_as_the_last_choice(tmp_path: Path) -> None:
    programs = tmp_path / "programs"
    edge = install(programs / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    variables = {"ProgramFiles": str(programs)}

    only_edge = find_browsers(machine(tmp_path, platform="win32", variables=variables))
    chromium = install(programs / "Chromium" / "Application" / "chrome.exe")
    with_chromium = find_browsers(machine(tmp_path, platform="win32", variables=variables))

    assert only_edge == (BrowserProgram("chrome", "chromium", edge, "Microsoft Edge"),)
    assert with_chromium == (BrowserProgram("chrome", "chromium", chromium, "Chromium"),)


def test_macos_looks_in_the_system_and_personal_applications(tmp_path: Path) -> None:
    system = tmp_path / "root"
    personal = tmp_path / "home" / "Applications"
    edge = install(
        system / "Applications" / "Microsoft Edge.app" / "Contents" / "MacOS" / "Microsoft Edge"
    )
    firefox = install(personal / "Firefox.app" / "Contents" / "MacOS" / "firefox")

    found = find_browsers(machine(tmp_path, platform="darwin"), system_root=system)
    chrome = install(personal / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome")
    preferred = find_browsers(machine(tmp_path, platform="darwin"), system_root=system)

    assert found == (
        BrowserProgram("chrome", "chromium", edge, "Microsoft Edge"),
        BrowserProgram("firefox", "firefox", firefox, "Mozilla Firefox"),
    )
    assert preferred[0] == BrowserProgram("chrome", "chromium", chrome, "Google Chrome")


def test_linux_asks_the_path_then_the_snap_folder(tmp_path: Path) -> None:
    chromium = install(tmp_path / "usr" / "bin" / "chromium-browser")
    snap = install(tmp_path / "root" / "snap" / "bin" / "firefox")
    asked: list[str] = []

    def which(command: str) -> str | None:
        asked.append(command)
        return str(chromium) if command == "chromium-browser" else None

    found = find_browsers(
        machine(tmp_path, platform="linux"), which=which, system_root=tmp_path / "root"
    )

    assert found == (
        BrowserProgram("chrome", "chromium", chromium, "Chromium"),
        BrowserProgram("firefox", "firefox", snap, "Mozilla Firefox"),
    )
    assert asked == [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        "firefox",
    ]


def test_linux_prefers_the_firefox_on_the_path(tmp_path: Path) -> None:
    firefox = install(tmp_path / "usr" / "bin" / "firefox")
    install(tmp_path / "root" / "snap" / "bin" / "firefox")

    found = find_browsers(
        machine(tmp_path, platform="linux"),
        names=("firefox",),
        which=lambda command: str(firefox) if command == "firefox" else None,
        system_root=tmp_path / "root",
    )

    assert found == (BrowserProgram("firefox", "firefox", firefox, "Mozilla Firefox"),)


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_nothing_found_is_an_empty_answer(tmp_path: Path, platform: str) -> None:
    variables = {"ProgramFiles": str(tmp_path / "programs")}

    found = find_browsers(
        machine(tmp_path, platform=platform, variables=variables),
        which=nothing,
        system_root=tmp_path / "root",
    )

    assert found == ()


def test_the_names_choose_and_order_the_browsers(tmp_path: Path) -> None:
    chrome = install(tmp_path / "chrome.exe")
    firefox = install(tmp_path / "firefox.exe")
    variables = {"ORCHESTWIN_CHROME": str(chrome), "ORCHESTWIN_FIREFOX": str(firefox)}
    computer = machine(tmp_path, platform="linux", variables=variables)

    reversed_order = find_browsers(computer, names=("firefox", "chrome", "firefox"))
    only_chrome = find_browsers(computer, names=("chrome",))

    assert [program.name for program in reversed_order] == ["firefox", "chrome"]
    assert [program.name for program in only_chrome] == ["chrome"]
    with pytest.raises(ValueError, match="unknown browser: opera"):
        find_browsers(computer, names=("opera",))
