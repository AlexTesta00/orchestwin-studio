from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "common.description": {
        "it": "ut esegue i passi di OrchesTwin Studio dalla cartella di un progetto.",
        "en": "ut performs the steps of OrchesTwin Studio from the folder of a project.",
    },
    "common.commands_title": {"it": "comandi", "en": "commands"},
    "common.option_help": {"it": "mostra questo aiuto ed esce", "en": "show this help and exit"},
    "common.option_version": {
        "it": "mostra la versione di ut ed esce",
        "en": "show the version of ut and exit",
    },
    "common.option_lang": {
        "it": "lingua dei messaggi: it oppure en",
        "en": "language of the messages: it or en",
    },
    "common.option_no_color": {"it": "non usa i colori", "en": "do not use colours"},
    "common.option_yes": {
        "it": "conferma le spese stimate senza chiedere",
        "en": "confirm the estimated spending without asking",
    },
    "common.option_project_dir": {
        "it": "cartella del progetto, quando non è quella in cui ti trovi",
        "en": "folder of the project, when it is not the one you are in",
    },
    "common.option_debug": {
        "it": "in caso di errore mostra tutti i dettagli tecnici",
        "en": "show every technical detail when an error happens",
    },
    "common.missing_command": {
        "it": "Scegli un comando, per esempio `ut status`.",
        "en": "Choose a command, for example `ut status`.",
    },
    "common.not_available": {
        "it": "Questo comando non è ancora disponibile in questa versione di ut.",
        "en": "This command is not available yet in this version of ut.",
    },
    "common.interrupted": {"it": "Interrotto.", "en": "Interrupted."},
    "common.yes_no_default_yes": {"it": "[S/n]", "en": "[Y/n]"},
    "common.yes_no_default_no": {"it": "[s/N]", "en": "[y/N]"},
    "common.answer_yes_no": {
        "it": "Rispondi s per sì oppure n per no.",
        "en": "Answer y for yes or n for no.",
    },
    "common.answer_required": {
        "it": "Serve una risposta per andare avanti.",
        "en": "An answer is needed to go on.",
    },
    "common.choose_prompt": {
        "it": "Scrivi il numero della tua scelta:",
        "en": "Write the number of your choice:",
    },
    "common.choice_invalid": {
        "it": "Scegli uno dei numeri dell'elenco.",
        "en": "Choose one of the numbers in the list.",
    },
    "common.text_hint": {
        "it": "Scrivi una o più righe; una riga vuota conclude.",
        "en": "Write one or more lines; an empty line ends the text.",
    },
    "common.progress_started": {"it": "{label}...", "en": "{label}..."},
    "common.progress_running": {
        "it": "{label}: {detail} (da {elapsed})",
        "en": "{label}: {detail} ({elapsed} so far)",
    },
    "common.progress_waiting": {
        "it": "{label}: ancora in corso (da {elapsed})",
        "en": "{label}: still running ({elapsed} so far)",
    },
    "common.progress_done": {
        "it": "{label}: fatto in {elapsed}.",
        "en": "{label}: done in {elapsed}.",
    },
    "common.progress_not_completed": {
        "it": "{label}: non completato dopo {elapsed}.",
        "en": "{label}: not completed after {elapsed}.",
    },
    "common.progress_interrupted": {
        "it": "{label}: interrotto dopo {elapsed}.",
        "en": "{label}: interrupted after {elapsed}.",
    },
    "common.stage_brief": {"it": "Brief", "en": "Brief"},
    "common.stage_team": {"it": "Prospettive", "en": "Perspectives"},
    "common.stage_twins": {"it": "User Twin", "en": "User Twin"},
    "common.stage_requirements": {"it": "Definizione", "en": "Definition"},
    "common.stage_design": {"it": "Design e valutazione", "en": "Design & Evaluation"},
    "common.stage_package": {"it": "Dossier", "en": "Dossier"},
    "common.next_describe_idea": {
        "it": "Racconta la tua idea: lancia `ut init`.",
        "en": "Tell your idea: launch `ut init`.",
    },
    "common.next_approve_brief": {
        "it": "Approva il brief: lancia `ut init`.",
        "en": "Approve the brief: launch `ut init`.",
    },
    "common.next_approve_team": {
        "it": "Approva le prospettive: lancia `ut init`.",
        "en": "Approve the perspectives: launch `ut init`.",
    },
    "common.next_confirm_twins": {
        "it": "Conferma i twin: lancia `ut init`.",
        "en": "Confirm the twins: launch `ut init`.",
    },
    "common.next_approve_requirements": {
        "it": "Approva i requisiti: lancia `ut init`.",
        "en": "Approve the requirements: launch `ut init`.",
    },
    "common.next_approve_design": {
        "it": "Scegli e approva il design: lancia `ut design`.",
        "en": "Choose and approve the design: launch `ut design`.",
    },
    "common.next_download_folder": {
        "it": "Scarica la cartella di conoscenza: lancia `ut package publish`.",
        "en": "Download the knowledge folder: launch `ut package publish`.",
    },
    "common.next_unknown": {
        "it": "Prossima azione nello Studio: {code}.",
        "en": "Next action in the Studio: {code}.",
    },
    "common.folder_publishing": {
        "it": "Preparo la cartella di conoscenza nello Studio",
        "en": "Preparing the knowledge folder in the Studio",
    },
    "common.folder_downloading": {
        "it": "Scarico la cartella di conoscenza",
        "en": "Downloading the knowledge folder",
    },
}
