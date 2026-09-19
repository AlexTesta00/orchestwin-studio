"""Parse JavaScript without executing generated code or declaring tests passed."""

import os
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import PurePosixPath

from orchestwin.models.proposal_generation import ProposalGenerationError


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
            raise ProposalGenerationError("SOURCE_JAVASCRIPT_SYNTAX_INVALID")
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
            raise ProposalGenerationError("SOURCE_JAVASCRIPT_SYNTAX_INVALID")
