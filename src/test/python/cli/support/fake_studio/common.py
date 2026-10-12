from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    AgentIdentifier,
)
from orchestwin.agents.persistence.repositories import proposal_from_snapshot
from orchestwin.agents.selection_rules import (
    DeterministicTeamConstraints,
    RuleEvidence,
    TeamRoleConstraint,
    TeamRoleConstraintKind,
    TeamSelectionIssue,
    TeamSelectionIssueCode,
    TeamSelectionReason,
    TeamSelectionReasonCode,
)
from orchestwin.api.requirements import RequirementsSpecificationPayload
from orchestwin.artifacts.design_change_targets import DesignChangeTargetError
from orchestwin.artifacts.generated_mockup_review import (
    MockupIssueSeverity,
    review_generated_mockup,
)
from orchestwin.artifacts.generated_mockups import GeneratedMockup, generated_mockup_from_snapshot
from orchestwin.artifacts.visual_catalog import MODES, ColorMode, VisualChoices
from orchestwin.knowledge.state import MAX_FINDINGS, MAX_TASK_LENGTH
from orchestwin.models.design_change import (
    MAX_TARGET_ELEMENTS,
    MIN_TARGET_ELEMENTS,
    TARGET_PART_FIELDS,
    DesignChangeTarget,
    DesignChangeTargetElement,
    target_html,
    target_label,
    target_view,
)
from orchestwin.models.design_change import TARGET_FIELDS as CHANGE_TARGET_FIELDS
from orchestwin.projects.briefs import BriefField
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.progress import ArtifactVersion
from orchestwin.twins.persistence.snapshots import (
    persona_profile_from_snapshot,
    user_twin_profile_from_snapshot,
)
from orchestwin.twins.personas import PersonaProfileVersion
from orchestwin.twins.user_twins import (
    UserTwinProfileVersion,
    VersionedArtifactReference,
    create_user_modeling_snapshot,
)
from orchestwin.workflow.gates import GateArtifactReference, HumanGate, HumanGateEvent

from .texts import ALIGNMENT_TEXTS, LAX_BOOLEANS
from .values import CUT_MARK, ELEMENT_CODE, SCREEN_CODE, _Invalid, _Refusal

if TYPE_CHECKING:
    from .fields import _Call, _Fields


CITED_KEYS = ("requirement_ids", "user_story_ids", "acceptance_criterion_ids")
FIRST_LINE_LENGTH = 120


def _error(location: Sequence[object], kind: str) -> dict[str, object]:
    return {"loc": list(location), "type": kind}


def _control_free(value: str) -> bool:
    return all(ord(character) >= 32 and ord(character) != 127 for character in value)


def _single_line(value: object) -> str:
    normalized = " ".join(str(value).split())
    if not normalized or not _control_free(normalized):
        raise ValueError("the text must be one visible line")
    return normalized


def _optional_line(value: object) -> str | None:
    return None if value is None or not str(value).strip() else _single_line(value)


def _changed_path(value: object) -> str:
    path = str(value)
    if not path.strip() or not _control_free(path):
        raise ValueError("the path must be visible")
    return path


def _lax_boolean(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        return LAX_BOOLEANS.get(value.lower())
    return None


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _copy(value: object) -> object:
    return json.loads(json.dumps(value))


def _identifiers(items: Sequence[Mapping[str, object]]) -> list[str]:
    return sorted(str(item["id"]) for item in items)


def _bounded(value: str, maximum: int = 120) -> str:
    return value if len(value) <= maximum else f"{value[: maximum - 3].rstrip()}..."


def _first_screen(package: Mapping[str, object]) -> str:
    prototype = package.get("prototype")
    screens = [] if prototype is None else prototype["screens"]
    return str(screens[0]["code"]) if screens else "SCR-001"


def _first_line(message: str) -> str:
    line = next((" ".join(item.split()) for item in message.splitlines() if item.strip()), "")
    return _bounded(line, FIRST_LINE_LENGTH)


def _first_goal(twin: Mapping[str, object]) -> str:
    for item in twin["profile"]["observations"]:
        goals = item["value"]["items"]
        if item["observation_key"] == "user_twin.goals" and goals:
            return str(goals[0])
    return str(twin["profile"]["name"])


def _findings_by_twin(critiques: Sequence[Mapping[str, object]]) -> dict[str, list[str]]:
    return {
        str(critique["twin_id"]): [str(item["text"]) for item in critique["findings"]][
            :MAX_FINDINGS
        ]
        for critique in critiques
    }


def _critique_of(
    document: Mapping[str, object] | None, twin_id: object
) -> dict[str, object] | None:
    if document is None:
        return None
    return next((item for item in document["critiques"] if item["twin_id"] == twin_id), None)


def _code_number(code: object) -> int:
    return int(str(code).split("-", 1)[1])


def _listed(value: object) -> list[str]:
    return [] if value is None else [str(value)]


def _task_origin(
    kind: str,
    *,
    commit: str | None = None,
    test_run_id: str | None = None,
    twin_id: str | None = None,
    twin_name: str | None = None,
    finding: str | None = None,
) -> dict[str, object]:
    return {
        "kind": kind,
        "commit": commit,
        "test_run_id": test_run_id,
        "twin_id": twin_id,
        "twin_name": twin_name,
        "finding": finding,
    }


def _prepared_task(text: str | None, resolved: Mapping[str, object]) -> dict[str, object]:
    finding = resolved["finding"]
    if finding is None:
        return {
            "text": text,
            "about": {"requirements": [], "screens": [], "criteria": []},
            "origin": resolved["origin"],
        }
    about = finding["about"]
    action = finding["action"]
    written = " ".join(str(action if action and action.strip() else finding["text"]).split())
    if len(written) > MAX_TASK_LENGTH:
        written = written[: MAX_TASK_LENGTH - len(CUT_MARK)].rstrip() + CUT_MARK
    return {
        "text": written if text is None else text,
        "about": {
            "requirements": _listed(about.get("requirement")),
            "screens": _listed(about.get("screen")),
            "criteria": _listed(about.get("criterion")),
        },
        "origin": resolved["origin"],
    }


def _models(
    fields: _Fields,
    name: str,
    allowed: Sequence[str],
    parse: Callable[[_Fields], dict[str, object]],
    *,
    required: bool = True,
    nullable: bool = False,
    minimum_items: int = 0,
    maximum_items: int | None = None,
) -> list[dict[str, object]]:
    found = []
    items = fields.children(
        name,
        allowed,
        required=required,
        nullable=nullable,
        minimum_items=minimum_items,
        maximum_items=maximum_items,
    )
    for item in items or []:
        found.append(parse(item))
        fields.adopt(item)
    return found


def _model_rule(fields: _Fields, rule: Callable[[], object]) -> None:
    if fields.errors:
        return
    try:
        rule()
    except ValueError:
        fields.errors.append(_error(fields.location, "value_error"))


def _distinct(values: Iterable[object]) -> None:
    listed = list(values)
    if len(set(listed)) != len(listed):
        raise ValueError("the values must not repeat")


def _by_id(items: Sequence[Mapping[str, object]], identifier: str) -> dict | None:
    return next((item for item in items if str(item.get("id")) == identifier), None)


def _submission_status(status: str) -> int:
    if status == "SUBMITTED":
        return 201
    if status in {"ALREADY_PENDING", "ALREADY_APPROVED"}:
        return 200
    return 409


def _blank_to_none(reason: str | None) -> str | None:
    normalized = " ".join((reason or "").split())
    return normalized or None


def _artifact_version(artifact: Mapping[str, object]) -> ArtifactVersion:
    return ArtifactVersion(
        UUID(str(artifact["id"])), int(artifact["version_number"]), str(artifact["content_hash"])
    )


def _reference_version(reference: Mapping[str, object]) -> ArtifactVersion:
    return ArtifactVersion(
        UUID(str(reference["artifact_id"])),
        int(reference["version_number"]),
        str(reference["content_hash"]),
    )


def _plain_reference(artifact: Mapping[str, object]) -> dict[str, object]:
    return {
        "artifact_id": artifact["id"],
        "version_number": artifact["version_number"],
        "content_hash": artifact["content_hash"],
    }


def _key(artifact: Mapping[str, object] | None) -> tuple[str, int, str] | None:
    if artifact is None:
        return None
    return (str(artifact["id"]), int(artifact["version_number"]), str(artifact["content_hash"]))


def _reference_key(reference: Mapping[str, object]) -> tuple[str, int, str]:
    return (
        str(reference["artifact_id"]),
        int(reference["version_number"]),
        str(reference["content_hash"]),
    )


def _cited_ids(package: Mapping[str, object]) -> frozenset[str]:
    holders: list[Mapping[str, object]] = []
    for alternative in package["alternatives"]:
        holders.append(alternative)
        holders.extend(alternative["workflows"])
    holders.extend(package["concerns"])
    prototype = package.get("prototype")
    if prototype is not None:
        for screen in prototype["screens"]:
            holders.append(screen)
            holders.extend(screen["elements"])
    cited = {
        str(identifier)
        for holder in holders
        for key in CITED_KEYS
        for identifier in holder.get(key) or ()
    }
    bound = package.get("generated_mockup")
    if bound is not None:
        for value in bound["requirement_ids_by_code"].values():
            cited.update(str(item) for item in (value if isinstance(value, list) else [value]))
    return frozenset(cited)


def _gate_artifact(reference: GateArtifactReference) -> dict[str, object]:
    return {
        "project_id": str(reference.project_id),
        "gate_type": reference.gate_type.value,
        "artifact_id": str(reference.artifact_id),
        "version": reference.version,
        "content_hash": reference.content_hash,
    }


def _gate_payload(gate: HumanGate | None, *, resume: bool = True) -> dict[str, object] | None:
    if gate is None:
        return None
    payload: dict[str, object] = {
        "id": str(gate.id),
        "project_id": str(gate.project_id),
        "owner_user_id": str(gate.owner_user_id),
        "gate_type": gate.gate_type.value,
        "artifact": _gate_artifact(gate.artifact),
        "iteration": gate.iteration,
        "max_iterations": gate.max_iterations,
        "status": gate.status.value,
        "created_at": _stamp(gate.created_at),
        "updated_at": _stamp(gate.updated_at),
        "event_sequence": gate.event_sequence,
    }
    if resume:
        payload["resume_status"] = None if gate.resume_status is None else gate.resume_status.value
    return payload


def _event_payload(event: HumanGateEvent) -> dict[str, object]:
    return {
        "id": str(event.id),
        "gate_id": str(event.gate_id),
        "sequence_number": event.sequence_number,
        "kind": event.kind.value,
        "previous_status": event.previous_status.value,
        "resulting_status": event.resulting_status.value,
        "artifact": _gate_artifact(event.artifact),
        "occurred_at": _stamp(event.occurred_at),
        "actor_user_id": None if event.actor_user_id is None else str(event.actor_user_id),
        "reason": event.reason,
    }


def _selection_reason(payload: Mapping[str, object]) -> TeamSelectionReason:
    evidence = payload["evidence"]
    return TeamSelectionReason(
        code=TeamSelectionReasonCode(str(payload["code"])),
        evidence=RuleEvidence(
            fields=tuple(BriefField(str(item)) for item in evidence["fields"]),
            terms=tuple(str(item) for item in evidence["terms"]),
        ),
    )


def _team_constraints(content: Mapping[str, object]) -> DeterministicTeamConstraints:
    return DeterministicTeamConstraints(
        catalog_version=int(content["catalog_version"]),
        catalog_content_hash=str(content["catalog_content_hash"]),
        project_mode=ProjectMode(str(content["project_mode"])),
        role_constraints=tuple(
            TeamRoleConstraint(
                agent_id=AgentIdentifier(str(item["agent_id"])),
                kind=TeamRoleConstraintKind(str(item["kind"])),
                reasons=tuple(_selection_reason(reason) for reason in item["reasons"]),
            )
            for item in content["role_constraints"]
        ),
        issues=tuple(
            TeamSelectionIssue(
                code=TeamSelectionIssueCode(str(item["code"])),
                agent_id=AgentIdentifier(str(item["agent_id"])),
                mandatory_reasons=tuple(
                    _selection_reason(reason) for reason in item["mandatory_reasons"]
                ),
                impossible_reasons=tuple(
                    _selection_reason(reason) for reason in item["impossible_reasons"]
                ),
            )
            for item in content["constraint_issues"]
        ),
    )


def _items_value(items: Sequence[str]) -> dict[str, object]:
    return {"kind": "ITEMS", "text": None, "items": list(items), "reason": None}


def _fake_team_proposal(version: Mapping[str, object]):
    return proposal_from_snapshot(
        {
            "schema_version": version["schema_version"],
            "project_id": version["project_id"],
            "project_mode": version["project_mode"],
            "provider": {key: version[key] for key in ("provider_id", "provider_version")}
            | {"kind": version["provider_kind"]},
            "brief_version": {
                "id": version["brief_version_id"],
                "version_number": version["brief_version_number"],
                "content_hash": version["brief_content_hash"],
            },
            "catalog": {
                "version": version["catalog_version"],
                "content_hash": version["catalog_content_hash"],
            },
            "constraints": _team_constraints(version).to_snapshot(),
            "constraints_content_hash": version["constraints_content_hash"],
            "members": version["members"],
        }
    )


def _fake_requirements(specification: Mapping[str, object]):
    return RequirementsSpecificationPayload.model_validate(specification).to_domain()


def _fake_design(package: Mapping[str, object]):
    from orchestwin.api.design import DesignPackagePayload

    return DesignPackagePayload.model_validate(package).to_domain()


def _fake_twin_profile(profile: Mapping[str, object]):
    payload = copy.deepcopy(dict(profile))
    payload.setdefault("schema_version", 1)
    payload.setdefault(
        "catalog",
        {
            "version": payload.pop("catalog_version", AGENT_CATALOG_VERSION),
            "content_hash": payload.pop("catalog_content_hash", AGENT_CATALOG_CONTENT_HASH),
        },
    )
    payload.setdefault(
        "requires_human_validation",
        any(item["human_validation"] == "REQUIRED" for item in payload["observations"]),
    )
    return user_twin_profile_from_snapshot(payload)


def _fake_modeling(body: Mapping[str, object]):
    def reference(value):
        return VersionedArtifactReference(
            artifact_id=UUID(value["artifact_id"]),
            version_number=value["version_number"],
            content_hash=value["content_hash"],
        )

    return create_user_modeling_snapshot(
        project_id=UUID(body["project_id"]),
        project_brief_reference=reference(body["project_brief_reference"]),
        agent_team_reference=reference(body["agent_team_reference"]),
        catalog_version=body["catalog_version"],
        catalog_content_hash=body["catalog_content_hash"],
        persona_versions=(_fake_persona(version) for version in body["persona_versions"]),
        twin_versions=(
            UserTwinProfileVersion(
                id=UUID(version["id"]),
                project_id=UUID(version["project_id"]),
                twin_id=UUID(version["twin_id"]),
                version_number=version["version_number"],
                based_on_version_number=version.get("based_on_version_number"),
                profile=_fake_twin_profile(version["profile"]),
                content_hash=version["content_hash"],
                created_by_user_id=UUID(version["created_by_user_id"]),
                created_at=datetime.fromisoformat(version["created_at"]),
            )
            for version in body["twin_versions"]
        ),
    )


def _fake_persona(version: Mapping[str, object]) -> PersonaProfileVersion:
    payload = copy.deepcopy(version["profile"])
    payload.setdefault("schema_version", 1)
    profile = persona_profile_from_snapshot(payload)
    return PersonaProfileVersion(
        id=UUID(version["id"]),
        project_id=UUID(version["project_id"]),
        persona_id=UUID(version["persona_id"]),
        version_number=version["version_number"],
        based_on_version_number=version.get("based_on_version_number"),
        profile=profile,
        content_hash=profile.content_hash,
        created_by_user_id=UUID(version["created_by_user_id"]),
        created_at=datetime.fromisoformat(version["created_at"]),
    )


def _twin_reference(twin: Mapping[str, object]) -> dict[str, object]:
    return {
        "twin_id": twin["twin_id"],
        "version_number": twin["version_number"],
        "content_hash": twin["content_hash"],
        "name": twin["profile"]["name"],
    }


def _visual_language(package: Mapping[str, object], alternative_id: str) -> dict[str, object]:
    alternative = _by_id(package["alternatives"], alternative_id)
    if alternative is None:
        raise RuntimeError("the mockup needs its alternative")
    return alternative["visual_language"]


def _tokens(package: Mapping[str, object], alternative_id: str) -> dict[str, str]:
    return dict(_visual_language(package, alternative_id)["tokens"])


def _applied_alternative_id(package: Mapping[str, object]) -> str:
    return str(package["generated_mockup"]["mockup"]["design_alternative_id"])


def _colour_mode(package: Mapping[str, object]) -> ColorMode:
    choices = _visual_language(package, _applied_alternative_id(package))["choices"]
    return VisualChoices.from_snapshot(choices).color_mode


def _applied_mockup(package: Mapping[str, object]) -> GeneratedMockup:
    tokens = _tokens(package, _applied_alternative_id(package))
    return generated_mockup_from_snapshot(package["generated_mockup"]["mockup"], token_names=tokens)


def _mockup_warnings(
    package: Mapping[str, object], specification: Mapping[str, object]
) -> list[dict[str, object]]:
    if package.get("generated_mockup") is None:
        return []
    report = review_generated_mockup(
        _applied_mockup(package),
        tokens=_tokens(package, _applied_alternative_id(package)),
        requirement_codes=[str(item["code"]) for item in specification["requirements"]],
        text_contrast_threshold=MODES[_colour_mode(package)].text_threshold,
    )
    return [
        {"code": issue.code, "screen_code": issue.screen_code, "detail": issue.detail}
        for issue in report.issues
        if issue.severity is MockupIssueSeverity.WARNING
    ]


def _query_zones(call: _Call) -> bool:
    value = call.value("zones")
    zones = False if value is None else _lax_boolean(value)
    if zones is None:
        raise _Invalid([_error(("query", "zones"), "bool_parsing")])
    return zones


def _screen_list(mockup: Mapping[str, object]) -> list[dict[str, object]]:
    return [
        {"code": screen["code"], "title": screen["title"], "state": screen["state"]}
        for screen in mockup["screens"]
    ]


def _change_target(fields: _Fields, *, required: bool = False) -> dict[str, object] | None:
    child = fields.child("target", CHANGE_TARGET_FIELDS, required=required, nullable=not required)
    if child is None:
        return None
    screen = child.pattern("screen_code", SCREEN_CODE)
    element = child.pattern("element_code", ELEMENT_CODE, required=False, nullable=True)
    texts = _target_texts(child)
    parts = _models(
        child,
        "elements",
        TARGET_PART_FIELDS,
        _target_part,
        required=False,
        nullable=True,
        minimum_items=MIN_TARGET_ELEMENTS,
        maximum_items=MAX_TARGET_ELEMENTS,
    )
    target = {"screen_code": screen, "element_code": element, **texts}
    if parts:
        target["elements"] = parts
    _model_rule(child, lambda: _target_domain(target))
    valid = not child.errors
    fields.adopt(child)
    return target if valid else None


def _target_texts(fields: _Fields) -> dict[str, object]:
    texts: dict[str, object] = {}
    for name, normalizer in (("label", target_label), ("html", target_html)):
        text = fields.text(name, required=False, nullable=True)
        texts[name] = None if text is None else fields.normalized(name, text, normalizer)
    return texts


def _target_part(fields: _Fields) -> dict[str, object]:
    return {"element_code": fields.pattern("element_code", ELEMENT_CODE), **_target_texts(fields)}


def _target_snapshot(target: Mapping[str, object] | None) -> dict[str, object] | None:
    if target is None:
        return None
    snapshot = _present(target)
    if "elements" in snapshot:
        snapshot["elements"] = [_present(item) for item in snapshot["elements"]]
    return snapshot


def _present(values: Mapping[str, object]) -> dict[str, object]:
    return {name: value for name, value in values.items() if value is not None}


def _checked_target(package: Mapping[str, object], target: Mapping[str, object] | None) -> None:
    if target is None:
        return
    mockup = None if package.get("generated_mockup") is None else _applied_mockup(package)
    try:
        target_view(_target_domain(target), mockup)
    except DesignChangeTargetError as error:
        raise _Refusal(422, {"code": error.code}) from error


def _target_domain(target: Mapping[str, object]) -> DesignChangeTarget:
    snapshot = _target_snapshot(target)
    parts = tuple(DesignChangeTargetElement(**part) for part in snapshot.pop("elements", ()))
    return DesignChangeTarget(**snapshot, elements=parts)


def _with_targeted(
    changes: list[str], language: str, target: Mapping[str, object] | None
) -> list[str]:
    if target is None:
        return changes
    texts = ALIGNMENT_TEXTS[language]
    screen = target["screen_code"]
    codes = [part["element_code"] for part in target.get("elements") or ()]
    if codes:
        joined = f"{', '.join(codes[:-1])} {texts['and']} {codes[-1]}"
        line = texts["targeted_parts"].format(elements=joined, screen=screen)
    elif target["element_code"] is None:
        line = texts["targeted_screen"].format(screen=screen)
    else:
        line = texts["targeted_element"].format(element=target["element_code"], screen=screen)
    return list(dict.fromkeys((line, *changes)))
