from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID

from orchestwin.knowledge.diagram_service import (
    ProjectDiagramService,
    brief_system_name,
    build_project_diagrams,
)
from orchestwin.knowledge.diagrams import DiagramKind, DiagramStage
from src.test.python.artifacts.design_fixtures import (
    OWNER_ID,
    PROJECT_ID,
    design_version,
    requirements_version,
)


class FakeQuery:
    def __init__(self, value, method: str = "current") -> None:
        self.value = value
        self.calls: list[dict[str, UUID]] = []
        setattr(self, method, self._answer)

    async def _answer(self, **scope: UUID):
        self.calls.append(scope)
        return self.value


def brief(name: object = "Lista ospiti workshop"):
    snapshot = {"fields": {"name": name}}
    return SimpleNamespace(brief=SimpleNamespace(to_snapshot=lambda: snapshot))


def service(*, brief_version=None, requirements=None, design=None) -> ProjectDiagramService:
    return ProjectDiagramService(
        project_service=FakeQuery(brief_version, "current_brief"),
        requirements_query_service=FakeQuery(requirements),
        design_query_service=FakeQuery(design),
    )


def current(diagrams: ProjectDiagramService, locale: str = "it"):
    return asyncio.run(
        diagrams.current(owner_user_id=OWNER_ID, project_id=PROJECT_ID, locale=locale)
    )


def test_system_name_comes_from_the_brief_and_falls_back_by_locale() -> None:
    assert brief_system_name(brief("  Lista   ospiti "), "it") == "Lista ospiti"
    assert brief_system_name(brief(None), "it") == "Sistema"
    assert brief_system_name(brief("  "), "en") == "System"
    assert brief_system_name(brief(None), "de") == "System"


def test_diagrams_carry_the_exact_versions_they_were_drawn_from() -> None:
    requirements = requirements_version()
    design = design_version()

    result = build_project_diagrams(
        brief=brief(), requirements=requirements, design=design, locale="it"
    )

    assert result.project_id == PROJECT_ID
    assert result.locale == "it"
    assert result.system_name == "Lista ospiti workshop"
    assert result.requirements.version_id == requirements.id
    assert result.requirements.version_number == requirements.version_number
    assert result.requirements.content_hash == requirements.content_hash
    assert result.design is not None
    assert result.design.version_id == design.id
    assert result.design.content_hash == design.content_hash
    assert {item.kind for item in result.diagrams} == set(DiagramKind)
    assert 'systemBoundary SYSTEM["Lista ospiti workshop"]' in result.diagrams[0].source


def test_service_reads_the_current_versions_of_the_owner_scoped_project() -> None:
    diagrams = service(
        brief_version=brief(), requirements=requirements_version(), design=design_version()
    )

    result = current(diagrams)

    scope = {"project_id": PROJECT_ID, "owner_user_id": OWNER_ID}
    assert result is not None
    assert diagrams.project_service.calls == [scope]
    assert diagrams.requirements_query_service.calls == [scope]
    assert diagrams.design_query_service.calls == [scope]
    assert result.diagrams[0].title == "Casi d'uso"


def test_project_without_design_gets_the_requirements_diagrams_only() -> None:
    result = current(service(brief_version=brief(), requirements=requirements_version()))

    assert result is not None
    assert result.design is None
    assert {item.stage for item in result.diagrams} == {DiagramStage.REQUIREMENTS}


def test_missing_project_or_requirements_yield_no_diagrams() -> None:
    unknown = service(requirements=requirements_version())
    early = service(brief_version=brief())

    assert current(unknown) is None
    assert unknown.requirements_query_service.calls == []
    assert current(early) is None
    assert early.design_query_service.calls == []


def test_unknown_locale_is_normalized_to_english() -> None:
    result = current(
        service(brief_version=brief(), requirements=requirements_version()), locale="de"
    )

    assert result is not None
    assert result.locale == "en"
    assert result.diagrams[0].title == "Use cases"
