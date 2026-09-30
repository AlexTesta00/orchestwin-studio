from __future__ import annotations

import copy
import json
import re
from datetime import UTC, datetime
from pathlib import Path

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
