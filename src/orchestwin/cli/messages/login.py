from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "login.help": {
        "it": "Accedi a uno Studio di OrchesTwin",
        "en": "Sign in to an OrchesTwin Studio",
    },
    "login.option_studio": {
        "it": "indirizzo dello Studio, per esempio http://127.0.0.1:8000",
        "en": "address of the Studio, for example http://127.0.0.1:8000",
    },
    "login.option_email": {"it": "e-mail del tuo account", "en": "e-mail of your account"},
    "login.option_password_stdin": {
        "it": "legge la password dalla prima riga dello standard input",
        "en": "read the password from the first line of the standard input",
    },
    "login.email": {"it": "E-mail:", "en": "E-mail:"},
    "login.password": {"it": "Password:", "en": "Password:"},
    "login.password_empty": {
        "it": "La password è vuota: non ho inviato nulla allo Studio.",
        "en": "The password is empty: nothing was sent to the Studio.",
    },
    "login.refused": {
        "it": "Accesso rifiutato: l'e-mail o la password non sono corrette.",
        "en": "Sign-in refused: the e-mail or the password is not correct.",
    },
    "login.too_many_attempts": {
        "it": "Troppi tentativi di accesso: aspetta qualche minuto e riprova.",
        "en": "Too many sign-in attempts: wait a few minutes and try again.",
    },
    "login.done": {
        "it": "Accesso eseguito come {email} sullo Studio {studio}.",
        "en": "Signed in as {email} to the Studio {studio}.",
    },
    "login.other_studio": {
        "it": "Questa cartella è collegata a un progetto dello Studio {linked}: i comandi "
        "lanciati qui usano quello Studio.",
        "en": "This folder is linked to a project of the Studio {linked}: the commands "
        "launched here use that Studio.",
    },
    "login.local_mode": {
        "it": "Lo Studio {studio} è locale e non chiede l'accesso: i comandi funzionano senza "
        "`ut login`.",
        "en": "The Studio {studio} is local and needs no sign-in: the commands work without "
        "`ut login`.",
    },
}
