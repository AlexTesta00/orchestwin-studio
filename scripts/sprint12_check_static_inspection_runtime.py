"""Read-only local readiness check. No project, owner decision or browser job is created."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

import sqlalchemy as sa

from orchestwin.api.app import create_app
from orchestwin.api.services import create_default_runtime
from orchestwin.api.static_inspection_runtime import StaticInspectionSettings
from orchestwin.config import load_settings
from orchestwin.web_execution.static_inspection_persistence import STATIC_BROWSER_INSPECTIONS
from orchestwin.web_execution.static_inspections import InspectionError


async def check() -> dict[str, object]:
    configuration = StaticInspectionSettings()
    if not configuration.enabled:
        raise InspectionError("STATIC_INSPECTION_SERVICE_DISABLED")
    runtime = create_default_runtime(load_settings())
    try:
        if runtime.database_runtime is None or runtime.static_inspection_service is None:
            raise InspectionError("STATIC_INSPECTION_RUNTIME_UNAVAILABLE")
        app = create_app(runtime=runtime)
        operations = {
            operation.get("operationId")
            for item in app.openapi()["paths"].values()
            for operation in item.values()
            if isinstance(operation, dict)
        }
        expected = {
            "prepareStaticBrowserInspection",
            "listStaticBrowserInspections",
            "getStaticBrowserInspection",
            "decideStaticBrowserInspectionGate",
            "executeStaticBrowserInspection",
            "recoverStaticBrowserInspection",
        }
        if not expected <= operations:
            raise InspectionError("STATIC_INSPECTION_ROUTES_MISSING")
        backend = runtime.static_inspection_service._backend
        binding = await backend.binding()
        async with asyncio.timeout(20), runtime.database_runtime.engine.connect() as connection:
            await connection.execution_options(postgresql_readonly=True)
            if await connection.scalar(sa.text("SHOW transaction_read_only")) != "on":
                raise InspectionError("DATABASE_READONLY_NOT_CONFIRMED")
            revisions = tuple(
                (
                    await connection.execute(sa.text("SELECT version_num FROM alembic_version"))
                ).scalars()
            )
            await connection.execute(sa.select(STATIC_BROWSER_INSPECTIONS).limit(0))
            await connection.rollback()
        if revisions != ("0032_static_browser_inspections",):
            raise InspectionError("STATIC_INSPECTION_MIGRATION_NOT_AT_EXPECTED_HEAD")
        return {
            "status": "STATIC_INSPECTION_API_CONFIGURED",
            "report_type": "LOCAL_READINESS_NOT_FORMAL_EVIDENCE",
            "platform_commit": binding.platform_commit,
            "registered_operations": sorted(expected),
            "database_connection": "CONNECTED_READ_ONLY",
            "database_revision": list(revisions),
            "inspection_table_readable": True,
            "database_constraint_audit": "NOT_PERFORMED",
            "runner_observation_content_hash": binding.runner.manifest_content_hash,
            "runner_image_id": binding.runner.image_id,
            "runner_manifest_integrity": "VERIFIED",
            "docker_execution_in_this_check": "NOT_PERFORMED",
            "persisted_gate_7_required": True,
            "formal_run_started": False,
            "full_workflow_validated": False,
        }
    finally:
        await runtime.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if Path.cwd().resolve() != args.repo_root.resolve():
        print(json.dumps({"status": "FAILED", "code": "RUN_FROM_REPOSITORY_ROOT"}))
        return 1
    logging.disable(logging.CRITICAL)
    try:
        result = asyncio.run(check(), loop_factory=asyncio.SelectorEventLoop)
    except Exception as error:
        # Operator boundary: values, traceback, DB URLs and local secrets are not output.
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "code": error.code
                    if isinstance(error, InspectionError)
                    else type(error).__name__,
                    "formal_run_started": False,
                }
            )
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
