"""Tests for digest-pinned Web runner build inputs."""

from __future__ import annotations

from pathlib import Path

from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus
from orchestwin.web_execution.runners import WebRunnerKind, load_web_runner_image_lock

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def test_runner_lock_pins_every_upstream_image_by_digest() -> None:
    image_lock = load_web_runner_image_lock(REPOSITORY_ROOT / "infra/web-runners/images.lock.json")

    assert {runner.kind for runner in image_lock.runners} == set(WebRunnerKind)
    assert all("@sha256:" in image.reference.value for image in image_lock.base_images)
    assert all(":latest@" not in image.reference.value for image in image_lock.base_images)
    assert len({image.reference.digest for image in image_lock.base_images}) == 4
    assert len(image_lock.content_hash) == 64


def test_built_runner_digest_remains_explicitly_pending_before_validation() -> None:
    image_lock = load_web_runner_image_lock(REPOSITORY_ROOT / "infra/web-runners/images.lock.json")

    assert not image_lock.ready_for_level_d_validation
    assert all(
        runner.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
        for runner in image_lock.runners
    )
    assert all(runner.built_image_reference is None for runner in image_lock.runners)


def test_dockerfiles_repeat_the_exact_locked_base_references() -> None:
    image_lock = load_web_runner_image_lock(REPOSITORY_ROOT / "infra/web-runners/images.lock.json")

    for runner in image_lock.runners:
        dockerfile = (REPOSITORY_ROOT / runner.dockerfile_path).read_text(encoding="utf-8")
        for image_id in runner.base_image_ids:
            assert image_lock.base_image(image_id).reference.value in dockerfile


def test_node_and_php_recipes_install_the_controlled_helper_scripts() -> None:
    image_lock = load_web_runner_image_lock(REPOSITORY_ROOT / "infra/web-runners/images.lock.json")
    node_recipe = (
        REPOSITORY_ROOT / image_lock.runner(WebRunnerKind.NODE).dockerfile_path
    ).read_text(encoding="utf-8")
    php_recipe = (REPOSITORY_ROOT / image_lock.runner(WebRunnerKind.PHP).dockerfile_path).read_text(
        encoding="utf-8"
    )

    assert "/opt/orchestwin/bin/static-server.mjs" in node_recipe
    assert "/opt/orchestwin/bin/php-lint.php" in php_recipe
