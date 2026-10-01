from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from orchestwin.knowledge.layout import (
    KNOWLEDGE_SCHEMA_VERSION,
    TWIN_DOCUMENT_KIND,
    twin_document,
    twin_slug,
    twin_text,
)
from orchestwin.knowledge.sources import KnowledgeSources
from orchestwin.twins.user_twins import UserModelingSnapshotVersion
from orchestwin.workflow.gates import HumanGate


@dataclass(frozen=True, slots=True)
class PortableTwin:
    slug: str
    document: dict[str, object]

    @property
    def document_path(self) -> str:
        return twin_document(self.slug)

    @property
    def text_path(self) -> str:
        return twin_text(self.slug)

    @property
    def twin(self) -> Mapping[str, object]:
        return self.document["twin"]

    @property
    def persona(self) -> Mapping[str, object]:
        return self.document["persona"]

    def summary(self) -> dict[str, object]:
        profile = self.twin["profile"]
        return {
            "twin_id": self.twin["twin_id"],
            "name": profile["name"],
            "slug": self.slug,
            "version_number": self.twin["version_number"],
            "content_hash": self.twin["content_hash"],
            "validation_status": profile["validation_status"],
            "persona_id": self.persona["persona_id"],
            "document": self.document_path,
            "text": self.text_path,
        }


def _persona_of(
    twin: Mapping[str, object], personas: list[Mapping[str, object]]
) -> Mapping[str, object]:
    reference = twin["profile"]["persona_reference"]
    for persona in personas:
        if (
            persona["persona_id"] == reference["persona_id"]
            and persona["version_number"] == reference["version_number"]
            and persona["content_hash"] == reference["content_hash"]
        ):
            return persona
    raise ValueError("user twin references a persona version outside its snapshot")


def portable_twin_documents(
    *,
    project_id: UUID,
    project_name: str,
    modeling: UserModelingSnapshotVersion,
    modeling_gate: HumanGate,
) -> tuple[PortableTwin, ...]:
    snapshot = modeling.snapshot.to_snapshot()
    personas = list(snapshot["persona_versions"])
    origin = {
        "project_id": str(project_id),
        "project_name": project_name,
        "user_modeling": {
            "version_id": str(modeling.id),
            "version_number": modeling.version_number,
            "content_hash": modeling.content_hash,
        },
        "approved_at": modeling_gate.updated_at.isoformat(),
    }
    twins = []
    for twin in snapshot["twin_versions"]:
        slug = twin_slug(twin["profile"]["name"], twin["twin_id"])
        twins.append(
            PortableTwin(
                slug=slug,
                document={
                    "schema_version": KNOWLEDGE_SCHEMA_VERSION,
                    "kind": TWIN_DOCUMENT_KIND,
                    "slug": slug,
                    "origin": dict(origin),
                    "persona": _persona_of(twin, personas),
                    "twin": twin,
                },
            )
        )
    return tuple(twins)


def portable_twins(sources: KnowledgeSources) -> tuple[PortableTwin, ...]:
    if sources.modeling is None or sources.modeling_gate is None:
        return ()
    return portable_twin_documents(
        project_id=sources.project_id,
        project_name=sources.project_name,
        modeling=sources.modeling,
        modeling_gate=sources.modeling_gate,
    )


__all__ = [
    "PortableTwin",
    "portable_twin_documents",
    "portable_twins",
]
