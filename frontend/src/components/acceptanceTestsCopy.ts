export const acceptanceTestsCopy = {
  en: {
    eyebrow: "On the application you built",
    title: "Acceptance tests",
    intro:
      "The acceptance criteria of the approved requirements are tried in real browsers on the application built outside the Studio, through paths: the steps a person would take on the screens. Here you read the outcome of the latest run.",
    refresh: "Read again",
    loading: "Loading the acceptance tests…",
    loadFailed: "The acceptance tests could not be loaded.",
    loadFailedCode: "The acceptance tests could not be loaded ({code}).",
    noModel:
      "On this Studio the model cannot write the paths or ask the twins: connect a model. Paths already saved in your project still run.",
    empty:
      "No test run is recorded yet. The tests run from the terminal: launch `ut test` in the folder of your project.",
    latestRun: "Latest run",
    when: "When",
    browsers: "Browsers",
    application: "Application",
    reference: "Checked against",
    referenceValue: "requirements version {requirements}, design version {design}{alternative}",
    stale:
      "This run was made against earlier versions of the requirements or of the design: launch `ut test` to check the application against the approved ones.",
    browserName: {
      chrome: "Chrome",
      firefox: "Firefox",
    },
    applicationKind: {
      URL: "Web address",
      STATIC: "Static folder",
    },
    countsLabel: "Criteria by outcome",
    counts: {
      PASSED: ["{count} passed", "{count} passed"],
      FAILED: ["{count} failed", "{count} failed"],
      BLOCKED: ["{count} blocked", "{count} blocked"],
      NOT_COVERED: ["{count} not covered", "{count} not covered"],
      NOT_RUN: ["{count} not run", "{count} not run"],
    },
    legend:
      "Blocked: the test could not reach what it had to check. Not covered: the criterion cannot be checked on the screens. Not run: the criterion was left out of this run.",
    criteriaTitle: "Criteria ({count})",
    criteriaCaption: "Outcome of each acceptance criterion in the latest run",
    noCriteria: "This run names no criterion.",
    columns: {
      code: "Criterion",
      statement: "What it asks",
      status: "Outcome",
      paths: "Paths tried",
    },
    status: {
      PASSED: "Passed",
      FAILED: "Failed",
      BLOCKED: "Blocked",
      NOT_COVERED: "Not covered",
      NOT_RUN: "Not run",
    },
    statementMissing: "text not available",
    noPaths: "no path",
    reason: "Why",
    critiquesTitle: "What the twins say",
    reviewedAt: "Comments from {date}",
    earlierReview:
      "No twin has commented on the latest run yet: here are their comments on the run of {date}.",
    noReview:
      "No twin has commented on this run yet: at the end of a run `ut test` asks for their comments, once you confirm the cost.",
    critique: {
      FINE: "No concerns",
      CONCERN: "Some concerns",
      DRIFT: "Off course",
    },
    severity: {
      LOW: "Minor",
      MEDIUM: "Moderate",
      HIGH: "Major",
    },
    about: "About",
    action: "Suggested action",
    noFindings: "No remarks.",
    terminal:
      "The tests run from the terminal: `ut test` repeats them with the saved paths, `ut test --plan new` first has the model write new paths.",
    planRedo: "The test plan must be made again: `ut test --plan new`",
  },
  it: {
    eyebrow: "Sull'applicazione realizzata",
    title: "Verifica dei criteri",
    intro:
      "I criteri di accettazione dei requisiti approvati vengono provati in browser veri sull'applicazione realizzata fuori dallo Studio, con dei percorsi: i passi che una persona farebbe sulle schermate. Qui leggi l'esito dell'ultima verifica.",
    refresh: "Rileggi",
    loading: "Carico la verifica dei criteri…",
    loadFailed: "Non è stato possibile caricare la verifica dei criteri.",
    loadFailedCode: "Non è stato possibile caricare la verifica dei criteri ({code}).",
    noModel:
      "In questo Studio il modello non può scrivere i percorsi né interpellare i twin: collega un modello. I percorsi già salvati nel tuo progetto funzionano ancora.",
    empty:
      "Non è ancora registrata nessuna verifica. I test partono dal terminale: lancia `ut test` nella cartella del tuo progetto.",
    latestRun: "Ultima verifica",
    when: "Quando",
    browsers: "Browser",
    application: "Applicazione",
    reference: "Confrontata con",
    referenceValue: "requisiti versione {requirements}, design versione {design}{alternative}",
    stale:
      "Questa verifica è stata fatta su versioni precedenti dei requisiti o del design: lancia `ut test` per controllare l'applicazione su quelle approvate.",
    browserName: {
      chrome: "Chrome",
      firefox: "Firefox",
    },
    applicationKind: {
      URL: "Indirizzo web",
      STATIC: "Cartella statica",
    },
    countsLabel: "Criteri per esito",
    counts: {
      PASSED: ["{count} superato", "{count} superati"],
      FAILED: ["{count} non superato", "{count} non superati"],
      BLOCKED: ["{count} bloccato", "{count} bloccati"],
      NOT_COVERED: ["{count} non coperto", "{count} non coperti"],
      NOT_RUN: ["{count} non eseguito", "{count} non eseguiti"],
    },
    legend:
      "Bloccato: la prova non è arrivata a ciò che doveva controllare. Non coperto: il criterio non si può controllare dalle schermate. Non eseguito: il criterio è rimasto fuori da questa verifica.",
    criteriaTitle: "Criteri ({count})",
    criteriaCaption: "Esito di ogni criterio di accettazione nell'ultima verifica",
    noCriteria: "Questa verifica non riguarda nessun criterio.",
    columns: {
      code: "Criterio",
      statement: "Che cosa chiede",
      status: "Esito",
      paths: "Percorsi provati",
    },
    status: {
      PASSED: "Superato",
      FAILED: "Non superato",
      BLOCKED: "Bloccato",
      NOT_COVERED: "Non coperto",
      NOT_RUN: "Non eseguito",
    },
    statementMissing: "testo non disponibile",
    noPaths: "nessun percorso",
    reason: "Perché",
    critiquesTitle: "Che cosa dicono i twin",
    reviewedAt: "Commenti del {date}",
    earlierReview:
      "Nessun twin ha ancora commentato l'ultima verifica: ecco i loro commenti sulla verifica del {date}.",
    noReview:
      "Nessun twin ha ancora commentato questa verifica: alla fine di una verifica `ut test` chiede il loro commento, dopo che hai confermato la spesa.",
    critique: {
      FINE: "Nessun dubbio",
      CONCERN: "Qualche dubbio",
      DRIFT: "Fuori strada",
    },
    severity: {
      LOW: "Minore",
      MEDIUM: "Moderata",
      HIGH: "Importante",
    },
    about: "Riguarda",
    action: "Azione suggerita",
    noFindings: "Nessuna osservazione.",
    terminal:
      "I test partono dal terminale: `ut test` li ripete con i percorsi salvati, `ut test --plan new` fa prima scrivere al modello percorsi nuovi.",
    planRedo: "Il piano dei test va rifatto: `ut test --plan new`",
  },
} as const;
