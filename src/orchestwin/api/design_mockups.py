"""Audited visual mockups that do not replace an approved Design Package."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Annotated, Final
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.design import DesignPackagePayload
from orchestwin.api.design_context import require_current_design_context
from orchestwin.api.generation_jobs import (
    GENERATION_JOB_NOT_FOUND,
    GenerationJobFailure,
    GenerationJobKind,
    GenerationJobProgress,
    GenerationJobStage,
    generation_jobs,
)
from orchestwin.artifacts.design_evaluation_persistence import (
    SqlAlchemyDesignEvaluationRepository,
)
from orchestwin.artifacts.design_finding_validation_persistence import (
    SqlAlchemyFindingValidationRepository,
)
from orchestwin.artifacts.design_packages import MAX_OWNER_ASSERTIONS, DesignExplorationPackage
from orchestwin.artifacts.generated_mockup_document import mockup_document
from orchestwin.artifacts.generated_mockup_structure import nodes_text
from orchestwin.artifacts.generated_mockups import screen_trees
from orchestwin.artifacts.visual_catalog import ARCHETYPES
from orchestwin.identity.domain import UserAccount
from orchestwin.models.design_drafts import requirements_language, requirements_view
from orchestwin.models.design_mockups import MockupDraft, bind_mockup
from orchestwin.models.generated_mockup_drafts import (
    GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE,
    MAX_REASON_DETAIL_LENGTH,
    UNSAFE_MOCKUP_OUTPUT,
    GeneratedMockupDraft,
    GeneratedMockupRejection,
    MockupRejectionReason,
    bind_generated_mockup,
)
from orchestwin.models.generated_mockup_instructions import (
    DESIGN_ITERATION,
    DESIGN_MOCKUP_HTML,
    GENERATED_MOCKUP_PURPOSES,
    alternative_view,
    confirmed_observations,
    mockup_context,
    mockup_instruction,
)
from orchestwin.models.generation_budget import provider_result_cost_microusd
from orchestwin.models.hosted_configuration import HOSTED_PROVIDER_KINDS, ModelPrices
from orchestwin.models.output_language import dominant_language
from orchestwin.models.proposal_evidence import (
    ProposalEvidenceError,
    current_proposal_evidence,
    evidence_application,
    retain_adapter_result,
    retire_model_generation,
)
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.real_runtime import RealModelRuntimeError
from orchestwin.models.structured_generation import StructuredGenerationProviderKind

MOCKUP_RULES = (
    "Act as the UX/UI designer. Produce an actual visual mockup of the selected design in the "
    "requirements' language with real interface copy, never a narrative about a screen. Each "
    "screen depicts one moment. Never combine a successful result and an error message on one "
    "screen: SUCCESS screens contain only success content. Validation requirements remain "
    "binding for implementation but error examples are omitted unless a separate reachable "
    "ERROR screen is needed. This is a click-through mockup, not executing business logic; "
    "begin example results with 'Esempio:' in Italian or 'Example:' in English, for example "
    "'Esempio: 5 + 3 = 8'. Screen codes SCR-001, SCR-002 and so on in order; every screen must "
    "be reachable from SCR-001 and the entry screen has no return action to itself. BUTTON and "
    "LINK must have target_screen pointing to an existing screen; all other elements set "
    "target_screen null. TEXT_INPUT and SELECT need a nonempty field_name (for example "
    "'operation' for an operation SELECT), all others null. Only fields may be required. Only "
    "SELECT has nonempty options. LIST holds one item per element. Every element cites supplied "
    "requirement codes. No HTML, JavaScript, approval or empirical claims. "
)
DEFAULT_MOCKUP_RECIPE = (
    "Prefer two concise screens with up to eight elements each: SCR-001 is DEFAULT with the "
    "task inputs and a forward action to SCR-002; SCR-002 is SUCCESS with one illustrative "
    "result and a return action to SCR-001. For a calculator show operand fields, operation "
    "choice, calculate action, and an illustrative result."
)
DESIGN_MOCKUP: Final = "DESIGN_MOCKUP"
MOCKUP_PURPOSES: Final = (DESIGN_MOCKUP, *GENERATED_MOCKUP_PURPOSES)
GENERATED_OUTPUT_TOKENS: Final = 32_000
DECLARATIVE_OUTPUT_TOKENS: Final = 4096
MAX_GENERATIONS: Final = 2
MOCKUP_ATTEMPT: Final = "MOCKUP_ATTEMPT"
DISCARDED_ANSWER_CODES: Final = frozenset({"RESPONSE_SCHEMA_ERROR", "INVALID_PROVIDER_OUTPUT"})
EVALUATION_RUNS_SEARCHED: Final = 50
DEFAULT_DOCUMENT_LANGUAGE: Final = "en"
DESIGN_CONTEXT_CHANGED: Final = "DESIGN_CONTEXT_CHANGED"
DESIGN_ALTERNATIVE_NOT_FOUND: Final = "DESIGN_ALTERNATIVE_NOT_FOUND"
REAL_MOCKUP_MODEL_NOT_CONFIGURED: Final = "REAL_MOCKUP_MODEL_NOT_CONFIGURED"
GENERATED_MOCKUP_PATH_ACTIVE: Final = "GENERATED_MOCKUP_PATH_ACTIVE"
GENERATED_MOCKUP_PATH_INACTIVE: Final = "GENERATED_MOCKUP_PATH_INACTIVE"
GENERATED_MOCKUP_NOT_FOUND: Final = "GENERATED_MOCKUP_NOT_FOUND"
MOCKUP_ENTRY_SCREEN_INVALID: Final = "MOCKUP_ENTRY_SCREEN_INVALID"
GENERATION_BUDGET_EXCEEDED: Final = "GENERATION_BUDGET_EXCEEDED"
GENERATION_BUDGET_UNAVAILABLE: Final = "GENERATION_BUDGET_UNAVAILABLE"
REQUIREMENTS_QUERY_UNAVAILABLE: Final = "REQUIREMENTS_QUERY_UNAVAILABLE"


def _mockup_instruction(alternative):
    visual = alternative.visual_language
    if visual is None:
        return MOCKUP_RULES + DEFAULT_MOCKUP_RECIPE
    spec = ARCHETYPES[visual.choices.archetype]
    return (
        MOCKUP_RULES
        + f"The design follows the {spec.label} archetype ({spec.description}); the product is "
        f"called '{visual.product_name}' and its tone is {visual.choices.tone.value}. Use "
        f"between {spec.minimum_screens} and {spec.maximum_screens} screens with up to ten "
        f"elements each. Recipe: {spec.recipe}"
    )


_alternative_view = alternative_view


class MockupCommandError(HTTPException):
    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(status_code, detail={"code": code})
        self.code = code


class MockupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    design_version_id: UUID
    design_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    alternative_id: UUID


class MockupCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    generated_mockups: bool
    iterations: bool
    model: str | None
    static_check: bool
    paid: bool


class MockupStatus(StrEnum):
    GENERATED = "MOCKUP_GENERATED"


class MockupDocumentSource(StrEnum):
    APPLIED = "applied"
    LATEST = "latest"


@dataclass(frozen=True)
class MockupResult:
    status: MockupStatus
    generation_id: UUID
    design_version_id: UUID
    design_content_hash: str
    package: DesignExplorationPackage
    approach: str | None = None
    changes: tuple[str, ...] = ()
    warnings: tuple[dict, ...] = ()
    cost_microusd: int | None = None


def generated_route(generator, purpose):
    if generator is None:
        return None
    route_of = getattr(generator, "route", None)
    route = route_of("design", purpose) if callable(route_of) else generator
    configuration = getattr(route, "configuration", None)
    ceiling = getattr(configuration, "max_output_tokens", None)
    if (
        getattr(configuration, "provider_kind", None) in HOSTED_PROVIDER_KINDS
        and type(ceiling) is int
        and ceiling >= GENERATED_OUTPUT_TOKENS
    ):
        return route
    return None


def _alternative(package, alternative_id):
    return next((item for item in package.alternatives if item.id == alternative_id), None)


def _route_kind(route):
    return getattr(getattr(route, "configuration", None), "provider_kind", None)


def _unpriced(route) -> bool:
    prices = getattr(getattr(route, "configuration", None), "prices", None)
    return isinstance(prices, ModelPrices) and prices.unpriced


def _result_cost(result) -> int:
    return 0 if result is None else provider_result_cost_microusd(result.to_snapshot())


def _failure_message(error: ProposalGenerationError) -> str:
    failure = getattr(error.result, "failure", None)
    if failure is not None:
        return failure.message
    return "The answer does not satisfy the structured contract of the output."


def _discarded(error: ProposalGenerationError):
    if error.code not in DISCARDED_ANSWER_CODES:
        return None
    detail = " ".join(_failure_message(error).split())[:MAX_REASON_DETAIL_LENGTH]
    reason = MockupRejectionReason(error.code, None, detail)
    return {"code": error.code, "reasons": [reason.to_snapshot()]}


def _retryable(error: ProposalGenerationError) -> bool:
    if error.code in DISCARDED_ANSWER_CODES:
        return True
    failure = getattr(error.result, "failure", None)
    return failure is not None and failure.retryable is True


def _propose(propose, draft, binding):
    try:
        return propose(draft, binding)
    except (TypeError, ValueError) as error:
        detail = " ".join(str(error).split())[:MAX_REASON_DETAIL_LENGTH]
        raise GeneratedMockupRejection(
            UNSAFE_MOCKUP_OUTPUT, (MockupRejectionReason(UNSAFE_MOCKUP_OUTPUT, None, detail),)
        ) from error


def _payload(result):
    return {
        "status": result.status.value,
        "generation_id": str(result.generation_id),
        "design_version_id": str(result.design_version_id),
        "design_content_hash": result.design_content_hash,
        "package": DesignPackagePayload.from_domain(result.package).model_dump(mode="json"),
        "approach": result.approach,
        "changes": list(result.changes),
        "warnings": [dict(item) for item in result.warnings],
        "cost_microusd": result.cost_microusd,
    }


def _stored_package(result):
    try:
        return DesignPackagePayload.model_validate(result["package"]).to_domain()
    except (KeyError, TypeError, ValueError):
        return None


def _stored_payload(result, package):
    return {
        "status": result.get("status", MockupStatus.GENERATED.value),
        "generation_id": result.get("generation_id"),
        "design_version_id": result.get("design_version_id"),
        "design_content_hash": result.get("design_content_hash"),
        "package": DesignPackagePayload.from_domain(package).model_dump(mode="json"),
        "approach": result.get("approach"),
        "changes": list(result.get("changes") or []),
        "warnings": list(result.get("warnings") or []),
        "cost_microusd": result.get("cost_microusd"),
    }


def _rebased(current, package):
    assertions = (
        *current.owner_assertions,
        *(item for item in package.owner_assertions if item not in current.owner_assertions),
    )
    if len(assertions) > MAX_OWNER_ASSERTIONS:
        assertions = current.owner_assertions
    try:
        return replace(
            current,
            owner_selected_alternative_id=package.owner_selected_alternative_id,
            prototype=package.prototype,
            generated_mockup=package.generated_mockup,
            owner_assertions=assertions,
        )
    except (TypeError, ValueError):
        return None


def _document_language(mockup) -> str:
    trees = screen_trees(mockup)
    return (
        dominant_language(nodes_text(trees[screen.code]) for screen in mockup.screens)
        or DEFAULT_DOCUMENT_LANGUAGE
    )


def job_failure(error: Exception) -> GenerationJobFailure | None:
    if isinstance(error, GenerationJobFailure):
        return error
    if isinstance(error, GeneratedMockupRejection):
        return GenerationJobFailure(
            error.code,
            rejected=True,
            reasons=[reason.to_snapshot() for reason in error.reasons],
        )
    if isinstance(error, ProposalGenerationError):
        rejection = _discarded(error)
        return GenerationJobFailure(
            error.code,
            rejected=rejection is not None,
            reasons=() if rejection is None else rejection["reasons"],
        )
    if isinstance(error, HTTPException):
        detail = error.detail
        code = detail.get("code") if isinstance(detail, dict) else detail
        return GenerationJobFailure(str(code or error.status_code))
    if isinstance(error, ProposalEvidenceError | RealModelRuntimeError):
        return GenerationJobFailure(str(error))
    return None


async def job_payload(command):
    try:
        result = await command
    except Exception as error:
        failure = job_failure(error)
        if failure is None:
            raise
        raise failure from error
    return _payload(result)


class ModelMockupApplication:
    def __init__(self, runtime):
        self.runtime = runtime
        self._proposal_evidence_store = runtime.proposal_evidence_store

    async def current(self, owner_user_id, project_id):
        if self.runtime.design_query_service is None:
            raise HTTPException(503, detail={"code": "DESIGN_QUERY_UNAVAILABLE"})
        current = await self.runtime.design_query_service.current(
            owner_user_id=owner_user_id,
            project_id=project_id,
        )
        if current is None:
            raise HTTPException(404, detail={"code": "DESIGN_PACKAGE_NOT_FOUND"})
        return current

    def design_generator(self):
        real = getattr(self.runtime, "real_model_runtime", None)
        design = getattr(real, "design", None)
        return getattr(getattr(design, "proposal_port", None), "generator", None)

    def generated_route(self, purpose):
        if self._proposal_evidence_store is None:
            return None
        return generated_route(self.design_generator(), purpose)

    def capabilities(self) -> MockupCapabilities:
        mockups = self.generated_route(DESIGN_MOCKUP_HTML)
        iterations = self.generated_route(DESIGN_ITERATION)
        chosen = mockups if mockups is not None else iterations
        model = getattr(getattr(chosen, "configuration", None), "model", None)
        return MockupCapabilities(
            generated_mockups=mockups is not None,
            iterations=iterations is not None,
            model=model if chosen is not None and isinstance(model, str) else None,
            static_check=getattr(self.runtime, "final_evaluator_runtime", None) is not None,
            paid=chosen is None
            or _route_kind(chosen) is not StructuredGenerationProviderKind.CLAUDE_CODE_CLI,
        )

    @evidence_application
    async def generate(self, *, owner_user_id, project_id, body):
        current = await self.checked_version(
            owner_user_id, project_id, body.design_version_id, body.design_content_hash
        )
        alternative = _alternative(current.package, body.alternative_id)
        if alternative is None:
            raise HTTPException(422, detail={"code": DESIGN_ALTERNATIVE_NOT_FOUND})
        real = self.runtime.real_model_runtime
        if real is None or self._proposal_evidence_store is None:
            raise HTTPException(503, detail={"code": REAL_MOCKUP_MODEL_NOT_CONFIGURED})
        if self.generated_route(DESIGN_MOCKUP_HTML) is not None:
            raise HTTPException(409, detail={"code": GENERATED_MOCKUP_PATH_ACTIVE})
        requirements = await self.runtime.requirements_query_service.current(
            owner_user_id=owner_user_id,
            project_id=project_id,
        )
        reference = current.package.grounding.requirements_reference
        if requirements is None or (requirements.id, requirements.content_hash) != (
            reference.artifact_id,
            reference.content_hash,
        ):
            raise HTTPException(409, detail={"code": DESIGN_CONTEXT_CHANGED})
        generator = real.design.proposal_port.generator
        route_of = getattr(generator, "route", None)
        route = route_of("design", DESIGN_MOCKUP) if callable(route_of) else generator
        draft = await generator.generate(
            task="design",
            output_type=MockupDraft,
            max_output_tokens=min(DECLARATIVE_OUTPUT_TOKENS, route.configuration.max_output_tokens),
            context={
                "project_id": str(project_id),
                "purpose": DESIGN_MOCKUP,
                "design_version_id": str(current.id),
                "design_content_hash": current.content_hash,
                "alternative": _alternative_view(alternative),
                "requirements": requirements_view(requirements),
            },
            instruction=_mockup_instruction(alternative),
        )
        try:
            prototype = bind_mockup(draft, alternative, requirements)
            proposed = replace(
                current.package,
                owner_selected_alternative_id=alternative.id,
                prototype=prototype,
                generated_mockup=None,
            )
        except (TypeError, ValueError) as error:
            await retain_adapter_result(error=error, reason=str(error))
            raise ProposalGenerationError("INVALID_MOCKUP_OUTPUT") from error
        await self.checked_version(owner_user_id, project_id, current.id, current.content_hash)
        scope = current_proposal_evidence()
        result = MockupResult(
            status=MockupStatus.GENERATED,
            generation_id=scope.request.request_id,
            design_version_id=current.id,
            design_content_hash=current.content_hash,
            package=proposed,
        )
        await scope.event(
            "ADAPTER_ACCEPTED",
            {
                "result": _payload(result),
                "generated_content_hashes": {"DESIGN": [proposed.content_hash]},
            },
        )
        return result

    async def checked_version(self, owner_user_id, project_id, version_id, content_hash):
        current = await self.current(owner_user_id, project_id)
        if (current.id, current.content_hash) != (version_id, content_hash):
            raise MockupCommandError(409, DESIGN_CONTEXT_CHANGED)
        await require_current_design_context(
            self.runtime, owner_user_id=owner_user_id, project_id=project_id
        )
        await self.selected_agent_ids(owner_user_id, project_id, current)
        return current

    async def selected_agent_ids(self, owner_user_id, project_id, current):
        if not hasattr(self.runtime, "team_proposal_service"):
            return ()
        service = self.runtime.team_proposal_service
        team = (
            None
            if service is None
            else await service.current(owner_user_id=owner_user_id, project_id=project_id)
        )
        reference = current.package.grounding.agent_team_reference
        if team is None or (team.project_id, team.id, team.version_number, team.content_hash) != (
            project_id,
            reference.artifact_id,
            reference.version_number,
            reference.content_hash,
        ):
            raise MockupCommandError(409, DESIGN_CONTEXT_CHANGED)
        return tuple(team.proposal.selected_agent_ids)

    async def grounded_requirements(self, owner_user_id, project_id, current):
        query = getattr(self.runtime, "requirements_query_service", None)
        if query is None:
            raise MockupCommandError(503, REQUIREMENTS_QUERY_UNAVAILABLE)
        requirements = await query.current(owner_user_id=owner_user_id, project_id=project_id)
        reference = current.package.grounding.requirements_reference
        if requirements is None or (requirements.id, requirements.content_hash) != (
            reference.artifact_id,
            reference.content_hash,
        ):
            raise MockupCommandError(409, DESIGN_CONTEXT_CHANGED)
        return requirements

    def hosted_route(self, purpose):
        real = getattr(self.runtime, "real_model_runtime", None)
        if real is None or self._proposal_evidence_store is None or self.design_generator() is None:
            raise MockupCommandError(503, REAL_MOCKUP_MODEL_NOT_CONFIGURED)
        route = self.generated_route(purpose)
        if route is None:
            raise MockupCommandError(409, GENERATED_MOCKUP_PATH_INACTIVE)
        return route

    async def require_budget(self, route, project_id):
        budget = getattr(route, "budget", None)
        if budget is None or _unpriced(route):
            return
        reader = getattr(self._proposal_evidence_store, "spent_microusd", None)
        if reader is None:
            raise MockupCommandError(503, GENERATION_BUDGET_UNAVAILABLE)
        try:
            project_spent = await reader(project_id=project_id)
            total_spent = await reader(since=budget.period_start)
        except ProposalEvidenceError as error:
            raise MockupCommandError(503, GENERATION_BUDGET_UNAVAILABLE) from error
        if project_spent >= budget.per_project_microusd or total_spent >= budget.total_microusd:
            raise MockupCommandError(402, GENERATION_BUDGET_EXCEEDED)

    def drawable_alternative(self, package, alternative_id):
        alternative = _alternative(package, alternative_id)
        if alternative is None:
            raise MockupCommandError(422, DESIGN_ALTERNATIVE_NOT_FOUND)
        if alternative.visual_language is None:
            raise MockupCommandError(422, GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE)
        return alternative

    async def observations(self, owner_user_id, project_id, version, alternative):
        database = getattr(self.runtime, "database_runtime", None)
        if database is None:
            return []
        try:
            async with database.session_factory() as session:
                runs = await SqlAlchemyDesignEvaluationRepository(
                    session, owner_user_id=owner_user_id
                ).list(project_id=project_id, limit=EVALUATION_RUNS_SEARCHED)
                run = next((item for item in runs if item.alternative_id == alternative.id), None)
                if run is None:
                    return []
                validations = await SqlAlchemyFindingValidationRepository(
                    session, owner_user_id=owner_user_id
                ).current(project_id=project_id)
        except (KeyError, TypeError, ValueError):
            return []
        names = {
            reference.twin_id: reference.name
            for reference in version.package.grounding.user_twin_references
        }
        return confirmed_observations(run, validations, names)

    async def generate_bound(
        self,
        *,
        output_type,
        alternative,
        requirements,
        language,
        context_for: Callable,
        propose: Callable,
        progress: GenerationJobProgress,
    ):
        generator = self.design_generator()
        code = None if language is None else language["code"]
        cost = 0
        previous_answer = rejection = None
        for attempt in range(1, MAX_GENERATIONS + 1):
            progress.update(
                GenerationJobStage.GENERATING if attempt == 1 else GenerationJobStage.RETRYING,
                attempt,
            )
            context = context_for(previous_answer, rejection)
            try:
                draft = await generator.generate(
                    task="design",
                    context=context,
                    output_type=output_type,
                    instruction=mockup_instruction(
                        alternative, requirements=requirements, language=language, context=context
                    ),
                    max_output_tokens=GENERATED_OUTPUT_TOKENS,
                    retry_schema_errors=False,
                    retry_transient_failures=False,
                )
            except ProposalGenerationError as error:
                cost += _result_cost(error.result)
                if attempt < MAX_GENERATIONS and _retryable(error):
                    await retire_model_generation(role=MOCKUP_ATTEMPT, code=error.code)
                    previous_answer, rejection = None, _discarded(error)
                    continue
                raise
            cost += _result_cost(getattr(current_proposal_evidence(), "result", None))
            progress.update(GenerationJobStage.VALIDATING, attempt)
            try:
                binding = bind_generated_mockup(
                    draft, alternative=alternative, requirements=requirements, language=code
                )
                proposed = _propose(propose, draft, binding)
            except GeneratedMockupRejection as error:
                await retain_adapter_result(error=error, reason=error.reason_text())
                if attempt < MAX_GENERATIONS:
                    await retire_model_generation(role=MOCKUP_ATTEMPT, code=error.code)
                    previous_answer, rejection = draft.model_dump(mode="json"), error.to_snapshot()
                    continue
                raise
            return draft, binding, proposed, cost
        raise RuntimeError("mockup generations are exhausted")

    async def accept(
        self, *, owner_user_id, project_id, current, proposed, draft, binding, cost, changes=()
    ):
        await self.checked_version(owner_user_id, project_id, current.id, current.content_hash)
        scope = current_proposal_evidence()
        result = MockupResult(
            status=MockupStatus.GENERATED,
            generation_id=scope.request.request_id,
            design_version_id=current.id,
            design_content_hash=current.content_hash,
            package=proposed,
            approach=draft.approach,
            changes=tuple(changes),
            warnings=binding.warning_snapshots(),
            cost_microusd=cost,
        )
        related = list(scope.related_generations)
        await scope.event(
            "ADAPTER_ACCEPTED",
            {
                "result": _payload(result),
                "generated_content_hashes": {"DESIGN": [proposed.content_hash]},
                **({"related_generations": related} if related else {}),
            },
        )
        return result

    async def prepare_mockup(self, *, owner_user_id, project_id, body):
        current = await self.checked_version(
            owner_user_id, project_id, body.design_version_id, body.design_content_hash
        )
        alternative = self.drawable_alternative(current.package, body.alternative_id)
        route = self.hosted_route(DESIGN_MOCKUP_HTML)
        await self.grounded_requirements(owner_user_id, project_id, current)
        await self.require_budget(route, project_id)
        return alternative

    def mockup_job(self, *, owner_user_id, project_id, body):
        async def run(progress):
            return await job_payload(
                self.generate_mockup(
                    owner_user_id=owner_user_id, project_id=project_id, body=body, progress=progress
                )
            )

        return run

    @evidence_application
    async def generate_mockup(self, *, owner_user_id, project_id, body, progress=None):
        progress = GenerationJobProgress() if progress is None else progress
        current = await self.checked_version(
            owner_user_id, project_id, body.design_version_id, body.design_content_hash
        )
        alternative = self.drawable_alternative(current.package, body.alternative_id)
        self.hosted_route(DESIGN_MOCKUP_HTML)
        requirements = await self.grounded_requirements(owner_user_id, project_id, current)
        language = requirements_language(requirements_view(requirements))
        observations = await self.observations(owner_user_id, project_id, current, alternative)
        selected_agent_ids = await self.selected_agent_ids(owner_user_id, project_id, current)
        command_id = uuid4()

        def context_for(previous_answer, rejection):
            return mockup_context(
                project_id=project_id,
                purpose=DESIGN_MOCKUP_HTML,
                command_id=command_id,
                version=current,
                alternative=alternative,
                requirements=requirements,
                selected_agent_ids=selected_agent_ids,
                observations=observations,
                previous_answer=previous_answer,
                rejection=rejection,
            )

        def propose(_draft, binding):
            return replace(
                current.package,
                owner_selected_alternative_id=alternative.id,
                prototype=binding.prototype,
                generated_mockup=binding.mockup,
            )

        draft, binding, proposed, cost = await self.generate_bound(
            output_type=GeneratedMockupDraft,
            alternative=alternative,
            requirements=requirements,
            language=language,
            context_for=context_for,
            propose=propose,
            progress=progress,
        )
        return await self.accept(
            owner_user_id=owner_user_id,
            project_id=project_id,
            current=current,
            proposed=proposed,
            draft=draft,
            binding=binding,
            cost=cost,
        )

    async def _earlier_hashes(self, owner_user_id, project_id, version, alternative):
        history = getattr(self.runtime.design_query_service, "history", None)
        if history is None:
            return ()
        snapshot = alternative.to_snapshot()
        hashes = []
        for item in await history(owner_user_id=owner_user_id, project_id=project_id):
            candidate = _alternative(item.package, alternative.id)
            if (
                item.content_hash != version.content_hash
                and candidate is not None
                and candidate.to_snapshot() == snapshot
            ):
                hashes.append(item.content_hash)
        return tuple(hashes)

    async def newest_accepted(self, owner_user_id, project_id, version, alternative_id, purposes):
        store = self._proposal_evidence_store
        alternative = _alternative(version.package, alternative_id)
        if store is None or alternative is None:
            return None
        common = {
            "owner_user_id": owner_user_id,
            "project_id": project_id,
            "alternative_id": alternative_id,
            "purposes": purposes,
        }
        result = await store.latest_design_mockup(
            design_content_hashes=(version.content_hash,), **common
        )
        if result is None:
            earlier = await self._earlier_hashes(owner_user_id, project_id, version, alternative)
            if earlier:
                result = await store.latest_design_mockup(design_content_hashes=earlier, **common)
        if result is None:
            return None
        package = _stored_package(result)
        if package is None or package.owner_selected_alternative_id != alternative_id:
            return None
        return result, package

    async def latest(self, *, owner_user_id, project_id, alternative_id):
        version = await self.current(owner_user_id, project_id)
        found = await self.newest_accepted(
            owner_user_id, project_id, version, alternative_id, MOCKUP_PURPOSES
        )
        if found is None:
            return None
        result, package = found
        if result.get("design_content_hash") != version.content_hash:
            package = _rebased(version.package, package)
            if package is None:
                return None
        return _stored_payload(result, package)

    async def document(self, *, owner_user_id, project_id, alternative_id, source, entry_screen):
        version = await self.current(owner_user_id, project_id)
        if source is MockupDocumentSource.APPLIED:
            package = version.package
            bound = package.generated_mockup
            if bound is None or bound.design_alternative_id != alternative_id:
                raise MockupCommandError(404, GENERATED_MOCKUP_NOT_FOUND)
        else:
            found = await self.newest_accepted(
                owner_user_id, project_id, version, alternative_id, GENERATED_MOCKUP_PURPOSES
            )
            if found is None or found[1].generated_mockup is None:
                raise MockupCommandError(404, GENERATED_MOCKUP_NOT_FOUND)
            package = found[1]
            bound = package.generated_mockup
        mockup = bound.mockup
        codes = [screen.code for screen in mockup.screens]
        entry = codes[0] if entry_screen is None else entry_screen
        if entry not in codes:
            raise MockupCommandError(422, MOCKUP_ENTRY_SCREEN_INVALID)
        alternative = _alternative(package, alternative_id)
        html = mockup_document(
            mockup,
            tokens=alternative.visual_language.token_values,
            language=_document_language(mockup),
            entry_screen=entry,
        )
        return {
            "html": html,
            "content_hash": hashlib.sha256(html.encode("utf-8")).hexdigest(),
            "source": source.value,
            "alternative_id": str(alternative_id),
            "title": mockup.title,
            "entry_screen": entry,
            "screens": [
                {"code": screen.code, "title": screen.title, "state": screen.state.value}
                for screen in mockup.screens
            ],
        }


def create_design_mockup_router():
    router = APIRouter(prefix="/projects/{project_id}/design/mockups", tags=["design"])

    @router.post("")
    async def generate(
        project_id: UUID,
        body: MockupRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        result = await ModelMockupApplication(request.app.state.application_runtime).generate(
            owner_user_id=user.id,
            project_id=project_id,
            body=body,
        )
        return _payload(result)

    @router.get("")
    async def current(
        project_id: UUID,
        alternative_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        return await ModelMockupApplication(request.app.state.application_runtime).latest(
            owner_user_id=user.id, project_id=project_id, alternative_id=alternative_id
        )

    @router.get("/capabilities", response_model=MockupCapabilities)
    async def capabilities(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        return ModelMockupApplication(request.app.state.application_runtime).capabilities()

    @router.post("/jobs", status_code=202)
    async def start_job(
        project_id: UUID,
        body: MockupRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        jobs = generation_jobs(request)
        application = ModelMockupApplication(request.app.state.application_runtime)
        await application.prepare_mockup(owner_user_id=user.id, project_id=project_id, body=body)
        job = jobs.start(
            user.id,
            project_id,
            GenerationJobKind.MOCKUP,
            f"{body.design_content_hash}:{body.alternative_id}",
            application.mockup_job(owner_user_id=user.id, project_id=project_id, body=body),
            alternative_id=body.alternative_id,
        )
        return job.to_payload()

    @router.get("/jobs/{job_id}")
    async def read_job(
        project_id: UUID,
        job_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        job = generation_jobs(request).get(user.id, project_id, job_id, GenerationJobKind.MOCKUP)
        if job is None:
            raise HTTPException(404, detail={"code": GENERATION_JOB_NOT_FOUND})
        return job.to_payload()

    @router.get("/document")
    async def document(
        project_id: UUID,
        alternative_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        source: MockupDocumentSource = MockupDocumentSource.LATEST,
        entry_screen: str | None = None,
    ):
        return await ModelMockupApplication(request.app.state.application_runtime).document(
            owner_user_id=user.id,
            project_id=project_id,
            alternative_id=alternative_id,
            source=source,
            entry_screen=entry_screen,
        )

    return router


__all__ = [
    "DISCARDED_ANSWER_CODES",
    "GENERATED_MOCKUP_NOT_FOUND",
    "GENERATED_MOCKUP_PATH_ACTIVE",
    "GENERATED_MOCKUP_PATH_INACTIVE",
    "GENERATED_OUTPUT_TOKENS",
    "MAX_GENERATIONS",
    "MOCKUP_ATTEMPT",
    "MOCKUP_ENTRY_SCREEN_INVALID",
    "MOCKUP_PURPOSES",
    "MockupCapabilities",
    "MockupCommandError",
    "MockupDocumentSource",
    "MockupRequest",
    "MockupResult",
    "MockupStatus",
    "ModelMockupApplication",
    "create_design_mockup_router",
    "generated_route",
    "job_failure",
    "job_payload",
]
