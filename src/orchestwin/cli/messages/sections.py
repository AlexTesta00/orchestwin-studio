from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "sections.archetypes_behind": {
        "it": "{sections} da aggiornare: gli archetipi sono cambiati. Prepara i twin nuovi e approvali con `ut init`, poi aggiorna le sezioni.",
        "en": "{sections} to update: the archetypes changed. Prepare the new twins and approve them with `ut init`, then update the sections.",
    },
    "sections.reason_prepare_twins": {
        "it": "gli archetipi sono cambiati: prepara e approva i twin aggiornati; lo storico resta disponibile",
        "en": "the archetypes changed: prepare and approve the updated twins; the history remains available",
    },
    "sections.help": {
        "it": "Mostra lo stato delle sezioni del progetto e aggiorna quelle rimaste indietro",
        "en": "Show the state of the sections of the project and update the ones left behind",
    },
    "sections.option_json": {
        "it": "stampa l'oggetto delle sezioni come lo dà lo Studio, per altri programmi",
        "en": "print the object of the sections as the Studio gives it, for other programs",
    },
    "sections.option_action": {
        "it": "che cosa fare: update; senza azione mostra le sezioni",
        "en": "what to do: update; without an action the sections are shown",
    },
    "sections.help_update": {
        "it": "riaggancia alle versioni nuove le sezioni da aggiornare, con i contenuti "
        "invariati, e le conferma; con `ut --yes sections update` non chiede conferma",
        "en": "re-anchor the sections to update to the new versions, with their content "
        "unchanged, and confirm them; `ut --yes sections update` does not ask",
    },
    "sections.column_section": {"it": "Sezione", "en": "Section"},
    "sections.state_not_started": {"it": "In attesa", "en": "Waiting"},
    "sections.state_in_progress": {"it": "Tocca a te", "en": "Your turn"},
    "sections.state_fine": {"it": "A posto", "en": "Up to date"},
    "sections.state_update_available": {
        "it": "Aggiornamento disponibile",
        "en": "Update available",
    },
    "sections.state_to_update": {"it": "Da aggiornare", "en": "To update"},
    "sections.version": {"it": "v{number}", "en": "v{number}"},
    "sections.behind": {
        "it": "{sections} da aggiornare: a monte qualcosa è cambiato. I contenuti che hai "
        "approvato restano gli stessi, vengono solo riagganciati alle versioni nuove.",
        "en": "{sections} to update: something upstream changed. The content you approved "
        "stays the same, it is only re-anchored to the new versions.",
    },
    "sections.behind_command": {
        "it": "Aggiorna e conferma con `ut sections update`.",
        "en": "Update and confirm with `ut sections update`.",
    },
    "sections.uncovered": {
        "it": "Requisiti nuovi che il design non copre ancora: {codes}. Dopo l'aggiornamento "
        "puoi chiedere una modifica al design con `ut design change`.",
        "en": "New requirements that the design does not cover yet: {codes}. After the update "
        "you can ask for a change to the design with `ut design change`.",
    },
    "sections.not_covered": {
        "it": "Requisiti che il design non copre ancora: {codes}. Puoi chiedere una modifica al "
        "design con `ut design change`.",
        "en": "Requirements that the design does not cover yet: {codes}. You can ask for a "
        "change to the design with `ut design change`.",
    },
    "sections.blocked": {
        "it": "{section} non si aggiorna da sola: {reason}.",
        "en": "{section} cannot be updated by itself: {reason}.",
    },
    "sections.reason_requirement_no_longer_available": {
        "it": "il design cita {codes}, che la Definizione non contiene più: rigenera le "
        "alternative nel passo Design e valutazione del web",
        "en": "the design cites {codes}, which the Definition no longer contains: regenerate the "
        "alternatives in the Design & Evaluation step of the web Studio",
    },
    "sections.reason_twin_set_changed": {
        "it": "i twin non sono più gli stessi",
        "en": "the twins are no longer the same",
    },
    "sections.reason_twin_no_longer_available": {
        "it": "i twin non sono più gli stessi",
        "en": "the twins are no longer the same",
    },
    "sections.reason_revision_pending": {
        "it": "c'è una modifica proposta da decidere",
        "en": "a proposed change is waiting for your decision",
    },
    "sections.reason_upstream_not_ready": {
        "it": "prima va sistemata la sezione a monte",
        "en": "the section upstream has to be settled first",
    },
    "sections.reason_prepare_again": {
        "it": "il brief è cambiato: prepara di nuovo le prospettive",
        "en": "the brief changed: prepare the perspectives again",
    },
    "sections.reason_other": {
        "it": "lo Studio ha risposto {code}",
        "en": "the Studio answered {code}",
    },
    "sections.solve_init": {"it": "Lancia `ut init`.", "en": "Launch `ut init`."},
    "sections.solve_design": {"it": "Lancia `ut design`.", "en": "Launch `ut design`."},
    "sections.solve_design_change": {
        "it": "Poi continua con `ut design`.",
        "en": "Then go on with `ut design`.",
    },
    "sections.solve_web": {
        "it": "Si sistema dallo Studio web.",
        "en": "It is settled in the web Studio.",
    },
    "sections.twins_learned": {
        "it": "I twin hanno imparato qualcosa durante lo sviluppo: guarda la proposta con "
        "`ut twins update`.",
        "en": "The twins learned something during development: see the proposal with "
        "`ut twins update`.",
    },
    "sections.evaluation_missing": {
        "it": "I twin non hanno ancora valutato questa versione del design: chiedi una "
        "valutazione con `ut design review`.",
        "en": "The twins have not evaluated this version of the design yet: ask for an "
        "evaluation with `ut design review`.",
    },
    "sections.evaluation_after": {
        "it": "Il design è stato riagganciato alla Definizione nuova: puoi chiedere ai twin una "
        "nuova valutazione con `ut design review`.",
        "en": "The design was re-anchored to the new Definition: you can ask the twins for a "
        "new evaluation with `ut design review`.",
    },
    "sections.dossier_behind": {
        "it": "Il Dossier non contiene ancora le ultime versioni approvate: pubblicalo con "
        "`ut package publish`.",
        "en": "The Dossier does not hold the latest approved versions yet: publish it with "
        "`ut package publish`.",
    },
    "sections.confirm": {
        "it": "Aggiorno e confermo queste sezioni?",
        "en": "Update and confirm these sections?",
    },
    "sections.cancelled": {
        "it": "Non ho aggiornato nulla.",
        "en": "Nothing was updated.",
    },
    "sections.nothing": {
        "it": "Nessuna sezione è da aggiornare: non è cambiato nulla.",
        "en": "No section needs an update: nothing changed.",
    },
    "sections.result_aligned": {
        "it": "{section}: aggiornata e confermata alla versione {version}.",
        "en": "{section}: updated and confirmed at version {version}.",
    },
    "sections.result_skipped": {
        "it": "{section}: lasciata com'era.",
        "en": "{section}: left as it was.",
    },
    "sections.done": {
        "it": "Sezioni aggiornate: {sections}.",
        "en": "Sections updated: {sections}.",
    },
    "sections.folder_updated": {
        "it": "Cartella di conoscenza aggiornata in {path}: versione {version}.",
        "en": "Knowledge folder updated in {path}: version {version}.",
    },
    "sections.folder_not_updated": {
        "it": "La cartella di conoscenza non è stata aggiornata ({code}): aggiornala più tardi "
        "con `ut package publish`.",
        "en": "The knowledge folder was not updated ({code}): update it later with "
        "`ut package publish`.",
    },
    "sections.folder_waits": {
        "it": "La cartella di conoscenza resta com'era: si aggiorna quando ogni sezione è a posto.",
        "en": "The knowledge folder stays as it was: it is updated once every section is up to "
        "date.",
    },
    "sections.errors.SECTIONS_UNSUPPORTED": {
        "it": "Lo Studio {studio} non dà ancora lo stato delle sezioni: è più vecchio di questa "
        "versione di ut. Aggiorna lo Studio; intanto `ut status` mostra i passi.",
        "en": "The Studio {studio} does not give the state of the sections yet: it is older "
        "than this version of ut. Update the Studio; meanwhile `ut status` shows the steps.",
    },
    "sections.errors.SECTIONS_JSON_ALONE": {
        "it": "--json vale solo per `ut sections`, non per `ut sections update`.",
        "en": "--json works only with `ut sections`, not with `ut sections update`.",
    },
}
