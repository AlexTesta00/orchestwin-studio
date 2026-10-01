from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "costs.estimate": {
        "it": "Stima: {amount} USD, circa {minutes}. Credito rimasto nello Studio: "
        "{remaining} USD.",
        "en": "Estimate: {amount} USD, about {minutes}. Credit left in the Studio: "
        "{remaining} USD.",
    },
    "costs.estimate_no_credit": {
        "it": "Stima: {amount} USD, circa {minutes}.",
        "en": "Estimate: {amount} USD, about {minutes}.",
    },
    "costs.subscription": {
        "it": "Questa generazione usa l'abbonamento di Claude: non spende credito. Tempo stimato: "
        "circa {minutes}.",
        "en": "This generation runs on the Claude subscription: it spends no credit. Estimated "
        "time: about {minutes}.",
    },
    "costs.over_credit": {
        "it": "La stima supera il credito rimasto: lo Studio potrebbe rifiutare la generazione.",
        "en": "The estimate is above the credit left: the Studio may refuse the generation.",
    },
    "costs.confirm": {
        "it": "Vado avanti con questa spesa?",
        "en": "Go ahead with this spending?",
    },
    "costs.assumed": {
        "it": "Spesa confermata con --yes.",
        "en": "Spending confirmed with --yes.",
    },
}
