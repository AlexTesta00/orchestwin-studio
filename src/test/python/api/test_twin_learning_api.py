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

from orchestwin.api import twin_learning
from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.generation_jobs import GenerationOperation
from orchestwin.api.generation_requests import PREFERENCE_APPLIED, RESPOND_ASYNC, request_key
from orchestwin.api.services import ApplicationRuntime
from orchestwin.api.twin_learning import (
    TwinLearningApplication,
    TwinUpdateRequest,
    TwinUpdateStatus,
    create_twin_learning_router,
)
from orchestwin.artifacts.design_evaluation import DesignEvaluationError
from orchestwin.artifacts.design_gate import design_artifact_reference
from orchestwin.config import ApplicationSettings
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.models.proposal_evidence import ProposalEvidenceError, begin_model_generation
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.twin_update import UPDATE_INSTRUCTION, UPDATE_PURPOSE, UPDATE_TASK
from orchestwin.projects.briefs import create_project_brief
from orchestwin.projects.code_changes import (
    AlignmentStatus,
    AlignmentVerdict,
    ChangeDecision,
    ChangeReviewRun,
    CritiqueFinding,
    CritiqueVerdict,
    DecisionKind,
    FindingSeverity,
    TwinCritique,
    create_code_change,
)
from orchestwin.projects.persistence.twin_learning import SqlAlchemyTwinLearningRepository
from orchestwin.projects.requirements_gate import requirements_artifact_reference
from orchestwin.projects.requirements_primitives import snapshot_content_hash
from orchestwin.projects.twin_learning import (
    LearnedObservation,
    LearningSource,
    ProposedObservation,
    TwinUpdate,
    UpdateDecisionKind,
    UpdateStatus,
    twin_learning_from_snapshot,
    twin_update_from_snapshot,
)
from orchestwin.twins.user_modeling_gate import user_modeling_artifact_reference
from orchestwin.workflow.gates import (
    HumanGateAction,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)
from src.test.python.artifacts import design_fixtures
from src.test.python.projects.test_acceptance_tests import (
    sample_critique,
    sample_finding,
    sample_review,
    sample_run,
)
from src.test.python.twins.test_user_modeling_gate import snapshot_version

PREFIX = "/api/v1"
OWNER = design_fixtures.OWNER_ID
PROJECT = design_fixtures.PROJECT_ID
STRANGER = UUID("00000000-0000-4000-8000-00000000ffff")
NOW = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
PROJECT_PATH = f"{PREFIX}/projects/{PROJECT}"
LEARNING = f"{PROJECT_PATH}/twin-learning"
JOBS = f"{PROJECT_PATH}/generation-jobs"
ASYNC = {"Prefer": RESPOND_ASYNC}
TWIN_ONE = UUID("00000000-0000-4000-8000-000000000030")
TWIN_TWO = UUID("00000000-0000-4000-8000-000000000b02")
FIRST = "a1" * 20
SECOND = "b2" * 20
BRIEF = create_project_brief(
    name="Lista ospiti",
    problem="La reception perde le prenotazioni.",
    goals=("Registrare gli ospiti in fretta",),
)
ITALIAN_COMMENT = "Ho capito che il mio gruppo registra gli ospiti con il telefono in mano."
ENGLISH_COMMENT = "I learned that my group registers the guests while they answer the phone."
FINDING = "Il modulo non chiede la data di arrivo."
BASIS = "Tre critiche sulla registrazione degli ospiti."
REQUEST = {"locale": "it-IT"}


def updates_path(twin=TWIN_ONE):
    return f"{PROJECT_PATH}/user-twins/{twin}/updates"


def update_path(update_id):
    return f"{PROJECT_PATH}/twin-updates/{update_id}"


def decision_path(update_id):
    return f"{update_path(update_id)}/decision"


def observations_path(twin=TWIN_ONE):
    return f"{PROJECT_PATH}/user-twins/{twin}/observations"


def retire_path(code, twin=TWIN_ONE):
    return f"{observations_path(twin)}/{code}/retire"


def observation_answer(**values):
    answer = {
        "about_requirement": "REQ-001",
        "about_screen": "SCR-001",
        "basis": BASIS,
        "contradicts_profile": None,
        "statement": "Il gruppo registra gli ospiti mentre parla al telefono.",
    }
    answer.update(values)
    return answer


def update_answer(comment=ITALIAN_COMMENT, observations=None):
    return {
        "comment": comment,
        "observations": [observation_answer()] if observations is None else observations,
    }


def three_observations():
    return update_answer(
        observations=[
            observation_answer(),
            observation_answer(statement="Il gruppo stampa la ricevuta per ogni ospite."),
            observation_answer(
                statement="Il gruppo lavora anche di notte.",
                about_requirement=None,
                about_screen="SCR-002",
                contradicts_profile="Il profilo dice che lavora solo di giorno.",
            ),
        ]
    )


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def now(self, tz=None):
        return self.moment


class Stored:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def to_snapshot(self):
        return dict(self.snapshot)


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
        self.observations: dict[int, LearnedObservation] = {}
        self.updates: list[TwinUpdate] = []
        self.changes = []
        self.runs = []
        self.tasks = []
        self.test_runs = []


class MemoryLearning(SqlAlchemyTwinLearningRepository):
    store: ClassVar[MemoryStore] = MemoryStore()

    def _mine(self, project_id):
        return self._owner_user_id == OWNER and project_id in self.store.projects

    async def project_exists(self, project_id):
        return self._mine(project_id)

    async def _lock_project(self, project_id):
        return self._mine(project_id)

    async def observations(self, project_id, twin_id):
        if not self._mine(project_id):
            return ()
        return tuple(
            item for _, item in sorted(self.store.observations.items()) if item.twin_id == twin_id
        )

    async def next_observation_number(self, project_id):
        return max(self.store.observations, default=0) + 1

    def _listed(self, project_id):
        if not self._mine(project_id):
            return []
        return sorted(
            self.store.updates, key=lambda item: (item.created_at, str(item.id)), reverse=True
        )

    async def update(self, project_id, update_id):
        return next((item for item in self._listed(project_id) if item.id == update_id), None)

    async def updates(self, project_id, twin_id):
        return tuple(item for item in self._listed(project_id) if item.twin_id == twin_id)

    async def pending_update(self, project_id, twin_id):
        return next(
            (item for item in self._listed(project_id) if item.twin_id == twin_id and item.pending),
            None,
        )

    async def latest_update(self, project_id, twin_id):
        return next((item for item in self._listed(project_id) if item.twin_id == twin_id), None)

    async def _store_observations(self, project_id, observations):
        for item in observations:
            assert item.number not in self.store.observations
            self.store.observations[item.number] = item

    async def _store_retirement(self, project_id, observation):
        self.store.observations[observation.number] = observation

    async def _store_update(self, project_id, update):
        self.store.updates.append(update)

    async def _store_decision(self, update):
        index = next(place for place, item in enumerate(self.store.updates) if item.id == update.id)
        self.store.updates[index] = update


class MemoryChanges:
    store: ClassVar[MemoryStore] = MemoryStore()

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    def _mine(self, project_id):
        return self.owner_user_id == OWNER and project_id in self.store.projects

    async def list(self, project_id, *, pending_only=False, limit=200):
        return tuple(reversed(self.store.changes)) if self._mine(project_id) else ()

    async def project_runs(self, project_id, *, limit=None):
        return tuple(reversed(self.store.runs)) if self._mine(project_id) else ()

    async def tasks(self, project_id, *, open_only=False):
        return tuple(Stored(item) for item in self.store.tasks) if self._mine(project_id) else ()


class MemoryTests:
    store: ClassVar[MemoryStore] = MemoryStore()

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def runs(self, project_id, *, limit=20):
        if self.owner_user_id != OWNER or project_id not in self.store.projects:
            return ()
        return tuple(reversed(self.store.test_runs))


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
        if index == 2:
            raise ProposalEvidenceError("PROPOSAL_EVIDENCE_HASH_MISMATCH")
        usage = {"success": {"usage": {"cost_microusd": 100_000 + index * 52_000}}}
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
        if callable(outcome):
            outcome = outcome()
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
        version_number=2,
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
        brief=True,
    ):
        self.store = MemoryStore()
        for memory in (MemoryLearning, MemoryChanges, MemoryTests):
            monkeypatch.setattr(memory, "store", self.store)
        monkeypatch.setattr(twin_learning, "SqlAlchemyTwinLearningRepository", MemoryLearning)
        monkeypatch.setattr(twin_learning, "SqlAlchemyCodeChangeRepository", MemoryChanges)
        monkeypatch.setattr(twin_learning, "SqlAlchemyAcceptanceTestRepository", MemoryTests)
        self.clock = Clock(NOW)
        monkeypatch.setattr(twin_learning, "datetime", self.clock)
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
            project_service=SimpleNamespace(
                current_brief=returning(SimpleNamespace(brief=BRIEF) if brief else None)
            ),
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

    def later(self, **values):
        self.clock.moment = self.clock.moment + timedelta(**values)
        return self.clock.moment

    def reviewed_change(self, commit=FIRST, *, at, twins=(TWIN_ONE,), texts=(FINDING,), kind=None):
        change = create_code_change(
            project_id=PROJECT,
            owner_user_id=OWNER,
            commit=commit,
            parent=None,
            committed_at=at - timedelta(hours=1),
            author="Ada Lovelace",
            message="Aggiunge la lista degli ospiti\n\nCon la data.",
            files=(),
            diff="",
            recorded_at=at - timedelta(minutes=30),
        )
        if kind is not None:
            change = change.with_decision(ChangeDecision(kind=kind, decided_at=at))
        names = {TWIN_ONE: "Receptionist Twin", TWIN_TWO: "Night Auditor Twin"}
        run = ChangeReviewRun(
            id=uuid4(),
            change_id=change.id,
            project_id=PROJECT,
            owner_user_id=OWNER,
            commit=commit,
            reviewed_at=at,
            locale="it-IT",
            requirements_version_number=1,
            design_version_number=1,
            alternative_code="DES-001",
            critiques=tuple(
                TwinCritique(
                    twin_id=twin,
                    twin_name=names[twin],
                    verdict=CritiqueVerdict.CONCERN,
                    summary="La modifica mi aiuta ma manca la data di arrivo che uso.",
                    findings=tuple(
                        CritiqueFinding(
                            severity=FindingSeverity.MEDIUM,
                            text=text,
                            requirement="REQ-001",
                            screen="SCR-001",
                        )
                        for text in texts
                    ),
                )
                for twin in twins
            ),
            alignment=AlignmentVerdict(
                status=AlignmentStatus.ALIGNED,
                summary="Il codice segue il design approvato e i requisiti.",
            ),
        )
        self.store.changes.append(change)
        self.store.runs.append(run)
        return change, run

    def reviewed_test_run(self, *, at, twins=(TWIN_ONE,), run_id=None):
        identifier = uuid4() if run_id is None else run_id
        run = sample_run(run_id=identifier)
        review = sample_review(
            run_id=identifier,
            id=uuid4(),
            reviewed_at=at,
            critiques=tuple(sample_critique(twin_id=twin) for twin in twins),
        )
        reviewed = run.with_review(review)
        self.store.test_runs.append(reviewed)
        return reviewed

    def owner_observation(self, number=1, *, twin=TWIN_ONE, version=None, **values):
        arguments = {
            "twin_id": twin,
            "number": number,
            "statement": f"Il gruppo, osservazione del proprietario {number}.",
            "source": LearningSource.OWNER,
            "added_in_version": number if version is None else version,
            "approved_at": NOW - timedelta(days=2),
        }
        arguments.update(values)
        observation = LearnedObservation(**arguments)
        self.store.observations[number] = observation
        return observation

    def stored_update(self, *, twin=TWIN_ONE, base=0, status=UpdateStatus.PROPOSED, at=None):
        update = TwinUpdate(
            id=uuid4(),
            twin_id=twin,
            twin_name="Receptionist Twin" if twin == TWIN_ONE else "Night Auditor Twin",
            created_at=NOW - timedelta(days=1) if at is None else at,
            locale="it-IT",
            status=status,
            base_profile_version=1,
            base_development_version=base,
            comment=ITALIAN_COMMENT,
            observations=()
            if status is UpdateStatus.EMPTY
            else (
                ProposedObservation(index=0, statement="Il gruppo usa la tastiera.", basis=BASIS),
                ProposedObservation(
                    index=1, statement="Il gruppo stampa ogni ricevuta.", basis=BASIS
                ),
            ),
            material_changes=1,
            material_tests=0,
        )
        self.store.updates.append(update)
        return update


def propose(client, twin=TWIN_ONE, **values):
    return client.post(updates_path(twin), json={**REQUEST, **values})


def test_router_registers_the_six_routes():
    router = create_twin_learning_router()
    methods = sorted(
        (route.path.removeprefix("/projects/{project_id}"), *sorted(route.methods))
        for route in router.routes
    )
    assert methods == [
        ("/twin-learning", "GET"),
        ("/twin-updates/{update_id}", "GET"),
        ("/twin-updates/{update_id}/decision", "POST"),
        ("/user-twins/{twin_id}/observations", "POST"),
        ("/user-twins/{twin_id}/observations/{code}/retire", "POST"),
        ("/user-twins/{twin_id}/updates", "POST"),
    ]


UPDATE_ID = UUID("00000000-0000-4000-8000-000000000d01")
ROUTES = [
    ("GET", "/twin-learning", None),
    ("POST", f"/user-twins/{TWIN_ONE}/updates", REQUEST),
    ("GET", f"/twin-updates/{UPDATE_ID}", None),
    ("POST", f"/twin-updates/{UPDATE_ID}/decision", {"decision": "REJECT"}),
    ("POST", f"/user-twins/{TWIN_ONE}/observations", {"statement": "Il gruppo usa il tablet."}),
    ("POST", f"/user-twins/{TWIN_ONE}/observations/OBS-001/retire", {}),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_every_route_answers_project_not_found_for_another_owner(monkeypatch, method, path, body):
    studio = Studio(monkeypatch, update_answer())
    studio.reviewed_change(at=NOW - timedelta(hours=1))
    studio.owner_observation(1)
    with studio.client() as client:
        studio.app.dependency_overrides[current_user_dependency] = lambda: account(STRANGER)
        answer = client.request(method, f"{PROJECT_PATH}{path}", json=body)
    assert answer.status_code == 404
    assert answer.json() == {"detail": {"code": "PROJECT_NOT_FOUND"}}
    assert studio.calls == []
    assert studio.store.updates == []
    assert list(studio.store.observations) == [1]


def test_a_proposal_asks_the_model_once_with_the_experience_and_stores_the_update(monkeypatch):
    studio = Studio(monkeypatch, three_observations())
    studio.owner_observation(1, statement="Il gruppo usa sempre il telefono.")
    _, run = studio.reviewed_change(at=NOW - timedelta(hours=2), kind=DecisionKind.CODE_TASKS)
    studio.reviewed_change(SECOND, at=NOW - timedelta(hours=1), twins=(TWIN_TWO,))
    test_run = studio.reviewed_test_run(at=NOW - timedelta(minutes=30))
    studio.store.tasks.append(
        {
            "code": "TSK-001",
            "text": "Aggiungere la data di arrivo.",
            "about": {"requirements": ["REQ-001"], "screens": [], "criteria": []},
            "origin": {
                "kind": "CODE_CHANGE",
                "commit": FIRST,
                "test_run_id": None,
                "twin_id": str(TWIN_ONE),
                "twin_name": "Receptionist Twin",
                "finding": FINDING,
            },
            "from_commit": FIRST,
            "created_at": (NOW - timedelta(minutes=90)).isoformat(),
            "status": "OPEN",
            "closed_at": None,
            "note": None,
        }
    )
    with studio.client() as client:
        answer = propose(client)
        stored = client.get(update_path(answer.json()["update"]["id"])).json()
        overview = client.get(LEARNING).json()
    assert answer.status_code == 201, answer.text
    body = answer.json()
    assert list(body) == ["status", "update"]
    assert body["status"] == "PROPOSED"
    update = body["update"]
    [kept] = studio.store.updates
    assert update == kept.to_snapshot() == stored
    assert twin_update_from_snapshot(update) == replace(kept, generation_ids=())
    assert update["twin_id"] == str(TWIN_ONE)
    assert update["twin_name"] == "Receptionist Twin"
    assert update["created_at"] == NOW.isoformat()
    assert (update["locale"], update["status"], update["cost_microusd"]) == ("it-IT", "PROPOSED", 0)
    assert update["base"] == {"profile_version_number": 1, "development_version_number": 1}
    assert update["material"] == {"changes": 1, "tests": 1}
    assert update["decision"] is None
    assert update["comment"] == ITALIAN_COMMENT
    assert [item["index"] for item in update["observations"]] == [0, 1, 2]
    assert update["observations"][2] == {
        "index": 2,
        "statement": "Il gruppo lavora anche di notte.",
        "basis": BASIS,
        "about": {"requirement": None, "screen": "SCR-002"},
        "contradicts_profile": "Il profilo dice che lavora solo di giorno.",
    }
    [call] = studio.calls
    assert (call["task"], call["instruction"], call["retry_schema_errors"]) == (
        UPDATE_TASK,
        UPDATE_INSTRUCTION,
        False,
    )
    context = call["context"]
    assert list(context) == [
        "project_id",
        "purpose",
        "locale",
        "user_twin",
        "project_brief",
        "requirements",
        "design",
        "experience",
        "limits",
    ]
    assert (context["purpose"], context["locale"]) == (UPDATE_PURPOSE, "it-IT")
    assert context["user_twin"]["learned"] == [
        {"code": "OBS-001", "statement": "Il gruppo usa sempre il telefono.", "source": "OWNER"}
    ]
    assert context["user_twin"]["twin_id"] == str(TWIN_ONE)
    [change_item] = context["experience"]["changes"]
    assert change_item["commit"] == FIRST[:8]
    assert change_item["message"] == "Aggiunge la lista degli ospiti"
    assert change_item["reviewed_at"] == run.reviewed_at.isoformat()
    assert (change_item["alignment"], change_item["decision"]) == ("ALIGNED", "CODE_TASKS")
    assert change_item["critique"]["findings"][0]["task"] == {"code": "TSK-001", "status": "OPEN"}
    [test_item] = context["experience"]["tests"]
    assert test_item["finished_at"] == test_run.to_snapshot()["finished_at"]
    assert test_item["critique"]["findings"][0]["text"] == sample_finding().text
    assert context["design"]["screens"] == [
        {"code": "SCR-001", "title": "Create reservation"},
        {"code": "SCR-002", "title": "Reservation confirmation"},
    ]
    assert context["limits"] == {"max_observations": 6}
    evidence = studio.evidence
    assert evidence.kinds() == [(0, "ADAPTER_ACCEPTED"), (0, "APPLICATION_RESULT")]
    assert evidence.payloads("ADAPTER_ACCEPTED") == [
        {
            "result": update,
            "generated_content_hashes": {"TWIN_UPDATE": [snapshot_content_hash(update)]},
        }
    ]
    assert evidence.payloads("APPLICATION_RESULT") == [
        {"status": TwinUpdateStatus.PROPOSED.value, "issue": None}
    ]
    assert TwinUpdateStatus.PROPOSED.value == "TWIN_UPDATE_PROPOSED"
    assert kept.generation_ids == (evidence.generations[0],)
    first, second = overview["twins"]
    assert first["pending_update"] == update
    assert first["new_material"] == {"changes": 0, "tests": 0}
    assert second["pending_update"] is None
    assert second["new_material"] == {"changes": 1, "tests": 0}


def test_a_twin_without_learned_observations_gets_no_learned_key(monkeypatch):
    studio = Studio(monkeypatch, update_answer())
    studio.reviewed_change(at=NOW - timedelta(hours=1), twins=(TWIN_ONE, TWIN_TWO))
    with studio.client() as client:
        answer = propose(client, TWIN_TWO)
    assert answer.status_code == 201, answer.text
    [call] = studio.calls
    assert "learned" not in call["context"]["user_twin"]
    assert call["context"]["user_twin"]["twin_id"] == str(TWIN_TWO)
    assert call["context"]["experience"]["tests"] == []
    assert answer.json()["update"]["base"] == {
        "profile_version_number": 2,
        "development_version_number": 0,
    }
    assert answer.json()["update"]["twin_name"] == "Night Auditor Twin"


def test_an_answer_without_observations_gives_an_empty_update_that_needs_no_decision(monkeypatch):
    studio = Studio(
        monkeypatch,
        update_answer("Le ultime critiche non mi insegnano nulla di nuovo sul gruppo.", []),
        update_answer(),
    )
    studio.reviewed_change(at=NOW - timedelta(hours=1))
    with studio.client() as client:
        empty = propose(client)
        studio.later(minutes=5)
        nothing_new = propose(client)
        studio.reviewed_change(SECOND, at=studio.later(minutes=5))
        studio.later(minutes=5)
        again = propose(client)
        decided = client.post(
            decision_path(empty.json()["update"]["id"]), json={"decision": "REJECT"}
        )
    assert empty.status_code == 201, empty.text
    assert empty.json()["update"]["status"] == "EMPTY"
    assert empty.json()["update"]["observations"] == []
    assert nothing_new.status_code == 409
    assert nothing_new.json() == {"detail": {"code": "TWIN_UPDATE_NOTHING_NEW"}}
    assert again.status_code == 201
    assert again.json()["update"]["status"] == "PROPOSED"
    assert again.json()["update"]["material"] == {"changes": 1, "tests": 0}
    assert decided.status_code == 409
    assert decided.json() == {"detail": {"code": "TWIN_UPDATE_ALREADY_DECIDED"}}
    assert len(studio.calls) == 2


def test_a_proposal_started_as_a_job_answers_as_the_synchronous_one_under_its_key(monkeypatch):
    studio = Studio(monkeypatch, update_answer(), update_answer())
    studio.reviewed_change(at=NOW - timedelta(hours=1), twins=(TWIN_ONE, TWIN_TWO))
    with studio.client() as client:
        synchronous = propose(client)
        started = client.post(updates_path(TWIN_TWO), json=REQUEST, headers=ASYNC)
        assert started.status_code == 202, started.text
        job_id = UUID(started.json()["job_id"])
        client.portal.call(studio.app.state.generation_jobs.wait, job_id)
        job = client.get(f"{JOBS}/{job_id}").json()
        key = studio.app.state.generation_jobs.get(OWNER, PROJECT, job_id).key
    assert started.headers[PREFERENCE_APPLIED] == RESPOND_ASYNC
    assert synchronous.status_code == 201
    assert (job["kind"], job["operation"], job["status"]) == ("REQUEST", "TWIN_UPDATE", "SUCCEEDED")
    first, second = studio.store.updates
    assert synchronous.json() == {"status": "PROPOSED", "update": first.to_snapshot()}
    assert job["response"] == {
        "status_code": 201,
        "body": {"status": "PROPOSED", "update": second.to_snapshot()},
    }
    assert key == request_key(
        GenerationOperation.TWIN_UPDATE,
        {"project_id": str(PROJECT), "twin_id": str(TWIN_TWO)},
        TwinUpdateRequest(locale="it-IT"),
    )
    assert key.startswith(f"TWIN_UPDATE:twin_id={TWIN_TWO}:")


@pytest.mark.parametrize(
    ("setting", "seed", "twin", "status_code", "code"),
    [
        (
            {"modeling": False, "requirements": False, "model": False},
            "pending",
            TWIN_ONE,
            409,
            "USER_MODELING_APPROVAL_REQUIRED",
        ),
        (
            {"requirements": False, "model": False},
            "pending",
            UUID("00000000-0000-4000-8000-00000000abcd"),
            404,
            "USER_TWIN_NOT_FOUND",
        ),
        (
            {"requirements": False, "design": False},
            "pending",
            TWIN_ONE,
            409,
            "REQUIREMENTS_APPROVAL_REQUIRED",
        ),
        ({"design": False}, "pending", TWIN_ONE, 409, "DESIGN_APPROVAL_REQUIRED"),
        ({"model": False}, "pending", TWIN_ONE, 409, "TWIN_UPDATE_PENDING"),
        ({"model": False}, "nothing", TWIN_ONE, 409, "TWIN_UPDATE_NOTHING_NEW"),
        ({"model": False}, "material", TWIN_ONE, 503, "TWIN_UPDATE_MODEL_NOT_CONFIGURED"),
        ({"brief": False}, "material", TWIN_ONE, 404, "PROJECT_NOT_FOUND"),
        ({"modeling": False}, "material", TWIN_ONE, 409, "USER_MODELING_APPROVAL_REQUIRED"),
    ],
)
def test_the_refusals_of_a_proposal_come_in_the_order_of_the_contract(
    monkeypatch, setting, seed, twin, status_code, code
):
    studio = Studio(monkeypatch, update_answer(), **setting)
    pending = None
    if seed == "pending":
        pending = studio.stored_update()
    if seed != "nothing":
        studio.reviewed_change(at=NOW - timedelta(hours=1))
    with studio.client() as client:
        refused = propose(client, twin)
        started = client.post(updates_path(twin), json=REQUEST, headers=ASYNC)
        client.portal.call(studio.app.state.generation_jobs.wait, UUID(started.json()["job_id"]))
        job = client.get(f"{JOBS}/{started.json()['job_id']}").json()
    expected = {"code": code}
    if code == "TWIN_UPDATE_PENDING":
        expected["update_id"] = str(pending.id)
    assert refused.status_code == status_code
    assert refused.json() == {"detail": expected}
    assert job["response"] == {"status_code": status_code, "body": {"detail": expected}}
    assert job["status"] == "FAILED"
    assert studio.calls == []
    assert len(studio.store.updates) == int(pending is not None)
    if studio.evidence is not None:
        assert studio.evidence.events == []


@pytest.mark.parametrize(
    "body",
    [{"locale": "?"}, {"locale": "it-IT", "again": True}, {"locale": 5}, {"locale": "italiano-IT"}],
)
def test_the_body_of_a_proposal_is_validated_before_anything_else(monkeypatch, body):
    studio = Studio(monkeypatch, update_answer(), modeling=False)
    with studio.client() as client:
        refused = client.post(updates_path(), json=body)
        defaulted = client.post(updates_path(), json={})
    assert refused.status_code == 422
    assert refused.json()["detail"] == "invalid_request"
    assert defaulted.status_code == 409
    assert studio.calls == []


def test_an_invalid_answer_is_generated_once_more_and_its_attempt_is_retired(monkeypatch):
    studio = Studio(monkeypatch, update_answer(ENGLISH_COMMENT), update_answer())
    studio.reviewed_change(at=NOW - timedelta(hours=1))
    with studio.client() as client:
        answer = propose(client)
    assert answer.status_code == 201, answer.text
    assert len(studio.calls) == 2
    assert studio.calls[0]["context"] == studio.calls[1]["context"]
    [update] = studio.store.updates
    evidence = studio.evidence
    assert evidence.kinds() == [
        (0, "ADAPTER_REJECTED"),
        (0, "APPLICATION_RESULT"),
        (1, "ADAPTER_ACCEPTED"),
        (1, "APPLICATION_RESULT"),
    ]
    assert evidence.events[0][2] == {
        "code": "ValueError",
        "reason": "the update comment is not written in the language of the project",
    }
    assert evidence.events[1][2] == {"status": "UPDATE_REJECTED", "twin_update_id": str(update.id)}
    [accepted] = evidence.payloads("ADAPTER_ACCEPTED")
    assert accepted["related_generations"] == [
        {
            "role": "TWIN_LEARNER",
            "generation_id": str(evidence.generations[0]),
            "request_hash": "d" * 64,
            "code": "UPDATE_REJECTED",
        }
    ]
    assert update.generation_ids == tuple(evidence.generations)


def test_a_second_invalid_answer_fails_with_invalid_provider_output(monkeypatch):
    studio = Studio(monkeypatch, update_answer("Troppo breve."), update_answer("x"))
    studio.reviewed_change(at=NOW - timedelta(hours=1))
    with studio.client() as client:
        answer = propose(client)
    assert answer.status_code == 502
    assert answer.json() == {
        "detail": {"code": "INVALID_PROVIDER_OUTPUT", "stage": "MODEL_PROPOSAL"}
    }
    assert studio.store.updates == []
    assert studio.evidence.kinds() == [
        (0, "ADAPTER_REJECTED"),
        (0, "APPLICATION_RESULT"),
        (1, "ADAPTER_REJECTED"),
        (1, "APPLICATION_RESULT"),
    ]
    assert [item["reason"] for item in studio.evidence.payloads("ADAPTER_REJECTED")] == [
        "the update comment is shorter than 20 characters",
        "the update comment is shorter than 20 characters",
    ]
    assert studio.evidence.events[-1][2] == {"status": "FAILED", "code": "INVALID_PROVIDER_OUTPUT"}


@pytest.mark.parametrize(
    ("outcomes", "status_code", "calls"),
    [
        ((ProposalGenerationError("RESPONSE_SCHEMA_ERROR"), update_answer()), 201, 2),
        (({"comment": "", "observations": []}, update_answer()), 201, 2),
        (({"comment": "", "observations": []}, {"comment": "", "observations": []}), 502, 2),
        ((ProposalGenerationError("INCOMPLETE_OUTPUT"), update_answer()), 201, 2),
        ((ProposalGenerationError("PROVIDER_UNAVAILABLE"),), 503, 1),
        ((ProposalGenerationError("GENERATION_BUDGET_EXCEEDED"),), 402, 1),
        ((ProposalGenerationError("GENERATION_BUDGET_UNAVAILABLE"),), 503, 1),
        ((ProposalGenerationError("CONTEXT_BUDGET_EXCEEDED"),), 422, 1),
    ],
)
def test_schema_errors_are_retried_once_and_other_failures_are_not(
    monkeypatch, outcomes, status_code, calls
):
    studio = Studio(monkeypatch, *outcomes)
    studio.reviewed_change(at=NOW - timedelta(hours=1))
    with studio.client() as client:
        answer = propose(client)
    assert answer.status_code == status_code, answer.text
    assert len(studio.calls) == calls
    assert len(studio.store.updates) == int(status_code == 201)
    if status_code != 201:
        assert studio.evidence.events[-1][2]["status"] == "FAILED"


def test_the_cost_of_an_update_is_the_sum_read_from_the_evidence(monkeypatch):
    studio = Studio(
        monkeypatch, update_answer(ENGLISH_COMMENT), update_answer(), evidence=CostedEvidence()
    )
    studio.reviewed_change(at=NOW - timedelta(hours=1))
    with studio.client() as client:
        answer = propose(client)
    assert answer.status_code == 201, answer.text
    assert answer.json()["update"]["cost_microusd"] == 100_000 + 152_000
    assert studio.store.updates[0].cost_microusd == 252_000


def test_a_design_that_cannot_be_viewed_answers_its_code_before_any_spending(monkeypatch):
    def unreadable(**_):
        raise DesignEvaluationError("DESIGN_SELECTION_REQUIRED")

    studio = Studio(monkeypatch, update_answer())
    monkeypatch.setattr(twin_learning, "learning_material", unreadable)
    studio.reviewed_change(at=NOW - timedelta(hours=1))
    with studio.client() as client:
        refused = propose(client)
    assert refused.status_code == 409
    assert refused.json() == {"detail": {"code": "DESIGN_SELECTION_REQUIRED"}}
    assert studio.calls == []
    assert studio.store.updates == []


def test_a_proposal_that_finds_another_one_stored_meanwhile_is_refused_as_pending(monkeypatch):
    stored = []

    def racing():
        stored.append(studio.stored_update())
        return update_answer()

    studio = Studio(monkeypatch, racing)
    studio.reviewed_change(at=NOW - timedelta(hours=1))
    with studio.client() as client:
        answer = propose(client)
    assert answer.status_code == 409
    assert answer.json() == {
        "detail": {"code": "TWIN_UPDATE_PENDING", "update_id": str(stored[0].id)}
    }
    assert studio.store.updates == stored
    assert studio.evidence.kinds() == [(0, "ADAPTER_ACCEPTED"), (0, "APPLICATION_RESULT")]


@pytest.mark.parametrize(
    ("status", "decision"),
    [
        (UpdateStatus.EMPTY, None),
        (UpdateStatus.PROPOSED, None),
        (UpdateStatus.PROPOSED, UpdateDecisionKind.APPROVE),
        (UpdateStatus.PROPOSED, UpdateDecisionKind.REJECT),
    ],
)
def test_the_new_material_starts_after_the_latest_update_of_any_status(
    monkeypatch, status, decision
):
    studio = Studio(monkeypatch, model=False)
    studio.reviewed_change(at=NOW - timedelta(days=3))
    studio.reviewed_test_run(at=NOW - timedelta(days=3))
    studio.stored_update(status=UpdateStatus.PROPOSED, at=NOW - timedelta(days=5))
    studio.store.updates[0] = studio.store.updates[0].decided(
        UpdateDecisionKind.REJECT, decided_at=NOW - timedelta(days=5)
    )
    latest = studio.stored_update(status=status, at=NOW - timedelta(days=2))
    if decision is not None:
        kept = (0,) if decision is UpdateDecisionKind.APPROVE else ()
        studio.store.updates[1] = latest.decided(decision, kept=kept, decided_at=NOW)
    studio.reviewed_change(SECOND, at=NOW - timedelta(days=1))
    studio.reviewed_test_run(at=NOW - timedelta(days=1), twins=(TWIN_TWO,))
    with studio.client() as client:
        overview = client.get(LEARNING).json()
    first, second = overview["twins"]
    assert first["new_material"] == {"changes": 1, "tests": 0}
    assert second["new_material"] == {"changes": 0, "tests": 1}
    assert overview["update_available"] is False


def test_the_overview_lists_every_approved_twin_with_its_entry(monkeypatch):
    studio = Studio(monkeypatch)
    studio.owner_observation(1)
    critique_update = studio.stored_update(base=1)
    studio.store.updates[0] = critique_update.decided(
        UpdateDecisionKind.APPROVE, kept=(0, 1), decided_at=NOW - timedelta(hours=20)
    )
    for number, proposal in enumerate(critique_update.observations, 2):
        studio.store.observations[number] = LearnedObservation(
            twin_id=TWIN_ONE,
            number=number,
            statement=proposal.statement,
            source=LearningSource.TWIN_CRITIQUE,
            added_in_version=2,
            approved_at=NOW - timedelta(hours=20),
            basis=BASIS,
            update_id=critique_update.id,
        )
    studio.store.observations[3] = studio.store.observations[3].retire(
        version=3, retired_at=NOW - timedelta(hours=10), reason="Superata."
    )
    pending = studio.stored_update(base=3, at=NOW - timedelta(hours=5))
    with studio.client() as client:
        overview = client.get(LEARNING).json()
    assert list(overview) == ["project_id", "update_available", "twins"]
    assert (overview["project_id"], overview["update_available"]) == (str(PROJECT), True)
    first, second = overview["twins"]
    assert list(first) == [
        "twin_id",
        "twin_name",
        "profile_version_number",
        "development_version_number",
        "label",
        "observations",
        "retired",
        "pending_update",
        "new_material",
    ]
    assert (first["twin_id"], first["twin_name"], first["label"]) == (
        str(TWIN_ONE),
        "Receptionist Twin",
        "1.3",
    )
    assert [item["code"] for item in first["observations"]] == ["OBS-001", "OBS-002"]
    assert first["observations"][1]["update_id"] == str(critique_update.id)
    assert first["retired"] == [
        {
            "code": "OBS-003",
            "statement": "Il gruppo stampa ogni ricevuta.",
            "retired_in_version": 3,
            "retired_at": (NOW - timedelta(hours=10)).isoformat(),
            "reason": "Superata.",
        }
    ]
    assert first["pending_update"] == pending.to_snapshot()
    entry = {
        key: value for key, value in first.items() if key not in ("pending_update", "new_material")
    }
    assert twin_learning_from_snapshot(entry).to_snapshot() == entry
    assert second == {
        "twin_id": str(TWIN_TWO),
        "twin_name": "Night Auditor Twin",
        "profile_version_number": 2,
        "development_version_number": 0,
        "label": "2.0",
        "observations": [],
        "retired": [],
        "pending_update": None,
        "new_material": {"changes": 0, "tests": 0},
    }


def test_the_overview_has_no_twins_while_the_user_modeling_is_not_approved(monkeypatch):
    studio = Studio(monkeypatch, modeling=False)
    studio.owner_observation(1)
    with studio.client() as client:
        overview = client.get(LEARNING).json()
    assert overview == {"project_id": str(PROJECT), "update_available": True, "twins": []}


def test_an_update_is_read_by_its_id(monkeypatch):
    studio = Studio(monkeypatch)
    update = studio.stored_update()
    with studio.client() as client:
        found = client.get(update_path(update.id))
        missing = client.get(update_path(uuid4()))
        malformed = client.get(update_path("not-a-uuid"))
    assert found.status_code == 200
    assert found.json() == update.to_snapshot()
    assert missing.status_code == 404
    assert missing.json() == {"detail": {"code": "TWIN_UPDATE_NOT_FOUND"}}
    assert malformed.status_code == 422


def test_a_database_less_runtime_answers_database_unavailable(monkeypatch):
    studio = Studio(monkeypatch)
    studio.runtime.database_runtime = None
    with pytest.raises(HTTPException) as failure:
        asyncio.run(
            TwinLearningApplication(studio.runtime).overview(
                owner_user_id=OWNER, project_id=PROJECT
            )
        )
    assert failure.value.status_code == 503
    assert failure.value.detail == {"code": "DATABASE_UNAVAILABLE"}


def decide(client, update_id, decision="APPROVE", **values):
    return client.post(decision_path(update_id), json={"decision": decision, **values})


def test_an_approval_adds_the_kept_observations_with_the_edited_statements_as_a_new_version(
    monkeypatch,
):
    studio = Studio(monkeypatch)
    studio.owner_observation(1)
    update = studio.stored_update(base=1)
    decided_at = studio.later(hours=1)
    with studio.client() as client:
        answer = decide(
            client,
            update.id,
            kept=[
                {"index": 1},
                {"index": 0, "statement": "  Il gruppo   usa la tastiera numerica. "},
            ],
            reason="  Utili   entrambe. ",
        )
        stored = client.get(update_path(update.id)).json()
        overview = client.get(LEARNING).json()
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert list(body) == ["status", "update", "twin"]
    assert body["status"] == "DECIDED"
    assert body["update"] == stored
    assert body["update"]["status"] == "APPROVED"
    assert body["update"]["decision"] == {
        "decided_at": decided_at.isoformat(),
        "kept": [0, 1],
        "reason": "Utili entrambe.",
    }
    assert body["update"]["observations"] == [item.to_snapshot() for item in update.observations]
    twin = body["twin"]
    assert (twin["label"], twin["development_version_number"]) == ("1.2", 2)
    assert [item["code"] for item in twin["observations"]] == ["OBS-001", "OBS-002", "OBS-003"]
    assert twin["observations"][1:] == [
        {
            "code": "OBS-002",
            "statement": "Il gruppo usa la tastiera numerica.",
            "basis": BASIS,
            "source": "TWIN_CRITIQUE",
            "about": {"requirement": None, "screen": None},
            "contradicts_profile": None,
            "added_in_version": 2,
            "approved_at": decided_at.isoformat(),
            "update_id": str(update.id),
        },
        {
            "code": "OBS-003",
            "statement": "Il gruppo stampa ogni ricevuta.",
            "basis": BASIS,
            "source": "TWIN_CRITIQUE",
            "about": {"requirement": None, "screen": None},
            "contradicts_profile": None,
            "added_in_version": 2,
            "approved_at": decided_at.isoformat(),
            "update_id": str(update.id),
        },
    ]
    first = overview["twins"][0]
    assert first["pending_update"] is None
    assert {key: first[key] for key in twin} == twin


def test_a_rejection_adds_nothing_and_keeps_its_reason(monkeypatch):
    studio = Studio(monkeypatch)
    update = studio.stored_update()
    with studio.client() as client:
        answer = decide(client, update.id, "REJECT", reason="  Non mi   convince. ")
        again = decide(client, update.id, "REJECT")
    assert answer.status_code == 200, answer.text
    assert answer.json()["update"]["status"] == "REJECTED"
    assert answer.json()["update"]["decision"] == {
        "decided_at": NOW.isoformat(),
        "kept": [],
        "reason": "Non mi convince.",
    }
    assert answer.json()["twin"]["label"] == "1.0"
    assert answer.json()["twin"]["observations"] == []
    assert studio.store.observations == {}
    assert again.status_code == 409
    assert again.json() == {"detail": {"code": "TWIN_UPDATE_ALREADY_DECIDED"}}


def test_an_approval_on_a_twin_that_moved_is_refused_but_a_rejection_closes_it(monkeypatch):
    studio = Studio(monkeypatch)
    update = studio.stored_update(base=0)
    studio.owner_observation(1)
    with studio.client() as client:
        approval = decide(client, update.id, kept=[{"index": 0}])
        rejection = decide(client, update.id, "REJECT")
    assert approval.status_code == 409
    assert approval.json() == {"detail": {"code": "TWIN_UPDATE_CONTEXT_CHANGED"}}
    assert rejection.status_code == 200
    assert rejection.json()["update"]["status"] == "REJECTED"
    assert list(studio.store.observations) == [1]


def test_an_approval_beyond_twenty_active_observations_is_refused(monkeypatch):
    studio = Studio(monkeypatch)
    for number in range(1, 20):
        studio.owner_observation(number, version=1)
    retired = studio.owner_observation(20, version=1).retire(version=2, retired_at=NOW)
    studio.store.observations[20] = retired
    update = studio.stored_update(base=2)
    with studio.client() as client:
        refused = decide(client, update.id, kept=[{"index": 0}, {"index": 1}])
        kept = decide(client, update.id, kept=[{"index": 1}])
    assert refused.status_code == 409
    assert refused.json() == {"detail": {"code": "TWIN_OBSERVATIONS_LIMIT"}}
    assert kept.status_code == 200
    assert len(kept.json()["twin"]["observations"]) == 20
    assert kept.json()["twin"]["observations"][-1]["code"] == "OBS-021"


def test_an_index_outside_the_proposal_is_refused_after_the_conflicts(monkeypatch):
    studio = Studio(monkeypatch)
    update = studio.stored_update()
    with studio.client() as client:
        refused = decide(client, update.id, kept=[{"index": 0}, {"index": 5}])
    assert refused.status_code == 422
    assert refused.json() == {
        "detail": {
            "code": "invalid_request",
            "errors": [
                {
                    "loc": ["body", "kept", 1, "index"],
                    "type": "value_error",
                    "msg": "the proposal has no observation at this index",
                }
            ],
        }
    }
    assert studio.store.updates == [update]
    assert studio.store.observations == {}


def unknown_update(studio):
    studio.stored_update()
    return uuid4()


def decided_moved_and_full(studio):
    update = studio.stored_update(base=0)
    studio.store.updates[0] = update.decided(UpdateDecisionKind.REJECT, decided_at=NOW)
    for number in range(1, 21):
        studio.owner_observation(number, version=1)
    return update.id


def moved_and_full(studio):
    update = studio.stored_update(base=0)
    for number in range(1, 21):
        studio.owner_observation(number, version=1)
    return update.id


def full(studio):
    for number in range(1, 20):
        studio.owner_observation(number, version=1)
    return studio.stored_update(base=1).id


@pytest.mark.parametrize(
    ("seed", "status_code", "code"),
    [
        (unknown_update, 404, "TWIN_UPDATE_NOT_FOUND"),
        (decided_moved_and_full, 409, "TWIN_UPDATE_ALREADY_DECIDED"),
        (moved_and_full, 409, "TWIN_UPDATE_CONTEXT_CHANGED"),
        (full, 409, "TWIN_OBSERVATIONS_LIMIT"),
    ],
)
def test_the_refusals_of_a_decision_come_in_the_order_of_the_contract(
    monkeypatch, seed, status_code, code
):
    studio = Studio(monkeypatch)
    update_id = seed(studio)
    observations = dict(studio.store.observations)
    with studio.client() as client:
        refused = decide(client, update_id, kept=[{"index": 0}, {"index": 1}, {"index": 4}])
    assert refused.status_code == status_code
    assert refused.json() == {"detail": {"code": code}}
    assert studio.store.observations == observations


@pytest.mark.parametrize(
    "body",
    [
        {"decision": "APPROVE"},
        {"decision": "APPROVE", "kept": []},
        {"decision": "REJECT", "kept": [{"index": 0}]},
        {"decision": "APPROVE", "kept": [{"index": 0}, {"index": 0}]},
        {"decision": "APPROVE", "kept": [{"index": -1}]},
        {"decision": "APPROVE", "kept": [{"index": 0, "statement": "   "}]},
        {"decision": "APPROVE", "kept": [{"index": 0, "statement": ""}]},
        {"decision": "APPROVE", "kept": [{"index": 0, "statement": "x" * 401}]},
        {"decision": "APPROVE", "kept": [{"index": 0, "extra": True}]},
        {"decision": "APPROVE", "kept": [{"index": index} for index in range(7)]},
        {"decision": "REJECT", "reason": "x" * 301},
        {"decision": "REJECT", "note": "Una nota."},
        {"decision": "LATER"},
        {"kept": [{"index": 0}]},
        {},
    ],
)
def test_a_decision_body_is_validated(monkeypatch, body):
    studio = Studio(monkeypatch)
    update = studio.stored_update()
    with studio.client() as client:
        refused = client.post(decision_path(update.id), json=body)
    assert refused.status_code == 422
    assert refused.json()["detail"] == "invalid_request"
    assert studio.store.updates == [update]


def test_a_decision_on_a_twin_outside_the_approved_user_modeling_keeps_the_name_of_the_update(
    monkeypatch,
):
    studio = Studio(monkeypatch, modeling=False)
    update = studio.stored_update()
    with studio.client() as client:
        answer = decide(client, update.id, kept=[{"index": 0}])
    assert answer.status_code == 200, answer.text
    twin = answer.json()["twin"]
    assert (twin["twin_name"], twin["profile_version_number"], twin["label"]) == (
        "Receptionist Twin",
        1,
        "1.1",
    )


def learn(client, twin=TWIN_ONE, **body):
    return client.post(observations_path(twin), json=body)


def test_the_owner_writes_an_observation_as_a_new_version(monkeypatch):
    studio = Studio(monkeypatch)
    studio.owner_observation(1)
    approved_at = studio.later(hours=1)
    with studio.client() as client:
        answer = learn(
            client,
            statement="  Il gruppo   usa il tablet. ",
            about={"requirement": "REQ-001", "screen": None},
        )
        plain = learn(client, TWIN_TWO, statement="Il gruppo lavora di notte.")
    assert answer.status_code == 201, answer.text
    assert list(answer.json()) == ["status", "twin"]
    assert answer.json()["status"] == "LEARNED"
    twin = answer.json()["twin"]
    assert twin["label"] == "1.2"
    assert twin["observations"][1] == {
        "code": "OBS-002",
        "statement": "Il gruppo usa il tablet.",
        "basis": None,
        "source": "OWNER",
        "about": {"requirement": "REQ-001", "screen": None},
        "contradicts_profile": None,
        "added_in_version": 2,
        "approved_at": approved_at.isoformat(),
        "update_id": None,
    }
    assert plain.status_code == 201
    other = plain.json()["twin"]
    assert (other["twin_id"], other["label"]) == (str(TWIN_TWO), "2.1")
    assert other["observations"][0]["code"] == "OBS-003"
    assert other["observations"][0]["about"] == {"requirement": None, "screen": None}


def full_with_pending(studio):
    for number in range(1, 21):
        studio.owner_observation(number, version=1)
    studio.stored_update(base=1)


@pytest.mark.parametrize(
    ("setting", "seed", "twin", "status_code", "code"),
    [
        ({"modeling": False}, full_with_pending, TWIN_ONE, 409, "USER_MODELING_APPROVAL_REQUIRED"),
        (
            {},
            full_with_pending,
            UUID("00000000-0000-4000-8000-00000000abcd"),
            404,
            "USER_TWIN_NOT_FOUND",
        ),
        ({}, full_with_pending, TWIN_ONE, 409, "TWIN_OBSERVATIONS_LIMIT"),
        ({}, lambda studio: studio.stored_update(), TWIN_ONE, 409, "TWIN_UPDATE_PENDING"),
    ],
)
def test_the_refusals_of_an_observation_of_the_owner_come_in_order(
    monkeypatch, setting, seed, twin, status_code, code
):
    studio = Studio(monkeypatch, **setting)
    seed(studio)
    observations = dict(studio.store.observations)
    with studio.client() as client:
        refused = learn(client, twin, statement="Il gruppo usa il tablet.")
    expected = {"code": code}
    if code == "TWIN_UPDATE_PENDING":
        expected["update_id"] = str(studio.store.updates[0].id)
    assert refused.status_code == status_code
    assert refused.json() == {"detail": expected}
    assert studio.store.observations == observations


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"statement": ""},
        {"statement": "   "},
        {"statement": "x" * 401},
        {"statement": None},
        {"statement": "Il gruppo usa il tablet.", "about": {"requirement": "REQ-1"}},
        {"statement": "Il gruppo usa il tablet.", "about": {"screen": "scr-001"}},
        {"statement": "Il gruppo usa il tablet.", "about": {"file": "src/app.js"}},
        {"statement": "Il gruppo usa il tablet.", "source": "OWNER"},
        {"statement": "Il gruppo usa il tablet.", "basis": "Perché sì."},
    ],
)
def test_the_body_of_an_observation_is_validated(monkeypatch, body):
    studio = Studio(monkeypatch)
    with studio.client() as client:
        refused = client.post(observations_path(), json=body)
    assert refused.status_code == 422
    assert refused.json()["detail"] == "invalid_request"
    assert studio.store.observations == {}


def retire(client, code, twin=TWIN_ONE, **body):
    return client.post(retire_path(code, twin), json=body)


def test_an_observation_is_retired_as_a_new_version(monkeypatch):
    studio = Studio(monkeypatch)
    studio.owner_observation(1)
    studio.owner_observation(2)
    retired_at = studio.later(hours=1)
    with studio.client() as client:
        answer = retire(client, "obs-001", reason="  Non   vale più. ")
        second = retire(client, "OBS-002")
    assert answer.status_code == 200, answer.text
    assert list(answer.json()) == ["status", "twin"]
    assert answer.json()["status"] == "RETIRED"
    twin = answer.json()["twin"]
    assert twin["label"] == "1.3"
    assert [item["code"] for item in twin["observations"]] == ["OBS-002"]
    assert twin["retired"] == [
        {
            "code": "OBS-001",
            "statement": "Il gruppo, osservazione del proprietario 1.",
            "retired_in_version": 3,
            "retired_at": retired_at.isoformat(),
            "reason": "Non vale più.",
        }
    ]
    assert second.status_code == 200
    assert second.json()["twin"]["label"] == "1.4"
    assert [item["reason"] for item in second.json()["twin"]["retired"]] == ["Non vale più.", None]


def retired_first(studio):
    studio.owner_observation(1)
    studio.store.observations[1] = studio.store.observations[1].retire(version=2, retired_at=NOW)


@pytest.mark.parametrize(
    ("setting", "seed", "code_path", "twin", "status_code", "code"),
    [
        (
            {"modeling": False},
            lambda studio: studio.owner_observation(1),
            "OBS-001",
            TWIN_ONE,
            409,
            "USER_MODELING_APPROVAL_REQUIRED",
        ),
        (
            {},
            lambda studio: studio.owner_observation(1),
            "OBS-001",
            UUID("00000000-0000-4000-8000-00000000abcd"),
            404,
            "USER_TWIN_NOT_FOUND",
        ),
        (
            {},
            lambda studio: studio.owner_observation(1),
            "OBS-009",
            TWIN_ONE,
            404,
            "TWIN_OBSERVATION_NOT_FOUND",
        ),
        (
            {},
            lambda studio: studio.owner_observation(1),
            "TSK-001",
            TWIN_ONE,
            404,
            "TWIN_OBSERVATION_NOT_FOUND",
        ),
        (
            {},
            lambda studio: studio.owner_observation(1),
            "OBS-1",
            TWIN_ONE,
            404,
            "TWIN_OBSERVATION_NOT_FOUND",
        ),
        (
            {},
            lambda studio: studio.owner_observation(1, twin=TWIN_TWO),
            "OBS-001",
            TWIN_ONE,
            404,
            "TWIN_OBSERVATION_NOT_FOUND",
        ),
        ({}, retired_first, "OBS-001", TWIN_ONE, 404, "TWIN_OBSERVATION_NOT_FOUND"),
        (
            {},
            lambda studio: (studio.owner_observation(1), studio.stored_update(base=1)),
            "OBS-001",
            TWIN_ONE,
            409,
            "TWIN_UPDATE_PENDING",
        ),
    ],
)
def test_the_refusals_of_a_retirement_come_in_order(
    monkeypatch, setting, seed, code_path, twin, status_code, code
):
    studio = Studio(monkeypatch, **setting)
    seed(studio)
    observations = dict(studio.store.observations)
    with studio.client() as client:
        refused = retire(client, code_path, twin)
    expected = {"code": code}
    if code == "TWIN_UPDATE_PENDING":
        expected["update_id"] = str(studio.store.updates[0].id)
    assert refused.status_code == status_code
    assert refused.json() == {"detail": expected}
    assert studio.store.observations == observations


@pytest.mark.parametrize("body", [{"reason": "x" * 301}, {"reason": 5}, {"why": "Superata."}])
def test_the_body_of_a_retirement_is_validated(monkeypatch, body):
    studio = Studio(monkeypatch)
    studio.owner_observation(1)
    with studio.client() as client:
        refused = client.post(retire_path("OBS-001"), json=body)
        missing = client.post(retire_path("OBS-001"))
    assert refused.status_code == 422
    assert refused.json()["detail"] == "invalid_request"
    assert missing.status_code == 422
    assert studio.store.observations[1].active
