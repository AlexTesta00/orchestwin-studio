"""Tests for the CI-facing digest-pinned Web runner manifest validator."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.verify_web_runner_manifest import validate_web_runner_manifest

REPOSITORY_ROOT = Path(__file__).parents[4]


def test_repository_runner_manifest_is_complete_and_capability_honest() -> None:
    result = validate_web_runner_manifest(REPOSITORY_ROOT)

    assert result.is_valid, result.errors
    assert result.runner_ids == (
        "web.browser",
        "web.node",
        "web.php",
    )
    assert len(result.base_image_references) == 4
    assert all("@sha256:" in reference for reference in result.base_image_references)


def test_validator_rejects_unpinned_and_prematurely_promoted_runner(
    tmp_path: Path,
) -> None:
    runner_root = tmp_path / "infra" / "web-runners"
    runner_root.mkdir(parents=True)
    dockerfile = runner_root / "Dockerfile.node"
    dockerfile.write_text(
        "FROM node:latest\nUSER node\n",
        encoding="utf-8",
    )
    (runner_root / "images.lock.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "base_images": [
                    {
                        "image_id": "node",
                        "reference": "node:latest",
                    }
                ],
                "runners": [
                    {
                        "runner_id": "web.node",
                        "dockerfile_path": "infra/web-runners/Dockerfile.node",
                        "base_image_ids": ["node"],
                        "capability_status": "VALIDATED_LEVEL_D",
                        "built_image_reference": "orchestwin/web-node@sha256:" + "a" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = validate_web_runner_manifest(tmp_path)

    assert not result.is_valid
    assert any("not pinned" in error for error in result.errors)
    assert any("must remain DESIGN_ONLY_LEVEL_C" in error for error in result.errors)
    assert any("fabricated built image" in error for error in result.errors)
