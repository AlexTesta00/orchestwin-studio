"""Parse JavaScript without executing generated code or declaring tests passed."""

import os
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import PurePosixPath

from orchestwin.models.proposal_generation import ProposalGenerationError


class SourceSyntaxError(ProposalGenerationError):
    """A bounded parser diagnostic without generated text or process stderr."""

    def __init__(self, *, reason, module=False, line=None, parser="node --check", detail=None):
        super().__init__("SOURCE_JAVASCRIPT_SYNTAX_INVALID")
        self.diagnostic = {
            "parser": parser,
            "input_type": "module" if module else "commonjs",
            "reason": reason,
            "line": line,
            **({"detail": detail} if detail else {}),
        }


_REDECLARED = re.compile(r"SyntaxError: Identifier '([^']+)' has already been declared")


def _syntax_diagnostic(stderr, *, module):
    text = stderr.decode("utf-8", errors="replace")
    reasons = {
        "Unexpected token 'export'": "ES_MODULE_EXPORT_IN_CLASSIC_SCRIPT",
        "Cannot use import statement outside a module": "ES_MODULE_IMPORT_IN_CLASSIC_SCRIPT",
        "Unexpected end of input": "UNEXPECTED_END_OF_INPUT",
        "Invalid or unexpected token": "INVALID_OR_UNEXPECTED_TOKEN",
    }
    messages = set(text.splitlines())
    reason = next(
        (code for message, code in reasons.items() if "SyntaxError: " + message in messages),
        "JAVASCRIPT_PARSE_ERROR",
    )
    if module and reason.startswith("ES_MODULE_"):
        reason = "JAVASCRIPT_PARSE_ERROR"
    redeclared = _REDECLARED.search(text)
    if redeclared:
        reason = "IDENTIFIER_ALREADY_DECLARED"
    position = re.search(r"^\[stdin\]:(\d+)\s*$", text, re.MULTILINE)
    return SourceSyntaxError(
        reason=reason,
        module=module,
        line=int(position[1]) if position else None,
        detail=redeclared.group(1) if redeclared else None,
    )


class _InlineScripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts = []
        self.current = None
        self.module = False

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        attributes = dict(attrs)
        kind = attributes.get("type", "") or ""
        if "src" not in attributes and kind in {
            "",
            "module",
            "text/javascript",
            "application/javascript",
        }:
            self.current = []
            self.module = kind == "module"

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.scripts.append(("".join(self.current), self.module))
            self.current = None


def validate_source_syntax(item):
    """Fail closed when a JavaScript parser is missing; never run generated code.

    Node reads stdin in explicit syntax-check mode. NODE_OPTIONS/NODE_PATH are
    removed so inherited preload settings cannot turn parsing into execution.
    This is a syntax check only, not a test run or Level D qualification.
    """
    suffix = PurePosixPath(item.normalized_path).suffix.lower()
    scripts = []
    if suffix in {".js", ".cjs", ".mjs"}:
        scripts = [(item.content, suffix == ".mjs")]
    elif suffix == ".html":
        parser = _InlineScripts()
        parser.feed(item.content)
        if parser.current is not None:
            raise SourceSyntaxError(reason="UNCLOSED_INLINE_SCRIPT", parser="html.parser")
        scripts = parser.scripts
    if not scripts:
        return
    node = shutil.which("node")
    if node is None:
        raise ProposalGenerationError("SOURCE_JAVASCRIPT_PARSER_UNAVAILABLE")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in {"NODE_OPTIONS", "NODE_PATH"}
    }
    for source, module in scripts:
        try:
            result = subprocess.run(
                [node, "--check", "--input-type=" + ("module" if module else "commonjs")],
                input=source.encode("utf-8"),
                capture_output=True,
                timeout=10,
                env=environment,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ProposalGenerationError("SOURCE_JAVASCRIPT_PARSER_UNAVAILABLE") from error
        if result.returncode != 0:
            raise _syntax_diagnostic(result.stderr, module=module)
