from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest

from orchestwin.knowledge.export import KnowledgeExportError, KnowledgeSourceLoader
from orchestwin.knowledge.sources import (
    KnowledgeFeedback,
    KnowledgeSources,
    consistency_issue,
)
from orchestwin.knowledge.stage_documents import stage_versions
from orchestwin.workflow.gates import HumanGateStatus
from src.test.python.artifacts.design_fixtures import OWNER_ID

from .knowledge_fixtures import (
    REAL_PROJECT_ID,
    feedback,
    real_documents,
    real_sources,
    sources_of,
)

PROJECT_ID = REAL_PROJECT_ID


def sources() -> KnowledgeSources:
    return real_sources(feedback=feedback())


class FakeQuery:
    def __init__(self, value, method: str) -> None:
        self.value = value
        self.calls: list[dict[str, UUID]] = []
        setattr(self, method, self._answer)

    async def _answer(self, **scope: UUID):
        self.calls.append(scope)
        return self.value


def loader(package: KnowledgeSources, *, with_feedback: bool = True, **overrides):
    values = {
        "project_service": FakeQuery(package.brief, "current_brief"),
        "brief_gate_service": FakeQuery(package.brief_gate, "current_gate"),
        "team_proposal_service": FakeQuery(package.team, "current"),
        "agent_team_service": FakeQuery(package.team_gate, "current_gate"),
        "user_modeling_services": SimpleNamespace(
            queries=FakeQuery(package.modeling, "current_snapshot"),
            gates=FakeQuery(package.modeling_gate, "current_gate"),
        ),
        "requirements_query_service": FakeQuery(package.requirements, "current"),
        "requirements_gate_service": FakeQuery(package.requirements_gate, "current_gate"),
        "design_query_service": FakeQuery(package.design, "current"),
        "design_gate_service": FakeQuery(package.design_gate, "current_gate"),
        "feedback_query_service": (
            FakeQuery(package.feedback, "current") if with_feedback else None
        ),
    }
    values.update(overrides)
    return KnowledgeSourceLoader(**values)


def load(service: KnowledgeSourceLoader) -> KnowledgeSources:
    return asyncio.run(service.load(owner_user_id=OWNER_ID, project_id=PROJECT_ID))


def test_loader_collects_the_approved_stages_and_the_feedback_of_the_owner() -> None:
    package = sources()
    service = loader(package)

    loaded = load(service)

    scope = {"project_id": PROJECT_ID, "owner_user_id": OWNER_ID}
    assert loaded.project_id == PROJECT_ID
    assert loaded.brief is package.brief
    assert loaded.team is package.team
    assert loaded.modeling is package.modeling
    assert loaded.requirements is package.requirements
    assert loaded.design is package.design
    assert loaded.design_gate is package.design_gate
    assert loaded.feedback is package.feedback
    assert service.project_service.calls == [scope]
    assert service.design_gate_service.calls == [scope]
    assert service.feedback_query_service.calls == [scope]


def test_project_name_is_the_name_written_in_the_brief() -> None:
    package = sources()

    loaded = load(loader(package))

    assert loaded.project_name == package.brief.brief.to_snapshot()["fields"]["name"]


def test_loader_without_feedback_service_exports_an_empty_history() -> None:
    loaded = load(loader(sources(), with_feedback=False))

    assert loaded.feedback == KnowledgeFeedback()


def test_missing_project_is_reported_before_anything_else() -> None:
    service = loader(sources(), project_service=FakeQuery(None, "current_brief"))

    with pytest.raises(KnowledgeExportError) as error:
        load(service)

    assert error.value.code == "PROJECT_NOT_FOUND"
    assert service.brief_gate_service.calls == []


@pytest.mark.parametrize(
    ("service_name", "method", "code"),
    [
        ("brief_gate_service", "current_gate", "BRIEF_APPROVAL_REQUIRED"),
        ("team_proposal_service", "current", "TEAM_APPROVAL_REQUIRED"),
        ("agent_team_service", "current_gate", "TEAM_APPROVAL_REQUIRED"),
        ("requirements_query_service", "current", "REQUIREMENTS_APPROVAL_REQUIRED"),
        ("requirements_gate_service", "current_gate", "REQUIREMENTS_APPROVAL_REQUIRED"),
        ("design_query_service", "current", "DESIGN_APPROVAL_REQUIRED"),
        ("design_gate_service", "current_gate", "DESIGN_APPROVAL_REQUIRED"),
    ],
)
def test_first_missing_approval_is_reported(service_name: str, method: str, code: str) -> None:
    service = loader(sources(), **{service_name: FakeQuery(None, method)})

    with pytest.raises(KnowledgeExportError) as error:
        load(service)

    assert error.value.code == code
    assert service.feedback_query_service.calls == []


@pytest.mark.parametrize("part", ["queries", "gates"])
def test_missing_twin_approval_is_reported(part: str) -> None:
    package = sources()
    modeling = {
        "queries": FakeQuery(package.modeling, "current_snapshot"),
        "gates": FakeQuery(package.modeling_gate, "current_gate"),
    }
    modeling[part] = FakeQuery(None, "current_snapshot" if part == "queries" else "current_gate")

    with pytest.raises(KnowledgeExportError) as error:
        load(loader(package, user_modeling_services=SimpleNamespace(**modeling)))

    assert error.value.code == "USER_MODELING_APPROVAL_REQUIRED"


def test_gate_that_approves_another_version_does_not_count() -> None:
    package = sources()
    stale = replace(
        package.design_gate,
        artifact=replace(package.design_gate.artifact, content_hash="f" * 64),
    )
    pending = replace(package.requirements_gate, status=HumanGateStatus.PENDING_APPROVAL)

    with pytest.raises(KnowledgeExportError) as design_error:
        load(loader(package, design_gate_service=FakeQuery(stale, "current_gate")))
    with pytest.raises(KnowledgeExportError) as requirements_error:
        load(loader(package, requirements_gate_service=FakeQuery(pending, "current_gate")))

    assert design_error.value.code == "DESIGN_APPROVAL_REQUIRED"
    assert requirements_error.value.code == "REQUIREMENTS_APPROVAL_REQUIRED"


def test_feedback_fixture_is_not_empty() -> None:
    assert not feedback().is_empty


def test_stages_of_the_real_project_are_consistent_with_each_other() -> None:
    assert consistency_issue(real_sources()) is None


@pytest.mark.parametrize(
    ("stage", "issue"),
    [
        ("brief", "TEAM_OUTDATED"),
        ("team", "USER_TWINS_OUTDATED"),
        ("twins", "REQUIREMENTS_OUTDATED"),
        ("requirements", "DESIGN_OUTDATED"),
    ],
)
def test_stage_written_for_an_older_version_of_the_previous_one_is_outdated(
    stage: str, issue: str
) -> None:
    versions = stage_versions(real_documents())
    versions[stage] = replace(versions[stage], id=UUID(int=77))
    package = sources_of(versions, project_id=REAL_PROJECT_ID)

    assert consistency_issue(package) == issue
    with pytest.raises(KnowledgeExportError) as error:
        load(loader(package))
    assert error.value.code == issue


def test_stage_of_another_project_is_a_mismatch() -> None:
    package = replace(real_sources(), project_id=UUID(int=78))

    assert consistency_issue(package) == "PROJECT_MISMATCH"
