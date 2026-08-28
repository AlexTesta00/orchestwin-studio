"""Tests for the CI-facing digest-pinned JVM runner manifest validator."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.verify_jvm_runner_manifest import validate_jvm_runner_manifest

REPOSITORY_ROOT = Path(__file__).parents[4]


def test_repository_jvm_runner_manifest_is_complete_and_capability_honest() -> None:
    result = validate_jvm_runner_manifest(REPOSITORY_ROOT)

    assert result.is_valid, result.errors
    assert result.runner_ids == ("jvm.gradle", "jvm.sbt")
    assert len(result.base_image_references) == 2
    assert all("@sha256:" in reference for reference in result.base_image_references)


def test_validator_rejects_unpinned_promoted_and_root_runner(tmp_path: Path) -> None:
    runner_root = tmp_path / "infra" / "jvm-runners"
    runner_root.mkdir(parents=True)
    (runner_root / "Dockerfile.gradle").write_text(
        "FROM gradle:latest\nUSER root\n",
        encoding="utf-8",
    )
    (runner_root / "images.lock.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "base_images": [{"image_id": "gradle", "reference": "gradle:latest"}],
                "runners": [
                    {
                        "runner_id": "jvm.gradle",
                        "dockerfile_path": "infra/jvm-runners/Dockerfile.gradle",
                        "base_image_ids": ["gradle"],
                        "capability_status": "VALIDATED_LEVEL_D",
                        "built_image_reference": "orchestwin/jvm-gradle@sha256:" + "a" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = validate_jvm_runner_manifest(tmp_path)

    assert not result.is_valid
    assert any("not pinned" in error for error in result.errors)
    assert any("must remain DESIGN_ONLY_LEVEL_C" in error for error in result.errors)
    assert any("fabricated built image" in error for error in result.errors)
    assert any("non-root final USER" in error for error in result.errors)
