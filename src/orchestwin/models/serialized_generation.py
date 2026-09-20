"""One inference at a time across proposal and evaluator calls in this API process."""

import asyncio

from orchestwin.models.structured_generation import (
    StructuredGenerationPort,
    StructuredGenerationRequest,
    StructuredGenerationResult,
)


class SerializedGenerationPort:
    def __init__(self, port: StructuredGenerationPort, lock: asyncio.Lock):
        self._port, self._lock = port, lock

    async def generate(self, request: StructuredGenerationRequest) -> StructuredGenerationResult:
        async with self._lock:
            pending = asyncio.create_task(self._port.generate(request))
            try:
                return await asyncio.shield(pending)
            except asyncio.CancelledError:
                # HTTP work delegated to a thread survives cancellation. Keep the
                # slot until that bounded call finishes, then propagate cancellation.
                while not pending.done():
                    try:
                        await asyncio.shield(pending)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not pending.cancelled():
                    pending.exception()
                raise
