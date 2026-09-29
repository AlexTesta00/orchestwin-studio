from __future__ import annotations

from datetime import datetime

from orchestwin.knowledge.folder import KnowledgeFolder, build_knowledge_folder, folder_archive
from src.test.python.knowledge.knowledge_fixtures import (
    PUBLISHED_AT,
    REAL_PROJECT_ID,
    real_sources,
)

DEFAULT_PROJECT_NAME = "Calcolo mancia"
ARCHIVE_PROJECT_ID = str(REAL_PROJECT_ID)


def valid_folder(
    *,
    project_name: str = DEFAULT_PROJECT_NAME,
    version_number: int = 1,
    created_at: datetime = PUBLISHED_AT,
) -> KnowledgeFolder:
    return build_knowledge_folder(
        real_sources(project_name=project_name),
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
