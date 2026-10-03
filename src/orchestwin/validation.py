from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from copy import deepcopy


class ValidationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_DESIGN_KINDS = frozenset(
    {"DESIGN_PACKAGE", "DESIGN_ALTERNATIVE", "PROTOTYPE_SCREEN", "PROTOTYPE_ELEMENT"}
)
_IGNORED_LINKS = frozenset({"CONTAINS", "HAS_CLAIM", "CONTEXT"})


def _ordered(items):
    return sorted(
        items, key=lambda item: (item.get("kind", ""), item.get("code", ""), item.get("key", ""))
    )


def _graph(document):
    nodes = {node["key"]: node for node in document.get("nodes", ())}
    up, down = defaultdict(set), defaultdict(set)
    for link in document.get("links", ()):
        source, target = link.get("source"), link.get("target")
        if source in nodes and target in nodes and link.get("kind") not in _IGNORED_LINKS:
            up[source].add(target)
            down[target].add(source)
    return nodes, up, down


def _walk(key, adjacency):
    seen = {key}
    pending = deque([key])
    while pending:
        for linked in adjacency.get(pending.popleft(), ()):
            if linked not in seen:
                seen.add(linked)
                pending.append(linked)
    return seen


def _related(nodes, keys, kinds):
    return deepcopy(_ordered(nodes[key] for key in keys if nodes[key].get("kind") in kinds))


def validation_candidates(document: Mapping) -> list[dict]:
    nodes, up, down = _graph(document)
    candidates = []
    for node in _ordered(nodes.values()):
        if not node.get("current", True) or node.get("kind") == "USER_TWIN":
            continue
        if not node.get("validation_required") and node.get("kind") != "SYNTHETIC_FINDING":
            continue
        upstream, downstream = _walk(node["key"], up), _walk(node["key"], down)
        scenarios = _related(nodes, upstream | downstream, {"SCENARIO"})
        twins = _related(nodes, upstream, {"USER_TWIN"})
        design = _related(nodes, upstream | downstream, _DESIGN_KINDS)
        gaps = deepcopy(node.get("gaps", []))
        for code, values in (
            ("MISSING_TWIN", twins),
            ("MISSING_SCENARIO", scenarios),
            ("MISSING_DESIGN", design),
        ):
            if not values and not any(gap.get("code") == code for gap in gaps):
                gaps.append(
                    {"code": code, "node_key": node["key"], "related_code": None, "stage": None}
                )
        candidates.append(
            {
                "key": node["key"],
                "code": node["code"],
                "kind": node["kind"],
                "title": node.get("title", node["code"]),
                "reference": deepcopy(node.get("reference", {})),
                "origin": deepcopy(node),
                "twin_references": twins,
                "scenario_candidates": [item for item in scenarios if item.get("current", True)],
                "design_references": [item for item in design if item.get("current", True)],
                "gaps": gaps,
                "limits": ["CANDIDATE_NOT_AN_OPERATIONAL_HYPOTHESIS", "HUMAN_VALIDATION_REQUIRED"],
            }
        )
    return candidates


def scenario_walkthrough(
    document: Mapping,
    scenario_key: str,
    *,
    alternative_id: str | None = None,
    document_hash: str | None = None,
) -> dict:
    nodes, up, down = _graph(document)
    scenario = nodes.get(scenario_key)
    if scenario is None:
        matches = [
            item
            for item in nodes.values()
            if item.get("code") == scenario_key and item.get("kind") == "SCENARIO"
        ]
        current = [item for item in matches if item.get("current", True)]
        if current:
            matches = current
        if len(matches) != 1:
            raise ValidationError("VALIDATION_INPUT_INVALID")
        scenario = matches[0]
    if scenario.get("kind") != "SCENARIO":
        raise ValidationError("VALIDATION_INPUT_INVALID")
    payload = scenario.get("declared_context", {}).get("scenario", {})
    keys = _walk(scenario["key"], down)
    anchors = _related(nodes, keys, {"PROTOTYPE_ELEMENT"})
    if alternative_id is not None:
        anchors = [
            item
            for item in anchors
            if item.get("declared_context", {}).get("mockup", {}).get("alternative_id")
            == alternative_id
        ]
    if document_hash is not None:
        anchors = [
            item
            for item in anchors
            if document_hash
            in item.get("declared_context", {})
            .get("mockup", {})
            .get("document_hashes", {})
            .values()
        ]
    steps = [
        {
            "number": number,
            "text": text,
            "anchors": [],
            "observe": [],
            "gaps": [{"code": "STEP_ANCHOR_NOT_ATTESTED", "node_key": scenario["key"]}],
        }
        for number, text in enumerate(payload.get("steps", ()), start=1)
    ]
    gaps = deepcopy(scenario.get("gaps", []))
    if not steps:
        gaps.append({"code": "SCENARIO_STEPS_UNAVAILABLE", "node_key": scenario["key"]})
    if not anchors:
        gaps.append({"code": "MISSING_MOCKUP_ANCHOR", "node_key": scenario["key"]})
    if not scenario.get("current", True) or any(not item.get("current", True) for item in anchors):
        gaps.append({"code": "CONTEXT_OUTDATED", "node_key": scenario["key"]})
    return {
        "kind": "orchestwin.scenario-walkthrough",
        "schema_version": 1,
        "project_id": document["project_id"],
        "scenario": deepcopy(scenario),
        "twin_references": _related(nodes, _walk(scenario["key"], up), {"USER_TWIN"}),
        "task": payload.get("goal"),
        "steps": steps,
        "reference": deepcopy(scenario.get("reference", {})),
        "design_references": _related(nodes, keys, _DESIGN_KINDS),
        "anchor_candidates": anchors,
        "expected_outcome": payload.get("expected_outcome"),
        "gaps": gaps,
        "limits": ["SCENARIO_LEVEL_ANCHORS_ONLY", "SOFTWARE_NAVIGATION_NOT_HUMAN_OBSERVATION"],
    }


def _source_index(document, evidence):
    sources = list((evidence or {}).get("evidence", ()))
    sources.extend(
        node.get("declared_context", {}).get("source", {})
        for node in document.get("nodes", ())
        if node.get("kind") == "RESEARCH_EVIDENCE"
    )
    return {
        (str(source.get("id")), source.get("version"), source.get("content_hash")): source
        for source in sources
    }


def validation_overview(
    *,
    document: Mapping,
    hypotheses: Sequence = (),
    outcomes: Sequence = (),
    evidence: Mapping | None = None,
) -> dict:
    sources = _source_index(document, evidence)
    projected_outcomes = []
    for original in outcomes:
        item = deepcopy(dict(original))
        source = sources.get(
            (
                str(item.get("evidence_id")),
                item.get("evidence_version"),
                item.get("evidence_content_hash"),
            )
        )
        item["effective_status"] = (
            "RETIRED"
            if source and source.get("status") == "RETIRED"
            else "ACTIVE"
            if source
            else "SOURCE_UNAVAILABLE"
        )
        item["source_text_available"] = (
            None if source is None else source.get("text_available", True)
        )
        item["gaps"] = []
        if source is None:
            item["gaps"].append({"code": "MISSING_SOURCE_VERSION"})
        elif source.get("text_available") is False:
            item["gaps"].append({"code": "SOURCE_TEXT_UNAVAILABLE"})
        projected_outcomes.append(item)
    latest = {}
    for item in hypotheses:
        latest[str(item["id"])] = max(latest.get(str(item["id"]), 0), item["version_number"])
    projected_hypotheses = []
    states = {state: 0 for state in ("TO_VERIFY", "CONFIRMED", "REFUTED", "UNCERTAIN", "CONTESTED")}
    nodes = {node["key"]: node for node in document.get("nodes", ())}
    for original in sorted(hypotheses, key=lambda item: (item["code"], item["version_number"])):
        item = deepcopy(dict(original))
        matching = [
            result
            for result in projected_outcomes
            if str(result.get("hypothesis_id")) == str(item["id"])
            and result.get("hypothesis_version_number") == item["version_number"]
            and result.get("hypothesis_content_hash") == item["content_hash"]
        ]
        active = [
            result
            for result in matching
            if result["effective_status"] == "ACTIVE"
            and result.get("session_kind") == "HUMAN_SESSION"
        ]
        values = {result.get("outcome") for result in active}
        state = (
            "CONTESTED"
            if {"CONFIRMED", "REFUTED"}.issubset(values)
            else "UNCERTAIN"
            if "UNCERTAIN" in values
            or any(result.get("coverage") == "PARTIAL" for result in active)
            else next(iter(values))
            if values
            else "TO_VERIFY"
        )
        item["state"] = state
        item["current"] = item["version_number"] == latest[str(item["id"])]
        item["active_outcome_ids"] = [result["id"] for result in active]
        item["outcomes"] = matching
        item["partial_evidence"] = any(result.get("coverage") == "PARTIAL" for result in active)
        item["conflicting_outcomes"] = state == "CONTESTED"
        item["gaps"] = []
        for field in ("origin_key", "twin_key", "scenario_key", "design_key"):
            node = nodes.get(item.get(field))
            if node is None:
                item["gaps"].append(
                    {"code": "VALIDATION_REFERENCE_UNAVAILABLE", "reference": field}
                )
            elif not node.get("current", True) or any(
                gap.get("code") == "CONTEXT_OUTDATED" for gap in node.get("gaps", ())
            ):
                item["gaps"].append({"code": "CONTEXT_OUTDATED", "reference": field})
        if item["current"]:
            states[state] += 1
        projected_hypotheses.append(item)
    candidates = validation_candidates(document)
    return {
        "kind": "orchestwin.human-validation",
        "schema_version": 1,
        "project_id": document["project_id"],
        "candidates": candidates,
        "candidate_count": len(candidates),
        "hypotheses": projected_hypotheses,
        "outcomes": sorted(
            projected_outcomes, key=lambda item: (item.get("code", ""), item.get("id", ""))
        ),
        "summary": {
            "hypotheses": len(latest),
            "to_verify": states["TO_VERIFY"],
            "confirmed": states["CONFIRMED"],
            "refuted": states["REFUTED"],
            "uncertain": states["UNCERTAIN"],
            "contested": states["CONTESTED"],
            "retired_outcomes": sum(
                item["effective_status"] == "RETIRED" for item in projected_outcomes
            ),
        },
        "empirical_summary": {
            "human_session_outcomes": sum(
                item.get("session_kind") == "HUMAN_SESSION" and item["effective_status"] == "ACTIVE"
                for item in projected_outcomes
            ),
            "synthetic_exercise_outcomes": sum(
                item.get("session_kind") == "SYNTHETIC_EXERCISE"
                and item["effective_status"] == "ACTIVE"
                for item in projected_outcomes
            ),
        },
        "omitted_sections": deepcopy(document.get("omitted_sections", [])),
        "limits": [
            "OUTCOMES_DO_NOT_PROMOTE_TWIN_CLAIMS",
            "SYNTHETIC_EXERCISES_NOT_EMPIRICAL_VALIDATION",
        ],
    }


__all__ = [
    "ValidationError",
    "scenario_walkthrough",
    "validation_candidates",
    "validation_overview",
]
