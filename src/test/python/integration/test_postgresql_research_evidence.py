from __future__ import annotations

import asyncio
import importlib
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from orchestwin.api import twin_learning
from orchestwin.api.research_evidence import (
    EvidenceAssociateBody,
    EvidenceBody,
    EvidenceDeleteBody,
    EvidenceRetireBody,
    ResearchEvidenceApplication,
)
from orchestwin.api.twin_learning import (
    TwinLearningApplication,
    TwinUpdateDecisionRequest,
    TwinUpdateRequest,
)
from orchestwin.models.evidence_update import EvidenceUpdateOutput
from orchestwin.persistence import create_database_runtime
from orchestwin.persistence.migrate import downgrade_database
from orchestwin.projects.evidence_application import append_evidence_profiles, apply_evidence_change
from orchestwin.projects.persistence.research_evidence import SqlAlchemyResearchEvidenceRepository
from orchestwin.projects.research_evidence import (
    EvidenceChange,
    EvidenceCitation,
    EvidenceEffect,
    ResearchEvidenceError,
)
from orchestwin.projects.twin_learning import UpdateStatus
from orchestwin.twins.epistemics import EvidenceSourceKind
from orchestwin.twins.persistence.repositories import SqlAlchemyUserModelingSnapshotRepository
from orchestwin.twins.user_modeling_gate import (
    user_modeling_gate_is_currently_approved,
)
from orchestwin.twins.user_twins import UserTwinField
from orchestwin.workflow.gates import HumanGateType
from orchestwin.workflow.persistence.repositories import SqlAlchemyHumanGateRepository
from src.test.python.integration.postgres_isolation import assert_reversible_migration
from src.test.python.integration.test_postgresql_twin_import import (
    add_users,
    approving_at,
    members_named,
    seed_project,
)
from src.test.python.integration.test_proposal_evidence_postgres import database, run

__all__ = ["database"]

pytestmark = pytest.mark.integration
MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0068_research_evidence"
)
NOW = datetime.now(UTC)


async def seeded(database):
    db = create_database_runtime(database)
    owner, project = uuid4(), uuid4()
    await add_users(db.session_factory, owner)
    gates = approving_at(db.session_factory, NOW)
    snapshot = await seed_project(
        db,
        gates,
        project_id=project,
        name="Synthetic evidence project",
        members=members_named("Synthetic Operator Twin", "Synthetic Reviewer Twin"),
        owner_id=owner,
    )
    runtime = SimpleNamespace(
        database_runtime=db,
        proposal_evidence_store=object(),
        real_model_runtime=SimpleNamespace(
            user_modeling=SimpleNamespace(proposal_port=SimpleNamespace(generator=object()))
        ),
    )
    return (
        db,
        owner,
        project,
        snapshot,
        ResearchEvidenceApplication(runtime),
        TwinLearningApplication(runtime),
    )


def body(text):
    return EvidenceBody(
        title="Synthetic technical source",
        text=text,
        acknowledged=True,
        context="Technical fixture, not empirical research.",
        limitations="No interviews or participants.",
    )


async def current(db, owner, project):
    async with db.session_factory() as session:
        snapshot = await SqlAlchemyUserModelingSnapshotRepository(
            session, owner_user_id=owner
        ).current(project_id=project)
        gate = await SqlAlchemyHumanGateRepository(session).get_latest_owned_for_update(
            owner_user_id=owner, project_id=project, gate_type=HumanGateType.USER_MODELING
        )
    return snapshot, gate


def answer(twin, *, effect="SUPPORTS", field="role", quote, value=None):
    observation = twin.profile.observation_for(UserTwinField(field))
    supplied = observation.value.to_snapshot() if value is None else value
    return {
        "statement": "Synthetic information for the project owner's review.",
        "basis": "The exact passage is only a technical source.",
        "effect": effect,
        "field": field,
        "quote": quote,
        "line": 1,
        "value": {key: supplied[key] for key in ("kind", "text", "items")},
    }


def test_source_versions_owner_scope_text_deletion_and_reassociation(database):
    async def scenario():
        db, owner, project, _, evidence, _ = await seeded(database)
        try:
            scope = {"owner_user_id": owner, "project_id": project}
            first = (await evidence.insert(**scope, body=body("First\r\npassage")))["evidence"]
            source_id = UUID(first["id"])
            assert first["version"] == 1 and first["character_count"] == len("First\npassage")
            assert "text" not in first
            with pytest.raises(ResearchEvidenceError, match="PROJECT_NOT_FOUND"):
                await evidence.get(owner_user_id=uuid4(), project_id=project, source_id=source_id)
            with pytest.raises(ResearchEvidenceError, match="EVIDENCE_RETIRE_REQUIRED"):
                await evidence.delete_text(
                    **scope, source_id=source_id, body=EvidenceDeleteBody(acknowledged=True)
                )
            second = (
                await evidence.insert(**scope, source_id=source_id, body=body("Revised source"))
            )["evidence"]
            assert (
                second["id"] == first["id"]
                and second["code"] == first["code"]
                and second["version"] == 2
            )
            assert (await evidence.get(**scope, source_id=source_id, version=1, include_text=True))[
                "text"
            ] == "First\npassage"
            assert len((await evidence.list(**scope, all_versions=True))["evidence"]) == 2
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=owner)
                imported = {
                    **first,
                    "id": str(uuid4()),
                    "code": "EVD-002",
                    "text_available": False,
                    "imported_from": {
                        "project_id": str(project),
                        "source_id": first["id"],
                        "source_version": 1,
                        "content_hash": first["content_hash"],
                    },
                }
                await repository.import_dossier(project, {"evidence": [imported], "citations": []})
            imported_id = UUID(imported["id"])
            with pytest.raises(ResearchEvidenceError, match="EVIDENCE_CONTEXT_CHANGED"):
                await evidence.associate_text(
                    **scope,
                    source_id=imported_id,
                    body=EvidenceAssociateBody(version=1, text="Different text", acknowledged=True),
                )
            associated = await evidence.associate_text(
                **scope,
                source_id=imported_id,
                body=EvidenceAssociateBody(version=1, text="First\r\npassage", acknowledged=True),
            )
            assert associated["evidence"]["content_hash"] == first["content_hash"]
            assert associated["evidence"]["imported_from"] == imported["imported_from"]
            await evidence.retire(
                **scope,
                source_id=source_id,
                body=EvidenceRetireBody(reason="Synthetic retirement."),
            )
            deleted = await evidence.delete_text(
                **scope, source_id=source_id, body=EvidenceDeleteBody(acknowledged=True)
            )
            assert not deleted["evidence"]["text_available"]
            with pytest.raises(ResearchEvidenceError, match="EVIDENCE_TEXT_UNAVAILABLE"):
                await evidence.get(**scope, source_id=source_id, version=1, include_text=True)
            with pytest.raises(ResearchEvidenceError, match="EVIDENCE_RETIRED"):
                await evidence.associate_text(
                    **scope,
                    source_id=source_id,
                    body=EvidenceAssociateBody(version=1, text="First\npassage", acknowledged=True),
                )
        finally:
            await db.dispose()

    run(scenario())


def test_support_contradiction_addition_owner_correction_rejection_and_retirement_preserve_identity(
    monkeypatch,
    database,
):
    responses = []

    async def generate(generator, context):
        return EvidenceUpdateOutput(
            comment="Synthetic evidence proposes changes for the owner to review.",
            changes=responses.pop(0),
        )

    monkeypatch.setattr(twin_learning, "propose_evidence_update", generate)

    async def scenario():
        db, owner, project, initial, evidence, learning = await seeded(database)
        try:
            scope = {"owner_user_id": owner, "project_id": project}
            twin = initial.snapshot.twin_versions[0]
            other = initial.snapshot.twin_versions[1]
            role = twin.profile.observation_for(UserTwinField.ROLE).value.text
            text = f"{role}\nAdd a review step.\nSynthetic contradictory observation."
            source = (await evidence.insert(**scope, body=body(text)))["evidence"]
            source_id = UUID(source["id"])
            support = answer(twin, quote=role)
            responses.append(
                [support, {**support, "quote": "This nonexistent passage is rejected."}]
            )
            proposal = (
                await learning.propose(
                    **scope,
                    twin_id=twin.twin_id,
                    body=TwinUpdateRequest(locale="en-US", evidence_id=source_id),
                )
            ).update
            assert proposal.evidence.rejected_changes == 1
            approved, _ = await learning.decide(
                **scope,
                update_id=proposal.id,
                body=TwinUpdateDecisionRequest.model_validate(
                    {"decision": "APPROVE", "kept": [{"index": 0}]}
                ),
            )
            assert approved.status is UpdateStatus.APPROVED
            after, gate = await current(db, owner, project)
            assert user_modeling_gate_is_currently_approved(gate, after)
            updated = next(
                item for item in after.snapshot.twin_versions if item.twin_id == twin.twin_id
            )
            assert (
                updated.version_number == 2
                and updated.profile.persona_reference == twin.profile.persona_reference
            )
            assert (
                next(item for item in after.snapshot.twin_versions if item.twin_id == other.twin_id)
                == other
            )
            assert after.snapshot.persona_versions == initial.snapshot.persona_versions
            assert (await evidence.list(**scope))["citations"][0]["citation"]["quote"] == role
            responses.append(
                [
                    answer(
                        updated, effect="CONTRADICTS", quote="Synthetic contradictory observation."
                    )
                ]
            )
            contested = (
                await learning.propose(
                    **scope,
                    twin_id=twin.twin_id,
                    body=TwinUpdateRequest(locale="en-US", evidence_id=source_id),
                )
            ).update
            await learning.decide(
                **scope,
                update_id=contested.id,
                body=TwinUpdateDecisionRequest.model_validate(
                    {
                        "decision": "APPROVE",
                        "kept": [
                            {
                                "index": 0,
                                "statement": "Corrected interpretation of a synthetic contradiction.",
                            }
                        ],
                    }
                ),
            )
            after, _ = await current(db, owner, project)
            updated = next(
                item for item in after.snapshot.twin_versions if item.twin_id == twin.twin_id
            )
            assert (
                updated.profile.observation_for(UserTwinField.ROLE).epistemic_status.value
                == "CONTESTED"
            )
            old_goals = updated.profile.observation_for(UserTwinField.GOALS).value.items
            responses.append(
                [
                    answer(
                        updated,
                        effect="ADDS",
                        field="goals",
                        quote="Add a review step.",
                        value={"kind": "ITEMS", "text": None, "items": ["Add a review step."]},
                    )
                ]
            )
            addition = (
                await learning.propose(
                    **scope,
                    twin_id=twin.twin_id,
                    body=TwinUpdateRequest(locale="en-US", evidence_id=source_id),
                )
            ).update
            await learning.decide(
                **scope,
                update_id=addition.id,
                body=TwinUpdateDecisionRequest.model_validate(
                    {
                        "decision": "APPROVE",
                        "kept": [{"index": 0, "statement": "Review the result before sharing."}],
                    }
                ),
            )
            after, _ = await current(db, owner, project)
            updated = next(
                item for item in after.snapshot.twin_versions if item.twin_id == twin.twin_id
            )
            assert updated.profile.observation_for(UserTwinField.GOALS).value.items == (
                *old_goals,
                "Review the result before sharing.",
            )
            responses.append([answer(updated, quote=role)])
            discard = (
                await learning.propose(
                    **scope,
                    twin_id=twin.twin_id,
                    body=TwinUpdateRequest(locale="en-US", evidence_id=source_id),
                )
            ).update
            rejected, _ = await learning.decide(
                **scope,
                update_id=discard.id,
                body=TwinUpdateDecisionRequest.model_validate({"decision": "REJECT", "kept": []}),
            )
            assert rejected.status is UpdateStatus.REJECTED
            responses.append([answer(updated, quote=role)])
            pending = (
                await learning.propose(
                    **scope,
                    twin_id=twin.twin_id,
                    body=TwinUpdateRequest(locale="en-US", evidence_id=source_id),
                )
            ).update
            retired = await evidence.retire(
                **scope,
                source_id=source_id,
                body=EvidenceRetireBody(reason="Synthetic source no longer used."),
            )
            assert retired["affected_twins"] == [str(twin.twin_id)]
            assert (
                await learning.update_of(**scope, update_id=pending.id)
            ).status is UpdateStatus.REJECTED
            after, gate = await current(db, owner, project)
            final = next(
                item for item in after.snapshot.twin_versions if item.twin_id == twin.twin_id
            )
            assert user_modeling_gate_is_currently_approved(gate, after)
            assert (
                final.profile.observation_for(UserTwinField.ROLE).epistemic_status.value
                == "UNSUPPORTED_ASSUMPTION"
            )
            assert (
                final.profile.observation_for(UserTwinField.GOALS).epistemic_status.value
                == "UNSUPPORTED_ASSUMPTION"
            )
            assert (
                final.twin_id == twin.twin_id
                and after.snapshot.persona_versions == initial.snapshot.persona_versions
            )
            assert all(
                item["status"] == "RETIRED"
                for item in (await evidence.list(**scope, all_versions=True))["citations"]
            )
        finally:
            await db.dispose()

    run(scenario())


def test_retirement_of_evidence_from_a_draft_does_not_approve_unreviewed_contents(
    monkeypatch, database
):
    responses = []

    async def generate(generator, context):
        return EvidenceUpdateOutput(
            comment="Synthetic evidence proposes one claim for an offline check.",
            changes=responses.pop(0),
        )

    monkeypatch.setattr(twin_learning, "propose_evidence_update", generate)

    async def scenario():
        db, owner, project, initial, evidence, learning = await seeded(database)
        try:
            scope = {"owner_user_id": owner, "project_id": project}
            twin = initial.snapshot.twin_versions[0]
            role = twin.profile.observation_for(UserTwinField.ROLE).value.text
            source_id = UUID((await evidence.insert(**scope, body=body(role)))["evidence"]["id"])
            responses.append([answer(twin, quote=role)])
            proposal = (
                await learning.propose(
                    **scope,
                    twin_id=twin.twin_id,
                    body=TwinUpdateRequest(locale="en-US", evidence_id=source_id),
                )
            ).update
            await learning.decide(
                **scope,
                update_id=proposal.id,
                body=TwinUpdateDecisionRequest.model_validate(
                    {"decision": "APPROVE", "kept": [{"index": 0}]}
                ),
            )
            approved, _ = await current(db, owner, project)
            updated = next(
                item for item in approved.snapshot.twin_versions if item.twin_id == twin.twin_id
            )
            draft_profile = replace(updated.profile, name="Unreviewed synthetic draft")
            async with db.session_factory() as session, session.begin():
                await append_evidence_profiles(
                    session,
                    owner_user_id=owner,
                    current=approved,
                    profiles={twin.twin_id: draft_profile},
                    occurred_at=NOW,
                    approve=False,
                )
            retired = await evidence.retire(
                **scope,
                source_id=source_id,
                body=EvidenceRetireBody(reason="Withdraw technical source."),
            )
            assert retired["review_required"] is True
            after, gate = await current(db, owner, project)
            assert not user_modeling_gate_is_currently_approved(gate, after)
            updated = next(
                item for item in after.snapshot.twin_versions if item.twin_id == twin.twin_id
            )
            assert updated.profile.name == "Unreviewed synthetic draft"
            assert (
                updated.profile.observation_for(UserTwinField.ROLE).epistemic_status.value
                == "UNSUPPORTED_ASSUMPTION"
            )
            assert after.snapshot.persona_versions == initial.snapshot.persona_versions
        finally:
            await db.dispose()

    run(scenario())


def test_research_evidence_migration_downgrade_restores_the_previous_schema_exactly(database):
    assert_reversible_migration(database, MIGRATION)


def test_source_revision_during_generation_refuses_stale_proposal_and_invalidates_pending(
    monkeypatch, database
):
    on_generate = None
    response = None

    async def generate(generator, context):
        if on_generate is not None:
            await on_generate()
        return EvidenceUpdateOutput(
            comment="Synthetic evidence proposes one claim for a concurrency check.",
            changes=[response],
        )

    monkeypatch.setattr(twin_learning, "propose_evidence_update", generate)

    async def scenario():
        nonlocal on_generate, response
        db, owner, project, initial, evidence, learning = await seeded(database)
        try:
            scope = {"owner_user_id": owner, "project_id": project}
            twin = initial.snapshot.twin_versions[0]
            role = twin.profile.observation_for(UserTwinField.ROLE).value.text
            source_id = UUID((await evidence.insert(**scope, body=body(role)))["evidence"]["id"])
            response = answer(twin, quote=role)

            async def revision():
                await evidence.insert(
                    **scope,
                    source_id=source_id,
                    body=body(f"{role}\nNew synthetic source version."),
                )

            on_generate = revision
            with pytest.raises(HTTPException) as stale:
                await learning.propose(
                    **scope,
                    twin_id=twin.twin_id,
                    body=TwinUpdateRequest(locale="en-US", evidence_id=source_id),
                )
            assert (
                stale.value.status_code == 409
                and stale.value.detail["code"] == "EVIDENCE_CONTEXT_CHANGED"
            )
            on_generate = None
            proposal = (
                await learning.propose(
                    **scope,
                    twin_id=twin.twin_id,
                    body=TwinUpdateRequest(locale="en-US", evidence_id=source_id),
                )
            ).update
            await revision()
            assert (
                await learning.update_of(**scope, update_id=proposal.id)
            ).status is UpdateStatus.REJECTED
            state, _ = await current(db, owner, project)
            assert state.id == initial.id and state.content_hash == initial.content_hash
        finally:
            await db.dispose()

    run(scenario())


def test_stale_evidence_update_can_be_discarded_while_current_modeling_is_unapproved(
    monkeypatch, database
):
    response = None

    async def generate(generator, context):
        return EvidenceUpdateOutput(
            comment="Synthetic evidence proposes one claim for a stale draft check.",
            changes=[response],
        )

    monkeypatch.setattr(twin_learning, "propose_evidence_update", generate)

    async def scenario():
        nonlocal response
        db, owner, project, initial, evidence, learning = await seeded(database)
        try:
            scope = {"owner_user_id": owner, "project_id": project}
            twin = initial.snapshot.twin_versions[0]
            role = twin.profile.observation_for(UserTwinField.ROLE).value.text
            source_id = UUID((await evidence.insert(**scope, body=body(role)))["evidence"]["id"])
            response = answer(twin, quote=role)
            proposal = (
                await learning.propose(
                    **scope,
                    twin_id=twin.twin_id,
                    body=TwinUpdateRequest(locale="en-US", evidence_id=source_id),
                )
            ).update
            async with db.session_factory() as session, session.begin():
                await append_evidence_profiles(
                    session,
                    owner_user_id=owner,
                    current=initial,
                    profiles={
                        twin.twin_id: replace(twin.profile, name="Unapproved synthetic draft")
                    },
                    occurred_at=NOW,
                    approve=False,
                )
            discarded, _ = await learning.decide(
                **scope,
                update_id=proposal.id,
                body=TwinUpdateDecisionRequest.model_validate({"decision": "REJECT", "kept": []}),
            )
            assert discarded.status is UpdateStatus.REJECTED
            state, gate = await current(db, owner, project)
            assert not user_modeling_gate_is_currently_approved(gate, state)
        finally:
            await db.dispose()

    run(scenario())


def test_downgrade_refuses_to_discard_new_source_metadata_and_preserves_legacy_snapshot(database):
    async def scenario():
        db, owner, project, initial, evidence, _ = await seeded(database)
        try:
            await evidence.insert(
                owner_user_id=owner,
                project_id=project,
                body=body("Synthetic text retained for downgrade protection."),
            )
            before, _ = await current(db, owner, project)
            assert before.content_hash == initial.content_hash
        finally:
            await db.dispose()
        with pytest.raises(RuntimeError, match="research evidence must be preserved"):
            await asyncio.to_thread(downgrade_database, database, revision=MIGRATION.down_revision)
        db = create_database_runtime(database)
        try:
            after, _ = await current(db, owner, project)
            assert after.content_hash == initial.content_hash
            assert after.to_snapshot() == initial.to_snapshot()
            async with db.session_factory() as session:
                assert (
                    len(
                        await SqlAlchemyResearchEvidenceRepository(
                            session, owner_user_id=owner
                        ).list(project)
                    )
                    == 1
                )
        finally:
            await db.dispose()

    run(scenario())


def test_imported_citation_is_withdrawable_and_associating_text_does_not_promote_a_draft(database):
    async def scenario():
        db, owner, project, initial, evidence, _ = await seeded(database)
        try:
            original_twin = initial.snapshot.twin_versions[0]
            observation = original_twin.profile.observation_for(UserTwinField.ROLE)
            text = observation.value.text
            empirical_body = body(text).model_copy(
                update={
                    "source_kind": EvidenceSourceKind.EMPIRICAL_RESEARCH,
                    "empirical": True,
                    "method": "Synthetic declared method for a technical policy test.",
                }
            )
            original_source = (
                await evidence.insert(owner_user_id=owner, project_id=project, body=empirical_body)
            )["evidence"]
            target = uuid4()
            gates = approving_at(db.session_factory, NOW)
            target_initial = await seed_project(
                db,
                gates,
                project_id=target,
                name="Imported synthetic evidence project",
                members=members_named("Imported Operator Twin", "Imported Reviewer Twin"),
                owner_id=owner,
            )
            twin = target_initial.snapshot.twin_versions[0]
            source_id = uuid4()
            metadata = {
                **original_source,
                "id": str(source_id),
                "text_available": False,
                "imported_from": {
                    "project_id": str(project),
                    "source_id": original_source["id"],
                    "source_version": 1,
                    "content_hash": original_source["content_hash"],
                },
            }
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=owner)
                await repository.import_dossier(target, {"evidence": [metadata], "citations": []})
                imported = await repository.get(target, source_id)
                citation = EvidenceCitation(
                    source_id, 1, imported.content_hash, text, 0, len(text), 1, 1
                )
                proposal = EvidenceChange(
                    EvidenceEffect.ADDS, UserTwinField.ROLE, observation.value, citation
                )
                imported_claim = apply_evidence_change(
                    twin.profile.observation_for(UserTwinField.ROLE),
                    proposal,
                    imported,
                    rationale="Historical approved citation imported as provenance.",
                )
                profile = replace(
                    twin.profile,
                    observations=tuple(
                        imported_claim
                        if item.observation_key == UserTwinField.ROLE.observation_key
                        else item
                        for item in twin.profile.observations
                    ),
                )
                draft = await append_evidence_profiles(
                    session,
                    owner_user_id=owner,
                    current=target_initial,
                    profiles={twin.twin_id: profile},
                    occurred_at=NOW,
                    approve=False,
                )
                payload = {
                    "evidence": [],
                    "citations": [
                        {
                            "twin_id": str(twin.twin_id),
                            "twin_version": 7,
                            "field": "role",
                            "effect": "SUPPORTS",
                            "citation": citation.to_snapshot(),
                            "status": "ACTIVE",
                        }
                    ],
                }
                await repository.import_dossier(target, payload, draft)
            scope = {"owner_user_id": owner, "project_id": target}
            before, gate = await current(db, owner, target)
            assert not user_modeling_gate_is_currently_approved(gate, before)
            assert (await evidence.get(**scope, source_id=source_id))["imported_from"] == metadata[
                "imported_from"
            ]
            await evidence.associate_text(
                **scope,
                source_id=source_id,
                body=EvidenceAssociateBody(version=1, text=text, acknowledged=True),
            )
            associated, gate = await current(db, owner, target)
            assert associated.id == before.id and associated.content_hash == before.content_hash
            assert not user_modeling_gate_is_currently_approved(gate, associated)
            retired = await evidence.retire(
                **scope,
                source_id=source_id,
                body=EvidenceRetireBody(reason="Withdraw imported synthetic source."),
            )
            assert retired["review_required"] is True
            after, gate = await current(db, owner, target)
            imported_twin = next(
                item for item in after.snapshot.twin_versions if item.twin_id == twin.twin_id
            )
            assert (
                imported_twin.profile.observation_for(UserTwinField.ROLE).epistemic_status.value
                == "UNSUPPORTED_ASSUMPTION"
            )
            assert not user_modeling_gate_is_currently_approved(gate, after)
            assert imported_twin.twin_id == twin.twin_id
        finally:
            await db.dispose()

    run(scenario())
