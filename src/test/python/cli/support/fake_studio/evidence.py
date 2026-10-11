from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import TYPE_CHECKING
from uuid import UUID

from orchestwin.api.research_evidence import EvidenceBody
from orchestwin.projects.evidence_application import evidence_profile, withdrawn_observation
from orchestwin.projects.research_evidence import (
    EvidenceVersion,
    ResearchEvidenceError,
    evidence_content_hash,
    normalize_evidence_text,
)
from orchestwin.workflow.gates import (
    HumanGateAction,
    HumanGateStatus,
    create_human_gate,
    mark_human_gate_stale,
    transition_human_gate,
)

from .common import (
    _fake_design,
    _fake_modeling,
    _fake_requirements,
    _fake_team_proposal,
    _fake_twin_profile,
    _stamp,
)
from .fields import _Fields
from .values import FOLDER_SECTIONS, GATE_TYPES, STAGES, _Answer, _iso, _Refusal

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject


class _EvidenceRoutes:
    def _evidence_citations(self, project: FakeProject) -> list[dict[str, object]]:
        return [
            {
                "twin_id": row["twin_id"],
                "twin_version": row["twin_version"],
                "field": row["field"],
                "effect": row["change"]["effect"],
                "citation": copy.deepcopy(row["change"]["citation"]),
                "status": "ACTIVE" if row["retired_at"] is None else "RETIRED",
                **(
                    {"imported_from": copy.deepcopy(row["change"]["imported_from"])}
                    if row["change"].get("imported_from") is not None
                    else {}
                ),
            }
            for row in project.evidence_changes
        ]

    def _evidence_dossier(self, project: FakeProject) -> dict[str, object]:
        result = {
            "kind": "orchestwin.research-evidence",
            "schema_version": 1,
            "project_id": project.id,
            "evidence": copy.deepcopy(project.evidence_versions),
            "citations": self._evidence_citations(project),
        }
        present = self._publishable(project)
        if project.evidence_versions and any(
            project.artifact(stage) is not None for stage in STAGES if stage not in present
        ):
            sections = self._project_sections(project)
            result["omitted_sections"] = []
            for stage in STAGES:
                if stage in present or project.artifact(stage) is None:
                    continue
                section = sections.section(FOLDER_SECTIONS[stage])
                result["omitted_sections"].append(
                    {
                        "stage": stage,
                        "reason": ",".join(reason.value for reason in section.reasons)
                        or "APPROVAL_REQUIRED",
                        "affected_codes": {
                            key: list(values) for key, values in section.affected_codes.items()
                        },
                    }
                )
        return result

    def _evidence_source(self, project: FakeProject, source_id: str, version: int | None = None):
        found = [
            item
            for item in project.evidence_versions
            if item["id"] == source_id and (version is None or item["version"] == version)
        ]
        if not found:
            raise _Refusal(404, {"code": "EVIDENCE_NOT_FOUND"})
        return max(found, key=lambda item: item["version"])

    def _route_evidence_list(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        values = project.evidence_versions
        if call.query.get("all") != ["true"]:
            latest = {item["id"]: item for item in values}
            values = [
                item
                for item in latest.values()
                if item["status"] == "ACTIVE" and item["text_available"]
            ]
        return _Answer(
            200,
            {
                "project_id": project.id,
                "evidence": copy.deepcopy(values),
                "citations": self._evidence_citations(project),
            },
        )

    def _why_document(self, project: FakeProject, *, validation_context=False) -> dict[str, object]:
        from orchestwin.why import build_why_document

        return build_why_document(
            project_id=project.id,
            validation_context=validation_context,
            stages={
                "brief": [
                    {**item.payload, "brief": item.brief.to_snapshot()} for item in project.briefs
                ],
                "team": [
                    {
                        **{name: value for name, value in item.items() if name != "perspectives"},
                        "proposal": _fake_team_proposal(item).to_snapshot(),
                    }
                    for item in project.teams
                ],
                "twins": [
                    {**item, "snapshot": _fake_modeling(item["snapshot"]).to_snapshot()}
                    for item in project.snapshots
                ],
                "requirements": [
                    {
                        **item,
                        "specification": _fake_requirements(item["specification"]).to_snapshot(),
                    }
                    for item in project.requirements
                ],
                "design": [
                    {**item, "package": _fake_design(item["package"]).to_snapshot()}
                    for item in project.designs
                ],
            },
            evidence={
                "evidence": project.evidence_versions,
                "citations": self._evidence_citations(project),
            },
            evaluations=[{"runs": project.runs, "decisions": project.finding_decisions}],
            hypotheses=project.validation_hypotheses,
            outcomes=project.validation_outcomes,
            learning={"twins": self._learning_entries(project)},
            workflow_inputs=self._workflow_inputs(project),
            mockups=[
                item
                for item in project.mockups.values()
                if item.get("base_reference") and item.get("audit_reference")
            ],
        )

    def _route_why_document(self, call: _Call) -> _Answer:
        return _Answer(200, self._why_document(self._code_project(call)))

    def seed_validation_records(self, project: FakeProject, *, hypotheses=(), outcomes=()):
        from orchestwin.artifacts.human_validation import (
            hypothesis_from_snapshot,
            outcome_from_snapshot,
        )

        for restore, items in (
            (hypothesis_from_snapshot, hypotheses),
            (outcome_from_snapshot, outcomes),
        ):
            for item in items:
                record = restore(item).to_snapshot()
                if record["project_id"] != project.id or record["owner_user_id"] != str(
                    project.account.id
                ):
                    raise ValueError("validation fixture must match its project and owner")
        project.validation_hypotheses = copy.deepcopy(list(hypotheses))
        project.validation_outcomes = copy.deepcopy(list(outcomes))

    def _route_validation(self, call: _Call) -> _Answer:
        from orchestwin.validation import validation_overview

        project = self._code_project(call)
        document = validation_overview(
            document=self._why_document(project, validation_context=True),
            hypotheses=project.validation_hypotheses,
            outcomes=project.validation_outcomes,
            evidence={"evidence": project.evidence_versions},
        )
        if project.workflow_decisions or project.provided_prototypes:
            document = {**document, "workflow_inputs": self._workflow_inputs(project)}
        return _Answer(200, document)

    def _route_validation_walkthrough(self, call: _Call) -> _Answer:
        from orchestwin.validation import ValidationError, scenario_walkthrough

        try:
            return _Answer(
                200,
                scenario_walkthrough(
                    self._why_document(self._code_project(call), validation_context=True),
                    call.query.get("scenario_key", [""])[0],
                    alternative_id=call.query.get("alternative_id", [None])[0],
                    document_hash=call.query.get("document_hash", [None])[0],
                ),
            )
        except ValidationError as error:
            raise _Refusal(409, {"code": error.code}) from None

    def _route_why(self, call: _Call) -> _Answer:
        from orchestwin.why import WhyError, explain_why

        document = self._why_document(self._code_project(call))
        try:
            return _Answer(200, explain_why(document, call.query.get("code", [""])[0]))
        except WhyError as error:
            status = {"WHY_CODE_INVALID": 422, "WHY_CODE_AMBIGUOUS": 409}.get(error.code, 404)
            raise _Refusal(
                status, {"code": error.code, "candidates": list(error.candidates)}
            ) from None

    def _route_evidence_show(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        version = call.query.get("version", [None])[0]
        try:
            version = None if version is None else int(version)
        except ValueError:
            raise _Refusal(422, {"code": "EVIDENCE_INVALID_TEXT"}) from None
        source = self._evidence_source(project, call.params["evidence_id"], version)
        result = copy.deepcopy(source)
        result["citations"] = [
            item
            for item in self._evidence_citations(project)
            if item["citation"]["source_id"] == source["id"]
        ]
        if call.query.get("text") == ["true"]:
            text = project.evidence_texts.get((source["id"], source["version"]))
            if text is None:
                raise _Refusal(409, {"code": "EVIDENCE_TEXT_UNAVAILABLE"})
            result["text"] = text
        return _Answer(200, result)

    def _evidence_insert(self, call: _Call, *, revision: bool) -> _Answer:
        project = self._code_project(call)
        try:
            body = EvidenceBody.model_validate(call.json())
            text = normalize_evidence_text(body.text)
        except ResearchEvidenceError as error:
            raise _Refusal(422, {"code": error.code}) from None
        except ValueError:
            raise _Refusal(422, {"code": "EVIDENCE_INVALID_TEXT"}) from None
        if not body.acknowledged:
            raise _Refusal(422, {"code": "EVIDENCE_ACKNOWLEDGEMENT_REQUIRED"})
        if (
            len(project.evidence_versions) >= 50
            or sum(len(value.encode("utf-8")) for value in project.evidence_texts.values())
            + len(text.encode("utf-8"))
            > 1048576
        ):
            raise _Refusal(422, {"code": "EVIDENCE_LIMIT", "message": "Split the text into parts."})
        previous = self._evidence_source(project, call.params["evidence_id"]) if revision else None
        if previous is not None and previous["status"] != "ACTIVE":
            raise _Refusal(409, {"code": "EVIDENCE_RETIRED"})
        source = EvidenceVersion(
            id=UUID(self._new_id() if previous is None else previous["id"]),
            code=f"EVD-{len({item['id'] for item in project.evidence_versions}) + 1:03d}"
            if previous is None
            else previous["code"],
            version=1 if previous is None else previous["version"] + 1,
            title=body.title,
            source_kind=body.source_kind,
            source_ref=body.source_ref,
            context=body.context,
            method=body.method,
            collected_at=body.collected_at,
            limitations=body.limitations,
            empirical=body.empirical,
            content_hash=evidence_content_hash(text),
            character_count=len(text),
            byte_count=len(text.encode("utf-8")),
            created_at=self._now(),
        ).to_snapshot()
        project.evidence_versions.append(source)
        project.evidence_texts[(source["id"], source["version"])] = text
        project.fingerprint = None
        if revision:
            self._invalidate_evidence_pending(
                project, source["id"], "The evidence source has a new version."
            )
        return _Answer(
            201,
            {
                "status": "EVIDENCE_REVISED" if revision else "EVIDENCE_ADDED",
                "evidence": copy.deepcopy(source),
            },
        )

    def _route_evidence_add(self, call: _Call) -> _Answer:
        return self._evidence_insert(call, revision=False)

    def _route_evidence_revise(self, call: _Call) -> _Answer:
        return self._evidence_insert(call, revision=True)

    def _invalidate_evidence_pending(
        self, project: FakeProject, source_id: str, reason: str
    ) -> None:
        for update in project.updates:
            if (
                update["status"] == "PROPOSED"
                and update.get("evidence", {}).get("source_id") == source_id
            ):
                update["status"] = "REJECTED"
                update["decision"] = {"decided_at": _iso(self._now()), "kept": [], "reason": reason}

    def _append_evidence_profiles(self, project: FakeProject, profiles: Mapping[str, object]):
        previous = project.snapshot
        body = copy.deepcopy(previous["snapshot"])
        twins = []
        for base in body["twin_versions"]:
            profile = profiles.get(base["twin_id"])
            if profile is None:
                twins.append(base)
                continue
            twin = {
                **base,
                "id": self._new_id(),
                "version_number": base["version_number"] + 1,
                "based_on_version_number": base["version_number"],
                "created_at": _stamp(self._now()),
                "profile": profile.to_snapshot(),
                "content_hash": profile.content_hash,
            }
            project.twins[twin["twin_id"]].append(twin)
            twins.append(twin)
        body["twin_versions"] = twins
        version = {
            **previous,
            "id": self._new_id(),
            "version_number": previous["version_number"] + 1,
            "based_on_version_number": previous["version_number"],
            "created_at": _stamp(self._now()),
            "snapshot": body,
            "content_hash": _fake_modeling(body).content_hash,
        }
        project.snapshots.append(version)
        reference = self._reference(project, "twins")
        latest = project.gates.get("twins")
        if latest is not None and latest.status is not HumanGateStatus.STALE:
            stale = mark_human_gate_stale(
                latest,
                current_artifact=reference,
                occurred_at=self._now(),
                event_id=UUID(self._new_id()),
            )
            if stale.event is not None:
                self._save_gate(project, "twins", stale.gate, stale.event)
        gate = create_human_gate(
            gate_id=UUID(self._new_id()),
            project_id=UUID(project.id),
            owner_user_id=UUID(project.account.id),
            gate_type=GATE_TYPES["twins"],
            artifact=reference,
            created_at=self._now(),
        )
        for action in (HumanGateAction.SUBMIT, HumanGateAction.APPROVE):
            transition = transition_human_gate(
                gate,
                action=action,
                actor_user_id=UUID(project.account.id),
                occurred_at=self._now(),
                event_id=UUID(self._new_id()),
            )
            if transition.event is None:
                raise _Refusal(409, {"code": "EVIDENCE_CONTEXT_CHANGED"})
            gate = transition.gate
            self._save_gate(project, "twins", gate, transition.event)
        project.fingerprint = None
        return version

    def _route_evidence_retire(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("reason",))
        reason = fields.text("reason", minimum=1, maximum=300)
        fields.check()
        project = self._code_project(call)
        source_id = call.params["evidence_id"]
        self._evidence_source(project, source_id)
        moment = _iso(self._now())
        for source in project.evidence_versions:
            if source["id"] == source_id and source["status"] == "ACTIVE":
                source.update(status="RETIRED", retired_at=moment, retired_reason=reason)
        self._invalidate_evidence_pending(project, source_id, "The evidence source was withdrawn.")
        affected = {
            row["twin_id"]
            for row in project.evidence_changes
            if row["source_id"] == source_id and row["retired_at"] is None
        }
        for row in project.evidence_changes:
            if row["source_id"] == source_id:
                row["retired_at"] = row["retired_at"] or moment
        profiles = {}
        review_required = bool(affected) and not self._approvals(project)["twins"]
        if affected and not review_required:
            for twin in project.snapshot["snapshot"]["twin_versions"]:
                if twin["twin_id"] not in affected:
                    continue
                profile = _fake_twin_profile(twin["profile"])
                records = [
                    row for row in project.evidence_changes if row["twin_id"] == twin["twin_id"]
                ]
                fields = {row["field"] for row in records if row["source_id"] == source_id}
                observations = [
                    withdrawn_observation(
                        observation,
                        [
                            row
                            for row in records
                            if row["field"]
                            == observation.observation_key.removeprefix("user_twin.")
                        ],
                        source_id=UUID(source_id),
                    )
                    for observation in profile.observations
                    if observation.observation_key.removeprefix("user_twin.") in fields
                ]
                profiles[twin["twin_id"]] = evidence_profile(profile, observations)
            self._append_evidence_profiles(project, profiles)
        project.fingerprint = None
        result = {
            "status": "EVIDENCE_RETIRED",
            "evidence": copy.deepcopy(self._evidence_source(project, source_id)),
            "affected_twins": sorted(affected),
        }
        if review_required:
            result["review_required"] = True
        return _Answer(200, result)

    def _route_evidence_delete(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        source_id = call.params["evidence_id"]
        self._evidence_source(project, source_id)
        body = call.json()
        if not isinstance(body, dict) or body.get("acknowledged") is not True:
            raise _Refusal(422, {"code": "EVIDENCE_ACKNOWLEDGEMENT_REQUIRED"})
        if any(
            item["id"] == source_id and item["status"] == "ACTIVE"
            for item in project.evidence_versions
        ):
            raise _Refusal(409, {"code": "EVIDENCE_RETIRE_REQUIRED"})
        for source in project.evidence_versions:
            if source["id"] == source_id:
                project.evidence_texts.pop((source_id, source["version"]), None)
                source["text_available"] = False
        project.fingerprint = None
        return _Answer(
            200,
            {
                "status": "EVIDENCE_TEXT_DELETED",
                "evidence": copy.deepcopy(self._evidence_source(project, source_id)),
            },
        )

    def _route_evidence_associate(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        body = call.json()
        if not isinstance(body, dict) or body.get("acknowledged") is not True:
            raise _Refusal(422, {"code": "EVIDENCE_ACKNOWLEDGEMENT_REQUIRED"})
        source = self._evidence_source(project, call.params["evidence_id"], body.get("version"))
        if source["status"] != "ACTIVE":
            raise _Refusal(409, {"code": "EVIDENCE_RETIRED"})
        try:
            text = normalize_evidence_text(body.get("text"))
        except ResearchEvidenceError as error:
            raise _Refusal(422, {"code": error.code}) from None
        if evidence_content_hash(text) != source["content_hash"]:
            raise _Refusal(409, {"code": "EVIDENCE_CONTEXT_CHANGED"})
        if (
            not source["text_available"]
            and sum(len(value.encode("utf-8")) for value in project.evidence_texts.values())
            + len(text.encode("utf-8"))
            > 1048576
        ):
            raise _Refusal(422, {"code": "EVIDENCE_LIMIT", "message": "Split the text into parts."})
        project.evidence_texts[(source["id"], source["version"])] = text
        source["text_available"] = True
        project.fingerprint = None
        return _Answer(
            200, {"status": "EVIDENCE_TEXT_REASSOCIATED", "evidence": copy.deepcopy(source)}
        )
