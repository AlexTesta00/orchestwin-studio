export const designPackageCopy = {
  en: {
    agentRole: "Interface developer",
    agentReady:
      "I gathered the five approved steps into a folder ready for your development tools.",
    agentPartial:
      "I gather the steps approved so far into a folder ready for your development tools; the next ones join it when you approve them.",
    agentWaiting:
      "As soon as the brief is approved, I will gather the approved steps into a folder ready for your development tools.",
    eyebrow: "Knowledge folder",
    title: "The project is ready",
    titlePartial: "The folder is taking shape",
    titleWaiting: "The folder is not ready yet",
    intro:
      "The five steps are approved. The folder holds the brief, the perspectives, the twins, the requirements and the chosen design as text, tables and diagrams.",
    introPartial:
      "The folder holds the steps approved so far as text, tables and diagrams. You can prepare it now and again after each approval.",
    introWaiting:
      "The folder will hold the brief, the perspectives, the twins, the requirements and the chosen design as text, tables and diagrams.",
    notReady: "The folder can be prepared as soon as the brief is approved.",
    held: ["{count} of {total} steps", "{count} of {total} steps"],
    partial: [
      "The folder holds {held}: {steps} is still to be approved.",
      "The folder holds {held}: {steps} are still to be approved.",
    ],
    partialRule: "Each step joins the folder when you approve it.",
    prepare: "Prepare and download the folder",
    preparing: "Preparing the folder…",
    latest: "{files} files · version {number}",
    created: "Version {number} of the folder is ready and downloaded: {file}",
    reused:
      "Nothing has changed since version {number}: the same folder was downloaded again: {file}",
    failed: "The folder could not be prepared.",
    downloadFailed: "The folder could not be downloaded.",
    behind:
      "{section} is behind: use “Update and confirm” at the top of the page, then prepare the folder again.",
    behindStep:
      "The {section} step is behind: open it and bring it up to date, then prepare the folder again.",
    perspectivesBehind:
      "The brief changed: prepare the perspectives again, then prepare the folder again.",
    outdated: {
      USER_TWINS_OUTDATED: "User Twin",
      REQUIREMENTS_OUTDATED: "Definition",
      DESIGN_OUTDATED: "Design & Evaluation",
    },
    contents: "What it contains",
    twins: ["twin, in its own reusable file", "twins, each in its own reusable file"],
    diagrams: ["diagram of requirements and design", "diagrams of requirements and design"],
    tables: ["table of requirements and design", "tables of requirements and design"],
    findings: [
      "observation of the twins on the chosen design",
      "observations of the twins on the chosen design",
    ],
    feedback:
      "{reviews} twin reviews · {decisions} decisions of yours · {discussions} approved discussions",
    countedLater: "Diagrams, tables and observations are counted when you prepare the folder.",
    design: "The chosen design",
    noDesign: "The chosen design appears here once Design & Evaluation is approved.",
    noPreview: "No preview",
    path: "The steps and their versions",
    stageVersion: "version {number}",
    noVersion: "no version",
    approved: "approved",
    pending: "pending",
    howTo: "How to use it",
    terminalWay: "From the terminal, with `ut`",
    terminalSteps: {
      login: "Log in to the Studio from the terminal. You need this only once on this computer.",
      folder: "Create an empty folder for the project and go into it.",
      link: "Link the folder to this project: `ut` downloads the knowledge folder here.",
      editor:
        "Open the folder in Visual Studio Code: the OrchesTwin panel shows the state of the project and runs the same commands.",
    },
    developmentWay: "Then, during development",
    developmentSteps: {
      git: "Put the folder under git: `ut verify` works on the commits.",
      code: "Have your coding agent write the application, with the requirements and the design as context.",
      test: "Check the acceptance criteria in the browsers of this computer (with `--url` if the application has an address of its own).",
      verify:
        "The twins review the commits and the model says whether code, Definition and Design are aligned; you decide.",
      align:
        "Reads the code changes and proposes updates to the Definition, the Design and the test plan: you approve them one by one.",
      alignDesign:
        "When the design changes in the Studio after the code exists, bring the code up to the current design: your agent receives a work order limited to what changed.",
      push: "Sends the hand-made changes of the knowledge folder to the Studio: you see the differences, approve them, and a new version is born.",
      learn: "Have the twins propose what they learned from the development.",
      status: "See where the project stands.",
    },
    zipWay: "Without `ut`: download the zip",
    folder: "project",
    copyCommand: "Copy",
    commandCopied: "Copied",
    commandNotCopied: "Could not copy",
    steps: [
      "Download the folder with the button above and extract it into your project, in a folder named orchestwin.",
      "Open ORCHESTWIN.md: it is the index and explains every file.",
      "Build with your own tools. Requirements, screens and elements have stable codes to quote in your work.",
      "When the scope changes, come back to the Studio, approve the new version and download the folder again.",
    ],
    history: "Versions of the folder",
    historyIntro:
      "A new version is created only when something has changed. Every version can be downloaded again exactly as it was. The project's `orchestwin/` folder is the source of truth: hand-made changes come back to the Studio with `ut push` as versions supplied by you.",
    loadingHistory: "Loading the versions…",
    noHistory: "No version has been prepared yet.",
    version: "Version {number}",
    versionMeta: "{date} · {files} files",
    versionNext: "{held}, next: {step}",
    download: "Download",
    downloadVersion: "Download version {number}",
    earlier: "Earlier versions ({count})",
    terminal:
      "Development goes on from the terminal: `ut verify` checks the commits against the design and `ut watch` follows them.",
  },
  it: {
    agentRole: "Sviluppatore dell'interfaccia",
    agentReady:
      "Ho raccolto i cinque passi approvati in una cartella pronta per i tuoi strumenti di sviluppo.",
    agentPartial:
      "Raccolgo i passi approvati finora in una cartella pronta per i tuoi strumenti di sviluppo; i prossimi si aggiungono quando li approvi.",
    agentWaiting:
      "Appena il brief è approvato, raccoglierò i passi approvati in una cartella pronta per i tuoi strumenti di sviluppo.",
    eyebrow: "Cartella di conoscenza",
    title: "Il progetto è pronto",
    titlePartial: "La cartella prende forma",
    titleWaiting: "La cartella non è ancora pronta",
    intro:
      "I cinque passi sono approvati. La cartella raccoglie brief, prospettive, twin, requisiti e design scelto in forma di testo, tabelle e diagrammi.",
    introPartial:
      "La cartella raccoglie i passi approvati finora in forma di testo, tabelle e diagrammi. Puoi prepararla subito e di nuovo dopo ogni approvazione.",
    introWaiting:
      "La cartella raccoglierà brief, prospettive, twin, requisiti e design scelto in forma di testo, tabelle e diagrammi.",
    notReady: "La cartella si può preparare appena il brief è approvato.",
    held: ["{count} passo su {total}", "{count} passi su {total}"],
    partial: [
      "La cartella contiene {held}: resta da approvare {steps}.",
      "La cartella contiene {held}: restano da approvare {steps}.",
    ],
    partialRule: "Ogni passo entra nella cartella quando lo approvi.",
    prepare: "Prepara e scarica la cartella",
    preparing: "Preparo la cartella…",
    latest: "{files} file · versione {number}",
    created: "La versione {number} della cartella è pronta ed è stata scaricata: {file}",
    reused:
      "Non è cambiato nulla dalla versione {number}: ho scaricato di nuovo la stessa cartella: {file}",
    failed: "Non è stato possibile preparare la cartella.",
    downloadFailed: "Non è stato possibile scaricare la cartella.",
    behind:
      "La sezione {section} è rimasta indietro: usa «Aggiorna e conferma» in cima alla pagina, poi prepara di nuovo la cartella.",
    behindStep:
      "Il passo {section} è rimasto indietro: aprilo e aggiornalo, poi prepara di nuovo la cartella.",
    perspectivesBehind:
      "Il brief è cambiato: prepara di nuovo le prospettive, poi prepara di nuovo la cartella.",
    outdated: {
      USER_TWINS_OUTDATED: "User Twin",
      REQUIREMENTS_OUTDATED: "Definizione",
      DESIGN_OUTDATED: "Design e valutazione",
    },
    contents: "Che cosa contiene",
    twins: ["twin, in un file riutilizzabile", "twin, ciascuno in un file riutilizzabile"],
    diagrams: ["diagramma di requisiti e design", "diagrammi di requisiti e design"],
    tables: ["tabella di requisiti e design", "tabelle di requisiti e design"],
    findings: [
      "osservazione dei twin sul design scelto",
      "osservazioni dei twin sul design scelto",
    ],
    feedback:
      "{reviews} revisioni dei twin · {decisions} tue decisioni · {discussions} discussioni approvate",
    countedLater: "Diagrammi, tabelle e osservazioni si contano quando prepari la cartella.",
    design: "Il design scelto",
    noDesign: "Il design scelto compare qui dopo l'approvazione di Design e valutazione.",
    noPreview: "Nessuna anteprima",
    path: "I passi e le loro versioni",
    stageVersion: "versione {number}",
    noVersion: "nessuna versione",
    approved: "approvato",
    pending: "in attesa",
    howTo: "Come usarla",
    terminalWay: "Dal terminale, con `ut`",
    terminalSteps: {
      login: "Accedi allo Studio dal terminale. Serve una volta sola su questo computer.",
      folder: "Crea una cartella vuota per il progetto ed entraci.",
      link: "Collega la cartella a questo progetto: `ut` scarica qui la cartella di conoscenza.",
      editor:
        "Apri la cartella in Visual Studio Code: il pannello OrchesTwin mostra lo stato del progetto e lancia gli stessi comandi.",
    },
    developmentWay: "Poi, durante lo sviluppo",
    developmentSteps: {
      git: "Metti la cartella sotto git: `ut verify` lavora sui commit.",
      code: "Fai scrivere l'applicazione al tuo agente di programmazione, con requisiti e design come contesto.",
      test: "Verifica i criteri di accettazione nei browser di questo computer (con `--url` se l'applicazione ha un suo indirizzo).",
      verify:
        "I twin esaminano i commit e il modello dice se codice, Definizione e Design sono allineati; decidi tu.",
      align:
        "Legge le modifiche del codice e propone aggiornamenti alla Definizione, al Design e al piano dei test: li approvi uno per uno.",
      alignDesign:
        "Quando il design cambia nello Studio dopo che il codice esiste, porta il codice al design attuale: il tuo agente riceve un ordine di lavoro limitato a ciò che è cambiato.",
      push: "Invia allo Studio le modifiche fatte a mano nella cartella di conoscenza: vedi le differenze, le approvi e nasce una versione nuova.",
      learn: "Fai proporre ai twin che cosa hanno imparato dallo sviluppo.",
      status: "Guarda a che punto è il progetto.",
    },
    zipWay: "Senza `ut`: scarica lo zip",
    folder: "progetto",
    copyCommand: "Copia",
    commandCopied: "Copiato",
    commandNotCopied: "Copia non riuscita",
    steps: [
      "Scarica la cartella con il pulsante qui sopra ed estraila nel tuo progetto, in una cartella chiamata orchestwin.",
      "Apri ORCHESTWIN.md: è l'indice e spiega ogni file.",
      "Realizza il progetto con i tuoi strumenti. Requisiti, schermate ed elementi hanno codici stabili da citare nel lavoro.",
      "Quando lo scopo cambia, torna nello Studio, approva la nuova versione e scarica di nuovo la cartella.",
    ],
    history: "Versioni della cartella",
    historyIntro:
      "Una nuova versione nasce solo quando cambia qualcosa. Ognuna si riscarica esattamente com'era. La cartella `orchestwin/` del progetto è la fonte di verità: le modifiche fatte a mano tornano nello Studio con `ut push` come versioni fornite da te.",
    loadingHistory: "Carico le versioni…",
    noHistory: "Non hai ancora preparato nessuna versione.",
    version: "Versione {number}",
    versionMeta: "{date} · {files} file",
    versionNext: "{held}, il prossimo è {step}",
    download: "Scarica",
    downloadVersion: "Scarica la versione {number}",
    earlier: "Versioni precedenti ({count})",
    terminal:
      "Lo sviluppo continua dal terminale: `ut verify` confronta i commit con il design e `ut watch` li segue.",
  },
} as const;

export const designPackageSectionCopy = {
  en: {
    agentReady:
      "I gathered the five approved sections into a folder ready for your development tools.",
    agentPartial:
      "I gather the sections approved so far into a folder ready for your development tools; the next ones join it when you approve them.",
    agentWaiting:
      "As soon as the brief is approved, I will gather the approved sections into a folder ready for your development tools.",
    intro:
      "The five sections are approved. The folder holds the brief, the perspectives, the twins, the requirements and the chosen design as text, tables and diagrams.",
    introPartial:
      "The folder holds the sections approved so far as text, tables and diagrams. You can prepare it now and again after each approval.",
    held: ["{count} of {total} sections", "{count} of {total} sections"],
    partialRule: "Each section joins the folder when you approve it.",
    path: "The sections and their versions",
    versionNext: "{held}, next: {step}",
  },
  it: {
    agentReady:
      "Ho raccolto le cinque sezioni approvate in una cartella pronta per i tuoi strumenti di sviluppo.",
    agentPartial:
      "Raccolgo le sezioni approvate finora in una cartella pronta per i tuoi strumenti di sviluppo; le prossime si aggiungono quando le approvi.",
    agentWaiting:
      "Appena il brief è approvato, raccoglierò le sezioni approvate in una cartella pronta per i tuoi strumenti di sviluppo.",
    intro:
      "Le cinque sezioni sono approvate. La cartella raccoglie brief, prospettive, twin, requisiti e design scelto in forma di testo, tabelle e diagrammi.",
    introPartial:
      "La cartella raccoglie le sezioni approvate finora in forma di testo, tabelle e diagrammi. Puoi prepararla subito e di nuovo dopo ogni approvazione.",
    held: ["{count} sezione su {total}", "{count} sezioni su {total}"],
    partialRule: "Ogni sezione entra nella cartella quando la approvi.",
    path: "Le sezioni e le loro versioni",
    versionNext: "{held}, la prossima è {step}",
  },
} as const;
