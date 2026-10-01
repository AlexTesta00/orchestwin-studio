from fastapi import HTTPException

from orchestwin.projects.progress import ProjectStage
from orchestwin.projects.sections import SectionState
from orchestwin.projects.sections_service import PROJECT_NOT_FOUND, SectionsFailure

DESIGN_CONTEXT_CHANGED = "DESIGN_CONTEXT_CHANGED"


async def require_current_design_context(runtime, *, owner_user_id, project_id) -> None:
    service = getattr(runtime, "sections_service", None)
    if service is None:
        return
    try:
        sections = await service.current(owner_user_id=owner_user_id, project_id=project_id)
    except SectionsFailure as error:
        raise HTTPException(
            404 if error.code == PROJECT_NOT_FOUND else 409, detail={"code": error.code}
        ) from None
    ready = {SectionState.FINE, SectionState.UPDATE_AVAILABLE}
    if any(
        sections.section(key).state not in ready
        for key in (
            ProjectStage.BRIEF,
            ProjectStage.TEAM,
            ProjectStage.USER_TWINS,
            ProjectStage.REQUIREMENTS,
        )
    ) or sections.section(ProjectStage.DESIGN).state not in ready | {SectionState.IN_PROGRESS}:
        raise HTTPException(409, detail={"code": DESIGN_CONTEXT_CHANGED})
