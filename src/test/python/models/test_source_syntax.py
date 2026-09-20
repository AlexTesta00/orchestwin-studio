import shutil
from types import SimpleNamespace

import pytest

from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.source_syntax import (
    SourceSyntaxError,
    _syntax_diagnostic,
    validate_source_syntax,
)


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


@pytest.mark.skipif(shutil.which("node") is None, reason="Node parser not installed")
@pytest.mark.parametrize(
    "declaration, reason",
    [
        ("export const value = 1;", "ES_MODULE_EXPORT_IN_CLASSIC_SCRIPT"),
        ("import value from './value.js';", "ES_MODULE_IMPORT_IN_CLASSIC_SCRIPT"),
    ],
)
def test_classic_script_module_mismatch_has_actual_bounded_parser_feedback(declaration, reason):
    content = "// Header\n\n" + declaration
    with pytest.raises(SourceSyntaxError) as caught:
        validate_source_syntax(source("app.js", content))
    assert caught.value.diagnostic == {
        "parser": "node --check",
        "input_type": "commonjs",
        "reason": reason,
        "line": 3,
    }
    # The same unmodified source is syntactically valid under a different mode.
    # --check neither resolves the import nor executes the generated module.
    validate_source_syntax(source("module.mjs", content))


def test_safe_diagnostic_does_not_retain_stderr_source_or_paths():
    error = _syntax_diagnostic(
        b"[stdin]:8\nthrow SECRET; // SyntaxError: Unexpected token 'export'\n^\n"
        b"SyntaxError: Unexpected identifier 'SECRET'\n at /private/runtime.js:4\n",
        module=False,
    )
    assert error.diagnostic == {
        "parser": "node --check",
        "input_type": "commonjs",
        "reason": "JAVASCRIPT_PARSE_ERROR",
        "line": 8,
    }
    assert "SECRET" not in repr(error.diagnostic) and "/private" not in repr(error.diagnostic)
