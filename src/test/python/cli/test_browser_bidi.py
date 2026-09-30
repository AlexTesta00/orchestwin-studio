from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from orchestwin.cli.browser import BrowserError, Page, open_page
from orchestwin.cli.browser.launch import FIREFOX_PREFERENCES, firefox_preferences
from orchestwin.cli.browser.snapshot import (
    FIELD_SCRIPT,
    FOCUS_SCRIPT,
    READY_SCRIPT,
    RECT_SCRIPT,
    SCROLL_SCRIPT,
    SELECT_SCRIPT,
    SNAPSHOT_SCRIPT,
    expression,
)

from .support.browsers import (
    BIDI,
    CONTEXT,
    FAKE_PNG,
    FIREFOX_VERSION,
    SESSION_PATH,
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
RELEASE = ("input.releaseActions", {"context": CONTEXT})


@pytest.fixture
def temporary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "temp"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    return folder


@pytest.fixture
def browser(temporary: Path) -> Iterator[ScriptedBrowser]:
    with ScriptedBrowser(protocol=BIDI) as scripted:
        yield scripted


def start(
    tmp_path: Path, browser: ScriptedBrowser, *, language: str = "it-IT"
) -> tuple[Page, Terminal, FakeBrowserProgram]:
    bundle = terminal(tmp_path, transport=NoNetwork(), start_process=browser)
    program = FakeBrowserProgram.create(tmp_path / "programs", "firefox")
    page = open_page(command_context(bundle.environment), program, language=language)
    return page, bundle, program


def calls(requests: list[EndpointRequest]) -> list[tuple[str, dict[str, object]]]:
    assert all(request.session is None for request in requests)
    return [(request.method, dict(request.params)) for request in requests]


def after(browser: ScriptedBrowser, count: int) -> list[EndpointRequest]:
    return browser.endpoint.requests[count:]


def evaluation(source: str) -> tuple[str, dict[str, object]]:
    return (
        "script.evaluate",
        {
            "expression": source,
            "target": {"context": CONTEXT},
            "awaitPromise": True,
            "resultOwnership": "none",
        },
    )


def keys(*values: str) -> tuple[str, dict[str, object]]:
    actions: list[dict[str, str]] = []
    for value in values:
        actions.extend(({"type": "keyDown", "value": value}, {"type": "keyUp", "value": value}))
    return (
        "input.performActions",
        {"context": CONTEXT, "actions": [{"type": "key", "id": "keyboard", "actions": actions}]},
    )


def pointer(x: int, y: int) -> tuple[str, dict[str, object]]:
    return (
        "input.performActions",
        {
            "context": CONTEXT,
            "actions": [
                {
                    "type": "pointer",
                    "id": "mouse",
                    "parameters": {"pointerType": "mouse"},
                    "actions": [
                        {"type": "pointerMove", "x": x, "y": y, "origin": "viewport"},
                        {"type": "pointerDown", "button": 0},
                        {"type": "pointerUp", "button": 0},
                    ],
                }
            ],
        },
    )


def browser_error(caught: pytest.ExceptionInfo[BrowserError], code: str) -> str:
    assert caught.value.code == code
    assert caught.value.status == 1
    assert caught.value.program == "Mozilla Firefox"
    return caught.value.detail


def test_firefox_starts_headless_with_a_prepared_profile(
    tmp_path: Path, temporary: Path, browser: ScriptedBrowser
) -> None:
    page, bundle, program = start(tmp_path, browser)
    call = browser.calls[0]
    profile = call.profile
    preferences = (profile / "user.js").read_text(encoding="utf-8")
    page.close()

    assert call.arguments == (
        str(program.path),
        "--headless",
        "--remote-debugging-port",
        "0",
        "--profile",
        str(profile),
        "-no-remote",
        "-new-instance",
        "--width",
        "1280",
        "--height",
        "800",
        "about:blank",
    )
    assert call.folder == profile.parent
    assert profile.parent.parent == temporary
    assert not profile.is_relative_to(bundle.environment.working_directory)
    assert call.variables == {
        **bundle.environment.variables,
        "MOZ_CRASHREPORTER_DISABLE": "1",
        "MOZ_CRASHREPORTER_NO_REPORT": "1",
    }
    assert preferences == firefox_preferences("it-IT")
    assert 'user_pref("remote.active-protocols", 1);\n' in preferences
    assert 'user_pref("browser.startup.page", 0);\n' in preferences
    assert 'user_pref("app.update.auto", false);\n' in preferences
    assert 'user_pref("intl.accept_languages", "it-IT, it");\n' in preferences
    assert browser.endpoint.paths == [SESSION_PATH]
    assert not profile.parent.exists()


def test_the_preferences_are_one_line_each_and_the_language_is_optional() -> None:
    lines = firefox_preferences("").splitlines()

    assert len(lines) == len(FIREFOX_PREFERENCES)
    assert lines[0] == 'user_pref("app.normandy.api_url", "");'
    assert all(line.startswith("user_pref(") and line.endswith(");") for line in lines)
    assert 'user_pref("intl.accept_languages", "en");' in firefox_preferences("en")
    assert 'user_pref("intl.accept_languages", "en-GB, en");' in firefox_preferences("en_GB")
    assert "network.proxy.type" not in firefox_preferences("en")


def test_a_direct_connection_turns_the_proxy_off(tmp_path: Path, browser: ScriptedBrowser) -> None:
    bundle = terminal(tmp_path, transport=NoNetwork(), start_process=browser)
    program = FakeBrowserProgram.create(tmp_path / "programs", "firefox")

    page = open_page(command_context(bundle.environment), program, language="it", direct=True)
    preferences = (browser.calls[0].profile / "user.js").read_text(encoding="utf-8")
    page.close()

    assert 'user_pref("network.proxy.type", 0);\n' in preferences
    assert "--no-proxy-server" not in browser.calls[0].arguments


def test_the_session_takes_the_first_page_sets_its_size_and_listens_to_it(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    page, _, _ = start(tmp_path, browser)
    page.close()

    assert calls(browser.endpoint.requests) == [
        (
            "session.new",
            {
                "capabilities": {
                    "alwaysMatch": {
                        "acceptInsecureCerts": False,
                        "unhandledPromptBehavior": {"default": "accept"},
                    }
                }
            },
        ),
        ("browsingContext.getTree", {"maxDepth": 0}),
        (
            "browsingContext.setViewport",
            {"context": CONTEXT, "viewport": {"width": 1280, "height": 800}},
        ),
        ("session.subscribe", {"events": ["browsingContext"]}),
        ("browser.close", {}),
    ]
    assert (page.browser, page.version) == ("firefox", FIREFOX_VERSION)


def test_a_session_without_a_page_is_an_error(tmp_path: Path, temporary: Path) -> None:
    with ScriptedBrowser(protocol=BIDI) as browser, pytest.raises(BrowserError) as caught:
        browser.endpoint.answer("browsingContext.getTree", {"contexts": []})
        start(tmp_path, browser)

    assert browser_error(caught, "BROWSER_PROTOCOL_ERROR") == "the browser has no page"
    assert browser.processes[0].terminated == 1
    assert list(temporary.iterdir()) == []


def test_opening_an_address_waits_for_the_complete_page(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    page, bundle, _ = start(tmp_path, browser)
    count = len(browser.endpoint.requests)

    page.open(ADDRESS)
    page.close()

    assert calls(after(browser, count))[:2] == [
        (
            "browsingContext.navigate",
            {"context": CONTEXT, "url": ADDRESS, "wait": "complete"},
        ),
        evaluation(expression(READY_SCRIPT)),
    ]
    assert bundle.clock.slept == pytest.approx(0.25)


def test_a_page_that_fails_to_load_is_reported(tmp_path: Path, browser: ScriptedBrowser) -> None:
    browser.endpoint.answer("browsingContext.navigate", error="Error: NS_ERROR_CONNECTION_REFUSED")
    page, _, _ = start(tmp_path, browser)

    with pytest.raises(BrowserError) as caught:
        page.open(ADDRESS)
    page.close()

    assert browser_error(caught, "PAGE_NOT_LOADED") == (
        "browsingContext.navigate: unknown error: Error: NS_ERROR_CONNECTION_REFUSED"
    )


def test_the_snapshot_is_evaluated_in_the_page_as_text(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    browser.endpoint.snapshot = page_snapshot(BUTTON, FIELD, SIZE, title="Ordini")
    page, _, _ = start(tmp_path, browser)
    count = len(browser.endpoint.requests)

    snapshot = page.snapshot()
    page.close()

    assert snapshot == browser.endpoint.snapshot
    assert calls(after(browser, count))[0] == evaluation(expression(SNAPSHOT_SCRIPT))


def test_a_script_that_throws_is_an_error_with_its_text(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    browser.endpoint.fail_script(SCROLL_SCRIPT, "ReferenceError: find is not defined")
    browser.endpoint.answer(
        "script.evaluate",
        {"type": "success", "result": {"type": "undefined"}, "realm": "realm-1"},
        script=SNAPSHOT_SCRIPT,
        repeat=True,
    )
    page, _, _ = start(tmp_path, browser)

    with pytest.raises(BrowserError) as thrown:
        page.click(BUTTON)
    with pytest.raises(BrowserError) as empty:
        page.snapshot()
    page.close()

    assert browser_error(thrown, "ACTION_FAILED") == (
        "the page script failed: ReferenceError: find is not defined"
    )
    assert browser_error(empty, "BROWSER_PROTOCOL_ERROR") == "page description: not an object"


def test_a_click_is_a_pointer_action_at_the_centre(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    browser.endpoint.answer_script(RECT_SCRIPT, {"found": True, "visible": True, "x": 20.5, "y": 7})
    page, _, _ = start(tmp_path, browser)
    count = len(browser.endpoint.requests)

    page.click(BUTTON)
    page.close()

    assert calls(after(browser, count))[:5] == [
        evaluation(expression(SCROLL_SCRIPT, 3)),
        evaluation(expression(RECT_SCRIPT, 3)),
        pointer(20, 7),
        RELEASE,
        evaluation(expression(READY_SCRIPT)),
    ]


def test_typing_presses_one_key_per_character(tmp_path: Path, browser: ScriptedBrowser) -> None:
    page, _, _ = start(tmp_path, browser)
    count = len(browser.endpoint.requests)

    page.type(FIELD, "Zoë 2")
    page.close()

    assert calls(after(browser, count))[:9] == [
        evaluation(expression(FIELD_SCRIPT, 5)),
        evaluation(expression(SCROLL_SCRIPT, 5)),
        evaluation(expression(RECT_SCRIPT, 5)),
        pointer(100, 50),
        RELEASE,
        evaluation(expression(FOCUS_SCRIPT, 5)),
        keys("Z", "o", "ë", " ", "2"),
        RELEASE,
        evaluation(expression(READY_SCRIPT)),
    ]


def test_typing_nothing_deletes_the_selected_content(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    page, _, _ = start(tmp_path, browser)

    page.type(FIELD, "")
    page.close()

    assert calls(browser.endpoint.called("input.performActions"))[-1] == keys(chr(0xE017))


def test_selecting_goes_through_the_page(tmp_path: Path, browser: ScriptedBrowser) -> None:
    page, _, _ = start(tmp_path, browser)
    count = len(browser.endpoint.requests)

    page.select(SIZE, "Grande")
    page.close()

    assert calls(after(browser, count))[:2] == [
        evaluation(expression(SELECT_SCRIPT, 8, "Grande")),
        evaluation(expression(READY_SCRIPT)),
    ]


@pytest.mark.parametrize(
    ("key", "value"),
    [("Enter", 0xE007), ("Escape", 0xE00C), ("Tab", 0xE004), ("Space", 0xE00D), ("End", 0xE010)],
)
def test_a_key_is_the_webdriver_value_of_the_key(
    tmp_path: Path, browser: ScriptedBrowser, key: str, value: int
) -> None:
    page, _, _ = start(tmp_path, browser)
    count = len(browser.endpoint.requests)

    page.press(key)
    page.close()

    assert calls(after(browser, count))[:3] == [
        keys(chr(value)),
        RELEASE,
        evaluation(expression(READY_SCRIPT)),
    ]


def test_an_action_that_the_browser_refuses_is_an_action_that_failed(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    browser.endpoint.answer("input.performActions", error="Move target (5, 5) is out of bounds")
    page, _, _ = start(tmp_path, browser)

    with pytest.raises(BrowserError) as caught:
        page.press("Enter")
    page.close()

    assert browser_error(caught, "ACTION_FAILED") == (
        "input.performActions: unknown error: Move target (5, 5) is out of bounds"
    )


def test_the_screenshot_is_the_png_of_the_viewport(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    page, _, _ = start(tmp_path, browser)

    image = page.screenshot()
    page.close()

    assert image == FAKE_PNG
    assert calls(browser.endpoint.called("browsingContext.captureScreenshot")) == [
        ("browsingContext.captureScreenshot", {"context": CONTEXT})
    ]


def test_closing_ends_the_browser_the_process_and_the_profile(
    tmp_path: Path, temporary: Path
) -> None:
    with ScriptedBrowser(protocol=BIDI) as browser:
        page, _, _ = start(tmp_path, browser)
        page.close()
        page.close()

    process = browser.processes[0]
    assert browser.endpoint.methods().count("browser.close") == 1
    assert browser.server.connections[0].closed_by_client
    assert (process.terminated, process.waits, process.returncode) == (1, [5.0, 10.0], 0)
    assert list(temporary.iterdir()) == []


def test_the_launcher_waits_for_the_file_with_the_port(tmp_path: Path, temporary: Path) -> None:
    with ScriptedBrowser(protocol=BIDI, polls_before_ready=3) as browser:
        page, bundle, _ = start(tmp_path, browser)
        waited = bundle.clock.slept
        port_file = json.loads(
            (browser.calls[0].profile / "WebDriverBiDiServer.json").read_text(encoding="utf-8")
        )
        page.close()

    assert waited == pytest.approx(0.3)
    assert port_file == {"ws_host": "127.0.0.1", "ws_port": browser.server.port}


def test_a_firefox_that_ends_at_once_did_not_start(tmp_path: Path, temporary: Path) -> None:
    with (
        ScriptedBrowser(protocol=BIDI, exit_status=0) as browser,
        pytest.raises(BrowserError) as caught,
    ):
        start(tmp_path, browser)

    assert browser_error(caught, "BROWSER_NOT_STARTED") == "exited with 0"
    assert list(temporary.iterdir()) == []


def test_a_prompt_left_open_is_accepted_and_a_handled_one_is_left_alone(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    opened = {"context": CONTEXT, "type": "confirm", "message": "Sicuro?"}
    browser.endpoint.answer(
        "input.performActions",
        {},
        before=[
            ("browsingContext.userPromptOpened", {**opened, "handler": "ignore"}),
            ("browsingContext.userPromptOpened", {**opened, "handler": "accept"}),
            ("browsingContext.userPromptOpened", {**opened, "context": "OTHER"}),
        ],
    )
    page, _, _ = start(tmp_path, browser)

    page.click(BUTTON)
    page.close()

    assert calls(browser.endpoint.called("browsingContext.handleUserPrompt")) == [
        ("browsingContext.handleUserPrompt", {"context": CONTEXT, "accept": True})
    ]


def test_after_an_action_the_page_waits_for_the_navigation_of_its_own_context(
    tmp_path: Path, browser: ScriptedBrowser
) -> None:
    started = {"navigation": "navigation-2", "url": ADDRESS, "timestamp": 3}
    browser.endpoint.answer(
        "input.performActions",
        {},
        events=[
            ("browsingContext.navigationStarted", {**started, "context": "FRAME-2"}),
            ("browsingContext.navigationStarted", {**started, "context": CONTEXT}),
        ],
    )
    browser.endpoint.answer_script(READY_SCRIPT, "complete")
    browser.endpoint.answer_script(
        READY_SCRIPT,
        "interactive",
        before=[("browsingContext.fragmentNavigated", {**started, "context": CONTEXT})],
    )
    page, bundle, _ = start(tmp_path, browser)

    page.click(BUTTON)
    page.close()

    assert browser.endpoint.scripts() == ["scroll", "rect", "ready", "ready", "ready"]
    assert bundle.clock.slept == pytest.approx(0.45)
