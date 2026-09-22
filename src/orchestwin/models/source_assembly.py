import re

RESET_FUNCTION = "resetSharedState"
_STATEFUL_MODULE = re.compile(r"^function resetSharedState\(\) \{\n(?!\})", re.MULTILINE)
DOCUMENT_GUARD_OPEN = (
    "if (typeof document !== 'undefined') {\n"
    "  document.addEventListener('DOMContentLoaded', function () {\n"
)
DOCUMENT_GUARD_CLOSE = "\n  });\n}\n\n"
MODULE_GUARD_OPEN = "if (typeof module !== 'undefined') {\n  module.exports = { "
MODULE_GUARD_CLOSE = " };\n}\n"
PART_KEYS = ("shared_state", "private_helpers", "functions", "browser_setup")


def _field(value, key):
    return value[key] if isinstance(value, dict) else getattr(value, key)


def reset_statements(declarations):
    statements = []
    for declaration in declarations:
        name = _field(declaration, "name")
        initializer = _field(declaration, "initializer")
        if _field(declaration, "kind") == "let":
            statements.append("  " + name + " = " + initializer + ";")
        elif initializer == "[]":
            statements.append("  " + name + ".length = 0;")
        elif initializer == "{}":
            statements.append(
                "  Object.keys(" + name + ").forEach(function (key) { delete " + name + "[key]; });"
            )
        elif initializer in ("new Map()", "new Set()"):
            statements.append("  " + name + ".clear();")
    return statements


def module_keeps_state(content):
    return _STATEFUL_MODULE.search(content) is not None


def assemble_static_module(parts):
    text = ""
    declarations = _field(parts, "shared_state")
    if declarations:
        text += "\n".join(
            _field(declaration, "kind")
            + " "
            + _field(declaration, "name")
            + " = "
            + _field(declaration, "initializer")
            + ";"
            for declaration in declarations
        )
        text += "\n\n"
    helpers = _field(parts, "private_helpers")
    if helpers:
        text += helpers + "\n\n"
    functions = _field(parts, "functions")
    for function in functions:
        text += (
            "function "
            + _field(function, "name")
            + "("
            + _field(function, "parameters")
            + ") {\n"
            + _field(function, "body")
            + "\n}\n\n"
        )
    text += "function " + RESET_FUNCTION + "() {\n"
    text += "".join(statement + "\n" for statement in reset_statements(declarations))
    text += "}\n\n"
    text += DOCUMENT_GUARD_OPEN + _field(parts, "browser_setup") + DOCUMENT_GUARD_CLOSE
    names = ", ".join([*(_field(function, "name") for function in functions), RESET_FUNCTION])
    return text + MODULE_GUARD_OPEN + names + MODULE_GUARD_CLOSE
