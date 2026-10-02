from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "mcp.title_get_why": {"it": "Perché?", "en": "Why?"},
    "mcp.describe_get_why": {
        "it": "Legge dal Dossier verificato la catena, le lacune e ciò che resta da verificare con persone vere. Nessuna generazione o spesa.",
        "en": "Reads the chain, gaps and what remains to verify with real people from the verified Dossier. No generation or spending.",
    },
    "mcp.parameter_why_code": {
        "it": "Codice dell'artefatto o selettore univoco restituito dal catalogo.",
        "en": "Artifact code or unique selector returned by the catalog.",
    },
    "mcp.title_get_evidence": {"it": "Leggi le evidenze", "en": "Read evidence"},
    "mcp.describe_get_evidence": {
        "it": "Legge dal Dossier le citazioni approvate, origine, versioni e limiti. Non invia testo originale e non genera; l'approvazione del proprietario non è validazione umana.",
        "en": "Reads approved quotations, origins, versions and limits from the Dossier. Does not send original text or generate; owner approval is not human validation.",
    },
    "mcp.parameter_evidence_code": {
        "it": "Codice facoltativo della fonte, per esempio EVD-001.",
        "en": "Optional source code, for example EVD-001.",
    },
    "mcp.help": {
        "it": "Avvia il server MCP orchestwin-twins, che dà agli agenti dell'editor la conoscenza "
        "approvata del progetto",
        "en": "Start the MCP server orchestwin-twins, which gives the agents of the editor the "
        "approved knowledge of the project",
    },
    "mcp.option_spend": {
        "it": "permette agli agenti gli strumenti a pagamento ask_twin, review_changes e "
        "run_tests: ogni chiamata è una spesa del modello",
        "en": "allow the agents the paid tools ask_twin, review_changes and run_tests: each call "
        "is a spending of the model",
    },
    "mcp.option_config": {
        "it": "invece di avviare il server mostra la configurazione da copiare nell'editor: "
        "claude-code, cursor oppure vscode",
        "en": "instead of starting the server, show the configuration to copy into the editor: "
        "claude-code, cursor or vscode",
    },
    "mcp.config_free": {
        "it": "Senza --spend gli strumenti a pagamento ask_twin, review_changes e run_tests "
        "rispondono con un errore; per permetterli aggiungi --spend.",
        "en": "Without --spend the paid tools ask_twin, review_changes and run_tests answer with "
        "an error; to allow them, add --spend.",
    },
    "mcp.config_spend": {
        "it": "Con --spend gli agenti possono usare ask_twin, review_changes e run_tests: ogni "
        "chiamata è una spesa del modello.",
        "en": "With --spend the agents can use ask_twin, review_changes and run_tests: each call "
        "is a spending of the model.",
    },
    "mcp.config_claude_code_command": {
        "it": "Per aggiungere il server a Claude Code lancia questo comando dalla cartella del "
        "progetto:",
        "en": "To add the server to Claude Code, launch this command from the folder of the "
        "project:",
    },
    "mcp.config_claude_code_file": {
        "it": "Oppure scrivi questo nel file .mcp.json della cartella del progetto:",
        "en": "Or write this in the file .mcp.json of the folder of the project:",
    },
    "mcp.config_cursor": {
        "it": "Scrivi questo nel file .cursor/mcp.json della cartella del progetto:",
        "en": "Write this in the file .cursor/mcp.json of the folder of the project:",
    },
    "mcp.config_vscode": {
        "it": "Scrivi questo nel file .vscode/mcp.json della cartella del progetto:",
        "en": "Write this in the file .vscode/mcp.json of the folder of the project:",
    },
    "mcp.started": {
        "it": "Server MCP orchestwin-twins avviato per il progetto «{project}» ({folder}). "
        "Strumenti a pagamento: {paid}. Aspetto i messaggi sull'input standard; per fermarlo "
        "chiudi l'input oppure premi Ctrl+C.",
        "en": 'MCP server orchestwin-twins started for the project "{project}" ({folder}). '
        "Paid tools: {paid}. Waiting for messages on the standard input; to stop it, close "
        "the input or press Ctrl+C.",
    },
    "mcp.paid_on": {"it": "permessi (--spend)", "en": "allowed (--spend)"},
    "mcp.paid_off": {"it": "non permessi (manca --spend)", "en": "not allowed (no --spend)"},
    "mcp.client": {
        "it": "Collegato a {client} (protocollo {version}).",
        "en": "Connected to {client} (protocol {version}).",
    },
    "mcp.stopped": {
        "it": "L'input si è chiuso: il server MCP si ferma.",
        "en": "The input closed: the MCP server stops.",
    },
    "mcp.interrupted": {
        "it": "Interrotto: il server MCP si ferma.",
        "en": "Interrupted: the MCP server stops.",
    },
    "mcp.internal_error": {
        "it": "Errore inatteso durante {method}: {kind}: {detail}. Il server continua; con "
        "--debug vedi i dettagli.",
        "en": "Unexpected error during {method}: {kind}: {detail}. The server goes on; --debug "
        "shows the details.",
    },
    "mcp.label_review": {
        "it": "Revisione del commit {commit}",
        "en": "Review of the commit {commit}",
    },
    "mcp.instructions_free": {
        "it": "Questo server dà agli agenti dell'editor la conoscenza approvata del progetto "
        "«{project}» di OrchesTwin Studio: brief, requisiti, design scelto, stato dello "
        "sviluppo, compiti per il codice, critiche dei twin sul codice ed esiti dei test di "
        "accettazione. Gli User Twin sono profili dei gruppi di utenti del progetto simulati dal "
        "modello: le loro risposte sono ipotesi da valutare, non opinioni di persone reali. "
        "Durante lo sviluppo un twin può aver imparato osservazioni nuove sul suo gruppo, "
        "approvate dal proprietario: get_twin e list_twins le mostrano, e dove contraddicono il "
        "profilo valgono loro, perché sono più recenti. Gli strumenti che leggono la cartella "
        "non spendono nulla, compresi get_tasks con i compiti aperti per il codice e "
        "get_test_results con gli ultimi esiti dei test; ask_twin e review_changes spendono sul "
        "modello e ora rispondono con un errore, perché il server è stato avviato senza "
        "--spend. Lo stesso vale per run_tests, che verifica i criteri di accettazione "
        "sull'applicazione nei browser di questo computer. Le decisioni sui commit e sui compiti "
        "restano al proprietario del progetto, con `ut align` e `ut tasks`.",
        "en": "This server gives the agents of the editor the approved knowledge of the project "
        '"{project}" of OrchesTwin Studio: brief, requirements, chosen design, development '
        "state, the tasks for the code, the critiques of the twins on the code and the outcome "
        "of the acceptance tests. User Twins are profiles of the user groups of the project "
        "simulated by the model: their answers are hypotheses to weigh, not opinions of real "
        "people. During the development a twin may have learned new observations about its "
        "group, approved by the owner: get_twin and list_twins show them, and where they "
        "contradict the profile they prevail, because they are newer. The tools that read the "
        "folder spend nothing, get_tasks with the open tasks for the code and get_test_results "
        "with the latest outcome of the tests included; ask_twin and review_changes spend on the "
        "model and now answer with an error, because the server was started without --spend. "
        "The same holds for run_tests, which checks the acceptance criteria on the application "
        "in the browsers of this computer. Decisions on the commits and on the tasks stay with "
        "the owner of the project, through `ut align` and `ut tasks`.",
    },
    "mcp.instructions_spend": {
        "it": "Questo server dà agli agenti dell'editor la conoscenza approvata del progetto "
        "«{project}» di OrchesTwin Studio: brief, requisiti, design scelto, stato dello "
        "sviluppo, compiti per il codice, critiche dei twin sul codice ed esiti dei test di "
        "accettazione. Gli User Twin sono profili dei gruppi di utenti del progetto simulati dal "
        "modello: le loro risposte sono ipotesi da valutare, non opinioni di persone reali. "
        "Durante lo sviluppo un twin può aver imparato osservazioni nuove sul suo gruppo, "
        "approvate dal proprietario: get_twin e list_twins le mostrano, e dove contraddicono il "
        "profilo valgono loro, perché sono più recenti. Gli strumenti che leggono la cartella "
        "non spendono nulla, compresi get_tasks con i compiti aperti per il codice e "
        "get_test_results con gli ultimi esiti dei test; ask_twin e review_changes spendono sul "
        "modello a ogni chiamata e sono permessi, perché il server è stato avviato con --spend. "
        "È permesso anche run_tests: verifica i criteri di accettazione sull'applicazione nei "
        "browser di questo computer, registra l'esito nello Studio e spende sul modello per il "
        "piano dei test e per le critiche dei twin. Le decisioni sui commit e sui compiti "
        "restano al proprietario del progetto, con `ut align` e `ut tasks`.",
        "en": "This server gives the agents of the editor the approved knowledge of the project "
        '"{project}" of OrchesTwin Studio: brief, requirements, chosen design, development '
        "state, the tasks for the code, the critiques of the twins on the code and the outcome "
        "of the acceptance tests. User Twins are profiles of the user groups of the project "
        "simulated by the model: their answers are hypotheses to weigh, not opinions of real "
        "people. During the development a twin may have learned new observations about its "
        "group, approved by the owner: get_twin and list_twins show them, and where they "
        "contradict the profile they prevail, because they are newer. The tools that read the "
        "folder spend nothing, get_tasks with the open tasks for the code and get_test_results "
        "with the latest outcome of the tests included; ask_twin and review_changes spend on the "
        "model at each call and are allowed, because the server was started with --spend. "
        "run_tests is allowed too: it checks the acceptance criteria on the application in the "
        "browsers of this computer, records the outcome in the Studio and spends on the model "
        "for the test plan and for the critiques of the twins. Decisions on the commits and on "
        "the tasks stay with the owner of the project, through `ut align` and `ut tasks`.",
    },
    "mcp.rpc_parse_error": {
        "it": "Il messaggio non è JSON valido.",
        "en": "The message is not valid JSON.",
    },
    "mcp.rpc_invalid_request": {
        "it": "Il messaggio non è una richiesta JSON-RPC 2.0 valida.",
        "en": "The message is not a valid JSON-RPC 2.0 request.",
    },
    "mcp.rpc_not_initialized": {
        "it": "Il server non è ancora inizializzato: manda prima initialize.",
        "en": "The server is not initialized yet: send initialize first.",
    },
    "mcp.rpc_method_not_found": {
        "it": "Metodo sconosciuto: {method}.",
        "en": "Unknown method: {method}.",
    },
    "mcp.rpc_params_object": {
        "it": "I parametri di {method} devono essere un oggetto JSON.",
        "en": "The parameters of {method} must be a JSON object.",
    },
    "mcp.rpc_param_missing": {
        "it": "Manca il parametro {name} di {method}, che deve essere un testo.",
        "en": "The parameter {name} of {method} is missing; it must be a text.",
    },
    "mcp.rpc_unknown_tool": {
        "it": "Strumento sconosciuto: {name}. Strumenti disponibili: {tools}.",
        "en": "Unknown tool: {name}. Available tools: {tools}.",
    },
    "mcp.rpc_resource_not_found": {
        "it": "Risorsa non trovata: {uri}. Le risorse sono i file .md della cartella di "
        "conoscenza.",
        "en": "Resource not found: {uri}. The resources are the .md files of the knowledge folder.",
    },
    "mcp.rpc_internal_error": {
        "it": "Errore interno del server ({kind}).",
        "en": "Internal error of the server ({kind}).",
    },
    "mcp.argument_object": {
        "it": "Gli argomenti di {tool} devono essere un oggetto JSON.",
        "en": "The arguments of {tool} must be a JSON object.",
    },
    "mcp.argument_unknown": {
        "it": "{tool} non ha l'argomento {name}.",
        "en": "{tool} has no argument {name}.",
    },
    "mcp.argument_missing": {
        "it": "Manca l'argomento {name} di {tool}.",
        "en": "The argument {name} of {tool} is missing.",
    },
    "mcp.argument_text": {
        "it": "L'argomento {name} di {tool} deve essere un testo di {minimum}-{maximum} caratteri.",
        "en": "The argument {name} of {tool} must be a text of {minimum}-{maximum} characters.",
    },
    "mcp.argument_twin": {
        "it": "L'argomento {name} di {tool} deve essere il numero del twin oppure l'inizio del "
        "suo nome, al massimo {maximum} caratteri.",
        "en": "The argument {name} of {tool} must be the number of the twin or the beginning "
        "of its name, at most {maximum} characters.",
    },
    "mcp.argument_count": {
        "it": "L'argomento {name} di {tool} deve essere un numero intero da {minimum} a {maximum}.",
        "en": "The argument {name} of {tool} must be a whole number from {minimum} to {maximum}.",
    },
    "mcp.argument_codes": {
        "it": "L'argomento {name} di {tool} deve essere un elenco di al massimo {maximum} "
        "codici, ciascuno di al massimo {length} caratteri, per esempio REQ-003.",
        "en": "The argument {name} of {tool} must be a list of at most {maximum} codes, each of "
        "at most {length} characters, for example REQ-003.",
    },
    "mcp.argument_commit": {
        "it": "L'argomento {name} di {tool} deve essere l'hash di un commit, da 7 a 64 "
        "caratteri esadecimali.",
        "en": "The argument {name} of {tool} must be the hash of a commit, 7 to 64 hexadecimal "
        "characters.",
    },
    "mcp.argument_revision": {
        "it": "L'argomento {name} di {tool} deve essere l'hash di un commit, da 7 a 64 "
        "caratteri esadecimali, oppure HEAD.",
        "en": "The argument {name} of {tool} must be the hash of a commit, 7 to 64 hexadecimal "
        "characters, or HEAD.",
    },
    "mcp.argument_criteria": {
        "it": "L'argomento {name} di {tool} deve essere un elenco da {minimum} a {maximum} codici "
        "di criteri di accettazione, ciascuno di al massimo {length} caratteri, per esempio "
        "AC-003.",
        "en": "The argument {name} of {tool} must be a list of {minimum} to {maximum} codes of "
        "acceptance criteria, each of at most {length} characters, for example AC-003.",
    },
    "mcp.argument_application": {
        "it": "L'argomento {name} di {tool} deve essere un oggetto con kind (URL oppure STATIC) e "
        "address (un testo da 1 a {maximum} caratteri).",
        "en": "The argument {name} of {tool} must be an object with kind (URL or STATIC) and "
        "address (a text of 1 to {maximum} characters).",
    },
    "mcp.argument_browser": {
        "it": "L'argomento {name} di {tool} deve essere chrome, firefox oppure all.",
        "en": "The argument {name} of {tool} must be chrome, firefox or all.",
    },
    "mcp.argument_flag": {
        "it": "L'argomento {name} di {tool} deve essere true oppure false.",
        "en": "The argument {name} of {tool} must be true or false.",
    },
    "mcp.argument_status": {
        "it": "L'argomento {name} di {tool} deve essere open oppure all.",
        "en": "The argument {name} of {tool} must be open or all.",
    },
    "mcp.title_project_state": {"it": "Stato del progetto", "en": "Project state"},
    "mcp.describe_project_state": {
        "it": "Stato del progetto letto dalla cartella di conoscenza: passi approvati, versioni "
        "di requisiti e design da realizzare, punto allineato, commit successivi e quante loro "
        "revisioni sono da rifare perché fatte su versioni precedenti, compiti aperti per il "
        "codice e che cosa fare dopo. Nessuna spesa.",
        "en": "State of the project read from the knowledge folder: approved steps, "
        "requirements and design versions to implement, aligned point, later commits and how "
        "many of their reviews need doing again because they were made on earlier versions, "
        "open tasks for the code and what to do next. No spending.",
    },
    "mcp.title_list_twins": {"it": "User Twin del progetto", "en": "User Twins of the project"},
    "mcp.describe_list_twins": {
        "it": "Elenca gli User Twin approvati con numero, nome, ruolo, primo obiettivo, versione "
        "(per esempio 1.2: profilo approvato 1, due passi di apprendimento durante lo sviluppo) "
        "e numero di osservazioni imparate durante lo sviluppo. Gli User Twin sono profili dei "
        "gruppi di utenti simulati dal modello. Nessuna spesa.",
        "en": "List the approved User Twins with number, name, role, first goal, version (for "
        "example 1.2: approved profile 1, two learning steps during the development) and the "
        "number of observations learned during the development. User Twins are profiles of the "
        "user groups simulated by the model. No spending.",
    },
    "mcp.title_get_twin": {"it": "Profilo di un User Twin", "en": "Profile of a User Twin"},
    "mcp.describe_get_twin": {
        "it": "Profilo completo di un User Twin: ruolo, obiettivi, frustrazioni, difficoltà, "
        "contesto d'uso e ogni osservazione con la sua origine; in learned, le osservazioni che "
        "il twin ha imparato durante lo sviluppo, approvate dal proprietario. Nessuna spesa.",
        "en": "Full profile of a User Twin: role, goals, frustrations, pain points, context of "
        "use and every observation with its origin; in learned, the observations that the twin "
        "learned during the development, approved by the owner. No spending.",
    },
    "mcp.title_get_requirements": {"it": "Requisiti approvati", "en": "Approved requirements"},
    "mcp.describe_get_requirements": {
        "it": "Requisiti approvati con storie utente e criteri di accettazione; con codes solo "
        "i codici indicati e ciò che cita quei requisiti. Nessuna spesa.",
        "en": "Approved requirements with user stories and acceptance criteria; with codes "
        "only the given codes and what cites those requirements. No spending.",
    },
    "mcp.title_get_design": {"it": "Design approvato", "en": "Approved design"},
    "mcp.describe_get_design": {
        "it": "Il design approvato: alternativa scelta, flussi e schermate con i loro elementi "
        "visibili; con screen una sola schermata con le transizioni da e verso di essa. "
        "Nessuna spesa.",
        "en": "The approved design: chosen alternative, workflows and screens with their "
        "visible elements; with screen only one screen with the transitions from and to it. "
        "No spending.",
    },
    "mcp.title_get_feedback": {
        "it": "Critiche dei twin sul codice",
        "en": "Critiques of the twins on the code",
    },
    "mcp.describe_get_feedback": {
        "it": "Le ultime revisioni dei commit: critiche dei twin con i loro rilievi, verdetto "
        "di allineamento e compiti proposti; con commit solo le revisioni di quel commit. "
        "Nessuna spesa.",
        "en": "The latest reviews of the commits: critiques of the twins with their findings, "
        "alignment verdict and proposed tasks; with commit only the reviews of that commit. "
        "No spending.",
    },
    "mcp.title_ask_twin": {"it": "Domanda a un User Twin", "en": "Ask a User Twin"},
    "mcp.describe_ask_twin": {
        "it": "Fa una domanda a un User Twin nello Studio e restituisce la risposta simulata "
        "dal modello: un'ipotesi da valutare, non l'opinione di una persona reale. A "
        "pagamento, circa {amount} USD a domanda.",
        "en": "Ask a User Twin a question in the Studio and return the answer simulated by the "
        "model: a hypothesis to weigh, not the opinion of a real person. Paid, about {amount} "
        "USD per question.",
    },
    "mcp.title_review_changes": {"it": "Revisione di un commit", "en": "Review of a commit"},
    "mcp.describe_review_changes": {
        "it": "Registra un commit nello Studio (HEAD se non indicato) e lo fa criticare dai "
        "twin, con il verdetto di allineamento al design e ai requisiti approvati. A "
        "pagamento, circa {review} USD per twin più {alignment} USD per il verdetto. La "
        "decisione resta al proprietario del progetto, con `ut align`.",
        "en": "Record a commit in the Studio (HEAD when not given) and have the twins criticize "
        "it, with the verdict of alignment with the approved design and requirements. Paid, "
        "about {review} USD per twin plus {alignment} USD for the verdict. The decision stays "
        "with the owner of the project, through `ut align`.",
    },
    "mcp.describe_review_changes_plain": {
        "it": "Registra un commit nello Studio (HEAD se non indicato) e lo fa criticare dai "
        "twin, con il verdetto di allineamento al design e ai requisiti approvati. A "
        "pagamento. La decisione resta al proprietario del progetto, con `ut align`.",
        "en": "Record a commit in the Studio (HEAD when not given) and have the twins criticize "
        "it, with the verdict of alignment with the approved design and requirements. Paid. "
        "The decision stays with the owner of the project, through `ut align`.",
    },
    "mcp.title_get_test_results": {
        "it": "Esiti dei test di accettazione",
        "en": "Outcome of the acceptance tests",
    },
    "mcp.describe_get_test_results": {
        "it": "Le ultime esecuzioni dei test di accettazione sull'applicazione in sviluppo, lette "
        "dalla cartella di conoscenza: stato di ogni criterio, esito di ogni percorso in ogni "
        "browser e critiche dei twin. Nessuna spesa.",
        "en": "The latest runs of the acceptance tests on the application under development, "
        "read from the knowledge folder: status of every criterion, outcome of every path in "
        "every browser and the critiques of the twins. No spending.",
    },
    "mcp.title_run_tests": {
        "it": "Verifica dei criteri di accettazione",
        "en": "Check of the acceptance criteria",
    },
    "mcp.describe_run_tests": {
        "it": "Apre l'applicazione in sviluppo nei browser di questo computer, verifica i "
        "criteri di accettazione approvati lungo percorsi scritti dal modello, registra l'esito "
        "nello Studio e lo fa criticare dai twin. A pagamento.",
        "en": "Open the application under development in the browsers of this computer, check "
        "the approved acceptance criteria along paths written by the model, record the outcome "
        "in the Studio and have the twins criticize it. Paid.",
    },
    "mcp.describe_run_tests_estimate": {
        "it": "Circa {plan} USD per un nuovo piano dei test e {review} USD per twin per le "
        "critiche.",
        "en": "About {plan} USD for a new test plan and {review} USD per twin for the critiques.",
    },
    "mcp.title_get_tasks": {"it": "Compiti per il codice", "en": "Tasks for the code"},
    "mcp.describe_get_tasks": {
        "it": "I compiti per il codice letti dalla cartella di conoscenza: il testo, i requisiti, "
        "le schermate e i criteri che riguardano, da dove vengono (una critica di un twin su un "
        "commit o sui test, la decisione su un commit, oppure il proprietario) e il loro stato; "
        "con status all anche quelli fatti o lasciati cadere. Nessuna spesa.",
        "en": "The tasks for the code read from the knowledge folder: the text, the "
        "requirements, screens and criteria they are about, where they come from (a critique of "
        "a twin on a commit or on the tests, the decision on a commit, or the owner) and their "
        "status; with status all also the ones done or dropped. No spending.",
    },
    "mcp.describe_disabled": {
        "it": "Ora non disponibile: il server è stato avviato senza --spend.",
        "en": "Not available now: the server was started without --spend.",
    },
    "mcp.parameter_twin": {
        "it": "Numero del twin come in list_twins, oppure l'inizio del suo nome.",
        "en": "Number of the twin as in list_twins, or the beginning of its name.",
    },
    "mcp.parameter_question": {
        "it": "La domanda per il twin, al massimo 1000 caratteri.",
        "en": "The question for the twin, at most 1000 characters.",
    },
    "mcp.parameter_codes": {
        "it": "Codici da cercare, REQ, USR, AC, NED, SCN o JRN; senza codici, tutto.",
        "en": "Codes to look for, REQ, USR, AC, NED, SCN or JRN; without codes, everything.",
    },
    "mcp.parameter_screen": {
        "it": "Codice di una schermata del design scelto, per esempio SCR-002.",
        "en": "Code of a screen of the chosen design, for example SCR-002.",
    },
    "mcp.parameter_feedback_commit": {
        "it": "Hash di un commit, almeno 7 caratteri: solo le revisioni di quel commit.",
        "en": "Hash of a commit, at least 7 characters: only the reviews of that commit.",
    },
    "mcp.parameter_limit": {
        "it": "Quante revisioni dare, dalla più recente: da 1 a 20, di solito 3.",
        "en": "How many reviews to give, newest first: 1 to 20, usually 3.",
    },
    "mcp.parameter_review_commit": {
        "it": "Hash del commit da rivedere, almeno 7 caratteri; senza, HEAD.",
        "en": "Hash of the commit to review, at least 7 characters; without it, HEAD.",
    },
    "mcp.parameter_test_limit": {
        "it": "Quante esecuzioni dei test dare, dalla più recente: da 1 a 20, di solito 1.",
        "en": "How many runs of the tests to give, newest first: 1 to 20, usually 1.",
    },
    "mcp.parameter_application": {
        "it": "L'applicazione da verificare: kind URL con l'indirizzo, oppure kind STATIC con la "
        "cartella dell'applicazione costruita, che contiene index.html; senza, quella "
        "dell'esecuzione precedente.",
        "en": "The application to check: kind URL with the address, or kind STATIC with the "
        "folder of the built application, which holds index.html; without it, the one of the "
        "previous run.",
    },
    "mcp.parameter_browser": {
        "it": "Il browser da usare: chrome, firefox oppure all per tutti quelli trovati; di "
        "solito all.",
        "en": "The browser to use: chrome, firefox, or all for every one found; usually all.",
    },
    "mcp.parameter_criteria": {
        "it": "Codici dei criteri di accettazione da verificare, per esempio AC-003; senza, tutti.",
        "en": "Codes of the acceptance criteria to check, for example AC-003; without them, all.",
    },
    "mcp.parameter_review": {
        "it": "Se i twin devono criticare l'esito dei test, a pagamento; di solito sì.",
        "en": "Whether the twins criticize the outcome of the tests, paid; usually yes.",
    },
    "mcp.parameter_new_plan": {
        "it": "Se chiedere allo Studio un nuovo piano dei test, a pagamento, invece di riusare "
        "quello salvato; di solito no.",
        "en": "Whether to ask the Studio for a new test plan, paid, instead of using the saved "
        "one again; usually no.",
    },
    "mcp.parameter_task_status": {
        "it": "Quali compiti dare: open per quelli aperti, all per tutti; di solito open.",
        "en": "Which tasks to give: open for the open ones, all for every task; usually open.",
    },
    "mcp.next_no_folder": {
        "it": "Qui non c'è ancora la cartella di conoscenza: continua con `ut init` oppure, se "
        "il brief è già approvato, scaricala con `ut package publish`.",
        "en": "The knowledge folder is not here yet: go on with `ut init` or, if the brief is "
        "already approved, download it with `ut package publish`.",
    },
    "mcp.next_stage": {
        "it": "Il prossimo passo da approvare è «{stage}»: continua con {command}.",
        "en": 'The next step to approve is "{stage}": go on with {command}.',
    },
    "mcp.next_no_state": {
        "it": "Il design è approvato, ma questa cartella non ha lo stato dello sviluppo: "
        "scarica la versione nuova con `ut package publish`, poi dopo i commit lancia "
        "`ut align`.",
        "en": "The design is approved, but this folder has no development state: download the "
        "new version with `ut package publish`, then after the commits launch `ut align`.",
    },
    "mcp.next_start": {
        "it": "Il design è approvato e nessun commit è ancora registrato: sviluppa il codice, "
        "poi lancia `ut align` per far rivedere i commit ai twin.",
        "en": "The design is approved and no commit is recorded yet: develop the code, then "
        "launch `ut align` to have the twins review the commits.",
    },
    "mcp.next_pending": {
        "it": "Commit dopo il punto allineato ancora da rivedere o decidere: {count}. Lancia "
        "`ut align`.",
        "en": "Commits after the aligned point still to review or decide: {count}. Launch "
        "`ut align`.",
    },
    "mcp.next_tasks": {
        "it": "Compiti aperti per il codice: {count} ({codes}). Realizzali, fai il commit, poi "
        "lancia `ut align`.",
        "en": "Open tasks for the code: {count} ({codes}). Carry them out, commit, then launch "
        "`ut align`.",
    },
    "mcp.next_aligned": {
        "it": "Il codice è allineato al design approvato al commit {commit}: continua a "
        "sviluppare e lancia `ut align` dopo i prossimi commit.",
        "en": "The code is aligned with the approved design at the commit {commit}: go on "
        "developing and launch `ut align` after the next commits.",
    },
    "mcp.next_undecided": {
        "it": "Ci sono commit registrati, ma nessuno è ancora segnato come allineato: lancia "
        "`ut align` per decidere.",
        "en": "Commits are recorded, but none is marked as aligned yet: launch `ut align` to "
        "decide.",
    },
    "mcp.errors.PROJECT_NOT_LINKED": {
        "it": "Questa cartella non è collegata a un progetto dello Studio, quindi il server MCP "
        "non ha una cartella di conoscenza da offrire. Avvialo dalla cartella del progetto, "
        "oppure con --project-dir, o crea il progetto con `ut init`.",
        "en": "This folder is not linked to a project of the Studio, so the MCP server has no "
        "knowledge folder to offer. Start it from the folder of the project, or with "
        "--project-dir, or create the project with `ut init`.",
    },
    "mcp.errors.SPEND_REQUIRED": {
        "it": "Lo strumento {tool} spende sul modello, ma il server è stato avviato senza "
        "--spend. Per permetterlo avvia il server con `ut mcp --spend`; per Claude Code: "
        "`claude mcp add orchestwin-twins -- ut mcp --spend`.",
        "en": "The tool {tool} spends on the model, but the server was started without "
        "--spend. To allow it, start the server with `ut mcp --spend`; for Claude Code: "
        "`claude mcp add orchestwin-twins -- ut mcp --spend`.",
    },
    "mcp.errors.FOLDER_MISSING": {
        "it": "La cartella di conoscenza {path} non c'è ancora: dopo l'approvazione del brief "
        "scaricala con `ut package publish`.",
        "en": "The knowledge folder {path} is not there yet: once the brief is approved, "
        "download it with `ut package publish`.",
    },
    "mcp.errors.FOLDER_UNREADABLE": {
        "it": "La cartella di conoscenza non si legge ({path}): scaricala di nuovo con "
        "`ut package pull`.",
        "en": "The knowledge folder cannot be read ({path}): download it again with "
        "`ut package pull`.",
    },
    "mcp.errors.FOLDER_SCHEMA_UNSUPPORTED": {
        "it": "La cartella di conoscenza usa uno schema che questa versione di ut non conosce "
        "({version}): aggiorna ut oppure scarica di nuovo la cartella con `ut package pull`.",
        "en": "The knowledge folder uses a schema that this version of ut does not know "
        "({version}): update ut or download the folder again with `ut package pull`.",
    },
    "mcp.errors.STAGE_NOT_APPROVED": {
        "it": "Il passo «{stage}» non è ancora approvato, quindi la cartella di conoscenza non "
        "lo contiene: continua con {command}.",
        "en": 'The step "{stage}" is not approved yet, so the knowledge folder does not hold '
        "it: go on with {command}.",
    },
    "mcp.errors.TWIN_NOT_FOUND": {
        "it": "Nessun twin corrisponde a «{value}». I twin sono: {twins}.",
        "en": 'No twin matches "{value}". The twins are: {twins}.',
    },
    "mcp.errors.TWIN_AMBIGUOUS": {
        "it": "Più twin corrispondono a «{value}»: {twins}. Indica il numero.",
        "en": 'More than one twin matches "{value}": {twins}. Give the number.',
    },
    "mcp.errors.SCREEN_NOT_FOUND": {
        "it": "Il design scelto non ha la schermata {screen}. Schermate: {screens}.",
        "en": "The chosen design has no screen {screen}. Screens: {screens}.",
    },
    "mcp.errors.TWINS_NOT_APPROVED": {
        "it": "I twin di questo progetto non sono approvati nello Studio, oppure sono rimasti "
        "indietro: aggiornali con `ut sections update` o confermali con `ut init`, poi riprova.",
        "en": "The twins of this project are not approved in the Studio, or they fell behind: "
        "update them with `ut sections update` or confirm them with `ut init`, then try again.",
    },
    "mcp.errors.TWIN_ANSWER_FAILED": {
        "it": "{name} non ha potuto rispondere: il modello non ha dato una risposta valida "
        "oppure non era raggiungibile ({code}). Puoi rifare la domanda, ma è una nuova spesa.",
        "en": "{name} could not answer: the model gave no valid answer or could not be reached "
        "({code}). You can ask the question again, but it is a new spending.",
    },
    "mcp.errors.TWIN_CHAT_MODEL_NOT_CONFIGURED": {
        "it": "Il modello che dà voce ai twin non è collegato allo Studio: chi gestisce lo "
        "Studio può collegarlo.",
        "en": "The model that plays the twins is not connected to the Studio: whoever runs the "
        "Studio can connect it.",
    },
    "mcp.errors.TWIN_CONVERSATION_CHANGED": {
        "it": "Nel frattempo la conversazione con il twin è cambiata, forse dalla pagina dello "
        "Studio: rifai la domanda.",
        "en": "The conversation with the twin changed in the meantime, perhaps from the page "
        "of the Studio: ask the question again.",
    },
    "mcp.errors.TWIN_CONVERSATION_FULL": {
        "it": "La conversazione con questo twin è piena: non accetta altre domande. Puoi "
        "chiedere agli altri twin del progetto.",
        "en": "The conversation with this twin is full: it takes no more questions. You can "
        "ask the other twins of the project.",
    },
    "mcp.errors.TWIN_QUESTION_INVALID": {
        "it": "Lo Studio non accetta questa domanda: riscrivila con parole semplici, in al "
        "massimo 1000 caratteri.",
        "en": "The Studio does not accept this question: write it again with plain words, in "
        "at most 1000 characters.",
    },
    "mcp.errors.USER_TWIN_NOT_FOUND": {
        "it": "Questo twin non è più tra i twin del progetto: scarica di nuovo la cartella con "
        "`ut package pull` e guarda l'elenco con list_twins.",
        "en": "This twin is no longer among the twins of the project: download the folder "
        "again with `ut package pull` and see the list with list_twins.",
    },
    "mcp.errors.NO_GIT_REPOSITORY": {
        "it": "La cartella {folder} non è dentro un repository git: i twin possono rivedere "
        "solo commit di un repository.",
        "en": "The folder {folder} is not inside a git repository: the twins can review only "
        "commits of a repository.",
    },
    "mcp.errors.GIT_NOT_AVAILABLE": {
        "it": "Il programma git non si trova su questo computer: installalo per far rivedere "
        "i commit.",
        "en": "The git program is not found on this computer: install it to have the commits "
        "reviewed.",
    },
    "mcp.errors.NO_COMMIT": {
        "it": "Il repository non ha ancora nessun commit da rivedere.",
        "en": "The repository has no commit to review yet.",
    },
    "mcp.errors.COMMIT_NOT_FOUND": {
        "it": "Il commit {commit} non è nel repository, oppure non è tra gli ultimi {limit} "
        "commit del ramo corrente.",
        "en": "The commit {commit} is not in the repository, or it is not among the latest "
        "{limit} commits of the current branch.",
    },
    "mcp.errors.GIT_FAILED": {
        "it": "Il programma git non ha potuto leggere il repository: {detail}.",
        "en": "The git program could not read the repository: {detail}.",
    },
    "mcp.errors.GIT_COMMIT_UNKNOWN": {
        "it": "Il repository non ha il commit {commit}.",
        "en": "The repository does not have the commit {commit}.",
    },
    "mcp.errors.CHANGE_REVIEW_MODEL_NOT_CONFIGURED": {
        "it": "I twin non possono rivedere il codice su questo Studio, perché non ha un "
        "modello collegato; il commit resta registrato. Chi gestisce lo Studio può "
        "collegarne uno.",
        "en": "The twins cannot review the code on this Studio, because it has no model "
        "connected; the commit stays recorded. Whoever runs the Studio can connect one.",
    },
    "mcp.errors.REQUIREMENTS_APPROVAL_REQUIRED": {
        "it": "Per rivedere un commit servono i requisiti approvati: approvali con `ut init`.",
        "en": "Reviewing a commit needs approved requirements: approve them with `ut init`.",
    },
    "mcp.errors.DESIGN_APPROVAL_REQUIRED": {
        "it": "Per rivedere un commit serve il design approvato: approvalo con `ut design`.",
        "en": "Reviewing a commit needs an approved design: approve it with `ut design`.",
    },
    "mcp.errors.USER_MODELING_APPROVAL_REQUIRED": {
        "it": "Per rivedere un commit servono i twin approvati: confermali con `ut init`.",
        "en": "Reviewing a commit needs approved twins: confirm them with `ut init`.",
    },
    "mcp.errors.INVALID_PROVIDER_OUTPUT": {
        "it": "Il modello ha risposto in un modo che lo Studio non può usare, quindi la "
        "revisione non è stata salvata. Puoi riprovare, ma è una nuova spesa.",
        "en": "The model answered in a way the Studio cannot use, so the review was not "
        "saved. You can try again, but it is a new spending.",
    },
    "mcp.errors.RESPONSE_SCHEMA_ERROR": {
        "it": "Il modello ha risposto due volte in una forma sbagliata, quindi la revisione "
        "non è stata salvata. Puoi riprovare, ma è una nuova spesa.",
        "en": "The model answered twice in a wrong form, so the review was not saved. You can "
        "try again, but it is a new spending.",
    },
    "mcp.errors.INCOMPLETE_OUTPUT": {
        "it": "Il modello ha interrotto la risposta due volte, quindi la revisione non è stata "
        "salvata. Puoi riprovare, ma è una nuova spesa.",
        "en": "The model cut its answer short twice, so the review was not saved. You can try "
        "again, but it is a new spending.",
    },
    "mcp.errors.CONTEXT_BUDGET_EXCEEDED": {
        "it": "Il commit con il design e i requisiti è troppo grande perché il modello lo "
        "rivegga: dividi il lavoro in commit più piccoli.",
        "en": "The commit together with the design and the requirements is too large for the "
        "model to review: split the work into smaller commits.",
    },
    "mcp.errors.GENERATION_STILL_RUNNING": {
        "it": "La revisione continua nello Studio: richiama review_changes con lo stesso "
        "commit più tardi per leggerla.",
        "en": "The review goes on in the Studio: call review_changes again later with the "
        "same commit to read it.",
    },
    "mcp.errors.GENERATION_LOST": {
        "it": "La revisione si è persa, forse perché lo Studio è ripartito. Puoi richiamare "
        "review_changes, ma è una nuova spesa.",
        "en": "The review was lost, perhaps because the Studio restarted. You can call "
        "review_changes again, but it is a new spending.",
    },
    "mcp.errors.TEST_DESIGN_REQUIRED": {
        "it": "I test di accettazione richiedono i requisiti e il design approvati nella "
        "cartella di conoscenza: approvali con `ut init` e `ut design`, poi scarica di nuovo la "
        "cartella con `ut package pull`.",
        "en": "The acceptance tests need the approved requirements and design in the knowledge "
        "folder: approve them with `ut init` and `ut design`, then download the folder again "
        "with `ut package pull`.",
    },
    "mcp.errors.TEST_APPLICATION_REQUIRED": {
        "it": "Non so ancora quale applicazione verificare: richiama run_tests con application, "
        "kind URL e l'indirizzo, oppure kind STATIC e la cartella dell'applicazione costruita; "
        "le esecuzioni successive la ricordano.",
        "en": "No application to check is known yet: call run_tests again with application, "
        "kind URL and the address, or kind STATIC and the folder of the built application; the "
        "next runs remember it.",
    },
    "mcp.errors.TEST_STATIC_INVALID": {
        "it": "La cartella dell'applicazione non esiste oppure non contiene index.html: indica "
        "la cartella con l'applicazione costruita.",
        "en": "The folder of the application does not exist or holds no index.html: give the "
        "folder with the built application.",
    },
    "mcp.errors.TEST_NO_BROWSER": {
        "it": "Su questo computer non trovo nessun browser: installa Google Chrome, Chromium, "
        "Microsoft Edge oppure Mozilla Firefox, oppure indica il programma con "
        "ORCHESTWIN_CHROME o ORCHESTWIN_FIREFOX.",
        "en": "No browser was found on this computer: install Google Chrome, Chromium, "
        "Microsoft Edge or Mozilla Firefox, or name the program with ORCHESTWIN_CHROME or "
        "ORCHESTWIN_FIREFOX.",
    },
    "mcp.errors.TEST_MODEL_NOT_CONFIGURED": {
        "it": "Questo Studio non ha un modello collegato, quindi non può scrivere un nuovo piano "
        "dei test; un piano già salvato su questo computer si esegue ancora con new_plan "
        "false. Chi gestisce lo Studio può collegare un modello.",
        "en": "This Studio has no model connected, so it cannot write a new test plan; a plan "
        "already saved on this computer still runs with new_plan false. Whoever runs the "
        "Studio can connect a model.",
    },
    "mcp.errors.TEST_CRITERION_UNKNOWN": {
        "it": "Alcuni codici di criteria non sono criteri del piano dei test: usa i codici che "
        "elenca get_requirements, per esempio AC-001.",
        "en": "Some codes in criteria are not criteria of the test plan: use the codes that "
        "get_requirements lists, for example AC-001.",
    },
    "mcp.errors.TEST_PLAN_NOT_FOUND": {
        "it": "Il piano dei test salvato su questo computer non è più nello Studio: richiama "
        "run_tests con new_plan true, che è una nuova spesa.",
        "en": "The test plan saved on this computer is no longer in the Studio: call run_tests "
        "again with new_plan true, which is a new spending.",
    },
    "mcp.errors.ACCEPTANCE_CRITERION_UNKNOWN": {
        "it": "Lo Studio non conosce alcuni dei criteri indicati: scarica di nuovo la cartella "
        "con `ut package pull` e usa i codici che elenca get_requirements.",
        "en": "The Studio does not know some of the criteria given: download the folder again "
        "with `ut package pull` and use the codes that get_requirements lists.",
    },
    "mcp.errors.BROWSER_NOT_FOUND": {
        "it": "Il browser indicato non è installato su questo computer: scegline un altro con "
        "browser, oppure all.",
        "en": "The browser given is not installed on this computer: choose another with "
        "browser, or all.",
    },
    "mcp.errors.BROWSER_NOT_STARTED": {
        "it": "Il browser {program} non è partito: controlla che si apra su questo computer, "
        "oppure scegline un altro con browser.",
        "en": "The browser {program} did not start: check that it opens on this computer, or "
        "choose another with browser.",
    },
    "mcp.errors.BROWSER_PROTOCOL_ERROR": {
        "it": "La comunicazione con il browser si è interrotta: riprova; se succede ancora, "
        "scegli l'altro browser con browser.",
        "en": "The conversation with the browser broke off: try again; if it happens again, "
        "choose the other browser with browser.",
    },
    "mcp.errors.PAGE_NOT_LOADED": {
        "it": "L'applicazione non si è aperta nel browser: controlla che l'indirizzo risponda, "
        "oppure che la cartella contenga index.html, poi riprova.",
        "en": "The application did not open in the browser: check that the address answers, or "
        "that the folder holds index.html, then try again.",
    },
    "mcp.errors.ACTION_FAILED": {
        "it": "Il browser non ha potuto eseguire un passo dei test: riprova, oppure chiedi un "
        "nuovo piano con new_plan true, che è una nuova spesa.",
        "en": "The browser could not carry out a step of the tests: try again, or ask for a new "
        "plan with new_plan true, which is a new spending.",
    },
    "mcp.errors.run_tests.REQUIREMENTS_APPROVAL_REQUIRED": {
        "it": "Per verificare l'applicazione servono i requisiti approvati nello Studio: "
        "approvali con `ut init`.",
        "en": "Checking the application needs approved requirements in the Studio: approve "
        "them with `ut init`.",
    },
    "mcp.errors.run_tests.DESIGN_APPROVAL_REQUIRED": {
        "it": "Per verificare l'applicazione serve il design approvato nello Studio: approvalo "
        "con `ut design`.",
        "en": "Checking the application needs an approved design in the Studio: approve it "
        "with `ut design`.",
    },
    "mcp.errors.run_tests.USER_MODELING_APPROVAL_REQUIRED": {
        "it": "I twin possono criticare i test solo quando sono approvati: confermali con "
        "`ut init`, oppure richiama run_tests con review false.",
        "en": "The twins can criticize the tests only once they are approved: confirm them "
        "with `ut init`, or call run_tests again with review false.",
    },
    "mcp.errors.run_tests.INVALID_PROVIDER_OUTPUT": {
        "it": "Il modello ha risposto in un modo che lo Studio non può usare, quindi il piano dei "
        "test o le critiche non sono stati salvati. Puoi riprovare, ma è una nuova spesa.",
        "en": "The model answered in a way the Studio cannot use, so the test plan or the "
        "critiques were not saved. You can try again, but it is a new spending.",
    },
    "mcp.errors.run_tests.RESPONSE_SCHEMA_ERROR": {
        "it": "Il modello ha risposto due volte in una forma sbagliata, quindi il piano dei test "
        "o le critiche non sono stati salvati. Puoi riprovare, ma è una nuova spesa.",
        "en": "The model answered twice in a wrong form, so the test plan or the critiques were "
        "not saved. You can try again, but it is a new spending.",
    },
    "mcp.errors.run_tests.INCOMPLETE_OUTPUT": {
        "it": "Il modello ha interrotto la risposta due volte, quindi il piano dei test o le "
        "critiche non sono stati salvati. Puoi riprovare, ma è una nuova spesa.",
        "en": "The model cut its answer short twice, so the test plan or the critiques were not "
        "saved. You can try again, but it is a new spending.",
    },
    "mcp.errors.run_tests.CONTEXT_BUDGET_EXCEEDED": {
        "it": "La pagina insieme al design e ai requisiti è troppo grande per il modello: "
        "verifica meno criteri alla volta con criteria.",
        "en": "The page together with the design and the requirements is too large for the "
        "model: check fewer criteria at a time with criteria.",
    },
    "mcp.errors.run_tests.GENERATION_STILL_RUNNING": {
        "it": "Il modello sta ancora lavorando nello Studio: richiama run_tests fra qualche "
        "minuto.",
        "en": "The model is still working in the Studio: call run_tests again in a few minutes.",
    },
    "mcp.errors.run_tests.GENERATION_LOST": {
        "it": "La generazione si è persa, forse perché lo Studio è ripartito. Puoi richiamare "
        "run_tests, ma è una nuova spesa.",
        "en": "The generation was lost, perhaps because the Studio restarted. You can call "
        "run_tests again, but it is a new spending.",
    },
}
