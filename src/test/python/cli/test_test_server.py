from __future__ import annotations

import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from orchestwin.cli.flows.test_server import StaticServer

PAGE = "<!doctype html><title>Mancia</title><h1>Calcola la mancia</h1>\n"


def site(tmp_path: Path) -> Path:
    folder = tmp_path / "dist"
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_bytes(PAGE.encode("utf-8"))
    (folder / "assets" / "app.js").write_bytes(b"export const tip = 0.15;\n")
    (folder / "assets" / "app.css").write_bytes(b"h1{color:#123}\n")
    return folder


def fetch(address: str) -> tuple[int, str, bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(address, timeout=10) as response:
            return response.status, media_type(response.headers), response.read()
    except urllib.error.HTTPError as error:
        with error:
            return error.code, media_type(error.headers), error.read()


def media_type(headers: object) -> str:
    value = headers.get("Content-Type", "") if hasattr(headers, "get") else ""
    return str(value).split(";", 1)[0].strip()


def test_the_folder_is_served_on_the_loopback_and_nothing_is_logged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = site(tmp_path)

    with StaticServer(folder) as server:
        address = server.address
        page = fetch(address)
        index = fetch(f"{address}index.html")
        script = fetch(f"{address}assets/app.js")
        style = fetch(f"{address}assets/app.css")
        missing = fetch(f"{address}nothing.html")

    assert address == f"http://127.0.0.1:{server_port(address)}/"
    assert page == (200, "text/html", PAGE.encode("utf-8"))
    assert index[0] == 200
    assert script[:2] == (200, "text/javascript")
    assert style[:2] == (200, "text/css")
    assert missing[0] == 404
    assert capsys.readouterr() == ("", "")


def test_the_server_stops_its_thread_and_can_be_stopped_twice(tmp_path: Path) -> None:
    server = StaticServer(site(tmp_path)).start()
    address = server.address

    assert server.running
    assert fetch(address)[0] == 200
    server.stop()
    server.stop()

    assert not server.running
    assert not any(thread.name == "ut-static-server" for thread in threading.enumerate())
    with pytest.raises(RuntimeError):
        _ = server.address


def test_a_server_that_runs_cannot_start_again(tmp_path: Path) -> None:
    with StaticServer(site(tmp_path)) as server, pytest.raises(RuntimeError):
        server.start()


def server_port(address: str) -> int:
    return int(address.rsplit(":", 1)[1].rstrip("/"))
