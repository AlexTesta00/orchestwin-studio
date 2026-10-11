from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import alignment as alignment_api
from orchestwin.cli.api import changes as changes_api
from orchestwin.cli.api import projects as project_api
from orchestwin.cli.api import sections as sections_api
from orchestwin.cli.api import tests as tests_api
from orchestwin.cli.api import usage
from orchestwin.cli.api.replies import route_missing_or_down
from orchestwin.cli.client import LOCAL_ACCESS, ensure_access
from orchestwin.cli.errors import UNREACHABLE, ApiFailure, CliError, signed_out_reason
from orchestwin.cli.flows import align_knowledge, code_run
from orchestwin.cli.project import read_json
from orchestwin.cli.shapes import mapping_list, mappings, squeezed

if TYPE_CHECKING:
    from orchestwin.cli.api.sections import Sections
    from orchestwin.cli.api.tests import AcceptanceSummary
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.folder import FolderSummary, StateSummary
    from orchestwin.cli.project import ProjectFolder, ProjectLink

SCHEMA_VERSION: Final = 1
HEALTHY: Final = 200
SERVER_ERROR: Final = 500
DESIGN_STAGE: Final = "design"
TWINS_STAGE: Final = "twins"
FROM_STUDIO: Final = "studio"
FROM_FOLDER: Final = "folder"
REQUESTED: Final = "requested"
PROJECT_MISSING: Final = "project_missing"


@dataclass(frozen=True, slots=True)
class TwinLearning:
    twin_id: str
    name: str
    label: str
    observations: int

    def document(self) -> dict[str, object]:
        return {
            "twin_id": self.twin_id,
            "name": self.name,
            "label": self.label,
            "observations": self.observations,
        }


@dataclass(frozen=True, slots=True)
class KnowledgeAlignment:
    latest_run: Mapping[str, object] | None
    waiting: int

    def document(self) -> dict[str, object]:
        return {
            "latest_run": None if self.latest_run is None else dict(self.latest_run),
            "waiting": self.waiting,
        }


@dataclass(frozen=True, slots=True)
class Report:
    source: str
    reason: str | None
    studio: str
    project_id: str
    name: str
    mode: str
    language: str | None
    root: str
    current_stage: str
    next_action: str
    steps: tuple[project_api.StepState, ...]
    local_version: int | None
    local_error: str | None
    studio_version: int | None
    has_budget: bool
    spent_usd: float | None
    remaining_usd: float | None
    alignment: StateSummary | None = None
    local_complete: bool = False
    tests: AcceptanceSummary | None = None
    stale_reviews: int = 0
    learning: tuple[TwinLearning, ...] | None = None
    billing: str = usage.API_BILLING
    sections: Sections | None = None
    knowledge: KnowledgeAlignment | None = None
    local_access: bool = False
    aligned_design_version: int | None = None
    current_design_version: int | None = None

    @property
    def folder_current(self) -> bool:
        if self.studio_version is not None:
            return self.local_version is not None and self.local_version == self.studio_version
        return self.source == FROM_FOLDER and self.local_complete

    def document(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "project",
            "source": self.source,
            "reason": self.reason,
            "studio": self.studio,
            "project": {
                "id": self.project_id,
                "name": self.name,
                "mode": self.mode,
                "language": self.language,
                "root": self.root,
            },
            "current_stage": self.current_stage,
            "next_action": self.next_action,
            "next_command": project_api.next_command(
                self.next_action, folder_current=self.folder_current
            ),
            "steps": [
                {
                    "stage": step.stage,
                    "state": step.state,
                    "version": step.version,
                    "approved": step.approved,
                }
                for step in self.steps
            ],
            "knowledge_folder": {
                "local_version": self.local_version,
                "studio_version": self.studio_version,
                "local_error": self.local_error,
            },
            "spending": (
                {
                    "currency": "USD",
                    "project_spent_usd": _rounded(self.spent_usd),
                    "remaining_usd": _rounded(self.remaining_usd),
                    "billing": self.billing,
                }
                if self.has_budget
                else None
            ),
            "alignment": (
                None
                if self.alignment is None
                else {
                    "recorded": self.alignment.changes,
                    "pending": self.alignment.pending_changes,
                    "aligned_commit": self.alignment.aligned_commit,
                    "open_tasks": self.alignment.open_tasks,
                    "stale_reviews": self.stale_reviews,
                    "aligned_design_version": self.aligned_design_version,
                    "current_design_version": self.current_design_version,
                }
            ),
            "tests": None if self.tests is None else self.tests.document(),
            "learning": (
                {"twins": [twin.document() for twin in self.learning]} if self.learning else None
            ),
            "sections": None if self.sections is None else dict(self.sections.document),
            "knowledge_alignment": None if self.knowledge is None else self.knowledge.document(),
        }


@dataclass(frozen=True, slots=True)
class _Studio:
    project: Mapping[str, object]
    steps: tuple[project_api.StepState, ...]
    has_budget: bool
    spent_usd: float | None
    remaining_usd: float | None
    alignment: StateSummary | None = None
    tests: AcceptanceSummary | None = None
    stale_reviews: int = 0
    learning: tuple[TwinLearning, ...] | None = None
    billing: str = usage.API_BILLING
    sections: Sections | None = None
    knowledge: KnowledgeAlignment | None = None
    local_access: bool = False
    aligned_design_version: int | None = None


def project_report(context: CommandContext, project: ProjectFolder, *, offline: bool) -> Report:
    link = project.link()
    local, local_error = _local_summary(project)
    client = context.client()
    if offline:
        return _folder_report(project, link, local, local_error, client.studio.origin, REQUESTED)
    found = _studio_facts(context, client, link)
    if isinstance(found, str):
        return _folder_report(project, link, local, local_error, client.studio.origin, found)
    name = found.project.get("display_name")
    stage = found.project.get("current_stage")
    action = found.project.get("next_action")
    current = project_api.current_stage(found.steps)
    section_progress = _section_progress(found.sections)
    if section_progress is not None:
        stage, action = section_progress
    return Report(
        source=FROM_STUDIO,
        reason=None,
        studio=client.studio.origin,
        project_id=link.project_id,
        name=name if isinstance(name, str) and name else link.project_name,
        mode=link.mode,
        language=link.language,
        root=str(project.root),
        current_stage=stage if isinstance(stage, str) else current,
        next_action=action if isinstance(action, str) else project_api.STAGE_ACTIONS[current],
        steps=found.steps,
        local_version=None if local is None else local.version_number,
        local_error=local_error,
        studio_version=found.steps[-1].version,
        has_budget=found.has_budget,
        spent_usd=found.spent_usd,
        remaining_usd=found.remaining_usd,
        alignment=found.alignment,
        tests=found.tests if found.tests is not None else local_tests(project),
        stale_reviews=found.stale_reviews,
        learning=found.learning if found.learning is not None else local_learning(project),
        billing=found.billing,
        sections=found.sections,
        knowledge=found.knowledge
        if found.knowledge is not None
        else folder_knowledge(project, found.steps),
        local_access=found.local_access,
        aligned_design_version=_aligned_design_version(
            project, found.alignment, found.aligned_design_version
        ),
        current_design_version=_design_version(found.steps),
    )


def studio_knowledge(client: StudioClient, project_id: str) -> KnowledgeAlignment | None:
    try:
        document = alignment_api.proposals(client, project_id)
    except ApiFailure as failure:
        if route_missing_or_down(failure):
            return None
        raise
    return KnowledgeAlignment(
        alignment_api.latest_run(document), len(alignment_api.waiting(document))
    )


def local_knowledge(project: ProjectFolder) -> KnowledgeAlignment | None:
    latest = align_knowledge.read_latest(project)
    if latest is None:
        return None
    run_id = str(latest["run_id"])
    run = align_knowledge.read_run(project, run_id)
    if run is not None:
        found = {key: run.get(key) for key in alignment_api.LATEST_RUN_KEYS}
    else:
        found = {
            **dict.fromkeys(alignment_api.LATEST_RUN_KEYS),
            "id": run_id,
            "from_commit": latest.get("from_commit"),
            "to_commit": latest.get("to_commit"),
            "created_at": latest.get("finished_at"),
        }
    waiting = latest.get("waiting")
    valid = isinstance(waiting, int) and not isinstance(waiting, bool) and waiting >= 0
    return KnowledgeAlignment(found, waiting if valid else 0)


def folder_knowledge(
    project: ProjectFolder, steps: tuple[project_api.StepState, ...]
) -> KnowledgeAlignment | None:
    return local_knowledge(project) if _design_approved(steps) else None


def local_learning(project: ProjectFolder) -> tuple[TwinLearning, ...] | None:
    manifest = read_json(project.knowledge / knowledge.MANIFEST_NAME)
    feedback = manifest.get("feedback") if isinstance(manifest, Mapping) else None
    named = feedback.get("learned") if isinstance(feedback, Mapping) else None
    if not isinstance(named, str) or not _inside(named):
        return None
    document = read_json(project.knowledge.joinpath(*named.split("/")))
    if not isinstance(document, Mapping):
        return None
    return learning_of(document.get("twins"))


def local_stale_reviews(project: ProjectFolder) -> int:
    manifest = read_json(project.knowledge / knowledge.MANIFEST_NAME)
    state = manifest.get("state") if isinstance(manifest, Mapping) else None
    value = state.get("stale_reviews") if isinstance(state, Mapping) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def learning_of(entries: object) -> tuple[TwinLearning, ...]:
    found: list[TwinLearning] = []
    for entry in mappings(entries):
        twin_id = entry.get("twin_id")
        if not isinstance(twin_id, str) or not twin_id:
            continue
        found.append(
            TwinLearning(
                twin_id=twin_id,
                name=squeezed(entry.get("twin_name")) or "-",
                label=learning_label(entry),
                observations=len(mapping_list(entry.get("observations"))),
            )
        )
    return tuple(found)


def learning_label(entry: Mapping[str, object]) -> str:
    label = entry.get("label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    profile = entry.get("profile_version_number")
    development = entry.get("development_version_number")
    if all(
        isinstance(value, int) and not isinstance(value, bool) for value in (profile, development)
    ):
        return f"{profile}.{development}"
    return "-"


def local_tests(project: ProjectFolder) -> AcceptanceSummary | None:
    manifest = read_json(project.knowledge / knowledge.MANIFEST_NAME)
    feedback = manifest.get("feedback") if isinstance(manifest, Mapping) else None
    count = feedback.get("test_runs") if isinstance(feedback, Mapping) else None
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        return None
    named = feedback.get("tests")
    relative = named if isinstance(named, str) and _inside(named) else knowledge.TESTS_DOCUMENT
    document = read_json(project.knowledge.joinpath(*relative.split("/")))
    runs = tests_api.mappings(document.get("runs")) if isinstance(document, Mapping) else []
    return tests_api.run_summary_of(runs[0] if runs else None, count)


def _section_progress(found: Sections | None) -> tuple[str, str] | None:
    if found is None:
        return None
    for section in found.sections:
        if section.key == sections_api.PACKAGE:
            break
        if section.state in {sections_api.NOT_STARTED, sections_api.IN_PROGRESS}:
            return None
        if not section.behind:
            continue
        if found.alignment.available:
            return section.key, project_api.UPDATE_SECTIONS
        if section.blocked == "PREPARE_TWINS":
            return sections_api.USER_TWINS, project_api.PREPARE_TWINS
        if section.key == sections_api.DESIGN and section.blocked in {
            "REQUIREMENT_NO_LONGER_AVAILABLE",
            "PREPARE_AGAIN",
        }:
            return sections_api.DESIGN, project_api.PREPARE_DESIGN
        return section.key, project_api.STAGE_ACTIONS[section.key]
    return None


def _studio_facts(
    context: CommandContext, client: StudioClient, link: ProjectLink
) -> _Studio | str:
    try:
        access = ensure_access(context, client)
        if client.health().status != HEALTHY:
            return UNREACHABLE
        found = project_api.get_project(client, link.project_id)
        steps = project_api.step_states(client, link.project_id)
        sections = studio_sections(client, link.project_id)
        approved = _design_approved(steps)
        development = changes_api.development(client, link.project_id) if approved else None
        tests = tests_api.summary(client, link.project_id) if approved else None
        knowledge = studio_knowledge(client, link.project_id) if approved else None
        learning = studio_learning(client, link.project_id) if _twins_approved(steps) else None
        has_budget, spent, remaining, billing = _spending(client, link.project_id)
    except CliError as error:
        reason = _offline_reason(error)
        if reason is None:
            raise
        return reason
    return _Studio(
        found,
        steps,
        has_budget,
        spent,
        remaining,
        alignment=None if development is None else development.summary,
        tests=tests,
        stale_reviews=0 if development is None else development.stale_reviews,
        learning=learning,
        billing=billing,
        sections=sections,
        knowledge=knowledge,
        local_access=access == LOCAL_ACCESS,
        aligned_design_version=None if development is None else development.aligned_design_version,
    )


def studio_sections(client: StudioClient, project_id: str) -> Sections | None:
    try:
        return sections_api.sections(client, project_id)
    except ApiFailure as failure:
        if failure.http_status >= SERVER_ERROR or failure.http_status == HEALTHY:
            return None
        raise


def studio_learning(client: StudioClient, project_id: str) -> tuple[TwinLearning, ...] | None:
    try:
        document = client.get(f"/projects/{project_id}/twin-learning")
    except ApiFailure as failure:
        if route_missing_or_down(failure):
            return None
        raise
    return learning_of(document.get("twins") if isinstance(document, Mapping) else None)


def _design_approved(steps: tuple[project_api.StepState, ...]) -> bool:
    return any(step.stage == DESIGN_STAGE and step.approved for step in steps)


def _twins_approved(steps: tuple[project_api.StepState, ...]) -> bool:
    return any(step.stage == TWINS_STAGE and step.approved for step in steps)


def _design_version(steps: tuple[project_api.StepState, ...]) -> int | None:
    return next((step.version for step in steps if step.stage == DESIGN_STAGE), None)


def _aligned_design_version(
    project: ProjectFolder, alignment: StateSummary | None, verified: int | None
) -> int | None:
    return None if alignment is None else code_run.aligned_design_version(project, verified)


def _offline_reason(error: CliError) -> str | None:
    reason = signed_out_reason(error)
    if reason is None and isinstance(error, ApiFailure) and error.http_status == 404:
        return PROJECT_MISSING
    return reason


def _spending(
    client: StudioClient, project_id: str
) -> tuple[bool, float | None, float | None, str]:
    try:
        budget = usage.budget(client)
        if budget is None:
            return False, None, None, usage.API_BILLING
        used = usage.project_usage(client, project_id)
    except ApiFailure as failure:
        if failure.http_status >= 500:
            return False, None, None, usage.API_BILLING
        raise
    spent = None if used is None else usage.spent_usd(used)
    return True, spent, usage.remaining_usd(budget), usage.billing(budget)


def _local_summary(project: ProjectFolder) -> tuple[FolderSummary | None, str | None]:
    try:
        return knowledge.summary(project.knowledge), None
    except CliError as error:
        return None, str(error.values.get("code", error.code))


def _folder_report(
    project: ProjectFolder,
    link: ProjectLink,
    local: FolderSummary | None,
    local_error: str | None,
    studio: str,
    reason: str,
) -> Report:
    steps = folder_steps(project, local)
    current = project_api.current_stage(steps)
    state = None if local is None else local.state
    alignment = state if _design_approved(steps) else None
    return Report(
        source=FROM_FOLDER,
        reason=reason,
        studio=studio,
        project_id=link.project_id,
        name=link.project_name,
        mode=link.mode,
        language=link.language,
        root=str(project.root),
        current_stage=current,
        next_action=project_api.STAGE_ACTIONS[current],
        steps=steps,
        local_version=None if local is None else local.version_number,
        local_error=local_error,
        studio_version=None,
        has_budget=False,
        spent_usd=None,
        remaining_usd=None,
        alignment=alignment,
        local_complete=local is not None
        and local.complete
        and set(knowledge.FOLDER_STAGES) <= set(local.progress),
        tests=local_tests(project),
        stale_reviews=0 if alignment is None else local_stale_reviews(project),
        learning=local_learning(project),
        knowledge=folder_knowledge(project, steps),
        aligned_design_version=_aligned_design_version(project, alignment, None),
        current_design_version=_design_version(steps),
    )


def folder_steps(
    project: ProjectFolder, local: FolderSummary | None
) -> tuple[project_api.StepState, ...]:
    saved = project.steps()
    facts: list[tuple[str, int | None, bool]] = []
    for stage in knowledge.FOLDER_STAGES:
        entry = None if local is None or stage not in local.progress else local.stage(stage)
        if entry is not None and entry.version_number is not None:
            facts.append((stage, entry.version_number, entry.gate_status == project_api.APPROVED))
            continue
        document = saved.get(stage)
        version = None if document is None else document.get("version")
        number = version.get("version_number") if isinstance(version, Mapping) else None
        valid = isinstance(number, int) and not isinstance(number, bool)
        facts.append((stage, number if valid else None, document is not None))
    facts.append(("package", None if local is None else local.version_number, facts[-1][2]))
    return project_api.arrange(facts)


def _inside(path: str) -> bool:
    parts = path.split("/")
    return (
        bool(path)
        and "\\" not in path
        and ":" not in path
        and all(part not in ("", ".", "..") for part in parts)
    )


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 6)
