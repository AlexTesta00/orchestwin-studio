from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from orchestwin.cli.project import ProjectFolder

from .support.terminal import PROJECT_ID, START, link_folder, run_ut, store_session
from .support.transports import API, ScriptedTransport

LOCAL = "http://127.0.0.1:8000"
BASE = f"{API}/projects/{PROJECT_ID}"
ALIGNED = "4f2a9c1e7b3d5a8f0c6e2b9d1a7f3c5e8b0d2a46"
TEST_RUN = "00000000-0000-4000-8000-00000000e001"
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


def gate(artifact_id: str, content_hash: str, status: str = "APPROVED") -> dict[str, object]:
    return {
        "id": f"gate-{artifact_id}",
        "status": status,
        "artifact": {"artifact_id": artifact_id, "version": 1, "content_hash": content_hash},
    }


def version(identifier: str, number: int, content_hash: str) -> dict[str, object]:
    return {"id": identifier, "version_number": number, "content_hash": content_hash}


def alignment_document(
    *, aligned: str | None = ALIGNED, pending: int = 1, tasks: int = 1
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
    if later_approved and routes:
        expect_alignment(
            transport, alignment_document() if alignment is None else alignment, recorded
        )
        transport.expect(
            "GET",
            f"{BASE}/acceptance-tests",
            body=acceptance_document() if tests is None else tests,
        )
    elif later_approved:
        transport.expect("GET", f"{BASE}/alignment", status=404, body={"detail": "Not Found"})
        transport.expect(
            "GET", f"{BASE}/acceptance-tests", status=404, body={"detail": "Not Found"}
        )
    if budget:
        transport.expect("GET", f"{API}/model-runtime/budget", body=BUDGET)
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
        "Step          State                      Version",
        "------------  -------------------------  -------",
        "Brief         approved                   2",
        "Team          approved                   1",
        "User Twins    waiting for your approval  1",
        "Requirements  later                      -",
        "Design        later                      -",
        "Package       later                      -",
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
        "Passo      Stato                Versione",
        "---------  -------------------  --------",
        "Brief      approvato            2",
        "Squadra    approvato            1",
        "User Twin  approvato            1",
        "Requisiti  approvato            1",
        "Design     approvato            2",
        "Pacchetto  pronto da scaricare  3",
    ]
    assert lines[14:] == [
        "Prossimo passo: Scarica la cartella di conoscenza: lancia `ut package publish`.",
        "Cartella di conoscenza: versione 2 in questa cartella, versione 3 nello Studio.",
        "La cartella qui è più vecchia: aggiornala con `ut package pull`.",
        "Sviluppo: commit registrati: 3; dopo il punto allineato: 1; commit allineato: "
        "4f2a9c1; compiti aperti per il codice: 1.",
        "Spesa del progetto: 0,42 USD. Credito rimasto nello Studio: 25,13 USD.",
    ]


def test_a_folder_at_the_version_of_the_studio_sends_the_development_to_ut_align(
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
    assert lines[14:18] == [
        "Next step: The knowledge folder is up to date: the development goes on with "
        "`ut align` and `ut watch`.",
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
    }
    assert document["next_command"] == "ut align"
    assert (
        "Development: no commit recorded yet. After your first commit launch `ut align`."
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
    }
    assert document["alignment"] is None
    assert document["tests"] is None
    assert list(document)[-2:] == ["alignment", "tests"]


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
    assert document["next_command"] == "ut align"
    assert document["spending"] is None


@pytest.mark.parametrize(
    ("language", "line"),
    [
        (
            "en",
            "Next step: The knowledge folder is up to date: the development goes on with "
            "`ut align` and `ut watch`.",
        ),
        (
            "it",
            "Prossimo passo: La cartella di conoscenza è aggiornata: lo sviluppo continua con "
            "`ut align` e `ut watch`.",
        ),
    ],
)
def test_offline_a_complete_folder_sends_the_development_to_ut_align(
    tmp_path: Path, language: str, line: str
) -> None:
    project = link_folder(tmp_path / "project")
    local_manifest(project, 4)

    run = run_ut(
        ["--lang", language, "status", "--offline"], tmp_path, transport=ScriptedTransport()
    )

    assert run.status == 0
    assert line in run.output.splitlines()


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
        "Project            Step                Your turn",
        "-----------------  ------------------  -----------------------------------------",
        "Calcolo mancia     3 of 6: User Twins  Confirm the twins: launch `ut init`.",
        "Registro prestiti  6 of 6: Package     Download the knowledge folder: launch `ut",
        "                                       package publish`.",
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
    assert list(document)[-1] == "tests"
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
