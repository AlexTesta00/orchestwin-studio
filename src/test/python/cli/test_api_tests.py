from __future__ import annotations

from pathlib import Path

import pytest

from orchestwin.cli.api import tests as tests_api
from orchestwin.cli.client import StudioClient
from orchestwin.cli.errors import ApiFailure
from orchestwin.knowledge import state

from .support.terminal import PROJECT_ID, command_context, store_session, terminal
from .support.transports import API, ScriptedTransport

BASE = f"{API}/projects/{PROJECT_ID}"
PLAN_ID = "00000000-0000-4000-8000-00000000f001"
RUN_ID = "00000000-0000-4000-8000-00000000f101"
SUMMARY = {"passed": 2, "failed": 1, "blocked": 0, "not_covered": 1, "not_run": 0}
RUN = {
    "id": RUN_ID,
    "finished_at": "2026-09-29T10:01:12+00:00",
    "summary": SUMMARY,
    "criteria": [
        {"code": "AC-001", "status": "PASSED", "paths": ["TP-001"]},
        {"code": "AC-002", "status": "FAILED", "paths": ["TP-002"]},
    ],
}
OVERVIEW = {
    "project_id": PROJECT_ID,
    "reference": {
        "requirements": {"version_id": "r", "version_number": 2, "content_hash": "hr"},
        "design": {
            "version_id": "d",
            "version_number": 4,
            "content_hash": "hd",
            "alternative_code": "DES-002",
        },
    },
    "plan_available": True,
    "plans": 2,
    "runs": 3,
    "latest_run": RUN,
}


def client_for(tmp_path: Path, transport: ScriptedTransport) -> StudioClient:
    store_session(tmp_path)
    bundle = terminal(tmp_path, transport=transport)
    return command_context(bundle.environment).client()


def test_the_names_and_limits_follow_the_knowledge_folder() -> None:
    assert tests_api.TEST_ACTIONS == state.TEST_ACTIONS
    assert tests_api.TEST_EXPECTATIONS == state.TEST_EXPECTATIONS
    assert tests_api.PATH_STATUSES == state.PATH_STATUSES
    assert tests_api.CRITERION_STATUSES == state.CRITERION_STATUSES
    assert tests_api.STEP_STATUSES == state.STEP_STATUSES
    assert tests_api.BROWSER_NAMES == state.BROWSER_NAMES
    assert tests_api.APPLICATION_KINDS == state.APPLICATION_KINDS
    assert tests_api.CRITIQUE_VERDICTS == state.CRITIQUE_VERDICTS
    assert tests_api.SEVERITIES == state.SEVERITIES
    assert tests_api.MAX_PATHS == state.MAX_PATHS
    assert tests_api.MAX_STEPS == state.MAX_STEPS
    assert tests_api.MAX_EARLIER_PATHS == state.MAX_EARLIER_PATHS
    assert tests_api.MAX_BROWSERS == state.MAX_BROWSERS
    assert tests_api.MAX_RESULTS == state.MAX_RESULTS
    assert tests_api.MAX_STEP_DETAIL_LENGTH == state.MAX_STEP_DETAIL_LENGTH
    assert tests_api.MAX_PAGE_TEXT_LENGTH == state.MAX_PAGE_TEXT_LENGTH
    assert tests_api.MAX_SCREENSHOT_PATH_LENGTH == state.MAX_SCREENSHOT_PATH_LENGTH
    assert tests_api.MAX_ADDRESS_LENGTH == state.MAX_ADDRESS_LENGTH
    assert tests_api.MAX_BROWSER_VERSION_LENGTH == state.MAX_BROWSER_VERSION_LENGTH
    assert tests_api.MAX_REASON_LENGTH == state.MAX_REASON_LENGTH
    assert tests_api.MAX_FOLDER_TEST_RUNS == state.MAX_FOLDER_TEST_RUNS
    assert tests_api.MAX_REPLANS == 5


def test_the_paths_and_the_review_body() -> None:
    assert tests_api.overview_path(PROJECT_ID) == f"/projects/{PROJECT_ID}/acceptance-tests"
    assert tests_api.plans_path(PROJECT_ID) == f"/projects/{PROJECT_ID}/test-plans"
    assert tests_api.plan_path(PROJECT_ID, PLAN_ID).endswith(f"/test-plans/{PLAN_ID}")
    assert tests_api.runs_path(PROJECT_ID) == f"/projects/{PROJECT_ID}/test-runs"
    assert tests_api.run_path(PROJECT_ID, RUN_ID).endswith(f"/test-runs/{RUN_ID}")
    assert tests_api.review_path(PROJECT_ID, RUN_ID).endswith(f"/test-runs/{RUN_ID}/reviews")
    assert tests_api.review_body("it-IT") == {"locale": "it-IT", "again": False}
    assert tests_api.review_body("en-US", True) == {"locale": "en-US", "again": True}


def test_the_documents_of_the_tests_are_read(tmp_path: Path) -> None:
    review = {"id": "review-1", "run_id": RUN_ID, "critiques": []}
    transport = (
        ScriptedTransport()
        .expect("GET", f"{BASE}/acceptance-tests", body=OVERVIEW)
        .expect("GET", f"{BASE}/test-plans", body={"items": [{"id": PLAN_ID}, "noise"]})
        .expect("GET", f"{BASE}/test-plans/{PLAN_ID}", body={"id": PLAN_ID})
        .expect(
            "GET",
            f"{BASE}/test-plans/{RUN_ID}",
            status=404,
            body={"detail": {"code": "TEST_PLAN_NOT_FOUND"}},
        )
        .expect("GET", f"{BASE}/test-runs", body={"items": [RUN]})
        .expect("GET", f"{BASE}/test-runs/{RUN_ID}", body=RUN)
        .expect(
            "GET",
            f"{BASE}/test-runs/{PLAN_ID}",
            status=404,
            body={"detail": {"code": "TEST_RUN_NOT_FOUND"}},
        )
        .expect("GET", f"{BASE}/test-runs/{RUN_ID}/reviews", body={"items": [review]})
    )
    client = client_for(tmp_path, transport)

    overview = tests_api.overview(client, PROJECT_ID)

    assert tests_api.plan_available(overview) is True
    assert tests_api.reference_number(overview, "requirements") == 2
    assert tests_api.reference_number(overview, "design") == 4
    assert tests_api.latest_run(overview) == RUN
    assert tests_api.plans(client, PROJECT_ID) == [{"id": PLAN_ID}]
    assert tests_api.plan_of(client, PROJECT_ID, PLAN_ID) == {"id": PLAN_ID}
    assert tests_api.plan_of(client, PROJECT_ID, RUN_ID) is None
    assert tests_api.runs(client, PROJECT_ID) == [RUN]
    assert tests_api.run_of(client, PROJECT_ID, RUN_ID) == RUN
    assert tests_api.run_of(client, PROJECT_ID, PLAN_ID) is None
    assert tests_api.reviews(client, PROJECT_ID, RUN_ID) == [review]
    transport.assert_done()


def test_a_plan_request_answers_the_status_and_the_body_without_raising(tmp_path: Path) -> None:
    body = {"locale": "it-IT", "application": {"kind": "URL", "address": "http://x.test/"}}
    refused = {"detail": {"code": "TEST_MODEL_NOT_CONFIGURED"}}
    transport = (
        ScriptedTransport()
        .expect("POST", f"{BASE}/test-plans", status=503, body=refused)
        .expect("POST", f"{BASE}/test-plans", status=201, body={"status": "PLANNED"})
    )
    client = client_for(tmp_path, transport)

    assert tests_api.plan(client, PROJECT_ID, body) == (503, refused)
    assert tests_api.plan(client, PROJECT_ID, body) == (201, {"status": "PLANNED"})
    assert transport.sent[0].json() == body
    assert transport.sent[0].header("prefer") is None


def test_recording_a_run_answers_the_document_and_raises_on_a_refusal(tmp_path: Path) -> None:
    recorded = {"status": "RECORDED", "run": RUN}
    domain = {
        "detail": {
            "code": "invalid_request",
            "errors": [{"loc": ["body"], "type": "value_error", "msg": "result 0"}],
        }
    }
    transport = (
        ScriptedTransport()
        .expect("POST", f"{BASE}/test-runs", status=201, body=recorded)
        .expect(
            "POST",
            f"{BASE}/test-runs",
            status=404,
            body={"detail": {"code": "TEST_PLAN_NOT_FOUND"}},
        )
        .expect("POST", f"{BASE}/test-runs", status=422, body=domain)
    )
    client = client_for(tmp_path, transport)

    assert tests_api.record(client, PROJECT_ID, {"plan_id": PLAN_ID}) == (201, recorded)
    with pytest.raises(ApiFailure) as missing:
        tests_api.record(client, PROJECT_ID, {"plan_id": PLAN_ID})
    with pytest.raises(ApiFailure) as invalid:
        tests_api.record(client, PROJECT_ID, {"plan_id": PLAN_ID})

    assert (missing.value.code, missing.value.http_status) == ("TEST_PLAN_NOT_FOUND", 404)
    assert (invalid.value.code, invalid.value.status) == (tests_api.INVALID_REQUEST, 1)


def test_the_summary_for_the_status_reads_the_latest_run(tmp_path: Path) -> None:
    empty = {**OVERVIEW, "runs": 0, "latest_run": None}
    transport = (
        ScriptedTransport()
        .expect("GET", f"{BASE}/acceptance-tests", body=OVERVIEW)
        .expect("GET", f"{BASE}/acceptance-tests", body=empty)
        .expect("GET", f"{BASE}/acceptance-tests", status=404, body={"detail": "Not Found"})
        .expect("GET", f"{BASE}/acceptance-tests", status=405, body={"detail": "Not Allowed"})
        .expect(
            "GET",
            f"{BASE}/acceptance-tests",
            status=500,
            body={"detail": "Internal Server Error"},
        )
        .expect(
            "GET",
            f"{BASE}/acceptance-tests",
            status=403,
            body={"detail": {"code": "FORBIDDEN"}},
        )
    )
    client = client_for(tmp_path, transport)

    found = tests_api.summary(client, PROJECT_ID)
    nothing = tests_api.summary(client, PROJECT_ID)
    missing = [tests_api.summary(client, PROJECT_ID) for _ in range(3)]
    with pytest.raises(ApiFailure) as refused:
        tests_api.summary(client, PROJECT_ID)

    assert found == tests_api.AcceptanceSummary(3, RUN_ID, RUN["finished_at"], SUMMARY)
    assert found is not None
    assert found.document() == {
        "runs": 3,
        "latest": {"id": RUN_ID, "finished_at": RUN["finished_at"], "summary": SUMMARY},
    }
    assert nothing is not None
    assert (nothing.runs, nothing.document()) == (0, None)
    assert missing == [None, None, None]
    assert refused.value.code == "FORBIDDEN"


def test_a_summary_without_a_readable_run_gives_the_count_alone() -> None:
    unknown = tests_api.run_summary_of(None, 2)
    broken = tests_api.run_summary_of({"summary": {"passed": -1, "failed": True}}, 1)

    assert unknown.document() == {"runs": 2, "latest": None}
    assert broken.summary == dict.fromkeys(tests_api.SUMMARY_KEYS, 0)
    assert tests_api.summary_of({"runs": "many", "latest_run": RUN}).runs == 1


@pytest.mark.parametrize(
    ("status", "body", "code", "values"),
    [
        (
            422,
            {"detail": {"code": "ACCEPTANCE_CRITERION_UNKNOWN", "codes": ["AC-009", "AC-010"]}},
            "ACCEPTANCE_CRITERION_UNKNOWN",
            {"codes": "AC-009, AC-010"},
        ),
        (503, {"detail": {"code": "TEST_MODEL_NOT_CONFIGURED"}}, "TEST_MODEL_NOT_CONFIGURED", {}),
        (422, {"detail": "invalid_request", "errors": []}, "invalid_request", {}),
        (502, {"job_id": "j", "failure": {"code": "TIMEOUT"}}, "TIMEOUT", {}),
        (500, "Internal Server Error", "API_FAILURE", {}),
    ],
)
def test_a_refusal_becomes_a_failure_with_its_code(
    status: int, body: object, code: str, values: dict[str, object]
) -> None:
    failure = tests_api.failure(status, body)

    assert (failure.code, failure.http_status) == (code, status)
    assert dict(failure.values) == {"code": code, "http_status": status, **values}


def test_the_latest_review_may_come_from_an_older_run() -> None:
    review = {
        "run_id": RUN_ID,
        "finished_at": "2026-09-29T10:01:12+00:00",
        "reviewed_at": "2026-09-29T10:03:00+00:00",
        "critiques": [],
    }

    assert tests_api.latest_review({**OVERVIEW, "latest_review": review}) == review
    assert tests_api.latest_review({**OVERVIEW, "latest_review": None}) is None
    assert tests_api.latest_review(OVERVIEW) is None
    assert tests_api.latest_review({"latest_review": {**review, "run_id": ""}}) is None
    assert tests_api.latest_review({"latest_review": "noise"}) is None


def test_a_run_fails_when_a_criterion_failed_or_was_blocked() -> None:
    blocked = {"criteria": [{"code": "AC-001", "status": "BLOCKED"}]}
    fine = {"criteria": [{"code": "AC-001", "status": "PASSED"}, {"status": "NOT_COVERED"}]}

    assert tests_api.failing(RUN) is True
    assert tests_api.failing(blocked) is True
    assert tests_api.failing(fine) is False
    assert tests_api.failing({"criteria": "none"}) is False
    assert tests_api.numbers(RUN) == SUMMARY
    assert tests_api.ordered(["b", "a", "b"]) == ["b", "a"]
    assert tests_api.texts(["a", 1, None, "b"]) == ["a", "b"]
    assert tests_api.mappings("text") == []
