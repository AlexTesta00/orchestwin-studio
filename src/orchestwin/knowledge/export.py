from __future__ import annotations

from uuid import UUID

from orchestwin.agents.team_gate import agent_team_gate_is_currently_approved
from orchestwin.artifacts.design_gate import design_gate_is_currently_approved
from orchestwin.knowledge.diagram_service import brief_system_name
from orchestwin.knowledge.diagrams import DEFAULT_DIAGRAM_LOCALE
from orchestwin.knowledge.research_evidence import present as has_evidence
from orchestwin.knowledge.sources import (
    KnowledgeFeedback,
    KnowledgeSources,
    consistency_issue,
)
from orchestwin.knowledge.state import ProjectStateSources
from orchestwin.projects.brief_gate import project_brief_gate_is_currently_approved
from orchestwin.projects.requirements_gate import requirements_gate_is_currently_approved
from orchestwin.projects.sections import requirements_actor_codes
from orchestwin.twins.user_modeling_gate import user_modeling_gate_is_currently_approved


class KnowledgeExportError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class KnowledgeSourceLoader:
    def __init__(
        self,
        *,
        project_service,
        brief_gate_service,
        team_proposal_service,
        agent_team_service,
        user_modeling_services,
        requirements_query_service,
        requirements_gate_service,
        design_query_service,
        design_gate_service,
        feedback_query_service=None,
        state_query_service=None,
        evidence_query_service=None,
        validation_query_service=None,
        workflow_query_service=None,
        import_origin_query_service=None,
    ) -> None:
        self.project_service = project_service
        self.brief_gate_service = brief_gate_service
        self.team_proposal_service = team_proposal_service
        self.agent_team_service = agent_team_service
        self.user_modeling_services = user_modeling_services
        self.requirements_query_service = requirements_query_service
        self.requirements_gate_service = requirements_gate_service
        self.design_query_service = design_query_service
        self.design_gate_service = design_gate_service
        self.feedback_query_service = feedback_query_service
        self.state_query_service = state_query_service
        self.evidence_query_service = evidence_query_service
        self.validation_query_service = validation_query_service
        self.workflow_query_service = workflow_query_service
        self.import_origin_query_service = import_origin_query_service

    def _later_stages(self):
        return (
            (
                "team",
                self.team_proposal_service.current,
                self.agent_team_service.current_gate,
                agent_team_gate_is_currently_approved,
            ),
            (
                "modeling",
                self.user_modeling_services.queries.current_snapshot,
                self.user_modeling_services.gates.current_gate,
                user_modeling_gate_is_currently_approved,
            ),
            (
                "requirements",
                self.requirements_query_service.current,
                self.requirements_gate_service.current_gate,
                requirements_gate_is_currently_approved,
            ),
            (
                "design",
                self.design_query_service.current,
                self.design_gate_service.current_gate,
                design_gate_is_currently_approved,
            ),
        )

    async def load(self, *, owner_user_id: UUID, project_id: UUID) -> KnowledgeSources:
        scope = {"project_id": project_id, "owner_user_id": owner_user_id}
        brief = await self.project_service.current_brief(**scope)
        if brief is None:
            raise KnowledgeExportError("PROJECT_NOT_FOUND")
        brief_gate = await self.brief_gate_service.current_gate(**scope)
        if not project_brief_gate_is_currently_approved(brief_gate, brief):
            raise KnowledgeExportError("BRIEF_APPROVAL_REQUIRED")
        approved: dict[str, object] = {}
        evidence = (
            {}
            if self.evidence_query_service is None
            else await self.evidence_query_service.current(**scope)
        )
        stages = self._later_stages()
        for position, (name, current, current_gate, is_approved) in enumerate(stages):
            version = await current(**scope)
            gate = await current_gate(**scope)
            if version is None or not is_approved(gate, version):
                break
            if (
                name == "modeling"
                and not await self.user_modeling_services.commands.snapshot_context_is_current(
                    **scope, snapshot=version
                )
            ):
                break
            if has_evidence(evidence):
                candidate = KnowledgeSources(
                    project_id=project_id,
                    project_name=brief_system_name(brief, DEFAULT_DIAGRAM_LOCALE),
                    brief=brief,
                    brief_gate=brief_gate,
                    **approved,
                    **{name: version, f"{name}_gate": gate},
                )
                issue = consistency_issue(candidate)
                if issue is not None:
                    omitted = self._omitted(name, issue, version, approved)
                    for later_name, later_current, _, _ in stages[position + 1 :]:
                        if await later_current(**scope) is not None:
                            omitted.append(
                                {
                                    "stage": "twins" if later_name == "modeling" else later_name,
                                    "reason": "UPSTREAM_CONTEXT_CHANGED",
                                    "affected_codes": omitted[0]["affected_codes"],
                                }
                            )
                    evidence = {**evidence, "omitted_sections": omitted}
                    break
            approved[name] = version
            approved[f"{name}_gate"] = gate
        feedback = (
            await self.feedback_query_service.current(**scope)
            if "design" in approved and self.feedback_query_service is not None
            else KnowledgeFeedback()
        )
        state = (
            ProjectStateSources()
            if self.state_query_service is None
            else await self.state_query_service.current(**scope)
        )
        validation_records = (
            {}
            if self.validation_query_service is None
            else await self.validation_query_service.records(**scope) or {}
        )
        if self.import_origin_query_service is not None:
            from orchestwin.knowledge.validation_records import preserve_import_history

            validation_records = preserve_import_history(
                validation_records,
                await self.import_origin_query_service.origin(**scope),
            )
        sources = KnowledgeSources(
            project_id=project_id,
            project_name=brief_system_name(brief, DEFAULT_DIAGRAM_LOCALE),
            brief=brief,
            brief_gate=brief_gate,
            feedback=feedback,
            state=state,
            research_evidence=evidence,
            validation_records=validation_records,
            workflow_inputs=(
                {}
                if self.workflow_query_service is None
                else await self.workflow_query_service.records(**scope) or {}
            ),
            provided_design=(
                {}
                if self.workflow_query_service is None
                else await self.workflow_query_service.state(**scope)
            ),
            **approved,
        )
        issue = consistency_issue(sources)
        if issue is not None:
            raise KnowledgeExportError(issue)
        return sources

    def _omitted(self, name, issue, version, approved):
        codes = {key: [] for key in ("scenarios", "needs", "requirements")}
        if name == "requirements" and "modeling" in approved:
            current = {
                item.twin_id: (item.version_number, item.content_hash)
                for item in approved["modeling"].snapshot.twin_versions
            }
            changed = {
                item.twin_id
                for item in version.specification.user_twin_references
                if current.get(item.twin_id) != (item.version_number, item.content_hash)
            }
            actors = requirements_actor_codes(version.specification)
            codes = {
                key: sorted(
                    {code for twin_id in changed for code in actors.get(twin_id, {}).get(key, ())}
                )
                for key in codes
            }
        return [
            {
                "stage": "twins" if name == "modeling" else name,
                "reason": "USER_TWINS_CHANGED" if name == "requirements" else issue,
                "affected_codes": codes,
            }
        ]


__all__ = [
    "KnowledgeExportError",
    "KnowledgeSourceLoader",
]
