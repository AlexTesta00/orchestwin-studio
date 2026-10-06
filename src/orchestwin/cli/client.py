from __future__ import annotations

import json
import urllib.parse
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from orchestwin import __version__
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.http import JSON_TYPE, SET_COOKIE, Reply, is_loopback
from orchestwin.cli.project import json_default
from orchestwin.cli.session import (
    DEFAULT_COOKIE,
    SessionStore,
    StudioAddress,
    StudioSession,
    parse_moment,
)

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.environment import Environment

ACCOUNTS: Final = "ACCOUNTS"
LOCAL_OWNER: Final = "LOCAL_OWNER"
SESSION_ACCESS: Final = "session"
LOCAL_ACCESS: Final = "local"
REFRESH_MARGIN: Final = timedelta(seconds=60)
GET_ATTEMPTS: Final = 3
GET_RETRY_SECONDS: Final = 2.0
DEFAULT_TIMEOUT: Final = 300.0
AUTH_TIMEOUT: Final = 30.0
HEALTH_TIMEOUT: Final = 10.0
USER_AGENT: Final = f"ut/{__version__}"
REFUSED_RENEWAL: Final = frozenset({401, 403})
ARCHIVE_ACCEPT: Final = "application/zip, application/json;q=0.5"


class StudioClient:
    def __init__(
        self,
        studio: StudioAddress,
        environment: Environment,
        sessions: SessionStore,
    ) -> None:
        self.studio = studio
        self._environment = environment
        self._sessions = sessions
        self._access_mode: str | None = None

    def access_mode(self) -> str:
        if self._access_mode is None:
            reply = self.request("GET", "/auth/mode", timeout=AUTH_TIMEOUT, authorized=False)
            self._access_mode = _mode_of(reply)
        return self._access_mode

    def local_access(self) -> bool:
        host = urllib.parse.urlsplit(self.studio.origin).hostname or ""
        return is_loopback(host) and self.access_mode() == LOCAL_OWNER

    def sign_in(
        self,
        email: str,
        password: str,
        *,
        make_default: bool = True,
    ) -> Mapping[str, object]:
        body = json.dumps({"email": email, "password": password}).encode("utf-8")
        headers = {"Accept": JSON_TYPE, "Content-Type": JSON_TYPE}
        reply = self._send("POST", "/auth/login", headers, body, AUTH_TIMEOUT)
        if reply.status >= 400:
            raise api_failure(reply)
        access, expires, user = _authentication(reply)
        cookie = refresh_cookie(reply.headers.get(SET_COOKIE, ""), DEFAULT_COOKIE)
        known_email = user.get("email")
        session = StudioSession(
            email=known_email if isinstance(known_email, str) and known_email else email,
            cookie_name=cookie[0] if cookie else DEFAULT_COOKIE,
            refresh_token=cookie[1] if cookie else None,
            access_token=access,
            access_expires_at=expires,
            saved_at=self._environment.now(),
            api_prefix=self.studio.api_prefix,
        )
        self._sessions.save(self.studio, session, make_default=make_default)
        return MappingProxyType(dict(user))

    def sign_out(self) -> None:
        with self._sessions.locked():
            session = self._sessions.read(self.studio)
            if session is None:
                return
            try:
                if session.refresh_token:
                    headers = {
                        "Accept": JSON_TYPE,
                        "Cookie": f"{session.cookie_name}={session.refresh_token}",
                    }
                    self._send("POST", "/auth/logout", headers, None, AUTH_TIMEOUT)
            finally:
                self._sessions.forget(self.studio)

    def health(self) -> Reply:
        return self._send("GET", "/health", {"Accept": JSON_TYPE}, None, HEALTH_TIMEOUT)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: object | None = None,
        form: tuple[str, bytes] | None = None,
        prefer_async: bool = False,
        accept: str = JSON_TYPE,
        timeout: float = DEFAULT_TIMEOUT,
        authorized: bool = True,
    ) -> Reply:
        verb = method.upper()
        headers = {"Accept": accept}
        content: bytes | None = None
        if form is not None:
            headers["Content-Type"], content = form
        elif body is not None:
            headers["Content-Type"] = JSON_TYPE
            content = json.dumps(body, ensure_ascii=False, default=json_default).encode("utf-8")
        if prefer_async:
            headers["Prefer"] = "respond-async"
        attempts = GET_ATTEMPTS if verb == "GET" else 1
        if not authorized:
            return self._exchange(verb, path, headers, content, timeout, attempts)
        session = self._current()
        reply = self._exchange(verb, path, _bearer(headers, session), content, timeout, attempts)
        if reply.status != 401:
            return reply
        if session is None:
            raise CliError("NOT_SIGNED_IN", values={"studio": self.studio.origin})
        renewed = self._renew(session)
        return self._exchange(verb, path, _bearer(headers, renewed), content, timeout, attempts)

    def get(self, path: str, *, optional: bool = False) -> object:
        reply = self.request("GET", path)
        if optional and reply.status == 404:
            return None
        return payload(reply)

    def post(self, path: str, body: object | None = None) -> object:
        return payload(self.request("POST", path, body=body))

    def patch(self, path: str, body: object | None = None) -> object:
        return payload(self.request("PATCH", path, body=body))

    def download(self, path: str) -> Reply:
        reply = self.request("GET", path, accept=ARCHIVE_ACCEPT)
        if reply.status >= 400:
            raise api_failure(reply)
        return reply

    def _exchange(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str],
        content: bytes | None,
        timeout: float,
        attempts: int,
    ) -> Reply:
        attempt = 1
        while True:
            try:
                return self._send(method, path, headers, content, timeout)
            except CliError as error:
                if error.code != "STUDIO_UNREACHABLE" or attempt >= attempts:
                    raise
            attempt += 1
            self._environment.sleep(GET_RETRY_SECONDS)

    def _send(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str],
        content: bytes | None,
        timeout: float,
    ) -> Reply:
        return self._environment.transport.send(
            method,
            self.studio.url(path),
            headers={"User-Agent": USER_AGENT, **headers},
            body=content,
            timeout=timeout,
        )

    def _current(self) -> StudioSession | None:
        session = self._sessions.read(self.studio)
        if session is None or not session.signed_in:
            if self.local_access():
                return None
            raise CliError("NOT_SIGNED_IN", values={"studio": self.studio.origin})
        if self._fresh(session):
            return session
        return self._renew(session)

    def _fresh(self, session: StudioSession) -> bool:
        return (
            session.access_token is not None
            and session.access_expires_at is not None
            and self._environment.now() < session.access_expires_at - REFRESH_MARGIN
        )

    def _renew(self, stale: StudioSession) -> StudioSession:
        with self._sessions.locked():
            current = self._sessions.read(self.studio)
            if current is None or not current.signed_in:
                raise CliError("NOT_SIGNED_IN", values={"studio": self.studio.origin})
            changed = (current.access_token, current.refresh_token) != (
                stale.access_token,
                stale.refresh_token,
            )
            if changed and self._fresh(current):
                return current
            if not current.refresh_token:
                raise CliError("SESSION_EXPIRED", values={"studio": self.studio.origin})
            return self._refresh(current)

    def _refresh(self, current: StudioSession) -> StudioSession:
        headers = {
            "Accept": JSON_TYPE,
            "Cookie": f"{current.cookie_name}={current.refresh_token}",
        }
        try:
            reply = self._send("POST", "/auth/refresh", headers, None, AUTH_TIMEOUT)
        except CliError as error:
            if error.values.get("sent") is not False:
                self._sessions.save(self.studio, replace(current, refresh_token=None))
            raise
        if reply.status in REFUSED_RENEWAL:
            self._sessions.save(self.studio, current.without_tokens())
            raise CliError("SESSION_EXPIRED", values={"studio": self.studio.origin})
        if reply.status >= 400:
            raise api_failure(reply)
        cookie = refresh_cookie(reply.headers.get(SET_COOKIE, ""), current.cookie_name)
        rotated = replace(
            current,
            refresh_token=cookie[1] if cookie else None,
            saved_at=self._environment.now(),
        )
        try:
            access, expires, _ = _authentication(reply)
        except ApiFailure:
            self._sessions.save(
                self.studio, replace(rotated, access_token=None, access_expires_at=None)
            )
            raise
        renewed = replace(rotated, access_token=access, access_expires_at=expires)
        self._sessions.save(self.studio, renewed)
        return renewed


def ensure_access(context: CommandContext, client: StudioClient) -> str:
    session = context.sessions.read(client.studio)
    if session is not None and session.signed_in:
        return SESSION_ACCESS
    if client.local_access():
        return LOCAL_ACCESS
    raise CliError("NOT_SIGNED_IN", values={"studio": client.studio.origin})


def _mode_of(reply: Reply) -> str:
    if not reply.ok:
        return ACCOUNTS
    try:
        document = reply.json()
    except ApiFailure:
        return ACCOUNTS
    found = document.get("access_mode") if isinstance(document, dict) else None
    return LOCAL_OWNER if found == LOCAL_OWNER else ACCOUNTS


def _bearer(headers: Mapping[str, str], session: StudioSession | None) -> dict[str, str]:
    if session is None:
        return dict(headers)
    return {**headers, "Authorization": f"Bearer {session.access_token}"}


def _authentication(reply: Reply) -> tuple[str, datetime, Mapping[str, object]]:
    document = reply.json()
    if not isinstance(document, dict):
        raise ApiFailure("API_FAILURE", http_status=reply.status)
    access = document.get("access_token")
    expires = parse_moment(document.get("expires_at"))
    user = document.get("user")
    if not isinstance(access, str) or not access or expires is None:
        raise ApiFailure("API_FAILURE", http_status=reply.status)
    return access, expires, user if isinstance(user, dict) else {}


def refresh_cookie(header: str, preferred: str) -> tuple[str, str] | None:
    found: list[tuple[str, str]] = []
    for line in header.split("\n"):
        name, separator, value = line.split(";", 1)[0].strip().partition("=")
        cleaned = value.strip().strip('"')
        if separator and name.strip() and cleaned:
            found.append((name.strip(), cleaned))
    for name, value in found:
        if name == preferred:
            return name, value
    return found[0] if len(found) == 1 else None


def payload(reply: Reply) -> object:
    if reply.status >= 400:
        raise api_failure(reply)
    if not reply.content.strip():
        return None
    return reply.json()


def api_failure(reply: Reply) -> ApiFailure:
    try:
        document = json.loads(reply.content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        document = None
    detail = document.get("detail") if isinstance(document, dict) else document
    if isinstance(detail, dict) and isinstance(detail.get("code"), str) and detail["code"]:
        code = detail["code"]
    elif isinstance(detail, str) and detail:
        code = detail
    else:
        code = "API_FAILURE"
    return ApiFailure(code, http_status=reply.status, detail=detail)
