from __future__ import annotations

import json
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

import pytest

from orchestwin.cli.http import Reply, unreachable

API = "/api/v1"
COOKIE_NAME = "orchestwin_refresh"


@dataclass(frozen=True, slots=True)
class Sent:
    method: str
    url: str
    path: str
    headers: Mapping[str, str]
    body: bytes | None
    timeout: float

    def json(self) -> object:
        return None if self.body is None else json.loads(self.body.decode("utf-8"))

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


@dataclass(slots=True)
class Expected:
    method: str
    path: str
    status: int = 200
    body: object = None
    headers: Mapping[str, str] = field(default_factory=dict)
    unreachable: bool = False
    sent: bool = False
    respond: Callable[[Sent], Reply] | None = None

    def matches(self, request: Sent) -> bool:
        return self.method == request.method and self.path == request.path

    def answer(self, request: Sent) -> Reply:
        if self.unreachable:
            raise unreachable(request.url, sent=self.sent)
        if self.respond is not None:
            return self.respond(request)
        return reply(self.status, self.body, self.headers)


class ScriptedTransport:
    def __init__(self, *expected: Expected) -> None:
        self.expected: list[Expected] = list(expected)
        self.sent: list[Sent] = []

    def expect(
        self,
        method: str,
        path: str,
        *,
        status: int = 200,
        body: object = None,
        headers: Mapping[str, str] | None = None,
        unreachable: bool = False,
        sent: bool = False,
        respond: Callable[[Sent], Reply] | None = None,
    ) -> ScriptedTransport:
        self.expected.append(
            Expected(
                method=method,
                path=path,
                status=status,
                body=body,
                headers=dict(headers or {}),
                unreachable=unreachable,
                sent=sent,
                respond=respond,
            )
        )
        return self

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> Reply:
        parts = urllib.parse.urlsplit(url)
        path = f"{parts.path}?{parts.query}" if parts.query else parts.path
        request = Sent(
            method=method,
            url=url,
            path=path,
            headers={name.lower(): value for name, value in headers.items()},
            body=body,
            timeout=timeout,
        )
        self.sent.append(request)
        for index, expected in enumerate(self.expected):
            if expected.matches(request):
                del self.expected[index]
                return expected.answer(request)
        pytest.fail(f"unexpected request: {method} {path}")

    def assert_done(self) -> None:
        if self.expected:
            missing = ", ".join(f"{item.method} {item.path}" for item in self.expected)
            pytest.fail(f"expected requests that were never sent: {missing}")

    def requests(self, method: str | None = None, path: str | None = None) -> list[Sent]:
        return [
            request
            for request in self.sent
            if (method is None or request.method == method)
            and (path is None or request.path == path)
        ]


def reply(
    status: int = 200,
    body: object = None,
    headers: Mapping[str, str] | None = None,
) -> Reply:
    extra = dict(headers or {})
    if isinstance(body, bytes):
        return Reply(status, extra, body)
    if body is None:
        return Reply(status, extra, b"")
    content = json.dumps(body).encode("utf-8")
    return Reply(status, {"content-type": "application/json", **extra}, content)


def refresh_cookie(token: str, *, name: str = COOKIE_NAME) -> str:
    return f"{name}={token}; HttpOnly; Max-Age=2592000; Path=/api/v1/auth; SameSite=lax"


def authentication(
    *,
    access_token: str,
    expires_at: datetime,
    email: str = "person@example.test",
) -> dict[str, object]:
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
        "user": {
            "id": "00000000-0000-4000-8000-000000000042",
            "email": email,
            "is_active": True,
            "created_at": "2026-09-01T08:00:00+00:00",
        },
    }


class NoNetwork:
    def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> Reply:
        pytest.fail(f"no request was expected: {method} {url}")
