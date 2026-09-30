from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from orchestwin.cli.environment import Environment

BROWSER_NAMES: Final = ("chrome", "firefox")
CHROMIUM_FAMILY: Final = "chromium"
FIREFOX_FAMILY: Final = "firefox"
GOOGLE_CHROME: Final = "Google Chrome"
CHROMIUM: Final = "Chromium"
MICROSOFT_EDGE: Final = "Microsoft Edge"
MOZILLA_FIREFOX: Final = "Mozilla Firefox"
SYSTEM_ROOT: Final = Path("/")
FAMILIES: Final[Mapping[str, str]] = MappingProxyType(
    {"chrome": CHROMIUM_FAMILY, "firefox": FIREFOX_FAMILY}
)
VARIABLES: Final[Mapping[str, str]] = MappingProxyType(
    {"chrome": "ORCHESTWIN_CHROME", "firefox": "ORCHESTWIN_FIREFOX"}
)
WINDOWS_FOLDERS: Final = ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData")
WINDOWS_PLACES: Final[Mapping[str, tuple[tuple[str, tuple[str, ...]], ...]]] = MappingProxyType(
    {
        "chrome": (
            (GOOGLE_CHROME, ("Google", "Chrome", "Application", "chrome.exe")),
            (CHROMIUM, ("Chromium", "Application", "chrome.exe")),
            (MICROSOFT_EDGE, ("Microsoft", "Edge", "Application", "msedge.exe")),
        ),
        "firefox": ((MOZILLA_FIREFOX, ("Mozilla Firefox", "firefox.exe")),),
    }
)
MAC_PLACES: Final[Mapping[str, tuple[tuple[str, tuple[str, ...]], ...]]] = MappingProxyType(
    {
        "chrome": (
            (GOOGLE_CHROME, ("Google Chrome.app", "Contents", "MacOS", "Google Chrome")),
            (CHROMIUM, ("Chromium.app", "Contents", "MacOS", "Chromium")),
            (MICROSOFT_EDGE, ("Microsoft Edge.app", "Contents", "MacOS", "Microsoft Edge")),
        ),
        "firefox": ((MOZILLA_FIREFOX, ("Firefox.app", "Contents", "MacOS", "firefox")),),
    }
)
LINUX_COMMANDS: Final[Mapping[str, tuple[tuple[str, str], ...]]] = MappingProxyType(
    {
        "chrome": (
            (GOOGLE_CHROME, "google-chrome"),
            (GOOGLE_CHROME, "google-chrome-stable"),
            (CHROMIUM, "chromium"),
            (CHROMIUM, "chromium-browser"),
            (MICROSOFT_EDGE, "microsoft-edge"),
        ),
        "firefox": ((MOZILLA_FIREFOX, "firefox"),),
    }
)
LINUX_PLACES: Final[Mapping[str, tuple[tuple[str, tuple[str, ...]], ...]]] = MappingProxyType(
    {"chrome": (), "firefox": ((MOZILLA_FIREFOX, ("snap", "bin", "firefox")),)}
)


@dataclass(frozen=True, slots=True)
class BrowserProgram:
    name: str
    family: str
    path: Path
    label: str


def find_browsers(
    environment: Environment,
    *,
    names: Sequence[str] = BROWSER_NAMES,
    which: Callable[[str], str | None] = shutil.which,
    system_root: Path = SYSTEM_ROOT,
) -> tuple[BrowserProgram, ...]:
    found: list[BrowserProgram] = []
    for name in dict.fromkeys(names):
        if name not in BROWSER_NAMES:
            raise ValueError(f"unknown browser: {name}")
        program = find_browser(environment, name, which=which, system_root=system_root)
        if program is not None:
            found.append(program)
    return tuple(found)


def find_browser(
    environment: Environment,
    name: str,
    *,
    which: Callable[[str], str | None] = shutil.which,
    system_root: Path = SYSTEM_ROOT,
) -> BrowserProgram | None:
    chosen = _variable(environment.variables, VARIABLES[name])
    if chosen:
        path = Path(chosen)
        if path.is_file():
            return BrowserProgram(name, FAMILIES[name], path, _label_of(name, path))
    for label, path in _places(environment, name, which, system_root):
        if path.is_file():
            return BrowserProgram(name, FAMILIES[name], path, label)
    return None


def _places(
    environment: Environment,
    name: str,
    which: Callable[[str], str | None],
    system_root: Path,
) -> list[tuple[str, Path]]:
    if environment.platform == "win32":
        bases = [_variable(environment.variables, folder) for folder in WINDOWS_FOLDERS]
        return [
            (label, Path(base, *parts))
            for label, parts in WINDOWS_PLACES[name]
            for base in bases
            if base
        ]
    if environment.platform == "darwin":
        folders = (system_root / "Applications", environment.home / "Applications")
        return [
            (label, folder.joinpath(*parts))
            for label, parts in MAC_PLACES[name]
            for folder in folders
        ]
    places: list[tuple[str, Path]] = []
    for label, command in LINUX_COMMANDS[name]:
        location = which(command)
        if location:
            places.append((label, Path(location)))
    places.extend((label, system_root.joinpath(*parts)) for label, parts in LINUX_PLACES[name])
    return places


def _variable(variables: Mapping[str, str], name: str) -> str:
    value = variables.get(name)
    if value is None:
        wanted = name.upper()
        value = next((item for key, item in variables.items() if key.upper() == wanted), None)
    return (value or "").strip()


def _label_of(name: str, path: Path) -> str:
    if name == "firefox":
        return MOZILLA_FIREFOX
    program = path.name.lower()
    if any(word in program for word in ("msedge", "microsoft-edge", "microsoft edge")):
        return MICROSOFT_EDGE
    if "chromium" in path.as_posix().lower():
        return CHROMIUM
    return GOOGLE_CHROME
