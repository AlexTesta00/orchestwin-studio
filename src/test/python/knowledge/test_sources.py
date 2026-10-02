from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.knowledge.layout import STAGES
from orchestwin.knowledge.sources import (
    KnowledgeSources,
    consistency_issue,
    stage_consistency_issue,
)
from orchestwin.knowledge.stage_documents import stage_versions
from orchestwin.knowledge.state import ProjectStateSources

from .knowledge_fixtures import (
    REAL_PROJECT_ID,
    partial_sources,
    real_documents,
    real_sources,
    sources_of,
    state_sources,
)

FIELDS = {
    "team": ("team", "team_gate"),
    "twins": ("modeling", "modeling_gate"),
    "requirements": ("requirements", "requirements_gate"),
    "design": ("design", "design_gate"),
}


def without(*stages: str) -> dict[str, None]:
    return {name: None for stage in stages for name in FIELDS[stage]}


@pytest.mark.parametrize("count", range(1, len(STAGES) + 1))
def test_the_present_stages_are_the_approved_prefix_of_the_five(count: int) -> None:
    package = partial_sources(STAGES[count - 1])

    assert package.present_stages == STAGES[:count]
    assert package.pending_stage == (STAGES[count] if count < len(STAGES) else None)
    assert package.complete is (count == len(STAGES))


def test_a_complete_project_has_no_pending_stage() -> None:
    package = real_sources()

    assert package.present_stages == STAGES
    assert package.pending_stage is None
    assert package.complete is True
    assert package.state == ProjectStateSources()


@pytest.mark.parametrize("stage", ["team", "twins", "requirements", "design"])
def test_version_gate_and_payload_of_a_stage_that_is_not_present_raise_key_error(
    stage: str,
) -> None:
    package = partial_sources("brief")

    for read in (package.version, package.gate, package.payload):
        with pytest.raises(KeyError) as error:
            read(stage)
        assert error.value.args == (stage,)


def test_an_unknown_stage_raises_key_error() -> None:
    with pytest.raises(KeyError):
        real_sources().version("roadmap")


@pytest.mark.parametrize(
    "missing",
    [("team",), ("twins",), ("requirements",), ("team", "requirements"), ("twins", "design")],
)
def test_sources_whose_stages_are_not_a_prefix_are_refused(missing: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="only after every stage before it"):
        replace(real_sources(), **without(*missing))


def test_sources_that_only_miss_the_last_stages_are_accepted() -> None:
    package = replace(real_sources(), **without("requirements", "design"))

    assert package.present_stages == ("brief", "team", "twins")
    assert isinstance(package, KnowledgeSources)


def test_sources_without_an_approved_brief_are_refused() -> None:
    package = partial_sources("brief")

    with pytest.raises(ValueError, match="approved project brief"):
        replace(package, brief_gate=None)


def test_a_stage_given_without_its_gate_is_not_present() -> None:
    package = real_sources()

    trimmed = replace(package, design_gate=None)

    assert trimmed.present_stages == STAGES[:4]
    assert trimmed.pending_stage == "design"
    with pytest.raises(KeyError):
        trimmed.version("design")


def test_the_development_state_travels_with_the_sources() -> None:
    state = state_sources()

    package = partial_sources("team", state=state)

    assert package.state is state
    assert package.state.pending_changes == 1
    assert package.state.open_tasks == 1


@pytest.mark.parametrize(
    ("through", "stage", "issue"),
    [
        ("team", "brief", "TEAM_OUTDATED"),
        ("twins", "team", "USER_TWINS_OUTDATED"),
        ("requirements", "twins", "REQUIREMENTS_OUTDATED"),
        ("design", "requirements", "DESIGN_OUTDATED"),
    ],
)
def test_the_consistency_check_ignores_the_stages_that_are_not_present(
    through: str, stage: str, issue: str
) -> None:
    versions = stage_versions(real_documents())
    versions[stage] = replace(versions[stage], id=UUID(int=77))
    kept = STAGES[: STAGES.index(through)]
    partial = sources_of(
        {name: version for name, version in versions.items() if name in kept},
        project_id=REAL_PROJECT_ID,
    )

    assert consistency_issue(sources_of(versions, project_id=REAL_PROJECT_ID)) == issue
    assert partial.present_stages == kept
    assert consistency_issue(partial) is None


def test_stage_consistency_checks_only_the_given_stages() -> None:
    versions = stage_versions(real_documents())
    payloads = {stage: real_sources().payload(stage) for stage in STAGES}

    assert stage_consistency_issue(REAL_PROJECT_ID, {"brief": versions["brief"]}, {}) is None
    assert (
        stage_consistency_issue(
            REAL_PROJECT_ID,
            {stage: versions[stage] for stage in ("brief", "team")},
            {"team": payloads["team"]},
        )
        is None
    )
    assert (
        stage_consistency_issue(REAL_PROJECT_ID, {"team": versions["team"]}, payloads)
        == "TEAM_OUTDATED"
    )
    assert (
        stage_consistency_issue(UUID(int=78), {"brief": versions["brief"]}, payloads)
        == "PROJECT_MISMATCH"
    )
