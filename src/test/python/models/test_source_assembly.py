import pytest
from pydantic import TypeAdapter, ValidationError

from orchestwin.models.source_assembly import assemble_static_module
from orchestwin.models.source_file_generation import _module_parts_type
from orchestwin.models.source_structure import validate_static_module_contract
from orchestwin.projects.requirements_primitives import canonical_json

PARTS = {
    "shared_state": "const items = [];",
    "private_helpers": "function clean(name) {\n  return String(name).trim();\n}",
    "functions": [
        {
            "name": "addItem",
            "parameters": "name",
            "body": "  const record = clean(name);\n  items.push(record);\n  return { ok: true, record };",
        },
        {"name": "resetItems", "parameters": "", "body": "  items.length = 0;"},
    ],
    "browser_setup": "    const out = document.getElementById('ELM-005');\n    out.textContent = '';",
}


def test_assembly_places_parts_between_fixed_guards_in_a_deterministic_layout():
    assert assemble_static_module(PARTS) == (
        "const items = [];\n\n"
        "function clean(name) {\n  return String(name).trim();\n}\n\n"
        "function addItem(name) {\n"
        "  const record = clean(name);\n  items.push(record);\n  return { ok: true, record };\n"
        "}\n\n"
        "function resetItems() {\n  items.length = 0;\n}\n\n"
        "if (typeof document !== 'undefined') {\n"
        "  document.addEventListener('DOMContentLoaded', function () {\n"
        "    const out = document.getElementById('ELM-005');\n    out.textContent = '';\n"
        "  });\n}\n\n"
        "if (typeof module !== 'undefined') {\n  module.exports = { addItem, resetItems };\n}\n"
    )
    validate_static_module_contract(assemble_static_module(PARTS))


def test_empty_sections_leave_no_blank_prefix():
    parts = {**PARTS, "shared_state": "", "private_helpers": ""}
    assert assemble_static_module(parts).startswith("function addItem(name) {\n")


def test_model_output_and_plain_mapping_assemble_identically():
    adapter = TypeAdapter(_module_parts_type(["addItem", "resetItems"]))
    output = adapter.validate_json(canonical_json(PARTS), strict=True)
    assert assemble_static_module(output) == assemble_static_module(PARTS)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda parts: parts["functions"].reverse(),
        lambda parts: parts["functions"].pop(),
        lambda parts: parts["functions"][0].update(name="render"),
        lambda parts: parts["functions"][0].update(parameters="name) { alert(1); } function x("),
        lambda parts: parts["functions"][0].update(parameters="name: string, amount: number"),
        lambda parts: parts["functions"][0].update(body="  return 1;\r\n"),
        lambda parts: parts.update(browser_setup=""),
        lambda parts: parts.update(shared_state="\x01"),
        lambda parts: parts.update(content="complete file"),
    ],
)
def test_schema_pins_exported_names_order_and_bounded_text(mutation):
    parts = {
        **PARTS,
        "functions": [dict(function) for function in PARTS["functions"]],
    }
    mutation(parts)
    adapter = TypeAdapter(_module_parts_type(["addItem", "resetItems"]))
    with pytest.raises(ValidationError):
        adapter.validate_json(canonical_json(parts), strict=True)
