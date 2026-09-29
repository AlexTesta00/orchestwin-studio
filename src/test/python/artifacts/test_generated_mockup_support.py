from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from orchestwin.artifacts.generated_mockups import GeneratedMockup, create_generated_mockup
from orchestwin.artifacts.prototypes import PrototypeScreenState
from orchestwin.artifacts.visual_catalog import (
    NEUTRAL_VISUAL_CHOICES,
    ColorMode,
    VisualChoices,
    resolve_visual_tokens,
)

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "generated_mockups"
DASHBOARD = "library-loans"
GUIDED_FORM = "library-registration"
FIXTURES = (DASHBOARD, GUIDED_FORM)

ALTERNATIVE_ID = UUID("5b7e0d0a-2f4c-4d7b-9a1e-3c6f8e2b1d10")
LIGHT_CHOICES = NEUTRAL_VISUAL_CHOICES
DARK_CHOICES = replace(NEUTRAL_VISUAL_CHOICES, color_mode=ColorMode.DARK)
HIGH_CONTRAST_CHOICES = replace(NEUTRAL_VISUAL_CHOICES, color_mode=ColorMode.HIGH_CONTRAST_LIGHT)
LIGHT_TOKENS = resolve_visual_tokens(LIGHT_CHOICES)
DARK_TOKENS = resolve_visual_tokens(DARK_CHOICES)
HIGH_CONTRAST_TOKENS = resolve_visual_tokens(HIGH_CONTRAST_CHOICES)
TOKEN_NAMES = frozenset(LIGHT_TOKENS)
BASE_CODES = frozenset({"REQ-001", "REQ-002"})

HTML_COMMENT_OPEN = "<!" + "--"
HTML_COMMENT_CLOSE = "--" + ">"
CSS_COMMENT_OPEN = "/" + "*"
CSS_COMMENT_CLOSE = "*" + "/"

BASE_FIRST = (
    '<main data-req="REQ-001">'
    "<h1>Prestiti della settimana</h1>"
    "<p>Controlla i prestiti aperti della sede centrale e invia un promemoria ai lettori "
    "che non hanno ancora restituito i volumi.</p>"
    '<form aria-label="Filtri">'
    '<label for="stato">Stato del prestito</label>'
    '<select id="stato" name="stato"><option>Tutti</option><option>In ritardo</option></select>'
    "</form>"
    "<table>"
    '<thead><tr><th scope="col">Lettore</th><th scope="col">Titolo</th>'
    '<th scope="col">Scadenza</th></tr></thead>'
    "<tbody>"
    "<tr><td>Anna Riva</td><td>Le città invisibili</td><td>3 ottobre</td></tr>"
    "<tr><td>Marco Pini</td><td>Il barone rampante</td><td>5 ottobre</td></tr>"
    "<tr><td>Sara Galli</td><td>Lessico famigliare</td><td>7 ottobre</td></tr>"
    "</tbody>"
    "</table>"
    '<a href="#SCR-002">Invia promemoria</a>'
    "</main>"
)
BASE_SECOND = (
    '<main data-req="REQ-002">'
    "<h1>Promemoria inviato</h1>"
    '<p role="status">Il promemoria è stato inviato a tre lettori con prestiti in scadenza '
    "nella settimana corrente.</p>"
    "<h2>Prossimi passi</h2>"
    "<ul><li>Verifica le restituzioni di venerdì mattina.</li>"
    "<li>Aggiorna il registro dopo ogni restituzione.</li></ul>"
    "<p>Puoi tornare al registro per controllare gli altri prestiti in corso.</p>"
    '<a href="#SCR-001">Torna al registro</a>'
    "</main>"
)
BASE_STYLES = (
    "main{max-width:960px;margin:0 auto;padding:var(--vl-space)}"
    "@media (max-width:600px){main{padding:var(--vl-gap)}}"
)
BASE_TITLES = (
    "Prestiti della settimana",
    "Promemoria inviato",
    "Dettaglio del prestito",
    "Storico dei prestiti",
    "Impostazioni del registro",
    "Lettori sospesi",
    "Statistiche mensili",
    "Aiuto del registro",
)
BASE_STATES = (PrototypeScreenState.DEFAULT, PrototypeScreenState.SUCCESS)


def screen_payloads(
    markups: Iterable[str],
    *,
    states: Iterable[PrototypeScreenState] = BASE_STATES,
    titles: Iterable[str] = BASE_TITLES,
) -> list[dict[str, object]]:
    chosen_states = list(states)
    chosen_titles = list(titles)
    return [
        {
            "code": f"SCR-{index:03d}",
            "title": chosen_titles[index - 1],
            "state": chosen_states[index - 1]
            if index - 1 < len(chosen_states)
            else PrototypeScreenState.DEFAULT,
            "markup": markup,
        }
        for index, markup in enumerate(markups, start=1)
    ]


def build(
    first: str = BASE_FIRST,
    second: str = BASE_SECOND,
    *,
    extra: Iterable[str] = (),
    styles: str = BASE_STYLES,
    states: Iterable[PrototypeScreenState] = BASE_STATES,
    title: str = "Registro dei prestiti",
    token_names: Iterable[str] = TOKEN_NAMES,
) -> GeneratedMockup:
    return create_generated_mockup(
        design_alternative_id=ALTERNATIVE_ID,
        title=title,
        styles=styles,
        screens=screen_payloads((first, second, *extra), states=states),
        token_names=token_names,
    )


def with_first(snippet: str, **options: object) -> GeneratedMockup:
    return build(BASE_FIRST.replace("</main>", snippet + "</main>"), **options)


def fixture_data(name: str) -> dict[str, object]:
    data = json.loads((FIXTURE_DIRECTORY / f"{name}.json").read_text(encoding="utf-8"))
    screens = [
        {
            "code": item["code"],
            "title": item["title"],
            "state": PrototypeScreenState(item["state"]),
            "markup": (FIXTURE_DIRECTORY / item["markup"]).read_text(encoding="utf-8"),
        }
        for item in data["screens"]
    ]
    return {
        "design_alternative_id": UUID(data["design_alternative_id"]),
        "title": data["title"],
        "styles": "\n".join(data["styles"]),
        "screens": screens,
        "requirement_codes": frozenset(data["requirement_codes"]),
        "choices": VisualChoices.from_snapshot(data["visual_choices"]),
    }


def fixture_tokens(name: str) -> dict[str, str]:
    choices = fixture_data(name)["choices"]
    assert isinstance(choices, VisualChoices)
    return resolve_visual_tokens(choices)


def fixture_codes(name: str) -> frozenset[str]:
    codes = fixture_data(name)["requirement_codes"]
    assert isinstance(codes, frozenset)
    return codes


def fixture_mockup(name: str) -> GeneratedMockup:
    data = fixture_data(name)
    return create_generated_mockup(
        design_alternative_id=data["design_alternative_id"],
        title=data["title"],
        styles=data["styles"],
        screens=data["screens"],
        token_names=frozenset(fixture_tokens(name)),
    )


def requirement_ids(codes: Iterable[str]) -> dict[str, UUID]:
    return {code: uuid5(NAMESPACE_URL, f"orchestwin:requirement:{code}") for code in codes}
