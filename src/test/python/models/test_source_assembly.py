import pytest
from pydantic import TypeAdapter, ValidationError

from orchestwin.models.source_assembly import (
    assemble_static_module,
    module_keeps_state,
    reset_statements,
)
from orchestwin.models.source_file_generation import _module_parts_type
from orchestwin.models.source_structure import (
    validate_reserved_names,
    validate_static_module_contract,
)
from orchestwin.models.source_syntax import SourceSyntaxError
from orchestwin.projects.requirements_primitives import canonical_json

PARTS = {
    "shared_state": [{"kind": "const", "name": "items", "initializer": "[]"}],
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
        "function resetSharedState() {\n  items.length = 0;\n}\n\n"
        "if (typeof document !== 'undefined') {\n"
        "  document.addEventListener('DOMContentLoaded', function () {\n"
        "    const out = document.getElementById('ELM-005');\n    out.textContent = '';\n"
        "  });\n}\n\n"
        "if (typeof module !== 'undefined') {\n  module.exports = { addItem, resetItems, resetSharedState };\n}\n"
    )
    validate_static_module_contract(assemble_static_module(PARTS))


def test_reset_restores_every_mutable_declaration_and_leaves_constants():
    declarations = [
        {"kind": "let", "name": "count", "initializer": "0"},
        {"kind": "let", "name": "label", "initializer": "'Totale'"},
        {"kind": "const", "name": "items", "initializer": "[]"},
        {"kind": "const", "name": "byName", "initializer": "{}"},
        {"kind": "const", "name": "index", "initializer": "new Map()"},
        {"kind": "const", "name": "seen", "initializer": "new Set()"},
        {"kind": "const", "name": "RATE", "initializer": "0.5"},
        {"kind": "const", "name": "EMPTY", "initializer": "null"},
    ]
    assert reset_statements(declarations) == [
        "  count = 0;",
        "  label = 'Totale';",
        "  items.length = 0;",
        "  Object.keys(byName).forEach(function (key) { delete byName[key]; });",
        "  index.clear();",
        "  seen.clear();",
    ]
    assembled = assemble_static_module({**PARTS, "shared_state": declarations})
    assert "function resetSharedState() {\n  count = 0;\n  label = 'Totale';\n" in assembled
    assert module_keeps_state(assembled)
    validate_static_module_contract(assembled)


@pytest.mark.parametrize(
    "shared_state",
    [[], [{"kind": "const", "name": "RATE", "initializer": "0.5"}]],
)
def test_stateless_modules_export_an_empty_reset(shared_state):
    assembled = assemble_static_module({**PARTS, "shared_state": shared_state})
    assert "function resetSharedState() {\n}\n\n" in assembled
    assert assembled.endswith("module.exports = { addItem, resetItems, resetSharedState };\n}\n")
    assert not module_keeps_state(assembled)


def test_empty_sections_leave_no_blank_prefix():
    parts = {**PARTS, "shared_state": [], "private_helpers": ""}
    assert assemble_static_module(parts).startswith("function addItem(name) {\n")


def test_a_model_function_cannot_shadow_the_platform_reset():
    adapter = TypeAdapter(_module_parts_type(["addItem", "resetSharedState"]))
    parts = {
        **PARTS,
        "functions": [PARTS["functions"][0], {**PARTS["functions"][1], "name": "resetSharedState"}],
    }
    output = adapter.validate_json(canonical_json(parts), strict=True)
    with pytest.raises(SourceSyntaxError) as failure:
        validate_reserved_names(output)
    assert failure.value.diagnostic["reason"] == "RESERVED_MODULE_NAME"


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
        lambda parts: parts.update(private_helpers="\x01"),
        lambda parts: parts["shared_state"].append(
            {"kind": "const", "name": "input", "initializer": "document.getElementById('x')"}
        ),
        lambda parts: parts["shared_state"].append(
            {"kind": "var", "name": "x", "initializer": "0"}
        ),
        lambda parts: parts["shared_state"].append(
            {"kind": "let", "name": "x", "initializer": "a + 1"}
        ),
        lambda parts: parts.update(content="complete file"),
    ],
)
def test_schema_pins_exported_names_order_and_bounded_text(mutation):
    parts = {
        **PARTS,
        "shared_state": [dict(declaration) for declaration in PARTS["shared_state"]],
        "functions": [dict(function) for function in PARTS["functions"]],
    }
    mutation(parts)
    adapter = TypeAdapter(_module_parts_type(["addItem", "resetItems"]))
    with pytest.raises(ValidationError):
        adapter.validate_json(canonical_json(parts), strict=True)
