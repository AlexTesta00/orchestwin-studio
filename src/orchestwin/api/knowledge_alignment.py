from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from typing import Annotated, Final, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.code_changes import (
    CODE_CHANGE_AMBIGUOUS,
    CODE_CHANGE_NOT_FOUND,
    COMMIT_REQUEST_PATTERN,
    DESIGN_APPROVAL_REQUIRED,
    PROJECT_NOT_FOUND,
    REQUIREMENTS_APPROVAL_REQUIRED,
    CodeChangeApplication,
)
from orchestwin.api.design import design_change_payload
from orchestwin.api.generation_jobs import GenerationOperation
from orchestwin.api.generation_requests import generation_request
from orchestwin.api.requirements import RequirementsRevisionPayload, _changed_revision
from orchestwin.artifacts.design_evaluation import DesignEvaluationError
from orchestwin.identity.domain import UserAccount
from orchestwin.models.generation_budget import provider_result_cost_microusd
from orchestwin.models.knowledge_alignment import (
    PURPOSE,
    alignment_context,
    bind_alignment,
    propose_alignment,
)
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
    CodeChange,
    CodeChangeAmbiguous,
)
from orchestwin.projects.knowledge_alignment import (
    MAX_ANY_REQUEST_LENGTH,
    MAX_COMMITS,
    MAX_NOTE_LENGTH,
    MAX_REQUEST_LENGTH,
    AlignmentProposal,
    KnowledgeAlignmentRun,
    ProposalAlreadyDecided,
    ProposalSection,
    ProposalStatus,
    create_run,
)
from orchestwin.projects.persistence.acceptance_tests import SqlAlchemyAcceptanceTestRepository
from orchestwin.projects.persistence.code_changes import SqlAlchemyCodeChangeRepository
from orchestwin.projects.persistence.knowledge_alignment import (
    SqlAlchemyKnowledgeAlignmentRepository,
)
from orchestwin.projects.requirements_primitives import snapshot_content_hash

KNOWLEDGE_ALIGNMENT_API_PREFIX: Final = "/projects/{project_id}"
KNOWLEDGE_ALIGNMENT_MODEL_NOT_CONFIGURED: Final = "KNOWLEDGE_ALIGNMENT_MODEL_NOT_CONFIGURED"
KNOWLEDGE_ALIGNMENT_RUN_NOT_FOUND: Final = "KNOWLEDGE_ALIGNMENT_RUN_NOT_FOUND"
ALIGNMENT_PROPOSAL_NOT_FOUND: Final = "ALIGNMENT_PROPOSAL_NOT_FOUND"
ALIGNMENT_PROPOSAL_DECIDED: Final = "ALIGNMENT_PROPOSAL_DECIDED"
INVALID_PROVIDER_OUTPUT: Final = "INVALID_PROVIDER_OUTPUT"
INVALID_REQUEST: Final = "invalid_request"
ALIGNMENT_ROLE: Final = "KNOWLEDGE_ALIGNMENT"
ALIGNMENT_REJECTED: Final = "ALIGNMENT_REJECTED"
PROPOSAL_STATUS_FILTERS: Final = ("waiting", "all")
LATEST_RUN_KEYS: Final = (
    "id",
    "from_commit",
    "to_commit",
    "created_at",
    "requirements_version_number",
    "design_version_number",
    "alternative_code",
    "summary",
)
GENERATION_ATTEMPTS: Final = 2
RETRYABLE_CODES: Final = frozenset(
    {INVALID_PROVIDER_OUTPUT, "INCOMPLETE_OUTPUT", "RESPONSE_SCHEMA_ERROR"}
)
_OPERATIONS: Final = {
    ProposalSection.REQUIREMENTS: GenerationOperation.REQUIREMENTS_CHANGE,
    ProposalSection.DESIGN: GenerationOperation.DESIGN_CHANGE,
}


def _blank_to_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


def _same_commit(first: str, second: str) -> bool:
    return first.startswith(second) or second.startswith(first)


class KnowledgeAlignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: str = Field(
        default="it-IT", min_length=2, max_length=MAX_LOCALE_LENGTH, pattern=LOCALE_PATTERN
    )
    from_commit: str | None = Field(default=None, pattern=COMMIT_REQUEST_PATTERN)
    to_commit: str = Field(pattern=COMMIT_REQUEST_PATTERN)
    commits: list[Annotated[str, Field(pattern=COMMIT_REQUEST_PATTERN)]] = Field(
        min_length=1, max_length=MAX_COMMITS
    )

    @field_validator("from_commit", "to_commit")
    @classmethod
    def lower_case(cls, value: str | None) -> str | None:
        return None if value is None else value.lower()

    @field_validator("commits")
    @classmethod
    def lower_case_commits(cls, value: list[str]) -> list[str]:
        return [item.lower() for item in value]

    @model_validator(mode="after")
    def consistent_commits(self) -> KnowledgeAlignmentRequest:
        if len(set(self.commits)) != len(self.commits):
            raise ValueError("the commits of a run are named once")
        if not _same_commit(self.to_commit, self.commits[-1]):
            raise ValueError("a run ends with the last of its commits")
        if self.from_commit is not None and any(
            _same_commit(self.from_commit, item) for item in self.commits
        ):
            raise ValueError("a run starts before its first commit")
        return self


class ProposalApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=MAX_ANY_REQUEST_LENGTH)
    locale: str = Field(
        default="it-IT", min_length=2, max_length=MAX_LOCALE_LENGTH, pattern=LOCALE_PATTERN
    )

    @field_validator("text")
    @classmethod
    def trimmed_text(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class ProposalSkipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)

    @field_validator("reason")
    @classmethod
    def trimmed_reason(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class KnowledgeAlignmentStatus(StrEnum):
    RECORDED = "KNOWLEDGE_ALIGNMENT_RECORDED"


@dataclass(frozen=True)
class KnowledgeAlignmentResult:
    status: KnowledgeAlignmentStatus
    run: KnowledgeAlignmentRun


def _refusal(status_code: int, code: str, **extra: object) -> HTTPException:
    return HTTPException(status_code, detail={"code": code, **extra})


async def _retire(role: str, code: str, run_id: UUID) -> None:
    scope = current_proposal_evidence()
    if scope is None or scope.request is None:
        return
    await scope.event("APPLICATION_RESULT", {"status": code, "alignment_run_id": str(run_id)})
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
            await _retire(role, ALIGNMENT_REJECTED, run_id)
    raise RuntimeError("knowledge alignment attempts are exhausted")


def _generation_ids() -> tuple[UUID, ...]:
    scope = current_proposal_evidence()
    if scope is None:
        return ()
    identifiers = [UUID(str(item["generation_id"])) for item in scope.related_generations]
    if scope.request is not None:
        identifiers.append(scope.request.request_id)
    return tuple(dict.fromkeys(identifiers))


def _run_item(run: KnowledgeAlignmentRun) -> dict[str, object]:
    snapshot = run.to_snapshot()
    return {
        **{key: value for key, value in snapshot.items() if key != "proposals"},
        "waiting": len(run.waiting),
        "proposals_count": len(run.proposals),
    }


def _latest_run(run: KnowledgeAlignmentRun | None) -> dict[str, object] | None:
    if run is None:
        return None
    snapshot = run.to_snapshot()
    return {key: snapshot[key] for key in LATEST_RUN_KEYS}


def _applied_text(proposal: AlignmentProposal, text: str | None) -> str:
    chosen = proposal.request if text is None else text
    if not 1 <= len(chosen) <= MAX_REQUEST_LENGTH[proposal.section]:
        raise HTTPException(422, detail=INVALID_REQUEST)
    return chosen


class KnowledgeAlignmentApplication:
    def __init__(self, runtime):
        self.runtime = runtime
        self._proposal_evidence_store = getattr(runtime, "proposal_evidence_store", None)
        self._changes = CodeChangeApplication(runtime)

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
        return SqlAlchemyKnowledgeAlignmentRepository(session, owner_user_id=owner_user_id)

    def alignment_available(self) -> bool:
        return (
            getattr(self.runtime, "real_model_runtime", None) is not None
            and self._proposal_evidence_store is not None
        )

    def _generator(self):
        if not self.alignment_available():
            raise _refusal(503, KNOWLEDGE_ALIGNMENT_MODEL_NOT_CONFIGURED)
        return self.runtime.real_model_runtime.user_modeling.proposal_port.generator

    @staticmethod
    async def _owned(repository, project_id: UUID) -> None:
        if not await repository.project_exists(project_id):
            raise _refusal(404, PROJECT_NOT_FOUND)

    @staticmethod
    async def _recorded(repository, project_id: UUID, commit: str) -> CodeChange:
        try:
            change = await repository.get(project_id, commit)
        except CodeChangeAmbiguous as error:
            raise _refusal(409, CODE_CHANGE_AMBIGUOUS) from error
        if change is None:
            raise _refusal(404, CODE_CHANGE_NOT_FOUND)
        return change

    @staticmethod
    async def _proposal(repository, project_id: UUID, code: str) -> AlignmentProposal:
        proposal = await repository.proposal(project_id, code)
        if proposal is None:
            raise _refusal(404, ALIGNMENT_PROPOSAL_NOT_FOUND)
        return proposal

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

    @evidence_application
    async def run(
        self, *, owner_user_id: UUID, project_id: UUID, body: KnowledgeAlignmentRequest
    ) -> KnowledgeAlignmentResult:
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            recorded = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner_user_id)
            changes = [
                await self._recorded(recorded, project_id, commit) for commit in body.commits
            ]
            plans = await SqlAlchemyAcceptanceTestRepository(
                session, owner_user_id=owner_user_id
            ).plans(project_id, limit=1)
        reference = await self._changes.reference(
            owner_user_id=owner_user_id, project_id=project_id
        )
        if reference.requirements is None:
            raise _refusal(409, REQUIREMENTS_APPROVAL_REQUIRED)
        if reference.design is None:
            raise _refusal(409, DESIGN_APPROVAL_REQUIRED)
        generator = self._generator()
        brief = await self._brief(owner_user_id, project_id)
        try:
            context = alignment_context(
                project_id=project_id,
                locale=body.locale,
                brief=brief,
                requirements=reference.requirements,
                design=reference.design,
                changes=changes,
                test_plan=plans[0] if plans else None,
            )
        except DesignEvaluationError as error:
            raise _refusal(409, error.code) from error
        run_id = uuid4()
        draft = await _attempt(
            partial(propose_alignment, generator, context),
            partial(bind_alignment, context=context),
            role=ALIGNMENT_ROLE,
            run_id=run_id,
        )
        generation_ids = _generation_ids()
        requirements_version, design_version = reference.version_numbers
        try:
            run = create_run(
                run_id=run_id,
                project_id=project_id,
                owner_user_id=owner_user_id,
                from_commit=body.from_commit,
                commits=tuple(item.commit for item in changes),
                locale=body.locale,
                requirements_version_number=requirements_version,
                design_version_number=design_version,
                alternative_code=reference.alternative_code,
                summary=draft.summary,
                created_at=datetime.now(UTC),
                cost_microusd=await self._cost(owner_user_id, project_id, generation_ids),
                generation_ids=generation_ids,
                proposals=draft.proposals,
            )
        except ValueError as error:
            raise HTTPException(422, detail=INVALID_REQUEST) from error
        async with sessions() as session, session.begin():
            try:
                stored = await self._repository(session, owner_user_id).create_run(run)
            except ValueError as error:
                raise _refusal(404, PROJECT_NOT_FOUND) from error
        await _accept(PURPOSE, stored.to_snapshot())
        return KnowledgeAlignmentResult(status=KnowledgeAlignmentStatus.RECORDED, run=stored)

    async def runs(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> tuple[KnowledgeAlignmentRun, ...]:
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            return await repository.runs(project_id)

    async def run_of(
        self, *, owner_user_id: UUID, project_id: UUID, run_id: UUID
    ) -> KnowledgeAlignmentRun:
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            run = await repository.run(project_id, run_id)
        if run is None:
            raise _refusal(404, KNOWLEDGE_ALIGNMENT_RUN_NOT_FOUND)
        return run

    async def proposals(
        self, *, owner_user_id: UUID, project_id: UUID, waiting_only: bool
    ) -> tuple[tuple[AlignmentProposal, ...], KnowledgeAlignmentRun | None]:
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            items = await repository.proposals(project_id, waiting_only=waiting_only)
            latest = await repository.latest_run(project_id)
        return items, latest

    async def proposal_of(
        self, *, owner_user_id: UUID, project_id: UUID, code: str
    ) -> AlignmentProposal:
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            return await self._proposal(repository, project_id, code)

    async def _decide(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        code: str,
        status: ProposalStatus,
        note: str | None = None,
        applied_text: str | None = None,
        applied_diff_id: UUID | None = None,
    ) -> AlignmentProposal:
        sessions = self._sessions()
        async with sessions() as session, session.begin():
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            try:
                decided = await repository.decide(
                    project_id,
                    code,
                    status=status,
                    decided_at=datetime.now(UTC),
                    note=note,
                    applied_text=applied_text,
                    applied_diff_id=applied_diff_id,
                )
            except ProposalAlreadyDecided as error:
                raise _refusal(409, ALIGNMENT_PROPOSAL_DECIDED) from error
        if decided is None:
            raise _refusal(404, ALIGNMENT_PROPOSAL_NOT_FOUND)
        return decided

    async def apply(
        self, *, owner_user_id: UUID, project_id: UUID, code: str, body: ProposalApplyRequest
    ) -> tuple[AlignmentProposal, dict[str, object] | None]:
        proposal = await self.proposal_of(
            owner_user_id=owner_user_id, project_id=project_id, code=code
        )
        if proposal.status is not ProposalStatus.PROPOSED:
            raise _refusal(409, ALIGNMENT_PROPOSAL_DECIDED)
        text = _applied_text(proposal, body.text)
        revision = None
        diff_id = None
        if proposal.section is ProposalSection.REQUIREMENTS:
            service = self._service(
                "requirements_change_service", "REQUIREMENTS_CHANGE_UNAVAILABLE"
            )
            result = await service.request_change(
                owner_user_id=owner_user_id, project_id=project_id, owner_request=text
            )
            changed = _changed_revision(result)
            revision = RequirementsRevisionPayload.from_domain(changed).model_dump(mode="json")
            diff_id = changed.diff.id
        elif proposal.section is ProposalSection.DESIGN:
            service = self._service("design_change_service", "DESIGN_CHANGE_UNAVAILABLE")
            result = await service.request_change(
                owner_user_id=owner_user_id,
                project_id=project_id,
                owner_request=text,
                locale=body.locale,
            )
            revision = design_change_payload(result).model_dump(mode="json")
            diff_id = result.revision.diff.id
        decided = await self._decide(
            owner_user_id=owner_user_id,
            project_id=project_id,
            code=code,
            status=ProposalStatus.APPLIED,
            applied_text=text,
            applied_diff_id=diff_id,
        )
        return decided, revision

    async def skip(
        self, *, owner_user_id: UUID, project_id: UUID, code: str, body: ProposalSkipRequest
    ) -> AlignmentProposal:
        return await self._decide(
            owner_user_id=owner_user_id,
            project_id=project_id,
            code=code,
            status=ProposalStatus.SKIPPED,
            note=body.reason,
        )


def create_knowledge_alignment_router() -> APIRouter:
    router = APIRouter(prefix=KNOWLEDGE_ALIGNMENT_API_PREFIX, tags=["knowledge-alignment"])

    def application(request: Request) -> KnowledgeAlignmentApplication:
        return KnowledgeAlignmentApplication(request.app.state.application_runtime)

    @router.post("/alignment/runs", status_code=201)
    async def run(
        project_id: UUID,
        body: KnowledgeAlignmentRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        async def aligning():
            result = await application(request).run(
                owner_user_id=user.id, project_id=project_id, body=body
            )
            return {"run": result.run.to_snapshot()}

        return await generation_request(
            request,
            GenerationOperation.KNOWLEDGE_ALIGNMENT,
            aligning,
            owner_user_id=user.id,
            project_id=project_id,
            body=body,
        )

    @router.get("/alignment/runs")
    async def runs(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        items = await application(request).runs(owner_user_id=user.id, project_id=project_id)
        return {"items": [_run_item(item) for item in items]}

    @router.get("/alignment/runs/{run_id}")
    async def run_of(
        project_id: UUID,
        run_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        item = await application(request).run_of(
            owner_user_id=user.id, project_id=project_id, run_id=run_id
        )
        return {"run": item.to_snapshot()}

    @router.get("/alignment/proposals")
    async def proposals(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        status: Literal[PROPOSAL_STATUS_FILTERS] = "waiting",
    ):
        items, latest = await application(request).proposals(
            owner_user_id=user.id, project_id=project_id, waiting_only=status == "waiting"
        )
        return {"items": [item.to_snapshot() for item in items], "latest_run": _latest_run(latest)}

    @router.post("/alignment/proposals/{code}/apply")
    async def apply(
        project_id: UUID,
        code: str,
        body: ProposalApplyRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        studio = application(request)
        proposal = await studio.proposal_of(owner_user_id=user.id, project_id=project_id, code=code)

        async def applying():
            decided, revision = await studio.apply(
                owner_user_id=user.id, project_id=project_id, code=code, body=body
            )
            return {"proposal": decided.to_snapshot(), "revision": revision}

        operation = _OPERATIONS.get(proposal.section)
        if operation is None:
            return await applying()
        return await generation_request(
            request, operation, applying, owner_user_id=user.id, project_id=project_id, body=body
        )

    @router.post("/alignment/proposals/{code}/skip")
    async def skip(
        project_id: UUID,
        code: str,
        body: ProposalSkipRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        decided = await application(request).skip(
            owner_user_id=user.id, project_id=project_id, code=code, body=body
        )
        return {"proposal": decided.to_snapshot()}

    return router


__all__ = [
    "ALIGNMENT_PROPOSAL_DECIDED",
    "ALIGNMENT_PROPOSAL_NOT_FOUND",
    "ALIGNMENT_REJECTED",
    "ALIGNMENT_ROLE",
    "KNOWLEDGE_ALIGNMENT_API_PREFIX",
    "KNOWLEDGE_ALIGNMENT_MODEL_NOT_CONFIGURED",
    "KNOWLEDGE_ALIGNMENT_RUN_NOT_FOUND",
    "LATEST_RUN_KEYS",
    "PROPOSAL_STATUS_FILTERS",
    "KnowledgeAlignmentApplication",
    "KnowledgeAlignmentRequest",
    "KnowledgeAlignmentResult",
    "KnowledgeAlignmentStatus",
    "ProposalApplyRequest",
    "ProposalSkipRequest",
    "create_knowledge_alignment_router",
]
