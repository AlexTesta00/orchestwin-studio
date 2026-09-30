from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from orchestwin.cli.browser.snapshot import (
    FIELD_SCRIPT,
    FOCUS_SCRIPT,
    MAX_SNAPSHOT_ELEMENTS,
    MAX_SNAPSHOT_OPTIONS,
    MAX_SNAPSHOT_TEXT_LENGTH,
    MAX_TARGET_NAME_LENGTH,
    MAX_VALUE_LENGTH,
    READY_SCRIPT,
    RECT_SCRIPT,
    SCROLL_SCRIPT,
    SELECT_SCRIPT,
    SNAPSHOT_SCRIPT,
    VALUE_SCRIPT,
    expression,
)
from orchestwin.cli.errors import CliError

if TYPE_CHECKING:
    from orchestwin.cli.browser.discovery import BrowserProgram
    from orchestwin.cli.browser.launch import Launched
    from orchestwin.cli.browser.protocol import Connection
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.environment import Environment

BROWSER_ERROR_CODES: Final = (
    "BROWSER_NOT_FOUND",
    "BROWSER_NOT_STARTED",
    "BROWSER_PROTOCOL_ERROR",
    "PAGE_NOT_LOADED",
    "ACTION_FAILED",
)
TEST_ROLES: Final = (
    "button",
    "link",
    "textbox",
    "checkbox",
    "radio",
    "combobox",
    "option",
    "slider",
    "spinbutton",
    "switch",
    "heading",
    "text",
    "image",
    "alert",
    "status",
    "dialog",
    "tab",
    "listitem",
    "cell",
    "progressbar",
)
TEST_KEYS: Final = (
    "Enter",
    "Escape",
    "Tab",
    "Space",
    "Backspace",
    "ArrowUp",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
    "Home",
    "End",
)
ELEMENT_STATES: Final = ("checked", "disabled")
BLANK_PAGE: Final = "about:blank"
MAX_DETAIL_LENGTH: Final = 300
MAX_BROWSER_VERSION_LENGTH: Final = 80
DEFAULT_WIDTH: Final = 1280
DEFAULT_HEIGHT: Final = 800
LOAD_TIMEOUT_SECONDS: Final = 30.0
POLL_SECONDS: Final = 0.1
SETTLE_SECONDS: Final = 0.25
SNAPSHOT_ATTEMPTS: Final = 3
COMPLETE: Final = "complete"
CLEAR_KEY: Final = "Delete"
TEXT_FIELD: Final = "text"
SELECT_FIELD: Final = "select"
VALUE_FIELD: Final = "value"


class BrowserError(CliError):
    def __init__(self, code: str, *, program: str = "", detail: str = "") -> None:
        super().__init__(
            code,
            values={"program": program, "detail": shortened(detail, MAX_DETAIL_LENGTH)},
        )

    @property
    def program(self) -> str:
        return str(self.values.get("program", ""))

    @property
    def detail(self) -> str:
        return str(self.values.get("detail", ""))


@dataclass(frozen=True, slots=True)
class Element:
    index: int
    role: str
    name: str
    value: str | None = None
    state: str | None = None
    options: tuple[str, ...] | None = None

    def document(self) -> dict[str, object]:
        return {
            "index": self.index,
            "role": self.role,
            "name": self.name,
            "value": self.value,
            "state": self.state,
            "options": None if self.options is None else list(self.options),
        }


@dataclass(frozen=True, slots=True)
class PageSnapshot:
    url: str
    title: str
    text: str
    elements: tuple[Element, ...]

    def document(self) -> dict[str, object]:
        return {
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "elements": [element.document() for element in self.elements],
        }


class Page(Protocol):
    browser: str
    version: str

    def open(self, url: str) -> None: ...

    def snapshot(self) -> PageSnapshot: ...

    def click(self, element: Element) -> None: ...

    def type(self, element: Element, text: str) -> None: ...

    def select(self, element: Element, option: str) -> None: ...

    def press(self, key: str) -> None: ...

    def screenshot(self) -> bytes: ...

    def close(self) -> None: ...


def open_page(
    context: CommandContext,
    program: BrowserProgram,
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    language: str,
    direct: bool = False,
) -> Page:
    from orchestwin.cli.browser.launch import launch_page

    return launch_page(
        context.environment,
        program,
        width=width,
        height=height,
        language=language,
        direct=direct,
    )


class BrowserPage:
    def __init__(
        self,
        environment: Environment,
        program: BrowserProgram,
        launched: Launched,
        connection: Connection,
    ) -> None:
        self.browser = program.name
        self.version = ""
        self.label = program.label
        self._environment = environment
        self._launched = launched
        self._connection = connection
        self._loading = False
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def open(self, url: str) -> None:
        self._require_open()
        self._navigate(url)
        self._settle(strict=True)

    def snapshot(self) -> PageSnapshot:
        self._require_open()
        failure: BrowserError | None = None
        for _ in range(SNAPSHOT_ATTEMPTS):
            if self._loading:
                self._wait_until_ready(strict=False)
            try:
                document = self._evaluate(
                    expression(SNAPSHOT_SCRIPT), code="BROWSER_PROTOCOL_ERROR"
                )
            except BrowserError as error:
                if self._connection.closed:
                    raise
                failure = error
                self._environment.sleep(POLL_SECONDS)
                continue
            if self._loading:
                continue
            try:
                return snapshot_from_document(document)
            except ValueError as error:
                raise self.error("BROWSER_PROTOCOL_ERROR", f"page description: {error}") from None
        if failure is not None:
            raise failure
        raise self.error("BROWSER_PROTOCOL_ERROR", "the page kept changing while it was read")

    def click(self, element: Element) -> None:
        self._require_open()
        self._click_at(element)
        self._settle(strict=False)

    def type(self, element: Element, text: str) -> None:
        self._require_open()
        kind = self._field_kind(element)
        if kind == SELECT_FIELD:
            self._choose(element, text)
        elif kind == VALUE_FIELD:
            self._set_value(element, text)
        else:
            self._click_at(element)
            self._action(FOCUS_SCRIPT, element.index)
            if text:
                self._insert_text(text)
            else:
                self._key(CLEAR_KEY)
        self._settle(strict=False)

    def select(self, element: Element, option: str) -> None:
        self._require_open()
        self._choose(element, option)
        self._settle(strict=False)

    def press(self, key: str) -> None:
        self._require_open()
        if key not in TEST_KEYS:
            raise self.error("ACTION_FAILED", f"unknown key: {key}")
        self._key(key)
        self._settle(strict=False)

    def screenshot(self) -> bytes:
        self._require_open()
        return self._capture()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._shutdown()
        except BrowserError:
            pass
        finally:
            self._connection.close()
            self._launched.stop(self._environment, graceful=True)

    def error(self, code: str, detail: str) -> BrowserError:
        return BrowserError(code, program=self.label, detail=detail)

    def _require_open(self) -> None:
        if self._closed:
            raise self.error("BROWSER_PROTOCOL_ERROR", "the page is closed")

    def _settle(self, *, strict: bool) -> None:
        self._wait_until_ready(strict=strict)
        self._environment.sleep(SETTLE_SECONDS)

    def _wait_until_ready(self, *, strict: bool) -> None:
        deadline = self._environment.monotonic() + LOAD_TIMEOUT_SECONDS
        while True:
            state = self._ready_state()
            if state == COMPLETE and not self._loading:
                return
            if self._environment.monotonic() >= deadline:
                if strict:
                    raise self.error("PAGE_NOT_LOADED", "the page did not finish loading in time")
                self._loading = False
                return
            self._environment.sleep(POLL_SECONDS)

    def _ready_state(self) -> str | None:
        try:
            state = self._evaluate(expression(READY_SCRIPT), code="BROWSER_PROTOCOL_ERROR")
        except BrowserError:
            if self._connection.closed:
                raise
            return None
        return state if isinstance(state, str) else None

    def _click_at(self, element: Element) -> None:
        self._action(SCROLL_SCRIPT, element.index)
        answer = self._action(RECT_SCRIPT, element.index)
        if answer.get("visible") is not True:
            raise self.error("ACTION_FAILED", f"{describe(element)}: the element cannot be seen")
        x, y = answer.get("x"), answer.get("y")
        if not _is_number(x) or not _is_number(y):
            raise self.error("BROWSER_PROTOCOL_ERROR", "the position of the element is not valid")
        self._mouse_click(round(float(x)), round(float(y)))

    def _field_kind(self, element: Element) -> str:
        kind = self._action(FIELD_SCRIPT, element.index).get("kind")
        return kind if kind in (TEXT_FIELD, SELECT_FIELD, VALUE_FIELD) else TEXT_FIELD

    def _choose(self, element: Element, option: str) -> None:
        answer = self._action(SELECT_SCRIPT, element.index, option)
        if answer.get("ok") is not True:
            detail = answer.get("detail")
            raise self.error(
                "ACTION_FAILED",
                f"{describe(element)}: {detail if isinstance(detail, str) else option}",
            )

    def _set_value(self, element: Element, value: str) -> None:
        answer = self._action(VALUE_SCRIPT, element.index, value)
        if answer.get("ok") is not True:
            raise self.error(
                "ACTION_FAILED", f"{describe(element)}: the field did not accept {value!r}"
            )

    def _action(self, script: str, index: int, *arguments: object) -> Mapping[str, object]:
        answer = self._evaluate(expression(script, index, *arguments), code="ACTION_FAILED")
        if not isinstance(answer, Mapping):
            raise self.error("BROWSER_PROTOCOL_ERROR", "the page answered an action with no result")
        if answer.get("found") is not True:
            raise self.error("ACTION_FAILED", f"element {index} is no longer on the page")
        return answer

    def _decoded(self, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise self.error("BROWSER_PROTOCOL_ERROR", "a page script did not answer with text")
        try:
            return json.loads(value)
        except ValueError:
            raise self.error(
                "BROWSER_PROTOCOL_ERROR", "a page script answered with text that is not JSON"
            ) from None

    def _image(self, answer: Mapping[str, object]) -> bytes:
        data = answer.get("data")
        if not isinstance(data, str):
            raise self.error("BROWSER_PROTOCOL_ERROR", "the screenshot has no image")
        try:
            return base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            raise self.error("BROWSER_PROTOCOL_ERROR", "the screenshot is not valid") from None

    def _evaluate(self, source: str, *, code: str) -> object:
        raise NotImplementedError

    def _navigate(self, url: str) -> None:
        raise NotImplementedError

    def _mouse_click(self, x: int, y: int) -> None:
        raise NotImplementedError

    def _insert_text(self, text: str) -> None:
        raise NotImplementedError

    def _key(self, key: str) -> None:
        raise NotImplementedError

    def _capture(self) -> bytes:
        raise NotImplementedError

    def _shutdown(self) -> None:
        raise NotImplementedError


def snapshot_from_document(document: object) -> PageSnapshot:
    if not isinstance(document, Mapping):
        raise ValueError("not an object")
    elements = document.get("elements")
    if not isinstance(elements, list):
        raise ValueError("elements is not a list")
    if len(elements) > MAX_SNAPSHOT_ELEMENTS:
        raise ValueError(f"more than {MAX_SNAPSHOT_ELEMENTS} elements")
    return PageSnapshot(
        url=_text(document, "url"),
        title=shortened(collapsed(_text(document, "title")), MAX_TARGET_NAME_LENGTH),
        text=shortened(collapsed(_text(document, "text")), MAX_SNAPSHOT_TEXT_LENGTH),
        elements=tuple(_element(item, position) for position, item in enumerate(elements)),
    )


def _element(item: object, position: int) -> Element:
    if not isinstance(item, Mapping):
        raise ValueError(f"element {position} is not an object")
    index = item.get("index")
    if not isinstance(index, int) or isinstance(index, bool) or index != position:
        raise ValueError(f"element {position} has the index {index!r}")
    role = item.get("role")
    if role not in TEST_ROLES:
        raise ValueError(f"element {position} has the role {role!r}")
    value = item.get("value")
    if value is not None and not isinstance(value, str):
        raise ValueError(f"element {position} has a value that is not text")
    state = item.get("state")
    if state is not None and state not in ELEMENT_STATES:
        raise ValueError(f"element {position} has the state {state!r}")
    return Element(
        index=index,
        role=str(role),
        name=shortened(collapsed(_text(item, "name")), MAX_TARGET_NAME_LENGTH),
        value=None if value is None else value[:MAX_VALUE_LENGTH],
        state=state if isinstance(state, str) else None,
        options=_options(item.get("options"), str(role), position),
    )


def _options(options: object, role: str, position: int) -> tuple[str, ...] | None:
    if options is None:
        return None
    if role != "combobox":
        raise ValueError(f"element {position} has options but is not a combobox")
    if not isinstance(options, list) or not all(isinstance(option, str) for option in options):
        raise ValueError(f"element {position} has options that are not texts")
    labels = (shortened(collapsed(option), MAX_TARGET_NAME_LENGTH) for option in options)
    return tuple(label for label in labels if label)[:MAX_SNAPSHOT_OPTIONS]


def _text(document: Mapping[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} is not text")
    return value


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def collapsed(text: str) -> str:
    return " ".join(text.split())


def shortened(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip()


def describe(element: Element) -> str:
    return f"{element.role}: {element.name}" if element.name else element.role


def script_failure(text: str) -> str:
    lines = text.strip().splitlines()
    return f"the page script failed: {lines[0] if lines else 'no reason given'}"


def version_of(text: str) -> str:
    return shortened(collapsed(text), MAX_BROWSER_VERSION_LENGTH)
