from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from orchestwin.knowledge.archive import MOCKUP_LOCATION, verify_folder
from orchestwin.knowledge.project_import_service import ProjectImportError, ProjectImportService

from .test_knowledge_generated_mockup_import import (
    IMPORTED_AT,
    NEW_OWNER,
    appended,
    edited,
    refusal,
    styled,
)
from .test_knowledge_generated_mockup_support import archive_of, generated_folder

AUTOCOMPLETE = '<input name="q" aria-label="Cerca" autocomplete="off">'


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        (appended(AUTOCOMPLETE), "ATTRIBUTE_FORBIDDEN"),
        (appended('<p style="color:red">Nota</p>'), "ATTRIBUTE_FORBIDDEN"),
        (appended("<p><u>Nota</u></p>"), "ELEMENT_FORBIDDEN"),
        (appended('<a href="#SCR-009">Altro</a>'), "LINK_TARGET"),
        (appended('<p data-req="REQ-001, REQ-002">Nota</p>'), "DATA_REQ_INVALID"),
        (styled(".kpi{color:red}"), "STYLES_COLOUR"),
        (styled("html{margin:0}"), "STYLES_SELECTOR"),
    ],
)
def test_a_folder_whose_mockup_holds_a_slip_that_the_repair_would_remove_is_still_refused(
    change: Callable[[dict[str, object]], None], rule: str
) -> None:
    refused = refusal(edited(change))

    assert (refused.code, refused.detail) == (
        "FOLDER_DOCUMENT_INVALID",
        f"{MOCKUP_LOCATION}: {rule}",
    )


def test_the_unchanged_folder_is_still_accepted() -> None:
    folder = generated_folder()

    assert verify_folder(folder.files).content_hash == folder.content_hash


def test_an_archive_with_a_slip_that_the_repair_would_remove_never_reaches_the_database() -> None:
    opened: list[bool] = []

    def session_factory():
        opened.append(True)
        raise AssertionError("the import must not reach the database")

    service = ProjectImportService(session_factory=session_factory, clock=lambda: IMPORTED_AT)
    content = archive_of(edited(appended(AUTOCOMPLETE)))

    with pytest.raises(ProjectImportError) as caught:
        asyncio.run(service.import_archive(owner_user_id=NEW_OWNER, content=content))

    assert (caught.value.code, caught.value.detail) == (
        "FOLDER_DOCUMENT_INVALID",
        f"{MOCKUP_LOCATION}: ATTRIBUTE_FORBIDDEN",
    )
    assert opened == []
