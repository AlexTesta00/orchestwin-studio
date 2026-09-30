from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import ClassVar
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from orchestwin.api import acceptance_tests as acceptance_api
from orchestwin.api.acceptance_tests import (
    AcceptanceTestApplication,
    TestPlanRequest,
    TestPlanStatus,
    TestReviewRequest,
    TestReviewStatus,
    create_acceptance_test_router,
)
from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.generation_jobs import GenerationOperation
from orchestwin.api.generation_requests import PREFERENCE_APPLIED, RESPOND_ASYNC, request_key
from orchestwin.api.services import ApplicationRuntime
from orchestwin.artifacts.design_gate import design_artifact_reference
from orchestwin.config import ApplicationSettings
from orchestwin.knowledge.state import MAX_SNAPSHOT_HIDDEN_TEXT_LENGTH
from orchestwin.models.change_review import LEARNED_INSTRUCTION
from orchestwin.models.proposal_evidence import ProposalEvidenceError
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.test_planning import NOT_PLANNED_REASON, PLAN_PURPOSE, PLAN_TASK
from orchestwin.models.test_review import (
    REVIEW_INSTRUCTION,
    REVIEW_PURPOSE,
    REVIEW_TASK,
    run_material,
)
from orchestwin.projects.acceptance_tests import TestPlanUnknown, path_number
from orchestwin.projects.persistence.acceptance_tests import AcceptanceTestWriteStatus
from orchestwin.projects.requirements_gate import requirements_artifact_reference
from orchestwin.projects.requirements_primitives import snapshot_content_hash
from orchestwin.twins.user_modeling_gate import user_modeling_artifact_reference
from orchestwin.workflow.gates import HumanGateType
from src.test.python.api.test_code_changes_api import (
    FakeGenerator,
    FakeSession,
    MemoryEvidence,
    MemoryLearning,
    account,
    approved,
    first_twin,
    learned_by,
    nothing,
    second_twin,
)
from src.test.python.artifacts import design_fixtures
from src.test.python.models.test_test_planning import BRIEF, requirements_with_criteria
from src.test.python.projects.test_acceptance_tests import (
    PLAN_ID,
    REPLAN_ID,
    RUN_ID,
    page,
    sample_critique,
    sample_finding,
    sample_path,
    sample_plan,
    sample_review,
    sample_run,
)

PREFIX = "/api/v1"
OWNER = design_fixtures.OWNER_ID
PROJECT = design_fixtures.PROJECT_ID
STRANGER = UUID("00000000-0000-4000-8000-00000000ffff")
UNKNOWN = UUID("00000000-0000-4000-8000-00000000eeee")
PROJECT_PATH = f"{PREFIX}/projects/{PROJECT}"
OVERVIEW = f"{PROJECT_PATH}/acceptance-tests"
PLANS = f"{PROJECT_PATH}/test-plans"
RUNS = f"{PROJECT_PATH}/test-runs"
JOBS = f"{PROJECT_PATH}/generation-jobs"
ASYNC = {"Prefer": RESPOND_ASYNC}
REVIEW = {"locale": "it-IT", "again": False}
ITALIAN_HEADING = "Calcolo della mancia con il pulsante"
ENGLISH_HEADING = "The waiter computes the tip with the button of the form"
ITALIAN = "Il calcolo funziona, ma non vedo la valuta che uso per ogni conto."
ENGLISH = "The tip works but the total does not show the currency that I need."
MANUAL = "Serve un controllo manuale della ricevuta."
PLAN_KEYS = [
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
RUN_KEYS = [
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


def plan_body(**values):
    body = {
        "locale": "it-IT",
        "application": {"kind": "STATIC", "address": "dist"},
        "snapshot": page().to_snapshot(),
        "criteria": None,
        "earlier": None,
    }
    body.update(values)
    return body


def target_answer(name="Calcola", role="button"):
    return {"name": name, "role": role}


def step_answer(action="OPEN", *, expect=None, target=None, value=None):
    return {"action": action, "expect": expect, "target": target, "value": value}


def path_answer(criteria=("AC-001",), heading=ITALIAN_HEADING, steps=None):
    return {
        "about_criteria": list(criteria),
        "heading": heading,
        "steps": steps
        if steps is not None
        else [
            step_answer(value="/"),
            step_answer("TYPE", target=target_answer("Importo del conto", "textbox"), value="42"),
            step_answer(
                "CLICK",
                target=target_answer(),
                expect={"kind": "TEXT_VISIBLE", "target": None, "text": "Mancia"},
            ),
        ],
    }


def plan_answer(paths=None, not_covered=None):
    return {
        "not_covered": not_covered
        if not_covered is not None
        else [{"criterion": "AC-003", "reason": MANUAL}],
        "paths": paths if paths is not None else [path_answer(), path_answer(("AC-002",))],
    }


def invalid_plan_answer():
    return plan_answer(paths=[path_answer(steps=[step_answer("CLICK", target=target_answer())])])


def finding_answer(**values):
    answer = {
        "about_criterion": "AC-001",
        "about_requirement": "REQ-001",
        "about_screen": "SCR-001",
        "problem": "Il totale non mostra la valuta.",
        "severity": "MEDIUM",
        "suggestion": "Mostrare la valuta accanto al totale.",
    }
    answer.update(values)
    return answer


def critique_answer(summary=ITALIAN, **values):
    answer = {"assessment": "CONCERN", "comment": summary, "findings": [finding_answer()]}
    answer.update(values)
    return answer


def fine_answer():
    return critique_answer(
        "Il calcolo va bene per il mio turno di notte.", assessment="FINE", findings=[]
    )


def result_body(path, browser="chrome", status="PASSED", steps=None, **values):
    count = len(path.steps) if steps is None else steps
    body = {
        "path": path.to_snapshot(),
        "browser": browser,
        "status": status,
        "seconds": 4.2,
        "steps": [
            {
                "index": index,
                "status": "DONE",
                "detail": None,
                "url": "http://127.0.0.1:8123/index.html",
                "title": "Mance",
                "screenshot": f"{path.code}/{browser}/{index:02d}.png",
            }
            for index in range(1, count + 1)
        ],
        "page_text": "Mancia 6,30 euro Totale 48,30 euro",
    }
    body.update(values)
    return body


def run_body(plan=None, results=None, **values):
    chosen = plan if plan is not None else sample_plan()
    body = {
        "plan_id": str(chosen.id),
        "replan_ids": [],
        "started_at": "2026-09-29T12:00:00+02:00",
        "finished_at": "2026-09-29T12:02:00+02:00",
        "application": {"kind": "STATIC", "address": "dist"},
        "browsers": [
            {"name": "chrome", "version": "151.0.7922.76"},
            {"name": "firefox", "version": "156.0.1"},
        ],
        "results": results
        if results is not None
        else [
            result_body(chosen.paths[0]),
            result_body(chosen.paths[0], "firefox", "FAILED"),
            result_body(chosen.paths[1]),
        ],
        "not_covered": [item.to_snapshot() for item in chosen.not_covered],
    }
    body.update(values)
    return body


class MemoryStore:
    def __init__(self):
        self.projects = {PROJECT}
        self.plans = []
        self.runs = []
        self.reviews = []


class MemoryTests:
    store: ClassVar[MemoryStore] = MemoryStore()

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    def _owned(self, project_id):
        return self.owner_user_id == OWNER and project_id in self.store.projects

    async def project_exists(self, project_id):
        return self._owned(project_id)

    async def create_plan(self, plan):
        if plan.owner_user_id != self.owner_user_id or not self._owned(plan.project_id):
            return AcceptanceTestWriteStatus.PROJECT_NOT_FOUND
        self.store.plans.append(plan)
        return AcceptanceTestWriteStatus.RECORDED

    async def plans(self, project_id, *, limit=20):
        if not self._owned(project_id):
            return ()
        items = [item for item in reversed(self.store.plans) if item.project_id == project_id]
        return tuple(items if limit is None else items[:limit])

    async def plan(self, project_id, plan_id):
        return next(
            (item for item in await self.plans(project_id, limit=None) if item.id == plan_id),
            None,
        )

    async def next_path_number(self, project_id):
        plans = await self.plans(project_id, limit=None)
        return 1 + max((path_number(path.code) for plan in plans for path in plan.paths), default=0)

    async def create_run(self, run):
        if run.owner_user_id != self.owner_user_id or not self._owned(run.project_id):
            return AcceptanceTestWriteStatus.PROJECT_NOT_FOUND
        known = {item.id for item in await self.plans(run.project_id, limit=None)}
        for plan_id in (run.plan_id, *run.replan_ids):
            if plan_id not in known:
                raise TestPlanUnknown(plan_id)
        self.store.runs.append(run)
        return AcceptanceTestWriteStatus.RECORDED

    def _latest(self, run_id):
        reviews = [item for item in self.store.reviews if item.run_id == run_id]
        return reviews[-1] if reviews else None

    async def runs(self, project_id, *, limit=20):
        if not self._owned(project_id):
            return ()
        items = [
            item.with_review(self._latest(item.id))
            for item in reversed(self.store.runs)
            if item.project_id == project_id
        ]
        return tuple(items if limit is None else items[:limit])

    async def run(self, project_id, run_id):
        return next(
            (item for item in await self.runs(project_id, limit=None) if item.id == run_id), None
        )

    async def latest_reviewed_run(self, project_id, *, before=None):
        runs = list(await self.runs(project_id, limit=None))
        if before is not None:
            place = next(index for index, item in enumerate(runs) if item.id == before.id)
            runs = runs[place + 1 :]
        return next((item for item in runs if item.review is not None), None)

    async def reviews(self, run_id):
        return tuple(reversed([item for item in self.store.reviews if item.run_id == run_id]))

    async def latest_review(self, run_id):
        return self._latest(run_id)

    async def create_review(self, review):
        if review.owner_user_id != self.owner_user_id or not self._owned(review.project_id):
            return AcceptanceTestWriteStatus.PROJECT_NOT_FOUND
        if not any(item.id == review.run_id for item in self.store.runs):
            return AcceptanceTestWriteStatus.RUN_NOT_FOUND
        self.store.reviews.append(review)
        return AcceptanceTestWriteStatus.RECORDED

    async def counts(self, project_id):
        return (
            len(await self.plans(project_id, limit=None)),
            len(await self.runs(project_id, limit=None)),
        )


class CostedEvidence(MemoryEvidence):
    def __init__(self, costs):
        super().__init__()
        self.costs = costs

    async def get_owned(self, *, owner_user_id, project_id, generation_id):
        assert (owner_user_id, project_id) == (OWNER, PROJECT)
        cost = self.costs[self.generations.index(generation_id)]
        if cost is None:
            raise ProposalEvidenceError("PROPOSAL_EVIDENCE_HASH_MISMATCH")
        return {
            "observations": [
                {"kind": "HTTP_REQUEST", "payload": {"cost_microusd": 999}},
                {"kind": "PROVIDER_RESULT", "payload": {"success": {"usage": cost}}},
            ]
        }


class Studio:
    def __init__(
        self,
        monkeypatch,
        *outcomes,
        model=True,
        evidence=None,
        requirements=True,
        design=True,
        modeling=True,
        twins=None,
        learned=None,
    ):
        MemoryTests.store = MemoryStore()
        monkeypatch.setattr(acceptance_api, "SqlAlchemyAcceptanceTestRepository", MemoryTests)
        monkeypatch.setattr(MemoryLearning, "learned", dict(learned or {}))
        monkeypatch.setattr(acceptance_api, "SqlAlchemyTwinLearningRepository", MemoryLearning)
        self.generator = FakeGenerator(*outcomes) if model else None
        self.evidence = (MemoryEvidence() if evidence is None else evidence) if model else None
        self.requirements = requirements_with_criteria()
        self.design = design_fixtures.design_version()
        self.twins = (first_twin(), second_twin()) if twins is None else twins
        self.modeling = SimpleNamespace(
            id=UUID("00000000-0000-4000-8000-000000000b10"),
            project_id=PROJECT,
            version_number=1,
            content_hash="f" * 64,
            snapshot=SimpleNamespace(twin_versions=self.twins),
        )
        gates = {
            "requirements": approved(
                self.requirements,
                HumanGateType.REQUIREMENTS,
                requirements_artifact_reference(self.requirements),
            )
            if requirements
            else None,
            "design": approved(
                self.design, HumanGateType.DESIGN, design_artifact_reference(self.design)
            )
            if design
            else None,
            "modeling": approved(
                self.modeling,
                HumanGateType.USER_MODELING,
                user_modeling_artifact_reference(self.modeling),
            )
            if modeling
            else None,
        }

        def returning(value):
            async def answer(**scope):
                assert set(scope) == {"owner_user_id", "project_id"}
                return value

            return answer

        real = None
        if model:
            real = SimpleNamespace(
                user_modeling=SimpleNamespace(
                    proposal_port=SimpleNamespace(generator=self.generator)
                ),
                check_readiness=nothing,
            )
        self.runtime = ApplicationRuntime(
            identity_service=object(),
            database_runtime=SimpleNamespace(session_factory=FakeSession, dispose=nothing),
            project_service=SimpleNamespace(current_brief=returning(SimpleNamespace(brief=BRIEF))),
            requirements_query_service=SimpleNamespace(current=returning(self.requirements)),
            requirements_gate_service=SimpleNamespace(
                current_gate=returning(gates["requirements"])
            ),
            design_query_service=SimpleNamespace(current=returning(self.design)),
            design_gate_service=SimpleNamespace(current_gate=returning(gates["design"])),
            user_modeling_services=SimpleNamespace(
                commands=SimpleNamespace(snapshot_context_is_current=nothing),
                revisions=SimpleNamespace(),
                queries=SimpleNamespace(current_snapshot=returning(self.modeling)),
                gates=SimpleNamespace(current_gate=returning(gates["modeling"])),
            ),
            real_model_runtime=real,
            proposal_evidence_store=self.evidence,
        )
        self.app = create_app(
            ApplicationSettings(api_prefix=PREFIX, debug=False, _env_file=None),
            runtime=self.runtime,
            auth_settings=AuthApiSettings(_env_file=None),
        )
        self.app.dependency_overrides[current_user_dependency] = account

    def client(self):
        return TestClient(self.app, raise_server_exceptions=False)

    @property
    def calls(self):
        return [] if self.generator is None else self.generator.calls

    def application(self):
        return AcceptanceTestApplication(self.runtime)


def stored_plan(plan=None):
    chosen = plan if plan is not None else sample_plan()
    MemoryTests.store.plans.append(chosen)
    return chosen


def stored_run():
    plan = stored_plan()
    run = sample_run((plan,))
    MemoryTests.store.runs.append(run)
    return run


def job_of(studio, client, started):
    assert started.status_code == 202, started.text
    assert started.headers[PREFERENCE_APPLIED] == RESPOND_ASYNC
    job_id = started.json()["job_id"]
    client.portal.call(studio.app.state.generation_jobs.wait, UUID(job_id))
    return client.get(f"{JOBS}/{job_id}").json()


def test_router_registers_the_routes():
    router = create_acceptance_test_router()
    methods = sorted(
        (route.path.removeprefix("/projects/{project_id}"), *sorted(route.methods))
        for route in router.routes
    )
    assert methods == [
        ("/acceptance-tests", "GET"),
        ("/test-plans", "GET"),
        ("/test-plans", "POST"),
        ("/test-plans/{plan_id}", "GET"),
        ("/test-runs", "GET"),
        ("/test-runs", "POST"),
        ("/test-runs/{run_id}", "GET"),
        ("/test-runs/{run_id}/reviews", "GET"),
        ("/test-runs/{run_id}/reviews", "POST"),
    ]
    assert all(route.path.startswith("/projects/{project_id}/") for route in router.routes)


def test_a_plan_asks_the_model_once_and_stores_the_plan(monkeypatch):
    studio = Studio(monkeypatch, plan_answer())
    with studio.client() as client:
        answer = client.post(PLANS, json=plan_body())
        listed = client.get(PLANS).json()
        plan_id = answer.json()["plan"]["id"]
        single = client.get(f"{PLANS}/{plan_id}")
        missing = client.get(f"{PLANS}/{UNKNOWN}")
    assert answer.status_code == 201, answer.text
    body = answer.json()
    assert body["status"] == "PLANNED"
    plan = body["plan"]
    assert list(plan) == PLAN_KEYS
    assert (plan["locale"], plan["criteria"], plan["replan_of"]) == (
        "it-IT",
        ["AC-001", "AC-002", "AC-003"],
        [],
    )
    assert plan["reference"] == {
        "requirements_version_number": 1,
        "design_version_number": 1,
        "alternative_code": "DES-001",
    }
    assert plan["application"] == {"kind": "STATIC", "address": "dist"}
    assert [(item["code"], item["criteria"]) for item in plan["paths"]] == [
        ("TP-001", ["AC-001"]),
        ("TP-002", ["AC-002"]),
    ]
    assert plan["paths"][0]["steps"][2] == {
        "action": "CLICK",
        "target": {"role": "button", "name": "Calcola"},
        "value": None,
        "expect": {"kind": "TEXT_VISIBLE", "target": None, "text": "Mancia"},
    }
    assert plan["not_covered"] == [{"criterion": "AC-003", "reason": MANUAL}]
    assert plan["cost_microusd"] == 0
    assert datetime.fromisoformat(plan["created_at"]).utcoffset().total_seconds() == 0
    [stored] = MemoryTests.store.plans
    assert stored.to_snapshot() == plan
    assert stored.snapshot_summary.to_snapshot() == {
        "url": "http://127.0.0.1:8123/index.html",
        "title": "Mance",
        "elements": 5,
        "text_length": len(page().text),
    }
    assert listed == {"items": [plan]}
    assert single.json() == plan
    assert missing.status_code == 404
    assert missing.json() == {"detail": {"code": "TEST_PLAN_NOT_FOUND"}}
    [call] = studio.calls
    assert call["task"] == PLAN_TASK
    assert call["retry_schema_errors"] is False
    context = call["context"]
    assert context["purpose"] == PLAN_PURPOSE
    assert context["locale"] == "it-IT"
    assert context["project_brief"]["name"] == "Calcolo mance"
    assert [item["code"] for item in context["acceptance_criteria"]] == [
        "AC-001",
        "AC-002",
        "AC-003",
    ]
    assert context["application"] == {
        "kind": "STATIC",
        "address": "dist",
        "snapshot": page().to_snapshot(),
    }
    assert context["earlier"] == []
    assert context["design"]["alternative_code"] == "DES-001"
    evidence = studio.evidence
    assert evidence.kinds() == [(0, "ADAPTER_ACCEPTED"), (0, "APPLICATION_RESULT")]
    assert evidence.payloads("APPLICATION_RESULT") == [
        {"status": TestPlanStatus.PLANNED.value, "issue": None}
    ]
    assert TestPlanStatus.PLANNED.value == "TEST_PLANNED"
    assert evidence.payloads("ADAPTER_ACCEPTED") == [
        {"result": plan, "generated_content_hashes": {"TEST_PLAN": [snapshot_content_hash(plan)]}}
    ]
    assert stored.generation_ids == tuple(evidence.generations)


def test_a_plan_started_as_a_job_answers_as_the_synchronous_plan(monkeypatch):
    studio = Studio(monkeypatch, plan_answer(), plan_answer())
    with studio.client() as client:
        synchronous = client.post(PLANS, json=plan_body())
        job = job_of(studio, client, client.post(PLANS, json=plan_body(), headers=ASYNC))
        stored_job = studio.app.state.generation_jobs.get(OWNER, PROJECT, UUID(job["job_id"]))
    first, second = MemoryTests.store.plans
    assert synchronous.status_code == 201
    assert synchronous.json() == {"status": "PLANNED", "plan": first.to_snapshot()}
    assert (job["kind"], job["operation"], job["status"]) == ("REQUEST", "TEST_PLAN", "SUCCEEDED")
    assert job["response"] == {
        "status_code": 201,
        "body": {"status": "PLANNED", "plan": second.to_snapshot()},
    }
    assert stored_job.key == request_key(
        GenerationOperation.TEST_PLAN,
        {"project_id": PROJECT},
        TestPlanRequest.model_validate(plan_body()),
    )
    assert stored_job.key.startswith("TEST_PLAN:")
    assert [item.code for item in second.paths] == ["TP-001", "TP-002"]
    kinds = studio.evidence.kinds()
    assert [kind for index, kind in kinds if index == 0] == [
        kind for index, kind in kinds if index == 1
    ]


def test_a_plan_for_chosen_criteria_keeps_the_order_of_the_specification(monkeypatch):
    studio = Studio(
        monkeypatch,
        plan_answer(
            paths=[path_answer()],
            not_covered=[{"criterion": "AC-003", "reason": MANUAL}],
        ),
    )
    with studio.client() as client:
        answer = client.post(PLANS, json=plan_body(criteria=["ac-003", "AC-001", "AC-001"]))
    assert answer.status_code == 201, answer.text
    assert answer.json()["plan"]["criteria"] == ["AC-001", "AC-003"]
    context = studio.calls[0]["context"]
    assert [item["code"] for item in context["acceptance_criteria"]] == ["AC-001", "AC-003"]


def test_a_criterion_without_a_path_gets_the_reason_that_the_model_wrote_none(monkeypatch):
    studio = Studio(monkeypatch, plan_answer(paths=[path_answer()], not_covered=[]))
    with studio.client() as client:
        answer = client.post(PLANS, json=plan_body())
    assert answer.json()["plan"]["not_covered"] == [
        {"criterion": "AC-002", "reason": NOT_PLANNED_REASON["it"]},
        {"criterion": "AC-003", "reason": NOT_PLANNED_REASON["it"]},
    ]


def test_an_unknown_criterion_is_refused_before_any_generation(monkeypatch):
    studio = Studio(monkeypatch, plan_answer())
    body = plan_body(criteria=["AC-001", "AC-009", "xyz", "AC-1"])
    refusal = {
        "detail": {"code": "ACCEPTANCE_CRITERION_UNKNOWN", "codes": ["AC-009", "XYZ", "AC-1"]}
    }
    with studio.client() as client:
        refused = client.post(PLANS, json=body)
        job = job_of(studio, client, client.post(PLANS, json=body, headers=ASYNC))
    assert refused.status_code == 422
    assert refused.json() == refusal
    assert job["response"] == {"status_code": 422, "body": refusal}
    assert job["status"] == "FAILED"
    assert studio.calls == []
    assert MemoryTests.store.plans == []
    assert studio.evidence.events == []


@pytest.mark.parametrize(
    ("setting", "status_code", "code"),
    [
        ({"requirements": False}, 409, "REQUIREMENTS_APPROVAL_REQUIRED"),
        ({"design": False}, 409, "DESIGN_APPROVAL_REQUIRED"),
        ({"model": False}, 503, "TEST_MODEL_NOT_CONFIGURED"),
        ({"model": False, "requirements": False}, 409, "REQUIREMENTS_APPROVAL_REQUIRED"),
        ({"model": False, "design": False}, 409, "DESIGN_APPROVAL_REQUIRED"),
    ],
)
def test_a_plan_refuses_an_incomplete_reference_or_a_missing_model(
    monkeypatch, setting, status_code, code
):
    studio = Studio(monkeypatch, plan_answer(), **setting)
    body = plan_body(criteria=["AC-009"])
    with studio.client() as client:
        refused = client.post(PLANS, json=body)
        job = job_of(studio, client, client.post(PLANS, json=body, headers=ASYNC))
    assert refused.status_code == status_code
    assert refused.json() == {"detail": {"code": code}}
    assert job["response"] == {"status_code": status_code, "body": {"detail": {"code": code}}}
    assert studio.calls == []
    assert MemoryTests.store.plans == []
    if studio.evidence is not None:
        assert studio.evidence.events == []


def test_an_invalid_plan_is_generated_once_more(monkeypatch):
    studio = Studio(monkeypatch, invalid_plan_answer(), plan_answer())
    with studio.client() as client:
        answer = client.post(PLANS, json=plan_body())
    assert answer.status_code == 201, answer.text
    plan = answer.json()["plan"]
    assert len(studio.calls) == 2
    assert studio.calls[0]["context"] == studio.calls[1]["context"]
    evidence = studio.evidence
    assert evidence.kinds() == [
        (0, "ADAPTER_REJECTED"),
        (0, "APPLICATION_RESULT"),
        (1, "ADAPTER_ACCEPTED"),
        (1, "APPLICATION_RESULT"),
    ]
    assert evidence.events[0][2] == {
        "code": "ValueError",
        "reason": "the first step of a path is OPEN",
    }
    assert evidence.events[1][2] == {"status": "PLAN_REJECTED", "test_plan_id": plan["id"]}
    related = evidence.payloads("ADAPTER_ACCEPTED")[0]["related_generations"]
    assert [(item["role"], item["code"]) for item in related] == [("TEST_PLANNER", "PLAN_REJECTED")]
    [stored] = MemoryTests.store.plans
    assert stored.generation_ids == tuple(evidence.generations)


@pytest.mark.parametrize(
    ("outcomes", "reason"),
    [
        ((invalid_plan_answer(), invalid_plan_answer()), "the first step of a path is OPEN"),
        (
            (
                plan_answer(paths=[path_answer(heading=ENGLISH_HEADING)]),
                plan_answer(paths=[path_answer(heading=ENGLISH_HEADING)]),
            ),
            "the path heading is not written in the language of the project",
        ),
    ],
)
def test_a_second_invalid_plan_fails_with_invalid_provider_output(monkeypatch, outcomes, reason):
    studio = Studio(monkeypatch, *outcomes)
    with studio.client() as client:
        answer = client.post(PLANS, json=plan_body())
    assert answer.status_code == 502
    assert answer.json() == {
        "detail": {"code": "INVALID_PROVIDER_OUTPUT", "stage": "MODEL_PROPOSAL"}
    }
    assert len(studio.calls) == 2
    assert MemoryTests.store.plans == []
    assert studio.evidence.kinds() == [
        (0, "ADAPTER_REJECTED"),
        (0, "APPLICATION_RESULT"),
        (1, "ADAPTER_REJECTED"),
        (1, "APPLICATION_RESULT"),
    ]
    assert [item["reason"] for item in studio.evidence.payloads("ADAPTER_REJECTED")] == [
        reason,
        reason,
    ]
    assert studio.evidence.events[-1][2] == {"status": "FAILED", "code": "INVALID_PROVIDER_OUTPUT"}


@pytest.mark.parametrize(
    ("outcomes", "status_code", "calls"),
    [
        ((ProposalGenerationError("RESPONSE_SCHEMA_ERROR"), plan_answer()), 201, 2),
        ((ProposalGenerationError("INCOMPLETE_OUTPUT"), plan_answer()), 201, 2),
        ((plan_answer(paths=[{"about_criteria": []}]), plan_answer()), 201, 2),
        (
            (
                ProposalGenerationError("RESPONSE_SCHEMA_ERROR"),
                ProposalGenerationError("RESPONSE_SCHEMA_ERROR"),
            ),
            502,
            2,
        ),
        ((ProposalGenerationError("PROVIDER_UNAVAILABLE"),), 503, 1),
        ((ProposalGenerationError("GENERATION_BUDGET_EXCEEDED"),), 402, 1),
        ((ProposalGenerationError("GENERATION_BUDGET_UNAVAILABLE"),), 503, 1),
        ((ProposalGenerationError("CONTEXT_BUDGET_EXCEEDED"),), 422, 1),
    ],
)
def test_plan_schema_errors_are_retried_once_and_other_failures_are_not(
    monkeypatch, outcomes, status_code, calls
):
    studio = Studio(monkeypatch, *outcomes)
    with studio.client() as client:
        answer = client.post(PLANS, json=plan_body())
    assert answer.status_code == status_code, answer.text
    assert len(studio.calls) == calls
    assert len(MemoryTests.store.plans) == int(status_code == 201)
    if status_code != 201:
        assert answer.json()["detail"]["code"] == outcomes[-1].code
        assert studio.evidence.events[-1][2] == {"status": "FAILED", "code": outcomes[-1].code}


def test_the_cost_of_a_plan_is_read_from_the_evidence_of_every_attempt(monkeypatch):
    evidence = CostedEvidence({0: {"cost_microusd": 50_000}, 1: {"cost_microusd": 210_000}})
    studio = Studio(monkeypatch, invalid_plan_answer(), plan_answer(), evidence=evidence)
    with studio.client() as client:
        answer = client.post(PLANS, json=plan_body())
    assert answer.status_code == 201, answer.text
    assert answer.json()["plan"]["cost_microusd"] == 260_000
    unreadable = CostedEvidence({0: None})
    studio = Studio(monkeypatch, plan_answer(), evidence=unreadable)
    with studio.client() as client:
        answer = client.post(PLANS, json=plan_body())
    assert answer.json()["plan"]["cost_microusd"] == 0


def test_a_replan_continues_the_codes_and_names_the_earlier_paths(monkeypatch):
    replanned = plan_answer(
        paths=[path_answer(heading="Un altro percorso per il calcolo")], not_covered=[]
    )
    studio = Studio(monkeypatch, plan_answer(), replanned)
    with studio.client() as client:
        first = client.post(PLANS, json=plan_body()).json()["plan"]
        earlier = {
            **first["paths"][0],
            "blocked_step": 3,
            "detail": "target not found: button:   Calcola",
            "snapshot": page().to_snapshot(),
        }
        second = client.post(PLANS, json=plan_body(criteria=["AC-001"], earlier=[earlier]))
    assert second.status_code == 201, second.text
    replan = second.json()["plan"]
    assert replan["criteria"] == ["AC-001"]
    assert replan["replan_of"] == ["TP-001"]
    assert [item["code"] for item in replan["paths"]] == ["TP-003"]
    assert replan["not_covered"] == []
    context = studio.calls[1]["context"]
    assert context["earlier"] == [{**earlier, "detail": "target not found: button: Calcola"}]
    assert [item["code"] for item in context["acceptance_criteria"]] == ["AC-001"]


def test_the_texts_read_from_the_page_are_collapsed_and_cut_before_the_model_reads_them(
    monkeypatch,
):
    snapshot = page().to_snapshot()
    snapshot["title"] = "  Mance \n del   giorno "
    snapshot["elements"][0]["name"] = "Titolo " * 50
    snapshot["elements"][1]["value"] = "v" * 1500
    snapshot["elements"][2]["options"] = ["  dieci  ", "x" * 300]
    studio = Studio(monkeypatch, plan_answer())
    with studio.client() as client:
        answer = client.post(PLANS, json=plan_body(snapshot=snapshot))
    assert answer.status_code == 201, answer.text
    seen = studio.calls[0]["context"]["application"]["snapshot"]
    assert seen["title"] == "Mance del giorno"
    heading, field, choice = seen["elements"][:3]
    assert len(heading["name"]) == 200
    assert heading["name"].endswith("…")
    assert len(field["value"]) == 1000
    assert choice["options"][0] == "dieci"
    assert len(choice["options"][1]) == 200


def page_document(**values):
    document = {key: value for key, value in page().to_snapshot().items() if key != "hidden_text"}
    document.update(values)
    return document


def earlier_item(snapshot):
    return {
        **sample_path().to_snapshot(),
        "blocked_step": 3,
        "detail": "target not found: button: Calcola",
        "snapshot": snapshot,
    }


def plan_key(body):
    return request_key(
        GenerationOperation.TEST_PLAN,
        {"project_id": PROJECT},
        TestPlanRequest.model_validate(body),
    )


def test_the_hidden_text_of_the_page_reaches_the_model_collapsed_and_cut(monkeypatch):
    body = plan_body(
        snapshot=page_document(hidden_text="  Sezione \n nascosta  " + "x" * 5000),
        earlier=[earlier_item(page_document(hidden_text=" Totale \t da   pagare "))],
    )
    studio = Studio(monkeypatch, plan_answer())
    with studio.client() as client:
        answer = client.post(PLANS, json=body)
    assert answer.status_code == 201, answer.text
    context = studio.calls[0]["context"]
    seen = context["application"]["snapshot"]
    assert list(seen) == ["url", "title", "text", "hidden_text", "elements"]
    assert MAX_SNAPSHOT_HIDDEN_TEXT_LENGTH == 3000
    assert len(seen["hidden_text"]) == MAX_SNAPSHOT_HIDDEN_TEXT_LENGTH
    assert seen["hidden_text"] == "Sezione nascosta " + "x" * 2982 + "…"
    assert seen["text"] == page().text
    assert context["earlier"][0]["snapshot"]["hidden_text"] == "Totale da pagare"
    [stored] = MemoryTests.store.plans
    assert stored.snapshot_summary == page().summary()
    assert "Sezione nascosta" not in answer.text


def test_a_snapshot_without_the_hidden_text_reaches_the_model_with_an_empty_one(monkeypatch):
    body = plan_body(snapshot=page_document(), earlier=[earlier_item(page_document())])
    assert "hidden_text" not in body["snapshot"]
    studio = Studio(monkeypatch, plan_answer())
    with studio.client() as client:
        answer = client.post(PLANS, json=body)
    assert answer.status_code == 201, answer.text
    context = studio.calls[0]["context"]
    assert context["application"]["snapshot"] == page().to_snapshot()
    assert context["application"]["snapshot"]["hidden_text"] == ""
    assert context["earlier"][0]["snapshot"]["hidden_text"] == ""


@pytest.mark.parametrize(
    ("values", "kind"),
    [
        ({"hidden_text": None}, "string_type"),
        ({"hidden_text": 42}, "string_type"),
        ({"hidden_text": "x" * 100_001}, "string_too_long"),
    ],
)
@pytest.mark.parametrize("place", ["snapshot", "earlier"])
def test_a_hidden_text_that_is_not_a_page_text_is_refused(monkeypatch, values, kind, place):
    snapshot = page_document(**values)
    if place == "earlier":
        body = plan_body(earlier=[earlier_item(snapshot)])
        location = ["body", "earlier", 0, "snapshot", "hidden_text"]
    else:
        body = plan_body(snapshot=snapshot)
        location = ["body", "snapshot", "hidden_text"]
    studio = Studio(monkeypatch, plan_answer())
    with studio.client() as client:
        refused = client.post(PLANS, json=body)
    assert refused.status_code == 422
    assert refused.json() == {
        "detail": "invalid_request",
        "errors": [{"loc": location, "type": kind}],
    }
    assert studio.calls == []
    assert MemoryTests.store.plans == []


def test_the_job_key_of_a_plan_holds_the_hidden_text_also_when_it_is_not_sent(monkeypatch):
    bare = plan_body(snapshot=page_document(), earlier=[earlier_item(page_document())])
    empty = plan_body(
        snapshot=page_document(hidden_text=""),
        earlier=[earlier_item(page_document(hidden_text=""))],
    )
    hidden = plan_body(
        snapshot=page_document(hidden_text="Sezione nascosta"),
        earlier=[earlier_item(page_document())],
    )
    hidden_earlier = plan_body(
        snapshot=page_document(),
        earlier=[earlier_item(page_document(hidden_text="Sezione nascosta"))],
    )
    studio = Studio(monkeypatch, plan_answer())
    with studio.client() as client:
        job = job_of(studio, client, client.post(PLANS, json=bare, headers=ASYNC))
        stored_job = studio.app.state.generation_jobs.get(OWNER, PROJECT, UUID(job["job_id"]))
    assert job["status"] == "SUCCEEDED"
    dumped = TestPlanRequest.model_validate(bare).model_dump(mode="json")
    assert dumped["snapshot"]["hidden_text"] == ""
    assert dumped["earlier"][0]["snapshot"]["hidden_text"] == ""
    assert stored_job.key == plan_key(bare) == plan_key(empty)
    assert stored_job.key.startswith("TEST_PLAN:")
    assert len({plan_key(bare), plan_key(hidden), plan_key(hidden_earlier)}) == 3


def element_body(**values):
    return {**page().to_snapshot()["elements"][4], **values}


@pytest.mark.parametrize(
    "values",
    [
        {"locale": "?"},
        {"locale": "italiano"},
        {"application": {"kind": "FTP", "address": "dist"}},
        {"application": {"kind": "STATIC", "address": "/home/owner/dist"}},
        {"application": {"kind": "STATIC", "address": "C:/progetto/dist"}},
        {"application": {"kind": "URL", "address": "ftp://example.org"}},
        {"application": {"kind": "URL", "address": "x" * 501}},
        {"snapshot": None},
        {"snapshot": {**page().to_snapshot(), "elements": [element_body(role="menu")]}},
        {"snapshot": {**page().to_snapshot(), "elements": [element_body(state="hidden")]}},
        {"snapshot": {**page().to_snapshot(), "elements": [element_body(options=["uno"])]}},
        {"snapshot": {**page().to_snapshot(), "elements": [element_body(index=-1)]}},
        {"snapshot": {**page().to_snapshot(), "elements": [element_body(), element_body()]}},
        {
            "snapshot": {
                **page().to_snapshot(),
                "elements": [element_body(index=n) for n in range(151)],
            }
        },
        {"snapshot": {"url": "x", "title": "y", "elements": []}},
        {"criteria": []},
        {"criteria": ["AC 001"]},
        {"criteria": ["A" * 21]},
        {"earlier": [{**sample_path().to_snapshot(), "blocked_step": 5}]},
        {"earlier": [{**sample_path().to_snapshot(), "blocked_step": 1}] * 2},
        {
            "earlier": [
                {**sample_path(f"TP-00{n}").to_snapshot(), "blocked_step": 1} for n in range(1, 7)
            ]
        },
        {"earlier": [{**sample_path().to_snapshot(), "steps": [], "blocked_step": 1}]},
        {"earlier": [{**sample_path().to_snapshot(), "code": "TP-1", "blocked_step": 1}]},
        {"extra": True},
    ],
)
def test_the_plan_body_is_validated_before_anything_else(monkeypatch, values):
    studio = Studio(monkeypatch, plan_answer())
    with studio.client() as client:
        refused = client.post(PLANS, json=plan_body(**values))
    assert refused.status_code == 422
    assert refused.json()["detail"] == "invalid_request"
    assert studio.calls == []


def test_a_run_is_recorded_against_its_plan_with_its_criteria_and_summary(monkeypatch):
    studio = Studio(monkeypatch)
    plan = stored_plan()
    with studio.client() as client:
        answer = client.post(RUNS, json=run_body(plan))
        listed = client.get(RUNS).json()
        run_id = answer.json()["run"]["id"]
        single = client.get(f"{RUNS}/{run_id}")
        missing = client.get(f"{RUNS}/{UNKNOWN}")
        reviews = client.get(f"{RUNS}/{run_id}/reviews").json()
    assert answer.status_code == 201, answer.text
    body = answer.json()
    assert body["status"] == "RECORDED"
    run = body["run"]
    assert list(run) == RUN_KEYS
    assert (run["started_at"], run["finished_at"]) == (
        "2026-09-29T10:00:00+00:00",
        "2026-09-29T10:02:00+00:00",
    )
    assert run["criteria"] == [
        {"code": "AC-001", "status": "FAILED", "paths": ["TP-001"]},
        {"code": "AC-002", "status": "PASSED", "paths": ["TP-002"]},
        {"code": "AC-003", "status": "NOT_COVERED", "paths": []},
    ]
    assert run["summary"] == {
        "passed": 1,
        "failed": 1,
        "blocked": 0,
        "not_covered": 1,
        "not_run": 0,
    }
    assert (run["critiques"], run["reviewed_at"], run["cost_microusd"]) == ([], None, 210_000)
    assert run["reference"] == plan.reference_snapshot()
    assert run["results"][0]["path"] == plan.paths[0].to_snapshot()
    assert run["results"][1]["steps"][3]["screenshot"] == "TP-001/firefox/04.png"
    [stored] = MemoryTests.store.runs
    assert stored.to_snapshot() == run
    assert (stored.plan_id, stored.replan_ids) == (PLAN_ID, ())
    assert listed == {"items": [run]}
    assert single.json() == run
    assert missing.status_code == 404
    assert missing.json() == {"detail": {"code": "TEST_RUN_NOT_FOUND"}}
    assert reviews == {"items": []}
    assert studio.calls == []


def test_a_run_with_a_replan_counts_both_plans(monkeypatch):
    studio = Studio(monkeypatch)
    plan = stored_plan()
    replan = stored_plan(
        sample_plan(
            id=REPLAN_ID,
            criteria=("AC-001",),
            paths=(sample_path("TP-003"),),
            not_covered=(),
            replan_of=("TP-001",),
            cost_microusd=190_000,
        )
    )
    body = run_body(
        plan,
        results=[result_body(replan.paths[0]), result_body(replan.paths[0], "firefox")],
        replan_ids=[str(REPLAN_ID)],
    )
    with studio.client() as client:
        answer = client.post(RUNS, json=body)
    assert answer.status_code == 201, answer.text
    run = answer.json()["run"]
    assert run["cost_microusd"] == 400_000
    assert run["criteria"] == [
        {"code": "AC-001", "status": "PASSED", "paths": ["TP-003"]},
        {"code": "AC-002", "status": "NOT_RUN", "paths": ["TP-002"]},
        {"code": "AC-003", "status": "NOT_COVERED", "paths": []},
    ]
    assert MemoryTests.store.runs[0].replan_ids == (REPLAN_ID,)


@pytest.mark.parametrize(
    "values",
    [
        {"plan_id": str(UNKNOWN)},
        {"replan_ids": [str(UNKNOWN)]},
    ],
)
def test_a_run_refuses_an_unknown_plan(monkeypatch, values):
    studio = Studio(monkeypatch)
    plan = stored_plan()
    with studio.client() as client:
        refused = client.post(RUNS, json=run_body(plan, **values))
    assert refused.status_code == 404
    assert refused.json() == {"detail": {"code": "TEST_PLAN_NOT_FOUND"}}
    assert MemoryTests.store.runs == []


def test_a_plan_of_another_project_is_unknown_to_the_run(monkeypatch):
    studio = Studio(monkeypatch)
    stored_plan(sample_plan(project_id=STRANGER))
    with studio.client() as client:
        refused = client.post(RUNS, json=run_body())
    assert refused.status_code == 404
    assert refused.json() == {"detail": {"code": "TEST_PLAN_NOT_FOUND"}}


@pytest.mark.parametrize(
    ("results", "not_covered", "message"),
    [
        (
            [result_body(sample_path("TP-009"))],
            None,
            "result 0 names the path TP-009, which is not in the plan or in its replans",
        ),
        (
            [result_body(sample_path("TP-002", ("AC-002",)))],
            None,
            "result 0 holds more steps than its path",
        ),
        (
            [],
            [{"criterion": "AC-009", "reason": "Fuori dal piano."}],
            "the not covered criteria AC-009 are not in the plans",
        ),
    ],
)
def test_a_run_refuses_results_outside_its_plan(monkeypatch, results, not_covered, message):
    studio = Studio(monkeypatch)
    plan = stored_plan()
    body = run_body(plan, results=results)
    if not_covered is not None:
        body["not_covered"] = not_covered
    with studio.client() as client:
        refused = client.post(RUNS, json=body)
    assert refused.status_code == 422
    assert refused.json() == {
        "detail": {
            "code": "invalid_request",
            "errors": [{"loc": ["body"], "type": "value_error", "msg": message}],
        }
    }
    assert MemoryTests.store.runs == []


def steps_body(*indexes):
    return [
        {
            "index": index,
            "status": "DONE",
            "detail": None,
            "url": None,
            "title": None,
            "screenshot": None,
        }
        for index in indexes
    ]


PATH = sample_plan().paths[0]


@pytest.mark.parametrize(
    "values",
    [
        {"results": [{**result_body(PATH), "steps": steps_body(2, 1)}]},
        {"results": [{**result_body(PATH), "steps": steps_body(1, 3)}]},
        {"results": [{**result_body(PATH), "steps": steps_body(1, 2, 3, 4, 5)}]},
        {"results": [{**result_body(PATH), "steps": steps_body(0)}]},
        {"results": [result_body(PATH, status="SKIPPED")]},
        {"results": [result_body(PATH, browser="safari")]},
        {"results": [result_body(PATH, seconds=-1)]},
        {"results": [result_body(PATH, page_text="x" * 100_001)]},
        {"results": [{**result_body(PATH), "path": {**PATH.to_snapshot(), "steps": []}}]},
        {"results": [result_body(PATH)] * 61},
        {"browsers": [{"name": "chrome", "version": "151"}] * 2},
        {"browsers": [{"name": "chrome", "version": "151"}]},
        {"browsers": []},
        {"browsers": [{"name": "chrome", "version": ""}, {"name": "firefox", "version": "1"}]},
        {"started_at": "2026-09-29T12:03:00+02:00"},
        {"started_at": "2026-09-29T12:00:00"},
        {"plan_id": "not-a-uuid"},
        {"replan_ids": [str(PLAN_ID)]},
        {"replan_ids": [str(REPLAN_ID), str(REPLAN_ID)]},
        {"application": {"kind": "STATIC", "address": "../dist"}},
        {"not_covered": [{"criterion": "AC-003", "reason": "Uno."}] * 2},
        {"not_covered": [{"criterion": "AC-3", "reason": "Uno."}]},
        {"extra": True},
    ],
)
def test_the_run_body_is_validated_before_anything_else(monkeypatch, values):
    studio = Studio(monkeypatch)
    stored_plan()
    with studio.client() as client:
        refused = client.post(RUNS, json=run_body(**values))
    assert refused.status_code == 422
    assert refused.json()["detail"] == "invalid_request"
    assert MemoryTests.store.runs == []


@pytest.mark.parametrize(
    "screenshot", ["../01.png", "/tmp/01.png", "C:/01.png", "TP-001\\01.png", "x" * 201]
)
def test_a_screenshot_outside_the_run_folder_is_refused(monkeypatch, screenshot):
    studio = Studio(monkeypatch)
    stored_plan()
    result = result_body(PATH)
    result["steps"][0]["screenshot"] = screenshot
    with studio.client() as client:
        refused = client.post(RUNS, json=run_body(results=[result]))
    assert refused.status_code == 422
    assert refused.json()["detail"] == "invalid_request"


def test_the_texts_of_the_page_in_a_run_are_collapsed_and_cut(monkeypatch):
    studio = Studio(monkeypatch)
    plan = stored_plan()
    result = result_body(plan.paths[1], page_text="  Totale \n " + "x" * 2000)
    result["steps"][0]["detail"] = "d" * 400
    result["steps"][0]["title"] = " Mance \t oggi "
    with studio.client() as client:
        answer = client.post(RUNS, json=run_body(plan, results=[result]))
    assert answer.status_code == 201, answer.text
    [stored] = answer.json()["run"]["results"]
    assert len(stored["page_text"]) == 1500
    assert stored["page_text"].startswith("Totale x")
    assert len(stored["steps"][0]["detail"]) == 300
    assert stored["steps"][0]["title"] == "Mance oggi"


def test_a_review_asks_every_approved_twin_and_stores_the_critiques(monkeypatch):
    studio = Studio(monkeypatch, critique_answer(), fine_answer())
    run = stored_run()
    with studio.client() as client:
        answer = client.post(f"{RUNS}/{RUN_ID}/reviews", json=REVIEW)
        reviews = client.get(f"{RUNS}/{RUN_ID}/reviews").json()
        read = client.get(f"{RUNS}/{RUN_ID}").json()
        overview = client.get(OVERVIEW).json()
    assert answer.status_code == 201, answer.text
    body = answer.json()
    assert body["status"] == "REVIEWED"
    [review] = MemoryTests.store.reviews
    snapshot = body["review"]
    assert snapshot == review.to_snapshot()
    assert list(snapshot) == ["id", "run_id", "reviewed_at", "locale", "critiques", "cost_microusd"]
    assert (snapshot["run_id"], snapshot["locale"], snapshot["cost_microusd"]) == (
        str(RUN_ID),
        "it-IT",
        0,
    )
    assert reviews == {"items": [snapshot]}
    assert read["critiques"] == snapshot["critiques"]
    assert read["reviewed_at"] == snapshot["reviewed_at"]
    assert read["cost_microusd"] == 210_000
    assert overview["latest_run"] == read
    critiques = snapshot["critiques"]
    assert [item["twin_name"] for item in critiques] == ["Receptionist Twin", "Night Auditor Twin"]
    assert [item["verdict"] for item in critiques] == ["CONCERN", "FINE"]
    assert critiques[0]["findings"] == [
        {
            "severity": "MEDIUM",
            "text": "Il totale non mostra la valuta.",
            "about": {"criterion": "AC-001", "requirement": "REQ-001", "screen": "SCR-001"},
            "action": "Mostrare la valuta accanto al totale.",
        }
    ]
    calls = studio.calls
    assert [call["task"] for call in calls] == [REVIEW_TASK] * 2
    assert [call["context"]["purpose"] for call in calls] == [REVIEW_PURPOSE] * 2
    assert [call["context"]["user_twin"]["twin_id"] for call in calls] == [
        str(first_twin().twin_id),
        str(second_twin().twin_id),
    ]
    assert {call["retry_schema_errors"] for call in calls} == {False}
    context = calls[0]["context"]
    assert context["run"] == run_material(run.to_snapshot())
    assert [item["code"] for item in context["acceptance_criteria"]] == [
        "AC-001",
        "AC-002",
        "AC-003",
    ]
    evidence = studio.evidence
    assert evidence.kinds() == [
        (0, "ADAPTER_ACCEPTED"),
        (0, "APPLICATION_RESULT"),
        (1, "ADAPTER_ACCEPTED"),
        (1, "APPLICATION_RESULT"),
    ]
    assert evidence.payloads("APPLICATION_RESULT") == [
        {"status": "TWIN_CRITIQUED", "test_run_id": str(RUN_ID), "test_review_id": snapshot["id"]},
        {"status": TestReviewStatus.REVIEWED.value, "issue": None},
    ]
    assert TestReviewStatus.REVIEWED.value == "TEST_RUN_REVIEWED"
    first, second = evidence.payloads("ADAPTER_ACCEPTED")
    assert first == {
        "result": critiques[0],
        "generated_content_hashes": {"TEST_REVIEW": [snapshot_content_hash(critiques[0])]},
    }
    assert second["result"] == critiques[1]
    assert second["related_generations"] == [
        {
            "role": "TEST_CRITIQUE",
            "generation_id": str(evidence.generations[0]),
            "request_hash": "d" * 64,
            "code": "TWIN_CRITIQUED",
        }
    ]
    assert review.generation_ids == tuple(evidence.generations)


def test_a_review_started_as_a_job_answers_as_the_synchronous_review(monkeypatch):
    studio = Studio(monkeypatch, critique_answer(), fine_answer(), fine_answer(), fine_answer())
    stored_run()
    with studio.client() as client:
        synchronous = client.post(f"{RUNS}/{RUN_ID}/reviews", json=REVIEW)
        job = job_of(
            studio,
            client,
            client.post(f"{RUNS}/{RUN_ID}/reviews", json={**REVIEW, "again": True}, headers=ASYNC),
        )
        stored_job = studio.app.state.generation_jobs.get(OWNER, PROJECT, UUID(job["job_id"]))
        listed = client.get(f"{RUNS}/{RUN_ID}/reviews").json()["items"]
        read = client.get(f"{RUNS}/{RUN_ID}").json()
    first, second = MemoryTests.store.reviews
    assert synchronous.json() == {"status": "REVIEWED", "review": first.to_snapshot()}
    assert (job["kind"], job["operation"], job["status"]) == (
        "REQUEST",
        "TEST_REVIEW",
        "SUCCEEDED",
    )
    assert job["response"] == {
        "status_code": 201,
        "body": {"status": "REVIEWED", "review": second.to_snapshot()},
    }
    assert stored_job.key == request_key(
        GenerationOperation.TEST_REVIEW,
        {"project_id": PROJECT, "run_id": RUN_ID},
        TestReviewRequest(again=True),
    )
    assert stored_job.key.startswith(f"TEST_REVIEW:run_id={RUN_ID}:")
    assert [item["id"] for item in listed] == [str(second.id), str(first.id)]
    assert read["critiques"] == second.to_snapshot()["critiques"]
    assert [item["verdict"] for item in read["critiques"]] == ["FINE", "FINE"]


def test_a_second_review_needs_again(monkeypatch):
    studio = Studio(monkeypatch, critique_answer(), fine_answer())
    stored_run()
    with studio.client() as client:
        assert client.post(f"{RUNS}/{RUN_ID}/reviews", json=REVIEW).status_code == 201
        refused = client.post(f"{RUNS}/{RUN_ID}/reviews", json=REVIEW)
    assert refused.status_code == 409
    assert refused.json() == {"detail": {"code": "TEST_REVIEW_EXISTS"}}
    assert len(studio.calls) == 2


@pytest.mark.parametrize(
    ("setting", "run_id", "status_code", "code"),
    [
        ({}, UNKNOWN, 404, "TEST_RUN_NOT_FOUND"),
        ({"requirements": False}, RUN_ID, 409, "REQUIREMENTS_APPROVAL_REQUIRED"),
        ({"design": False}, RUN_ID, 409, "DESIGN_APPROVAL_REQUIRED"),
        ({"modeling": False}, RUN_ID, 409, "USER_MODELING_APPROVAL_REQUIRED"),
        ({"twins": ()}, RUN_ID, 409, "USER_MODELING_APPROVAL_REQUIRED"),
        ({"model": False}, RUN_ID, 503, "TEST_MODEL_NOT_CONFIGURED"),
        ({"model": False, "modeling": False}, RUN_ID, 409, "USER_MODELING_APPROVAL_REQUIRED"),
    ],
)
def test_a_review_refuses_in_the_order_of_the_contract(
    monkeypatch, setting, run_id, status_code, code
):
    studio = Studio(monkeypatch, critique_answer(), fine_answer(), **setting)
    stored_run()
    with studio.client() as client:
        refused = client.post(f"{RUNS}/{run_id}/reviews", json=REVIEW)
        job = job_of(
            studio, client, client.post(f"{RUNS}/{run_id}/reviews", json=REVIEW, headers=ASYNC)
        )
    assert refused.status_code == status_code
    assert refused.json() == {"detail": {"code": code}}
    assert job["response"] == {"status_code": status_code, "body": {"detail": {"code": code}}}
    assert studio.calls == []
    assert MemoryTests.store.reviews == []


def test_an_existing_review_is_refused_before_the_missing_model(monkeypatch):
    studio = Studio(monkeypatch, model=False, modeling=False)
    run = stored_run()
    MemoryTests.store.reviews.append(
        sample_review(run_id=run.id, reviewed_at=datetime(2026, 9, 29, 13, 0, tzinfo=UTC))
    )
    with studio.client() as client:
        refused = client.post(f"{RUNS}/{RUN_ID}/reviews", json=REVIEW)
        read = client.get(f"{RUNS}/{RUN_ID}").json()
    assert refused.status_code == 409
    assert refused.json() == {"detail": {"code": "TEST_REVIEW_EXISTS"}}
    assert read["reviewed_at"] == "2026-09-29T13:00:00+00:00"
    assert read["cost_microusd"] == 360_000


def test_an_invalid_critique_is_generated_once_more(monkeypatch):
    studio = Studio(monkeypatch, critique_answer(ENGLISH), critique_answer(), fine_answer())
    stored_run()
    with studio.client() as client:
        answer = client.post(f"{RUNS}/{RUN_ID}/reviews", json=REVIEW)
    assert answer.status_code == 201, answer.text
    review = answer.json()["review"]
    assert len(studio.calls) == 3
    assert studio.calls[0]["context"] == studio.calls[1]["context"]
    evidence = studio.evidence
    assert evidence.kinds() == [
        (0, "ADAPTER_REJECTED"),
        (0, "APPLICATION_RESULT"),
        (1, "ADAPTER_ACCEPTED"),
        (1, "APPLICATION_RESULT"),
        (2, "ADAPTER_ACCEPTED"),
        (2, "APPLICATION_RESULT"),
    ]
    assert evidence.events[0][2] == {
        "code": "ValueError",
        "reason": "the critique summary is not written in the language of the project",
    }
    assert evidence.events[1][2] == {
        "status": "CRITIQUE_REJECTED",
        "test_run_id": str(RUN_ID),
        "test_review_id": review["id"],
    }
    related = evidence.payloads("ADAPTER_ACCEPTED")[-1]["related_generations"]
    assert [(item["role"], item["code"]) for item in related] == [
        ("TEST_CRITIQUE", "CRITIQUE_REJECTED"),
        ("TEST_CRITIQUE", "TWIN_CRITIQUED"),
    ]
    assert review["critiques"][0]["summary"] == ITALIAN


def test_a_second_invalid_critique_fails_and_stores_nothing(monkeypatch):
    studio = Studio(monkeypatch, critique_answer("x"), critique_answer("Troppo breve."))
    stored_run()
    with studio.client() as client:
        answer = client.post(f"{RUNS}/{RUN_ID}/reviews", json=REVIEW)
    assert answer.status_code == 502
    assert answer.json() == {
        "detail": {"code": "INVALID_PROVIDER_OUTPUT", "stage": "MODEL_PROPOSAL"}
    }
    assert MemoryTests.store.reviews == []
    assert [item["reason"] for item in studio.evidence.payloads("ADAPTER_REJECTED")] == [
        "the critique summary is shorter than 20 characters",
        "the critique summary is shorter than 20 characters",
    ]


def test_the_cost_of_a_review_is_the_sum_of_its_generations(monkeypatch):
    evidence = CostedEvidence({0: {"cost_microusd": 150_000}, 1: {"cost_microusd": 140_000}})
    studio = Studio(monkeypatch, critique_answer(), fine_answer(), evidence=evidence)
    stored_run()
    with studio.client() as client:
        answer = client.post(f"{RUNS}/{RUN_ID}/reviews", json=REVIEW)
        read = client.get(f"{RUNS}/{RUN_ID}").json()
    assert answer.json()["review"]["cost_microusd"] == 290_000
    assert read["cost_microusd"] == 500_000


@pytest.mark.parametrize(
    "body", [{"locale": "?"}, {"again": "maybe"}, {"locale": "it-IT", "extra": 1}]
)
def test_the_review_body_is_validated(monkeypatch, body):
    studio = Studio(monkeypatch, critique_answer(), fine_answer())
    stored_run()
    with studio.client() as client:
        refused = client.post(f"{RUNS}/{RUN_ID}/reviews", json=body)
    assert refused.status_code == 422
    assert refused.json()["detail"] == "invalid_request"
    assert studio.calls == []


def test_the_overview_answers_the_reference_the_counts_and_the_latest_run(monkeypatch):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        empty = client.get(OVERVIEW).json()
        run = stored_run()
        filled = client.get(OVERVIEW).json()
    requirements, design = studio.requirements, studio.design
    assert empty == {
        "project_id": str(PROJECT),
        "reference": {
            "requirements": {
                "version_id": str(requirements.id),
                "version_number": 1,
                "content_hash": requirements.content_hash,
            },
            "design": {
                "version_id": str(design.id),
                "version_number": 1,
                "content_hash": design.content_hash,
                "alternative_code": "DES-001",
            },
        },
        "plan_available": True,
        "plans": 0,
        "runs": 0,
        "latest_run": None,
        "latest_run_stale": False,
        "latest_review": None,
    }
    assert list(empty) == [
        "project_id",
        "reference",
        "plan_available",
        "plans",
        "runs",
        "latest_run",
        "latest_run_stale",
        "latest_review",
    ]
    assert (filled["plans"], filled["runs"]) == (1, 1)
    assert filled["latest_run"] == run.to_snapshot()
    assert filled["latest_run_stale"] is True
    assert filled["latest_review"] is None
    bare = Studio(monkeypatch, model=False, requirements=False, design=False)
    with bare.client() as client:
        partial = client.get(OVERVIEW).json()
    assert partial["reference"] == {"requirements": None, "design": None}
    assert partial["plan_available"] is False
    assert (partial["latest_run"], partial["latest_run_stale"]) == (None, False)


ROUTES = [
    ("GET", "/acceptance-tests", None),
    ("POST", "/test-plans", plan_body()),
    ("GET", "/test-plans", None),
    ("GET", f"/test-plans/{PLAN_ID}", None),
    ("POST", "/test-runs", run_body()),
    ("GET", "/test-runs", None),
    ("GET", f"/test-runs/{RUN_ID}", None),
    ("POST", f"/test-runs/{RUN_ID}/reviews", REVIEW),
    ("GET", f"/test-runs/{RUN_ID}/reviews", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_every_route_answers_project_not_found_for_another_owner(monkeypatch, method, path, body):
    studio = Studio(monkeypatch, plan_answer(), critique_answer(), fine_answer())
    stored_run()
    studio.app.dependency_overrides[current_user_dependency] = lambda: account(STRANGER)
    with studio.client() as client:
        answer = client.request(method, f"{PROJECT_PATH}{path}", json=body)
    assert answer.status_code == 404
    assert answer.json() == {"detail": {"code": "PROJECT_NOT_FOUND"}}
    assert studio.calls == []
    assert (len(MemoryTests.store.plans), len(MemoryTests.store.runs)) == (1, 1)
    assert MemoryTests.store.reviews == []


def test_the_application_can_be_driven_without_the_router(monkeypatch):
    studio = Studio(monkeypatch, plan_answer())
    application = studio.application()
    assert application.plan_available()
    result = asyncio.run(
        application.plan(
            owner_user_id=OWNER,
            project_id=PROJECT,
            body=TestPlanRequest.model_validate(plan_body()),
        )
    )
    assert result.status is TestPlanStatus.PLANNED
    assert MemoryTests.store.plans == [result.plan]
    plans = asyncio.run(application.plans(owner_user_id=OWNER, project_id=PROJECT))
    assert plans == (result.plan,)


def test_a_database_less_runtime_answers_database_unavailable(monkeypatch):
    studio = Studio(monkeypatch)
    studio.runtime.database_runtime = None
    with pytest.raises(HTTPException) as failure:
        asyncio.run(studio.application().runs(owner_user_id=OWNER, project_id=PROJECT))
    assert failure.value.status_code == 503
    assert failure.value.detail == {"code": "DATABASE_UNAVAILABLE"}


OLDER_RUN = UUID("00000000-0000-4000-8000-000000000c0a")
MIDDLE_RUN = UUID("00000000-0000-4000-8000-000000000c0b")
BUTTON_FINDING = "Il pulsante Calcola non risponde al tocco."


@pytest.mark.parametrize(
    ("reference", "setting", "stale"),
    [
        ({"requirements_version_number": 1, "design_version_number": 1}, {}, False),
        ({"requirements_version_number": 2, "design_version_number": 1}, {}, True),
        ({"requirements_version_number": 1, "design_version_number": 2}, {}, True),
        (
            {
                "requirements_version_number": 1,
                "design_version_number": 1,
                "alternative_code": "DES-002",
            },
            {},
            True,
        ),
        ({"requirements_version_number": 2}, {"design": False}, False),
        ({"design_version_number": 2}, {"requirements": False}, False),
    ],
)
def test_the_overview_says_whether_the_latest_run_is_stale(monkeypatch, reference, setting, stale):
    studio = Studio(monkeypatch, **setting)
    plan = stored_plan(sample_plan(**{"alternative_code": "DES-001", **reference}))
    MemoryTests.store.runs.append(sample_run((plan,)))
    with studio.client() as client:
        overview = client.get(OVERVIEW).json()
    assert overview["latest_run"]["reference"] == plan.reference_snapshot()
    assert overview["latest_run_stale"] is stale


def test_the_overview_gives_the_latest_review_also_when_the_latest_run_has_none(monkeypatch):
    studio = Studio(monkeypatch)
    plan = stored_plan()
    older = sample_run((plan,), run_id=OLDER_RUN)
    newest = sample_run((plan,))
    MemoryTests.store.runs.extend([older, newest])
    first = sample_review(id=UUID(int=0xF1), run_id=OLDER_RUN)
    second = sample_review(
        id=UUID(int=0xF2),
        run_id=OLDER_RUN,
        reviewed_at=first.reviewed_at + timedelta(hours=1),
        critiques=(sample_critique(findings=(sample_finding(text=BUTTON_FINDING),)),),
    )
    MemoryTests.store.reviews.extend([first, second])
    with studio.client() as client:
        unreviewed = client.get(OVERVIEW).json()
        MemoryTests.store.reviews.append(sample_review(id=UUID(int=0xF3), run_id=RUN_ID))
        reviewed = client.get(OVERVIEW).json()
    assert unreviewed["latest_run"]["id"] == str(RUN_ID)
    assert unreviewed["latest_run"]["critiques"] == []
    latest = unreviewed["latest_review"]
    assert list(latest) == ["run_id", "finished_at", "reviewed_at", "critiques"]
    snapshot = older.with_review(second).to_snapshot()
    assert latest == {
        "run_id": str(OLDER_RUN),
        "finished_at": snapshot["finished_at"],
        "reviewed_at": snapshot["reviewed_at"],
        "critiques": snapshot["critiques"],
    }
    assert latest["critiques"][0]["findings"][0]["text"] == BUTTON_FINDING
    assert reviewed["latest_review"]["run_id"] == str(RUN_ID)
    assert reviewed["latest_review"]["critiques"] == reviewed["latest_run"]["critiques"]


def test_the_critique_of_a_run_remembers_the_findings_of_the_newest_reviewed_run_before_it(
    monkeypatch,
):
    studio = Studio(monkeypatch, *([critique_answer(), fine_answer()] * 4))
    plan = stored_plan()
    MemoryTests.store.runs.extend(
        [
            sample_run((plan,), run_id=OLDER_RUN),
            sample_run((plan,), run_id=MIDDLE_RUN),
            sample_run((plan,)),
        ]
    )
    MemoryTests.store.reviews.append(
        sample_review(
            id=UUID(int=0xF1),
            run_id=OLDER_RUN,
            critiques=(
                sample_critique(
                    first_twin().twin_id,
                    findings=(sample_finding(), sample_finding(text=BUTTON_FINDING)),
                ),
                sample_critique(second_twin().twin_id, "Night Auditor Twin", findings=()),
            ),
        )
    )
    with studio.client() as client:
        for run_id, again in (
            (RUN_ID, False),
            (MIDDLE_RUN, False),
            (OLDER_RUN, True),
            (RUN_ID, True),
        ):
            answer = client.post(f"{RUNS}/{run_id}/reviews", json={**REVIEW, "again": again})
            assert answer.status_code == 201, answer.text
    remembered = [call["context"]["earlier_findings"] for call in studio.calls]
    older_findings = ["Il totale non mostra la valuta che uso.", BUTTON_FINDING]
    assert remembered == [
        older_findings,
        [],
        older_findings,
        [],
        [],
        [],
        ["Il totale non mostra la valuta."],
        [],
    ]
    assert all(list(call["context"])[-2:] == ["run", "earlier_findings"] for call in studio.calls)


def test_a_test_critique_gives_each_twin_what_it_learned(monkeypatch):
    twin_id = second_twin().twin_id
    learned = {twin_id: learned_by(twin_id, "Il gruppo lavora di notte con poca luce.")}
    studios = []
    for known in (learned, None):
        current = Studio(monkeypatch, critique_answer(), fine_answer(), learned=known)
        stored_run()
        with current.client() as client:
            answer = client.post(f"{RUNS}/{RUN_ID}/reviews", json=REVIEW)
            assert answer.status_code == 201, answer.text
        studios.append(current)
    studio, plain = studios
    first, second = studio.calls
    assert "learned" not in first["context"]["user_twin"]
    assert first["instruction"] is REVIEW_INSTRUCTION
    assert second["context"]["user_twin"]["learned"] == [
        {
            "code": "OBS-001",
            "statement": "Il gruppo lavora di notte con poca luce.",
            "source": "OWNER",
        }
    ]
    assert second["instruction"] == f"{REVIEW_INSTRUCTION} {LEARNED_INSTRUCTION}"
    plain_first, plain_second = plain.calls
    assert plain_first["context"] == first["context"]
    assert plain_first["instruction"] is REVIEW_INSTRUCTION
    assert plain_second["context"] == {
        **second["context"],
        "user_twin": {
            key: value for key, value in second["context"]["user_twin"].items() if key != "learned"
        },
    }
    assert plain_second["instruction"] is REVIEW_INSTRUCTION
    assert studio.evidence.kinds() == plain.evidence.kinds()
