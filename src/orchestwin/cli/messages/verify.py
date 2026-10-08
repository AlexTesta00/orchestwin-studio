from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "verify.help": {
        "it": "Registra i commit nello Studio: i twin esaminano i commit e il modello dice se "
        "codice, Definizione e Design sono allineati; decidi tu",
        "en": "Record the commits in the Studio: the twins review the commits and the model says "
        "whether code, Definition and Design are aligned; you decide",
    },
    "verify.option_since": {
        "it": "considera i commit dopo questo (hash o nome di un commit), invece che dopo il "
        "punto allineato",
        "en": "consider the commits after this one (hash or name of a commit), instead of after "
        "the aligned point",
    },
    "verify.option_latest": {
        "it": "fa esaminare soltanto il commit più recente",
        "en": "have only the newest commit reviewed",
    },
    "verify.option_dry_run": {
        "it": "registra i commit e mostra che cosa verrebbe esaminato, senza spendere",
        "en": "record the commits and show what would be reviewed, without spending",
    },
    "verify.option_decide": {
        "it": "riapre la decisione su un commit già esaminato (hash o nome di un commit), senza "
        "nuovi esami e senza registrare altro",
        "en": "open again the decision on a commit already reviewed (hash or name of a commit), "
        "without new reviews and without recording anything else",
    },
    "verify.option_recheck": {
        "it": "fa esaminare di nuovo ai twin i commit in attesa il cui esame è stato fatto con "
        "versioni precedenti dei requisiti o del design",
        "en": "have the twins review again the waiting commits whose review was made against "
        "earlier versions of the requirements or of the design",
    },
    "verify.heading": {"it": "Allineamento di «{name}»", "en": 'Alignment of "{name}"'},
    "verify.reference": {
        "it": "Riferimento approvato: requisiti versione {requirements}, design versione "
        "{design} (alternativa {alternative}).",
        "en": "Approved reference: requirements version {requirements}, design version "
        "{design} (alternative {alternative}).",
    },
    "verify.not_aligned": {
        "it": "Nessun commit è ancora allineato.",
        "en": "No commit is aligned yet.",
    },
    "verify.aligned": {
        "it": "Punto allineato: commit {commit} del {date}, con i requisiti versione "
        "{requirements} e il design versione {design}.",
        "en": "Aligned point: commit {commit} of {date}, with requirements version "
        "{requirements} and design version {design}.",
    },
    "verify.open_tasks": {
        "it": "Compiti aperti per il codice: {count}.",
        "en": "Open tasks for the code: {count}.",
    },
    "verify.uncommitted": {
        "it": "Nella cartella ci sono modifiche non ancora salvate in un commit: ut verify "
        "considera soltanto i commit.",
        "en": "The folder has changes not saved in a commit yet: ut verify considers only commits.",
    },
    "verify.nothing": {
        "it": "Non ci sono commit nuovi da allineare.",
        "en": "There is no new commit to align.",
    },
    "verify.considered_since": {
        "it": "Commit dopo {commit}: {count}.",
        "en": "Commits after {commit}: {count}.",
    },
    "verify.considered_after": {
        "it": "Commit dopo il punto allineato: {count}.",
        "en": "Commits after the aligned point: {count}.",
    },
    "verify.considered_all": {
        "it": "Commit del repository considerati (al massimo gli ultimi {limit}): {count}.",
        "en": "Commits of the repository considered (the newest {limit} at most): {count}.",
    },
    "verify.commit_line": {
        "it": "{commit}  {date}  {line}  (file: {files})",
        "en": "{commit}  {date}  {line}  (files: {files})",
    },
    "verify.recorded": {
        "it": "Commit registrati ora nello Studio: {count}.",
        "en": "Commits recorded now in the Studio: {count}.",
    },
    "verify.dry_run": {
        "it": "Prova senza spesa (--dry-run). Commit che i twin esaminerebbero: {count}.",
        "en": "Trial without spending (--dry-run). Commits the twins would review: {count}.",
    },
    "verify.dry_run_none": {
        "it": "Prova senza spesa (--dry-run): ogni commit ha già un esame dei twin, non ci "
        "sarebbe niente da esaminare.",
        "en": "Trial without spending (--dry-run): every commit already has a review of the "
        "twins, there would be nothing to review.",
    },
    "verify.dry_run_estimate": {
        "it": "Stima di questi esami: {amount} USD, circa {minutes}. Senza --dry-run partono "
        "davvero.",
        "en": "Estimate of these reviews: {amount} USD, about {minutes}. Without --dry-run they "
        "really start.",
    },
    "verify.dry_run_subscription": {
        "it": "Questi esami usano l'abbonamento di Claude: non spendono credito. Tempo stimato: "
        "circa {minutes}. Senza --dry-run partono davvero.",
        "en": "These reviews run on the Claude subscription: they spend no credit. Estimated "
        "time: about {minutes}. Without --dry-run they really start.",
    },
    "verify.recheck_none": {
        "it": "Nessun esame è stato fatto con versioni precedenti dei requisiti o del design: non "
        "c'è niente da far esaminare di nuovo.",
        "en": "No review was made against earlier versions of the requirements or of the design: "
        "there is nothing to review again.",
    },
    "verify.recheck_list": {
        "it": "Esami fatti con versioni precedenti dei requisiti o del design, da rifare con i "
        "requisiti versione {requirements} e il design versione {design} (alternativa "
        "{alternative}): {count}.",
        "en": "Reviews made against earlier versions of the requirements or of the design, to do "
        "again with requirements version {requirements} and design version {design} "
        "(alternative {alternative}): {count}.",
    },
    "verify.recheck_line": {
        "it": "{commit}  {date}  {line}  (esaminato con i requisiti versione {requirements} e il "
        "design versione {design}, alternativa {alternative})",
        "en": "{commit}  {date}  {line}  (reviewed with requirements version {requirements} and "
        "design version {design}, alternative {alternative})",
    },
    "verify.recheck_dry_run": {
        "it": "Prova senza spesa (--dry-run): i twin esaminerebbero di nuovo questi commit.",
        "en": "Trial without spending (--dry-run): the twins would review these commits again.",
    },
    "verify.recheck_reviewing": {
        "it": "Commit da far esaminare di nuovo ai twin: {count}. Twin in ogni esame: {twins}. "
        "Ogni twin dà di nuovo la sua opinione, con le versioni approvate adesso, poi il modello "
        "dice se codice, design e requisiti sono ancora allineati.",
        "en": "Commits for the twins to review again: {count}. Twins in each review: {twins}. "
        "Each twin gives its opinion again, against the versions approved now, then the model "
        "says whether code, design and requirements are still aligned.",
    },
    "verify.recheck_hint": {
        "it": "Esami fatti con versioni precedenti dei requisiti o del design: {count}. "
        "`ut verify --recheck` fa riesaminare quei commit ai twin.",
        "en": "Reviews made against earlier versions of the requirements or of the design: "
        "{count}. `ut verify --recheck` has the twins review those commits again.",
    },
    "verify.reviews_none": {
        "it": "Ogni commit da considerare ha già un esame dei twin.",
        "en": "Every commit to consider already has a review of the twins.",
    },
    "verify.reviewing": {
        "it": "Commit da far esaminare ai twin: {count}. Twin in ogni esame: {twins}. Ogni twin "
        "dà la sua opinione su ogni commit, poi il modello dice se codice, design e requisiti "
        "sono ancora allineati.",
        "en": "Commits for the twins to review: {count}. Twins in each review: {twins}. Each "
        "twin gives its opinion on each commit, then the model says whether code, design and "
        "requirements are still aligned.",
    },
    "verify.review_label": {
        "it": "Esame del commit {commit}",
        "en": "Review of commit {commit}",
    },
    "verify.review_heading": {
        "it": "Esame del commit {commit}: {line}",
        "en": "Review of commit {commit}: {line}",
    },
    "verify.review_heading_plain": {
        "it": "Esame del commit {commit}",
        "en": "Review of commit {commit}",
    },
    "verify.no_critiques": {
        "it": "Nessun twin ha espresso un parere.",
        "en": "No twin gave an opinion.",
    },
    "verify.twin_unknown": {"it": "Un twin", "en": "A twin"},
    "verify.twin_line": {"it": "{name}: {verdict}", "en": "{name}: {verdict}"},
    "verify.critique_fine": {"it": "va bene così", "en": "fine"},
    "verify.critique_concern": {"it": "ha qualche dubbio", "en": "has a concern"},
    "verify.critique_drift": {
        "it": "vede il codice allontanarsi da quanto approvato",
        "en": "sees the code drift from what was approved",
    },
    "verify.no_findings": {
        "it": "Nessun problema segnalato.",
        "en": "No problem reported.",
    },
    "verify.review_cost": {
        "it": "Costo di questo esame: {amount} USD.",
        "en": "Cost of this review: {amount} USD.",
    },
    "verify.verdict_heading": {"it": "Verdetto del modello", "en": "Verdict of the model"},
    "verify.verdict_aligned": {
        "it": "Il codice è allineato ai requisiti e al design approvati (ALIGNED).",
        "en": "The code is aligned with the approved requirements and design (ALIGNED).",
    },
    "verify.verdict_code_drift": {
        "it": "Il codice si allontana dal design o dai requisiti approvati: è il codice che "
        "dovrebbe cambiare (CODE_DRIFT).",
        "en": "The code departs from the approved design or requirements: the code should "
        "change (CODE_DRIFT).",
    },
    "verify.verdict_design_outdated": {
        "it": "La modifica è un'evoluzione legittima che il design approvato non descrive: il "
        "design dovrebbe avere una nuova versione (DESIGN_OUTDATED).",
        "en": "The change is a legitimate evolution that the approved design does not "
        "describe: the design should get a new version (DESIGN_OUTDATED).",
    },
    "verify.verdict_requirements_outdated": {
        "it": "La modifica è un'evoluzione legittima che i requisiti approvati non coprono: i "
        "requisiti dovrebbero avere una nuova versione (REQUIREMENTS_OUTDATED).",
        "en": "The change is a legitimate evolution that the approved requirements do not "
        "cover: the requirements should get a new version (REQUIREMENTS_OUTDATED).",
    },
    "verify.verdict_other": {
        "it": "Verdetto del modello: {status}.",
        "en": "Verdict of the model: {status}.",
    },
    "verify.affected_requirements": {
        "it": "Requisiti coinvolti: {items}",
        "en": "Requirements concerned: {items}",
    },
    "verify.affected_screens": {
        "it": "Schermate coinvolte: {items}",
        "en": "Screens concerned: {items}",
    },
    "verify.proposed_design": {
        "it": "Richiesta proposta per il design:",
        "en": "Proposed request for the design:",
    },
    "verify.proposed_requirements": {
        "it": "Modifica proposta ai requisiti:",
        "en": "Proposed change of the requirements:",
    },
    "verify.proposed_tasks": {
        "it": "Compiti proposti per il codice:",
        "en": "Tasks proposed for the code:",
    },
    "verify.quoted": {"it": "«{text}»", "en": '"{text}"'},
    "verify.finding": {"it": "{severity}: {text}", "en": "{severity}: {text}"},
    "verify.severity_low": {"it": "Importanza bassa", "en": "Low importance"},
    "verify.severity_medium": {"it": "Importanza media", "en": "Medium importance"},
    "verify.severity_high": {"it": "Importanza alta", "en": "High importance"},
    "verify.about_requirement": {
        "it": "requisito {code} «{title}»",
        "en": 'requirement {code} "{title}"',
    },
    "verify.about_requirement_code": {"it": "requisito {code}", "en": "requirement {code}"},
    "verify.about_screen": {
        "it": "schermata {code} «{title}»",
        "en": 'screen {code} "{title}"',
    },
    "verify.about_screen_code": {"it": "schermata {code}", "en": "screen {code}"},
    "verify.about_file": {"it": "file {path}", "en": "file {path}"},
    "verify.finding_about": {
        "it": "{finding} (riguarda: {about})",
        "en": "{finding} (about: {about})",
    },
    "verify.finding_action": {
        "it": "{finding} Cosa fare: {action}",
        "en": "{finding} What to do: {action}",
    },
    "verify.named": {"it": "{code} «{title}»", "en": '{code} "{title}"'},
    "verify.decision_heading": {
        "it": "La tua decisione sul commit {commit}: {line}",
        "en": "Your decision on commit {commit}: {line}",
    },
    "verify.decision_question": {
        "it": "Che cosa fai con questo commit?",
        "en": "What do you do with this commit?",
    },
    "verify.choice_mark_aligned": {
        "it": "Segna questo commit come allineato",
        "en": "Mark this commit as aligned",
    },
    "verify.choice_aligned_anyway": {
        "it": "Segnalo comunque come allineato",
        "en": "Mark it as aligned anyway",
    },
    "verify.choice_tasks": {
        "it": "Registra dei compiti per il codice",
        "en": "Record tasks for the code",
    },
    "verify.choice_model_tasks": {
        "it": "Registra questi compiti per il codice",
        "en": "Record these tasks for the code",
    },
    "verify.choice_later": {"it": "Lascialo per dopo", "en": "Leave it for later"},
    "verify.choice_design": {
        "it": "Chiedi una nuova versione del design con questa richiesta",
        "en": "Ask for a new version of the design with this request",
    },
    "verify.choice_requirements": {
        "it": "Chiedi una modifica dei requisiti con questa richiesta",
        "en": "Ask for a change of the requirements with this request",
    },
    "verify.choice_design_follow": {
        "it": "Chiedi una nuova versione del design che segua questo commit",
        "en": "Ask for a new version of the design that follows this commit",
    },
    "verify.choice_requirements_follow": {
        "it": "Chiedi una modifica dei requisiti che segua questo commit",
        "en": "Ask for a change of the requirements that follows this commit",
    },
    "verify.decided_later": {
        "it": "Non ho registrato niente: il commit aspetta la tua decisione. Rilancia "
        "`ut verify` quando vuoi.",
        "en": "Nothing recorded: the commit waits for your decision. Launch `ut verify` again "
        "whenever you want.",
    },
    "verify.decided_aligned": {
        "it": "Il commit {commit} è ora il punto allineato: i compiti aperti per il codice che "
        "vengono da questo commit o da quelli precedenti sono chiusi; quelli dei commit più "
        "recenti restano aperti.",
        "en": "Commit {commit} is now the aligned point: the open tasks for the code that come "
        "from this commit or from earlier ones are closed; those of newer commits stay open.",
    },
    "verify.tasks_none": {
        "it": "Nessun compito scritto: non ho registrato niente.",
        "en": "No task written: nothing recorded.",
    },
    "verify.decided_tasks": {
        "it": "Compiti registrati per il codice: {count}. Restano aperti finché questo commit o "
        "uno successivo non viene segnato come allineato.",
        "en": "Tasks recorded for the code: {count}. They stay open until this commit or a "
        "later one is marked as aligned.",
    },
    "verify.covered_note": {"it": "coperto da {commit}", "en": "covered by {commit}"},
    "verify.folder_note": {
        "it": "solo cartella di conoscenza",
        "en": "knowledge folder only",
    },
    "verify.folder_only": {
        "it": "Commit che cambiano soltanto la cartella di conoscenza, registrati senza farli "
        "esaminare: {count} ({commits}).",
        "en": "Commits that change only the knowledge folder, recorded without a review: "
        "{count} ({commits}).",
    },
    "verify.folder_only_dismissed": {
        "it": "Commit che cambiano soltanto la cartella di conoscenza, registrati senza farli "
        "esaminare: {count} ({commits}); il più recente non ha bisogno di una decisione ed è "
        "segnato come scartato.",
        "en": "Commits that change only the knowledge folder, recorded without a review: "
        "{count} ({commits}); the newest needs no decision and is marked as dismissed.",
    },
    "verify.earlier_decision": {
        "it": "Decisione presa prima su questo commit: {decision}. Quella nuova la sostituisce.",
        "en": "Decision taken before on this commit: {decision}. The new one replaces it.",
    },
    "verify.kind_aligned": {"it": "segnato come allineato", "en": "marked as aligned"},
    "verify.kind_design_change": {
        "it": "chiesta una nuova versione del design",
        "en": "a new version of the design asked for",
    },
    "verify.kind_requirements_change": {
        "it": "chiesta una modifica dei requisiti",
        "en": "a change of the requirements asked for",
    },
    "verify.kind_code_tasks": {
        "it": "compiti registrati per il codice",
        "en": "tasks recorded for the code",
    },
    "verify.kind_dismissed": {"it": "scartato", "en": "dismissed"},
    "verify.dismissed": {
        "it": "Commit {commit}: stesso verdetto di {newest}, registrato come coperto da quel "
        "commit.",
        "en": "Commit {commit}: same verdict as {newest}, recorded as covered by it.",
    },
    "verify.design_request": {
        "it": "Richiesta per il design proposta dal modello:",
        "en": "Request for the design proposed by the model:",
    },
    "verify.design_not_started": {
        "it": "La nuova versione del design non è partita: non ho registrato nessuna decisione.",
        "en": "The new version of the design did not start: no decision was recorded.",
    },
    "verify.decided_design": {
        "it": "Decisione registrata: dal commit {commit} è stata chiesta una nuova versione del "
        "design.",
        "en": "Decision recorded: a new version of the design was requested from commit {commit}.",
    },
    "verify.design_approve": {
        "it": "Approvi ora la versione {version} del design?",
        "en": "Do you approve version {version} of the design now?",
    },
    "verify.design_left": {
        "it": "La versione {version} del design aspetta la tua approvazione: approvala con "
        "`ut design approve`.",
        "en": "Version {version} of the design waits for your approval: approve it with "
        "`ut design approve`.",
    },
    "verify.requirements_request": {
        "it": "Modifica dei requisiti proposta dal modello:",
        "en": "Change of the requirements proposed by the model:",
    },
    "verify.requirements_missing": {
        "it": "Lo Studio non ha una versione dei requisiti da modificare: non ho registrato "
        "nessuna decisione.",
        "en": "The Studio has no version of the requirements to change: no decision was recorded.",
    },
    "verify.decided_requirements": {
        "it": "Decisione registrata: dal commit {commit} è stata chiesta una modifica dei "
        "requisiti.",
        "en": "Decision recorded: a change of the requirements was requested from commit {commit}.",
    },
    "verify.requirements_approve": {
        "it": "Approvi i requisiti alla versione {version}? Dopo riaggancio il design approvato "
        "a questa versione, con i contenuti invariati.",
        "en": "Do you approve the requirements at version {version}? Then the approved design "
        "is re-anchored to this version, with its content unchanged.",
    },
    "verify.requirements_left": {
        "it": "I requisiti alla versione {version} aspettano la tua approvazione: approvali con "
        "`ut init`.",
        "en": "The requirements at version {version} wait for your approval: approve them with "
        "`ut init`.",
    },
    "verify.design_realigned": {
        "it": "Il design è stato riagganciato alla Definizione nuova e confermato alla versione "
        "{version}, senza ridisegnare le alternative.",
        "en": "The design was re-anchored to the new Definition and confirmed at version "
        "{version}, without redrawing the alternatives.",
    },
    "verify.design_not_realigned": {
        "it": "Questo Studio non sa ancora riagganciare il design alla Definizione nuova: "
        "aggiornalo, poi lancia `ut sections update`.",
        "en": "This Studio cannot re-anchor the design to the new Definition yet: update it, "
        "then launch `ut sections update`.",
    },
    "verify.design_realign_failed": {
        "it": "Il design non è stato riagganciato alla Definizione nuova ({code}): riprova più "
        "tardi con `ut sections update`.",
        "en": "The design was not re-anchored to the new Definition ({code}): try again later "
        "with `ut sections update`.",
    },
    "verify.request_keep": {
        "it": "Premi Invio per inviarla così, oppure scrivi il tuo testo:",
        "en": "Press Enter to send it as it is, or write your own text:",
    },
    "verify.request_write": {
        "it": "Descrivi a parole che cosa deve cambiare perché segua questo commit (un testo "
        "vuoto annulla e non registra niente):",
        "en": "Describe in words what should change so that it follows this commit (an empty "
        "text cancels and records nothing):",
    },
    "verify.request_none": {
        "it": "Nessuna richiesta scritta: non ho registrato niente.",
        "en": "No request written: nothing recorded.",
    },
    "verify.request_too_long": {
        "it": "La richiesta ha al massimo {limit} caratteri: scrivila più breve.",
        "en": "The request has at most {limit} characters: write it shorter.",
    },
    "verify.tasks_intro": {
        "it": "Scrivi i compiti per il codice, uno per riga (al massimo {limit}); una riga vuota "
        "conclude.",
        "en": "Write the tasks for the code, one per line (at most {limit}); an empty line ends "
        "the list.",
    },
    "verify.findings_intro": {
        "it": "Rilievi dei twin su questo commit che possono diventare compiti:",
        "en": "Findings of the twins on this commit that can become tasks:",
    },
    "verify.findings_intro_verdict": {
        "it": "Compiti proposti dal modello e rilievi dei twin su questo commit:",
        "en": "Tasks proposed by the model and findings of the twins on this commit:",
    },
    "verify.findings_question": {
        "it": "Quali rilievi diventano compiti? Scrivi i numeri separati da virgole o spazi, a per "
        "tutti; Invio per nessuno:",
        "en": "Which findings become tasks? Type their numbers separated by commas or spaces, a "
        "for all; Enter for none:",
    },
    "verify.findings_question_verdict": {
        "it": "Quali diventano compiti? Scrivi i numeri separati da virgole o spazi, a per tutti; "
        "Invio per i compiti proposti dal modello:",
        "en": "Which become tasks? Type their numbers separated by commas or spaces, a for all; "
        "Enter for the tasks proposed by the model:",
    },
    "verify.task_too_long": {
        "it": "Un compito ha al massimo {limit} caratteri: scrivilo più breve.",
        "en": "A task has at most {limit} characters: write it shorter.",
    },
    "verify.model_tasks_intro": {
        "it": "Il modello propone questi compiti. Per ognuno premi Invio per tenerlo, scrivi un "
        "testo nuovo per sostituirlo, oppure scrivi - per toglierlo.",
        "en": "The model proposes these tasks. For each one press Enter to keep it, write a new "
        "text to replace it, or write - to drop it.",
    },
    "verify.model_task": {"it": "Compito {number}: {text}", "en": "Task {number}: {text}"},
    "verify.model_task_edit": {
        "it": "Invio lo tiene, - lo toglie:",
        "en": "Enter keeps it, - drops it:",
    },
    "verify.folder_updated": {
        "it": "Cartella di conoscenza aggiornata in orchestwin/ (versione {version}): "
        "orchestwin/state contiene lo stato dello sviluppo.",
        "en": "Knowledge folder updated in orchestwin/ (version {version}): orchestwin/state "
        "holds the state of the development.",
    },
    "verify.folder_refused": {
        "it": "Lo Studio non ha pubblicato la cartella di conoscenza ({code}): la decisione è "
        "registrata; pubblicala più tardi con `ut package publish`.",
        "en": "The Studio did not publish the knowledge folder ({code}): the decision is "
        "recorded; publish it later with `ut package publish`.",
    },
    "verify.folder_not_updated": {
        "it": "La cartella di conoscenza non è stata aggiornata ({code}): la decisione è "
        "registrata; aggiornala più tardi con `ut package publish`.",
        "en": "The knowledge folder was not updated ({code}): the decision is recorded; update "
        "it later with `ut package publish`.",
    },
    "verify.errors.ALIGN_SINCE_UNKNOWN": {
        "it": "Il commit {commit} indicato con --since non è in questo repository: controlla "
        "l'hash o il nome.",
        "en": "The commit {commit} given with --since is not in this repository: check the hash "
        "or the name.",
    },
    "verify.errors.ALIGN_DECIDE_UNKNOWN": {
        "it": "Il commit {commit} indicato con --decide non è in questo repository: controlla "
        "l'hash o il nome.",
        "en": "The commit {commit} given with --decide is not in this repository: check the "
        "hash or the name.",
    },
    "verify.errors.ALIGN_DECIDE_ALONE": {
        "it": "--decide si usa da solo: non va insieme a --since, --latest o --dry-run.",
        "en": "--decide goes alone: it cannot be used with --since, --latest or --dry-run.",
    },
    "verify.errors.ALIGN_RECHECK_ALONE": {
        "it": "--recheck non va insieme a --since o --decide: usalo da solo, oppure con --latest "
        "e --dry-run.",
        "en": "--recheck cannot be used with --since or --decide: use it alone, or with --latest "
        "and --dry-run.",
    },
    "verify.errors.TASK_SOURCE_INVALID": {
        "it": "Un rilievo scelto non è più nell'ultimo esame del commit (TASK_SOURCE_INVALID): non "
        "è stato registrato niente. Rilancia `ut verify --decide` su quel commit.",
        "en": "A chosen finding is no longer in the latest review of the commit "
        "(TASK_SOURCE_INVALID): nothing was recorded. Launch `ut verify --decide` on that commit "
        "again.",
    },
    "verify.errors.ALIGN_NOT_REVIEWED": {
        "it": "Il commit {commit} non ha ancora un esame dei twin nello Studio "
        "(ALIGN_NOT_REVIEWED): lancia `ut verify` per registrarlo e farlo esaminare, poi decidi.",
        "en": "The commit {commit} has no review of the twins in the Studio yet "
        "(ALIGN_NOT_REVIEWED): launch `ut verify` to record it and have it reviewed, then "
        "decide.",
    },
    "verify.errors.CHANGE_REVIEW_MODEL_NOT_CONFIGURED": {
        "it": "I twin non possono esaminare il codice su questo Studio, perché non è collegato "
        "nessun modello (CHANGE_REVIEW_MODEL_NOT_CONFIGURED). I commit restano registrati; chi "
        "gestisce lo Studio può collegare un modello.",
        "en": "The twins cannot review the code on this Studio, because no model is connected "
        "(CHANGE_REVIEW_MODEL_NOT_CONFIGURED). The commits stay recorded; whoever runs the "
        "Studio can connect a model.",
    },
    "verify.errors.REQUIREMENTS_APPROVAL_REQUIRED": {
        "it": "In questo momento i requisiti non sono approvati "
        "(REQUIREMENTS_APPROVAL_REQUIRED): approvali con `ut init`, poi rilancia `ut verify`.",
        "en": "The requirements are not approved at the moment (REQUIREMENTS_APPROVAL_REQUIRED): "
        "approve them with `ut init`, then launch `ut verify` again.",
    },
    "verify.errors.DESIGN_APPROVAL_REQUIRED": {
        "it": "In questo momento il design non è approvato (DESIGN_APPROVAL_REQUIRED): "
        "approvalo con `ut design approve`, poi rilancia `ut verify`.",
        "en": "The design is not approved at the moment (DESIGN_APPROVAL_REQUIRED): approve it "
        "with `ut design approve`, then launch `ut verify` again.",
    },
    "verify.errors.USER_MODELING_APPROVAL_REQUIRED": {
        "it": "In questo momento gli User Twin non sono approvati "
        "(USER_MODELING_APPROVAL_REQUIRED): approvali con `ut init`, poi rilancia `ut verify`.",
        "en": "The User Twins are not approved at the moment (USER_MODELING_APPROVAL_REQUIRED): "
        "approve them with `ut init`, then launch `ut verify` again.",
    },
    "verify.errors.CODE_CHANGE_NOT_FOUND": {
        "it": "Lo Studio non trova questo commit tra quelli registrati (CODE_CHANGE_NOT_FOUND): "
        "rilancia `ut verify`, che lo registra di nuovo.",
        "en": "The Studio does not find this commit among the recorded ones "
        "(CODE_CHANGE_NOT_FOUND): launch `ut verify` again, and it records it again.",
    },
    "verify.errors.CODE_CHANGE_AMBIGUOUS": {
        "it": "L'inizio dell'hash indica più di un commit registrato (CODE_CHANGE_AMBIGUOUS): "
        "usa l'hash completo.",
        "en": "The start of the hash points to more than one recorded commit "
        "(CODE_CHANGE_AMBIGUOUS): use the whole hash.",
    },
    "verify.errors.INVALID_PROVIDER_OUTPUT": {
        "it": "Il modello ha dato una risposta che lo Studio non può usare "
        "(INVALID_PROVIDER_OUTPUT): non è stato salvato niente. Rilanciando `ut verify` si "
        "riprova, ed è una nuova spesa.",
        "en": "The model gave an answer that the Studio cannot use (INVALID_PROVIDER_OUTPUT): "
        "nothing was stored. Launching `ut verify` again tries once more, and it is a new "
        "expense.",
    },
    "verify.errors.RESPONSE_SCHEMA_ERROR": {
        "it": "Il modello ha dato una risposta nella forma sbagliata (RESPONSE_SCHEMA_ERROR): "
        "non è stato salvato niente. Rilanciando `ut verify` si riprova, ed è una nuova spesa.",
        "en": "The model gave an answer in the wrong shape (RESPONSE_SCHEMA_ERROR): nothing was "
        "stored. Launching `ut verify` again tries once more, and it is a new expense.",
    },
    "verify.errors.INCOMPLETE_OUTPUT": {
        "it": "La risposta del modello si è interrotta a metà (INCOMPLETE_OUTPUT): non è stato "
        "salvato niente. Rilanciando `ut verify` si riprova, ed è una nuova spesa.",
        "en": "The answer of the model stopped halfway (INCOMPLETE_OUTPUT): nothing was stored. "
        "Launching `ut verify` again tries once more, and it is a new expense.",
    },
    "verify.errors.CONTEXT_BUDGET_EXCEEDED": {
        "it": "Il commit è troppo grande perché il modello lo esamini (CONTEXT_BUDGET_EXCEEDED): "
        "dividi le modifiche in commit più piccoli.",
        "en": "The commit is too large for the model to review (CONTEXT_BUDGET_EXCEEDED): split "
        "the changes into smaller commits.",
    },
    "verify.errors.GENERATION_BUDGET_EXCEEDED": {
        "it": "Lo Studio ha rifiutato l'esame perché supererebbe un tetto di spesa. I commit "
        "restano registrati; chi gestisce lo Studio può alzare il tetto; poi rilancia "
        "`ut verify`.",
        "en": "The Studio refused the review because it would go over a spending ceiling. The "
        "commits stay recorded; whoever runs the Studio can raise the ceiling; then launch "
        "`ut verify` again.",
    },
    "verify.errors.GENERATION_BUDGET_EXCEEDED.total": {
        "it": "Lo Studio ha raggiunto il suo tetto di spesa complessivo ({ceiling} USD): l'esame "
        "non è partito. I commit restano registrati; chi gestisce lo Studio può alzare il "
        "tetto; poi rilancia `ut verify`.",
        "en": "The Studio reached its overall spending ceiling ({ceiling} USD): the review did "
        "not start. The commits stay recorded; whoever runs the Studio can raise the ceiling; "
        "then launch `ut verify` again.",
    },
    "verify.errors.GENERATION_BUDGET_EXCEEDED.project": {
        "it": "Questo progetto ha raggiunto il suo tetto di spesa ({ceiling} USD): l'esame non "
        "è partito. I commit restano registrati; chi gestisce lo Studio può alzare il tetto; "
        "poi rilancia `ut verify`.",
        "en": "This project reached its spending ceiling ({ceiling} USD): the review did not "
        "start. The commits stay recorded; whoever runs the Studio can raise the ceiling; then "
        "launch `ut verify` again.",
    },
    "verify.errors.GENERATION_BUDGET_EXCEEDED.generation": {
        "it": "Una generazione dell'esame supererebbe il tetto di spesa di una singola "
        "generazione ({ceiling} USD), quindi non è partita. Chi gestisce lo Studio può alzarlo; "
        "poi rilancia `ut verify`.",
        "en": "A generation of the review would go over the spending ceiling of a single "
        "generation ({ceiling} USD), so it did not start. Whoever runs the Studio can raise it; "
        "then launch `ut verify` again.",
    },
    "verify.errors.GENERATION_LOST": {
        "it": "{label}: l'esame si è perso, forse perché lo Studio è ripartito. I commit restano "
        "registrati: rilancia `ut verify` (un nuovo esame è una nuova spesa).",
        "en": "{label}: the review was lost, perhaps because the Studio restarted. The commits "
        "stay recorded: launch `ut verify` again (a new review is a new expense).",
    },
    "verify.errors.GENERATION_STILL_RUNNING": {
        "it": "{label}: l'esame continua nello Studio. Rilancia `ut verify` più tardi: lo "
        "ritrova senza spendere di nuovo.",
        "en": "{label}: the review goes on in the Studio. Launch `ut verify` again later: it "
        "finds it without spending again.",
    },
    "verify.errors.GENERATION_INTERRUPTED": {
        "it": "Interrotto. {label}: l'esame continua nello Studio; rilanciando `ut verify` lo "
        "ritrovi senza spendere di nuovo.",
        "en": "Interrupted. {label}: the review goes on in the Studio; launching `ut verify` "
        "again finds it without spending again.",
    },
}
