"""Immutable architecture-stage test-plan artifacts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    canonical_json,
    canonical_uuid_tuple,
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_display_code,
)

_MAX_TITLE_LENGTH: Final = 200
_MAX_DESCRIPTION_LENGTH: Final = 4000
_MAX_ITEM_LENGTH: Final = 2000


class TestLevel(StrEnum):
    """Stable test levels used across generated-project stacks."""

    UNIT = "UNIT"
    COMPONENT = "COMPONENT"
    CONTRACT = "CONTRACT"
    INTEGRATION = "INTEGRATION"
    END_TO_END = "END_TO_END"
    ACCESSIBILITY = "ACCESSIBILITY"
    SECURITY = "SECURITY"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class TestAutomation(StrEnum):
    """How one planned check is executed."""

    AUTOMATED = "AUTOMATED"
    MANUAL = "MANUAL"
    HYBRID = "HYBRID"


class TestPriority(StrEnum):
    """Execution priority of a planned test."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class TestEnvironmentKind(StrEnum):
    """Portable environment classifications for test execution."""

    LOCAL = "LOCAL"
    CONTAINER = "CONTAINER"
    BROWSER = "BROWSER"
    ANDROID_EMULATOR = "ANDROID_EMULATOR"
    PHYSICAL_DEVICE = "PHYSICAL_DEVICE"


@dataclass(frozen=True, slots=True)
class TestEnvironment:
    """One declared environment needed by planned tests."""

    id: UUID
    code: str
    name: str
    kind: TestEnvironmentKind
    description: str
    configuration: tuple[str, ...]

    def __post_init__(self) -> None:
        """Protect normalized, inspectable environment metadata."""
        validate_display_code(self.code, prefix="ENV", label="test environment code")

        for value, label, maximum_length in (
            (self.name, "test environment name", _MAX_TITLE_LENGTH),
            (self.description, "test environment description", _MAX_DESCRIPTION_LENGTH),
        ):
            if normalize_required_text(value, label=label, maximum_length=maximum_length) != value:
                raise ValueError(f"{label} must be normalized")

        if self.configuration != normalize_text_items(
            self.configuration,
            label="test environment configuration",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ):
            raise ValueError("test environment configuration must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic environment snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "name": self.name,
            "kind": self.kind.value,
            "description": self.description,
            "configuration": list(self.configuration),
        }


@dataclass(frozen=True, slots=True)
class PlannedTestCase:
    """One traceable generated-project test or review activity."""

    id: UUID
    code: str
    title: str
    objective: str
    level: TestLevel
    automation: TestAutomation
    priority: TestPriority
    preconditions: tuple[str, ...]
    steps: tuple[str, ...]
    expected_results: tuple[str, ...]
    requirement_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]
    architecture_component_ids: tuple[UUID, ...]
    design_alternative_ids: tuple[UUID, ...]
    environment_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        """Protect executable intent and end-to-end traceability."""
        validate_display_code(self.code, prefix="TST", label="planned test-case code")

        for value, label, maximum_length in (
            (self.title, "planned test-case title", _MAX_TITLE_LENGTH),
            (self.objective, "planned test-case objective", _MAX_DESCRIPTION_LENGTH),
        ):
            if normalize_required_text(value, label=label, maximum_length=maximum_length) != value:
                raise ValueError(f"{label} must be normalized")

        for values, label, require_items, require_unique in (
            (self.preconditions, "planned test preconditions", False, False),
            (self.steps, "planned test steps", True, False),
            (self.expected_results, "planned test expected results", True, False),
        ):
            if values != normalize_text_items(
                values,
                label=label,
                maximum_item_length=_MAX_ITEM_LENGTH,
                require_items=require_items,
                require_unique=require_unique,
            ):
                raise ValueError(f"{label} must be normalized")

        for values, label, require_items in (
            (self.requirement_ids, "planned test requirement IDs", False),
            (
                self.acceptance_criterion_ids,
                "planned test acceptance-criterion IDs",
                False,
            ),
            (
                self.architecture_component_ids,
                "planned test architecture-component IDs",
                True,
            ),
            (
                self.design_alternative_ids,
                "planned test design-alternative IDs",
                True,
            ),
            (self.environment_ids, "planned test environment IDs", True),
        ):
            if values != canonical_uuid_tuple(
                values,
                label=label,
                require_items=require_items,
            ):
                raise ValueError(f"{label} must use canonical order")

        if not self.requirement_ids and not self.acceptance_criterion_ids:
            raise ValueError(
                "planned tests require requirement or acceptance-criterion traceability"
            )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic planned-test snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "title": self.title,
            "objective": self.objective,
            "level": self.level.value,
            "automation": self.automation.value,
            "priority": self.priority.value,
            "preconditions": list(self.preconditions),
            "steps": list(self.steps),
            "expected_results": list(self.expected_results),
            "requirement_ids": [str(value) for value in self.requirement_ids],
            "acceptance_criterion_ids": [str(value) for value in self.acceptance_criterion_ids],
            "architecture_component_ids": [str(value) for value in self.architecture_component_ids],
            "design_alternative_ids": [str(value) for value in self.design_alternative_ids],
            "environment_ids": [str(value) for value in self.environment_ids],
        }


@dataclass(frozen=True, slots=True)
class QualityGate:
    """One deterministic completion condition over planned tests."""

    id: UUID
    code: str
    title: str
    criterion: str
    required_test_case_ids: tuple[UUID, ...]
    minimum_pass_rate: int
    blocking: bool

    def __post_init__(self) -> None:
        """Protect stable gate identity and a valid pass threshold."""
        validate_display_code(self.code, prefix="QGT", label="quality-gate code")

        for value, label, maximum_length in (
            (self.title, "quality-gate title", _MAX_TITLE_LENGTH),
            (self.criterion, "quality-gate criterion", _MAX_DESCRIPTION_LENGTH),
        ):
            if normalize_required_text(value, label=label, maximum_length=maximum_length) != value:
                raise ValueError(f"{label} must be normalized")

        if self.required_test_case_ids != canonical_uuid_tuple(
            self.required_test_case_ids,
            label="quality-gate test-case IDs",
            require_items=True,
        ):
            raise ValueError("quality-gate test-case IDs must use canonical order")

        if (
            isinstance(self.minimum_pass_rate, bool)
            or not isinstance(self.minimum_pass_rate, int)
            or not 0 <= self.minimum_pass_rate <= 100
        ):
            raise ValueError("quality-gate minimum pass rate must be between 0 and 100")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic quality-gate snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "title": self.title,
            "criterion": self.criterion,
            "required_test_case_ids": [str(value) for value in self.required_test_case_ids],
            "minimum_pass_rate": self.minimum_pass_rate,
            "blocking": self.blocking,
        }


class _CodedArtifact(Protocol):
    id: UUID
    code: str


def _canonical_coded_artifacts[T: _CodedArtifact](
    values: Iterable[T],
    *,
    label: str,
    require_items: bool,
) -> tuple[T, ...]:
    """Return unique coded artifacts in deterministic code order."""
    artifacts = tuple(values)

    if require_items and not artifacts:
        raise ValueError(f"{label} must not be empty")

    if len({artifact.id for artifact in artifacts}) != len(artifacts):
        raise ValueError(f"{label} identities must be unique")

    if len({artifact.code for artifact in artifacts}) != len(artifacts):
        raise ValueError(f"{label} codes must be unique")

    return tuple(sorted(artifacts, key=lambda artifact: artifact.code))


@dataclass(frozen=True, slots=True)
class TestPlan:
    """A complete and traceable architecture-stage test strategy."""

    id: UUID
    code: str
    title: str
    strategy: str
    architecture_id: UUID
    selected_design_alternative_id: UUID
    requirement_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]
    architecture_component_ids: tuple[UUID, ...]
    environments: tuple[TestEnvironment, ...]
    test_cases: tuple[PlannedTestCase, ...]
    quality_gates: tuple[QualityGate, ...]
    fixtures: tuple[str, ...]
    assumptions: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Protect canonical ordering, references, and complete test coverage."""
        validate_display_code(self.code, prefix="TPL", label="test-plan code")

        for value, label, maximum_length in (
            (self.title, "test-plan title", _MAX_TITLE_LENGTH),
            (self.strategy, "test-plan strategy", _MAX_DESCRIPTION_LENGTH),
        ):
            if normalize_required_text(value, label=label, maximum_length=maximum_length) != value:
                raise ValueError(f"{label} must be normalized")

        for values, label in (
            (self.requirement_ids, "test-plan requirement IDs"),
            (self.acceptance_criterion_ids, "test-plan acceptance-criterion IDs"),
            (self.architecture_component_ids, "test-plan architecture-component IDs"),
        ):
            if values != canonical_uuid_tuple(values, label=label, require_items=True):
                raise ValueError(f"{label} must use canonical order")

        for values, expected, label in (
            (
                self.environments,
                _canonical_coded_artifacts(
                    self.environments,
                    label="test environments",
                    require_items=True,
                ),
                "test environments",
            ),
            (
                self.test_cases,
                _canonical_coded_artifacts(
                    self.test_cases,
                    label="planned test cases",
                    require_items=True,
                ),
                "planned test cases",
            ),
            (
                self.quality_gates,
                _canonical_coded_artifacts(
                    self.quality_gates,
                    label="quality gates",
                    require_items=True,
                ),
                "quality gates",
            ),
        ):
            if values != expected:
                raise ValueError(f"{label} must use canonical code order")

        for values, label, require_items in (
            (self.fixtures, "test-plan fixtures", False),
            (self.assumptions, "test-plan assumptions", False),
            (self.open_questions, "test-plan open questions", False),
        ):
            if values != normalize_text_items(
                values,
                label=label,
                maximum_item_length=_MAX_ITEM_LENGTH,
                require_items=require_items,
            ):
                raise ValueError(f"{label} must be normalized")

        self._validate_references_and_coverage()

    def _validate_references_and_coverage(self) -> None:
        """Reject unknown links and uncovered approved outcomes."""
        environment_ids = frozenset(environment.id for environment in self.environments)
        test_case_ids = frozenset(test_case.id for test_case in self.test_cases)
        component_ids = frozenset(self.architecture_component_ids)
        requirement_ids = frozenset(self.requirement_ids)
        criterion_ids = frozenset(self.acceptance_criterion_ids)

        covered_requirements: set[UUID] = set()
        covered_criteria: set[UUID] = set()

        for test_case in self.test_cases:
            _require_subset(
                test_case.environment_ids,
                environment_ids,
                "planned tests contain unknown environment references",
            )
            _require_subset(
                test_case.architecture_component_ids,
                component_ids,
                "planned tests contain unknown architecture-component references",
            )
            _require_subset(
                test_case.requirement_ids,
                requirement_ids,
                "planned tests contain unknown requirement references",
            )
            _require_subset(
                test_case.acceptance_criterion_ids,
                criterion_ids,
                "planned tests contain unknown acceptance-criterion references",
            )

            if test_case.design_alternative_ids != (self.selected_design_alternative_id,):
                raise ValueError(
                    "planned tests must reference only the selected design alternative"
                )

            covered_requirements.update(test_case.requirement_ids)
            covered_criteria.update(test_case.acceptance_criterion_ids)

        if covered_requirements != requirement_ids:
            raise ValueError("the test plan must cover every approved requirement")

        if covered_criteria != criterion_ids:
            raise ValueError("the test plan must cover every approved acceptance criterion")

        for gate in self.quality_gates:
            _require_subset(
                gate.required_test_case_ids,
                test_case_ids,
                "quality gates contain unknown test-case references",
            )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic test-plan snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "title": self.title,
            "strategy": self.strategy,
            "architecture_id": str(self.architecture_id),
            "selected_design_alternative_id": str(self.selected_design_alternative_id),
            "requirement_ids": [str(value) for value in self.requirement_ids],
            "acceptance_criterion_ids": [str(value) for value in self.acceptance_criterion_ids],
            "architecture_component_ids": [str(value) for value in self.architecture_component_ids],
            "environments": [environment.to_snapshot() for environment in self.environments],
            "test_cases": [test_case.to_snapshot() for test_case in self.test_cases],
            "quality_gates": [gate.to_snapshot() for gate in self.quality_gates],
            "fixtures": list(self.fixtures),
            "assumptions": list(self.assumptions),
            "open_questions": list(self.open_questions),
        }

    def canonical_json(self) -> str:
        """Serialize this test plan deterministically."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of this test plan."""
        return snapshot_content_hash(self.to_snapshot())


def _require_subset(values: Iterable[UUID], allowed: frozenset[UUID], message: str) -> None:
    """Require every UUID in one collection to resolve in an allowed set."""
    if not frozenset(values).issubset(allowed):
        raise ValueError(message)


def create_test_environment(
    *,
    environment_id: UUID,
    code: str,
    name: str,
    kind: TestEnvironmentKind,
    description: str,
    configuration: Iterable[str] = (),
) -> TestEnvironment:
    """Create one normalized test environment."""
    return TestEnvironment(
        id=environment_id,
        code=code,
        name=normalize_required_text(
            name,
            label="test environment name",
            maximum_length=_MAX_TITLE_LENGTH,
        ),
        kind=kind,
        description=normalize_required_text(
            description,
            label="test environment description",
            maximum_length=_MAX_DESCRIPTION_LENGTH,
        ),
        configuration=normalize_text_items(
            configuration,
            label="test environment configuration",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ),
    )


def create_planned_test_case(
    *,
    test_case_id: UUID,
    code: str,
    title: str,
    objective: str,
    level: TestLevel,
    automation: TestAutomation,
    priority: TestPriority,
    steps: Iterable[str],
    expected_results: Iterable[str],
    architecture_component_ids: Iterable[UUID],
    design_alternative_ids: Iterable[UUID],
    environment_ids: Iterable[UUID],
    requirement_ids: Iterable[UUID] = (),
    acceptance_criterion_ids: Iterable[UUID] = (),
    preconditions: Iterable[str] = (),
) -> PlannedTestCase:
    """Create one normalized, traceable planned test."""
    return PlannedTestCase(
        id=test_case_id,
        code=code,
        title=normalize_required_text(
            title,
            label="planned test-case title",
            maximum_length=_MAX_TITLE_LENGTH,
        ),
        objective=normalize_required_text(
            objective,
            label="planned test-case objective",
            maximum_length=_MAX_DESCRIPTION_LENGTH,
        ),
        level=level,
        automation=automation,
        priority=priority,
        preconditions=normalize_text_items(
            preconditions,
            label="planned test preconditions",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
            require_unique=False,
        ),
        steps=normalize_text_items(
            steps,
            label="planned test steps",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=True,
            require_unique=False,
        ),
        expected_results=normalize_text_items(
            expected_results,
            label="planned test expected results",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=True,
            require_unique=False,
        ),
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="planned test requirement IDs",
            require_items=False,
        ),
        acceptance_criterion_ids=canonical_uuid_tuple(
            acceptance_criterion_ids,
            label="planned test acceptance-criterion IDs",
            require_items=False,
        ),
        architecture_component_ids=canonical_uuid_tuple(
            architecture_component_ids,
            label="planned test architecture-component IDs",
            require_items=True,
        ),
        design_alternative_ids=canonical_uuid_tuple(
            design_alternative_ids,
            label="planned test design-alternative IDs",
            require_items=True,
        ),
        environment_ids=canonical_uuid_tuple(
            environment_ids,
            label="planned test environment IDs",
            require_items=True,
        ),
    )


def create_quality_gate(
    *,
    gate_id: UUID,
    code: str,
    title: str,
    criterion: str,
    required_test_case_ids: Iterable[UUID],
    minimum_pass_rate: int,
    blocking: bool,
) -> QualityGate:
    """Create one normalized deterministic quality gate."""
    return QualityGate(
        id=gate_id,
        code=code,
        title=normalize_required_text(
            title,
            label="quality-gate title",
            maximum_length=_MAX_TITLE_LENGTH,
        ),
        criterion=normalize_required_text(
            criterion,
            label="quality-gate criterion",
            maximum_length=_MAX_DESCRIPTION_LENGTH,
        ),
        required_test_case_ids=canonical_uuid_tuple(
            required_test_case_ids,
            label="quality-gate test-case IDs",
            require_items=True,
        ),
        minimum_pass_rate=minimum_pass_rate,
        blocking=blocking,
    )


def create_test_plan(
    *,
    plan_id: UUID,
    code: str,
    title: str,
    strategy: str,
    architecture_id: UUID,
    selected_design_alternative_id: UUID,
    requirement_ids: Iterable[UUID],
    acceptance_criterion_ids: Iterable[UUID],
    architecture_component_ids: Iterable[UUID],
    environments: Iterable[TestEnvironment],
    test_cases: Iterable[PlannedTestCase],
    quality_gates: Iterable[QualityGate],
    fixtures: Iterable[str] = (),
    assumptions: Iterable[str] = (),
    open_questions: Iterable[str] = (),
) -> TestPlan:
    """Create one canonical architecture-stage test plan."""
    return TestPlan(
        id=plan_id,
        code=code,
        title=normalize_required_text(
            title,
            label="test-plan title",
            maximum_length=_MAX_TITLE_LENGTH,
        ),
        strategy=normalize_required_text(
            strategy,
            label="test-plan strategy",
            maximum_length=_MAX_DESCRIPTION_LENGTH,
        ),
        architecture_id=architecture_id,
        selected_design_alternative_id=selected_design_alternative_id,
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="test-plan requirement IDs",
            require_items=True,
        ),
        acceptance_criterion_ids=canonical_uuid_tuple(
            acceptance_criterion_ids,
            label="test-plan acceptance-criterion IDs",
            require_items=True,
        ),
        architecture_component_ids=canonical_uuid_tuple(
            architecture_component_ids,
            label="test-plan architecture-component IDs",
            require_items=True,
        ),
        environments=_canonical_coded_artifacts(
            environments,
            label="test environments",
            require_items=True,
        ),
        test_cases=_canonical_coded_artifacts(
            test_cases,
            label="planned test cases",
            require_items=True,
        ),
        quality_gates=_canonical_coded_artifacts(
            quality_gates,
            label="quality gates",
            require_items=True,
        ),
        fixtures=normalize_text_items(
            fixtures,
            label="test-plan fixtures",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ),
        assumptions=normalize_text_items(
            assumptions,
            label="test-plan assumptions",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ),
        open_questions=normalize_text_items(
            open_questions,
            label="test-plan open questions",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ),
    )


__all__ = [
    "PlannedTestCase",
    "QualityGate",
    "TestAutomation",
    "TestEnvironment",
    "TestEnvironmentKind",
    "TestLevel",
    "TestPlan",
    "TestPriority",
    "create_planned_test_case",
    "create_quality_gate",
    "create_test_environment",
    "create_test_plan",
]
