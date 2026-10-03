from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

from orchestwin.projects import sections_service as reads
from orchestwin.projects.progress import ArtifactVersion, GateState, ProjectStage
from orchestwin.projects.sections import (
    SectionBlock,
    SectionReason,
    SectionState,
    project_sections,
)
from orchestwin.workflow.gates import HumanGateStatus
from src.test.python.artifacts.test_provided_prototypes36 import prototype
from src.test.python.projects.test_sections import (
    TWINS_2,
    aligned,
    artifact,
    brief,
    design,
    requirements,
    team,
    user_twins,
)

PROTOTYPE_ID = UUID("c0417408-a40e-4b11-a816-229b50c80788")
OWNER_ID = UUID("bc96b7e4-a973-4f38-a157-b20f17e64268")
PROJECT_ID = UUID("838e3a26-0a99-43d3-8488-192b02922139")


def supplied(**changes):
    return replace(
        design(provided=True, has_mockup=True),
        version=replace(artifact("design"), artifact_id=PROTOTYPE_ID),
        **changes,
    )


def facts(**changes):
    return aligned(design=supplied(), design_approved_once=False, **changes)


def install_prototype_reads(monkeypatch):
    current = prototype()
    base = aligned()
    specification = SimpleNamespace(
        agent_team_reference=base.team.version,
        user_modeling_reference=base.user_twins.version,
        user_twin_references=[
            SimpleNamespace(
                twin_id=item.artifact_id,
                version_number=item.version_number,
                content_hash=item.content_hash,
            )
            for item in base.user_twins.twins
        ],
        requirements=[SimpleNamespace(code=code) for code in ("REQ-001", "REQ-002", "REQ-003")],
    )
    for name, result in (
        ("SqlAlchemyDesignPackageRepository", None),
        ("SqlAlchemyWorkflowInputsRepository", current),
        (
            "SqlAlchemyRequirementsSpecificationRepository",
            SimpleNamespace(specification=specification),
        ),
    ):
        monkeypatch.setattr(
            reads,
            name,
            lambda *args, result=result, **kwargs: SimpleNamespace(
                current=AsyncMock(return_value=result)
            ),
        )
    identity = ArtifactVersion(current.id, current.version_number, current.content_hash)
    return current, identity


def test_exact_approved_prototype_gate_produces_approved_design_facts(monkeypatch):
    current, identity = install_prototype_reads(monkeypatch)

    result = asyncio.run(
        reads.SqlAlchemySectionReads._design(
            None,
            GateState(HumanGateStatus.APPROVED, identity),
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
        )
    )

    assert result.version == identity
    assert result.approved is True
    assert result.provided is True
    assert result.has_mockup is True
    assert result.reviewed is False
    assert result.requirements == ArtifactVersion(
        UUID(current.definition_reference["artifact_id"]),
        current.definition_reference["version_number"],
        current.definition_reference["content_hash"],
    )
    assert result.uncovered_codes == ("REQ-003",)


def test_other_identity_or_gate_status_cannot_approve_the_supplied_design(monkeypatch):
    _, identity = install_prototype_reads(monkeypatch)
    gates = (
        None,
        GateState(HumanGateStatus.PENDING_APPROVAL, identity),
        GateState(HumanGateStatus.REJECTED, identity),
        GateState(HumanGateStatus.APPROVED, replace(identity, artifact_id=PROTOTYPE_ID)),
        GateState(HumanGateStatus.APPROVED, replace(identity, version_number=2)),
        GateState(HumanGateStatus.APPROVED, replace(identity, content_hash="f" * 64)),
    )

    for gate in gates:
        result = asyncio.run(
            reads.SqlAlchemySectionReads._design(
                None, gate, owner_user_id=OWNER_ID, project_id=PROJECT_ID
            )
        )
        state = project_sections(aligned(design=result, design_approved_once=False))
        assert result.approved is False
        assert state.section(ProjectStage.DESIGN).state is SectionState.IN_PROGRESS
        assert state.first_pass_complete is False
        assert state.section(ProjectStage.PACKAGE).blocked is SectionBlock.UPSTREAM_NOT_READY


def test_changed_definition_requires_a_new_supplied_design():
    state = project_sections(facts(requirements=requirements(2)))
    section = state.section(ProjectStage.DESIGN)

    assert section.state is SectionState.TO_UPDATE
    assert section.reasons == (SectionReason.REQUIREMENTS_CHANGED,)
    assert section.blocked is None
    assert state.first_pass_complete is True
    assert state.alignment.available is False
    assert state.alignment.sections == (ProjectStage.DESIGN,)


def test_changed_upstream_context_is_not_hidden_by_a_supplied_design():
    cases = (
        (facts(brief=brief(2)), SectionBlock.UPSTREAM_NOT_READY),
        (facts(team=team(2)), None),
        (facts(user_twins=user_twins(2, twins=TWINS_2)), None),
    )

    for value, blocked in cases:
        state = project_sections(value)
        section = state.section(ProjectStage.DESIGN)
        assert section.state is SectionState.TO_UPDATE
        assert SectionReason.REQUIREMENTS_CHANGED in section.reasons
        assert section.blocked is blocked
        assert state.alignment.available is False
        assert state.section(ProjectStage.PACKAGE).state is SectionState.TO_UPDATE


def test_alignment_offer_is_removed_only_for_the_supplied_design():
    provided = facts(requirements=requirements(2))
    generated = replace(provided, design=replace(provided.design, provided=False))

    assert project_sections(generated).alignment.available is True
    assert project_sections(provided).alignment.to_snapshot() == {
        "available": False,
        "sections": ["DESIGN"],
        "uncovered_codes": [],
    }


def test_sections_read_does_not_query_generated_alignment_for_a_supplied_design():
    value = replace(facts(), design=supplied(uncovered_codes=("REQ-004",)))
    reader = SimpleNamespace(facts=AsyncMock(return_value=value))
    alignment = SimpleNamespace(status=AsyncMock(side_effect=AssertionError("generated alignment")))
    learning = SimpleNamespace(learned=AsyncMock(return_value=False))
    step = Mock()
    service = reads.SectionsService(
        reads=reader,
        user_twins=step,
        requirements=step,
        design=step,
        design_alignment=alignment,
        twin_learning=learning,
    )

    result = asyncio.run(service.current(owner_user_id=OWNER_ID, project_id=PROJECT_ID))

    alignment.status.assert_not_awaited()
    assert result.section(ProjectStage.DESIGN).codes == ("REQ-004",)
    assert result.section(ProjectStage.DESIGN).state is SectionState.UPDATE_AVAILABLE
    assert step.mock_calls == []


def test_missing_evaluation_and_missing_anchors_stay_visible_after_approval():
    value = replace(facts(), design=supplied(uncovered_codes=("REQ-004", "REQ-007")))
    result = project_sections(value)

    assert result.first_pass_complete is True
    assert result.section(ProjectStage.DESIGN).to_snapshot() == {
        "key": "DESIGN",
        "state": "UPDATE_AVAILABLE",
        "version_number": 1,
        "reasons": ["REQUIREMENTS_NOT_COVERED", "EVALUATION_MISSING"],
        "blocked": None,
        "codes": ["REQ-004", "REQ-007"],
    }
    assert result.alignment.available is False
    covered = project_sections(facts()).section(ProjectStage.DESIGN)
    assert covered.state is SectionState.UPDATE_AVAILABLE
    assert covered.reasons == (SectionReason.EVALUATION_MISSING,)
    assert covered.codes == ()


def test_legacy_dossier_cannot_claim_to_contain_the_approved_supplied_design():
    value = facts()
    result = project_sections(value)

    assert value.folder.stages[ProjectStage.DESIGN] != value.design.version
    assert result.section(ProjectStage.PACKAGE).to_snapshot() == {
        "key": "PACKAGE",
        "state": "TO_UPDATE",
        "version_number": 5,
        "reasons": ["FOLDER_BEHIND"],
        "blocked": None,
        "codes": [],
    }
    current = replace(
        value,
        folder=replace(
            value.folder,
            stages=value.folder.stages | {ProjectStage.DESIGN: value.design.version},
        ),
    )
    assert project_sections(current).section(ProjectStage.PACKAGE).state is SectionState.FINE


def test_historical_approval_does_not_approve_a_new_supplied_draft_or_its_dossier():
    value = replace(facts(), design=supplied(approved=False), design_approved_once=True)
    result = project_sections(value)

    assert result.first_pass_complete is True
    assert result.section(ProjectStage.DESIGN).state is SectionState.IN_PROGRESS
    assert result.section(ProjectStage.PACKAGE).state is SectionState.TO_UPDATE
    assert result.section(ProjectStage.PACKAGE).blocked is SectionBlock.UPSTREAM_NOT_READY
    assert (
        project_sections(replace(value, folder=None)).section(ProjectStage.PACKAGE).state
        is SectionState.NOT_STARTED
    )


def test_removed_anchor_is_reported_and_never_offered_as_an_alignment():
    value = replace(
        facts(requirements=requirements(2)),
        design=supplied(missing_codes=("REQ-002",), uncovered_codes=("REQ-004",)),
    )
    result = project_sections(value)
    section = result.section(ProjectStage.DESIGN)

    assert section.state is SectionState.TO_UPDATE
    assert section.blocked is SectionBlock.REQUIREMENT_NO_LONGER_AVAILABLE
    assert section.codes == ("REQ-002",)
    assert result.alignment.available is False
    assert result.alignment.uncovered_codes == ()
    assert result.section(ProjectStage.PACKAGE).blocked is SectionBlock.UPSTREAM_NOT_READY
