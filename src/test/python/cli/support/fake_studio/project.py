from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from orchestwin.projects.brief_dialogue import BriefDialogue
from orchestwin.projects.clarification_state import BriefAssumption
from orchestwin.projects.progress import ArtifactVersion
from orchestwin.twins.conversations import TwinConversation
from orchestwin.workflow.gates import HumanGate, HumanGateEvent

from .common import _copy, _gate_payload
from .values import STAGES

if TYPE_CHECKING:
    from .studio import FakeStudio
    from .values import _Account, _BriefVersion


class FakeProject:
    def __init__(
        self,
        studio: FakeStudio,
        account: _Account,
        project_id: str,
        name: str,
        mode: str,
        created_at: datetime,
    ) -> None:
        self._studio = studio
        self.account = account
        self.id = project_id
        self.name = name
        self.mode = mode
        self.created_at = created_at
        self.updated_at = created_at
        self.briefs: list[_BriefVersion] = []
        self.dialogues: list[BriefDialogue] = []
        self.assumptions: list[BriefAssumption] = []
        self.gates: dict[str, HumanGate] = {}
        self.gate_events: dict[str, list[HumanGateEvent]] = {}
        self.teams: list[dict[str, object]] = []
        self.personas: dict[str, list[dict[str, object]]] = {}
        self.snapshots: list[dict[str, object]] = []
        self.twins: dict[str, list[dict[str, object]]] = {}
        self.twin_diffs: list[dict[str, object]] = []
        self.conversations: dict[str, TwinConversation] = {}
        self.requirements: list[dict[str, object]] = []
        self.requirement_diffs: list[dict[str, object]] = []
        self.designs: list[dict[str, object]] = []
        self.design_diffs: list[dict[str, object]] = []
        self.mockups: dict[str, dict[str, object]] = {}
        self.iterations: list[dict[str, object]] = []
        self.runs: list[dict[str, object]] = []
        self.finding_decisions: list[dict[str, object]] = []
        self.packages: list[dict[str, object]] = []
        self.folders: list[dict[str, ArtifactVersion]] = []
        self.gestures: list[dict[str, object]] = []
        self.archives: dict[int, bytes] = {}
        self.fingerprint: tuple[str, ...] | None = None
        self.usage: list[dict[str, object]] = []
        self.origin: dict[str, object] | None = None
        self.variant = 0
        self.code_changes: list[dict[str, object]] = []
        self.change_runs: list[dict[str, object]] = []
        self.code_tasks: list[dict[str, object]] = []
        self.decision_count = 0
        self.acceptance_plans: list[dict[str, object]] = []
        self.acceptance_plan_requests: list[dict[str, object]] = []
        self.acceptance_runs: list[dict[str, object]] = []
        self.acceptance_reviews: list[dict[str, object]] = []
        self.critique_contexts: list[dict[str, object]] = []
        self.knowledge_runs: list[dict[str, object]] = []
        self.learned: list[dict[str, object]] = []
        self.development: dict[str, int] = {}
        self.updates: list[dict[str, object]] = []
        self.evidence_versions: list[dict[str, object]] = []
        self.evidence_texts: dict[tuple[str, int], str] = {}
        self.evidence_changes: list[dict[str, object]] = []
        self.validation_hypotheses: list[dict[str, object]] = []
        self.validation_outcomes: list[dict[str, object]] = []
        self.workflow_decisions: list[dict[str, object]] = []
        self.provided_prototypes: list[dict[str, object]] = []
        self.provided_gate: dict[str, object] | None = None
        self.provided_context_current = True
        self.activity_journal: list[dict[str, object]] = []
        self.critique_sources: list[dict[str, object]] = []
        self.critique_shots: dict[tuple[str, str], tuple[str, bytes]] = {}
        self.critique_runs: list[dict[str, object]] = []

    @property
    def owner(self) -> str:
        return self.account.email

    @property
    def brief(self) -> _BriefVersion | None:
        return self.briefs[-1] if self.briefs else None

    @property
    def team(self) -> dict[str, object] | None:
        return self.teams[-1] if self.teams else None

    @property
    def snapshot(self) -> dict[str, object] | None:
        return self.snapshots[-1] if self.snapshots else None

    @property
    def specification(self) -> dict[str, object] | None:
        return self.requirements[-1] if self.requirements else None

    @property
    def design(self) -> dict[str, object] | None:
        return self.designs[-1] if self.designs else None

    def artifact(self, stage: str) -> dict[str, object] | None:
        if stage == "brief":
            return None if self.brief is None else self.brief.payload
        return {
            "team": self.team,
            "twins": self.snapshot,
            "requirements": self.specification,
            "design": self.design,
        }[_stage(stage)]

    @property
    def stage(self) -> str:
        with self._studio._lock:
            return self._studio._progress(self)[0]

    @property
    def next_action(self) -> str:
        with self._studio._lock:
            return self._studio._progress(self)[1]

    @property
    def spent_microusd(self) -> int:
        with self._studio._lock:
            return sum(int(item["cost_microusd"] or 0) for item in self.usage)

    def approved(self, stage: str) -> bool:
        with self._studio._lock:
            return self._studio._approvals(self)[_stage(stage)]

    def current(self, stage: str) -> dict[str, object] | None:
        with self._studio._lock:
            artifact = self.artifact(stage)
            if artifact is not None and _stage(stage) == "twins":
                return self._studio._readable_snapshot(artifact)
            return None if artifact is None else _copy(artifact)

    def gate(self, stage: str) -> dict[str, object] | None:
        with self._studio._lock:
            gate = self.gates.get(_stage(stage))
            return None if gate is None else _gate_payload(gate)

    def jobs(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return [
                job.payload()
                for job in self._studio._jobs.values()
                if job.project_id == self.id and not job.lost
            ]

    def knowledge_versions(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.packages)

    def mark_knowledge_changed(self) -> None:
        with self._studio._lock:
            self.fingerprint = None

    def changes(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return [self._studio._change_payload(self, record) for record in self.code_changes]

    def change_reviews(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.change_runs)

    def tasks(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.code_tasks)

    def aligned(self) -> dict[str, object] | None:
        with self._studio._lock:
            return self._studio._aligned(self)

    def test_plans(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.acceptance_plans)

    def plan_requests(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.acceptance_plan_requests)

    def test_runs(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return [self._studio._test_run_payload(self, record) for record in self.acceptance_runs]

    def test_reviews(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.acceptance_reviews)

    def rewrite_criterion(self, code: str, statement: str) -> None:
        with self._studio._lock:
            specification = self.specification
            if specification is None:
                raise ValueError("the project has no requirements yet")
            for item in specification["specification"]["acceptance_criteria"]:
                if item["code"] == code:
                    item["statement"] = statement
                    return
            raise ValueError(f"the requirements have no acceptance criterion {code}")

    def twin_learning(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return self._studio._learning_entries(self)

    def twin_updates(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.updates)

    def earlier_findings(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.critique_contexts)

    def seed_change(
        self, message: str | None = None, *, commit: str | None = None, reviewed: bool = True
    ) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_change(self, message, commit, reviewed)

    def seed_test_run(self, *, failed: bool = True, reviewed: bool = True) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_test_run(self, failed=failed, reviewed=reviewed)

    def seed_version(self, stage: str) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_version(self, stage)

    def add_tasks(self, items: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
        with self._studio._lock:
            return self._studio._seeded(lambda: self._studio._add_tasks(self, items))

    def seed_tasks(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return self._studio._seeded(lambda: self._studio._seed_tasks(self))

    def set_task_status(self, code: str, status: str, note: str | None = None) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seeded(
                lambda: self._studio._changed_task(self, code, {"status": status, "note": note})
            )

    def seed_learning(
        self,
        twin: int | str = 0,
        statements: Sequence[str] | None = None,
        *,
        source: str = "TWIN_CRITIQUE",
    ) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_learning(self, twin, statements, source)

    def seed_update(
        self,
        twin: int | str = 0,
        observations: Sequence[Mapping[str, object]] | None = None,
    ) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_update(self, twin, observations)

    def sections(self) -> dict[str, object]:
        with self._studio._lock:
            return _copy(self._studio._sections(self))

    def alignments(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.gestures)

    def seed_perspective_change(self, agent_id: str) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_perspective_change(self, agent_id)

    def seed_requirements_change(self) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_requirements_change(self)

    def seed_brief_change(self) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_brief_change(self)

    def seed_requirement_removed(self) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_requirement_removed(self)

    def seed_design_revision(self) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_design_revision(self)

    def seed_alignment_run(self, proposals: Sequence[object] | None = None) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_alignment_run(self, proposals)

    def alignment_runs(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.knowledge_runs)

    def alignment_proposals(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self._studio._alignment_proposals(self))


def _stage(stage: str) -> str:
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {', '.join(STAGES)}")
    return stage
