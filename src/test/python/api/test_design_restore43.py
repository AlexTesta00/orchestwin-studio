from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.design import DesignPackagePayload, create_design_router
from orchestwin.artifacts.design_packages import DesignExplorationPackage, DesignPackageVersion
from orchestwin.artifacts.design_revision_application import (
    DesignDiffPersistenceStatus,
    LocalDesignRevisionService,
)
from orchestwin.artifacts.design_revisions import (
    DesignPackageDiff,
    DesignPackageDiffStatus,
    propose_design_revision,
)
from orchestwin.artifacts.references import ArtifactKind, VersionedArtifactReference
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.projects.design_application import DesignVersionAppendStatus
from orchestwin.projects.progress import ProjectStage
from orchestwin.projects.requirements_primitives import (
    UserTwinVersionReference,
    canonical_uuid_tuple,
)
from orchestwin.projects.sections import SectionState
from src.test.python.api.test_design_context import sections_port
from src.test.python.artifacts.design_fixtures import (
    OWNER_ID,
    PROJECT_ID,
    REQUIREMENT_ID,
    TWIN_ID,
    design_package,
    design_version,
    twin_reference,
)

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)
DIFF_ID = UUID("00000000-0000-4000-8000-000000004301")
NEW_VERSION_ID = UUID("00000000-0000-4000-8000-000000004302")
PENDING_DIFF_ID = UUID("00000000-0000-4000-8000-000000004303")
EXTRA_REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000011")
RESTORE = f"/projects/{PROJECT_ID}/design/revisions/restore"
OLD_TWIN = UserTwinVersionReference(
    twin_id=TWIN_ID,
    version_number=1,
    content_hash="c" * 64,
    name="Hotel Receptionist",
)
OTHER_TWIN = UserTwinVersionReference(
    twin_id=UUID("00000000-0000-4000-8000-000000000061"),
    version_number=1,
    content_hash="d" * 64,
    name="Night Porter Twin",
)
OLD_REQUIREMENTS = VersionedArtifactReference(
    kind=ArtifactKind.REQUIREMENTS_SPECIFICATION,
    artifact_id=UUID("00000000-0000-4000-8000-000000000901"),
    version_number=1,
    content_hash="9" * 64,
)


class Store:
    def __init__(self, versions: tuple[DesignPackageVersion, ...]) -> None:
        self.versions = list(versions)
        self.diffs: list[DesignPackageDiff] = []
        self.append_status = DesignVersionAppendStatus.APPENDED
        self.commits = 0


class Packages:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def current(self, *, project_id: UUID) -> DesignPackageVersion | None:
        owned = [item for item in self.store.versions if item.project_id == project_id]
        return owned[-1] if owned else None

    async def history(self, *, project_id: UUID) -> tuple[DesignPackageVersion, ...]:
        return tuple(item for item in self.store.versions if item.project_id == project_id)

    async def append(self, version: DesignPackageVersion) -> DesignVersionAppendStatus:
        if self.store.append_status is not DesignVersionAppendStatus.APPENDED:
            return self.store.append_status
        current = await self.current(project_id=version.project_id)
        if current is not None and version.content_hash == current.content_hash:
            return DesignVersionAppendStatus.CONTENT_CONFLICT
        self.store.versions.append(version)
        return DesignVersionAppendStatus.APPENDED


class Diffs:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def create(self, diff: DesignPackageDiff) -> DesignDiffPersistenceStatus:
        if any(item.id == diff.id for item in self.store.diffs):
            return DesignDiffPersistenceStatus.CONFLICT
        self.store.diffs.append(diff)
        return DesignDiffPersistenceStatus.CREATED

    async def get(self, *, project_id: UUID, diff_id: UUID) -> DesignPackageDiff | None:
        return next(
            (
                item
                for item in self.store.diffs
                if item.project_id == project_id and item.id == diff_id
            ),
            None,
        )

    async def current_proposed(
        self, *, project_id: UUID, base_version_id: UUID
    ) -> DesignPackageDiff | None:
        return next(
            (
                item
                for item in self.store.diffs
                if item.project_id == project_id
                and item.base_version_id == base_version_id
                and item.status is DesignPackageDiffStatus.PROPOSED
            ),
            None,
        )

    async def history(self, *, project_id: UUID) -> tuple[DesignPackageDiff, ...]:
        return tuple(item for item in self.store.diffs if item.project_id == project_id)

    async def save_decision(self, diff: DesignPackageDiff) -> DesignDiffPersistenceStatus:
        for index, item in enumerate(self.store.diffs):
            if item.id == diff.id and item.status is DesignPackageDiffStatus.PROPOSED:
                self.store.diffs[index] = diff
                return DesignDiffPersistenceStatus.UPDATED
        return DesignDiffPersistenceStatus.CONFLICT


class Unit:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.packages = Packages(store)
        self.diffs = Diffs(store)
        self.saved: tuple[list[DesignPackageVersion], list[DesignPackageDiff]] = ([], [])
        self.done = False

    async def __aenter__(self) -> Unit:
        self.saved = (list(self.store.versions), list(self.store.diffs))
        self.done = False
        return self

    async def __aexit__(self, *_: object) -> None:
        if not self.done:
            await self.rollback()

    async def commit(self) -> None:
        self.store.commits += 1
        self.done = True

    async def rollback(self) -> None:
        self.store.versions[:], self.store.diffs[:] = self.saved
        self.done = True


def user() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def service(store: Store) -> LocalDesignRevisionService:
    identifiers = iter((DIFF_ID, NEW_VERSION_ID))

    def factory(*, owner_user_id: UUID) -> Unit:
        assert owner_user_id == OWNER_ID
        return Unit(store)

    return LocalDesignRevisionService(
        uow_factory=factory,
        uuid_factory=lambda: next(identifiers),
        clock=lambda: NOW,
    )


def client_for(store: Store, *, sections=None) -> TestClient:
    app = FastAPI()
    app.state.design_revision_service = service(store)
    if sections is not None:
        app.state.application_runtime = SimpleNamespace(sections_service=sections)
    app.include_router(create_design_router())
    app.dependency_overrides[current_user_dependency] = user
    return TestClient(app)


def asked(package: DesignExplorationPackage, question: str) -> DesignExplorationPackage:
    return replace(package, open_questions=(question,))


def history(*packages: DesignExplorationPackage) -> tuple[DesignPackageVersion, ...]:
    return tuple(
        design_version(version_number=number, package=package)
        for number, package in enumerate(packages, start=1)
    )


def with_twin(
    package: DesignExplorationPackage, twin: UserTwinVersionReference
) -> DesignExplorationPackage:
    return replace(
        package,
        grounding=replace(
            package.grounding,
            requirements_reference=OLD_REQUIREMENTS,
            user_twin_references=(twin,),
        ),
        alternatives=tuple(
            replace(
                alternative,
                user_twin_references=(twin,),
                visual_language=(
                    None
                    if alternative.visual_language is None
                    else replace(
                        alternative.visual_language,
                        twin_fit=tuple(
                            replace(fit, twin_id=twin.twin_id, name=twin.name)
                            for fit in alternative.visual_language.twin_fit
                        ),
                    )
                ),
            )
            for alternative in package.alternatives
        ),
        critiques=tuple(
            replace(critique, user_twin_reference=twin) for critique in package.critiques
        ),
    )


def citing_a_removed_requirement(package: DesignExplorationPackage) -> DesignExplorationPackage:
    identifiers = canonical_uuid_tuple(
        (REQUIREMENT_ID, EXTRA_REQUIREMENT_ID), label="requirement IDs", require_items=True
    )
    return replace(
        package,
        grounding=replace(
            package.grounding,
            requirements_reference=OLD_REQUIREMENTS,
            requirement_ids=identifiers,
        ),
        alternatives=tuple(
            replace(alternative, requirement_ids=identifiers)
            for alternative in package.alternatives
        ),
    )


def three_versions() -> Store:
    return Store(
        history(
            design_package(selected=False),
            design_package(),
            asked(design_package(), "Should the night shift see the same list?"),
        )
    )


@pytest.mark.parametrize(
    ("body", "note"),
    [
        ({"version_number": 2}, "Ripristino della versione 2"),
        ({"version_number": 2, "locale": "it-IT"}, "Ripristino della versione 2"),
        ({"version_number": 2, "locale": "en-US"}, "Restored from version 2"),
    ],
)
def test_a_past_version_comes_back_as_a_new_version_with_the_same_contents(body, note) -> None:
    store = three_versions()
    restored = store.versions[1]

    response = client_for(store).post(RESTORE, json=body)

    assert response.status_code == 201, response.text
    answer = response.json()
    version = answer["revision"]["version"]
    diff = answer["revision"]["diff"]
    assert (answer["reason"], answer["restored_version_number"], answer["note"]) == (
        "RESTORED",
        2,
        note,
    )
    assert answer["revision"]["status"] == "APPLIED"
    assert (version["id"], version["version_number"], version["based_on_version_number"]) == (
        str(NEW_VERSION_ID),
        4,
        3,
    )
    assert version["content_hash"] == restored.content_hash
    assert version["package"] == DesignPackagePayload.from_domain(restored.package).model_dump(
        mode="json"
    )
    assert version["ready_for_gate"] is True
    assert (diff["id"], diff["status"], diff["decision_reason"]) == (str(DIFF_ID), "APPROVED", note)
    assert (diff["base_version_number"], diff["applied_version_id"]) == (3, str(NEW_VERSION_ID))
    assert [item.version_number for item in store.versions] == [1, 2, 3, 4]
    assert store.versions[-1].package == restored.package
    assert store.versions[-1].created_by_user_id == OWNER_ID
    assert [(item.status, item.decision_reason) for item in store.diffs] == [
        (DesignPackageDiffStatus.APPROVED, note)
    ]
    assert store.commits == 1


def test_the_first_version_without_a_choice_comes_back_waiting_for_a_choice() -> None:
    store = three_versions()

    response = client_for(store).post(RESTORE, json={"version_number": 1})

    assert response.status_code == 201, response.text
    version = response.json()["revision"]["version"]
    assert version["version_number"] == 4
    assert version["content_hash"] == store.versions[0].content_hash
    assert version["ready_for_gate"] is False
    assert store.versions[-1].package.owner_selected_alternative_id is None


def test_a_version_of_older_twins_is_reanchored_to_the_current_grounding() -> None:
    store = Store(
        history(
            design_package(selected=False),
            with_twin(design_package(), OLD_TWIN),
            asked(design_package(), "Should the night shift see the same list?"),
        )
    )

    response = client_for(store).post(RESTORE, json={"version_number": 2})

    assert response.status_code == 201, response.text
    created = store.versions[-1]
    assert created.package == design_package()
    assert created.package.grounding == store.versions[2].package.grounding
    assert created.package.alternatives[0].user_twin_references == (twin_reference(),)
    assert created.package.critiques[0].user_twin_reference == twin_reference()
    assert response.json()["revision"]["version"]["content_hash"] == design_package().content_hash


@pytest.mark.parametrize(
    ("old", "code"),
    [
        (with_twin(design_package(), OTHER_TWIN), "TWIN_SET_CHANGED"),
        (citing_a_removed_requirement(design_package()), "REQUIREMENT_NO_LONGER_AVAILABLE"),
    ],
    ids=["twins", "requirements"],
)
def test_a_version_that_cannot_be_reanchored_is_refused_without_changes(old, code) -> None:
    store = Store(
        history(
            design_package(selected=False),
            old,
            asked(design_package(), "Should the night shift see the same list?"),
        )
    )

    response = client_for(store).post(RESTORE, json={"version_number": 2})

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": code}}
    assert [item.version_number for item in store.versions] == [1, 2, 3]
    assert store.diffs == []


@pytest.mark.parametrize("number", [3, 1])
def test_the_current_version_or_one_equal_to_it_is_not_restored(number) -> None:
    store = Store(
        history(
            design_package(),
            asked(design_package(), "Should the night shift see the same list?"),
            design_package(),
        )
    )

    response = client_for(store).post(RESTORE, json={"version_number": number})

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "DESIGN_RESTORE_CURRENT"}}
    assert len(store.versions) == 3
    assert store.diffs == []


def test_a_version_that_does_not_exist_is_not_found() -> None:
    store = three_versions()

    response = client_for(store).post(RESTORE, json={"version_number": 9})

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "DESIGN_VERSION_NOT_FOUND"}}
    assert len(store.versions) == 3


def test_a_project_without_a_design_has_nothing_to_restore() -> None:
    store = Store(())

    response = client_for(store).post(RESTORE, json={"version_number": 1})

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "PACKAGE_NOT_FOUND"}}


def test_a_change_waiting_for_a_decision_blocks_the_restore() -> None:
    store = three_versions()
    current = store.versions[-1]
    proposal = propose_design_revision(
        diff_id=PENDING_DIFF_ID,
        owner_user_id=OWNER_ID,
        base_version=current,
        proposed_package=asked(current.package, "Should the desk show the arrivals?"),
        created_at=NOW,
    )
    assert proposal.diff is not None
    store.diffs.append(proposal.diff)

    response = client_for(store).post(RESTORE, json={"version_number": 2})

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "DIFF_ALREADY_PENDING"}}
    assert [item.id for item in store.diffs] == [PENDING_DIFF_ID]
    assert len(store.versions) == 3


def test_a_refused_new_version_leaves_no_change_waiting_behind() -> None:
    store = three_versions()
    store.append_status = DesignVersionAppendStatus.VERSION_CONFLICT

    response = client_for(store).post(RESTORE, json={"version_number": 2})

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "PERSISTENCE_REJECTED"}}
    assert store.diffs == []
    assert len(store.versions) == 3
    assert store.commits == 0


def test_an_upstream_step_to_update_refuses_the_restore_before_the_service() -> None:
    store = three_versions()
    sections = sections_port(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
        states={ProjectStage.REQUIREMENTS: SectionState.TO_UPDATE},
    )

    with client_for(store, sections=sections) as client:
        response = client.post(RESTORE, json={"version_number": 2})

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "DESIGN_CONTEXT_CHANGED"}}
    assert len(store.versions) == 3
    assert len(sections.calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"version_number": 0},
        {"version_number": -2},
        {"version_number": "2"},
        {"version_number": 2.0},
        {"version_number": 2.5},
        {"version_number": True},
        {"version_number": None},
        {"version_number": 2, "reason": "RESTORED"},
        {"version_number": 2, "locale": "x"},
    ],
    ids=[
        "missing",
        "zero",
        "negative",
        "text",
        "float",
        "fraction",
        "boolean",
        "null",
        "extra",
        "locale",
    ],
)
def test_a_body_that_is_not_a_positive_whole_number_is_refused(body) -> None:
    store = three_versions()

    response = client_for(store).post(RESTORE, json=body)

    assert response.status_code == 422
    assert len(store.versions) == 3
    assert store.diffs == []


def test_the_body_is_checked_before_the_service_is_looked_for() -> None:
    app = FastAPI()
    app.include_router(create_design_router())
    app.dependency_overrides[current_user_dependency] = user
    client = TestClient(app)

    invalid = client.post(RESTORE, json={"version_number": 0})
    valid = client.post(RESTORE, json={"version_number": 2})

    assert invalid.status_code == 422
    assert valid.status_code == 503
    assert valid.json() == {"detail": "design_revision_service_unavailable"}


def test_the_route_is_described_with_its_body_and_its_answer() -> None:
    app = FastAPI()
    app.include_router(create_design_router())
    document = app.openapi()
    operation = document["paths"]["/projects/{project_id}/design/revisions/restore"]["post"]
    schemas = document["components"]["schemas"]

    assert operation["operationId"] == "restoreDesignVersion"
    assert set(operation["responses"]) >= {"201", "422"}
    assert schemas["DesignRestoreRequest"]["required"] == ["version_number"]
    assert schemas["DesignRestorePayload"]["properties"]["reason"]["const"] == "RESTORED"
