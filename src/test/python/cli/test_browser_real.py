from __future__ import annotations

import functools
import io
import os
import socketserver
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from orchestwin.cli.browser import (
    BROWSER_NAMES,
    BrowserProgram,
    Element,
    Page,
    PageSnapshot,
    find_browsers,
    matches_text,
    open_page,
    resolve_target,
)
from orchestwin.cli.console import Console
from orchestwin.cli.context import CommandContext
from orchestwin.cli.environment import (
    Environment,
    RunningProcess,
    default_start_process,
    utc_now,
)

from .support.transports import NoNetwork

pytestmark = pytest.mark.browser

SKIP_VARIABLE = "ORCHESTWIN_SKIP_BROWSER_TESTS"
ATTEMPTS = 4
PAUSE_SECONDS = 0.4
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ORDER_PAGE = """<!doctype html>
<html lang="it">
<head><meta charset="utf-8"><title>Prova ordini</title></head>
<body>
<h1>Nuovo ordine</h1>
<p>Compila il modulo e <strong>controlla</strong> il riepilogo.</p>
<form action="/sent.html" method="get">
  <label for="name">Nome cliente</label>
  <input id="name" name="name" type="text">
  <label for="size">Taglia</label>
  <select id="size" name="size">
    <option value="s">Piccola</option><option value="m">Media</option><option value="l">Grande</option>
  </select>
  <label><input type="checkbox" id="gift" name="gift"> Confezione regalo</label>
  <button type="button" id="check">Controlla</button>
  <button type="submit">Invia</button>
  <p role="status" id="result"></p>
  <a href="/help.html">Aiuto</a>
  <div style="display:none">Testo nascosto</div>
</form>
<script>
document.getElementById("check").addEventListener("click", () => {
  const name = document.getElementById("name").value;
  const size = document.getElementById("size").selectedOptions[0].textContent;
  const gift = document.getElementById("gift").checked ? " con regalo" : "";
  document.getElementById("result").textContent = "Ordine di " + name + ": " + size + gift;
});
</script>
</body>
</html>
"""
SENT_PAGE = """<!doctype html>
<html lang="it"><head><meta charset="utf-8"><title>Inviato</title></head>
<body><h1>Ordine inviato</h1></body></html>
"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return None


class LoopbackServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = True

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


class RecordedStarts:
    def __init__(self) -> None:
        self.processes: list[RunningProcess] = []
        self.folders: list[Path] = []

    def __call__(
        self, arguments: Sequence[str], folder: Path, variables: Mapping[str, str]
    ) -> RunningProcess:
        process = default_start_process(arguments, folder, variables)
        self.processes.append(process)
        self.folders.append(folder)
        return process


@pytest.fixture
def site(tmp_path: Path) -> Iterator[str]:
    folder = tmp_path / "site"
    folder.mkdir()
    (folder / "index.html").write_text(ORDER_PAGE, encoding="utf-8", newline="\n")
    (folder / "sent.html").write_text(SENT_PAGE, encoding="utf-8", newline="\n")
    handler = functools.partial(QuietHandler, directory=str(folder))
    server = LoopbackServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def machine(tmp_path: Path, starts: RecordedStarts) -> Environment:
    return Environment(
        stdin=io.StringIO(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        variables=dict(os.environ),
        home=Path.home(),
        working_directory=tmp_path,
        platform=sys.platform,
        interactive=False,
        now=utc_now,
        monotonic=time.monotonic,
        sleep=time.sleep,
        read_secret=lambda prompt: "",
        open_browser=lambda address: False,
        transport=NoNetwork(),
        system_language=None,
        start_process=starts,
    )


def installed(environment: Environment, name: str) -> BrowserProgram:
    if environment.variables.get(SKIP_VARIABLE) == "1":
        pytest.skip(f"{SKIP_VARIABLE} is 1")
    found = find_browsers(environment, names=(name,))
    if not found:
        pytest.skip(f"no {name} is installed on this machine")
    return found[0]


def waited(
    page: Page, environment: Environment, condition: Callable[[PageSnapshot], bool]
) -> PageSnapshot:
    snapshot = page.snapshot()
    for _ in range(ATTEMPTS - 1):
        if condition(snapshot):
            return snapshot
        environment.sleep(PAUSE_SECONDS)
        snapshot = page.snapshot()
    return snapshot


def target(snapshot: PageSnapshot, role: str, name: str, action: str | None = None) -> Element:
    found = resolve_target(snapshot, {"role": role, "name": name}, action=action)
    assert found is not None, f"{role}: {name} not in {snapshot.document()}"
    return found


@pytest.mark.parametrize("name", BROWSER_NAMES)
def test_a_real_browser_reads_the_page_and_acts_like_a_person(
    tmp_path: Path, site: str, name: str
) -> None:
    starts = RecordedStarts()
    environment = machine(tmp_path, starts)
    program = installed(environment, name)
    context = CommandContext(
        environment, Console(environment, language="en", color=False), language="en"
    )

    page = open_page(context, program, language="it-IT", direct=True)
    try:
        assert (page.browser, bool(page.version)) == (name, True)
        page.open(f"{site}/index.html")
        first = page.snapshot()
        roles = {(item.role, item.name) for item in first.elements}
        assert {
            ("heading", "Nuovo ordine"),
            ("text", "Compila il modulo e controlla il riepilogo."),
            ("textbox", "Nome cliente"),
            ("combobox", "Taglia"),
            ("checkbox", "Confezione regalo"),
            ("button", "Controlla"),
            ("button", "Invia"),
            ("link", "Aiuto"),
        } <= roles
        assert first.title == "Prova ordini"
        assert first.url == f"{site}/index.html"
        assert not matches_text(first.text, "Testo nascosto")
        size = target(first, "combobox", "Taglia", "SELECT")
        assert (size.value, size.options) == ("Piccola", ("Piccola", "Media", "Grande"))

        page.type(target(first, "textbox", "Nome cliente", "TYPE"), "Anna")
        page.select(size, "Grande")
        page.click(target(first, "checkbox", "Confezione regalo", "CLICK"))
        page.click(target(first, "button", "Controlla", "CLICK"))
        checked = waited(
            page, environment, lambda snapshot: matches_text(snapshot.text, "Anna: Grande")
        )

        assert matches_text(checked.text, "Ordine di Anna: Grande con regalo")
        assert target(checked, "status", "Ordine di Anna").name == (
            "Ordine di Anna: Grande con regalo"
        )
        assert target(checked, "textbox", "Nome cliente").value == "Anna"
        assert target(checked, "combobox", "Taglia").value == "Grande"
        assert target(checked, "checkbox", "Confezione regalo").state == "checked"

        page.type(target(checked, "textbox", "Nome cliente", "TYPE"), "Bruno")
        page.press("Enter")
        sent = waited(page, environment, lambda snapshot: "sent.html" in snapshot.url)

        assert sent.url.startswith(f"{site}/sent.html?name=Bruno&size=l&gift=on")
        assert sent.title == "Inviato"
        assert target(sent, "heading", "Ordine inviato").index == 0
        image = page.screenshot()
        assert image.startswith(PNG_SIGNATURE)
        assert len(image) > 1024
    finally:
        page.close()

    assert len(starts.processes) == 1
    assert all(process.poll() is not None for process in starts.processes)
    assert not any(folder.exists() for folder in starts.folders)
