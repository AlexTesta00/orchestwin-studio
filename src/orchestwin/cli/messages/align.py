from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "align.help": {
        "it": "Legge le modifiche del codice e propone aggiornamenti alla Definizione, al Design "
        "e al piano dei test, che approvi uno per uno; con --from-design porta il codice al "
        "design attuale",
        "en": "Read the code changes and propose updates to the Definition, the Design and the "
        "test plan, which you approve one by one; with --from-design bring the code up to the "
        "current design",
    },
    "align.option_since": {
        "it": "considera i commit dopo questo (hash o nome di un commit), invece che dopo "
        "l'ultimo esame; con --from-design, il numero della versione del design da cui partire",
        "en": "consider the commits after this one (hash or name of a commit), instead of after "
        "the latest review; with --from-design, the number of the design version to start from",
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
    "align.option_from_design": {
        "it": "porta il codice al design attuale: legge le differenze fra la versione del design "
        "a cui il codice è allineato e quella approvata, scrive un ordine di lavoro limitato a "
        "quelle e avvia il tuo agente di programmazione come `ut code`",
        "en": "bring the code up to the current design: read the differences between the design "
        "version the code is aligned with and the approved one, write a work order limited to "
        "them and start your coding agent as `ut code` does",
    },
    "align.option_max_agent_usd": {
        "it": "con --from-design e Claude Code senza conversazione (scelto con "
        "`ut code --headless`): quanto al massimo Claude Code può spendere in questa esecuzione "
        "sul tuo account, in USD",
        "en": "with --from-design and Claude Code without a conversation (chosen with "
        "`ut code --headless`): the most Claude Code may spend in this run on your account, in "
        "USD",
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
    "align.design_heading": {
        "it": "Codice di «{name}» allineato al design",
        "en": 'Code of "{name}" aligned with the design',
    },
    "align.design_point_since": {
        "it": "Punto di partenza: il design versione {version}, indicato con --since.",
        "en": "Starting point: design version {version}, given with --since.",
    },
    "align.design_point_run": {
        "it": "Punto di partenza: il design versione {version}, l'ultimo portato nel codice.",
        "en": "Starting point: design version {version}, the latest one brought into the code.",
    },
    "align.design_point_verify": {
        "it": "Punto di partenza: il design versione {version}, il punto allineato di `ut verify`.",
        "en": "Starting point: design version {version}, the aligned point of `ut verify`.",
    },
    "align.design_current": {
        "it": "Design approvato: versione {version}, alternativa {code}.",
        "en": "Approved design: version {version}, alternative {code}.",
    },
    "align.design_nothing": {
        "it": "Il codice è già allineato al design versione {version}: niente da fare.",
        "en": "The code is already aligned with design version {version}: nothing to do.",
    },
    "align.design_changes_heading": {
        "it": "Che cosa cambia dal design {from} al design {to}: {count} differenze",
        "en": "What changes from design {from} to design {to}: {count} differences",
    },
    "align.design_changes_heading_one": {
        "it": "Che cosa cambia dal design {from} al design {to}: {count} differenza",
        "en": "What changes from design {from} to design {to}: {count} difference",
    },
    "align.design_other_changes": {
        "it": "Altre {count} differenze riguardano critiche e criticità: non toccano il codice.",
        "en": "{count} other differences concern critiques and concerns: they do not touch the "
        "code.",
    },
    "align.design_other_changes_one": {
        "it": "Un'altra differenza riguarda critiche e criticità: non tocca il codice.",
        "en": "One other difference concerns critiques and concerns: it does not touch the code.",
    },
    "align.design_no_code_changes": {
        "it": "Il design {to} non cambia schermate, flussi, testi né aspetto rispetto al design "
        "{from}: niente da portare nel codice. Il punto allineato passa alla versione {to}.",
        "en": "Design {to} changes no screen, flow, text or look compared with design {from}: "
        "nothing to bring into the code. The aligned point moves to version {to}.",
    },
    "align.design_hand_commits": {
        "it": "Il codice ha {count} commit dopo il punto allineato che lo Studio non ha ancora "
        "esaminato: l'ordine di lavoro lo dice all'agente.",
        "en": "The code has {count} commits after the aligned point that the Studio has not "
        "examined yet: the work order tells the agent.",
    },
    "align.design_hand_commits_one": {
        "it": "Il codice ha {count} commit dopo il punto allineato che lo Studio non ha ancora "
        "esaminato: l'ordine di lavoro lo dice all'agente.",
        "en": "The code has {count} commit after the aligned point that the Studio has not "
        "examined yet: the work order tells the agent.",
    },
    "align.design_confirm": {
        "it": "Avvio l'agente adesso? Lavora sul tuo account di Claude Code, non sullo Studio.",
        "en": "Start the agent now? It works on your Claude Code account, not on the Studio.",
    },
    "align.design_next_steps": {
        "it": "Rileggi le modifiche, registra il commit e lancia `ut verify`: quando lo segni "
        "come allineato, il punto allineato di `ut verify` passa al design versione {version}.",
        "en": "Review the changes, commit them and launch `ut verify`: when you mark the commit "
        "as aligned, the aligned point of `ut verify` moves to design version {version}.",
    },
    "align.design_next_steps_failed": {
        "it": "L'agente non ha finito: l'ordine di lavoro resta in {folder}; correggi e rilancia "
        "`ut align --from-design`.",
        "en": "The agent did not finish: the work order stays in {folder}; fix what went wrong "
        "and launch `ut align --from-design` again.",
    },
    "align.design_line_selection": {
        "it": "{sign} alternativa scelta: {to} al posto di {from}",
        "en": "{sign} chosen alternative: {to} instead of {from}",
    },
    "align.design_line_alternative": {
        "it": "{sign} alternativa {code} «{title}» cambiata{fields}",
        "en": '{sign} alternative {code} "{title}" changed{fields}',
    },
    "align.design_line_workflow": {
        "it": "{sign} flusso {code} «{title}» {what}{fields}",
        "en": '{sign} flow {code} "{title}" {what}{fields}',
    },
    "align.design_line_visual": {
        "it": "{sign} linguaggio visivo cambiato{fields}",
        "en": "{sign} visual language changed{fields}",
    },
    "align.design_line_screen": {
        "it": "{sign} schermata {code} «{title}» {what}{fields}",
        "en": '{sign} screen {code} "{title}" {what}{fields}',
    },
    "align.design_line_element": {
        "it": "{sign} schermata {screen}: elemento {code} «{title}» {what}{fields}",
        "en": '{sign} screen {screen}: element {code} "{title}" {what}{fields}',
    },
    "align.design_line_transition": {
        "it": "{sign} passaggio {code} «{title}» {what}{fields}",
        "en": '{sign} transition {code} "{title}" {what}{fields}',
    },
    "align.design_line_mockup": {
        "it": "{sign} mockup della schermata {code} «{title}» {what}",
        "en": '{sign} mockup of screen {code} "{title}" {what}',
    },
    "align.design_line_styles": {
        "it": "{sign} stili del mockup cambiati",
        "en": "{sign} mockup styles changed",
    },
    "align.design_what_added": {"it": "aggiunta", "en": "added"},
    "align.design_what_removed": {"it": "tolta", "en": "removed"},
    "align.design_what_changed": {"it": "cambiata", "en": "changed"},
    "align.design_what_added_masculine": {"it": "aggiunto", "en": "added"},
    "align.design_what_removed_masculine": {"it": "tolto", "en": "removed"},
    "align.design_what_changed_masculine": {"it": "cambiato", "en": "changed"},
    "align.design_what_redrawn": {"it": "ridisegnato", "en": "redrawn"},
    "align.design_field_title": {"it": "titolo", "en": "title"},
    "align.design_field_summary": {"it": "sintesi", "en": "summary"},
    "align.design_field_information_architecture": {
        "it": "architettura delle informazioni",
        "en": "information architecture",
    },
    "align.design_field_steps": {"it": "passi", "en": "steps"},
    "align.design_field_state": {"it": "stato", "en": "state"},
    "align.design_field_kind": {"it": "tipo", "en": "kind"},
    "align.design_field_content": {"it": "contenuto", "en": "content"},
    "align.design_field_accessible_name": {"it": "nome accessibile", "en": "accessible name"},
    "align.design_field_options": {"it": "opzioni", "en": "options"},
    "align.design_field_field_name": {"it": "nome del campo", "en": "field name"},
    "align.design_field_required": {"it": "obbligatorietà", "en": "required"},
    "align.design_field_product_name": {"it": "nome del prodotto", "en": "product name"},
    "align.design_field_direction": {"it": "direzione visiva", "en": "visual direction"},
    "align.design_field_palette": {"it": "colori", "en": "colours"},
    "align.design_field_choices": {"it": "scelte visive", "en": "visual choices"},
    "align.design_field_tokens": {"it": "token di stile", "en": "style tokens"},
    "align.design_field_trigger": {"it": "elemento che lo avvia", "en": "element that starts it"},
    "align.design_field_source": {"it": "schermata di partenza", "en": "starting screen"},
    "align.design_field_target": {"it": "schermata di arrivo", "en": "destination screen"},
    "align.design_field_outcome": {"it": "esito", "en": "outcome"},
    "align.design_field_markup": {"it": "HTML", "en": "HTML"},
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
    "align.errors.ALIGN_PENDING_ALONE.FROM_DESIGN": {
        "it": "--pending si usa da solo: non va insieme a --from-design.",
        "en": "--pending goes alone: it cannot be used with --from-design.",
    },
    "align.errors.SPENDING_REFUSED.AGENT": {
        "it": "L'agente non è partito: non hai confermato.",
        "en": "The agent was not started: you did not confirm.",
    },
    "align.errors.CODE_AGENT_NOT_FOUND": {
        "it": "Non trovo Claude Code (CODE_AGENT_NOT_FOUND): installalo, oppure indica il suo "
        "programma con la variabile {variable}, oppure scegli un altro agente con "
        "`ut code --agent custom --command`.",
        "en": "Claude Code cannot be found (CODE_AGENT_NOT_FOUND): install it, or name its "
        "program with the variable {variable}, or choose another agent with "
        "`ut code --agent custom --command`.",
    },
    "align.errors.CODE_AGENT_NOT_STARTED": {
        "it": "L'agente {program} non è partito: {detail} (CODE_AGENT_NOT_STARTED).",
        "en": "The agent {program} did not start: {detail} (CODE_AGENT_NOT_STARTED).",
    },
    "align.errors.CODE_BUDGET_NEEDS_HEADLESS": {
        "it": "--max-agent-usd vale solo quando l'agente è Claude Code senza conversazione, "
        "scelto con `ut code --headless` (CODE_BUDGET_NEEDS_HEADLESS): Claude Code accetta un "
        "tetto di spesa solo quando lavora da solo.",
        "en": "--max-agent-usd works only when the agent is Claude Code without a conversation, "
        "chosen with `ut code --headless` (CODE_BUDGET_NEEDS_HEADLESS): Claude Code accepts a "
        "spending ceiling only when it works alone.",
    },
    "align.errors.CODE_MAX_USD_INVALID": {
        "it": "--max-agent-usd vuole un importo maggiore di 0, per esempio 2.50 "
        "(CODE_MAX_USD_INVALID).",
        "en": "--max-agent-usd needs an amount above 0, for example 2.50 (CODE_MAX_USD_INVALID).",
    },
    "align.errors.CODE_COMMAND_INVALID": {
        "it": "Il comando dell'agente custom salvato da `ut code` non si può usare "
        "(CODE_COMMAND_INVALID): sceglilo di nuovo con `ut code --agent custom --command`.",
        "en": "The command of the custom agent saved by `ut code` cannot be used "
        "(CODE_COMMAND_INVALID): choose it again with `ut code --agent custom --command`.",
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
