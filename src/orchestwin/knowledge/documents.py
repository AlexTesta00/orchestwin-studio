from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from orchestwin.agents.proposals import TeamProposalVersion
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.visual_catalog import ARCHETYPES, LayoutArchetype
from orchestwin.knowledge.layout import STAGE_LABELS, STAGES, VIEW_STAGES
from orchestwin.projects.briefs import ProjectBriefVersion
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.twins.user_twins import UserModelingSnapshotVersion
from orchestwin.workflow.gates import HumanGate

UNSET: Final = "not provided"


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
        f"approved by gate {gate.gate_type.value} on {gate.updated_at.isoformat()}.",
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


def team_markdown(version: TeamProposalVersion, gate: HumanGate) -> str:
    snapshot = version.proposal.to_snapshot()
    lines = _version_lines(STAGE_LABELS["team"], version, gate)
    lines.extend(
        [
            f"Project mode: {snapshot['project_mode']}. Provider: "
            f"{snapshot['provider']['provider_id']} v{snapshot['provider']['provider_version']}.",
            "",
            "## Members",
            "",
        ]
    )
    rows = []
    for member in snapshot["members"]:
        justifications = "; ".join(
            item["statement"] or f"{item['kind']} {item['code']}"
            for item in member["justifications"]
        )
        rows.append((title_text(member["agent_id"]), title_text(member["source"]), justifications))
    lines.extend(markdown_table(("Agent", "Source", "Justification"), rows))
    lines.extend(["", "## Role constraints", ""])
    rows = [
        (
            title_text(constraint["agent_id"]),
            constraint["kind"],
            "; ".join(reason["code"] for reason in constraint["reasons"]),
        )
        for constraint in snapshot["constraints"]["role_constraints"]
    ]
    lines.extend(
        markdown_table(
            (
                "Agent",
                "Constraint",
                "Reasons",
            ),
            rows,
        )
    )
    lines.append("")
    return "\n".join(lines)


def twins_markdown(version: UserModelingSnapshotVersion, gate: HumanGate) -> str:
    snapshot = version.snapshot.to_snapshot()
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
        lines.extend(
            [
                f"### {profile['name']}",
                "",
                f"Twin {twin['twin_id']} version {twin['version_number']}, "
                f"validation status {profile['validation_status']}, human validation "
                f"{'required' if profile['requires_human_validation'] else 'not required'}, "
                f"persona {reference_text(profile['persona_reference'])}.",
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
    lines.extend(markdown_bullets(specification["risks"]))
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
        f"Product name: {visual['product_name']}. Catalog version {visual['catalog_version']} "
        f"({visual['catalog_content_hash']}). {described}.",
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


def views_markdown(
    *,
    tables: Sequence[str],
    diagrams: Sequence[Mapping[str, object]],
    mermaid_version: str,
) -> str:
    lines = [
        "",
        "## Views",
        "",
        "This document is the text view. The same content is available as tables and as "
        f"diagrams written for Mermaid {mermaid_version}; paths are relative to this folder.",
        "",
        "Tables:",
        *markdown_bullets(f"`{path}`" for path in tables),
        "",
        "Diagrams:",
        *markdown_bullets(f"`{diagram['path']}`: {diagram['title']}" for diagram in diagrams),
        "",
    ]
    for diagram in diagrams:
        lines.extend(
            [
                f"### {diagram['title']}",
                "",
                str(diagram["description"]),
                "",
                "```mermaid",
                str(diagram["source"]).rstrip("\n"),
                "```",
                "",
            ]
        )
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
        f"User twin {twin['twin_id']} version {twin['version_number']}, content hash "
        f"`{twin['content_hash']}`, of the project {origin['project_name']} "
        f"({origin['project_id']}). Validation status {profile['validation_status']}, human "
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
        for entry in (manifest["stages"][stage] for stage in STAGES)
    ]


def _view_rows(manifest: Mapping[str, object]) -> list[tuple[object, ...]]:
    return [
        (stage, form, f"`{entry['path']}`", entry["title"])
        for stage, view in ((name, manifest["views"][name]) for name in VIEW_STAGES)
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


def index_markdown(manifest: Mapping[str, object]) -> str:
    project = manifest["project"]
    package = manifest["package"]
    feedback = manifest["feedback"]
    lines = [
        f"# OrchesTwin knowledge folder: {project['name']}",
        "",
        f"Knowledge folder version {package['version_number']} of project {project['id']}, "
        f"written on {package['created_at']} with folder schema version "
        f"{manifest['schema_version']}. Content hash `{package['content_hash']}`.",
        "",
        "## What this folder is",
        "",
        "The brief, the agent team, the user twins, the requirements and the design of this "
        "project, each approved by the owner through a human gate in OrchesTwin Studio. The "
        "project is implemented outside the Studio: this folder travels with the source code "
        "and tells people and coding agents what has to be built and for whom.",
        "",
        "## How to use it",
        "",
        "- Build against `requirements/requirements.md` and `design/design.md`: they are the "
        "approved scope. Requirements, user stories, acceptance criteria, screens and elements "
        "have stable codes (REQ-001, USR-001, AC-001, SCR-001, ELM-001): quote them in code "
        "reviews, commits and tests.",
        "- Judge every change from the point of view of the user twins in `twins/`: each twin "
        "has a profile with goals, constraints and accessibility needs.",
        "- Treat the twins as models: an observation or a finding is an assumption until a "
        "person validates it.",
        "- Do not edit the files of the approved stages: their hashes are listed below and in "
        f"`{manifest['manifest']}`. A change of scope goes through the Studio and produces a "
        "new version of this folder.",
        f"- The feedback of the twins lives in `{feedback['folder']}/`.",
        "",
        "## Approved stages",
        "",
        *markdown_table(
            ("Stage", "Text", "Exact snapshot", "Version", "Content hash", "Gate", "Approved at"),
            _stage_rows(manifest),
        ),
        "",
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
        "## Views",
        "",
        "Requirements and design are available in three forms: text (Markdown), tables (CSV) "
        f"and diagrams (Mermaid {manifest['generator']['mermaid_version']}, also embedded in the "
        "Markdown documents).",
        "",
        *markdown_table(("Stage", "Form", "File", "Content"), _view_rows(manifest)),
        "",
        "## Twin feedback",
        "",
        f"`{feedback['text']}` summarises {feedback_counts(feedback)} recorded in the Studio. "
        "The exact records are in the JSON files of the same folder.",
        "",
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
        *markdown_table(("File", "SHA-256"), manifest["files"].items()),
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "UNSET",
    "brief_markdown",
    "code_index",
    "code_list",
    "counted",
    "critiques_markdown",
    "design_markdown",
    "feedback_counts",
    "index_markdown",
    "markdown_bullets",
    "markdown_table",
    "mockups_markdown",
    "observation_table",
    "plain_text",
    "reference_text",
    "requirements_markdown",
    "team_markdown",
    "title_text",
    "twin_markdown",
    "twin_names",
    "twins_markdown",
    "views_markdown",
]
