from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from orchestwin.artifacts.design import contains_control_character
from orchestwin.artifacts.design_critique import (
    FILE_EXTENSIONS,
    MAX_IMAGE_SIDE,
    MIN_IMAGE_SIDE,
    DesignCritiqueError,
    image_dimensions,
    image_media_type,
)
from orchestwin.models.structured_generation import MAX_ATTACHMENT_BYTES, GenerationAttachment

DEFAULT_REFERENCES_DIR: Final = "var/studio/references"
MAX_REFERENCES: Final = 2
MAX_NOTE_LENGTH: Final = 300
NOTE_FILE_NAME: Final = "note.txt"
REFERENCE_SUFFIXES: Final = frozenset({".png", ".jpg", ".jpeg"})
_MAX_NOTE_BYTES: Final = 16 * 1024
_LOGGER: Final = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DesignReferences:
    note: str | None
    attachments: tuple[GenerationAttachment, ...]
    screens: tuple[dict[str, str], ...]

    def view(self) -> dict[str, object]:
        return {"note": self.note, "screens": [dict(screen) for screen in self.screens]}


def _skip(name: str, reason: str) -> None:
    _LOGGER.warning("The design reference %s is skipped: %s.", name, reason)


def _bounded(path: Path, maximum: int) -> bytes:
    with path.open("rb") as handle:
        return handle.read(maximum + 1)


def _image(path: Path) -> tuple[str, bytes] | None:
    try:
        content = _bounded(path, MAX_ATTACHMENT_BYTES)
    except OSError:
        _skip(path.name, "it cannot be read")
        return None
    if len(content) > MAX_ATTACHMENT_BYTES:
        _skip(path.name, "it is larger than 5 MiB")
        return None
    try:
        media_type = image_media_type(content)
        width, height = image_dimensions(content)
    except DesignCritiqueError:
        _skip(path.name, "it is not a valid PNG or JPEG image")
        return None
    if min(width, height) < MIN_IMAGE_SIDE or max(width, height) > MAX_IMAGE_SIDE:
        _skip(path.name, f"its sides are not between {MIN_IMAGE_SIDE} and {MAX_IMAGE_SIDE} pixels")
        return None
    return media_type, content


def _note(directory: Path) -> str | None:
    path = directory / NOTE_FILE_NAME
    try:
        if not path.is_file():
            return None
        raw = _bounded(path, _MAX_NOTE_BYTES)
        text = "" if len(raw) > _MAX_NOTE_BYTES else raw.decode("utf-8-sig")
    except OSError:
        _skip(NOTE_FILE_NAME, "it cannot be read")
        return None
    except UnicodeDecodeError:
        _skip(NOTE_FILE_NAME, "it is not UTF-8 text")
        return None
    note = " ".join(text.split())
    if len(raw) > _MAX_NOTE_BYTES or len(note) > MAX_NOTE_LENGTH:
        _skip(NOTE_FILE_NAME, f"it is longer than {MAX_NOTE_LENGTH} characters")
        return None
    if contains_control_character(note):
        _skip(NOTE_FILE_NAME, "it contains control characters")
        return None
    return note or None


def _candidates(directory: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in directory.iterdir()
            if path.suffix.lower() in REFERENCE_SUFFIXES and path.is_file()
        ),
        key=lambda path: (path.name.casefold(), path.name),
    )


def load_design_references(
    directory: Path | None, *, limit: int = MAX_REFERENCES
) -> DesignReferences | None:
    count = min(limit, MAX_REFERENCES)
    if directory is None or count < 1:
        return None
    try:
        if not directory.is_dir():
            return None
        candidates = _candidates(directory)
    except OSError:
        _LOGGER.warning("The folder of the design references cannot be read.")
        return None
    attachments: list[GenerationAttachment] = []
    screens: list[dict[str, str]] = []
    for path in candidates:
        if len(attachments) == count:
            break
        image = _image(path)
        if image is None:
            continue
        media_type, content = image
        number = len(attachments) + 1
        name = f"reference-{number:03d}.{FILE_EXTENSIONS[media_type]}"
        attachments.append(GenerationAttachment(name=name, media_type=media_type, content=content))
        screens.append({"code": f"REF-{number:03d}", "file": name, "label": path.name})
    if not attachments:
        return None
    return DesignReferences(
        note=_note(directory), attachments=tuple(attachments), screens=tuple(screens)
    )


__all__ = [
    "DEFAULT_REFERENCES_DIR",
    "MAX_NOTE_LENGTH",
    "MAX_REFERENCES",
    "NOTE_FILE_NAME",
    "REFERENCE_SUFFIXES",
    "DesignReferences",
    "load_design_references",
]
