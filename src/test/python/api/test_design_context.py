from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from orchestwin.api.design_context import require_current_design_context
from orchestwin.projects.progress import ProjectStage
from orchestwin.projects.sections import ProjectSections, Section, SectionAlignment, SectionState
from orchestwin.projects.sections_service import SectionsFailure


def sections_port(*, owner_user_id, project_id, states=None):
    states = {} if states is None else states
    calls = []

    async def current(**scope):
        assert scope == {"owner_user_id": owner_user_id, "project_id": project_id}
        calls.append(scope)
        return ProjectSections(
            first_pass_complete=True,
            sections=tuple(
                Section(key, states.get(key, SectionState.FINE)) for key in ProjectStage
            ),
            alignment=SectionAlignment(),
        )

    return SimpleNamespace(current=current, calls=calls)


@pytest.mark.parametrize("key", tuple(ProjectStage)[:5])
def test_changed_design_or_upstream_sections_refuse_mutation(key):
    owner_user_id, project_id = uuid4(), uuid4()
    service = sections_port(
        owner_user_id=owner_user_id, project_id=project_id, states={key: SectionState.TO_UPDATE}
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            require_current_design_context(
                SimpleNamespace(sections_service=service),
                owner_user_id=owner_user_id,
                project_id=project_id,
            )
        )
    assert error.value.status_code == 409
    assert error.value.detail == {"code": "DESIGN_CONTEXT_CHANGED"}


@pytest.mark.parametrize("state", (SectionState.NOT_STARTED, SectionState.IN_PROGRESS))
@pytest.mark.parametrize("key", tuple(ProjectStage)[:4])
def test_upstream_not_ready_refuses_mutation(key, state):
    owner_user_id, project_id = uuid4(), uuid4()
    service = sections_port(owner_user_id=owner_user_id, project_id=project_id, states={key: state})
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            require_current_design_context(
                SimpleNamespace(sections_service=service),
                owner_user_id=owner_user_id,
                project_id=project_id,
            )
        )
    assert error.value.detail == {"code": "DESIGN_CONTEXT_CHANGED"}


@pytest.mark.parametrize(
    "state", (SectionState.IN_PROGRESS, SectionState.FINE, SectionState.UPDATE_AVAILABLE)
)
def test_normal_design_choice_and_additional_material_are_allowed(state):
    owner_user_id, project_id = uuid4(), uuid4()
    service = sections_port(
        owner_user_id=owner_user_id,
        project_id=project_id,
        states={
            ProjectStage.DESIGN: state,
            ProjectStage.REQUIREMENTS: SectionState.UPDATE_AVAILABLE,
        },
    )
    asyncio.run(
        require_current_design_context(
            SimpleNamespace(sections_service=service),
            owner_user_id=owner_user_id,
            project_id=project_id,
        )
    )
    assert len(service.calls) == 1


def test_legacy_runtime_without_section_port_remains_readable():
    asyncio.run(
        require_current_design_context(SimpleNamespace(), owner_user_id=uuid4(), project_id=uuid4())
    )


def test_sections_owner_lookup_failure_is_controlled():
    async def current(**scope):
        raise SectionsFailure("PROJECT_NOT_FOUND")

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            require_current_design_context(
                SimpleNamespace(sections_service=SimpleNamespace(current=current)),
                owner_user_id=uuid4(),
                project_id=uuid4(),
            )
        )
    assert error.value.status_code == 404
    assert error.value.detail == {"code": "PROJECT_NOT_FOUND"}
