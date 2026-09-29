from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from typing import Annotated, Final
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.generation_jobs import GenerationOperation
from orchestwin.api.generation_requests import generation_request
from orchestwin.artifacts.design_evaluation import DesignEvaluationError
from orchestwin.artifacts.design_gate import design_gate_is_currently_approved
from orchestwin.identity.domain import UserAccount
from orchestwin.knowledge.state import (
    MAX_AUTHOR_LENGTH,
    MAX_DIFF_LENGTH,
    MAX_FILES,
    MAX_MESSAGE_LENGTH,
    MAX_NOTE_LENGTH,
    MAX_PATH_LENGTH,
    MAX_TASK_LENGTH,
    MAX_TASKS,
)
from orchestwin.models.change_review import (
    ALIGNMENT_PURPOSE,
    CRITIQUE_PURPOSE,
    MAX_EARLIER_FINDINGS,
    alignment_context,
    bind_alignment,
    bind_critique,
    critique_change,
    critique_context,
    judge_alignment,
    review_material,
)
from orchestwin.models.generation_budget import provider_result_cost_microusd
from orchestwin.models.proposal_evidence import (
    ProposalEvidenceError,
    current_proposal_evidence,
    evidence_application,
    retain_adapter_result,
)
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.projects.code_changes import (
    LOCALE_PATTERN,
    MAX_LOCALE_LENGTH,
    ChangeDecision,
    ChangedFile,
    ChangedFileKind,
    ChangeReviewRun,
    CodeChange,
    CodeChangeAmbiguous,
    DecisionKind,
    create_code_change,
    normalize_author,
    normalize_diff,
    normalize_message,
    normalize_note,
    normalize_path,
    normalize_task_text,
)
from orchestwin.projects.persistence.code_changes import (
    CodeChangeWriteResult,
    CodeChangeWriteStatus,
    SqlAlchemyCodeChangeRepository,
)
from orchestwin.projects.requirements_gate import requirements_gate_is_currently_approved
from orchestwin.projects.requirements_primitives import snapshot_content_hash
from orchestwin.twins.user_modeling_gate import user_modeling_gate_is_currently_approved

CODE_CHANGES_API_PREFIX: Final = "/projects/{project_id}"
COMMIT_REQUEST_PATTERN: Final = r"^[0-9a-fA-F]{7,64}$"
RECORDED: Final = "RECORDED"
ALREADY_RECORDED: Final = "ALREADY_RECORDED"
REVIEWED: Final = "REVIEWED"
DECIDED: Final = "DECIDED"
PROJECT_NOT_FOUND: Final = "PROJECT_NOT_FOUND"
CODE_CHANGE_NOT_FOUND: Final = "CODE_CHANGE_NOT_FOUND"
CODE_CHANGE_AMBIGUOUS: Final = "CODE_CHANGE_AMBIGUOUS"
CODE_CHANGE_REVIEW_EXISTS: Final = "CODE_CHANGE_REVIEW_EXISTS"
CHANGE_REVIEW_MODEL_NOT_CONFIGURED: Final = "CHANGE_REVIEW_MODEL_NOT_CONFIGURED"
REQUIREMENTS_APPROVAL_REQUIRED: Final = "REQUIREMENTS_APPROVAL_REQUIRED"
DESIGN_APPROVAL_REQUIRED: Final = "DESIGN_APPROVAL_REQUIRED"
USER_MODELING_APPROVAL_REQUIRED: Final = "USER_MODELING_APPROVAL_REQUIRED"
INVALID_PROVIDER_OUTPUT: Final = "INVALID_PROVIDER_OUTPUT"
CRITIQUE_ROLE: Final = "CHANGE_CRITIQUE"
ALIGNMENT_ROLE: Final = "CHANGE_ALIGNMENT"
TWIN_CRITIQUED: Final = "TWIN_CRITIQUED"
CRITIQUE_REJECTED: Final = "CRITIQUE_REJECTED"
GENERATION_ATTEMPTS: Final = 2
RETRYABLE_CODES: Final = frozenset(
    {INVALID_PROVIDER_OUTPUT, "INCOMPLETE_OUTPUT", "RESPONSE_SCHEMA_ERROR"}
)


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


class ChangeDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DecisionKind
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    tasks: list[Annotated[str, Field(min_length=1, max_length=MAX_TASK_LENGTH)]] = Field(
        default_factory=list, max_length=MAX_TASKS
    )

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
        if (self.kind is DecisionKind.CODE_TASKS) != bool(self.tasks):
            raise ValueError("tasks are given exactly with a CODE_TASKS decision")
        return self


class ChangeReviewStatus(StrEnum):
    REVIEWED = "CODE_CHANGE_REVIEWED"


@dataclass(frozen=True)
class ChangeReviewResult:
    status: ChangeReviewStatus
    run: ChangeReviewRun


@dataclass(frozen=True)
class ChangeReference:
    requirements: object | None = None
    design: object | None = None

    @property
    def alternative_code(self) -> str | None:
        if self.design is None:
            return None
        package = self.design.package
        return next(
            (
                item.code
                for item in package.alternatives
                if item.id == package.owner_selected_alternative_id
            ),
            None,
        )

    @property
    def version_numbers(self) -> tuple[int | None, int | None]:
        return (
            None if self.requirements is None else self.requirements.version_number,
            None if self.design is None else self.design.version_number,
        )

    def to_snapshot(self) -> dict[str, object]:
        requirements = self.requirements
        design = self.design
        return {
            "requirements": None
            if requirements is None
            else {
                "version_id": str(requirements.id),
                "version_number": requirements.version_number,
                "content_hash": requirements.content_hash,
            },
            "design": None
            if design is None
            else {
                "version_id": str(design.id),
                "version_number": design.version_number,
                "content_hash": design.content_hash,
                "alternative_code": self.alternative_code,
            },
        }


def _refusal(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code, detail={"code": code})


async def _retire(role: str, code: str, run_id: UUID) -> None:
    scope = current_proposal_evidence()
    if scope is None or scope.request is None:
        return
    await scope.event("APPLICATION_RESULT", {"status": code, "review_run_id": str(run_id)})
    scope.retire(role=role, code=code)


async def _accept(kind: str, snapshot: dict[str, object]) -> None:
    scope = current_proposal_evidence()
    if scope is None or scope.request is None:
        return
    await scope.event(
        "ADAPTER_ACCEPTED",
        {
            "result": snapshot,
            "generated_content_hashes": {kind: [snapshot_content_hash(snapshot)]},
            **(
                {"related_generations": list(scope.related_generations)}
                if scope.related_generations
                else {}
            ),
        },
    )


async def _attempt(
    generation: Callable[[], Awaitable[object]],
    bind: Callable[[object], object],
    *,
    role: str,
    run_id: UUID,
):
    for attempt in range(1, GENERATION_ATTEMPTS + 1):
        try:
            output = await generation()
            try:
                return bind(output)
            except (TypeError, ValueError) as error:
                await retain_adapter_result(error=error, reason=str(error))
                raise ProposalGenerationError(INVALID_PROVIDER_OUTPUT) from error
        except ProposalGenerationError as error:
            if attempt == GENERATION_ATTEMPTS or error.code not in RETRYABLE_CODES:
                raise
            await _retire(role, CRITIQUE_REJECTED, run_id)
    raise RuntimeError("change review attempts are exhausted")


def _generation_ids() -> tuple[UUID, ...]:
    scope = current_proposal_evidence()
    if scope is None:
        return ()
    identifiers = [UUID(str(item["generation_id"])) for item in scope.related_generations]
    if scope.request is not None:
        identifiers.append(scope.request.request_id)
    return tuple(dict.fromkeys(identifiers))


class CodeChangeApplication:
    def __init__(self, runtime):
        self.runtime = runtime
        self._proposal_evidence_store = getattr(runtime, "proposal_evidence_store", None)

    def _sessions(self):
        database = getattr(self.runtime, "database_runtime", None)
        if database is None:
            raise _refusal(503, "DATABASE_UNAVAILABLE")
        return database.session_factory

    def _service(self, name: str, code: str):
        service = getattr(self.runtime, name, None)
        if service is None:
            raise _refusal(503, code)
        return service

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
            raise _refusal(503, CHANGE_REVIEW_MODEL_NOT_CONFIGURED)
        return self.runtime.real_model_runtime.user_modeling.proposal_port.generator

    @staticmethod
    async def _owned(repository, project_id: UUID) -> None:
        if not await repository.project_exists(project_id):
            raise _refusal(404, PROJECT_NOT_FOUND)

    @staticmethod
    async def _change(repository, project_id: UUID, commit: str) -> CodeChange:
        try:
            change = await repository.get(project_id, commit)
        except CodeChangeAmbiguous as error:
            raise _refusal(409, CODE_CHANGE_AMBIGUOUS) from error
        if change is None:
            raise _refusal(404, CODE_CHANGE_NOT_FOUND)
        return change

    async def reference(self, *, owner_user_id: UUID, project_id: UUID) -> ChangeReference:
        scope = {"owner_user_id": owner_user_id, "project_id": project_id}
        requirements = await self._service(
            "requirements_query_service", "REQUIREMENTS_QUERY_UNAVAILABLE"
        ).current(**scope)
        requirements_gate = await self._service(
            "requirements_gate_service", "REQUIREMENTS_GATE_UNAVAILABLE"
        ).current_gate(**scope)
        design = await self._service("design_query_service", "DESIGN_QUERY_UNAVAILABLE").current(
            **scope
        )
        design_gate = await self._service(
            "design_gate_service", "DESIGN_GATE_UNAVAILABLE"
        ).current_gate(**scope)
        return ChangeReference(
            requirements=requirements
            if requirements_gate_is_currently_approved(requirements_gate, requirements)
            else None,
            design=design if design_gate_is_currently_approved(design_gate, design) else None,
        )

    async def _twins(self, owner_user_id: UUID, project_id: UUID) -> tuple[object, ...]:
        services = self._service("user_modeling_services", "USER_MODELING_UNAVAILABLE")
        scope = {"owner_user_id": owner_user_id, "project_id": project_id}
        snapshot = await services.queries.current_snapshot(**scope)
        gate = await services.gates.current_gate(**scope)
        if snapshot is None or not user_modeling_gate_is_currently_approved(gate, snapshot):
            raise _refusal(409, USER_MODELING_APPROVAL_REQUIRED)
        return tuple(snapshot.snapshot.twin_versions)

    async def _brief(self, owner_user_id: UUID, project_id: UUID):
        version = await self._service("project_service", "PROJECT_QUERY_UNAVAILABLE").current_brief(
            project_id=project_id, owner_user_id=owner_user_id
        )
        if version is None:
            raise _refusal(404, PROJECT_NOT_FOUND)
        return version.brief

    async def _cost(
        self, owner_user_id: UUID, project_id: UUID, generation_ids: Sequence[UUID]
    ) -> int:
        reader = getattr(self._proposal_evidence_store, "get_owned", None)
        if reader is None:
            return 0
        total = 0
        for generation_id in generation_ids:
            try:
                record = await reader(
                    owner_user_id=owner_user_id,
                    project_id=project_id,
                    generation_id=generation_id,
                )
            except ProposalEvidenceError:
                continue
            if record is None:
                continue
            total += sum(
                provider_result_cost_microusd(item["payload"])
                for item in record["observations"]
                if item.get("kind") == "PROVIDER_RESULT"
                and isinstance(item.get("payload"), Mapping)
            )
        return total

    @staticmethod
    async def _earlier_findings(
        repository, project_id: UUID, change: CodeChange
    ) -> dict[UUID, tuple[str, ...]]:
        pending = await repository.list(project_id, pending_only=True, limit=None)
        index = next((place for place, item in enumerate(pending) if item.id == change.id), None)
        if index is None:
            return {}
        for older in pending[index + 1 :]:
            run = await repository.latest_run(older.id)
            if run is not None:
                return {
                    critique.twin_id: tuple(item.text for item in critique.findings)[
                        :MAX_EARLIER_FINDINGS
                    ]
                    for critique in run.critiques
                }
        return {}

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
        sessions = self._sessions()
        async with sessions() as session, session.begin():
            result = await self._repository(session, owner_user_id).record(change)
        if result.status is CodeChangeWriteStatus.PROJECT_NOT_FOUND:
            raise _refusal(404, PROJECT_NOT_FOUND)
        return result

    async def changes(
        self, *, owner_user_id: UUID, project_id: UUID, pending: bool = False
    ) -> tuple[CodeChange, ...]:
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            return await repository.list(project_id, pending_only=pending)

    async def change(self, *, owner_user_id: UUID, project_id: UUID, commit: str) -> CodeChange:
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            return await self._change(repository, project_id, commit)

    async def reviews(
        self, *, owner_user_id: UUID, project_id: UUID, commit: str
    ) -> tuple[ChangeReviewRun, ...]:
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            change = await self._change(repository, project_id, commit)
            return await repository.runs(change.id)

    async def alignment(self, *, owner_user_id: UUID, project_id: UUID) -> dict[str, object]:
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            aligned = await repository.aligned_point(project_id)
            pending = await repository.count(project_id, pending_only=True)
            latest = await repository.list(project_id, limit=1)
            tasks = await repository.tasks(project_id, open_only=True)
        reference = await self.reference(owner_user_id=owner_user_id, project_id=project_id)
        return {
            "project_id": str(project_id),
            "reference": reference.to_snapshot(),
            "aligned": None if aligned is None else aligned.to_snapshot(),
            "pending_changes": pending,
            "latest_change": latest[0].to_snapshot() if latest else None,
            "tasks": [task.to_snapshot() for task in tasks],
            "review_available": self.review_available(),
        }

    @evidence_application
    async def review(
        self, *, owner_user_id: UUID, project_id: UUID, commit: str, body
    ) -> ChangeReviewResult:
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            change = await self._change(repository, project_id, commit)
            if await repository.runs(change.id) and not body.again:
                raise _refusal(409, CODE_CHANGE_REVIEW_EXISTS)
            earlier = await self._earlier_findings(repository, project_id, change)
            open_tasks = await repository.tasks(project_id, open_only=True)
        reference = await self.reference(owner_user_id=owner_user_id, project_id=project_id)
        if reference.requirements is None:
            raise _refusal(409, REQUIREMENTS_APPROVAL_REQUIRED)
        if reference.design is None:
            raise _refusal(409, DESIGN_APPROVAL_REQUIRED)
        twins = await self._twins(owner_user_id, project_id)
        generator = self._generator()
        brief = await self._brief(owner_user_id, project_id)
        try:
            material = review_material(
                brief=brief,
                requirements=reference.requirements,
                design=reference.design,
                change=change,
                language=body.locale.split("-")[0],
            )
        except DesignEvaluationError as error:
            raise _refusal(409, error.code) from error
        run_id = uuid4()
        critiques = []
        for twin in twins:
            context = critique_context(
                project_id=project_id,
                locale=body.locale,
                twin=twin,
                material=material,
                earlier_findings=earlier.get(twin.twin_id, ()),
            )
            critique = await _attempt(
                partial(critique_change, generator, context),
                partial(bind_critique, twin=twin, context=context),
                role=CRITIQUE_ROLE,
                run_id=run_id,
            )
            await _accept(CRITIQUE_PURPOSE, critique.to_snapshot())
            await _retire(CRITIQUE_ROLE, TWIN_CRITIQUED, run_id)
            critiques.append(critique)
        context = alignment_context(
            project_id=project_id,
            locale=body.locale,
            material=material,
            critiques=critiques,
            open_tasks=open_tasks,
        )
        verdict = await _attempt(
            partial(judge_alignment, generator, context),
            partial(bind_alignment, context=context),
            role=ALIGNMENT_ROLE,
            run_id=run_id,
        )
        await _accept(ALIGNMENT_PURPOSE, verdict.to_snapshot())
        generation_ids = _generation_ids()
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
            cost_microusd=await self._cost(owner_user_id, project_id, generation_ids),
        )
        async with sessions() as session, session.begin():
            status = await self._repository(session, owner_user_id).create_run(run)
        if status is CodeChangeWriteStatus.PROJECT_NOT_FOUND:
            raise _refusal(404, PROJECT_NOT_FOUND)
        if status is not CodeChangeWriteStatus.RECORDED:
            raise _refusal(404, CODE_CHANGE_NOT_FOUND)
        return ChangeReviewResult(status=ChangeReviewStatus.REVIEWED, run=run)

    async def decide(
        self, *, owner_user_id: UUID, project_id: UUID, commit: str, body
    ) -> tuple[CodeChange, dict[str, object]]:
        reference = await self.reference(owner_user_id=owner_user_id, project_id=project_id)
        decided_at = datetime.now(UTC)
        decision = ChangeDecision(kind=body.kind, decided_at=decided_at, note=body.note)
        sessions = self._sessions()
        async with sessions() as session, session.begin():
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            change = await self._change(repository, project_id, commit)
            decided = await repository.decide(
                change.id, decision, aligned_versions=reference.version_numbers
            )
            if decided is None:
                raise _refusal(404, CODE_CHANGE_NOT_FOUND)
            if decision.kind is DecisionKind.ALIGNED:
                await repository.close_open_tasks(project_id, change.id, decided_at)
            elif decision.kind is DecisionKind.CODE_TASKS:
                latest = await repository.latest_run(change.id)
                await repository.create_tasks(
                    project_id,
                    change.id,
                    body.tasks,
                    created_at=decided_at,
                    requirements=() if latest is None else latest.alignment.affected_requirements,
                    screens=() if latest is None else latest.alignment.affected_screens,
                )
        alignment = await self.alignment(owner_user_id=owner_user_id, project_id=project_id)
        return decided, alignment


def create_code_change_router() -> APIRouter:
    router = APIRouter(prefix=CODE_CHANGES_API_PREFIX, tags=["code-changes"])

    @router.get("/alignment")
    async def alignment(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        return await CodeChangeApplication(request.app.state.application_runtime).alignment(
            owner_user_id=user.id, project_id=project_id
        )

    @router.post("/code-changes", status_code=201)
    async def record(
        project_id: UUID,
        body: CodeChangeRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        result = await CodeChangeApplication(request.app.state.application_runtime).record(
            owner_user_id=user.id, project_id=project_id, body=body
        )
        payload = {"status": result.status.value, "change": result.change.to_snapshot()}
        if result.status is CodeChangeWriteStatus.ALREADY_RECORDED:
            return JSONResponse(payload, status_code=200)
        return payload

    @router.get("/code-changes")
    async def changes(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        pending: bool = False,
    ):
        items = await CodeChangeApplication(request.app.state.application_runtime).changes(
            owner_user_id=user.id, project_id=project_id, pending=pending
        )
        return {"items": [item.to_snapshot() for item in items]}

    @router.get("/code-changes/{commit}")
    async def change(
        project_id: UUID,
        commit: str,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        item = await CodeChangeApplication(request.app.state.application_runtime).change(
            owner_user_id=user.id, project_id=project_id, commit=commit
        )
        return item.to_snapshot(include_diff=True)

    @router.post("/code-changes/{commit}/reviews", status_code=201)
    async def review(
        project_id: UUID,
        commit: str,
        body: ChangeReviewRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        async def reviewing():
            result = await CodeChangeApplication(request.app.state.application_runtime).review(
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
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        items = await CodeChangeApplication(request.app.state.application_runtime).reviews(
            owner_user_id=user.id, project_id=project_id, commit=commit
        )
        return {"items": [item.to_snapshot() for item in items]}

    @router.post("/code-changes/{commit}/decision")
    async def decide(
        project_id: UUID,
        commit: str,
        body: ChangeDecisionRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        decided, alignment = await CodeChangeApplication(
            request.app.state.application_runtime
        ).decide(owner_user_id=user.id, project_id=project_id, commit=commit, body=body)
        return {"status": DECIDED, "change": decided.to_snapshot(), "alignment": alignment}

    return router


__all__ = [
    "ALIGNMENT_ROLE",
    "ALREADY_RECORDED",
    "CHANGE_REVIEW_MODEL_NOT_CONFIGURED",
    "CODE_CHANGES_API_PREFIX",
    "CODE_CHANGE_AMBIGUOUS",
    "CODE_CHANGE_NOT_FOUND",
    "CODE_CHANGE_REVIEW_EXISTS",
    "CRITIQUE_REJECTED",
    "CRITIQUE_ROLE",
    "DECIDED",
    "RECORDED",
    "REVIEWED",
    "TWIN_CRITIQUED",
    "ChangeDecisionRequest",
    "ChangeReference",
    "ChangeReviewRequest",
    "ChangeReviewResult",
    "ChangeReviewStatus",
    "ChangedFileRequest",
    "CodeChangeApplication",
    "CodeChangeRequest",
    "create_code_change_router",
]
