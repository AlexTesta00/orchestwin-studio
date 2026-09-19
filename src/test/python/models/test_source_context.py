"""A behavior change in approved artifacts must reach the source model unchanged."""

from copy import deepcopy

import pytest

from orchestwin.models.source_context import implementation_contract, implementation_work_order


def approved_context():
    return {
        "design": {
            "reference": {"id": "approved-design", "content_hash": "a" * 64},
            "content": {
                "prototype": {
                    "entry_screen_id": "booking",
                    "screens": [{"id": "booking"}, {"id": "confirmation"}, {"id": "error"}],
                    "transitions": [
                        {
                            "source_screen_id": "booking",
                            "target_screen_id": "confirmation",
                            "trigger_element_id": "submit",
                        }
                    ],
                },
            },
        },
        "requirements": {
            "content": {"acceptance_criteria": [{"code": "AC-1", "requirement_ids": ["FR-1"]}]},
        },
        "architecture": {
            "content": {
                "decisions": [{"context": "Reservations need a unique identifier."}],
                "connections": [{"source_id": "ui", "target_id": "service"}],
                "test_plan": {"acceptance_criterion_references": ["AC-1"]},
            },
        },
    }


def test_preserves_complete_selected_content_without_mutating_approved_artifacts():
    original = approved_context()
    before = deepcopy(original)
    projected = implementation_contract(original)
    assert projected["content"] == {name: value["content"] for name, value in original.items()}
    projected["content"]["design"]["prototype"]["screens"].clear()
    assert original == before


def test_work_order_repeats_business_statements_and_conditions_without_rewriting_them():
    original = approved_context()
    original["requirements"]["content"]["scenarios"] = [
        {"code": "SCN-9", "steps": ["Save two reservations."], "expected_outcome": "Retrieve both."}
    ]
    contract = implementation_contract(original)
    before = deepcopy(contract)
    work = implementation_work_order(contract)
    scenario = next(item for item in work["statements"] if item["code"] == "SCN-9")
    assert scenario == {
        "source": "implementation_contract.content.requirements.scenarios[0]",
        "code": "SCN-9",
        "steps": ["Save two reservations."],
        "expected_outcome": "Retrieve both.",
    }
    scenario["steps"].clear()
    assert contract == before


def test_required_design_fields_reach_the_acceptance_work_order_verbatim():
    original = approved_context()
    element = {"id": "guest", "field_name": "guest_name", "required": True, "kind": "TEXT_INPUT"}
    original["design"]["content"]["prototype"]["screens"][0]["elements"] = [element]
    contract = implementation_contract(original)
    work = implementation_work_order(contract)
    field = next(item for item in work["statements"] if item.get("id") == "guest")
    assert {k: v for k, v in field.items() if k != "source"} == element
    assert field["source"].endswith("screens[0].elements[0]")
    field["required"] = False
    assert (
        contract["content"]["design"]["prototype"]["screens"][0]["elements"][0]["required"] is True
    )


@pytest.mark.parametrize(
    "path,new_value",
    [
        (("design", "prototype", "transitions", 0, "target_screen_id"), "error"),
        (("design", "prototype", "entry_screen_id"), "confirmation"),
        (("requirements", "acceptance_criteria", 0, "code"), "AC-2"),
        (("architecture", "decisions", 0, "context"), "Reservations may share an identifier."),
        (("architecture", "connections", 0, "target_id"), "database"),
    ],
)
def test_behavior_changes_cannot_collapse_to_the_same_model_input(path, new_value):
    original = approved_context()
    changed = deepcopy(original)
    node = changed[path[0]]["content"]
    for key in path[1:-1]:
        node = node[key]
    node[path[-1]] = new_value
    assert implementation_contract(original) != implementation_contract(changed)


def test_reference_dictionary_is_lossless_and_does_not_rewrite_business_text():
    from orchestwin.models.source_context import compact_implementation_references

    identifier = "12345678-1234-1234-1234-123456789abc"
    original = approved_context()
    original["requirements"]["content"]["requirements"] = [
        {"id": identifier, "statement": identifier},
    ]
    original["architecture"]["content"]["requirement_ids"] = [identifier] * 10
    encoded = compact_implementation_references(original)
    alias, value = next(iter(encoded["reference_aliases"].items()))
    assert value == identifier
    assert encoded["requirements"]["content"]["requirements"][0]["statement"] == identifier
    assert encoded["architecture"]["content"]["requirement_ids"] == [alias] * 10
    assert encoded["design"]["reference"] == original["design"]["reference"]
    contract = implementation_contract(encoded)
    assert contract["reference_aliases"][alias] == identifier
    assert original["architecture"]["content"]["requirement_ids"] == [identifier] * 10
    encoded["architecture"]["content"]["requirement_ids"] = [
        contract["reference_aliases"][x]
        for x in encoded["architecture"]["content"]["requirement_ids"]
    ]
    assert encoded["architecture"]["content"] == original["architecture"]["content"]
