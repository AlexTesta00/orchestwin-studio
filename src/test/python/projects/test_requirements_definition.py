from copy import deepcopy
from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.projects.requirements_persistence import (
    diff_from_record,
    diff_to_record,
    specification_from_snapshot,
    specification_version_from_record,
    specification_version_to_record,
)
from orchestwin.projects.requirements_primitives import snapshot_content_hash
from orchestwin.projects.requirements_realignment import realign_requirements
from orchestwin.projects.requirements_revisions import (
    RequirementsArtifactKind,
    RequirementsDiffOperationKind,
    RequirementsDiffProposalIssueCode,
    RequirementsDiffProposalStatus,
    propose_requirements_diff,
)
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.projects.requirements_traceability import (
    TraceabilityLinkKind,
    TraceabilityNodeKind,
    build_requirements_traceability,
    summarize_requirements_coverage,
)
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
    VERSION_ID,
    build_specification,
)


def definition_version(*, legacy=False):
    specification = build_specification() if legacy else enriched_specification()
    return RequirementsSpecificationVersion(
        id=VERSION_ID,
        project_id=specification.project_id,
        version_number=1,
        specification=specification,
        content_hash=specification.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def test_legacy_specification_graph_and_coverage_hashes_remain_exact():
    version = definition_version(legacy=True)
    assert (
        version.content_hash == "cb85823113b3ff2dbe48569c13c0f8080b14085830a04e73de081aec8f083e47"
    )
    assert (
        build_requirements_traceability(version).content_hash
        == "00349c35f9434117231fee6cc4e202ded7beef2acfbd712b1047e04ec99f1afc"
    )
    assert (
        snapshot_content_hash(summarize_requirements_coverage(version).to_snapshot())
        == "7fca8df149546597c4763f7ad1728447563b4d3e5484167bb9f4a06dd88ac449"
    )


@pytest.mark.parametrize("legacy", (True, False))
def test_definition_persistence_roundtrip_keeps_exact_schema_and_snapshots(legacy):
    version = definition_version(legacy=legacy)
    record = specification_version_to_record(version)
    assert record["schema_version"] == version.specification.schema_version
    assert specification_version_from_record(record) == version
    assert specification_from_snapshot(version.specification.to_snapshot()) == version.specification


@pytest.mark.parametrize(
    "field",
    (
        "schema_version",
        "content_hash",
        "traceability_hash",
        "traceability_snapshot",
        "coverage_snapshot",
    ),
)
def test_definition_record_rejects_inconsistent_schema_hash_graph_or_coverage(field):
    record = specification_version_to_record(definition_version())
    if field == "schema_version":
        record[field] = 1
    elif field.endswith("hash"):
        record[field] = "0" * 64
    else:
        record[field] = {}
    with pytest.raises(ValueError):
        specification_version_from_record(record)


def test_definition_parser_rejects_noncanonical_new_content():
    snapshot = deepcopy(enriched_specification().to_snapshot())
    snapshot["needs"][0]["title"] = " unnormalized title "
    with pytest.raises(ValueError, match="normalized"):
        specification_from_snapshot(snapshot)
    snapshot = deepcopy(enriched_specification().to_snapshot())
    snapshot["scenarios"][0].pop("criticalities")
    with pytest.raises(ValueError, match="canonical"):
        specification_from_snapshot(snapshot)


def test_definition_traceability_adds_the_complete_chain_only_for_schema_two():
    version = definition_version()
    graph = build_requirements_traceability(version)
    specification = version.specification
    need = specification.needs[0]
    scenario = specification.scenarios[0]
    shapes = {
        (
            link.kind,
            link.source.kind,
            link.source.artifact_id,
            link.target.kind,
            link.target.artifact_id,
        )
        for link in graph.links
    }
    assert (
        TraceabilityLinkKind.PARTICIPATES_IN,
        TraceabilityNodeKind.USER_TWIN,
        scenario.actor.twin_id,
        TraceabilityNodeKind.SCENARIO,
        scenario.id,
    ) in shapes
    assert (
        TraceabilityLinkKind.REVEALS,
        TraceabilityNodeKind.SCENARIO,
        scenario.id,
        TraceabilityNodeKind.NEED,
        need.id,
    ) in shapes
    for kind, artifacts in (
        (TraceabilityNodeKind.REQUIREMENT, specification.requirements),
        (TraceabilityNodeKind.USER_STORY, specification.user_stories),
    ):
        for artifact in artifacts:
            assert (
                TraceabilityLinkKind.MOTIVATES,
                TraceabilityNodeKind.NEED,
                need.id,
                kind,
                artifact.id,
            ) in shapes
    legacy = build_requirements_traceability(definition_version(legacy=True))
    assert all(node.reference.kind is not TraceabilityNodeKind.NEED for node in legacy.nodes)
    assert all(
        link.kind not in (TraceabilityLinkKind.REVEALS, TraceabilityLinkKind.PARTICIPATES_IN)
        for link in legacy.links
    )


def test_explicit_legacy_revision_adds_needs_preserving_all_surviving_identities():
    base = definition_version(legacy=True)
    result = propose_requirements_diff(
        base_version=base,
        proposed_specification=enriched_specification(base.specification),
        diff_id=UUID(int=1001),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )
    assert result.status is RequirementsDiffProposalStatus.CREATED
    assert result.diff is not None
    assert any(
        operation.artifact_kind is RequirementsArtifactKind.NEED
        and operation.operation is RequirementsDiffOperationKind.ADD
        for operation in result.diff.operations
    )
    assert all(
        operation.operation is not RequirementsDiffOperationKind.REMOVE
        for operation in result.diff.operations
    )
    assert diff_from_record(diff_to_record(result.diff)) == result.diff


def test_need_only_revision_is_typed_and_roundtrips():
    base = definition_version()
    specification = base.specification
    result = propose_requirements_diff(
        base_version=base,
        proposed_specification=replace(
            specification,
            needs=(replace(specification.needs[0], title="Choose confidently before confirming"),),
        ),
        diff_id=UUID(int=1002),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )
    assert result.diff is not None
    assert len(result.diff.operations) == 1
    operation = result.diff.operations[0]
    assert operation.artifact_kind is RequirementsArtifactKind.NEED
    assert operation.operation is RequirementsDiffOperationKind.REPLACE
    assert operation.artifact_id == specification.needs[0].id
    assert diff_from_record(diff_to_record(result.diff)) == result.diff


def test_need_code_cannot_move_to_a_new_identity():
    base = definition_version()
    specification = base.specification
    new_id = UUID(int=1003)
    proposed = replace(
        specification,
        needs=(replace(specification.needs[0], id=new_id),),
        requirements=tuple(
            replace(value, need_ids=(new_id,)) for value in specification.requirements
        ),
        user_stories=tuple(
            replace(value, need_ids=(new_id,)) for value in specification.user_stories
        ),
    )
    result = propose_requirements_diff(
        base_version=base,
        proposed_specification=proposed,
        diff_id=UUID(int=1004),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )
    assert result.issue is RequirementsDiffProposalIssueCode.IDENTITY_CHANGED


@pytest.mark.parametrize("legacy", (True, False))
def test_realignment_keeps_schema_and_historical_need_and_scenario_sources(legacy):
    base = aligned_specification(first_snapshot())
    written = base if legacy else enriched_specification(base)
    realigned = realign_requirements(written, second_snapshot())
    assert realigned.schema_version == written.schema_version
    assert realigned.needs == written.needs
    assert [
        (value.id, value.context, value.goal, value.criticalities, value.sources)
        for value in realigned.scenarios
    ] == [
        (value.id, value.context, value.goal, value.criticalities, value.sources)
        for value in written.scenarios
    ]
    assert [value.need_ids for value in realigned.requirements] == [
        value.need_ids for value in written.requirements
    ]
    assert [value.need_ids for value in realigned.user_stories] == [
        value.need_ids for value in written.user_stories
    ]
    assert realigned.scenarios[0].actor != written.scenarios[0].actor
