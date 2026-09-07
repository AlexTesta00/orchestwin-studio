"""Keep model-spike CLIs usable without backend or GPU packages at import time."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from importlib import import_module
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
TRAINING_ROOT = REPOSITORY_ROOT / "environments" / "training"
PERSISTENCE_EXPORTS = (
    "DatasetBuildQualityReport",
    "InMemoryTrainingDatasetRepository",
    "SqlAlchemyTrainingDatasetRepository",
    "StoredTrainingDatasetVersion",
    "TrainingDatasetQualityReportRecord",
    "TrainingDatasetRepository",
    "TrainingDatasetStoreResult",
    "TrainingDatasetStoreStatus",
    "TrainingDatasetVersionRecord",
    "create_dataset_quality_report",
)


def _isolated_python(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Use a fresh interpreter that cannot see any installed third-party package."""
    environment = dict(os.environ)
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "ORCHESTWIN_MODEL_SOURCE_ALLOW_NETWORK": "0",
            "ORCHESTWIN_MODEL_SPIKE_ALLOW_NETWORK": "0",
            "ORCHESTWIN_MODEL_SPIKE_ALLOW_ALL": "0",
        }
    )
    return subprocess.run(
        [sys.executable, "-I", "-S", *arguments],
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def _isolated_code(source: str, *, cwd: Path) -> subprocess.CompletedProcess[str]:
    prelude = "import sys\nsys.path.insert(0, sys.argv[1])\n"
    return _isolated_python(
        "-c",
        prelude + textwrap.dedent(source),
        str(REPOSITORY_ROOT / "src"),
        cwd=cwd,
    )


def test_domain_exports_do_not_import_persistence(tmp_path: Path) -> None:
    result = _isolated_code(
        """
        import orchestwin.training as training
        from orchestwin.training import DatasetLanguage, default_dataset_split_policy

        assert DatasetLanguage.ITALIAN.value == "it"
        assert callable(default_dataset_split_policy)
        assert "SqlAlchemyTrainingDatasetRepository" in training.__all__
        assert "SqlAlchemyTrainingDatasetRepository" in dir(training)
        assert len(training.__all__) == len(set(training.__all__))
        assert "orchestwin.training.persistence" not in sys.modules
        assert "sqlalchemy" not in sys.modules
        print("domain_import_without_backend: PASSED")
        """,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "domain_import_without_backend: PASSED" in result.stdout


def test_model_spike_modules_import_without_optional_stacks(tmp_path: Path) -> None:
    result = _isolated_code(
        """
        from importlib import import_module

        for name in (
            "model_candidate_matrix_files",
            "model_source_evidence",
            "model_spike_requests",
            "model_spike_batch",
            "model_spike_results",
            "model_spike_reports",
        ):
            import_module(f"orchestwin.training.{name}")
        for name in (
            "sqlalchemy", "alembic", "psycopg", "fastapi",
            "torch", "unsloth", "transformers", "huggingface_hub",
        ):
            assert name not in sys.modules, name
        assert "orchestwin.training.persistence" not in sys.modules
        print("model_spike_import_boundary: PASSED")
        """,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "model_spike_import_boundary: PASSED" in result.stdout


@pytest.mark.parametrize(
    "filename",
    (
        "capture_model_sources.py",
        "materialize_model_spike_requests.py",
        "run_model_spike.py",
        "run_model_spike_batch.py",
        "validate_model_spike_results.py",
        "report_model_spike.py",
        "run_qlora.py",
    ),
)
def test_training_cli_help_needs_only_stdlib(filename: str, tmp_path: Path) -> None:
    result = _isolated_python(str(TRAINING_ROOT / filename), "--help", cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "usage:" in result.stdout.casefold()
    assert not tuple(tmp_path.iterdir()), "--help must not write runtime artifacts"


def test_capture_reaches_candidate_validation_without_backend(tmp_path: Path) -> None:
    result = _isolated_python(
        str(TRAINING_ROOT / "capture_model_sources.py"),
        "--candidate-id",
        "model-candidate-not-in-the-frozen-matrix",
        "--output-root",
        str(tmp_path / "sources"),
        cwd=tmp_path,
    )
    assert result.returncode == 22, result.stdout + result.stderr
    assert "candidate is not present in the frozen matrix" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr
    assert not (tmp_path / "sources").exists()


def test_missing_backend_dependency_is_not_silently_hidden(tmp_path: Path) -> None:
    result = _isolated_code(
        """
        import orchestwin.training as training

        try:
            training.SqlAlchemyTrainingDatasetRepository
        except ModuleNotFoundError as error:
            assert error.name == "sqlalchemy", error
        else:
            raise AssertionError("A persistence export still requires SQLAlchemy")
        print("explicit_persistence_dependency: PASSED")
        """,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "explicit_persistence_dependency: PASSED" in result.stdout


def test_unknown_export_raises_attribute_error_without_backend(tmp_path: Path) -> None:
    result = _isolated_code(
        """
        import orchestwin.training as training

        try:
            training.not_a_training_export
        except AttributeError as error:
            assert "not_a_training_export" in str(error)
        else:
            raise AssertionError("Unknown exports must raise AttributeError")
        assert "orchestwin.training.persistence" not in sys.modules
        print("unknown_export: PASSED")
        """,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "unknown_export: PASSED" in result.stdout


def test_backend_reexports_preserve_original_object_identity() -> None:
    training = import_module("orchestwin.training")
    persistence = import_module("orchestwin.training.persistence")

    for name in PERSISTENCE_EXPORTS:
        assert name in training.__all__
        assert name in dir(training)
        assert getattr(training, name) is getattr(persistence, name)
