from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "align.help": {
        "it": "Legge le modifiche del codice e propone aggiornamenti alla Definizione, al Design "
        "e al piano dei test: li approvi uno per uno",
        "en": "Read the code changes and propose updates to the Definition, the Design and the "
        "test plan: you approve them one by one",
    },
    "align.option_since": {
        "it": "considera i commit dopo questo (hash o nome di un commit), invece che dopo "
        "l'ultimo esame",
        "en": "consider the commits after this one (hash or name of a commit), instead of after "
        "the latest review",
    },
    "align.option_dry_run": {
        "it": "registra i commit e mostra che cosa verrebbe esaminato, senza spendere",
        "en": "record the commits and show what would be reviewed, without spending",
    },
    "align.option_pending": {
        "it": "decide soltanto le proposte che aspettano ancora una decisione, senza esaminare "
        "nuovi commit",
        "en": "decide only the proposals still waiting for a decision, without reviewing new "
        "commits",
    },
    "align.heading": {
        "it": "Conoscenza di «{name}» allineata al codice",
        "en": 'Knowledge of "{name}" aligned with the code',
    },
    "align.start_since": {
        "it": "Punto di partenza: il commit {commit} indicato con --since.",
        "en": "Starting point: commit {commit}, given with --since.",
    },
    "align.start_run": {
        "it": "Punto di partenza: il commit {commit}, l'ultimo esaminato da `ut align`.",
        "en": "Starting point: commit {commit}, the latest one reviewed by `ut align`.",
    },
    "align.start_verify": {
        "it": "Punto di partenza: il commit {commit}, il punto allineato di `ut verify`.",
        "en": "Starting point: commit {commit}, the aligned point of `ut verify`.",
    },
    "align.start_all": {
        "it": "Punto di partenza: nessun esame precedente, considero tutti i commit del "
        "repository (al massimo gli ultimi {limit}).",
        "en": "Starting point: no earlier review, every commit of the repository is considered "
        "(the newest {limit} at most).",
    },
    "align.commits": {"it": "Commit da esaminare: {count}.", "en": "Commits to review: {count}."},
    "align.folder_only": {
        "it": "Commit che cambiano soltanto la cartella di conoscenza, lasciati fuori: {count} "
        "({commits}).",
        "en": "Commits that change only the knowledge folder, left out: {count} ({commits}).",
    },
    "align.nothing": {
        "it": "Non ci sono commit nuovi da esaminare.",
        "en": "There is no new commit to review.",
    },
    "align.waiting_hint": {
        "it": "Proposte che aspettano ancora una decisione: {count}. Decidile con "
        "`ut align --pending`.",
        "en": "Proposals still waiting for a decision: {count}. Decide them with "
        "`ut align --pending`.",
    },
    "align.recorded": {
        "it": "Commit registrati ora nello Studio: {count}.",
        "en": "Commits recorded now in the Studio: {count}.",
    },
    "align.dry_run": {
        "it": "Prova senza spesa (--dry-run). Commit che il modello leggerebbe: {count}.",
        "en": "Trial without spending (--dry-run). Commits the model would read: {count}.",
    },
    "align.dry_run_estimate": {
        "it": "Stima di questo esame: {amount} USD, circa {minutes}. Senza --dry-run parte "
        "davvero.",
        "en": "Estimate of this review: {amount} USD, about {minutes}. Without --dry-run it "
        "really starts.",
    },
    "align.dry_run_subscription": {
        "it": "Questo esame usa l'abbonamento di Claude: non spende credito. Tempo stimato: "
        "circa {minutes}. Senza --dry-run parte davvero.",
        "en": "This review runs on the Claude subscription: it spends no credit. Estimated "
        "time: about {minutes}. Without --dry-run it really starts.",
    },
    "align.reading": {
        "it": "Il modello legge il diff dei commit e propone aggiornamenti alla Definizione, "
        "al Design e al piano dei test. Nessuna proposta cambia qualcosa finché non la approvi.",
        "en": "The model reads the diff of the commits and proposes updates to the Definition, "
        "the Design and the test plan. No proposal changes anything until you approve it.",
    },
    "align.run_label": {
        "it": "Lettura delle modifiche del codice",
        "en": "Reading of the code changes",
    },
    "align.run_heading": {
        "it": "Che cosa ha cambiato il codice ({count} commit, fino a {commit})",
        "en": "What the code changed ({count} commits, up to {commit})",
    },
    "align.no_proposals": {
        "it": "Il modello non propone aggiornamenti: il codice non cambia ciò che la conoscenza "
        "dice.",
        "en": "The model proposes no update: the code does not change what the knowledge says.",
    },
    "align.section_requirements": {
        "it": "Proposte per la Definizione",
        "en": "Proposals for the Definition",
    },
    "align.section_design": {"it": "Proposte per il Design", "en": "Proposals for the Design"},
    "align.section_tests": {
        "it": "Proposte per il piano dei test",
        "en": "Proposals for the test plan",
    },
    "align.proposal": {"it": "{code}: {title}", "en": "{code}: {title}"},
    "align.rationale": {"it": "Perché: {text}", "en": "Why: {text}"},
    "align.origin_commits": {"it": "Commit: {items}", "en": "Commits: {items}"},
    "align.origin_files": {"it": "File: {files}", "en": "Files: {files}"},
    "align.excerpt": {"it": "Estratto del diff:", "en": "Excerpt of the diff:"},
    "align.excerpt_more": {
        "it": "(altre {count} righe nell'estratto)",
        "en": "({count} more lines in the excerpt)",
    },
    "align.subjects_requirements": {
        "it": "Requisiti toccati: {items}",
        "en": "Requirements concerned: {items}",
    },
    "align.subjects_screens": {
        "it": "Schermate toccate: {items}",
        "en": "Screens concerned: {items}",
    },
    "align.subjects_criteria": {
        "it": "Criteri toccati: {items}",
        "en": "Criteria concerned: {items}",
    },
    "align.hypothesis": {
        "it": "Ipotesi del modello ricavata dal diff del codice: nessuna persona l'ha verificata.",
        "en": "A hypothesis of the model drawn from the code diff: no person has verified it.",
    },
    "align.decision_heading": {
        "it": "La tua decisione su {code}: {title}",
        "en": "Your decision on {code}: {title}",
    },
    "align.decision_question": {
        "it": "Che cosa fai con questa proposta?",
        "en": "What do you do with this proposal?",
    },
    "align.choice_apply": {"it": "Applica", "en": "Apply"},
    "align.choice_edit": {
        "it": "Modifica il testo e applica",
        "en": "Edit the text and apply",
    },
    "align.choice_skip": {"it": "Salta", "en": "Skip"},
    "align.choice_later": {"it": "Più tardi", "en": "Later"},
    "align.decided_later": {
        "it": "La proposta resta in attesa: decidila quando vuoi con `ut align --pending` o "
        "nello Studio web.",
        "en": "The proposal stays waiting: decide it whenever you want with `ut align --pending` "
        "or in the web Studio.",
    },
    "align.request_heading": {
        "it": "Testo proposto dal modello:",
        "en": "Text proposed by the model:",
    },
    "align.skip_reason": {
        "it": "Perché la salti? (Invio per non dirlo)",
        "en": "Why do you skip it? (Enter to leave it unsaid)",
    },
    "align.skipped": {
        "it": "Proposta {code} saltata: non cambia niente.",
        "en": "Proposal {code} skipped: nothing changes.",
    },
    "align.apply_label": {
        "it": "Applicazione della proposta {code}",
        "en": "Applying proposal {code}",
    },
    "align.applied": {
        "it": "Proposta {code} applicata.",
        "en": "Proposal {code} applied.",
    },
    "align.already_decided": {
        "it": "La proposta {code} è già stata decisa, forse dallo Studio web: non cambia niente.",
        "en": "Proposal {code} was already decided, perhaps in the web Studio: nothing changes.",
    },
    "align.revision_pending": {
        "it": "Una modifica di questa sezione aspetta già la tua approvazione: approvala o "
        "scartala prima, poi riprova.",
        "en": "A change of this section already waits for your approval: approve or discard it "
        "first, then try again.",
    },
    "align.unchanged": {
        "it": "Il modello non ha trovato niente da cambiare con questa richiesta: la proposta "
        "resta in attesa.",
        "en": "The model found nothing to change with this request: the proposal stays waiting.",
    },
    "align.tests_marked": {
        "it": "Il piano dei test va rifatto: al prossimo `ut test` lo Studio scrive un piano "
        "nuovo che tiene conto di questa proposta.",
        "en": "The test plan must be made again: at the next `ut test` the Studio writes a new "
        "plan that takes this proposal into account.",
    },
    "align.requirements_approve": {
        "it": "Approvi i requisiti alla versione {version}? Dopo riaggancio il design approvato "
        "a questa versione, con i contenuti invariati.",
        "en": "Do you approve the requirements at version {version}? Then the approved design "
        "is re-anchored to this version, with its content unchanged.",
    },
    "align.requirements_left": {
        "it": "I requisiti alla versione {version} aspettano la tua approvazione: approvali con "
        "`ut init`.",
        "en": "The requirements at version {version} wait for your approval: approve them with "
        "`ut init`.",
    },
    "align.revision_left": {
        "it": "Le differenze proposte aspettano la tua decisione nella sezione Definizione "
        "dello Studio web.",
        "en": "The proposed differences wait for your decision in the Definition section of the "
        "web Studio.",
    },
    "align.design_changes": {
        "it": "Che cosa cambia nel design:",
        "en": "What changes in the design:",
    },
    "align.design_approve": {
        "it": "Approvi questa modifica del design? Diventa una nuova versione, approvata subito.",
        "en": "Do you approve this change of the design? It becomes a new version, approved at "
        "once.",
    },
    "align.design_left": {
        "it": "La modifica del design aspetta la tua decisione nella sezione Design dello Studio "
        "web.",
        "en": "The change of the design waits for your decision in the Design section of the web "
        "Studio.",
    },
    "align.design_revised": {
        "it": "Il design è ora alla versione {version}.",
        "en": "The design is now at version {version}.",
    },
    "align.pending_none": {
        "it": "Nessuna proposta aspetta una decisione.",
        "en": "No proposal waits for a decision.",
    },
    "align.pending_intro": {
        "it": "Proposte che aspettano una decisione: {count}.",
        "en": "Proposals waiting for a decision: {count}.",
    },
    "align.files_written": {
        "it": "Esito salvato in {path}.",
        "en": "Outcome saved in {path}.",
    },
    "align.errors.ALIGN_SINCE_UNKNOWN": {
        "it": "Il commit {commit} indicato con --since non è in questo repository: controlla "
        "l'hash o il nome.",
        "en": "The commit {commit} given with --since is not in this repository: check the hash "
        "or the name.",
    },
    "align.errors.ALIGN_PENDING_ALONE": {
        "it": "--pending si usa da solo: non va insieme a --since o --dry-run.",
        "en": "--pending goes alone: it cannot be used with --since or --dry-run.",
    },
    "align.errors.KNOWLEDGE_ALIGNMENT_MODEL_NOT_CONFIGURED": {
        "it": "Questo Studio non può leggere le modifiche del codice, perché non è collegato "
        "nessun modello. I commit restano registrati; chi gestisce lo Studio può collegare un "
        "modello.",
        "en": "This Studio cannot read the code changes, because no model is connected. The "
        "commits stay recorded; whoever runs the Studio can connect a model.",
    },
    "align.errors.DESIGN_CHANGE_MODEL_NOT_CONFIGURED": {
        "it": "Questo Studio non può modificare il design a parole, perché non è collegato "
        "nessun modello: la proposta resta in attesa.",
        "en": "This Studio cannot change the design from words, because no model is connected: "
        "the proposal stays waiting.",
    },
    "align.errors.REQUIREMENTS_CHANGE_UNAVAILABLE": {
        "it": "Questo Studio non può modificare la Definizione: la proposta resta in attesa.",
        "en": "This Studio cannot change the Definition: the proposal stays waiting.",
    },
    "align.errors.DESIGN_CHANGE_UNAVAILABLE": {
        "it": "Questo Studio non può modificare il Design: la proposta resta in attesa.",
        "en": "This Studio cannot change the Design: the proposal stays waiting.",
    },
    "align.errors.REQUIREMENTS_APPROVAL_REQUIRED": {
        "it": "In questo momento la Definizione non è approvata: approvala con `ut init`, poi "
        "rilancia `ut align`.",
        "en": "The Definition is not approved at the moment: approve it with `ut init`, then "
        "launch `ut align` again.",
    },
    "align.errors.DESIGN_APPROVAL_REQUIRED": {
        "it": "In questo momento il Design non è approvato: approvalo con `ut design approve`, "
        "poi rilancia `ut align`.",
        "en": "The Design is not approved at the moment: approve it with `ut design approve`, "
        "then launch `ut align` again.",
    },
    "align.errors.DESIGN_ALTERNATIVE_NOT_CHOSEN": {
        "it": "Il design non ha un'alternativa scelta: scegline una con `ut design`, poi riprova.",
        "en": "The design has no chosen alternative: choose one with `ut design`, then try again.",
    },
    "align.errors.CODE_CHANGE_NOT_FOUND": {
        "it": "Lo Studio non trova uno dei commit tra quelli registrati: rilancia `ut align`, "
        "che lo registra di nuovo.",
        "en": "The Studio does not find one of the commits among the recorded ones: launch "
        "`ut align` again, and it records it again.",
    },
    "align.errors.CODE_CHANGE_AMBIGUOUS": {
        "it": "L'inizio dell'hash indica più di un commit registrato: usa l'hash completo.",
        "en": "The start of the hash points to more than one recorded commit: use the whole hash.",
    },
    "align.errors.ALIGNMENT_PROPOSAL_DECIDED": {
        "it": "Questa proposta è già stata decisa: non cambia niente.",
        "en": "This proposal was already decided: nothing changes.",
    },
    "align.errors.ALIGNMENT_PROPOSAL_NOT_FOUND": {
        "it": "Lo Studio non trova questa proposta: rilancia `ut align --pending` per vedere "
        "quelle in attesa.",
        "en": "The Studio does not find this proposal: launch `ut align --pending` to see the "
        "waiting ones.",
    },
    "align.errors.KNOWLEDGE_ALIGNMENT_RUN_NOT_FOUND": {
        "it": "Lo Studio non trova questo esame delle modifiche del codice.",
        "en": "The Studio does not find this review of the code changes.",
    },
    "align.errors.INVALID_PROVIDER_OUTPUT": {
        "it": "Il modello ha dato una risposta che lo Studio non può usare: non è stato salvato "
        "niente. Rilanciando `ut align` si riprova, ed è una nuova spesa.",
        "en": "The model gave an answer that the Studio cannot use: nothing was stored. "
        "Launching `ut align` again tries once more, and it is a new expense.",
    },
    "align.errors.RESPONSE_SCHEMA_ERROR": {
        "it": "Il modello ha dato una risposta nella forma sbagliata: non è stato salvato "
        "niente. Rilanciando `ut align` si riprova, ed è una nuova spesa.",
        "en": "The model gave an answer in the wrong shape: nothing was stored. Launching "
        "`ut align` again tries once more, and it is a new expense.",
    },
    "align.errors.INCOMPLETE_OUTPUT": {
        "it": "La risposta del modello si è interrotta a metà: non è stato salvato niente. "
        "Rilanciando `ut align` si riprova, ed è una nuova spesa.",
        "en": "The answer of the model stopped halfway: nothing was stored. Launching "
        "`ut align` again tries once more, and it is a new expense.",
    },
    "align.errors.CONTEXT_BUDGET_EXCEEDED": {
        "it": "I commit sono troppo grandi perché il modello li legga insieme: usa --since per "
        "esaminarne meno alla volta.",
        "en": "The commits are too large for the model to read together: use --since to review "
        "fewer of them at a time.",
    },
    "align.errors.GENERATION_BUDGET_EXCEEDED": {
        "it": "Lo Studio ha rifiutato l'esame perché supererebbe un tetto di spesa. I commit "
        "restano registrati; chi gestisce lo Studio può alzare il tetto; poi rilancia "
        "`ut align`.",
        "en": "The Studio refused the review because it would go over a spending ceiling. The "
        "commits stay recorded; whoever runs the Studio can raise the ceiling; then launch "
        "`ut align` again.",
    },
    "align.errors.GENERATION_BUDGET_EXCEEDED.total": {
        "it": "Lo Studio ha raggiunto il suo tetto di spesa complessivo ({ceiling} USD): l'esame "
        "non è partito. I commit restano registrati; chi gestisce lo Studio può alzare il "
        "tetto; poi rilancia `ut align`.",
        "en": "The Studio reached its overall spending ceiling ({ceiling} USD): the review did "
        "not start. The commits stay recorded; whoever runs the Studio can raise the ceiling; "
        "then launch `ut align` again.",
    },
    "align.errors.GENERATION_BUDGET_EXCEEDED.project": {
        "it": "Questo progetto ha raggiunto il suo tetto di spesa ({ceiling} USD): l'esame non "
        "è partito. I commit restano registrati; chi gestisce lo Studio può alzare il tetto; "
        "poi rilancia `ut align`.",
        "en": "This project reached its spending ceiling ({ceiling} USD): the review did not "
        "start. The commits stay recorded; whoever runs the Studio can raise the ceiling; then "
        "launch `ut align` again.",
    },
    "align.errors.GENERATION_BUDGET_EXCEEDED.generation": {
        "it": "Una generazione dell'esame supererebbe il tetto di spesa di una singola "
        "generazione ({ceiling} USD), quindi non è partita. Chi gestisce lo Studio può alzarlo; "
        "poi rilancia `ut align`.",
        "en": "A generation of the review would go over the spending ceiling of a single "
        "generation ({ceiling} USD), so it did not start. Whoever runs the Studio can raise it; "
        "then launch `ut align` again.",
    },
    "align.errors.GENERATION_LOST": {
        "it": "{label}: la generazione si è persa, forse perché lo Studio è ripartito. I commit "
        "restano registrati: rilancia `ut align` (un nuovo esame è una nuova spesa).",
        "en": "{label}: the generation was lost, perhaps because the Studio restarted. The "
        "commits stay recorded: launch `ut align` again (a new review is a new expense).",
    },
    "align.errors.GENERATION_STILL_RUNNING": {
        "it": "{label}: la generazione continua nello Studio. Rilancia `ut align` più tardi: "
        "le proposte in attesa si decidono con `ut align --pending`.",
        "en": "{label}: the generation goes on in the Studio. Launch `ut align` again later: "
        "the waiting proposals are decided with `ut align --pending`.",
    },
    "align.errors.GENERATION_INTERRUPTED": {
        "it": "Interrotto. {label}: la generazione continua nello Studio; le proposte in attesa "
        "si decidono con `ut align --pending`.",
        "en": "Interrupted. {label}: the generation goes on in the Studio; the waiting "
        "proposals are decided with `ut align --pending`.",
    },
}
