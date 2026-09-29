from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "twins.help": {
        "it": "Parla con gli User Twin del progetto e chiedi loro di rivedere il design",
        "en": "Talk to the User Twins of the project and ask them to review the design",
    },
    "twins.option_action": {
        "it": "che cosa fare: list, show, ask oppure review; senza azione elenca i twin",
        "en": "what to do: list, show, ask or review; without an action the twins are listed",
    },
    "twins.help_list": {"it": "elenca i twin del progetto", "en": "list the twins of the project"},
    "twins.help_show": {"it": "mostra un twin per intero", "en": "show one twin in full"},
    "twins.help_ask": {
        "it": "fa una domanda a un twin, oppure apre una conversazione",
        "en": "ask a twin one question, or open a conversation",
    },
    "twins.help_review": {
        "it": "fa rivedere ai twin il design scelto",
        "en": "let the twins review the chosen design",
    },
    "twins.option_twin": {
        "it": "numero del twin nell'elenco, oppure l'inizio del suo nome",
        "en": "number of the twin in the list, or the beginning of its name",
    },
    "twins.option_question": {
        "it": "la domanda; senza domanda si apre una conversazione",
        "en": "the question; without it a conversation opens",
    },
    "twins.list_heading": {"it": "User Twin di «{project}»", "en": 'User Twins of "{project}"'},
    "twins.none": {
        "it": "In questa versione non c'è nessun twin.",
        "en": "There is no twin in this version.",
    },
    "twins.column_number": {"it": "N.", "en": "No."},
    "twins.column_name": {"it": "Nome", "en": "Name"},
    "twins.column_role": {"it": "Ruolo", "en": "Role"},
    "twins.column_wants": {"it": "Che cosa vuole", "en": "What they want"},
    "twins.hint_show": {
        "it": "Per vedere un twin per intero: `ut twins show {number}`.",
        "en": "To see a twin in full: `ut twins show {number}`.",
    },
    "twins.hint_ask": {
        "it": "Per fargli una domanda: `ut twins ask {number}`.",
        "en": "To ask it a question: `ut twins ask {number}`.",
    },
    "twins.role": {"it": "Ruolo: {role}", "en": "Role: {role}"},
    "twins.section_goals": {"it": "Obiettivi", "en": "Goals"},
    "twins.section_obstacles": {"it": "Che cosa è di ostacolo", "en": "What holds them back"},
    "twins.section_context": {"it": "Contesto d'uso", "en": "Context of use"},
    "twins.section_observations": {
        "it": "Tutte le osservazioni, con la loro origine",
        "en": "Every observation, with its origin",
    },
    "twins.observation": {
        "it": "{label}: {value} (origine: {origin})",
        "en": "{label}: {value} (origin: {origin})",
    },
    "twins.observation_why": {
        "it": "{line}. Perché: {rationale}",
        "en": "{line}. Why: {rationale}",
    },
    "twins.field_role": {"it": "Ruolo", "en": "Role"},
    "twins.field_age_range": {"it": "Fascia di età", "en": "Age range"},
    "twins.field_expertise": {"it": "Competenze", "en": "Expertise"},
    "twins.field_goals": {"it": "Obiettivi", "en": "Goals"},
    "twins.field_recurring_tasks": {"it": "Attività ricorrenti", "en": "Recurring tasks"},
    "twins.field_context_of_use": {"it": "Contesto d'uso", "en": "Context of use"},
    "twins.field_information_needs": {"it": "Bisogni informativi", "en": "Information needs"},
    "twins.field_decision_criteria": {"it": "Criteri decisionali", "en": "Decision criteria"},
    "twins.field_preferred_vocabulary": {
        "it": "Vocabolario preferito",
        "en": "Preferred vocabulary",
    },
    "twins.field_frustrations": {"it": "Frustrazioni", "en": "Frustrations"},
    "twins.field_pain_points": {"it": "Difficoltà", "en": "Pain points"},
    "twins.field_trust_concerns": {
        "it": "Preoccupazioni sulla fiducia",
        "en": "Trust concerns",
    },
    "twins.field_accessibility_needs": {
        "it": "Esigenze di accessibilità",
        "en": "Accessibility needs",
    },
    "twins.field_operational_constraints": {
        "it": "Vincoli operativi",
        "en": "Operational constraints",
    },
    "twins.field_technical_literacy": {"it": "Competenza tecnica", "en": "Technical literacy"},
    "twins.field_risk_sensitivity": {"it": "Sensibilità al rischio", "en": "Risk sensitivity"},
    "twins.field_assumptions": {"it": "Assunzioni", "en": "Assumptions"},
    "twins.not_known": {"it": "non noto", "en": "not known"},
    "twins.abstained": {
        "it": "il modello non si è pronunciato",
        "en": "the model gave no answer",
    },
    "twins.value_reason": {"it": "{value} ({reason})", "en": "{value} ({reason})"},
    "twins.status_model_inferred": {"it": "ipotesi del modello", "en": "model suggestion"},
    "twins.status_unsupported_assumption": {
        "it": "ipotesi non confermata",
        "en": "unverified assumption",
    },
    "twins.status_user_provided": {
        "it": "informazione data da una persona",
        "en": "provided by a person",
    },
    "twins.status_human_validated": {
        "it": "verificato da una persona",
        "en": "reviewed by a person",
    },
    "twins.status_empirically_supported": {
        "it": "supportato da osservazioni reali",
        "en": "supported by real observations",
    },
    "twins.needs_review": {"it": "{status}, da verificare", "en": "{status}, to be checked"},
    "twins.source_kind_project_brief": {"it": "brief del progetto", "en": "project brief"},
    "twins.source_kind_owner_input": {"it": "indicazioni tue", "en": "your input"},
    "twins.source_kind_empirical_research": {
        "it": "ricerca con utenti reali",
        "en": "research with real users",
    },
    "twins.source_kind_human_review": {
        "it": "revisione di una persona",
        "en": "review by a person",
    },
    "twins.source_kind_model_output": {"it": "proposta del modello", "en": "model proposal"},
    "twins.source_kind_system_artifact": {
        "it": "documento dello Studio",
        "en": "document of the Studio",
    },
    "twins.origin_sources": {
        "it": "{status}; fonti: {sources}",
        "en": "{status}; sources: {sources}",
    },
    "twins.no_match": {
        "it": "Nessun twin corrisponde a «{value}». Ecco i twin del progetto:",
        "en": 'No twin matches "{value}". These are the twins of the project:',
    },
    "twins.which": {
        "it": "Più twin corrispondono a «{value}»: quale intendi?",
        "en": 'More than one twin matches "{value}": which one do you mean?',
    },
    "twins.offline_unreachable": {
        "it": "Lo Studio {studio} non risponde: ecco i twin salvati {source}.",
        "en": "The Studio {studio} does not answer: here are the twins saved {source}.",
    },
    "twins.offline_not_signed_in": {
        "it": "Non hai eseguito l'accesso allo Studio {studio}: ecco i twin salvati {source}. "
        "Per parlare con loro accedi con `ut login`.",
        "en": "You are not signed in to the Studio {studio}: here are the twins saved {source}. "
        "To talk to them, sign in with `ut login`.",
    },
    "twins.offline_session_expired": {
        "it": "L'accesso allo Studio {studio} è scaduto: ecco i twin salvati {source}. "
        "Per parlare con loro accedi di nuovo con `ut login`.",
        "en": "Your sign-in to the Studio {studio} has expired: here are the twins saved "
        "{source}. To talk to them, sign in again with `ut login`.",
    },
    "twins.source_folder": {
        "it": "nella cartella di conoscenza {path} (versione {version})",
        "en": "in the knowledge folder {path} (version {version})",
    },
    "twins.source_folder_plain": {
        "it": "nella cartella di conoscenza {path}",
        "en": "in the knowledge folder {path}",
    },
    "twins.source_step": {
        "it": "nel passo approvato {path}",
        "en": "in the approved step {path}",
    },
    "twins.simulated": {
        "it": "Le risposte dei twin sono simulate dal modello: sono ipotesi da valutare, non "
        "opinioni di persone reali.",
        "en": "The answers of the twins are simulated by the model: they are hypotheses to "
        "weigh, not opinions of real people.",
    },
    "twins.conversation_hint": {
        "it": "Scrivi una domanda e premi Invio. Per finire scrivi /esci. Ogni risposta è una "
        "piccola spesa del modello.",
        "en": "Write a question and press Enter. To finish write /quit. Each answer is a small "
        "spending of the model.",
    },
    "twins.you": {"it": "Tu:", "en": "You:"},
    "twins.answer_by": {"it": "{name}:", "en": "{name}:"},
    "twins.previous_turns": {
        "it": "Conversazione precedente con {name} (domande mostrate: {count}):",
        "en": "Earlier conversation with {name} (questions shown: {count}):",
    },
    "twins.twin_changed": {
        "it": "Il twin {name} è cambiato dall'ultima conversazione: ne comincia una nuova.",
        "en": "The twin {name} has changed since the last conversation: a new one starts.",
    },
    "twins.question_too_long": {
        "it": "La domanda è troppo lunga: al massimo {limit} caratteri. Accorciala e riprova.",
        "en": "The question is too long: at most {limit} characters. Shorten it and try again.",
    },
    "twins.answer_failed": {
        "it": "{name} non ha potuto rispondere: il modello non ha dato una risposta valida "
        "oppure non era raggiungibile ({code}). Puoi fare di nuovo la domanda: è una nuova "
        "spesa, e prima ti mostro di nuovo la stima.",
        "en": "{name} could not answer: the model gave no valid answer or could not be "
        "reached ({code}). You can ask the question again: it is a new spending, and the "
        "estimate is shown again first.",
    },
    "twins.conversation_changed": {
        "it": "Nel frattempo la conversazione con {name} è cambiata, forse dalla pagina dello "
        "Studio: ho letto di nuovo le ultime domande. Fai di nuovo la tua domanda.",
        "en": "The conversation with {name} changed in the meantime, perhaps from the page of "
        "the Studio: the latest questions were read again. Ask your question again.",
    },
    "twins.conversation_end": {
        "it": "Conversazione finita: domande e risposte restano salvate nello Studio.",
        "en": "Conversation ended: questions and answers stay saved in the Studio.",
    },
    "twins.errors.TWINS_NOT_APPROVED": {
        "it": "I twin di questo progetto non sono ancora approvati, oppure vanno approvati di "
        "nuovo dopo un cambiamento del brief o della squadra. Confermali con `ut init`, poi "
        "riprova.",
        "en": "The twins of this project are not approved yet, or they must be approved again "
        "after a change of the brief or of the team. Confirm them with `ut init`, then try "
        "again.",
    },
    "twins.errors.TWIN_QUESTION_TOO_LONG": {
        "it": "La domanda è troppo lunga: al massimo {limit} caratteri. Accorciala e rilancia "
        "il comando.",
        "en": "The question is too long: at most {limit} characters. Shorten it and launch the "
        "command again.",
    },
    "twins.errors.TWIN_ANSWER_FAILED": {
        "it": "{name} non ha potuto rispondere: il modello non ha dato una risposta valida "
        "oppure non era raggiungibile ({code}). Puoi fare di nuovo la domanda rilanciando il "
        "comando: è una nuova spesa, e prima ti mostro di nuovo la stima.",
        "en": "{name} could not answer: the model gave no valid answer or could not be "
        "reached ({code}). You can ask the question again by launching the command again: it "
        "is a new spending, and the estimate is shown again first.",
    },
    "twins.errors.TWIN_CHAT_MODEL_NOT_CONFIGURED": {
        "it": "Il modello che dà voce ai twin non è collegato allo Studio. Chiedi a chi "
        "gestisce lo Studio di collegarlo, poi riprova.",
        "en": "The model that plays the twins is not connected to the Studio. Ask whoever runs "
        "the Studio to connect it, then try again.",
    },
    "twins.errors.TWIN_CONVERSATION_CHANGED": {
        "it": "Nel frattempo la conversazione è cambiata, forse dalla pagina dello Studio. "
        "Rilancia il comando per fare la domanda.",
        "en": "The conversation changed in the meantime, perhaps from the page of the Studio. "
        "Launch the command again to ask the question.",
    },
    "twins.errors.TWIN_CONVERSATION_FULL": {
        "it": "Questa conversazione è piena: il twin non accetta altre domande. Puoi "
        "continuare con gli altri twin del progetto.",
        "en": "This conversation is full: the twin takes no more questions. You can go on "
        "with the other twins of the project.",
    },
    "twins.errors.TWIN_QUESTION_INVALID": {
        "it": "La domanda non si può inviare: riscrivila con parole semplici, in al massimo "
        "1000 caratteri.",
        "en": "The question cannot be sent: write it again with plain words, in at most 1000 "
        "characters.",
    },
    "twins.errors.USER_TWIN_NOT_FOUND": {
        "it": "Questo twin non è più tra i twin del progetto: guarda l'elenco aggiornato con "
        "`ut twins`.",
        "en": "This twin is no longer among the twins of the project: see the updated list "
        "with `ut twins`.",
    },
    "twins.errors.GENERATION_BUDGET_EXCEEDED": {
        "it": "Lo Studio ha rifiutato la richiesta ai twin perché supererebbe un tetto di "
        "spesa. Chi gestisce lo Studio può alzarlo; poi potrai riprovare.",
        "en": "The Studio refused the request to the twins because it would go over a spending "
        "ceiling. Whoever runs the Studio can raise it; then you can try again.",
    },
    "twins.errors.DATABASE_UNAVAILABLE": {
        "it": "Lo Studio non riesce a usare il suo archivio dati in questo momento. Riprova "
        "tra poco.",
        "en": "The Studio cannot use its database right now. Try again in a moment.",
    },
}
