from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "test.help": {
        "it": "Verifica i criteri di accettazione sull'applicazione, nei browser di questo computer",
        "en": "Verify the acceptance criteria on the application, in the browsers of this computer",
    },
    "test.option_url": {
        "it": "indirizzo dell'applicazione da verificare (http o https)",
        "en": "address of the application to verify (http or https)",
    },
    "test.option_static": {
        "it": "cartella dell'applicazione costruita, con index.html: ut la serve da questo computer",
        "en": "folder of the built application, with index.html: ut serves it from this computer",
    },
    "test.option_browser": {
        "it": "browser da usare: chrome, firefox oppure all, cioè tutti quelli trovati "
        "(predefinito)",
        "en": "browser to use: chrome, firefox or all, that is every one found (default)",
    },
    "test.option_criteria": {
        "it": "codici dei criteri da verificare, separati da virgole (per esempio AC-001,AC-003)",
        "en": "codes of the criteria to verify, separated by commas (for example AC-001,AC-003)",
    },
    "test.option_plan": {
        "it": "latest riusa il piano dei test salvato finché vale ancora (predefinito); new chiede "
        "allo Studio un piano nuovo, a pagamento",
        "en": "latest reuses the saved test plan while it still fits (default); new asks the "
        "Studio for a new plan, which is paid",
    },
    "test.option_no_review": {
        "it": "non chiede ai twin di criticare l'esecuzione (nessuna spesa per le critiche)",
        "en": "do not ask the twins to criticize the run (no spending for the critiques)",
    },
    "test.option_max_usd": {
        "it": "spesa massima in USD per i piani di questa esecuzione: un secondo piano per i "
        "percorsi bloccati parte solo se resta entro questa cifra (predefinito 2.00)",
        "en": "most USD to spend on the plans of this run: a second plan for the blocked paths "
        "starts only if it stays within it (default 2.00)",
    },
    "test.option_open": {
        "it": "apre il rapporto nel browser alla fine",
        "en": "open the report in the browser at the end",
    },
    "test.option_json": {
        "it": "stampa l'esecuzione registrata come un solo documento JSON, per altri programmi",
        "en": "print the recorded run as a single JSON document, for other programs",
    },
    "test.heading": {
        "it": "Verifica dei criteri di «{name}»",
        "en": 'Acceptance tests of "{name}"',
    },
    "test.application_url": {
        "it": "Applicazione: l'indirizzo {address}.",
        "en": "Application: the address {address}.",
    },
    "test.application_static": {
        "it": "Applicazione: la cartella {folder}, servita da questo computer all'indirizzo "
        "{address}.",
        "en": "Application: the folder {folder}, served by this computer at {address}.",
    },
    "test.browser_failed": {
        "it": "{browser} non è partito e resta fuori da questa verifica: {detail}",
        "en": "{browser} did not start and stays out of this run: {detail}",
    },
    "test.browsers": {"it": "Browser: {browsers}.", "en": "Browsers: {browsers}."},
    "test.plan_reused": {
        "it": "Piano dei test riusato, scritto il {date}: percorsi {paths}, criteri non coperti "
        "{not_covered}.",
        "en": "Test plan reused, written on {date}: {paths} paths, {not_covered} criteria not "
        "covered.",
    },
    "test.plan_stale": {
        "it": "Il piano dei test salvato era per i requisiti versione {plan_requirements} e il "
        "design versione {plan_design}; la cartella di conoscenza ha i requisiti versione "
        "{requirements} e il design versione {design}: serve un piano nuovo.",
        "en": "The saved test plan was written for requirements version {plan_requirements} "
        "and design version {plan_design}; the knowledge folder has requirements version "
        "{requirements} and design version {design}: a new plan is needed.",
    },
    "test.plan_uncovered": {
        "it": "Il piano dei test salvato non copre {codes}: serve un piano nuovo.",
        "en": "The saved test plan does not cover {codes}: a new plan is needed.",
    },
    "test.plan_requested": {
        "it": "Lo Studio scrive ora un piano dei test: il modello legge la pagina come si apre e "
        "scrive i percorsi per i criteri di accettazione.",
        "en": "The Studio now writes a test plan: the model reads the page as it opens and "
        "writes the paths for the acceptance criteria.",
    },
    "test.plan_label": {"it": "Piano dei test", "en": "Test plan"},
    "test.plan_written": {
        "it": "Piano dei test nuovo: percorsi {paths}, criteri non coperti {not_covered}.",
        "en": "New test plan: {paths} paths, {not_covered} criteria not covered.",
    },
    "test.not_covered_line": {
        "it": "{code} non coperto: {reason}",
        "en": "{code} not covered: {reason}",
    },
    "test.plan_cost": {
        "it": "Costo del piano: {amount} USD.",
        "en": "Cost of the plan: {amount} USD.",
    },
    "test.path_label": {
        "it": "Percorso {code} in {browser}: {heading}",
        "en": "Path {code} in {browser}: {heading}",
    },
    "test.path_failed": {
        "it": "{code} in {browser} non superato al passo {step}: {detail}",
        "en": "{code} in {browser} failed at step {step}: {detail}",
    },
    "test.path_blocked": {
        "it": "{code} in {browser} bloccato al passo {step}: {detail}",
        "en": "{code} in {browser} blocked at step {step}: {detail}",
    },
    "test.detail_target_missing": {
        "it": "elemento non trovato: {target}",
        "en": "target not found: {target}",
    },
    "test.detail_expectation_failed": {
        "it": "attesa non verificata: {expectation}",
        "en": "expectation not met: {expectation}",
    },
    "test.detail_action_failed": {
        "it": "il browser non ha potuto eseguire il passo: {detail}",
        "en": "the browser could not do the step: {detail}",
    },
    "test.detail_page_not_loaded": {
        "it": "la pagina non si è aperta: {detail}",
        "en": "the page did not open: {detail}",
    },
    "test.detail_browser_not_started": {
        "it": "il browser non è partito: {detail}",
        "en": "the browser did not start: {detail}",
    },
    "test.detail_browser_failed": {
        "it": "il browser ha smesso di rispondere: {detail}",
        "en": "the browser stopped answering: {detail}",
    },
    "test.replan": {
        "it": "Percorsi bloccati mandati allo Studio per un piano nuovo: {codes}.",
        "en": "Blocked paths sent back to the Studio for a new plan: {codes}.",
    },
    "test.replan_label": {
        "it": "Piano nuovo per i percorsi bloccati",
        "en": "New plan for the blocked paths",
    },
    "test.replan_done": {
        "it": "Percorsi nuovi al posto di quelli bloccati: {codes}. Ora girano in ogni browser.",
        "en": "New paths in place of the blocked ones: {codes}. They now run in every browser.",
    },
    "test.replan_empty": {
        "it": "Il piano nuovo non ha trovato altri percorsi: i criteri dei percorsi bloccati "
        "restano senza percorso.",
        "en": "The new plan found no other path: the criteria of the blocked paths stay "
        "without a path.",
    },
    "test.replan_over_budget": {
        "it": "I percorsi bloccati non vengono ripianificati: con un piano nuovo la spesa "
        "arriverebbe a {amount} USD, oltre il limite di --max-usd ({limit} USD).",
        "en": "The blocked paths are not planned again: a new plan would bring the spending to "
        "{amount} USD, over the limit of --max-usd ({limit} USD).",
    },
    "test.replan_limit": {
        "it": "I percorsi bloccati non vengono ripianificati: il piano salvato ha già {count} "
        "piani aggiuntivi, il massimo che lo Studio accetta. Chiedi un piano nuovo con "
        "`ut test --plan new`.",
        "en": "The blocked paths are not planned again: the saved plan already has {count} "
        "further plans, the most the Studio takes. Ask for a new plan with "
        "`ut test --plan new`.",
    },
    "test.replan_unavailable": {
        "it": "I percorsi bloccati non vengono ripianificati: lo Studio non ha un modello "
        "collegato.",
        "en": "The blocked paths are not planned again: the Studio has no model connected.",
    },
    "test.replan_failed": {
        "it": "I percorsi bloccati non sono stati ripianificati ({code}): restano bloccati in "
        "questa esecuzione.",
        "en": "The blocked paths were not planned again ({code}): they stay blocked in this run.",
    },
    "test.column_criterion": {"it": "Criterio", "en": "Criterion"},
    "test.column_status": {"it": "Esito", "en": "Status"},
    "test.column_paths": {"it": "Percorsi", "en": "Paths"},
    "test.column_browsers": {"it": "Browser", "en": "Browsers"},
    "test.status_passed": {"it": "superato", "en": "passed"},
    "test.status_failed": {"it": "fallito", "en": "failed"},
    "test.status_blocked": {"it": "bloccato", "en": "blocked"},
    "test.status_not_covered": {"it": "non coperto", "en": "not covered"},
    "test.status_not_run": {"it": "non eseguito", "en": "not run"},
    "test.summary": {
        "it": "Criteri: {passed} superati, {failed} falliti, {blocked} bloccati, {not_covered} "
        "non coperti, {not_run} non eseguiti.",
        "en": "Criteria: {passed} passed, {failed} failed, {blocked} blocked, {not_covered} not "
        "covered, {not_run} not run.",
    },
    "test.report_written": {
        "it": "Rapporto con i passi e le schermate: {path}",
        "en": "Report with the steps and the screenshots: {path}",
    },
    "test.failed_summary": {
        "it": "Alcuni criteri sono falliti o bloccati: il rapporto mostra ogni passo con la sua "
        "schermata. Correggi l'applicazione, poi rilancia `ut test`.",
        "en": "Some criteria failed or were blocked: the report shows every step with its "
        "screenshot. Fix the application, then launch `ut test` again.",
    },
    "test.reviewing": {
        "it": "Ora i twin criticano l'esecuzione: twin {twins}, una generazione ciascuno.",
        "en": "The twins now criticize the run: {twins} twins, one generation each.",
    },
    "test.review_label": {"it": "Critiche dei twin", "en": "Critiques of the twins"},
    "test.review_heading": {
        "it": "Critiche dei twin su questa esecuzione",
        "en": "Critiques of the twins on this run",
    },
    "test.review_unavailable": {
        "it": "I twin non possono criticare l'esecuzione, perché lo Studio non ha un modello "
        "collegato (TEST_MODEL_NOT_CONFIGURED). L'esecuzione resta registrata.",
        "en": "The twins cannot criticize the run, because the Studio has no model connected "
        "(TEST_MODEL_NOT_CONFIGURED). The run stays recorded.",
    },
    "test.review_skipped": {
        "it": "I twin non criticano questa esecuzione: la spesa non è stata confermata. "
        "L'esecuzione resta registrata.",
        "en": "The twins do not criticize this run: the spending was not confirmed. The run "
        "stays recorded.",
    },
    "test.review_failed": {
        "it": "I twin non hanno criticato l'esecuzione ({code}). L'esecuzione resta registrata.",
        "en": "The twins did not criticize the run ({code}). The run stays recorded.",
    },
    "test.review_cost": {
        "it": "Costo delle critiche: {amount} USD.",
        "en": "Cost of the critiques: {amount} USD.",
    },
    "test.no_critiques": {
        "it": "Nessun twin ha espresso un parere.",
        "en": "No twin gave an opinion.",
    },
    "test.twin_unknown": {"it": "Un twin", "en": "A twin"},
    "test.twin_line": {"it": "{name}: {verdict}", "en": "{name}: {verdict}"},
    "test.verdict_fine": {"it": "i risultati vanno bene", "en": "the results are fine"},
    "test.verdict_concern": {
        "it": "i risultati sollevano un dubbio",
        "en": "the results raise a concern",
    },
    "test.verdict_drift": {
        "it": "l'applicazione si allontana da quanto approvato",
        "en": "the application departs from what was approved",
    },
    "test.no_findings": {"it": "Nessun problema segnalato.", "en": "No problem reported."},
    "test.finding": {"it": "{severity}: {text}", "en": "{severity}: {text}"},
    "test.severity_low": {"it": "Importanza bassa", "en": "Low importance"},
    "test.severity_medium": {"it": "Importanza media", "en": "Medium importance"},
    "test.severity_high": {"it": "Importanza alta", "en": "High importance"},
    "test.about_criterion": {
        "it": "criterio {code} «{title}»",
        "en": 'criterion {code} "{title}"',
    },
    "test.about_criterion_code": {"it": "criterio {code}", "en": "criterion {code}"},
    "test.about_requirement": {
        "it": "requisito {code} «{title}»",
        "en": 'requirement {code} "{title}"',
    },
    "test.about_requirement_code": {"it": "requisito {code}", "en": "requirement {code}"},
    "test.about_screen": {
        "it": "schermata {code} «{title}»",
        "en": 'screen {code} "{title}"',
    },
    "test.about_screen_code": {"it": "schermata {code}", "en": "screen {code}"},
    "test.finding_about": {
        "it": "{finding} (riguarda: {about})",
        "en": "{finding} (about: {about})",
    },
    "test.finding_action": {
        "it": "{finding} Cosa fare: {action}",
        "en": "{finding} What to do: {action}",
    },
    "test.folder_updated": {
        "it": "Cartella di conoscenza aggiornata in orchestwin/ (versione {version}): "
        "orchestwin/twins/feedback/tests.json contiene le esecuzioni con le critiche dei twin.",
        "en": "Knowledge folder updated in orchestwin/ (version {version}): "
        "orchestwin/twins/feedback/tests.json holds the runs with the critiques of the twins.",
    },
    "test.folder_not_updated": {
        "it": "La cartella di conoscenza non è stata aggiornata ({code}): l'esecuzione è "
        "registrata nello Studio; aggiorna la cartella più tardi con `ut package publish`.",
        "en": "The knowledge folder was not updated ({code}): the run is recorded in the "
        "Studio; update the folder later with `ut package publish`.",
    },
    "test.report_title": {
        "it": "Verifica dei criteri di «{name}»",
        "en": 'Acceptance tests of "{name}"',
    },
    "test.report_lead": {
        "it": "Esecuzione del {date} su {application}, in {browsers}.",
        "en": "Run of {date} on {application}, in {browsers}.",
    },
    "test.report_on_url": {"it": "l'indirizzo {address}", "en": "the address {address}"},
    "test.report_on_static": {"it": "la cartella {folder}", "en": "the folder {folder}"},
    "test.report_path": {
        "it": "{code} in {browser}, {seconds} s",
        "en": "{code} in {browser}, {seconds} s",
    },
    "test.report_not_covered": {
        "it": "Nessun percorso può verificare questo criterio dall'interfaccia: {reason}",
        "en": "No path can verify this criterion through the interface: {reason}",
    },
    "test.report_not_run": {
        "it": "Nessun percorso di questa esecuzione verifica questo criterio.",
        "en": "No path of this run verifies this criterion.",
    },
    "test.report_screenshot": {
        "it": "Schermata dopo il passo {index} di {code} in {browser}",
        "en": "Screenshot after step {index} of {code} in {browser}",
    },
    "test.report_page_text": {
        "it": "Testo della pagina alla fine: {text}",
        "en": "Text of the page at the end: {text}",
    },
    "test.report_no_review": {
        "it": "I twin non hanno ancora criticato questa esecuzione.",
        "en": "The twins have not criticized this run yet.",
    },
    "test.report_first_attempt": {
        "it": "Primo tentativo dei percorsi bloccati",
        "en": "First attempt of the blocked paths",
    },
    "test.report_first_attempt_lead": {
        "it": "Questi percorsi si sono bloccati nel primo browser e sono stati sostituiti da un "
        "piano nuovo: lo Studio registra soltanto i percorsi che li sostituiscono.",
        "en": "These paths got blocked in the first browser and were replaced by a new plan: "
        "the Studio records only the paths that replace them.",
    },
    "test.step_done": {"it": "fatto", "en": "done"},
    "test.step_failed": {"it": "non superato", "en": "failed"},
    "test.step_blocked": {"it": "bloccato", "en": "blocked"},
    "test.step_skipped": {"it": "saltato", "en": "skipped"},
    "test.step_open": {"it": "Apri {value}", "en": "Open {value}"},
    "test.step_click": {"it": "Fai clic su {target}", "en": "Click {target}"},
    "test.step_type": {"it": "Scrivi «{value}» in {target}", "en": 'Type "{value}" in {target}'},
    "test.step_select": {
        "it": "Scegli «{value}» in {target}",
        "en": 'Choose "{value}" in {target}',
    },
    "test.step_press": {"it": "Premi {value}", "en": "Press {value}"},
    "test.step_check": {"it": "Controlla la pagina", "en": "Check the page"},
    "test.step_expecting": {
        "it": "{step}; atteso: {expectation}",
        "en": "{step}; expected: {expectation}",
    },
    "test.expect_text_visible": {
        "it": "la pagina mostra «{text}»",
        "en": 'the page shows "{text}"',
    },
    "test.expect_text_absent": {
        "it": "la pagina non mostra «{text}»",
        "en": 'the page does not show "{text}"',
    },
    "test.expect_element_visible": {
        "it": "{target} è nella pagina",
        "en": "{target} is on the page",
    },
    "test.expect_element_absent": {
        "it": "{target} non è nella pagina",
        "en": "{target} is not on the page",
    },
    "test.expect_value_is": {
        "it": "{target} contiene «{text}»",
        "en": '{target} holds "{text}"',
    },
    "test.expect_url_contains": {
        "it": "l'indirizzo contiene «{text}»",
        "en": 'the address contains "{text}"',
    },
    "test.expect_title_contains": {
        "it": "il titolo contiene «{text}»",
        "en": 'the title contains "{text}"',
    },
    "test.target": {"it": "{role} «{name}»", "en": '{role} "{name}"'},
    "test.target_name": {"it": "«{name}»", "en": '"{name}"'},
    "test.errors.TEST_DESIGN_REQUIRED": {
        "it": "La verifica dei criteri richiede i requisiti e il design approvati nella cartella "
        "di conoscenza (TEST_DESIGN_REQUIRED): approvali con `ut init` e `ut design`, poi "
        "scarica la cartella con `ut package pull`.",
        "en": "The acceptance tests need the approved requirements and design in the knowledge "
        "folder (TEST_DESIGN_REQUIRED): approve them with `ut init` and `ut design`, then "
        "download the folder with `ut package pull`.",
    },
    "test.errors.TEST_APPLICATION_REQUIRED": {
        "it": "Non so ancora quale applicazione verificare (TEST_APPLICATION_REQUIRED): lancia "
        "`ut test --url INDIRIZZO` oppure `ut test --static CARTELLA`; le volte successive "
        "`ut test` la ricorda.",
        "en": "Which application to verify is not known yet (TEST_APPLICATION_REQUIRED): launch "
        "`ut test --url ADDRESS` or `ut test --static FOLDER`; the next times `ut test` "
        "remembers it.",
    },
    "test.errors.TEST_URL_INVALID": {
        "it": "L'indirizzo {address} non è un indirizzo http o https (TEST_URL_INVALID): "
        "scrivilo per esempio così: http://127.0.0.1:5173/.",
        "en": "The address {address} is not an http or https address (TEST_URL_INVALID): write "
        "it for example like this: http://127.0.0.1:5173/.",
    },
    "test.errors.TEST_STATIC_INVALID": {
        "it": "La cartella {folder} non esiste oppure non contiene index.html "
        "(TEST_STATIC_INVALID): indica la cartella dell'applicazione costruita.",
        "en": "The folder {folder} does not exist or has no index.html (TEST_STATIC_INVALID): "
        "give the folder of the built application.",
    },
    "test.errors.TEST_NO_BROWSER": {
        "it": "Su questo computer non trovo un browser che parta (TEST_NO_BROWSER): installa "
        "Google Chrome, Chromium, Microsoft Edge o Mozilla Firefox, oppure indica dove si trova "
        "il programma con la variabile ORCHESTWIN_CHROME o ORCHESTWIN_FIREFOX.",
        "en": "No browser that starts was found on this computer (TEST_NO_BROWSER): install "
        "Google Chrome, Chromium, Microsoft Edge or Mozilla Firefox, or say where the program "
        "is with the variable ORCHESTWIN_CHROME or ORCHESTWIN_FIREFOX.",
    },
    "test.errors.TEST_MODEL_NOT_CONFIGURED": {
        "it": "Questo Studio non ha un modello collegato, quindi non può scrivere un piano dei "
        "test nuovo (TEST_MODEL_NOT_CONFIGURED). Un piano già salvato su questo computer si "
        "esegue ancora con `ut test`; chi gestisce lo Studio può collegare un modello.",
        "en": "This Studio has no model connected, so it cannot write a new test plan "
        "(TEST_MODEL_NOT_CONFIGURED). A plan already saved on this computer still runs with "
        "`ut test`; whoever runs the Studio can connect a model.",
    },
    "test.errors.TEST_CRITERION_UNKNOWN": {
        "it": "Questi codici non sono criteri di accettazione dei requisiti approvati: {codes} "
        "(TEST_CRITERION_UNKNOWN). Usa i codici della cartella orchestwin/requirements, per "
        "esempio AC-001.",
        "en": "These codes are not acceptance criteria of the approved requirements: {codes} "
        "(TEST_CRITERION_UNKNOWN). Use the codes of the folder orchestwin/requirements, for "
        "example AC-001.",
    },
    "test.errors.TEST_MAX_USD_INVALID": {
        "it": "--max-usd vuole una cifra in dollari, da 0 in su (TEST_MAX_USD_INVALID).",
        "en": "--max-usd takes an amount of dollars, from 0 up (TEST_MAX_USD_INVALID).",
    },
    "test.errors.TEST_PLAN_NOT_FOUND": {
        "it": "Il piano dei test salvato su questo computer non è nello Studio "
        "(TEST_PLAN_NOT_FOUND): i risultati di questa esecuzione restano in .orchestwin/tests; "
        "lancia `ut test --plan new` per un piano nuovo, che è una nuova spesa.",
        "en": "The test plan saved on this computer is not in the Studio (TEST_PLAN_NOT_FOUND): "
        "the results of this run stay in .orchestwin/tests; launch `ut test --plan new` for a "
        "new plan, which is a new spending.",
    },
    "test.errors.TEST_RUN_NOT_FOUND": {
        "it": "Lo Studio non trova questa esecuzione (TEST_RUN_NOT_FOUND): rilancia `ut test`.",
        "en": "The Studio does not find this run (TEST_RUN_NOT_FOUND): launch `ut test` again.",
    },
    "test.errors.TEST_REVIEW_EXISTS": {
        "it": "Questa esecuzione ha già le critiche dei twin (TEST_REVIEW_EXISTS).",
        "en": "This run already has the critiques of the twins (TEST_REVIEW_EXISTS).",
    },
    "test.errors.ACCEPTANCE_CRITERION_UNKNOWN": {
        "it": "Lo Studio non conosce questi criteri di accettazione: {codes} "
        "(ACCEPTANCE_CRITERION_UNKNOWN). Scarica di nuovo la cartella con `ut package pull` e "
        "usa i suoi codici.",
        "en": "The Studio does not know these acceptance criteria: {codes} "
        "(ACCEPTANCE_CRITERION_UNKNOWN). Download the folder again with `ut package pull` and "
        "use its codes.",
    },
    "test.errors.REQUIREMENTS_APPROVAL_REQUIRED": {
        "it": "In questo momento i requisiti non sono approvati nello Studio "
        "(REQUIREMENTS_APPROVAL_REQUIRED): approvali con `ut init`, poi rilancia `ut test`.",
        "en": "The requirements are not approved in the Studio at the moment "
        "(REQUIREMENTS_APPROVAL_REQUIRED): approve them with `ut init`, then launch `ut test` "
        "again.",
    },
    "test.errors.DESIGN_APPROVAL_REQUIRED": {
        "it": "In questo momento il design non è approvato nello Studio "
        "(DESIGN_APPROVAL_REQUIRED): approvalo con `ut design approve`, poi rilancia `ut test`.",
        "en": "The design is not approved in the Studio at the moment (DESIGN_APPROVAL_REQUIRED): "
        "approve it with `ut design approve`, then launch `ut test` again.",
    },
    "test.errors.USER_MODELING_APPROVAL_REQUIRED": {
        "it": "In questo momento gli User Twin non sono approvati "
        "(USER_MODELING_APPROVAL_REQUIRED), quindi non possono criticare l'esecuzione, che "
        "resta registrata: approvali con `ut init`.",
        "en": "The User Twins are not approved at the moment (USER_MODELING_APPROVAL_REQUIRED), "
        "so they cannot criticize the run, which stays recorded: approve them with `ut init`.",
    },
    "test.errors.INVALID_PROVIDER_OUTPUT": {
        "it": "Il modello ha dato una risposta che lo Studio non può usare "
        "(INVALID_PROVIDER_OUTPUT): non è stato salvato niente. Rilanciando `ut test` si "
        "riprova, ed è una nuova spesa.",
        "en": "The model gave an answer that the Studio cannot use (INVALID_PROVIDER_OUTPUT): "
        "nothing was stored. Launching `ut test` again tries once more, and it is a new "
        "spending.",
    },
    "test.errors.RESPONSE_SCHEMA_ERROR": {
        "it": "Il modello ha dato una risposta nella forma sbagliata (RESPONSE_SCHEMA_ERROR): "
        "non è stato salvato niente. Rilanciando `ut test` si riprova, ed è una nuova spesa.",
        "en": "The model gave an answer in the wrong shape (RESPONSE_SCHEMA_ERROR): nothing was "
        "stored. Launching `ut test` again tries once more, and it is a new spending.",
    },
    "test.errors.INCOMPLETE_OUTPUT": {
        "it": "La risposta del modello si è interrotta a metà (INCOMPLETE_OUTPUT): non è stato "
        "salvato niente. Rilanciando `ut test` si riprova, ed è una nuova spesa.",
        "en": "The answer of the model stopped halfway (INCOMPLETE_OUTPUT): nothing was stored. "
        "Launching `ut test` again tries once more, and it is a new spending.",
    },
    "test.errors.CONTEXT_BUDGET_EXCEEDED": {
        "it": "Il materiale da mandare al modello è troppo grande (CONTEXT_BUDGET_EXCEEDED): non "
        "è stato salvato niente e niente è stato speso.",
        "en": "The material to send to the model is too large (CONTEXT_BUDGET_EXCEEDED): "
        "nothing was stored and nothing was spent.",
    },
    "test.errors.GENERATION_BUDGET_EXCEEDED": {
        "it": "Lo Studio ha rifiutato la generazione perché supererebbe un tetto di spesa. Chi "
        "gestisce lo Studio può alzare il tetto, poi rilancia `ut test`.",
        "en": "The Studio refused the generation because it would go over a spending ceiling. "
        "Whoever runs the Studio can raise the ceiling, then launch `ut test` again.",
    },
    "test.errors.GENERATION_BUDGET_EXCEEDED.total": {
        "it": "Lo Studio ha raggiunto il suo tetto di spesa complessivo ({ceiling} USD): la "
        "generazione non è partita. Chi gestisce lo Studio può alzare il tetto, poi rilancia "
        "`ut test`.",
        "en": "The Studio reached its overall spending ceiling ({ceiling} USD): the generation "
        "did not start. Whoever runs the Studio can raise the ceiling, then launch `ut test` "
        "again.",
    },
    "test.errors.GENERATION_BUDGET_EXCEEDED.project": {
        "it": "Questo progetto ha raggiunto il suo tetto di spesa ({ceiling} USD): la "
        "generazione non è partita. Chi gestisce lo Studio può alzare il tetto, poi rilancia "
        "`ut test`.",
        "en": "This project reached its spending ceiling ({ceiling} USD): the generation did not "
        "start. Whoever runs the Studio can raise the ceiling, then launch `ut test` again.",
    },
    "test.errors.GENERATION_BUDGET_EXCEEDED.generation": {
        "it": "La generazione supererebbe il tetto di spesa di una singola generazione "
        "({ceiling} USD), quindi non è partita. Chi gestisce lo Studio può alzarlo, poi rilancia "
        "`ut test`.",
        "en": "The generation would go over the spending ceiling of a single generation "
        "({ceiling} USD), so it did not start. Whoever runs the Studio can raise it, then launch "
        "`ut test` again.",
    },
    "test.errors.GENERATION_LOST": {
        "it": "{label}: la generazione si è persa, forse perché lo Studio è ripartito. Rilancia "
        "`ut test` (una generazione nuova è una nuova spesa).",
        "en": "{label}: the generation was lost, perhaps because the Studio restarted. Launch "
        "`ut test` again (a new generation is a new spending).",
    },
    "test.errors.GENERATION_STILL_RUNNING": {
        "it": "{label}: il lavoro continua nello Studio e il risultato resterà lì. Rilanciando "
        "`ut test` più tardi, un piano o delle critiche nuove sono una nuova spesa.",
        "en": "{label}: the work goes on in the Studio and its result stays there. Launching "
        "`ut test` again later, a new plan or new critiques are a new spending.",
    },
    "test.errors.GENERATION_INTERRUPTED": {
        "it": "Interrotto. {label}: il lavoro continua nello Studio e il risultato resterà lì.",
        "en": "Interrupted. {label}: the work goes on in the Studio and its result stays there.",
    },
    "test.errors.invalid_request": {
        "it": "Lo Studio ha rifiutato come non validi i dati mandati da ut test "
        "(invalid_request): i risultati già ottenuti restano in .orchestwin/tests su questo "
        "computer.",
        "en": "The Studio refused the data sent by ut test as not valid (invalid_request): the "
        "results already obtained stay in .orchestwin/tests on this computer.",
    },
}
