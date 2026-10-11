from __future__ import annotations

import copy
import hashlib
import itertools
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from orchestwin.api.requirements import RequirementsSpecificationPayload
from orchestwin.knowledge.archive import (
    MAX_ARCHIVE_SIZE,
    KnowledgeArchiveError,
    read_verified_folder,
)
from orchestwin.knowledge.folder import build_knowledge_folder, folder_archive
from orchestwin.knowledge.project_import import plan_documents, plan_project_import
from orchestwin.knowledge.sources import KnowledgeSources
from orchestwin.knowledge.stage_documents import stage_versions
from orchestwin.knowledge.state import MAX_FOLDER_TEST_RUNS, ProjectStateSources

from .common import (
    _artifact_version,
    _digest,
    _error,
    _fake_design,
    _fake_modeling,
    _fake_requirements,
    _fake_team_proposal,
    _key,
    _reference_key,
    _stamp,
)
from .projects import MAX_PROJECT_NAME, MAX_SOURCE_NAME, PROJECT_MODES, _multipart
from .values import STAGES, _Answer, _BriefVersion, _Invalid, _iso, _Refusal

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject


FEEDBACK_KEYS = (
    "reviews",
    "findings",
    "decisions",
    "discussions",
    "insights",
    "change_reviews",
    "test_runs",
    "learned_observations",
)
STATE_KEYS = ("changes", "pending_changes", "stale_reviews", "aligned_commit", "open_tasks")


class _PackageRoutes:
    def _publishable(self, project: FakeProject) -> list[str]:
        present = list(
            itertools.takewhile(lambda stage: self._gate_approved(project, stage), STAGES)
        )
        if "twins" in present and not self._archetypes_current(project, project.snapshot):
            return present[:2]
        if project.evidence_versions:
            for position in range(1, len(present) + 1):
                if self._folder_issue(project, present[:position]) is not None:
                    return present[: position - 1]
        return present

    def _folder_issue(self, project: FakeProject, present: Sequence[str]) -> str | None:
        keys = {stage: _key(project.artifact(stage)) for stage in present}
        brief, team, twins = (keys.get(stage) for stage in ("brief", "team", "twins"))
        if "team" in keys and _team_brief(project.team) != brief:
            return "TEAM_OUTDATED"
        if "twins" in keys:
            body = project.snapshot["snapshot"]
            if (
                _reference_key(body["project_brief_reference"]),
                _reference_key(body["agent_team_reference"]),
            ) != (brief, team):
                return "USER_TWINS_OUTDATED"
        if "requirements" in keys:
            context = project.specification["specification"]
            if (
                _reference_key(context["project_brief_reference"]),
                _reference_key(context["agent_team_reference"]),
                _reference_key(context["user_modeling_reference"]),
            ) != (brief, team, twins):
                return "REQUIREMENTS_OUTDATED"
        if "design" in keys:
            grounding = project.design["package"]["grounding"]
            if (
                _reference_key(grounding["requirements_reference"]),
                _reference_key(grounding["agent_team_reference"]),
                _reference_key(grounding["user_modeling_reference"]),
            ) != (keys["requirements"], team, twins):
                return "DESIGN_OUTDATED"
        return None

    def _route_publish(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        if not self._gate_approved(project, "brief"):
            raise _Refusal(409, {"code": "BRIEF_APPROVAL_REQUIRED"})
        present = self._publishable(project)
        issue = self._folder_issue(project, present)
        if issue is not None:
            raise _Refusal(409, {"code": issue})
        fingerprint = (
            *(str(project.artifact(stage)["id"]) for stage in present),
            f"changes={len(project.code_changes)}",
            f"runs={len(project.change_runs)}",
            f"decisions={project.decision_count}",
            f"tests={len(project.acceptance_runs)}",
            f"test_reviews={len(project.acceptance_reviews)}",
            f"tasks={_digest(project.code_tasks)}",
            f"learning={_digest(project.development)}",
        )
        if project.packages and project.fingerprint == fingerprint:
            return _Answer(200, {"reused": True, "version": project.packages[-1]})
        number = len(project.packages) + 1
        created_at = self._now()
        folder = self._knowledge_folder(project, present, number, created_at)
        archive = folder_archive(folder)
        manifest = folder.manifest
        views = [view for view in manifest["views"].values() if view]
        stages = [stage for stage in STAGES if manifest["stages"].get(stage)]
        version = {
            "id": self._new_id(),
            "project_id": project.id,
            "project_name": manifest["project"]["name"],
            "version_number": number,
            "schema_version": manifest["schema_version"],
            "content_hash": folder.content_hash,
            "archive_hash": archive.archive_hash,
            "file_name": f"orchestwin-{project.id}-knowledge-v{number}.zip",
            "file_count": len(archive.entries),
            "archive_size": len(archive.content),
            "created_at": _stamp(created_at),
            "stages": [
                {
                    "stage": stage,
                    "label": manifest["stages"][stage]["label"],
                    "version_number": manifest["stages"][stage]["version_number"],
                    "content_hash": manifest["stages"][stage]["content_hash"],
                }
                for stage in stages
            ],
            "progress": {
                "approved": list(manifest["progress"]["approved"]),
                "pending": manifest["progress"]["pending"],
                "complete": manifest["progress"]["complete"],
            },
            "state": {
                key: manifest["state"][key] for key in STATE_KEYS if key in manifest["state"]
            },
            "twins": [
                {
                    "twin_id": twin["twin_id"],
                    "name": twin["name"],
                    "slug": twin["slug"],
                    "version_number": twin["version_number"],
                    "document": twin["document"],
                }
                for twin in manifest["twins"]
            ],
            "feedback": {
                key: manifest["feedback"][key]
                for key in FEEDBACK_KEYS
                if key in manifest["feedback"]
            },
            "diagram_count": sum(len(view["diagrams"]) for view in views),
            "table_count": sum(len(view["tables"]) for view in views),
            "entries": list(archive.entries),
        }
        project.packages.append(version)
        project.folders.append(
            {stage: _artifact_version(project.artifact(stage)) for stage in present}
        )
        project.archives[number] = archive.content
        project.fingerprint = fingerprint
        return _Answer(201, {"reused": False, "version": version})

    def _route_package_history(self, call: _Call) -> _Answer:
        raw_limit = call.value("limit")
        limit = 50
        if raw_limit is not None:
            if re.fullmatch(r"[0-9]+", raw_limit) is None:
                raise _Invalid([_error(("query", "limit"), "int_parsing")])
            limit = int(raw_limit)
            if limit < 1:
                raise _Invalid([_error(("query", "limit"), "greater_than_equal")])
            if limit > 200:
                raise _Invalid([_error(("query", "limit"), "less_than_equal")])
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        return _Answer(
            200,
            {"project_id": call.project_id, "versions": list(reversed(project.packages))[:limit]},
        )

    def _route_package_archive(self, call: _Call) -> _Answer:
        number = int(call.params["version_number"])
        if number < 1:
            raise _Invalid([_error(("path", "version_number"), "greater_than_equal")])
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        content = project.archives.get(number)
        if content is None:
            raise _Refusal(404, {"code": "KNOWLEDGE_PACKAGE_NOT_FOUND"})
        version = project.packages[number - 1]
        return _Answer(
            200,
            raw=content,
            content_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{version["file_name"]}"',
                "X-Content-SHA256": hashlib.sha256(content).hexdigest(),
            },
        )

    def _route_import_project(self, call: _Call) -> _Answer:
        declared = call.headers.get("content-length", "")
        if declared.isdecimal() and int(declared) > MAX_ARCHIVE_SIZE + 64 * 1024:
            raise _Refusal(413, {"code": "FOLDER_ARCHIVE_TOO_LARGE", "location": None})
        form = _multipart(call.headers.get("content-type", ""), call.raw)
        archive = form.get("archive")
        if archive is None or archive[0] is None:
            raise _Invalid([_error(("body", "archive"), "missing")])
        content = archive[1]
        if len(content) > MAX_ARCHIVE_SIZE:
            raise _Refusal(413, {"code": "FOLDER_ARCHIVE_TOO_LARGE", "location": None})
        display = form.get("display_name")
        given = None if display is None else display[1].decode("utf-8", "replace")
        try:
            verified = read_verified_folder(content)
        except KnowledgeArchiveError as error:
            status = 413 if error.code == "FOLDER_ARCHIVE_TOO_LARGE" else 422
            raise _Refusal(status, {"code": error.code, "location": error.detail}) from error
        missing = [stage for stage in STAGES if not verified.manifest["stages"].get(stage)]
        if missing:
            raise _Refusal(422, {"code": "FOLDER_INCOMPLETE", "location": missing[0]})
        source_name = verified.project_name
        if not 1 <= len(source_name) <= MAX_SOURCE_NAME:
            raise _Refusal(
                422,
                {"code": "FOLDER_DOCUMENT_INVALID", "location": "orchestwin.json: project.name"},
            )
        name = " ".join((given or "").split())
        if name and len(name) > MAX_PROJECT_NAME:
            raise _Refusal(422, {"code": "PROJECT_NAME_INVALID", "location": "display_name"})
        if not name:
            name = " ".join(source_name.split())[:MAX_PROJECT_NAME].rstrip()
        if not name:
            raise _Refusal(422, {"code": "PROJECT_NAME_INVALID", "location": "display_name"})
        try:
            mode = str(verified.documents["team"]["proposal"]["project_mode"])
        except (KeyError, TypeError) as error:
            raise _Refusal(
                422, {"code": "FOLDER_DOCUMENT_INVALID", "location": "team: project_mode"}
            ) from error
        if mode not in PROJECT_MODES:
            raise _Refusal(
                422, {"code": "FOLDER_DOCUMENT_INVALID", "location": "team: project_mode"}
            )
        project = self._new_project(call.account, name, mode)
        self._seed(project, "design", approve=False)
        imported_at = self._now()
        plan = None
        if "twins/evidence.json" in verified.files or "why" in verified.manifest:
            from orchestwin.api.design import DesignPackagePayload
            from orchestwin.api.teams import TeamProposalVersionResponse
            from orchestwin.api.user_modeling import UserModelingSnapshotVersionPayload

            try:
                plan = plan_project_import(
                    verified,
                    project_id=UUID(project.id),
                    brief_version_id=UUID(self._new_id()),
                    owner_user_id=UUID(call.account.id),
                    created_at=imported_at,
                )
            except KnowledgeArchiveError as error:
                self._projects.pop(project.id, None)
                raise _Refusal(422, {"code": error.code, "location": error.detail}) from None
            documents = plan_documents(
                plan, owner_user_id=UUID(call.account.id), created_at=imported_at
            )
            project.briefs = [_BriefVersion(documents["brief"], plan.brief)]
            project.teams = [
                TeamProposalVersionResponse.from_domain(plan.team).model_dump(mode="json")
            ]
            project.snapshots = [
                UserModelingSnapshotVersionPayload.from_domain(plan.modeling).model_dump(
                    mode="json"
                )
            ]
            project.personas = {
                item["persona_id"]: [item]
                for item in project.snapshot["snapshot"]["persona_versions"]
            }
            project.twins = {
                item["twin_id"]: [item] for item in project.snapshot["snapshot"]["twin_versions"]
            }
            project.requirements = [
                {
                    **documents["requirements"],
                    "specification": RequirementsSpecificationPayload.from_domain(
                        plan.requirements.specification
                    ).model_dump(mode="json"),
                }
            ]
            project.designs = [
                {
                    **documents["design"],
                    "package": DesignPackagePayload.from_domain(plan.design.package).model_dump(
                        mode="json"
                    ),
                }
            ]
            project.gates = {}
            project.gate_events = {}
            project.mockups = {}
            project.runs = [item.to_snapshot() for item in plan.evaluations]
            project.finding_decisions = [item.to_snapshot() for item in plan.finding_decisions]
            project.validation_hypotheses = copy.deepcopy(
                (plan.validation_records or {}).get("hypotheses", [])
            )
            project.validation_outcomes = copy.deepcopy(
                (plan.validation_records or {}).get("outcomes", [])
            )
            project.evidence_versions = copy.deepcopy(
                (plan.research_evidence or {}).get("evidence", [])
            )
            for item in (plan.research_evidence or {}).get("citations", []):
                twin = next(
                    (twin for twin in plan.twins if str(twin.twin_id) == item["twin_id"]), None
                )
                observation = next(
                    (
                        observation
                        for observation in (() if twin is None else twin.profile.observations)
                        if observation.observation_key == f"user_twin.{item['field']}"
                    ),
                    None,
                )
                citation = item["citation"]
                project.evidence_changes.append(
                    {
                        "twin_id": item["twin_id"],
                        "twin_version": item["twin_version"],
                        "field": item["field"],
                        "source_id": citation["source_id"],
                        "source_version": citation["source_version"],
                        "change": {
                            "effect": item["effect"],
                            "field": item["field"],
                            **(
                                {"value": observation.value.to_snapshot()}
                                if observation is not None
                                else {"historical_only": True}
                            ),
                            "citation": copy.deepcopy(citation),
                            **(
                                {"imported_from": copy.deepcopy(item["imported_from"])}
                                if item.get("imported_from") is not None
                                else {}
                            ),
                        },
                        "before": None,
                        "after": observation.to_snapshot()
                        if observation is not None
                        else {"kind": "historical-citation", "profile_available": False},
                        "retired_at": None if item["status"] == "ACTIVE" else _iso(imported_at),
                    }
                )
        if plan is not None and "why" in verified.manifest:
            from orchestwin.knowledge.why import importable_why, normalized_why

            original = importable_why(verified, plan.omitted_sections)
            if normalized_why(
                original, identities=plan.identities, hashes=plan.hashes
            ) != normalized_why(self._why_document(project)):
                self._projects.pop(project.id, None)
                raise _Refusal(
                    422, {"code": "FOLDER_WHY_MISMATCH", "location": "exported derivation"}
                )
        stages = {
            stage: {
                "version_id": project.artifact(stage)["id"],
                "version_number": project.artifact(stage)["version_number"],
                "content_hash": project.artifact(stage)["content_hash"],
            }
            for stage in STAGES
        }
        origin = {
            "project_id": verified.project_id,
            "project_name": source_name,
            "package_version": verified.package_version,
            "package_content_hash": verified.content_hash,
            "schema_version": verified.manifest["schema_version"],
        }
        project.origin = {
            "origin": origin,
            "stages": stages,
            "imported_at": _stamp(imported_at),
            "archive_hash": hashlib.sha256(content).hexdigest(),
        }
        if plan is not None and plan.import_limits:
            project.origin["import_limits"] = list(plan.import_limits)
        if plan is not None and plan.omitted_sections:
            project.origin["omitted_sections"] = list(plan.omitted_sections)
        twins = project.snapshot["snapshot"]["twin_versions"] if project.snapshot else []
        return _Answer(
            201,
            {
                "project": {
                    "id": project.id,
                    "display_name": project.name,
                    "mode": project.mode,
                    "created_at": _stamp(project.created_at),
                },
                "origin": origin,
                "stages": stages,
                "twins": [
                    {"twin_id": twin["twin_id"], "name": twin["profile"]["name"]} for twin in twins
                ],
                "imported_at": _stamp(imported_at),
                "approval_required": list(STAGES),
                "why_verified": plan is not None and "why" in verified.manifest,
                "import_limits": [] if plan is None else list(plan.import_limits),
                **(
                    {"omitted_sections": list(plan.omitted_sections)}
                    if plan is not None and plan.omitted_sections
                    else {}
                ),
            },
        )

    def _route_import_origin(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.origin is None:
            raise _Refusal(404, {"code": "PROJECT_IMPORT_NOT_FOUND", "location": None})
        return _Answer(200, project.origin)

    def _route_usage(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        items = list(project.usage)
        return _Answer(
            200,
            {
                "items": items,
                "totals": {
                    "generations": len(items),
                    "input_tokens": sum(int(item["input_tokens"]) for item in items),
                    "output_tokens": sum(int(item["output_tokens"]) for item in items),
                    "reasoning_tokens": sum(int(item["reasoning_tokens"]) for item in items),
                    "cost_microusd": sum(int(item["cost_microusd"] or 0) for item in items),
                },
            },
        )

    def _knowledge_folder(
        self, project: FakeProject, present: Sequence[str], number: int, moment: datetime
    ):
        from types import SimpleNamespace

        from orchestwin.artifacts.design_evaluation import design_evaluation_run_from_snapshot
        from orchestwin.artifacts.design_finding_validations import finding_validation_from_snapshot
        from orchestwin.knowledge.sources import knowledge_feedback
        from orchestwin.knowledge.validation_records import preserve_import_history

        origin = None
        if project.origin is not None:
            metadata = project.origin["origin"]
            origin = SimpleNamespace(
                source_project_id=metadata["project_id"],
                package_version=metadata["package_version"],
                package_content_hash=metadata["package_content_hash"],
                omitted_sections=project.origin.get("omitted_sections", ()),
                import_limits=project.origin.get("import_limits", ()),
            )

        documents = {}
        for stage in present:
            version = copy.deepcopy(project.artifact(stage))
            if stage == "brief":
                version["brief"] = project.brief.brief.to_snapshot()
            elif stage == "team":
                version["proposal"] = _fake_team_proposal(version).to_snapshot()
                if version["revision_kind"] == "PROPOSER_GENERATED":
                    version["based_on_version_number"] = None
            elif stage == "twins":
                version["snapshot"] = _fake_modeling(version["snapshot"]).to_snapshot()
            elif stage == "requirements":
                version["specification"] = _fake_requirements(
                    version["specification"]
                ).to_snapshot()
            elif stage == "design":
                version["package"] = _fake_design(version["package"]).to_snapshot()
            documents[stage] = version
        versions = stage_versions(documents)
        values = {
            "project_id": UUID(project.id),
            "project_name": project.name,
            "state": self._state_sources(project, present[-1]),
            "research_evidence": self._evidence_dossier(project),
            "validation_records": preserve_import_history(
                {
                    "hypotheses": project.validation_hypotheses,
                    "outcomes": project.validation_outcomes,
                },
                origin,
            ),
            "feedback": knowledge_feedback(
                runs=(design_evaluation_run_from_snapshot(item) for item in project.runs),
                validations=(
                    finding_validation_from_snapshot(item) for item in project.finding_decisions
                ),
            ),
        }
        for stage, version in versions.items():
            name = "modeling" if stage == "twins" else stage
            values[name] = version
            values[f"{name}_gate"] = project.gates[stage]
        return build_knowledge_folder(
            KnowledgeSources(**values), version_number=number, created_at=moment
        )

    def _state_sources(self, project: FakeProject, through: str) -> ProjectStateSources:
        frame = {
            "reference": self._current_reference(project) if through == "design" else None,
            "twins": tuple(
                {
                    "twin_id": twin["twin_id"],
                    "twin_name": twin["profile"]["name"],
                    "profile_version_number": twin["version_number"],
                }
                for twin in (
                    []
                    if project.snapshot is None
                    or through not in ("twins", "requirements", "design")
                    else project.snapshot["snapshot"]["twin_versions"]
                )
            ),
        }
        return ProjectStateSources(
            aligned=self._aligned(project),
            changes=tuple(
                self._change_payload(project, record, frame) for record in project.code_changes
            ),
            runs=tuple(copy.deepcopy(run) for run in project.change_runs),
            tasks=tuple(copy.deepcopy(task) for task in project.code_tasks),
            tests=tuple(
                self._test_run_payload(project, record)
                for record in project.acceptance_runs[:MAX_FOLDER_TEST_RUNS]
            ),
            learning=self._folder_learning(project, frame),
        )

    def _folder_learning(
        self, project: FakeProject, frame: Mapping[str, object]
    ) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                **entry,
                "twin_id": twin["twin_id"],
                "twin_name": twin["twin_name"],
                "profile_version_number": twin["profile_version_number"],
                "label": f"{twin['profile_version_number']}.{entry['development_version_number']}",
            }
            for entry, twin in zip(self._learning_entries(project), frame["twins"], strict=False)
        )


def _team_brief(team: Mapping[str, object] | None) -> tuple[str, int, str] | None:
    if team is None:
        return None
    return (
        str(team["brief_version_id"]),
        int(team["brief_version_number"]),
        str(team["brief_content_hash"]),
    )
