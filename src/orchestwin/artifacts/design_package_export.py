from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from orchestwin.agents.proposals import TeamProposalVersion
from orchestwin.agents.team_gate import agent_team_gate_is_currently_approved
from orchestwin.artifacts.design_gate import design_gate_is_currently_approved
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.mockup_html import MOCKUP_HTML_FILE, mockup_html
from orchestwin.projects.brief_gate import project_brief_gate_is_currently_approved
from orchestwin.projects.briefs import ProjectBriefVersion
from orchestwin.projects.requirements_gate import requirements_gate_is_currently_approved
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.twins.user_modeling_gate import user_modeling_gate_is_currently_approved
from orchestwin.twins.user_twins import UserModelingSnapshotVersion
from orchestwin.workflow.gates import HumanGate

DESIGN_PACKAGE_SCHEMA_VERSION: Final = 1
DESIGN_PACKAGE_INDEX: Final = "ORCHESTWIN.md"
DESIGN_PACKAGE_MANIFEST: Final = "orchestwin.json"
STAGE_LABELS: Final = {
    "brief": "Project brief",
    "team": "Agent team",
    "twins": "User twins",
    "requirements": "Requirements",
    "design": "Design",
}
_ENTRY_DATE_TIME: Final = (1980, 1, 1, 0, 0, 0)
_UNSET: Final = "not provided"


class DesignPackageExportError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class DesignPackageSources:
    project_id: UUID
    brief: ProjectBriefVersion
    brief_gate: HumanGate
    team: TeamProposalVersion
    team_gate: HumanGate
    modeling: UserModelingSnapshotVersion
    modeling_gate: HumanGate
    requirements: RequirementsSpecificationVersion
    requirements_gate: HumanGate
    design: DesignPackageVersion
    design_gate: HumanGate


@dataclass(frozen=True, slots=True)
class DesignPackageArchive:
    project_id: UUID
    file_name: str
    content: bytes
    content_hash: str
    entries: tuple[str, ...]


def _text(value: object) -> str:
    if value is None:
        return _UNSET
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return value if value.strip() else _UNSET
    if isinstance(value, Mapping):
        return ", ".join(f"{key}: {_text(item)}" for key, item in value.items()) or _UNSET
    if isinstance(value, Sequence):
        return ", ".join(_text(item) for item in value) if value else _UNSET
    return str(value)


def _title(value: str) -> str:
    return value.replace("_", " ").capitalize()


def _bullets(items: Iterable[object]) -> list[str]:
    lines = [f"- {_text(item)}" for item in items]
    return lines or [f"- {_UNSET}"]


def _cell(value: object) -> str:
    if value is None or (isinstance(value, Sequence) and not isinstance(value, str) and not value):
        return ""
    return _text(value).replace("|", "/").replace("\n", " ")


def _table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    body = ["| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows]
    if not body:
        return [f"{_UNSET}."]
    return [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(" --- " for _ in headers) + "|",
        *body,
    ]


def _reference(reference: Mapping[str, object]) -> str:
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
        return "; ".join(_text(item) for item in items)
    reason = value.get("reason")
    return f"unknown ({reason})" if reason else _UNSET


def _observations(observations: Iterable[Mapping[str, object]]) -> list[str]:
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
    return _table(("Observation", "Value", "Epistemic status", "Confidence", "Validation"), rows)


def _json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _enum_text(value: object) -> object:
    return getattr(value, "value", value)


def _version_document(version: object, key: str, payload: object) -> dict[str, object]:
    document: dict[str, object] = {
        "id": str(version.id),
        "project_id": str(version.project_id),
        "version_number": version.version_number,
        "content_hash": version.content_hash,
        "created_by_user_id": str(version.created_by_user_id),
        "created_at": version.created_at.isoformat(),
    }
    based_on = getattr(version, "based_on_version_number", None)
    if based_on is not None:
        document["based_on_version_number"] = based_on
    revision_kind = getattr(version, "revision_kind", None)
    if revision_kind is not None:
        document["revision_kind"] = _enum_text(revision_kind)
    document[key] = payload
    return document


def _gate_document(gate: HumanGate) -> dict[str, object]:
    return {
        "id": str(gate.id),
        "gate_type": gate.gate_type.value,
        "status": gate.status.value,
        "iteration": gate.iteration,
        "updated_at": gate.updated_at.isoformat(),
        "artifact": {
            "artifact_id": str(gate.artifact.artifact_id),
            "version": gate.artifact.version,
            "content_hash": gate.artifact.content_hash,
        },
    }


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
        lines.extend([f"## {_title(key)}", ""])
        if isinstance(value, list):
            lines.extend(_bullets(value))
        else:
            lines.append(_text(value))
        lines.append("")
    lines.extend(["## Fields marked as unknown", "", *_bullets(snapshot["unknown_fields"]), ""])
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
        rows.append((_title(member["agent_id"]), _title(member["source"]), justifications))
    lines.extend(_table(("Agent", "Source", "Justification"), rows))
    lines.extend(["", "## Role constraints", ""])
    rows = [
        (
            _title(constraint["agent_id"]),
            constraint["kind"],
            "; ".join(reason["code"] for reason in constraint["reasons"]),
        )
        for constraint in snapshot["constraints"]["role_constraints"]
    ]
    lines.extend(
        _table(
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
                f"Source {_title(profile['source'])}, {_title(profile['kind'])}, "
                f"{_title(profile['confirmation_status'])}, "
                f"version {persona['version_number']}.",
                "",
                *_observations(profile["observations"]),
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
                f"persona {_reference(profile['persona_reference'])}.",
                "",
                *_observations(profile["observations"]),
                "",
            ]
        )
    return "\n".join(lines)


def _code_index(specification: Mapping[str, object]) -> dict[str, str]:
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


def _codes(identifiers: Iterable[str], codes: Mapping[str, str]) -> str:
    return ", ".join(codes.get(identifier, identifier) for identifier in identifiers) or _UNSET


def requirements_markdown(version: RequirementsSpecificationVersion, gate: HumanGate) -> str:
    specification = version.specification.to_snapshot()
    codes = _code_index(specification)
    lines = _version_lines(STAGE_LABELS["requirements"], version, gate)
    lines.extend(["## User twins in scope", ""])
    lines.extend(_bullets(_reference(item) for item in specification["user_twin_references"]))
    lines.extend(["", "## Requirements", ""])
    lines.extend(
        _table(
            ("Code", "Title", "Kind", "Priority", "Statement", "Twins"),
            (
                (
                    item["code"],
                    item["title"],
                    item["kind"],
                    item["priority"],
                    item["statement"],
                    ", ".join(twin["name"] for twin in item["user_twin_references"]),
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
            f"(requirements {_codes(story['requirement_ids'], codes)})."
        )
    lines.extend(["", "## Acceptance criteria", ""])
    lines.extend(
        _table(
            ("Code", "Statement", "Verification", "Requirements", "User stories"),
            (
                (
                    item["code"],
                    item["statement"],
                    _title(item["verification_method"]),
                    _codes(item["requirement_ids"], codes),
                    _codes(item["user_story_ids"], codes),
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
                *_bullets(scenario["preconditions"]),
                "",
                "Steps:",
                *[f"{index}. {step}" for index, step in enumerate(scenario["steps"], 1)],
                "",
                f"Expected outcome: {scenario['expected_outcome']} "
                f"(requirements {_codes(scenario['requirement_ids'], codes)}, criteria "
                f"{_codes(scenario['acceptance_criterion_ids'], codes)}).",
                "",
            ]
        )
    lines.extend(["## Risks", ""])
    lines.extend(_bullets(specification["risks"]))
    lines.extend(["", "## Definition of done", ""])
    lines.extend(
        _table(
            ("Code", "Statement", "Verification", "Applicability", "Condition", "Requirements"),
            (
                (
                    item["code"],
                    item["statement"],
                    _title(item["verification_method"]),
                    item["applicability"],
                    item["condition"],
                    _codes(item["requirement_ids"], codes),
                )
                for item in specification["definition_of_done"]
            ),
        )
    )
    lines.append("")
    return "\n".join(lines)


def _alternative_codes(package: Mapping[str, object]) -> dict[str, str]:
    return {item["id"]: item["code"] for item in package["alternatives"]}


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
            f"Selected alternative: {alternatives.get(selected, _UNSET)}. "
            f"Recommended alternative: {alternatives.get(recommended, _UNSET)}.",
            "",
            "## Alternatives",
            "",
        ]
    )
    for item in package["alternatives"]:
        lines.extend(
            [
                f"### {item['code']}: {item['title']}",
                "",
                f"Approach {_title(item['approach'])}. {item['summary']}",
                "",
                f"Rationale: {item['rationale']}",
                "",
                f"Requirements {_codes(item['requirement_ids'], codes)}; user stories "
                f"{_codes(item['user_story_ids'], codes)}; acceptance criteria "
                f"{_codes(item['acceptance_criterion_ids'], codes)}; twins "
                f"{', '.join(twin['name'] for twin in item['user_twin_references']) or _UNSET}.",
                "",
                "#### Workflows",
                "",
            ]
        )
        for workflow in item["workflows"]:
            lines.extend(
                [
                    f"- {workflow['code']}: {workflow['title']} "
                    f"(requirements {_codes(workflow['requirement_ids'], codes)})",
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
            lines.extend(["", f"#### {_title(key)}", "", *_bullets(item[key])])
        lines.extend(_visual_language_lines(item.get("visual_language")))
        lines.append("")
    lines.extend(["## Concerns", ""])
    for concern in package["concerns"]:
        lines.append(
            f"- {concern['code']}: {concern['summary']} Mitigation: {concern['mitigation']} "
            f"(alternatives {_codes(concern['design_alternative_ids'], alternatives)}, "
            f"requirements {_codes(concern['requirement_ids'], codes)})"
        )
    if not package["concerns"]:
        lines.append(f"- {_UNSET}")
    lines.extend(["", "## Open questions", "", *_bullets(package["open_questions"]), ""])
    return "\n".join(lines)


def _visual_language_lines(visual: Mapping[str, object] | None) -> list[str]:
    if visual is None:
        return []
    choices = visual["choices"]
    described = ", ".join(
        f"{name.replace('_', ' ')} {_title(value)}" for name, value in choices.items()
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
        *_bullets(f"{item['name']}: {item['statement']}" for item in visual["twin_fit"]),
        "",
        *_table(("Role", "Colour"), visual["palette"].items()),
    ]


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
                f"{alternatives.get(critique['design_alternative_id'], _UNSET)}",
                "",
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
            lines.extend([f"### {_title(key)}", "", *_bullets(critique[key]), ""])
    if not package["critiques"]:
        lines.append(f"{_UNSET}.")
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
            f"{alternatives.get(prototype['design_alternative_id'], _UNSET)}. Viewports "
            f"{_text(prototype['supported_viewports'])}. Entry screen "
            f"{screens[prototype['entry_screen_id']]['code']}.",
            "",
        ]
    )
    for screen in prototype["screens"]:
        lines.extend([f"## {screen['code']}: {screen['title']} ({_title(screen['state'])})", ""])
        lines.extend(
            _table(
                ("Code", "Kind", "Content", "Accessible name", "Field", "Required", "Options"),
                (
                    (
                        element["code"],
                        _title(element["kind"]),
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
            f"{trigger.get('code', _UNSET)} ({trigger.get('content', _UNSET)}): "
            f"{transition['outcome']}"
        )
    if not prototype["transitions"]:
        lines.append(f"- {_UNSET}")
    lines.append("")
    return "\n".join(lines)


def _stage_documents(sources: DesignPackageSources) -> dict[str, dict[str, object]]:
    return {
        "brief": _version_document(sources.brief, "brief", sources.brief.brief.to_snapshot()),
        "team": _version_document(sources.team, "proposal", sources.team.proposal.to_snapshot()),
        "twins": _version_document(
            sources.modeling, "snapshot", sources.modeling.snapshot.to_snapshot()
        ),
        "requirements": _version_document(
            sources.requirements,
            "specification",
            sources.requirements.specification.to_snapshot(),
        ),
        "design": _version_document(
            sources.design, "package", sources.design.package.to_snapshot()
        ),
    }


def _gates(sources: DesignPackageSources) -> dict[str, HumanGate]:
    return {
        "brief": sources.brief_gate,
        "team": sources.team_gate,
        "twins": sources.modeling_gate,
        "requirements": sources.requirements_gate,
        "design": sources.design_gate,
    }


def design_package_files(sources: DesignPackageSources) -> dict[str, str]:
    codes = _code_index(sources.requirements.specification.to_snapshot())
    documents = _stage_documents(sources)
    gates = _gates(sources)
    files = {
        "brief/brief.md": brief_markdown(sources.brief, gates["brief"]),
        "brief/brief.json": _json(documents["brief"]),
        "team/team.md": team_markdown(sources.team, gates["team"]),
        "team/team.json": _json(documents["team"]),
        "twins/twins.md": twins_markdown(sources.modeling, gates["twins"]),
        "twins/twins.json": _json(documents["twins"]),
        "requirements/requirements.md": requirements_markdown(
            sources.requirements, gates["requirements"]
        ),
        "requirements/requirements.json": _json(documents["requirements"]),
        "design/design.md": design_markdown(sources.design, gates["design"], codes),
        "design/critiques.md": critiques_markdown(sources.design),
        "design/mockups.md": mockups_markdown(sources.design),
        MOCKUP_HTML_FILE: mockup_html(sources.design),
        "design/design.json": _json(documents["design"]),
    }
    digests = {
        path: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for path, content in sorted(files.items())
    }
    stages = {
        stage: {
            "label": STAGE_LABELS[stage],
            "version_id": documents[stage]["id"],
            "version_number": documents[stage]["version_number"],
            "content_hash": documents[stage]["content_hash"],
            "gate": _gate_document(gates[stage]),
        }
        for stage in STAGE_LABELS
    }
    manifest = {
        "schema_version": DESIGN_PACKAGE_SCHEMA_VERSION,
        "project_id": str(sources.project_id),
        "stages": stages,
        "files": digests,
    }
    index = [
        "# OrchesTwin design package",
        "",
        f"Project {sources.project_id}, package schema version "
        f"{DESIGN_PACKAGE_SCHEMA_VERSION}. Every stage below was approved by its human gate; "
        "the JSON file next to each Markdown document is the exact approved snapshot.",
        "",
        "## Approved stages",
        "",
        *_table(
            ("Stage", "Gate", "Version", "Content hash", "Approved at"),
            (
                (
                    entry["label"],
                    entry["gate"]["gate_type"],
                    entry["version_number"],
                    entry["content_hash"],
                    entry["gate"]["updated_at"],
                )
                for entry in stages.values()
            ),
        ),
        "",
        "## Files",
        "",
        *_table(("File", "SHA-256"), digests.items()),
        "",
    ]
    files[DESIGN_PACKAGE_INDEX] = "\n".join(index)
    files[DESIGN_PACKAGE_MANIFEST] = _json(manifest)
    return files


def build_design_package(sources: DesignPackageSources) -> DesignPackageArchive:
    files = design_package_files(sources)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=_ENTRY_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[path].encode("utf-8"))
    content = buffer.getvalue()
    return DesignPackageArchive(
        project_id=sources.project_id,
        file_name=f"orchestwin-{sources.project_id}-design-package.zip",
        content=content,
        content_hash=hashlib.sha256(content).hexdigest(),
        entries=tuple(sorted(files)),
    )


class DesignPackageExportService:
    def __init__(
        self,
        *,
        project_service,
        brief_gate_service,
        team_proposal_service,
        agent_team_service,
        user_modeling_services,
        requirements_query_service,
        requirements_gate_service,
        design_query_service,
        design_gate_service,
    ) -> None:
        self.project_service = project_service
        self.brief_gate_service = brief_gate_service
        self.team_proposal_service = team_proposal_service
        self.agent_team_service = agent_team_service
        self.user_modeling_services = user_modeling_services
        self.requirements_query_service = requirements_query_service
        self.requirements_gate_service = requirements_gate_service
        self.design_query_service = design_query_service
        self.design_gate_service = design_gate_service

    async def load_sources(self, *, owner_user_id: UUID, project_id: UUID) -> DesignPackageSources:
        scope = {"project_id": project_id, "owner_user_id": owner_user_id}
        brief = await self.project_service.current_brief(**scope)
        if brief is None:
            raise DesignPackageExportError("PROJECT_NOT_FOUND")
        brief_gate = await self.brief_gate_service.current_gate(**scope)
        if not project_brief_gate_is_currently_approved(brief_gate, brief):
            raise DesignPackageExportError("BRIEF_APPROVAL_REQUIRED")
        team = await self.team_proposal_service.current(**scope)
        team_gate = await self.agent_team_service.current_gate(**scope)
        if team is None or not agent_team_gate_is_currently_approved(team_gate, team):
            raise DesignPackageExportError("TEAM_APPROVAL_REQUIRED")
        modeling = await self.user_modeling_services.queries.current_snapshot(**scope)
        modeling_gate = await self.user_modeling_services.gates.current_gate(**scope)
        if modeling is None or not user_modeling_gate_is_currently_approved(
            modeling_gate, modeling
        ):
            raise DesignPackageExportError("USER_MODELING_APPROVAL_REQUIRED")
        requirements = await self.requirements_query_service.current(**scope)
        requirements_gate = await self.requirements_gate_service.current_gate(**scope)
        if requirements is None or not requirements_gate_is_currently_approved(
            requirements_gate, requirements
        ):
            raise DesignPackageExportError("REQUIREMENTS_APPROVAL_REQUIRED")
        design = await self.design_query_service.current(**scope)
        design_gate = await self.design_gate_service.current_gate(**scope)
        if design is None or not design_gate_is_currently_approved(design_gate, design):
            raise DesignPackageExportError("DESIGN_APPROVAL_REQUIRED")
        return DesignPackageSources(
            project_id=project_id,
            brief=brief,
            brief_gate=brief_gate,
            team=team,
            team_gate=team_gate,
            modeling=modeling,
            modeling_gate=modeling_gate,
            requirements=requirements,
            requirements_gate=requirements_gate,
            design=design,
            design_gate=design_gate,
        )

    async def export(self, *, owner_user_id: UUID, project_id: UUID) -> DesignPackageArchive:
        sources = await self.load_sources(owner_user_id=owner_user_id, project_id=project_id)
        return build_design_package(sources)


__all__ = [
    "DESIGN_PACKAGE_INDEX",
    "DESIGN_PACKAGE_MANIFEST",
    "DESIGN_PACKAGE_SCHEMA_VERSION",
    "DesignPackageArchive",
    "DesignPackageExportError",
    "DesignPackageExportService",
    "DesignPackageSources",
    "build_design_package",
    "design_package_files",
]
