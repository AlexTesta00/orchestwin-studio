import type { UserTwinField } from "../types/userModeling";

export const fieldLabels: Record<"en" | "it", Record<UserTwinField, string>> = {
  en: {
    role: "Role",
    age_range: "Age range",
    expertise: "Expertise",
    goals: "Goals",
    recurring_tasks: "Recurring tasks",
    context_of_use: "Context of use",
    information_needs: "Information needs",
    decision_criteria: "Decision criteria",
    preferred_vocabulary: "Preferred vocabulary",
    frustrations: "Frustrations",
    pain_points: "Pain points",
    trust_concerns: "Trust concerns",
    accessibility_needs: "Accessibility needs",
    operational_constraints: "Operational constraints",
    technical_literacy: "Technical literacy",
    risk_sensitivity: "Risk sensitivity",
    assumptions: "Assumptions",
    description: "Description",
    represents: "Represents",
    does_not_represent: "Does not represent",
    evidence_gaps: "Evidence gaps",
  },

  it: {
    role: "Ruolo",
    age_range: "Fascia di età",
    expertise: "Competenze",
    goals: "Obiettivi",
    recurring_tasks: "Attività ricorrenti",
    context_of_use: "Contesto d'uso",
    information_needs: "Bisogni informativi",
    decision_criteria: "Criteri decisionali",
    preferred_vocabulary: "Vocabolario preferito",
    frustrations: "Frustrazioni",
    pain_points: "Difficoltà",
    trust_concerns: "Preoccupazioni sulla fiducia",
    accessibility_needs: "Esigenze di accessibilità",
    operational_constraints: "Vincoli operativi",
    technical_literacy: "Competenza tecnica",
    risk_sensitivity: "Sensibilità al rischio",
    assumptions: "Assunzioni",
    description: "Descrizione",
    represents: "Rappresenta",
    does_not_represent: "Non rappresenta",
    evidence_gaps: "Limiti delle evidenze",
  },
};

export const userModelingFlowCopy = {
  en: {
    region: "User Twin",

    loading: "Updating user profiles…",
    generating: "Preparing the profiles. This may take a few minutes; keep this page open.",

    error: "User Twin operation failed.",

    genericFailure: "The request could not be completed. You can try again.",

    unexpectedError: "An unexpected error occurred in the User Twin step.",

    personasHeading: "Archetypes",

    twinsHeading: "The twins of your project",

    profilesCount: "{confirmed} of {total} archetypes confirmed",

    profilesSentence: "Confirm the archetypes that describe who will use the product.",

    twinsCountOne: "1 twin to approve",

    twinsCountOther: "{n} twins to approve",

    twinsApprovedOne: "1 twin approved by you",

    twinsApprovedOther: "{n} twins approved by you",

    twinsSentence:
      "The twins' answers are simulated: hypotheses to weigh, not opinions of real people.",

    proposePersonas: "Suggest archetypes",

    noPersonasTitle: "No archetype yet",

    noPersonas: "Add an archetype or ask for suggestions from the brief.",

    noTwins: "No twin in this version.",

    fromBrief: "From the brief",

    fromOwner: "Described by you",

    reused: "Reused from “{project}”",

    reusedElsewhere: "Reused from another project",

    hypothesesOne: "1 hypothesis to verify",

    hypothesesOther: "{n} hypotheses to verify",

    confirmedByYou: "Confirmed by you",

    rejectedChip: "Set aside",

    pending: "Pending confirmation",

    awaitingApproval: "To approve",

    goals: "Goals",

    context: "Context of use",

    holdsBack: "What holds them back",

    fullProfile: "See the full profile",

    confirm: "Confirm",

    reject: "Set aside",

    rejectConfirm: "Set the archetype aside",

    rejectionReason: "Why do you set it aside?",

    reasonPlaceholder: "Explain why this archetype does not describe who will use the product…",

    rejectedBecause: "Set aside: {reason}",

    cancel: "Cancel",

    talk: "Talk to the twin",

    pendingDiffsOne: "1 change to approve in the profile",

    pendingDiffsOther: "{n} changes to approve in the profile",

    startingProfiles: "Archetypes",

    profileTitle: "Profile of {name}",

    staleContext:
      "The brief or the perspectives changed: generate and approve a new User Twin version before continuing.",

    staleContextSections:
      "The brief or the perspectives changed: use “Update and confirm” above to keep these twins and re-anchor them, or create them again.",

    generateTwins: "Create the twins",

    regenerateTwins: "Create the twins again",

    decideProfiles:
      "Confirm or set aside every proposed archetype: the twins are born from the confirmed archetypes.",

    confirmOne: "Confirm at least one archetype to create the twins.",

    readyToGenerate:
      "Confirmed archetypes: {n}. Create their twins: you will be able to talk to them and correct them.",

    submitFailed:
      "The twins could not be brought to your approval. Refresh the page and try again.",

    requestPlaceholder:
      "Write what does not convince you in the profiles: the note stays in the history of the decisions.",

    decisionResume: "You paused this decision. Resume it when you are ready.",

    profileDetails: "View profile",

    evidenceDetails: "Why we think this",

    knowledgeSource: "Where does this information come from?",

    edit: "Correct",

    editField: "Correct {field}",

    observationUnavailable: "This information is read-only.",

    revisionValue: "New value",

    revisionItemsHint: "Use one item per line.",

    userProvided: "Owner / user provided",

    humanValidated: "Human validated",

    humanValidatedWarning:
      "Choose Human validated only if a person has checked this information. Approving a profile alone does not verify its assumptions.",

    proposeRevision: "Propose this change",

    diffs: "Suggested profile changes",

    proposedDiff: "Proposed",

    approvedDiff: "Approved",

    rejectedDiff: "Rejected",

    before: "Before",

    after: "After",

    approveDiff: "Approve change",

    rejectDiff: "Reject change",

    diffReason: "Decision reason",

    otherDecisions: "Other decisions",

    approveGate: "Confirm the twins and continue",

    rejectGate: "Reject",

    pause: "Pause",

    resume: "Resume",

    cancelGate: "Cancel approval",

    gateReason: "Reason for your decision",

    gateReasonHint: "Needed to reject the profiles.",

    gateMethodology:
      "Your approval allows the project to use these profiles. It does not mean their assumptions have been verified with real users.",

    currentSnapshotApproved: "You have approved these user profiles.",

    ready: "Ready for the Definition.",

    notReady: "Review and approve your user profiles to continue.",

    stale: "The profiles have changed since your last approval. Review them again.",

    revisionRequested:
      "You asked for changes. Correct the twins: the new version comes back for your approval.",

    revisionNote: "Your note: “{note}”",

    cancelled: "You cancelled this decision. Correct a twin to prepare a new version.",

    rejected: "You rejected these profiles. Correct a twin to prepare a new version.",

    pausedNeedsHuman: "The decision is stopped and needs your intervention.",

    technicalSummary: "Version {number} · {state}",

    technicalProfiles: "Proposed archetypes · twins not created yet",

    technicalEmpty: "No archetype yet",

    stateApproved: "approved",

    statePending: "waiting for your decision",

    stateDraft: "being prepared",

    contentHash: "Content hash",

    gateStatus: "Approval",

    workflow: "Workflow state",

    decisionCounter: "Decision no. {n}",

    technicalTwins: "Twins",

    technicalPersonas: "Archetypes",

    persistedLifecycle: "Persisted lifecycle",

    effectiveLifecycle: "Effective lifecycle",

    unknown: "Unknown",

    abstained: "Abstained",

    empty: "No value",

    requiredReason: "A reason is required for this decision.",

    requiredValue: "Enter a value before proposing the revision.",

    invalidField: "The selected observation is not mapped to a User Twin field.",

    projectMissing: "Project and access token are required.",

    profileInformation: "Profile information",
  },

  it: {
    region: "User Twin",

    loading: "Aggiornamento dei profili…",
    generating:
      "Preparazione dei profili in corso. Può richiedere alcuni minuti; mantieni aperta questa pagina.",

    error: "Operazione sugli User Twin non riuscita.",

    genericFailure: "Non è stato possibile completare la richiesta. Puoi riprovare.",

    unexpectedError: "Si è verificato un errore inatteso nel passo User Twin.",

    personasHeading: "Archetipi",

    twinsHeading: "I twin del progetto",

    profilesCount: "{confirmed} di {total} archetipi confermati",

    profilesSentence: "Conferma gli archetipi che descrivono chi userà il prodotto.",

    twinsCountOne: "1 twin da approvare",

    twinsCountOther: "{n} twin da approvare",

    twinsApprovedOne: "1 twin approvato da te",

    twinsApprovedOther: "{n} twin approvati da te",

    twinsSentence:
      "Le risposte dei twin sono simulate: ipotesi da pesare, non opinioni di persone reali.",

    proposePersonas: "Proponi archetipi",

    noPersonasTitle: "Ancora nessun archetipo",

    noPersonas: "Aggiungi un archetipo o chiedi proposte dal brief.",

    noTwins: "Nessun twin in questa versione.",

    fromBrief: "Dal brief",

    fromOwner: "Descritto da te",

    reused: "Riusato da «{project}»",

    reusedElsewhere: "Riusato da un altro progetto",

    hypothesesOne: "1 ipotesi da verificare",

    hypothesesOther: "{n} ipotesi da verificare",

    confirmedByYou: "Confermato da te",

    rejectedChip: "Scartato",

    pending: "In attesa di conferma",

    awaitingApproval: "Da approvare",

    goals: "Obiettivi",

    context: "Contesto d'uso",

    holdsBack: "Che cosa è di ostacolo",

    fullProfile: "Vedi il profilo completo",

    confirm: "Conferma",

    reject: "Scarta",

    rejectConfirm: "Scarta l'archetipo",

    rejectionReason: "Perché lo scarti?",

    reasonPlaceholder: "Spiega perché questo archetipo non descrive chi userà il prodotto…",

    rejectedBecause: "Scartato: {reason}",

    cancel: "Annulla",

    talk: "Parla con il twin",

    pendingDiffsOne: "1 modifica al profilo da approvare",

    pendingDiffsOther: "{n} modifiche al profilo da approvare",

    startingProfiles: "Archetipi",

    profileTitle: "Il profilo di {name}",

    staleContext:
      "Brief o prospettive sono cambiati: genera una nuova versione degli User Twin e approvala prima di proseguire.",

    staleContextSections:
      "Brief o prospettive sono cambiati: usa «Aggiorna e conferma» qui sopra per tenere questi twin e riagganciarli, oppure creali di nuovo.",

    generateTwins: "Crea i twin",

    regenerateTwins: "Crea di nuovo i twin",

    decideProfiles:
      "Conferma o scarta ogni archetipo proposto: i twin nascono dagli archetipi confermati.",

    confirmOne: "Conferma almeno un archetipo per creare i twin.",

    readyToGenerate: "Archetipi confermati: {n}. Crea i loro twin: potrai parlarci e correggerli.",

    submitFailed:
      "Non è stato possibile portare i twin alla tua approvazione. Ricarica la pagina e riprova.",

    requestPlaceholder:
      "Scrivi che cosa non ti convince nei profili: la nota resta nella cronologia delle decisioni.",

    decisionResume: "Hai messo in pausa questa decisione. Riprendila quando sei pronto.",

    profileDetails: "Vedi il profilo",

    evidenceDetails: "Da dove nasce questa informazione",

    knowledgeSource: "Da dove proviene questa informazione?",

    edit: "Correggi",

    editField: "Correggi {field}",

    observationUnavailable: "Questa informazione è di sola lettura.",

    revisionValue: "Nuovo valore",

    revisionItemsHint: "Inserisci un elemento per riga.",

    userProvided: "Fornito dal proprietario / utente",

    humanValidated: "Validato da una persona",

    humanValidatedWarning:
      "Scegli Validato da una persona solo se qualcuno ha verificato questa informazione. Approvare il profilo, da solo, non conferma le sue ipotesi.",

    proposeRevision: "Proponi questa modifica",

    diffs: "Modifiche proposte ai profili",

    proposedDiff: "Proposta",

    approvedDiff: "Approvata",

    rejectedDiff: "Rifiutata",

    before: "Prima",

    after: "Dopo",

    approveDiff: "Approva modifica",

    rejectDiff: "Rifiuta modifica",

    diffReason: "Motivazione della decisione",

    otherDecisions: "Altre decisioni",

    approveGate: "Conferma i twin e continua",

    rejectGate: "Rifiuta",

    pause: "Pausa",

    resume: "Riprendi",

    cancelGate: "Annulla approvazione",

    gateReason: "Motivazione della decisione",

    gateReasonHint: "Serve per rifiutare i profili.",

    gateMethodology:
      "La tua approvazione permette al progetto di usare questi profili. Non significa che le loro ipotesi siano state verificate con utenti reali.",

    currentSnapshotApproved: "Hai approvato questi profili degli utenti.",

    ready: "Pronto per la Definizione.",

    notReady: "Controlla e approva i profili degli utenti per proseguire.",

    stale: "I profili sono cambiati dalla tua ultima approvazione. Controllali di nuovo.",

    revisionRequested:
      "Hai chiesto modifiche. Correggi i twin: la nuova versione tornerà alla tua approvazione.",

    revisionNote: "La tua nota: «{note}»",

    cancelled:
      "Hai annullato questa decisione. Correggi un twin per prepararne una nuova versione.",

    rejected: "Hai rifiutato questi profili. Correggi un twin per prepararne una nuova versione.",

    pausedNeedsHuman: "La decisione è ferma e serve il tuo intervento.",

    technicalSummary: "Versione {number} · {state}",

    technicalProfiles: "Archetipi proposti · twin non ancora creati",

    technicalEmpty: "Ancora nessun archetipo",

    stateApproved: "approvata",

    statePending: "in attesa della tua decisione",

    stateDraft: "in preparazione",

    contentHash: "Hash del contenuto",

    gateStatus: "Approvazione",

    workflow: "Stato del flusso",

    decisionCounter: "Decisione n. {n}",

    technicalTwins: "Twin",

    technicalPersonas: "Archetipi",

    persistedLifecycle: "Ciclo di vita salvato",

    effectiveLifecycle: "Ciclo di vita effettivo",

    unknown: "Sconosciuto",

    abstained: "Astensione",

    empty: "Nessun valore",

    requiredReason: "Per questa decisione è richiesta una motivazione.",

    requiredValue: "Inserisci un valore prima di proporre la revisione.",

    invalidField: "L'osservazione selezionata non corrisponde a un campo User Twin.",

    projectMissing: "Sono richiesti progetto e access token.",

    profileInformation: "Informazione sul profilo",
  },
} as const;

export const archetypeTexts = {
  it: {
    heading: "Archetipi",
    add: "Aggiungi archetipo",
    edit: "Modifica",
    remove: "Rimuovi",
    confirm: "Rimuovi archetipo",
    cancel: "Annulla",
    archive:
      "L'archetipo sarà archiviato e lo storico resterà disponibile. I twin dovranno essere aggiornati; requisiti e design che citano il twin rimosso possono richiedere una nuova preparazione.",
    stale:
      "Gli archetipi sono cambiati. Genera i twin aggiornati e approvali: i riferimenti precedenti restano nello storico.",
    contested: "Contestato",
    rationale: "Perché contesti questa informazione?",
  },
  en: {
    heading: "Archetypes",
    add: "Add archetype",
    edit: "Edit",
    remove: "Remove",
    confirm: "Remove archetype",
    cancel: "Cancel",
    archive:
      "The archetype will be archived and its history preserved. The twins will need updating; requirements and design that cite the removed twin may need preparing again.",
    stale:
      "The archetypes changed. Generate the updated twins and approve them: earlier references remain in the history.",
    contested: "Contested",
    rationale: "Why do you contest this information?",
  },
};
