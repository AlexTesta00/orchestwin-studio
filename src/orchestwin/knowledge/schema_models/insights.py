from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from orchestwin.knowledge.feedback import INSIGHTS_KIND
from orchestwin.knowledge.layout import SUPPORTED_SCHEMA_VERSIONS
from orchestwin.knowledge.schema_models.base import (
    _BY_VALUE,
    Sha256,
    Timestamp,
    Uuid,
    _BriefFieldName,
    _Record,
    _Version,
)
from orchestwin.projects.insight_applications import InsightSourceKind, InsightTarget


class InsightApplication(_Record):
    id: Uuid = Field(description="Identifier of the application.")
    project_id: Uuid = Field(description="Project the application belongs to.")
    owner_user_id: Uuid = Field(description="Owner who applied the insight.")
    source_kind: Annotated[InsightSourceKind, _BY_VALUE] = Field(
        description="Kind of twin feedback the insight comes from."
    )
    source_id: str = Field(description="Identifier of that feedback.")
    source_twin_id: Uuid | None = Field(
        description="User twin the insight comes from, or null when it has no single twin."
    )
    text: str = Field(description="Text that was applied.")
    target: Annotated[InsightTarget, _BY_VALUE] = Field(
        description="Artifact the insight was applied to."
    )
    target_field: _BriefFieldName | None = Field(
        description="Brief field that received the insight, or null outside the brief."
    )
    target_version_id: Uuid = Field(description="Version created by the application.")
    target_version_number: _Version = Field(description="Version number of that version.")
    target_code: str | None = Field(
        description="Code of the requirement or design item created, or null for the brief."
    )
    created_at: Timestamp = Field(description="When the insight was applied.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the application content.")


class InsightsDocument(_Record):
    schema_version: Literal[SUPPORTED_SCHEMA_VERSIONS] = Field(
        description="Version of the knowledge folder format."
    )
    kind: Literal[INSIGHTS_KIND] = Field(description="Kind of document, the applied insights.")
    project_id: Uuid = Field(description="Project the applications belong to.")
    applications: list[InsightApplication] = Field(
        description="Applied insights in the order they were applied."
    )
