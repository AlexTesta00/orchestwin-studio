from __future__ import annotations

from collections.abc import Mapping


def show_limits(console, limits):
    from orchestwin.workflow_inputs import PROVIDED_PROTOTYPE_LIMIT_MESSAGES

    messages = PROVIDED_PROTOTYPE_LIMIT_MESSAGES.get(
        console.language, PROVIDED_PROTOTYPE_LIMIT_MESSAGES["en"]
    )
    for code in limits:
        if code in messages:
            console.write(f"{messages[code]} ({code})")


def show_records(console, document):
    if not isinstance(document, Mapping):
        return
    for decision in document.get("decisions", []):
        label = (
            "Manca, dichiarato da te" if console.language == "it" else "Missing, declared by you"
        )
        if decision["action"] == "RESOLVE_MISSING":
            label = "Lacuna risolta da te" if console.language == "it" else "Gap resolved by you"
        console.write(f"{decision['target']}: {label} · {decision['reason']}")
    for prototype in document.get("prototypes", []):
        label = "Prototipo fornito" if console.language == "it" else "Supplied prototype"
        console.write(
            f"{label} {prototype['code']} · {prototype['title']} · v{prototype['version_number']}"
        )
        if prototype.get("declared_origin"):
            label = "Origine dichiarata" if console.language == "it" else "Declared origin"
            console.write(f"{label}: {prototype['declared_origin']}")
    show_limits(console, document.get("limits", []))
