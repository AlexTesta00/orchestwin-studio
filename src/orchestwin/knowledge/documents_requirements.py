from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final

from orchestwin.knowledge.documents_markdown import (
    UNSET,
    _sentence,
    _version_lines,
    code_list,
    markdown_bullets,
    markdown_table,
    title_text,
    twin_names,
)
from orchestwin.knowledge.layout import STAGE_LABELS
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.workflow.gates import HumanGate


def _lowered(value: object) -> str:
    return str(value).replace("_", " ").lower()


def reference_text(reference: Mapping[str, object]) -> str:
    if "name" in reference:
        return f"{reference['name']} (v{reference['version_number']})"
    identifier = reference.get("artifact_id", reference.get("persona_id", reference.get("id")))
    return f"{identifier} v{reference.get('version_number')}"


def code_index(specification: Mapping[str, object]) -> dict[str, str]:
    codes: dict[str, str] = {}
    for key in (
        "needs",
        "requirements",
        "user_stories",
        "acceptance_criteria",
        "scenarios",
        "definition_of_done",
    ):
        for item in specification.get(key, ()):
            codes[item["id"]] = item["code"]
    return codes


def _risk_line(risk: Mapping[str, object], codes: Mapping[str, str]) -> str:
    return (
        f"- {risk['code']}: {_sentence(risk['summary'])} Likelihood "
        f"{_lowered(risk['likelihood'])}, impact {_lowered(risk['impact'])}. Mitigation: "
        f"{_sentence(risk['mitigation'])} Requirements {code_list(risk['requirement_ids'], codes)}."
    )


def _legacy_requirements_markdown(
    version: RequirementsSpecificationVersion, gate: HumanGate
) -> str:
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


_DEFINITION_TEXTS: Final = {
    "en": {
        "definition": "Definition",
        "twins": "User twins",
        "scenarios": "Scenarios",
        "needs": "Needs",
        "journeys": "Journey",
        "phases": "Phases",
        "action": "Action",
        "touchpoint": "Touchpoint",
        "stories": "User stories",
        "actor": "Actor",
        "context": "Context",
        "goal": "Goal",
        "trigger": "Trigger",
        "steps": "Steps",
        "criticalities": "Potential difficulties",
        "sources": "Sources",
        "preconditions": "Preconditions",
        "outcome": "Expected outcome",
        "benefit": "Benefit",
        "requirements": "Requirements",
        "criteria": "Acceptance criteria",
        "risks": "Risks",
        "done": "Definition of done",
        "verification": "Verification",
        "mitigation": "Mitigation",
        "priority": "Priority",
        "condition": "Condition",
        "likelihood": "Likelihood",
        "impact": "Impact",
        "review_status": "Review status",
        "applicability": "Applicability",
        "warning": "This definition comes from the brief and the twins: it still needs to be checked with real users.",
        "legacy": "This definition has no needs: they were not recorded in this version.",
        "FUNCTIONAL": "Functional requirements",
        "NON_FUNCTIONAL": "Non-functional requirements",
        "CONSTRAINT": "Constraints",
    },
    "it": {
        "definition": "Definizione",
        "twins": "Twin degli utenti",
        "scenarios": "Scenari",
        "needs": "Bisogni",
        "journeys": "Journey",
        "phases": "Fasi",
        "action": "Azione",
        "touchpoint": "Punto di contatto",
        "stories": "Storie",
        "actor": "Attore",
        "context": "Contesto",
        "goal": "Obiettivo",
        "trigger": "Evento iniziale",
        "steps": "Passi",
        "criticalities": "Criticità",
        "sources": "Fonti",
        "preconditions": "Precondizioni",
        "outcome": "Risultato atteso",
        "benefit": "Beneficio",
        "requirements": "Requisiti",
        "criteria": "Criteri di accettazione",
        "risks": "Rischi",
        "done": "Condizioni di completamento",
        "verification": "Verifica",
        "mitigation": "Mitigazione",
        "priority": "Priorità",
        "condition": "Condizione",
        "likelihood": "Probabilità",
        "impact": "Impatto",
        "review_status": "Stato di revisione",
        "applicability": "Applicabilità",
        "warning": "Questa definizione deriva dal brief e dai twin: resta da verificare con utenti reali.",
        "legacy": "Questa definizione non contiene bisogni: non erano registrati in questa versione.",
        "FUNCTIONAL": "Requisiti funzionali",
        "NON_FUNCTIONAL": "Requisiti non funzionali",
        "CONSTRAINT": "Vincoli",
    },
}


def requirements_markdown(
    version: RequirementsSpecificationVersion, gate: HumanGate, *, locale: str = "en"
) -> str:
    specification = version.specification.to_snapshot()
    language = locale if locale in _DEFINITION_TEXTS else "en"
    if language == "en" and specification["schema_version"] == 1:
        return _legacy_requirements_markdown(version, gate)
    text = _DEFINITION_TEXTS[language]
    collections = (
        "scenarios",
        "journeys",
        "needs",
        "user_stories",
        "requirements",
        "acceptance_criteria",
        "risks",
        "definition_of_done",
    )
    items = {str(item["id"]): item for key in collections for item in specification.get(key, ())}
    twin_anchors = {
        str(item["twin_id"]): f"twin-{index}"
        for index, item in enumerate(
            sorted(
                specification["user_twin_references"], key=lambda item: str(item["name"]).casefold()
            ),
            1,
        )
    }

    def links(identifiers: Iterable[object]) -> str:
        return (
            ", ".join(
                f"[{items[str(identifier)]['code']} · {items[str(identifier)].get('title', items[str(identifier)].get('goal', items[str(identifier)].get('statement', items[str(identifier)].get('summary', ''))))}](#{str(items[str(identifier)]['code']).lower()})"
                for identifier in identifiers
                if str(identifier) in items
            )
            or "—"
        )

    def heading(item: Mapping[str, object], title: object) -> list[str]:
        return [f"### {item['code']}: {title}", "", f'<a id="{str(item["code"]).lower()}"></a>', ""]

    def sources(item: Mapping[str, object]) -> list[str]:
        references = item.get("sources", ())
        if not references:
            return []
        known = {
            str(reference["twin_id"]): str(reference["name"])
            for reference in specification["user_twin_references"]
        }
        known[str(specification["context"]["project_brief"]["artifact_id"])] = (
            "Brief di progetto" if language == "it" else "Project brief"
        )
        labels = {
            "PROJECT_BRIEF": "Brief di progetto" if language == "it" else "Project brief",
            "USER_TWIN": "Twin utente" if language == "it" else "User twin",
            "OWNER_INPUT": "Indicazione del proprietario" if language == "it" else "Owner input",
            "MODEL_PROPOSAL": "Proposta del modello" if language == "it" else "Model proposal",
            "SYSTEM_ARTIFACT": "Artefatto di sistema" if language == "it" else "System artifact",
        }
        return [
            f"<details><summary>{text['sources']}</summary>",
            "",
            *markdown_bullets(
                " · ".join(
                    str(value)
                    for value in (
                        known.get(str(source["source_id"]), labels[str(source["kind"])]),
                        source.get("source_version"),
                        source.get("locator"),
                        source["source_id"]
                        if str(source["source_id"]) not in known
                        and source["kind"] not in ("PROJECT_BRIEF", "USER_TWIN")
                        else None,
                    )
                    if value is not None
                )
                for source in references
            ),
            "",
            "</details>",
            "",
        ]

    version_word = "Versione" if language == "it" else "Version"
    lines = [
        f"# {text['definition']}",
        "",
        (
            f"Versione {version.version_number}, hash del contenuto `{version.content_hash}`, approvata dal proprietario il {gate.updated_at.isoformat()}."
            if language == "it"
            else f"{version_word} {version.version_number}, content hash `{version.content_hash}`, approved by the owner on {gate.updated_at.isoformat()}."
        ),
        "",
        text["warning"],
        "",
        f"## {text['twins']}",
        "",
    ]
    for reference in specification["user_twin_references"]:
        lines.extend(
            [
                f'<a id="{twin_anchors[str(reference["twin_id"])]}"></a>',
                f"- {reference_text(reference)} · {text['scenarios']}: {links(item['id'] for item in specification['scenarios'] if item['actor']['twin_id'] == reference['twin_id'])}",
                "",
            ]
        )
    lines.extend(["", f"## {text['scenarios']}", ""])
    for scenario in specification["scenarios"]:
        lines.extend(heading(scenario, scenario["title"]))
        lines.append(
            f"{text['actor']}: [{scenario['actor']['name']}](#{twin_anchors[str(scenario['actor']['twin_id'])]})"
        )
        for field in ("context", "goal", "trigger"):
            if scenario.get(field):
                lines.extend(["", f"{text[field]}: {scenario[field]}"])
        for field in ("preconditions", "steps", "criticalities"):
            if scenario.get(field):
                values = (
                    [f"{index}. {step}" for index, step in enumerate(scenario[field], 1)]
                    if field == "steps"
                    else markdown_bullets(scenario[field])
                )
                lines.extend(["", f"{text[field]}:", *values])
        revealed = [
            need["id"]
            for need in specification.get("needs", ())
            if scenario["id"] in need["scenario_ids"]
        ]
        lines.extend(
            [
                "",
                f"{text['outcome']}: {scenario['expected_outcome']}",
                f"{text['needs']}: {links(revealed)}",
                f"{text['requirements']}: {links(scenario['requirement_ids'])}",
                f"{text['criteria']}: {links(scenario['acceptance_criterion_ids'])}",
                *(
                    [
                        f"{text['journeys']}: {links(item['id'] for item in specification['journeys'] if item['scenario_id'] == scenario['id'])}"
                    ]
                    if specification.get("journeys")
                    else []
                ),
                "",
                *sources(scenario),
            ]
        )
    if specification.get("journeys"):
        lines.extend([f"## {text['journeys']}", ""])
        for journey in specification["journeys"]:
            scenario = items[str(journey["scenario_id"])]
            lines.extend(
                [
                    *heading(journey, journey["title"]),
                    f"{text['scenarios']}: {links([journey['scenario_id']])}",
                    f"{text['actor']}: [{scenario['actor']['name']}](#{twin_anchors[str(scenario['actor']['twin_id'])]})",
                    "",
                    f"{text['phases']}:",
                    "",
                ]
            )
            for index, phase in enumerate(journey["phases"], 1):
                lines.extend(
                    [
                        f"#### {index}. {phase['title']}",
                        "",
                        f"{text['action']}: {phase['action']}",
                        f"{text['needs']}: {links(phase['need_ids'])}",
                        "",
                    ]
                )
                if phase.get("touchpoint"):
                    lines.extend([f"{text['touchpoint']}: {phase['touchpoint']}", ""])
                if phase.get("criticalities"):
                    lines.extend(
                        [f"{text['criticalities']}:", *markdown_bullets(phase["criticalities"]), ""]
                    )
            lines.extend(sources(journey))
    lines.extend([f"## {text['needs']}", ""])
    if not specification.get("needs"):
        lines.extend([text["legacy"], ""])
    for need in specification.get("needs", ()):
        lines.extend(
            [
                *heading(need, need["title"]),
                str(need["statement"]),
                "",
                f"{text['scenarios']}: {links(need['scenario_ids'])}",
                f"{text['stories']}: {links(item['id'] for item in specification['user_stories'] if need['id'] in item.get('need_ids', ()))}",
                f"{text['requirements']}: {links(item['id'] for item in specification['requirements'] if need['id'] in item.get('need_ids', ()))}",
                *(
                    [
                        f"{text['journeys']}: {links(item['id'] for item in specification['journeys'] if any(need['id'] in phase['need_ids'] for phase in item['phases']))}"
                    ]
                    if specification.get("journeys")
                    else []
                ),
                "",
                *sources(need),
            ]
        )
    lines.extend([f"## {text['stories']}", ""])
    for story in specification["user_stories"]:
        lines.extend(
            [
                *heading(story, story["goal"]),
                f"{text['actor']}: {story['user_twin_reference']['name']}",
                f"{text['goal']}: {story['goal']}",
                f"{text['benefit']}: {story['benefit']}",
                f"{text['needs']}: {links(story.get('need_ids', ()))}",
                f"{text['requirements']}: {links(story['requirement_ids'])}",
                "",
            ]
        )
    for kind in ("FUNCTIONAL", "NON_FUNCTIONAL", "CONSTRAINT"):
        lines.extend([f"## {text[kind]}", ""])
        for item in specification["requirements"]:
            if item["kind"] == kind:
                lines.extend(
                    [
                        *heading(item, item["title"]),
                        str(item["statement"]),
                        "",
                        f"{text['priority']}: {item['priority']}",
                        f"{text['twins']}: {twin_names(item['user_twin_references'])}",
                        f"{text['needs']}: {links(item.get('need_ids', ()))}",
                        "",
                        *sources(item),
                    ]
                )
    for key, label, field in (
        ("acceptance_criteria", "criteria", "statement"),
        ("risks", "risks", "summary"),
        ("definition_of_done", "done", "statement"),
    ):
        lines.extend([f"## {text[label]}", ""])
        for item in specification[key]:
            lines.extend(
                [
                    *heading(item, item[field]),
                    f"{text['requirements']}: {links(item['requirement_ids'])}",
                ]
            )
            if "user_story_ids" in item:
                lines.append(f"{text['stories']}: {links(item['user_story_ids'])}")
            for name in (
                "verification_method",
                "mitigation",
                "condition",
                "likelihood",
                "impact",
                "review_status",
                "applicability",
            ):
                if item.get(name):
                    lines.append(
                        f"{text['verification' if name == 'verification_method' else name]}: {item[name]}"
                    )
            lines.extend(["", *sources(item)])
    return "\n".join(lines)
