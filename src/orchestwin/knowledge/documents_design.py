from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.visual_catalog import ARCHETYPES, LayoutArchetype
from orchestwin.artifacts.visual_directions import (
    DIRECTION_AXES,
    DirectionColour,
    DirectionDensity,
    DirectionLayout,
    DirectionShape,
    DirectionType,
)
from orchestwin.knowledge.documents_markdown import (
    UNSET,
    _sentence,
    _version_lines,
    code_list,
    counted,
    markdown_bullets,
    markdown_table,
    plain_text,
    title_text,
    twin_names,
)
from orchestwin.knowledge.layout import STAGE_LABELS
from orchestwin.models.design_systems import DESIGN_SYSTEMS
from orchestwin.workflow.gates import HumanGate

_VISUAL_AXIS_NAMES: Final = {
    "layout": "Layout",
    "shape": "Shapes",
    "type": "Type",
    "colour": "Colour",
    "density": "Density",
}
_VISUAL_AXIS_VALUES: Final[dict[str, dict[str, str]]] = {
    "layout": {
        DirectionLayout.PANELS: "Panels",
        DirectionLayout.BANDS: "Bands",
        DirectionLayout.EDITORIAL: "Editorial page",
        DirectionLayout.STAGE: "Stage",
        DirectionLayout.WORKBENCH: "Workbench",
        DirectionLayout.MOSAIC: "Mosaic",
    },
    "shape": {
        DirectionShape.ROUNDED_OUTLINE: "Rounded outlines",
        DirectionShape.SQUARE_RULES: "Square corners and rules",
        DirectionShape.HEAVY_FRAME: "Heavy frames",
        DirectionShape.SOFT_FILL: "Filled surfaces",
        DirectionShape.PILL: "Pills",
    },
    "type": {
        DirectionType.EVEN: "Restrained scale",
        DirectionType.DISPLAY: "Very large titles",
        DirectionType.CAPS_LABELS: "Upper-case labels",
        DirectionType.READING: "Reading",
    },
    "colour": {
        DirectionColour.ACCENT_ONLY: "Colour on the action only",
        DirectionColour.FIELDS: "Fields of colour",
        DirectionColour.INK: "Almost monochrome",
        DirectionColour.TINTED: "Tinted surfaces",
    },
    "density": {
        DirectionDensity.COMPACT: "Compact",
        DirectionDensity.COMFORTABLE: "Comfortable",
        DirectionDensity.SPACIOUS: "Spacious",
    },
}
_VISUAL_DIRECTION_ORIGIN: Final = (
    "Proposed by the model among {count} candidates; chosen by the Studio because it is far from "
    "the other."
)
_SYSTEM_DIRECTION_ORIGIN: Final = "Direction of the {name} design system."


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


def _design_system_name(identifier: str) -> str:
    system = DESIGN_SYSTEMS.get(identifier)
    return identifier if system is None else system.name


def _design_system_lines(identifier: str | None) -> list[str]:
    if identifier is None:
        return []
    return [f"Design system: {_design_system_name(identifier)}.", ""]


def _visual_direction_lines(
    direction: Mapping[str, object] | None, *, system: str | None = None
) -> list[str]:
    if direction is None:
        return []
    axes = direction["axes"]
    positions = " ".join(
        f"{_VISUAL_AXIS_NAMES[axis]}: {_VISUAL_AXIS_VALUES[axis][axes[axis]]}."
        for axis in DIRECTION_AXES
    )
    return [
        f"Visual direction: {_sentence(direction['name'])}",
        "",
        str(direction["concept"]),
        "",
        positions,
        "",
        *markdown_bullets(direction["rules"]),
        "",
        _VISUAL_DIRECTION_ORIGIN.format(count=direction["candidates"])
        if system is None
        else _SYSTEM_DIRECTION_ORIGIN.format(name=_design_system_name(system)),
        "",
    ]


def _visual_language_lines(visual: Mapping[str, object] | None) -> list[str]:
    if visual is None:
        return []
    choices = visual["choices"]
    described = ", ".join(
        f"{name.replace('_', ' ')} {title_text(value)}" for name, value in choices.items()
    )
    identifier = visual.get("design_system")
    system = identifier if isinstance(identifier, str) else None
    return [
        "",
        "#### Visual language",
        "",
        *_design_system_lines(system),
        *_visual_direction_lines(visual.get("direction"), system=system),
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
