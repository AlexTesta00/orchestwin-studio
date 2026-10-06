"use strict";

const LANGUAGES = Object.freeze(["en", "it"]);

const MONTHS = Object.freeze({
  en: Object.freeze([
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ]),
  it: Object.freeze([
    "gen",
    "feb",
    "mar",
    "apr",
    "mag",
    "giu",
    "lug",
    "ago",
    "set",
    "ott",
    "nov",
    "dic",
  ]),
});

const MESSAGES = Object.freeze({
  en: Object.freeze({
    "workflow.title": "Supplied inputs and declared gaps",
    "workflow.invalid": "The workflow records cannot be verified. Download the Dossier again.",
    "workflow.filter": "Show",
    "workflow.all": "All inputs",
    "workflow.gaps": "Declared gaps",
    "workflow.owner": "Owner supplied",
    "workflow.missing": "Missing, declared by you",
    "workflow.resolved": "Gap resolved by you",
    "workflow.supplied": "Supplied prototype",
    "workflow.origin": "Declared origin",
    "why.gap.DECLARED_MISSING": "Missing, declared by you",
    "workflow.limit.PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE": "Synthetic review is unavailable for a supplied prototype.",
    "workflow.limit.PROVIDED_PROTOTYPE_CODE_UNAVAILABLE": "Code generation is unavailable for a supplied prototype.",
    "workflow.limit.PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE": "Scenario walkthrough is unavailable for a supplied prototype.",
    "workflow.limit.PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE": "This operation is unavailable for a supplied prototype.",
    "workflow.limit.PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE": "Twin evaluation is unavailable for a supplied prototype. The mockup structure is preserved for a future integration.",
    "validation.title": "Evaluation and validation",
    "validation.readOnly": "Read candidates, operational hypotheses and outcomes here. Complete hypotheses and record outcomes in Studio web or API. Session notes use ut evidence.",
    "validation.readLocal": "Read verified local Dossier",
    "validation.readStudio": "Read from Studio",
    "validation.readFrom": "Read from",
    "validation.offline": "From the verified local Dossier, without network or login. Its data may predate Studio; omitted sections remain explicit.",
    "validation.studio": "Read from Studio through ut, using the existing sign-in. No generation or validation writes.",
    "validation.loading": "Reading validation data…",
    "validation.unavailable": "The ut program could not be started. Check its configured path.",
    "validation.folderUnverified": "The local Dossier could not be verified. Check it with ut package verify before reading validation data.",
    "validation.invalid": "Enter a scenario code or exact selector, an optional alternative and a valid document hash.",
    "validation.failed": "Validation data could not be read. Check the project with ut validation --json.",
    "validation.candidates": "Candidates to verify",
    "validation.candidateNote": "Candidates remain derived. Only your selection and completed question or task become a saved operational hypothesis.",
    "validation.candidateDetails": "Show candidate details",
    "validation.operational": "Operational hypotheses",
    "validation.operationalHypothesis": "Operational hypothesis",
    "validation.noHypotheses": "No operational hypothesis recorded.",
    "validation.questionOrTask": "Question or task",
    "validation.observe": "What to observe",
    "validation.outcomes": "Outcomes",
    "validation.outcomeHistory": "Outcome history and exact sources",
    "validation.empiricalSummary": "Active outcomes by session type",
    "validation.session.HUMAN_SESSION": "Session with people",
    "validation.session.SYNTHETIC_EXERCISE": "Synthetic exercise, not empirical",
    "validation.state.TO_VERIFY": "To verify",
    "validation.state.CONFIRMED": "Confirmed",
    "validation.state.REFUTED": "Refuted",
    "validation.state.UNCERTAIN": "Uncertain",
    "validation.state.CONTESTED": "Conflicting outcomes",
    "validation.partial": "Partial evidence",
    "validation.retired": "Retired outcome",
    "validation.previous": "Previous version",
    "validation.linkToComplete": "Link to complete",
    "validation.sourceWithoutText": "Source without original text",
    "validation.referenceUnavailable": "The exact reference is unavailable in this context.",
    "validation.stepsUnavailable": "The original scenario steps are unavailable in this context.",
    "validation.taskUnavailable": "The original scenario task is unavailable in this context.",
    "validation.provenance": "Provenance, versions and hashes",
    "validation.source": "Source",
    "validation.hypothesisVersion": "Exact hypothesis version",
    "validation.origin": "Origin",
    "validation.twins": "User Twins",
    "validation.scenarios": "Scenarios",
    "validation.design": "Design references",
    "validation.omitted": "Omitted sections",
    "validation.noPromotion": "Outcomes do not automatically promote twin claims. Synthetic exercises do not validate hypotheses with people.",
    "validation.gapDetails": "Exact link details",
    "validation.walkthrough": "Scenario walkthrough",
    "validation.scenarioSelect": "Select a local scenario",
    "validation.scenarioKey": "Scenario code or exact selector",
    "validation.alternativeOptional": "Alternative identifier (optional)",
    "validation.documentHashOptional": "Mockup document hash (optional)",
    "validation.expected": "Expected outcome",
    "validation.anchorCandidates": "Elements relevant to the scenario",
    "validation.anchorNote": "These elements are candidates for the scenario. A link to an individual step is shown only when it is recorded.",
    "validation.softwareLimit": "Software navigation is not an observation with people.",
    "why.stage.brief": "Project brief",
    "why.stage.twins": "User Twin",
    "why.stage.design": "Design & Evaluation",
    "why.title": "Why?",
    "why.intro":
      "Select an artifact to read its chain from the verified Dossier.",
    "why.code": "Artifact code or exact selector",
    "why.select": "Select an artifact",
    "why.legacy":
      "This Dossier has no exported chain. Enter a code to recalculate it from the available data.",
    "why.invalidCatalog":
      "The exported artifact list cannot be read. The command will verify the Dossier before showing a chain.",
    "why.offline":
      "From the verified local Dossier. Omitted sections cannot be explained here.",
    "why.upstream": "Where it comes from",
    "why.downstream": "What depends on it",
    "why.validation": "To verify with real people",
    "why.context": "Declared context",
    "why.gaps": "Interrupted chain",
    "why.model": "Model-generated rationale",
    "why.owner": "Owner rationale",
    "why.system": "System rationale",
    "why.unknownOrigin": "Rationale with undeclared origin",
    "why.missing": "Data for this link is missing",
    "why.retired": "Retired source",
    "why.noRationale": "No rationale recorded",
    "why.noItems": "No links recorded",
    "why.noValidation": "No human validation requirement recorded",
    "why.synthetic":
      "Synthetic finding. An owner decision does not validate it with real people.",
    "why.modelRef": "Model configuration",
    "why.observation": "Claim",
    "why.abstained": "Abstained",
    "why.promptRef": "Prompt version",
    "why.gap.MISSING_NEED": "No linked need recorded",
    "why.gap.MISSING_SCENARIO": "No linked scenario recorded",
    "why.gap.MISSING_TWIN": "The exact twin reference is missing",
    "why.gap.MISSING_CLAIM": "The exact claim reference is missing",
    "why.gap.MISSING_SOURCE": "No linked source recorded",
    "why.gap.MISSING_SOURCE_VERSION": "The exact source version is missing",
    "why.gap.MISSING_RATIONALE": "No rationale recorded",
    "why.gap.SOURCE_RETIRED": "Retired source",
    "why.gap.SOURCE_TEXT_UNAVAILABLE":
      "The original source text is unavailable; preserved citations remain readable",
    "why.gap.OMITTED_SECTION": "This section was omitted from the Dossier",
    "why.gap.CONTEXT_OUTDATED": "This artifact uses an earlier context",
    "why.references": "Exact references",
    "why.details": "Rationale, references and citations",
    "why.baseReference": "Generation context",
    "why.auditReference": "Recorded generation",
    "why.requestHash": "Request content hash",
    "why.mockup": "Mockup",
    "why.alternative": "Alternative",
    "why.screen": "Screen",
    "why.LATEST": "Latest generation",
    "why.APPLIED": "Applied generation",
    "why.relations": "Recorded links",
    "why.limits": "Limits",
    "why.current": "Current version",
    "why.historical": "Historical version",
    "why.completeTwin": "Reaches a twin",
    "why.completeEvidence": "Reaches active evidence",
    "why.allPaths": "All paths reach active evidence",
    "why.yes": "Yes",
    "why.no": "No",
    "why.loading": "Reading the chain…",
    "why.failed":
      "The chain could not be read. Check the Dossier with ut why --offline.",
    "why.unavailable":
      "The ut program could not be started. Check its configured path.",
    "why.invalid": "The code or chain is invalid for this project.",
    "why.ambiguous": "Choose the exact artifact version or context.",
    "why.EVIDENCED": "Evidenced",
    "why.INFERRED": "Inferred",
    "why.HYPOTHESIZED": "Hypothesized",
    "why.CONTESTED": "Contested",
    "why.UNKNOWN": "Unknown",
    "panel.title": "OrchesTwin Studio",
    "panel.eyebrow": "OrchesTwin project",
    "panel.noFolder": "No folder open",
    "panel.unlinkedEyebrow": "Folder not linked",
    "panel.error":
      "The panel cannot show this project: see where it stands in the terminal (`ut status`).",
    "header.folderVersion": "Knowledge folder version {version}",
    "header.folderPublished":
      "Knowledge folder version {version}, published on {date}",
    "header.folderMissing": "The knowledge folder ({folder}/) is not here yet.",
    "header.folderBroken": "The knowledge folder ({folder}/) cannot be read.",
    "header.steps": "Steps of the project",
    "header.partial":
      "The design is not approved yet: the development starts after the design is approved.",
    "stage.brief": "Brief",
    "stage.team": "Perspectives",
    "stage.twins": "User Twin",
    "stage.requirements": "Definition",
    "stage.design": "Design & Evaluation",
    "stage.approved": "approved",
    "stage.pending": "not approved yet",
    "notice.label": "Files the panel could not read",
    "notice.INVALID_JSON": "{file} is not valid JSON: the panel skips it.",
    "notice.UNREADABLE": "{file} cannot be read: the panel skips it.",
    "notice.UNEXPECTED":
      "{file} does not hold what the panel expects: the panel skips it.",
    "next.title": "Next step",
    "next.noFolder":
      "Open the folder of an OrchesTwin project in the editor. To start a new project, launch `ut init` in the terminal of that folder.",
    "next.notLinked":
      "This folder is not linked to an OrchesTwin project yet: launch `ut init` in the terminal to create the project and link the folder.",
    "next.folderMissing":
      "The knowledge folder is not here yet: see where the project stands.",
    "next.folderBroken":
      "Some files of the knowledge folder cannot be read: download the folder again.",
    "next.init":
      "The next step to approve is “{stage}”: the guided path starts again from the first step not approved.",
    "next.design":
      "The requirements are approved: choose and approve the design. The development starts after it.",
    "next.recheck": [
      "One review was made on an earlier version of the design or of the requirements: have the twins review that commit again.",
      "{count} reviews were made on an earlier version of the design or of the requirements: have the twins review those commits again.",
    ],
    "next.code": [
      "One task for the code is open: start the coding agent on it.",
      "{count} tasks for the code are open: start the coding agent on them.",
    ],
    "next.tasksFromTest": [
      "One criterion failed or was blocked in the latest test run: choose which findings of the twins become tasks for the code.",
      "{count} criteria failed or were blocked in the latest test run: choose which findings of the twins become tasks for the code.",
    ],
    "next.align": [
      "One proposal from the code waits for a decision: decide it with `ut align --pending`.",
      "{count} proposals from the code wait for a decision: decide them with `ut align --pending`.",
    ],
    "next.verify": [
      "One commit came after the aligned point: have it reviewed by the twins and decide what to do.",
      "{count} commits came after the aligned point: have them reviewed by the twins and decide what to do.",
    ],
    "next.firstTest":
      "No test run yet: verify the acceptance criteria on your application in the browsers.",
    "next.test":
      "Commits and tasks are in order: verify the acceptance criteria again after your next change.",
    "action.status": "Show where the project stands",
    "action.init": "Continue the guided path",
    "action.design": "Work on the design",
    "action.publish": "Download the knowledge folder again",
    "action.test": "Verify the acceptance criteria",
    "action.verify": "Have the twins review the commits",
    "action.recheck": "Review the commits again",
    "action.align": "Align the knowledge to the code",
    "action.alignPending": "Decide the proposals from the code",
    "action.code": "Start the coding agent",
    "action.tasks": "List the tasks",
    "action.tasksFromTest": "Turn findings into tasks",
    "action.twinsUpdate": "Let the twins learn",
    "action.openReport": "Open the report",
    "action.connectAgents": "Connect the twins to the agents of the editor",
    "cost.SPENDS": "may spend: the terminal asks first",
    "cost.AGENT": "the agent works on your own account",
    "cost.FREE": "free",
    "detail.openReport": "opens in your browser",
    "detail.connectAgents": "writes .vscode/mcp.json · free",
    "part.unavailable":
      "Not available yet: download the knowledge folder again (`ut package publish`).",
    "development.title": "Development",
    "development.notYet":
      "The commits, the tasks for the code and the acceptance tests appear here once the design is approved.",
    "development.aligned": "Aligned commit",
    "development.noAligned": "none yet",
    "development.pending": "Pending commits",
    "development.stale": "To re-review",
    "development.none": "none",
    "development.reference": "Reference",
    "development.referenceValue":
      "requirements v{requirements} · design v{design}",
    "development.direction": "Visual direction",
    "development.latest": "Latest commit",
    "development.noCommits":
      "No commit recorded yet: after your first commit, have it reviewed by the twins (`ut verify`).",
    "knowledge.title": "Knowledge",
    "knowledge.run": "Last run",
    "knowledge.commits": "from {from} to {to}",
    "knowledge.upTo": "up to {to}",
    "knowledge.proposals": "Proposals",
    "knowledge.waiting": "Waiting for a decision",
    "verdict.NONE": "Not reviewed yet",
    "verdict.ALIGNED": "Aligned",
    "verdict.CODE_DRIFT": "The code should change",
    "verdict.DESIGN_OUTDATED": "The design should change",
    "verdict.REQUIREMENTS_OUTDATED": "The requirements should change",
    "decision.ALIGNED": "Decision: aligned point",
    "decision.DESIGN_CHANGE": "Decision: new design asked",
    "decision.REQUIREMENTS_CHANGE": "Decision: requirements change asked",
    "decision.CODE_TASKS": "Decision: tasks for the code",
    "decision.DISMISSED": "Decision: nothing to do",
    "chip.stale": "To re-review",
    "tasks.title": "Tasks for the code",
    "tasks.none": "No open task.",
    "tasks.open": ["{count} open", "{count} open"],
    "tasks.done": ["{count} done", "{count} done"],
    "tasks.dropped": ["{count} dropped", "{count} dropped"],
    "tasks.more": [
      "One more open task: `ut tasks` lists them all.",
      "{count} more open tasks: `ut tasks` lists them all.",
    ],
    "origin.twinCommit": "From {twin}, on commit {commit}",
    "origin.verdictCommit": "From the decision on commit {commit}",
    "origin.twinTestCriteria": [
      "From {twin}, on a test run, criterion {criteria}",
      "From {twin}, on a test run, criteria {criteria}",
    ],
    "origin.twinTest": "From {twin}, on a test run",
    "origin.testRun": "From a test run",
    "origin.owner": "Written by you",
    "code.title": "Latest work of the coding agent",
    "code.when": "When",
    "code.agent": "Agent",
    "code.agent.claude": "Claude Code",
    "code.agent.custom": "your own command",
    "code.outcome": "Outcome",
    "code.exitOk": "Finished without errors",
    "code.exitStatus": "Ended with status {status}",
    "code.files": "Files changed",
    "tests.title": "Acceptance tests",
    "tests.none":
      "No test run yet: the tests open your application in the browsers and verify the acceptance criteria (`ut test`).",
    "tests.latest": "Latest run",
    "tests.browsers": "Browsers",
    "tests.local": "Read from this computer: not in the knowledge folder yet.",
    "tests.counts": "Criteria by outcome",
    "tests.PASSED": ["{count} passed", "{count} passed"],
    "tests.FAILED": ["{count} failed", "{count} failed"],
    "tests.BLOCKED": ["{count} blocked", "{count} blocked"],
    "tests.NOT_COVERED": ["{count} not covered", "{count} not covered"],
    "tests.NOT_RUN": ["{count} not run", "{count} not run"],
    "tests.problems": "Failed or blocked",
    "tests.statementMissing": "text not available",
    "tests.moreProblems": [
      "One more criterion is in the report.",
      "{count} more criteria are in the report.",
    ],
    "tests.reviewed": "Reviewed by the twins on {date}",
    "tests.reviewedUndated": "Reviewed by the twins",
    "tests.notReviewed": "The twins have not reviewed this run yet.",
    "tests.stale":
      "This run was made on an earlier version of the design or of the requirements: verify again.",
    "status.PASSED": "Passed",
    "status.FAILED": "Failed",
    "status.BLOCKED": "Blocked",
    "twins.title": "Twins",
    "twins.notYet":
      "The twins are not approved yet: the guided path gets to them (`ut init`).",
    "twins.none": "No twin in the approved user modeling.",
    "twins.version": "version {label}",
    "twins.onCommit": "On commit {commit}",
    "twins.onTest": "On the test run of {date}",
    "twins.noCommit": "No commit reviewed yet",
    "twins.noTest": "No test run reviewed yet",
    "twins.learned": [
      "Learned one thing during the development",
      "Learned {count} things during the development",
    ],
    "twins.learnedNone": "Nothing learned during the development yet",
    "twins.evidence": "Evidence references",
    "twins.evidenceLimit":
      "Approved quotations, without original documents. Owner approval is not empirical research or human validation.",
    "critique.FINE": "No concerns",
    "critique.CONCERN": "Some concerns",
    "critique.DRIFT": "Off course",
    "source.TWIN_CRITIQUE": "from its critiques",
    "source.OWNER": "written by you",
    "agents.title": "Agents of the editor",
    "agents.intro":
      "The agents of the editor that use MCP, for example Copilot in agent mode, can read the project and ask the twins through the server of OrchesTwin (`orchestwin-twins`). The server starts without spending: the paid questions stay off.",
    "agents.CONNECTED": "Connected in .vscode/mcp.json",
    "agents.NOT_CONNECTED": "Not connected yet",
    "agents.MISSING": "Not connected yet",
    "agents.INVALID":
      ".vscode/mcp.json is not valid JSON: the panel does not overwrite it",
    "agents.UNREADABLE":
      ".vscode/mcp.json cannot be read: the panel does not overwrite it",
    "footer.note":
      "The panel reads the files of this folder: it never calls the Studio and never spends. Why? reads the Dossier with ut why --offline. Development commands run in the terminal, where ut asks before any paid step.",
    "status.sent": "Written in the terminal: {command}",
    "status.noFolder": "Open the folder of a project first.",
    "status.noReport": "No report yet: the tests write it (`ut test`).",
    "status.reportOpened": "Report opened in your browser.",
    "status.reportFailed": "The report could not be opened.",
    "status.connect.CREATED":
      "Created .vscode/mcp.json with the server of the twins (orchestwin-twins).",
    "status.connect.UPDATED":
      "Added the server of the twins (orchestwin-twins) to .vscode/mcp.json.",
    "status.connect.UNCHANGED":
      ".vscode/mcp.json already has the server of the twins (orchestwin-twins).",
    "status.connect.INVALID":
      ".vscode/mcp.json is not valid JSON: the panel left it as it is. Fix it, or add the server that `ut mcp --config vscode` prints.",
    "status.connect.UNREADABLE":
      ".vscode/mcp.json cannot be read: the panel left it as it is. Add the server that `ut mcp --config vscode` prints.",
    "status.connect.FAILED": ".vscode/mcp.json could not be written.",
  }),
  it: Object.freeze({
    "workflow.title": "Contenuti forniti e lacune dichiarate",
    "workflow.invalid": "I record del flusso non sono verificabili. Scarica di nuovo il Dossier.",
    "workflow.filter": "Mostra",
    "workflow.all": "Tutti i contenuti",
    "workflow.gaps": "Lacune dichiarate",
    "workflow.owner": "Fornito dal proprietario",
    "workflow.missing": "Manca, dichiarato da te",
    "workflow.resolved": "Lacuna risolta da te",
    "workflow.supplied": "Prototipo fornito",
    "workflow.origin": "Origine dichiarata",
    "why.gap.DECLARED_MISSING": "Manca, dichiarato da te",
    "workflow.limit.PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE": "La revisione sintetica non è disponibile per il prototipo fornito.",
    "workflow.limit.PROVIDED_PROTOTYPE_CODE_UNAVAILABLE": "La generazione del codice non è disponibile per il prototipo fornito.",
    "workflow.limit.PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE": "Il percorso dello scenario non è disponibile per il prototipo fornito.",
    "workflow.limit.PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE": "Questa operazione non è disponibile per il prototipo fornito.",
    "workflow.limit.PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE": "La valutazione dei twin non è disponibile per il prototipo fornito. La struttura dei mockup è conservata per un collegamento futuro.",
    "validation.title": "Valutazione e validazione",
    "validation.readOnly": "Qui leggi candidate, ipotesi operative ed esiti. Compila le ipotesi e registra gli esiti nello Studio web o via API. Per gli appunti di sessione usa ut evidence.",
    "validation.readLocal": "Leggi il Dossier locale verificato",
    "validation.readStudio": "Leggi dallo Studio",
    "validation.readFrom": "Leggi da",
    "validation.offline": "Dal Dossier locale verificato, senza rete o login. I dati possono essere precedenti a Studio; le sezioni omesse restano esplicite.",
    "validation.studio": "Letto dallo Studio tramite ut, con l'accesso già eseguito. Nessuna generazione o scrittura di validazione.",
    "validation.loading": "Lettura dei dati di validazione…",
    "validation.unavailable": "Non è stato possibile avviare ut. Controlla il percorso configurato.",
    "validation.folderUnverified": "Non è stato possibile verificare il Dossier locale. Controllalo con ut package verify prima di leggere i dati di validazione.",
    "validation.invalid": "Inserisci un codice o selettore esatto dello scenario, un'alternativa facoltativa e un hash valido del documento.",
    "validation.failed": "Non è stato possibile leggere i dati di validazione. Controlla il progetto con ut validation --json.",
    "validation.candidates": "Candidate da verificare",
    "validation.candidateNote": "Le candidate restano derivate. Diventa ipotesi operativa salvata solo la tua scelta con domanda o compito completo.",
    "validation.candidateDetails": "Mostra i dettagli delle candidate",
    "validation.operational": "Ipotesi operative",
    "validation.operationalHypothesis": "Ipotesi operativa",
    "validation.noHypotheses": "Nessuna ipotesi operativa registrata.",
    "validation.questionOrTask": "Domanda o compito",
    "validation.observe": "Che cosa osservare",
    "validation.outcomes": "Esiti",
    "validation.outcomeHistory": "Storico degli esiti e fonti esatte",
    "validation.empiricalSummary": "Esiti attivi per tipo di sessione",
    "validation.session.HUMAN_SESSION": "Sessione con persone",
    "validation.session.SYNTHETIC_EXERCISE": "Prova sintetica, non empirica",
    "validation.state.TO_VERIFY": "Da verificare",
    "validation.state.CONFIRMED": "Confermata",
    "validation.state.REFUTED": "Smentita",
    "validation.state.UNCERTAIN": "Incerta",
    "validation.state.CONTESTED": "Esiti in disaccordo",
    "validation.partial": "Evidenza parziale",
    "validation.retired": "Esito ritirato",
    "validation.previous": "Versione precedente",
    "validation.linkToComplete": "Collegamento da completare",
    "validation.sourceWithoutText": "Fonte senza testo originale",
    "validation.referenceUnavailable": "Il riferimento esatto non è disponibile in questo contesto.",
    "validation.stepsUnavailable": "I passi originali dello scenario non sono disponibili in questo contesto.",
    "validation.taskUnavailable": "Il compito originale dello scenario non è disponibile in questo contesto.",
    "validation.provenance": "Provenienza, versioni e hash",
    "validation.source": "Fonte",
    "validation.hypothesisVersion": "Versione esatta dell'ipotesi",
    "validation.origin": "Origine",
    "validation.twins": "User Twin",
    "validation.scenarios": "Scenari",
    "validation.design": "Riferimenti al Design",
    "validation.omitted": "Sezioni omesse",
    "validation.noPromotion": "Gli esiti non promuovono automaticamente i claim del twin. Le prove sintetiche non validano le ipotesi con persone.",
    "validation.gapDetails": "Dettagli esatti dei collegamenti",
    "validation.walkthrough": "Percorso dello scenario",
    "validation.scenarioSelect": "Scegli uno scenario locale",
    "validation.scenarioKey": "Codice o selettore esatto dello scenario",
    "validation.alternativeOptional": "Identificatore dell'alternativa (facoltativo)",
    "validation.documentHashOptional": "Hash del documento mockup (facoltativo)",
    "validation.expected": "Esito atteso",
    "validation.anchorCandidates": "Elementi pertinenti allo scenario",
    "validation.anchorNote": "Questi elementi sono candidati per lo scenario. Il collegamento a un singolo passo si mostra solo quando è registrato.",
    "validation.softwareLimit": "La navigazione software non è un'osservazione con persone.",
    "why.stage.brief": "Brief del progetto",
    "why.stage.twins": "User Twin",
    "why.stage.design": "Design e valutazione",
    "why.title": "Perché?",
    "why.intro":
      "Scegli un artefatto per leggere la sua catena dal Dossier verificato.",
    "why.code": "Codice artefatto o selettore esatto",
    "why.select": "Scegli un artefatto",
    "why.legacy":
      "Questo Dossier non ha la catena esportata. Inserisci un codice per ricalcolarla dai dati disponibili.",
    "why.invalidCatalog":
      "L'elenco degli artefatti esportati non si può leggere. Il comando verificherà il Dossier prima di mostrare una catena.",
    "why.offline":
      "Dal Dossier locale verificato. Le sezioni omesse non si possono spiegare qui.",
    "why.upstream": "Da dove viene",
    "why.downstream": "Che cosa ne dipende",
    "why.validation": "Da verificare con persone vere",
    "why.context": "Contesto dichiarato",
    "why.gaps": "Catena interrotta",
    "why.model": "Motivazione generata dal modello",
    "why.owner": "Motivazione del proprietario",
    "why.system": "Motivazione del sistema",
    "why.unknownOrigin": "Motivazione di origine non dichiarata",
    "why.missing": "Mancano i dati per questo collegamento",
    "why.retired": "Fonte ritirata",
    "why.noRationale": "Nessuna motivazione registrata",
    "why.noItems": "Nessun collegamento registrato",
    "why.noValidation": "Nessuna verifica con persone vere registrata",
    "why.synthetic":
      "Rilievo sintetico. Una decisione del proprietario non lo valida con persone vere.",
    "why.modelRef": "Configurazione del modello",
    "why.observation": "Affermazione",
    "why.abstained": "Astensione",
    "why.promptRef": "Versione del prompt",
    "why.gap.MISSING_NEED": "Nessun bisogno collegato registrato",
    "why.gap.MISSING_SCENARIO": "Nessuno scenario collegato registrato",
    "why.gap.MISSING_TWIN": "Manca il riferimento al twin esatto",
    "why.gap.MISSING_CLAIM": "Manca il riferimento al claim esatto",
    "why.gap.MISSING_SOURCE": "Nessuna fonte collegata registrata",
    "why.gap.MISSING_SOURCE_VERSION": "Manca la versione esatta della fonte",
    "why.gap.MISSING_RATIONALE": "Nessuna motivazione registrata",
    "why.gap.SOURCE_RETIRED": "Fonte ritirata",
    "why.gap.SOURCE_TEXT_UNAVAILABLE":
      "Il testo originale della fonte non è disponibile; le citazioni conservate restano leggibili",
    "why.gap.OMITTED_SECTION": "Questa sezione è stata omessa dal Dossier",
    "why.gap.CONTEXT_OUTDATED": "Questo artefatto usa un contesto precedente",
    "why.references": "Riferimenti esatti",
    "why.details": "Motivazione, riferimenti e citazioni",
    "why.baseReference": "Contesto della generazione",
    "why.auditReference": "Generazione registrata",
    "why.requestHash": "Hash del contenuto della richiesta",
    "why.mockup": "Mockup",
    "why.alternative": "Alternativa",
    "why.screen": "Schermata",
    "why.LATEST": "Ultima generazione",
    "why.APPLIED": "Generazione applicata",
    "why.relations": "Collegamenti registrati",
    "why.limits": "Limiti",
    "why.current": "Versione corrente",
    "why.historical": "Versione storica",
    "why.completeTwin": "Arriva a un twin",
    "why.completeEvidence": "Arriva a evidenza attiva",
    "why.allPaths": "Tutti i percorsi arrivano a evidenza attiva",
    "why.yes": "Sì",
    "why.no": "No",
    "why.loading": "Lettura della catena…",
    "why.failed":
      "La catena non si può leggere. Controlla il Dossier con ut why --offline.",
    "why.unavailable":
      "Il programma ut non si avvia. Controlla il percorso configurato.",
    "why.invalid": "Il codice o la catena non sono validi per questo progetto.",
    "why.ambiguous": "Scegli la versione o il contesto esatto dell'artefatto.",
    "why.EVIDENCED": "Documentato",
    "why.INFERRED": "Dedotto",
    "why.HYPOTHESIZED": "Ipotizzato",
    "why.CONTESTED": "Contestato",
    "why.UNKNOWN": "Sconosciuto",
    "panel.title": "OrchesTwin Studio",
    "panel.eyebrow": "Progetto OrchesTwin",
    "panel.noFolder": "Nessuna cartella aperta",
    "panel.unlinkedEyebrow": "Cartella non collegata",
    "panel.error":
      "Il pannello non riesce a mostrare questo progetto: guarda a che punto è nel terminale (`ut status`).",
    "header.folderVersion": "Cartella di conoscenza versione {version}",
    "header.folderPublished":
      "Cartella di conoscenza versione {version}, pubblicata il {date}",
    "header.folderMissing":
      "La cartella di conoscenza ({folder}/) non è ancora qui.",
    "header.folderBroken":
      "La cartella di conoscenza ({folder}/) non si legge.",
    "header.steps": "Passi del progetto",
    "header.partial":
      "Il design non è ancora approvato: lo sviluppo parte dopo l'approvazione del design.",
    "stage.brief": "Brief",
    "stage.team": "Prospettive",
    "stage.twins": "User Twin",
    "stage.requirements": "Definizione",
    "stage.design": "Design e valutazione",
    "stage.approved": "approvato",
    "stage.pending": "non ancora approvato",
    "notice.label": "File che il pannello non ha potuto leggere",
    "notice.INVALID_JSON": "{file} non è un JSON valido: il pannello lo salta.",
    "notice.UNREADABLE": "{file} non si può leggere: il pannello lo salta.",
    "notice.UNEXPECTED":
      "{file} non contiene quello che il pannello si aspetta: il pannello lo salta.",
    "next.title": "Prossimo passo",
    "next.noFolder":
      "Apri nell'editor la cartella di un progetto OrchesTwin. Per iniziare un progetto nuovo, lancia `ut init` nel terminale di quella cartella.",
    "next.notLinked":
      "Questa cartella non è ancora collegata a un progetto OrchesTwin: lancia `ut init` nel terminale per creare il progetto e collegare la cartella.",
    "next.folderMissing":
      "La cartella di conoscenza non è ancora qui: guarda a che punto è il progetto.",
    "next.folderBroken":
      "Alcuni file della cartella di conoscenza non si leggono: scarica di nuovo la cartella.",
    "next.init":
      "Il prossimo passo da approvare è «{stage}»: il percorso guidato riparte dal primo passo non approvato.",
    "next.design":
      "I requisiti sono approvati: scegli e approva il design. Lo sviluppo parte dopo.",
    "next.recheck": [
      "Un esame è stato fatto su una versione precedente del design o dei requisiti: fai riesaminare quel commit ai twin.",
      "{count} esami sono stati fatti su una versione precedente del design o dei requisiti: fai riesaminare quei commit ai twin.",
    ],
    "next.code": [
      "C'è un compito aperto per il codice: avvia l'agente di programmazione su quel compito.",
      "Ci sono {count} compiti aperti per il codice: avvia l'agente di programmazione su quei compiti.",
    ],
    "next.tasksFromTest": [
      "Un criterio è fallito o bloccato nell'ultima verifica: scegli quali osservazioni dei twin diventano compiti per il codice.",
      "{count} criteri sono falliti o bloccati nell'ultima verifica: scegli quali osservazioni dei twin diventano compiti per il codice.",
    ],
    "next.align": [
      "Una proposta dal codice aspetta una decisione: decidila con `ut align --pending`.",
      "{count} proposte dal codice aspettano una decisione: decidile con `ut align --pending`.",
    ],
    "next.verify": [
      "Un commit è arrivato dopo il punto allineato: fallo esaminare ai twin e decidi che cosa fare.",
      "{count} commit sono arrivati dopo il punto allineato: falli esaminare ai twin e decidi che cosa fare.",
    ],
    "next.firstTest":
      "Nessuna verifica ancora: prova i criteri di accettazione sulla tua applicazione, nei browser.",
    "next.test":
      "Commit e compiti sono in ordine: verifica di nuovo i criteri di accettazione dopo la prossima modifica.",
    "action.status": "Mostra a che punto è il progetto",
    "action.init": "Continua il percorso guidato",
    "action.design": "Lavora sul design",
    "action.publish": "Scarica di nuovo la cartella di conoscenza",
    "action.test": "Verifica i criteri di accettazione",
    "action.verify": "Fai esaminare i commit ai twin",
    "action.recheck": "Riesamina i commit",
    "action.align": "Allinea la conoscenza al codice",
    "action.alignPending": "Decidi le proposte dal codice",
    "action.code": "Avvia l'agente di programmazione",
    "action.tasks": "Elenca i compiti",
    "action.tasksFromTest": "Trasforma le osservazioni in compiti",
    "action.twinsUpdate": "Fai imparare i twin",
    "action.openReport": "Apri il rapporto",
    "action.connectAgents": "Collega i twin agli agenti dell'editor",
    "cost.SPENDS": "può spendere: il terminale chiede prima",
    "cost.AGENT": "l'agente lavora sul tuo account",
    "cost.FREE": "gratis",
    "detail.openReport": "si apre nel browser",
    "detail.connectAgents": "scrive .vscode/mcp.json · gratis",
    "part.unavailable":
      "Non ancora disponibile: scarica di nuovo la cartella di conoscenza (`ut package publish`).",
    "development.title": "Sviluppo",
    "development.notYet":
      "I commit, i compiti per il codice e la verifica dei criteri compaiono qui dopo l'approvazione del design.",
    "development.aligned": "Commit allineato",
    "development.noAligned": "nessuno ancora",
    "development.pending": "Commit in attesa",
    "development.stale": "Da riesaminare",
    "development.none": "nessuno",
    "development.reference": "Riferimento",
    "development.referenceValue":
      "requisiti v{requirements} · design v{design}",
    "development.direction": "Direzione visiva",
    "development.latest": "Ultimo commit",
    "development.noCommits":
      "Nessun commit registrato: dopo il primo commit, fallo esaminare ai twin (`ut verify`).",
    "knowledge.title": "Conoscenza",
    "knowledge.run": "Ultima corsa",
    "knowledge.commits": "da {from} a {to}",
    "knowledge.upTo": "fino a {to}",
    "knowledge.proposals": "Proposte",
    "knowledge.waiting": "In attesa di decisione",
    "verdict.NONE": "Non ancora esaminato",
    "verdict.ALIGNED": "Allineato",
    "verdict.CODE_DRIFT": "Va cambiato il codice",
    "verdict.DESIGN_OUTDATED": "Va aggiornato il design",
    "verdict.REQUIREMENTS_OUTDATED": "Vanno aggiornati i requisiti",
    "decision.ALIGNED": "Decisione: punto allineato",
    "decision.DESIGN_CHANGE": "Decisione: chiesto un nuovo design",
    "decision.REQUIREMENTS_CHANGE":
      "Decisione: chiesta una modifica dei requisiti",
    "decision.CODE_TASKS": "Decisione: compiti per il codice",
    "decision.DISMISSED": "Decisione: niente da fare",
    "chip.stale": "Da riesaminare",
    "tasks.title": "Compiti per il codice",
    "tasks.none": "Nessun compito aperto.",
    "tasks.open": ["{count} aperto", "{count} aperti"],
    "tasks.done": ["{count} fatto", "{count} fatti"],
    "tasks.dropped": ["{count} annullato", "{count} annullati"],
    "tasks.more": [
      "Ancora un compito aperto: `ut tasks` li elenca tutti.",
      "Altri {count} compiti aperti: `ut tasks` li elenca tutti.",
    ],
    "origin.twinCommit": "Da {twin}, sul commit {commit}",
    "origin.verdictCommit": "Dalla decisione sul commit {commit}",
    "origin.twinTestCriteria": [
      "Da {twin}, su una verifica, criterio {criteria}",
      "Da {twin}, su una verifica, criteri {criteria}",
    ],
    "origin.twinTest": "Da {twin}, su una verifica",
    "origin.testRun": "Da una verifica",
    "origin.owner": "Scritto da te",
    "code.title": "Ultimo lavoro dell'agente di programmazione",
    "code.when": "Quando",
    "code.agent": "Agente",
    "code.agent.claude": "Claude Code",
    "code.agent.custom": "il tuo comando",
    "code.outcome": "Esito",
    "code.exitOk": "Finito senza errori",
    "code.exitStatus": "Finito con lo stato {status}",
    "code.files": "File cambiati",
    "tests.title": "Verifica dei criteri",
    "tests.none":
      "Nessuna verifica ancora: i test aprono la tua applicazione nei browser e verificano i criteri di accettazione (`ut test`).",
    "tests.latest": "Ultima verifica",
    "tests.browsers": "Browser",
    "tests.local":
      "Letta da questo computer: non è ancora nella cartella di conoscenza.",
    "tests.counts": "Criteri per esito",
    "tests.PASSED": ["{count} superato", "{count} superati"],
    "tests.FAILED": ["{count} fallito", "{count} falliti"],
    "tests.BLOCKED": ["{count} bloccato", "{count} bloccati"],
    "tests.NOT_COVERED": ["{count} non coperto", "{count} non coperti"],
    "tests.NOT_RUN": ["{count} non eseguito", "{count} non eseguiti"],
    "tests.problems": "Falliti o bloccati",
    "tests.statementMissing": "testo non disponibile",
    "tests.moreProblems": [
      "Un altro criterio è nel rapporto.",
      "Altri {count} criteri sono nel rapporto.",
    ],
    "tests.reviewed": "Commentata dai twin il {date}",
    "tests.reviewedUndated": "Commentata dai twin",
    "tests.notReviewed": "I twin non hanno ancora commentato questa verifica.",
    "tests.stale":
      "Questa verifica è stata fatta su una versione precedente del design o dei requisiti: ripetila.",
    "status.PASSED": "Superato",
    "status.FAILED": "Fallito",
    "status.BLOCKED": "Bloccato",
    "twins.title": "Twin",
    "twins.notYet":
      "I twin non sono ancora approvati: ci arriva il percorso guidato (`ut init`).",
    "twins.none": "Nessun twin nella modellazione degli utenti approvata.",
    "twins.version": "versione {label}",
    "twins.onCommit": "Sul commit {commit}",
    "twins.onTest": "Sulla verifica del {date}",
    "twins.noCommit": "Nessun commit esaminato",
    "twins.noTest": "Nessuna verifica commentata",
    "twins.learned": [
      "Ha imparato una cosa durante lo sviluppo",
      "Ha imparato {count} cose durante lo sviluppo",
    ],
    "twins.learnedNone": "Non ha ancora imparato niente durante lo sviluppo",
    "twins.evidence": "Riferimenti alle evidenze",
    "twins.evidenceLimit":
      "Citazioni approvate, senza documenti originali. L'approvazione del proprietario non è ricerca empirica o validazione umana.",
    "critique.FINE": "Nessun dubbio",
    "critique.CONCERN": "Qualche dubbio",
    "critique.DRIFT": "Fuori strada",
    "source.TWIN_CRITIQUE": "dalle sue critiche",
    "source.OWNER": "scritta da te",
    "agents.title": "Agenti dell'editor",
    "agents.intro":
      "Gli agenti dell'editor che usano MCP, per esempio Copilot in modalità agente, possono leggere il progetto e interpellare i twin attraverso il server di OrchesTwin (`orchestwin-twins`). Il server parte senza spesa: le domande a pagamento restano spente.",
    "agents.CONNECTED": "Collegati in .vscode/mcp.json",
    "agents.NOT_CONNECTED": "Non ancora collegati",
    "agents.MISSING": "Non ancora collegati",
    "agents.INVALID":
      ".vscode/mcp.json non è un JSON valido: il pannello non lo sovrascrive",
    "agents.UNREADABLE":
      ".vscode/mcp.json non si può leggere: il pannello non lo sovrascrive",
    "footer.note":
      "Il pannello legge i file di questa cartella: non chiama mai lo Studio e non spende mai. Perché? legge il Dossier con ut why --offline. I comandi di sviluppo si avviano nel terminale, dove ut chiede conferma prima dei passi a pagamento.",
    "status.sent": "Scritto nel terminale: {command}",
    "status.noFolder": "Apri prima la cartella di un progetto.",
    "status.noReport":
      "Nessun rapporto ancora: lo scrivono i test (`ut test`).",
    "status.reportOpened": "Rapporto aperto nel browser.",
    "status.reportFailed": "Non è stato possibile aprire il rapporto.",
    "status.connect.CREATED":
      "Creato .vscode/mcp.json con il server dei twin (orchestwin-twins).",
    "status.connect.UPDATED":
      "Aggiunto il server dei twin (orchestwin-twins) a .vscode/mcp.json.",
    "status.connect.UNCHANGED":
      ".vscode/mcp.json ha già il server dei twin (orchestwin-twins).",
    "status.connect.INVALID":
      ".vscode/mcp.json non è un JSON valido: il pannello l'ha lasciato com'è. Correggilo, o aggiungi il server che stampa `ut mcp --config vscode`.",
    "status.connect.UNREADABLE":
      ".vscode/mcp.json non si può leggere: il pannello l'ha lasciato com'è. Aggiungi il server che stampa `ut mcp --config vscode`.",
    "status.connect.FAILED": "Non è stato possibile scrivere .vscode/mcp.json.",
  }),
});

function languageOf(value) {
  return typeof value === "string" && value.toLowerCase().startsWith("it")
    ? "it"
    : "en";
}

function template(language, key) {
  const table = MESSAGES[languageOf(language)];
  if (Object.hasOwn(table, key)) {
    return table[key];
  }
  if (Object.hasOwn(MESSAGES.en, key)) {
    return MESSAGES.en[key];
  }
  return key;
}

function fill(pattern, values) {
  return pattern.replace(/\{(\w+)\}/g, (match, name) => {
    if (
      !Object.hasOwn(values, name) ||
      values[name] === null ||
      values[name] === undefined
    ) {
      return match;
    }
    return String(values[name]);
  });
}

function text(language, key, values = {}) {
  const pattern = template(language, key);
  return fill(Array.isArray(pattern) ? pattern[1] : pattern, values);
}

function plural(language, key, count, values = {}) {
  const pattern = template(language, key);
  const form = Array.isArray(pattern) ? pattern[count === 1 ? 0 : 1] : pattern;
  return fill(form, { ...values, count });
}

function twoDigits(value) {
  return String(value).padStart(2, "0");
}

function momentOf(value) {
  if (typeof value !== "string" || value.trim() === "") {
    return null;
  }
  const moment = new Date(value);
  return Number.isNaN(moment.getTime()) ? null : moment;
}

function parts(moment, timeZone) {
  const utc = timeZone === "UTC";
  return {
    day: utc ? moment.getUTCDate() : moment.getDate(),
    month: utc ? moment.getUTCMonth() : moment.getMonth(),
    year: utc ? moment.getUTCFullYear() : moment.getFullYear(),
    hours: utc ? moment.getUTCHours() : moment.getHours(),
    minutes: utc ? moment.getUTCMinutes() : moment.getMinutes(),
  };
}

function formatDay(language, value, options = {}) {
  const moment = momentOf(value);
  if (moment === null) {
    return null;
  }
  const found = parts(moment, options.timeZone);
  return `${found.day} ${MONTHS[languageOf(language)][found.month]} ${found.year}`;
}

function formatDate(language, value, options = {}) {
  const moment = momentOf(value);
  if (moment === null) {
    return null;
  }
  const found = parts(moment, options.timeZone);
  const day = `${found.day} ${MONTHS[languageOf(language)][found.month]} ${found.year}`;
  return `${day}, ${twoDigits(found.hours)}:${twoDigits(found.minutes)}`;
}

module.exports = {
  LANGUAGES,
  MESSAGES,
  MONTHS,
  formatDate,
  formatDay,
  languageOf,
  plural,
  text,
};
