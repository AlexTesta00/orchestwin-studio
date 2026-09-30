from __future__ import annotations

import functools
import socketserver
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar, Final

HOST: Final = "127.0.0.1"
POLL_SECONDS: Final = 0.05
REQUEST_TIMEOUT_SECONDS: Final = 10.0
CONTENT_TYPES: Final = MappingProxyType(
    {
        ".html": "text/html",
        ".htm": "text/html",
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".cjs": "text/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".map": "application/json",
        ".webmanifest": "application/manifest+json",
        ".txt": "text/plain",
        ".xml": "application/xml",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".avif": "image/avif",
        ".ico": "image/x-icon",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
        ".otf": "font/otf",
        ".wasm": "application/wasm",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".pdf": "application/pdf",
    }
)


class QuietHandler(SimpleHTTPRequestHandler):
    extensions_map: ClassVar[dict[str, str]] = {
        **SimpleHTTPRequestHandler.extensions_map,
        **CONTENT_TYPES,
    }
    timeout = REQUEST_TIMEOUT_SECONDS

    def log_message(self, *_: object) -> None:
        return None


class LoopbackServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


class StaticServer:
    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self._server: LoopbackServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("the static server is not running")
        return int(self._server.server_address[1])

    @property
    def address(self) -> str:
        return f"http://{HOST}:{self.port}/"

    def start(self) -> StaticServer:
        if self._server is not None:
            raise RuntimeError("the static server is already running")
        handler = functools.partial(QuietHandler, directory=str(self.folder))
        server = LoopbackServer((HOST, 0), handler)
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": POLL_SECONDS},
            name="ut-static-server",
            daemon=True,
        )
        self._server = server
        self._thread = thread
        thread.start()
        return self

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is None:
            return
        try:
            if thread is not None:
                server.shutdown()
        finally:
            server.server_close()
            if thread is not None:
                thread.join()

    def __enter__(self) -> StaticServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
