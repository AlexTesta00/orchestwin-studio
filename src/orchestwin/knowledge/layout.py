from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Final
from uuid import UUID

from orchestwin.knowledge.state import (
    FEEDBACK_CHANGES,
    FEEDBACK_LEARNING,
    FEEDBACK_TESTS,
    STATE_DOCUMENT,
    STATE_FOLDER,
    STATE_TEXT,
)

KNOWLEDGE_SCHEMA_VERSION: Final = 3
SUPPORTED_SCHEMA_VERSIONS: Final = (2, 3)
KNOWLEDGE_INDEX: Final = "ORCHESTWIN.md"
KNOWLEDGE_MANIFEST: Final = "orchestwin.json"
KNOWLEDGE_FOLDER_NAME: Final = "orchestwin"
KNOWLEDGE_FOLDER_KIND: Final = "orchestwin.knowledge-folder"
STAGES: Final = ("brief", "team", "twins", "requirements", "design")
STAGE_LABELS: Final = {
    "brief": "Project brief",
    "team": "Perspectives",
    "twins": "User twins",
    "requirements": "Definition",
    "design": "Design and evaluation",
}
STAGE_PAYLOAD_KEYS: Final = {
    "brief": "brief",
    "team": "proposal",
    "twins": "snapshot",
    "requirements": "specification",
    "design": "package",
}
VIEW_STAGES: Final = ("requirements", "design")
SCHEMA_FOLDER: Final = "schema"
TWIN_FOLDER: Final = "twins"
FEEDBACK_FOLDER: Final = "twins/feedback"
TABLE_FOLDER: Final = "tables"
DIAGRAM_FOLDER: Final = "diagrams"
TWIN_DOCUMENT_KIND: Final = "orchestwin.user-twin"
FEEDBACK_REVIEWS: Final = f"{FEEDBACK_FOLDER}/reviews.json"
FEEDBACK_DISCUSSIONS: Final = f"{FEEDBACK_FOLDER}/discussions.json"
FEEDBACK_INSIGHTS: Final = f"{FEEDBACK_FOLDER}/insights.json"
FEEDBACK_TEXT: Final = f"{FEEDBACK_FOLDER}/feedback.md"
SCHEMA_FILE_NAMES: Final = {"learning": "learned"}

_SLUG_LIMIT: Final = 48
_SLUG_SEPARATORS: Final = re.compile(r"[^a-z0-9]+")


def stage_document(stage: str) -> str:
    return f"{stage}/{stage}.json"


def stage_text(stage: str) -> str:
    return f"{stage}/{stage}.md"


def schema_document(name: str) -> str:
    return f"{SCHEMA_FOLDER}/{SCHEMA_FILE_NAMES.get(name, name)}.schema.json"


def twin_slug(name: str, twin_id: UUID | str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    words = _SLUG_SEPARATORS.sub("-", ascii_name.lower()).strip("-")[:_SLUG_LIMIT].strip("-")
    suffix = UUID(str(twin_id)).hex[:8]
    return f"{words or 'twin'}-{suffix}"


def twin_document(slug: str) -> str:
    return f"{TWIN_FOLDER}/{slug}/twin.json"


def twin_text(slug: str) -> str:
    return f"{TWIN_FOLDER}/{slug}/twin.md"


def table_document(stage: str, name: str) -> str:
    return f"{stage}/{TABLE_FOLDER}/{name}.csv"


def stage_present(manifest: Mapping[str, object], stage: str) -> bool:
    stages = manifest.get("stages")
    return isinstance(stages, Mapping) and isinstance(stages.get(stage), Mapping)


def present_stages(manifest: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(stage for stage in STAGES if stage_present(manifest, stage))


__all__ = [
    "DIAGRAM_FOLDER",
    "FEEDBACK_CHANGES",
    "FEEDBACK_DISCUSSIONS",
    "FEEDBACK_FOLDER",
    "FEEDBACK_INSIGHTS",
    "FEEDBACK_LEARNING",
    "FEEDBACK_REVIEWS",
    "FEEDBACK_TESTS",
    "FEEDBACK_TEXT",
    "KNOWLEDGE_FOLDER_KIND",
    "KNOWLEDGE_FOLDER_NAME",
    "KNOWLEDGE_INDEX",
    "KNOWLEDGE_MANIFEST",
    "KNOWLEDGE_SCHEMA_VERSION",
    "SCHEMA_FILE_NAMES",
    "SCHEMA_FOLDER",
    "STAGES",
    "STAGE_LABELS",
    "STAGE_PAYLOAD_KEYS",
    "STATE_DOCUMENT",
    "STATE_FOLDER",
    "STATE_TEXT",
    "SUPPORTED_SCHEMA_VERSIONS",
    "TABLE_FOLDER",
    "TWIN_DOCUMENT_KIND",
    "TWIN_FOLDER",
    "VIEW_STAGES",
    "present_stages",
    "schema_document",
    "stage_document",
    "stage_present",
    "stage_text",
    "table_document",
    "twin_document",
    "twin_slug",
    "twin_text",
]
