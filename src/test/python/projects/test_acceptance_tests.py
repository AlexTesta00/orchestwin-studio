from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from orchestwin.knowledge.state import (
    APPLICATION_KINDS,
    CRITERION_STATUSES,
    MAX_BROWSERS,
    MAX_EARLIER_PATHS,
    MAX_FINDINGS,
    MAX_PAGE_TEXT_LENGTH,
    MAX_PATHS,
    MAX_RESULTS,
    MAX_SNAPSHOT_ELEMENTS,
    MAX_SNAPSHOT_HIDDEN_TEXT_LENGTH,
    MAX_SNAPSHOT_OPTIONS,
    MAX_SNAPSHOT_TEXT_LENGTH,
    MAX_STEP_DETAIL_LENGTH,
    MAX_STEPS,
    MAX_TARGET_NAME_LENGTH,
    PATH_STATUSES,
    STEP_STATUSES,
    TEST_ACTIONS,
    TEST_EXPECTATIONS,
    TEST_KEYS,
    ProjectStateSources,
)
from orchestwin.projects import acceptance_tests as domain
from orchestwin.projects.acceptance_tests import (
    CUT_MARK,
    MAX_REPLANS,
    ApplicationKind,
    BrowserInfo,
    CriterionOutcome,
    CriterionStatus,
    EarlierPath,
    ExpectationKind,
    NotCovered,
    PageSnapshot,
    PathResult,
    PathStatus,
    RunSummary,
    SnapshotElement,
    StepAction,
    StepResult,
    StepStatus,
    TestApplication,
    TestCritique,
    TestExpectation,
    TestFinding,
    TestPath,
    TestPlan,
    TestPlanUnknown,
    TestReview,
    TestStep,
    TestTarget,
    build_test_run,
    criteria_outcomes,
    critique_from_snapshot,
    cut_text,
    normalize_address,
    normalize_screenshot,
    page_snapshot_from_document,
    path_code,
    path_from_snapshot,
    path_number,
    path_result_from_snapshot,
    run_summary,
)
from orchestwin.projects.code_changes import CritiqueVerdict, FindingSeverity
from src.test.python.artifacts import design_fixtures

PROJECT = design_fixtures.PROJECT_ID
OWNER = design_fixtures.OWNER_ID
PLAN_ID = UUID("00000000-0000-4000-8000-000000000c01")
REPLAN_ID = UUID("00000000-0000-4000-8000-000000000c02")
RUN_ID = UUID("00000000-0000-4000-8000-000000000c10")
REVIEW_ID = UUID("00000000-0000-4000-8000-000000000c20")
TWIN_ONE = UUID("00000000-0000-4000-8000-000000000a01")
TWIN_TWO = UUID("00000000-0000-4000-8000-000000000a02")
NOW = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
HEADING = "Calcolo della mancia con il pulsante"
STATIC = TestApplication(kind=ApplicationKind.STATIC, address="dist")


def target(role="button", name="Calcola"):
    return TestTarget(role=role, name=name)


def opening(value="/"):
    return TestStep(action=StepAction.OPEN, value=value)


def clicking(name="Calcola", expect=None):
    return TestStep(action=StepAction.CLICK, target=target(name=name), expect=expect)


def typing(value="42", name="Importo del conto"):
    return TestStep(action=StepAction.TYPE, target=target("textbox", name), value=value)


def checking(text="Mancia"):
    return TestStep(
        action=StepAction.CHECK,
        expect=TestExpectation(kind=ExpectationKind.TEXT_VISIBLE, text=text),
    )


def sample_path(code="TP-001", criteria=("AC-001",), steps=None, heading=HEADING):
    return TestPath(
        code=code,
        heading=heading,
        criteria=tuple(criteria),
        steps=steps if steps is not None else (opening(), typing(), clicking(), checking()),
    )


def sample_plan(**values):
    arguments = {
        "id": PLAN_ID,
        "project_id": PROJECT,
        "owner_user_id": OWNER,
        "created_at": NOW,
        "locale": "it-IT",
        "requirements_version_number": 1,
        "design_version_number": 4,
        "alternative_code": "DES-002",
        "application": STATIC,
        "criteria": ("AC-001", "AC-002", "AC-003"),
        "paths": (
            sample_path(),
            sample_path("TP-002", ("AC-002",), steps=(opening(), checking("Totale"))),
        ),
        "not_covered": (NotCovered(criterion="AC-003", reason="Serve un controllo manuale."),),
        "snapshot_summary": domain.SnapshotSummary(
            url="http://127.0.0.1:8123/index.html", title="Mance", elements=4, text_length=120
        ),
        "generation_ids": (UUID(int=0xE101),),
        "cost_microusd": 210_000,
    }
    arguments.update(values)
    return TestPlan(**arguments)


def step_results(count, *statuses):
    listed = list(statuses) + [StepStatus.DONE] * (count - len(statuses))
    return tuple(
        StepResult(
            index=index,
            status=status,
            detail=None if status is StepStatus.DONE else "target not found: button: Calcola",
            url="http://127.0.0.1:8123/index.html",
            title="Mance",
            screenshot=f"TP-001/chrome/{index:02d}.png",
        )
        for index, status in enumerate(listed[:count], 1)
    )


def sample_result(path=None, browser="chrome", status=PathStatus.PASSED, steps=None, **values):
    chosen = path if path is not None else sample_path()
    arguments = {
        "path": chosen,
        "browser": browser,
        "status": status,
        "seconds": 4.2,
        "steps": steps if steps is not None else step_results(len(chosen.steps)),
        "page_text": "Mancia 6,30 euro Totale 48,30 euro",
    }
    arguments.update(values)
    return PathResult(**arguments)


def browsers():
    return (
        BrowserInfo(name="chrome", version="151.0.7922.76"),
        BrowserInfo(name="firefox", version="156.0.1"),
    )


def sample_run(plans=None, results=None, not_covered=None, **values):
    chosen = plans if plans is not None else (sample_plan(),)
    arguments = {
        "run_id": RUN_ID,
        "plans": chosen,
        "started_at": NOW + timedelta(hours=1),
        "finished_at": NOW + timedelta(hours=1, minutes=2),
        "recorded_at": NOW + timedelta(hours=1, minutes=3),
        "application": STATIC,
        "browsers": browsers(),
        "results": results
        if results is not None
        else (sample_result(), sample_result(browser="firefox")),
        "not_covered": not_covered if not_covered is not None else chosen[0].not_covered,
    }
    arguments.update(values)
    return build_test_run(**arguments)


def sample_finding(**values):
    arguments = {
        "severity": FindingSeverity.MEDIUM,
        "text": "Il totale non mostra la valuta che uso.",
        "criterion": "AC-001",
        "requirement": "REQ-001",
        "screen": "SCR-001",
        "action": "Mostrare la valuta accanto al totale.",
    }
    arguments.update(values)
    return TestFinding(**arguments)


def sample_critique(twin_id=TWIN_ONE, twin_name="Receptionist Twin", **values):
    arguments = {
        "twin_id": twin_id,
        "twin_name": twin_name,
        "verdict": CritiqueVerdict.CONCERN,
        "summary": "Il calcolo funziona ma resta un dubbio sulla valuta che uso.",
        "findings": (sample_finding(),),
    }
    arguments.update(values)
    return TestCritique(**arguments)


def sample_review(run_id=RUN_ID, **values):
    arguments = {
        "id": REVIEW_ID,
        "run_id": run_id,
        "project_id": PROJECT,
        "owner_user_id": OWNER,
        "reviewed_at": NOW + timedelta(hours=2),
        "locale": "it-IT",
        "critiques": (sample_critique(),),
        "generation_ids": (UUID(int=0xE201),),
        "cost_microusd": 150_000,
    }
    arguments.update(values)
    return TestReview(**arguments)


def element(index=0, role="button", name="Calcola", **values):
    return SnapshotElement(index=index, role=role, name=name, **values)


def page(**values):
    arguments = {
        "url": "http://127.0.0.1:8123/index.html",
        "title": "Mance",
        "text": "Calcola la mancia Importo del conto",
        "elements": (
            element(0, "heading", "Calcola la mancia"),
            element(1, "textbox", "Importo del conto", value=""),
            element(2, "combobox", "Percentuale", value="15", options=("10", "15", "20")),
            element(3, "checkbox", "Arrotonda", state="checked"),
            element(4, "button", "Calcola", state="disabled"),
        ),
    }
    arguments.update(values)
    return PageSnapshot(**arguments)


def test_the_enumerations_match_the_shared_contract():
    assert tuple(item.value for item in ApplicationKind) == APPLICATION_KINDS
    assert tuple(item.value for item in StepAction) == TEST_ACTIONS
    assert tuple(item.value for item in ExpectationKind) == TEST_EXPECTATIONS
    assert tuple(item.value for item in PathStatus) == PATH_STATUSES
    assert tuple(item.value for item in StepStatus) == STEP_STATUSES
    assert tuple(item.value for item in CriterionStatus) == CRITERION_STATUSES


@pytest.mark.parametrize(
    ("number", "code"),
    [(1, "TP-001"), (42, "TP-042"), (999, "TP-999"), (1000, "TP-1000"), (999999, "TP-999999")],
)
def test_path_codes_continue_the_three_digit_sequence(number, code):
    assert path_code(number) == code
    assert path_number(code) == number


@pytest.mark.parametrize("number", [0, -1, 1_000_000, True, 1.0, "1"])
def test_a_path_number_is_a_positive_integer_within_six_digits(number):
    with pytest.raises(ValueError):
        path_code(number)


@pytest.mark.parametrize("code", ["TP-1", "TP-1234567", "tp-001", "AC-001", 1])
def test_a_path_code_follows_the_tp_format(code):
    with pytest.raises(ValueError):
        path_number(code)


@pytest.mark.parametrize(
    ("kind", "address", "expected"),
    [
        (ApplicationKind.URL, "https://mance.example.org/app", "https://mance.example.org/app"),
        (ApplicationKind.URL, " http://127.0.0.1:5173/ ", "http://127.0.0.1:5173/"),
        (ApplicationKind.URL, "HTTP://localhost", "HTTP://localhost"),
        (ApplicationKind.STATIC, "dist", "dist"),
        (ApplicationKind.STATIC, "web/build output", "web/build output"),
        (ApplicationKind.STATIC, ".", "."),
    ],
)
def test_an_application_address_is_kept_as_the_owner_typed_it(kind, address, expected):
    assert normalize_address(kind, address) == expected
    application = TestApplication(kind=kind, address=expected)
    assert application.to_snapshot() == {"kind": kind.value, "address": expected}
    assert domain.application_from_snapshot(application.to_snapshot()) == application


@pytest.mark.parametrize(
    ("kind", "address"),
    [
        (ApplicationKind.URL, "ftp://example.org"),
        (ApplicationKind.URL, "example.org"),
        (ApplicationKind.URL, "http://"),
        (ApplicationKind.URL, "http://exa mple.org"),
        (ApplicationKind.URL, "http://[::1"),
        (ApplicationKind.URL, "http://" + "a" * 500),
        (ApplicationKind.URL, "   "),
        (ApplicationKind.URL, "http://example.org/\x07"),
        (ApplicationKind.STATIC, "/home/owner/dist"),
        (ApplicationKind.STATIC, "C:/progetto/dist"),
        (ApplicationKind.STATIC, "web\\dist"),
        (ApplicationKind.STATIC, "../dist"),
        (ApplicationKind.STATIC, "web/../dist"),
        (ApplicationKind.STATIC, "web//dist"),
        (ApplicationKind.STATIC, "./dist"),
        (ApplicationKind.STATIC, "dist/"),
    ],
)
def test_an_application_address_outside_the_rules_is_refused(kind, address):
    with pytest.raises(ValueError):
        normalize_address(kind, address)


def test_an_application_needs_a_kind_and_a_normalized_address():
    with pytest.raises(ValueError):
        TestApplication(kind="URL", address="http://example.org")
    with pytest.raises(ValueError):
        TestApplication(kind=ApplicationKind.STATIC, address=" dist ")


@pytest.mark.parametrize(
    ("value", "maximum", "expected"),
    [
        ("  Calcola   la\n mancia ", 50, "Calcola la mancia"),
        ("a\x00b\x07c", 10, "abc"),
        ("x" * 12, 10, "x" * 9 + CUT_MARK),
        ("parola " * 3, 10, "parola " + "pa" + CUT_MARK),
        ("", 10, ""),
    ],
)
def test_texts_read_from_a_page_are_collapsed_and_cut(value, maximum, expected):
    assert cut_text(value, maximum=maximum) == expected


def test_a_snapshot_round_trips_and_summarizes_itself():
    snapshot = page()
    document = snapshot.to_snapshot()
    assert list(document) == ["url", "title", "text", "hidden_text", "elements"]
    assert document["hidden_text"] == ""
    assert document["elements"][2] == {
        "index": 2,
        "role": "combobox",
        "name": "Percentuale",
        "value": "15",
        "state": None,
        "options": ["10", "15", "20"],
    }
    assert page_snapshot_from_document(document) == snapshot
    summary = snapshot.summary()
    assert summary.to_snapshot() == {
        "url": "http://127.0.0.1:8123/index.html",
        "title": "Mance",
        "elements": 5,
        "text_length": len(snapshot.text),
    }
    assert domain.snapshot_summary_from_snapshot(summary.to_snapshot()) == summary
    empty = PageSnapshot(url="about:blank", title="", text="")
    assert empty.summary().elements == 0


def test_a_snapshot_carries_the_text_that_the_page_hides_when_it_is_read():
    hidden = "Mancia calcolata Totale da pagare"
    snapshot = page(hidden_text=hidden)
    document = snapshot.to_snapshot()
    assert list(document) == ["url", "title", "text", "hidden_text", "elements"]
    assert (document["text"], document["hidden_text"]) == (page().text, hidden)
    assert page_snapshot_from_document(document) == snapshot
    older = {key: value for key, value in page().to_snapshot().items() if key != "hidden_text"}
    assert page_snapshot_from_document(older) == page()
    assert page_snapshot_from_document(older).hidden_text == ""
    assert PageSnapshot(url="about:blank", title="", text="").hidden_text == ""
    assert snapshot.summary() == page().summary()
    assert list(snapshot.summary().to_snapshot()) == ["url", "title", "elements", "text_length"]
    assert snapshot.summary().text_length == len(page().text)
    longest = "x" * MAX_SNAPSHOT_HIDDEN_TEXT_LENGTH
    assert page(hidden_text=longest).hidden_text == longest
    cut = cut_text("Sezione " * 1000, maximum=MAX_SNAPSHOT_HIDDEN_TEXT_LENGTH)
    assert page(hidden_text=cut).hidden_text.endswith(CUT_MARK)
    with pytest.raises(ValueError, match="snapshot hidden text"):
        page_snapshot_from_document({**document, "hidden_text": None})


@pytest.mark.parametrize(
    "values",
    [
        {"hidden_text": "x" * (MAX_SNAPSHOT_HIDDEN_TEXT_LENGTH + 1)},
        {"hidden_text": "Mancia  calcolata"},
        {"hidden_text": " Mancia calcolata"},
        {"hidden_text": "Mancia calcolata "},
        {"hidden_text": "Mancia\ncalcolata"},
        {"hidden_text": "Mancia\x07calcolata"},
        {"hidden_text": None},
        {"hidden_text": 42},
        {"hidden_text": ("Mancia calcolata",)},
    ],
)
def test_a_hidden_text_over_the_limit_not_collapsed_or_not_a_text_is_refused(values):
    with pytest.raises(ValueError, match="snapshot hidden text"):
        page(**values)


@pytest.mark.parametrize(
    "values",
    [
        {"role": "menu"},
        {"index": -1},
        {"index": True},
        {"state": "hidden"},
        {"name": "x" * (MAX_TARGET_NAME_LENGTH + 1)},
        {"name": " Calcola"},
        {"name": "Cal\x07cola"},
        {"options": ("uno",)},
        {"role": "combobox", "options": ("x",) * (MAX_SNAPSHOT_OPTIONS + 1)},
        {"role": "combobox", "options": ["uno"]},
        {"value": "x" * (domain.MAX_SNAPSHOT_VALUE_LENGTH + 1)},
    ],
)
def test_every_limit_of_a_snapshot_element_is_validated(values):
    arguments = {"index": 0, "role": "button", "name": "Calcola", **values}
    with pytest.raises(ValueError):
        SnapshotElement(**arguments)


def test_a_snapshot_holds_at_most_its_limits_and_distinct_indexes():
    many = tuple(element(index) for index in range(MAX_SNAPSHOT_ELEMENTS))
    assert len(page(elements=many).elements) == MAX_SNAPSHOT_ELEMENTS
    assert element(role="combobox", options=("x",) * MAX_SNAPSHOT_OPTIONS).options
    assert element(name="").name == ""
    for values in (
        {"elements": (*many, element(MAX_SNAPSHOT_ELEMENTS))},
        {"elements": (element(1), element(1))},
        {"elements": [element(0)]},
        {"text": "x" * (MAX_SNAPSHOT_TEXT_LENGTH + 1)},
        {"title": "t" * (domain.MAX_SNAPSHOT_TITLE_LENGTH + 1)},
        {"url": "u" * (domain.MAX_SNAPSHOT_URL_LENGTH + 1)},
        {"text": "doppio  spazio"},
    ):
        with pytest.raises(ValueError):
            page(**values)


@pytest.mark.parametrize(
    ("kind", "arguments"),
    [
        (ExpectationKind.TEXT_VISIBLE, {"text": "Mancia"}),
        (ExpectationKind.TEXT_ABSENT, {"text": "Errore"}),
        (ExpectationKind.ELEMENT_VISIBLE, {"target": target()}),
        (ExpectationKind.ELEMENT_ABSENT, {"target": target("alert", "Errore")}),
        (ExpectationKind.VALUE_IS, {"target": target("textbox", "Totale"), "text": "48,30"}),
        (ExpectationKind.URL_CONTAINS, {"text": "/risultato"}),
        (ExpectationKind.TITLE_CONTAINS, {"text": "Mance"}),
    ],
)
def test_each_expectation_carries_exactly_what_its_kind_needs(kind, arguments):
    expectation = TestExpectation(kind=kind, **arguments)
    snapshot = expectation.to_snapshot()
    assert list(snapshot) == ["kind", "target", "text"]
    assert domain.expectation_from_snapshot(snapshot) == expectation
    if "target" in arguments:
        with pytest.raises(ValueError, match="needs target"):
            TestExpectation(kind=kind, text=arguments.get("text"))
    else:
        with pytest.raises(ValueError, match="takes no target"):
            TestExpectation(kind=kind, target=target(), text=arguments["text"])
    if "text" in arguments:
        with pytest.raises(ValueError, match="needs text"):
            TestExpectation(kind=kind, target=arguments.get("target"))
    else:
        with pytest.raises(ValueError, match="takes no text"):
            TestExpectation(kind=kind, target=arguments["target"], text="x")


def test_a_target_names_a_role_of_the_contract_or_any_role():
    assert target().to_snapshot() == {"role": "button", "name": "Calcola"}
    assert TestTarget(role=None, name="Calcola").to_snapshot()["role"] is None
    for values in (
        {"role": "menu"},
        {"name": ""},
        {"name": "x" * (MAX_TARGET_NAME_LENGTH + 1)},
        {"name": "Calcola  ora"},
    ):
        with pytest.raises(ValueError):
            TestTarget(**{"role": "button", "name": "Calcola", **values})


@pytest.mark.parametrize(
    "step",
    [
        TestStep(action=StepAction.OPEN, value="/"),
        TestStep(action=StepAction.OPEN, value="index.html"),
        TestStep(action=StepAction.OPEN, value="https://mance.example.org/ordini?x=1"),
        TestStep(action=StepAction.CLICK, target=TestTarget(role=None, name="Calcola")),
        TestStep(action=StepAction.CLICK, target=TestTarget(role="cell", name="Totale")),
        TestStep(action=StepAction.TYPE, target=target("spinbutton", "Persone"), value="3"),
        TestStep(action=StepAction.SELECT, target=target("combobox", "Percentuale"), value="15"),
        TestStep(action=StepAction.PRESS, value="Enter"),
        TestStep(
            action=StepAction.CHECK,
            expect=TestExpectation(kind=ExpectationKind.URL_CONTAINS, text="/risultato"),
        ),
    ],
)
def test_every_action_accepts_the_fields_it_needs(step):
    assert domain.step_from_snapshot(step.to_snapshot()) == step
    assert list(step.to_snapshot()) == ["action", "target", "value", "expect"]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"action": StepAction.OPEN}, "needs value"),
        ({"action": StepAction.OPEN, "value": "/", "target": target()}, "takes no target"),
        ({"action": StepAction.OPEN, "value": "file:///etc/passwd"}, "OPEN step"),
        ({"action": StepAction.OPEN, "value": "javascript:alert(1)"}, "OPEN step"),
        ({"action": StepAction.OPEN, "value": "localhost:8080"}, "OPEN step"),
        ({"action": StepAction.CLICK}, "needs target"),
        ({"action": StepAction.CLICK, "target": target(), "value": "x"}, "takes no value"),
        ({"action": StepAction.CLICK, "target": target("progressbar", "Carico")}, "cannot act"),
        ({"action": StepAction.TYPE, "target": target("textbox", "Importo")}, "needs value"),
        ({"action": StepAction.TYPE, "target": target(), "value": "3"}, "cannot act"),
        (
            {"action": StepAction.SELECT, "target": target("textbox", "Mancia"), "value": "15"},
            "cannot act",
        ),
        ({"action": StepAction.PRESS}, "needs value"),
        ({"action": StepAction.PRESS, "value": "Invio"}, "test keys"),
        ({"action": StepAction.PRESS, "value": "enter"}, "test keys"),
        ({"action": StepAction.PRESS, "value": "Enter", "target": target()}, "takes no target"),
        ({"action": StepAction.CHECK}, "needs an expectation"),
        ({"action": StepAction.CHECK, "value": "x"}, "takes no value"),
        ({"action": "OPEN", "value": "/"}, "StepAction"),
        (
            {"action": StepAction.TYPE, "target": target("textbox", "Importo"), "value": " 3"},
            "normalized",
        ),
        (
            {"action": StepAction.TYPE, "target": target("textbox", "I"), "value": "x" * 201},
            "exceeds",
        ),
    ],
)
def test_the_rules_of_the_actions_are_enforced(arguments, message):
    with pytest.raises(ValueError, match=message):
        TestStep(**arguments)


def test_every_key_of_the_contract_can_be_pressed():
    for key in TEST_KEYS:
        assert TestStep(action=StepAction.PRESS, value=key).value == key


def test_a_path_has_the_shape_and_the_limits_of_the_contract():
    path = sample_path()
    snapshot = path.to_snapshot()
    assert list(snapshot) == ["code", "heading", "criteria", "steps"]
    assert snapshot["steps"][1] == {
        "action": "TYPE",
        "target": {"role": "textbox", "name": "Importo del conto"},
        "value": "42",
        "expect": None,
    }
    assert path_from_snapshot(snapshot) == path
    longest = sample_path(steps=(opening(), *(checking() for _ in range(MAX_STEPS - 1))))
    assert len(longest.steps) == MAX_STEPS
    assert sample_path(criteria=tuple(f"AC-00{index}" for index in range(1, 7))).criteria
    for values in (
        {"steps": ()},
        {"steps": (checking(),)},
        {"steps": (opening(),) * (MAX_STEPS + 1)},
        {"steps": [opening()]},
        {"criteria": ()},
        {"criteria": ("AC-001", "AC-001")},
        {"criteria": ("REQ-001",)},
        {"criteria": tuple(f"AC-00{index}" for index in range(1, 8))},
        {"heading": ""},
        {"heading": "x" * 121},
        {"code": "TP-1"},
    ):
        with pytest.raises(ValueError):
            sample_path(**values)


def test_an_earlier_path_names_a_step_of_its_path():
    earlier = EarlierPath(
        path=sample_path(), blocked_step=3, detail="target not found: button: Calcola"
    )
    context = earlier.to_context()
    assert list(context) == [
        "code",
        "heading",
        "criteria",
        "steps",
        "blocked_step",
        "detail",
        "snapshot",
    ]
    assert context["snapshot"] is None
    assert EarlierPath(path=sample_path(), blocked_step=1, snapshot=page()).to_context()[
        "snapshot"
    ] == (page().to_snapshot())
    for values in (
        {"blocked_step": 0},
        {"blocked_step": 5},
        {"detail": "x" * (MAX_STEP_DETAIL_LENGTH + 1)},
        {"snapshot": page().to_snapshot()},
    ):
        with pytest.raises(ValueError):
            EarlierPath(**{"path": sample_path(), "blocked_step": 1, **values})


def test_a_plan_has_the_exact_shape_of_the_contract():
    plan = sample_plan(replan_of=("TP-003",))
    snapshot = plan.to_snapshot()
    assert list(snapshot) == [
        "id",
        "created_at",
        "locale",
        "reference",
        "application",
        "criteria",
        "replan_of",
        "paths",
        "not_covered",
        "cost_microusd",
    ]
    assert snapshot["id"] == str(PLAN_ID)
    assert snapshot["created_at"] == "2026-09-29T10:00:00+00:00"
    assert snapshot["reference"] == {
        "requirements_version_number": 1,
        "design_version_number": 4,
        "alternative_code": "DES-002",
    }
    assert snapshot["application"] == {"kind": "STATIC", "address": "dist"}
    assert snapshot["criteria"] == ["AC-001", "AC-002", "AC-003"]
    assert snapshot["replan_of"] == ["TP-003"]
    assert [item["code"] for item in snapshot["paths"]] == ["TP-001", "TP-002"]
    assert snapshot["not_covered"] == [
        {"criterion": "AC-003", "reason": "Serve un controllo manuale."}
    ]
    assert snapshot["cost_microusd"] == 210_000
    assert (
        sample_plan(
            created_at=datetime(2026, 9, 29, 12, 0, tzinfo=timezone(timedelta(hours=2)))
        ).to_snapshot()["created_at"]
        == "2026-09-29T10:00:00+00:00"
    )


@pytest.mark.parametrize(
    "values",
    [
        {"criteria": ()},
        {"criteria": ("AC-001", "AC-001", "AC-002", "AC-003")},
        {"not_covered": ()},
        {"not_covered": (NotCovered(criterion="AC-004", reason="Fuori."),)},
        {"not_covered": (NotCovered(criterion="AC-001", reason="Doppio."),)},
        {
            "not_covered": (
                NotCovered(criterion="AC-003", reason="Uno."),
                NotCovered(criterion="AC-003", reason="Due."),
            )
        },
        {"paths": (sample_path(), sample_path())},
        {"paths": (sample_path(criteria=("AC-009",)),)},
        {"paths": tuple(sample_path(path_code(index)) for index in range(1, MAX_PATHS + 2))},
        {"replan_of": tuple(path_code(index) for index in range(1, MAX_EARLIER_PATHS + 2))},
        {"replan_of": ("TP-001", "TP-001")},
        {"locale": "it_IT"},
        {"alternative_code": "ALT-001"},
        {"requirements_version_number": 0},
        {"design_version_number": None},
        {"cost_microusd": -1},
        {"generation_ids": (UUID(int=1), UUID(int=1))},
        {"created_at": datetime(2026, 9, 29, 10, 0)},
        {"application": {"kind": "STATIC", "address": "dist"}},
        {"snapshot_summary": {"url": "x"}},
    ],
)
def test_every_rule_of_a_plan_is_validated(values):
    with pytest.raises(ValueError):
        sample_plan(**values)


def test_a_plan_may_hold_no_path_when_every_criterion_is_not_covered():
    plan = sample_plan(
        criteria=("AC-003",),
        paths=(),
        not_covered=(NotCovered(criterion="AC-003", reason="Serve un controllo manuale."),),
    )
    assert plan.to_snapshot()["paths"] == []


def test_a_step_result_and_a_path_result_have_the_shape_of_the_contract():
    result = sample_result(
        status=PathStatus.BLOCKED,
        steps=step_results(4, *[StepStatus.DONE] * 2, StepStatus.BLOCKED, StepStatus.SKIPPED),
    )
    snapshot = result.to_snapshot()
    assert list(snapshot) == ["path", "browser", "status", "seconds", "steps", "page_text"]
    assert snapshot["seconds"] == 4.2
    assert snapshot["steps"][2] == {
        "index": 3,
        "status": "BLOCKED",
        "detail": "target not found: button: Calcola",
        "url": "http://127.0.0.1:8123/index.html",
        "title": "Mance",
        "screenshot": "TP-001/chrome/03.png",
    }
    assert path_result_from_snapshot(snapshot) == result
    assert sample_result(seconds=4).to_snapshot()["seconds"] == 4.0
    assert sample_result(steps=()).steps == ()
    assert sample_result(status=PathStatus.NOT_RUN, steps=(), page_text=None).page_text is None


@pytest.mark.parametrize(
    "values",
    [
        {"browser": "safari"},
        {"status": "PASSED"},
        {"seconds": -0.1},
        {"seconds": float("nan")},
        {"seconds": float("inf")},
        {"seconds": domain.MAX_PATH_SECONDS + 1},
        {"seconds": True},
        {"steps": step_results(5)},
        {"steps": step_results(4)[1:]},
        {"steps": tuple(reversed(step_results(2)))},
        {"steps": list(step_results(1))},
        {"page_text": "x" * (MAX_PAGE_TEXT_LENGTH + 1)},
    ],
)
def test_every_limit_of_a_path_result_is_validated(values):
    with pytest.raises(ValueError):
        sample_result(**values)


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("TP-001/chrome/01.png", True),
        ("01.png", True),
        ("x" * 200, True),
        ("x" * 201, False),
        ("", False),
        ("/TP-001/chrome/01.png", False),
        ("TP-001\\chrome\\01.png", False),
        ("C:/tests/01.png", False),
        ("TP-001/../01.png", False),
        ("TP-001/./01.png", False),
        ("TP-001//01.png", False),
        ("TP-001/\x00.png", False),
    ],
)
def test_a_screenshot_path_stays_inside_the_run_folder(value, valid):
    if valid:
        assert normalize_screenshot(value) == value
        assert StepResult(index=1, status=StepStatus.DONE, screenshot=value).screenshot == value
    else:
        with pytest.raises(ValueError):
            normalize_screenshot(value)


def test_every_limit_of_a_step_result_is_validated():
    for values in (
        {"index": 0},
        {"index": MAX_STEPS + 1},
        {"status": "DONE"},
        {"detail": "x" * (MAX_STEP_DETAIL_LENGTH + 1)},
        {"detail": "due  spazi"},
        {"url": "u" * (domain.MAX_SNAPSHOT_URL_LENGTH + 1)},
        {"title": "t" * (domain.MAX_SNAPSHOT_TITLE_LENGTH + 1)},
    ):
        with pytest.raises(ValueError):
            StepResult(**{"index": 1, "status": StepStatus.DONE, **values})


def statuses(outcomes):
    return {item.code: item.status for item in outcomes}


def test_the_criteria_follow_every_result_that_names_them_in_every_browser():
    first = sample_path("TP-001", ("AC-001", "AC-002"))
    second = sample_path("TP-002", ("AC-002", "AC-003"))
    third = sample_path("TP-003", ("AC-004",))
    fourth = sample_path("TP-004", ("AC-005",))
    fifth = sample_path("TP-005", ("AC-006",))
    results = (
        sample_result(first, "chrome", PathStatus.PASSED),
        sample_result(first, "firefox", PathStatus.PASSED),
        sample_result(second, "chrome", PathStatus.PASSED),
        sample_result(second, "firefox", PathStatus.FAILED),
        sample_result(third, "chrome", PathStatus.BLOCKED),
        sample_result(third, "firefox", PathStatus.PASSED),
        sample_result(fifth, "chrome", PathStatus.NOT_RUN, steps=()),
    )
    requested = ("AC-001", "AC-002", "AC-003", "AC-004", "AC-005", "AC-006", "AC-007", "AC-008")
    not_covered = (NotCovered(criterion="AC-007", reason="Serve un controllo manuale."),)
    outcomes = criteria_outcomes(
        (first, second, third, fourth, fifth), results, not_covered, requested
    )
    assert [item.code for item in outcomes] == list(requested)
    assert statuses(outcomes) == {
        "AC-001": CriterionStatus.PASSED,
        "AC-002": CriterionStatus.FAILED,
        "AC-003": CriterionStatus.FAILED,
        "AC-004": CriterionStatus.BLOCKED,
        "AC-005": CriterionStatus.NOT_RUN,
        "AC-006": CriterionStatus.NOT_RUN,
        "AC-007": CriterionStatus.NOT_COVERED,
        "AC-008": CriterionStatus.NOT_RUN,
    }
    paths = {item.code: item.paths for item in outcomes}
    assert paths["AC-002"] == ("TP-001", "TP-002")
    assert paths["AC-005"] == ("TP-004",)
    assert paths["AC-006"] == ("TP-005",)
    assert (paths["AC-007"], paths["AC-008"]) == ((), ())
    assert run_summary(outcomes) == RunSummary(
        passed=1, failed=2, blocked=1, not_covered=1, not_run=3
    )
    assert run_summary(outcomes).to_snapshot() == {
        "passed": 1,
        "failed": 2,
        "blocked": 1,
        "not_covered": 1,
        "not_run": 3,
    }


def test_a_failure_wins_over_a_block_and_a_result_wins_over_not_covered():
    path = sample_path("TP-001", ("AC-001",))
    mixed = (
        sample_result(path, "chrome", PathStatus.BLOCKED),
        sample_result(path, "firefox", PathStatus.FAILED),
    )
    covered = (NotCovered(criterion="AC-001", reason="Il piano lo escludeva."),)
    [failed] = criteria_outcomes((path,), mixed, covered, ("AC-001",))
    assert failed.status is CriterionStatus.FAILED
    [passed] = criteria_outcomes((path,), (sample_result(path),), covered, ["AC-001"])
    assert passed.status is CriterionStatus.PASSED
    assert criteria_outcomes((), (), (), ()) == ()
    assert run_summary(()) == RunSummary()


def test_a_run_binds_its_results_to_the_planned_paths_and_counts_the_criteria():
    plan = sample_plan()
    run = sample_run(
        results=(
            sample_result(plan.paths[0], "chrome", PathStatus.PASSED),
            sample_result(plan.paths[0], "firefox", PathStatus.FAILED),
            sample_result(plan.paths[1], "chrome", PathStatus.PASSED, steps=step_results(2)),
        )
    )
    assert run.id == RUN_ID
    assert (run.plan_id, run.replan_ids) == (PLAN_ID, ())
    assert run.reference_snapshot() == plan.reference_snapshot()
    assert run.cost_microusd == 210_000
    assert statuses(run.criteria) == {
        "AC-001": CriterionStatus.FAILED,
        "AC-002": CriterionStatus.PASSED,
        "AC-003": CriterionStatus.NOT_COVERED,
    }
    assert run.summary == RunSummary(passed=1, failed=1, not_covered=1)


def test_a_run_keeps_the_stored_path_and_refuses_paths_outside_its_plans():
    plan = sample_plan()
    sent = replace(plan.paths[1], heading="Un titolo diverso")
    run = sample_run(results=(sample_result(sent, steps=step_results(2)),))
    assert run.results[0].path == plan.paths[1]
    with pytest.raises(ValueError, match="TP-009"):
        sample_run(results=(sample_result(sample_path("TP-009")),))
    longer = replace(plan.paths[1], steps=(opening(), checking(), checking()))
    with pytest.raises(ValueError, match="more steps"):
        sample_run(results=(sample_result(longer, steps=step_results(3)),))
    with pytest.raises(ValueError, match="AC-009"):
        sample_run(not_covered=(NotCovered(criterion="AC-009", reason="Fuori dal piano."),))
    with pytest.raises(ValueError):
        sample_run(plans=(), not_covered=())


def test_a_replan_adds_its_paths_criteria_and_cost_to_the_run():
    plan = sample_plan()
    replan = sample_plan(
        id=REPLAN_ID,
        criteria=("AC-001",),
        paths=(sample_path("TP-003", ("AC-001",), steps=(opening(), clicking())),),
        not_covered=(),
        replan_of=("TP-001",),
        cost_microusd=190_000,
    )
    run = sample_run(
        plans=(plan, replan),
        results=(
            sample_result(replan.paths[0], "chrome", steps=step_results(2)),
            sample_result(replan.paths[0], "firefox", steps=step_results(2)),
        ),
    )
    assert run.replan_ids == (REPLAN_ID,)
    assert run.cost_microusd == 400_000
    assert statuses(run.criteria) == {
        "AC-001": CriterionStatus.PASSED,
        "AC-002": CriterionStatus.NOT_RUN,
        "AC-003": CriterionStatus.NOT_COVERED,
    }
    assert run.criteria[0].paths == ("TP-003",)
    assert run.criteria[1].paths == ("TP-002",)


def test_a_run_has_the_exact_shape_of_the_tests_document():
    run = sample_run()
    snapshot = run.to_snapshot()
    assert list(snapshot) == [
        "id",
        "started_at",
        "finished_at",
        "recorded_at",
        "application",
        "browsers",
        "reference",
        "summary",
        "criteria",
        "not_covered",
        "results",
        "critiques",
        "reviewed_at",
        "cost_microusd",
    ]
    assert snapshot["started_at"] == "2026-09-29T11:00:00+00:00"
    assert snapshot["browsers"] == [
        {"name": "chrome", "version": "151.0.7922.76"},
        {"name": "firefox", "version": "156.0.1"},
    ]
    assert snapshot["criteria"][0] == {"code": "AC-001", "status": "PASSED", "paths": ["TP-001"]}
    assert snapshot["summary"] == {
        "passed": 1,
        "failed": 0,
        "blocked": 0,
        "not_covered": 1,
        "not_run": 1,
    }
    assert (snapshot["critiques"], snapshot["reviewed_at"], snapshot["cost_microusd"]) == (
        [],
        None,
        210_000,
    )
    reviewed = run.with_review(sample_review())
    document = reviewed.to_snapshot()
    assert document["critiques"] == [sample_critique().to_snapshot()]
    assert document["reviewed_at"] == "2026-09-29T12:00:00+00:00"
    assert document["cost_microusd"] == 360_000
    assert reviewed.total_cost_microusd == 360_000
    sources = ProjectStateSources(tests=(document,))
    assert not sources.is_empty
    assert sources.tests[0]["id"] == str(RUN_ID)


@pytest.mark.parametrize(
    "values",
    [
        {"replan_ids": (PLAN_ID,)},
        {"replan_ids": (REPLAN_ID, REPLAN_ID)},
        {"replan_ids": tuple(UUID(int=index) for index in range(1, MAX_REPLANS + 2))},
        {"finished_at": NOW},
        {"started_at": datetime(2026, 9, 29, 11, 0)},
        {"browsers": ()},
        {"browsers": (BrowserInfo(name="chrome", version="1"),) * 2},
        {"browsers": (BrowserInfo(name="chrome", version="1"),) * (MAX_BROWSERS + 1)},
        {"results": (sample_result(browser="firefox"),) * (MAX_RESULTS + 1)},
        {"browsers": (BrowserInfo(name="chrome", version="151"),)},
        {"summary": RunSummary()},
        {"criteria": ()},
        {"cost_microusd": -1},
        {"review": sample_review(run_id=REPLAN_ID)},
        {"alternative_code": "DES-2"},
        {
            "not_covered": (
                NotCovered(criterion="AC-003", reason="Uno."),
                NotCovered(criterion="AC-003", reason="Due."),
            )
        },
    ],
)
def test_every_rule_of_a_run_is_validated(values):
    with pytest.raises(ValueError):
        replace(sample_run(), **values)


def test_a_browser_has_a_known_name_and_a_version():
    assert BrowserInfo(name="firefox", version="156.0.1").to_snapshot() == {
        "name": "firefox",
        "version": "156.0.1",
    }
    for values in ({"name": "edge"}, {"version": ""}, {"version": "x" * 81}):
        with pytest.raises(ValueError):
            BrowserInfo(**{"name": "chrome", "version": "151", **values})


def test_a_criterion_outcome_names_path_codes_once():
    outcome = CriterionOutcome(code="AC-001", status=CriterionStatus.PASSED, paths=("TP-001",))
    assert domain.outcome_from_snapshot(outcome.to_snapshot()) == outcome
    for values in (
        {"paths": ("TP-001", "TP-001")},
        {"paths": ("AC-001",)},
        {"code": "TP-001"},
        {"status": "PASSED"},
    ):
        with pytest.raises(ValueError):
            CriterionOutcome(**{"code": "AC-001", "status": CriterionStatus.PASSED, **values})


def test_a_finding_and_a_critique_have_the_shape_of_the_tests_document():
    assert sample_finding().to_snapshot() == {
        "severity": "MEDIUM",
        "text": "Il totale non mostra la valuta che uso.",
        "about": {"criterion": "AC-001", "requirement": "REQ-001", "screen": "SCR-001"},
        "action": "Mostrare la valuta accanto al totale.",
    }
    critique = sample_critique(findings=(sample_finding(), sample_finding(criterion=None)))
    assert critique_from_snapshot(critique.to_snapshot()) == critique
    assert len(sample_critique(findings=(sample_finding(),) * MAX_FINDINGS).findings) == 6
    for values in (
        {"criterion": "REQ-001"},
        {"requirement": "AC-001"},
        {"screen": "SCR-1"},
        {"text": " spazio "},
        {"action": "x" * 301},
        {"severity": "HIGH"},
    ):
        with pytest.raises(ValueError):
            sample_finding(**values)
    for values in (
        {"findings": (sample_finding(),) * (MAX_FINDINGS + 1)},
        {"findings": [sample_finding()]},
        {"verdict": "FINE"},
        {"summary": ""},
        {"twin_name": ""},
        {"twin_id": str(TWIN_ONE)},
    ):
        with pytest.raises(ValueError):
            sample_critique(**values)


def test_a_review_has_the_shape_of_the_route_and_one_critique_per_twin():
    review = sample_review(
        critiques=(sample_critique(), sample_critique(TWIN_TWO, "Night Auditor Twin"))
    )
    snapshot = review.to_snapshot()
    assert list(snapshot) == ["id", "run_id", "reviewed_at", "locale", "critiques", "cost_microusd"]
    assert snapshot["run_id"] == str(RUN_ID)
    assert [item["twin_name"] for item in snapshot["critiques"]] == [
        "Receptionist Twin",
        "Night Auditor Twin",
    ]
    for values in (
        {"critiques": ()},
        {"critiques": (sample_critique(), sample_critique())},
        {"critiques": tuple(sample_critique(UUID(int=index)) for index in range(1, 10))},
        {"locale": "italiano"},
        {"cost_microusd": -1},
        {"generation_ids": ("x",)},
        {"reviewed_at": datetime(2026, 9, 29, 12, 0)},
    ):
        with pytest.raises(ValueError):
            sample_review(**values)


def test_an_unknown_plan_names_its_identifier():
    error = TestPlanUnknown(PLAN_ID)
    assert error.plan_id == PLAN_ID
    assert isinstance(error, LookupError)
