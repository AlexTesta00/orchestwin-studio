from __future__ import annotations

import gc
import socket
import threading
import warnings
from collections.abc import Iterator, Mapping
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.http import Reply, UrlTransport, is_loopback, multipart

ROUTES: dict[str, tuple[int, list[tuple[str, str]], bytes]] = {
    "/ok": (
        200,
        [
            ("Content-Type", "application/json"),
            ("X-Mixed-Case", "Value"),
            ("Set-Cookie", "first=1; Path=/"),
            ("Set-Cookie", "second=2; Path=/"),
        ],
        b'{"status": "ok"}',
    ),
    "/missing": (404, [("Content-Type", "application/json")], b'{"detail": "project_not_found"}'),
    "/broken": (500, [("Content-Type", "text/plain")], b"Internal Server Error"),
    "/moved": (302, [("Location", "/ok")], b""),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._answer()

    def do_POST(self) -> None:
        self._answer()

    def log_message(self, *arguments: object) -> None:
        return None

    def _answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.received.append((self.command, self.path, dict(self.headers.items()), body))
        if self.path == "/drop":
            self.close_connection = True
            return
        status, headers, content = ROUTES.get(self.path, (404, [], b""))
        if self.path == "/echo":
            status, headers, content = 200, [("Content-Type", "application/json")], body
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


class Recorder(HTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.received: list[tuple[str, str, dict[str, str], bytes]] = []

    @property
    def address(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"


@pytest.fixture
def server() -> Iterator[Recorder]:
    recorder = Recorder()
    thread = threading.Thread(target=recorder.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield recorder
    finally:
        recorder.shutdown()
        recorder.server_close()
        thread.join()


def send(
    transport: UrlTransport,
    server: Recorder,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> Reply:
    return transport.send(
        method, f"{server.address}{path}", headers=dict(headers or {}), body=body, timeout=10.0
    )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_every_status_comes_back_as_a_reply_and_every_socket_is_closed(server: Recorder) -> None:
    transport = UrlTransport()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        ok = send(transport, server, "GET", "/ok")
        missing = send(transport, server, "GET", "/missing")
        broken = send(transport, server, "GET", "/broken")
        gc.collect()

    assert not [item for item in caught if issubclass(item.category, ResourceWarning)]
    assert ok.status == 200
    assert ok.ok
    assert ok.json() == {"status": "ok"}
    assert missing.status == 404
    assert not missing.ok
    assert missing.json() == {"detail": "project_not_found"}
    assert broken.status == 500
    assert broken.content == b"Internal Server Error"
    with pytest.raises(ApiFailure) as failure:
        broken.json()
    assert failure.value.code == "API_FAILURE"


def test_header_names_are_lower_case_and_repeated_cookies_are_kept(server: Recorder) -> None:
    reply = send(UrlTransport(), server, "GET", "/ok")

    assert all(name == name.lower() for name in reply.headers)
    assert reply.headers["x-mixed-case"] == "Value"
    assert reply.headers["set-cookie"] == "first=1; Path=/\nsecond=2; Path=/"


def test_a_redirect_is_returned_and_never_followed(server: Recorder) -> None:
    reply = send(UrlTransport(), server, "GET", "/moved")

    assert reply.status == 302
    assert reply.headers["location"] == "/ok"
    assert [path for _, path, _, _ in server.received] == ["/moved"]


def test_the_body_and_the_headers_reach_the_server(server: Recorder) -> None:
    reply = send(
        UrlTransport(),
        server,
        "POST",
        "/echo",
        body=b'{"answer": 42}',
        headers={"Content-Type": "application/json", "Prefer": "respond-async"},
    )

    method, path, headers, body = server.received[0]
    assert (method, path, body) == ("POST", "/echo", b'{"answer": 42}')
    assert headers["Prefer"] == "respond-async"
    assert headers["Content-Type"] == "application/json"
    assert reply.json() == {"answer": 42}


def test_the_proxy_of_the_machine_is_bypassed_for_loopback(
    server: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("NO_PROXY", "no_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{free_port()}")
    monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{free_port()}")

    reply = send(UrlTransport(), server, "GET", "/ok")

    assert reply.status == 200
    assert [path for _, path, _, _ in server.received] == ["/ok"]


def test_a_refused_connection_is_unreachable_and_was_not_sent() -> None:
    address = f"http://127.0.0.1:{free_port()}"

    with pytest.raises(CliError) as caught:
        UrlTransport().send("GET", f"{address}/api/v1/health", headers={}, body=None, timeout=10.0)

    assert caught.value.code == "STUDIO_UNREACHABLE"
    assert caught.value.status == 4
    assert caught.value.values["address"] == address
    assert caught.value.values["sent"] is False


def test_an_answer_that_never_arrives_may_have_been_received(server: Recorder) -> None:
    with pytest.raises(CliError) as caught:
        send(UrlTransport(), server, "POST", "/drop", body=b"{}")

    assert caught.value.code == "STUDIO_UNREACHABLE"
    assert caught.value.values["sent"] is True
    assert [path for _, path, _, _ in server.received] == ["/drop"]


def test_a_reply_reads_json_and_lowers_the_header_names() -> None:
    reply = Reply(201, {"X-Content-SHA256": "abc"}, b'{"items": [1, 2]}')

    assert dict(reply.headers) == {"x-content-sha256": "abc"}
    assert reply.ok
    assert reply.json() == {"items": [1, 2]}
    assert not Reply(302, {}, b"").ok
    with pytest.raises(ApiFailure) as failure:
        Reply(200, {}, b"not json").json()
    assert failure.value.http_status == 200


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("127.0.0.2", True),
        ("::1", True),
        ("[::1]", True),
        ("localhost", True),
        ("studio.localhost", True),
        ("LOCALHOST.", True),
        ("192.168.1.10", False),
        ("example.org", False),
        ("localhost.example.org", False),
        ("", False),
    ],
)
def test_loopback_hosts(host: str, expected: bool) -> None:
    assert is_loopback(host) is expected


def test_a_multipart_form_is_read_back_by_the_email_package() -> None:
    content = bytes(range(256)) * 3 + b"\r\n--not-the-boundary\r\n\n\r"
    name = "Calcolo mancia " + chr(0x00E8)
    content_type, body = multipart(
        {"display_name": name},
        {"archive": ('progetto "uno".zip', "application/zip", content)},
    )

    assert content_type.startswith("multipart/form-data; boundary=")
    message = BytesParser(policy=policy.HTTP).parsebytes(
        b"Content-Type: " + content_type.encode("ascii") + b"\r\n\r\n" + body
    )
    parts = list(message.iter_parts())
    names = [part.get_param("name", header="content-disposition") for part in parts]
    assert names == ["display_name", "archive"]
    assert parts[0].get_payload(decode=True).decode("utf-8") == name
    assert parts[1].get_filename() == "progetto %22uno%22.zip"
    assert parts[1].get_content_type() == "application/zip"
    assert parts[1].get_payload(decode=True) == content
