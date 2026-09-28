from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

MERMAID_VERSION: Final = "12.0.0"
DIAGRAM_LOCALES: Final = ("en", "it")
DEFAULT_DIAGRAM_LOCALE: Final = "en"
DIAGRAM_EXTENSION: Final = ".mmd"

_LABEL_WIDTH: Final = 34
_SHORT_TEXT: Final = 72
_INDENT: Final = "  "
_ELLIPSIS: Final = "…"
_ENTITIES: Final = {
    '"': "#quot;",
    "#": "#35;",
    "<": "#lt;",
    ">": "#gt;",
    "&": "#amp;",
    "`": "#96;",
    "{": "#123;",
    "}": "#125;",
    "[": "#91;",
    "]": "#93;",
    "(": "#40;",
    ")": "#41;",
    "|": "#124;",
    ";": "#59;",
    ":": "#58;",
    "%": "#37;",
    "\\": "#92;",
}
_PLAIN_PUNCTUATION: Final = frozenset(" .,'-·")
_REQUIREMENT_TYPES: Final = {
    "FUNCTIONAL": "functionalRequirement",
    "NON_FUNCTIONAL": "requirement",
    "CONSTRAINT": "designConstraint",
}
_VERIFICATION_METHODS: Final = {
    "AUTOMATED_TEST": "Test",
    "MANUAL_REVIEW": "Inspection",
    "INSPECTION": "Inspection",
    "DEMONSTRATION": "Demonstration",
    "ANALYSIS": "Analysis",
}
_RISK_LEVELS: Final = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 3}
_RISK_NAMES: Final = {1: "Low", 2: "Medium", 3: "High"}
_NOUNS: Final = {
    "en": {
        "actor": ("actor", "actors"),
        "case": ("use case", "use cases"),
        "requirement": ("requirement", "requirements"),
        "criterion": ("acceptance criterion", "acceptance criteria"),
        "scenario": ("usage scenario", "usage scenarios"),
        "twin": ("user twin", "user twins"),
        "story": ("user story", "user stories"),
        "risk": ("risk", "risks"),
        "done": ("definition of done item", "definition of done items"),
        "flow": ("workflow", "workflows"),
        "step": ("step", "steps"),
        "screen": ("screen", "screens"),
        "transition": ("transition", "transitions"),
        "element": ("element", "elements"),
    },
    "it": {
        "actor": ("attore", "attori"),
        "case": ("caso d'uso", "casi d'uso"),
        "requirement": ("requisito", "requisiti"),
        "criterion": ("criterio di accettazione", "criteri di accettazione"),
        "scenario": ("scenario d'uso", "scenari d'uso"),
        "twin": ("user twin", "user twin"),
        "story": ("storia utente", "storie utente"),
        "risk": ("rischio", "rischi"),
        "done": ("voce della definizione di fatto", "voci della definizione di fatto"),
        "flow": ("flusso", "flussi"),
        "step": ("passo", "passi"),
        "screen": ("schermata", "schermate"),
        "transition": ("transizione", "transizioni"),
        "element": ("elemento", "elementi"),
    },
}
_TEXT: Final = {
    "en": {
        "use_cases": "Use cases",
        "use_cases_description": (
            "Use case diagram of {system}: {actors} and {cases}. "
            "Every use case is the goal of a user story."
        ),
        "requirements": "Requirements",
        "requirements_description": (
            "Requirement diagram: {requirements} with kind, risk and verification method, "
            "verified by {criteria} and {scenarios}."
        ),
        "requirements_traceability": "Requirements traceability",
        "requirements_traceability_description": (
            "Traceability from {twins} through {stories} to {requirements}, {criteria} and "
            "{scenarios}, with {risks} and {done}."
        ),
        "workflows": "Workflows of {code}",
        "workflows_description": (
            "Activity flow of alternative {code}, {title}: {flows} and {steps}. "
            "Every workflow is followed by the requirements it covers."
        ),
        "screen_map": "Screen map of {code}",
        "screen_map_description": (
            "Navigation among {screens} of the mockup of alternative {code} through "
            "{transitions}, starting from {entry}."
        ),
        "design_traceability": "Design traceability of {code}",
        "design_traceability_description": (
            "Coverage of {requirements} by {flows} and {screens} of alternative {code}. {gaps}"
        ),
        "gaps_none": "Every requirement is covered.",
        "gaps_one": "1 requirement is not covered.",
        "gaps_many": "{count} requirements are not covered.",
        "twins": "User twins",
        "stories": "User stories",
        "criteria": "Acceptance criteria",
        "scenarios": "Usage scenarios",
        "risks": "Risks",
        "done": "Definition of done",
        "screens": "Screens",
        "flows": "Workflows",
        "affects": "affects",
        "governs": "governs",
        "exercised_by": "exercised by",
        "start": "Start",
        "end": "End",
        "covers": "Covers",
        "criterion_type": "acceptance criterion",
        "scenario_type": "usage scenario",
        "state_DEFAULT": "default",
        "state_EMPTY": "empty",
        "state_ERROR": "error",
        "state_SUCCESS": "success",
    },
    "it": {
        "use_cases": "Casi d'uso",
        "use_cases_description": (
            "Diagramma dei casi d'uso di {system}: {actors} e {cases}. "
            "Ogni caso d'uso è l'obiettivo di una storia utente."
        ),
        "requirements": "Requisiti",
        "requirements_description": (
            "Diagramma dei requisiti: {requirements} con tipo, rischio e metodo di verifica, "
            "con {criteria} e {scenarios} che li verificano."
        ),
        "requirements_traceability": "Tracciabilità dei requisiti",
        "requirements_traceability_description": (
            "Tracciabilità da {twins}, attraverso {stories}, a {requirements}, {criteria} e "
            "{scenarios}, con {risks} e {done}."
        ),
        "workflows": "Flussi di {code}",
        "workflows_description": (
            "Flusso di attività dell'alternativa {code}, {title}: {flows} e {steps}. "
            "Ogni flusso è seguito dai requisiti che copre."
        ),
        "screen_map": "Mappa delle schermate di {code}",
        "screen_map_description": (
            "Navigazione fra {screens} del mockup dell'alternativa {code} attraverso "
            "{transitions}, a partire da {entry}."
        ),
        "design_traceability": "Tracciabilità del design di {code}",
        "design_traceability_description": (
            "Copertura di {requirements} da parte di {flows} e {screens} dell'alternativa "
            "{code}. {gaps}"
        ),
        "gaps_none": "Ogni requisito è coperto.",
        "gaps_one": "1 requisito non è coperto.",
        "gaps_many": "{count} requisiti non sono coperti.",
        "twins": "User twin",
        "stories": "Storie utente",
        "criteria": "Criteri di accettazione",
        "scenarios": "Scenari d'uso",
        "risks": "Rischi",
        "done": "Definizione di fatto",
        "screens": "Schermate",
        "flows": "Flussi",
        "affects": "riguarda",
        "governs": "regola",
        "exercised_by": "esercitato da",
        "start": "Inizio",
        "end": "Fine",
        "covers": "Copre",
        "criterion_type": "criterio di accettazione",
        "scenario_type": "scenario d'uso",
        "state_DEFAULT": "predefinito",
        "state_EMPTY": "vuoto",
        "state_ERROR": "errore",
        "state_SUCCESS": "successo",
    },
}


class DiagramStage(StrEnum):
    REQUIREMENTS = "requirements"
    DESIGN = "design"


class DiagramKind(StrEnum):
    USE_CASES = "USE_CASES"
    REQUIREMENTS = "REQUIREMENTS"
    REQUIREMENTS_TRACEABILITY = "REQUIREMENTS_TRACEABILITY"
    WORKFLOWS = "WORKFLOWS"
    SCREEN_MAP = "SCREEN_MAP"
    DESIGN_TRACEABILITY = "DESIGN_TRACEABILITY"


@dataclass(frozen=True, slots=True)
class Diagram:
    key: str
    stage: DiagramStage
    kind: DiagramKind
    subject: str | None
    title: str
    description: str
    source: str

    @property
    def path(self) -> str:
        stage, name = self.key.split("/", 1)
        return f"{stage}/diagrams/{name}{DIAGRAM_EXTENSION}"

    def to_snapshot(self) -> dict[str, object]:
        return {
            "key": self.key,
            "stage": self.stage.value,
            "kind": self.kind.value,
            "subject": self.subject,
            "title": self.title,
            "description": self.description,
            "path": self.path,
            "source": self.source,
        }


def diagram_locale(locale: str | None) -> str:
    return locale if locale in DIAGRAM_LOCALES else DEFAULT_DIAGRAM_LOCALE


def _normal(text: object) -> str:
    return " ".join(str(text).split())


def _escape(text: str) -> str:
    return "".join(_ENTITIES.get(character, character) for character in text if character >= " ")


def _short(text: object, limit: int = _SHORT_TEXT) -> str:
    value = _normal(text)
    if len(value) <= limit:
        return value
    cut = value[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:")
    return f"{cut or value[: limit - 1]}{_ELLIPSIS}"


def _lines(text: object, width: int = _LABEL_WIDTH) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in _normal(text).split(" "):
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def _label(*parts: object, width: int = _LABEL_WIDTH) -> str:
    lines = [line for part in parts for line in _lines(part, width)]
    return "<br/>".join(_escape(line) for line in lines)


def _line(text: object) -> str:
    return _escape(_normal(text))


def _plain(text: object) -> str:
    value = "".join(
        character if character.isalnum() or character in _PLAIN_PUNCTUATION else " "
        for character in str(text).replace(":", ",").replace(";", ",")
    )
    return _normal(value).replace(" ,", ",")


def _count(locale: str, noun: str, items: object) -> str:
    number = items if isinstance(items, int) else len(items)
    singular, plural = _NOUNS[locale][noun]
    return f"{number} {singular if number == 1 else plural}"


def _identifier(code: object) -> str:
    value = "".join(character for character in str(code) if character.isalnum())
    return value if value[:1].isalpha() else f"N{value}"


def _accessibility(title: str, description: str) -> list[str]:
    return [
        f"{_INDENT}accTitle: {_plain(title)}",
        f"{_INDENT}accDescr: {_plain(description)}",
    ]


def _source(lines: Iterable[str]) -> str:
    return "\n".join(lines) + "\n"


def _codes(items: Iterable[Mapping[str, object]]) -> dict[str, str]:
    return {str(item["id"]): str(item["code"]) for item in items}


def _twins(specification: Mapping[str, object]) -> list[Mapping[str, object]]:
    return sorted(
        specification["user_twin_references"],
        key=lambda reference: (_normal(reference["name"]).casefold(), reference["name"]),
    )


def _twin_keys(specification: Mapping[str, object]) -> dict[str, str]:
    return {
        str(reference["twin_id"]): f"T{index}"
        for index, reference in enumerate(_twins(specification), 1)
    }


def _edges(pairs: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    return sorted(set(pairs))


def use_case_diagram(
    specification: Mapping[str, object],
    *,
    system_name: str,
    locale: str = DEFAULT_DIAGRAM_LOCALE,
) -> Diagram:
    language = diagram_locale(locale)
    text = _TEXT[language]
    twins = _twin_keys(specification)
    stories = specification["user_stories"]
    title = text["use_cases"]
    description = text["use_cases_description"].format(
        system=_normal(system_name),
        actors=_count(language, "actor", twins),
        cases=_count(language, "case", stories),
    )
    lines = ["usecase-beta", *_accessibility(title, description), f"{_INDENT}direction LR"]
    for reference in _twins(specification):
        key = twins[str(reference["twin_id"])]
        lines.append(f'{_INDENT}actor {key}("{_line(reference["name"])}")')
    lines.append(f'{_INDENT}systemBoundary SYSTEM["{_line(system_name)}"]')
    for story in stories:
        label = _line(f"{story['code']} {_short(story['goal'])}")
        lines.append(f'{_INDENT * 2}{_identifier(story["code"])}("{label}")')
    lines.append(f"{_INDENT}end")
    for story in stories:
        actor = twins[str(story["user_twin_reference"]["twin_id"])]
        lines.append(f"{_INDENT}{actor} --> {_identifier(story['code'])}")
    return Diagram(
        key="requirements/use-cases",
        stage=DiagramStage.REQUIREMENTS,
        kind=DiagramKind.USE_CASES,
        subject=None,
        title=title,
        description=description,
        source=_source(lines),
    )


def _requirement_risks(specification: Mapping[str, object]) -> dict[str, int]:
    levels: dict[str, int] = {}
    for risk in specification["risks"]:
        level = _RISK_LEVELS.get(str(risk["impact"]))
        if level is None:
            continue
        for identifier in risk["requirement_ids"]:
            levels[str(identifier)] = max(level, levels.get(str(identifier), 0))
    return levels


def _requirement_methods(specification: Mapping[str, object]) -> dict[str, str]:
    methods: dict[str, str] = {}
    for criterion in specification["acceptance_criteria"]:
        method = _VERIFICATION_METHODS.get(str(criterion["verification_method"]))
        if method is None:
            continue
        for identifier in criterion["requirement_ids"]:
            methods.setdefault(str(identifier), method)
    return methods


def _named(item: Mapping[str, object], field: str) -> str:
    return _line(f"{item['code']} {_short(item[field], 48)}")


def requirement_diagram(
    specification: Mapping[str, object],
    *,
    locale: str = DEFAULT_DIAGRAM_LOCALE,
) -> Diagram:
    language = diagram_locale(locale)
    text = _TEXT[language]
    requirements = specification["requirements"]
    criteria = specification["acceptance_criteria"]
    scenarios = specification["scenarios"]
    names = {str(item["id"]): _named(item, "title") for item in requirements}
    risks = _requirement_risks(specification)
    methods = _requirement_methods(specification)
    title = text["requirements"]
    description = text["requirements_description"].format(
        requirements=_count(language, "requirement", requirements),
        criteria=_count(language, "criterion", criteria),
        scenarios=_count(language, "scenario", scenarios),
    )
    lines = ["requirementDiagram", *_accessibility(title, description), ""]
    for item in requirements:
        identifier = str(item["id"])
        lines.extend(
            [
                f'{_INDENT}{_REQUIREMENT_TYPES[str(item["kind"])]} "{names[identifier]}" {{',
                f'{_INDENT * 2}id: "{_line(item["code"])}"',
                f'{_INDENT * 2}text: "{_line(_short(item["statement"]))}"',
            ]
        )
        if identifier in risks:
            lines.append(f"{_INDENT * 2}risk: {_RISK_NAMES[risks[identifier]]}")
        if identifier in methods:
            lines.append(f"{_INDENT * 2}verifymethod: {methods[identifier]}")
        lines.append(f"{_INDENT}}}")
    relations: list[str] = []
    for kind, items, field in (
        ("criterion_type", criteria, "statement"),
        ("scenario_type", scenarios, "title"),
    ):
        for item in items:
            name = _named(item, field)
            lines.extend(
                [
                    f'{_INDENT}element "{name}" {{',
                    f'{_INDENT * 2}type: "{_line(text[kind])}"',
                    f"{_INDENT}}}",
                ]
            )
            verified = {str(identifier) for identifier in item["requirement_ids"]}
            relations.extend(
                f'{_INDENT}"{name}" - verifies -> "{names[str(requirement["id"])]}"'
                for requirement in requirements
                if str(requirement["id"]) in verified
            )
    lines.extend(relations)
    return Diagram(
        key="requirements/requirements",
        stage=DiagramStage.REQUIREMENTS,
        kind=DiagramKind.REQUIREMENTS,
        subject=None,
        title=title,
        description=description,
        source=_source(lines),
    )


def _group(identifier: str, title: str, nodes: Sequence[str]) -> list[str]:
    if not nodes:
        return []
    return [
        f'{_INDENT}subgraph {identifier}["{_line(title)}"]',
        f"{_INDENT * 2}direction TB",
        *(f"{_INDENT * 2}{node}" for node in nodes),
        f"{_INDENT}end",
    ]


def _node(item: Mapping[str, object], field: str) -> str:
    return f'{_identifier(item["code"])}["{_label(item["code"], _short(item[field]))}"]'


def requirements_traceability_diagram(
    specification: Mapping[str, object],
    *,
    locale: str = DEFAULT_DIAGRAM_LOCALE,
) -> Diagram:
    language = diagram_locale(locale)
    text = _TEXT[language]
    twins = _twin_keys(specification)
    requirements = specification["requirements"]
    stories = specification["user_stories"]
    criteria = specification["acceptance_criteria"]
    scenarios = specification["scenarios"]
    risks = specification["risks"]
    done = specification["definition_of_done"]
    codes = {
        **_codes(requirements),
        **_codes(stories),
        **_codes(criteria),
    }
    title = text["requirements_traceability"]
    description = text["requirements_traceability_description"].format(
        twins=_count(language, "twin", twins),
        stories=_count(language, "story", stories),
        requirements=_count(language, "requirement", requirements),
        criteria=_count(language, "criterion", criteria),
        scenarios=_count(language, "scenario", scenarios),
        risks=_count(language, "risk", risks),
        done=_count(language, "done", done),
    )
    lines = ["flowchart LR", *_accessibility(title, description)]
    lines.extend(
        _group(
            "TWINS",
            text["twins"],
            [
                f'{twins[str(reference["twin_id"])]}(["{_label(reference["name"])}"])'
                for reference in _twins(specification)
            ],
        )
    )
    for identifier, label, items, field in (
        ("STORIES", text["stories"], stories, "goal"),
        ("REQUIREMENTS", text["requirements"], requirements, "title"),
        ("CRITERIA", text["criteria"], criteria, "statement"),
        ("SCENARIOS", text["scenarios"], scenarios, "title"),
        ("RISKS", text["risks"], risks, "summary"),
        ("DONE", text["done"], done, "statement"),
    ):
        lines.extend(_group(identifier, label, [_node(item, field) for item in items]))

    def target(identifier: object) -> str:
        return _identifier(codes[str(identifier)])

    solid = _edges(
        [
            *(
                (twins[str(story["user_twin_reference"]["twin_id"])], _identifier(story["code"]))
                for story in stories
            ),
            *(
                (_identifier(story["code"]), target(identifier))
                for story in stories
                for identifier in story["requirement_ids"]
            ),
            *(
                (target(identifier), _identifier(criterion["code"]))
                for criterion in criteria
                for identifier in (*criterion["requirement_ids"], *criterion["user_story_ids"])
            ),
        ]
    )
    lines.extend(f"{_INDENT}{source} --> {destination}" for source, destination in solid)
    for label, pairs in (
        (
            text["exercised_by"],
            _edges(
                (target(identifier), _identifier(scenario["code"]))
                for scenario in scenarios
                for identifier in (
                    *scenario["requirement_ids"],
                    *scenario["acceptance_criterion_ids"],
                )
            ),
        ),
        (
            text["affects"],
            _edges(
                (_identifier(risk["code"]), target(identifier))
                for risk in risks
                for identifier in risk["requirement_ids"]
            ),
        ),
        (
            text["governs"],
            _edges(
                (_identifier(item["code"]), target(identifier))
                for item in done
                for identifier in item["requirement_ids"]
            ),
        ),
    ):
        lines.extend(
            f'{_INDENT}{source} -.->|"{_line(label)}"| {destination}'
            for source, destination in pairs
        )
    return Diagram(
        key="requirements/traceability",
        stage=DiagramStage.REQUIREMENTS,
        kind=DiagramKind.REQUIREMENTS_TRACEABILITY,
        subject=None,
        title=title,
        description=description,
        source=_source(lines),
    )


def requirements_diagrams(
    specification: Mapping[str, object],
    *,
    system_name: str,
    locale: str = DEFAULT_DIAGRAM_LOCALE,
) -> tuple[Diagram, ...]:
    return (
        use_case_diagram(specification, system_name=system_name, locale=locale),
        requirement_diagram(specification, locale=locale),
        requirements_traceability_diagram(specification, locale=locale),
    )


def _requirement_list(identifiers: Iterable[object], codes: Mapping[str, str]) -> str:
    return ", ".join(sorted(codes[str(identifier)] for identifier in identifiers))


def workflow_diagram(
    alternative: Mapping[str, object],
    specification: Mapping[str, object],
    *,
    locale: str = DEFAULT_DIAGRAM_LOCALE,
) -> Diagram:
    language = diagram_locale(locale)
    text = _TEXT[language]
    codes = _codes(specification["requirements"])
    code = str(alternative["code"])
    workflows = alternative["workflows"]
    title = text["workflows"].format(code=code)
    description = text["workflows_description"].format(
        code=code,
        title=_normal(alternative["title"]),
        flows=_count(language, "flow", workflows),
        steps=_count(language, "step", sum(len(workflow["steps"]) for workflow in workflows)),
    )
    lines = ["flowchart TD", *_accessibility(title, description)]
    notes: list[str] = []
    for workflow in workflows:
        flow = _identifier(workflow["code"])
        steps = workflow["steps"]
        names = [f"{flow}S0", *(f"{flow}S{index}" for index in range(1, len(steps) + 1))]
        lines.extend(
            [
                f'{_INDENT}subgraph {flow}["{_line(workflow["code"])} · '
                f'{_line(_short(workflow["title"]))}"]',
                f"{_INDENT * 2}direction TB",
                f'{_INDENT * 2}{flow}S0(["{_line(text["start"])}"])',
                *(
                    f'{_INDENT * 2}{flow}S{index}["{_label(f"{index}. {_normal(step)}")}"]'
                    for index, step in enumerate(steps, 1)
                ),
                f'{_INDENT * 2}{flow}E(["{_line(text["end"])}"])',
                *(
                    f"{_INDENT * 2}{source} --> {destination}"
                    for source, destination in zip(names, [*names[1:], f"{flow}E"], strict=True)
                ),
                f"{_INDENT}end",
            ]
        )
        covered = _requirement_list(workflow["requirement_ids"], codes)
        notes.extend(
            [
                f'{_INDENT}{flow}R[/"{_label(f"{text['covers']} {covered}")}"/]',
                f"{_INDENT}{flow}E -.-> {flow}R",
            ]
        )
    lines.extend(notes)
    return Diagram(
        key=f"design/{code.lower()}-workflows",
        stage=DiagramStage.DESIGN,
        kind=DiagramKind.WORKFLOWS,
        subject=code,
        title=title,
        description=description,
        source=_source(lines),
    )


def _alternative(package: Mapping[str, object], identifier: object) -> Mapping[str, object] | None:
    for alternative in package["alternatives"]:
        if str(alternative["id"]) == str(identifier):
            return alternative
    return None


def focus_alternative(package: Mapping[str, object]) -> Mapping[str, object] | None:
    prototype = package.get("prototype")
    candidates = (
        None if prototype is None else prototype["design_alternative_id"],
        package.get("owner_selected_alternative_id"),
        package.get("recommended_alternative_id"),
    )
    for identifier in candidates:
        alternative = None if identifier is None else _alternative(package, identifier)
        if alternative is not None:
            return alternative
    alternatives = package["alternatives"]
    return alternatives[0] if alternatives else None


def screen_map_diagram(
    package: Mapping[str, object],
    *,
    locale: str = DEFAULT_DIAGRAM_LOCALE,
) -> Diagram | None:
    prototype = package.get("prototype")
    if prototype is None:
        return None
    language = diagram_locale(locale)
    text = _TEXT[language]
    alternative = _alternative(package, prototype["design_alternative_id"])
    code = str(prototype["code"] if alternative is None else alternative["code"])
    screens = prototype["screens"]
    transitions = prototype["transitions"]
    screen_codes = _codes(screens)
    elements = {str(element["id"]): element for screen in screens for element in screen["elements"]}
    entry = screen_codes[str(prototype["entry_screen_id"])]
    title = text["screen_map"].format(code=code)
    description = text["screen_map_description"].format(
        code=code,
        screens=_count(language, "screen", screens),
        transitions=_count(language, "transition", transitions),
        entry=entry,
    )
    lines = ["stateDiagram-v2", *_accessibility(title, description), f"{_INDENT}direction LR"]
    for screen in screens:
        state = text[f"state_{screen['state']}"]
        count = _count(language, "element", screen["elements"])
        label = _label(f"{screen['code']} · {_short(screen['title'])}", f"{state} · {count}")
        lines.append(f'{_INDENT}state "{label}" as {_identifier(screen["code"])}')
    lines.append(f"{_INDENT}[*] --> {_identifier(entry)}")
    for transition in transitions:
        trigger = elements.get(str(transition["trigger_element_id"]))
        outcome = _short(transition["outcome"])
        parts = [] if trigger is None else [f"{trigger['code']} {_short(trigger['content'])}"]
        if trigger is None or _normal(trigger["content"]).casefold() != outcome.casefold():
            parts.append(outcome)
        source = _identifier(screen_codes[str(transition["source_screen_id"])])
        destination = _identifier(screen_codes[str(transition["target_screen_id"])])
        lines.append(f"{_INDENT}{source} --> {destination}: {_label(*parts)}")
    return Diagram(
        key="design/screen-map",
        stage=DiagramStage.DESIGN,
        kind=DiagramKind.SCREEN_MAP,
        subject=code,
        title=title,
        description=description,
        source=_source(lines),
    )


def design_traceability_diagram(
    package: Mapping[str, object],
    specification: Mapping[str, object],
    *,
    locale: str = DEFAULT_DIAGRAM_LOCALE,
) -> Diagram | None:
    alternative = focus_alternative(package)
    if alternative is None:
        return None
    language = diagram_locale(locale)
    text = _TEXT[language]
    code = str(alternative["code"])
    requirements = specification["requirements"]
    codes = _codes(requirements)
    workflows = alternative["workflows"]
    prototype = package.get("prototype")
    screens = (
        prototype["screens"]
        if prototype is not None
        and str(prototype["design_alternative_id"]) == str(alternative["id"])
        else []
    )
    flow_edges = _edges(
        (_identifier(workflow["code"]), _identifier(codes[str(identifier)]))
        for workflow in workflows
        for identifier in workflow["requirement_ids"]
    )
    screen_edges = _edges(
        (_identifier(codes[str(identifier)]), _identifier(screen["code"]))
        for screen in screens
        for identifier in (
            *screen["requirement_ids"],
            *(
                requirement
                for element in screen["elements"]
                for requirement in element["requirement_ids"]
            ),
        )
    )
    covered = {destination for _, destination in flow_edges} | {
        source for source, _ in screen_edges
    }
    gaps = [item for item in requirements if _identifier(item["code"]) not in covered]
    title = text["design_traceability"].format(code=code)
    uncovered = (
        text["gaps_none"]
        if not gaps
        else text["gaps_one"]
        if len(gaps) == 1
        else text["gaps_many"].format(count=len(gaps))
    )
    description = text["design_traceability_description"].format(
        code=code,
        requirements=_count(language, "requirement", requirements),
        flows=_count(language, "flow", workflows),
        screens=_count(language, "screen", screens),
        gaps=uncovered,
    )
    lines = ["flowchart LR", *_accessibility(title, description)]
    lines.extend(
        _group("FLOWS", text["flows"], [_node(workflow, "title") for workflow in workflows])
    )
    lines.extend(
        _group(
            "REQUIREMENTS", text["requirements"], [_node(item, "title") for item in requirements]
        )
    )
    lines.extend(_group("SCREENS", text["screens"], [_node(screen, "title") for screen in screens]))
    lines.extend(f"{_INDENT}{source} --> {destination}" for source, destination in flow_edges)
    lines.extend(f"{_INDENT}{source} --> {destination}" for source, destination in screen_edges)
    if gaps:
        lines.append(f"{_INDENT}classDef gap stroke-dasharray:6 4")
        lines.append(f"{_INDENT}class {','.join(_identifier(item['code']) for item in gaps)} gap")
    return Diagram(
        key="design/traceability",
        stage=DiagramStage.DESIGN,
        kind=DiagramKind.DESIGN_TRACEABILITY,
        subject=code,
        title=title,
        description=description,
        source=_source(lines),
    )


def design_diagrams(
    package: Mapping[str, object],
    specification: Mapping[str, object],
    *,
    locale: str = DEFAULT_DIAGRAM_LOCALE,
) -> tuple[Diagram, ...]:
    diagrams: list[Diagram] = [
        workflow_diagram(alternative, specification, locale=locale)
        for alternative in package["alternatives"]
    ]
    for diagram in (
        screen_map_diagram(package, locale=locale),
        design_traceability_diagram(package, specification, locale=locale),
    ):
        if diagram is not None:
            diagrams.append(diagram)
    return tuple(diagrams)


def project_diagrams(
    *,
    specification: Mapping[str, object],
    package: Mapping[str, object] | None,
    system_name: str,
    locale: str = DEFAULT_DIAGRAM_LOCALE,
) -> tuple[Diagram, ...]:
    diagrams = requirements_diagrams(specification, system_name=system_name, locale=locale)
    if package is None:
        return diagrams
    return (*diagrams, *design_diagrams(package, specification, locale=locale))


__all__ = [
    "DEFAULT_DIAGRAM_LOCALE",
    "DIAGRAM_EXTENSION",
    "DIAGRAM_LOCALES",
    "MERMAID_VERSION",
    "Diagram",
    "DiagramKind",
    "DiagramStage",
    "design_diagrams",
    "design_traceability_diagram",
    "diagram_locale",
    "focus_alternative",
    "project_diagrams",
    "requirement_diagram",
    "requirements_diagrams",
    "requirements_traceability_diagram",
    "screen_map_diagram",
    "use_case_diagram",
    "workflow_diagram",
]
