"""Exercise the generic executor on committed technical fixtures, never formal cases."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from orchestwin.sandbox.host_process import run_bounded_host_process
from orchestwin.web_execution.static_browser_executor import (
    HARNESS_PATH,
    BrowserExecutionAuthorization,
    execute_static_browser_job,
)
from orchestwin.web_execution.static_browser_jobs import (
    BrowserAction,
    BrowserScenario,
    StaticBrowserError,
    content_hash,
    job_from_revision,
)
from orchestwin.web_execution.verified_browser_runner import (
    read_json,
    read_regular,
    verify_browser_runner,
)

FIXTURE_PATH = "experiments/runner-validation/static-browser-v1.json"


def fixture_job(fixture, *, runner_hash, harness_hash):
    """Use the same revision-to-job compiler as the future application caller."""
    owner = uuid5(NAMESPACE_URL, "orchestwin:technical-browser-validation-owner")
    project = uuid5(owner, fixture["id"])
    blobs = {}
    entries = []
    for path, text in sorted(
        fixture["files"].items(), key=lambda item: (item[0].casefold(), item[0])
    ):
        data = text.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        key = f"sha256/{digest[:2]}/{digest}"
        blobs[key] = data
        entries.append(
            {
                "normalized_path": path,
                "sha256_digest": digest,
                "size_bytes": len(data),
                "storage_key": key,
                "media_type": "text/plain",
            }
        )
    revision = {
        "id": str(uuid5(project, "revision-1")),
        "project_id": str(project),
        "created_by_user_id": str(owner),
        "version_number": 1,
        "based_on": None,
        "target_selection": {
            "target": "WEB_STATIC",
            "layout": "SINGLE_ROOT",
            "language_configuration": {"frontend": "STATIC_ASSETS", "backend": None},
        },
        "origin": "DETERMINISTIC_FIXTURE",
        "validation_scope_hash": "0" * 64,
        "related_failure_signature": None,
        "files": entries,
        "provenance_references": [
            {
                "kind": "SOURCE_PLAN",
                "reference_id": f"fixture:{fixture['id']}",
                "version_number": 1,
                "content_hash": content_hash(fixture),
            }
        ],
        "created_at": "2026-09-09T00:00:00+00:00",
    }
    revision["content_hash"] = content_hash(revision)
    revision["source_tree_hash"] = content_hash(
        {
            "files": [
                {key: entry[key] for key in ("normalized_path", "sha256_digest", "size_bytes")}
                for entry in entries
            ]
        }
    )
    scenario = BrowserScenario(
        fixture["id"], "/", tuple(BrowserAction(**action) for action in fixture["actions"])
    )
    job = job_from_revision(
        revision,
        project_id=project,
        owner_user_id=owner,
        read_content=blobs.get,
        scenarios=(scenario,),
        runner_manifest_content_hash=runner_hash,
        harness_sha256=harness_hash,
    )
    return job, revision, blobs


def validate_fixture_outcome(expected, outcome):
    """A negative control must reach its assertion, not merely return some failure."""
    if (
        outcome.get("status") != "COMPLETED"
        or outcome.get("cleanup_confirmed") is not True
        or outcome.get("assertion_status") != expected
    ):
        raise StaticBrowserError("STATIC_BROWSER_VALIDATION_OUTCOME_MISMATCH")
    if expected == "FAILED":
        screens = outcome.get("screens", [])
        if not screens or any(
            screen.get("blocked_requests") != 0
            or screen.get("page_error_count") != 0
            or not any(
                action.get("kind") == "expect_text"
                and action.get("status") == "FAILED"
                and action.get("failure_code") == "TEXT_ASSERTION_FAILED"
                for action in screen.get("actions", [])
            )
            for screen in screens
        ):
            raise StaticBrowserError("STATIC_BROWSER_NEGATIVE_CONTROL_INVALID")


async def validate_static_browser_executor(root: Path, runner_manifest: Path, output: Path):
    root = root.resolve(strict=True)
    output = output.absolute()
    if (
        output.exists()
        or output == root
        or root in output.parents
        or ".." in output.parts
        or any(item.is_symlink() or item.is_junction() for item in (output, *output.parents))
    ):
        raise StaticBrowserError("VALIDATION_OUTPUT_MUST_BE_NEW_SAFE_AND_EXTERNAL")
    fixture_bytes = read_regular(root / FIXTURE_PATH, 1024 * 1024)
    # Profile-validation authority is restricted to reviewed committed fixture bytes.
    result = await run_bounded_host_process(
        ("git", "-C", str(root), "show", f"HEAD:{FIXTURE_PATH}"),
        timeout_seconds=10,
        maximum_output_bytes_per_stream=1024 * 1024,
        environment_overrides={},
    )
    if (
        result.status != "COMPLETED"
        or result.exit_code != 0
        or result.stdout.replace(b"\r\n", b"\n") != fixture_bytes.replace(b"\r\n", b"\n")
    ):
        raise StaticBrowserError("VALIDATION_FIXTURES_NOT_COMMITTED")
    payload = read_json(fixture_bytes)
    if payload.get("purpose") != "REPOSITORY_OWNED_PROFILE_VALIDATION_NOT_FORMAL_CASES":
        raise StaticBrowserError("VALIDATION_FIXTURE_PURPOSE_INVALID")
    fixtures = payload.get("fixtures", [])
    if [item.get("expected") for item in fixtures] != ["PASSED", "PASSED", "FAILED"]:
        raise StaticBrowserError("VALIDATION_REQUIRES_POSITIVE_AND_NEGATIVE_CASES")
    observed = verify_browser_runner(runner_manifest, root)
    harness_hash = hashlib.sha256(read_regular(root / HARNESS_PATH, 20000)).hexdigest()
    jobs = [
        fixture_job(item, runner_hash=observed.manifest_content_hash, harness_hash=harness_hash)[0]
        for item in fixtures
    ]
    permitted = {
        job.content_hash: fixture["id"] for job, fixture in zip(jobs, fixtures, strict=True)
    }

    async def authorize(job):
        fixture_id = permitted.get(job.content_hash)
        return (
            None
            if fixture_id is None
            else BrowserExecutionAuthorization(
                job.content_hash, "PROFILE_VALIDATION", f"committed-fixture:{fixture_id}"
            )
        )

    output.mkdir(parents=True)
    manifest = {
        "report_type": "STATIC_BROWSER_EXECUTOR_VALIDATION_NOT_FORMAL_EVIDENCE",
        "status": "IN_PROGRESS",
        "formal_run_started": False,
        "level_d_validated": False,
        "owner_gate_integration_verified": False,
        "runner_image_id": observed.image_id,
        "runner_observation_content_hash": observed.manifest_content_hash,
        "fixture_file_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "results": [],
    }
    try:
        for fixture, job in zip(fixtures, jobs, strict=True):
            print(f"[STATIC_EXECUTOR {fixture['id']} expected={fixture['expected']}]", flush=True)
            outcome = await execute_static_browser_job(
                job,
                repo_root=root,
                runner_manifest=runner_manifest,
                output_root=output / fixture["id"],
                authorize=authorize,
            )
            row = {
                "fixture": fixture["id"],
                "expected_assertions": fixture["expected"],
                "observed_assertions": outcome["assertion_status"],
                "execution_status": outcome["status"],
                "cleanup_confirmed": outcome["cleanup_confirmed"],
                "manifest_content_hash": outcome["content_hash"],
            }
            manifest["results"].append(row)
            validate_fixture_outcome(fixture["expected"], outcome)
        manifest["status"] = "STATIC_BROWSER_EXECUTOR_VALIDATION_PASSED"
    except BaseException as error:
        manifest["status"] = "FAILED"
        manifest["failure_code"] = (
            str(error) if isinstance(error, StaticBrowserError) else type(error).__name__
        )
        raise
    finally:
        manifest["content_hash"] = content_hash(manifest)
        with (output / "manifest.json").open("x", encoding="utf-8", newline="\n") as file:
            json.dump(manifest, file, indent=2, sort_keys=True)
            file.write("\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--runner-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--validate-static-executor", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(
            validate_static_browser_executor(args.repo_root, args.runner_manifest, args.output_root)
        )
    except (StaticBrowserError, OSError, ValueError, TypeError, KeyError, IndexError) as error:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "code": str(error)
                    if isinstance(error, StaticBrowserError)
                    else type(error).__name__,
                    "formal_run_started": False,
                }
            )
        )
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0
