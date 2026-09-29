from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from orchestwin.cli.context import CommandContext
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.flows.publish import publish_and_pull, pull
from orchestwin.cli.project import ProjectFolder
from orchestwin.knowledge.folder import KnowledgeFolder, build_knowledge_folder, folder_archive

from ..knowledge.knowledge_fixtures import PUBLISHED_AT, real_sources
from .support.terminal import (
    PROJECT_ID,
    Terminal,
    command_context,
    link_folder,
    store_session,
    terminal,
)
from .support.transports import API, ScriptedTransport

PACKAGES = f"{API}/projects/{PROJECT_ID}/knowledge-packages"


@pytest.fixture(scope="module")
def built() -> KnowledgeFolder:
    return build_knowledge_folder(real_sources(), version_number=3, created_at=PUBLISHED_AT)


@pytest.fixture(scope="module")
def archive(built: KnowledgeFolder) -> bytes:
    return folder_archive(built).content


def version(number: int) -> dict[str, object]:
    return {"id": f"version-{number}", "version_number": number, "content_hash": "abc"}


def prepared(
    tmp_path: Path, transport: ScriptedTransport
) -> tuple[CommandContext, ProjectFolder, Terminal]:
    store_session(tmp_path)
    project = link_folder(tmp_path / "project")
    bundle = terminal(tmp_path, transport=transport)
    return command_context(bundle.environment), project, bundle


def expect_archive(
    transport: ScriptedTransport, number: int, content: bytes, digest: str | None = None
) -> None:
    headers = {"Content-Type": "application/zip"}
    headers["X-Content-SHA256"] = hashlib.sha256(content).hexdigest() if digest is None else digest
    transport.expect("GET", f"{PACKAGES}/{number}/archive", body=content, headers=headers)


@pytest.mark.parametrize(("status", "reused"), [(201, False), (200, True)])
def test_publish_downloads_and_unpacks_the_new_version(
    tmp_path: Path, archive: bytes, built: KnowledgeFolder, status: int, reused: bool
) -> None:
    transport = ScriptedTransport()
    transport.expect(
        "POST", PACKAGES, status=status, body={"reused": reused, "version": version(3)}
    )
    expect_archive(transport, 3, archive)
    context, project, bundle = prepared(tmp_path, transport)

    found = publish_and_pull(context, context.client(), project)

    assert found.version_number == 3
    assert found.content_hash == built.content_hash
    assert (project.knowledge / "orchestwin.json").read_text(encoding="utf-8") == built.files[
        "orchestwin.json"
    ]
    assert bundle.output.splitlines() == [
        "Preparing the knowledge folder in the Studio...",
        "Preparing the knowledge folder in the Studio: done in 0 s.",
        "Downloading the knowledge folder...",
        "Downloading the knowledge folder: done in 0 s.",
    ]
    transport.assert_done()


@pytest.mark.parametrize("digest", ["0" * 64, ""])
def test_an_archive_that_does_not_match_its_hash_is_refused(
    tmp_path: Path, archive: bytes, digest: str
) -> None:
    transport = ScriptedTransport()
    transport.expect("POST", PACKAGES, status=201, body={"reused": False, "version": version(3)})
    expect_archive(transport, 3, archive, digest)
    context, project, _ = prepared(tmp_path, transport)

    with pytest.raises(CliError) as caught:
        publish_and_pull(context, context.client(), project)

    assert caught.value.code == "FOLDER_NOT_VERIFIED"
    assert caught.value.values["code"] == "ARCHIVE_HASH_MISMATCH"
    assert not project.knowledge.exists()


def test_a_missing_step_stops_the_publication(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect(
        "POST", PACKAGES, status=409, body={"detail": {"code": "DESIGN_APPROVAL_REQUIRED"}}
    )
    context, project, _ = prepared(tmp_path, transport)

    with pytest.raises(ApiFailure) as caught:
        publish_and_pull(context, context.client(), project)

    assert caught.value.code == "DESIGN_APPROVAL_REQUIRED"
    assert not project.knowledge.exists()
    transport.assert_done()


def test_pull_takes_the_latest_version(tmp_path: Path, archive: bytes) -> None:
    transport = ScriptedTransport()
    transport.expect(
        "GET",
        f"{PACKAGES}?limit=1",
        body={"project_id": PROJECT_ID, "versions": [version(3)]},
    )
    expect_archive(transport, 3, archive)
    context, project, _ = prepared(tmp_path, transport)

    found = pull(context, context.client(), project)

    assert found.version_number == 3
    transport.assert_done()


def test_pull_takes_the_version_asked(tmp_path: Path, archive: bytes) -> None:
    transport = ScriptedTransport()
    expect_archive(transport, 2, archive)
    context, project, _ = prepared(tmp_path, transport)

    pull(context, context.client(), project, 2)

    transport.assert_done()


def test_pull_without_any_version(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect("GET", f"{PACKAGES}?limit=1", body={"project_id": PROJECT_ID, "versions": []})
    context, project, _ = prepared(tmp_path, transport)

    with pytest.raises(CliError) as caught:
        pull(context, context.client(), project)

    assert caught.value.code == "FOLDER_NOT_PUBLISHED"


def test_the_folder_named_in_the_link_is_used(tmp_path: Path, archive: bytes) -> None:
    transport = ScriptedTransport()
    expect_archive(transport, 3, archive)
    context, project, _ = prepared(tmp_path, transport)
    project.update_link(knowledge_folder="knowledge")

    pull(context, context.client(), project, 3)

    assert (tmp_path / "project" / "knowledge" / "orchestwin.json").is_file()
    assert not (tmp_path / "project" / "orchestwin").exists()
