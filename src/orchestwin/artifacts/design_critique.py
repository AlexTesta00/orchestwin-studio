from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from orchestwin.artifacts.design_evaluation import (
    MAX_EVALUATED_TWINS,
    evaluation_bundle_from_snapshot,
    evaluation_reference,
    evaluation_response_from_snapshot,
    finding_anchor_key,
)
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactBundle,
    EvaluationArtifactKind,
    EvaluationScenario,
    create_evaluation_artifact_bundle,
)
from orchestwin.evaluation.evaluator import (
    UserTwinEvaluationResponse,
    UserTwinEvaluatorConfiguration,
)
from orchestwin.evaluation.findings import SyntheticFinding, SyntheticFindingSeverity
from orchestwin.models.structured_generation import GenerationAttachment
from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash

DESIGN_CRITIQUE_SCHEMA_VERSION: Final = 1
DESIGN_CRITIQUE_IMAGE_INVALID: Final = "DESIGN_CRITIQUE_IMAGE_INVALID"
DESIGN_CRITIQUE_IMAGE_TOO_LARGE: Final = "DESIGN_CRITIQUE_IMAGE_TOO_LARGE"
DESIGN_CRITIQUE_PAGE_INVALID: Final = "DESIGN_CRITIQUE_PAGE_INVALID"
DESIGN_CRITIQUE_URL_INVALID: Final = "DESIGN_CRITIQUE_URL_INVALID"
DESIGN_CRITIQUE_SOURCE_INVALID: Final = "DESIGN_CRITIQUE_SOURCE_INVALID"
DESIGN_CRITIQUE_SOURCE_NOT_FOUND: Final = "DESIGN_CRITIQUE_SOURCE_NOT_FOUND"
DESIGN_CRITIQUE_TWINS_REQUIRED: Final = "DESIGN_CRITIQUE_TWINS_REQUIRED"
DESIGN_CRITIQUE_PROVIDER_UNSUPPORTED: Final = "DESIGN_CRITIQUE_PROVIDER_UNSUPPORTED"
DESIGN_CRITIQUE_FAILED: Final = "DESIGN_CRITIQUE_FAILED"
DESIGN_CRITIQUE_INVALID: Final = "DESIGN_CRITIQUE_INVALID"
DESIGN_CRITIQUE_ERROR_CODES: Final = (
    DESIGN_CRITIQUE_IMAGE_INVALID,
    DESIGN_CRITIQUE_IMAGE_TOO_LARGE,
    DESIGN_CRITIQUE_PAGE_INVALID,
    DESIGN_CRITIQUE_URL_INVALID,
    DESIGN_CRITIQUE_SOURCE_INVALID,
    DESIGN_CRITIQUE_SOURCE_NOT_FOUND,
    DESIGN_CRITIQUE_TWINS_REQUIRED,
    DESIGN_CRITIQUE_PROVIDER_UNSUPPORTED,
    DESIGN_CRITIQUE_FAILED,
    DESIGN_CRITIQUE_INVALID,
)
MAX_SHOTS: Final = 2
MAX_SHOT_BYTES: Final = 5 * 1024 * 1024
MAX_IMAGE_SIDE: Final = 8000
MIN_IMAGE_SIDE: Final = 16
SHOT_MEDIA_TYPES: Final = frozenset({"image/png", "image/jpeg"})
MAX_TITLE_LENGTH: Final = 200
MAX_URL_LENGTH: Final = 2048
CAPTURE_WIDTHS: Final = (1440, 390)
MAX_PAGE_TEXT_LENGTH: Final = 20_000
MAX_PAGE_HIDDEN_TEXT_LENGTH: Final = 4_000
MAX_PAGE_ELEMENTS: Final = 400
MAX_PAGE_ROLE_LENGTH: Final = 32
MAX_PAGE_NAME_LENGTH: Final = 200
MAX_PAGE_VALUE_LENGTH: Final = 200
MAX_PAGE_OPTIONS: Final = 20
PAGE_ELEMENT_STATES: Final = ("checked", "disabled")
PAGE_LOCATION: Final = "critique/page.json"
PAGE_MEDIA_TYPE: Final = "application/json"
MAX_TWIN_NAME_LENGTH: Final = 200
VERDICT_WORKS: Final = "WORKS"
VERDICT_SLOWS: Final = "SLOWS"
VERDICT_BLOCKS: Final = "BLOCKS"
SHOT_CODES: Final = tuple(f"SCR-{number:03d}" for number in range(1, MAX_SHOTS + 1))
FILE_EXTENSIONS: Final = {"image/png": "png", "image/jpeg": "jpg"}
SCREEN_LABELS: Final = {
    "it": ("Schermata {number} · {width} px", "Immagine fornita · {width} x {height} px"),
    "en": ("Screen {number} · {width} px", "Supplied image · {width} x {height} px"),
}
SCENARIO_TASKS: Final = {
    "it": "Capire questo design e usarlo per il tuo scopo abituale con un prodotto come questo",
    "en": "Understand this design and use it for your usual goal with a product like this one",
}
SCENARIO_OUTCOMES: Final = {
    "it": "Trovi ciò che ti serve e sai che cosa fare",
    "en": "You find what you need and you know what to do",
}
_SCENARIO_NAMESPACE: Final = UUID("8f3c1a52-6d47-4b9e-a1c3-5e2f7d9b0c44")
_PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE: Final = b"\xff\xd8\xff"
_JPEG_FRAMES: Final = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
_JPEG_STANDALONE: Final = frozenset({0x01, *range(0xD0, 0xD8)})
_JPEG_STOPS: Final = frozenset({0x00, 0xD8, 0xD9, 0xDA})
_BLOCKING: Final = frozenset({SyntheticFindingSeverity.CRITICAL, SyntheticFindingSeverity.MAJOR})
_SLOWING: Final = frozenset({SyntheticFindingSeverity.MODERATE, SyntheticFindingSeverity.MINOR})
_WEB_SCHEMES: Final = frozenset({"http", "https"})
_DIGEST: Final = re.compile(r"[0-9a-f]{64}")


class DesignCritiqueError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DesignCritiqueSourceKind(StrEnum):
    IMAGE = "IMAGE"
    WEB_PAGE = "WEB_PAGE"


def _is_compact(value: object, minimum: int, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and " ".join(value.split()) == value
        and minimum <= len(value) <= maximum
    )


def _is_count(value: object, minimum: int, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


def _is_aware(value: object) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _language(value: object) -> str:
    return "it" if isinstance(value, str) and value.split("-")[0].lower() == "it" else "en"


def is_web_url(value: object) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_URL_LENGTH:
        return False
    if any(character.isspace() or not character.isprintable() for character in value):
        return False
    try:
        parts = urlsplit(value)
        host = parts.hostname
    except ValueError:
        return False
    return parts.scheme in _WEB_SCHEMES and bool(host)


def image_media_type(content: bytes) -> str:
    if isinstance(content, bytes | bytearray):
        if content.startswith(_PNG_SIGNATURE):
            return "image/png"
        if content.startswith(_JPEG_SIGNATURE):
            return "image/jpeg"
    raise DesignCritiqueError(DESIGN_CRITIQUE_IMAGE_INVALID)


def _png_size(content: bytes) -> tuple[int, int] | None:
    if len(content) < 24 or content[12:16] != b"IHDR":
        return None
    return int.from_bytes(content[16:20], "big"), int.from_bytes(content[20:24], "big")


def _jpeg_size(content: bytes) -> tuple[int, int] | None:
    position = 2
    while position + 1 < len(content):
        if content[position] != 0xFF:
            return None
        marker = content[position + 1]
        if marker == 0xFF:
            position += 1
            continue
        if marker in _JPEG_STANDALONE:
            position += 2
            continue
        if marker in _JPEG_STOPS or position + 4 > len(content):
            return None
        length = int.from_bytes(content[position + 2 : position + 4], "big")
        if length < 2:
            return None
        if marker in _JPEG_FRAMES:
            if length < 7 or position + 9 > len(content):
                return None
            height = int.from_bytes(content[position + 5 : position + 7], "big")
            width = int.from_bytes(content[position + 7 : position + 9], "big")
            return width, height
        position += 2 + length
    return None


def image_dimensions(content: bytes) -> tuple[int, int]:
    media_type = image_media_type(content)
    size = _png_size(content) if media_type == "image/png" else _jpeg_size(content)
    if size is None or min(size) < 1:
        raise DesignCritiqueError(DESIGN_CRITIQUE_IMAGE_INVALID)
    return size


def _valid_options(options: object) -> bool:
    return (
        isinstance(options, tuple)
        and len(options) <= MAX_PAGE_OPTIONS
        and all(_is_compact(option, 1, MAX_PAGE_NAME_LENGTH) for option in options)
    )


@dataclass(frozen=True, slots=True)
class DesignCritiquePageElement:
    index: int
    role: str
    name: str
    value: str | None = None
    state: str | None = None
    options: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not (
            _is_count(self.index, 0, MAX_PAGE_ELEMENTS - 1)
            and _is_compact(self.role, 1, MAX_PAGE_ROLE_LENGTH)
            and _is_compact(self.name, 0, MAX_PAGE_NAME_LENGTH)
            and (self.value is None or _is_compact(self.value, 0, MAX_PAGE_VALUE_LENGTH))
            and (self.state is None or self.state in PAGE_ELEMENT_STATES)
            and (self.options is None or _valid_options(self.options))
        ):
            raise DesignCritiqueError(DESIGN_CRITIQUE_PAGE_INVALID)

    def to_snapshot(self) -> dict[str, object]:
        snapshot: dict[str, object] = {"index": self.index, "role": self.role, "name": self.name}
        if self.value is not None:
            snapshot["value"] = self.value
        if self.state is not None:
            snapshot["state"] = self.state
        if self.options is not None:
            snapshot["options"] = list(self.options)
        return snapshot


@dataclass(frozen=True, slots=True)
class DesignCritiquePage:
    url: str
    title: str
    text: str
    hidden_text: str
    elements: tuple[DesignCritiquePageElement, ...]

    def __post_init__(self) -> None:
        if not (
            is_web_url(self.url)
            and _is_compact(self.title, 0, MAX_TITLE_LENGTH)
            and _is_compact(self.text, 0, MAX_PAGE_TEXT_LENGTH)
            and _is_compact(self.hidden_text, 0, MAX_PAGE_HIDDEN_TEXT_LENGTH)
            and isinstance(self.elements, tuple)
            and len(self.elements) <= MAX_PAGE_ELEMENTS
            and all(
                isinstance(element, DesignCritiquePageElement) and element.index == position
                for position, element in enumerate(self.elements)
            )
        ):
            raise DesignCritiqueError(DESIGN_CRITIQUE_PAGE_INVALID)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "hidden_text": self.hidden_text,
            "elements": [element.to_snapshot() for element in self.elements],
        }


def _page_text(value: object) -> str:
    if not isinstance(value, str):
        raise DesignCritiqueError(DESIGN_CRITIQUE_PAGE_INVALID)
    return " ".join(value.split())


def _page_element(item: object, position: int) -> DesignCritiquePageElement:
    if not isinstance(item, Mapping) or not _is_count(item.get("index"), position, position):
        raise DesignCritiqueError(DESIGN_CRITIQUE_PAGE_INVALID)
    value = item.get("value")
    options = item.get("options")
    if options is not None and not isinstance(options, list | tuple):
        raise DesignCritiqueError(DESIGN_CRITIQUE_PAGE_INVALID)
    labels = None if options is None else tuple(_page_text(option) for option in options)
    return DesignCritiquePageElement(
        index=position,
        role=_page_text(item.get("role")),
        name=_page_text(item.get("name", "")),
        value=None if value is None else _page_text(value),
        state=item.get("state"),
        options=None if labels is None else tuple(label for label in labels if label),
    )


def page_from_document(document: object) -> DesignCritiquePage:
    if not isinstance(document, Mapping):
        raise DesignCritiqueError(DESIGN_CRITIQUE_PAGE_INVALID)
    elements = document.get("elements", ())
    if not isinstance(elements, list | tuple) or len(elements) > MAX_PAGE_ELEMENTS:
        raise DesignCritiqueError(DESIGN_CRITIQUE_PAGE_INVALID)
    return DesignCritiquePage(
        url=document.get("url"),
        title=_page_text(document.get("title", "")),
        text=_page_text(document.get("text", "")),
        hidden_text=_page_text(document.get("hidden_text", "")),
        elements=tuple(_page_element(item, position) for position, item in enumerate(elements)),
    )


@dataclass(frozen=True, slots=True)
class DesignCritiqueShot:
    code: str
    media_type: str
    byte_size: int
    sha256: str
    width: int
    height: int
    viewport_width: int | None = None

    def __post_init__(self) -> None:
        if not (
            isinstance(self.code, str)
            and self.code in SHOT_CODES
            and isinstance(self.media_type, str)
            and self.media_type in SHOT_MEDIA_TYPES
            and _is_count(self.byte_size, 1, MAX_SHOT_BYTES)
            and _is_digest(self.sha256)
            and _is_count(self.width, MIN_IMAGE_SIDE, MAX_IMAGE_SIDE)
            and _is_count(self.height, MIN_IMAGE_SIDE, MAX_IMAGE_SIDE)
            and (
                self.viewport_width is None
                or _is_count(self.viewport_width, MIN_IMAGE_SIDE, MAX_IMAGE_SIDE)
            )
        ):
            raise DesignCritiqueError(DESIGN_CRITIQUE_SOURCE_INVALID)

    @property
    def file_name(self) -> str:
        return f"screenshot-{self.code[4:]}.{FILE_EXTENSIONS[self.media_type]}"

    def to_snapshot(self) -> dict[str, object]:
        return {
            "code": self.code,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
            "viewport_width": self.viewport_width,
        }


def _shot_from_snapshot(item: Mapping[str, object]) -> DesignCritiqueShot:
    return DesignCritiqueShot(
        code=item["code"],
        media_type=item["media_type"],
        byte_size=item["byte_size"],
        sha256=item["sha256"],
        width=item["width"],
        height=item["height"],
        viewport_width=item["viewport_width"],
    )


def _measured_shot(content: object, viewport_width: object, position: int) -> DesignCritiqueShot:
    if not isinstance(content, bytes | bytearray) or not content:
        raise DesignCritiqueError(DESIGN_CRITIQUE_IMAGE_INVALID)
    if len(content) > MAX_SHOT_BYTES:
        raise DesignCritiqueError(DESIGN_CRITIQUE_IMAGE_TOO_LARGE)
    media_type = image_media_type(content)
    width, height = image_dimensions(content)
    if max(width, height) > MAX_IMAGE_SIDE:
        raise DesignCritiqueError(DESIGN_CRITIQUE_IMAGE_TOO_LARGE)
    if min(width, height) < MIN_IMAGE_SIDE:
        raise DesignCritiqueError(DESIGN_CRITIQUE_IMAGE_INVALID)
    if viewport_width is not None and not _is_count(viewport_width, MIN_IMAGE_SIDE, MAX_IMAGE_SIDE):
        raise DesignCritiqueError(DESIGN_CRITIQUE_SOURCE_INVALID)
    return DesignCritiqueShot(
        code=SHOT_CODES[position],
        media_type=media_type,
        byte_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        width=width,
        height=height,
        viewport_width=viewport_width,
    )


def _source_semantic(
    *, source_id, project_id, owner_user_id, kind, title, url, page, shots, created_at
) -> dict[str, object]:
    return {
        "schema_version": DESIGN_CRITIQUE_SCHEMA_VERSION,
        "id": str(source_id),
        "project_id": str(project_id),
        "owner_user_id": str(owner_user_id),
        "kind": kind.value,
        "title": title,
        "url": url,
        "page": None if page is None else page.to_snapshot(),
        "shots": [shot.to_snapshot() for shot in shots],
        "created_at": created_at.astimezone(UTC).isoformat(),
    }


@dataclass(frozen=True, slots=True)
class DesignCritiqueSource:
    id: UUID
    project_id: UUID
    owner_user_id: UUID
    kind: DesignCritiqueSourceKind
    title: str
    url: str | None
    page: DesignCritiquePage | None
    shots: tuple[DesignCritiqueShot, ...]
    created_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DesignCritiqueSourceKind) or not _is_compact(
            self.title, 1, MAX_TITLE_LENGTH
        ):
            raise DesignCritiqueError(DESIGN_CRITIQUE_SOURCE_INVALID)
        if not (
            isinstance(self.shots, tuple)
            and 1 <= len(self.shots) <= MAX_SHOTS
            and all(
                isinstance(shot, DesignCritiqueShot) and shot.code == SHOT_CODES[position]
                for position, shot in enumerate(self.shots)
            )
        ):
            raise DesignCritiqueError(DESIGN_CRITIQUE_SOURCE_INVALID)
        if self.kind is DesignCritiqueSourceKind.IMAGE:
            if self.url is not None or self.page is not None:
                raise DesignCritiqueError(DESIGN_CRITIQUE_SOURCE_INVALID)
        elif not is_web_url(self.url):
            raise DesignCritiqueError(DESIGN_CRITIQUE_URL_INVALID)
        elif self.page is not None and not isinstance(self.page, DesignCritiquePage):
            raise DesignCritiqueError(DESIGN_CRITIQUE_PAGE_INVALID)
        if not _is_aware(self.created_at) or not _is_digest(self.content_hash):
            raise DesignCritiqueError(DESIGN_CRITIQUE_SOURCE_INVALID)
        if self.content_hash != snapshot_content_hash(self.semantic_snapshot()):
            raise DesignCritiqueError(DESIGN_CRITIQUE_SOURCE_INVALID)

    def semantic_snapshot(self) -> dict[str, object]:
        return _source_semantic(
            source_id=self.id,
            project_id=self.project_id,
            owner_user_id=self.owner_user_id,
            kind=self.kind,
            title=self.title,
            url=self.url,
            page=self.page,
            shots=self.shots,
            created_at=self.created_at,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {**self.semantic_snapshot(), "content_hash": self.content_hash}


def create_design_critique_source(
    *,
    source_id: UUID,
    project_id: UUID,
    owner_user_id: UUID,
    kind: DesignCritiqueSourceKind | str,
    title: str,
    url: str | None,
    page: DesignCritiquePage | Mapping[str, object] | None,
    shots: Sequence[tuple[bytes, int | None]],
    created_at: datetime,
) -> tuple[DesignCritiqueSource, dict[str, bytes]]:
    try:
        resolved = DesignCritiqueSourceKind(kind)
    except ValueError as error:
        raise DesignCritiqueError(DESIGN_CRITIQUE_SOURCE_INVALID) from error
    name = " ".join(title.split()) if isinstance(title, str) else ""
    if not 1 <= len(name) <= MAX_TITLE_LENGTH:
        raise DesignCritiqueError(DESIGN_CRITIQUE_SOURCE_INVALID)
    address = (url.strip() or None) if isinstance(url, str) else url
    if resolved is DesignCritiqueSourceKind.IMAGE:
        if address is not None or page is not None:
            raise DesignCritiqueError(DESIGN_CRITIQUE_SOURCE_INVALID)
    elif not is_web_url(address):
        raise DesignCritiqueError(DESIGN_CRITIQUE_URL_INVALID)
    parsed = (
        page if page is None or isinstance(page, DesignCritiquePage) else page_from_document(page)
    )
    if (
        isinstance(shots, str | bytes | bytearray)
        or not isinstance(shots, Sequence)
        or not 1 <= len(shots) <= MAX_SHOTS
        or any(not isinstance(item, tuple | list) or len(item) != 2 for item in shots)
    ):
        raise DesignCritiqueError(DESIGN_CRITIQUE_SOURCE_INVALID)
    measured = tuple(
        _measured_shot(content, viewport, position)
        for position, (content, viewport) in enumerate(shots)
    )
    if not _is_aware(created_at):
        raise DesignCritiqueError(DESIGN_CRITIQUE_SOURCE_INVALID)
    semantic = _source_semantic(
        source_id=source_id,
        project_id=project_id,
        owner_user_id=owner_user_id,
        kind=resolved,
        title=name,
        url=address,
        page=parsed,
        shots=measured,
        created_at=created_at,
    )
    source = DesignCritiqueSource(
        id=source_id,
        project_id=project_id,
        owner_user_id=owner_user_id,
        kind=resolved,
        title=name,
        url=address,
        page=parsed,
        shots=measured,
        created_at=created_at,
        content_hash=snapshot_content_hash(semantic),
    )
    return source, {shot.code: bytes(item[0]) for shot, item in zip(measured, shots, strict=True)}


def design_critique_source_from_snapshot(payload: Mapping[str, object]) -> DesignCritiqueSource:
    try:
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != DESIGN_CRITIQUE_SCHEMA_VERSION
        ):
            raise DesignCritiqueError(DESIGN_CRITIQUE_SOURCE_INVALID)
        page = payload["page"]
        source = DesignCritiqueSource(
            id=UUID(str(payload["id"])),
            project_id=UUID(str(payload["project_id"])),
            owner_user_id=UUID(str(payload["owner_user_id"])),
            kind=DesignCritiqueSourceKind(payload["kind"]),
            title=payload["title"],
            url=payload["url"],
            page=None if page is None else page_from_document(page),
            shots=tuple(_shot_from_snapshot(item) for item in payload["shots"]),
            created_at=datetime.fromisoformat(payload["created_at"]),
            content_hash=payload["content_hash"],
        )
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise DesignCritiqueError(DESIGN_CRITIQUE_SOURCE_INVALID) from error
    if source.to_snapshot() != dict(payload):
        raise DesignCritiqueError(DESIGN_CRITIQUE_SOURCE_INVALID)
    return source


def screen_label(shot: DesignCritiqueShot, number: int, language: str) -> str:
    screen, image = SCREEN_LABELS[_language(language)]
    if shot.viewport_width is not None:
        return screen.format(number=number, width=shot.viewport_width)
    return image.format(width=shot.width, height=shot.height)


def critique_anchors(source: DesignCritiqueSource, language: str) -> dict[str, str]:
    return {
        shot.code: f"{shot.code} {screen_label(shot, number, language)}"
        for number, shot in enumerate(source.shots, 1)
    }


def critique_source_view(source: DesignCritiqueSource, language: str) -> dict[str, object]:
    return {
        "kind": source.kind.value,
        "title": source.title,
        "url": source.url,
        "page": None if source.page is None else source.page.to_snapshot(),
        "screens": [
            {
                "code": shot.code,
                "file": shot.file_name,
                "label": screen_label(shot, number, language),
                "width": shot.width,
                "height": shot.height,
                "viewport_width": shot.viewport_width,
            }
            for number, shot in enumerate(source.shots, 1)
        ],
    }


def shot_content(shot: DesignCritiqueShot, contents: Mapping[str, bytes]) -> bytes:
    content = contents.get(shot.code)
    if (
        not isinstance(content, bytes | bytearray)
        or hashlib.sha256(content).hexdigest() != shot.sha256
    ):
        raise DesignCritiqueError(DESIGN_CRITIQUE_SOURCE_INVALID)
    return bytes(content)


def critique_attachments(
    source: DesignCritiqueSource, contents: Mapping[str, bytes]
) -> tuple[GenerationAttachment, ...]:
    return tuple(
        GenerationAttachment(
            name=shot.file_name,
            media_type=shot.media_type,
            content=shot_content(shot, contents),
        )
        for shot in source.shots
    )


def critique_scenario(source: DesignCritiqueSource, locale: str) -> EvaluationScenario:
    language = _language(locale)
    return EvaluationScenario(
        id=uuid5(_SCENARIO_NAMESPACE, str(source.id)),
        name=source.title,
        task=SCENARIO_TASKS[language],
        locale=locale,
        expected_outcomes=(SCENARIO_OUTCOMES[language],),
    )


def critique_bundle(
    source: DesignCritiqueSource,
    contents: Mapping[str, bytes],
    *,
    locale: str,
    created_at: datetime,
    bundle_id: UUID | None = None,
) -> EvaluationArtifactBundle:
    artifacts = [
        evaluation_reference(
            artifact_id=source.id,
            version_number=number,
            kind=EvaluationArtifactKind.SCREENSHOT,
            media_type=shot.media_type,
            content=shot_content(shot, contents),
            location=f"critique/{shot.code}.{FILE_EXTENSIONS[shot.media_type]}",
        )
        for number, shot in enumerate(source.shots, 1)
    ]
    if source.page is not None:
        artifacts.append(
            evaluation_reference(
                artifact_id=source.id,
                version_number=1,
                kind=EvaluationArtifactKind.DOM_SNAPSHOT,
                media_type=PAGE_MEDIA_TYPE,
                content=canonical_json(source.page.to_snapshot()).encode("utf-8"),
                location=PAGE_LOCATION,
            )
        )
    return create_evaluation_artifact_bundle(
        project_id=source.project_id,
        workflow_run_id=source.id,
        scenario=critique_scenario(source, locale),
        artifacts=tuple(artifacts),
        created_at=created_at,
        bundle_id=bundle_id,
    )


def verdict_of(severities: Iterable[SyntheticFindingSeverity | str]) -> str:
    found = {SyntheticFindingSeverity(item) for item in severities}
    if found & _BLOCKING:
        return VERDICT_BLOCKS
    if found & _SLOWING:
        return VERDICT_SLOWS
    return VERDICT_WORKS


def _screen_of(finding: SyntheticFinding) -> str | None:
    anchor = finding_anchor_key(finding)
    return anchor if anchor is not None and "/" not in anchor else None


def _twin_matches(entry: object, response: UserTwinEvaluationResponse) -> bool:
    return (
        isinstance(entry, tuple)
        and len(entry) == 3
        and entry[0] == response.twin_id
        and _is_count(entry[1], response.twin_version, response.twin_version)
        and _is_compact(entry[2], 1, MAX_TWIN_NAME_LENGTH)
    )


def _run_semantic(
    *,
    run_id,
    project_id,
    owner_user_id,
    source,
    bundle,
    twins,
    responses,
    started_at,
    completed_at,
) -> dict[str, object]:
    return {
        "schema_version": DESIGN_CRITIQUE_SCHEMA_VERSION,
        "id": str(run_id),
        "project_id": str(project_id),
        "owner_user_id": str(owner_user_id),
        "source": source.to_snapshot(),
        "bundle": bundle.to_snapshot(),
        "twins": [
            {"twin_id": str(twin_id), "version_number": version_number, "name": name}
            for twin_id, version_number, name in twins
        ],
        "responses": [response.to_snapshot() for response in responses],
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
    }


@dataclass(frozen=True, slots=True)
class DesignCritiqueRun:
    id: UUID
    project_id: UUID
    owner_user_id: UUID
    source: DesignCritiqueSource
    bundle: EvaluationArtifactBundle
    twins: tuple[tuple[UUID, int, str], ...]
    responses: tuple[UserTwinEvaluationResponse, ...]
    started_at: datetime
    completed_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        if not self._consistent() or self.content_hash != design_critique_run_hash(self):
            raise DesignCritiqueError(DESIGN_CRITIQUE_INVALID)

    def _consistent(self) -> bool:
        source, bundle, responses = self.source, self.bundle, self.responses
        if not isinstance(source, DesignCritiqueSource) or not isinstance(
            bundle, EvaluationArtifactBundle
        ):
            return False
        if (source.project_id, source.owner_user_id) != (self.project_id, self.owner_user_id):
            return False
        if bundle.project_id != self.project_id or bundle.workflow_run_id != source.id:
            return False
        if not isinstance(responses, tuple) or not 1 <= len(responses) <= MAX_EVALUATED_TWINS:
            return False
        identities = [response.twin_id for response in responses]
        if len(set(identities)) != len(identities):
            return False
        if any(
            response.evaluation_run_id != self.id
            or response.artifact_bundle_id != bundle.id
            or response.artifact_bundle_hash != bundle.content_hash
            for response in responses
        ):
            return False
        if not (
            isinstance(self.twins, tuple)
            and len(self.twins) == len(responses)
            and all(
                _twin_matches(entry, response)
                for entry, response in zip(self.twins, responses, strict=True)
            )
        ):
            return False
        codes = {shot.code for shot in source.shots}
        if any(_screen_of(finding) not in codes for finding in self.findings):
            return False
        if not (_is_aware(self.started_at) and _is_aware(self.completed_at)):
            return False
        return self.completed_at >= self.started_at and _is_digest(self.content_hash)

    @property
    def findings(self) -> tuple[SyntheticFinding, ...]:
        return tuple(finding for response in self.responses for finding in response.findings)

    @property
    def evaluator(self) -> UserTwinEvaluatorConfiguration:
        return self.responses[0].evaluator

    def verdicts(self) -> tuple[dict[str, str], ...]:
        return tuple(
            {
                "twin_id": str(response.twin_id),
                "anchor_key": shot.code,
                "verdict": verdict_of(
                    finding.severity
                    for finding in response.findings
                    if _screen_of(finding) == shot.code
                ),
            }
            for response in self.responses
            for shot in self.source.shots
        )

    def semantic_snapshot(self) -> dict[str, object]:
        return _run_semantic(
            run_id=self.id,
            project_id=self.project_id,
            owner_user_id=self.owner_user_id,
            source=self.source,
            bundle=self.bundle,
            twins=self.twins,
            responses=self.responses,
            started_at=self.started_at,
            completed_at=self.completed_at,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {**self.semantic_snapshot(), "content_hash": self.content_hash}


def design_critique_run_hash(run: DesignCritiqueRun) -> str:
    return snapshot_content_hash(run.semantic_snapshot())


def create_design_critique_run(
    *,
    run_id: UUID,
    owner_user_id: UUID,
    source: DesignCritiqueSource,
    bundle: EvaluationArtifactBundle,
    twins: Sequence[tuple[UUID, int, str]],
    responses: Sequence[UserTwinEvaluationResponse],
    started_at: datetime,
    completed_at: datetime,
) -> DesignCritiqueRun:
    ordered = tuple(sorted(responses, key=lambda item: str(item.twin_id)))
    named: dict[UUID, tuple[UUID, int, str]] = {}
    for entry in twins:
        if not isinstance(entry, tuple | list) or len(entry) != 3 or not isinstance(entry[2], str):
            raise DesignCritiqueError(DESIGN_CRITIQUE_INVALID)
        twin_id, version_number, name = entry
        if twin_id in named:
            raise DesignCritiqueError(DESIGN_CRITIQUE_INVALID)
        named[twin_id] = (twin_id, version_number, " ".join(name.split()))
    if set(named) != {response.twin_id for response in ordered}:
        raise DesignCritiqueError(DESIGN_CRITIQUE_INVALID)
    listed = tuple(named[response.twin_id] for response in ordered)
    values = {
        "run_id": run_id,
        "project_id": source.project_id,
        "owner_user_id": owner_user_id,
        "source": source,
        "bundle": bundle,
        "twins": listed,
        "responses": ordered,
        "started_at": started_at,
        "completed_at": completed_at,
    }
    return DesignCritiqueRun(
        id=run_id,
        project_id=source.project_id,
        owner_user_id=owner_user_id,
        source=source,
        bundle=bundle,
        twins=listed,
        responses=ordered,
        started_at=started_at,
        completed_at=completed_at,
        content_hash=snapshot_content_hash(_run_semantic(**values)),
    )


def _twin_from_snapshot(item: Mapping[str, object]) -> tuple[UUID, object, object]:
    return UUID(str(item["twin_id"])), item["version_number"], item["name"]


def design_critique_run_from_snapshot(payload: Mapping[str, object]) -> DesignCritiqueRun:
    try:
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != DESIGN_CRITIQUE_SCHEMA_VERSION
        ):
            raise DesignCritiqueError(DESIGN_CRITIQUE_INVALID)
        run = DesignCritiqueRun(
            id=UUID(str(payload["id"])),
            project_id=UUID(str(payload["project_id"])),
            owner_user_id=UUID(str(payload["owner_user_id"])),
            source=design_critique_source_from_snapshot(payload["source"]),
            bundle=evaluation_bundle_from_snapshot(payload["bundle"]),
            twins=tuple(_twin_from_snapshot(item) for item in payload["twins"]),
            responses=tuple(
                evaluation_response_from_snapshot(item) for item in payload["responses"]
            ),
            started_at=datetime.fromisoformat(payload["started_at"]),
            completed_at=datetime.fromisoformat(payload["completed_at"]),
            content_hash=payload["content_hash"],
        )
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise DesignCritiqueError(DESIGN_CRITIQUE_INVALID) from error
    if run.to_snapshot() != dict(payload):
        raise DesignCritiqueError(DESIGN_CRITIQUE_INVALID)
    return run


__all__ = [
    "CAPTURE_WIDTHS",
    "DESIGN_CRITIQUE_ERROR_CODES",
    "DESIGN_CRITIQUE_FAILED",
    "DESIGN_CRITIQUE_IMAGE_INVALID",
    "DESIGN_CRITIQUE_IMAGE_TOO_LARGE",
    "DESIGN_CRITIQUE_INVALID",
    "DESIGN_CRITIQUE_PAGE_INVALID",
    "DESIGN_CRITIQUE_PROVIDER_UNSUPPORTED",
    "DESIGN_CRITIQUE_SCHEMA_VERSION",
    "DESIGN_CRITIQUE_SOURCE_INVALID",
    "DESIGN_CRITIQUE_SOURCE_NOT_FOUND",
    "DESIGN_CRITIQUE_TWINS_REQUIRED",
    "DESIGN_CRITIQUE_URL_INVALID",
    "FILE_EXTENSIONS",
    "MAX_IMAGE_SIDE",
    "MAX_PAGE_ELEMENTS",
    "MAX_PAGE_HIDDEN_TEXT_LENGTH",
    "MAX_PAGE_NAME_LENGTH",
    "MAX_PAGE_OPTIONS",
    "MAX_PAGE_ROLE_LENGTH",
    "MAX_PAGE_TEXT_LENGTH",
    "MAX_PAGE_VALUE_LENGTH",
    "MAX_SHOTS",
    "MAX_SHOT_BYTES",
    "MAX_TITLE_LENGTH",
    "MAX_TWIN_NAME_LENGTH",
    "MAX_URL_LENGTH",
    "MIN_IMAGE_SIDE",
    "PAGE_ELEMENT_STATES",
    "PAGE_LOCATION",
    "PAGE_MEDIA_TYPE",
    "SCENARIO_OUTCOMES",
    "SCENARIO_TASKS",
    "SCREEN_LABELS",
    "SHOT_CODES",
    "SHOT_MEDIA_TYPES",
    "VERDICT_BLOCKS",
    "VERDICT_SLOWS",
    "VERDICT_WORKS",
    "DesignCritiqueError",
    "DesignCritiquePage",
    "DesignCritiquePageElement",
    "DesignCritiqueRun",
    "DesignCritiqueShot",
    "DesignCritiqueSource",
    "DesignCritiqueSourceKind",
    "create_design_critique_run",
    "create_design_critique_source",
    "critique_anchors",
    "critique_attachments",
    "critique_bundle",
    "critique_scenario",
    "critique_source_view",
    "design_critique_run_from_snapshot",
    "design_critique_run_hash",
    "design_critique_source_from_snapshot",
    "image_dimensions",
    "image_media_type",
    "is_web_url",
    "page_from_document",
    "screen_label",
    "shot_content",
    "verdict_of",
]
