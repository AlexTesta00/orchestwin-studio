from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from orchestwin.cli.browser import BrowserError, Page, matches_text, open_page
from orchestwin.cli.browser.snapshot import (
    FIELD_SCRIPT,
    FOCUS_SCRIPT,
    READY_SCRIPT,
    RECT_SCRIPT,
    SCROLL_SCRIPT,
    SELECT_SCRIPT,
    SNAPSHOT_SCRIPT,
    VALUE_SCRIPT,
    expression,
)

from .support.browsers import (
    BROWSER_PATH,
    CDP,
    CHROME_VERSION,
    FAKE_PNG,
    SESSION,
    TARGET,
    EndpointRequest,
    FakeBrowserProgram,
    ScriptedBrowser,
    element,
    page_snapshot,
)
from .support.terminal import Terminal, command_context, terminal
from .support.transports import NoNetwork

ADDRESS = "http://127.0.0.1:8123/ordini"
BUTTON = element(3, "button", "Salva")
FIELD = element(5, "textbox", "Nome", value="")
SIZE = element(8, "combobox", "Taglia", value="Piccola", options=("Piccola", "Grande"))


@pytest.fixture
def temporary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "temp"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    return folder


@pytest.fixture
def browser(temporary: Path) -> Iterator[ScriptedBrowser]:
    with ScriptedBrowser(protocol=CDP) as scripted:
        yield scripted


def start(
    tmp_path: Path, browser: ScriptedBrowser, *, language: str = "it-IT"
) -> tuple[Page, Terminal, FakeBrowserProgram]:
    bundle = terminal(tmp_path, transport=NoNetwork(), start_process=browser)
    program = FakeBrowserProgram.create(tmp_path / "programs", "chrome")
    page = open_page(command_context(bundle.environment), program, language=language)
    return page, bundle, program


def calls(requests: list[EndpointRequest]) -> list[tuple[str, dict[str, object], str | None]]:
    return [(request.method, dict(request.params), request.session) for request in requests]


def after(browser: ScriptedBrowser, count: int) -> list[EndpointRequest]:
    return browser.endpoint.requests[count:]


def evaluation(source: str) -> tuple[str, dict[str, object], str]:
    return (
        "Runtime.evaluate",
        {"expression": source, "returnByValue": True, "awaitPromise": True},
        SESSION,
    )


def mouse(kind: str, x: int, y: int) -> tuple[str, dict[str, object], str]:
    params: dict[str, object] = {"type": kind, "x": x, "y": y}
    if kind != "mouseMoved":
        params.update(
            {"button": "left", "buttons": 1 if kind == "mousePressed" else 0, "clickCount": 1}
        )
    return ("Input.dispatchMouseEvent", params, SESSION)


def browser_error(caught: pytest.ExceptionInfo[BrowserError], code: str) -> str:
    assert caught.value.code == code
    assert caught.value.status == 1
    assert caught.value.program == "Google Chrome"
    return caught.value.detail


def test_chrome_starts_headless_with_a_fresh_profile_in_a_temporary_folder(
    tmp_path: Path, temporary: Path, browser: ScriptedBrowser
) -> None:
    page, bundle, program = start(tmp_path, browser)
    call = browser.calls[0]
    profile = call.profile
    page.close()

    assert call.arguments == (
        str(program.path),
        "--headless=new",
        "--remote-debugging-port=0",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--disable-translate",
        "--metrics-recording-only",
        "--no-service-autorun",
        "--password-store=basic",
        "--use-mock-keychain",
        "--disable-gpu",
        "--hide-scrollbars",
        "--window-size=1280,800",
        "--lang=it-IT",
        "about:blank",
    )
    assert call.folder == profile.parent
    assert profile.parent.parent == temporary
    assert profile.parent.name.startswith("orchestwin-browser-")
    assert not profile.is_relative_to(bundle.environment.working_directory)
    assert call.variables == bundle.environment.variables
    assert browser.endpoint.paths == [BROWSER_PATH]
    assert not profile.parent.exists()


def test_the_page_is_a_new_target_attached_with_its_own_session(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    page, _, _ = start(tmp_path, browser)
    page.close()

    assert calls(browser.endpoint.requests) == [
        ("Target.createTarget", {"url": "about:blank"}, None),
        ("Target.attachToTarget", {"targetId": TARGET, "flatten": True}, None),
        ("Page.enable", {}, SESSION),
        ("Runtime.enable", {}, SESSION),
        (
            "Emulation.setDeviceMetricsOverride",
            {"width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False},
            SESSION,
        ),
        ("Browser.getVersion", {}, None),
        ("Browser.close", {}, None),
    ]
    assert (page.browser, page.version) == ("chrome", CHROME_VERSION)


def test_the_size_the_language_and_the_direct_connection_are_passed_on(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    bundle = terminal(tmp_path, transport=NoNetwork(), start_process=browser)
    program = FakeBrowserProgram.create(tmp_path / "programs", "chrome")
    context = command_context(bundle.environment)

    page = open_page(context, program, width=390, height=844, language="en_GB", direct=True)
    page.close()

    arguments = browser.calls[0].arguments
    assert arguments[-4:] == (
        "--no-proxy-server",
        "--window-size=390,844",
        "--lang=en-GB",
        "about:blank",
    )
    metrics = browser.endpoint.called("Emulation.setDeviceMetricsOverride")[0]
    assert dict(metrics.params) == {
        "width": 390,
        "height": 844,
        "deviceScaleFactor": 1,
        "mobile": False,
    }


def test_opening_an_address_navigates_and_waits_for_the_load(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    page, bundle, _ = start(tmp_path, browser)
    count = len(browser.endpoint.requests)

    page.open(ADDRESS)
    page.close()

    assert calls(after(browser, count))[:2] == [
        ("Page.navigate", {"url": ADDRESS}, SESSION),
        evaluation(expression(READY_SCRIPT)),
    ]
    assert bundle.clock.slept == pytest.approx(0.25)


def test_a_page_that_fails_to_load_is_reported(tmp_path: Path, browser: ScriptedBrowser) -> None:
    browser.endpoint.answer(
        "Page.navigate",
        {"frameId": TARGET, "loaderId": "L", "errorText": "net::ERR_CONNECTION_REFUSED"},
    )
    browser.endpoint.answer("Page.navigate", error="Cannot navigate to invalid URL")
    page, _, _ = start(tmp_path, browser)

    with pytest.raises(BrowserError) as refused:
        page.open(ADDRESS)
    with pytest.raises(BrowserError) as invalid:
        page.open("nowhere")
    page.close()

    assert browser_error(refused, "PAGE_NOT_LOADED") == f"{ADDRESS}: net::ERR_CONNECTION_REFUSED"
    assert browser_error(invalid, "PAGE_NOT_LOADED") == (
        "Page.navigate: Cannot navigate to invalid URL"
    )


def test_a_page_that_keeps_loading_is_not_loaded(tmp_path: Path, browser: ScriptedBrowser) -> None:
    browser.endpoint.answer(
        "Page.navigate",
        {"frameId": TARGET, "loaderId": "L"},
        before=[("Page.frameStartedLoading", {"frameId": TARGET})],
        events=[("Page.loadEventFired", {"timestamp": 1})],
    )
    page, bundle, _ = start(tmp_path, browser)

    with pytest.raises(BrowserError) as caught:
        page.open(ADDRESS)
    page.close()

    assert browser_error(caught, "PAGE_NOT_LOADED") == "the page did not finish loading in time"
    assert bundle.clock.slept >= 30


def test_the_snapshot_is_read_by_one_script_and_checked(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    browser.endpoint.snapshot = page_snapshot(BUTTON, FIELD, SIZE, title="Ordini")
    page, _, _ = start(tmp_path, browser)
    count = len(browser.endpoint.requests)

    snapshot = page.snapshot()
    page.close()

    assert snapshot == browser.endpoint.snapshot
    assert calls(after(browser, count))[0] == evaluation(expression(SNAPSHOT_SCRIPT))


def test_a_snapshot_is_tried_again_when_the_page_script_fails(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    browser.endpoint.fail_script(SNAPSHOT_SCRIPT, "TypeError: document.body is null")
    page, bundle, _ = start(tmp_path, browser)

    snapshot = page.snapshot()
    page.close()

    assert snapshot == browser.endpoint.snapshot
    assert browser.endpoint.scripts() == ["snapshot", "snapshot"]
    assert bundle.clock.slept == pytest.approx(0.1)


def test_a_snapshot_that_keeps_failing_is_an_error(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    browser.endpoint.fail_script(
        SNAPSHOT_SCRIPT, "TypeError: boom\n    at <anonymous>", repeat=True
    )
    page, _, _ = start(tmp_path, browser)

    with pytest.raises(BrowserError) as caught:
        page.snapshot()
    page.close()

    assert browser_error(caught, "BROWSER_PROTOCOL_ERROR") == (
        "the page script failed: TypeError: boom"
    )
    assert browser.endpoint.scripts() == ["snapshot", "snapshot", "snapshot"]


def test_a_snapshot_that_breaks_the_contract_is_an_error(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    browser.endpoint.answer_script(SNAPSHOT_SCRIPT, {"url": 1, "elements": []})
    browser.endpoint.answer_script(SNAPSHOT_SCRIPT, "not an object")
    page, _, _ = start(tmp_path, browser)

    with pytest.raises(BrowserError) as first:
        page.snapshot()
    with pytest.raises(BrowserError) as second:
        page.snapshot()
    page.close()

    assert browser_error(first, "BROWSER_PROTOCOL_ERROR") == "page description: url is not text"
    assert browser_error(second, "BROWSER_PROTOCOL_ERROR") == "page description: not an object"


def test_a_snapshot_taken_while_a_new_page_loads_is_taken_again(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    first = page_snapshot(BUTTON, url="http://127.0.0.1:8123/old")
    browser.endpoint.answer_script(
        SNAPSHOT_SCRIPT,
        first.document(),
        before=[("Page.frameStartedLoading", {"frameId": TARGET})],
    )
    browser.endpoint.answer_script(
        READY_SCRIPT, "complete", before=[("Page.frameStoppedLoading", {"frameId": TARGET})]
    )
    browser.endpoint.snapshot = page_snapshot(FIELD, url="http://127.0.0.1:8123/new")
    page, _, _ = start(tmp_path, browser)

    snapshot = page.snapshot()
    page.close()

    assert snapshot.url == "http://127.0.0.1:8123/new"
    assert browser.endpoint.scripts() == ["snapshot", "ready", "snapshot"]


def test_a_click_is_a_real_mouse_click_at_the_centre(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    browser.endpoint.answer_script(
        RECT_SCRIPT, {"found": True, "visible": True, "x": 640.4, "y": 411.6}
    )
    page, bundle, _ = start(tmp_path, browser)
    count = len(browser.endpoint.requests)

    page.click(BUTTON)
    page.close()

    assert calls(after(browser, count))[:6] == [
        evaluation(expression(SCROLL_SCRIPT, 3)),
        evaluation(expression(RECT_SCRIPT, 3)),
        mouse("mouseMoved", 640, 412),
        mouse("mousePressed", 640, 412),
        mouse("mouseReleased", 640, 412),
        evaluation(expression(READY_SCRIPT)),
    ]
    assert bundle.clock.slept == pytest.approx(0.25)


@pytest.mark.parametrize(
    ("script", "answer", "detail"),
    [
        (SCROLL_SCRIPT, {"found": False}, "element 3 is no longer on the page"),
        (
            RECT_SCRIPT,
            {"found": True, "visible": False},
            "button: Salva: the element cannot be seen",
        ),
    ],
)
def test_an_element_that_cannot_be_clicked_is_an_action_that_failed(
    tmp_path: Path, browser: ScriptedBrowser, script: str, answer: object, detail: str
) -> None:
    browser.endpoint.answer_script(script, answer)
    page, _, _ = start(tmp_path, browser)

    with pytest.raises(BrowserError) as caught:
        page.click(BUTTON)
    page.close()

    assert browser_error(caught, "ACTION_FAILED") == detail
    assert browser.endpoint.called("Input.dispatchMouseEvent") == []


def test_a_click_that_the_browser_refuses_is_an_action_that_failed(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    browser.endpoint.answer("Input.dispatchMouseEvent", error="Invalid parameters")
    page, _, _ = start(tmp_path, browser)

    with pytest.raises(BrowserError) as caught:
        page.click(BUTTON)
    page.close()

    assert browser_error(caught, "ACTION_FAILED") == "Input.dispatchMouseEvent: Invalid parameters"


def test_typing_clicks_selects_the_content_and_inserts_the_text(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    page, _, _ = start(tmp_path, browser)
    count = len(browser.endpoint.requests)

    page.type(FIELD, "Anna Maria")
    page.close()

    assert calls(after(browser, count))[:9] == [
        evaluation(expression(FIELD_SCRIPT, 5)),
        evaluation(expression(SCROLL_SCRIPT, 5)),
        evaluation(expression(RECT_SCRIPT, 5)),
        mouse("mouseMoved", 100, 50),
        mouse("mousePressed", 100, 50),
        mouse("mouseReleased", 100, 50),
        evaluation(expression(FOCUS_SCRIPT, 5)),
        ("Input.insertText", {"text": "Anna Maria"}, SESSION),
        evaluation(expression(READY_SCRIPT)),
    ]


def test_typing_nothing_deletes_the_selected_content(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    page, _, _ = start(tmp_path, browser)

    page.type(FIELD, "")
    page.close()

    assert calls(browser.endpoint.called("Input.dispatchKeyEvent")) == [
        (
            "Input.dispatchKeyEvent",
            {"type": "rawKeyDown", "key": "Delete", "code": "Delete", "windowsVirtualKeyCode": 46},
            SESSION,
        ),
        (
            "Input.dispatchKeyEvent",
            {"type": "keyUp", "key": "Delete", "code": "Delete", "windowsVirtualKeyCode": 46},
            SESSION,
        ),
    ]
    assert browser.endpoint.called("Input.insertText") == []


def test_typing_into_a_list_chooses_the_option_and_into_a_date_sets_the_value(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    browser.endpoint.answer_script(FIELD_SCRIPT, {"found": True, "kind": "select"})
    browser.endpoint.answer_script(FIELD_SCRIPT, {"found": True, "kind": "value"})
    page, _, _ = start(tmp_path, browser)
    count = len(browser.endpoint.requests)

    page.type(SIZE, "Grande")
    page.type(element(9, "textbox", "Data"), "2026-09-29")
    page.close()

    evaluated = [request.expression for request in after(browser, count)][:6]
    assert evaluated == [
        expression(FIELD_SCRIPT, 8),
        expression(SELECT_SCRIPT, 8, "Grande"),
        expression(READY_SCRIPT),
        expression(FIELD_SCRIPT, 9),
        expression(VALUE_SCRIPT, 9, "2026-09-29"),
        expression(READY_SCRIPT),
    ]
    assert browser.endpoint.called("Input.dispatchMouseEvent") == []


def test_a_value_that_the_field_refuses_is_an_action_that_failed(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    browser.endpoint.answer_script(FIELD_SCRIPT, {"found": True, "kind": "value"})
    browser.endpoint.answer_script(VALUE_SCRIPT, {"found": True, "ok": False})
    page, _, _ = start(tmp_path, browser)

    with pytest.raises(BrowserError) as caught:
        page.type(element(9, "textbox", "Data"), "2026-02-30")
    page.close()

    assert browser_error(caught, "ACTION_FAILED") == (
        "textbox: Data: the field did not accept '2026-02-30'"
    )


def test_selecting_sets_the_option_through_the_page(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    browser.endpoint.answer_script(
        SELECT_SCRIPT, {"found": True, "ok": False, "detail": 'no option called "Enorme"'}
    )
    page, _, _ = start(tmp_path, browser)
    count = len(browser.endpoint.requests)

    with pytest.raises(BrowserError) as caught:
        page.select(SIZE, "Enorme")
    page.select(SIZE, "Grande")
    page.close()

    assert browser_error(caught, "ACTION_FAILED") == 'combobox: Taglia: no option called "Enorme"'
    assert [request.expression for request in after(browser, count)][:3] == [
        expression(SELECT_SCRIPT, 8, "Enorme"),
        expression(SELECT_SCRIPT, 8, "Grande"),
        expression(READY_SCRIPT),
    ]


@pytest.mark.parametrize(
    ("key", "down", "up"),
    [
        (
            "Enter",
            {
                "type": "keyDown",
                "key": "Enter",
                "code": "Enter",
                "windowsVirtualKeyCode": 13,
                "text": "\r",
                "unmodifiedText": "\r",
            },
            {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13},
        ),
        (
            "Space",
            {
                "type": "keyDown",
                "key": " ",
                "code": "Space",
                "windowsVirtualKeyCode": 32,
                "text": " ",
                "unmodifiedText": " ",
            },
            {"type": "keyUp", "key": " ", "code": "Space", "windowsVirtualKeyCode": 32},
        ),
        (
            "Tab",
            {"type": "rawKeyDown", "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9},
            {"type": "keyUp", "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9},
        ),
        (
            "ArrowDown",
            {
                "type": "rawKeyDown",
                "key": "ArrowDown",
                "code": "ArrowDown",
                "windowsVirtualKeyCode": 40,
            },
            {"type": "keyUp", "key": "ArrowDown", "code": "ArrowDown", "windowsVirtualKeyCode": 40},
        ),
    ],
)
def test_a_key_goes_to_the_focused_element_with_its_windows_code(
    tmp_path: Path,
    browser: ScriptedBrowser,
    key: str,
    down: dict[str, object],
    up: dict[str, object],
) -> None:
    page, _, _ = start(tmp_path, browser)
    count = len(browser.endpoint.requests)

    page.press(key)
    page.close()

    assert calls(after(browser, count))[:3] == [
        ("Input.dispatchKeyEvent", down, SESSION),
        ("Input.dispatchKeyEvent", up, SESSION),
        evaluation(expression(READY_SCRIPT)),
    ]


def test_a_key_outside_the_contract_is_refused_before_anything_is_sent(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    page, _, _ = start(tmp_path, browser)
    count = len(browser.endpoint.requests)

    with pytest.raises(BrowserError) as caught:
        page.press("F5")
    page.close()

    assert browser_error(caught, "ACTION_FAILED") == "unknown key: F5"
    assert [request.method for request in after(browser, count)] == ["Browser.close"]


def test_the_screenshot_is_the_png_of_the_viewport(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    browser.endpoint.answer("Page.captureScreenshot", {"data": "not base64 !"})
    page, _, _ = start(tmp_path, browser)

    with pytest.raises(BrowserError) as caught:
        page.screenshot()
    image = page.screenshot()
    page.close()

    assert image == FAKE_PNG
    assert browser_error(caught, "BROWSER_PROTOCOL_ERROR") == "the screenshot is not valid"
    assert calls(browser.endpoint.called("Page.captureScreenshot")) == [
        ("Page.captureScreenshot", {"format": "png"}, SESSION),
        ("Page.captureScreenshot", {"format": "png"}, SESSION),
    ]


def test_closing_closes_the_browser_the_connection_the_process_and_the_profile(
    tmp_path: Path, temporary: Path
) -> None:
    with ScriptedBrowser(protocol=CDP) as browser:
        page, _, _ = start(tmp_path, browser)
        page.close()
        page.close()
        with pytest.raises(BrowserError) as caught:
            page.snapshot()

    process = browser.processes[0]
    assert browser.endpoint.methods()[-1] == "Browser.close"
    assert browser.endpoint.methods().count("Browser.close") == 1
    assert browser.server.connections[0].closed_by_client
    assert (process.terminated, process.killed, process.waits) == (1, 0, [5.0, 10.0])
    assert process.returncode == 0
    assert list(temporary.iterdir()) == []
    assert browser_error(caught, "BROWSER_PROTOCOL_ERROR") == "the page is closed"


def test_a_process_that_does_not_end_is_killed(tmp_path: Path, temporary: Path) -> None:
    with ScriptedBrowser(protocol=CDP, graceful=False, stubborn=True) as browser:
        page, _, _ = start(tmp_path, browser)
        page.close()

    process = browser.processes[0]
    assert (process.terminated, process.killed) == (1, 1)
    assert process.waits == [5.0, 10.0, 10.0]
    assert list(temporary.iterdir()) == []


def test_the_launcher_waits_for_the_port_file(tmp_path: Path, temporary: Path) -> None:
    with ScriptedBrowser(protocol=CDP, polls_before_ready=5) as browser:
        page, bundle, _ = start(tmp_path, browser)
        waited = bundle.clock.slept
        page.close()

    assert browser.processes[0].polls == 5
    assert waited == pytest.approx(0.5)


def test_a_browser_that_ends_before_the_port_file_did_not_start(
    tmp_path: Path, temporary: Path
) -> None:
    with (
        ScriptedBrowser(protocol=CDP, exit_status=3) as browser,
        pytest.raises(BrowserError) as caught,
    ):
        start(tmp_path, browser)

    assert browser_error(caught, "BROWSER_NOT_STARTED") == "exited with 3"
    assert browser.server.connections == []
    assert browser.processes[0].terminated == 1
    assert list(temporary.iterdir()) == []


def test_a_browser_that_never_answers_is_stopped_after_thirty_seconds(
    tmp_path: Path, temporary: Path
) -> None:
    with (
        ScriptedBrowser(protocol=CDP, write_port_file=False) as browser,
        pytest.raises(BrowserError) as caught,
    ):
        start(tmp_path, browser)

    assert browser_error(caught, "BROWSER_NOT_STARTED") == "no answer within 30 seconds"
    assert browser.processes[0].terminated == 1
    assert list(temporary.iterdir()) == []


def test_a_program_that_cannot_start_leaves_nothing_behind(tmp_path: Path, temporary: Path) -> None:
    bundle = terminal(tmp_path, transport=NoNetwork())
    program = FakeBrowserProgram.create(tmp_path / "programs", "chrome")

    with pytest.raises(BrowserError) as caught:
        open_page(command_context(bundle.environment), program, language="it")

    assert browser_error(caught, "BROWSER_NOT_STARTED") == "no browser runs in the tests"
    assert list(temporary.iterdir()) == []


def test_a_program_that_disappeared_is_not_found(tmp_path: Path, temporary: Path) -> None:
    bundle = terminal(tmp_path, transport=NoNetwork())
    program = FakeBrowserProgram.create(tmp_path / "programs", "chrome")
    program.path.unlink()

    with pytest.raises(BrowserError) as caught:
        open_page(command_context(bundle.environment), program, language="it")

    assert browser_error(caught, "BROWSER_NOT_FOUND") == str(program.path)
    assert list(temporary.iterdir()) == []


def test_a_connection_that_breaks_during_the_start_cleans_up(
    tmp_path: Path, temporary: Path
) -> None:
    with ScriptedBrowser(protocol=CDP) as browser, pytest.raises(BrowserError) as caught:
        browser.endpoint.answer("Emulation.setDeviceMetricsOverride", close=True)
        start(tmp_path, browser)

    assert browser_error(caught, "BROWSER_PROTOCOL_ERROR") == "the browser closed the connection"
    assert browser.processes[0].terminated == 1
    assert list(temporary.iterdir()) == []


def test_a_dialog_is_accepted_so_that_the_page_goes_on(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    dialog = {
        "url": ADDRESS,
        "message": "Sicuro?",
        "type": "prompt",
        "hasBrowserHandler": True,
        "defaultPrompt": "Anna",
    }
    browser.endpoint.answer(
        "Input.dispatchMouseEvent",
        {},
        before=[("Page.javascriptDialogOpening", dialog)],
        when=lambda request: request.params.get("type") == "mousePressed",
    )
    page, _, _ = start(tmp_path, browser)

    page.click(BUTTON)
    page.close()

    methods = browser.endpoint.methods()
    pressed = methods.index("Page.handleJavaScriptDialog")
    assert methods[pressed - 1 : pressed + 2] == [
        "Input.dispatchMouseEvent",
        "Page.handleJavaScriptDialog",
        "Input.dispatchMouseEvent",
    ]
    assert calls(browser.endpoint.called("Page.handleJavaScriptDialog")) == [
        ("Page.handleJavaScriptDialog", {"accept": True, "promptText": "Anna"}, SESSION)
    ]


def test_after_an_action_the_page_waits_for_a_navigation_that_started(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    browser.endpoint.answer(
        "Input.dispatchMouseEvent",
        {},
        events=[
            ("Page.frameStartedLoading", {"frameId": "IFRAME-7"}),
            ("Page.frameStartedLoading", {"frameId": TARGET}),
        ],
        when=lambda request: request.params.get("type") == "mouseReleased",
    )
    browser.endpoint.answer_script(READY_SCRIPT, "loading")
    browser.endpoint.answer_script(
        READY_SCRIPT, "complete", before=[("Page.frameStoppedLoading", {"frameId": TARGET})]
    )
    page, bundle, _ = start(tmp_path, browser)

    page.click(BUTTON)
    page.close()

    assert browser.endpoint.scripts() == ["scroll", "rect", "ready", "ready"]
    assert bundle.clock.slept == pytest.approx(0.35)


def test_the_scripted_endpoint_can_play_a_small_page(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    before = page_snapshot(element(0, "button", "Controlla"), element(1, "textbox", "Nome"))
    after_click = page_snapshot(
        element(0, "button", "Controlla"),
        element(1, "textbox", "Nome"),
        element(2, "status", "Ordine controllato"),
    )
    browser.endpoint.snapshot = before

    def react(request: EndpointRequest) -> None:
        if request.params.get("type") == "mouseReleased":
            browser.endpoint.snapshot = after_click

    browser.endpoint.on_request = react
    page, _, _ = start(tmp_path, browser)
    page.open(ADDRESS)

    first = page.snapshot()
    page.click(first.elements[0])
    second = page.snapshot()
    page.close()

    assert first == before
    assert second.elements[2] == element(2, "status", "Ordine controllato")
    assert matches_text(second.text, "ordine controllato")


def test_after_an_action_a_navigation_that_never_ends_is_given_up(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    browser.endpoint.answer(
        "Input.dispatchMouseEvent",
        {},
        events=[("Page.frameStartedLoading", {"frameId": TARGET})],
        when=lambda request: request.params.get("type") == "mouseReleased",
    )
    page, bundle, _ = start(tmp_path, browser)

    page.click(BUTTON)
    page.close()

    assert bundle.clock.slept == pytest.approx(30.25, abs=0.2)
