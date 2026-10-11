from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from orchestwin.knowledge.state import (
    APPLICATION_KINDS,
    BROWSER_NAMES,
    INTERACTIVE_ROLES,
    MAX_ADDRESS_LENGTH,
    MAX_BROWSER_VERSION_LENGTH,
    MAX_BROWSERS,
    MAX_CRITERIA_PER_PATH,
    MAX_EARLIER_PATHS,
    MAX_EXPECTED_TEXT_LENGTH,
    MAX_PAGE_TEXT_LENGTH,
    MAX_PATH_HEADING_LENGTH,
    MAX_REASON_LENGTH,
    MAX_RESULTS,
    MAX_SCREENSHOT_PATH_LENGTH,
    MAX_SNAPSHOT_ELEMENTS,
    MAX_SNAPSHOT_OPTIONS,
    MAX_STEP_DETAIL_LENGTH,
    MAX_STEP_VALUE_LENGTH,
    MAX_STEPS,
    MAX_TARGET_NAME_LENGTH,
    PATH_STATUSES,
    STEP_STATUSES,
    TEST_ACTIONS,
    TEST_EXPECTATIONS,
    TEST_KEYS,
    TEST_ROLES,
    review_is_stale,
)

from .common import (
    _control_free,
    _copy,
    _distinct,
    _findings_by_twin,
    _first_goal,
    _first_screen,
    _model_rule,
    _models,
    _single_line,
)
from .fields import _Fields
from .texts import COSTS
from .values import (
    CUT_MARK,
    DEFAULT_LOCALE,
    LOCALE_PATTERN,
    MAX_LOCALE_LENGTH,
    _Answer,
    _domain_refusal,
    _iso,
    _Refusal,
)

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject


LIST_LIMIT = 20
CRITERION_LENGTH = 20
MAX_RAW_TEXT_LENGTH = 100_000
MAX_REPLANS = 5
MAX_REQUESTED_CRITERIA = 200
MAX_PATH_SECONDS = 86_400
MAX_SNAPSHOT_URL_LENGTH = 2000
MAX_SNAPSHOT_TITLE_LENGTH = 300
PATH_CODE = re.compile(r"TP-[0-9]{3,6}")
CRITERION_CODE = re.compile(r"AC-[0-9]{3,6}")
CRITERION_REQUEST = re.compile(r"[A-Za-z0-9-]+")
ELEMENT_STATES = ("checked", "disabled")
FAILING_STATUSES = ("FAILED", "BLOCKED")
TARGET_ACTIONS = ("CLICK", "TYPE", "SELECT")
VALUE_ACTIONS = ("OPEN", "TYPE", "SELECT", "PRESS")
ACTION_ROLES = {
    "CLICK": (*INTERACTIVE_ROLES, "text", "image", "listitem", "cell", "heading"),
    "TYPE": ("textbox", "spinbutton", "combobox", "slider"),
    "SELECT": ("combobox",),
}
TARGET_EXPECTATIONS = ("ELEMENT_VISIBLE", "ELEMENT_ABSENT", "VALUE_IS")
TEXT_EXPECTATIONS = ("TEXT_VISIBLE", "TEXT_ABSENT", "VALUE_IS", "URL_CONTAINS", "TITLE_CONTAINS")
SUMMARY_KEYS = ("passed", "failed", "blocked", "not_covered", "not_run")
MANUAL_WORD = "manual"
HEADING_LENGTH = 60
CHECK_WORDS = 3
TITLE_WORD = "a"
TARGET_FIELDS = ("role", "name")
EXPECTATION_FIELDS = ("kind", "target", "text")
STEP_FIELDS = ("action", "target", "value", "expect")
PATH_FIELDS = ("code", "heading", "criteria", "steps")
EARLIER_FIELDS = (*PATH_FIELDS, "blocked_step", "detail", "snapshot")
APPLICATION_FIELDS = ("kind", "address")
SNAPSHOT_FIELDS = ("url", "title", "text", "hidden_text", "elements")
ELEMENT_FIELDS = ("index", "role", "name", "value", "state", "options")
PLAN_FIELDS = ("locale", "application", "snapshot", "criteria", "earlier")
RUN_FIELDS = (
    "plan_id",
    "replan_ids",
    "started_at",
    "finished_at",
    "application",
    "browsers",
    "results",
    "not_covered",
)
BROWSER_FIELDS = ("name", "version")
RESULT_FIELDS = ("path", "browser", "status", "seconds", "steps", "page_text")
STEP_RESULT_FIELDS = ("index", "status", "detail", "url", "title", "screenshot")
NOT_COVERED_FIELDS = ("criterion", "reason")
NOT_COVERED_REASON = {"it": "Richiede una verifica manuale", "en": "Needs a manual check"}
TEST_CRITIQUES = {
    "it": {
        "CONCERN": "Per «{goal}» i test sull'applicazione ({numbers}) mi lasciano qualche dubbio: "
        "ecco dove.",
        "FINE": "Per «{goal}» i test sull'applicazione ({numbers}) mi vanno bene.",
        "numbers": "{passed} criteri superati, {failed} falliti, {blocked} bloccati, "
        "{not_covered} non coperti, {not_run} non eseguiti",
        "concern": (
            "Il criterio {code} non mi assicura che l'applicazione faccia quello che mi serve.",
            "Correggere l'applicazione dove si ferma il percorso del criterio {code}.",
        ),
        "check": (
            "Il criterio {code} va provato anche su un telefono.",
            "Ripetere il percorso del criterio {code} su uno schermo piccolo.",
        ),
    },
    "en": {
        "CONCERN": "For “{goal}” the tests on the application ({numbers}) leave me some doubts: "
        "here is where.",
        "FINE": "For “{goal}” the tests on the application ({numbers}) work for me.",
        "numbers": "{passed} criteria passed, {failed} failed, {blocked} blocked, "
        "{not_covered} not covered, {not_run} not run",
        "concern": (
            "Criterion {code} does not assure me that the application does what I need.",
            "Fix the application where the path of criterion {code} stops.",
        ),
        "check": (
            "Criterion {code} should be tried on a phone too.",
            "Repeat the path of criterion {code} on a small screen.",
        ),
    },
}


class _AcceptanceRoutes:
    def _find_test_plan(self, project: FakeProject, identifier: str) -> dict[str, object]:
        plan = next((item for item in project.acceptance_plans if item["id"] == identifier), None)
        if plan is None:
            raise _Refusal(404, {"code": "TEST_PLAN_NOT_FOUND"})
        return plan

    def _find_test_run(self, project: FakeProject, identifier: str) -> dict[str, object]:
        record = next((item for item in project.acceptance_runs if item["id"] == identifier), None)
        if record is None:
            raise _Refusal(404, {"code": "TEST_RUN_NOT_FOUND"})
        return record

    def _test_run_payload(
        self, project: FakeProject, record: Mapping[str, object]
    ) -> dict[str, object]:
        payload = copy.deepcopy(dict(record))
        latest = next(
            (review for review in project.acceptance_reviews if review["run_id"] == record["id"]),
            None,
        )
        if latest is not None:
            payload["critiques"] = copy.deepcopy(latest["critiques"])
            payload["reviewed_at"] = latest["reviewed_at"]
            payload["cost_microusd"] = int(record["cost_microusd"]) + int(latest["cost_microusd"])
        return payload

    def _route_acceptance_tests(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        runs = project.acceptance_runs
        latest = runs[0] if runs else None
        reviewed = self._latest_reviewed_run(project)
        return _Answer(
            200,
            {
                "project_id": project.id,
                "reference": self._alignment_reference(project),
                "plan_available": self.hosted,
                "plans": len(project.acceptance_plans),
                "runs": len(runs),
                "latest_run": None if latest is None else self._test_run_payload(project, latest),
                "latest_run_stale": latest is not None
                and review_is_stale(latest["reference"], self._current_reference(project)),
                "latest_review": None
                if reviewed is None
                else {
                    "run_id": reviewed[0]["id"],
                    "finished_at": reviewed[0]["finished_at"],
                    "reviewed_at": reviewed[1]["reviewed_at"],
                    "critiques": copy.deepcopy(reviewed[1]["critiques"]),
                },
            },
        )

    def _route_plan_tests(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), PLAN_FIELDS)
        locale = fields.pattern(
            "locale",
            LOCALE_PATTERN,
            required=False,
            minimum=2,
            maximum=MAX_LOCALE_LENGTH,
            default=DEFAULT_LOCALE,
        )
        application = _application_of(fields)
        snapshot = _snapshot_of(fields)
        criteria = fields.texts(
            "criteria",
            minimum_items=1,
            maximum_items=MAX_REQUESTED_CRITERIA,
            item_minimum=1,
            item_maximum=CRITERION_LENGTH,
            item_pattern=CRITERION_REQUEST,
        )
        earlier = _earlier_of(fields)
        if criteria is not None:
            criteria = list(dict.fromkeys(code.upper() for code in criteria))
        _model_rule(fields, lambda: _distinct(item["code"] for item in earlier or ()))
        fields.check()
        body = {
            "locale": locale,
            "application": application,
            "snapshot": snapshot,
            "criteria": criteria,
            "earlier": earlier,
        }
        return self._later(call, "TEST_PLAN", body, lambda: self._planned_tests(call, body))

    def _next_path_number(self, project: FakeProject) -> int:
        numbers = [
            int(str(path["code"]).split("-", 1)[1])
            for plan in project.acceptance_plans
            for path in plan["paths"]
        ]
        return max(numbers, default=0) + 1

    def _planned_tests(self, call: _Call, body: Mapping[str, object]) -> _Answer:
        project = self._code_project(call)
        first = self._next_path_number(project) if body["earlier"] else 1
        reference = self._alignment_reference(project)
        if reference["requirements"] is None:
            raise _Refusal(409, {"code": "REQUIREMENTS_APPROVAL_REQUIRED"})
        if reference["design"] is None:
            raise _Refusal(409, {"code": "DESIGN_APPROVAL_REQUIRED"})
        if not self.hosted:
            raise _Refusal(503, {"code": "TEST_MODEL_NOT_CONFIGURED"})
        specification = project.specification
        if specification is None:
            raise RuntimeError("a plan needs the approved requirements")
        statements = {
            str(item["code"]): str(item["statement"])
            for item in specification["specification"]["acceptance_criteria"]
        }
        asked = body["criteria"]
        unknown = [code for code in dict.fromkeys(asked or ()) if code not in statements]
        if unknown:
            raise _Refusal(422, {"code": "ACCEPTANCE_CRITERION_UNKNOWN", "codes": unknown})
        earlier = body["earlier"] or []
        if earlier:
            named = {str(code) for path in earlier for code in path["criteria"]}
            wanted = [code for code in statements if code in named]
        else:
            wanted = [code for code in statements if asked is None or code in asked]
        self._record(project, "TEST_PLAN")
        plan = self._test_plan(
            body, reference, [(code, statements[code]) for code in wanted], first
        )
        project.acceptance_plans.insert(0, plan)
        project.acceptance_plan_requests.insert(0, _copy(dict(body)))
        return _Answer(201, {"status": "PLANNED", "plan": copy.deepcopy(plan)})

    def _test_plan(
        self,
        body: Mapping[str, object],
        reference: Mapping[str, object],
        wanted: Sequence[tuple[str, str]],
        first: int,
    ) -> dict[str, object]:
        earlier = body["earlier"] or []
        words = str(body["snapshot"]["title"]).split()
        title = words[0] if words else TITLE_WORD
        paths: list[dict[str, object]] = []
        not_covered = []
        for code, statement in wanted:
            if MANUAL_WORD in statement.casefold():
                not_covered.append({"criterion": code, "reason": NOT_COVERED_REASON[self.language]})
                continue
            steps = [
                _test_step("OPEN", value="/"),
                _test_step(
                    "CHECK",
                    expect=_test_expectation(
                        "TEXT_VISIBLE", " ".join(statement.split()[:CHECK_WORDS])
                    ),
                ),
            ]
            if earlier:
                steps.append(_test_step("CHECK", expect=_test_expectation("TITLE_CONTAINS", title)))
            paths.append(
                {
                    "code": f"TP-{first + len(paths):03d}",
                    "heading": statement[:HEADING_LENGTH].rstrip(),
                    "criteria": [code],
                    "steps": steps,
                }
            )
        requirements = reference["requirements"]
        design = reference["design"]
        return {
            "id": self._new_id(),
            "created_at": _iso(self._now()),
            "locale": body["locale"],
            "reference": {
                "requirements_version_number": requirements["version_number"],
                "design_version_number": design["version_number"],
                "alternative_code": design["alternative_code"],
            },
            "application": _normal_application(body["application"]),
            "criteria": [code for code, _ in wanted],
            "replan_of": [str(path["code"]) for path in earlier],
            "paths": paths,
            "not_covered": not_covered,
            "cost_microusd": COSTS["TEST_PLAN"],
        }

    def _route_test_plans(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        return _Answer(200, {"items": copy.deepcopy(project.acceptance_plans[:LIST_LIMIT])})

    def _route_test_plan(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        return _Answer(200, copy.deepcopy(self._find_test_plan(project, call.params["plan_id"])))

    def _route_record_test_run(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), RUN_FIELDS)
        plan_id = fields.identifier("plan_id")
        replan_ids = fields.identifiers("replan_ids", maximum_items=MAX_REPLANS)
        started_at = fields.moment("started_at")
        finished_at = fields.moment("finished_at")
        application = _application_of(fields)
        browsers = _models(
            fields,
            "browsers",
            BROWSER_FIELDS,
            _browser_of,
            minimum_items=1,
            maximum_items=MAX_BROWSERS,
        )
        results = _models(fields, "results", RESULT_FIELDS, _result_of, maximum_items=MAX_RESULTS)
        not_covered = _models(
            fields,
            "not_covered",
            NOT_COVERED_FIELDS,
            _not_covered_of,
            maximum_items=MAX_REQUESTED_CRITERIA,
        )
        _model_rule(
            fields,
            lambda: _run_rule(
                plan_id, replan_ids, started_at, finished_at, browsers, results, not_covered
            ),
        )
        fields.check()
        project = self._code_project(call)
        plans = [
            self._find_test_plan(project, identifier) for identifier in (str(plan_id), *replan_ids)
        ]
        bound = _bound_results(plans, results, not_covered)
        uncovered = [
            {"criterion": item["criterion"], "reason": _single_line(item["reason"])}
            for item in not_covered
        ]
        outcomes = _criteria_outcomes(plans, bound, uncovered)
        record: dict[str, object] = {
            "id": self._new_id(),
            "started_at": _iso(started_at) if started_at is not None else None,
            "finished_at": _iso(finished_at) if finished_at is not None else None,
            "recorded_at": _iso(self._now()),
            "application": _normal_application(application or {}),
            "browsers": [
                {"name": item["name"], "version": _single_line(item["version"])}
                for item in browsers
            ],
            "reference": copy.deepcopy(plans[0]["reference"]),
            "summary": _run_summary(outcomes),
            "criteria": outcomes,
            "not_covered": uncovered,
            "results": bound,
            "critiques": [],
            "reviewed_at": None,
            "cost_microusd": sum(int(plan["cost_microusd"]) for plan in plans),
        }
        project.acceptance_runs.insert(0, record)
        return _Answer(201, {"status": "RECORDED", "run": self._test_run_payload(project, record)})

    def _route_test_runs(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        return _Answer(
            200,
            {
                "items": [
                    self._test_run_payload(project, record)
                    for record in project.acceptance_runs[:LIST_LIMIT]
                ]
            },
        )

    def _route_test_run(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        record = self._find_test_run(project, call.params["run_id"])
        return _Answer(200, self._test_run_payload(project, record))

    def _route_review_test_run(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("locale", "again"))
        locale = fields.pattern(
            "locale",
            LOCALE_PATTERN,
            required=False,
            minimum=2,
            maximum=MAX_LOCALE_LENGTH,
            default=DEFAULT_LOCALE,
        )
        again = fields.flag("again")
        fields.check()
        return self._later(
            call,
            "TEST_REVIEW",
            {"locale": locale, "again": again},
            lambda: self._reviewed_test_run(call, str(locale), again),
        )

    def _reviewed_test_run(self, call: _Call, locale: str, again: bool) -> _Answer:
        project = self._code_project(call)
        record = self._find_test_run(project, call.params["run_id"])
        if not again and any(
            review["run_id"] == record["id"] for review in project.acceptance_reviews
        ):
            raise _Refusal(409, {"code": "TEST_REVIEW_EXISTS"})
        reference = self._alignment_reference(project)
        if reference["requirements"] is None:
            raise _Refusal(409, {"code": "REQUIREMENTS_APPROVAL_REQUIRED"})
        if reference["design"] is None:
            raise _Refusal(409, {"code": "DESIGN_APPROVAL_REQUIRED"})
        twins = self._approved_twins(project)
        if not twins:
            raise _Refusal(409, {"code": "USER_MODELING_APPROVAL_REQUIRED"})
        if not self.hosted:
            raise _Refusal(503, {"code": "TEST_MODEL_NOT_CONFIGURED"})
        charged = 0
        for _ in twins:
            self._record(project, "TEST_REVIEW")
            charged += COSTS["TEST_REVIEW"]
        review = self._stored_test_review(project, record, twins, locale, charged)
        return _Answer(201, {"status": "REVIEWED", "review": copy.deepcopy(review)})

    def _stored_test_review(
        self,
        project: FakeProject,
        record: Mapping[str, object],
        twins: Sequence[Mapping[str, object]],
        locale: str,
        charged: int,
    ) -> dict[str, object]:
        earlier = self._earlier_test_findings(project, record)
        review = {
            "id": self._new_id(),
            "run_id": record["id"],
            "reviewed_at": _iso(self._now()),
            "locale": locale,
            "critiques": self._test_critiques(project, record, twins),
            "cost_microusd": charged,
        }
        project.acceptance_reviews.insert(0, review)
        project.critique_contexts.insert(
            0,
            {
                "kind": "TEST_RUN",
                "review_id": review["id"],
                "run_id": record["id"],
                "twins": [
                    {
                        "twin_id": twin["twin_id"],
                        "earlier_findings": earlier.get(twin["twin_id"], []),
                    }
                    for twin in twins
                ],
            },
        )
        return review

    def _latest_test_review(self, project: FakeProject, run_id: object) -> dict[str, object] | None:
        return next(
            (review for review in project.acceptance_reviews if review["run_id"] == run_id), None
        )

    def _latest_reviewed_run(
        self, project: FakeProject
    ) -> tuple[dict[str, object], dict[str, object]] | None:
        for record in project.acceptance_runs:
            review = self._latest_test_review(project, record["id"])
            if review is not None:
                return record, review
        return None

    def _earlier_test_findings(
        self, project: FakeProject, record: Mapping[str, object]
    ) -> dict[str, list[str]]:
        runs = project.acceptance_runs
        index = next(
            (place for place, item in enumerate(runs) if item["id"] == record["id"]), len(runs)
        )
        for older in runs[index + 1 :]:
            review = self._latest_test_review(project, older["id"])
            if review is not None:
                return _findings_by_twin(review["critiques"])
        return {}

    def _test_critiques(
        self,
        project: FakeProject,
        record: Mapping[str, object],
        twins: Sequence[Mapping[str, object]],
    ) -> list[dict[str, object]]:
        texts = TEST_CRITIQUES[self.language]
        criteria = record["criteria"]
        chosen = next(
            (item for item in criteria if item["status"] in FAILING_STATUSES),
            criteria[0] if criteria else None,
        )
        code = None if chosen is None else str(chosen["code"])
        about = {
            "criterion": code,
            "requirement": self._criterion_requirement(project, code),
            "screen": None if project.design is None else _first_screen(project.design["package"]),
        }
        numbers = texts["numbers"].format(**record["summary"])
        critiques = []
        for position, twin in enumerate(twins):
            findings = []
            if code is not None and position < 2:
                severity, key = ("MEDIUM", "concern") if position == 0 else ("LOW", "check")
                text, action = texts[key]
                findings.append(
                    {
                        "severity": severity,
                        "text": text.format(code=code),
                        "about": dict(about),
                        "action": action.format(code=code),
                    }
                )
            verdict = "CONCERN" if position == 0 else "FINE"
            critiques.append(
                {
                    "twin_id": twin["twin_id"],
                    "twin_name": twin["profile"]["name"],
                    "verdict": verdict,
                    "summary": texts[verdict].format(goal=_first_goal(twin), numbers=numbers),
                    "findings": findings,
                }
            )
        return critiques

    def _criterion_requirement(self, project: FakeProject, code: str | None) -> str | None:
        specification = project.specification
        if specification is None or code is None:
            return None
        content = specification["specification"]
        criterion = next(
            (item for item in content["acceptance_criteria"] if item["code"] == code), None
        )
        if criterion is None or not criterion["requirement_ids"]:
            return None
        codes = {str(item["id"]): str(item["code"]) for item in content["requirements"]}
        return codes.get(str(criterion["requirement_ids"][0]))

    def _route_test_run_reviews(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        record = self._find_test_run(project, call.params["run_id"])
        return _Answer(
            200,
            {
                "items": [
                    copy.deepcopy(review)
                    for review in project.acceptance_reviews
                    if review["run_id"] == record["id"]
                ]
            },
        )


def _test_step(
    action: str,
    *,
    target: Mapping[str, object] | None = None,
    value: str | None = None,
    expect: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {"action": action, "target": target, "value": value, "expect": expect}


def _test_expectation(kind: str, text: str) -> dict[str, object]:
    return {"kind": kind, "target": None, "text": text}


def _application_of(fields: _Fields) -> dict[str, object] | None:
    child = fields.child("application", APPLICATION_FIELDS)
    if child is None:
        return None
    application = {
        "kind": child.choice("kind", APPLICATION_KINDS),
        "address": child.text("address", minimum=1, maximum=MAX_ADDRESS_LENGTH),
    }
    _model_rule(child, lambda: _normal_application(application))
    fields.adopt(child)
    return application


def _snapshot_of(fields: _Fields, *, required: bool = True) -> dict[str, object] | None:
    child = fields.child("snapshot", SNAPSHOT_FIELDS, required=required, nullable=not required)
    if child is None:
        return None
    snapshot = {
        "url": child.text("url", maximum=MAX_RAW_TEXT_LENGTH),
        "title": child.text("title", maximum=MAX_RAW_TEXT_LENGTH),
        "text": child.text("text", maximum=MAX_RAW_TEXT_LENGTH),
        "hidden_text": child.text(
            "hidden_text", required=False, maximum=MAX_RAW_TEXT_LENGTH, default=""
        ),
        "elements": _models(
            child, "elements", ELEMENT_FIELDS, _element_of, maximum_items=MAX_SNAPSHOT_ELEMENTS
        ),
    }
    _model_rule(child, lambda: _distinct(item["index"] for item in snapshot["elements"]))
    fields.adopt(child)
    return snapshot


def _element_of(fields: _Fields) -> dict[str, object]:
    element = {
        "index": fields.integer("index", minimum=0),
        "role": fields.choice("role", TEST_ROLES, literal=True),
        "name": fields.text("name", maximum=MAX_RAW_TEXT_LENGTH),
        "value": fields.text("value", required=False, nullable=True, maximum=MAX_RAW_TEXT_LENGTH),
        "state": fields.choice(
            "state", ELEMENT_STATES, required=False, nullable=True, literal=True
        ),
        "options": fields.texts(
            "options", maximum_items=MAX_SNAPSHOT_OPTIONS, item_maximum=MAX_RAW_TEXT_LENGTH
        ),
    }
    _model_rule(fields, lambda: _element_rule(element))
    return element


def _target_of(fields: _Fields) -> dict[str, object] | None:
    child = fields.child("target", TARGET_FIELDS, required=False, nullable=True)
    if child is None:
        return None
    target = {
        "role": child.choice("role", TEST_ROLES, required=False, nullable=True, literal=True),
        "name": child.text("name", minimum=1, maximum=MAX_TARGET_NAME_LENGTH),
    }
    _model_rule(child, lambda: _normal_target(target))
    fields.adopt(child)
    return target


def _expectation_of(fields: _Fields) -> dict[str, object] | None:
    child = fields.child("expect", EXPECTATION_FIELDS, required=False, nullable=True)
    if child is None:
        return None
    expectation = {
        "kind": child.choice("kind", TEST_EXPECTATIONS),
        "target": _target_of(child),
        "text": child.text("text", required=False, nullable=True, maximum=MAX_EXPECTED_TEXT_LENGTH),
    }
    _model_rule(child, lambda: _normal_expectation(expectation))
    fields.adopt(child)
    return expectation


def _step_of(fields: _Fields) -> dict[str, object]:
    step = {
        "action": fields.choice("action", TEST_ACTIONS),
        "target": _target_of(fields),
        "value": fields.text("value", required=False, nullable=True, maximum=MAX_STEP_VALUE_LENGTH),
        "expect": _expectation_of(fields),
    }
    _model_rule(fields, lambda: _normal_step(step))
    return step


def _path_fields(fields: _Fields) -> dict[str, object]:
    return {
        "code": fields.pattern("code", PATH_CODE),
        "heading": fields.text("heading", minimum=1, maximum=MAX_PATH_HEADING_LENGTH),
        "criteria": fields.texts(
            "criteria",
            required=True,
            nullable=False,
            minimum_items=1,
            maximum_items=MAX_CRITERIA_PER_PATH,
            item_pattern=CRITERION_CODE,
        ),
        "steps": _models(
            fields, "steps", STEP_FIELDS, _step_of, minimum_items=1, maximum_items=MAX_STEPS
        ),
    }


def _path_of(fields: _Fields) -> dict[str, object] | None:
    child = fields.child("path", PATH_FIELDS)
    if child is None:
        return None
    path = _path_fields(child)
    _model_rule(child, lambda: _normal_path(path))
    fields.adopt(child)
    return path


def _earlier_of(fields: _Fields) -> list[dict[str, object]] | None:
    items = fields.children(
        "earlier", EARLIER_FIELDS, required=False, nullable=True, maximum_items=MAX_EARLIER_PATHS
    )
    if items is None:
        return None
    earlier = []
    for item in items:
        entry = {
            **_path_fields(item),
            "blocked_step": item.integer("blocked_step", minimum=1, maximum=MAX_STEPS),
            "detail": item.text(
                "detail", required=False, nullable=True, maximum=MAX_RAW_TEXT_LENGTH
            ),
            "snapshot": _snapshot_of(item, required=False),
        }
        _model_rule(item, lambda entry=entry: _earlier_rule(entry))
        earlier.append(entry)
        fields.adopt(item)
    return earlier


def _browser_of(fields: _Fields) -> dict[str, object]:
    browser = {
        "name": fields.choice("name", BROWSER_NAMES, literal=True),
        "version": fields.text("version", minimum=1, maximum=MAX_BROWSER_VERSION_LENGTH),
    }
    _model_rule(fields, lambda: _single_line(browser["version"]))
    return browser


def _result_of(fields: _Fields) -> dict[str, object]:
    result = {
        "path": _path_of(fields),
        "browser": fields.choice("browser", BROWSER_NAMES, literal=True),
        "status": fields.choice("status", PATH_STATUSES),
        "seconds": fields.number("seconds", minimum=0, maximum=MAX_PATH_SECONDS),
        "steps": _models(
            fields,
            "steps",
            STEP_RESULT_FIELDS,
            _step_result_of,
            required=False,
            maximum_items=MAX_STEPS,
        ),
        "page_text": fields.text(
            "page_text", required=False, nullable=True, maximum=MAX_RAW_TEXT_LENGTH
        ),
    }
    _model_rule(fields, lambda: _result_rule(result))
    return result


def _step_result_of(fields: _Fields) -> dict[str, object]:
    result = {
        "index": fields.integer("index", minimum=1, maximum=MAX_STEPS),
        "status": fields.choice("status", STEP_STATUSES),
        "detail": fields.text("detail", required=False, nullable=True, maximum=MAX_RAW_TEXT_LENGTH),
        "url": fields.text("url", required=False, nullable=True, maximum=MAX_RAW_TEXT_LENGTH),
        "title": fields.text("title", required=False, nullable=True, maximum=MAX_RAW_TEXT_LENGTH),
        "screenshot": fields.text(
            "screenshot", required=False, nullable=True, maximum=MAX_SCREENSHOT_PATH_LENGTH
        ),
    }
    _model_rule(fields, lambda: result["screenshot"] is None or _screenshot(result["screenshot"]))
    return result


def _not_covered_of(fields: _Fields) -> dict[str, object]:
    item = {
        "criterion": fields.pattern("criterion", CRITERION_CODE),
        "reason": fields.text("reason", minimum=1, maximum=MAX_REASON_LENGTH),
    }
    _model_rule(fields, lambda: _single_line(item["reason"]))
    return item


def _element_rule(element: Mapping[str, object]) -> None:
    if element["options"] is not None and element["role"] != "combobox":
        raise ValueError("only a combobox lists its options")


def _normal_application(application: Mapping[str, object]) -> dict[str, object]:
    kind = application["kind"]
    address = str(application["address"]).strip()
    if not address or not _control_free(address):
        raise ValueError("the address of the application must be visible")
    if kind == "URL":
        if any(character.isspace() for character in address):
            raise ValueError("an address has no spaces")
        parts = urlsplit(address)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            raise ValueError("an address is an http or https address")
    elif (
        "\\" in address
        or ":" in address
        or (address != "." and any(part in ("", ".", "..") for part in address.split("/")))
    ):
        raise ValueError("a static folder is relative to the project and stays inside it")
    return {"kind": kind, "address": address}


def _normal_target(target: Mapping[str, object]) -> dict[str, object]:
    return {"role": target["role"], "name": _single_line(target["name"])}


def _normal_expectation(expectation: Mapping[str, object]) -> dict[str, object]:
    kind = expectation["kind"]
    target = None if expectation["target"] is None else _normal_target(expectation["target"])
    text = None if expectation["text"] is None else _single_line(expectation["text"])
    if (target is not None) != (kind in TARGET_EXPECTATIONS):
        raise ValueError("the expectation names a target exactly when its kind needs one")
    if (text is not None) != (kind in TEXT_EXPECTATIONS):
        raise ValueError("the expectation gives a text exactly when its kind needs one")
    return {"kind": kind, "target": target, "text": text}


def _normal_step(step: Mapping[str, object]) -> dict[str, object]:
    action = step["action"]
    target = None if step["target"] is None else _normal_target(step["target"])
    value = None if step["value"] is None else _single_line(step["value"])
    expect = None if step["expect"] is None else _normal_expectation(step["expect"])
    if (target is not None) != (action in TARGET_ACTIONS):
        raise ValueError("the step names a target exactly when its action needs one")
    if (value is not None) != (action in VALUE_ACTIONS):
        raise ValueError("the step gives a value exactly when its action needs one")
    if action == "CHECK" and expect is None:
        raise ValueError("a CHECK step needs an expectation")
    if action == "OPEN":
        parts = urlsplit(str(value))
        scheme = parts.scheme.lower()
        if scheme and (scheme not in ("http", "https") or not parts.netloc):
            raise ValueError("an OPEN step opens a path of the application or an http address")
    if action == "PRESS" and value not in TEST_KEYS:
        raise ValueError("a PRESS step presses one of the test keys")
    roles = ACTION_ROLES.get(str(action))
    if roles is not None and target is not None and target["role"] not in (None, *roles):
        raise ValueError("the step cannot act on an element of that role")
    return {"action": action, "target": target, "value": value, "expect": expect}


def _normal_path(path: Mapping[str, object]) -> dict[str, object]:
    criteria = [str(code) for code in path["criteria"]]
    _distinct(criteria)
    steps = [_normal_step(step) for step in path["steps"]]
    if steps[0]["action"] != "OPEN":
        raise ValueError("the first step of a path is OPEN")
    return {
        "code": path["code"],
        "heading": _single_line(path["heading"]),
        "criteria": criteria,
        "steps": steps,
    }


def _earlier_rule(entry: Mapping[str, object]) -> None:
    path = _normal_path(entry)
    if int(entry["blocked_step"]) > len(path["steps"]):
        raise ValueError("the blocked step is a step of the path")


def _result_rule(result: Mapping[str, object]) -> None:
    indexes = [step["index"] for step in result["steps"]]
    if indexes != list(range(1, len(indexes) + 1)):
        raise ValueError("the steps of a result are numbered from 1 in order")
    if len(indexes) > len(result["path"]["steps"]):
        raise ValueError("a result holds at most the steps of its path")


def _run_rule(
    plan_id: str | None,
    replan_ids: Sequence[str],
    started_at: datetime | None,
    finished_at: datetime | None,
    browsers: Sequence[Mapping[str, object]],
    results: Sequence[Mapping[str, object]],
    not_covered: Sequence[Mapping[str, object]],
) -> None:
    _distinct(replan_ids)
    if plan_id in replan_ids:
        raise ValueError("the replans are other plans than the plan of the run")
    if started_at is not None and finished_at is not None and finished_at < started_at:
        raise ValueError("a run ends after it starts")
    names = [item["name"] for item in browsers]
    _distinct(names)
    if any(item["browser"] not in names for item in results):
        raise ValueError("every result names a browser of the run")
    _distinct(item["criterion"] for item in not_covered)


def _screenshot(value: object) -> str:
    path = str(value)
    if not path or not _control_free(path) or "\\" in path or ":" in path:
        raise ValueError("the screenshot is a relative path with / as separator")
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise ValueError("the screenshot stays inside the run folder")
    return path


def _cut_text(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    kept = "".join(
        character
        for character in str(value)
        if character.isspace() or (ord(character) >= 32 and ord(character) != 127)
    )
    text = " ".join(kept.split())
    if len(text) <= maximum:
        return text
    return text[: maximum - len(CUT_MARK)].rstrip() + CUT_MARK


def _bound_results(
    plans: Sequence[Mapping[str, object]],
    results: Sequence[Mapping[str, object]],
    not_covered: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    paths = [path for plan in plans for path in plan["paths"]]
    requested = {str(code) for plan in plans for code in plan["criteria"]}
    bound = []
    for position, result in enumerate(results):
        code = str(result["path"]["code"])
        candidates = [path for path in paths if path["code"] == code]
        if not candidates:
            raise _domain_refusal(
                f"result {position} names the path {code}, "
                "which is not in the plan or in its replans"
            )
        wanted = _normal_path(result["path"])
        planned = next((path for path in candidates if path == wanted), candidates[-1])
        if len(result["steps"]) > len(planned["steps"]):
            raise _domain_refusal(f"result {position} holds more steps than its path")
        bound.append(
            {
                "path": copy.deepcopy(planned),
                "browser": result["browser"],
                "status": result["status"],
                "seconds": float(result["seconds"]),
                "steps": [
                    {
                        "index": step["index"],
                        "status": step["status"],
                        "detail": _cut_text(step["detail"], MAX_STEP_DETAIL_LENGTH),
                        "url": _cut_text(step["url"], MAX_SNAPSHOT_URL_LENGTH),
                        "title": _cut_text(step["title"], MAX_SNAPSHOT_TITLE_LENGTH),
                        "screenshot": step["screenshot"],
                    }
                    for step in result["steps"]
                ],
                "page_text": _cut_text(result["page_text"], MAX_PAGE_TEXT_LENGTH),
            }
        )
    unknown = [str(item["criterion"]) for item in not_covered if item["criterion"] not in requested]
    if unknown:
        raise _domain_refusal(f"the not covered criteria {', '.join(unknown)} are not in the plans")
    return bound


def _criteria_outcomes(
    plans: Sequence[Mapping[str, object]],
    results: Sequence[Mapping[str, object]],
    not_covered: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    requested = list(dict.fromkeys(str(code) for plan in plans for code in plan["criteria"]))
    paths = [path for plan in plans for path in plan["paths"]]
    uncovered = {str(item["criterion"]) for item in not_covered}
    outcomes = []
    for code in requested:
        named = [result for result in results if code in result["path"]["criteria"]]
        statuses = {result["status"] for result in named}
        if "FAILED" in statuses:
            status = "FAILED"
        elif "BLOCKED" in statuses:
            status = "BLOCKED"
        elif named and statuses == {"PASSED"}:
            status = "PASSED"
        elif not named and code in uncovered:
            status = "NOT_COVERED"
        else:
            status = "NOT_RUN"
        if named:
            codes = [str(result["path"]["code"]) for result in named]
        elif status == "NOT_RUN":
            codes = [str(path["code"]) for path in paths if code in path["criteria"]]
        else:
            codes = []
        outcomes.append({"code": code, "status": status, "paths": list(dict.fromkeys(codes))})
    return outcomes


def _run_summary(outcomes: Sequence[Mapping[str, object]]) -> dict[str, int]:
    summary = dict.fromkeys(SUMMARY_KEYS, 0)
    for item in outcomes:
        summary[str(item["status"]).lower()] += 1
    return summary
