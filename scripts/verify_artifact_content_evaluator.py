"""One explicit live call using verified recorded axe content, through the normal factory."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
from pathlib import Path

from orchestwin.evaluation.artifact_content_control import public_error, run_content_control


async def run(args):
    from orchestwin.api.services import create_default_runtime

    runtime = create_default_runtime()
    try:
        if runtime.final_evaluator_runtime is None:
            raise ValueError("FINAL_EVALUATOR_NOT_CONFIGURED")
        return await run_content_control(
            runtime.final_evaluator_runtime,
            args.repo_root.resolve(),
            args.runner_manifest.absolute(),
            args.output_root.absolute(),
            platform_commit=args.platform_commit,
        )
    finally:
        await runtime.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--runner-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--run-one-content-evaluation",
        action="store_true",
        required=True,
        help="Authorize one local inference on the recorded technical axe fixture.",
    )
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        root = args.repo_root.resolve(strict=True)
        if root != Path.cwd().resolve():
            raise ValueError("RUN_FROM_REPOSITORY_ROOT")
        result = subprocess.run(
            ("git", "status", "--porcelain"),
            cwd=root,
            capture_output=True,
            timeout=15,
            check=True,
            stdin=subprocess.DEVNULL,
        )
        if result.stdout.strip():
            raise ValueError("COMMIT_VERIFIED_CODE_FIRST")
        commit = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=root,
            capture_output=True,
            timeout=15,
            check=True,
            stdin=subprocess.DEVNULL,
        )
        args.platform_commit = commit.stdout.decode().strip()
        report = asyncio.run(run(args), loop_factory=asyncio.SelectorEventLoop)
    except Exception as error:
        report = {
            "status": "FAILED",
            "failure_code": public_error(error),
            "stage": "PREFLIGHT",
            "formal_run_started": False,
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "FINAL_EVALUATOR_ARTIFACT_CONTENT_CONTROL_PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
