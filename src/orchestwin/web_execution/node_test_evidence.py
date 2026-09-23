"""Read the Node TAP summary; exit zero alone does not prove a test ran."""

import re
from collections.abc import Iterator

from orchestwin.web_execution.reports import WebNormalizedFinding

PARSER_ID = "node.test.tap.v1"


_TAP_RESULT = re.compile(r"^( *)not ok [0-9]+ - (.+)$")
_TAP_FIELD = re.compile(r"^([A-Za-z_]+):(?: (.*))?$")
_TAP_BLOCK_MARKERS = frozenset({None, "|", "|-", ">", ">-"})
_WORKSPACE_PATH = re.compile(r"/workspace/([A-Za-z0-9_./-]+:[0-9]+(?::[0-9]+)?)")
_ERROR_CLASS = re.compile(r"[A-Za-z]*Error")
MAX_FINDINGS = 8


def failure_findings(stdout: bytes, stderr: bytes) -> tuple[WebNormalizedFinding, ...]:
    """Retain a bounded diagnostic for repair; complete original streams stay in evidence."""
    text = (stdout + b"\n" + stderr).decode("utf-8", errors="replace")
    found = list(_tap_failures(text.splitlines()))
    lines = [line.removeprefix("# ") for line in text.splitlines()]
    for index, line in enumerate(lines):
        if len(found) >= MAX_FINDINGS:
            break
        match = re.match(
            r"(ReferenceError|SyntaxError|TypeError|RangeError|AssertionError)(?: \[[A-Z0-9_]+\])?: (.+)",
            line,
        )
        if match:
            message = " ".join(line.split())[:1000].strip()
            found.append(
                WebNormalizedFinding(
                    "NODE_TEST_" + match.group(1).upper(),
                    message,
                    "node:test",
                    _error_location(lines, index),
                )
            )
    if not found:
        match = re.search(r"^\s+error: ['\"]?([^\n]+)", text, re.MULTILINE)
        if match and match.group(1).strip(" '\"") not in {"test failed", "|", "|-"}:
            found.append(
                WebNormalizedFinding(
                    "NODE_TEST_FAILURE",
                    " ".join(match.group(1).strip(" '\"").split())[:1000].strip(),
                    "node:test",
                    None,
                )
            )
    return tuple(
        sorted(
            set(found),
            key=lambda item: (item.code, item.message, item.source_tool, item.location or ""),
        )
    )


def _tap_failures(lines: list[str]) -> Iterator[WebNormalizedFinding]:
    count = 0
    for index, line in enumerate(lines):
        match = _TAP_RESULT.match(line)
        if not match:
            continue
        prefix = match[1] + "  "
        if index + 1 == len(lines) or lines[index + 1] != prefix + "---":
            continue
        fields = _tap_fields(lines, index + 2, prefix)
        if fields.get("failureType") == "subtestsFailed":
            continue
        name = re.sub(r" # (SKIP|TODO).*$", "", match[2], flags=re.IGNORECASE).strip()
        error = fields.get("error", "")
        message = " ".join((f"{name}: {error}" if error else f"{name} failed").split())
        kind = fields.get("name", "")
        location = _WORKSPACE_PATH.search(fields.get("stack", "")) or _WORKSPACE_PATH.search(
            fields.get("location", "")
        )
        yield WebNormalizedFinding(
            "NODE_TEST_" + kind.upper() if _ERROR_CLASS.fullmatch(kind) else "NODE_TEST_FAILURE",
            message[:1000].strip(),
            "node:test",
            None if location is None else location.group(1),
        )
        count += 1
        if count == MAX_FINDINGS:
            return


def _tap_fields(lines: list[str], start: int, prefix: str) -> dict[str, str]:
    fields: dict[str, list[str] | str] = {}
    block: list[str] | None = None
    for raw in lines[start:]:
        if raw == "" and block is not None:
            block.append("")
            continue
        if raw == prefix + "..." or not raw.startswith(prefix):
            break
        content = raw[len(prefix) :]
        if block is not None and content.startswith("  "):
            block.append(content[2:])
            continue
        block = None
        field = _TAP_FIELD.match(content)
        if not field:
            continue
        key, value = field[1], field[2]
        if key in fields:
            if value in _TAP_BLOCK_MARKERS:
                block = []
            continue
        if value in _TAP_BLOCK_MARKERS:
            block = []
            fields[key] = block
        else:
            fields[key] = _tap_scalar(value)
    return {
        key: " ".join(" ".join(value).split()) if isinstance(value, list) else value
        for key, value in fields.items()
    }


def _tap_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def _error_location(lines: list[str], index: int) -> str | None:
    path = r"/workspace/([A-Za-z0-9_./-]+:[0-9]+(?::[0-9]+)?)"
    # A V8 source excerpt precedes its error by at most three lines. Otherwise
    # use that error's immediate stack, not the first path in another test's log.
    for line in reversed(lines[max(0, index - 3) : index]):
        if match := re.fullmatch(path, line):
            return match.group(1)
    for line in lines[index + 1 : index + 7]:
        if not line.lstrip().startswith("at "):
            break
        if match := re.search(path, line):
            return match.group(1)
    return None


def _passing_test_names(stdout: bytes) -> Iterator[str]:
    """Read passing leaf records from the pinned Node TAP reporter."""
    lines = stdout.decode("utf-8", errors="replace").splitlines()
    for index, line in enumerate(lines):
        match = re.fullmatch(r"( *)ok [0-9]+ - (.+)", line)
        if not match or re.search(r" # (SKIP|TODO)(?:\s|$)", match[2], re.IGNORECASE):
            continue
        prefix = match[1] + "  "
        if index + 1 == len(lines) or lines[index + 1] != prefix + "---":
            continue
        is_test = False
        for diagnostic_index in range(index + 2, len(lines)):
            diagnostic = lines[diagnostic_index]
            if diagnostic == prefix + "...":
                if is_test:
                    yield match[2].strip()
                break
            if not diagnostic.startswith(prefix):
                break
            if diagnostic == prefix + "type: 'test'":
                is_test = True


def has_executed_passing_tests(stdout: bytes, test_paths: tuple[str, ...] = ()) -> bool:
    # Node reports an empty file itself as one passing test. Require a passing
    # leaf test beyond those automatic file entries; keep the original TAP too.
    paths = tuple(path.removeprefix("./") for path in test_paths)
    if not any(
        not any(name == path or name.endswith("/" + path) for path in paths)
        for name in _passing_test_names(stdout)
    ):
        return False
    counts = {
        key.decode("ascii"): int(value)
        for key, value in re.findall(
            rb"^# (tests|pass|fail|cancelled|skipped|todo) ([0-9]{1,9})\r?$",
            stdout,
            re.MULTILINE,
        )
    }
    if set(counts) != {"tests", "pass", "fail", "cancelled", "skipped", "todo"}:
        return False
    return (
        counts["pass"] > 0
        and counts["fail"] == counts["cancelled"] == 0
        and counts["tests"]
        == sum(counts[key] for key in ("pass", "fail", "cancelled", "skipped", "todo"))
    )
