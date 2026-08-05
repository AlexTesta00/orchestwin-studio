const messages = {
  app: {
    homeAriaLabel: "Pagina iniziale di OrchesTwin Studio",
    title: "OrchesTwin Studio",
  },
  locale: {
    en: "Inglese",
    it: "Italiano",
    label: "Lingua",
  },
  navigation: {
    close: "Chiudi",
    closeLabel: "Chiudi la navigazione principale",
    label: "Navigazione principale",
    menu: "Menu",
    openLabel: "Apri la navigazione principale",
    overview: "Panoramica",
    projects: "Progetti",
    skip: "Vai al contenuto principale",
  },
  overview: {
    capabilities: {
      api: "API health versionata",
      backend: "Backend FastAPI tipizzato",
      frontend: "Workspace Vue verificato",
    },
    capabilitiesTitle: "Capacità della fondazione",
    description:
      "La fondazione attuale fornisce workspace backend e frontend verificabili in modo indipendente. I workflow di progetto verranno introdotti negli sprint successivi.",
    eyebrow: "Agentic UCD governato dall'essere umano",
    status: "Workspace frontend operativo",
    title: "OrchesTwin Studio",
  },
  projects: {
    description:
      "L'acquisizione dei progetti e i brief versionati verranno introdotti nello Sprint 02.",
    emptyDescription:
      "Lo sprint di fondazione verifica la navigazione e la struttura del workspace senza creare prematuramente dati di dominio.",
    emptyTitle: "Nessun progetto presente",
    eyebrow: "Workspace dei progetti",
    title: "Progetti",
  },
} as const;

export default messages;
