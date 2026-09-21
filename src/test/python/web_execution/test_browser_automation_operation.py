"""Exercise the actual orchestration with a recorded-shape Docker transport double."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestwin.web_execution.browser_automation import (
    AutomationError,
    canonical_hash,
    verify_browser_automation,
)

from .test_browser_automation_contracts import parent_fixture, successful_probe


def output(value=b"", code=0):
    body = value if isinstance(value, bytes) else json.dumps(value).encode()
    return SimpleNamespace(status="COMPLETED", exit_code=code, stdout=body, stderr=b"")


class DockerDouble:
    def __init__(self, repo, failure=None):
        self.repo = repo
        self.calls = []
        self.failure = failure
        self.operation = None

    async def __call__(self, argv, timeout=30):
        self.calls.append(argv)
        if argv[0] == "git":
            if "rev-parse" in argv:
                return output(b"a" * 40)
            if "status" in argv:
                return output(b" M local.py" if self.failure == "dirty" else b"")
            if "show" in argv:
                return output((self.repo / argv[-1].removeprefix("HEAD:")).read_bytes())
            return output()
        if argv[1:3] == ("context", "show"):
            return output(b"desktop-linux")
        if argv[1:3] == ("context", "inspect"):
            endpoint = (
                "tcp://remote.invalid:2375"
                if self.failure == "remote"
                else "npipe:////./pipe/docker_engine"
            )
            return output([{"Endpoints": {"docker": {"Host": endpoint}}}])
        if "info" in argv:
            return output({"os": "linux", "arch": "amd64"})
        if "build" in argv:
            contents = {p.name for p in Path(argv[-1]).iterdir()}
            assert contents == {
                "Dockerfile",
                "package.json",
                "fixture.html",
                "probe.cjs",
                "seccomp.json",
            }
            return output(code=1 if self.failure == "build" else 0)
        if "image" in argv:
            return output([{"Id": "sha256:" + "f" * 64, "Os": "linux", "Architecture": "amd64"}])
        if "create" in argv:
            self.operation = argv[argv.index("--label") + 1].split("=", 1)[1]
            return output(b"containerid")
        if "start" in argv:
            if self.failure == "cancel":
                raise asyncio.CancelledError
            return output(successful_probe(), code=1 if self.failure == "probe" else 0)
        if "inspect" in argv:
            if self.failure == "cleanup-exception":
                raise OSError("sentinel-private-error")
            label = "other-operation" if self.failure == "foreign-container" else self.operation
            return output([{"Config": {"Labels": {"org.orchestwin.browser-probe": label}}}])
        if "rm" in argv:
            return output(code=1 if self.failure == "cleanup" else 0)
        raise AssertionError(argv)


def setup_operation(tmp_path):
    repo, parent, parent_data = parent_fixture(tmp_path)
    real = Path(__file__).resolve().parents[4] / "infra/web-runners/browser-automation"
    target = repo / "infra/web-runners/browser-automation"
    target.mkdir()
    for source in real.iterdir():
        if source.is_file():
            (target / source.name).write_bytes(source.read_bytes())
    # The new Dockerfile must keep exactly the original pinned browser base.
    original = repo / "infra/web-runners/Dockerfile.browser"
    original.write_text((target / "Dockerfile").read_text().splitlines()[0] + "\n")
    for item in parent_data["recipes"]:
        item["sha256"] = hashlib.sha256((repo / item["path"]).read_bytes()).hexdigest()
    parent_data.pop("content_hash")
    parent_data["content_hash"] = canonical_hash(parent_data)
    parent.write_text(json.dumps(parent_data))
    return repo, parent, tmp_path / "observations"


def test_success_requires_probe_evidence_cleanup_and_retains_parent(tmp_path):
    repo, parent, destination = setup_operation(tmp_path)
    original = parent.read_bytes()
    fake = DockerDouble(repo)
    result = asyncio.run(verify_browser_automation(repo, parent, destination, runner=fake))
    assert result["status"] == "BROWSER_AUTOMATION_PROBE_PASSED"
    assert result["browser_automation_verified"] is True
    assert result["level_d_validated"] is False
    assert result["formal_run_started"] is False
    assert result["generated_projects_authorized"] is False
    assert parent.read_bytes() == original
    saved = json.loads((destination / "manifest.json").read_bytes())
    supplied_hash = saved.pop("content_hash")
    assert canonical_hash(saved) == supplied_hash
    for artifact in saved["artifacts"]:
        body = (destination / artifact["path"]).read_bytes()
        assert artifact["sha256"] == hashlib.sha256(body).hexdigest()
    assert sum("build" in call for call in fake.calls) == 1
    assert not any("volume" in call or "prune" in call for call in fake.calls)


@pytest.mark.parametrize(
    "failure", ["build", "probe", "cleanup", "foreign-container", "cleanup-exception"]
)
def test_failure_preserves_manifest_without_success_flags(tmp_path, failure):
    repo, parent, destination = setup_operation(tmp_path)
    fake = DockerDouble(repo, failure)
    with pytest.raises(AutomationError):
        asyncio.run(verify_browser_automation(repo, parent, destination, runner=fake))
    saved = json.loads((destination / "manifest.json").read_bytes())
    assert saved["status"] == "FAILED"
    assert saved["browser_automation_verified"] is False
    if failure == "foreign-container":
        assert not any("rm" in call for call in fake.calls)
    assert "sentinel-private-error" not in (destination / "manifest.json").read_text()


@pytest.mark.parametrize("failure", ["dirty", "remote"])
def test_preflight_failures_do_not_build_or_create_observations(tmp_path, failure):
    repo, parent, destination = setup_operation(tmp_path)
    fake = DockerDouble(repo, failure)
    with pytest.raises(AutomationError):
        asyncio.run(verify_browser_automation(repo, parent, destination, runner=fake))
    assert not destination.exists()
    assert not any("build" in call for call in fake.calls)


def test_cancellation_cleans_owned_probe_and_records_failure(tmp_path):
    repo, parent, destination = setup_operation(tmp_path)
    fake = DockerDouble(repo, "cancel")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(verify_browser_automation(repo, parent, destination, runner=fake))
    saved = json.loads((destination / "manifest.json").read_bytes())
    assert saved["status"] == "FAILED"
    assert saved["cleanup_confirmed"] is True
    assert saved["browser_automation_verified"] is False


def test_output_directory_cannot_be_reused(tmp_path):
    repo, parent, destination = setup_operation(tmp_path)
    destination.mkdir()
    fake = DockerDouble(repo)
    with pytest.raises(AutomationError):
        asyncio.run(verify_browser_automation(repo, parent, destination, runner=fake))
    assert fake.calls == []
