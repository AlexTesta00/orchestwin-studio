from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from orchestwin.cli.browser.page import BrowserError, BrowserPage, script_failure, version_of
from orchestwin.cli.browser.protocol import PROTOCOL_ERROR, Connection, Event

if TYPE_CHECKING:
    from orchestwin.cli.browser.discovery import BrowserProgram
    from orchestwin.cli.browser.launch import Launched
    from orchestwin.cli.browser.websocket import WebSocket
    from orchestwin.cli.environment import Environment

SHUTDOWN_TIMEOUT_SECONDS: Final = 5.0
SUBSCRIBED_EVENTS: Final = ("browsingContext",)
CAPABILITIES: Final[Mapping[str, object]] = MappingProxyType(
    {"acceptInsecureCerts": False, "unhandledPromptBehavior": {"default": "accept"}}
)
NAVIGATION_STARTED: Final = "browsingContext.navigationStarted"
NAVIGATION_ENDED: Final = frozenset(
    {
        "browsingContext.load",
        "browsingContext.navigationFailed",
        "browsingContext.navigationAborted",
        "browsingContext.fragmentNavigated",
    }
)
PROMPT_OPENED: Final = "browsingContext.userPromptOpened"
HANDLED_PROMPTS: Final = frozenset({"accept", "dismiss"})
KEYS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "Enter": chr(0xE007),
        "Escape": chr(0xE00C),
        "Tab": chr(0xE004),
        "Space": chr(0xE00D),
        "Backspace": chr(0xE003),
        "Delete": chr(0xE017),
        "ArrowUp": chr(0xE013),
        "ArrowDown": chr(0xE015),
        "ArrowLeft": chr(0xE012),
        "ArrowRight": chr(0xE014),
        "Home": chr(0xE011),
        "End": chr(0xE010),
    }
)


class FirefoxPage(BrowserPage):
    def __init__(
        self,
        environment: Environment,
        program: BrowserProgram,
        launched: Launched,
        connection: Connection,
        *,
        context: str,
    ) -> None:
        super().__init__(environment, program, launched, connection)
        self._context = context

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
    ) -> FirefoxPage:
        connection = Connection(socket, program=program.label)
        created = connection.call(
            "session.new", {"capabilities": {"alwaysMatch": dict(CAPABILITIES)}}
        )
        capabilities = created.get("capabilities")
        version = capabilities.get("browserVersion") if isinstance(capabilities, Mapping) else None
        tree = connection.call("browsingContext.getTree", {"maxDepth": 0})
        page = cls(
            environment, program, launched, connection, context=_first_context(tree, program)
        )
        page.version = version_of(version) if isinstance(version, str) else ""
        connection.on_event = page._on_event
        connection.call(
            "browsingContext.setViewport",
            {"context": page._context, "viewport": {"width": width, "height": height}},
        )
        connection.call("session.subscribe", {"events": list(SUBSCRIBED_EVENTS)})
        return page

    def _call(
        self,
        method: str,
        params: Mapping[str, object] | None = None,
        *,
        code: str = PROTOCOL_ERROR,
    ) -> Mapping[str, object]:
        return self._connection.call(method, params, code=code)

    def _on_event(self, event: Event) -> None:
        if event.params.get("context") != self._context:
            return
        if event.method == NAVIGATION_STARTED:
            self._loading = True
        elif event.method in NAVIGATION_ENDED:
            self._loading = False
        elif event.method == PROMPT_OPENED and event.params.get("handler") not in HANDLED_PROMPTS:
            self._connection.send(
                "browsingContext.handleUserPrompt", {"context": self._context, "accept": True}
            )

    def _navigate(self, url: str) -> None:
        self._call(
            "browsingContext.navigate",
            {"context": self._context, "url": url, "wait": "complete"},
            code="PAGE_NOT_LOADED",
        )

    def _evaluate(self, source: str, *, code: str) -> object:
        result = self._call(
            "script.evaluate",
            {
                "expression": source,
                "target": {"context": self._context},
                "awaitPromise": True,
                "resultOwnership": "none",
            },
            code=code,
        )
        if result.get("type") == "exception":
            details = result.get("exceptionDetails")
            text = details.get("text") if isinstance(details, Mapping) else None
            raise self.error(code, script_failure(text if isinstance(text, str) else ""))
        remote = result.get("result")
        if not isinstance(remote, Mapping) or remote.get("type") in ("undefined", "null"):
            return None
        return self._decoded(remote.get("value"))

    def _mouse_click(self, x: int, y: int) -> None:
        self._perform(
            {
                "type": "pointer",
                "id": "mouse",
                "parameters": {"pointerType": "mouse"},
                "actions": [
                    {"type": "pointerMove", "x": x, "y": y, "origin": "viewport"},
                    {"type": "pointerDown", "button": 0},
                    {"type": "pointerUp", "button": 0},
                ],
            }
        )

    def _insert_text(self, text: str) -> None:
        self._perform(_keyboard(list(text)))

    def _key(self, key: str) -> None:
        value = KEYS.get(key)
        if value is None:
            raise self.error("ACTION_FAILED", f"unknown key: {key}")
        self._perform(_keyboard([value]))

    def _capture(self) -> bytes:
        return self._image(
            self._call("browsingContext.captureScreenshot", {"context": self._context})
        )

    def _shutdown(self) -> None:
        self._connection.call("browser.close", timeout=SHUTDOWN_TIMEOUT_SECONDS)

    def _perform(self, source: Mapping[str, object]) -> None:
        self._call(
            "input.performActions",
            {"context": self._context, "actions": [dict(source)]},
            code="ACTION_FAILED",
        )
        self._call("input.releaseActions", {"context": self._context}, code="ACTION_FAILED")


def _keyboard(values: Sequence[str]) -> dict[str, object]:
    actions: list[dict[str, str]] = []
    for value in values:
        actions.append({"type": "keyDown", "value": value})
        actions.append({"type": "keyUp", "value": value})
    return {"type": "key", "id": "keyboard", "actions": actions}


def _first_context(tree: Mapping[str, object], program: BrowserProgram) -> str:
    contexts = tree.get("contexts")
    if isinstance(contexts, list) and contexts and isinstance(contexts[0], Mapping):
        context = contexts[0].get("context")
        if isinstance(context, str) and context:
            return context
    raise BrowserError(PROTOCOL_ERROR, program=program.label, detail="the browser has no page")
