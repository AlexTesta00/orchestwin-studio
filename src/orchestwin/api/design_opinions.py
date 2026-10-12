from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from orchestwin.api.auth import CurrentUser
from orchestwin.api.design import DesignChangeTargetRequest
from orchestwin.api.design_context import DESIGN_CONTEXT_CHANGED
from orchestwin.api.design_iterations import GENERATED_MOCKUP_REQUIRED
from orchestwin.api.design_loop import (
    RETRYABLE_REVIEW_CODES,
    DesignEvaluationMode,
    DesignLoopApplication,
)
from orchestwin.api.generation_evidence import (
    accept_generation,
    current_generation_ids,
    retire_generation,
)
from orchestwin.api.generation_jobs import GenerationOperation
from orchestwin.api.generation_requests import generation_request
from orchestwin.api.refusals import refusal
from orchestwin.api.runtime_access import generation_cost, runtime_service
from orchestwin.artifacts.design_change_opinions import (
    MAX_LOCALE_LENGTH,
    MIN_LOCALE_LENGTH,
    ChangeOpinion,
    ChangeOpinionRun,
    normalize_owner_request,
)
from orchestwin.artifacts.design_change_targets import DesignChangeTargetError, validate_target
from orchestwin.evaluation.change_opinion import (
    CHANGE_OPINION_PURPOSE,
    INVALID_CHANGE_OPINION_OUTPUT,
    ChangeOpinionRequest,
    ProposerDesignChangeOpinionReviewer,
    change_opinion_context,
    change_opinion_hosted,
    change_opinion_run,
)
from orchestwin.evaluation.evaluator import EvaluationUserTwinProfile
from orchestwin.models.generation_budget import provider_result_cost_microusd
from orchestwin.models.proposal_evidence import evidence_application

DESIGN_OPINIONS_API_PREFIX: Final = "/projects/{project_id}/design/opinions"
DESIGN_CHANGE_OPINION_FAILED: Final = "DESIGN_CHANGE_OPINION_FAILED"
DESIGN_QUERY_UNAVAILABLE: Final = "DESIGN_QUERY_UNAVAILABLE"
OPINION_ROLE: Final = "TWIN_OPINION"
OPINION_GIVEN: Final = "TWIN_OPINION_GIVEN"
OPINION_REJECTED: Final = "TWIN_OPINION_REJECTED"
RETRYABLE_OPINION_CODES: Final = RETRYABLE_REVIEW_CODES | {INVALID_CHANGE_OPINION_OUTPUT}
MAX_REASON_LENGTH: Final = 300
RUN_PAYLOAD_KEYS: Final = (
    "run_id",
    "design_version_id",
    "design_content_hash",
    "design_version_number",
    "request",
    "target",
    "locale",
    "requested_at",
    "opinions",
    "contrast",
    "cost_microusd",
)


class ChangeOpinionStatus(StrEnum):
    RECORDED = "DESIGN_CHANGE_OPINION_RECORDED"


class DesignOpinionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design_version_id: UUID
    design_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    request: str
    target: DesignChangeTargetRequest
    locale: str = Field(default="it-IT", min_length=MIN_LOCALE_LENGTH, max_length=MAX_LOCALE_LENGTH)

    @field_validator("request")
    @classmethod
    def checked_request(cls, value: str) -> str:
        normalize_owner_request(value)
        return value


@dataclass(frozen=True, slots=True)
class ChangeOpinionResult:
    status: ChangeOpinionStatus
    run: ChangeOpinionRun
    design_version_number: int


def run_payload(run: ChangeOpinionRun, design_version_number: int | None) -> dict[str, object]:
    values = {
        **run.to_snapshot(),
        "run_id": str(run.id),
        "design_version_number": design_version_number,
    }
    return {key: values[key] for key in RUN_PAYLOAD_KEYS}


def _run_reference(run_id: UUID) -> dict[str, str]:
    return {"opinion_run_id": str(run_id)}


def _command_groups(records: Iterable[Mapping[str, object]]) -> list[list[Mapping[str, object]]]:
    groups: dict[str, list[Mapping[str, object]]] = {}
    for record in records:
        groups.setdefault(str(record["context"]["command_id"]), []).append(record)
    return [sorted(group, key=lambda item: item["recorded_at"]) for group in groups.values()]


def _recorded(group: Sequence[Mapping[str, object]]) -> bool:
    outcome = group[-1]["events"].get("APPLICATION_RESULT") or {}
    return outcome.get("status") == ChangeOpinionStatus.RECORDED.value


def _stored_run(group: Sequence[Mapping[str, object]]) -> ChangeOpinionRun:
    first = group[0]
    return change_opinion_run(
        first["context"],
        requested_at=datetime.fromisoformat(first["recorded_at"]),
        opinions=[
            ChangeOpinion.from_snapshot(record["events"]["ADAPTER_ACCEPTED"]["result"])
            for record in group
            if "ADAPTER_ACCEPTED" in record["events"]
        ],
        cost_microusd=sum(
            provider_result_cost_microusd(record["events"].get("PROVIDER_RESULT") or {})
            for record in group
        ),
    )


def opinion_items(records: Iterable[Mapping[str, object]], versions) -> list[dict[str, object]]:
    numbers = {str(version.id): version.version_number for version in versions}
    runs = sorted(
        (_stored_run(group) for group in _command_groups(records) if _recorded(group)),
        key=lambda run: run.requested_at,
        reverse=True,
    )
    return [run_payload(run, numbers.get(str(run.design_version_id))) for run in runs]


def _checked_target(version, target: Mapping[str, object]) -> None:
    bound = version.package.generated_mockup
    if bound is None:
        raise refusal(409, GENERATED_MOCKUP_REQUIRED)
    try:
        validate_target(target, bound.mockup)
    except DesignChangeTargetError as error:
        raise refusal(422, error.code) from error


class DesignOpinionApplication(DesignLoopApplication):
    retryable_codes = RETRYABLE_OPINION_CODES
    retire_role = OPINION_ROLE
    retire_status = OPINION_REJECTED

    async def _opinions(self, reviewer, twins, run_id: UUID) -> list[ChangeOpinion]:
        reference = _run_reference(run_id)
        opinions = []
        for index, twin in enumerate(twins):
            if index:
                await retire_generation(OPINION_ROLE, OPINION_GIVEN, reference)
            request = ChangeOpinionRequest(
                run_id=run_id, twin=EvaluationUserTwinProfile.from_version(twin)
            )
            try:
                opinion = await self._review(reviewer, request, reference)
            except ValueError as error:
                raise refusal(
                    502, DESIGN_CHANGE_OPINION_FAILED, reason=str(error)[:MAX_REASON_LENGTH]
                ) from error
            await accept_generation(CHANGE_OPINION_PURPOSE, opinion.to_snapshot())
            opinions.append(opinion)
        return opinions

    @evidence_application
    async def ask(self, *, owner_user_id, project_id, body) -> ChangeOpinionResult:
        version = await self._current(owner_user_id, project_id)
        if (version.id, version.content_hash) != (body.design_version_id, body.design_content_hash):
            raise refusal(409, DESIGN_CONTEXT_CHANGED)
        target = body.target.to_domain().to_snapshot()
        _checked_target(version, target)
        twins = await self._twins(owner_user_id, project_id, version)
        _, generator = self._mode(DesignEvaluationMode.TWIN_REVIEW)
        run_id = uuid4()
        requested_at = datetime.now(UTC)
        context = change_opinion_context(
            version,
            command_id=run_id,
            locale=body.locale,
            owner_request=body.request,
            target=target,
            hosted=change_opinion_hosted(generator),
        )
        reviewer = ProposerDesignChangeOpinionReviewer(generator, context_base=context)
        opinions = await self._opinions(reviewer, twins, run_id)
        cost = await generation_cost(
            self._proposal_evidence_store, owner_user_id, project_id, current_generation_ids()
        )
        run = change_opinion_run(
            context, requested_at=requested_at, opinions=opinions, cost_microusd=cost
        )
        return ChangeOpinionResult(
            status=ChangeOpinionStatus.RECORDED,
            run=run,
            design_version_number=version.version_number,
        )

    async def opinion_runs(self, *, owner_user_id, project_id) -> dict[str, object]:
        query = runtime_service(self.runtime, "design_query_service", DESIGN_QUERY_UNAVAILABLE)
        reader = getattr(self._proposal_evidence_store, "design_change_opinion_generations", None)
        records = (
            []
            if reader is None
            else await reader(owner_user_id=owner_user_id, project_id=project_id)
        )
        if not records:
            return {"items": []}
        versions = await query.history(owner_user_id=owner_user_id, project_id=project_id)
        return {"items": opinion_items(records, versions)}


def create_design_opinion_router() -> APIRouter:
    router = APIRouter(prefix=DESIGN_OPINIONS_API_PREFIX, tags=["design"])

    @router.post("", status_code=201)
    async def ask(
        project_id: UUID,
        body: DesignOpinionRequest,
        request: Request,
        user: CurrentUser,
    ):
        async def opinion():
            result = await DesignOpinionApplication(request.app.state.application_runtime).ask(
                owner_user_id=user.id, project_id=project_id, body=body
            )
            return run_payload(result.run, result.design_version_number)

        return await generation_request(
            request,
            GenerationOperation.DESIGN_CHANGE_OPINION,
            opinion,
            owner_user_id=user.id,
            project_id=project_id,
            body=body,
        )

    @router.get("")
    async def opinion_runs(
        project_id: UUID,
        request: Request,
        user: CurrentUser,
    ):
        application = DesignOpinionApplication(request.app.state.application_runtime)
        return await application.opinion_runs(owner_user_id=user.id, project_id=project_id)

    return router


__all__ = [
    "DESIGN_CHANGE_OPINION_FAILED",
    "DESIGN_OPINIONS_API_PREFIX",
    "OPINION_GIVEN",
    "OPINION_REJECTED",
    "OPINION_ROLE",
    "RETRYABLE_OPINION_CODES",
    "RUN_PAYLOAD_KEYS",
    "ChangeOpinionResult",
    "ChangeOpinionStatus",
    "DesignOpinionApplication",
    "DesignOpinionRequest",
    "create_design_opinion_router",
    "opinion_items",
    "run_payload",
]
