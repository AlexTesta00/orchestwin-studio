from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Final
from uuid import UUID

WORKFLOW_TARGETS: Final = (
    "BRIEF",
    "TEAM",
    "USER_TWINS",
    "EVIDENCE",
    "SCENARIOS",
    "NEEDS",
    "REQUIREMENTS",
    "JOURNEYS",
    "DESIGN",
    "EVALUATION",
    "PACKAGE",
)
WORKFLOW_ACTIONS: Final = ("DECLARE_MISSING", "RESOLVE_MISSING")
PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE: Final = "PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE"
PROVIDED_PROTOTYPE_CODE_UNAVAILABLE: Final = "PROVIDED_PROTOTYPE_CODE_UNAVAILABLE"
PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE: Final = "PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE"
PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE: Final = "PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE"
PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE: Final = "PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE"
PROVIDED_PROTOTYPE_LIMITS: Final = (
    PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE,
    PROVIDED_PROTOTYPE_CODE_UNAVAILABLE,
    PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE,
    PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE,
    PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE,
)
PROVIDED_PROTOTYPE_LIMIT_MESSAGES: Final = MappingProxyType(
    {
        "it": MappingProxyType(
            {
                PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE: "La revisione sintetica non è disponibile per il prototipo fornito.",
                PROVIDED_PROTOTYPE_CODE_UNAVAILABLE: "La generazione del codice non è disponibile per il prototipo fornito.",
                PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE: "Il percorso dello scenario non è disponibile per il prototipo fornito.",
                PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE: "Questa operazione non è disponibile per il prototipo fornito.",
                PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE: "La valutazione dei twin non è disponibile per il prototipo fornito. La struttura dei mockup è conservata per un collegamento futuro.",
            }
        ),
        "en": MappingProxyType(
            {
                PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE: "Synthetic review is unavailable for a supplied prototype.",
                PROVIDED_PROTOTYPE_CODE_UNAVAILABLE: "Code generation is unavailable for a supplied prototype.",
                PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE: "Scenario walkthrough is unavailable for a supplied prototype.",
                PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE: "This operation is unavailable for a supplied prototype.",
                PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE: "Twin evaluation is unavailable for a supplied prototype. The mockup structure is preserved for a future integration.",
            }
        ),
    }
)
_SHA256: Final = re.compile(r"[a-f0-9]{64}")
_DECISION_FIELDS: Final = frozenset(
    {
        "id",
        "project_id",
        "sequence",
        "target",
        "action",
        "reason",
        "base_context",
        "recorded_at",
        "content_hash",
    }
)
_PROTOTYPE_FIELDS: Final = frozenset(
    {
        "id",
        "code",
        "project_id",
        "version_number",
        "based_on_version_number",
        "definition_reference",
        "title",
        "visual_choices",
        "mockup",
        "created_at",
        "content_hash",
    }
)


class WorkflowInputError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code
        self.detail = detail


def canonical_workflow_json(payload: Mapping[str, object]) -> str:
    try:
        return json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "JSON data required") from error


def decision_content_hash(payload: Mapping[str, object]) -> str:
    content = {key: value for key, value in payload.items() if key != "content_hash"}
    return hashlib.sha256(canonical_workflow_json(content).encode("utf-8")).hexdigest()


def _uuid(value: object) -> str:
    if not isinstance(value, str):
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "UUID text required")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "invalid UUID") from error
    if str(parsed) != value:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "canonical UUID required")
    return value


def _positive(value: object) -> int:
    if type(value) is not int or value < 1:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "positive integer required")
    return value


def _hash(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "SHA-256 required")
    return value


def _timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "timestamp text required")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "invalid timestamp") from error
    if parsed.utcoffset() is None:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "aware timestamp required")
    return value


def normalize_workflow_reason(value: object) -> str:
    if not isinstance(value, str):
        raise WorkflowInputError("WORKFLOW_REASON_INVALID")
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if (
        not value
        or len(value) > 4000
        or any(ord(character) < 32 and character not in "\n\t" for character in value)
    ):
        raise WorkflowInputError("WORKFLOW_REASON_INVALID")
    return value


def validate_workflow_reference(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise WorkflowInputError("WORKFLOW_REFERENCE_INVALID")
    if not {"artifact_id", "version_number", "content_hash"} <= set(value):
        raise WorkflowInputError("WORKFLOW_REFERENCE_INVALID")
    if set(value) - {"artifact_id", "version_number", "content_hash", "kind"}:
        raise WorkflowInputError("WORKFLOW_REFERENCE_INVALID")
    _uuid(value["artifact_id"])
    _positive(value["version_number"])
    _hash(value["content_hash"])
    if "kind" in value and (not isinstance(value["kind"], str) or not value["kind"]):
        raise WorkflowInputError("WORKFLOW_REFERENCE_INVALID")
    return dict(value)


def _origin(value: object) -> None:
    if not isinstance(value, Mapping) or not value:
        raise WorkflowInputError("WORKFLOW_REFERENCE_INVALID")
    for key in ("id", "artifact_id", "project_id"):
        if key in value:
            _uuid(value[key])
    for key in ("sequence", "version_number"):
        if key in value:
            _positive(value[key])
    if "content_hash" in value:
        _hash(value["content_hash"])
    canonical_workflow_json(value)


def _validate_decision(value: object, project_id: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or not set(value) >= _DECISION_FIELDS:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "decision fields")
    if set(value) - _DECISION_FIELDS - {"origin_reference"}:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "unknown decision fields")
    _uuid(value["id"])
    if _uuid(value["project_id"]) != project_id:
        raise WorkflowInputError("WORKFLOW_PROJECT_MISMATCH")
    _positive(value["sequence"])
    if value["target"] not in WORKFLOW_TARGETS:
        raise WorkflowInputError("WORKFLOW_TARGET_INVALID")
    if value["action"] not in WORKFLOW_ACTIONS:
        raise WorkflowInputError("WORKFLOW_ACTION_INVALID")
    if normalize_workflow_reason(value["reason"]) != value["reason"]:
        raise WorkflowInputError("WORKFLOW_REASON_INVALID", "reason is not canonical")
    context = value["base_context"]
    if not isinstance(context, Mapping) or set(context) - set(WORKFLOW_TARGETS):
        raise WorkflowInputError("WORKFLOW_REFERENCE_INVALID", "base context")
    for reference in context.values():
        validate_workflow_reference(reference)
    _timestamp(value["recorded_at"])
    if "origin_reference" in value:
        _origin(value["origin_reference"])
    if _hash(value["content_hash"]) != decision_content_hash(value):
        raise WorkflowInputError("WORKFLOW_HASH_MISMATCH")
    return dict(value)


def _validate_prototype(value: object, project_id: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or not set(value) >= _PROTOTYPE_FIELDS:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "prototype fields")
    if set(value) - _PROTOTYPE_FIELDS - {"declared_origin", "original_reference"}:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "unknown prototype fields")
    _uuid(value["id"])
    if _uuid(value["project_id"]) != project_id:
        raise WorkflowInputError("WORKFLOW_PROJECT_MISMATCH")
    if not isinstance(value["code"], str) or re.fullmatch(r"PRT-[0-9]{3,6}", value["code"]) is None:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "prototype code")
    version = _positive(value["version_number"])
    base = value["based_on_version_number"]
    if (version == 1 and base is not None) or (version > 1 and base != version - 1):
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "prototype version base")
    if base is not None:
        _positive(base)
    validate_workflow_reference(value["definition_reference"])
    for name in ("title", "declared_origin"):
        if name in value and (
            not isinstance(value[name], str) or not value[name].strip() or len(value[name]) > 200
        ):
            raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", name)
    choices = value["visual_choices"]
    if (
        not isinstance(choices, Mapping)
        or not choices
        or not all(isinstance(key, str) and isinstance(item, str) for key, item in choices.items())
    ):
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "visual choices")
    mockup = value["mockup"]
    if not isinstance(mockup, Mapping) or set(mockup) != {"mockup", "requirement_ids_by_code"}:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "bound mockup")
    raw_mockup = mockup["mockup"]
    if not isinstance(raw_mockup, Mapping) or set(raw_mockup) != {
        "contract_version",
        "design_alternative_id",
        "title",
        "styles",
        "screens",
    }:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "mockup fields")
    if raw_mockup.get("design_alternative_id") != value["id"]:
        raise WorkflowInputError("WORKFLOW_REFERENCE_INVALID", "prototype mockup identity")
    if type(raw_mockup["contract_version"]) is not int or raw_mockup["contract_version"] != 1:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "mockup contract version")
    if raw_mockup["title"] != value["title"] or not isinstance(raw_mockup["styles"], str):
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "mockup values")
    screens = raw_mockup["screens"]
    if not isinstance(screens, list) or not 2 <= len(screens) <= 8:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "mockup screens")
    for index, screen in enumerate(screens, start=1):
        if (
            not isinstance(screen, Mapping)
            or set(screen) != {"code", "title", "state", "markup"}
            or not all(isinstance(item, str) for item in screen.values())
            or screen["code"] != f"SCR-{index:03d}"
        ):
            raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "mockup screen fields")
    requirements = mockup["requirement_ids_by_code"]
    if not isinstance(requirements, Mapping):
        raise WorkflowInputError("WORKFLOW_REFERENCE_INVALID", "requirement bindings")
    for identifier in requirements.values():
        _uuid(identifier)
    if not all(isinstance(code, str) for code in requirements):
        raise WorkflowInputError("WORKFLOW_REFERENCE_INVALID", "requirement codes")
    if len(set(requirements.values())) != len(requirements):
        raise WorkflowInputError("WORKFLOW_REFERENCE_INVALID", "duplicate requirement identity")
    _timestamp(value["created_at"])
    if "original_reference" in value:
        _origin(value["original_reference"])
    if _hash(value["content_hash"]) != decision_content_hash(value):
        raise WorkflowInputError("WORKFLOW_HASH_MISMATCH")
    return dict(value)


def create_workflow_decision(
    *,
    decision_id: UUID,
    project_id: UUID,
    sequence: int,
    target: str,
    action: str,
    reason: str,
    base_context: Mapping[str, object],
    recorded_at: datetime,
    origin_reference: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if not isinstance(recorded_at, datetime) or recorded_at.utcoffset() is None:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "aware timestamp required")
    payload: dict[str, object] = {
        "id": str(decision_id),
        "project_id": str(project_id),
        "sequence": sequence,
        "target": target,
        "action": action,
        "reason": normalize_workflow_reason(reason),
        "base_context": dict(base_context),
        "recorded_at": recorded_at.astimezone(UTC).isoformat(),
    }
    if origin_reference is not None:
        payload["origin_reference"] = dict(origin_reference)
    payload["content_hash"] = decision_content_hash(payload)
    return _validate_decision(payload, str(project_id))


def validate_workflow_records(payload: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(payload, Mapping) or set(payload) != {
        "kind",
        "schema_version",
        "project_id",
        "decisions",
        "prototypes",
        "limits",
    }:
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "envelope fields")
    if (
        payload["kind"] != "orchestwin.workflow-inputs"
        or type(payload["schema_version"]) is not int
    ):
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "envelope kind or schema")
    if payload["schema_version"] != 1:
        raise WorkflowInputError("WORKFLOW_SCHEMA_UNSUPPORTED")
    project_id = _uuid(payload["project_id"])
    if not isinstance(payload["decisions"], list) or not isinstance(payload["prototypes"], list):
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "record arrays")
    decisions = [_validate_decision(value, project_id) for value in payload["decisions"]]
    prototypes = [_validate_prototype(value, project_id) for value in payload["prototypes"]]
    sequences = [value["sequence"] for value in decisions]
    if sequences != sorted(set(sequences)):
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "decision sequence order")
    if len({value["id"] for value in decisions}) != len(decisions):
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "duplicate decision identity")
    versions = [(value["id"], value["version_number"]) for value in prototypes]
    if len(set(versions)) != len(versions):
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "duplicate prototype version")
    if payload["limits"] != list(PROVIDED_PROTOTYPE_LIMITS if prototypes else ()):
        raise WorkflowInputError("WORKFLOW_RECORDS_INVALID", "declared limits")
    return json.loads(canonical_workflow_json(payload))


def workflow_records(
    project_id: UUID | str,
    decisions: Iterable[Mapping[str, object]] = (),
    prototypes: Iterable[Mapping[str, object]] = (),
) -> dict[str, object]:
    prototype_records = [dict(value) for value in prototypes]
    return validate_workflow_records(
        {
            "kind": "orchestwin.workflow-inputs",
            "schema_version": 1,
            "project_id": str(project_id),
            "decisions": [dict(value) for value in decisions],
            "prototypes": prototype_records,
            "limits": list(PROVIDED_PROTOTYPE_LIMITS if prototype_records else ()),
        }
    )


__all__ = [
    "PROVIDED_PROTOTYPE_CODE_UNAVAILABLE",
    "PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE",
    "PROVIDED_PROTOTYPE_LIMITS",
    "PROVIDED_PROTOTYPE_LIMIT_MESSAGES",
    "PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE",
    "PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE",
    "PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE",
    "WORKFLOW_ACTIONS",
    "WORKFLOW_TARGETS",
    "WorkflowInputError",
    "canonical_workflow_json",
    "create_workflow_decision",
    "decision_content_hash",
    "normalize_workflow_reason",
    "validate_workflow_records",
    "validate_workflow_reference",
    "workflow_records",
]
