from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from orchestwin.cli.browser.snapshot import (
    MAX_SNAPSHOT_HIDDEN_TEXT_LENGTH,
    MAX_SNAPSHOT_TEXT_LENGTH,
)
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
SNAPSHOT = {
    "url": "http://127.0.0.1:8123/",
    "title": "Mancia",
    "text": "Mancia",
    "hidden_text": "Risultato Totale",
    "elements": [],
}
PAGE_TEXT = "Calcolo della mancia Conto Percentuale Calcola"
PAGE_HIDDEN = "Risultato Totale Esempio: 10,05 € al 10% dà una mancia di 1,01 €."
MEASURE_TEXT = (
    "Mancia Subito Pagina web gratuita, si apre dal browser senza installare nulla Calcola la "
    "mancia Scrivi il conto, la percentuale e le persone al tavolo, poi tocca Calcola: mancia, "
    "totale e quota a testa compaiono sotto i campi. Conto In euro, con un solo separatore per i "
    "decimali: 38,45 oppure 38.45. € Percentuale di mancia Scrivi la percentuale, per esempio 10 "
    "oppure 12,5: resta pronta anche per il tavolo successivo. % Persone Quante persone dividono "
    "il conto: con 1 il conto non viene diviso. Calcola"
)
MEASURE_HIDDEN = (
    "Risultato Totale Mancia A testa Mancia arrotondata al centesimo, metà per eccesso; il totale "
    "somma il conto e la mancia già arrotondata. Regola confermata dalla gestione del ristorante. "
    "Esempio: 10,05 € al 10% dà una mancia di 1,01 € e un totale di 11,06 €."
)


def saved(*replans: dict[str, object]) -> plan_flow.SavedPlan:
    return plan_flow.SavedPlan(
        saved_at="2026-09-29T09:00:00+00:00",
        application={"kind": "STATIC", "address": "dist"},
        plan=copy.deepcopy(PLAN),
        replans=tuple(copy.deepcopy(item) for item in replans),
    )


def expecting(kind: str, text: object, *, action: str = "CHECK") -> dict[str, object]:
    return {
        "action": action,
        "target": None,
        "value": "/" if action == "OPEN" else None,
        "expect": {"kind": kind, "target": None, "text": text},
    }


def steps_path(
    code: str, *steps: object, criteria: tuple[str, ...] = ("AC-001",)
) -> dict[str, object]:
    return {
        "code": code,
        "heading": f"Percorso {code}",
        "criteria": list(criteria),
        "steps": list(steps),
    }


def page(text: str = PAGE_TEXT, hidden: str = PAGE_HIDDEN) -> dict[str, object]:
    return {**SNAPSHOT, "text": text, "hidden_text": hidden}


def weak(path_code: str, step: int, kind: str, text: str) -> dict[str, object]:
    return {"path": path_code, "step": step, "kind": kind, "text": text}


def measure_path(code: str, bill: str, percent: str, tip: str, total: str) -> dict[str, object]:
    return steps_path(
        code,
        OPEN,
        {
            "action": "TYPE",
            "target": {"role": "textbox", "name": "Conto"},
            "value": bill,
            "expect": None,
        },
        {
            "action": "TYPE",
            "target": {"role": "textbox", "name": "Percentuale di mancia"},
            "value": percent,
            "expect": None,
        },
        {
            "action": "CLICK",
            "target": {"role": "button", "name": "Calcola"},
            "value": None,
            "expect": {"kind": "TEXT_VISIBLE", "target": None, "text": tip},
        },
        expecting("TEXT_VISIBLE", total),
        criteria=("AC-003",),
    )


def passed_run(*paths: dict[str, object], criteria: list[dict[str, object]]) -> dict[str, object]:
    return {
        "criteria": criteria,
        "results": [
            {"path": item, "browser": browser, "status": "PASSED"}
            for item in paths
            for browser in ("chrome", "firefox")
        ],
    }


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
    assert list(document) == [
        "schema_version",
        "saved_at",
        "application",
        "plan",
        "replans",
        "weak_expectations",
    ]
    assert document["schema_version"] == 1
    assert document["weak_expectations"] == []
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


def test_a_saved_plan_is_not_reused_while_the_redo_file_exists(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    plan = saved(REPLAN)

    assert plan_flow.read_redo(project) is None
    first = plan_flow.mark_redo(
        project,
        [{"code": "ALN-003", "request": "Cover the split among friends."}],
        written_at="2026-09-29T10:00:00+00:00",
    )
    second = plan_flow.mark_redo(
        project,
        [
            {"code": "ALN-003", "request": "Cover the split among friends again."},
            {"code": "ALN-005", "request": "Cover the rounding."},
        ],
        written_at="2026-09-29T10:05:00+00:00",
    )
    document = json.loads(second.read_bytes().decode("utf-8"))
    redo = plan_flow.read_redo(project)
    choice = plan_flow.decide(plan, (2, 4), ["AC-002"], new=False, redo=redo)
    forced = plan_flow.decide(plan, (2, 4), [], new=True, redo=redo)
    plan_flow.clear_redo(project)
    gone = plan_flow.read_redo(project)
    plan_flow.clear_redo(project)

    assert first == second == project.root / ".orchestwin" / "tests" / "redo.json"
    assert list(document) == ["schema_version", "written_at", "proposals"]
    assert (document["schema_version"], document["written_at"]) == (
        1,
        "2026-09-29T10:05:00+00:00",
    )
    assert redo == (
        {"code": "ALN-003", "request": "Cover the split among friends again."},
        {"code": "ALN-005", "request": "Cover the rounding."},
    )
    assert choice == plan_flow.PlanChoice(
        reuse=False, key="test.plan_redo", values={"codes": "ALN-003, ALN-005"}
    )
    assert forced == plan_flow.PlanChoice(reuse=False)
    assert gone is None


@pytest.mark.parametrize(
    "document",
    [
        None,
        "text",
        {"schema_version": 2, "proposals": [{"code": "ALN-001", "request": "x"}]},
        {"schema_version": 1, "proposals": [{"code": 1, "request": "x"}, "noise"]},
    ],
)
def test_a_redo_file_that_cannot_be_read_still_asks_for_a_new_plan(
    tmp_path: Path, document: object
) -> None:
    project = link_folder(tmp_path / "project")
    target = plan_flow.redo_file(project)
    target.parent.mkdir(parents=True)
    target.write_text("" if document is None else json.dumps(document), encoding="utf-8")

    redo = plan_flow.read_redo(project)
    choice = plan_flow.decide(saved(REPLAN), (2, 4), [], new=False, redo=redo)

    assert redo == ()
    assert choice == plan_flow.PlanChoice(reuse=False, key="test.plan_redo", values={"codes": "-"})


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


def test_the_bodies_keep_every_key_of_the_snapshot_they_receive() -> None:
    older = {key: value for key, value in SNAPSHOT.items() if key != "hidden_text"}
    blocked = path("TP-002", "AC-002")
    earlier = plan_flow.earlier_item(blocked, 2, "target not found", SNAPSHOT)
    body = plan_flow.plan_body(
        "it-IT", {"kind": "URL", "address": "x"}, SNAPSHOT, earlier=[earlier]
    )
    plain = plan_flow.plan_body("it-IT", {"kind": "URL", "address": "x"}, older)

    assert list(body["snapshot"]) == ["url", "title", "text", "hidden_text", "elements"]
    assert body["snapshot"] == SNAPSHOT
    assert body["snapshot"] is not SNAPSHOT
    assert earlier["snapshot"] == SNAPSHOT
    assert list(earlier["snapshot"]) == list(SNAPSHOT)
    assert body["earlier"][0]["snapshot"]["hidden_text"] == "Risultato Totale"
    assert plain["snapshot"] == older


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


def test_each_kind_of_expectation_that_proves_little_names_its_path_step_and_text() -> None:
    first = steps_path(
        "TP-001",
        OPEN,
        {
            "action": "TYPE",
            "target": {"role": "textbox", "name": "Conto"},
            "value": "10,05",
            "expect": None,
        },
        expecting("TEXT_VISIBLE", "Calcola", action="CLICK"),
        expecting("TEXT_VISIBLE", "1,01"),
        expecting("TEXT_ABSENT", "Errore"),
        expecting("TEXT_ABSENT", "Risultato"),
        expecting("TEXT_VISIBLE", "34,50"),
    )
    second = steps_path("TP-002", OPEN, expecting("TEXT_ABSENT", "Conto"))

    found = plan_flow.weak_expectations([first, second], page())

    assert found == [
        weak("TP-001", 3, "VISIBLE_AT_OPENING", "Calcola"),
        weak("TP-001", 4, "HIDDEN_AT_OPENING", "1,01"),
        weak("TP-001", 5, "NEVER_ON_PAGE", "Errore"),
        weak("TP-002", 2, "ABSENT_VISIBLE_AT_OPENING", "Conto"),
    ]
    assert [list(item) for item in found] == [["path", "step", "kind", "text"]] * 4
    assert plan_flow.WEAK_KINDS == (
        "VISIBLE_AT_OPENING",
        "HIDDEN_AT_OPENING",
        "ABSENT_VISIBLE_AT_OPENING",
        "NEVER_ON_PAGE",
    )
    assert (
        plan_flow.VISIBLE_AT_OPENING,
        plan_flow.HIDDEN_AT_OPENING,
        plan_flow.ABSENT_VISIBLE_AT_OPENING,
        plan_flow.NEVER_ON_PAGE,
    ) == plan_flow.WEAK_KINDS


def test_the_open_step_checks_the_opening_and_the_visible_text_comes_before_the_hidden() -> None:
    both = page(text="Calcolo della mancia Totale 11,06", hidden="Esempio: totale 11,06")
    opening = steps_path(
        "TP-001",
        expecting("TEXT_VISIBLE", "Calcolo della mancia", action="OPEN"),
        expecting("TEXT_VISIBLE", "11,06"),
    )
    hidden_at_open = steps_path(
        "TP-002",
        expecting("TEXT_VISIBLE", "Esempio", action="OPEN"),
        expecting("TEXT_VISIBLE", "11,06", action="OPEN"),
        expecting("TEXT_ABSENT", "Errore", action="OPEN"),
    )

    found = plan_flow.weak_expectations([opening, hidden_at_open], both)

    assert found == [
        weak("TP-001", 2, "VISIBLE_AT_OPENING", "11,06"),
        weak("TP-002", 1, "HIDDEN_AT_OPENING", "Esempio"),
        weak("TP-002", 3, "NEVER_ON_PAGE", "Errore"),
    ]


def test_texts_are_matched_as_the_runner_matches_them() -> None:
    plan = steps_path(
        "TP-001",
        OPEN,
        expecting("TEXT_VISIBLE", "  CALCOLO   della MANCIA "),
        expecting("TEXT_VISIBLE", "DA UNA MANCIA di 1,01"),
        expecting("TEXT_VISIBLE", "Totale  Esempio"),
        expecting("TEXT_ABSENT", "ERRORE"),
        expecting("TEXT_ABSENT", "risultato"),
        expecting("TEXT_ABSENT", "percentuale"),
        expecting("TEXT_VISIBLE", "1,011"),
    )
    snapshot = page(text="Calcolo della mancia Conto Percentuale Errore", hidden=PAGE_HIDDEN)

    found = plan_flow.weak_expectations([plan], snapshot)

    assert found == [
        weak("TP-001", 2, "VISIBLE_AT_OPENING", "  CALCOLO   della MANCIA "),
        weak("TP-001", 3, "HIDDEN_AT_OPENING", "DA UNA MANCIA di 1,01"),
        weak("TP-001", 4, "HIDDEN_AT_OPENING", "Totale  Esempio"),
        weak("TP-001", 5, "ABSENT_VISIBLE_AT_OPENING", "ERRORE"),
        weak("TP-001", 7, "ABSENT_VISIBLE_AT_OPENING", "percentuale"),
    ]


def test_a_text_cut_by_the_limits_of_the_snapshot_is_never_called_absent() -> None:
    hidden_cut = "a" * (MAX_SNAPSHOT_HIDDEN_TEXT_LENGTH - 5) + " 11,0"
    text_cut = "b " * (MAX_SNAPSHOT_TEXT_LENGTH // 2 - 1) + "c"
    plan = steps_path(
        "TP-001",
        OPEN,
        expecting("TEXT_VISIBLE", "11,06"),
        expecting("TEXT_VISIBLE", "11,0"),
        expecting("TEXT_ABSENT", "Errore"),
    )
    short = "a" * (MAX_SNAPSHOT_HIDDEN_TEXT_LENGTH - 2)

    at_hidden_limit = plan_flow.weak_expectations([plan], page(hidden=hidden_cut))
    at_text_limit = plan_flow.weak_expectations([plan], page(text=text_cut))
    under_limits = plan_flow.weak_expectations([plan], page(text=PAGE_TEXT, hidden=short))

    assert len(hidden_cut) == MAX_SNAPSHOT_HIDDEN_TEXT_LENGTH
    assert len(text_cut) == MAX_SNAPSHOT_TEXT_LENGTH - 1
    assert at_hidden_limit == [weak("TP-001", 3, "HIDDEN_AT_OPENING", "11,0")]
    assert at_text_limit == []
    assert under_limits == [weak("TP-001", 4, "NEVER_ON_PAGE", "Errore")]


def test_the_absence_of_a_text_the_page_shows_at_opening_can_never_be_verified() -> None:
    plan = steps_path(
        "TP-001",
        expecting("TEXT_ABSENT", "Calcolo della mancia", action="OPEN"),
        expecting("TEXT_ABSENT", "  TOTALE "),
        expecting("TEXT_ABSENT", "Esempio"),
        expecting("TEXT_ABSENT", "Errore"),
        expecting("TEXT_VISIBLE", "Esempio"),
    )
    shown = page(text="Calcolo della mancia Totale 11,06", hidden="Totale Esempio: 11,06")
    cut = page(
        text="Calcolo della mancia Totale " + "x" * MAX_SNAPSHOT_TEXT_LENGTH,
        hidden="Totale Esempio: 11,06",
    )

    found = plan_flow.weak_expectations([plan], shown)
    at_limit = plan_flow.weak_expectations([plan], cut)

    assert found == [
        weak("TP-001", 1, "ABSENT_VISIBLE_AT_OPENING", "Calcolo della mancia"),
        weak("TP-001", 2, "ABSENT_VISIBLE_AT_OPENING", "  TOTALE "),
        weak("TP-001", 4, "NEVER_ON_PAGE", "Errore"),
        weak("TP-001", 5, "HIDDEN_AT_OPENING", "Esempio"),
    ]
    assert at_limit == [
        weak("TP-001", 1, "ABSENT_VISIBLE_AT_OPENING", "Calcolo della mancia"),
        weak("TP-001", 2, "ABSENT_VISIBLE_AT_OPENING", "  TOTALE "),
        weak("TP-001", 5, "HIDDEN_AT_OPENING", "Esempio"),
    ]


def test_blank_texts_other_expectations_and_steps_without_one_prove_nothing_here() -> None:
    plan = steps_path(
        "TP-001",
        OPEN,
        expecting("TEXT_VISIBLE", ""),
        expecting("TEXT_VISIBLE", "   "),
        expecting("TEXT_ABSENT", None),
        expecting("TEXT_ABSENT", 12),
        {
            "action": "CLICK",
            "target": {"role": "button", "name": "Calcola"},
            "value": None,
            "expect": {
                "kind": "ELEMENT_VISIBLE",
                "target": {"role": "button", "name": "Calcola"},
                "text": "Calcola",
            },
        },
        {
            "action": "CHECK",
            "target": None,
            "value": None,
            "expect": {
                "kind": "VALUE_IS",
                "target": {"role": "textbox", "name": "Conto"},
                "text": "Conto",
            },
        },
        expecting("URL_CONTAINS", "127.0.0.1"),
        expecting("TITLE_CONTAINS", "Mancia"),
        expecting("ELEMENT_ABSENT", "Errore"),
        expecting("SOUND_PLAYS", "Errore"),
        {"action": "CHECK", "target": None, "value": None, "expect": "TEXT_VISIBLE"},
    )
    nameless = {"heading": "Senza codice", "steps": [expecting("TEXT_VISIBLE", "Calcola")]}
    older = {key: value for key, value in page().items() if key != "hidden_text"}

    assert plan_flow.weak_expectations([plan, nameless], page()) == []
    assert (
        plan_flow.weak_expectations(
            [steps_path("TP-002", OPEN, "noise", expecting("TEXT_VISIBLE", "Totale"))], older
        )
        == []
    )
    assert plan_flow.weak_expectations(
        [steps_path("TP-003", OPEN, "noise", expecting("TEXT_VISIBLE", "Conto"))], older
    ) == [weak("TP-003", 2, "VISIBLE_AT_OPENING", "Conto")]


def test_the_case_of_the_measure_with_its_real_texts() -> None:
    example = measure_path("TP-005", "10,05", "10", "1,01", "11,06")
    other = measure_path("TP-006", "33,33", "15", "5,00", "38,33")
    empty_bill = steps_path(
        "TP-007",
        OPEN,
        {
            "action": "CLICK",
            "target": {"role": "radio", "name": "10%"},
            "value": None,
            "expect": None,
        },
        {
            "action": "CLICK",
            "target": {"role": "button", "name": "Calcola"},
            "value": None,
            "expect": {"kind": "TEXT_VISIBLE", "target": None, "text": "obbligatorio"},
        },
        expecting("TEXT_ABSENT", "Risultato"),
        expecting("TEXT_ABSENT", "A testa"),
        criteria=("AC-004",),
    )
    snapshot = {**SNAPSHOT, "text": MEASURE_TEXT, "hidden_text": MEASURE_HIDDEN}

    found = plan_flow.weak_expectations([example, other, empty_bill], snapshot)
    both = passed_run(
        example,
        other,
        criteria=[{"code": "AC-003", "status": "PASSED", "paths": ["TP-005", "TP-006"]}],
    )
    alone = passed_run(
        example, criteria=[{"code": "AC-003", "status": "PASSED", "paths": ["TP-005"]}]
    )
    failed = passed_run(
        empty_bill, criteria=[{"code": "AC-004", "status": "FAILED", "paths": ["TP-007"]}]
    )

    assert "quota a testa compaiono" in MEASURE_TEXT
    assert "Mancia A testa" in MEASURE_HIDDEN
    assert found == [
        weak("TP-005", 4, "HIDDEN_AT_OPENING", "1,01"),
        weak("TP-005", 5, "HIDDEN_AT_OPENING", "11,06"),
        weak("TP-007", 5, "ABSENT_VISIBLE_AT_OPENING", "A testa"),
    ]
    assert plan_flow.weakly_passed(both, found) == []
    assert plan_flow.weakly_passed(alone, found) == ["AC-003"]
    assert plan_flow.weakly_passed(failed, found) == []


def test_a_criterion_rests_on_expectations_that_prove_little_only_when_all_of_them_do() -> None:
    only_weak = steps_path("TP-001", OPEN, expecting("TEXT_VISIBLE", "Calcola"))
    mixed = steps_path(
        "TP-002",
        OPEN,
        expecting("TEXT_VISIBLE", "Calcola"),
        expecting("TEXT_VISIBLE", "34,50"),
        criteria=("AC-002",),
    )
    failed = steps_path("TP-003", OPEN, expecting("TEXT_VISIBLE", "Conto"), criteria=("AC-003",))
    silent = steps_path("TP-004", OPEN, criteria=("AC-004",))
    items = [
        weak("TP-001", 2, "VISIBLE_AT_OPENING", "Calcola"),
        weak("TP-002", 2, "VISIBLE_AT_OPENING", "Calcola"),
        weak("TP-003", 2, "VISIBLE_AT_OPENING", "Conto"),
        {"path": ["TP-004"], "step": [1]},
    ]
    run = passed_run(
        only_weak,
        mixed,
        failed,
        silent,
        criteria=[
            {"code": "AC-001", "status": "PASSED", "paths": ["TP-001"]},
            {"code": "AC-002", "status": "PASSED", "paths": ["TP-002"]},
            {"code": "AC-003", "status": "FAILED", "paths": ["TP-003"]},
            {"code": "AC-004", "status": "PASSED", "paths": ["TP-004"]},
            {"code": "AC-005", "status": "PASSED", "paths": []},
            {"code": "AC-006", "status": "PASSED", "paths": ["TP-001", "TP-009"]},
            {"code": "AC-007", "status": "PASSED", "paths": ["TP-001", "TP-002"]},
        ],
    )

    assert plan_flow.weakly_passed(run, items) == ["AC-001"]
    assert plan_flow.weakly_passed(run, []) == []


def test_the_weak_expectations_are_saved_after_the_replans_and_read_again(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    items = (
        weak("TP-001", 2, "VISIBLE_AT_OPENING", "Mancia"),
        weak("TP-003", 2, "HIDDEN_AT_OPENING", "Risultato"),
    )
    written = plan_flow.SavedPlan(
        saved_at="2026-09-29T09:00:00+00:00",
        application={"kind": "STATIC", "address": "dist"},
        plan=copy.deepcopy(PLAN),
        weak=items,
    )

    document = json.loads(plan_flow.save_plan(project, written).read_bytes().decode("utf-8"))
    read = plan_flow.read_plan(project)

    assert list(document)[-2:] == ["replans", "weak_expectations"]
    assert document["weak_expectations"] == list(items)
    assert read == written
    assert read is not None
    assert read.weak_of("TP-003") == [items[1]]
    assert read.weak_of("TP-001", "TP-003") == list(items)
    assert read.weak_of("TP-002") == []
    assert list(plan_flow.SavedPlan.__dataclass_fields__)[-1] == "weak"


def test_a_plan_saved_before_the_weak_expectations_still_reads() -> None:
    document = {
        "schema_version": 1,
        "saved_at": "2026-09-29T09:00:00+00:00",
        "application": {"kind": "STATIC", "address": "dist"},
        "plan": PLAN,
        "replans": [],
    }

    found = plan_flow.saved_plan_from(document)

    assert found is not None
    assert found.weak == ()
    assert found.plan_id == PLAN_ID


VALID_ITEM = {"path": "TP-001", "step": 2, "kind": "HIDDEN_AT_OPENING", "text": "1,01"}


@pytest.mark.parametrize(
    "value",
    [
        None,
        "TP-001",
        {"items": []},
        [1],
        [VALID_ITEM, None],
        [{key: value for key, value in VALID_ITEM.items() if key != "text"}],
        [{**VALID_ITEM, "kind": "WEAK"}],
        [{**VALID_ITEM, "step": 0}],
        [{**VALID_ITEM, "step": True}],
        [{**VALID_ITEM, "step": "2"}],
        [{**VALID_ITEM, "path": ""}],
        [{**VALID_ITEM, "path": 1}],
        [{**VALID_ITEM, "text": "  "}],
        [{**VALID_ITEM, "text": 101}],
    ],
)
def test_a_broken_list_of_weak_expectations_reads_as_none(value: object) -> None:
    document = {"schema_version": 1, "plan": PLAN, "replans": [], "weak_expectations": value}

    found = plan_flow.saved_plan_from(document)

    assert found is not None
    assert found.weak == ()
    assert found.plan_id == PLAN_ID


def test_a_valid_list_keeps_only_the_four_keys_of_each_item() -> None:
    absent = {**VALID_ITEM, "step": 5, "kind": "ABSENT_VISIBLE_AT_OPENING", "text": "A testa"}
    document = {
        "schema_version": 1,
        "plan": PLAN,
        "weak_expectations": [{**VALID_ITEM, "note": "x"}, absent],
    }

    found = plan_flow.saved_plan_from(document)

    assert found is not None
    assert found.weak == (VALID_ITEM, absent)
    assert plan_flow.weak_items([]) == ()


def test_a_replan_drops_the_weak_expectations_of_the_paths_it_replaces() -> None:
    before = plan_flow.SavedPlan(
        saved_at="earlier",
        application={"kind": "STATIC", "address": "dist"},
        plan=copy.deepcopy(PLAN),
        weak=(
            weak("TP-001", 2, "VISIBLE_AT_OPENING", "Mancia"),
            weak("TP-002", 2, "HIDDEN_AT_OPENING", "Risultato"),
            weak("TP-003", 2, "NEVER_ON_PAGE", "Errore"),
        ),
    )
    fresh = [weak("TP-004", 2, "HIDDEN_AT_OPENING", "Percentuali")]

    after = before.with_replan(REPLAN, saved_at="later", weak=fresh)
    plain = before.with_replan(REPLAN, saved_at="later")

    assert [item["code"] for item in after.paths()] == ["TP-001", "TP-004"]
    assert after.weak == (weak("TP-001", 2, "VISIBLE_AT_OPENING", "Mancia"), *fresh)
    assert plain.weak == (weak("TP-001", 2, "VISIBLE_AT_OPENING", "Mancia"),)
    assert after.replans == (REPLAN,)
    assert after.saved_at == "later"
