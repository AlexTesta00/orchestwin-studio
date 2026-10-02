from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from orchestwin.cli.browser.bidi import FirefoxPage
from orchestwin.cli.browser.cdp import ChromiumPage
from orchestwin.cli.browser.discovery import CHROMIUM_FAMILY, FIREFOX_FAMILY, BrowserProgram
from orchestwin.cli.browser.page import BLANK_PAGE, BROWSER_ERROR_CODES, BrowserError, Page
from orchestwin.cli.browser.websocket import WebSocket, connect
from orchestwin.cli.errors import CliError

if TYPE_CHECKING:
    from orchestwin.cli.environment import Environment, RunningProcess

PROFILE_PREFIX: Final = "orchestwin-browser-"
PROFILE_FOLDER: Final = "profile"
SNAP_FOLDER: Final = "/snap/"
CHROMIUM_PORT_FILE: Final = "DevToolsActivePort"
FIREFOX_PORT_FILE: Final = "WebDriverBiDiServer.json"
FIREFOX_PREFERENCES_FILE: Final = "user.js"
LOOPBACK: Final = "127.0.0.1"
PORT_FILE_SECONDS: Final = 30.0
PORT_POLL_SECONDS: Final = 0.1
GRACEFUL_SECONDS: Final = 5.0
TERMINATE_SECONDS: Final = 10.0
REMOVE_ATTEMPTS: Final = 10
REMOVE_PAUSE_SECONDS: Final = 0.2
CHROMIUM_FLAGS: Final = (
    "--headless=new",
    "--remote-debugging-port=0",
)
CHROMIUM_QUIET_FLAGS: Final = (
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-sync",
    "--disable-translate",
    "--metrics-recording-only",
    "--no-service-autorun",
    "--password-store=basic",
    "--use-mock-keychain",
    "--disable-gpu",
    "--hide-scrollbars",
)
CHROMIUM_DIRECT_FLAG: Final = "--no-proxy-server"
FIREFOX_PROXY_PREFERENCE: Final = "network.proxy.type"
FIREFOX_NO_PROXY: Final = 0
FIREFOX_VARIABLES: Final[Mapping[str, str]] = MappingProxyType(
    {"MOZ_CRASHREPORTER_DISABLE": "1", "MOZ_CRASHREPORTER_NO_REPORT": "1"}
)
FIREFOX_PREFERENCES: Final[Mapping[str, bool | int | str]] = MappingProxyType(
    {
        "app.normandy.api_url": "",
        "app.normandy.enabled": False,
        "app.shield.optoutstudies.enabled": False,
        "app.update.auto": False,
        "app.update.checkInstallTime": False,
        "app.update.disabledForTesting": True,
        "browser.aboutwelcome.enabled": False,
        "browser.cache.disk.enable": False,
        "browser.contentblocking.report.lockwise.enabled": False,
        "browser.discovery.enabled": False,
        "browser.formfill.enable": False,
        "browser.newtabpage.enabled": False,
        "browser.ping-centre.telemetry": False,
        "browser.region.network.url": "",
        "browser.region.update.enabled": False,
        "browser.safebrowsing.blockedURIs.enabled": False,
        "browser.safebrowsing.downloads.enabled": False,
        "browser.safebrowsing.downloads.remote.enabled": False,
        "browser.safebrowsing.malware.enabled": False,
        "browser.safebrowsing.phishing.enabled": False,
        "browser.safebrowsing.provider.google.updateURL": "",
        "browser.safebrowsing.provider.google4.updateURL": "",
        "browser.safebrowsing.provider.mozilla.updateURL": "",
        "browser.search.update": False,
        "browser.sessionstore.privacy_level": 2,
        "browser.sessionstore.resume_from_crash": False,
        "browser.shell.checkDefaultBrowser": False,
        "browser.startup.homepage": BLANK_PAGE,
        "browser.startup.homepage_override.mstone": "ignore",
        "browser.startup.page": 0,
        "browser.tabs.warnOnClose": False,
        "browser.topsites.contile.enabled": False,
        "browser.warnOnQuit": False,
        "captivedetect.canonicalURL": "",
        "datareporting.healthreport.uploadEnabled": False,
        "datareporting.policy.dataSubmissionEnabled": False,
        "datareporting.policy.firstRunURL": "",
        "dom.push.connection.enabled": False,
        "dom.push.enabled": False,
        "extensions.blocklist.enabled": False,
        "extensions.getAddons.cache.enabled": False,
        "extensions.systemAddon.update.enabled": False,
        "extensions.update.autoUpdateDefault": False,
        "extensions.update.enabled": False,
        "geo.provider.network.url": "",
        "identity.fxaccounts.enabled": False,
        "media.gmp-gmpopenh264.enabled": False,
        "media.gmp-manager.updateEnabled": False,
        "media.gmp-manager.url": "",
        "media.gmp-widevinecdm.enabled": False,
        "network.captive-portal-service.enabled": False,
        "network.connectivity-service.enabled": False,
        "network.dns.disablePrefetch": True,
        "network.http.speculative-parallel-limit": 0,
        "network.prefetch-next": False,
        "remote.active-protocols": 1,
        "security.remote_settings.crlite_filters.enabled": False,
        "security.remote_settings.intermediates.enabled": False,
        "services.settings.server": "data:,#remote-settings-dummy/v1",
        "signon.autofillForms": False,
        "signon.formlessCapture.enabled": False,
        "signon.generation.enabled": False,
        "signon.rememberSignons": False,
        "toolkit.telemetry.archive.enabled": False,
        "toolkit.telemetry.enabled": False,
        "toolkit.telemetry.server": "",
        "toolkit.telemetry.unified": False,
        "ui.useOverlayScrollbars": 1,
    }
)


@dataclass(frozen=True, slots=True)
class Launched:
    program: BrowserProgram
    process: RunningProcess
    root: Path
    profile: Path

    def stop(self, environment: Environment, *, graceful: bool = False) -> None:
        process = self.process
        if graceful:
            _wait(process, GRACEFUL_SECONDS)
        process.terminate()
        if not _wait(process, TERMINATE_SECONDS):
            process.kill()
            _wait(process, TERMINATE_SECONDS)
        remove_folder(environment, self.root)


def chromium_arguments(
    program: BrowserProgram,
    profile: Path,
    *,
    width: int,
    height: int,
    language: str,
    direct: bool = False,
) -> list[str]:
    return [
        str(program.path),
        *CHROMIUM_FLAGS,
        f"--user-data-dir={profile}",
        *CHROMIUM_QUIET_FLAGS,
        *((CHROMIUM_DIRECT_FLAG,) if direct else ()),
        f"--window-size={width},{height}",
        f"--lang={language_tag(language)}",
        BLANK_PAGE,
    ]


def firefox_arguments(
    program: BrowserProgram, profile: Path, *, width: int, height: int
) -> list[str]:
    return [
        str(program.path),
        "--headless",
        "--remote-debugging-port",
        "0",
        "--profile",
        str(profile),
        "-no-remote",
        "-new-instance",
        "--width",
        str(width),
        "--height",
        str(height),
        BLANK_PAGE,
    ]


def firefox_preferences(language: str, *, direct: bool = False) -> str:
    values: dict[str, bool | int | str] = dict(FIREFOX_PREFERENCES)
    accepted = accepted_languages(language)
    if accepted:
        values["intl.accept_languages"] = accepted
    if direct:
        values[FIREFOX_PROXY_PREFERENCE] = FIREFOX_NO_PROXY
    lines = (
        f"user_pref({json.dumps(name)}, {json.dumps(value)});" for name, value in values.items()
    )
    return "".join(f"{line}\n" for line in lines)


def accepted_languages(language: str) -> str:
    code = language_tag(language)
    if not code:
        return ""
    primary = code.split("-", 1)[0]
    return code if primary == code else f"{code}, {primary}"


def language_tag(language: str) -> str:
    return language.strip().replace("_", "-")


def launch(
    environment: Environment,
    program: BrowserProgram,
    *,
    width: int,
    height: int,
    language: str,
    direct: bool = False,
) -> Launched:
    if program.family not in (CHROMIUM_FAMILY, FIREFOX_FAMILY):
        raise ValueError(f"unknown browser family: {program.family}")
    if not program.path.is_file():
        raise BrowserError("BROWSER_NOT_FOUND", program=program.label, detail=str(program.path))
    root = Path(tempfile.mkdtemp(prefix=PROFILE_PREFIX, dir=temporary_parent(environment, program)))
    profile = root / PROFILE_FOLDER
    try:
        profile.mkdir()
        variables = dict(environment.variables)
        if program.family == FIREFOX_FAMILY:
            (profile / FIREFOX_PREFERENCES_FILE).write_text(
                firefox_preferences(language, direct=direct), encoding="utf-8", newline="\n"
            )
            arguments = firefox_arguments(program, profile, width=width, height=height)
            variables.update(FIREFOX_VARIABLES)
        else:
            arguments = chromium_arguments(
                program, profile, width=width, height=height, language=language, direct=direct
            )
        process = _start(environment, program, arguments, root, variables)
    except BaseException:
        remove_folder(environment, root)
        raise
    return Launched(program=program, process=process, root=root, profile=profile)


def temporary_parent(environment: Environment, program: BrowserProgram) -> Path | None:
    if program.path.as_posix().startswith(SNAP_FOLDER):
        return environment.home
    return None


def wait_for_endpoint(environment: Environment, launched: Launched) -> str:
    deadline = environment.monotonic() + PORT_FILE_SECONDS
    label = launched.program.label
    while True:
        address = read_endpoint(launched)
        if address is not None:
            return address
        status = launched.process.poll()
        if status is not None:
            raise BrowserError("BROWSER_NOT_STARTED", program=label, detail=f"exited with {status}")
        if environment.monotonic() >= deadline:
            raise BrowserError(
                "BROWSER_NOT_STARTED",
                program=label,
                detail=f"no answer within {PORT_FILE_SECONDS:g} seconds",
            )
        environment.sleep(PORT_POLL_SECONDS)


def read_endpoint(launched: Launched) -> str | None:
    if launched.program.family == FIREFOX_FAMILY:
        return _firefox_endpoint(launched.profile / FIREFOX_PORT_FILE)
    return _chromium_endpoint(launched.profile / CHROMIUM_PORT_FILE)


def launch_page(
    environment: Environment,
    program: BrowserProgram,
    *,
    width: int,
    height: int,
    language: str,
    direct: bool = False,
) -> Page:
    launched = launch(
        environment, program, width=width, height=height, language=language, direct=direct
    )
    socket: WebSocket | None = None
    try:
        address = wait_for_endpoint(environment, launched)
        socket = connect(address, program=program.label)
        if program.family == FIREFOX_FAMILY:
            return FirefoxPage.start(
                environment, program, launched, socket, width=width, height=height
            )
        return ChromiumPage.start(
            environment, program, launched, socket, width=width, height=height
        )
    except BaseException:
        if socket is not None:
            socket.close()
        launched.stop(environment)
        raise


def remove_folder(environment: Environment, folder: Path) -> None:
    for attempt in range(REMOVE_ATTEMPTS):
        shutil.rmtree(folder, ignore_errors=True)
        if not folder.exists():
            return
        if attempt + 1 < REMOVE_ATTEMPTS:
            environment.sleep(REMOVE_PAUSE_SECONDS)


def _start(
    environment: Environment,
    program: BrowserProgram,
    arguments: list[str],
    folder: Path,
    variables: Mapping[str, str],
) -> RunningProcess:
    try:
        return environment.start_process(arguments, folder, variables)
    except BrowserError:
        raise
    except CliError as error:
        code = error.code if error.code in BROWSER_ERROR_CODES else "BROWSER_NOT_STARTED"
        detail = error.values.get("detail")
        raise BrowserError(
            code, program=program.label, detail=str(detail) if detail else error.code
        ) from None


def _wait(process: RunningProcess, seconds: float) -> bool:
    try:
        process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        return False
    return True


def _chromium_endpoint(path: Path) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if len(lines) < 2:
        return None
    port = _port(lines[0].strip())
    target = lines[1].strip()
    if port is None or not target.startswith("/"):
        return None
    return f"ws://{LOOPBACK}:{port}{target}"


def _firefox_endpoint(path: Path) -> str | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    port = document.get("ws_port")
    host = document.get("ws_host", LOOPBACK)
    if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
        return None
    if not isinstance(host, str) or not host:
        return None
    address = f"[{host}]" if ":" in host else host
    return f"ws://{address}:{port}/session"


def _port(text: str) -> int | None:
    if not text.isdecimal():
        return None
    port = int(text)
    return port if 0 < port < 65536 else None
