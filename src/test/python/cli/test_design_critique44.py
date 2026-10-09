from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from orchestwin.cli import costs
from orchestwin.cli.api import design as design_api
from orchestwin.cli.browser import BrowserProgram, PageSnapshot
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows import design_critique
from orchestwin.cli.flows.test_report import moment_text
from orchestwin.cli.http import UrlTransport
from orchestwin.cli.messages import text

from .support.browsers import FakeBrowserProgram, element, page_snapshot
from .support.fake_studio import RecordedRequest, _multipart_many
from .support.terminal import command_context, link_folder, run_ut, terminal
from .support.transports import NoNetwork
from .test_api_design import Session, design_session
from .test_consumers36 import seed
from .test_design_change import chosen
from .test_fake_studio_critique44 import jpeg, png

ADDRESS = "https://shop.example.test/checkout"
SOURCES = "/design/critiques/sources"
CRITIQUES = "/design/critiques"
ITERATIONS = "/design/iterations/jobs"
EVALUATIONS = "/design/evaluations"
LOCALES = {"en": "en-US", "it": "it-IT"}
ESTIMATES = {
    "en": "Estimate: 0.35-0.60 USD, about 3 min.",
    "it": "Stima: 0,35-0,60 USD, circa 3 min.",
}
REDRAW_ESTIMATES = {
    "en": "Estimate: 0.85-1.33 USD, about 7 min.",
    "it": "Stima: 0,85-1,33 USD, circa 7 min.",
}
SNAPSHOT = page_snapshot(
    element(0, "heading", "Checkout"),
    element(1, "button", "Pay now"),
    element(2, "link", "Basket"),
    url=ADDRESS,
    title="Checkout · Shop",
)
SHOTS = {1440: png(144, 90), 390: png(39, 84)}


def said(key: str, language: str = "en", **values: object) -> str:
    return text(key, language, **values)


def flat(output: str) -> str:
    return " ".join(output.split())


def parts(request: RecordedRequest) -> list[tuple[str, str | None, bytes]]:
    return _multipart_many(request.headers["content-type"], request.body)


def fields_of(request: RecordedRequest) -> dict[str, str]:
    return {
        name: content.decode("utf-8")
        for name, file_name, content in parts(request)
        if file_name is None
    }


def files_of(request: RecordedRequest) -> list[tuple[str | None, bytes]]:
    return [(file_name, content) for name, file_name, content in parts(request) if name == "shots"]


def uploads(session: Session) -> list[RecordedRequest]:
    return session.requests("POST", SOURCES)


def critiques_sent(session: Session) -> list[dict[str, object]]:
    return [json.loads(item.body) for item in session.requests("POST", CRITIQUES)]


def files_in(folder: Path) -> list[str]:
    return sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*"))


def image(tmp_path: Path, name: str = "Basket.png", content: bytes | None = None) -> Path:
    path = tmp_path / "designs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png(120, 80) if content is None else content)
    return path


class FakePage:
    browser = "chrome"
    version = "151.0.7922.76"

    def __init__(self, width: int, log: list[tuple[object, ...]]) -> None:
        self.width = width
        self.log = log

    def open(self, url: str) -> None:
        self.log.append(("open", self.width, url))

    def snapshot(self) -> PageSnapshot:
        return SNAPSHOT

    def screenshot(self) -> bytes:
        return SHOTS[self.width]

    def close(self) -> None:
        self.log.append(("close", self.width))


def browsers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, names: tuple[str, ...] = ("chrome", "firefox")
) -> list[tuple[object, ...]]:
    log: list[tuple[object, ...]] = []
    programs = tuple(FakeBrowserProgram.create(tmp_path / "programs", name) for name in names)

    def opened(
        context: object,
        program: BrowserProgram,
        *,
        width: int,
        height: int,
        language: str,
        direct: bool = False,
    ) -> FakePage:
        log.append(("start", program.name, width, height, language, direct))
        return FakePage(width, log)

    monkeypatch.setattr(design_critique, "find_browsers", lambda environment, **_: programs)
    monkeypatch.setattr(design_critique, "open_page", opened)
    return log


def labels(language: str, run: Mapping[str, object]) -> dict[str, str]:
    found = {}
    for number, shot in enumerate(run["source"]["shots"], start=1):
        width = shot["viewport_width"]
        found[shot["code"]] = (
            said("design.critique_image", language)
            if width is None
            else said("design.critique_screen", language, number=number, width=width)
        )
    return found


def opinion_lines(language: str, run: Mapping[str, object]) -> list[str]:
    places = labels(language, run)
    return [
        said(
            "design.critique_verdict",
            language,
            screen=places[item["anchor_key"]],
            verdict=said(f"design.critique_verdict_{item['verdict']}", language),
        )
        for item in run["verdicts"]
    ]


def done_line(language: str, run: Mapping[str, object]) -> str:
    return said(
        "design.critique_done",
        language,
        seconds=round(run["duration_seconds"]),
        cost=costs.usd_text(run["cost_microusd"] / 1_000_000, language),
    )


def check_opinions(language: str, output: str, run: Mapping[str, object]) -> None:
    names = {twin["twin_id"]: twin["name"] for twin in run["twins"]}
    lines = output.splitlines()
    for line in opinion_lines(language, run):
        assert line in lines
    for response in run["responses"]:
        summary = said(
            "design.critique_twin",
            language,
            name=names[response["twin_id"]],
            summary=response["summary"],
        )
        assert summary in lines
        for finding in response["findings"]:
            action = said(
                "design.critique_what_to_do", language, action=finding["recommended_action"]
            )
            assert flat(action) in flat(output)
            assert flat(finding["summary"]) in flat(output)
        for gap in response["evidence_gaps"]:
            assert flat(gap) in flat(output)


@pytest.mark.parametrize("language", ["en", "it"])
def test_an_image_is_uploaded_reviewed_by_the_twins_and_shown_with_time_and_cost(
    tmp_path: Path, language: str
) -> None:
    path = image(tmp_path)
    with design_session(tmp_path, language=language) as session:
        before = files_in(session.folder)
        run = session.ut(
            "design", "critique", "--image", str(path), answers=["y"], language=language
        )
        after = files_in(session.folder)
        [sent] = uploads(session)
        bodies = critiques_sent(session)
        [source] = session.project.critique_sources
        [critique] = session.project.critique_runs
        evaluations = session.count("POST", EVALUATIONS)

    assert run.status == 0, run.errors
    assert fields_of(sent) == {"kind": "IMAGE", "title": "Basket"}
    assert files_of(sent) == [("Basket.png", path.read_bytes())]
    assert source["shots"][0]["media_type"] == "image/png"
    assert bodies == [{"source_id": source["id"], "locale": LOCALES[language]}]
    uploading = said("design.critique_uploading", language, title="Basket")
    about = said("design.critique_about", language, title="Basket")
    confirm = said("costs.confirm", language)
    heading = said("design.critique_heading", language, title="Basket")
    output = run.output
    assert output.index(uploading) < output.index(about) < output.index(ESTIMATES[language])
    assert output.index(ESTIMATES[language]) < output.index(confirm) < output.index(heading)
    assert f"{heading}\n{'=' * len(heading)}\n{said('design.review_simulated', language)}\n" in (
        output
    )
    check_opinions(language, output, critique)
    assert said("design.critique_image", language) in output
    assert output.endswith(done_line(language, critique) + "\n")
    assert critique["cost_microusd"] > 0
    assert after == before
    assert evaluations == 0
    assert run.opened == ()


def test_a_jpeg_is_sent_as_a_jpeg_with_its_file_name(tmp_path: Path) -> None:
    path = image(tmp_path, "Home page.jpeg", jpeg(320, 200))
    with design_session(tmp_path) as session:
        run = session.ut("--yes", "design", "critique", "--image", str(path))
        [sent] = uploads(session)
        [source] = session.project.critique_sources

    assert run.status == 0, run.errors
    assert fields_of(sent)["title"] == "Home page"
    assert files_of(sent) == [("Home page.jpeg", path.read_bytes())]
    assert (source["shots"][0]["media_type"], source["shots"][0]["width"]) == ("image/jpeg", 320)
    assert said("costs.assumed") in run.output


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_website_is_photographed_at_two_widths_with_the_first_browser_and_reviewed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    log = browsers(monkeypatch, tmp_path)
    with design_session(tmp_path, language=language) as session:
        run = session.ut("design", "critique", "--url", ADDRESS, answers=["y"], language=language)
        [sent] = uploads(session)
        [source] = session.project.critique_sources
        [critique] = session.project.critique_runs

    assert run.status == 0, run.errors
    assert log == [
        ("start", "chrome", 1440, 900, language, False),
        ("open", 1440, ADDRESS),
        ("close", 1440),
        ("start", "chrome", 390, 844, language, False),
        ("open", 390, ADDRESS),
        ("close", 390),
    ]
    fields = fields_of(sent)
    assert (fields["kind"], fields["title"], fields["url"]) == (
        "WEB_PAGE",
        "Checkout · Shop",
        ADDRESS,
    )
    assert json.loads(fields["page"]) == SNAPSHOT.document()
    assert json.loads(fields["viewport_widths"]) == [1440, 390]
    assert files_of(sent) == [
        ("screenshot-1440.png", SHOTS[1440]),
        ("screenshot-390.png", SHOTS[390]),
    ]
    assert [shot["viewport_width"] for shot in source["shots"]] == [1440, 390]
    for width in (1440, 390):
        capturing = said(
            "design.critique_capturing", language, browser="Google Chrome", width=width
        )
        assert capturing in run.output
    check_opinions(language, run.output, critique)
    assert {item["verdict"] for item in critique["verdicts"]} == {"BLOCKS", "SLOWS", "WORKS"}
    assert run.output.endswith(done_line(language, critique) + "\n")


def test_a_website_on_this_computer_is_opened_without_a_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = browsers(monkeypatch, tmp_path, ("firefox",))
    local = "http://127.0.0.1:5173/"
    with design_session(tmp_path) as session:
        run = session.ut("--yes", "design", "critique", "--url", local)

    assert run.status == 0, run.errors
    assert [entry for entry in log if entry[0] == "start"] == [
        ("start", "firefox", 1440, 900, "en", True),
        ("start", "firefox", 390, 844, "en", True),
    ]
    assert said("design.critique_capturing", browser="Mozilla Firefox", width=390) in run.output


def test_without_a_browser_the_website_is_not_photographed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(design_critique, "find_browsers", lambda environment, **_: ())
    link_folder(tmp_path / "project")
    run = run_ut(
        ["--lang", "en", "design", "critique", "--url", ADDRESS], tmp_path, transport=NoNetwork()
    )

    assert run.status == 1
    assert run.errors == said("design.errors.BROWSER_NOT_FOUND") + "\n"
    assert run.output == ""


@pytest.mark.parametrize("language", ["en", "it"])
def test_wrong_files_and_addresses_are_refused_without_asking_the_studio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    monkeypatch.setattr(design_critique, "find_browsers", lambda environment, **_: ())
    link_folder(tmp_path / "project")
    gif = image(tmp_path, "animation.gif", b"GIF89a" + bytes(40))
    big = image(tmp_path, "huge.png", png(16, 16) + bytes(5 * 1024 * 1024))
    missing = tmp_path / "designs" / "missing.png"
    size = "5,0" if language == "it" else "5.0"
    cases = [
        (["--image", str(gif)], 2, "DESIGN_CRITIQUE_FILE_TYPE", {"path": str(gif)}),
        (
            ["--image", str(big)],
            1,
            "DESIGN_CRITIQUE_FILE_TOO_LARGE",
            {"name": "huge.png", "size": size},
        ),
        (["--image", str(missing)], 1, "DESIGN_CRITIQUE_FILE_MISSING", {"path": str(missing)}),
        (
            ["--url", "ftp://shop.example.test/"],
            2,
            "DESIGN_CRITIQUE_URL_INVALID",
            {"address": "ftp://shop.example.test/"},
        ),
        (
            ["--url", "shop.example.test"],
            2,
            "DESIGN_CRITIQUE_URL_INVALID",
            {"address": "shop.example.test"},
        ),
        (
            ["--url", "https://shop example"],
            2,
            "DESIGN_CRITIQUE_URL_INVALID",
            {"address": "https://shop example"},
        ),
    ]
    for arguments, status, code, values in cases:
        run = run_ut(
            ["--lang", language, "design", "critique", *arguments],
            tmp_path,
            transport=NoNetwork(),
        )
        assert run.status == status, arguments
        assert run.errors == said(f"design.errors.{code}", language, **values) + "\n", arguments
        assert run.output == "", arguments


def test_without_approved_twins_the_studio_refuses_before_any_spending(tmp_path: Path) -> None:
    path = image(tmp_path)
    with design_session(tmp_path, through="team") as session:
        run = session.ut("design", "critique", "--image", str(path), answers=["y"])
        started = critiques_sent(session)
        stored = list(session.project.critique_sources)

    assert run.status == 1
    assert run.errors == said("design.errors.DESIGN_CRITIQUE_TWINS_REQUIRED") + "\n"
    assert said("costs.confirm") not in run.output
    assert (started, stored) == ([], [])


def test_refused_spending_keeps_the_upload_and_asks_for_no_opinion(tmp_path: Path) -> None:
    path = image(tmp_path)
    with design_session(tmp_path) as session:
        run = session.ut("design", "critique", "--image", str(path), answers=["n"])
        started = critiques_sent(session)
        stored = len(session.project.critique_sources)

    assert run.status == 5
    assert run.errors == said("errors.SPENDING_REFUSED") + "\n"
    assert (started, stored) == ([], 1)


@pytest.mark.parametrize("language", ["en", "it"])
def test_on_the_subscription_the_critique_shows_the_time_and_spends_no_credit(
    tmp_path: Path, language: str
) -> None:
    path = image(tmp_path)
    with design_session(tmp_path, language=language, billing="SUBSCRIPTION") as session:
        run = session.ut("design", "critique", "--image", str(path), language=language)
        [critique] = session.project.critique_runs

    assert run.status == 0, run.errors
    assert said("costs.subscription", language, minutes="3 min") in run.output
    assert said("costs.confirm", language) not in run.output
    assert "USD" not in run.output
    assert run.output.endswith(
        said(
            "design.critique_done_subscription",
            language,
            seconds=round(critique["duration_seconds"]),
        )
        + "\n"
    )


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_list_numbers_the_critiques_from_the_latest_with_their_verdicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    browsers(monkeypatch, tmp_path)
    path = image(tmp_path)
    with design_session(tmp_path, language=language) as session:
        empty = session.ut("design", "critique", language=language)
        first = session.ut("--yes", "design", "critique", "--image", str(path))
        second = session.ut("--yes", "design", "critique", "--url", ADDRESS)
        listed = session.ut("design", "critique", language=language)
        runs = list(session.project.critique_runs)

    assert (empty.status, first.status, second.status, listed.status) == (0, 0, 0, 0)
    assert empty.output == said("design.critique_none", language) + "\n"
    heading = said("design.critique_list_heading", language)
    lines = [
        said(
            "design.critique_list_line",
            language,
            number=number,
            date=moment_text(run["completed_at"]),
            title=title,
            kind=said(f"design.critique_kind_{kind}", language),
            twins=2,
            works=works,
            slows=slows,
            blocks=blocks,
        )
        for number, run, title, kind, works, slows, blocks in (
            (1, runs[0], "Checkout · Shop", "WEB_PAGE", 2, 1, 1),
            (2, runs[1], "Basket", "IMAGE", 1, 0, 1),
        )
    ]
    assert listed.output == (
        f"{heading}\n{'=' * len(heading)}\n"
        + "".join(f"{line}\n" for line in lines)
        + said("design.critique_list_next", language)
        + "\n"
    )


def test_a_supplied_prototype_does_not_hide_the_critiques(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        seed(session)
        run = session.ut("design", "critique")

    assert run.status == 0, run.errors
    assert run.output == said("design.critique_none") + "\n"


def test_redraw_without_a_design_with_its_mockup_says_what_is_needed(tmp_path: Path) -> None:
    path = image(tmp_path)
    with design_session(tmp_path) as session:
        session.ut("--yes", "design", "critique", "--image", str(path))
        run = session.ut("design", "critique", "--redraw", answers=["y"])
        started = session.count("POST", ITERATIONS)

    assert run.status == 1
    assert run.output.endswith(said("design.critique_redraw_needs_design") + "\n")
    assert said("costs.confirm") not in run.output
    assert started == 0


def test_redraw_without_critiques_names_the_options(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        run = session.ut("design", "critique", "--redraw")
        started = session.count("POST", ITERATIONS)

    assert run.status == 1
    assert run.output == said("design.critique_none") + "\n"
    assert started == 0


@pytest.mark.parametrize("language", ["en", "it"])
def test_redraw_starts_an_iteration_with_the_critique_and_writes_the_previews(
    tmp_path: Path, language: str
) -> None:
    path = image(tmp_path)
    with design_session(tmp_path, language=language) as session:
        chosen(session)
        session.ut("--yes", "design", "critique", "--image", str(path))
        reviews = session.count("POST", EVALUATIONS)
        before = session.project.current("design")
        run = session.ut("design", "critique", "--redraw", answers=["y"], language=language)
        [sent] = [json.loads(item.body) for item in session.requests("POST", ITERATIONS)]
        listed = design_api.iterations(session.client(), session.project.id)
        [source] = session.project.critique_sources
        after = session.project.current("design")
        index = session.previews / "index.html"
        written = index.is_file()
        reviewed = session.count("POST", EVALUATIONS) - reviews

    request = design_critique.REDRAW_TEXT[language].format(title="Basket")
    assert run.status == 0, run.errors
    assert sent == {
        "design_version_id": before["id"],
        "design_content_hash": before["content_hash"],
        "request": request,
        "assertions": [],
        "critique_source_id": source["id"],
    }
    assert [(item["critique_source_id"], item["request"]) for item in listed] == [
        (source["id"], request)
    ]
    assert after["version_number"] == before["version_number"] + 1 == 3
    about = said("design.critique_redraw_about", language, title="Basket")
    assert run.output.index(about) < run.output.index(REDRAW_ESTIMATES[language])
    assert said("design.change_applied", language, version=3) in run.output
    assert flat(said("design.change_request", language, request=request)) in flat(run.output)
    assert said("design.previews_written", language, path=str(index.parent)) in run.output
    assert run.output.endswith(
        said("design.change_review_later", language, version=3)
        + "\n"
        + said("design.critique_redrawn", language, title="Basket", version=3)
        + "\n"
    )
    assert written
    assert run.opened == (session.uri("index.html"),)
    assert reviewed == 0


def test_redraw_with_a_number_uses_that_critique_and_refuses_a_missing_one(
    tmp_path: Path,
) -> None:
    older = image(tmp_path, "Basket.png")
    newer = image(tmp_path, "Cart.png", png(64, 48))
    with design_session(tmp_path) as session:
        chosen(session)
        session.ut("--yes", "design", "critique", "--image", str(older))
        session.ut("--yes", "design", "critique", "--image", str(newer))
        missing = session.ut("design", "critique", "--redraw", "3")
        run = session.ut("--yes", "design", "critique", "--redraw", "2")
        [sent] = [json.loads(item.body) for item in session.requests("POST", ITERATIONS)]
        sources = {item["title"]: item["id"] for item in session.project.critique_sources}

    assert missing.status == 1
    assert (
        missing.errors == said("design.errors.DESIGN_CRITIQUE_NOT_FOUND", number=3, count=2) + "\n"
    )
    assert run.status == 0, run.errors
    assert sent["critique_source_id"] == sources["Basket"]
    assert sent["request"] == design_critique.REDRAW_TEXT["en"].format(title="Basket")


@pytest.mark.parametrize(
    ("arguments", "key", "values"),
    [
        (["show", "--image", "a.png"], "design.usage_critique", {}),
        (["--url", ADDRESS], "design.usage_critique", {}),
        (["change", "Bigger", "--redraw"], "design.usage_critique", {}),
        (["critique", "--image", "a.png", "--url", ADDRESS], "design.usage_critique", {}),
        (["critique", "--redraw", "--image", "a.png"], "design.usage_critique", {}),
        (["critique", "extra"], "design.usage_value", {"action": "critique"}),
        (
            ["critique", "--redraw", "0"],
            "design.errors.DESIGN_CRITIQUE_NUMBER_INVALID",
            {"value": "0"},
        ),
        (
            ["critique", "--redraw", "two"],
            "design.errors.DESIGN_CRITIQUE_NUMBER_INVALID",
            {"value": "two"},
        ),
        (["critique", "--screen", "SCR-001"], "design.usage_target", {}),
    ],
    ids=[
        "show",
        "alone",
        "change",
        "image-and-url",
        "redraw-and-image",
        "value",
        "zero",
        "word",
        "screen",
    ],
)
def test_the_critique_options_go_only_with_critique_and_one_at_a_time(
    tmp_path: Path, arguments: list[str], key: str, values: dict[str, str]
) -> None:
    run = run_ut(["--lang", "en", "design", *arguments], tmp_path, transport=NoNetwork())

    assert run.status == 2
    assert run.errors == said(key, **values) + "\n"
    assert run.output == ""


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_help_names_the_critique_and_its_options(tmp_path: Path, language: str) -> None:
    run = run_ut(["--lang", language, "design", "--help"], tmp_path, transport=NoNetwork())
    flat_help = flat(run.output)

    assert run.status == 0
    for option in ("--image FILE", "--url ADDRESS", "--redraw [N]"):
        assert option in run.output
    assert "critique (" in flat_help
    for key in ("design.option_image", "design.option_url", "design.option_redraw"):
        assert flat(said(key, language)) in flat_help


def test_the_number_of_a_critique_and_the_page_sent_to_the_studio() -> None:
    assert [design_critique.critique_number(value) for value in ("latest", " 2 ", "10")] == [
        1,
        2,
        10,
    ]
    for value in ("0", "-1", "1.5", "two", "", None):
        with pytest.raises(CliError) as refused:
            design_critique.critique_number(value)
        assert (refused.value.code, refused.value.status) == ("DESIGN_CRITIQUE_NUMBER_INVALID", 2)
    crowded = page_snapshot(
        *(
            element(index, "combobox", f"Choice {index}", options=["x" * 200] * 20)
            for index in range(150)
        )
    )
    document = design_critique.page_document(crowded)
    size = len(json.dumps(document, ensure_ascii=False).encode("utf-8"))
    assert 0 < len(document["elements"]) < 150
    assert size <= design_critique.MAX_PAGE_BYTES
    assert document["elements"] == crowded.document()["elements"][: len(document["elements"])]
    assert design_critique.page_document(SNAPSHOT) == SNAPSHOT.document()


def test_the_capture_can_be_replaced_and_sees_every_width(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    taken: list[tuple[str, str, int, int]] = []
    programs = (
        FakeBrowserProgram.create(tmp_path / "programs", "firefox"),
        FakeBrowserProgram.create(tmp_path / "programs", "chrome"),
    )

    def capture(
        context: object, program: BrowserProgram, address: str, width: int, height: int
    ) -> tuple[PageSnapshot, bytes]:
        taken.append((program.name, address, width, height))
        return SNAPSHOT, SHOTS[width]

    monkeypatch.setattr(design_critique, "find_browsers", lambda environment, **_: programs)
    with design_session(tmp_path) as session:
        bundle = terminal(tmp_path, transport=UrlTransport())
        context = command_context(bundle.environment, assume_yes=True)
        status = design_critique.critique_url(
            context, context.client(), context.project(), f"  {ADDRESS} ", capture=capture
        )
        [sent] = uploads(session)
        [critique] = session.project.critique_runs

    assert status == 0
    assert taken == [("firefox", ADDRESS, 1440, 900), ("firefox", ADDRESS, 390, 844)]
    assert fields_of(sent)["url"] == ADDRESS
    assert files_of(sent) == [
        ("screenshot-1440.png", SHOTS[1440]),
        ("screenshot-390.png", SHOTS[390]),
    ]
    assert bundle.output.endswith(done_line("en", critique) + "\n")
