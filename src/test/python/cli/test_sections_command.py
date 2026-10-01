from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from orchestwin.cli import messages
from orchestwin.cli.api import sections as sections_api
from orchestwin.cli.commands import COMMANDS
from orchestwin.cli.commands import sections as sections_command
from orchestwin.cli.http import UrlTransport

from .support.fake_studio import FakeProject, FakeStudio
from .support.folders import valid_archive
from .support.terminal import (
    PROJECT_ID,
    TEST_PASSWORD,
    Run,
    command_context,
    environment,
    link_folder,
    run_ut,
    store_session,
)
from .support.transports import API, NoNetwork, ScriptedTransport
from .test_status_command import (
    ALL_FINE,
    DESIGN_WAITING,
    PERSPECTIVE_CHANGED,
    gate,
    section,
    sections_document,
    version,
)

BASE = f"{API}/projects/{PROJECT_ID}"
SECTIONS = f"{BASE}/sections"
ALIGNMENT = f"{SECTIONS}/alignment"
PACKAGES = f"{BASE}/knowledge-packages"
LANGUAGES = ("en", "it")
BEHIND = {
    "en": "User Twin, Definition, Design & Evaluation to update: something upstream changed. "
    "The content you approved stays the same, it is only re-anchored to the new versions.",
    "it": "User Twin, Definizione, Design e valutazione da aggiornare: a monte qualcosa è "
    "cambiato. I contenuti che hai approvato restano gli stessi, vengono solo riagganciati "
    "alle versioni nuove.",
}
GESTURE_DONE = {
    "status": "ALIGNED",
    "results": [
        {
            "key": "USER_TWINS",
            "outcome": "ALIGNED",
            "issue": None,
            "version_number": 2,
            "codes": [],
        },
        {
            "key": "REQUIREMENTS",
            "outcome": "ALIGNED",
            "issue": None,
            "version_number": 4,
            "codes": [],
        },
        {"key": "DESIGN", "outcome": "ALIGNED", "issue": None, "version_number": 5, "codes": []},
    ],
    "sections": ALL_FINE,
}


def said(key: str, language: str = "en", **values: object) -> str:
    return messages.text(key, language, **values)


def found_of(document: dict[str, object]) -> sections_api.Sections:
    found = sections_api.sections_of(document)
    assert found is not None
    return found


def sentences(tmp_path: Path, document: dict[str, object], language: str) -> list[str]:
    context = command_context(
        environment(tmp_path, transport=NoNetwork(), language=language), language=language
    )
    return sections_command.sentences(context, found_of(document))


def linked(tmp_path: Path) -> None:
    store_session(tmp_path)
    link_folder(tmp_path / "project")


def expect_publication(transport: ScriptedTransport, number: int) -> None:
    archive = valid_archive(version_number=number)
    transport.expect(
        "POST",
        PACKAGES,
        status=201,
        body={
            "reused": False,
            "version": {"id": f"package-{number}", "version_number": number, "content_hash": "c"},
        },
    )
    transport.expect(
        "GET",
        f"{PACKAGES}/{number}/archive",
        body=archive,
        headers={
            "Content-Type": "application/zip",
            "X-Content-SHA256": hashlib.sha256(archive).hexdigest(),
        },
    )


def expect_steps(transport: ScriptedTransport) -> None:
    transport.expect("GET", f"{BASE}/brief-versions/current", body=version("brief-2", 2, "hb"))
    transport.expect("GET", f"{BASE}/gates/project-brief/current", body=gate("brief-2", "hb"))
    transport.expect(
        "GET",
        f"{BASE}/team-proposals/current",
        body={**version("team-1", 1, "ht"), "brief_version_number": 1, "brief_content_hash": "x"},
    )
    transport.expect("GET", f"{BASE}/gates/agent-team/current", body=gate("team-1", "ht"))
    transport.expect("GET", f"{BASE}/readiness", body={"status": "READY_FOR_MAIN_WORKFLOW"})
    transport.expect(
        "GET",
        f"{BASE}/user-modeling/readiness",
        body={"snapshot_version_number": 1, "approved_current_snapshot": False},
    )
    transport.expect("GET", f"{BASE}/requirements/readiness", body={"status": "NONE"})
    transport.expect("GET", f"{BASE}/design/readiness", body={"status": "NONE"})
    transport.expect("GET", f"{PACKAGES}?limit=1", body={"project_id": PROJECT_ID, "versions": []})


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_sections_behind_name_the_gesture_and_what_the_design_will_not_cover(
    tmp_path: Path, language: str
) -> None:
    document = {
        **PERSPECTIVE_CHANGED,
        "alignment": {**PERSPECTIVE_CHANGED["alignment"], "uncovered_codes": ["REQ-007"]},
    }

    lines = sentences(tmp_path, document, language)

    assert lines == [
        f"{BEHIND[language]} {said('sections.behind_command', language)}",
        said("sections.uncovered", language, codes="REQ-007"),
    ]
    assert lines[0].endswith("`ut sections update`.")
    assert lines[1].endswith("`ut design change`.")


PREPARE_AGAIN = sections_document(
    section("BRIEF", "FINE", 3),
    section("TEAM", "TO_UPDATE", 2, reasons=("BRIEF_CHANGED",), blocked="PREPARE_AGAIN"),
    section(
        "USER_TWINS",
        "TO_UPDATE",
        1,
        reasons=("BRIEF_CHANGED", "PERSPECTIVES_CHANGED"),
        blocked="UPSTREAM_NOT_READY",
    ),
    section(
        "REQUIREMENTS", "TO_UPDATE", 3, reasons=("BRIEF_CHANGED",), blocked="UPSTREAM_NOT_READY"
    ),
    section(
        "DESIGN", "TO_UPDATE", 4, reasons=("REQUIREMENTS_CHANGED",), blocked="UPSTREAM_NOT_READY"
    ),
    section("PACKAGE", "TO_UPDATE", 6, reasons=("FOLDER_BEHIND",)),
    aligned=("USER_TWINS", "REQUIREMENTS", "DESIGN"),
)
REMOVED = sections_document(
    *(item for item in ALL_FINE["sections"] if item["key"] not in {"DESIGN", "PACKAGE"}),
    section(
        "DESIGN",
        "TO_UPDATE",
        4,
        reasons=("REQUIREMENTS_CHANGED",),
        blocked="REQUIREMENT_NO_LONGER_AVAILABLE",
        codes=("REQ-003", "AC-004"),
    ),
    section("PACKAGE", "TO_UPDATE", 6, reasons=("FOLDER_BEHIND",)),
    aligned=("DESIGN",),
)


def blocked_document(key: str, blocked: str, *upstream: dict[str, object]) -> dict[str, object]:
    kept = [
        item
        for item in ALL_FINE["sections"]
        if item["key"] not in {key, *(u["key"] for u in upstream)}
    ]
    items = [
        *upstream,
        section(key, "TO_UPDATE", 3, reasons=("USER_TWINS_CHANGED",), blocked=blocked),
        *kept,
    ]
    order = list(sections_api.SECTION_KEYS)
    return sections_document(
        *sorted(items, key=lambda item: order.index(str(item["key"]))), aligned=(key,)
    )


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        (
            PREPARE_AGAIN,
            {
                "en": [
                    "Perspectives cannot be updated by itself: the brief changed: prepare the "
                    "perspectives again. Launch `ut init`."
                ],
                "it": [
                    "Prospettive non si aggiorna da sola: il brief è cambiato: prepara di nuovo "
                    "le prospettive. Lancia `ut init`."
                ],
            },
        ),
        (
            REMOVED,
            {
                "en": [
                    "Design & Evaluation cannot be updated by itself: the design cites REQ-003, "
                    "AC-004, which the Definition no longer contains: regenerate the alternatives "
                    "in the Design & Evaluation step of the web Studio. Then go on with "
                    "`ut design`."
                ],
                "it": [
                    "Design e valutazione non si aggiorna da sola: il design cita REQ-003, "
                    "AC-004, che la Definizione non contiene più: rigenera le alternative nel "
                    "passo Design e valutazione del web. Poi continua con `ut design`."
                ],
            },
        ),
        (
            blocked_document("REQUIREMENTS", "TWIN_NO_LONGER_AVAILABLE"),
            {
                "en": [
                    "Definition cannot be updated by itself: the twins are no longer the same. It "
                    "is settled in the web Studio."
                ],
                "it": [
                    "Definizione non si aggiorna da sola: i twin non sono più gli stessi. Si "
                    "sistema dallo Studio web."
                ],
            },
        ),
        (
            blocked_document("DESIGN", "TWIN_SET_CHANGED"),
            {
                "en": [
                    "Design & Evaluation cannot be updated by itself: the twins are no longer the "
                    "same. It is settled in the web Studio."
                ],
                "it": [
                    "Design e valutazione non si aggiorna da sola: i twin non sono più gli "
                    "stessi. Si sistema dallo Studio web."
                ],
            },
        ),
        (
            blocked_document("DESIGN", "DESIGN_REVISION_PENDING"),
            {
                "en": [
                    "Design & Evaluation cannot be updated by itself: a proposed change is "
                    "waiting for your decision. Launch `ut design`."
                ],
                "it": [
                    "Design e valutazione non si aggiorna da sola: c'è una modifica proposta da "
                    "decidere. Lancia `ut design`."
                ],
            },
        ),
        (
            blocked_document("USER_TWINS", "REVISION_PENDING"),
            {
                "en": [
                    "User Twin cannot be updated by itself: a proposed change is waiting for your "
                    "decision. It is settled in the web Studio."
                ],
                "it": [
                    "User Twin non si aggiorna da sola: c'è una modifica proposta da decidere. Si "
                    "sistema dallo Studio web."
                ],
            },
        ),
        (
            blocked_document(
                "USER_TWINS", "UPSTREAM_NOT_READY", section("REQUIREMENTS", "FINE", 1)
            ),
            {
                "en": [
                    "User Twin cannot be updated by itself: the section upstream has to be "
                    "settled first."
                ],
                "it": ["User Twin non si aggiorna da sola: prima va sistemata la sezione a monte."],
            },
        ),
        (
            blocked_document(
                "REQUIREMENTS", "UPSTREAM_NOT_READY", section("BRIEF", "IN_PROGRESS", 3)
            ),
            {
                "en": [
                    "Definition cannot be updated by itself: the section upstream has to be "
                    "settled first. Launch `ut init`."
                ],
                "it": [
                    "Definizione non si aggiorna da sola: prima va sistemata la sezione a monte. "
                    "Lancia `ut init`."
                ],
            },
        ),
        (
            blocked_document("REQUIREMENTS", "SOMETHING_NEW"),
            {
                "en": [
                    "Definition cannot be updated by itself: the Studio answered SOMETHING_NEW."
                ],
                "it": ["Definizione non si aggiorna da sola: lo Studio ha risposto SOMETHING_NEW."],
            },
        ),
    ],
)
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_section_that_cannot_be_updated_says_why_and_what_solves_it(
    tmp_path: Path, document: dict[str, object], expected: dict[str, list[str]], language: str
) -> None:
    assert sentences(tmp_path, document, language) == expected[language]


@pytest.mark.parametrize("language", LANGUAGES)
def test_new_material_is_told_with_its_command(tmp_path: Path, language: str) -> None:
    document = sections_document(
        *(item for item in ALL_FINE["sections"] if item["key"] not in {"USER_TWINS", "DESIGN"}),
        section("USER_TWINS", "UPDATE_AVAILABLE", 1, reasons=("TWINS_LEARNED",)),
        section(
            "DESIGN",
            "UPDATE_AVAILABLE",
            5,
            reasons=("REQUIREMENTS_NOT_COVERED", "EVALUATION_MISSING"),
            codes=("REQ-007", "REQ-008"),
        ),
    )

    lines = sentences(tmp_path, document, language)

    assert lines == [
        said("sections.twins_learned", language),
        said("sections.not_covered", language, codes="REQ-007, REQ-008"),
        said("sections.evaluation_missing", language),
    ]
    assert [line.rsplit("`", 2)[1] for line in lines] == [
        "ut twins update",
        "ut design change",
        "ut design review",
    ]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_dossier_behind_alone_names_the_publication(tmp_path: Path, language: str) -> None:
    alone = sections_document(
        *(item for item in ALL_FINE["sections"] if item["key"] != "PACKAGE"),
        section("PACKAGE", "TO_UPDATE", 3, reasons=("FOLDER_BEHIND",)),
    )

    assert sentences(tmp_path, alone, language) == [said("sections.dossier_behind", language)]
    assert sentences(tmp_path, ALL_FINE, language) == []
    assert "ut package publish" not in " ".join(sentences(tmp_path, PERSPECTIVE_CHANGED, language))


@pytest.mark.parametrize(
    ("language", "rows"),
    [
        ("en", ["Design & Evaluation  Your turn   v3", "Dossier              To update   v3"]),
        (
            "it",
            ["Design e valutazione  Tocca a te     v3", "Dossier               Da aggiornare  v3"],
        ),
    ],
)
def test_a_dossier_waiting_for_the_design_in_progress_gets_no_sentence(
    tmp_path: Path, language: str, rows: list[str]
) -> None:
    linked(tmp_path)
    transport = ScriptedTransport().expect("GET", SECTIONS, body=DESIGN_WAITING)

    run = run_ut(["--lang", language, "sections"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    assert sentences(tmp_path, DESIGN_WAITING, language) == []
    assert run.output.splitlines()[-2:] == rows
    assert "" not in run.output.splitlines()
    transport.assert_done()


def test_every_word_of_the_contract_has_a_sentence() -> None:
    keys = [
        *(f"sections.state_{state.lower()}" for state in sections_api.STATES),
        *(f"sections.reason_{block.lower()}" for block in sections_api.BLOCKS),
        *(f"common.stage_{stage}" for stage in sections_api.STAGE_OF.values()),
    ]

    assert [key for key in keys if not messages.known(key)] == []


def test_the_command_is_listed_after_status(tmp_path: Path) -> None:
    run = run_ut(["--help"], tmp_path, transport=NoNetwork())

    names = [module.NAME for module in COMMANDS]
    lines = [line.split()[0] for line in run.output.splitlines() if line.startswith("    ")]
    assert names[names.index("status") + 1] == "sections"
    assert lines[lines.index("status") + 1] == "sections"


@pytest.mark.parametrize(
    ("language", "fragments"),
    [
        (
            "en",
            [
                "Show the state of the sections of the project",
                "print the object of the sections as the Studio gives it",
                "re-anchor the sections to update to the new versions",
            ],
        ),
        (
            "it",
            [
                "Mostra lo stato delle sezioni del progetto",
                "stampa l'oggetto delle sezioni come lo dà lo Studio",
                "riaggancia alle versioni nuove le sezioni da aggiornare",
            ],
        ),
    ],
)
def test_the_help_speaks_both_languages(
    tmp_path: Path, language: str, fragments: list[str]
) -> None:
    run = run_ut(["--lang", language, "sections", "--help"], tmp_path, transport=NoNetwork())

    assert run.status == 0
    for fragment in fragments:
        assert fragment in " ".join(run.output.split())


def test_sections_show_the_table_and_the_sentences_and_nothing_else(tmp_path: Path) -> None:
    linked(tmp_path)
    transport = ScriptedTransport().expect("GET", SECTIONS, body=PERSPECTIVE_CHANGED)

    run = run_ut(["sections"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    assert run.output.splitlines() == [
        "Section              State       Version",
        "-------------------  ----------  -------",
        "Brief                Up to date  v2",
        "Perspectives         Up to date  v2",
        "User Twin            To update   v1",
        "Definition           To update   v3",
        "Design & Evaluation  To update   v4",
        "Dossier              To update   v6",
        "",
        f"{BEHIND['en']} Update and confirm with `ut sections update`.",
    ]
    transport.assert_done()


def test_sections_as_json_are_the_object_of_the_studio(tmp_path: Path) -> None:
    linked(tmp_path)
    transport = ScriptedTransport().expect("GET", SECTIONS, body=PERSPECTIVE_CHANGED)

    run = run_ut(["sections", "--json"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    assert json.loads(run.output) == PERSPECTIVE_CHANGED


def test_during_the_first_pass_sections_show_the_steps(tmp_path: Path) -> None:
    linked(tmp_path)
    transport = ScriptedTransport().expect(
        "GET", SECTIONS, body=PREPARE_AGAIN | {"first_pass_complete": False}
    )
    expect_steps(transport)

    run = run_ut(["--lang", "it", "sections"], tmp_path, transport=transport)

    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert lines[0].startswith("Passo ")
    assert lines[3].startswith("Prospettive ") and "da approvare" in lines[3]
    assert lines[-2:] == [
        "",
        "Prospettive non si aggiorna da sola: il brief è cambiato: prepara di nuovo le "
        "prospettive. Lancia `ut init`.",
    ]
    transport.assert_done()


@pytest.mark.parametrize(
    "arguments", [["sections"], ["sections", "--json"], ["sections", "update"]]
)
def test_an_older_studio_is_said_and_nothing_else_is_sent(
    tmp_path: Path, arguments: list[str]
) -> None:
    linked(tmp_path)
    transport = ScriptedTransport().expect(
        "GET", SECTIONS, status=404, body={"detail": "Not Found"}
    )

    run = run_ut(arguments, tmp_path, transport=transport)

    assert run.status == 1
    assert run.output == ""
    assert (
        run.errors
        == said("sections.errors.SECTIONS_UNSUPPORTED", studio="http://127.0.0.1:8000") + "\n"
    )
    transport.assert_done()


def test_json_goes_only_with_the_list(tmp_path: Path) -> None:
    run = run_ut(["sections", "--json", "update"], tmp_path, transport=NoNetwork())

    assert run.status == 2
    assert run.errors == said("sections.errors.SECTIONS_JSON_ALONE") + "\n"


def test_a_folder_not_linked_is_said(tmp_path: Path) -> None:
    run = run_ut(["sections", "update"], tmp_path, transport=NoNetwork())

    assert run.status == 6


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_update_says_what_changes_asks_once_sends_the_gesture_and_publishes(
    tmp_path: Path, language: str
) -> None:
    linked(tmp_path)
    transport = ScriptedTransport().expect("GET", SECTIONS, body=PERSPECTIVE_CHANGED)
    transport.expect("POST", ALIGNMENT, body=GESTURE_DONE)
    expect_publication(transport, 7)

    run = run_ut(
        ["--lang", language, "sections", "update"], tmp_path, transport=transport, answers=[""]
    )

    lines = run.output.splitlines()
    names = [
        said(f"common.stage_{stage}", language) for stage in ("twins", "requirements", "design")
    ]
    assert run.status == 0, run.errors
    assert lines[0] == BEHIND[language]
    assert (
        lines[1]
        == f"{said('sections.confirm', language)} {said('common.yes_no_default_yes', language)} "
    )
    assert lines[2:5] == [
        said("sections.result_aligned", language, section=names[0], version=2),
        said("sections.result_aligned", language, section=names[1], version=4),
        said("sections.result_aligned", language, section=names[2], version=5),
    ]
    assert lines[5] == said("sections.done", language, sections=", ".join(names))
    assert lines[-1] == said("sections.folder_updated", language, path="orchestwin/", version=7)
    assert len(transport.requests("POST", ALIGNMENT)) == 1
    assert (tmp_path / "project" / "orchestwin" / "orchestwin.json").is_file()
    transport.assert_done()


def test_yes_skips_the_question(tmp_path: Path) -> None:
    linked(tmp_path)
    transport = ScriptedTransport().expect("GET", SECTIONS, body=PERSPECTIVE_CHANGED)
    transport.expect("POST", ALIGNMENT, body=GESTURE_DONE)
    expect_publication(transport, 7)

    run = run_ut(["--yes", "sections", "update"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    assert said("sections.confirm") not in run.output
    transport.assert_done()


def test_a_refused_confirmation_sends_nothing(tmp_path: Path) -> None:
    linked(tmp_path)
    transport = ScriptedTransport().expect("GET", SECTIONS, body=PERSPECTIVE_CHANGED)

    run = run_ut(["sections", "update"], tmp_path, transport=transport, answers=["n"])

    assert run.status == 1
    assert run.output.splitlines()[-1] == "Nothing was updated."
    assert transport.requests("POST") == []


def test_a_closed_input_ends_with_one_and_nothing_done(tmp_path: Path) -> None:
    linked(tmp_path)
    transport = ScriptedTransport().expect("GET", SECTIONS, body=PERSPECTIVE_CHANGED)

    run = run_ut(["sections", "update"], tmp_path, transport=transport)

    assert run.status == 1
    assert run.errors == said("errors.INPUT_CLOSED") + "\n"
    assert transport.requests("POST") == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_nothing_to_align_is_one_plain_sentence(tmp_path: Path, language: str) -> None:
    linked(tmp_path)
    nothing = ScriptedTransport().expect("GET", SECTIONS, body=ALL_FINE)
    raced = ScriptedTransport().expect("GET", SECTIONS, body=PERSPECTIVE_CHANGED)
    raced.expect(
        "POST", ALIGNMENT, body={"status": "NOTHING_TO_ALIGN", "results": [], "sections": ALL_FINE}
    )

    quiet = run_ut(["--lang", language, "sections", "update"], tmp_path, transport=nothing)
    late = run_ut(["--lang", language, "--yes", "sections", "update"], tmp_path, transport=raced)

    assert (quiet.status, late.status) == (0, 0)
    assert quiet.output == said("sections.nothing", language) + "\n"
    assert late.output.splitlines()[-1] == said("sections.nothing", language)
    assert nothing.requests("POST") == []


def test_a_blocked_chain_is_told_with_its_command_and_ends_with_one(tmp_path: Path) -> None:
    linked(tmp_path)
    transport = ScriptedTransport().expect("GET", SECTIONS, body=REMOVED)

    run = run_ut(["sections", "update"], tmp_path, transport=transport)

    assert run.status == 1
    assert run.output.splitlines() == sentences(tmp_path, REMOVED, "en")
    assert transport.requests("POST") == []


def test_a_partial_gesture_tells_the_blocked_section_and_waits_for_the_folder(
    tmp_path: Path,
) -> None:
    linked(tmp_path)
    after = sections_document(
        *(item for item in ALL_FINE["sections"] if item["key"] not in {"DESIGN", "PACKAGE"}),
        section(
            "DESIGN", "TO_UPDATE", 4, reasons=("REQUIREMENTS_CHANGED",), blocked="TWIN_SET_CHANGED"
        ),
        section("PACKAGE", "TO_UPDATE", 6, reasons=("FOLDER_BEHIND",)),
        aligned=("DESIGN",),
    )
    gesture = {
        "status": "PARTIAL",
        "results": [
            GESTURE_DONE["results"][0],
            GESTURE_DONE["results"][1],
            {
                "key": "DESIGN",
                "outcome": "BLOCKED",
                "issue": "TWIN_SET_CHANGED",
                "version_number": None,
                "codes": [],
            },
        ],
        "sections": after,
    }
    transport = ScriptedTransport().expect("GET", SECTIONS, body=PERSPECTIVE_CHANGED)
    transport.expect("POST", ALIGNMENT, body=gesture)

    run = run_ut(["--yes", "sections", "update"], tmp_path, transport=transport)

    assert run.status == 1
    assert run.output.splitlines()[1:] == [
        "User Twin: updated and confirmed at version 2.",
        "Definition: updated and confirmed at version 4.",
        "Design & Evaluation cannot be updated by itself: the twins are no longer the same. It is "
        "settled in the web Studio.",
        "Sections updated: User Twin, Definition.",
        "The knowledge folder stays as it was: it is updated once every section is up to date.",
    ]
    assert transport.requests("POST", PACKAGES) == []
    transport.assert_done()


def test_a_design_re_anchored_without_a_review_says_that_the_twins_can_evaluate_it(
    tmp_path: Path,
) -> None:
    linked(tmp_path)
    after = sections_document(
        *(item for item in ALL_FINE["sections"] if item["key"] != "DESIGN"),
        section("DESIGN", "UPDATE_AVAILABLE", 5, reasons=("EVALUATION_MISSING",)),
    )
    transport = ScriptedTransport().expect("GET", SECTIONS, body=PERSPECTIVE_CHANGED)
    transport.expect("POST", ALIGNMENT, body={**GESTURE_DONE, "sections": after})
    transport.expect("POST", PACKAGES, status=409, body={"detail": {"code": "DESIGN_OUTDATED"}})

    run = run_ut(["--yes", "sections", "update"], tmp_path, transport=transport)

    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert lines[
        lines.index("Sections updated: User Twin, Definition, Design & Evaluation.") + 1
    ] == (said("sections.evaluation_after"))
    assert lines[-1] == said("sections.folder_not_updated", code="DESIGN_OUTDATED")


def test_a_section_blocked_at_the_gesture_is_told_and_ends_with_one(tmp_path: Path) -> None:
    linked(tmp_path)
    behind = sections_document(
        *(item for item in ALL_FINE["sections"] if item["key"] != "DESIGN"),
        section("DESIGN", "TO_UPDATE", 4, reasons=("REQUIREMENTS_CHANGED",)),
        available=True,
        aligned=("DESIGN",),
    )
    gesture = {
        "status": "NOTHING_TO_ALIGN",
        "results": [
            {
                "key": "DESIGN",
                "outcome": "BLOCKED",
                "issue": "ITERATION_LIMIT_REACHED",
                "version_number": None,
                "codes": [],
            }
        ],
        "sections": behind,
    }
    transport = ScriptedTransport().expect("GET", SECTIONS, body=behind)
    transport.expect("POST", ALIGNMENT, body=gesture)

    run = run_ut(["--yes", "sections", "update"], tmp_path, transport=transport)

    assert run.status == 1
    assert run.output.splitlines()[-1] == (
        "Design & Evaluation cannot be updated by itself: the Studio answered "
        "ITERATION_LIMIT_REACHED."
    )
    assert said("sections.nothing") not in run.output
    assert transport.requests("POST", PACKAGES) == []
    transport.assert_done()


def test_an_older_studio_at_the_gesture_is_said(tmp_path: Path) -> None:
    linked(tmp_path)
    transport = ScriptedTransport().expect("GET", SECTIONS, body=PERSPECTIVE_CHANGED)
    transport.expect("POST", ALIGNMENT, status=404, body={"detail": "Not Found"})

    run = run_ut(["--yes", "sections", "update"], tmp_path, transport=transport)

    assert run.status == 1
    assert (
        run.errors
        == said("sections.errors.SECTIONS_UNSUPPORTED", studio="http://127.0.0.1:8000") + "\n"
    )


EMAIL = "owner@example.com"
NAME = "Calcolo mancia"


@dataclass(frozen=True, slots=True)
class Session:
    studio: FakeStudio
    project: FakeProject
    tmp_path: Path

    def ut(self, *arguments: str, answers: Sequence[str] = (), language: str = "en") -> Run:
        return run_ut(
            ["--lang", language, *arguments],
            self.tmp_path,
            transport=UrlTransport(),
            answers=answers,
        )

    def states(self) -> dict[str, str]:
        return {
            str(item["key"]): str(item["state"]) for item in self.project.sections()["sections"]
        }

    def twin_ids(self) -> list[str]:
        snapshot = self.project.current("twins")
        assert snapshot is not None
        return sorted(str(twin["twin_id"]) for twin in snapshot["snapshot"]["twin_versions"])

    def design(self) -> tuple[object, ...]:
        design = self.project.current("design")
        assert design is not None
        package = design["package"]
        return (
            [(item["id"], item["code"], item["title"]) for item in package["alternatives"]],
            package["owner_selected_alternative_id"],
            package["prototype"],
            package["owner_assertions"],
        )


@contextmanager
def session(tmp_path: Path, *, language: str = "en") -> Iterator[Session]:
    with FakeStudio(language=language, twins=2) as studio:
        studio.add_account(EMAIL, TEST_PASSWORD)
        project = studio.seed_project(owner=EMAIL, name=NAME, through="design")
        login = run_ut(
            ["login", "--studio", studio.address, "--email", EMAIL, "--password-stdin"],
            tmp_path,
            transport=UrlTransport(),
            answers=[TEST_PASSWORD],
        )
        assert login.status == 0, login.errors
        link_folder(tmp_path / "project", project_id=project.id, name=NAME, studio=studio.address)
        yield Session(studio=studio, project=project, tmp_path=tmp_path)
        assert studio.errors == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_perspective_switched_after_the_design_is_re_anchored_in_one_gesture(
    tmp_path: Path, language: str
) -> None:
    with session(tmp_path, language=language) as current:
        twins, design = current.twin_ids(), current.design()
        current.project.seed_perspective_change("SECURITY_REVIEWER")
        refused = current.ut("package", "publish", language=language)
        status = current.ut("status", language=language)
        run = current.ut("sections", "update", answers=[""], language=language)
        states = current.states()
        gestures = current.project.alignments()
        same_twins, same_design = current.twin_ids() == twins, current.design() == design
        published = current.project.knowledge_versions()

    names = [
        said(f"common.stage_{stage}", language) for stage in ("twins", "requirements", "design")
    ]
    lines = run.output.splitlines()
    assert refused.status == 1
    assert refused.errors == said("package.errors.USER_TWINS_OUTDATED", language) + "\n"
    assert f"{BEHIND[language]} {said('sections.behind_command', language)}" in status.output
    assert run.status == 0, run.errors
    assert lines[0] == BEHIND[language]
    assert lines[2:5] == [
        said("sections.result_aligned", language, section=names[0], version=2),
        said("sections.result_aligned", language, section=names[1], version=2),
        said("sections.result_aligned", language, section=names[2], version=3),
    ]
    assert lines[5] == said("sections.done", language, sections=", ".join(names))
    assert lines[-1] == said("sections.folder_updated", language, path="orchestwin/", version=1)
    assert len(gestures) == 1
    assert same_twins and same_design
    assert len(published) == 1
    assert [key for key, state in states.items() if state == "TO_UPDATE"] == []
    assert (tmp_path / "project" / "orchestwin" / "orchestwin.json").is_file()


def test_new_requirements_after_the_design_are_announced_before_the_gesture(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        before = current.project.seed_requirements_change()
        run = current.ut("--yes", "sections", "update")
        after = current.project.sections()
        gestures = current.project.alignments()

    uncovered = before["alignment"]["uncovered_codes"]
    design = next(item for item in after["sections"] if item["key"] == "DESIGN")
    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert uncovered
    assert lines[:2] == [
        said("sections.behind", sections=said("common.stage_design")),
        said("sections.uncovered", codes=", ".join(uncovered)),
    ]
    assert said("sections.evaluation_after") in lines
    assert design["state"] == "UPDATE_AVAILABLE"
    assert design["codes"] == uncovered
    assert len(gestures) == 1


def test_a_requirement_removed_under_the_design_stops_the_gesture_before_it_is_sent(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as current:
        before = current.project.seed_requirement_removed()
        run = current.ut("--yes", "sections", "update")
        gestures = current.project.alignments()
        states = current.states()

    design = next(item for item in before["sections"] if item["key"] == "DESIGN")
    assert run.status == 1
    assert design["blocked"] == "REQUIREMENT_NO_LONGER_AVAILABLE"
    assert run.output.splitlines() == [
        said(
            "sections.blocked",
            section=said("common.stage_design"),
            reason=said(
                "sections.reason_requirement_no_longer_available",
                codes=", ".join(design["codes"]),
            ),
        )
        + " "
        + said("sections.solve_design_change")
    ]
    assert "the Design & Evaluation step of the web Studio" in run.output
    assert "ut design change" not in run.output
    assert "ask for a change" not in run.output
    assert gestures == []
    assert states["DESIGN"] == "TO_UPDATE"


def test_a_new_brief_asks_to_prepare_the_perspectives_again(tmp_path: Path) -> None:
    with session(tmp_path, language="it") as current:
        current.project.seed_brief_change()
        run = current.ut("sections", "update", language="it")
        gestures = current.project.alignments()

    assert run.status == 1
    assert run.output.splitlines() == [
        "Prospettive non si aggiorna da sola: il brief è cambiato: prepara di nuovo le "
        "prospettive. Lancia `ut init`."
    ]
    assert gestures == []


@pytest.mark.parametrize(("answers", "status"), [(["n"], 1), ([], 1)])
def test_a_gesture_not_confirmed_changes_nothing(
    tmp_path: Path, answers: list[str], status: int
) -> None:
    with session(tmp_path) as current:
        current.project.seed_requirements_change()
        run = current.ut("sections", "update", answers=answers)
        gestures = current.project.alignments()
        states = current.states()

    assert run.status == status
    assert gestures == []
    assert states["DESIGN"] == "TO_UPDATE"
    if answers:
        assert run.output.splitlines()[-1] == said("sections.cancelled")
    else:
        assert run.errors == said("errors.INPUT_CLOSED") + "\n"


def test_sections_against_the_studio_read_once_and_send_nothing(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        current.project.seed_requirements_change()
        before = len(current.studio.requests)
        run = current.ut("sections")
        document = json.loads(current.ut("sections", "--json").output)
        sent = [
            (request.method, request.path.rsplit("/", 1)[-1])
            for request in current.studio.requests[before:]
        ]
        expected = current.project.sections()

    assert run.status == 0, run.errors
    assert document == expected
    assert sent == [("GET", "sections"), ("GET", "sections")]
