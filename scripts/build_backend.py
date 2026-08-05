"""Build and verify the distributable OrchesTwin backend package."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
DIST_DIRECTORY = ROOT / "dist"
EXPECTED_CONSOLE_SCRIPT = "orchestwin-api = orchestwin.api.server:main"
REQUIRED_PACKAGE_FILES = {
    "orchestwin/__init__.py",
    "orchestwin/api/__init__.py",
    "orchestwin/api/app.py",
    "orchestwin/api/health.py",
    "orchestwin/api/server.py",
    "orchestwin/config.py",
    "orchestwin/py.typed",
}


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


def verify_wheel(wheel_path: Path) -> None:
    """Ensure the wheel contains the package and console entry point."""
    with ZipFile(wheel_path) as wheel:
        packaged_files = set(wheel.namelist())
        entry_point_files = sorted(
            name for name in packaged_files if name.endswith(".dist-info/entry_points.txt")
        )

        if len(entry_point_files) != 1:
            names = ", ".join(entry_point_files) or "none"
            raise RuntimeError(
                f"wheel must contain exactly one entry_points.txt file, found: {names}"
            )

        entry_point_configuration = wheel.read(entry_point_files[0]).decode("utf-8")

    missing_files = REQUIRED_PACKAGE_FILES.difference(packaged_files)
    if missing_files:
        missing = ", ".join(sorted(missing_files))
        raise RuntimeError(f"wheel is missing required package files: {missing}")

    if EXPECTED_CONSOLE_SCRIPT not in entry_point_configuration:
        raise RuntimeError(
            f"wheel is missing the expected console script: {EXPECTED_CONSOLE_SCRIPT}"
        )


def verify_source_distribution(source_path: Path) -> None:
    """Ensure the source distribution contains the backend package sources."""
    with tarfile.open(source_path, mode="r:gz") as source_archive:
        packaged_files = source_archive.getnames()

    missing_files = {
        required
        for required in REQUIRED_PACKAGE_FILES
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
