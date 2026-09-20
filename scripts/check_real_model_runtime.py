"""Check the composed API's real providers and database, without inference or case reads."""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from orchestwin.api.services import create_default_runtime
from orchestwin.config import ApplicationSettings, ModelRuntimeMode
from orchestwin.models.real_runtime import RealModelRuntimeError


async def check(path):
    runtime = create_default_runtime(
        ApplicationSettings(
            model_runtime_mode=ModelRuntimeMode.REAL_REQUIRED, model_runtime_config_file=path
        )
    )
    try:
        report = await runtime.real_model_runtime.check_readiness(
            runtime.database_runtime.session_factory
        )
        return {"schema_version": 1, "recorded_at": datetime.now(UTC).isoformat(), **report}
    finally:
        await runtime.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("OUTPUT_ALREADY_EXISTS")
    try:
        options = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
        report = asyncio.run(check(args.config), **options)
    except Exception as error:
        report = {
            "ready": False,
            "code": str(error)
            if isinstance(error, RealModelRuntimeError)
            else "REAL_MODEL_RUNTIME_CHECK_FAILED",
            "generation_performed": False,
        }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
