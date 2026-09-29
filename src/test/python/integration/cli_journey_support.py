from __future__ import annotations

import http.client
import io
import json
import os
import re
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import IO, Final

from orchestwin.api.design import DesignPackagePayload
from orchestwin.api.requirements import RequirementsSpecificationPayload
from orchestwin.artifacts.visual_catalog import ARCHETYPES
from orchestwin.cli.environment import Environment
from orchestwin.cli.http import Reply, UrlTransport, origin_of, unreachable
from orchestwin.cli.main import main
from orchestwin.cli.messages import text
from orchestwin.models.design_mockups import MockupDraft, bind_mockup

HOST: Final = "127.0.0.1"
API_PREFIX: Final = "/api/v1"
FORBIDDEN_PORTS: Final = frozenset({8000, 8080})
PROJECT_ROOT: Final = Path(__file__).resolve().parents[4]
LANGUAGE: Final = "en"
TEST_EMAIL: Final = "cli-journey@example.com"
TEST_PASSWORD: Final = "Test-password-not-real!"
JWT_SECRET: Final = "test-jwt-secret-not-real-for-the-cli-journey"
DATABASE_VARIABLE: Final = "ORCHESTWIN_DATABASE_URL"
CONFIG_VARIABLE: Final = "ORCHESTWIN_CONFIG_DIR"
DETERMINISTIC: Final = "FAKE_DETERMINISTIC"
LOG_NAME: Final = "studio.log"
STARTUP_SECONDS: Final = 90.0
SHUTDOWN_SECONDS: Final = 15.0
HEALTH_POLL_SECONDS: Final = 0.1
POLL_WAIT_SECONDS: Final = 0.25
REQUEST_SECONDS: Final = 60.0
LOG_TAIL: Final = 20_000
AUTH_PATHS: Final = ("/auth/",)
RENEWAL_PATH: Final = "/auth/refresh"
READ_METHODS: Final = frozenset({"GET", "HEAD"})
TERMINAL_COLUMNS: Final = "160"
ACCESS_LINE: Final = re.compile(r'^INFO:\s+\S+:\d+ - "')
CELL_GAP: Final = re.compile(r" {2,}")
EMPTY_CELL: Final = "-"


class StudioFailure(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Answer:
    status: int
    headers: Mapping[str, str] = field(repr=False)
    content: bytes = field(repr=False)

    def json(self) -> object:
        if not self.content.strip():
            return None
        return json.loads(self.content.decode("utf-8"))

    @property
    def code(self) -> str | None:
        try:
            document = self.json()
        except ValueError:
            return None
        detail = document.get("detail") if isinstance(document, dict) else None
        if isinstance(detail, dict) and isinstance(detail.get("code"), str):
            return detail["code"]
        return detail if isinstance(detail, str) else None


@dataclass(frozen=True, slots=True)
class Exchange:
    method: str
    url: str
    status: int | None
    content: bytes = field(repr=False)

    @property
    def path(self) -> str:
        parts = urllib.parse.urlsplit(self.url)
        path = parts.path.removeprefix(API_PREFIX)
        return f"{path}?{parts.query}" if parts.query else path

    @property
    def code(self) -> str | None:
        return Answer(self.status or 0, {}, self.content).code if self.content else None

    def line(self) -> str:
        shown = "not sent" if self.status is None else str(self.status)
        code = self.code
        return f"{self.method} {self.path} -> {shown}" + (f" {code}" if code else "")


@dataclass(frozen=True, slots=True)
class Run:
    arguments: tuple[str, ...]
    directory: Path = field(repr=False)
    status: int
    output: str = field(repr=False)
    errors: str = field(repr=False)
    opened: tuple[str, ...] = field(repr=False)
    exchanges: tuple[Exchange, ...] = field(repr=False)

    def transcript(self) -> str:
        requests = "\n".join(f"  {exchange.line()}" for exchange in self.exchanges) or "  -"
        return (
            f"ut {' '.join(self.arguments)} (in {self.directory.name}) ended with {self.status}\n"
            f"--- output ---\n{self.output}--- errors ---\n{self.errors}"
            f"--- requests ---\n{requests}"
        )

    def requests(self, method: str, path: str) -> list[Exchange]:
        return [
            exchange
            for exchange in self.exchanges
            if exchange.method == method and exchange.path.split("?", 1)[0].endswith(path)
        ]

    def shows(self, sentence: str) -> bool:
        return flat(sentence) in flat(f"{self.output}\n{self.errors}")

    def writes(self) -> list[Exchange]:
        return [
            exchange
            for exchange in self.exchanges
            if exchange.method not in READ_METHODS and exchange.path != RENEWAL_PATH
        ]


def say(key: str, /, **values: object) -> str:
    return text(key, LANGUAGE, **values)


def flat(content: str) -> str:
    return " ".join(content.split())


def utc_now() -> datetime:
    return datetime.now(UTC)


def short_wait(seconds: float) -> None:
    time.sleep(min(max(seconds, 0.0), POLL_WAIT_SECONDS))


def no_secret(prompt: str) -> str:
    raise EOFError(prompt)


def free_port() -> int:
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            candidate.bind((HOST, 0))
            port = int(candidate.getsockname()[1])
        if port not in FORBIDDEN_PORTS:
            return port


def server_environment(database_url: str) -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith("ORCHESTWIN_")
        and name.upper() not in {"PYTHONPATH", "PYTHONWARNINGS"}
    }
    environment.update(
        {
            "ORCHESTWIN_APPLICATION_NAME": "OrchesTwin CLI Journey API",
            "ORCHESTWIN_ENVIRONMENT": "test",
            "ORCHESTWIN_DEBUG": "false",
            "ORCHESTWIN_LOG_LEVEL": "INFO",
            "ORCHESTWIN_API_PREFIX": API_PREFIX,
            "ORCHESTWIN_MODEL_RUNTIME_MODE": "DEVELOPMENT_FIXTURES",
            "ORCHESTWIN_DATABASE_URL": database_url,
            "ORCHESTWIN_DATABASE_ECHO": "false",
            "ORCHESTWIN_AUTH_JWT_SECRET": JWT_SECRET,
            "ORCHESTWIN_AUTH_JWT_ISSUER": "orchestwin-studio",
            "ORCHESTWIN_AUTH_JWT_AUDIENCE": "orchestwin-api",
            "ORCHESTWIN_TEAM_PROPOSAL_PROVIDER": DETERMINISTIC,
            "ORCHESTWIN_USER_MODELING_MODE": DETERMINISTIC,
            "ORCHESTWIN_REQUIREMENTS_MODE": DETERMINISTIC,
            "ORCHESTWIN_DESIGN_MODE": DETERMINISTIC,
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(PROJECT_ROOT / "src"),
        }
    )
    return environment


class StudioApi:
    def __init__(self, origin: str) -> None:
        self.origin = origin
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._credentials: tuple[str, str] | None = None
        self._access: str | None = None

    def call(
        self,
        method: str,
        path: str,
        body: object | None = None,
        *,
        headers: Mapping[str, str] | None = None,
        authorized: bool = True,
    ) -> Answer:
        sent = {"Accept": "application/json", **(headers or {})}
        content = None
        if body is not None:
            sent["Content-Type"] = "application/json"
            content = json.dumps(body).encode("utf-8")
        if authorized and self._access is not None:
            sent["Authorization"] = f"Bearer {self._access}"
        request = urllib.request.Request(
            f"{self.origin}{API_PREFIX}{path}", data=content, headers=sent, method=method
        )
        try:
            with self._opener.open(request, timeout=REQUEST_SECONDS) as response:
                return Answer(response.status, dict(response.headers.items()), response.read())
        except urllib.error.HTTPError as error:
            try:
                return Answer(error.code, dict(error.headers.items()), error.read())
            finally:
                error.close()

    def register(self, email: str, password: str) -> Answer:
        answer = self.call(
            "POST", "/auth/register", {"email": email, "password": password}, authorized=False
        )
        if answer.status == 201:
            self._credentials = (email, password)
            self._access = _access_token(answer)
        return answer

    def sign_in(self) -> None:
        if self._credentials is None:
            raise StudioFailure("the account of the journey was not registered")
        email, password = self._credentials
        answer = self.call(
            "POST", "/auth/login", {"email": email, "password": password}, authorized=False
        )
        if answer.status != 200:
            raise StudioFailure(f"the journey account cannot sign in: {answer.status}")
        self._access = _access_token(answer)

    def request(self, method: str, path: str, body: object | None = None) -> Answer:
        answer = self.call(method, path, body)
        if answer.status == 401:
            self.sign_in()
            answer = self.call(method, path, body)
        return answer

    def document(self, path: str) -> object:
        answer = self.request("GET", path)
        if answer.status != 200:
            raise StudioFailure(f"GET {path} answered {answer.status} {answer.code}")
        return answer.json()

    def health(self) -> int | None:
        try:
            return self.call("GET", "/health", authorized=False).status
        except (OSError, http.client.HTTPException):
            return None


def _access_token(answer: Answer) -> str:
    document = answer.json()
    token = document.get("access_token") if isinstance(document, dict) else None
    if not isinstance(token, str) or not token:
        raise StudioFailure("the Studio answered a sign-in without an access token")
    return token


class StudioProcess:
    def __init__(self, folder: Path, database_url: str) -> None:
        self.folder = folder
        self.database_url = database_url
        self.port = 0
        self.output = ""
        self._log: IO[bytes] | None = None
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def origin(self) -> str:
        return f"http://{HOST}:{self.port}"

    def __enter__(self) -> StudioProcess:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.port = free_port()
        self._log = (self.folder / LOG_NAME).open("wb")
        try:
            self._process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "orchestwin.api.server",
                    "--host",
                    HOST,
                    "--port",
                    str(self.port),
                ],
                cwd=self.folder,
                env=server_environment(self.database_url),
                stdin=subprocess.DEVNULL,
                stdout=self._log,
                stderr=subprocess.STDOUT,
            )
        except BaseException:
            self._close_log()
            raise
        try:
            self._wait_until_healthy()
        except BaseException as error:
            self.stop()
            error.add_note(self.diagnostics())
            raise
        return self

    def __exit__(self, kind: object, error: BaseException | None, trace: object) -> None:
        self.stop()
        if error is not None:
            error.add_note(self.diagnostics())

    def stop(self) -> None:
        process = self._process
        if process is not None:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=SHUTDOWN_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            self._process = None
        self._close_log()
        log = self.folder / LOG_NAME
        if log.is_file():
            self.output = log.read_bytes().decode("utf-8", "replace")

    def diagnostics(self) -> str:
        lines = [line for line in self.output.splitlines() if not ACCESS_LINE.match(line)]
        tail = "\n".join(lines)[-LOG_TAIL:].strip() or "<no server output>"
        return f"Studio output, request lines left out:\n{tail}"

    def _wait_until_healthy(self) -> None:
        api = StudioApi(self.origin)
        deadline = time.monotonic() + STARTUP_SECONDS
        while time.monotonic() < deadline:
            process = self._process
            if process is None or process.poll() is not None:
                raise StudioFailure("the Studio process ended before answering")
            if api.health() == 200:
                return
            time.sleep(HEALTH_POLL_SECONDS)
        raise StudioFailure(f"the Studio did not answer within {STARTUP_SECONDS:.0f} seconds")

    def _close_log(self) -> None:
        if self._log is not None:
            self._log.close()
            self._log = None


class RecordingTransport:
    def __init__(self, origin: str, *, offline: bool = False) -> None:
        self.origin = origin
        self.offline = offline
        self.exchanges: list[Exchange] = []
        self.refused: list[str] = []
        self._inner = UrlTransport()

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> Reply:
        port = urllib.parse.urlsplit(url).port
        if origin_of(url) != self.origin or port in FORBIDDEN_PORTS:
            self.refused.append(f"{method} {url}")
            self.exchanges.append(Exchange(method, url, None, b""))
            raise unreachable(url, sent=False)
        if self.offline:
            self.exchanges.append(Exchange(method, url, None, b""))
            raise unreachable(url, sent=False)
        reply = self._inner.send(method, url, headers=headers, body=body, timeout=timeout)
        kept = b"" if any(part in url for part in AUTH_PATHS) else reply.content
        self.exchanges.append(Exchange(method, url, reply.status, kept))
        return reply


class Browser:
    def __init__(self) -> None:
        self.opened: list[str] = []

    def open(self, address: str) -> bool:
        self.opened.append(address)
        return True


class Terminal:
    def __init__(self, root: Path, origin: str) -> None:
        self.home = root / "home"
        self.config = root / "config"
        self.origin = origin
        self.refused: list[str] = []
        self.runs: list[Run] = []
        self.home.mkdir(parents=True, exist_ok=True)

    @property
    def sessions_file(self) -> Path:
        return self.config / "sessions.json"

    def run(
        self,
        arguments: Sequence[str],
        *,
        directory: Path,
        answers: Sequence[str] = (),
        offline: bool = False,
    ) -> Run:
        directory.mkdir(parents=True, exist_ok=True)
        transport = RecordingTransport(self.origin, offline=offline)
        browser = Browser()
        stdout = io.StringIO()
        stderr = io.StringIO()
        environment = Environment(
            stdin=io.StringIO("".join(f"{answer}\n" for answer in answers)),
            stdout=stdout,
            stderr=stderr,
            variables={
                CONFIG_VARIABLE: str(self.config),
                "NO_COLOR": "1",
                "COLUMNS": TERMINAL_COLUMNS,
            },
            home=self.home,
            working_directory=directory,
            platform=sys.platform,
            interactive=False,
            now=utc_now,
            monotonic=time.monotonic,
            sleep=short_wait,
            read_secret=no_secret,
            open_browser=browser.open,
            transport=transport,
            system_language=LANGUAGE,
        )
        status = main(list(arguments), environment=environment)
        self.refused.extend(transport.refused)
        run = Run(
            arguments=tuple(arguments),
            directory=directory,
            status=status,
            output=stdout.getvalue(),
            errors=stderr.getvalue(),
            opened=tuple(browser.opened),
            exchanges=tuple(transport.exchanges),
        )
        self.runs.append(run)
        return run

    def session_document(self) -> Mapping[str, object]:
        if not self.sessions_file.is_file():
            return {}
        document = json.loads(self.sessions_file.read_bytes().decode("utf-8"))
        return document if isinstance(document, dict) else {}


@dataclass
class Journey:
    problems: list[str] = field(default_factory=list)

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        try:
            yield
        except (AssertionError, StudioFailure) as error:
            self.problems.append(f"[{name}] {error}")
        except Exception as error:
            details = "".join(traceback.format_exception(error)).rstrip()
            self.problems.append(f"[{name}] {details}")

    def report(self) -> str:
        return "\n\n".join(self.problems)


def table_rows(output: str) -> list[list[str]]:
    rows: list[list[str]] = []
    inside = False
    for line in output.splitlines():
        if not inside:
            inside = bool(line.strip()) and set(line) <= {"-", " "} and "  " in line.strip()
            continue
        if not line.strip():
            break
        rows.append(re.split(r" {2,}", line.strip()))
    return rows


def dash_rows(output: str) -> list[str]:
    found: list[str] = []
    for line in output.splitlines():
        cells = CELL_GAP.split(line.strip())
        if len(cells) > 1 and set(cells[1:]) == {EMPTY_CELL}:
            found.append(line)
    return found


def date_text(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def write_json(path: Path, document: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return path


def read_json(path: Path) -> object:
    return json.loads(path.read_bytes().decode("utf-8"))


def mockup_draft(alternative: object, requirement_code: str, *, product: str) -> MockupDraft:
    visual = getattr(alternative, "visual_language", None)
    spec = None if visual is None else ARCHETYPES[visual.choices.archetype]
    count = 2 if spec is None else min(max(spec.minimum_screens, 2), spec.maximum_screens, 4)
    screens: list[dict[str, object]] = []
    for number in range(1, count):
        screens.append(
            {
                "code": f"SCR-{number:03d}",
                "title": f"{product}: step {number}",
                "state": "DEFAULT",
                "elements": [
                    _element("HEADING", f"Step {number} of {count - 1}", requirement_code),
                    _element(
                        "TEXT_INPUT",
                        "Amount of the bill",
                        requirement_code,
                        field_name=f"amount_{number}",
                    ),
                    _element(
                        "BUTTON",
                        "Continue",
                        requirement_code,
                        target_screen=f"SCR-{number + 1:03d}",
                    ),
                ],
            }
        )
    screens.append(
        {
            "code": f"SCR-{count:03d}",
            "title": f"{product}: summary",
            "state": "SUCCESS",
            "elements": [
                _element("HEADING", "Everything is ready", requirement_code),
                _element("TEXT", "Example: each person pays 12.50 EUR.", requirement_code),
                _element("LINK", "Start again", requirement_code, target_screen="SCR-001"),
            ],
        }
    )
    return MockupDraft.model_validate({"title": f"{product} prototype", "screens": screens})


def _element(
    kind: str,
    content: str,
    requirement_code: str,
    *,
    field_name: str | None = None,
    target_screen: str | None = None,
) -> dict[str, object]:
    return {
        "kind": kind,
        "content": content,
        "requirements": [requirement_code],
        "field_name": field_name,
        "required": False,
        "options": [],
        "target_screen": target_screen,
    }


def chosen_package(
    design: Mapping[str, object], requirements: Mapping[str, object], alternative_id: str
) -> dict[str, object]:
    package = DesignPackagePayload.model_validate(design["package"]).to_domain()
    specification = RequirementsSpecificationPayload.model_validate(
        requirements["specification"]
    ).to_domain()
    alternative = next(item for item in package.alternatives if str(item.id) == alternative_id)
    code = specification.requirements[0].code
    visual = alternative.visual_language
    product = "Tip splitter" if visual is None else visual.product_name
    draft = mockup_draft(alternative, code, product=product)
    prototype = bind_mockup(draft, alternative, SimpleNamespace(specification=specification))
    chosen = replace(
        package,
        owner_selected_alternative_id=alternative.id,
        prototype=prototype,
        generated_mockup=None,
    )
    return DesignPackagePayload.from_domain(chosen).model_dump(mode="json")
