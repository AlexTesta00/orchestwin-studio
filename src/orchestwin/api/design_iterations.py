from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from orchestwin.api.auth import CurrentUser
from orchestwin.api.design import DesignChangeTargetRequest
from orchestwin.api.design_mockups import (
    DISCARDED_ANSWER_CODES,
    MOCKUP_ATTEMPT,
    MockupCommandError,
    MockupStatus,
    ModelMockupApplication,
    first_version_numbers,
    job_payload,
)
from orchestwin.api.generation_jobs import (
    GenerationJobKind,
    GenerationJobProgress,
    generation_jobs,
    owned_job,
)
from orchestwin.artifacts.design import contains_control_character
from orchestwin.artifacts.design_change_targets import DesignChangeTargetError
from orchestwin.artifacts.design_critique import (
    DESIGN_CRITIQUE_SOURCE_NOT_FOUND,
    DesignCritiqueError,
    critique_attachments,
    critique_source_view,
    shot_content,
)
from orchestwin.artifacts.design_critique_persistence import SqlAlchemyDesignCritiqueRepository
from orchestwin.artifacts.design_packages import MAX_OWNER_ASSERTION_LENGTH, MAX_OWNER_ASSERTIONS
from orchestwin.artifacts.visual_icons import mockup_resources
from orchestwin.models.design_change import DesignChangeTarget, target_view, with_targeted_change
from orchestwin.models.design_drafts import requirements_language, requirements_view
from orchestwin.models.generated_mockup_drafts import GeneratedIterationDraft
from orchestwin.models.generated_mockup_instructions import DESIGN_ITERATION, mockup_context
from orchestwin.models.generation_budget import provider_result_cost_microusd
from orchestwin.models.proposal_evidence import evidence_application

MAX_ITERATION_REQUEST_LENGTH: Final = 1000
MAX_NEW_ASSERTIONS: Final = 5
ITERATION_REQUEST_INVALID: Final = "ITERATION_REQUEST_INVALID"
GENERATED_MOCKUP_REQUIRED: Final = "GENERATED_MOCKUP_REQUIRED"
REQUESTED_TARGET: Final = "requested_target"


class IterationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    design_version_id: UUID
    design_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    request: str
    assertions: list[str] = Field(default_factory=list)
    target: DesignChangeTargetRequest | None = None
    critique_source_id: UUID | None = None
    opinion_id: UUID | None = Field(default=None, exclude_if=lambda value: value is None)


class IterationStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


def _invalid() -> MockupCommandError:
    return MockupCommandError(422, ITERATION_REQUEST_INVALID)


def _normalized(value: str, maximum: int) -> str:
    text = " ".join(value.split())
    if not 1 <= len(text) <= maximum or contains_control_character(text):
        raise _invalid()
    return text


def normalized_iteration(body: IterationRequest) -> tuple[str, tuple[str, ...]]:
    request = _normalized(body.request, MAX_ITERATION_REQUEST_LENGTH)
    if len(body.assertions) > MAX_NEW_ASSERTIONS:
        raise _invalid()
    assertions: list[str] = []
    for item in body.assertions:
        text = _normalized(item, MAX_OWNER_ASSERTION_LENGTH)
        if text not in assertions:
            assertions.append(text)
    return request, tuple(assertions)


def merged_assertions(package, assertions: Iterable[str]) -> tuple[str, ...]:
    merged = (
        *package.owner_assertions,
        *(item for item in assertions if item not in package.owner_assertions),
    )
    if len(merged) > MAX_OWNER_ASSERTIONS:
        raise _invalid()
    return merged


def _aimed_target(
    body: IterationRequest, mockup
) -> tuple[DesignChangeTarget | None, dict[str, object] | None]:
    if body.target is None:
        return None, None
    target = body.target.to_domain()
    try:
        return target, target_view(target, mockup)
    except DesignChangeTargetError as error:
        raise MockupCommandError(422, error.code) from error


def _recorded_request(
    target: DesignChangeTarget | None, view: Mapping[str, object] | None, source, opinion_id
) -> dict[str, object]:
    recorded: dict[str, object] = {}
    if source is not None:
        recorded["critique_source_id"] = str(source.id)
    if opinion_id is not None:
        recorded["opinion_id"] = str(opinion_id)
    snapshot = None if target is None else target.to_snapshot()
    if snapshot != view:
        recorded[REQUESTED_TARGET] = snapshot
    return recorded


def _status(events: Mapping, outcome: Mapping, applied: Mapping[str, int]):
    accepted = events.get("ADAPTER_ACCEPTED")
    if accepted is not None and outcome.get("status") == MockupStatus.GENERATED.value:
        hashes = (accepted.get("generated_content_hashes") or {}).get("DESIGN") or []
        number = next((applied[value] for value in hashes if value in applied), None)
        if number is not None:
            return IterationStatus.APPLIED, number
        return IterationStatus.PROPOSED, None
    if "ADAPTER_REJECTED" in events or outcome.get("code") in DISCARDED_ANSWER_CODES:
        return IterationStatus.REJECTED, None
    return IterationStatus.FAILED, None


def _groups(records) -> list[list]:
    groups: dict[str, list] = {}
    for record in records:
        context = record.get("context") or {}
        key = context.get("command_id") or record["generation_id"]
        groups.setdefault(str(key), []).append(record)
    return [sorted(group, key=lambda item: item["recorded_at"]) for group in groups.values()]


def _iteration_item(group, numbers, packages, applied) -> dict[str, object] | None:
    final = group[-1]
    events = final.get("events") or {}
    outcome = events.get("APPLICATION_RESULT")
    if outcome is None or outcome.get("role") == MOCKUP_ATTEMPT:
        return None
    first = group[0].get("context") or {}
    status, applied_number = _status(events, outcome, applied)
    base_id = first.get("design_version_id")
    base = packages.get(base_id)
    known = () if base is None else base.owner_assertions
    result = (events.get("ADAPTER_ACCEPTED") or {}).get("result") or {}
    return {
        "generation_id": final["generation_id"],
        "requested_at": group[0]["recorded_at"],
        "request": first.get("owner_request"),
        "target": first.get(REQUESTED_TARGET, first.get("target")),
        "critique_source_id": first.get("critique_source_id"),
        "assertions": [item for item in first.get("assertions") or [] if item not in known],
        "changes": list(result.get("changes") or []),
        "status": status.value,
        "base_design_version_number": numbers.get(base_id),
        "applied_design_version_number": applied_number,
        "cost_microusd": sum(
            provider_result_cost_microusd((record.get("events") or {}).get("PROVIDER_RESULT") or {})
            for record in group
        ),
        "warnings": list(result.get("warnings") or []),
        "corrections": list(result.get("corrections") or []),
        "opinion_id": first.get("opinion_id"),
    }


def iteration_items(records, versions) -> list[dict[str, object]]:
    numbers = {str(version.id): version.version_number for version in versions}
    packages = {str(version.id): version.package for version in versions}
    applied = first_version_numbers(versions)
    items = [
        item
        for group in _groups(records)
        if (item := _iteration_item(group, numbers, packages, applied)) is not None
    ]
    items.sort(key=lambda item: item["requested_at"], reverse=True)
    return items


class DesignIterationApplication(ModelMockupApplication):
    def applied_mockup(self, package):
        bound = package.generated_mockup
        if bound is None:
            raise MockupCommandError(409, GENERATED_MOCKUP_REQUIRED)
        return bound

    async def _critique_source(self, owner_user_id, project_id, source_id):
        database = getattr(self.runtime, "database_runtime", None)
        if database is None:
            raise MockupCommandError(503, "DATABASE_UNAVAILABLE")
        try:
            async with database.session_factory() as session:
                repository = SqlAlchemyDesignCritiqueRepository(
                    session, owner_user_id=owner_user_id
                )
                source = await repository.source(project_id, source_id)
                if source is None:
                    raise MockupCommandError(404, DESIGN_CRITIQUE_SOURCE_NOT_FOUND)
                found = {
                    shot.code: await repository.shot(project_id, source_id, shot.code)
                    for shot in source.shots
                }
            stored = {code: item[1] for code, item in found.items() if item is not None}
            return source, {shot.code: shot_content(shot, stored) for shot in source.shots}
        except DesignCritiqueError as error:
            raise MockupCommandError(404, DESIGN_CRITIQUE_SOURCE_NOT_FOUND) from error

    async def prepare_iteration(self, *, owner_user_id, project_id, body):
        _request, assertions = normalized_iteration(body)
        current = await self.checked_version(
            owner_user_id, project_id, body.design_version_id, body.design_content_hash
        )
        if body.critique_source_id is not None:
            await self._critique_source(owner_user_id, project_id, body.critique_source_id)
        bound = self.applied_mockup(current.package)
        _aimed_target(body, bound.mockup)
        merged_assertions(current.package, assertions)
        route = self.hosted_route(DESIGN_ITERATION)
        await self.grounded_requirements(owner_user_id, project_id, current)
        await self.require_budget(route, project_id)
        return bound.design_alternative_id

    def iteration_job(self, *, owner_user_id, project_id, body):
        async def run(progress):
            return await job_payload(
                self.generate_iteration(
                    owner_user_id=owner_user_id, project_id=project_id, body=body, progress=progress
                )
            )

        return run

    @evidence_application
    async def generate_iteration(self, *, owner_user_id, project_id, body, progress=None):
        progress = GenerationJobProgress() if progress is None else progress
        request, assertions = normalized_iteration(body)
        current = await self.checked_version(
            owner_user_id, project_id, body.design_version_id, body.design_content_hash
        )
        bound = self.applied_mockup(current.package)
        target, view = _aimed_target(body, bound.mockup)
        merged = merged_assertions(current.package, assertions)
        alternative = self.drawable_alternative(current.package, bound.design_alternative_id)
        route = self.hosted_route(DESIGN_ITERATION)
        requirements = await self.grounded_requirements(owner_user_id, project_id, current)
        language = requirements_language(requirements_view(requirements))
        observations = await self.observations(owner_user_id, project_id, current, alternative)
        selected_agent_ids = await self.selected_agent_ids(owner_user_id, project_id, current)
        command_id = uuid4()
        source = redraw = None
        attachments = ()
        if body.critique_source_id is not None:
            source, contents = await self._critique_source(
                owner_user_id, project_id, body.critique_source_id
            )
            redraw = critique_source_view(source, "en" if language is None else language["code"])
            attachments = critique_attachments(source, contents)
        references = self.design_references(route, len(attachments))
        if references is not None:
            attachments = (*attachments, *references.attachments)
        reference = None if references is None else references.view()
        resources = mockup_resources()
        system = self.alternative_design_system(alternative)
        recorded = _recorded_request(target, view, source, body.opinion_id)

        def context_for(previous_answer, rejection):
            context = mockup_context(
                project_id=project_id,
                purpose=DESIGN_ITERATION,
                command_id=command_id,
                version=current,
                alternative=alternative,
                requirements=requirements,
                selected_agent_ids=selected_agent_ids,
                observations=observations,
                current_mockup=bound.mockup,
                owner_request=request,
                target=view,
                assertions=merged,
                previous_answer=previous_answer,
                rejection=rejection,
                redraw=redraw,
                reference=reference,
                resources=resources,
                design_system=system,
            )
            return {**context, **recorded}

        def propose(_draft, binding):
            return replace(
                current.package,
                owner_selected_alternative_id=alternative.id,
                prototype=binding.prototype,
                generated_mockup=binding.mockup,
                owner_assertions=merged,
            )

        draft, binding, proposed, cost = await self.generate_bound(
            output_type=GeneratedIterationDraft,
            alternative=alternative,
            requirements=requirements,
            language=language,
            context_for=context_for,
            propose=propose,
            progress=progress,
            attachments=attachments,
        )
        return await self.accept(
            owner_user_id=owner_user_id,
            project_id=project_id,
            current=current,
            proposed=proposed,
            draft=draft,
            binding=binding,
            cost=cost,
            changes=with_targeted_change(
                tuple(draft.changes), target, None if language is None else language["code"]
            ),
        )

    async def iterations(self, *, owner_user_id, project_id):
        query = getattr(self.runtime, "design_query_service", None)
        if query is None:
            raise HTTPException(503, detail={"code": "DESIGN_QUERY_UNAVAILABLE"})
        reader = getattr(self._proposal_evidence_store, "design_iteration_generations", None)
        if reader is None:
            return {"items": []}
        records = await reader(owner_user_id=owner_user_id, project_id=project_id)
        if not records:
            return {"items": []}
        versions = await query.history(owner_user_id=owner_user_id, project_id=project_id)
        return {"items": iteration_items(records, versions)}


def create_design_iteration_router():
    router = APIRouter(prefix="/projects/{project_id}/design/iterations", tags=["design"])

    @router.post("/jobs", status_code=202)
    async def start_job(
        project_id: UUID,
        body: IterationRequest,
        request: Request,
        user: CurrentUser,
    ):
        jobs = generation_jobs(request)
        application = DesignIterationApplication(request.app.state.application_runtime)
        alternative_id = await application.prepare_iteration(
            owner_user_id=user.id, project_id=project_id, body=body
        )
        job = jobs.start(
            user.id,
            project_id,
            GenerationJobKind.ITERATION,
            body.design_content_hash,
            application.iteration_job(owner_user_id=user.id, project_id=project_id, body=body),
            alternative_id=alternative_id,
        )
        return job.to_payload()

    @router.get("/jobs/{job_id}")
    async def read_job(
        project_id: UUID,
        job_id: UUID,
        request: Request,
        user: CurrentUser,
    ):
        job = owned_job(request, user.id, project_id, job_id, GenerationJobKind.ITERATION)
        return job.to_payload()

    @router.get("")
    async def iterations(
        project_id: UUID,
        request: Request,
        user: CurrentUser,
    ):
        return await DesignIterationApplication(request.app.state.application_runtime).iterations(
            owner_user_id=user.id, project_id=project_id
        )

    return router


__all__ = [
    "GENERATED_MOCKUP_REQUIRED",
    "ITERATION_REQUEST_INVALID",
    "MAX_ITERATION_REQUEST_LENGTH",
    "MAX_NEW_ASSERTIONS",
    "REQUESTED_TARGET",
    "DesignIterationApplication",
    "IterationRequest",
    "IterationStatus",
    "create_design_iteration_router",
    "iteration_items",
    "merged_assertions",
    "normalized_iteration",
]
