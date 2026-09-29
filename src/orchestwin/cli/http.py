from __future__ import annotations

import http.client
import ipaddress
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import Message
from types import MappingProxyType
from typing import Final, Protocol

from orchestwin.cli.errors import ApiFailure, CliError

JSON_TYPE: Final = "application/json"
SET_COOKIE: Final = "set-cookie"
LOOPBACK_NAMES: Final = frozenset({"localhost"})
LOOPBACK_SUFFIX: Final = ".localhost"


@dataclass(frozen=True, slots=True)
class Reply:
    status: int
    headers: Mapping[str, str]
    content: bytes

    def __post_init__(self) -> None:
        lowered = {str(name).lower(): str(value) for name, value in self.headers.items()}
        object.__setattr__(self, "headers", MappingProxyType(lowered))

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> object:
        try:
            return json.loads(self.content.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise ApiFailure("API_FAILURE", http_status=self.status) from None


class Transport(Protocol):
    def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> Reply: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrlTransport:
    def __init__(self) -> None:
        self._direct = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self._proxied = urllib.request.build_opener(_NoRedirect())

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
        opener = self._direct if is_loopback(parts.hostname or "") else self._proxied
        request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
        try:
            with opener.open(request, timeout=timeout) as response:
                return Reply(response.status, header_map(response.headers), response.read())
        except urllib.error.HTTPError as error:
            try:
                return Reply(error.code, header_map(error.headers), _error_content(error))
            finally:
                error.close()
        except urllib.error.URLError as error:
            raise unreachable(url, sent=False) from error
        except (OSError, http.client.HTTPException) as error:
            raise unreachable(url, sent=True) from error


def _error_content(error: urllib.error.HTTPError) -> bytes:
    try:
        return error.read()
    except (OSError, http.client.HTTPException, ValueError):
        return b""


def origin_of(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def unreachable(url: str, *, sent: bool) -> CliError:
    return CliError("STUDIO_UNREACHABLE", values={"address": origin_of(url), "sent": sent})


def header_map(message: Message | Mapping[str, str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if message is None:
        return result
    for name, value in message.items():
        key = name.lower()
        if key in result:
            separator = "\n" if key == SET_COOKIE else ", "
            result[key] = f"{result[key]}{separator}{value}"
        else:
            result[key] = value
    return result


def is_loopback(host: str) -> bool:
    name = host.strip().strip("[]").lower().rstrip(".")
    if name in LOOPBACK_NAMES or name.endswith(LOOPBACK_SUFFIX):
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def multipart(
    fields: Mapping[str, str],
    files: Mapping[str, tuple[str, str, bytes]],
) -> tuple[str, bytes]:
    boundary = _boundary(fields, files)
    parts: list[bytes] = []
    for name, value in fields.items():
        head = f'--{boundary}\r\nContent-Disposition: form-data; name="{_quoted(name)}"\r\n\r\n'
        parts.append(head.encode("utf-8") + value.encode("utf-8") + b"\r\n")
    for name, (file_name, media_type, content) in files.items():
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{_quoted(name)}"; '
            f'filename="{_quoted(file_name)}"\r\n'
            f"Content-Type: {media_type}\r\n\r\n"
        )
        parts.append(head.encode("utf-8") + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return f"multipart/form-data; boundary={boundary}", b"".join(parts)


def _boundary(
    fields: Mapping[str, str],
    files: Mapping[str, tuple[str, str, bytes]],
) -> str:
    contents = [value.encode("utf-8") for value in fields.values()]
    contents.extend(content for _, _, content in files.values())
    while True:
        boundary = f"orchestwin-{secrets.token_hex(16)}"
        marker = boundary.encode("ascii")
        if not any(marker in content for content in contents):
            return boundary


def _quoted(value: str) -> str:
    return value.replace('"', "%22").replace("\r", "%0D").replace("\n", "%0A")
