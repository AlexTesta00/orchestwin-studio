from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from typing import Annotated, Final, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.code_changes import ChangeReference
from orchestwin.api.generation_jobs import GenerationOperation
from orchestwin.api.generation_requests import generation_request
from orchestwin.artifacts.design_evaluation import DesignEvaluationError
from orchestwin.artifacts.design_gate import design_gate_is_currently_approved
from orchestwin.identity.domain import UserAccount
from orchestwin.knowledge.state import (
    BROWSER_NAMES,
    MAX_ADDRESS_LENGTH,
    MAX_BROWSER_VERSION_LENGTH,
    MAX_BROWSERS,
    MAX_CRITERIA_PER_PATH,
    MAX_EARLIER_PATHS,
    MAX_EXPECTED_TEXT_LENGTH,
    MAX_PAGE_TEXT_LENGTH,
    MAX_PATH_HEADING_LENGTH,
    MAX_REASON_LENGTH,
    MAX_RESULTS,
    MAX_SCREENSHOT_PATH_LENGTH,
    MAX_SNAPSHOT_ELEMENTS,
    MAX_SNAPSHOT_HIDDEN_TEXT_LENGTH,
    MAX_SNAPSHOT_OPTIONS,
    MAX_SNAPSHOT_TEXT_LENGTH,
    MAX_STEP_DETAIL_LENGTH,
    MAX_STEP_VALUE_LENGTH,
    MAX_STEPS,
    MAX_TARGET_NAME_LENGTH,
    TEST_ROLES,
    review_is_stale,
)
from orchestwin.models.generation_budget import provider_result_cost_microusd
from orchestwin.models.proposal_evidence import (
    ProposalEvidenceError,
    current_proposal_evidence,
    evidence_application,
    retain_adapter_result,
)
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.test_planning import (
    PLAN_PURPOSE,
    acceptance_material,
    bind_plan,
    plan_context,
    plan_tests,
)
from orchestwin.models.test_review import (
    REVIEW_PURPOSE,
    bind_test_critique,
    critique_context,
    critique_run,
    run_material,
)
from orchestwin.projects.acceptance_tests import (
    CRITERION_CODE_PATTERN,
    ELEMENT_STATES,
    MAX_OPTION_LABEL_LENGTH,
    MAX_PATH_SECONDS,
    MAX_REPLANS,
    MAX_REQUESTED_CRITERIA,
    MAX_SNAPSHOT_TITLE_LENGTH,
    MAX_SNAPSHOT_URL_LENGTH,
    MAX_SNAPSHOT_VALUE_LENGTH,
    PATH_CODE_PATTERN,
    ApplicationKind,
    BrowserInfo,
    EarlierPath,
    ExpectationKind,
    NotCovered,
    PageSnapshot,
    PathResult,
    PathStatus,
    SnapshotElement,
    StepAction,
    StepResult,
    StepStatus,
    TestApplication,
    TestExpectation,
    TestPath,
    TestPlan,
    TestPlanUnknown,
    TestReview,
    TestRun,
    TestStep,
    TestTarget,
    build_test_run,
    cut_text,
    normalize_address,
    normalize_screenshot,
)
from orchestwin.projects.code_changes import LOCALE_PATTERN, MAX_LOCALE_LENGTH, normalized_line
from orchestwin.projects.persistence.acceptance_tests import (
    AcceptanceTestWriteStatus,
    SqlAlchemyAcceptanceTestRepository,
)
from orchestwin.projects.persistence.twin_learning import SqlAlchemyTwinLearningRepository
from orchestwin.projects.requirements_gate import requirements_gate_is_currently_approved
from orchestwin.projects.requirements_primitives import snapshot_content_hash
from orchestwin.projects.twin_learning import learned_view
from orchestwin.twins.user_modeling_gate import user_modeling_gate_is_currently_approved

ACCEPTANCE_TESTS_API_PREFIX: Final = "/projects/{project_id}"
CRITERION_REQUEST_PATTERN: Final = r"^[A-Za-z0-9-]+$"
MAX_CRITERION_REQUEST_LENGTH: Final = 20
MAX_RAW_TEXT_LENGTH: Final = 100_000
PLANNED: Final = "PLANNED"
RECORDED: Final = "RECORDED"
REVIEWED: Final = "REVIEWED"
INVALID_REQUEST: Final = "invalid_request"
PROJECT_NOT_FOUND: Final = "PROJECT_NOT_FOUND"
TEST_PLAN_NOT_FOUND: Final = "TEST_PLAN_NOT_FOUND"
TEST_RUN_NOT_FOUND: Final = "TEST_RUN_NOT_FOUND"
TEST_REVIEW_EXISTS: Final = "TEST_REVIEW_EXISTS"
TEST_MODEL_NOT_CONFIGURED: Final = "TEST_MODEL_NOT_CONFIGURED"
ACCEPTANCE_CRITERION_UNKNOWN: Final = "ACCEPTANCE_CRITERION_UNKNOWN"
REQUIREMENTS_APPROVAL_REQUIRED: Final = "REQUIREMENTS_APPROVAL_REQUIRED"
DESIGN_APPROVAL_REQUIRED: Final = "DESIGN_APPROVAL_REQUIRED"
USER_MODELING_APPROVAL_REQUIRED: Final = "USER_MODELING_APPROVAL_REQUIRED"
INVALID_PROVIDER_OUTPUT: Final = "INVALID_PROVIDER_OUTPUT"
PLANNER_ROLE: Final = "TEST_PLANNER"
CRITIQUE_ROLE: Final = "TEST_CRITIQUE"
PLAN_REJECTED: Final = "PLAN_REJECTED"
TWIN_CRITIQUED: Final = "TWIN_CRITIQUED"
CRITIQUE_REJECTED: Final = "CRITIQUE_REJECTED"
GENERATION_ATTEMPTS: Final = 2
RETRYABLE_CODES: Final = frozenset(
    {INVALID_PROVIDER_OUTPUT, "INCOMPLETE_OUTPUT", "RESPONSE_SCHEMA_ERROR"}
)

CriterionCode = Annotated[str, Field(pattern=CRITERION_CODE_PATTERN)]
CriterionName = Annotated[
    str,
    Field(min_length=1, max_length=MAX_CRITERION_REQUEST_LENGTH, pattern=CRITERION_REQUEST_PATTERN),
]
PageText = Annotated[str, Field(max_length=MAX_RAW_TEXT_LENGTH)]


def _line(value: str | None, *, label: str, maximum: int) -> str | None:
    return None if value is None else normalized_line(value, label=label, maximum=maximum)


def _page(value: str | None, *, maximum: int) -> str | None:
    return None if value is None else cut_text(value, maximum=maximum)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApplicationRequest(_Body):
    kind: ApplicationKind
    address: str = Field(min_length=1, max_length=MAX_ADDRESS_LENGTH)

    def to_domain(self) -> TestApplication:
        return TestApplication(kind=self.kind, address=normalize_address(self.kind, self.address))

    @model_validator(mode="after")
    def valid_application(self) -> ApplicationRequest:
        self.to_domain()
        return self


class TargetRequest(_Body):
    role: Literal[TEST_ROLES] | None = None
    name: str = Field(min_length=1, max_length=MAX_TARGET_NAME_LENGTH)

    def to_domain(self) -> TestTarget:
        return TestTarget(
            role=self.role,
            name=normalized_line(self.name, label="target name", maximum=MAX_TARGET_NAME_LENGTH),
        )

    @model_validator(mode="after")
    def valid_target(self) -> TargetRequest:
        self.to_domain()
        return self


class ExpectationRequest(_Body):
    kind: ExpectationKind
    target: TargetRequest | None = None
    text: str | None = Field(default=None, max_length=MAX_EXPECTED_TEXT_LENGTH)

    def to_domain(self) -> TestExpectation:
        return TestExpectation(
            kind=self.kind,
            target=None if self.target is None else self.target.to_domain(),
            text=_line(self.text, label="expected text", maximum=MAX_EXPECTED_TEXT_LENGTH),
        )

    @model_validator(mode="after")
    def valid_expectation(self) -> ExpectationRequest:
        self.to_domain()
        return self


class StepRequest(_Body):
    action: StepAction
    target: TargetRequest | None = None
    value: str | None = Field(default=None, max_length=MAX_STEP_VALUE_LENGTH)
    expect: ExpectationRequest | None = None

    def to_domain(self) -> TestStep:
        return TestStep(
            action=self.action,
            target=None if self.target is None else self.target.to_domain(),
            value=_line(self.value, label="step value", maximum=MAX_STEP_VALUE_LENGTH),
            expect=None if self.expect is None else self.expect.to_domain(),
        )

    @model_validator(mode="after")
    def valid_step(self) -> StepRequest:
        self.to_domain()
        return self


class PathRequest(_Body):
    code: str = Field(pattern=PATH_CODE_PATTERN)
    heading: str = Field(min_length=1, max_length=MAX_PATH_HEADING_LENGTH)
    criteria: list[CriterionCode] = Field(min_length=1, max_length=MAX_CRITERIA_PER_PATH)
    steps: list[StepRequest] = Field(min_length=1, max_length=MAX_STEPS)

    def to_domain(self) -> TestPath:
        return TestPath(
            code=self.code,
            heading=normalized_line(
                self.heading, label="path heading", maximum=MAX_PATH_HEADING_LENGTH
            ),
            criteria=tuple(self.criteria),
            steps=tuple(item.to_domain() for item in self.steps),
        )

    @model_validator(mode="after")
    def valid_path(self) -> PathRequest:
        self.to_domain()
        return self


class ElementRequest(_Body):
    index: int = Field(ge=0)
    role: Literal[TEST_ROLES]
    name: PageText
    value: PageText | None = None
    state: Literal[ELEMENT_STATES] | None = None
    options: list[PageText] | None = Field(default=None, max_length=MAX_SNAPSHOT_OPTIONS)

    def to_domain(self) -> SnapshotElement:
        return SnapshotElement(
            index=self.index,
            role=self.role,
            name=cut_text(self.name, maximum=MAX_TARGET_NAME_LENGTH),
            value=_page(self.value, maximum=MAX_SNAPSHOT_VALUE_LENGTH),
            state=self.state,
            options=None
            if self.options is None
            else tuple(cut_text(item, maximum=MAX_OPTION_LABEL_LENGTH) for item in self.options),
        )

    @model_validator(mode="after")
    def valid_element(self) -> ElementRequest:
        self.to_domain()
        return self


class SnapshotRequest(_Body):
    url: PageText
    title: PageText
    text: PageText
    hidden_text: PageText = ""
    elements: list[ElementRequest] = Field(max_length=MAX_SNAPSHOT_ELEMENTS)

    def to_domain(self) -> PageSnapshot:
        return PageSnapshot(
            url=cut_text(self.url, maximum=MAX_SNAPSHOT_URL_LENGTH),
            title=cut_text(self.title, maximum=MAX_SNAPSHOT_TITLE_LENGTH),
            text=cut_text(self.text, maximum=MAX_SNAPSHOT_TEXT_LENGTH),
            hidden_text=cut_text(self.hidden_text, maximum=MAX_SNAPSHOT_HIDDEN_TEXT_LENGTH),
            elements=tuple(item.to_domain() for item in self.elements),
        )

    @model_validator(mode="after")
    def valid_snapshot(self) -> SnapshotRequest:
        self.to_domain()
        return self


class EarlierRequest(PathRequest):
    blocked_step: int = Field(ge=1, le=MAX_STEPS)
    detail: PageText | None = None
    snapshot: SnapshotRequest | None = None

    def to_earlier(self) -> EarlierPath:
        return EarlierPath(
            path=self.to_domain(),
            blocked_step=self.blocked_step,
            detail=_page(self.detail, maximum=MAX_STEP_DETAIL_LENGTH),
            snapshot=None if self.snapshot is None else self.snapshot.to_domain(),
        )

    @model_validator(mode="after")
    def valid_earlier(self) -> EarlierRequest:
        self.to_earlier()
        return self


class TestPlanRequest(_Body):
    __test__ = False

    locale: str = Field(
        default="it-IT", min_length=2, max_length=MAX_LOCALE_LENGTH, pattern=LOCALE_PATTERN
    )
    application: ApplicationRequest
    snapshot: SnapshotRequest
    criteria: list[CriterionName] | None = Field(
        default=None, min_length=1, max_length=MAX_REQUESTED_CRITERIA
    )
    earlier: list[EarlierRequest] | None = Field(default=None, max_length=MAX_EARLIER_PATHS)

    @field_validator("criteria")
    @classmethod
    def upper_case(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else list(dict.fromkeys(item.upper() for item in value))

    @model_validator(mode="after")
    def distinct_earlier(self) -> TestPlanRequest:
        codes = [item.code for item in self.earlier or ()]
        if len(set(codes)) != len(codes):
            raise ValueError("the earlier paths name each path once")
        return self


class BrowserRequest(_Body):
    name: Literal[BROWSER_NAMES]
    version: str = Field(min_length=1, max_length=MAX_BROWSER_VERSION_LENGTH)

    def to_domain(self) -> BrowserInfo:
        return BrowserInfo(
            name=self.name,
            version=normalized_line(
                self.version, label="browser version", maximum=MAX_BROWSER_VERSION_LENGTH
            ),
        )

    @model_validator(mode="after")
    def valid_browser(self) -> BrowserRequest:
        self.to_domain()
        return self


class StepResultRequest(_Body):
    index: int = Field(ge=1, le=MAX_STEPS)
    status: StepStatus
    detail: PageText | None = None
    url: PageText | None = None
    title: PageText | None = None
    screenshot: str | None = Field(default=None, max_length=MAX_SCREENSHOT_PATH_LENGTH)

    def to_domain(self) -> StepResult:
        return StepResult(
            index=self.index,
            status=self.status,
            detail=_page(self.detail, maximum=MAX_STEP_DETAIL_LENGTH),
            url=_page(self.url, maximum=MAX_SNAPSHOT_URL_LENGTH),
            title=_page(self.title, maximum=MAX_SNAPSHOT_TITLE_LENGTH),
            screenshot=None if self.screenshot is None else normalize_screenshot(self.screenshot),
        )

    @model_validator(mode="after")
    def valid_step_result(self) -> StepResultRequest:
        self.to_domain()
        return self


class PathResultRequest(_Body):
    path: PathRequest
    browser: Literal[BROWSER_NAMES]
    status: PathStatus
    seconds: float = Field(ge=0, le=MAX_PATH_SECONDS, allow_inf_nan=False)
    steps: list[StepResultRequest] = Field(default_factory=list, max_length=MAX_STEPS)
    page_text: PageText | None = None

    def to_domain(self) -> PathResult:
        return PathResult(
            path=self.path.to_domain(),
            browser=self.browser,
            status=self.status,
            seconds=self.seconds,
            steps=tuple(item.to_domain() for item in self.steps),
            page_text=_page(self.page_text, maximum=MAX_PAGE_TEXT_LENGTH),
        )

    @model_validator(mode="after")
    def valid_result(self) -> PathResultRequest:
        self.to_domain()
        return self


class NotCoveredRequest(_Body):
    criterion: CriterionCode
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)

    def to_domain(self) -> NotCovered:
        return NotCovered(
            criterion=self.criterion,
            reason=normalized_line(
                self.reason, label="not covered reason", maximum=MAX_REASON_LENGTH
            ),
        )

    @model_validator(mode="after")
    def valid_not_covered(self) -> NotCoveredRequest:
        self.to_domain()
        return self


class TestRunRequest(_Body):
    __test__ = False

    plan_id: UUID
    replan_ids: list[UUID] = Field(default_factory=list, max_length=MAX_REPLANS)
    started_at: AwareDatetime
    finished_at: AwareDatetime
    application: ApplicationRequest
    browsers: list[BrowserRequest] = Field(min_length=1, max_length=MAX_BROWSERS)
    results: list[PathResultRequest] = Field(max_length=MAX_RESULTS)
    not_covered: list[NotCoveredRequest] = Field(max_length=MAX_REQUESTED_CRITERIA)

    @model_validator(mode="after")
    def consistent_run(self) -> TestRunRequest:
        if len(set(self.replan_ids)) != len(self.replan_ids) or self.plan_id in self.replan_ids:
            raise ValueError("the replans are distinct plans other than the plan of the run")
        if self.finished_at < self.started_at:
            raise ValueError("a run ends after it starts")
        names = [item.name for item in self.browsers]
        if len(set(names)) != len(names):
            raise ValueError("a run names each browser once")
        if any(item.browser not in names for item in self.results):
            raise ValueError("every result names a browser of the run")
        criteria = [item.criterion for item in self.not_covered]
        if len(set(criteria)) != len(criteria):
            raise ValueError("the not covered criteria name each criterion once")
        return self


class TestReviewRequest(_Body):
    __test__ = False

    locale: str = Field(
        default="it-IT", min_length=2, max_length=MAX_LOCALE_LENGTH, pattern=LOCALE_PATTERN
    )
    again: bool = False


class TestPlanStatus(StrEnum):
    __test__ = False

    PLANNED = "TEST_PLANNED"


class TestReviewStatus(StrEnum):
    __test__ = False

    REVIEWED = "TEST_RUN_REVIEWED"


@dataclass(frozen=True)
class TestPlanResult:
    __test__ = False

    status: TestPlanStatus
    plan: TestPlan


@dataclass(frozen=True)
class TestReviewResult:
    __test__ = False

    status: TestReviewStatus
    review: TestReview


def _refusal(status_code: int, code: str, **extra: object) -> HTTPException:
    return HTTPException(status_code, detail={"code": code, **extra})


def _invalid(error: ValueError) -> HTTPException:
    return _refusal(
        422,
        INVALID_REQUEST,
        errors=[{"loc": ["body"], "type": "value_error", "msg": str(error)}],
    )


async def _retire(role: str, code: str, reference: Mapping[str, str]) -> None:
    scope = current_proposal_evidence()
    if scope is None or scope.request is None:
        return
    await scope.event("APPLICATION_RESULT", {"status": code, **reference})
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
    rejected: str,
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
            await _retire(role, rejected, reference)
    raise RuntimeError("acceptance test generation attempts are exhausted")


def _generation_ids() -> tuple[UUID, ...]:
    scope = current_proposal_evidence()
    if scope is None:
        return ()
    identifiers = [UUID(str(item["generation_id"])) for item in scope.related_generations]
    if scope.request is not None:
        identifiers.append(scope.request.request_id)
    return tuple(dict.fromkeys(identifiers))


def _findings_by_twin(run: TestRun | None) -> dict[UUID, tuple[str, ...]]:
    if run is None or run.review is None:
        return {}
    return {
        critique.twin_id: tuple(item.text for item in critique.findings)
        for critique in run.review.critiques
    }


def _latest_review(run: TestRun) -> dict[str, object]:
    snapshot = run.to_snapshot()
    return {
        "run_id": snapshot["id"],
        "finished_at": snapshot["finished_at"],
        "reviewed_at": snapshot["reviewed_at"],
        "critiques": snapshot["critiques"],
    }


def _requested(requirements, criteria: Sequence[str] | None) -> tuple[str, ...]:
    codes = tuple(item.code for item in requirements.specification.acceptance_criteria)
    if criteria is None:
        return codes
    wanted = tuple(dict.fromkeys(criteria))
    unknown = [code for code in wanted if code not in codes]
    if unknown:
        raise _refusal(422, ACCEPTANCE_CRITERION_UNKNOWN, codes=unknown)
    return tuple(code for code in codes if code in wanted)


class AcceptanceTestApplication:
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
        return SqlAlchemyAcceptanceTestRepository(session, owner_user_id=owner_user_id)

    def plan_available(self) -> bool:
        return (
            getattr(self.runtime, "real_model_runtime", None) is not None
            and self._proposal_evidence_store is not None
        )

    def _generator(self):
        if not self.plan_available():
            raise _refusal(503, TEST_MODEL_NOT_CONFIGURED)
        return self.runtime.real_model_runtime.user_modeling.proposal_port.generator

    @staticmethod
    async def _owned(repository, project_id: UUID) -> None:
        if not await repository.project_exists(project_id):
            raise _refusal(404, PROJECT_NOT_FOUND)

    @staticmethod
    async def _run(repository, project_id: UUID, run_id: UUID) -> TestRun:
        run = await repository.run(project_id, run_id)
        if run is None:
            raise _refusal(404, TEST_RUN_NOT_FOUND)
        return run

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

    async def _twins(self, owner_user_id: UUID, project_id: UUID) -> tuple[object, ...]:
        services = self._service("user_modeling_services", "USER_MODELING_UNAVAILABLE")
        scope = {"owner_user_id": owner_user_id, "project_id": project_id}
        snapshot = await services.queries.current_snapshot(**scope)
        gate = await services.gates.current_gate(**scope)
        if snapshot is None or not user_modeling_gate_is_currently_approved(gate, snapshot):
            raise _refusal(409, USER_MODELING_APPROVAL_REQUIRED)
        twins = tuple(snapshot.snapshot.twin_versions)
        if not twins:
            raise _refusal(409, USER_MODELING_APPROVAL_REQUIRED)
        return twins

    async def _material(
        self, owner_user_id: UUID, project_id: UUID, reference: ChangeReference, locale: str
    ) -> dict[str, object]:
        version = await self._service("project_service", "PROJECT_QUERY_UNAVAILABLE").current_brief(
            project_id=project_id, owner_user_id=owner_user_id
        )
        if version is None:
            raise _refusal(404, PROJECT_NOT_FOUND)
        try:
            return acceptance_material(
                brief=version.brief,
                requirements=reference.requirements,
                design=reference.design,
                language=locale.split("-")[0],
            )
        except DesignEvaluationError as error:
            raise _refusal(409, error.code) from error

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
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            plans, runs = await repository.counts(project_id)
            latest = await repository.runs(project_id, limit=1)
            reviewed = await repository.latest_reviewed_run(project_id)
        reference = await self.reference(owner_user_id=owner_user_id, project_id=project_id)
        latest_run = latest[0] if latest else None
        return {
            "project_id": str(project_id),
            "reference": reference.to_snapshot(),
            "plan_available": self.plan_available(),
            "plans": plans,
            "runs": runs,
            "latest_run": None if latest_run is None else latest_run.to_snapshot(),
            "latest_run_stale": latest_run is not None
            and review_is_stale(latest_run.reference_snapshot(), reference.current_versions()),
            "latest_review": None if reviewed is None else _latest_review(reviewed),
        }

    @evidence_application
    async def plan(self, *, owner_user_id: UUID, project_id: UUID, body) -> TestPlanResult:
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            first_number = await repository.next_path_number(project_id) if body.earlier else 1
        reference = await self._approved(owner_user_id, project_id)
        generator = self._generator()
        codes = _requested(reference.requirements, body.criteria)
        material = await self._material(owner_user_id, project_id, reference, body.locale)
        plan_id = uuid4()
        application = body.application.to_domain()
        snapshot = body.snapshot.to_domain()
        earlier = tuple(item.to_earlier() for item in body.earlier or ())
        context = plan_context(
            project_id=project_id,
            locale=body.locale,
            material=material,
            application=application,
            snapshot=snapshot,
            earlier=earlier,
            criteria_codes=codes,
        )
        paths, not_covered = await _attempt(
            partial(plan_tests, generator, context),
            partial(bind_plan, context=context, locale=body.locale, first_number=first_number),
            role=PLANNER_ROLE,
            rejected=PLAN_REJECTED,
            reference={"test_plan_id": str(plan_id)},
        )
        generation_ids = _generation_ids()
        requirements_version, design_version = reference.version_numbers
        plan = TestPlan(
            id=plan_id,
            project_id=project_id,
            owner_user_id=owner_user_id,
            created_at=datetime.now(UTC),
            locale=body.locale,
            requirements_version_number=requirements_version,
            design_version_number=design_version,
            alternative_code=reference.alternative_code,
            application=application,
            criteria=codes,
            paths=paths,
            not_covered=not_covered,
            replan_of=tuple(item.path.code for item in earlier),
            snapshot_summary=snapshot.summary(),
            generation_ids=generation_ids,
            cost_microusd=await self._cost(owner_user_id, project_id, generation_ids),
        )
        await _accept(PLAN_PURPOSE, plan.to_snapshot())
        async with sessions() as session, session.begin():
            status = await self._repository(session, owner_user_id).create_plan(plan)
        if status is not AcceptanceTestWriteStatus.RECORDED:
            raise _refusal(404, PROJECT_NOT_FOUND)
        return TestPlanResult(status=TestPlanStatus.PLANNED, plan=plan)

    async def plans(self, *, owner_user_id: UUID, project_id: UUID) -> tuple[TestPlan, ...]:
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            return await repository.plans(project_id)

    async def plan_of(self, *, owner_user_id: UUID, project_id: UUID, plan_id: UUID) -> TestPlan:
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            plan = await repository.plan(project_id, plan_id)
        if plan is None:
            raise _refusal(404, TEST_PLAN_NOT_FOUND)
        return plan

    async def record(self, *, owner_user_id: UUID, project_id: UUID, body) -> TestRun:
        sessions = self._sessions()
        async with sessions() as session, session.begin():
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            plans = []
            for plan_id in (body.plan_id, *body.replan_ids):
                plan = await repository.plan(project_id, plan_id)
                if plan is None:
                    raise _refusal(404, TEST_PLAN_NOT_FOUND)
                plans.append(plan)
            try:
                run = build_test_run(
                    run_id=uuid4(),
                    plans=plans,
                    started_at=body.started_at,
                    finished_at=body.finished_at,
                    recorded_at=datetime.now(UTC),
                    application=body.application.to_domain(),
                    browsers=[item.to_domain() for item in body.browsers],
                    results=[item.to_domain() for item in body.results],
                    not_covered=[item.to_domain() for item in body.not_covered],
                )
            except ValueError as error:
                raise _invalid(error) from error
            try:
                status = await repository.create_run(run)
            except TestPlanUnknown as error:
                raise _refusal(404, TEST_PLAN_NOT_FOUND) from error
        if status is not AcceptanceTestWriteStatus.RECORDED:
            raise _refusal(404, PROJECT_NOT_FOUND)
        return run

    async def runs(self, *, owner_user_id: UUID, project_id: UUID) -> tuple[TestRun, ...]:
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            return await repository.runs(project_id)

    async def run_of(self, *, owner_user_id: UUID, project_id: UUID, run_id: UUID) -> TestRun:
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            return await self._run(repository, project_id, run_id)

    @evidence_application
    async def review(
        self, *, owner_user_id: UUID, project_id: UUID, run_id: UUID, body
    ) -> TestReviewResult:
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            run = await self._run(repository, project_id, run_id)
            if not body.again and await repository.latest_review(run.id) is not None:
                raise _refusal(409, TEST_REVIEW_EXISTS)
            earlier = await repository.latest_reviewed_run(project_id, before=run)
            learned = await SqlAlchemyTwinLearningRepository(
                session, owner_user_id=owner_user_id
            ).active(project_id)
        reference = await self._approved(owner_user_id, project_id)
        twins = await self._twins(owner_user_id, project_id)
        generator = self._generator()
        material = await self._material(owner_user_id, project_id, reference, body.locale)
        review_id = uuid4()
        bounded = run_material(run.to_snapshot())
        earlier_findings = _findings_by_twin(earlier)
        identifiers = {"test_run_id": str(run.id), "test_review_id": str(review_id)}
        critiques = []
        for position, twin in enumerate(twins, 1):
            context = critique_context(
                project_id=project_id,
                locale=body.locale,
                twin=twin,
                material=material,
                run_material=bounded,
                earlier_findings=earlier_findings.get(twin.twin_id, ()),
                learned=learned_view(learned.get(twin.twin_id, ())),
            )
            critique = await _attempt(
                partial(critique_run, generator, context),
                partial(bind_test_critique, twin=twin, context=context),
                role=CRITIQUE_ROLE,
                rejected=CRITIQUE_REJECTED,
                reference=identifiers,
            )
            await _accept(REVIEW_PURPOSE, critique.to_snapshot())
            if position < len(twins):
                await _retire(CRITIQUE_ROLE, TWIN_CRITIQUED, identifiers)
            critiques.append(critique)
        generation_ids = _generation_ids()
        review = TestReview(
            id=review_id,
            run_id=run.id,
            project_id=project_id,
            owner_user_id=owner_user_id,
            reviewed_at=datetime.now(UTC),
            locale=body.locale,
            critiques=tuple(critiques),
            generation_ids=generation_ids,
            cost_microusd=await self._cost(owner_user_id, project_id, generation_ids),
        )
        async with sessions() as session, session.begin():
            status = await self._repository(session, owner_user_id).create_review(review)
        if status is AcceptanceTestWriteStatus.PROJECT_NOT_FOUND:
            raise _refusal(404, PROJECT_NOT_FOUND)
        if status is not AcceptanceTestWriteStatus.RECORDED:
            raise _refusal(404, TEST_RUN_NOT_FOUND)
        return TestReviewResult(status=TestReviewStatus.REVIEWED, review=review)

    async def reviews(
        self, *, owner_user_id: UUID, project_id: UUID, run_id: UUID
    ) -> tuple[TestReview, ...]:
        sessions = self._sessions()
        async with sessions() as session:
            repository = self._repository(session, owner_user_id)
            await self._owned(repository, project_id)
            run = await self._run(repository, project_id, run_id)
            return await repository.reviews(run.id)


def create_acceptance_test_router() -> APIRouter:
    router = APIRouter(prefix=ACCEPTANCE_TESTS_API_PREFIX, tags=["acceptance-tests"])

    def application(request: Request) -> AcceptanceTestApplication:
        return AcceptanceTestApplication(request.app.state.application_runtime)

    @router.get("/acceptance-tests")
    async def overview(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        return await application(request).overview(owner_user_id=user.id, project_id=project_id)

    @router.post("/test-plans", status_code=201)
    async def plan(
        project_id: UUID,
        body: TestPlanRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        async def planning():
            result = await application(request).plan(
                owner_user_id=user.id, project_id=project_id, body=body
            )
            return {"status": PLANNED, "plan": result.plan.to_snapshot()}

        return await generation_request(
            request,
            GenerationOperation.TEST_PLAN,
            planning,
            owner_user_id=user.id,
            project_id=project_id,
            body=body,
        )

    @router.get("/test-plans")
    async def plans(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        items = await application(request).plans(owner_user_id=user.id, project_id=project_id)
        return {"items": [item.to_snapshot() for item in items]}

    @router.get("/test-plans/{plan_id}")
    async def plan_of(
        project_id: UUID,
        plan_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        item = await application(request).plan_of(
            owner_user_id=user.id, project_id=project_id, plan_id=plan_id
        )
        return item.to_snapshot()

    @router.post("/test-runs", status_code=201)
    async def record(
        project_id: UUID,
        body: TestRunRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        run = await application(request).record(
            owner_user_id=user.id, project_id=project_id, body=body
        )
        return {"status": RECORDED, "run": run.to_snapshot()}

    @router.get("/test-runs")
    async def runs(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        items = await application(request).runs(owner_user_id=user.id, project_id=project_id)
        return {"items": [item.to_snapshot() for item in items]}

    @router.get("/test-runs/{run_id}")
    async def run_of(
        project_id: UUID,
        run_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        item = await application(request).run_of(
            owner_user_id=user.id, project_id=project_id, run_id=run_id
        )
        return item.to_snapshot()

    @router.post("/test-runs/{run_id}/reviews", status_code=201)
    async def review(
        project_id: UUID,
        run_id: UUID,
        body: TestReviewRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        async def reviewing():
            result = await application(request).review(
                owner_user_id=user.id, project_id=project_id, run_id=run_id, body=body
            )
            return {"status": REVIEWED, "review": result.review.to_snapshot()}

        return await generation_request(
            request,
            GenerationOperation.TEST_REVIEW,
            reviewing,
            owner_user_id=user.id,
            project_id=project_id,
            body=body,
        )

    @router.get("/test-runs/{run_id}/reviews")
    async def reviews(
        project_id: UUID,
        run_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        items = await application(request).reviews(
            owner_user_id=user.id, project_id=project_id, run_id=run_id
        )
        return {"items": [item.to_snapshot() for item in items]}

    return router


__all__ = [
    "ACCEPTANCE_CRITERION_UNKNOWN",
    "ACCEPTANCE_TESTS_API_PREFIX",
    "CRITERION_REQUEST_PATTERN",
    "CRITIQUE_REJECTED",
    "CRITIQUE_ROLE",
    "DESIGN_APPROVAL_REQUIRED",
    "INVALID_REQUEST",
    "MAX_CRITERION_REQUEST_LENGTH",
    "MAX_RAW_TEXT_LENGTH",
    "PLANNED",
    "PLANNER_ROLE",
    "PLAN_REJECTED",
    "PROJECT_NOT_FOUND",
    "RECORDED",
    "REQUIREMENTS_APPROVAL_REQUIRED",
    "REVIEWED",
    "TEST_MODEL_NOT_CONFIGURED",
    "TEST_PLAN_NOT_FOUND",
    "TEST_REVIEW_EXISTS",
    "TEST_RUN_NOT_FOUND",
    "TWIN_CRITIQUED",
    "USER_MODELING_APPROVAL_REQUIRED",
    "AcceptanceTestApplication",
    "ApplicationRequest",
    "BrowserRequest",
    "EarlierRequest",
    "ElementRequest",
    "ExpectationRequest",
    "NotCoveredRequest",
    "PathRequest",
    "PathResultRequest",
    "SnapshotRequest",
    "StepRequest",
    "StepResultRequest",
    "TargetRequest",
    "TestPlanRequest",
    "TestPlanResult",
    "TestPlanStatus",
    "TestReviewRequest",
    "TestReviewResult",
    "TestReviewStatus",
    "TestRunRequest",
    "create_acceptance_test_router",
]
