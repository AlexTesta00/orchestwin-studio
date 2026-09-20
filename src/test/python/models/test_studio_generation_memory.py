"""Interactive memory policy keeps sampling and failures unchanged; no GPU required."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("fails", [False, True])
def test_last_token_logits_and_cache_release_do_not_retry_or_replace_output(monkeypatch, fails):
    folder = Path(__file__).resolve().parents[4] / "environments/training"
    monkeypatch.syspath_prepend(str(folder))
    spec = importlib.util.spec_from_file_location(
        "studio_memory_test", folder / "serve_studio_models.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cuda = SimpleNamespace(
        empty_cache=Mock(),
        reset_peak_memory_stats=Mock(),
        memory_allocated=Mock(return_value=123),
        memory_reserved=Mock(return_value=456),
        max_memory_allocated=Mock(return_value=789),
    )
    result = object()
    failure = RuntimeError("model failure")
    attention = SimpleNamespace(
        paged_attention=object(), paged_attention_K=object(), temp_O=object()
    )
    hook = Mock()
    decoder = SimpleNamespace(
        self_attn=attention, mlp=object(), register_forward_hook=Mock(return_value=hook)
    )

    def run_generation(**kwargs):
        assert vars(attention) == {}
        callback = decoder.register_forward_hook.call_args.args[0]
        layer_output = object()
        assert (
            callback(decoder, [SimpleNamespace(shape=(1, 8000, 2560))], layer_output)
            is layer_output
        )
        before_decode = cuda.empty_cache.call_count
        assert callback(decoder, [SimpleNamespace(shape=(1, 1, 2560))], layer_output) is None
        assert cuda.empty_cache.call_count == before_decode
        scores = object()
        for produced in (0, 1, 2):
            tokens = SimpleNamespace(shape=(1, 8000 + produced))
            assert kwargs["logits_processor"][-1](tokens, scores) is scores
        attention.paged_attention = object()
        attention.paged_attention_V = object()
        attention.temp_O = object()
        if fails:
            raise failure
        return result

    generate = Mock(side_effect=run_generation)
    weights = object()
    layer = SimpleNamespace(weight=weights)
    model = SimpleNamespace(generate=generate, modules=lambda: [attention, layer, decoder])
    module.configure_interactive_generation(SimpleNamespace(cuda=cuda), model)
    arguments = {
        "input_ids": SimpleNamespace(shape=(1, 8000)),
        "max_new_tokens": 4096,
        "temperature": 0.6,
    }
    if fails:
        with pytest.raises(RuntimeError) as caught:
            model.generate(**arguments)
        assert caught.value is failure
    else:
        assert model.generate(**arguments) is result
    generate.assert_called_once()
    generated_arguments = dict(generate.call_args.kwargs)
    assert len(generated_arguments.pop("logits_processor")) == 1
    assert generated_arguments == {**arguments, "logits_to_keep": 1}
    assert cuda.empty_cache.call_count == 6
    hook.remove.assert_called_once()
    assert vars(attention) == {}
    assert layer.weight is weights


@pytest.mark.parametrize("batch,length,hidden", [(1, 7, 16), (2, 9, 8)])
def test_prefill_cache_preserves_exact_values_and_reuses_decode_storage(
    monkeypatch, batch, length, hidden
):
    torch = pytest.importorskip("torch")
    folder = Path(__file__).resolve().parents[4] / "environments/training"
    monkeypatch.syspath_prepend(str(folder))
    from studio_inference_memory import prepare_prefill_cache, release_interactive_attention_cache

    attention = SimpleNamespace(
        config=SimpleNamespace(num_attention_heads=4, num_key_value_heads=2, hidden_size=hidden),
        head_dim=4,
    )
    key = torch.arange(batch * 2 * length * 4, dtype=torch.float32).reshape(batch, 2, length, 4)
    value = -key
    copied_key, copied_value = prepare_prefill_cache(torch, attention, (key, value), 512)
    assert torch.equal(key, copied_key)
    assert torch.equal(value, copied_value)
    assert attention.paged_attention.shape == (length + 513, 2, batch, 2, 4)
    assert (
        copied_key.untyped_storage().data_ptr()
        == attention.paged_attention.untyped_storage().data_ptr()
    )
    assert (
        copied_value.untyped_storage().data_ptr()
        == attention.paged_attention.untyped_storage().data_ptr()
    )
    attention.paged_attention_K[length].fill_(123)
    attention.paged_attention_V[length].fill_(-123)
    assert torch.equal(key, copied_key) and torch.equal(value, copied_value)
    assert attention.temp_O.shape == (batch, 1, hidden)
    assert attention.attention.shape == (batch, 4, 1, length + 512)
    assert attention.scalar == 0.5 and attention.half_head_dim == 2
    bounded_key, bounded_value = prepare_prefill_cache(torch, attention, (key, value), 4096)
    assert attention.paged_attention.shape[0] > length + 4096
    assert attention.attention.shape[-1] >= length + 4096
    assert torch.equal(key, bounded_key) and torch.equal(value, bounded_value)
    release_interactive_attention_cache(SimpleNamespace(modules=lambda: [attention]))
    assert not hasattr(attention, "paged_attention")
