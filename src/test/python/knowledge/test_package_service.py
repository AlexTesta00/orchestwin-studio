from __future__ import annotations

import asyncio
import hashlib
import io
import json
import zipfile
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest

from orchestwin.knowledge import package_service as module
from orchestwin.knowledge.export import KnowledgeExportError
from orchestwin.knowledge.layout import KNOWLEDGE_MANIFEST, KNOWLEDGE_SCHEMA_VERSION
from orchestwin.knowledge.package_persistence import KnowledgePackageWriteStatus
from orchestwin.knowledge.package_service import KnowledgePackageService
from orchestwin.knowledge.packages import KnowledgePackageVersion
from orchestwin.knowledge.schema import KnowledgeSchemaError
from src.test.python.artifacts.design_fixtures import OWNER_ID, PROJECT_ID

from .knowledge_fixtures import PUBLISHED_AT, sources

STRANGER = UUID(int=99)


class FakeLoader:
    def __init__(self, package=None, error: KnowledgeExportError | None = None) -> None:
        self.package = sources() if package is None and error is None else package
        self.error = error
        self.calls: list[tuple[UUID, UUID]] = []

    async def load(self, *, owner_user_id: UUID, project_id: UUID):
        self.calls.append((owner_user_id, project_id))
        if self.error is not None:
            raise self.error
        return self.package


class FakeRepository:
    def __init__(self, store: FakeStore, owner_user_id: UUID) -> None:
        self.store = store
        self.owner_user_id = owner_user_id

    async def lock_project(self, *, project_id: UUID) -> bool:
        self.store.locks.append(project_id)
        return self.owner_user_id == OWNER_ID and project_id == PROJECT_ID

    async def latest(self, *, project_id: UUID):
        versions = await self.list(project_id=project_id)
        return versions[0] if versions else None

    async def list(self, *, project_id: UUID, limit: int = 50):
        self.store.limits.append(limit)
        if self.owner_user_id != OWNER_ID:
            return ()
        owned = [item for item, _ in self.store.rows if item.project_id == project_id]
        return tuple(sorted(owned, key=lambda item: -item.version_number))[:limit]

    async def get(self, *, project_id: UUID, version_number: int):
        for item in await self.list(project_id=project_id, limit=1000):
            if item.version_number == version_number:
                return item
        return None

    async def archive(self, *, project_id: UUID, version_number: int):
        if self.owner_user_id != OWNER_ID:
            return None
        for item, content in self.store.rows:
            if item.project_id == project_id and item.version_number == version_number:
                return content
        return None

    async def create(self, version: KnowledgePackageVersion, archive: bytes):
        if self.store.write_status is not KnowledgePackageWriteStatus.WRITTEN:
            return self.store.write_status
        self.store.rows.append((version, archive))
        return KnowledgePackageWriteStatus.WRITTEN


class FakeStore:
    def __init__(self) -> None:
        self.rows: list[tuple[KnowledgePackageVersion, bytes]] = []
        self.locks: list[UUID] = []
        self.limits: list[int] = []
        self.transactions: list[UUID] = []
        self.write_status = KnowledgePackageWriteStatus.WRITTEN

    @asynccontextmanager
    async def transaction(self, *, owner_user_id: UUID):
        self.transactions.append(owner_user_id)
        yield FakeRepository(self, owner_user_id)


def service(loader=None, store=None, *, minutes: int = 0) -> KnowledgePackageService:
    identifiers = iter(UUID(int=9000 + index) for index in range(100))
    return KnowledgePackageService(
        source_loader=FakeLoader() if loader is None else loader,
        store=FakeStore() if store is None else store,
        clock=lambda: PUBLISHED_AT + timedelta(minutes=minutes),
        id_factory=lambda: next(identifiers),
    )


def publish(packages: KnowledgePackageService, owner: UUID = OWNER_ID):
    return asyncio.run(packages.publish(owner_user_id=owner, project_id=PROJECT_ID))


def test_first_publication_records_version_one_with_its_archive() -> None:
    packages = service()

    publication = publish(packages)

    version = publication.version
    (stored, archive) = packages.store.rows[0]
    assert publication.reused is False
    assert stored is version
    assert version.id == UUID(int=9000)
    assert version.project_id == PROJECT_ID
    assert version.owner_user_id == OWNER_ID
    assert version.version_number == 1
    assert version.schema_version == KNOWLEDGE_SCHEMA_VERSION
    assert version.created_at == PUBLISHED_AT
    assert version.file_name == f"orchestwin-{PROJECT_ID}-knowledge-v1.zip"
    assert version.archive_hash == hashlib.sha256(archive).hexdigest()
    assert version.archive_size == len(archive)
    assert version.matches(archive)
    assert version.manifest["package"] == {
        "version_number": 1,
        "content_hash": version.content_hash,
        "created_at": PUBLISHED_AT.isoformat(),
    }
    with zipfile.ZipFile(io.BytesIO(archive)) as folder:
        assert tuple(folder.namelist()) == version.entries
        assert version.file_count == len(folder.namelist())
        assert json.loads(folder.read(KNOWLEDGE_MANIFEST)) == version.manifest
    assert packages.source_loader.calls == [(OWNER_ID, PROJECT_ID)]
    assert packages.store.locks == [PROJECT_ID]


def test_unchanged_project_reuses_the_latest_version() -> None:
    loader, store = FakeLoader(), FakeStore()
    first = publish(service(loader, store))

    second = publish(service(loader, store, minutes=30))

    assert second.reused is True
    assert second.version is first.version
    assert len(store.rows) == 1


def test_changed_content_becomes_the_next_version() -> None:
    package = sources()
    store = FakeStore()
    first = publish(service(FakeLoader(package), store))

    second = publish(
        service(FakeLoader(replace(package, project_name="Lista ospiti 2")), store, minutes=30)
    )

    assert second.reused is False
    assert second.version.version_number == 2
    assert second.version.content_hash != first.version.content_hash
    assert second.version.created_at == PUBLISHED_AT + timedelta(minutes=30)
    assert second.version.file_name.endswith("-knowledge-v2.zip")
    assert [item.version_number for item, _ in store.rows] == [1, 2]


def test_older_schema_version_is_not_reused() -> None:
    loader, store = FakeLoader(), FakeStore()
    first = publish(service(loader, store)).version
    store.rows[0] = (replace(first, schema_version=1), store.rows[0][1])

    second = publish(service(loader, store))

    assert second.reused is False
    assert second.version.version_number == 2
    assert second.version.content_hash == first.content_hash


def test_missing_approvals_stop_the_publication_before_any_write() -> None:
    store = FakeStore()
    packages = service(FakeLoader(error=KnowledgeExportError("DESIGN_APPROVAL_REQUIRED")), store)

    with pytest.raises(KnowledgeExportError) as error:
        publish(packages)

    assert error.value.code == "DESIGN_APPROVAL_REQUIRED"
    assert store.transactions == []
    assert store.rows == []


def test_project_of_another_owner_is_not_found() -> None:
    store = FakeStore()

    with pytest.raises(KnowledgeExportError) as error:
        publish(service(store=store), owner=STRANGER)

    assert error.value.code == "PROJECT_NOT_FOUND"
    assert store.rows == []


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (KnowledgePackageWriteStatus.PROJECT_NOT_FOUND, "PROJECT_NOT_FOUND"),
        (KnowledgePackageWriteStatus.VERSION_CONFLICT, "KNOWLEDGE_PACKAGE_VERSION_CONFLICT"),
    ],
)
def test_rejected_writes_are_reported(status: KnowledgePackageWriteStatus, code: str) -> None:
    store = FakeStore()
    store.write_status = status

    with pytest.raises(KnowledgeExportError) as error:
        publish(service(store=store))

    assert error.value.code == code


def test_folder_that_breaks_its_own_schema_is_never_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(_files) -> None:
        raise KnowledgeSchemaError(
            code="DOCUMENT_INVALID",
            document="manifest",
            location="package",
            message="Field required",
        )

    monkeypatch.setattr(module, "validate_files", broken)
    store = FakeStore()

    with pytest.raises(KnowledgeExportError) as error:
        publish(service(store=store))

    assert error.value.code == "KNOWLEDGE_FOLDER_INVALID"
    assert store.transactions == []


def test_history_lists_the_newest_version_first_within_the_limit() -> None:
    package = sources()
    store = FakeStore()
    publish(service(FakeLoader(package), store))
    publish(service(FakeLoader(replace(package, project_name="Seconda")), store))
    packages = service(store=store)

    versions = asyncio.run(packages.history(owner_user_id=OWNER_ID, project_id=PROJECT_ID))
    bounded = asyncio.run(
        packages.history(owner_user_id=OWNER_ID, project_id=PROJECT_ID, limit=10_000)
    )
    single = asyncio.run(packages.history(owner_user_id=OWNER_ID, project_id=PROJECT_ID, limit=0))

    assert [item.version_number for item in versions] == [2, 1]
    assert bounded == versions
    assert [item.version_number for item in single] == [2]
    assert store.limits[-3:] == [50, 200, 1]


def test_history_of_a_project_of_another_owner_is_not_found() -> None:
    with pytest.raises(KnowledgeExportError) as error:
        asyncio.run(service().history(owner_user_id=STRANGER, project_id=PROJECT_ID))

    assert error.value.code == "PROJECT_NOT_FOUND"


def test_archive_returns_the_stored_bytes_of_a_version() -> None:
    store = FakeStore()
    version = publish(service(store=store)).version

    archive = asyncio.run(
        service(store=store).archive(
            owner_user_id=OWNER_ID, project_id=PROJECT_ID, version_number=1
        )
    )

    assert archive.content == store.rows[0][1]
    assert archive.archive_hash == version.archive_hash
    assert archive.content_hash == version.content_hash
    assert archive.file_name == version.file_name
    assert archive.version_number == 1
    assert archive.entries == version.entries


@pytest.mark.parametrize(("owner", "number"), [(OWNER_ID, 2), (STRANGER, 1)])
def test_unknown_version_or_stranger_gets_no_archive(owner: UUID, number: int) -> None:
    store = FakeStore()
    publish(service(store=store))

    with pytest.raises(KnowledgeExportError) as error:
        asyncio.run(
            service(store=store).archive(
                owner_user_id=owner, project_id=PROJECT_ID, version_number=number
            )
        )

    assert error.value.code == "KNOWLEDGE_PACKAGE_NOT_FOUND"


def test_archive_that_no_longer_matches_its_hash_is_refused() -> None:
    store = FakeStore()
    publish(service(store=store))
    store.rows[0] = (store.rows[0][0], store.rows[0][1] + b"x")

    with pytest.raises(KnowledgeExportError) as error:
        asyncio.run(
            service(store=store).archive(
                owner_user_id=OWNER_ID, project_id=PROJECT_ID, version_number=1
            )
        )

    assert error.value.code == "KNOWLEDGE_PACKAGE_CORRUPTED"
