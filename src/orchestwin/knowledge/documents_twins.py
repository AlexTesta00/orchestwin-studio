from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from orchestwin.knowledge.documents_markdown import (
    UNSET,
    _version_lines,
    markdown_bullets,
    markdown_table,
    plain_text,
    title_text,
)
from orchestwin.knowledge.layout import STAGE_LABELS, twin_slug, twin_text
from orchestwin.twins.persistence.snapshots import (
    persona_version_from_snapshot,
    user_twin_version_from_snapshot,
)
from orchestwin.twins.representation import twin_view
from orchestwin.twins.user_twins import UserModelingSnapshotVersion
from orchestwin.workflow.gates import HumanGate


def _observation_value(value: Mapping[str, object]) -> str:
    text = value.get("text")
    if isinstance(text, str) and text.strip():
        return text
    items = value.get("items")
    if isinstance(items, Sequence) and items:
        return "; ".join(plain_text(item) for item in items)
    reason = value.get("reason")
    return f"unknown ({reason})" if reason else UNSET


def observation_table(observations: Iterable[Mapping[str, object]]) -> list[str]:
    rows = [
        (
            item["observation_key"],
            _observation_value(item["value"]),
            item["epistemic_status"],
            item["confidence"],
            item["human_validation"],
        )
        for item in observations
    ]
    return markdown_table(
        ("Observation", "Value", "Epistemic status", "Confidence", "Validation"), rows
    )


def _persona_names(snapshot: Mapping[str, object]) -> dict[tuple[str, object], str]:
    return {
        (str(persona["persona_id"]), persona["version_number"]): str(persona["profile"]["name"])
        for persona in snapshot["persona_versions"]
    }


def twins_markdown(
    version: UserModelingSnapshotVersion, gate: HumanGate, *, language: str | None = None
) -> str:
    snapshot = version.snapshot.to_snapshot()
    personas = _persona_names(snapshot)
    lines = _version_lines(STAGE_LABELS["twins"], version, gate)
    lines.extend(["## Archetipi" if language == "it" else "## Archetypes", ""])
    for persona in snapshot["persona_versions"]:
        profile = persona["profile"]
        lines.extend(
            [
                f"### {profile['name']}",
                "",
                f"Source {title_text(profile['source'])}, {title_text(profile['kind'])}, "
                f"{title_text(profile['confirmation_status'])}, "
                f"version {persona['version_number']}.",
                "",
                *markdown_bullets(
                    _observation_value(item["value"])
                    for item in profile["observations"]
                    if item["observation_key"] == "persona.summary"
                ),
                "",
            ]
        )
    lines.extend(["## User twins", ""])
    for twin in snapshot["twin_versions"]:
        profile = twin["profile"]
        reference = profile["persona_reference"]
        persona = personas.get((str(reference["persona_id"]), reference["version_number"]), UNSET)
        exact = next(
            item
            for item in snapshot["persona_versions"]
            if item["persona_id"] == reference["persona_id"]
            and item["content_hash"] == reference["content_hash"]
        )
        view = twin_view(
            user_twin_version_from_snapshot(twin), persona_version_from_snapshot(exact)
        )
        texts = _twin_texts(language)
        path = twin_text(twin_slug(profile["name"], twin["twin_id"])).removeprefix("twins/")
        lines.extend(
            [
                f"### {profile['name']}",
                "",
                f"Version {twin['version_number']}, "
                f"validation status {profile['validation_status']}, human validation "
                f"{'required' if profile['requires_human_validation'] else 'not required'}, "
                f"{texts['archetype']} {persona} (v{reference['version_number']}).",
                "",
                f"{texts['basis']}: {texts[view['basis']]}. "
                + _observation_value(view["persona"]["description"]["value"]),
                texts["provisional"] if view["basis"] == "PROVISIONAL" else "",
                f"[{texts['persona']} · {texts['why']}]({path})",
                "",
            ]
        )
    return "\n".join(lines)


def _twin_texts(language: str | None) -> dict[str, str]:
    labels = {
        "archetype": ("Archetipo", "Archetype"),
        "persona": ("Persona", "Persona"),
        "basis": ("Fondamento", "Basis"),
        "PROVISIONAL": ("Provvisorio", "Provisional"),
        "EVIDENCE_BASED": ("Fondato su evidenze", "Evidence based"),
        "represents": ("Rappresenta", "Represents"),
        "does_not_represent": ("Non rappresenta", "Does not represent"),
        "contexts": ("Contesti coperti", "Covered contexts"),
        "persona_contexts": ("Contesti", "Contexts"),
        "evidence_gaps": ("Limiti delle evidenze", "Evidence gaps"),
        "description": ("Descrizione", "Description"),
        "goals": ("Obiettivi", "Goals"),
        "needs": ("Bisogni", "Needs"),
        "behaviours": ("Comportamenti", "Behaviours"),
        "pain_points": ("Difficoltà", "Pain points"),
        "constraints": ("Vincoli", "Constraints"),
        "EVIDENCED": ("Documentato", "Evidenced"),
        "INFERRED": ("Dedotto", "Inferred"),
        "HYPOTHESIZED": ("Ipotizzato", "Hypothesized"),
        "CONTESTED": ("Contestato", "Contested"),
        "UNKNOWN": ("Sconosciuto", "Unknown"),
        "why": ("Perché?", "Why?"),
        "missing_rationale": ("Motivazione non fornita.", "Rationale not provided."),
        "missing_sources": ("Fonti non fornite.", "Sources not provided."),
        "provisional": (
            "Il brief e le scelte del proprietario non sono evidenze su utenti reali.",
            "The brief and the owner's choices are not evidence about real users.",
        ),
    }
    return {key: value[0 if language == "it" else 1] for key, value in labels.items()}


def _claim_lines(label: str, claim: Mapping[str, object], texts: Mapping[str, str]) -> list[str]:
    value = claim["value"]
    shown = (
        texts["UNKNOWN"] if value["kind"] in {"UNKNOWN", "ABSTAINED"} else _observation_value(value)
    )
    sources = claim["provenance"]
    return [
        f"- **{label}**: {shown} [{texts[claim['display_status']]}]",
        "",
        f"<details><summary>{texts['why']} · {label}</summary>",
        "",
        str(claim["rationale"] or texts["missing_rationale"]),
        "",
        *(
            markdown_bullets(
                " · ".join(
                    str(source[key])
                    for key in (
                        "source_kind",
                        "source_id",
                        "source_version",
                        "content_hash",
                        "locator",
                        "summary",
                    )
                    if source.get(key) is not None
                )
                for source in sources
            )
            if sources
            else [texts["missing_sources"]]
        ),
        "",
        "</details>",
        "",
    ]


def twin_markdown(document: Mapping[str, object], *, language: str | None = None) -> str:
    origin = document["origin"]
    persona = document["persona"]
    twin = document["twin"]
    profile = twin["profile"]
    persona_profile = persona["profile"]
    modeling = origin["user_modeling"]
    view = twin_view(user_twin_version_from_snapshot(twin), persona_version_from_snapshot(persona))
    texts = _twin_texts(language)
    lines = [
        f"# {profile['name']}",
        "",
        (
            f"User twin version {twin['version_number']}, content hash "
            f"`{twin['content_hash']}`, of the project {origin['project_name']}. "
            f"Validation status {profile['validation_status']}, human "
            f"validation {'required' if profile['requires_human_validation'] else 'not required'}. "
            f"Approved with user modeling version {modeling['version_number']} on "
            f"{origin['approved_at']}."
            if language != "it"
            else f"User Twin versione {twin['version_number']}, hash del contenuto "
            f"`{twin['content_hash']}`, del progetto {origin['project_name']}. "
            f"Stato di validazione {profile['validation_status']}, validazione umana "
            f"{'richiesta' if profile['requires_human_validation'] else 'non richiesta'}. "
            f"Approvato con il modello utenti versione {modeling['version_number']} il "
            f"{origin['approved_at']}."
        ),
        "",
        (
            "A user twin is a model of a kind of user, not a person: its observations are "
            "assumptions with a declared epistemic status and confidence. `twin.json` next to this "
            "document is a self-contained copy that another OrchesTwin project can import."
            if language != "it"
            else "Uno User Twin è un modello di un tipo di utente, non una persona: le sue "
            "osservazioni sono ipotesi con stato epistemico e confidenza dichiarati. "
            "`twin.json` accanto a questo documento è una copia autonoma che un altro "
            "progetto OrchesTwin può importare."
        ),
        "",
        f"## {texts['archetype']}",
        "",
        f"{persona_profile['name']}: {'fonte' if language == 'it' else 'source'} "
        f"{title_text(persona_profile['source'])}, "
        f"{title_text(persona_profile['kind'])}, "
        f"{title_text(persona_profile['confirmation_status'])}, "
        f"{'versione' if language == 'it' else 'version'} "
        f"{persona['version_number']}.",
        "",
        f"{texts['basis']}: **{texts[view['basis']]}**.",
        texts["provisional"] if view["basis"] == "PROVISIONAL" else "",
        "",
    ]
    for field in ("represents", "does_not_represent", "contexts", "evidence_gaps"):
        lines.extend(_claim_lines(texts[field], view[field], texts))
    lines.extend(
        [f"## {texts['persona']}", "", f"<details><summary>{texts['persona']}</summary>", ""]
    )
    for field, claim in view["persona"].items():
        lines.extend(
            _claim_lines(texts["persona_contexts" if field == "contexts" else field], claim, texts)
        )
    lines.extend(
        [
            "</details>",
            "",
            f"<details><summary>{'Profilo' if language == 'it' else 'Profile'} · JSON</summary>",
            "",
            "## Profilo" if language == "it" else "## Profile",
            "",
            *observation_table(profile["observations"]),
            "",
            "[JSON](twin.json)",
            "",
            "</details>",
            "",
        ]
    )
    return "\n".join(lines)
