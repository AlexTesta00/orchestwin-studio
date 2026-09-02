"""Contract tests for the isolated WSL2 CUDA training environment."""

from __future__ import annotations

import py_compile
import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
ENVIRONMENT_ROOT = REPOSITORY_ROOT / "environments" / "training"


def _toml(name: str) -> dict[str, object]:
    return tomllib.loads((ENVIRONMENT_ROOT / name).read_text(encoding="utf-8"))


def test_training_dependencies_and_toolchain_are_exactly_pinned() -> None:
    project = _toml("pyproject.toml")
    toolchain = _toml("toolchain.toml")

    assert project["project"]["requires-python"] == ">=3.13,<3.14"
    assert project["project"]["dependencies"] == [
        "trl==1.12.0",
        "unsloth==2026.8.22",
        "unsloth-zoo==2026.8.16",
    ]
    assert toolchain["python_version"] == "3.13"
    assert toolchain["uv_version"] == "0.12.3"
    assert toolchain["lockfile"] == "uv.lock"
    assert (ENVIRONMENT_ROOT / ".python-version").read_text().strip() == "3.13"


def test_training_stack_does_not_leak_into_core_dependencies() -> None:
    root_project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())
    root_requirements = (REPOSITORY_ROOT / "requirements-dev.txt").read_text()
    prohibited = ("unsloth", "unsloth-zoo", "trl", "bitsandbytes", "torch")

    root_dependencies = "\n".join(root_project["project"]["dependencies"]).casefold()
    assert all(name not in root_dependencies for name in prohibited)
    assert all(name not in root_requirements.casefold() for name in prohibited)


def test_bootstrap_requires_wsl_exact_tools_and_explicit_network_gate() -> None:
    script = (ENVIRONMENT_ROOT / "bootstrap-wsl.sh").read_text()

    assert "WSL_DISTRO_NAME" in script
    assert 'REQUIRED_PYTHON_MINOR="3.13"' in script
    assert 'REQUIRED_UV_VERSION="0.12.3"' in script
    assert "ORCHESTWIN_TRAINING_ALLOW_NETWORK" in script
    assert "uv sync --frozen --no-dev" in script
    assert "download model weights" in script
    assert "curl " not in script
    assert "wget " not in script
    assert "git clone" not in script


def test_environment_capture_is_stdlib_only_and_records_missing_evidence() -> None:
    capture_script = ENVIRONMENT_ROOT / "capture_environment.py"
    source = capture_script.read_text()

    py_compile.compile(str(capture_script), doraise=True)
    assert "uv_lock_sha256" in source
    assert '"complete": complete' in source
    assert "nvidia-smi" in source
    assert "PackageNotFoundError" in source
    assert "subprocess.run" in source
    assert "shell=True" not in source


def test_large_training_outputs_are_excluded_but_lock_decision_stays_visible() -> None:
    ignored = set((ENVIRONMENT_ROOT / ".gitignore").read_text().splitlines())

    assert {".venv/", "artifacts/", "checkpoints/", "*.safetensors", "*.gguf"}.issubset(ignored)
    assert "uv.lock" not in ignored
