from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, replace
from datetime import datetime
from typing import Final
from uuid import UUID, uuid5

from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.generated_mockup_structure import derive_elements
from orchestwin.artifacts.mockup_html import render_evaluation_document
from orchestwin.artifacts.prototypes import (
    PrototypeElement,
    PrototypeElementKind,
    PrototypeScreen,
)
from orchestwin.evaluation.artifact_content import MAX_VIEW_BYTES
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactBundle,
    EvaluationArtifactKind,
    EvaluationArtifactReference,
    EvaluationScenario,
    create_evaluation_artifact_bundle,
)
from orchestwin.evaluation.evaluator import (
    UserTwinEvaluationResponse,
    UserTwinEvaluatorConfiguration,
)
from orchestwin.evaluation.findings import (
    SyntheticFinding,
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.projects.requirements_primitives import (
    canonical_json,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.twins.limits import MAX_USER_TWINS

DESIGN_EVALUATION_SCHEMA_VERSION: Final = 1
EVALUATION_DOCUMENT_LOCATION: Final = "design/mockup.html"
DESIGN_SPECIFICATION_LOCATION: Final = "design/design.json"
EVALUATION_DOCUMENT_MEDIA_TYPE: Final = "text/html"
DESIGN_SPECIFICATION_MEDIA_TYPE: Final = "application/json"
MAX_EVALUATED_TWINS: Final = MAX_USER_TWINS
MATCH_SIMILARITY: Final = 0.3
MATCH_STEM_LENGTH: Final = 6
ANCHOR_LABEL_LENGTH: Final = 80
SCENARIO_NAME_LENGTH: Final = 200
SCENARIO_TASK_LENGTH: Final = 2000
SCENARIO_OUTCOME_LENGTH: Final = 1000
_SCENARIO_NAMESPACE: Final = UUID("5b0d2f1e-0e4a-4d1f-9d6a-3c1e5e7f2a11")
CONTENT_STEPS: Final = (None, 400, 240, 160, 100, 60)
HOSTED_DOCUMENT_BYTES: Final = 96 * 1024
TABLE_ROWS_SHOWN: Final = 12
MAX_ELEMENT_ANCHORS: Final = 120
OTHER_ANCHORS_PER_SCREEN: Final = 8
REMAINING_ROWS: Final = {
    "it": ("… e un'altra riga della tabella", "… e altre {count} righe della tabella"),
    "en": ("… and one more row in the table", "… and {count} more rows in the table"),
}
_ANCHOR_KEY: Final = re.compile(r"SCR-[0-9]{3,6}(?:/ELM-[0-9]{3,6})?")
_WORD: Final = re.compile(r"[a-z0-9àèéìòù]+")
_STOPWORDS: Final = frozenset(
    [
        "il",
        "lo",
        "la",
        "gli",
        "le",
        "un",
        "uno",
        "una",
        "di",
        "da",
        "in",
        "con",
        "su",
        "per",
        "tra",
        "fra",
        "ma",
        "che",
        "non",
        "sono",
        "ha",
        "hanno",
        "del",
        "della",
        "dei",
        "delle",
        "degli",
        "al",
        "alla",
        "ai",
        "alle",
        "dal",
        "dalla",
        "nel",
        "nella",
        "nei",
        "nelle",
        "sul",
        "sulla",
        "come",
        "più",
        "meno",
        "anche",
        "se",
        "ci",
        "si",
        "mi",
        "ti",
        "ed",
        "the",
        "an",
        "of",
        "to",
        "on",
        "for",
        "and",
        "or",
        "is",
        "are",
        "not",
        "with",
        "by",
        "as",
        "at",
        "it",
        "this",
        "that",
        "does",
        "do",
        "has",
        "have",
        "be",
        "can",
    ]
)


class DesignEvaluationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class AnchoredSyntheticFinding(SyntheticFinding):
    anchor_key: str

    def __post_init__(self) -> None:
        SyntheticFinding.__post_init__(self)
        if not isinstance(self.anchor_key, str) or _ANCHOR_KEY.fullmatch(self.anchor_key) is None:
            raise ValueError("synthetic finding anchor key must name a screen or an element")

    def to_snapshot(self) -> dict[str, object]:
        snapshot: dict[str, object] = {}
        for key, value in SyntheticFinding.to_snapshot(self).items():
            snapshot[key] = value
            if key == "location":
                snapshot["anchor_key"] = self.anchor_key
        return snapshot


def anchor_finding(finding: SyntheticFinding, anchor_key: str) -> AnchoredSyntheticFinding:
    return AnchoredSyntheticFinding(
        **{item.name: getattr(finding, item.name) for item in fields(SyntheticFinding)},
        anchor_key=anchor_key,
    )


def finding_anchor_key(finding: SyntheticFinding) -> str | None:
    return finding.anchor_key if isinstance(finding, AnchoredSyntheticFinding) else None


@dataclass(frozen=True, slots=True)
class DesignEvaluationDocument:
    content: bytes
    reference: EvaluationArtifactReference

    def read(self, key: str, maximum_bytes: int) -> bytes:
        if key != self.reference.storage_key or maximum_bytes < len(self.content):
            raise DesignEvaluationError("EVALUATION_DOCUMENT_UNAVAILABLE")
        return self.content


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def evaluation_reference(
    *,
    artifact_id: UUID,
    version_number: int,
    kind: EvaluationArtifactKind,
    media_type: str,
    content: bytes,
    location: str,
) -> EvaluationArtifactReference:
    digest = _digest(content)
    return EvaluationArtifactReference(
        artifact_id=artifact_id,
        version_number=version_number,
        kind=kind,
        media_type=media_type,
        sha256_digest=digest,
        size_bytes=len(content),
        storage_key=f"sha256/{digest[:2]}/{digest}",
        location=location,
    )


def evaluation_document(
    version: DesignPackageVersion, *, language: str = "und", hosted: bool = False
) -> DesignEvaluationDocument:
    package = version.package
    if package.prototype is None or package.owner_selected_alternative_id is None:
        raise DesignEvaluationError("DESIGN_PROTOTYPE_REQUIRED")
    snapshot = package.to_snapshot()
    maximum = MAX_VIEW_BYTES
    if hosted and package.generated_mockup is not None:
        snapshot = _reduced_snapshot(version, snapshot, language)
        maximum = HOSTED_DOCUMENT_BYTES
    for step in CONTENT_STEPS:
        text = render_evaluation_document(snapshot, language=language, max_content=step)
        content = text.encode("utf-8")
        if len(content) <= maximum:
            return DesignEvaluationDocument(
                content=content,
                reference=evaluation_reference(
                    artifact_id=package.prototype.id,
                    version_number=version.version_number,
                    kind=EvaluationArtifactKind.DOM_SNAPSHOT,
                    media_type=EVALUATION_DOCUMENT_MEDIA_TYPE,
                    content=content,
                    location=EVALUATION_DOCUMENT_LOCATION,
                ),
            )
    raise DesignEvaluationError("EVALUATION_DOCUMENT_TOO_LARGE")


def _selected_alternative(version: DesignPackageVersion):
    package = version.package
    if package.prototype is None or package.owner_selected_alternative_id is None:
        raise DesignEvaluationError("DESIGN_PROTOTYPE_REQUIRED")
    return next(
        item for item in package.alternatives if item.id == package.owner_selected_alternative_id
    )


def ordered_screens(version: DesignPackageVersion):
    prototype = version.package.prototype
    entry = next(screen for screen in prototype.screens if screen.id == prototype.entry_screen_id)
    return (entry, *(screen for screen in prototype.screens if screen.id != entry.id))


def _bounded(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    return normalized if len(normalized) <= limit else normalized[: limit - 1] + "…"


def _anchor_label(text: str) -> str:
    return text if len(text) <= ANCHOR_LABEL_LENGTH else text[: ANCHOR_LABEL_LENGTH - 1] + "…"


def remaining_rows_text(count: int, language: str) -> str:
    one, many = REMAINING_ROWS.get(language, REMAINING_ROWS["en"])
    return one if count == 1 else many.format(count=count)


def _hidden_rows(version: DesignPackageVersion) -> tuple[frozenset[str], dict[str, int]]:
    elements = derive_elements(version.package.generated_mockup.mockup)
    tables: dict[tuple[str, tuple[int, ...]], list] = {}
    for item in elements:
        if item.node_name == "tr" and item.kind is PrototypeElementKind.LIST:
            tables.setdefault((item.screen_code, item.path[:-2]), []).append(item)
    paths: dict[str, set[tuple[int, ...]]] = {}
    markers: dict[str, int] = {}
    for (screen, _table), rows in tables.items():
        rest = rows[TABLE_ROWS_SHOWN:]
        if rest:
            markers[rest[0].code] = len(rest)
            paths.setdefault(screen, set()).update(row.path for row in rest)
    hidden = frozenset(
        item.code
        for item in elements
        if any(
            item.path[:depth] in paths.get(item.screen_code, ())
            for depth in range(1, len(item.path) + 1)
        )
    )
    return hidden, markers


def review_screens(
    version: DesignPackageVersion, *, hosted: bool = False, language: str = "und"
) -> tuple[tuple[PrototypeScreen, tuple[PrototypeElement, ...]], ...]:
    screens = ordered_screens(version)
    if not hosted or version.package.generated_mockup is None:
        return tuple((screen, screen.elements) for screen in screens)
    hidden, markers = _hidden_rows(version)
    reduced = []
    for screen in screens:
        elements = []
        for element in screen.elements:
            count = markers.get(element.code)
            if count is not None:
                elements.append(
                    replace(
                        element,
                        kind=PrototypeElementKind.TEXT,
                        content=remaining_rows_text(count, language),
                        accessible_name=None,
                    )
                )
            elif element.code not in hidden:
                elements.append(element)
        reduced.append((screen, tuple(elements)))
    return tuple(reduced)


def _reduced_snapshot(
    version: DesignPackageVersion, snapshot: Mapping[str, object], language: str
) -> dict[str, object]:
    elements = {
        screen.code: [element.to_snapshot() for element in items]
        for screen, items in review_screens(version, hosted=True, language=language)
    }
    prototype = snapshot["prototype"]
    return {
        **snapshot,
        "prototype": {
            **prototype,
            "screens": [
                {**screen, "elements": elements[screen["code"]]} for screen in prototype["screens"]
            ],
        },
    }


def _anchored_elements(elements):
    kept, others = [], 0
    for element in elements:
        if element.is_interactive or element.kind is PrototypeElementKind.HEADING:
            kept.append(element)
        elif others < OTHER_ANCHORS_PER_SCREEN:
            others += 1
            kept.append(element)
    return tuple(kept)


def design_review_anchors(
    version: DesignPackageVersion, *, hosted: bool = False, language: str = "und"
) -> dict[str, str]:
    _selected_alternative(version)
    screens = review_screens(version, hosted=hosted, language=language)
    bounded = sum(len(elements) for _screen, elements in screens) > MAX_ELEMENT_ANCHORS
    anchors: dict[str, str] = {}
    for screen, elements in screens:
        place = f"{screen.code} {_anchor_label(screen.title)}"
        anchors[screen.code] = place
        for element in _anchored_elements(elements) if bounded else elements:
            label = _anchor_label(element.accessible_name or element.content)
            anchors[f"{screen.code}/{element.code}"] = f"{place} · {element.code} {label}"
    return anchors


def _element_view(element, leads) -> dict[str, object]:
    return {
        "code": element.code,
        "kind": element.kind.value,
        "content": element.content,
        "accessible_name": element.accessible_name,
        "field_name": element.field_name,
        "required": element.required,
        "options": list(element.options),
        "leads_to": leads.get(element.id),
    }


def _compact_element_view(element, leads) -> dict[str, object]:
    view: dict[str, object] = {
        "code": element.code,
        "kind": element.kind.value,
        "content": element.content,
    }
    if element.accessible_name is not None and element.accessible_name != element.content:
        view["accessible_name"] = element.accessible_name
    if element.field_name is not None:
        view["field_name"] = element.field_name
    if element.required:
        view["required"] = True
    if element.options:
        view["options"] = list(element.options)
    if element.id in leads:
        view["leads_to"] = leads[element.id]
    return view


def _screen_view(screen, elements, leads, *, generated: bool) -> dict[str, object]:
    view: dict[str, object] = {
        "code": screen.code,
        "title": screen.title,
        "state": screen.state.value,
    }
    if not generated:
        view["elements"] = [_element_view(element, leads) for element in elements]
        return view
    view["visible_text"] = [element.content for element in elements]
    view["elements"] = [_compact_element_view(element, leads) for element in elements]
    return view


def design_review_view(
    version: DesignPackageVersion, *, hosted: bool = False, language: str = "und"
) -> dict[str, object]:
    alternative = _selected_alternative(version)
    prototype = version.package.prototype
    screens = review_screens(version, hosted=hosted, language=language)
    codes = {screen.id: screen.code for screen, _elements in screens}
    leads = {
        item.trigger_element_id: codes[item.target_screen_id] for item in prototype.transitions
    }
    generated = version.package.generated_mockup is not None
    visual = alternative.visual_language
    return {
        "alternative": {
            "code": alternative.code,
            "title": alternative.title,
            "summary": alternative.summary,
            "rationale": alternative.rationale,
            "information_architecture": list(alternative.information_architecture),
            "accessibility_considerations": list(alternative.accessibility_considerations),
            "trade_offs": list(alternative.trade_offs),
            "workflows": [
                {"code": item.code, "title": item.title, "steps": list(item.steps)}
                for item in alternative.workflows
            ],
        },
        "visual_language": None
        if visual is None
        else {
            "product_name": visual.product_name,
            "rationale": visual.rationale,
            "choices": visual.choices.to_snapshot(),
            "twin_fit": {str(item.twin_id): item.statement for item in visual.twin_fit},
        },
        "entry_screen": screens[0][0].code,
        "screens": [
            _screen_view(screen, elements, leads, generated=generated)
            for screen, elements in screens
        ],
    }


def evaluation_scenario(version: DesignPackageVersion, *, locale: str) -> EvaluationScenario:
    package = version.package
    alternative = next(
        item for item in package.alternatives if item.id == package.owner_selected_alternative_id
    )
    workflow = alternative.workflows[0]
    outcomes = tuple(
        dict.fromkeys(_bounded(step, SCENARIO_OUTCOME_LENGTH) for step in workflow.steps)
    )
    return EvaluationScenario(
        id=uuid5(_SCENARIO_NAMESPACE, f"{version.id}:{alternative.id}"),
        name=_bounded(alternative.title, SCENARIO_NAME_LENGTH),
        task=_bounded(workflow.title, SCENARIO_TASK_LENGTH),
        locale=locale,
        expected_outcomes=outcomes,
    )


def evaluation_bundle(
    version: DesignPackageVersion,
    document: DesignEvaluationDocument,
    *,
    locale: str,
    created_at: datetime,
    bundle_id: UUID | None = None,
) -> EvaluationArtifactBundle:
    specification = canonical_json(version.package.to_snapshot()).encode("utf-8")
    return create_evaluation_artifact_bundle(
        project_id=version.project_id,
        workflow_run_id=version.id,
        scenario=evaluation_scenario(version, locale=locale),
        artifacts=(
            document.reference,
            evaluation_reference(
                artifact_id=version.id,
                version_number=version.version_number,
                kind=EvaluationArtifactKind.DESIGN_SPECIFICATION,
                media_type=DESIGN_SPECIFICATION_MEDIA_TYPE,
                content=specification,
                location=DESIGN_SPECIFICATION_LOCATION,
            ),
        ),
        created_at=created_at,
        bundle_id=bundle_id,
    )


@dataclass(frozen=True, slots=True)
class DesignEvaluationRun:
    id: UUID
    project_id: UUID
    owner_user_id: UUID
    design_version_id: UUID
    design_version_number: int
    design_content_hash: str
    alternative_id: UUID
    alternative_code: str
    bundle: EvaluationArtifactBundle
    responses: tuple[UserTwinEvaluationResponse, ...]
    started_at: datetime
    completed_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        validate_positive_integer(self.design_version_number, label="design evaluation version")
        validate_sha256(self.design_content_hash, label="design evaluation content hash")
        validate_sha256(self.content_hash, label="design evaluation run hash")
        if not 1 <= len(self.responses) <= MAX_EVALUATED_TWINS:
            raise ValueError("design evaluation run needs one response per twin")
        twins = [response.twin_id for response in self.responses]
        if len(set(twins)) != len(twins):
            raise ValueError("design evaluation run responses must name distinct twins")
        if any(
            response.evaluation_run_id != self.id
            or response.artifact_bundle_id != self.bundle.id
            or response.artifact_bundle_hash != self.bundle.content_hash
            for response in self.responses
        ):
            raise ValueError("design evaluation responses must belong to the run and its bundle")
        if (
            self.bundle.project_id != self.project_id
            or self.bundle.workflow_run_id != self.design_version_id
        ):
            raise ValueError("design evaluation bundle must describe the evaluated design version")
        for value, label in ((self.started_at, "started"), (self.completed_at, "completed")):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"design evaluation {label} timestamp must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("design evaluation must complete after it starts")
        if self.content_hash != design_evaluation_run_hash(self):
            raise ValueError("design evaluation run hash is inconsistent")

    @property
    def findings(self) -> tuple[SyntheticFinding, ...]:
        return tuple(finding for response in self.responses for finding in response.findings)

    @property
    def evaluator(self) -> UserTwinEvaluatorConfiguration:
        return self.responses[0].evaluator

    def semantic_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": DESIGN_EVALUATION_SCHEMA_VERSION,
            "id": str(self.id),
            "project_id": str(self.project_id),
            "owner_user_id": str(self.owner_user_id),
            "design_version_id": str(self.design_version_id),
            "design_version_number": self.design_version_number,
            "design_content_hash": self.design_content_hash,
            "alternative_id": str(self.alternative_id),
            "alternative_code": self.alternative_code,
            "bundle": self.bundle.to_snapshot(),
            "responses": [response.to_snapshot() for response in self.responses],
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
        }

    def to_snapshot(self) -> dict[str, object]:
        return {**self.semantic_snapshot(), "content_hash": self.content_hash}


def design_evaluation_run_hash(run: DesignEvaluationRun) -> str:
    return snapshot_content_hash(run.semantic_snapshot())


def create_design_evaluation_run(
    *,
    run_id: UUID,
    owner_user_id: UUID,
    version: DesignPackageVersion,
    bundle: EvaluationArtifactBundle,
    responses: Sequence[UserTwinEvaluationResponse],
    started_at: datetime,
    completed_at: datetime,
) -> DesignEvaluationRun:
    package = version.package
    alternative = next(
        item for item in package.alternatives if item.id == package.owner_selected_alternative_id
    )
    ordered = tuple(sorted(responses, key=lambda item: str(item.twin_id)))
    return _build_run(
        run_id, owner_user_id, version, alternative, bundle, ordered, started_at, completed_at
    )


def _build_run(
    run_id, owner_user_id, version, alternative, bundle, responses, started_at, completed_at
):
    fields = {
        "id": run_id,
        "project_id": version.project_id,
        "owner_user_id": owner_user_id,
        "design_version_id": version.id,
        "design_version_number": version.version_number,
        "design_content_hash": version.content_hash,
        "alternative_id": alternative.id,
        "alternative_code": alternative.code,
        "bundle": bundle,
        "responses": responses,
        "started_at": started_at,
        "completed_at": completed_at,
    }
    semantic = {
        "schema_version": DESIGN_EVALUATION_SCHEMA_VERSION,
        "id": str(run_id),
        "project_id": str(version.project_id),
        "owner_user_id": str(owner_user_id),
        "design_version_id": str(version.id),
        "design_version_number": version.version_number,
        "design_content_hash": version.content_hash,
        "alternative_id": str(alternative.id),
        "alternative_code": alternative.code,
        "bundle": bundle.to_snapshot(),
        "responses": [response.to_snapshot() for response in responses],
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
    }
    return DesignEvaluationRun(**fields, content_hash=snapshot_content_hash(semantic))


def _words(text: str) -> set[str]:
    return {
        word[:MATCH_STEM_LENGTH]
        for word in _WORD.findall(text.casefold())
        if len(word) > 2 and word not in _STOPWORDS
    }


def finding_similarity(first: SyntheticFinding, second: SyntheticFinding) -> float:
    if first.twin_id != second.twin_id:
        return 0.0
    if (
        first.criterion is second.criterion
        and first.location.casefold() == second.location.casefold()
    ):
        return 1.0
    a, b = _words(first.summary), _words(second.summary)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass(frozen=True, slots=True)
class DesignEvaluationComparison:
    base_run_id: UUID
    head_run_id: UUID
    resolved: tuple[SyntheticFinding, ...]
    persisting: tuple[tuple[SyntheticFinding, SyntheticFinding], ...]
    introduced: tuple[SyntheticFinding, ...]
    dismissed: int = 0

    def to_snapshot(self) -> dict[str, object]:
        return {
            "base_run_id": str(self.base_run_id),
            "head_run_id": str(self.head_run_id),
            "resolved": [item.to_snapshot() for item in self.resolved],
            "persisting": [
                {"before": before.to_snapshot(), "after": after.to_snapshot()}
                for before, after in self.persisting
            ],
            "introduced": [item.to_snapshot() for item in self.introduced],
            "counts": {
                "base": len(self.resolved) + len(self.persisting),
                "head": len(self.introduced) + len(self.persisting),
                "resolved": len(self.resolved),
                "persisting": len(self.persisting),
                "introduced": len(self.introduced),
                "dismissed": self.dismissed,
            },
        }


def finding_key(run_id: UUID, finding: SyntheticFinding) -> tuple[UUID, UUID, str]:
    return (run_id, finding.twin_id, finding.finding_id)


def compare_design_evaluations(
    base: DesignEvaluationRun,
    head: DesignEvaluationRun,
    *,
    dismissed: frozenset[tuple[UUID, UUID, str]] = frozenset(),
) -> DesignEvaluationComparison:
    rejected = [item for item in base.findings if finding_key(base.id, item) in dismissed]
    considered = [item for item in base.findings if finding_key(base.id, item) not in dismissed]
    remaining = [
        item
        for item in head.findings
        if finding_key(head.id, item) not in dismissed
        and not any(finding_similarity(earlier, item) >= MATCH_SIMILARITY for earlier in rejected)
    ]
    excluded = len(head.findings) - len(remaining) + len(rejected)
    resolved, persisting = [], []
    for finding in considered:
        best, score = None, 0.0
        for candidate in remaining:
            similarity = finding_similarity(finding, candidate)
            if similarity > score:
                best, score = candidate, similarity
        if best is not None and score >= MATCH_SIMILARITY:
            persisting.append((finding, best))
            remaining.remove(best)
        else:
            resolved.append(finding)
    return DesignEvaluationComparison(
        base_run_id=base.id,
        head_run_id=head.id,
        resolved=tuple(resolved),
        persisting=tuple(persisting),
        introduced=tuple(remaining),
        dismissed=excluded,
    )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO timestamp")
    return datetime.fromisoformat(value)


def synthetic_finding_from_snapshot(payload: Mapping[str, object]) -> SyntheticFinding:
    finding = create_synthetic_finding(
        finding_id=str(payload["finding_id"]),
        twin_id=UUID(str(payload["twin_id"])),
        twin_version=int(payload["twin_version"]),
        artifact_id=UUID(str(payload["artifact_id"])),
        artifact_version=int(payload["artifact_version"]),
        location=str(payload["location"]),
        summary=str(payload["summary"]),
        rationale=str(payload["rationale"]),
        criterion=SyntheticFindingCriterion(str(payload["criterion"])),
        severity=SyntheticFindingSeverity(str(payload["severity"])),
        epistemic_status=SyntheticFindingEpistemicStatus(str(payload["epistemic_status"])),
        evidence_refs=tuple(str(item) for item in payload["evidence_refs"]),
        confidence=float(payload["confidence"]),
        recommended_action=str(payload["recommended_action"]),
        requires_human_validation=bool(payload["requires_human_validation"]),
        model_config_ref=str(payload["model_config_ref"]),
        prompt_version_ref=str(payload["prompt_version_ref"]),
    )
    if finding.content_hash != payload["content_hash"]:
        raise ValueError("synthetic finding snapshot is not canonical")
    if "anchor_key" in payload:
        return anchor_finding(finding, payload["anchor_key"])
    return finding


def evaluation_response_from_snapshot(payload: Mapping[str, object]) -> UserTwinEvaluationResponse:
    evaluator = _mapping(payload["evaluator"], "evaluator")
    return UserTwinEvaluationResponse(
        evaluation_run_id=UUID(str(payload["evaluation_run_id"])),
        artifact_bundle_id=UUID(str(payload["artifact_bundle_id"])),
        artifact_bundle_hash=str(payload["artifact_bundle_hash"]),
        twin_id=UUID(str(payload["twin_id"])),
        twin_version=int(payload["twin_version"]),
        evaluator=UserTwinEvaluatorConfiguration(
            evaluator_id=str(evaluator["evaluator_id"]),
            evaluator_version=str(evaluator["evaluator_version"]),
            model_config_ref=str(evaluator["model_config_ref"]),
            prompt_version_ref=str(evaluator["prompt_version_ref"]),
        ),
        findings=tuple(
            synthetic_finding_from_snapshot(_mapping(item, "finding"))
            for item in payload["findings"]
        ),
        summary=str(payload["summary"]),
        evidence_gaps=tuple(str(item) for item in payload["evidence_gaps"]),
        completed_at=_timestamp(payload["completed_at"], "completed_at"),
        content_hash=str(payload["content_hash"]),
    )


def evaluation_bundle_from_snapshot(payload: Mapping[str, object]) -> EvaluationArtifactBundle:
    scenario = _mapping(payload["scenario"], "scenario")
    bundle = create_evaluation_artifact_bundle(
        project_id=UUID(str(payload["project_id"])),
        workflow_run_id=UUID(str(payload["workflow_run_id"])),
        scenario=EvaluationScenario(
            id=UUID(str(scenario["id"])),
            name=str(scenario["name"]),
            task=str(scenario["task"]),
            locale=str(scenario["locale"]),
            expected_outcomes=tuple(str(item) for item in scenario["expected_outcomes"]),
        ),
        artifacts=tuple(
            EvaluationArtifactReference(
                artifact_id=UUID(str(item["artifact_id"])),
                version_number=int(item["version_number"]),
                kind=EvaluationArtifactKind(str(item["kind"])),
                media_type=str(item["media_type"]),
                sha256_digest=str(item["sha256_digest"]),
                size_bytes=int(item["size_bytes"]),
                storage_key=str(item["storage_key"]),
                location=str(item["location"]),
            )
            for item in payload["artifacts"]
        ),
        created_at=_timestamp(payload["created_at"], "created_at"),
        bundle_id=UUID(str(payload["id"])),
    )
    if bundle.content_hash != payload["content_hash"]:
        raise ValueError("evaluation bundle snapshot is not canonical")
    return bundle


def design_evaluation_run_from_snapshot(payload: Mapping[str, object]) -> DesignEvaluationRun:
    if payload.get("schema_version") != DESIGN_EVALUATION_SCHEMA_VERSION:
        raise ValueError("unsupported design evaluation schema")
    run = DesignEvaluationRun(
        id=UUID(str(payload["id"])),
        project_id=UUID(str(payload["project_id"])),
        owner_user_id=UUID(str(payload["owner_user_id"])),
        design_version_id=UUID(str(payload["design_version_id"])),
        design_version_number=int(payload["design_version_number"]),
        design_content_hash=str(payload["design_content_hash"]),
        alternative_id=UUID(str(payload["alternative_id"])),
        alternative_code=str(payload["alternative_code"]),
        bundle=evaluation_bundle_from_snapshot(_mapping(payload["bundle"], "bundle")),
        responses=tuple(
            evaluation_response_from_snapshot(_mapping(item, "response"))
            for item in payload["responses"]
        ),
        started_at=_timestamp(payload["started_at"], "started_at"),
        completed_at=_timestamp(payload["completed_at"], "completed_at"),
        content_hash=str(payload["content_hash"]),
    )
    if run.to_snapshot() != dict(payload):
        raise ValueError("design evaluation run snapshot is not canonical")
    return run


__all__ = [
    "ANCHOR_LABEL_LENGTH",
    "CONTENT_STEPS",
    "DESIGN_EVALUATION_SCHEMA_VERSION",
    "DESIGN_SPECIFICATION_LOCATION",
    "EVALUATION_DOCUMENT_LOCATION",
    "HOSTED_DOCUMENT_BYTES",
    "MATCH_SIMILARITY",
    "MATCH_STEM_LENGTH",
    "MAX_ELEMENT_ANCHORS",
    "MAX_EVALUATED_TWINS",
    "OTHER_ANCHORS_PER_SCREEN",
    "REMAINING_ROWS",
    "TABLE_ROWS_SHOWN",
    "AnchoredSyntheticFinding",
    "DesignEvaluationComparison",
    "DesignEvaluationDocument",
    "DesignEvaluationError",
    "DesignEvaluationRun",
    "anchor_finding",
    "compare_design_evaluations",
    "create_design_evaluation_run",
    "design_evaluation_run_from_snapshot",
    "design_evaluation_run_hash",
    "design_review_anchors",
    "design_review_view",
    "evaluation_bundle",
    "evaluation_bundle_from_snapshot",
    "evaluation_document",
    "evaluation_reference",
    "evaluation_response_from_snapshot",
    "evaluation_scenario",
    "finding_anchor_key",
    "finding_key",
    "finding_similarity",
    "ordered_screens",
    "remaining_rows_text",
    "review_screens",
    "synthetic_finding_from_snapshot",
]
