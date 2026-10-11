from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from typing import Annotated, Final, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from orchestwin.api.auth import CurrentUser
from orchestwin.api.generation_evidence import (
    accept_generation,
    attempt_generation,
    current_generation_ids,
    retire_generation,
)
from orchestwin.api.generation_jobs import GenerationOperation
from orchestwin.api.generation_requests import generation_request
from orchestwin.api.refusals import refusal
from orchestwin.api.runtime_access import (
    PROJECT_NOT_FOUND,
    ChangeReference,
    approved_reference,
    current_brief,
    database_sessions,
    generation_cost,
    require_approved,
    require_project,
    runtime_service,
)
from orchestwin.artifacts.design_evaluation import DesignEvaluationError
from orchestwin.knowledge.state import (
    MAX_AUTHOR_LENGTH,
    MAX_DIFF_LENGTH,
    MAX_FILES,
    MAX_MESSAGE_LENGTH,
    MAX_NOTE_LENGTH,
    MAX_PATH_LENGTH,
    MAX_TASK_LENGTH,
    MAX_TASK_NOTE_LENGTH,
    MAX_TASKS,
)
from orchestwin.models.change_review import (
    ALIGNMENT_PURPOSE,
    CRITIQUE_PURPOSE,
    EARLIER_PREVIOUS_COMMIT,
    EARLIER_THIS_COMMIT,
    MAX_EARLIER_FINDINGS,
    alignment_context,
    bind_alignment,
    bind_critique,
    critique_change,
    critique_context,
    judge_alignment,
    review_material,
)
from orchestwin.models.proposal_evidence import evidence_application
from orchestwin.projects.code_changes import (
    LOCALE_PATTERN,
    MAX_LOCALE_LENGTH,
    ChangeDecision,
    ChangedFile,
    ChangedFileKind,
    ChangeReviewRun,
    CodeChange,
    CodeChangeAmbiguous,
    CodeTask,
    DecisionKind,
    TaskOrigin,
    TaskSource,
    TaskStatus,
    create_code_change,
    finding_task_text,
    normalize_author,
    normalize_diff,
    normalize_message,
    normalize_note,
    normalize_path,
    normalize_task_note,
    normalize_task_text,
    task_number,
)
from orchestwin.projects.persistence.acceptance_tests import SqlAlchemyAcceptanceTestRepository
from orchestwin.projects.persistence.code_changes import (
    CodeChangeWriteResult,
    CodeChangeWriteStatus,
    CreatedTasks,
    SqlAlchemyCodeChangeRepository,
)
from orchestwin.projects.persistence.twin_learning import SqlAlchemyTwinLearningRepository
from orchestwin.projects.twin_learning import learned_view
from orchestwin.twins.user_modeling_gate import user_modeling_gate_is_currently_approved

CODE_CHANGES_API_PREFIX: Final = "/projects/{project_id}"
COMMIT_REQUEST_PATTERN: Final = r"^[0-9a-fA-F]{7,64}$"
TASK_STATUS_FILTERS: Final = ("open", "all")
REVIEWED: Final = "REVIEWED"
DECIDED: Final = "DECIDED"
CREATED: Final = "CREATED"
UPDATED: Final = "UPDATED"
CODE_CHANGE_NOT_FOUND: Final = "CODE_CHANGE_NOT_FOUND"
CODE_CHANGE_AMBIGUOUS: Final = "CODE_CHANGE_AMBIGUOUS"
CODE_CHANGE_REVIEW_EXISTS: Final = "CODE_CHANGE_REVIEW_EXISTS"
TEST_RUN_NOT_FOUND: Final = "TEST_RUN_NOT_FOUND"
CODE_TASK_NOT_FOUND: Final = "CODE_TASK_NOT_FOUND"
TASK_SOURCE_INVALID: Final = "TASK_SOURCE_INVALID"
CHANGE_REVIEW_MODEL_NOT_CONFIGURED: Final = "CHANGE_REVIEW_MODEL_NOT_CONFIGURED"
USER_MODELING_APPROVAL_REQUIRED: Final = "USER_MODELING_APPROVAL_REQUIRED"
CRITIQUE_ROLE: Final = "CHANGE_CRITIQUE"
ALIGNMENT_ROLE: Final = "CHANGE_ALIGNMENT"
TWIN_CRITIQUED: Final = "TWIN_CRITIQUED"
CRITIQUE_REJECTED: Final = "CRITIQUE_REJECTED"
ATTEMPTS_EXHAUSTED: Final = "change review attempts are exhausted"


class ChangedFileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=MAX_PATH_LENGTH)
    kind: ChangedFileKind
    added: int = Field(ge=0)
    removed: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def valid_path(cls, value: str) -> str:
        return normalize_path(value)

    def to_domain(self) -> ChangedFile:
        return ChangedFile(path=self.path, kind=self.kind, added=self.added, removed=self.removed)


class CodeChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commit: str = Field(pattern=COMMIT_REQUEST_PATTERN)
    parent: str | None = Field(default=None, pattern=COMMIT_REQUEST_PATTERN)
    committed_at: AwareDatetime
    author: str | None = Field(default=None, max_length=MAX_AUTHOR_LENGTH)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    files: list[ChangedFileRequest] = Field(default_factory=list, max_length=MAX_FILES)
    diff: str = Field(default="", max_length=MAX_DIFF_LENGTH)

    @field_validator("commit", "parent")
    @classmethod
    def lower_case(cls, value: str | None) -> str | None:
        return None if value is None else value.lower()

    @field_validator("author")
    @classmethod
    def valid_author(cls, value: str | None) -> str | None:
        return normalize_author(value)

    @field_validator("message")
    @classmethod
    def valid_message(cls, value: str) -> str:
        return normalize_message(value)

    @field_validator("diff")
    @classmethod
    def valid_diff(cls, value: str) -> str:
        return normalize_diff(value)

    @model_validator(mode="after")
    def distinct_parent(self) -> CodeChangeRequest:
        if self.parent is not None and self.parent == self.commit:
            raise ValueError("a commit cannot be its own parent")
        return self


class ChangeReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: str = Field(
        default="it-IT", min_length=2, max_length=MAX_LOCALE_LENGTH, pattern=LOCALE_PATTERN
    )
    again: bool = False


class FindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    twin_id: UUID
    finding: int = Field(ge=0)


class ChangeDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DecisionKind
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    tasks: list[Annotated[str, Field(min_length=1, max_length=MAX_TASK_LENGTH)]] = Field(
        default_factory=list, max_length=MAX_TASKS
    )
    findings: list[FindingRequest] = Field(default_factory=list, max_length=MAX_TASKS)

    @field_validator("note")
    @classmethod
    def valid_note(cls, value: str | None) -> str | None:
        return normalize_note(value)

    @field_validator("tasks")
    @classmethod
    def valid_tasks(cls, value: list[str]) -> list[str]:
        return [normalize_task_text(item) for item in value]

    @model_validator(mode="after")
    def tasks_of_code_tasks(self) -> ChangeDecisionRequest:
        count = len(self.tasks) + len(self.findings)
        if self.kind is DecisionKind.CODE_TASKS:
            if not 1 <= count <= MAX_TASKS:
                raise ValueError(f"a CODE_TASKS decision holds 1 to {MAX_TASKS} tasks and findings")
        elif count:
            raise ValueError("tasks and findings are given only with a CODE_TASKS decision")
        return self


class OwnerSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["OWNER"]


class RunSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["TEST_RUN"]
    test_run_id: UUID
    twin_id: UUID
    finding: int = Field(ge=0)


class ChangeSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["CODE_CHANGE"]
    commit: str = Field(pattern=COMMIT_REQUEST_PATTERN)
    twin_id: UUID
    finding: int = Field(ge=0)

    @field_validator("commit")
    @classmethod
    def lower_case(cls, value: str) -> str:
        return value.lower()


SourceRequest = Annotated[
    OwnerSourceRequest | RunSourceRequest | ChangeSourceRequest, Field(discriminator="kind")
]


class TaskItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, min_length=1, max_length=MAX_TASK_LENGTH)
    source: SourceRequest

    @field_validator("text")
    @classmethod
    def valid_text(cls, value: str | None) -> str | None:
        return None if value is None else normalize_task_text(value)

    @model_validator(mode="after")
    def text_of_owner(self) -> TaskItemRequest:
        if isinstance(self.source, OwnerSourceRequest) and self.text is None:
            raise ValueError("a task written by the owner needs a text")
        return self


class CodeTasksRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[TaskItemRequest] = Field(min_length=1, max_length=MAX_TASKS)


class TaskStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TaskStatus
    note: str | None = Field(default=None, max_length=MAX_TASK_NOTE_LENGTH)

    @field_validator("note")
    @classmethod
    def valid_note(cls, value: str | None) -> str | None:
        return normalize_task_note(value)


class ChangeReviewStatus(StrEnum):
    REVIEWED = "CODE_CHANGE_REVIEWED"


@dataclass(frozen=True)
class ChangeReviewResult:
    status: ChangeReviewStatus
    run: ChangeReviewRun


async def recorded_change(repository, project_id: UUID, commit: str) -> CodeChange:
    try:
        change = await repository.get(project_id, commit)
    except CodeChangeAmbiguous as error:
        raise refusal(409, CODE_CHANGE_AMBIGUOUS) from error
    if change is None:
        raise refusal(404, CODE_CHANGE_NOT_FOUND)
    return change


def _finding_source(
    critiques: Sequence[object],
    twin_id: UUID,
    position: int,
    text: str | None,
    *,
    change: CodeChange | None = None,
    test_run_id: UUID | None = None,
) -> TaskSource | None:
    critique = next((item for item in critiques if item.twin_id == twin_id), None)
    if critique is None or not 0 <= position < len(critique.findings):
        return None
    finding = critique.findings[position]
    criterion = getattr(finding, "criterion", None)
    return TaskSource(
        origin=TaskOrigin.TEST_RUN if change is None else TaskOrigin.CODE_CHANGE,
        text=finding_task_text(finding.text, finding.action) if text is None else text,
        change_id=None if change is None else change.id,
        commit=None if change is None else change.commit,
        test_run_id=test_run_id,
        twin_id=critique.twin_id,
        twin_name=critique.twin_name,
        finding=finding.text,
        requirements=() if finding.requirement is None else (finding.requirement,),
        screens=() if finding.screen is None else (finding.screen,),
        criteria=() if criterion is None else (criterion,),
    )


def _decision_sources(
    change: CodeChange, latest: ChangeReviewRun | None, body: ChangeDecisionRequest
) -> list[TaskSource]:
    sources = [
        TaskSource(
            origin=TaskOrigin.CODE_CHANGE,
            text=text,
            change_id=change.id,
            commit=change.commit,
            requirements=() if latest is None else latest.alignment.affected_requirements,
            screens=() if latest is None else latest.alignment.affected_screens,
        )
        for text in body.tasks
    ]
    critiques = () if latest is None else latest.critiques
    for index, item in enumerate(body.findings):
        source = _finding_source(critiques, item.twin_id, item.finding, None, change=change)
        if source is None:
            raise refusal(422, TASK_SOURCE_INVALID, index=index)
        sources.append(source)
    return sources


class CodeChangeApplication:
    def __init__(self, runtime):
        self.runtime = runtime
        self._proposal_evidence_store = getattr(runtime, "proposal_evidence_store", None)

    @staticmethod
    def _repository(session, owner_user_id: UUID):
        return SqlAlchemyCodeChangeRepository(session, owner_user_id=owner_user_id)

    def review_available(self) -> bool:
        return (
            getattr(self.runtime, "real_model_runtime", None) is not None
            and self._proposal_evidence_store is not None
        )

    def _generator(self):
        if not self.review_available():
            raise refusal(503, CHANGE_REVIEW_MODEL_NOT_CONFIGURED)
        return self.runtime.real_model_runtime.user_modeling.proposal_port.generator

    async def _twins(self, owner_user_id: UUID, project_id: UUID) -> tuple[object, ...]:
        services = runtime_service(
            self.runtime, "user_modeling_services", "USER_MODELING_UNAVAILABLE"
        )
        scope = {"owner_user_id": owner_user_id, "project_id": project_id}
        snapshot = await services.queries.current_snapshot(**scope)
        gate = await services.gates.current_gate(**scope)
        if snapshot is None or not user_modeling_gate_is_currently_approved(gate, snapshot):
            raise refusal(409, USER_MODELING_APPROVAL_REQUIRED)
        return tuple(snapshot.snapshot.twin_versions)

    @staticmethod
    def _findings_by_twin(run: ChangeReviewRun) -> dict[UUID, tuple[str, ...]]:
        return {
            critique.twin_id: run.findings_of(critique.twin_id)[:MAX_EARLIER_FINDINGS]
            for critique in run.critiques
        }

    @classmethod
    async def _earlier_findings(
        cls, repository, project_id: UUID, change: CodeChange, latest: ChangeReviewRun | None
    ) -> tuple[dict[UUID, tuple[str, ...]], str]:
        if latest is not None:
            return cls._findings_by_twin(latest), EARLIER_THIS_COMMIT
        pending = await repository.list(project_id, pending_only=True, limit=None)
        index = next((place for place, item in enumerate(pending) if item.id == change.id), None)
        if index is None:
            return {}, EARLIER_PREVIOUS_COMMIT
        for older in pending[index + 1 :]:
            run = await repository.latest_run(older.id)
            if run is not None:
                return cls._findings_by_twin(run), EARLIER_PREVIOUS_COMMIT
        return {}, EARLIER_PREVIOUS_COMMIT

    async def current_versions(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> dict[str, object] | None:
        reference = await approved_reference(self.runtime, owner_user_id, project_id)
        return reference.current_versions()

    async def record(self, *, owner_user_id: UUID, project_id: UUID, body) -> CodeChangeWriteResult:
        try:
            change = create_code_change(
                project_id=project_id,
                owner_user_id=owner_user_id,
                commit=body.commit,
                parent=body.parent,
                committed_at=body.committed_at,
                author=body.author,
                message=body.message,
                files=tuple(item.to_domain() for item in body.files),
                diff=body.diff,
                recorded_at=datetime.now(UTC),
            )
        except ValueError as error:
            raise HTTPException(422, detail="invalid_request") from error
        sessions = database_sessions(self.runtime)
        async with sessions() as session, session.begin():
            result = await self._repository(session, owner_user_id).record(change)
        if result.status is CodeChangeWriteStatus.PROJECT_NOT_FOUND:
            raise refusal(404, PROJECT_NOT_FOUND)
        return result

    async def changes(
        self, *, owner_user_id: UUID, project_id: UUID, pending: bool = False
    ) -> tuple[CodeChange, ...]:
        sessions = database_sessions(self.runtime)
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await require_project(repository, project_id)
            return await repository.list(project_id, pending_only=pending)

    async def change(self, *, owner_user_id: UUID, project_id: UUID, commit: str) -> CodeChange:
        sessions = database_sessions(self.runtime)
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await require_project(repository, project_id)
            return await recorded_change(repository, project_id, commit)

    async def reviews(
        self, *, owner_user_id: UUID, project_id: UUID, commit: str
    ) -> tuple[ChangeReviewRun, ...]:
        sessions = database_sessions(self.runtime)
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await require_project(repository, project_id)
            change = await recorded_change(repository, project_id, commit)
            return await repository.runs(change.id)

    async def alignment(self, *, owner_user_id: UUID, project_id: UUID) -> dict[str, object]:
        sessions = database_sessions(self.runtime)
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await require_project(repository, project_id)
            aligned = await repository.aligned_point(project_id)
            pending = await repository.list(project_id, pending_only=True, limit=None)
            latest = await repository.list(project_id, limit=1)
            tasks = await repository.tasks(project_id, open_only=True)
        reference = await approved_reference(self.runtime, owner_user_id, project_id)
        current = reference.current_versions()
        return {
            "project_id": str(project_id),
            "reference": reference.to_snapshot(),
            "aligned": None if aligned is None else aligned.to_snapshot(),
            "pending_changes": len(pending),
            "stale_reviews": sum(
                1
                for change in pending
                if change.review is not None and change.review.stale(current)
            ),
            "latest_change": latest[0].to_answer(current) if latest else None,
            "tasks": [task.to_snapshot() for task in tasks],
            "review_available": self.review_available(),
        }

    @evidence_application
    async def review(
        self, *, owner_user_id: UUID, project_id: UUID, commit: str, body
    ) -> ChangeReviewResult:
        sessions = database_sessions(self.runtime)
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await require_project(repository, project_id)
            change = await recorded_change(repository, project_id, commit)
            latest = await repository.latest_run(change.id)
            if latest is not None and not body.again:
                raise refusal(409, CODE_CHANGE_REVIEW_EXISTS)
            earlier, earlier_source = await self._earlier_findings(
                repository, project_id, change, latest
            )
            open_tasks = await repository.tasks(project_id, open_only=True)
            learned = await SqlAlchemyTwinLearningRepository(
                session, owner_user_id=owner_user_id
            ).active(project_id)
        reference = await require_approved(self.runtime, owner_user_id, project_id)
        twins = await self._twins(owner_user_id, project_id)
        generator = self._generator()
        brief = await current_brief(self.runtime, owner_user_id, project_id)
        try:
            material = review_material(
                brief=brief,
                requirements=reference.requirements,
                design=reference.design,
                change=change,
                language=body.locale.split("-")[0],
            )
        except DesignEvaluationError as error:
            raise refusal(409, error.code) from error
        run_id = uuid4()
        identifiers = {"review_run_id": str(run_id)}
        critiques = []
        for twin in twins:
            context = critique_context(
                project_id=project_id,
                locale=body.locale,
                twin=twin,
                material=material,
                earlier_findings=earlier.get(twin.twin_id, ()),
                earlier_source=earlier_source,
                learned=learned_view(learned.get(twin.twin_id, ())),
            )
            critique = await attempt_generation(
                partial(critique_change, generator, context),
                partial(bind_critique, twin=twin, context=context),
                role=CRITIQUE_ROLE,
                rejected=CRITIQUE_REJECTED,
                reference=identifiers,
                exhausted=ATTEMPTS_EXHAUSTED,
            )
            await accept_generation(CRITIQUE_PURPOSE, critique.to_snapshot())
            await retire_generation(CRITIQUE_ROLE, TWIN_CRITIQUED, identifiers)
            critiques.append(critique)
        context = alignment_context(
            project_id=project_id,
            locale=body.locale,
            material=material,
            critiques=critiques,
            open_tasks=open_tasks,
        )
        verdict = await attempt_generation(
            partial(judge_alignment, generator, context),
            partial(bind_alignment, context=context),
            role=ALIGNMENT_ROLE,
            rejected=CRITIQUE_REJECTED,
            reference=identifiers,
            exhausted=ATTEMPTS_EXHAUSTED,
        )
        await accept_generation(ALIGNMENT_PURPOSE, verdict.to_snapshot())
        generation_ids = current_generation_ids()
        requirements_version, design_version = reference.version_numbers
        run = ChangeReviewRun(
            id=run_id,
            change_id=change.id,
            project_id=project_id,
            owner_user_id=owner_user_id,
            commit=change.commit,
            reviewed_at=datetime.now(UTC),
            locale=body.locale,
            requirements_version_number=requirements_version,
            design_version_number=design_version,
            alternative_code=reference.alternative_code,
            critiques=tuple(critiques),
            alignment=verdict,
            generation_ids=generation_ids,
            cost_microusd=await generation_cost(
                self._proposal_evidence_store, owner_user_id, project_id, generation_ids
            ),
        )
        async with sessions() as session, session.begin():
            status = await self._repository(session, owner_user_id).create_run(run)
        if status is CodeChangeWriteStatus.PROJECT_NOT_FOUND:
            raise refusal(404, PROJECT_NOT_FOUND)
        if status is not CodeChangeWriteStatus.RECORDED:
            raise refusal(404, CODE_CHANGE_NOT_FOUND)
        return ChangeReviewResult(status=ChangeReviewStatus.REVIEWED, run=run)

    async def decide(
        self, *, owner_user_id: UUID, project_id: UUID, commit: str, body
    ) -> tuple[CodeChange, dict[str, object]]:
        reference = await approved_reference(self.runtime, owner_user_id, project_id)
        decided_at = datetime.now(UTC)
        decision = ChangeDecision(kind=body.kind, decided_at=decided_at, note=body.note)
        sessions = database_sessions(self.runtime)
        async with sessions() as session, session.begin():
            repository = self._repository(session, owner_user_id)
            await require_project(repository, project_id)
            change = await recorded_change(repository, project_id, commit)
            sources = []
            if decision.kind is DecisionKind.CODE_TASKS:
                latest = await repository.latest_run(change.id)
                sources = _decision_sources(change, latest, body)
            decided = await repository.decide(
                change.id, decision, aligned_versions=reference.version_numbers
            )
            if decided is None:
                raise refusal(404, CODE_CHANGE_NOT_FOUND)
            if decision.kind is DecisionKind.ALIGNED:
                await repository.close_open_tasks(project_id, change.id, decided_at)
            elif decision.kind is DecisionKind.CODE_TASKS:
                await repository.create_tasks(project_id, sources, created_at=decided_at)
        alignment = await self.alignment(owner_user_id=owner_user_id, project_id=project_id)
        return decided, alignment

    async def tasks(
        self, *, owner_user_id: UUID, project_id: UUID, every: bool = False
    ) -> tuple[CodeTask, ...]:
        sessions = database_sessions(self.runtime)
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await require_project(repository, project_id)
            return await repository.tasks(project_id, open_only=not every)

    @staticmethod
    async def _sources(
        repository, tests, project_id: UUID, items: Sequence[TaskItemRequest]
    ) -> list[TaskSource]:
        runs = {}
        changes = {}
        ambiguous = set()
        for item in items:
            source = item.source
            if isinstance(source, RunSourceRequest) and source.test_run_id not in runs:
                runs[source.test_run_id] = await tests.run(project_id, source.test_run_id)
            elif isinstance(source, ChangeSourceRequest) and source.commit not in changes:
                try:
                    changes[source.commit] = await repository.get(project_id, source.commit)
                except CodeChangeAmbiguous:
                    changes[source.commit] = None
                    ambiguous.add(source.commit)
        if any(run is None for run in runs.values()):
            raise refusal(404, TEST_RUN_NOT_FOUND)
        if any(value is None and key not in ambiguous for key, value in changes.items()):
            raise refusal(404, CODE_CHANGE_NOT_FOUND)
        if ambiguous:
            raise refusal(409, CODE_CHANGE_AMBIGUOUS)
        latest = {}
        sources = []
        for index, item in enumerate(items):
            source = item.source
            if isinstance(source, OwnerSourceRequest):
                sources.append(TaskSource(origin=TaskOrigin.OWNER, text=item.text))
                continue
            if isinstance(source, RunSourceRequest):
                run = runs[source.test_run_id]
                critiques = () if run.review is None else run.review.critiques
                found = _finding_source(
                    critiques, source.twin_id, source.finding, item.text, test_run_id=run.id
                )
            else:
                change = changes[source.commit]
                if change.id not in latest:
                    latest[change.id] = await repository.latest_run(change.id)
                reviewed = latest[change.id]
                critiques = () if reviewed is None else reviewed.critiques
                found = _finding_source(
                    critiques, source.twin_id, source.finding, item.text, change=change
                )
            if found is None:
                raise refusal(422, TASK_SOURCE_INVALID, index=index)
            sources.append(found)
        return sources

    async def create_tasks(
        self, *, owner_user_id: UUID, project_id: UUID, body: CodeTasksRequest
    ) -> tuple[CreatedTasks, dict[str, object]]:
        sessions = database_sessions(self.runtime)
        async with sessions() as session, session.begin():
            repository = self._repository(session, owner_user_id)
            await require_project(repository, project_id)
            tests = SqlAlchemyAcceptanceTestRepository(session, owner_user_id=owner_user_id)
            sources = await self._sources(repository, tests, project_id, body.tasks)
            created = await repository.create_tasks(
                project_id, sources, created_at=datetime.now(UTC)
            )
        alignment = await self.alignment(owner_user_id=owner_user_id, project_id=project_id)
        return created, alignment

    async def set_task_status(
        self, *, owner_user_id: UUID, project_id: UUID, code: str, body: TaskStatusRequest
    ) -> tuple[CodeTask, dict[str, object]]:
        sessions = database_sessions(self.runtime)
        async with sessions() as session, session.begin():
            repository = self._repository(session, owner_user_id)
            await require_project(repository, project_id)
            number = task_number(code)
            task = (
                None
                if number is None
                else await repository.set_task_status(
                    project_id, number, body.status, at=datetime.now(UTC), note=body.note
                )
            )
            if task is None:
                raise refusal(404, CODE_TASK_NOT_FOUND)
        alignment = await self.alignment(owner_user_id=owner_user_id, project_id=project_id)
        return task, alignment


def create_code_change_router() -> APIRouter:
    router = APIRouter(prefix=CODE_CHANGES_API_PREFIX, tags=["code-changes"])

    def application(request: Request) -> CodeChangeApplication:
        return CodeChangeApplication(request.app.state.application_runtime)

    @router.get("/alignment")
    async def alignment(
        project_id: UUID,
        request: Request,
        user: CurrentUser,
    ):
        return await application(request).alignment(owner_user_id=user.id, project_id=project_id)

    @router.post("/code-changes", status_code=201)
    async def record(
        project_id: UUID,
        body: CodeChangeRequest,
        request: Request,
        user: CurrentUser,
    ):
        studio = application(request)
        result = await studio.record(owner_user_id=user.id, project_id=project_id, body=body)
        current = (
            None
            if result.change.review is None
            else await studio.current_versions(owner_user_id=user.id, project_id=project_id)
        )
        payload = {"status": result.status.value, "change": result.change.to_answer(current)}
        if result.status is CodeChangeWriteStatus.ALREADY_RECORDED:
            return JSONResponse(payload, status_code=200)
        return payload

    @router.get("/code-changes")
    async def changes(
        project_id: UUID,
        request: Request,
        user: CurrentUser,
        pending: bool = False,
    ):
        studio = application(request)
        items = await studio.changes(owner_user_id=user.id, project_id=project_id, pending=pending)
        current = await studio.current_versions(owner_user_id=user.id, project_id=project_id)
        return {"items": [item.to_answer(current) for item in items]}

    @router.get("/code-changes/{commit}")
    async def change(
        project_id: UUID,
        commit: str,
        request: Request,
        user: CurrentUser,
    ):
        studio = application(request)
        item = await studio.change(owner_user_id=user.id, project_id=project_id, commit=commit)
        current = await studio.current_versions(owner_user_id=user.id, project_id=project_id)
        return item.to_answer(current, include_diff=True)

    @router.post("/code-changes/{commit}/reviews", status_code=201)
    async def review(
        project_id: UUID,
        commit: str,
        body: ChangeReviewRequest,
        request: Request,
        user: CurrentUser,
    ):
        async def reviewing():
            result = await application(request).review(
                owner_user_id=user.id, project_id=project_id, commit=commit, body=body
            )
            return {"status": REVIEWED, "run": result.run.to_snapshot()}

        return await generation_request(
            request,
            GenerationOperation.CODE_CHANGE_REVIEW,
            reviewing,
            owner_user_id=user.id,
            project_id=project_id,
            body=body,
        )

    @router.get("/code-changes/{commit}/reviews")
    async def reviews(
        project_id: UUID,
        commit: str,
        request: Request,
        user: CurrentUser,
    ):
        items = await application(request).reviews(
            owner_user_id=user.id, project_id=project_id, commit=commit
        )
        return {"items": [item.to_snapshot() for item in items]}

    @router.post("/code-changes/{commit}/decision")
    async def decide(
        project_id: UUID,
        commit: str,
        body: ChangeDecisionRequest,
        request: Request,
        user: CurrentUser,
    ):
        studio = application(request)
        decided, alignment = await studio.decide(
            owner_user_id=user.id, project_id=project_id, commit=commit, body=body
        )
        current = await studio.current_versions(owner_user_id=user.id, project_id=project_id)
        return {"status": DECIDED, "change": decided.to_answer(current), "alignment": alignment}

    @router.get("/code-tasks")
    async def code_tasks(
        project_id: UUID,
        request: Request,
        user: CurrentUser,
        status: Literal[TASK_STATUS_FILTERS] = "open",
    ):
        items = await application(request).tasks(
            owner_user_id=user.id, project_id=project_id, every=status == "all"
        )
        return {"items": [item.to_snapshot() for item in items]}

    @router.post("/code-tasks", status_code=201)
    async def create_tasks(
        project_id: UUID,
        body: CodeTasksRequest,
        request: Request,
        user: CurrentUser,
    ):
        created, alignment = await application(request).create_tasks(
            owner_user_id=user.id, project_id=project_id, body=body
        )
        return {
            "status": CREATED,
            "created": created.created,
            "tasks": [item.to_snapshot() for item in created.tasks],
            "alignment": alignment,
        }

    @router.post("/code-tasks/{code}/status")
    async def task_status(
        project_id: UUID,
        code: str,
        body: TaskStatusRequest,
        request: Request,
        user: CurrentUser,
    ):
        task, alignment = await application(request).set_task_status(
            owner_user_id=user.id, project_id=project_id, code=code, body=body
        )
        return {"status": UPDATED, "task": task.to_snapshot(), "alignment": alignment}

    return router


__all__ = [
    "ALIGNMENT_ROLE",
    "CHANGE_REVIEW_MODEL_NOT_CONFIGURED",
    "CODE_CHANGES_API_PREFIX",
    "CODE_CHANGE_AMBIGUOUS",
    "CODE_CHANGE_NOT_FOUND",
    "CODE_CHANGE_REVIEW_EXISTS",
    "CODE_TASK_NOT_FOUND",
    "CREATED",
    "CRITIQUE_REJECTED",
    "CRITIQUE_ROLE",
    "DECIDED",
    "REVIEWED",
    "TASK_SOURCE_INVALID",
    "TASK_STATUS_FILTERS",
    "TEST_RUN_NOT_FOUND",
    "TWIN_CRITIQUED",
    "UPDATED",
    "ChangeDecisionRequest",
    "ChangeReference",
    "ChangeReviewRequest",
    "ChangeReviewResult",
    "ChangeReviewStatus",
    "ChangeSourceRequest",
    "ChangedFileRequest",
    "CodeChangeApplication",
    "CodeChangeRequest",
    "CodeTasksRequest",
    "FindingRequest",
    "OwnerSourceRequest",
    "RunSourceRequest",
    "TaskItemRequest",
    "TaskStatusRequest",
    "create_code_change_router",
    "recorded_change",
]
