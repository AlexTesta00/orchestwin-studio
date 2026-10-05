import asyncio
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest

from orchestwin.artifacts import workflow_inputs_runtime as runtime
from orchestwin.artifacts.provided_prototypes import provided_prototype_from_snapshot
from orchestwin.workflow.gates import (
    HumanGateAction,
    HumanGateEventKind,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)
from orchestwin.workflow_inputs import WorkflowInputError, decision_content_hash, workflow_records
from src.test.python.api.test_artifact_why import NOW, OWNER_ID, PROJECT_ID
from src.test.python.artifacts.test_generated_mockup_support import BASE_CODES, requirement_ids
from src.test.python.artifacts.test_provided_prototypes36 import (
    DEFINITION,
    input_payload,
    prototype,
)


class Transaction:
    def __init__(self, store):
        self.store = store

    async def __aenter__(self):
        self.before = (
            list(self.store.decisions),
            list(self.store.prototypes),
            self.store.gate,
            list(self.store.events),
        )
        return self

    async def __aexit__(self, kind, error, traceback):
        if error is None:
            self.store.commits += 1
        else:
            self.store.decisions, self.store.prototypes, self.store.gate, self.store.events = (
                self.before
            )
            self.store.rollbacks += 1


class Session:
    def __init__(self, store):
        self.store = store

    async def __aenter__(self):
        return self

    async def __aexit__(self, kind, error, traceback):
        return None

    def begin(self):
        return Transaction(self.store)


def runtime_setup(monkeypatch):
    store = SimpleNamespace(
        decisions=[], prototypes=[], gate=None, events=[], audit=[], commits=0, rollbacks=0
    )
    definition = SimpleNamespace(
        id=UUID(DEFINITION["artifact_id"]),
        version_number=DEFINITION["version_number"],
        content_hash=DEFINITION["content_hash"],
        specification=SimpleNamespace(
            requirements=tuple(
                SimpleNamespace(code=code, id=identity)
                for code, identity in requirement_ids(BASE_CODES).items()
            )
        ),
    )

    class Repository:
        def __init__(self, session, *, owner_user_id):
            assert session.store is store
            self.owner = owner_user_id

        async def owned(self, project_id, *, lock=False):
            allowed = self.owner == OWNER_ID and project_id == PROJECT_ID
            store.audit.append(("owned", self.owner, project_id, lock))
            return allowed

        async def records(self, project_id):
            assert await self.owned(project_id)
            return workflow_records(
                project_id, store.decisions, [item.to_snapshot() for item in store.prototypes]
            )

        async def current(self, project_id):
            assert await self.owned(project_id)
            return store.prototypes[-1] if store.prototypes else None

        async def append_decision(self, decision):
            assert await self.owned(UUID(decision["project_id"]))
            store.decisions.append(decision)
            store.audit.append(("decision", decision["content_hash"]))

        async def append_prototype(self, value):
            assert await self.owned(value.project_id)
            store.prototypes.append(value)
            store.audit.append(("prototype", value.id, value.version_number, value.content_hash))

    class Gates:
        def __init__(self, session):
            assert session.store is store

        async def get_latest_owned_for_update(self, *, owner_user_id, project_id, gate_type):
            assert owner_user_id == OWNER_ID and project_id == PROJECT_ID
            assert gate_type is HumanGateType.DESIGN
            return store.gate

        async def list_events_owned(self, *, project_id, owner_user_id, gate_id):
            assert owner_user_id == OWNER_ID and project_id == PROJECT_ID
            assert gate_id == store.gate.id
            return tuple(store.events)

        async def add_with_event(self, *, gate, event):
            assert event.kind is HumanGateEventKind.SUBMIT
            store.gate = gate
            store.events.append(event)
            store.audit.append(("submit", gate.artifact))

        async def save_transition(self, *, previous_gate, updated_gate, event):
            assert previous_gate == store.gate
            store.gate = updated_gate
            store.events.append(event)
            store.audit.append(("transition", event.kind, updated_gate.artifact))

    async def current_inputs(session, *, owner_user_id, project_id):
        assert session.store is store and owner_user_id == OWNER_ID and project_id == PROJECT_ID
        return {"REQUIREMENTS": definition}

    async def ready_definition(session, *, owner_user_id, project_id):
        assert session.store is store and owner_user_id == OWNER_ID and project_id == PROJECT_ID
        return definition

    async def latest_gate(session, *, owner_user_id, project_id, gate_type):
        assert session.store is store and owner_user_id == OWNER_ID and project_id == PROJECT_ID
        assert gate_type is HumanGateType.DESIGN
        return store.gate

    monkeypatch.setattr(runtime, "SqlAlchemyWorkflowInputsRepository", Repository)
    monkeypatch.setattr(runtime, "SqlAlchemyHumanGateRepository", Gates)
    monkeypatch.setattr(runtime, "current_inputs", current_inputs)
    monkeypatch.setattr(runtime, "ready_definition", ready_definition)
    monkeypatch.setattr(runtime, "latest_gate", latest_gate)
    service = runtime.SqlAlchemyWorkflowInputsService(lambda: Session(store), clock=lambda: NOW)
    return SimpleNamespace(store=store, definition=definition, service=service)


def supplied_request():
    return input_payload() | {
        "expected_definition_reference": dict(DEFINITION),
        "expected_version_number": 0,
        "declared_origin": "Figma desktop",
    }


def invoke(setup, method, **values):
    return asyncio.run(
        getattr(setup.service, method)(owner_user_id=OWNER_ID, project_id=PROJECT_ID, **values)
    )


def test_runtime_declaration_preserves_lf_and_exact_context_without_filling_artifacts(monkeypatch):
    setup = runtime_setup(monkeypatch)
    result = invoke(
        setup,
        "declare",
        request={
            "target": "EVIDENCE",
            "action": "DECLARE_MISSING",
            "reason": "Missing interviews.\r\nAwait field research.",
            "base_context": {"REQUIREMENTS": dict(DEFINITION)},
        },
    )
    assert result["reason"] == "Missing interviews.\nAwait field research."
    assert result["base_context"] == {"REQUIREMENTS": dict(DEFINITION)}
    assert result["content_hash"] == decision_content_hash(result)
    assert result["sequence"] == 1
    assert not setup.store.prototypes and setup.store.gate is None
    assert invoke(setup, "records")["decisions"] == [result]


@pytest.mark.parametrize(
    "payload,code",
    [
        ({"target": "EVIDENCE", "action": "DECLARE_MISSING"}, "WORKFLOW_REASON_INVALID"),
        (
            {"target": "EVIDENCE", "action": "DECLARE_MISSING", "reason": " ", "unknown": True},
            "WORKFLOW_RECORDS_INVALID",
        ),
        (
            {
                "target": "EVIDENCE",
                "action": "DECLARE_MISSING",
                "reason": "Missing.",
                "base_context": {"REQUIREMENTS": dict(DEFINITION) | {"content_hash": "b" * 64}},
            },
            "WORKFLOW_CONTEXT_CHANGED",
        ),
    ],
)
def test_runtime_invalid_declaration_rolls_back_without_records(monkeypatch, payload, code):
    setup = runtime_setup(monkeypatch)
    with pytest.raises(WorkflowInputError) as caught:
        invoke(setup, "declare", request=payload)
    assert caught.value.code == code
    assert not setup.store.decisions and setup.store.commits == 0


def test_runtime_supplied_prototype_has_real_bound_hash_and_two_distinct_gate_actions(monkeypatch):
    setup = runtime_setup(monkeypatch)
    payload = supplied_request()
    original = deepcopy(payload)
    saved = invoke(setup, "save_prototype", request=payload)
    assert payload == original
    assert provided_prototype_from_snapshot(saved).to_snapshot() == saved
    assert saved["declared_origin"] == "Figma desktop"
    state = invoke(setup, "state")
    assert state["source"] == "PROVIDED_PROTOTYPE"
    assert state["context_current"] and not state["approved"]
    assert state["gate"] is None
    with pytest.raises(WorkflowInputError, match="WORKFLOW_CONTEXT_CHANGED"):
        invoke(setup, "gate_action", action="APPROVE")
    submitted = invoke(setup, "gate_action", action="SUBMIT")
    assert submitted["status"] == "PENDING_APPROVAL"
    assert not invoke(setup, "state")["approved"]
    approved = invoke(setup, "gate_action", action="APPROVE")
    assert approved["status"] == "APPROVED"
    assert invoke(setup, "state")["approved"]
    assert [event.kind for event in setup.store.events] == [
        HumanGateEventKind.SUBMIT,
        HumanGateEventKind.APPROVE,
    ]
    artifact = setup.store.gate.artifact
    assert str(artifact.artifact_id) == saved["id"]
    assert (
        artifact.version == saved["version_number"]
        and artifact.content_hash == saved["content_hash"]
    )


@pytest.mark.parametrize(
    "case,code",
    [
        ("hash", "WORKFLOW_CONTEXT_CHANGED"),
        ("version", "PROVIDED_PROTOTYPE_VERSION_CONFLICT"),
        ("boolean", "PROVIDED_PROTOTYPE_VERSION_CONFLICT"),
        ("fields", "PROVIDED_PROTOTYPE_INPUT_INVALID"),
        ("one_screen", "SCREEN_COUNT"),
        ("reference", "PROVIDED_PROTOTYPE_REQUIREMENT_REFERENCE_INVALID"),
    ],
)
def test_runtime_rejects_inexact_definition_and_invalid_prototype_without_a_gate(
    monkeypatch, case, code
):
    setup = runtime_setup(monkeypatch)
    request = supplied_request()
    if case == "hash":
        request["expected_definition_reference"]["content_hash"] = "b" * 64
    elif case == "version":
        request["expected_version_number"] = 1
    elif case == "boolean":
        request["expected_version_number"] = False
    elif case == "fields":
        request["unknown"] = "Unsupported"
    elif case == "one_screen":
        request["mockup"]["screens"] = request["mockup"]["screens"][:1]
    else:
        for screen in request["mockup"]["screens"]:
            screen["markup"] = screen["markup"].replace("REQ-001", "REQ-999")
    with pytest.raises(WorkflowInputError) as caught:
        invoke(setup, "save_prototype", request=request)
    assert caught.value.code == code
    assert not setup.store.prototypes and setup.store.gate is None
    assert setup.store.commits == 0


def test_runtime_revising_supplied_prototype_stales_the_exact_previous_approval(monkeypatch):
    setup = runtime_setup(monkeypatch)
    first = invoke(setup, "save_prototype", request=supplied_request())
    invoke(setup, "gate_action", action="SUBMIT")
    invoke(setup, "gate_action", action="APPROVE")
    next_request = supplied_request() | {
        "expected_version_number": 1,
        "declared_origin": "Updated supplied mockup",
    }
    second = invoke(setup, "save_prototype", request=next_request)
    assert first["id"] == second["id"] and first["content_hash"] != second["content_hash"]
    assert second["version_number"] == 2 and second["based_on_version_number"] == 1
    state = invoke(setup, "state")
    assert state["source"] == "PROVIDED_PROTOTYPE" and not state["approved"]
    assert state["gate"]["status"] == "STALE"


def test_runtime_other_owner_cannot_read_or_write_the_existing_prototype(monkeypatch):
    setup = runtime_setup(monkeypatch)
    saved = invoke(setup, "save_prototype", request=supplied_request())
    assert (
        asyncio.run(setup.service.records(owner_user_id=UUID(int=9000), project_id=PROJECT_ID))
        is None
    )
    for method, values in (
        ("current", {}),
        ("state", {}),
        ("save_prototype", {"request": supplied_request()}),
        ("gate_action", {"action": "SUBMIT"}),
        ("document", {"prototype_id": UUID(saved["id"])}),
    ):
        with pytest.raises(WorkflowInputError, match="PROJECT_NOT_FOUND"):
            asyncio.run(
                getattr(setup.service, method)(
                    owner_user_id=UUID(int=9000), project_id=PROJECT_ID, **values
                )
            )
    assert len(setup.store.prototypes) == 1 and setup.store.gate is None


def test_runtime_context_change_removes_approval_and_document_uses_static_sandbox_policy(
    monkeypatch,
):
    setup = runtime_setup(monkeypatch)
    saved = invoke(setup, "save_prototype", request=supplied_request())
    invoke(setup, "gate_action", action="SUBMIT")
    invoke(setup, "gate_action", action="APPROVE")
    setup.definition.version_number = 2
    state = invoke(setup, "state")
    assert not state["context_current"] and not state["approved"]
    with pytest.raises(WorkflowInputError, match="WORKFLOW_CONTEXT_CHANGED"):
        invoke(setup, "gate_action", action="APPROVE")
    document = invoke(setup, "document", prototype_id=UUID(saved["id"]))
    assert "Content-Security-Policy" in document["html"]
    assert "default-src 'none'" in document["html"]
    assert "form-action 'none'" in document["html"]


def test_ready_definition_checks_every_approved_hash_and_internal_reference(monkeypatch):
    definition = SimpleNamespace(
        id=UUID(DEFINITION["artifact_id"]), version_number=1, content_hash="a" * 64
    )
    values = {
        key: SimpleNamespace(
            id=UUID(int=900 + index), version_number=1, content_hash=str(index) * 64
        )
        for index, key in enumerate(("BRIEF", "TEAM", "USER_TWINS"), start=1)
    }
    values["USER_TWINS"].snapshot = SimpleNamespace(
        twin_versions=[
            SimpleNamespace(twin_id=UUID(int=950), version_number=1, content_hash="b" * 64)
        ]
    )
    definition.specification = SimpleNamespace(
        project_brief_reference=SimpleNamespace(
            artifact_id=values["BRIEF"].id,
            version_number=1,
            content_hash=values["BRIEF"].content_hash,
        ),
        agent_team_reference=SimpleNamespace(
            artifact_id=values["TEAM"].id,
            version_number=1,
            content_hash=values["TEAM"].content_hash,
        ),
        user_modeling_reference=SimpleNamespace(
            artifact_id=values["USER_TWINS"].id,
            version_number=1,
            content_hash=values["USER_TWINS"].content_hash,
        ),
        user_twin_references=[
            SimpleNamespace(twin_id=UUID(int=950), version_number=1, content_hash="b" * 64)
        ],
    )
    values["REQUIREMENTS"] = definition
    values["TEAM"].proposal = SimpleNamespace(
        brief_version_id=values["BRIEF"].id,
        brief_version_number=1,
        brief_content_hash=values["BRIEF"].content_hash,
    )
    values[
        "USER_TWINS"
    ].snapshot.project_brief_reference = definition.specification.project_brief_reference
    values[
        "USER_TWINS"
    ].snapshot.agent_team_reference = definition.specification.agent_team_reference
    gates = {}
    for key, kind in (
        ("BRIEF", HumanGateType.PROJECT_BRIEF),
        ("TEAM", HumanGateType.AGENT_TEAM),
        ("USER_TWINS", HumanGateType.USER_MODELING),
        ("REQUIREMENTS", HumanGateType.REQUIREMENTS),
    ):
        value = values[key]
        gate = create_human_gate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            gate_type=kind,
            artifact=replace(
                runtime.prototype_artifact(prototype(project_id=PROJECT_ID)),
                gate_type=kind,
                artifact_id=value.id,
                version=1,
                content_hash=value.content_hash,
            ),
            created_at=NOW,
        )
        submitted = transition_human_gate(
            gate, action=HumanGateAction.SUBMIT, actor_user_id=OWNER_ID, occurred_at=NOW
        )
        gates[kind] = transition_human_gate(
            submitted.gate, action=HumanGateAction.APPROVE, actor_user_id=OWNER_ID, occurred_at=NOW
        ).gate

    async def current_inputs(session, **scope):
        return values

    async def latest_gate(session, *, gate_type, **scope):
        return gates.get(gate_type)

    monkeypatch.setattr(runtime, "current_inputs", current_inputs)
    monkeypatch.setattr(runtime, "latest_gate", latest_gate)
    archetypes = SimpleNamespace(current=True)

    class Personas:
        def __init__(self, session, *, owner_user_id):
            assert owner_user_id == OWNER_ID

        async def list_current(self, *, project_id):
            assert project_id == PROJECT_ID
            return ["current-archetype"]

    def matches(snapshot, personas):
        assert snapshot is values["USER_TWINS"] and personas == ["current-archetype"]
        return archetypes.current

    monkeypatch.setattr(runtime, "SqlAlchemyPersonaVersionRepository", Personas)
    monkeypatch.setattr(runtime, "snapshot_matches_archetypes", matches)
    scope = dict(owner_user_id=OWNER_ID, project_id=PROJECT_ID)
    assert asyncio.run(runtime.ready_definition(object(), **scope)) is definition
    values["TEAM"].proposal.brief_content_hash = "e" * 64
    with pytest.raises(WorkflowInputError, match="WORKFLOW_CONTEXT_CHANGED"):
        asyncio.run(runtime.ready_definition(object(), **scope))
    values["TEAM"].proposal.brief_content_hash = values["BRIEF"].content_hash
    for _key, kind in (
        ("BRIEF", HumanGateType.PROJECT_BRIEF),
        ("TEAM", HumanGateType.AGENT_TEAM),
        ("USER_TWINS", HumanGateType.USER_MODELING),
        ("REQUIREMENTS", HumanGateType.REQUIREMENTS),
    ):
        old = gates[kind]
        gates[kind] = replace(old, artifact=replace(old.artifact, content_hash="e" * 64))
        with pytest.raises(WorkflowInputError, match="REQUIREMENTS_APPROVAL_REQUIRED"):
            asyncio.run(runtime.ready_definition(object(), **scope))
        gates[kind] = old
    definition.specification.user_twin_references[0].content_hash = "c" * 64
    with pytest.raises(WorkflowInputError, match="WORKFLOW_CONTEXT_CHANGED"):
        asyncio.run(runtime.ready_definition(object(), **scope))
    definition.specification.user_twin_references[0].content_hash = "b" * 64
    archetypes.current = False
    with pytest.raises(WorkflowInputError, match="WORKFLOW_CONTEXT_CHANGED"):
        asyncio.run(runtime.ready_definition(object(), **scope))
