from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final

from orchestwin.cli.browser.page import BrowserError
from orchestwin.cli.browser.websocket import WebSocket

REQUEST_TIMEOUT_SECONDS: Final = 30.0
EVENT_LIMIT: Final = 1000
PROTOCOL_ERROR: Final = "BROWSER_PROTOCOL_ERROR"


@dataclass(frozen=True, slots=True)
class Event:
    method: str
    params: Mapping[str, object] = field(default_factory=dict)
    session: str | None = None


class Connection:
    def __init__(
        self,
        socket: WebSocket,
        *,
        program: str = "",
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._socket = socket
        self._program = program
        self._timeout = timeout
        self._last = 0
        self._waiting: set[int] = set()
        self._replies: dict[int, Mapping[str, object]] = {}
        self._events: deque[Event] = deque(maxlen=EVENT_LIMIT)
        self.on_event: Callable[[Event], None] | None = None

    @property
    def closed(self) -> bool:
        return self._socket.closed

    @property
    def events(self) -> tuple[Event, ...]:
        return tuple(self._events)

    def send(
        self,
        method: str,
        params: Mapping[str, object] | None = None,
        *,
        session: str | None = None,
    ) -> int:
        self._last += 1
        message: dict[str, object] = {
            "id": self._last,
            "method": method,
            "params": dict(params or {}),
        }
        if session is not None:
            message["sessionId"] = session
        self._socket.send(json.dumps(message, ensure_ascii=False, separators=(",", ":")))
        return self._last

    def call(
        self,
        method: str,
        params: Mapping[str, object] | None = None,
        *,
        session: str | None = None,
        code: str = PROTOCOL_ERROR,
        timeout: float | None = None,
    ) -> Mapping[str, object]:
        limit = self._timeout if timeout is None else timeout
        identifier = self.send(method, params, session=session)
        self._waiting.add(identifier)
        deadline = time.monotonic() + limit
        try:
            while identifier not in self._replies:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BrowserError(
                        code,
                        program=self._program,
                        detail=f"{method}: no answer within {limit:g} seconds",
                    )
                text = self._socket.poll(remaining)
                if text is not None:
                    self._dispatch(text)
        finally:
            self._waiting.discard(identifier)
        reply = self._replies.pop(identifier)
        failure = refusal(reply)
        if failure is not None:
            raise BrowserError(code, program=self._program, detail=f"{method}: {failure}")
        result = reply.get("result")
        return result if isinstance(result, Mapping) else {}

    def wait_event(
        self,
        method: str,
        *,
        session: str | None = None,
        match: Callable[[Event], bool] | None = None,
        timeout: float | None = None,
    ) -> Event | None:
        limit = self._timeout if timeout is None else timeout
        deadline = time.monotonic() + limit
        while True:
            for event in self._events:
                if (
                    event.method == method
                    and (session is None or event.session == session)
                    and (match is None or match(event))
                ):
                    self._events.remove(event)
                    return event
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            text = self._socket.poll(remaining)
            if text is not None:
                self._dispatch(text)

    def clear_events(self) -> None:
        self._events.clear()

    def close(self) -> None:
        self._socket.close()

    def _dispatch(self, text: str) -> None:
        try:
            message = json.loads(text)
        except ValueError:
            raise self._error("a message of the browser is not JSON") from None
        if not isinstance(message, dict):
            raise self._error("a message of the browser is not an object")
        identifier = message.get("id")
        if isinstance(identifier, int) and not isinstance(identifier, bool):
            if identifier in self._waiting:
                self._replies[identifier] = message
            return
        method = message.get("method")
        if isinstance(method, str):
            params = message.get("params")
            session = message.get("sessionId")
            event = Event(
                method=method,
                params=params if isinstance(params, dict) else {},
                session=session if isinstance(session, str) else None,
            )
            self._events.append(event)
            if self.on_event is not None:
                self.on_event(event)
            return
        failure = refusal(message)
        if failure is not None:
            raise self._error(f"the browser refused a message: {failure}")

    def _error(self, detail: str) -> BrowserError:
        return BrowserError(PROTOCOL_ERROR, program=self._program, detail=detail)


def refusal(message: Mapping[str, object]) -> str | None:
    error = message.get("error")
    if error is None and message.get("type") != "error":
        return None
    if isinstance(error, Mapping):
        text = error.get("message") or error.get("code") or "error"
        return str(text)
    detail = message.get("message")
    if isinstance(error, str):
        return f"{error}: {detail}" if isinstance(detail, str) and detail else error
    return str(detail) if detail else "error"
