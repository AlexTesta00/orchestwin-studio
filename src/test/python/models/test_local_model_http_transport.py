"""Exercise real loopback HTTP destination binding with a synthetic token."""

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from orchestwin.models.openai_compatible import UrllibOpenAICompatibleTransport


@pytest.mark.parametrize("status", [200, 302, 307, 308])
def test_transport_ignores_ambient_proxy_and_never_follows_redirects(monkeypatch, status):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            requests.append(
                (
                    self.path,
                    self.headers.get("Authorization"),
                    self.rfile.read(int(self.headers["Content-Length"])),
                )
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Location", "/unexpected-destination")
            self.end_headers()
            self.wfile.write(b"{}")

        def do_GET(self):
            requests.append((self.path, self.headers.get("Authorization"), b""))
            self.send_response(200)
            self.end_headers()

    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setenv("NO_PROXY", "")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = asyncio.run(
            UrllibOpenAICompatibleTransport().post_json(
                url=f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                payload={"synthetic": True},
                headers={"Authorization": "Bearer synthetic-only"},
                timeout_seconds=2,
            )
        )
        assert response.status_code == status and response.body == b"{}"
        assert requests == [
            ("/v1/chat/completions", "Bearer synthetic-only", b'{"synthetic":true}')
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
