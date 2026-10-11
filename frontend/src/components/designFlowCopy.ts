export const designFlowCopy = {
  en: {
    designer: "UX/UI designer",
    noPackage:
      "I am ready to propose a look for your app: I prepare the alternatives and have the twins try them.",
    prerequisite: "Approve the requirements first: then I can prepare the alternatives.",
    generate: "Prepare the design alternatives",
    generating: "The designer is preparing the alternatives…",
    loading: "Loading the design…",
    updating: "Updating the design…",
    introOne: "I prepared one alternative and had the twins try it. Their opinion is below.",
    introMany: "I prepared {n} alternatives and had the twins try them. Their opinion is below.",
    introChosen:
      "You chose {alternative}. Read what the twins think and approve the design when you are ready.",
    introIterate:
      "You chose {alternative}. If something should change, ask for changes: I draw a new version and you compare it with the current one.",
    numbers: ["no", "one", "two", "three", "four", "five", "six", "seven", "eight"],
    viewLabel: "Views of the design",
    loadError: "Design & Evaluation could not be loaded.",
    genericFailure: "The request could not be completed. You can try again.",
    mockupRequired: "The mockup of this alternative is not ready yet: wait for it before choosing.",
    mockupRequiredDeclarative: "Try the mockup of this alternative first: then you can choose it.",
    pendingOther:
      "Another change is waiting for your decision above: apply it or discard it first.",
    proposeFailed: "Your choice could not be recorded, so nothing changed. Try again in a moment.",
    contextChanged:
      "An earlier step needs updating. Review that step before choosing a design alternative. Your current choice is unchanged.",
    applyFailed:
      "Your choice is recorded but it was not applied yet. Press “Choose this one” again.",
    noChanges: "This design is already the current one.",
    iterationApplyFailed:
      "The new version is recorded but it was not applied yet. Press “Apply the new version” again.",
    iterationStale: "The design changed in the meantime: this version can no longer be applied.",
    iterationPending:
      "A new version is already waiting for your decision: apply it or discard it before asking for other changes.",
    ruleTooLong:
      "A rule can have at most 300 characters: shorten the request or do not keep it as a rule.",
    ruleFailed: "The rule could not be removed. Try again in a moment.",
    hintTry: "Try the mockup first: then you can choose it.",
    hintPendingOther: "Decide first on the change waiting above.",
    notCovered: "The mockup does not show these requirements yet: {list}.",
    previewTitle: "Mockup of {alternative}",
    previewDraft: "Model-generated draft · not applied",
    previewCurrent: "The mockup of the chosen design",
    previewHelp:
      "Explore the screens and controls. Example results illustrate the design; the application is built from the knowledge folder with your own tools.",
    previewMissing: "This alternative has no preview yet. Creating it takes a moment.",
    previewError: "The preview could not be loaded.",
    createMockup: "Create the preview",
    reloadPreview: "Try again",
    closePreview: "Close the preview",
    pendingTitle: ["A change is waiting for your decision", "Changes waiting for your decision"],
    applyDiff: "Apply the change",
    rejectDiff: "Discard it",
    diffReason: "Why you discard it (needed to discard it)",
    reasonRequired: "A reason is required to reject or to discard.",
    regenerateText:
      "Did you bring insights into the project? Regenerate the alternatives: the twins will review them again.",
    regenerate: "Regenerate the alternatives",
    regenerating: "The designer is regenerating the alternatives…",
    regenerationRejected: "The design could not be regenerated.",
    regenerationRequirements:
      "The requirements have changed and are waiting for your approval. Approve them again, then regenerate the design alternatives.",
    regenerationNoPackage:
      "There is no design to regenerate yet. Generate the design alternatives first.",
    concernsTitle: "Points of attention and open questions ({n})",
    concerns: "Points of attention",
    remedy: "Remedy",
    openQuestions: "Open questions",
    approveGate: "Approve the chosen design",
    askChanges: "Ask for changes",
    barChoose:
      "Choose one of the alternatives with “Choose this one”: then you approve the design here.",
    barApprove:
      "You approve {alternative}. The knowledge folder will contain this design and the opinion of the twins.",
    barApproved:
      "You approved this design. You can still ask for changes in words: the new version comes back here for your approval.",
    barApprovedDrawing:
      "The designer is drawing the new version you asked for: the approved design stays as it is until you apply it.",
    barApprovedWaiting: "The new version is waiting above: apply it, then approve it here.",
    barPending:
      "A proposed change is waiting above: if you approve now, it stays out of this version.",
    barIteration:
      "A new version is waiting above: if you approve now, you approve the current one.",
    barDrawing:
      "The designer is drawing the new version you asked for: you can wait for it or approve the current one.",
    barRevision:
      "You asked for changes: ask the designer for a new version, choose another alternative or regenerate the alternatives.",
    barRequestIteration: "Until you apply the new version, the current design stays as it is.",
    barRequestRevision:
      "The current design does not change: your note stays in the history of the design.",
    iterationPlaceholder:
      "Write what to change: the designer draws a new version and you decide whether to apply it.",
    revisionPlaceholder:
      "Write what is wrong: the request is recorded with your note. For a different design, choose another alternative or regenerate the alternatives.",
    keepRule: "Keep it as a rule for the next versions",
    keepRuleHint: "The designer will follow it every time it draws a new version.",
    submitFailed:
      "The design could not be brought to your approval, so nothing was approved. Try again in a moment.",
    approveFailed:
      "The design is ready for your approval, but the approval did not go through. Press “Approve the chosen design” again.",
    requestFailed:
      "Your request for changes could not be recorded. Your note is still there: try again in a moment.",
    moreActions: "Other choices on the approval",
    reason: "Reason (needed to reject or to ask for a revision)",
    rejectGate: "Reject the design",
    requestRevision: "Ask for a revision",
    pause: "Pause the approval",
    cancelGate: "Cancel the approval",
    pausedText: "The approval of this design is paused.",
    resume: "Resume the approval",
    revisionTitle: "You asked for changes",
    rejectedTitle: "You rejected this design",
    cancelledTitle: "You cancelled the approval",
    closedText:
      "To change it, choose another alternative, ask for changes or regenerate the alternatives: the new version comes back here for your approval.",
    yourNote: "Your note",
    ready: "Design approved by you. Next: the Dossier.",
    reanchoredReview:
      "The design was re-anchored to the new Definition: you can ask the twins for a new evaluation.",
    matrixEmpty: "The twins have not given an opinion on these alternatives yet.",
    readObservations: "Read every observation of {twin} on {alternative} ({count})",
    closeObservations: "Close the observations",
    version: "Version",
    statusChoose: "waiting for your choice",
    statusPending: "waiting for your decision",
    statusApproved: "approved",
    statusPaused: "paused",
    statusRevision: "changes requested",
    statusRejected: "rejected",
    statusCancelled: "approval cancelled",
    contentHash: "Content hash",
    basedOn: "Based on version",
    created: "Created",
    approval: "Approval",
    decisionCounter: "Decision no. {n}",
    requirements: "Requirements",
    catalog: "Style catalogue",
    model: "Model that draws the mockups",
    localModel: "local model, declarative preview",
    mockupGeneration: "Mockup of {code}",
    generations: "Generations of the project",
    cost: "Cost of the generations",
    tokens: "Tokens",
    tokensValue: "{input} in · {output} out · {reasoning} reasoning",
    none: "None",
    methodology:
      "Gate 5 approves the exact Design Package ID, version, and content hash. Owner approval is governance, not empirical validation. Synthetic User Twin feedback remains a design hypothesis.",
    history: "Versions of the design",
    historyItem: "Version {n} · {date}",
    historyTitle: "Versions of the design ({n})",
    historyCurrent: "current",
    restoreVersion: "Go back to this version",
    restoreNamed: "version {n}",
    restoreText:
      "A new version is created, identical to version {n}: then it has to be approved, like every new version.",
    restoreConfirm: "Go back to version {n}",
    restoreCancel: "Cancel",
    restoreRunning: "Going back to version {n}…",
    restoreDone:
      "Version {m} created from version {n}: approve it with “Approve the chosen design”.",
    restoreCurrent:
      "The current design is already the same as version {n}: there is nothing to restore.",
    restoreMissing: "Version {n} is no longer in the Studio: reload the page.",
    restoreRequirements:
      "Version {n} cites requirements that the Definition no longer contains: it cannot come back.",
    restoreTwins:
      "Version {n} was prepared with twins different from the current ones: it cannot come back.",
    restoreContext: "An earlier step needs updating: update it, then go back to this version.",
    restoreFailed:
      "Going back to version {n} did not work, so nothing changed. Try again in a moment.",
    decided: "Changes already decided",
    applied: "Applied",
    discarded: "Discarded",
    provenance: "Provenance of the critiques",
    confidence: "self-assessed confidence {value}",
    usage: "Generations with the hosted model",
    usageItem: "{date} · {purpose} · {model} · {status}",
    subscription: "subscription",
    mockupNotes: "Notes of the Studio on the mockups",
    mockupNotesIntro: "The Studio accepted these mockups and noted these points.",
    mockupNotesOf: "{code} · {title}",
    onScreen: "On the screen “{title}”: {text}",
    redrawRequest:
      "Redraw the mockup so that it reproduces the look and the structure of the supplied design “{title}”: same layout, colours and hierarchy of the content, with the screens and the requirements of the project.",
  },
  it: {
    designer: "Designer UX/UI",
    noPackage:
      "Sono pronto a proporti un aspetto per la tua app: preparo le alternative e le faccio provare ai twin.",
    prerequisite: "Approva prima i requisiti: poi posso preparare le alternative.",
    generate: "Prepara le alternative di design",
    generating: "Il designer sta preparando le alternative…",
    loading: "Carico il design…",
    updating: "Aggiorno il design…",
    introOne:
      "Ho preparato un'alternativa e l'ho fatta provare ai twin. Il loro parere è qui sotto.",
    introMany:
      "Ho preparato {n} alternative e le ho fatte provare ai twin. Il loro parere è qui sotto.",
    introChosen:
      "Hai scelto {alternative}. Leggi il parere dei twin e approva il design quando sei pronto.",
    introIterate:
      "Hai scelto {alternative}. Se qualcosa va cambiato, chiedi modifiche: disegno una nuova versione e la confronti con quella attuale.",
    numbers: ["nessuna", "una", "due", "tre", "quattro", "cinque", "sei", "sette", "otto"],
    viewLabel: "Viste del design",
    loadError: "Non è stato possibile caricare Design e valutazione.",
    genericFailure: "Non è stato possibile completare la richiesta. Puoi riprovare.",
    mockupRequired:
      "Il mockup di questa alternativa non è ancora pronto: aspettalo prima di sceglierla.",
    mockupRequiredDeclarative:
      "Prova prima il mockup di questa alternativa: poi potrai sceglierla.",
    pendingOther:
      "Un'altra modifica aspetta la tua decisione qui sopra: applicala o scartala prima.",
    proposeFailed:
      "Non è stato possibile registrare la tua scelta: non è cambiato nulla. Riprova tra poco.",
    contextChanged:
      "Un passo precedente è da aggiornare. Rivedi quel passo prima di scegliere un'alternativa di design. La scelta attuale non è cambiata.",
    applyFailed:
      "La tua scelta è registrata ma non è ancora stata applicata. Premi di nuovo «Scegli questa».",
    noChanges: "Questo design è già quello attuale.",
    iterationApplyFailed:
      "La nuova versione è registrata ma non è ancora stata applicata. Premi di nuovo «Applica la nuova versione».",
    iterationStale: "Il design è cambiato nel frattempo: questa versione non si può più applicare.",
    iterationPending:
      "Una nuova versione aspetta già la tua decisione: applicala o scartala prima di chiedere altre modifiche.",
    ruleTooLong:
      "Una regola può avere al massimo 300 caratteri: accorcia la richiesta o non tenerla come regola.",
    ruleFailed: "Non è stato possibile togliere la regola. Riprova tra poco.",
    hintTry: "Prova prima il mockup: poi potrai sceglierla.",
    hintPendingOther: "Decidi prima la modifica che aspetta qui sopra.",
    notCovered: "Il mockup non mostra ancora questi requisiti: {list}.",
    previewTitle: "Mockup di {alternative}",
    previewDraft: "Bozza generata dal modello · non applicata",
    previewCurrent: "Il mockup del design scelto",
    previewHelp:
      "Esplora schermate e controlli. I risultati di esempio illustrano il design; l'applicazione si realizza dalla cartella di conoscenza con i tuoi strumenti.",
    previewMissing:
      "Questa alternativa non ha ancora un'anteprima. Crearla richiede qualche istante.",
    previewError: "Non è stato possibile caricare l'anteprima.",
    createMockup: "Crea l'anteprima",
    reloadPreview: "Riprova",
    closePreview: "Chiudi l'anteprima",
    pendingTitle: [
      "Una modifica aspetta la tua decisione",
      "Modifiche che aspettano la tua decisione",
    ],
    applyDiff: "Applica la modifica",
    rejectDiff: "Scartala",
    diffReason: "Perché la scarti (serve per scartarla)",
    reasonRequired: "Per respingere o scartare serve una motivazione.",
    regenerateText:
      "Hai portato degli spunti nel progetto? Rigenera le alternative: i twin le valuteranno di nuovo.",
    regenerate: "Rigenera le alternative",
    regenerating: "Il designer sta rigenerando le alternative…",
    regenerationRejected: "Non è stato possibile rigenerare il design.",
    regenerationRequirements:
      "I requisiti sono cambiati e aspettano la tua approvazione. Riapprovali, poi rigenera le alternative di design.",
    regenerationNoPackage:
      "Non c'è ancora un design da rigenerare. Genera prima le alternative di design.",
    concernsTitle: "Punti di attenzione e domande aperte ({n})",
    concerns: "Punti di attenzione",
    remedy: "Rimedio",
    openQuestions: "Domande aperte",
    approveGate: "Approva il design scelto",
    askChanges: "Chiedi modifiche",
    barChoose: "Scegli una delle alternative con «Scegli questa»: poi approvi il design qui.",
    barApprove:
      "Approvi {alternative}. La cartella di conoscenza conterrà questo design e il parere dei twin.",
    barApproved:
      "Hai approvato questo design. Puoi ancora chiedere modifiche a parole: la nuova versione torna qui per la tua approvazione.",
    barApprovedDrawing:
      "Il designer sta disegnando la nuova versione che hai chiesto: il design approvato resta com'è finché non la applichi.",
    barApprovedWaiting: "La nuova versione aspetta qui sopra: applicala, poi approvala qui.",
    barPending:
      "Una modifica proposta aspetta qui sopra: se approvi ora, resta fuori da questa versione.",
    barIteration: "Una nuova versione aspetta qui sopra: se approvi ora, approvi quella attuale.",
    barDrawing:
      "Il designer sta disegnando la nuova versione che hai chiesto: puoi aspettarla o approvare quella attuale.",
    barRevision:
      "Hai chiesto modifiche: chiedi al designer una nuova versione, scegli un'altra alternativa o rigenera le alternative.",
    barRequestIteration: "Finché non applichi la nuova versione, il design attuale resta com'è.",
    barRequestRevision: "Il design attuale non cambia: la tua nota resta nella storia del design.",
    iterationPlaceholder:
      "Scrivi che cosa cambiare: il designer disegna una nuova versione e decidi tu se applicarla.",
    revisionPlaceholder:
      "Scrivi che cosa non va: la richiesta viene registrata con la tua nota. Per un design diverso scegli un'altra alternativa o rigenera le alternative.",
    keepRule: "Tienila come regola per le prossime versioni",
    keepRuleHint: "Il designer la rispetterà ogni volta che disegna una nuova versione.",
    submitFailed:
      "Non è stato possibile portare il design alla tua approvazione: non è stato approvato nulla. Riprova tra poco.",
    approveFailed:
      "Il design è pronto per la tua approvazione, ma l'approvazione non è andata a buon fine. Premi di nuovo «Approva il design scelto».",
    requestFailed:
      "Non è stato possibile registrare la tua richiesta di modifiche. La nota è ancora lì: riprova tra poco.",
    moreActions: "Altre scelte sull'approvazione",
    reason: "Motivazione (serve per respingere o per chiedere una revisione)",
    rejectGate: "Respingi il design",
    requestRevision: "Chiedi una revisione",
    pause: "Metti in pausa l'approvazione",
    cancelGate: "Annulla l'approvazione",
    pausedText: "L'approvazione di questo design è in pausa.",
    resume: "Riprendi l'approvazione",
    revisionTitle: "Hai chiesto modifiche",
    rejectedTitle: "Hai respinto questo design",
    cancelledTitle: "Hai annullato l'approvazione",
    closedText:
      "Per cambiarlo scegli un'altra alternativa, chiedi modifiche o rigenera le alternative: la nuova versione torna qui per la tua approvazione.",
    yourNote: "La tua nota",
    ready: "Design approvato da te. Ora il Dossier.",
    reanchoredReview:
      "Il design è stato riagganciato alla Definizione nuova: puoi chiedere ai twin una nuova valutazione.",
    matrixEmpty: "I twin non hanno ancora espresso un parere su queste alternative.",
    readObservations: "Leggi tutte le osservazioni di {twin} su {alternative} ({count})",
    closeObservations: "Chiudi le osservazioni",
    version: "Versione",
    statusChoose: "in attesa della tua scelta",
    statusPending: "in attesa della tua decisione",
    statusApproved: "approvata",
    statusPaused: "in pausa",
    statusRevision: "modifiche richieste",
    statusRejected: "respinta",
    statusCancelled: "approvazione annullata",
    contentHash: "Hash del contenuto",
    basedOn: "Basata sulla versione",
    created: "Creata il",
    approval: "Approvazione",
    decisionCounter: "Decisione n. {n}",
    requirements: "Requisiti",
    catalog: "Catalogo degli stili",
    model: "Modello che disegna i mockup",
    localModel: "modello locale, anteprima dichiarativa",
    mockupGeneration: "Mockup di {code}",
    generations: "Generazioni del progetto",
    cost: "Costo delle generazioni",
    tokens: "Token",
    tokensValue: "{input} in ingresso · {output} in uscita · {reasoning} di ragionamento",
    none: "Nessuno",
    methodology:
      "Il Gate 5 approva ID, versione e hash esatti del Design Package. L'approvazione del proprietario è governance, non validazione empirica. Il feedback sintetico degli User Twin resta un'ipotesi progettuale.",
    history: "Versioni del design",
    historyItem: "Versione {n} · {date}",
    historyTitle: "Versioni del design ({n})",
    historyCurrent: "attuale",
    restoreVersion: "Torna a questa versione",
    restoreNamed: "versione {n}",
    restoreText:
      "Nasce una versione nuova, uguale alla versione {n}: poi va approvata, come ogni versione nuova.",
    restoreConfirm: "Torna alla versione {n}",
    restoreCancel: "Annulla",
    restoreRunning: "Torno alla versione {n}…",
    restoreDone:
      "Versione {m} creata dalla versione {n}: approvala con «Approva il design scelto».",
    restoreCurrent:
      "Il design attuale è già uguale alla versione {n}: non c'è niente da ripristinare.",
    restoreMissing: "La versione {n} non c'è più nello Studio: ricarica la pagina.",
    restoreRequirements:
      "La versione {n} cita requisiti che la Definizione non contiene più: non può tornare.",
    restoreTwins:
      "La versione {n} è stata preparata con twin diversi da quelli di adesso: non può tornare.",
    restoreContext: "Un passo precedente è da aggiornare: aggiornalo, poi torna a questa versione.",
    restoreFailed:
      "Il ritorno alla versione {n} non è riuscito: non è cambiato nulla. Riprova tra poco.",
    decided: "Modifiche già decise",
    applied: "Applicata",
    discarded: "Scartata",
    provenance: "Provenienza delle critiche",
    confidence: "confidenza auto-valutata {value}",
    usage: "Generazioni con il modello ospitato",
    usageItem: "{date} · {purpose} · {model} · {status}",
    subscription: "abbonamento",
    mockupNotes: "Note dello Studio sui mockup",
    mockupNotesIntro: "Lo Studio ha accettato questi mockup e ha annotato questi punti.",
    mockupNotesOf: "{code} · {title}",
    onScreen: "Nella schermata «{title}»: {text}",
    redrawRequest:
      "Ridisegna il mockup perché riproduca l'aspetto e la struttura del design fornito «{title}»: stessa disposizione, stessi colori e stessa gerarchia dei contenuti, con le schermate e i requisiti del progetto.",
  },
} as const;
