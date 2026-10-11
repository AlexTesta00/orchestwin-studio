from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from orchestwin.agents.perspectives import (
    AspectView,
    GuidanceStage,
    Perspective,
    PerspectiveAspect,
    PerspectiveStanding,
    PerspectiveView,
    perspective_guidance,
    perspective_views,
)
from orchestwin.agents.proposals import TeamProposalVersion
from orchestwin.agents.selection_rules import RuleEvidence
from orchestwin.knowledge.documents_markdown import UNSET, _version_lines, markdown_bullets
from orchestwin.knowledge.layout import STAGE_LABELS
from orchestwin.projects.briefs import BriefField
from orchestwin.workflow.gates import HumanGate

_PERSPECTIVES_INTRODUCTION: Final = (
    "The perspectives are the competences through which this project is looked at. Each applied "
    "perspective adds its considerations when the requirements and the design alternatives are "
    "written."
)
_PERSPECTIVE_TEXTS: Final[dict[Perspective, tuple[str, str]]] = {
    Perspective.UX: (
        "User experience (UX)",
        "Looks at the project through the eyes of the people who will use it: goals, context, "
        "places where they may get stuck.",
    ),
    Perspective.ACCESSIBILITY: (
        "Accessibility",
        "Checks that everyone can use it: keyboard, contrast, readable text, clear messages.",
    ),
    Perspective.SOFTWARE_ENGINEERING: (
        "Software engineering",
        "Keeps the project feasible within its technical constraints, time and budget, and "
        "verifiable.",
    ),
    Perspective.PRODUCT: (
        "Product",
        "Keeps the priorities: what the first version needs and what can wait.",
    ),
    Perspective.SECURITY: ("Security", "Protects data and access: who may see and do what."),
}
_ASPECT_NAMES: Final[dict[PerspectiveAspect, str]] = {
    PerspectiveAspect.WEB: "Web interface",
    PerspectiveAspect.SERVICES: "Services and data",
    PerspectiveAspect.MOBILE: "Mobile",
    PerspectiveAspect.INTEGRATIONS: "Connections to other systems",
}
_ASPECT_OF: Final = "aspect of software engineering"
_BRIEF_FIELD_NAMES: Final[dict[BriefField, str]] = {
    BriefField.NAME: "Name",
    BriefField.DESCRIPTION: "The idea",
    BriefField.PROBLEM: "The problem",
    BriefField.GOALS: "Goals",
    BriefField.TARGET_USERS: "For whom",
    BriefField.DOMAIN: "Context",
    BriefField.TECHNICAL_CONSTRAINTS: "Technical constraints",
    BriefField.TEMPORAL_CONSTRAINTS: "Timing",
    BriefField.BUDGET: "Budget",
    BriefField.FUNCTIONAL_REQUIREMENTS: "What it must do",
    BriefField.NON_FUNCTIONAL_REQUIREMENTS: "Expected qualities",
    BriefField.RISKS: "Risks",
    BriefField.STAKEHOLDERS: "People involved",
    BriefField.AVAILABLE_ARTIFACTS: "Available materials",
    BriefField.DEFINITION_OF_DONE: "When it is done",
}
_ALWAYS_APPLIED: Final = "Always applied"
_PREPARED_EARLIER: Final = "This version was prepared before this perspective became always applied"
_OPTIONAL_APPLIED: Final = "Applied, optional"
_OPTIONAL: Final = "Optional"
_STANDING_TEXTS: Final[dict[PerspectiveStanding, str]] = {
    PerspectiveStanding.REQUIRED: "The brief asks for it{requested}",
    PerspectiveStanding.EXCLUDED: "The brief rules it out{excluded}",
    PerspectiveStanding.CONTESTED: (
        "The brief says two different things: the owner decides. It rules it out{excluded} and "
        "also calls for it{requested}"
    ),
}
_GUIDANCE_HEADINGS: Final = (
    (GuidanceStage.DEFINITION, "In the definition:"),
    (GuidanceStage.DESIGN, "In the design:"),
)


def _evidence_text(evidence: RuleEvidence) -> str:
    if not evidence.terms:
        return ""
    terms = ", ".join(f"“{term}”" for term in evidence.terms)
    fields = ", ".join(_BRIEF_FIELD_NAMES[field] for field in evidence.fields)
    return f" ({terms} in {fields})"


def _standing_text(unit: PerspectiveView | AspectView) -> str:
    if unit.standing is PerspectiveStanding.ALWAYS:
        return _ALWAYS_APPLIED if unit.applied else _PREPARED_EARLIER
    if unit.standing is PerspectiveStanding.OPTIONAL:
        return _OPTIONAL_APPLIED if unit.applied else _OPTIONAL
    return _STANDING_TEXTS[unit.standing].format(
        requested=_evidence_text(unit.requested), excluded=_evidence_text(unit.excluded)
    )


def _considerations(version: TeamProposalVersion) -> dict[GuidanceStage, dict[str, list[str]]]:
    selected = version.proposal.selected_agent_ids
    return {
        stage: {
            str(item["perspective"]): [str(sentence) for sentence in item["considerations"]]
            for item in perspective_guidance(selected, stage)
        }
        for stage, _heading in _GUIDANCE_HEADINGS
    }


def _applied_perspective_lines(
    view: PerspectiveView, considerations: Mapping[GuidanceStage, Mapping[str, list[str]]]
) -> list[str]:
    name, line = _PERSPECTIVE_TEXTS[view.key]
    lines = [f"### {name}", "", line, "", f"{_standing_text(view)}.", ""]
    aspects = [aspect for aspect in view.aspects if aspect.applied]
    if aspects:
        lines.extend(
            [
                "Applied aspects:",
                *(f"- {_ASPECT_NAMES[item.key]}: {_standing_text(item)}." for item in aspects),
                "",
            ]
        )
    for stage, heading in _GUIDANCE_HEADINGS:
        sentences = considerations[stage].get(view.key.value, [])
        lines.extend([heading, *markdown_bullets(sentences), ""])
    return lines


def _not_applied_lines(views: Sequence[PerspectiveView]) -> list[str]:
    lines: list[str] = []
    for view in views:
        if not view.applied:
            lines.append(f"- {_PERSPECTIVE_TEXTS[view.key][0]}: {_standing_text(view)}.")
        lines.extend(
            f"- {_ASPECT_NAMES[aspect.key]} ({_ASPECT_OF}): {_standing_text(aspect)}."
            for aspect in view.aspects
            if not aspect.applied
        )
    return ["## Not applied", "", *lines, ""] if lines else []


def team_markdown(version: TeamProposalVersion, gate: HumanGate) -> str:
    proposal = version.proposal
    views = perspective_views(proposal.constraints, proposal.selected_agent_ids)
    considerations = _considerations(version)
    lines = _version_lines(STAGE_LABELS["team"], version, gate)
    lines.extend([_PERSPECTIVES_INTRODUCTION, "", "## Applied", ""])
    applied = [view for view in views if view.applied]
    for view in applied:
        lines.extend(_applied_perspective_lines(view, considerations))
    if not applied:
        lines.extend([f"{UNSET}.", ""])
    lines.extend(_not_applied_lines(views))
    return "\n".join(lines)
