from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "push.help": {
        "it": "Invia allo Studio le modifiche fatte a mano nella cartella di conoscenza, come "
        "versioni fornite da te",
        "en": "Send the hand-made changes of the knowledge folder to the Studio as versions "
        "supplied by you",
    },
    "push.option_dry_run": {
        "it": "mostra soltanto le differenze, senza inviare niente allo Studio",
        "en": "only show the differences, without sending anything to the Studio",
    },
    "push.option_stage": {
        "it": "invia soltanto le modifiche di questo passo",
        "en": "send only the changes of this step",
    },
    "push.summary": {
        "it": "Rispetto alla versione {version} della cartella: documenti dei passi cambiati "
        "{pushable}, file derivati cambiati {derived}, file sconosciuti {unknown}.",
        "en": "Compared with version {version} of the folder: step documents changed "
        "{pushable}, derived files changed {derived}, unknown files {unknown}.",
    },
    "push.file_pushable": {
        "it": "  {path} ({change}): documento del passo «{stage}», le sue modifiche si possono "
        "inviare.",
        "en": '  {path} ({change}): document of the "{stage}" step, its changes can be sent.',
    },
    "push.file_derived": {
        "it": "  {path} ({change}): file derivato, non si invia.",
        "en": "  {path} ({change}): derived file, it is not sent.",
    },
    "push.file_unknown": {
        "it": "  {path} ({change}): file che lo Studio non conosce, resta sul disco e non si "
        "invia.",
        "en": "  {path} ({change}): a file the Studio does not know, it stays on the disk and "
        "is not sent.",
    },
    "push.change_changed": {"it": "cambiato", "en": "changed"},
    "push.change_added": {"it": "aggiunto", "en": "added"},
    "push.change_deleted": {"it": "cancellato", "en": "deleted"},
    "push.derived_hint": {
        "it": "I file derivati si rigenerano dallo Studio: modifica i documenti JSON dei passi.",
        "en": "Derived files are generated again by the Studio: change the JSON documents of "
        "the steps.",
    },
    "push.diff_line": {"it": "    {sign} {what}", "en": "    {sign} {what}"},
    "push.brief_fields_ignored": {
        "it": "    Campi del Brief che lo Studio non prevede, lasciati fuori: {fields}.",
        "en": "    Fields of the Brief that the Studio does not expect, left out: {fields}.",
    },
    "push.twin_fields_ignored": {
        "it": "    Modifiche di «{name}» che non si possono inviare, lasciate fuori: {fields}.",
        "en": '    Changes of "{name}" that cannot be sent, left out: {fields}.',
    },
    "push.nothing": {
        "it": "Nessun documento dei passi ha modifiche da inviare: non c'è niente da fare.",
        "en": "No step document has changes to send: there is nothing to do.",
    },
    "push.dry_run_done": {
        "it": "Prova senza invio (--dry-run): lo Studio e la cartella restano come sono.",
        "en": "Trial without sending (--dry-run): the Studio and the folder stay as they are.",
    },
    "push.send_stage": {
        "it": "Invio allo Studio le modifiche di «{stage}»?",
        "en": 'Send the changes of "{stage}" to the Studio?',
    },
    "push.approve_stage": {
        "it": "Approvi le differenze di «{stage}»? Diventano una versione nuova, fornita da te.",
        "en": 'Do you approve the differences of "{stage}"? They become a new version, '
        "supplied by you.",
    },
    "push.stage_kept": {
        "it": "«{stage}» resta com'era nello Studio.",
        "en": '"{stage}" stays as it was in the Studio.',
    },
    "push.stage_unchanged": {
        "it": "Nello Studio «{stage}» è già così: non c'è niente da inviare.",
        "en": 'In the Studio "{stage}" is already like this: there is nothing to send.',
    },
    "push.reject_reason": {
        "it": "Rifiutata dal proprietario del progetto con ut push.",
        "en": "Refused by the owner of the project with ut push.",
    },
    "push.done": {
        "it": "Inviato: {stages}. Cartella alla versione {version} ({files} file).",
        "en": "Sent: {stages}. Folder at version {version} ({files} files).",
    },
    "push.files_kept": {
        "it": "Rimessi nella cartella come li avevi lasciati, senza inviarli: {files}. Finché "
        "ci sono, la cartella non supera la verifica.",
        "en": "Put back in the folder as you left them, without sending them: {files}. While "
        "they are there, the folder does not pass the verification.",
    },
    "push.errors.FOLDER_MISSING": {
        "it": "Nel progetto non c'è la cartella di conoscenza {path}: scaricala con "
        "`ut package pull`, modificala e rilancia `ut push`.",
        "en": "The project has no knowledge folder {path}: download it with `ut package pull`, "
        "change it and launch `ut push` again.",
    },
    "push.errors.PUSH_FOLDER_BEHIND": {
        "it": "Lo Studio è alla versione {studio}, la cartella parte dalla {local}: scarica con "
        "`ut package pull` e rifai le modifiche.",
        "en": "The Studio is at version {studio}, the folder starts from version {local}: "
        "download it with `ut package pull` and make the changes again.",
    },
    "push.errors.PUSH_REVISION_PENDING": {
        "it": "C'è già una revisione in attesa per «{stage}»: decidila nel web prima di inviare.",
        "en": 'A revision already waits for "{stage}": decide it in the web before sending.',
    },
    "push.errors.PUSH_DOCUMENT_INVALID": {
        "it": "Il documento {path} non si legge come documento del passo: deve essere JSON "
        "valido e contenere «{key}». Correggilo, oppure scaricalo di nuovo con "
        "`ut package pull`.",
        "en": "The document {path} cannot be read as a step document: it must be valid JSON "
        'and hold "{key}". Fix it, or download it again with `ut package pull`.',
    },
    "push.errors.PUSH_DESIGN_MISSING": {
        "it": "Lo Studio non ha ancora un Design: generalo con `ut design`; un Design scritto a "
        "mano non si può fornire.",
        "en": "The Studio has no Design yet: generate it with `ut design`; a Design written by "
        "hand cannot be supplied.",
    },
    "push.errors.INVALID_PROPOSAL": {
        "it": "Lo Studio non accetta la Definizione modificata: forse cambia il codice di voci "
        "esistenti, oppure parte da passi precedenti diversi da quelli dello Studio. "
        "Controlla il file, oppure scarica la cartella con `ut package pull` e rifai le "
        "modifiche.",
        "en": "The Studio does not accept the changed Definition: perhaps it changes the code "
        "of existing entries, or it starts from earlier steps that differ from those of the "
        "Studio. Check the file, or download the folder with `ut package pull` and make the "
        "changes again.",
    },
    "push.errors.CONTEXT_CHANGED": {
        "it": "Nello Studio il passo non parte più dalle versioni da cui partono le tue "
        "modifiche: scarica la cartella con `ut package pull` e rifai le modifiche.",
        "en": "In the Studio the step no longer starts from the versions your changes start "
        "from: download the folder with `ut package pull` and make the changes again.",
    },
    "push.errors.IDENTIFIER_CHANGED": {
        "it": "Il Design modificato cambia il codice o l'identificativo di voci esistenti: lo "
        "Studio non lo accetta. Lascia com'erano i campi id e code.",
        "en": "The changed Design changes the code or the identifier of existing entries: the "
        "Studio does not accept it. Leave the id and code fields as they were.",
    },
    "push.errors.GATE_REFUSED": {
        "it": "Lo Studio non accetta l'approvazione del passo «{step}» ({code}): la versione "
        "inviata resta da approvare. Apri il progetto nell'interfaccia web per vedere perché.",
        "en": 'The Studio does not accept the approval of the step "{step}" ({code}): the '
        "version sent still waits for approval. Open the project in the web interface to see "
        "why.",
    },
    "push.errors.STATE_CHANGED": {
        "it": "Il progetto è cambiato mentre ut push lavorava ({code}): forse è aperto anche "
        "nell'interfaccia web. Finisci lì le modifiche, poi rilancia `ut push`.",
        "en": "The project changed while ut push worked ({code}): perhaps it is open in the web "
        "interface too. Finish the changes there, then launch `ut push` again.",
    },
    "push.errors.BRIEF_INCOMPLETE": {
        "it": "Il Brief inviato non si può approvare, mancano questi punti: {fields}. "
        "Completali in brief/brief.json e rilancia `ut push`.",
        "en": "The Brief sent cannot be approved, these points are missing: {fields}. Fill "
        "them in brief/brief.json and launch `ut push` again.",
    },
}
