"""Verify Docker command construction and manifests without using Docker."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from orchestwin.web_execution import local_runners as module

REPOSITORY_ROOT = Path(__file__).parents[4]

NODE_DOCKERFILE = (
    "FROM node:26@sha256:" + "a" * 64 + "\n"
    "COPY --chown=node:node infra/web-runners/bin/static-server.mjs "
    "/opt/orchestwin/bin/static-server.mjs\nUSER node\n"
)
BROWSER_DOCKERFILE = "FROM example/browser:v1@sha256:" + "b" * 64 + "\nUSER pwuser\n"


def sources(root: Path):
    for name in (
        "Dockerfile.node",
        "Dockerfile.php",
        "Dockerfile.browser",
        "images.lock.json",
        "bin/static-server.mjs",
        "bin/php-lint.php",
        "packages/unzip_6.0-28+deb12u1_amd64.deb",
        "browser-locked/Dockerfile",
        "browser-locked/package.json",
        "browser-locked/package-lock.json",
    ):
        path = root / "infra/web-runners" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY_ROOT / "infra/web-runners" / name, path)
    (root / ".env").write_text("DO_NOT_COPY=secret\n")
    return root


class FakeDocker:
    def __init__(
        self,
        *,
        context="npipe:////./pipe/docker_engine",
        fail_smoke=False,
        bad_probe=None,
        bad_environment=False,
        bad_builder=False,
        dirty=False,
        changed_after_build=False,
        transport="COMPLETED",
    ):
        self.calls = []
        self.context = context
        self.fail_smoke = fail_smoke
        self.seen_context_paths = []
        self.limits = []
        self.bad_probe = bad_probe
        self.bad_environment = bad_environment
        self.bad_builder = bad_builder
        self.dirty = dirty
        self.changed_after_build = changed_after_build
        self.transport = transport

    async def __call__(self, argv, **_kwargs):
        self.calls.append(argv)
        self.limits.append(_kwargs)
        if argv[0] == "git" and "rev-parse" in argv:
            return module.CommandOutput(0, ("a" * 40).encode(), b"")
        if argv[0] == "git" and "status" in argv:
            dirty = self.dirty or (
                self.changed_after_build and any("build" in call for call in self.calls)
            )
            return module.CommandOutput(0, b" M changed" if dirty else b"", b"")
        if argv[0] == "git" and "show" in argv:
            return module.CommandOutput(
                0, (Path(argv[2]) / argv[-1].split(":", 1)[1]).read_bytes(), b""
            )
        if "context" in argv and "show" in argv:
            payload = b"desktop-linux"
        elif "context" in argv and "inspect" in argv:
            payload = json.dumps([{"Endpoints": {"docker": {"Host": self.context}}}]).encode()
        elif "buildx" in argv:
            payload = (
                b"Driver: docker\nEndpoint: remote-builder\n"
                if self.bad_builder
                else b"Driver: docker\nEndpoint: desktop-linux\n"
            )
        elif "version" in argv:
            payload = b'{"client_version":"28.0.0","server_version":"28.0.0"}'
        elif "info" in argv:
            payload = json.dumps(
                {
                    "os": "linux",
                    "arch": "x86_64",
                    "kernel_version": "test-kernel",
                    "operating_system": "test-linux",
                    "private_extra": "must-not-be-exported",
                }
            ).encode()
            if self.bad_environment:
                payload = b'{"os":"linux","arch":"x86_64"}'
        elif "build" in argv:
            context = Path(argv[-1])
            self.seen_context_paths = [
                path.relative_to(context).as_posix()
                for path in context.rglob("*")
                if path.is_file()
            ]
            payload = b"built"
        elif "image" in argv and "inspect" in argv:
            payload = json.dumps(
                [
                    {
                        "Id": "sha256:" + "c" * 64,
                        "Os": "linux",
                        "Architecture": "amd64",
                        "Config": {"User": "1000"},
                    }
                ]
            ).encode()
        elif "run" in argv:
            if self.fail_smoke:
                return module.CommandOutput(1, b"", b"private stderr sentinel")
            if "php" in argv:
                observation = {
                    "php_version": "8.4.24",
                    "composer_version": "2.10.2",
                    "uid": 65532,
                    "php_lint_valid": True,
                    "php_lint_invalid_rejected": True,
                    "php_http": True,
                }
            elif "static-server.mjs" in argv[-1]:
                observation = {
                    "node_version": "v26.7.0",
                    "npm_version": "11.0.0",
                    "uid": 65532,
                    "static_http": True,
                }
            else:
                lock = (
                    REPOSITORY_ROOT / "infra/web-runners/browser-locked/package-lock.json"
                ).read_bytes()
                observation = {
                    "node_version": "v24.0.0",
                    "npm_version": "11.0.0",
                    "uid": 65532,
                    "browser_binaries_present": True,
                    "playwright_package_resolvable": True,
                    "playwright_version": "1.62.1",
                    "playwright_core_version": "1.62.1",
                    "axe_version": "4.13.0",
                    "chromium_version_output": "Google Chrome for Testing 151.0.7922.34",
                    "package_lock_sha256": hashlib.sha256(lock).hexdigest(),
                }
            if self.bad_probe:
                observation.update(self.bad_probe)
            payload = json.dumps(observation).encode()
            return module.CommandOutput(0, payload, b"", self.transport)
        else:
            payload = b""
        return module.CommandOutput(0, payload, b"")


def test_build_uses_minimal_context_and_content_pinned_run(tmp_path: Path) -> None:
    root = sources(tmp_path / "repo")
    fake = FakeDocker()
    result = asyncio.run(
        module.build_and_probe_local_web_runners(
            root,
            tmp_path / "evidence",
            runner=fake,
        )
    )
    assert ".env" not in fake.seen_context_paths
    assert "infra/web-runners/Dockerfile.php" in fake.seen_context_paths
    assert "infra/web-runners/browser-locked/package-lock.json" in fake.seen_context_paths
    assert "infra/web-runners/Dockerfile.browser" not in fake.seen_context_paths
    run_calls = [call for call in fake.calls if "run" in call]
    assert len(run_calls) == 3
    for call in run_calls:
        assert call[call.index("--network") + 1] == "none"
        assert "--read-only" in call and "--cap-drop" in call
        assert "--pull=never" in call
        assert "sha256:" + "c" * 64 in call
        assert "--privileged" not in call and "--publish" not in call
        assert "--volume" not in call and "--mount" not in call
        assert call[call.index("--user") + 1] == "65532:65532"
        assert all(flag in call for flag in ("--cpus", "--memory", "--pids-limit", "--tmpfs"))
    assert result["formal_run_started"] is False
    assert result["level_d_validated"] is False
    assert result["browser_automation_verified"] is False
    assert result["schema_version"] == 2
    assert {runner["kind"] for runner in result["runners"]} == {"NODE", "PHP", "BROWSER"}
    assert result["runners"][0]["image_id_kind"] == "LOCAL_CONFIG_DIGEST"
    assert (tmp_path / "evidence/manifest.json").is_file()
    assert result == json.loads((tmp_path / "evidence/manifest.json").read_text())
    content = {key: value for key, value in result.items() if key != "content_hash"}
    assert (
        result["content_hash"]
        == hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )
    assert "private_extra" not in json.dumps(result)
    assert "must-not-be-exported" not in json.dumps(result)
    assert all(len(runner["recipe_content_hash"]) == 64 for runner in result["runners"])
    for call in (call for call in fake.calls if "build" in call):
        assert call[call.index("--builder") + 1] == "desktop-linux"
        assert "--network" in call
    for artifact in result["artifacts"]:
        raw = (tmp_path / "evidence" / artifact["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == artifact["sha256"]


def test_remote_context_is_rejected_before_build(tmp_path: Path) -> None:
    root = sources(tmp_path / "repo")
    fake = FakeDocker(context="tcp://remote.example:2376")
    with pytest.raises(module.RunnerBootstrapError, match="LOCAL_DOCKER_CONTEXT_REQUIRED"):
        asyncio.run(module.build_and_probe_local_web_runners(root, tmp_path / "out", runner=fake))
    assert not any("build" in call for call in fake.calls)


def test_failed_probe_has_no_success_manifest_and_cleans_its_container(tmp_path: Path) -> None:
    root = sources(tmp_path / "repo")
    fake = FakeDocker(fail_smoke=True)
    with pytest.raises(module.RunnerBootstrapError) as caught:
        asyncio.run(module.build_and_probe_local_web_runners(root, tmp_path / "out", runner=fake))
    assert "private stderr" not in str(caught.value)
    assert any("rm" in call and "--force" in call for call in fake.calls)
    manifest = json.loads((tmp_path / "out/manifest.json").read_text())
    assert manifest["status"] == "FAILED"
    assert manifest["level_d_validated"] is False


def test_refuses_existing_output(tmp_path: Path) -> None:
    root = sources(tmp_path / "repo")
    output = tmp_path / "out"
    output.mkdir()
    with pytest.raises(module.RunnerBootstrapError, match="OUTPUT_ALREADY_EXISTS"):
        asyncio.run(module.build_and_probe_local_web_runners(root, output, runner=FakeDocker()))


def test_refuses_output_inside_repository(tmp_path: Path) -> None:
    root = sources(tmp_path / "repo")
    with pytest.raises(module.RunnerBootstrapError, match="OUTPUT_MUST_BE_OUTSIDE_REPOSITORY"):
        asyncio.run(
            module.build_and_probe_local_web_runners(root, root / "out", runner=FakeDocker())
        )


def test_rejects_unpinned_recipe(tmp_path: Path) -> None:
    root = sources(tmp_path / "repo")
    (root / "infra/web-runners/Dockerfile.node").write_text("FROM node:latest\n")
    fake = FakeDocker()
    with pytest.raises(module.RunnerBootstrapError, match="RUNNER_BASE_NOT_PINNED"):
        asyncio.run(module.build_and_probe_local_web_runners(root, tmp_path / "out", runner=fake))
    assert not any("build" in call for call in fake.calls)


def test_cli_requires_explicit_build_permission() -> None:
    with pytest.raises(SystemExit) as caught:
        module.main(["--repo-root", ".", "--output-root", "out"])
    assert caught.value.code != 0


def test_rejects_parent_traversal_in_evidence_root(tmp_path: Path) -> None:
    root = sources(tmp_path / "repo")
    with pytest.raises(module.RunnerBootstrapError, match="OUTPUT_PATH_NOT_CANONICAL"):
        asyncio.run(
            module.build_and_probe_local_web_runners(
                root,
                tmp_path / "outside" / ".." / "out",
                runner=FakeDocker(),
            )
        )


def test_rejects_additional_unpinned_from_stage(tmp_path: Path) -> None:
    root = sources(tmp_path / "repo")
    path = root / "infra/web-runners/Dockerfile.node"
    path.write_text(path.read_text() + "FROM node:latest\n")
    fake = FakeDocker()
    with pytest.raises(module.RunnerBootstrapError, match="RUNNER_BASE_NOT_PINNED"):
        asyncio.run(module.build_and_probe_local_web_runners(root, tmp_path / "out", runner=fake))
    assert not any("build" in call for call in fake.calls)


def test_cli_redacts_unexpected_container_metadata(monkeypatch, capsys) -> None:
    async def malformed(*_args, **_kwargs):
        raise KeyError("private metadata sentinel")

    monkeypatch.setattr(module, "build_and_probe_local_web_runners", malformed)
    result = module.main(["--repo-root", ".", "--output-root", "out", "--build-runners"])
    captured = capsys.readouterr()
    assert result == 1
    assert "private metadata sentinel" not in captured.out + captured.err
    assert json.loads(captured.out)["code"] == "KeyError"


@pytest.mark.parametrize(
    "bad_probe",
    [
        {"uid": 0},
        {"npm_version": ""},
        {"php_version": "8.0.0"},
        {"composer_version": ""},
        {"php_lint_valid": False},
        {"php_lint_invalid_rejected": False},
        {"php_http": False},
        {"playwright_version": "0.0.0"},
        {"axe_version": "0.0.0"},
        {"package_lock_sha256": "0" * 64},
        {"browser_binaries_present": False},
        {"playwright_package_resolvable": False},
    ],
)
def test_incomplete_or_mismatched_observed_tools_fail_closed(tmp_path: Path, bad_probe) -> None:
    root = sources(tmp_path / "repo")
    with pytest.raises(module.RunnerBootstrapError):
        asyncio.run(
            module.build_and_probe_local_web_runners(
                root, tmp_path / "out", runner=FakeDocker(bad_probe=bad_probe)
            )
        )
    manifest = json.loads((tmp_path / "out/manifest.json").read_text())
    assert manifest["status"] == "FAILED"
    assert manifest["level_d_validated"] is False


@pytest.mark.parametrize("transport", ["TIMEOUT", "OUTPUT_LIMIT_EXCEEDED"])
def test_incomplete_transport_never_records_success(tmp_path: Path, transport: str) -> None:
    root = sources(tmp_path / "repo")
    fake = FakeDocker(transport=transport)
    with pytest.raises(module.RunnerBootstrapError):
        asyncio.run(module.build_and_probe_local_web_runners(root, tmp_path / "out", runner=fake))
    assert any("rm" in call for call in fake.calls)


@pytest.mark.parametrize("condition", ["bad_environment", "bad_builder", "dirty"])
def test_invalid_environment_or_uncommitted_tree_blocks_before_build(
    tmp_path: Path, condition: str
) -> None:
    root = sources(tmp_path / "repo")
    fake = FakeDocker(**{condition: True})
    with pytest.raises(module.RunnerBootstrapError):
        asyncio.run(module.build_and_probe_local_web_runners(root, tmp_path / "out", runner=fake))
    assert not any("build" in call for call in fake.calls)


def test_changed_working_tree_during_build_cannot_produce_success_manifest(tmp_path: Path) -> None:
    root = sources(tmp_path / "repo")
    with pytest.raises(module.RunnerBootstrapError, match="WORKING_TREE"):
        asyncio.run(
            module.build_and_probe_local_web_runners(
                root, tmp_path / "out", runner=FakeDocker(changed_after_build=True)
            )
        )
    assert json.loads((tmp_path / "out/manifest.json").read_text())["status"] == "FAILED"


@pytest.mark.parametrize(
    ("version_output", "expected"),
    [
        ("Chromium 149.0.0.0", "149.0.0.0"),
        # Observed from the pinned d641dc1 image as UID 65532, with exit code zero.
        ("Google Chrome for Testing 151.0.7922.34", "151.0.7922.34"),
    ],
)
def test_browser_version_is_parsed_from_observed_product_output(
    tmp_path: Path, version_output: str, expected: str
) -> None:
    root = sources(tmp_path / "repo")
    result = asyncio.run(
        module.build_and_probe_local_web_runners(
            root,
            tmp_path / "out",
            runner=FakeDocker(
                bad_probe={"chromium_version_output": version_output, "chromium_version": None}
            ),
        )
    )
    browser = next(row for row in result["runners"] if row["kind"] == "BROWSER")
    assert browser["probe"]["chromium_version"] == expected
    assert browser["probe"]["chromium_version_output"] == version_output
    assert result["browser_automation_verified"] is False
    assert result["level_d_validated"] is False


@pytest.mark.parametrize(
    "version_output",
    [
        None,
        "",
        "151.0.7922.34",
        "Unknown 151.0.7922.34",
        "Chromium 151.0",
        "Chromium 151.0.7922.34 extra",
    ],
)
def test_invalid_browser_product_output_cannot_use_a_claimed_version(
    tmp_path: Path, version_output: str | None
) -> None:
    root = sources(tmp_path / "repo")
    with pytest.raises(module.RunnerBootstrapError):
        asyncio.run(
            module.build_and_probe_local_web_runners(
                root,
                tmp_path / "out",
                runner=FakeDocker(
                    bad_probe={
                        "chromium_version_output": version_output,
                        "chromium_version": "151.0.7922.34",
                    }
                ),
            )
        )
    assert json.loads((tmp_path / "out/manifest.json").read_text())["status"] == "FAILED"
