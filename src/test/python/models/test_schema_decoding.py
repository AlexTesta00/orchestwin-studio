"""Optional decoder contract without loading model or tensor dependencies."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from orchestwin.models import schema_decoding


class TokenSequence:
    def __init__(self, tokens):
        self.tokens = tokens
        self.shape = (1, len(tokens))

    def __getitem__(self, index):
        return SimpleNamespace(tolist=lambda: self.tokens[index[1]])


def factory(monkeypatch, *, rejected=False):
    matcher = Mock()
    matcher.is_error.return_value = False
    matcher.consume_token.return_value = not rejected
    matcher.consume_tokens.side_effect = AssertionError("bulk EOS API must not be used")
    matcher.is_accepting.return_value = True
    matcher.is_stopped.return_value = True
    constructor = Mock(return_value=matcher)
    constructor.grammar_from_json_schema.return_value = "grammar"
    monkeypatch.setattr(schema_decoding, "version", lambda _: "1.8.0")
    monkeypatch.setitem(sys.modules, "llguidance", SimpleNamespace(LLMatcher=constructor))
    monkeypatch.setitem(sys.modules, "llguidance.hf", SimpleNamespace(from_tokenizer=Mock()))
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace())
    return schema_decoding.build_schema_processor_factory(object(), object(), 16), matcher


def test_terminal_eos_uses_single_token_api_and_consumes_each_token_once(monkeypatch):
    create, matcher = factory(monkeypatch)
    processor = create({"type": "object"}, 2)
    processor.consume(TokenSequence([8, 9, 3]))
    assert processor.finish(TokenSequence([8, 9, 3, 2]))
    assert [call.args[0] for call in matcher.consume_token.call_args_list] == [3, 2]
    assert processor.finish(TokenSequence([8, 9, 3, 2]))
    assert matcher.consume_token.call_count == 2


def test_rejected_token_and_shortened_sequence_fail_closed(monkeypatch):
    create, _ = factory(monkeypatch, rejected=True)
    processor = create({"type": "object"}, 2)
    with pytest.raises(ValueError, match="SCHEMA_TOKEN_REJECTED"):
        processor.finish(TokenSequence([8, 9, 3]))
    with pytest.raises(ValueError, match="SCHEMA_SEQUENCE_REJECTED"):
        processor.finish(TokenSequence([8]))


def test_different_decoder_version_is_rejected_before_initialization(monkeypatch):
    monkeypatch.setattr(schema_decoding, "version", lambda _: "1.9.0")
    with pytest.raises(RuntimeError, match="pinned"):
        schema_decoding.build_schema_processor_factory(object(), object(), 16)


def test_schema_order_matches_canonical_wire_order_without_changing_the_input(monkeypatch):
    create, _ = factory(monkeypatch)
    schema = {"type": "object", "properties": {"z": {"type": "string"}, "a": {"type": "boolean"}}}
    create(schema, 2)
    compiled = sys.modules["llguidance"].LLMatcher.grammar_from_json_schema.call_args.args[0]
    assert list(compiled["properties"]) == ["a", "z"]
    assert list(schema["properties"]) == ["z", "a"]
    create({"properties": {"a": {"type": "boolean"}, "z": {"type": "string"}}, "type": "object"}, 2)
    again = sys.modules["llguidance"].LLMatcher.grammar_from_json_schema.call_args.args[0]
    assert list(again) == list(compiled)
    assert list(again["properties"]) == list(compiled["properties"])


def test_structural_whitespace_is_bounded_at_grammar_compilation(monkeypatch):
    create, _ = factory(monkeypatch)
    schema = {"type": "object", "x-guidance": {"whitespace_pattern": r"\s+"}}
    create(schema, 2)
    call = sys.modules["llguidance"].LLMatcher.grammar_from_json_schema.call_args
    assert call.kwargs["overrides"] == {
        "whitespace_flexible": True,
        "whitespace_pattern": r"[\x20\x0A\x0D\x09]{1,8}",
    }
    assert schema["x-guidance"]["whitespace_pattern"] == r"\s+"
    assert schema_decoding.POLICY == "LLGUIDANCE_JSON_SCHEMA_CANONICAL_BOUNDED_WS_V3"
