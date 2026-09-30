from __future__ import annotations

import base64
import contextlib
import hashlib
import ipaddress
import os
import socket
import struct
import time
import urllib.parse
from typing import Final

from orchestwin.cli.browser.page import BrowserError
from orchestwin.cli.http import is_loopback

HANDSHAKE_GUID: Final = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_MESSAGE_BYTES: Final = 64 * 1024 * 1024
MAX_HEADER_BYTES: Final = 65536
MAX_CONTROL_BYTES: Final = 125
CONNECT_TIMEOUT_SECONDS: Final = 30.0
SEND_TIMEOUT_SECONDS: Final = 30.0
CLOSE_TIMEOUT_SECONDS: Final = 1.0
READ_SIZE: Final = 262144
CONTINUATION: Final = 0x0
TEXT: Final = 0x1
BINARY: Final = 0x2
CLOSE: Final = 0x8
PING: Final = 0x9
PONG: Final = 0xA
NORMAL_CLOSURE: Final = 1000
HEADER_END: Final = b"\r\n\r\n"


class WebSocket:
    def __init__(
        self, connection: socket.socket, *, program: str = "", buffer: bytes = b""
    ) -> None:
        self._socket = connection
        self._program = program
        self._buffer = bytearray(buffer)
        self._fragments: list[bytes] = []
        self._fragment_size = 0
        self._fragmented = False
        self._closed = False
        self._close_sent = False

    @property
    def closed(self) -> bool:
        return self._closed

    def send(self, text: str) -> None:
        self._send_frame(TEXT, text.encode("utf-8"))

    def receive(self, timeout: float) -> str:
        message = self.poll(timeout)
        if message is None:
            raise self._error(f"no message within {timeout:g} seconds")
        return message

    def poll(self, timeout: float) -> str | None:
        if self._closed:
            raise self._error("the connection is closed")
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            message = self._next_message()
            if message is not None:
                return message
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self._read(remaining)

    def close(self) -> None:
        if self._closed:
            return
        try:
            if not self._close_sent:
                self._close_sent = True
                self._send_frame(CLOSE, struct.pack(">H", NORMAL_CLOSURE))
            self._await_close(CLOSE_TIMEOUT_SECONDS)
        except BrowserError:
            pass
        finally:
            self._shutdown()

    def _next_message(self) -> str | None:
        while True:
            frame = self._take_frame()
            if frame is None:
                return None
            final, opcode, payload = frame
            if opcode == PING:
                self._send_frame(PONG, payload)
            elif opcode == PONG:
                continue
            elif opcode == CLOSE:
                self._answer_close(payload)
                raise self._error(f"the browser closed the connection{_close_reason(payload)}")
            elif opcode in (TEXT, BINARY):
                if self._fragmented:
                    raise self._failure("a message started before the previous one ended")
                if final:
                    return self._decoded(payload)
                self._fragmented = True
                self._fragments = [payload]
                self._fragment_size = len(payload)
            elif opcode == CONTINUATION:
                if not self._fragmented:
                    raise self._failure("a continuation arrived without a message")
                self._fragment_size += len(payload)
                if self._fragment_size > MAX_MESSAGE_BYTES:
                    raise self._failure("a message is larger than 64 MB")
                self._fragments.append(payload)
                if final:
                    data = b"".join(self._fragments)
                    self._fragments = []
                    self._fragment_size = 0
                    self._fragmented = False
                    return self._decoded(data)
            else:
                raise self._failure(f"unknown frame type {opcode}")

    def _take_frame(self) -> tuple[bool, int, bytes] | None:
        buffer = self._buffer
        if len(buffer) < 2:
            return None
        first, second = buffer[0], buffer[1]
        if first & 0x70:
            raise self._failure("a frame uses an extension that was not agreed")
        if second & 0x80:
            raise self._failure("the browser sent a masked frame")
        final = bool(first & 0x80)
        opcode = first & 0x0F
        length = second & 0x7F
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
        if opcode >= CLOSE and (length > MAX_CONTROL_BYTES or not final):
            raise self._failure("a control frame is not valid")
        if length > MAX_MESSAGE_BYTES:
            raise self._failure("a message is larger than 64 MB")
        end = offset + length
        if len(buffer) < end:
            return None
        payload = bytes(buffer[offset:end])
        del buffer[:end]
        return final, opcode, payload

    def _decoded(self, data: bytes) -> str:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            raise self._failure("a message is not valid text") from None

    def _read(self, timeout: float) -> None:
        try:
            self._socket.settimeout(timeout)
            chunk = self._socket.recv(READ_SIZE)
        except TimeoutError:
            return
        except OSError as error:
            self._shutdown()
            raise self._error(f"the connection broke: {error}") from None
        if not chunk:
            self._shutdown()
            raise self._error("the browser closed the connection")
        self._buffer += chunk

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self._closed:
            raise self._error("the connection is closed")
        mask = os.urandom(4)
        frame = frame_header(opcode, len(payload), masked=True) + mask + masked(payload, mask)
        try:
            self._socket.settimeout(SEND_TIMEOUT_SECONDS)
            self._socket.sendall(frame)
        except OSError as error:
            self._shutdown()
            raise self._error(f"a message could not be sent: {error}") from None

    def _answer_close(self, payload: bytes) -> None:
        if not self._close_sent:
            self._close_sent = True
            with contextlib.suppress(BrowserError):
                self._send_frame(CLOSE, payload[:2])
        self._shutdown()

    def _await_close(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while not self._closed:
            try:
                frame = self._take_frame()
            except BrowserError:
                return
            if frame is not None:
                if frame[1] == CLOSE:
                    return
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._read(remaining)

    def _shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(OSError):
            self._socket.shutdown(socket.SHUT_RDWR)
        self._socket.close()

    def _failure(self, detail: str) -> BrowserError:
        self._shutdown()
        return self._error(detail)

    def _error(self, detail: str) -> BrowserError:
        return BrowserError("BROWSER_PROTOCOL_ERROR", program=self._program, detail=detail)


def connect(url: str, *, timeout: float = CONNECT_TIMEOUT_SECONDS, program: str = "") -> WebSocket:
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "ws":
        raise _refused(program, f"{url}: only ws:// addresses are used")
    if not is_loopback(host):
        raise _refused(program, f"{host or url} is not an address of this computer")
    try:
        port = parts.port or 80
    except ValueError:
        raise _refused(program, f"{url}: the port is not valid") from None
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    deadline = time.monotonic() + timeout
    connection = _open_socket(host, port, timeout, program)
    try:
        leftover = _handshake(connection, _host_header(host, port), path, deadline, program)
    except BaseException:
        connection.close()
        raise
    return WebSocket(connection, program=program, buffer=leftover)


def frame_header(opcode: int, length: int, *, masked: bool, final: bool = True) -> bytes:
    first = (0x80 if final else 0) | opcode
    flag = 0x80 if masked else 0
    if length < 126:
        return bytes((first, flag | length))
    if length < 65536:
        return bytes((first, flag | 126)) + struct.pack(">H", length)
    return bytes((first, flag | 127)) + struct.pack(">Q", length)


def masked(payload: bytes, mask: bytes) -> bytes:
    if not payload:
        return b""
    size = len(payload)
    key = (mask * (size // 4 + 1))[:size]
    return (int.from_bytes(payload, "big") ^ int.from_bytes(key, "big")).to_bytes(size, "big")


def accept_key(key: str) -> str:
    digest = hashlib.sha1(f"{key}{HANDSHAKE_GUID}".encode("ascii"), usedforsecurity=False).digest()
    return base64.b64encode(digest).decode("ascii")


def _open_socket(host: str, port: int, timeout: float, program: str) -> socket.socket:
    try:
        found = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as error:
        raise _refused(program, f"{host}: {error}") from None
    addresses = [
        (family, address)
        for family, _, _, _, address in found
        if _loopback_address(str(address[0]))
    ]
    if not addresses:
        raise _refused(program, f"{host} is not an address of this computer")
    failure: OSError | None = None
    for family, address in addresses:
        connection = socket.socket(family, socket.SOCK_STREAM)
        try:
            connection.settimeout(timeout)
            connection.connect(address)
        except OSError as error:
            connection.close()
            failure = error
            continue
        return connection
    raise _refused(program, f"{host}:{port} does not answer: {failure}")


def _handshake(
    connection: socket.socket, host: str, path: str, deadline: float, program: str
) -> bytes:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    try:
        connection.settimeout(max(deadline - time.monotonic(), 0.001))
        connection.sendall(request.encode("ascii"))
    except OSError as error:
        raise _refused(program, f"the handshake could not be sent: {error}") from None
    received = bytearray()
    while HEADER_END not in received:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _refused(program, "no answer to the handshake in time")
        try:
            connection.settimeout(remaining)
            chunk = connection.recv(4096)
        except TimeoutError:
            raise _refused(program, "no answer to the handshake in time") from None
        except OSError as error:
            raise _refused(program, f"the handshake broke: {error}") from None
        if not chunk:
            raise _refused(program, "the browser closed the connection during the handshake")
        received += chunk
        if len(received) > MAX_HEADER_BYTES:
            raise _refused(program, "the answer to the handshake is too long")
    head, _, rest = bytes(received).partition(HEADER_END)
    lines = head.decode("iso-8859-1").split("\r\n")
    status = lines[0].split(" ", 2)
    if len(status) < 2 or status[1] != "101":
        raise _refused(program, f"the browser refused the connection: {lines[0]}")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, separator, value = line.partition(":")
        if separator:
            headers[name.strip().lower()] = value.strip()
    tokens = {token.strip().lower() for token in headers.get("connection", "").split(",")}
    if headers.get("upgrade", "").lower() != "websocket" or "upgrade" not in tokens:
        raise _refused(program, "the answer to the handshake is not a WebSocket upgrade")
    if headers.get("sec-websocket-accept") != accept_key(key):
        raise _refused(program, "the answer to the handshake has a wrong key")
    return rest


def _host_header(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def _loopback_address(address: str) -> bool:
    try:
        return ipaddress.ip_address(address.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _close_reason(payload: bytes) -> str:
    if len(payload) < 2:
        return ""
    return f" (code {struct.unpack('>H', payload[:2])[0]})"


def _refused(program: str, detail: str) -> BrowserError:
    return BrowserError("BROWSER_PROTOCOL_ERROR", program=program, detail=detail)
