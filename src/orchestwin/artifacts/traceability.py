"""Cross-stage artifact traceability derived from immutable project artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from orchestwin.artifacts.architecture_packages import ArchitecturePackageVersion
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.references import ArtifactKind, VersionedArtifactReference
from orchestwin.projects.requirements_primitives import (
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
    ARCHITECTURE = "ARCHITECTURE"
    TESTING = "TESTING"


class ArtifactGraphNodeKind(StrEnum):
    """Kinds of immutable or derived artifacts represented as graph nodes."""

    PROJECT_BRIEF = "PROJECT_BRIEF"
    AGENT_TEAM = "AGENT_TEAM"
    USER_MODELING = "USER_MODELING"
    USER_TWIN = "USER_TWIN"
    REQUIREMENTS_SPECIFICATION = "REQUIREMENTS_SPECIFICATION"
    REQUIREMENT = "REQUIREMENT"
    USER_STORY = "USER_STORY"
    ACCEPTANCE_CRITERION = "ACCEPTANCE_CRITERION"
    SCENARIO = "SCENARIO"
    PROJECT_RISK = "PROJECT_RISK"
    DEFINITION_OF_DONE = "DEFINITION_OF_DONE"
    DESIGN_PACKAGE = "DESIGN_PACKAGE"
    DESIGN_ALTERNATIVE = "DESIGN_ALTERNATIVE"
    DESIGN_WORKFLOW = "DESIGN_WORKFLOW"
    SYNTHETIC_DESIGN_CRITIQUE = "SYNTHETIC_DESIGN_CRITIQUE"
    DESIGN_CONCERN = "DESIGN_CONCERN"
    DECLARATIVE_PROTOTYPE = "DECLARATIVE_PROTOTYPE"
    PROTOTYPE_SCREEN = "PROTOTYPE_SCREEN"
    ARCHITECTURE_PACKAGE = "ARCHITECTURE_PACKAGE"
    SOFTWARE_ARCHITECTURE = "SOFTWARE_ARCHITECTURE"
    ARCHITECTURE_COMPONENT = "ARCHITECTURE_COMPONENT"
    ARCHITECTURE_CONNECTION = "ARCHITECTURE_CONNECTION"
    ARCHITECTURE_DECISION = "ARCHITECTURE_DECISION"
    ARCHITECTURE_DATA_ENTITY = "ARCHITECTURE_DATA_ENTITY"
    ARCHITECTURE_API_OPERATION = "ARCHITECTURE_API_OPERATION"
    ARCHITECTURE_RISK = "ARCHITECTURE_RISK"
    TEST_PLAN = "TEST_PLAN"
    TEST_ENVIRONMENT = "TEST_ENVIRONMENT"
    TEST_CASE = "TEST_CASE"
    QUALITY_GATE = "QUALITY_GATE"


class ArtifactGraphLinkKind(StrEnum):
    """Semantic relationships preserved across workflow stages."""

    CONTAINS = "CONTAINS"
    GROUNDED_IN = "GROUNDED_IN"
    ACTS_AS = "ACTS_AS"
    MOTIVATES = "MOTIVATES"
    VERIFIED_BY = "VERIFIED_BY"
    EXERCISES = "EXERCISES"
    AFFECTS = "AFFECTS"
    GOVERNS = "GOVERNS"
    TRACES_TO = "TRACES_TO"
    REPRESENTS = "REPRESENTS"
    CRITIQUES = "CRITIQUES"
    REALIZES = "REALIZES"
    CONNECTS = "CONNECTS"
    OWNED_BY = "OWNED_BY"
    TESTS = "TESTS"
    EXECUTES_IN = "EXECUTES_IN"


_STAGE_ORDER = {
    ArtifactGraphStage.CONTEXT: 0,
    ArtifactGraphStage.REQUIREMENTS: 1,
    ArtifactGraphStage.DESIGN: 2,
    ArtifactGraphStage.ARCHITECTURE: 3,
    ArtifactGraphStage.TESTING: 4,
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
    """Canonical graph from exact Requirements, Design, and Architecture versions."""

    project_id: UUID
    requirements_reference: VersionedArtifactReference
    design_reference: VersionedArtifactReference | None
    architecture_reference: VersionedArtifactReference | None
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

        if self.architecture_reference is not None:
            if self.design_reference is None:
                raise ValueError("artifact graph Architecture requires a Design reference")
            if self.architecture_reference.kind is not ArtifactKind.ARCHITECTURE_PACKAGE:
                raise ValueError(
                    "artifact graph Architecture reference must identify an Architecture Package"
                )

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
            (self.architecture_reference, ArtifactGraphNodeKind.ARCHITECTURE_PACKAGE),
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
            "architecture_reference": (
                None
                if self.architecture_reference is None
                else self.architecture_reference.to_snapshot()
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
    reference: VersionedArtifactReference,
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


def _link(
    kind: ArtifactGraphLinkKind,
    source: ArtifactGraphReference,
    target: ArtifactGraphReference,
) -> ArtifactGraphLink:
    """Create one concise graph relationship."""
    return ArtifactGraphLink(kind=kind, source=source, target=target)


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


def _context_reference(
    kind: ArtifactGraphNodeKind,
    artifact_id: UUID,
    version_number: int,
    content_hash: str,
) -> ArtifactGraphReference:
    """Create one exact graph reference from Requirements context metadata."""
    return ArtifactGraphReference(
        kind=kind,
        artifact_id=artifact_id,
        version_number=version_number,
        content_hash=content_hash,
    )


def _add_requirement_stage(
    version: RequirementsSpecificationVersion,
    nodes: list[ArtifactGraphNode],
    links: list[ArtifactGraphLink],
) -> tuple[ArtifactGraphReference, ArtifactGraphReference, ArtifactGraphReference]:
    """Add exact context, Requirements artifacts, and internal traceability."""
    specification = version.specification
    requirements_exact = _exact_requirements_reference(version)
    requirements_root = _versioned_reference(
        ArtifactGraphNodeKind.REQUIREMENTS_SPECIFICATION,
        requirements_exact,
    )
    brief = specification.project_brief_reference
    team = specification.agent_team_reference
    user_modeling = specification.user_modeling_reference
    brief_root = _context_reference(
        ArtifactGraphNodeKind.PROJECT_BRIEF,
        brief.artifact_id,
        brief.version_number,
        brief.content_hash,
    )
    team_root = _context_reference(
        ArtifactGraphNodeKind.AGENT_TEAM,
        team.artifact_id,
        team.version_number,
        team.content_hash,
    )
    user_modeling_root = _context_reference(
        ArtifactGraphNodeKind.USER_MODELING,
        user_modeling.artifact_id,
        user_modeling.version_number,
        user_modeling.content_hash,
    )
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
                title="Approved Agent Team",
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
        _link(ArtifactGraphLinkKind.GROUNDED_IN, requirements_root, target)
        for target in (brief_root, team_root, user_modeling_root)
    )

    for twin in specification.user_twin_references:
        twin_reference = ArtifactGraphReference(
            kind=ArtifactGraphNodeKind.USER_TWIN,
            artifact_id=twin.twin_id,
            version_number=twin.version_number,
            content_hash=twin.content_hash,
        )
        nodes.append(
            _node(
                reference=twin_reference,
                stage=ArtifactGraphStage.CONTEXT,
                display_code=f"UT-{twin.twin_id.hex[:8].upper()}-v{twin.version_number}",
                title=twin.name,
            )
        )
        links.append(_link(ArtifactGraphLinkKind.CONTAINS, user_modeling_root, twin_reference))

    for requirement in specification.requirements:
        reference = _plain_reference(ArtifactGraphNodeKind.REQUIREMENT, requirement.id)
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.REQUIREMENTS,
                display_code=requirement.code,
                title=requirement.title,
            )
        )
        links.append(_link(ArtifactGraphLinkKind.CONTAINS, requirements_root, reference))

    for story in specification.user_stories:
        reference = _plain_reference(ArtifactGraphNodeKind.USER_STORY, story.id)
        twin_reference = ArtifactGraphReference(
            kind=ArtifactGraphNodeKind.USER_TWIN,
            artifact_id=story.user_twin_reference.twin_id,
            version_number=story.user_twin_reference.version_number,
            content_hash=story.user_twin_reference.content_hash,
        )
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.REQUIREMENTS,
                display_code=story.code,
                title=story.goal,
            )
        )
        links.extend(
            (
                _link(ArtifactGraphLinkKind.CONTAINS, requirements_root, reference),
                _link(ArtifactGraphLinkKind.ACTS_AS, twin_reference, reference),
            )
        )
        links.extend(
            _link(
                ArtifactGraphLinkKind.MOTIVATES,
                reference,
                _plain_reference(ArtifactGraphNodeKind.REQUIREMENT, requirement_id),
            )
            for requirement_id in story.requirement_ids
        )

    for criterion in specification.acceptance_criteria:
        reference = _plain_reference(ArtifactGraphNodeKind.ACCEPTANCE_CRITERION, criterion.id)
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.REQUIREMENTS,
                display_code=criterion.code,
                title=criterion.statement,
            )
        )
        links.append(_link(ArtifactGraphLinkKind.CONTAINS, requirements_root, reference))
        links.extend(
            _link(
                ArtifactGraphLinkKind.VERIFIED_BY,
                _plain_reference(ArtifactGraphNodeKind.REQUIREMENT, requirement_id),
                reference,
            )
            for requirement_id in criterion.requirement_ids
        )
        links.extend(
            _link(
                ArtifactGraphLinkKind.VERIFIED_BY,
                _plain_reference(ArtifactGraphNodeKind.USER_STORY, story_id),
                reference,
            )
            for story_id in criterion.user_story_ids
        )

    for scenario in specification.scenarios:
        reference = _plain_reference(ArtifactGraphNodeKind.SCENARIO, scenario.id)
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.REQUIREMENTS,
                display_code=scenario.code,
                title=scenario.title,
            )
        )
        links.append(_link(ArtifactGraphLinkKind.CONTAINS, requirements_root, reference))
        links.extend(
            _link(
                ArtifactGraphLinkKind.EXERCISES,
                reference,
                _plain_reference(ArtifactGraphNodeKind.REQUIREMENT, requirement_id),
            )
            for requirement_id in scenario.requirement_ids
        )
        links.extend(
            _link(
                ArtifactGraphLinkKind.EXERCISES,
                reference,
                _plain_reference(ArtifactGraphNodeKind.ACCEPTANCE_CRITERION, criterion_id),
            )
            for criterion_id in scenario.acceptance_criterion_ids
        )

    for risk in specification.risks:
        reference = _plain_reference(ArtifactGraphNodeKind.PROJECT_RISK, risk.id)
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.REQUIREMENTS,
                display_code=risk.code,
                title=risk.summary,
            )
        )
        links.append(_link(ArtifactGraphLinkKind.CONTAINS, requirements_root, reference))
        links.extend(
            _link(
                ArtifactGraphLinkKind.AFFECTS,
                reference,
                _plain_reference(ArtifactGraphNodeKind.REQUIREMENT, requirement_id),
            )
            for requirement_id in risk.requirement_ids
        )

    for item in specification.definition_of_done:
        reference = _plain_reference(ArtifactGraphNodeKind.DEFINITION_OF_DONE, item.id)
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.REQUIREMENTS,
                display_code=item.code,
                title=item.statement,
            )
        )
        links.append(_link(ArtifactGraphLinkKind.CONTAINS, requirements_root, reference))
        links.extend(
            _link(
                ArtifactGraphLinkKind.GOVERNS,
                reference,
                _plain_reference(ArtifactGraphNodeKind.REQUIREMENT, requirement_id),
            )
            for requirement_id in item.requirement_ids
        )

    return requirements_root, team_root, user_modeling_root


def _add_trace_links(
    links: list[ArtifactGraphLink],
    source: ArtifactGraphReference,
    *,
    requirement_ids: tuple[UUID, ...] = (),
    user_story_ids: tuple[UUID, ...] = (),
    acceptance_criterion_ids: tuple[UUID, ...] = (),
) -> None:
    """Add deterministic links from a later artifact to Requirements-stage nodes."""
    links.extend(
        _link(
            ArtifactGraphLinkKind.TRACES_TO,
            source,
            _plain_reference(ArtifactGraphNodeKind.REQUIREMENT, value),
        )
        for value in requirement_ids
    )
    links.extend(
        _link(
            ArtifactGraphLinkKind.TRACES_TO,
            source,
            _plain_reference(ArtifactGraphNodeKind.USER_STORY, value),
        )
        for value in user_story_ids
    )
    links.extend(
        _link(
            ArtifactGraphLinkKind.TRACES_TO,
            source,
            _plain_reference(ArtifactGraphNodeKind.ACCEPTANCE_CRITERION, value),
        )
        for value in acceptance_criterion_ids
    )


def _add_design_stage(
    version: DesignPackageVersion,
    *,
    requirements_root: ArtifactGraphReference,
    team_root: ArtifactGraphReference,
    user_modeling_root: ArtifactGraphReference,
    nodes: list[ArtifactGraphNode],
    links: list[ArtifactGraphLink],
) -> ArtifactGraphReference:
    """Add one exact Design Package and all inspectable design artifacts."""
    package = version.package
    exact = _exact_design_reference(version)
    root = _versioned_reference(ArtifactGraphNodeKind.DESIGN_PACKAGE, exact)
    nodes.append(
        _node(
            reference=root,
            stage=ArtifactGraphStage.DESIGN,
            display_code=f"DESIGN-v{version.version_number}",
            title="Design Exploration Package",
        )
    )
    links.extend(
        _link(ArtifactGraphLinkKind.GROUNDED_IN, root, target)
        for target in (requirements_root, team_root, user_modeling_root)
    )

    for alternative in package.alternatives:
        reference = _plain_reference(ArtifactGraphNodeKind.DESIGN_ALTERNATIVE, alternative.id)
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.DESIGN,
                display_code=alternative.code,
                title=alternative.title,
            )
        )
        links.append(_link(ArtifactGraphLinkKind.CONTAINS, root, reference))
        _add_trace_links(
            links,
            reference,
            requirement_ids=alternative.requirement_ids,
            user_story_ids=alternative.user_story_ids,
            acceptance_criterion_ids=alternative.acceptance_criterion_ids,
        )
        for twin in alternative.user_twin_references:
            links.append(
                _link(
                    ArtifactGraphLinkKind.TRACES_TO,
                    reference,
                    ArtifactGraphReference(
                        kind=ArtifactGraphNodeKind.USER_TWIN,
                        artifact_id=twin.twin_id,
                        version_number=twin.version_number,
                        content_hash=twin.content_hash,
                    ),
                )
            )

        for workflow in alternative.workflows:
            workflow_reference = _plain_reference(
                ArtifactGraphNodeKind.DESIGN_WORKFLOW,
                workflow.id,
            )
            nodes.append(
                _node(
                    reference=workflow_reference,
                    stage=ArtifactGraphStage.DESIGN,
                    display_code=workflow.code,
                    title=workflow.title,
                )
            )
            links.append(_link(ArtifactGraphLinkKind.CONTAINS, reference, workflow_reference))
            _add_trace_links(
                links,
                workflow_reference,
                requirement_ids=workflow.requirement_ids,
                user_story_ids=workflow.user_story_ids,
            )

    for critique in package.critiques:
        reference = _plain_reference(
            ArtifactGraphNodeKind.SYNTHETIC_DESIGN_CRITIQUE,
            critique.id,
        )
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.DESIGN,
                display_code=critique.code,
                title=f"Synthetic critique for {critique.user_twin_reference.name}",
            )
        )
        links.extend(
            (
                _link(ArtifactGraphLinkKind.CONTAINS, root, reference),
                _link(
                    ArtifactGraphLinkKind.CRITIQUES,
                    reference,
                    _plain_reference(
                        ArtifactGraphNodeKind.DESIGN_ALTERNATIVE,
                        critique.design_alternative_id,
                    ),
                ),
                _link(
                    ArtifactGraphLinkKind.TRACES_TO,
                    reference,
                    ArtifactGraphReference(
                        kind=ArtifactGraphNodeKind.USER_TWIN,
                        artifact_id=critique.user_twin_reference.twin_id,
                        version_number=critique.user_twin_reference.version_number,
                        content_hash=critique.user_twin_reference.content_hash,
                    ),
                ),
            )
        )

    for concern in package.concerns:
        reference = _plain_reference(ArtifactGraphNodeKind.DESIGN_CONCERN, concern.id)
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.DESIGN,
                display_code=concern.code,
                title=concern.summary,
            )
        )
        links.append(_link(ArtifactGraphLinkKind.CONTAINS, root, reference))
        links.extend(
            _link(
                ArtifactGraphLinkKind.AFFECTS,
                reference,
                _plain_reference(ArtifactGraphNodeKind.DESIGN_ALTERNATIVE, value),
            )
            for value in concern.design_alternative_ids
        )
        _add_trace_links(links, reference, requirement_ids=concern.requirement_ids)

    if package.prototype is not None:
        prototype = package.prototype
        prototype_reference = _plain_reference(
            ArtifactGraphNodeKind.DECLARATIVE_PROTOTYPE,
            prototype.id,
        )
        nodes.append(
            _node(
                reference=prototype_reference,
                stage=ArtifactGraphStage.DESIGN,
                display_code=prototype.code,
                title=prototype.title,
            )
        )
        links.extend(
            (
                _link(ArtifactGraphLinkKind.CONTAINS, root, prototype_reference),
                _link(
                    ArtifactGraphLinkKind.REPRESENTS,
                    prototype_reference,
                    _plain_reference(
                        ArtifactGraphNodeKind.DESIGN_ALTERNATIVE,
                        prototype.design_alternative_id,
                    ),
                ),
            )
        )
        for screen in prototype.screens:
            screen_reference = _plain_reference(
                ArtifactGraphNodeKind.PROTOTYPE_SCREEN,
                screen.id,
            )
            nodes.append(
                _node(
                    reference=screen_reference,
                    stage=ArtifactGraphStage.DESIGN,
                    display_code=screen.code,
                    title=screen.title,
                )
            )
            links.append(
                _link(ArtifactGraphLinkKind.CONTAINS, prototype_reference, screen_reference)
            )
            _add_trace_links(
                links,
                screen_reference,
                requirement_ids=screen.requirement_ids,
                user_story_ids=screen.user_story_ids,
                acceptance_criterion_ids=screen.acceptance_criterion_ids,
            )

    return root


def _add_architecture_stage(
    version: ArchitecturePackageVersion,
    *,
    design_root: ArtifactGraphReference,
    requirements_root: ArtifactGraphReference,
    team_root: ArtifactGraphReference,
    user_modeling_root: ArtifactGraphReference,
    nodes: list[ArtifactGraphNode],
    links: list[ArtifactGraphLink],
) -> ArtifactGraphReference:
    """Add one exact Architecture Package, architecture model, and test plan."""
    package = version.package
    exact = version.reference
    root = _versioned_reference(ArtifactGraphNodeKind.ARCHITECTURE_PACKAGE, exact)
    nodes.append(
        _node(
            reference=root,
            stage=ArtifactGraphStage.ARCHITECTURE,
            display_code=f"ARCH-v{version.version_number}",
            title="Architecture and Test Plan Package",
        )
    )
    links.extend(
        _link(ArtifactGraphLinkKind.GROUNDED_IN, root, target)
        for target in (design_root, requirements_root, team_root, user_modeling_root)
    )

    architecture = package.architecture
    architecture_reference = _plain_reference(
        ArtifactGraphNodeKind.SOFTWARE_ARCHITECTURE,
        architecture.id,
    )
    nodes.append(
        _node(
            reference=architecture_reference,
            stage=ArtifactGraphStage.ARCHITECTURE,
            display_code=architecture.code,
            title=architecture.title,
        )
    )
    links.extend(
        (
            _link(ArtifactGraphLinkKind.CONTAINS, root, architecture_reference),
            _link(
                ArtifactGraphLinkKind.REALIZES,
                architecture_reference,
                _plain_reference(
                    ArtifactGraphNodeKind.DESIGN_ALTERNATIVE,
                    architecture.selected_design_alternative_id,
                ),
            ),
            _link(
                ArtifactGraphLinkKind.REALIZES,
                architecture_reference,
                _plain_reference(
                    ArtifactGraphNodeKind.DECLARATIVE_PROTOTYPE,
                    architecture.prototype_id,
                ),
            ),
        )
    )
    _add_trace_links(
        links,
        architecture_reference,
        requirement_ids=architecture.requirement_ids,
        acceptance_criterion_ids=architecture.acceptance_criterion_ids,
    )

    for component in architecture.components:
        reference = _plain_reference(ArtifactGraphNodeKind.ARCHITECTURE_COMPONENT, component.id)
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.ARCHITECTURE,
                display_code=component.code,
                title=component.name,
            )
        )
        links.append(_link(ArtifactGraphLinkKind.CONTAINS, architecture_reference, reference))
        _add_trace_links(links, reference, requirement_ids=component.requirement_ids)

    for connection in architecture.connections:
        reference = _plain_reference(
            ArtifactGraphNodeKind.ARCHITECTURE_CONNECTION,
            connection.id,
        )
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.ARCHITECTURE,
                display_code=connection.code,
                title=connection.description,
            )
        )
        links.extend(
            (
                _link(ArtifactGraphLinkKind.CONTAINS, architecture_reference, reference),
                _link(
                    ArtifactGraphLinkKind.CONNECTS,
                    reference,
                    _plain_reference(
                        ArtifactGraphNodeKind.ARCHITECTURE_COMPONENT,
                        connection.source_component_id,
                    ),
                ),
                _link(
                    ArtifactGraphLinkKind.CONNECTS,
                    reference,
                    _plain_reference(
                        ArtifactGraphNodeKind.ARCHITECTURE_COMPONENT,
                        connection.target_component_id,
                    ),
                ),
            )
        )
        _add_trace_links(links, reference, requirement_ids=connection.requirement_ids)

    for decision in architecture.decisions:
        reference = _plain_reference(ArtifactGraphNodeKind.ARCHITECTURE_DECISION, decision.id)
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.ARCHITECTURE,
                display_code=decision.code,
                title=decision.title,
            )
        )
        links.append(_link(ArtifactGraphLinkKind.CONTAINS, architecture_reference, reference))
        _add_trace_links(links, reference, requirement_ids=decision.requirement_ids)

    for entity in architecture.data_entities:
        reference = _plain_reference(
            ArtifactGraphNodeKind.ARCHITECTURE_DATA_ENTITY,
            entity.id,
        )
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.ARCHITECTURE,
                display_code=entity.code,
                title=entity.name,
            )
        )
        links.extend(
            (
                _link(ArtifactGraphLinkKind.CONTAINS, architecture_reference, reference),
                _link(
                    ArtifactGraphLinkKind.OWNED_BY,
                    reference,
                    _plain_reference(
                        ArtifactGraphNodeKind.ARCHITECTURE_COMPONENT,
                        entity.owning_component_id,
                    ),
                ),
            )
        )
        _add_trace_links(links, reference, requirement_ids=entity.requirement_ids)

    for operation in architecture.api_operations:
        reference = _plain_reference(
            ArtifactGraphNodeKind.ARCHITECTURE_API_OPERATION,
            operation.id,
        )
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.ARCHITECTURE,
                display_code=operation.code,
                title=f"{operation.method.value} {operation.path} — {operation.summary}",
            )
        )
        links.extend(
            (
                _link(ArtifactGraphLinkKind.CONTAINS, architecture_reference, reference),
                _link(
                    ArtifactGraphLinkKind.OWNED_BY,
                    reference,
                    _plain_reference(
                        ArtifactGraphNodeKind.ARCHITECTURE_COMPONENT,
                        operation.owning_component_id,
                    ),
                ),
            )
        )
        _add_trace_links(
            links,
            reference,
            requirement_ids=operation.requirement_ids,
            acceptance_criterion_ids=operation.acceptance_criterion_ids,
        )

    for risk in architecture.risks:
        reference = _plain_reference(ArtifactGraphNodeKind.ARCHITECTURE_RISK, risk.id)
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.ARCHITECTURE,
                display_code=risk.code,
                title=risk.summary,
            )
        )
        links.append(_link(ArtifactGraphLinkKind.CONTAINS, architecture_reference, reference))
        links.extend(
            _link(
                ArtifactGraphLinkKind.AFFECTS,
                reference,
                _plain_reference(ArtifactGraphNodeKind.ARCHITECTURE_COMPONENT, value),
            )
            for value in risk.component_ids
        )
        _add_trace_links(links, reference, requirement_ids=risk.requirement_ids)

    test_plan = package.test_plan
    test_plan_reference = _plain_reference(ArtifactGraphNodeKind.TEST_PLAN, test_plan.id)
    nodes.append(
        _node(
            reference=test_plan_reference,
            stage=ArtifactGraphStage.TESTING,
            display_code=test_plan.code,
            title=test_plan.title,
        )
    )
    links.extend(
        (
            _link(ArtifactGraphLinkKind.CONTAINS, root, test_plan_reference),
            _link(ArtifactGraphLinkKind.TESTS, test_plan_reference, architecture_reference),
            _link(
                ArtifactGraphLinkKind.TESTS,
                test_plan_reference,
                _plain_reference(
                    ArtifactGraphNodeKind.DESIGN_ALTERNATIVE,
                    test_plan.selected_design_alternative_id,
                ),
            ),
        )
    )
    _add_trace_links(
        links,
        test_plan_reference,
        requirement_ids=test_plan.requirement_ids,
        acceptance_criterion_ids=test_plan.acceptance_criterion_ids,
    )
    links.extend(
        _link(
            ArtifactGraphLinkKind.TESTS,
            test_plan_reference,
            _plain_reference(ArtifactGraphNodeKind.ARCHITECTURE_COMPONENT, value),
        )
        for value in test_plan.architecture_component_ids
    )

    for environment in test_plan.environments:
        reference = _plain_reference(ArtifactGraphNodeKind.TEST_ENVIRONMENT, environment.id)
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.TESTING,
                display_code=environment.code,
                title=environment.name,
            )
        )
        links.append(_link(ArtifactGraphLinkKind.CONTAINS, test_plan_reference, reference))

    for test_case in test_plan.test_cases:
        reference = _plain_reference(ArtifactGraphNodeKind.TEST_CASE, test_case.id)
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.TESTING,
                display_code=test_case.code,
                title=test_case.title,
            )
        )
        links.append(_link(ArtifactGraphLinkKind.CONTAINS, test_plan_reference, reference))
        links.extend(
            _link(
                ArtifactGraphLinkKind.TESTS,
                reference,
                _plain_reference(ArtifactGraphNodeKind.REQUIREMENT, value),
            )
            for value in test_case.requirement_ids
        )
        links.extend(
            _link(
                ArtifactGraphLinkKind.TESTS,
                reference,
                _plain_reference(ArtifactGraphNodeKind.ACCEPTANCE_CRITERION, value),
            )
            for value in test_case.acceptance_criterion_ids
        )
        links.extend(
            _link(
                ArtifactGraphLinkKind.TESTS,
                reference,
                _plain_reference(ArtifactGraphNodeKind.ARCHITECTURE_COMPONENT, value),
            )
            for value in test_case.architecture_component_ids
        )
        links.extend(
            _link(
                ArtifactGraphLinkKind.TESTS,
                reference,
                _plain_reference(ArtifactGraphNodeKind.DESIGN_ALTERNATIVE, value),
            )
            for value in test_case.design_alternative_ids
        )
        links.extend(
            _link(
                ArtifactGraphLinkKind.EXECUTES_IN,
                reference,
                _plain_reference(ArtifactGraphNodeKind.TEST_ENVIRONMENT, value),
            )
            for value in test_case.environment_ids
        )

    for quality_gate in test_plan.quality_gates:
        reference = _plain_reference(ArtifactGraphNodeKind.QUALITY_GATE, quality_gate.id)
        nodes.append(
            _node(
                reference=reference,
                stage=ArtifactGraphStage.TESTING,
                display_code=quality_gate.code,
                title=quality_gate.title,
            )
        )
        links.append(_link(ArtifactGraphLinkKind.CONTAINS, test_plan_reference, reference))
        links.extend(
            _link(
                ArtifactGraphLinkKind.GOVERNS,
                reference,
                _plain_reference(ArtifactGraphNodeKind.TEST_CASE, value),
            )
            for value in quality_gate.required_test_case_ids
        )

    return root


def build_cross_stage_artifact_graph(
    requirements: RequirementsSpecificationVersion,
    design: DesignPackageVersion | None = None,
    architecture: ArchitecturePackageVersion | None = None,
) -> CrossStageArtifactGraph:
    """Derive a deterministic graph without persisting duplicate relationship state."""
    requirements_exact = _exact_requirements_reference(requirements)
    design_exact = None if design is None else _exact_design_reference(design)
    architecture_exact = None if architecture is None else architecture.reference

    if design is not None:
        if design.project_id != requirements.project_id:
            raise ValueError("Design and Requirements versions must belong to the same project")
        if design.package.grounding.requirements_reference != requirements_exact:
            raise ValueError("Design Package must reference the exact Requirements version")

    if architecture is not None:
        if design is None:
            raise ValueError("Architecture traceability requires the exact Design version")
        if architecture.project_id != requirements.project_id:
            raise ValueError("Architecture and Requirements must belong to the same project")
        if architecture.package.grounding.design_package_reference != design_exact:
            raise ValueError("Architecture Package must reference the exact Design version")
        if architecture.package.grounding.requirements_reference != requirements_exact:
            raise ValueError("Architecture Package must reference the exact Requirements version")

    nodes: list[ArtifactGraphNode] = []
    links: list[ArtifactGraphLink] = []
    requirements_root, team_root, user_modeling_root = _add_requirement_stage(
        requirements,
        nodes,
        links,
    )
    design_root: ArtifactGraphReference | None = None

    if design is not None:
        design_root = _add_design_stage(
            design,
            requirements_root=requirements_root,
            team_root=team_root,
            user_modeling_root=user_modeling_root,
            nodes=nodes,
            links=links,
        )

    if architecture is not None:
        if design_root is None:
            raise ValueError("Architecture traceability requires a Design graph root")
        _add_architecture_stage(
            architecture,
            design_root=design_root,
            requirements_root=requirements_root,
            team_root=team_root,
            user_modeling_root=user_modeling_root,
            nodes=nodes,
            links=links,
        )

    return CrossStageArtifactGraph(
        project_id=requirements.project_id,
        requirements_reference=requirements_exact,
        design_reference=design_exact,
        architecture_reference=architecture_exact,
        nodes=tuple(sorted(nodes, key=lambda node: node.sort_key)),
        links=tuple(sorted(set(links), key=lambda link: link.sort_key)),
    )


__all__ = [
    "ArtifactGraphLink",
    "ArtifactGraphLinkKind",
    "ArtifactGraphNode",
    "ArtifactGraphNodeKind",
    "ArtifactGraphReference",
    "ArtifactGraphStage",
    "CrossStageArtifactGraph",
    "build_cross_stage_artifact_graph",
]
