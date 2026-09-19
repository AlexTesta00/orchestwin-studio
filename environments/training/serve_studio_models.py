#!/usr/bin/env python3
"""Offline local demo: a shared frozen base, separate proposal and evaluator identities."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import serve_proposal_model as serving
from evaluator_candidate_worker import inference_model, verify_adapter
from studio_inference_memory import configure_interactive_generation

from orchestwin.models.structured_generation import ModelRuntimeIdentity
from orchestwin.projects.requirements_primitives import snapshot_content_hash


def public_path(path):
    """Write paths usable by the native Windows API when inference runs in WSL."""
    value = str(path)
    if value.startswith("/mnt/") and len(value) > 7 and value[6] == "/":
        return value[5].upper() + ":/" + value[7:]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--weights-sha256", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--proposal-port", type=int, default=8787)
    parser.add_argument("--evaluator-port", type=int, default=8788)
    args = parser.parse_args()
    hashes = verify_adapter(args.adapter, args.weights_sha256, args.config_sha256)
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", WANDB_DISABLED="true")
    # Long prefill and paged decode interleave large temporary allocations with
    # persistent KV buffers. Use CUDA's stream-ordered pool to avoid native
    # allocator fragmentation; expandable segments are unavailable on WSL.
    os.environ.setdefault("PYTORCH_ALLOC_CONF", "backend:cudaMallocAsync")
    os.chdir(serving.ROOT / "environments/training")
    # Profile batches include the complete schema and their immutable provenance.
    # This interactive limit is separate from the frozen qualification server.
    serving.MAX_SEQUENCE = 24576
    print("Loading cached base and verified evaluator adapter; inference only.", flush=True)
    torch, base, tokenizer, evidence = serving.load_model()
    from peft import PeftModel
    from unsloth import FastLanguageModel
    from unsloth.models.llama import KV_CACHE_INCREMENT

    model = inference_model(
        base,
        args.adapter,
        load_adapter=PeftModel.from_pretrained,
        prepare_inference=FastLanguageModel.for_inference,
    )
    configure_interactive_generation(torch, model, cache_increment=KV_CACHE_INCREMENT)
    processor = serving.build_schema_processor_factory(tokenizer, torch, model.config.vocab_size)
    lock = threading.BoundedSemaphore(1)
    token = secrets.token_urlsafe(48)
    token_path = output / "access-token.secret"
    token_path.write_text(token, encoding="ascii")
    token_path.chmod(0o600)
    run_id = str(uuid4())
    servers = []
    for role, port in (("proposal", args.proposal_port), ("evaluator", args.evaluator_port)):
        adapted = role == "evaluator"
        configuration = {
            "role": role,
            "run_id": run_id,
            "loader": evidence,
            "adapter_files": hashes if adapted else {},
            "server_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "memory_helper_sha256": hashlib.sha256(
                Path(__file__).with_name("studio_inference_memory.py").read_bytes()
            ).hexdigest(),
            "generation_sha256": hashlib.sha256(Path(serving.__file__).read_bytes()).hexdigest(),
            "model": serving.MODEL,
            "revision": serving.REVISION,
            "max_sequence": serving.MAX_SEQUENCE,
            "max_output": 2048 if adapted else serving.MAX_OUTPUT,
            "max_generation_seconds": 1140,
            "memory_policy": "REQUEST_BOUNDED_LAYER_KV_REUSE_V6",
            "cuda_allocator": os.environ["PYTORCH_ALLOC_CONF"],
            "training_executed": False,
        }
        identity = ModelRuntimeIdentity(
            provider_id="local-studio-model",
            runtime_id=f"{role}-{run_id}",
            base_model_repository=serving.MODEL,
            base_model_revision=serving.REVISION,
            tokenizer_revision=serving.REVISION,
            configuration_sha256=snapshot_content_hash(configuration),
            adapter_id="interactive-evaluator-" + args.weights_sha256[:16] if adapted else None,
            adapter_sha256=snapshot_content_hash(hashes) if adapted else None,
        )
        state = dict(
            torch=torch,
            model=model,
            tokenizer=tokenizer,
            schema_processor=processor,
            identity=identity,
            model_name=f"orchestwin-{role}",
            slot=lock,
            completed_generation_count=0,
            max_generation_seconds=configuration["max_generation_seconds"],
            shared_adapter_loaded=True,
            evaluator=adapted,
            supported_tasks=["user-twin-evaluation"] if adapted else sorted(serving.TASKS),
        )
        server = ThreadingHTTPServer(("127.0.0.1", port), serving.handler_for(state, token))
        server.daemon_threads = True
        servers.append(server)
        runtime = dict(
            schema_version=1,
            base_url=f"http://127.0.0.1:{server.server_port}",
            model_name=state["model_name"],
            identity=identity.to_snapshot(),
            token_file=public_path(token_path),
            temperature=0.0 if adapted else 0.6,
            max_output_tokens=configuration["max_output"],
            timeout_seconds=1200,
        )
        (output / f"{role}.json").write_text(json.dumps(runtime, indent=2), encoding="utf-8")
        (output / f"{role}-loader.json").write_text(
            json.dumps(configuration, indent=2), encoding="utf-8"
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
    (output / "models.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "proposal_config_file": public_path(output / "proposal.json"),
                "final_evaluator_config_file": public_path(output / "evaluator.json"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("STUDIO_MODELS_READY", flush=True)
    try:
        stopped = threading.Event()
        while not (output / "stop.request").exists():
            stopped.wait(1)
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
