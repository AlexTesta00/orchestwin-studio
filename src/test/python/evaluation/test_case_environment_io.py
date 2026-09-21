"""Tests for persisted observed case-study environment identities."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from orchestwin.evaluation.case_environment import (
    CaseStudyContainerImage,
    CaseStudyRuntimeVersion,
    create_case_study_environment_identity,
)
from orchestwin.evaluation.case_environment_io import (
    load_case_study_environment_identity,
    write_case_study_environment_identity,
)


def _environment():
    return create_case_study_environment_identity(
        platform_commit="4" * 40,
        execution_profile="WEB_STATIC",
        operating_system="Linux test host",
        architecture="x86_64",
        python_version="3.14.0",
        runtime_versions=(
            CaseStudyRuntimeVersion(component="Node.js", version="24.0.0"),
            CaseStudyRuntimeVersion(component="Python", version="3.14.0"),
        ),
        container_images=(
            CaseStudyContainerImage(
                name="orchestwin/web-browser-runner", digest="sha256:" + "a" * 64
            ),
        ),
        network_policy="No external network during generated application execution.",
        captured_at=datetime(2026, 9, 7, 16, 0, tzinfo=UTC),
    )


def test_environment_identity_round_trips_without_losing_observed_versions(tmp_path) -> None:
    environment = _environment()
    path = tmp_path / "environment.json"

    write_case_study_environment_identity(path, environment)
    loaded = load_case_study_environment_identity(path)

    assert loaded == environment
    assert loaded.runtime_versions[0].component == "Node.js"
    assert loaded.container_images[0].digest.startswith("sha256:")


def test_environment_loader_rejects_tampered_identity(tmp_path) -> None:
    path = tmp_path / "environment.json"
    write_case_study_environment_identity(path, _environment())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["python_version"] = "9.9.9"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="content hash"):
        load_case_study_environment_identity(path)
