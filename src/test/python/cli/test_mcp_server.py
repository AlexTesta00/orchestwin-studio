from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import orchestwin
from orchestwin.cli import jobs
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows import changes as changes_flow
from orchestwin.cli.http import UrlTransport
from orchestwin.cli.mcp import knowledge
from orchestwin.cli.mcp.server import Server

from .support.fake_studio import FakeProject, FakeStudio
from .support.terminal import TEST_PASSWORD, Run, link_folder, run_ut, store_session
from .support.transports import NoNetwork, ScriptedTransport
from .test_mcp_knowledge import (
    RECEPTION,
    VOLUNTEERS,
    linked,
    schema_two_folder,
    state_folder,
)
from .test_mcp_protocol import call, initialize, notification, request
from .test_mcp_tools import CHANGES, fake_git, recorded_change

EMAIL = "owner@example.com"
TURNS = "/projects/{project_id}/user-twins/{twin_id}/conversation/turns"
MODEL_FAILURE = {"detail": {"code": "INVALID_TWIN_CHAT_OUTPUT", "stage": "MODEL_PROPOSAL"}}
TOOL_ORDER = [
    "project_state",
    "list_twins",
    "get_twin",
    "get_requirements",
    "get_design",
    "get_feedback",
    "ask_twin",
    "review_changes",
]
CAPABILITIES = {
    "tools": {"listChanged": False},
    "resources": {"subscribe": False, "listChanged": False},
}
STOPPED = "The input closed: the MCP server stops.\n"
NOT_LINKED = (
    "This folder is not linked to a project of the Studio, so the MCP server has no knowledge "
    "folder to offer. Start it from the folder of the project, or with --project-dir, or create "
    "the project with `ut init`.\n"
)
TIP_COMMIT = "1234567890abcdef1234567890abcdef12345678"
TIP_PARENT = "abcdefabcdefabcdefabcdefabcdefabcdefabcd"
TIP = changes_flow.Commit(
    hash=TIP_COMMIT,
    parent=TIP_PARENT,
    committed_at="2026-09-29T08:30:00+00:00",
    author="Alex Testa",
    message="Add the tip field",
    files=(changes_flow.ChangedFile("src/tip.js", "ADDED", 20, 0),),
)
TIP_REVISIONS = {f"{TIP_COMMIT}^": TIP_PARENT, TIP_COMMIT[:7]: TIP_COMMIT}


def serve(
    tmp_path: Path,
    *lines: str,
    spend: bool = False,
    language: str = "en",
    transport: object = None,
) -> Run:
    arguments = ["--lang", language, "mcp"]
    if spend:
        arguments.append("--spend")
    return run_ut(
        arguments,
        tmp_path,
        transport=NoNetwork() if transport is None else transport,
        answers=list(lines),
    )


def messages(run: Run) -> dict[object, dict[str, object]]:
    found = [json.loads(line) for line in run.output.splitlines()]
    assert all(isinstance(item, dict) and item["jsonrpc"] == "2.0" for item in found)
    return {item["id"]: item for item in found}


def structured(message: dict[str, object]) -> dict[str, object]:
    result = message["result"]
    assert result["isError"] is False, result
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    return result["structuredContent"]


def tool_error(message: dict[str, object]) -> dict[str, object]:
    result = message["result"]
    assert result["isError"] is True, result
    assert result["content"] == [{"type": "text", "text": result["structuredContent"]["message"]}]
    return result["structuredContent"]


def started(tmp_path: Path, *, paid: str = "not allowed (no --spend)") -> str:
    return (
        'MCP server orchestwin-twins started for the project "Calcolo mancia" '
        f"({tmp_path / 'project'}). Paid tools: {paid}. Waiting for messages on the standard "
        "input; to stop it, close the input or press Ctrl+C.\n"
    )


def signed_in(
    tmp_path: Path, studio: FakeStudio, *, language: str = "en", through: str = "design"
) -> FakeProject:
    studio.add_account(EMAIL, TEST_PASSWORD)
    login = run_ut(
        ["login", "--studio", studio.address, "--email", EMAIL, "--password-stdin"],
        tmp_path,
        transport=UrlTransport(),
        answers=[TEST_PASSWORD],
    )
    assert login.status == 0, login.errors
    project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through=through)
    link_folder(
        tmp_path / "project",
        project_id=project.id,
        name=project.name,
        studio=studio.address,
        language=language,
    )
    return project


def test_initialize_introduces_the_server_in_the_language_of_the_project(tmp_path: Path) -> None:
    state_folder(tmp_path)

    run = serve(
        tmp_path, initialize(1), notification("notifications/initialized"), request(2, "ping")
    )

    answered = messages(run)
    result = answered[1]["result"]
    assert run.status == 0
    assert sorted(answered) == [1, 2]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"] == CAPABILITIES
    assert result["serverInfo"] == {"name": "orchestwin-twins", "version": orchestwin.__version__}
    assert result["instructions"].startswith(
        "Questo server dà agli agenti dell'editor la conoscenza approvata del progetto "
        "«Calcolo mancia» di OrchesTwin Studio"
    )
    assert "Gli User Twin sono profili dei gruppi di utenti" in result["instructions"]
    assert (
        "ask_twin e review_changes spendono sul modello e ora rispondono con un errore, perché "
        "il server è stato avviato senza --spend."
    ) in result["instructions"]
    assert answered[2]["result"] == {}
    assert run.errors == (
        f"{started(tmp_path)}Connected to test client 1.0 (protocol 2025-06-18).\n{STOPPED}"
    )


def test_with_spend_the_instructions_say_that_the_paid_tools_are_allowed(tmp_path: Path) -> None:
    state_folder(tmp_path, language="en")

    run = serve(tmp_path, initialize(), spend=True, language="it")

    instructions = messages(run)[1]["result"]["instructions"]
    assert instructions.startswith(
        'This server gives the agents of the editor the approved knowledge of the project "Calcolo'
        ' mancia" of OrchesTwin Studio'
    )
    assert (
        "ask_twin and review_changes spend on the model at each call and are allowed, because "
        "the server was started with --spend."
    ) in instructions
    assert run.errors.startswith(
        "Server MCP orchestwin-twins avviato per il progetto «Calcolo mancia» "
    )
    assert "Strumenti a pagamento: permessi (--spend)." in run.errors
    assert run.errors.endswith("L'input si è chiuso: il server MCP si ferma.\n")


@pytest.mark.parametrize(
    ("requested", "answered"),
    [
        ("2025-06-18", "2025-06-18"),
        ("2025-03-26", "2025-03-26"),
        ("2024-11-05", "2024-11-05"),
        ("2030-01-01", "2025-06-18"),
    ],
)
def test_the_version_of_the_client_is_answered_when_it_is_known(
    tmp_path: Path, requested: str, answered: str
) -> None:
    state_folder(tmp_path)

    run = serve(tmp_path, initialize(1, requested))

    assert messages(run)[1]["result"]["protocolVersion"] == answered


def test_the_eight_tools_are_listed_with_schemas_that_hold_together(tmp_path: Path) -> None:
    state_folder(tmp_path)

    run = serve(tmp_path, initialize(), request(2, "tools/list"))

    tools = messages(run)[2]["result"]["tools"]
    assert [tool["name"] for tool in tools] == TOOL_ORDER
    for tool in tools:
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) <= set(schema["properties"])
        assert tool["title"]
        assert tool["description"]
        for field in schema["properties"].values():
            assert field["type"] in ("string", "integer", "array")
            assert field["description"]
            if "pattern" in field:
                re.compile(field["pattern"])
    assert {tool["name"]: tool["inputSchema"]["required"] for tool in tools} == {
        "project_state": [],
        "list_twins": [],
        "get_twin": ["twin"],
        "get_requirements": [],
        "get_design": [],
        "get_feedback": [],
        "ask_twin": ["twin", "question"],
        "review_changes": [],
    }
    assert tools[5]["inputSchema"]["properties"]["limit"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 20,
        "default": 3,
        "description": "How many reviews to give, newest first: 1 to 20, usually 3.",
    }
    assert tools[0]["title"] == "Project state"
    assert tools[0]["description"].endswith("what to do next. Free.")


def test_the_tools_speak_the_language_of_the_command(tmp_path: Path) -> None:
    state_folder(tmp_path, language="en")

    run = serve(tmp_path, initialize(), request(2, "tools/list"), language="it")

    tools = messages(run)[2]["result"]["tools"]
    assert [tool["title"] for tool in tools[:2]] == ["Stato del progetto", "User Twin del progetto"]
    assert tools[6]["description"].endswith(
        "Ora non disponibile: il server è stato avviato senza --spend."
    )


def test_the_free_tools_answer_from_a_schema_three_folder(tmp_path: Path) -> None:
    state_folder(tmp_path)

    run = serve(
        tmp_path,
        initialize(),
        call(2, "project_state"),
        call(3, "list_twins"),
        call(4, "get_twin", {"twin": "addetti"}),
        call(5, "get_requirements", {"codes": ["REQ-003"]}),
        call(6, "get_design", {"screen": "SCR-001"}),
        call(7, "get_feedback", {"limit": 1}),
    )

    answered = messages(run)
    state = structured(answered[2])
    assert state["folder"]["schema_version"] == 3
    assert [item["commit"] for item in state["pending_changes"]] == [
        "4f2a9c1e7b3d5a8f0c6e2b9d1a7f3c5e8b0d2a46"
    ]
    assert [item["code"] for item in state["open_tasks"]] == ["TSK-001"]
    assert [twin["name"] for twin in structured(answered[3])["twins"]] == [RECEPTION, VOLUNTEERS]
    assert structured(answered[4])["twin"]["number"] == 1
    requirements = structured(answered[5])
    assert [item["code"] for item in requirements["requirements"]] == ["REQ-003"]
    assert [item["code"] for item in requirements["user_stories"]] == ["USR-002"]
    assert requirements["unknown_codes"] == []
    screens = structured(answered[6])["chosen"]["screens"]
    assert [(screen["code"], len(screen["transitions"])) for screen in screens] == [("SCR-001", 3)]
    feedback = structured(answered[7])
    assert [item["alignment"]["status"] for item in feedback["runs"]] == ["CODE_DRIFT"]
    assert run.status == 0


def test_the_free_tools_answer_from_a_schema_two_folder(tmp_path: Path) -> None:
    schema_two_folder(tmp_path, language="en")

    run = serve(
        tmp_path,
        initialize(),
        call(2, "project_state"),
        call(3, "get_feedback"),
        call(4, "get_design"),
    )

    answered = messages(run)
    state = structured(answered[2])
    assert state["folder"]["schema_version"] == 2
    assert (state["reference"], state["aligned"], state["pending_changes"]) == (None, None, [])
    assert state["next"].startswith("The design is approved, but this folder has no development")
    assert structured(answered[3]) == {"runs": [], "design_reviews": 0}
    assert structured(answered[4])["chosen"]["code"] == "DES-002"


def test_without_the_knowledge_folder_the_tools_say_how_to_get_it(tmp_path: Path) -> None:
    linked(tmp_path)

    run = serve(
        tmp_path,
        initialize(),
        call(2, "project_state"),
        call(3, "get_design"),
        request(4, "resources/list"),
    )

    answered = messages(run)
    assert structured(answered[2])["folder"] is None
    assert tool_error(answered[3]) == {
        "code": "FOLDER_MISSING",
        "message": "La cartella di conoscenza orchestwin/ non c'è ancora: dopo l'approvazione "
        "del brief scaricala con `ut package publish`. (FOLDER_MISSING)",
    }
    assert answered[4]["result"] == {"resources": []}


def test_the_resources_are_the_markdown_files_of_the_folder(tmp_path: Path) -> None:
    project = state_folder(tmp_path)
    (project.root / "outside.md").write_bytes(b"# Outside\n")
    refused = [
        "orchestwin://orchestwin.json",
        "orchestwin://../outside.md",
        "orchestwin://missing.md",
        "file:///state/state.md",
    ]

    run = serve(
        tmp_path,
        initialize(),
        request(2, "resources/list"),
        request(3, "resources/read", {"uri": "orchestwin://state/state.md"}),
        *(request(4 + index, "resources/read", {"uri": uri}) for index, uri in enumerate(refused)),
    )

    answered = messages(run)
    resources = answered[2]["result"]["resources"]
    assert [item["name"] for item in resources] == knowledge.markdown_files(project.knowledge)
    assert {
        "uri": "orchestwin://state/state.md",
        "name": "state/state.md",
        "mimeType": "text/markdown",
    } in resources
    assert answered[3]["result"] == {
        "contents": [
            {
                "uri": "orchestwin://state/state.md",
                "mimeType": "text/markdown",
                "text": (project.knowledge / "state" / "state.md").read_bytes().decode("utf-8"),
            }
        ]
    }
    for index, uri in enumerate(refused):
        assert answered[4 + index]["error"] == {
            "code": -32602,
            "message": f"Resource not found: {uri}. The resources are the .md files of the "
            "knowledge folder.",
            "data": "RESOURCE_NOT_FOUND",
        }


def test_the_paid_tools_need_spend_and_send_nothing_without_it(tmp_path: Path) -> None:
    state_folder(tmp_path)

    run = serve(
        tmp_path,
        initialize(),
        call(2, "ask_twin", {"twin": "1", "question": "Come lavori?"}),
        call(3, "review_changes"),
    )

    answered = messages(run)
    for identifier, name in ((2, "ask_twin"), (3, "review_changes")):
        refused = tool_error(answered[identifier])
        assert refused["code"] == "SPEND_REQUIRED"
        assert refused["tool"] == name
        assert refused["message"].startswith(f"Lo strumento {name} spende sul modello")


def test_a_folder_that_is_not_linked_ends_with_six_before_serving(tmp_path: Path) -> None:
    run = serve(tmp_path, initialize(), request(2, "tools/list"))

    assert run.status == 6
    assert run.output == ""
    assert run.errors == NOT_LINKED


def test_ctrl_c_stops_the_server_with_one_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(server: Server, line: str) -> str | None:
        raise KeyboardInterrupt

    monkeypatch.setattr(Server, "handle", interrupted)
    state_folder(tmp_path)

    run = serve(tmp_path, initialize())

    assert run.status == 0
    assert run.output == ""
    assert run.errors == f"{started(tmp_path)}Interrupted: the MCP server stops.\n"


def test_ctrl_c_during_a_review_stops_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = state_folder(tmp_path)
    store_session(tmp_path)
    fake_git(monkeypatch, root=project.root)

    def interrupted(*arguments: object, **options: object) -> object:
        raise CliError("GENERATION_INTERRUPTED", status=130)

    monkeypatch.setattr(jobs, "generate", interrupted)
    transport = ScriptedTransport().expect("POST", CHANGES, status=201, body=recorded_change())

    run = serve(
        tmp_path,
        initialize(),
        call(2, "review_changes"),
        request(3, "ping"),
        spend=True,
        transport=transport,
    )

    assert run.status == 0
    assert sorted(messages(run)) == [1]
    assert run.errors.endswith("Interrupted: the MCP server stops.\n")
    transport.assert_done()


def test_stdout_holds_only_the_answers_even_after_wrong_messages(tmp_path: Path) -> None:
    state_folder(tmp_path)

    run = serve(
        tmp_path,
        "not json",
        "",
        "[]",
        notification("notifications/initialized"),
        request(1, "ping"),
    )

    lines = run.output.splitlines()
    assert [json.loads(line) for line in lines] == [
        {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32700,
                "message": "The message is not valid JSON.",
                "data": "PARSE_ERROR",
            },
        },
        {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32600,
                "message": "The message is not a valid JSON-RPC 2.0 request.",
                "data": "INVALID_REQUEST",
            },
        },
        {"jsonrpc": "2.0", "id": 1, "result": {}},
    ]
    assert run.errors == f"{started(tmp_path)}{STOPPED}"


def test_asking_a_twin_goes_to_the_studio_and_is_charged(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=2) as studio:
        project = signed_in(tmp_path, studio)
        run = serve(
            tmp_path,
            initialize(),
            call(2, "ask_twin", {"twin": 2, "question": "How do you split the bill?"}),
            spend=True,
            transport=UrlTransport(),
        )
        twin = project.current("twins")["snapshot"]["twin_versions"][1]
        turns = studio.project(project.id).conversations[twin["twin_id"]].to_snapshot()["turns"]
        spent = studio.project(project.id).spent_microusd
        failures = list(studio.errors)

    assert run.status == 0
    assert structured(messages(run)[2]) == {
        "twin": twin["profile"]["name"],
        "reply": turns[-1]["reply"],
        "insights": turns[-1]["insights"],
        "estimated_usd": [0.02, 0.05],
    }
    assert turns[-1]["question"] == "How do you split the bill?"
    assert spent == 30_000
    assert failures == []
    assert "Paid tools: allowed (--spend)." in run.errors


def test_a_failed_answer_of_the_studio_is_a_tool_error_with_its_code(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=1) as studio:
        project = signed_in(tmp_path, studio)
        studio.fail_next("POST", TURNS, status=502, body=MODEL_FAILURE)
        run = serve(
            tmp_path,
            initialize(),
            call(2, "ask_twin", {"twin": "1", "question": "Why?"}),
            call(3, "ask_twin", {"twin": "Nobody", "question": "Why?"}),
            spend=True,
            transport=UrlTransport(),
        )
        name = project.current("twins")["snapshot"]["twin_versions"][0]["profile"]["name"]
        spent = studio.project(project.id).spent_microusd

    answered = messages(run)
    assert tool_error(answered[2]) == {
        "code": "INVALID_TWIN_CHAT_OUTPUT",
        "message": f"{name} could not answer: the model gave no valid answer or could not be "
        "reached (INVALID_TWIN_CHAT_OUTPUT). You can ask the question again, but it is a new "
        "spending.",
    }
    assert tool_error(answered[3]) == {
        "code": "TWIN_NOT_FOUND",
        "message": f'No twin matches "Nobody". The twins are: 1. {name}. (TWIN_NOT_FOUND)',
        "twins": [{"number": 1, "name": name}],
    }
    assert spent == 0


def test_reviewing_a_commit_follows_the_job_and_finds_the_run_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with FakeStudio(language="en", twins=2, job_polls=2) as studio:
        project = signed_in(tmp_path, studio)
        fake_git(
            monkeypatch,
            root=tmp_path / "project",
            head=TIP_COMMIT,
            revisions=TIP_REVISIONS,
            commits=(TIP,),
        )
        first = serve(
            tmp_path,
            initialize(),
            call(2, "review_changes"),
            spend=True,
            transport=UrlTransport(),
        )
        second = serve(
            tmp_path,
            initialize(),
            call(2, "review_changes", {"commit": TIP_COMMIT[:7]}),
            spend=True,
            transport=UrlTransport(),
        )
        runs = studio.project(project.id).change_reviews()
        changes = studio.project(project.id).changes()
        spent = studio.project(project.id).spent_microusd
        failures = list(studio.errors)

    reviewed = structured(messages(first)[2])
    found = structured(messages(second)[2])
    assert (first.status, second.status) == (0, 0)
    assert reviewed == {
        **runs[0],
        "reused": False,
        "decide_with": "ut align",
        "estimated_usd": [0.45, 0.8],
    }
    assert reviewed["commit"] == TIP_COMMIT
    assert reviewed["alignment"]["status"] == "ALIGNED"
    assert len(reviewed["critiques"]) == 2
    assert found == {**reviewed, "reused": True}
    assert len(runs) == 1
    assert [change["commit"] for change in changes] == [TIP_COMMIT]
    assert spent == 650_000
    assert failures == []
    assert "Review of the commit 1234567..." in first.errors
    assert "Review of the commit 1234567: done in " in first.errors
    assert first.output.count("\n") == 2


def test_a_studio_without_a_model_records_the_commit_but_cannot_review_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with FakeStudio(language="en", twins=2, hosted=False, job_polls=0) as studio:
        project = signed_in(tmp_path, studio, language="it")
        fake_git(
            monkeypatch,
            root=tmp_path / "project",
            head=TIP_COMMIT,
            revisions=TIP_REVISIONS,
            commits=(TIP,),
        )
        run = serve(
            tmp_path, initialize(), call(2, "review_changes"), spend=True, transport=UrlTransport()
        )
        changes = studio.project(project.id).changes()
        runs = studio.project(project.id).change_reviews()

    assert tool_error(messages(run)[2]) == {
        "code": "CHANGE_REVIEW_MODEL_NOT_CONFIGURED",
        "message": "I twin non possono rivedere il codice su questo Studio, perché non ha un "
        "modello collegato; il commit resta registrato. Chi gestisce lo Studio può collegarne "
        "uno. (CHANGE_REVIEW_MODEL_NOT_CONFIGURED)",
    }
    assert [change["commit"] for change in changes] == [TIP_COMMIT]
    assert runs == []
