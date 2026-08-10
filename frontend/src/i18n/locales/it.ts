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
    login: "Accedi",
    logout: "Esci",
    menu: "Menu",
    openLabel: "Apri la navigazione principale",
    overview: "Panoramica",
    projects: "Progetti",
    register: "Registrati",
    skip: "Vai al contenuto principale",
  },
  auth: {
    email: "Indirizzo email",
    password: "Password",
    passwordHint:
      "Usa almeno 15 caratteri. Sono supportati spazi e passphrase.",
    submitting: "Attendi…",
    login: {
      eyebrow: "Account locale",
      title: "Accedi",
      description: "Continua verso i tuoi progetti OrchesTwin Studio.",
      submit: "Accedi",
      noAccount: "Non hai ancora un account?",
      registerLink: "Creane uno",
    },
    register: {
      eyebrow: "Account locale",
      title: "Crea il tuo account",
      description: "Registra un account locale proprietario dei tuoi progetti.",
      submit: "Registrati",
      hasAccount: "Hai già un account?",
      loginLink: "Accedi",
    },
    errors: {
      invalid_authentication: "L'email o la password non sono valide.",
      email_already_registered: "Esiste già un account con questo indirizzo email.",
      invalid_registration: "I dati di registrazione non sono validi.",
      invalid_refresh_token: "La sessione non è più valida. Accedi nuovamente.",
      expired_refresh_token: "La sessione è scaduta. Accedi nuovamente.",
      refresh_token_reuse_detected:
        "La sessione è stata revocata perché è stato riutilizzato un token precedente. Accedi nuovamente.",
      unexpected_api_error: "Il server ha restituito una risposta inattesa.",
      unexpected_error: "Si è verificato un errore inatteso.",
    },
  },
  overview: {
    capabilities: {
      api: "API health versionata",
      backend: "Backend FastAPI tipizzato",
      frontend: "Workspace Vue verificato",
    },
    capabilitiesTitle: "Capacità della fondazione",
    description:
      "La fondazione attuale fornisce workspace backend e frontend verificabili in modo indipendente. I workflow di progetto verranno introdotti progressivamente.",
    eyebrow: "Agentic UCD governato dall'essere umano",
    status: "Workspace frontend operativo",
    title: "OrchesTwin Studio",
  },
  projects: {
    description: "Crea e gestisci i tuoi progetti software strutturati.",
    emptyDescription: "Crea il primo progetto per iniziare il relativo Project Brief.",
    emptyTitle: "Nessun progetto presente",
    eyebrow: "Workspace dei progetti",
    title: "Progetti",
  },
} as const;

export default messages;