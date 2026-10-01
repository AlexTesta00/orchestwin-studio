from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

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
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.visual_catalog import ARCHETYPES, LayoutArchetype
from orchestwin.knowledge.layout import STAGE_LABELS, STAGES, VIEW_STAGES, present_stages
from orchestwin.projects.briefs import BriefField, ProjectBriefVersion
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.twins.user_twins import UserModelingSnapshotVersion
from orchestwin.workflow.gates import HumanGate

UNSET: Final = "not provided"
OVERVIEW_DESCRIPTION_LENGTH: Final = 300
OVERVIEW_REQUIREMENTS: Final = 12
_ROLE_KEY: Final = "user_twin.role"
_MUST: Final = "MUST"
_VERIFIED: Final = "- How it is verified: {criteria}, which `ut test` checks in the browsers."
_OVERVIEW_TEXTS: Final[dict[str, dict[str, Any]]] = {
    "en": {
        "heading": "## In short",
        "project": "- Project: {name}.",
        "described": "- Project: {name}. {description}",
        "twins": "- Who it is for: {twins}.",
        "must": "- What it must do:",
        "more": ("and 1 more.", "and {count} more."),
        "design": "- Chosen design: {alternative}.",
        "product": "{alternative} (product name: {product})",
        "criteria": (_VERIFIED, _VERIFIED),
        "criterion_words": ("acceptance criterion", "acceptance criteria"),
    },
    "it": {
        "heading": "## In breve",
        "project": "- Progetto: {name}.",
        "described": "- Progetto: {name}. {description}",
        "twins": "- Per chi è: {twins}.",
        "must": "- Cosa deve fare:",
        "more": ("e un altro.", "e altri {count}."),
        "design": "- Design scelto: {alternative}.",
        "product": "{alternative} (nome del prodotto: {product})",
        "criteria": (
            "- Come si verifica: {criteria}, controllato da `ut test` nei browser.",
            "- Come si verifica: {criteria}, controllati da `ut test` nei browser.",
        ),
        "criterion_words": ("criterio di accettazione", "criteri di accettazione"),
    },
}
_STEP_NAMES: Final = ", ".join(STAGE_LABELS[stage] for stage in STAGES)
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


def plain_text(value: object) -> str:
    if value is None:
        return UNSET
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return value if value.strip() else UNSET
    if isinstance(value, Mapping):
        return ", ".join(f"{key}: {plain_text(item)}" for key, item in value.items()) or UNSET
    if isinstance(value, Sequence):
        return ", ".join(plain_text(item) for item in value) if value else UNSET
    return str(value)


def title_text(value: str) -> str:
    return value.replace("_", " ").capitalize()


def _inline(value: object) -> str:
    return " ".join(str(value).split())


def _bare(value: object) -> str:
    return _inline(value).rstrip(".")


def _sentence(value: object) -> str:
    text = _inline(value)
    return text if not text or text.endswith((".", "!", "?", "…")) else f"{text}."


def _lowered(value: object) -> str:
    return str(value).replace("_", " ").lower()


def excerpt(text: str, limit: int = OVERVIEW_DESCRIPTION_LENGTH) -> str:
    flat = _inline(text)
    if len(flat) <= limit:
        return flat
    head = flat[: limit + 1]
    cut = head.rsplit(" ", 1)[0] if " " in head else flat[:limit]
    return f"{cut.rstrip(' ,;:.')}…"


def markdown_bullets(items: Iterable[object]) -> list[str]:
    lines = [f"- {plain_text(item)}" for item in items]
    return lines or [f"- {UNSET}"]


def _cell(value: object) -> str:
    if value is None or (isinstance(value, Sequence) and not isinstance(value, str) and not value):
        return ""
    return plain_text(value).replace("|", "/").replace("\n", " ")


def markdown_table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    body = ["| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows]
    if not body:
        return [f"{UNSET}."]
    return [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(" --- " for _ in headers) + "|",
        *body,
    ]


def reference_text(reference: Mapping[str, object]) -> str:
    if "name" in reference:
        return f"{reference['name']} (v{reference['version_number']})"
    identifier = reference.get("artifact_id", reference.get("persona_id", reference.get("id")))
    return f"{identifier} v{reference.get('version_number')}"


def _observation_value(value: Mapping[str, object]) -> str:
    text = value.get("text")
    if isinstance(text, str) and text.strip():
        return text
    items = value.get("items")
    if isinstance(items, Sequence) and items:
        return "; ".join(plain_text(item) for item in items)
    reason = value.get("reason")
    return f"unknown ({reason})" if reason else UNSET


def observation_table(observations: Iterable[Mapping[str, object]]) -> list[str]:
    rows = [
        (
            item["observation_key"],
            _observation_value(item["value"]),
            item["epistemic_status"],
            item["confidence"],
            item["human_validation"],
        )
        for item in observations
    ]
    return markdown_table(
        ("Observation", "Value", "Epistemic status", "Confidence", "Validation"), rows
    )


def _version_lines(label: str, version: object, gate: HumanGate) -> list[str]:
    return [
        f"# {label}",
        "",
        f"Version {version.version_number}, content hash `{version.content_hash}`, "
        f"approved by the owner on {gate.updated_at.isoformat()}.",
        "",
    ]


def brief_markdown(version: ProjectBriefVersion, gate: HumanGate) -> str:
    snapshot = version.brief.to_snapshot()
    lines = _version_lines(STAGE_LABELS["brief"], version, gate)
    for key, value in snapshot["fields"].items():
        lines.extend([f"## {title_text(key)}", ""])
        if isinstance(value, list):
            lines.extend(markdown_bullets(value))
        else:
            lines.append(plain_text(value))
        lines.append("")
    lines.extend(
        ["## Fields marked as unknown", "", *markdown_bullets(snapshot["unknown_fields"]), ""]
    )
    return "\n".join(lines)


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


def _persona_names(snapshot: Mapping[str, object]) -> dict[tuple[str, object], str]:
    return {
        (str(persona["persona_id"]), persona["version_number"]): str(persona["profile"]["name"])
        for persona in snapshot["persona_versions"]
    }


def twins_markdown(version: UserModelingSnapshotVersion, gate: HumanGate) -> str:
    snapshot = version.snapshot.to_snapshot()
    personas = _persona_names(snapshot)
    lines = _version_lines(STAGE_LABELS["twins"], version, gate)
    lines.extend(["## Personas", ""])
    for persona in snapshot["persona_versions"]:
        profile = persona["profile"]
        lines.extend(
            [
                f"### {profile['name']}",
                "",
                f"Source {title_text(profile['source'])}, {title_text(profile['kind'])}, "
                f"{title_text(profile['confirmation_status'])}, "
                f"version {persona['version_number']}.",
                "",
                *observation_table(profile["observations"]),
                "",
            ]
        )
    lines.extend(["## User twins", ""])
    for twin in snapshot["twin_versions"]:
        profile = twin["profile"]
        reference = profile["persona_reference"]
        persona = personas.get((str(reference["persona_id"]), reference["version_number"]), UNSET)
        lines.extend(
            [
                f"### {profile['name']}",
                "",
                f"Version {twin['version_number']}, "
                f"validation status {profile['validation_status']}, human validation "
                f"{'required' if profile['requires_human_validation'] else 'not required'}, "
                f"persona {persona} (v{reference['version_number']}).",
                "",
                *observation_table(profile["observations"]),
                "",
            ]
        )
    return "\n".join(lines)


def code_index(specification: Mapping[str, object]) -> dict[str, str]:
    codes: dict[str, str] = {}
    for key in (
        "requirements",
        "user_stories",
        "acceptance_criteria",
        "scenarios",
        "definition_of_done",
    ):
        for item in specification[key]:
            codes[item["id"]] = item["code"]
    return codes


def code_list(identifiers: Iterable[str], codes: Mapping[str, str]) -> str:
    return (
        ", ".join(sorted(codes.get(identifier, identifier) for identifier in identifiers)) or UNSET
    )


def twin_names(references: Iterable[Mapping[str, object]]) -> str:
    names = sorted(
        (str(reference["name"]) for reference in references),
        key=lambda name: (name.casefold(), name),
    )
    return ", ".join(names)


def _risk_line(risk: Mapping[str, object], codes: Mapping[str, str]) -> str:
    return (
        f"- {risk['code']}: {_sentence(risk['summary'])} Likelihood "
        f"{_lowered(risk['likelihood'])}, impact {_lowered(risk['impact'])}. Mitigation: "
        f"{_sentence(risk['mitigation'])} Requirements {code_list(risk['requirement_ids'], codes)}."
    )


def requirements_markdown(version: RequirementsSpecificationVersion, gate: HumanGate) -> str:
    specification = version.specification.to_snapshot()
    codes = code_index(specification)
    lines = _version_lines(STAGE_LABELS["requirements"], version, gate)
    lines.extend(["## User twins in scope", ""])
    lines.extend(
        markdown_bullets(reference_text(item) for item in specification["user_twin_references"])
    )
    lines.extend(["", "## Requirements", ""])
    lines.extend(
        markdown_table(
            ("Code", "Title", "Kind", "Priority", "Statement", "Twins"),
            (
                (
                    item["code"],
                    item["title"],
                    item["kind"],
                    item["priority"],
                    item["statement"],
                    twin_names(item["user_twin_references"]),
                )
                for item in specification["requirements"]
            ),
        )
    )
    lines.extend(["", "## User stories", ""])
    for story in specification["user_stories"]:
        lines.append(
            f"- {story['code']}: as {story['user_twin_reference']['name']}, I want to "
            f"{story['goal']} so that I can {story['benefit']} "
            f"(requirements {code_list(story['requirement_ids'], codes)})."
        )
    lines.extend(["", "## Acceptance criteria", ""])
    lines.extend(
        markdown_table(
            ("Code", "Statement", "Verification", "Requirements", "User stories"),
            (
                (
                    item["code"],
                    item["statement"],
                    title_text(item["verification_method"]),
                    code_list(item["requirement_ids"], codes),
                    code_list(item["user_story_ids"], codes),
                )
                for item in specification["acceptance_criteria"]
            ),
        )
    )
    lines.extend(["", "## Usage scenarios", ""])
    for scenario in specification["scenarios"]:
        lines.extend(
            [
                f"### {scenario['code']}: {scenario['title']}",
                "",
                f"Actor {scenario['actor']['name']}. Trigger: {scenario['trigger']}",
                "",
                "Preconditions:",
                *markdown_bullets(scenario["preconditions"]),
                "",
                "Steps:",
                *[f"{index}. {step}" for index, step in enumerate(scenario["steps"], 1)],
                "",
                f"Expected outcome: {scenario['expected_outcome']} "
                f"(requirements {code_list(scenario['requirement_ids'], codes)}, criteria "
                f"{code_list(scenario['acceptance_criterion_ids'], codes)}).",
                "",
            ]
        )
    lines.extend(["## Risks", ""])
    lines.extend(_risk_line(risk, codes) for risk in specification["risks"])
    if not specification["risks"]:
        lines.append(f"- {UNSET}")
    lines.extend(["", "## Definition of done", ""])
    lines.extend(
        markdown_table(
            ("Code", "Statement", "Verification", "Applicability", "Condition", "Requirements"),
            (
                (
                    item["code"],
                    item["statement"],
                    title_text(item["verification_method"]),
                    item["applicability"],
                    item["condition"],
                    code_list(item["requirement_ids"], codes),
                )
                for item in specification["definition_of_done"]
            ),
        )
    )
    lines.append("")
    return "\n".join(lines)


def _alternative_codes(package: Mapping[str, object]) -> dict[str, str]:
    return {item["id"]: item["code"] for item in package["alternatives"]}


def _direction(item: Mapping[str, object]) -> str:
    visual = item.get("visual_language")
    if visual is not None:
        archetype = ARCHETYPES[LayoutArchetype(visual["choices"]["archetype"])]
        return f"Layout archetype {archetype.label}. {item['summary']}"
    approach = item.get("approach")
    if approach is not None:
        return f"Approach {title_text(approach)}. {item['summary']}"
    return item["summary"]


def design_markdown(
    version: DesignPackageVersion, gate: HumanGate, codes: Mapping[str, str]
) -> str:
    package = version.package.to_snapshot()
    alternatives = _alternative_codes(package)
    lines = _version_lines(STAGE_LABELS["design"], version, gate)
    selected = package["owner_selected_alternative_id"]
    recommended = package["recommended_alternative_id"]
    lines.extend(
        [
            f"Selected alternative: {alternatives.get(selected, UNSET)}. "
            f"Recommended alternative: {alternatives.get(recommended, UNSET)}.",
            "",
        ]
    )
    lines.extend(_generated_mockup_lines(package, alternatives))
    lines.extend(_owner_assertion_lines(package.get("owner_assertions") or ()))
    lines.extend(["## Alternatives", ""])
    for item in package["alternatives"]:
        lines.extend(
            [
                f"### {item['code']}: {item['title']}",
                "",
                _direction(item),
                "",
                f"Rationale: {item['rationale']}",
                "",
                f"Requirements {code_list(item['requirement_ids'], codes)}; user stories "
                f"{code_list(item['user_story_ids'], codes)}; acceptance criteria "
                f"{code_list(item['acceptance_criterion_ids'], codes)}; twins "
                f"{twin_names(item['user_twin_references']) or UNSET}.",
                "",
                "#### Workflows",
                "",
            ]
        )
        for workflow in item["workflows"]:
            lines.extend(
                [
                    f"- {workflow['code']}: {workflow['title']} "
                    f"(requirements {code_list(workflow['requirement_ids'], codes)})",
                    *[f"  {index}. {step}" for index, step in enumerate(workflow["steps"], 1)],
                ]
            )
        for key in (
            "information_architecture",
            "accessibility_considerations",
            "security_considerations",
            "advantages",
            "trade_offs",
            "assumptions",
            "open_questions",
        ):
            lines.extend(["", f"#### {title_text(key)}", "", *markdown_bullets(item[key])])
        lines.extend(_visual_language_lines(item.get("visual_language")))
        lines.append("")
    lines.extend(["## Concerns", ""])
    for concern in package["concerns"]:
        lines.append(
            f"- {concern['code']}: {concern['summary']} Mitigation: {concern['mitigation']} "
            f"(alternatives {code_list(concern['design_alternative_ids'], alternatives)}, "
            f"requirements {code_list(concern['requirement_ids'], codes)})"
        )
    if not package["concerns"]:
        lines.append(f"- {UNSET}")
    lines.extend(["", "## Open questions", "", *markdown_bullets(package["open_questions"]), ""])
    return "\n".join(lines)


def _generated_mockup_lines(
    package: Mapping[str, object], alternatives: Mapping[str, str]
) -> list[str]:
    generated = package.get("generated_mockup")
    if generated is None:
        return []
    mockup = generated["mockup"]
    return [
        f"Generated mockup: {mockup['title']}, "
        f"{counted(len(mockup['screens']), 'screen', 'screens')} written as HTML and CSS for "
        f"{alternatives.get(mockup['design_alternative_id'], UNSET)}. It opens from "
        "`mockup.html`; `mockups.md` describes its screens, elements and transitions.",
        "",
    ]


def _owner_assertion_lines(assertions: Sequence[str]) -> list[str]:
    if not assertions:
        return []
    return [
        "## Owner assertions",
        "",
        "Statements of the owner that the design must respect, in the order the owner gave them.",
        "",
        *(f"{number}. {assertion}" for number, assertion in enumerate(assertions, 1)),
        "",
    ]


def _visual_language_lines(visual: Mapping[str, object] | None) -> list[str]:
    if visual is None:
        return []
    choices = visual["choices"]
    described = ", ".join(
        f"{name.replace('_', ' ')} {title_text(value)}" for name, value in choices.items()
    )
    return [
        "",
        "#### Visual language",
        "",
        f"Product name: {visual['product_name']}. Catalog version {visual['catalog_version']}. "
        f"{described}.",
        "",
        f"Rationale: {visual['rationale']}",
        "",
        *markdown_bullets(f"{item['name']}: {item['statement']}" for item in visual["twin_fit"]),
        "",
        *markdown_table(("Role", "Colour"), visual["palette"].items()),
    ]


def _verdict_lines(critique: Mapping[str, object]) -> list[str]:
    verdict = critique.get("verdict")
    if verdict is None:
        return []
    return [f"Verdict: {verdict}", "", f"> {critique.get('quote') or UNSET}", ""]


def critiques_markdown(version: DesignPackageVersion) -> str:
    package = version.package.to_snapshot()
    alternatives = _alternative_codes(package)
    lines = ["# Twin critiques of the design alternatives", ""]
    for critique in sorted(
        package["critiques"],
        key=lambda item: (alternatives.get(item["design_alternative_id"], ""), item["code"]),
    ):
        twin = critique["user_twin_reference"]
        lines.extend(
            [
                f"## {critique['code']}: {twin['name']} on "
                f"{alternatives.get(critique['design_alternative_id'], UNSET)}",
                "",
                *_verdict_lines(critique),
                f"Confidence {critique['confidence']}, epistemic status "
                f"{critique['epistemic_status']}, human validation "
                f"{critique['human_validation']}. {critique['rationale']}",
                "",
            ]
        )
        for key in (
            "strengths",
            "concerns",
            "unmet_needs",
            "accessibility_observations",
            "trust_concerns",
            "questions",
            "suggested_changes",
        ):
            lines.extend([f"### {title_text(key)}", "", *markdown_bullets(critique[key]), ""])
    if not package["critiques"]:
        lines.append(f"{UNSET}.")
    return "\n".join(lines)


def mockups_markdown(version: DesignPackageVersion) -> str:
    package = version.package.to_snapshot()
    alternatives = _alternative_codes(package)
    prototype = package["prototype"]
    lines = ["# Mockups of the selected alternative", ""]
    if prototype is None:
        lines.append("No declarative prototype was recorded for the selected alternative.")
        return "\n".join(lines)
    screens = {screen["id"]: screen for screen in prototype["screens"]}
    elements = {
        element["id"]: element for screen in prototype["screens"] for element in screen["elements"]
    }
    lines.extend(
        [
            f"{prototype['code']}: {prototype['title']} for alternative "
            f"{alternatives.get(prototype['design_alternative_id'], UNSET)}. Viewports "
            f"{plain_text(prototype['supported_viewports'])}. Entry screen "
            f"{screens[prototype['entry_screen_id']]['code']}.",
            "",
        ]
    )
    if package.get("generated_mockup") is not None:
        lines.extend(
            [
                "The screens, elements and transitions below are derived from the HTML of the "
                "generated mockup in `mockup.html`: every screen is the section whose identifier "
                "is its code, every element carries its code in the attribute `data-elm`, and "
                "every transition is a link between two screens.",
                "",
            ]
        )
    for screen in prototype["screens"]:
        lines.extend(
            [f"## {screen['code']}: {screen['title']} ({title_text(screen['state'])})", ""]
        )
        lines.extend(
            markdown_table(
                ("Code", "Kind", "Content", "Accessible name", "Field", "Required", "Options"),
                (
                    (
                        element["code"],
                        title_text(element["kind"]),
                        element["content"],
                        element["accessible_name"],
                        element["field_name"],
                        element["required"],
                        element["options"],
                    )
                    for element in screen["elements"]
                ),
            )
        )
        lines.append("")
    lines.extend(["## Transitions", ""])
    for transition in prototype["transitions"]:
        trigger = elements.get(transition["trigger_element_id"], {})
        lines.append(
            f"- {transition['code']}: {screens[transition['source_screen_id']]['code']} "
            f"-> {screens[transition['target_screen_id']]['code']} through "
            f"{trigger.get('code', UNSET)} ({trigger.get('content', UNSET)}): "
            f"{transition['outcome']}"
        )
    if not prototype["transitions"]:
        lines.append(f"- {UNSET}")
    lines.append("")
    return "\n".join(lines)


def _links(entries: Sequence[Mapping[str, object]]) -> list[str]:
    links = [f"- [{_inline(entry['title'])}]({entry['path']})" for entry in entries]
    return links or [f"- {UNSET}"]


def views_markdown(
    *,
    tables: Sequence[Mapping[str, object]],
    diagrams: Sequence[Mapping[str, object]],
    mermaid_version: str,
) -> str:
    lines = [
        "",
        "## Views",
        "",
        "This document is the text view. The same content is in the tables (CSV) and in the "
        f"diagrams (Mermaid {mermaid_version}) below; the links are relative to this document.",
        "",
        "Tables:",
        *_links(tables),
        "",
        "Diagrams:",
        *_links(diagrams),
        "",
    ]
    return "\n".join(lines)


def twin_markdown(document: Mapping[str, object]) -> str:
    origin = document["origin"]
    persona = document["persona"]
    twin = document["twin"]
    profile = twin["profile"]
    persona_profile = persona["profile"]
    modeling = origin["user_modeling"]
    lines = [
        f"# {profile['name']}",
        "",
        f"User twin version {twin['version_number']}, content hash "
        f"`{twin['content_hash']}`, of the project {origin['project_name']}. "
        f"Validation status {profile['validation_status']}, human "
        f"validation {'required' if profile['requires_human_validation'] else 'not required'}. "
        f"Approved with user modeling version {modeling['version_number']} on "
        f"{origin['approved_at']}.",
        "",
        "A user twin is a model of a kind of user, not a person: its observations are "
        "assumptions with a declared epistemic status and confidence. `twin.json` next to this "
        "document is a self-contained copy that another OrchesTwin project can import.",
        "",
        "## Persona",
        "",
        f"{persona_profile['name']}: source {title_text(persona_profile['source'])}, "
        f"{title_text(persona_profile['kind'])}, "
        f"{title_text(persona_profile['confirmation_status'])}, version "
        f"{persona['version_number']}.",
        "",
        *observation_table(persona_profile["observations"]),
        "",
        "## Profile",
        "",
        *observation_table(profile["observations"]),
        "",
    ]
    return "\n".join(lines)


def _stage_rows(manifest: Mapping[str, object]) -> list[tuple[object, ...]]:
    return [
        (
            entry["label"],
            f"`{entry['text']}`",
            f"`{entry['document']}`",
            entry["version_number"],
            entry["content_hash"],
            entry["gate"]["gate_type"],
            entry["gate"]["updated_at"],
        )
        for entry in (manifest["stages"][stage] for stage in present_stages(manifest))
    ]


def _view_rows(manifest: Mapping[str, object]) -> list[tuple[object, ...]]:
    views = manifest["views"]
    return [
        (stage, form, f"`{entry['path']}`", entry["title"])
        for stage, view in ((name, views[name]) for name in VIEW_STAGES if name in views)
        for form, key in (
            ("text", "text"),
            ("table", "tables"),
            ("diagram", "diagrams"),
            ("mockup", "mockups"),
        )
        for entry in view[key]
    ]


def counted(number: int, singular: str, plural: str) -> str:
    return f"{number} {singular if number == 1 else plural}"


def feedback_counts(counts: Mapping[str, object]) -> str:
    return (
        f"{counted(counts['reviews'], 'review', 'reviews')} with "
        f"{counted(counts['findings'], 'finding', 'findings')}, "
        f"{counted(counts['decisions'], 'owner decision', 'owner decisions')}, "
        f"{counted(counts['discussions'], 'approved discussion', 'approved discussions')} and "
        f"{counted(counts['insights'], 'applied insight', 'applied insights')}"
    )


def progress_sentence(manifest: Mapping[str, object]) -> str:
    present = present_stages(manifest)
    held = f"This folder holds {len(present)} of {len(STAGES)} approved steps"
    if len(present) == len(STAGES):
        return f"{held}; every step is approved."
    return f"{held}; next: {STAGE_LABELS[STAGES[len(present)]]}."


def _scope_line(present: tuple[str, ...]) -> str:
    if "design" in present:
        return (
            "- Build against `requirements/requirements.md` and `design/design.md`: they are the "
            "approved scope. Requirements, user stories, acceptance criteria, screens and "
            "elements have stable codes (REQ-001, USR-001, AC-001, SCR-001, ELM-001): quote them "
            "in code reviews, commits and tests."
        )
    if "requirements" in present:
        return (
            "- The requirements are approved in `requirements/requirements.md`, with stable codes "
            "(REQ-001, USR-001, AC-001); the design comes into this folder once the owner "
            "approves it, and only then is the scope complete."
        )
    return (
        "- The scope is not approved yet: the requirements and the design come into this folder "
        "once the owner approves them, and only then is there an approved scope to build against."
    )


def _usage_lines(manifest: Mapping[str, object]) -> list[str]:
    present = present_stages(manifest)
    state = manifest.get("state")
    lines = [_scope_line(present)]
    if "twins" in present:
        lines.extend(
            [
                "- Judge every change from the point of view of the user twins in `twins/`: each "
                "twin has a profile with goals, constraints and accessibility needs.",
                "- Treat the twins as models: an observation or a finding is an assumption until "
                "a person validates it.",
            ]
        )
    lines.extend(
        [
            "- Do not edit the files of the approved stages: their digests are in "
            f"`{manifest['manifest']}`. A change of scope goes through the Studio and produces a "
            "new version of this folder.",
            f"- The feedback of the twins lives in `{manifest['feedback']['folder']}/`.",
        ]
    )
    if isinstance(state, Mapping):
        lines.append(
            f"- The state of the development is in `{state['text']}` and `{state['document']}`: "
            "the commits recorded in the Studio, the critiques of the twins on them, the "
            "decisions of the owner and the tasks for the code."
        )
    return lines


def _twin_lines(manifest: Mapping[str, object]) -> list[str]:
    if "twins" not in present_stages(manifest):
        return []
    return [
        "## User twins",
        "",
        *markdown_table(
            ("Twin", "Text", "Portable copy", "Version", "Validation status"),
            (
                (
                    twin["name"],
                    f"`{twin['text']}`",
                    f"`{twin['document']}`",
                    twin["version_number"],
                    twin["validation_status"],
                )
                for twin in manifest["twins"]
            ),
        ),
        "",
    ]


def _views_lines(manifest: Mapping[str, object]) -> list[str]:
    if not any(stage in manifest["views"] for stage in VIEW_STAGES):
        return []
    return [
        "## Views",
        "",
        "The approved requirements and design are available in three forms: text (Markdown), "
        f"tables (CSV) and diagrams (Mermaid {manifest['generator']['mermaid_version']}, linked "
        "from the Markdown documents).",
        "",
        *markdown_table(("Stage", "Form", "File", "Content"), _view_rows(manifest)),
        "",
    ]


def _feedback_lines(manifest: Mapping[str, object]) -> list[str]:
    feedback = manifest["feedback"]
    lines = ["## Twin feedback", ""]
    if feedback.get("text"):
        lines.append(
            f"`{feedback['text']}` summarises {feedback_counts(feedback)} recorded in the Studio. "
            "The exact records are in the JSON files of the same folder."
        )
    else:
        lines.append(
            "The feedback of the twins on the design comes into this folder once the design is "
            "approved."
        )
    if feedback.get("changes"):
        runs = counted(feedback.get("change_reviews") or 0, "review run", "review runs")
        lines.extend(
            ["", f"`{feedback['changes']}` holds {runs} of the twins on the code changes."]
        )
    return [*lines, ""]


def _overview_project(name: str, brief: Mapping[str, object], texts: Mapping[str, Any]) -> str:
    description = brief["fields"].get("description")
    if not isinstance(description, str) or not description.strip():
        return texts["project"].format(name=_bare(name))
    return texts["described"].format(name=_bare(name), description=excerpt(description))


def _role(profile: Mapping[str, object]) -> str | None:
    for observation in profile["observations"]:
        if observation["observation_key"] == _ROLE_KEY:
            text = observation["value"].get("text")
            return _bare(text) if isinstance(text, str) and text.strip() else None
    return None


def _twin_label(profile: Mapping[str, object]) -> str:
    name = _bare(profile["name"])
    role = _role(profile)
    if role is None or role.casefold() == name.casefold():
        return name
    return f"{name} ({role})"


def _overview_twins(twins: Mapping[str, object], texts: Mapping[str, Any]) -> list[str]:
    labels = [_twin_label(twin["profile"]) for twin in twins["twin_versions"]]
    return [texts["twins"].format(twins="; ".join(labels))] if labels else []


def _overview_must(specification: Mapping[str, object], texts: Mapping[str, Any]) -> list[str]:
    must = [item for item in specification["requirements"] if item["priority"] == _MUST]
    if not must:
        return []
    lines = [
        texts["must"],
        *(f"  - {item['code']} {_bare(item['title'])}" for item in must[:OVERVIEW_REQUIREMENTS]),
    ]
    hidden = len(must) - OVERVIEW_REQUIREMENTS
    if hidden > 0:
        one, many = texts["more"]
        lines.append(f"  - {(one if hidden == 1 else many).format(count=hidden)}")
    return lines


def _overview_design(package: Mapping[str, object], texts: Mapping[str, Any]) -> list[str]:
    selected = package.get("owner_selected_alternative_id")
    chosen = next((item for item in package["alternatives"] if item["id"] == selected), None)
    if chosen is None:
        return []
    title = _bare(chosen["title"])
    alternative = f"{chosen['code']} {title}"
    visual = chosen.get("visual_language")
    product = _bare(visual["product_name"]) if isinstance(visual, Mapping) else ""
    if product and product.casefold() != title.casefold():
        alternative = texts["product"].format(alternative=alternative, product=product)
    return [texts["design"].format(alternative=alternative)]


def _overview_criteria(specification: Mapping[str, object], texts: Mapping[str, Any]) -> list[str]:
    count = len(specification["acceptance_criteria"])
    if not count:
        return []
    one, many = texts["criteria"]
    line = one if count == 1 else many
    return [line.format(criteria=counted(count, *texts["criterion_words"]))]


def overview_lines(
    *,
    language: str,
    project_name: str,
    brief: Mapping[str, object],
    twins: Mapping[str, object] | None = None,
    specification: Mapping[str, object] | None = None,
    package: Mapping[str, object] | None = None,
) -> list[str]:
    texts = _OVERVIEW_TEXTS[language]
    lines = [texts["heading"], "", _overview_project(project_name, brief, texts)]
    if twins is not None:
        lines.extend(_overview_twins(twins, texts))
    if specification is not None:
        lines.extend(_overview_must(specification, texts))
    if package is not None:
        lines.extend(_overview_design(package, texts))
    if specification is not None:
        lines.extend(_overview_criteria(specification, texts))
    return [*lines, ""]


def index_markdown(
    manifest: Mapping[str, object],
    *,
    overview: Sequence[str] = (),
    development: Sequence[str] = (),
) -> str:
    project = manifest["project"]
    package = manifest["package"]
    lines = [
        f"# OrchesTwin knowledge folder: {project['name']}",
        "",
        f"Knowledge folder version {package['version_number']} of project {project['id']}, "
        f"written on {package['created_at']} with folder schema version "
        f"{manifest['schema_version']}. Content hash `{package['content_hash']}`.",
        "",
        *overview,
        "## What this folder is",
        "",
        f"The approved steps of this project ({_STEP_NAMES}), each approved by the owner through "
        "a human gate in OrchesTwin Studio: a step comes into this folder once it is approved. "
        f"{progress_sentence(manifest)} The project is implemented outside the Studio: this "
        "folder travels with the source code and tells people and coding agents what has to be "
        "built and for whom.",
        "",
        "## How to use it",
        "",
        *_usage_lines(manifest),
        "",
        "## Approved stages",
        "",
        *markdown_table(
            ("Stage", "Text", "Exact snapshot", "Version", "Content hash", "Gate", "Approved at"),
            _stage_rows(manifest),
        ),
        "",
        *_twin_lines(manifest),
        *_views_lines(manifest),
        *_feedback_lines(manifest),
        *development,
        "## Schema",
        "",
        f"`{manifest['manifest']}` is the machine-readable index of this folder. Every JSON "
        "document is described by a JSON Schema:",
        "",
        *markdown_table(
            ("Document", "Schema"),
            ((name, f"`{path}`") for name, path in manifest["schemas"].items()),
        ),
        "",
        "## Files",
        "",
        f"`{manifest['manifest']}` holds the SHA-256 digest of every file of this folder except "
        "itself and this index: the Studio and `ut` check the files against those digests before "
        "they accept a folder.",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "OVERVIEW_DESCRIPTION_LENGTH",
    "OVERVIEW_REQUIREMENTS",
    "UNSET",
    "brief_markdown",
    "code_index",
    "code_list",
    "counted",
    "critiques_markdown",
    "design_markdown",
    "excerpt",
    "feedback_counts",
    "index_markdown",
    "markdown_bullets",
    "markdown_table",
    "mockups_markdown",
    "observation_table",
    "overview_lines",
    "plain_text",
    "progress_sentence",
    "reference_text",
    "requirements_markdown",
    "team_markdown",
    "title_text",
    "twin_markdown",
    "twin_names",
    "twins_markdown",
    "views_markdown",
]
