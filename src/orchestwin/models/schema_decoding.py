"""Exact JSON-schema token masking for the optional local GPU proposal server."""

from importlib.metadata import version

POLICY = "LLGUIDANCE_JSON_SCHEMA_V1"
VERSION = "1.8.0"


def build_schema_processor_factory(tokenizer, torch, vocabulary_size):
    # Optional serving dependency: importing application code never loads torch or a model.
    if version("llguidance") != VERSION:
        raise RuntimeError("pinned llguidance version required")
    import numpy as np
    from llguidance import LLMatcher
    from llguidance.hf import from_tokenizer

    vocabulary = from_tokenizer(tokenizer, n_vocab=vocabulary_size)

    class SchemaProcessor:
        def __init__(self, schema, prompt_length):
            grammar = LLMatcher.grammar_from_json_schema(schema)
            self.matcher = LLMatcher(vocabulary, grammar)
            if self.matcher.is_error():
                raise ValueError("SCHEMA_GRAMMAR_REJECTED")
            self.position = prompt_length

        def consume(self, input_ids):
            if input_ids.shape[0] != 1 or input_ids.shape[-1] < self.position:
                raise ValueError("SCHEMA_SEQUENCE_REJECTED")
            new_tokens = input_ids[0, self.position :].tolist()
            # The 1.8.0 bulk API rejects EOS after a grammar reaches NoExtension;
            # consume_token correctly accepts that terminal token.
            for token in new_tokens:
                if not self.matcher.consume_token(token):
                    raise ValueError("SCHEMA_TOKEN_REJECTED")
            self.position = input_ids.shape[-1]

        def __call__(self, input_ids, scores):
            self.consume(input_ids)
            if scores.shape != (1, vocabulary_size):
                raise ValueError("SCHEMA_VOCABULARY_MISMATCH")
            bits = np.frombuffer(self.matcher.compute_bitmask(), dtype=np.uint8)
            allowed = np.unpackbits(bits, bitorder="little")[:vocabulary_size].astype(bool)
            if self.matcher.is_error() or not allowed.any():
                raise ValueError("SCHEMA_MASK_REJECTED")
            mask = torch.from_numpy(allowed).to(device=scores.device)
            return scores.masked_fill(~mask.unsqueeze(0), float("-inf"))

        def finish(self, generated):
            self.consume(generated)
            return not self.matcher.is_error() and (
                self.matcher.is_accepting() or self.matcher.is_stopped()
            )

    return SchemaProcessor
