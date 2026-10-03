from __future__ import annotations

MESSAGES = {
    "validation.help": {
        "it": "Legge candidate, ipotesi operative, esiti e percorsi degli scenari.",
        "en": "Read candidates, operational hypotheses, outcomes and scenario walkthroughs.",
    },
    "validation.option_action": {
        "it": "Percorso dello scenario a richiesta.",
        "en": "Scenario walkthrough on request.",
    },
    "validation.option_scenario": {"it": "Key esatta dello scenario.", "en": "Exact scenario key."},
    "validation.option_alternative": {
        "it": "Identificatore dell'alternativa.",
        "en": "Alternative identifier.",
    },
    "validation.option_document_hash": {
        "it": "Hash del documento mockup.",
        "en": "Mockup document hash.",
    },
    "validation.option_all": {
        "it": "Mostra tutti i dettagli e i riferimenti storici.",
        "en": "Show all details and historical references.",
    },
    "validation.option_json": {
        "it": "Restituisce la risposta completa in JSON.",
        "en": "Return the complete answer as JSON.",
    },
    "validation.option_offline": {
        "it": "Legge il Dossier verificato senza rete o login.",
        "en": "Read the verified Dossier without network or login.",
    },
    "validation.offline": {
        "it": "Dossier locale verificato ({reason}); i dati possono essere precedenti a Studio.",
        "en": "Verified local Dossier ({reason}); its data may predate Studio.",
    },
    "validation.candidates": {
        "it": "Candidate da verificare ({count})",
        "en": "Candidates to verify ({count})",
    },
    "validation.more": {
        "it": "  Usa --all per i dettagli delle {count} candidate.",
        "en": "  Use --all for details of the {count} candidates.",
    },
    "validation.hypotheses": {
        "it": "Ipotesi operative ({count})",
        "en": "Operational hypotheses ({count})",
    },
    "validation.outcomes": {"it": "Esiti ({count})", "en": "Outcomes ({count})"},
    "validation.walkthrough": {
        "it": "Percorso dello scenario: {title}",
        "en": "Scenario walkthrough: {title}",
    },
    "validation.task": {"it": "Domanda o compito: {value}", "en": "Question or task: {value}"},
    "validation.anchor_candidates": {
        "it": "Elementi pertinenti allo scenario ({count})",
        "en": "Elements relevant to the scenario ({count})",
    },
    "validation.state.TO_VERIFY": {"it": "Da verificare", "en": "To verify"},
    "validation.state.CONFIRMED": {"it": "Confermata", "en": "Confirmed"},
    "validation.state.REFUTED": {"it": "Smentita", "en": "Refuted"},
    "validation.state.UNCERTAIN": {"it": "Incerta", "en": "Uncertain"},
    "validation.state.CONTESTED": {"it": "Esiti in disaccordo", "en": "Conflicting outcomes"},
    "validation.partial": {"it": "Evidenza parziale", "en": "Partial evidence"},
    "validation.retired": {"it": "Esito ritirato", "en": "Retired outcome"},
    "validation.previous": {"it": "Versione precedente", "en": "Previous version"},
    "validation.session.HUMAN_SESSION": {"it": "Sessione con persone", "en": "Session with people"},
    "validation.session.SYNTHETIC_EXERCISE": {
        "it": "Prova sintetica, non empirica",
        "en": "Synthetic exercise, not empirical",
    },
    "validation.synthetic_limit": {
        "it": "La navigazione software non è un'osservazione con persone.",
        "en": "Software navigation is not an observation with people.",
    },
    "validation.no_promotion": {
        "it": "Gli esiti non promuovono automaticamente i claim del twin.",
        "en": "Outcomes do not automatically promote twin claims.",
    },
    "validation.omitted": {
        "it": "Omissione nel Dossier: {value}",
        "en": "Dossier omission: {value}",
    },
    "validation.gap.STEP_ANCHOR_NOT_ATTESTED": {
        "it": "Collegamento da completare",
        "en": "Link to complete",
    },
    "validation.gap.SOURCE_TEXT_UNAVAILABLE": {
        "it": "Fonte senza testo originale",
        "en": "Source without original text",
    },
    "validation.gap.MISSING_SOURCE_VERSION": {
        "it": "Manca la versione esatta della fonte.",
        "en": "The exact source version is missing.",
    },
    "validation.errors.VALIDATION_INPUT_INVALID": {
        "it": "Usa ut validation oppure ut validation walkthrough SCENARIO.",
        "en": "Use ut validation or ut validation walkthrough SCENARIO.",
    },
    "validation.errors.VALIDATION_CONTEXT_CHANGED": {
        "it": "Scenario non disponibile nel contesto verificato.",
        "en": "Scenario unavailable in the verified context.",
    },
}
