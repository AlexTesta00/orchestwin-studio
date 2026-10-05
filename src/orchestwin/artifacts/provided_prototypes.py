from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import UUID

from orchestwin.artifacts.bound_mockups import (
    BoundGeneratedMockup,
    bound_mockup_from_snapshot,
    create_bound_mockup,
    markup_requirement_codes,
)
from orchestwin.artifacts.generated_mockup_review import MockupReport, review_generated_mockup
from orchestwin.artifacts.generated_mockups import (
    GeneratedMockupError,
    create_generated_mockup,
    generated_mockup_from_snapshot,
)
from orchestwin.artifacts.visual_catalog import (
    ARCHETYPES,
    MODES,
    VisualChoices,
    resolve_visual_tokens,
)
from orchestwin.projects.requirements_primitives import (
    normalize_optional_text,
    validate_display_code,
    validate_positive_integer,
)
from orchestwin.workflow_inputs import (
    WorkflowInputError,
    canonical_workflow_json,
    decision_content_hash,
    validate_workflow_reference,
    workflow_records,
)


def _reference(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        try:
            value = {
                "artifact_id": str(value.artifact_id),
                "version_number": value.version_number,
                "content_hash": value.content_hash,
            }
        except AttributeError as error:
            raise WorkflowInputError("WORKFLOW_REFERENCE_INVALID") from error
    return MappingProxyType(validate_workflow_reference(value))


def _choices(value: object) -> VisualChoices:
    if not isinstance(value, Mapping):
        raise WorkflowInputError("PROVIDED_PROTOTYPE_VISUAL_CHOICES_INVALID")
    try:
        return VisualChoices.from_snapshot(value)
    except (TypeError, ValueError) as error:
        raise WorkflowInputError("PROVIDED_PROTOTYPE_VISUAL_CHOICES_INVALID") from error


def _text(value: object, *, label: str, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str):
        raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", label)
    try:
        return normalize_optional_text(value, label=label, maximum_length=200)
    except ValueError as error:
        raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", label) from error


def _quality(mockup: BoundGeneratedMockup, choices: VisualChoices) -> MockupReport:
    tokens = resolve_visual_tokens(choices)
    try:
        generated_mockup_from_snapshot(mockup.mockup.to_snapshot(), token_names=tokens)
        report = review_generated_mockup(
            mockup.mockup,
            tokens=tokens,
            requirement_codes=mockup.requirement_codes,
            text_contrast_threshold=MODES[choices.color_mode].text_threshold,
        )
    except GeneratedMockupError as error:
        raise WorkflowInputError(error.code, error.detail) from error
    if not report.is_acceptable:
        details = "; ".join(issue.code for issue in report.issues if issue.severity == "ERROR")
        raise WorkflowInputError("MOCKUP_QUALITY_REJECTED", details)
    if len(mockup.mockup.screens) < ARCHETYPES[choices.archetype].minimum_screens:
        raise WorkflowInputError("MOCKUP_SCREEN_COUNT")
    try:
        mockup.prototype()
    except (GeneratedMockupError, KeyError, TypeError, ValueError) as error:
        raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", str(error)) from error
    return report


@dataclass(frozen=True, slots=True)
class ProvidedPrototypeVersion:
    id: UUID
    code: str
    project_id: UUID
    version_number: int
    based_on_version_number: int | None
    definition_reference: Mapping[str, object]
    title: str
    declared_origin: str | None
    visual_choices: Mapping[str, str]
    mockup: BoundGeneratedMockup
    created_at: datetime
    original_reference: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID) or not isinstance(self.project_id, UUID):
            raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", "UUID identities")
        try:
            validate_display_code(self.code, prefix="PRT", label="provided prototype code")
            validate_positive_integer(self.version_number, label="provided prototype version")
            if self.based_on_version_number is not None:
                validate_positive_integer(
                    self.based_on_version_number, label="provided prototype base version"
                )
        except (TypeError, ValueError) as error:
            raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", str(error)) from error
        if (self.version_number == 1 and self.based_on_version_number is not None) or (
            self.version_number > 1 and self.based_on_version_number != self.version_number - 1
        ):
            raise WorkflowInputError("PROVIDED_PROTOTYPE_VERSION_BASE_INVALID")
        if _text(self.title, label="title") != self.title:
            raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", "canonical title")
        if (
            _text(self.declared_origin, label="declared origin", optional=True)
            != self.declared_origin
        ):
            raise WorkflowInputError(
                "PROVIDED_PROTOTYPE_INPUT_INVALID", "canonical declared origin"
            )
        if not isinstance(self.created_at, datetime) or self.created_at.utcoffset() is None:
            raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", "aware timestamp")
        if not isinstance(self.mockup, BoundGeneratedMockup):
            raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", "bound mockup required")
        if self.mockup.design_alternative_id != self.id:
            raise WorkflowInputError("PROVIDED_PROTOTYPE_IDENTITY_MISMATCH")
        if self.mockup.mockup.title != self.title:
            raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", "mockup title mismatch")
        object.__setattr__(self, "definition_reference", _reference(self.definition_reference))
        choices = _choices(self.visual_choices)
        object.__setattr__(self, "visual_choices", MappingProxyType(choices.to_snapshot()))
        if self.original_reference is not None:
            if not isinstance(self.original_reference, Mapping):
                raise WorkflowInputError("WORKFLOW_REFERENCE_INVALID")
            original = json.loads(canonical_workflow_json(self.original_reference))
            object.__setattr__(self, "original_reference", MappingProxyType(original))
        _quality(self.mockup, choices)

    def _payload(self) -> dict[str, object]:
        values: dict[str, object] = {
            "id": str(self.id),
            "code": self.code,
            "project_id": str(self.project_id),
            "version_number": self.version_number,
            "based_on_version_number": self.based_on_version_number,
            "definition_reference": dict(self.definition_reference),
            "title": self.title,
            "visual_choices": dict(self.visual_choices),
            "mockup": self.mockup.to_snapshot(),
            "created_at": self.created_at.isoformat(),
        }
        if self.declared_origin is not None:
            values["declared_origin"] = self.declared_origin
        if self.original_reference is not None:
            values["original_reference"] = dict(self.original_reference)
        return values

    @property
    def content_hash(self) -> str:
        return decision_content_hash(self._payload())

    @property
    def report(self) -> MockupReport:
        return _quality(self.mockup, _choices(self.visual_choices))

    def to_snapshot(self) -> dict[str, object]:
        return self._payload() | {"content_hash": self.content_hash}

    def canonical_json(self) -> str:
        return canonical_workflow_json(self.to_snapshot())


PrototypeVersion = ProvidedPrototypeVersion


def create_provided_prototype(
    *,
    prototype_id: UUID,
    code: str,
    project_id: UUID,
    version_number: int,
    based_on_version_number: int | None,
    definition_reference: object,
    title: str,
    visual_choices: Mapping[str, str],
    mockup: BoundGeneratedMockup,
    created_at: datetime,
    declared_origin: str | None = None,
    original_reference: Mapping[str, object] | None = None,
    requirement_ids_by_code: Mapping[str, UUID] | None = None,
) -> ProvidedPrototypeVersion:
    if not isinstance(created_at, datetime) or created_at.utcoffset() is None:
        raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", "aware timestamp")
    if not isinstance(mockup, BoundGeneratedMockup):
        raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", "bound mockup required")
    if requirement_ids_by_code is not None:
        actual = dict(mockup.requirement_ids_by_code)
        if any(requirement_ids_by_code.get(code) != value for code, value in actual.items()):
            raise WorkflowInputError("PROVIDED_PROTOTYPE_REQUIREMENT_REFERENCE_INVALID")
    return ProvidedPrototypeVersion(
        id=prototype_id,
        code=code,
        project_id=project_id,
        version_number=version_number,
        based_on_version_number=based_on_version_number,
        definition_reference=_reference(definition_reference),
        title=_text(title, label="title"),
        declared_origin=_text(declared_origin, label="declared origin", optional=True),
        visual_choices=visual_choices,
        mockup=mockup,
        created_at=created_at.astimezone(UTC),
        original_reference=original_reference,
    )


def provided_prototype_from_payload(
    payload: Mapping[str, object],
    *,
    prototype_id: UUID,
    code: str,
    project_id: UUID,
    version_number: int,
    based_on_version_number: int | None,
    definition_reference: object,
    requirement_ids_by_code: Mapping[str, UUID],
    created_at: datetime,
) -> ProvidedPrototypeVersion:
    if not isinstance(payload, Mapping) or not set(payload) >= {
        "title",
        "visual_choices",
        "mockup",
    }:
        raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", "prototype fields")
    if set(payload) - {"title", "declared_origin", "visual_choices", "mockup"}:
        raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", "unknown prototype fields")
    title = _text(payload["title"], label="title")
    choices = _choices(payload["visual_choices"])
    raw_mockup = payload["mockup"]
    if not isinstance(raw_mockup, Mapping) or not set(raw_mockup) >= {"styles", "screens"}:
        raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", "mockup fields")
    if set(raw_mockup) - {
        "styles",
        "screens",
        "title",
        "contract_version",
        "design_alternative_id",
    }:
        raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", "unknown mockup fields")
    if "title" in raw_mockup and _text(raw_mockup["title"], label="mockup title") != title:
        raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", "mockup title mismatch")
    if "design_alternative_id" in raw_mockup and raw_mockup["design_alternative_id"] != str(
        prototype_id
    ):
        raise WorkflowInputError("PROVIDED_PROTOTYPE_IDENTITY_MISMATCH")
    if "contract_version" in raw_mockup and (
        type(raw_mockup["contract_version"]) is not int or raw_mockup["contract_version"] != 1
    ):
        raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", "mockup contract version")
    try:
        generated = create_generated_mockup(
            design_alternative_id=prototype_id,
            title=title,
            styles=raw_mockup["styles"],
            screens=raw_mockup["screens"],
            token_names=resolve_visual_tokens(choices),
        )
        codes = markup_requirement_codes(generated)
        unknown = set(codes) - set(requirement_ids_by_code)
        if unknown:
            raise WorkflowInputError(
                "PROVIDED_PROTOTYPE_REQUIREMENT_REFERENCE_INVALID", ", ".join(sorted(unknown))
            )
        bound = create_bound_mockup(
            mockup=generated,
            requirement_ids_by_code={code: requirement_ids_by_code[code] for code in codes},
        )
    except GeneratedMockupError as error:
        raise WorkflowInputError(error.code, error.detail) from error
    except (TypeError, ValueError) as error:
        if isinstance(error, WorkflowInputError):
            raise
        raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", "mockup input") from error
    return create_provided_prototype(
        prototype_id=prototype_id,
        code=code,
        project_id=project_id,
        version_number=version_number,
        based_on_version_number=based_on_version_number,
        definition_reference=definition_reference,
        title=title,
        declared_origin=payload.get("declared_origin"),
        visual_choices=choices.to_snapshot(),
        mockup=bound,
        created_at=created_at,
        requirement_ids_by_code=requirement_ids_by_code,
    )


def provided_prototype_from_snapshot(payload: Mapping[str, object]) -> ProvidedPrototypeVersion:
    if not isinstance(payload, Mapping):
        raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID", "prototype snapshot")
    try:
        workflow_records(payload.get("project_id"), prototypes=[payload])
        choices = _choices(payload["visual_choices"])
        bound = bound_mockup_from_snapshot(
            payload["mockup"], token_names=resolve_visual_tokens(choices)
        )
        result = ProvidedPrototypeVersion(
            id=UUID(payload["id"]),
            code=payload["code"],
            project_id=UUID(payload["project_id"]),
            version_number=payload["version_number"],
            based_on_version_number=payload["based_on_version_number"],
            definition_reference=payload["definition_reference"],
            title=payload["title"],
            declared_origin=payload.get("declared_origin"),
            visual_choices=payload["visual_choices"],
            mockup=bound,
            created_at=datetime.fromisoformat(payload["created_at"]),
            original_reference=payload.get("original_reference"),
        )
    except GeneratedMockupError as error:
        raise WorkflowInputError(error.code, error.detail) from error
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, WorkflowInputError):
            raise
        raise WorkflowInputError(
            "PROVIDED_PROTOTYPE_INPUT_INVALID", "prototype snapshot"
        ) from error
    if result.to_snapshot() != dict(payload):
        raise WorkflowInputError("PROVIDED_PROTOTYPE_SNAPSHOT_NOT_CANONICAL")
    return result


__all__ = [
    "PrototypeVersion",
    "ProvidedPrototypeVersion",
    "create_provided_prototype",
    "provided_prototype_from_payload",
    "provided_prototype_from_snapshot",
]
