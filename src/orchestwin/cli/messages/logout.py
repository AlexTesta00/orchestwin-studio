from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "logout.help": {
        "it": "Esci dallo Studio e togli l'accesso da questo computer",
        "en": "Sign out of the Studio and remove the sign-in from this computer",
    },
    "logout.option_studio": {
        "it": "indirizzo dello Studio da cui uscire",
        "en": "address of the Studio to sign out of",
    },
    "logout.nobody": {
        "it": "Nessuno ha eseguito l'accesso allo Studio {studio} da questo computer.",
        "en": "Nobody is signed in to the Studio {studio} from this computer.",
    },
    "logout.done": {
        "it": "Uscita eseguita dallo Studio {studio}.",
        "en": "Signed out of the Studio {studio}.",
    },
    "logout.offline": {
        "it": "Lo Studio {studio} non risponde: ho tolto comunque l'accesso da questo computer.",
        "en": "The Studio {studio} does not answer: the sign-in was removed from this "
        "computer all the same.",
    },
}
