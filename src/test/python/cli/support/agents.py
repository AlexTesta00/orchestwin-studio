from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from orchestwin.cli.errors import CliError


class AgentCall(NamedTuple):
    arguments: tuple[str, ...]
    folder: Path
    variables: dict[str, str]


class ScriptedAgent:
    def __init__(
        self,
        status: int = 0,
        *,
        writes: Mapping[str, str | bytes] | None = None,
        interrupt: bool = False,
    ) -> None:
        self.status = status
        self.writes = dict(writes or {})
        self.interrupt = interrupt
        self.calls: list[AgentCall] = []

    def __call__(self, arguments: Sequence[str], folder: Path, variables: Mapping[str, str]) -> int:
        self.calls.append(
            AgentCall(tuple(str(item) for item in arguments), Path(folder), dict(variables))
        )
        for name, content in self.writes.items():
            path = Path(folder).joinpath(*name.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        if self.interrupt:
            raise KeyboardInterrupt
        return self.status

    @property
    def arguments(self) -> tuple[str, ...]:
        return self.calls[-1].arguments


def no_agents(arguments: Sequence[str], folder: Path, variables: Mapping[str, str]) -> int:
    name = Path(str(arguments[0])).name if arguments else "agent"
    raise CliError(
        "CODE_AGENT_NOT_STARTED",
        status=1,
        values={"program": name, "detail": "no agent runs in the tests"},
    )
