from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "jobs.stage_generating": {"it": "il modello sta lavorando", "en": "the model is working"},
    "jobs.stage_validating": {
        "it": "lo Studio controlla il risultato",
        "en": "the Studio is checking the result",
    },
    "jobs.stage_retrying": {"it": "nuovo tentativo", "en": "trying again"},
    "jobs.stage_waiting": {"it": "in attesa", "en": "waiting"},
    "jobs.attempt": {"it": "tentativo {attempt}", "en": "attempt {attempt}"},
}
