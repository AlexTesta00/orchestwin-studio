from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from orchestwin.projects.persistence.research_evidence import SqlAlchemyResearchEvidenceRepository

EVIDENCE_DOCUMENT = "twins/evidence.json"
EVIDENCE_TEXT = "twins/evidence.md"
EVIDENCE_KIND = "orchestwin.research-evidence"


class SqlAlchemyKnowledgeEvidenceQueryService:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def current(self, *, owner_user_id: UUID, project_id: UUID) -> Mapping[str, object]:
        async with self._session_factory() as session:
            repository = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=owner_user_id)
            if not await repository.owned(project_id):
                return {}
            return await repository.dossier(project_id)


def present(document: Mapping[str, object]) -> bool:
    return bool(document.get("evidence") or document.get("citations"))


def evidence_markdown(document: Mapping[str, object], *, language: str | None) -> str:
    italian = language == "it"
    lines = ["# Evidenze" if italian else "# Evidence", ""]
    lines.extend(
        [
            "Il Dossier conserva citazioni e provenienza, senza documenti originali. L'inserimento e l'approvazione di una fonte non attestano ricerca empirica o validazione umana."
            if italian
            else "The Dossier preserves citations and provenance without original documents. Adding and approving a source does not establish empirical research or human validation.",
            "",
        ]
    )
    omitted = document.get("omitted_sections", ())
    if omitted:
        lines.extend(
            [
                "## Sezioni da rivedere e omesse"
                if italian
                else "## Omitted sections requiring review",
                "",
            ]
        )
        for section in omitted:
            codes = section.get("affected_codes", {})
            listed = "; ".join(
                f"{key}: {', '.join(values) or '-'}" for key, values in codes.items()
            )
            lines.append(f"- {section['stage']}: {section['reason']} · {listed}")
        lines.append("")
    citations = document.get("citations", ())
    for source in document.get("evidence", ()):
        lines.extend([f"## {source['code']} v{source['version']} — {source['title']}", ""])
        for key, it, en in (
            ("status", "Stato", "Status"),
            ("source_kind", "Tipo di fonte", "Source kind"),
            ("source_ref", "Origine", "Origin"),
            ("context", "Contesto", "Context"),
            ("method", "Metodo", "Method"),
            ("collected_at", "Data o periodo", "Date or period"),
            ("limitations", "Limiti", "Limitations"),
            ("content_hash", "Hash del testo", "Text hash"),
        ):
            lines.append(f"- {it if italian else en}: {source.get(key) or '-'}")
        nature = "ricerca empirica dichiarata" if italian else "declared empirical research"
        if not source.get("empirical"):
            nature = "non empirica" if italian else "nonempirical"
        lines.extend([f"- {nature}", ""])
        for entry in citations:
            citation = entry["citation"]
            if (
                citation["source_id"] != source["id"]
                or citation["source_version"] != source["version"]
            ):
                continue
            lines.append(
                f"{entry['twin_id']} v{entry['twin_version']} · {entry['field']} · {entry['effect']} · {entry['status']} · L{citation['start_line']}-L{citation['end_line']} · [{citation['start']},{citation['end']})"
            )
            lines.extend(["", *(f"> {line}" for line in citation["quote"].split("\n")), ""])
    return "\n".join(lines) + "\n"
