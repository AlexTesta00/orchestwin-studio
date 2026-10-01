from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "status.help": {
        "it": "Mostra a che punto è il progetto",
        "en": "Show where the project stands",
    },
    "status.option_offline": {
        "it": "legge solo la cartella, senza chiedere allo Studio",
        "en": "read only the folder, without asking the Studio",
    },
    "status.option_all": {
        "it": "elenca tutti i progetti del tuo account",
        "en": "list every project of your account",
    },
    "status.option_json": {
        "it": "stampa un solo documento JSON, per altri programmi",
        "en": "print a single JSON document, for other programs",
    },
    "status.studio": {"it": "Studio: {studio}", "en": "Studio: {studio}"},
    "status.mode": {"it": "Modalità: {mode}", "en": "Mode: {mode}"},
    "status.mode_design_only": {"it": "solo design", "en": "design only"},
    "status.mode_design_and_code": {"it": "design e codice", "en": "design and code"},
    "status.column_step": {"it": "Passo", "en": "Step"},
    "status.column_state": {"it": "Stato", "en": "State"},
    "status.column_version": {"it": "Versione", "en": "Version"},
    "status.state_approved": {"it": "approvato", "en": "approved"},
    "status.state_waiting": {"it": "da approvare", "en": "waiting for your approval"},
    "status.state_todo": {"it": "da fare", "en": "to do"},
    "status.state_later": {"it": "più avanti", "en": "later"},
    "status.state_ready": {"it": "pronto da scaricare", "en": "ready to download"},
    "status.next": {"it": "Prossimo passo: {action}", "en": "Next step: {action}"},
    "status.folder_both": {
        "it": "Cartella di conoscenza: versione {local} in questa cartella, versione {studio} "
        "nello Studio.",
        "en": "Knowledge folder: version {local} in this folder, version {studio} in the Studio.",
    },
    "status.folder_older": {
        "it": "La cartella qui è più vecchia: aggiornala con `ut package pull`.",
        "en": "The folder here is older: update it with `ut package pull`.",
    },
    "status.folder_only_studio": {
        "it": "Cartella di conoscenza: versione {studio} nello Studio, non ancora in questa "
        "cartella. Scaricala con `ut package pull`.",
        "en": "Knowledge folder: version {studio} in the Studio, not in this folder yet. "
        "Download it with `ut package pull`.",
    },
    "status.folder_only_local": {
        "it": "Cartella di conoscenza: versione {local} in questa cartella.",
        "en": "Knowledge folder: version {local} in this folder.",
    },
    "status.folder_none": {
        "it": "Cartella di conoscenza: non ancora pubblicata.",
        "en": "Knowledge folder: not published yet.",
    },
    "status.next_folder_current": {
        "it": "La cartella di conoscenza è aggiornata: lo sviluppo continua con questi comandi:",
        "en": "The knowledge folder is up to date: the development goes on with these commands:",
    },
    "status.alignment": {
        "it": "Sviluppo: commit registrati: {recorded}; dopo il punto allineato: {pending}; "
        "commit allineato: {commit}; compiti aperti per il codice: {tasks}.",
        "en": "Development: commits recorded: {recorded}; after the aligned point: {pending}; "
        "aligned commit: {commit}; open tasks for the code: {tasks}.",
    },
    "status.alignment_not_aligned": {
        "it": "Sviluppo: commit registrati: {recorded}; nessuno ancora allineato (in attesa: "
        "{pending}); compiti aperti per il codice: {tasks}.",
        "en": "Development: commits recorded: {recorded}; none aligned yet (waiting: {pending}); "
        "open tasks for the code: {tasks}.",
    },
    "status.alignment_none": {
        "it": "Sviluppo: nessun commit registrato finora. Dopo il primo commit lancia `ut align`.",
        "en": "Development: no commit recorded yet. After your first commit launch `ut align`.",
    },
    "status.stale_reviews": {
        "it": "Esami da rifare perché i requisiti o il design sono cambiati: {count} "
        "(`ut align --recheck`).",
        "en": "Reviews to do again because the requirements or the design changed: {count} "
        "(`ut align --recheck`).",
    },
    "status.learning": {
        "it": "Cosa hanno imparato i twin durante lo sviluppo: {twins}.",
        "en": "What the twins learned during the development: {twins}.",
    },
    "status.learning_twin": {
        "it": "{name} (versione {label}, osservazioni: {count})",
        "en": "{name} (version {label}, observations: {count})",
    },
    "status.tests": {
        "it": "Verifica dei criteri: ultima esecuzione il {date}: {passed} superati, {failed} "
        "falliti, {blocked} bloccati, {not_covered} non coperti.",
        "en": "Acceptance tests: latest run on {date}: {passed} passed, {failed} failed, "
        "{blocked} blocked, {not_covered} not covered.",
    },
    "status.folder_unreadable": {
        "it": "La cartella di conoscenza qui non si legge ({code}): controllala con "
        "`ut package verify`.",
        "en": "The knowledge folder here cannot be read ({code}): check it with "
        "`ut package verify`.",
    },
    "status.spending": {
        "it": "Spesa del progetto: {spent} USD. Credito rimasto nello Studio: {remaining} USD.",
        "en": "Spent on this project: {spent} USD. Credit left in the Studio: {remaining} USD.",
    },
    "status.spending_no_credit": {
        "it": "Spesa del progetto: {spent} USD.",
        "en": "Spent on this project: {spent} USD.",
    },
    "status.credit_only": {
        "it": "Credito rimasto nello Studio: {remaining} USD.",
        "en": "Credit left in the Studio: {remaining} USD.",
    },
    "status.subscription": {
        "it": "Le generazioni usano l'abbonamento di Claude: nessun credito speso.",
        "en": "Generations run on the Claude subscription: no credit is spent.",
    },
    "status.offline_requested": {
        "it": "Stato letto da questa cartella, come chiesto con --offline.",
        "en": "State read from this folder, as asked with --offline.",
    },
    "status.offline_unreachable": {
        "it": "Stato letto da questa cartella: lo Studio {studio} non risponde.",
        "en": "State read from this folder: the Studio {studio} does not answer.",
    },
    "status.offline_not_signed_in": {
        "it": "Stato letto da questa cartella: non hai eseguito l'accesso allo Studio "
        "{studio} (`ut login`).",
        "en": "State read from this folder: you are not signed in to the Studio {studio} "
        "(`ut login`).",
    },
    "status.offline_session_expired": {
        "it": "Stato letto da questa cartella: l'accesso allo Studio {studio} è scaduto "
        "(`ut login`).",
        "en": "State read from this folder: your sign-in to the Studio {studio} has expired "
        "(`ut login`).",
    },
    "status.offline_project_missing": {
        "it": "Stato letto da questa cartella: lo Studio {studio} non trova questo progetto "
        "per il tuo account.",
        "en": "State read from this folder: the Studio {studio} does not find this project "
        "for your account.",
    },
    "status.projects_heading": {
        "it": "Progetti nello Studio {studio}",
        "en": "Projects in the Studio {studio}",
    },
    "status.no_projects": {
        "it": "Il tuo account non ha ancora progetti. Creane uno con `ut init`.",
        "en": "Your account has no project yet. Create one with `ut init`.",
    },
    "status.column_project": {"it": "Progetto", "en": "Project"},
    "status.column_turn": {"it": "Tocca a te", "en": "Your turn"},
    "status.step_position": {
        "it": "{number} di {total}: {stage}",
        "en": "{number} of {total}: {stage}",
    },
    "status.this_folder": {"it": "{name} (questa cartella)", "en": "{name} (this folder)"},
}
