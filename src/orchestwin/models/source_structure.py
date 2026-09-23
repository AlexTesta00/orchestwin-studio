import re

from orchestwin.models.source_assembly import RESET_FUNCTION, assemble_static_module
from orchestwin.models.source_syntax import SourceSyntaxError

PARSER = "static-module-contract"
_DOCUMENT_GUARD = re.compile(r"^if\s*\(\s*typeof\s+(document|window)\s*!==?\s*['\"][^'\"]*['\"]")
_MODULE_GUARD = re.compile(r"^if\s*\(\s*typeof\s+module\s*!==?\s*['\"][^'\"]*['\"]")
_FUNCTION = re.compile(r"^(async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(")
_CLASS = re.compile(r"^class\s+([A-Za-z_$][\w$]*)")
_VARIABLE = re.compile(r"^(const|let|var)\s+([A-Za-z_$][\w$]*)")
_DOM = re.compile(
    r"\b(document|window|globalThis|localStorage|sessionStorage|navigator|fetch|XMLHttpRequest|alert)\b"
)
_EXPORTS = re.compile(r"module\.exports\s*=\s*\{([^}]*)\}")
_DIRECTIVE = re.compile(r"^['\"]\s*['\"]\s*;?$")
_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")


def _blank(source):
    output = []
    index = 0
    size = len(source)
    while index < size:
        character = source[index]
        if source.startswith("//", index):
            end = source.find("\n", index)
            end = size if end < 0 else end
            output.append(" " * (end - index))
            index = end
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            end = size if end < 0 else end + 2
            output.append("".join("\n" if ch == "\n" else " " for ch in source[index:end]))
            index = end
            continue
        if character in "'\"`":
            end = index + 1
            while end < size and source[end] != character:
                if source[end] == "\\":
                    end += 1
                end += 1
            end = min(size, end + 1)
            inner = "".join("\n" if ch == "\n" else " " for ch in source[index + 1 : end - 1])
            output.append(character + inner + (character if end <= size else ""))
            index = end
            continue
        output.append(character)
        index += 1
    return "".join(output)


def _statements(blanked):
    statements = []
    depth = 0
    start = None
    for index, character in enumerate(blanked):
        if start is None:
            if character.isspace():
                continue
            start = index
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
            if depth == 0 and character == "}":
                statements.append((start, blanked[start : index + 1]))
                start = None
                continue
        elif character == ";" and depth == 0:
            statements.append((start, blanked[start : index + 1]))
            start = None
    if start is not None:
        statements.append((start, blanked[start:]))
    return statements


def _names(fragment):
    names = set()
    for entry in fragment.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            entry = entry.split(":", 1)[1].strip()
        match = _IDENTIFIER.fullmatch(entry)
        if match is None:
            return None
        names.add(match.group(0))
    return names


def exported_names(content):
    match = _EXPORTS.search(_blank(content))
    return (_names(match.group(1)) or set()) if match else set()


def validate_static_module_contract(content):
    blanked = _blank(content)
    declared = set()
    exported = None
    exports_line = None
    for start, statement in _statements(blanked):
        line = blanked.count("\n", 0, start) + 1
        text = statement.strip()
        if text == ";" or _DIRECTIVE.match(text):
            continue
        function = _FUNCTION.match(text)
        if function:
            touched = _DOM.search(statement)
            if touched:
                raise SourceSyntaxError(
                    reason="MODULE_FUNCTION_TOUCHES_DOM",
                    line=line,
                    parser=PARSER,
                    detail=function.group(2) + " uses " + touched.group(1),
                )
            declared.add(function.group(2))
            continue
        klass = _CLASS.match(text)
        if klass:
            declared.add(klass.group(1))
            continue
        if _DOCUMENT_GUARD.match(text):
            continue
        if _MODULE_GUARD.match(text):
            match = _EXPORTS.search(statement)
            if match is None:
                raise SourceSyntaxError(
                    reason="MISSING_GUARDED_MODULE_EXPORTS", line=line, parser=PARSER
                )
            exported = _names(match.group(1))
            exports_line = line
            continue
        variable = _VARIABLE.match(text)
        if variable:
            if _DOM.search(text):
                raise SourceSyntaxError(reason="MODULE_SCOPE_DOM_ACCESS", line=line, parser=PARSER)
            declared.add(variable.group(2))
            continue
        reason = "MODULE_SCOPE_DOM_ACCESS" if _DOM.search(text) else "MODULE_SCOPE_SIDE_EFFECT"
        raise SourceSyntaxError(reason=reason, line=line, parser=PARSER)
    if exported is None:
        raise SourceSyntaxError(reason="MISSING_GUARDED_MODULE_EXPORTS", parser=PARSER)
    if not exported or not exported <= declared:
        raise SourceSyntaxError(
            reason="EXPORTS_UNDECLARED_FUNCTION", line=exports_line, parser=PARSER
        )
    bodies = {}
    for name in declared:
        body_start, body = _function_body(blanked, name)
        if body is not None:
            bodies[name] = (body_start, body)
    for name in sorted(exported):
        offender = _dom_reach(name, bodies, frozenset())
        if offender is not None:
            raise SourceSyntaxError(
                reason="EXPORTED_FUNCTION_TOUCHES_DOM",
                line=blanked.count("\n", 0, bodies[name][0]) + 1,
                parser=PARSER,
                detail=name if offender == name else f"{name} calls {offender}",
            )


def _dom_reach(name, bodies, path):
    entry = bodies.get(name)
    if entry is None or name in path:
        return None
    _, body = entry
    if _DOM.search(body):
        return name
    for callee in sorted(set(_IDENTIFIER.findall(body))):
        if callee != name and callee in bodies:
            found = _dom_reach(callee, bodies, path | {name})
            if found is not None:
                return found
    return None


def _function_body(blanked, name):
    match = re.search(r"\bfunction\s*\*?\s*" + re.escape(name) + r"\s*\(", blanked)
    if match is None:
        return None, None
    index = blanked.find("{", match.end())
    if index < 0:
        return None, None
    depth = 0
    for position in range(index, len(blanked)):
        if blanked[position] == "{":
            depth += 1
        elif blanked[position] == "}":
            depth -= 1
            if depth == 0:
                return match.start(), blanked[index : position + 1]
    return match.start(), blanked[index:]


_MUTABLE_INITIALIZERS = frozenset({"[]", "{}", "new Map()", "new Set()"})
_MUTATION_METHODS = "push|pop|shift|unshift|splice|sort|reverse|fill|set|delete|clear|add"


def _mutation(name):
    escaped = re.escape(name)
    return re.compile(
        r"(\b" + escaped + r"\s*(\.(" + _MUTATION_METHODS + r")\s*\(|"
        r"(\.[A-Za-z_$][\w$]*|\[[^\]]*\])*\s*(=(?!=)|\+\+|--|\+=|-=|\*=|/=))|"
        r"(\+\+|--)\s*" + escaped + r"\b|Object\.assign\(\s*" + escaped + r"\b)"
    )


_CALL = re.compile(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(")
_DECLARED = re.compile(r"\b(?:function\s+|const\s+|let\s+|var\s+)([A-Za-z_$][\w$]*)")
_PARAMETER = re.compile(r"[A-Za-z_$][\w$]*")
_HELPER_PARAMETERS = re.compile(r"function\s+[A-Za-z_$][\w$]*\s*\(([^)]*)\)")
_OBJECT_KEY = re.compile(r"[{,]\s*([A-Za-z_$][\w$]*)\s*:")


def _part(value, key):
    return value[key] if isinstance(value, dict) else getattr(value, key)


_NESTED_READY = re.compile(r"DOMContentLoaded|addEventListener\(\s*['\"]load['\"]|\.onload\s*=")


def validate_reserved_names(parts):
    declared = (
        [_part(declaration, "name") for declaration in _part(parts, "shared_state")]
        + _DECLARED.findall(_blank(_part(parts, "private_helpers")))
        + [_part(function, "name") for function in _part(parts, "functions")]
    )
    if RESET_FUNCTION in declared:
        raise SourceSyntaxError(reason="RESERVED_MODULE_NAME", parser=PARSER, detail=RESET_FUNCTION)


_DECLARATION_ONLY = re.compile(r"^(?:async\s+)?(?:function\b|class\b)")


def validate_browser_setup(parts):
    browser_setup = _part(parts, "browser_setup")
    statements = [text.strip() for _, text in _statements(_blank(browser_setup)) if text.strip()]
    if statements and all(_DECLARATION_ONLY.match(text) for text in statements):
        raise SourceSyntaxError(reason="BROWSER_SETUP_ONLY_DECLARES_FUNCTIONS", parser=PARSER)
    match = _NESTED_READY.search(browser_setup)
    if match is None:
        return
    content = assemble_static_module(parts)
    offset = content.find(browser_setup)
    raise SourceSyntaxError(
        reason="BROWSER_SETUP_NESTS_DOM_READY",
        line=content.count("\n", 0, offset + match.start()) + 1 if offset >= 0 else None,
        parser=PARSER,
    )


def _call_line(parts, name, callee):
    content = _blank(assemble_static_module(parts))
    header = (
        content.find(_blank(_part(parts, "private_helpers")))
        if name == "private_helpers"
        else content.find("function " + name + "(")
    )
    if header < 0:
        return None
    position = content.find(callee + "(", header)
    if position < 0:
        position = content.find(callee, header)
    if position < 0:
        return None
    return content.count("\n", 0, position) + 1


_IDENTIFIER_USE = re.compile(r"(?<![.\w$])([A-Za-z_$][\w$]*)")


def _scopes(parts):
    helpers = _blank(_part(parts, "private_helpers"))
    if helpers.strip():
        yield "private_helpers", helpers, ", ".join(_HELPER_PARAMETERS.findall(helpers))
    for function in _part(parts, "functions"):
        yield (
            _part(function, "name"),
            _blank(_part(function, "body")),
            _part(function, "parameters"),
        )


def validate_core_calls(parts):
    functions = _part(parts, "functions")
    browser_names = set(_DECLARED.findall(_blank(_part(parts, "browser_setup"))))
    module_names = (
        {_part(declaration, "name") for declaration in _part(parts, "shared_state")}
        | set(_DECLARED.findall(_blank(_part(parts, "private_helpers"))))
        | {_part(function, "name") for function in functions}
    )
    offences = []
    first_line = None
    for name, body, parameters in _scopes(parts):
        local = set(_DECLARED.findall(body)) | set(_PARAMETER.findall(parameters))
        called = set(_CALL.findall(body))
        used = set(_IDENTIFIER_USE.findall(body)) - called - set(_OBJECT_KEY.findall(body))
        excluded = module_names | local
        calls = sorted(item for item in called if item in browser_names and item not in excluded)
        uses = sorted(item for item in used if item in browser_names and item not in excluded)
        if calls:
            offences.append(name + " calls " + ", ".join(calls))
        if uses:
            offences.append(name + " uses " + ", ".join(uses))
        if (calls or uses) and first_line is None:
            first_line = _call_line(parts, name, (calls or uses)[0])
    if offences:
        raise SourceSyntaxError(
            reason="MODULE_FUNCTION_CALLS_BROWSER_HELPER",
            line=first_line,
            parser=PARSER,
            detail="; ".join(offences),
        )


_JS_KEYWORDS = frozenset(
    {
        "async",
        "await",
        "break",
        "case",
        "catch",
        "class",
        "const",
        "continue",
        "default",
        "delete",
        "do",
        "else",
        "export",
        "finally",
        "for",
        "function",
        "get",
        "if",
        "import",
        "in",
        "instanceof",
        "let",
        "new",
        "of",
        "return",
        "set",
        "static",
        "super",
        "switch",
        "this",
        "throw",
        "try",
        "typeof",
        "var",
        "void",
        "while",
        "with",
        "yield",
    }
)
_JS_CALLABLES = frozenset(
    {
        "AbortController",
        "Array",
        "ArrayBuffer",
        "BigInt",
        "Blob",
        "Boolean",
        "CustomEvent",
        "DataView",
        "Date",
        "Error",
        "EvalError",
        "Event",
        "Float64Array",
        "FormData",
        "Function",
        "Headers",
        "Int32Array",
        "Intl",
        "JSON",
        "Map",
        "Math",
        "Number",
        "Object",
        "Promise",
        "Proxy",
        "RangeError",
        "ReferenceError",
        "Reflect",
        "RegExp",
        "Request",
        "Response",
        "Set",
        "String",
        "Symbol",
        "SyntaxError",
        "TextDecoder",
        "TextEncoder",
        "TypeError",
        "URIError",
        "URL",
        "URLSearchParams",
        "Uint8Array",
        "WeakMap",
        "WeakSet",
        "clearInterval",
        "clearTimeout",
        "decodeURI",
        "decodeURIComponent",
        "encodeURI",
        "encodeURIComponent",
        "escape",
        "eval",
        "isFinite",
        "isNaN",
        "parseFloat",
        "parseInt",
        "queueMicrotask",
        "require",
        "setInterval",
        "setTimeout",
        "structuredClone",
        "unescape",
    }
)
_CLASS_NAME = re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)")
_NESTED_PARAMETERS = re.compile(
    r"function\s*[A-Za-z_$]?[\w$]*\s*\(([^)]*)\)|\(([^()]*)\)\s*=>|([A-Za-z_$][\w$]*)\s*=>"
)
_DEFINITION = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\([^()]*\)\s*\{")


def validate_defined_calls(parts):
    browser_names = set(_DECLARED.findall(_blank(_part(parts, "browser_setup"))))
    helpers = _blank(_part(parts, "private_helpers"))
    module_names = (
        {_part(declaration, "name") for declaration in _part(parts, "shared_state")}
        | set(_DECLARED.findall(helpers))
        | set(_CLASS_NAME.findall(helpers))
        | {_part(function, "name") for function in _part(parts, "functions")}
        | {RESET_FUNCTION}
    )
    offences = []
    first_line = None
    for name, body, parameters in _scopes(parts):
        local = (
            set(_DECLARED.findall(body))
            | set(_CLASS_NAME.findall(body))
            | set(_DEFINITION.findall(body))
            | set(_PARAMETER.findall(parameters))
        )
        for match in _NESTED_PARAMETERS.finditer(body):
            local.update(_PARAMETER.findall("".join(group or "" for group in match.groups())))
        known = module_names | local | browser_names | _JS_KEYWORDS | _JS_CALLABLES
        unknown = sorted(item for item in set(_CALL.findall(body)) if item not in known)
        if unknown:
            offences.append(name + " calls " + ", ".join(unknown))
            if first_line is None:
                first_line = _call_line(parts, name, unknown[0])
    if offences:
        raise SourceSyntaxError(
            reason="MODULE_FUNCTION_CALLS_UNDEFINED_FUNCTION",
            line=first_line,
            parser=PARSER,
            detail="; ".join(offences),
        )


def validate_shared_state_updates(shared_state, bodies):
    blanked_bodies = _blank(bodies)
    for declaration in shared_state:
        name = _part(declaration, "name")
        mutable = (
            _part(declaration, "kind") == "let"
            or _part(declaration, "initializer") in _MUTABLE_INITIALIZERS
        )
        if mutable and _mutation(name).search(blanked_bodies) is None:
            raise SourceSyntaxError(reason="SHARED_STATE_NEVER_UPDATED", parser=PARSER, detail=name)


_TEST_DOM = re.compile(
    r"\b(document|window|globalThis|localStorage|sessionStorage|navigator|fetch|XMLHttpRequest|jsdom|JSDOM)\b"
)
_TEST_REQUIRE = re.compile(r"require\(\s*['\"]\./app\.js['\"]\s*\)")
_TEST_FRAMEWORK = re.compile(r"require\(\s*['\"]node:test['\"]\s*\)")
_TEST_ASSERTION = re.compile(r"\bassert\.([A-Za-z_$][\w$]*)\s*\(")
_TEST_STATE_RESET = re.compile(r"\bbeforeEach\s*\([^;]*?\b" + RESET_FUNCTION + r"\b")
NODE_ASSERTIONS = frozenset(
    {
        "ok",
        "equal",
        "notEqual",
        "deepEqual",
        "notDeepEqual",
        "strictEqual",
        "notStrictEqual",
        "deepStrictEqual",
        "notDeepStrictEqual",
        "throws",
        "doesNotThrow",
        "rejects",
        "doesNotReject",
        "match",
        "doesNotMatch",
        "fail",
        "ifError",
        "partialDeepStrictEqual",
    }
)


_TEST_DESTRUCTURE = re.compile(
    r"\b(?:const|let|var)\s*\{([^}]*)\}\s*=\s*require\(\s*['\"]\./app\.js['\"]\s*\)"
)
_TEST_ALIAS = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*require\(\s*['\"]\./app\.js['\"]\s*\)"
    r"(?!\s*\.)"
)
_TEST_MEMBER = re.compile(r"require\(\s*['\"]\./app\.js['\"]\s*\)\s*\.\s*([A-Za-z_$][\w$]*)")


def _test_module_names(content, blanked):
    names = set()
    for match in _TEST_DESTRUCTURE.finditer(content):
        for entry in match.group(1).split(","):
            entry = entry.split("=", 1)[0].split(":", 1)[0].strip()
            if entry and not entry.startswith("...") and _IDENTIFIER.fullmatch(entry):
                names.add(entry)
    names.update(_TEST_MEMBER.findall(content))
    for alias in _TEST_ALIAS.findall(content):
        names.update(re.findall(r"\b" + re.escape(alias) + r"\s*\.\s*([A-Za-z_$][\w$]*)", blanked))
    return names


def validate_node_test_contract(content, *, stateful=False, exports=None):
    blanked = _blank(content)
    if _TEST_FRAMEWORK.search(content) is None:
        raise SourceSyntaxError(reason="NODE_TEST_FRAMEWORK_MISSING", parser=PARSER)
    if _TEST_REQUIRE.search(content) is None:
        raise SourceSyntaxError(reason="NODE_TEST_DOES_NOT_LOAD_MODULE", parser=PARSER)
    match = _TEST_DOM.search(blanked)
    if match is not None:
        raise SourceSyntaxError(
            reason="NODE_TEST_REFERENCES_DOM",
            line=blanked.count("\n", 0, match.start()) + 1,
            parser=PARSER,
        )
    if stateful and _TEST_STATE_RESET.search(blanked) is None:
        raise SourceSyntaxError(
            reason="NODE_TEST_MISSING_STATE_RESET", parser=PARSER, detail=RESET_FUNCTION
        )
    if exports is not None:
        unknown = sorted(_test_module_names(content, blanked) - set(exports))
        if unknown:
            raise SourceSyntaxError(
                reason="NODE_TEST_USES_UNEXPORTED_NAME",
                parser=PARSER,
                detail=", ".join(unknown),
            )
    for call in _TEST_ASSERTION.finditer(blanked):
        if call.group(1) not in NODE_ASSERTIONS:
            raise SourceSyntaxError(
                reason="NODE_TEST_UNKNOWN_ASSERTION",
                line=blanked.count("\n", 0, call.start()) + 1,
                parser=PARSER,
            )
