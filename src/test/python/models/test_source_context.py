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
