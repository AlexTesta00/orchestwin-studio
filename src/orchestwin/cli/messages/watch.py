from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "watch.help": {
        "it": "Osserva i commit del progetto, li registra nello Studio e, con --twins, li fa "
        "esaminare ai twin",
        "en": "Watch the commits of the project, record them in the Studio and, with --twins, "
        "have the twins review them",
    },
    "watch.option_twins": {
        "it": "fa esaminare ai twin ogni nuovo commit (a pagamento, entro --max-usd)",
        "en": "have the twins review each new commit (paid, within --max-usd)",
    },
    "watch.option_max_usd": {
        "it": "spesa stimata massima di questa sessione, in USD; senza l'opzione 5.00",
        "en": "highest estimated spending of this session, in USD; 5.00 without the option",
    },
    "watch.option_interval": {
        "it": "secondi tra un controllo e il successivo, almeno 2; senza l'opzione 15",
        "en": "seconds between two checks, at least 2; 15 without the option",
    },
    "watch.option_once": {
        "it": "fa un solo controllo e termina",
        "en": "make one check only, then end",
    },
    "watch.heading": {
        "it": "Osservo i commit di «{name}»",
        "en": 'Watching the commits of "{name}"',
    },
    "watch.folder": {"it": "Cartella: {path}", "en": "Folder: {path}"},
    "watch.branch": {"it": "Ramo: {branch}", "en": "Branch: {branch}"},
    "watch.branch_detached": {
        "it": "Ramo: nessuno (HEAD non è su un ramo).",
        "en": "Branch: none (HEAD is not on a branch).",
    },
    "watch.aligned": {
        "it": "Punto allineato: commit {commit}. Registro i commit che vengono dopo.",
        "en": "Aligned point: commit {commit}. I record the commits that come after it.",
    },
    "watch.not_aligned": {
        "it": "Nessun commit è ancora allineato: registro i commit che vengono dopo {commit}, "
        "l'ultimo registrato nello Studio.",
        "en": "No commit is aligned yet: I record the commits that come after {commit}, the last "
        "one recorded in the Studio.",
    },
    "watch.not_aligned_head": {
        "it": "Nessun commit è ancora allineato e nessun commit di questo repository è registrato "
        "nello Studio: registro i commit fatti da adesso in poi.",
        "en": "No commit is aligned yet and no commit of this repository is recorded in the "
        "Studio: I record the commits made from now on.",
    },
    "watch.twins_off": {
        "it": "I twin non esaminano i commit: aggiungi --twins per farli esaminare.",
        "en": "The twins do not review the commits: add --twins to have them reviewed.",
    },
    "watch.review_unavailable": {
        "it": "I twin non possono esaminare il codice su questo Studio "
        "(CHANGE_REVIEW_MODEL_NOT_CONFIGURED): registro soltanto i commit.",
        "en": "The twins cannot review the code on this Studio "
        "(CHANGE_REVIEW_MODEL_NOT_CONFIGURED): I only record the commits.",
    },
    "watch.twins_on": {
        "it": "I twin esaminano ogni nuovo commit, fino a {cap} USD di spesa stimata in questa "
        "sessione (--max-usd).",
        "en": "The twins review each new commit, up to {cap} USD of estimated spending in this "
        "session (--max-usd).",
    },
    "watch.twins_on_subscription": {
        "it": "I twin esaminano ogni nuovo commit con l'abbonamento di Claude: non spendono "
        "credito. Per non consumare troppo l'abbonamento, in questa sessione si fermano prima di "
        "superare {cap} USD di esami ai prezzi a pagamento (--max-usd).",
        "en": "The twins review each new commit on the Claude subscription: they spend no "
        "credit. To spare the subscription, in this session they stop before going over {cap} "
        "USD of reviews at paid prices (--max-usd).",
    },
    "watch.credit": {
        "it": "Credito rimasto nello Studio: {remaining} USD.",
        "en": "Credit left in the Studio: {remaining} USD.",
    },
    "watch.waiting": {
        "it": "Controllo ogni {seconds} secondi. Fermami con Ctrl+C.",
        "en": "Checking every {seconds} seconds. Stop me with Ctrl+C.",
    },
    "watch.history_changed": {
        "it": "La storia del repository è cambiata (il commit {commit} non c'è più): riparto dal "
        "commit attuale.",
        "en": "The history of the repository changed (commit {commit} is gone): I go on from the "
        "current commit.",
    },
    "watch.new_commits": {"it": "Nuovi commit: {count}.", "en": "New commits: {count}."},
    "watch.nothing_new": {
        "it": "Nessun commit nuovo da registrare.",
        "en": "No new commit to record.",
    },
    "watch.folder_only": {
        "it": "Commit che cambiano soltanto la cartella di conoscenza, registrati senza farli "
        "esaminare: {count} ({commits}).",
        "en": "Commits that change only the knowledge folder, recorded without a review: "
        "{count} ({commits}).",
    },
    "watch.folder_only_dismissed": {
        "it": "Commit che cambiano soltanto la cartella di conoscenza, registrati senza farli "
        "esaminare: {count} ({commits}); il più recente non ha bisogno di una decisione ed è "
        "segnato come scartato.",
        "en": "Commits that change only the knowledge folder, recorded without a review: "
        "{count} ({commits}); the newest needs no decision and is marked as dismissed.",
    },
    "watch.cap_reached": {
        "it": "Il prossimo esame supererebbe {cap} USD di spesa stimata: i twin smettono di "
        "esaminare, i commit continuano a essere registrati. Fai esaminare gli altri con "
        "`ut align`.",
        "en": "The next review would go over {cap} USD of estimated spending: the twins stop "
        "reviewing, the commits are still recorded. Have the others reviewed with `ut align`.",
    },
    "watch.cap_reached_subscription": {
        "it": "Il prossimo esame supererebbe {cap} USD di esami ai prezzi a pagamento "
        "(--max-usd): i twin smettono di esaminare, i commit continuano a essere registrati. Fai "
        "esaminare gli altri con `ut align`.",
        "en": "The next review would go over {cap} USD of reviews at paid prices (--max-usd): "
        "the twins stop reviewing, the commits are still recorded. Have the others reviewed with "
        "`ut align`.",
    },
    "watch.review_stopped": {
        "it": "I twin smettono di esaminare ({code}): i commit continuano a essere registrati. "
        "`ut align` spiega che cosa manca.",
        "en": "The twins stop reviewing ({code}): the commits are still recorded. `ut align` "
        "explains what is missing.",
    },
    "watch.review_failed": {
        "it": "L'esame del commit {commit} non è riuscito ({code}): `ut align` può ripeterlo.",
        "en": "The review of commit {commit} did not succeed ({code}): `ut align` can repeat it.",
    },
    "watch.review_reminder": {
        "it": "La decisione su questo commit la prendi con `ut align`.",
        "en": "You take the decision on this commit with `ut align`.",
    },
    "watch.review_interrupted": {
        "it": "{label}: l'esame continua nello Studio; `ut align` lo ritrova.",
        "en": "{label}: the review goes on in the Studio; `ut align` finds it.",
    },
    "watch.stopped": {
        "it": "Osservazione terminata. I commit registrati aspettano la tua decisione con "
        "`ut align`.",
        "en": "Watching ended. The recorded commits wait for your decision with `ut align`.",
    },
    "watch.unreachable": {
        "it": "Lo Studio {address} non risponde: riprovo al prossimo controllo.",
        "en": "The Studio {address} does not answer: I try again at the next check.",
    },
    "watch.failed": {
        "it": "Lo Studio ha risposto con un errore ({code}): riprovo al prossimo controllo.",
        "en": "The Studio answered with an error ({code}): I try again at the next check.",
    },
    "watch.errors.WATCH_INTERVAL_INVALID": {
        "it": "L'intervallo tra due controlli deve essere di almeno {minimum} secondi.",
        "en": "The interval between two checks must be at least {minimum} seconds.",
    },
    "watch.errors.WATCH_MAX_USD_INVALID": {
        "it": "La spesa massima deve essere un importo positivo in USD, per esempio 5.00.",
        "en": "The highest spending must be a positive amount in USD, for example 5.00.",
    },
}
