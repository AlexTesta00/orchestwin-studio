"""Tests for deterministic mandatory and impossible team rules."""

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    ALWAYS_PRESENT_AGENT_IDS,
    AgentIdentifier,
    all_agent_catalog_entries,
)
from orchestwin.agents.selection_rules import (
    TeamRoleConstraintKind,
    TeamSelectionIssueCode,
    TeamSelectionReasonCode,
    determine_team_constraints,
)
from orchestwin.projects.briefs import (
    BriefField,
    create_project_brief,
)
from orchestwin.projects.domain import (
    ProjectMode,
)


def test_constraints_cover_complete_catalog_in_stable_order() -> None:
    """Return one deterministic constraint for every fixed role."""
    constraints = determine_team_constraints(
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=create_project_brief(name="Project"),
    )

    assert tuple(constraint.agent_id for constraint in constraints.role_constraints) == tuple(
        entry.agent_id for entry in all_agent_catalog_entries()
    )

    assert constraints.catalog_version == (AGENT_CATALOG_VERSION)
    assert constraints.catalog_content_hash == (AGENT_CATALOG_CONTENT_HASH)


def test_platform_and_core_ucd_roles_are_mandatory() -> None:
    """Require governance, UCD, architecture, and quality disciplines."""
    brief = create_project_brief(
        name="Project",
        unknown_fields=[field for field in BriefField if field is not BriefField.NAME],
    )

    constraints = determine_team_constraints(
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=brief,
    )

    assert constraints.mandatory_agent_ids == (
        *ALWAYS_PRESENT_AGENT_IDS,
        AgentIdentifier.REQUIREMENTS_ANALYST,
        AgentIdentifier.UX_RESEARCHER_USER_MODELER,
        AgentIdentifier.SOFTWARE_ARCHITECT,
        AgentIdentifier.QA_TEST_ENGINEER,
    )

    assert AgentIdentifier.UX_UI_DESIGNER in constraints.optional_agent_ids
    assert AgentIdentifier.FRONTEND_ENGINEER in constraints.optional_agent_ids
    assert AgentIdentifier.BACKEND_ENGINEER in constraints.optional_agent_ids
    assert constraints.has_conflicts is False


def test_web_backend_security_accessibility_and_integration_signals() -> None:
    """Mandate specialists supported by explicit Project Brief evidence."""
    brief = create_project_brief(
        name="Accessible dashboard",
        description=("An accessible web application with a browser dashboard."),
        technical_constraints=[
            "Vue frontend",
            "FastAPI backend",
            "PostgreSQL database",
            "WCAG 2.2 AA",
        ],
        functional_requirements=[
            "Users log in with a password.",
            ("Synchronize weather data from an external API provider."),
        ],
    )

    constraints = determine_team_constraints(
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=brief,
    )

    expected_signal_roles = {
        AgentIdentifier.UX_UI_DESIGNER,
        AgentIdentifier.FRONTEND_ENGINEER,
        AgentIdentifier.BACKEND_ENGINEER,
        AgentIdentifier.SECURITY_REVIEWER,
        AgentIdentifier.ACCESSIBILITY_REVIEWER,
        AgentIdentifier.INTEGRATION_ENGINEER,
    }

    assert expected_signal_roles.issubset(set(constraints.mandatory_agent_ids))
    assert constraints.has_conflicts is False

    frontend_constraint = constraints.constraint_for(AgentIdentifier.FRONTEND_ENGINEER)
    frontend_reason = next(
        reason
        for reason in frontend_constraint.reasons
        if (reason.code is TeamSelectionReasonCode.WEB_DELIVERY_SIGNAL)
    )

    assert BriefField.TECHNICAL_CONSTRAINTS in frontend_reason.evidence.fields
    assert "vue" in (frontend_reason.evidence.terms)
    assert "frontend" in (frontend_reason.evidence.terms)


def test_mobile_delivery_mandates_designer_and_mobile_engineer() -> None:
    """Select the mobile delivery roles from explicit stack signals."""
    brief = create_project_brief(
        name="Mobile application",
        description=("A mobile app for Android users."),
        technical_constraints=[
            "Kotlin",
            "Jetpack Compose",
        ],
    )

    constraints = determine_team_constraints(
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=brief,
    )

    assert AgentIdentifier.UX_UI_DESIGNER in constraints.mandatory_agent_ids
    assert AgentIdentifier.MOBILE_ENGINEER in constraints.mandatory_agent_ids
    assert AgentIdentifier.FRONTEND_ENGINEER in constraints.optional_agent_ids


def test_explicit_scope_exclusions_mark_roles_impossible() -> None:
    """Respect explicit exclusions without inventing positive signals."""
    brief = create_project_brief(
        name="Headless service",
        description=(
            "A headless API only service with no frontend, no mobile, and no external integrations."
        ),
        technical_constraints=[
            "Backend only",
        ],
    )

    constraints = determine_team_constraints(
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=brief,
    )

    assert AgentIdentifier.BACKEND_ENGINEER in constraints.mandatory_agent_ids

    expected_impossible_roles = {
        AgentIdentifier.UX_UI_DESIGNER,
        AgentIdentifier.FRONTEND_ENGINEER,
        AgentIdentifier.MOBILE_ENGINEER,
        AgentIdentifier.ACCESSIBILITY_REVIEWER,
        AgentIdentifier.INTEGRATION_ENGINEER,
    }

    assert expected_impossible_roles.issubset(set(constraints.impossible_agent_ids))
    assert constraints.has_conflicts is False

    frontend_constraint = constraints.constraint_for(AgentIdentifier.FRONTEND_ENGINEER)

    assert frontend_constraint.kind is (TeamRoleConstraintKind.IMPOSSIBLE)
    assert frontend_constraint.reasons[0].code is (TeamSelectionReasonCode.EXPLICIT_SCOPE_EXCLUSION)


def test_true_positive_and_negative_signals_produce_conflict() -> None:
    """Expose contradictory owner input instead of choosing silently."""
    brief = create_project_brief(
        name="Contradictory project",
        description=("Use Vue for the frontend. The final product must have no frontend."),
    )

    constraints = determine_team_constraints(
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=brief,
    )

    frontend_constraint = constraints.constraint_for(AgentIdentifier.FRONTEND_ENGINEER)

    assert frontend_constraint.kind is (TeamRoleConstraintKind.CONFLICT)
    assert constraints.conflicting_agent_ids == (AgentIdentifier.FRONTEND_ENGINEER,)
    assert constraints.has_conflicts is True
    assert constraints.issues[0].code is (TeamSelectionIssueCode.CONTRADICTORY_ROLE_SIGNALS)


def test_negated_role_name_does_not_count_as_positive_evidence() -> None:
    """Remove exclusion phrases before matching positive markers."""
    brief = create_project_brief(
        name="Backend service",
        description=("No frontend is required."),
    )

    constraints = determine_team_constraints(
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=brief,
    )

    frontend_constraint = constraints.constraint_for(AgentIdentifier.FRONTEND_ENGINEER)

    assert frontend_constraint.kind is (TeamRoleConstraintKind.IMPOSSIBLE)
    assert frontend_constraint.agent_id not in constraints.conflicting_agent_ids


def test_brownfield_requires_integration_engineer() -> None:
    """Require controlled integration for an existing system."""
    brief = create_project_brief(
        name="Existing system",
        description=("Assess an existing codebase with no external integrations."),
    )

    constraints = determine_team_constraints(
        project_mode=(ProjectMode.BROWNFIELD_ASSESSMENT),
        brief=brief,
    )

    integration_constraint = constraints.constraint_for(AgentIdentifier.INTEGRATION_ENGINEER)

    assert integration_constraint.kind is (TeamRoleConstraintKind.MANDATORY)
    assert any(
        reason.code is TeamSelectionReasonCode.BROWNFIELD_INTEGRATION
        for reason in integration_constraint.reasons
    )
    assert AgentIdentifier.INTEGRATION_ENGINEER not in constraints.conflicting_agent_ids


def test_missing_and_unknown_fields_do_not_create_signals() -> None:
    """Use only values actually provided by the project owner."""
    brief = create_project_brief(
        name="Project",
        unknown_fields=[
            BriefField.TECHNICAL_CONSTRAINTS,
            BriefField.FUNCTIONAL_REQUIREMENTS,
            BriefField.NON_FUNCTIONAL_REQUIREMENTS,
        ],
    )

    constraints = determine_team_constraints(
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=brief,
    )

    signal_roles = {
        AgentIdentifier.UX_UI_DESIGNER,
        AgentIdentifier.FRONTEND_ENGINEER,
        AgentIdentifier.BACKEND_ENGINEER,
        AgentIdentifier.MOBILE_ENGINEER,
        AgentIdentifier.SECURITY_REVIEWER,
        AgentIdentifier.ACCESSIBILITY_REVIEWER,
        AgentIdentifier.INTEGRATION_ENGINEER,
    }

    assert signal_roles.issubset(set(constraints.optional_agent_ids))


def test_constraint_snapshot_and_hash_are_deterministic() -> None:
    """Produce stable input for future typed team proposals."""
    brief = create_project_brief(
        name="Web project",
        description=("A Vue web application with a PostgreSQL backend."),
    )

    first = determine_team_constraints(
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=brief,
    )
    second = determine_team_constraints(
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=brief,
    )

    assert first == second
    assert first.to_snapshot() == (second.to_snapshot())
    assert first.canonical_json() == (second.canonical_json())
    assert first.content_hash == (second.content_hash)
    assert len(first.content_hash) == 64
    assert all(character in "0123456789abcdef" for character in first.content_hash)
