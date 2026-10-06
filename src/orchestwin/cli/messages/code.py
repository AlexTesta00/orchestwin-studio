from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "code.help": {
        "it": "Affida lo sviluppo a un agente di programmazione esterno (Claude Code o un tuo "
        "comando), con la cartella di conoscenza come contesto e i compiti aperti come ordine di "
        "lavoro",
        "en": "Hand the development to an external coding agent (Claude Code or a command of "
        "yours), with the knowledge folder as context and the open tasks as work order",
    },
    "code.option_request": {
        "it": "quello che chiedi all'agente, con parole tue (facoltativo)",
        "en": "what you ask the agent, in your own words (optional)",
    },
    "code.option_task": {
        "it": "codici dei compiti aperti da svolgere, separati da virgole o spazi; senza "
        "l'opzione e senza richiesta, tutti i compiti aperti",
        "en": "codes of the open tasks to carry out, separated by commas or spaces; without the "
        "option and without a request, every open task",
    },
    "code.option_agent": {
        "it": "l'agente: claude (Claude Code, il predefinito) o custom (il tuo --command); la "
        "scelta resta per le volte successive",
        "en": "the agent: claude (Claude Code, the default) or custom (your --command); the "
        "choice is kept for the next runs",
    },
    "code.option_command": {
        "it": "il comando di un agente custom; le sue parole possono contenere {prompt_file}, "
        "{prompt_line}, {mcp_config} e {project}; resta per le volte successive",
        "en": "the command of a custom agent; its words may hold {prompt_file}, {prompt_line}, "
        "{mcp_config} and {project}; it is kept for the next runs",
    },
    "code.option_model": {
        "it": "il modello di Claude Code (per esempio opus); resta per le volte successive, un "
        "nome vuoto torna al modello predefinito",
        "en": "the model of Claude Code (for example opus); it is kept for the next runs, an "
        "empty name goes back to the default model",
    },
    "code.option_headless": {
        "it": "avvia Claude Code senza conversazione: lavora da solo, applica le sue modifiche "
        "ai file senza chiedere e termina da solo",
        "en": "start Claude Code without a conversation: it works alone, applies its edits to "
        "the files without asking and ends by itself",
    },
    "code.option_max_agent_usd": {
        "it": "con --headless: quanto al massimo Claude Code può spendere in questa esecuzione "
        "sul tuo account, in USD",
        "en": "with --headless: the most Claude Code may spend in this run on your account, in USD",
    },
    "code.option_spend": {
        "it": "lascia all'agente gli strumenti a pagamento del server MCP (domande ai twin, "
        "revisioni, test), che spendono nello Studio",
        "en": "let the agent use the paid tools of the MCP server (questions to the twins, "
        "reviews, tests), which spend in the Studio",
    },
    "code.option_dry_run": {
        "it": "scrive l'ordine di lavoro e mostra la riga di comando senza avviare l'agente",
        "en": "write the work order and show the command line without starting the agent",
    },
    "code.heading": {
        "it": "Agente di programmazione per «{name}»",
        "en": 'Coding agent for "{name}"',
    },
    "code.agent_claude": {
        "it": "Agente: Claude Code ({program}).",
        "en": "Agent: Claude Code ({program}).",
    },
    "code.agent_custom": {
        "it": "Agente: il tuo comando ({program}).",
        "en": "Agent: your command ({program}).",
    },
    "code.mode_interactive": {
        "it": "Modalità: interattiva, l'agente parla con te in questo terminale finché non lo "
        "chiudi.",
        "en": "Mode: interactive, the agent talks with you in this terminal until you close it.",
    },
    "code.mode_headless": {
        "it": "Modalità: senza conversazione, l'agente lavora da solo e termina da solo.",
        "en": "Mode: headless, the agent works alone and ends by itself.",
    },
    "code.mode_headless_claude": {
        "it": "Modalità: senza conversazione, Claude Code lavora da solo, applica le sue "
        "modifiche ai file senza chiedere e termina da solo.",
        "en": "Mode: headless, Claude Code works alone, applies its edits to the files without "
        "asking and ends by itself.",
    },
    "code.model": {
        "it": "Modello: {model}.",
        "en": "Model: {model}.",
    },
    "code.budget": {
        "it": "Spesa massima dell'agente in questa esecuzione: {usd} USD, sul tuo account di "
        "Claude Code.",
        "en": "The most the agent may spend in this run: {usd} USD, on your Claude Code account.",
    },
    "code.work_tasks": {
        "it": "Lavoro: i compiti {codes}.",
        "en": "Work: the tasks {codes}.",
    },
    "code.work_all_tasks": {
        "it": "Lavoro: tutti i compiti aperti della cartella di conoscenza ({codes}).",
        "en": "Work: every open task of the knowledge folder ({codes}).",
    },
    "code.work_request": {
        "it": "Lavoro: la tua richiesta.",
        "en": "Work: your request.",
    },
    "code.work_tasks_request": {
        "it": "Lavoro: i compiti {codes} e la tua richiesta.",
        "en": "Work: the tasks {codes} and your request.",
    },
    "code.work_build": {
        "it": "Lavoro: costruire l'applicazione come la descrivono i requisiti e il design "
        "approvati.",
        "en": "Work: build the application as the approved requirements and design describe.",
    },
    "code.order": {
        "it": "Ordine di lavoro: {path}",
        "en": "Work order: {path}",
    },
    "code.own_account": {
        "it": "L'agente lavora con il tuo account di quell'agente: quello che spende è fuori dai "
        "tetti di spesa dello Studio, che non lo conta.",
        "en": "The agent works with your own account of that agent: what it spends is outside "
        "the spending ceilings of the Studio, which does not count it.",
    },
    "code.own_account_spend": {
        "it": "L'agente lavora con il tuo account di quell'agente: quello che spende è fuori dai "
        "tetti di spesa dello Studio. Può anche fare domande ai twin e far eseguire revisioni e "
        "test attraverso lo Studio, che spende entro i suoi tetti.",
        "en": "The agent works with your own account of that agent: what it spends is outside "
        "the spending ceilings of the Studio. It may also ask the twins and have reviews and "
        "tests run through the Studio, which spends within its ceilings.",
    },
    "code.confirm": {
        "it": "Avvio l'agente adesso?",
        "en": "Start the agent now?",
    },
    "code.starting": {
        "it": "Avvio {program}: il terminale è dell'agente finché non termina.",
        "en": "Starting {program}: the terminal belongs to the agent until it ends.",
    },
    "code.words": {
        "it": "Riga di comando dell'agente, una parola per riga:",
        "en": "Command line of the agent, one word per line:",
    },
    "code.dry_run": {
        "it": "Prova senza avvio: l'agente non è partito. L'ordine di lavoro e la configurazione "
        "MCP restano in {folder}.",
        "en": "Dry run: the agent was not started. The work order and the MCP configuration "
        "stay in {folder}.",
    },
    "code.ended": {
        "it": "L'agente ha terminato dopo {elapsed}.",
        "en": "The agent ended after {elapsed}.",
    },
    "code.ended_status": {
        "it": "L'agente ha terminato con lo stato {status} dopo {elapsed}: guarda nel terminale "
        "qui sopra che cosa è successo.",
        "en": "The agent ended with the status {status} after {elapsed}: see in the terminal "
        "above what happened.",
    },
    "code.changed": {
        "it": "File con modifiche non ancora registrate in un commit ({count}):",
        "en": "Files with changes not committed yet ({count}):",
    },
    "code.changed_more": {
        "it": "... e altri {count}: l'elenco completo è in {path}.",
        "en": "... and {count} more: the whole list is in {path}.",
    },
    "code.changed_none": {
        "it": "Nessun file ha modifiche non ancora registrate in un commit.",
        "en": "No file has changes that are not committed yet.",
    },
    "code.changes_no_git": {
        "it": "Non posso elencare i file cambiati: questa cartella non è in un repository git, "
        "oppure git manca. `ut verify` ha bisogno di un repository git (`git init`).",
        "en": "The changed files cannot be listed: this folder is not in a git repository, or "
        "git is missing. `ut verify` needs a git repository (`git init`).",
    },
    "code.changes_failed": {
        "it": "Non posso elencare i file cambiati: git ha risposto {detail}.",
        "en": "The changed files cannot be listed: git answered {detail}.",
    },
    "code.knowledge_touched": {
        "it": "Attenzione: l'agente ha cambiato la cartella di conoscenza {folder}/, che non va "
        "modificata a mano: `ut package pull` la ripristina.",
        "en": "Warning: the agent changed the knowledge folder {folder}/, which must not be "
        "edited: `ut package pull` restores it.",
    },
    "code.next_steps": {
        "it": "Prossimi passi: guarda le modifiche e registrale in un commit; `ut test` verifica "
        "i criteri di accettazione sull'applicazione; con `ut verify` i twin esaminano il commit "
        "e il modello dice se codice, Definizione e Design sono allineati; decidi tu.",
        "en": "Next steps: look at the changes and commit them; `ut test` verifies the "
        "acceptance criteria on the application; with `ut verify` the twins review the commit "
        "and the model says whether code, Definition and Design are aligned; you decide.",
    },
    "code.next_steps_failed": {
        "it": "L'ordine di lavoro e la configurazione MCP restano in {folder}. Rilancia `ut code` "
        "quando vuoi.",
        "en": "The work order and the MCP configuration stay in {folder}. Launch `ut code` again "
        "whenever you want.",
    },
    "code.errors.CODE_DESIGN_REQUIRED": {
        "it": "La cartella di conoscenza locale non contiene il design approvato "
        "(CODE_DESIGN_REQUIRED): approvalo con `ut design`, poi scarica la cartella con "
        "`ut package pull`.",
        "en": "The local knowledge folder does not hold the approved design "
        "(CODE_DESIGN_REQUIRED): approve it with `ut design`, then download the folder with "
        "`ut package pull`.",
    },
    "code.errors.CODE_TASK_UNKNOWN": {
        "it": "Questi codici non sono compiti aperti nella cartella di conoscenza locale: "
        "{codes} (CODE_TASK_UNKNOWN). `ut tasks` mostra i compiti aperti; `ut package pull` "
        "porta nella cartella quelli più recenti.",
        "en": "These codes are not open tasks of the local knowledge folder: {codes} "
        "(CODE_TASK_UNKNOWN). `ut tasks` shows the open tasks; `ut package pull` brings the "
        "latest ones into the folder.",
    },
    "code.errors.CODE_AGENT_NOT_FOUND": {
        "it": "Non trovo Claude Code (CODE_AGENT_NOT_FOUND): installalo, oppure indica il suo "
        "programma con la variabile {variable}, oppure avvia un altro agente con "
        "`--agent custom --command`.",
        "en": "Claude Code cannot be found (CODE_AGENT_NOT_FOUND): install it, or name its "
        "program with the variable {variable}, or start another agent with "
        "`--agent custom --command`.",
    },
    "code.errors.CODE_AGENT_NOT_STARTED": {
        "it": "L'agente {program} non è partito: {detail} (CODE_AGENT_NOT_STARTED).",
        "en": "The agent {program} did not start: {detail} (CODE_AGENT_NOT_STARTED).",
    },
    "code.errors.CODE_COMMAND_REQUIRED": {
        "it": "L'agente custom ha bisogno del suo comando (CODE_COMMAND_REQUIRED): indicalo con "
        '--command, per esempio --command "mio-agente {prompt_file}".',
        "en": "The custom agent needs its command (CODE_COMMAND_REQUIRED): give it with "
        '--command, for example --command "my-agent {prompt_file}".',
    },
    "code.errors.CODE_COMMAND_INVALID": {
        "it": "Il comando dell'agente custom non si può usare (CODE_COMMAND_INVALID): controlla "
        "le parole date con --command.",
        "en": "The command of the custom agent cannot be used (CODE_COMMAND_INVALID): check the "
        "words given with --command.",
    },
    "code.errors.CODE_COMMAND_INVALID.EMPTY": {
        "it": "Il comando dell'agente custom è vuoto (CODE_COMMAND_INVALID): indica con "
        "--command il programma e le sue parole.",
        "en": "The command of the custom agent is empty (CODE_COMMAND_INVALID): give the "
        "program and its words with --command.",
    },
    "code.errors.CODE_COMMAND_INVALID.QUOTES": {
        "it": "Nel comando dell'agente custom una virgoletta non si chiude "
        "(CODE_COMMAND_INVALID): correggi il testo dato con --command.",
        "en": "A quotation mark in the command of the custom agent is never closed "
        "(CODE_COMMAND_INVALID): correct the text given with --command.",
    },
    "code.errors.CODE_COMMAND_INVALID.PLACEHOLDER": {
        "it": "Il comando dell'agente custom contiene {placeholder}, che ut non conosce "
        "(CODE_COMMAND_INVALID): le sue parole possono contenere solo {prompt_file}, "
        "{prompt_line}, {mcp_config} e {project}.",
        "en": "The command of the custom agent holds {placeholder}, which ut does not know "
        "(CODE_COMMAND_INVALID): its words may hold only {prompt_file}, {prompt_line}, "
        "{mcp_config} and {project}.",
    },
    "code.errors.CODE_COMMAND_NEEDS_CUSTOM": {
        "it": "L'opzione --command vale per l'agente custom (CODE_COMMAND_NEEDS_CUSTOM): "
        "aggiungi --agent custom, oppure togli --agent.",
        "en": "The option --command is for the custom agent (CODE_COMMAND_NEEDS_CUSTOM): add "
        "--agent custom, or leave out --agent.",
    },
    "code.errors.CODE_BUDGET_NEEDS_HEADLESS": {
        "it": "--max-agent-usd vale solo con --headless e l'agente claude "
        "(CODE_BUDGET_NEEDS_HEADLESS): Claude Code accetta un tetto di spesa solo quando lavora "
        "da solo.",
        "en": "--max-agent-usd works only with --headless and the agent claude "
        "(CODE_BUDGET_NEEDS_HEADLESS): Claude Code accepts a spending ceiling only when it "
        "works alone.",
    },
    "code.errors.CODE_MAX_USD_INVALID": {
        "it": "--max-agent-usd vuole un importo maggiore di 0, per esempio 2.50 "
        "(CODE_MAX_USD_INVALID).",
        "en": "--max-agent-usd needs an amount above 0, for example 2.50 (CODE_MAX_USD_INVALID).",
    },
    "code.errors.SPENDING_REFUSED": {
        "it": "L'agente non è partito: non hai confermato.",
        "en": "The agent was not started: you did not confirm.",
    },
    "code.errors.INPUT_CLOSED": {
        "it": "L'input si è chiuso prima della risposta: l'agente non è partito.",
        "en": "The input closed before the answer: the agent was not started.",
    },
}
