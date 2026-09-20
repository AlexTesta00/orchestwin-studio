"""Cancellation and failed cleanup must stop later runner builds."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from orchestwin.web_execution import local_runners as module

from .test_local_runner_bootstrap import FakeDocker, sources


class CleanupDocker(FakeDocker):
    """Control the exact cleanup await without Docker or timing-based sleeps."""

    def __init__(self, *, blocked: bool = False, outcome: str = "removed") -> None:
        super().__init__()
        self.cleanup_started = asyncio.Event()
        self.cleanup_release = asyncio.Event()
        if not blocked:
            self.cleanup_release.set()
        self.cleanup_finished = False
        self.outcome = outcome

    async def __call__(self, argv, **kwargs):
        if "rm" not in argv or "--force" not in argv:
            return await super().__call__(argv, **kwargs)
        self.calls.append(argv)
        self.limits.append(kwargs)
        self.cleanup_started.set()
        await self.cleanup_release.wait()
        self.cleanup_finished = True
        if self.outcome == "removed":
            return module.CommandOutput(0, b"", b"")
        if self.outcome == "already-removed":
            return module.CommandOutput(
                1, b"", f"Error response from daemon: No such container: {argv[-1]}".encode()
            )
        if self.outcome == "different-container":
            return module.CommandOutput(
                1, b"", b"Error response from daemon: No such container: unrelated-container"
            )
        if self.outcome == "transport-failure":
            return module.CommandOutput(0, b"", b"", "TIMED_OUT")
        return module.CommandOutput(1, b"", b"private cleanup error sentinel")


def _assert_failed_first_runner(output: Path, fake: CleanupDocker) -> None:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "FAILED"
    assert manifest["level_d_validated"] is False
    assert manifest["formal_run_started"] is False
    assert len(manifest["runners"]) == 1
    assert len([call for call in fake.calls if "build" in call]) == 1
    probes = [call for call in fake.calls if "run" in call]
    cleanups = [call for call in fake.calls if "rm" in call]
    assert len(probes) == len(cleanups) == 1
    assert cleanups[0][-1] == probes[0][probes[0].index("--name") + 1]


@pytest.mark.parametrize("cancel_count", [1, 3])
def test_cancellation_during_success_cleanup_is_propagated_after_cleanup_finishes(
    tmp_path: Path, cancel_count: int
) -> None:
    root = sources(tmp_path / "repo")
    output = tmp_path / "output"

    async def scenario() -> None:
        fake = CleanupDocker(blocked=True)
        task = asyncio.create_task(
            module.build_and_probe_local_web_runners(root, output, runner=fake)
        )
        try:
            await asyncio.wait_for(fake.cleanup_started.wait(), timeout=3)
            for _ in range(cancel_count):
                task.cancel()
                # Yield to the pending cancellation; cleanup remains blocked on its event.
                await asyncio.sleep(0)
                assert not task.done()
                assert not fake.cleanup_finished
            fake.cleanup_release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=3)
            assert fake.cleanup_finished
            _assert_failed_first_runner(output, fake)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            assert manifest["runners"][0]["cleanup_confirmed"] is True
        finally:
            fake.cleanup_release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["failed", "different-container", "transport-failure"])
def test_unconfirmed_cleanup_records_failure_and_prevents_later_builds(
    tmp_path: Path, outcome: str
) -> None:
    root = sources(tmp_path / "repo")
    output = tmp_path / "output"

    async def scenario() -> None:
        fake = CleanupDocker(outcome=outcome)
        with pytest.raises(module.RunnerBootstrapError, match="PROBE_CLEANUP_NOT_CONFIRMED"):
            await module.build_and_probe_local_web_runners(root, output, runner=fake)
        assert fake.cleanup_finished
        _assert_failed_first_runner(output, fake)

    asyncio.run(scenario())


def test_cleanup_accepts_only_the_exact_probe_container_already_removed(tmp_path: Path) -> None:
    root = sources(tmp_path / "repo")

    async def scenario() -> None:
        fake = CleanupDocker(outcome="already-removed")
        result = await module.build_and_probe_local_web_runners(
            root, tmp_path / "output", runner=fake
        )
        assert result["status"] == "IMAGES_BUILT_PROBES_RECORDED"
        assert len(result["runners"]) == 3
        assert all(runner["cleanup_confirmed"] is True for runner in result["runners"])

    asyncio.run(scenario())
