from __future__ import annotations

import copy
import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from orchestwin.cli.context import CommandContext
from orchestwin.cli.flows import test_report as report_flow

from .support.folders import TEST_RUN_ID, acceptance_run_document
from .support.terminal import Terminal, command_context, link_folder, terminal
from .support.transports import NoNetwork

LABELS = {"chrome": "Google Chrome", "firefox": "Mozilla Firefox"}
NAMES = report_flow.Names(
    criteria={
        "AC-001": "Un ospite aggiunto compare subito nella lista.",
        "AC-002": "Un nome vuoto non entra nella lista.",
    },
    requirements={"REQ-003": "Nome obbligatorio"},
    screens={"SCR-002": "Lista degli ospiti"},
)
MOMENT = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
ATTRIBUTE = re.compile(r'(?:src|href)="([^"]*)"')


def console(tmp_path: Path, language: str = "en") -> tuple[CommandContext, Terminal]:
    bundle = terminal(tmp_path, transport=NoNetwork(), variables={"COLUMNS": "400"})
    return command_context(bundle.environment, language=language), bundle


def run_without_review() -> dict[str, object]:
    run = acceptance_run_document()
    run["critiques"] = []
    run["reviewed_at"] = None
    return run


def test_the_report_is_a_page_without_scripts_and_with_relative_screenshots(
    tmp_path: Path,
) -> None:
    context, _ = console(tmp_path)
    run = acceptance_run_document()

    page = report_flow.report_html(
        context, run, project_name="Lista <ospiti>", names=NAMES, labels=LABELS
    )

    assert page.startswith('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">')
    assert "<script" not in page.lower()
    assert "<link" not in page.lower()
    assert "@import" not in page
    sources = ATTRIBUTE.findall(page)
    assert sources
    assert all(not re.match(r"^([a-z]+:|/)", source) for source in sources)
    assert "TP-001/chrome/01.png" in sources
    assert (
        '<img src="TP-002/firefox/02.png" width="480" '
        'alt="Screenshot after step 2 of TP-002 in Mozilla Firefox">' in page
    )
    assert "loading=" not in page
    assert "<title>Acceptance tests of &quot;Lista &lt;ospiti&gt;&quot;</title>" in page
    assert page.count('<section class="criterion">') == 3
    assert "Un ospite aggiunto compare subito nella lista." in page
    assert (
        "Run of 2026-09-29 10:01 UTC on the folder dist, in Google Chrome 151.0.7922.76, "
        "Mozilla Firefox 156.0.1." in page
    )
    assert "Criteria: 1 passed, 1 failed, 0 blocked, 1 not covered, 0 not run." in page
    assert (
        "No path can verify this criterion through the interface: Richiede una verifica "
        "manuale" in page
    )
    assert "TP-001 in Mozilla Firefox, 4.1 s" in page
    assert "Type &quot;Marco Rossi&quot; in textbox &quot;Nome ospite&quot;" in page
    assert (
        "Click button &quot;Conferma&quot;; expected: alert &quot;Il nome è obbligatorio&quot; "
        "is on the page" in page
    )
    assert "ELEMENT_VISIBLE: alert: Il nome è obbligatorio" in page
    assert "Addetti all&#x27;accoglienza: the results raise a concern" in page
    assert (
        "Medium importance: Con il nome vuoto non compare nessun messaggio. (about: criterion "
        "AC-002 &quot;Un nome vuoto non entra nella lista.&quot;, requirement REQ-003 "
        "&quot;Nome obbligatorio&quot;, screen SCR-002 &quot;Lista degli ospiti&quot;) What "
        "to do: Mostrare un avviso accanto al campo del nome." in page
    )
    assert "Organizzatori volontari: the results are fine" in page
    assert "First attempt" not in page
    assert "chip weak" not in page
    assert '<p class="weak">' not in page


def test_the_report_speaks_the_language_of_the_command_and_names_the_first_attempt(
    tmp_path: Path,
) -> None:
    context, _ = console(tmp_path, "it")
    run = run_without_review()
    first = copy.deepcopy(run["results"][2])
    first["path"]["heading"] = "Percorso <b>vecchio</b>"
    first["status"] = "BLOCKED"

    page = report_flow.report_html(
        context,
        run,
        project_name="Lista ospiti",
        names=report_flow.Names({}, {}, {}),
        labels=LABELS,
        first_attempt=[first],
    )

    assert '<html lang="it">' in page
    assert "<h1>Verifica dei criteri di «Lista ospiti»</h1>" in page
    assert "I twin non hanno ancora criticato questa esecuzione." in page
    assert "Primo tentativo dei percorsi bloccati" in page
    assert "Percorso &lt;b&gt;vecchio&lt;/b&gt;" in page
    assert "Scrivi «Marco Rossi» in textbox «Nome ospite»" in page
    assert '<span class="chip blocked">bloccato</span>' in page
    assert "<script" not in page.lower()


def test_the_run_the_latest_pointer_and_the_folders_are_written(tmp_path: Path) -> None:
    tests = tmp_path / "project" / ".orchestwin" / "tests"
    run = acceptance_run_document()

    first = report_flow.run_folder(tests, MOMENT)
    second = report_flow.run_folder(tests, MOMENT)
    written = report_flow.write_run(first, run, first_attempt=[{"status": "BLOCKED"}])
    plain = report_flow.write_run(second, run)
    latest = report_flow.write_latest(tests, first, run)

    assert (first.name, second.name) == ("20260929-090000", "20260929-090000-2")
    assert (tests / ".gitignore").read_bytes() == b"*\n"
    document = json.loads(written.read_bytes().decode("utf-8"))
    assert list(document)[-1] == "first_attempt"
    assert document["id"] == TEST_RUN_ID
    assert "first_attempt" not in json.loads(plain.read_bytes().decode("utf-8"))
    assert json.loads(latest.read_bytes().decode("utf-8")) == {
        "schema_version": 1,
        "run_id": TEST_RUN_ID,
        "folder": "20260929-090000",
        "report": "20260929-090000/report.html",
        "finished_at": "2026-09-29T10:01:12+00:00",
    }


def test_the_report_file_is_written_next_to_the_screenshots(tmp_path: Path) -> None:
    context, _ = console(tmp_path)
    folder = tmp_path / "run"
    folder.mkdir()

    path = report_flow.write_report(
        context,
        folder,
        acceptance_run_document(),
        project_name="Lista ospiti",
        names=NAMES,
        labels=LABELS,
    )

    assert path == folder / "report.html"
    assert path.read_bytes().decode("utf-8").endswith("</html>\n")


def test_the_table_and_the_summary_on_the_console(tmp_path: Path) -> None:
    context, bundle = console(tmp_path)
    run = acceptance_run_document()

    report_flow.show_table(context, run, LABELS)
    report_flow.show_summary(context, run)

    assert bundle.output.splitlines() == [
        "Criterion  Status       Paths   Browsers",
        "---------  -----------  ------  ------------------------------",
        "AC-001     passed       TP-001  Google Chrome, Mozilla Firefox",
        "AC-002     failed       TP-002  Google Chrome, Mozilla Firefox",
        "AC-003     not covered  -       -",
        "Criteria: 1 passed, 1 failed, 0 blocked, 1 not covered, 0 not run.",
    ]


def test_the_table_in_italian(tmp_path: Path) -> None:
    context, bundle = console(tmp_path, "it")

    report_flow.show_table(context, acceptance_run_document(), {})
    report_flow.show_summary(context, acceptance_run_document())

    assert bundle.output.splitlines() == [
        "Criterio  Esito        Percorsi  Browser",
        "--------  -----------  --------  ---------------",
        "AC-001    superato     TP-001    chrome, firefox",
        "AC-002    fallito      TP-002    chrome, firefox",
        "AC-003    non coperto  -         -",
        "Criteri: 1 superati, 1 falliti, 0 bloccati, 1 non coperti, 0 non eseguiti.",
    ]


def test_the_critiques_are_shown_with_their_findings(tmp_path: Path) -> None:
    context, bundle = console(tmp_path)
    critiques = acceptance_run_document()["critiques"]

    report_flow.show_review(context, critiques, NAMES, cost_microusd=300000)

    assert bundle.output.splitlines() == [
        "",
        "Critiques of the twins on this run",
        "==================================",
        "",
        "Addetti all'accoglienza: the results raise a concern",
        "  Un nome vuoto non mostra nessun avviso: all'ingresso perderei tempo.",
        "  - Medium importance: Con il nome vuoto non compare nessun messaggio. (about: "
        'criterion AC-002 "Un nome vuoto non entra nella lista.", requirement REQ-003 "Nome '
        'obbligatorio", screen SCR-002 "Lista degli ospiti") What to do: Mostrare un avviso '
        "accanto al campo del nome.",
        "",
        "Organizzatori volontari: the results are fine",
        "  La lista si aggiorna subito dopo l'aggiunta di un ospite.",
        "  No problem reported.",
        "",
        "Cost of the critiques: 0.30 USD.",
    ]


def test_a_review_without_critiques_says_so(tmp_path: Path) -> None:
    context, bundle = console(tmp_path, "it")

    report_flow.show_review(context, [], NAMES)

    assert bundle.output.splitlines()[-1] == "Nessun twin ha espresso un parere."


def test_a_long_statement_is_cut_in_a_finding(tmp_path: Path) -> None:
    context, _ = console(tmp_path)
    names = report_flow.Names({"AC-009": "parola " * 30}, {}, {})
    finding = {"severity": "HIGH", "text": "Grave.", "about": {"criterion": "AC-009"}}

    line = report_flow.finding_line(context, finding, names)

    opening = 'High importance: Grave. (about: criterion AC-009 "'
    assert line.startswith(f"{opening}parola parola")
    assert line.endswith('…")')
    assert len(line) <= len(opening) + report_flow.STATEMENT_LIMIT + len('")')


def test_the_words_of_steps_targets_and_expectations(tmp_path: Path) -> None:
    context, _ = console(tmp_path)
    field = {"role": "textbox", "name": "Nome"}

    assert report_flow.target_text({"role": "button", "name": "Conferma"}) == "button: Conferma"
    assert report_flow.target_text({"role": None, "name": " Totale  netto "}) == "Totale netto"
    assert report_flow.target_text(None) == "-"
    assert report_flow.expectation_text({"kind": "VALUE_IS", "target": field, "text": "Marco"}) == (
        "VALUE_IS: textbox: Nome = Marco"
    )
    assert report_flow.expectation_text(
        {"kind": "TEXT_ABSENT", "target": None, "text": "Errore"}
    ) == ("TEXT_ABSENT: Errore")
    assert report_flow.step_text(
        context, {"action": "PRESS", "target": None, "value": "Enter", "expect": None}
    ) == ("Press Enter")
    assert report_flow.step_text(
        context,
        {
            "action": "SELECT",
            "target": {"role": "combobox", "name": "Mancia"},
            "value": "15%",
            "expect": {"kind": "URL_CONTAINS", "target": None, "text": "/totale"},
        },
    ) == ('Choose "15%" in combobox "Mancia"; expected: the address contains "/totale"')
    assert report_flow.step_text(context, {"action": "WAIT"}) == "WAIT"
    assert report_flow.step_text(context, None) == "-"


WEAK = [
    {"path": "TP-001", "step": 3, "kind": "VISIBLE_AT_OPENING", "text": "Marco  Rossi"},
    {"path": "TP-002", "step": 2, "kind": "HIDDEN_AT_OPENING", "text": "Il nome <è> obbligatorio"},
    {"path": "TP-009", "step": 1, "kind": "NEVER_ON_PAGE", "text": "Errore"},
    {"path": "TP-002", "step": 1, "kind": "ABSENT_VISIBLE_AT_OPENING", "text": "Nessun ospite"},
    {"path": "TP-001", "step": 1, "kind": "SOMETHING_ELSE", "text": "Lista"},
]
WEAK_SENTENCES = {
    "en": (
        'TP-001, step 3: the page shows "Marco Rossi" as soon as it opens, so this expectation '
        "holds before anything is done.",
        'TP-002, step 2: "Il nome <è> obbligatorio" is already in the page when it opens, in a '
        "hidden part, so this expectation proves only that the part appeared.",
        'TP-009, step 1: the page as it opens does not hold "Errore" anywhere, not even in its '
        "hidden parts, so its absence proves little.",
        'TP-002, step 1: "Nessun ospite" is already visible when the page opens, so its absence '
        "cannot be verified: this expectation fails even when the application is right.",
    ),
    "it": (
        "TP-001, passo 3: la pagina mostra «Marco Rossi» già quando si apre, quindi questa attesa "
        "è vera prima di fare qualunque cosa.",
        "TP-002, passo 2: «Il nome <è> obbligatorio» è già nella pagina quando si apre, in una "
        "parte nascosta, quindi questa attesa prova soltanto che quella parte è comparsa.",
        "TP-009, passo 1: la pagina, quando si apre, non contiene «Errore» da nessuna parte, "
        "nemmeno nelle parti nascoste, quindi che manchi prova poco.",
        "TP-002, passo 1: «Nessun ospite» è già visibile quando la pagina si apre, quindi che "
        "manchi non si può verificare: questa attesa fallisce anche quando l'applicazione è "
        "giusta.",
    ),
}
WEAK_SUMMARIES = {
    "en": "Expectations that prove little: 3. Each one is marked on its step with the reason; a "
    "criterion passed only through them needs to be confirmed by hand.",
    "it": "Attese che provano poco: 3. Ognuna è segnata sul suo passo con il motivo; un criterio "
    "superato soltanto con queste attese va confermato a mano.",
}
MARKS = {"en": "proves little", "it": "prova poco"}


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_report_marks_the_expectations_that_prove_little(tmp_path: Path, language: str) -> None:
    context, _ = console(tmp_path, language)
    run = acceptance_run_document()
    first = copy.deepcopy(run["results"][2])
    first["path"]["code"] = "TP-009"
    first["status"] = "BLOCKED"

    page = report_flow.report_html(
        context,
        run,
        project_name="Lista ospiti",
        names=NAMES,
        labels=LABELS,
        first_attempt=[first],
        weak=WEAK,
    )

    visible, hidden, _, shown = (html.escape(item, quote=True) for item in WEAK_SENTENCES[language])
    summary = f'<p class="weak">{html.escape(WEAK_SUMMARIES[language], quote=True)}</p>'
    mark = f'<span class="chip weak">{MARKS[language]}</span>'
    assert page.index(summary) > page.index('<p class="summary">')
    assert page.index(summary) < page.index('<section class="criterion">')
    assert page.count(mark) == 6
    assert page.count(f'<p class="weak">{visible}</p>') == 2
    assert page.count(f'<p class="weak">{hidden}</p>') == 2
    assert page.count(f'<p class="weak">{shown}</p>') == 2
    assert page.index(shown) < page.index(hidden)
    assert "Errore" not in page
    assert f'{mark}<p class="weak">{visible}</p>' in page
    firefox = page.index("TP-001 in Mozilla Firefox")
    assert page.index(mark, firefox) < page.index("TP-002 in Google Chrome")
    assert "<script" not in page.lower()
    assert ".chip.weak{" in page


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_console_lists_the_expectations_that_prove_little(
    tmp_path: Path, language: str
) -> None:
    context, bundle = console(tmp_path, language)

    report_flow.show_weak(context, WEAK)
    report_flow.show_weak(context, [WEAK[-1]])
    report_flow.show_weak(context, [])

    count = (
        "Expectations that prove little: 4." if language == "en" else "Attese che provano poco: 4."
    )
    assert bundle.output.splitlines() == [
        count,
        *(f"- {line}" for line in WEAK_SENTENCES[language]),
    ]
    assert report_flow.weak_sentence(context, WEAK[-1]) == ""
    assert report_flow.weak_sentence(context, WEAK[0]) == WEAK_SENTENCES[language][0]


def test_moments_are_written_in_utc() -> None:
    assert report_flow.moment_text("2026-09-29T10:01:12+00:00") == "2026-09-29 10:01 UTC"
    assert report_flow.moment_text("2026-09-29T12:01:12+02:00") == "2026-09-29 10:01 UTC"
    assert report_flow.moment_text("2026-09-29T10:01:12") == "2026-09-29 10:01 UTC"
    assert report_flow.moment_text(None) == "-"
    assert report_flow.moment_text("yesterday") == "yesterday"


def test_the_statements_come_from_the_requirements_of_the_folder(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    folder = project.knowledge / "requirements"
    folder.mkdir(parents=True)
    document = {
        "specification": {
            "requirements": [{"code": "REQ-001", "title": "Aggiunta  ospite"}],
            "acceptance_criteria": [
                {"code": "AC-001", "statement": " Un ospite\ncompare. "},
                {"code": "AC-002", "statement": ""},
                {"statement": "senza codice"},
            ],
        }
    }
    (folder / "requirements.json").write_text(json.dumps(document), encoding="utf-8")

    names = report_flow.names(project)

    assert report_flow.statements(project) == {"AC-001": "Un ospite compare."}
    assert names.criteria == {"AC-001": "Un ospite compare."}
    assert names.requirements == {"REQ-001": "Aggiunta ospite"}
    assert names.screens == {}
    assert report_flow.statements(link_folder(tmp_path / "other")) == {}
