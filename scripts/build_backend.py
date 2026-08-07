"""Build and verify the distributable OrchesTwin backend package."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PACKAGE_DIRECTORY = ROOT / "src" / "orchestwin"
DIST_DIRECTORY = ROOT / "dist"


def reset_build_output() -> None:
    """Remove stale build artifacts before creating a new distribution."""
    shutil.rmtree(DIST_DIRECTORY, ignore_errors=True)
    shutil.rmtree(ROOT / "build", ignore_errors=True)


def run_build() -> None:
    """Create both the wheel and source distribution in an isolated environment."""
    subprocess.run(
        [sys.executable, "-m", "build", "--sdist", "--wheel"],
        cwd=ROOT,
        check=True,
    )


def require_single_artifact(pattern: str) -> Path:
    """Return exactly one generated artifact matching the expected pattern."""
    artifacts = sorted(DIST_DIRECTORY.glob(pattern))

    if len(artifacts) != 1:
        names = ", ".join(path.name for path in artifacts) or "none"
        raise RuntimeError(f"expected one {pattern} artifact, found: {names}")

    return artifacts[0]


def required_package_files() -> set[str]:
    """Discover package files that must be present in built artifacts."""
    required: set[str] = set()

    for path in SOURCE_PACKAGE_DIRECTORY.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue

        if path.suffix not in {".py", ".mako"} and path.name != "py.typed":
            continue

        required.add(path.relative_to(ROOT / "src").as_posix())

    return required


def expected_console_scripts() -> set[str]:
    """Read the expected console scripts from project metadata."""
    project_definition = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = project_definition.get("project", {}).get("scripts", {})

    return {f"{name} = {target}" for name, target in scripts.items()}


def verify_wheel(wheel_path: Path) -> None:
    """Ensure the wheel contains package files and declared entry points."""
    required_files = required_package_files()
    expected_scripts = expected_console_scripts()

    with ZipFile(wheel_path) as wheel:
        packaged_files = set(wheel.namelist())
        entry_point_files = sorted(
            name for name in packaged_files if name.endswith(".dist-info/entry_points.txt")
        )

        entry_point_configuration = ""

        if expected_scripts:
            if len(entry_point_files) != 1:
                names = ", ".join(entry_point_files) or "none"
                raise RuntimeError(
                    f"wheel must contain exactly one entry_points.txt file, found: {names}"
                )

            entry_point_configuration = wheel.read(entry_point_files[0]).decode("utf-8")

    missing_files = required_files.difference(packaged_files)

    if missing_files:
        missing = ", ".join(sorted(missing_files))
        raise RuntimeError(f"wheel is missing required package files: {missing}")

    missing_scripts = {
        script for script in expected_scripts if script not in entry_point_configuration
    }

    if missing_scripts:
        missing = ", ".join(sorted(missing_scripts))
        raise RuntimeError(f"wheel is missing console scripts: {missing}")


def verify_source_distribution(source_path: Path) -> None:
    """Ensure the source distribution contains every package source file."""
    required_files = required_package_files()

    with tarfile.open(source_path, mode="r:gz") as source_archive:
        packaged_files = source_archive.getnames()

    missing_files = {
        required
        for required in required_files
        if not any(name.endswith(f"/src/{required}") for name in packaged_files)
    }

    if missing_files:
        missing = ", ".join(sorted(missing_files))
        raise RuntimeError(f"source distribution is missing required package files: {missing}")


def main() -> None:
    """Build fresh artifacts and verify their package contents."""
    reset_build_output()
    run_build()

    wheel = require_single_artifact("*.whl")
    source_distribution = require_single_artifact("*.tar.gz")

    verify_wheel(wheel)
    verify_source_distribution(source_distribution)

    print(f"Backend distribution verification: PASS ({wheel.name}, {source_distribution.name})")


if __name__ == "__main__":
    main()
