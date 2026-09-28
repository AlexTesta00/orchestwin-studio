from __future__ import annotations

from uuid import UUID

from orchestwin.agents.team_gate import agent_team_gate_is_currently_approved
from orchestwin.artifacts.design_gate import design_gate_is_currently_approved
from orchestwin.knowledge.diagram_service import brief_system_name
from orchestwin.knowledge.diagrams import DEFAULT_DIAGRAM_LOCALE
from orchestwin.knowledge.sources import (
    KnowledgeFeedback,
    KnowledgeSources,
    consistency_issue,
)
from orchestwin.projects.brief_gate import project_brief_gate_is_currently_approved
from orchestwin.projects.requirements_gate import requirements_gate_is_currently_approved
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

    async def load(self, *, owner_user_id: UUID, project_id: UUID) -> KnowledgeSources:
        scope = {"project_id": project_id, "owner_user_id": owner_user_id}
        brief = await self.project_service.current_brief(**scope)
        if brief is None:
            raise KnowledgeExportError("PROJECT_NOT_FOUND")
        brief_gate = await self.brief_gate_service.current_gate(**scope)
        if not project_brief_gate_is_currently_approved(brief_gate, brief):
            raise KnowledgeExportError("BRIEF_APPROVAL_REQUIRED")
        team = await self.team_proposal_service.current(**scope)
        team_gate = await self.agent_team_service.current_gate(**scope)
        if team is None or not agent_team_gate_is_currently_approved(team_gate, team):
            raise KnowledgeExportError("TEAM_APPROVAL_REQUIRED")
        modeling = await self.user_modeling_services.queries.current_snapshot(**scope)
        modeling_gate = await self.user_modeling_services.gates.current_gate(**scope)
        if modeling is None or not user_modeling_gate_is_currently_approved(
            modeling_gate, modeling
        ):
            raise KnowledgeExportError("USER_MODELING_APPROVAL_REQUIRED")
        requirements = await self.requirements_query_service.current(**scope)
        requirements_gate = await self.requirements_gate_service.current_gate(**scope)
        if requirements is None or not requirements_gate_is_currently_approved(
            requirements_gate, requirements
        ):
            raise KnowledgeExportError("REQUIREMENTS_APPROVAL_REQUIRED")
        design = await self.design_query_service.current(**scope)
        design_gate = await self.design_gate_service.current_gate(**scope)
        if design is None or not design_gate_is_currently_approved(design_gate, design):
            raise KnowledgeExportError("DESIGN_APPROVAL_REQUIRED")
        feedback = (
            KnowledgeFeedback()
            if self.feedback_query_service is None
            else await self.feedback_query_service.current(**scope)
        )
        sources = KnowledgeSources(
            project_id=project_id,
            project_name=brief_system_name(brief, DEFAULT_DIAGRAM_LOCALE),
            brief=brief,
            brief_gate=brief_gate,
            team=team,
            team_gate=team_gate,
            modeling=modeling,
            modeling_gate=modeling_gate,
            requirements=requirements,
            requirements_gate=requirements_gate,
            design=design,
            design_gate=design_gate,
            feedback=feedback,
        )
        issue = consistency_issue(sources)
        if issue is not None:
            raise KnowledgeExportError(issue)
        return sources


__all__ = [
    "KnowledgeExportError",
    "KnowledgeSourceLoader",
]
