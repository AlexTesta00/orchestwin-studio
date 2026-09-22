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
    text += DOCUMENT_GUARD_OPEN + _field(parts, "browser_setup") + DOCUMENT_GUARD_CLOSE
    names = ", ".join(_field(function, "name") for function in functions)
    return text + MODULE_GUARD_OPEN + names + MODULE_GUARD_CLOSE
