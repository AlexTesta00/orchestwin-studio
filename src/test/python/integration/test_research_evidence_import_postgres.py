from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from orchestwin.api.research_evidence import (
    EvidenceAssociateBody,
    EvidenceRetireBody,
    ResearchEvidenceApplication,
)
from orchestwin.artifacts.design_gate import design_artifact_reference
from orchestwin.artifacts.design_realignment import realigned_design_version
from orchestwin.knowledge.folder import build_knowledge_folder, folder_archive
from orchestwin.knowledge.project_import_service import ProjectImportService
from orchestwin.persistence import create_database_runtime
from orchestwin.projects.evidence_application import apply_evidence_change, evidence_profile
from orchestwin.projects.persistence.research_evidence import (
    SqlAlchemyResearchEvidenceRepository,
    evidence_version_from_row,
)
from orchestwin.projects.requirements_gate import requirements_artifact_reference
from orchestwin.projects.requirements_realignment import realigned_requirements_version
from orchestwin.projects.research_evidence import EvidenceChange, EvidenceCitation, EvidenceEffect
from orchestwin.twins.epistemics import EvidenceSourceKind
from orchestwin.twins.persistence.repositories import SqlAlchemyUserModelingSnapshotRepository
from orchestwin.twins.user_modeling_gate import (
    user_modeling_artifact_reference,
    user_modeling_gate_is_currently_approved,
)
from orchestwin.twins.user_twins import UserTwinField, UserTwinLifecycleStatus
from orchestwin.workflow.gates import HumanGateType
from orchestwin.workflow.persistence.repositories import SqlAlchemyHumanGateRepository
from src.test.python.integration.test_postgresql_project_import import seed_users
from src.test.python.integration.test_postgresql_twin_import import approve
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.knowledge.knowledge_fixtures import PUBLISHED_AT, approved_gate, real_sources
from src.test.python.knowledge.test_research_evidence import evidence_document

__all__ = ["database"]
pytestmark = pytest.mark.integration


def synthetic_evidence_archive():
    sources = real_sources()
    document = evidence_document(sources)
    source = document["evidence"][0]
    evidence = evidence_version_from_row(
        {
            "id": UUID(source["id"]),
            "code": source["code"],
            "version": source["version"],
            "metadata": source,
            "byte_count": source["byte_count"],
            "retired_at": None,
            "retired_reason": None,
            "text_present": source["id"],
        }
    )
    original = (
        "Unexported synthetic preface.\n"
        + document["citations"][0]["citation"]["quote"]
        + "\nUnexported synthetic ending."
    )
    previous = sources.modeling.snapshot.twin_versions[0]
    observation = previous.profile.observation_for(UserTwinField.GOALS)
    change = EvidenceChange(
        effect=EvidenceEffect.SUPPORTS,
        field=UserTwinField.GOALS,
        value=observation.value,
        citation=EvidenceCitation.from_snapshot(document["citations"][0]["citation"]),
    )
    supported = apply_evidence_change(
        observation,
        change,
        evidence,
        rationale="Synthetic nonempirical support for an import fixture.",
    )
    profile = evidence_profile(previous.profile, (supported,))
    twin = replace(
        previous,
        id=uuid4(),
        version_number=previous.version_number + 1,
        based_on_version_number=previous.version_number,
        profile=profile,
        content_hash=profile.content_hash,
    )
    snapshot = replace(
        sources.modeling.snapshot,
        twin_versions=(twin, *sources.modeling.snapshot.twin_versions[1:]),
    )
    modeling = replace(
        sources.modeling,
        id=uuid4(),
        version_number=sources.modeling.version_number + 1,
        based_on_version_number=sources.modeling.version_number,
        snapshot=snapshot,
        content_hash=snapshot.content_hash,
    )
    requirements = realigned_requirements_version(
        sources.requirements,
        modeling,
        version_id=uuid4(),
        created_by_user_id=modeling.created_by_user_id,
        created_at=PUBLISHED_AT,
    )
    design = realigned_design_version(
        sources.design,
        requirements,
        version_id=uuid4(),
        created_by_user_id=modeling.created_by_user_id,
        created_at=PUBLISHED_AT,
    )
    document["citations"][0]["twin_version"] = twin.version_number
    document["citations"].append({**document["citations"][0], "twin_id": str(uuid4())})
    sources = replace(
        sources,
        modeling=modeling,
        modeling_gate=approved_gate(
            modeling, HumanGateType.USER_MODELING, user_modeling_artifact_reference(modeling), 9960
        ),
        requirements=requirements,
        requirements_gate=approved_gate(
            requirements,
            HumanGateType.REQUIREMENTS,
            requirements_artifact_reference(requirements),
            9961,
        ),
        design=design,
        design_gate=approved_gate(
            design, HumanGateType.DESIGN, design_artifact_reference(design), 9962
        ),
        research_evidence=document,
    )
    folder = build_knowledge_folder(sources, version_number=3, created_at=PUBLISHED_AT)
    return folder_archive(folder).content, original, document


def test_real_project_import_preserves_exact_quotes_then_reassociation_and_retirement(database):
    async def scenario():
        db = create_database_runtime(database)
        owner = uuid4()
        try:
            await seed_users(db, owner)
            content, original, source_document = synthetic_evidence_archive()
            imported = await ProjectImportService(
                session_factory=db.session_factory, clock=lambda: datetime.now(UTC)
            ).import_archive(owner_user_id=owner, content=content)
            project_id = imported.project.id
            scope = {"owner_user_id": owner, "project_id": project_id}
            async with db.session_factory() as session:
                repository = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=owner)
                dossier = await repository.dossier(project_id)
                sources = await repository.list(project_id, all_versions=True)
                initial = await SqlAlchemyUserModelingSnapshotRepository(
                    session, owner_user_id=owner
                ).current(project_id=project_id)
                gates_before = (
                    await session.execute(
                        sa.text("SELECT count(*) FROM human_gates WHERE project_id = :project"),
                        {"project": project_id},
                    )
                ).scalar_one()
                assert await repository.text(project_id, sources[0].id, sources[0].version) is None
            source = sources[0]
            active = next(item for item in dossier["citations"] if item["status"] == "ACTIVE")
            historical = next(item for item in dossier["citations"] if item["status"] == "RETIRED")
            old = source_document["citations"][0]
            twin = next(
                item
                for item in initial.snapshot.twin_versions
                if str(item.twin_id) == active["twin_id"]
            )
            assert source.id != UUID(source_document["evidence"][0]["id"])
            assert source.version == 2 and not source.text_available
            assert source.imported_from["source_id"] == source_document["evidence"][0]["id"]
            assert active["twin_id"] != old["twin_id"]
            assert active["twin_version"] == old["twin_version"]
            assert active["citation"] == {**old["citation"], "source_id": str(source.id)}
            assert active["imported_from"] == {
                "project_id": source_document["project_id"],
                "twin_id": old["twin_id"],
                "twin_version": old["twin_version"],
                "status": "ACTIVE",
                "mapped_twin_version": 1,
            }
            assert (
                historical["citation"]["quote"]
                == source_document["citations"][1]["citation"]["quote"]
            )
            assert (
                historical["imported_from"]["twin_id"] == source_document["citations"][1]["twin_id"]
            )
            references = twin.profile.observation_for(UserTwinField.GOALS).provenance.references
            matching = [item for item in references if item.source_id == str(source.id)]
            assert len(matching) == 1
            assert (
                matching[0].source_version == 2 and matching[0].content_hash == source.content_hash
            )
            assert matching[0].source_kind is EvidenceSourceKind.OWNER_INPUT
            assert twin.profile.validation_status is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT
            assert gates_before == 0
            application = ResearchEvidenceApplication(SimpleNamespace(database_runtime=db))
            associated = await application.associate_text(
                **scope,
                source_id=source.id,
                body=EvidenceAssociateBody(
                    version=2, text=original.replace("\n", "\r\n"), acknowledged=True
                ),
            )
            assert associated["status"] == "EVIDENCE_TEXT_REASSOCIATED"
            async with db.session_factory() as session:
                after_attach = await SqlAlchemyUserModelingSnapshotRepository(
                    session, owner_user_id=owner
                ).current(project_id=project_id)
                assert after_attach == initial
                assert (
                    await SqlAlchemyHumanGateRepository(session).get_latest_owned_for_update(
                        **scope, gate_type=HumanGateType.USER_MODELING
                    )
                    is None
                )
            await approve(
                db,
                project_id=project_id,
                gate_type=HumanGateType.USER_MODELING,
                version=initial,
                owner_id=owner,
            )
            retired = await application.retire(
                **scope,
                source_id=source.id,
                body=EvidenceRetireBody(reason="Synthetic test source withdrawn."),
            )
            assert retired["affected_twins"] == [str(twin.twin_id)]
            assert not retired.get("review_required", False)
            async with db.session_factory() as session:
                final = await SqlAlchemyUserModelingSnapshotRepository(
                    session, owner_user_id=owner
                ).current(project_id=project_id)
                gate = await SqlAlchemyHumanGateRepository(session).get_latest_owned_for_update(
                    **scope, gate_type=HumanGateType.USER_MODELING
                )
                final_document = await SqlAlchemyResearchEvidenceRepository(
                    session, owner_user_id=owner
                ).dossier(project_id)
            updated = next(
                item for item in final.snapshot.twin_versions if item.twin_id == twin.twin_id
            )
            observation = updated.profile.observation_for(UserTwinField.GOALS)
            assert observation.epistemic_status.value == "UNSUPPORTED_ASSUMPTION"
            assert all(
                item.source_id != str(source.id) for item in observation.provenance.references
            )
            assert updated.profile.persona_reference == twin.profile.persona_reference
            assert final.snapshot.persona_versions == initial.snapshot.persona_versions
            assert user_modeling_gate_is_currently_approved(gate, final)
            assert all(item["status"] == "RETIRED" for item in final_document["citations"])
            assert [item["citation"]["quote"] for item in final_document["citations"]] == [
                item["citation"]["quote"] for item in dossier["citations"]
            ]
        finally:
            await db.dispose()

    run(scenario())
