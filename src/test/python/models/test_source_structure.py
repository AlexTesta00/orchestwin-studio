import pytest

from orchestwin.models.source_structure import (
    validate_shared_state_updates,
    validate_static_module_contract,
)
from orchestwin.models.source_syntax import SourceSyntaxError

COMPLIANT = """'use strict';
const guests = [];

function addGuest(name) {
  if (typeof name !== 'string' || name.trim() === '') {
    throw new Error('Il nome non può essere vuoto; document is only a word here');
  }
  const record = { id: guests.length + 1, name: name.trim() };
  guests.push(record);
  return record;
}

function listGuests() {
  return guests.map((guest) => ({ ...guest }));
}

// initializeApp(); this comment must not count
if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', function () {
    const button = document.getElementById('ELM-003');
    button.addEventListener('click', function () {
      addGuest(document.getElementById('ELM-002').value);
    });
  });
}

if (typeof module !== 'undefined') {
  module.exports = { addGuest, listGuests };
}
"""

GENERATED_YESTERDAY = """const guests = [];

function addGuest(name) {
  const errorMessageElement = document.getElementById('ELM-007');
  if (!name || name.trim() === '') {
    errorMessageElement.hidden = false;
    return false;
  }
  guests.push({ name: name });
  return true;
}

function initializeApp() {
  document.addEventListener('DOMContentLoaded', function () {
    const addButton = document.getElementById('ELM-003');
    addButton.addEventListener('click', function () {
      addGuest('x');
    });
  });
}

initializeApp();"""


def test_compliant_module_passes():
    validate_static_module_contract(COMPLIANT)


@pytest.mark.parametrize(
    "content,reason,line",
    [
        (GENERATED_YESTERDAY, "MODULE_FUNCTION_TOUCHES_DOM", 3),
        (
            "function a() {}\ndocument.addEventListener('DOMContentLoaded', a);\n"
            "if (typeof module !== 'undefined') { module.exports = { a }; }\n",
            "MODULE_SCOPE_DOM_ACCESS",
            2,
        ),
        (
            "const root = document.getElementById('x');\nfunction a() {}\n"
            "if (typeof module !== 'undefined') { module.exports = { a }; }\n",
            "MODULE_SCOPE_DOM_ACCESS",
            1,
        ),
        ("function a() {}\n", "MISSING_GUARDED_MODULE_EXPORTS", None),
        (
            "function a() {}\nif (typeof module !== 'undefined') { module.exports = { a, b }; }\n",
            "EXPORTS_UNDECLARED_FUNCTION",
            2,
        ),
        (
            "function a() {}\nif (typeof module !== 'undefined') { module.exports = {}; }\n",
            "EXPORTS_UNDECLARED_FUNCTION",
            2,
        ),
    ],
)
def test_contract_violations_are_reported_with_lines(content, reason, line):
    with pytest.raises(SourceSyntaxError) as failure:
        validate_static_module_contract(content)
    assert failure.value.diagnostic["reason"] == reason
    assert failure.value.diagnostic["line"] == line
    assert failure.value.diagnostic["parser"] == "static-module-contract"


def test_exports_may_reference_arrow_functions_and_aliases():
    content = (
        "const render = () => 'ok';\nfunction core() { return render(); }\n"
        "if (typeof module !== 'undefined' && module.exports) {\n"
        "  module.exports = { core: core, render };\n}\n"
    )
    validate_static_module_contract(content)


def test_exported_functions_must_not_touch_the_dom():
    content = (
        "function core() { return 1; }\n"
        "function render() { document.getElementById('x').textContent = core(); }\n"
        "if (typeof module !== 'undefined') { module.exports = { core, render }; }\n"
    )
    with pytest.raises(SourceSyntaxError) as failure:
        validate_static_module_contract(content)
    assert failure.value.diagnostic["reason"] == "MODULE_FUNCTION_TOUCHES_DOM"
    assert failure.value.diagnostic["line"] == 2
    assert failure.value.diagnostic["detail"] == "render"


def test_exported_functions_must_not_reach_the_dom_through_helpers():
    content = (
        "function core(name) { if (!name) { showError('empty'); return; } return name; }\n"
        "function showError(message) { document.getElementById('e').textContent = message; }\n"
        "if (typeof module !== 'undefined') { module.exports = { core }; }\n"
    )
    with pytest.raises(SourceSyntaxError) as failure:
        validate_static_module_contract(content)
    assert failure.value.diagnostic["reason"] == "MODULE_FUNCTION_TOUCHES_DOM"
    assert failure.value.diagnostic["line"] == 2
    assert failure.value.diagnostic["detail"] == "showError"


def test_top_level_dom_helpers_are_rejected_even_when_only_the_guard_calls_them():
    content = (
        "function core(name) { return { ok: Boolean(name) }; }\n"
        "function render(result) { document.getElementById('o').textContent = result.ok; }\n"
        "if (typeof document !== 'undefined') {\n"
        "  document.addEventListener('DOMContentLoaded', function () { render(core('a')); });\n"
        "}\n"
        "if (typeof module !== 'undefined') { module.exports = { core }; }\n"
    )
    with pytest.raises(SourceSyntaxError) as failure:
        validate_static_module_contract(content)
    assert failure.value.diagnostic["reason"] == "MODULE_FUNCTION_TOUCHES_DOM"
    assert failure.value.diagnostic["detail"] == "render"


def test_dom_helpers_inside_the_document_guard_pass():
    content = (
        "const items = [];\n"
        "function addItem(name) { items.push(name); return { ok: true, count: items.length }; }\n"
        "function resetItems() { items.length = 0; }\n"
        "if (typeof document !== 'undefined') {\n"
        "  document.addEventListener('DOMContentLoaded', function () {\n"
        "    const output = document.getElementById('o');\n"
        "    function render(result) { output.textContent = result.count; }\n"
        "    document.getElementById('b').addEventListener('click', function () { render(addItem('x')); });\n"
        "  });\n"
        "}\n"
        "if (typeof module !== 'undefined') { module.exports = { addItem, resetItems }; }\n"
    )
    validate_static_module_contract(content)


@pytest.mark.parametrize(
    "content,reason,line",
    [
        (
            "const guests = JSON.parse(localStorage.getItem('guests')) || [];\n"
            "function core() { return guests; }\n"
            "if (typeof module !== 'undefined') { module.exports = { core }; }\n",
            "MODULE_SCOPE_DOM_ACCESS",
            1,
        ),
        (
            "const guests = [];\n"
            "function core(name) { guests.push(name); save(); return { ok: true }; }\n"
            "function save() { localStorage.setItem('guests', JSON.stringify(guests)); }\n"
            "if (typeof module !== 'undefined') { module.exports = { core }; }\n",
            "MODULE_FUNCTION_TOUCHES_DOM",
            3,
        ),
        (
            "function core() { return fetch('/api').then(r => r.json()); }\n"
            "if (typeof module !== 'undefined') { module.exports = { core }; }\n",
            "MODULE_FUNCTION_TOUCHES_DOM",
            1,
        ),
    ],
)
def test_browser_globals_count_as_dom_access(content, reason, line):
    with pytest.raises(SourceSyntaxError) as failure:
        validate_static_module_contract(content)
    assert failure.value.diagnostic["reason"] == reason
    assert failure.value.diagnostic["line"] == line


def test_node_tests_must_not_reference_storage():
    from orchestwin.models.source_structure import validate_node_test_contract

    content = (
        "const test = require('node:test');\n"
        "const { core } = require('./app.js');\n"
        "test('x', () => { localStorage.clear(); core(); });\n"
    )
    with pytest.raises(SourceSyntaxError) as failure:
        validate_node_test_contract(content)
    assert failure.value.diagnostic["reason"] == "NODE_TEST_REFERENCES_DOM"


@pytest.mark.parametrize(
    "content,reason",
    [
        ("const test = require('node:test');\nconst app = require('./app.js');\n", None),
        ("const app = require('./app.js');\n", "NODE_TEST_FRAMEWORK_MISSING"),
        ("const test = require('node:test');\n", "NODE_TEST_DOES_NOT_LOAD_MODULE"),
        (
            "const test = require('node:test');\nconst app = require('./app.js');\nglobal.document = {};\n",
            "NODE_TEST_REFERENCES_DOM",
        ),
        (
            "const test = require('node:test');\nconst app = require('./app.js');\n// document stays a comment\n",
            None,
        ),
    ],
)
def test_node_test_contract(content, reason):
    from orchestwin.models.source_structure import validate_node_test_contract

    if reason is None:
        validate_node_test_contract(content)
        return
    with pytest.raises(SourceSyntaxError) as failure:
        validate_node_test_contract(content)
    assert failure.value.diagnostic["reason"] == reason


def test_empty_statements_and_braceless_module_guards_pass():
    content = (
        "function core() { return 1; };\n"
        "if (typeof module !== 'undefined') module.exports = { core };\n"
    )
    validate_static_module_contract(content)


@pytest.mark.parametrize(
    "assertion,accepted",
    [
        ("assert.ok(value())", True),
        ("assert.deepStrictEqual(value(), 3)", True),
        ("assert.throws(() => value(null))", True),
        ("assert.notOk(value())", False),
        ("assert.isTrue(value())", False),
        ("assert.equals(value(), 3)", False),
    ],
)
def test_node_tests_may_use_only_real_assert_methods(assertion, accepted):
    from orchestwin.models.source_structure import validate_node_test_contract

    content = (
        "const test = require('node:test');\n"
        "const assert = require('node:assert/strict');\n"
        "const { value } = require('./app.js');\n"
        "test('value', () => { " + assertion + "; });\n"
    )
    if accepted:
        validate_node_test_contract(content)
        return
    with pytest.raises(SourceSyntaxError) as failure:
        validate_node_test_contract(content)
    assert failure.value.diagnostic["reason"] == "NODE_TEST_UNKNOWN_ASSERTION"
    assert failure.value.diagnostic["line"] == 4


@pytest.mark.parametrize(
    "shared_state,bodies",
    [
        ("const items = [];", "  items.push(name);\n  return { ok: true, count: items.length };"),
        ("let count = 0;", "  count += 1;\n  return count;"),
        ("let total = 0;", "  total = total + amount;"),
        ("const state = { count: 0 };", "  state.count += 1;"),
        ("const byName = new Map();", "  byName.set(name, record);"),
        ("const RATE = 0.621371;", "  return kilometers * RATE;"),
        ("const items = [];", "function store(record) {\n  items.push(record);\n}"),
        ("const items = [];", "  items[items.length] = record;"),
        ("const loans = [];", "  Object.assign(loans, [record]);"),
        ("", "  return 1;"),
    ],
)
def test_shared_state_mutated_by_core_functions_passes(shared_state, bodies):
    validate_shared_state_updates(shared_state, bodies)


@pytest.mark.parametrize(
    "shared_state,bodies,name",
    [
        ("const loans = [];", "  return loans.map((loan, index) => ({ id: index + 1 }));", "loans"),
        (
            "const items = [];",
            "  if (items.length === 0) { return false; }\n  return true;",
            "items",
        ),
        ("let count = 0;", "  return count;", "count"),
        ("const items = [];\nlet last = '';", "  items.push(name);\n  return last;", "last"),
        ("const items = [];", "  return items == null || items.length === 0;", "items"),
    ],
)
def test_shared_state_never_updated_is_rejected(shared_state, bodies, name):
    with pytest.raises(SourceSyntaxError) as failure:
        validate_shared_state_updates(shared_state, bodies)
    assert failure.value.diagnostic["reason"] == "SHARED_STATE_NEVER_UPDATED"
    assert failure.value.diagnostic["detail"] == name
