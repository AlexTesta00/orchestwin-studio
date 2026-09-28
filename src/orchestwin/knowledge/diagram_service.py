from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.knowledge.diagrams import Diagram, diagram_locale, project_diagrams
from orchestwin.projects.briefs import ProjectBriefVersion
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion

_FALLBACK_SYSTEM_NAME: Final = {"en": "System", "it": "Sistema"}


@dataclass(frozen=True, slots=True)
class DiagramSourceVersion:
    version_id: UUID
    version_number: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class ProjectDiagrams:
    project_id: UUID
    locale: str
    system_name: str
    requirements: DiagramSourceVersion
    design: DiagramSourceVersion | None
    diagrams: tuple[Diagram, ...]


def brief_system_name(brief: ProjectBriefVersion, locale: str) -> str:
    name = brief.brief.to_snapshot()["fields"].get("name")
    if isinstance(name, str) and name.strip():
        return " ".join(name.split())
    return _FALLBACK_SYSTEM_NAME[diagram_locale(locale)]


def _source_version(
    version: RequirementsSpecificationVersion | DesignPackageVersion,
) -> DiagramSourceVersion:
    return DiagramSourceVersion(
        version_id=version.id,
        version_number=version.version_number,
        content_hash=version.content_hash,
    )


def build_project_diagrams(
    *,
    brief: ProjectBriefVersion,
    requirements: RequirementsSpecificationVersion,
    design: DesignPackageVersion | None,
    locale: str,
) -> ProjectDiagrams:
    language = diagram_locale(locale)
    system_name = brief_system_name(brief, language)
    return ProjectDiagrams(
        project_id=requirements.project_id,
        locale=language,
        system_name=system_name,
        requirements=_source_version(requirements),
        design=None if design is None else _source_version(design),
        diagrams=project_diagrams(
            specification=requirements.specification.to_snapshot(),
            package=None if design is None else design.package.to_snapshot(),
            system_name=system_name,
            locale=language,
        ),
    )


class ProjectDiagramService:
    def __init__(
        self,
        *,
        project_service,
        requirements_query_service,
        design_query_service,
    ) -> None:
        self.project_service = project_service
        self.requirements_query_service = requirements_query_service
        self.design_query_service = design_query_service

    async def current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        locale: str,
    ) -> ProjectDiagrams | None:
        scope = {"project_id": project_id, "owner_user_id": owner_user_id}
        brief = await self.project_service.current_brief(**scope)
        if brief is None:
            return None
        requirements = await self.requirements_query_service.current(**scope)
        if requirements is None:
            return None
        design = await self.design_query_service.current(**scope)
        return build_project_diagrams(
            brief=brief,
            requirements=requirements,
            design=design,
            locale=locale,
        )


__all__ = [
    "DiagramSourceVersion",
    "ProjectDiagramService",
    "ProjectDiagrams",
    "brief_system_name",
    "build_project_diagrams",
]
