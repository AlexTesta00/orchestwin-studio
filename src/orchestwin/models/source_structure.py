import re

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
