from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from orchestwin.knowledge.research_evidence import EVIDENCE_KIND
from orchestwin.knowledge.schema_models.base import (
    _BY_VALUE,
    Sha256,
    Timestamp,
    Uuid,
    _code,
    _Count,
    _Record,
    _Version,
)
from orchestwin.twins.epistemics import EvidenceSourceKind
from orchestwin.twins.user_twins import UserTwinField


class ResearchEvidenceCitation(_Record):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_id: Uuid
    source_version: _Version
    content_hash: Sha256
    quote: Annotated[str, Field(min_length=1, max_length=1000)]
    start: _Count
    end: _Count
    start_line: _Version
    end_line: _Version

    @model_validator(mode="after")
    def _interval(self):
        if self.end != self.start + len(self.quote) or self.end_line < self.start_line:
            raise ValueError("citation interval does not match the exact quote")
        if "\r" in self.quote or self.end_line - self.start_line != self.quote[:-1].count("\n"):
            raise ValueError("citation lines do not match its preserved LF text")
        return self


class ResearchEvidenceLink(_Record):
    model_config = ConfigDict(extra="forbid", strict=True)
    twin_id: Uuid
    twin_version: _Version
    field: Annotated[UserTwinField, _BY_VALUE]
    effect: Literal["SUPPORTS", "CONTRADICTS", "ADDS"]
    citation: ResearchEvidenceCitation
    status: Literal["ACTIVE", "RETIRED"]
    imported_from: dict[str, object] | None = None


class ResearchEvidenceVersion(_Record):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: Uuid
    code: Annotated[str, Field(pattern=_code("EVD"))]
    version: _Version
    title: str
    source_kind: Annotated[EvidenceSourceKind, _BY_VALUE]
    source_ref: str
    context: str
    method: str
    collected_at: str | None
    limitations: str
    empirical: bool
    content_hash: Sha256
    character_count: Annotated[int, Field(ge=1, le=24000)]
    byte_count: Annotated[int, Field(ge=1, le=32768)]
    created_at: Timestamp
    status: Literal["ACTIVE", "RETIRED"]
    retired_at: Timestamp | None
    retired_reason: str | None
    text_available: bool
    imported_from: dict[str, object] | None = None

    @model_validator(mode="after")
    def _nature(self):
        if (self.source_kind is EvidenceSourceKind.EMPIRICAL_RESEARCH) != self.empirical:
            raise ValueError("declared empirical nature must match its source kind")
        if self.empirical and (not self.method.strip() or not self.limitations.strip()):
            raise ValueError("empirical sources require their method and limitations")
        if self.status == "RETIRED" and self.retired_at is None:
            raise ValueError("retired source requires its retirement time")
        return self


class ResearchEvidenceDocument(_Record):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal[EVIDENCE_KIND]
    schema_version: Literal[1]
    project_id: Uuid
    evidence: Annotated[list[ResearchEvidenceVersion], Field(max_length=50)]
    citations: list[ResearchEvidenceLink]
    omitted_sections: list[dict[str, object]] | None = None

    @model_validator(mode="after")
    def _references(self):
        sources = {(item.id, item.version): item for item in self.evidence}
        if len(sources) != len(self.evidence):
            raise ValueError("evidence source versions must be unique")
        for item in self.citations:
            quote = item.citation
            source = sources.get((quote.source_id, quote.source_version))
            if (
                source is None
                or quote.content_hash != source.content_hash
                or quote.end > source.character_count
            ):
                raise ValueError("citation does not match its source version")
            if source.status == "RETIRED" and item.status == "ACTIVE":
                raise ValueError("a retired source cannot support an active citation")
        return self
