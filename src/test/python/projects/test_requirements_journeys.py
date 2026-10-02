from copy import deepcopy
from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.artifacts.traceability import (
    ArtifactGraphLinkKind,
    ArtifactGraphNodeKind,
    build_cross_stage_artifact_graph,
)
from orchestwin.projects.requirements_journeys import (
    create_journey_phase,
    create_user_journey,
)
from orchestwin.projects.requirements_persistence import (
    diff_from_record,
    diff_to_record,
    specification_from_snapshot,
    specification_version_from_record,
    specification_version_to_record,
)
from orchestwin.projects.requirements_realignment import realign_requirements
from orchestwin.projects.requirements_revisions import (
    RequirementsArtifactKind,
    RequirementsDiffOperationKind,
    RequirementsDiffProposalIssueCode,
    propose_requirements_diff,
)
from orchestwin.projects.requirements_specifications import RequirementsSpecification
from orchestwin.projects.requirements_traceability import (
    TraceabilityLinkKind,
    TraceabilityNodeKind,
    build_requirements_traceability,
    summarize_requirements_coverage,
)
from src.test.python.projects.test_requirements_definition import definition_version
from src.test.python.projects.test_requirements_needs import enriched_specification
from src.test.python.projects.test_requirements_realignment import (
    first_snapshot,
    second_snapshot,
)
from src.test.python.projects.test_requirements_realignment import (
    specification as aligned_specification,
)
from src.test.python.projects.test_requirements_specifications import (
    CREATED_AT,
    OWNER_ID,
    brief_source,
    build_specification,
)

JOURNEY_ID = UUID(int=2001)


def journey_specification(
    specification: RequirementsSpecification | None = None,
) -> RequirementsSpecification:
    base = enriched_specification() if specification is None else specification
    if base.schema_version == 1:
        base = enriched_specification(base)
    journeys = tuple(
        create_user_journey(
            journey_id=UUID(int=2001 + index),
            code=f"JRN-{index + 1:03}",
            title=f"Complete {scenario.title}",
            scenario_id=scenario.id,
            phases=(
                create_journey_phase(
                    title="Identify the request",
                    action="Review the request and identify the available choices.",
                    need_ids=tuple(
                        need.id for need in base.needs if scenario.id in need.scenario_ids
                    ),
                    touchpoint=None,
                    criticalities=("The initial request may need clarification.",),
                ),
                create_journey_phase(
                    title="Confirm the choice",
                    action="Check availability before confirming the selected choice.",
                    need_ids=tuple(
                        need.id for need in base.needs if scenario.id in need.scenario_ids
                    ),
                    touchpoint="Reception desk",
                ),
            ),
            sources=scenario.sources,
        )
        for index, scenario in enumerate(base.scenarios)
    )
    return replace(base, journeys=journeys)


def journey_version():
    version = definition_version()
    specification = journey_specification(version.specification)
    return replace(version, specification=specification, content_hash=specification.content_hash)


def test_phase_factory_normalizes_canonical_links_and_preserves_narrative_difficulties():
    phase = create_journey_phase(
        title=" Identify  choices ",
        action=" Review the  available choices. ",
        need_ids=(UUID(int=2), UUID(int=1)),
        touchpoint=" Reception  desk ",
        criticalities=(" Second difficulty. ", " First difficulty. "),
    )
    assert phase.title == "Identify choices"
    assert phase.action == "Review the available choices."
    assert phase.touchpoint == "Reception desk"
    assert phase.need_ids == (UUID(int=1), UUID(int=2))
    assert phase.criticalities == ("Second difficulty.", "First difficulty.")
    assert set(phase.to_snapshot()) == {
        "title",
        "action",
        "need_ids",
        "touchpoint",
        "criticalities",
    }
    assert len(phase.content_hash) == 64
    assert '"touchpoint"' in phase.canonical_json()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("title", " ", "empty"),
        ("title", "x" * 201, "maximum"),
        ("action", " ", "empty"),
        ("action", "x" * 2001, "maximum"),
        ("touchpoint", " ", "empty"),
        ("touchpoint", "x" * 2001, "maximum"),
        ("need_ids", (), "empty"),
        ("need_ids", (UUID(int=1), UUID(int=1)), "unique"),
        ("criticalities", ("x" * 2001,), "maximum"),
        ("criticalities", ("Issue", " Issue "), "unique"),
    ),
)
def test_phase_factory_rejects_invalid_values(field, value, message):
    values = {
        "title": "Identify choices",
        "action": "Review available choices.",
        "need_ids": (UUID(int=1),),
    }
    values[field] = value
    with pytest.raises(ValueError, match=message):
        create_journey_phase(**values)


def test_phase_direct_constructor_requires_canonical_normalized_content():
    phase = journey_specification().journeys[0].phases[0]
    with pytest.raises(ValueError, match="normalized"):
        replace(phase, action=" action ")
    with pytest.raises(ValueError, match="canonical"):
        replace(phase, need_ids=(UUID(int=2), UUID(int=1)))


def test_journey_preserves_phase_order_and_exact_snapshot_fields():
    journey = journey_specification().journeys[0]
    assert set(journey.to_snapshot()) == {"id", "code", "title", "scenario_id", "phases", "sources"}
    assert journey.to_snapshot()["phases"][0]["touchpoint"] is None
    reordered = replace(journey, phases=tuple(reversed(journey.phases)))
    assert reordered.content_hash != journey.content_hash
    assert reordered.canonical_json() != journey.canonical_json()
    with pytest.raises(ValueError, match="normalized"):
        replace(journey, title=" title ")


@pytest.mark.parametrize("size", (0, 33))
def test_journey_phase_count_outside_bounds_is_rejected(size):
    journey = journey_specification().journeys[0]
    with pytest.raises(ValueError, match="1 and 32"):
        replace(journey, phases=(journey.phases[0],) * size)


def test_journey_accepts_thirty_two_phases_and_rejects_invalid_phase_type():
    journey = journey_specification().journeys[0]
    assert len(replace(journey, phases=(journey.phases[0],) * 32).phases) == 32
    with pytest.raises(ValueError, match="JourneyPhase"):
        replace(journey, phases=("untyped phase",))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("code", "SCN-001", "JRN"),
        ("title", "x" * 201, "maximum"),
        ("sources", (), "empty"),
        ("sources", (brief_source(), brief_source()), "unique"),
    ),
)
def test_journey_factory_rejects_invalid_values(field, value, message):
    journey = journey_specification().journeys[0]
    values = {name: getattr(journey, name) for name in journey.__dataclass_fields__}
    values["journey_id"] = values.pop("id")
    values[field] = value
    with pytest.raises(ValueError, match=message):
        create_user_journey(**values)


def test_schema_one_rejects_journeys_without_upgrading_the_specification():
    with pytest.raises(ValueError, match="schema 1"):
        replace(build_specification(), journeys=journey_specification().journeys)


def test_schema_two_omits_empty_journeys_and_preserves_other_content():
    current = enriched_specification()
    assert current.journeys == ()
    assert "journeys" not in current.to_snapshot()
    proposed = journey_specification(current)
    snapshot = proposed.to_snapshot()
    assert snapshot.pop("journeys") == [journey.to_snapshot() for journey in proposed.journeys]
    assert snapshot == current.to_snapshot()
    assert (
        summarize_requirements_coverage(journey_version()).to_snapshot()
        == summarize_requirements_coverage(definition_version()).to_snapshot()
    )


@pytest.mark.parametrize(
    ("legacy", "specification_hash", "graph_hash", "cross_hash"),
    (
        (
            True,
            "cb85823113b3ff2dbe48569c13c0f8080b14085830a04e73de081aec8f083e47",
            "00349c35f9434117231fee6cc4e202ded7beef2acfbd712b1047e04ec99f1afc",
            "d8e9d4f5b93a643885bb4d77cb44f39cf59c2173931d9f242766b64aaad549fb",
        ),
        (
            False,
            "f4acd980e33ae740c6fb62ea594a8499849582c2ca9e774defce3ed118618c9f",
            "b4b4e2189431cd1fd72cdb4dba62dfa3b8c30ccf9f7888af92fc80edf16fd51d",
            "e68970b86eca9b7d64ddfd01246cc7f58bd89cde9eabf627ae3be9580161d2b7",
        ),
    ),
)
def test_specification_and_graph_hashes_without_journeys_match_the_preintegration_baseline(
    legacy, specification_hash, graph_hash, cross_hash
):
    version = definition_version(legacy=legacy)
    assert version.content_hash == specification_hash
    assert build_requirements_traceability(version).content_hash == graph_hash
    assert build_cross_stage_artifact_graph(version).content_hash == cross_hash
    assert "journeys" not in version.specification.to_snapshot()


def test_journey_requires_existing_scenario_and_at_most_one_journey_per_scenario():
    specification = journey_specification()
    journey = specification.journeys[0]
    with pytest.raises(ValueError, match="unknown reference"):
        replace(specification, journeys=(replace(journey, scenario_id=UUID(int=2999)),))
    with pytest.raises(ValueError, match="at most one"):
        replace(
            specification, journeys=(journey, replace(journey, id=UUID(int=2002), code="JRN-002"))
        )


def test_journey_identity_cannot_collide_with_existing_artifact():
    specification = journey_specification()
    with pytest.raises(ValueError, match="globally unique"):
        replace(
            specification,
            journeys=(replace(specification.journeys[0], id=specification.needs[0].id),),
        )


def test_journey_phase_need_must_exist_and_belong_to_the_journey_scenario():
    specification = journey_specification()
    journey = specification.journeys[0]
    with pytest.raises(ValueError, match="unknown references"):
        replace(
            specification,
            journeys=(
                replace(journey, phases=(replace(journey.phases[0], need_ids=(UUID(int=2999),)),)),
            ),
        )
    scenario = replace(specification.scenarios[0], id=UUID(int=2010), code="SCN-002")
    need = replace(
        specification.needs[0], id=UUID(int=2011), code="NED-002", scenario_ids=(scenario.id,)
    )
    extended = replace(
        specification,
        scenarios=(*specification.scenarios, scenario),
        needs=(*specification.needs, need),
        requirements=tuple(
            replace(value, need_ids=(*value.need_ids, need.id))
            for value in specification.requirements
        ),
    )
    with pytest.raises(ValueError, match="journey scenario"):
        replace(
            extended,
            journeys=(replace(journey, phases=(replace(journey.phases[0], need_ids=(need.id,)),)),),
        )


def test_journey_snapshot_record_and_diff_roundtrips_are_lossless():
    version = journey_version()
    assert specification_from_snapshot(version.specification.to_snapshot()) == version.specification
    assert specification_version_from_record(specification_version_to_record(version)) == version
    proposal = propose_requirements_diff(
        base_version=definition_version(),
        proposed_specification=version.specification,
        diff_id=UUID(int=2020),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )
    assert proposal.diff is not None
    [operation] = proposal.diff.operations
    assert operation.artifact_kind is RequirementsArtifactKind.JOURNEY
    assert operation.operation is RequirementsDiffOperationKind.ADD
    assert diff_from_record(diff_to_record(proposal.diff)) == proposal.diff


def test_phase_content_revision_keeps_journey_identity_and_order():
    base = journey_version()
    journey = base.specification.journeys[0]
    phases = (
        replace(journey.phases[0], action="Clarify the request before reviewing choices."),
        journey.phases[1],
    )
    proposed = replace(base.specification, journeys=(replace(journey, phases=phases),))
    result = propose_requirements_diff(
        base_version=base,
        proposed_specification=proposed,
        diff_id=UUID(int=2021),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )
    assert result.diff is not None
    [operation] = result.diff.operations
    assert operation.artifact_kind is RequirementsArtifactKind.JOURNEY
    assert operation.operation is RequirementsDiffOperationKind.REPLACE
    assert operation.artifact_id == journey.id
    assert operation.after.phases[1] == journey.phases[1]
    assert diff_from_record(diff_to_record(result.diff)) == result.diff


def test_journey_code_cannot_move_to_another_identity():
    base = journey_version()
    proposed = replace(
        base.specification, journeys=(replace(base.specification.journeys[0], id=UUID(int=2999)),)
    )
    result = propose_requirements_diff(
        base_version=base,
        proposed_specification=proposed,
        diff_id=UUID(int=2022),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )
    assert result.issue is RequirementsDiffProposalIssueCode.IDENTITY_CHANGED


@pytest.mark.parametrize(
    "tamper", ("missing_touchpoint", "empty_journeys", "unknown_field", "unnormalized_phase")
)
def test_journey_snapshot_parser_rejects_noncanonical_content(tamper):
    snapshot = deepcopy(journey_specification().to_snapshot())
    if tamper == "missing_touchpoint":
        snapshot["journeys"][0]["phases"][0].pop("touchpoint")
    elif tamper == "empty_journeys":
        snapshot["journeys"] = []
    elif tamper == "unknown_field":
        snapshot["journeys"][0]["emotion"] = "invented"
    else:
        snapshot["journeys"][0]["phases"][0]["action"] = " action "
    with pytest.raises(ValueError):
        specification_from_snapshot(snapshot)


def test_journey_graphs_expand_scenario_and_aggregate_each_need_once():
    version = journey_version()
    journey = version.specification.journeys[0]
    graph = build_requirements_traceability(version)
    expands = [link for link in graph.links if link.kind is TraceabilityLinkKind.EXPANDS]
    assert len(expands) == 1
    assert expands[0].source.kind is TraceabilityNodeKind.SCENARIO
    assert expands[0].source.artifact_id == journey.scenario_id
    assert expands[0].target.kind is TraceabilityNodeKind.JOURNEY
    assert expands[0].target.artifact_id == journey.id
    reveals = [
        link
        for link in graph.links
        if link.kind is TraceabilityLinkKind.REVEALS
        and link.source.kind is TraceabilityNodeKind.JOURNEY
    ]
    assert len(reveals) == 1
    assert reveals[0].target.artifact_id == journey.phases[0].need_ids[0]
    cross = build_cross_stage_artifact_graph(version)
    assert len([link for link in cross.links if link.kind is ArtifactGraphLinkKind.EXPANDS]) == 1
    assert (
        len(
            [
                link
                for link in cross.links
                if link.kind is ArtifactGraphLinkKind.REVEALS
                and link.source.kind is ArtifactGraphNodeKind.JOURNEY
            ]
        )
        == 1
    )
    assert any(
        node.reference.kind is ArtifactGraphNodeKind.JOURNEY and node.title == journey.title
        for node in cross.nodes
    )


def test_realignment_preserves_journey_phases_links_and_historical_sources():
    written = journey_specification(enriched_specification(aligned_specification(first_snapshot())))
    realigned = realign_requirements(written, second_snapshot())
    assert realigned.journeys == written.journeys
    assert realigned.schema_version == 2
    assert realigned.scenarios[0].actor != written.scenarios[0].actor
