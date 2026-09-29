from __future__ import annotations

from datetime import datetime

from orchestwin.knowledge.folder import KnowledgeFolder, build_knowledge_folder, folder_archive
from orchestwin.knowledge.state import ProjectStateSources
from src.test.python.knowledge.knowledge_fixtures import (
    PUBLISHED_AT,
    REAL_PROJECT_ID,
    partial_sources,
)

DEFAULT_PROJECT_NAME = "Calcolo mancia"
ARCHIVE_PROJECT_ID = str(REAL_PROJECT_ID)
COMPLETE_STAGE = "design"


def stage_folder(
    *,
    through: str,
    project_name: str = DEFAULT_PROJECT_NAME,
    version_number: int = 1,
    created_at: datetime = PUBLISHED_AT,
    state: ProjectStateSources | None = None,
) -> KnowledgeFolder:
    sources = partial_sources(
        through, project_name=project_name, state=state or ProjectStateSources()
    )
    return build_knowledge_folder(sources, version_number=version_number, created_at=created_at)


def valid_folder(
    *,
    project_name: str = DEFAULT_PROJECT_NAME,
    version_number: int = 1,
    created_at: datetime = PUBLISHED_AT,
) -> KnowledgeFolder:
    return stage_folder(
        through=COMPLETE_STAGE,
        project_name=project_name,
        version_number=version_number,
        created_at=created_at,
    )


def valid_archive(*, project_name: str = DEFAULT_PROJECT_NAME, version_number: int = 1) -> bytes:
    folder = valid_folder(project_name=project_name, version_number=version_number)
    return folder_archive(folder).content


def valid_files(
    *, project_name: str = DEFAULT_PROJECT_NAME, version_number: int = 1
) -> dict[str, str]:
    return dict(valid_folder(project_name=project_name, version_number=version_number).files)


def partial_archive(
    *, through: str, project_name: str = DEFAULT_PROJECT_NAME, version_number: int = 1
) -> bytes:
    folder = stage_folder(through=through, project_name=project_name, version_number=version_number)
    return folder_archive(folder).content


def state_archive(
    *,
    project_name: str = DEFAULT_PROJECT_NAME,
    version_number: int = 1,
    state: ProjectStateSources,
) -> bytes:
    folder = stage_folder(
        through=COMPLETE_STAGE,
        project_name=project_name,
        version_number=version_number,
        state=state,
    )
    return folder_archive(folder).content
