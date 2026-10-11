from __future__ import annotations

import asyncio
import copy
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from orchestwin.agents.catalog import AGENT_CATALOG_CONTENT_HASH, AGENT_CATALOG_VERSION
from orchestwin.twins.archetypes import ArchetypeFailure, ArchetypeService
from orchestwin.twins.conversations import (
    MAX_QUESTION_CHARACTERS,
    MAX_TURNS_PER_CONVERSATION,
    TwinConversation,
    TwinConversationTurn,
    TwinInsight,
    TwinInsightKind,
    normalized_text,
)
from orchestwin.twins.persistence.repositories import VersionAppendStatus
from orchestwin.twins.persistence.snapshots import (
    persona_profile_from_snapshot,
    user_twin_profile_from_snapshot,
)
from orchestwin.twins.representation import ArchetypeInput, archetype_payload, twin_view
from orchestwin.twins.user_twins import UserTwinField, UserTwinProfileVersion
from orchestwin.workflow.gates import HumanGate, HumanGateEvent, HumanGateStatus

from .common import (
    _blank_to_none,
    _by_id,
    _digest,
    _error,
    _event_payload,
    _fake_modeling,
    _fake_persona,
    _fake_twin_profile,
    _gate_payload,
    _items_value,
    _plain_reference,
    _stamp,
)
from .fields import _Fields, _gate_decision
from .texts import PERSONAS, PROFILE
from .values import GATE_ACTIONS, _Answer, _domain_refusal, _Invalid, _Refusal

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject
    from .values import _Account, _BriefVersion


CHAT = {
    "it": (
        "Sono {name}: mi serve vedere subito quanto lasciare di mancia, senza fare conti.",
        "Vedere subito l'importo della mancia",
    ),
    "en": (
        "I am {name}: I need to see at once how much to tip, without doing the maths.",
        "See the tip amount at once",
    ),
}


class _TwinRoutes:
    def _modeling_issue(self, project: FakeProject | None) -> None:
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        approvals = self._approvals(project)
        if not approvals["brief"]:
            raise _Refusal(409, {"code": "BRIEF_APPROVAL_REQUIRED"})
        if project.team is None:
            raise _Refusal(409, {"code": "TEAM_PROPOSAL_REQUIRED"})
        if not approvals["team"]:
            raise _Refusal(409, {"code": "TEAM_APPROVAL_REQUIRED"})

    def _brief_source(self, version: _BriefVersion, locator: str) -> dict[str, object]:
        return {
            "source_kind": "PROJECT_BRIEF",
            "source_id": version.id,
            "source_version": version.number,
            "content_hash": version.content_hash,
            "locator": locator,
            "summary": None,
        }

    def _persona_profile(
        self, name: str, version: _BriefVersion, status: str, reason: str | None
    ) -> dict[str, object]:
        texts = PROFILE[self.language]
        source = self._brief_source(version, "target_users")
        return {
            "name": name,
            "source": "SYSTEM_PROPOSED",
            "kind": "PROTO_PERSONA",
            "confirmation_status": status,
            "rejection_reason": reason,
            "observations": [
                _observation("persona.role", _text_value(name), source),
                _observation(
                    "persona.summary", _text_value(texts["summary"].format(name=name)), source
                ),
                _observation("persona.goals", _items_value(texts["goals"]), source),
                _observation("persona.context_of_use", _text_value(texts["context"]), source),
            ],
        }

    def _persona_version(
        self,
        project: FakeProject,
        persona_id: str,
        number: int,
        profile: dict[str, object],
        account: _Account,
    ) -> dict[str, object]:
        return {
            "id": self._new_id(),
            "project_id": project.id,
            "persona_id": persona_id,
            "version_number": number,
            "based_on_version_number": None if number == 1 else number - 1,
            "content_hash": _fake_persona_profile(profile).content_hash,
            "created_by_user_id": account.id,
            "created_at": _stamp(self._now()),
            "profile": profile,
        }

    def _current_personas(self, project: FakeProject | None) -> list[dict[str, object]]:
        if project is None:
            return []
        return [
            project.personas[key][-1]
            for key in sorted(project.personas)
            if not project.personas[key][-1]["profile"].get("archived", False)
        ]

    def _archetype_service(self, project: FakeProject) -> ArchetypeService:
        class Unit:
            def __init__(unit, *, owner_user_id):
                unit.owner = owner_user_id
                unit.staged = copy.deepcopy(project.personas)
                unit.personas = unit

            async def __aenter__(unit):
                return unit

            async def __aexit__(unit, *_args):
                return None

            async def lock_project(unit, *, project_id):
                return str(project_id) == project.id and str(unit.owner) == project.account.id

            async def has_pending_revision(unit, *, project_id):
                return str(project_id) == project.id and any(
                    update["status"] == "PROPOSED" for update in project.updates
                )

            async def list_current(unit, *, project_id):
                return tuple(_fake_persona(versions[-1]) for versions in unit.staged.values())

            async def current(unit, *, project_id, persona_id):
                versions = unit.staged.get(str(persona_id))
                return None if not versions else _fake_persona(versions[-1])

            async def append(unit, version):
                unit.staged.setdefault(str(version.persona_id), []).append(version.to_snapshot())
                return VersionAppendStatus.APPENDED

            async def commit(unit):
                project.personas = unit.staged

        return ArchetypeService(
            uow_factory=Unit, uuid_factory=lambda: UUID(self._new_id()), clock=self._now
        )

    def _archetype_input(self, call: _Call, *, editing: bool = False):
        fields = _Fields(
            call.json(),
            (
                "name",
                "description",
                "role",
                "goals",
                "context",
                *(["based_on_version_number"] if editing else []),
            ),
        )
        name = fields.text("name")
        description = fields.text("description")
        role = fields.text("role")
        goals = fields.texts("goals", default=[], nullable=False)
        context = fields.text("context", required=False, nullable=True)
        base = fields.integer("based_on_version_number", minimum=1) if editing else None
        fields.check()
        try:
            data = ArchetypeInput(
                name=name,
                description=description,
                role=role,
                goals=tuple(goals or ()),
                context=context,
            )
        except (TypeError, ValueError) as error:
            raise _domain_refusal(str(error)) from None
        return data, base

    def _archetype_command(self, call: _Call, operation: str, **arguments):
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        service = self._archetype_service(project)
        try:
            result = asyncio.run(
                getattr(service, operation)(
                    owner_user_id=UUID(call.account.id), project_id=UUID(project.id), **arguments
                )
            )
        except ArchetypeFailure as error:
            raise _Refusal(
                404 if error.issue.value in {"PROJECT_NOT_FOUND", "ARCHETYPE_NOT_FOUND"} else 409,
                {"code": error.issue.value},
            ) from None
        return result

    def _route_archetypes(self, call: _Call) -> _Answer:
        return _Answer(
            200, [archetype_payload(item) for item in self._archetype_command(call, "list_current")]
        )

    def _route_archetype_create(self, call: _Call) -> _Answer:
        data, _ = self._archetype_input(call)
        return _Answer(201, archetype_payload(self._archetype_command(call, "create", data=data)))

    def _route_archetype_edit(self, call: _Call) -> _Answer:
        data, base = self._archetype_input(call, editing=True)
        result = self._archetype_command(
            call,
            "edit",
            persona_id=UUID(call.params["persona_id"]),
            based_on_version_number=base,
            data=data,
        )
        return _Answer(200, archetype_payload(result))

    def _route_archetype_archive(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("based_on_version_number",))
        base = fields.integer("based_on_version_number", minimum=1)
        fields.check()
        result = self._archetype_command(
            call,
            "archive",
            persona_id=UUID(call.params["persona_id"]),
            based_on_version_number=base,
        )
        return _Answer(200, archetype_payload(result))

    def _archetypes_current(self, project: FakeProject, snapshot: Mapping[str, object]) -> bool:
        active = [
            item
            for item in self._current_personas(project)
            if item["profile"]["confirmation_status"] != "REJECTED"
        ]
        if any(item["profile"]["confirmation_status"] != "CONFIRMED" for item in active):
            return False

        def key(item):
            return item["id"], item["version_number"], item["content_hash"]

        return {item["persona_id"]: key(item) for item in active} == {
            item["persona_id"]: key(item) for item in snapshot["snapshot"]["persona_versions"]
        }

    def _readable_snapshot(self, snapshot: Mapping[str, object]) -> dict[str, object]:
        document = copy.deepcopy(snapshot)
        for twin in document["snapshot"]["twin_versions"]:
            reference = twin["profile"]["persona_reference"]
            persona = next(
                (
                    item
                    for item in snapshot["snapshot"]["persona_versions"]
                    if all(
                        item[key] == reference[key]
                        for key in ("persona_id", "version_number", "content_hash")
                    )
                ),
                None,
            )
            twin["view"] = _fake_twin_view(twin, persona)
        return document

    def _route_personas(self, call: _Call) -> _Answer:
        return _Answer(200, self._current_personas(self._owned(call)))

    def _route_persona_proposals(self, call: _Call) -> _Answer:
        return self._later(call, "PERSONA_PROPOSAL", {}, lambda: self._proposed_personas(call))

    def _proposed_personas(self, call: _Call) -> _Answer:
        project = self._owned(call)
        self._modeling_issue(project)
        assert project is not None
        if project.personas:
            raise _Refusal(409, {"code": "PERSONAS_ALREADY_EXIST"})
        self._record(project, "PERSONA_PROPOSAL")
        versions = self._propose_personas(project, call.account)
        return _Answer(
            200,
            {
                "status": "CREATED",
                "issue": None,
                "candidate_issue": None,
                "proposal_issue": None,
                "versions": versions,
            },
        )

    def _propose_personas(self, project: FakeProject, account: _Account) -> list:
        brief = project.brief
        if brief is None:
            raise RuntimeError("personas need a brief")
        versions = []
        for name in PERSONAS[self.language][: self.twins]:
            persona_id = self._new_id()
            profile = self._persona_profile(name, brief, "PENDING_CONFIRMATION", None)
            version = self._persona_version(project, persona_id, 1, profile, account)
            project.personas[persona_id] = [version]
            versions.append(version)
        return versions

    def _route_persona_decision(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("decision", "reason"))
        decision = fields.choice("decision", ("CONFIRM", "REJECT"))
        reason = fields.text("reason", required=False, nullable=True)
        fields.check()
        project = self._owned(call)
        self._modeling_issue(project)
        assert project is not None
        versions = project.personas.get(call.params["persona_id"])
        if versions is None:
            raise _Refusal(404, {"code": "PERSONA_NOT_FOUND"})
        version = self._decide_persona(project, versions, decision or "", reason, call.account)
        if version is None:
            return _Answer(
                200,
                {
                    "status": "NO_CHANGE",
                    "issue": None,
                    "decision_issue": None,
                    "version": versions[-1],
                },
            )
        return _Answer(
            200,
            {"status": "APPLIED", "issue": None, "decision_issue": None, "version": version},
        )

    def _decide_persona(
        self,
        project: FakeProject,
        versions: list[dict[str, object]],
        decision: str,
        reason: str | None,
        account: _Account,
    ) -> dict[str, object] | None:
        current = versions[-1]
        profile = copy.deepcopy(current["profile"])
        status = profile["confirmation_status"]
        if (decision, status) in {("CONFIRM", "CONFIRMED"), ("REJECT", "REJECTED")}:
            return None
        if status != "PENDING_CONFIRMATION":
            raise _Refusal(409, {"code": "PERSONA_DECISION_REJECTED"})
        if decision == "CONFIRM":
            profile["confirmation_status"] = "CONFIRMED"
        else:
            normalized = " ".join((reason or "").split())
            if not normalized or len(normalized) > 2000:
                raise _Refusal(409, {"code": "PERSONA_DECISION_REJECTED"})
            profile["confirmation_status"] = "REJECTED"
            profile["rejection_reason"] = normalized
        version = self._persona_version(
            project,
            str(current["persona_id"]),
            int(current["version_number"]) + 1,
            profile,
            account,
        )
        versions.append(version)
        return version

    def _snapshot_current(self, project: FakeProject, snapshot: Mapping[str, object]) -> bool:
        brief = project.brief
        team = project.team
        body = snapshot["snapshot"]
        return (
            brief is not None
            and team is not None
            and body["project_brief_reference"]
            == {
                "artifact_id": brief.id,
                "version_number": brief.number,
                "content_hash": brief.content_hash,
            }
            and body["agent_team_reference"] == _plain_reference(team)
        )

    def _route_twins_generate(self, call: _Call) -> _Answer:
        return self._later(call, "USER_TWIN_GENERATION", {}, lambda: self._generated_twins(call))

    def _generated_twins(self, call: _Call) -> _Answer:
        project = self._owned(call)
        self._modeling_issue(project)
        assert project is not None
        snapshot = project.snapshot
        if any(update["status"] == "PROPOSED" for update in project.updates):
            raise _Refusal(409, {"code": "USER_TWIN_REVISION_PENDING"})
        if (
            snapshot is not None
            and self._snapshot_current(project, snapshot)
            and self._archetypes_current(project, snapshot)
        ):
            raise _Refusal(409, {"code": "SNAPSHOT_ALREADY_EXISTS"})
        personas = self._current_personas(project)
        if not personas:
            raise _Refusal(409, {"code": "PERSONAS_REQUIRED"})
        statuses = [persona["profile"]["confirmation_status"] for persona in personas]
        if "PENDING_CONFIRMATION" in statuses:
            raise _Refusal(409, {"code": "PERSONA_CONFIRMATION_REQUIRED"})
        if "CONFIRMED" not in statuses:
            raise _Refusal(409, {"code": "PERSONAS_REQUIRED"})
        self._record(project, "USER_TWIN_GENERATION")
        created = self._create_twins(project, personas, call.account)
        return _Answer(
            200,
            {
                "status": "CREATED",
                "issue": None,
                "proposal_issue": None,
                "snapshot_version": self._readable_snapshot(created),
                "twin_versions": self._readable_snapshot(created)["snapshot"]["twin_versions"],
            },
        )

    def _create_twins(
        self,
        project: FakeProject,
        personas: Sequence[Mapping[str, object]],
        account: _Account,
    ) -> dict[str, object]:
        brief = project.brief
        team = project.team
        if brief is None or team is None:
            raise RuntimeError("twins need a brief and a team")
        confirmed = [
            persona
            for persona in personas
            if persona["profile"]["confirmation_status"] == "CONFIRMED"
        ]
        brief_reference = {
            "artifact_id": brief.id,
            "version_number": brief.number,
            "content_hash": brief.content_hash,
        }
        team_reference = _plain_reference(team)
        twins = []
        previous_twins = (
            {}
            if project.snapshot is None
            else {
                item["profile"]["persona_reference"]["persona_id"]: item
                for item in project.snapshot["snapshot"]["twin_versions"]
            }
        )
        for persona in confirmed:
            twin = self._twin_version(
                project,
                persona,
                brief,
                team_reference,
                account,
                previous=previous_twins.get(persona["persona_id"]),
            )
            project.twins.setdefault(str(twin["twin_id"]), []).append(twin)
            twins.append(twin)
        twins.sort(key=lambda twin: str(twin["twin_id"]))
        ordered = sorted(confirmed, key=lambda persona: str(persona["persona_id"]))
        body = {
            "project_id": project.id,
            "project_brief_reference": brief_reference,
            "agent_team_reference": team_reference,
            "catalog_version": AGENT_CATALOG_VERSION,
            "catalog_content_hash": AGENT_CATALOG_CONTENT_HASH,
            "persona_count": len(ordered),
            "twin_count": len(twins),
            "persona_versions": [copy.deepcopy(persona) for persona in ordered],
            "twin_versions": twins,
        }
        previous = project.snapshot
        version = {
            "id": self._new_id(),
            "project_id": project.id,
            "version_number": 1 if previous is None else int(previous["version_number"]) + 1,
            "based_on_version_number": None if previous is None else previous["version_number"],
            "content_hash": _fake_modeling(body).content_hash,
            "created_by_user_id": account.id,
            "created_at": _stamp(self._now()),
            "snapshot": body,
        }
        project.snapshots.append(version)
        return version

    def _twin_version(
        self,
        project: FakeProject,
        persona: Mapping[str, object],
        brief: _BriefVersion,
        team_reference: Mapping[str, object],
        account: _Account,
        *,
        previous: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        texts = PROFILE[self.language]
        name = str(persona["profile"]["name"])
        source = self._brief_source(brief, "target_users")
        values = {
            "role": _text_value(name),
            "expertise": _items_value(texts["expertise"]),
            "goals": _items_value(texts["goals"]),
            "recurring_tasks": _items_value(texts["tasks"]),
            "context_of_use": _text_value(texts["context"]),
            "information_needs": _items_value(texts["needs"]),
            "decision_criteria": None,
            "preferred_vocabulary": None,
            "frustrations": _items_value(texts["frustrations"]),
            "pain_points": _items_value(texts["pain_points"]),
            "trust_concerns": None,
            "accessibility_needs": None,
            "operational_constraints": None,
            "technical_literacy": _text_value(texts["literacy"]),
            "risk_sensitivity": None,
            "assumptions": _items_value(texts["assumptions"]),
        }
        source_values = {
            item["observation_key"]: item["value"] for item in persona["profile"]["observations"]
        }
        for source_field in ("role", "goals", "context_of_use"):
            supplied = source_values.get(f"persona.{source_field}")
            if supplied is not None:
                values[source_field] = supplied if supplied["kind"] in {"TEXT", "ITEMS"} else None
        role_value = source_values.get("persona.role") or {}
        values.update(
            {
                "description": source_values.get("persona.summary"),
                "represents": _items_value([role_value["text"]])
                if role_value.get("kind") == "TEXT" and role_value.get("text")
                else None,
                "does_not_represent": None,
                "evidence_gaps": None,
            }
        )
        observations = [
            _observation(f"user_twin.{key}", value, source)
            if value is not None
            else _unknown_observation(f"user_twin.{key}", source)
            for key, value in values.items()
        ]
        profile = {
            "name": name,
            "persona_reference": {
                "persona_id": persona["persona_id"],
                "version_number": persona["version_number"],
                "content_hash": persona["content_hash"],
                "source": persona["profile"]["source"],
                "kind": persona["profile"]["kind"],
                "confirmation_status": persona["profile"]["confirmation_status"],
            },
            "project_brief_reference": {
                "artifact_id": brief.id,
                "version_number": brief.number,
                "content_hash": brief.content_hash,
            },
            "agent_team_reference": dict(team_reference),
            "catalog_version": AGENT_CATALOG_VERSION,
            "catalog_content_hash": AGENT_CATALOG_CONTENT_HASH,
            "validation_status": "PROJECT_GROUNDED_UT",
            "observations": observations,
        }
        return {
            "id": self._new_id(),
            "project_id": project.id,
            "twin_id": self._new_id() if previous is None else previous["twin_id"],
            "version_number": 1 if previous is None else int(previous["version_number"]) + 1,
            "based_on_version_number": None if previous is None else previous["version_number"],
            "content_hash": _fake_twin_profile(profile).content_hash,
            "created_by_user_id": account.id,
            "created_at": _stamp(self._now()),
            "profile": profile,
        }

    def _route_snapshot_current(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.snapshot is None:
            raise _Refusal(404, {"code": "USER_MODELING_SNAPSHOT_NOT_FOUND"})
        return _Answer(200, self._readable_snapshot(project.snapshot))

    def _route_snapshot_history(self, call: _Call) -> _Answer:
        project = self._owned(call)
        return _Answer(
            200,
            []
            if project is None
            else [self._readable_snapshot(item) for item in project.snapshots],
        )

    def _route_twin_revision(self, call: _Call) -> _Answer:
        from orchestwin.api.user_modeling import (
            ProfileObservationPayload,
            ProfileRevisionProposalRequest,
        )

        fields = _Fields(call.json(), ("replacements",))
        raw = fields.value("replacements")
        fields.check()
        try:
            request = ProfileRevisionProposalRequest.model_validate({"replacements": raw})
        except ValueError as error:
            raise _Invalid([_error(("body", "replacements"), "value_error")]) from error
        try:
            replacements = request.to_domain()
        except ValueError as error:
            raise _Refusal(
                422, {"code": "INVALID_PROFILE_REPLACEMENT", "message": str(error)}
            ) from error
        project = self._owned(call)
        snapshot = None if project is None else project.snapshot
        if project is None or snapshot is None:
            raise _Refusal(404, {"code": "SNAPSHOT_NOT_FOUND"})
        twin_id = call.params["twin_id"]
        twin = next(
            (
                item
                for item in snapshot["snapshot"]["twin_versions"]
                if str(item["twin_id"]) == twin_id
            ),
            None,
        )
        if twin is None:
            raise _Refusal(404, {"code": "TWIN_NOT_FOUND"})
        if any(
            diff["status"] == "PROPOSED"
            and diff["base_snapshot_version_id"] == snapshot["id"]
            and diff["twin_id"] == twin_id
            for diff in project.twin_diffs
        ):
            raise _Refusal(409, {"code": "DIFF_ALREADY_PENDING"})
        before = {
            item["observation_key"]: ProfileObservationPayload.model_validate(item).model_dump(
                mode="json"
            )
            for item in twin["profile"]["observations"]
        }
        order = list(UserTwinField)
        operations = []
        for name in sorted(replacements, key=order.index):
            after = ProfileObservationPayload.from_domain(replacements[name]).model_dump(
                mode="json"
            )
            previous = before.get(name.observation_key)
            if previous != after:
                operations.append({"field": name.value, "before": previous, "after": after})
        if not operations:
            raise _Refusal(409, {"code": "INVALID_REPLACEMENT"})
        try:
            _fake_twin_profile(_revised_profile(twin["profile"], operations))
        except ValueError as error:
            raise _Refusal(409, {"code": "INVALID_REPLACEMENT"}) from error
        diff = {
            "id": self._new_id(),
            "project_id": project.id,
            "base_snapshot_version_id": snapshot["id"],
            "base_snapshot_version_number": snapshot["version_number"],
            "base_snapshot_content_hash": snapshot["content_hash"],
            "twin_id": twin_id,
            "base_twin_version_id": twin["id"],
            "base_twin_version_number": twin["version_number"],
            "base_twin_content_hash": twin["content_hash"],
            "proposal_hash": _digest(operations),
            "status": "PROPOSED",
            "operations": operations,
            "created_by_user_id": call.account.id,
            "created_at": _stamp(self._now()),
            "decided_by_user_id": None,
            "decided_at": None,
            "decision_reason": None,
            "applied_snapshot_version_id": None,
        }
        project.twin_diffs.append(diff)
        return _Answer(200, _twin_revision_payload("CREATED", diff, None, None))

    def _route_twin_revision_decision(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("decision", "reason"))
        decision = fields.choice("decision", ("APPROVE", "REJECT"))
        reason = fields.text("reason", required=False, nullable=True)
        fields.check()
        project = self._owned(call)
        diff = _by_id([] if project is None else project.twin_diffs, call.params["diff_id"])
        if project is None or diff is None:
            raise _Refusal(404, {"code": "DIFF_NOT_FOUND"})
        wanted = "APPROVED" if decision == "APPROVE" else "REJECTED"
        if diff["status"] != "PROPOSED":
            if diff["status"] == wanted:
                return _Answer(200, _twin_revision_payload("NO_CHANGE", diff, None, None))
            raise _Refusal(409, {"code": "DECISION_REJECTED"})
        normalized = _blank_to_none(reason)
        if decision == "REJECT" and normalized is None:
            raise _Refusal(409, {"code": "DECISION_REJECTED"})
        snapshot = project.snapshot
        if snapshot is None:
            raise _Refusal(404, {"code": "SNAPSHOT_NOT_FOUND"})
        if (snapshot["id"], snapshot["version_number"], snapshot["content_hash"]) != (
            diff["base_snapshot_version_id"],
            diff["base_snapshot_version_number"],
            diff["base_snapshot_content_hash"],
        ):
            raise _Refusal(409, {"code": "CONTEXT_CHANGED"})
        version = None if decision == "REJECT" else self._revised_twins(project, diff, call.account)
        diff["status"] = wanted
        diff["decided_by_user_id"] = call.account.id
        diff["decided_at"] = _stamp(self._now())
        diff["decision_reason"] = normalized
        if version is None:
            return _Answer(200, _twin_revision_payload("APPLIED", diff, None, None))
        diff["applied_snapshot_version_id"] = version["id"]
        readable = self._readable_snapshot(version)
        twin = next(
            item
            for item in readable["snapshot"]["twin_versions"]
            if item["twin_id"] == diff["twin_id"]
        )
        return _Answer(200, _twin_revision_payload("APPLIED", diff, twin, readable))

    def _revised_twins(
        self, project: FakeProject, diff: Mapping[str, object], account: _Account
    ) -> dict[str, object]:
        previous = project.snapshot
        if previous is None:
            raise RuntimeError("a twin revision needs a snapshot")
        body = copy.deepcopy(previous["snapshot"])
        revised: list[dict[str, object]] = []
        twins = []
        for base in body["twin_versions"]:
            if str(base["twin_id"]) != diff["twin_id"]:
                twins.append(base)
                continue
            profile = _revised_profile(base["profile"], diff["operations"])
            twin = {
                **base,
                "id": self._new_id(),
                "version_number": int(base["version_number"]) + 1,
                "based_on_version_number": base["version_number"],
                "content_hash": _fake_twin_profile(profile).content_hash,
                "created_by_user_id": account.id,
                "created_at": _stamp(self._now()),
                "profile": profile,
            }
            revised.append(twin)
            twins.append(twin)
        body["twin_versions"] = twins
        version = {
            "id": self._new_id(),
            "project_id": project.id,
            "version_number": int(previous["version_number"]) + 1,
            "based_on_version_number": previous["version_number"],
            "content_hash": _fake_modeling(body).content_hash,
            "created_by_user_id": account.id,
            "created_at": _stamp(self._now()),
            "snapshot": body,
        }
        for twin in revised:
            project.twins.setdefault(str(twin["twin_id"]), []).append(twin)
        project.snapshots.append(version)
        return version

    def _route_modeling_readiness(self, call: _Call) -> _Answer:
        project = self._owned(call)
        snapshot = None if project is None else project.snapshot
        gate = None if project is None else project.gates.get("twins")
        base = {
            "gate_exists": gate is not None,
            "gate_id": None if gate is None else str(gate.id),
            "gate_status": None if gate is None else gate.status.value,
        }
        if project is None or snapshot is None:
            return _Answer(
                200,
                {
                    "snapshot_exists": False,
                    "snapshot_version_id": None,
                    "snapshot_version_number": None,
                    "snapshot_content_hash": None,
                    **base,
                    "approved_current_snapshot": False,
                    "context_current": True,
                    "archetypes_current": False,
                    "workflow_state": "USER_MODELING_REQUIRED",
                    "twins": [],
                },
            )
        context_current = self._snapshot_current(project, snapshot)
        archetypes_current = self._archetypes_current(project, snapshot)
        reference = self._require_reference(project, "twins")
        approved = (
            context_current
            and archetypes_current
            and gate is not None
            and gate.status is HumanGateStatus.APPROVED
            and gate.artifact == reference
        )
        return _Answer(
            200,
            {
                "snapshot_exists": True,
                "snapshot_version_id": snapshot["id"],
                "snapshot_version_number": snapshot["version_number"],
                "snapshot_content_hash": snapshot["content_hash"],
                **base,
                "approved_current_snapshot": approved,
                "context_current": context_current,
                "archetypes_current": archetypes_current,
                "workflow_state": "READY_FOR_REQUIREMENTS_DEFINITION"
                if approved
                else "USER_MODELING_REVIEW_REQUIRED",
                "twins": [
                    {
                        "twin_id": twin["twin_id"],
                        "version_number": twin["version_number"],
                        "persisted_status": twin["profile"]["validation_status"],
                        "effective_status": "OWNER_APPROVED_UT"
                        if approved
                        else "PROJECT_GROUNDED_UT",
                    }
                    for twin in snapshot["snapshot"]["twin_versions"]
                ],
            },
        )

    def _twins_command(
        self,
        outcome: str,
        gate: HumanGate | None,
        events: Sequence[HumanGateEvent],
    ) -> _Answer:
        return _Answer(
            200,
            {
                "outcome": outcome,
                "gate": None if gate is None else _gate_payload(gate, resume=False),
                "events": [_event_payload(event) for event in events],
                "issue": None,
            },
        )

    def _route_twins_gate_submit(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.snapshot is None:
            raise _Refusal(404, {"code": "SNAPSHOT_NOT_FOUND"})
        status, gate, events, issue = self._submit_gate(
            project, "twins", self._require_reference(project, "twins")
        )
        if status == "SUBMITTED":
            return self._twins_command("APPLIED", gate, events)
        if status in {"ALREADY_PENDING", "ALREADY_APPROVED"}:
            return self._twins_command("NO_CHANGE", gate, events)
        raise _Refusal(409, {"code": issue or status})

    def _route_twins_gate_decision(self, call: _Call) -> _Answer:
        action, reason = _gate_decision(call, GATE_ACTIONS, literal=False, maximum=None)
        if action == "SUBMIT":
            raise _Invalid([_error(("body",), "value_error")])
        project = self._owned(call)
        if project is None or project.snapshot is None:
            raise _Refusal(404, {"code": "SNAPSHOT_NOT_FOUND"})
        status, gate, event, issue = self._decide_gate(
            project, "twins", self._require_reference(project, "twins"), action, reason
        )
        if status == "APPLIED":
            return self._twins_command("APPLIED", gate, [] if event is None else [event])
        if status == "GATE_NOT_FOUND":
            raise _Refusal(404, {"code": status})
        raise _Refusal(409, {"code": issue or status})

    def _route_twins_gate_current(self, call: _Call) -> _Answer:
        project = self._owned(call)
        gate = None if project is None else project.gates.get("twins")
        if gate is None:
            raise _Refusal(404, {"code": "USER_MODELING_GATE_NOT_FOUND"})
        return _Answer(200, _gate_payload(gate, resume=False))

    def _route_twins_gate_events(self, call: _Call) -> _Answer:
        project = self._owned(call)
        gate = None if project is None else project.gates.get("twins")
        if project is None or gate is None:
            return _Answer(200, [])
        return _Answer(
            200, [_event_payload(event) for event in project.gate_events.get(str(gate.id), [])]
        )

    def _current_twin(self, project: FakeProject | None, twin_id: str) -> dict | None:
        if project is None or twin_id not in project.twins:
            return None
        return project.twins[twin_id][-1]

    def _route_conversation(self, call: _Call) -> _Answer:
        project = self._owned(call)
        conversation = (
            None if project is None else project.conversations.get(call.params["twin_id"])
        )
        if conversation is None:
            raise _Refusal(404, {"code": "TWIN_CONVERSATION_NOT_FOUND"})
        return _Answer(200, {"snapshot": conversation.to_snapshot()})

    def _route_conversation_turn(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("question", "expected_turn_count"))
        question = fields.text("question", minimum=1, maximum=MAX_QUESTION_CHARACTERS)
        expected = fields.integer(
            "expected_turn_count", minimum=0, maximum=MAX_TURNS_PER_CONVERSATION
        )
        fields.check()
        try:
            question = normalized_text(question, maximum=MAX_QUESTION_CHARACTERS)
        except ValueError as error:
            raise _Refusal(422, {"code": "TWIN_QUESTION_INVALID"}) from error
        project = self._owned(call)
        twin_id = call.params["twin_id"]
        twin = self._current_twin(project, twin_id)
        if project is None or twin is None:
            raise _Refusal(404, {"code": "USER_TWIN_NOT_FOUND"})
        latest = project.conversations.get(twin_id)
        current = (
            latest if latest is not None and str(latest.twin_version_id) == twin["id"] else None
        )
        turns = () if current is None else current.turns
        if expected != len(turns):
            raise _Refusal(409, {"code": "TWIN_CONVERSATION_CHANGED"})
        if len(turns) >= MAX_TURNS_PER_CONVERSATION:
            raise _Refusal(409, {"code": "TWIN_CONVERSATION_FULL"})
        if not self.hosted:
            raise _Refusal(503, {"code": "TWIN_CHAT_MODEL_NOT_CONFIGURED"})
        generation = self._record(project, "TWIN_CHAT")
        moment = self._now()
        name = str(twin["profile"]["name"])
        conversation = current or TwinConversation(
            id=UUID(self._new_id()),
            project_id=UUID(project.id),
            owner_user_id=UUID(call.account.id),
            twin_id=UUID(twin_id),
            twin_version_id=UUID(str(twin["id"])),
            twin_version_number=int(twin["version_number"]),
            twin_content_hash=str(twin["content_hash"]),
            twin_name=name,
            created_at=moment,
            turns=(),
        )
        reply, insight = CHAT[self.language]
        turn = TwinConversationTurn(
            id=UUID(self._new_id()),
            conversation_id=conversation.id,
            ordinal=len(turns) + 1,
            question=question,
            reply=reply.format(name=name),
            insights=(
                TwinInsight(
                    kind=TwinInsightKind.NEED,
                    text=insight,
                    confidence=0.6,
                    grounded_on=("user_twin.goals",),
                ),
            ),
            model_generation_id=UUID(generation),
            created_at=moment,
        )
        recorded = conversation.with_turn(turn)
        project.conversations[twin_id] = recorded
        return _Answer(201, {"status": "TWIN_TURN_RECORDED", "snapshot": recorded.to_snapshot()})


def _text_value(text: str) -> dict[str, object]:
    return {"kind": "TEXT", "text": text, "items": [], "reason": None}


def _fake_persona_profile(profile: Mapping[str, object]):
    payload = copy.deepcopy(dict(profile))
    payload.setdefault("schema_version", 1)
    return persona_profile_from_snapshot(payload)


def _fake_twin_view(
    version: Mapping[str, object], persona: Mapping[str, object] | None
) -> dict[str, object]:
    payload = copy.deepcopy(version["profile"])
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
    archetype = None if persona is None else _fake_persona(persona)
    if archetype is not None:
        payload["persona_reference"]["content_hash"] = archetype.content_hash
    profile = user_twin_profile_from_snapshot(payload)
    twin = UserTwinProfileVersion(
        id=UUID(version["id"]),
        project_id=UUID(version["project_id"]),
        twin_id=UUID(version["twin_id"]),
        version_number=version["version_number"],
        based_on_version_number=version.get("based_on_version_number"),
        profile=profile,
        content_hash=profile.content_hash,
        created_by_user_id=UUID(version["created_by_user_id"]),
        created_at=datetime.fromisoformat(version["created_at"]),
    )
    return twin_view(twin, archetype)


def _observation(
    key: str, value: Mapping[str, object], source: Mapping[str, object]
) -> dict[str, object]:
    return {
        "observation_key": key,
        "value": dict(value),
        "epistemic_status": "MODEL_INFERRED",
        "confidence": 0.6,
        "provenance": [dict(source)],
        "human_validation": "REQUIRED",
        "rationale": "Simulated inference from the cited project brief.",
    }


def _unknown_observation(key: str, source: Mapping[str, object]) -> dict[str, object]:
    return {
        "observation_key": key,
        "value": {"kind": "UNKNOWN", "text": None, "items": [], "reason": None},
        "epistemic_status": "MODEL_INFERRED",
        "confidence": 0.0,
        "provenance": [dict(source)],
        "human_validation": "REQUIRED",
        "rationale": "No value was supplied for this field.",
    }


def _twin_revision_payload(
    status: str,
    diff: Mapping[str, object],
    twin: Mapping[str, object] | None,
    snapshot: Mapping[str, object] | None,
) -> dict[str, object]:
    return {
        "status": status,
        "issue": None,
        "proposal_issue": None,
        "diff": diff,
        "twin_version": twin,
        "snapshot_version": snapshot,
    }


def _revised_profile(
    profile: Mapping[str, object], operations: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    revised = copy.deepcopy(dict(profile))
    replaced = {
        UserTwinField(str(item["field"])).observation_key: copy.deepcopy(item["after"])
        for item in operations
    }
    observations = [
        replaced.pop(str(item["observation_key"]), item) for item in revised["observations"]
    ]
    observations.extend(replaced.values())
    revised["observations"] = observations
    return revised
