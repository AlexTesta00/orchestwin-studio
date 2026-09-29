"""Tests for deterministic mandatory and impossible team rules."""

from dataclasses import replace

import pytest

from orchestwin.agents import selection_rules
from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    ALWAYS_PRESENT_AGENT_IDS,
    AgentIdentifier,
    all_agent_catalog_entries,
    catalog_entry,
)
from orchestwin.agents.selection_rules import (
    RuleEvidence,
    TeamRoleConstraintKind,
    TeamSelectionIssueCode,
    TeamSelectionReason,
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

DESIGN_STEP_CORE_REASONS = {
    AgentIdentifier.UX_UI_DESIGNER: TeamSelectionReasonCode.CORE_USER_CENTERED_DESIGN,
    AgentIdentifier.ACCESSIBILITY_REVIEWER: TeamSelectionReasonCode.CORE_ACCESSIBILITY_DISCIPLINE,
}
DESIGN_STEP_SIGNAL_REASONS = {
    AgentIdentifier.UX_UI_DESIGNER: TeamSelectionReasonCode.USER_INTERFACE_SIGNAL,
    AgentIdentifier.ACCESSIBILITY_REVIEWER: (
        TeamSelectionReasonCode.ACCESSIBILITY_REQUIREMENT_SIGNAL
    ),
}
NIGHTLY_JOB = "A nightly job that reconciles supplier invoices."
SERVICE_WITHOUT_INTERFACE = "Un servizio senza interfaccia che riconcilia le fatture."
BRIEF_CASES = {
    "interface words": (
        {"description": "A web application with a dashboard and HTML screens."},
        RuleEvidence(
            fields=(BriefField.DESCRIPTION,),
            terms=("dashboard", "html", "screens", "web application"),
        ),
        None,
    ),
    "no interface words": ({"description": NIGHTLY_JOB}, None, None),
    "senza interfaccia": ({"description": SERVICE_WITHOUT_INTERFACE}, None, None),
    "api only": ({"technical_constraints": ["API only", "PostgreSQL database"]}, None, None),
    "accessibility asked": (
        {
            "description": NIGHTLY_JOB,
            "non_functional_requirements": ["WCAG 2.2 AA", "Keyboard navigation for every action"],
        },
        None,
        RuleEvidence(
            fields=(BriefField.NON_FUNCTIONAL_REQUIREMENTS,),
            terms=("keyboard navigation", "wcag"),
        ),
    ),
    "accessibility without interface": (
        {
            "description": SERVICE_WITHOUT_INTERFACE,
            "non_functional_requirements": ["WCAG 2.2 AA"],
        },
        None,
        RuleEvidence(fields=(BriefField.NON_FUNCTIONAL_REQUIREMENTS,), terms=("wcag",)),
    ),
    "interface and headless": (
        {"description": "Use HTML screens, but the final product must be headless."},
        RuleEvidence(fields=(BriefField.DESCRIPTION,), terms=("html", "screens")),
        None,
    ),
}


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
        AgentIdentifier.UX_UI_DESIGNER,
        AgentIdentifier.SOFTWARE_ARCHITECT,
        AgentIdentifier.QA_TEST_ENGINEER,
        AgentIdentifier.ACCESSIBILITY_REVIEWER,
    )

    assert constraints.optional_agent_ids == (
        AgentIdentifier.FRONTEND_ENGINEER,
        AgentIdentifier.BACKEND_ENGINEER,
        AgentIdentifier.MOBILE_ENGINEER,
        AgentIdentifier.SECURITY_REVIEWER,
        AgentIdentifier.INTEGRATION_ENGINEER,
    )
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
    assert AgentIdentifier.UX_UI_DESIGNER in constraints.mandatory_agent_ids
    assert AgentIdentifier.ACCESSIBILITY_REVIEWER in constraints.mandatory_agent_ids

    expected_impossible_roles = {
        AgentIdentifier.FRONTEND_ENGINEER,
        AgentIdentifier.MOBILE_ENGINEER,
        AgentIdentifier.INTEGRATION_ENGINEER,
    }

    assert set(constraints.impossible_agent_ids) == expected_impossible_roles
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
        AgentIdentifier.FRONTEND_ENGINEER,
        AgentIdentifier.BACKEND_ENGINEER,
        AgentIdentifier.MOBILE_ENGINEER,
        AgentIdentifier.SECURITY_REVIEWER,
        AgentIdentifier.INTEGRATION_ENGINEER,
    }

    assert signal_roles.issubset(set(constraints.optional_agent_ids))

    for agent_id in DESIGN_STEP_CORE_REASONS:
        assert constraints.constraint_for(agent_id).reasons == (
            TeamSelectionReason(code=DESIGN_STEP_CORE_REASONS[agent_id]),
        )


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


def test_italian_static_web_scope_keeps_designer_and_excludes_backend():
    constraints = determine_team_constraints(
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        brief=create_project_brief(
            name="Calcolatrice web accessibile",
            technical_constraints=["WEB_STATIC: HTML CSS JavaScript", "Nessun backend o database"],
            functional_requirements=["Tutte le azioni da tastiera"],
        ),
    )
    assert not constraints.has_conflicts
    assert AgentIdentifier.UX_UI_DESIGNER in constraints.mandatory_agent_ids
    assert AgentIdentifier.ACCESSIBILITY_REVIEWER in constraints.mandatory_agent_ids
    assert AgentIdentifier.BACKEND_ENGINEER in constraints.impossible_agent_ids


@pytest.mark.parametrize("project_mode", tuple(ProjectMode))
@pytest.mark.parametrize(
    ("brief_fields", "interface_evidence", "accessibility_evidence"),
    tuple(BRIEF_CASES.values()),
    ids=tuple(BRIEF_CASES),
)
def test_designer_and_accessibility_specialist_are_in_every_team_whatever_the_brief_says(
    project_mode: ProjectMode,
    brief_fields: dict[str, object],
    interface_evidence: RuleEvidence | None,
    accessibility_evidence: RuleEvidence | None,
) -> None:
    constraints = determine_team_constraints(
        project_mode=project_mode,
        brief=create_project_brief(name="Project", **brief_fields),
    )

    for agent_id, signal_evidence in (
        (AgentIdentifier.UX_UI_DESIGNER, interface_evidence),
        (AgentIdentifier.ACCESSIBILITY_REVIEWER, accessibility_evidence),
    ):
        constraint = constraints.constraint_for(agent_id)
        expected_reasons = (TeamSelectionReason(code=DESIGN_STEP_CORE_REASONS[agent_id]),)

        if signal_evidence is not None:
            expected_reasons = (
                *expected_reasons,
                TeamSelectionReason(
                    code=DESIGN_STEP_SIGNAL_REASONS[agent_id],
                    evidence=signal_evidence,
                ),
            )

        assert project_mode in catalog_entry(agent_id).supported_project_modes
        assert constraint.kind is TeamRoleConstraintKind.MANDATORY
        assert constraint.reasons == expected_reasons
        assert constraint.owner_editable is False
        assert agent_id not in constraints.impossible_agent_ids
        assert agent_id not in constraints.conflicting_agent_ids
        assert all(issue.agent_id is not agent_id for issue in constraints.issues)


def test_words_of_exclusion_keep_their_effect_on_every_other_role() -> None:
    constraints = determine_team_constraints(
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        brief=create_project_brief(
            name="Headless service",
            description="Use HTML screens, but the final product must be headless.",
            technical_constraints=["No mobile", "No external integrations", "Nessun backend"],
        ),
    )

    frontend = constraints.constraint_for(AgentIdentifier.FRONTEND_ENGINEER)

    assert constraints.conflicting_agent_ids == (AgentIdentifier.FRONTEND_ENGINEER,)
    assert [reason.code for reason in frontend.reasons] == [
        TeamSelectionReasonCode.WEB_DELIVERY_SIGNAL,
        TeamSelectionReasonCode.EXPLICIT_SCOPE_EXCLUSION,
    ]
    assert constraints.impossible_agent_ids == (
        AgentIdentifier.BACKEND_ENGINEER,
        AgentIdentifier.MOBILE_ENGINEER,
        AgentIdentifier.INTEGRATION_ENGINEER,
    )
    for agent_id in constraints.impossible_agent_ids:
        assert [reason.code for reason in constraints.constraint_for(agent_id).reasons] == [
            TeamSelectionReasonCode.EXPLICIT_SCOPE_EXCLUSION
        ]
    assert set(DESIGN_STEP_CORE_REASONS).issubset(constraints.mandatory_agent_ids)


def test_mode_that_a_specialist_does_not_support_keeps_the_rule_of_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = tuple(
        replace(entry, supported_project_modes=frozenset({ProjectMode.GREENFIELD_GENERATION}))
        if entry.agent_id in DESIGN_STEP_CORE_REASONS
        else entry
        for entry in all_agent_catalog_entries()
    )
    monkeypatch.setattr(selection_rules, "all_agent_catalog_entries", lambda: entries)

    def constraint_for(
        agent_id: AgentIdentifier,
        project_mode: ProjectMode,
        description: str | None = None,
    ):
        return determine_team_constraints(
            project_mode=project_mode,
            brief=create_project_brief(name="Project", description=description),
        ).constraint_for(agent_id)

    unsupported = ProjectMode.BROWNFIELD_ASSESSMENT
    plain = constraint_for(AgentIdentifier.ACCESSIBILITY_REVIEWER, unsupported)
    interface = constraint_for(
        AgentIdentifier.UX_UI_DESIGNER, unsupported, "A dashboard with HTML screens."
    )
    headless = constraint_for(AgentIdentifier.UX_UI_DESIGNER, unsupported, "A headless service.")
    supported = constraint_for(
        AgentIdentifier.UX_UI_DESIGNER,
        ProjectMode.GREENFIELD_GENERATION,
        "A headless service.",
    )

    assert plain.kind is TeamRoleConstraintKind.IMPOSSIBLE
    assert [reason.code for reason in plain.reasons] == [
        TeamSelectionReasonCode.CATALOG_MODE_INCOMPATIBLE
    ]
    assert interface.kind is TeamRoleConstraintKind.CONFLICT
    assert [reason.code for reason in interface.reasons] == [
        TeamSelectionReasonCode.USER_INTERFACE_SIGNAL,
        TeamSelectionReasonCode.CATALOG_MODE_INCOMPATIBLE,
    ]
    assert headless.kind is TeamRoleConstraintKind.IMPOSSIBLE
    assert [reason.code for reason in headless.reasons] == [
        TeamSelectionReasonCode.CATALOG_MODE_INCOMPATIBLE,
        TeamSelectionReasonCode.EXPLICIT_SCOPE_EXCLUSION,
    ]
    assert supported.kind is TeamRoleConstraintKind.MANDATORY
    assert supported.reasons == (
        TeamSelectionReason(code=TeamSelectionReasonCode.CORE_USER_CENTERED_DESIGN),
    )
