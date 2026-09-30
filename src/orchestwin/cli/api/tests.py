from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from orchestwin.cli.client import payload
from orchestwin.cli.errors import ApiFailure
from orchestwin.cli.jobs import reply_body

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient

PLANNED: Final = "PLANNED"
RECORDED: Final = "RECORDED"
REVIEWED: Final = "REVIEWED"
URL: Final = "URL"
STATIC: Final = "STATIC"
APPLICATION_KINDS: Final = (URL, STATIC)
OPEN: Final = "OPEN"
CLICK: Final = "CLICK"
TYPE: Final = "TYPE"
SELECT: Final = "SELECT"
PRESS: Final = "PRESS"
CHECK: Final = "CHECK"
TEST_ACTIONS: Final = (OPEN, CLICK, TYPE, SELECT, PRESS, CHECK)
TARGET_ACTIONS: Final = (CLICK, TYPE, SELECT)
TEXT_VISIBLE: Final = "TEXT_VISIBLE"
TEXT_ABSENT: Final = "TEXT_ABSENT"
ELEMENT_VISIBLE: Final = "ELEMENT_VISIBLE"
ELEMENT_ABSENT: Final = "ELEMENT_ABSENT"
VALUE_IS: Final = "VALUE_IS"
URL_CONTAINS: Final = "URL_CONTAINS"
TITLE_CONTAINS: Final = "TITLE_CONTAINS"
TEST_EXPECTATIONS: Final = (
    TEXT_VISIBLE,
    TEXT_ABSENT,
    ELEMENT_VISIBLE,
    ELEMENT_ABSENT,
    VALUE_IS,
    URL_CONTAINS,
    TITLE_CONTAINS,
)
PASSED: Final = "PASSED"
FAILED: Final = "FAILED"
BLOCKED: Final = "BLOCKED"
NOT_RUN: Final = "NOT_RUN"
NOT_COVERED: Final = "NOT_COVERED"
PATH_STATUSES: Final = (PASSED, FAILED, BLOCKED, NOT_RUN)
CRITERION_STATUSES: Final = (PASSED, FAILED, BLOCKED, NOT_COVERED, NOT_RUN)
FAILING_STATUSES: Final = frozenset({FAILED, BLOCKED})
DONE: Final = "DONE"
SKIPPED: Final = "SKIPPED"
STEP_STATUSES: Final = (DONE, FAILED, BLOCKED, SKIPPED)
FINE: Final = "FINE"
CONCERN: Final = "CONCERN"
DRIFT: Final = "DRIFT"
CRITIQUE_VERDICTS: Final = (FINE, CONCERN, DRIFT)
SEVERITIES: Final = ("LOW", "MEDIUM", "HIGH")
BROWSER_NAMES: Final = ("chrome", "firefox")
PLAN_OPERATION: Final = "TEST_PLAN"
REVIEW_OPERATION: Final = "TEST_REVIEW"
NO_TEST_MODEL: Final = "TEST_MODEL_NOT_CONFIGURED"
PLAN_NOT_FOUND: Final = "TEST_PLAN_NOT_FOUND"
RUN_NOT_FOUND: Final = "TEST_RUN_NOT_FOUND"
REVIEW_EXISTS: Final = "TEST_REVIEW_EXISTS"
CRITERION_UNKNOWN: Final = "ACCEPTANCE_CRITERION_UNKNOWN"
REQUIREMENTS_APPROVAL_REQUIRED: Final = "REQUIREMENTS_APPROVAL_REQUIRED"
DESIGN_APPROVAL_REQUIRED: Final = "DESIGN_APPROVAL_REQUIRED"
USER_MODELING_APPROVAL_REQUIRED: Final = "USER_MODELING_APPROVAL_REQUIRED"
INVALID_REQUEST: Final = "invalid_request"
MAX_PATHS: Final = 20
MAX_STEPS: Final = 12
MAX_EARLIER_PATHS: Final = 5
MAX_BROWSERS: Final = 3
MAX_RESULTS: Final = MAX_PATHS * MAX_BROWSERS
MAX_STEP_DETAIL_LENGTH: Final = 300
MAX_PAGE_TEXT_LENGTH: Final = 1500
MAX_SCREENSHOT_PATH_LENGTH: Final = 200
MAX_ADDRESS_LENGTH: Final = 500
MAX_BROWSER_VERSION_LENGTH: Final = 80
MAX_REASON_LENGTH: Final = 300
MAX_FOLDER_TEST_RUNS: Final = 20
MAX_REPLANS: Final = 5
SUMMARY_KEYS: Final = ("passed", "failed", "blocked", "not_covered", "not_run")
MISSING_ROUTE: Final = frozenset({404, 405})


@dataclass(frozen=True, slots=True)
class AcceptanceSummary:
    runs: int
    latest_id: str | None
    finished_at: str | None
    summary: Mapping[str, int]

    def document(self) -> dict[str, object] | None:
        if self.runs <= 0:
            return None
        latest = (
            None
            if self.latest_id is None and self.finished_at is None
            else {
                "id": self.latest_id,
                "finished_at": self.finished_at,
                "summary": dict(self.summary),
            }
        )
        return {"runs": self.runs, "latest": latest}


def overview_path(project_id: str) -> str:
    return f"/projects/{project_id}/acceptance-tests"


def plans_path(project_id: str) -> str:
    return f"/projects/{project_id}/test-plans"


def plan_path(project_id: str, plan_id: str) -> str:
    return f"{plans_path(project_id)}/{plan_id}"


def runs_path(project_id: str) -> str:
    return f"/projects/{project_id}/test-runs"


def run_path(project_id: str, run_id: str) -> str:
    return f"{runs_path(project_id)}/{run_id}"


def review_path(project_id: str, run_id: str) -> str:
    return f"{run_path(project_id, run_id)}/reviews"


def review_body(locale: str, again: bool = False) -> dict[str, object]:
    return {"locale": locale, "again": bool(again)}


def overview(client: StudioClient, project_id: str) -> Mapping[str, object]:
    return _mapping_of(client.get(overview_path(project_id)))


def plan(client: StudioClient, project_id: str, body: Mapping[str, object]) -> tuple[int, object]:
    reply = client.request("POST", plans_path(project_id), body=dict(body))
    return reply.status, reply_body(reply)


def plans(client: StudioClient, project_id: str) -> list[Mapping[str, object]]:
    return _items(client.get(plans_path(project_id)))


def plan_of(client: StudioClient, project_id: str, plan_id: str) -> Mapping[str, object] | None:
    document = client.get(plan_path(project_id, plan_id), optional=True)
    return document if isinstance(document, Mapping) else None


def record(
    client: StudioClient, project_id: str, body: Mapping[str, object]
) -> tuple[int, Mapping[str, object]]:
    reply = client.request("POST", runs_path(project_id), body=dict(body))
    return reply.status, _mapping_of(payload(reply), reply.status)


def runs(client: StudioClient, project_id: str) -> list[Mapping[str, object]]:
    return _items(client.get(runs_path(project_id)))


def run_of(client: StudioClient, project_id: str, run_id: str) -> Mapping[str, object] | None:
    document = client.get(run_path(project_id, run_id), optional=True)
    return document if isinstance(document, Mapping) else None


def reviews(client: StudioClient, project_id: str, run_id: str) -> list[Mapping[str, object]]:
    return _items(client.get(review_path(project_id, run_id)))


def summary(client: StudioClient, project_id: str) -> AcceptanceSummary | None:
    try:
        document = overview(client, project_id)
    except ApiFailure as failure:
        if failure.http_status in MISSING_ROUTE or failure.http_status >= 500:
            return None
        raise
    return summary_of(document)


def summary_of(document: Mapping[str, object]) -> AcceptanceSummary:
    latest = latest_run(document)
    count = document.get("runs")
    runs_count = count if _integer(count) and count >= 0 else 0
    if latest is not None:
        runs_count = max(runs_count, 1)
    return run_summary_of(latest, runs_count)


def run_summary_of(run: Mapping[str, object] | None, count: int) -> AcceptanceSummary:
    if run is None:
        return AcceptanceSummary(count, None, None, dict.fromkeys(SUMMARY_KEYS, 0))
    identifier = run.get("id")
    finished = run.get("finished_at")
    return AcceptanceSummary(
        runs=count,
        latest_id=identifier if isinstance(identifier, str) else None,
        finished_at=finished if isinstance(finished, str) else None,
        summary=numbers(run),
    )


def numbers(run: Mapping[str, object]) -> dict[str, int]:
    found = run.get("summary")
    found = found if isinstance(found, Mapping) else {}
    counted: dict[str, int] = {}
    for key in SUMMARY_KEYS:
        value = found.get(key)
        counted[key] = value if _integer(value) and value >= 0 else 0
    return counted


def plan_available(document: Mapping[str, object]) -> bool:
    return document.get("plan_available") is True


def reference_number(document: Mapping[str, object], stage: str) -> int | None:
    parts = document.get("reference")
    value = parts.get(stage) if isinstance(parts, Mapping) else None
    number = value.get("version_number") if isinstance(value, Mapping) else None
    return number if _integer(number) else None


def latest_run(document: Mapping[str, object]) -> Mapping[str, object] | None:
    value = document.get("latest_run")
    return value if isinstance(value, Mapping) else None


def criteria_of(run: Mapping[str, object]) -> list[Mapping[str, object]]:
    return mappings(run.get("criteria"))


def results_of(run: Mapping[str, object]) -> list[Mapping[str, object]]:
    return mappings(run.get("results"))


def critiques_of(document: Mapping[str, object]) -> list[Mapping[str, object]]:
    return mappings(document.get("critiques"))


def failing(run: Mapping[str, object]) -> bool:
    return any(item.get("status") in FAILING_STATUSES for item in criteria_of(run))


def code_of(document: object) -> str | None:
    if not isinstance(document, Mapping):
        return None
    detail = document.get("detail")
    if isinstance(detail, Mapping) and isinstance(detail.get("code"), str) and detail["code"]:
        return str(detail["code"])
    if isinstance(detail, str) and detail:
        return detail
    job_failure = document.get("failure")
    found = job_failure.get("code") if isinstance(job_failure, Mapping) else None
    return found if isinstance(found, str) and found else None


def failure(status: int, document: object) -> ApiFailure:
    detail = document.get("detail") if isinstance(document, Mapping) else document
    values: dict[str, object] = {}
    codes = detail.get("codes") if isinstance(detail, Mapping) else None
    if isinstance(codes, list):
        values["codes"] = ", ".join(str(item) for item in codes)
    return ApiFailure(
        code_of(document) or "API_FAILURE", http_status=status, detail=detail, values=values
    )


def mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def texts(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, str)]


def ordered(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _items(document: object) -> list[Mapping[str, object]]:
    items = document.get("items") if isinstance(document, Mapping) else None
    return mappings(items)


def _mapping_of(document: object, status: int = 200) -> Mapping[str, object]:
    if not isinstance(document, Mapping):
        raise ApiFailure("API_FAILURE", http_status=status)
    return document


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
