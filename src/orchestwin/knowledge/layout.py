from __future__ import annotations

import re
import unicodedata
from typing import Final
from uuid import UUID

KNOWLEDGE_SCHEMA_VERSION: Final = 2
KNOWLEDGE_INDEX: Final = "ORCHESTWIN.md"
KNOWLEDGE_MANIFEST: Final = "orchestwin.json"
KNOWLEDGE_FOLDER_NAME: Final = "orchestwin"
KNOWLEDGE_FOLDER_KIND: Final = "orchestwin.knowledge-folder"
STAGES: Final = ("brief", "team", "twins", "requirements", "design")
STAGE_LABELS: Final = {
    "brief": "Project brief",
    "team": "Agent team",
    "twins": "User twins",
    "requirements": "Requirements",
    "design": "Design",
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

_SLUG_LIMIT: Final = 48
_SLUG_SEPARATORS: Final = re.compile(r"[^a-z0-9]+")


def stage_document(stage: str) -> str:
    return f"{stage}/{stage}.json"


def stage_text(stage: str) -> str:
    return f"{stage}/{stage}.md"


def schema_document(name: str) -> str:
    return f"{SCHEMA_FOLDER}/{name}.schema.json"


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


__all__ = [
    "DIAGRAM_FOLDER",
    "FEEDBACK_DISCUSSIONS",
    "FEEDBACK_FOLDER",
    "FEEDBACK_INSIGHTS",
    "FEEDBACK_REVIEWS",
    "FEEDBACK_TEXT",
    "KNOWLEDGE_FOLDER_KIND",
    "KNOWLEDGE_FOLDER_NAME",
    "KNOWLEDGE_INDEX",
    "KNOWLEDGE_MANIFEST",
    "KNOWLEDGE_SCHEMA_VERSION",
    "SCHEMA_FOLDER",
    "STAGES",
    "STAGE_LABELS",
    "STAGE_PAYLOAD_KEYS",
    "TABLE_FOLDER",
    "TWIN_DOCUMENT_KIND",
    "TWIN_FOLDER",
    "VIEW_STAGES",
    "schema_document",
    "stage_document",
    "stage_text",
    "table_document",
    "twin_document",
    "twin_slug",
    "twin_text",
]
