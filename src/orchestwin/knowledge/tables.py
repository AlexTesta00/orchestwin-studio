from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from orchestwin.knowledge.layout import table_document

type _Rows = list[dict[str, object]]

_REQUIREMENTS_STAGE: Final = "requirements"
_DESIGN_STAGE: Final = "design"
_SEPARATOR: Final = "; "
_TRUE: Final = "yes"
_FALSE: Final = "no"
_FORMULA_PREFIXES: Final = ("=", "+", "-", "@")
_TEXT_MARKER: Final = "'"
_REQUIREMENT_LINKS: Final = (
    "user_stories",
    "acceptance_criteria",
    "scenarios",
    "risks",
    "definition_of_done",
)
_CRITIQUE_ASPECTS: Final = (
    "strengths",
    "concerns",
    "unmet_needs",
    "accessibility_observations",
    "trust_concerns",
    "questions",
    "suggested_changes",
)
_STAGE_COLUMNS: Final = {
    _REQUIREMENTS_STAGE: {
        "requirements": (
            "code",
            "title",
            "kind",
            "priority",
            "statement",
            "twins",
            "user_stories",
            "acceptance_criteria",
            "scenarios",
            "risks",
            "definition_of_done",
        ),
        "user-stories": (
            "code",
            "twin",
            "goal",
            "benefit",
            "requirements",
            "acceptance_criteria",
        ),
        "acceptance-criteria": (
            "code",
            "statement",
            "verification_method",
            "requirements",
            "user_stories",
            "scenarios",
        ),
        "scenarios": (
            "code",
            "title",
            "actor",
            "trigger",
            "preconditions",
            "steps",
            "expected_outcome",
            "requirements",
            "acceptance_criteria",
        ),
        "risks": (
            "code",
            "summary",
            "likelihood",
            "impact",
            "mitigation",
            "review_status",
            "requirements",
        ),
        "definition-of-done": (
            "code",
            "statement",
            "verification_method",
            "applicability",
            "condition",
            "requirements",
        ),
    },
    _DESIGN_STAGE: {
        "alternatives": (
            "code",
            "title",
            "selected",
            "recommended",
            "archetype",
            "product_name",
            "summary",
            "rationale",
            "requirements",
            "user_stories",
            "acceptance_criteria",
            "twins",
            "workflows",
        ),
        "workflows": (
            "alternative",
            "code",
            "title",
            "step_number",
            "step",
            "requirements",
            "user_stories",
        ),
        "visual-language": ("alternative", "dimension", "value"),
        "palette": ("alternative", "role", "colour"),
        "critiques": (
            "code",
            "alternative",
            "twin",
            "aspect",
            "text",
            "confidence",
            "epistemic_status",
            "human_validation",
        ),
        "concerns": ("code", "summary", "mitigation", "alternatives", "requirements"),
        "screens": (
            "screen",
            "title",
            "state",
            "entry",
            "element",
            "kind",
            "content",
            "accessible_name",
            "field_name",
            "required",
            "options",
            "requirements",
        ),
        "transitions": ("code", "source", "target", "trigger", "trigger_content", "outcome"),
    },
}
TABLE_COLUMNS: Final = {
    table_document(stage, name): columns
    for stage, tables in _STAGE_COLUMNS.items()
    for name, columns in tables.items()
}
CRITIQUE_VERDICT_COLUMNS: Final = ("verdict", "quote")


def _codes(items: Iterable[Mapping[str, object]]) -> dict[str, str]:
    return {str(item["id"]): str(item["code"]) for item in items}


@dataclass(frozen=True, slots=True)
class _Codes:
    requirements: Mapping[str, str]
    stories: Mapping[str, str]
    criteria: Mapping[str, str]

    @classmethod
    def of(cls, specification: Mapping[str, object]) -> _Codes:
        return cls(
            requirements=_codes(specification["requirements"]),
            stories=_codes(specification["user_stories"]),
            criteria=_codes(specification["acceptance_criteria"]),
        )


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return _TRUE if value else _FALSE
    if isinstance(value, list | tuple):
        return _SEPARATOR.join(_text(item) for item in value)
    return " ".join(str(value).split())


def _cell(value: object) -> str:
    text = _text(value)
    return _TEXT_MARKER + text if text.startswith(_FORMULA_PREFIXES) else text


def _csv(columns: Sequence[str], rows: Iterable[Mapping[str, object]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writerow({column: _cell(column) for column in columns})
    writer.writerows({column: _cell(value) for column, value in row.items()} for row in rows)
    return buffer.getvalue()


def _stage_tables(
    stage: str,
    tables: Mapping[str, _Rows],
    extra_columns: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, str]:
    columns = _STAGE_COLUMNS[stage]
    extra = extra_columns or {}
    return {
        table_document(stage, name): _csv((*columns[name], *extra.get(name, ())), rows)
        for name, rows in tables.items()
    }


def _code(identifier: object, codes: Mapping[str, str]) -> str:
    return codes.get(str(identifier), str(identifier))


def _references(identifiers: Iterable[object], codes: Mapping[str, str]) -> list[str]:
    return sorted({_code(identifier, codes) for identifier in identifiers})


def _backlinks(items: Iterable[Mapping[str, object]], field: str) -> dict[str, set[str]]:
    links: dict[str, set[str]] = {}
    for item in items:
        for identifier in item[field]:
            links.setdefault(str(identifier), set()).add(str(item["code"]))
    return links


def _linked(links: Mapping[str, set[str]], item: Mapping[str, object]) -> list[str]:
    return sorted(links.get(str(item["id"]), ()))


def _names(references: Iterable[Mapping[str, object]]) -> list[object]:
    return sorted(
        (reference["name"] for reference in references),
        key=lambda name: (str(name).casefold(), str(name)),
    )


def _numbered(steps: Iterable[object]) -> list[str]:
    return [f"{number}. {_text(step)}" for number, step in enumerate(steps, 1)]


def _matches(identifier: object, candidate: object) -> bool:
    return candidate is not None and str(candidate) == str(identifier)


def _requirement_rows(specification: Mapping[str, object]) -> _Rows:
    links = {key: _backlinks(specification[key], "requirement_ids") for key in _REQUIREMENT_LINKS}
    return [
        {
            "code": requirement["code"],
            "title": requirement["title"],
            "kind": requirement["kind"],
            "priority": requirement["priority"],
            "statement": requirement["statement"],
            "twins": _names(requirement["user_twin_references"]),
            **{key: _linked(backlinks, requirement) for key, backlinks in links.items()},
        }
        for requirement in specification["requirements"]
    ]


def _story_rows(specification: Mapping[str, object], codes: _Codes) -> _Rows:
    criteria = _backlinks(specification["acceptance_criteria"], "user_story_ids")
    return [
        {
            "code": story["code"],
            "twin": story["user_twin_reference"]["name"],
            "goal": story["goal"],
            "benefit": story["benefit"],
            "requirements": _references(story["requirement_ids"], codes.requirements),
            "acceptance_criteria": _linked(criteria, story),
        }
        for story in specification["user_stories"]
    ]


def _criterion_rows(specification: Mapping[str, object], codes: _Codes) -> _Rows:
    scenarios = _backlinks(specification["scenarios"], "acceptance_criterion_ids")
    return [
        {
            "code": criterion["code"],
            "statement": criterion["statement"],
            "verification_method": criterion["verification_method"],
            "requirements": _references(criterion["requirement_ids"], codes.requirements),
            "user_stories": _references(criterion["user_story_ids"], codes.stories),
            "scenarios": _linked(scenarios, criterion),
        }
        for criterion in specification["acceptance_criteria"]
    ]


def _scenario_rows(specification: Mapping[str, object], codes: _Codes) -> _Rows:
    return [
        {
            "code": scenario["code"],
            "title": scenario["title"],
            "actor": scenario["actor"]["name"],
            "trigger": scenario["trigger"],
            "preconditions": scenario["preconditions"],
            "steps": _numbered(scenario["steps"]),
            "expected_outcome": scenario["expected_outcome"],
            "requirements": _references(scenario["requirement_ids"], codes.requirements),
            "acceptance_criteria": _references(
                scenario["acceptance_criterion_ids"], codes.criteria
            ),
        }
        for scenario in specification["scenarios"]
    ]


def _risk_rows(specification: Mapping[str, object], codes: _Codes) -> _Rows:
    return [
        {
            "code": risk["code"],
            "summary": risk["summary"],
            "likelihood": risk["likelihood"],
            "impact": risk["impact"],
            "mitigation": risk["mitigation"],
            "review_status": risk["review_status"],
            "requirements": _references(risk["requirement_ids"], codes.requirements),
        }
        for risk in specification["risks"]
    ]


def _done_rows(specification: Mapping[str, object], codes: _Codes) -> _Rows:
    return [
        {
            "code": item["code"],
            "statement": item["statement"],
            "verification_method": item["verification_method"],
            "applicability": item["applicability"],
            "condition": item.get("condition"),
            "requirements": _references(item["requirement_ids"], codes.requirements),
        }
        for item in specification["definition_of_done"]
    ]


def _visual(alternative: Mapping[str, object]) -> Mapping[str, object]:
    return alternative.get("visual_language") or {}


def _alternative_rows(package: Mapping[str, object], codes: _Codes) -> _Rows:
    selected = package.get("owner_selected_alternative_id")
    recommended = package.get("recommended_alternative_id")
    rows: _Rows = []
    for alternative in package["alternatives"]:
        visual = _visual(alternative)
        rows.append(
            {
                "code": alternative["code"],
                "title": alternative["title"],
                "selected": _matches(alternative["id"], selected),
                "recommended": _matches(alternative["id"], recommended),
                "archetype": (visual.get("choices") or {}).get("archetype"),
                "product_name": visual.get("product_name"),
                "summary": alternative["summary"],
                "rationale": alternative["rationale"],
                "requirements": _references(alternative["requirement_ids"], codes.requirements),
                "user_stories": _references(alternative["user_story_ids"], codes.stories),
                "acceptance_criteria": _references(
                    alternative["acceptance_criterion_ids"], codes.criteria
                ),
                "twins": _names(alternative["user_twin_references"]),
                "workflows": sorted(str(workflow["code"]) for workflow in alternative["workflows"]),
            }
        )
    return rows


def _workflow_rows(package: Mapping[str, object], codes: _Codes) -> _Rows:
    rows: _Rows = []
    for alternative in package["alternatives"]:
        for workflow in alternative["workflows"]:
            workflow_row: dict[str, object] = {
                "alternative": alternative["code"],
                "code": workflow["code"],
                "title": workflow["title"],
                "requirements": _references(workflow["requirement_ids"], codes.requirements),
                "user_stories": _references(workflow["user_story_ids"], codes.stories),
            }
            steps = workflow["steps"]
            if not steps:
                rows.append(workflow_row)
            rows.extend(
                {**workflow_row, "step_number": number, "step": step}
                for number, step in enumerate(steps, 1)
            )
    return rows


def _visual_rows(
    package: Mapping[str, object], field: str, name_column: str, value_column: str
) -> _Rows:
    rows: _Rows = []
    for alternative in package["alternatives"]:
        entries = _visual(alternative).get(field) or {}
        rows.extend(
            {"alternative": alternative["code"], name_column: name, value_column: entries[name]}
            for name in sorted(entries)
        )
    return rows


def _has_verdicts(package: Mapping[str, object]) -> bool:
    return any(critique.get("verdict") is not None for critique in package["critiques"])


def _critique_rows(
    package: Mapping[str, object], alternatives: Mapping[str, str], *, verdicts: bool
) -> _Rows:
    rows: _Rows = []
    for critique in package["critiques"]:
        critique_row: dict[str, object] = {
            "code": critique["code"],
            "alternative": _code(critique["design_alternative_id"], alternatives),
            "twin": critique["user_twin_reference"]["name"],
            "confidence": critique["confidence"],
            "epistemic_status": critique["epistemic_status"],
            "human_validation": critique["human_validation"],
        }
        if verdicts:
            critique_row.update(
                {column: critique.get(column) for column in CRITIQUE_VERDICT_COLUMNS}
            )
        rows.extend(
            {**critique_row, "aspect": aspect, "text": text}
            for aspect in _CRITIQUE_ASPECTS
            for text in critique.get(aspect) or ()
        )
    return rows


def _concern_rows(
    package: Mapping[str, object], codes: _Codes, alternatives: Mapping[str, str]
) -> _Rows:
    return [
        {
            "code": concern["code"],
            "summary": concern["summary"],
            "mitigation": concern["mitigation"],
            "alternatives": _references(concern["design_alternative_ids"], alternatives),
            "requirements": _references(concern["requirement_ids"], codes.requirements),
        }
        for concern in package["concerns"]
    ]


def _screen_rows(prototype: Mapping[str, object], codes: _Codes) -> _Rows:
    entry = str(prototype["entry_screen_id"])
    rows: _Rows = []
    for screen in prototype["screens"]:
        screen_row: dict[str, object] = {
            "screen": screen["code"],
            "title": screen["title"],
            "state": screen["state"],
            "entry": str(screen["id"]) == entry,
        }
        elements = screen["elements"]
        if not elements:
            rows.append(
                {
                    **screen_row,
                    "requirements": _references(screen["requirement_ids"], codes.requirements),
                }
            )
        rows.extend(
            {
                **screen_row,
                "element": element["code"],
                "kind": element["kind"],
                "content": element["content"],
                "accessible_name": element.get("accessible_name"),
                "field_name": element.get("field_name"),
                "required": element["required"],
                "options": element["options"],
                "requirements": _references(
                    [*screen["requirement_ids"], *element["requirement_ids"]], codes.requirements
                ),
            }
            for element in elements
        )
    return rows


def _transition_rows(prototype: Mapping[str, object]) -> _Rows:
    screens = _codes(prototype["screens"])
    elements = {
        str(element["id"]): element
        for screen in prototype["screens"]
        for element in screen["elements"]
    }
    rows: _Rows = []
    for transition in prototype["transitions"]:
        trigger = elements.get(str(transition["trigger_element_id"]))
        rows.append(
            {
                "code": transition["code"],
                "source": _code(transition["source_screen_id"], screens),
                "target": _code(transition["target_screen_id"], screens),
                "trigger": (
                    str(transition["trigger_element_id"]) if trigger is None else trigger["code"]
                ),
                "trigger_content": None if trigger is None else trigger["content"],
                "outcome": transition["outcome"],
            }
        )
    return rows


def requirements_tables(specification: Mapping[str, object]) -> dict[str, str]:
    codes = _Codes.of(specification)
    return _stage_tables(
        _REQUIREMENTS_STAGE,
        {
            "requirements": _requirement_rows(specification),
            "user-stories": _story_rows(specification, codes),
            "acceptance-criteria": _criterion_rows(specification, codes),
            "scenarios": _scenario_rows(specification, codes),
            "risks": _risk_rows(specification, codes),
            "definition-of-done": _done_rows(specification, codes),
        },
    )


def design_tables(
    package: Mapping[str, object], specification: Mapping[str, object]
) -> dict[str, str]:
    codes = _Codes.of(specification)
    alternatives = _codes(package["alternatives"])
    verdicts = _has_verdicts(package)
    tables: dict[str, _Rows] = {
        "alternatives": _alternative_rows(package, codes),
        "workflows": _workflow_rows(package, codes),
        "visual-language": _visual_rows(package, "choices", "dimension", "value"),
        "palette": _visual_rows(package, "palette", "role", "colour"),
        "critiques": _critique_rows(package, alternatives, verdicts=verdicts),
        "concerns": _concern_rows(package, codes, alternatives),
    }
    prototype = package.get("prototype")
    if prototype is not None:
        tables["screens"] = _screen_rows(prototype, codes)
        tables["transitions"] = _transition_rows(prototype)
    extra = {"critiques": CRITIQUE_VERDICT_COLUMNS} if verdicts else None
    return _stage_tables(_DESIGN_STAGE, tables, extra)


def knowledge_tables(
    *, specification: Mapping[str, object], package: Mapping[str, object] | None
) -> dict[str, str]:
    tables = requirements_tables(specification)
    if package is not None:
        tables.update(design_tables(package, specification))
    return tables


__all__ = [
    "CRITIQUE_VERDICT_COLUMNS",
    "TABLE_COLUMNS",
    "design_tables",
    "knowledge_tables",
    "requirements_tables",
]
