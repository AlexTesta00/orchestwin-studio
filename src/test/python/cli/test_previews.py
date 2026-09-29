from __future__ import annotations

import dataclasses
import re
import webbrowser
from pathlib import Path

import pytest

from orchestwin.cli.api import design as design_api
from orchestwin.cli.flows import previews
from orchestwin.cli.flows.design_state import DesignState
from orchestwin.cli.http import UrlTransport
from orchestwin.cli.main import main

from .support.terminal import command_context, terminal
from .test_api_design import Session, design_session, draw, propose, without_drawing

ADDRESSES = re.compile(r'(?:href|src|action)\s*=\s*"([^"]*)"', re.IGNORECASE)


def ready(session: Session) -> None:
    propose(session)
    draw(session, "DES-001", "DES-002")


def unsafe_state() -> DesignState:
    package = {
        "alternatives": [
            {
                "id": "a1",
                "code": "DES-001",
                "title": '<script>alert("x")</script>',
                "summary": "Tom & Jerry <b>bold</b>",
                "visual_language": {"product_name": "Tip </title>", "choices": {}},
            },
            {"id": "a2", "code": "../DES 002", "title": "Plain", "summary": ""},
        ],
        "critiques": [
            {
                "design_alternative_id": "a1",
                "user_twin_reference": {"twin_id": "t1", "name": "<i>Anna</i>"},
                "verdict": "Nice & clear",
                "quote": "I'd use it <now>",
            }
        ],
        "recommended_alternative_id": "a1",
        "owner_selected_alternative_id": None,
        "prototype": None,
    }
    return DesignState(
        project_id="p",
        project_name="<Tip> & co",
        stage="DESIGN",
        version={"id": "v", "version_number": 1, "content_hash": "h", "package": package},
        capabilities=design_api.Capabilities(True, True, True, "model"),
        documents={"a1": {"html": "<!doctype html><title>x</title>"}},
    )


def test_the_file_of_an_alternative_is_the_document_of_the_api_byte_for_byte(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        run = session.ut("design", "open")
        client = session.client()
        documents = {
            code: design_api.mockup_document(client, session.project.id, session.alternative(code))
            for code in ("DES-001", "DES-002")
        }
        written = {code: (session.previews / f"{code}.html").read_bytes() for code in documents}

    assert run.status == 0, run.errors
    for code, document in documents.items():
        assert document is not None
        assert written[code] == str(document["html"]).encode("utf-8")
    assert run.opened == (session.uri("index.html"),)
    assert f"Previews written in {session.previews}." in run.output


def test_the_index_has_no_script_and_nothing_from_outside(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        session.ut("design", "open")
        index = (session.previews / "index.html").read_text(encoding="utf-8")
        names = sorted(item.name for item in session.previews.iterdir())

    assert index.startswith('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">')
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in index
    assert "<script" not in index.lower()
    assert "http:" not in index and "https:" not in index and "url(" not in index
    assert sorted(ADDRESSES.findall(index)) == ["DES-001.html", "DES-002.html"]
    assert set(ADDRESSES.findall(index)) <= set(names)
    assert "<title>Calcolo mancia · design previews</title>" in index
    assert "Recommended by the model" in index
    assert "<strong>Pizzeria owner</strong>: Clear at the table" in index
    assert "a:focus-visible{outline:3px solid" in index
    assert "minmax(min(100%,300px),1fr)" in index


def test_the_index_in_italian(tmp_path: Path) -> None:
    with design_session(tmp_path, language="it") as session:
        ready(session)
        run = session.ut("design", "open", language="it")
        index = (session.previews / "index.html").read_text(encoding="utf-8")

    assert run.status == 0, run.errors
    assert '<html lang="it">' in index
    assert "<title>Calcolo mancia · anteprime del design</title>" in index
    assert "Consigliata dal modello" in index
    assert "Apri il mockup di DES-001" in index


def test_every_text_of_the_project_is_escaped(tmp_path: Path) -> None:
    bundle = terminal(tmp_path, transport=UrlTransport())
    context = command_context(bundle.environment)
    state = unsafe_state()

    page = previews.index_html(context, state, {"a1": "DES-001.html"})

    assert "<script" not in page.lower()
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in page
    assert "Tom &amp; Jerry &lt;b&gt;bold&lt;/b&gt;" in page
    assert "Product: Tip &lt;/title&gt;" in page
    assert "<title>&lt;Tip&gt; &amp; co · design previews</title>" in page
    assert "<strong>&lt;i&gt;Anna&lt;/i&gt;</strong>: Nice &amp; clear" in page
    assert "“I&#x27;d use it &lt;now&gt;”" in page
    assert page.count("<li") == 3


def test_a_critique_without_verdict_lists_what_the_twin_wrote(tmp_path: Path) -> None:
    bundle = terminal(tmp_path, transport=UrlTransport())
    context = command_context(bundle.environment)
    state = unsafe_state()
    package = dict(state.package)
    package["critiques"] = [
        {
            "design_alternative_id": "a1",
            "user_twin_reference": {"twin_id": "t1", "name": "Anna"},
            "verdict": None,
            "quote": None,
            "concerns": ["Small <b>digits</b>.", "Too dark"],
            "questions": ["Can I split the bill?"],
        }
    ]
    version = {**dict(state.version or {}), "package": package}

    page = previews.index_html(context, dataclasses.replace(state, version=version), {})

    assert (
        '<li><strong>Anna</strong><ul class="points"><li>Concerns: Small &lt;b&gt;digits'
        "&lt;/b&gt;. Too dark</li><li>Questions: Can I split the bill?</li></ul></li>"
    ) in page
    assert "<b>" not in page


def test_unsafe_codes_give_safe_file_names(tmp_path: Path) -> None:
    project = type("Project", (), {"previews": tmp_path / "previews"})()
    bundle = terminal(tmp_path, transport=UrlTransport())
    context = command_context(bundle.environment)
    state = dataclasses.replace(
        unsafe_state(), documents={"a2": {"html": "<p>two</p>"}, "a1": {"html": "<p>one</p>"}}
    )

    index = previews.write_previews(context, project, state)

    assert sorted(item.name for item in index.parent.iterdir()) == [
        "DES-001.html",
        "DES-002.html",
        "index.html",
    ]
    assert (index.parent / "DES-002.html").read_bytes() == b"<p>two</p>"


def test_open_with_a_code_opens_that_mockup(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        run = session.ut("design", "open", "des-002")

    assert run.status == 0, run.errors
    assert run.opened == (session.uri("DES-002.html"),)


@pytest.mark.parametrize(
    ("budget", "ending"),
    [(60.0, "offers it in its menu, with its estimate.\n"), (None, "offers it in its menu.\n")],
)
def test_open_an_alternative_without_mockup(
    tmp_path: Path, budget: float | None, ending: str
) -> None:
    with design_session(tmp_path, budget_usd=budget) as session:
        propose(session)
        draw(session, "DES-001")
        run = session.ut("design", "open", "DES-002")

    assert run.status == 1
    assert run.output.endswith(f"DES-002 has no mockup to open yet. `ut design` {ending}")
    assert run.opened == ()


@pytest.mark.parametrize("failure", ["refused", "raised"])
def test_when_the_browser_cannot_be_opened_the_path_is_printed(
    tmp_path: Path, failure: str
) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        bundle = terminal(tmp_path, transport=UrlTransport())

        def browser(address: str) -> bool:
            if failure == "raised":
                raise webbrowser.Error("no browser")
            return False

        environment = dataclasses.replace(bundle.environment, open_browser=browser)
        status = main(["--lang", "en", "design", "open"], environment=environment)
        index = session.previews / "index.html"

    assert status == 0
    assert bundle.output.endswith(f"I cannot open the browser: open this file yourself: {index}\n")
    assert index.is_file()


def test_old_previews_are_removed_and_other_files_are_kept(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        session.previews.mkdir(parents=True)
        (session.previews / "DES-009.html").write_bytes(b"old")
        (session.previews / "notes.txt").write_bytes(b"mine")
        run = session.ut("design", "open")
        names = sorted(item.name for item in session.previews.iterdir())

    assert run.status == 0, run.errors
    assert names == ["DES-001.html", "DES-002.html", "index.html", "notes.txt"]


def test_without_a_model_there_is_nothing_to_open(tmp_path: Path) -> None:
    with design_session(tmp_path, hosted=False) as session:
        propose(session)
        run = session.ut("design", "open", "DES-002")

    assert run.status == 1
    assert "Design alternatives" in run.output and "What the twins think" in run.output
    assert run.output.endswith(
        "The alternatives and what the twins think are shown above; whoever runs the Studio "
        "can connect a model.\n"
    )
    assert "the mockup previews in the browser are not available" not in run.output
    assert not session.previews.exists()
    assert run.opened == ()


def test_a_model_that_draws_no_mockup_has_no_previews(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        propose(session)
        without_drawing(session)
        run = session.ut("design", "open")

    assert run.status == 1
    assert "Design alternatives" in run.output and "What the twins think" in run.output
    assert run.output.endswith(
        "With the model of this Studio the mockup previews in the browser are not available: "
        "the alternatives and what the twins think are shown here. Choice and approval work "
        "all the same.\n"
    )
    assert not session.previews.exists()
    assert run.opened == ()


def test_open_before_the_design_exists(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        run = session.ut("design", "open")

    assert run.status == 1
    assert run.output.endswith(
        "The design does not exist yet. Launch `ut design`: it tells you what preparing it "
        "costs and generates it only if you confirm.\n"
    )
