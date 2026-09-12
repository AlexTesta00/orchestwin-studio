"""Browser access is bound to the owned execution attempt and isolated server."""

import asyncio
import json
from uuid import uuid4

import pytest

from orchestwin.sandbox.host_process import BoundedHostProcessResult
from orchestwin.web_execution.phase_runtime import WebBrowserCleanupFailure, WebPhaseRuntimeError
from orchestwin.web_execution.plans import WebExecutionPhase

from .test_phase_executor import setup_executor
from .test_phase_runtime import IMAGE, Host, runtime, static_command


def test_attempt_binding_is_fixed_before_source_execution(tmp_path):
    async def scenario():
        executor, contract, *_ = setup_executor(tmp_path)
        attempt_id = uuid4()
        executor.bind_attempt(attempt_id)
        assert executor.execution_attempt_id == attempt_id
        with pytest.raises(ValueError):
            executor.bind_attempt(uuid4())
        result = await executor.execute(
            contract.execution_plan.phase(WebExecutionPhase.VALIDATE), contract=contract
        )
        assert result.status.value == "PASSED"
        with pytest.raises(ValueError):
            executor.bind_attempt(attempt_id)
        await executor.finalize()

    asyncio.run(scenario())


def test_finalization_preserves_unresolved_browser_cleanup_diagnostics(tmp_path):
    observation = BoundedHostProcessResult("COMPLETED", 1, b"", b"removal failed", None)

    class Runtime:
        browser_cleanup_failures = (
            WebBrowserCleanupFailure(
                "f" * 32, "e" * 64, "owned-browser", (("REMOVE", observation),)
            ),
        )

        async def close(self):
            raise WebPhaseRuntimeError("WEB_BROWSER_CLEANUP_UNCONFIRMED")

    async def scenario():
        executor, contract, store, _ = setup_executor(tmp_path)
        await executor.execute(
            contract.execution_plan.phase(WebExecutionPhase.VALIDATE), contract=contract
        )
        executor.runtime = Runtime()
        try:
            result = await executor.finalize()
            assert result.is_failure and executor.workspace.path.exists()
            manifest = next(
                json.loads(store.read(ref.storage_key))
                for ref in result.artifact_refs
                if b'"browser_cleanup_failures"' in store.read(ref.storage_key)
            )
            failure = manifest["observations"]["browser_cleanup_failures"][0]
            assert failure["container_id"] == "e" * 64
            assert (
                store.read(failure["operations"][0]["stderr_ref"]["storage_key"])
                == b"removal failed"
            )
        finally:
            executor.workspace.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", [None, "network", "image", "running", "id", "user"])
def test_browser_network_requires_owned_running_isolated_container(tmp_path, monkeypatch, invalid):
    async def scenario():
        adapter = runtime(tmp_path, Host())
        name = await adapter.start_command(static_command())
        data = {
            "Id": "d" * 64,
            "Image": IMAGE,
            "State": {"Running": True},
            "Config": {"User": "65532:65532"},
            "HostConfig": {"NetworkMode": "none"},
        }
        if invalid == "network":
            data["HostConfig"]["NetworkMode"] = "host"
        elif invalid == "image":
            data["Image"] = "sha256:" + "e" * 64
        elif invalid == "running":
            data["State"]["Running"] = False
        elif invalid == "id":
            data["Id"] = "another-server"
        elif invalid == "user":
            data["Config"]["User"] = "root"

        async def inspect(*argv):
            assert argv == ("inspect", name)
            return data

        monkeypatch.setattr(adapter, "_inspect", inspect)
        try:
            if invalid:
                with pytest.raises(WebPhaseRuntimeError):
                    await adapter.browser_network()
            else:
                assert await adapter.browser_network() == "d" * 64
        finally:
            await adapter.close()

    asyncio.run(scenario())
