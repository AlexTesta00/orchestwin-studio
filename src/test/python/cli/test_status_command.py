from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from orchestwin.cli import messages
from orchestwin.cli.project import ProjectFolder

from .support.terminal import PROJECT_ID, START, link_folder, run_ut, store_session
from .support.transports import API, ScriptedTransport

LOCAL = "http://127.0.0.1:8000"
BASE = f"{API}/projects/{PROJECT_ID}"
ALIGNED = "4f2a9c1e7b3d5a8f0c6e2b9d1a7f3c5e8b0d2a46"
TEST_RUN = "00000000-0000-4000-8000-00000000e001"
TWIN_OWNER = "00000000-0000-4000-8000-0000000000b1"
TWIN_WAITER = "00000000-0000-4000-8000-0000000000b2"
TEST_SUMMARY = {"passed": 3, "failed": 1, "blocked": 1, "not_covered": 2, "not_run": 0}
BUDGET = {
    "currency": "USD",
    "per_generation_microusd": 5_000_000,
    "per_project_microusd": 20_000_000,
    "total_microusd": 60_000_000,
    "spent_total_microusd": 34_870_000,
    "remaining_total_microusd": 25_130_000,
    "period_start": None,
}
AFTER_DESIGN = {
    "en": [
        "- `ut code` writes the application with your coding agent.",
        "- `ut test` checks the acceptance criteria in the browsers.",
        "- `ut tasks` shows the things left to do.",
        "- `ut verify`: the twins review the commits and the model says whether code,",
        "  Definition and Design are aligned; you decide.",
        "- `ut twins update` shows what the twins learned.",
        "- `ut watch` watches the commits and records them in the Studio.",
    ],
    "it": [
        "- `ut code` scrive l'applicazione con il tuo agente di programmazione.",
        "- `ut test` verifica i criteri di accettazione nei browser.",
        "- `ut tasks` mostra le cose che restano da fare.",
        "- `ut verify`: i twin esaminano i commit e il modello dice se codice,",
        "  Definizione e Design sono allineati; decidi tu.",
        "- `ut twins update` mostra che cosa hanno imparato i twin.",
        "- `ut watch` osserva i commit e li registra nello Studio.",
    ],
}


def gate(artifact_id: str, content_hash: str, status: str = "APPROVED") -> dict[str, object]:
    return {
        "id": f"gate-{artifact_id}",
        "status": status,
        "artifact": {"artifact_id": artifact_id, "version": 1, "content_hash": content_hash},
    }


def version(identifier: str, number: int, content_hash: str) -> dict[str, object]:
    return {"id": identifier, "version_number": number, "content_hash": content_hash}


def alignment_document(
    *, aligned: str | None = ALIGNED, pending: int = 1, tasks: int = 1, stale: int = 0
) -> dict[str, object]:
    return {
        "project_id": PROJECT_ID,
        "reference": {"requirements": None, "design": None},
        "aligned": None
        if aligned is None
        else {
            "commit": aligned,
            "decided_at": "2026-09-29T08:00:00+00:00",
            "requirements_version_number": 1,
            "design_version_number": 2,
        },
        "pending_changes": pending,
        "stale_reviews": stale,
        "latest_change": None,
        "tasks": [
            {"code": f"TSK-{index + 1:03d}", "text": "Fix it", "status": "OPEN"}
            for index in range(tasks)
        ],
        "review_available": True,
    }


def acceptance_document(
    *, runs: int = 0, summary: dict[str, int] | None = None
) -> dict[str, object]:
    latest = (
        None
        if runs == 0
        else {
            "id": TEST_RUN,
            "finished_at": "2026-09-29T10:01:12+00:00",
            "summary": summary or TEST_SUMMARY,
        }
    )
    return {
        "project_id": PROJECT_ID,
        "reference": {"requirements": None, "design": None},
        "plan_available": True,
        "plans": 1 if runs else 0,
        "runs": runs,
        "latest_run": latest,
    }


def learning_entry(twin_id: str, name: str, label: str, observations: int) -> dict[str, object]:
    return {
        "twin_id": twin_id,
        "twin_name": name,
        "profile_version_number": 1,
        "development_version_number": int(label.split(".")[1]),
        "label": label,
        "observations": [
            {"code": f"OBS-{index:03d}", "statement": f"Statement {index}."}
            for index in range(1, observations + 1)
        ],
        "retired": [],
    }


LEARNED = [
    learning_entry(TWIN_OWNER, "Pizzeria owner", "1.2", 2),
    learning_entry(TWIN_WAITER, "Evening shift waiter", "1.0", 0),
]
EMPTY_LEARNING = {"project_id": PROJECT_ID, "update_available": False, "twins": []}
RUN_ID = "00000000-0000-4000-8000-00000000a001"
LATEST_RUN = {
    "id": RUN_ID,
    "from_commit": None,
    "to_commit": ALIGNED,
    "created_at": "2026-09-29T10:15:00+00:00",
    "requirements_version_number": 1,
    "design_version_number": 2,
    "alternative_code": "DES-002",
    "summary": "The code adds a split of the bill among friends.",
}
NO_KNOWLEDGE = {"items": [], "latest_run": None}
PROPOSALS_PATH = f"{BASE}/alignment/proposals?status=waiting"


def knowledge_document(*, waiting: int = 2) -> dict[str, object]:
    return {
        "items": [
            {"code": f"ALN-{index + 1:03d}", "section": "REQUIREMENTS", "status": "PROPOSED"}
            for index in range(waiting)
        ],
        "latest_run": dict(LATEST_RUN),
    }


def align_files(project: ProjectFolder, *, waiting: int = 1, run: bool = True) -> None:
    folder = project.local / "align"
    folder.mkdir(parents=True)
    latest = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "finished_at": "2026-09-29T10:20:00+00:00",
        "from_commit": None,
        "to_commit": ALIGNED,
        "proposals": 3,
        "waiting": waiting,
        "applied": 1,
        "skipped": 1,
    }
    (folder / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    if run:
        snapshot = {**LATEST_RUN, "project_id": PROJECT_ID, "commits": [ALIGNED], "proposals": []}
        (folder / f"{RUN_ID}.json").write_text(json.dumps(snapshot), encoding="utf-8")


def knowledge_line(language: str, count: int) -> str:
    return messages.text(
        "status.knowledge", language, commit="4f2a9c1", date="2026-09-29 10:15", count=count
    )


def expect_alignment(
    transport: ScriptedTransport, document: dict[str, object], recorded: int
) -> None:
    transport.expect("GET", f"{BASE}/alignment", body=document)
    transport.expect(
        "GET",
        f"{BASE}/code-changes",
        body={"items": [{"commit": f"{index:040x}"} for index in range(recorded)]},
    )


def expect_studio(
    transport: ScriptedTransport,
    *,
    stage: str = "USER_TWINS",
    action: str = "CONFIRM_TWINS",
    twins_approved: bool = False,
    later_approved: bool = False,
    folder: int | None = None,
    budget: bool = True,
    alignment: dict[str, object] | None = None,
    recorded: int = 3,
    routes: bool = True,
    tests: dict[str, object] | None = None,
    learning: dict[str, object] | None = None,
    billing: str | None = None,
    sections: dict[str, object] | None = None,
    knowledge: dict[str, object] | None = None,
) -> ScriptedTransport:
    requirements = version("requirements-1", 1, "hr")
    design = version("design-2", 2, "hd")
    transport.expect("GET", f"{API}/health", body={"status": "ok"})
    transport.expect(
        "GET",
        BASE,
        body={
            "id": PROJECT_ID,
            "display_name": "Calcolo mancia",
            "mode": "GREENFIELD_GENERATION",
            "current_stage": stage,
            "next_action": action,
        },
    )
    transport.expect("GET", f"{BASE}/brief-versions/current", body=version("brief-2", 2, "hb"))
    transport.expect("GET", f"{BASE}/gates/project-brief/current", body=gate("brief-2", "hb"))
    transport.expect(
        "GET",
        f"{BASE}/team-proposals/current",
        body={
            **version("team-1", 1, "ht"),
            "brief_version_number": 2,
            "brief_content_hash": "hb",
        },
    )
    transport.expect("GET", f"{BASE}/gates/agent-team/current", body=gate("team-1", "ht"))
    transport.expect("GET", f"{BASE}/readiness", body={"status": "READY_FOR_MAIN_WORKFLOW"})
    transport.expect(
        "GET",
        f"{BASE}/user-modeling/readiness",
        body={
            "snapshot_exists": True,
            "snapshot_version_number": 1,
            "approved_current_snapshot": twins_approved,
            "workflow_state": (
                "READY_FOR_REQUIREMENTS_DEFINITION"
                if twins_approved
                else "USER_MODELING_REVIEW_REQUIRED"
            ),
        },
    )
    transport.expect(
        "GET",
        f"{BASE}/requirements/readiness",
        body={
            "status": "READY_FOR_DESIGN_EXPLORATION" if later_approved else "REQUIREMENTS_REQUIRED",
            "version": requirements if later_approved else None,
            "gate": gate("requirements-1", "hr") if later_approved else None,
        },
    )
    transport.expect(
        "GET",
        f"{BASE}/design/readiness",
        body={
            "status": "READY_FOR_ARCHITECTURE_PLANNING" if later_approved else "DESIGN_REQUIRED",
            "version": design if later_approved else None,
            "gate": gate("design-2", "hd") if later_approved else None,
        },
    )
    transport.expect(
        "GET",
        f"{BASE}/knowledge-packages?limit=1",
        body={
            "project_id": PROJECT_ID,
            "versions": [] if folder is None else [{"version_number": folder}],
        },
    )
    if sections is None:
        transport.expect("GET", f"{BASE}/sections", status=404, body={"detail": "Not Found"})
    else:
        transport.expect("GET", f"{BASE}/sections", body=sections)
    if later_approved and routes:
        expect_alignment(
            transport, alignment_document() if alignment is None else alignment, recorded
        )
        transport.expect(
            "GET",
            f"{BASE}/acceptance-tests",
            body=acceptance_document() if tests is None else tests,
        )
        transport.expect(
            "GET", PROPOSALS_PATH, body=NO_KNOWLEDGE if knowledge is None else knowledge
        )
    elif later_approved:
        transport.expect("GET", f"{BASE}/alignment", status=404, body={"detail": "Not Found"})
        transport.expect(
            "GET", f"{BASE}/acceptance-tests", status=404, body={"detail": "Not Found"}
        )
        transport.expect("GET", PROPOSALS_PATH, status=404, body={"detail": "Not Found"})
    if twins_approved and routes:
        transport.expect(
            "GET", f"{BASE}/twin-learning", body=EMPTY_LEARNING if learning is None else learning
        )
    elif twins_approved:
        transport.expect("GET", f"{BASE}/twin-learning", status=404, body={"detail": "Not Found"})
    if budget:
        transport.expect(
            "GET",
            f"{API}/model-runtime/budget",
            body=BUDGET if billing is None else {**BUDGET, "billing": billing},
        )
        transport.expect(
            "GET",
            f"{BASE}/model-usage",
            body={"items": [], "totals": {"generations": 3, "cost_microusd": 420_000}},
        )
    else:
        transport.expect(
            "GET",
            f"{API}/model-runtime/budget",
            status=503,
            body={"detail": {"code": "REAL_MODEL_RUNTIME_NOT_CONFIGURED"}},
        )
    return transport


def local_manifest(project: ProjectFolder, number: int) -> None:
    stages = {
        stage: {"version_number": index + 1, "gate": {"status": "APPROVED"}}
        for index, stage in enumerate(("brief", "team", "twins", "requirements", "design"))
    }
    project.knowledge.mkdir(parents=True)
    (project.knowledge / "orchestwin.json").write_text(
        json.dumps(
            {
                "package": {"version_number": number, "content_hash": "c"},
                "project": {"id": PROJECT_ID, "name": "Calcolo mancia"},
                "stages": stages,
                "files": {},
            }
        ),
        encoding="utf-8",
    )


def signed_in_folder(tmp_path: Path) -> ProjectFolder:
    store_session(tmp_path)
    return link_folder(tmp_path / "project")


def test_status_from_the_studio_in_english(tmp_path: Path) -> None:
    signed_in_folder(tmp_path)
    transport = expect_studio(ScriptedTransport())

    run = run_ut(["status"], tmp_path, transport=transport)

    assert run.status == 0
    assert run.errors == ""
    assert run.output.splitlines() == [
        "Calcolo mancia",
        "==============",
        f"Studio: {LOCAL}",
        "Mode: design only",
        "",
        "Step                 State                      Version",
        "-------------------  -------------------------  -------",
        "Brief                approved                   2",
        "Perspectives         approved                   1",
        "User Twin            waiting for your approval  1",
        "Definition           later                      -",
        "Design & Evaluation  later                      -",
        "Dossier              later                      -",
        "",
        "Next step: Confirm the twins: launch `ut init`.",
        "Knowledge folder: not published yet.",
        "Spent on this project: 0.42 USD. Credit left in the Studio: 25.13 USD.",
    ]
    transport.assert_done()


def test_status_from_the_studio_in_italian_with_an_older_folder(tmp_path: Path) -> None:
    project = signed_in_folder(tmp_path)
    local_manifest(project, 2)
    transport = expect_studio(
        ScriptedTransport(),
        stage="PACKAGE",
        action="DOWNLOAD_FOLDER",
        twins_approved=True,
        later_approved=True,
        folder=3,
    )

    run = run_ut(["--lang", "it", "status"], tmp_path, transport=transport)

    assert run.status == 0
    lines = run.output.splitlines()
    assert lines[3] == "Modalità: solo design"
    assert lines[5:13] == [
        "Passo                 Stato                Versione",
        "--------------------  -------------------  --------",
        "Brief                 approvato            2",
        "Prospettive           approvato            1",
        "User Twin             approvato            1",
        "Definizione           approvato            1",
        "Design e valutazione  approvato            2",
        "Dossier               pronto da scaricare  3",
    ]
    assert lines[14:] == [
        "Prossimo passo: Scarica la cartella di conoscenza: lancia `ut package publish`.",
        "Cartella di conoscenza: versione 2 in questa cartella, versione 3 nello Studio.",
        "La cartella qui è più vecchia: aggiornala con `ut package pull`.",
        "Sviluppo: commit registrati: 3; dopo il punto allineato: 1; commit allineato: "
        "4f2a9c1; compiti aperti per il codice: 1.",
        "Spesa del progetto: 0,42 USD. Credito rimasto nello Studio: 25,13 USD.",
    ]


def test_a_folder_at_the_version_of_the_studio_sends_the_development_to_ut_verify(
    tmp_path: Path,
) -> None:
    project = signed_in_folder(tmp_path)
    local_manifest(project, 3)
    transport = expect_studio(
        ScriptedTransport(),
        stage="PACKAGE",
        action="DOWNLOAD_FOLDER",
        twins_approved=True,
        later_approved=True,
        folder=3,
        alignment=alignment_document(aligned=None, pending=2, tasks=0),
        recorded=2,
    )

    run = run_ut(["status"], tmp_path, transport=transport)

    assert run.status == 0
    lines = run.output.splitlines()
    assert lines[14:] == [
        "Next step: The knowledge folder is up to date: the development goes on with these "
        "commands:",
        *AFTER_DESIGN["en"],
        "Knowledge folder: version 3 in this folder, version 3 in the Studio.",
        "Development: commits recorded: 2; none aligned yet (waiting: 2); open tasks for the "
        "code: 0.",
        "Spent on this project: 0.42 USD. Credit left in the Studio: 25.13 USD.",
    ]
    transport.assert_done()


def test_the_development_as_json_and_when_nothing_is_recorded(tmp_path: Path) -> None:
    project = signed_in_folder(tmp_path)
    local_manifest(project, 3)
    studio = dict(
        stage="PACKAGE",
        action="DOWNLOAD_FOLDER",
        twins_approved=True,
        later_approved=True,
        folder=3,
    )
    first = expect_studio(ScriptedTransport(), **studio)
    empty = expect_studio(
        ScriptedTransport(),
        **studio,
        alignment=alignment_document(aligned=None, pending=0, tasks=0),
        recorded=0,
    )

    document = json.loads(run_ut(["status", "--json"], tmp_path, transport=first).output)
    nothing = run_ut(["status"], tmp_path, transport=empty)

    assert document["alignment"] == {
        "recorded": 3,
        "pending": 1,
        "aligned_commit": ALIGNED,
        "open_tasks": 1,
        "stale_reviews": 0,
    }
    assert document["next_command"] == "ut verify"
    assert (
        "Development: no commit recorded yet. After your first commit launch `ut verify`."
        in nothing.output.splitlines()
    )


def test_a_studio_without_the_routes_of_the_development_shows_no_line(tmp_path: Path) -> None:
    signed_in_folder(tmp_path)
    transport = expect_studio(
        ScriptedTransport(),
        stage="PACKAGE",
        action="DOWNLOAD_FOLDER",
        twins_approved=True,
        later_approved=True,
        folder=3,
        routes=False,
    )

    run = run_ut(["status", "--json"], tmp_path, transport=transport)

    document = json.loads(run.output)
    assert run.status == 0
    assert document["alignment"] is None
    assert document["next_command"] == "ut package publish"
    transport.assert_done()


def test_offline_the_development_comes_from_the_folder(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    project.knowledge.mkdir(parents=True)
    stages = ("brief", "team", "twins", "requirements", "design")
    manifest = {
        "schema_version": 3,
        "package": {"version_number": 5, "content_hash": "c"},
        "project": {"id": PROJECT_ID, "name": "Calcolo mancia"},
        "stages": {
            stage: {"version_number": 1, "gate": {"status": "APPROVED"}} for stage in stages
        },
        "progress": {"approved": list(stages), "pending": None, "complete": True},
        "state": {
            "document": "state/state.json",
            "text": "state/state.md",
            "changes": 4,
            "pending_changes": 2,
            "aligned_commit": ALIGNED,
            "open_tasks": 3,
        },
        "files": {},
    }
    (project.knowledge / "orchestwin.json").write_text(json.dumps(manifest), encoding="utf-8")

    text = run_ut(["--lang", "it", "status", "--offline"], tmp_path, transport=ScriptedTransport())
    document = json.loads(
        run_ut(["status", "--offline", "--json"], tmp_path, transport=ScriptedTransport()).output
    )

    assert (
        "Sviluppo: commit registrati: 4; dopo il punto allineato: 2; commit allineato: "
        "4f2a9c1; compiti aperti per il codice: 3." in text.output.splitlines()
    )
    assert document["alignment"] == {
        "recorded": 4,
        "pending": 2,
        "aligned_commit": ALIGNED,
        "open_tasks": 3,
        "stale_reviews": 0,
    }


def test_offline_a_partial_folder_and_the_saved_steps_are_read_together(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    project.save_step("brief", version("brief-2", 2, "hb"), gate("brief-2", "hb"), START)
    project.save_step("team", version("team-1", 1, "ht"), gate("team-1", "ht"), START)
    project.save_step("twins", version("twins-4", 4, "hw"), gate("twins-4", "hw"), START)
    project.knowledge.mkdir(parents=True)
    manifest = {
        "schema_version": 3,
        "package": {"version_number": 2, "content_hash": "c"},
        "project": {"id": PROJECT_ID, "name": "Calcolo mancia"},
        "stages": {
            "brief": {"version_number": 3, "gate": {"status": "APPROVED"}},
            "team": {"version_number": 1, "gate": {"status": "APPROVED"}},
        },
        "progress": {"approved": ["brief", "team"], "pending": "twins", "complete": False},
        "state": {"changes": 0, "pending_changes": 0, "aligned_commit": None, "open_tasks": 0},
        "files": {},
    }
    (project.knowledge / "orchestwin.json").write_text(json.dumps(manifest), encoding="utf-8")

    run = run_ut(["status", "--offline", "--json"], tmp_path, transport=ScriptedTransport())

    document = json.loads(run.output)
    assert [(step["stage"], step["version"]) for step in document["steps"]][:4] == [
        ("brief", 3),
        ("team", 1),
        ("twins", 4),
        ("requirements", None),
    ]
    assert document["alignment"] is None


def test_without_a_budget_the_spending_is_not_shown(tmp_path: Path) -> None:
    signed_in_folder(tmp_path)
    transport = expect_studio(ScriptedTransport(), budget=False)

    run = run_ut(["status"], tmp_path, transport=transport)

    assert run.status == 0
    assert "Spent" not in run.output
    transport.assert_done()


def test_status_as_json_from_the_studio(tmp_path: Path) -> None:
    project = signed_in_folder(tmp_path)
    transport = expect_studio(ScriptedTransport())

    run = run_ut(["status", "--json"], tmp_path, transport=transport)

    document = json.loads(run.output)
    assert run.status == 0
    assert document["schema_version"] == 1
    assert document["kind"] == "project"
    assert (document["source"], document["reason"]) == ("studio", None)
    assert document["studio"] == LOCAL
    assert document["project"] == {
        "id": PROJECT_ID,
        "name": "Calcolo mancia",
        "mode": "DESIGN_ONLY",
        "language": None,
        "root": str(project.root),
    }
    assert (document["current_stage"], document["next_action"]) == ("USER_TWINS", "CONFIRM_TWINS")
    assert document["next_command"] == "ut init"
    assert document["steps"][2] == {
        "stage": "twins",
        "state": "WAITING",
        "version": 1,
        "approved": False,
    }
    assert [step["stage"] for step in document["steps"]] == [
        "brief",
        "team",
        "twins",
        "requirements",
        "design",
        "package",
    ]
    assert document["knowledge_folder"] == {
        "local_version": None,
        "studio_version": None,
        "local_error": None,
    }
    assert document["spending"] == {
        "currency": "USD",
        "project_spent_usd": 0.42,
        "remaining_usd": 25.13,
        "billing": "API",
    }
    assert document["alignment"] is None
    assert document["tests"] is None
    assert document["learning"] is None
    assert document["sections"] is None
    assert document["knowledge_alignment"] is None
    assert list(document)[-5:] == [
        "alignment",
        "tests",
        "learning",
        "sections",
        "knowledge_alignment",
    ]


@pytest.mark.parametrize(
    ("language", "line"),
    [
        ("en", "Generations run on the Claude subscription: no credit is spent."),
        ("it", "Le generazioni usano l'abbonamento di Claude: nessun credito speso."),
    ],
)
def test_on_the_subscription_the_status_says_that_no_credit_is_spent(
    tmp_path: Path, language: str, line: str
) -> None:
    signed_in_folder(tmp_path)
    text = expect_studio(ScriptedTransport(), billing="SUBSCRIPTION")
    as_json = expect_studio(ScriptedTransport(), billing="SUBSCRIPTION")

    run = run_ut(["--lang", language, "status"], tmp_path, transport=text)
    document = json.loads(run_ut(["status", "--json"], tmp_path, transport=as_json).output)

    assert run.status == 0, run.errors
    assert run.output.splitlines()[-1] == line
    assert "USD" not in run.output
    assert document["spending"] == {
        "currency": "USD",
        "project_spent_usd": 0.42,
        "remaining_usd": 25.13,
        "billing": "SUBSCRIPTION",
    }
    text.assert_done()
    as_json.assert_done()


@pytest.mark.parametrize("billing", ["MIXED", "API"])
def test_with_paid_routes_the_spending_and_the_credit_are_shown(
    tmp_path: Path, billing: str
) -> None:
    signed_in_folder(tmp_path)
    text = expect_studio(ScriptedTransport(), billing=billing)
    as_json = expect_studio(ScriptedTransport(), billing=billing)

    run = run_ut(["status"], tmp_path, transport=text)
    document = json.loads(run_ut(["status", "--json"], tmp_path, transport=as_json).output)

    assert run.output.splitlines()[-1] == (
        "Spent on this project: 0.42 USD. Credit left in the Studio: 25.13 USD."
    )
    assert document["spending"]["billing"] == billing
    assert list(document["spending"]) == [
        "currency",
        "project_spent_usd",
        "remaining_usd",
        "billing",
    ]


def saved_steps(project: ProjectFolder) -> None:
    project.save_step("brief", version("brief-2", 2, "hb"), gate("brief-2", "hb"), START)
    project.save_step("team", version("team-1", 1, "ht"), gate("team-1", "ht"), START)


@pytest.mark.parametrize(
    ("language", "reason_line", "next_line"),
    [
        (
            "en",
            "State read from this folder, as asked with --offline.",
            "Next step: Confirm the twins: launch `ut init`.",
        ),
        (
            "it",
            "Stato letto da questa cartella, come chiesto con --offline.",
            "Prossimo passo: Conferma i twin: lancia `ut init`.",
        ),
    ],
)
def test_offline_status_reads_only_the_folder(
    tmp_path: Path, language: str, reason_line: str, next_line: str
) -> None:
    saved_steps(link_folder(tmp_path / "project"))

    run = run_ut(
        ["--lang", language, "status", "--offline"], tmp_path, transport=ScriptedTransport()
    )

    assert run.status == 0
    lines = run.output.splitlines()
    assert lines[4] == reason_line
    assert [line.split()[-1] for line in lines[8:14]] == ["2", "1", "-", "-", "-", "-"]
    assert lines[15] == next_line
    assert len(lines) == 16


def test_offline_status_uses_the_manifest_of_the_knowledge_folder(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    local_manifest(project, 4)

    run = run_ut(["status", "--offline", "--json"], tmp_path, transport=ScriptedTransport())

    document = json.loads(run.output)
    assert (document["source"], document["reason"]) == ("folder", "requested")
    assert [step["state"] for step in document["steps"]] == ["APPROVED"] * 5 + ["READY"]
    assert document["steps"][-1]["version"] == 4
    assert document["knowledge_folder"]["local_version"] == 4
    assert document["next_action"] == "DOWNLOAD_FOLDER"
    assert document["next_command"] == "ut verify"
    assert document["spending"] is None


@pytest.mark.parametrize(
    ("language", "line"),
    [
        (
            "en",
            "Next step: The knowledge folder is up to date: the development goes on with these "
            "commands:",
        ),
        (
            "it",
            "Prossimo passo: La cartella di conoscenza è aggiornata: lo sviluppo continua con "
            "questi comandi:",
        ),
    ],
)
def test_offline_a_complete_folder_names_the_commands_that_follow_the_design(
    tmp_path: Path, language: str, line: str
) -> None:
    project = link_folder(tmp_path / "project")
    local_manifest(project, 4)

    run = run_ut(
        ["--lang", language, "status", "--offline"], tmp_path, transport=ScriptedTransport()
    )

    lines = run.output.splitlines()
    position = lines.index(line)
    assert run.status == 0
    assert lines[position + 1 : position + 8] == AFTER_DESIGN[language]


def test_offline_a_partial_folder_still_asks_to_download_the_complete_one(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    for number, stage in enumerate(("brief", "team", "twins", "requirements", "design"), 1):
        identifier = f"{stage}-{number}"
        project.save_step(
            stage, version(identifier, 1, f"h{number}"), gate(identifier, f"h{number}"), START
        )
    project.knowledge.mkdir(parents=True)
    stages = ("brief", "team", "twins", "requirements")
    manifest = {
        "schema_version": 3,
        "package": {"version_number": 3, "content_hash": "c"},
        "project": {"id": PROJECT_ID, "name": "Calcolo mancia"},
        "stages": {
            stage: {"version_number": 1, "gate": {"status": "APPROVED"}} for stage in stages
        },
        "progress": {"approved": list(stages), "pending": "design", "complete": False},
        "files": {},
    }
    (project.knowledge / "orchestwin.json").write_text(json.dumps(manifest), encoding="utf-8")

    run = run_ut(["status", "--offline"], tmp_path, transport=ScriptedTransport())
    document = json.loads(
        run_ut(["status", "--offline", "--json"], tmp_path, transport=ScriptedTransport()).output
    )

    assert run.status == 0
    assert (
        "Next step: Download the knowledge folder: launch `ut package publish`."
        in run.output.splitlines()
    )
    assert document["next_command"] == "ut package publish"


def test_without_sign_in_the_folder_is_read_and_nothing_is_sent(tmp_path: Path) -> None:
    saved_steps(link_folder(tmp_path / "project"))
    transport = ScriptedTransport()

    run = run_ut(["status"], tmp_path, transport=transport)

    assert run.status == 0
    assert (
        "State read from this folder: you are not signed in to the Studio "
        f"{LOCAL} (`ut login`)." in run.output
    )
    assert transport.sent == []


def test_a_studio_that_does_not_answer_gives_the_folder(tmp_path: Path) -> None:
    signed_in_folder(tmp_path)
    transport = ScriptedTransport().expect("GET", f"{API}/health", unreachable=True)

    run = run_ut(["status", "--json"], tmp_path, transport=transport)

    document = json.loads(run.output)
    assert (document["source"], document["reason"]) == ("folder", "unreachable")
    assert run.slept == 0
    assert len(transport.sent) == 1


def test_an_expired_sign_in_gives_the_folder(tmp_path: Path) -> None:
    store_session(tmp_path, expires_at=START - timedelta(minutes=1))
    link_folder(tmp_path / "project")
    transport = ScriptedTransport()
    transport.expect("GET", f"{API}/health", body={"status": "ok"})
    transport.expect("POST", f"{API}/auth/refresh", status=401, body={"detail": "expired"})

    run = run_ut(["status"], tmp_path, transport=transport)

    assert run.status == 0
    assert f"your sign-in to the Studio {LOCAL} has expired" in run.output
    transport.assert_done()


def test_a_project_the_studio_does_not_know_gives_the_folder(tmp_path: Path) -> None:
    signed_in_folder(tmp_path)
    transport = ScriptedTransport()
    transport.expect("GET", f"{API}/health", body={"status": "ok"})
    transport.expect("GET", BASE, status=404, body={"detail": "project_not_found"})

    run = run_ut(["status"], tmp_path, transport=transport)

    assert run.status == 0
    assert "does not find this project for your account" in run.output


def projects_list() -> list[dict[str, object]]:
    return [
        {
            "id": PROJECT_ID,
            "display_name": "Calcolo mancia",
            "current_stage": "USER_TWINS",
            "next_action": "CONFIRM_TWINS",
        },
        {
            "id": "other",
            "display_name": "Registro prestiti",
            "current_stage": "PACKAGE",
            "next_action": "DOWNLOAD_FOLDER",
        },
    ]


def test_outside_a_linked_folder_the_projects_are_listed(tmp_path: Path) -> None:
    store_session(tmp_path)
    transport = ScriptedTransport().expect("GET", f"{API}/projects", body=projects_list())

    run = run_ut(["status"], tmp_path, transport=transport)

    assert run.status == 0
    assert run.output.splitlines() == [
        f"Projects in the Studio {LOCAL}",
        "=" * len(f"Projects in the Studio {LOCAL}"),
        "Project            Step               Your turn",
        "-----------------  -----------------  ------------------------------------------",
        "Calcolo mancia     3 of 6: User Twin  Confirm the twins: launch `ut init`.",
        "Registro prestiti  6 of 6: Dossier    Download the knowledge folder: launch `ut",
        "                                      package publish`.",
    ]


def test_all_projects_mark_the_linked_one_in_italian_json(tmp_path: Path) -> None:
    signed_in_folder(tmp_path)
    transport = ScriptedTransport().expect("GET", f"{API}/projects", body=projects_list())

    run = run_ut(["--lang", "it", "status", "--all", "--json"], tmp_path, transport=transport)

    document = json.loads(run.output)
    assert document["kind"] == "projects"
    assert [item["linked"] for item in document["projects"]] == [True, False]
    assert [item["next_command"] for item in document["projects"]] == [
        "ut init",
        "ut package publish",
    ]


@pytest.mark.parametrize("language", ["en", "it"])
def test_all_projects_use_the_available_sections_gesture_in_text_and_json(
    tmp_path: Path, language: str
) -> None:
    signed_in_folder(tmp_path)
    project = projects_list()[0] | {"current_stage": "TEAM", "next_action": "UPDATE_SECTIONS"}
    table = ScriptedTransport().expect("GET", f"{API}/projects", body=[project])
    as_json = ScriptedTransport().expect("GET", f"{API}/projects", body=[project])
    run = run_ut(["--lang", language, "status", "--all"], tmp_path, transport=table)
    document = json.loads(run_ut(["status", "--all", "--json"], tmp_path, transport=as_json).output)
    assert run.status == 0
    assert "`ut" in run.output and "sections update`." in run.output
    assert "ut package publish" not in run.output
    assert document["projects"][0]["next_action"] == "UPDATE_SECTIONS"
    assert document["projects"][0]["next_command"] == "ut sections update"


@pytest.mark.parametrize("language", ["en", "it"])
@pytest.mark.parametrize(
    ("stage", "action", "command"),
    [
        ("USER_TWINS", "PREPARE_TWINS", "ut init"),
        ("DESIGN", "PREPARE_DESIGN", "ut design regenerate"),
    ],
)
def test_all_projects_name_preparation_of_obsolete_artifacts(
    tmp_path: Path, language: str, stage: str, action: str, command: str
) -> None:
    signed_in_folder(tmp_path)
    project = projects_list()[0] | {"current_stage": stage, "next_action": action}
    table = ScriptedTransport().expect("GET", f"{API}/projects", body=[project])
    as_json = ScriptedTransport().expect("GET", f"{API}/projects", body=[project])
    run = run_ut(["--lang", language, "status", "--all"], tmp_path, transport=table)
    document = json.loads(run_ut(["status", "--all", "--json"], tmp_path, transport=as_json).output)
    assert run.status == 0
    assert ("Prepara di nuovo" if language == "it" else "Prepare the") in run.output
    assert document["projects"][0]["next_action"] == action
    assert document["projects"][0]["next_command"] == command


def test_all_projects_in_a_table_mark_this_folder(tmp_path: Path) -> None:
    signed_in_folder(tmp_path)
    transport = ScriptedTransport().expect("GET", f"{API}/projects", body=projects_list())

    run = run_ut(["--lang", "it", "status", "--all"], tmp_path, transport=transport)

    lines = run.output.splitlines()
    assert lines[4].startswith("Calcolo mancia (questa ")
    assert lines[5].startswith("cartella)")
    assert "3 di 6: User Twin" in lines[4]
    assert all(len(line) <= 80 for line in lines)


def test_an_account_without_projects(tmp_path: Path) -> None:
    store_session(tmp_path)
    transport = ScriptedTransport().expect("GET", f"{API}/projects", body=[])

    run = run_ut(["status"], tmp_path, transport=transport)

    assert (
        run.output.splitlines()[-1] == "Your account has no project yet. Create one with `ut init`."
    )


def test_the_list_needs_a_sign_in(tmp_path: Path) -> None:
    run = run_ut(["status"], tmp_path, transport=ScriptedTransport())

    assert run.status == 3
    assert run.errors == (
        f"You are not signed in to the Studio {LOCAL}. Sign in with `ut login`.\n"
    )


def test_offline_outside_a_linked_folder_is_not_linked(tmp_path: Path) -> None:
    run = run_ut(["status", "--offline"], tmp_path, transport=ScriptedTransport())

    assert run.status == 6
    assert "is not linked to a project" in run.errors


def test_offline_and_all_together_are_wrong_usage(tmp_path: Path) -> None:
    run = run_ut(["status", "--offline", "--all"], tmp_path, transport=ScriptedTransport())

    assert run.status == 2
    assert "not allowed with argument" in run.errors


def test_a_broken_knowledge_folder_is_reported(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    project.knowledge.mkdir(parents=True)
    (project.knowledge / "orchestwin.json").write_text("{", encoding="utf-8")

    run = run_ut(["status", "--offline"], tmp_path, transport=ScriptedTransport())

    assert run.status == 0
    assert (
        "The knowledge folder here cannot be read (FOLDER_DOCUMENT_INVALID): check it with "
        "`ut package verify`." in run.output
    )


def folder_with_tests(project: ProjectFolder, runs: int, tests: object) -> None:
    project.knowledge.mkdir(parents=True)
    stages = ("brief", "team", "twins", "requirements", "design")
    manifest = {
        "schema_version": 3,
        "package": {"version_number": 5, "content_hash": "c"},
        "project": {"id": PROJECT_ID, "name": "Calcolo mancia"},
        "stages": {
            stage: {"version_number": 1, "gate": {"status": "APPROVED"}} for stage in stages
        },
        "progress": {"approved": list(stages), "pending": None, "complete": True},
        "feedback": {"tests": "twins/feedback/tests.json", "test_runs": runs},
        "files": {},
    }
    (project.knowledge / "orchestwin.json").write_text(json.dumps(manifest), encoding="utf-8")
    feedback = project.knowledge / "twins" / "feedback"
    feedback.mkdir(parents=True)
    (feedback / "tests.json").write_text(json.dumps(tests), encoding="utf-8")


def local_tests_document() -> dict[str, object]:
    return {
        "schema_version": 3,
        "kind": "orchestwin.test-reviews",
        "project_id": PROJECT_ID,
        "runs": [
            {
                "id": TEST_RUN,
                "finished_at": "2026-09-29T12:30:00+02:00",
                "summary": {"passed": 1, "failed": 0, "blocked": 0, "not_covered": 1},
            }
        ],
    }


@pytest.mark.parametrize(
    ("language", "line"),
    [
        (
            "en",
            "Acceptance tests: latest run on 2026-09-29 10:01 UTC: 3 passed, 1 failed, 1 blocked, "
            "2 not covered.",
        ),
        (
            "it",
            "Verifica dei criteri: ultima esecuzione il 2026-09-29 10:01 UTC: 3 superati, 1 "
            "falliti, 1 bloccati, 2 non coperti.",
        ),
    ],
)
def test_the_latest_run_of_the_tests_follows_the_development_line(
    tmp_path: Path, language: str, line: str
) -> None:
    signed_in_folder(tmp_path)
    studio = dict(
        stage="PACKAGE",
        action="DOWNLOAD_FOLDER",
        twins_approved=True,
        later_approved=True,
        folder=3,
        tests=acceptance_document(runs=2),
    )
    text = expect_studio(ScriptedTransport(), **studio)
    as_json = expect_studio(ScriptedTransport(), **studio)

    run = run_ut(["--lang", language, "status"], tmp_path, transport=text)
    document = json.loads(run_ut(["status", "--json"], tmp_path, transport=as_json).output)

    lines = run.output.splitlines()
    position = lines.index(line)
    assert lines[position - 1].startswith(("Development:", "Sviluppo:"))
    assert lines[position + 1].startswith(("Spent", "Spesa"))
    assert document["tests"] == {
        "runs": 2,
        "latest": {
            "id": TEST_RUN,
            "finished_at": "2026-09-29T10:01:12+00:00",
            "summary": TEST_SUMMARY,
        },
    }
    assert list(document)[-4:] == ["tests", "learning", "sections", "knowledge_alignment"]
    text.assert_done()


def test_a_studio_without_runs_shows_no_line_of_the_tests(tmp_path: Path) -> None:
    signed_in_folder(tmp_path)
    studio = dict(
        stage="PACKAGE",
        action="DOWNLOAD_FOLDER",
        twins_approved=True,
        later_approved=True,
        folder=3,
    )

    run = run_ut(["status"], tmp_path, transport=expect_studio(ScriptedTransport(), **studio))
    document = json.loads(
        run_ut(
            ["status", "--json"], tmp_path, transport=expect_studio(ScriptedTransport(), **studio)
        ).output
    )

    assert not any(line.startswith("Acceptance tests") for line in run.output.splitlines())
    assert document["tests"] is None


def test_a_studio_without_the_route_of_the_tests_leaves_them_to_the_folder(
    tmp_path: Path,
) -> None:
    project = signed_in_folder(tmp_path)
    folder_with_tests(project, 1, local_tests_document())
    transport = expect_studio(
        ScriptedTransport(),
        stage="PACKAGE",
        action="DOWNLOAD_FOLDER",
        twins_approved=True,
        later_approved=True,
        folder=5,
        routes=False,
    )

    run = run_ut(["status"], tmp_path, transport=transport)

    assert (
        "Acceptance tests: latest run on 2026-09-29 10:30 UTC: 1 passed, 0 failed, 0 blocked, "
        "1 not covered." in run.output.splitlines()
    )
    transport.assert_done()


def test_offline_the_tests_come_from_the_folder(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    folder_with_tests(project, 2, local_tests_document())

    run = run_ut(["status", "--offline"], tmp_path, transport=ScriptedTransport())
    document = json.loads(
        run_ut(["status", "--offline", "--json"], tmp_path, transport=ScriptedTransport()).output
    )

    assert (
        "Acceptance tests: latest run on 2026-09-29 10:30 UTC: 1 passed, 0 failed, 0 blocked, "
        "1 not covered." in run.output.splitlines()
    )
    assert document["tests"] == {
        "runs": 2,
        "latest": {
            "id": TEST_RUN,
            "finished_at": "2026-09-29T12:30:00+02:00",
            "summary": {"passed": 1, "failed": 0, "blocked": 0, "not_covered": 1, "not_run": 0},
        },
    }


@pytest.mark.parametrize(
    ("runs", "tests", "expected"),
    [
        (0, {"runs": []}, None),
        (2, "not an object", {"runs": 2, "latest": None}),
        (1, {"runs": []}, {"runs": 1, "latest": None}),
    ],
)
def test_offline_a_folder_without_a_readable_run_shows_no_line(
    tmp_path: Path, runs: int, tests: object, expected: object
) -> None:
    project = link_folder(tmp_path / "project")
    folder_with_tests(project, runs, tests)

    run = run_ut(["status", "--offline"], tmp_path, transport=ScriptedTransport())
    document = json.loads(
        run_ut(["status", "--offline", "--json"], tmp_path, transport=ScriptedTransport()).output
    )

    assert not any(line.startswith("Acceptance tests") for line in run.output.splitlines())
    assert document["tests"] == expected


def test_status_from_a_subfolder_and_from_the_project_option(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "work" / "tip")
    inner = project.root / "src"
    inner.mkdir()

    below = run_ut(
        ["status", "--offline", "--json"],
        tmp_path,
        transport=ScriptedTransport(),
        working_directory=inner,
    )
    option = run_ut(
        ["--project-dir", str(Path("work") / "tip"), "status", "--offline", "--json"],
        tmp_path,
        transport=ScriptedTransport(),
        working_directory=tmp_path,
    )

    assert json.loads(below.output)["project"]["root"] == str(project.root)
    assert json.loads(option.output)["project"]["root"] == str(project.root)


PACKAGE_STEP = {
    "stage": "PACKAGE",
    "action": "DOWNLOAD_FOLDER",
    "twins_approved": True,
    "later_approved": True,
    "folder": 3,
}


def folder_with_state(
    project: ProjectFolder,
    *,
    state: dict[str, object] | None = None,
    learned: object = None,
    listed: bool = True,
) -> None:
    project.knowledge.mkdir(parents=True)
    stages = ("brief", "team", "twins", "requirements", "design")
    manifest: dict[str, object] = {
        "schema_version": 3,
        "package": {"version_number": 5, "content_hash": "c"},
        "project": {"id": PROJECT_ID, "name": "Calcolo mancia"},
        "stages": {
            stage: {"version_number": 1, "gate": {"status": "APPROVED"}} for stage in stages
        },
        "progress": {"approved": list(stages), "pending": None, "complete": True},
        "state": state
        or {"changes": 2, "pending_changes": 1, "aligned_commit": None, "open_tasks": 0},
        "files": {},
    }
    if listed:
        manifest["feedback"] = {"learned": "twins/feedback/learned.json", "learned_observations": 2}
    (project.knowledge / "orchestwin.json").write_text(json.dumps(manifest), encoding="utf-8")
    if learned is not None:
        feedback = project.knowledge / "twins" / "feedback"
        feedback.mkdir(parents=True)
        document = {
            "schema_version": 3,
            "kind": "orchestwin.twin-learning",
            "project_id": PROJECT_ID,
            "twins": learned,
        }
        (feedback / "learned.json").write_text(json.dumps(document), encoding="utf-8")


def learning_line(language: str, twins: list[tuple[str, str, int]]) -> str:
    listed = "; ".join(
        messages.text("status.learning_twin", language, name=name, label=label, count=count)
        for name, label, count in twins
    )
    return messages.text("status.learning", language, twins=listed)


LEARNED_TWINS = {
    "twins": [
        {"twin_id": TWIN_OWNER, "name": "Pizzeria owner", "label": "1.2", "observations": 2},
        {"twin_id": TWIN_WAITER, "name": "Evening shift waiter", "label": "1.0", "observations": 0},
    ]
}


@pytest.mark.parametrize("language", ["en", "it"])
def test_stale_reviews_join_the_development_line_and_the_json(
    tmp_path: Path, language: str
) -> None:
    signed_in_folder(tmp_path)
    studio = {**PACKAGE_STEP, "alignment": alignment_document(stale=2)}
    text = expect_studio(ScriptedTransport(), **studio)
    as_json = expect_studio(ScriptedTransport(), **studio)

    run = run_ut(["--lang", language, "status"], tmp_path, transport=text)
    document = json.loads(run_ut(["status", "--json"], tmp_path, transport=as_json).output)

    development = messages.text(
        "status.alignment", language, recorded=3, pending=1, commit="4f2a9c1", tasks=1
    )
    stale = messages.text("status.stale_reviews", language, count=2)
    assert f"{development} {stale}" in run.output.splitlines()
    assert "`ut verify --recheck`" in stale
    assert document["alignment"] == {
        "recorded": 3,
        "pending": 1,
        "aligned_commit": ALIGNED,
        "open_tasks": 1,
        "stale_reviews": 2,
    }
    assert list(document["alignment"])[-1] == "stale_reviews"
    assert document["learning"] is None
    text.assert_done()
    as_json.assert_done()


def test_without_stale_reviews_the_development_line_stays_as_it_was(tmp_path: Path) -> None:
    signed_in_folder(tmp_path)
    transport = expect_studio(ScriptedTransport(), **PACKAGE_STEP)

    run = run_ut(["status"], tmp_path, transport=transport)

    assert (
        "Development: commits recorded: 3; after the aligned point: 1; aligned commit: 4f2a9c1; "
        "open tasks for the code: 1." in run.output.splitlines()
    )


@pytest.mark.parametrize("language", ["en", "it"])
def test_offline_the_stale_reviews_come_from_the_manifest(tmp_path: Path, language: str) -> None:
    project = link_folder(tmp_path / "project")
    state = {
        "changes": 2,
        "pending_changes": 2,
        "stale_reviews": 1,
        "aligned_commit": None,
        "open_tasks": 0,
    }
    folder_with_state(project, state=state, listed=False)

    run = run_ut(
        ["--lang", language, "status", "--offline"], tmp_path, transport=ScriptedTransport()
    )
    document = json.loads(
        run_ut(["status", "--offline", "--json"], tmp_path, transport=ScriptedTransport()).output
    )

    development = messages.text(
        "status.alignment_not_aligned", language, recorded=2, pending=2, tasks=0
    )
    stale = messages.text("status.stale_reviews", language, count=1)
    assert f"{development} {stale}" in run.output.splitlines()
    assert document["alignment"]["stale_reviews"] == 1
    assert document["learning"] is None


@pytest.mark.parametrize("value", [None, -1, "2", True])
def test_offline_a_missing_or_wrong_count_of_stale_reviews_is_zero(
    tmp_path: Path, value: object
) -> None:
    project = link_folder(tmp_path / "project")
    state: dict[str, object] = {
        "changes": 2,
        "pending_changes": 2,
        "aligned_commit": None,
        "open_tasks": 0,
    }
    if value is not None:
        state["stale_reviews"] = value
    folder_with_state(project, state=state, listed=False)

    document = json.loads(
        run_ut(["status", "--offline", "--json"], tmp_path, transport=ScriptedTransport()).output
    )

    assert document["alignment"]["stale_reviews"] == 0


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_knowledge_line_follows_the_development_and_the_json_ends_with_it(
    tmp_path: Path, language: str
) -> None:
    signed_in_folder(tmp_path)
    studio = {**PACKAGE_STEP, "knowledge": knowledge_document(waiting=2)}
    text = expect_studio(ScriptedTransport(), **studio)
    as_json = expect_studio(ScriptedTransport(), **studio)

    run = run_ut(["--lang", language, "status"], tmp_path, transport=text)
    document = json.loads(run_ut(["status", "--json"], tmp_path, transport=as_json).output)

    lines = run.output.splitlines()
    position = lines.index(knowledge_line(language, 2))
    assert lines[position - 1].startswith(("Development:", "Sviluppo:"))
    assert lines[position + 1].startswith(("Spent", "Spesa"))
    assert document["knowledge_alignment"] == {"latest_run": LATEST_RUN, "waiting": 2}
    assert list(document)[-1] == "knowledge_alignment"
    text.assert_done()
    as_json.assert_done()


def test_without_a_run_the_knowledge_line_is_absent_and_the_json_counts_zero(
    tmp_path: Path,
) -> None:
    signed_in_folder(tmp_path)
    text = expect_studio(ScriptedTransport(), **PACKAGE_STEP)
    as_json = expect_studio(ScriptedTransport(), **PACKAGE_STEP)

    run = run_ut(["status"], tmp_path, transport=text)
    document = json.loads(run_ut(["status", "--json"], tmp_path, transport=as_json).output)

    assert not any(line.startswith("Knowledge:") for line in run.output.splitlines())
    assert document["knowledge_alignment"] == {"latest_run": None, "waiting": 0}
    text.assert_done()


def test_a_studio_without_the_route_of_the_knowledge_leaves_it_to_the_folder(
    tmp_path: Path,
) -> None:
    project = signed_in_folder(tmp_path)
    align_files(project, waiting=1)
    transport = expect_studio(ScriptedTransport(), **PACKAGE_STEP)
    transport.expected = [item for item in transport.expected if item.path != PROPOSALS_PATH]
    transport.expect("GET", PROPOSALS_PATH, status=404, body={"detail": "Not Found"})

    run = run_ut(["status", "--json"], tmp_path, transport=transport)

    assert run.status == 0
    assert json.loads(run.output)["knowledge_alignment"] == {
        "latest_run": LATEST_RUN,
        "waiting": 1,
    }
    transport.assert_done()


@pytest.mark.parametrize("language", ["en", "it"])
def test_offline_the_knowledge_comes_from_the_align_files(tmp_path: Path, language: str) -> None:
    project = link_folder(tmp_path / "project")
    folder_with_state(project, listed=False)
    align_files(project, waiting=1)

    run = run_ut(
        ["--lang", language, "status", "--offline"], tmp_path, transport=ScriptedTransport()
    )
    document = json.loads(
        run_ut(["status", "--offline", "--json"], tmp_path, transport=ScriptedTransport()).output
    )

    lines = run.output.splitlines()
    position = lines.index(knowledge_line(language, 1))
    assert lines[position - 1].startswith(("Development:", "Sviluppo:"))
    assert document["knowledge_alignment"] == {"latest_run": LATEST_RUN, "waiting": 1}
    assert list(document)[-1] == "knowledge_alignment"


def test_offline_without_the_run_file_the_latest_file_is_enough(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    folder_with_state(project, listed=False)
    align_files(project, waiting=0, run=False)

    run = run_ut(["status", "--offline"], tmp_path, transport=ScriptedTransport())
    document = json.loads(
        run_ut(["status", "--offline", "--json"], tmp_path, transport=ScriptedTransport()).output
    )

    assert (
        "Knowledge: aligned with the code up to commit 4f2a9c1 (2026-09-29 10:20); proposals "
        "waiting: 0." in run.output.splitlines()
    )
    assert document["knowledge_alignment"] == {
        "latest_run": {
            "id": RUN_ID,
            "from_commit": None,
            "to_commit": ALIGNED,
            "created_at": "2026-09-29T10:20:00+00:00",
            "requirements_version_number": None,
            "design_version_number": None,
            "alternative_code": None,
            "summary": None,
        },
        "waiting": 0,
    }


@pytest.mark.parametrize(
    "document",
    [None, {"schema_version": 2, "run_id": RUN_ID}, {"schema_version": 1, "run_id": ""}, "text"],
)
def test_offline_a_missing_or_broken_latest_file_gives_no_knowledge(
    tmp_path: Path, document: object
) -> None:
    project = link_folder(tmp_path / "project")
    folder_with_state(project, listed=False)
    if document is not None:
        folder = project.local / "align"
        folder.mkdir(parents=True)
        (folder / "latest.json").write_text(json.dumps(document), encoding="utf-8")

    run = run_ut(["status", "--offline"], tmp_path, transport=ScriptedTransport())
    found = json.loads(
        run_ut(["status", "--offline", "--json"], tmp_path, transport=ScriptedTransport()).output
    )

    assert not any(line.startswith("Knowledge:") for line in run.output.splitlines())
    assert found["knowledge_alignment"] is None


@pytest.mark.parametrize("language", ["en", "it"])
def test_what_the_twins_learned_follows_the_tests_line(tmp_path: Path, language: str) -> None:
    signed_in_folder(tmp_path)
    studio = {
        **PACKAGE_STEP,
        "tests": acceptance_document(runs=1),
        "learning": {"project_id": PROJECT_ID, "update_available": True, "twins": LEARNED},
    }
    text = expect_studio(ScriptedTransport(), **studio)
    as_json = expect_studio(ScriptedTransport(), **studio)

    run = run_ut(["--lang", language, "status"], tmp_path, transport=text)
    document = json.loads(run_ut(["status", "--json"], tmp_path, transport=as_json).output)

    lines = run.output.splitlines()
    line = learning_line(
        language, [("Pizzeria owner", "1.2", 2), ("Evening shift waiter", "1.0", 0)]
    )
    position = lines.index(line)
    assert lines[position - 1].startswith(("Acceptance tests:", "Verifica dei criteri:"))
    assert lines[position + 1].startswith(("Spent", "Spesa"))
    assert document["learning"] == LEARNED_TWINS
    assert list(document)[-3:] == ["learning", "sections", "knowledge_alignment"]
    text.assert_done()


def test_a_studio_without_the_route_of_the_learning_leaves_it_to_the_folder(
    tmp_path: Path,
) -> None:
    project = signed_in_folder(tmp_path)
    folder_with_state(project, learned=LEARNED)
    transport = expect_studio(ScriptedTransport(), **{**PACKAGE_STEP, "routes": False})

    run = run_ut(["status", "--json"], tmp_path, transport=transport)

    assert json.loads(run.output)["learning"] == LEARNED_TWINS
    transport.assert_done()


def test_offline_the_learning_comes_from_the_folder(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    folder_with_state(project, learned=LEARNED)

    run = run_ut(["status", "--offline"], tmp_path, transport=ScriptedTransport())
    document = json.loads(
        run_ut(["status", "--offline", "--json"], tmp_path, transport=ScriptedTransport()).output
    )

    assert learning_line(
        "en", [("Pizzeria owner", "1.2", 2), ("Evening shift waiter", "1.0", 0)]
    ) in (run.output.splitlines())
    assert document["learning"] == LEARNED_TWINS


@pytest.mark.parametrize(
    ("learned", "listed", "expected"),
    [
        (None, True, None),
        (LEARNED, False, None),
        ("not a list", True, None),
        ([], True, None),
        (
            [
                {**LEARNED[1], "label": " "},
                "noise",
                {**LEARNED[0], "twin_id": None},
            ],
            True,
            {
                "twins": [
                    {
                        "twin_id": TWIN_WAITER,
                        "name": "Evening shift waiter",
                        "label": "1.0",
                        "observations": 0,
                    }
                ]
            },
        ),
    ],
)
def test_nothing_learned_gives_no_line(
    tmp_path: Path, learned: object, listed: bool, expected: object
) -> None:
    project = link_folder(tmp_path / "project")
    folder_with_state(project, learned=learned, listed=listed)

    run = run_ut(["status", "--offline"], tmp_path, transport=ScriptedTransport())
    document = json.loads(
        run_ut(["status", "--offline", "--json"], tmp_path, transport=ScriptedTransport()).output
    )

    assert not any(line.startswith("What the twins learned") for line in run.output.splitlines())
    assert document["learning"] == expected


def test_a_learning_route_that_fails_hard_is_an_error(tmp_path: Path) -> None:
    signed_in_folder(tmp_path)
    transport = expect_studio(
        ScriptedTransport(),
        **PACKAGE_STEP,
        learning=None,
    )
    transport.expected = [
        item for item in transport.expected if not item.path.endswith("/twin-learning")
    ]
    transport.expect(
        "GET", f"{BASE}/twin-learning", status=403, body={"detail": {"code": "FORBIDDEN"}}
    )

    run = run_ut(["status"], tmp_path, transport=transport)

    assert run.status == 1
    assert "FORBIDDEN" in run.errors


def section(
    key: str,
    state: str,
    number: int | None = None,
    *,
    reasons: tuple[str, ...] = (),
    blocked: str | None = None,
    codes: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "key": key,
        "state": state,
        "version_number": number,
        "reasons": list(reasons),
        "blocked": blocked,
        "codes": list(codes),
    }


def sections_document(
    *items: dict[str, object],
    first_pass: bool = True,
    available: bool = False,
    aligned: tuple[str, ...] = (),
    uncovered: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "first_pass_complete": first_pass,
        "sections": list(items),
        "alignment": {
            "available": available,
            "sections": list(aligned),
            "uncovered_codes": list(uncovered),
        },
    }


ALL_FINE = sections_document(
    section("BRIEF", "FINE", 2),
    section("TEAM", "FINE", 1),
    section("USER_TWINS", "FINE", 1),
    section("REQUIREMENTS", "FINE", 1),
    section("DESIGN", "FINE", 2),
    section("PACKAGE", "FINE", 3),
)
EVERY_STATE = sections_document(
    section("BRIEF", "FINE", 2),
    section("TEAM", "UPDATE_AVAILABLE", 2),
    section("USER_TWINS", "TO_UPDATE", 1, reasons=("PERSPECTIVES_CHANGED",)),
    section("REQUIREMENTS", "IN_PROGRESS", 3),
    section("DESIGN", "NOT_STARTED"),
    section("PACKAGE", "NOT_STARTED"),
)
PERSPECTIVE_CHANGED = sections_document(
    section("BRIEF", "FINE", 2),
    section("TEAM", "FINE", 2),
    section("USER_TWINS", "TO_UPDATE", 1, reasons=("PERSPECTIVES_CHANGED",)),
    section("REQUIREMENTS", "TO_UPDATE", 3, reasons=("PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED")),
    section("DESIGN", "TO_UPDATE", 4, reasons=("REQUIREMENTS_CHANGED",)),
    section("PACKAGE", "TO_UPDATE", 6, reasons=("FOLDER_BEHIND",)),
    available=True,
    aligned=("USER_TWINS", "REQUIREMENTS", "DESIGN"),
)
DESIGN_WAITING = sections_document(
    *(item for item in ALL_FINE["sections"] if item["key"] not in {"DESIGN", "PACKAGE"}),
    section("DESIGN", "IN_PROGRESS", 3),
    section("PACKAGE", "TO_UPDATE", 3, reasons=("FOLDER_BEHIND",), blocked="UPSTREAM_NOT_READY"),
)
SECTION_TABLES = {
    "en": [
        "Section              State             Version",
        "-------------------  ----------------  -------",
        "Brief                Up to date        v2",
        "Perspectives         Update available  v2",
        "User Twin            To update         v1",
        "Definition           Your turn         v3",
        "Design & Evaluation  Waiting           -",
        "Dossier              Waiting           -",
    ],
    "it": [
        "Sezione               Stato                      Versione",
        "--------------------  -------------------------  --------",
        "Brief                 A posto                    v2",
        "Prospettive           Aggiornamento disponibile  v2",
        "User Twin             Da aggiornare              v1",
        "Definizione           Tocca a te                 v3",
        "Design e valutazione  In attesa                  -",
        "Dossier               In attesa                  -",
    ],
}
BEHIND_LINES = {
    "en": "User Twin, Definition, Design & Evaluation to update: something upstream changed. "
    "The content you approved stays the same, it is only re-anchored to the new versions. "
    "Update and confirm with `ut sections update`.",
    "it": "User Twin, Definizione, Design e valutazione da aggiornare: a monte qualcosa è "
    "cambiato. I contenuti che hai approvato restano gli stessi, vengono solo riagganciati "
    "alle versioni nuove. Aggiorna e conferma con `ut sections update`.",
}


@pytest.mark.parametrize("language", ["en", "it"])
def test_after_the_first_pass_the_table_shows_every_state_of_the_sections(
    tmp_path: Path, language: str
) -> None:
    signed_in_folder(tmp_path)
    transport = expect_studio(ScriptedTransport(), **PACKAGE_STEP, sections=EVERY_STATE)

    run = run_ut(["--lang", language, "status"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    assert run.output.splitlines()[5:13] == SECTION_TABLES[language]
    transport.assert_done()


@pytest.mark.parametrize("language", ["en", "it"])
def test_sections_behind_are_told_with_the_gesture_in_place_of_the_next_step(
    tmp_path: Path, language: str
) -> None:
    signed_in_folder(tmp_path)
    transport = expect_studio(ScriptedTransport(), **PACKAGE_STEP, sections=PERSPECTIVE_CHANGED)

    run = run_ut(["--lang", language, "status"], tmp_path, transport=transport)

    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert lines[13:15] == ["", BEHIND_LINES[language]]
    assert lines[15].startswith(("Knowledge folder:", "Cartella di conoscenza:"))
    assert not any(line.startswith(("Next step", "Prossimo passo")) for line in lines)
    assert "ut package publish" not in run.output
    transport.assert_done()


def test_a_section_waiting_for_the_owner_gives_the_next_step_of_its_stage(tmp_path: Path) -> None:
    signed_in_folder(tmp_path)
    waiting = sections_document(
        section("BRIEF", "IN_PROGRESS", 3),
        *(item for item in ALL_FINE["sections"] if item["key"] != "BRIEF"),
    )
    transport = expect_studio(ScriptedTransport(), **PACKAGE_STEP, sections=waiting)

    run = run_ut(["status"], tmp_path, transport=transport)

    lines = run.output.splitlines()
    assert lines[7] == "Brief                Your turn   v3"
    assert lines[13:15] == ["", "Next step: Approve the brief: launch `ut init`."]


def test_every_section_up_to_date_names_the_commands_after_the_design(tmp_path: Path) -> None:
    project = signed_in_folder(tmp_path)
    local_manifest(project, 3)
    transport = expect_studio(ScriptedTransport(), **PACKAGE_STEP, sections=ALL_FINE)

    run = run_ut(["status"], tmp_path, transport=transport)

    lines = run.output.splitlines()
    assert lines[13:22] == [
        "",
        "Next step: The knowledge folder is up to date: the development goes on with these "
        "commands:",
        *AFTER_DESIGN["en"],
    ]
    transport.assert_done()


def test_during_the_first_pass_the_steps_stay_and_the_sentences_follow(tmp_path: Path) -> None:
    signed_in_folder(tmp_path)
    first_pass = sections_document(
        section("BRIEF", "FINE", 2),
        section("TEAM", "TO_UPDATE", 1, reasons=("BRIEF_CHANGED",), blocked="PREPARE_AGAIN"),
        section(
            "USER_TWINS",
            "TO_UPDATE",
            1,
            reasons=("BRIEF_CHANGED", "PERSPECTIVES_CHANGED"),
            blocked="UPSTREAM_NOT_READY",
        ),
        section("REQUIREMENTS", "NOT_STARTED"),
        section("DESIGN", "NOT_STARTED"),
        section("PACKAGE", "FINE", 1),
        first_pass=False,
        aligned=("USER_TWINS",),
    )
    transport = expect_studio(ScriptedTransport(), sections=first_pass)

    run = run_ut(["status"], tmp_path, transport=transport)

    lines = run.output.splitlines()
    assert lines[5] == "Step                 State                      Version"
    assert lines[9] == "User Twin            waiting for your approval  1"
    assert lines[13:16] == [
        "",
        "Perspectives cannot be updated by itself: the brief changed: prepare the perspectives "
        "again. Launch `ut init`.",
        "Knowledge folder: not published yet.",
    ]


def test_during_the_first_pass_a_dossier_behind_keeps_the_next_step(tmp_path: Path) -> None:
    signed_in_folder(tmp_path)
    first_pass = sections_document(
        section("BRIEF", "FINE", 2),
        section("TEAM", "FINE", 1),
        section("USER_TWINS", "IN_PROGRESS", 1),
        section("REQUIREMENTS", "NOT_STARTED"),
        section("DESIGN", "NOT_STARTED"),
        section("PACKAGE", "TO_UPDATE", 1, reasons=("FOLDER_BEHIND",)),
        first_pass=False,
    )
    transport = expect_studio(ScriptedTransport(), sections=first_pass)

    run = run_ut(["--lang", "it", "status"], tmp_path, transport=transport)

    assert run.output.splitlines()[13:16] == [
        "",
        "Il Dossier non contiene ancora le ultime versioni approvate: pubblicalo con "
        "`ut package publish`.",
        "Prossimo passo: Conferma i twin: lancia `ut init`.",
    ]


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en", "Next step: Choose and approve the design: launch `ut design`."),
        ("it", "Prossimo passo: Scegli e approva il design: lancia `ut design`."),
    ],
)
def test_a_dossier_waiting_for_the_design_in_progress_keeps_the_next_step(
    tmp_path: Path, language: str, expected: str
) -> None:
    signed_in_folder(tmp_path)
    transport = expect_studio(ScriptedTransport(), **PACKAGE_STEP, sections=DESIGN_WAITING)

    run = run_ut(["--lang", language, "status"], tmp_path, transport=transport)

    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert lines[13:15] == ["", expected]
    assert lines[15].startswith(("Knowledge folder:", "Cartella di conoscenza:"))
    assert "ut package publish" not in run.output
    transport.assert_done()


def test_the_json_ends_with_the_object_of_the_sections_as_it_is(tmp_path: Path) -> None:
    signed_in_folder(tmp_path)
    extra = {**PERSPECTIVE_CHANGED, "added_later": {"kept": True}}
    transport = expect_studio(ScriptedTransport(), **PACKAGE_STEP, sections=extra)

    document = json.loads(run_ut(["status", "--json"], tmp_path, transport=transport).output)

    assert list(document)[-2:] == ["sections", "knowledge_alignment"]
    assert document["sections"] == extra
    assert document["next_action"] == "UPDATE_SECTIONS"
    assert document["next_command"] == "ut sections update"
    transport.assert_done()


@pytest.mark.parametrize("language", ["en", "it"])
@pytest.mark.parametrize(
    ("stage", "block", "action", "command"),
    [
        ("USER_TWINS", "PREPARE_TWINS", "PREPARE_TWINS", "ut init"),
        ("DESIGN", "REQUIREMENT_NO_LONGER_AVAILABLE", "PREPARE_DESIGN", "ut design regenerate"),
        ("DESIGN", "PREPARE_AGAIN", "PREPARE_DESIGN", "ut design regenerate"),
    ],
)
def test_status_derives_preparation_from_a_blocked_obsolete_section(
    tmp_path: Path, language: str, stage: str, block: str, action: str, command: str
) -> None:
    signed_in_folder(tmp_path)
    rows = [dict(item) for item in ALL_FINE["sections"]]
    target = next(item for item in rows if item["key"] == stage)
    target.update(
        state="TO_UPDATE",
        blocked=block,
        reasons=["ARCHETYPES_CHANGED" if stage == "USER_TWINS" else "REQUIREMENTS_CHANGED"],
    )
    found = sections_document(*rows, available=False, aligned=(stage,))
    table = expect_studio(ScriptedTransport(), **PACKAGE_STEP, sections=found)
    as_json = expect_studio(ScriptedTransport(), **PACKAGE_STEP, sections=found)
    run = run_ut(["--lang", language, "status"], tmp_path, transport=table)
    document = json.loads(run_ut(["status", "--json"], tmp_path, transport=as_json).output)
    assert run.status == 0
    assert document["current_stage"] == stage
    assert document["next_action"] == action
    assert document["next_command"] == command
    assert ("Prepara di nuovo" if language == "it" else "Prepare the") in run.output
    assert command in run.output
    assert "ut package publish" not in run.output


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (404, {"detail": "Not Found"}),
        (405, {"detail": "Method Not Allowed"}),
        (503, {"detail": {"code": "SECTIONS_SERVICE_UNAVAILABLE"}}),
        (200, {"sections": "not a list"}),
    ],
)
def test_a_studio_without_usable_sections_shows_the_steps_as_today(
    tmp_path: Path, status: int, body: dict[str, object]
) -> None:
    signed_in_folder(tmp_path)
    transport = expect_studio(ScriptedTransport(), **PACKAGE_STEP)
    transport.expected = [
        item for item in transport.expected if not item.path.endswith("/sections")
    ]
    transport.expect("GET", f"{BASE}/sections", status=status, body=body)
    as_json = expect_studio(ScriptedTransport(), **PACKAGE_STEP)
    as_json.expected = [item for item in as_json.expected if not item.path.endswith("/sections")]
    as_json.expect("GET", f"{BASE}/sections", status=status, body=body)

    run = run_ut(["status"], tmp_path, transport=transport)
    document = json.loads(run_ut(["status", "--json"], tmp_path, transport=as_json).output)

    assert run.status == 0, run.errors
    assert run.output.splitlines()[5].startswith("Step ")
    assert document["sections"] is None
    transport.assert_done()
