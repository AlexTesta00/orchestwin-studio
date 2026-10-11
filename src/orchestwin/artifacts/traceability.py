"""Cross-stage artifact traceability derived from immutable project artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.references import ArtifactKind, VersionedArtifactReference
from orchestwin.projects.requirements_primitives import (
    RequirementsContextReference,
    canonical_json,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion


class ArtifactGraphStage(StrEnum):
    """Governed workflow stages represented in the artifact graph."""

    CONTEXT = "CONTEXT"
    REQUIREMENTS = "REQUIREMENTS"
    DESIGN = "DESIGN"


class ArtifactGraphNodeKind(StrEnum):
    """Kinds of immutable or derived artifacts represented as graph nodes."""

    PROJECT_BRIEF = "PROJECT_BRIEF"
    AGENT_TEAM = "AGENT_TEAM"
    USER_MODELING = "USER_MODELING"
    USER_TWIN = "USER_TWIN"
    RESEARCH_EVIDENCE = "RESEARCH_EVIDENCE"
    REQUIREMENTS_SPECIFICATION = "REQUIREMENTS_SPECIFICATION"
    REQUIREMENT = "REQUIREMENT"
    USER_STORY = "USER_STORY"
    ACCEPTANCE_CRITERION = "ACCEPTANCE_CRITERION"
    SCENARIO = "SCENARIO"
    NEED = "NEED"
    JOURNEY = "JOURNEY"
    PROJECT_RISK = "PROJECT_RISK"
    DEFINITION_OF_DONE = "DEFINITION_OF_DONE"
    DESIGN_PACKAGE = "DESIGN_PACKAGE"
    DESIGN_ALTERNATIVE = "DESIGN_ALTERNATIVE"
    DESIGN_WORKFLOW = "DESIGN_WORKFLOW"
    SYNTHETIC_DESIGN_CRITIQUE = "SYNTHETIC_DESIGN_CRITIQUE"
    DESIGN_CONCERN = "DESIGN_CONCERN"
    DECLARATIVE_PROTOTYPE = "DECLARATIVE_PROTOTYPE"
    PROTOTYPE_SCREEN = "PROTOTYPE_SCREEN"


class ArtifactGraphLinkKind(StrEnum):
    """Semantic relationships preserved across workflow stages."""

    CONTAINS = "CONTAINS"
    GROUNDED_IN = "GROUNDED_IN"
    ACTS_AS = "ACTS_AS"
    PARTICIPATES_IN = "PARTICIPATES_IN"
    REVEALS = "REVEALS"
    EXPANDS = "EXPANDS"
    MOTIVATES = "MOTIVATES"
    VERIFIED_BY = "VERIFIED_BY"
    EXERCISES = "EXERCISES"
    AFFECTS = "AFFECTS"
    GOVERNS = "GOVERNS"
    TRACES_TO = "TRACES_TO"
    REPRESENTS = "REPRESENTS"
    CRITIQUES = "CRITIQUES"
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    ADDS = "ADDS"


_Kind = ArtifactGraphNodeKind
_Relation = ArtifactGraphLinkKind

_STAGE_ORDER = {
    ArtifactGraphStage.CONTEXT: 0,
    ArtifactGraphStage.REQUIREMENTS: 1,
    ArtifactGraphStage.DESIGN: 2,
}


@dataclass(frozen=True, slots=True)
class ArtifactGraphReference:
    """Stable identity of one graph node, with an exact tuple when versioned."""

    kind: ArtifactGraphNodeKind
    artifact_id: UUID
    version_number: int | None = None
    content_hash: str | None = None

    def __post_init__(self) -> None:
        """Require version and hash to appear together and remain valid."""
        if (self.version_number is None) != (self.content_hash is None):
            raise ValueError("artifact graph references require both version and content hash")

        if self.version_number is not None:
            validate_positive_integer(
                self.version_number,
                label="artifact graph reference version number",
            )
            validate_sha256(
                self.content_hash,
                label="artifact graph reference content hash",
            )

    @property
    def sort_key(self) -> tuple[str, str, int, str]:
        """Return deterministic reference ordering metadata."""
        return (
            self.kind.value,
            self.artifact_id.hex,
            self.version_number or 0,
            self.content_hash or "",
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic graph-reference snapshot."""
        return {
            "kind": self.kind.value,
            "artifact_id": str(self.artifact_id),
            "version_number": self.version_number,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class ArtifactGraphNode:
    """One inspectable artifact in the cross-stage graph."""

    reference: ArtifactGraphReference
    stage: ArtifactGraphStage
    display_code: str
    title: str

    def __post_init__(self) -> None:
        """Protect normalized human-readable graph metadata."""
        for value, label in (
            (self.display_code, "artifact graph display code"),
            (self.title, "artifact graph title"),
        ):
            if not value or value != " ".join(value.split()):
                raise ValueError(f"{label} must be normalized")

    @property
    def sort_key(self) -> tuple[int, str, str, tuple[str, str, int, str]]:
        """Return canonical stage and identity ordering metadata."""
        return (
            _STAGE_ORDER[self.stage],
            self.reference.kind.value,
            self.display_code,
            self.reference.sort_key,
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic graph-node snapshot."""
        return {
            "reference": self.reference.to_snapshot(),
            "stage": self.stage.value,
            "display_code": self.display_code,
            "title": self.title,
        }


@dataclass(frozen=True, slots=True)
class ArtifactGraphLink:
    """One typed directional relationship between graph nodes."""

    kind: ArtifactGraphLinkKind
    source: ArtifactGraphReference
    target: ArtifactGraphReference

    def __post_init__(self) -> None:
        """Reject self-links that provide no cross-artifact information."""
        if self.source == self.target:
            raise ValueError("artifact graph links must connect different nodes")

    @property
    def sort_key(self) -> tuple[str, tuple[str, str, int, str], tuple[str, str, int, str]]:
        """Return deterministic relationship ordering metadata."""
        return (self.kind.value, self.source.sort_key, self.target.sort_key)

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic graph-link snapshot."""
        return {
            "kind": self.kind.value,
            "source": self.source.to_snapshot(),
            "target": self.target.to_snapshot(),
        }


@dataclass(frozen=True, slots=True)
class CrossStageArtifactGraph:
    """Canonical graph from exact Requirements and Design versions."""

    project_id: UUID
    requirements_reference: VersionedArtifactReference
    design_reference: VersionedArtifactReference | None
    nodes: tuple[ArtifactGraphNode, ...]
    links: tuple[ArtifactGraphLink, ...]

    def __post_init__(self) -> None:
        """Protect project scope, exact roots, canonical order, and referential integrity."""
        if self.requirements_reference.kind is not ArtifactKind.REQUIREMENTS_SPECIFICATION:
            raise ValueError("artifact graph requires an exact Requirements reference")

        if (
            self.design_reference is not None
            and self.design_reference.kind is not ArtifactKind.DESIGN_PACKAGE
        ):
            raise ValueError("artifact graph Design reference must identify a Design Package")

        if not self.nodes:
            raise ValueError("artifact graph requires nodes")

        references = tuple(node.reference for node in self.nodes)
        if len(references) != len(set(references)):
            raise ValueError("artifact graph node references must be unique")

        if self.nodes != tuple(sorted(self.nodes, key=lambda node: node.sort_key)):
            raise ValueError("artifact graph nodes must use canonical order")

        if len(self.links) != len(set(self.links)):
            raise ValueError("artifact graph links must be unique")

        if self.links != tuple(sorted(self.links, key=lambda link: link.sort_key)):
            raise ValueError("artifact graph links must use canonical order")

        reference_set = frozenset(references)
        for link in self.links:
            if link.source not in reference_set or link.target not in reference_set:
                raise ValueError("artifact graph links must reference existing nodes")

        for exact, kind in (
            (self.requirements_reference, ArtifactGraphNodeKind.REQUIREMENTS_SPECIFICATION),
            (self.design_reference, ArtifactGraphNodeKind.DESIGN_PACKAGE),
        ):
            if exact is None:
                continue
            expected = _versioned_reference(kind, exact)
            if expected not in reference_set:
                raise ValueError("artifact graph exact stage roots must be represented as nodes")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic exportable graph snapshot."""
        return {
            "schema_version": 1,
            "project_id": str(self.project_id),
            "requirements_reference": self.requirements_reference.to_snapshot(),
            "design_reference": (
                None if self.design_reference is None else self.design_reference.to_snapshot()
            ),
            "nodes": [node.to_snapshot() for node in self.nodes],
            "links": [link.to_snapshot() for link in self.links],
        }

    def canonical_json(self) -> str:
        """Serialize the graph deterministically for export and reproducibility."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the graph SHA-256 content hash."""
        return snapshot_content_hash(self.to_snapshot())


def _versioned_reference(
    kind: ArtifactGraphNodeKind,
    reference: VersionedArtifactReference | RequirementsContextReference,
) -> ArtifactGraphReference:
    """Convert an exact governed reference into a graph reference."""
    return ArtifactGraphReference(
        kind=kind,
        artifact_id=reference.artifact_id,
        version_number=reference.version_number,
        content_hash=reference.content_hash,
    )


def _plain_reference(kind: ArtifactGraphNodeKind, artifact_id: UUID) -> ArtifactGraphReference:
    """Create one stable non-versioned graph reference."""
    return ArtifactGraphReference(kind=kind, artifact_id=artifact_id)


def _twin_reference(twin) -> ArtifactGraphReference:
    return ArtifactGraphReference(
        kind=_Kind.USER_TWIN,
        artifact_id=twin.twin_id,
        version_number=twin.version_number,
        content_hash=twin.content_hash,
    )


def _node(
    *,
    reference: ArtifactGraphReference,
    stage: ArtifactGraphStage,
    display_code: str,
    title: str,
) -> ArtifactGraphNode:
    """Create one concise normalized graph node."""
    return ArtifactGraphNode(
        reference=reference,
        stage=stage,
        display_code=" ".join(display_code.split()),
        title=" ".join(title.split()),
    )


def _twin_node(reference: ArtifactGraphReference, name: str) -> ArtifactGraphNode:
    return _node(
        reference=reference,
        stage=ArtifactGraphStage.CONTEXT,
        display_code=f"UT-{reference.artifact_id.hex[:8].upper()}-v{reference.version_number}",
        title=name,
    )


def _link(
    kind: ArtifactGraphLinkKind,
    source: ArtifactGraphReference,
    target: ArtifactGraphReference,
) -> ArtifactGraphLink:
    """Create one concise graph relationship."""
    return ArtifactGraphLink(kind=kind, source=source, target=target)


def _links_to(links, kind, source, target_kind, ids) -> None:
    links.extend(_link(kind, source, _plain_reference(target_kind, value)) for value in ids)


def _links_from(links, kind, source_kind, ids, target) -> None:
    links.extend(_link(kind, _plain_reference(source_kind, value), target) for value in ids)


def _contained(nodes, links, parent, stage, kind, artifact, title) -> ArtifactGraphReference:
    reference = _plain_reference(kind, artifact.id)
    nodes.append(_node(reference=reference, stage=stage, display_code=artifact.code, title=title))
    links.append(_link(_Relation.CONTAINS, parent, reference))
    return reference


def _exact_requirements_reference(
    version: RequirementsSpecificationVersion,
) -> VersionedArtifactReference:
    """Return the exact Requirements version tuple used by later stages."""
    return VersionedArtifactReference(
        kind=ArtifactKind.REQUIREMENTS_SPECIFICATION,
        artifact_id=version.id,
        version_number=version.version_number,
        content_hash=version.content_hash,
    )


def _exact_design_reference(version: DesignPackageVersion) -> VersionedArtifactReference:
    """Return the exact Design Package version tuple used by Architecture."""
    return VersionedArtifactReference(
        kind=ArtifactKind.DESIGN_PACKAGE,
        artifact_id=version.id,
        version_number=version.version_number,
        content_hash=version.content_hash,
    )


def _add_context_roots(
    version, nodes, links
) -> tuple[ArtifactGraphReference, ArtifactGraphReference, ArtifactGraphReference]:
    specification = version.specification
    brief = specification.project_brief_reference
    team = specification.agent_team_reference
    user_modeling = specification.user_modeling_reference
    requirements_root = _versioned_reference(
        _Kind.REQUIREMENTS_SPECIFICATION, _exact_requirements_reference(version)
    )
    brief_root = _versioned_reference(_Kind.PROJECT_BRIEF, brief)
    team_root = _versioned_reference(_Kind.AGENT_TEAM, team)
    user_modeling_root = _versioned_reference(_Kind.USER_MODELING, user_modeling)
    nodes.extend(
        (
            _node(
                reference=brief_root,
                stage=ArtifactGraphStage.CONTEXT,
                display_code=f"BRIEF-v{brief.version_number}",
                title="Approved Project Brief",
            ),
            _node(
                reference=team_root,
                stage=ArtifactGraphStage.CONTEXT,
                display_code=f"TEAM-v{team.version_number}",
                title="Approved perspectives",
            ),
            _node(
                reference=user_modeling_root,
                stage=ArtifactGraphStage.CONTEXT,
                display_code=f"UM-v{user_modeling.version_number}",
                title="Approved User Modeling snapshot",
            ),
            _node(
                reference=requirements_root,
                stage=ArtifactGraphStage.REQUIREMENTS,
                display_code=f"REQSPEC-v{version.version_number}",
                title="Requirements Specification",
            ),
        )
    )
    links.extend(
        _link(_Relation.GROUNDED_IN, requirements_root, target)
        for target in (brief_root, team_root, user_modeling_root)
    )
    return requirements_root, team_root, user_modeling_root


def _add_requirement_stage(
    version: RequirementsSpecificationVersion,
    nodes: list[ArtifactGraphNode],
    links: list[ArtifactGraphLink],
) -> tuple[ArtifactGraphReference, ArtifactGraphReference, ArtifactGraphReference]:
    """Add exact context, Requirements artifacts, and internal traceability."""
    specification = version.specification
    roots = _add_context_roots(version, nodes, links)
    root, _, user_modeling_root = roots
    stage = ArtifactGraphStage.REQUIREMENTS

    for journey in specification.journeys:
        reference = _contained(nodes, links, root, stage, _Kind.JOURNEY, journey, journey.title)
        _links_from(links, _Relation.EXPANDS, _Kind.SCENARIO, (journey.scenario_id,), reference)
        need_ids = {value for phase in journey.phases for value in phase.need_ids}
        _links_to(links, _Relation.REVEALS, reference, _Kind.NEED, need_ids)

    for twin in specification.user_twin_references:
        reference = _twin_reference(twin)
        nodes.append(_twin_node(reference, twin.name))
        links.append(_link(_Relation.CONTAINS, user_modeling_root, reference))

    for requirement in specification.requirements:
        _contained(nodes, links, root, stage, _Kind.REQUIREMENT, requirement, requirement.title)

    if specification.schema_version == 2:
        for need in specification.needs:
            reference = _contained(nodes, links, root, stage, _Kind.NEED, need, need.title)
            _links_from(links, _Relation.REVEALS, _Kind.SCENARIO, need.scenario_ids, reference)
        for kind, artifacts in (
            (_Kind.REQUIREMENT, specification.requirements),
            (_Kind.USER_STORY, specification.user_stories),
        ):
            for artifact in artifacts:
                target = _plain_reference(kind, artifact.id)
                _links_from(links, _Relation.MOTIVATES, _Kind.NEED, artifact.need_ids, target)
        links.extend(
            _link(
                _Relation.PARTICIPATES_IN,
                _twin_reference(scenario.actor),
                _plain_reference(_Kind.SCENARIO, scenario.id),
            )
            for scenario in specification.scenarios
        )

    for story in specification.user_stories:
        twin_reference = _twin_reference(story.user_twin_reference)
        reference = _contained(nodes, links, root, stage, _Kind.USER_STORY, story, story.goal)
        links.append(_link(_Relation.ACTS_AS, twin_reference, reference))
        _links_to(links, _Relation.MOTIVATES, reference, _Kind.REQUIREMENT, story.requirement_ids)

    for criterion in specification.acceptance_criteria:
        reference = _contained(
            nodes, links, root, stage, _Kind.ACCEPTANCE_CRITERION, criterion, criterion.statement
        )
        for kind, ids in (
            (_Kind.REQUIREMENT, criterion.requirement_ids),
            (_Kind.USER_STORY, criterion.user_story_ids),
        ):
            _links_from(links, _Relation.VERIFIED_BY, kind, ids, reference)

    for scenario in specification.scenarios:
        reference = _contained(nodes, links, root, stage, _Kind.SCENARIO, scenario, scenario.title)
        for kind, ids in (
            (_Kind.REQUIREMENT, scenario.requirement_ids),
            (_Kind.ACCEPTANCE_CRITERION, scenario.acceptance_criterion_ids),
        ):
            _links_to(links, _Relation.EXERCISES, reference, kind, ids)

    for risk in specification.risks:
        reference = _contained(nodes, links, root, stage, _Kind.PROJECT_RISK, risk, risk.summary)
        _links_to(links, _Relation.AFFECTS, reference, _Kind.REQUIREMENT, risk.requirement_ids)

    for item in specification.definition_of_done:
        reference = _contained(
            nodes, links, root, stage, _Kind.DEFINITION_OF_DONE, item, item.statement
        )
        _links_to(links, _Relation.GOVERNS, reference, _Kind.REQUIREMENT, item.requirement_ids)

    return roots


def _add_trace_links(
    links: list[ArtifactGraphLink],
    source: ArtifactGraphReference,
    *,
    requirement_ids: tuple[UUID, ...] = (),
    user_story_ids: tuple[UUID, ...] = (),
    acceptance_criterion_ids: tuple[UUID, ...] = (),
) -> None:
    """Add deterministic links from a later artifact to Requirements-stage nodes."""
    for kind, ids in (
        (_Kind.REQUIREMENT, requirement_ids),
        (_Kind.USER_STORY, user_story_ids),
        (_Kind.ACCEPTANCE_CRITERION, acceptance_criterion_ids),
    ):
        _links_to(links, _Relation.TRACES_TO, source, kind, ids)


def _add_design_stage(
    version: DesignPackageVersion,
    *,
    requirements_root: ArtifactGraphReference,
    team_root: ArtifactGraphReference,
    user_modeling_root: ArtifactGraphReference,
    nodes: list[ArtifactGraphNode],
    links: list[ArtifactGraphLink],
) -> None:
    """Add one exact Design Package and all inspectable design artifacts."""
    package = version.package
    stage = ArtifactGraphStage.DESIGN
    root = _versioned_reference(_Kind.DESIGN_PACKAGE, _exact_design_reference(version))
    nodes.append(
        _node(
            reference=root,
            stage=stage,
            display_code=f"DESIGN-v{version.version_number}",
            title="Design Exploration Package",
        )
    )
    links.extend(
        _link(_Relation.GROUNDED_IN, root, target)
        for target in (requirements_root, team_root, user_modeling_root)
    )

    for alternative in package.alternatives:
        reference = _contained(
            nodes, links, root, stage, _Kind.DESIGN_ALTERNATIVE, alternative, alternative.title
        )
        _add_trace_links(
            links,
            reference,
            requirement_ids=alternative.requirement_ids,
            user_story_ids=alternative.user_story_ids,
            acceptance_criterion_ids=alternative.acceptance_criterion_ids,
        )
        links.extend(
            _link(_Relation.TRACES_TO, reference, _twin_reference(twin))
            for twin in alternative.user_twin_references
        )
        for workflow in alternative.workflows:
            workflow_reference = _contained(
                nodes, links, reference, stage, _Kind.DESIGN_WORKFLOW, workflow, workflow.title
            )
            _add_trace_links(
                links,
                workflow_reference,
                requirement_ids=workflow.requirement_ids,
                user_story_ids=workflow.user_story_ids,
            )

    for critique in package.critiques:
        title = f"Synthetic critique for {critique.user_twin_reference.name}"
        reference = _contained(
            nodes, links, root, stage, _Kind.SYNTHETIC_DESIGN_CRITIQUE, critique, title
        )
        critiqued = _plain_reference(_Kind.DESIGN_ALTERNATIVE, critique.design_alternative_id)
        links.append(_link(_Relation.CRITIQUES, reference, critiqued))
        twin = _twin_reference(critique.user_twin_reference)
        links.append(_link(_Relation.TRACES_TO, reference, twin))

    for concern in package.concerns:
        reference = _contained(
            nodes, links, root, stage, _Kind.DESIGN_CONCERN, concern, concern.summary
        )
        alternative_ids = concern.design_alternative_ids
        _links_to(links, _Relation.AFFECTS, reference, _Kind.DESIGN_ALTERNATIVE, alternative_ids)
        _add_trace_links(links, reference, requirement_ids=concern.requirement_ids)

    if package.prototype is not None:
        prototype = package.prototype
        reference = _contained(
            nodes, links, root, stage, _Kind.DECLARATIVE_PROTOTYPE, prototype, prototype.title
        )
        represented = _plain_reference(_Kind.DESIGN_ALTERNATIVE, prototype.design_alternative_id)
        links.append(_link(_Relation.REPRESENTS, reference, represented))
        for screen in prototype.screens:
            screen_reference = _contained(
                nodes, links, reference, stage, _Kind.PROTOTYPE_SCREEN, screen, screen.title
            )
            _add_trace_links(
                links,
                screen_reference,
                requirement_ids=screen.requirement_ids,
                user_story_ids=screen.user_story_ids,
                acceptance_criterion_ids=screen.acceptance_criterion_ids,
            )


def grounded_design(
    requirements: RequirementsSpecificationVersion,
    design: DesignPackageVersion | None,
) -> DesignPackageVersion | None:
    if (
        design is None
        or design.project_id != requirements.project_id
        or design.package.grounding.requirements_reference
        != _exact_requirements_reference(requirements)
    ):
        return None
    return design


def build_cross_stage_artifact_graph(
    requirements: RequirementsSpecificationVersion,
    design: DesignPackageVersion | None = None,
    *,
    research_evidence: Mapping[str, object] | None = None,
    evidence_twins: Sequence = (),
) -> CrossStageArtifactGraph:
    """Derive a deterministic graph without persisting duplicate relationship state."""
    requirements_exact = _exact_requirements_reference(requirements)
    design_exact = None if design is None else _exact_design_reference(design)

    if design is not None:
        if design.project_id != requirements.project_id:
            raise ValueError("Design and Requirements versions must belong to the same project")
        if design.package.grounding.requirements_reference != requirements_exact:
            raise ValueError("Design Package must reference the exact Requirements version")

    nodes: list[ArtifactGraphNode] = []
    links: list[ArtifactGraphLink] = []
    requirements_root, team_root, user_modeling_root = _add_requirement_stage(
        requirements,
        nodes,
        links,
    )
    if design is not None:
        _add_design_stage(
            design,
            requirements_root=requirements_root,
            team_root=team_root,
            user_modeling_root=user_modeling_root,
            nodes=nodes,
            links=links,
        )
    if research_evidence and research_evidence.get("evidence"):
        _add_evidence_stage(research_evidence, evidence_twins, nodes, links)

    return CrossStageArtifactGraph(
        project_id=requirements.project_id,
        requirements_reference=requirements_exact,
        design_reference=design_exact,
        nodes=tuple(sorted(nodes, key=lambda node: node.sort_key)),
        links=tuple(sorted(set(links), key=lambda link: link.sort_key)),
    )


def _add_evidence_stage(document, twins, nodes, links) -> None:
    sources = {}
    for source in document.get("evidence", ()):
        reference = ArtifactGraphReference(
            kind=_Kind.RESEARCH_EVIDENCE,
            artifact_id=UUID(source["id"]),
            version_number=source["version"],
            content_hash=source["content_hash"],
        )
        sources[(source["id"], source["version"], source["content_hash"])] = reference
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.CONTEXT,
                display_code=f"{source['code']}-v{source['version']}",
                title=f"{source['title']} ({source['status']})",
            )
        )
    profiles = {str(twin.twin_id): twin for twin in twins}
    for item in document.get("citations", ()):
        if item.get("status") != "ACTIVE":
            continue
        citation = item["citation"]
        source = sources.get(
            (citation["source_id"], citation["source_version"], citation["content_hash"])
        )
        twin = profiles.get(item["twin_id"])
        if source is None or twin is None:
            continue
        observation = next(
            (
                entry
                for entry in twin.profile.observations
                if entry.observation_key == f"user_twin.{item['field']}"
            ),
            None,
        )
        if observation is None or not any(
            entry.source_id == citation["source_id"]
            and entry.source_version == citation["source_version"]
            and entry.content_hash == citation["content_hash"]
            for entry in observation.provenance.references
        ):
            continue
        target = _twin_reference(twin)
        if not any(node.reference == target for node in nodes):
            nodes.append(_twin_node(target, twin.profile.name))
        links.append(_link(_Relation(item["effect"]), source, target))


__all__ = [
    "ArtifactGraphLink",
    "ArtifactGraphLinkKind",
    "ArtifactGraphNode",
    "ArtifactGraphNodeKind",
    "ArtifactGraphReference",
    "ArtifactGraphStage",
    "CrossStageArtifactGraph",
    "build_cross_stage_artifact_graph",
    "grounded_design",
]
