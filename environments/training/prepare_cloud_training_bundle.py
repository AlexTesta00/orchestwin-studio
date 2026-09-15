#!/usr/bin/env python3
"""Create an explicit, secret-free pilot transfer bundle; never provision cloud resources."""

from __future__ import annotations

import argparse
import tarfile
from pathlib import Path

from complete_training_data import TokenDataset, digest, save

DIRECTORY = Path(__file__).resolve().parent
OPERATORS = (
    "complete_training_data.py",
    "complete_training_runtime.py",
    "run_complete_evaluator.py",
    "run_cloud_training_job.py",
    "bootstrap_complete_training.py",
    "complete-evaluator-pilot.json",
    "pyproject.toml",
    "uv.lock",
)


def prepare(cache, output):
    cache, output = Path(cache).resolve(), Path(output).resolve()
    if DIRECTORY.parents[1] == output or DIRECTORY.parents[1] in output.parents:
        raise ValueError("transfer bundle must be outside the repository")
    dataset = TokenDataset(cache)
    dataset.close()
    output.mkdir(parents=True, exist_ok=False)
    paths = {f"environments/training/{name}": DIRECTORY / name for name in OPERATORS}
    paths.update({f"cache/{name}": cache / name for name in ("cache.json", "train.sqlite")})
    manifest = dict(
        format_version=1,
        purpose="THROUGHPUT_AND_RELIABILITY_PILOT_NOT_MODEL_QUALIFICATION",
        files={
            name: dict(sha256=digest(path), bytes=path.stat().st_size)
            for name, path in paths.items()
        },
        dataset_manifest_sha256=dataset.metadata["dataset_manifest_sha256"],
        training_rows=dataset.metadata["rows"],
        final_cases_included=False,
        secrets_included=False,
        model_weights_included=False,
    )
    save(output / "bundle.json", manifest)
    archive = output / "pilot.tar.gz"
    with tarfile.open(archive, "x:gz") as target:
        for name, path in paths.items():
            if path.is_symlink() or not path.is_file():
                raise ValueError("only regular, explicit bundle files are allowed")
            target.add(path, arcname=name, recursive=False)
        target.add(output / "bundle.json", arcname="bundle.json", recursive=False)
    receipt = dict(
        archive_sha256=digest(archive),
        manifest_sha256=digest(output / "bundle.json"),
        bytes=archive.stat().st_size,
        files=len(paths) + 1,
    )
    save(output / "transfer.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.cache, args.output), flush=True)
