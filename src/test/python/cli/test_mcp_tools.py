from __future__ import annotations

import copy
import importlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, ModuleType

import pytest

from orchestwin.cli import costs, flows, jobs
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.flows import changes as changes_flow
from orchestwin.cli.mcp import tools as tools_module
from orchestwin.cli.mcp.knowledge import Knowledge
from orchestwin.cli.mcp.protocol import RpcError
from orchestwin.cli.mcp.server import quiet_context
from orchestwin.cli.mcp.tools import Tools
from orchestwin.cli.messages import text
from orchestwin.cli.project import ProjectFolder
from src.test.python.knowledge.knowledge_fixtures import (
    ALIGNED_COMMIT,
    PENDING_COMMIT,
    RECEPTION_TWIN,
    VOLUNTEER_TWIN,
    change_run,
    real_documents,
    state_sources,
)

from .support.folders import (
    acceptance_run_document,
    learned_entries,
    legacy_task,
    origin_tasks,
    partial_archive,
    valid_archive,
)
from .support.terminal import (
    PROJECT_ID,
    PROJECT_NAME,
    Terminal,
    command_context,
    link_folder,
    store_session,
    terminal,
)
from .support.transports import API, NoNetwork, ScriptedTransport
from .test_mcp_knowledge import (
    RECEPTION,
    STAGES,
    VOLUNTEERS,
    declare_learning,
    declare_tests,
    edit_json,
    learning_folder,
    linked,
    runs_newest_first,
    schema_two_folder,
    state_folder,
    with_archive,
    with_learning,
    with_state_tasks,
    with_test_runs,
    without_learning,
)

BASE = f"{API}/projects/{PROJECT_ID}"
READINESS = f"{BASE}/user-modeling/readiness"
SNAPSHOT = f"{BASE}/user-modeling/snapshots/current"
CONVERSATION = f"{BASE}/user-twins/{RECEPTION_TWIN}/conversation"
TURNS = f"{CONVERSATION}/turns"
CHANGES = f"{BASE}/code-changes"
REVIEWS = f"{CHANGES}/{PENDING_COMMIT}/reviews"
MODEL_FAILURE = {"detail": {"code": "INVALID_TWIN_CHAT_OUTPUT", "stage": "MODEL_PROPOSAL"}}
DIFF = "diff --git a/src/app.js b/src/app.js\n@@ -1 +1 @@\n-a\n+b\n"
COMMIT = changes_flow.Commit(
    hash=PENDING_COMMIT,
    parent=ALIGNED_COMMIT,
    committed_at="2026-09-28T11:00:00+00:00",
    author="Alex Testa",
    message="Controllo del nome vuoto",
    files=(changes_flow.ChangedFile("src/app.js", "MODIFIED", 12, 3),),
)
NOT_LINKED = (
    "This folder is not linked to a project of the Studio, so the MCP server has no knowledge "
    "folder to offer. Start it from the folder of the project, or with --project-dir, or create "
    "the project with `ut init`. (PROJECT_NOT_LINKED)"
)
SPEND_IT = (
    "Lo strumento {tool} spende sul modello, ma il server è stato avviato senza --spend. Per "
    "permetterlo avvia il server con `ut mcp --spend`; per Claude Code: `claude mcp add "
    "orchestwin-twins -- ut mcp --spend`. (SPEND_REQUIRED)"
)
TEST_FLOW = "orchestwin.cli.flows.test_run"
TOOL_NAMES = [
    "project_state",
    "list_twins",
    "get_twin",
    "get_requirements",
    "get_design",
    "get_feedback",
    "ask_twin",
    "review_changes",
    "get_test_results",
    "run_tests",
    "get_tasks",
]
RUN_FOLDER = ("tests", "20260929-100000")


@dataclass(frozen=True, slots=True)
class FakeTestRequest:
    application: Mapping[str, object] | None = None
    browsers: tuple[str, ...] = ("all",)
    criteria: tuple[str, ...] = ()
    new_plan: bool = False
    review: bool = True
    max_usd: float = 2.0


@dataclass(frozen=True, slots=True)
class FakeOutcome:
    run: Mapping[str, object]
    critiques: tuple[Mapping[str, object], ...]
    folder: Path
    report: Path


def fake_test_flow(
    monkeypatch: pytest.MonkeyPatch,
    *,
    outcome: FakeOutcome | None = None,
    failure: CliError | None = None,
) -> list[tuple[object, object]]:
    calls: list[tuple[object, object]] = []

    def execute(context: object, request: object) -> FakeOutcome | None:
        calls.append((context, request))
        if failure is not None:
            raise failure
        return outcome

    try:
        module = importlib.import_module(TEST_FLOW)
    except ModuleNotFoundError as error:
        if error.name != TEST_FLOW:
            raise
        module = ModuleType(TEST_FLOW)
        module.TestRequest = FakeTestRequest
        monkeypatch.setitem(sys.modules, TEST_FLOW, module)
        monkeypatch.setattr(flows, "test_run", module, raising=False)
    monkeypatch.setattr(module, "execute", execute, raising=False)
    return calls


def request_fields(request: object) -> tuple[object, ...]:
    return tuple(
        getattr(request, name)
        for name in ("application", "browsers", "criteria", "new_plan", "review")
    )


def outcome_of(project_root: Path) -> tuple[FakeOutcome, dict[str, object]]:
    document = acceptance_run_document()
    folder = project_root.joinpath(".orchestwin", *RUN_FOLDER)
    outcome = FakeOutcome(
        run=MappingProxyType(document),
        critiques=tuple(MappingProxyType(item) for item in document["critiques"]),
        folder=folder,
        report=folder / "report.html",
    )
    return outcome, document


def build(
    tmp_path: Path,
    *,
    spend: bool = False,
    language: str = "en",
    transport: object = None,
) -> tuple[Tools, Terminal]:
    bundle = terminal(tmp_path, transport=NoNetwork() if transport is None else transport)
    context = quiet_context(command_context(bundle.environment, language=language))
    return Tools(context, spend=spend), bundle


def folder_language(project: ProjectFolder, language: str | None) -> None:
    def change(document: dict) -> None:
        document["project"]["language"] = language

    edit_json(project.knowledge / "orchestwin.json", change)


def run(tools: Tools, name: str, **arguments: object) -> dict[str, object]:
    result = tools.call(name, arguments)
    assert result["isError"] is False, result
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    return result["structuredContent"]


def refused(tools: Tools, name: str, **arguments: object) -> dict[str, object]:
    result = tools.call(name, arguments)
    assert result["isError"] is True, result
    structured = result["structuredContent"]
    assert result["content"] == [{"type": "text", "text": structured["message"]}]
    return structured


def state_document(project_knowledge: Path) -> dict[str, object]:
    return json.loads((project_knowledge / "state" / "state.json").read_bytes().decode("utf-8"))


def twin_snapshot() -> dict[str, object]:
    return copy.deepcopy(real_documents()["twins"])


def reception_version() -> str:
    return str(twin_snapshot()["snapshot"]["twin_versions"][0]["id"])


def turn(question: str, reply: str) -> dict[str, object]:
    return {
        "id": "00000000-0000-4000-8000-00000000c001",
        "ordinal": 1,
        "question": question,
        "reply": reply,
        "insights": [
            {
                "kind": "NEED",
                "text": "Vuole chiudere il conto in fretta.",
                "confidence": 0.6,
                "grounded_on": ["user_twin.goals"],
            }
        ],
    }


def conversation(turns: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {
        "snapshot": {
            "id": "00000000-0000-4000-8000-00000000c000",
            "twin_id": RECEPTION_TWIN,
            "twin_version_id": reception_version(),
            "turns": list(turns),
        }
    }


def approved_twins(transport: ScriptedTransport) -> ScriptedTransport:
    return transport.expect(
        "GET", READINESS, body={"snapshot_exists": True, "approved_current_snapshot": True}
    ).expect("GET", SNAPSHOT, body=twin_snapshot())


def fake_git(
    monkeypatch: pytest.MonkeyPatch,
    *,
    root: Path | None,
    head: str | None = PENDING_COMMIT,
    revisions: Mapping[str, str] | None = None,
    commits: Sequence[changes_flow.Commit] = (COMMIT,),
) -> list[tuple[object, ...]]:
    calls: list[tuple[object, ...]] = []
    known = {f"{PENDING_COMMIT}^": ALIGNED_COMMIT} if revisions is None else dict(revisions)

    def repository_root(context: object, start: Path) -> Path | None:
        calls.append(("root", start))
        return root

    def current(context: object, folder: Path) -> str | None:
        calls.append(("head",))
        return head

    def resolve(context: object, folder: Path, revision: str) -> str | None:
        calls.append(("resolve", revision))
        return known.get(revision)

    def commits_after(
        context: object, folder: Path, since: str | None, *, limit: int = 50
    ) -> tuple[changes_flow.Commit, ...]:
        calls.append(("commits_after", since, limit))
        return tuple(commits)

    def diff_of(context: object, folder: Path, commit: changes_flow.Commit) -> str:
        calls.append(("diff_of", commit.hash))
        return DIFF

    monkeypatch.setattr(changes_flow, "repository_root", repository_root)
    monkeypatch.setattr(changes_flow, "head", current)
    monkeypatch.setattr(changes_flow, "resolve", resolve)
    monkeypatch.setattr(changes_flow, "commits_after", commits_after)
    monkeypatch.setattr(changes_flow, "diff_of", diff_of)
    return calls


def recorded_change() -> dict[str, object]:
    return {
        "status": "RECORDED",
        "change": {
            "commit": PENDING_COMMIT,
            "parent": ALIGNED_COMMIT,
            "committed_at": "2026-09-28T11:00:00+00:00",
            "author": "Alex Testa",
            "message": "Controllo del nome vuoto",
            "files": [{"path": "src/app.js", "kind": "MODIFIED", "added": 12, "removed": 3}],
            "recorded_at": "2026-09-29T09:00:00+00:00",
            "review": None,
            "decision": None,
        },
    }


def test_the_project_state_joins_the_link_the_folder_and_the_development_state(
    tmp_path: Path,
) -> None:
    project = state_folder(tmp_path)
    tools, _ = build(tmp_path)
    sources = state_sources()

    document = run(tools, "project_state")

    state = state_document(project.knowledge)
    reference = state["reference"]
    assert reference["requirements"]["version_number"] == 2
    assert (reference["design"]["version_number"], reference["design"]["alternative_code"]) == (
        4,
        "DES-002",
    )
    assert document == {
        "project": {
            "id": PROJECT_ID,
            "name": PROJECT_NAME,
            "mode": "DESIGN_ONLY",
            "language": "it",
            "studio": "http://127.0.0.1:8000",
        },
        "folder": {
            "schema_version": 3,
            "version_number": 1,
            "approved_stages": list(STAGES),
            "pending_stage": None,
            "complete": True,
        },
        "reference": reference,
        "aligned": dict(sources.aligned),
        "pending_changes": [
            {
                "commit": PENDING_COMMIT,
                "committed_at": "2026-09-28T11:00:00+00:00",
                "message": "Controllo del nome vuoto",
                "files": 2,
                "verdict": "CODE_DRIFT",
                "decision": "CODE_TASKS",
            }
        ],
        "stale_reviews": 0,
        "open_tasks": [task for task in state["tasks"] if task["status"] == "OPEN"],
        "next": "Compiti aperti per il codice: 1 (TSK-001). Realizzali, fai il commit, poi "
        "lancia `ut align`.",
    }
    assert [task["code"] for task in document["open_tasks"]] == [sources.tasks[0]["code"]]


OPEN_TASKS_NEXT = {
    "en": "Open tasks for the code: 1 (TSK-001). Carry them out, commit, then launch `ut align`.",
    "it": "Compiti aperti per il codice: 1 (TSK-001). Realizzali, fai il commit, poi lancia "
    "`ut align`.",
}


@pytest.mark.parametrize(
    ("folder", "link", "command", "expected"),
    [
        ("en-US", "it", "it", "en"),
        ("it", "en", "en", "it"),
        (None, "en-US", "it", "en"),
        (None, None, "it", "it"),
        (None, None, "en", "en"),
    ],
)
def test_the_next_step_speaks_the_language_of_the_folder_then_of_the_link_then_of_the_command(
    tmp_path: Path, folder: str | None, link: str | None, command: str, expected: str
) -> None:
    project = state_folder(tmp_path, language=link)
    folder_language(project, folder)
    tools, _ = build(tmp_path, language=command)

    assert run(tools, "project_state")["next"] == OPEN_TASKS_NEXT[expected]


@pytest.mark.parametrize(
    ("through", "language", "sentence"),
    [
        (
            "brief",
            "it",
            "Il prossimo passo da approvare è «Prospettive»: continua con `ut init`.",
        ),
        ("twins", "en", 'The next step to approve is "Definition": go on with `ut init`.'),
        (
            "requirements",
            "it",
            "Il prossimo passo da approvare è «Design e valutazione»: continua con `ut design`.",
        ),
    ],
)
def test_a_partial_folder_names_the_next_step_and_its_command(
    tmp_path: Path, through: str, language: str, sentence: str
) -> None:
    project = with_archive(tmp_path, partial_archive(through=through), language=language)
    folder_language(project, language)
    tools, _ = build(tmp_path)

    document = run(tools, "project_state")

    assert document["folder"] == {
        "schema_version": 3,
        "version_number": 1,
        "approved_stages": list(STAGES[: STAGES.index(through) + 1]),
        "pending_stage": STAGES[STAGES.index(through) + 1],
        "complete": False,
    }
    reference = document["reference"]
    assert reference["design"] is None
    assert (reference["requirements"] is None) is (through != "requirements")
    assert (document["aligned"], document["pending_changes"], document["open_tasks"]) == (
        None,
        [],
        [],
    )
    assert document["next"] == sentence


def test_a_complete_folder_without_commits_says_to_develop_and_align(tmp_path: Path) -> None:
    with_archive(tmp_path, valid_archive())
    tools, _ = build(tmp_path)

    document = run(tools, "project_state")

    assert (document["aligned"], document["pending_changes"], document["open_tasks"]) == (
        None,
        [],
        [],
    )
    assert document["next"] == (
        "Il design è approvato e nessun commit è ancora registrato: sviluppa il codice, poi "
        "lancia `ut align` per far rivedere i commit ai twin."
    )


def test_a_schema_two_folder_has_no_development_state(tmp_path: Path) -> None:
    schema_two_folder(tmp_path)
    tools, _ = build(tmp_path)

    document = run(tools, "project_state")

    assert document["folder"] == {
        "schema_version": 2,
        "version_number": 1,
        "approved_stages": list(STAGES),
        "pending_stage": None,
        "complete": True,
    }
    assert (document["reference"], document["aligned"]) == (None, None)
    assert (document["pending_changes"], document["open_tasks"]) == ([], [])
    assert document["next"] == (
        "Il design è approvato, ma questa cartella non ha lo stato dello sviluppo: scarica la "
        "versione nuova con `ut package publish`, poi dopo i commit lancia `ut align`."
    )
    assert run(tools, "get_feedback") == {"runs": [], "design_reviews": 0}


def test_without_the_knowledge_folder_only_the_project_state_answers(tmp_path: Path) -> None:
    linked(tmp_path)
    tools, _ = build(tmp_path)

    document = run(tools, "project_state")
    missing = refused(tools, "list_twins")

    assert document["folder"] is None
    assert (document["reference"], document["aligned"]) == (None, None)
    assert (document["pending_changes"], document["open_tasks"]) == ([], [])
    assert document["next"] == (
        "Qui non c'è ancora la cartella di conoscenza: continua con `ut init` oppure, se il "
        "brief è già approvato, scaricala con `ut package publish`."
    )
    assert missing == {
        "code": "FOLDER_MISSING",
        "message": "La cartella di conoscenza orchestwin/ non c'è ancora: dopo l'approvazione "
        "del brief scaricala con `ut package publish`. (FOLDER_MISSING)",
    }
    for name in ("get_twin", "get_requirements", "get_design", "get_feedback"):
        arguments = {"twin": "1"} if name == "get_twin" else {}
        assert refused(tools, name, **arguments)["code"] == "FOLDER_MISSING"


def ready_knowledge(tmp_path: Path) -> Knowledge:
    return Knowledge(
        root=tmp_path,
        manifest={},
        schema_version=3,
        version_number=1,
        approved=STAGES,
        pending=None,
    )


def change(commit: str, decision: str | None) -> dict[str, object]:
    return {
        "commit": commit,
        "committed_at": "2026-09-28T11:00:00+00:00",
        "message": "Riga uno\nRiga due",
        "files": [],
        "review": None,
        "decision": None if decision is None else {"kind": decision},
    }


@pytest.mark.parametrize(
    ("changes", "aligned", "tasks", "sentence"),
    [
        (
            [change(PENDING_COMMIT, None), change(ALIGNED_COMMIT, "ALIGNED")],
            {"commit": ALIGNED_COMMIT},
            [{"code": "TSK-001"}],
            "Commit dopo il punto allineato ancora da rivedere o decidere: 1. Lancia `ut align`.",
        ),
        (
            [change(ALIGNED_COMMIT, "ALIGNED")],
            {"commit": ALIGNED_COMMIT},
            [],
            "Il codice è allineato al design approvato al commit 9d8e7f6: continua a sviluppare "
            "e lancia `ut align` dopo i prossimi commit.",
        ),
        (
            [change(PENDING_COMMIT, "DISMISSED"), change(ALIGNED_COMMIT, "DESIGN_CHANGE")],
            None,
            [],
            "Ci sono commit registrati, ma nessuno è ancora segnato come allineato: lancia "
            "`ut align` per decidere.",
        ),
        (
            [change(PENDING_COMMIT, "CODE_TASKS"), change(ALIGNED_COMMIT, "ALIGNED")],
            {"commit": ALIGNED_COMMIT},
            [{"code": "TSK-001"}, {"code": "TSK-002"}],
            "Compiti aperti per il codice: 2 (TSK-001, TSK-002). Realizzali, fai il commit, poi "
            "lancia `ut align`.",
        ),
    ],
)
def test_the_next_step_follows_the_development_state(
    tmp_path: Path,
    changes: list[dict[str, object]],
    aligned: dict[str, object] | None,
    tasks: list[dict[str, object]],
    sentence: str,
) -> None:
    pending = tools_module.pending_changes(changes, aligned)
    state = {"changes": changes, "aligned": aligned, "tasks": tasks}

    found = tools_module.next_step(
        "it", ready_knowledge(tmp_path), state, changes, pending, tasks, aligned
    )

    assert found == sentence
    assert all(item["message"] == "Riga uno" for item in pending)


def test_the_pending_changes_are_the_ones_after_the_aligned_commit() -> None:
    changes = [change("a" * 40, None), change("b" * 40, "DISMISSED"), change("c" * 40, "ALIGNED")]

    assert [item["commit"] for item in tools_module.pending_changes(changes, None)] == [
        "a" * 40,
        "b" * 40,
        "c" * 40,
    ]
    assert [
        item["commit"] for item in tools_module.pending_changes(changes, {"commit": "c" * 40})
    ] == ["a" * 40, "b" * 40]
    assert tools_module.pending_changes(changes, {"commit": "a" * 40}) == []


def test_the_twins_come_from_the_folder_with_their_numbers(tmp_path: Path) -> None:
    state_folder(tmp_path)
    tools, _ = build(tmp_path)

    assert run(tools, "list_twins") == {
        "twins": [
            {
                "number": 1,
                "twin_id": RECEPTION_TWIN,
                "name": RECEPTION,
                "role": RECEPTION,
                "wants": "Verificare la presenza degli ospiti",
                "label": "1.0",
                "learned_observations": 0,
            },
            {
                "number": 2,
                "twin_id": VOLUNTEER_TWIN,
                "name": VOLUNTEERS,
                "role": VOLUNTEERS,
                "wants": "Aggiungere ospiti per nome",
                "label": "1.0",
                "learned_observations": 0,
            },
        ]
    }


@pytest.mark.parametrize("value", ["2", 2, "org", "ORGANIZZATORI  volontari", " organizzatori "])
def test_a_twin_is_chosen_by_number_or_by_the_beginning_of_its_name(
    tmp_path: Path, value: object
) -> None:
    state_folder(tmp_path)
    tools, _ = build(tmp_path)

    twin = run(tools, "get_twin", twin=value)["twin"]

    assert (twin["number"], twin["twin_id"], twin["name"], twin["role"]) == (
        2,
        VOLUNTEER_TWIN,
        VOLUNTEERS,
        VOLUNTEERS,
    )
    assert twin["goals"] == [
        "Aggiungere ospiti per nome",
        "Vedere la lista aggiornata",
        "Evitare nomi vuoti",
    ]
    assert twin["frustrations"] == ["Perdita di informazioni", "Conteggio errato"]
    assert twin["pain_points"] == ["Lista su carta", "Dati persi"]
    assert len(twin["context_of_use"]) == 1
    assert twin["context_of_use"][0].startswith("Utilizza l'applicazione durante gli eventi")
    assert len(twin["observations"]) == 16
    assert twin["observations"]["expertise"] == {"value": None, "status": "MODEL_INFERRED"}
    assert twin["observations"]["technical_literacy"] == {
        "value": "Bassa",
        "status": "MODEL_INFERRED",
    }
    assert twin["observations"]["goals"] == {
        "value": twin["goals"],
        "status": "MODEL_INFERRED",
    }


def test_a_twin_that_matches_nothing_or_many_is_a_tool_error(tmp_path: Path) -> None:
    project = state_folder(tmp_path)
    tools, _ = build(tmp_path)
    nothing = refused(tools, "get_twin", twin="zzz")
    number = refused(tools, "get_twin", twin="3")

    def rename(document: dict) -> None:
        versions = document["snapshot"]["twin_versions"]
        versions[0]["profile"]["name"] = "Cameriere di sala"
        versions[1]["profile"]["name"] = "Cameriere del turno serale"

    edit_json(project.knowledge / "twins" / "twins.json", rename)
    many = refused(tools, "get_twin", twin="cam")

    assert nothing == {
        "code": "TWIN_NOT_FOUND",
        "message": "Nessun twin corrisponde a «zzz». I twin sono: 1. Addetti all'accoglienza; "
        "2. Organizzatori volontari. (TWIN_NOT_FOUND)",
        "twins": [{"number": 1, "name": RECEPTION}, {"number": 2, "name": VOLUNTEERS}],
    }
    assert number["code"] == "TWIN_NOT_FOUND"
    assert many == {
        "code": "TWIN_AMBIGUOUS",
        "message": "Più twin corrispondono a «cam»: 1. Cameriere di sala; 2. Cameriere del "
        "turno serale. Indica il numero. (TWIN_AMBIGUOUS)",
        "twins": [
            {"number": 1, "name": "Cameriere di sala"},
            {"number": 2, "name": "Cameriere del turno serale"},
        ],
    }


def test_the_twins_of_a_folder_without_them_are_a_stage_not_approved(tmp_path: Path) -> None:
    with_archive(tmp_path, partial_archive(through="team"))
    tools, _ = build(tmp_path)

    assert refused(tools, "list_twins") == {
        "code": "STAGE_NOT_APPROVED",
        "message": "Il passo «User Twin» non è ancora approvato, quindi la cartella di "
        "conoscenza non lo contiene: continua con `ut init`. (STAGE_NOT_APPROVED)",
        "stage": "twins",
    }
    assert refused(tools, "get_twin", twin="1")["stage"] == "twins"


def test_the_requirements_come_whole_or_selected_by_their_codes(tmp_path: Path) -> None:
    state_folder(tmp_path)
    tools, _ = build(tmp_path)

    whole = run(tools, "get_requirements")
    empty = run(tools, "get_requirements", codes=[])
    selected = run(tools, "get_requirements", codes=["req-001", "XYZ-9"])

    assert whole == empty
    assert whole["version_number"] == 2
    assert [item["code"] for item in whole["requirements"]] == [
        f"REQ-00{number}" for number in range(1, 8)
    ]
    assert [item["code"] for item in whole["user_stories"]] == ["USR-001", "USR-002"]
    assert [item["code"] for item in whole["acceptance_criteria"]] == ["AC-001"]
    assert "unknown_codes" not in whole
    assert selected["version_number"] == 2
    assert selected["schema_version"] == 1
    assert selected["needs"] == []
    assert [item["code"] for item in selected["requirements"]] == [
        "REQ-001",
        "REQ-002",
        "REQ-003",
        "REQ-004",
    ]
    assert selected["user_stories"] == whole["user_stories"]
    assert selected["acceptance_criteria"] == whole["acceptance_criteria"]
    assert selected["unknown_codes"] == ["XYZ-9"]


def test_the_requirements_of_a_folder_without_them_are_a_stage_not_approved(
    tmp_path: Path,
) -> None:
    project = with_archive(tmp_path, partial_archive(through="twins"), language="en")
    folder_language(project, "en")
    tools, _ = build(tmp_path)

    assert refused(tools, "get_requirements") == {
        "code": "STAGE_NOT_APPROVED",
        "message": 'The step "Definition" is not approved yet, so the knowledge folder does '
        "not hold it: go on with `ut init`. (STAGE_NOT_APPROVED)",
        "stage": "requirements",
    }


def test_the_design_gives_the_chosen_alternative_its_workflows_and_its_screens(
    tmp_path: Path,
) -> None:
    state_folder(tmp_path)
    tools, _ = build(tmp_path)

    document = run(tools, "get_design")

    chosen = document["chosen"]
    assert document["version_number"] == 4
    assert (chosen["code"], chosen["title"]) == ("DES-002", "Event Guest Manager")
    assert chosen["summary"].startswith("A comprehensive guest list manager")
    assert chosen["workflows"] == [
        {
            "code": "FLOW-001",
            "steps": [
                "User adds guest name in the input area",
                "System validates name and highlights duplicates",
                "User confirms addition",
                "Guest name appears in the table list",
            ],
        }
    ]
    assert chosen["screens"][1] == {
        "code": "SCR-002",
        "title": "Aggiungi Ospite",
        "elements": ["AGGIUNGI OSPITE", "Nome ospite", "Conferma", "Annulla"],
    }
    assert [screen["code"] for screen in chosen["screens"]] == ["SCR-001", "SCR-002", "SCR-003"]
    assert document["alternatives"] == [
        {"code": "DES-001", "title": "Guest Register Pro", "chosen": False},
        {"code": "DES-002", "title": "Event Guest Manager", "chosen": True},
    ]


def test_one_screen_comes_with_the_transitions_from_and_to_it(tmp_path: Path) -> None:
    state_folder(tmp_path)
    tools, _ = build(tmp_path)

    screens = run(tools, "get_design", screen="scr-003")["chosen"]["screens"]

    assert screens == [
        {
            "code": "SCR-003",
            "title": "Conferma Aggiunta",
            "elements": [
                "OSPITE AGGIUNTO CON SUCCESSO",
                "Il nome 'Marco Rossi' è stato aggiunto alla lista.",
                "Continua ad aggiungere ospiti",
                "Torna alla lista",
            ],
            "transitions": [
                {
                    "code": "TRN-002",
                    "from": "SCR-002",
                    "to": "SCR-003",
                    "trigger": "Conferma",
                    "outcome": "Conferma",
                },
                {
                    "code": "TRN-004",
                    "from": "SCR-003",
                    "to": "SCR-002",
                    "trigger": "Continua ad aggiungere ospiti",
                    "outcome": "Continua ad aggiungere ospiti",
                },
                {
                    "code": "TRN-005",
                    "from": "SCR-003",
                    "to": "SCR-001",
                    "trigger": "Torna alla lista",
                    "outcome": "Torna alla lista",
                },
            ],
        }
    ]


def test_an_unknown_screen_is_a_tool_error_that_lists_the_screens(tmp_path: Path) -> None:
    state_folder(tmp_path)
    tools, _ = build(tmp_path)

    assert refused(tools, "get_design", screen="SCR-009") == {
        "code": "SCREEN_NOT_FOUND",
        "message": "Il design scelto non ha la schermata SCR-009. Schermate: SCR-001, SCR-002, "
        "SCR-003. (SCREEN_NOT_FOUND)",
        "screens": ["SCR-001", "SCR-002", "SCR-003"],
    }


def test_the_design_of_a_folder_without_it_is_a_stage_not_approved(tmp_path: Path) -> None:
    with_archive(tmp_path, partial_archive(through="requirements"))
    tools, _ = build(tmp_path)

    assert refused(tools, "get_design") == {
        "code": "STAGE_NOT_APPROVED",
        "message": "Il passo «Design e valutazione» non è ancora approvato, quindi la cartella "
        "di conoscenza non lo contiene: continua con `ut design`. (STAGE_NOT_APPROVED)",
        "stage": "design",
    }


def test_the_feedback_gives_the_latest_runs_filtered_by_commit(tmp_path: Path) -> None:
    state_folder(tmp_path)
    tools, _ = build(tmp_path)

    latest = run(tools, "get_feedback")
    one = run(tools, "get_feedback", commit="4F2A9C1", limit=1)
    other = run(tools, "get_feedback", commit=ALIGNED_COMMIT[:12], limit=2.0)

    assert latest == {"runs": [change_run()], "design_reviews": 0}
    assert one == latest
    assert other == {"runs": [], "design_reviews": 0}


def test_a_folder_that_cannot_be_read_is_a_tool_error(tmp_path: Path) -> None:
    project = state_folder(tmp_path)
    tools, _ = build(tmp_path)
    (project.knowledge / "orchestwin.json").write_bytes(b"{")
    unreadable = refused(tools, "project_state")
    (project.knowledge / "orchestwin.json").write_bytes(
        json.dumps({"kind": "orchestwin.knowledge-folder", "schema_version": 9}).encode("utf-8")
    )
    unsupported = refused(tools, "get_feedback")

    assert unreadable == {
        "code": "FOLDER_UNREADABLE",
        "message": "La cartella di conoscenza non si legge (orchestwin/orchestwin.json): "
        "scaricala di nuovo con `ut package pull`. (FOLDER_UNREADABLE)",
    }
    assert unsupported == {
        "code": "FOLDER_SCHEMA_UNSUPPORTED",
        "message": "La cartella di conoscenza usa uno schema che questa versione di ut non "
        "conosce (9): aggiorna ut oppure scarica di nuovo la cartella con `ut package pull`. "
        "(FOLDER_SCHEMA_UNSUPPORTED)",
    }


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("project_state", {}),
        ("list_twins", {}),
        ("get_twin", {"twin": "1"}),
        ("get_requirements", {}),
        ("get_design", {}),
        ("get_feedback", {}),
        ("ask_twin", {"twin": "1", "question": "Ciao?"}),
        ("review_changes", {}),
        ("get_test_results", {}),
        ("run_tests", {}),
        ("get_tasks", {}),
    ],
)
def test_without_a_linked_folder_every_tool_answers_the_same_error(
    tmp_path: Path, name: str, arguments: dict[str, object]
) -> None:
    tools, _ = build(tmp_path, spend=True)

    assert refused(tools, name, **arguments) == {
        "code": "PROJECT_NOT_LINKED",
        "message": NOT_LINKED,
    }


def test_a_link_that_cannot_be_read_is_a_tool_error(tmp_path: Path) -> None:
    project = state_folder(tmp_path)
    (project.local / "project.json").write_bytes(b"{}")
    tools, _ = build(tmp_path)

    found = refused(tools, "project_state")

    assert found["code"] == "PROJECT_LINK_INVALID"
    assert found["message"].startswith("The file ")
    assert found["message"].endswith(
        "cannot be read as the link to a project. Check it, or link the folder again. "
        "(PROJECT_LINK_INVALID)"
    )


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("ask_twin", {"twin": "1", "question": "Come lavori?"}),
        ("review_changes", {}),
        ("run_tests", {"application": {"kind": "URL", "address": "http://127.0.0.1:5173/"}}),
    ],
)
def test_paid_tools_without_spend_are_refused_in_the_language_of_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, arguments: dict[str, object]
) -> None:
    state_folder(tmp_path)
    calls = fake_test_flow(monkeypatch)
    tools, _ = build(tmp_path)

    assert refused(tools, name, **arguments) == {
        "code": "SPEND_REQUIRED",
        "message": SPEND_IT.format(tool=name),
        "tool": name,
    }
    assert calls == []


def test_paid_tools_without_spend_are_refused_in_english_for_an_english_project(
    tmp_path: Path,
) -> None:
    project = state_folder(tmp_path, language="en")
    folder_language(project, "en")
    tools, _ = build(tmp_path, language="it")

    assert refused(tools, "review_changes", commit="HEAD")["message"] == (
        "The tool review_changes spends on the model, but the server was started without "
        "--spend. To allow it, start the server with `ut mcp --spend`; for Claude Code: "
        "`claude mcp add orchestwin-twins -- ut mcp --spend`. (SPEND_REQUIRED)"
    )


def test_the_descriptions_of_the_paid_tools_carry_the_estimates(tmp_path: Path) -> None:
    free, _ = build(tmp_path / "free")
    paid, _ = build(tmp_path / "paid", spend=True, language="it")

    listed = {tool["name"]: tool for tool in free.definitions()}
    italian = {tool["name"]: tool for tool in paid.definitions()}

    assert listed["ask_twin"]["description"] == (
        "Ask a User Twin a question in the Studio and return the answer simulated by the model: "
        "a hypothesis to weigh, not the opinion of a real person. Paid, about 0.02-0.05 USD per "
        "question. Not available now: the server was started without --spend."
    )
    assert (
        "about 0.15-0.25 USD per twin plus 0.15-0.30 USD for the verdict"
        in (listed["review_changes"]["description"])
    )
    assert listed["review_changes"]["description"].endswith(
        "Not available now: the server was started without --spend."
    )
    assert "circa 0,02-0,05 USD a domanda." in italian["ask_twin"]["description"]
    assert (
        "circa 0,15-0,25 USD per twin più 0,15-0,30 USD per il verdetto"
        in (italian["review_changes"]["description"])
    )
    assert not italian["review_changes"]["description"].endswith("--spend.")
    assert listed["project_state"]["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert listed["ask_twin"]["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }


def test_without_the_estimates_of_a_review_the_description_has_no_figures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    estimates = {
        name: value
        for name, value in costs.ESTIMATES.items()
        if name not in ("CODE_CHANGE_REVIEW", "CODE_ALIGNMENT")
    }
    monkeypatch.setattr(costs, "ESTIMATES", MappingProxyType(estimates))
    tools, _ = build(tmp_path, spend=True)

    listed = {tool["name"]: tool for tool in tools.definitions()}

    assert listed["review_changes"]["description"] == (
        "Record a commit in the Studio (HEAD when not given) and have the twins criticize it, "
        "with the verdict of alignment with the approved design and requirements. Paid. The "
        "decision stays with the owner of the project, through `ut align`."
    )
    assert tools_module.review_estimate(2) is None


def test_asking_a_twin_sends_the_question_with_the_turns_of_its_version(tmp_path: Path) -> None:
    state_folder(tmp_path)
    store_session(tmp_path)
    earlier = turn("Prima domanda?", "Prima risposta.")
    answered = {**turn("Come lavori?", "Lavoro di sera."), "ordinal": 2}
    transport = approved_twins(ScriptedTransport())
    transport.expect("GET", CONVERSATION, body=conversation([earlier]))
    transport.expect(
        "POST",
        TURNS,
        status=201,
        body={"status": "TWIN_TURN_RECORDED", **conversation([earlier, answered])},
    )
    tools, bundle = build(tmp_path, spend=True, transport=transport)

    document = run(tools, "ask_twin", twin="add", question="  Come   lavori? ")

    assert document == {
        "twin": RECEPTION,
        "reply": "Lavoro di sera.",
        "insights": answered["insights"],
        "estimated_usd": [0.02, 0.05],
    }
    assert transport.requests("POST", TURNS)[0].json() == {
        "question": "Come lavori?",
        "expected_turn_count": 1,
    }
    transport.assert_done()
    assert bundle.output == ""


def test_a_conversation_of_another_version_counts_no_turn(tmp_path: Path) -> None:
    state_folder(tmp_path)
    store_session(tmp_path)
    older = conversation([turn("Vecchia?", "Vecchia.")])
    older["snapshot"]["twin_version_id"] = "00000000-0000-4000-8000-00000000beef"
    transport = approved_twins(ScriptedTransport())
    transport.expect("GET", CONVERSATION, body=older)
    transport.expect(
        "POST",
        TURNS,
        status=201,
        body={"status": "TWIN_TURN_RECORDED", **conversation([turn("Nuova?", "Nuova.")])},
    )
    tools, _ = build(tmp_path, spend=True, transport=transport)

    document = run(tools, "ask_twin", twin=1, question="Nuova?")

    assert document["reply"] == "Nuova."
    assert transport.requests("POST", TURNS)[0].json()["expected_turn_count"] == 0


@pytest.mark.parametrize(
    ("status", "body", "code", "message"),
    [
        (
            502,
            MODEL_FAILURE,
            "INVALID_TWIN_CHAT_OUTPUT",
            "Addetti all'accoglienza non ha potuto rispondere: il modello non ha dato una "
            "risposta valida oppure non era raggiungibile (INVALID_TWIN_CHAT_OUTPUT). Puoi rifare "
            "la domanda, ma è una nuova spesa.",
        ),
        (
            503,
            {"detail": {"code": "TWIN_CHAT_MODEL_NOT_CONFIGURED"}},
            "TWIN_CHAT_MODEL_NOT_CONFIGURED",
            "Il modello che dà voce ai twin non è collegato allo Studio: chi gestisce lo Studio "
            "può collegarlo. (TWIN_CHAT_MODEL_NOT_CONFIGURED)",
        ),
        (
            409,
            {"detail": {"code": "TWIN_CONVERSATION_CHANGED"}},
            "TWIN_CONVERSATION_CHANGED",
            "Nel frattempo la conversazione con il twin è cambiata, forse dalla pagina dello "
            "Studio: rifai la domanda. (TWIN_CONVERSATION_CHANGED)",
        ),
        (
            402,
            {"detail": {"code": "GENERATION_BUDGET_EXCEEDED"}},
            "GENERATION_BUDGET_EXCEEDED",
            "Lo Studio ha rifiutato la generazione perché supererebbe un tetto di spesa. Chi "
            "gestisce lo Studio può alzarlo. (GENERATION_BUDGET_EXCEEDED)",
        ),
        (
            418,
            {"detail": {"code": "BRAND_NEW"}},
            "BRAND_NEW",
            "Lo Studio ha risposto con un errore (stato 418, BRAND_NEW).",
        ),
    ],
)
def test_a_failed_answer_is_a_tool_error_with_the_code_of_the_studio(
    tmp_path: Path, status: int, body: object, code: str, message: str
) -> None:
    state_folder(tmp_path)
    store_session(tmp_path)
    transport = approved_twins(ScriptedTransport())
    transport.expect("GET", CONVERSATION, status=404, body={"detail": {"code": "NOT_FOUND"}})
    transport.expect("POST", TURNS, status=status, body=body)
    tools, _ = build(tmp_path, spend=True, transport=transport)

    assert refused(tools, "ask_twin", twin="1", question="Ciao?") == {
        "code": code,
        "message": message,
    }


def test_asking_needs_approved_twins_and_the_sign_in(tmp_path: Path) -> None:
    state_folder(tmp_path)
    tools, _ = build(tmp_path, spend=True)
    signed_out = refused(tools, "ask_twin", twin="1", question="Ciao?")
    store_session(tmp_path)
    transport = ScriptedTransport().expect(
        "GET", READINESS, body={"snapshot_exists": True, "approved_current_snapshot": False}
    )
    waiting, _ = build(tmp_path, spend=True, transport=transport)

    assert signed_out == {
        "code": "NOT_SIGNED_IN",
        "message": "Non hai eseguito l'accesso allo Studio http://127.0.0.1:8000. Accedi con "
        "`ut login`. (NOT_SIGNED_IN)",
    }
    assert refused(waiting, "ask_twin", twin="1", question="Ciao?") == {
        "code": "TWINS_NOT_APPROVED",
        "message": "I twin di questo progetto non sono approvati nello Studio, oppure sono "
        "rimasti indietro: aggiornali con `ut sections update` o confermali con `ut init`, poi "
        "riprova. (TWINS_NOT_APPROVED)",
    }


def test_a_review_records_the_head_commit_and_asks_the_twins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = state_folder(tmp_path)
    store_session(tmp_path)
    calls = fake_git(monkeypatch, root=project.root)
    transport = ScriptedTransport()
    transport.expect("POST", CHANGES, status=201, body=recorded_change())
    transport.expect("POST", REVIEWS, status=201, body={"status": "REVIEWED", "run": change_run()})
    tools, bundle = build(tmp_path, spend=True, transport=transport)

    document = run(tools, "review_changes")

    assert document == {
        **change_run(),
        "reused": False,
        "decide_with": "ut align",
        "estimated_usd": [0.45, 0.8],
    }
    assert calls == [
        ("root", project.root),
        ("head",),
        ("resolve", f"{PENDING_COMMIT}^"),
        ("commits_after", ALIGNED_COMMIT, 50),
        ("diff_of", PENDING_COMMIT),
    ]
    assert transport.requests("POST", CHANGES)[0].json() == changes_flow.change_body(COMMIT, DIFF)
    review = transport.requests("POST", REVIEWS)[0]
    assert review.json() == {"locale": "it-IT", "again": False}
    assert review.header("prefer") == "respond-async"
    transport.assert_done()
    assert bundle.output == ""


def test_a_review_of_a_named_commit_resolves_it_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = state_folder(tmp_path, language="en")
    folder_language(project, "en")
    store_session(tmp_path)
    calls = fake_git(
        monkeypatch,
        root=project.root,
        revisions={"4f2a9c1": PENDING_COMMIT, f"{PENDING_COMMIT}^": ALIGNED_COMMIT},
    )
    transport = ScriptedTransport()
    transport.expect(
        "POST", CHANGES, status=200, body={**recorded_change(), "status": "ALREADY_RECORDED"}
    )
    transport.expect("POST", REVIEWS, status=201, body={"status": "REVIEWED", "run": change_run()})
    tools, _ = build(tmp_path, spend=True, transport=transport)

    document = run(tools, "review_changes", commit="4F2A9C1")

    assert document["id"] == change_run()["id"]
    assert calls[1:3] == [("resolve", "4f2a9c1"), ("resolve", f"{PENDING_COMMIT}^")]
    assert transport.requests("POST", REVIEWS)[0].json() == {"locale": "en-US", "again": False}


def test_an_italian_folder_asks_the_studio_for_italian_from_an_english_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = state_folder(tmp_path, language="en")
    folder_language(project, "it")
    store_session(tmp_path)
    fake_git(monkeypatch, root=project.root)
    transport = ScriptedTransport()
    transport.expect("POST", CHANGES, status=201, body=recorded_change())
    transport.expect("POST", REVIEWS, status=201, body={"status": "REVIEWED", "run": change_run()})
    tools, _ = build(tmp_path, spend=True, transport=transport)

    run(tools, "review_changes")

    assert transport.requests("POST", REVIEWS)[0].json() == {"locale": "it-IT", "again": False}
    assert run(tools, "project_state")["next"] == OPEN_TASKS_NEXT["it"]
    transport.assert_done()


def test_a_review_that_exists_gives_the_latest_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = state_folder(tmp_path)
    store_session(tmp_path)
    fake_git(monkeypatch, root=project.root)
    newer = {**change_run(), "id": "00000000-0000-4000-8000-00000000d002"}
    transport = ScriptedTransport()
    transport.expect("POST", CHANGES, status=201, body=recorded_change())
    transport.expect(
        "POST", REVIEWS, status=409, body={"detail": {"code": "CODE_CHANGE_REVIEW_EXISTS"}}
    )
    transport.expect("GET", REVIEWS, body={"items": [newer, change_run()]})
    tools, _ = build(tmp_path, spend=True, transport=transport)

    document = run(tools, "review_changes", commit="HEAD")

    assert document == {
        **newer,
        "reused": True,
        "decide_with": "ut align",
        "estimated_usd": [0.45, 0.8],
    }
    transport.assert_done()


def test_the_first_commit_of_a_repository_is_looked_for_among_the_latest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = state_folder(tmp_path)
    store_session(tmp_path)
    calls = fake_git(monkeypatch, root=project.root, revisions={})
    transport = ScriptedTransport()
    transport.expect("POST", CHANGES, status=201, body=recorded_change())
    transport.expect("POST", REVIEWS, status=201, body={"status": "REVIEWED", "run": change_run()})
    tools, _ = build(tmp_path, spend=True, transport=transport)

    run(tools, "review_changes")

    assert ("commits_after", None, 50) in calls


@pytest.mark.parametrize(
    ("options", "arguments", "expected"),
    [
        (
            {"root": None},
            {},
            {
                "code": "NO_GIT_REPOSITORY",
                "message": "La cartella {folder} non è dentro un repository git: i twin possono "
                "rivedere solo commit di un repository. (NO_GIT_REPOSITORY)",
            },
        ),
        (
            {"head": None},
            {},
            {
                "code": "NO_COMMIT",
                "message": "Il repository non ha ancora nessun commit da rivedere. (NO_COMMIT)",
            },
        ),
        (
            {},
            {"commit": "abcdef1"},
            {
                "code": "COMMIT_NOT_FOUND",
                "message": "Il commit abcdef1 non è nel repository, oppure non è tra gli ultimi "
                "50 commit del ramo corrente. (COMMIT_NOT_FOUND)",
            },
        ),
        (
            {"commits": ()},
            {},
            {
                "code": "COMMIT_NOT_FOUND",
                "message": "Il commit HEAD non è nel repository, oppure non è tra gli ultimi 50 "
                "commit del ramo corrente. (COMMIT_NOT_FOUND)",
            },
        ),
    ],
)
def test_a_commit_that_cannot_be_found_sends_nothing_to_the_studio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    options: dict[str, object],
    arguments: dict[str, object],
    expected: dict[str, str],
) -> None:
    project = state_folder(tmp_path)
    store_session(tmp_path)
    fake_git(monkeypatch, **{"root": project.root, **options})
    tools, _ = build(tmp_path, spend=True)

    found = refused(tools, "review_changes", **arguments)

    assert found == {**expected, "message": expected["message"].format(folder=project.root)}


def test_git_that_is_missing_is_a_tool_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_folder(tmp_path)

    def missing(context: object, start: Path) -> Path | None:
        raise CliError("GIT_NOT_AVAILABLE", status=1)

    monkeypatch.setattr(changes_flow, "repository_root", missing)
    tools, _ = build(tmp_path, spend=True)

    assert refused(tools, "review_changes") == {
        "code": "GIT_NOT_AVAILABLE",
        "message": "Il programma git non si trova su questo computer: installalo per far "
        "rivedere i commit. (GIT_NOT_AVAILABLE)",
    }


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (
            503,
            "CHANGE_REVIEW_MODEL_NOT_CONFIGURED",
            "I twin non possono rivedere il codice su questo Studio, perché non ha un modello "
            "collegato; il commit resta registrato. Chi gestisce lo Studio può collegarne uno. "
            "(CHANGE_REVIEW_MODEL_NOT_CONFIGURED)",
        ),
        (
            409,
            "DESIGN_APPROVAL_REQUIRED",
            "Per rivedere un commit serve il design approvato: approvalo con `ut design`. "
            "(DESIGN_APPROVAL_REQUIRED)",
        ),
        (
            502,
            "INVALID_PROVIDER_OUTPUT",
            "Il modello ha risposto in un modo che lo Studio non può usare, quindi la revisione "
            "non è stata salvata. Puoi riprovare, ma è una nuova spesa. (INVALID_PROVIDER_OUTPUT)",
        ),
        (
            429,
            "TOO_MANY_GENERATIONS",
            "Nello Studio girano già troppe generazioni: aspetta che una finisca, poi riprova. "
            "(TOO_MANY_GENERATIONS)",
        ),
    ],
)
def test_a_review_refused_by_the_studio_is_a_tool_error_with_its_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int, code: str, message: str
) -> None:
    project = state_folder(tmp_path)
    store_session(tmp_path)
    fake_git(monkeypatch, root=project.root)
    transport = ScriptedTransport()
    transport.expect("POST", CHANGES, status=201, body=recorded_change())
    transport.expect("POST", REVIEWS, status=status, body={"detail": {"code": code}})
    tools, _ = build(tmp_path, spend=True, transport=transport)

    assert refused(tools, "review_changes") == {"code": code, "message": message}
    transport.assert_done()


def test_a_record_refused_by_the_studio_stops_before_the_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = state_folder(tmp_path)
    store_session(tmp_path)
    fake_git(monkeypatch, root=project.root)
    transport = ScriptedTransport().expect(
        "POST", CHANGES, status=404, body={"detail": {"code": "PROJECT_NOT_FOUND"}}
    )
    tools, _ = build(tmp_path, spend=True, transport=transport)

    assert refused(tools, "review_changes") == {
        "code": "PROJECT_NOT_FOUND",
        "message": "Lo Studio non trova questo progetto per il tuo account. (PROJECT_NOT_FOUND)",
    }
    transport.assert_done()


def test_an_interrupted_review_stops_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = state_folder(tmp_path)
    store_session(tmp_path)
    fake_git(monkeypatch, root=project.root)

    def interrupted(*arguments: object, **options: object) -> object:
        raise CliError("GENERATION_INTERRUPTED", status=130)

    monkeypatch.setattr(jobs, "generate", interrupted)
    transport = ScriptedTransport().expect("POST", CHANGES, status=201, body=recorded_change())
    tools, _ = build(tmp_path, spend=True, transport=transport)

    with pytest.raises(KeyboardInterrupt):
        tools.call("review_changes", {})


def test_the_link_is_read_again_at_every_call(tmp_path: Path) -> None:
    tools, _ = build(tmp_path)
    before = refused(tools, "project_state")
    link_folder(tmp_path / "project", language="en")

    after = run(tools, "project_state")

    assert before["code"] == "PROJECT_NOT_LINKED"
    assert after["project"]["language"] == "en"
    assert after["folder"] is None


def with_test_estimates(monkeypatch: pytest.MonkeyPatch, *, present: bool) -> None:
    estimates = {
        name: value
        for name, value in costs.ESTIMATES.items()
        if name not in ("TEST_PLAN", "TEST_REVIEW")
    }
    if present:
        estimates["TEST_PLAN"] = costs.Estimate(0.15, 0.30, 2.0)
        estimates["TEST_REVIEW"] = costs.Estimate(0.10, 0.20, 1.0)
    monkeypatch.setattr(costs, "ESTIMATES", MappingProxyType(estimates))


def test_the_eleven_tools_end_with_the_tools_of_the_tests_and_of_the_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_test_estimates(monkeypatch, present=True)
    free, _ = build(tmp_path / "free")
    italian, _ = build(tmp_path / "italian", language="it")

    listed = free.definitions()
    results, tests, tasks = listed[8], listed[9], listed[10]

    assert [tool["name"] for tool in listed] == TOOL_NAMES
    assert tasks == {
        "name": "get_tasks",
        "title": "Tasks for the code",
        "description": "The tasks for the code read from the knowledge folder: the text, the "
        "requirements, screens and criteria they are about, where they come from (a critique of "
        "a twin on a commit or on the tests, the decision on a commit, or the owner) and their "
        "status; with status all also the ones done or dropped. No spending.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["open", "all"],
                    "default": "open",
                    "description": "Which tasks to give: open for the open ones, all for every "
                    "task; usually open.",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }
    assert italian.definitions()[10]["title"] == "Compiti per il codice"
    assert italian.definitions()[10]["description"].endswith(
        "con status all anche quelli fatti o lasciati cadere. Nessuna spesa."
    )
    assert (
        "(una critica di un twin su un commit o sui test, la decisione su un commit, oppure il "
        "proprietario)" in italian.definitions()[10]["description"]
    )
    assert results == {
        "name": "get_test_results",
        "title": "Outcome of the acceptance tests",
        "description": "The latest runs of the acceptance tests on the application under "
        "development, read from the knowledge folder: status of every criterion, outcome of "
        "every path in every browser and the critiques of the twins. No spending.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 1,
                    "description": "How many runs of the tests to give, newest first: 1 to 20, "
                    "usually 1.",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }
    assert tests["title"] == "Check of the acceptance criteria"
    assert tests["description"] == (
        "Open the application under development in the browsers of this computer, check the "
        "approved acceptance criteria along paths written by the model, record the outcome in "
        "the Studio and have the twins criticize it. Paid. About 0.15-0.30 USD for a new test "
        "plan and 0.10-0.20 USD per twin for the critiques. Not available now: the server was "
        "started without --spend."
    )
    properties = tests["inputSchema"]["properties"]
    assert list(properties) == ["application", "browser", "criteria", "review", "new_plan"]
    assert {
        name: {key: value for key, value in field.items() if key != "description"}
        for name, field in properties.items()
    } == {
        "application": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["URL", "STATIC"]},
                "address": {"type": "string", "minLength": 1, "maxLength": 500},
            },
            "required": ["kind", "address"],
            "additionalProperties": False,
        },
        "browser": {"type": "string", "enum": ["chrome", "firefox", "all"]},
        "criteria": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 20},
            "minItems": 1,
            "maxItems": 20,
        },
        "review": {"type": "boolean", "default": True},
        "new_plan": {"type": "boolean", "default": False},
    }
    assert all(field["description"] for field in properties.values())
    assert (tests["inputSchema"]["required"], tests["inputSchema"]["additionalProperties"]) == (
        [],
        False,
    )
    assert tests["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }


def test_the_description_of_the_tests_carries_the_estimates_only_when_they_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_test_estimates(monkeypatch, present=True)
    italian, _ = build(tmp_path / "italian", spend=True, language="it")
    priced = italian.definitions()[9]["description"]
    with_test_estimates(monkeypatch, present=False)
    plain, _ = build(tmp_path / "plain", spend=True)

    assert priced.endswith(
        "A pagamento. Circa 0,15-0,30 USD per un nuovo piano dei test e 0,10-0,20 USD per twin "
        "per le critiche."
    )
    assert plain.definitions()[9]["description"] == (
        "Open the application under development in the browsers of this computer, check the "
        "approved acceptance criteria along paths written by the model, record the outcome in "
        "the Studio and have the twins criticize it. Paid."
    )
    assert tools_module.acceptance_prices("en") is None


def test_the_test_results_give_the_latest_runs_from_the_folder(tmp_path: Path) -> None:
    runs = runs_newest_first()
    with_test_runs(tmp_path, runs)
    tools, _ = build(tmp_path)

    assert run(tools, "get_test_results") == {"runs": runs[:1]}
    assert run(tools, "get_test_results", limit=2) == {"runs": runs}
    assert run(tools, "get_test_results", limit=20.0) == {"runs": runs}


def test_older_folders_have_no_test_results(tmp_path: Path) -> None:
    schema_two_folder(tmp_path / "older")
    project = state_folder(tmp_path / "undeclared")
    (project.knowledge / "twins" / "feedback" / "tests.json").unlink(missing_ok=True)
    declare_tests(project, declared=False)
    older, _ = build(tmp_path / "older")
    undeclared, _ = build(tmp_path / "undeclared")

    assert run(older, "get_test_results") == {"runs": []}
    assert run(undeclared, "get_test_results", limit=5) == {"runs": []}


def test_the_test_results_answer_the_folder_problems(tmp_path: Path) -> None:
    linked(tmp_path / "missing")
    project = with_test_runs(tmp_path / "broken", runs_newest_first())
    (project.knowledge / "twins" / "feedback" / "tests.json").unlink()
    missing, _ = build(tmp_path / "missing")
    broken, _ = build(tmp_path / "broken")

    assert refused(missing, "get_test_results")["code"] == "FOLDER_MISSING"
    assert refused(broken, "get_test_results") == {
        "code": "FOLDER_UNREADABLE",
        "message": "La cartella di conoscenza non si legge (orchestwin/twins/feedback/tests.json): "
        "scaricala di nuovo con `ut package pull`. (FOLDER_UNREADABLE)",
    }


def test_running_the_tests_hands_the_request_to_the_flow_and_answers_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = state_folder(tmp_path)
    outcome, document = outcome_of(project.root)
    calls = fake_test_flow(monkeypatch, outcome=outcome)
    tools, bundle = build(tmp_path, spend=True)

    answer = run(
        tools,
        "run_tests",
        application={"kind": " static ", "address": " dist "},
        browser=" Firefox ",
        criteria=["ac-002", " AC-001 ", "ac-002"],
        review=False,
        new_plan=True,
    )

    folder = project.root.joinpath(".orchestwin", *RUN_FOLDER)
    assert answer == {
        "run": document,
        "critiques": document["critiques"],
        "report": str(folder / "report.html"),
        "folder": str(folder),
    }
    ((context, request),) = calls
    module = importlib.import_module(TEST_FLOW)
    assert isinstance(request, module.TestRequest)
    assert request_fields(request) == (
        {"kind": "STATIC", "address": "dist"},
        ("firefox",),
        ("AC-002", "AC-001"),
        True,
        False,
    )
    assert request.max_usd == 2.0
    assert context.assume_yes is True
    assert context.language == "en"
    assert context.environment.stdout is bundle.environment.stderr
    assert context.environment.stdin.read() == ""
    assert context.directory == tmp_path / "project"
    assert bundle.output == ""


def test_running_the_tests_without_arguments_uses_the_saved_application_and_every_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = state_folder(tmp_path)
    outcome, _ = outcome_of(project.root)
    calls = fake_test_flow(monkeypatch, outcome=outcome)
    tools, _ = build(tmp_path, spend=True)

    run(tools, "run_tests")
    run(tools, "run_tests", browser="all", review=True, new_plan=False)

    assert [request_fields(request) for _, request in calls] == [
        (None, ("all",), (), False, True),
        (None, ("all",), (), False, True),
    ]


APPLICATION_KEY = "mcp.argument_application"


@pytest.mark.parametrize(
    ("name", "arguments", "key"),
    [
        ("run_tests", {"application": "dist"}, APPLICATION_KEY),
        ("run_tests", {"application": {"kind": "FILE", "address": "dist"}}, APPLICATION_KEY),
        ("run_tests", {"application": {"kind": "URL"}}, APPLICATION_KEY),
        ("run_tests", {"application": {"kind": "URL", "address": "x", "port": 1}}, APPLICATION_KEY),
        ("run_tests", {"application": {"kind": "URL", "address": "   "}}, APPLICATION_KEY),
        ("run_tests", {"application": {"kind": "URL", "address": "a" * 501}}, APPLICATION_KEY),
        ("run_tests", {"application": {"kind": 1, "address": "dist"}}, APPLICATION_KEY),
        ("run_tests", {"browser": "safari"}, "mcp.argument_browser"),
        ("run_tests", {"browser": 3}, "mcp.argument_browser"),
        ("run_tests", {"criteria": []}, "mcp.argument_criteria"),
        ("run_tests", {"criteria": ["AC-001"] * 21}, "mcp.argument_criteria"),
        ("run_tests", {"criteria": [" "]}, "mcp.argument_criteria"),
        ("run_tests", {"criteria": "AC-001"}, "mcp.argument_criteria"),
        ("run_tests", {"review": "yes"}, "mcp.argument_flag"),
        ("run_tests", {"new_plan": 1}, "mcp.argument_flag"),
        ("run_tests", {"plan": "new"}, "mcp.argument_unknown"),
        ("get_test_results", {"limit": 0}, "mcp.argument_count"),
        ("get_test_results", {"limit": 21}, "mcp.argument_count"),
        ("get_test_results", {"limit": "2"}, "mcp.argument_count"),
    ],
)
def test_the_arguments_of_the_tools_of_the_tests_are_checked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    arguments: dict[str, object],
    key: str,
) -> None:
    state_folder(tmp_path)
    calls = fake_test_flow(monkeypatch)
    tools, _ = build(tmp_path, spend=True)

    with pytest.raises(RpcError) as refused_call:
        tools.call(name, arguments)

    error = refused_call.value
    assert (error.code, error.word, error.key) == (-32602, "INVALID_ARGUMENTS", key)
    assert calls == []


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (
            CliError("TEST_DESIGN_REQUIRED"),
            "I test di accettazione richiedono i requisiti e il design approvati nella cartella "
            "di conoscenza: approvali con `ut init` e `ut design`, poi scarica di nuovo la "
            "cartella con `ut package pull`. (TEST_DESIGN_REQUIRED)",
        ),
        (
            CliError("TEST_APPLICATION_REQUIRED", status=2),
            "Non so ancora quale applicazione verificare: richiama run_tests con application, "
            "kind URL e l'indirizzo, oppure kind STATIC e la cartella dell'applicazione "
            "costruita; le esecuzioni successive la ricordano. (TEST_APPLICATION_REQUIRED)",
        ),
        (
            CliError("TEST_STATIC_INVALID", status=2),
            "La cartella dell'applicazione non esiste oppure non contiene index.html: indica la "
            "cartella con l'applicazione costruita. (TEST_STATIC_INVALID)",
        ),
        (
            CliError("TEST_NO_BROWSER"),
            "Su questo computer non trovo nessun browser: installa Google Chrome, Chromium, "
            "Microsoft Edge oppure Mozilla Firefox, oppure indica il programma con "
            "ORCHESTWIN_CHROME o ORCHESTWIN_FIREFOX. (TEST_NO_BROWSER)",
        ),
        (
            CliError("TEST_MODEL_NOT_CONFIGURED"),
            "Questo Studio non ha un modello collegato, quindi non può scrivere un nuovo piano dei "
            "test; un piano già salvato su questo computer si esegue ancora con new_plan false. "
            "Chi gestisce lo Studio può collegare un modello. (TEST_MODEL_NOT_CONFIGURED)",
        ),
        (
            CliError("TEST_CRITERION_UNKNOWN", status=2),
            "Alcuni codici di criteria non sono criteri del piano dei test: usa i codici che "
            "elenca get_requirements, per esempio AC-001. (TEST_CRITERION_UNKNOWN)",
        ),
        (
            CliError("BROWSER_NOT_FOUND", values={"program": "firefox"}),
            "Il browser indicato non è installato su questo computer: scegline un altro con "
            "browser, oppure all. (BROWSER_NOT_FOUND)",
        ),
        (
            CliError("BROWSER_NOT_STARTED", values={"program": "chrome"}),
            "Il browser chrome non è partito: controlla che si apra su questo computer, oppure "
            "scegline un altro con browser. (BROWSER_NOT_STARTED)",
        ),
        (
            CliError("BROWSER_PROTOCOL_ERROR", values={"program": "chrome", "detail": "closed"}),
            "La comunicazione con il browser si è interrotta: riprova; se succede ancora, scegli "
            "l'altro browser con browser. (BROWSER_PROTOCOL_ERROR)",
        ),
        (
            CliError("PAGE_NOT_LOADED", values={"program": "chrome", "detail": "refused"}),
            "L'applicazione non si è aperta nel browser: controlla che l'indirizzo risponda, "
            "oppure che la cartella contenga index.html, poi riprova. (PAGE_NOT_LOADED)",
        ),
        (
            CliError("ACTION_FAILED", values={"program": "firefox", "detail": "no node"}),
            "Il browser non ha potuto eseguire un passo dei test: riprova, oppure chiedi un nuovo "
            "piano con new_plan true, che è una nuova spesa. (ACTION_FAILED)",
        ),
        (
            ApiFailure("REQUIREMENTS_APPROVAL_REQUIRED", http_status=409),
            "Per verificare l'applicazione servono i requisiti approvati nello Studio: approvali "
            "con `ut init`. (REQUIREMENTS_APPROVAL_REQUIRED)",
        ),
        (
            ApiFailure("DESIGN_APPROVAL_REQUIRED", http_status=409),
            "Per verificare l'applicazione serve il design approvato nello Studio: approvalo con "
            "`ut design`. (DESIGN_APPROVAL_REQUIRED)",
        ),
        (
            ApiFailure("USER_MODELING_APPROVAL_REQUIRED", http_status=409),
            "I twin possono criticare i test solo quando sono approvati: confermali con "
            "`ut init`, oppure richiama run_tests con review false. "
            "(USER_MODELING_APPROVAL_REQUIRED)",
        ),
        (
            ApiFailure("TEST_PLAN_NOT_FOUND", http_status=404),
            "Il piano dei test salvato su questo computer non è più nello Studio: richiama "
            "run_tests con new_plan true, che è una nuova spesa. (TEST_PLAN_NOT_FOUND)",
        ),
        (
            ApiFailure("INVALID_PROVIDER_OUTPUT", http_status=502),
            "Il modello ha risposto in un modo che lo Studio non può usare, quindi il piano dei "
            "test o le critiche non sono stati salvati. Puoi riprovare, ma è una nuova spesa. "
            "(INVALID_PROVIDER_OUTPUT)",
        ),
        (
            CliError("GENERATION_STILL_RUNNING"),
            "Il modello sta ancora lavorando nello Studio: richiama run_tests fra qualche minuto. "
            "(GENERATION_STILL_RUNNING)",
        ),
        (
            ApiFailure("GENERATION_BUDGET_EXCEEDED", http_status=402),
            "Lo Studio ha rifiutato la generazione perché supererebbe un tetto di spesa. Chi "
            "gestisce lo Studio può alzarlo. (GENERATION_BUDGET_EXCEEDED)",
        ),
        (
            ApiFailure("BRAND_NEW", http_status=418),
            "Lo Studio ha risposto con un errore (stato 418, BRAND_NEW).",
        ),
    ],
)
def test_a_failed_run_of_the_tests_is_a_tool_error_with_its_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: CliError, message: str
) -> None:
    state_folder(tmp_path)
    calls = fake_test_flow(monkeypatch, failure=failure)
    tools, _ = build(tmp_path, spend=True)

    assert refused(tools, "run_tests") == {"code": failure.code, "message": message}
    assert len(calls) == 1


def test_the_sentences_for_the_tests_leave_the_other_tools_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = state_folder(tmp_path)
    store_session(tmp_path)
    fake_git(monkeypatch, root=project.root)

    def still_running(*arguments: object, **options: object) -> object:
        raise CliError("GENERATION_STILL_RUNNING")

    monkeypatch.setattr(jobs, "generate", still_running)
    transport = ScriptedTransport().expect("POST", CHANGES, status=201, body=recorded_change())
    tools, _ = build(tmp_path, spend=True, transport=transport)

    assert refused(tools, "review_changes") == {
        "code": "GENERATION_STILL_RUNNING",
        "message": "La revisione continua nello Studio: richiama review_changes con lo stesso "
        "commit più tardi per leggerla. (GENERATION_STILL_RUNNING)",
    }


def test_an_interrupted_run_of_the_tests_stops_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_folder(tmp_path)
    fake_test_flow(monkeypatch, failure=CliError("GENERATION_INTERRUPTED", status=130))
    tools, _ = build(tmp_path, spend=True)

    with pytest.raises(KeyboardInterrupt):
        tools.call("run_tests", {})


def test_the_tasks_are_the_open_ones_of_the_folder_unless_all_are_asked(tmp_path: Path) -> None:
    project = learning_folder(tmp_path)
    tools, _ = build(tmp_path)
    written = state_document(project.knowledge)["tasks"]

    opened = run(tools, "get_tasks")
    every = run(tools, "get_tasks", status="all")
    spaced = run(tools, "get_tasks", status="  ALL ")
    default = run(tools, "get_tasks", status=None)

    assert opened == {"tasks": [task for task in written if task["status"] == "OPEN"]}
    assert [task["code"] for task in opened["tasks"]] == ["TSK-001", "TSK-003", "TSK-005"]
    assert every == spaced == {"tasks": written}
    assert default == opened
    assert every["tasks"][:4] == list(origin_tasks())
    assert every["tasks"][2]["origin"] == {
        "kind": "TEST_RUN",
        "commit": None,
        "test_run_id": "00000000-0000-4000-8000-00000000e001",
        "twin_id": RECEPTION_TWIN,
        "twin_name": RECEPTION,
        "finding": "Con il nome vuoto non compare nessun messaggio.",
    }


def test_the_tasks_of_older_folders_come_as_they_were_written(tmp_path: Path) -> None:
    sprint_27 = state_folder(tmp_path / "sprint27")
    done = {**legacy_task(), "code": "TSK-006", "status": "DONE"}
    with_state_tasks(sprint_27, [legacy_task(), done])
    schema_two_folder(tmp_path / "older")
    newer, _ = build(tmp_path / "sprint27")
    older, _ = build(tmp_path / "older")

    assert run(newer, "get_tasks") == {"tasks": [legacy_task()]}
    assert run(newer, "get_tasks", status="all") == {"tasks": [legacy_task(), done]}
    assert run(older, "get_tasks", status="all") == {"tasks": []}


def test_the_tasks_answer_the_problems_of_the_folder(tmp_path: Path) -> None:
    linked(tmp_path / "missing")
    broken = state_folder(tmp_path / "broken")
    (broken.knowledge / "state" / "state.json").unlink()
    missing, _ = build(tmp_path / "missing")
    unreadable, _ = build(tmp_path / "broken")

    assert refused(missing, "get_tasks")["code"] == "FOLDER_MISSING"
    assert refused(unreadable, "get_tasks") == {
        "code": "FOLDER_UNREADABLE",
        "message": "La cartella di conoscenza non si legge (orchestwin/state/state.json): "
        "scaricala di nuovo con `ut package pull`. (FOLDER_UNREADABLE)",
    }


@pytest.mark.parametrize("value", ["done", "", 3, True, ["all"]])
def test_the_filter_of_the_tasks_is_open_or_all(tmp_path: Path, value: object) -> None:
    state_folder(tmp_path)
    tools, _ = build(tmp_path)

    with pytest.raises(RpcError) as refused_call:
        tools.call("get_tasks", {"status": value})

    error = refused_call.value
    assert (error.code, error.word, error.key) == (
        -32602,
        "INVALID_ARGUMENTS",
        "mcp.argument_status",
    )
    assert text(error.key, "en", **error.values) == (
        "The argument status of get_tasks must be open or all."
    )
    assert text(error.key, "it", **error.values) == (
        "L'argomento status di get_tasks deve essere open oppure all."
    )


def test_the_twins_carry_their_label_and_what_they_learned(tmp_path: Path) -> None:
    learning_folder(tmp_path)
    tools, _ = build(tmp_path)
    reception, volunteers = learned_entries()

    listed = run(tools, "list_twins")["twins"]
    first = run(tools, "get_twin", twin="1")
    second = run(tools, "get_twin", twin="organizzatori")

    assert [
        (twin["number"], twin["name"], twin["label"], twin["learned_observations"])
        for twin in listed
    ] == [(1, RECEPTION, "1.3", 2), (2, VOLUNTEERS, "1.0", 0)]
    assert first["twin"]["twin_id"] == RECEPTION_TWIN
    assert first["learned"] == reception
    assert [item["code"] for item in first["learned"]["observations"]] == ["OBS-001", "OBS-003"]
    assert [item["code"] for item in first["learned"]["retired"]] == ["OBS-002"]
    assert second["learned"] == volunteers
    assert list(first) == ["twin", "learned"]


def test_without_the_learning_document_a_twin_keeps_the_version_of_its_profile(
    tmp_path: Path,
) -> None:
    without_learning(tmp_path / "without")
    with_learning(tmp_path / "partial", [learned_entries()[0]])
    before, _ = build(tmp_path / "without")
    partial, _ = build(tmp_path / "partial")

    listed = run(before, "list_twins")["twins"]
    partly = run(partial, "list_twins")["twins"]

    assert [(twin["label"], twin["learned_observations"]) for twin in listed] == [
        ("1", 0),
        ("1", 0),
    ]
    assert run(before, "get_twin", twin="1")["learned"] is None
    assert [(twin["label"], twin["learned_observations"]) for twin in partly] == [
        ("1.3", 2),
        ("1", 0),
    ]
    assert run(partial, "get_twin", twin="2")["learned"] is None


def test_a_learning_document_that_cannot_be_read_is_a_tool_error(tmp_path: Path) -> None:
    project = with_learning(tmp_path, list(learned_entries()))
    (project.knowledge / "twins" / "feedback" / "learned.json").unlink()
    declare_learning(project, declared=True)
    tools, _ = build(tmp_path)
    message = (
        "La cartella di conoscenza non si legge (orchestwin/twins/feedback/learned.json): "
        "scaricala di nuovo con `ut package pull`. (FOLDER_UNREADABLE)"
    )

    assert refused(tools, "list_twins") == {"code": "FOLDER_UNREADABLE", "message": message}
    assert refused(tools, "get_twin", twin="1") == {"code": "FOLDER_UNREADABLE", "message": message}
    assert run(tools, "get_requirements")["version_number"] == 2


def test_the_project_state_counts_the_reviews_to_do_again(tmp_path: Path) -> None:
    project = learning_folder(tmp_path / "stale")
    linked(tmp_path / "nothing")
    stale, _ = build(tmp_path / "stale")
    nothing, _ = build(tmp_path / "nothing")

    document = run(stale, "project_state")
    edit_json(
        project.knowledge / "orchestwin.json",
        lambda manifest: manifest["state"].pop("stale_reviews"),
    )
    older = run(stale, "project_state")

    assert list(document)[4:7] == ["pending_changes", "stale_reviews", "open_tasks"]
    assert document["stale_reviews"] == 1
    assert [task["code"] for task in document["open_tasks"]] == ["TSK-001", "TSK-003", "TSK-005"]
    assert older["stale_reviews"] == 0
    assert run(nothing, "project_state")["stale_reviews"] == 0
