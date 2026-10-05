from __future__ import annotations

from types import MappingProxyType

MESSAGES = MappingProxyType(
    {
        "evidence.help": {
            "it": "Aggiungi e governa fonti testuali dei twin.",
            "en": "Add and govern textual sources for twins.",
        },
        "evidence.option_all": {
            "it": "Mostra anche versioni precedenti e ritirate.",
            "en": "Include previous and retired versions.",
        },
        "evidence.option_json": {"it": "Mostra JSON.", "en": "Show JSON."},
        "evidence.option_text": {
            "it": "Richiedi il testo originale allo Studio.",
            "en": "Request the original text from the Studio.",
        },
        "evidence.help_add": {
            "it": "Aggiungi un file UTF-8 .txt o .md.",
            "en": "Add a UTF-8 .txt or .md file.",
        },
        "evidence.help_revise": {
            "it": "Aggiungi una nuova versione della fonte.",
            "en": "Add a new source version.",
        },
        "evidence.help_show": {
            "it": "Leggi metadati e citazioni di una fonte.",
            "en": "Read source metadata and citations.",
        },
        "evidence.help_retire": {
            "it": "Ritira una fonte e riapri ciò che dipende da essa.",
            "en": "Retire a source and reopen its dependants.",
        },
        "evidence.help_delete-text": {
            "it": "Elimina i testi originali dopo il ritiro.",
            "en": "Delete original texts after retirement.",
        },
        "evidence.help_reassociate": {
            "it": "Riassocia il testo originale importato con hash identico.",
            "en": "Reassociate imported original text with the same hash.",
        },
        "evidence.privacy": {
            "it": "Il testo sarà inviato al modello quando chiedi una proposta. Prima anonimizzalo e rimuovi dati personali. Inserirlo o approvarlo non è ricerca empirica né validazione umana.",
            "en": "The text will be sent to the model when you request a proposal. Anonymize it and remove personal data first. Adding or approving it is neither empirical research nor human validation.",
        },
        "evidence.confirm_add": {
            "it": "Confermi che il testo è anonimizzato e può essere inviato al modello?",
            "en": "Confirm that the text is anonymized and may be sent to the model?",
        },
        "evidence.heading": {"it": "Fonti di evidenza", "en": "Evidence sources"},
        "evidence.none": {"it": "Nessuna fonte disponibile.", "en": "No sources available."},
        "evidence.empirical": {
            "it": "ricerca empirica dichiarata dal proprietario",
            "en": "empirical research declared by the owner",
        },
        "evidence.non_empirical": {"it": "non empirica", "en": "nonempirical"},
        "evidence.source_ref": {"it": "Origine", "en": "Origin"},
        "evidence.context": {"it": "Contesto", "en": "Context"},
        "evidence.method": {"it": "Metodo", "en": "Method"},
        "evidence.limitations": {"it": "Limiti", "en": "Limitations"},
        "evidence.content_hash": {"it": "Hash del testo", "en": "Text hash"},
        "evidence.offline": {
            "it": "Studio non raggiungibile: leggo gli estratti del Dossier, senza testo originale.",
            "en": "The Studio is unavailable: reading Dossier excerpts without original text.",
        },
        "evidence.retire_warning": {
            "it": "La fonte non sarà più utilizzabile. I twin collegati vengono ricalcolati e le sezioni a valle segnalano revisione, senza generazioni.",
            "en": "The source will no longer be usable. Linked twins are recalculated and downstream sections request review without generation.",
        },
        "evidence.confirm_retire": {"it": "Ritiri questa fonte?", "en": "Retire this source?"},
        "evidence.retired": {"it": "{code} ritirata.", "en": "{code} retired."},
        "evidence.review_required": {
            "it": "Un aggiornamento del profilo è già in corso: la fonte è ritirata, ma occorre rivedere il profilo in attesa.",
            "en": "A profile update is already in progress: the source is retired, but the pending profile requires review.",
        },
        "evidence.delete_warning": {
            "it": "Si eliminano soltanto i testi originali dal deposito dello Studio. Citazioni storiche, copie esportate, backup e copie del fornitore del modello possono restare.",
            "en": "Only original texts in Studio storage are deleted. Historical citations, exported copies, backups and provider copies may remain.",
        },
        "evidence.confirm_delete": {
            "it": "Elimini i testi originali?",
            "en": "Delete the original texts?",
        },
        "evidence.deleted": {
            "it": "Testi originali di {code} eliminati.",
            "en": "Original texts for {code} deleted.",
        },
        "evidence.errors.EVIDENCE_LIMIT": {
            "it": "Testo oltre il limite: 24.000 caratteri e 32 KiB per fonte. Dividi il testo in parti e riprova.",
            "en": "Text exceeds the limit: 24,000 characters and 32 KiB per source. Split the text into parts and retry.",
        },
        "evidence.errors.EVIDENCE_INVALID_TEXT": {
            "it": "Usa un file .txt o .md UTF-8 valido, non vuoto e senza dati binari.",
            "en": "Use a valid, nonempty UTF-8 .txt or .md file without binary data.",
        },
        "evidence.errors.EVIDENCE_NOT_FOUND": {
            "it": "Fonte non trovata: usa un codice EVD-001 mostrato da ut evidence.",
            "en": "Source not found: use an EVD-001 code shown by ut evidence.",
        },
        "evidence.errors.EVIDENCE_CONTEXT_CHANGED": {
            "it": "Il testo non coincide con l'hash della versione importata. Usa il documento originale di quella versione.",
            "en": "The text does not match the imported version hash. Use that version's original document.",
        },
    }
)
