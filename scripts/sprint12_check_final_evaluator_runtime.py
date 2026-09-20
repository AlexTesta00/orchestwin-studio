"""Check the standard application evaluator factory and replay existing R2, without inference."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
from pathlib import Path

from orchestwin.api.app import create_app
from orchestwin.api.services import create_default_runtime
from orchestwin.evaluation.final_runtime_replay import replay_r2


async def check(evidence_root: Path) -> dict[str, object]:
    runtime = create_default_runtime()
    try:
        factory = runtime.final_evaluator_runtime
        if factory is None:
            raise ValueError("FINAL_EVALUATOR_NOT_CONFIGURED")
        app = create_app(runtime=runtime)
        if app.state.final_evaluator_runtime is not factory:
            raise ValueError("FINAL_EVALUATOR_APP_STATE_NOT_WIRED")
        before = await factory.check_health()
        replay = await replay_r2(factory, evidence_root)
        after = await factory.check_health()
        if after["completed_generation_count"] != before["completed_generation_count"]:
            raise ValueError("CONCURRENT_GENERATION_OBSERVED")
        return {
            "status": "FINAL_EVALUATOR_FACTORY_AND_R2_REPLAY_VERIFIED",
            "report_type": "LOCAL_FACTORY_HEALTH_AND_REPLAY_NOT_FORMAL_EVIDENCE",
            "application_evaluator_factory_configured": True,
            "authenticated_live_health_verified": True,
            "prompt_version_ref": factory.create_evaluator().configuration.prompt_version_ref,
            "model_identity": factory.session.identity,
            "completed_generation_count_before": before["completed_generation_count"],
            "completed_generation_count_after": after["completed_generation_count"],
            "replay": replay,
            "new_generation_performed": False,
            "database_queries_performed": False,
            "training_executed": False,
            "formal_run_started": False,
            "evaluation_http_endpoint_added": False,
            "workflow_evaluator_routing_completed": False,
            "full_workflow_validated": False,
        }
    finally:
        await runtime.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--r2-evidence", type=Path, required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        root = args.repo_root.resolve(strict=True)
        if root != Path.cwd().resolve():
            raise ValueError("RUN_FROM_REPOSITORY_ROOT")
        git = subprocess.run(
            ("git", "status", "--porcelain"),
            cwd=root,
            capture_output=True,
            timeout=15,
            check=True,
            stdin=subprocess.DEVNULL,
        )
        if git.stdout.strip():
            raise ValueError("COMMIT_VERIFIED_CODE_FIRST")
        result = asyncio.run(check(args.r2_evidence), loop_factory=asyncio.SelectorEventLoop)
    except Exception as error:
        # Error codes from this boundary are fixed strings, never dump settings or HTTP bodies.
        code = (
            str(error)
            if isinstance(error, ValueError) and str(error).isupper() and len(str(error)) <= 100
            else type(error).__name__
        )
        print(json.dumps({"status": "FAILED", "code": code, "new_generation_performed": False}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
