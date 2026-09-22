import re

from orchestwin.models.source_assembly import assemble_static_module
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
            if _DOM.search(statement):
                raise SourceSyntaxError(
                    reason="MODULE_FUNCTION_TOUCHES_DOM",
                    line=line,
                    parser=PARSER,
                    detail=function.group(2),
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


_CALL = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
_DECLARED = re.compile(r"\b(?:function\s+|const\s+|let\s+|var\s+)([A-Za-z_$][\w$]*)")
_PARAMETER = re.compile(r"[A-Za-z_$][\w$]*")


def _part(value, key):
    return value[key] if isinstance(value, dict) else getattr(value, key)


_NESTED_READY = re.compile(r"DOMContentLoaded|addEventListener\(\s*['\"]load['\"]|\.onload\s*=")


def validate_browser_setup(parts):
    browser_setup = _part(parts, "browser_setup")
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
    header = content.find("function " + name + "(")
    if header < 0:
        return None
    position = content.find(callee + "(", header)
    if position < 0:
        position = content.find(callee, header)
    if position < 0:
        return None
    return content.count("\n", 0, position) + 1


_IDENTIFIER_USE = re.compile(r"\b([A-Za-z_$][\w$]*)\b")


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
    for function in functions:
        name = _part(function, "name")
        body = _blank(_part(function, "body"))
        local = set(_DECLARED.findall(body)) | set(
            _PARAMETER.findall(_part(function, "parameters"))
        )
        called = set(_CALL.findall(body))
        used = set(_IDENTIFIER_USE.findall(body)) - called
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


def validate_node_test_contract(content):
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
    for call in _TEST_ASSERTION.finditer(blanked):
        if call.group(1) not in NODE_ASSERTIONS:
            raise SourceSyntaxError(
                reason="NODE_TEST_UNKNOWN_ASSERTION",
                line=blanked.count("\n", 0, call.start()) + 1,
                parser=PARSER,
            )
