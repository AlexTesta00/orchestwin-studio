from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from orchestwin.artifacts.bound_mockups import create_bound_mockup
from orchestwin.artifacts.generated_mockup_review import review_generated_mockup
from orchestwin.artifacts.provided_prototypes import (
    ProvidedPrototypeVersion,
    create_provided_prototype,
    provided_prototype_from_payload,
    provided_prototype_from_snapshot,
)
from orchestwin.workflow_inputs import (
    PROVIDED_PROTOTYPE_LIMITS,
    WorkflowInputError,
    decision_content_hash,
    validate_workflow_records,
    workflow_records,
)

from .test_generated_mockup_support import (
    ALTERNATIVE_ID,
    BASE_CODES,
    BASE_FIRST,
    BASE_SECOND,
    LIGHT_CHOICES,
    LIGHT_TOKENS,
    build,
    requirement_ids,
)

PROJECT_ID = UUID("c22a89a3-4aee-47f9-bd2b-ff541e517e70")
MOMENT = datetime(2026, 10, 3, 15, 50, tzinfo=UTC)
DEFINITION = {
    "artifact_id": "26a781d3-45fd-490c-bd2b-ff541e517e70",
    "version_number": 1,
    "content_hash": "a" * 64,
}


def parameters(**changes):
    return {
        "prototype_id": ALTERNATIVE_ID,
        "code": "PRT-001",
        "project_id": PROJECT_ID,
        "version_number": 1,
        "based_on_version_number": None,
        "definition_reference": DEFINITION,
        "created_at": MOMENT,
        "requirement_ids_by_code": requirement_ids(BASE_CODES),
    } | changes


def input_payload():
    mockup = build()
    return {
        "title": mockup.title,
        "visual_choices": LIGHT_CHOICES.to_snapshot(),
        "mockup": {
            "styles": mockup.styles,
            "screens": [screen.to_snapshot() for screen in mockup.screens],
        },
    }


def prototype(**changes):
    return provided_prototype_from_payload(input_payload(), **parameters(**changes))


def test_supplied_mockup_has_its_real_identity_and_generated_structure():
    source = input_payload()
    result = prototype()
    assert isinstance(result, ProvidedPrototypeVersion)
    assert result.id == result.mockup.design_alternative_id == ALTERNATIVE_ID
    assert result.mockup.mockup.to_snapshot() == build().to_snapshot()
    assert dict(result.mockup.requirement_ids_by_code) == requirement_ids(BASE_CODES)
    assert "declared_origin" not in result.to_snapshot()
    assert source == input_payload()


def test_supplied_mockup_uses_identical_static_review_and_contrast():
    result = prototype()
    expected = review_generated_mockup(
        result.mockup.mockup, tokens=LIGHT_TOKENS, requirement_codes=BASE_CODES
    )
    assert result.report == expected
    assert result.report.is_acceptable
    assert any(issue.code == "TABLE_TOO_SHORT" for issue in result.report.issues)


def test_snapshot_and_dossier_round_trip_preserve_origin_references_and_hash():
    payload = input_payload() | {"declared_origin": "  Figma   desktop  "}
    result = provided_prototype_from_payload(payload, **parameters())
    assert result.declared_origin == "Figma desktop"
    source_reference = {
        "project_id": "c3109c46-5723-43dc-9f64-13f46f9149c5",
        "artifact_id": str(result.id),
        "version_number": 2,
        "content_hash": "b" * 64,
    }
    imported = replace(result, original_reference=source_reference)
    snapshot = imported.to_snapshot()
    assert provided_prototype_from_snapshot(snapshot).to_snapshot() == snapshot
    envelope = workflow_records(PROJECT_ID, prototypes=[snapshot])
    assert envelope["limits"] == list(PROVIDED_PROTOTYPE_LIMITS)
    assert validate_workflow_records(envelope)["prototypes"][0] == snapshot
    assert snapshot["original_reference"]["content_hash"] == "b" * 64
    assert snapshot["content_hash"] != result.content_hash


def test_partial_definition_coverage_keeps_only_real_bindings():
    known = requirement_ids(BASE_CODES | {"REQ-003", "REQ-004", "REQ-005", "REQ-006"})
    result = prototype(requirement_ids_by_code=known)
    assert set(result.mockup.requirement_codes) == BASE_CODES
    assert "REQ-003" not in result.mockup.to_snapshot()["requirement_ids_by_code"]
    assert len(result.mockup.requirement_ids) == 2


def test_definition_reference_accepts_exact_artifact_version_values():
    reference = SimpleNamespace(
        artifact_id=UUID(DEFINITION["artifact_id"]),
        version_number=DEFINITION["version_number"],
        content_hash=DEFINITION["content_hash"],
    )
    assert dict(prototype(definition_reference=reference).definition_reference) == DEFINITION


def test_stable_identity_has_a_new_hash_and_exact_base_for_each_version():
    first = prototype()
    second = prototype(version_number=2, based_on_version_number=1)
    assert first.id == second.id
    assert first.code == second.code
    assert first.content_hash != second.content_hash
    assert provided_prototype_from_snapshot(second.to_snapshot()) == second


@pytest.mark.parametrize("count", [0, 1, 9])
def test_screen_contract_intentionally_rejects_one_screen_and_out_of_range_counts(count):
    payload = input_payload()
    screen = payload["mockup"]["screens"][0]
    payload["mockup"]["screens"] = [{**screen, "code": f"SCR-{i + 1:03d}"} for i in range(count)]
    with pytest.raises(WorkflowInputError) as caught:
        provided_prototype_from_payload(payload, **parameters())
    assert caught.value.code == "SCREEN_COUNT"


def test_eight_screens_keep_the_existing_global_upper_bound():
    links = "".join(f'<a href="#SCR-{i:03d}">Apri vista {i}</a>' for i in range(3, 9))
    mockup = build(
        BASE_FIRST.replace("</main>", links + "</main>"),
        BASE_SECOND,
        extra=[BASE_SECOND] * 6,
    )
    payload = input_payload()
    payload["mockup"] = mockup.to_snapshot()
    result = provided_prototype_from_payload(payload, **parameters())
    assert len(result.mockup.mockup.screens) == 8
    assert provided_prototype_from_snapshot(result.to_snapshot()).mockup == result.mockup


def test_no_anchors_are_rejected_by_unchanged_static_quality_contract():
    payload = input_payload()
    for screen in payload["mockup"]["screens"]:
        screen["markup"] = (
            screen["markup"].replace(' data-req="REQ-001"', "").replace(' data-req="REQ-002"', "")
        )
    with pytest.raises(WorkflowInputError) as caught:
        provided_prototype_from_payload(payload, **parameters())
    assert caught.value.code == "MOCKUP_QUALITY_REJECTED"
    assert "UNTRACED_CONTROL" in caught.value.detail
    assert "UNTRACED_SCREEN" in caught.value.detail


def test_unknown_requirement_is_not_repaired_or_bound_to_an_invented_identity():
    payload = input_payload()
    payload["mockup"]["screens"][0]["markup"] = payload["mockup"]["screens"][0]["markup"].replace(
        "REQ-001", "REQ-999"
    )
    unchanged = deepcopy(payload)
    with pytest.raises(WorkflowInputError) as caught:
        provided_prototype_from_payload(payload, **parameters())
    assert caught.value.code == "PROVIDED_PROTOTYPE_REQUIREMENT_REFERENCE_INVALID"
    assert payload == unchanged


@pytest.mark.parametrize(
    "unsafe",
    [
        "<script>alert(1)</script>",
        '<button onclick="alert(1)">Esegui</button>',
        '<img src="https://example.com/image.png">',
    ],
)
def test_unsafe_supplied_markup_is_rejected_without_repair(unsafe):
    payload = input_payload()
    payload["mockup"]["screens"][0]["markup"] += unsafe
    unchanged = deepcopy(payload)
    with pytest.raises(WorkflowInputError):
        provided_prototype_from_payload(payload, **parameters())
    assert payload == unchanged


@pytest.mark.parametrize(
    "styles", ["main{background:url(external.png)}", "main{color:var(--fake-color)}"]
)
def test_external_resources_and_unknown_tokens_are_rejected(styles):
    payload = input_payload()
    payload["mockup"]["styles"] = styles
    with pytest.raises(WorkflowInputError):
        provided_prototype_from_payload(payload, **parameters())


def test_wrong_mockup_identity_and_supplied_invented_fields_are_rejected():
    payload = input_payload()
    payload["mockup"]["design_alternative_id"] = "bf148737-a65b-4058-a0b4-97b09fcb21fe"
    with pytest.raises(WorkflowInputError) as caught:
        provided_prototype_from_payload(payload, **parameters())
    assert caught.value.code == "PROVIDED_PROTOTYPE_IDENTITY_MISMATCH"
    with pytest.raises(WorkflowInputError):
        provided_prototype_from_payload(input_payload() | {"synthetic_review": []}, **parameters())


def test_stored_payload_revalidates_static_quality_even_with_a_recomputed_hash():
    payload = prototype().to_snapshot()
    payload["mockup"]["mockup"]["screens"][0]["markup"] = (
        '<main data-req="REQ-001"><h1>Vuota</h1><a href="#SCR-002">Vai</a></main>'
    )
    payload["content_hash"] = decision_content_hash(payload)
    with pytest.raises(WorkflowInputError) as caught:
        provided_prototype_from_snapshot(payload)
    assert caught.value.code == "MOCKUP_QUALITY_REJECTED"
    assert "SCREEN_TOO_EMPTY" in caught.value.detail


def test_stored_payload_rejects_modified_hash_and_definition_reference():
    payload = prototype().to_snapshot()
    payload["definition_reference"]["content_hash"] = "b" * 64
    with pytest.raises(WorkflowInputError) as caught:
        provided_prototype_from_snapshot(payload)
    assert caught.value.code == "WORKFLOW_HASH_MISMATCH"


def test_factory_rechecks_real_requirement_bindings_and_freezes_metadata():
    mockup = build()
    bound = create_bound_mockup(mockup=mockup, requirement_ids_by_code=requirement_ids(BASE_CODES))
    wrong = requirement_ids(BASE_CODES)
    wrong["REQ-001"] = UUID("f93c194f-8968-4d34-b52d-eb5906832669")
    with pytest.raises(WorkflowInputError) as caught:
        create_provided_prototype(
            **parameters(requirement_ids_by_code=wrong),
            title=mockup.title,
            visual_choices=LIGHT_CHOICES.to_snapshot(),
            mockup=bound,
        )
    assert caught.value.code == "PROVIDED_PROTOTYPE_REQUIREMENT_REFERENCE_INVALID"
    result = prototype()
    with pytest.raises(FrozenInstanceError):
        result.title = "Altro"
    with pytest.raises(TypeError):
        result.definition_reference["content_hash"] = "b" * 64
    with pytest.raises(TypeError):
        result.visual_choices["archetype"] = "DASHBOARD"


@pytest.mark.parametrize(
    "changes",
    [
        {"version_number": 1, "based_on_version_number": 1},
        {"version_number": 2, "based_on_version_number": None},
        {"version_number": 3, "based_on_version_number": 1},
        {"version_number": True},
        {"created_at": datetime(2026, 10, 3)},
    ],
)
def test_invalid_version_bases_and_naive_timestamps_are_rejected(changes):
    with pytest.raises(WorkflowInputError):
        prototype(**changes)


@pytest.mark.parametrize(
    "bad_mockup",
    [None, "html", {}, {"styles": None, "screens": []}, {"styles": "", "screens": None}],
)
def test_malformed_supplied_mockup_uses_the_workflow_error_contract(bad_mockup):
    payload = input_payload() | {"mockup": bad_mockup}
    with pytest.raises(WorkflowInputError):
        provided_prototype_from_payload(payload, **parameters())
