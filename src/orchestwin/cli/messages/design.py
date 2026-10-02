from __future__ import annotations

from typing import Final

VISUAL_WORDS: Final[dict[str, dict[str, tuple[str, str]]]] = {
    "archetype": {
        "GUIDED_STEPS": ("a passi guidati", "guided steps"),
        "SINGLE_CARD": ("a scheda unica", "single card"),
        "LIST_DETAIL": ("a elenco e dettaglio", "list and detail"),
        "DASHBOARD": ("a cruscotto", "dashboard"),
        "SPLIT_SCREEN": ("a schermo diviso", "split screen"),
        "CONVERSATIONAL": ("a conversazione", "conversational"),
        "TABLE_FIRST": ("a tabella", "table first"),
        "CARD_GALLERY": ("a galleria di schede", "card gallery"),
        "FEED_TIMELINE": ("a flusso cronologico", "feed and timeline"),
        "KANBAN_BOARD": ("a bacheca kanban", "kanban board"),
        "SEARCH_FIRST": ("con la ricerca in primo piano", "search first"),
        "FOCUS_MODE": ("un passo alla volta", "focus mode"),
    },
    "hue_family": {
        "CRIMSON": ("cremisi", "crimson"),
        "CORAL": ("corallo", "coral"),
        "TERRACOTTA": ("terracotta", "terracotta"),
        "AMBER": ("ambra", "amber"),
        "OCHRE": ("ocra", "ochre"),
        "OLIVE": ("oliva", "olive"),
        "FOREST": ("verde bosco", "forest green"),
        "EMERALD": ("smeraldo", "emerald"),
        "TEAL": ("ottanio", "teal"),
        "OCEAN": ("oceano", "ocean blue"),
        "COBALT": ("cobalto", "cobalt"),
        "INDIGO": ("indaco", "indigo"),
        "VIOLET": ("viola", "violet"),
        "PLUM": ("prugna", "plum"),
        "MAGENTA": ("magenta", "magenta"),
        "ROSE": ("rosa", "rose"),
        "SLATE": ("ardesia", "slate"),
        "GRAPHITE": ("grafite", "graphite"),
        "SAND": ("sabbia", "sand"),
    },
    "color_mode": {
        "LIGHT": ("chiara", "light"),
        "DARK": ("scura", "dark"),
        "HIGH_CONTRAST_LIGHT": ("chiara ad alto contrasto", "high-contrast light"),
        "HIGH_CONTRAST_DARK": ("scura ad alto contrasto", "high-contrast dark"),
    },
    "tone": {
        "ESSENTIAL": ("essenziale", "essential"),
        "WARM": ("caloroso", "warm"),
        "INSTITUTIONAL": ("istituzionale", "institutional"),
        "PLAYFUL": ("giocoso", "playful"),
        "TECHNICAL": ("tecnico", "technical"),
        "EDITORIAL": ("editoriale", "editorial"),
        "LUXURIOUS": ("lussuoso", "luxurious"),
        "ENERGETIC": ("energico", "energetic"),
        "CALM": ("calmo", "calm"),
        "RUSTIC": ("rustico", "rustic"),
        "FUTURISTIC": ("futuristico", "futuristic"),
        "CLINICAL": ("clinico", "clinical"),
        "ARTISANAL": ("artigianale", "artisanal"),
        "CIVIC": ("civico", "civic"),
    },
    "heading_family": {
        "HUMANIST_SANS": ("senza grazie umanistico", "humanist sans"),
        "GEOMETRIC_SANS": ("senza grazie geometrico", "geometric sans"),
        "GROTESQUE_SANS": ("senza grazie grottesco", "grotesque sans"),
        "SOFT_SANS": ("senza grazie morbido", "soft sans"),
        "NARROW_SANS": ("senza grazie stretto", "narrow sans"),
        "WIDE_SANS": ("senza grazie largo", "wide sans"),
        "SYSTEM_UI": ("di sistema", "system font"),
        "TRANSITIONAL_SERIF": ("graziato transizionale", "transitional serif"),
        "OLD_STYLE_SERIF": ("graziato antico", "old-style serif"),
        "MODERN_SERIF": ("graziato moderno", "modern serif"),
        "SLAB_SERIF": ("graziato a blocchi", "slab serif"),
        "MONOSPACE": ("monospaziato", "monospace"),
        "DISPLAY_HEAVY": ("da vetrina, molto marcato", "heavy display"),
        "SCRIPT": ("calligrafico", "script"),
    },
}

MESSAGES: dict[str, dict[str, str]] = {
    "design.help": {
        "it": "lavora sul design: alternative, mockup nel browser, parere dei twin, modifiche "
        "a parole, scelta e approvazione",
        "en": "work on the design: alternatives, mockups in the browser, what the twins think, "
        "changes in words, choice and approval",
    },
    "design.option_action": {
        "it": "che cosa fare: show (mostra), open (apre le anteprime), choose (sceglie "
        "un'alternativa), change (chiede una modifica), review (revisione dei twin), approve "
        "(approva), regenerate (rigenera le alternative); senza azione il comando ti guida "
        "passo per passo",
        "en": "what to do: show, open (the previews), choose (an alternative), change (ask for "
        "a change), review (by the twins), approve, regenerate (the alternatives); without "
        "an action the command guides you "
        "step by step",
    },
    "design.option_value": {
        "it": "il codice o il numero di un'alternativa (per open e choose), oppure la modifica "
        "scritta a parole tra virgolette (per change)",
        "en": "the code or the number of an alternative (for open and choose), or the change "
        "written in words between quotes (for change)",
    },
    "design.option_rule": {
        "it": "una regola che deve restare valida anche dopo le prossime modifiche; si può "
        "ripetere, solo con change",
        "en": "a rule that must stay valid after the next changes too; it can be repeated, "
        "only with change",
    },
    "design.usage_rule": {
        "it": "--rule si usa solo con `ut design change`.",
        "en": "--rule can be used only with `ut design change`.",
    },
    "design.usage_value": {
        "it": "`ut design {action}` non vuole altro testo dopo l'azione: toglilo e riprova.",
        "en": "`ut design {action}` takes no other text after the action: remove it and try again.",
    },
    "design.usage_code": {
        "it": "Scrivi quale alternativa scegli, per esempio `ut design choose DES-001`.",
        "en": "Write which alternative you choose, for example `ut design choose DES-001`.",
    },
    "design.heading": {"it": "Design di {project}", "en": "Design of {project}"},
    "design.requirements_pending": {
        "it": "Il design viene dopo i requisiti, che non sono ancora approvati. Completa i "
        "passi precedenti con `ut init`, poi torna qui.",
        "en": "The design comes after the requirements, which are not approved yet. Complete "
        "the earlier steps with `ut init`, then come back here.",
    },
    "design.no_design_yet": {
        "it": "Il design non esiste ancora. Lancia `ut design`: ti dice quanto costa prepararlo "
        "e lo genera solo se confermi.",
        "en": "The design does not exist yet. Launch `ut design`: it tells you what preparing it "
        "costs and generates it only if you confirm.",
    },
    "design.no_design_yet_plain": {
        "it": "Il design non esiste ancora. Lancia `ut design` per prepararlo.",
        "en": "The design does not exist yet. Launch `ut design` to prepare it.",
    },
    "design.wait_running": {
        "it": "Nello Studio è in corso: {names}. Aspetta che finisca: `ut design` la segue e poi "
        "puoi andare avanti.",
        "en": "In the Studio this is running: {names}. Wait for it to finish: `ut design` "
        "follows it, then you can go on.",
    },
    "design.proposal_missing": {
        "it": "Le alternative di design non sono state preparate. Quando vuoi riprovare, "
        "rilancia `ut design`: prima ti mostra la stima.",
        "en": "The design alternatives were not prepared. When you want to try again, launch "
        "`ut design` again: it shows you the estimate first.",
    },
    "design.proposal_missing_plain": {
        "it": "Le alternative di design non sono state preparate. Quando vuoi riprovare, "
        "rilancia `ut design`.",
        "en": "The design alternatives were not prepared. When you want to try again, launch "
        "`ut design` again.",
    },
    "design.show_running": {
        "it": "Nello Studio è in corso: {names}.",
        "en": "In the Studio this is running: {names}.",
    },
    "design.running": {
        "it": "Nello Studio è già in corso: {names}. Non ne avvio un'altra: seguo questa.",
        "en": "In the Studio this is already running: {names}. I start nothing new: I follow it.",
    },
    "design.label_running": {
        "it": "Attendo la fine della generazione in corso",
        "en": "Waiting for the running generation to end",
    },
    "design.next_job_running": {
        "it": "Lancia `ut design` per seguire la generazione in corso e andare avanti.",
        "en": "Launch `ut design` to follow the running generation and go on.",
    },
    "design.next_no_mockups": {
        "it": "Lancia `ut design` per far disegnare i mockup: ti mostra prima la stima della "
        "spesa.",
        "en": "Launch `ut design` to have the mockups drawn: it shows you the estimated "
        "spending first.",
    },
    "design.next_no_mockups_plain": {
        "it": "Lancia `ut design` per far disegnare i mockup.",
        "en": "Launch `ut design` to have the mockups drawn.",
    },
    "design.next_mockups_ready": {
        "it": "Guarda le anteprime con `ut design open`, poi scegli con `ut design choose CODE`.",
        "en": "Look at the previews with `ut design open`, then choose with `ut design choose "
        "CODE`.",
    },
    "design.next_chosen": {
        "it": 'Puoi chiedere una modifica con `ut design change "..."` oppure approvare con '
        "`ut design approve`.",
        "en": 'You can ask for a change with `ut design change "..."` or approve with '
        "`ut design approve`.",
    },
    "design.next_approved": {
        "it": 'Il design è approvato. Una modifica con `ut design change "..."` apre una nuova '
        "versione da approvare.",
        "en": 'The design is approved. A change with `ut design change "..."` opens a new '
        "version to approve.",
    },
    "design.next_choose": {
        "it": "Scegli un'alternativa con `ut design choose CODE`.",
        "en": "Choose an alternative with `ut design choose CODE`.",
    },
    "design.next_chosen_approve": {
        "it": "Puoi approvare il design con `ut design approve`.",
        "en": "You can approve the design with `ut design approve`.",
    },
    "design.no_model": {
        "it": "Questo Studio non ha un modello collegato, quindi non può disegnare i mockup né "
        "preparare il prototipo di un'alternativa: per scegliere un'alternativa e approvare il "
        "design ne serve uno. Qui sopra trovi le alternative e il parere dei twin; chi gestisce "
        "lo Studio può collegare un modello.",
        "en": "This Studio has no model connected, so it cannot draw the mockups or prepare the "
        "prototype of an alternative: choosing an alternative and approving the design need "
        "one. The alternatives and what the twins think are shown above; whoever runs the "
        "Studio can connect a model.",
    },
    "design.no_model_chosen": {
        "it": "Questo Studio non ha un modello collegato, quindi qui il design non si può "
        "modificare e non si può scegliere un'altra alternativa. Chi gestisce lo Studio può "
        "collegarne uno.",
        "en": "This Studio has no model connected, so here the design cannot be changed and no "
        "other alternative can be chosen. Whoever runs the Studio can connect one.",
    },
    "design.no_model_choice": {
        "it": "Su questo Studio non si può scegliere un'alternativa: non ha un modello "
        "collegato, e la scelta ne ha bisogno per preparare il prototipo dell'alternativa. Non "
        "è cambiato nulla; chi gestisce lo Studio può collegarne uno.",
        "en": "On this Studio no alternative can be chosen: it has no model connected, and the "
        "choice needs one to prepare the prototype of the alternative. Nothing changed; "
        "whoever runs the Studio can connect one.",
    },
    "design.no_model_change": {
        "it": "Su questo Studio il design non si può modificare a parole: non ha un modello "
        "collegato, e la modifica ne ha bisogno. Non è cambiato nulla; chi gestisce lo Studio "
        "può collegarne uno.",
        "en": "On this Studio the design cannot be changed in words: it has no model connected, "
        "and a change needs one. Nothing changed; whoever runs the Studio can connect one.",
    },
    "design.no_model_approve": {
        "it": "Il design non si può ancora approvare: prima va scelta un'alternativa, e su "
        "questo Studio la scelta ha bisogno di un modello che non è collegato. Chi gestisce lo "
        "Studio può collegarne uno.",
        "en": "The design cannot be approved yet: an alternative must be chosen first, and on "
        "this Studio the choice needs a model that is not connected. Whoever runs the Studio "
        "can connect one.",
    },
    "design.previews_unavailable": {
        "it": "Con il modello di questo Studio le anteprime dei mockup nel browser non sono "
        "disponibili: trovi qui sotto le alternative e il parere dei twin. Scelta e "
        "approvazione funzionano lo stesso.",
        "en": "With the model of this Studio the mockup previews in the browser are not "
        "available: the alternatives and what the twins think are shown here. Choice and "
        "approval work all the same.",
    },
    "design.alternatives_heading": {
        "it": "Alternative di design",
        "en": "Design alternatives",
    },
    "design.alternative": {"it": "{code} · {title}", "en": "{code} · {title}"},
    "design.alternative_recommended": {
        "it": "{code} · {title} (consigliata dal modello)",
        "en": "{code} · {title} (recommended by the model)",
    },
    "design.alternative_product": {"it": "  Prodotto: {name}", "en": "  Product: {name}"},
    "design.mockup_present": {"it": "  Mockup: pronto.", "en": "  Mockup: ready."},
    "design.mockup_absent": {
        "it": "  Mockup: non ancora disegnato.",
        "en": "  Mockup: not drawn yet.",
    },
    "design.visual_line": {
        "it": "Aspetto: impaginazione {layout}, tinta {hue}, modalità {mode}, tono {tone}, "
        "titoli con carattere {font}.",
        "en": "Look: {layout} layout, {hue} colour, {mode} mode, {tone} tone, {font} headings.",
    },
    "design.verdicts_heading": {"it": "Cosa pensano i twin", "en": "What the twins think"},
    "design.column_twin": {"it": "Twin", "en": "Twin"},
    "design.quote": {"it": "{twin}: “{quote}”", "en": "{twin}: “{quote}”"},
    "design.verdict_below": {"it": "vedi sotto", "en": "see below"},
    "design.point": {"it": "{label}: {text}", "en": "{label}: {text}"},
    "design.point_strengths": {"it": "Punti di forza", "en": "Strengths"},
    "design.point_concerns": {"it": "Dubbi", "en": "Concerns"},
    "design.point_unmet_needs": {"it": "Bisogni non coperti", "en": "Unmet needs"},
    "design.point_accessibility_observations": {"it": "Accessibilità", "en": "Accessibility"},
    "design.point_trust_concerns": {"it": "Fiducia", "en": "Trust"},
    "design.point_questions": {"it": "Domande", "en": "Questions"},
    "design.point_suggested_changes": {"it": "Modifiche suggerite", "en": "Suggested changes"},
    "design.chosen_heading": {"it": "Design scelto", "en": "Chosen design"},
    "design.chosen_waiting": {
        "it": "Versione {version}, non ancora approvata.",
        "en": "Version {version}, not approved yet.",
    },
    "design.chosen_approved": {
        "it": "Versione {version}, approvata.",
        "en": "Version {version}, approved.",
    },
    "design.rules_heading": {
        "it": "Regole in vigore, che ogni modifica deve rispettare:",
        "en": "Rules in force, which every change must respect:",
    },
    "design.rules_none": {
        "it": "Nessuna regola in vigore: puoi aggiungerne quando chiedi una modifica.",
        "en": "No rule in force: you can add some when you ask for a change.",
    },
    "design.rules_none_plain": {"it": "Nessuna regola in vigore.", "en": "No rule in force."},
    "design.summary_no_mockups": {
        "it": "Le alternative sono pronte; nessun mockup è ancora disegnato.",
        "en": "The alternatives are ready; no mockup has been drawn yet.",
    },
    "design.summary_mockups": {
        "it": "Mockup pronti: {codes}. Nessuna alternativa è ancora scelta.",
        "en": "Mockups ready: {codes}. No alternative has been chosen yet.",
    },
    "design.summary_alternatives": {
        "it": "Le alternative sono pronte; nessuna è ancora scelta.",
        "en": "The alternatives are ready; none has been chosen yet.",
    },
    "design.summary_chosen": {
        "it": "Scelta: {code} “{title}”, versione {version}, non ancora approvata.",
        "en": "Chosen: {code} “{title}”, version {version}, not approved yet.",
    },
    "design.summary_approved": {
        "it": "Approvato: {code} “{title}”, versione {version}.",
        "en": "Approved: {code} “{title}”, version {version}.",
    },
    "design.folder_here": {
        "it": "La cartella di conoscenza è in {path}: versione {version}, {files} file.",
        "en": "The knowledge folder is in {path}: version {version}, {files} files.",
    },
    "design.folder_newer": {
        "it": "Nello Studio c'è la versione {version}, più recente: scaricala con "
        "`ut package pull`.",
        "en": "The Studio has version {version}, which is newer: download it with "
        "`ut package pull`.",
    },
    "design.folder_not_here": {
        "it": "La cartella di conoscenza non è ancora in {path}. Nello Studio c'è la versione "
        "{version}: scaricala con `ut package pull`.",
        "en": "The knowledge folder is not in {path} yet. The Studio has version {version}: "
        "download it with `ut package pull`.",
    },
    "design.folder_not_published": {
        "it": "La cartella di conoscenza non è ancora stata preparata: `ut package publish` la "
        "crea.",
        "en": "The knowledge folder has not been prepared yet: `ut package publish` creates it.",
    },
    "design.folder_unreadable": {
        "it": "La cartella di conoscenza in {path} non si legge ({code}): scaricala di nuovo "
        "con `ut package pull`.",
        "en": "The knowledge folder in {path} cannot be read ({code}): download it again with "
        "`ut package pull`.",
    },
    "design.estimate": {
        "it": "stima {amount} USD, circa {minutes}",
        "en": "estimate {amount} USD, about {minutes}",
    },
    "design.estimate_subscription": {
        "it": "abbonamento di Claude, nessun credito speso, circa {minutes}",
        "en": "Claude subscription, no credit spent, about {minutes}",
    },
    "design.menu": {"it": "Che cosa vuoi fare?", "en": "What do you want to do?"},
    "design.menu_open": {
        "it": "Apri le anteprime nel browser",
        "en": "Open the previews in the browser",
    },
    "design.priced": {"it": "{label} ({estimate})", "en": "{label} ({estimate})"},
    "design.menu_choose": {
        "it": "Scegli un'alternativa; subito dopo i twin la rivedono",
        "en": "Choose an alternative; right after, the twins review it",
    },
    "design.menu_choose_other": {
        "it": "Scegli un'altra alternativa; subito dopo i twin la rivedono",
        "en": "Choose another alternative; right after, the twins review it",
    },
    "design.menu_mockups": {
        "it": "Disegna i mockup che mancano: {codes}",
        "en": "Draw the missing mockups: {codes}",
    },
    "design.menu_apply": {
        "it": "Applica la modifica che avevi chiesto: “{request}” (nessuna spesa)",
        "en": "Apply the change you asked for: “{request}” (no spending)",
    },
    "design.menu_change": {
        "it": "Chiedi una modifica a parole; subito dopo i twin la rivedono",
        "en": "Ask for a change in words; right after, the twins review it",
    },
    "design.menu_review": {
        "it": "Fai rivedere il design ai twin",
        "en": "Have the twins review the design",
    },
    "design.menu_approve": {
        "it": "Approva il design; poi la cartella di conoscenza appare in orchestwin/",
        "en": "Approve the design; then the knowledge folder appears in orchestwin/",
    },
    "design.menu_leave": {"it": "Esci", "en": "Leave"},
    "design.choose_which": {
        "it": "Quale alternativa scegli?",
        "en": "Which alternative do you choose?",
    },
    "design.choice_label": {"it": "{code} · {title}", "en": "{code} · {title}"},
    "design.change_ask": {
        "it": "Scrivi a parole che cosa vuoi cambiare nel design scelto.",
        "en": "Write in words what you want to change in the chosen design.",
    },
    "design.rules_ask": {
        "it": "Se vuoi, scrivi le regole che devono restare valide anche dopo le prossime "
        "modifiche, una per riga (al massimo 5). Se non ne hai, premi solo Invio.",
        "en": "If you want, write the rules that must stay valid after the next changes too, "
        "one per line (at most 5). If you have none, just press Enter.",
    },
    "design.change_cancelled": {
        "it": "Nessuna modifica chiesta: non ho speso nulla.",
        "en": "No change asked: nothing was spent.",
    },
    "design.busy_wait": {
        "it": "Nello Studio girano già troppe generazioni: aspetto {seconds} secondi e riprovo "
        "(tentativo {attempt} di {attempts}).",
        "en": "Too many generations are already running in the Studio: I wait {seconds} "
        "seconds and try again (attempt {attempt} of {attempts}).",
    },
    "design.about_design_and_mockups": {
        "it": "Adesso preparo le alternative di design; poi faccio disegnare insieme i mockup "
        "di due alternative, così puoi vederli nel browser.",
        "en": "I am about to prepare the design alternatives; then I have the mockups of two "
        "alternatives drawn at the same time, so that you can see them in the browser.",
    },
    "design.about_design": {
        "it": "Adesso preparo le alternative di design.",
        "en": "I am about to prepare the design alternatives.",
    },
    "design.about_mockups": {
        "it": "Adesso faccio disegnare i mockup di {codes}, tutti insieme.",
        "en": "I am about to have the mockups of {codes} drawn, all at the same time.",
    },
    "design.label_proposal": {
        "it": "Preparo le alternative di design",
        "en": "Preparing the design alternatives",
    },
    "design.label_mockups": {"it": "Disegno i mockup", "en": "Drawing the mockups"},
    "design.label_mockup": {
        "it": "Disegno il mockup di {code}",
        "en": "Drawing the mockup of {code}",
    },
    "design.label_change": {
        "it": "Applico la modifica al design",
        "en": "Applying the change to the design",
    },
    "design.label_review": {
        "it": "I twin rivedono il design",
        "en": "The twins are reviewing the design",
    },
    "design.label_declarative": {
        "it": "Preparo il prototipo di {code}",
        "en": "Preparing the prototype of {code}",
    },
    "design.job_mockup": {"it": "mockup di {code}", "en": "mockup of {code}"},
    "design.job_proposal": {"it": "alternative di design", "en": "design alternatives"},
    "design.job_review": {"it": "revisione dei twin", "en": "review of the twins"},
    "design.job_change": {"it": "modifica del design", "en": "change of the design"},
    "design.job_other": {"it": "generazione del design", "en": "design generation"},
    "design.mockup_ready": {"it": "Pronto: {name}.", "en": "Ready: {name}."},
    "design.job_budget": {
        "it": "Generazione non fatta ({name}): lo Studio ha raggiunto un tetto di spesa "
        "({code}); chi gestisce lo Studio può alzarlo.",
        "en": "Not done: {name}. The Studio reached a spending ceiling ({code}); whoever runs "
        "the Studio can raise it.",
    },
    "design.job_refused": {
        "it": "Generazione non partita ({name}): lo Studio l'ha rifiutata (stato {http_status}, "
        "{code}).",
        "en": "Not started: {name}. The Studio refused it (status {http_status}, {code}).",
    },
    "design.job_lost": {
        "it": "Generazione persa ({name}), forse perché lo Studio è ripartito. Non è cambiato "
        "nulla.",
        "en": "Lost: {name}, perhaps because the Studio restarted. Nothing changed.",
    },
    "design.job_context": {
        "it": "Risultato non usato ({name}): nel frattempo il design è cambiato, forse "
        "dall'interfaccia web.",
        "en": "Not used: {name}. In the meantime the design changed, perhaps in the web interface.",
    },
    "design.job_cut": {
        "it": "Generazione interrotta ({name}): è stata tagliata perché era troppo lunga "
        "({code}); non è cambiato nulla.",
        "en": "Cut: {name}. The generation was stopped because it was too long ({code}); "
        "nothing changed.",
    },
    "design.job_rejected": {
        "it": "Risultato scartato ({name}): non ha superato i controlli dello Studio ({code}); "
        "non è cambiato nulla.",
        "en": "Discarded: {name}. The result did not pass the checks of the Studio ({code}); "
        "nothing changed.",
    },
    "design.job_failed": {
        "it": "Generazione non riuscita ({name}, {code}). Non è cambiato nulla.",
        "en": "Failed: {name} ({code}). Nothing changed.",
    },
    "design.mockup_again": {
        "it": "Le altre alternative restano utilizzabili. Disegnare di nuovo {code} è una nuova "
        "spesa ({amount} USD, circa {minutes}): `ut design` te lo propone nel menu.",
        "en": "The other alternatives remain usable. Drawing {code} again is a new spending "
        "({amount} USD, about {minutes}): `ut design` offers it in its menu.",
    },
    "design.mockup_again_subscription": {
        "it": "Le altre alternative restano utilizzabili. Disegnare di nuovo {code} usa "
        "l'abbonamento di Claude e non spende credito (circa {minutes}): `ut design` te lo "
        "propone nel menu.",
        "en": "The other alternatives remain usable. Drawing {code} again runs on the Claude "
        "subscription and spends no credit (about {minutes}): `ut design` offers it in its menu.",
    },
    "design.mockup_again_plain": {
        "it": "Le altre alternative restano utilizzabili. `ut design` ti propone nel menu di "
        "disegnare di nuovo {code}.",
        "en": "The other alternatives remain usable. `ut design` offers in its menu to draw "
        "{code} again.",
    },
    "design.previews_written": {
        "it": "Anteprime scritte in {path}.",
        "en": "Previews written in {path}.",
    },
    "design.previews_opened": {
        "it": "Ho chiesto al browser di aprire {path}.",
        "en": "I asked the browser to open {path}.",
    },
    "design.previews_not_opened": {
        "it": "Non riesco ad aprire il browser: apri tu questo file: {path}",
        "en": "I cannot open the browser: open this file yourself: {path}",
    },
    "design.open_missing": {
        "it": "{code} non ha ancora un mockup da aprire. `ut design` te lo propone nel menu, "
        "con la sua stima.",
        "en": "{code} has no mockup to open yet. `ut design` offers it in its menu, with its "
        "estimate.",
    },
    "design.open_missing_plain": {
        "it": "{code} non ha ancora un mockup da aprire. `ut design` te lo propone nel menu.",
        "en": "{code} has no mockup to open yet. `ut design` offers it in its menu.",
    },
    "design.already_chosen": {
        "it": "{code} “{title}” è già l'alternativa scelta: non ho cambiato nulla.",
        "en": "{code} “{title}” is already the chosen alternative: nothing changed.",
    },
    "design.choose_needs_mockup": {
        "it": "{code} non ha ancora un mockup, e senza mockup non si può scegliere. Lancia "
        "`ut design`: te lo propone nel menu, con la sua stima.",
        "en": "{code} has no mockup yet, and without a mockup it cannot be chosen. Launch "
        "`ut design`: it offers it in its menu, with its estimate.",
    },
    "design.choose_needs_mockup_plain": {
        "it": "{code} non ha ancora un mockup, e senza mockup non si può scegliere. Lancia "
        "`ut design`: te lo propone nel menu.",
        "en": "{code} has no mockup yet, and without a mockup it cannot be chosen. Launch "
        "`ut design`: it offers it in its menu.",
    },
    "design.about_declarative": {
        "it": "Per applicare la scelta preparo il prototipo di {code}.",
        "en": "To apply the choice I prepare the prototype of {code}.",
    },
    "design.chosen": {
        "it": "Hai scelto {code} “{title}”: il design è ora alla versione {version}.",
        "en": "You chose {code} “{title}”: the design is now at version {version}.",
    },
    "design.approve_needs_choice": {
        "it": "Prima di approvare scegli un'alternativa, per esempio con `ut design choose "
        "DES-001`.",
        "en": "Before approving, choose an alternative, for example with `ut design choose "
        "DES-001`.",
    },
    "design.already_approved": {
        "it": "Il design è già approvato: {code} “{title}”, versione {version}.",
        "en": "The design is already approved: {code} “{title}”, version {version}.",
    },
    "design.approved": {
        "it": "Design approvato: {code} “{title}”, versione {version}. Ora preparo la cartella "
        "di conoscenza.",
        "en": "Design approved: {code} “{title}”, version {version}. Now I prepare the "
        "knowledge folder.",
    },
    "design.publish_later": {
        "it": "Il design resta approvato, ma la cartella di conoscenza non è stata preparata "
        "adesso: `ut package publish` completa il lavoro.",
        "en": "The design stays approved, but the knowledge folder was not prepared now: "
        "`ut package publish` completes the work.",
    },
    "design.folder_ready": {
        "it": "La cartella di conoscenza è in {path}: versione {version}, {files} file.",
        "en": "The knowledge folder is in {path}: version {version}, {files} files.",
    },
    "design.folder_contents": {
        "it": "Dentro trovi ORCHESTWIN.md, da leggere per primo: descrive il progetto e dice "
        "dove sono brief, prospettive, twin, requisiti e design, ognuno in un documento di "
        "testo e in uno JSON. Un agente dell'editor, per esempio in Visual Studio Code, parte da "
        "lì; orchestwin.json elenca i file con la loro impronta, così si vede se qualcosa è "
        "stato cambiato a mano.",
        "en": "Inside you find ORCHESTWIN.md, to be read first: it describes the project and "
        "says where the brief, the perspectives, the twins, the requirements and the design "
        "are, each in a text document and in a JSON one. An agent of the editor, for example in "
        "Visual Studio Code, starts from there; orchestwin.json lists the files with their "
        "fingerprint, so that a change made by hand shows.",
    },
    "design.after_heading": {
        "it": "Lo sviluppo continua con questi comandi:",
        "en": "The development goes on with these commands:",
    },
    "design.after_code": {
        "it": "`ut code` scrive l'applicazione con il tuo agente di programmazione.",
        "en": "`ut code` writes the application with your coding agent.",
    },
    "design.after_test": {
        "it": "`ut test` verifica i criteri di accettazione nei browser.",
        "en": "`ut test` checks the acceptance criteria in the browsers.",
    },
    "design.after_tasks": {
        "it": "`ut tasks` mostra le cose che restano da fare.",
        "en": "`ut tasks` shows the things left to do.",
    },
    "design.after_align": {
        "it": "`ut align` confronta i commit con i requisiti e il design.",
        "en": "`ut align` compares the commits with the requirements and the design.",
    },
    "design.after_twins": {
        "it": "`ut twins update` mostra che cosa hanno imparato i twin.",
        "en": "`ut twins update` shows what the twins learned.",
    },
    "design.after_watch": {
        "it": "`ut watch` osserva i commit e li registra nello Studio.",
        "en": "`ut watch` watches the commits and records them in the Studio.",
    },
    "design.behind": {
        "it": "Il design è rimasto indietro rispetto alle sezioni a monte, quindi per ora lo "
        "Studio non lo cambia: non ho applicato nulla. Riaggancialo con `ut sections update`, "
        "con i contenuti invariati, poi riprova.",
        "en": "The design is behind the sections upstream, so for now the Studio does not change "
        "it: nothing was applied. Re-anchor it with `ut sections update`, with its content "
        "unchanged, then try again.",
    },
    "design.recovery_requirement_removed": {
        "it": "Il design cita {codes}, che la Definizione non contiene più. Puoi leggere le "
        "anteprime storiche; per continuare rigenera le alternative con `ut design regenerate`.",
        "en": "The design cites {codes}, which the Definition no longer contains. You can read "
        "the historical previews; to continue, regenerate the alternatives with "
        "`ut design regenerate`.",
    },
    "design.recovery_prepare_again": {
        "it": "Questo design va preparato di nuovo. Puoi leggere le anteprime storiche; "
        "per continuare rigenera le alternative con `ut design regenerate`.",
        "en": "This design needs to be prepared again. You can read the historical previews; "
        "to continue, regenerate the alternatives with `ut design regenerate`.",
    },
    "design.recovery_revision_pending": {
        "it": "C'è una modifica proposta da decidere nello Studio web. Decidila prima di "
        "rigenerare o cambiare il design; non ho avviato alcuna generazione.",
        "en": "A proposed change is waiting for your decision in the web Studio. Decide it "
        "before regenerating or changing the design; no generation was started.",
    },
    "design.recovery_blocked": {
        "it": "Il design non può essere rigenerato o cambiato adesso. {blocked} "
        "`ut sections` mostra che cosa completare prima.",
        "en": "The design cannot be regenerated or changed now. {blocked} "
        "`ut sections` shows what needs to be completed first.",
    },
    "design.menu_regenerate": {
        "it": "Rigenera le alternative dai passi approvati",
        "en": "Regenerate the alternatives from the approved steps",
    },
    "design.menu_update_sections": {
        "it": "Aggiorna i collegamenti con `ut sections update`",
        "en": "Update the links with `ut sections update`",
    },
    "design.regenerate_explicit": {
        "it": "Preparo nuove alternative dai passi approvati. Il design precedente resta "
        "nello storico; dovrai scegliere e approvare il nuovo design.",
        "en": "I will prepare new alternatives from the approved steps. The previous design "
        "stays in the history; you will need to choose and approve the new design.",
    },
    "design.no_model_regenerate": {
        "it": "Questo Studio non ha un modello collegato per rigenerare le alternative. "
        "Chi gestisce lo Studio può collegarne uno.",
        "en": "This Studio has no model connected to regenerate the alternatives. Whoever "
        "runs the Studio can connect one.",
    },
    "design.behind_blocked": {
        "it": "Il design è rimasto indietro rispetto alle sezioni a monte, quindi per ora lo "
        "Studio non lo cambia: non ho applicato nulla. {blocked}",
        "en": "The design is behind the sections upstream, so for now the Studio does not change "
        "it: nothing was applied. {blocked}",
    },
    "design.change_needs_choice": {
        "it": "Per chiedere una modifica scegli prima un'alternativa, per esempio con "
        "`ut design choose DES-001`.",
        "en": "To ask for a change, choose an alternative first, for example with "
        "`ut design choose DES-001`.",
    },
    "design.change_unavailable": {
        "it": "Con il modello di questo Studio le modifiche a parole non sono disponibili, "
        "oppure il design scelto non ha un mockup disegnato dal modello.",
        "en": "With the model of this Studio changes in words are not available, or the chosen "
        "design has no mockup drawn by the model.",
    },
    "design.about_change": {
        "it": "Adesso chiedo al modello di cambiare il design scelto: “{request}”. Subito dopo "
        "i twin rivedono la nuova versione.",
        "en": "I am about to ask the model to change the chosen design: “{request}”. Right "
        "after, the twins review the new version.",
    },
    "design.about_rules": {
        "it": "Queste regole resteranno in vigore anche dopo:",
        "en": "These rules will stay in force afterwards too:",
    },
    "design.change_applied": {
        "it": "Modifica applicata: il design è ora alla versione {version}, da approvare.",
        "en": "Change applied: the design is now at version {version}, to be approved.",
    },
    "design.change_same": {
        "it": "Il risultato della modifica è identico al design attuale: non è cambiato nulla "
        "e il design resta alla versione {version}.",
        "en": "The result of the change is identical to the current design: nothing changed "
        "and the design stays at version {version}.",
    },
    "design.change_request": {
        "it": "Avevi chiesto: “{request}”",
        "en": "You asked: “{request}”",
    },
    "design.change_list": {"it": "Che cosa è cambiato:", "en": "What changed:"},
    "design.change_not_reviewed": {
        "it": "La modifica resta applicata nella versione {version}, ma i twin non l'hanno "
        "rivista, per il motivo indicato. Quando il motivo è risolto, lancia `ut design review` "
        "per far fare la revisione.",
        "en": "The change stays applied in version {version}, but the twins did not review it, "
        "for the reason given. Once the reason is solved, launch `ut design review` to have the "
        "review done.",
    },
    "design.choice_not_reviewed": {
        "it": "La scelta resta applicata nella versione {version}, ma i twin non l'hanno "
        "rivista, per il motivo indicato. Quando il motivo è risolto, lancia `ut design review` "
        "per far fare la revisione.",
        "en": "The choice stays applied in version {version}, but the twins did not review it, "
        "for the reason given. Once the reason is solved, launch `ut design review` to have the "
        "review done.",
    },
    "design.pending_change": {
        "it": "Una modifica che avevi chiesto è pronta ma non ancora applicata: “{request}”. "
        "`ut design` te la propone nel menu, senza nuova spesa.",
        "en": "A change you asked for is ready but not applied yet: “{request}”. `ut design` "
        "offers it in its menu, without new spending.",
    },
    "design.pending_missing": {
        "it": "Lo Studio non ha più il risultato di quella modifica: chiedila di nuovo se ti "
        "serve (è una nuova spesa).",
        "en": "The Studio no longer has the result of that change: ask for it again if you "
        "need it (it is a new spending).",
    },
    "design.review_no_design": {
        "it": "Il design non esiste ancora, quindi i twin non hanno niente da rivedere. Lancia "
        "`ut design`.",
        "en": "The design does not exist yet, so the twins have nothing to review. Launch "
        "`ut design`.",
    },
    "design.review_not_chosen": {
        "it": "I twin rivedono il design scelto: prima scegli un'alternativa, per esempio con "
        "`ut design choose DES-001`.",
        "en": "The twins review the chosen design: choose an alternative first, for example "
        "with `ut design choose DES-001`.",
    },
    "design.review_about": {
        "it": "Adesso chiedo ai twin di rivedere il design scelto.",
        "en": "I am about to ask the twins to review the chosen design.",
    },
    "design.review_running": {
        "it": "Una revisione dei twin è già in corso nello Studio: non ne avvio un'altra, "
        "seguo questa.",
        "en": "A review of the twins is already running in the Studio: I start no other one, "
        "I follow it.",
    },
    "design.review_exists": {
        "it": "I twin hanno già rivisto questa versione del design: non la faccio rivedere di "
        "nuovo, ecco la loro revisione.",
        "en": "The twins have already reviewed this version of the design: I do not start "
        "another review, here is theirs.",
    },
    "design.review_changed": {
        "it": "Nel frattempo il design è cambiato, forse dall'interfaccia web, quindi i twin "
        "non l'hanno rivisto. Rilancia la revisione per la nuova versione.",
        "en": "In the meantime the design changed, perhaps in the web interface, so the twins "
        "did not review it. Launch the review again for the new version.",
    },
    "design.review_heading": {
        "it": "Revisione dei twin, versione {version}",
        "en": "Review of the twins, version {version}",
    },
    "design.review_empty": {
        "it": "La revisione non contiene osservazioni.",
        "en": "The review contains no observations.",
    },
    "design.review_no_findings": {
        "it": "- Nessuna osservazione.",
        "en": "- No observation.",
    },
    "design.review_twin": {"it": "Twin", "en": "Twin"},
    "design.comparison_heading": {
        "it": "Rispetto alla revisione precedente dei twin:",
        "en": "Compared with the previous review of the twins:",
    },
    "design.comparison_resolved": {
        "it": "Risolte ({count}):",
        "en": "Solved ({count}):",
    },
    "design.comparison_resolved_none": {
        "it": "Risolte: nessuna.",
        "en": "Solved: none.",
    },
    "design.comparison_persisting": {
        "it": "Ancora aperte ({count}):",
        "en": "Still open ({count}):",
    },
    "design.comparison_persisting_none": {
        "it": "Ancora aperte: nessuna.",
        "en": "Still open: none.",
    },
    "design.comparison_introduced": {
        "it": "Nuove ({count}):",
        "en": "New ({count}):",
    },
    "design.comparison_introduced_none": {
        "it": "Nuove: nessuna.",
        "en": "New: none.",
    },
    "design.comparison_item": {"it": "{twin} · {finding}", "en": "{twin} · {finding}"},
    "design.finding": {"it": "{weight}: {summary}", "en": "{weight}: {summary}"},
    "design.finding_placed": {
        "it": "{weight}: {summary} ({place})",
        "en": "{weight}: {summary} ({place})",
    },
    "design.place_screen": {"it": "schermata “{screen}”", "en": "screen “{screen}”"},
    "design.place_element": {
        "it": "schermata “{screen}”, elemento “{element}”",
        "en": "screen “{screen}”, element “{element}”",
    },
    "design.weight_critical": {"it": "Grave", "en": "Critical"},
    "design.weight_major": {"it": "Importante", "en": "Major"},
    "design.weight_moderate": {"it": "Media", "en": "Moderate"},
    "design.weight_minor": {"it": "Lieve", "en": "Minor"},
    "design.weight_observation": {"it": "Osservazione", "en": "Observation"},
    "design.weight_unknown": {"it": "Osservazione", "en": "Observation"},
    "design.page_title": {
        "it": "{project} · anteprime del design",
        "en": "{project} · design previews",
    },
    "design.page_lead": {
        "it": "Apri un'alternativa per vedere il suo mockup. Queste pagine sono state scritte "
        "da ut design su questo computer e non caricano nulla da internet.",
        "en": "Open an alternative to see its mockup. These pages were written by ut design on "
        "this computer and load nothing from the internet.",
    },
    "design.page_recommended": {"it": "Consigliata dal modello", "en": "Recommended by the model"},
    "design.page_chosen": {"it": "Scelta", "en": "Chosen"},
    "design.page_product": {"it": "Prodotto: {name}", "en": "Product: {name}"},
    "design.page_twins": {"it": "Cosa pensano i twin", "en": "What the twins think"},
    "design.page_quote": {"it": "“{quote}”", "en": "“{quote}”"},
    "design.page_open": {"it": "Apri il mockup di {code}", "en": "Open the mockup of {code}"},
    "design.page_missing": {
        "it": "Mockup non ancora disegnato.",
        "en": "Mockup not drawn yet.",
    },
    "design.page_change": {
        "it": "Modifica chiesta: “{request}”",
        "en": "Change asked: “{request}”",
    },
    "design.page_before": {
        "it": "Prima della modifica (versione {version})",
        "en": "Before the change (version {version})",
    },
    "design.page_after": {
        "it": "Dopo la modifica (versione {version})",
        "en": "After the change (version {version})",
    },
    "design.errors.DESIGN_CONTEXT_CHANGED": {
        "it": "Nel frattempo il design è cambiato, forse dall'interfaccia web: non ho applicato "
        "nulla. Ho riletto lo stato: ricontrolla e riprova.",
        "en": "In the meantime the design changed, perhaps in the web interface: nothing was "
        "applied. I read the state again: check it and try again.",
    },
    "design.errors.DESIGN_CODE_UNKNOWN": {
        "it": "Non trovo l'alternativa {code}. Scrivi uno di questi codici, o il suo numero: "
        "{codes}.",
        "en": "The alternative {code} does not exist. Write one of these codes, or its number: "
        "{codes}.",
    },
    "design.errors.STUDIO_UNREACHABLE": {
        "it": "Lo Studio all'indirizzo {address} non risponde. Controlla che sia avviato, poi "
        "rilancia `ut design`: una generazione già partita continua nello Studio e il comando "
        "la ritrova.",
        "en": "The Studio at {address} does not answer. Check that it is running, then launch "
        "`ut design` again: a generation that already started goes on in the Studio and the "
        "command finds it.",
    },
    "design.errors.STUDIO_UNREACHABLE.JOB_RUNNING": {
        "it": "Lo Studio all'indirizzo {address} ha smesso di rispondere durante: {label}. Se "
        "la generazione era partita continua nello Studio: quando lo Studio risponde di nuovo, "
        "rilancia lo stesso comando e la ritrovi.",
        "en": "The Studio at {address} stopped answering during: {label}. If the generation "
        "had started it goes on in the Studio: when the Studio answers again, launch the same "
        "command and it finds it.",
    },
    "design.errors.TOO_MANY_GENERATIONS": {
        "it": "Nello Studio girano troppe generazioni: ho riprovato 8 volte, a 15 secondi di "
        "distanza, senza spendere nulla. Aspetta che una finisca, poi rilancia il comando.",
        "en": "Too many generations are running in the Studio: I tried 8 times, 15 seconds "
        "apart, without spending anything. Wait for one to finish, then launch the command "
        "again.",
    },
    "design.errors.GENERATION_BUDGET_EXCEEDED": {
        "it": "Lo Studio ha raggiunto un tetto di spesa e non avvia questa generazione. Quello "
        "che hai già resta com'è; chi gestisce lo Studio può alzare il tetto.",
        "en": "The Studio reached a spending ceiling and does not start this generation. What "
        "you already have stays as it is; whoever runs the Studio can raise the ceiling.",
    },
    "design.errors.GENERATION_LOST": {
        "it": "La generazione si è persa, forse perché lo Studio è ripartito. Il design non è "
        "cambiato: rilancia `ut design` per vedere lo stato e riprovare.",
        "en": "The generation was lost, perhaps because the Studio restarted. The design did "
        "not change: launch `ut design` again to see the state and try again.",
    },
    "design.errors.GENERATION_REJECTED": {
        "it": "Il risultato non ha superato i controlli dello Studio: {detail} ({code}). Il "
        "design non è cambiato; chiedere di nuovo è una nuova spesa.",
        "en": "The result did not pass the checks of the Studio: {detail} ({code}). The design "
        "did not change; asking again is a new spending.",
    },
    "design.errors.INCOMPLETE_OUTPUT": {
        "it": "La generazione è stata tagliata perché era troppo lunga ({code}). Il design non "
        "è cambiato; riprovare è una nuova spesa.",
        "en": "The generation was stopped because it was too long ({code}). The design did not "
        "change; trying again is a new spending.",
    },
    "design.errors.TIMEOUT": {
        "it": "La generazione è stata tagliata perché durava troppo ({code}). Il design non è "
        "cambiato; riprovare è una nuova spesa.",
        "en": "The generation was stopped because it took too long ({code}). The design did "
        "not change; trying again is a new spending.",
    },
    "design.errors.INVALID_MOCKUP_OUTPUT": {
        "it": "Il modello ha restituito un prototipo che non si può usare ({code}). Il design "
        "non è cambiato; riprovare è una nuova spesa.",
        "en": "The model returned a prototype that cannot be used ({code}). The design did not "
        "change; trying again is a new spending.",
    },
    "design.errors.INVALID_PROVIDER_OUTPUT": {
        "it": "Il modello ha restituito una risposta che non si può usare ({code}). Il design "
        "non è cambiato; riprovare è una nuova spesa.",
        "en": "The model returned an answer that cannot be used ({code}). The design did not "
        "change; trying again is a new spending.",
    },
    "design.errors.REQUIREMENTS_APPROVAL_REQUIRED": {
        "it": "Lo Studio chiede prima l'approvazione dei requisiti: completala con `ut init`.",
        "en": "The Studio asks for the approval of the requirements first: complete it with "
        "`ut init`.",
    },
    "design.errors.REAL_MOCKUP_MODEL_NOT_CONFIGURED": {
        "it": "Questo Studio non ha un modello collegato per disegnare i mockup o preparare il "
        "prototipo di un'alternativa ({code}): scegliere un'alternativa, modificare il design a "
        "parole e disegnare i mockup ne hanno bisogno. Non è cambiato nulla; chi gestisce lo "
        "Studio può collegarne uno.",
        "en": "This Studio has no model connected to draw mockups or prepare the prototype of "
        "an alternative ({code}): choosing an alternative, changing the design in words and "
        "drawing mockups need one. Nothing changed; whoever runs the Studio can connect one.",
    },
    "design.errors.PROPOSAL_REJECTED": {
        "it": "Il modello non è riuscito a preparare le alternative di design a partire dai "
        "passi approvati, e lo Studio non ha indicato il motivo ({code}). Non è cambiato nulla; "
        "puoi rilanciare `ut design`, e un nuovo tentativo è una nuova generazione.",
        "en": "The model could not prepare the design alternatives from the approved steps, "
        "and the Studio gave no reason ({code}). Nothing changed; you can launch `ut design` "
        "again, and a new attempt is a new generation.",
    },
    "design.errors.PROPOSAL_REJECTED.UX_DESIGNER_REQUIRED": {
        "it": "Le alternative di design non sono state preparate: nelle prospettive approvate di "
        "questo progetto l'Esperienza d'uso (UX) non è applicata per intero ({reason}). Può "
        "succedere con le prospettive approvate prima del 29 settembre 2026. Prepara di nuovo "
        "le prospettive e approvale nello Studio web, poi rilancia `ut design`.",
        "en": "The design alternatives were not prepared: in the approved perspectives of this "
        "project User experience (UX) is not fully applied ({reason}). It can happen with "
        "perspectives approved before 29 September 2026. Prepare the perspectives again and "
        "approve them in the web Studio, then launch `ut design` again.",
    },
    "design.errors.PROPOSAL_REJECTED.GROUNDED_INPUT_REQUIRED": {
        "it": "Le alternative di design non sono state preparate: i passi approvati non danno "
        "al modello abbastanza fatti su cui lavorare ({reason}). Aggiungi dettagli al brief "
        "nello Studio web, per esempio chi userà il prodotto e che cosa deve permettere di "
        "fare, poi rilancia `ut design`.",
        "en": "The design alternatives were not prepared: the approved steps do not give the "
        "model enough facts to work on ({reason}). Add details to the brief in the web Studio, "
        "for example who will use the product and what it must let them do, then launch "
        "`ut design` again.",
    },
    "design.errors.PROPOSAL_REJECTED.INVALID_PROVIDER_OUTPUT": {
        "it": "Le alternative di design non sono state preparate: il modello ha dato una "
        "risposta che non si può usare ({reason}). Non è cambiato nulla; rilanciare "
        "`ut design` è una nuova generazione.",
        "en": "The design alternatives were not prepared: the model gave an answer that "
        "cannot be used ({reason}). Nothing changed; launching `ut design` again is a new "
        "generation.",
    },
    "design.errors.GENERATED_MOCKUP_PATH_INACTIVE": {
        "it": "Con il modello di questo Studio i mockup disegnati dal modello non sono "
        "disponibili ({code}).",
        "en": "With the model of this Studio mockups drawn by the model are not available "
        "({code}).",
    },
    "design.errors.GENERATED_MOCKUP_PATH_ACTIVE": {
        "it": "Questo Studio disegna i mockup con il modello: rilancia `ut design` per "
        "vederli ({code}).",
        "en": "This Studio draws the mockups with the model: launch `ut design` again to see "
        "them ({code}).",
    },
    "design.errors.GENERATED_MOCKUP_REQUIRED": {
        "it": "Il design scelto non ha un mockup disegnato dal modello, quindi non si può "
        "modificare a parole ({code}).",
        "en": "The chosen design has no mockup drawn by the model, so it cannot be changed in "
        "words ({code}).",
    },
    "design.errors.GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE": {
        "it": "Questa alternativa non ha scelte visive, quindi il modello non può disegnarne il "
        "mockup ({code}).",
        "en": "This alternative has no visual choices, so the model cannot draw its mockup "
        "({code}).",
    },
    "design.errors.DESIGN_ALTERNATIVE_NOT_FOUND": {
        "it": "Lo Studio non trova più questa alternativa: forse il design è stato rigenerato. "
        "Rilancia `ut design` per vedere lo stato.",
        "en": "The Studio no longer finds this alternative: perhaps the design was generated "
        "again. Launch `ut design` again to see the state.",
    },
    "design.errors.ITERATION_REQUEST_INVALID": {
        "it": "Lo Studio non accetta la modifica così com'è scritta ({code}): accorciala, "
        "togli i caratteri speciali o usa meno regole, poi riprova.",
        "en": "The Studio does not accept the change as it is written ({code}): make it "
        "shorter, remove special characters or use fewer rules, then try again.",
    },
    "design.errors.DESIGN_REVIEWER_NOT_CONFIGURED": {
        "it": "Su questo Studio i twin non possono rivedere il design: non c'è un modello "
        "collegato per la revisione ({code}). Il design resta com'è; chi gestisce lo Studio "
        "può collegarne uno.",
        "en": "On this Studio the twins cannot review the design: no model is connected for "
        "the review ({code}). The design stays as it is; whoever runs the Studio can connect "
        "one.",
    },
    "design.errors.DESIGN_EVALUATOR_NOT_CONFIGURED": {
        "it": "Su questo Studio i twin non possono rivedere il design: non c'è né un modello "
        "né un controllo automatico per la revisione ({code}). Il design resta com'è; chi "
        "gestisce lo Studio può collegarne uno.",
        "en": "On this Studio the twins cannot review the design: neither a model nor an "
        "automatic check for the review is connected ({code}). The design stays as it is; "
        "whoever runs the Studio can connect one.",
    },
    "design.errors.DESIGN_PROTOTYPE_REQUIRED": {
        "it": "I twin rivedono il design scelto: prima scegli un'alternativa ({code}).",
        "en": "The twins review the chosen design: choose an alternative first ({code}).",
    },
    "design.errors.USER_TWIN_CONTEXT_CHANGED": {
        "it": "I twin sono cambiati dopo che il design è stato preparato, quindi non possono "
        "rivederlo così ({code}). Controlla i passi precedenti con `ut status`.",
        "en": "The twins changed after the design was prepared, so they cannot review it as it "
        "is ({code}). Check the earlier steps with `ut status`.",
    },
    "design.errors.PACKAGE_NOT_READY": {
        "it": "Il design non è pronto per l'approvazione: prima scegli un'alternativa ({code}).",
        "en": "The design is not ready for approval: choose an alternative first ({code}).",
    },
    "design.errors.ITERATION_LIMIT_REACHED": {
        "it": "Lo Studio non accetta un'altra versione del design: le ultime tre non sono state "
        "approvate ({code}).",
        "en": "The Studio does not accept another version of the design: the last three were not "
        "approved ({code}).",
    },
    "design.errors.GATE_BLOCKED": {
        "it": "L'approvazione del design è sospesa nello Studio ({code}): riprendila "
        "dall'interfaccia web, poi riprova.",
        "en": "The approval of the design is on hold in the Studio ({code}): resume it in the "
        "web interface, then try again.",
    },
    "design.errors.NEW_PACKAGE_REQUIRED": {
        "it": "Questa versione del design è già stata respinta: serve una nuova versione, per "
        "esempio con una modifica ({code}).",
        "en": "This version of the design was already turned down: a new version is needed, "
        "for example with a change ({code}).",
    },
    "design.errors.DIFF_ALREADY_PENDING": {
        "it": "Nello Studio c'è già una proposta di cambiamento del design in attesa di "
        "decisione, fatta altrove (forse dall'interfaccia web). Decidila lì, poi rilancia il "
        "comando.",
        "en": "The Studio already holds a proposed change of the design waiting for a "
        "decision, made elsewhere (perhaps in the web interface). Decide it there, then launch "
        "the command again.",
    },
    "design.errors.CHANGE_EMPTY": {
        "it": "La modifica è vuota: scrivi a parole che cosa vuoi cambiare.",
        "en": "The change is empty: write in words what you want to change.",
    },
    "design.errors.CHANGE_TOO_LONG": {
        "it": "La modifica è troppo lunga: {length} caratteri, al massimo {limit}. Accorciala e "
        "riprova; non ho speso nulla.",
        "en": "The change is too long: {length} characters, at most {limit}. Make it shorter "
        "and try again; nothing was spent.",
    },
    "design.errors.CHANGE_NOT_VALID": {
        "it": "La modifica contiene caratteri di controllo che lo Studio non accetta: "
        "riscrivila; non ho speso nulla.",
        "en": "The change contains control characters that the Studio does not accept: write "
        "it again; nothing was spent.",
    },
    "design.errors.RULE_NOT_VALID": {
        "it": "La regola “{rule}” non va bene: al massimo {limit} caratteri e nessun carattere "
        "di controllo. Correggila; non ho speso nulla.",
        "en": "The rule “{rule}” is not valid: at most {limit} characters and no control "
        "characters. Correct it; nothing was spent.",
    },
    "design.errors.TOO_MANY_NEW_RULES": {
        "it": "Puoi aggiungere al massimo {limit} regole per ogni modifica; non ho speso nulla.",
        "en": "You can add at most {limit} rules with each change; nothing was spent.",
    },
    "design.errors.TOO_MANY_RULES": {
        "it": "Le regole in vigore sono già {count} e il massimo è {limit}: aggiungine meno; "
        "non ho speso nulla.",
        "en": "There are already {count} rules in force and the maximum is {limit}: add fewer; "
        "nothing was spent.",
    },
    **{
        f"design.visual_{dimension}_{value}": {"it": italian, "en": english}
        for dimension, words in VISUAL_WORDS.items()
        for value, (italian, english) in words.items()
    },
}
