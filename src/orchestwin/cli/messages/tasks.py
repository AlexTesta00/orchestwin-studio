from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "tasks.help": {
        "it": "Mostra e cambia i compiti per il codice",
        "en": "Show and change the tasks for the code",
    },
    "tasks.option_action": {
        "it": "che cosa fare: add, done, drop, reopen, from-test o from-commit; senza, l'elenco "
        "dei compiti aperti",
        "en": "what to do: add, done, drop, reopen, from-test or from-commit; without it, the "
        "list of the open tasks",
    },
    "tasks.option_all": {
        "it": "mostra tutti i compiti, anche quelli fatti e quelli abbandonati",
        "en": "show every task, also the done and the dropped ones",
    },
    "tasks.option_json": {
        "it": "stampa un solo documento JSON, per altri programmi",
        "en": "print a single JSON document, for other programs",
    },
    "tasks.help_add": {
        "it": "scrive un compito tuo per il codice",
        "en": "write a task of your own for the code",
    },
    "tasks.help_done": {
        "it": "segna dei compiti come fatti",
        "en": "mark tasks as done",
    },
    "tasks.help_drop": {
        "it": "abbandona dei compiti che non servono più",
        "en": "drop tasks that are no longer wanted",
    },
    "tasks.help_reopen": {
        "it": "riapre dei compiti fatti o abbandonati",
        "en": "open again tasks that were done or dropped",
    },
    "tasks.help_from_test": {
        "it": "sceglie quali rilievi dei twin sulla verifica dei criteri diventano compiti",
        "en": "choose which findings of the twins on the acceptance tests become tasks",
    },
    "tasks.help_from_commit": {
        "it": "sceglie quali rilievi dei twin sull'esame di un commit diventano compiti",
        "en": "choose which findings of the twins on the review of a commit become tasks",
    },
    "tasks.option_text": {
        "it": "il testo del compito",
        "en": "the text of the task",
    },
    "tasks.option_codes": {
        "it": "i codici dei compiti, per esempio TSK-004",
        "en": "the codes of the tasks, for example TSK-004",
    },
    "tasks.option_note": {
        "it": "una nota breve sul perché (facoltativa)",
        "en": "a short note on why (optional)",
    },
    "tasks.option_run": {
        "it": "l'identificativo di un'esecuzione della verifica dei criteri; senza, l'ultima "
        "criticata dai twin",
        "en": "the identifier of a run of the acceptance tests; without it, the latest one the "
        "twins criticized",
    },
    "tasks.option_commit": {
        "it": "l'hash di un commit registrato, almeno 7 caratteri; senza, il commit in attesa "
        "più recente che ha un esame dei twin",
        "en": "the hash of a recorded commit, at least 7 characters; without it, the newest "
        "waiting commit that has a review of the twins",
    },
    "tasks.heading_open": {
        "it": "Compiti aperti per il codice di «{name}»",
        "en": 'Open tasks for the code of "{name}"',
    },
    "tasks.heading_all": {
        "it": "Tutti i compiti per il codice di «{name}»",
        "en": 'Every task for the code of "{name}"',
    },
    "tasks.column_code": {"it": "Codice", "en": "Code"},
    "tasks.column_status": {"it": "Stato", "en": "Status"},
    "tasks.column_text": {"it": "Compito", "en": "Task"},
    "tasks.column_origin": {"it": "Da dove viene", "en": "Where it comes from"},
    "tasks.status_open": {"it": "aperto", "en": "open"},
    "tasks.status_done": {"it": "fatto", "en": "done"},
    "tasks.status_dropped": {"it": "abbandonato", "en": "dropped"},
    "tasks.origin_owner": {"it": "scritto da te", "en": "written by you"},
    "tasks.origin_verdict": {
        "it": "dalla decisione sul commit {commit}",
        "en": "from the decision on commit {commit}",
    },
    "tasks.origin_commit": {
        "it": "rilievo di {twin} sul commit {commit}",
        "en": "finding of {twin} on commit {commit}",
    },
    "tasks.origin_test": {
        "it": "rilievo di {twin} sulla verifica dei criteri",
        "en": "finding of {twin} on the acceptance tests",
    },
    "tasks.origin_test_named": {
        "it": "rilievo di {twin} sulla verifica dei criteri del {run}",
        "en": "finding of {twin} on the acceptance tests of {run}",
    },
    "tasks.origin_some_twin": {"it": "un twin", "en": "a twin"},
    "tasks.none": {
        "it": "Non ci sono compiti aperti per il codice. I compiti nascono dai rilievi dei twin "
        "(`ut test`, `ut align`) oppure da te (`ut tasks add`).",
        "en": "There are no open tasks for the code. Tasks come from the findings of the twins "
        "(`ut test`, `ut align`) or from you (`ut tasks add`).",
    },
    "tasks.none_all": {
        "it": "Non c'è ancora nessun compito per il codice. I compiti nascono dai rilievi dei "
        "twin (`ut test`, `ut align`) oppure da te (`ut tasks add`).",
        "en": "There is no task for the code yet. Tasks come from the findings of the twins "
        "(`ut test`, `ut align`) or from you (`ut tasks add`).",
    },
    "tasks.hint": {
        "it": "Quando un compito è fatto, chiudilo con `ut tasks done CODE`; `ut code` affida i "
        "compiti aperti all'agente di programmazione.",
        "en": "When a task is done, close it with `ut tasks done CODE`; `ut code` hands the open "
        "tasks to the coding agent.",
    },
    "tasks.offline_unreachable": {
        "it": "Compiti letti dalla cartella di conoscenza {path}: lo Studio {studio} non risponde.",
        "en": "Tasks read from the knowledge folder {path}: the Studio {studio} does not answer.",
    },
    "tasks.offline_not_signed_in": {
        "it": "Compiti letti dalla cartella di conoscenza {path}: non hai eseguito l'accesso "
        "allo Studio {studio} (`ut login`).",
        "en": "Tasks read from the knowledge folder {path}: you are not signed in to the Studio "
        "{studio} (`ut login`).",
    },
    "tasks.offline_session_expired": {
        "it": "Compiti letti dalla cartella di conoscenza {path}: l'accesso allo Studio {studio} "
        "è scaduto (`ut login`).",
        "en": "Tasks read from the knowledge folder {path}: your sign-in to the Studio {studio} "
        "has expired (`ut login`).",
    },
    "tasks.offline_missing": {
        "it": "Compiti letti dalla cartella di conoscenza {path}: lo Studio {studio} non dà i "
        "compiti di questo progetto.",
        "en": "Tasks read from the knowledge folder {path}: the Studio {studio} does not give the "
        "tasks of this project.",
    },
    "tasks.added": {
        "it": "Compito scritto: {task}: {text}",
        "en": "Task written: {task}: {text}",
    },
    "tasks.changed_done": {
        "it": "Compiti segnati come fatti: {count}.",
        "en": "Tasks marked as done: {count}.",
    },
    "tasks.changed_dropped": {
        "it": "Compiti abbandonati: {count}.",
        "en": "Tasks dropped: {count}.",
    },
    "tasks.changed_reopened": {
        "it": "Compiti riaperti: {count}.",
        "en": "Tasks open again: {count}.",
    },
    "tasks.not_found": {
        "it": "{task} non è cambiato: lo Studio non trova questo compito (CODE_TASK_NOT_FOUND). "
        "`ut tasks --all` mostra tutti i codici.",
        "en": "{task} was not changed: the Studio does not find this task (CODE_TASK_NOT_FOUND). "
        "`ut tasks --all` shows every code.",
    },
    "tasks.not_changed": {
        "it": "{task} non è cambiato: lo Studio ha rifiutato la modifica ({code}).",
        "en": "{task} was not changed: the Studio refused the change ({code}).",
    },
    "tasks.folder_updated": {
        "it": "Cartella di conoscenza aggiornata in {path} (versione {version}): i compiti sono in "
        "{path}state, dove li legge anche `ut code`.",
        "en": "Knowledge folder updated in {path} (version {version}): the tasks are in "
        "{path}state, where `ut code` reads them too.",
    },
    "tasks.folder_not_updated": {
        "it": "La cartella di conoscenza non è stata aggiornata ({code}): la modifica è registrata "
        "nello Studio; aggiorna la cartella più tardi con `ut package publish`.",
        "en": "The knowledge folder was not updated ({code}): the change is recorded in the "
        "Studio; update the folder later with `ut package publish`.",
    },
    "tasks.test_heading": {
        "it": "Rilievi dei twin sulla verifica dei criteri del {date}",
        "en": "Findings of the twins on the acceptance tests of {date}",
    },
    "tasks.test_none_reviewed": {
        "it": "Nessuna esecuzione della verifica dei criteri ha ancora le critiche dei twin: "
        "`ut test` verifica i criteri e fa criticare l'esecuzione ai twin.",
        "en": "No run of the acceptance tests has the critiques of the twins yet: `ut test` "
        "verifies the criteria and has the twins criticize the run.",
    },
    "tasks.test_not_reviewed": {
        "it": "L'esecuzione {run} non ha ancora le critiche dei twin: nessun compito da creare.",
        "en": "The run {run} has no critiques of the twins yet: no task to create.",
    },
    "tasks.commit_heading": {
        "it": "Rilievi dei twin sul commit {commit}: {line}",
        "en": "Findings of the twins on commit {commit}: {line}",
    },
    "tasks.commit_none_reviewed": {
        "it": "Nessun commit in attesa ha ancora un esame dei twin: `ut align` registra i commit "
        "e li fa esaminare.",
        "en": "No waiting commit has a review of the twins yet: `ut align` records the commits "
        "and has them reviewed.",
    },
    "tasks.commit_not_reviewed": {
        "it": "Il commit {commit} non ha ancora un esame dei twin: nessun compito da creare. "
        "`ut align` lo fa esaminare.",
        "en": "The commit {commit} has no review of the twins yet: no task to create. "
        "`ut align` has it reviewed.",
    },
    "tasks.no_findings": {
        "it": "I twin non hanno segnalato nessun problema: nessun compito da creare.",
        "en": "The twins reported no problem: no task to create.",
    },
    "tasks.choose_question": {
        "it": "Quali diventano compiti? Scrivi i numeri separati da virgole o spazi, a per tutti; "
        "Invio per nessuno:",
        "en": "Which become tasks? Type their numbers separated by commas or spaces, a for all; "
        "Enter for none:",
    },
    "tasks.created": {
        "it": "Compiti creati: {count}.",
        "en": "Tasks created: {count}.",
    },
    "tasks.created_none": {
        "it": "Nessun compito creato.",
        "en": "No task created.",
    },
    "tasks.created_next": {
        "it": "`ut code` affida i compiti aperti all'agente di programmazione; `ut tasks` li "
        "mostra tutti.",
        "en": "`ut code` hands the open tasks to the coding agent; `ut tasks` shows them all.",
    },
    "tasks.choice_finding": {
        "it": "{who}, {importance}: {finding}",
        "en": "{who}, {importance}: {finding}",
    },
    "tasks.choice_verdict": {
        "it": "Il verdetto del modello: {text}",
        "en": "The verdict of the model: {text}",
    },
    "tasks.choice_task": {"it": "Compito: {text}", "en": "Task: {text}"},
    "tasks.choice_existing": {
        "it": "{line} (già il compito aperto {code})",
        "en": "{line} (already the open task {code})",
    },
    "tasks.importance_low": {"it": "importanza bassa", "en": "low importance"},
    "tasks.importance_medium": {"it": "importanza media", "en": "medium importance"},
    "tasks.importance_high": {"it": "importanza alta", "en": "high importance"},
    "tasks.twin_unknown": {"it": "Un twin", "en": "A twin"},
    "tasks.choice_invalid": {
        "it": "Scrivi numeri da 1 a {count}, separati da virgole o spazi, oppure a per tutti.",
        "en": "Type numbers from 1 to {count}, separated by commas or spaces, or a for all.",
    },
    "tasks.choice_too_many": {
        "it": "Qui puoi sceglierne al massimo {limit}.",
        "en": "You can choose at most {limit} here.",
    },
    "tasks.choice_given_up": {
        "it": "Nessuna risposta valida: non ho scelto niente.",
        "en": "No valid answer: nothing was chosen.",
    },
    "tasks.choice_all_tasks": {
        "it": "Ognuno di questi rilievi è già un compito aperto.",
        "en": "Each of these findings is already an open task.",
    },
    "tasks.errors.TASKS_CODE_INVALID": {
        "it": "{value} non è il codice di un compito (TASKS_CODE_INVALID): un codice è TSK- "
        "seguito da 3 a 6 cifre, per esempio TSK-004.",
        "en": "{value} is not the code of a task (TASKS_CODE_INVALID): a code is TSK- followed "
        "by 3 to 6 digits, for example TSK-004.",
    },
    "tasks.errors.TASKS_TEXT_EMPTY": {
        "it": "Il compito non ha testo (TASKS_TEXT_EMPTY): scrivilo dopo `ut tasks add`.",
        "en": "The task has no text (TASKS_TEXT_EMPTY): write it after `ut tasks add`.",
    },
    "tasks.errors.TASKS_TEXT_TOO_LONG": {
        "it": "Un compito ha al massimo {limit} caratteri (TASKS_TEXT_TOO_LONG): scrivilo più "
        "breve.",
        "en": "A task has at most {limit} characters (TASKS_TEXT_TOO_LONG): write it shorter.",
    },
    "tasks.errors.TASKS_NOTE_TOO_LONG": {
        "it": "La nota ha al massimo {limit} caratteri (TASKS_NOTE_TOO_LONG): scrivila più breve.",
        "en": "The note has at most {limit} characters (TASKS_NOTE_TOO_LONG): write it shorter.",
    },
    "tasks.errors.TASKS_RUN_INVALID": {
        "it": "{value} non è l'identificativo di un'esecuzione (TASKS_RUN_INVALID): copialo da "
        "`ut status --json`, oppure togli --run per usare l'ultima esecuzione criticata dai twin.",
        "en": "{value} is not the identifier of a run (TASKS_RUN_INVALID): copy it from "
        "`ut status --json`, or leave out --run to use the latest run the twins criticized.",
    },
    "tasks.errors.TASKS_COMMIT_INVALID": {
        "it": "{value} non è l'hash di un commit (TASKS_COMMIT_INVALID): scrivi almeno i suoi "
        "primi 7 caratteri, per esempio 4f2a9c1.",
        "en": "{value} is not the hash of a commit (TASKS_COMMIT_INVALID): write at least its "
        "first 7 characters, for example 4f2a9c1.",
    },
    "tasks.errors.CODE_TASK_NOT_FOUND": {
        "it": "Lo Studio non trova il compito {task} (CODE_TASK_NOT_FOUND): `ut tasks --all` "
        "mostra tutti i codici.",
        "en": "The Studio does not find the task {task} (CODE_TASK_NOT_FOUND): `ut tasks --all` "
        "shows every code.",
    },
    "tasks.errors.TASK_SOURCE_INVALID": {
        "it": "Un rilievo scelto non è più nell'ultimo esame (TASK_SOURCE_INVALID): nel frattempo "
        "i twin hanno esaminato di nuovo. Rilancia il comando: non è stato creato nessun compito.",
        "en": "A chosen finding is no longer in the latest review (TASK_SOURCE_INVALID): the "
        "twins reviewed again in the meantime. Launch the command again: no task was created.",
    },
    "tasks.errors.TEST_RUN_NOT_FOUND": {
        "it": "Lo Studio non trova l'esecuzione {run} (TEST_RUN_NOT_FOUND): controlla "
        "l'identificativo, oppure togli --run.",
        "en": "The Studio does not find the run {run} (TEST_RUN_NOT_FOUND): check the "
        "identifier, or leave out --run.",
    },
    "tasks.errors.CODE_CHANGE_NOT_FOUND": {
        "it": "Lo Studio non trova il commit {commit} tra quelli registrati "
        "(CODE_CHANGE_NOT_FOUND): `ut align` lo registra.",
        "en": "The Studio does not find the commit {commit} among the recorded ones "
        "(CODE_CHANGE_NOT_FOUND): `ut align` records it.",
    },
    "tasks.errors.CODE_CHANGE_AMBIGUOUS": {
        "it": "L'inizio dell'hash indica più di un commit registrato (CODE_CHANGE_AMBIGUOUS): "
        "scrivi più caratteri dell'hash.",
        "en": "The start of the hash points to more than one recorded commit "
        "(CODE_CHANGE_AMBIGUOUS): write more characters of the hash.",
    },
    "tasks.errors.invalid_request": {
        "it": "Lo Studio ha rifiutato come non validi i dati mandati da ut tasks "
        "(invalid_request).",
        "en": "The Studio refused the data sent by ut tasks as not valid (invalid_request).",
    },
}
