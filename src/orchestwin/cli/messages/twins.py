from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "twins.option_evidence": {
        "it": "Proponi aggiornamenti da questa fonte EVD-001.",
        "en": "Propose updates from this EVD-001 source.",
    },
    "twins.update_evidence": {
        "it": "Fonte {source}, versione {version}. Cambiamenti rifiutati dal controllo della citazione: {count}.",
        "en": "Source {source}, version {version}. Changes rejected by citation verification: {count}.",
    },
    "twins.update_citation": {
        "it": "{effect} su {field}, fonte v{version}, righe {first}-{last}: «{quote}»",
        "en": "{effect} on {field}, source v{version}, lines {first}-{last}: “{quote}”",
    },
    "twins.help_persona": {
        "it": "Mostra la Persona derivata dal User Twin",
        "en": "Show the Persona derived from the User Twin",
    },
    "twins.option_why": {
        "it": "mostra valore, stato, motivazione e fonti del campo",
        "en": "show the field's value, status, rationale and sources",
    },
    "twins.option_json": {"it": "mostra i dati JSON", "en": "show the JSON data"},
    "twins.persona_heading": {"it": "Persona · {name}", "en": "Persona · {name}"},
    "twins.basis": {"it": "Fondamento: {basis}", "en": "Basis: {basis}"},
    "twins.basis_provisional": {"it": "Provvisorio", "en": "Provisional"},
    "twins.basis_evidence_based": {"it": "Fondato su evidenze", "en": "Evidence based"},
    "twins.provisional_note": {
        "it": "Il brief e le scelte del proprietario non sono evidenze su utenti reali.",
        "en": "The brief and the owner's choices are not evidence about real users.",
    },
    "twins.status_evidenced": {"it": "Evidenziato", "en": "Evidenced"},
    "twins.status_inferred": {"it": "Dedotto", "en": "Inferred"},
    "twins.status_hypothesized": {"it": "Ipotizzato", "en": "Hypothesized"},
    "twins.status_contested": {"it": "Contestato", "en": "Contested"},
    "twins.status_unknown": {"it": "Sconosciuto", "en": "Unknown"},
    "twins.persona_description": {"it": "Descrizione", "en": "Description"},
    "twins.persona_goals": {"it": "Obiettivi", "en": "Goals"},
    "twins.persona_needs": {"it": "Bisogni", "en": "Needs"},
    "twins.persona_behaviours": {"it": "Comportamenti", "en": "Behaviours"},
    "twins.persona_pain_points": {"it": "Difficoltà", "en": "Pain points"},
    "twins.persona_constraints": {"it": "Vincoli", "en": "Constraints"},
    "twins.persona_contexts": {"it": "Contesti", "en": "Contexts"},
    "twins.persona_represents": {"it": "Chi rappresenta", "en": "Represents"},
    "twins.persona_does_not_represent": {"it": "Chi non rappresenta", "en": "Does not represent"},
    "twins.persona_evidence_gaps": {"it": "Lacune nelle evidenze", "en": "Evidence gaps"},
    "twins.field_description": {"it": "Descrizione", "en": "Description"},
    "twins.field_represents": {"it": "Chi rappresenta", "en": "Represents"},
    "twins.field_does_not_represent": {"it": "Chi non rappresenta", "en": "Does not represent"},
    "twins.field_evidence_gaps": {"it": "Lacune nelle evidenze", "en": "Evidence gaps"},
    "twins.origin_contested": {"it": "contestato", "en": "contested"},
    "twins.why": {"it": "Perché?", "en": "Why?"},
    "twins.no_rationale": {"it": "Motivazione non fornita.", "en": "Rationale not provided."},
    "twins.no_sources": {"it": "Fonti non fornite.", "en": "Sources not provided."},
    "twins.help": {
        "it": "Parla con gli User Twin del progetto, chiedi loro di rivedere il design e segui "
        "quello che imparano durante lo sviluppo",
        "en": "Talk to the User Twins of the project, ask them to review the design and follow "
        "what they learn during the development",
    },
    "twins.option_action": {
        "it": "che cosa fare: list, show, ask, review, update, learn oppure forget; senza azione "
        "elenca i twin",
        "en": "what to do: list, show, ask, review, update, learn or forget; without an action "
        "the twins are listed",
    },
    "twins.help_update": {
        "it": "propone che cosa hanno imparato i twin dalle loro ultime critiche (una "
        "generazione del modello per ogni twin) e te lo fa rivedere",
        "en": "propose what the twins learned from their latest critiques (one generation of the "
        "model for each twin) and let you review it",
    },
    "twins.help_learn": {
        "it": "scrivi tu una cosa che un twin ha imparato (nessuna spesa)",
        "en": "write yourself something a twin learned (no spending)",
    },
    "twins.help_forget": {
        "it": "ritira un'osservazione che un twin aveva imparato (nessuna spesa)",
        "en": "retire an observation a twin had learned (no spending)",
    },
    "twins.option_update_twin": {
        "it": "numero del twin nell'elenco, oppure l'inizio del suo nome; senza, ogni twin con "
        "nuove critiche",
        "en": "number of the twin in the list, or the beginning of its name; without it, every "
        "twin with new critiques",
    },
    "twins.option_text": {
        "it": "quello che il twin ha imparato, in una frase",
        "en": "what the twin learned, in one sentence",
    },
    "twins.option_code": {
        "it": "codice dell'osservazione appresa, per esempio OBS-001",
        "en": "code of the learned observation, for example OBS-001",
    },
    "twins.option_reason": {
        "it": "perché ritiri l'osservazione (facoltativo)",
        "en": "why you retire the observation (optional)",
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
    "twins.column_version": {"it": "Versione", "en": "Version"},
    "twins.column_learned": {"it": "Apprese", "en": "Learned"},
    "twins.hint_pending": {
        "it": "Una proposta di ciò che {name} ha imparato aspetta la tua revisione: "
        "`ut twins update {number}` la riprende senza nuova spesa.",
        "en": "A proposal of what {name} learned waits for your review: "
        "`ut twins update {number}` takes it up again without spending.",
    },
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
    "twins.section_learned": {
        "it": "Appreso durante lo sviluppo (versione {label})",
        "en": "Learned during the development (version {label})",
    },
    "twins.learned_observation": {
        "it": "{code}: {statement} ({origin})",
        "en": "{code}: {statement} ({origin})",
    },
    "twins.learned_from_critiques": {
        "it": "dalle sue critiche, approvata da te il {date}",
        "en": "from its own critiques, approved by you on {date}",
    },
    "twins.learned_from_owner": {
        "it": "scritta da te il {date}",
        "en": "written by you on {date}",
    },
    "twins.learned_on": {"it": "approvata il {date}", "en": "approved on {date}"},
    "twins.learned_contradiction": {
        "it": "{line}. Attenzione, contraddice il profilo: {text}",
        "en": "{line}. Warning, it contradicts the profile: {text}",
    },
    "twins.learned_none": {
        "it": "Non ha ancora imparato niente durante lo sviluppo: `ut twins update` propone ciò "
        "che ha imparato dalle sue ultime critiche, `ut twins learn` ti fa scrivere "
        "un'osservazione.",
        "en": "It has not learned anything yet during the development: `ut twins update` "
        "proposes what it learned from its latest critiques, `ut twins learn` lets you write "
        "an observation yourself.",
    },
    "twins.learned_none_active": {
        "it": "Nessuna osservazione appresa è in uso.",
        "en": "No learned observation is in use.",
    },
    "twins.learned_retired": {
        "it": "Osservazioni ritirate: {count}.",
        "en": "Retired observations: {count}.",
    },
    "twins.learned_pending": {
        "it": "Una proposta di ciò che ha imparato aspetta la tua revisione: "
        "`ut twins update {number}` la riprende senza nuova spesa.",
        "en": "A proposal of what it learned waits for your review: `ut twins update {number}` "
        "takes it up again without spending.",
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
        "it": "I twin di questo progetto non sono ancora approvati, oppure sono rimasti indietro "
        "dopo un cambiamento del brief o delle prospettive. Se sono indietro aggiornali con "
        "`ut sections update`, altrimenti confermali con `ut init`; poi riprova.",
        "en": "The twins of this project are not approved yet, or they fell behind after a "
        "change of the brief or of the perspectives. If they are behind, update them with "
        "`ut sections update`; otherwise confirm them with `ut init`. Then try again.",
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
    "twins.update_unsupported": {
        "it": "Questo Studio non tiene ancora traccia di ciò che imparano i twin: è più vecchio "
        "di questa versione di ut. Aggiorna lo Studio, poi riprova.",
        "en": "This Studio does not keep track yet of what the twins learn: it is older than "
        "this version of ut. Update the Studio, then try again.",
    },
    "twins.update_no_model": {
        "it": "Lo Studio non ha un modello collegato, quindi non può proporre che cosa hanno "
        "imparato i twin (TWIN_UPDATE_MODEL_NOT_CONFIGURED). Puoi comunque scrivere tu "
        "un'osservazione con `ut twins learn`; chi gestisce lo Studio può collegare un modello.",
        "en": "The Studio has no model connected, so it cannot propose what the twins learned "
        "(TWIN_UPDATE_MODEL_NOT_CONFIGURED). You can still write an observation yourself with "
        "`ut twins learn`; whoever runs the Studio can connect a model.",
    },
    "twins.update_resumed": {
        "it": "Una proposta di ciò che {name} ha imparato aspettava già la tua revisione: la "
        "riprendo, senza nuova spesa.",
        "en": "A proposal of what {name} learned was already waiting for your review: it is "
        "taken up again, without spending.",
    },
    "twins.update_nothing_new": {
        "it": "{name} non ha nuove critiche dal suo ultimo aggiornamento: non c'è niente di "
        "nuovo da imparare.",
        "en": "{name} has no new critiques since its latest update: there is nothing new to learn.",
    },
    "twins.update_to_generate": {
        "it": "Proposte da generare, una per ogni twin con nuove critiche: {names}.",
        "en": "Proposals to generate, one for each twin with new critiques: {names}.",
    },
    "twins.update_label": {
        "it": "Proposta di ciò che {name} ha imparato",
        "en": "Proposal of what {name} learned",
    },
    "twins.update_already_waiting": {
        "it": "Nel frattempo una proposta di ciò che {name} ha imparato era già pronta: la "
        "riprendo senza nuova spesa.",
        "en": "Meanwhile a proposal of what {name} learned was already made: it is taken up "
        "again without spending.",
    },
    "twins.update_heading": {
        "it": "Cosa ha imparato {name} (versione {label})",
        "en": "What {name} learned (version {label})",
    },
    "twins.update_material": {
        "it": "Critiche da cui ha imparato: commit {changes}, esecuzioni dei test {tests}.",
        "en": "Critiques it learned from: commits {changes}, test runs {tests}.",
    },
    "twins.update_comment": {"it": "{name} dice: {comment}", "en": "{name} says: {comment}"},
    "twins.update_empty": {
        "it": "{name} non ha trovato niente di nuovo da imparare nelle sue ultime critiche: non "
        "c'è niente da decidere.",
        "en": "{name} found nothing new to learn in its latest critiques: there is nothing to "
        "decide.",
    },
    "twins.update_how": {
        "it": "Per ogni osservazione rispondi t per tenerla, c per correggerla o s per "
        "scartarla; senza risposta la tieni.",
        "en": "For each observation answer k to keep it, e to edit it or d to drop it; nothing "
        "typed keeps it.",
    },
    "twins.update_observation": {
        "it": "Osservazione {number} di {count}: {statement}",
        "en": "Observation {number} of {count}: {statement}",
    },
    "twins.update_basis": {"it": "Perché: {basis}", "en": "Why: {basis}"},
    "twins.update_about": {"it": "Riguarda: {about}", "en": "About: {about}"},
    "twins.about_requirement": {
        "it": "requisito {code} «{title}»",
        "en": 'requirement {code} "{title}"',
    },
    "twins.about_requirement_code": {"it": "requisito {code}", "en": "requirement {code}"},
    "twins.about_screen": {
        "it": "schermata {code} «{title}»",
        "en": 'screen {code} "{title}"',
    },
    "twins.about_screen_code": {"it": "schermata {code}", "en": "screen {code}"},
    "twins.update_contradiction": {
        "it": "Attenzione: contraddice il profilo del twin ({text}). Il profilo non cambia qui: "
        "si rivede nello Studio, e rivederlo riapre il design.",
        "en": "Warning: it contradicts the profile of the twin ({text}). The profile does not "
        "change here: it is revised in the Studio, and revising it reopens the design.",
    },
    "twins.update_question": {
        "it": "Tieni, correggi o scarta? [t/c/s]",
        "en": "Keep, edit or drop? [k/e/d]",
    },
    "twins.update_answer_invalid": {
        "it": "Rispondi t per tenerla, c per correggerla o s per scartarla.",
        "en": "Answer k to keep it, e to edit it or d to drop it.",
    },
    "twins.update_edit": {
        "it": "Scrivi la frase corretta in una riga (senza risposta resta quella proposta):",
        "en": "Write the corrected sentence in one line (nothing typed keeps the proposed one):",
    },
    "twins.update_edit_too_long": {
        "it": "La frase è troppo lunga: al massimo {limit} caratteri. Scrivila di nuovo.",
        "en": "The sentence is too long: at most {limit} characters. Write it again.",
    },
    "twins.update_reason": {
        "it": "Non tieni nessuna osservazione: perché scarti la proposta? Una riga, puoi "
        "lasciarla vuota:",
        "en": "You keep no observation: why do you drop the proposal? One line, it may stay empty:",
    },
    "twins.update_reason_too_long": {
        "it": "Il motivo è troppo lungo: al massimo {limit} caratteri. Scrivilo di nuovo.",
        "en": "The reason is too long: at most {limit} characters. Write it again.",
    },
    "twins.update_approved": {
        "it": "{name} è ora alla versione {label} e ha imparato: {codes}.",
        "en": "{name} is now at version {label} and learned: {codes}.",
    },
    "twins.update_evidence_approved": {
        "it": "{name} è ora alla versione {label}. Modifiche approvate dalla fonte {source} "
        "v{version}: {count}.",
        "en": "{name} is now at version {label}. Approved changes from source {source} "
        "v{version}: {count}.",
    },
    "twins.update_rejected": {
        "it": "{name} non ha imparato niente da questa proposta, che resta scartata (versione "
        "{label}).",
        "en": "{name} learned nothing from this proposal, which stays dropped (version {label}).",
    },
    "twins.update_left_pending": {
        "it": "La revisione di ciò che {name} ha imparato si è fermata prima della decisione: la "
        "proposta resta in attesa nello Studio e `ut twins update` la riprende senza nuova "
        "spesa.",
        "en": "The review of what {name} learned stopped before the decision: the proposal "
        "stays waiting in the Studio, and `ut twins update` takes it up again without spending.",
    },
    "twins.update_cost": {
        "it": "Costo delle proposte generate ora: {amount} USD.",
        "en": "Cost of the proposals generated now: {amount} USD.",
    },
    "twins.update_failed": {
        "it": "La proposta per {name} non è andata a buon fine ({code}). Puoi rilanciare "
        "`ut twins update` più tardi: se lo Studio l'ha salvata, la riprende senza nuova spesa.",
        "en": "The proposal for {name} did not go through ({code}). You can launch "
        "`ut twins update` again later: if the Studio kept it, it is taken up again without "
        "spending.",
    },
    "twins.update_decision_failed": {
        "it": "La decisione su ciò che {name} ha imparato non è stata registrata ({code}): la "
        "proposta resta in attesa e `ut twins update {number}` la riprende senza nuova spesa.",
        "en": "The decision on what {name} learned was not recorded ({code}): the proposal "
        "stays waiting, and `ut twins update {number}` takes it up again without spending.",
    },
    "twins.update_errors.GENERATION_BUDGET_EXCEEDED": {
        "it": "Lo Studio ha rifiutato la proposta per {name} perché supererebbe un tetto di "
        "spesa: per questo twin non è stato speso niente. Chi gestisce lo Studio può alzare il "
        "tetto, poi rilancia `ut twins update`.",
        "en": "The Studio refused the proposal for {name} because it would go over a spending "
        "ceiling: nothing was spent for this twin. Whoever runs the Studio can raise the "
        "ceiling, then launch `ut twins update` again.",
    },
    "twins.update_errors.GENERATION_BUDGET_EXCEEDED.total": {
        "it": "Lo Studio ha raggiunto il suo tetto di spesa complessivo ({ceiling} USD): la "
        "proposta per {name} non è partita. Chi gestisce lo Studio può alzare il tetto, poi "
        "rilancia `ut twins update`.",
        "en": "The Studio reached its overall spending ceiling ({ceiling} USD): the proposal for "
        "{name} did not start. Whoever runs the Studio can raise the ceiling, then launch "
        "`ut twins update` again.",
    },
    "twins.update_errors.GENERATION_BUDGET_EXCEEDED.project": {
        "it": "Questo progetto ha raggiunto il suo tetto di spesa ({ceiling} USD): la proposta "
        "per {name} non è partita. Chi gestisce lo Studio può alzare il tetto, poi rilancia "
        "`ut twins update`.",
        "en": "This project reached its spending ceiling ({ceiling} USD): the proposal for "
        "{name} did not start. Whoever runs the Studio can raise the ceiling, then launch "
        "`ut twins update` again.",
    },
    "twins.update_errors.GENERATION_BUDGET_EXCEEDED.generation": {
        "it": "La proposta per {name} supererebbe il tetto di spesa di una singola generazione "
        "({ceiling} USD), quindi non è partita. Chi gestisce lo Studio può alzarlo, poi "
        "rilancia `ut twins update`.",
        "en": "The proposal for {name} would go over the spending ceiling of a single "
        "generation ({ceiling} USD), so it did not start. Whoever runs the Studio can raise it, "
        "then launch `ut twins update` again.",
    },
    "twins.update_errors.GENERATION_BUDGET_UNAVAILABLE": {
        "it": "Lo Studio non riesce a leggere quanto è già stato speso, quindi non ha fatto la "
        "proposta per {name}. Riprova più tardi con `ut twins update`.",
        "en": "The Studio cannot read how much has already been spent, so it did not make the "
        "proposal for {name}. Try again later with `ut twins update`.",
    },
    "twins.update_errors.TWIN_UPDATE_MODEL_NOT_CONFIGURED": {
        "it": "Lo Studio non ha un modello collegato, quindi non ha fatto la proposta per "
        "{name} (TWIN_UPDATE_MODEL_NOT_CONFIGURED). Chi gestisce lo Studio può collegarne uno.",
        "en": "The Studio has no model connected, so it did not make the proposal for {name} "
        "(TWIN_UPDATE_MODEL_NOT_CONFIGURED). Whoever runs the Studio can connect one.",
    },
    "twins.update_errors.USER_MODELING_APPROVAL_REQUIRED": {
        "it": "In questo momento gli User Twin non sono approvati, quindi {name} non può "
        "imparare niente: approvali con `ut init`, poi rilancia `ut twins update`.",
        "en": "The User Twins are not approved at the moment, so {name} cannot learn anything: "
        "approve them with `ut init`, then launch `ut twins update` again.",
    },
    "twins.update_errors.REQUIREMENTS_APPROVAL_REQUIRED": {
        "it": "In questo momento i requisiti non sono approvati, quindi {name} non può imparare "
        "niente: approvali con `ut init`, poi rilancia `ut twins update`.",
        "en": "The requirements are not approved at the moment, so {name} cannot learn "
        "anything: approve them with `ut init`, then launch `ut twins update` again.",
    },
    "twins.update_errors.DESIGN_APPROVAL_REQUIRED": {
        "it": "In questo momento il design non è approvato, quindi {name} non può imparare "
        "niente: approvalo con `ut design`, poi rilancia `ut twins update`.",
        "en": "The design is not approved at the moment, so {name} cannot learn anything: "
        "approve it with `ut design`, then launch `ut twins update` again.",
    },
    "twins.update_errors.USER_TWIN_NOT_FOUND": {
        "it": "{name} non è più tra i twin del progetto: guarda l'elenco aggiornato con "
        "`ut twins`.",
        "en": "{name} is no longer among the twins of the project: see the updated list with "
        "`ut twins`.",
    },
    "twins.update_errors.GENERATION_LOST": {
        "it": "La proposta per {name} si è persa, forse perché lo Studio è ripartito. Rilancia "
        "`ut twins update`: se lo Studio l'aveva salvata la riprende senza nuova spesa, "
        "altrimenti ne fa una nuova.",
        "en": "The proposal for {name} was lost, perhaps because the Studio restarted. Launch "
        "`ut twins update` again: if the Studio stored it, it is taken up again without "
        "spending, otherwise a new one is made.",
    },
    "twins.update_errors.GENERATION_STILL_RUNNING": {
        "it": "La proposta per {name} è ancora in preparazione nello Studio: rilancia "
        "`ut twins update` più tardi e la riprenderà senza nuova spesa.",
        "en": "The proposal for {name} is still being made in the Studio: launch "
        "`ut twins update` again later and it will be taken up without spending.",
    },
    "twins.update_errors.TOO_MANY_GENERATIONS": {
        "it": "Nello Studio girano già troppe generazioni, quindi la proposta per {name} non è "
        "partita: aspetta che una finisca, poi rilancia `ut twins update`.",
        "en": "Too many generations are already running in the Studio, so the proposal for "
        "{name} did not start: wait for one to finish, then launch `ut twins update` again.",
    },
    "twins.update_errors.INVALID_PROVIDER_OUTPUT": {
        "it": "Il modello ha dato una risposta che lo Studio non può usare "
        "(INVALID_PROVIDER_OUTPUT): per {name} non è stato salvato niente. Rilanciando "
        "`ut twins update` si riprova, ed è una nuova spesa.",
        "en": "The model gave an answer that the Studio cannot use (INVALID_PROVIDER_OUTPUT): "
        "nothing was stored for {name}. Launching `ut twins update` again tries once more, and "
        "it is a new spending.",
    },
    "twins.update_errors.TWIN_UPDATE_ALREADY_DECIDED": {
        "it": "Nel frattempo la proposta per {name} è già stata decisa, forse da un altro "
        "terminale: questa decisione non è stata registrata. `ut twins show {number}` mostra "
        "che cosa ha imparato.",
        "en": "Meanwhile the proposal for {name} was already decided, perhaps from another "
        "terminal: this decision was not recorded. `ut twins show {number}` shows what it "
        "learned.",
    },
    "twins.update_errors.TWIN_UPDATE_CONTEXT_CHANGED": {
        "it": "Durante la revisione ciò che {name} sa è cambiato (un'osservazione è stata "
        "scritta o ritirata): la proposta non si può più approvare. Rilancia "
        "`ut twins update {number}` e scarta ogni osservazione; dopo se ne potrà generare una "
        "nuova.",
        "en": "What {name} knows changed during the review (an observation was written or "
        "retired): the proposal can no longer be approved. Launch `ut twins update {number}` "
        "again and drop every observation; then a new one can be generated.",
    },
    "twins.update_errors.TWIN_OBSERVATIONS_LIMIT": {
        "it": "{name} terrebbe più di {limit} osservazioni apprese, il massimo: la proposta "
        "resta in attesa. Rilancia `ut twins update {number}` e tienine meno.",
        "en": "{name} would keep more than {limit} learned observations, the most it can keep: "
        "the proposal stays waiting. Launch `ut twins update {number}` again and keep fewer.",
    },
    "twins.update_errors.TWIN_UPDATE_NOT_FOUND": {
        "it": "Lo Studio non trova più la proposta per {name}: rilancia "
        "`ut twins update {number}`.",
        "en": "The Studio no longer finds the proposal for {name}: launch "
        "`ut twins update {number}` again.",
    },
    "twins.learn_done": {
        "it": "{name} ha imparato {code} ed è ora alla versione {label}.",
        "en": "{name} learned {code} and is now at version {label}.",
    },
    "twins.forget_done": {
        "it": "{name} non usa più {code} ed è ora alla versione {label}.",
        "en": "{name} no longer uses {code} and is now at version {label}.",
    },
    "twins.folder_updated": {
        "it": "La cartella di conoscenza contiene ora ciò che hanno imparato i twin (versione "
        "{version}).",
        "en": "The knowledge folder now holds what the twins learned (version {version}).",
    },
    "twins.folder_not_updated": {
        "it": "La cartella di conoscenza non è stata aggiornata ({code}): ciò che hanno "
        "imparato i twin resta nello Studio, e `ut package publish` la scarica più tardi.",
        "en": "The knowledge folder was not updated ({code}): what the twins learned stays in "
        "the Studio, and `ut package publish` downloads it later.",
    },
    "twins.errors.TWINS_TEXT_EMPTY": {
        "it": "Scrivi dopo il twin ciò che ha imparato, per esempio: "
        "`ut twins learn 1 Chi paga legge le cifre da lontano`.",
        "en": "Write after the twin what it learned, for example: "
        "`ut twins learn 1 People who pay read the digits from a distance`.",
    },
    "twins.errors.TWINS_TEXT_TOO_LONG": {
        "it": "L'osservazione è troppo lunga: al massimo {limit} caratteri. Accorciala e "
        "rilancia il comando.",
        "en": "The observation is too long: at most {limit} characters. Shorten it and launch "
        "the command again.",
    },
    "twins.errors.TWINS_CODE_INVALID": {
        "it": "«{observation}» non è il codice di un'osservazione appresa: scrivilo come "
        "OBS-001 (`ut twins show` mostra i codici).",
        "en": '"{observation}" is not the code of a learned observation: write it like OBS-001 '
        "(`ut twins show` shows the codes).",
    },
    "twins.errors.TWINS_REASON_TOO_LONG": {
        "it": "Il motivo è troppo lungo: al massimo {limit} caratteri. Accorcialo e rilancia il "
        "comando.",
        "en": "The reason is too long: at most {limit} characters. Shorten it and launch the "
        "command again.",
    },
    "twins.errors.TWIN_OBSERVATIONS_LIMIT": {
        "it": "{name} tiene già {limit} osservazioni apprese, il massimo: ritirane una con "
        "`ut twins forget {number} CODE`, poi riprova.",
        "en": "{name} already keeps {limit} learned observations, the most it can keep: retire "
        "one with `ut twins forget {number} CODE`, then try again.",
    },
    "twins.errors.TWIN_UPDATE_PENDING": {
        "it": "Una proposta di ciò che {name} ha imparato aspetta la tua revisione: decidi "
        "prima su quella con `ut twins update {number}` (senza nuova spesa), poi riprova.",
        "en": "A proposal of what {name} learned waits for your review: decide on it first with "
        "`ut twins update {number}` (no new spending), then try again.",
    },
    "twins.errors.TWIN_OBSERVATION_NOT_FOUND": {
        "it": "{name} non ha un'osservazione appresa in uso con il codice {observation}: "
        "`ut twins show {number}` mostra quelle che usa.",
        "en": "{name} has no learned observation in use with the code {observation}: "
        "`ut twins show {number}` shows the ones it uses.",
    },
    "twins.errors.USER_MODELING_APPROVAL_REQUIRED": {
        "it": "In questo momento gli User Twin non sono approvati, quindi ciò che hanno "
        "imparato non può cambiare: approvali con `ut init`, poi riprova.",
        "en": "The User Twins are not approved at the moment, so what they learned cannot "
        "change: approve them with `ut init`, then try again.",
    },
}
