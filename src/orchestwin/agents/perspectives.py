from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from orchestwin.agents.catalog import AgentIdentifier
from orchestwin.agents.selection_rules import (
    DeterministicTeamConstraints,
    RuleEvidence,
    TeamRoleConstraintKind,
    TeamSelectionReasonCode,
    merge_rule_evidence,
)


class Perspective(StrEnum):
    UX = "UX"
    ACCESSIBILITY = "ACCESSIBILITY"
    SOFTWARE_ENGINEERING = "SOFTWARE_ENGINEERING"
    PRODUCT = "PRODUCT"
    SECURITY = "SECURITY"


class PerspectiveAspect(StrEnum):
    WEB = "WEB"
    SERVICES = "SERVICES"
    MOBILE = "MOBILE"
    INTEGRATIONS = "INTEGRATIONS"


class PerspectiveStanding(StrEnum):
    ALWAYS = "ALWAYS"
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    EXCLUDED = "EXCLUDED"
    CONTESTED = "CONTESTED"


class GuidanceStage(StrEnum):
    DEFINITION = "DEFINITION"
    DESIGN = "DESIGN"


PERSPECTIVE_ORDER: Final[tuple[Perspective, ...]] = (
    Perspective.UX,
    Perspective.ACCESSIBILITY,
    Perspective.SOFTWARE_ENGINEERING,
    Perspective.PRODUCT,
    Perspective.SECURITY,
)


ASPECT_ORDER: Final[tuple[PerspectiveAspect, ...]] = (
    PerspectiveAspect.WEB,
    PerspectiveAspect.SERVICES,
    PerspectiveAspect.MOBILE,
    PerspectiveAspect.INTEGRATIONS,
)


PERSPECTIVE_AGENT_IDS: Final[Mapping[Perspective, tuple[AgentIdentifier, ...]]] = MappingProxyType(
    {
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
)


ASPECT_AGENT_IDS: Final[Mapping[PerspectiveAspect, AgentIdentifier]] = MappingProxyType(
    {
        PerspectiveAspect.WEB: AgentIdentifier.FRONTEND_ENGINEER,
        PerspectiveAspect.SERVICES: AgentIdentifier.BACKEND_ENGINEER,
        PerspectiveAspect.MOBILE: AgentIdentifier.MOBILE_ENGINEER,
        PerspectiveAspect.INTEGRATIONS: AgentIdentifier.INTEGRATION_ENGINEER,
    }
)


SWITCHABLE_PERSPECTIVE_AGENT_IDS: Final[Mapping[Perspective, AgentIdentifier]] = MappingProxyType(
    {Perspective.SECURITY: AgentIdentifier.SECURITY_REVIEWER}
)


_UNIT_STANDINGS: Final[Mapping[TeamRoleConstraintKind, PerspectiveStanding]] = MappingProxyType(
    {
        TeamRoleConstraintKind.MANDATORY: PerspectiveStanding.REQUIRED,
        TeamRoleConstraintKind.OPTIONAL: PerspectiveStanding.OPTIONAL,
        TeamRoleConstraintKind.IMPOSSIBLE: PerspectiveStanding.EXCLUDED,
        TeamRoleConstraintKind.CONFLICT: PerspectiveStanding.CONTESTED,
    }
)


_EDITABLE_STANDINGS: Final = frozenset(
    {
        PerspectiveStanding.OPTIONAL,
        PerspectiveStanding.CONTESTED,
    }
)


_SIGNAL_SUFFIX: Final = "_SIGNAL"


_AGENTS_BY_VALUE: Final[Mapping[str, AgentIdentifier]] = MappingProxyType(
    {agent_id.value: agent_id for agent_id in AgentIdentifier}
)


_PERSPECTIVE_CONSIDERATIONS: Final[
    Mapping[GuidanceStage, Mapping[Perspective, tuple[str, ...]]]
] = MappingProxyType(
    {
        GuidanceStage.DEFINITION: MappingProxyType(
            {
                Perspective.UX: (
                    "Write each user story and scenario from the point of view of one twin: "
                    "the goal, the context of use and the moment where that person may get "
                    "stuck.",
                    "Each functional requirement serves a need of a twin or of the brief and "
                    "says what the person sees after acting.",
                ),
                Perspective.ACCESSIBILITY: (
                    "State as requirements or acceptance criteria the accessibility needs that "
                    "this project implies: use from the keyboard, readable contrast and text "
                    "size, names for controls and images, messages that say in words what went "
                    "wrong.",
                    "When a twin has a limitation or a context that makes the interface harder "
                    "to use, at least one acceptance criterion covers it.",
                ),
                Perspective.SOFTWARE_ENGINEERING: (
                    "Keep every requirement feasible within the technical constraints, the time "
                    "and the budget of the brief, and name as a risk what may not be.",
                    "Write acceptance criteria that can be checked by using the application, "
                    "each with one observable outcome.",
                ),
                Perspective.PRODUCT: (
                    "Give each requirement the priority that the brief supports: what the first "
                    "usable version must have and what can wait.",
                    "Keep out what the brief leaves out, and name as a risk any assumption about "
                    "value that nobody has verified.",
                ),
                Perspective.SECURITY: (
                    "Name the data and the actions that need protection and who may see or do "
                    "them; add requirements for access, session and data protection only where "
                    "the brief implies them.",
                    "Cover with an acceptance criterion what happens after wrong credentials, an "
                    "expired session or an action that is not allowed.",
                ),
            }
        ),
        GuidanceStage.DESIGN: MappingProxyType(
            {
                Perspective.UX: (
                    "Each alternative lets every twin reach their main goal in few steps, shows "
                    "the result of each action and lets the person undo or correct a mistake.",
                    "The alternatives differ in how the person works, not only in how they look.",
                ),
                Perspective.ACCESSIBILITY: (
                    "In each alternative every action is reachable from the keyboard with a "
                    "visible focus, text keeps a readable contrast and no information depends "
                    "on colour alone.",
                    "Controls and fields have a visible name, and errors are explained in words "
                    "next to the field.",
                ),
                Perspective.SOFTWARE_ENGINEERING: (
                    "Each alternative can be built within the technical constraints of the "
                    "brief; name what would be costly to build.",
                    "Each screen has its empty, loading and error states.",
                ),
                Perspective.PRODUCT: (
                    "Say for each alternative which goal of the brief it serves best and what "
                    "it gives up.",
                    "Do not add screens or functions that no requirement asks for.",
                ),
                Perspective.SECURITY: (
                    "Show how the person knows they are signed in and how they sign out, and "
                    "ask for confirmation before an action that destroys data.",
                    "Do not show sensitive data in full where a part is enough.",
                ),
            }
        ),
    }
)


_ASPECT_CONSIDERATIONS: Final[Mapping[GuidanceStage, Mapping[PerspectiveAspect, str]]] = (
    MappingProxyType(
        {
            GuidanceStage.DEFINITION: MappingProxyType(
                {
                    PerspectiveAspect.WEB: (
                        "The application runs in a browser: cover the window sizes it must work at "
                        "and what the person sees while content loads or fails to load."
                    ),
                    PerspectiveAspect.SERVICES: (
                        "The application keeps data or logic on a server: say which data are kept "
                        "and what the person sees when the service does not answer or refuses."
                    ),
                    PerspectiveAspect.MOBILE: (
                        "The application is used on a phone or a tablet: cover touch use, small "
                        "screens and a connection that comes and goes."
                    ),
                    PerspectiveAspect.INTEGRATIONS: (
                        "The application depends on other systems: say which data cross the "
                        "boundary and what the person sees when the other system fails."
                    ),
                }
            ),
            GuidanceStage.DESIGN: MappingProxyType(
                {
                    PerspectiveAspect.WEB: (
                        "Layouts adapt from a phone-wide window to a desktop one."
                    ),
                    PerspectiveAspect.SERVICES: (
                        "Show what the person sees while data are being saved or fetched and when "
                        "that fails."
                    ),
                    PerspectiveAspect.MOBILE: (
                        "Controls are large enough for touch and the main actions are reachable "
                        "with one hand."
                    ),
                    PerspectiveAspect.INTEGRATIONS: (
                        "Show the state of each connection to another system and what the person "
                        "can do when it is unavailable."
                    ),
                }
            ),
        }
    )
)


def _evidence_snapshot(
    evidence: RuleEvidence,
) -> dict[str, object]:
    return {
        "fields": [field.value for field in evidence.fields],
        "terms": list(evidence.terms),
    }


def _expected_editable(
    standing: PerspectiveStanding,
) -> bool:
    return standing in _EDITABLE_STANDINGS


@dataclass(frozen=True, slots=True)
class AspectView:
    key: PerspectiveAspect
    agent_id: AgentIdentifier
    standing: PerspectiveStanding
    applied: bool
    editable: bool
    requested: RuleEvidence
    excluded: RuleEvidence

    def __post_init__(self) -> None:
        if self.agent_id is not ASPECT_AGENT_IDS[self.key]:
            raise ValueError("an aspect view must use the agent of its aspect")

        if self.standing is PerspectiveStanding.ALWAYS:
            raise ValueError("an aspect is switched by the owner and is never always applied")

        if self.editable is not _expected_editable(self.standing):
            raise ValueError("an aspect view is editable only when optional or contested")

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        return {
            "key": self.key.value,
            "agent_id": self.agent_id.value,
            "standing": self.standing.value,
            "applied": self.applied,
            "editable": self.editable,
            "requested": _evidence_snapshot(self.requested),
            "excluded": _evidence_snapshot(self.excluded),
        }


@dataclass(frozen=True, slots=True)
class PerspectiveView:
    key: Perspective
    standing: PerspectiveStanding
    applied: bool
    editable: bool
    agent_id: AgentIdentifier | None
    requested: RuleEvidence
    excluded: RuleEvidence
    aspects: tuple[AspectView, ...] = ()

    def __post_init__(self) -> None:
        switch_agent_id = SWITCHABLE_PERSPECTIVE_AGENT_IDS.get(self.key)

        if self.agent_id is not switch_agent_id:
            raise ValueError("a perspective view must use the agent that switches it")

        if (self.standing is PerspectiveStanding.ALWAYS) is not (switch_agent_id is None):
            raise ValueError("only a perspective that the owner cannot switch is always applied")

        if self.editable is not _expected_editable(self.standing):
            raise ValueError("a perspective view is editable only when optional or contested")

        expected_aspects = ASPECT_ORDER if self.key is Perspective.SOFTWARE_ENGINEERING else ()

        if tuple(aspect.key for aspect in self.aspects) != expected_aspects:
            raise ValueError("only software engineering holds aspects, all four in order")

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        return {
            "key": self.key.value,
            "standing": self.standing.value,
            "applied": self.applied,
            "editable": self.editable,
            "agent_id": None if self.agent_id is None else self.agent_id.value,
            "requested": _evidence_snapshot(self.requested),
            "excluded": _evidence_snapshot(self.excluded),
            "aspects": [aspect.to_snapshot() for aspect in self.aspects],
        }


def _selected_agents(
    selected_agent_ids: Iterable[AgentIdentifier | str],
) -> frozenset[AgentIdentifier]:
    selected: set[AgentIdentifier] = set()

    for value in selected_agent_ids:
        if isinstance(value, AgentIdentifier):
            selected.add(value)
            continue

        if isinstance(value, str) and value in _AGENTS_BY_VALUE:
            selected.add(_AGENTS_BY_VALUE[value])

    return frozenset(selected)


def _perspective_applied(
    perspective: Perspective,
    selected: frozenset[AgentIdentifier],
) -> bool:
    return all(agent_id in selected for agent_id in PERSPECTIVE_AGENT_IDS[perspective])


def _requested_evidence(
    constraints: DeterministicTeamConstraints,
    agent_ids: tuple[AgentIdentifier, ...],
) -> RuleEvidence:
    return merge_rule_evidence(
        reason.evidence
        for agent_id in agent_ids
        for reason in constraints.constraint_for(agent_id).reasons
        if reason.code.value.endswith(_SIGNAL_SUFFIX)
    )


def _excluded_evidence(
    constraints: DeterministicTeamConstraints,
    agent_ids: tuple[AgentIdentifier, ...],
) -> RuleEvidence:
    return merge_rule_evidence(
        reason.evidence
        for agent_id in agent_ids
        for reason in constraints.constraint_for(agent_id).reasons
        if reason.code is TeamSelectionReasonCode.EXPLICIT_SCOPE_EXCLUSION
    )


def _unit_standing(
    constraints: DeterministicTeamConstraints,
    agent_id: AgentIdentifier,
) -> PerspectiveStanding:
    return _UNIT_STANDINGS[constraints.constraint_for(agent_id).kind]


def _aspect_view(
    constraints: DeterministicTeamConstraints,
    aspect: PerspectiveAspect,
    selected: frozenset[AgentIdentifier],
) -> AspectView:
    agent_id = ASPECT_AGENT_IDS[aspect]
    standing = _unit_standing(constraints, agent_id)

    return AspectView(
        key=aspect,
        agent_id=agent_id,
        standing=standing,
        applied=agent_id in selected,
        editable=_expected_editable(standing),
        requested=_requested_evidence(constraints, (agent_id,)),
        excluded=_excluded_evidence(constraints, (agent_id,)),
    )


def _perspective_view(
    constraints: DeterministicTeamConstraints,
    perspective: Perspective,
    selected: frozenset[AgentIdentifier],
) -> PerspectiveView:
    agent_ids = PERSPECTIVE_AGENT_IDS[perspective]
    switch_agent_id = SWITCHABLE_PERSPECTIVE_AGENT_IDS.get(perspective)
    standing = (
        PerspectiveStanding.ALWAYS
        if switch_agent_id is None
        else _unit_standing(constraints, switch_agent_id)
    )

    return PerspectiveView(
        key=perspective,
        standing=standing,
        applied=_perspective_applied(perspective, selected),
        editable=_expected_editable(standing),
        agent_id=switch_agent_id,
        requested=_requested_evidence(constraints, agent_ids),
        excluded=_excluded_evidence(constraints, agent_ids),
        aspects=(
            tuple(_aspect_view(constraints, aspect, selected) for aspect in ASPECT_ORDER)
            if perspective is Perspective.SOFTWARE_ENGINEERING
            else ()
        ),
    )


def perspective_views(
    constraints: DeterministicTeamConstraints,
    selected_agent_ids: Iterable[AgentIdentifier | str],
) -> tuple[PerspectiveView, ...]:
    selected = _selected_agents(selected_agent_ids)

    return tuple(
        _perspective_view(constraints, perspective, selected) for perspective in PERSPECTIVE_ORDER
    )


def perspective_guidance(
    selected_agent_ids: Iterable[AgentIdentifier | str],
    stage: GuidanceStage,
) -> list[dict[str, object]]:
    selected = _selected_agents(selected_agent_ids)
    perspective_considerations = _PERSPECTIVE_CONSIDERATIONS[GuidanceStage(stage)]
    aspect_considerations = _ASPECT_CONSIDERATIONS[GuidanceStage(stage)]
    guidance: list[dict[str, object]] = []

    for perspective in PERSPECTIVE_ORDER:
        if not _perspective_applied(perspective, selected):
            continue

        considerations = list(perspective_considerations[perspective])

        if perspective is Perspective.SOFTWARE_ENGINEERING:
            considerations.extend(
                aspect_considerations[aspect]
                for aspect in ASPECT_ORDER
                if ASPECT_AGENT_IDS[aspect] in selected
            )

        guidance.append(
            {
                "perspective": perspective.value,
                "considerations": considerations,
            }
        )

    return guidance


__all__ = [
    "ASPECT_AGENT_IDS",
    "ASPECT_ORDER",
    "PERSPECTIVE_AGENT_IDS",
    "PERSPECTIVE_ORDER",
    "SWITCHABLE_PERSPECTIVE_AGENT_IDS",
    "AspectView",
    "GuidanceStage",
    "Perspective",
    "PerspectiveAspect",
    "PerspectiveStanding",
    "PerspectiveView",
    "perspective_guidance",
    "perspective_views",
]
