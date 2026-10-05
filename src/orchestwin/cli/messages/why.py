from __future__ import annotations

MESSAGES = {
    "why.origin.OWNER_INPUT": {"it": "Fornito dal proprietario", "en": "Owner supplied"},
    "why.gap.DECLARED_MISSING": {
        "it": "Manca, dichiarato da te.",
        "en": "Missing, declared by you.",
    },
    "why.help": {
        "it": "Mostra perché esiste un artefatto e che cosa ne dipende.",
        "en": "Show why an artifact exists and what depends on it.",
    },
    "why.option_code": {
        "it": "Codice o selettore univoco dell'artefatto.",
        "en": "Artifact code or unique selector.",
    },
    "why.option_all": {
        "it": "Mostra citazioni, versioni, hash e collegamenti.",
        "en": "Show citations, versions, hashes and links.",
    },
    "why.option_json": {
        "it": "Restituisce la risposta completa in JSON.",
        "en": "Return the complete answer as JSON.",
    },
    "why.option_offline": {
        "it": "Legge il Dossier locale verificato senza rete né accesso allo Studio.",
        "en": "Read the verified local Dossier without network or login.",
    },
    "why.target": {"it": "Perché? {title}", "en": "Why? {title}"},
    "why.completeness": {
        "it": "Arriva al twin: {twin} · evidenza attiva: {evidence} · tutti i rami completi: {branches}",
        "en": "Reaches twin: {twin} · active evidence: {evidence} · all branches complete: {branches}",
    },
    "why.boolean.true": {"it": "sì", "en": "yes"},
    "why.boolean.false": {"it": "no", "en": "no"},
    "why.limits": {"it": "Limiti ({count})", "en": "Limits ({count})"},
    "why.version": {"it": "versione {version}", "en": "version {version}"},
    "why.more": {
        "it": "  Altri {count}; usa --all per i dettagli.",
        "en": "  {count} more; use --all for details.",
    },
    "why.origin.MODEL": {
        "it": "Motivazione generata dal modello",
        "en": "Model-generated rationale",
    },
    "why.origin.OWNER": {"it": "Motivazione del proprietario", "en": "Owner rationale"},
    "why.origin.SYSTEM": {"it": "Motivazione del sistema", "en": "System rationale"},
    "why.origin.UNKNOWN": {"it": "Origine non dichiarata", "en": "Undeclared origin"},
    "why.offline": {
        "it": "Dossier locale verificato ({reason}); i dati possono essere precedenti a Studio.",
        "en": "Verified local Dossier ({reason}); its data may predate Studio.",
    },
    "why.upstream": {"it": "Da dove viene ({count})", "en": "Where it comes from ({count})"},
    "why.downstream": {"it": "Che cosa ne dipende ({count})", "en": "What depends on it ({count})"},
    "why.human_validation": {
        "it": "Da verificare con persone vere ({count})",
        "en": "To verify with real people ({count})",
    },
    "why.context": {"it": "Contesto dichiarato", "en": "Declared context"},
    "why.direction": {"it": "Direzione visiva: {name}", "en": "Visual direction: {name}"},
    "why.direction_axis": {"it": "{axis}: {value}", "en": "{axis}: {value}"},
    "why.direction_origin": {
        "it": "Proposta dal modello fra {count} candidate; scelta dallo Studio perché lontana "
        "dall'altra.",
        "en": "Proposed by the model among {count} candidates; chosen by the Studio because it "
        "is far from the other.",
    },
    "why.limit.LEGACY_DOSSIER": {
        "it": "Dossier precedente: catena ricalcolata dai soli dati disponibili.",
        "en": "Legacy Dossier: chain rebuilt from the available data.",
    },
    "why.limit.LEGACY_FEEDBACK_CONTEXT_MISSING": {
        "it": "Il Dossier non include i dati di origine del feedback sintetico.",
        "en": "The Dossier omits the source data for synthetic feedback.",
    },
    "why.interrupted": {
        "it": "Catena interrotta: {count} lacune.",
        "en": "Interrupted chain: {count} gaps.",
    },
    "why.model_rationale": {
        "it": "Motivazione generata dal modello",
        "en": "Model-generated rationale",
    },
    "why.status.EVIDENCED": {"it": "Documentato", "en": "Evidenced"},
    "why.status.INFERRED": {"it": "Dedotto", "en": "Inferred"},
    "why.status.HYPOTHESIZED": {"it": "Ipotizzato", "en": "Hypothesized"},
    "why.status.CONTESTED": {"it": "Contestato", "en": "Contested"},
    "why.status.UNKNOWN": {"it": "Sconosciuto", "en": "Unknown"},
    "why.errors.WHY_CODE_NOT_FOUND": {
        "it": "Artefatto non trovato nel contesto disponibile.",
        "en": "Artifact not found in the available context.",
    },
    "why.errors.WHY_CODE_AMBIGUOUS": {
        "it": "Codice ambiguo. Usa uno dei selettori: {candidates}.",
        "en": "Ambiguous code. Use one of these selectors: {candidates}.",
    },
    "why.errors.WHY_CODE_INVALID": {
        "it": "Codice artefatto non valido.",
        "en": "Invalid artifact code.",
    },
    "why.gap.MISSING_NEED": {
        "it": "Manca un bisogno collegato.",
        "en": "A linked need is missing.",
    },
    "why.gap.MISSING_SCENARIO": {
        "it": "Manca uno scenario collegato.",
        "en": "A linked scenario is missing.",
    },
    "why.gap.MISSING_TWIN": {
        "it": "Manca il twin collegato.",
        "en": "The linked twin is missing.",
    },
    "why.gap.MISSING_CLAIM": {
        "it": "Manca il claim collegato.",
        "en": "The linked claim is missing.",
    },
    "why.gap.MISSING_SOURCE": {
        "it": "Manca la fonte collegata.",
        "en": "The linked source is missing.",
    },
    "why.gap.MISSING_SOURCE_VERSION": {
        "it": "Manca la versione esatta della fonte.",
        "en": "The exact source version is missing.",
    },
    "why.gap.MISSING_RATIONALE": {
        "it": "Manca una motivazione dichiarata.",
        "en": "A declared rationale is missing.",
    },
    "why.gap.SOURCE_RETIRED": {
        "it": "Fonte ritirata: il riferimento resta storico.",
        "en": "Retired source: the reference remains historical.",
    },
    "why.gap.SOURCE_TEXT_UNAVAILABLE": {
        "it": "Testo originale non disponibile; resta la citazione.",
        "en": "Original text unavailable; the quotation remains.",
    },
    "why.gap.OMITTED_SECTION": {
        "it": "Sezione omessa dal Dossier.",
        "en": "Section omitted from the Dossier.",
    },
    "why.gap.CONTEXT_OUTDATED": {
        "it": "Il contesto citato precede quello corrente.",
        "en": "The cited context predates the current one.",
    },
}
