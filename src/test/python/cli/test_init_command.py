from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from orchestwin.cli.http import UrlTransport

from .support.fake_studio import FakeProject, FakeStudio
from .support.terminal import PROJECT_ID, TEST_PASSWORD, Run, link_folder, run_ut, store_session
from .support.transports import API, ScriptedTransport

EMAIL = "owner@example.com"
IDEA = "Una pagina per calcolare la mancia e dividere il conto."
NAME = "Calcolo mancia"
DIALOGUE = (
    "Al tavolo nessuno sa quanto lasciare.",
    "Camerieri",
    "Clienti",
    "",
    "Calcolare la mancia in fretta",
    "",
    "?",
)
CREATED_AT = "2026-09-29T09:00:00+00:00"
STAGES = ("brief", "team", "twins", "requirements")
PUBLICATION = "/knowledge-packages"
BASE = f"{API}/projects/{PROJECT_ID}"


def sign_in(studio: FakeStudio, tmp_path: Path) -> None:
    studio.add_account(EMAIL, TEST_PASSWORD)
    run = run_ut(
        ["login", "--studio", studio.address, "--email", EMAIL, "--password-stdin"],
        tmp_path,
        transport=UrlTransport(),
        answers=[TEST_PASSWORD],
    )
    assert run.status == 0, run.errors


def ut(
    tmp_path: Path,
    *arguments: str,
    answers: Sequence[str] = (),
    language: str = "en",
    yes: bool = False,
    working_directory: Path | None = None,
) -> Run:
    options = ["--lang", language, *(["--yes"] if yes else []), "init", *arguments]
    return run_ut(
        options,
        tmp_path,
        transport=UrlTransport(),
        answers=answers,
        working_directory=working_directory,
    )


def start(yes: str = "y", *, mode: str = "1") -> list[str]:
    return [mode, IDEA, "", NAME, yes]


def brief_answers() -> list[str]:
    return [*DIALOGUE, "1", "1"]


def twins_answers(yes: str = "y", count: int = 2) -> list[str]:
    return [*([yes] * count), "1"]


def whole_path(yes: str = "y", *, twins: int = 2) -> list[str]:
    return [*start(yes), *brief_answers(), "1", *twins_answers(yes, twins), "1"]


def link_document(tmp_path: Path) -> dict[str, object]:
    path = tmp_path / "project" / ".orchestwin" / "project.json"
    return json.loads(path.read_text(encoding="utf-8"))


def fake_project(studio: FakeStudio, tmp_path: Path) -> FakeProject:
    return studio.project(str(link_document(tmp_path)["project_id"]))


def saved_step(tmp_path: Path, stage: str) -> dict[str, object]:
    path = tmp_path / "project" / ".orchestwin" / "steps" / f"{stage}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def saved_stages(tmp_path: Path) -> list[str]:
    folder = tmp_path / "project" / ".orchestwin" / "steps"
    if not folder.is_dir():
        return []
    return [stage for stage in STAGES if (folder / f"{stage}.json").is_file()]


def changes(studio: FakeStudio) -> list[tuple[str, str, bytes]]:
    return [
        (request.method, request.path, request.body)
        for request in studio.requests
        if request.method != "GET" and not request.path.endswith(("/auth/login", PUBLICATION))
    ]


def publications(studio: FakeStudio) -> int:
    return len(
        [
            request
            for request in studio.requests
            if request.method == "POST" and request.path.endswith(PUBLICATION)
        ]
    )


def local_progress(tmp_path: Path) -> tuple[list[str], str | None]:
    manifest = tmp_path / "project" / "orchestwin" / "orchestwin.json"
    document = json.loads(manifest.read_text(encoding="utf-8"))
    return document["progress"]["approved"], document["progress"]["pending"]


def posted(studio: FakeStudio, suffix: str) -> list[object]:
    return [
        json.loads(request.body.decode("utf-8")) if request.body else None
        for request in studio.requests
        if request.method in {"POST", "PATCH"} and request.path.endswith(suffix)
    ]


def link_bytes(studio: FakeStudio, project_id: str, *, mode: str, language: str | None) -> bytes:
    shown = "null" if language is None else f'"{language}"'
    return (
        "{\n"
        '  "schema_version": 1,\n'
        f'  "studio": "{studio.address}",\n'
        '  "api_prefix": "/api/v1",\n'
        f'  "project_id": "{project_id}",\n'
        f'  "project_name": "{NAME}",\n'
        f'  "mode": "{mode}",\n'
        f'  "language": {shown},\n'
        f'  "created_at": "{CREATED_AT}",\n'
        '  "knowledge_folder": "orchestwin"\n'
        "}\n"
    ).encode()


def assert_saved(studio: FakeStudio, tmp_path: Path, stages: Sequence[str]) -> None:
    project = fake_project(studio, tmp_path)
    assert saved_stages(tmp_path) == list(stages)
    for stage in stages:
        document = saved_step(tmp_path, stage)
        assert (document["schema_version"], document["stage"]) == (1, stage)
        assert document["version"] == project.current(stage)
        gate = document["gate"]
        assert gate["status"] == "APPROVED"
        assert gate["artifact"]["artifact_id"] == document["version"]["id"]
        assert gate["artifact"]["content_hash"] == document["version"]["content_hash"]


@pytest.mark.parametrize(("language", "yes"), [("it", "s"), ("en", "y")])
def test_the_whole_path_with_typed_answers(tmp_path: Path, language: str, yes: str) -> None:
    with FakeStudio(language=language) as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, answers=whole_path(yes), language=language)

        assert run.status == 0, run.errors
        project = fake_project(studio, tmp_path)
        assert (project.stage, project.next_action) == ("DESIGN", "APPROVE_DESIGN")
        root = tmp_path / "project" / ".orchestwin"
        assert (root / "project.json").read_bytes() == link_bytes(
            studio, project.id, mode="DESIGN_ONLY", language=language
        )
        assert (root / ".gitignore").read_bytes() == b"previews/\n"
        assert_saved(studio, tmp_path, STAGES)
        next_line = {
            "it": "Il prossimo comando è `ut design`",
            "en": "The next command is `ut design`",
        }
        folder_line = {
            "it": "Cartella di conoscenza aggiornata in orchestwin/ (versione 4): contiene i "
            "passi approvati finora.",
            "en": "Knowledge folder updated in orchestwin/ (version 4): it holds the steps "
            "approved so far.",
        }
        assert next_line[language] in run.output
        assert folder_line[language] in run.output.splitlines()
        assert len(changes(studio)) == len(set(changes(studio)))
        assert publications(studio) == 4
        assert local_progress(tmp_path) == (list(STAGES), "design")
        assert run.errors == ""
        assert studio.errors == []


def test_the_whole_path_in_italian_says_what_happens_at_each_step(tmp_path: Path) -> None:
    with FakeStudio(language="it") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, answers=whole_path("s"), language="it")

    lines = run.output.splitlines()
    assert run.status == 0
    assert "Nuovo progetto di OrchesTwin in questa cartella." in lines
    assert "Stima: 0,48-0,72 USD, circa 5 min. Credito rimasto nello Studio: 60,00 USD." in lines
    assert "Punti essenziali ancora aperti: 4." in lines
    assert "Domanda 1: Quale problema risolve il progetto?" in lines
    assert "Punti essenziali ancora aperti: 1." in lines
    assert 'Passo "Brief" approvato (versione 3). Salvato in .orchestwin/steps/brief.json.' in lines
    assert "Il percorso ha quattro passi: Brief, Prospettive, User Twin e Definizione." in (
        run.output
    )
    assert "Passo 2 di 4: Prospettive" in lines
    assert "Passo 3 di 4: User Twin" in lines
    assert "Passo 4 di 4: Definizione" in lines
    assert "Profilo 2 di 2: Titolare della pizzeria" in lines
    assert "  Difficoltà: Conti a mente sbagliati; Attesa alla cassa" in lines
    assert "REQ-003  Divisione del conto       importante" in lines
    assert (
        'Fatto: il progetto "Calcolo mancia" ha approvati tutti i passi fino alla Definizione.'
        in (lines)
    )
    assert lines[lines.index("- Brief: versione 3") : lines.index("- Brief: versione 3") + 4] == [
        "- Brief: versione 3",
        "- Prospettive: versione 1",
        "- User Twin: versione 1",
        "- Definizione: versione 1",
    ]


def test_the_whole_path_with_an_answers_file_asks_nothing(tmp_path: Path) -> None:
    script = tmp_path / "answers.json"
    script.write_text(
        json.dumps(
            {
                "mode": "DESIGN_ONLY",
                "name": NAME,
                "idea": IDEA,
                "answers": {
                    "problem": "Al tavolo nessuno sa quanto lasciare.",
                    "goals": ["Fare presto"],
                },
                "proposals": "ACCEPT_ALL",
                "team": "APPROVE",
                "profiles": "CONFIRM_ALL",
                "twins": "APPROVE",
                "requirements": {"changes": [], "decision": "APPROVE"},
            }
        ),
        encoding="utf-8",
    )
    with FakeStudio(language="it") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, "--answers", str(script), language="it", yes=True)

        assert run.status == 0, run.errors
        project = fake_project(studio, tmp_path)
        assert project.stage == "DESIGN"
        assert posted(studio, "/brief-dialogue/answers") == [
            {
                "kind": "TEXT",
                "text": "Al tavolo nessuno sa quanto lasciare.",
                "expected_turn_count": 1,
            },
            {"kind": "UNKNOWN", "expected_turn_count": 2},
            {"kind": "ITEM_LIST", "items": ["Fare presto"], "expected_turn_count": 3},
            {"kind": "UNKNOWN", "expected_turn_count": 4},
        ]
        assert_saved(studio, tmp_path, STAGES)
        assert len(changes(studio)) == len(set(changes(studio)))
    assert "Spesa confermata con --yes." in run.output
    assert "Risposta dal file: non lo so, lo propone il modello." in run.output


def test_without_sign_in_nothing_is_asked_and_nothing_is_sent(tmp_path: Path) -> None:
    run = run_ut(["init"], tmp_path, transport=ScriptedTransport())

    assert run.status == 3
    assert "ut login" in run.errors
    assert run.output == ""


def test_a_refused_spending_leaves_nothing_behind(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, answers=start("n"))

        assert run.status == 5
        assert "the spending was not confirmed" in run.errors
        assert not (tmp_path / "project" / ".orchestwin").exists()
        assert [request.path for request in studio.requests if request.method == "POST"] == [
            f"{API}/auth/login"
        ]


def test_a_studio_without_a_budget_asks_nothing_about_spending(tmp_path: Path) -> None:
    with FakeStudio(language="en", budget_usd=None) as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, "--until", "brief", answers=["", IDEA, "", NAME, *brief_answers()])

    assert run.status == 0, run.errors
    assert "Estimate" not in run.output
    assert "spending" not in run.output
    assert "Write the number of your choice: [1]" in run.output
    assert link_document(tmp_path)["mode"] == "DESIGN_ONLY"


def test_design_and_code_is_written_in_the_link_with_one_sentence(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, "--until", "brief", answers=[*start(mode="2")[:-1], *brief_answers()])

        assert run.status == 0, run.errors
        project = fake_project(studio, tmp_path)
        path = tmp_path / "project" / ".orchestwin" / "project.json"
        assert path.read_bytes() == link_bytes(
            studio, project.id, mode="DESIGN_AND_CODE", language="en"
        )
    assert (
        "The code will be generated by a later command: in this mode too the path starts "
        "from the design." in run.output
    )


def test_until_stops_after_the_step_and_the_next_launch_goes_on(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        first = ut(tmp_path, "--until", "brief", answers=[*start()[:-1], *brief_answers()])
        after_first = saved_stages(tmp_path)
        second = ut(tmp_path, answers=["y", "1", *twins_answers(), "1"])

        assert (first.status, second.status) == (0, 0), second.errors
        assert after_first == ["brief"]
        assert_saved(studio, tmp_path, STAGES)
    assert (
        'Stopping after the step "Brief", as asked with --until. Launch `ut init` again to go on '
        'with the step "Perspectives".' in first.output
    )
    assert "Step 2 of 4" not in first.output
    assert 'Resuming the project "Calcolo mancia" from step 2 of 4: Perspectives.' in second.output
    assert 'Step "Brief" already approved (version 3).' in second.output
    assert "Step 2 of 4: Perspectives" in second.output.splitlines()
    assert 'Done: the project "Calcolo mancia" has every step approved up to the Definition.' in (
        second.output.splitlines()
    )


STOPS = {
    "brief": (
        [*start(), *DIALOGUE, "1", "3"],
        ["y", "1", "1", *twins_answers(), "1"],
        [],
    ),
    "team": (
        [*start(), *brief_answers(), "3"],
        ["y", "1", *twins_answers(), "1"],
        ["brief"],
    ),
    "twins": (
        [*start(), *brief_answers(), "1", "y", "y", "2"],
        ["y", "1", "1"],
        ["brief", "team"],
    ),
    "requirements": (
        [*start(), *brief_answers(), "1", *twins_answers(), "4"],
        ["1"],
        ["brief", "team", "twins"],
    ),
}
LEFT = {
    "brief": "The brief stays waiting for your approval.",
    "team": "The perspectives stay waiting for your approval.",
    "twins": "The User Twins stay waiting for your approval.",
    "requirements": "The requirements stay waiting for your approval.",
}


@pytest.mark.parametrize("stage", STAGES)
def test_an_interruption_after_each_step_is_continued(tmp_path: Path, stage: str) -> None:
    first_answers, second_answers, kept = STOPS[stage]
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        first = ut(tmp_path, answers=first_answers)
        after_first = saved_stages(tmp_path)
        second = ut(tmp_path, answers=second_answers)

        assert first.status == 0, first.errors
        assert after_first == kept
        assert LEFT[stage] in first.output
        assert second.status == 0, second.errors
        assert_saved(studio, tmp_path, STAGES)
        assert len(changes(studio)) == len(set(changes(studio)))
    for approved in kept:
        assert "already approved" in second.output
        assert f"Step {STAGES.index(approved) + 1} of 4" not in second.output


def test_the_project_option_links_the_folder_to_a_project_of_the_studio(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        seeded = studio.seed_project(owner=EMAIL, name=NAME, through="team")

        run = ut(tmp_path, "--project", seeded.id, answers=["1", "y", *twins_answers(), "1"])

        assert run.status == 0, run.errors
        path = tmp_path / "project" / ".orchestwin" / "project.json"
        assert path.read_bytes() == link_bytes(studio, seeded.id, mode="DESIGN_ONLY", language=None)
        assert_saved(studio, tmp_path, STAGES)
        assert seeded.stage == "DESIGN"
    assert 'Linking this folder to the project "Calcolo mancia" of the Studio.' in run.output
    assert 'Resuming the project "Calcolo mancia" from step 3 of 4: User Twin.' in run.output
    assert 'Step "Perspectives" already approved (version 1).' in run.output


def test_a_project_already_at_the_design_step_only_saves_its_steps(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        seeded = studio.seed_project(owner=EMAIL, name=NAME, through="requirements")

        run = ut(tmp_path, "--project", seeded.id, "--mode", "design")

        assert run.status == 0, run.errors
        assert_saved(studio, tmp_path, STAGES)
        assert changes(studio) == []
        assert publications(studio) >= 1
        assert len(seeded.knowledge_versions()) == 1
        assert local_progress(tmp_path) == (list(STAGES), "design")
    assert (
        'The project "Calcolo mancia" already has the steps Brief, Perspectives, User Twin and '
        "Definition approved." in run.output.splitlines()
    )
    assert "The next command is `ut design`" in run.output
    assert (
        "Knowledge folder updated in orchestwin/ (version 1): it holds the steps approved "
        "so far." in run.output.splitlines()
    )


def test_the_project_option_refuses_a_folder_linked_to_another_project(tmp_path: Path) -> None:
    store_session(tmp_path)
    link_folder(tmp_path / "project")
    other = "3f7c2a58-0000-4000-8000-000000000002"
    transport = ScriptedTransport()

    run = run_ut(["init", "--project", other], tmp_path, transport=transport)

    assert run.status == 1
    assert "already linked to another project" in run.errors
    assert transport.sent == []


@pytest.mark.parametrize(
    ("arguments", "words"),
    [
        (["--project", "not-a-project"], '"not-a-project" is not the identifier of a project'),
        (["--name", "   "], "The name of the project must have from 1 to 120 characters."),
        (["--idea", ""], "The idea must have from 1 to 2000 characters."),
        (["--until", "design"], "invalid choice"),
    ],
)
def test_wrong_options_are_usage_errors(tmp_path: Path, arguments: list[str], words: str) -> None:
    transport = ScriptedTransport()

    run = run_ut(["init", *arguments], tmp_path, transport=transport)

    assert run.status == 2
    assert words in run.errors
    assert transport.sent == []


def test_the_input_closed_during_the_dialogue_is_continued_later(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        first = ut(tmp_path, answers=[*start(), DIALOGUE[0]])
        after_first = saved_stages(tmp_path)
        second = ut(tmp_path, answers=["y", *DIALOGUE[1:], "1", "1", "1", *twins_answers(), "1"])

        assert first.status == 1
        assert (
            "The input closed while an answer was awaited: nothing else was done." in first.errors
        )
        assert after_first == []
        assert (tmp_path / "project" / ".orchestwin" / "project.json").is_file()
        assert second.status == 0, second.errors
        assert_saved(studio, tmp_path, STAGES)
        assert len(changes(studio)) == len(set(changes(studio)))
    assert "Question 2: Who will use the product?" in first.output
    assert "Question 2: Who will use the product?" in second.output
    assert "Question 1:" not in second.output


def test_a_studio_that_cannot_be_reached_in_the_middle_loses_nothing(tmp_path: Path) -> None:
    store_session(tmp_path)
    link_folder(tmp_path / "project")
    transport = ScriptedTransport()
    for _ in range(3):
        transport.expect("GET", f"{API}/projects/{PROJECT_ID}", unreachable=True)

    run = run_ut(["init"], tmp_path, transport=transport)

    assert run.status == 4
    assert "Nothing is lost: what you approved is saved." in run.errors
    assert (tmp_path / "project" / ".orchestwin" / "project.json").is_file()
    transport.assert_done()


def test_each_approved_step_brings_the_partial_folder_into_the_project(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        first = ut(tmp_path, "--until", "brief", answers=[*start()[:-1], *brief_answers()])
        after_brief = local_progress(tmp_path)
        second = ut(tmp_path, "--until", "team", answers=["y", "1"])
        after_team = local_progress(tmp_path)
        versions = fake_project(studio, tmp_path).knowledge_versions()

        assert (first.status, second.status) == (0, 0), second.errors
        assert [version["version_number"] for version in versions] == [1, 2]
        assert studio.errors == []
    assert after_brief == (["brief"], "team")
    assert after_team == (["brief", "team"], "twins")
    assert (
        "Knowledge folder updated in orchestwin/ (version 1): it holds the steps approved "
        "so far." in first.output.splitlines()
    )
    assert "Knowledge folder updated in orchestwin/ (version 2)" in second.output


def write_local_manifest(project: Path, stages: Sequence[str]) -> None:
    folder = project / "orchestwin"
    folder.mkdir(parents=True)
    manifest = {
        "schema_version": 3,
        "package": {"version_number": 7, "content_hash": "c"},
        "project": {"id": PROJECT_ID, "name": NAME},
        "stages": {
            stage: {"version_number": 1, "gate": {"status": "APPROVED"}} for stage in stages
        },
        "progress": {"approved": list(stages), "pending": "design", "complete": False},
        "files": {},
    }
    (folder / "orchestwin.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_a_folder_that_already_holds_the_approved_steps_is_not_published_again(
    tmp_path: Path,
) -> None:
    store_session(tmp_path)
    link_folder(tmp_path / "project")
    write_local_manifest(tmp_path / "project", STAGES)
    transport = ScriptedTransport()
    expect_approved_steps(transport)

    run = run_ut(["init"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    assert transport.requests("POST") == []
    transport.assert_done()


def expect_approved_steps(transport: ScriptedTransport) -> None:
    brief = {"id": "brief-1", "version_number": 1, "content_hash": "hb", "brief": {}}
    team = {
        "id": "team-1",
        "version_number": 1,
        "content_hash": "ht",
        "brief_version_number": 1,
        "brief_content_hash": "hb",
        "selected_agent_ids": ["UX_UI_DESIGNER"],
        "role_constraints": [],
        "constraint_issues": [],
        "members": [{"agent_id": "UX_UI_DESIGNER", "justifications": []}],
    }
    snapshot = {"id": "snapshot-1", "version_number": 1, "content_hash": "hs"}
    requirements = {"id": "spec-1", "version_number": 1, "content_hash": "hr"}

    def gate(version: dict[str, object]) -> dict[str, object]:
        return {
            "id": f"gate-{version['id']}",
            "status": "APPROVED",
            "artifact": {"artifact_id": version["id"], "content_hash": version["content_hash"]},
        }

    transport.expect(
        "GET", BASE, body={"id": PROJECT_ID, "display_name": NAME, "current_stage": "DESIGN"}
    )
    transport.expect("GET", f"{BASE}/brief-versions/current", body=brief)
    transport.expect("GET", f"{BASE}/gates/project-brief/current", body=gate(brief))
    transport.expect("GET", f"{BASE}/team-proposals/current", body=team)
    transport.expect("GET", f"{BASE}/readiness", body={"status": "READY_FOR_MAIN_WORKFLOW"})
    transport.expect("GET", f"{BASE}/gates/agent-team/current", body=gate(team))
    transport.expect(
        "GET",
        f"{BASE}/user-modeling/readiness",
        body={
            "workflow_state": "READY_FOR_REQUIREMENTS_DEFINITION",
            "approved_current_snapshot": True,
            "snapshot_version_number": 1,
        },
    )
    transport.expect("GET", f"{BASE}/user-modeling/snapshots/current", body=snapshot)
    transport.expect("GET", f"{BASE}/user-modeling/gate", body=gate(snapshot))
    transport.expect(
        "GET",
        f"{BASE}/requirements/readiness",
        body={
            "status": "READY_FOR_DESIGN_EXPLORATION",
            "version": requirements,
            "gate": gate(requirements),
        },
    )


def test_a_studio_that_publishes_only_complete_folders_is_asked_once_and_says_nothing(
    tmp_path: Path,
) -> None:
    store_session(tmp_path)
    link_folder(tmp_path / "project")
    transport = ScriptedTransport()
    expect_approved_steps(transport)
    transport.expect(
        "POST",
        f"{BASE}{PUBLICATION}",
        status=409,
        body={"detail": {"code": "DESIGN_APPROVAL_REQUIRED"}},
    )

    run = run_ut(["init"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    assert run.errors == ""
    assert "knowledge folder" not in run.output.lower()
    transport.assert_done()


def test_a_publication_that_fails_is_said_in_one_line_and_the_path_goes_on(
    tmp_path: Path,
) -> None:
    store_session(tmp_path)
    link_folder(tmp_path / "project")
    transport = ScriptedTransport()
    expect_approved_steps(transport)
    transport.expect(
        "POST",
        f"{BASE}{PUBLICATION}",
        status=503,
        body={"detail": {"code": "KNOWLEDGE_PACKAGE_SERVICE_UNAVAILABLE"}},
    )

    run = run_ut(["--lang", "it", "init"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    lines = run.output.splitlines()
    assert (
        lines.count(
            "La cartella di conoscenza non è stata aggiornata "
            "(KNOWLEDGE_PACKAGE_SERVICE_UNAVAILABLE): il percorso continua, e puoi scaricarla più "
            "tardi con `ut package publish`."
        )
        == 1
    )
    assert "Il prossimo comando è `ut design`" in run.output
    transport.assert_done()


@pytest.mark.parametrize(
    ("language", "words"),
    [
        (
            "it",
            "si ferma dopo il passo indicato: brief (Brief), team (Prospettive), twins (User "
            "Twin) oppure requirements (Definizione)",
        ),
        (
            "en",
            "stop after the named step: brief (Brief), team (Perspectives), twins (User Twin) or "
            "requirements (Definition)",
        ),
    ],
)
def test_the_help_of_the_command_is_translated(tmp_path: Path, language: str, words: str) -> None:
    run = run_ut(["--lang", language, "init", "--help"], tmp_path, transport=ScriptedTransport())

    assert run.status == 0
    assert words in " ".join(run.output.split())


@pytest.mark.parametrize(
    ("language", "words"),
    [
        ("it", "Crea un progetto e lo porta dall'idea alla Definizione approvata"),
        ("en", "Create a project and take it from the idea to an approved Definition"),
    ],
)
def test_the_list_of_commands_says_where_init_takes_the_project(
    tmp_path: Path, language: str, words: str
) -> None:
    run = run_ut(["--lang", language, "--help"], tmp_path, transport=ScriptedTransport())

    assert run.status == 0
    assert words in " ".join(run.output.split())
