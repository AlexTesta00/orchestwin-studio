from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import Field

from orchestwin.knowledge.layout import KNOWLEDGE_SCHEMA_VERSION
from orchestwin.knowledge.schema_models.base import (
    Timestamp,
    Uuid,
    _AlternativeCode,
    _code,
    _Count,
    _CriterionCode,
    _Record,
    _RequirementCode,
    _ScreenCode,
    _Summary,
    _Version,
)
from orchestwin.knowledge.state import (
    APPLICATION_KINDS,
    BROWSER_NAMES,
    CRITERION_STATUSES,
    CRITIQUE_VERDICTS,
    MAX_ACTION_LENGTH,
    MAX_ADDRESS_LENGTH,
    MAX_BROWSER_VERSION_LENGTH,
    MAX_BROWSERS,
    MAX_CRITERIA_PER_PATH,
    MAX_EXPECTED_TEXT_LENGTH,
    MAX_FINDING_LENGTH,
    MAX_FINDINGS,
    MAX_FOLDER_TEST_RUNS,
    MAX_PAGE_TEXT_LENGTH,
    MAX_PATH_HEADING_LENGTH,
    MAX_REASON_LENGTH,
    MAX_RESULTS,
    MAX_SCREENSHOT_PATH_LENGTH,
    MAX_STEP_DETAIL_LENGTH,
    MAX_STEP_VALUE_LENGTH,
    MAX_STEPS,
    MAX_TARGET_NAME_LENGTH,
    PATH_STATUSES,
    SEVERITIES,
    STEP_STATUSES,
    TEST_ACTIONS,
    TEST_EXPECTATIONS,
    TEST_REVIEWS_KIND,
    TEST_ROLES,
)

_SCREENSHOT_SEGMENT: Final = r"(?:[^/\\:.][^/\\:]*|\.|\.[^/\\:.][^/\\:]*|\.\.[^/\\:]+)"
_SCREENSHOT_PATTERN: Final = rf"^{_SCREENSHOT_SEGMENT}(?:/{_SCREENSHOT_SEGMENT})*$"

_PathCode = Annotated[str, Field(pattern=_code("TP"))]


class ApplicationUnderTest(_Record):
    kind: Literal[APPLICATION_KINDS] = Field(
        description=(
            "URL for an address, STATIC for a folder served on the computer that ran the tests."
        )
    )
    address: Annotated[str, Field(min_length=1, max_length=MAX_ADDRESS_LENGTH)] = Field(
        description=(
            "The address, or the folder relative to the project root with / separators, or only "
            "its name when it is outside the project."
        )
    )


class RunBrowser(_Record):
    name: Literal[BROWSER_NAMES] = Field(
        description="chrome for Chrome, Chromium or Edge; firefox for Firefox."
    )
    version: Annotated[str, Field(min_length=1, max_length=MAX_BROWSER_VERSION_LENGTH)] = Field(
        description="Version of the browser that ran the paths."
    )


class VerifiedVersions(_Record):
    requirements_version_number: _Version = Field(
        description="Approved requirements version whose acceptance criteria were verified."
    )
    design_version_number: _Version = Field(
        description="Approved design version the application was verified against."
    )
    alternative_code: _AlternativeCode | None = Field(
        description="Code of the selected design alternative, like DES-002, or null."
    )


class CriteriaSummary(_Record):
    passed: _Count = Field(description="Number of criteria whose every result passed.")
    failed: _Count = Field(description="Number of criteria with at least one failed result.")
    blocked: _Count = Field(
        description="Number of criteria with a blocked result and no failed one."
    )
    not_covered: _Count = Field(description="Number of criteria that no path verifies.")
    not_run: _Count = Field(description="Number of criteria that the run did not verify.")


class CriterionOutcome(_Record):
    code: _CriterionCode = Field(description="Code of the acceptance criterion, like AC-001.")
    status: Literal[CRITERION_STATUSES] = Field(
        description="Outcome of the criterion computed from every result that names it."
    )
    paths: list[_PathCode] = Field(description="Codes of the paths that name the criterion.")


class UncoveredCriterion(_Record):
    criterion: _CriterionCode = Field(description="Code of the criterion that no path verifies.")
    reason: Annotated[str, Field(max_length=MAX_REASON_LENGTH)] = Field(
        description="Why no path verifies it, for example because a person has to judge it."
    )


class StepTarget(_Record):
    role: Literal[TEST_ROLES] | None = Field(
        description="Role of the element as a person perceives it, like button, or null for any."
    )
    name: Annotated[str, Field(min_length=1, max_length=MAX_TARGET_NAME_LENGTH)] = Field(
        description="Name or visible text of the element."
    )


class StepExpectation(_Record):
    kind: Literal[TEST_EXPECTATIONS] = Field(
        description="What is checked on the page after the action."
    )
    target: StepTarget | None = Field(
        description="Element the expectation is about, or null when it is about a text."
    )
    text: Annotated[str, Field(max_length=MAX_EXPECTED_TEXT_LENGTH)] | None = Field(
        description="Expected text, value, part of the address or part of the title, or null."
    )


class PathStep(_Record):
    action: Literal[TEST_ACTIONS] = Field(
        description="What a person does: open a page, click, type, select, press a key or check."
    )
    target: StepTarget | None = Field(
        description="Element the action is done on, or null for an action without one."
    )
    value: Annotated[str, Field(max_length=MAX_STEP_VALUE_LENGTH)] | None = Field(
        description="Page to open, text to type, option to select or key to press, or null."
    )
    expect: StepExpectation | None = Field(
        description="What must be true after the action, or null."
    )


class AcceptancePath(_Record):
    code: _PathCode = Field(description="Code of the path inside its plan, like TP-001.")
    heading: Annotated[str, Field(max_length=MAX_PATH_HEADING_LENGTH)] = Field(
        description="What the path verifies, in words."
    )
    criteria: list[_CriterionCode] = Field(
        min_length=1,
        max_length=MAX_CRITERIA_PER_PATH,
        description="Codes of the acceptance criteria the path verifies.",
    )
    steps: list[PathStep] = Field(
        min_length=1,
        max_length=MAX_STEPS,
        description="Steps of the path, described by what a person sees; the first one opens.",
    )


class StepOutcome(_Record):
    index: Annotated[int, Field(ge=1, le=MAX_STEPS)] = Field(
        description="Position of the step in its path, starting at 1."
    )
    status: Literal[STEP_STATUSES] = Field(
        description="DONE, FAILED, BLOCKED, or SKIPPED after a failed or blocked step."
    )
    detail: Annotated[str, Field(max_length=MAX_STEP_DETAIL_LENGTH)] | None = Field(
        description="Why the step failed or was blocked, or null."
    )
    url: str | None = Field(description="Address of the page after the step, or null.")
    title: str | None = Field(description="Title of the page after the step, or null.")
    screenshot: (
        Annotated[str, Field(max_length=MAX_SCREENSHOT_PATH_LENGTH, pattern=_SCREENSHOT_PATTERN)]
        | None
    ) = Field(
        description=(
            "Path of the screenshot taken after the step, relative to the folder of the run on "
            "the computer that ran it, or null; screenshots are never copied into this folder."
        )
    )


class PathResult(_Record):
    path: AcceptancePath = Field(description="The path that was run.")
    browser: Literal[BROWSER_NAMES] = Field(description="Browser the path ran in.")
    status: Literal[PATH_STATUSES] = Field(description="Outcome of the path in that browser.")
    seconds: Annotated[float, Field(ge=0)] = Field(description="How long the path took.")
    steps: list[StepOutcome] = Field(
        max_length=MAX_STEPS, description="Outcome of every step, in the order of the path."
    )
    page_text: Annotated[str, Field(max_length=MAX_PAGE_TEXT_LENGTH)] | None = Field(
        description="Visible text of the page at the end of the path, or null."
    )


class CriterionSubject(_Record):
    criterion: _CriterionCode | None = Field(
        description="Code of the acceptance criterion the finding is about, or null."
    )
    requirement: _RequirementCode | None = Field(
        description="Code of the requirement the finding is about, or null."
    )
    screen: _ScreenCode | None = Field(
        description="Code of the screen the finding is about, or null."
    )


class AcceptanceFinding(_Record):
    severity: Literal[SEVERITIES] = Field(description="How much the finding matters to the twin.")
    text: str = Field(max_length=MAX_FINDING_LENGTH, description="What the twin found.")
    about: CriterionSubject = Field(
        description="Criterion, requirement and screen the finding is about."
    )
    action: Annotated[str, Field(max_length=MAX_ACTION_LENGTH)] | None = Field(
        description="What the twin suggests doing, or null."
    )


class AcceptanceCritique(_Record):
    twin_id: Uuid = Field(description="User twin that criticized the run.")
    twin_name: str = Field(min_length=1, description="Display name of that user twin.")
    verdict: Literal[CRITIQUE_VERDICTS] = Field(
        description="Whether the results are fine for the twin, worry it or depart from the design."
    )
    summary: _Summary = Field(description="Critique of the twin, in the language of the project.")
    findings: list[AcceptanceFinding] = Field(
        max_length=MAX_FINDINGS, description="Findings of the twin, most important first."
    )


class AcceptanceRun(_Record):
    id: Uuid = Field(description="Identifier of the run.")
    started_at: Timestamp = Field(description="When the run started.")
    finished_at: Timestamp = Field(description="When the run finished.")
    recorded_at: Timestamp = Field(description="When the Studio recorded the run.")
    application: ApplicationUnderTest = Field(description="Application the paths ran on.")
    browsers: list[RunBrowser] = Field(
        min_length=1, max_length=MAX_BROWSERS, description="Browsers the paths ran in."
    )
    reference: VerifiedVersions = Field(
        description="Approved versions whose acceptance criteria were verified."
    )
    summary: CriteriaSummary = Field(description="Number of criteria for every outcome.")
    criteria: list[CriterionOutcome] = Field(
        description="Outcome of every criterion of the approved requirements."
    )
    not_covered: list[UncoveredCriterion] = Field(
        description="Criteria that the plan could not turn into a path, with the reason."
    )
    results: list[PathResult] = Field(
        max_length=MAX_RESULTS, description="Outcome of every path in every browser."
    )
    critiques: list[AcceptanceCritique] = Field(
        description="Latest review of the run, one critique for every approved twin, or empty."
    )
    reviewed_at: Timestamp | None = Field(
        description="When the latest review completed, or null before any review."
    )
    cost_microusd: _Count = Field(
        description="Cost of the plans of the run and of its latest review, in microdollars."
    )


class TestReviewsDocument(_Record):
    schema_version: Literal[KNOWLEDGE_SCHEMA_VERSION] = Field(
        description="Version of the knowledge folder format."
    )
    kind: Literal[TEST_REVIEWS_KIND] = Field(
        description="Kind of document, the acceptance tests and the twin critiques on them."
    )
    project_id: Uuid = Field(description="Project the runs belong to.")
    runs: list[AcceptanceRun] = Field(
        max_length=MAX_FOLDER_TEST_RUNS, description="Runs of the acceptance tests, newest first."
    )
