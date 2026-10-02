from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from copy import deepcopy

from orchestwin.why_builder import build_why_document


class WhyError(ValueError):
    def __init__(self, code: str, candidates: Sequence[str] = ()) -> None:
        super().__init__(code)
        self.code = code
        self.candidates = tuple(sorted(candidates))


PERSONA_FIELDS = {
    "description": "description",
    "goals": "goals",
    "needs": "information_needs",
    "behaviours": "recurring_tasks",
    "pain_points": "pain_points",
    "constraints": "operational_constraints",
    "contexts": "context_of_use",
}
_NON_CAUSAL = frozenset({"CONTAINS", "CONTEXT", "ACTOR", "CLAIM_OF", "EVALUATED_BY"})
_NON_BREAKING = frozenset({"MISSING_RATIONALE", "SOURCE_TEXT_UNAVAILABLE", "CONTEXT_OUTDATED"})


def _breaks_chain(gap):
    return gap["code"] not in _NON_BREAKING and not (
        gap["code"] == "OMITTED_SECTION" and gap.get("stage") in {"brief", "team"}
    )


def _selector(code: str) -> str:
    if (
        not isinstance(code, str)
        or not code
        or len(code) > 2048
        or code != code.strip()
        or any(ord(char) < 33 for char in code)
        or not re.fullmatch(r"[A-Za-z0-9_.:/%@+\-]+", code)
    ):
        raise WhyError("WHY_CODE_INVALID")
    if ":persona." in code:
        base, field = code.rsplit(":persona.", 1)
        if field not in PERSONA_FIELDS:
            raise WhyError("WHY_CODE_INVALID")
        return f"{base}:user_twin.{PERSONA_FIELDS[field]}"
    return code


def _canonical(values):
    return sorted(values, key=lambda item: (item["kind"], item["code"], item["key"]))


def _walk(start: str, adjacency: Mapping[str, Sequence[str]]) -> set[str]:
    visited = {start}
    pending = deque([start])
    while pending:
        for key in adjacency.get(pending.popleft(), ()):
            if key not in visited:
                visited.add(key)
                pending.append(key)
    return visited - {start}


def _active_citation(node: Mapping) -> bool:
    for item in node.get("citations", ()):
        citation = item.get("citation", item)
        source = item.get("source", {})
        if (
            item.get("status") == "ACTIVE"
            and item.get("applicable", True)
            and source.get("status", "ACTIVE") == "ACTIVE"
            and item.get("effect") in {"SUPPORTS", "ADDS"}
            and citation.get("source_id")
            and isinstance(citation.get("source_version"), int)
            and citation.get("content_hash")
            and isinstance(citation.get("quote"), str)
            and bool(citation.get("quote"))
            and isinstance(citation.get("start"), int)
            and isinstance(citation.get("end"), int)
            and citation["end"] - citation["start"] == len(citation["quote"])
            and citation["start"] >= 0
            and isinstance(citation.get("start_line"), int)
            and citation["start_line"] >= 1
            and isinstance(citation.get("end_line"), int)
            and citation["end_line"] >= citation["start_line"]
        ):
            return True
    return False


def _completeness(target, nodes, adjacency, twin_context):
    memo = {}
    active = set()

    def visit(key):
        if key in memo:
            return memo[key]
        if key in active:
            return False, False, False
        active.add(key)
        node = nodes[key]
        own_twin = node["kind"] in {"USER_TWIN", "USER_TWIN_CLAIM"}
        own_evidence = node["kind"] == "USER_TWIN_CLAIM" and _active_citation(node)
        children = [visit(child) for child in adjacency.get(key, ())]
        twin = own_twin or key in twin_context or any(child[0] for child in children)
        evidence = own_evidence or any(child[1] for child in children)
        broken = any(_breaks_chain(gap) for gap in node.get("gaps", ()))
        if own_evidence:
            all_complete = not broken
        elif children:
            all_complete = all(child[2] for child in children) and not broken
        else:
            all_complete = False
        active.remove(key)
        memo[key] = twin, evidence, all_complete
        return memo[key]

    return visit(target["key"])


def explain_why(document: Mapping, code: str) -> dict:
    selected = _selector(code)
    nodes = {item["key"]: item for item in document.get("nodes", ())}
    if selected in nodes:
        target = nodes[selected]
    else:
        matches = [node for node in nodes.values() if node["code"] == selected]
        if not matches:
            raise WhyError("WHY_CODE_NOT_FOUND")
        if len(matches) > 1:
            raise WhyError("WHY_CODE_AMBIGUOUS", [node["key"] for node in matches])
        target = matches[0]
    upstream_index = defaultdict(list)
    downstream_index = defaultdict(list)
    completeness_index = defaultdict(list)
    twin_context = set()
    links = list(document.get("links", ()))
    for link in links:
        source, origin = link["source"], link["target"]
        if source not in nodes or origin not in nodes or link["kind"] == "CONTAINS":
            continue
        if link["kind"] == "HAS_CLAIM" and target["kind"] != "USER_TWIN":
            continue
        upstream_index[source].append(origin)
        downstream_index[origin].append(source)
        if link["kind"] not in _NON_CAUSAL:
            completeness_index[source].append(origin)
        elif link["kind"] in {"ACTOR", "EVALUATED_BY"} and nodes[origin]["kind"] == "USER_TWIN":
            twin_context.add(source)
    up = _walk(target["key"], upstream_index)
    down = _walk(target["key"], downstream_index)
    included = up | down | {target["key"]}
    selected_nodes = _canonical(nodes[key] for key in up | {target["key"]})
    gaps = [gap for node in selected_nodes for gap in node.get("gaps", ())]
    twin, evidence, all_complete = _completeness(target, nodes, completeness_index, twin_context)
    return deepcopy(
        {
            "kind": "orchestwin.why-answer",
            "schema_version": 1,
            "project_id": document["project_id"],
            "target": target,
            "summary": {
                "upstream_count": len(up),
                "downstream_count": len(down),
                "complete_to_twin": twin,
                "complete_to_evidence": evidence,
                "all_paths_complete": all_complete,
                "stop_reasons": sorted({gap["code"] for gap in gaps if _breaks_chain(gap)}),
            },
            "upstream": _canonical(nodes[key] for key in up),
            "downstream": _canonical(nodes[key] for key in down),
            "links": sorted(
                [
                    link
                    for link in links
                    if link["source"] in included and link["target"] in included
                ],
                key=lambda link: (link["source"], link["target"], link["kind"]),
            ),
            "gaps": sorted(
                gaps, key=lambda gap: (gap["node_key"], gap["code"], gap.get("related_code") or "")
            ),
            "human_validation": [
                node for node in selected_nodes if node.get("validation_required")
            ],
            "declared_context": target.get("declared_context", {"perspectives": []}),
            "limits": sorted({gap["code"] for gap in gaps}),
        }
    )


__all__ = ["WhyError", "build_why_document", "explain_why"]
