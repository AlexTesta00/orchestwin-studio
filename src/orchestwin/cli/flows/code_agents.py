from __future__ import annotations

import math
import re
import shlex
import shutil
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final

from orchestwin.cli.errors import USAGE_STATUS, CliError
from orchestwin.cli.mcp.protocol import SERVER_NAME

CLAUDE: Final = "claude"
CUSTOM: Final = "custom"
AGENTS: Final = (CLAUDE, CUSTOM)
CLAUDE_PROGRAM: Final = "claude"
CLAUDE_VARIABLE: Final = "ORCHESTWIN_CLAUDE"
PATH_VARIABLE: Final = "PATH"
WINDOWS: Final = "win32"
PROMPT_FILE: Final = "prompt_file"
PROMPT_LINE: Final = "prompt_line"
MCP_CONFIG: Final = "mcp_config"
PROJECT: Final = "project"
PLACEHOLDERS: Final = (PROMPT_FILE, PROMPT_LINE, MCP_CONFIG, PROJECT)
PLACEHOLDER: Final = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
QUOTES: Final = ('"', "'")
PRINT_OPTION: Final = "--print"
MCP_CONFIG_OPTION: Final = "--mcp-config"
PERMISSION_MODE_OPTION: Final = "--permission-mode"
ACCEPT_EDITS: Final = "acceptEdits"
ALLOWED_TOOLS_OPTION: Final = "--allowedTools"
MODEL_OPTION: Final = "--model"
MAX_BUDGET_OPTION: Final = "--max-budget-usd"
TWIN_TOOLS: Final = f"mcp__{SERVER_NAME}"
PROMPT_SENTENCE: Final = (
    "Read the file {path} of this repository and carry out the work order it contains."
)
EMPTY_COMMAND: Final = "EMPTY"
OPEN_QUOTES: Final = "QUOTES"
UNKNOWN_PLACEHOLDER: Final = "PLACEHOLDER"

Which = Callable[..., str | None]


def find_claude(variables: Mapping[str, str], *, base: Path, which: Which = shutil.which) -> Path:
    configured = variables.get(CLAUDE_VARIABLE, "").strip()
    if configured:
        path = Path(configured)
        candidate = path if path.is_absolute() else base / path
        if candidate.is_file():
            return candidate
    found = which(CLAUDE_PROGRAM, path=search_path(variables))
    if found:
        return Path(found)
    raise CliError("CODE_AGENT_NOT_FOUND", status=1, values={"variable": CLAUDE_VARIABLE})


def search_path(variables: Mapping[str, str]) -> str:
    value = variables.get(PATH_VARIABLE)
    if value is None:
        value = next(
            (item for name, item in variables.items() if name.upper() == PATH_VARIABLE), ""
        )
    return value


def command_words(text: str, *, platform: str) -> tuple[str, ...]:
    posix = platform != WINDOWS
    try:
        words = shlex.split(text, posix=posix)
    except ValueError:
        raise invalid(OPEN_QUOTES) from None
    return checked_words(words if posix else [unquoted(word) for word in words])


def checked_words(words: Sequence[str]) -> tuple[str, ...]:
    cleaned = tuple(str(word) for word in words)
    if not cleaned or not cleaned[0].strip():
        raise invalid(EMPTY_COMMAND)
    for word in cleaned:
        for name in PLACEHOLDER.findall(word):
            if name not in PLACEHOLDERS:
                raise invalid(UNKNOWN_PLACEHOLDER, placeholder=f"{{{name}}}")
    return cleaned


def unquoted(word: str) -> str:
    if len(word) >= 2 and word[0] in QUOTES and word[-1] == word[0]:
        return word[1:-1]
    return word


def invalid(reason: str, **values: object) -> CliError:
    return CliError(
        "CODE_COMMAND_INVALID", status=USAGE_STATUS, values={"reason": reason, **values}
    )


def budget(value: str | None, *, agent: str, headless: bool) -> float | None:
    if value is None:
        return None
    if agent != CLAUDE or not headless:
        raise CliError("CODE_BUDGET_NEEDS_HEADLESS", status=USAGE_STATUS)
    try:
        amount = float(value)
    except ValueError:
        raise CliError("CODE_MAX_USD_INVALID", status=USAGE_STATUS) from None
    if not math.isfinite(amount) or round(amount, 2) <= 0:
        raise CliError("CODE_MAX_USD_INVALID", status=USAGE_STATUS)
    return round(amount, 2)


def budget_text(amount: float) -> str:
    return f"{amount:.2f}"


def prompt_line(relative: str) -> str:
    return PROMPT_SENTENCE.format(path=relative)


def claude_arguments(
    program: Path | str,
    *,
    prompt_line: str,
    mcp_config: Path | str,
    model: str | None = None,
    headless: bool = False,
    max_usd: float | None = None,
) -> list[str]:
    words = [str(program)]
    if headless:
        words.append(PRINT_OPTION)
    words.extend([prompt_line, MCP_CONFIG_OPTION, str(mcp_config)])
    if headless:
        words.extend([PERMISSION_MODE_OPTION, ACCEPT_EDITS, ALLOWED_TOOLS_OPTION, TWIN_TOOLS])
    if model:
        words.extend([MODEL_OPTION, model])
    if headless and max_usd is not None:
        words.extend([MAX_BUDGET_OPTION, budget_text(max_usd)])
    return words


def placeholder_values(
    *, prompt_file: Path | str, prompt_line: str, mcp_config: Path | str, project: Path | str
) -> dict[str, str]:
    return {
        PROMPT_FILE: str(prompt_file),
        PROMPT_LINE: prompt_line,
        MCP_CONFIG: str(mcp_config),
        PROJECT: str(project),
    }


def custom_arguments(words: Sequence[str], values: Mapping[str, str]) -> list[str]:
    return [
        PLACEHOLDER.sub(lambda match: values.get(match.group(1), match.group(0)), word)
        for word in checked_words(words)
    ]
