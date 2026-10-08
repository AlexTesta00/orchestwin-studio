from __future__ import annotations

from dataclasses import replace
from typing import ClassVar
from uuid import UUID

import pytest

from orchestwin.api import knowledge_alignment as alignment_api
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.generation_requests import PREFERENCE_APPLIED, RESPOND_ASYNC
from orchestwin.api.knowledge_alignment import LATEST_RUN_KEYS, create_knowledge_alignment_router
from orchestwin.artifacts.design_revision_application import (
    DesignRevisionResult,
    DesignRevisionStatus,
)
from orchestwin.models.knowledge_alignment import INSTRUCTION, PURPOSE, TASK
from orchestwin.projects.design_change_application import (
    DesignChangeIssueCode,
    DesignChangeResult,
    DesignChangeStatus,
)
from orchestwin.projects.knowledge_alignment import proposal_number
from orchestwin.projects.requirements_change_application import (
    RequirementsChangeIssueCode,
    RequirementsChangeResult,
    RequirementsChangeStatus,
)
from orchestwin.projects.requirements_primitives import snapshot_content_hash
from src.test.python.api.test_code_changes_api import (
    FIRST,
    JOBS,
    PROJECT_PATH,
    SECOND,
    STRANGER,
    THIRD,
    MemoryChanges,
    Studio,
    account,
    record,
)
from src.test.python.api.test_design_api import design_version, proposed_diff
from src.test.python.artifacts import design_fixtures
from src.test.python.projects.test_acceptance_tests import sample_plan
from src.test.python.projects.test_requirements_change_application import Harness

OWNER = design_fixtures.OWNER_ID
PROJECT = design_fixtures.PROJECT_ID
RUNS = f"{PROJECT_PATH}/alignment/runs"
PROPOSALS = f"{PROJECT_PATH}/alignment/proposals"
ASYNC = {"Prefer": RESPOND_ASYNC}
ITALIAN = "Il codice aggiunge la lista degli ospiti con la data di arrivo che la Definizione non descrive."
ENGLISH = (
    "The code adds the guest list with the arrival date that the requirements do not describe."
)
TEXT = "Aggiungere alla Definizione il requisito della data di arrivo di ogni ospite."
DESIGN_CHANGE = "Il flusso chiede una conferma prima del salvataggio della prenotazione."
RUN_KEYS = [
    "id",
    "project_id",
    "from_commit",
    "to_commit",
    "commits",
    "locale",
    "requirements_version_number",
    "design_version_number",
    "alternative_code",
    "summary",
    "created_at",
    "cost_microusd",
    "generation_ids",
    "proposals",
]
REVISION_KEYS = {
    "status",
    "diff",
    "version",
    "issue",
    "proposal_issue",
    "diff_persistence_status",
    "version_persistence_status",
}


def proposal_answer(section="REQUIREMENTS", **values):
    answer = {
        "excerpt": "+nuovo",
        "files": ["src/app.js"],
        "rationale": "Il diff aggiunge la lista degli ospiti che la Definizione non nomina.",
        "request": (
            "Aggiungere alla Definizione il requisito della lista degli ospiti con la data di arrivo."
        ),
        "section": section,
        "subjects": {"criteria": ["AC-001"], "requirements": ["REQ-001"], "screens": ["SCR-001"]},
        "title": "Lista degli ospiti nella Definizione",
    }
    answer.update(values)
    return answer


def alignment_answer(proposals=None, summary=ITALIAN):
    return {
        "proposals": [proposal_answer(section) for section in ("REQUIREMENTS", "DESIGN", "TESTS")]
        if proposals is None
        else list(proposals),
        "summary": summary,
    }


class AlignmentStore:
    def __init__(self):
        self.runs = []


class MemoryAlignment:
    store: ClassVar[AlignmentStore] = AlignmentStore()

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    def _owned(self, project_id):
        return self.owner_user_id == OWNER and project_id == PROJECT

    def _runs(self, project_id):
        if not self._owned(project_id):
            return []
        return sorted(
            (run for run in self.store.runs if run.project_id == project_id),
            key=lambda run: (run.created_at, str(run.id)),
            reverse=True,
        )

    async def project_exists(self, project_id):
        return self._owned(project_id)

    async def next_number(self, project_id):
        numbers = [
            item.number
            for run in self.store.runs
            if run.project_id == project_id
            for item in run.proposals
        ]
        return max(numbers, default=0) + 1

    async def create_run(self, run):
        if run.owner_user_id != self.owner_user_id or not self._owned(run.project_id):
            raise ValueError("knowledge alignment runs need an owned active project")
        stored = run.renumbered(await self.next_number(run.project_id))
        self.store.runs.append(stored)
        return stored

    async def runs(self, project_id):
        return tuple(self._runs(project_id))

    async def latest_run(self, project_id):
        runs = self._runs(project_id)
        return runs[0] if runs else None

    async def run(self, project_id, run_id):
        return next((run for run in self._runs(project_id) if run.id == run_id), None)

    async def proposals(self, project_id, *, waiting_only=False):
        items = [
            item
            for run in self._runs(project_id)
            for item in run.proposals
            if item.waiting or not waiting_only
        ]
        return tuple(sorted(items, key=lambda item: (item.created_at, item.number), reverse=True))

    async def proposal(self, project_id, code):
        number = proposal_number(code)
        if number is None:
            return None
        return next(
            (item for item in await self.proposals(project_id) if item.number == number), None
        )

    async def decide(
        self,
        project_id,
        code,
        *,
        status,
        decided_at,
        note=None,
        applied_text=None,
        applied_diff_id=None,
    ):
        number = proposal_number(code)
        if number is None or not self._owned(project_id):
            return None
        for index, run in enumerate(self.store.runs):
            for item in run.proposals:
                if run.project_id == project_id and item.number == number:
                    decided = item.with_decision(
                        status=status,
                        decided_at=decided_at,
                        note=note,
                        applied_text=applied_text,
                        applied_diff_id=applied_diff_id,
                    )
                    self.store.runs[index] = replace(
                        run,
                        proposals=tuple(
                            decided if candidate.id == item.id else candidate
                            for candidate in run.proposals
                        ),
                    )
                    return decided
        return None


class MemoryPlans:
    store: ClassVar[list] = []

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def plans(self, project_id, *, limit=20):
        if self.owner_user_id != OWNER:
            return ()
        items = [plan for plan in reversed(self.store) if plan.project_id == project_id]
        return tuple(items if limit is None else items[:limit])


class ScriptedService:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    async def request_change(self, **arguments):
        self.calls.append(arguments)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class AlignmentStudio(Studio):
    def __init__(self, monkeypatch, *outcomes, **settings):
        MemoryAlignment.store = AlignmentStore()
        MemoryPlans.store = []
        monkeypatch.setattr(
            alignment_api, "SqlAlchemyKnowledgeAlignmentRepository", MemoryAlignment
        )
        monkeypatch.setattr(alignment_api, "SqlAlchemyCodeChangeRepository", MemoryChanges)
        monkeypatch.setattr(alignment_api, "SqlAlchemyAcceptanceTestRepository", MemoryPlans)
        super().__init__(monkeypatch, *outcomes, **settings)


def align(client, *commits, headers=None, **values):
    chosen = list(commits) if commits else [FIRST, SECOND]
    body = {"locale": "it-IT", "from_commit": None, "to_commit": chosen[-1], "commits": chosen}
    body.update(values)
    return client.post(RUNS, json=body, headers=headers)


def finished(client, studio, started):
    assert started.status_code == 202, started.text
    job_id = started.json()["job_id"]
    client.portal.call(studio.app.state.generation_jobs.wait, UUID(job_id))
    return client.get(f"{JOBS}/{job_id}").json()


def test_router_registers_the_routes():
    router = create_knowledge_alignment_router()
    methods = sorted(
        (route.path.removeprefix("/projects/{project_id}"), *sorted(route.methods))
        for route in router.routes
    )
    assert methods == [
        ("/alignment/proposals", "GET"),
        ("/alignment/proposals/{code}/apply", "POST"),
        ("/alignment/proposals/{code}/skip", "POST"),
        ("/alignment/runs", "GET"),
        ("/alignment/runs", "POST"),
        ("/alignment/runs/{run_id}", "GET"),
    ]


def test_a_run_proposes_updates_from_the_recorded_commits_and_stores_them(monkeypatch):
    studio = AlignmentStudio(monkeypatch, alignment_answer())
    with studio.client() as client:
        record(client, FIRST, SECOND)
        answer = align(client)
    assert answer.status_code == 201, answer.text
    [stored] = MemoryAlignment.store.runs
    assert answer.json() == {"run": stored.to_snapshot()}
    run = answer.json()["run"]
    assert list(run) == RUN_KEYS
    assert (run["project_id"], run["from_commit"], run["to_commit"], run["commits"]) == (
        str(PROJECT),
        None,
        SECOND,
        [FIRST, SECOND],
    )
    assert (run["locale"], run["summary"], run["cost_microusd"]) == ("it-IT", ITALIAN, 0)
    assert (
        run["requirements_version_number"],
        run["design_version_number"],
        run["alternative_code"],
    ) == (1, 1, "DES-001")
    assert [(item["code"], item["section"], item["status"]) for item in run["proposals"]] == [
        ("ALN-001", "REQUIREMENTS", "PROPOSED"),
        ("ALN-002", "DESIGN", "PROPOSED"),
        ("ALN-003", "TESTS", "PROPOSED"),
    ]
    first = run["proposals"][0]
    assert first["run_id"] == run["id"]
    assert first["origin"] == {
        "commits": [FIRST, SECOND],
        "files": ["src/app.js"],
        "excerpt": "+nuovo",
    }
    assert first["subjects"] == {
        "requirements": ["REQ-001"],
        "screens": ["SCR-001"],
        "criteria": ["AC-001"],
    }
    assert (
        first["decided_at"],
        first["decision_note"],
        first["applied_text"],
        first["applied_diff_id"],
    ) == (None, None, None, None)
    [call] = studio.calls
    assert (call["task"], call["instruction"], call["retry_schema_errors"]) == (
        TASK,
        INSTRUCTION,
        False,
    )
    context = call["context"]
    assert (context["purpose"], context["locale"]) == (PURPOSE, "it-IT")
    assert context["project_brief"]["name"] == "Lista ospiti"
    assert [item["commit"] for item in context["changes"]] == [FIRST, SECOND]
    assert context["changes"][0]["diff"].startswith("diff --git a/src/app.js")
    assert context["design"]["alternative_code"] == "DES-001"
    assert [item["code"] for item in context["user_stories"]] == ["USR-001"]
    assert context["test_plan"] is None
    evidence = studio.evidence
    assert evidence.kinds() == [(0, "ADAPTER_ACCEPTED"), (0, "APPLICATION_RESULT")]
    assert evidence.payloads("ADAPTER_ACCEPTED") == [
        {"result": run, "generated_content_hashes": {PURPOSE: [snapshot_content_hash(run)]}}
    ]
    assert evidence.payloads("APPLICATION_RESULT") == [
        {"status": "KNOWLEDGE_ALIGNMENT_RECORDED", "issue": None}
    ]
    assert stored.generation_ids == tuple(evidence.generations)


def test_the_runs_and_the_proposals_are_listed_newest_first(monkeypatch):
    studio = AlignmentStudio(
        monkeypatch,
        alignment_answer(),
        alignment_answer([proposal_answer("TESTS", title="Rifare il piano dei test")]),
    )
    with studio.client() as client:
        record(client, FIRST, SECOND, THIRD)
        first = align(client, FIRST, SECOND).json()["run"]
        second = align(client, THIRD, from_commit=SECOND).json()["run"]
        listed = client.get(RUNS).json()
        single = client.get(f"{RUNS}/{first['id']}").json()
        unknown = client.get(f"{RUNS}/{UUID(int=99)}")
        waiting = client.get(PROPOSALS).json()
        skipped = client.post(f"{PROPOSALS}/ALN-002/skip", json={"reason": "Non serve."})
        after = client.get(PROPOSALS).json()
        everything = client.get(PROPOSALS, params={"status": "all"}).json()
        refused = client.get(PROPOSALS, params={"status": "open"})
    assert (second["from_commit"], second["to_commit"], second["commits"]) == (
        SECOND,
        THIRD,
        [THIRD],
    )
    assert [item["id"] for item in listed["items"]] == [second["id"], first["id"]]
    assert all("proposals" not in item for item in listed["items"])
    assert [(item["waiting"], item["proposals_count"]) for item in listed["items"]] == [
        (1, 1),
        (3, 3),
    ]
    assert listed["items"][1]["summary"] == ITALIAN
    assert single == {"run": first}
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": {"code": "KNOWLEDGE_ALIGNMENT_RUN_NOT_FOUND"}}
    assert [item["code"] for item in waiting["items"]] == [
        "ALN-004",
        "ALN-003",
        "ALN-002",
        "ALN-001",
    ]
    assert list(waiting["latest_run"]) == list(LATEST_RUN_KEYS)
    assert waiting["latest_run"] == {key: second[key] for key in LATEST_RUN_KEYS}
    assert skipped.status_code == 200
    assert [item["code"] for item in after["items"]] == ["ALN-004", "ALN-003", "ALN-001"]
    assert [(item["code"], item["status"]) for item in everything["items"]] == [
        ("ALN-004", "PROPOSED"),
        ("ALN-003", "PROPOSED"),
        ("ALN-002", "SKIPPED"),
        ("ALN-001", "PROPOSED"),
    ]
    assert refused.status_code == 422


def test_the_latest_test_plan_reaches_the_context(monkeypatch):
    studio = AlignmentStudio(monkeypatch, alignment_answer())
    MemoryPlans.store.append(sample_plan())
    with studio.client() as client:
        record(client, FIRST)
        assert align(client, FIRST).status_code == 201
    [call] = studio.calls
    plan = call["context"]["test_plan"]
    assert (plan["requirements_version_number"], plan["design_version_number"]) == (1, 4)
    assert [(item["code"], item["criteria"]) for item in plan["paths"]] == [
        ("TP-001", ["AC-001"]),
        ("TP-002", ["AC-002"]),
    ]


@pytest.mark.parametrize(
    ("setting", "status_code", "code"),
    [
        ({"requirements": False}, 409, "REQUIREMENTS_APPROVAL_REQUIRED"),
        ({"design": False}, 409, "DESIGN_APPROVAL_REQUIRED"),
        ({"model": False}, 503, "KNOWLEDGE_ALIGNMENT_MODEL_NOT_CONFIGURED"),
    ],
)
def test_a_run_refuses_an_incomplete_reference_or_a_missing_model(
    monkeypatch, setting, status_code, code
):
    studio = AlignmentStudio(monkeypatch, alignment_answer(), **setting)
    with studio.client() as client:
        record(client, FIRST)
        refused = align(client, FIRST)
        job = finished(client, studio, align(client, FIRST, headers=ASYNC))
    assert refused.status_code == status_code
    assert refused.json() == {"detail": {"code": code}}
    assert job["response"] == {"status_code": status_code, "body": {"detail": {"code": code}}}
    assert (job["operation"], job["status"]) == ("KNOWLEDGE_ALIGNMENT", "FAILED")
    assert studio.calls == []
    assert MemoryAlignment.store.runs == []
    if studio.evidence is not None:
        assert studio.evidence.events == []


def test_a_run_needs_recorded_and_unambiguous_commits(monkeypatch):
    studio = AlignmentStudio(monkeypatch, alignment_answer())
    prefix = "abcdef1"
    with studio.client() as client:
        record(client, FIRST, prefix + "0" * 33, prefix + "f" * 33)
        unknown = align(client, FIRST, "9" * 40)
        ambiguous = align(client, prefix)
        short = align(client, FIRST[:7].upper())
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": {"code": "CODE_CHANGE_NOT_FOUND"}}
    assert ambiguous.status_code == 409
    assert ambiguous.json() == {"detail": {"code": "CODE_CHANGE_AMBIGUOUS"}}
    assert short.status_code == 201, short.text
    assert (short.json()["run"]["commits"], short.json()["run"]["to_commit"]) == ([FIRST], FIRST)
    assert len(studio.calls) == 1


@pytest.mark.parametrize(
    "values",
    [
        {"commits": []},
        {"commits": [f"{index:040x}" for index in range(1, 52)], "to_commit": f"{51:040x}"},
        {"commits": ["xyz1234"], "to_commit": "xyz1234"},
        {"to_commit": FIRST},
        {"from_commit": FIRST},
        {"from_commit": SECOND[:7]},
        {"commits": [FIRST, FIRST], "to_commit": FIRST},
        {"locale": "?"},
        {"branch": "main"},
        {"to_commit": None},
    ],
)
def test_the_limits_of_a_run_request_are_refused(monkeypatch, values):
    studio = AlignmentStudio(monkeypatch, alignment_answer())
    with studio.client() as client:
        record(client, FIRST, SECOND)
        refused = align(client, **values)
    assert refused.status_code == 422
    assert refused.json()["detail"] == "invalid_request"
    assert studio.calls == []
    assert MemoryAlignment.store.runs == []


def test_an_invalid_answer_is_asked_once_more(monkeypatch):
    studio = AlignmentStudio(monkeypatch, alignment_answer(summary=ENGLISH), alignment_answer())
    with studio.client() as client:
        record(client, FIRST)
        answer = align(client, FIRST)
    assert answer.status_code == 201, answer.text
    assert len(studio.calls) == 2
    assert studio.calls[0]["context"] == studio.calls[1]["context"]
    run = answer.json()["run"]
    evidence = studio.evidence
    assert evidence.kinds() == [
        (0, "ADAPTER_REJECTED"),
        (0, "APPLICATION_RESULT"),
        (1, "ADAPTER_ACCEPTED"),
        (1, "APPLICATION_RESULT"),
    ]
    assert evidence.payloads("ADAPTER_REJECTED") == [
        {
            "code": "ALIGNMENT_LANGUAGE",
            "reason": "the alignment summary is not written in the language of the project",
        }
    ]
    assert evidence.payloads("APPLICATION_RESULT")[0] == {
        "status": "ALIGNMENT_REJECTED",
        "alignment_run_id": run["id"],
    }
    [accepted] = evidence.payloads("ADAPTER_ACCEPTED")
    assert [(item["role"], item["code"]) for item in accepted["related_generations"]] == [
        ("KNOWLEDGE_ALIGNMENT", "ALIGNMENT_REJECTED")
    ]
    assert run["generation_ids"] == [str(item) for item in evidence.generations]


def test_a_second_invalid_answer_fails_with_invalid_provider_output(monkeypatch):
    studio = AlignmentStudio(
        monkeypatch, alignment_answer(summary=ENGLISH), alignment_answer(summary=ENGLISH)
    )
    with studio.client() as client:
        record(client, FIRST)
        answer = align(client, FIRST)
    assert answer.status_code == 502
    assert answer.json() == {
        "detail": {"code": "INVALID_PROVIDER_OUTPUT", "stage": "MODEL_PROPOSAL"}
    }
    assert len(studio.calls) == 2
    assert MemoryAlignment.store.runs == []
    assert studio.evidence.events[-1][2] == {"status": "FAILED", "code": "INVALID_PROVIDER_OUTPUT"}


def test_a_run_started_as_a_job_answers_as_the_synchronous_run(monkeypatch):
    studio = AlignmentStudio(
        monkeypatch, alignment_answer(), alignment_answer([proposal_answer("TESTS")])
    )
    with studio.client() as client:
        record(client, FIRST, SECOND)
        synchronous = align(client, FIRST)
        started = align(client, SECOND, from_commit=FIRST, headers=ASYNC)
        job = finished(client, studio, started)
    assert started.headers[PREFERENCE_APPLIED] == RESPOND_ASYNC
    assert synchronous.status_code == 201
    first, second = MemoryAlignment.store.runs
    assert synchronous.json() == {"run": first.to_snapshot()}
    assert (job["kind"], job["operation"], job["status"]) == (
        "REQUEST",
        "KNOWLEDGE_ALIGNMENT",
        "SUCCEEDED",
    )
    assert job["response"] == {"status_code": 201, "body": {"run": second.to_snapshot()}}
    assert [item.code for item in second.proposals] == ["ALN-004"]
    kinds = studio.evidence.kinds()
    assert [kind for index, kind in kinds if index == 0] == [
        kind for index, kind in kinds if index == 1
    ]


ROUTES = [
    (
        "POST",
        "/alignment/runs",
        {"locale": "it-IT", "from_commit": None, "to_commit": FIRST, "commits": [FIRST]},
    ),
    ("GET", "/alignment/runs", None),
    ("GET", f"/alignment/runs/{UUID(int=7)}", None),
    ("GET", "/alignment/proposals", None),
    ("POST", "/alignment/proposals/ALN-001/apply", {"text": None}),
    ("POST", "/alignment/proposals/ALN-001/skip", {"reason": None}),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_every_route_answers_project_not_found_for_another_owner(monkeypatch, method, path, body):
    studio = AlignmentStudio(monkeypatch, alignment_answer())
    with studio.client() as client:
        record(client, FIRST)
        assert align(client, FIRST).status_code == 201
        studio.app.dependency_overrides[current_user_dependency] = lambda: account(STRANGER)
        answer = client.request(method, f"{PROJECT_PATH}{path}", json=body)
    assert answer.status_code == 404
    assert answer.json() == {"detail": {"code": "PROJECT_NOT_FOUND"}}
    assert len(studio.calls) == 1
    [run] = MemoryAlignment.store.runs
    assert all(item.waiting for item in run.proposals)


def test_a_tests_proposal_is_applied_without_a_generation(monkeypatch):
    studio = AlignmentStudio(monkeypatch, alignment_answer())
    with studio.client() as client:
        record(client, FIRST)
        run = align(client, FIRST).json()["run"]
        applied = client.post(f"{PROPOSALS}/ALN-003/apply", json={"text": None}, headers=ASYNC)
        jobs = client.get(JOBS).json()
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert list(body) == ["proposal", "revision"]
    assert body["revision"] is None
    proposal = body["proposal"]
    assert (proposal["code"], proposal["status"]) == ("ALN-003", "APPLIED")
    assert proposal["applied_text"] == run["proposals"][2]["request"]
    assert (proposal["applied_diff_id"], proposal["decision_note"]) == (None, None)
    assert proposal["decided_at"] is not None
    assert jobs == {"items": []}
    assert len(studio.calls) == 1
    [stored] = MemoryAlignment.store.runs
    assert [item.status.value for item in stored.proposals] == ["PROPOSED", "PROPOSED", "APPLIED"]


def test_a_requirements_proposal_is_applied_through_the_requirements_change(monkeypatch):
    studio = AlignmentStudio(
        monkeypatch,
        alignment_answer(
            [
                proposal_answer("REQUIREMENTS"),
                proposal_answer("REQUIREMENTS", title="La seconda richiesta della lista"),
            ]
        ),
    )
    created = Harness().run()
    service = ScriptedService(created)
    studio.runtime.requirements_change_service = service
    with studio.client() as client:
        record(client, FIRST)
        run = align(client, FIRST).json()["run"]
        applied = client.post(f"{PROPOSALS}/ALN-001/apply", json={"text": f"  {TEXT}\n"})
        job = finished(
            client, studio, client.post(f"{PROPOSALS}/ALN-002/apply", json={}, headers=ASYNC)
        )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    diff = created.revision.diff
    assert (body["proposal"]["code"], body["proposal"]["status"]) == ("ALN-001", "APPLIED")
    assert body["proposal"]["applied_text"] == TEXT
    assert body["proposal"]["applied_diff_id"] == str(diff.id)
    assert set(body["revision"]) == REVISION_KEYS
    assert body["revision"]["status"] == "CREATED"
    assert (body["revision"]["diff"]["id"], body["revision"]["diff"]["status"]) == (
        str(diff.id),
        "PROPOSED",
    )
    assert (job["operation"], job["status"]) == ("REQUIREMENTS_CHANGE", "SUCCEEDED")
    assert job["response"]["status_code"] == 200
    assert job["response"]["body"]["proposal"]["code"] == "ALN-002"
    assert job["response"]["body"]["proposal"]["applied_text"] == run["proposals"][1]["request"]
    assert service.calls == [
        {"owner_user_id": OWNER, "project_id": PROJECT, "owner_request": TEXT},
        {
            "owner_user_id": OWNER,
            "project_id": PROJECT,
            "owner_request": run["proposals"][1]["request"],
        },
    ]
    assert len(studio.calls) == 1


def test_a_refused_requirements_change_leaves_the_proposal_waiting(monkeypatch):
    studio = AlignmentStudio(monkeypatch, alignment_answer())
    service = ScriptedService(
        RequirementsChangeResult(
            status=RequirementsChangeStatus.REJECTED,
            issue=RequirementsChangeIssueCode.REVISION_PENDING,
        )
    )
    studio.runtime.requirements_change_service = service
    with studio.client() as client:
        record(client, FIRST)
        assert align(client, FIRST).status_code == 201
        refused = client.post(f"{PROPOSALS}/ALN-001/apply", json={})
        job = finished(
            client, studio, client.post(f"{PROPOSALS}/ALN-001/apply", json={}, headers=ASYNC)
        )
        studio.runtime.requirements_change_service = None
        unavailable = client.post(f"{PROPOSALS}/ALN-001/apply", json={})
        waiting = client.get(PROPOSALS).json()
    assert refused.status_code == 409
    assert refused.json() == {"detail": {"code": "REQUIREMENTS_REVISION_PENDING"}}
    assert job["response"] == {
        "status_code": 409,
        "body": {"detail": {"code": "REQUIREMENTS_REVISION_PENDING"}},
    }
    assert (job["operation"], job["status"]) == ("REQUIREMENTS_CHANGE", "FAILED")
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": {"code": "REQUIREMENTS_CHANGE_UNAVAILABLE"}}
    assert [item["code"] for item in waiting["items"]] == ["ALN-003", "ALN-002", "ALN-001"]
    assert len(service.calls) == 2


def test_a_design_proposal_is_applied_through_the_design_change(monkeypatch):
    studio = AlignmentStudio(monkeypatch, alignment_answer())
    diff = proposed_diff(design_version())
    service = ScriptedService(
        DesignChangeResult(
            status=DesignChangeStatus.CREATED,
            revision=DesignRevisionResult(status=DesignRevisionStatus.CREATED, diff=diff),
            changes=(DESIGN_CHANGE,),
        )
    )
    studio.runtime.design_change_service = service
    with studio.client() as client:
        record(client, FIRST)
        run = align(client, FIRST).json()["run"]
        job = finished(
            client,
            studio,
            client.post(f"{PROPOSALS}/ALN-002/apply", json={"locale": "en-US"}, headers=ASYNC),
        )
        refused = client.post(f"{PROPOSALS}/ALN-002/apply", json={})
    assert (job["operation"], job["status"]) == ("DESIGN_CHANGE", "SUCCEEDED")
    body = job["response"]["body"]
    assert job["response"]["status_code"] == 200
    assert (body["proposal"]["code"], body["proposal"]["status"]) == ("ALN-002", "APPLIED")
    assert body["proposal"]["applied_text"] == run["proposals"][1]["request"]
    assert body["proposal"]["applied_diff_id"] == str(diff.id)
    assert list(body["revision"]) == ["revision", "changes"]
    assert body["revision"]["changes"] == [DESIGN_CHANGE]
    assert body["revision"]["revision"]["status"] == "CREATED"
    assert body["revision"]["revision"]["diff"]["id"] == str(diff.id)
    assert service.calls == [
        {
            "owner_user_id": OWNER,
            "project_id": PROJECT,
            "owner_request": run["proposals"][1]["request"],
            "locale": "en-US",
        }
    ]
    assert refused.status_code == 409
    assert refused.json() == {"detail": {"code": "ALIGNMENT_PROPOSAL_DECIDED"}}


def test_a_refused_design_change_leaves_the_proposal_waiting(monkeypatch):
    studio = AlignmentStudio(monkeypatch, alignment_answer())
    service = ScriptedService(
        DesignChangeResult(
            status=DesignChangeStatus.REJECTED, issue=DesignChangeIssueCode.UNCHANGED
        )
    )
    studio.runtime.design_change_service = service
    with studio.client() as client:
        record(client, FIRST)
        assert align(client, FIRST).status_code == 201
        refused = client.post(f"{PROPOSALS}/ALN-002/apply", json={"text": TEXT})
        studio.runtime.design_change_service = None
        unavailable = client.post(f"{PROPOSALS}/ALN-002/apply", json={})
        waiting = client.get(PROPOSALS).json()
    assert refused.status_code == 409
    assert refused.json() == {"detail": {"code": "DESIGN_UNCHANGED"}}
    assert service.calls == [
        {"owner_user_id": OWNER, "project_id": PROJECT, "owner_request": TEXT, "locale": "it-IT"}
    ]
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": {"code": "DESIGN_CHANGE_UNAVAILABLE"}}
    assert [item["code"] for item in waiting["items"]] == ["ALN-003", "ALN-002", "ALN-001"]


def test_a_decided_proposal_is_not_decided_again(monkeypatch):
    studio = AlignmentStudio(monkeypatch, alignment_answer())
    with studio.client() as client:
        record(client, FIRST)
        assert align(client, FIRST).status_code == 201
        skipped = client.post(f"{PROPOSALS}/ALN-003/skip", json={"reason": "  Non serve ora.  "})
        again = client.post(f"{PROPOSALS}/ALN-003/skip", json={"reason": None})
        applied = client.post(f"{PROPOSALS}/aln-003/apply", json={"text": None})
        unknown = client.post(f"{PROPOSALS}/ALN-999/skip", json={})
        malformed = client.post(f"{PROPOSALS}/nope/apply", json={})
        long_reason = client.post(f"{PROPOSALS}/ALN-001/skip", json={"reason": "x" * 301})
        extra = client.post(f"{PROPOSALS}/ALN-001/skip", json={"note": "x"})
    assert skipped.status_code == 200, skipped.text
    proposal = skipped.json()["proposal"]
    assert (proposal["status"], proposal["decision_note"]) == ("SKIPPED", "Non serve ora.")
    assert (proposal["applied_text"], proposal["applied_diff_id"]) == (None, None)
    for answer in (again, applied):
        assert answer.status_code == 409
        assert answer.json() == {"detail": {"code": "ALIGNMENT_PROPOSAL_DECIDED"}}
    for answer in (unknown, malformed):
        assert answer.status_code == 404
        assert answer.json() == {"detail": {"code": "ALIGNMENT_PROPOSAL_NOT_FOUND"}}
    for answer in (long_reason, extra):
        assert answer.status_code == 422
        assert answer.json()["detail"] == "invalid_request"
    [stored] = MemoryAlignment.store.runs
    assert [item.status.value for item in stored.proposals] == ["PROPOSED", "PROPOSED", "SKIPPED"]


def test_the_text_of_an_applied_proposal_respects_the_limit_of_its_section(monkeypatch):
    studio = AlignmentStudio(monkeypatch, alignment_answer([proposal_answer("TESTS")]))
    with studio.client() as client:
        record(client, FIRST)
        run = align(client, FIRST).json()["run"]
        too_long = client.post(f"{PROPOSALS}/ALN-001/apply", json={"text": "x" * 601})
        blank = client.post(f"{PROPOSALS}/ALN-001/apply", json={"text": "   "})
    assert too_long.status_code == 422
    assert too_long.json()["detail"] == "invalid_request"
    assert blank.status_code == 200, blank.text
    assert blank.json()["proposal"]["applied_text"] == run["proposals"][0]["request"]
