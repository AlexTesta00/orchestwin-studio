from __future__ import annotations

COSTS = {
    "BRIEF_QUESTION": 12_000,
    "BRIEF_SYNTHESIS": 30_000,
    "TEAM_PROPOSAL": 25_000,
    "PERSONA_PROPOSAL": 50_000,
    "USER_TWIN_GENERATION": 150_000,
    "TWIN_CHAT": 30_000,
    "REQUIREMENTS_PROPOSAL": 280_000,
    "REQUIREMENTS_CHANGE": 300_000,
    "DESIGN_PROPOSAL": 450_000,
    "DESIGN_REGENERATION": 450_000,
    "DESIGN_DIRECTIONS": 150_000,
    "MOCKUP": 1_450_000,
    "ITERATION": 1_100_000,
    "DESIGN_EVALUATION": 165_000,
    "DESIGN_CHANGE_OPINION": 120_000,
    "DESIGN_CRITIQUE": 225_000,
    "CODE_CHANGE_REVIEW": 200_000,
    "CODE_ALIGNMENT": 250_000,
    "TEST_PLAN": 200_000,
    "TEST_REVIEW": 150_000,
    "TWIN_UPDATE": 150_000,
    "KNOWLEDGE_ALIGNMENT": 300_000,
    "DESIGN_CHANGE": 350_000,
}
TASKS = {
    "BRIEF_QUESTION": "brief",
    "BRIEF_SYNTHESIS": "brief",
    "TEAM_PROPOSAL": "team",
    "PERSONA_PROPOSAL": "user_modeling",
    "USER_TWIN_GENERATION": "user_modeling",
    "TWIN_CHAT": "user_modeling",
    "REQUIREMENTS_PROPOSAL": "requirements",
    "REQUIREMENTS_CHANGE": "requirements",
    "DESIGN_PROPOSAL": "design",
    "DESIGN_REGENERATION": "design",
    "DESIGN_DIRECTIONS": "design",
    "MOCKUP": "design",
    "ITERATION": "design",
    "DESIGN_EVALUATION": "twin_review",
    "DESIGN_CHANGE_OPINION": "twin_review",
    "DESIGN_CRITIQUE": "user-twin-evaluation",
    "CODE_CHANGE_REVIEW": "user-twin-evaluation",
    "CODE_ALIGNMENT": "user-twin-evaluation",
    "TEST_PLAN": "requirements",
    "TEST_REVIEW": "user-twin-evaluation",
    "TWIN_UPDATE": "user-twin-evaluation",
    "KNOWLEDGE_ALIGNMENT": "requirements",
    "DESIGN_CHANGE": "design",
}
PURPOSES = {
    "BRIEF_QUESTION": "BRIEF_QUESTION",
    "BRIEF_SYNTHESIS": "BRIEF_SYNTHESIS",
    "TEAM_PROPOSAL": "TEAM_PROPOSAL",
    "PERSONA_PROPOSAL": "PERSONA_PROPOSAL",
    "USER_TWIN_GENERATION": "USER_TWIN_GENERATION",
    "TWIN_CHAT": "TWIN_CHAT",
    "REQUIREMENTS_PROPOSAL": "REQUIREMENTS_PROPOSAL",
    "REQUIREMENTS_CHANGE": "REQUIREMENTS_CHANGE",
    "DESIGN_PROPOSAL": "DESIGN_ALTERNATIVES_HOSTED",
    "DESIGN_REGENERATION": "DESIGN_ALTERNATIVES_HOSTED",
    "DESIGN_DIRECTIONS": "DESIGN_DIRECTIONS",
    "MOCKUP": "DESIGN_MOCKUP_HTML",
    "ITERATION": "DESIGN_ITERATION",
    "DESIGN_EVALUATION": "DESIGN_TWIN_REVIEW",
    "DESIGN_CHANGE_OPINION": "DESIGN_CHANGE_OPINION",
    "DESIGN_CRITIQUE": "DESIGN_CRITIQUE",
    "CODE_CHANGE_REVIEW": "CODE_CHANGE_REVIEW",
    "CODE_ALIGNMENT": "CODE_ALIGNMENT",
    "TEST_PLAN": "TEST_PLAN",
    "TEST_REVIEW": "TEST_REVIEW",
    "TWIN_UPDATE": "TWIN_UPDATE",
    "KNOWLEDGE_ALIGNMENT": "KNOWLEDGE_ALIGNMENT",
    "DESIGN_CHANGE": "DESIGN_CHANGE",
}
TEAM_CONTENT_KEYS = (
    "schema_version",
    "provider_kind",
    "provider_id",
    "provider_version",
    "project_mode",
    "brief_version_id",
    "brief_version_number",
    "brief_content_hash",
    "catalog_version",
    "catalog_content_hash",
    "constraints_content_hash",
)
LAX_BOOLEANS = {
    "0": False,
    "off": False,
    "f": False,
    "false": False,
    "n": False,
    "no": False,
    "1": True,
    "on": True,
    "t": True,
    "true": True,
    "y": True,
    "yes": True,
}
ALIGNMENT_TEXTS = {
    "it": {
        "summary": "Il codice di {count} commit cambia ciò che la conoscenza dice su «{line}».",
        "summary_empty": "I commit esaminati non cambiano ciò che la conoscenza del progetto dice.",
        "rationale": "Il diff registrato motiva la proposta.",
        "requirements_title": "Aggiorna la Definizione dopo «{line}»",
        "requirements_request": (
            "Aggiorna il requisito {code} in base a {file}: il codice ora realizza «{line}»."
        ),
        "requirements_rationale": "Il diff di {file} cambia il comportamento descritto nella "
        "Definizione.",
        "design_title": "Aggiorna il Design dopo «{line}»",
        "design_request": (
            "Aggiorna la descrizione e i flussi dell'alternativa scelta per la schermata "
            "{screen}: il codice ora realizza «{line}»."
        ),
        "design_rationale": "Il diff tocca {count} file che il Design descrive.",
        "tests_title": "Aggiorna il piano dei test dopo «{line}»",
        "tests_request": "Copri con un percorso di prova il criterio {code} dopo «{line}».",
        "tests_rationale": "Il piano dei test non copre ancora la modifica del codice.",
        "design_change": "L'alternativa «{title}» cambia come chiesto: {request}",
        "targeted_element": "Modifica mirata a {element} di {screen}",
        "targeted_screen": "Modifica mirata a {screen}",
        "targeted_parts": "Modifica mirata a {elements} di {screen}",
        "and": "e",
    },
    "en": {
        "summary": "The code of {count} commits changes what the knowledge says about “{line}”.",
        "summary_empty": "The reviewed commits do not change what the project knowledge says.",
        "rationale": "The recorded diff motivates the proposal.",
        "requirements_title": "Update the Definition after “{line}”",
        "requirements_request": (
            "Update the requirement {code} according to {file}: the code now realizes “{line}”."
        ),
        "requirements_rationale": "The diff of {file} changes the behaviour the Definition "
        "describes.",
        "design_title": "Update the Design after “{line}”",
        "design_request": (
            "Update the description and the flows of the chosen alternative for the screen "
            "{screen}: the code now realizes “{line}”."
        ),
        "design_rationale": "The diff touches {count} files that the Design describes.",
        "tests_title": "Update the test plan after “{line}”",
        "tests_request": "Cover the criterion {code} with a test path after “{line}”.",
        "tests_rationale": "The test plan does not cover the code change yet.",
        "design_change": "The alternative “{title}” changes as asked: {request}",
        "targeted_element": "Targeted change to {element} of {screen}",
        "targeted_screen": "Targeted change to {screen}",
        "targeted_parts": "Targeted change to {elements} of {screen}",
        "and": "and",
    },
}
WORKFLOW_STEPS = {
    "GUIDED_WORKFLOW": (
        "Open the guided sequence for {code}.",
        "Collect only the information required by the current step.",
        "Review linked requirements before confirming the outcome.",
    ),
    "DASHBOARD_FIRST": (
        "Review current status and priorities in the operational overview.",
        "Open the contextual action panel for {code}.",
        "Complete the linked actions while preserving overview context.",
        "Return to the overview with updated status and feedback.",
    ),
    "TASK_FOCUSED": (
        "Open the focused workspace for {code}.",
        "Complete the information required by the linked requirements.",
        "Resolve inline validation feedback in the same workspace.",
        "Confirm the expected outcome and review the completion summary.",
    ),
}
PERSONAS = {
    "it": (
        "Cameriere del turno serale",
        "Titolare della pizzeria",
        "Cliente abituale",
        "Cassiera del bar",
        "Turista in vacanza",
        "Studente fuori sede",
        "Responsabile di sala",
        "Contabile del locale",
    ),
    "en": (
        "Evening shift waiter",
        "Pizzeria owner",
        "Regular customer",
        "Bar cashier",
        "Tourist on holiday",
        "Student living away from home",
        "Dining room manager",
        "Restaurant accountant",
    ),
}
PROFILE = {
    "it": {
        "summary": "{name} usa il calcolo della mancia a fine pasto.",
        "goals": ("Chiudere il conto in fretta", "Evitare errori di calcolo"),
        "context": "Al tavolo, dal telefono, spesso con poca luce.",
        "expertise": ("Conti del ristorante",),
        "tasks": ("Calcolare la mancia", "Dividere il conto"),
        "needs": ("Quota per persona",),
        "frustrations": ("Conti a mente sbagliati",),
        "pain_points": ("Attesa alla cassa",),
        "literacy": "Usa il telefono ogni giorno.",
        "assumptions": ("Paga spesso con la carta",),
    },
    "en": {
        "summary": "{name} works out the tip at the end of a meal.",
        "goals": ("Settle the bill quickly", "Avoid calculation mistakes"),
        "context": "At the table, on a phone, often in dim light.",
        "expertise": ("Restaurant bills",),
        "tasks": ("Work out the tip", "Split the bill"),
        "needs": ("Share per person",),
        "frustrations": ("Wrong mental maths",),
        "pain_points": ("Waiting at the till",),
        "literacy": "Uses a phone every day.",
        "assumptions": ("Often pays by card",),
    },
}
REQUIREMENTS = {
    "it": (
        (
            "FUNCTIONAL",
            "MUST",
            "Inserimento dell'importo",
            "Il sistema permette di inserire l'importo del conto in euro.",
        ),
        (
            "FUNCTIONAL",
            "MUST",
            "Scelta della mancia",
            "Il sistema permette di scegliere la mancia tra 5, 10 e 15 per cento.",
        ),
        (
            "FUNCTIONAL",
            "SHOULD",
            "Divisione del conto",
            "Il sistema mostra la quota di ciascun commensale.",
        ),
        (
            "NON_FUNCTIONAL",
            "MUST",
            "Risposta immediata",
            "Il risultato compare in meno di un secondo.",
        ),
    ),
    "en": (
        ("FUNCTIONAL", "MUST", "Amount entry", "The system lets people enter the bill in euros."),
        (
            "FUNCTIONAL",
            "MUST",
            "Tip choice",
            "The system lets people choose a tip of 5, 10 or 15 percent.",
        ),
        ("FUNCTIONAL", "SHOULD", "Bill split", "The system shows the share of each diner."),
        ("NON_FUNCTIONAL", "MUST", "Immediate answer", "The result appears in under a second."),
    ),
}
CRITERIA = {
    "it": (
        "Con 30 euro e il 15 per cento la mancia è di 4,50 euro.",
        "L'elenco delle percentuali mostra 5, 10 e 15.",
        "Con 3 persone ogni quota è un terzo del totale.",
        "Il risultato compare entro un secondo.",
    ),
    "en": (
        "With 30 euros and 15 percent the tip is 4.50 euros.",
        "The list of percentages shows 5, 10 and 15.",
        "With 3 people each share is a third of the total.",
        "The result appears within one second.",
    ),
}
SCENARIO = {
    "it": (
        "Mancia a fine cena",
        ("Il conto è arrivato al tavolo",),
        "Il cliente apre la pagina",
        ("Inserisce l'importo", "Sceglie il 10 per cento", "Legge la mancia"),
        "Sa quanto lasciare in pochi secondi",
    ),
    "en": (
        "Tip after dinner",
        ("The bill has reached the table",),
        "The customer opens the page",
        ("Enters the amount", "Chooses 10 percent", "Reads the tip"),
        "Knows how much to leave within seconds",
    ),
}
ALTERNATIVES = {
    "it": (
        {
            "code": "DES-001",
            "approach": "GUIDED_WORKFLOW",
            "title": "Calcolo guidato",
            "summary": "Due passi: prima l'importo, poi il risultato.",
            "rationale": "Chi è al tavolo segue un passo alla volta senza distrazioni.",
            "product_name": "Mancia facile",
            "archetype": "GUIDED_STEPS",
            "hue": "TEAL",
            "mode": "LIGHT",
            "tone": "WARM",
        },
        {
            "code": "DES-002",
            "approach": "TASK_FOCUSED",
            "title": "Scheda unica",
            "summary": "Importo, mancia e quote nella stessa scheda.",
            "rationale": "Chi ha fretta vede tutto il calcolo in un colpo d'occhio.",
            "product_name": "Conto chiaro",
            "archetype": "SINGLE_CARD",
            "hue": "COBALT",
            "mode": "DARK",
            "tone": "ESSENTIAL",
        },
    ),
    "en": (
        {
            "code": "DES-001",
            "approach": "GUIDED_WORKFLOW",
            "title": "Guided calculation",
            "summary": "Two steps: first the amount, then the result.",
            "rationale": "People at the table follow one step at a time without distractions.",
            "product_name": "Easy tip",
            "archetype": "GUIDED_STEPS",
            "hue": "TEAL",
            "mode": "LIGHT",
            "tone": "WARM",
        },
        {
            "code": "DES-002",
            "approach": "TASK_FOCUSED",
            "title": "Single card",
            "summary": "Amount, tip and shares on the same card.",
            "rationale": "People in a hurry see the whole calculation at a glance.",
            "product_name": "Clear bill",
            "archetype": "SINGLE_CARD",
            "hue": "COBALT",
            "mode": "DARK",
            "tone": "ESSENTIAL",
        },
    ),
}
SYSTEM_ALTERNATIVES = {
    "it": {
        "code": "DES-003",
        "approach": "INFORMATION_RICH",
        "title": "Calcolo in stile iPhone",
        "summary": "Importo, mancia e totale su pannelli chiari, come in un'app di sistema.",
        "rationale": "Chi usa un iPhone ritrova le forme e i gesti che conosce già.",
        "product_name": "Mancia",
        "archetype": "SINGLE_CARD",
        "hue": "COBALT",
        "mode": "LIGHT",
        "tone": "CALM",
    },
    "en": {
        "code": "DES-003",
        "approach": "INFORMATION_RICH",
        "title": "iPhone-style calculation",
        "summary": "Amount, tip and total on clear panels, as in an app of the system.",
        "rationale": "People who use an iPhone find the shapes and gestures they already know.",
        "product_name": "Tip",
        "archetype": "SINGLE_CARD",
        "hue": "COBALT",
        "mode": "LIGHT",
        "tone": "CALM",
    },
}
DIRECTED_ALTERNATIVES = {
    "DES-001": (
        {
            "layout": "STAGE",
            "shape": "SOFT_FILL",
            "type": "READING",
            "colour": "TINTED",
            "density": "SPACIOUS",
        },
        8,
    ),
    "DES-002": (
        {
            "layout": "WORKBENCH",
            "shape": "SQUARE_RULES",
            "type": "CAPS_LABELS",
            "colour": "INK",
            "density": "COMFORTABLE",
        },
        5,
    ),
}
DIRECTION_TEXTS = {
    "it": {
        "DES-001": (
            "Foglio da lettura",
            "Una sola colonna centrata, come una pagina da leggere con calma. Al tavolo, con poca "
            "luce, chi paga trova un compito per volta e cifre grandi.",
            (
                "Il titolo della schermata sta in alto al centro, grande e da solo.",
                "I gruppi stanno su superfici tinte, senza bordi.",
                "L'azione principale è un pulsante pieno, l'unico elemento colorato.",
            ),
        ),
        "DES-002": (
            "Scontrino di cassa",
            "Uno strumento a tutta larghezza, come uno scontrino: righe fitte, etichette "
            "maiuscole, cifre in colonna. Chi divide il conto confronta le quote a colpo d'occhio.",
            (
                "Il titolo è un'etichetta piccola nella barra in alto.",
                "Filetti sottili separano le righe; nessun riquadro.",
                "Le cifre stanno in colonna, allineate a destra.",
                "Il colore primario compare solo sull'azione principale.",
            ),
        ),
    },
    "en": {
        "DES-001": (
            "Reading sheet",
            "One centred column, like a page read at leisure. At the table, in dim light, whoever "
            "pays finds one task at a time and large digits.",
            (
                "The screen title sits at the top centre, large and alone.",
                "Groups sit on tinted surfaces, without borders.",
                "The main action is a filled button, the only coloured element.",
            ),
        ),
        "DES-002": (
            "Till receipt",
            "A full-width tool, like a receipt: dense rows, upper-case labels, digits in columns. "
            "Whoever splits the bill compares the shares at a glance.",
            (
                "The title is a small label in the top bar.",
                "Thin rules separate the rows; no boxes.",
                "Digits stand in columns, aligned to the right.",
                "The primary colour appears only on the main action.",
            ),
        ),
    },
}
DESIGN_TEXTS = {
    "it": {
        "workflow": (
            "Calcolare la mancia",
            ("Inserire l'importo", "Scegliere la percentuale", "Leggere il risultato"),
        ),
        "architecture": ("Calcolo", "Risultato"),
        "accessibility": ("Cifre grandi e contrasto alto",),
        "security": ("Nessun dato personale salvato",),
        "advantages": ("Pochi passi al tavolo",),
        "trade_offs": ("Meno spazio per i dettagli",),
        "assumptions": ("Il cliente ha il telefono in mano",),
        "questions": ("Serve arrotondare la mancia all'euro?",),
        "concern": (
            "I numeri piccoli sono difficili da leggere al buio.",
            "Usare cifre grandi e un buon contrasto.",
        ),
        "fit": "{name} trova subito il totale.",
        "strength": "Il percorso è chiaro.",
        "suggestion": "Aggiungere la divisione del conto.",
        "rationale": "Critica simulata a partire dal profilo del twin.",
    },
    "en": {
        "workflow": (
            "Work out the tip",
            ("Enter the amount", "Choose the percentage", "Read the result"),
        ),
        "architecture": ("Calculation", "Result"),
        "accessibility": ("Large digits and high contrast",),
        "security": ("No personal data stored",),
        "advantages": ("Few steps at the table",),
        "trade_offs": ("Less room for details",),
        "assumptions": ("The customer holds a phone",),
        "questions": ("Should the tip be rounded to the euro?",),
        "concern": (
            "Small numbers are hard to read in the dark.",
            "Use large digits and good contrast.",
        ),
        "fit": "{name} finds the total at once.",
        "strength": "The path is clear.",
        "suggestion": "Add the bill split.",
        "rationale": "Simulated critique based on the twin profile.",
    },
}
CRITIQUES = {
    "it": {
        "DES-001": (
            ("Chiaro al tavolo", "Vedo subito dove inserire l'importo."),
            ("Utile, con riserve", "Mi serve anche dividere il conto."),
        ),
        "DES-002": (
            ("Tutto a portata di mano", "Una sola scheda mi basta."),
            ("Troppo scuro", "Con il tema scuro leggo male i numeri."),
        ),
        "DES-003": (
            ("Familiare", "Sembra un'app che uso ogni giorno."),
            ("Ordinato", "I pannelli tengono separati importo e mancia."),
        ),
    },
    "en": {
        "DES-001": (
            ("Clear at the table", "I see at once where to type the amount."),
            ("Useful, with doubts", "I also need to split the bill."),
        ),
        "DES-002": (
            ("Everything at hand", "One card is enough for me."),
            ("Too dark", "With the dark theme I misread the numbers."),
        ),
        "DES-003": (
            ("Familiar", "It feels like an app I use every day."),
            ("Tidy", "The panels keep the amount and the tip apart."),
        ),
    },
}
MOCKUP_STYLES = (
    ".page{display:grid;gap:16px;max-width:560px;margin:0 auto;padding:var(--vl-space)}"
    ".card{display:grid;gap:12px;padding:24px;background:var(--vl-color-surface);"
    "border:var(--vl-border-width) solid var(--vl-color-border);"
    "border-radius:var(--vl-radius-panel)}"
    "h1{margin:0;font-family:var(--vl-font-heading);font-size:var(--vl-size-display)}"
    ".lead{margin:0;color:var(--vl-color-text-muted)}"
    "input,select{min-height:var(--vl-control-height);padding:0 12px;"
    "border:1px solid var(--vl-color-text-muted);border-radius:var(--vl-radius-control)}"
    ".button{display:inline-flex;align-items:center;justify-content:center;"
    "min-height:var(--vl-control-height);padding:0 20px;border-radius:var(--vl-radius-control);"
    "background:var(--vl-color-primary);color:var(--vl-color-on-primary);font-weight:700;"
    "text-decoration:none}"
    ".result{margin:0;padding:16px;border-radius:var(--vl-radius-control);"
    "background:var(--vl-color-success-soft);color:var(--vl-color-success);font-weight:700}"
    ".shares{margin:0;padding-left:20px}"
    "@media (max-width:600px){.page{padding:var(--vl-gap)}}"
)
SCREENS = {
    "it": {
        "DES-001": (
            (
                "SCR-001",
                "Importo del conto",
                "DEFAULT",
                "Quanto hai speso?",
                '<main class="page" data-req="REQ-001 REQ-002"><h1>{heading}</h1>'
                '<p class="lead">Scrivi l\'importo del conto e scegli la mancia.</p>'
                '<form class="card" aria-label="Calcolo della mancia">'
                '<label for="amount">Importo del conto</label>'
                '<input id="amount" name="amount" type="text" value="30,00" required>'
                '<label for="tip">Percentuale di mancia</label>'
                '<select id="tip" name="tip" required><option>5%</option>'
                "<option selected>10%</option><option>15%</option></select>"
                '<p class="lead">Di solito la mancia va dal 5% al 10% del conto.</p>'
                '<a class="button" href="#SCR-002">Calcola</a></form></main>',
            ),
            (
                "SCR-002",
                "Risultato",
                "SUCCESS",
                "Ecco la mancia",
                '<main class="page" data-req="REQ-003 REQ-004"><h1>{heading}</h1>'
                '<p class="result" role="status">Esempio: mancia di 3,00 euro su 30,00 euro.</p>'
                '<ul class="shares"><li>Totale da pagare: 33,00 euro</li>'
                "<li>Mancia arrotondata: 3,00 euro</li></ul>"
                '<p class="lead">Il totale compare subito, senza conti a mente.</p>'
                '<a class="button" href="#SCR-001">Nuovo calcolo</a></main>',
            ),
        ),
        "DES-002": (
            (
                "SCR-001",
                "Calcolo mancia",
                "DEFAULT",
                "Calcolo mancia",
                '<main class="card" data-req="REQ-001 REQ-002 REQ-003"><h1>{heading}</h1>'
                '<p class="lead">Inserisci il conto, la mancia e quante persone dividono '
                "la spesa.</p>"
                '<form aria-label="Conto e mancia">'
                '<label for="amount">Importo</label>'
                '<input id="amount" name="amount" type="text" value="34,50" required>'
                '<label for="tip">Mancia</label>'
                '<select id="tip" name="tip"><option>5%</option><option selected>10%</option>'
                "<option>15%</option></select>"
                '<label for="people">Persone al tavolo</label>'
                '<input id="people" name="people" type="text" value="3">'
                '<a class="button" href="#SCR-002">Dividi il conto</a></form>'
                '<ul class="shares"><li>Ultimo conto: 41,20 euro in 4 persone</li></ul></main>',
            ),
            (
                "SCR-002",
                "Conto diviso",
                "SUCCESS",
                "Quota per persona",
                '<main class="card" data-req="REQ-004"><h1>{heading}</h1>'
                '<p class="result" role="status">Esempio: 3 persone, 12,65 euro a testa.</p>'
                '<ul class="shares"><li>Anna: 12,65 euro</li><li>Luca: 12,65 euro</li>'
                "<li>Sara: 12,65 euro</li></ul>"
                '<p class="lead">Ognuno paga la stessa quota, mancia compresa.</p>'
                '<a class="button" href="#SCR-001">Torna al calcolo</a></main>',
            ),
        ),
    },
    "en": {
        "DES-001": (
            (
                "SCR-001",
                "Bill amount",
                "DEFAULT",
                "How much did you spend?",
                '<main class="page" data-req="REQ-001 REQ-002"><h1>{heading}</h1>'
                '<p class="lead">Type the amount of the bill and choose the tip.</p>'
                '<form class="card" aria-label="Tip calculation">'
                '<label for="amount">Bill amount</label>'
                '<input id="amount" name="amount" type="text" value="30.00" required>'
                '<label for="tip">Tip percentage</label>'
                '<select id="tip" name="tip" required><option>5%</option>'
                "<option selected>10%</option><option>15%</option></select>"
                '<p class="lead">In most restaurants a tip ranges from 5% to 10% of the bill.</p>'
                '<a class="button" href="#SCR-002">Calculate</a></form></main>',
            ),
            (
                "SCR-002",
                "Result",
                "SUCCESS",
                "Here is the tip",
                '<main class="page" data-req="REQ-003 REQ-004"><h1>{heading}</h1>'
                '<p class="result" role="status">Example: a tip of 3.00 euros on 30.00 euros.</p>'
                '<ul class="shares"><li>Total to pay: 33.00 euros</li>'
                "<li>Rounded tip: 3.00 euros</li></ul>"
                '<p class="lead">The total appears at once, without mental maths.</p>'
                '<a class="button" href="#SCR-001">New calculation</a></main>',
            ),
        ),
        "DES-002": (
            (
                "SCR-001",
                "Tip calculator",
                "DEFAULT",
                "Tip calculator",
                '<main class="card" data-req="REQ-001 REQ-002 REQ-003"><h1>{heading}</h1>'
                '<p class="lead">Enter the bill, choose the tip and say how many people share '
                "the cost.</p>"
                '<form aria-label="Bill and tip">'
                '<label for="amount">Amount</label>'
                '<input id="amount" name="amount" type="text" value="34.50" required>'
                '<label for="tip">Tip</label>'
                '<select id="tip" name="tip"><option>5%</option><option selected>10%</option>'
                "<option>15%</option></select>"
                '<label for="people">People at the table</label>'
                '<input id="people" name="people" type="text" value="3">'
                '<a class="button" href="#SCR-002">Split the bill</a></form>'
                '<ul class="shares"><li>Last bill: 41.20 euros for 4 people</li></ul></main>',
            ),
            (
                "SCR-002",
                "Split bill",
                "SUCCESS",
                "Share per person",
                '<main class="card" data-req="REQ-004"><h1>{heading}</h1>'
                '<p class="result" role="status">Example: 3 people, 12.65 euros each.</p>'
                '<ul class="shares"><li>Anna: 12.65 euros</li><li>Luca: 12.65 euros</li>'
                "<li>Sara: 12.65 euros</li></ul>"
                '<p class="lead">Everyone pays the same share, tip included.</p>'
                '<a class="button" href="#SCR-001">Back to the calculation</a></main>',
            ),
        ),
    },
}
LANDMARK_ENTRY = {
    "it": (
        "SCR-001",
        "Calcolo mancia",
        "DEFAULT",
        "Calcolo mancia",
        '<header class="bar" data-req="REQ-001"><h1>{heading}</h1>'
        '<a href="#SCR-002">Quote</a><a href="#SCR-002">Scontrino</a></header>'
        '<nav class="tabs" aria-label="Sezioni" data-req="REQ-002">'
        '<a href="#SCR-002">Conto</a><a href="#SCR-002">Mancia</a>'
        '<a href="#SCR-002">Persone</a></nav>'
        '<main class="card" aria-label="Calcolo" data-req="REQ-001 REQ-002 REQ-003">'
        '<p class="lead">Inserisci il conto, la mancia e quante persone dividono la spesa.</p>'
        '<form aria-label="Conto e mancia">'
        '<label for="amount">Importo</label>'
        '<input id="amount" name="amount" type="text" value="34,50" required>'
        '<label for="tip">Mancia</label>'
        '<select id="tip" name="tip"><option>5%</option><option selected>10%</option>'
        "<option>15%</option></select>"
        '<a class="button" href="#SCR-002">Dividi il conto</a></form>'
        '<section class="recent" aria-label="Conti recenti">'
        '<article><h2>Serata pizza</h2><button type="button">Dividi di nuovo</button></article>'
        "<article><h2>Pranzo della domenica</h2>"
        '<button type="button">Mostra le quote</button></article></section></main>',
    ),
    "en": (
        "SCR-001",
        "Tip calculator",
        "DEFAULT",
        "Tip calculator",
        '<header class="bar" data-req="REQ-001"><h1>{heading}</h1>'
        '<a href="#SCR-002">Shares</a><a href="#SCR-002">Receipt</a></header>'
        '<nav class="tabs" aria-label="Sections" data-req="REQ-002">'
        '<a href="#SCR-002">Bill</a><a href="#SCR-002">Tip</a>'
        '<a href="#SCR-002">People</a></nav>'
        '<main class="card" aria-label="Calculation" data-req="REQ-001 REQ-002 REQ-003">'
        '<p class="lead">Enter the bill, choose the tip and say how many people share the '
        "cost.</p>"
        '<form aria-label="Bill and tip">'
        '<label for="amount">Amount</label>'
        '<input id="amount" name="amount" type="text" value="34.50" required>'
        '<label for="tip">Tip</label>'
        '<select id="tip" name="tip"><option>5%</option><option selected>10%</option>'
        "<option>15%</option></select>"
        '<a class="button" href="#SCR-002">Split the bill</a></form>'
        '<section class="recent" aria-label="Recent bills">'
        '<article><h2>Pizza night</h2><button type="button">Split it again</button></article>'
        "<article><h2>Sunday lunch</h2>"
        '<button type="button">Show the shares</button></article></section></main>',
    ),
}
LANDMARK_SCREENS = {
    language: (LANDMARK_ENTRY[language], screens["DES-002"][1])
    for language, screens in SCREENS.items()
}
COLOUR_WORDS = (
    "rosso",
    "blu",
    "verde",
    "giallo",
    "bianco",
    "nero",
    "red",
    "blue",
    "green",
    "yellow",
    "white",
    "black",
)
OPINION_TEXTS = {
    "it": {
        "BLOCKS": "Con questi due colori vicini non leggerei le scritte al tavolo, con poca luce.",
        "SLOWS": "Dopo la modifica dovrei cercare di nuovo dove toccare per dividere il conto.",
        "HELPS": "La modifica mi aiuta: trovo subito quello che mi serve al tavolo.",
        "what_to_do": "Tieni il testo molto più scuro o molto più chiaro dello sfondo.",
        "try_this": "Rendi la barra più scura e il testo bianco, ben leggibile.",
    },
    "en": {
        "BLOCKS": "With these two colours close together I could not read the words at the table.",
        "SLOWS": "After the change I would look again for where to tap to split the bill.",
        "HELPS": "The change helps me: I find what I need at the table at once.",
        "what_to_do": "Keep the text much darker or much lighter than the background.",
        "try_this": "Make the bar darker and the text white, easy to read.",
    },
}
