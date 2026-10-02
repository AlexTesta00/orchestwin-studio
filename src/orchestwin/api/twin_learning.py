from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from typing import Annotated, Final
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.code_changes import ChangeReference
from orchestwin.api.generation_jobs import GenerationOperation
from orchestwin.api.generation_requests import generation_request
from orchestwin.api.research_evidence import research_evidence_refusal
from orchestwin.artifacts.design_evaluation import DesignEvaluationError
from orchestwin.artifacts.design_gate import design_gate_is_currently_approved
from orchestwin.identity.domain import UserAccount
from orchestwin.knowledge.state import MAX_OBSERVATION_LENGTH, MAX_UPDATE_OBSERVATIONS
from orchestwin.models.evidence_update import (
    bind_evidence_update,
    evidence_update_context,
    propose_evidence_update,
)
from orchestwin.models.generation_budget import provider_result_cost_microusd
from orchestwin.models.proposal_evidence import (
    ProposalEvidenceError,
    current_proposal_evidence,
    evidence_application,
    retain_adapter_result,
)
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.twin_update import (
    UPDATE_PURPOSE,
    bind_update,
    learning_material,
    propose_update,
    update_context,
    update_material,
)
from orchestwin.projects.code_changes import LOCALE_PATTERN, MAX_LOCALE_LENGTH
from orchestwin.projects.evidence_application import apply_update_changes, current_approved_snapshot
from orchestwin.projects.persistence.acceptance_tests import SqlAlchemyAcceptanceTestRepository
from orchestwin.projects.persistence.code_changes import SqlAlchemyCodeChangeRepository
from orchestwin.projects.persistence.research_evidence import SqlAlchemyResearchEvidenceRepository
from orchestwin.projects.persistence.twin_learning import (
    SqlAlchemyTwinLearningRepository,
    TwinLearningWriteResult,
    TwinLearningWriteStatus,
)
from orchestwin.projects.requirements_gate import requirements_gate_is_currently_approved
from orchestwin.projects.requirements_primitives import snapshot_content_hash
from orchestwin.projects.research_evidence import EvidenceUpdateSource, ResearchEvidenceError
from orchestwin.projects.twin_learning import (
    MAX_LEARNING_REASON_LENGTH,
    REQUIREMENT_CODE_PATTERN,
    SCREEN_CODE_PATTERN,
    KeptObservation,
    ObservationDraft,
    TwinLearning,
    TwinUpdate,
    UpdateDecisionKind,
    UpdateStatus,
    build_twin_learning,
    normalize_learning_reason,
    normalize_statement,
    requested_observation_number,
)
from orchestwin.twins.persistence.uow import SqlAlchemyUserModelingUnitOfWork
from orchestwin.twins.user_modeling_gate import user_modeling_gate_is_currently_approved

TWIN_LEARNING_API_PREFIX: Final = "/projects/{project_id}"
PROPOSED: Final = "PROPOSED"
DECIDED: Final = "DECIDED"
LEARNED: Final = "LEARNED"
RETIRED: Final = "RETIRED"
INVALID_REQUEST: Final = "invalid_request"
PROJECT_NOT_FOUND: Final = "PROJECT_NOT_FOUND"
USER_MODELING_APPROVAL_REQUIRED: Final = "USER_MODELING_APPROVAL_REQUIRED"
USER_TWIN_NOT_FOUND: Final = "USER_TWIN_NOT_FOUND"
REQUIREMENTS_APPROVAL_REQUIRED: Final = "REQUIREMENTS_APPROVAL_REQUIRED"
DESIGN_APPROVAL_REQUIRED: Final = "DESIGN_APPROVAL_REQUIRED"
TWIN_UPDATE_PENDING: Final = "TWIN_UPDATE_PENDING"
TWIN_UPDATE_NOTHING_NEW: Final = "TWIN_UPDATE_NOTHING_NEW"
TWIN_UPDATE_MODEL_NOT_CONFIGURED: Final = "TWIN_UPDATE_MODEL_NOT_CONFIGURED"
TWIN_UPDATE_NOT_FOUND: Final = "TWIN_UPDATE_NOT_FOUND"
TWIN_UPDATE_ALREADY_DECIDED: Final = "TWIN_UPDATE_ALREADY_DECIDED"
TWIN_UPDATE_CONTEXT_CHANGED: Final = "TWIN_UPDATE_CONTEXT_CHANGED"
TWIN_OBSERVATIONS_LIMIT: Final = "TWIN_OBSERVATIONS_LIMIT"
TWIN_OBSERVATION_NOT_FOUND: Final = "TWIN_OBSERVATION_NOT_FOUND"
INVALID_PROVIDER_OUTPUT: Final = "INVALID_PROVIDER_OUTPUT"
LEARNER_ROLE: Final = "TWIN_LEARNER"
UPDATE_REJECTED: Final = "UPDATE_REJECTED"
UNKNOWN_INDEX: Final = "the proposal has no observation at this index"
GENERATION_ATTEMPTS: Final = 2
RETRYABLE_CODES: Final = frozenset(
    {INVALID_PROVIDER_OUTPUT, "INCOMPLETE_OUTPUT", "RESPONSE_SCHEMA_ERROR"}
)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TwinUpdateRequest(_Body):
    locale: str = Field(
        default="it-IT", min_length=2, max_length=MAX_LOCALE_LENGTH, pattern=LOCALE_PATTERN
    )
    evidence_id: UUID | None = Field(default=None, exclude_if=lambda value: value is None)
    evidence_version: int | None = Field(default=None, ge=1, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def evidence_reference(self):
        if self.evidence_version is not None and self.evidence_id is None:
            raise ValueError("an evidence version requires its source ID")
        return self


class KeptObservationRequest(_Body):
    index: int = Field(ge=0)
    statement: str | None = Field(default=None, min_length=1, max_length=MAX_OBSERVATION_LENGTH)

    @field_validator("statement")
    @classmethod
    def valid_statement(cls, value: str | None) -> str | None:
        return None if value is None else normalize_statement(value)

    def to_domain(self) -> KeptObservation:
        return KeptObservation(index=self.index, statement=self.statement)


class TwinUpdateDecisionRequest(_Body):
    decision: UpdateDecisionKind
    kept: list[KeptObservationRequest] = Field(
        default_factory=list, max_length=MAX_UPDATE_OBSERVATIONS
    )
    reason: str | None = Field(default=None, max_length=MAX_LEARNING_REASON_LENGTH)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value: str | None) -> str | None:
        return normalize_learning_reason(value)

    @model_validator(mode="after")
    def kept_of_the_decision(self) -> TwinUpdateDecisionRequest:
        if (self.decision is UpdateDecisionKind.APPROVE) != bool(self.kept):
            raise ValueError("an approval keeps one or more observations and a rejection none")
        indexes = [item.index for item in self.kept]
        if len(set(indexes)) != len(indexes):
            raise ValueError("a decision keeps each observation once")
        return self


class ObservationAboutRequest(_Body):
    requirement: str | None = Field(default=None, pattern=REQUIREMENT_CODE_PATTERN)
    screen: str | None = Field(default=None, pattern=SCREEN_CODE_PATTERN)


class LearnedObservationRequest(_Body):
    statement: str = Field(min_length=1, max_length=MAX_OBSERVATION_LENGTH)
    about: ObservationAboutRequest | None = None

    @field_validator("statement")
    @classmethod
    def valid_statement(cls, value: str) -> str:
        return normalize_statement(value)

    def to_domain(self) -> ObservationDraft:
        about = self.about
        return ObservationDraft(
            statement=self.statement,
            requirement=None if about is None else about.requirement,
            screen=None if about is None else about.screen,
        )


class RetireObservationRequest(_Body):
    reason: str | None = Field(default=None, max_length=MAX_LEARNING_REASON_LENGTH)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value: str | None) -> str | None:
        return normalize_learning_reason(value)


class TwinUpdateStatus(StrEnum):
    PROPOSED = "TWIN_UPDATE_PROPOSED"


@dataclass(frozen=True)
class TwinUpdateResult:
    status: TwinUpdateStatus
    update: TwinUpdate


def _refusal(status_code: int, code: str, **extra: object) -> HTTPException:
    return HTTPException(status_code, detail={"code": code, **extra})


def _pending(update: TwinUpdate | None) -> HTTPException:
    return _refusal(409, TWIN_UPDATE_PENDING, update_id=None if update is None else str(update.id))


def _unknown_index(position: int | None) -> HTTPException:
    return _refusal(
        422,
        INVALID_REQUEST,
        errors=[
            {
                "loc": ["body", "kept", position, "index"],
                "type": "value_error",
                "msg": UNKNOWN_INDEX,
            }
        ],
    )


def _refused(result: TwinLearningWriteResult) -> HTTPException | None:
    status = result.status
    if status is TwinLearningWriteStatus.RECORDED:
        return None
    if status is TwinLearningWriteStatus.UPDATE_PENDING:
        return _pending(result.pending)
    if status is TwinLearningWriteStatus.INDEX_UNKNOWN:
        return _unknown_index(result.position)
    refusals = {
        TwinLearningWriteStatus.PROJECT_NOT_FOUND: (404, PROJECT_NOT_FOUND),
        TwinLearningWriteStatus.UPDATE_NOT_FOUND: (404, TWIN_UPDATE_NOT_FOUND),
        TwinLearningWriteStatus.ALREADY_DECIDED: (409, TWIN_UPDATE_ALREADY_DECIDED),
        TwinLearningWriteStatus.CONTEXT_CHANGED: (409, TWIN_UPDATE_CONTEXT_CHANGED),
        TwinLearningWriteStatus.LIMIT_REACHED: (409, TWIN_OBSERVATIONS_LIMIT),
        TwinLearningWriteStatus.OBSERVATION_NOT_FOUND: (404, TWIN_OBSERVATION_NOT_FOUND),
    }
    status_code, code = refusals[status]
    return _refusal(status_code, code)


def _written(result: TwinLearningWriteResult) -> TwinLearningWriteResult:
    refusal = _refused(result)
    if refusal is not None:
        raise refusal
    return result


async def _retire(reference: Mapping[str, str]) -> None:
    scope = current_proposal_evidence()
    if scope is None or scope.request is None:
        return
    await scope.event("APPLICATION_RESULT", {"status": UPDATE_REJECTED, **reference})
    scope.retire(role=LEARNER_ROLE, code=UPDATE_REJECTED)


async def _accept(snapshot: dict[str, object]) -> None:
    scope = current_proposal_evidence()
    if scope is None or scope.request is None:
        return
    await scope.event(
        "ADAPTER_ACCEPTED",
        {
            "result": snapshot,
            "generated_content_hashes": {UPDATE_PURPOSE: [snapshot_content_hash(snapshot)]},
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
    reference: Mapping[str, str],
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
            await _retire(reference)
    raise RuntimeError("twin update attempts are exhausted")


def _generation_ids() -> tuple[UUID, ...]:
    scope = current_proposal_evidence()
    if scope is None:
        return ()
    identifiers = [UUID(str(item["generation_id"])) for item in scope.related_generations]
    if scope.request is not None:
        identifiers.append(scope.request.request_id)
    return tuple(dict.fromkeys(identifiers))


class TwinLearningApplication:
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
        return SqlAlchemyTwinLearningRepository(session, owner_user_id=owner_user_id)

    def update_available(self) -> bool:
        return (
            getattr(self.runtime, "real_model_runtime", None) is not None
            and self._proposal_evidence_store is not None
        )

    def _generator(self):
        if not self.update_available():
            raise _refusal(503, TWIN_UPDATE_MODEL_NOT_CONFIGURED)
        return self.runtime.real_model_runtime.user_modeling.proposal_port.generator

    async def _owned(self, owner_user_id: UUID, project_id: UUID) -> None:
        async with self._sessions()() as session:
            exists = await self._repository(session, owner_user_id).project_exists(project_id)
        if not exists:
            raise _refusal(404, PROJECT_NOT_FOUND)

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

    async def _approved(self, owner_user_id: UUID, project_id: UUID) -> ChangeReference:
        reference = await self.reference(owner_user_id=owner_user_id, project_id=project_id)
        if reference.requirements is None:
            raise _refusal(409, REQUIREMENTS_APPROVAL_REQUIRED)
        if reference.design is None:
            raise _refusal(409, DESIGN_APPROVAL_REQUIRED)
        return reference

    async def approved_twins(self, *, owner_user_id: UUID, project_id: UUID) -> tuple[object, ...]:
        services = self._service("user_modeling_services", "USER_MODELING_UNAVAILABLE")
        scope = {"owner_user_id": owner_user_id, "project_id": project_id}
        snapshot = await services.queries.current_snapshot(**scope)
        gate = await services.gates.current_gate(**scope)
        if snapshot is None or not user_modeling_gate_is_currently_approved(gate, snapshot):
            return ()
        return tuple(snapshot.snapshot.twin_versions)

    async def _twin(self, owner_user_id: UUID, project_id: UUID, twin_id: UUID):
        twins = await self.approved_twins(owner_user_id=owner_user_id, project_id=project_id)
        if not twins:
            raise _refusal(409, USER_MODELING_APPROVAL_REQUIRED)
        twin = next((item for item in twins if item.twin_id == twin_id), None)
        if twin is None:
            raise _refusal(404, USER_TWIN_NOT_FOUND)
        return twin

    @staticmethod
    def _entry(twin, records) -> TwinLearning:
        return build_twin_learning(
            twin_id=twin.twin_id,
            twin_name=twin.profile.name,
            profile_version_number=twin.version_number,
            records=records,
        )

    @staticmethod
    async def _sources(session, owner_user_id: UUID, project_id: UUID) -> dict[str, tuple]:
        changes = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner_user_id)
        tests = SqlAlchemyAcceptanceTestRepository(session, owner_user_id=owner_user_id)
        recorded = await changes.list(project_id, limit=None)
        runs = await changes.project_runs(project_id)
        tasks = await changes.tasks(project_id)
        test_runs = await tests.runs(project_id, limit=None)
        return {
            "changes": tuple(item.to_snapshot() for item in recorded),
            "change_runs": tuple(item.to_snapshot() for item in runs),
            "test_runs": tuple(item.to_snapshot() for item in test_runs),
            "tasks": tuple(item.to_snapshot() for item in tasks),
        }

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

    async def overview(self, *, owner_user_id: UUID, project_id: UUID) -> dict[str, object]:
        await self._owned(owner_user_id, project_id)
        twins = await self.approved_twins(owner_user_id=owner_user_id, project_id=project_id)
        entries = []
        if twins:
            async with self._sessions()() as session:
                repository = self._repository(session, owner_user_id)
                sources = await self._sources(session, owner_user_id, project_id)
                for twin in twins:
                    records = await repository.observations(project_id, twin.twin_id)
                    pending = await repository.pending_update(project_id, twin.twin_id)
                    latest = await repository.latest_update(project_id, twin.twin_id)
                    material = update_material(
                        twin_id=twin.twin_id,
                        since=None if latest is None else latest.created_at,
                        **sources,
                    )
                    entries.append(
                        {
                            **self._entry(twin, records).to_snapshot(),
                            "pending_update": None if pending is None else pending.to_snapshot(),
                            "new_material": material.counts(),
                        }
                    )
        return {
            "project_id": str(project_id),
            "update_available": self.update_available(),
            "twins": entries,
        }

    @evidence_application
    async def propose(
        self, *, owner_user_id: UUID, project_id: UUID, twin_id: UUID, body
    ) -> TwinUpdateResult:
        await self._owned(owner_user_id, project_id)
        if getattr(body, "evidence_id", None) is not None:
            return await self._propose_evidence(
                owner_user_id=owner_user_id, project_id=project_id, twin_id=twin_id, body=body
            )
        twin = await self._twin(owner_user_id, project_id, twin_id)
        reference = await self._approved(owner_user_id, project_id)
        created_at = datetime.now(UTC)
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            pending = await repository.pending_update(project_id, twin.twin_id)
            if pending is not None:
                raise _pending(pending)
            records = await repository.observations(project_id, twin.twin_id)
            latest = await repository.latest_update(project_id, twin.twin_id)
            sources = await self._sources(session, owner_user_id, project_id)
        material = update_material(
            twin_id=twin.twin_id, since=None if latest is None else latest.created_at, **sources
        )
        if material.empty:
            raise _refusal(409, TWIN_UPDATE_NOTHING_NEW)
        generator = self._generator()
        brief = await self._brief(owner_user_id, project_id)
        try:
            views = learning_material(
                brief=brief,
                requirements=reference.requirements,
                design=reference.design,
                language=body.locale.split("-")[0],
            )
        except DesignEvaluationError as error:
            raise _refusal(409, error.code) from error
        entry = self._entry(twin, records)
        experience = material.experience()
        context = update_context(
            project_id=project_id,
            locale=body.locale,
            twin=twin,
            learned=entry.learned_view(),
            material=views,
            experience=experience,
        )
        update_id = uuid4()
        comment, observations = await _attempt(
            partial(propose_update, generator, context),
            partial(bind_update, context=context),
            reference={"twin_update_id": str(update_id)},
        )
        generation_ids = _generation_ids()
        update = TwinUpdate(
            id=update_id,
            twin_id=twin.twin_id,
            twin_name=entry.twin_name,
            created_at=created_at,
            locale=body.locale,
            status=UpdateStatus.PROPOSED if observations else UpdateStatus.EMPTY,
            base_profile_version=entry.profile_version_number,
            base_development_version=entry.development_version_number,
            comment=comment,
            observations=observations,
            material_changes=len(experience["changes"]),
            material_tests=len(experience["tests"]),
            generation_ids=generation_ids,
            cost_microusd=await self._cost(owner_user_id, project_id, generation_ids),
        )
        await _accept(update.to_snapshot())
        async with sessions() as session, session.begin():
            _written(
                await self._repository(session, owner_user_id).create_update(project_id, update)
            )
        return TwinUpdateResult(status=TwinUpdateStatus.PROPOSED, update=update)

    async def _evidence_context_guard(
        self, session, *, owner_user_id: UUID, project_id: UUID, twin_id: UUID, twin=None
    ):
        uow = SqlAlchemyUserModelingUnitOfWork(session, owner_user_id=owner_user_id)
        if not await uow.lock_project(project_id=project_id):
            raise _refusal(404, PROJECT_NOT_FOUND)
        if await uow.has_pending_manual_revision(project_id=project_id):
            raise _refusal(409, "USER_TWIN_REVISION_PENDING")
        snapshot = await current_approved_snapshot(
            session, owner_user_id=owner_user_id, project_id=project_id
        )
        current = next(
            (item for item in snapshot.snapshot.twin_versions if item.twin_id == twin_id), None
        )
        if current is None:
            raise _refusal(404, USER_TWIN_NOT_FOUND)
        if twin is not None and (
            current.id != twin.id
            or current.version_number != twin.version_number
            or current.content_hash != twin.content_hash
        ):
            raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
        return current

    async def _propose_evidence(
        self, *, owner_user_id: UUID, project_id: UUID, twin_id: UUID, body
    ):
        try:
            async with self._sessions()() as session, session.begin():
                twin = await self._evidence_context_guard(
                    session, owner_user_id=owner_user_id, project_id=project_id, twin_id=twin_id
                )
                learning = self._repository(session, owner_user_id)
                pending = await learning.pending_update(project_id, twin_id)
                if pending is not None:
                    raise _pending(pending)
                records = await learning.observations(project_id, twin_id)
                sources = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=owner_user_id)
                source = await sources.get(project_id, body.evidence_id, body.evidence_version)
                if source is None:
                    raise ResearchEvidenceError("EVIDENCE_NOT_FOUND")
                latest = await sources.get(project_id, source.id)
                if latest.version != source.version:
                    raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
                if source.status.value != "ACTIVE":
                    raise ResearchEvidenceError("EVIDENCE_RETIRED")
                text = await sources.text(project_id, source.id, source.version)
                if text is None:
                    raise ResearchEvidenceError("EVIDENCE_TEXT_UNAVAILABLE")
            context = evidence_update_context(
                project_id=project_id,
                locale=body.locale,
                twin=twin,
                evidence=source.to_snapshot(),
                text=text,
            )
            update_id = uuid4()
            comment, observations, rejected = await _attempt(
                partial(propose_evidence_update, self._generator(), context),
                partial(bind_evidence_update, context=context),
                reference={"twin_update_id": str(update_id)},
            )
            generation_ids = _generation_ids()
            update = TwinUpdate(
                id=update_id,
                twin_id=twin.twin_id,
                twin_name=twin.profile.name,
                created_at=datetime.now(UTC),
                locale=body.locale,
                status=UpdateStatus.PROPOSED if observations else UpdateStatus.EMPTY,
                base_profile_version=twin.version_number,
                base_development_version=self._entry(twin, records).development_version_number,
                comment=comment,
                observations=observations,
                generation_ids=generation_ids,
                cost_microusd=await self._cost(owner_user_id, project_id, generation_ids),
                evidence=EvidenceUpdateSource(
                    source.id, source.version, source.content_hash, rejected
                ),
            )
            await _accept(update.to_snapshot())
            async with self._sessions()() as session, session.begin():
                await self._evidence_context_guard(
                    session,
                    owner_user_id=owner_user_id,
                    project_id=project_id,
                    twin_id=twin_id,
                    twin=twin,
                )
                sources = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=owner_user_id)
                current = await sources.get(project_id, source.id)
                if (
                    current is None
                    or current.status.value != "ACTIVE"
                    or current.version != source.version
                    or current.content_hash != source.content_hash
                ):
                    raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
                if (
                    await self._repository(session, owner_user_id).development_version(
                        project_id, twin_id
                    )
                    != update.base_development_version
                ):
                    raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
                _written(
                    await self._repository(session, owner_user_id).create_update(project_id, update)
                )
            return TwinUpdateResult(status=TwinUpdateStatus.PROPOSED, update=update)
        except ResearchEvidenceError as error:
            raise research_evidence_refusal(error) from error

    async def update_of(
        self, *, owner_user_id: UUID, project_id: UUID, update_id: UUID
    ) -> TwinUpdate:
        await self._owned(owner_user_id, project_id)
        async with self._sessions()() as session:
            update = await self._repository(session, owner_user_id).update(project_id, update_id)
        if update is None:
            raise _refusal(404, TWIN_UPDATE_NOT_FOUND)
        return update

    async def decide(
        self, *, owner_user_id: UUID, project_id: UUID, update_id: UUID, body
    ) -> tuple[TwinUpdate, TwinLearning]:
        await self._owned(owner_user_id, project_id)
        existing = await self.update_of(
            owner_user_id=owner_user_id, project_id=project_id, update_id=update_id
        )
        if existing.evidence is not None:
            return await self._decide_evidence(
                owner_user_id=owner_user_id, project_id=project_id, update_id=update_id, body=body
            )
        twins = await self.approved_twins(owner_user_id=owner_user_id, project_id=project_id)
        async with self._sessions()() as session, session.begin():
            repository = self._repository(session, owner_user_id)
            result = _written(
                await repository.decide_update(
                    project_id,
                    update_id,
                    body.decision,
                    tuple(item.to_domain() for item in body.kept),
                    decided_at=datetime.now(UTC),
                    reason=body.reason,
                )
            )
            update = result.update
            records = await repository.observations(project_id, update.twin_id)
        twin = next((item for item in twins if item.twin_id == update.twin_id), None)
        if twin is not None:
            return update, self._entry(twin, records)
        return update, build_twin_learning(
            twin_id=update.twin_id,
            twin_name=update.twin_name,
            profile_version_number=update.base_profile_version,
            records=records,
        )

    async def _decide_evidence(
        self, *, owner_user_id: UUID, project_id: UUID, update_id: UUID, body
    ):
        try:
            async with self._sessions()() as session, session.begin():
                repository = self._repository(session, owner_user_id)
                if not await repository._lock_project(project_id):
                    raise _refusal(404, PROJECT_NOT_FOUND)
                update = await repository.update(project_id, update_id)
                if update is None:
                    raise _refusal(404, TWIN_UPDATE_NOT_FOUND)
                if body.decision is UpdateDecisionKind.APPROVE:
                    await self._evidence_context_guard(
                        session,
                        owner_user_id=owner_user_id,
                        project_id=project_id,
                        twin_id=update.twin_id,
                    )
                kept = tuple(item.to_domain() for item in body.kept)
                result = _written(
                    await repository.decide_update(
                        project_id,
                        update_id,
                        body.decision,
                        kept,
                        decided_at=datetime.now(UTC),
                        reason=body.reason,
                    )
                )
                update = result.update
                if body.decision is UpdateDecisionKind.APPROVE:
                    snapshot = await apply_update_changes(
                        session,
                        owner_user_id=owner_user_id,
                        project_id=project_id,
                        update=update,
                        kept=kept,
                        occurred_at=update.decision.decided_at,
                    )
                    twin = next(
                        item
                        for item in snapshot.snapshot.twin_versions
                        if item.twin_id == update.twin_id
                    )
                else:
                    snapshot = await SqlAlchemyUserModelingUnitOfWork(
                        session, owner_user_id=owner_user_id
                    ).snapshots.current(project_id=project_id)
                    twin = (
                        None
                        if snapshot is None
                        else next(
                            (
                                item
                                for item in snapshot.snapshot.twin_versions
                                if item.twin_id == update.twin_id
                            ),
                            None,
                        )
                    )
                records = await repository.observations(project_id, update.twin_id)
            if twin is not None:
                return update, self._entry(twin, records)
            return update, build_twin_learning(
                twin_id=update.twin_id,
                twin_name=update.twin_name,
                profile_version_number=update.base_profile_version,
                records=records,
            )
        except ResearchEvidenceError as error:
            raise research_evidence_refusal(error) from error

    async def learn(
        self, *, owner_user_id: UUID, project_id: UUID, twin_id: UUID, body
    ) -> TwinLearning:
        await self._owned(owner_user_id, project_id)
        twin = await self._twin(owner_user_id, project_id, twin_id)
        async with self._sessions()() as session, session.begin():
            repository = self._repository(session, owner_user_id)
            _written(
                await repository.add(
                    project_id, twin.twin_id, (body.to_domain(),), approved_at=datetime.now(UTC)
                )
            )
            records = await repository.observations(project_id, twin.twin_id)
        return self._entry(twin, records)

    async def retire(
        self, *, owner_user_id: UUID, project_id: UUID, twin_id: UUID, code: str, body
    ) -> TwinLearning:
        await self._owned(owner_user_id, project_id)
        twin = await self._twin(owner_user_id, project_id, twin_id)
        number = requested_observation_number(code)
        if number is None:
            raise _refusal(404, TWIN_OBSERVATION_NOT_FOUND)
        async with self._sessions()() as session, session.begin():
            repository = self._repository(session, owner_user_id)
            _written(
                await repository.retire(
                    project_id,
                    twin.twin_id,
                    number,
                    retired_at=datetime.now(UTC),
                    reason=body.reason,
                )
            )
            records = await repository.observations(project_id, twin.twin_id)
        return self._entry(twin, records)


def create_twin_learning_router() -> APIRouter:
    router = APIRouter(prefix=TWIN_LEARNING_API_PREFIX, tags=["twin-learning"])

    def application(request: Request) -> TwinLearningApplication:
        return TwinLearningApplication(request.app.state.application_runtime)

    @router.get("/twin-learning")
    async def overview(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        return await application(request).overview(owner_user_id=user.id, project_id=project_id)

    @router.post("/user-twins/{twin_id}/updates", status_code=201)
    async def propose(
        project_id: UUID,
        twin_id: UUID,
        body: TwinUpdateRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        async def proposing():
            result = await application(request).propose(
                owner_user_id=user.id, project_id=project_id, twin_id=twin_id, body=body
            )
            return {"status": PROPOSED, "update": result.update.to_snapshot()}

        return await generation_request(
            request,
            GenerationOperation.TWIN_UPDATE,
            proposing,
            owner_user_id=user.id,
            project_id=project_id,
            body=body,
        )

    @router.get("/twin-updates/{update_id}")
    async def update_of(
        project_id: UUID,
        update_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        update = await application(request).update_of(
            owner_user_id=user.id, project_id=project_id, update_id=update_id
        )
        return update.to_snapshot()

    @router.post("/twin-updates/{update_id}/decision")
    async def decide(
        project_id: UUID,
        update_id: UUID,
        body: TwinUpdateDecisionRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        update, twin = await application(request).decide(
            owner_user_id=user.id, project_id=project_id, update_id=update_id, body=body
        )
        return {"status": DECIDED, "update": update.to_snapshot(), "twin": twin.to_snapshot()}

    @router.post("/user-twins/{twin_id}/observations", status_code=201)
    async def learn(
        project_id: UUID,
        twin_id: UUID,
        body: LearnedObservationRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        twin = await application(request).learn(
            owner_user_id=user.id, project_id=project_id, twin_id=twin_id, body=body
        )
        return {"status": LEARNED, "twin": twin.to_snapshot()}

    @router.post("/user-twins/{twin_id}/observations/{code}/retire")
    async def retire(
        project_id: UUID,
        twin_id: UUID,
        code: str,
        body: RetireObservationRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        twin = await application(request).retire(
            owner_user_id=user.id, project_id=project_id, twin_id=twin_id, code=code, body=body
        )
        return {"status": RETIRED, "twin": twin.to_snapshot()}

    return router


__all__ = [
    "DECIDED",
    "DESIGN_APPROVAL_REQUIRED",
    "INVALID_PROVIDER_OUTPUT",
    "INVALID_REQUEST",
    "LEARNED",
    "LEARNER_ROLE",
    "PROJECT_NOT_FOUND",
    "PROPOSED",
    "REQUIREMENTS_APPROVAL_REQUIRED",
    "RETIRED",
    "TWIN_LEARNING_API_PREFIX",
    "TWIN_OBSERVATIONS_LIMIT",
    "TWIN_OBSERVATION_NOT_FOUND",
    "TWIN_UPDATE_ALREADY_DECIDED",
    "TWIN_UPDATE_CONTEXT_CHANGED",
    "TWIN_UPDATE_MODEL_NOT_CONFIGURED",
    "TWIN_UPDATE_NOTHING_NEW",
    "TWIN_UPDATE_NOT_FOUND",
    "TWIN_UPDATE_PENDING",
    "UNKNOWN_INDEX",
    "UPDATE_REJECTED",
    "USER_MODELING_APPROVAL_REQUIRED",
    "USER_TWIN_NOT_FOUND",
    "KeptObservationRequest",
    "LearnedObservationRequest",
    "ObservationAboutRequest",
    "RetireObservationRequest",
    "TwinLearningApplication",
    "TwinUpdateDecisionRequest",
    "TwinUpdateRequest",
    "TwinUpdateResult",
    "TwinUpdateStatus",
    "create_twin_learning_router",
]
