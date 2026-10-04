from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "activity.help": {
        "it": "Mostra i tempi e i passi del progetto e avvia o ferma una sessione di prova",
        "en": "Show the times and the steps of the project and start or stop a study session",
    },
    "activity.option_action": {
        "it": "start avvia una sessione di prova con il codice, stop la ferma; senza azione "
        "mostra i tempi",
        "en": "start begins a study session with the code, stop ends it; without an action "
        "the times are shown",
    },
    "activity.option_code": {
        "it": "codice della sessione, come SES-P01, senza nomi",
        "en": "code of the session, such as SES-P01, without names",
    },
    "activity.option_json": {
        "it": "stampa il documento dei tempi come lo dà lo Studio, per altri programmi",
        "en": "print the document of the times as the Studio gives it, for other programs",
    },
    "activity.option_csv": {
        "it": "scrive gli eventi nel file CSV indicato",
        "en": "write the events to the given CSV file",
    },
    "activity.column_first": {"it": "Inizio", "en": "Start"},
    "activity.column_approved": {"it": "Approvata", "en": "Approved"},
    "activity.column_elapsed": {"it": "Tempo", "en": "Time"},
    "activity.column_owner": {"it": "Gesti", "en": "Actions"},
    "activity.column_generations": {"it": "Gener.", "en": "Gener."},
    "activity.column_wait": {"it": "Attesa", "en": "Wait"},
    "activity.column_retries": {"it": "Ritentate", "en": "Retried"},
    "activity.utc": {"it": "Orari in UTC.", "en": "Times are in UTC."},
    "activity.brief_dialogue": {
        "it": "Dialogo del brief: {questions} domande, {answered} risposte ({unknown} «non lo "
        "so»), tempo medio di risposta {average}.",
        "en": "Dialogue of the brief: {questions} questions, {answered} answers ({unknown} "
        "“I do not know”), average answer time {average}.",
    },
    "activity.session": {
        "it": "Sessione di prova {code}: dal {started} al {ended} UTC, {events} eventi "
        "({sources}), {discarded} intervalli scartati.",
        "en": "Study session {code}: from {started} to {ended} UTC, {events} events "
        "({sources}), {discarded} intervals discarded.",
    },
    "activity.session_open": {
        "it": "Sessione di prova {code}: in corso dal {started} UTC, {events} eventi "
        "({sources}), {discarded} intervalli scartati.",
        "en": "Study session {code}: running since {started} UTC, {events} events "
        "({sources}), {discarded} intervals discarded.",
    },
    "activity.limits": {
        "it": "Limiti della misura: i tempi comprendono le pause e le aperture si registrano "
        "solo durante le sessioni di prova ({codes}).",
        "en": "Limits of the measure: the times include the pauses and the openings are "
        "recorded only during study sessions ({codes}).",
    },
    "activity.csv_written": {
        "it": "Ho scritto {count} righe di eventi in {path}.",
        "en": "Wrote {count} rows of events to {path}.",
    },
    "activity.started": {
        "it": "Sessione di prova {code} avviata: da ora ut registra quali comandi lanci in "
        "questa cartella e quanto durano, senza argomenti né contenuti del progetto. Fermala "
        "con `ut activity stop`.",
        "en": "Study session {code} started: from now on ut records which commands you launch "
        "in this folder and how long they take, without arguments or project content. Stop "
        "it with `ut activity stop`.",
    },
    "activity.stopped": {
        "it": "Sessione di prova {code} fermata: ut non registra più i comandi.",
        "en": "Study session {code} stopped: ut no longer records the commands.",
    },
    "activity.errors.ACTIVITY_OPTIONS_INVALID": {
        "it": "Usa `ut activity` (anche con --json oppure --csv FILE), `ut activity start "
        "CODICE` oppure `ut activity stop`.",
        "en": "Use `ut activity` (also with --json or --csv FILE), `ut activity start CODE` "
        "or `ut activity stop`.",
    },
    "activity.errors.ACTIVITY_CSV_NOT_WRITTEN": {
        "it": "Il file {path} non si può scrivere: controlla la cartella e riprova.",
        "en": "The file {path} cannot be written: check the folder and try again.",
    },
    "activity.errors.PROJECT_NOT_FOUND": {
        "it": "Lo Studio non trova questo progetto per il tuo account, quindi non ne mostra né "
        "registra i tempi.",
        "en": "The Studio does not find this project for your account, so it neither shows nor "
        "records its times.",
    },
    "activity.errors.ACTIVITY_INPUT_INVALID": {
        "it": "Il codice non è valido. Usa un codice come SES-P01, senza nomi.",
        "en": "The code is not valid. Use a code such as SES-P01, without names.",
    },
    "activity.errors.ACTIVITY_SESSION_ACTIVE": {
        "it": "Una sessione di prova è già attiva. Fermala con `ut activity stop`.",
        "en": "A study session is already active. Stop it with `ut activity stop`.",
    },
    "activity.errors.ACTIVITY_SESSION_CODE_USED": {
        "it": "Questo codice è già stato usato in questo progetto.",
        "en": "This code was already used in this project.",
    },
    "activity.errors.ACTIVITY_SESSION_NOT_ACTIVE": {
        "it": "Non c'è una sessione di prova attiva da fermare.",
        "en": "There is no active study session to stop.",
    },
    "activity.errors.ACTIVITY_JOURNAL_FULL": {
        "it": "Il registro dei tempi di questo progetto è pieno.",
        "en": "The journal of the times of this project is full.",
    },
    "activity.errors.ACTIVITY_RECORDS_INVALID": {
        "it": "Lo Studio non riesce a ricostruire i tempi di questo progetto dai suoi dati.",
        "en": "The Studio cannot rebuild the times of this project from its records.",
    },
    "activity.errors.ACTIVITY_SERVICE_UNAVAILABLE": {
        "it": "Questo Studio non offre ancora i tempi e i passi del progetto.",
        "en": "This Studio does not offer the times and the steps of the project yet.",
    },
}
