"""Verify Docker command construction and manifests without using Docker."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from orchestwin.web_execution import local_runners as module

NODE_DOCKERFILE = (
    "FROM node:26@sha256:" + "a" * 64 + "\n"
    "COPY --chown=node:node infra/web-runners/bin/static-server.mjs "
    "/opt/orchestwin/bin/static-server.mjs\nUSER node\n"
)
BROWSER_DOCKERFILE = "FROM example/browser:v1@sha256:" + "b" * 64 + "\nUSER pwuser\n"


def sources(root: Path):
    folder = root / "infra/web-runners"
    (folder / "bin").mkdir(parents=True)
    (folder / "Dockerfile.node").write_text(NODE_DOCKERFILE)
    (folder / "Dockerfile.browser").write_text(BROWSER_DOCKERFILE)
    (folder / "bin/static-server.mjs").write_text("// trusted recipe helper\n")
    (root / ".env").write_text("DO_NOT_COPY=secret\n")
    return root


class FakeDocker:
    def __init__(self, *, context="npipe:////./pipe/docker_engine", fail_smoke=False):
        self.calls = []
        self.context = context
        self.fail_smoke = fail_smoke
        self.seen_context_paths = []

    async def __call__(self, argv, **_kwargs):
        self.calls.append(argv)
        if argv[0] == "git" and "rev-parse" in argv:
            return module.CommandOutput(0, ("a" * 40).encode(), b"")
        if argv[0] == "git" and "status" in argv:
            return module.CommandOutput(0, b"", b"")
        if "context" in argv and "show" in argv:
            payload = b"desktop-linux"
        elif "context" in argv and "inspect" in argv:
            payload = json.dumps([{"Endpoints": {"docker": {"Host": self.context}}}]).encode()
        elif "info" in argv:
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
            if "static-server.mjs" in argv[-1]:
                payload = b'{"node_version":"v26.7.0","uid":65532,"static_http":true}'
            else:
                payload = b'{"node_version":"v26.7.0","uid":65532,"browser_binaries_present":true,"playwright_package_resolvable":false}'
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
    assert not any("php" in item for item in fake.seen_context_paths)
    run_calls = [call for call in fake.calls if "run" in call]
    assert len(run_calls) == 2
    for call in run_calls:
        assert call[call.index("--network") + 1] == "none"
        assert "--read-only" in call and "--cap-drop" in call
        assert "--pull=never" in call
        assert "sha256:" + "c" * 64 in call
        assert "--privileged" not in call and "--publish" not in call
    assert result["formal_run_started"] is False
    assert result["level_d_validated"] is False
    assert result["browser_automation_verified"] is False
    assert result["runners"][0]["image_id_kind"] == "LOCAL_CONFIG_DIGEST"
    assert (tmp_path / "evidence/manifest.json").is_file()


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
    (root / "infra/web-runners/Dockerfile.node").write_text(NODE_DOCKERFILE + "FROM node:latest\n")
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
