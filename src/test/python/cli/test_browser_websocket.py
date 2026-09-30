from __future__ import annotations

import base64
import socket
import struct
from collections.abc import Callable

import pytest

from orchestwin.cli.browser.page import BrowserError
from orchestwin.cli.browser.websocket import (
    BINARY,
    CLOSE,
    CONTINUATION,
    PING,
    PONG,
    TEXT,
    WebSocket,
    accept_key,
    connect,
    frame_header,
)

from .support.browsers import ServerSocket, WebSocketServer

Handler = Callable[[ServerSocket], None]
MEGABYTE = 1024 * 1024


def serving(handler: Handler) -> WebSocketServer:
    return WebSocketServer(handler)


def protocol_error(caught: pytest.ExceptionInfo[BrowserError]) -> str:
    assert caught.value.code == "BROWSER_PROTOCOL_ERROR"
    assert caught.value.status == 1
    return caught.value.detail


def test_the_handshake_asks_for_an_upgrade_with_a_fresh_key() -> None:
    seen: list[ServerSocket] = []

    def handler(connection: ServerSocket) -> None:
        connection.handshake()
        seen.append(connection)
        connection.receive()

    with serving(handler) as server:
        client = connect(server.url("/devtools/browser/abc?x=1"), program="Google Chrome")
        client.close()

    connection = seen[0]
    assert connection.request_line == "GET /devtools/browser/abc?x=1 HTTP/1.1"
    assert connection.headers["host"] == f"127.0.0.1:{server.port}"
    assert connection.headers["upgrade"] == "websocket"
    assert connection.headers["connection"] == "Upgrade"
    assert connection.headers["sec-websocket-version"] == "13"
    assert len(base64.b64decode(connection.headers["sec-websocket-key"])) == 16
    assert "origin" not in connection.headers
    assert client.closed


def test_the_accept_key_follows_the_standard() -> None:
    assert accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def test_messages_travel_both_ways_and_the_client_masks_its_frames() -> None:
    received: list[str] = []

    def handler(connection: ServerSocket) -> None:
        connection.handshake()
        received.append(connection.receive() or "")
        connection.send_text("risposta: caffè")
        connection.receive()

    with serving(handler) as server:
        client = connect(server.url())
        client.send("domanda: perché?")
        answer = client.receive(5)
        client.close()

    assert received == ["domanda: perché?"]
    assert answer == "risposta: caffè"
    frames = server.connections[0].frames
    assert frames[0] == (True, TEXT, "domanda: perché?".encode(), True)
    assert frames[-1][1] == CLOSE
    assert all(frame[3] for frame in frames)


def test_bytes_that_arrive_with_the_handshake_are_kept() -> None:
    def handler(connection: ServerSocket) -> None:
        payload = b"subito"
        connection.handshake(extra=frame_header(TEXT, len(payload), masked=False) + payload)
        connection.receive()

    with serving(handler) as server:
        client = connect(server.url())
        assert client.receive(5) == "subito"
        client.close()


def test_a_fragmented_message_is_assembled_even_with_a_ping_in_the_middle() -> None:
    def handler(connection: ServerSocket) -> None:
        connection.handshake()
        connection.send_frame(TEXT, b"uno ", final=False)
        connection.send_frame(PING, b"ci sei?")
        connection.send_frame(CONTINUATION, b"due ", final=False)
        connection.send_frame(CONTINUATION, b"tre", final=True)
        connection.send_text("quattro cinque sei", fragments=3)
        connection.receive()

    with serving(handler) as server:
        client = connect(server.url())
        first = client.receive(5)
        second = client.receive(5)
        client.close()

    assert (first, second) == ("uno due tre", "quattro cinque sei")
    pongs = [frame for frame in server.connections[0].frames if frame[1] == PONG]
    assert pongs == [(True, PONG, b"ci sei?", True)]


def test_a_ping_is_answered_and_a_pong_is_ignored() -> None:
    def handler(connection: ServerSocket) -> None:
        connection.handshake()
        connection.send_frame(PONG, b"spontaneo")
        connection.send_frame(PING, b"eco")
        connection.send_text("dopo")
        connection.receive()

    with serving(handler) as server:
        client = connect(server.url())
        assert client.receive(5) == "dopo"
        client.close()

    frames = server.connections[0].frames
    assert (True, PONG, b"eco", True) in frames


def test_large_messages_use_the_long_lengths_both_ways() -> None:
    megabyte = "x" * MEGABYTE
    middle = "y" * 1000
    received: list[str] = []

    def handler(connection: ServerSocket) -> None:
        connection.handshake()
        received.append(connection.receive() or "")
        received.append(connection.receive() or "")
        connection.send_text(megabyte)
        connection.send_text(middle)
        connection.receive()

    with serving(handler) as server:
        client = connect(server.url())
        client.send(megabyte)
        client.send(middle)
        assert client.receive(10) == megabyte
        assert client.receive(10) == middle
        client.close()

    assert received == [megabyte, middle]


def test_binary_messages_are_read_as_text() -> None:
    def handler(connection: ServerSocket) -> None:
        connection.handshake()
        connection.send_frame(BINARY, b"binario")
        connection.receive()

    with serving(handler) as server:
        client = connect(server.url())
        assert client.receive(5) == "binario"
        client.close()


def test_closing_sends_the_close_frame_and_waits_for_the_answer() -> None:
    def handler(connection: ServerSocket) -> None:
        connection.handshake()
        connection.receive()

    with serving(handler) as server:
        client = connect(server.url())
        client.close()
        client.close()

    closing = [frame for frame in server.connections[0].frames if frame[1] == CLOSE]
    assert closing == [(True, CLOSE, struct.pack(">H", 1000), True)]
    assert server.connections[0].closed_by_client
    assert client.closed


def test_the_browser_closing_first_is_answered_and_reported() -> None:
    def handler(connection: ServerSocket) -> None:
        connection.handshake()
        connection.send_frame(CLOSE, struct.pack(">H", 1001))
        connection.receive_frame()

    with serving(handler) as server:
        client = connect(server.url(), program="Mozilla Firefox")
        with pytest.raises(BrowserError) as caught:
            client.receive(5)
        client.close()

    assert protocol_error(caught) == "the browser closed the connection (code 1001)"
    assert caught.value.program == "Mozilla Firefox"
    assert server.connections[0].frames == [(True, CLOSE, struct.pack(">H", 1001), True)]
    assert client.closed


def test_a_connection_that_drops_is_an_error() -> None:
    def handler(connection: ServerSocket) -> None:
        connection.handshake()

    with serving(handler) as server:
        client = connect(server.url())
        with pytest.raises(BrowserError) as caught:
            client.receive(5)
        with pytest.raises(BrowserError):
            client.send("ancora")
        client.close()

    assert protocol_error(caught) == "the browser closed the connection"


@pytest.mark.parametrize(
    ("send", "detail"),
    [
        (lambda connection: connection.send_frame(TEXT, b"x", mask=True), "masked frame"),
        (lambda connection: connection.send_frame(TEXT, b"x", rsv=0x40), "extension"),
        (lambda connection: connection.send_frame(0x3, b"x"), "unknown frame type 3"),
        (lambda connection: connection.send_frame(CONTINUATION, b"x"), "continuation"),
        (lambda connection: connection.send_frame(PING, b"x", final=False), "control frame"),
        (lambda connection: connection.send_frame(TEXT, b"\xff\xfe"), "not valid text"),
        (
            lambda connection: connection.send_raw(
                bytes((0x81, 127)) + struct.pack(">Q", 64 * MEGABYTE + 1)
            ),
            "larger than 64 MB",
        ),
        (
            lambda connection: (
                connection.send_frame(TEXT, b"a", final=False),
                connection.send_frame(TEXT, b"b"),
            ),
            "started before",
        ),
    ],
)
def test_frames_that_break_the_rules_close_the_connection(
    send: Callable[[ServerSocket], object], detail: str
) -> None:
    def handler(connection: ServerSocket) -> None:
        connection.handshake()
        send(connection)
        connection.receive()

    with serving(handler) as server:
        client = connect(server.url())
        with pytest.raises(BrowserError) as caught:
            client.receive(5)
        client.close()

    assert detail in protocol_error(caught)
    assert client.closed


def test_nothing_waiting_answers_none_or_an_error_at_once() -> None:
    def handler(connection: ServerSocket) -> None:
        connection.handshake()
        connection.receive()

    with serving(handler) as server:
        client = connect(server.url())
        assert client.poll(0) is None
        with pytest.raises(BrowserError) as caught:
            client.receive(0)
        client.close()

    assert protocol_error(caught) == "no message within 0 seconds"


@pytest.mark.parametrize(
    ("status", "accept", "detail"),
    [
        (400, None, "refused the connection: HTTP/1.1 400 Bad Request"),
        (101, "d3Jvbmcta2V5", "wrong key"),
    ],
)
def test_a_handshake_that_is_refused_is_an_error(
    status: int, accept: str | None, detail: str
) -> None:
    def handler(connection: ServerSocket) -> None:
        connection.handshake(status=status, accept=accept)

    with serving(handler) as server, pytest.raises(BrowserError) as caught:
        connect(server.url())

    assert detail in protocol_error(caught)


@pytest.mark.parametrize(
    "address",
    [
        "ws://example.com:9222/devtools",
        "ws://10.0.0.1:9222/",
        "ws://[2001:db8::1]:9222/",
        "wss://127.0.0.1:9222/",
        "http://127.0.0.1:9222/",
        "ws://127.0.0.1:99999/",
    ],
)
def test_only_the_loopback_is_ever_reached(address: str) -> None:
    with pytest.raises(BrowserError) as caught:
        connect(address, timeout=0.2)

    assert protocol_error(caught)


def test_a_server_that_stays_silent_times_out() -> None:
    with socket.create_server(("127.0.0.1", 0)) as listener:
        port = listener.getsockname()[1]
        with pytest.raises(BrowserError) as caught:
            connect(f"ws://127.0.0.1:{port}/session", timeout=0.2)

    assert protocol_error(caught) == "no answer to the handshake in time"


def test_bytes_given_at_construction_are_read_first() -> None:
    first, second = socket.socketpair()
    with second:
        start = frame_header(TEXT, 2, masked=False) + b"ok"
        client = WebSocket(first, program="Google Chrome", buffer=start)
        assert client.receive(0) == "ok"
        second.sendall(frame_header(CLOSE, 2, masked=False) + struct.pack(">H", 1000))
        client.close()

    assert client.closed
