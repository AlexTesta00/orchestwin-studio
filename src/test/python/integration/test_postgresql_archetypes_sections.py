from __future__ import annotations

import asyncio
import os
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from orchestwin.agents.persistence.team_gate import SqlAlchemyAgentTeamUnitOfWorkFactory
from orchestwin.agents.team_gate import LocalAgentTeamApprovalService
from orchestwin.api.user_modeling import ProfileRevisionProposalRequest
from orchestwin.twins.persistence.repositories import (
    SqlAlchemyPersonaVersionRepository,
    SqlAlchemyUserModelingSnapshotRepository,
    SqlAlchemyUserTwinVersionRepository,
    VersionAppendStatus,
)
from orchestwin.twins.realignment import UserModelingRealignment
from orchestwin.twins.realignment_service import (
    UserModelingRealignmentFailure,
    UserModelingRealignmentService,
)
from orchestwin.twins.revision_persistence import (
    DiffPersistenceStatus,
    SqlAlchemyUserTwinProfileDiffRepository,
)
from orchestwin.twins.revisions import propose_user_twin_profile_diff
from orchestwin.twins.runtime import (
    ManagedUserModelingUnitOfWork,
    SqlAlchemyUserModelingGovernanceAdapter,
)
from orchestwin.twins.user_twins import UserModelingSnapshotVersion, create_user_modeling_snapshot
from src.test.python.integration.cli_journey_support import (
    DATABASE_VARIABLE,
    TEST_EMAIL,
    TEST_PASSWORD,
    StudioApi,
    StudioProcess,
    database_runtime,
    journey_scene,
    run_coroutine,
)
from src.test.python.integration.test_postgresql_sections import (
    approved,
    by_key,
    design_content,
    first_pass,
    optional_agent,
    publish,
    request,
    sections,
)
from src.test.python.twins.test_user_modeling_realignment import first_snapshot

pytestmark = pytest.mark.integration
MODEL = "/user-modeling"


def archetype_body(archetype):
    return {key: archetype[key] for key in ("name", "description", "role", "goals", "context")}


async def stored_snapshot(database_url, snapshot_id):
    runtime = database_runtime(database_url)
    try:
        async with runtime.session_factory() as session:
            row = (
                await session.execute(
                    sa.text(
                        "SELECT snapshot, content_hash FROM user_modeling_snapshot_versions WHERE id = :id"
                    ),
                    {"id": UUID(snapshot_id)},
                )
            ).one()
            return deepcopy(row.snapshot), row.content_hash
    finally:
        await runtime.dispose()


async def seed_legacy_snapshot(database_url, owner_user_id, project_id):
    runtime = database_runtime(database_url)
    try:
        async with runtime.session_factory() as session:
            repository = SqlAlchemyUserModelingSnapshotRepository(
                session, owner_user_id=owner_user_id
            )
            current = await repository.current(project_id=project_id)
            historical = first_snapshot().snapshot
            personas = tuple(
                replace(
                    version, id=uuid4(), project_id=project_id, created_by_user_id=owner_user_id
                )
                for version in historical.persona_versions
            )
            twins = []
            for old in historical.twin_versions:
                profile = replace(
                    old.profile,
                    project_brief_reference=current.snapshot.project_brief_reference,
                    agent_team_reference=current.snapshot.agent_team_reference,
                    catalog_version=current.snapshot.catalog_version,
                    catalog_content_hash=current.snapshot.catalog_content_hash,
                )
                twins.append(
                    replace(
                        old,
                        id=uuid4(),
                        project_id=project_id,
                        profile=profile,
                        content_hash=profile.content_hash,
                        created_by_user_id=owner_user_id,
                    )
                )
            snapshot = create_user_modeling_snapshot(
                project_id=project_id,
                project_brief_reference=current.snapshot.project_brief_reference,
                agent_team_reference=current.snapshot.agent_team_reference,
                catalog_version=current.snapshot.catalog_version,
                catalog_content_hash=current.snapshot.catalog_content_hash,
                persona_versions=personas,
                twin_versions=twins,
            )
            legacy = UserModelingSnapshotVersion(
                id=uuid4(),
                project_id=project_id,
                version_number=current.version_number + 1,
                based_on_version_number=current.version_number,
                snapshot=snapshot,
                content_hash=snapshot.content_hash,
                created_by_user_id=owner_user_id,
                created_at=datetime.now(UTC),
            )
            for persona in personas:
                assert (
                    await SqlAlchemyPersonaVersionRepository(
                        session, owner_user_id=owner_user_id
                    ).append(persona)
                    is VersionAppendStatus.APPENDED
                )
            for twin in twins:
                assert (
                    await SqlAlchemyUserTwinVersionRepository(
                        session, owner_user_id=owner_user_id
                    ).append(twin)
                    is VersionAppendStatus.APPENDED
                )
            assert await repository.append(legacy) is VersionAppendStatus.APPENDED
            await session.commit()
            return str(legacy.id), legacy.content_hash
    finally:
        await runtime.dispose()


def assert_progress(scene, action):
    projects = scene.api.document("/projects")
    listing = projects if isinstance(projects, list) else projects["items"]
    current = next(project for project in listing if project["id"] == scene.project_id)
    assert current["next_action"] == action
    status = scene.ut("status", "--json")
    import json

    document = json.loads(status.output)
    assert document["next_action"] == action
    assert document["next_command"] == (
        "ut sections update" if action == "UPDATE_SECTIONS" else "ut init"
    )


def test_owner_archetype_crud_pending_guard_same_twin_regeneration_and_downstream_sql(
    tmp_path: Path,
):
    database_url = os.environ.get(DATABASE_VARIABLE, "")
    assert database_url
    with StudioProcess(tmp_path / "studio", database_url) as studio:
        api = StudioApi(studio.origin)
        assert api.register(TEST_EMAIL, TEST_PASSWORD).status == 201
        scene = journey_scene(tmp_path, studio.origin, studio.port, api)
        first_pass(scene)
        owner = api.document("/auth/me")["id"]
        original = scene.document(MODEL + "/snapshots/current")
        stored = run_coroutine(stored_snapshot(database_url, original["id"]))
        historical = scene.document(MODEL + "/snapshots")
        assert any(
            version["id"] == original["id"] and version["content_hash"] == original["content_hash"]
            for version in historical
        )
        assert run_coroutine(stored_snapshot(database_url, original["id"])) == stored
        assert all("view" not in twin for twin in stored[0]["twin_versions"])
        archetypes = scene.document(MODEL + "/archetypes")
        assert len(archetypes) == 1, archetypes
        core = archetypes[0]
        extra_body = {
            "name": "Temporary auditor",
            "description": "Checks monthly totals.",
            "role": "Auditor",
            "goals": ["Find errors"],
            "context": "Monthly review",
        }
        created = request(scene, "POST", MODEL + "/archetypes", extra_body)
        assert created.status == 201
        extra = created.json()
        outsider = StudioApi(studio.origin)
        assert outsider.register("other-owner@example.com", TEST_PASSWORD).status == 201
        assert outsider.request("GET", scene.base + MODEL + "/archetypes").status == 404
        assert (
            outsider.request(
                "PATCH",
                scene.base + MODEL + "/archetypes/" + extra["persona_id"],
                extra_body | {"based_on_version_number": 1},
            ).status
            == 404
        )
        extra_path = MODEL + "/archetypes/" + extra["persona_id"]
        edited = request(
            scene,
            "PATCH",
            extra_path,
            extra_body | {"name": "Senior auditor", "based_on_version_number": 1},
        )
        assert edited.status == 200, f"archetype edit answered {edited.status} {edited.code}"
        assert edited.json()["version_number"] == 2
        stale = request(scene, "DELETE", extra_path, {"based_on_version_number": 1})
        assert (stale.status, stale.code) == (409, "ARCHETYPE_VERSION_CONFLICT")
        archived = request(scene, "DELETE", extra_path, {"based_on_version_number": 2})
        assert archived.status == 200, (
            f"archetype archive answered {archived.status} {archived.code}"
        )
        assert archived.json()["archived"]
        assert extra["persona_id"] not in {
            item["persona_id"] for item in scene.document(MODEL + "/archetypes")
        }
        assert by_key(sections(scene))["USER_TWINS"]["state"] == "FINE"
        core_path = MODEL + "/archetypes/" + core["persona_id"]
        changed = archetype_body(core) | {
            "description": "Needs an explicit total before confirming each payment.",
            "based_on_version_number": core["version_number"],
        }
        changed_core = request(scene, "PATCH", core_path, changed)
        assert changed_core.status == 200, (
            f"core archetype edit answered {changed_core.status} {changed_core.code}"
        )
        ready = scene.document(MODEL + "/readiness")
        assert (
            ready["snapshot_exists"]
            and not ready["archetypes_current"]
            and not ready["approved_current_snapshot"]
        )
        stale_sections = by_key(sections(scene))
        assert stale_sections["USER_TWINS"]["blocked"] == "PREPARE_TWINS"
        assert stale_sections["USER_TWINS"]["reasons"] == ["ARCHETYPES_CHANGED"]
        assert stale_sections["PACKAGE"]["state"] == "TO_UPDATE"
        assert_progress(scene, "PREPARE_TWINS")
        refused = request(scene, "POST", MODEL + "/context-alignment")
        assert (refused.status, refused.code) == (409, "ARCHETYPES_CHANGED")
        refused = request(scene, "POST", "/requirements/proposals")
        assert (refused.status, refused.code) == (409, "USER_MODELING_APPROVAL_REQUIRED")
        twin = original["snapshot"]["twin_versions"][0]
        proposal = request(
            scene,
            "POST",
            MODEL + f"/twins/{twin['twin_id']}/revisions",
            {
                "replacements": [
                    {
                        "field": "goals",
                        "value": {
                            "kind": "ITEMS",
                            "text": None,
                            "items": ["See the total before confirming"],
                            "reason": None,
                        },
                        "epistemic_status": "USER_PROVIDED",
                        "confidence": 1.0,
                        "provenance": [
                            {
                                "source_kind": "OWNER_INPUT",
                                "source_id": owner,
                                "source_version": 1,
                                "content_hash": None,
                                "locator": "user_twin.goals",
                                "summary": "Owner supplied this goal.",
                            }
                        ],
                        "human_validation": "NOT_REQUIRED",
                        "rationale": None,
                    }
                ]
            },
        )
        assert proposal.status == 200, (
            f"twin revision proposal answered {proposal.status} {proposal.code}"
        )
        refused = request(scene, "POST", MODEL + "/snapshots/generate")
        assert (refused.status, refused.code) == (409, "USER_TWIN_REVISION_PENDING")
        diff = proposal.json()["diff"]
        rejected = request(
            scene,
            "POST",
            MODEL + f"/revisions/{diff['id']}/decision",
            {"decision": "REJECT", "reason": "Regenerate from the edited archetype instead."},
        )
        assert rejected.status == 200, (
            f"twin revision rejection answered {rejected.status} {rejected.code}"
        )
        generated = request(scene, "POST", MODEL + "/snapshots/generate")
        assert generated.status == 200, (
            f"twin regeneration answered {generated.status} {generated.code}"
        )
        fresh = scene.document(MODEL + "/snapshots/current")
        before_twins = {
            item["profile"]["persona_reference"]["persona_id"]: item
            for item in original["snapshot"]["twin_versions"]
        }
        after_twins = {
            item["profile"]["persona_reference"]["persona_id"]: item
            for item in fresh["snapshot"]["twin_versions"]
        }
        assert before_twins.keys() == after_twins.keys()
        for persona_id, previous in before_twins.items():
            current = after_twins[persona_id]
            assert current["twin_id"] == previous["twin_id"]
            assert current["version_number"] > previous["version_number"]
            assert current["based_on_version_number"] == previous["version_number"]
        approved(scene, "POST", MODEL + "/gate/submit", None, {200, 201})
        approved(scene, "POST", MODEL + "/gate/decision", {"action": "APPROVE"}, {200})
        assert_progress(scene, "UPDATE_SECTIONS")
        before_design = scene.document("/design/current")
        gesture = request(scene, "POST", "/sections/alignment")
        assert gesture.status == 200, f"sections alignment answered {gesture.status} {gesture.code}"
        assert [(item["key"], item["outcome"]) for item in gesture.json()["results"]] == [
            ("REQUIREMENTS", "ALIGNED"),
            ("DESIGN", "ALIGNED"),
        ]
        assert design_content(scene.document("/design/current")) == design_content(before_design)
        publish(scene)
        assert run_coroutine(stored_snapshot(database_url, original["id"])) == stored
        core = next(
            item
            for item in scene.document(MODEL + "/archetypes")
            if item["persona_id"] == core["persona_id"]
        )
        replacement_created = request(
            scene,
            "POST",
            MODEL + "/archetypes",
            {
                "name": "New dinner organizer",
                "description": "Checks how the bill is split for the next dinner.",
                "role": "Dinner organizer",
                "goals": ["Check each share before collecting payment"],
                "context": "Planning a dinner with friends",
            },
        )
        assert replacement_created.status == 201, (
            f"replacement archetype creation answered {replacement_created.status} {replacement_created.code}"
        )
        replacement_archetype = replacement_created.json()
        archived_core = request(
            scene, "DELETE", core_path, {"based_on_version_number": core["version_number"]}
        )
        assert archived_core.status == 200, (
            f"core archetype archive answered {archived_core.status} {archived_core.code}"
        )
        active_persona_ids = {item["persona_id"] for item in scene.document(MODEL + "/archetypes")}
        assert active_persona_ids == {replacement_archetype["persona_id"]}
        assert core["persona_id"] not in active_persona_ids
        assert by_key(sections(scene))["USER_TWINS"]["blocked"] == "PREPARE_TWINS"
        generated = request(scene, "POST", MODEL + "/snapshots/generate")
        assert generated.status == 200, (
            f"twin generation after archive answered {generated.status} {generated.code}"
        )
        replacement_snapshot = scene.document(MODEL + "/snapshots/current")
        replacement_twins = replacement_snapshot["snapshot"]["twin_versions"]
        assert len(replacement_twins) == 1
        replacement_twin = replacement_twins[0]
        assert (
            replacement_twin["profile"]["persona_reference"]["persona_id"]
            == (replacement_archetype["persona_id"])
        )
        assert replacement_twin["twin_id"] not in {
            previous["twin_id"] for previous in after_twins.values()
        }
        assert replacement_twin["version_number"] == 1
        assert replacement_twin["based_on_version_number"] is None
        approved(scene, "POST", MODEL + "/gate/submit", None, {200, 201})
        approved(scene, "POST", MODEL + "/gate/decision", {"action": "APPROVE"}, {200})
        assert by_key(sections(scene))["REQUIREMENTS"]["blocked"] == "TWIN_NO_LONGER_AVAILABLE"
        legacy_id, legacy_hash = run_coroutine(
            seed_legacy_snapshot(database_url, UUID(owner), UUID(scene.project_id))
        )
        legacy_stored = run_coroutine(stored_snapshot(database_url, legacy_id))
        assert legacy_stored[1] == legacy_hash
        for persona in legacy_stored[0]["persona_versions"]:
            assert "archived" not in persona["profile"]
        for twin in legacy_stored[0]["twin_versions"]:
            assert "view" not in twin
            assert not {
                "user_twin.description",
                "user_twin.represents",
                "user_twin.does_not_represent",
                "user_twin.evidence_gaps",
            } & {observation["observation_key"] for observation in twin["profile"]["observations"]}
        history = scene.document(MODEL + "/snapshots")
        assert (
            next(version for version in history if version["id"] == legacy_id)["content_hash"]
            == legacy_hash
        )
        current = scene.document(MODEL + "/snapshots/current")
        assert current["id"] == legacy_id
        assert all(
            twin["view"]["persona"]["description"]["value"]["text"]
            for twin in current["snapshot"]["twin_versions"]
        )
        assert run_coroutine(stored_snapshot(database_url, legacy_id)) == legacy_stored
        assert run_coroutine(stored_snapshot(database_url, original["id"])) == stored


async def concurrent_sql_realign(database_url, owner_user_id, project_id):
    runtime = database_runtime(database_url)
    ready = asyncio.Event()
    waiting = 0

    class RacingUnit(ManagedUserModelingUnitOfWork):
        async def lock_project(self, *, project_id):
            nonlocal waiting
            waiting += 1
            if waiting == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), 10)
            return await super().lock_project(project_id=project_id)

    service = UserModelingRealignmentService(
        governance=SqlAlchemyUserModelingGovernanceAdapter(runtime.session_factory),
        team_queries=LocalAgentTeamApprovalService(
            unit_of_work_factory=SqlAlchemyAgentTeamUnitOfWorkFactory(runtime.session_factory)
        ),
        uow_factory=lambda *, owner_user_id: RacingUnit(
            runtime.session_factory(), owner_user_id=owner_user_id
        ),
    )

    async def attempt():
        try:
            return await service.realign(owner_user_id=owner_user_id, project_id=project_id)
        except UserModelingRealignmentFailure as error:
            return error.code

    try:
        answers = await asyncio.wait_for(asyncio.gather(attempt(), attempt()), 30)
        assert sum(isinstance(answer, UserModelingRealignment) for answer in answers) == 1
        assert "ALREADY_ALIGNED" in answers
    finally:
        await runtime.dispose()


async def historical_pending_diff(database_url, owner_user_id, project_id):
    runtime = database_runtime(database_url)
    try:
        async with runtime.session_factory() as session:
            history = await SqlAlchemyUserModelingSnapshotRepository(
                session, owner_user_id=owner_user_id
            ).history(project_id=project_id)
            base = next(version for version in history if version.version_number == 1)
            replacement = ProfileRevisionProposalRequest.model_validate(
                {
                    "replacements": [
                        {
                            "field": "goals",
                            "value": {
                                "kind": "ITEMS",
                                "text": None,
                                "items": ["Review the historical suggestion before updating"],
                                "reason": None,
                            },
                            "epistemic_status": "USER_PROVIDED",
                            "confidence": 1.0,
                            "provenance": [
                                {
                                    "source_kind": "OWNER_INPUT",
                                    "source_id": str(owner_user_id),
                                    "source_version": 1,
                                    "content_hash": None,
                                    "locator": "user_twin.goals",
                                    "summary": "Historical owner suggestion.",
                                }
                            ],
                            "human_validation": "NOT_REQUIRED",
                            "rationale": None,
                        }
                    ]
                }
            ).to_domain()
            proposal = propose_user_twin_profile_diff(
                base_snapshot_version=base,
                twin_id=base.snapshot.twin_versions[0].twin_id,
                replacements=replacement,
                diff_id=uuid4(),
                created_by_user_id=owner_user_id,
                created_at=datetime.now(UTC),
            )
            assert proposal.diff is not None
            status = await SqlAlchemyUserTwinProfileDiffRepository(
                session, owner_user_id=owner_user_id
            ).create(proposal.diff)
            assert status is DiffPersistenceStatus.CREATED
            await session.commit()
    finally:
        await runtime.dispose()


def test_two_controlled_concurrent_realignments_serialize_on_real_postgresql(tmp_path: Path):
    database_url = os.environ.get(DATABASE_VARIABLE, "")
    assert database_url
    with StudioProcess(tmp_path / "studio", database_url) as studio:
        api = StudioApi(studio.origin)
        assert api.register(TEST_EMAIL, TEST_PASSWORD).status == 201
        scene = journey_scene(tmp_path, studio.origin, studio.port, api)
        first_pass(scene)
        original = scene.document(MODEL + "/snapshots/current")
        proposal = scene.document("/team-proposals/current")
        agent = optional_agent(proposal)
        approved(
            scene,
            "PATCH",
            "/team-proposals/current",
            {
                "selected_agent_ids": [*proposal["selected_agent_ids"], agent],
                "owner_rationales": [
                    {"agent_id": agent, "statement": "The owner requests this perspective."}
                ],
            },
            {201},
        )
        approved(scene, "POST", "/gates/agent-team/submit", None, {201})
        approved(scene, "POST", "/gates/agent-team/decisions", {"action": "APPROVE"}, {200})
        owner = UUID(api.document("/auth/me")["id"])
        run_coroutine(concurrent_sql_realign(database_url, owner, UUID(scene.project_id)))
        history = scene.document(MODEL + "/snapshots")
        assert len(history) == 2 and {version["version_number"] for version in history} == {1, 2}
        fresh = scene.document(MODEL + "/snapshots/current")
        assert {item["twin_id"] for item in fresh["snapshot"]["twin_versions"]} == {
            item["twin_id"] for item in original["snapshot"]["twin_versions"]
        }
        refused = request(scene, "POST", MODEL + "/context-alignment")
        assert (refused.status, refused.code) == (409, "ALREADY_ALIGNED")
        approved(scene, "POST", MODEL + "/gate/submit", None, {200, 201})
        approved(scene, "POST", MODEL + "/gate/decision", {"action": "APPROVE"}, {200})
        proposal = scene.document("/team-proposals/current")
        agent = optional_agent(proposal)
        approved(
            scene,
            "PATCH",
            "/team-proposals/current",
            {
                "selected_agent_ids": [*proposal["selected_agent_ids"], agent],
                "owner_rationales": [
                    {"agent_id": agent, "statement": "The owner requests another perspective."}
                ],
            },
            {201},
        )
        approved(scene, "POST", "/gates/agent-team/submit", None, {201})
        approved(scene, "POST", "/gates/agent-team/decisions", {"action": "APPROVE"}, {200})
        run_coroutine(historical_pending_diff(database_url, owner, UUID(scene.project_id)))
        assert by_key(sections(scene))["USER_TWINS"]["blocked"] == "REVISION_PENDING"
        assert_progress(scene, "CONFIRM_TWINS")
        refused = request(scene, "POST", MODEL + "/context-alignment")
        assert (refused.status, refused.code) == (409, "USER_TWIN_REVISION_PENDING")
