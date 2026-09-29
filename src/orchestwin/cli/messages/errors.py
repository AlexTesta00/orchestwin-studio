from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "errors.NOT_SIGNED_IN": {
        "it": "Non hai eseguito l'accesso allo Studio {studio}. Accedi con `ut login`.",
        "en": "You are not signed in to the Studio {studio}. Sign in with `ut login`.",
    },
    "errors.SESSION_EXPIRED": {
        "it": "L'accesso allo Studio {studio} è scaduto. Accedi di nuovo con `ut login`.",
        "en": "Your sign-in to the Studio {studio} has expired. Sign in again with `ut login`.",
    },
    "errors.invalid_authentication": {
        "it": "Lo Studio non riconosce più il tuo accesso. Accedi di nuovo con `ut login`.",
        "en": "The Studio no longer recognises your sign-in. Sign in again with `ut login`.",
    },
    "errors.STUDIO_UNREACHABLE": {
        "it": "Lo Studio all'indirizzo {address} non risponde. Controlla che sia avviato, "
        "poi riprova.",
        "en": "The Studio at {address} does not answer. Check that it is running, then try again.",
    },
    "errors.STUDIO_NOT_RECOGNIZED": {
        "it": "All'indirizzo {address} risponde un servizio che non sembra lo Studio di "
        "OrchesTwin (stato {http_status}). Controlla l'indirizzo.",
        "en": "The service that answers at {address} does not look like the OrchesTwin "
        "Studio (status {http_status}). Check the address.",
    },
    "errors.STUDIO_ADDRESS_INVALID": {
        "it": "L'indirizzo dello Studio non è valido: {address}. Scrivilo per esempio così: "
        "http://127.0.0.1:8000.",
        "en": "The address of the Studio is not valid: {address}. Write it for example like "
        "this: http://127.0.0.1:8000.",
    },
    "errors.STUDIO_NOT_SECURE": {
        "it": "L'indirizzo {address} usa http verso un altro computer: la password e "
        "l'accesso viaggerebbero in chiaro. Usa un indirizzo https.",
        "en": "The address {address} uses http towards another computer: the password and "
        "the sign-in would travel in clear. Use an https address.",
    },
    "errors.SPENDING_REFUSED": {
        "it": "Nessuna generazione è partita: la spesa non è stata confermata.",
        "en": "No generation started: the spending was not confirmed.",
    },
    "errors.GENERATION_BUDGET_EXCEEDED": {
        "it": "Lo Studio ha rifiutato la generazione perché supererebbe un tetto di spesa. "
        "Chi gestisce lo Studio può alzarlo.",
        "en": "The Studio refused the generation because it would go over a spending "
        "ceiling. Whoever runs the Studio can raise it.",
    },
    "errors.GENERATION_BUDGET_UNAVAILABLE": {
        "it": "Lo Studio non riesce a leggere quanto è già stato speso, quindi non avvia "
        "generazioni a pagamento. Riprova più tardi.",
        "en": "The Studio cannot read how much has already been spent, so it starts no paid "
        "generation. Try again later.",
    },
    "errors.PROJECT_NOT_LINKED": {
        "it": "Questa cartella non è collegata a un progetto dello Studio. Lancia `ut init` "
        "per crearne uno, oppure entra nella cartella del progetto.",
        "en": "This folder is not linked to a project of the Studio. Launch `ut init` to "
        "create one, or move into the folder of the project.",
    },
    "errors.PROJECT_ALREADY_LINKED": {
        "it": "La cartella {root} è già collegata a un progetto dello Studio.",
        "en": "The folder {root} is already linked to a project of the Studio.",
    },
    "errors.PROJECT_LINK_INVALID": {
        "it": "Il file {path} non si legge come collegamento a un progetto. Controllalo, "
        "oppure collega di nuovo la cartella.",
        "en": "The file {path} cannot be read as the link to a project. Check it, or link "
        "the folder again.",
    },
    "errors.PROJECT_NOT_FOUND": {
        "it": "Lo Studio non trova questo progetto per il tuo account.",
        "en": "The Studio does not find this project for your account.",
    },
    "errors.project_not_found": {
        "it": "Lo Studio non trova questo progetto per il tuo account.",
        "en": "The Studio does not find this project for your account.",
    },
    "errors.FOLDER_NOT_VERIFIED": {
        "it": "La cartella di conoscenza non supera la verifica ({code}: {path}). Scaricala "
        "di nuovo con `ut package pull`.",
        "en": "The knowledge folder does not pass the verification ({code}: {path}). "
        "Download it again with `ut package pull`.",
    },
    "errors.FOLDER_NOT_VERIFIED.LINE_ENDINGS": {
        "it": "Il file {path} della cartella di conoscenza ha i fine riga di Windows, forse "
        "riscritti da git. Scarica di nuovo la cartella con `ut package pull`: il file "
        ".gitattributes che la accompagna impedisce a git di cambiarli ({code}).",
        "en": "The file {path} of the knowledge folder has Windows line endings, perhaps "
        "rewritten by git. Download the folder again with `ut package pull`: the "
        ".gitattributes file that comes with it stops git from changing them ({code}).",
    },
    "errors.FOLDER_SWAP_FAILED": {
        "it": "La cartella {folder} non è stata sostituita ({path}): forse un suo file è "
        "aperto in un altro programma. La versione di prima è rimasta al suo posto: chiudi "
        "il programma e riprova.",
        "en": "The folder {folder} was not replaced ({path}): perhaps one of its files is "
        "open in another program. The previous version is still in place: close the "
        "program and try again.",
    },
    "errors.FOLDER_NOT_PUBLISHED": {
        "it": "Lo Studio non ha ancora pubblicato una cartella di conoscenza per questo "
        "progetto. Pubblicala con `ut package publish`.",
        "en": "The Studio has not published a knowledge folder for this project yet. "
        "Publish it with `ut package publish`.",
    },
    "errors.KNOWLEDGE_PACKAGE_NOT_FOUND": {
        "it": "Lo Studio non ha questa versione della cartella di conoscenza.",
        "en": "The Studio does not have this version of the knowledge folder.",
    },
    "errors.GENERATION_LOST": {
        "it": "La generazione si è persa, forse perché lo Studio è ripartito. Rilancia il "
        "comando: quello che hai già approvato è al sicuro.",
        "en": "The generation was lost, perhaps because the Studio restarted. Launch the "
        "command again: what you already approved is safe.",
    },
    "errors.GENERATION_REJECTED": {
        "it": "La generazione non ha superato i controlli dello Studio. Puoi riprovare, ma è "
        "una nuova spesa.",
        "en": "The generation did not pass the checks of the Studio. You can try again, but "
        "it is a new spending.",
    },
    "errors.GENERATION_STILL_RUNNING": {
        "it": "{label}: la generazione continua nello Studio. Rilancia il comando più tardi: "
        "la ritroverà.",
        "en": "{label}: the generation goes on in the Studio. Launch the command again "
        "later: it will find it.",
    },
    "errors.GENERATION_INTERRUPTED": {
        "it": "Interrotto. {label}: la generazione continua nello Studio; rilanciando il "
        "comando la ritrovi.",
        "en": "Interrupted. {label}: the generation goes on in the Studio; launching the "
        "command again finds it.",
    },
    "errors.TOO_MANY_GENERATIONS": {
        "it": "Nello Studio girano già troppe generazioni: aspetta che una finisca, poi riprova.",
        "en": "Too many generations are already running in the Studio: wait for one to "
        "finish, then try again.",
    },
    "errors.TIMEOUT": {
        "it": "Il modello ha impiegato troppo tempo e la generazione è stata fermata. Puoi "
        "riprovare, ma è una nuova spesa.",
        "en": "The model took too long and the generation was stopped. You can try again, "
        "but it is a new spending.",
    },
    "errors.PROVIDER_UNAVAILABLE": {
        "it": "Il fornitore del modello non si raggiunge in questo momento. Riprova tra "
        "qualche minuto.",
        "en": "The provider of the model cannot be reached right now. Try again in a few minutes.",
    },
    "errors.RATE_LIMITED": {
        "it": "Il fornitore del modello chiede di rallentare. Riprova tra qualche minuto.",
        "en": "The provider of the model asks to slow down. Try again in a few minutes.",
    },
    "errors.INPUT_CLOSED": {
        "it": "L'input si è chiuso mentre aspettavo una risposta: non ho fatto altro.",
        "en": "The input closed while an answer was awaited: nothing else was done.",
    },
    "errors.ANSWER_NOT_VALID": {
        "it": "Troppe risposte non valide: il comando si ferma qui.",
        "en": "Too many answers that are not valid: the command stops here.",
    },
    "errors.SESSION_FILE_LOCKED": {
        "it": "Il file degli accessi è occupato da un altro comando ut ({path}). Riprova tra poco.",
        "en": "The sign-in file is busy with another ut command ({path}). Try again in a moment.",
    },
    "errors.API_FAILURE": {
        "it": "Lo Studio ha risposto con un errore (stato {http_status}, {code}).",
        "en": "The Studio answered with an error (status {http_status}, {code}).",
    },
    "errors.UNKNOWN": {
        "it": "Qualcosa non è andato ({code}).",
        "en": "Something went wrong ({code}).",
    },
    "errors.UNEXPECTED": {
        "it": "Errore inatteso: {kind}: {detail}. Rilancia il comando con --debug per vedere "
        "i dettagli.",
        "en": "Unexpected error: {kind}: {detail}. Launch the command again with --debug to "
        "see the details.",
    },
}
