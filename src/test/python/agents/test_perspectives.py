from __future__ import annotations

import json
from dataclasses import replace

import pytest

from orchestwin.agents.catalog import (
    ALWAYS_PRESENT_AGENT_IDS,
    SELECTABLE_SPECIALIST_AGENT_IDS,
    AgentIdentifier,
)
from orchestwin.agents.perspectives import (
    ASPECT_AGENT_IDS,
    ASPECT_ORDER,
    PERSPECTIVE_AGENT_IDS,
    PERSPECTIVE_ORDER,
    SWITCHABLE_PERSPECTIVE_AGENT_IDS,
    GuidanceStage,
    Perspective,
    PerspectiveAspect,
    PerspectiveStanding,
    perspective_guidance,
    perspective_views,
)
from orchestwin.agents.selection_rules import (
    DeterministicTeamConstraints,
    RuleEvidence,
    TeamRoleConstraint,
    TeamRoleConstraintKind,
    TeamSelectionReason,
    TeamSelectionReasonCode,
    determine_team_constraints,
)
from orchestwin.projects.briefs import BriefField, create_project_brief
from orchestwin.projects.domain import ProjectMode

EMPTY = {"fields": [], "terms": []}
MINIMUM_TEAM = (
    AgentIdentifier.REQUIREMENTS_ANALYST,
    AgentIdentifier.UX_RESEARCHER_USER_MODELER,
    AgentIdentifier.UX_UI_DESIGNER,
    AgentIdentifier.SOFTWARE_ARCHITECT,
    AgentIdentifier.QA_TEST_ENGINEER,
    AgentIdentifier.ACCESSIBILITY_REVIEWER,
)
SWITCH_AGENTS = (
    AgentIdentifier.FRONTEND_ENGINEER,
    AgentIdentifier.BACKEND_ENGINEER,
    AgentIdentifier.MOBILE_ENGINEER,
    AgentIdentifier.INTEGRATION_ENGINEER,
    AgentIdentifier.SECURITY_REVIEWER,
)
CONTRADICTION = "Una app con database ma senza backend."
CONTRACT_BRIEF = {
    "description": "Runs in the browser, senza server, no integrations.",
    "technical_constraints": ["An api for the data"],
}
CONTRACT_SOFTWARE_ENGINEERING = {
    "key": "SOFTWARE_ENGINEERING",
    "standing": "ALWAYS",
    "applied": True,
    "editable": False,
    "agent_id": None,
    "requested": {"fields": [], "terms": []},
    "excluded": {"fields": [], "terms": []},
    "aspects": [
        {
            "key": "WEB",
            "agent_id": "FRONTEND_ENGINEER",
            "standing": "REQUIRED",
            "applied": True,
            "editable": False,
            "requested": {"fields": ["description"], "terms": ["browser"]},
            "excluded": {"fields": [], "terms": []},
        },
        {
            "key": "SERVICES",
            "agent_id": "BACKEND_ENGINEER",
            "standing": "CONTESTED",
            "applied": False,
            "editable": True,
            "requested": {"fields": ["technical_constraints"], "terms": ["api"]},
            "excluded": {"fields": ["description"], "terms": ["senza server"]},
        },
        {
            "key": "MOBILE",
            "agent_id": "MOBILE_ENGINEER",
            "standing": "OPTIONAL",
            "applied": False,
            "editable": True,
            "requested": {"fields": [], "terms": []},
            "excluded": {"fields": [], "terms": []},
        },
        {
            "key": "INTEGRATIONS",
            "agent_id": "INTEGRATION_ENGINEER",
            "standing": "EXCLUDED",
            "applied": False,
            "editable": False,
            "requested": {"fields": [], "terms": []},
            "excluded": {"fields": ["description"], "terms": ["no integrations"]},
        },
    ],
}
DEFINITION_GUIDANCE = [
    {
        "perspective": "UX",
        "considerations": [
            "Write each user story and scenario from the point of view of one twin: the goal, "
            "the context of use and the moment where that person may get stuck.",
            "Each functional requirement serves a need of a twin or of the brief and says what "
            "the person sees after acting.",
        ],
    },
    {
        "perspective": "ACCESSIBILITY",
        "considerations": [
            "State as requirements or acceptance criteria the accessibility needs that this "
            "project implies: use from the keyboard, readable contrast and text size, names for "
            "controls and images, messages that say in words what went wrong.",
            "When a twin has a limitation or a context that makes the interface harder to use, "
            "at least one acceptance criterion covers it.",
        ],
    },
    {
        "perspective": "SOFTWARE_ENGINEERING",
        "considerations": [
            "Keep every requirement feasible within the technical constraints, the time and the "
            "budget of the brief, and name as a risk what may not be.",
            "Write acceptance criteria that can be checked by using the application, each with "
            "one observable outcome.",
            "The application runs in a browser: cover the window sizes it must work at and what "
            "the person sees while content loads or fails to load.",
            "The application keeps data or logic on a server: say which data are kept and what "
            "the person sees when the service does not answer or refuses.",
            "The application is used on a phone or a tablet: cover touch use, small screens and "
            "a connection that comes and goes.",
            "The application depends on other systems: say which data cross the boundary and "
            "what the person sees when the other system fails.",
        ],
    },
    {
        "perspective": "PRODUCT",
        "considerations": [
            "Give each requirement the priority that the brief supports: what the first usable "
            "version must have and what can wait.",
            "Keep out what the brief leaves out, and name as a risk any assumption about value "
            "that nobody has verified.",
        ],
    },
    {
        "perspective": "SECURITY",
        "considerations": [
            "Name the data and the actions that need protection and who may see or do them; add "
            "requirements for access, session and data protection only where the brief implies "
            "them.",
            "Cover with an acceptance criterion what happens after wrong credentials, an expired "
            "session or an action that is not allowed.",
        ],
    },
]
DESIGN_GUIDANCE = [
    {
        "perspective": "UX",
        "considerations": [
            "Each alternative lets every twin reach their main goal in few steps, shows the "
            "result of each action and lets the person undo or correct a mistake.",
            "The alternatives differ in how the person works, not only in how they look.",
        ],
    },
    {
        "perspective": "ACCESSIBILITY",
        "considerations": [
            "In each alternative every action is reachable from the keyboard with a visible "
            "focus, text keeps a readable contrast and no information depends on colour alone.",
            "Controls and fields have a visible name, and errors are explained in words next to "
            "the field.",
        ],
    },
    {
        "perspective": "SOFTWARE_ENGINEERING",
        "considerations": [
            "Each alternative can be built within the technical constraints of the brief; name "
            "what would be costly to build.",
            "Each screen has its empty, loading and error states.",
            "Layouts adapt from a phone-wide window to a desktop one.",
            "Show what the person sees while data are being saved or fetched and when that fails.",
            "Controls are large enough for touch and the main actions are reachable with one hand.",
            "Show the state of each connection to another system and what the person can do when "
            "it is unavailable.",
        ],
    },
    {
        "perspective": "PRODUCT",
        "considerations": [
            "Say for each alternative which goal of the brief it serves best and what it gives up.",
            "Do not add screens or functions that no requirement asks for.",
        ],
    },
    {
        "perspective": "SECURITY",
        "considerations": [
            "Show how the person knows they are signed in and how they sign out, and ask for "
            "confirmation before an action that destroys data.",
            "Do not show sensitive data in full where a part is enough.",
        ],
    },
]
FULL_GUIDANCE = {
    GuidanceStage.DEFINITION: DEFINITION_GUIDANCE,
    GuidanceStage.DESIGN: DESIGN_GUIDANCE,
}


def constraints_for(
    project_mode: ProjectMode = ProjectMode.GREENFIELD_GENERATION,
    **fields: object,
) -> DeterministicTeamConstraints:
    return determine_team_constraints(
        project_mode=project_mode,
        brief=create_project_brief(name="Project", **fields),
    )


def snapshots_for(
    project_mode: ProjectMode = ProjectMode.GREENFIELD_GENERATION,
    **fields: object,
) -> dict[str, dict[str, object]]:
    constraints = constraints_for(project_mode, **fields)

    return {
        view.key.value: view.to_snapshot()
        for view in perspective_views(constraints, constraints.mandatory_agent_ids)
    }


def units_of(
    snapshots: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    aspects = snapshots["SOFTWARE_ENGINEERING"]["aspects"]

    assert isinstance(aspects, list)

    return {
        **{aspect["key"]: aspect for aspect in aspects},
        "SECURITY": snapshots["SECURITY"],
    }


def test_the_perspectives_cover_the_eleven_specialists_once_and_no_platform_component() -> None:
    agents = [
        *(
            agent_id
            for perspective in PERSPECTIVE_ORDER
            for agent_id in PERSPECTIVE_AGENT_IDS[perspective]
        ),
        *(ASPECT_AGENT_IDS[aspect] for aspect in ASPECT_ORDER),
    ]

    assert len(agents) == 11
    assert sorted(agents) == sorted(SELECTABLE_SPECIALIST_AGENT_IDS)
    assert set(agents).isdisjoint(ALWAYS_PRESENT_AGENT_IDS)
    assert dict(PERSPECTIVE_AGENT_IDS) == {
        Perspective.UX: (
            AgentIdentifier.UX_RESEARCHER_USER_MODELER,
            AgentIdentifier.UX_UI_DESIGNER,
        ),
        Perspective.ACCESSIBILITY: (AgentIdentifier.ACCESSIBILITY_REVIEWER,),
        Perspective.SOFTWARE_ENGINEERING: (
            AgentIdentifier.SOFTWARE_ARCHITECT,
            AgentIdentifier.QA_TEST_ENGINEER,
        ),
        Perspective.PRODUCT: (AgentIdentifier.REQUIREMENTS_ANALYST,),
        Perspective.SECURITY: (AgentIdentifier.SECURITY_REVIEWER,),
    }
    assert dict(ASPECT_AGENT_IDS) == {
        PerspectiveAspect.WEB: AgentIdentifier.FRONTEND_ENGINEER,
        PerspectiveAspect.SERVICES: AgentIdentifier.BACKEND_ENGINEER,
        PerspectiveAspect.MOBILE: AgentIdentifier.MOBILE_ENGINEER,
        PerspectiveAspect.INTEGRATIONS: AgentIdentifier.INTEGRATION_ENGINEER,
    }
    assert dict(SWITCHABLE_PERSPECTIVE_AGENT_IDS) == {
        Perspective.SECURITY: AgentIdentifier.SECURITY_REVIEWER
    }


def test_keys_and_orders_follow_the_contract() -> None:
    assert [perspective.value for perspective in PERSPECTIVE_ORDER] == [
        "UX",
        "ACCESSIBILITY",
        "SOFTWARE_ENGINEERING",
        "PRODUCT",
        "SECURITY",
    ]
    assert [aspect.value for aspect in ASPECT_ORDER] == [
        "WEB",
        "SERVICES",
        "MOBILE",
        "INTEGRATIONS",
    ]
    assert tuple(Perspective) == PERSPECTIVE_ORDER
    assert tuple(PerspectiveAspect) == ASPECT_ORDER
    assert [standing.value for standing in PerspectiveStanding] == [
        "ALWAYS",
        "REQUIRED",
        "OPTIONAL",
        "EXCLUDED",
        "CONTESTED",
    ]
    assert [stage.value for stage in GuidanceStage] == ["DEFINITION", "DESIGN"]

    for enumeration in (Perspective, PerspectiveAspect, PerspectiveStanding, GuidanceStage):
        assert all(member.value == member.name for member in enumeration)


def test_a_brief_without_signals_applies_four_perspectives_and_leaves_the_switches_off() -> None:
    snapshots = snapshots_for()

    assert list(snapshots) == [perspective.value for perspective in PERSPECTIVE_ORDER]

    for key in ("UX", "ACCESSIBILITY", "PRODUCT"):
        assert snapshots[key] == {
            "key": key,
            "standing": "ALWAYS",
            "applied": True,
            "editable": False,
            "agent_id": None,
            "requested": EMPTY,
            "excluded": EMPTY,
            "aspects": [],
        }

    assert snapshots["SOFTWARE_ENGINEERING"] == {
        "key": "SOFTWARE_ENGINEERING",
        "standing": "ALWAYS",
        "applied": True,
        "editable": False,
        "agent_id": None,
        "requested": EMPTY,
        "excluded": EMPTY,
        "aspects": [
            {
                "key": aspect.value,
                "agent_id": ASPECT_AGENT_IDS[aspect].value,
                "standing": "OPTIONAL",
                "applied": False,
                "editable": True,
                "requested": EMPTY,
                "excluded": EMPTY,
            }
            for aspect in ASPECT_ORDER
        ],
    }
    assert snapshots["SECURITY"] == {
        "key": "SECURITY",
        "standing": "OPTIONAL",
        "applied": False,
        "editable": True,
        "agent_id": "SECURITY_REVIEWER",
        "requested": EMPTY,
        "excluded": EMPTY,
        "aspects": [],
    }


@pytest.mark.parametrize(
    ("word", "unit"),
    (
        ("Vue", "WEB"),
        ("PostgreSQL", "SERVICES"),
        ("Kotlin", "MOBILE"),
        ("Webhook", "INTEGRATIONS"),
        ("Encryption", "SECURITY"),
    ),
)
def test_a_signal_makes_its_unit_required_with_the_words_of_the_brief(word: str, unit: str) -> None:
    units = units_of(snapshots_for(technical_constraints=[word]))

    assert units[unit]["standing"] == "REQUIRED"
    assert units[unit]["applied"] is True
    assert units[unit]["editable"] is False
    assert units[unit]["requested"] == {
        "fields": ["technical_constraints"],
        "terms": [word.casefold()],
    }
    assert units[unit]["excluded"] == EMPTY
    assert [other["standing"] for key, other in units.items() if key != unit] == ["OPTIONAL"] * 4


def test_an_exclusion_rules_its_unit_out_with_the_words_of_the_brief() -> None:
    units = units_of(snapshots_for(technical_constraints=["No mobile"]))

    assert units["MOBILE"] == {
        "key": "MOBILE",
        "agent_id": "MOBILE_ENGINEER",
        "standing": "EXCLUDED",
        "applied": False,
        "editable": False,
        "requested": EMPTY,
        "excluded": {"fields": ["technical_constraints"], "terms": ["no mobile"]},
    }


def test_a_contradiction_leaves_the_contested_unit_to_the_owner_with_both_groups_of_words() -> None:
    constraints = constraints_for(description=CONTRADICTION)
    proposed = perspective_views(constraints, constraints.mandatory_agent_ids)
    added = perspective_views(
        constraints,
        (*constraints.mandatory_agent_ids, AgentIdentifier.BACKEND_ENGINEER),
    )
    services = proposed[2].aspects[1]

    assert services.to_snapshot() == {
        "key": "SERVICES",
        "agent_id": "BACKEND_ENGINEER",
        "standing": "CONTESTED",
        "applied": False,
        "editable": True,
        "requested": {"fields": ["description"], "terms": ["database"]},
        "excluded": {"fields": ["description"], "terms": ["senza backend"]},
    }
    assert added[2].aspects[1] == replace(services, applied=True)
    assert added[:2] == proposed[:2]
    assert added[3:] == proposed[3:]


def test_brownfield_requires_the_integrations_aspect_whatever_the_brief_excludes() -> None:
    description = "Assess it with no external integrations."
    greenfield = units_of(snapshots_for(description=description))["INTEGRATIONS"]
    brownfield = units_of(snapshots_for(ProjectMode.BROWNFIELD_ASSESSMENT, description=description))

    assert greenfield["standing"] == "EXCLUDED"
    assert greenfield["excluded"] == {
        "fields": ["description"],
        "terms": ["no external integrations"],
    }
    assert brownfield["INTEGRATIONS"] == {
        "key": "INTEGRATIONS",
        "agent_id": "INTEGRATION_ENGINEER",
        "standing": "REQUIRED",
        "applied": True,
        "editable": False,
        "requested": EMPTY,
        "excluded": EMPTY,
    }
    assert brownfield["SECURITY"]["standing"] == "OPTIONAL"


@pytest.mark.parametrize("switched_on", (False, True))
def test_applied_follows_the_selection_and_editable_follows_the_standing(
    switched_on: bool,
) -> None:
    constraints = constraints_for(**CONTRACT_BRIEF)
    selected = (*MINIMUM_TEAM, *(SWITCH_AGENTS if switched_on else ()))
    views = perspective_views(constraints, selected)
    units = {
        **{aspect.key.value: aspect for aspect in views[2].aspects},
        "SECURITY": views[4],
    }

    assert {key: unit.standing for key, unit in units.items()} == {
        "WEB": PerspectiveStanding.REQUIRED,
        "SERVICES": PerspectiveStanding.CONTESTED,
        "MOBILE": PerspectiveStanding.OPTIONAL,
        "INTEGRATIONS": PerspectiveStanding.EXCLUDED,
        "SECURITY": PerspectiveStanding.OPTIONAL,
    }
    assert {key: unit.editable for key, unit in units.items()} == {
        "WEB": False,
        "SERVICES": True,
        "MOBILE": True,
        "INTEGRATIONS": False,
        "SECURITY": True,
    }
    assert all(unit.applied is switched_on for unit in units.values())
    assert [(view.standing, view.applied, view.editable) for view in views[:4]] == [
        (PerspectiveStanding.ALWAYS, True, False)
    ] * 4


@pytest.mark.parametrize(
    ("missing", "perspective"),
    (
        (AgentIdentifier.UX_UI_DESIGNER, Perspective.UX),
        (AgentIdentifier.UX_RESEARCHER_USER_MODELER, Perspective.UX),
        (AgentIdentifier.ACCESSIBILITY_REVIEWER, Perspective.ACCESSIBILITY),
        (AgentIdentifier.QA_TEST_ENGINEER, Perspective.SOFTWARE_ENGINEERING),
        (AgentIdentifier.REQUIREMENTS_ANALYST, Perspective.PRODUCT),
    ),
)
def test_a_perspective_always_applied_needs_every_one_of_its_agents(
    missing: AgentIdentifier,
    perspective: Perspective,
) -> None:
    constraints = constraints_for()
    selected = tuple(
        agent_id for agent_id in SELECTABLE_SPECIALIST_AGENT_IDS if agent_id != missing
    )
    views = perspective_views(constraints, selected)

    assert {view.key: view.applied for view in views} == {
        **dict.fromkeys(PERSPECTIVE_ORDER, True),
        perspective: False,
    }
    assert all(aspect.applied for aspect in views[2].aspects)
    assert all(view.standing is PerspectiveStanding.ALWAYS for view in views[:4])
    assert perspective not in [
        Perspective(item["perspective"])
        for item in perspective_guidance(selected, GuidanceStage.DEFINITION)
    ]


def test_evidence_of_the_agents_of_a_perspective_is_merged_in_the_order_of_the_rules() -> None:
    constraints = constraints_for(description="A website.")
    researcher = TeamRoleConstraint(
        agent_id=AgentIdentifier.UX_RESEARCHER_USER_MODELER,
        kind=TeamRoleConstraintKind.MANDATORY,
        reasons=(
            TeamSelectionReason(code=TeamSelectionReasonCode.CORE_USER_CENTERED_DESIGN),
            TeamSelectionReason(
                code=TeamSelectionReasonCode.USER_INTERFACE_SIGNAL,
                evidence=RuleEvidence(fields=(BriefField.TARGET_USERS,), terms=("screen",)),
            ),
            TeamSelectionReason(
                code=TeamSelectionReasonCode.BROWNFIELD_INTEGRATION,
            ),
        ),
    )
    merged = replace(
        constraints,
        role_constraints=tuple(
            researcher
            if constraint.agent_id is AgentIdentifier.UX_RESEARCHER_USER_MODELER
            else constraint
            for constraint in constraints.role_constraints
        ),
    )
    ux = perspective_views(merged, merged.mandatory_agent_ids)[0]

    assert constraints.constraint_for(AgentIdentifier.UX_UI_DESIGNER).reasons[1].evidence == (
        RuleEvidence(fields=(BriefField.DESCRIPTION,), terms=("website",))
    )
    assert ux.requested == RuleEvidence(
        fields=(BriefField.DESCRIPTION, BriefField.TARGET_USERS),
        terms=("screen", "website"),
    )
    assert ux.excluded == RuleEvidence()


def test_evidence_from_several_fields_keeps_the_order_of_the_brief() -> None:
    units = units_of(snapshots_for(description="A website.", technical_constraints=["Vue"]))

    assert units["WEB"]["requested"] == {
        "fields": ["description", "technical_constraints"],
        "terms": ["vue", "website"],
    }


def test_snapshots_give_exactly_the_payload_of_the_contract() -> None:
    constraints = constraints_for(**CONTRACT_BRIEF)
    views = perspective_views(constraints, constraints.mandatory_agent_ids)
    snapshots = [view.to_snapshot() for view in views]

    assert [view.key for view in views] == list(PERSPECTIVE_ORDER)
    assert snapshots[2] == CONTRACT_SOFTWARE_ENGINEERING
    assert list(snapshots[2]) == [
        "key",
        "standing",
        "applied",
        "editable",
        "agent_id",
        "requested",
        "excluded",
        "aspects",
    ]
    assert list(snapshots[2]["aspects"][0]) == [
        "key",
        "agent_id",
        "standing",
        "applied",
        "editable",
        "requested",
        "excluded",
    ]
    assert snapshots[4]["agent_id"] == "SECURITY_REVIEWER"
    assert [snapshot["aspects"] for index, snapshot in enumerate(snapshots) if index != 2] == [
        []
    ] * 4
    assert json.loads(json.dumps(snapshots)) == snapshots


@pytest.mark.parametrize("stage", tuple(GuidanceStage))
def test_guidance_with_every_perspective_and_aspect_applied_is_word_for_word(
    stage: GuidanceStage,
) -> None:
    assert perspective_guidance(SELECTABLE_SPECIALIST_AGENT_IDS, stage) == FULL_GUIDANCE[stage]
    assert json.loads(json.dumps(FULL_GUIDANCE[stage])) == FULL_GUIDANCE[stage]


@pytest.mark.parametrize("stage", tuple(GuidanceStage))
def test_the_minimum_team_gets_four_perspectives_and_the_core_of_software_engineering(
    stage: GuidanceStage,
) -> None:
    guidance = perspective_guidance(MINIMUM_TEAM, stage)
    full = {item["perspective"]: item["considerations"] for item in FULL_GUIDANCE[stage]}

    assert [item["perspective"] for item in guidance] == [
        "UX",
        "ACCESSIBILITY",
        "SOFTWARE_ENGINEERING",
        "PRODUCT",
    ]
    assert guidance[2]["considerations"] == full["SOFTWARE_ENGINEERING"][:2]
    assert [item["considerations"] for item in guidance if item is not guidance[2]] == [
        full["UX"],
        full["ACCESSIBILITY"],
        full["PRODUCT"],
    ]


@pytest.mark.parametrize("stage", tuple(GuidanceStage))
def test_aspect_sentences_follow_the_core_in_the_order_of_the_aspects(
    stage: GuidanceStage,
) -> None:
    selected = (
        AgentIdentifier.MOBILE_ENGINEER,
        *reversed(MINIMUM_TEAM),
        AgentIdentifier.FRONTEND_ENGINEER,
    )
    software = perspective_guidance(selected, stage)[2]
    full = FULL_GUIDANCE[stage][2]["considerations"]

    assert software == {
        "perspective": "SOFTWARE_ENGINEERING",
        "considerations": [full[0], full[1], full[2], full[4]],
    }


def test_security_is_given_only_when_its_agent_is_selected() -> None:
    with_security = perspective_guidance(
        (*MINIMUM_TEAM, AgentIdentifier.SECURITY_REVIEWER),
        GuidanceStage.DESIGN,
    )

    assert with_security[-1] == DESIGN_GUIDANCE[-1]
    assert [item["perspective"] for item in with_security] == [
        "UX",
        "ACCESSIBILITY",
        "SOFTWARE_ENGINEERING",
        "PRODUCT",
        "SECURITY",
    ]


def test_strings_are_accepted_and_unknown_values_are_ignored() -> None:
    as_strings = [agent_id.value for agent_id in SELECTABLE_SPECIALIST_AGENT_IDS]
    platform = [agent_id.value for agent_id in ALWAYS_PRESENT_AGENT_IDS]
    noisy = [*as_strings, "NOT_AN_AGENT", "", *platform, *as_strings]
    constraints = constraints_for(**CONTRACT_BRIEF)

    for stage in GuidanceStage:
        assert perspective_guidance(as_strings, stage) == FULL_GUIDANCE[stage]
        assert perspective_guidance(noisy, stage) == FULL_GUIDANCE[stage]
        assert perspective_guidance(["NOT_AN_AGENT", *platform], stage) == []
        assert perspective_guidance([], stage) == []

    assert perspective_views(constraints, noisy) == perspective_views(
        constraints, SELECTABLE_SPECIALIST_AGENT_IDS
    )
    assert perspective_views(
        constraints, [*(agent_id.value for agent_id in MINIMUM_TEAM), "security_reviewer"]
    ) == perspective_views(constraints, MINIMUM_TEAM)
    assert perspective_views(constraints, iter(as_strings)) == perspective_views(
        constraints, SELECTABLE_SPECIALIST_AGENT_IDS
    )


def test_each_call_returns_new_lists() -> None:
    first = perspective_guidance(MINIMUM_TEAM, GuidanceStage.DEFINITION)
    first[0]["considerations"].append("Changed by a caller.")
    first.append({"perspective": "SECURITY", "considerations": []})

    assert perspective_guidance(MINIMUM_TEAM, GuidanceStage.DEFINITION) == [
        DEFINITION_GUIDANCE[0],
        DEFINITION_GUIDANCE[1],
        {
            "perspective": "SOFTWARE_ENGINEERING",
            "considerations": DEFINITION_GUIDANCE[2]["considerations"][:2],
        },
        DEFINITION_GUIDANCE[3],
    ]


def test_views_refuse_values_that_contradict_the_contract() -> None:
    constraints = constraints_for()
    ux, _, software, _, security = perspective_views(constraints, constraints.mandatory_agent_ids)
    web = software.aspects[0]
    refused = (
        lambda: replace(ux, editable=True),
        lambda: replace(ux, agent_id=AgentIdentifier.UX_UI_DESIGNER),
        lambda: replace(ux, standing=PerspectiveStanding.OPTIONAL, editable=True),
        lambda: replace(ux, aspects=software.aspects),
        lambda: replace(software, aspects=software.aspects[:3]),
        lambda: replace(software, aspects=tuple(reversed(software.aspects))),
        lambda: replace(security, standing=PerspectiveStanding.ALWAYS, editable=False),
        lambda: replace(security, agent_id=None),
        lambda: replace(security, editable=False),
        lambda: replace(web, agent_id=AgentIdentifier.BACKEND_ENGINEER),
        lambda: replace(web, standing=PerspectiveStanding.ALWAYS, editable=False),
        lambda: replace(web, editable=False),
        lambda: replace(web, standing=PerspectiveStanding.REQUIRED),
    )

    for build in refused:
        with pytest.raises(ValueError):
            build()
