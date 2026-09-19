import shutil
from types import SimpleNamespace

import pytest

from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.source_syntax import validate_source_syntax


def source(path, content):
    return SimpleNamespace(normalized_path=path, content=content)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node parser not installed")
def test_rejects_truncated_test_and_inline_script_without_executing_code(tmp_path):
    marker = tmp_path / "must-not-exist"
    validate_source_syntax(
        source(
            "app.test.cjs",
            f"require('node:fs').writeFileSync({str(marker).replace(chr(92), '/')!r}, 'executed');",
        )
    )
    assert not marker.exists()
    for path, content in [
        ("app.test.cjs", "assert.strictEqual(result.error, \\"),
        ("index.html", "<script>const a = ;</script>"),
    ]:
        with pytest.raises(ProposalGenerationError, match="SOURCE_JAVASCRIPT_SYNTAX_INVALID"):
            validate_source_syntax(source(path, content))


@pytest.mark.skipif(shutil.which("node") is None, reason="Node parser not installed")
def test_module_scripts_and_json_metadata_are_parsed_in_their_correct_mode(monkeypatch):
    monkeypatch.setenv("NODE_OPTIONS", "--require=nonexistent-preload")
    validate_source_syntax(source("module.mjs", "export const n = 1;"))
    validate_source_syntax(
        source(
            "index.html",
            '<script type="module">export const n = 1;</script><script type="application/ld+json">{"a":1}</script>',
        )
    )


def test_parser_absence_is_explicit_not_a_silent_acceptance(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(ProposalGenerationError, match="SOURCE_JAVASCRIPT_PARSER_UNAVAILABLE"):
        validate_source_syntax(source("app.js", "const a = 1;"))
