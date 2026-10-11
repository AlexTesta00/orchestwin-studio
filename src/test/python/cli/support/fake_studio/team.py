from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from orchestwin.agents.catalog import AGENT_CATALOG_CONTENT_HASH, AGENT_CATALOG_VERSION
from orchestwin.agents.perspectives import perspective_views
from orchestwin.agents.realignment import reanchored_team, team_selection_can_realign
from orchestwin.agents.selection_rules import (
    DeterministicTeamConstraints,
    TeamRoleConstraint,
    TeamRoleConstraintKind,
    TeamSelectionReason,
    determine_team_constraints,
)
from orchestwin.agents.team_gate import OWNER_CHOICE_STATEMENT
from orchestwin.models.fake_team_proposals import FakeDeterministicTeamProposalAdapter
from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGateStatus,
    HumanGateTransitionStatus,
    mark_human_gate_stale,
)

from .common import (
    _digest,
    _error,
    _event_payload,
    _fake_team_proposal,
    _gate_payload,
    _stamp,
    _submission_status,
    _team_constraints,
)
from .fields import _Fields, _gate_decision
from .texts import TEAM_CONTENT_KEYS
from .values import AGENT_ORDER, DECISION_ACTIONS, _Answer, _Refusal

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject
    from .values import _Account, _BriefVersion


SUGGESTED_SPECIALISTS = ("FRONTEND_ENGINEER",)
DETERMINISTIC_TEAM_PROVIDER = FakeDeterministicTeamProposalAdapter.PROVIDER_ID
HOSTED_TEAM_PROVIDER = "fake-team-proposer"
RULE_KEYS = ("constraints_content_hash", "role_constraints", "constraint_issues")
TEAM_TEXTS = {
    "it": "Serve per costruire la pagina web del calcolo.",
    "en": "Needed to build the web page of the calculation.",
}


class _TeamRoutes:
    def _require_reference(self, project: FakeProject, stage: str) -> GateArtifactReference:
        reference = self._reference(project, stage)
        if reference is None:
            raise RuntimeError(f"no artifact at {stage}")
        return reference

    def _team_rules(
        self, project: FakeProject, brief: _BriefVersion, dropped: Sequence[str] = ()
    ) -> DeterministicTeamConstraints:
        constraints = determine_team_constraints(
            project_mode=ProjectMode(project.mode), brief=brief.brief
        )
        if not dropped:
            return constraints
        return replace(
            constraints,
            role_constraints=tuple(
                TeamRoleConstraint(agent_id=item.agent_id, kind=TeamRoleConstraintKind.OPTIONAL)
                if item.agent_id.value in dropped
                else item
                for item in constraints.role_constraints
            ),
            issues=tuple(item for item in constraints.issues if item.agent_id.value not in dropped),
        )

    def _team_content(
        self,
        project: FakeProject,
        brief: _BriefVersion,
        selected: Sequence[str],
        previous: Sequence[Mapping[str, object]],
        rationales: Mapping[str, str],
        rules: Mapping[str, object],
        *,
        owner: bool = False,
    ) -> dict[str, object]:
        constraints = {str(item["agent_id"]): item for item in rules["role_constraints"]}
        earlier = {str(member["agent_id"]): member for member in previous}
        members = []
        for agent in AGENT_ORDER:
            if agent not in selected:
                continue
            if agent in earlier:
                members.append(copy.deepcopy(earlier[agent]))
            elif owner:
                members.append(
                    {
                        "agent_id": agent,
                        "source": "OWNER_ADDED",
                        "justifications": [
                            _justification(
                                "OWNER_RATIONALE",
                                "OWNER_SELECTED_ROLE",
                                statement=rationales.get(agent, OWNER_CHOICE_STATEMENT),
                            )
                        ],
                    }
                )
            elif constraints[agent]["kind"] == "MANDATORY":
                members.append(
                    {
                        "agent_id": agent,
                        "source": "DETERMINISTIC_MANDATORY",
                        "justifications": _rule_justifications(constraints[agent]),
                    }
                )
            else:
                members.append(
                    {
                        "agent_id": agent,
                        "source": "PROPOSER_SUGGESTED",
                        "justifications": [
                            _justification(
                                "PROPOSER_RATIONALE",
                                "MODEL_RECOMMENDATION",
                                statement=TEAM_TEXTS[self.language],
                            )
                        ],
                    }
                )
        return {
            "schema_version": 1,
            "provider_kind": "MODEL_ADAPTER" if self.hosted else "FAKE_DETERMINISTIC",
            "provider_id": HOSTED_TEAM_PROVIDER if self.hosted else DETERMINISTIC_TEAM_PROVIDER,
            "provider_version": 1,
            "project_mode": project.mode,
            "brief_version_id": brief.id,
            "brief_version_number": brief.number,
            "brief_content_hash": brief.content_hash,
            "catalog_version": AGENT_CATALOG_VERSION,
            "catalog_content_hash": AGENT_CATALOG_CONTENT_HASH,
            "constraints_content_hash": rules["constraints_content_hash"],
            "selected_agent_ids": [agent for agent in AGENT_ORDER if agent in selected],
            "role_constraints": copy.deepcopy(list(rules["role_constraints"])),
            "constraint_issues": copy.deepcopy(list(rules["constraint_issues"])),
            "members": members,
        }

    def _append_team(
        self,
        project: FakeProject,
        content: dict[str, object],
        revision_kind: str,
        account: _Account,
    ) -> dict[str, object]:
        previous = project.team
        version = {
            "id": self._new_id(),
            "project_id": project.id,
            "version_number": len(project.teams) + 1,
            "revision_kind": revision_kind,
            "based_on_version_number": None if previous is None else previous["version_number"],
            **{key: content[key] for key in TEAM_CONTENT_KEYS},
            "content_hash": _digest(content),
            "selected_agent_ids": content["selected_agent_ids"],
            "role_constraints": content["role_constraints"],
            "constraint_issues": content["constraint_issues"],
            "members": content["members"],
            "perspectives": _perspectives(content),
            "created_by_user_id": account.id,
            "created_at": _stamp(self._now()),
        }
        version["content_hash"] = _fake_team_proposal(version).content_hash
        project.teams.append(version)
        return version

    def _generated_team(
        self,
        project: FakeProject,
        brief: _BriefVersion,
        constraints: DeterministicTeamConstraints,
        dropped: Sequence[str] = (),
    ) -> dict[str, object]:
        selected = [agent.value for agent in constraints.mandatory_agent_ids]
        if self.hosted:
            optional = {agent.value for agent in constraints.optional_agent_ids}
            selected.extend(
                agent
                for agent in SUGGESTED_SPECIALISTS
                if agent in optional and agent not in dropped
            )
        return self._team_content(project, brief, selected, (), {}, _rules_payload(constraints))

    def _team_matches(self, project: FakeProject) -> bool:
        team = project.team
        brief = project.brief
        return (
            team is not None
            and brief is not None
            and team["brief_version_id"] == brief.id
            and team["brief_version_number"] == brief.number
            and team["brief_content_hash"] == brief.content_hash
        )

    def _route_team_proposal(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.brief is None:
            raise _Refusal(404, "team_proposal_context_not_found")
        if not self._approvals(project)["brief"]:
            return _Answer(409, {"status": "BRIEF_NOT_APPROVED", "version": None, "issues": []})
        constraints = self._team_rules(project, project.brief)
        self._record(project, "TEAM_PROPOSAL")
        content = self._generated_team(project, project.brief, constraints)
        issues = copy.deepcopy(content["constraint_issues"])
        current = project.team
        if (
            current is not None
            and current["content_hash"]
            == _fake_team_proposal({**content, "project_id": project.id}).content_hash
        ):
            return _Answer(200, {"status": "UNCHANGED", "version": current, "issues": issues})
        version = self._append_team(project, content, "PROPOSER_GENERATED", call.account)
        return _Answer(201, {"status": "CREATED", "version": version, "issues": issues})

    def _team_alignment_issue(self, project: FakeProject | None) -> str | None:
        if project is None or project.team is None:
            return "TEAM_NOT_FOUND"
        if not self._gate_approved(project, "brief"):
            return "BRIEF_APPROVAL_REQUIRED"
        if not self._gate_approved(project, "team"):
            return "TEAM_APPROVAL_REQUIRED"
        if self._team_matches(project):
            return "ALREADY_ALIGNED"
        if not team_selection_can_realign(
            _fake_team_proposal(project.team),
            brief=project.brief.brief,
            project_mode=ProjectMode(project.mode),
        ):
            return "PREPARE_AGAIN"
        return None

    def _route_team_alignment(self, call: _Call) -> _Answer:
        project = self._owned(call)
        issue = self._team_alignment_issue(project)
        return _Answer(
            200,
            {
                "aligned": issue == "ALREADY_ALIGNED",
                "issue": issue,
                "team_version_number": None
                if project is None or project.team is None
                else project.team["version_number"],
                "brief_version_number": None
                if project is None or project.brief is None
                else project.brief.number,
            },
        )

    def _realign_team(self, project: FakeProject, account: _Account) -> dict[str, object]:
        issue = self._team_alignment_issue(project)
        if issue is not None:
            raise _Refusal(404 if issue == "TEAM_NOT_FOUND" else 409, {"code": issue})
        proposal = reanchored_team(
            _fake_team_proposal(project.team),
            brief=_fake_brief_version(project.brief),
            project_mode=ProjectMode(project.mode),
        )
        content = self._team_content(
            project,
            project.brief,
            [agent.value for agent in proposal.selected_agent_ids],
            proposal.to_snapshot()["members"],
            {},
            _rules_payload(proposal.constraints),
            owner=True,
        )
        return self._append_team(project, content, "OWNER_EDITED", account)

    def _route_realign_team(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "TEAM_NOT_FOUND"})
        version = self._realign_team(project, call.account)
        return _Answer(
            200,
            {
                "version_id": version["id"],
                "version_number": version["version_number"],
                "based_on_version_number": version["based_on_version_number"],
                "content_hash": version["content_hash"],
                "gate_approval_required": True,
            },
        )

    def _route_team_history(self, call: _Call) -> _Answer:
        project = self._owned(call)
        return _Answer(200, [] if project is None else list(project.teams))

    def _route_team_current(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.team is None:
            raise _Refusal(404, "team_proposal_not_found")
        return _Answer(200, project.team)

    def _route_team_edit(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("selected_agent_ids", "owner_rationales"))
        selected = fields.texts(
            "selected_agent_ids",
            required=True,
            nullable=False,
            minimum_items=1,
            maximum_items=len(AGENT_ORDER),
        )
        for index, agent in enumerate(selected or []):
            if agent not in AGENT_ORDER:
                fields.errors.append(_error(("body", "selected_agent_ids", index), "enum"))
        raw_rationales = fields.value("owner_rationales", required=False)
        rationales: list[tuple[str, str]] = []
        if raw_rationales is not None:
            if not isinstance(raw_rationales, list) or len(raw_rationales) > len(AGENT_ORDER):
                fields.errors.append(_error(("body", "owner_rationales"), "list_type"))
            else:
                for index, item in enumerate(raw_rationales):
                    location = ("body", "owner_rationales", index)
                    if (
                        not isinstance(item, dict)
                        or set(item) != {"agent_id", "statement"}
                        or item["agent_id"] not in AGENT_ORDER
                        or not isinstance(item["statement"], str)
                        or not 1 <= len(item["statement"]) <= 2000
                        or not " ".join(item["statement"].split())
                    ):
                        fields.errors.append(_error(location, "value_error"))
                        continue
                    rationales.append(
                        (str(item["agent_id"]), " ".join(str(item["statement"]).split()))
                    )
        fields.check()
        selected = selected or []
        empty = {"version": None, "issues": [], "events": []}
        project = self._owned(call)
        if project is None or project.brief is None:
            raise _Refusal(404, "team_proposal_not_found")
        if not self._approvals(project)["brief"]:
            return _Answer(409, {"status": "BRIEF_NOT_APPROVED", **empty})
        current = project.team
        if current is None:
            raise _Refusal(404, "team_proposal_not_found")
        if not self._team_matches(project):
            return _Answer(409, {"status": "PROPOSAL_STALE", **empty})
        issues = _team_issues(current, selected, rationales)
        if issues:
            return _Answer(
                422, {"status": "REJECTED", "version": None, "issues": issues, "events": []}
            )
        content = self._team_content(
            project,
            project.brief,
            selected,
            list(current["members"]),
            dict(rationales),
            {key: current[key] for key in RULE_KEYS},
            owner=True,
        )
        if _digest(content) == current["content_hash"]:
            return _Answer(
                200, {"status": "UNCHANGED", "version": current, "issues": [], "events": []}
            )
        version = self._append_team(project, content, "OWNER_EDITED", call.account)
        events = []
        latest = project.gates.get("team")
        reference = self._require_reference(project, "team")
        if (
            latest is not None
            and latest.status not in {HumanGateStatus.STALE, HumanGateStatus.CANCELLED}
            and latest.artifact != reference
        ):
            stale = mark_human_gate_stale(
                latest,
                current_artifact=reference,
                occurred_at=self._now(),
                event_id=UUID(self._new_id()),
            )
            if stale.status is HumanGateTransitionStatus.APPLIED and stale.event is not None:
                self._save_gate(project, "team", stale.gate, stale.event)
                events.append(_event_payload(stale.event))
        return _Answer(
            201, {"status": "UPDATED", "version": version, "issues": [], "events": events}
        )

    def _route_team_readiness(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, "project_not_found")
        approvals = self._approvals(project)
        if not approvals["brief"]:
            status = "BRIEF_APPROVAL_REQUIRED"
        elif not self._team_matches(project):
            status = "TEAM_PROPOSAL_REQUIRED"
        elif not approvals["team"]:
            status = "TEAM_APPROVAL_REQUIRED"
        else:
            status = "READY_FOR_MAIN_WORKFLOW"
        return _Answer(200, {"status": status})

    def _team_gate_context(self, call: _Call, missing: str) -> tuple[FakeProject | None, str]:
        project = self._owned(call)
        if project is None or project.brief is None:
            raise _Refusal(404, missing)
        if not self._approvals(project)["brief"]:
            return None, "BRIEF_NOT_APPROVED"
        if project.team is None:
            raise _Refusal(404, missing)
        if not self._team_matches(project):
            return None, "PROPOSAL_STALE"
        return project, ""

    def _route_team_gate_submit(self, call: _Call) -> _Answer:
        project, blocked = self._team_gate_context(call, "agent_team_gate_context_not_found")
        if project is None:
            return _Answer(409, {"status": blocked, "gate": None, "events": [], "issue": None})
        status, gate, events, issue = self._submit_gate(
            project, "team", self._require_reference(project, "team")
        )
        return _Answer(
            _submission_status(status),
            {
                "status": status,
                "gate": _gate_payload(gate),
                "events": [_event_payload(event) for event in events],
                "issue": issue,
            },
        )

    def _route_team_gate_current(self, call: _Call) -> _Answer:
        project = self._owned(call)
        gate = None if project is None else project.gates.get("team")
        if gate is None:
            raise _Refusal(404, "agent_team_gate_not_found")
        return _Answer(200, _gate_payload(gate))

    def _route_team_gate_decision(self, call: _Call) -> _Answer:
        action, reason = _gate_decision(call, DECISION_ACTIONS, literal=True, maximum=2000)
        project, blocked = self._team_gate_context(call, "agent_team_gate_not_found")
        if project is None:
            return _Answer(409, {"status": blocked, "gate": None, "event": None, "issue": None})
        status, gate, event, issue = self._decide_gate(
            project, "team", self._require_reference(project, "team"), action, reason
        )
        if status == "GATE_NOT_FOUND":
            raise _Refusal(404, "agent_team_gate_not_found")
        return _Answer(
            200 if status == "APPLIED" else 409,
            {
                "status": status,
                "gate": _gate_payload(gate),
                "event": None if event is None else _event_payload(event),
                "issue": issue,
            },
        )

    def _route_team_gate_events(self, call: _Call) -> _Answer:
        return _Answer(200, self._gate_events(self._owned(call), "team", call.params["gate_id"]))


def _reason_payload(reason: TeamSelectionReason) -> dict[str, object]:
    return {
        "code": reason.code.value,
        "evidence": {
            "fields": [item.value for item in reason.evidence.fields],
            "terms": list(reason.evidence.terms),
        },
    }


def _rules_payload(constraints: DeterministicTeamConstraints) -> dict[str, object]:
    return {
        "constraints_content_hash": constraints.content_hash,
        "role_constraints": constraints.to_snapshot()["role_constraints"],
        "constraint_issues": [
            {
                "code": issue.code.value,
                "agent_id": issue.agent_id.value,
                "mandatory_reasons": [_reason_payload(item) for item in issue.mandatory_reasons],
                "impossible_reasons": [_reason_payload(item) for item in issue.impossible_reasons],
            }
            for issue in constraints.issues
        ],
    }


def _perspectives(content: Mapping[str, object]) -> list[dict[str, object]]:
    views = perspective_views(_team_constraints(content), content["selected_agent_ids"])
    return [view.to_snapshot() for view in views]


def _rule_justifications(constraint: Mapping[str, object]) -> list[dict[str, object]]:
    return [
        {
            "kind": "DETERMINISTIC_RULE",
            "code": reason["code"],
            "evidence_fields": list(reason["evidence"]["fields"]),
            "evidence_terms": list(reason["evidence"]["terms"]),
            "statement": None,
        }
        for reason in constraint["reasons"]
    ]


def _justification(
    kind: str,
    code: str,
    fields: Sequence[str] = (),
    *,
    statement: str | None = None,
) -> dict[str, object]:
    return {
        "kind": kind,
        "code": code,
        "evidence_fields": list(fields),
        "evidence_terms": [],
        "statement": statement,
    }


def _team_issues(
    current: Mapping[str, object],
    selected: Sequence[str],
    rationales: Sequence[tuple[str, str]],
) -> list[dict[str, object]]:
    issues = []
    for agent in sorted(set(selected)):
        if selected.count(agent) > 1:
            issues.append({"code": "DUPLICATE_AGENT", "agent_id": agent})
    named = [agent for agent, _ in rationales]
    for agent in sorted(set(named)):
        if named.count(agent) > 1:
            issues.append({"code": "DUPLICATE_RATIONALE", "agent_id": agent})
    mandatory = {
        constraint["agent_id"]
        for constraint in current["role_constraints"]
        if constraint["kind"] == "MANDATORY"
    }
    issues.extend(
        {"code": "MANDATORY_AGENT_MISSING", "agent_id": agent}
        for agent in mandatory - set(selected)
    )
    blocked = {
        constraint["agent_id"]
        for constraint in current["role_constraints"]
        if constraint["kind"] == "IMPOSSIBLE"
    }
    issues.extend(
        {"code": "AGENT_NOT_SELECTABLE", "agent_id": agent} for agent in set(selected) & blocked
    )
    added = set(selected) - set(current["selected_agent_ids"])
    issues.extend({"code": "UNUSED_RATIONALE", "agent_id": agent} for agent in set(named) - added)
    return sorted(
        issues, key=lambda issue: (AGENT_ORDER.index(str(issue["agent_id"])), str(issue["code"]))
    )


def _fake_brief_version(version: _BriefVersion):
    from orchestwin.projects.briefs import ProjectBriefVersion

    return ProjectBriefVersion(
        id=UUID(version.id),
        project_id=UUID(version.payload["project_id"]),
        version_number=version.number,
        schema_version=version.brief.SCHEMA_VERSION,
        brief=version.brief,
        content_hash=version.brief.content_hash,
        created_by_user_id=UUID(version.payload["created_by_user_id"]),
        created_at=datetime.fromisoformat(version.payload["created_at"]),
    )
