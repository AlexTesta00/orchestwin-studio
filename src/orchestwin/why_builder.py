from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from urllib.parse import quote

_STAGES = {
    "brief": ("brief", "PROJECT_BRIEF", "BRIEF"),
    "team": ("proposal", "AGENT_TEAM", "TEAM"),
    "twins": ("snapshot", "USER_MODELING", "UM"),
    "requirements": ("specification", "REQUIREMENTS_SPECIFICATION", "REQSPEC"),
    "design": ("package", "DESIGN_PACKAGE", "DESIGN"),
}
_FIELDS = (
    "role",
    "age_range",
    "expertise",
    "goals",
    "recurring_tasks",
    "context_of_use",
    "information_needs",
    "decision_criteria",
    "preferred_vocabulary",
    "frustrations",
    "pain_points",
    "trust_concerns",
    "accessibility_needs",
    "operational_constraints",
    "technical_literacy",
    "risk_sensitivity",
    "assumptions",
    "description",
    "represents",
    "does_not_represent",
    "evidence_gaps",
)
_PERSPECTIVES = {
    "UX": ("UX_RESEARCHER_USER_MODELER", "UX_UI_DESIGNER"),
    "ACCESSIBILITY": ("ACCESSIBILITY_REVIEWER",),
    "SOFTWARE_ENGINEERING": ("SOFTWARE_ARCHITECT", "QA_TEST_ENGINEER"),
    "PRODUCT": ("REQUIREMENTS_ANALYST",),
    "SECURITY": ("SECURITY_REVIEWER",),
}


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _items(value):
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _key(kind, identifier, version, digest, context=""):
    return ":".join(
        quote(str(value or ""), safe="._-")
        for value in (
            kind,
            identifier,
            version,
            digest,
            context,
        )
    )


def _reference(envelope, identifier=None):
    return {
        "artifact_id": str(identifier or envelope.get("id") or envelope.get("artifact_id") or ""),
        "version_number": envelope.get("version_number", envelope.get("version")),
        "content_hash": envelope.get("content_hash"),
    }


def _status(value):
    if value.get("display_status") in {
        "EVIDENCED",
        "INFERRED",
        "HYPOTHESIZED",
        "CONTESTED",
        "UNKNOWN",
    }:
        return value["display_status"]
    if _mapping(value.get("value")).get("kind") in {"UNKNOWN", "ABSTAINED"}:
        return "UNKNOWN"
    epistemic = value.get("epistemic_status")
    if epistemic == "CONTESTED":
        return "CONTESTED"
    if epistemic == "MODEL_INFERRED":
        return "INFERRED"
    if epistemic == "UNSUPPORTED_ASSUMPTION":
        return "HYPOTHESIZED"
    if epistemic in {"EMPIRICALLY_SUPPORTED", "HUMAN_VALIDATED"} and any(
        source.get("source_kind", source.get("kind")) == "EMPIRICAL_RESEARCH"
        for source in _items(value.get("provenance"))
    ):
        return "EVIDENCED"
    return "HYPOTHESIZED" if epistemic else "UNKNOWN"


def _origin(value):
    explicit = value.get("rationale_origin")
    if explicit in {"MODEL", "OWNER", "SYSTEM", "UNKNOWN"}:
        return explicit
    kinds = {
        source.get("source_kind", source.get("kind")) for source in _items(value.get("provenance"))
    }
    if (
        value.get("rationale")
        == "Evidence was withdrawn; remaining independent sources and uncovered claims require review."
    ):
        return "UNKNOWN"
    if "MODEL_OUTPUT" in kinds and kinds.issubset(
        {"MODEL_OUTPUT", "PROJECT_BRIEF", "SYSTEM_ARTIFACT"}
    ):
        return "MODEL"
    if kinds == {"OWNER_INPUT"} and not any(
        item.get("source_id") == "withdrawn-evidence" for item in _items(value.get("provenance"))
    ):
        return "OWNER"
    if kinds == {"SYSTEM_ARTIFACT"}:
        return "SYSTEM"
    return "UNKNOWN"


def _envelopes(stage, value):
    result = []
    candidates = _items(value) if isinstance(value, list | tuple) else [_mapping(value)]
    for candidate in candidates:
        if not candidate:
            continue
        if isinstance(candidate.get("document"), Mapping):
            candidate = candidate["document"]
        elif isinstance(candidate.get("version"), Mapping):
            candidate = candidate["version"]
        wrapper = _STAGES[stage][0]
        if wrapper not in candidate and candidate.get("id"):
            candidate = {**candidate, wrapper: candidate}
        result.append(deepcopy(dict(candidate)))
    return sorted(result, key=lambda item: (item.get("version_number", 0), str(item.get("id", ""))))


def _valid_citation(citation):
    text = citation.get("quote")
    start, end = citation.get("start"), citation.get("end")
    return (
        isinstance(text, str)
        and bool(text)
        and isinstance(start, int)
        and isinstance(end, int)
        and start >= 0
        and end - start == len(text)
        and isinstance(citation.get("start_line"), int)
        and citation["start_line"] >= 1
        and isinstance(citation.get("end_line"), int)
        and citation["end_line"] >= citation["start_line"]
    )


class _Builder:
    def __init__(self, project_id, stages, evidence, sections, validation_context):
        self.project_id = str(project_id)
        self.stages = {stage: _envelopes(stage, stages.get(stage)) for stage in _STAGES}
        self.evidence = _mapping(evidence)
        self.sections = _mapping(sections)
        self.validation_context = validation_context
        section_keys = {
            "BRIEF": "brief",
            "TEAM": "team",
            "USER_TWINS": "twins",
            "REQUIREMENTS": "requirements",
            "DESIGN": "design",
        }
        for section in _items(self.sections.get("sections")):
            stage = section_keys.get(section.get("key"))
            if stage and self.stages[stage]:
                envelope = self.stages[stage][-1]
                envelope["section"] = deepcopy(section)
        self.nodes = {}
        self.links = set()
        self.index = {}
        self.stage_index = {}
        self.pending = []
        self.twin_index = {}
        self.claim_index = {}
        self.source_index = {}

    def gap(self, node, code, related=None, stage=None):
        gap = {"code": code, "node_key": node["key"], "related_code": related, "stage": stage}
        if gap not in node["gaps"]:
            node["gaps"].append(gap)

    def node(
        self,
        kind,
        code,
        title,
        reference,
        *,
        context="",
        current=True,
        data=None,
        rationale_origin=None,
    ):
        data = _mapping(data)
        key = _key(
            kind,
            reference["artifact_id"],
            reference["version_number"],
            reference["content_hash"],
            context,
        )
        if key in self.nodes:
            self.nodes[key]["current"] = self.nodes[key]["current"] or current
            return self.nodes[key]
        text = data.get("rationale")
        rationale = (
            None
            if not isinstance(text, str) or not text
            else {
                "text": text,
                "origin": rationale_origin or _origin(data),
                "version_number": reference["version_number"],
                "content_hash": reference["content_hash"],
            }
        )
        node = {
            "key": key,
            "code": str(code),
            "kind": kind,
            "title": str(title or code),
            "display_status": _status(data),
            "reference": reference,
            "current": bool(current),
            "rationale": rationale,
            "citations": [],
            "validation_required": bool(
                data.get("requires_human_validation") or data.get("human_validation") == "REQUIRED"
            ),
            "gaps": [],
            "declared_context": {"perspectives": []},
        }
        self.nodes[key] = node
        return node

    def link(self, node, origin, kind):
        if node and origin and node["key"] != origin["key"]:
            self.links.add((node["key"], origin["key"], kind))

    def queue(
        self, node, kind, identity, context, relation="TRACES_TO", gap="OMITTED_SECTION", stage=None
    ):
        self.pending.append((node, kind, str(identity), context, relation, gap, stage))

    def stage_roots(self):
        for stage, values in self.stages.items():
            for envelope in values:
                wrapper, kind, prefix = _STAGES[stage]
                payload = _mapping(envelope.get(wrapper))
                reference = _reference(envelope)
                current = envelope.get("current", envelope == values[-1])
                node = self.node(
                    kind,
                    f"{prefix}-v{reference['version_number']}",
                    payload.get("name", payload.get("title", kind)),
                    reference,
                    current=current,
                )
                self.note_stage(node, envelope)
                self.stage_index[
                    (
                        stage,
                        reference["artifact_id"],
                        reference["version_number"],
                        reference["content_hash"],
                    )
                ] = node

    def note_stage(self, node, envelope):
        if envelope.get("section"):
            node["declared_context"]["section"] = deepcopy(envelope["section"])
            if envelope["section"].get("state") == "TO_UPDATE":
                self.gap(node, "CONTEXT_OUTDATED", node["code"], envelope["section"]["key"])
        if envelope.get("base_reference"):
            node["declared_context"]["base_reference"] = deepcopy(envelope["base_reference"])
        if envelope.get("audit_reference"):
            node["declared_context"]["audit_reference"] = deepcopy(envelope["audit_reference"])

    def stage_context(self, node, reference, stage, relation="CONTEXT"):
        reference = _mapping(reference)
        key = (
            stage,
            str(reference.get("artifact_id", "")),
            reference.get("version_number", reference.get("version")),
            reference.get("content_hash"),
        )
        origin = self.stage_index.get(key)
        if origin:
            self.link(node, origin, relation)
            if not origin["current"]:
                self.gap(node, "CONTEXT_OUTDATED", origin["code"], stage)
        elif reference:
            self.gap(node, "OMITTED_SECTION", reference.get("kind"), stage)
        return origin

    def sources(self):
        latest = {}
        for source in _items(self.evidence.get("evidence")):
            latest[str(source.get("id"))] = max(
                latest.get(str(source.get("id")), 0), source.get("version", 0)
            )
        for source in _items(self.evidence.get("evidence")):
            reference = _reference(source)
            current = (
                source.get("version") == latest[str(source.get("id"))]
                and source.get("status") == "ACTIVE"
            )
            node = self.node(
                "RESEARCH_EVIDENCE",
                source.get("code", source.get("id")),
                source.get("title"),
                reference,
                current=current,
                data={"display_status": "UNKNOWN"},
            )
            node["declared_context"]["source"] = deepcopy(source)
            self.source_index[
                (reference["artifact_id"], reference["version_number"], reference["content_hash"])
            ] = node
            if source.get("status") == "RETIRED":
                self.gap(node, "SOURCE_RETIRED", node["code"], "evidence")
            if source.get("text_available") is False:
                self.gap(node, "SOURCE_TEXT_UNAVAILABLE", node["code"], "evidence")

    def twins(self):
        for envelope in self.stages["twins"]:
            payload = _mapping(envelope.get("snapshot"))
            personas = {
                (
                    str(item.get("persona_id")),
                    item.get("version_number"),
                    item.get("content_hash"),
                ): item
                for item in _items(payload.get("persona_versions"))
            }
            for version in _items(payload.get("twin_versions")):
                profile = _mapping(version.get("profile"))
                identifier = str(version.get("twin_id"))
                reference = _reference(version, identifier)
                code = (
                    f"UT-{identifier.replace('-', '')[:8].upper()}-v{reference['version_number']}"
                )
                current = envelope.get("current", envelope == self.stages["twins"][-1])
                twin = self.node(
                    "USER_TWIN", code, profile.get("name"), reference, current=current, data=profile
                )
                self.note_stage(twin, envelope)
                exact = (identifier, reference["version_number"], reference["content_hash"])
                self.twin_index[exact] = twin
                self.stage_context(twin, profile.get("project_brief_reference"), "brief")
                self.stage_context(twin, profile.get("agent_team_reference"), "team")
                observations = {
                    item.get("observation_key"): item
                    for item in _items(profile.get("observations"))
                }
                persona_ref = _mapping(profile.get("persona_reference"))
                persona = personas.get(
                    (
                        str(persona_ref.get("persona_id")),
                        persona_ref.get("version_number"),
                        persona_ref.get("content_hash"),
                    )
                )
                persona_profile = _mapping(persona.get("profile")) if persona else {}
                if (
                    "user_twin.description" not in observations
                    and persona
                    and not persona_profile.get("archived")
                    and persona_profile.get("confirmation_status") == "CONFIRMED"
                ):
                    summary = next(
                        (
                            item
                            for item in _items(_mapping(persona.get("profile")).get("observations"))
                            if item.get("observation_key") == "persona.summary"
                        ),
                        None,
                    )
                    if summary:
                        observations["user_twin.description"] = summary
                for field in _FIELDS:
                    observation_key = f"user_twin.{field}"
                    observation = observations.get(observation_key, {"value": {"kind": "UNKNOWN"}})
                    claim = self.node(
                        "USER_TWIN_CLAIM",
                        f"{code}:{observation_key}",
                        field,
                        reference,
                        context=observation_key,
                        current=current,
                        data=observation,
                    )
                    self.note_stage(claim, envelope)
                    claim["declared_context"]["observation_value"] = deepcopy(
                        observation.get("value")
                    )
                    claim["declared_context"]["provenance"] = deepcopy(
                        _items(observation.get("provenance"))
                    )
                    if observation.get("observation_key") == "persona.summary" and persona:
                        observation_reference = _reference(persona, persona.get("persona_id"))
                        claim["declared_context"]["observation_reference"] = observation_reference
                        if claim["rationale"]:
                            claim["rationale"]["version_number"] = observation_reference[
                                "version_number"
                            ]
                            claim["rationale"]["content_hash"] = observation_reference[
                                "content_hash"
                            ]
                    self.claim_index[(*exact, observation_key)] = claim
                    self.link(claim, twin, "CLAIM_OF")
                    self.link(twin, claim, "HAS_CLAIM")
                    if observation_key not in observations:
                        self.gap(claim, "MISSING_CLAIM", observation_key, "twins")
                    if not claim["rationale"]:
                        self.gap(claim, "MISSING_RATIONALE", observation_key, "twins")
                    self.claim_sources(claim, observation, exact, observation_key)

    def claim_sources(self, claim, observation, twin_exact, observation_key):
        references = _items(observation.get("provenance"))
        supported_exact = set()
        for item in _items(self.evidence.get("citations")):
            imported = _mapping(item.get("imported_from"))
            version_matches = item.get("twin_version") == twin_exact[1] or (
                imported.get("mapped_twin_version") == twin_exact[1]
            )
            if (
                str(item.get("twin_id")) != twin_exact[0]
                or not version_matches
                or item.get("field")
                not in {observation_key, observation_key.removeprefix("user_twin.")}
            ):
                continue
            citation = _mapping(item.get("citation"))
            exact = (
                str(citation.get("source_id")),
                citation.get("source_version"),
                citation.get("content_hash"),
            )
            origin = self.source_index.get(exact)
            payload = deepcopy(dict(item))
            if origin:
                payload["source"] = deepcopy(origin["declared_context"]["source"])
                self.link(claim, origin, item.get("effect", "SUPPORTS"))
            provenance_matches = any(
                str(reference.get("source_id")) == exact[0]
                and reference.get("source_version") == exact[1]
                and reference.get("content_hash") == exact[2]
                and reference.get("locator")
                in {
                    observation_key,
                    f"characters {citation.get('start')}:{citation.get('end')}; lines {citation.get('start_line')}:{citation.get('end_line')}",
                }
                for reference in references
            )
            payload["applicable"] = provenance_matches
            if not origin:
                self.gap(claim, "MISSING_SOURCE_VERSION", citation.get("source_id"), "evidence")
                payload["applicable"] = False
            source_active = (
                origin and origin["declared_context"]["source"].get("status") == "ACTIVE"
            )
            claim["citations"].append(payload)
            if (
                payload.get("status") == "ACTIVE"
                and source_active
                and payload["applicable"]
                and payload.get("effect") in {"SUPPORTS", "ADDS"}
                and _valid_citation(citation)
            ):
                supported_exact.add(exact)
            if payload.get("status") == "RETIRED" or (origin and not source_active):
                self.gap(claim, "SOURCE_RETIRED", origin["code"] if origin else None, "evidence")
        for reference in references:
            kind = reference.get("source_kind", reference.get("kind"))
            if kind == "PROJECT_BRIEF":
                self.stage_context(
                    claim,
                    {
                        "artifact_id": reference.get("source_id"),
                        "version_number": reference.get("source_version"),
                        "content_hash": reference.get("content_hash"),
                    },
                    "brief",
                )
            exact = (
                str(reference.get("source_id")),
                reference.get("source_version"),
                reference.get("content_hash"),
            )
            if kind == "EMPIRICAL_RESEARCH" and exact not in supported_exact:
                self.gap(claim, "MISSING_SOURCE", reference.get("source_id"), "evidence")
        if not supported_exact and not any(
            gap["code"] == "SOURCE_RETIRED" for gap in claim["gaps"]
        ):
            self.gap(claim, "MISSING_SOURCE", observation_key, "evidence")

    def twin_link(self, node, reference, relation="ACTOR"):
        reference = _mapping(reference)
        exact = (
            str(reference.get("twin_id")),
            reference.get("version_number", reference.get("twin_version")),
            reference.get("content_hash"),
        )
        twin = self.twin_index.get(exact)
        if twin:
            self.link(node, twin, relation)
        else:
            self.gap(
                node, "MISSING_TWIN", str(reference.get("twin_id")) if reference else None, "twins"
            )

    def source_links(self, node, sources, envelope):
        for source in _items(sources):
            kind = source.get("kind", source.get("source_kind"))
            if kind == "USER_TWIN":
                exact = (
                    str(source.get("source_id")),
                    source.get("source_version"),
                    source.get("content_hash"),
                )
                locator = source.get("locator")
                claim = self.claim_index.get((*exact, locator))
                if claim:
                    self.link(node, claim, "GROUNDED_IN")
                elif locator:
                    self.gap(node, "MISSING_CLAIM", str(locator), "twins")
                elif exact in self.twin_index:
                    self.link(node, self.twin_index[exact], "GROUNDED_IN")
                    self.gap(node, "MISSING_CLAIM", source.get("source_id"), "twins")
                else:
                    self.gap(node, "MISSING_TWIN", source.get("source_id"), "twins")
            elif kind == "PROJECT_BRIEF":
                self.stage_context(
                    node,
                    {
                        "artifact_id": source.get("source_id"),
                        "version_number": source.get("source_version"),
                        "content_hash": source.get("content_hash"),
                    },
                    "brief",
                    "GROUNDED_IN",
                )

    def perspectives(self, reference):
        reference = _mapping(reference)
        for envelope in self.stages["team"]:
            exact = _reference(envelope)
            if (
                exact["artifact_id"] != str(reference.get("artifact_id"))
                or exact["version_number"] != reference.get("version_number")
                or exact["content_hash"] != reference.get("content_hash")
            ):
                continue
            proposal = _mapping(envelope.get("proposal"))
            views = _items(envelope.get("perspectives", proposal.get("perspectives")))
            if views:
                return [deepcopy(dict(item)) for item in views if item.get("applied") is True]
            selected = set(
                proposal.get(
                    "selected_agent_ids",
                    (member.get("agent_id") for member in _items(proposal.get("members"))),
                )
            )
            return [
                {"key": key, "applied": True, "team_reference": deepcopy(dict(reference))}
                for key, agents in _PERSPECTIVES.items()
                if set(agents).issubset(selected)
            ]
        return []

    def requirements(self):
        for envelope in self.stages["requirements"]:
            specification = _mapping(envelope.get("specification"))
            context = str(envelope.get("id"))
            current = envelope.get("current", envelope == self.stages["requirements"][-1])
            kinds = {
                "requirements": "REQUIREMENT",
                "user_stories": "USER_STORY",
                "acceptance_criteria": "ACCEPTANCE_CRITERION",
                "scenarios": "SCENARIO",
                "needs": "NEED",
                "journeys": "JOURNEY",
                "risks": "PROJECT_RISK",
                "definition_of_done": "DEFINITION_OF_DONE",
            }
            for collection, kind in kinds.items():
                for item in _items(specification.get(collection)):
                    node = self.node(
                        kind,
                        item.get("code", item.get("id")),
                        item.get("title", item.get("goal", item.get("statement"))),
                        _reference(envelope, item.get("id")),
                        context=context,
                        current=current,
                        data=item,
                        rationale_origin="OWNER"
                        if any(
                            source.get("kind") == "OWNER_INPUT"
                            and source.get("source_id") == "owner-provided-definition"
                            for source in _items(item.get("sources"))
                        )
                        else "MODEL",
                    )
                    self.note_stage(node, envelope)
                    self.index[(kind, str(item.get("id")), context)] = node
                    if kind in {"REQUIREMENT", "USER_STORY"}:
                        if not item.get("need_ids"):
                            self.gap(node, "MISSING_NEED", None, "requirements")
                            team = _mapping(specification.get("context")).get("agent_team")
                            node["declared_context"]["perspectives"] = self.perspectives(team)
                            node["declared_context"]["team_reference"] = deepcopy(team)
                        for identifier in item.get("need_ids", ()):
                            self.queue(
                                node,
                                "NEED",
                                identifier,
                                context,
                                "MOTIVATED_BY",
                                "MISSING_NEED",
                                "requirements",
                            )
                    if kind == "NEED":
                        if not item.get("scenario_ids"):
                            self.gap(node, "MISSING_SCENARIO", None, "requirements")
                        for identifier in item.get("scenario_ids", ()):
                            self.queue(
                                node,
                                "SCENARIO",
                                identifier,
                                context,
                                "REVEALED_BY",
                                "MISSING_SCENARIO",
                                "requirements",
                            )
                    if kind == "SCENARIO":
                        if self.validation_context:
                            node["declared_context"]["scenario"] = deepcopy(dict(item))
                        self.twin_link(node, item.get("actor"))
                        if not any(
                            source.get("kind") == "USER_TWIN" and source.get("locator")
                            for source in _items(item.get("sources"))
                        ):
                            self.gap(
                                node,
                                "MISSING_CLAIM",
                                _mapping(item.get("actor")).get("twin_id"),
                                "twins",
                            )
                    for twin in _items(item.get("user_twin_references")):
                        self.twin_link(node, twin)
                    if item.get("user_twin_reference"):
                        self.twin_link(node, item["user_twin_reference"])
                    self.source_links(node, item.get("sources"), envelope)
                    if kind != "SCENARIO":
                        for identifier in item.get("requirement_ids", ()):
                            self.queue(node, "REQUIREMENT", identifier, context)
                        for identifier in item.get("user_story_ids", ()):
                            self.queue(node, "USER_STORY", identifier, context)
                        for identifier in item.get("acceptance_criterion_ids", ()):
                            self.queue(node, "ACCEPTANCE_CRITERION", identifier, context)
                    if kind == "JOURNEY" and item.get("scenario_id"):
                        self.queue(node, "SCENARIO", item["scenario_id"], context)
                    if kind == "ACCEPTANCE_CRITERION" and item.get("requirement_id"):
                        self.queue(node, "REQUIREMENT", item["requirement_id"], context)

    def requirements_context(self, package):
        grounding = _mapping(package.get("grounding"))
        reference = _mapping(grounding.get("requirements_reference", grounding.get("requirements")))
        return str(reference.get("artifact_id", grounding.get("requirements_version_id", "")))

    def artifact_links(self, node, item, requirements_context):
        for field, kind in (
            ("requirement_ids", "REQUIREMENT"),
            ("user_story_ids", "USER_STORY"),
            ("acceptance_criterion_ids", "ACCEPTANCE_CRITERION"),
        ):
            for identifier in item.get(field, ()):
                self.queue(node, kind, identifier, requirements_context, stage="requirements")
        for twin in _items(item.get("user_twin_references")):
            self.twin_link(node, twin)

    def prototype(self, prototype, envelope, alternative, requirements_context):
        prototype = _mapping(prototype)
        if not prototype:
            return
        context = f"{envelope.get('id')}:{alternative.get('id')}:{prototype.get('id')}"

        def note_mockup(node, screen_code):
            node["declared_context"]["mockup"] = {
                "alternative_id": str(
                    prototype.get("design_alternative_id", alternative.get("id", ""))
                ),
                "prototype_id": str(prototype.get("id", "")),
                "screen_code": screen_code,
                "source": "LATEST" if envelope.get("audit_reference") else "APPLIED",
                "document_hashes": deepcopy(envelope.get("mockup_document_hashes", {})),
                "visual_derived": True,
            }

        for screen in _items(prototype.get("screens")):
            screen_node = self.node(
                "PROTOTYPE_SCREEN",
                screen.get("code"),
                screen.get("title"),
                _reference(envelope, screen.get("id")),
                context=context,
                current=envelope.get("current", True),
                data=screen,
            )
            self.note_stage(screen_node, envelope)
            note_mockup(screen_node, screen.get("code"))
            self.index[("PROTOTYPE_SCREEN", str(screen.get("code")), str(envelope.get("id")))] = (
                screen_node
            )
            self.artifact_links(screen_node, screen, requirements_context)
            for element in _items(screen.get("elements")):
                node = self.node(
                    "PROTOTYPE_ELEMENT",
                    element.get("code"),
                    element.get("accessible_name") or element.get("content"),
                    _reference(envelope, element.get("id")),
                    context=f"{context}:{screen.get('id')}",
                    current=envelope.get("current", True),
                    data=element,
                )
                self.note_stage(node, envelope)
                note_mockup(node, screen.get("code"))
                self.index[
                    (
                        "PROTOTYPE_ELEMENT",
                        f"{screen.get('code')}/{element.get('code')}",
                        str(envelope.get("id")),
                    )
                ] = node
                self.artifact_links(node, element, requirements_context)
                if not any(
                    element.get(field)
                    for field in ("requirement_ids", "user_story_ids", "acceptance_criterion_ids")
                ):
                    self.gap(node, "OMITTED_SECTION", None, "requirements")
                self.link(node, screen_node, "CONTEXT")

    def design(self):
        for envelope in self.stages["design"]:
            package = _mapping(envelope.get("package"))
            context = str(envelope.get("id"))
            req_context = self.requirements_context(package)
            current = envelope.get("current", envelope == self.stages["design"][-1])
            for alternative in _items(package.get("alternatives")):
                node = self.node(
                    "DESIGN_ALTERNATIVE",
                    alternative.get("code"),
                    alternative.get("title"),
                    _reference(envelope, alternative.get("id")),
                    context=context,
                    current=current,
                    data=alternative,
                    rationale_origin="MODEL",
                )
                self.note_stage(node, envelope)
                self.index[("DESIGN_ALTERNATIVE", str(alternative.get("id")), context)] = node
                self.artifact_links(node, alternative, req_context)
                for workflow in _items(alternative.get("workflows")):
                    child = self.node(
                        "DESIGN_WORKFLOW",
                        workflow.get("code"),
                        workflow.get("title"),
                        _reference(envelope, workflow.get("id")),
                        context=f"{context}:{alternative.get('id')}",
                        current=current,
                        data=workflow,
                    )
                    self.artifact_links(child, workflow, req_context)
                    self.note_stage(child, envelope)
                    self.link(child, node, "CONTEXT")
            selected_id = package.get("owner_selected_alternative_id")
            if selected_id:
                selected = self.nodes.get(
                    _key(
                        "DESIGN_ALTERNATIVE",
                        selected_id,
                        envelope.get("version_number"),
                        envelope.get("content_hash"),
                        context,
                    )
                )
                node = self.node(
                    "DESIGN_SELECTION",
                    f"CHOICE-v{envelope.get('version_number')}",
                    selected["title"] if selected else "Design selection",
                    _reference(envelope),
                    context="selection",
                    current=current,
                    data={"rationale": package.get("selection_rationale")},
                    rationale_origin="OWNER",
                )
                self.note_stage(node, envelope)
                self.link(node, selected, "SELECTS")
                if not node["rationale"]:
                    self.gap(node, "MISSING_RATIONALE", None, "design")
            for collection, kind in (
                ("critiques", "SYNTHETIC_DESIGN_CRITIQUE"),
                ("concerns", "DESIGN_CONCERN"),
            ):
                for item in _items(package.get(collection)):
                    node = self.node(
                        kind,
                        item.get("code"),
                        item.get("title", item.get("rationale")),
                        _reference(envelope, item.get("id")),
                        context=context,
                        current=current,
                        data=item,
                        rationale_origin="MODEL",
                    )
                    node["validation_required"] = True
                    self.note_stage(node, envelope)
                    self.artifact_links(node, item, req_context)
                    if item.get("user_twin_reference"):
                        self.twin_link(node, item["user_twin_reference"])
                    if item.get("design_alternative_id"):
                        self.queue(
                            node,
                            "DESIGN_ALTERNATIVE",
                            item["design_alternative_id"],
                            context,
                            "CRITIQUES",
                        )
            prototype = _mapping(package.get("prototype"))
            alternative = next(
                (
                    item
                    for item in _items(package.get("alternatives"))
                    if str(item.get("id")) == str(prototype.get("design_alternative_id"))
                ),
                {},
            )
            self.prototype(prototype, {**envelope, "current": current}, alternative, req_context)

    def evaluations(self, values):
        runs = []
        decisions = {}
        for item in _items(values):
            runs.extend(_items(item.get("runs")) if "runs" in item else [item])
            for decision in _items(item.get("decisions")):
                key = (
                    str(decision.get("evaluation_run_id")),
                    str(decision.get("twin_id")),
                    decision.get("finding_id"),
                )
                if key not in decisions or decision.get("sequence_number", 0) > decisions[key].get(
                    "sequence_number", 0
                ):
                    decisions[key] = decision

        def run_order(run):
            envelope = _mapping(run.get("run", run))
            completed_at = envelope.get("completed_at")
            try:
                moment = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
                if moment.tzinfo is None:
                    moment = moment.replace(tzinfo=UTC)
                moment = moment.astimezone(UTC)
            except ValueError:
                moment = datetime.min.replace(tzinfo=UTC)
            return moment, str(envelope.get("id", envelope.get("run_id", "")))

        latest_run = max(runs, key=run_order) if runs else None
        latest_design = _reference(self.stages["design"][-1]) if self.stages["design"] else None
        for run in runs:
            envelope = _mapping(run.get("run", run))
            context = str(envelope.get("id", envelope.get("run_id", "")))
            design_ref = _mapping(
                envelope.get("design_reference", envelope.get("design_version_reference"))
            )
            design_id = str(envelope.get("design_version_id", design_ref.get("artifact_id", "")))
            base_reference = {
                "artifact_id": design_id,
                "version_number": envelope.get(
                    "design_version_number", design_ref.get("version_number")
                ),
                "content_hash": envelope.get("design_content_hash", design_ref.get("content_hash")),
            }
            current = run is latest_run and base_reference == latest_design
            for response in _items(envelope.get("responses")):
                for finding in _items(response.get("findings")):
                    version = finding.get("artifact_version")
                    reference = {
                        "artifact_id": str(finding.get("artifact_id")),
                        "version_number": version,
                        "content_hash": finding.get("content_hash"),
                    }
                    node = self.node(
                        "SYNTHETIC_FINDING",
                        finding.get("finding_id"),
                        finding.get("summary"),
                        reference,
                        context=f"{context}:{finding.get('twin_id')}:{finding.get('twin_version')}",
                        current=current,
                        data=finding,
                        rationale_origin="MODEL",
                    )
                    node["declared_context"]["base_reference"] = deepcopy(base_reference)
                    base_design = self.stage_context(node, base_reference, "design")
                    alternative_id = envelope.get(
                        "design_alternative_id", envelope.get("alternative_id")
                    )
                    if base_design and alternative_id:
                        self.queue(
                            node,
                            "DESIGN_ALTERNATIVE",
                            alternative_id,
                            design_id,
                            "CONTEXT",
                            stage="design",
                        )
                    node["declared_context"]["evaluation_reference"] = {
                        "artifact_id": context,
                        "content_hash": envelope.get("content_hash"),
                    }
                    node["declared_context"]["model_config_ref"] = finding.get("model_config_ref")
                    node["declared_context"]["prompt_version_ref"] = finding.get(
                        "prompt_version_ref"
                    )
                    node["declared_context"]["evidence_refs"] = deepcopy(
                        finding.get("evidence_refs", [])
                    )
                    decision = decisions.get(
                        (context, str(finding.get("twin_id")), finding.get("finding_id"))
                    )
                    if decision:
                        node["declared_context"]["owner_decision"] = deepcopy(decision)
                    node["validation_required"] = True
                    if node["display_status"] in {"UNKNOWN", "EVIDENCED"}:
                        node["display_status"] = "INFERRED"
                    twin_id = str(finding.get("twin_id"))
                    twin_version = finding.get("twin_version")
                    candidates = [
                        twin
                        for exact, twin in self.twin_index.items()
                        if exact[0] == twin_id and exact[1] == twin_version
                    ]
                    if len(candidates) == 1:
                        self.link(node, candidates[0], "EVALUATED_BY")
                    else:
                        self.gap(node, "MISSING_TWIN", twin_id, "twins")
                    resolved_claim = False
                    for reference_code in finding.get("evidence_refs", ()):
                        match = re.fullmatch(
                            r"user-twin:([^:]+):v([0-9]+)#(user_twin\.[a-z_]+)", str(reference_code)
                        )
                        if match:
                            claims = [
                                claim
                                for exact, claim in self.claim_index.items()
                                if exact[0] == match[1]
                                and exact[1] == int(match[2])
                                and exact[3] == match[3]
                            ]
                            if len(claims) == 1:
                                self.link(node, claims[0], "GROUNDED_IN")
                                resolved_claim = True
                            else:
                                self.gap(node, "MISSING_CLAIM", str(reference_code), "twins")
                    anchor = finding.get("anchor_key")
                    if anchor:
                        kind = "PROTOTYPE_ELEMENT" if "/" in anchor else "PROTOTYPE_SCREEN"
                        self.queue(node, kind, anchor, design_id, "EVALUATES", stage="design")
                    elif not resolved_claim:
                        self.gap(node, "MISSING_CLAIM", str(finding.get("finding_id")), "twins")

    def finish(self):
        for node, kind, identifier, context, relation, gap, stage in self.pending:
            origin = self.index.get((kind, identifier, context))
            if origin:
                self.link(node, origin, relation)
            else:
                self.gap(node, gap, identifier, stage)
        omitted = [stage for stage, values in self.stages.items() if not values]
        omitted.extend(
            str(stage)
            for stage in self.sections.get("omitted_sections", ())
            if stage not in omitted
        )
        for node in self.nodes.values():
            node["gaps"].sort(
                key=lambda item: (item["code"], item["related_code"] or "", item["stage"] or "")
            )
            citations = {
                json.dumps(item, sort_keys=True, ensure_ascii=False): item
                for item in node["citations"]
            }
            node["citations"] = [citations[key] for key in sorted(citations)]
        return {
            "kind": "orchestwin.why",
            "schema_version": 1,
            "project_id": self.project_id,
            "nodes": sorted(
                self.nodes.values(), key=lambda item: (item["kind"], item["code"], item["key"])
            ),
            "links": [
                {"source": source, "target": target, "kind": kind}
                for source, target, kind in sorted(self.links)
            ],
            "omitted_sections": sorted(set(omitted)),
        }

    def human_validation(self, hypotheses, outcomes):
        latest = {}
        for item in _items(hypotheses):
            latest[str(item.get("id"))] = max(
                latest.get(str(item.get("id")), 0), item.get("version_number", 0)
            )
        identities = {}
        for item in _items(hypotheses):
            node = self.node(
                "VALIDATION_HYPOTHESIS",
                item.get("code"),
                item.get("question") or item.get("task"),
                _reference(item),
                current=item.get("version_number") == latest[str(item.get("id"))],
            )
            node["declared_context"]["hypothesis"] = deepcopy(dict(item))
            identities[
                (str(item.get("id")), item.get("version_number"), item.get("content_hash"))
            ] = node
            for field, relation in (
                ("origin_key", "ORIGINATES_FROM"),
                ("twin_key", "ACTOR"),
                ("scenario_key", "VERIFIES_SCENARIO"),
                ("design_key", "VERIFIES_DESIGN"),
            ):
                origin = self.nodes.get(item.get(field))
                if origin:
                    self.link(node, origin, relation)
                    if not origin["current"]:
                        self.gap(node, "CONTEXT_OUTDATED", origin["code"])
                else:
                    self.gap(node, "VALIDATION_REFERENCE_UNAVAILABLE", field)
        for item in _items(outcomes):
            reference = {
                "artifact_id": str(item.get("id")),
                "version_number": 1,
                "content_hash": item.get("content_hash"),
            }
            node = self.node("VALIDATION_OUTCOME", item.get("code"), item.get("outcome"), reference)
            node["declared_context"]["outcome"] = deepcopy(dict(item))
            hypothesis = identities.get(
                (
                    str(item.get("hypothesis_id")),
                    item.get("hypothesis_version_number"),
                    item.get("hypothesis_content_hash"),
                )
            )
            if hypothesis:
                self.link(node, hypothesis, "TESTS_HYPOTHESIS")
            else:
                self.gap(node, "VALIDATION_REFERENCE_UNAVAILABLE", str(item.get("hypothesis_id")))
            source = self.source_index.get(
                (
                    str(item.get("evidence_id")),
                    item.get("evidence_version"),
                    item.get("evidence_content_hash"),
                )
            )
            if source:
                self.link(node, source, "RECORDED_IN")
                source_metadata = source["declared_context"]["source"]
                retired = source_metadata.get("status") == "RETIRED"
                node["current"] = not retired
                node["declared_context"]["effective_status"] = "RETIRED" if retired else "ACTIVE"
                if retired:
                    self.gap(node, "SOURCE_RETIRED", source["code"], "evidence")
                if source_metadata.get("text_available") is False:
                    self.gap(node, "SOURCE_TEXT_UNAVAILABLE", source["code"], "evidence")
                node["citations"].append(
                    {
                        "citation": deepcopy(item.get("citation", {})),
                        "source": deepcopy(source_metadata),
                        "status": "RETIRED" if retired else "ACTIVE",
                        "session_kind": item.get("session_kind"),
                    }
                )
            else:
                self.gap(node, "MISSING_SOURCE_VERSION", str(item.get("evidence_id")), "evidence")


def build_why_document(
    *,
    project_id: str,
    stages: Mapping[str, object],
    evidence: Mapping | None = None,
    evaluations: Sequence = (),
    learning: Mapping | None = None,
    mockups: Sequence = (),
    sections: Mapping | None = None,
    hypotheses: Sequence = (),
    outcomes: Sequence = (),
    validation_context: bool = False,
    workflow_inputs: Mapping | None = None,
) -> dict:
    builder = _Builder(project_id, stages, evidence, sections, validation_context)
    builder.stage_roots()
    builder.sources()
    builder.twins()
    builder.requirements()
    builder.design()
    for mockup in _items(mockups):
        envelope = _mapping(mockup.get("version", mockup))
        base = _mapping(envelope.get("base_reference"))
        base_envelope = next(
            (
                item
                for item in builder.stages["design"]
                if str(item.get("id")) == str(base.get("artifact_id"))
            ),
            {},
        )
        if base_envelope.get("section"):
            envelope = {**envelope, "section": base_envelope["section"]}
        package = _mapping(envelope.get("package"))
        builder.prototype(
            mockup.get("prototype", package.get("prototype")),
            envelope,
            _mapping(mockup.get("alternative")),
            builder.requirements_context(package),
        )
    builder.evaluations(evaluations)
    builder.human_validation(hypotheses, outcomes)
    from orchestwin.artifacts.workflow_why import add_workflow_why

    records = add_workflow_why(builder, workflow_inputs)
    result = builder.finish()
    if records is not None:
        result["workflow_records"] = records
    return result
