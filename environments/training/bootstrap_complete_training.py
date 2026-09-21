#!/usr/bin/env python3
"""Verify a pilot bundle, install its locked environment and run under the cloud supervisor."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from complete_training_data import digest


def verify_bundle(bundle, expected_manifest_sha256):
    bundle = Path(bundle).resolve()
    if digest(bundle / "bundle.json") != expected_manifest_sha256:
        raise ValueError("transfer manifest digest mismatch")
    manifest = json.loads((bundle / "bundle.json").read_bytes())
    for name, expected in manifest["files"].items():
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("bundle member escapes transfer directory")
        path = bundle / name
        if not path.resolve().is_relative_to(bundle) or any(
            p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(bundle)
        ):
            raise ValueError("bundle member escapes transfer directory")
        if path.stat().st_size != expected["bytes"] or digest(path) != expected["sha256"]:
            raise ValueError(f"transfer member changed: {name}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--run-directory", type=Path)
    parser.add_argument("--guard-state", type=Path)
    parser.add_argument("--hf-home", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    verify_bundle(bundle, args.manifest_sha256)
    if args.verify_only:
        print(json.dumps(dict(status="TRANSFER_VERIFIED", training=False)), flush=True)
        return
    if not all((args.run_directory, args.guard_state, args.hf_home)):
        raise ValueError("run directory, supervisor state and persistent HF cache required")
    if not os.environ.get("RUNPOD_POD_ID"):
        raise ValueError("cloud bootstrap requires the registered Runpod Pod")
    environment = bundle / "environments/training"
    uv = shutil.which("uv")
    if uv is None:
        raise ValueError("the official Runpod base must provide uv")
    os.environ["HF_HOME"] = str(args.hf_home.resolve())
    subprocess.run(
        [uv, "sync", "--project", str(environment), "--frozen", "--no-dev", "--python", "3.13"],
        check=True,
    )
    python = environment / ".venv/bin/python"
    # Download only the pinned base/tokenizer artifacts into persistent storage; no model code.
    download_environment = dict(os.environ)
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        download_environment.pop(key, None)
    subprocess.run(
        [
            str(python),
            "-c",
            "from huggingface_hub import snapshot_download; "
            "snapshot_download('Qwen/Qwen3-4B-Instruct-2507', "
            "revision='abcc171021d4f320b2e7f47c6f0deca67ded870c', "
            "allow_patterns=['*.json','*.safetensors','*.jinja','*.txt'])",
        ],
        check=True,
        env=download_environment,
    )
    command = [
        str(python),
        str(environment / "run_complete_evaluator.py"),
        "train",
        "--cache",
        str(bundle / "cache"),
        "--output",
        str(args.run_directory.resolve()),
        "--policy",
        str(environment / "complete-evaluator-pilot.json"),
        "--guard-state",
        str(args.guard_state.resolve()),
        "--authorize-cloud-training",
    ]
    os.execv(str(python), command)


if __name__ == "__main__":
    main()
