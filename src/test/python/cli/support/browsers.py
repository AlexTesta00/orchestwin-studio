from __future__ import annotations

import base64
import contextlib
import json
import os
import socket
import struct
import subprocess
import threading
import time
import traceback
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final

from orchestwin.cli.browser.discovery import (
    CHROMIUM_FAMILY,
    FIREFOX_FAMILY,
    GOOGLE_CHROME,
    MOZILLA_FIREFOX,
    BrowserProgram,
)
from orchestwin.cli.browser.launch import CHROMIUM_PORT_FILE, FIREFOX_PORT_FILE
from orchestwin.cli.browser.page import Element, PageSnapshot
from orchestwin.cli.browser.snapshot import (
    FIELD_SCRIPT,
    FOCUS_SCRIPT,
    READY_SCRIPT,
    RECT_SCRIPT,
    SCROLL_SCRIPT,
    SELECT_SCRIPT,
    SNAPSHOT_SCRIPT,
    VALUE_SCRIPT,
)
from orchestwin.cli.browser.websocket import (
    CLOSE,
    CONTINUATION,
    PING,
    PONG,
    TEXT,
    accept_key,
    frame_header,
    masked,
)
from orchestwin.cli.environment import RunningProcess
from orchestwin.cli.errors import CliError

CDP: Final = "cdp"
BIDI: Final = "bidi"
TARGET: Final = "TARGET-1"
SESSION: Final = "SESSION-1"
LOADER: Final = "LOADER-1"
CONTEXT: Final = "CONTEXT-1"
CHROME_VERSION: Final = "151.0.7922.76"
FIREFOX_VERSION: Final = "156.0.1"
BROWSER_PATH: Final = "/devtools/browser/fake-browser"
SESSION_PATH: Final = "/session"
SERVER_TIMEOUT_SECONDS: Final = 10.0
ACCEPT_POLL_SECONDS: Final = 0.05
TERMINATED_STATUS: Final = 1
KILLED_STATUS: Final = 9
DEFAULT_POINT: Final = (100, 50)
PAGE_URL: Final = "http://127.0.0.1:8123/"


def _png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\xff\xff\xff")
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")
    )


FAKE_PNG: Final = _png()


def element(
    index: int = 0,
    role: str = "button",
    name: str = "",
    *,
    value: str | None = None,
    state: str | None = None,
    options: Sequence[str] | None = None,
) -> Element:
    return Element(
        index=index,
        role=role,
        name=name,
        value=value,
        state=state,
        options=None if options is None else tuple(options),
    )


def elements(*entries: tuple[str, str]) -> tuple[Element, ...]:
    return tuple(element(index, role, name) for index, (role, name) in enumerate(entries))


def page_snapshot(
    *items: Element,
    url: str = PAGE_URL,
    title: str = "Prova",
    text: str | None = None,
) -> PageSnapshot:
    shown = " ".join(item.name for item in items if item.name) if text is None else text
    numbered = tuple(replace(item, index=position) for position, item in enumerate(items))
    return PageSnapshot(url=url, title=title, text=shown, elements=numbered)


def no_browsers(
    arguments: Sequence[str], folder: Path, variables: Mapping[str, str]
) -> RunningProcess:
    name = Path(str(arguments[0])).name if arguments else "browser"
    raise CliError(
        "BROWSER_NOT_STARTED",
        status=1,
        values={"program": name, "detail": "no browser runs in the tests"},
    )


@dataclass(frozen=True, slots=True)
class FakeBrowserProgram(BrowserProgram):
    @classmethod
    def create(cls, folder: Path, name: str = "chrome") -> FakeBrowserProgram:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"fake-{name}.exe"
        path.write_bytes(b"")
        if name == "firefox":
            return cls(name=name, family=FIREFOX_FAMILY, path=path, label=MOZILLA_FIREFOX)
        return cls(name=name, family=CHROMIUM_FAMILY, path=path, label=GOOGLE_CHROME)


class FakeProcess:
    def __init__(
        self,
        *,
        returncode: int | None = None,
        stubborn: bool = False,
        on_poll: Callable[[int], None] | None = None,
    ) -> None:
        self.returncode = returncode
        self.stubborn = stubborn
        self.polls = 0
        self.terminated = 0
        self.killed = 0
        self.waits: list[float | None] = []
        self._on_poll = on_poll

    def poll(self) -> int | None:
        self.polls += 1
        if self._on_poll is not None:
            self._on_poll(self.polls)
        return self.returncode

    def terminate(self) -> None:
        self.terminated += 1
        if self.returncode is None and not self.stubborn:
            self.returncode = TERMINATED_STATUS

    def kill(self) -> None:
        self.killed += 1
        if self.returncode is None:
            self.returncode = KILLED_STATUS

    def wait(self, timeout: float | None = None) -> int:
        self.waits.append(timeout)
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake-browser", 0 if timeout is None else timeout)
        return self.returncode

    def exit(self, status: int = 0) -> None:
        if self.returncode is None:
            self.returncode = status


class ServerSocket:
    def __init__(self, connection: socket.socket) -> None:
        self.connection = connection
        self.connection.settimeout(SERVER_TIMEOUT_SECONDS)
        self.path = ""
        self.request_line = ""
        self.headers: dict[str, str] = {}
        self.frames: list[tuple[bool, int, bytes, bool]] = []
        self.closed_by_client = False
        self._buffer = bytearray()

    def handshake(
        self, *, status: int = 101, accept: str | None = None, extra: bytes = b""
    ) -> None:
        while b"\r\n\r\n" not in self._buffer:
            self._fill()
        head, _, rest = bytes(self._buffer).partition(b"\r\n\r\n")
        self._buffer = bytearray(rest)
        lines = head.decode("iso-8859-1").split("\r\n")
        self.request_line = lines[0]
        self.path = lines[0].split(" ")[1]
        for line in lines[1:]:
            name, _, value = line.partition(":")
            self.headers[name.strip().lower()] = value.strip()
        key = accept if accept is not None else accept_key(self.headers["sec-websocket-key"])
        reason = "Switching Protocols" if status == 101 else "Bad Request"
        answer = (
            f"HTTP/1.1 {status} {reason}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {key}\r\n"
            "\r\n"
        )
        self.connection.sendall(answer.encode("ascii") + extra)

    def receive_frame(self) -> tuple[bool, int, bytes]:
        while True:
            parsed = self._parse()
            if parsed is not None:
                return parsed
            self._fill()

    def receive(self) -> str | None:
        parts: list[bytes] = []
        while True:
            final, opcode, payload = self.receive_frame()
            if opcode == CLOSE:
                self.closed_by_client = True
                with contextlib.suppress(OSError):
                    self.send_frame(CLOSE, payload[:2])
                return None
            if opcode in (PING, PONG):
                continue
            parts.append(payload)
            if final:
                return b"".join(parts).decode("utf-8")

    def send_text(self, text: str, *, fragments: int = 1) -> None:
        data = text.encode("utf-8")
        if fragments <= 1:
            self.send_frame(TEXT, data)
            return
        size = max(len(data) // fragments, 1)
        pieces = [data[start : start + size] for start in range(0, len(data), size)]
        for position, piece in enumerate(pieces):
            opcode = TEXT if position == 0 else CONTINUATION
            self.send_frame(opcode, piece, final=position == len(pieces) - 1)

    def send_frame(
        self,
        opcode: int,
        payload: bytes = b"",
        *,
        final: bool = True,
        mask: bool = False,
        rsv: int = 0,
    ) -> None:
        header = bytearray(frame_header(opcode, len(payload), masked=mask, final=final))
        header[0] |= rsv
        if mask:
            key = os.urandom(4)
            self.connection.sendall(bytes(header) + key + masked(payload, key))
        else:
            self.connection.sendall(bytes(header) + payload)

    def send_raw(self, data: bytes) -> None:
        self.connection.sendall(data)

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self.connection.shutdown(socket.SHUT_RDWR)
        self.connection.close()

    def _fill(self) -> None:
        chunk = self.connection.recv(1 << 20)
        if not chunk:
            raise ConnectionError("the client closed the connection")
        self._buffer += chunk

    def _parse(self) -> tuple[bool, int, bytes] | None:
        buffer = self._buffer
        if len(buffer) < 2:
            return None
        final = bool(buffer[0] & 0x80)
        opcode = buffer[0] & 0x0F
        is_masked = bool(buffer[1] & 0x80)
        length = buffer[1] & 0x7F
        offset = 2
        if length == 126:
            if len(buffer) < 4:
                return None
            length = struct.unpack_from(">H", buffer, 2)[0]
            offset = 4
        elif length == 127:
            if len(buffer) < 10:
                return None
            length = struct.unpack_from(">Q", buffer, 2)[0]
            offset = 10
        key = b""
        if is_masked:
            if len(buffer) < offset + 4:
                return None
            key = bytes(buffer[offset : offset + 4])
            offset += 4
        if len(buffer) < offset + length:
            return None
        payload = bytes(buffer[offset : offset + length])
        del buffer[: offset + length]
        if is_masked:
            payload = masked(payload, key)
        self.frames.append((final, opcode, payload, is_masked))
        return final, opcode, payload


class WebSocketServer:
    def __init__(self, handler: Callable[[ServerSocket], None]) -> None:
        self.handler = handler
        self.connections: list[ServerSocket] = []
        self.errors: list[str] = []
        self._listener: socket.socket | None = None
        self._port = 0
        self._stopping = threading.Event()
        self._acceptor: threading.Thread | None = None
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

    @property
    def port(self) -> int:
        if not self._port:
            raise RuntimeError("the server is not running")
        return self._port

    def url(self, path: str = "/") -> str:
        return f"ws://127.0.0.1:{self.port}{path}"

    def __enter__(self) -> WebSocketServer:
        listener = socket.create_server(("127.0.0.1", 0))
        listener.settimeout(ACCEPT_POLL_SECONDS)
        self._listener = listener
        self._port = int(listener.getsockname()[1])
        self._acceptor = threading.Thread(target=self._accept, name="fake-websocket", daemon=True)
        self._acceptor.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stopping.set()
        if self._acceptor is not None:
            self._acceptor.join()
        if exc[0] is None:
            deadline = time.monotonic() + SERVER_TIMEOUT_SECONDS
            for thread in list(self._threads):
                thread.join(max(deadline - time.monotonic(), 0.0))
        with self._lock:
            connections = list(self.connections)
        for connection in connections:
            connection.close()
        for thread in list(self._threads):
            thread.join()
        if self._listener is not None:
            self._listener.close()
        if self.errors and exc[0] is None:
            raise AssertionError("\n".join(self.errors))

    def _accept(self) -> None:
        listener = self._listener
        while listener is not None and not self._stopping.is_set():
            try:
                accepted, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            connection = ServerSocket(accepted)
            with self._lock:
                self.connections.append(connection)
            thread = threading.Thread(target=self._serve, args=(connection,), daemon=True)
            self._threads.append(thread)
            thread.start()

    def _serve(self, connection: ServerSocket) -> None:
        try:
            self.handler(connection)
        except OSError:
            return
        except Exception:
            self.errors.append(traceback.format_exc())
        finally:
            connection.close()


@dataclass(frozen=True, slots=True)
class EndpointRequest:
    id: int
    method: str
    params: Mapping[str, object]
    session: str | None = None

    @property
    def expression(self) -> str:
        value = self.params.get("expression")
        return value if isinstance(value, str) else ""

    def runs(self, script: str) -> bool:
        return script in self.expression


@dataclass(slots=True)
class Answer:
    method: str
    result: Mapping[str, object] | None = None
    error: str | None = None
    events: tuple[tuple[str, Mapping[str, object]], ...] = ()
    before: tuple[tuple[str, Mapping[str, object]], ...] = ()
    script: str | None = None
    when: Callable[[EndpointRequest], bool] | None = None
    repeat: bool = False
    close: bool = False
    silent: bool = False

    def matches(self, request: EndpointRequest) -> bool:
        if self.method != request.method:
            return False
        if self.script is not None and not request.runs(self.script):
            return False
        return self.when is None or self.when(request)


@dataclass(slots=True)
class ScriptedEndpoint:
    protocol: str = CDP
    snapshot: PageSnapshot = field(default_factory=lambda: page_snapshot())
    points: dict[int, tuple[int, int]] = field(default_factory=dict)
    answers: list[Answer] = field(default_factory=list)
    requests: list[EndpointRequest] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    on_close: Callable[[], None] | None = None
    on_request: Callable[[EndpointRequest], None] | None = None

    @property
    def evaluate_method(self) -> str:
        return "Runtime.evaluate" if self.protocol == CDP else "script.evaluate"

    def answer(
        self,
        method: str,
        result: Mapping[str, object] | None = None,
        *,
        error: str | None = None,
        events: Sequence[tuple[str, Mapping[str, object]]] = (),
        before: Sequence[tuple[str, Mapping[str, object]]] = (),
        script: str | None = None,
        when: Callable[[EndpointRequest], bool] | None = None,
        repeat: bool = False,
        close: bool = False,
        silent: bool = False,
    ) -> ScriptedEndpoint:
        self.answers.append(
            Answer(
                method=method,
                result=result,
                error=error,
                events=tuple(events),
                before=tuple(before),
                script=script,
                when=when,
                repeat=repeat,
                close=close,
                silent=silent,
            )
        )
        return self

    def answer_script(
        self,
        script: str,
        value: object,
        *,
        events: Sequence[tuple[str, Mapping[str, object]]] = (),
        before: Sequence[tuple[str, Mapping[str, object]]] = (),
        repeat: bool = False,
    ) -> ScriptedEndpoint:
        return self.answer(
            self.evaluate_method,
            evaluated(self.protocol, value),
            events=events,
            before=before,
            script=script,
            repeat=repeat,
        )

    def fail_script(self, script: str, text: str, *, repeat: bool = False) -> ScriptedEndpoint:
        return self.answer(
            self.evaluate_method, thrown(self.protocol, text), script=script, repeat=repeat
        )

    def methods(self) -> list[str]:
        return [request.method for request in self.requests]

    def called(self, method: str) -> list[EndpointRequest]:
        return [request for request in self.requests if request.method == method]

    def scripts(self) -> list[str]:
        names = {
            SNAPSHOT_SCRIPT: "snapshot",
            READY_SCRIPT: "ready",
            SCROLL_SCRIPT: "scroll",
            RECT_SCRIPT: "rect",
            FIELD_SCRIPT: "field",
            FOCUS_SCRIPT: "focus",
            VALUE_SCRIPT: "value",
            SELECT_SCRIPT: "select",
        }
        found: list[str] = []
        for request in self.requests:
            if request.method == self.evaluate_method:
                found.append(
                    next((name for script, name in names.items() if request.runs(script)), "?")
                )
        return found

    def serve(self, connection: ServerSocket) -> None:
        connection.handshake()
        self.paths.append(connection.path)
        while True:
            text = connection.receive()
            if text is None:
                return
            message = json.loads(text)
            session = message.get("sessionId")
            request = EndpointRequest(
                id=int(message["id"]),
                method=str(message["method"]),
                params=message.get("params") or {},
                session=session if isinstance(session, str) else None,
            )
            self.requests.append(request)
            if self.on_request is not None:
                self.on_request(request)
            answer = self._chosen(request)
            for method, params in answer.before:
                connection.send_text(self._event(method, params, request))
            if answer.close:
                connection.close()
                return
            if request.method in ("Browser.close", "browser.close") and self.on_close is not None:
                self.on_close()
            if not answer.silent:
                connection.send_text(self._reply(answer, request))
            for method, params in answer.events:
                connection.send_text(self._event(method, params, request))

    def _chosen(self, request: EndpointRequest) -> Answer:
        for position, answer in enumerate(self.answers):
            if answer.matches(request):
                if not answer.repeat:
                    del self.answers[position]
                return answer
        default = self._default(request)
        if default is None:
            self.unexpected.append(request.method)
            return Answer(method=request.method, error=f"unexpected method {request.method}")
        return default

    def _reply(self, answer: Answer, request: EndpointRequest) -> str:
        if self.protocol == CDP:
            message: dict[str, object] = {"id": request.id}
            if answer.error is not None:
                message["error"] = {"code": -32000, "message": answer.error}
            else:
                message["result"] = dict(answer.result or {})
            if request.session is not None:
                message["sessionId"] = request.session
            return json.dumps(message)
        if answer.error is not None:
            return json.dumps(
                {
                    "type": "error",
                    "id": request.id,
                    "error": "unknown error",
                    "message": answer.error,
                }
            )
        return json.dumps(
            {"type": "success", "id": request.id, "result": dict(answer.result or {})}
        )

    def _event(self, method: str, params: Mapping[str, object], request: EndpointRequest) -> str:
        if self.protocol == CDP:
            event: dict[str, object] = {"method": method, "params": dict(params)}
            if request.session is not None:
                event["sessionId"] = request.session
            return json.dumps(event)
        return json.dumps({"type": "event", "method": method, "params": dict(params)})

    def _default(self, request: EndpointRequest) -> Answer | None:
        if request.method == self.evaluate_method:
            return Answer(request.method, evaluated(self.protocol, self._script_value(request)))
        if self.protocol == CDP:
            return _cdp_default(request)
        return _bidi_default(request)

    def _script_value(self, request: EndpointRequest) -> object:
        arguments = _arguments(request.expression)
        index = arguments[0] if arguments else None
        if request.runs(SNAPSHOT_SCRIPT):
            return self.snapshot.document()
        if request.runs(READY_SCRIPT):
            return "complete"
        if request.runs(RECT_SCRIPT):
            x, y = self.points.get(index if isinstance(index, int) else -1, DEFAULT_POINT)
            return {"found": True, "visible": True, "x": x, "y": y}
        if request.runs(FIELD_SCRIPT):
            return {"found": True, "kind": "text"}
        if request.runs(VALUE_SCRIPT) or request.runs(SELECT_SCRIPT):
            return {"found": True, "ok": True}
        return {"found": True}


def evaluated(protocol: str, value: object) -> dict[str, object]:
    remote = {"type": "string", "value": json.dumps(value)}
    if protocol == CDP:
        return {"result": remote}
    return {"type": "success", "result": remote, "realm": "realm-1"}


def thrown(protocol: str, text: str) -> dict[str, object]:
    if protocol == CDP:
        return {
            "result": {"type": "object", "subtype": "error", "description": text},
            "exceptionDetails": {
                "exceptionId": 1,
                "text": "Uncaught",
                "lineNumber": 0,
                "columnNumber": 0,
                "exception": {"type": "object", "subtype": "error", "description": text},
            },
        }
    return {
        "type": "exception",
        "exceptionDetails": {"text": text, "lineNumber": 0, "columnNumber": 0},
        "realm": "realm-1",
    }


def screenshot_answer(data: bytes = FAKE_PNG) -> dict[str, object]:
    return {"data": base64.b64encode(data).decode("ascii")}


def _arguments(expression: str) -> list[object]:
    marker = ")("
    end = expression.rfind("))")
    start = expression.rfind(marker, 0, end)
    if start < 0 or end < 0:
        return []
    try:
        values = json.loads(f"[{expression[start + len(marker) : end]}]")
    except ValueError:
        return []
    return values if isinstance(values, list) else []


def _cdp_default(request: EndpointRequest) -> Answer | None:
    method = request.method
    if method == "Target.createTarget":
        return Answer(method, {"targetId": TARGET})
    if method == "Target.attachToTarget":
        return Answer(method, {"sessionId": SESSION})
    if method == "Browser.getVersion":
        return Answer(
            method,
            {
                "protocolVersion": "1.3",
                "product": f"HeadlessChrome/{CHROME_VERSION}",
                "revision": "@fake",
                "userAgent": f"Mozilla/5.0 HeadlessChrome/{CHROME_VERSION}",
                "jsVersion": "15.1",
            },
        )
    if method == "Page.navigate":
        return Answer(
            method,
            {"frameId": TARGET, "loaderId": LOADER},
            before=(("Page.frameStartedLoading", {"frameId": TARGET}),),
            events=(
                ("Page.loadEventFired", {"timestamp": 1.0}),
                ("Page.frameStoppedLoading", {"frameId": TARGET}),
            ),
        )
    if method == "Page.captureScreenshot":
        return Answer(method, screenshot_answer())
    if method in (
        "Page.enable",
        "Runtime.enable",
        "Emulation.setDeviceMetricsOverride",
        "Input.dispatchMouseEvent",
        "Input.dispatchKeyEvent",
        "Input.insertText",
        "Page.handleJavaScriptDialog",
        "Browser.close",
    ):
        return Answer(method, {})
    return None


def _bidi_default(request: EndpointRequest) -> Answer | None:
    method = request.method
    if method == "session.new":
        return Answer(
            method,
            {
                "sessionId": "bidi-session",
                "capabilities": {
                    "acceptInsecureCerts": False,
                    "browserName": "firefox",
                    "browserVersion": FIREFOX_VERSION,
                    "platformName": "windows",
                    "setWindowRect": False,
                    "userAgent": f"Mozilla/5.0 Firefox/{FIREFOX_VERSION}",
                },
            },
        )
    if method == "browsingContext.getTree":
        return Answer(
            method,
            {
                "contexts": [
                    {
                        "context": CONTEXT,
                        "url": "about:blank",
                        "children": [],
                        "parent": None,
                        "userContext": "default",
                        "originalOpener": None,
                        "clientWindow": "window-1",
                    }
                ]
            },
        )
    if method == "session.subscribe":
        return Answer(method, {"subscription": "subscription-1"})
    if method == "browsingContext.navigate":
        url = str(request.params.get("url", ""))
        started = {"context": CONTEXT, "navigation": "navigation-1", "url": url, "timestamp": 1}
        return Answer(
            method,
            {"navigation": "navigation-1", "url": url},
            before=(
                ("browsingContext.navigationStarted", started),
                ("browsingContext.load", {**started, "timestamp": 2}),
            ),
        )
    if method == "browsingContext.captureScreenshot":
        return Answer(method, screenshot_answer())
    if method in (
        "browsingContext.setViewport",
        "input.performActions",
        "input.releaseActions",
        "browsingContext.handleUserPrompt",
        "browser.close",
    ):
        return Answer(method, {})
    return None


@dataclass(frozen=True, slots=True)
class StartCall:
    arguments: tuple[str, ...]
    folder: Path
    variables: Mapping[str, str]

    @property
    def profile(self) -> Path:
        return profile_of(self.arguments)


def profile_of(arguments: Sequence[str]) -> Path:
    for position, argument in enumerate(arguments):
        if argument.startswith("--user-data-dir="):
            return Path(argument.split("=", 1)[1])
        if argument == "--profile" and position + 1 < len(arguments):
            return Path(arguments[position + 1])
    raise AssertionError(f"no profile folder in {list(arguments)}")


class ScriptedBrowser:
    def __init__(
        self,
        endpoint: ScriptedEndpoint | None = None,
        *,
        protocol: str = CDP,
        exit_status: int | None = None,
        polls_before_ready: int = 0,
        write_port_file: bool = True,
        graceful: bool = True,
        stubborn: bool = False,
    ) -> None:
        self.endpoint = endpoint if endpoint is not None else ScriptedEndpoint(protocol=protocol)
        self.exit_status = exit_status
        self.polls_before_ready = polls_before_ready
        self.write_port_file = write_port_file
        self.graceful = graceful
        self.stubborn = stubborn
        self.calls: list[StartCall] = []
        self.processes: list[FakeProcess] = []
        self.server = WebSocketServer(self.endpoint.serve)
        self.endpoint.on_close = self._closed

    @property
    def protocol(self) -> str:
        return self.endpoint.protocol

    def __enter__(self) -> ScriptedBrowser:
        self.server.__enter__()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.__exit__(*exc)

    def __call__(
        self, arguments: Sequence[str], folder: Path, variables: Mapping[str, str]
    ) -> FakeProcess:
        call = StartCall(tuple(str(item) for item in arguments), Path(folder), dict(variables))
        self.calls.append(call)
        if self.exit_status is not None:
            process = FakeProcess(returncode=self.exit_status)
        else:
            profile = call.profile

            def ready(polls: int) -> None:
                if self.write_port_file and polls >= self.polls_before_ready:
                    self._write_port_file(profile)

            process = FakeProcess(stubborn=self.stubborn, on_poll=ready)
            if self.write_port_file and self.polls_before_ready == 0:
                self._write_port_file(profile)
        self.processes.append(process)
        return process

    def _write_port_file(self, profile: Path) -> None:
        if self.protocol == CDP:
            target = profile / CHROMIUM_PORT_FILE
            if not target.exists():
                target.write_text(f"{self.server.port}\n{BROWSER_PATH}", encoding="utf-8")
            return
        target = profile / FIREFOX_PORT_FILE
        if not target.exists():
            content = json.dumps({"ws_host": "127.0.0.1", "ws_port": self.server.port}, indent=2)
            target.write_text(content, encoding="utf-8")

    def _closed(self) -> None:
        if self.graceful and self.processes:
            self.processes[-1].exit(0)
