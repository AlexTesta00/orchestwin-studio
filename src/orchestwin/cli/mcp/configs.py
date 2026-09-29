from __future__ import annotations

import json
import re
import shlex
from typing import TYPE_CHECKING, Final

from orchestwin.cli.mcp.protocol import SERVER_NAME

if TYPE_CHECKING:
    from pathlib import PurePath

    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.project import ProjectFolder

CLAUDE_CODE: Final = "claude-code"
CURSOR: Final = "cursor"
VSCODE: Final = "vscode"
EDITORS: Final = (CLAUDE_CODE, CURSOR, VSCODE)
PROGRAM: Final = "ut"
COMMAND: Final = "mcp"
PROJECT_DIR_OPTION: Final = "--project-dir"
SPEND_OPTION: Final = "--spend"
STDIO: Final = "stdio"
WINDOWS: Final = "win32"
WINDOWS_WORD: Final = re.compile(r"[\w:./-]+")


def server_arguments(root: PurePath, *, spend: bool) -> list[str]:
    arguments = [PROJECT_DIR_OPTION, root.as_posix(), COMMAND]
    return [*arguments, SPEND_OPTION] if spend else arguments


def claude_command(root: PurePath, *, spend: bool, platform: str) -> str:
    words = [shell_word(item, platform) for item in server_arguments(root, spend=spend)]
    return " ".join(("claude", "mcp", "add", SERVER_NAME, "--", PROGRAM, *words))


def shell_word(value: str, platform: str) -> str:
    if platform == WINDOWS:
        return value if WINDOWS_WORD.fullmatch(value) else f'"{value}"'
    return shlex.quote(value)


def snippet(editor: str, root: PurePath, *, spend: bool) -> dict[str, object]:
    entry: dict[str, object] = {
        "command": PROGRAM,
        "args": server_arguments(root, spend=spend),
        "cwd": root.as_posix(),
    }
    if editor == VSCODE:
        return {"servers": {SERVER_NAME: {"type": STDIO, **entry}}}
    if editor in (CLAUDE_CODE, CURSOR):
        return {"mcpServers": {SERVER_NAME: entry}}
    raise ValueError(f"unknown editor: {editor}")


def show(context: CommandContext, project: ProjectFolder, editor: str, *, spend: bool) -> int:
    console = context.console
    root = project.root
    content = json.dumps(snippet(editor, root, spend=spend), indent=2, ensure_ascii=True)
    if spend:
        console.say("mcp.config_spend")
    else:
        console.say("mcp.config_free")
    if editor == CLAUDE_CODE:
        console.say("mcp.config_claude_code_command")
        console.write(claude_command(root, spend=spend, platform=context.environment.platform))
        console.say("mcp.config_claude_code_file")
    elif editor == CURSOR:
        console.say("mcp.config_cursor")
    else:
        console.say("mcp.config_vscode")
    console.write(content)
    return 0
