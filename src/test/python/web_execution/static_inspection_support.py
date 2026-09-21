"""Transactional memory port and Docker transport doubles, never empirical evidence."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from orchestwin.web_execution.static_browser_executor import execute_static_browser_job
from orchestwin.web_execution.static_inspection_backend import verify_inspection_result
from orchestwin.web_execution.static_inspections import (
    InspectionError,
    InspectionPlan,
    SourceContext,
    StaticInspectionService,
)
from orchestwin.workflow.gates import GateArtifactReference, HumanGateType

from .static_browser_support import IMAGE_ID, DockerTransport, make_observation

NOW = datetime(2026, 9, 9, tzinfo=UTC)
ARCHITECTURE_ID = UUID(int=6801)


class MemoryStore:
    def __init__(self, context, owner):
        self.context = context
        self.owner = owner
        self.project = context.architecture.project_id
        self.records = {}
        self.gates = {}
        self.events = []
        self.latest = None
        self.lock = asyncio.Lock()
        self.opened = 0
        self.active = True
        self.fail_update = False

    @asynccontextmanager
    async def scope(self, *, owner_user_id, project_id):
        if not self.active or owner_user_id != self.owner or project_id != self.project:
            raise InspectionError("STATIC_INSPECTION_PROJECT_NOT_FOUND", 404)
        async with self.lock:
            backup = (dict(self.records), dict(self.gates), list(self.events), self.latest)
            self.opened += 1
            try:
                yield self
            except BaseException:
                self.records, self.gates, self.events, self.latest = backup
                raise
            finally:
                self.opened -= 1

    async def get(self, request_id):
        return self.records.get(request_id)

    async def history(self):
        return tuple(self.records.values())

    async def source_context(self, revision_id):
        if str(revision_id) != self.context.revision["id"]:
            raise InspectionError("STATIC_INSPECTION_SOURCE_NOT_CURRENT")
        return self.context

    async def latest_gate(self):
        return None if self.latest is None else self.gates[self.latest]

    async def gate(self, gate_id):
        return self.gates[gate_id]

    async def add_gate(self, gate, event):
        self.latest = gate.id
        self.gates[gate.id] = gate
        self.events.append(event)

    async def save_gate(self, previous, updated, event):
        assert self.gates[previous.id] == previous
        self.gates[updated.id] = updated
        self.events.append(event)

    async def insert(self, inspection):
        assert inspection.id not in self.records
        self.records[inspection.id] = inspection

    async def update(self, previous, updated):
        if self.fail_update:
            raise InspectionError("TEST_STORE_UPDATE_FAILED")
        assert self.records[previous.id] == previous
        self.records[previous.id] = updated


class Backend:
    def __init__(self, root, runner_manifest, job, context, output, store):
        self.root = root
        self.runner_manifest = runner_manifest
        self.job = job
        self.context = context
        self.output = output
        self.store = store
        self.calls = []
        self.changed_binding = False
        self.assertions_fail = False
        self.fail = None
        self.before_authority = None
        self.cancel_after_evidence = False
        self.started = asyncio.Event()
        self.release = None

    async def plan(self, context, scenarios):
        return InspectionPlan(
            replace(self.job, scenarios=scenarios), context.architecture, "c" * 40, IMAGE_ID
        )

    async def check_binding(self, plan):
        if self.changed_binding:
            raise InspectionError("STATIC_INSPECTION_RUNTIME_CHANGED_REPLAN_REQUIRED")

    async def execute(self, inspection, authorize):
        assert self.store.opened == 0, "Docker must not run inside a database transaction"
        self.calls.append(inspection.id)
        self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.before_authority is not None:
            self.before_authority()
        transport = DockerTransport(
            self.root, inspection.plan.job, assertions_fail=self.assertions_fail, fail=self.fail
        )
        await execute_static_browser_job(
            inspection.plan.job,
            repo_root=self.root,
            runner_manifest=self.runner_manifest,
            output_root=self.output / inspection.id.hex,
            authorize=authorize,
            runner=transport,
        )
        if self.cancel_after_evidence:
            raise asyncio.CancelledError

    def result(self, inspection):
        return verify_inspection_result(self.output / inspection.id.hex, inspection)


def setup_service(tmp_path):
    root, manifest, job, _, revision, _ = make_observation(tmp_path)
    context = SourceContext(
        revision,
        GateArtifactReference(
            job.project_id,
            HumanGateType.ARCHITECTURE,
            ARCHITECTURE_ID,
            1,
            "d" * 64,
        ),
    )
    store = MemoryStore(context, job.owner_user_id)
    backend = Backend(root, manifest, job, context, tmp_path / "executions", store)
    service = StaticInspectionService(store, backend)
    args = {"owner_user_id": job.owner_user_id, "project_id": job.project_id, "request_id": uuid4()}
    return service, store, backend, args


async def prepare(service, backend, args):
    return await service.prepare(
        **args, revision_id=backend.job.revision_id, scenarios=backend.job.scenarios
    )


async def approve(service, backend, args):
    from orchestwin.workflow.gates import HumanGateAction

    prepared = await prepare(service, backend, args)
    expected = prepared["plan"]["plan_content_hash"]
    await service.decide(
        **args,
        expected_hash=expected,
        expected_event_sequence=prepared["gate"]["event_sequence"],
        action=HumanGateAction.APPROVE,
    )
    return expected
