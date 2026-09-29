from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest

from orchestwin.knowledge.export import KnowledgeExportError, KnowledgeSourceLoader
from orchestwin.knowledge.layout import STAGES
from orchestwin.knowledge.sources import (
    KnowledgeFeedback,
    KnowledgeSources,
    consistency_issue,
)
from orchestwin.knowledge.stage_documents import stage_versions
from orchestwin.knowledge.state import ProjectStateSources
from orchestwin.workflow.gates import HumanGateStatus
from src.test.python.artifacts.design_fixtures import OWNER_ID

from .knowledge_fixtures import (
    REAL_PROJECT_ID,
    feedback,
    real_documents,
    real_sources,
    sources_of,
    state_sources,
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
    values: dict[str, object] = {
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


def stage_services(service: KnowledgeSourceLoader) -> dict[str, tuple[FakeQuery, FakeQuery]]:
    return {
        "team": (service.team_proposal_service, service.agent_team_service),
        "twins": (service.user_modeling_services.queries, service.user_modeling_services.gates),
        "requirements": (service.requirements_query_service, service.requirements_gate_service),
        "design": (service.design_query_service, service.design_gate_service),
    }


def test_missing_project_is_reported_before_anything_else() -> None:
    service = loader(sources(), project_service=FakeQuery(None, "current_brief"))

    with pytest.raises(KnowledgeExportError) as error:
        load(service)

    assert error.value.code == "PROJECT_NOT_FOUND"
    assert service.brief_gate_service.calls == []


def test_a_brief_that_is_not_approved_is_the_only_missing_approval_reported() -> None:
    service = loader(sources(), brief_gate_service=FakeQuery(None, "current_gate"))

    with pytest.raises(KnowledgeExportError) as error:
        load(service)

    assert error.value.code == "BRIEF_APPROVAL_REQUIRED"
    assert all(query.calls == [] for pair in stage_services(service).values() for query in pair)
    assert service.feedback_query_service.calls == []


@pytest.mark.parametrize(
    ("service_name", "method", "present"),
    [
        ("team_proposal_service", "current", ("brief",)),
        ("agent_team_service", "current_gate", ("brief",)),
        ("requirements_query_service", "current", ("brief", "team", "twins")),
        ("requirements_gate_service", "current_gate", ("brief", "team", "twins")),
        ("design_query_service", "current", ("brief", "team", "twins", "requirements")),
        ("design_gate_service", "current_gate", ("brief", "team", "twins", "requirements")),
    ],
)
def test_loader_includes_the_stages_up_to_the_first_one_not_approved_and_stops_there(
    service_name: str, method: str, present: tuple[str, ...]
) -> None:
    service = loader(sources(), **{service_name: FakeQuery(None, method)})

    loaded = load(service)

    missing = STAGES[len(present)]
    services = stage_services(service)
    assert loaded.present_stages == present
    assert loaded.pending_stage == missing
    assert loaded.complete is False
    assert all(len(query.calls) == 1 for query in services[missing])
    later = STAGES[len(present) + 1 :]
    assert all(query.calls == [] for stage in later for query in services[stage])
    assert service.feedback_query_service.calls == []
    with pytest.raises(KeyError):
        loaded.version(missing)


@pytest.mark.parametrize("part", ["queries", "gates"])
def test_twins_that_are_not_approved_end_the_folder_after_the_team(part: str) -> None:
    package = sources()
    modeling = {
        "queries": FakeQuery(package.modeling, "current_snapshot"),
        "gates": FakeQuery(package.modeling_gate, "current_gate"),
    }
    modeling[part] = FakeQuery(None, "current_snapshot" if part == "queries" else "current_gate")
    service = loader(package, user_modeling_services=SimpleNamespace(**modeling))

    loaded = load(service)

    assert loaded.present_stages == ("brief", "team")
    assert loaded.modeling is None and loaded.modeling_gate is None
    assert service.requirements_query_service.calls == []
    assert service.design_gate_service.calls == []


def test_gate_that_approves_another_version_does_not_count() -> None:
    package = sources()
    stale = replace(
        package.design_gate,
        artifact=replace(package.design_gate.artifact, content_hash="f" * 64),
    )
    pending = replace(package.requirements_gate, status=HumanGateStatus.PENDING_APPROVAL)

    without_design = load(loader(package, design_gate_service=FakeQuery(stale, "current_gate")))
    without_requirements = load(
        loader(package, requirements_gate_service=FakeQuery(pending, "current_gate"))
    )

    assert without_design.present_stages == ("brief", "team", "twins", "requirements")
    assert without_design.design is None
    assert without_requirements.present_stages == ("brief", "team", "twins")
    assert without_requirements.requirements is None


def test_a_stage_approved_after_a_missing_one_is_never_included() -> None:
    package = sources()
    service = loader(package, agent_team_service=FakeQuery(None, "current_gate"))

    loaded = load(service)

    assert loaded.present_stages == ("brief",)
    assert loaded.requirements is None and loaded.design is None
    assert service.design_query_service.calls == []


def test_loader_reads_the_development_state_of_the_owner() -> None:
    state = state_sources()
    service = loader(sources(), state_query_service=FakeQuery(state, "current"))

    loaded = load(service)

    assert loaded.state is state
    assert service.state_query_service.calls == [
        {"project_id": PROJECT_ID, "owner_user_id": OWNER_ID}
    ]


def test_loader_reads_the_development_state_even_before_the_team_is_approved() -> None:
    state = state_sources()
    service = loader(
        sources(),
        team_proposal_service=FakeQuery(None, "current"),
        state_query_service=FakeQuery(state, "current"),
    )

    loaded = load(service)

    assert loaded.present_stages == ("brief",)
    assert loaded.state is state
    assert len(service.state_query_service.calls) == 1


def test_loader_without_state_service_exports_no_change() -> None:
    loaded = load(loader(sources()))

    assert loaded.state == ProjectStateSources()
    assert loaded.state.is_empty


def test_a_later_stage_of_an_older_version_is_not_checked_while_it_is_not_approved() -> None:
    versions = stage_versions(real_documents())
    versions["requirements"] = replace(versions["requirements"], id=UUID(int=77))
    package = sources_of(versions, project_id=REAL_PROJECT_ID)
    stale = replace(
        package.design_gate,
        artifact=replace(package.design_gate.artifact, content_hash="f" * 64),
    )

    loaded = load(loader(package, design_gate_service=FakeQuery(stale, "current_gate")))

    assert consistency_issue(package) == "DESIGN_OUTDATED"
    assert loaded.present_stages == ("brief", "team", "twins", "requirements")
    assert consistency_issue(loaded) is None


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
