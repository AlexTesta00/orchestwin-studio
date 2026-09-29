from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from orchestwin.cli.errors import CliError

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.environment import ProcessResult

GIT: Final = "git"
GIT_OPTIONS: Final = (
    "-c",
    "core.quotepath=off",
    "-c",
    "i18n.logOutputEncoding=utf-8",
    "--no-pager",
)
LITERAL_PATHSPECS: Final = "--literal-pathspecs"
TIMEOUT_SECONDS: Final = 60.0
MISSING_STATUS: Final = 127
DEFAULT_LIMIT: Final = 50
LOG_FORMAT: Final = "--format=%H%x00%P%x00%aI%x00%an%x00%B%x00%x1e"
HEADER_FIELDS: Final = 6
SHORT_LENGTH: Final = 7
COMMIT_PATTERN: Final = re.compile(r"[0-9a-f]{7,64}")
NUMSTAT_PATTERN: Final = re.compile(r"\n?(-|[0-9]+)\t(-|[0-9]+)\t(.*)", re.DOTALL)
STATUS_PATTERN: Final = re.compile(r"\n?([A-Z])[0-9]*")
SECTION_PATTERN: Final = re.compile(r"(?m)^(?=diff --git )")
ADDED: Final = "ADDED"
MODIFIED: Final = "MODIFIED"
DELETED: Final = "DELETED"
RENAMED: Final = "RENAMED"
KINDS: Final[Mapping[str, str]] = {
    "A": ADDED,
    "C": ADDED,
    "D": DELETED,
    "M": MODIFIED,
    "R": RENAMED,
    "T": MODIFIED,
}
PAIRED_STATUSES: Final = frozenset({"R", "C"})
MAX_MESSAGE_LENGTH: Final = 2000
MAX_AUTHOR_LENGTH: Final = 200
MAX_PATH_LENGTH: Final = 500
MAX_FILES: Final = 500
MAX_DIFF_LENGTH: Final = 65536
MAX_FILE_BYTES: Final = 200 * 1024
MAX_EXCLUDED_TEXT: Final = 16384
PATHS_PER_CALL: Final = 16000
CUT_LINE: Final = "[... diff cut after 65536 characters]"
EMPTY_MESSAGE: Final = "-"
ELLIPSIS: Final = "…"
SECRET_NAMES: Final = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "id_ed25519*",
    "*secret*",
    "*credential*",
    "*.der",
    "*.jks",
    "*.keystore",
)
SKIPPED_FOLDERS: Final = frozenset(
    {"node_modules", ".venv", "venv", "dist", "build", "__pycache__"}
)
BINARY_MARKERS: Final = ("\nBinary files ", "\nGIT binary patch")


@dataclass(frozen=True, slots=True)
class ChangedFile:
    path: str
    kind: str
    added: int
    removed: int


@dataclass(frozen=True, slots=True)
class Commit:
    hash: str
    parent: str | None
    committed_at: str
    author: str | None
    message: str
    files: tuple[ChangedFile, ...]


@dataclass(frozen=True, slots=True)
class FileStat:
    added: int
    removed: int
    path: str
    source: str | None
    binary: bool


@dataclass(frozen=True, slots=True)
class LogEntry:
    hash: str
    parents: tuple[str, ...]
    date: str
    author: str
    body: str
    stats: tuple[FileStat, ...]


def git_command(*arguments: str, literal: bool = False) -> list[str]:
    prefix = (GIT, LITERAL_PATHSPECS) if literal else (GIT,)
    return [*prefix, *GIT_OPTIONS, *arguments]


def run_git(
    context: CommandContext, folder: Path, *arguments: str, literal: bool = False
) -> ProcessResult:
    result = context.environment.run_process(
        git_command(*arguments, literal=literal), folder, TIMEOUT_SECONDS
    )
    if result.status == MISSING_STATUS:
        raise CliError("GIT_NOT_AVAILABLE", status=1)
    return result


def repository_root(context: CommandContext, start: Path) -> Path | None:
    result = run_git(context, start, "rev-parse", "--show-toplevel")
    text = result.output.strip()
    if result.status != 0 or not text:
        return None
    return Path(text)


def head(context: CommandContext, root: Path) -> str | None:
    return _revision(context, root, "HEAD")


def resolve(context: CommandContext, root: Path, revision: str) -> str | None:
    wanted = revision.strip()
    if not wanted or wanted.startswith("-") or any(ord(character) < 33 for character in wanted):
        return None
    return _revision(context, root, f"{wanted}^{{commit}}")


def branch(context: CommandContext, root: Path) -> str | None:
    result = run_git(context, root, "rev-parse", "--abbrev-ref", "HEAD")
    text = result.output.strip()
    return text if result.status == 0 and text and text != "HEAD" else None


def uncommitted(context: CommandContext, root: Path, *, ignored: Sequence[str] = ()) -> bool:
    result = run_git(context, root, "status", "--porcelain", "-z")
    if result.status != 0:
        raise failed(result)
    prefixes = tuple(f"{prefix.rstrip('/')}/" for prefix in ignored if prefix.strip("/"))
    return any(not path.startswith(prefixes) for path in status_paths(result.output))


def status_paths(output: str) -> list[str]:
    tokens = output.split("\x00")
    paths: list[str] = []
    index = 0
    while index < len(tokens):
        entry = tokens[index]
        index += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if entry[0] in PAIRED_STATUSES:
            index += 1
    return paths


def log_arguments(since: str | None, limit: int = DEFAULT_LIMIT) -> tuple[str, ...]:
    return (
        "log",
        "--reverse",
        f"--max-count={max(int(limit), 1)}",
        "--no-color",
        "--find-renames",
        LOG_FORMAT,
        "--numstat",
        "-z",
        f"{since}..HEAD" if since else "HEAD",
    )


def kinds_arguments(commit: str) -> tuple[str, ...]:
    return ("show", "--name-status", "-z", "--no-color", "--find-renames", "--format=", commit)


def numstat_arguments(commit: str) -> tuple[str, ...]:
    return ("show", "--numstat", "-z", "--no-color", "--find-renames", "--format=", commit)


def diff_arguments(commit: str, paths: Sequence[str] = ()) -> tuple[str, ...]:
    return (
        "show",
        "--format=",
        "--unified=3",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--find-renames",
        commit,
        "--",
        *paths,
    )


def commits_after(
    context: CommandContext, root: Path, since: str | None, *, limit: int = DEFAULT_LIMIT
) -> tuple[Commit, ...]:
    result = run_git(context, root, *log_arguments(since, limit))
    if result.status != 0:
        if head(context, root) is None:
            return ()
        if since and resolve(context, root, since) is None:
            raise CliError("GIT_COMMIT_UNKNOWN", values={"commit": short(since)})
        raise failed(result)
    return tuple(
        _commit(entry, _kinds(context, root, entry.hash)) for entry in parse_log(result.output)
    )


def diff_of(context: CommandContext, root: Path, commit: Commit) -> str:
    stats = _numstat(context, root, commit.hash)
    excluded: set[str] = set()
    groups: list[tuple[str, ...]] = []
    for stat in stats:
        if skipped(stat):
            excluded.add(stat.path)
        else:
            groups.append((stat.source, stat.path) if stat.source else (stat.path,))
    text = "".join(_show(context, root, commit.hash, chunk) for chunk in _chunks(groups))
    kept, dropped = split_sections(text, [stat.path for stat in stats])
    excluded.update(dropped)
    listed = [stat.path for stat in stats if stat.path in excluded]
    listed.extend(path for path in dropped if path not in listed)
    return bounded_diff(kept, listed)


def change_body(commit: Commit, diff: str) -> dict[str, object]:
    text = diff if len(diff) <= MAX_DIFF_LENGTH and "\x00" not in diff else bounded_diff(diff)
    return {
        "commit": commit.hash,
        "parent": commit.parent,
        "committed_at": commit.committed_at,
        "author": commit.author,
        "message": commit.message,
        "files": [
            {
                "path": api_path(item.path),
                "kind": item.kind,
                "added": item.added,
                "removed": item.removed,
            }
            for item in commit.files[:MAX_FILES]
        ],
        "diff": text,
    }


def parse_log(output: str) -> list[LogEntry]:
    tokens = output.split("\x00")
    entries: list[LogEntry] = []
    index = 0
    while index < len(tokens):
        commit = tokens[index].strip().lower()
        if not commit:
            index += 1
            continue
        if index + HEADER_FIELDS > len(tokens) or COMMIT_PATTERN.fullmatch(commit) is None:
            raise CliError("GIT_FAILED", values={"detail": "git log"})
        parents = tuple(item.lower() for item in tokens[index + 1].split())
        date = tokens[index + 2].strip()
        author = tokens[index + 3]
        body = tokens[index + 4]
        stats, index = parse_stats(tokens, index + HEADER_FIELDS)
        entries.append(LogEntry(commit, parents, date, author, body, stats))
    return entries


def parse_stats(tokens: Sequence[str], start: int) -> tuple[tuple[FileStat, ...], int]:
    stats: list[FileStat] = []
    index = start
    while index < len(tokens):
        match = NUMSTAT_PATTERN.fullmatch(tokens[index])
        if match is None:
            break
        added, removed, path = match.groups()
        index += 1
        source: str | None = None
        if not path:
            if index + 1 >= len(tokens):
                break
            source, path = tokens[index], tokens[index + 1]
            index += 2
        binary = added == "-" and removed == "-"
        stats.append(FileStat(_number(added), _number(removed), path, source, binary))
    return tuple(stats), index


def parse_kinds(output: str) -> dict[str, str]:
    tokens = output.split("\x00")
    kinds: dict[str, str] = {}
    index = 0
    while index < len(tokens):
        match = STATUS_PATTERN.fullmatch(tokens[index])
        if match is None:
            index += 1
            continue
        letter = match.group(1)
        position = index + (2 if letter in PAIRED_STATUSES else 1)
        if position >= len(tokens):
            break
        kinds[tokens[position]] = KINDS.get(letter, MODIFIED)
        index = position + 1
    return kinds


def split_sections(text: str, paths: Sequence[str]) -> tuple[str, list[str]]:
    kept: list[str] = []
    dropped: list[str] = []
    for section in SECTION_PATTERN.split(text):
        if not section:
            continue
        binary = any(marker in section for marker in BINARY_MARKERS)
        if binary or len(section.encode("utf-8")) > MAX_FILE_BYTES:
            dropped.append(section_path(section, paths))
        else:
            kept.append(section)
    return "".join(kept), dropped


def section_path(section: str, paths: Sequence[str]) -> str:
    header = section.split("\n", 1)[0]
    for path in sorted(paths, key=len, reverse=True):
        if header.endswith((f" b/{path}", f' "b/{path}"')):
            return path
    return header.removeprefix("diff --git ").strip()


def bounded_diff(text: str, excluded: Sequence[str] = ()) -> str:
    body = text.replace("\x00", "")
    if body and not body.endswith("\n"):
        body += "\n"
    tail = excluded_lines(excluded)
    if len(body) + len(tail) <= MAX_DIFF_LENGTH:
        return body + tail
    marker = f"{CUT_LINE}\n"
    room = MAX_DIFF_LENGTH - len(tail) - len(marker) - 1
    kept = body[: max(room, 0)]
    if kept and not kept.endswith("\n"):
        kept += "\n"
    return kept + marker + tail


def excluded_lines(paths: Sequence[str]) -> str:
    lines = [f"[excluded: {visible(path)}]\n" for path in paths]
    text = "".join(lines)
    if len(text) <= MAX_EXCLUDED_TEXT:
        return text
    kept: list[str] = []
    size = 0
    for position, line in enumerate(lines):
        rest = f"[excluded: {len(lines) - position} more files]\n"
        if size + len(line) + len(rest) > MAX_EXCLUDED_TEXT:
            return "".join(kept) + rest
        kept.append(line)
        size += len(line)
    return text


def skipped(stat: FileStat) -> bool:
    return (
        stat.binary
        or excluded_path(stat.path)
        or (stat.source is not None and excluded_path(stat.source))
        or (stat.added + stat.removed) * 2 > MAX_FILE_BYTES
    )


def excluded_path(path: str) -> bool:
    parts = [part.lower() for part in path.replace("\\", "/").split("/") if part]
    if any(part in SKIPPED_FOLDERS for part in parts[:-1]):
        return True
    return any(fnmatch.fnmatchcase(part, pattern) for part in parts for pattern in SECRET_NAMES)


def api_path(path: str) -> str:
    text = visible(path)
    if not text.strip():
        return "?"
    if len(text) > MAX_PATH_LENGTH:
        return ELLIPSIS + text[-(MAX_PATH_LENGTH - 1) :]
    return text


def visible(text: str) -> str:
    return "".join(
        character if ord(character) >= 32 and ord(character) != 127 else "?" for character in text
    )


def first_line(message: str) -> str:
    for line in message.splitlines():
        text = " ".join("".join(ch if ch.isprintable() else " " for ch in line).split())
        if text:
            return text
    return EMPTY_MESSAGE


def short(commit: object) -> str:
    return str(commit or "")[:SHORT_LENGTH]


def commit_date(moment: str) -> str:
    try:
        parsed = datetime.fromisoformat(moment.strip())
    except ValueError:
        return moment.strip()[:16].replace("T", " ")
    return parsed.strftime("%Y-%m-%d %H:%M")


def failed(result: ProcessResult) -> CliError:
    lines = [line.strip() for line in result.errors.splitlines() if line.strip()]
    detail = lines[0] if lines else f"git {result.status}"
    return CliError("GIT_FAILED", values={"detail": detail})


def _revision(context: CommandContext, root: Path, revision: str) -> str | None:
    result = run_git(context, root, "rev-parse", "--verify", "--quiet", revision)
    text = result.output.strip().lower()
    if result.status != 0 or COMMIT_PATTERN.fullmatch(text) is None:
        return None
    return text


def _kinds(context: CommandContext, root: Path, commit: str) -> dict[str, str]:
    result = run_git(context, root, *kinds_arguments(commit))
    if result.status != 0:
        raise failed(result)
    return parse_kinds(result.output)


def _numstat(context: CommandContext, root: Path, commit: str) -> tuple[FileStat, ...]:
    result = run_git(context, root, *numstat_arguments(commit))
    if result.status != 0:
        raise failed(result)
    stats, _ = parse_stats(result.output.split("\x00"), 0)
    return stats


def _show(context: CommandContext, root: Path, commit: str, paths: Sequence[str]) -> str:
    result = run_git(context, root, *diff_arguments(commit, paths), literal=True)
    if result.status != 0:
        raise failed(result)
    return result.output


def _chunks(groups: Sequence[tuple[str, ...]]) -> Iterator[list[str]]:
    chunk: list[str] = []
    size = 0
    for group in groups:
        length = sum(len(path) + 1 for path in group)
        if chunk and size + length > PATHS_PER_CALL:
            yield chunk
            chunk, size = [], 0
        chunk.extend(group)
        size += length
    if chunk:
        yield chunk


def _commit(entry: LogEntry, kinds: Mapping[str, str]) -> Commit:
    files = tuple(
        ChangedFile(
            path=stat.path,
            kind=kinds.get(stat.path, RENAMED if stat.source else MODIFIED),
            added=stat.added,
            removed=stat.removed,
        )
        for stat in entry.stats
    )
    parent = entry.parents[0] if entry.parents else None
    return Commit(
        hash=entry.hash,
        parent=parent if parent and COMMIT_PATTERN.fullmatch(parent) else None,
        committed_at=entry.date,
        author=_author(entry.author),
        message=_message(entry.body),
        files=files,
    )


def _author(text: str) -> str | None:
    name = " ".join("".join(ch if ch.isprintable() else " " for ch in text).split())
    return name[:MAX_AUTHOR_LENGTH].strip() or None


def _message(text: str) -> str:
    message = text.replace("\x00", "").strip()
    if len(message) > MAX_MESSAGE_LENGTH:
        message = message[:MAX_MESSAGE_LENGTH].rstrip()
    return message or EMPTY_MESSAGE


def _number(value: str) -> int:
    return int(value) if value.isdigit() else 0
