from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from orchestwin.api import code_changes
from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.code_changes import (
    ChangeReviewRequest,
    ChangeReviewStatus,
    CodeChangeApplication,
    create_code_change_router,
)
from orchestwin.api.generation_requests import PREFERENCE_APPLIED, RESPOND_ASYNC
from orchestwin.api.services import ApplicationRuntime
from orchestwin.artifacts.design_gate import design_artifact_reference
from orchestwin.config import ApplicationSettings
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.knowledge.state import MAX_TASK_LENGTH
from orchestwin.models.change_review import (
    ALIGNMENT_INSTRUCTION,
    ALIGNMENT_PURPOSE,
    CHANGE_REVIEW_TASK,
    CRITIQUE_INSTRUCTION,
    CRITIQUE_PURPOSE,
    DIFF_CUT_LINE,
    LEARNED_INSTRUCTION,
)
from orchestwin.models.proposal_evidence import ProposalEvidenceError, begin_model_generation
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.projects.briefs import create_project_brief
from orchestwin.projects.code_changes import (
    CodeChangeAmbiguous,
    CodeTask,
    TaskOrigin,
    TaskStatus,
    aligned_change,
    commit_prefix,
    pending_changes,
)
from orchestwin.projects.persistence.code_changes import (
    CodeChangeWriteResult,
    CodeChangeWriteStatus,
    CreatedTasks,
)
from orchestwin.projects.requirements_gate import requirements_artifact_reference
from orchestwin.projects.requirements_primitives import snapshot_content_hash
from orchestwin.projects.twin_learning import LearnedObservation, LearningSource
from orchestwin.twins.user_modeling_gate import user_modeling_artifact_reference
from orchestwin.workflow.gates import (
    HumanGateAction,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)
from src.test.python.artifacts import design_fixtures
from src.test.python.projects.test_acceptance_tests import RUN_ID as TEST_RUN_ID
from src.test.python.projects.test_acceptance_tests import (
    sample_critique,
    sample_finding,
    sample_review,
    sample_run,
)
from src.test.python.projects.test_code_changes import TWIN_ONE, critique, finding, review_run
from src.test.python.twins.test_user_modeling_gate import snapshot_version

PREFIX = "/api/v1"
OWNER = design_fixtures.OWNER_ID
PROJECT = design_fixtures.PROJECT_ID
STRANGER = UUID("00000000-0000-4000-8000-00000000ffff")
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
PROJECT_PATH = f"{PREFIX}/projects/{PROJECT}"
CHANGES = f"{PROJECT_PATH}/code-changes"
ALIGNMENT = f"{PROJECT_PATH}/alignment"
TASKS = f"{PROJECT_PATH}/code-tasks"
JOBS = f"{PROJECT_PATH}/generation-jobs"
ASYNC = {"Prefer": RESPOND_ASYNC}
FIRST = "a1" * 20
SECOND = "b2" * 20
THIRD = "c3" * 20
TWIN_TWO = UUID("00000000-0000-4000-8000-000000000b02")
BRIEF = create_project_brief(
    name="Lista ospiti",
    problem="La reception perde le prenotazioni.",
    goals=("Registrare gli ospiti in fretta",),
)
ITALIAN = "La modifica mi aiuta, ma il modulo non chiede la data di arrivo che uso."
ENGLISH = "The change helps me but the form is missing the date that I need every day."
ENGLISH_FINDING = "The form does not ask for the arrival date that I need for every guest."
ENGLISH_TASK = "Restore the save button that the change removed from the form."
REVIEW = {"locale": "it-IT", "again": False}


def payload(commit=FIRST, **values):
    body = {
        "commit": commit,
        "parent": None,
        "committed_at": "2026-09-29T14:00:00+02:00",
        "author": "Ada Lovelace",
        "message": "Aggiunge la lista degli ospiti",
        "files": [{"path": "src/app.js", "kind": "MODIFIED", "added": 12, "removed": 3}],
        "diff": "diff --git a/src/app.js b/src/app.js\n+nuovo\n",
    }
    body.update(values)
    return body


def finding_answer(**values):
    answer = {
        "about_file": "src/app.js",
        "about_requirement": "REQ-001",
        "about_screen": "SCR-001",
        "problem": "Il modulo non chiede la data di arrivo.",
        "severity": "MEDIUM",
        "suggestion": "Aggiungere il campo della data.",
    }
    answer.update(values)
    return answer


def critique_answer(summary=ITALIAN, **values):
    answer = {"assessment": "CONCERN", "comment": summary, "findings": [finding_answer()]}
    answer.update(values)
    return answer


def fine_answer():
    return critique_answer(
        "La modifica va bene per il mio turno di notte.", assessment="FINE", findings=[]
    )


def verdict_answer(status="ALIGNED", **values):
    answer = {
        "conclusion": status,
        "explanation": "Il codice segue il design approvato e i requisiti della prenotazione.",
        "impacted_requirements": ["REQ-001"],
        "impacted_screens": ["SCR-001"],
        "next_design_request": None,
        "next_requirements_request": None,
        "tasks_for_code": [],
    }
    if status == "CODE_DRIFT":
        answer["tasks_for_code"] = ["Ripristinare il pulsante di salvataggio."]
    if status == "DESIGN_OUTDATED":
        answer["next_design_request"] = "Aggiungere al design la schermata degli arrivi del giorno."
    if status == "REQUIREMENTS_OUTDATED":
        answer["next_requirements_request"] = "Aggiungere il requisito della data di arrivo."
    answer.update(values)
    return answer


def review_answers(status="ALIGNED"):
    return (critique_answer(), fine_answer(), verdict_answer(status))


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


class FakeSession:
    def begin(self):
        return FakeTransaction()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


class MemoryStore:
    def __init__(self):
        self.projects = {PROJECT}
        self.changes = []
        self.runs = []
        self.tasks = []
        self.creations = []


class MemoryChanges:
    store: ClassVar[MemoryStore] = MemoryStore()

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    def _owned(self, project_id):
        return self.owner_user_id == OWNER and project_id in self.store.projects

    def _view(self, change, *, with_diff):
        runs = [run for run in self.store.runs if run.change_id == change.id]
        viewed = change.with_review(runs[-1].summary() if runs else None)
        return viewed if with_diff else replace(viewed, diff=None)

    def _newest_first(self, project_id):
        if not self._owned(project_id):
            return []
        return [item for item in reversed(self.store.changes) if item.project_id == project_id]

    async def project_exists(self, project_id):
        return self._owned(project_id)

    async def record(self, change):
        if change.owner_user_id != self.owner_user_id or not self._owned(change.project_id):
            return CodeChangeWriteResult(CodeChangeWriteStatus.PROJECT_NOT_FOUND)
        for stored in self._newest_first(change.project_id):
            if stored.commit == change.commit:
                return CodeChangeWriteResult(
                    CodeChangeWriteStatus.ALREADY_RECORDED, self._view(stored, with_diff=True)
                )
        self.store.changes.append(change)
        return CodeChangeWriteResult(CodeChangeWriteStatus.RECORDED, change)

    async def list(self, project_id, *, pending_only=False, limit=200):
        items = self._newest_first(project_id)
        if pending_only:
            items = list(pending_changes(items))
        if limit is not None:
            items = items[:limit]
        return tuple(self._view(item, with_diff=False) for item in items)

    async def count(self, project_id, *, pending_only=False):
        return len(await self.list(project_id, pending_only=pending_only, limit=None))

    async def get(self, project_id, commit_or_prefix):
        prefix = commit_prefix(commit_or_prefix)
        if prefix is None:
            return None
        items = self._newest_first(project_id)
        exact = [item for item in items if item.commit == prefix]
        if exact:
            return self._view(exact[0], with_diff=True)
        matches = [item for item in items if item.commit.startswith(prefix)]
        if len(matches) > 1:
            raise CodeChangeAmbiguous(prefix)
        return self._view(matches[0], with_diff=True) if matches else None

    async def runs(self, change_id):
        return tuple(reversed([run for run in self.store.runs if run.change_id == change_id]))

    async def latest_run(self, change_id):
        runs = await self.runs(change_id)
        return runs[0] if runs else None

    async def create_run(self, run):
        if run.owner_user_id != self.owner_user_id or not self._owned(run.project_id):
            return CodeChangeWriteStatus.PROJECT_NOT_FOUND
        if not any(item.id == run.change_id for item in self.store.changes):
            return CodeChangeWriteStatus.CHANGE_NOT_FOUND
        self.store.runs.append(run)
        return CodeChangeWriteStatus.RECORDED

    async def decide(self, change_id, decision, *, aligned_versions=(None, None)):
        for index, item in enumerate(self.store.changes):
            if item.id == change_id:
                decided = item.with_decision(
                    decision,
                    requirements_version=aligned_versions[0],
                    design_version=aligned_versions[1],
                )
                self.store.changes[index] = decided
                return self._view(decided, with_diff=True)
        return None

    async def aligned_point(self, project_id):
        change = aligned_change(self._newest_first(project_id))
        return None if change is None else change.aligned_point()

    async def tasks(self, project_id, *, open_only=False):
        if not self._owned(project_id):
            return ()
        return tuple(
            task
            for task in sorted(self.store.tasks, key=lambda item: item.number)
            if task.project_id == project_id and (task.open or not open_only)
        )

    async def task(self, project_id, number):
        return next((task for task in await self.tasks(project_id) if task.number == number), None)

    async def create_tasks(self, project_id, sources, *, created_at):
        self.store.creations.append(tuple(sources))
        known = {
            task.source_key: task
            for task in await self.tasks(project_id, open_only=True)
            if task.source_key is not None
        }
        number = max((task.number for task in self.store.tasks), default=0)
        tasks = []
        created = 0
        for source in sources:
            if source.key is not None and source.key in known:
                tasks.append(known[source.key])
                continue
            number += 1
            task = CodeTask.from_source(
                source,
                task_id=uuid4(),
                project_id=project_id,
                owner_user_id=self.owner_user_id,
                number=number,
                created_at=created_at,
            )
            self.store.tasks.append(task)
            if task.source_key is not None:
                known[task.source_key] = task
            tasks.append(task)
            created += 1
        return CreatedTasks(tasks=tuple(tasks), created=created)

    async def set_task_status(self, project_id, number, status, *, at, note=None):
        for index, task in enumerate(self.store.tasks):
            if task.project_id == project_id and task.number == number:
                self.store.tasks[index] = task.with_status(status, at=at, note=note)
                return self.store.tasks[index]
        return None

    async def close_open_tasks(self, project_id, aligned_change_id, closed_at):
        recorded = [item for item in self.store.changes if item.project_id == project_id]
        identifiers = [item.id for item in recorded]
        if aligned_change_id not in identifiers:
            return 0
        place = identifiers.index(aligned_change_id)
        covered = set(identifiers[: place + 1])
        moment = recorded[place].recorded_at
        closed = 0
        for index, task in enumerate(self.store.tasks):
            if task.project_id != project_id or not task.open:
                continue
            if task.from_change_id in covered or (
                task.origin is not TaskOrigin.CODE_CHANGE and task.created_at <= moment
            ):
                self.store.tasks[index] = task.done(closed_at)
                closed += 1
        return closed


class MemoryLearning:
    learned: ClassVar[dict] = {}

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def active(self, project_id):
        if self.owner_user_id != OWNER or project_id != PROJECT:
            return {}
        return dict(self.learned)


class MemoryRuns:
    store: ClassVar[list] = []

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def run(self, project_id, run_id):
        if self.owner_user_id != OWNER:
            return None
        return next(
            (item for item in self.store if item.id == run_id and item.project_id == project_id),
            None,
        )


class MemoryEvidence:
    def __init__(self):
        self.generations = []
        self.events = []

    async def begin(self, *, owner_user_id, project_id, request):
        self.generations.append(request.request_id)

    async def append(self, *, generation_id, kind, payload, **_):
        self.events.append((self.generations.index(generation_id), kind, payload))

    def kinds(self):
        return [(index, kind) for index, kind, _ in self.events]

    def payloads(self, kind):
        return [payload for _, observed, payload in self.events if observed == kind]


class CostedEvidence(MemoryEvidence):
    async def get_owned(self, *, owner_user_id, project_id, generation_id):
        assert (owner_user_id, project_id) == (OWNER, PROJECT)
        index = self.generations.index(generation_id)
        if index == 1:
            raise ProposalEvidenceError("PROPOSAL_EVIDENCE_HASH_MISMATCH")
        if index == 3:
            return None
        usage = {
            0: {"success": {"usage": {"cost_microusd": 200_000}}},
            2: {
                "success": {"usage": {"cost_microusd": 250_000}},
                "failure": {"usage": {"cost_microusd": 50_000}},
            },
        }[index]
        return {
            "observations": [
                {"kind": "HTTP_REQUEST", "payload": {"cost_microusd": 999}},
                {"kind": "PROVIDER_RESULT", "payload": usage},
            ]
        }


class FakeGenerator:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.configuration = SimpleNamespace(max_output_tokens=8192)

    def route(self, task, purpose=None):
        return self

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        await begin_model_generation(SimpleNamespace(request_id=uuid4(), content_hash="d" * 64))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        try:
            return kwargs["output_type"].model_validate(outcome)
        except ValidationError as error:
            raise ProposalGenerationError("RESPONSE_SCHEMA_ERROR") from error


def approved(version, gate_type, reference):
    draft = create_human_gate(
        project_id=version.project_id,
        owner_user_id=OWNER,
        gate_type=gate_type,
        artifact=reference,
        created_at=NOW,
    )
    submitted = transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER,
        occurred_at=NOW + timedelta(minutes=1),
    )
    return transition_human_gate(
        submitted.gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER,
        occurred_at=NOW + timedelta(minutes=2),
    ).gate


def first_twin():
    return snapshot_version().snapshot.twin_versions[0]


def second_twin():
    return SimpleNamespace(
        twin_id=TWIN_TWO,
        version_number=1,
        content_hash="e" * 64,
        profile=SimpleNamespace(
            name="Night Auditor Twin",
            to_snapshot=lambda: {"name": "Night Auditor Twin", "observations": []},
        ),
    )


def account(user_id=OWNER):
    return UserAccount(
        id=user_id,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


async def nothing(*_args, **_kwargs):
    return None


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
        MemoryChanges.store = MemoryStore()
        MemoryRuns.store = []
        monkeypatch.setattr(code_changes, "SqlAlchemyCodeChangeRepository", MemoryChanges)
        monkeypatch.setattr(code_changes, "SqlAlchemyAcceptanceTestRepository", MemoryRuns)
        monkeypatch.setattr(MemoryLearning, "learned", dict(learned or {}))
        monkeypatch.setattr(code_changes, "SqlAlchemyTwinLearningRepository", MemoryLearning)
        self.generator = FakeGenerator(*outcomes) if model else None
        self.evidence = (MemoryEvidence() if evidence is None else evidence) if model else None
        self.requirements = design_fixtures.requirements_version()
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
        return CodeChangeApplication(self.runtime)


def record(client, *commits):
    for minutes, commit in enumerate(commits):
        answer = client.post(
            CHANGES,
            json=payload(commit, committed_at=f"2026-09-29T10:{minutes:02d}:00+00:00"),
        )
        assert answer.status_code == 201, answer.text


def review(client, commit=FIRST, **values):
    return client.post(f"{CHANGES}/{commit}/reviews", json={**REVIEW, **values})


def decide(client, commit, **body):
    return client.post(f"{CHANGES}/{commit}/decision", json=body)


def test_router_registers_the_routes():
    router = create_code_change_router()
    assert sorted(route.path for route in router.routes) == [
        "/projects/{project_id}/alignment",
        "/projects/{project_id}/code-changes",
        "/projects/{project_id}/code-changes",
        "/projects/{project_id}/code-changes/{commit}",
        "/projects/{project_id}/code-changes/{commit}/decision",
        "/projects/{project_id}/code-changes/{commit}/reviews",
        "/projects/{project_id}/code-changes/{commit}/reviews",
        "/projects/{project_id}/code-tasks",
        "/projects/{project_id}/code-tasks",
        "/projects/{project_id}/code-tasks/{code}/status",
    ]
    methods = sorted(
        (route.path.removeprefix("/projects/{project_id}"), *sorted(route.methods))
        for route in router.routes
    )
    assert methods == [
        ("/alignment", "GET"),
        ("/code-changes", "GET"),
        ("/code-changes", "POST"),
        ("/code-changes/{commit}", "GET"),
        ("/code-changes/{commit}/decision", "POST"),
        ("/code-changes/{commit}/reviews", "GET"),
        ("/code-changes/{commit}/reviews", "POST"),
        ("/code-tasks", "GET"),
        ("/code-tasks", "POST"),
        ("/code-tasks/{code}/status", "POST"),
    ]


def test_a_commit_is_recorded_once_and_the_same_commit_again_changes_nothing(monkeypatch):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        created = client.post(CHANGES, json=payload(FIRST.upper(), parent=SECOND.upper()))
        again = client.post(CHANGES, json=payload(FIRST, message="Un altro messaggio"))
        listed = client.get(CHANGES).json()
    assert created.status_code == 201
    change = created.json()["change"]
    assert created.json()["status"] == "RECORDED"
    assert change == {
        "commit": FIRST,
        "parent": SECOND,
        "committed_at": "2026-09-29T12:00:00+00:00",
        "author": "Ada Lovelace",
        "message": "Aggiunge la lista degli ospiti",
        "files": [{"path": "src/app.js", "kind": "MODIFIED", "added": 12, "removed": 3}],
        "recorded_at": change["recorded_at"],
        "review": None,
        "decision": None,
    }
    assert datetime.fromisoformat(change["recorded_at"]).utcoffset() == timedelta(0)
    assert again.status_code == 200
    assert again.json() == {"status": "ALREADY_RECORDED", "change": change}
    assert listed == {"items": [change]}
    [stored] = MemoryChanges.store.changes
    assert stored.diff == "diff --git a/src/app.js b/src/app.js\n+nuovo\n"


@pytest.mark.parametrize(
    "values",
    [
        {"commit": "abcdef"},
        {"commit": "a" * 65},
        {"commit": "xyz1234"},
        {"parent": "123"},
        {"parent": FIRST.upper()},
        {"committed_at": "2026-09-29T14:00:00"},
        {"committed_at": "yesterday"},
        {"author": "x" * 201},
        {"message": ""},
        {"message": "   "},
        {"message": "x" * 2001},
        {"message": "a\x00b"},
        {"files": [{"path": "src/app.js", "kind": "MODIFIED", "added": 1, "removed": 0}] * 501},
        {"files": [{"path": "x" * 501, "kind": "ADDED", "added": 1, "removed": 0}]},
        {"files": [{"path": "src/\napp.js", "kind": "ADDED", "added": 1, "removed": 0}]},
        {"files": [{"path": "src/app.js", "kind": "COPIED", "added": 1, "removed": 0}]},
        {"files": [{"path": "src/app.js", "kind": "ADDED", "added": -1, "removed": 0}]},
        {"files": [{"path": "src/app.js", "kind": "ADDED", "added": 1}]},
        {"diff": "x" * 65537},
        {"diff": "a\x00b"},
        {"branch": "main"},
    ],
)
def test_the_limits_of_a_recorded_commit_are_refused(monkeypatch, values):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        refused = client.post(CHANGES, json=payload(**values))
    assert refused.status_code == 422
    assert refused.json()["detail"] == "invalid_request"
    assert MemoryChanges.store.changes == []


def test_a_commit_at_the_limits_is_recorded(monkeypatch):
    studio = Studio(monkeypatch)
    files = [
        {"path": f"src/{index}.js", "kind": "ADDED", "added": 1, "removed": 0}
        for index in range(500)
    ]
    with studio.client() as client:
        answer = client.post(
            CHANGES,
            json=payload(
                "a" * 64,
                parent="b" * 7,
                author="   ",
                message="x" * 2000,
                files=files,
                diff="y" * 65536,
            ),
        )
        missing = client.post(
            CHANGES,
            json={
                key: value
                for key, value in payload(SECOND).items()
                if key not in {"parent", "author", "files", "diff"}
            },
        )
    assert answer.status_code == 201
    assert answer.json()["change"]["author"] is None
    assert len(answer.json()["change"]["files"]) == 500
    assert missing.status_code == 201
    assert missing.json()["change"]["files"] == []


ROUTES = [
    ("GET", "/alignment", None),
    ("POST", "/code-changes", payload()),
    ("GET", "/code-changes", None),
    ("GET", f"/code-changes/{FIRST}", None),
    ("POST", f"/code-changes/{FIRST}/reviews", REVIEW),
    ("GET", f"/code-changes/{FIRST}/reviews", None),
    ("POST", f"/code-changes/{FIRST}/decision", {"kind": "DISMISSED"}),
    ("GET", "/code-tasks", None),
    ("POST", "/code-tasks", {"tasks": [{"text": "Un compito.", "source": {"kind": "OWNER"}}]}),
    ("POST", "/code-tasks/TSK-001/status", {"status": "DONE"}),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_every_route_answers_project_not_found_for_another_owner(monkeypatch, method, path, body):
    studio = Studio(monkeypatch, *review_answers())
    with studio.client() as client:
        record(client, FIRST)
        assert decide(client, FIRST, kind="CODE_TASKS", tasks=["Un compito."]).status_code == 200
        studio.app.dependency_overrides[current_user_dependency] = lambda: account(STRANGER)
        answer = client.request(method, f"{PROJECT_PATH}{path}", json=body)
    assert answer.status_code == 404
    assert answer.json() == {"detail": {"code": "PROJECT_NOT_FOUND"}}
    assert studio.calls == []
    assert len(MemoryChanges.store.changes) == 1
    [task] = MemoryChanges.store.tasks
    assert task.open


def test_the_changes_are_listed_newest_first_and_the_pending_ones_follow_the_aligned_point(
    monkeypatch,
):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        record(client, FIRST, SECOND, THIRD)
        before = client.get(CHANGES, params={"pending": "true"}).json()
        assert decide(client, SECOND, kind="ALIGNED").status_code == 200
        listed = client.get(CHANGES).json()
        pending = client.get(CHANGES, params={"pending": "true"}).json()
        alignment = client.get(ALIGNMENT).json()
    assert [item["commit"] for item in before["items"]] == [THIRD, SECOND, FIRST]
    assert [item["commit"] for item in listed["items"]] == [THIRD, SECOND, FIRST]
    assert all("diff" not in item for item in listed["items"])
    assert [item["commit"] for item in pending["items"]] == [THIRD]
    assert alignment["pending_changes"] == 1
    assert alignment["latest_change"]["commit"] == THIRD
    assert alignment["aligned"]["commit"] == SECOND


def test_a_change_is_read_by_its_hash_or_a_prefix_with_its_diff(monkeypatch):
    studio = Studio(monkeypatch)
    twin_prefix = "abcdef1"
    with studio.client() as client:
        record(client, FIRST, twin_prefix + "0" * 33, twin_prefix + "f" * 33)
        full = client.get(f"{CHANGES}/{FIRST}")
        short = client.get(f"{CHANGES}/{FIRST[:7].upper()}")
        longer = client.get(f"{CHANGES}/{twin_prefix}0")
        ambiguous = client.get(f"{CHANGES}/{twin_prefix.upper()}")
        unknown = client.get(f"{CHANGES}/{'9' * 40}")
        too_short = client.get(f"{CHANGES}/{FIRST[:6]}")
        not_hex = client.get(f"{CHANGES}/zzzzzzz")
    assert full.status_code == short.status_code == longer.status_code == 200
    assert full.json() == short.json()
    assert full.json()["commit"] == FIRST
    assert full.json()["diff"] == "diff --git a/src/app.js b/src/app.js\n+nuovo\n"
    assert list(full.json())[-1] == "diff"
    assert longer.json()["commit"] == twin_prefix + "0" * 33
    assert ambiguous.status_code == 409
    assert ambiguous.json() == {"detail": {"code": "CODE_CHANGE_AMBIGUOUS"}}
    for answer in (unknown, too_short, not_hex):
        assert answer.status_code == 404
        assert answer.json() == {"detail": {"code": "CODE_CHANGE_NOT_FOUND"}}


def test_a_review_asks_every_approved_twin_then_the_verdict_and_stores_the_run(monkeypatch):
    studio = Studio(monkeypatch, *review_answers())
    with studio.client() as client:
        record(client, FIRST)
        answer = review(client)
        reviews = client.get(f"{CHANGES}/{FIRST}/reviews").json()
        listed = client.get(CHANGES).json()
    assert answer.status_code == 201, answer.text
    body = answer.json()
    assert body["status"] == "REVIEWED"
    [run] = MemoryChanges.store.runs
    assert body["run"] == run.to_snapshot()
    assert reviews == {"items": [run.to_snapshot()]}
    snapshot = body["run"]
    assert (snapshot["commit"], snapshot["locale"], snapshot["cost_microusd"]) == (
        FIRST,
        "it-IT",
        0,
    )
    assert snapshot["reference"] == {
        "requirements_version_number": 1,
        "design_version_number": 1,
        "alternative_code": "DES-001",
    }
    assert [item["twin_name"] for item in snapshot["critiques"]] == [
        "Receptionist Twin",
        "Night Auditor Twin",
    ]
    assert snapshot["critiques"][0]["findings"] == [
        {
            "severity": "MEDIUM",
            "text": "Il modulo non chiede la data di arrivo.",
            "about": {"requirement": "REQ-001", "screen": "SCR-001", "file": "src/app.js"},
            "action": "Aggiungere il campo della data.",
        }
    ]
    assert snapshot["alignment"]["status"] == "ALIGNED"
    assert listed["items"][0]["review"] == {
        "run_id": snapshot["id"],
        "reviewed_at": snapshot["reviewed_at"],
        "verdict": "ALIGNED",
        "summary": snapshot["alignment"]["summary"],
        "reference": snapshot["reference"],
        "stale": False,
    }
    calls = studio.calls
    assert [call["task"] for call in calls] == [CHANGE_REVIEW_TASK] * 3
    assert [call["context"]["purpose"] for call in calls] == [
        CRITIQUE_PURPOSE,
        CRITIQUE_PURPOSE,
        ALIGNMENT_PURPOSE,
    ]
    assert [call["context"]["user_twin"]["twin_id"] for call in calls[:2]] == [
        str(first_twin().twin_id),
        str(TWIN_TWO),
    ]
    assert {call["retry_schema_errors"] for call in calls} == {False}
    critique_context, _, verdict_context = (call["context"] for call in calls)
    assert critique_context["locale"] == "it-IT"
    assert critique_context["project_brief"]["name"] == "Lista ospiti"
    assert critique_context["change"]["commit"] == FIRST
    assert critique_context["design"]["alternative_code"] == "DES-001"
    assert critique_context["earlier_findings"] == []
    assert critique_context["earlier_source"] is None
    assert [item["twin_name"] for item in verdict_context["critiques"]] == [
        "Receptionist Twin",
        "Night Auditor Twin",
    ]
    assert verdict_context["open_tasks"] == []
    evidence = studio.evidence
    assert evidence.kinds() == [
        (0, "ADAPTER_ACCEPTED"),
        (0, "APPLICATION_RESULT"),
        (1, "ADAPTER_ACCEPTED"),
        (1, "APPLICATION_RESULT"),
        (2, "ADAPTER_ACCEPTED"),
        (2, "APPLICATION_RESULT"),
    ]
    assert evidence.payloads("APPLICATION_RESULT") == [
        {"status": "TWIN_CRITIQUED", "review_run_id": snapshot["id"]},
        {"status": "TWIN_CRITIQUED", "review_run_id": snapshot["id"]},
        {"status": ChangeReviewStatus.REVIEWED.value, "issue": None},
    ]
    first, second, verdict = evidence.payloads("ADAPTER_ACCEPTED")
    assert first == {
        "result": snapshot["critiques"][0],
        "generated_content_hashes": {
            CRITIQUE_PURPOSE: [snapshot_content_hash(snapshot["critiques"][0])]
        },
    }
    assert second["related_generations"] == [
        {
            "role": "CHANGE_CRITIQUE",
            "generation_id": str(evidence.generations[0]),
            "request_hash": "d" * 64,
            "code": "TWIN_CRITIQUED",
        }
    ]
    assert verdict["result"] == snapshot["alignment"]
    assert verdict["generated_content_hashes"] == {
        ALIGNMENT_PURPOSE: [snapshot_content_hash(snapshot["alignment"])]
    }
    assert [item["generation_id"] for item in verdict["related_generations"]] == [
        str(item) for item in evidence.generations[:2]
    ]
    assert run.generation_ids == tuple(evidence.generations)


def test_a_review_started_as_a_job_answers_as_the_synchronous_review(monkeypatch):
    studio = Studio(monkeypatch, *review_answers(), *review_answers("CODE_DRIFT"))
    with studio.client() as client:
        record(client, FIRST)
        synchronous = review(client)
        started = client.post(
            f"{CHANGES}/{FIRST}/reviews", json={**REVIEW, "again": True}, headers=ASYNC
        )
        assert started.status_code == 202, started.text
        job_id = started.json()["job_id"]
        client.portal.call(studio.app.state.generation_jobs.wait, UUID(job_id))
        job = client.get(f"{JOBS}/{job_id}").json()
    assert started.headers[PREFERENCE_APPLIED] == RESPOND_ASYNC
    assert synchronous.status_code == 201
    assert (job["kind"], job["operation"], job["status"]) == (
        "REQUEST",
        "CODE_CHANGE_REVIEW",
        "SUCCEEDED",
    )
    first, second = MemoryChanges.store.runs
    assert synchronous.json() == {"status": "REVIEWED", "run": first.to_snapshot()}
    assert job["response"] == {
        "status_code": 201,
        "body": {"status": "REVIEWED", "run": second.to_snapshot()},
    }
    assert second.alignment.status.value == "CODE_DRIFT"
    kinds = studio.evidence.kinds()
    assert [kind for index, kind in kinds if index < 3] == [
        kind for index, kind in kinds if index >= 3
    ]


def test_a_second_review_needs_again_and_the_runs_are_listed_newest_first(monkeypatch):
    studio = Studio(monkeypatch, *review_answers(), *review_answers("DESIGN_OUTDATED"))
    with studio.client() as client:
        record(client, FIRST)
        assert review(client).status_code == 201
        refused = review(client)
        again = review(client, again=True)
        runs = client.get(f"{CHANGES}/{FIRST}/reviews").json()["items"]
        latest = client.get(f"{CHANGES}/{FIRST}").json()
    assert refused.status_code == 409
    assert refused.json() == {"detail": {"code": "CODE_CHANGE_REVIEW_EXISTS"}}
    assert again.status_code == 201
    assert [item["alignment"]["status"] for item in runs] == ["DESIGN_OUTDATED", "ALIGNED"]
    assert runs[0]["alignment"]["design_request"] == (
        "Aggiungere al design la schermata degli arrivi del giorno."
    )
    assert latest["review"]["run_id"] == runs[0]["id"]
    assert len(studio.calls) == 6


@pytest.mark.parametrize(
    ("setting", "status_code", "code"),
    [
        ({"requirements": False}, 409, "REQUIREMENTS_APPROVAL_REQUIRED"),
        ({"design": False}, 409, "DESIGN_APPROVAL_REQUIRED"),
        ({"modeling": False}, 409, "USER_MODELING_APPROVAL_REQUIRED"),
        ({"model": False}, 503, "CHANGE_REVIEW_MODEL_NOT_CONFIGURED"),
    ],
)
def test_a_review_refuses_an_incomplete_reference_or_a_missing_model(
    monkeypatch, setting, status_code, code
):
    studio = Studio(monkeypatch, *review_answers(), **setting)
    with studio.client() as client:
        record(client, FIRST)
        refused = review(client)
        started = client.post(f"{CHANGES}/{FIRST}/reviews", json=REVIEW, headers=ASYNC)
        client.portal.call(studio.app.state.generation_jobs.wait, UUID(started.json()["job_id"]))
        job = client.get(f"{JOBS}/{started.json()['job_id']}").json()
    assert refused.status_code == status_code
    assert refused.json() == {"detail": {"code": code}}
    assert job["response"] == {"status_code": status_code, "body": {"detail": {"code": code}}}
    assert job["status"] == "FAILED"
    assert studio.calls == []
    assert MemoryChanges.store.runs == []
    if studio.evidence is not None:
        assert studio.evidence.events == []


@pytest.mark.parametrize(
    ("setting", "commit", "status_code", "code"),
    [
        ({"model": False, "requirements": False}, "9" * 40, 404, "CODE_CHANGE_NOT_FOUND"),
        ({"model": False, "modeling": False}, FIRST, 409, "CODE_CHANGE_REVIEW_EXISTS"),
        ({"requirements": False, "modeling": False}, SECOND, 409, "REQUIREMENTS_APPROVAL_REQUIRED"),
        ({"design": False, "modeling": False}, SECOND, 409, "DESIGN_APPROVAL_REQUIRED"),
        ({"model": False, "modeling": False}, SECOND, 409, "USER_MODELING_APPROVAL_REQUIRED"),
    ],
)
def test_the_refusals_come_in_the_order_of_the_contract(
    monkeypatch, setting, commit, status_code, code
):
    studio = Studio(monkeypatch, **setting)
    with studio.client() as client:
        record(client, FIRST, SECOND)
        MemoryChanges.store.runs.append(review_run(MemoryChanges.store.changes[0]))
        refused = review(client, commit)
    assert refused.status_code == status_code
    assert refused.json() == {"detail": {"code": code}}


def test_an_invalid_critique_is_generated_once_more(monkeypatch):
    studio = Studio(monkeypatch, critique_answer(ENGLISH), *review_answers())
    with studio.client() as client:
        record(client, FIRST)
        answer = review(client)
    assert answer.status_code == 201, answer.text
    assert len(studio.calls) == 4
    assert studio.calls[0]["context"] == studio.calls[1]["context"]
    [run] = MemoryChanges.store.runs
    assert run.critiques[0].summary == ITALIAN
    evidence = studio.evidence
    assert evidence.kinds() == [
        (0, "ADAPTER_REJECTED"),
        (0, "APPLICATION_RESULT"),
        (1, "ADAPTER_ACCEPTED"),
        (1, "APPLICATION_RESULT"),
        (2, "ADAPTER_ACCEPTED"),
        (2, "APPLICATION_RESULT"),
        (3, "ADAPTER_ACCEPTED"),
        (3, "APPLICATION_RESULT"),
    ]
    assert evidence.events[0][2] == {
        "code": "ValueError",
        "reason": "the critique summary is not written in the language of the project",
    }
    assert evidence.events[1][2] == {"status": "CRITIQUE_REJECTED", "review_run_id": str(run.id)}
    assert run.generation_ids == tuple(evidence.generations)
    related = evidence.payloads("ADAPTER_ACCEPTED")[0]["related_generations"]
    assert [(item["role"], item["code"]) for item in related] == [
        ("CHANGE_CRITIQUE", "CRITIQUE_REJECTED")
    ]


def test_an_invalid_verdict_is_generated_once_more(monkeypatch):
    studio = Studio(
        monkeypatch,
        critique_answer(),
        fine_answer(),
        verdict_answer("DESIGN_OUTDATED", next_design_request=None),
        verdict_answer("DESIGN_OUTDATED"),
    )
    with studio.client() as client:
        record(client, FIRST)
        answer = review(client)
    assert answer.status_code == 201, answer.text
    assert answer.json()["run"]["alignment"]["design_request"] == (
        "Aggiungere al design la schermata degli arrivi del giorno."
    )
    assert studio.calls[2]["context"] == studio.calls[3]["context"]
    rejected = studio.evidence.payloads("APPLICATION_RESULT")[2]
    assert rejected == {"status": "CRITIQUE_REJECTED", "review_run_id": answer.json()["run"]["id"]}
    related = studio.evidence.payloads("ADAPTER_ACCEPTED")[-1]["related_generations"]
    assert [(item["role"], item["code"]) for item in related] == [
        ("CHANGE_CRITIQUE", "TWIN_CRITIQUED"),
        ("CHANGE_CRITIQUE", "TWIN_CRITIQUED"),
        ("CHANGE_ALIGNMENT", "CRITIQUE_REJECTED"),
    ]


def test_a_second_invalid_answer_fails_with_invalid_provider_output(monkeypatch):
    studio = Studio(monkeypatch, critique_answer(ENGLISH), critique_answer(ENGLISH))
    with studio.client() as client:
        record(client, FIRST)
        answer = review(client)
    assert answer.status_code == 502
    assert answer.json() == {
        "detail": {"code": "INVALID_PROVIDER_OUTPUT", "stage": "MODEL_PROPOSAL"}
    }
    assert len(studio.calls) == 2
    assert MemoryChanges.store.runs == []
    assert studio.evidence.kinds() == [
        (0, "ADAPTER_REJECTED"),
        (0, "APPLICATION_RESULT"),
        (1, "ADAPTER_REJECTED"),
        (1, "APPLICATION_RESULT"),
    ]
    assert studio.evidence.events[-1][2] == {"status": "FAILED", "code": "INVALID_PROVIDER_OUTPUT"}


@pytest.mark.parametrize(
    ("outcomes", "status_code", "calls"),
    [
        ((ProposalGenerationError("RESPONSE_SCHEMA_ERROR"), *review_answers()), 201, 4),
        ((ProposalGenerationError("INCOMPLETE_OUTPUT"), *review_answers()), 201, 4),
        (
            (
                ProposalGenerationError("INVALID_PROVIDER_OUTPUT"),
                ProposalGenerationError("INVALID_PROVIDER_OUTPUT"),
            ),
            502,
            2,
        ),
        ((ProposalGenerationError("PROVIDER_UNAVAILABLE"),), 503, 1),
        ((ProposalGenerationError("GENERATION_BUDGET_EXCEEDED"),), 402, 1),
        ((critique_answer(), ProposalGenerationError("GENERATION_BUDGET_UNAVAILABLE")), 503, 2),
    ],
)
def test_schema_errors_are_retried_once_and_other_failures_are_not(
    monkeypatch, outcomes, status_code, calls
):
    studio = Studio(monkeypatch, *outcomes)
    with studio.client() as client:
        record(client, FIRST)
        answer = review(client)
    assert answer.status_code == status_code, answer.text
    assert len(studio.calls) == calls
    assert len(MemoryChanges.store.runs) == int(status_code == 201)
    if status_code != 201:
        error = outcomes[-1]
        assert answer.json()["detail"]["code"] == error.code
        assert studio.evidence.events[-1][2] == {"status": "FAILED", "code": error.code}


LIVE_EMPTY_COMMENT = {"assessment": "DRIFT", "comment": "", "findings": []}


@pytest.mark.parametrize(
    ("outcomes", "status_code", "calls"),
    [
        ((LIVE_EMPTY_COMMENT, *review_answers()), 201, 4),
        ((LIVE_EMPTY_COMMENT, LIVE_EMPTY_COMMENT), 502, 2),
    ],
)
def test_an_empty_comment_is_asked_once_more_and_then_fails(
    monkeypatch, outcomes, status_code, calls
):
    studio = Studio(monkeypatch, *outcomes)
    with studio.client() as client:
        record(client, FIRST)
        answer = review(client)
    assert answer.status_code == status_code, answer.text
    assert len(studio.calls) == calls
    assert studio.calls[0]["context"] == studio.calls[1]["context"]
    assert studio.evidence.events[0][2]["status"] == "CRITIQUE_REJECTED"
    if status_code == 502:
        assert answer.json() == {
            "detail": {"code": "RESPONSE_SCHEMA_ERROR", "stage": "MODEL_PROPOSAL"}
        }
        assert MemoryChanges.store.runs == []
    else:
        assert answer.json()["run"]["critiques"][0]["summary"] == ITALIAN


@pytest.mark.parametrize(
    ("outcomes", "rejected", "reason"),
    [
        (
            (critique_answer("x"), *review_answers()),
            0,
            "the critique summary is shorter than 20 characters",
        ),
        (
            (
                critique_answer(findings=[finding_answer(problem=ENGLISH_FINDING)]),
                *review_answers(),
            ),
            0,
            "the finding text is not written in the language of the project",
        ),
        (
            (
                critique_answer(),
                fine_answer(),
                verdict_answer("CODE_DRIFT", tasks_for_code=[ENGLISH_TASK]),
                verdict_answer("CODE_DRIFT"),
            ),
            2,
            "the code task is not written in the language of the project",
        ),
    ],
)
def test_a_short_or_foreign_answer_is_asked_once_more(monkeypatch, outcomes, rejected, reason):
    studio = Studio(monkeypatch, *outcomes)
    with studio.client() as client:
        record(client, FIRST)
        answer = review(client)
    assert answer.status_code == 201, answer.text
    assert len(studio.calls) == 4
    assert studio.calls[rejected]["context"] == studio.calls[rejected + 1]["context"]
    assert studio.evidence.payloads("ADAPTER_REJECTED") == [
        {"code": "ValueError", "reason": reason}
    ]
    assert (rejected, "ADAPTER_REJECTED") in studio.evidence.kinds()
    run = answer.json()["run"]
    assert run["critiques"][0]["summary"] == ITALIAN
    assert run["critiques"][0]["findings"][0]["text"] == "Il modulo non chiede la data di arrivo."


def test_a_second_short_summary_fails_with_invalid_provider_output(monkeypatch):
    studio = Studio(monkeypatch, critique_answer("x"), critique_answer("Troppo breve."))
    with studio.client() as client:
        record(client, FIRST)
        answer = review(client)
    assert answer.status_code == 502
    assert answer.json() == {
        "detail": {"code": "INVALID_PROVIDER_OUTPUT", "stage": "MODEL_PROPOSAL"}
    }
    assert len(studio.calls) == 2
    assert MemoryChanges.store.runs == []
    assert [item["reason"] for item in studio.evidence.payloads("ADAPTER_REJECTED")] == [
        "the critique summary is shorter than 20 characters",
        "the critique summary is shorter than 20 characters",
    ]


def test_the_cost_of_a_run_is_the_sum_read_from_the_evidence(monkeypatch):
    studio = Studio(monkeypatch, *review_answers(), evidence=CostedEvidence())
    with studio.client() as client:
        record(client, FIRST)
        answer = review(client)
    assert answer.status_code == 201, answer.text
    assert answer.json()["run"]["cost_microusd"] == 500_000
    assert MemoryChanges.store.runs[0].cost_microusd == 500_000


def test_the_earlier_findings_of_the_same_twin_reach_the_next_pending_review(monkeypatch):
    findings = [
        finding_answer(
            about_file=None,
            about_requirement=None,
            about_screen=None,
            problem=f"Problema numero {index} del modulo.",
            severity="HIGH",
            suggestion=None,
        )
        for index in range(1, 3)
    ]
    studio = Studio(
        monkeypatch,
        critique_answer(findings=findings),
        fine_answer(),
        verdict_answer(),
        *review_answers(),
        *review_answers(),
    )
    with studio.client() as client:
        record(client, FIRST, SECOND, THIRD)
        assert review(client, FIRST).status_code == 201
        assert review(client, THIRD).status_code == 201
        assert decide(client, FIRST, kind="ALIGNED").status_code == 200
        assert review(client, SECOND).status_code == 201
    contexts = [call["context"] for call in studio.calls]
    assert contexts[0]["earlier_findings"] == []
    assert contexts[3]["earlier_findings"] == [
        "Problema numero 1 del modulo.",
        "Problema numero 2 del modulo.",
    ]
    assert contexts[3]["earlier_source"] == "PREVIOUS_COMMIT"
    assert contexts[4]["earlier_findings"] == []
    assert contexts[6]["earlier_findings"] == []
    assert [contexts[index]["earlier_source"] for index in (0, 4, 6)] == [None, None, None]


def test_the_decisions_record_the_aligned_point_the_tasks_and_their_closing(monkeypatch):
    studio = Studio(monkeypatch, *review_answers("CODE_DRIFT"))
    with studio.client() as client:
        record(client, FIRST, SECOND, THIRD)
        assert review(client, FIRST).status_code == 201
        tasks = decide(
            client,
            FIRST,
            kind="CODE_TASKS",
            note="  Da fare   subito.\n",
            tasks=["Ripristinare  il pulsante.", "Aggiungere la data."],
        )
        more = decide(client, SECOND[:10], kind="CODE_TASKS", tasks=["Terzo compito."])
        dismissed = decide(client, THIRD, kind="DISMISSED", note="   ")
        aligned = decide(client, SECOND, kind="ALIGNED")
        replaced = decide(client, SECOND, kind="DISMISSED")
    assert tasks.status_code == 200, tasks.text
    body = tasks.json()
    assert body["status"] == "DECIDED"
    assert body["change"]["commit"] == FIRST
    assert body["change"]["decision"]["kind"] == "CODE_TASKS"
    assert body["change"]["decision"]["note"] == "Da fare   subito."
    assert body["change"]["review"]["verdict"] == "CODE_DRIFT"
    assert "diff" not in body["change"]
    assert [task["code"] for task in body["alignment"]["tasks"]] == ["TSK-001", "TSK-002"]
    assert body["alignment"]["tasks"][0] == {
        "code": "TSK-001",
        "text": "Ripristinare il pulsante.",
        "about": {"requirements": ["REQ-001"], "screens": ["SCR-001"], "criteria": []},
        "origin": {
            "kind": "CODE_CHANGE",
            "commit": FIRST,
            "test_run_id": None,
            "twin_id": None,
            "twin_name": None,
            "finding": None,
        },
        "from_commit": FIRST,
        "created_at": body["change"]["decision"]["decided_at"],
        "status": "OPEN",
        "closed_at": None,
        "note": None,
    }
    assert body["alignment"]["pending_changes"] == 3
    assert [task["code"] for task in more.json()["alignment"]["tasks"]] == [
        "TSK-001",
        "TSK-002",
        "TSK-003",
    ]
    assert more.json()["alignment"]["tasks"][2]["about"] == {
        "requirements": [],
        "screens": [],
        "criteria": [],
    }
    assert dismissed.json()["change"]["decision"]["note"] is None
    assert len(dismissed.json()["alignment"]["tasks"]) == 3
    assert dismissed.json()["alignment"]["aligned"] is None
    point = aligned.json()["alignment"]
    assert point["aligned"] == {
        "commit": SECOND,
        "decided_at": aligned.json()["change"]["decision"]["decided_at"],
        "requirements_version_number": 1,
        "design_version_number": 1,
    }
    assert point["pending_changes"] == 1
    assert point["tasks"] == []
    assert {task.status for task in MemoryChanges.store.tasks} == {TaskStatus.DONE}
    assert replaced.json()["alignment"]["aligned"] is None
    assert replaced.json()["alignment"]["pending_changes"] == 3
    assert replaced.json()["change"]["decision"]["kind"] == "DISMISSED"


def test_an_aligned_decision_closes_only_the_tasks_of_changes_recorded_at_or_before_it(
    monkeypatch,
):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        record(client, FIRST, SECOND, THIRD)
        assert decide(client, SECOND, kind="CODE_TASKS", tasks=["Del secondo."]).status_code == 200
        assert decide(client, THIRD, kind="CODE_TASKS", tasks=["Del terzo."]).status_code == 200
        older = decide(client, FIRST, kind="ALIGNED").json()["alignment"]
        middle = decide(client, SECOND, kind="ALIGNED").json()["alignment"]
        statuses = {task.code: task.status for task in MemoryChanges.store.tasks}
        newest = decide(client, THIRD, kind="ALIGNED").json()["alignment"]
    assert older["aligned"]["commit"] == FIRST
    assert [(task["code"], task["from_commit"]) for task in older["tasks"]] == [
        ("TSK-001", SECOND),
        ("TSK-002", THIRD),
    ]
    assert middle["aligned"]["commit"] == SECOND
    assert [task["code"] for task in middle["tasks"]] == ["TSK-002"]
    assert statuses == {"TSK-001": TaskStatus.DONE, "TSK-002": TaskStatus.OPEN}
    assert newest["aligned"]["commit"] == THIRD
    assert newest["tasks"] == []
    assert {task.status for task in MemoryChanges.store.tasks} == {TaskStatus.DONE}


def test_an_aligned_decision_without_an_approved_reference_keeps_no_versions(monkeypatch):
    studio = Studio(monkeypatch, requirements=False, design=False)
    with studio.client() as client:
        record(client, FIRST)
        aligned = decide(client, FIRST, kind="ALIGNED")
    assert aligned.status_code == 200
    assert aligned.json()["alignment"]["aligned"]["requirements_version_number"] is None
    assert aligned.json()["alignment"]["aligned"]["design_version_number"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "ALIGNED", "tasks": ["Un compito."]},
        {"kind": "CODE_TASKS"},
        {"kind": "CODE_TASKS", "tasks": []},
        {"kind": "CODE_TASKS", "tasks": [], "findings": []},
        {"kind": "CODE_TASKS", "tasks": ["   "]},
        {"kind": "CODE_TASKS", "tasks": ["Compito."] * 11},
        {"kind": "CODE_TASKS", "tasks": ["x" * 301]},
        {
            "kind": "CODE_TASKS",
            "tasks": ["Compito."] * 6,
            "findings": [{"twin_id": str(TWIN_TWO), "finding": 0}] * 5,
        },
        {"kind": "CODE_TASKS", "findings": [{"twin_id": str(TWIN_TWO), "finding": 0}] * 11},
        {"kind": "CODE_TASKS", "findings": [{"twin_id": str(TWIN_TWO), "finding": -1}]},
        {"kind": "CODE_TASKS", "findings": [{"twin_id": "someone", "finding": 0}]},
        {"kind": "CODE_TASKS", "findings": [{"twin_id": str(TWIN_TWO)}]},
        {
            "kind": "CODE_TASKS",
            "findings": [{"twin_id": str(TWIN_TWO), "finding": 0, "text": "Uno."}],
        },
        {"kind": "ALIGNED", "findings": [{"twin_id": str(TWIN_TWO), "finding": 0}]},
        {"kind": "DISMISSED", "findings": [{"twin_id": str(TWIN_TWO), "finding": 0}]},
        {"kind": "DISMISSED", "note": "x" * 2001},
        {"kind": "LATER"},
        {"kind": "DISMISSED", "reason": "no"},
        {},
    ],
)
def test_a_decision_body_is_validated(monkeypatch, body):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        record(client, FIRST)
        refused = client.post(f"{CHANGES}/{FIRST}/decision", json=body)
    assert refused.status_code == 422
    assert refused.json()["detail"] == "invalid_request"
    assert MemoryChanges.store.changes[0].decision is None


def test_a_decision_on_an_unknown_or_ambiguous_commit_is_refused(monkeypatch):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        record(client, "abcdef1" + "0" * 33, "abcdef1" + "1" * 33)
        unknown = decide(client, "9" * 40, kind="DISMISSED")
        ambiguous = decide(client, "abcdef1", kind="DISMISSED")
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": {"code": "CODE_CHANGE_NOT_FOUND"}}
    assert ambiguous.status_code == 409
    assert ambiguous.json() == {"detail": {"code": "CODE_CHANGE_AMBIGUOUS"}}


def test_the_alignment_answers_the_reference_the_aligned_point_and_the_open_tasks(monkeypatch):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        empty = client.get(ALIGNMENT).json()
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
        "aligned": None,
        "pending_changes": 0,
        "stale_reviews": 0,
        "latest_change": None,
        "tasks": [],
        "review_available": True,
    }
    assert list(empty) == [
        "project_id",
        "reference",
        "aligned",
        "pending_changes",
        "stale_reviews",
        "latest_change",
        "tasks",
        "review_available",
    ]
    bare = Studio(monkeypatch, model=False, requirements=False, design=False)
    with bare.client() as client:
        record(client, FIRST)
        partial = client.get(ALIGNMENT).json()
    assert partial["reference"] == {"requirements": None, "design": None}
    assert partial["review_available"] is False
    assert partial["pending_changes"] == 1
    assert partial["latest_change"]["commit"] == FIRST


def test_the_application_reads_the_state_through_the_repository(monkeypatch):
    studio = Studio(monkeypatch, *review_answers())
    application = studio.application()
    with studio.client() as client:
        record(client, FIRST)
    result = asyncio.run(
        application.review(
            owner_user_id=OWNER,
            project_id=PROJECT,
            commit=FIRST[:7],
            body=ChangeReviewRequest(locale="it-IT"),
        )
    )
    assert result.status is ChangeReviewStatus.REVIEWED
    assert MemoryChanges.store.runs == [result.run]
    assert application.review_available()
    changes = asyncio.run(application.changes(owner_user_id=OWNER, project_id=PROJECT))
    assert [item.review for item in changes] == [result.run.summary()]
    long = Studio(monkeypatch, *review_answers())
    with long.client() as client:
        record(client, FIRST)
    MemoryChanges.store.changes[0] = replace(MemoryChanges.store.changes[0], diff="+" * 60_000)
    asyncio.run(
        long.application().review(
            owner_user_id=OWNER,
            project_id=PROJECT,
            commit=FIRST,
            body=ChangeReviewRequest(locale="it-IT"),
        )
    )
    assert long.calls[0]["context"]["change"]["diff"].endswith(DIFF_CUT_LINE)


def test_a_database_less_runtime_answers_database_unavailable(monkeypatch):
    studio = Studio(monkeypatch)
    studio.runtime.database_runtime = None
    with pytest.raises(HTTPException) as failure:
        asyncio.run(studio.application().changes(owner_user_id=OWNER, project_id=PROJECT))
    assert failure.value.status_code == 503
    assert failure.value.detail == {"code": "DATABASE_UNAVAILABLE"}


UNREVIEWED_RUN = UUID("00000000-0000-4000-8000-000000000c11")
UNKNOWN_RUN = UUID("00000000-0000-4000-8000-000000000c99")
DATE_FINDING = "Il modulo non chiede la data di arrivo."
DATE_ACTION = "Aggiungere il campo della data di arrivo."
PRINT_FINDING = "Il conto non si stampa dalla reception."
PHONE_FINDING = "Il pulsante di salvataggio non si vede sul telefono."
CURRENCY_FINDING = "Il totale non mostra la valuta che uso."
LONG_FINDING = ("parola " * 57).strip()
TWIN_KEYS = ["run_id", "reviewed_at", "verdict", "summary", "reference", "stale"]
NO_ORIGIN = {
    "commit": None,
    "test_run_id": None,
    "twin_id": None,
    "twin_name": None,
    "finding": None,
}


def owner_item(text="Scrivere la guida per la reception."):
    return {"text": text, "source": {"kind": "OWNER"}}


def change_item(commit=FIRST, *, twin_id=TWIN_ONE, position=0, text=None):
    source = {"kind": "CODE_CHANGE", "commit": commit, "twin_id": str(twin_id), "finding": position}
    return {"text": text, "source": source}


def run_item(run_id=TEST_RUN_ID, *, twin_id=TWIN_ONE, position=0, text=None):
    source = {
        "kind": "TEST_RUN",
        "test_run_id": str(run_id),
        "twin_id": str(twin_id),
        "finding": position,
    }
    return {"text": text, "source": source}


def reviewed_change(place, *findings, minutes=60, **values):
    change = MemoryChanges.store.changes[place]
    run = review_run(
        change,
        id=uuid4(),
        reviewed_at=NOW + timedelta(minutes=minutes),
        critiques=(critique(findings=findings or (finding(),)),),
        **values,
    )
    MemoryChanges.store.runs.append(run)
    return run


def reviewed_test_run(*findings, run_id=TEST_RUN_ID, minutes=0):
    review = sample_review(
        id=uuid4(),
        run_id=run_id,
        reviewed_at=NOW + timedelta(minutes=minutes),
        critiques=(sample_critique(findings=findings or (sample_finding(),)),),
    )
    reviewed = sample_run(run_id=run_id).with_review(review)
    MemoryRuns.store = [item for item in MemoryRuns.store if item.id != run_id] + [reviewed]
    return reviewed


def create(client, *items):
    return client.post(TASKS, json={"tasks": list(items)})


def set_status(client, code, **body):
    return client.post(f"{TASKS}/{code}/status", json=body)


def test_tasks_of_every_origin_are_created_in_the_order_sent(monkeypatch):
    studio = Studio(monkeypatch)
    printing = finding(text=PRINT_FINDING, action=None, requirement=None, screen="SCR-002")
    with studio.client() as client:
        record(client, FIRST)
        reviewed_change(0, finding(), printing)
        reviewed_test_run()
        answer = create(
            client,
            owner_item("  Scrivere la guida   per la reception. "),
            change_item(),
            change_item(FIRST[:7].upper(), position=1, text=" Aggiungere la stampa  del conto. "),
            run_item(),
        )
        listed = client.get(TASKS).json()
        alignment = client.get(ALIGNMENT).json()
    assert answer.status_code == 201, answer.text
    body = answer.json()
    assert list(body) == ["status", "created", "tasks", "alignment"]
    assert (body["status"], body["created"]) == ("CREATED", 4)
    assert [item["code"] for item in body["tasks"]] == ["TSK-001", "TSK-002", "TSK-003", "TSK-004"]
    written, from_change, chosen, from_run = body["tasks"]
    assert written == {
        "code": "TSK-001",
        "text": "Scrivere la guida per la reception.",
        "about": {"requirements": [], "screens": [], "criteria": []},
        "origin": {"kind": "OWNER", **NO_ORIGIN},
        "from_commit": None,
        "created_at": written["created_at"],
        "status": "OPEN",
        "closed_at": None,
        "note": None,
    }
    assert datetime.fromisoformat(written["created_at"]).utcoffset() == timedelta(0)
    assert from_change["text"] == DATE_ACTION
    assert from_change["about"] == {
        "requirements": ["REQ-001"],
        "screens": ["SCR-001"],
        "criteria": [],
    }
    assert from_change["origin"] == {
        "kind": "CODE_CHANGE",
        "commit": FIRST,
        "test_run_id": None,
        "twin_id": str(TWIN_ONE),
        "twin_name": "Receptionist Twin",
        "finding": DATE_FINDING,
    }
    assert from_change["from_commit"] == FIRST
    assert chosen["text"] == "Aggiungere la stampa del conto."
    assert chosen["origin"]["finding"] == PRINT_FINDING
    assert chosen["about"] == {"requirements": [], "screens": ["SCR-002"], "criteria": []}
    assert from_run["text"] == "Mostrare la valuta accanto al totale."
    assert from_run["about"] == {
        "requirements": ["REQ-001"],
        "screens": ["SCR-001"],
        "criteria": ["AC-001"],
    }
    assert from_run["origin"] == {
        "kind": "TEST_RUN",
        "commit": None,
        "test_run_id": str(TEST_RUN_ID),
        "twin_id": str(TWIN_ONE),
        "twin_name": "Receptionist Twin",
        "finding": CURRENCY_FINDING,
    }
    assert from_run["from_commit"] is None
    assert body["alignment"]["tasks"] == body["tasks"]
    assert body["alignment"] == alignment
    assert listed == {"items": body["tasks"]}


def test_a_finding_without_an_action_becomes_a_task_with_its_text_cut_to_the_limit(monkeypatch):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        record(client, FIRST)
        reviewed_change(0, finding(text=LONG_FINDING, action=None))
        reviewed_test_run(sample_finding(action=None))
        answer = create(client, change_item(), run_item())
    assert answer.status_code == 201, answer.text
    long, short = answer.json()["tasks"]
    assert len(LONG_FINDING) > MAX_TASK_LENGTH
    assert long["text"] == LONG_FINDING[: MAX_TASK_LENGTH - 1].rstrip() + "…"
    assert long["origin"]["finding"] == LONG_FINDING
    assert short["text"] == CURRENCY_FINDING


def test_the_same_finding_text_is_the_same_task_and_a_new_review_brings_new_sources(monkeypatch):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        record(client, FIRST)
        reviewed_change(0, finding(), finding(text=PRINT_FINDING))
        first = create(client, change_item()).json()
        again = create(client, change_item())
        twice = create(client, change_item(), change_item(FIRST[:10])).json()
        reviewed_change(0, finding(text=PHONE_FINDING), finding(), minutes=120)
        repeated = create(client, change_item(position=0), change_item(position=1)).json()
        assert set_status(client, "TSK-001", status="DONE").status_code == 200
        after_done = create(client, change_item(position=1)).json()
        reviewed_test_run()
        run_first = create(client, run_item()).json()
        run_again = create(client, run_item()).json()
        reviewed_test_run(
            sample_finding(text="Il pulsante Calcola non risponde."), sample_finding()
        )
        run_new = create(client, run_item(position=0), run_item(position=1)).json()
    assert again.status_code == 201
    assert (first["created"], [item["code"] for item in first["tasks"]]) == (1, ["TSK-001"])
    assert (again.json()["created"], again.json()["tasks"]) == (0, first["tasks"])
    assert (twice["created"], [item["code"] for item in twice["tasks"]]) == (
        0,
        ["TSK-001", "TSK-001"],
    )
    assert (repeated["created"], [item["code"] for item in repeated["tasks"]]) == (
        1,
        ["TSK-002", "TSK-001"],
    )
    assert repeated["tasks"][0]["origin"]["finding"] == PHONE_FINDING
    assert repeated["tasks"][1]["origin"]["finding"] == DATE_FINDING
    assert (after_done["created"], after_done["tasks"][0]["code"]) == (1, "TSK-003")
    assert after_done["tasks"][0]["origin"]["finding"] == DATE_FINDING
    assert (run_first["created"], run_first["tasks"][0]["code"]) == (1, "TSK-004")
    assert (run_again["created"], run_again["tasks"]) == (0, run_first["tasks"])
    assert (run_new["created"], [item["code"] for item in run_new["tasks"]]) == (
        1,
        ["TSK-005", "TSK-004"],
    )
    assert len(MemoryChanges.store.tasks) == 5


def test_nothing_is_created_when_one_task_is_refused(monkeypatch):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        record(client, FIRST)
        reviewed_change(0)
        refused = create(client, owner_item(), change_item(), change_item(position=5))
    assert refused.status_code == 422
    assert refused.json() == {"detail": {"code": "TASK_SOURCE_INVALID", "index": 2}}
    assert MemoryChanges.store.tasks == []
    assert MemoryChanges.store.creations == []


AMBIGUOUS = "abcdef1"


@pytest.mark.parametrize(
    ("items", "status_code", "detail"),
    [
        (
            [change_item("9" * 40), run_item(UNKNOWN_RUN)],
            404,
            {"code": "TEST_RUN_NOT_FOUND"},
        ),
        (
            [change_item(AMBIGUOUS), change_item("9" * 40)],
            404,
            {"code": "CODE_CHANGE_NOT_FOUND"},
        ),
        (
            [change_item(position=9), change_item(AMBIGUOUS)],
            409,
            {"code": "CODE_CHANGE_AMBIGUOUS"},
        ),
        (
            [owner_item(), change_item(SECOND)],
            422,
            {"code": "TASK_SOURCE_INVALID", "index": 1},
        ),
        ([change_item(twin_id=TWIN_TWO)], 422, {"code": "TASK_SOURCE_INVALID", "index": 0}),
        ([change_item(position=1)], 422, {"code": "TASK_SOURCE_INVALID", "index": 0}),
        ([run_item(UNREVIEWED_RUN)], 422, {"code": "TASK_SOURCE_INVALID", "index": 0}),
        ([run_item(twin_id=TWIN_TWO)], 422, {"code": "TASK_SOURCE_INVALID", "index": 0}),
        ([run_item(position=1)], 422, {"code": "TASK_SOURCE_INVALID", "index": 0}),
        (
            [run_item(), owner_item(), change_item(position=3), change_item(twin_id=TWIN_TWO)],
            422,
            {"code": "TASK_SOURCE_INVALID", "index": 2},
        ),
    ],
)
def test_the_task_refusals_come_in_the_order_of_the_contract(
    monkeypatch, items, status_code, detail
):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        record(client, FIRST, SECOND, AMBIGUOUS + "0" * 33, AMBIGUOUS + "f" * 33)
        reviewed_change(0)
        reviewed_test_run()
        MemoryRuns.store.append(sample_run(run_id=UNREVIEWED_RUN))
        refused = create(client, *items)
    assert refused.status_code == status_code
    assert refused.json() == {"detail": detail}
    assert MemoryChanges.store.tasks == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"tasks": []},
        {"tasks": [owner_item()] * 11},
        {"tasks": [{"text": None, "source": {"kind": "OWNER"}}]},
        {"tasks": [{"source": {"kind": "OWNER"}}]},
        {"tasks": [owner_item("   ")]},
        {"tasks": [owner_item("")]},
        {"tasks": [owner_item("x" * 301)]},
        {"tasks": [{"text": "Uno.", "source": {"kind": "MODEL"}}]},
        {"tasks": [{"text": "Uno."}]},
        {"tasks": [{"text": "Uno.", "source": {"kind": "OWNER", "twin_id": str(TWIN_ONE)}}]},
        {"tasks": [change_item("xyz1234")]},
        {"tasks": [change_item("abc12")]},
        {"tasks": [change_item("a" * 65)]},
        {"tasks": [change_item(position=-1)]},
        {"tasks": [run_item(position=-1)]},
        {
            "tasks": [
                {
                    "text": None,
                    "source": {"kind": "TEST_RUN", "test_run_id": "not-a-uuid", "twin_id": "x"},
                }
            ]
        },
        {
            "tasks": [
                {"text": None, "source": {"kind": "TEST_RUN", "test_run_id": str(TEST_RUN_ID)}}
            ]
        },
        {"tasks": [{"text": None, "source": {"kind": "CODE_CHANGE", "commit": FIRST}}]},
        {"tasks": [{**owner_item(), "note": "Una nota."}]},
        {"tasks": [owner_item()], "extra": True},
    ],
)
def test_a_task_body_is_validated(monkeypatch, body):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        record(client, FIRST)
        reviewed_change(0)
        refused = client.post(TASKS, json=body)
    assert refused.status_code == 422
    assert refused.json()["detail"] == "invalid_request"
    assert MemoryChanges.store.tasks == []


def test_the_open_tasks_are_listed_by_number_and_every_task_on_request(monkeypatch):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        created = create(client, owner_item("Primo."), owner_item("Secondo."), owner_item("Primo."))
        assert set_status(client, "TSK-001", status="DONE").status_code == 200
        assert set_status(client, "TSK-003", status="DROPPED", note="Doppio.").status_code == 200
        open_items = client.get(TASKS).json()["items"]
        explicit = client.get(TASKS, params={"status": "open"}).json()["items"]
        every = client.get(TASKS, params={"status": "all"}).json()["items"]
        wrong = client.get(TASKS, params={"status": "done"})
    assert created.json()["created"] == 3
    assert [item["code"] for item in open_items] == ["TSK-002"]
    assert explicit == open_items
    assert [(item["code"], item["status"], item["note"]) for item in every] == [
        ("TSK-001", "DONE", None),
        ("TSK-002", "OPEN", None),
        ("TSK-003", "DROPPED", "Doppio."),
    ]
    assert wrong.status_code == 422
    assert wrong.json()["detail"] == "invalid_request"


def test_a_task_is_closed_dropped_and_reopened_with_the_note_of_the_owner(monkeypatch):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        create(client, owner_item())
        done = set_status(client, "TSK-001", status="DONE", note="  Fatto   nel commit. ")
        noted = set_status(client, "tsk-001", status="DONE", note="Rivisto.")
        cleared = set_status(client, "TSK-001", status="DONE")
        dropped = set_status(client, "TSK-001", status="DROPPED", note="Non serve.")
        reopened = set_status(client, "Tsk-001", status="OPEN", note="Torna utile.")
        missing = [
            set_status(client, code, status="DONE")
            for code in ("TSK-002", "TSK-0001", "TSK-01", "TSK-000", "abc")
        ]
    assert done.status_code == 200, done.text
    body = done.json()
    assert list(body) == ["status", "task", "alignment"]
    assert body["status"] == "UPDATED"
    task = body["task"]
    assert (task["code"], task["status"], task["note"]) == ("TSK-001", "DONE", "Fatto nel commit.")
    assert datetime.fromisoformat(task["closed_at"]).utcoffset() == timedelta(0)
    assert body["alignment"]["tasks"] == []
    assert (noted.json()["task"]["closed_at"], noted.json()["task"]["note"]) == (
        task["closed_at"],
        "Rivisto.",
    )
    assert (cleared.json()["task"]["closed_at"], cleared.json()["task"]["note"]) == (
        task["closed_at"],
        None,
    )
    assert (dropped.json()["task"]["status"], dropped.json()["task"]["note"]) == (
        "DROPPED",
        "Non serve.",
    )
    assert dropped.json()["task"]["closed_at"] is not None
    again = reopened.json()["task"]
    assert (again["status"], again["closed_at"], again["note"]) == ("OPEN", None, "Torna utile.")
    assert reopened.json()["alignment"]["tasks"] == [again]
    for answer in missing:
        assert answer.status_code == 404
        assert answer.json() == {"detail": {"code": "CODE_TASK_NOT_FOUND"}}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"note": "Una nota."},
        {"status": "LATER"},
        {"status": "done"},
        {"status": "DONE", "note": "x" * 301},
        {"status": "DONE", "note": 3},
        {"status": "DONE", "extra": True},
    ],
)
def test_a_status_body_is_validated(monkeypatch, body):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        create(client, owner_item())
        refused = client.post(f"{TASKS}/TSK-001/status", json=body)
    assert refused.status_code == 422
    assert refused.json()["detail"] == "invalid_request"
    assert MemoryChanges.store.tasks[0].open


VERDICT_TASK = ("Ripristinare il pulsante.", None, ["REQ-001"], ["SCR-001"])
DATE_TASK = (DATE_ACTION, DATE_FINDING, ["REQ-001"], ["SCR-001"])
PRINT_TASK = (PRINT_FINDING, PRINT_FINDING, [], [])


@pytest.mark.parametrize(
    ("tasks", "positions", "expected"),
    [
        (["Ripristinare il pulsante."], [], [VERDICT_TASK]),
        ([], [0], [DATE_TASK]),
        (["Ripristinare il pulsante."], [1, 0], [VERDICT_TASK, PRINT_TASK, DATE_TASK]),
        ([], [0, 0], [DATE_TASK]),
    ],
)
def test_a_code_tasks_decision_takes_the_texts_of_the_verdict_and_the_chosen_findings(
    monkeypatch, tasks, positions, expected
):
    studio = Studio(monkeypatch)
    printing = finding(text=PRINT_FINDING, action=None, requirement=None, screen=None, file=None)
    with studio.client() as client:
        record(client, FIRST)
        reviewed_change(0, finding(), printing)
        answer = decide(
            client,
            FIRST,
            kind="CODE_TASKS",
            tasks=tasks,
            findings=[{"twin_id": str(TWIN_ONE), "finding": place} for place in positions],
        )
    assert answer.status_code == 200, answer.text
    created = answer.json()["alignment"]["tasks"]
    assert [
        (
            item["text"],
            item["origin"]["finding"],
            item["about"]["requirements"],
            item["about"]["screens"],
        )
        for item in created
    ] == list(expected)
    assert [item["code"] for item in created] == [
        f"TSK-{number:03d}" for number in range(1, len(expected) + 1)
    ]
    assert {item["origin"]["kind"] for item in created} == {"CODE_CHANGE"}
    assert {item["origin"]["commit"] for item in created} == {FIRST}
    assert answer.json()["change"]["decision"]["kind"] == "CODE_TASKS"


@pytest.mark.parametrize(
    ("commit", "findings", "index"),
    [
        (FIRST, [(TWIN_ONE, 0), (TWIN_ONE, 4)], 1),
        (FIRST, [(TWIN_TWO, 0)], 0),
        (SECOND, [(TWIN_ONE, 0)], 0),
    ],
)
def test_a_decision_with_a_finding_that_is_not_there_records_nothing(
    monkeypatch, commit, findings, index
):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        record(client, FIRST, SECOND)
        reviewed_change(0)
        refused = decide(
            client,
            commit,
            kind="CODE_TASKS",
            tasks=["Ripristinare il pulsante."],
            findings=[{"twin_id": str(twin), "finding": place} for twin, place in findings],
        )
    assert refused.status_code == 422
    assert refused.json() == {"detail": {"code": "TASK_SOURCE_INVALID", "index": index}}
    assert [item.decision for item in MemoryChanges.store.changes] == [None, None]
    assert MemoryChanges.store.tasks == []


def test_a_finding_chosen_in_a_decision_is_the_same_task_for_the_task_route(monkeypatch):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        record(client, FIRST)
        reviewed_change(0)
        decided = decide(
            client, FIRST, kind="CODE_TASKS", findings=[{"twin_id": str(TWIN_ONE), "finding": 0}]
        )
        posted = create(client, change_item()).json()
    assert decided.status_code == 200, decided.text
    assert [item["code"] for item in decided.json()["alignment"]["tasks"]] == ["TSK-001"]
    assert posted["created"] == 0
    assert posted["tasks"] == decided.json()["alignment"]["tasks"]


def stored_task(number, minutes, origin, change=None):
    from_run = origin is TaskOrigin.TEST_RUN
    task = CodeTask(
        id=uuid4(),
        project_id=PROJECT,
        owner_user_id=OWNER,
        number=number,
        text=f"Compito numero {number}.",
        created_at=NOW + timedelta(minutes=minutes),
        origin=origin,
        from_change_id=None if change is None else change.id,
        from_commit=None if change is None else change.commit,
        test_run_id=TEST_RUN_ID if from_run else None,
        twin_id=TWIN_ONE if from_run else None,
        twin_name="Receptionist Twin" if from_run else None,
        finding=f"Rilievo numero {number}." if from_run else None,
    )
    MemoryChanges.store.tasks.append(task)
    return task


def test_an_aligned_decision_closes_the_tasks_written_before_the_aligned_change_was_recorded(
    monkeypatch,
):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        record(client, FIRST, SECOND, THIRD)
        MemoryChanges.store.changes = [
            replace(item, recorded_at=NOW + timedelta(minutes=10 * place))
            for place, item in enumerate(MemoryChanges.store.changes)
        ]
        _, second, third = MemoryChanges.store.changes
        stored_task(1, 5, TaskOrigin.OWNER)
        stored_task(2, 10, TaskOrigin.TEST_RUN)
        stored_task(3, 15, TaskOrigin.TEST_RUN)
        stored_task(4, 25, TaskOrigin.OWNER)
        stored_task(5, 30, TaskOrigin.CODE_CHANGE, second)
        stored_task(6, 1, TaskOrigin.CODE_CHANGE, third)
        middle = decide(client, SECOND, kind="ALIGNED").json()["alignment"]
        newest = decide(client, THIRD, kind="ALIGNED").json()["alignment"]
    assert [item["code"] for item in middle["tasks"]] == ["TSK-003", "TSK-004", "TSK-006"]
    assert [item["code"] for item in newest["tasks"]] == ["TSK-004"]
    closed = {task.code: task for task in MemoryChanges.store.tasks if not task.open}
    assert sorted(closed) == ["TSK-001", "TSK-002", "TSK-003", "TSK-005", "TSK-006"]
    assert {task.status for task in closed.values()} == {TaskStatus.DONE}
    assert all(task.closed_at is not None and task.note is None for task in closed.values())


@pytest.mark.parametrize(
    ("reference", "setting", "stale"),
    [
        ({}, {}, False),
        ({"requirements_version_number": 2}, {}, True),
        ({"design_version_number": 2}, {}, True),
        ({"alternative_code": "DES-002"}, {}, True),
        ({"design_version_number": 2}, {"design": False}, False),
        ({"requirements_version_number": 2}, {"requirements": False}, False),
    ],
)
def test_every_answer_that_holds_a_change_says_whether_its_review_is_stale(
    monkeypatch, reference, setting, stale
):
    studio = Studio(monkeypatch, **setting)
    with studio.client() as client:
        record(client, FIRST)
        run = reviewed_change(0, **reference)
        again = client.post(CHANGES, json=payload(FIRST))
        answers = [
            client.get(ALIGNMENT).json()["latest_change"],
            client.get(CHANGES).json()["items"][0],
            client.get(CHANGES, params={"pending": "true"}).json()["items"][0],
            client.get(f"{CHANGES}/{FIRST}").json(),
            again.json()["change"],
            decide(client, FIRST, kind="DISMISSED").json()["change"],
        ]
        alignment = client.get(ALIGNMENT).json()
    assert again.status_code == 200
    expected = {**run.summary().to_snapshot(), "stale": stale}
    for answer in answers:
        assert list(answer["review"]) == TWIN_KEYS
        assert answer["review"] == expected
    assert alignment["stale_reviews"] == int(stale)


def test_the_alignment_counts_the_stale_reviews_of_the_pending_changes_only(monkeypatch):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        record(client, FIRST, SECOND, THIRD)
        reviewed_change(0, design_version_number=2)
        reviewed_change(1, alternative_code="DES-002")
        reviewed_change(2)
        before = client.get(ALIGNMENT).json()
        assert decide(client, FIRST, kind="ALIGNED").status_code == 200
        after = client.get(ALIGNMENT).json()
        assert decide(client, SECOND, kind="ALIGNED").status_code == 200
        last = client.get(ALIGNMENT).json()
    assert (before["pending_changes"], before["stale_reviews"]) == (3, 2)
    assert (after["pending_changes"], after["stale_reviews"]) == (2, 1)
    assert (last["pending_changes"], last["stale_reviews"]) == (1, 0)


def test_a_review_asked_again_gives_each_twin_its_findings_on_the_same_commit(monkeypatch):
    def problem(text):
        return critique_answer(findings=[finding_answer(problem=text, suggestion=None)])

    studio = Studio(
        monkeypatch,
        problem("Problema A del modulo."),
        fine_answer(),
        verdict_answer(),
        problem("Problema B del modulo."),
        fine_answer(),
        verdict_answer(),
        *review_answers(),
        *review_answers(),
    )
    with studio.client() as client:
        record(client, FIRST, SECOND)
        assert review(client, FIRST).status_code == 201
        assert review(client, SECOND).status_code == 201
        assert review(client, SECOND, again=True).status_code == 201
        assert review(client, FIRST, again=True).status_code == 201
    earlier = [
        (call["context"]["earlier_findings"], call["context"]["earlier_source"])
        for call in studio.calls
        if call["context"]["purpose"] == CRITIQUE_PURPOSE
    ]
    assert earlier == [
        ([], None),
        ([], None),
        (["Problema A del modulo."], "PREVIOUS_COMMIT"),
        ([], None),
        (["Problema B del modulo."], "THIS_COMMIT"),
        ([], None),
        (["Problema A del modulo."], "THIS_COMMIT"),
        ([], None),
    ]


def learned_by(twin_id, *statements):
    return tuple(
        LearnedObservation(
            twin_id=twin_id,
            number=number,
            statement=statement,
            source=LearningSource.OWNER,
            added_in_version=number,
            approved_at=NOW,
        )
        for number, statement in enumerate(statements, 1)
    )


def test_a_review_gives_each_twin_what_it_learned_and_leaves_the_verdict_as_it_was(monkeypatch):
    twin_id = first_twin().twin_id
    learned = {
        twin_id: learned_by(twin_id, "Il gruppo usa il telefono.", "Il gruppo lavora di notte.")
    }
    studios = []
    for known in (learned, None):
        current = Studio(monkeypatch, *review_answers(), learned=known)
        with current.client() as client:
            record(client, FIRST)
            assert review(client).status_code == 201
        studios.append(current)
    studio, plain = studios
    first, second, verdict = studio.calls
    assert first["context"]["user_twin"]["learned"] == [
        {"code": "OBS-001", "statement": "Il gruppo usa il telefono.", "source": "OWNER"},
        {"code": "OBS-002", "statement": "Il gruppo lavora di notte.", "source": "OWNER"},
    ]
    assert first["instruction"] == f"{CRITIQUE_INSTRUCTION} {LEARNED_INSTRUCTION}"
    assert "learned" not in second["context"]["user_twin"]
    assert second["instruction"] is CRITIQUE_INSTRUCTION
    assert "user_twin" not in verdict["context"]
    assert verdict["instruction"] is ALIGNMENT_INSTRUCTION
    plain_first, plain_second, plain_verdict = plain.calls
    assert plain_first["context"] == {
        **first["context"],
        "user_twin": {
            key: value for key, value in first["context"]["user_twin"].items() if key != "learned"
        },
    }
    assert plain_first["instruction"] is CRITIQUE_INSTRUCTION
    assert plain_second["context"] == second["context"]
    assert plain_verdict["context"] == verdict["context"]
    assert studio.evidence.kinds() == plain.evidence.kinds()
    assert [sorted(payload) for payload in studio.evidence.payloads("ADAPTER_ACCEPTED")] == [
        sorted(payload) for payload in plain.evidence.payloads("ADAPTER_ACCEPTED")
    ]
