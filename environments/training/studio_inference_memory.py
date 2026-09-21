"""Memory bounds for the pinned interactive Qwen3/Unsloth inference runtime."""

import gc
import json
import math
import time


def release_interactive_attention_cache(model):
    """Release Qwen3/Unsloth request buffers, including views retaining their storage.

    The pinned Qwen3 attention implementation recreates these at prefill. Clear
    all layers between requests, instead of retaining the previous sequence until
    each layer of the next (potentially larger) prefill is reached.
    """
    for module in model.modules():
        if not hasattr(module, "paged_attention"):
            continue
        for name in (
            "paged_attention_K",
            "paged_attention_V",
            "paged_attention",
            "temp_QA",
            "temp_KV",
            "temp_O",
            "RH_Q",
            "attention",
        ):
            if hasattr(module, name):
                delattr(module, name)


def prepare_prefill_cache(torch, attention, cache, increment):
    """Copy one layer's exact K/V into Unsloth's decode layout during prefill.

    This matches the pinned Qwen3 decode buffer contract. Returning views into
    this storage lets the prefill tensors die layer by layer, instead of keeping
    the entire old and new caches simultaneously on the first decode step.
    """
    key, value = cache
    batch, heads, length, head_dim = key.shape
    config = attention.config
    if heads != config.num_key_value_heads or head_dim != attention.head_dim:
        raise ValueError("interactive Qwen3 cache shape mismatch")
    capacity = length + increment + 1
    options = {"dtype": key.dtype, "device": key.device}
    attention.paged_attention = torch.empty((capacity, 2, batch, heads, head_dim), **options)
    attention.paged_attention_K = attention.paged_attention[:, 0]
    attention.paged_attention_V = attention.paged_attention[:, 1]
    attention.paged_attention_K[:length].copy_(key.permute(2, 0, 1, 3))
    attention.paged_attention_V[:length].copy_(value.permute(2, 0, 1, 3))
    attention_size = config.num_attention_heads * head_dim
    attention.temp_QA = torch.empty((2, batch, 1, attention_size), **options)
    attention.temp_KV = torch.empty((2, batch, 1, heads * head_dim), **options)
    attention.RH_Q = torch.empty((batch, config.num_attention_heads, 1, head_dim), **options)
    attention.temp_O = (
        torch.empty((batch, 1, config.hidden_size), **options)
        if attention_size != config.hidden_size
        else attention.temp_QA[1][:, :, : config.hidden_size]
    )
    attention.attention = torch.empty(
        (batch, config.num_attention_heads, 1, length + increment), **options
    )
    attention.scalar = 1.0 / math.sqrt(head_dim)
    attention.half_head_dim = head_dim // 2
    return (
        attention.paged_attention_K[:length].permute(1, 2, 0, 3),
        attention.paged_attention_V[:length].permute(1, 2, 0, 3),
    )


def configure_interactive_generation(torch, model, *, cache_increment=512):
    """Bound prefill logits and release inactive CUDA allocations between requests."""
    generate = model.generate

    def bounded_generate(*args, **kwargs):
        kwargs["logits_to_keep"] = 1
        release_interactive_attention_cache(model)
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        started = time.monotonic()
        prompt_length = kwargs["input_ids"].shape[-1]
        last_report = -1
        prefill_layers = 0

        def release_layer_temporaries(layer, inputs, output):
            nonlocal prefill_layers
            if inputs and inputs[0].shape[-2] > 1:
                attention = layer.self_attn
                if getattr(getattr(attention, "config", None), "model_type", None) == "qwen3":
                    if not isinstance(output, tuple) or len(output) != 2:
                        raise ValueError(
                            "interactive Qwen3 requires cached inference without attentions"
                        )
                    output = (
                        output[0],
                        prepare_prefill_cache(
                            torch,
                            attention,
                            output[1],
                            max(cache_increment, kwargs["max_new_tokens"]),
                        ),
                    )
                torch.cuda.empty_cache()
                prefill_layers += 1
                if prefill_layers % 8 == 0:
                    print(
                        json.dumps(
                            {
                                "event": "STUDIO_PREFILL_PROGRESS",
                                "layers": prefill_layers,
                                "seconds": round(time.monotonic() - started, 2),
                                "allocated_mib": round(torch.cuda.memory_allocated() / 2**20),
                                "reserved_mib": round(torch.cuda.memory_reserved() / 2**20),
                            }
                        ),
                        flush=True,
                    )
                return output

        # Long prefill MLP/attention temporaries otherwise accumulate inactive
        # allocator blocks while the live KV cache grows through the layers.
        hooks = [
            layer.register_forward_hook(release_layer_temporaries)
            for layer in model.modules()
            if hasattr(layer, "self_attn") and hasattr(layer, "mlp")
        ]

        def progress(input_ids, scores):
            nonlocal last_report
            produced = input_ids.shape[-1] - prompt_length
            if produced < 5 or produced // 256 > last_report:
                last_report = produced // 256
                # Prefill temporaries and the first decode's replaced KV storage
                # are no longer live. Returning their allocator blocks matters on
                # WDDM/WSL: retained blocks can force active weights into host RAM.
                torch.cuda.empty_cache()
                print(
                    json.dumps(
                        {
                            "event": "STUDIO_GENERATION_PROGRESS",
                            "output_tokens": produced,
                            "seconds": round(time.monotonic() - started, 2),
                            "allocated_mib": round(torch.cuda.memory_allocated() / 2**20),
                            "reserved_mib": round(torch.cuda.memory_reserved() / 2**20),
                        }
                    ),
                    flush=True,
                )
            return scores

        kwargs["logits_processor"] = [*kwargs.get("logits_processor", []), progress]
        print(
            json.dumps(
                {
                    "event": "STUDIO_GENERATION_START",
                    "input_tokens": prompt_length,
                    "max_output_tokens": kwargs["max_new_tokens"],
                    "allocated_mib": round(torch.cuda.memory_allocated() / 2**20),
                    "reserved_mib": round(torch.cuda.memory_reserved() / 2**20),
                }
            ),
            flush=True,
        )
        try:
            return generate(*args, **kwargs)
        finally:
            for hook in hooks:
                hook.remove()
            release_interactive_attention_cache(model)
            gc.collect()
            torch.cuda.empty_cache()
            print(
                json.dumps(
                    {
                        "event": "STUDIO_GENERATION_END",
                        "seconds": round(time.monotonic() - started, 2),
                        "peak_allocated_mib": round(torch.cuda.max_memory_allocated() / 2**20),
                        "reserved_mib": round(torch.cuda.memory_reserved() / 2**20),
                    }
                ),
                flush=True,
            )

    model.generate = bounded_generate
