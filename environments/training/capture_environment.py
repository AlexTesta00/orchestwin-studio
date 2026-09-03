"""Capture reproducibility evidence for the isolated WSL2 training environment."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

_PACKAGE_NAMES: Final = (
    "accelerate",
    "bitsandbytes",
    "datasets",
    "peft",
    "torch",
    "transformers",
    "trl",
    "unsloth",
    "unsloth-zoo",
    "xformers",
)
_COMMAND_TIMEOUT_SECONDS: Final = 15
_CUDA_VISIBLE_VERSION_PATTERN: Final = re.compile(
    r"\bCUDA(?: UMD)? Version:\s*([0-9]+(?:\.[0-9]+)*)"
)


def _package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for package_name in _PACKAGE_NAMES:
        try:
            versions[package_name] = importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            versions[package_name] = None
    return versions


def _run(command: tuple[str, ...]) -> dict[str, object]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return {"status": "NOT_AVAILABLE", "value": None, "detail": "command not found"}
    except subprocess.TimeoutExpired:
        return {"status": "COMMAND_FAILED", "value": None, "detail": "command timed out"}
    except OSError:
        return {"status": "COMMAND_FAILED", "value": None, "detail": "command failed"}
    stdout = result.stdout.strip()
    if result.returncode != 0:
        return {
            "status": "COMMAND_FAILED",
            "value": None,
            "detail": f"exit code {result.returncode}",
        }
    return {"status": "OBSERVED", "value": stdout, "detail": None}


def _first_non_empty_line(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return next((line.strip() for line in value.splitlines() if line.strip()), None)


def _command_record(executable: str) -> dict[str, object]:
    executable_path = shutil.which(executable)
    if executable_path is None:
        return {
            "status": "NOT_AVAILABLE",
            "executable": executable,
            "path": None,
            "version": None,
            "detail": "command not found",
        }
    observed = _run((executable_path, "--version"))
    return {
        "status": observed["status"],
        "executable": executable,
        "path": executable_path,
        "version": _first_non_empty_line(observed["value"]),
        "detail": observed["detail"],
    }


def _python_header_record() -> dict[str, object]:
    include_directory = Path(sysconfig.get_paths()["include"]).resolve()
    python_header = include_directory / "Python.h"
    exists = python_header.is_file()
    return {
        "status": "OBSERVED" if exists else "NOT_AVAILABLE",
        "path": str(python_header),
        "detail": None if exists else "Python.h was not found",
    }


def _build_toolchain_record() -> dict[str, object]:
    components = {
        "c_compiler": _command_record("gcc"),
        "cxx_compiler": _command_record("g++"),
        "build_tool": _command_record("make"),
        "python_header": _python_header_record(),
    }
    incomplete = tuple(
        sorted(name for name, component in components.items() if component["status"] != "OBSERVED")
    )
    statuses = {component["status"] for component in components.values()}
    if not incomplete:
        status = "OBSERVED"
        detail = None
    elif "COMMAND_FAILED" in statuses:
        status = "COMMAND_FAILED"
        detail = f"Unavailable or failing components: {', '.join(incomplete)}"
    else:
        status = "NOT_AVAILABLE"
        detail = f"Unavailable components: {', '.join(incomplete)}"
    return {
        "status": status,
        "package_hint": "build-essential",
        "components": components,
        "detail": detail,
    }


def _parse_cuda_visible_version(output: str) -> str | None:
    match = _CUDA_VISIBLE_VERSION_PATTERN.search(output)
    return None if match is None else match.group(1)


def _gpu_record() -> dict[str, object]:
    query = _run(
        (
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        )
    )
    header = _run(("nvidia-smi",))
    values: dict[str, object] = {
        "status": query["status"],
        "name": None,
        "memory_mb": None,
        "driver_version": None,
        "cuda_visible_version": None,
        "detail": query["detail"],
    }
    if query["status"] == "OBSERVED" and isinstance(query["value"], str):
        first_line = next(
            (line.strip() for line in query["value"].splitlines() if line.strip()),
            "",
        )
        fields = [field.strip() for field in first_line.split(",")]
        if len(fields) == 3:
            values["name"] = fields[0]
            try:
                values["memory_mb"] = int(float(fields[1]))
            except ValueError:
                values["status"] = "COMMAND_FAILED"
                values["detail"] = "GPU memory was not numeric"
            values["driver_version"] = fields[2]
    if header["status"] == "OBSERVED" and isinstance(header["value"], str):
        values["cuda_visible_version"] = _parse_cuda_visible_version(header["value"])
    return values


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_environment_record(environment_dir: Path) -> dict[str, object]:
    packages = _package_versions()
    build_toolchain = _build_toolchain_record()
    gpu = _gpu_record()
    uv = _run(("uv", "--version"))
    lock_sha256 = _sha256(environment_dir / "uv.lock")
    wsl_distribution = os.environ.get("WSL_DISTRO_NAME")
    is_wsl = bool(wsl_distribution) or (
        Path("/proc/version").is_file()
        and "microsoft" in Path("/proc/version").read_text(errors="ignore").casefold()
    )
    complete = all(
        (
            is_wsl,
            lock_sha256 is not None,
            uv["status"] == "OBSERVED",
            build_toolchain["status"] == "OBSERVED",
            gpu["status"] == "OBSERVED",
            gpu["cuda_visible_version"] is not None,
            all(value is not None for value in packages.values()),
        )
    )
    return {
        "schema_version": 1,
        "environment_id": "orchestwin-unsloth-wsl2-v1",
        "captured_at": datetime.now(UTC).isoformat(),
        "complete": complete,
        "platform": platform.platform(),
        "python": {
            "version": platform.python_version(),
            "executable": str(Path(sys.executable).resolve()),
        },
        "wsl": {
            "detected": is_wsl,
            "distribution": wsl_distribution,
        },
        "uv": uv,
        "build_toolchain": build_toolchain,
        "gpu": gpu,
        "packages": packages,
        "uv_lock_sha256": lock_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    environment_dir = Path(__file__).resolve().parent
    record = build_environment_record(environment_dir)
    output = arguments.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
