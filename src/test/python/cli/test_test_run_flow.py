from __future__ import annotations

import html
import re
import tempfile
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from orchestwin.cli.browser import BrowserError, BrowserProgram, Element, PageSnapshot
from orchestwin.cli.context import CommandContext
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows import test_run as run_flow
from orchestwin.cli.flows import test_settings as settings_flow

from .support.browsers import (
    CDP,
    CHROME_VERSION,
    FAKE_PNG,
    FIREFOX_VERSION,
    EndpointRequest,
    FakeBrowserProgram,
    ScriptedBrowser,
    element,
    page_snapshot,
)
from .support.terminal import Terminal, command_context, link_folder, terminal
from .support.transports import NoNetwork

BASE = "http://127.0.0.1:8123/"
TAG = re.compile(r"<[^>]+>")
HIDDEN = "Result Total Each person pays"


class FakeSite:
    def __init__(
        self,
        *,
        title: str = "Tip calculator",
        text: str = "",
        elements: Sequence[Element] = (),
        reveal: Mapping[str, str] | None = None,
        fetch: bool = False,
        hidden_text: str = "",
        later: str = "",
    ) -> None:
        self.title = title
        self.text = text
        self.elements = tuple(elements)
        self.reveal = dict(reveal or {})
        self.fetch = fetch
        self.hidden_text = hidden_text
        self.later = later
        self.starts: list[tuple[str, str, bool]] = []
        self.opened: list[tuple[str, str]] = []
        self.actions: list[tuple[str, str, str]] = []
        self.pages: list[FakePage] = []
        self.opens: dict[str, int] = {}
        self.failures: dict[tuple[str, int], BrowserError] = {}
        self.shots: dict[str, int] = {}
        self.shot_failures: set[tuple[str, int]] = set()
        self.broken: set[str] = set()
        self.snapshots = 0

    def open_page(
        self,
        context: CommandContext,
        program: BrowserProgram,
        *,
        width: int = 1280,
        height: int = 800,
        language: str,
        direct: bool = False,
    ) -> FakePage:
        self.starts.append((program.name, language, direct))
        if program.name in self.broken:
            raise BrowserError("BROWSER_NOT_STARTED", program=program.label, detail="exited with 1")
        page = FakePage(self, program)
        self.pages.append(page)
        return page

    def fail_open(
        self, browser: str, number: int, detail: str = "net::ERR_CONNECTION_REFUSED"
    ) -> None:
        self.failures[(browser, number)] = BrowserError(
            "PAGE_NOT_LOADED", program=browser, detail=detail
        )

    def fail_screenshot(self, browser: str, number: int) -> None:
        self.shot_failures.add((browser, number))

    def programs(self, folder: Path, names: Sequence[str]) -> dict[str, BrowserProgram]:
        return {name: FakeBrowserProgram.create(folder, name) for name in names}


class FakePage:
    def __init__(self, site: FakeSite, program: BrowserProgram) -> None:
        self.site = site
        self.browser = program.name
        self.version = CHROME_VERSION if program.name == "chrome" else FIREFOX_VERSION
        self.url = "about:blank"
        self.body = ""
        self.values: dict[int, str] = {}
        self.shown: list[str] = []
        self.taken = 0
        self.closed = False

    def open(self, url: str) -> None:
        count = self.site.opens.get(self.browser, 0) + 1
        self.site.opens[self.browser] = count
        failure = self.site.failures.get((self.browser, count))
        if failure is not None:
            raise failure
        self.site.opened.append((self.browser, url))
        self.url = url
        if self.site.fetch:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url, timeout=10) as response:
                page = response.read().decode("utf-8")
            self.body = " ".join(html.unescape(TAG.sub(" ", page)).split())

    def snapshot(self) -> PageSnapshot:
        self.site.snapshots += 1
        self.taken += 1
        base = self.body if self.site.fetch else self.site.text
        later = self.site.later if self.taken > 1 else ""
        items = tuple(
            replace(item, value=self.values.get(item.index, item.value))
            for item in self.site.elements
        )
        return PageSnapshot(
            url=self.url,
            title=self.site.title,
            text=" ".join(part for part in (base, later, *self.shown) if part),
            elements=items,
            hidden_text=self.site.hidden_text,
        )

    def click(self, target: Element) -> None:
        self.site.actions.append((self.browser, "click", target.name))
        revealed = self.site.reveal.get(target.name)
        if revealed:
            self.shown.append(revealed)

    def type(self, target: Element, text: str) -> None:
        self.site.actions.append((self.browser, "type", f"{target.name}={text}"))
        self.values[target.index] = text

    def select(self, target: Element, option: str) -> None:
        self.site.actions.append((self.browser, "select", f"{target.name}={option}"))
        self.values[target.index] = option

    def press(self, key: str) -> None:
        self.site.actions.append((self.browser, "press", key))

    def screenshot(self) -> bytes:
        count = self.site.shots.get(self.browser, 0) + 1
        self.site.shots[self.browser] = count
        if (self.browser, count) in self.site.shot_failures:
            raise BrowserError(
                "BROWSER_PROTOCOL_ERROR", program=self.browser, detail="the screenshot is not valid"
            )
        return FAKE_PNG

    def close(self) -> None:
        self.closed = True


class ScriptPage:
    def __init__(
        self,
        snapshots: Sequence[PageSnapshot],
        program: BrowserProgram,
        *,
        screenshots: bool = True,
    ) -> None:
        self.browser = program.name
        self.version = CHROME_VERSION
        self._snapshots = list(snapshots)
        self._screenshots = screenshots
        self.taken = 0
        self.closed = False

    def open(self, url: str) -> None:
        return None

    def snapshot(self) -> PageSnapshot:
        self.taken += 1
        return self._snapshots[min(self.taken, len(self._snapshots)) - 1]

    def click(self, target: Element) -> None:
        raise BrowserError("ACTION_FAILED", program="Google Chrome", detail="element 0 is gone")

    def type(self, target: Element, text: str) -> None:
        return None

    def select(self, target: Element, option: str) -> None:
        return None

    def press(self, key: str) -> None:
        return None

    def screenshot(self) -> bytes:
        if self._screenshots:
            return FAKE_PNG
        raise BrowserError("BROWSER_PROTOCOL_ERROR", program="Google Chrome", detail="closed")

    def close(self) -> None:
        self.closed = True


def step(
    action: str,
    *,
    target: tuple[str | None, str] | None = None,
    value: str | None = None,
    expect: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "action": action,
        "target": None if target is None else {"role": target[0], "name": target[1]},
        "value": value,
        "expect": None if expect is None else dict(expect),
    }


def visible(text: str) -> dict[str, object]:
    return {"kind": "TEXT_VISIBLE", "target": None, "text": text}


def path(code: str, *steps: Mapping[str, object], criteria: Sequence[str] = ("AC-001",)) -> dict:
    return {
        "code": code,
        "heading": f"Heading of {code}.",
        "criteria": list(criteria),
        "steps": [dict(item) for item in steps],
    }


TIP = path(
    "TP-001",
    step("OPEN", value="/"),
    step("TYPE", target=("textbox", "Amount"), value="30"),
    step("SELECT", target=("combobox", "Tip"), value="15%"),
    step("CLICK", target=("button", "Calculate"), expect=visible("tip is 4.50")),
    step("PRESS", value="Enter"),
    step(
        "CHECK",
        expect={"kind": "VALUE_IS", "target": {"role": "textbox", "name": "Amount"}, "text": "30"},
    ),
)
ELEMENTS = (
    element(0, "heading", "Tip calculator"),
    element(1, "textbox", "Amount", value=""),
    element(2, "combobox", "Tip", value="10%", options=("10%", "15%")),
    element(3, "button", "Calculate"),
)


def bench(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    site: FakeSite,
    *,
    language: str = "en",
    static: bool = False,
) -> tuple[run_flow.PathRunner, run_flow.Browser, Terminal]:
    bundle = terminal(tmp_path, transport=NoNetwork(), variables={"COLUMNS": "400"})
    context = command_context(bundle.environment, language=language)
    folder = tmp_path / "run"
    folder.mkdir(exist_ok=True)
    monkeypatch.setattr(run_flow, "open_page", site.open_page)
    runner = run_flow.PathRunner(
        context, run_flow.Site(base=BASE, static=static, direct=True), folder, language="en-US"
    )
    program = FakeBrowserProgram.create(tmp_path / "programs", "chrome")
    return runner, run_flow.Browser(program=program, version=CHROME_VERSION), bundle


def statuses(outcome: run_flow.PathOutcome) -> list[str]:
    return [item.status for item in outcome.steps]


def test_every_step_is_done_with_a_screenshot_and_the_page_is_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = FakeSite(
        text="Tip calculator", elements=ELEMENTS, reveal={"Calculate": "The tip is 4.50 euros"}
    )
    runner, browser, bundle = bench(tmp_path, monkeypatch, site)

    outcome = runner.run(browser, TIP)

    assert (outcome.status, outcome.browser, outcome.seconds) == ("PASSED", "chrome", 0.0)
    assert statuses(outcome) == ["DONE"] * 6
    assert [item.screenshot for item in outcome.steps] == [
        f"TP-001/chrome/{index:02d}.png" for index in range(1, 7)
    ]
    assert (tmp_path / "run" / "TP-001" / "chrome" / "04.png").read_bytes() == FAKE_PNG
    assert {(item.url, item.title) for item in outcome.steps} == {(BASE, "Tip calculator")}
    assert outcome.page_text == "Tip calculator The tip is 4.50 euros"
    assert site.actions == [
        ("chrome", "type", "Amount=30"),
        ("chrome", "select", "Tip=15%"),
        ("chrome", "click", "Calculate"),
        ("chrome", "press", "Enter"),
    ]
    assert site.starts == [("chrome", "en-US", True)]
    assert [page.closed for page in site.pages] == [True]
    assert outcome.document()["steps"][0] == {
        "index": 1,
        "status": "DONE",
        "detail": None,
        "url": BASE,
        "title": "Tip calculator",
        "screenshot": "TP-001/chrome/01.png",
    }
    assert bundle.output.splitlines() == [
        "Path TP-001 in Google Chrome: Heading of TP-001...",
        "Path TP-001 in Google Chrome: Heading of TP-001: done in 0 s.",
    ]


def test_a_target_that_is_not_on_the_page_blocks_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = FakeSite(text="Tip calculator", elements=ELEMENTS, hidden_text=HIDDEN)
    runner, browser, bundle = bench(tmp_path, monkeypatch, site)
    blocked = path(
        "TP-002",
        step("OPEN", value="/"),
        step("CLICK", target=("button", "Pay now")),
        step("CHECK", expect=visible("Paid")),
    )

    outcome = runner.run(browser, blocked)

    assert outcome.status == "BLOCKED"
    assert statuses(outcome) == ["DONE", "BLOCKED", "SKIPPED"]
    assert outcome.steps[1].detail == "target not found: button: Pay now"
    assert outcome.steps[1].screenshot == "TP-002/chrome/02.png"
    assert outcome.steps[2] == run_flow.StepOutcome(3, "SKIPPED")
    assert outcome.blocked_step == 2
    assert outcome.blocked_snapshot is not None
    earlier = outcome.earlier()
    assert (earlier["code"], earlier["blocked_step"], earlier["detail"]) == (
        "TP-002",
        2,
        "target not found: button: Pay now",
    )
    assert earlier["snapshot"]["elements"][3] == ELEMENTS[3].document()
    assert earlier["snapshot"]["hidden_text"] == HIDDEN
    assert list(earlier["snapshot"]) == ["url", "title", "text", "hidden_text", "elements"]
    assert bundle.output.splitlines()[1:] == [
        "Path TP-002 in Google Chrome: Heading of TP-002: not completed after 0 s.",
        "TP-002 in Google Chrome blocked at step 2: target not found: button: Pay now",
    ]


def test_an_expectation_is_checked_four_times_before_it_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = FakeSite(text="Tip calculator", elements=ELEMENTS)
    runner, browser, bundle = bench(tmp_path, monkeypatch, site, language="it")
    failing = path("TP-003", step("OPEN", value="/"), step("CHECK", expect=visible("4,50 euro")))

    outcome = runner.run(browser, failing)

    assert outcome.status == "FAILED"
    assert statuses(outcome) == ["DONE", "FAILED"]
    assert outcome.steps[1].detail == "attesa non verificata: TEXT_VISIBLE: 4,50 euro"
    assert outcome.steps[1].screenshot == "TP-003/chrome/02.png"
    assert site.snapshots == 5
    assert outcome.seconds == pytest.approx(1.2)
    assert bundle.output.splitlines()[-1] == (
        "TP-003 in Google Chrome non superato al passo 2: attesa non verificata: TEXT_VISIBLE: "
        "4,50 euro"
    )


def test_an_expectation_met_on_a_later_snapshot_passes_after_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    program = FakeBrowserProgram.create(tmp_path / "programs", "chrome")
    loading = page_snapshot(element(0, "status", "Loading"), url=BASE, title="Tip")
    ready = page_snapshot(element(0, "status", "Total 34.50"), url=BASE, title="Tip")
    page = ScriptPage([loading, loading, loading, ready], program)
    runner, browser, bundle = bench(tmp_path, monkeypatch, FakeSite())
    monkeypatch.setattr(run_flow, "open_page", lambda *arguments, **options: page)

    outcome = runner.run(
        browser,
        path(
            "TP-004",
            step("OPEN", value="/"),
            step(
                "PRESS",
                value="Enter",
                expect={
                    "kind": "ELEMENT_VISIBLE",
                    "target": {"role": "status", "name": "Total"},
                    "text": None,
                },
            ),
        ),
    )

    assert statuses(outcome) == ["DONE", "DONE"]
    assert page.taken == 4
    assert bundle.clock.slept == pytest.approx(0.8)
    assert outcome.page_text == "Total 34.50"
    assert page.closed


def test_a_screenshot_that_fails_blocks_the_step_with_the_words_of_the_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    program = FakeBrowserProgram.create(tmp_path / "programs", "chrome")
    snapshot = page_snapshot(element(0, "button", "Calculate"), url=BASE, title="Tip")
    page = ScriptPage([snapshot], program, screenshots=False)
    runner, browser, _ = bench(tmp_path, monkeypatch, FakeSite())
    monkeypatch.setattr(run_flow, "open_page", lambda *arguments, **options: page)

    outcome = runner.run(
        browser,
        path("TP-005", step("OPEN", value="/"), step("CLICK", target=(None, "Calculate"))),
    )

    assert statuses(outcome) == ["BLOCKED", "SKIPPED"]
    assert outcome.steps[0] == run_flow.StepOutcome(
        1, "BLOCKED", "the browser stopped answering: closed"
    )
    assert outcome.blocked_step == 1


def test_a_click_refused_by_the_page_is_blocked_on_the_page_it_saw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    program = FakeBrowserProgram.create(tmp_path / "programs", "chrome")
    snapshot = page_snapshot(
        element(0, "button", "Calculate"), url=BASE, title="Tip", hidden_text=HIDDEN
    )
    page = ScriptPage([snapshot], program)
    runner, browser, _ = bench(tmp_path, monkeypatch, FakeSite())
    monkeypatch.setattr(run_flow, "open_page", lambda *arguments, **options: page)

    outcome = runner.run(browser, path("TP-006", step("CLICK", target=("button", "Calculate"))))

    assert outcome.status == "BLOCKED"
    assert outcome.steps == (
        run_flow.StepOutcome(
            1,
            "BLOCKED",
            "the browser could not do the step: element 0 is gone",
            BASE,
            "Tip",
            "TP-006/chrome/01.png",
        ),
    )
    assert outcome.blocked_snapshot == snapshot
    assert outcome.earlier()["snapshot"] == snapshot.document()
    assert outcome.earlier()["snapshot"]["hidden_text"] == HIDDEN


def test_a_browser_that_stops_on_a_step_leaves_the_page_of_the_step_before_to_the_replan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = FakeSite(text="Tip calculator", elements=ELEMENTS, hidden_text=HIDDEN)
    site.fail_screenshot("chrome", 2)
    runner, browser, _ = bench(tmp_path, monkeypatch, site)

    outcome = runner.run(
        browser, path("TP-008", step("OPEN", value="/"), step("CHECK", expect=visible("Tip")))
    )

    assert statuses(outcome) == ["DONE", "BLOCKED"]
    assert outcome.steps[1].detail == "the browser stopped answering: the screenshot is not valid"
    earlier = outcome.earlier()
    assert (earlier["blocked_step"], earlier["snapshot"]["url"]) == (2, BASE)
    assert earlier["snapshot"]["hidden_text"] == HIDDEN
    assert site.shots == {"chrome": 3}


def test_the_expectations_never_look_at_the_hidden_text() -> None:
    snapshot = page_snapshot(
        element(0, "button", "Pay"), text="Total 34.50", hidden_text="Payment refused"
    )
    absent = {"kind": "TEXT_ABSENT", "text": "Payment refused"}

    assert run_flow.expectation_met(snapshot, visible("Payment refused")) is False
    assert run_flow.expectation_met(snapshot, absent) is True
    assert run_flow.expectation_met(snapshot, visible("Total 34.50")) is True


def test_a_part_that_appears_after_the_page_opened_is_seen_by_a_later_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = FakeSite(text="Tip calculator", hidden_text=HIDDEN, later="Each person pays 11.50")
    runner, browser, _ = bench(tmp_path, monkeypatch, site)

    outcome = runner.run(
        browser,
        path("TP-009", step("OPEN", value="/"), step("CHECK", expect=visible("each person pays"))),
    )

    assert statuses(outcome) == ["DONE", "DONE"]
    assert outcome.page_text == "Tip calculator Each person pays 11.50"
    assert site.pages[0].taken == 2


def test_a_page_that_does_not_open_and_a_browser_that_does_not_start_block_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = FakeSite(text="Tip calculator")
    site.fail_open("chrome", 1)
    runner, browser, _ = bench(tmp_path, monkeypatch, site)
    opening = path("TP-007", step("OPEN", value="/orders"), step("CHECK", expect=visible("Tip")))

    unreachable = runner.run(browser, opening)
    site.broken.add("chrome")
    stopped = runner.run(browser, opening)

    assert statuses(unreachable) == ["BLOCKED", "SKIPPED"]
    assert unreachable.steps[0].detail == "the page did not open: net::ERR_CONNECTION_REFUSED"
    assert unreachable.steps[0].screenshot == "TP-007/chrome/01.png"
    assert statuses(stopped) == ["BLOCKED", "SKIPPED"]
    assert stopped.steps[0].detail == "the browser did not start: exited with 1"
    assert stopped.page_text is None
    assert [page.closed for page in site.pages] == [True]


@pytest.mark.parametrize(
    ("expect", "met"),
    [
        (visible("TOTALE  34,50"), True),
        (visible("Totale 99"), False),
        ({"kind": "TEXT_ABSENT", "text": "Errore"}, True),
        ({"kind": "TEXT_ABSENT", "text": "caffè"}, False),
        ({"kind": "ELEMENT_VISIBLE", "target": {"role": "button", "name": "Paga"}}, True),
        ({"kind": "ELEMENT_VISIBLE", "target": {"role": "link", "name": "Paga"}}, False),
        ({"kind": "ELEMENT_ABSENT", "target": {"role": "alert", "name": "Errore"}}, True),
        ({"kind": "ELEMENT_ABSENT", "target": {"role": None, "name": "Paga"}}, False),
        ({"kind": "ELEMENT_ABSENT"}, False),
        (
            {
                "kind": "VALUE_IS",
                "target": {"role": "textbox", "name": "Nome"},
                "text": "Anna  Rossi",
            },
            True,
        ),
        (
            {
                "kind": "VALUE_IS",
                "target": {"role": "textbox", "name": "Nome"},
                "text": "anna rossi",
            },
            False,
        ),
        ({"kind": "URL_CONTAINS", "text": "/Ordini"}, True),
        ({"kind": "URL_CONTAINS", "text": "/cassa"}, False),
        ({"kind": "TITLE_CONTAINS", "text": "mancia"}, True),
        ({"kind": "TITLE_CONTAINS", "text": ""}, False),
        ({"kind": "SOUND_PLAYS", "text": "x"}, False),
    ],
)
def test_the_kinds_of_expectation(expect: Mapping[str, object], met: bool) -> None:
    snapshot = page_snapshot(
        element(0, "button", "Paga"),
        element(1, "textbox", "Nome", value="Anna Rossi"),
        url="http://127.0.0.1:8123/ordini",
        title="Calcolo mancia",
        text="Totale 34,50 caffè",
    )

    assert run_flow.expectation_met(snapshot, expect) is met


@pytest.mark.parametrize(
    ("base", "value", "address"),
    [
        (BASE, "/", BASE),
        (BASE, "", BASE),
        (BASE, "/orders?tab=2", f"{BASE}orders?tab=2"),
        (BASE, "index.html", f"{BASE}index.html"),
        (BASE, "#/orders", f"{BASE}#/orders"),
        ("https://shop.example/app", "/cart", "https://shop.example/app/cart"),
        ("https://shop.example/app/", "/", "https://shop.example/app/"),
        (
            "https://shop.example/app/index.html",
            "about.html",
            "https://shop.example/app/about.html",
        ),
        ("https://shop.example/app/?lang=it", "/", "https://shop.example/app/?lang=it"),
        (BASE, "https://other.example/help", "https://other.example/help"),
        (BASE, "//other.example/help", f"{BASE}other.example/help"),
    ],
)
def test_an_open_step_is_a_path_of_the_application(base: str, value: str, address: str) -> None:
    site = run_flow.Site(base=base, static=False, direct=False)

    assert run_flow.open_address(site, value) == address


def test_a_static_folder_moves_the_loopback_addresses_to_its_own_port() -> None:
    site = run_flow.Site(base="http://127.0.0.1:61000/", static=True, direct=True)

    moved = run_flow.open_address(site, "http://127.0.0.1:53211/about.html?x=1#top")
    kept = run_flow.open_address(site, "https://example.org/")

    assert moved == "http://127.0.0.1:61000/about.html?x=1#top"
    assert kept == "https://example.org/"


@pytest.mark.parametrize("value", ["file:///C:/Users/secret.txt", "javascript:alert(1)", "C:/x"])
def test_an_open_step_never_leaves_the_web(value: str) -> None:
    site = run_flow.Site(base=BASE, static=False, direct=True)

    with pytest.raises(BrowserError) as caught:
        run_flow.open_address(site, value, program="Google Chrome")

    assert caught.value.code == "ACTION_FAILED"
    assert "not an address of the application" in caught.value.detail


def test_screenshots_have_safe_relative_names() -> None:
    assert run_flow.screenshot_path("TP-001", "chrome", 3) == "TP-001/chrome/03.png"
    assert run_flow.screenshot_path("../../x", "fire fox", 12) == "x/fire_fox/12.png"
    assert run_flow.screenshot_path("..", "..", 1) == "path/path/01.png"


def test_the_application_comes_from_the_request_then_from_the_settings(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    dist = project.root / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<h1>Tip</h1>", encoding="utf-8")
    outside = tmp_path / "elsewhere" / "site"
    outside.mkdir(parents=True)
    (outside / "index.html").write_text("<h1>Tip</h1>", encoding="utf-8")
    context = command_context(terminal(tmp_path, transport=NoNetwork()).environment)
    saved = settings_flow.TestSettings(application={"kind": "STATIC", "address": "web/dist"})

    inside = run_flow.chosen_application(
        context, project, {"kind": " static ", "address": "web/dist"}, None
    )
    remembered = run_flow.chosen_application(context, project, None, saved)
    far = run_flow.chosen_application(
        context, project, {"kind": "STATIC", "address": str(outside)}, None
    )
    local = run_flow.chosen_application(
        context, project, {"kind": "URL", "address": "http://localhost:5173/"}, None
    )
    remote = run_flow.chosen_application(
        context, project, {"kind": "URL", "address": "https://shop.example/"}, None
    )

    assert (inside.address, inside.saved, inside.direct) == (
        "web/dist",
        {"kind": "STATIC", "address": "web/dist"},
        True,
    )
    assert remembered == inside
    assert far.address == "site"
    assert far.saved == {"kind": "STATIC", "address": str(outside)}
    assert (local.document(), local.direct) == (
        {"kind": "URL", "address": "http://localhost:5173/"},
        True,
    )
    assert remote.direct is False


@pytest.mark.parametrize(
    ("application", "code", "status"),
    [
        (None, "TEST_APPLICATION_REQUIRED", 2),
        ({"kind": "FILE", "address": "dist"}, "TEST_APPLICATION_REQUIRED", 2),
        ({"kind": "URL", "address": "ftp://x.test/"}, "TEST_URL_INVALID", 2),
        ({"kind": "URL", "address": "http://"}, "TEST_URL_INVALID", 2),
        ({"kind": "URL", "address": "http://x.test/a b"}, "TEST_URL_INVALID", 2),
        ({"kind": "URL", "address": "http://[::1"}, "TEST_URL_INVALID", 2),
        ({"kind": "URL", "address": "http://x.test/" + "a" * 500}, "TEST_URL_INVALID", 2),
        ({"kind": "STATIC", "address": "missing"}, "TEST_STATIC_INVALID", 2),
        ({"kind": "STATIC", "address": "empty"}, "TEST_STATIC_INVALID", 2),
        ({"kind": "STATIC", "address": ""}, "TEST_STATIC_INVALID", 2),
    ],
)
def test_an_application_that_cannot_be_used_is_refused(
    tmp_path: Path, application: Mapping[str, object] | None, code: str, status: int
) -> None:
    project = link_folder(tmp_path / "project")
    (project.root / "empty").mkdir()
    context = command_context(terminal(tmp_path, transport=NoNetwork()).environment)

    with pytest.raises(CliError) as caught:
        run_flow.chosen_application(context, project, application, None)

    assert (caught.value.code, caught.value.status) == (code, status)


def test_the_root_of_the_project_is_the_address_dot(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    (project.root / "index.html").write_text("<h1>Tip</h1>", encoding="utf-8")
    context = command_context(terminal(tmp_path, transport=NoNetwork()).environment)

    found = run_flow.chosen_application(context, project, {"kind": "STATIC", "address": "."}, None)

    assert (found.address, found.saved["address"]) == (".", ".")


def test_the_choice_of_the_browsers() -> None:
    firefox = settings_flow.TestSettings(application=None, browser="firefox")

    assert run_flow.browser_choice((), None) == "all"
    assert run_flow.browser_choice((), firefox) == "firefox"
    assert run_flow.browser_choice((" Chrome ",), firefox) == "chrome"
    assert run_flow.browser_choice(("chrome", "all"), None) == "all"
    assert run_flow.browser_choice(("chrome", "firefox"), None) == "all"
    assert run_flow.browser_choice(("safari",), None) == "all"


def test_the_criteria_are_checked_against_the_folder_and_the_saved_plan(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")

    assert run_flow.chosen_criteria(project, (" ac-002 ", "AC-001", "ac-002"), None) == (
        "AC-002",
        "AC-001",
    )
    assert run_flow.chosen_criteria(project, (), None) == ()
    with pytest.raises(CliError) as caught:
        run_flow.chosen_criteria(project, ("AC-001", "XYZ", "12"), None)

    assert (caught.value.code, caught.value.status) == ("TEST_CRITERION_UNKNOWN", 2)
    assert caught.value.values["codes"] == "XYZ, 12"


def test_a_review_adds_its_critiques_and_its_cost_to_the_run() -> None:
    run = {"id": "run", "critiques": [], "reviewed_at": None, "cost_microusd": 200000}
    review = {
        "reviewed_at": "2026-09-29T09:10:00+00:00",
        "critiques": [{"twin_name": "Anna"}, "noise"],
        "cost_microusd": 300000,
    }

    assert run_flow.with_review(run, review) == {
        "id": "run",
        "critiques": [{"twin_name": "Anna"}],
        "reviewed_at": "2026-09-29T09:10:00+00:00",
        "cost_microusd": 500000,
    }


def test_the_request_and_the_outcome_are_not_collected_by_pytest() -> None:
    assert run_flow.TestRequest.__test__ is False
    assert run_flow.TestOutcome.__test__ is False
    assert run_flow.TestRequest() == run_flow.TestRequest(
        application=None,
        browsers=("all",),
        criteria=(),
        new_plan=False,
        review=True,
        max_usd=2.0,
        offer_tasks=False,
    )
    assert list(run_flow.TestRequest.__dataclass_fields__)[-1] == "offer_tasks"
    outcome = run_flow.TestOutcome(run={}, critiques=(), folder=Path(), report=Path())
    assert outcome.weak == ()
    assert list(run_flow.TestOutcome.__dataclass_fields__) == [
        "run",
        "critiques",
        "folder",
        "report",
        "weak",
    ]


@pytest.fixture
def scripted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ScriptedBrowser]:
    folder = tmp_path / "temp"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    with ScriptedBrowser(protocol=CDP) as browser:
        yield browser


def test_a_path_runs_in_a_real_page_driven_through_the_protocol(
    tmp_path: Path, scripted: ScriptedBrowser
) -> None:
    before = page_snapshot(element(0, "button", "Calcola"), url=BASE, title="Mancia")
    after = page_snapshot(
        element(0, "button", "Calcola"),
        element(1, "status", "Mancia: 4,50 euro"),
        url=BASE,
        title="Mancia",
    )
    scripted.endpoint.snapshot = before

    def react(request: EndpointRequest) -> None:
        if request.params.get("type") == "mouseReleased":
            scripted.endpoint.snapshot = after

    scripted.endpoint.on_request = react
    bundle = terminal(tmp_path, transport=NoNetwork(), start_process=scripted)
    context = command_context(bundle.environment, language="it")
    folder = tmp_path / "run"
    folder.mkdir()
    runner = run_flow.PathRunner(
        context, run_flow.Site(base=BASE, static=False, direct=True), folder, language="it-IT"
    )
    program = FakeBrowserProgram.create(tmp_path / "programs", "chrome")

    outcome = runner.run(
        run_flow.Browser(program=program, version=CHROME_VERSION),
        path(
            "TP-001",
            step("OPEN", value="/"),
            step("CLICK", target=("button", "Calcola"), expect=visible("4,50 euro")),
        ),
    )

    assert outcome.status == "PASSED"
    assert statuses(outcome) == ["DONE", "DONE"]
    assert (folder / "TP-001" / "chrome" / "02.png").read_bytes() == FAKE_PNG
    assert scripted.endpoint.called("Page.navigate")[0].params == {"url": BASE}
    assert "--no-proxy-server" in scripted.calls[0].arguments
    assert scripted.processes[0].terminated or scripted.processes[0].returncode is not None
