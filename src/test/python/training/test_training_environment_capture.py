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


def test_cuda_visible_version_parser_accepts_standard_and_wsl_headers() -> None:
    module = _load_capture_module()
    parser = module._parse_cuda_visible_version

    assert parser("NVIDIA-SMI 610.57.01 CUDA Version: 13.0") == "13.0"
    assert parser("NVIDIA-SMI 610.57.01 KMD Version: 610.88 CUDA UMD Version: 13.3") == "13.3"
    assert parser("NVIDIA-SMI without a CUDA version") is None


def test_wsl_cuda_umd_header_produces_a_complete_environment_record(
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
    assert record["gpu"]["cuda_visible_version"] == "13.3"
