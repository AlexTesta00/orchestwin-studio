from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Final

from orchestwin.cli.errors import CliError

LOCAL_FOLDER: Final = ".orchestwin"
LINK_FILE: Final = "project.json"
STEPS_FOLDER: Final = "steps"
PREVIEWS_FOLDER: Final = "previews"
LOCAL_IGNORE: Final = "previews/\n"
LINK_SCHEMA_VERSION: Final = 1
STEP_SCHEMA_VERSION: Final = 1
KNOWLEDGE_FOLDER: Final = "orchestwin"
STEP_STAGES: Final = ("brief", "team", "twins", "requirements", "design")
MODES: Final = ("DESIGN_ONLY", "DESIGN_AND_CODE")
_LINK_TEXTS: Final = ("studio", "api_prefix", "project_id", "project_name", "mode", "created_at")


@dataclass(frozen=True, slots=True)
class ProjectLink:
    studio: str
    api_prefix: str
    project_id: str
    project_name: str
    mode: str
    language: str | None
    created_at: str
    knowledge_folder: str = KNOWLEDGE_FOLDER


class ProjectFolder:
    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def find(cls, start: Path) -> ProjectFolder | None:
        current = Path(os.path.abspath(start))
        for folder in (current, *current.parents):
            if (folder / LOCAL_FOLDER / LINK_FILE).is_file():
                return cls(folder)
        return None

    @classmethod
    def create(cls, root: Path, link: ProjectLink) -> ProjectFolder:
        absolute = Path(os.path.abspath(root))
        linked = cls.find(absolute)
        if linked is not None:
            raise CliError("PROJECT_ALREADY_LINKED", values={"root": str(linked.root)})
        if not valid_link(link):
            raise ValueError("the link of a project needs every field and a known mode")
        folder = cls(absolute)
        folder.local.mkdir(parents=True, exist_ok=True)
        write_atomically(folder.local / ".gitignore", LOCAL_IGNORE.encode("utf-8"))
        write_atomically(folder.local / LINK_FILE, json_bytes(link_document(link)))
        return folder

    @property
    def local(self) -> Path:
        return self.root / LOCAL_FOLDER

    @property
    def knowledge(self) -> Path:
        return self.root / self.link().knowledge_folder

    @property
    def previews(self) -> Path:
        return self.local / PREVIEWS_FOLDER

    def link(self) -> ProjectLink:
        path = self.local / LINK_FILE
        document = read_json(path)
        link = link_from(document)
        if link is None:
            raise CliError("PROJECT_LINK_INVALID", values={"path": str(path)})
        return link

    def update_link(self, **changes: object) -> ProjectLink:
        link = replace(self.link(), **changes)
        if not valid_link(link):
            raise ValueError("the link of a project needs every field and a known mode")
        write_atomically(self.local / LINK_FILE, json_bytes(link_document(link)))
        return link

    def save_step(
        self,
        stage: str,
        version: Mapping[str, object],
        gate: Mapping[str, object] | None,
        saved_at: datetime,
    ) -> Path:
        path = self._step_path(stage)
        document = {
            "schema_version": STEP_SCHEMA_VERSION,
            "stage": stage,
            "saved_at": saved_at.isoformat(timespec="seconds"),
            "version": version,
            "gate": gate,
        }
        write_atomically(path, json_bytes(document))
        return path

    def step(self, stage: str) -> Mapping[str, object] | None:
        document = read_json(self._step_path(stage))
        if (
            not isinstance(document, dict)
            or document.get("stage") != stage
            or not isinstance(document.get("version"), dict)
        ):
            return None
        return document

    def steps(self) -> dict[str, Mapping[str, object]]:
        found: dict[str, Mapping[str, object]] = {}
        for stage in STEP_STAGES:
            document = self.step(stage)
            if document is not None:
                found[stage] = document
        return found

    def _step_path(self, stage: str) -> Path:
        if stage not in STEP_STAGES:
            raise ValueError(f"unknown stage: {stage}")
        return self.local / STEPS_FOLDER / f"{stage}.json"


def link_document(link: ProjectLink) -> dict[str, object]:
    return {"schema_version": LINK_SCHEMA_VERSION, **asdict(link)}


def link_from(document: object) -> ProjectLink | None:
    if not isinstance(document, dict) or document.get("schema_version") != LINK_SCHEMA_VERSION:
        return None
    if not all(isinstance(document.get(name), str) for name in _LINK_TEXTS):
        return None
    language = document.get("language")
    folder = document.get("knowledge_folder", KNOWLEDGE_FOLDER)
    if (language is not None and not isinstance(language, str)) or not isinstance(folder, str):
        return None
    link = ProjectLink(
        studio=document["studio"],
        api_prefix=document["api_prefix"],
        project_id=document["project_id"],
        project_name=document["project_name"],
        mode=document["mode"],
        language=language,
        created_at=document["created_at"],
        knowledge_folder=folder,
    )
    return link if valid_link(link) else None


def valid_link(link: ProjectLink) -> bool:
    texts = (link.studio, link.api_prefix, link.project_id, link.project_name, link.created_at)
    return (
        all(isinstance(value, str) and value.strip() for value in texts)
        and link.mode in MODES
        and (link.language is None or isinstance(link.language, str))
        and valid_folder_name(link.knowledge_folder)
    )


def valid_folder_name(name: object) -> bool:
    return (
        isinstance(name, str)
        and bool(name.strip())
        and name == name.strip()
        and name not in {".", ".."}
        and not any(character in name for character in '/\\:*?"<>|\0')
    )


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return None


def json_bytes(value: object) -> bytes:
    text = json.dumps(value, indent=2, ensure_ascii=False, default=json_default)
    return f"{text}\n".encode()


def json_default(value: object) -> object:
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"{type(value).__name__} cannot be written as JSON")


def write_atomically(path: Path, content: bytes, *, permissions: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if permissions is not None:
            os.chmod(temporary, permissions)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
