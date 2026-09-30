from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final
from urllib.parse import urlsplit
from uuid import UUID

from orchestwin.knowledge.state import (
    BROWSER_NAMES,
    INTERACTIVE_ROLES,
    MAX_ACTION_LENGTH,
    MAX_ADDRESS_LENGTH,
    MAX_BROWSER_VERSION_LENGTH,
    MAX_BROWSERS,
    MAX_CRITERIA_PER_PATH,
    MAX_EARLIER_PATHS,
    MAX_EXPECTED_TEXT_LENGTH,
    MAX_FINDING_LENGTH,
    MAX_FINDINGS,
    MAX_PAGE_TEXT_LENGTH,
    MAX_PATH_HEADING_LENGTH,
    MAX_PATHS,
    MAX_REASON_LENGTH,
    MAX_RESULTS,
    MAX_SCREENSHOT_PATH_LENGTH,
    MAX_SNAPSHOT_ELEMENTS,
    MAX_SNAPSHOT_OPTIONS,
    MAX_SNAPSHOT_TEXT_LENGTH,
    MAX_STEP_DETAIL_LENGTH,
    MAX_STEP_VALUE_LENGTH,
    MAX_STEPS,
    MAX_SUMMARY_LENGTH,
    MAX_TARGET_NAME_LENGTH,
    TEST_KEYS,
    TEST_ROLES,
)
from orchestwin.projects.code_changes import (
    LOCALE_PATTERN,
    MAX_LOCALE_LENGTH,
    MAX_TWIN_NAME_LENGTH,
    CritiqueVerdict,
    FindingSeverity,
    normalized_line,
)
from orchestwin.twins.limits import MAX_USER_TWINS

PATH_CODE_PREFIX: Final = "TP"
PATH_CODE_PATTERN: Final = r"^TP-[0-9]{3,6}$"
CRITERION_CODE_PATTERN: Final = r"^AC-[0-9]{3,6}$"
MAX_PATH_NUMBER: Final = 999_999
MAX_SNAPSHOT_URL_LENGTH: Final = 2000
MAX_SNAPSHOT_TITLE_LENGTH: Final = 300
MAX_SNAPSHOT_VALUE_LENGTH: Final = 1000
MAX_OPTION_LABEL_LENGTH: Final = MAX_TARGET_NAME_LENGTH
MAX_PATH_SECONDS: Final = 86_400
MAX_REPLANS: Final = 5
MAX_REQUESTED_CRITERIA: Final = 200
ELEMENT_STATES: Final = ("checked", "disabled")
CLICKABLE_ROLES: Final = (*INTERACTIVE_ROLES, "text", "image", "listitem", "cell", "heading")
TYPING_ROLES: Final = ("textbox", "spinbutton", "combobox", "slider")
SELECTING_ROLES: Final = ("combobox",)
CUT_MARK: Final = "…"
_PATH_CODE: Final = re.compile(PATH_CODE_PATTERN)
_CRITERION_CODE: Final = re.compile(CRITERION_CODE_PATTERN)
_REQUIREMENT_CODE: Final = re.compile(r"^REQ-[0-9]{3,6}$")
_SCREEN_CODE: Final = re.compile(r"^SCR-[0-9]{3,6}$")
_ALTERNATIVE_CODE: Final = re.compile(r"^DES-[0-9]{3,6}$")
_LOCALE: Final = re.compile(LOCALE_PATTERN)


class ApplicationKind(StrEnum):
    URL = "URL"
    STATIC = "STATIC"


class StepAction(StrEnum):
    OPEN = "OPEN"
    CLICK = "CLICK"
    TYPE = "TYPE"
    SELECT = "SELECT"
    PRESS = "PRESS"
    CHECK = "CHECK"


class ExpectationKind(StrEnum):
    TEXT_VISIBLE = "TEXT_VISIBLE"
    TEXT_ABSENT = "TEXT_ABSENT"
    ELEMENT_VISIBLE = "ELEMENT_VISIBLE"
    ELEMENT_ABSENT = "ELEMENT_ABSENT"
    VALUE_IS = "VALUE_IS"
    URL_CONTAINS = "URL_CONTAINS"
    TITLE_CONTAINS = "TITLE_CONTAINS"


class PathStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    NOT_RUN = "NOT_RUN"


class StepStatus(StrEnum):
    DONE = "DONE"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


class CriterionStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    NOT_COVERED = "NOT_COVERED"
    NOT_RUN = "NOT_RUN"


TARGET_ACTIONS: Final = frozenset({StepAction.CLICK, StepAction.TYPE, StepAction.SELECT})
VALUE_ACTIONS: Final = frozenset(
    {StepAction.OPEN, StepAction.TYPE, StepAction.SELECT, StepAction.PRESS}
)
ACTION_ROLES: Final = {
    StepAction.CLICK: CLICKABLE_ROLES,
    StepAction.TYPE: TYPING_ROLES,
    StepAction.SELECT: SELECTING_ROLES,
}
TARGET_EXPECTATIONS: Final = frozenset(
    {ExpectationKind.ELEMENT_VISIBLE, ExpectationKind.ELEMENT_ABSENT, ExpectationKind.VALUE_IS}
)
TEXT_EXPECTATIONS: Final = frozenset(
    {
        ExpectationKind.TEXT_VISIBLE,
        ExpectationKind.TEXT_ABSENT,
        ExpectationKind.VALUE_IS,
        ExpectationKind.URL_CONTAINS,
        ExpectationKind.TITLE_CONTAINS,
    }
)


class TestPlanUnknown(LookupError):
    __test__ = False

    def __init__(self, plan_id: UUID) -> None:
        super().__init__(str(plan_id))
        self.plan_id = plan_id


def _aware(value: object, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be a timezone-aware timestamp")


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _uuid(value: object, label: str) -> None:
    if not isinstance(value, UUID):
        raise ValueError(f"{label} must be a UUID")


def _uuids(values: object, label: str, *, maximum: int | None = None) -> None:
    if not isinstance(values, tuple) or not all(isinstance(item, UUID) for item in values):
        raise ValueError(f"{label} must be a tuple of UUID")
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must not repeat")
    if maximum is not None and len(values) > maximum:
        raise ValueError(f"{label} hold at most {maximum} items")


def _count(value: object, label: str, *, minimum: int = 0, maximum: int | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer of at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be at most {maximum}")


def _control_free(value: str) -> bool:
    return all(ord(character) >= 32 and ord(character) != 127 for character in value)


def _code(value: object, pattern: re.Pattern[str], label: str) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{label} holds an invalid code")


def _codes(
    values: object,
    pattern: re.Pattern[str],
    label: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{label} must be a tuple")
    for value in values:
        _code(value, pattern, label)
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must not repeat a code")
    if len(values) < minimum or (maximum is not None and len(values) > maximum):
        raise ValueError(f"{label} hold between {minimum} and {maximum} codes")


def _normalized(value: object, *, label: str, maximum: int) -> None:
    if normalized_line(value, label=label, maximum=maximum) != value:
        raise ValueError(f"{label} must be normalized")


def _optional_normalized(value: object, *, label: str, maximum: int) -> None:
    if value is not None:
        _normalized(value, label=label, maximum=maximum)


def _bounded(value: object, *, label: str, maximum: int) -> None:
    if not isinstance(value, str) or cut_text(value, maximum=maximum, label=label) != value:
        raise ValueError(f"{label} must be a collapsed text of at most {maximum} characters")


def _optional_bounded(value: object, *, label: str, maximum: int) -> None:
    if value is not None:
        _bounded(value, label=label, maximum=maximum)


def _locale(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) > MAX_LOCALE_LENGTH
        or _LOCALE.fullmatch(value) is None
    ):
        raise ValueError("locale must be a language tag such as it-IT")


def _tuple_of(values: object, kind: type, label: str) -> None:
    if not isinstance(values, tuple) or not all(isinstance(item, kind) for item in values):
        raise ValueError(f"{label} must be a tuple of {kind.__name__}")


def cut_text(value: object, *, maximum: int, label: str = "text") -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a text")
    kept = "".join(
        character
        for character in value
        if character.isspace() or (ord(character) >= 32 and ord(character) != 127)
    )
    text = " ".join(kept.split())
    if len(text) <= maximum:
        return text
    return text[: maximum - len(CUT_MARK)].rstrip() + CUT_MARK


def normalize_address(kind: ApplicationKind, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("application address must be a text")
    address = value.strip()
    if not address:
        raise ValueError("application address must not be empty")
    if len(address) > MAX_ADDRESS_LENGTH:
        raise ValueError(f"application address exceeds {MAX_ADDRESS_LENGTH} characters")
    if not _control_free(address):
        raise ValueError("application address must not contain control characters")
    if ApplicationKind(kind) is ApplicationKind.URL:
        if any(character.isspace() for character in address):
            raise ValueError("an application address must not contain spaces")
        try:
            parts = urlsplit(address)
            host = parts.hostname
        except ValueError as error:
            raise ValueError("an application address must be an http or https address") from error
        if parts.scheme.lower() not in ("http", "https") or not host:
            raise ValueError("an application address must be an http or https address")
        return address
    if "\\" in address or ":" in address:
        raise ValueError("a static folder is relative and uses / as separator")
    if address != "." and any(part in ("", ".", "..") for part in address.split("/")):
        raise ValueError("a static folder is relative to the project and never leaves it")
    return address


def normalize_screenshot(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("screenshot path must not be empty")
    if len(value) > MAX_SCREENSHOT_PATH_LENGTH:
        raise ValueError(f"screenshot path exceeds {MAX_SCREENSHOT_PATH_LENGTH} characters")
    if not _control_free(value) or "\\" in value or ":" in value:
        raise ValueError("screenshot path is relative and uses / as separator")
    if any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("screenshot path stays inside the run folder")
    return value


def path_code(number: int) -> str:
    _count(number, "path number", minimum=1, maximum=MAX_PATH_NUMBER)
    return f"{PATH_CODE_PREFIX}-{number:03d}"


def path_number(code: object) -> int:
    _code(code, _PATH_CODE, "path code")
    return int(str(code).split("-", 1)[1])


def _open_value(value: str) -> None:
    try:
        parts = urlsplit(value)
    except ValueError as error:
        raise ValueError("an OPEN step opens a path of the application") from error
    scheme = parts.scheme.lower()
    if scheme and (scheme not in ("http", "https") or not parts.netloc):
        raise ValueError("an OPEN step opens a path of the application or an http address")


@dataclass(frozen=True, slots=True)
class TestApplication:
    __test__ = False

    kind: ApplicationKind
    address: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ApplicationKind):
            raise ValueError("application kind must be an ApplicationKind")
        if normalize_address(self.kind, self.address) != self.address:
            raise ValueError("application address must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        return {"kind": self.kind.value, "address": self.address}


def application_from_snapshot(payload: Mapping[str, object]) -> TestApplication:
    return TestApplication(kind=ApplicationKind(str(payload["kind"])), address=payload["address"])


@dataclass(frozen=True, slots=True)
class SnapshotElement:
    index: int
    role: str
    name: str
    value: str | None = None
    state: str | None = None
    options: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        _count(self.index, "element index")
        if self.role not in TEST_ROLES:
            raise ValueError("element role must be one of the test roles")
        _bounded(self.name, label="element name", maximum=MAX_TARGET_NAME_LENGTH)
        _optional_bounded(self.value, label="element value", maximum=MAX_SNAPSHOT_VALUE_LENGTH)
        if self.state is not None and self.state not in ELEMENT_STATES:
            raise ValueError("element state must be checked, disabled or null")
        if self.options is None:
            return
        if self.role != "combobox":
            raise ValueError("only a combobox lists its options")
        if not isinstance(self.options, tuple) or len(self.options) > MAX_SNAPSHOT_OPTIONS:
            raise ValueError(f"a combobox lists at most {MAX_SNAPSHOT_OPTIONS} options")
        for option in self.options:
            _bounded(option, label="option label", maximum=MAX_OPTION_LABEL_LENGTH)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "index": self.index,
            "role": self.role,
            "name": self.name,
            "value": self.value,
            "state": self.state,
            "options": None if self.options is None else list(self.options),
        }


def element_from_snapshot(payload: Mapping[str, object]) -> SnapshotElement:
    options = payload["options"]
    return SnapshotElement(
        index=payload["index"],
        role=payload["role"],
        name=payload["name"],
        value=payload["value"],
        state=payload["state"],
        options=None if options is None else tuple(options),
    )


@dataclass(frozen=True, slots=True)
class SnapshotSummary:
    url: str
    title: str
    elements: int
    text_length: int

    def __post_init__(self) -> None:
        _bounded(self.url, label="snapshot address", maximum=MAX_SNAPSHOT_URL_LENGTH)
        _bounded(self.title, label="snapshot title", maximum=MAX_SNAPSHOT_TITLE_LENGTH)
        _count(self.elements, "snapshot elements", maximum=MAX_SNAPSHOT_ELEMENTS)
        _count(self.text_length, "snapshot text length", maximum=MAX_SNAPSHOT_TEXT_LENGTH)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "url": self.url,
            "title": self.title,
            "elements": self.elements,
            "text_length": self.text_length,
        }


def snapshot_summary_from_snapshot(payload: Mapping[str, object]) -> SnapshotSummary:
    return SnapshotSummary(
        url=payload["url"],
        title=payload["title"],
        elements=payload["elements"],
        text_length=payload["text_length"],
    )


@dataclass(frozen=True, slots=True)
class PageSnapshot:
    url: str
    title: str
    text: str
    elements: tuple[SnapshotElement, ...] = ()

    def __post_init__(self) -> None:
        _bounded(self.url, label="snapshot address", maximum=MAX_SNAPSHOT_URL_LENGTH)
        _bounded(self.title, label="snapshot title", maximum=MAX_SNAPSHOT_TITLE_LENGTH)
        _bounded(self.text, label="snapshot text", maximum=MAX_SNAPSHOT_TEXT_LENGTH)
        _tuple_of(self.elements, SnapshotElement, "snapshot elements")
        if len(self.elements) > MAX_SNAPSHOT_ELEMENTS:
            raise ValueError(f"a snapshot holds at most {MAX_SNAPSHOT_ELEMENTS} elements")
        indexes = [item.index for item in self.elements]
        if len(set(indexes)) != len(indexes):
            raise ValueError("snapshot element indexes must not repeat")

    def summary(self) -> SnapshotSummary:
        return SnapshotSummary(
            url=self.url,
            title=self.title,
            elements=len(self.elements),
            text_length=len(self.text),
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "elements": [item.to_snapshot() for item in self.elements],
        }


def page_snapshot_from_document(payload: Mapping[str, object]) -> PageSnapshot:
    return PageSnapshot(
        url=payload["url"],
        title=payload["title"],
        text=payload["text"],
        elements=tuple(element_from_snapshot(item) for item in payload["elements"]),
    )


@dataclass(frozen=True, slots=True)
class TestTarget:
    __test__ = False

    role: str | None
    name: str

    def __post_init__(self) -> None:
        if self.role is not None and self.role not in TEST_ROLES:
            raise ValueError("target role must be one of the test roles")
        _normalized(self.name, label="target name", maximum=MAX_TARGET_NAME_LENGTH)

    def to_snapshot(self) -> dict[str, object]:
        return {"role": self.role, "name": self.name}


def target_from_snapshot(payload: Mapping[str, object]) -> TestTarget:
    return TestTarget(role=payload["role"], name=payload["name"])


@dataclass(frozen=True, slots=True)
class TestExpectation:
    __test__ = False

    kind: ExpectationKind
    target: TestTarget | None = None
    text: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ExpectationKind):
            raise ValueError("expectation kind must be an ExpectationKind")
        if self.target is not None and not isinstance(self.target, TestTarget):
            raise ValueError("expectation target must be a TestTarget")
        _optional_normalized(self.text, label="expected text", maximum=MAX_EXPECTED_TEXT_LENGTH)
        needs_target = self.kind in TARGET_EXPECTATIONS
        if (self.target is not None) != needs_target:
            need = "needs" if needs_target else "takes no"
            raise ValueError(f"a {self.kind.value} expectation {need} target")
        needs_text = self.kind in TEXT_EXPECTATIONS
        if (self.text is not None) != needs_text:
            need = "needs" if needs_text else "takes no"
            raise ValueError(f"a {self.kind.value} expectation {need} text")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "target": None if self.target is None else self.target.to_snapshot(),
            "text": self.text,
        }


def expectation_from_snapshot(payload: Mapping[str, object]) -> TestExpectation:
    target = payload["target"]
    return TestExpectation(
        kind=ExpectationKind(str(payload["kind"])),
        target=None if target is None else target_from_snapshot(target),
        text=payload["text"],
    )


@dataclass(frozen=True, slots=True)
class TestStep:
    __test__ = False

    action: StepAction
    target: TestTarget | None = None
    value: str | None = None
    expect: TestExpectation | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, StepAction):
            raise ValueError("step action must be a StepAction")
        if self.target is not None and not isinstance(self.target, TestTarget):
            raise ValueError("step target must be a TestTarget")
        if self.expect is not None and not isinstance(self.expect, TestExpectation):
            raise ValueError("step expectation must be a TestExpectation")
        _optional_normalized(self.value, label="step value", maximum=MAX_STEP_VALUE_LENGTH)
        action = self.action
        needs_target = action in TARGET_ACTIONS
        if (self.target is not None) != needs_target:
            need = "needs" if needs_target else "takes no"
            raise ValueError(f"a {action.value} step {need} target")
        needs_value = action in VALUE_ACTIONS
        if (self.value is not None) != needs_value:
            need = "needs" if needs_value else "takes no"
            raise ValueError(f"a {action.value} step {need} value")
        if action is StepAction.CHECK and self.expect is None:
            raise ValueError("a CHECK step needs an expectation")
        if action is StepAction.OPEN:
            _open_value(self.value)
        if action is StepAction.PRESS and self.value not in TEST_KEYS:
            raise ValueError("a PRESS step presses one of the test keys")
        roles = ACTION_ROLES.get(action)
        if roles is not None and self.target.role is not None and self.target.role not in roles:
            raise ValueError(f"a {action.value} step cannot act on a {self.target.role}")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "target": None if self.target is None else self.target.to_snapshot(),
            "value": self.value,
            "expect": None if self.expect is None else self.expect.to_snapshot(),
        }


def step_from_snapshot(payload: Mapping[str, object]) -> TestStep:
    target = payload["target"]
    expect = payload["expect"]
    return TestStep(
        action=StepAction(str(payload["action"])),
        target=None if target is None else target_from_snapshot(target),
        value=payload["value"],
        expect=None if expect is None else expectation_from_snapshot(expect),
    )


@dataclass(frozen=True, slots=True)
class TestPath:
    __test__ = False

    code: str
    heading: str
    criteria: tuple[str, ...]
    steps: tuple[TestStep, ...]

    def __post_init__(self) -> None:
        _code(self.code, _PATH_CODE, "path code")
        _normalized(self.heading, label="path heading", maximum=MAX_PATH_HEADING_LENGTH)
        _codes(
            self.criteria,
            _CRITERION_CODE,
            "path criteria",
            minimum=1,
            maximum=MAX_CRITERIA_PER_PATH,
        )
        _tuple_of(self.steps, TestStep, "path steps")
        if not 1 <= len(self.steps) <= MAX_STEPS:
            raise ValueError(f"a path holds between 1 and {MAX_STEPS} steps")
        if self.steps[0].action is not StepAction.OPEN:
            raise ValueError("the first step of a path is OPEN")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "code": self.code,
            "heading": self.heading,
            "criteria": list(self.criteria),
            "steps": [item.to_snapshot() for item in self.steps],
        }


def path_from_snapshot(payload: Mapping[str, object]) -> TestPath:
    return TestPath(
        code=payload["code"],
        heading=payload["heading"],
        criteria=tuple(payload["criteria"]),
        steps=tuple(step_from_snapshot(item) for item in payload["steps"]),
    )


@dataclass(frozen=True, slots=True)
class NotCovered:
    criterion: str
    reason: str

    def __post_init__(self) -> None:
        _code(self.criterion, _CRITERION_CODE, "not covered criterion")
        _normalized(self.reason, label="not covered reason", maximum=MAX_REASON_LENGTH)

    def to_snapshot(self) -> dict[str, object]:
        return {"criterion": self.criterion, "reason": self.reason}


def not_covered_from_snapshot(payload: Mapping[str, object]) -> NotCovered:
    return NotCovered(criterion=payload["criterion"], reason=payload["reason"])


def _not_covered(values: object, label: str) -> None:
    _tuple_of(values, NotCovered, label)
    criteria = [item.criterion for item in values]
    if len(set(criteria)) != len(criteria):
        raise ValueError(f"{label} name a criterion once")


@dataclass(frozen=True, slots=True)
class EarlierPath:
    path: TestPath
    blocked_step: int
    detail: str | None = None
    snapshot: PageSnapshot | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.path, TestPath):
            raise ValueError("an earlier path must be a TestPath")
        _count(self.blocked_step, "blocked step", minimum=1, maximum=len(self.path.steps))
        _optional_bounded(self.detail, label="blocked detail", maximum=MAX_STEP_DETAIL_LENGTH)
        if self.snapshot is not None and not isinstance(self.snapshot, PageSnapshot):
            raise ValueError("an earlier snapshot must be a PageSnapshot")

    def to_context(self) -> dict[str, object]:
        return {
            **self.path.to_snapshot(),
            "blocked_step": self.blocked_step,
            "detail": self.detail,
            "snapshot": None if self.snapshot is None else self.snapshot.to_snapshot(),
        }


@dataclass(frozen=True, slots=True)
class TestPlan:
    __test__ = False

    id: UUID
    project_id: UUID
    owner_user_id: UUID
    created_at: datetime
    locale: str
    requirements_version_number: int
    design_version_number: int
    alternative_code: str
    application: TestApplication
    criteria: tuple[str, ...]
    paths: tuple[TestPath, ...]
    not_covered: tuple[NotCovered, ...] = ()
    replan_of: tuple[str, ...] = ()
    snapshot_summary: SnapshotSummary | None = None
    generation_ids: tuple[UUID, ...] = ()
    cost_microusd: int = 0

    def __post_init__(self) -> None:
        for label, value in (
            ("test plan ID", self.id),
            ("project ID", self.project_id),
            ("owner ID", self.owner_user_id),
        ):
            _uuid(value, label)
        _aware(self.created_at, "test plan timestamp")
        _locale(self.locale)
        _count(self.requirements_version_number, "requirements version number", minimum=1)
        _count(self.design_version_number, "design version number", minimum=1)
        _code(self.alternative_code, _ALTERNATIVE_CODE, "alternative code")
        if not isinstance(self.application, TestApplication):
            raise ValueError("test plan application must be a TestApplication")
        _codes(self.criteria, _CRITERION_CODE, "test plan criteria", minimum=1)
        _tuple_of(self.paths, TestPath, "test plan paths")
        if len(self.paths) > MAX_PATHS:
            raise ValueError(f"a test plan holds at most {MAX_PATHS} paths")
        codes = [item.code for item in self.paths]
        if len(set(codes)) != len(codes):
            raise ValueError("test plan path codes must not repeat")
        requested = set(self.criteria)
        covered = {code for item in self.paths for code in item.criteria}
        if not covered <= requested:
            raise ValueError("a path verifies only requested criteria")
        _not_covered(self.not_covered, "test plan not covered criteria")
        uncovered = {item.criterion for item in self.not_covered}
        if not uncovered <= requested or uncovered & covered:
            raise ValueError("a not covered criterion is requested and in no path")
        if covered | uncovered != requested:
            raise ValueError("every requested criterion is in a path or not covered")
        _codes(self.replan_of, _PATH_CODE, "replanned paths", maximum=MAX_EARLIER_PATHS)
        if self.snapshot_summary is not None and not isinstance(
            self.snapshot_summary, SnapshotSummary
        ):
            raise ValueError("snapshot summary must be a SnapshotSummary")
        _uuids(self.generation_ids, "generation IDs")
        _count(self.cost_microusd, "test plan cost")

    def reference_snapshot(self) -> dict[str, object]:
        return {
            "requirements_version_number": self.requirements_version_number,
            "design_version_number": self.design_version_number,
            "alternative_code": self.alternative_code,
        }

    def to_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "created_at": _timestamp(self.created_at),
            "locale": self.locale,
            "reference": self.reference_snapshot(),
            "application": self.application.to_snapshot(),
            "criteria": list(self.criteria),
            "replan_of": list(self.replan_of),
            "paths": [item.to_snapshot() for item in self.paths],
            "not_covered": [item.to_snapshot() for item in self.not_covered],
            "cost_microusd": self.cost_microusd,
        }


@dataclass(frozen=True, slots=True)
class StepResult:
    index: int
    status: StepStatus
    detail: str | None = None
    url: str | None = None
    title: str | None = None
    screenshot: str | None = None

    def __post_init__(self) -> None:
        _count(self.index, "step index", minimum=1, maximum=MAX_STEPS)
        if not isinstance(self.status, StepStatus):
            raise ValueError("step status must be a StepStatus")
        _optional_bounded(self.detail, label="step detail", maximum=MAX_STEP_DETAIL_LENGTH)
        _optional_bounded(self.url, label="step address", maximum=MAX_SNAPSHOT_URL_LENGTH)
        _optional_bounded(self.title, label="step title", maximum=MAX_SNAPSHOT_TITLE_LENGTH)
        if self.screenshot is not None and normalize_screenshot(self.screenshot) != (
            self.screenshot
        ):
            raise ValueError("screenshot path must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "index": self.index,
            "status": self.status.value,
            "detail": self.detail,
            "url": self.url,
            "title": self.title,
            "screenshot": self.screenshot,
        }


def step_result_from_snapshot(payload: Mapping[str, object]) -> StepResult:
    return StepResult(
        index=payload["index"],
        status=StepStatus(str(payload["status"])),
        detail=payload["detail"],
        url=payload["url"],
        title=payload["title"],
        screenshot=payload["screenshot"],
    )


@dataclass(frozen=True, slots=True)
class PathResult:
    path: TestPath
    browser: str
    status: PathStatus
    seconds: float
    steps: tuple[StepResult, ...] = ()
    page_text: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.path, TestPath):
            raise ValueError("result path must be a TestPath")
        if self.browser not in BROWSER_NAMES:
            raise ValueError("result browser must be chrome or firefox")
        if not isinstance(self.status, PathStatus):
            raise ValueError("result status must be a PathStatus")
        seconds = self.seconds
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, int | float)
            or not math.isfinite(seconds)
            or not 0 <= seconds <= MAX_PATH_SECONDS
        ):
            raise ValueError(f"result seconds must be between 0 and {MAX_PATH_SECONDS}")
        _tuple_of(self.steps, StepResult, "result steps")
        if tuple(item.index for item in self.steps) != tuple(range(1, len(self.steps) + 1)):
            raise ValueError("the steps of a result are numbered from 1 in order")
        if len(self.steps) > len(self.path.steps):
            raise ValueError("a result holds at most the steps of its path")
        _optional_bounded(self.page_text, label="page text", maximum=MAX_PAGE_TEXT_LENGTH)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "path": self.path.to_snapshot(),
            "browser": self.browser,
            "status": self.status.value,
            "seconds": float(self.seconds),
            "steps": [item.to_snapshot() for item in self.steps],
            "page_text": self.page_text,
        }


def path_result_from_snapshot(payload: Mapping[str, object]) -> PathResult:
    return PathResult(
        path=path_from_snapshot(payload["path"]),
        browser=payload["browser"],
        status=PathStatus(str(payload["status"])),
        seconds=payload["seconds"],
        steps=tuple(step_result_from_snapshot(item) for item in payload["steps"]),
        page_text=payload["page_text"],
    )


@dataclass(frozen=True, slots=True)
class BrowserInfo:
    name: str
    version: str

    def __post_init__(self) -> None:
        if self.name not in BROWSER_NAMES:
            raise ValueError("browser name must be chrome or firefox")
        _normalized(self.version, label="browser version", maximum=MAX_BROWSER_VERSION_LENGTH)

    def to_snapshot(self) -> dict[str, object]:
        return {"name": self.name, "version": self.version}


def browser_from_snapshot(payload: Mapping[str, object]) -> BrowserInfo:
    return BrowserInfo(name=payload["name"], version=payload["version"])


@dataclass(frozen=True, slots=True)
class CriterionOutcome:
    code: str
    status: CriterionStatus
    paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _code(self.code, _CRITERION_CODE, "criterion code")
        if not isinstance(self.status, CriterionStatus):
            raise ValueError("criterion status must be a CriterionStatus")
        _codes(self.paths, _PATH_CODE, "criterion paths")

    def to_snapshot(self) -> dict[str, object]:
        return {"code": self.code, "status": self.status.value, "paths": list(self.paths)}


def outcome_from_snapshot(payload: Mapping[str, object]) -> CriterionOutcome:
    return CriterionOutcome(
        code=payload["code"],
        status=CriterionStatus(str(payload["status"])),
        paths=tuple(payload["paths"]),
    )


@dataclass(frozen=True, slots=True)
class RunSummary:
    passed: int = 0
    failed: int = 0
    blocked: int = 0
    not_covered: int = 0
    not_run: int = 0

    def __post_init__(self) -> None:
        for label, value in (
            ("passed criteria", self.passed),
            ("failed criteria", self.failed),
            ("blocked criteria", self.blocked),
            ("not covered criteria", self.not_covered),
            ("not run criteria", self.not_run),
        ):
            _count(value, label)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "failed": self.failed,
            "blocked": self.blocked,
            "not_covered": self.not_covered,
            "not_run": self.not_run,
        }


def run_summary_from_snapshot(payload: Mapping[str, object]) -> RunSummary:
    return RunSummary(
        passed=payload["passed"],
        failed=payload["failed"],
        blocked=payload["blocked"],
        not_covered=payload["not_covered"],
        not_run=payload["not_run"],
    )


def criteria_outcomes(
    paths: Sequence[TestPath],
    results: Sequence[PathResult],
    not_covered: Sequence[NotCovered],
    requested: Sequence[str],
) -> tuple[CriterionOutcome, ...]:
    uncovered = {item.criterion for item in not_covered}
    outcomes = []
    for code in dict.fromkeys(requested):
        named = [item for item in results if code in item.path.criteria]
        statuses = {item.status for item in named}
        if PathStatus.FAILED in statuses:
            status = CriterionStatus.FAILED
        elif PathStatus.BLOCKED in statuses:
            status = CriterionStatus.BLOCKED
        elif named and statuses == {PathStatus.PASSED}:
            status = CriterionStatus.PASSED
        elif not named and code in uncovered:
            status = CriterionStatus.NOT_COVERED
        else:
            status = CriterionStatus.NOT_RUN
        if named:
            codes = [item.path.code for item in named]
        elif status is CriterionStatus.NOT_RUN:
            codes = [item.code for item in paths if code in item.criteria]
        else:
            codes = []
        outcomes.append(
            CriterionOutcome(code=code, status=status, paths=tuple(dict.fromkeys(codes)))
        )
    return tuple(outcomes)


def run_summary(outcomes: Sequence[CriterionOutcome]) -> RunSummary:
    counts = Counter(item.status for item in outcomes)
    return RunSummary(
        passed=counts[CriterionStatus.PASSED],
        failed=counts[CriterionStatus.FAILED],
        blocked=counts[CriterionStatus.BLOCKED],
        not_covered=counts[CriterionStatus.NOT_COVERED],
        not_run=counts[CriterionStatus.NOT_RUN],
    )


@dataclass(frozen=True, slots=True)
class TestFinding:
    __test__ = False

    severity: FindingSeverity
    text: str
    criterion: str | None = None
    requirement: str | None = None
    screen: str | None = None
    action: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.severity, FindingSeverity):
            raise ValueError("finding severity must be a FindingSeverity")
        _normalized(self.text, label="finding text", maximum=MAX_FINDING_LENGTH)
        for value, pattern, label in (
            (self.criterion, _CRITERION_CODE, "finding criterion"),
            (self.requirement, _REQUIREMENT_CODE, "finding requirement"),
            (self.screen, _SCREEN_CODE, "finding screen"),
        ):
            if value is not None:
                _code(value, pattern, label)
        _optional_normalized(self.action, label="finding action", maximum=MAX_ACTION_LENGTH)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "severity": self.severity.value,
            "text": self.text,
            "about": {
                "criterion": self.criterion,
                "requirement": self.requirement,
                "screen": self.screen,
            },
            "action": self.action,
        }


def finding_from_snapshot(payload: Mapping[str, object]) -> TestFinding:
    about = payload["about"]
    if not isinstance(about, Mapping):
        raise ValueError("finding about must be an object")
    return TestFinding(
        severity=FindingSeverity(str(payload["severity"])),
        text=payload["text"],
        criterion=about["criterion"],
        requirement=about["requirement"],
        screen=about["screen"],
        action=payload["action"],
    )


@dataclass(frozen=True, slots=True)
class TestCritique:
    __test__ = False

    twin_id: UUID
    twin_name: str
    verdict: CritiqueVerdict
    summary: str
    findings: tuple[TestFinding, ...] = ()

    def __post_init__(self) -> None:
        _uuid(self.twin_id, "critique twin ID")
        _normalized(self.twin_name, label="critique twin name", maximum=MAX_TWIN_NAME_LENGTH)
        if not isinstance(self.verdict, CritiqueVerdict):
            raise ValueError("critique verdict must be a CritiqueVerdict")
        _normalized(self.summary, label="critique summary", maximum=MAX_SUMMARY_LENGTH)
        _tuple_of(self.findings, TestFinding, "critique findings")
        if len(self.findings) > MAX_FINDINGS:
            raise ValueError(f"a critique holds at most {MAX_FINDINGS} findings")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "twin_id": str(self.twin_id),
            "twin_name": self.twin_name,
            "verdict": self.verdict.value,
            "summary": self.summary,
            "findings": [item.to_snapshot() for item in self.findings],
        }


def critique_from_snapshot(payload: Mapping[str, object]) -> TestCritique:
    return TestCritique(
        twin_id=UUID(str(payload["twin_id"])),
        twin_name=payload["twin_name"],
        verdict=CritiqueVerdict(str(payload["verdict"])),
        summary=payload["summary"],
        findings=tuple(finding_from_snapshot(item) for item in payload["findings"]),
    )


@dataclass(frozen=True, slots=True)
class TestReview:
    __test__ = False

    id: UUID
    run_id: UUID
    project_id: UUID
    owner_user_id: UUID
    reviewed_at: datetime
    locale: str
    critiques: tuple[TestCritique, ...]
    generation_ids: tuple[UUID, ...] = ()
    cost_microusd: int = 0

    def __post_init__(self) -> None:
        for label, value in (
            ("test review ID", self.id),
            ("test run ID", self.run_id),
            ("project ID", self.project_id),
            ("owner ID", self.owner_user_id),
        ):
            _uuid(value, label)
        _aware(self.reviewed_at, "test review timestamp")
        _locale(self.locale)
        _tuple_of(self.critiques, TestCritique, "test review critiques")
        if not 1 <= len(self.critiques) <= MAX_USER_TWINS:
            raise ValueError(f"a test review holds between 1 and {MAX_USER_TWINS} critiques")
        twins = [item.twin_id for item in self.critiques]
        if len(set(twins)) != len(twins):
            raise ValueError("a test review holds one critique per twin")
        _uuids(self.generation_ids, "generation IDs")
        _count(self.cost_microusd, "test review cost")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "reviewed_at": _timestamp(self.reviewed_at),
            "locale": self.locale,
            "critiques": [item.to_snapshot() for item in self.critiques],
            "cost_microusd": self.cost_microusd,
        }


@dataclass(frozen=True, slots=True)
class TestRun:
    __test__ = False

    id: UUID
    project_id: UUID
    owner_user_id: UUID
    plan_id: UUID
    started_at: datetime
    finished_at: datetime
    recorded_at: datetime
    application: TestApplication
    browsers: tuple[BrowserInfo, ...]
    requirements_version_number: int
    design_version_number: int
    alternative_code: str
    results: tuple[PathResult, ...]
    not_covered: tuple[NotCovered, ...]
    criteria: tuple[CriterionOutcome, ...]
    summary: RunSummary
    replan_ids: tuple[UUID, ...] = ()
    cost_microusd: int = 0
    review: TestReview | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("test run ID", self.id),
            ("project ID", self.project_id),
            ("owner ID", self.owner_user_id),
            ("test plan ID", self.plan_id),
        ):
            _uuid(value, label)
        _uuids(self.replan_ids, "replan IDs", maximum=MAX_REPLANS)
        if self.plan_id in self.replan_ids:
            raise ValueError("a replan is not the plan itself")
        for label, value in (
            ("run start", self.started_at),
            ("run end", self.finished_at),
            ("run record time", self.recorded_at),
        ):
            _aware(value, label)
        if self.finished_at < self.started_at:
            raise ValueError("a run ends after it starts")
        if not isinstance(self.application, TestApplication):
            raise ValueError("run application must be a TestApplication")
        _tuple_of(self.browsers, BrowserInfo, "run browsers")
        names = [item.name for item in self.browsers]
        if not 1 <= len(names) <= MAX_BROWSERS or len(set(names)) != len(names):
            raise ValueError(f"a run names between 1 and {MAX_BROWSERS} distinct browsers")
        _count(self.requirements_version_number, "requirements version number", minimum=1)
        _count(self.design_version_number, "design version number", minimum=1)
        _code(self.alternative_code, _ALTERNATIVE_CODE, "alternative code")
        _tuple_of(self.results, PathResult, "run results")
        if len(self.results) > MAX_RESULTS:
            raise ValueError(f"a run holds at most {MAX_RESULTS} results")
        if any(item.browser not in names for item in self.results):
            raise ValueError("every result names a browser of the run")
        _not_covered(self.not_covered, "run not covered criteria")
        _tuple_of(self.criteria, CriterionOutcome, "run criteria")
        codes = [item.code for item in self.criteria]
        if len(set(codes)) != len(codes):
            raise ValueError("run criteria must not repeat")
        if any(item.criterion not in codes for item in self.not_covered):
            raise ValueError("a not covered criterion is a criterion of the run")
        if not isinstance(self.summary, RunSummary) or self.summary != run_summary(self.criteria):
            raise ValueError("the run summary counts the criteria of the run")
        _count(self.cost_microusd, "test run cost")
        if self.review is not None and (
            not isinstance(self.review, TestReview)
            or (self.review.run_id, self.review.project_id, self.review.owner_user_id)
            != (self.id, self.project_id, self.owner_user_id)
        ):
            raise ValueError("the review of a run belongs to that run")

    def reference_snapshot(self) -> dict[str, object]:
        return {
            "requirements_version_number": self.requirements_version_number,
            "design_version_number": self.design_version_number,
            "alternative_code": self.alternative_code,
        }

    def with_review(self, review: TestReview | None) -> TestRun:
        return replace(self, review=review)

    @property
    def total_cost_microusd(self) -> int:
        return self.cost_microusd + (0 if self.review is None else self.review.cost_microusd)

    def to_snapshot(self) -> dict[str, object]:
        review = self.review
        return {
            "id": str(self.id),
            "started_at": _timestamp(self.started_at),
            "finished_at": _timestamp(self.finished_at),
            "recorded_at": _timestamp(self.recorded_at),
            "application": self.application.to_snapshot(),
            "browsers": [item.to_snapshot() for item in self.browsers],
            "reference": self.reference_snapshot(),
            "summary": self.summary.to_snapshot(),
            "criteria": [item.to_snapshot() for item in self.criteria],
            "not_covered": [item.to_snapshot() for item in self.not_covered],
            "results": [item.to_snapshot() for item in self.results],
            "critiques": []
            if review is None
            else [item.to_snapshot() for item in review.critiques],
            "reviewed_at": None if review is None else _timestamp(review.reviewed_at),
            "cost_microusd": self.total_cost_microusd,
        }


def _planned_path(paths: Sequence[TestPath], result: PathResult, position: int) -> TestPath:
    candidates = [item for item in paths if item.code == result.path.code]
    if not candidates:
        raise ValueError(
            f"result {position} names the path {result.path.code}, "
            "which is not in the plan or in its replans"
        )
    return next((item for item in candidates if item == result.path), candidates[-1])


def build_test_run(
    *,
    run_id: UUID,
    plans: Sequence[TestPlan],
    started_at: datetime,
    finished_at: datetime,
    recorded_at: datetime,
    application: TestApplication,
    browsers: Sequence[BrowserInfo],
    results: Sequence[PathResult],
    not_covered: Sequence[NotCovered],
) -> TestRun:
    if not plans:
        raise ValueError("a run needs its plan")
    plan, *replans = plans
    paths = tuple(path for item in plans for path in item.paths)
    requested = tuple(dict.fromkeys(code for item in plans for code in item.criteria))
    bound = []
    for position, result in enumerate(results):
        planned = _planned_path(paths, result, position)
        if len(result.steps) > len(planned.steps):
            raise ValueError(f"result {position} holds more steps than its path")
        bound.append(replace(result, path=planned))
    unknown = [item.criterion for item in not_covered if item.criterion not in requested]
    if unknown:
        raise ValueError(f"the not covered criteria {', '.join(unknown)} are not in the plans")
    outcomes = criteria_outcomes(paths, bound, not_covered, requested)
    return TestRun(
        id=run_id,
        project_id=plan.project_id,
        owner_user_id=plan.owner_user_id,
        plan_id=plan.id,
        replan_ids=tuple(item.id for item in replans),
        started_at=started_at,
        finished_at=finished_at,
        recorded_at=recorded_at,
        application=application,
        browsers=tuple(browsers),
        requirements_version_number=plan.requirements_version_number,
        design_version_number=plan.design_version_number,
        alternative_code=plan.alternative_code,
        results=tuple(bound),
        not_covered=tuple(not_covered),
        criteria=outcomes,
        summary=run_summary(outcomes),
        cost_microusd=sum(item.cost_microusd for item in plans),
    )


__all__ = [
    "ACTION_ROLES",
    "CLICKABLE_ROLES",
    "CRITERION_CODE_PATTERN",
    "CUT_MARK",
    "ELEMENT_STATES",
    "MAX_OPTION_LABEL_LENGTH",
    "MAX_PATH_NUMBER",
    "MAX_PATH_SECONDS",
    "MAX_REPLANS",
    "MAX_REQUESTED_CRITERIA",
    "MAX_SNAPSHOT_TITLE_LENGTH",
    "MAX_SNAPSHOT_URL_LENGTH",
    "MAX_SNAPSHOT_VALUE_LENGTH",
    "PATH_CODE_PATTERN",
    "PATH_CODE_PREFIX",
    "SELECTING_ROLES",
    "TARGET_ACTIONS",
    "TARGET_EXPECTATIONS",
    "TEXT_EXPECTATIONS",
    "TYPING_ROLES",
    "VALUE_ACTIONS",
    "ApplicationKind",
    "BrowserInfo",
    "CriterionOutcome",
    "CriterionStatus",
    "EarlierPath",
    "ExpectationKind",
    "NotCovered",
    "PageSnapshot",
    "PathResult",
    "PathStatus",
    "RunSummary",
    "SnapshotElement",
    "SnapshotSummary",
    "StepAction",
    "StepResult",
    "StepStatus",
    "TestApplication",
    "TestCritique",
    "TestExpectation",
    "TestFinding",
    "TestPath",
    "TestPlan",
    "TestPlanUnknown",
    "TestReview",
    "TestRun",
    "TestStep",
    "TestTarget",
    "application_from_snapshot",
    "browser_from_snapshot",
    "build_test_run",
    "criteria_outcomes",
    "critique_from_snapshot",
    "cut_text",
    "element_from_snapshot",
    "expectation_from_snapshot",
    "finding_from_snapshot",
    "normalize_address",
    "normalize_screenshot",
    "not_covered_from_snapshot",
    "outcome_from_snapshot",
    "page_snapshot_from_document",
    "path_code",
    "path_from_snapshot",
    "path_number",
    "path_result_from_snapshot",
    "run_summary",
    "run_summary_from_snapshot",
    "snapshot_summary_from_snapshot",
    "step_from_snapshot",
    "step_result_from_snapshot",
    "target_from_snapshot",
]
