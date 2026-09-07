"""Behavior tests for WSL2 training-environment evidence capture."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
CAPTURE_SCRIPT = REPOSITORY_ROOT / "environments" / "training" / "capture_environment.py"


def _load_capture_module() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "orchestwin_training_environment_capture",
        CAPTURE_SCRIPT,
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _observed_toolchain() -> dict[str, object]:
    return {
        "status": "OBSERVED",
        "package_hint": "build-essential",
        "components": {
            "c_compiler": {
                "status": "OBSERVED",
                "executable": "gcc",
                "path": "/usr/bin/gcc",
                "version": "gcc 13.3.0",
                "detail": None,
            },
            "cxx_compiler": {
                "status": "OBSERVED",
                "executable": "g++",
                "path": "/usr/bin/g++",
                "version": "g++ 13.3.0",
                "detail": None,
            },
            "build_tool": {
                "status": "OBSERVED",
                "executable": "make",
                "path": "/usr/bin/make",
                "version": "GNU Make 4.3",
                "detail": None,
            },
            "python_header": {
                "status": "OBSERVED",
                "path": "/opt/python/include/python3.13/Python.h",
                "detail": None,
            },
        },
        "detail": None,
    }


def test_cuda_visible_version_parser_accepts_standard_and_wsl_headers() -> None:
    module = _load_capture_module()
    parser = module._parse_cuda_visible_version

    assert parser("NVIDIA-SMI 610.57.01 CUDA Version: 13.0") == "13.0"
    assert parser("NVIDIA-SMI 610.57.01 KMD Version: 610.88 CUDA UMD Version: 13.3") == "13.3"
    assert parser("NVIDIA-SMI without a CUDA version") is None


def test_build_toolchain_record_captures_commands_and_python_header(monkeypatch) -> None:
    module = _load_capture_module()
    command_paths = {
        "gcc": "/usr/bin/gcc",
        "g++": "/usr/bin/g++",
        "make": "/usr/bin/make",
    }
    version_lines = {
        "/usr/bin/gcc": "gcc (Ubuntu) 13.3.0",
        "/usr/bin/g++": "g++ (Ubuntu) 13.3.0",
        "/usr/bin/make": "GNU Make 4.3",
    }
    monkeypatch.setattr(module.shutil, "which", command_paths.get)
    monkeypatch.setattr(
        module,
        "_run",
        lambda command: {
            "status": "OBSERVED",
            "value": f"{version_lines[command[0]]}\nadditional detail",
            "detail": None,
        },
    )
    monkeypatch.setattr(
        module,
        "_python_header_record",
        lambda: {
            "status": "OBSERVED",
            "path": "/opt/python/include/python3.13/Python.h",
            "detail": None,
        },
    )

    record = module._build_toolchain_record()

    assert record["status"] == "OBSERVED"
    assert record["package_hint"] == "build-essential"
    assert record["components"]["c_compiler"]["path"] == "/usr/bin/gcc"
    assert record["components"]["c_compiler"]["version"] == "gcc (Ubuntu) 13.3.0"
    assert record["components"]["python_header"]["status"] == "OBSERVED"


def test_build_toolchain_record_is_incomplete_without_a_c_compiler(monkeypatch) -> None:
    module = _load_capture_module()

    def fake_which(executable: str) -> str | None:
        return None if executable == "gcc" else f"/usr/bin/{executable}"

    monkeypatch.setattr(module.shutil, "which", fake_which)
    monkeypatch.setattr(
        module,
        "_run",
        lambda command: {
            "status": "OBSERVED",
            "value": f"{command[0]} observed",
            "detail": None,
        },
    )
    monkeypatch.setattr(
        module,
        "_python_header_record",
        lambda: {
            "status": "OBSERVED",
            "path": "/opt/python/include/python3.13/Python.h",
            "detail": None,
        },
    )

    record = module._build_toolchain_record()

    assert record["status"] == "NOT_AVAILABLE"
    assert record["components"]["c_compiler"]["status"] == "NOT_AVAILABLE"
    assert record["detail"] == "Unavailable components: c_compiler"


def test_wsl_cuda_umd_header_and_build_toolchain_produce_a_complete_record(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_capture_module()
    package_names = module._PACKAGE_NAMES
    monkeypatch.setattr(
        module,
        "_package_versions",
        lambda: {package_name: "observed" for package_name in package_names},
    )
    monkeypatch.setattr(module, "_build_toolchain_record", _observed_toolchain)

    def fake_run(command: tuple[str, ...]) -> dict[str, object]:
        if command == ("uv", "--version"):
            return {"status": "OBSERVED", "value": "uv 0.12.3", "detail": None}
        if command == ("nvidia-smi",):
            return {
                "status": "OBSERVED",
                "value": ("NVIDIA-SMI 610.57.01 KMD Version: 610.88 CUDA UMD Version: 13.3"),
                "detail": None,
            }
        if command[0] == "nvidia-smi":
            return {
                "status": "OBSERVED",
                "value": "NVIDIA GeForce RTX 4060, 8188, 610.88",
                "detail": None,
            }
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(module, "_run", fake_run)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    record = module.build_environment_record(tmp_path)

    assert record["complete"] is True
    assert record["build_toolchain"] == _observed_toolchain()
    assert record["gpu"]["cuda_visible_version"] == "13.3"


def test_environment_record_is_incomplete_without_the_build_toolchain(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_capture_module()
    package_names = module._PACKAGE_NAMES
    monkeypatch.setattr(
        module,
        "_package_versions",
        lambda: {package_name: "observed" for package_name in package_names},
    )
    monkeypatch.setattr(
        module,
        "_build_toolchain_record",
        lambda: {
            **_observed_toolchain(),
            "status": "NOT_AVAILABLE",
            "detail": "Unavailable components: c_compiler",
        },
    )
    monkeypatch.setattr(
        module,
        "_gpu_record",
        lambda: {
            "status": "OBSERVED",
            "name": "NVIDIA GeForce RTX 4060",
            "memory_mb": 8188,
            "driver_version": "610.88",
            "cuda_visible_version": "13.3",
            "detail": None,
        },
    )
    monkeypatch.setattr(
        module,
        "_run",
        lambda command: {
            "status": "OBSERVED",
            "value": "uv 0.12.3",
            "detail": None,
        },
    )
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    record = module.build_environment_record(tmp_path)

    assert record["complete"] is False
    assert record["build_toolchain"]["status"] == "NOT_AVAILABLE"
