"""Real llguidance 1.8.0 masks on CPU, using a synthetic byte vocabulary only.

Runnable with stdlib unittest in the existing model environment; no pytest,
model, Hugging Face tokenizer, network, or GPU is needed.
"""

import json
import unittest
from importlib.metadata import version
from typing import ClassVar

from orchestwin.models import schema_decoding

try:
    import llguidance
except ImportError:
    llguidance = None


class _ByteVocabulary:
    tokens: ClassVar[list[bytes]] = [bytes([i]) for i in range(256)] + [
        b"<eos>",
        b" " * 8,
        b" " * 9,
    ]
    eos_token_id = 256
    bos_token_id = None
    special_token_ids: ClassVar[list[int]] = [256]

    def __call__(self, text):
        return list(text if isinstance(text, bytes) else text.encode("utf-8"))


ARRAY_SCHEMA = {
    "type": "object",
    "properties": {"a": {"type": "array", "items": {"type": "integer"}}},
    "required": ["a"],
    "additionalProperties": False,
}


@unittest.skipIf(llguidance is None, "optional native llguidance is not installed")
class NativeSchemaWhitespaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if version("llguidance") != schema_decoding.VERSION:
            raise RuntimeError("native decoder test requires pinned llguidance 1.8.0")
        cls.vocabulary = llguidance.LLTokenizer(
            llguidance.TokenizerWrapper(_ByteVocabulary()), slices=[]
        )

    def matcher(self, schema=ARRAY_SCHEMA):
        grammar = schema_decoding._schema_grammar(
            schema, llguidance.LLMatcher.grammar_from_json_schema
        )
        result = llguidance.LLMatcher(self.vocabulary, grammar)
        self.assertFalse(result.is_error(), result.get_error())
        return result

    def allowed(self, matcher, token):
        bits = matcher.compute_bitmask()
        return bool(bits[token // 8] & (1 << (token % 8)))

    def consume(self, matcher, content):
        for token in content:
            self.assertTrue(self.allowed(matcher, token), (token, matcher.get_error()))
            self.assertTrue(matcher.consume_token(token))

    def test_incomplete_array_prefix_masks_ninth_structural_whitespace(self):
        for prefix in (b'{"a":', b'{"a":[', b'{"a":[1,', b'{"a":[1]'):
            for whitespace in (b" " * 8, b"\n" * 8, b" \t\r\n" * 2):
                with self.subTest(prefix=prefix, whitespace=whitespace):
                    matcher = self.matcher()
                    self.consume(matcher, prefix + whitespace)
                    for token in b" \t\r\n":
                        self.assertFalse(self.allowed(matcher, token))
                    self.assertFalse(self.allowed(matcher, _ByteVocabulary.eos_token_id))
                    if prefix.endswith(b"]"):
                        self.assertTrue(self.allowed(matcher, ord("}")))

    def test_whitespace_tokens_cannot_cross_the_remaining_structural_budget(self):
        matcher = self.matcher()
        self.consume(matcher, b'{"a":[1]')
        self.assertTrue(self.allowed(matcher, 257))  # One token with eight spaces.
        self.assertFalse(self.allowed(matcher, 258))  # One token with nine spaces.
        self.consume(matcher, b" " * 4)
        self.assertFalse(self.allowed(matcher, 257))
        self.assertFalse(self.allowed(matcher, 258))
        self.consume(matcher, b" " * 4 + b"}")
        self.assertTrue(self.allowed(matcher, _ByteVocabulary.eos_token_id))
        self.assertTrue(matcher.consume_token(_ByteVocabulary.eos_token_id))
        self.assertTrue(matcher.is_stopped())

    def test_string_content_keeps_long_whitespace_and_escaped_controls(self):
        schema = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        }
        matcher = self.matcher(schema)
        self.consume(matcher, b'{"text":"')
        for _ in range(16):
            self.assertTrue(self.allowed(matcher, 258))
            self.assertTrue(matcher.consume_token(258))
        self.consume(matcher, b"\\n\\t\\r" + "è".encode() + b'"}')
        self.assertTrue(self.allowed(matcher, _ByteVocabulary.eos_token_id))
        self.assertTrue(matcher.consume_token(_ByteVocabulary.eos_token_id))

    def test_nested_objects_arrays_and_pretty_json_remain_valid(self):
        schema = {
            "type": "object",
            "properties": {
                "nested": {
                    "type": "object",
                    "properties": {
                        "flags": {"type": "array", "items": {"type": "boolean"}},
                        "title": {"type": "string"},
                    },
                    "required": ["flags", "title"],
                    "additionalProperties": False,
                }
            },
            "required": ["nested"],
            "additionalProperties": False,
        }
        document = {"nested": {"flags": [True, False], "title": "    spaced    "}}
        for content in (
            json.dumps(document, indent=2),
            json.dumps(document, separators=(",", ":")),
        ):
            with self.subTest(content=content):
                matcher = self.matcher(schema)
                self.consume(matcher, content.encode())
                self.assertTrue(matcher.is_accepting())
                self.assertTrue(self.allowed(matcher, _ByteVocabulary.eos_token_id))

    def test_incomplete_json_eos_is_rejected_without_repair(self):
        for prefix in (b'{"a":', b'{"a":[1', b'{"a":[1]' + b" " * 8):
            with self.subTest(prefix=prefix):
                matcher = self.matcher()
                self.consume(matcher, prefix)
                self.assertFalse(self.allowed(matcher, _ByteVocabulary.eos_token_id))
                self.assertFalse(matcher.consume_token(_ByteVocabulary.eos_token_id))

    def test_schema_cannot_override_the_structural_whitespace_limit(self):
        schema = {**ARRAY_SCHEMA, "x-guidance": {"whitespace_pattern": r"\s+"}}
        matcher = self.matcher(schema)
        self.consume(matcher, b'{"a":[1]' + b" " * 8)
        self.assertFalse(self.allowed(matcher, ord(" ")))
        self.assertTrue(self.allowed(matcher, ord("}")))

    def test_previous_default_reproduces_the_unbounded_whitespace_regression(self):
        grammar = llguidance.LLMatcher.grammar_from_json_schema(ARRAY_SCHEMA)
        matcher = llguidance.LLMatcher(self.vocabulary, grammar)
        self.consume(matcher, b'{"a":[1]' + b" " * 64)
        self.assertTrue(self.allowed(matcher, ord(" ")))
        self.assertFalse(self.allowed(matcher, _ByteVocabulary.eos_token_id))


if __name__ == "__main__":
    unittest.main()
