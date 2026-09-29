from __future__ import annotations

import contextlib
import os
import textwrap
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, TextIO

from orchestwin.cli.environment import is_terminal
from orchestwin.cli.errors import CliError
from orchestwin.cli.messages import text as message_text

if TYPE_CHECKING:
    from orchestwin.cli.environment import Environment

ATTEMPTS: Final = 5
TEXT_LINE_LIMIT: Final = 1000
PROGRESS_INTERVAL_SECONDS: Final = 60.0
DEFAULT_WIDTH: Final = 80
MINIMUM_WIDTH: Final = 20
COLUMN_GAP: Final = 2
MINIMUM_COLUMN: Final = 4
YES_ANSWERS: Final = frozenset({"s", "si", "sì", "y", "yes"})
NO_ANSWERS: Final = frozenset({"n", "no"})
BOLD: Final = "\x1b[1m"
RESET: Final = "\x1b[0m"
ENABLE_VIRTUAL_TERMINAL: Final = 0x0004
PLAIN_EQUIVALENTS: Final[Mapping[str, str]] = MappingProxyType(
    {
        chr(0x00B7): "-",
        chr(0x2192): "->",
        chr(0x2190): "<-",
        chr(0x2026): "...",
        chr(0x2713): "ok",
        chr(0x2714): "ok",
        chr(0x2717): "x",
        chr(0x2018): "'",
        chr(0x2019): "'",
        chr(0x201A): "'",
        chr(0x201C): '"',
        chr(0x201D): '"',
        chr(0x201E): '"',
        chr(0x00AB): '"',
        chr(0x00BB): '"',
        chr(0x2013): "-",
        chr(0x2014): "-",
        chr(0x2022): "-",
        chr(0x00A0): " ",
        chr(0x2264): "<=",
        chr(0x2265): ">=",
        chr(0x00D7): "x",
    }
)


class ProgressOutcome(StrEnum):
    DONE = "DONE"
    NOT_COMPLETED = "NOT_COMPLETED"
    INTERRUPTED = "INTERRUPTED"


OUTCOME_KEYS: Final[Mapping[ProgressOutcome, str]] = MappingProxyType(
    {
        ProgressOutcome.DONE: "common.progress_done",
        ProgressOutcome.NOT_COMPLETED: "common.progress_not_completed",
        ProgressOutcome.INTERRUPTED: "common.progress_interrupted",
    }
)


@dataclass(frozen=True, slots=True)
class Choice:
    key: str
    label: str


class Console:
    def __init__(self, environment: Environment, *, language: str, color: bool) -> None:
        self.environment = environment
        self.language = language
        self.width = terminal_width(environment)
        self.color = color and colour_allowed(environment)

    def text(self, key: str, /, **values: object) -> str:
        return message_text(key, self.language, **values)

    def say(self, key: str, /, **values: object) -> None:
        self.write(self.text(key, **values))

    def write(self, text: str = "") -> None:
        self._emit(self.environment.stdout, f"{text}\n")

    def error(self, key: str, /, **values: object) -> None:
        self._emit(self.environment.stderr, f"{self.text(key, **values)}\n")

    def heading(self, text: str) -> None:
        self.write(f"{BOLD}{text}{RESET}" if self.color else text)
        self.write("=" * min(max(len(text), 1), self.width))

    def table(self, headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
        for line in table_lines(headers, rows, self.width):
            self.write(line)

    def items(self, lines: Sequence[str]) -> None:
        for line in lines:
            parts = textwrap.wrap(
                line,
                width=max(self.width, MINIMUM_WIDTH),
                initial_indent="- ",
                subsequent_indent="  ",
            )
            for part in parts or ["-"]:
                self.write(part)

    def ask(
        self,
        key: str,
        /,
        *,
        default: str | None = None,
        required: bool = True,
        **values: object,
    ) -> str:
        question = self.text(key, **values)
        prompt = f"{question} [{default}] " if default else f"{question} "
        for _ in range(ATTEMPTS):
            answer = self._prompt(prompt).strip()
            if answer:
                return answer
            if default is not None:
                return default
            if not required:
                return ""
            self.say("common.answer_required")
        raise CliError("ANSWER_NOT_VALID")

    def ask_text(self, key: str, /, **values: object) -> str:
        self.write(self.text(key, **values))
        self.say("common.text_hint")
        lines: list[str] = []
        for _ in range(TEXT_LINE_LIMIT):
            line = self.environment.stdin.readline()
            if not line:
                if lines:
                    break
                raise CliError("INPUT_CLOSED")
            content = line.rstrip("\r\n")
            if not content.strip():
                break
            lines.append(content)
        return "\n".join(lines)

    def confirm(self, key: str, /, *, default: bool, **values: object) -> bool:
        hint = self.text("common.yes_no_default_yes" if default else "common.yes_no_default_no")
        prompt = f"{self.text(key, **values)} {hint} "
        for _ in range(ATTEMPTS):
            answer = self._prompt(prompt).strip().casefold()
            if not answer:
                return default
            if answer in YES_ANSWERS:
                return True
            if answer in NO_ANSWERS:
                return False
            self.say("common.answer_yes_no")
        raise CliError("ANSWER_NOT_VALID")

    def choose(self, key: str, /, options: Sequence[Choice], **values: object) -> Choice:
        if not options:
            raise ValueError("a choice needs at least one option")
        self.write(self.text(key, **values))
        for number, option in enumerate(options, start=1):
            self.write(f"  {number}. {option.label}")
        prompt = f"{self.text('common.choose_prompt')} "
        for _ in range(ATTEMPTS):
            selected = selected_choice(self._prompt(prompt).strip(), options)
            if selected is not None:
                return selected
            self.say("common.choice_invalid")
        raise CliError("ANSWER_NOT_VALID")

    def secret(self, key: str, /, **values: object) -> str:
        prompt = f"{self.text(key, **values)} "
        for _ in range(ATTEMPTS):
            try:
                value = self.environment.read_secret(prompt)
            except EOFError:
                raise CliError("INPUT_CLOSED") from None
            if value:
                return value
            self.say("common.answer_required")
        raise CliError("ANSWER_NOT_VALID")

    def read_line(self) -> str:
        line = self.environment.stdin.readline()
        if not line:
            raise CliError("INPUT_CLOSED")
        return line.rstrip("\r\n")

    def progress(self, label: str) -> Progress:
        return Progress(self, label)

    def _prompt(self, prompt: str) -> str:
        stdout = self.environment.stdout
        self._emit(stdout, prompt)
        line = self.environment.stdin.readline()
        if not self.environment.interactive:
            self._emit(stdout, "\n")
        if not line:
            raise CliError("INPUT_CLOSED")
        return line.rstrip("\r\n")

    def _emit(self, stream: TextIO, text: str) -> None:
        stream.write(plain(text, stream_encoding(stream)))
        stream.flush()


class Progress:
    def __init__(self, console: Console, label: str) -> None:
        self._console = console
        self._label = label
        self._detail = ""
        self._started = 0.0
        self._reported = 0.0
        self._drawn = 0
        self._outcome = ProgressOutcome.DONE

    @property
    def outcome(self) -> ProgressOutcome:
        return self._outcome

    def set_outcome(self, outcome: ProgressOutcome | str) -> None:
        self._outcome = ProgressOutcome(outcome)

    def __enter__(self) -> Progress:
        self._started = self._reported = self._console.environment.monotonic()
        if self._live:
            self._draw()
        else:
            self._console.say("common.progress_started", label=self._label)
        return self

    def update(self, detail: str = "") -> None:
        self._detail = detail
        if self._live:
            self._draw()
            return
        moment = self._console.environment.monotonic()
        if moment - self._reported < PROGRESS_INTERVAL_SECONDS:
            return
        self._reported = moment
        elapsed = format_elapsed(moment - self._started)
        if detail:
            self._console.say(
                "common.progress_running", label=self._label, detail=detail, elapsed=elapsed
            )
        else:
            self._console.say("common.progress_waiting", label=self._label, elapsed=elapsed)

    def __exit__(self, *exc: object) -> None:
        raised = exc[0] if exc else None
        if isinstance(raised, type) and issubclass(raised, KeyboardInterrupt):
            self._outcome = ProgressOutcome.INTERRUPTED
        elif raised is not None and self._outcome is ProgressOutcome.DONE:
            self._outcome = ProgressOutcome.NOT_COMPLETED
        elapsed = format_elapsed(self._console.environment.monotonic() - self._started)
        if self._live and self._drawn:
            self._console._emit(self._console.environment.stdout, f"\r{' ' * self._drawn}\r")
            self._drawn = 0
        self._console.say(OUTCOME_KEYS[self._outcome], label=self._label, elapsed=elapsed)

    @property
    def _live(self) -> bool:
        return self._console.environment.interactive

    def _draw(self) -> None:
        elapsed = format_elapsed(self._console.environment.monotonic() - self._started)
        parts = (self._label, self._detail, elapsed) if self._detail else (self._label, elapsed)
        line = " - ".join(parts)[: max(self._console.width - 1, 1)]
        padding = " " * max(self._drawn - len(line), 0)
        self._console._emit(self._console.environment.stdout, f"\r{line}{padding}")
        self._drawn = len(line)


def selected_choice(answer: str, options: Sequence[Choice]) -> Choice | None:
    if answer.isdecimal():
        number = int(answer)
        return options[number - 1] if 1 <= number <= len(options) else None
    wanted = answer.casefold()
    if not wanted:
        return None
    return next((option for option in options if option.key.casefold() == wanted), None)


def stream_encoding(stream: object) -> str:
    encoding = getattr(stream, "encoding", None)
    return encoding if isinstance(encoding, str) and encoding else "utf-8"


def plain(text: str, encoding: str) -> str:
    try:
        text.encode(encoding)
    except UnicodeEncodeError:
        return "".join(_plain_character(character, encoding) for character in text)
    except LookupError:
        return text
    return text


def _plain_character(character: str, encoding: str) -> str:
    if _encodes(character, encoding):
        return character
    for candidate in (PLAIN_EQUIVALENTS.get(character), _without_marks(character)):
        if candidate and _encodes(candidate, encoding):
            return candidate
    return "?"


def _without_marks(character: str) -> str:
    decomposed = unicodedata.normalize("NFKD", character)
    return "".join(part for part in decomposed if not unicodedata.combining(part))


def _encodes(text: str, encoding: str) -> bool:
    try:
        text.encode(encoding)
    except UnicodeEncodeError:
        return False
    return True


def table_lines(headers: Sequence[str], rows: Sequence[Sequence[str]], width: int) -> list[str]:
    columns = len(headers)
    if columns == 0:
        return []
    grid = [_cells(headers, columns), *(_cells(row, columns) for row in rows)]
    widths = [max(_longest(row[index]) for row in grid) for index in range(columns)]
    available = max(width - COLUMN_GAP * (columns - 1), columns * MINIMUM_COLUMN)
    while sum(widths) > available:
        widest = widths.index(max(widths))
        if widths[widest] <= MINIMUM_COLUMN:
            break
        widths[widest] -= 1
    gap = " " * COLUMN_GAP
    lines: list[str] = []
    for position, row in enumerate(grid):
        wrapped = [_wrapped(cell, widths[index]) for index, cell in enumerate(row)]
        for line in range(max(len(cell) for cell in wrapped)):
            parts = (
                (cell[line] if line < len(cell) else "").ljust(widths[index])
                for index, cell in enumerate(wrapped)
            )
            lines.append(gap.join(parts).rstrip())
        if position == 0:
            lines.append(gap.join("-" * size for size in widths))
    return lines


def _cells(row: Sequence[object], columns: int) -> list[str]:
    cells = [str(cell) for cell in row][:columns]
    return cells + [""] * (columns - len(cells))


def _longest(cell: str) -> int:
    return max((len(line) for line in cell.splitlines()), default=0)


def _wrapped(cell: str, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in cell.splitlines() or [""]:
        parts = textwrap.wrap(paragraph, width=width, break_long_words=True)
        lines.extend(parts or [""])
    return lines


def terminal_width(environment: Environment) -> int:
    configured = environment.variables.get("COLUMNS", "").strip()
    if configured.isdecimal() and int(configured) >= MINIMUM_WIDTH:
        return int(configured)
    stream = environment.stdout
    if is_terminal(stream):
        with contextlib.suppress(AttributeError, OSError, ValueError):
            return max(os.get_terminal_size(stream.fileno()).columns, MINIMUM_WIDTH)
    return DEFAULT_WIDTH


def colour_allowed(environment: Environment) -> bool:
    if "NO_COLOR" in environment.variables:
        return False
    if not is_terminal(environment.stdout):
        return False
    if environment.platform == "win32":
        return enable_virtual_terminal(environment.stdout)
    return True


def enable_virtual_terminal(stream: object) -> bool:
    try:
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(stream.fileno())
        kernel32 = ctypes.windll.kernel32
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL))
    except (AttributeError, ImportError, OSError, ValueError):
        return False


def format_elapsed(seconds: float) -> str:
    total = max(int(seconds), 0)
    if total < 60:
        return f"{total} s"
    minutes, rest = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} min {rest:02d} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"
