from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "archetypes.option_clear_goals": {
        "it": "lascia gli obiettivi sconosciuti; incompatibile con --goal",
        "en": "leave goals unknown; incompatible with --goal",
    },
    "archetypes.help": {
        "it": "Mostra e gestisce gli archetipi del progetto",
        "en": "Show and manage the project's archetypes",
    },
    "archetypes.heading": {"it": "Archetipi", "en": "Archetypes"},
    "archetypes.help_add": {"it": "Aggiungi un archetipo", "en": "Add an archetype"},
    "archetypes.help_edit": {"it": "Modifica un archetipo", "en": "Edit an archetype"},
    "archetypes.help_remove": {
        "it": "Archivia un archetipo conservando lo storico",
        "en": "Archive an archetype, keeping its history",
    },
    "archetypes.option_json": {"it": "mostra i dati JSON", "en": "show the JSON data"},
    "archetypes.option_archetype": {
        "it": "ID, numero o nome dell'archetipo",
        "en": "archetype ID, number or name",
    },
    "archetypes.option_name": {"it": "nome", "en": "name"},
    "archetypes.option_description": {"it": "breve descrizione", "en": "short description"},
    "archetypes.option_role": {"it": "ruolo", "en": "role"},
    "archetypes.option_context": {
        "it": "contesto, vuoto se sconosciuto",
        "en": "context, empty if unknown",
    },
    "archetypes.option_goal": {
        "it": "obiettivo; ripeti il flag per più obiettivi",
        "en": "goal; repeat the flag for more goals",
    },
    "archetypes.column_number": {"it": "N.", "en": "No."},
    "archetypes.column_name": {"it": "Nome", "en": "Name"},
    "archetypes.column_description": {"it": "Descrizione", "en": "Description"},
    "archetypes.column_version": {"it": "Versione", "en": "Version"},
    "archetypes.changed": {
        "it": "Archetipo salvato. Usa ut init per aggiornare e approvare i User Twin.",
        "en": "Archetype saved. Use ut init to update and approve the User Twins.",
    },
    "archetypes.manage": {"it": "Gestisci gli archetipi:", "en": "Manage the archetypes:"},
    "archetypes.done": {"it": "Continua", "en": "Continue"},
    "archetypes.select": {
        "it": "Quale archetipo? ID, numero o nome:",
        "en": "Which archetype? ID, number or name:",
    },
    "archetypes.ask_name": {"it": "Nome:", "en": "Name:"},
    "archetypes.ask_description": {"it": "Descrizione:", "en": "Description:"},
    "archetypes.ask_role": {"it": "Ruolo:", "en": "Role:"},
    "archetypes.ask_context": {
        "it": "Contesto, vuoto se sconosciuto:",
        "en": "Context, empty if unknown:",
    },
    "archetypes.ask_goals": {
        "it": "Obiettivi separati da ;, vuoto se sconosciuti:",
        "en": "Goals separated by ;, empty if unknown:",
    },
    "archetypes.errors.ARCHETYPE_NOT_FOUND": {
        "it": "Archetipo non trovato. Rileggi l'elenco con ut archetypes.",
        "en": "Archetype not found. Read the list again with ut archetypes.",
    },
    "archetypes.errors.ARCHETYPE_INPUT_INVALID": {
        "it": "Nome, descrizione e ruolo devono essere compilati.",
        "en": "Name, description and role must be filled in.",
    },
    "archetypes.errors.PROJECT_NOT_FOUND": {
        "it": "Il progetto non è disponibile per questo account.",
        "en": "The project is not available to this account.",
    },
    "archetypes.errors.ARCHETYPE_LIMIT_REACHED": {
        "it": "Il progetto ha già otto archetipi attivi. Archivia un archetipo prima di aggiungerne un altro.",
        "en": "The project already has eight active archetypes. Archive one before adding another.",
    },
    "archetypes.errors.ARCHETYPE_VERSION_CONFLICT": {
        "it": "L'archetipo è cambiato. Rileggi l'elenco e ripeti la modifica.",
        "en": "The archetype changed. Read the list again and repeat the edit.",
    },
    "archetypes.errors.ARCHETYPE_ALREADY_ARCHIVED": {
        "it": "L'archetipo è già archiviato; lo storico resta salvato.",
        "en": "The archetype is already archived; its history is still saved.",
    },
    "archetypes.errors.USER_TWIN_REVISION_PENDING": {
        "it": "Decidi prima la revisione del User Twin in attesa.",
        "en": "Decide the pending User Twin revision first.",
    },
    "archetypes.errors.PERSISTENCE_REJECTED": {
        "it": "Il salvataggio è stato rifiutato. Rileggi l'elenco prima di riprovare.",
        "en": "Saving was refused. Read the list again before trying again.",
    },
    "archetypes.errors.invalid_request": {
        "it": "I campi non sono validi: controlla testi, obiettivi e versione.",
        "en": "The fields are invalid: check the texts, goals and version.",
    },
    "archetypes.errors.REQUEST_VALIDATION_ERROR": {
        "it": "I campi non sono validi: controlla testi, obiettivi e versione.",
        "en": "The fields are invalid: check the texts, goals and version.",
    },
}
