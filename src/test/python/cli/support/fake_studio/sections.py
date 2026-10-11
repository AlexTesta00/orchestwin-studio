from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import UUID

from orchestwin.agents.catalog import AGENT_CATALOG_CONTENT_HASH, AGENT_CATALOG_VERSION
from orchestwin.projects.progress import ArtifactVersion, ProjectStage
from orchestwin.projects.sections import (
    BriefFacts,
    DesignFacts,
    FolderFacts,
    ProjectSections,
    RequirementsFacts,
    SectionBlock,
    SectionFacts,
    SectionState,
    TeamFacts,
    UserTwinsFacts,
    project_sections,
    requirements_actor_codes,
)
from orchestwin.workflow.gates import HumanGateStatus, HumanGateType, next_human_gate_iteration

from .common import (
    _artifact_version,
    _by_id,
    _cited_ids,
    _copy,
    _fake_modeling,
    _fake_requirements,
    _fake_twin_profile,
    _identifiers,
    _key,
    _plain_reference,
    _reference_key,
    _reference_version,
    _stamp,
    _twin_reference,
)
from .projects import _alignment_result, _gesture_issue, _gesture_status, _refusal_code
from .values import ALIGNMENT_REASON, FOLDER_SECTIONS, SECTION_STAGES, _Answer, _Refusal

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject
    from .values import _Account


DESIGN_ALIGNMENT_STATES = frozenset(
    {SectionState.FINE, SectionState.UPDATE_AVAILABLE, SectionState.TO_UPDATE}
)
SPECIFICATION_ITEMS = ("requirements", "user_stories", "acceptance_criteria")


class _SectionRoutes:
    def _sections(self, project: FakeProject) -> dict[str, object]:
        return self._project_sections(project).to_snapshot()

    def _project_sections(self, project: FakeProject, *, learning: bool = True) -> ProjectSections:
        facts = self._section_facts(project)
        draft = project_sections(facts)
        twins = facts.user_twins
        if (
            learning
            and twins is not None
            and draft.section(ProjectStage.USER_TWINS).state is SectionState.FINE
        ):
            facts = replace(facts, user_twins=replace(twins, learned=self._twins_learned(project)))
        design = draft.section(ProjectStage.DESIGN)
        current, requirements = project.design, project.specification
        if (
            facts.design is not None
            and current is not None
            and requirements is not None
            and design.state in DESIGN_ALIGNMENT_STATES
            and design.blocked is not SectionBlock.UPSTREAM_NOT_READY
        ):
            facts = replace(
                facts,
                design=replace(
                    facts.design,
                    missing_codes=tuple(self._missing_codes(project, current, requirements)),
                    uncovered_codes=tuple(self._uncovered_codes(current, requirements)),
                ),
            )
        return project_sections(facts)

    def _section_facts(self, project: FakeProject) -> SectionFacts:
        brief = project.artifact("brief")
        team, snapshot = project.team, project.snapshot
        requirements, design = project.specification, project.design
        return SectionFacts(
            brief=None
            if brief is None
            else BriefFacts(
                version=_artifact_version(brief), approved=self._gate_approved(project, "brief")
            ),
            team=None
            if team is None
            else TeamFacts(
                version=_artifact_version(team),
                approved=self._gate_approved(project, "team"),
                brief=_team_brief_version(team),
                alignable=self._team_alignment_issue(project) is None,
            ),
            user_twins=None if snapshot is None else self._twins_facts(project, snapshot),
            requirements=None
            if requirements is None
            else self._requirements_facts(project, requirements),
            design=None if design is None else self._design_facts(project, design),
            folder=None
            if not project.packages
            else FolderFacts(
                version_number=int(project.packages[-1]["version_number"]),
                stages={
                    FOLDER_SECTIONS[stage]: held for stage, held in project.folders[-1].items()
                },
            ),
            design_approved_once=self._first_pass_complete(project),
        )

    def _twins_facts(self, project: FakeProject, snapshot: Mapping[str, object]) -> UserTwinsFacts:
        body = snapshot["snapshot"]
        return UserTwinsFacts(
            version=_artifact_version(snapshot),
            approved=self._gate_approved(project, "twins"),
            brief=_reference_version(body["project_brief_reference"]),
            team=_reference_version(body["agent_team_reference"]),
            twins=_twin_versions(body["twin_versions"]),
            archetypes_current=self._archetypes_current(project, snapshot),
        )

    def _requirements_facts(
        self, project: FakeProject, version: Mapping[str, object]
    ) -> RequirementsFacts:
        specification = version["specification"]
        return RequirementsFacts(
            version=_artifact_version(version),
            approved=self._gate_approved(project, "requirements"),
            brief=_reference_version(specification["project_brief_reference"]),
            team=_reference_version(specification["agent_team_reference"]),
            user_modeling=_reference_version(specification["user_modeling_reference"]),
            twins=_twin_versions(specification["user_twin_references"]),
            cited_twin_ids=frozenset(
                UUID(identifier) for identifier in _referenced_twins(specification)
            ),
            revision_pending=self._pending_requirements_diff(project) is not None,
            actor_codes=requirements_actor_codes(_fake_requirements(specification)),
        )

    def _design_facts(self, project: FakeProject, version: Mapping[str, object]) -> DesignFacts:
        package = version["package"]
        grounding = package["grounding"]
        has_mockup = (
            package["owner_selected_alternative_id"] is not None
            and package["prototype"] is not None
        )
        return DesignFacts(
            version=_artifact_version(version),
            approved=self._gate_approved(project, "design"),
            requirements=_reference_version(grounding["requirements_reference"]),
            team=_reference_version(grounding["agent_team_reference"]),
            user_modeling=_reference_version(grounding["user_modeling_reference"]),
            twins=_twin_versions(grounding["user_twin_references"]),
            revision_pending=self._pending_design_diff(project) is not None,
            has_mockup=has_mockup,
            reviewed=has_mockup
            and any(run["design_version_id"] == version["id"] for run in project.runs),
        )

    def _first_pass_complete(self, project: FakeProject) -> bool:
        return any(
            event.resulting_status is HumanGateStatus.APPROVED
            and event.artifact.gate_type is HumanGateType.DESIGN
            for events in project.gate_events.values()
            for event in events
        )

    def _twins_learned(self, project: FakeProject) -> bool:
        return any(
            self._pending_update(project, str(twin["twin_id"])) is not None
            or (self.hosted and any(self._new_material(project, str(twin["twin_id"]))))
            for twin in self._approved_twins(project)
        )

    def _grounded_requirements(
        self, project: FakeProject, design: Mapping[str, object]
    ) -> dict[str, object] | None:
        reference = design["package"]["grounding"]["requirements_reference"]
        return _by_id(project.requirements, str(reference["artifact_id"]))

    def _missing_codes(
        self,
        project: FakeProject,
        design: Mapping[str, object],
        requirements: Mapping[str, object],
    ) -> list[str]:
        grounded = self._grounded_requirements(project, design)
        if grounded is None:
            return []
        cited = _cited_ids(design["package"])
        current = {
            str(item["id"])
            for kind in SPECIFICATION_ITEMS
            for item in requirements["specification"][kind]
        }
        return [
            code
            for kind in SPECIFICATION_ITEMS
            for code in sorted(
                str(item["code"])
                for item in grounded["specification"][kind]
                if str(item["id"]) in cited and str(item["id"]) not in current
            )
        ]

    def _uncovered_codes(
        self, design: Mapping[str, object], requirements: Mapping[str, object]
    ) -> list[str]:
        prototype = design["package"].get("prototype")
        if prototype is None:
            return []
        cited = {
            str(identifier)
            for screen in prototype["screens"]
            for holder in (screen, *screen["elements"])
            for identifier in holder["requirement_ids"]
        }
        return sorted(
            str(item["code"])
            for item in requirements["specification"]["requirements"]
            if str(item["id"]) not in cited
        )

    def _route_sections(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        document = self._sections(project)
        if project.workflow_decisions or project.provided_prototypes:
            document = {**document, "workflow_inputs": self._workflow_inputs(project)}
        return _Answer(200, document)

    def _route_align_sections(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        answer = self._aligned_sections(project, call.account)
        project.gestures.append(_copy(answer))
        return _Answer(200, answer)

    def _aligned_sections(self, project: FakeProject, account: _Account) -> dict[str, object]:
        before = self._project_sections(project, learning=False)
        results: list[dict[str, object]] = []
        for key in before.alignment.sections:
            if results and results[-1]["outcome"] != "ALIGNED":
                results.append(_alignment_result(key.value, "SKIPPED"))
                continue
            section = before.section(key)
            if section.blocked is not None:
                results.append(
                    _alignment_result(
                        key.value,
                        "BLOCKED",
                        issue=_gesture_issue(section.blocked.value),
                        codes=section.codes,
                    )
                )
                continue
            results.append(self._update_section(project, key.value, account))
        return {
            "status": _gesture_status(results),
            "results": results,
            "sections": self._sections(project),
        }

    def _update_section(
        self, project: FakeProject, key: str, account: _Account
    ) -> dict[str, object]:
        stage = SECTION_STAGES[key]
        gate = project.gates.get(stage)
        if gate is not None and next_human_gate_iteration(gate) is None:
            return _alignment_result(key, "BLOCKED", issue="ITERATION_LIMIT_REACHED")
        realign = {
            "TEAM": self._realign_team,
            "USER_TWINS": self._realign_twins,
            "REQUIREMENTS": self._realign_requirements,
            "DESIGN": self._realign_design,
        }[key]
        try:
            realign(project, account)
        except _Refusal as refusal:
            code, missing = _refusal_code(refusal)
            return _alignment_result(key, "BLOCKED", issue=_gesture_issue(code), codes=missing)
        reference = self._require_reference(project, stage)
        submitted, current, _, _ = self._submit_gate(project, stage, reference)
        if submitted == "ALREADY_APPROVED" and current is not None:
            return _alignment_result(key, "ALIGNED", version_number=current.artifact.version)
        if submitted not in ("SUBMITTED", "ALREADY_PENDING"):
            return _alignment_result(key, "BLOCKED", issue=_gesture_issue(submitted))
        status, decided, _, issue = self._decide_gate(
            project, stage, reference, "APPROVE", ALIGNMENT_REASON
        )
        if status != "APPLIED" or decided is None:
            return _alignment_result(key, "BLOCKED", issue=_gesture_issue(issue or status))
        return _alignment_result(key, "ALIGNED", version_number=decided.artifact.version)

    def _twins_alignment_issue(self, project: FakeProject | None) -> str | None:
        if project is None or project.snapshot is None:
            return "USER_TWINS_NOT_FOUND"
        approvals = self._approvals(project)
        if not approvals["brief"]:
            return "BRIEF_APPROVAL_REQUIRED"
        if not approvals["team"]:
            return "TEAM_APPROVAL_REQUIRED"
        if not self._archetypes_current(project, project.snapshot):
            return "ARCHETYPES_CHANGED"
        if any(update["status"] == "PROPOSED" for update in project.updates):
            return "USER_TWIN_REVISION_PENDING"
        if self._snapshot_current(project, project.snapshot):
            return "ALREADY_ALIGNED"
        return None

    def _route_twins_alignment(self, call: _Call) -> _Answer:
        project = self._owned(call)
        issue = self._twins_alignment_issue(project)
        snapshot = None if project is None else project.snapshot
        brief = None if project is None else project.brief
        team = None if project is None else project.team
        return _Answer(
            200,
            {
                "aligned": issue == "ALREADY_ALIGNED",
                "issue": issue,
                "snapshot_version_number": None if snapshot is None else snapshot["version_number"],
                "brief_version_number": None if brief is None else brief.number,
                "team_version_number": None if team is None else team["version_number"],
            },
        )

    def _route_realign_twins(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "USER_TWINS_NOT_FOUND"})
        version = self._realign_twins(project, call.account)
        return _Answer(
            201,
            {
                "snapshot_version_id": version["id"],
                "snapshot_version_number": version["version_number"],
                "based_on_version_number": version["based_on_version_number"],
                "content_hash": version["content_hash"],
                "twin_count": len(version["snapshot"]["twin_versions"]),
                "gate_approval_required": True,
            },
        )

    def _realign_twins(self, project: FakeProject, account: _Account) -> dict[str, object]:
        issue = self._twins_alignment_issue(project)
        if issue is not None:
            raise _Refusal(404 if issue == "USER_TWINS_NOT_FOUND" else 409, {"code": issue})
        snapshot, brief, team = project.snapshot, project.brief, project.team
        brief_reference = {
            "artifact_id": brief.id,
            "version_number": brief.number,
            "content_hash": brief.content_hash,
        }
        team_reference = _plain_reference(team)
        twins = []
        for twin in snapshot["snapshot"]["twin_versions"]:
            versions = project.twins[str(twin["twin_id"])]
            previous = int(versions[-1]["version_number"])
            profile = copy.deepcopy(twin["profile"])
            profile["project_brief_reference"] = dict(brief_reference)
            profile["agent_team_reference"] = dict(team_reference)
            profile["catalog_version"] = AGENT_CATALOG_VERSION
            profile["catalog_content_hash"] = AGENT_CATALOG_CONTENT_HASH
            version = {
                "id": self._new_id(),
                "project_id": project.id,
                "twin_id": twin["twin_id"],
                "version_number": previous + 1,
                "based_on_version_number": previous,
                "content_hash": _fake_twin_profile(profile).content_hash,
                "created_by_user_id": account.id,
                "created_at": _stamp(self._now()),
                "profile": profile,
            }
            versions.append(version)
            twins.append(version)
        twins.sort(key=lambda item: str(item["twin_id"]))
        body = copy.deepcopy(snapshot["snapshot"])
        body["project_brief_reference"] = brief_reference
        body["agent_team_reference"] = team_reference
        body["catalog_version"] = AGENT_CATALOG_VERSION
        body["catalog_content_hash"] = AGENT_CATALOG_CONTENT_HASH
        body["twin_versions"] = twins
        version = {
            "id": self._new_id(),
            "project_id": project.id,
            "version_number": int(snapshot["version_number"]) + 1,
            "based_on_version_number": snapshot["version_number"],
            "content_hash": _fake_modeling(body).content_hash,
            "created_by_user_id": account.id,
            "created_at": _stamp(self._now()),
            "snapshot": body,
        }
        project.snapshots.append(version)
        return version

    def _requirements_alignment_issue(self, project: FakeProject | None) -> str | None:
        current = None if project is None else project.specification
        if project is None or current is None:
            return "REQUIREMENTS_NOT_FOUND"
        snapshot = project.snapshot
        if snapshot is None:
            return "USER_TWINS_REQUIRED"
        if not self._approvals(project)["twins"]:
            return "USER_TWINS_APPROVAL_REQUIRED"
        specification = current["specification"]
        if _requirements_aligned(specification, snapshot):
            return "REQUIREMENTS_ALREADY_ALIGNED"
        if not _referenced_twins(specification) <= _twin_ids(snapshot["snapshot"]["twin_versions"]):
            return "TWIN_NO_LONGER_AVAILABLE"
        if self._pending_requirements_diff(project) is not None:
            return "REQUIREMENTS_REVISION_PENDING"
        return None

    def _route_requirements_alignment(self, call: _Call) -> _Answer:
        project = self._owned(call)
        current = None if project is None else project.specification
        snapshot = None if project is None else project.snapshot
        return _Answer(
            200,
            {
                "aligned": current is not None
                and snapshot is not None
                and _requirements_aligned(current["specification"], snapshot),
                "issue": self._requirements_alignment_issue(project),
                "requirements_version_number": None
                if current is None
                else current["version_number"],
                "snapshot_version_number": None if snapshot is None else snapshot["version_number"],
                "twins_approved": project is not None and self._approvals(project)["twins"],
            },
        )

    def _route_realign_requirements(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "REQUIREMENTS_NOT_FOUND"})
        version = self._realign_requirements(project, call.account)
        specification = version["specification"]
        return _Answer(
            201,
            {
                "version_id": version["id"],
                "version_number": version["version_number"],
                "based_on_version_number": version["based_on_version_number"],
                "content_hash": version["content_hash"],
                "user_modeling_version_number": specification["user_modeling_reference"][
                    "version_number"
                ],
                "twin_count": len(specification["user_twin_references"]),
                "gate_approval_required": True,
            },
        )

    def _realign_requirements(self, project: FakeProject, account: _Account) -> dict[str, object]:
        issue = self._requirements_alignment_issue(project)
        if issue is not None:
            raise _Refusal(404 if issue == "REQUIREMENTS_NOT_FOUND" else 409, {"code": issue})
        snapshot = project.snapshot
        body = snapshot["snapshot"]
        specification = copy.deepcopy(project.specification["specification"])
        twins = [_twin_reference(twin) for twin in body["twin_versions"]]
        current = {str(twin["twin_id"]): twin for twin in twins}
        specification["project_brief_reference"] = {
            "kind": "PROJECT_BRIEF",
            **_reference_fields(body["project_brief_reference"]),
        }
        specification["agent_team_reference"] = {
            "kind": "AGENT_TEAM",
            **_reference_fields(body["agent_team_reference"]),
        }
        specification["user_modeling_reference"] = {
            "kind": "USER_MODELING",
            **_plain_reference(snapshot),
        }
        specification["catalog_version"] = body["catalog_version"]
        specification["catalog_content_hash"] = body["catalog_content_hash"]
        specification["user_twin_references"] = twins
        for requirement in specification["requirements"]:
            requirement["user_twin_references"] = _sorted_twins(
                current[str(reference["twin_id"])]
                for reference in requirement["user_twin_references"]
            )
        for story in specification["user_stories"]:
            story["user_twin_reference"] = dict(
                current[str(story["user_twin_reference"]["twin_id"])]
            )
        for scenario in specification["scenarios"]:
            scenario["actor"] = dict(current[str(scenario["actor"]["twin_id"])])
        return self._append_requirements(project, specification, account)

    def _design_alignment_issue(self, project: FakeProject | None) -> str | None:
        design = None if project is None else project.design
        if project is None or design is None:
            return "DESIGN_NOT_FOUND"
        requirements = project.specification
        if requirements is None or not self._gate_approved(project, "requirements"):
            return "REQUIREMENTS_APPROVAL_REQUIRED"
        if _design_aligned(design, requirements):
            return "ALREADY_ALIGNED"
        if self._missing_codes(project, design, requirements):
            return "REQUIREMENT_NO_LONGER_AVAILABLE"
        if _twin_ids(design["package"]["grounding"]["user_twin_references"]) != _twin_ids(
            requirements["specification"]["user_twin_references"]
        ):
            return "TWIN_SET_CHANGED"
        if self._pending_design_diff(project) is not None:
            return "DESIGN_REVISION_PENDING"
        return None

    def _route_design_alignment(self, call: _Call) -> _Answer:
        project = self._owned(call)
        design = None if project is None else project.design
        requirements = None if project is None else project.specification
        known = design is not None and requirements is not None
        grounding = None if design is None else design["package"]["grounding"]
        return _Answer(
            200,
            {
                "aligned": known and _design_aligned(design, requirements),
                "issue": self._design_alignment_issue(project),
                "design_version_number": None if design is None else design["version_number"],
                "grounded_requirements_version_number": None
                if grounding is None
                else grounding["requirements_reference"]["version_number"],
                "requirements_version_number": None
                if requirements is None
                else requirements["version_number"],
                "missing_codes": self._missing_codes(project, design, requirements)
                if known
                else [],
                "uncovered_codes": self._uncovered_codes(design, requirements) if known else [],
            },
        )

    def _route_realign_design(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "DESIGN_NOT_FOUND"})
        version = self._realign_design(project, call.account)
        requirements = project.specification
        return _Answer(
            201,
            {
                "version_id": version["id"],
                "version_number": version["version_number"],
                "based_on_version_number": version["based_on_version_number"],
                "content_hash": version["content_hash"],
                "requirements_version_number": requirements["version_number"],
                "gate_approval_required": True,
                "uncovered_codes": self._uncovered_codes(version, requirements),
            },
        )

    def _realign_design(self, project: FakeProject, account: _Account) -> dict[str, object]:
        issue = self._design_alignment_issue(project)
        if issue == "REQUIREMENT_NO_LONGER_AVAILABLE":
            missing = self._missing_codes(project, project.design, project.specification)
            raise _Refusal(409, {"code": issue, "missing_codes": missing})
        if issue is not None:
            raise _Refusal(404 if issue == "DESIGN_NOT_FOUND" else 409, {"code": issue})
        requirements = project.specification
        specification = requirements["specification"]
        twins = {str(twin["twin_id"]): twin for twin in specification["user_twin_references"]}
        package = copy.deepcopy(project.design["package"])
        package["grounding"] = _requirements_grounding(requirements)
        for alternative in package["alternatives"]:
            alternative["user_twin_references"] = [
                dict(twins[str(reference["twin_id"])])
                for reference in alternative["user_twin_references"]
            ]
        for critique in package["critiques"]:
            twin_id = str(critique["user_twin_reference"]["twin_id"])
            critique["user_twin_reference"] = dict(twins[twin_id])
        return self._append_design(project, package, account)


def _reference_fields(reference: Mapping[str, object]) -> dict[str, object]:
    return {
        "artifact_id": reference["artifact_id"],
        "version_number": reference["version_number"],
        "content_hash": reference["content_hash"],
    }


def _twin_ids(items: Iterable[Mapping[str, object]]) -> frozenset[str]:
    return frozenset(str(item["twin_id"]) for item in items)


def _sorted_twins(items: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    return sorted((dict(item) for item in items), key=lambda item: str(item["twin_id"]))


def _referenced_twins(specification: Mapping[str, object]) -> frozenset[str]:
    return frozenset(
        {
            *(
                str(reference["twin_id"])
                for requirement in specification["requirements"]
                for reference in requirement["user_twin_references"]
            ),
            *(
                str(story["user_twin_reference"]["twin_id"])
                for story in specification["user_stories"]
            ),
            *(str(scenario["actor"]["twin_id"]) for scenario in specification["scenarios"]),
        }
    )


def _on_snapshot(
    specification: Mapping[str, object], snapshot: Mapping[str, object] | None
) -> bool:
    if snapshot is None:
        return False
    twins = (_twin_reference(twin) for twin in snapshot["snapshot"]["twin_versions"])
    return _reference_key(specification["user_modeling_reference"]) == _key(
        snapshot
    ) and _sorted_twins(specification["user_twin_references"]) == _sorted_twins(twins)


def _requirements_aligned(
    specification: Mapping[str, object], snapshot: Mapping[str, object]
) -> bool:
    body = snapshot["snapshot"]
    return (
        _reference_key(specification["project_brief_reference"])
        == _reference_key(body["project_brief_reference"])
        and _reference_key(specification["agent_team_reference"])
        == _reference_key(body["agent_team_reference"])
        and (specification["catalog_version"], specification["catalog_content_hash"])
        == (body["catalog_version"], body["catalog_content_hash"])
        and _on_snapshot(specification, snapshot)
    )


def _requirements_grounding(requirements: Mapping[str, object]) -> dict[str, object]:
    specification = requirements["specification"]
    return {
        "requirements_reference": {
            "kind": "REQUIREMENTS_SPECIFICATION",
            **_plain_reference(requirements),
        },
        "agent_team_reference": {
            "kind": "AGENT_TEAM",
            **_reference_fields(specification["agent_team_reference"]),
        },
        "user_modeling_reference": {
            "kind": "USER_MODELING",
            **_reference_fields(specification["user_modeling_reference"]),
        },
        "catalog": {
            "version": specification["catalog_version"],
            "content_hash": specification["catalog_content_hash"],
        },
        "requirement_ids": _identifiers(specification["requirements"]),
        "user_story_ids": _identifiers(specification["user_stories"]),
        "acceptance_criterion_ids": _identifiers(specification["acceptance_criteria"]),
        "user_twin_references": _sorted_twins(specification["user_twin_references"]),
    }


def _design_aligned(design: Mapping[str, object], requirements: Mapping[str, object]) -> bool:
    return design["package"]["grounding"] == _requirements_grounding(requirements)


def _twin_versions(items: Iterable[Mapping[str, object]]) -> frozenset[ArtifactVersion]:
    return frozenset(
        ArtifactVersion(
            UUID(str(item["twin_id"])), int(item["version_number"]), str(item["content_hash"])
        )
        for item in items
    )


def _team_brief_version(team: Mapping[str, object]) -> ArtifactVersion:
    return ArtifactVersion(
        UUID(str(team["brief_version_id"])),
        int(team["brief_version_number"]),
        str(team["brief_content_hash"]),
    )
