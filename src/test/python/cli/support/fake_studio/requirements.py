from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import TYPE_CHECKING
from uuid import UUID

from orchestwin.agents.catalog import AGENT_CATALOG_CONTENT_HASH, AGENT_CATALOG_VERSION
from orchestwin.api.requirements import (
    RequirementsSpecificationDiffPayload,
    RequirementsSpecificationPayload,
)
from orchestwin.knowledge.stage_documents import stage_versions
from orchestwin.projects.requirements_revisions import propose_requirements_diff

from .common import (
    _blank_to_none,
    _by_id,
    _code_number,
    _error,
    _event_payload,
    _fake_requirements,
    _gate_payload,
    _identifiers,
    _plain_reference,
    _stamp,
    _twin_reference,
)
from .fields import _Fields, _gate_decision
from .texts import CRITERIA, REQUIREMENTS, SCENARIO
from .values import GATE_ACTIONS, _Answer, _Invalid, _Refusal

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject
    from .values import _Account


MAX_CHANGE_REQUEST = 2000
APPROVAL_CODES = (
    ("brief", "BRIEF_APPROVAL_REQUIRED"),
    ("team", "TEAM_APPROVAL_REQUIRED"),
    ("twins", "USER_MODELING_APPROVAL_REQUIRED"),
    ("requirements", "REQUIREMENTS_APPROVAL_REQUIRED"),
    ("design", "DESIGN_APPROVAL_REQUIRED"),
)
STORY = {
    "it": ("calcolare la mancia senza fare conti a mente", "chiudere il conto in fretta"),
    "en": ("work out the tip without mental maths", "settle the bill quickly"),
}
RISK = {
    "it": ("Arrotondamenti diversi da quelli della cassa", "Mostrare gli importi con due decimali"),
    "en": ("Rounding differs from the till", "Show amounts with two decimals"),
}
DONE = {
    "it": (
        "Tutti i criteri di accettazione sono verificati",
        "La pagina funziona su telefono e computer",
    ),
    "en": ("Every acceptance criterion is verified", "The page works on phone and computer"),
}
OWNER_CHANGE = {"it": "Richiesta del titolare", "en": "Owner request"}


class _RequirementRoutes:
    def _specification(self, project: FakeProject, *, schema_version: int = 2) -> dict[str, object]:
        brief = project.brief
        team = project.team
        snapshot = project.snapshot
        if brief is None or team is None or snapshot is None:
            raise RuntimeError("requirements need brief, team and twins")
        language = self.language
        twins = [_twin_reference(twin) for twin in snapshot["snapshot"]["twin_versions"]]
        source = {
            "kind": "PROJECT_BRIEF",
            "source_id": brief.id,
            "source_version": brief.number,
            "content_hash": brief.content_hash,
            "locator": "functional_requirements",
        }
        requirements = [
            {
                "id": self._new_id(),
                "code": f"REQ-{index:03d}",
                "title": title,
                "statement": statement,
                "kind": kind,
                "priority": priority,
                "sources": [dict(source)],
                "user_twin_references": copy.deepcopy(twins),
            }
            for index, (kind, priority, title, statement) in enumerate(
                REQUIREMENTS[language], start=1
            )
        ]
        goal, benefit = STORY[language]
        stories = [
            {
                "id": self._new_id(),
                "code": f"USR-{index:03d}",
                "user_twin_reference": dict(twin),
                "goal": goal,
                "benefit": benefit,
                "requirement_ids": _identifiers(requirements[:2]),
            }
            for index, twin in enumerate(twins, start=1)
        ]
        criteria = [
            {
                "id": self._new_id(),
                "code": f"AC-{index:03d}",
                "statement": statement,
                "verification_method": "AUTOMATED_TEST",
                "requirement_ids": [requirements[index - 1]["id"]],
                "user_story_ids": [stories[0]["id"]] if index == 1 else [],
            }
            for index, statement in enumerate(CRITERIA[language], start=1)
        ]
        title, preconditions, trigger, steps, outcome = SCENARIO[language]
        summary, mitigation = RISK[language]
        specification = {
            "schema_version": 1,
            "project_id": project.id,
            "project_brief_reference": {
                "kind": "PROJECT_BRIEF",
                "artifact_id": brief.id,
                "version_number": brief.number,
                "content_hash": brief.content_hash,
            },
            "agent_team_reference": {"kind": "AGENT_TEAM", **_plain_reference(team)},
            "user_modeling_reference": {"kind": "USER_MODELING", **_plain_reference(snapshot)},
            "catalog_version": AGENT_CATALOG_VERSION,
            "catalog_content_hash": AGENT_CATALOG_CONTENT_HASH,
            "user_twin_references": twins,
            "requirements": requirements,
            "user_stories": stories,
            "acceptance_criteria": criteria,
            "scenarios": [
                {
                    "id": self._new_id(),
                    "code": "SCN-001",
                    "title": title,
                    "actor": dict(twins[0]),
                    "preconditions": list(preconditions),
                    "trigger": trigger,
                    "steps": list(steps),
                    "expected_outcome": outcome,
                    "requirement_ids": _identifiers(requirements[:2]),
                    "acceptance_criterion_ids": _identifiers(criteria[:2]),
                }
            ],
            "risks": [
                {
                    "id": self._new_id(),
                    "code": "RSK-001",
                    "summary": summary,
                    "likelihood": "POSSIBLE",
                    "impact": "MEDIUM",
                    "mitigation": mitigation,
                    "requirement_ids": [requirements[1]["id"]],
                    "sources": [dict(source)],
                    "review_status": "PROPOSED",
                }
            ],
            "definition_of_done": [
                {
                    "id": self._new_id(),
                    "code": f"DOD-{index:03d}",
                    "statement": statement,
                    "verification_method": "MANUAL_REVIEW",
                    "applicability": "REQUIRED",
                    "condition": None,
                    "requirement_ids": [],
                }
                for index, statement in enumerate(DONE[language], start=1)
            ],
        }

        if schema_version == 2:
            self._definition(
                specification,
                context=str(brief.brief.problem or brief.brief.description),
                goal=str((brief.brief.goals or (goal,))[0]),
            )
        return specification

    def _definition(
        self,
        specification: dict[str, object],
        *,
        context: str | None = None,
        goal: str | None = None,
    ) -> None:
        twins = specification["user_twin_references"]
        scenarios = specification["scenarios"]
        source = copy.deepcopy(specification["requirements"][0]["sources"])
        stories = specification["user_stories"]
        template = copy.deepcopy(scenarios[0])
        numbers = [_code_number(item["code"]) for item in scenarios]
        for twin in twins:
            if not any(item["actor"]["twin_id"] == twin["twin_id"] for item in scenarios):
                scenario = copy.deepcopy(template)
                scenario["id"] = self._new_id()
                scenario["code"] = f"SCN-{max(numbers, default=0) + 1:03d}"
                numbers.append(_code_number(scenario["code"]))
                scenario["actor"] = copy.deepcopy(twin)
                scenarios.append(scenario)
        needs = []
        for index, twin in enumerate(twins, start=1):
            story = next(
                item
                for item in stories
                if item["user_twin_reference"]["twin_id"] == twin["twin_id"]
            )
            owned = [item for item in scenarios if item["actor"]["twin_id"] == twin["twin_id"]]
            for scenario in owned:
                scenario["context"] = context or str(scenario["trigger"])
                scenario["goal"] = goal or str(story["goal"])
                scenario["criticalities"] = [
                    str(item["summary"]) for item in specification["risks"]
                ]
                scenario["sources"] = copy.deepcopy(source)
            need = {
                "id": self._new_id(),
                "code": f"NED-{index:03d}",
                "title": str(story["goal"]),
                "statement": str(story["benefit"]),
                "scenario_ids": _identifiers(owned),
                "sources": copy.deepcopy(source),
            }
            needs.append(need)
            story["need_ids"] = [need["id"]]
        for requirement in specification["requirements"]:
            requirement["need_ids"] = _identifiers(needs)
        specification["needs"] = needs
        specification["schema_version"] = 2

    def _append_requirements(
        self, project: FakeProject, specification: dict[str, object], account: _Account
    ) -> dict[str, object]:
        previous = project.specification
        version = {
            "id": self._new_id(),
            "project_id": project.id,
            "version_number": 1 if previous is None else int(previous["version_number"]) + 1,
            "based_on_version_number": None if previous is None else previous["version_number"],
            "content_hash": _fake_requirements(specification).content_hash,
            "created_by_user_id": account.id,
            "created_at": _stamp(self._now()),
            "specification": specification,
        }
        project.requirements.append(version)
        return version

    def _requirements_governance(self, project: FakeProject | None) -> None:
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        approvals = self._approvals(project)
        for stage, code in APPROVAL_CODES[:3]:
            if not approvals[stage]:
                raise _Refusal(409, {"code": code})

    def _route_requirements_proposal(self, call: _Call) -> _Answer:
        return self._later(
            call, "REQUIREMENTS_PROPOSAL", {}, lambda: self._generated_requirements(call)
        )

    def _generated_requirements(self, call: _Call) -> _Answer:
        project = self._owned(call)
        self._requirements_governance(project)
        assert project is not None
        if project.specification is not None:
            raise _Refusal(409, {"code": "SPECIFICATION_ALREADY_EXISTS"})
        self._record(project, "REQUIREMENTS_PROPOSAL")
        version = self._append_requirements(project, self._specification(project), call.account)
        return _Answer(
            201,
            {
                "status": "CREATED",
                "version": version,
                "issue": None,
                "proposal_issue": None,
                "persistence_status": "APPENDED",
            },
        )

    def _route_requirements_current(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.specification is None:
            raise _Refusal(404, {"code": "REQUIREMENTS_SPECIFICATION_NOT_FOUND"})
        return _Answer(200, project.specification)

    def _route_requirements_history(self, call: _Call) -> _Answer:
        project = self._owned(call)
        return _Answer(200, [] if project is None else list(project.requirements))

    def _route_requirements_readiness(self, call: _Call) -> _Answer:
        project = self._owned(call)
        version = None if project is None else project.specification
        gate = None if project is None else project.gates.get("requirements")
        if project is None or version is None:
            status = "REQUIREMENTS_REQUIRED"
        elif self._approvals(project)["requirements"]:
            status = "READY_FOR_DESIGN_EXPLORATION"
        else:
            status = "REQUIREMENTS_APPROVAL_REQUIRED"
        return _Answer(
            200,
            {
                "status": status,
                "version": version,
                "gate": None if gate is None else _gate_payload(gate),
                "approved_current_specification": status == "READY_FOR_DESIGN_EXPLORATION",
            },
        )

    def _route_requirements_change(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("request", "include_journeys"))
        request = fields.text("request")
        include_journeys = call.json().get("include_journeys", False)
        if not isinstance(include_journeys, bool):
            raise _Invalid([_error(("body", "include_journeys"), "bool_type")])
        fields.flag("include_journeys")
        fields.check()
        text = (request or "").strip()
        if not 1 <= len(text) <= MAX_CHANGE_REQUEST:
            raise _Invalid([_error(("body", "request"), "value_error")])
        return self._later(
            call,
            "REQUIREMENTS_CHANGE",
            {"request": text, **({"include_journeys": True} if include_journeys else {})},
            lambda: self._changed_requirements(call, text, include_journeys=include_journeys),
        )

    def _changed_requirements(
        self, call: _Call, text: str, *, include_journeys: bool = False
    ) -> _Answer:
        project = self._owned(call)
        self._requirements_governance(project)
        assert project is not None
        current = project.specification
        if current is None:
            raise _Refusal(404, {"code": "REQUIREMENTS_SPECIFICATION_NOT_FOUND"})
        if any(
            diff["status"] == "PROPOSED" and diff["base_version_id"] == current["id"]
            for diff in project.requirement_diffs
        ):
            raise _Refusal(409, {"code": "REQUIREMENTS_REVISION_PENDING"})
        self._record(project, "REQUIREMENTS_CHANGE")
        if include_journeys:
            proposed = self._with_journeys(current["specification"])
        else:
            proposed, _ = self._with_requirement(current["specification"], text)
        base = {
            **current,
            "specification": _fake_requirements(current["specification"]).to_snapshot(),
        }
        result = propose_requirements_diff(
            base_version=stage_versions({"requirements": base})["requirements"],
            proposed_specification=_fake_requirements(proposed),
            diff_id=UUID(self._new_id()),
            created_by_user_id=UUID(call.account.id),
            created_at=self._now(),
        )
        if result.diff is None:
            raise _Refusal(409, {"code": "REQUIREMENTS_UNCHANGED"})
        diff = RequirementsSpecificationDiffPayload.from_domain(result.diff).model_dump(mode="json")
        project.requirement_diffs.append(diff)
        return _Answer(201, _revision_payload("CREATED", diff, None))

    def _with_journeys(self, specification: Mapping[str, object]) -> dict[str, object]:
        proposed = copy.deepcopy(dict(specification))
        if proposed.get("schema_version", 1) == 1:
            self._definition(proposed)
        journeys = proposed.setdefault("journeys", [])
        covered = {item["scenario_id"] for item in journeys}
        number = max((_code_number(item["code"]) for item in journeys), default=0)
        for scenario in proposed["scenarios"]:
            if scenario["id"] in covered:
                continue
            need_ids = [
                item["id"] for item in proposed["needs"] if scenario["id"] in item["scenario_ids"]
            ]
            number += 1
            journeys.append(
                {
                    "id": self._new_id(),
                    "code": f"JRN-{number:03d}",
                    "title": scenario["title"],
                    "scenario_id": scenario["id"],
                    "phases": [
                        {
                            "title": f"{'Fase' if self.language == 'it' else 'Phase'} {index}",
                            "action": action,
                            "touchpoint": None,
                            "criticalities": scenario.get("criticalities", [])
                            if index == 1
                            else [],
                            "need_ids": need_ids,
                        }
                        for index, action in enumerate(scenario["steps"][:32], 1)
                    ],
                    "sources": copy.deepcopy(scenario["sources"]),
                }
            )
        return proposed

    def _with_requirement(
        self, specification: Mapping[str, object], text: str
    ) -> tuple[dict[str, object], dict[str, object]]:
        proposed = copy.deepcopy(dict(specification))
        if proposed.get("schema_version", 1) == 1:
            self._definition(proposed)
        requirements = proposed["requirements"]
        numbers = [_code_number(item["code"]) for item in requirements]
        added = {
            "id": self._new_id(),
            "code": f"REQ-{max(numbers, default=0) + 1:03d}",
            "title": OWNER_CHANGE[self.language],
            "statement": " ".join(text.split()),
            "kind": "FUNCTIONAL",
            "priority": "SHOULD",
            "sources": [
                {
                    "kind": "OWNER_INPUT",
                    "source_id": "owner-request",
                    "source_version": None,
                    "content_hash": None,
                    "locator": None,
                }
            ],
            "user_twin_references": [],
        }
        added["need_ids"] = _identifiers(proposed["needs"][:1])
        requirements.append(added)
        return proposed, added

    def _pending_requirements_diff(self, project: FakeProject) -> dict[str, object] | None:
        current = project.specification
        return next(
            (
                diff
                for diff in project.requirement_diffs
                if current is not None
                and diff["status"] == "PROPOSED"
                and diff["base_version_id"] == current["id"]
            ),
            None,
        )

    def _route_requirements_revise(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("specification",))
        specification = fields.value("specification")
        fields.check()
        try:
            payload = RequirementsSpecificationPayload.model_validate(specification)
        except ValueError as error:
            raise _Invalid([_error(("body", "specification"), "model_type")]) from error
        if str(payload.project_id) != call.project_id:
            raise _Refusal(422, {"code": "REQUIREMENTS_PROJECT_MISMATCH"})
        try:
            proposed = payload.to_domain()
        except (TypeError, ValueError) as error:
            raise _Refusal(422, {"code": "INVALID_REQUIREMENTS_SPECIFICATION"}) from error
        project = self._owned(call)
        current = None if project is None else project.specification
        if project is None or current is None:
            raise _Refusal(404, {"code": "SPECIFICATION_NOT_FOUND"})
        if self._pending_requirements_diff(project) is not None:
            raise _Refusal(409, {"code": "DIFF_ALREADY_PENDING"})
        base = {
            **current,
            "specification": _fake_requirements(current["specification"]).to_snapshot(),
        }
        result = propose_requirements_diff(
            base_version=stage_versions({"requirements": base})["requirements"],
            proposed_specification=proposed,
            diff_id=UUID(self._new_id()),
            created_by_user_id=UUID(call.account.id),
            created_at=self._now(),
        )
        if result.diff is None:
            raise _Refusal(409, {"code": "INVALID_PROPOSAL"})
        diff = RequirementsSpecificationDiffPayload.from_domain(result.diff).model_dump(mode="json")
        project.requirement_diffs.append(diff)
        return _Answer(201, _revision_payload("CREATED", diff, None))

    def _route_requirements_revisions(self, call: _Call) -> _Answer:
        project = self._owned(call)
        return _Answer(200, [] if project is None else list(project.requirement_diffs))

    def _route_requirements_revision(self, call: _Call) -> _Answer:
        project = self._owned(call)
        diff = _by_id([] if project is None else project.requirement_diffs, call.params["diff_id"])
        if diff is None:
            raise _Refusal(404, {"code": "REQUIREMENTS_DIFF_NOT_FOUND"})
        return _Answer(200, diff)

    def _route_requirements_revision_decision(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("decision", "reason"))
        decision = fields.choice("decision", ("APPROVE", "REJECT"))
        reason = fields.text("reason", required=False, nullable=True, maximum=2000)
        fields.check()
        project = self._owned(call)
        diff = _by_id([] if project is None else project.requirement_diffs, call.params["diff_id"])
        if project is None or diff is None:
            raise _Refusal(404, {"code": "DIFF_NOT_FOUND"})
        wanted = "APPROVED" if decision == "APPROVE" else "REJECTED"
        if diff["status"] != "PROPOSED":
            if diff["status"] == wanted:
                return _Answer(200, _revision_payload("NO_CHANGE", diff, None))
            raise _Refusal(409, {"code": "DECISION_REJECTED"})
        normalized = _blank_to_none(reason)
        if decision == "REJECT" and normalized is None:
            raise _Refusal(409, {"code": "DECISION_REJECTED"})
        current = project.specification
        if current is None:
            raise _Refusal(404, {"code": "SPECIFICATION_NOT_FOUND"})
        if (current["id"], current["version_number"], current["content_hash"]) != (
            diff["base_version_id"],
            diff["base_version_number"],
            diff["base_content_hash"],
        ):
            raise _Refusal(409, {"code": "CONTEXT_CHANGED"})
        version = None
        if decision == "APPROVE":
            version = self._append_requirements(
                project, copy.deepcopy(diff["proposed_specification"]), call.account
            )
            diff["applied_specification_version_id"] = version["id"]
        diff["status"] = wanted
        diff["decided_by_user_id"] = call.account.id
        diff["decided_at"] = _stamp(self._now())
        diff["decision_reason"] = normalized
        return _Answer(200, _revision_payload("APPLIED", diff, version))

    def _route_requirements_gate_submit(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.specification is None:
            raise _Refusal(404, {"code": "REQUIREMENTS_SPECIFICATION_NOT_FOUND"})
        status, gate, events, issue = self._submit_gate(
            project, "requirements", self._require_reference(project, "requirements")
        )
        if status not in {"SUBMITTED", "ALREADY_PENDING", "ALREADY_APPROVED"}:
            raise _Refusal(409, {"code": status})
        return _Answer(
            200,
            {
                "status": status,
                "gate": _gate_payload(gate),
                "events": [_event_payload(event) for event in events],
                "issue": issue,
            },
        )

    def _route_requirements_gate_decision(self, call: _Call) -> _Answer:
        action, reason = _gate_decision(call, GATE_ACTIONS, literal=False, maximum=2000)
        if action == "SUBMIT":
            raise _Invalid([_error(("body",), "value_error")])
        project = self._owned(call)
        if project is None or project.specification is None:
            raise _Refusal(404, {"code": "SPECIFICATION_NOT_FOUND"})
        return self._stage_decision(project, "requirements", action, reason)

    def _stage_decision(
        self, project: FakeProject, stage: str, action: str, reason: str | None
    ) -> _Answer:
        status, gate, event, issue = self._decide_gate(
            project, stage, self._require_reference(project, stage), action, reason
        )
        if status == "GATE_NOT_FOUND":
            raise _Refusal(404, {"code": status})
        if status != "APPLIED":
            raise _Refusal(409, {"code": issue or status})
        return _Answer(
            200,
            {
                "status": status,
                "gate": _gate_payload(gate),
                "event": None if event is None else _event_payload(event),
                "issue": None,
            },
        )

    def _stage_gate(self, call: _Call, stage: str, missing: str) -> _Answer:
        project = self._owned(call)
        gate = None if project is None else project.gates.get(stage)
        if gate is None:
            raise _Refusal(404, {"code": missing})
        return _Answer(200, _gate_payload(gate))

    def _stage_events(self, call: _Call, stage: str, missing: str) -> _Answer:
        project = self._owned(call)
        gate = None if project is None else project.gates.get(stage)
        if project is None or gate is None:
            raise _Refusal(404, {"code": missing})
        return _Answer(
            200, [_event_payload(event) for event in project.gate_events.get(str(gate.id), [])]
        )

    def _route_requirements_gate_current(self, call: _Call) -> _Answer:
        return self._stage_gate(call, "requirements", "REQUIREMENTS_GATE_NOT_FOUND")

    def _route_requirements_gate_events(self, call: _Call) -> _Answer:
        return self._stage_events(call, "requirements", "REQUIREMENTS_GATE_NOT_FOUND")


def _revision_payload(
    status: str, diff: Mapping[str, object], version: Mapping[str, object] | None
) -> dict[str, object]:
    return {
        "status": status,
        "diff": diff,
        "version": version,
        "issue": None,
        "proposal_issue": None,
        "diff_persistence_status": None,
        "version_persistence_status": None,
    }
