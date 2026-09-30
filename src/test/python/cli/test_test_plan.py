from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from orchestwin.cli.context import CommandContext
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.flows import test_plan as plan_flow
from orchestwin.cli.project import ProjectFolder

from .support.terminal import PROJECT_ID, command_context, link_folder, store_session, terminal
from .support.transports import API, ScriptedTransport

BASE = f"{API}/projects/{PROJECT_ID}"
PLAN_ID = "00000000-0000-4000-8000-00000000f001"
REPLAN_ID = "00000000-0000-4000-8000-00000000f002"
OPEN = {"action": "OPEN", "target": None, "value": "/", "expect": None}


def check(text: str) -> dict[str, object]:
    return {
        "action": "CHECK",
        "target": None,
        "value": None,
        "expect": {"kind": "TEXT_VISIBLE", "target": None, "text": text},
    }


def path(code: str, *criteria: str, text: str = "Mancia") -> dict[str, object]:
    return {
        "code": code,
        "heading": f"Percorso {code}",
        "criteria": list(criteria),
        "steps": [OPEN, check(text)],
    }


PLAN = {
    "id": PLAN_ID,
    "created_at": "2026-09-29T08:30:00+00:00",
    "locale": "it-IT",
    "reference": {
        "requirements_version_number": 2,
        "design_version_number": 4,
        "alternative_code": "DES-002",
    },
    "application": {"kind": "STATIC", "address": "dist"},
    "criteria": ["AC-001", "AC-002", "AC-003", "AC-004"],
    "replan_of": [],
    "paths": [path("TP-001", "AC-001"), path("TP-002", "AC-002"), path("TP-003", "AC-003")],
    "not_covered": [{"criterion": "AC-004", "reason": "Richiede una verifica manuale"}],
    "cost_microusd": 210000,
}
REPLAN = {
    **PLAN,
    "id": REPLAN_ID,
    "criteria": ["AC-002", "AC-003"],
    "replan_of": ["TP-002", "TP-003"],
    "paths": [path("TP-004", "AC-002", text="Percentuali")],
    "not_covered": [
        {"criterion": "AC-003", "reason": "Serve un secondo sistema"},
        {"criterion": "AC-004", "reason": "Altro motivo"},
    ],
}
SNAPSHOT = {"url": "http://127.0.0.1:8123/", "title": "Mancia", "text": "Mancia", "elements": []}


def saved(*replans: dict[str, object]) -> plan_flow.SavedPlan:
    return plan_flow.SavedPlan(
        saved_at="2026-09-29T09:00:00+00:00",
        application={"kind": "STATIC", "address": "dist"},
        plan=copy.deepcopy(PLAN),
        replans=tuple(copy.deepcopy(item) for item in replans),
    )


def prepared(tmp_path: Path, transport: ScriptedTransport) -> tuple[CommandContext, ProjectFolder]:
    store_session(tmp_path)
    project = link_folder(tmp_path / "project")
    bundle = terminal(tmp_path, transport=transport)
    return command_context(bundle.environment), project


def test_a_replan_replaces_the_blocked_paths_and_adds_its_not_covered_criteria() -> None:
    plain = saved()
    replanned = saved(REPLAN)

    assert [item["code"] for item in plain.paths()] == ["TP-001", "TP-002", "TP-003"]
    assert [item["code"] for item in replanned.paths()] == ["TP-001", "TP-004"]
    assert [item["criterion"] for item in replanned.not_covered()] == ["AC-004", "AC-003"]
    assert replanned.not_covered()[0]["reason"] == "Richiede una verifica manuale"
    assert replanned.criteria() == ["AC-001", "AC-002", "AC-003", "AC-004"]
    assert replanned.covered() == {"AC-001", "AC-002", "AC-003", "AC-004"}
    assert (replanned.plan_id, replanned.replan_ids) == (PLAN_ID, [REPLAN_ID])
    assert replanned.reference() == (2, 4)
    assert replanned.created_at == "2026-09-29T08:30:00+00:00"
    assert plain.with_replan(REPLAN, saved_at="later") == plan_flow.SavedPlan(
        saved_at="later", application=plain.application, plan=plain.plan, replans=(REPLAN,)
    )


def test_the_plan_file_is_written_and_read_again(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    written = saved(REPLAN)

    path_written = plan_flow.save_plan(project, written)
    document = json.loads(path_written.read_bytes().decode("utf-8"))

    assert path_written == project.root / ".orchestwin" / "tests" / "plan.json"
    assert list(document) == ["schema_version", "saved_at", "application", "plan", "replans"]
    assert document["schema_version"] == 1
    assert plan_flow.read_plan(project) == written


@pytest.mark.parametrize(
    "document",
    [
        None,
        {"schema_version": 2, "plan": PLAN, "replans": []},
        {"schema_version": 1, "plan": {**PLAN, "id": ""}, "replans": []},
        {"schema_version": 1, "plan": {**PLAN, "paths": "none"}, "replans": []},
        {"schema_version": 1, "plan": {**PLAN, "paths": [{"code": 1, "steps": []}]}},
        {"schema_version": 1, "plan": PLAN, "replans": [{"id": REPLAN_ID}]},
        {"schema_version": 1, "plan": PLAN, "replans": "none"},
    ],
)
def test_a_plan_file_that_cannot_be_read_counts_as_missing(
    tmp_path: Path, document: object
) -> None:
    project = link_folder(tmp_path / "project")
    target = plan_flow.plan_file(project)
    target.parent.mkdir(parents=True)
    if document is not None:
        target.write_text(json.dumps(document), encoding="utf-8")

    assert plan_flow.read_plan(project) is None


def test_a_saved_plan_is_reused_while_it_fits_the_folder_and_the_criteria() -> None:
    plan = saved(REPLAN)

    reused = plan_flow.decide(plan, (2, 4), ["AC-002", "AC-004"], new=False)
    asked = plan_flow.decide(plan, (2, 4), [], new=True)
    missing = plan_flow.decide(None, (2, 4), [], new=False)
    stale = plan_flow.decide(plan, (3, 4), [], new=False)
    uncovered = plan_flow.decide(saved(), (2, 4), ["AC-001", "AC-007", "AC-009"], new=False)

    assert reused == plan_flow.PlanChoice(reuse=True)
    assert asked == missing == plan_flow.PlanChoice(reuse=False)
    assert stale == plan_flow.PlanChoice(
        reuse=False,
        key="test.plan_stale",
        values={"plan_requirements": 2, "plan_design": 4, "requirements": 3, "design": 4},
    )
    assert uncovered.key == "test.plan_uncovered"
    assert uncovered.values == {"codes": "AC-007, AC-009"}


def test_a_plan_without_a_reference_never_fits() -> None:
    plan = plan_flow.SavedPlan("", {}, {**PLAN, "reference": None})

    choice = plan_flow.decide(plan, (2, 4), [], new=False)

    assert choice.key == "test.plan_stale"
    assert choice.values["plan_requirements"] == "-"


def test_the_bodies_of_a_plan_and_of_a_replan() -> None:
    blocked = path("TP-002", "AC-002")
    body = plan_flow.plan_body("it-IT", {"kind": "URL", "address": "http://x.test/"}, SNAPSHOT)
    earlier = plan_flow.earlier_item(blocked, 2, "x" * 400, SNAPSHOT)
    again = plan_flow.plan_body(
        "en-US",
        {"kind": "STATIC", "address": "dist"},
        SNAPSHOT,
        criteria=["AC-002"],
        earlier=[earlier],
    )

    assert body == {
        "locale": "it-IT",
        "application": {"kind": "URL", "address": "http://x.test/"},
        "snapshot": SNAPSHOT,
        "criteria": None,
        "earlier": None,
    }
    assert list(earlier) == [
        "code",
        "heading",
        "criteria",
        "steps",
        "blocked_step",
        "detail",
        "snapshot",
    ]
    assert (earlier["code"], earlier["blocked_step"], len(str(earlier["detail"]))) == (
        "TP-002",
        2,
        300,
    )
    assert again["criteria"] == ["AC-002"]
    assert again["earlier"] == [earlier]
    assert plan_flow.earlier_item(blocked, 1, None, None)["snapshot"] is None


def test_a_plan_answered_at_once_is_returned(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect(
        "POST", f"{BASE}/test-plans", status=201, body={"status": "PLANNED", "plan": PLAN}
    )
    context, project = prepared(tmp_path, transport)

    plan = plan_flow.request_plan(
        context, context.client(), project, {"locale": "it-IT"}, label="Piano"
    )

    assert plan == PLAN
    assert transport.sent[0].header("prefer") == "respond-async"
    assert plan_flow.plan_cost_usd(plan, 0.3) == 0.21
    assert plan_flow.plan_cost_usd({}, 0.3) == 0.3


def test_a_plan_answered_through_a_job_is_returned(tmp_path: Path) -> None:
    job = {"job_id": "job-1", "status": "RUNNING", "stage": "GENERATING"}
    done = {
        **job,
        "status": "SUCCEEDED",
        "response": {"status_code": 201, "body": {"status": "PLANNED", "plan": PLAN}},
    }
    transport = (
        ScriptedTransport()
        .expect("POST", f"{BASE}/test-plans", status=202, body=job)
        .expect("GET", f"{BASE}/generation-jobs/job-1", body=done)
    )
    context, project = prepared(tmp_path, transport)

    plan = plan_flow.request_plan(
        context, context.client(), project, {"locale": "it-IT"}, label="Piano"
    )

    assert plan["id"] == PLAN_ID
    transport.assert_done()


@pytest.mark.parametrize(
    ("status", "body", "code", "values"),
    [
        (
            503,
            {"detail": {"code": "TEST_MODEL_NOT_CONFIGURED"}},
            "TEST_MODEL_NOT_CONFIGURED",
            {},
        ),
        (
            409,
            {"detail": {"code": "DESIGN_APPROVAL_REQUIRED"}},
            "DESIGN_APPROVAL_REQUIRED",
            {},
        ),
        (
            422,
            {"detail": {"code": "ACCEPTANCE_CRITERION_UNKNOWN", "codes": ["AC-009"]}},
            "ACCEPTANCE_CRITERION_UNKNOWN",
            {"codes": "AC-009"},
        ),
        (
            502,
            {"detail": {"code": "INVALID_PROVIDER_OUTPUT", "stage": "MODEL_PROPOSAL"}},
            "INVALID_PROVIDER_OUTPUT",
            {},
        ),
        (201, {"status": "PLANNED", "plan": {"id": PLAN_ID}}, "API_FAILURE", {}),
    ],
)
def test_a_refused_plan_raises_the_code_of_the_studio(
    tmp_path: Path, status: int, body: object, code: str, values: dict[str, object]
) -> None:
    transport = ScriptedTransport().expect("POST", f"{BASE}/test-plans", status=status, body=body)
    context, project = prepared(tmp_path, transport)

    with pytest.raises(ApiFailure) as caught:
        plan_flow.request_plan(context, context.client(), project, {}, label="Piano")

    assert caught.value.code == code
    assert caught.value.status == 1
    assert {key: caught.value.values[key] for key in values} == values


def test_a_plan_over_the_ceiling_names_the_ceiling(tmp_path: Path) -> None:
    budget = {
        "currency": "USD",
        "per_generation_microusd": 2_000_000,
        "per_project_microusd": 20_000_000,
        "total_microusd": 60_000_000,
        "spent_total_microusd": 59_900_000,
        "remaining_total_microusd": 100_000,
    }
    transport = (
        ScriptedTransport()
        .expect(
            "POST",
            f"{BASE}/test-plans",
            status=402,
            body={"detail": {"code": "GENERATION_BUDGET_EXCEEDED", "stage": "MODEL_PROPOSAL"}},
        )
        .expect("GET", f"{API}/model-runtime/budget", body=budget)
    )
    context, project = prepared(tmp_path, transport)

    with pytest.raises(CliError) as caught:
        plan_flow.request_plan(context, context.client(), project, {}, label="Piano")

    assert (caught.value.code, caught.value.status) == ("GENERATION_BUDGET_EXCEEDED", 5)
    assert dict(caught.value.values) == {"reason": "total", "ceiling": "60.00"}
