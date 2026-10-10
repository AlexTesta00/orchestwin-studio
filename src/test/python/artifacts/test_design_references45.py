from __future__ import annotations

import logging
from pathlib import Path

import pytest

from orchestwin.artifacts.design_references import (
    DEFAULT_REFERENCES_DIR,
    MAX_NOTE_LENGTH,
    MAX_REFERENCES,
    DesignReferences,
    load_design_references,
)
from orchestwin.models.structured_generation import MAX_ATTACHMENT_BYTES, GenerationAttachment
from src.test.python.artifacts.test_design_critique44 import jpeg, png

LOGGER = "orchestwin.artifacts.design_references"
HOME = png(64, 48)
BOARD = jpeg(390, 844)


def folder(path: Path, files: dict[str, bytes]) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (path / name).write_bytes(content)
    return path


def summary(references: DesignReferences) -> list[tuple[str, str, bytes, dict[str, str]]]:
    return [
        (item.name, item.media_type, item.content, screen)
        for item, screen in zip(references.attachments, references.screens, strict=True)
    ]


def test_the_constants_follow_the_contract():
    assert (DEFAULT_REFERENCES_DIR, MAX_REFERENCES, MAX_NOTE_LENGTH) == (
        "var/studio/references",
        2,
        300,
    )


def test_a_missing_or_empty_folder_gives_no_references(tmp_path):
    plain = folder(tmp_path / "plain", {})
    unrelated = folder(
        tmp_path / "unrelated",
        {"note.txt": b"Mi piace la cura dei dettagli", "logo.gif": b"GIF89a", "brief.md": b"#"},
    )
    (unrelated / "shot.png").mkdir()
    a_file = tmp_path / "file.png"
    a_file.write_bytes(HOME)

    for directory in (None, tmp_path / "missing", plain, unrelated, a_file):
        assert load_design_references(directory) is None


def test_two_images_and_a_note_become_two_attachments_and_their_view(tmp_path):
    directory = folder(
        tmp_path / "references",
        {
            "b-board.jpeg": BOARD,
            "a-home.png": HOME,
            "note.txt": b"  Mi piace il ritmo\n\tdelle card  ",
        },
    )

    references = load_design_references(directory)

    assert isinstance(references, DesignReferences)
    assert all(isinstance(item, GenerationAttachment) for item in references.attachments)
    assert summary(references) == [
        (
            "reference-001.png",
            "image/png",
            HOME,
            {"code": "REF-001", "file": "reference-001.png", "label": "a-home.png"},
        ),
        (
            "reference-002.jpg",
            "image/jpeg",
            BOARD,
            {"code": "REF-002", "file": "reference-002.jpg", "label": "b-board.jpeg"},
        ),
    ]
    view = references.view()
    assert view == {
        "note": "Mi piace il ritmo delle card",
        "screens": [dict(screen) for screen in references.screens],
    }
    view["screens"][0]["label"] = "altro"
    assert references.screens[0]["label"] == "a-home.png"


def test_only_the_first_two_images_in_the_order_of_their_names_are_attached(tmp_path):
    directory = folder(
        tmp_path / "references",
        {"C-last.png": png(32, 32), "a-first.png": HOME, "B-second.PNG": BOARD},
    )

    references = load_design_references(directory)

    assert [screen["label"] for screen in references.screens] == ["a-first.png", "B-second.PNG"]
    assert [item.name for item in references.attachments] == [
        "reference-001.png",
        "reference-002.jpg",
    ]
    assert references.note is None
    assert len(load_design_references(directory, limit=5).attachments) == MAX_REFERENCES
    assert [item.content for item in load_design_references(directory, limit=1).attachments] == [
        HOME
    ]
    assert load_design_references(directory, limit=0) is None


def test_an_invalid_image_is_skipped_with_a_warning_and_the_next_one_takes_its_place(
    tmp_path, caplog
):
    directory = folder(
        tmp_path / "references",
        {
            "1-broken.png": b"not an image at all",
            "2-tiny.png": png(8, 8),
            "3-huge.png": HOME + bytes(MAX_ATTACHMENT_BYTES),
            "4-board.jpg": BOARD,
            "5-home.png": HOME,
            "6-spare.png": png(32, 32),
        },
    )

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        references = load_design_references(directory)

    assert [screen["label"] for screen in references.screens] == ["4-board.jpg", "5-home.png"]
    assert [screen["code"] for screen in references.screens] == ["REF-001", "REF-002"]
    warnings = [record for record in caplog.records if record.name == LOGGER]
    assert [record.levelno for record in warnings] == [logging.WARNING] * 3
    messages = [record.getMessage() for record in warnings]
    for name, message in zip(("1-broken.png", "2-tiny.png", "3-huge.png"), messages, strict=True):
        assert name in message
    assert str(tmp_path) not in caplog.text
    assert str(directory) not in caplog.text


@pytest.mark.parametrize(
    "content,expected,warned",
    [
        ("﻿Spazi ampi\n e  ombre morbide".encode(), "Spazi ampi e ombre morbide", False),
        (("x" * MAX_NOTE_LENGTH).encode(), "x" * MAX_NOTE_LENGTH, False),
        (("x" * (MAX_NOTE_LENGTH + 1)).encode(), None, True),
        (b" \n\t ", None, False),
        (b"\xff\xfe not utf-8", None, True),
        ("Titoli\u0000grandi".encode(), None, True),
        (b" " * 20_000 + b"x", None, True),
    ],
)
def test_the_note_is_optional_normalized_and_bounded(tmp_path, caplog, content, expected, warned):
    directory = folder(tmp_path / "references", {"home.png": HOME, "note.txt": content})

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        references = load_design_references(directory)

    assert references.note == expected
    assert [item.name for item in references.attachments] == ["reference-001.png"]
    warnings = [record.getMessage() for record in caplog.records if record.name == LOGGER]
    assert len(warnings) == int(warned)
    assert all("note.txt" in message for message in warnings)
    assert str(tmp_path) not in caplog.text
