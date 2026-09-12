"""The browser recipe installs one observed lock without resolving a new graph."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from orchestwin.web_execution.browser_automation import validate_lock
from scripts.verify_web_runner_manifest import validate_web_runner_manifest

ROOT = Path(__file__).resolve().parents[4]
RECIPE_ROOT = ROOT / "infra/web-runners/browser-locked"
OBSERVED_LOCK_HASH = "1b8e8ea4e50b4baa58a8fdf42882894a43e1f563d415e72f5441bb1179bff294"


def test_locked_recipe_preserves_the_real_observed_dependency_graph() -> None:
    lock_bytes = (RECIPE_ROOT / "package-lock.json").read_bytes()
    lock = json.loads(lock_bytes)
    package = json.loads((RECIPE_ROOT / "package.json").read_bytes())
    assert hashlib.sha256(lock_bytes).hexdigest() == OBSERVED_LOCK_HASH
    validate_lock(lock)
    assert package["dependencies"] == lock["packages"][""]["dependencies"]
    assert package["dependencies"] == {"axe-core": "4.13.0", "playwright": "1.62.1"}
    assert package["name"] == lock["name"]
    assert package["version"] == lock["version"]
    assert "scripts" not in package


def test_locked_browser_manifest_keeps_its_identity_and_pinned_base() -> None:
    manifest = json.loads((ROOT / "infra/web-runners/images.lock.json").read_bytes())
    browser = next(row for row in manifest["runners"] if row["runner_id"] == "web.browser")
    assert browser["version"] == "2.0.0"
    assert browser["kind"] == "BROWSER"
    assert browser["dockerfile_path"] == "infra/web-runners/browser-locked/Dockerfile"
    assert browser["base_image_ids"] == ["playwright-1.62.1-noble"]
    assert browser["capability_status"] == "DESIGN_ONLY_LEVEL_C"
    assert browser["built_image_reference"] is None
    base = next(
        row for row in manifest["base_images"] if row["image_id"] == browser["base_image_ids"][0]
    )
    instructions = (RECIPE_ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
    assert [line for line in instructions if line.startswith("FROM ")] == [
        f"FROM {base['reference']}"
    ]
    assert validate_web_runner_manifest(ROOT).is_valid


def test_browser_build_installs_only_the_copied_lock_and_retains_harness_tool_path() -> None:
    recipe = (RECIPE_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "npm install" not in recipe
    assert "package-lock-only" not in recipe
    assert "npm ci --ignore-scripts --omit=optional --no-audit --no-fund" in recipe
    assert "--registry=https://registry.npmjs.org" in recipe
    assert "COPY infra/web-runners/browser-locked/package.json" in recipe
    assert "COPY infra/web-runners/browser-locked/package-lock.json" in recipe
    assert "WORKDIR /opt/orchestwin/browser-automation" in recipe
    assert "ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1" in recipe
    assert "ENV HOME=/tmp" in recipe
    assert [line for line in recipe.splitlines() if line.startswith("USER ")][-1] == (
        "USER 65532:65532"
    )
    assert "ENTRYPOINT []" in recipe
    assert 'CMD ["node", "--version"]' in recipe


def test_legacy_browser_observation_recipe_bytes_are_preserved() -> None:
    expected = {
        "Dockerfile": "a61e0f597d5779d672e5ba1c21a0af124f7f768e7b9ed6837a1f496ace629ac5",
        "package.json": "9232d09caa833eb7d6383c3b26ef0317161f7002011d9a4d74fc5e429afdcaa8",
        "probe.cjs": "eb68c1c72b22da9184c0c2cdb7a8554a995e83ad712c02f9f717d3cc5735686f",
        "fixture.html": "075b9e0f013eca7ac9c95d03f7665280738fc5c6d8eed92df38cfc1c92be04a6",
        "seccomp.json": "c178b6b5777fbec3e392e49eb928a9a552db7ee8e90aa4da4d6788d78a2f7192",
    }
    for name, digest in expected.items():
        assert (
            hashlib.sha256(
                (ROOT / "infra/web-runners/browser-automation" / name).read_bytes()
            ).hexdigest()
            == digest
        )
    original = (ROOT / "infra/web-runners/Dockerfile.browser").read_text(encoding="utf-8")
    assert "USER pwuser" in original
    assert "npm ci" not in original
