"""Bootstrap input identities bind only pinned, bounded repository recipes."""

from __future__ import annotations

import base64
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from orchestwin.web_execution.runner_bootstrap_inputs import load_bootstrap_inputs

PREFIX = "infra/web-runners"
LOCK = f"{PREFIX}/images.lock.json"
BROWSER = f"{PREFIX}/browser-locked"
BASES = {
    "node": "docker.io/library/node:26.7.0@sha256:" + "a" * 64,
    "php": "docker.io/library/php:8.4.24@sha256:" + "b" * 64,
    "composer": "docker.io/library/composer:2.10.2@sha256:" + "c" * 64,
    "browser": "mcr.microsoft.com/playwright:v1.62.1-noble@sha256:" + "d" * 64,
}


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(root: Path) -> Path:
    """Synthetic input fixture only; these digests never enter production files."""
    files = {
        f"{PREFIX}/Dockerfile.node": f"FROM {BASES['node']}\nUSER node\n",
        f"{PREFIX}/bin/static-server.mjs": "// controlled static server fixture\n",
        f"{PREFIX}/Dockerfile.php": (
            f"FROM {BASES['composer']} AS composer_source\nFROM {BASES['php']}\nUSER runner\n"
        ),
        f"{PREFIX}/bin/php-lint.php": "<?php exit(0);\n",
        f"{BROWSER}/Dockerfile": f"FROM {BASES['browser']}\nUSER pwuser\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    dependencies = {"axe-core": "4.13.0", "playwright": "1.62.1"}
    package = {"name": "orchestwin-browser-tools", "version": "1.0.0", "dependencies": dependencies}
    _write_json(root / BROWSER / "package.json", package)
    _write_json(
        root / BROWSER / "package-lock.json",
        {
            "name": package["name"],
            "version": package["version"],
            "lockfileVersion": 3,
            "packages": {
                "": package,
                **{
                    f"node_modules/{name}": {
                        "version": version,
                        "resolved": f"https://registry.npmjs.org/{name}/-/{name}-{version}.tgz",
                        "integrity": "sha512-" + base64.b64encode(bytes(64)).decode(),
                    }
                    for name, version in {
                        **dependencies,
                        "playwright-core": "1.62.1",
                    }.items()
                },
            },
        },
    )
    _write_json(
        root / LOCK,
        {
            "schema_version": 1,
            "base_images": [
                {
                    "image_id": name,
                    "reference": reference,
                    "platform_scope": "linux-amd64",
                    "source": "https://example.test/fixture",
                    "retrieved_at": "2026-09-12",
                }
                for name, reference in BASES.items()
            ],
            "runners": [
                {
                    "runner_id": f"web.{kind}",
                    "kind": kind.upper(),
                    "version": "1.0.0",
                    "dockerfile_path": (
                        f"{BROWSER}/Dockerfile"
                        if kind == "browser"
                        else f"{PREFIX}/Dockerfile.{kind}"
                    ),
                    "base_image_ids": [kind, "composer"] if kind == "php" else [kind],
                    "output_repository": f"orchestwin/web-{kind}-runner",
                    "capability_status": "DESIGN_ONLY_LEVEL_C",
                    "built_image_reference": None,
                }
                for kind in ("node", "php", "browser")
            ],
        },
    )
    (root / ".env").write_text("PRIVATE_VALUE=must-not-enter-build-context", encoding="utf-8")
    return root


def test_inputs_capture_exact_three_runner_recipes_and_no_other_repository_files(tmp_path) -> None:
    root = _fixture(tmp_path / "repo")
    inputs = load_bootstrap_inputs(root)
    sources = dict(inputs.sources)

    assert len(sources) == 8
    assert tuple(sources) == tuple(sorted(sources))
    assert LOCK in sources
    assert ".env" not in sources
    assert {recipe.kind for recipe in inputs.runners} == {"NODE", "PHP", "BROWSER"}
    assert all(len(recipe.recipe_content_hash) == 64 for recipe in inputs.runners)
    assert all(recipe.runner_id == f"web.{recipe.kind.lower()}" for recipe in inputs.runners)
    assert all(recipe.version == "1.0.0" for recipe in inputs.runners)
    browser = next(recipe for recipe in inputs.runners if recipe.kind == "BROWSER")
    assert browser.dockerfile_path == f"{BROWSER}/Dockerfile"
    assert browser.source_paths == tuple(
        sorted(f"{BROWSER}/{name}" for name in ("Dockerfile", "package.json", "package-lock.json"))
    )
    php = next(recipe for recipe in inputs.runners if recipe.kind == "PHP")
    assert php.base_image_references == tuple(sorted((BASES["php"], BASES["composer"])))
    assert inputs == load_bootstrap_inputs(root)
    assert len(inputs.content_hash) == 64
    with pytest.raises(FrozenInstanceError):
        inputs.content_hash = "0" * 64


def test_helper_changes_only_its_runner_recipe_identity_and_full_input_hash(tmp_path) -> None:
    root = _fixture(tmp_path / "repo")
    before = load_bootstrap_inputs(root)
    helper = root / PREFIX / "bin/php-lint.php"
    helper.write_text("<?php exit(1);\n", encoding="utf-8")
    after = load_bootstrap_inputs(root)

    assert before.content_hash != after.content_hash
    previous = {recipe.kind: recipe.recipe_content_hash for recipe in before.runners}
    changed = {recipe.kind: recipe.recipe_content_hash for recipe in after.runners}
    assert previous["PHP"] != changed["PHP"]
    assert previous["NODE"] == changed["NODE"]
    assert previous["BROWSER"] == changed["BROWSER"]


@pytest.mark.parametrize("kind", ["NODE", "PHP", "BROWSER"])
def test_lock_cannot_identify_a_different_dockerfile_from_the_captured_recipe(tmp_path, kind):
    root = _fixture(tmp_path / "repo")
    lock = json.loads((root / LOCK).read_text())
    runner = next(runner for runner in lock["runners"] if runner["kind"] == kind)
    runner["dockerfile_path"] = f"{PREFIX}/Dockerfile.legacy"
    _write_json(root / LOCK, lock)
    with pytest.raises(ValueError, match=r"^BOOTSTRAP_DOCKERFILE_PATH_LOCK_MISMATCH$"):
        load_bootstrap_inputs(root)


@pytest.mark.parametrize("field", ["version", "source"])
def test_lock_identity_changes_are_never_omitted_from_hashes(tmp_path, field) -> None:
    root = _fixture(tmp_path / "repo")
    before = load_bootstrap_inputs(root)
    lock = json.loads((root / LOCK).read_text())
    if field == "version":
        lock["runners"][0][field] = "2.0.0"
    else:
        lock["base_images"][0][field] = "https://example.test/changed"
    _write_json(root / LOCK, lock)
    after = load_bootstrap_inputs(root)

    assert before.content_hash != after.content_hash
    if field == "version":
        assert next(recipe for recipe in before.runners if recipe.kind == "NODE") != next(
            recipe for recipe in after.runners if recipe.kind == "NODE"
        )


@pytest.mark.parametrize(
    "recipe",
    [
        "FROM node:latest\nUSER node\n",
        f"FROM {BASES['node']}\nFROM php:latest AS extra\nUSER node\n",
        f"FROM {BASES['php']}\nUSER node\n",
        f"FROM --platform=linux/amd64 {BASES['node']}\nUSER node\n",
        f"FROM {BASES['node']}\nUSER root\n",
        f"FROM {BASES['node']}\nUSER 0:1000\n",
        f"FROM {BASES['node']}\nUSER node\nFROM {BASES['node']}\n",
    ],
)
def test_unpinned_mismatching_or_root_final_stages_are_rejected(tmp_path, recipe) -> None:
    root = _fixture(tmp_path / "repo")
    (root / PREFIX / "Dockerfile.node").write_text(recipe, encoding="utf-8")
    with pytest.raises(ValueError, match=r"^BOOTSTRAP_"):
        load_bootstrap_inputs(root)


@pytest.mark.parametrize("changed", ["package", "lock-root", "integrity", "extra-dependency"])
def test_browser_package_and_lock_must_describe_the_exact_supported_tools(
    tmp_path, changed
) -> None:
    root = _fixture(tmp_path / "repo")
    package_path = root / BROWSER / "package.json"
    lock_path = root / BROWSER / "package-lock.json"
    package = json.loads(package_path.read_text())
    lock = json.loads(lock_path.read_text())
    if changed == "package":
        package["name"] = "different-package"
    elif changed == "lock-root":
        lock["packages"][""]["version"] = "99.0.0"
    elif changed == "integrity":
        lock["packages"]["node_modules/axe-core"]["integrity"] = "sha512-not-valid"
    else:
        package["devDependencies"] = {"unlocked": "*"}
    _write_json(package_path, package)
    _write_json(lock_path, lock)
    with pytest.raises(ValueError, match=r"^BOOTSTRAP_"):
        load_bootstrap_inputs(root)


@pytest.mark.parametrize(
    "filename", [LOCK, f"{BROWSER}/package.json", f"{BROWSER}/package-lock.json"]
)
def test_json_duplicate_keys_are_rejected_before_they_can_be_normalized(tmp_path, filename) -> None:
    root = _fixture(tmp_path / "repo")
    (root / filename).write_text('{"name":"one","name":"two"}', encoding="utf-8")
    with pytest.raises(ValueError, match=r"^BOOTSTRAP_"):
        load_bootstrap_inputs(root)


@pytest.mark.parametrize("condition", ["missing", "oversized", "symlink", "junction"])
def test_recipe_reads_reject_missing_oversized_or_redirected_paths(
    tmp_path, monkeypatch, condition
):
    root = _fixture(tmp_path / "repo")
    path = root / PREFIX / "bin/php-lint.php"
    if condition == "missing":
        path.unlink()
    elif condition == "oversized":
        path.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    else:
        method = "is_symlink" if condition == "symlink" else "is_junction"
        original = getattr(Path, method)
        monkeypatch.setattr(Path, method, lambda self: self == path.parent or original(self))
    with pytest.raises(ValueError, match=r"^BOOTSTRAP_"):
        load_bootstrap_inputs(root)
