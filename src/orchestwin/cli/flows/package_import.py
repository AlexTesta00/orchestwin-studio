from __future__ import annotations

import io
import os
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import imports
from orchestwin.cli.errors import NOT_VERIFIED_STATUS, CliError
from orchestwin.cli.project import KNOWLEDGE_FOLDER, ProjectFolder, ProjectLink

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.folder import FolderSummary
    from orchestwin.knowledge.archive import VerifiedFolder

NOT_VERIFIED: Final = "FOLDER_NOT_VERIFIED"
SWAP_FAILED: Final = "FOLDER_SWAP_FAILED"
FOLDER_IN_USE: Final = "FOLDER_IN_USE"
IMPORT_MODE: Final = "DESIGN_ONLY"
NAME_LIMIT: Final = 120
MEBIBYTE: Final = 1024 * 1024
ARCHIVE_SUFFIX: Final = ".zip"
PROBLEM_KEYS: Final = {
    "FOLDER_MISSING": "package.import_missing_folder",
    "FOLDER_TAMPERED": "package.import_tampered",
    "FOLDER_DOCUMENT_MISSING": "package.import_missing_file",
    "FOLDER_ARCHIVE_INVALID": "package.import_not_archive",
}


@dataclass(frozen=True, slots=True)
class LocalFolder:
    path: Path
    exists: bool
    summary: FolderSummary | None
    problem: CliError | None

    @property
    def verified(self) -> bool:
        return self.exists and self.summary is not None and self.problem is None

    @property
    def changed_by_hand(self) -> bool:
        return (
            self.exists
            and self.problem is not None
            and self.problem.values.get("reason") != knowledge.LINE_ENDINGS
        )


def local_folder(path: Path) -> LocalFolder:
    if not has_files(path):
        return LocalFolder(path, False, None, None)
    try:
        found = knowledge.summary(path)
    except CliError as error:
        if error.code != NOT_VERIFIED:
            raise
        return LocalFolder(path, True, None, error)
    try:
        knowledge.verify(path)
    except CliError as error:
        if error.code != NOT_VERIFIED:
            raise
        return LocalFolder(path, True, found, error)
    return LocalFolder(path, True, found, None)


def has_files(path: Path) -> bool:
    if not path.is_dir():
        return False
    for _, _, names in os.walk(path):
        if any(name not in knowledge.IGNORED_NAMES for name in names):
            return True
    return False


def confirm_replacement(context: CommandContext, local: LocalFolder, label: str) -> bool:
    if not local.changed_by_hand or local.problem is None:
        return True
    values = local.problem.values
    context.console.say(
        "package.changed_by_hand",
        path=label,
        file=str(values.get("path", "")),
        code=str(values.get("code", "")),
    )
    return context.console.confirm("package.replace_anyway", default=False)


def swap_problem(error: CliError) -> CliError:
    if error.code != SWAP_FAILED or "reason" in error.values:
        return error
    folder = str(error.values.get("folder") or "")
    path = str(error.values.get("path") or "")
    if folder and path and path != folder and Path(path).is_relative_to(folder):
        return error
    return CliError(SWAP_FAILED, values={**error.values, "reason": FOLDER_IN_USE})


def run_import(context: CommandContext, source_text: str, name: str | None) -> int:
    console = context.console
    source = source_path(context, source_text)
    display = display_name(name)
    try:
        content, verified = prepared(context, source)
    except CliError as error:
        if error.code != NOT_VERIFIED:
            raise
        console.error(
            problem_key(error),
            source=str(source),
            file=str(error.values.get("path", "")),
            code=str(error.values.get("code", "")),
        )
        return NOT_VERIFIED_STATUS
    shown = display or fallback_name(verified.project_name)
    project = context.project(required=False)
    linked = None if project is None else project.link()
    label = f"{KNOWLEDGE_FOLDER}/"
    link_here = False
    if linked is None:
        link_here = console.confirm(
            "package.import_offer_link", default=True, folder=str(context.directory), path=label
        )
        if link_here and not confirm_replacement(
            context, local_folder(context.directory / KNOWLEDGE_FOLDER), label
        ):
            console.say("package.import_cancelled", path=label)
            return 1
    client = context.client()
    with console.progress(context.text("package.import_progress", name=shown)):
        document = imports.import_project(
            client, content, file_name=archive_name(source), display_name=display
        )
    created = imports.imported_project(document)
    new_id = str(created.get("id"))
    new_name = str(created.get("display_name") or shown)
    console.say(
        "package.imported",
        name=new_name,
        origin=verified.project_name,
        version=verified.package_version,
    )
    if document.get("why_verified") is True:
        console.say("package.why_verified")
    for limit in document.get("import_limits", ()):
        if limit in {"LEGACY_FEEDBACK_CONTEXT_MISSING", "LEARNED_PROJECTION_NOT_RESTORED"}:
            console.say("package.import_limit." + limit)
    stages = imports.approval_required(document)
    if stages:
        console.say("package.import_approval", count=len(stages))
    if linked is not None:
        console.say("package.import_kept_link", linked=linked.project_name, name=new_name)
        return 0
    if not link_here:
        console.say("package.import_not_linked", name=new_name)
        return 0
    ProjectFolder.create(
        context.directory,
        ProjectLink(
            studio=client.studio.origin,
            api_prefix=client.studio.api_prefix,
            project_id=new_id,
            project_name=new_name,
            mode=IMPORT_MODE,
            language=folder_language(verified),
            created_at=context.environment.now().isoformat(timespec="seconds"),
        ),
    )
    try:
        knowledge.unpack(content, context.directory / KNOWLEDGE_FOLDER)
    except CliError as error:
        if error.code != SWAP_FAILED:
            raise
        console.error(
            "package.import_unpack_failed", path=label, file=str(error.values.get("path", ""))
        )
        return 1
    console.say("package.import_linked", path=label)
    return 0


def source_path(context: CommandContext, text: str) -> Path:
    given = Path(text)
    source = given if given.is_absolute() else context.environment.working_directory / given
    if not source.exists():
        raise CliError("IMPORT_SOURCE_MISSING", values={"path": str(source)})
    return source


def prepared(context: CommandContext, source: Path) -> tuple[bytes, VerifiedFolder]:
    from orchestwin.knowledge.archive import MAX_ARCHIVE_ENTRIES, MAX_ARCHIVE_SIZE

    try:
        if source.is_dir():
            count = len(knowledge.verify(source).files)
            content = knowledge.pack(source)
        else:
            size = source.stat().st_size
            if size > MAX_ARCHIVE_SIZE:
                raise too_large(context, source, size, MAX_ARCHIVE_SIZE)
            content = source.read_bytes()
            count = entry_count(content)
    except OSError:
        raise CliError("IMPORT_SOURCE_UNREADABLE", values={"path": str(source)}) from None
    if count is not None and count > MAX_ARCHIVE_ENTRIES:
        raise CliError(
            "ARCHIVE_TOO_MANY_ENTRIES",
            status=NOT_VERIFIED_STATUS,
            values={"source": str(source), "count": count, "limit": MAX_ARCHIVE_ENTRIES},
        )
    if len(content) > MAX_ARCHIVE_SIZE:
        raise too_large(context, source, len(content), MAX_ARCHIVE_SIZE)
    return content, knowledge.verify_archive(content)


def too_large(context: CommandContext, source: Path, size: int, limit: int) -> CliError:
    shown = f"{size / MEBIBYTE:.1f}"
    return CliError(
        "ARCHIVE_TOO_LARGE",
        status=NOT_VERIFIED_STATUS,
        values={
            "source": str(source),
            "size": shown.replace(".", ",") if context.language == "it" else shown,
            "limit": limit // MEBIBYTE,
        },
    )


def entry_count(content: bytes) -> int | None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return sum(1 for item in archive.infolist() if not item.is_dir())
    except (zipfile.BadZipFile, EOFError, OSError, ValueError):
        return None


def problem_key(error: CliError) -> str:
    if error.values.get("reason") == knowledge.LINE_ENDINGS:
        return "package.import_line_endings"
    return PROBLEM_KEYS.get(str(error.values.get("code")), "package.import_not_verified")


def display_name(name: str | None) -> str | None:
    if name is None:
        return None
    normalized = " ".join(name.split())
    if not normalized:
        return None
    if len(normalized) > NAME_LIMIT:
        raise CliError("PROJECT_NAME_INVALID")
    return normalized


def fallback_name(name: str) -> str:
    return " ".join(name.split())[:NAME_LIMIT].rstrip()


def archive_name(source: Path) -> str:
    if source.is_file() and source.name:
        return source.name
    return f"{source.name or KNOWLEDGE_FOLDER}{ARCHIVE_SUFFIX}"


def folder_language(verified: VerifiedFolder) -> str | None:
    project = verified.manifest.get("project")
    language = project.get("language") if isinstance(project, Mapping) else None
    return language if isinstance(language, str) and language else None
