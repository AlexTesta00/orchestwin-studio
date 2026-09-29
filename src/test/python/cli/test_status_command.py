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


def expect_studio(
    transport: ScriptedTransport,
    *,
    stage: str = "USER_TWINS",
    action: str = "CONFIRM_TWINS",
    twins_approved: bool = False,
    later_approved: bool = False,
    folder: int | None = None,
    budget: bool = True,
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
        "Spesa del progetto: 0,42 USD. Credito rimasto nello Studio: 25,13 USD.",
    ]


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
    assert document["spending"] is None


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
