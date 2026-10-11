from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Final

from pydantic import ValidationError
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue
from pydantic_core import core_schema

from orchestwin.agents.catalog import AgentIdentifier as AgentIdentifier
from orchestwin.agents.proposals import TeamProposalRevisionKind as TeamProposalRevisionKind
from orchestwin.agents.selection_rules import TeamRoleConstraintKind as TeamRoleConstraintKind
from orchestwin.agents.selection_rules import TeamSelectionIssueCode as TeamSelectionIssueCode
from orchestwin.agents.selection_rules import TeamSelectionReasonCode as TeamSelectionReasonCode
from orchestwin.artifacts.design import DesignApproach as DesignApproach
from orchestwin.artifacts.design import DesignCritiqueKind as DesignCritiqueKind
from orchestwin.artifacts.design_discussion import (
    DiscussionProposalTarget as DiscussionProposalTarget,
)
from orchestwin.artifacts.design_discussion import DiscussionStance as DiscussionStance
from orchestwin.artifacts.design_discussion import DiscussionStatus as DiscussionStatus
from orchestwin.artifacts.design_discussion import ReactionVerdict as ReactionVerdict
from orchestwin.artifacts.design_finding_validations import FindingDecision as FindingDecision
from orchestwin.artifacts.prototypes import PrototypeElementKind as PrototypeElementKind
from orchestwin.artifacts.prototypes import PrototypeScreenState as PrototypeScreenState
from orchestwin.artifacts.prototypes import PrototypeViewport as PrototypeViewport
from orchestwin.artifacts.references import ArtifactKind as ArtifactKind
from orchestwin.artifacts.visual_directions import DirectionColour as DirectionColour
from orchestwin.artifacts.visual_directions import DirectionDensity as DirectionDensity
from orchestwin.artifacts.visual_directions import DirectionLayout as DirectionLayout
from orchestwin.artifacts.visual_directions import DirectionShape as DirectionShape
from orchestwin.artifacts.visual_directions import DirectionType as DirectionType
from orchestwin.evaluation.artifacts import EvaluationArtifactModality as EvaluationArtifactModality
from orchestwin.evaluation.findings import SyntheticFindingCriterion as SyntheticFindingCriterion
from orchestwin.evaluation.findings import (
    SyntheticFindingEpistemicStatus as SyntheticFindingEpistemicStatus,
)
from orchestwin.evaluation.findings import SyntheticFindingSeverity as SyntheticFindingSeverity
from orchestwin.knowledge.diagrams import DiagramKind as DiagramKind
from orchestwin.knowledge.layout import (
    FEEDBACK_CHANGES,
    FEEDBACK_DISCUSSIONS,
    FEEDBACK_FOLDER,
    FEEDBACK_INSIGHTS,
    FEEDBACK_LEARNING,
    FEEDBACK_REVIEWS,
    FEEDBACK_TESTS,
    KNOWLEDGE_MANIFEST,
    KNOWLEDGE_SCHEMA_VERSION,
    STAGES,
    STATE_DOCUMENT,
    TWIN_FOLDER,
    schema_document,
    stage_document,
    twin_document,
)
from orchestwin.knowledge.research_evidence import EVIDENCE_DOCUMENT
from orchestwin.knowledge.schema_models.acceptance import TestReviewsDocument
from orchestwin.knowledge.schema_models.development import ChangeReviewsDocument, StateDocument
from orchestwin.knowledge.schema_models.discussions import DiscussionsDocument
from orchestwin.knowledge.schema_models.evidence import ResearchEvidenceDocument
from orchestwin.knowledge.schema_models.insights import InsightsDocument
from orchestwin.knowledge.schema_models.learning import TwinLearningDocument
from orchestwin.knowledge.schema_models.manifest import KnowledgeManifest
from orchestwin.knowledge.schema_models.reviews import ReviewsDocument
from orchestwin.knowledge.schema_models.stages import (
    BriefDocument,
    DesignDocument,
    RequirementsDocument,
    TeamDocument,
    TwinDocument,
    TwinsDocument,
)
from orchestwin.knowledge.schema_models.why import WhyDocument
from orchestwin.knowledge.validation_schema import ValidationRecords
from orchestwin.models.team_proposals import (
    TeamProposalJustificationKind as TeamProposalJustificationKind,
)
from orchestwin.models.team_proposals import TeamProposalMemberSource as TeamProposalMemberSource
from orchestwin.models.team_proposals import TeamProposalProviderKind as TeamProposalProviderKind
from orchestwin.projects.briefs import BriefField as BriefField
from orchestwin.projects.domain import ProjectMode as ProjectMode
from orchestwin.projects.insight_applications import InsightSourceKind as InsightSourceKind
from orchestwin.projects.insight_applications import InsightTarget as InsightTarget
from orchestwin.projects.requirements import RequirementKind as RequirementKind
from orchestwin.projects.requirements import RequirementPriority as RequirementPriority
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind as RequirementsContextKind,
)
from orchestwin.projects.requirements_primitives import (
    RequirementSourceKind as RequirementSourceKind,
)
from orchestwin.projects.requirements_quality import (
    DefinitionOfDoneApplicability as DefinitionOfDoneApplicability,
)
from orchestwin.projects.requirements_quality import RiskImpact as RiskImpact
from orchestwin.projects.requirements_quality import RiskLikelihood as RiskLikelihood
from orchestwin.projects.requirements_quality import RiskReviewStatus as RiskReviewStatus
from orchestwin.projects.requirements_quality import VerificationMethod as VerificationMethod
from orchestwin.twins.epistemics import EpistemicStatus as EpistemicStatus
from orchestwin.twins.epistemics import EvidenceSourceKind as EvidenceSourceKind
from orchestwin.twins.epistemics import HumanValidationRequirement as HumanValidationRequirement
from orchestwin.twins.epistemics import ObservationValueKind as ObservationValueKind
from orchestwin.twins.personas import PersonaConfirmationStatus as PersonaConfirmationStatus
from orchestwin.twins.personas import PersonaKind as PersonaKind
from orchestwin.twins.personas import PersonaSource as PersonaSource
from orchestwin.twins.user_twins import UserTwinField as UserTwinField
from orchestwin.twins.user_twins import UserTwinLifecycleStatus as UserTwinLifecycleStatus
from orchestwin.workflow.gates import HumanGateStatus as HumanGateStatus
from orchestwin.workflow.gates import HumanGateType as HumanGateType

SCHEMA_NAMES: Final = (
    "manifest",
    "brief",
    "team",
    "twins",
    "twin",
    "requirements",
    "design",
    "reviews",
    "discussions",
    "insights",
    "state",
    "changes",
    "tests",
    "learning",
)
SCHEMA_DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"
MAX_DOCUMENT_DEPTH: Final = 64
_SCHEMA_ID_PREFIX: Final = f"urn:orchestwin:knowledge-folder:{KNOWLEDGE_SCHEMA_VERSION}"
_DESIGN_ADDITIONS: Final = {
    "DesignCritique": ("verdict", "quote"),
    "DesignPackageSnapshot": ("generated_mockup", "owner_assertions"),
}
_DESIGN_ADDITION_KEYWORDS: Final = {"DesignCritique": ("dependentRequired",)}
_DIRECTION_ADDITIONS: Final = {"VisualLanguage": ("direction",)}
_DEFINITION_PREFIX: Final = "#/$defs/"


class KnowledgeSchemaError(Exception):
    def __init__(
        self,
        *,
        code: str,
        document: str,
        location: str = "",
        message: str = "",
        path: str | None = None,
    ) -> None:
        subject = document if path is None else f"{document} ({path})"
        where = f"{subject} at {location}" if location else subject
        super().__init__(f"{code}: {where}: {message}" if message else f"{code}: {where}")
        self.code = code
        self.document = document
        self.location = location
        self.message = message
        self.path = path


class _KnowledgeJsonSchema(GenerateJsonSchema):
    def default_schema(self, schema: core_schema.WithDefaultSchema) -> JsonSchemaValue:
        inner = schema["schema"]
        if inner["type"] == "function-before":
            while inner["type"] in {"function-before", "nullable"}:
                inner = inner["schema"]
        return self.generate_inner(inner)

    def field_title_should_be_set(self, schema: object) -> bool:
        return False


_MODELS: Final = {
    "manifest": KnowledgeManifest,
    "brief": BriefDocument,
    "team": TeamDocument,
    "twins": TwinsDocument,
    "twin": TwinDocument,
    "requirements": RequirementsDocument,
    "design": DesignDocument,
    "reviews": ReviewsDocument,
    "discussions": DiscussionsDocument,
    "insights": InsightsDocument,
    "state": StateDocument,
    "changes": ChangeReviewsDocument,
    "tests": TestReviewsDocument,
    "learning": TwinLearningDocument,
    "evidence": ResearchEvidenceDocument,
    "why": WhyDocument,
    "validation": ValidationRecords,
}
_WRITTEN_BY: Final = "OrchesTwin Studio writes it when it exports the knowledge folder."
_SCHEMA_TEXTS: Final = {
    "validation": (
        "Operational hypotheses and validation outcomes",
        "Owner-selected operational hypotheses and exact source citations; candidates remain derived.",
    ),
    "why": ("Why traceability", "Derived provenance links, gaps and declared context."),
    "evidence": (
        "Research evidence excerpts",
        "Exact approved quotations, source provenance and limits. Original documents are excluded; owner approval does not establish empirical research or human validation.",
    ),
    "manifest": (
        "Knowledge folder manifest",
        f"Machine-readable index of a knowledge folder, stored in {KNOWLEDGE_MANIFEST} at the "
        "folder root: approved stages, progress, development state, user twins, views, twin "
        "feedback, stable identifiers, schemas and the SHA-256 digest of every file. "
        f"{_WRITTEN_BY}",
    ),
    "brief": (
        "Approved project brief",
        "The project brief approved at the project brief gate, stored in "
        f"{stage_document('brief')}. {_WRITTEN_BY}",
    ),
    "team": (
        "Approved agent team",
        "The agent team proposal approved at the agent team gate with its deterministic role "
        f"constraints, stored in {stage_document('team')}. {_WRITTEN_BY}",
    ),
    "twins": (
        "Approved user modeling",
        "The confirmed personas and the user twins approved at the user modeling gate, stored in "
        f"{stage_document('twins')}. {_WRITTEN_BY}",
    ),
    "twin": (
        "Portable user twin",
        "One approved user twin with its persona and its origin, stored in "
        f"{twin_document('<slug>')} so that it can travel alone, for example into another "
        "project. OrchesTwin Studio writes one for every twin when it exports the knowledge "
        "folder.",
    ),
    "requirements": (
        "Approved requirements specification",
        "The requirements, user stories, acceptance criteria, scenarios, risks and definition of "
        f"done approved at the requirements gate, stored in {stage_document('requirements')}. "
        f"{_WRITTEN_BY}",
    ),
    "design": (
        "Approved design package",
        "The design alternatives, the synthetic twin critiques, the owner's selection, the "
        "declarative mockup and the design concerns approved at the design gate, stored in "
        f"{stage_document('design')}. {_WRITTEN_BY}",
    ),
    "reviews": (
        "Twin reviews of the design",
        "The simulated reviews in which the user twins inspected the mockup of a selected design "
        f"alternative, with their findings and the owner's decisions, stored in {FEEDBACK_REVIEWS}; "
        f"every finding is a model inference, not empirical evidence. {_WRITTEN_BY}",
    ),
    "discussions": (
        "Approved twin discussions",
        "The discussions among the user twins about a design alternative that the owner approved, "
        f"round by round, stored in {FEEDBACK_DISCUSSIONS}. {_WRITTEN_BY}",
    ),
    "insights": (
        "Applied twin insights",
        "The twin feedback that the owner applied to the brief, the requirements or the design, "
        f"stored in {FEEDBACK_INSIGHTS}. {_WRITTEN_BY}",
    ),
    "state": (
        "Development state",
        "The development of the project outside the Studio, stored in "
        f"{STATE_DOCUMENT}: the approved requirements and design versions the code is expected "
        "to implement, the commits recorded in the Studio with their latest verdict, the "
        "versions that verdict was made against and the owner's decision, the aligned point and "
        "the tasks for the code with where each comes from. The diff of a commit is never "
        f"exported. {_WRITTEN_BY}",
    ),
    "changes": (
        "Twin critiques on the code changes",
        "The review runs in which every approved user twin criticized a recorded commit and the "
        f"model gave one alignment verdict, stored in {FEEDBACK_CHANGES}; every critique is a "
        f"model inference, not empirical evidence. {_WRITTEN_BY}",
    ),
    "tests": (
        "Acceptance tests and twin critiques on them",
        "The runs in which the command line ut test verified the approved acceptance criteria on "
        "the application developed outside the Studio, in the browsers of the computer that ran "
        "them: the paths with their steps, the outcome of every step, path and criterion, and the "
        f"latest critiques of the approved user twins on every run, stored in {FEEDBACK_TESTS}, "
        "newest first. Screenshots are never exported; every critique is a model inference, not "
        f"empirical evidence. {_WRITTEN_BY}",
    ),
    "learning": (
        "What the user twins learned",
        "What every approved user twin learned during the development of the application, "
        f"stored in {FEEDBACK_LEARNING}: the observations about its user group that the owner "
        "approved from the critiques of the twin or wrote directly, with the development version "
        "of the twin that added them, and the observations the owner retired. The approved "
        "profile of a twin never changes here; every observation is an assumption about a "
        f"modelled user, not empirical evidence. {_WRITTEN_BY}",
    ),
}
_DOCUMENT_PATHS: Final = {
    KNOWLEDGE_MANIFEST: "manifest",
    **{stage_document(stage): stage for stage in STAGES},
    FEEDBACK_REVIEWS: "reviews",
    FEEDBACK_DISCUSSIONS: "discussions",
    FEEDBACK_INSIGHTS: "insights",
    STATE_DOCUMENT: "state",
    FEEDBACK_CHANGES: "changes",
    FEEDBACK_TESTS: "tests",
    FEEDBACK_LEARNING: "learning",
    EVIDENCE_DOCUMENT: "evidence",
    "traceability/why.json": "why",
    "validation/human-validation.json": "validation",
}


def has_design_additions(package: Mapping[str, object]) -> bool:
    critiques = package.get("critiques") or ()
    return (
        package.get("generated_mockup") is not None
        or bool(package.get("owner_assertions"))
        or any(
            isinstance(item, Mapping)
            and (item.get("verdict") is not None or item.get("quote") is not None)
            for item in critiques
        )
    )


def has_direction_additions(package: Mapping[str, object]) -> bool:
    return any(
        isinstance(item, Mapping)
        and isinstance(item.get("visual_language"), Mapping)
        and item["visual_language"].get("direction") is not None
        for item in package.get("alternatives") or ()
    )


def _referenced_definitions(node: object) -> set[str]:
    found: set[str] = set()
    pending = [node]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            reference = current.get("$ref")
            if isinstance(reference, str) and reference.startswith(_DEFINITION_PREFIX):
                found.add(reference.removeprefix(_DEFINITION_PREFIX))
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)
    return found


def _without_additions(
    schema: dict[str, object],
    additions: Mapping[str, tuple[str, ...]],
    addition_keywords: Mapping[str, tuple[str, ...]],
) -> dict[str, object]:
    stripped = deepcopy(schema)
    definitions = stripped["$defs"]
    for model, fields in additions.items():
        for field in fields:
            del definitions[model]["properties"][field]
    for model, keywords in addition_keywords.items():
        for keyword in keywords:
            del definitions[model][keyword]
    kept = _referenced_definitions(
        {key: value for key, value in stripped.items() if key != "$defs"}
    )
    pending = list(kept)
    while pending:
        for name in _referenced_definitions(definitions[pending.pop()]) - kept:
            kept.add(name)
            pending.append(name)
    stripped["$defs"] = {name: value for name, value in definitions.items() if name in kept}
    return stripped


def _published_schema(
    name: str,
    *,
    design_additions: bool,
    direction_additions: bool = False,
    validation_additions: bool = False,
    workflow_additions: bool = False,
) -> dict[str, object]:
    title, description = _SCHEMA_TEXTS[name]
    schema = _MODELS[name].model_json_schema(schema_generator=_KnowledgeJsonSchema)
    if not workflow_additions:
        if name == "manifest":
            schema["properties"].pop("workflow_inputs", None)
        if name == "why":
            schema["properties"].pop("workflow_records", None)
            schema["$defs"]["WhyGap"]["properties"]["code"]["enum"] = [
                item
                for item in schema["$defs"]["WhyGap"]["properties"]["code"]["enum"]
                if item not in {"DECLARED_MISSING", "MISSING_REQUIREMENT_ANCHOR"}
                and not item.startswith("PROVIDED_PROTOTYPE_")
            ]
        revision = schema.get("$defs", {}).get("TeamProposalRevisionKind")
        if isinstance(revision, dict) and "OWNER_PROVIDED" in revision.get("enum", []):
            revision["enum"].remove("OWNER_PROVIDED")
    if name == "design" and not design_additions:
        schema = _without_additions(schema, _DESIGN_ADDITIONS, _DESIGN_ADDITION_KEYWORDS)
    if name == "design" and not direction_additions:
        schema = _without_additions(schema, _DIRECTION_ADDITIONS, {})
    if name == "why" and not validation_additions:
        schema["$defs"]["WhyGap"]["properties"]["code"]["enum"].remove(
            "VALIDATION_REFERENCE_UNAVAILABLE"
        )
    return {
        **schema,
        "$schema": SCHEMA_DIALECT,
        "$id": f"{_SCHEMA_ID_PREFIX}:{name}",
        "title": title,
        "description": description,
    }


def knowledge_schemas(
    *,
    design_additions: bool = False,
    direction_additions: bool = False,
    research_evidence: bool = False,
    only_evidence: bool = False,
    only_why: bool = False,
    only_validation: bool = False,
    validation_additions: bool = False,
    workflow_additions: bool = False,
) -> dict[str, dict[str, object]]:
    names = (
        ("validation",)
        if only_validation
        else ("why",)
        if only_why
        else ("evidence",)
        if only_evidence
        else (*SCHEMA_NAMES, *(("evidence",) if research_evidence else ()))
    )
    return {
        name: _published_schema(
            name,
            design_additions=design_additions,
            direction_additions=direction_additions,
            validation_additions=validation_additions,
            workflow_additions=workflow_additions,
        )
        for name in names
    }


def schema_files(
    *,
    design_additions: bool = False,
    direction_additions: bool = False,
    research_evidence: bool = False,
    only_evidence: bool = False,
    only_why: bool = False,
    only_validation: bool = False,
    validation_additions: bool = False,
    workflow_additions: bool = False,
) -> dict[str, str]:
    return {
        schema_document(name): json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
        for name, schema in knowledge_schemas(
            design_additions=design_additions,
            direction_additions=direction_additions,
            research_evidence=research_evidence,
            only_evidence=only_evidence,
            only_why=only_why,
            only_validation=only_validation,
            validation_additions=validation_additions,
            workflow_additions=workflow_additions,
        ).items()
    }


def schema_name_for_path(path: str) -> str | None:
    known = _DOCUMENT_PATHS.get(path)
    if known is not None:
        return known
    parts = path.split("/")
    if (
        len(parts) == 3
        and parts[1]
        and path == twin_document(parts[1])
        and f"{TWIN_FOLDER}/{parts[1]}" != FEEDBACK_FOLDER
    ):
        return "twin"
    return None


def _location(parts: tuple[int | str, ...]) -> str:
    location = ""
    for part in parts:
        if isinstance(part, int):
            location += f"[{part}]"
        else:
            location += f".{part}" if location else part
    return location


def within_depth(value: object, limit: int = MAX_DOCUMENT_DEPTH) -> bool:
    level = [value]
    for _ in range(limit):
        following: list[object] = []
        for item in level:
            if isinstance(item, dict):
                following.extend(item.values())
            elif isinstance(item, list):
                following.extend(item)
        if not following:
            return True
        level = following
    return False


def _nested_too_deeply(name: str, path: str) -> KnowledgeSchemaError:
    return KnowledgeSchemaError(
        code="DOCUMENT_INVALID",
        document=name,
        message="the document is nested too deeply",
        path=path,
    )


def _validate(name: str, payload: object, path: str | None) -> None:
    model = _MODELS.get(name)
    if model is None:
        raise KnowledgeSchemaError(
            code="UNKNOWN_SCHEMA",
            document=name,
            message=f"no knowledge folder schema is named {name!r}",
            path=path,
        )
    try:
        model.model_validate(payload)
    except ValidationError as error:
        first = error.errors(include_url=False)[0]
        location = first["loc"]
        if (
            name == "requirements"
            and len(location) > 1
            and location[0] == "specification"
            and location[1] in (1, 2)
        ):
            location = (location[0], *location[2:])
        raise KnowledgeSchemaError(
            code="DOCUMENT_INVALID",
            document=name,
            location=_location(location),
            message=first["msg"],
            path=path,
        ) from error


def validate_document(name: str, payload: object) -> None:
    _validate(name, payload, None)


def validate_files(files: Mapping[str, str]) -> None:
    for path in sorted(files):
        name = schema_name_for_path(path)
        if name is None:
            continue
        try:
            payload = json.loads(files[path])
        except RecursionError as error:
            raise _nested_too_deeply(name, path) from error
        except (TypeError, ValueError) as error:
            raise KnowledgeSchemaError(
                code="DOCUMENT_NOT_JSON", document=name, message=str(error), path=path
            ) from error
        if not within_depth(payload):
            raise _nested_too_deeply(name, path)
        _validate(name, payload, path)


__all__ = [
    "MAX_DOCUMENT_DEPTH",
    "SCHEMA_DIALECT",
    "SCHEMA_NAMES",
    "KnowledgeSchemaError",
    "has_design_additions",
    "has_direction_additions",
    "knowledge_schemas",
    "schema_files",
    "schema_name_for_path",
    "validate_document",
    "validate_files",
    "within_depth",
]
