from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.projects.research_evidence import (
    EvidenceCitation,
    EvidenceStatus,
    EvidenceVersion,
)
from orchestwin.validation import ValidationError, validation_candidates


def _text(value, *, optional=False, limit=4000):
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValidationError("VALIDATION_INPUT_INVALID")
    value = value.strip()
    if not value and optional:
        return None
    if (
        not value
        or len(value) > limit
        or any(ord(char) < 32 and char not in "\n\t" for char in value)
    ):
        raise ValidationError("VALIDATION_INPUT_INVALID")
    return value


def _positive(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValidationError("VALIDATION_INPUT_INVALID")
    return value


def _reference(node):
    reference = node.get("reference", {})
    if (
        not reference.get("artifact_id")
        or not isinstance(reference.get("version_number"), int)
        or re.fullmatch(r"[a-f0-9]{64}", str(reference.get("content_hash"))) is None
    ):
        raise ValidationError("VALIDATION_CONTEXT_CHANGED")
    return dict(reference)


def _timestamp(moment):
    if not isinstance(moment, datetime) or moment.utcoffset() is None:
        raise ValidationError("VALIDATION_INPUT_INVALID")
    return moment.astimezone(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class HypothesisVersion:
    snapshot_json: str

    def __post_init__(self) -> None:
        _validate_snapshot(self.snapshot_json, hypothesis=True)

    def to_snapshot(self) -> dict:
        return json.loads(self.snapshot_json)

    @property
    def id(self) -> UUID:
        return UUID(self.to_snapshot()["id"])

    @property
    def content_hash(self) -> str:
        return self.to_snapshot()["content_hash"]

    @property
    def version_number(self) -> int:
        return self.to_snapshot()["version_number"]


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    snapshot_json: str

    def __post_init__(self) -> None:
        _validate_snapshot(self.snapshot_json, hypothesis=False)

    def to_snapshot(self) -> dict:
        return json.loads(self.snapshot_json)

    @property
    def id(self) -> UUID:
        return UUID(self.to_snapshot()["id"])

    @property
    def content_hash(self) -> str:
        return self.to_snapshot()["content_hash"]


def _record(cls, values):
    return cls(canonical_json({**values, "content_hash": snapshot_content_hash(values)}))


def _validate_snapshot(text, *, hypothesis):
    try:
        payload = json.loads(text)
        if not isinstance(payload, dict) or canonical_json(payload) != text:
            raise ValueError
        common = {"id", "code", "project_id", "owner_user_id", "limitations", "content_hash"}
        fields = (
            {
                "version_number",
                "based_on_version_number",
                "origin_key",
                "origin_reference",
                "origin_kind",
                "twin_key",
                "twin_reference",
                "scenario_key",
                "scenario_reference",
                "design_key",
                "design_reference",
                "alternative_id",
                "anchor_keys",
                "mockup_references",
                "question",
                "task",
                "observe",
                "created_at",
            }
            if hypothesis
            else {
                "hypothesis_id",
                "hypothesis_version_number",
                "hypothesis_content_hash",
                "session_ref",
                "session_kind",
                "outcome",
                "coverage",
                "evidence_id",
                "evidence_version",
                "evidence_content_hash",
                "citation",
                "recorded_at",
            }
        )
        if set(payload) != common | fields:
            raise ValueError
        values = {key: value for key, value in payload.items() if key != "content_hash"}
        if payload.get("content_hash") != snapshot_content_hash(values):
            raise ValueError
        for field in ("id", "project_id", "owner_user_id"):
            if str(UUID(payload[field])) != payload[field]:
                raise ValueError
        if _text(payload["limitations"]) != payload["limitations"]:
            raise ValueError
        moment = datetime.fromisoformat(payload["created_at" if hypothesis else "recorded_at"])
        if _timestamp(moment) != payload["created_at" if hypothesis else "recorded_at"]:
            raise ValueError
        if hypothesis:
            _positive(payload["version_number"])
            if re.fullmatch(r"HYP-[0-9]{3,6}", payload["code"]) is None:
                raise ValueError
            if not payload["question"] and not payload["task"]:
                raise ValueError
            for field in ("question", "task"):
                if _text(payload[field], optional=True) != payload[field]:
                    raise ValueError
            if (
                not isinstance(payload["observe"], list)
                or not 1 <= len(payload["observe"]) <= 24
                or any(_text(value, limit=500) != value for value in payload["observe"])
            ):
                raise ValueError
            base = payload["based_on_version_number"]
            if (payload["version_number"] == 1 and base is not None) or (
                payload["version_number"] > 1 and base != payload["version_number"] - 1
            ):
                raise ValueError
            for prefix in ("origin", "twin", "scenario", "design"):
                _text(payload[f"{prefix}_key"], limit=2048)
                _reference({"reference": payload[f"{prefix}_reference"]})
            if not isinstance(payload["anchor_keys"], list) or any(
                not isinstance(key, str) for key in payload["anchor_keys"]
            ):
                raise ValueError
            if not isinstance(payload["mockup_references"], list) or payload["origin_kind"] in {
                "USER_TWIN",
                "VALIDATION_HYPOTHESIS",
                "VALIDATION_OUTCOME",
            }:
                raise ValueError
        else:
            UUID(payload["hypothesis_id"])
            UUID(payload["evidence_id"])
            _positive(payload["hypothesis_version_number"])
            _positive(payload["evidence_version"])
            if any(
                re.fullmatch(r"[a-f0-9]{64}", payload[field]) is None
                for field in ("hypothesis_content_hash", "evidence_content_hash")
            ):
                raise ValueError
            if (
                re.fullmatch(r"HVO-[0-9]{3,6}", payload["code"]) is None
                or re.fullmatch(
                    r"(?:SES|SESSION|SYN|TEST)-[A-Za-z0-9_.:-]{1,70}", payload["session_ref"]
                )
                is None
            ):
                raise ValueError
            if (
                payload["session_kind"] not in {"HUMAN_SESSION", "SYNTHETIC_EXERCISE"}
                or payload["outcome"] not in {"CONFIRMED", "REFUTED", "UNCERTAIN"}
                or payload["coverage"] not in {"COMPLETE", "PARTIAL"}
            ):
                raise ValueError
            citation = EvidenceCitation.from_snapshot(payload["citation"])
            if (
                str(citation.source_id) != payload["evidence_id"]
                or citation.source_version != payload["evidence_version"]
                or citation.content_hash != payload["evidence_content_hash"]
            ):
                raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValidationError("VALIDATION_STORED_SNAPSHOT_INVALID") from None


def _restore(cls, payload):
    values = dict(payload)
    digest = values.pop("content_hash", None)
    if digest != snapshot_content_hash(values):
        raise ValidationError("VALIDATION_STORED_SNAPSHOT_INVALID")
    return cls(canonical_json(dict(payload)))


def hypothesis_from_snapshot(payload: Mapping) -> HypothesisVersion:
    return _restore(HypothesisVersion, payload)


def outcome_from_snapshot(payload: Mapping) -> ValidationOutcome:
    return _restore(ValidationOutcome, payload)


def validate_session_source(session_kind: str, source: Mapping) -> None:
    if session_kind == "HUMAN_SESSION":
        if (
            source.get("source_kind") != "EMPIRICAL_RESEARCH"
            or source.get("empirical") is not True
            or not all(
                isinstance(source.get(field), str) and source[field].strip()
                for field in ("context", "method", "limitations")
            )
        ):
            raise ValidationError("VALIDATION_SESSION_SOURCE_INVALID")
    elif session_kind == "SYNTHETIC_EXERCISE":
        if (
            source.get("empirical") is not False
            or source.get("source_kind") == "EMPIRICAL_RESEARCH"
            or not isinstance(source.get("limitations"), str)
            or not source["limitations"].strip()
        ):
            raise ValidationError("VALIDATION_SESSION_SOURCE_INVALID")
    else:
        raise ValidationError("VALIDATION_INPUT_INVALID")


def create_hypothesis(
    *,
    document: Mapping,
    project_id: UUID,
    owner_user_id: UUID,
    request: Mapping,
    code: str,
    created_at: datetime,
    hypothesis_id: UUID | None = None,
    version_number: int = 1,
    based_on_version_number: int | None = None,
) -> HypothesisVersion:
    for field in ("candidate_key", "twin_key", "scenario_key", "design_key"):
        _text(request.get(field), limit=2048)
    question, task = (
        _text(request.get("question"), optional=True),
        _text(request.get("task"), optional=True),
    )
    if not question and not task:
        raise ValidationError("VALIDATION_INPUT_INVALID")
    observe = request.get("observe")
    if not isinstance(observe, list) or not 1 <= len(observe) <= 24:
        raise ValidationError("VALIDATION_INPUT_INVALID")
    observe = [_text(value, limit=500) for value in observe]
    limitations = _text(request.get("limitations"))
    candidates = {item["key"]: item for item in validation_candidates(document)}
    candidate = candidates.get(request.get("candidate_key"))
    if candidate is None or document.get("project_id") != str(project_id):
        raise ValidationError("VALIDATION_CONTEXT_CHANGED")
    nodes = {item["key"]: item for item in document.get("nodes", ())}
    selections = {}
    for field, kinds in (
        ("twin_key", {"USER_TWIN"}),
        ("scenario_key", {"SCENARIO"}),
        (
            "design_key",
            {"DESIGN_PACKAGE", "DESIGN_ALTERNATIVE", "PROTOTYPE_SCREEN", "PROTOTYPE_ELEMENT"},
        ),
    ):
        node = nodes.get(request.get(field))
        if node is None or node.get("kind") not in kinds or not node.get("current", True):
            raise ValidationError("VALIDATION_CONTEXT_CHANGED")
        selections[field] = node
    twin, scenario, design = (
        selections[field] for field in ("twin_key", "scenario_key", "design_key")
    )
    if not any(item["key"] == twin["key"] for item in candidate["twin_references"]):
        raise ValidationError("VALIDATION_CONTEXT_CHANGED")
    if not any(
        link.get("source") == scenario["key"]
        and link.get("target") == twin["key"]
        and link.get("kind") == "ACTOR"
        for link in document.get("links", ())
    ):
        raise ValidationError("VALIDATION_CONTEXT_CHANGED")
    alternative_id = request.get("alternative_id")
    if alternative_id is not None:
        alternative_id = _text(alternative_id, limit=80)
        alternatives = [
            item
            for item in nodes.values()
            if item.get("kind") == "DESIGN_ALTERNATIVE"
            and item.get("current", True)
            and item.get("reference", {}).get("artifact_id") == alternative_id
        ]
        if len(alternatives) != 1:
            raise ValidationError("VALIDATION_CONTEXT_CHANGED")
        alternative = alternatives[0]
        if design["kind"] == "DESIGN_ALTERNATIVE" and design["key"] != alternative["key"]:
            raise ValidationError("VALIDATION_CONTEXT_CHANGED")
        if (
            design["reference"]["content_hash"] != alternative["reference"]["content_hash"]
            and design.get("declared_context", {}).get("mockup", {}).get("alternative_id")
            != alternative_id
        ):
            raise ValidationError("VALIDATION_CONTEXT_CHANGED")
    anchor_keys = request.get("anchor_keys", [])
    if (
        not isinstance(anchor_keys, list)
        or len(anchor_keys) > 100
        or any(not isinstance(key, str) for key in anchor_keys)
        or len(set(anchor_keys)) != len(anchor_keys)
    ):
        raise ValidationError("VALIDATION_INPUT_INVALID")
    anchors = []
    for key in anchor_keys:
        anchor = nodes.get(key)
        if (
            anchor is None
            or anchor.get("kind") != "PROTOTYPE_ELEMENT"
            or not anchor.get("current", True)
        ):
            raise ValidationError("VALIDATION_CONTEXT_CHANGED")
        mockup = anchor.get("declared_context", {}).get("mockup", {})
        if alternative_id is not None and mockup.get("alternative_id") != alternative_id:
            raise ValidationError("VALIDATION_CONTEXT_CHANGED")
        design_reference = _reference(design)
        base = anchor.get("declared_context", {}).get("base_reference", anchor.get("reference", {}))
        if (
            base.get("content_hash") != design_reference["content_hash"]
            and anchor.get("reference", {}).get("content_hash") != design_reference["content_hash"]
        ):
            raise ValidationError("VALIDATION_CONTEXT_CHANGED")
        anchors.append({"key": key, "reference": _reference(anchor), "mockup": dict(mockup)})
    if re.fullmatch(r"HYP-[0-9]{3,6}", code) is None:
        raise ValidationError("VALIDATION_INPUT_INVALID")
    _positive(version_number)
    if (version_number == 1 and based_on_version_number is not None) or (
        version_number > 1 and based_on_version_number != version_number - 1
    ):
        raise ValidationError("HYPOTHESIS_VERSION_CONFLICT")
    origin = candidate["origin"]
    return _record(
        HypothesisVersion,
        {
            "id": str(hypothesis_id or uuid4()),
            "code": code,
            "version_number": version_number,
            "based_on_version_number": based_on_version_number,
            "project_id": str(project_id),
            "owner_user_id": str(owner_user_id),
            "origin_key": origin["key"],
            "origin_reference": _reference(origin),
            "origin_kind": origin["kind"],
            "twin_key": twin["key"],
            "twin_reference": _reference(twin),
            "scenario_key": scenario["key"],
            "scenario_reference": _reference(scenario),
            "design_key": design["key"],
            "design_reference": _reference(design),
            "alternative_id": alternative_id,
            "anchor_keys": anchor_keys,
            "mockup_references": anchors,
            "question": question,
            "task": task,
            "observe": observe,
            "limitations": limitations,
            "created_at": _timestamp(created_at),
        },
    )


def create_outcome(
    *,
    hypothesis: HypothesisVersion,
    source: EvidenceVersion,
    text: str | None,
    project_id: UUID,
    owner_user_id: UUID,
    request: Mapping,
    code: str,
    recorded_at: datetime,
    outcome_id: UUID | None = None,
) -> ValidationOutcome:
    _positive(request.get("hypothesis_version_number"))
    _positive(request.get("evidence_version"))
    values = hypothesis.to_snapshot()
    if values["project_id"] != str(project_id) or values["owner_user_id"] != str(owner_user_id):
        raise ValidationError("HYPOTHESIS_NOT_FOUND")
    if (
        str(request.get("hypothesis_id")) != str(hypothesis.id)
        or request.get("hypothesis_version_number") != hypothesis.version_number
        or request.get("hypothesis_content_hash") != hypothesis.content_hash
    ):
        raise ValidationError("HYPOTHESIS_VERSION_CONFLICT")
    if (
        str(request.get("evidence_id")) != str(source.id)
        or request.get("evidence_version") != source.version
    ):
        raise ValidationError("VALIDATION_CONTEXT_CHANGED")
    if source.status is EvidenceStatus.RETIRED:
        raise ValidationError("VALIDATION_SOURCE_RETIRED")
    if text is None:
        raise ValidationError("VALIDATION_SOURCE_TEXT_UNAVAILABLE")
    session_kind, outcome, coverage = (
        request.get(field) for field in ("session_kind", "outcome", "coverage")
    )
    if not all(isinstance(value, str) for value in (session_kind, outcome, coverage)):
        raise ValidationError("VALIDATION_INPUT_INVALID")
    if (
        session_kind not in {"HUMAN_SESSION", "SYNTHETIC_EXERCISE"}
        or outcome not in {"CONFIRMED", "REFUTED", "UNCERTAIN"}
        or coverage not in {"COMPLETE", "PARTIAL"}
    ):
        raise ValidationError("VALIDATION_INPUT_INVALID")
    validate_session_source(session_kind, source.to_snapshot())
    session_ref = _text(request.get("session_ref"), limit=80)
    if re.fullmatch(r"(?:SES|SESSION|SYN|TEST)-[A-Za-z0-9_.:-]{1,70}", session_ref) is None:
        raise ValidationError("VALIDATION_INPUT_INVALID")
    limitations = _text(request.get("limitations"))
    quote = request.get("quote")
    line = request.get("line")
    if (
        not isinstance(quote, str)
        or not 1 <= len(quote) <= 1000
        or isinstance(line, bool)
        or not isinstance(line, int)
        or line < 1
    ):
        raise ValidationError("VALIDATION_CITATION_INVALID")
    matches = []
    start = text.find(quote)
    while start >= 0:
        if text.count("\n", 0, start) + 1 == line:
            matches.append(start)
        start = text.find(quote, start + 1)
    if len(matches) != 1:
        raise ValidationError("VALIDATION_CITATION_INVALID")
    start, end = matches[0], matches[0] + len(quote)
    citation = EvidenceCitation(
        source.id,
        source.version,
        source.content_hash,
        quote,
        start,
        end,
        line,
        text.count("\n", 0, end - 1) + 1,
    )
    if not citation.verify(text):
        raise ValidationError("VALIDATION_CITATION_INVALID")
    if re.fullmatch(r"HVO-[0-9]{3,6}", code) is None:
        raise ValidationError("VALIDATION_INPUT_INVALID")
    return _record(
        ValidationOutcome,
        {
            "id": str(outcome_id or uuid4()),
            "code": code,
            "project_id": str(project_id),
            "owner_user_id": str(owner_user_id),
            "hypothesis_id": str(hypothesis.id),
            "hypothesis_version_number": hypothesis.version_number,
            "hypothesis_content_hash": hypothesis.content_hash,
            "session_ref": session_ref,
            "session_kind": session_kind,
            "outcome": outcome,
            "coverage": coverage,
            "limitations": limitations,
            "evidence_id": str(source.id),
            "evidence_version": source.version,
            "evidence_content_hash": source.content_hash,
            "citation": citation.to_snapshot(),
            "recorded_at": _timestamp(recorded_at),
        },
    )


__all__ = [
    "HypothesisVersion",
    "ValidationOutcome",
    "create_hypothesis",
    "create_outcome",
    "hypothesis_from_snapshot",
    "outcome_from_snapshot",
    "validate_session_source",
]
