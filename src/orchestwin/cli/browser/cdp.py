from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from orchestwin.cli.browser.page import (
    BLANK_PAGE,
    LOAD_TIMEOUT_SECONDS,
    BrowserError,
    BrowserPage,
    script_failure,
    version_of,
)
from orchestwin.cli.browser.protocol import PROTOCOL_ERROR, Connection, Event

if TYPE_CHECKING:
    from orchestwin.cli.browser.discovery import BrowserProgram
    from orchestwin.cli.browser.launch import Launched
    from orchestwin.cli.browser.websocket import WebSocket
    from orchestwin.cli.environment import Environment

SHUTDOWN_TIMEOUT_SECONDS: Final = 5.0
LOAD_EVENT: Final = "Page.loadEventFired"
STARTED_LOADING: Final = "Page.frameStartedLoading"
STOPPED_LOADING: Final = "Page.frameStoppedLoading"
DIALOG_OPENING: Final = "Page.javascriptDialogOpening"


@dataclass(frozen=True, slots=True)
class KeyStroke:
    key: str
    code: str
    virtual: int
    text: str = ""


KEYS: Final[Mapping[str, KeyStroke]] = MappingProxyType(
    {
        "Enter": KeyStroke("Enter", "Enter", 13, "\r"),
        "Escape": KeyStroke("Escape", "Escape", 27),
        "Tab": KeyStroke("Tab", "Tab", 9),
        "Space": KeyStroke(" ", "Space", 32, " "),
        "Backspace": KeyStroke("Backspace", "Backspace", 8),
        "Delete": KeyStroke("Delete", "Delete", 46),
        "ArrowUp": KeyStroke("ArrowUp", "ArrowUp", 38),
        "ArrowDown": KeyStroke("ArrowDown", "ArrowDown", 40),
        "ArrowLeft": KeyStroke("ArrowLeft", "ArrowLeft", 37),
        "ArrowRight": KeyStroke("ArrowRight", "ArrowRight", 39),
        "Home": KeyStroke("Home", "Home", 36),
        "End": KeyStroke("End", "End", 35),
    }
)


class ChromiumPage(BrowserPage):
    def __init__(
        self,
        environment: Environment,
        program: BrowserProgram,
        launched: Launched,
        connection: Connection,
        *,
        target: str,
        session: str,
    ) -> None:
        super().__init__(environment, program, launched, connection)
        self._target = target
        self._session = session
        self._frame = target

    @classmethod
    def start(
        cls,
        environment: Environment,
        program: BrowserProgram,
        launched: Launched,
        socket: WebSocket,
        *,
        width: int,
        height: int,
    ) -> ChromiumPage:
        connection = Connection(socket, program=program.label)
        created = connection.call("Target.createTarget", {"url": BLANK_PAGE})
        target = _identifier(created, "targetId", program)
        attached = connection.call("Target.attachToTarget", {"targetId": target, "flatten": True})
        session = _identifier(attached, "sessionId", program)
        page = cls(environment, program, launched, connection, target=target, session=session)
        connection.on_event = page._on_event
        page._call("Page.enable")
        page._call("Runtime.enable")
        page._call(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
        )
        product = connection.call("Browser.getVersion").get("product")
        page.version = version_of(product.split("/", 1)[-1]) if isinstance(product, str) else ""
        return page

    def _call(
        self,
        method: str,
        params: Mapping[str, object] | None = None,
        *,
        code: str = PROTOCOL_ERROR,
    ) -> Mapping[str, object]:
        return self._connection.call(method, params, session=self._session, code=code)

    def _on_event(self, event: Event) -> None:
        if event.session != self._session:
            return
        if event.method == STARTED_LOADING and event.params.get("frameId") == self._frame:
            self._loading = True
        elif event.method == STOPPED_LOADING and event.params.get("frameId") == self._frame:
            self._loading = False
        elif event.method == DIALOG_OPENING:
            answer: dict[str, object] = {"accept": True}
            if event.params.get("type") == "prompt":
                answer["promptText"] = str(event.params.get("defaultPrompt") or "")
            self._connection.send("Page.handleJavaScriptDialog", answer, session=self._session)

    def _navigate(self, url: str) -> None:
        self._connection.clear_events()
        result = self._call("Page.navigate", {"url": url}, code="PAGE_NOT_LOADED")
        failure = result.get("errorText")
        if isinstance(failure, str) and failure:
            raise self.error("PAGE_NOT_LOADED", f"{url}: {failure}")
        frame = result.get("frameId")
        if isinstance(frame, str) and frame:
            self._frame = frame
        if result.get("loaderId"):
            loaded = self._connection.wait_event(
                LOAD_EVENT, session=self._session, timeout=LOAD_TIMEOUT_SECONDS
            )
            if loaded is None:
                raise self.error(
                    "PAGE_NOT_LOADED", f"{url}: the page did not finish loading in time"
                )

    def _evaluate(self, source: str, *, code: str) -> object:
        result = self._call(
            "Runtime.evaluate",
            {"expression": source, "returnByValue": True, "awaitPromise": True},
            code=code,
        )
        details = result.get("exceptionDetails")
        if isinstance(details, Mapping):
            raise self.error(code, script_failure(_exception_text(details)))
        remote = result.get("result")
        return self._decoded(remote.get("value") if isinstance(remote, Mapping) else None)

    def _mouse_click(self, x: int, y: int) -> None:
        for event in (
            {"type": "mouseMoved", "x": x, "y": y},
            {
                "type": "mousePressed",
                "x": x,
                "y": y,
                "button": "left",
                "buttons": 1,
                "clickCount": 1,
            },
            {
                "type": "mouseReleased",
                "x": x,
                "y": y,
                "button": "left",
                "buttons": 0,
                "clickCount": 1,
            },
        ):
            self._call("Input.dispatchMouseEvent", event, code="ACTION_FAILED")

    def _insert_text(self, text: str) -> None:
        self._call("Input.insertText", {"text": text}, code="ACTION_FAILED")

    def _key(self, key: str) -> None:
        stroke = KEYS.get(key)
        if stroke is None:
            raise self.error("ACTION_FAILED", f"unknown key: {key}")
        down: dict[str, object] = {
            "type": "keyDown" if stroke.text else "rawKeyDown",
            "key": stroke.key,
            "code": stroke.code,
            "windowsVirtualKeyCode": stroke.virtual,
        }
        if stroke.text:
            down["text"] = stroke.text
            down["unmodifiedText"] = stroke.text
        up = {
            "type": "keyUp",
            "key": stroke.key,
            "code": stroke.code,
            "windowsVirtualKeyCode": stroke.virtual,
        }
        self._call("Input.dispatchKeyEvent", down, code="ACTION_FAILED")
        self._call("Input.dispatchKeyEvent", up, code="ACTION_FAILED")

    def _capture(self) -> bytes:
        return self._image(self._call("Page.captureScreenshot", {"format": "png"}))

    def _shutdown(self) -> None:
        self._connection.call("Browser.close", timeout=SHUTDOWN_TIMEOUT_SECONDS)


def _identifier(answer: Mapping[str, object], key: str, program: BrowserProgram) -> str:
    value = answer.get(key)
    if isinstance(value, str) and value:
        return value
    raise BrowserError(PROTOCOL_ERROR, program=program.label, detail=f"the browser gave no {key}")


def _exception_text(details: Mapping[str, object]) -> str:
    exception = details.get("exception")
    if isinstance(exception, Mapping):
        description = exception.get("description")
        if isinstance(description, str) and description:
            return description
    text = details.get("text")
    return text if isinstance(text, str) else ""
