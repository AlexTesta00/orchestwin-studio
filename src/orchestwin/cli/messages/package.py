from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "package.help": {
        "it": "Porta la cartella di conoscenza tra lo Studio e questa cartella",
        "en": "Move the knowledge folder between the Studio and this folder",
    },
    "package.option_action": {
        "it": "che cosa fare: publish, pull, verify, history oppure import; senza azione "
        "mostra lo stato della cartella",
        "en": "what to do: publish, pull, verify, history or import; without an action the "
        "state of the folder is shown",
    },
    "package.help_publish": {
        "it": "pubblica una nuova versione nello Studio e la scarica in orchestwin/",
        "en": "publish a new version in the Studio and download it into orchestwin/",
    },
    "package.help_pull": {
        "it": "scarica in orchestwin/ una versione già pubblicata",
        "en": "download a published version into orchestwin/",
    },
    "package.option_version": {
        "it": "numero della versione; senza, l'ultima",
        "en": "number of the version; without it, the latest",
    },
    "package.help_verify": {
        "it": "controlla orchestwin/ senza lo Studio",
        "en": "check orchestwin/ without the Studio",
    },
    "package.help_history": {
        "it": "elenca le versioni pubblicate",
        "en": "list the published versions",
    },
    "package.help_import": {
        "it": "crea nello Studio un nuovo progetto da una cartella di conoscenza o dal suo zip",
        "en": "create a new project in the Studio from a knowledge folder or from its zip",
    },
    "package.option_path": {
        "it": "cartella di conoscenza oppure file .zip",
        "en": "knowledge folder or .zip file",
    },
    "package.option_name": {
        "it": "nome del nuovo progetto; senza, quello scritto nella cartella",
        "en": "name of the new project; without it, the one written in the folder",
    },
    "package.heading": {
        "it": "Cartella di conoscenza di «{project}»",
        "en": 'Knowledge folder of "{project}"',
    },
    "package.local_missing": {
        "it": "In questa cartella ({path}): non c'è ancora.",
        "en": "In this folder ({path}): not there yet.",
    },
    "package.local_ok": {
        "it": "In questa cartella ({path}): versione {version} del {date}, supera la verifica.",
        "en": "In this folder ({path}): version {version} of {date}, it passes the verification.",
    },
    "package.local_problem": {
        "it": "In questa cartella ({path}): versione {version}, ma non supera la verifica: il "
        "primo file diverso da quello pubblicato è {file} ({code}).",
        "en": "In this folder ({path}): version {version}, but it does not pass the "
        "verification: the first file that differs from the published one is {file} ({code}).",
    },
    "package.local_line_endings": {
        "it": "In questa cartella ({path}): versione {version}, ma il file {file} ha i fine "
        "riga di Windows, forse cambiati da git ({code}).",
        "en": "In this folder ({path}): version {version}, but the file {file} has Windows "
        "line endings, perhaps changed by git ({code}).",
    },
    "package.local_unreadable": {
        "it": "In questa cartella ({path}): c'è qualcosa, ma non si legge come una cartella di "
        "conoscenza ({code}: {file}).",
        "en": "In this folder ({path}): there is something, but it cannot be read as a "
        "knowledge folder ({code}: {file}).",
    },
    "package.studio_latest": {
        "it": "Nello Studio: versione {version} del {date}.",
        "en": "In the Studio: version {version} of {date}.",
    },
    "package.studio_none": {
        "it": "Nello Studio: nessuna versione pubblicata.",
        "en": "In the Studio: no published version.",
    },
    "package.studio_unreachable": {
        "it": "Nello Studio: non lo so, lo Studio {studio} non risponde.",
        "en": "In the Studio: unknown, the Studio {studio} does not answer.",
    },
    "package.studio_not_signed_in": {
        "it": "Nello Studio: non lo so, non hai eseguito l'accesso a {studio}. Accedi con "
        "`ut login`.",
        "en": "In the Studio: unknown, you are not signed in to {studio}. Sign in with `ut login`.",
    },
    "package.studio_session_expired": {
        "it": "Nello Studio: non lo so, l'accesso a {studio} è scaduto. Accedi di nuovo con "
        "`ut login`.",
        "en": "In the Studio: unknown, your sign-in to {studio} has expired. Sign in again with "
        "`ut login`.",
    },
    "package.studio_project_missing": {
        "it": "Nello Studio: {studio} non trova questo progetto per il tuo account.",
        "en": "In the Studio: {studio} does not find this project for your account.",
    },
    "package.advice_publish_first": {
        "it": "Quando i cinque passi sono approvati, pubblica la cartella con "
        "`ut package publish`.",
        "en": "When the five steps are approved, publish the folder with `ut package publish`.",
    },
    "package.advice_download": {
        "it": "Scarica la versione {version} in questa cartella con `ut package pull`.",
        "en": "Download version {version} into this folder with `ut package pull`.",
    },
    "package.advice_older": {
        "it": "La cartella qui è più vecchia: aggiornala alla versione {version} con "
        "`ut package pull`.",
        "en": "The folder here is older: update it to version {version} with `ut package pull`.",
    },
    "package.advice_newer": {
        "it": "La cartella qui ha una versione che lo Studio non ha per questo progetto: forse "
        "viene da un altro progetto. Controlla con `ut status`.",
        "en": "The folder here has a version that the Studio does not have for this project: "
        "perhaps it comes from another project. Check with `ut status`.",
    },
    "package.advice_different": {
        "it": "La cartella qui non corrisponde alla versione {version} dello Studio: "
        "scaricala di nuovo con `ut package pull`.",
        "en": "The folder here does not match version {version} of the Studio: download it "
        "again with `ut package pull`.",
    },
    "package.advice_up_to_date": {
        "it": "La cartella qui è aggiornata. Dopo nuove approvazioni nello Studio pubblica una "
        "nuova versione con `ut package publish`.",
        "en": "The folder here is up to date. After new approvals in the Studio publish a new "
        "version with `ut package publish`.",
    },
    "package.advice_restore": {
        "it": "Per tornare alla versione pubblicata scarica di nuovo la cartella con "
        "`ut package pull`: le modifiche fatte a mano andranno perse. Per vedere il problema "
        "lancia `ut package verify`.",
        "en": "To go back to the published version download the folder again with "
        "`ut package pull`: the changes made by hand will be lost. To see the problem launch "
        "`ut package verify`.",
    },
    "package.advice_line_endings": {
        "it": "Scarica di nuovo la cartella con `ut package pull`: arriva con un file "
        ".gitattributes che impedisce a git di cambiare i fine riga.",
        "en": "Download the folder again with `ut package pull`: it comes with a .gitattributes "
        "file that stops git from changing the line endings.",
    },
    "package.published": {
        "it": "Pubblicata la versione {version} della cartella di conoscenza e scaricata in "
        "{path}. File: {files}.",
        "en": "Version {version} of the knowledge folder is published and downloaded into "
        "{path}. Files: {files}.",
    },
    "package.up_to_date": {
        "it": "Niente è cambiato dall'ultima versione: la cartella di conoscenza in {path} è "
        "già aggiornata (versione {version}).",
        "en": "Nothing changed since the last version: the knowledge folder in {path} is "
        "already up to date (version {version}).",
    },
    "package.unchanged_downloaded": {
        "it": "Niente è cambiato dall'ultima versione pubblicata: ho scaricato di nuovo la "
        "versione {version} in {path}. File: {files}.",
        "en": "Nothing changed since the last published version: version {version} was "
        "downloaded again into {path}. Files: {files}.",
    },
    "package.kept_published": {
        "it": "La versione {version} è pubblicata nello Studio, ma la cartella {path} è rimasta "
        "com'era. Scaricala quando vuoi con `ut package pull`.",
        "en": "Version {version} is published in the Studio, but the folder {path} was left as "
        "it was. Download it when you want with `ut package pull`.",
    },
    "package.pulled": {
        "it": "Scaricata la versione {version} della cartella di conoscenza in {path}. "
        "File: {files}.",
        "en": "Version {version} of the knowledge folder is downloaded into {path}. "
        "Files: {files}.",
    },
    "package.kept": {
        "it": "Non ho toccato la cartella {path}.",
        "en": "The folder {path} was left as it was.",
    },
    "package.changed_by_hand": {
        "it": "La cartella {path} non è più come l'ha pubblicata lo Studio: il primo file "
        "diverso è {file} ({code}). Se la sostituisco, le modifiche fatte a mano vanno perse.",
        "en": "The folder {path} is no longer as the Studio published it: the first file that "
        "differs is {file} ({code}). If it is replaced, the changes made by hand are lost.",
    },
    "package.replace_anyway": {
        "it": "Sostituisco comunque la cartella?",
        "en": "Replace the folder anyway?",
    },
    "package.verified": {
        "it": "La cartella di conoscenza {path} supera la verifica: versione {version} di "
        "«{project}», impronta {hash}. File: {files}.",
        "en": "The knowledge folder {path} passes the verification: version {version} of "
        '"{project}", content hash {hash}. Files: {files}.',
    },
    "package.verify_missing": {
        "it": "Non c'è una cartella di conoscenza in {path} ({code}). Scaricala con "
        "`ut package pull`.",
        "en": "There is no knowledge folder in {path} ({code}). Download it with "
        "`ut package pull`.",
    },
    "package.verify_tampered": {
        "it": "La cartella di conoscenza {path} non supera la verifica: il file {file} è stato "
        "cambiato o aggiunto dopo la pubblicazione ({code}). Per tornare alla versione "
        "pubblicata scaricala di nuovo con `ut package pull`; le modifiche fatte a mano "
        "andranno perse.",
        "en": "The knowledge folder {path} does not pass the verification: the file {file} was "
        "changed or added after the publication ({code}). To go back to the published version "
        "download it again with `ut package pull`; the changes made by hand will be lost.",
    },
    "package.verify_missing_file": {
        "it": "La cartella di conoscenza {path} non supera la verifica: manca il file {file} "
        "({code}). Scaricala di nuovo con `ut package pull`.",
        "en": "The knowledge folder {path} does not pass the verification: the file {file} is "
        "missing ({code}). Download it again with `ut package pull`.",
    },
    "package.verify_invalid": {
        "it": "La cartella di conoscenza {path} non supera la verifica: {file} non si legge "
        "come dovrebbe ({code}). Scaricala di nuovo con `ut package pull`.",
        "en": "The knowledge folder {path} does not pass the verification: {file} cannot be "
        "read as it should ({code}). Download it again with `ut package pull`.",
    },
    "package.verify_schema": {
        "it": "La cartella di conoscenza {path} usa un formato che questa versione di ut non "
        "conosce ({code}). Aggiorna ut, oppure scarica di nuovo la cartella con "
        "`ut package pull`.",
        "en": "The knowledge folder {path} uses a format that this version of ut does not know "
        "({code}). Update ut, or download the folder again with `ut package pull`.",
    },
    "package.verify_line_endings": {
        "it": "Il file {file} della cartella di conoscenza {path} ha i fine riga di Windows: "
        "probabilmente li ha cambiati git, che su Windows può convertirli quando salva o "
        "scarica i file. Il contenuto è lo stesso, ma l'impronta non torna più ({code}). "
        "Scarica di nuovo la cartella con `ut package pull`: arriva con un file .gitattributes "
        "che impedisce a git di cambiarli ancora.",
        "en": "The file {file} of the knowledge folder {path} has Windows line endings: git "
        "probably changed them, as it can convert them on Windows when it saves or downloads "
        "files. The content is the same, but the content hash no longer matches ({code}). "
        "Download the folder again with `ut package pull`: it comes with a .gitattributes file "
        "that stops git from changing them again.",
    },
    "package.verify_generic": {
        "it": "La cartella di conoscenza {path} non supera la verifica ({code}: {file}). "
        "Scaricala di nuovo con `ut package pull`.",
        "en": "The knowledge folder {path} does not pass the verification ({code}: {file}). "
        "Download it again with `ut package pull`.",
    },
    "package.history_heading": {
        "it": "Versioni della cartella di conoscenza di «{project}»",
        "en": 'Versions of the knowledge folder of "{project}"',
    },
    "package.history_none": {
        "it": "Lo Studio non ha ancora pubblicato versioni della cartella di conoscenza. "
        "Pubblicane una con `ut package publish`.",
        "en": "The Studio has not published any version of the knowledge folder yet. Publish "
        "one with `ut package publish`.",
    },
    "package.history_here": {"it": "{version} (qui)", "en": "{version} (here)"},
    "package.column_version": {"it": "Versione", "en": "Version"},
    "package.column_date": {"it": "Data", "en": "Date"},
    "package.column_hash": {"it": "Impronta", "en": "Content hash"},
    "package.column_files": {"it": "File", "en": "Files"},
    "package.import_offer_link": {
        "it": "Questa cartella ({folder}) non è collegata a un progetto. Dopo l'importazione "
        "la collego al nuovo progetto e metto la cartella di conoscenza in {path}?",
        "en": "This folder ({folder}) is not linked to a project. After the import, link it to "
        "the new project and put the knowledge folder in {path}?",
    },
    "package.import_cancelled": {
        "it": "Non ho importato niente: la cartella {path} è rimasta com'era.",
        "en": "Nothing was imported: the folder {path} was left as it was.",
    },
    "package.import_progress": {
        "it": "Importo nello Studio il progetto «{name}»",
        "en": 'Importing the project "{name}" into the Studio',
    },
    "package.imported": {
        "it": "Nello Studio c'è il nuovo progetto «{name}», creato dalla versione {version} "
        "della cartella di conoscenza di «{origin}».",
        "en": 'The Studio has the new project "{name}", created from version {version} of the '
        'knowledge folder of "{origin}".',
    },
    "package.import_approval": {
        "it": "Passi importati da approvare di nuovo prima di andare avanti: {count}.",
        "en": "Imported steps to approve again before going on: {count}.",
    },
    "package.import_kept_link": {
        "it": "Questa cartella resta collegata al progetto «{linked}» e non l'ho toccata: il "
        "nuovo progetto «{name}» è nello Studio, dove puoi aprirlo.",
        "en": 'This folder stays linked to the project "{linked}" and was not touched: the new '
        'project "{name}" is in the Studio, where you can open it.',
    },
    "package.import_not_linked": {
        "it": "Non ho collegato questa cartella: apri il progetto «{name}» nello Studio per "
        "approvare i passi importati.",
        "en": 'This folder was not linked: open the project "{name}" in the Studio to approve '
        "the imported steps.",
    },
    "package.import_linked": {
        "it": "Ho collegato questa cartella al nuovo progetto e ho messo la cartella di "
        "conoscenza in {path}. Approva i passi importati con `ut init`, poi il design con "
        "`ut design`.",
        "en": "This folder is now linked to the new project and the knowledge folder is in "
        "{path}. Approve the imported steps with `ut init`, then the design with `ut design`.",
    },
    "package.import_not_verified": {
        "it": "{source} non si può importare: non supera la verifica ({code}: {file}). Serve "
        "una cartella di conoscenza pubblicata dallo Studio, senza modifiche fatte a mano, "
        "oppure il suo file .zip. Nessuna richiesta è partita.",
        "en": "{source} cannot be imported: it does not pass the verification ({code}: "
        "{file}). It must be a knowledge folder published by the Studio, without changes made "
        "by hand, or its .zip file. No request was sent.",
    },
    "package.import_tampered": {
        "it": "{source} non si può importare: il file {file} è stato cambiato o aggiunto dopo "
        "la pubblicazione ({code}). Usa la cartella come l'ha pubblicata lo Studio, oppure il "
        "suo file .zip. Nessuna richiesta è partita.",
        "en": "{source} cannot be imported: the file {file} was changed or added after the "
        "publication ({code}). Use the folder as the Studio published it, or its .zip file. No "
        "request was sent.",
    },
    "package.import_missing_file": {
        "it": "{source} non si può importare: manca il file {file} ({code}). Nessuna richiesta "
        "è partita.",
        "en": "{source} cannot be imported: the file {file} is missing ({code}). No request "
        "was sent.",
    },
    "package.import_missing_folder": {
        "it": "{source} non è una cartella di conoscenza ({code}: {file}). Nessuna richiesta è "
        "partita.",
        "en": "{source} is not a knowledge folder ({code}: {file}). No request was sent.",
    },
    "package.import_not_archive": {
        "it": "{source} non è l'archivio zip di una cartella di conoscenza ({code}). Nessuna "
        "richiesta è partita.",
        "en": "{source} is not the zip archive of a knowledge folder ({code}). No request was "
        "sent.",
    },
    "package.import_line_endings": {
        "it": "{source} non si può importare: il file {file} ha i fine riga di Windows, forse "
        "cambiati da git ({code}). Usa il file .zip originale, oppure scarica di nuovo la "
        "cartella con `ut package pull` nel suo progetto. Nessuna richiesta è partita.",
        "en": "{source} cannot be imported: the file {file} has Windows line endings, perhaps "
        "changed by git ({code}). Use the original .zip file, or download the folder again "
        "with `ut package pull` in its project. No request was sent.",
    },
    "package.import_unpack_failed": {
        "it": "Ho collegato questa cartella al nuovo progetto, ma non ho potuto mettere la "
        "cartella di conoscenza in {path}: forse un suo file è aperto in un altro programma "
        "({file}). Non serve importare di nuovo: approva i passi importati con `ut init`, poi "
        "il design con `ut design`, e `ut package publish` scaricherà la cartella.",
        "en": "This folder is now linked to the new project, but the knowledge folder could "
        "not be put in {path}: perhaps one of its files is open in another program ({file}). "
        "No new import is needed: approve the imported steps with `ut init`, then the design "
        "with `ut design`, and `ut package publish` will download the folder.",
    },
    "package.errors.FOLDER_SWAP_FAILED": {
        "it": "Non ho potuto sostituire la cartella {folder}: il file {path} è forse aperto in "
        "un altro programma, per esempio un editor. La versione di prima è rimasta al suo "
        "posto: chiudi il programma e rilancia il comando.",
        "en": "The folder {folder} could not be replaced: the file {path} is perhaps open in "
        "another program, for example an editor. The previous version is still in place: close "
        "the program and launch the command again.",
    },
    "package.errors.FOLDER_SWAP_FAILED.FOLDER_IN_USE": {
        "it": "Non ho potuto sostituire la cartella {folder}: forse un suo file è aperto in un "
        "altro programma, per esempio un editor o una finestra delle cartelle. La versione di "
        "prima è rimasta al suo posto: chiudi il programma e rilancia il comando.",
        "en": "The folder {folder} could not be replaced: perhaps one of its files is open in "
        "another program, for example an editor or a folder window. The previous version is "
        "still in place: close the program and launch the command again.",
    },
    "package.errors.PACKAGE_VERSION_NOT_FOUND": {
        "it": "La versione {version} della cartella di conoscenza non esiste nello Studio: "
        "l'ultima è la {latest}. Guarda le versioni con `ut package history`.",
        "en": "Version {version} of the knowledge folder does not exist in the Studio: the "
        "latest is {latest}. See the versions with `ut package history`.",
    },
    "package.errors.KNOWLEDGE_PACKAGE_NOT_FOUND": {
        "it": "Questa versione della cartella di conoscenza non esiste nello Studio. Guarda le "
        "versioni con `ut package history`.",
        "en": "This version of the knowledge folder does not exist in the Studio. See the "
        "versions with `ut package history`.",
    },
    "package.errors.BRIEF_APPROVAL_REQUIRED": {
        "it": "La cartella di conoscenza non si può ancora pubblicare: il brief non è "
        "approvato. Approvalo con `ut init`, poi riprova.",
        "en": "The knowledge folder cannot be published yet: the brief is not approved. "
        "Approve it with `ut init`, then try again.",
    },
    "package.errors.TEAM_APPROVAL_REQUIRED": {
        "it": "La cartella di conoscenza non si può ancora pubblicare: la squadra non è "
        "approvata. Approvala con `ut init`, poi riprova.",
        "en": "The knowledge folder cannot be published yet: the team is not approved. "
        "Approve it with `ut init`, then try again.",
    },
    "package.errors.USER_MODELING_APPROVAL_REQUIRED": {
        "it": "La cartella di conoscenza non si può ancora pubblicare: i twin non sono "
        "confermati. Confermali con `ut init`, poi riprova.",
        "en": "The knowledge folder cannot be published yet: the twins are not confirmed. "
        "Confirm them with `ut init`, then try again.",
    },
    "package.errors.REQUIREMENTS_APPROVAL_REQUIRED": {
        "it": "La cartella di conoscenza non si può ancora pubblicare: i requisiti non sono "
        "approvati. Approvali con `ut init`, poi riprova.",
        "en": "The knowledge folder cannot be published yet: the requirements are not "
        "approved. Approve them with `ut init`, then try again.",
    },
    "package.errors.DESIGN_APPROVAL_REQUIRED": {
        "it": "La cartella di conoscenza non si può ancora pubblicare: il design non è "
        "approvato. Sceglilo e approvalo con `ut design`, poi riprova.",
        "en": "The knowledge folder cannot be published yet: the design is not approved. "
        "Choose it and approve it with `ut design`, then try again.",
    },
    "package.errors.TEAM_OUTDATED": {
        "it": "La cartella di conoscenza non si può pubblicare: la squadra approvata non "
        "corrisponde più al brief attuale. Approvala di nuovo con `ut init`, poi riprova.",
        "en": "The knowledge folder cannot be published: the approved team no longer matches "
        "the current brief. Approve it again with `ut init`, then try again.",
    },
    "package.errors.USER_TWINS_OUTDATED": {
        "it": "La cartella di conoscenza non si può pubblicare: i twin confermati non "
        "corrispondono più al brief o alla squadra attuali. Confermali di nuovo con "
        "`ut init`, poi riprova.",
        "en": "The knowledge folder cannot be published: the confirmed twins no longer match "
        "the current brief or team. Confirm them again with `ut init`, then try again.",
    },
    "package.errors.REQUIREMENTS_OUTDATED": {
        "it": "La cartella di conoscenza non si può pubblicare: i requisiti approvati non "
        "corrispondono più ai passi prima di loro. Approvali di nuovo con `ut init`, poi "
        "riprova.",
        "en": "The knowledge folder cannot be published: the approved requirements no longer "
        "match the steps before them. Approve them again with `ut init`, then try again.",
    },
    "package.errors.DESIGN_OUTDATED": {
        "it": "La cartella di conoscenza non si può pubblicare: il design approvato non "
        "corrisponde più ai requisiti, alla squadra o ai twin attuali. Approvalo di nuovo con "
        "`ut design`, poi riprova.",
        "en": "The knowledge folder cannot be published: the approved design no longer "
        "matches the current requirements, team or twins. Approve it again with `ut design`, "
        "then try again.",
    },
    "package.errors.PROJECT_NOT_FOUND": {
        "it": "Lo Studio non trova questo progetto per il tuo account, oppure il progetto non "
        "ha ancora un brief. Se è nuovo, comincia con `ut init`.",
        "en": "The Studio does not find this project for your account, or the project has no "
        "brief yet. If it is new, start with `ut init`.",
    },
    "package.errors.KNOWLEDGE_PACKAGE_SERVICE_UNAVAILABLE": {
        "it": "Lo Studio non può preparare la cartella di conoscenza in questo momento. "
        "Riprova più tardi.",
        "en": "The Studio cannot prepare the knowledge folder right now. Try again later.",
    },
    "package.errors.FOLDER_ARCHIVE_TOO_LARGE": {
        "it": "Lo Studio ha rifiutato l'archivio perché è troppo grande: il limite è 16 MB "
        "({code}).",
        "en": "The Studio refused the archive because it is too large: the limit is 16 MB "
        "({code}).",
    },
    "package.errors.PROJECT_IMPORT_SERVICE_UNAVAILABLE": {
        "it": "Lo Studio non può importare progetti in questo momento. Riprova più tardi.",
        "en": "The Studio cannot import projects right now. Try again later.",
    },
    "package.errors.PROJECT_IMPORT_REJECTED": {
        "it": "Lo Studio non è riuscito a salvare il progetto importato. Riprova più tardi; se "
        "succede ancora, avvisa chi gestisce lo Studio.",
        "en": "The Studio could not save the imported project. Try again later; if it happens "
        "again, tell whoever runs the Studio.",
    },
    "package.errors.PROJECT_NAME_INVALID": {
        "it": "Il nome del progetto non è valido: scrivilo con al massimo 120 caratteri.",
        "en": "The name of the project is not valid: write it with at most 120 characters.",
    },
    "package.errors.IMPORT_SOURCE_MISSING": {
        "it": "Non trovo {path}. Indica una cartella di conoscenza, per esempio orchestwin, "
        "oppure il suo file .zip.",
        "en": "{path} cannot be found. Give a knowledge folder, for example orchestwin, or its "
        ".zip file.",
    },
    "package.errors.IMPORT_SOURCE_UNREADABLE": {
        "it": "Non riesco a leggere {path}: controlla di poterlo aprire e che non sia bloccato "
        "da un altro programma.",
        "en": "{path} cannot be read: check that you can open it and that no other program "
        "locks it.",
    },
    "package.errors.ARCHIVE_TOO_LARGE": {
        "it": "{source} occupa {size} MB: lo Studio accetta al massimo {limit} MB. Nessuna "
        "richiesta è partita.",
        "en": "{source} takes {size} MB: the Studio accepts at most {limit} MB. No request was "
        "sent.",
    },
    "package.errors.ARCHIVE_TOO_MANY_ENTRIES": {
        "it": "{source} contiene troppi file per lo Studio (file: {count}; al massimo "
        "{limit}). Nessuna richiesta è partita.",
        "en": "{source} contains too many files for the Studio (files: {count}; at most "
        "{limit}). No request was sent.",
    },
}
