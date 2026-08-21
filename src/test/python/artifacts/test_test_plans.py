"""Tests for immutable architecture-stage test plans."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.artifacts.test_plans import (
    TestAutomation as AutomationMode,
)
from orchestwin.artifacts.test_plans import (
    TestEnvironmentKind as EnvironmentKind,
)
from orchestwin.artifacts.test_plans import (
    TestLevel as PlanTestLevel,
)
from orchestwin.artifacts.test_plans import (
    TestPriority as PlanTestPriority,
)
from orchestwin.artifacts.test_plans import (
    create_planned_test_case,
    create_quality_gate,
    create_test_environment,
    create_test_plan,
)

REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000010")
CRITERION_ID = UUID("00000000-0000-4000-8000-000000000020")
ALTERNATIVE_ID = UUID("00000000-0000-4000-8000-000000000030")
ARCHITECTURE_ID = UUID("00000000-0000-4000-8000-000000000040")
COMPONENT_ID = UUID("00000000-0000-4000-8000-000000000050")
ENVIRONMENT_ID = UUID("00000000-0000-4000-8000-000000000060")
TEST_CASE_ID = UUID("00000000-0000-4000-8000-000000000070")
QUALITY_GATE_ID = UUID("00000000-0000-4000-8000-000000000080")
PLAN_ID = UUID("00000000-0000-4000-8000-000000000090")


def environment():
    """Create one portable browser test environment."""
    return create_test_environment(
        environment_id=ENVIRONMENT_ID,
        code="ENV-001",
        name="Headless browser",
        kind=EnvironmentKind.BROWSER,
        description="A controlled browser environment with no external network access.",
        configuration=("Viewport 1280x720",),
    )


def planned_test_case():
    """Create one end-to-end acceptance test."""
    return create_planned_test_case(
        test_case_id=TEST_CASE_ID,
        code="TST-001",
        title="Create a reservation",
        objective="Verify the approved reservation workflow and visible completion state.",
        level=PlanTestLevel.END_TO_END,
        automation=AutomationMode.AUTOMATED,
        priority=PlanTestPriority.CRITICAL,
        preconditions=("The application is running.",),
        steps=("Open the reservation screen.", "Submit valid reservation data."),
        expected_results=("The reservation appears in the current status.",),
        requirement_ids=(REQUIREMENT_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
        architecture_component_ids=(COMPONENT_ID,),
        design_alternative_ids=(ALTERNATIVE_ID,),
        environment_ids=(ENVIRONMENT_ID,),
    )


def quality_gate():
    """Create one blocking release condition."""
    return create_quality_gate(
        gate_id=QUALITY_GATE_ID,
        code="QGT-001",
        title="Acceptance suite",
        criterion="All critical acceptance tests pass.",
        required_test_case_ids=(TEST_CASE_ID,),
        minimum_pass_rate=100,
        blocking=True,
    )


def plan():
    """Create one complete test plan."""
    return create_test_plan(
        plan_id=PLAN_ID,
        code="TPL-001",
        title="Reservation test plan",
        strategy="Verify the selected workflow through layered deterministic checks.",
        architecture_id=ARCHITECTURE_ID,
        selected_design_alternative_id=ALTERNATIVE_ID,
        requirement_ids=(REQUIREMENT_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
        architecture_component_ids=(COMPONENT_ID,),
        environments=(environment(),),
        test_cases=(planned_test_case(),),
        quality_gates=(quality_gate(),),
        fixtures=("Minimal reservation fixture",),
    )


def test_plan_is_traceable_canonical_and_hashable() -> None:
    """Create a deterministic test plan with exact stage links."""
    value = plan()

    assert value.architecture_id == ARCHITECTURE_ID
    assert value.selected_design_alternative_id == ALTERNATIVE_ID
    assert value.test_cases[0].requirement_ids == (REQUIREMENT_ID,)
    assert len(value.content_hash) == 64


def test_plan_requires_complete_requirement_coverage() -> None:
    """Reject approved requirements that have no planned verification."""
    uncovered = UUID("00000000-0000-4000-8000-000000000099")

    with pytest.raises(ValueError, match="cover every approved requirement"):
        replace(plan(), requirement_ids=(REQUIREMENT_ID, uncovered))


def test_plan_requires_complete_acceptance_criterion_coverage() -> None:
    """Reject approved criteria that have no planned verification."""
    uncovered = UUID("00000000-0000-4000-8000-000000000099")

    with pytest.raises(ValueError, match="cover every approved acceptance criterion"):
        replace(plan(), acceptance_criterion_ids=(CRITERION_ID, uncovered))


def test_planned_test_must_reference_only_selected_design() -> None:
    """Prevent tests from silently targeting a rejected design direction."""
    other = UUID("00000000-0000-4000-8000-000000000099")
    invalid = replace(planned_test_case(), design_alternative_ids=(other,))

    with pytest.raises(ValueError, match="only the selected design alternative"):
        replace(plan(), test_cases=(invalid,))


def test_quality_gate_rejects_unknown_test_case() -> None:
    """Keep quality gates resolvable to planned checks."""
    unknown = UUID("00000000-0000-4000-8000-000000000099")
    invalid = replace(quality_gate(), required_test_case_ids=(unknown,))

    with pytest.raises(ValueError, match="unknown test-case references"):
        replace(plan(), quality_gates=(invalid,))


def test_quality_gate_pass_rate_is_bounded() -> None:
    """Reject impossible deterministic thresholds."""
    with pytest.raises(ValueError, match="between 0 and 100"):
        replace(quality_gate(), minimum_pass_rate=101)


def test_equal_test_plans_have_equal_snapshots_and_hashes() -> None:
    """Keep test-plan artifacts reproducible."""
    first = plan()
    second = plan()

    assert first.to_snapshot() == second.to_snapshot()
    assert first.canonical_json() == second.canonical_json()
    assert first.content_hash == second.content_hash
