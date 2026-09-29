from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import twin_chat
from orchestwin.cli.http import Reply, UrlTransport, unreachable
from orchestwin.cli.project import ProjectFolder

from .support.fake_studio import FakeProject, FakeStudio
from .support.folders import valid_archive
from .support.terminal import (
    PROJECT_ID,
    START,
    TEST_PASSWORD,
    Run,
    command_context,
    link_folder,
    run_ut,
    store_session,
    terminal,
)
from .support.transports import API, NoNetwork, ScriptedTransport

EMAIL = "owner@example.com"
WIDE = {"COLUMNS": "200"}
TURNS = "/projects/{project_id}/user-twins/{twin_id}/conversation/turns"
MODEL_FAILURE = {"detail": {"code": "INVALID_TWIN_CHAT_OUTPUT", "stage": "MODEL_PROPOSAL"}}
BASE = f"{API}/projects/{PROJECT_ID}"
ACCENTED = str.maketrans({"A": "À", "E": "È", "I": "Ì", "O": "Ò", "U": "Ù"})
LABELS = {
    "role": "Role",
    "age_range": "Age range",
    "expertise": "Expertise",
    "goals": "Goals",
    "recurring_tasks": "Recurring tasks",
    "context_of_use": "Context of use",
    "information_needs": "Information needs",
    "decision_criteria": "Decision criteria",
    "preferred_vocabulary": "Preferred vocabulary",
    "frustrations": "Frustrations",
    "pain_points": "Pain points",
    "trust_concerns": "Trust concerns",
    "accessibility_needs": "Accessibility needs",
    "operational_constraints": "Operational constraints",
    "technical_literacy": "Technical literacy",
    "risk_sensitivity": "Risk sensitivity",
    "assumptions": "Assumptions",
}
SECTIONS = (
    ("Goals", ("goals",)),
    ("What holds them back", ("frustrations", "pain_points")),
    ("Context of use", ("context_of_use",)),
)
SIMULATED = {
    "it": "Le risposte dei twin sono simulate dal modello: sono ipotesi da valutare, non "
    "opinioni di persone reali.",
    "en": "The answers of the twins are simulated by the model: they are hypotheses to weigh, "
    "not opinions of real people.",
}
HINT = {
    "it": "Scrivi una domanda e premi Invio. Per finire scrivi /esci. Ogni risposta è una "
    "piccola spesa del modello.",
    "en": "Write a question and press Enter. To finish write /quit. Each answer is a small "
    "spending of the model.",
}
END = {
    "it": "Conversazione finita: domande e risposte restano salvate nello Studio.",
    "en": "Conversation ended: questions and answers stay saved in the Studio.",
}


class Offline:
    def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> Reply:
        raise unreachable(url, sent=False)


def sign_in(tmp_path: Path, studio: FakeStudio) -> None:
    studio.add_account(EMAIL, TEST_PASSWORD)
    run = run_ut(
        ["login", "--studio", studio.address, "--email", EMAIL, "--password-stdin"],
        tmp_path,
        transport=UrlTransport(),
        answers=[TEST_PASSWORD],
    )
    assert run.status == 0, run.errors


def seeded(tmp_path: Path, studio: FakeStudio, *, through: str = "design") -> FakeProject:
    sign_in(tmp_path, studio)
    project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through=through)
    link_folder(
        tmp_path / "project", project_id=project.id, name=project.name, studio=studio.address
    )
    return project


def ut(tmp_path: Path, *arguments: str, answers: Sequence[str] = ()) -> Run:
    return run_ut(
        list(arguments), tmp_path, transport=UrlTransport(), answers=answers, variables=WIDE
    )


def versions(project: FakeProject) -> list[Mapping[str, object]]:
    snapshot = project.current("twins")
    assert snapshot is not None
    return list(snapshot["snapshot"]["twin_versions"])


def twin_names(project: FakeProject) -> list[str]:
    return [str(version["profile"]["name"]) for version in versions(project)]


def observed(version: Mapping[str, object], field: str) -> list[str]:
    for item in version["profile"]["observations"]:
        if item["observation_key"] != f"user_twin.{field}":
            continue
        value = item["value"]
        if value["kind"] == "TEXT":
            return [value["text"]]
        if value["kind"] == "ITEMS":
            return list(value["items"])
    return []


def role_of(version: Mapping[str, object]) -> str | None:
    found = observed(version, "role")
    return found[0] if found else None


def listed(project: FakeProject) -> list[list[str]]:
    rows = []
    for number, version in enumerate(versions(project), start=1):
        goals = observed(version, "goals")
        rows.append(
            [
                str(number),
                str(version["profile"]["name"]),
                role_of(version) or "-",
                goals[0] if goals else "-",
            ]
        )
    return rows


def choice(version: Mapping[str, object]) -> str:
    name = str(version["profile"]["name"])
    role = role_of(version)
    return name if role is None or role == name else f"{name} - {role}"


def plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def beginning(name: str, names: Sequence[str]) -> str:
    words = name.split()
    for count in range(1, len(words) + 1):
        start = " ".join(words[:count])
        if [other for other in names if plain(other).startswith(plain(start))] == [name]:
            return start
    return name


def value_text(observation: Mapping[str, object]) -> str:
    value = observation["value"]
    if value["kind"] == "TEXT":
        return str(value["text"])
    if value["kind"] == "ITEMS":
        return "; ".join(value["items"])
    if value["kind"] == "ABSTAINED":
        reason = value["reason"]
        return f"the model gave no answer ({reason})" if reason else "the model gave no answer"
    return "not known"


def observation_items(output: str) -> list[str]:
    lines = output.splitlines()
    items: list[str] = []
    for line in lines[lines.index("Every observation, with its origin") + 1 :]:
        if line.startswith("- "):
            items.append(line)
        elif line.startswith("  ") and items:
            items[-1] = f"{items[-1]} {line.strip()}"
    return items


def recorded_replies(
    tmp_path: Path, project: FakeProject, version: Mapping[str, object]
) -> list[str]:
    client = command_context(terminal(tmp_path, transport=UrlTransport()).environment).client()
    found = twin_chat.conversation(client, project.id, str(version["twin_id"]))
    return [twin_chat.turn_reply(turn) for turn in twin_chat.turns(found, str(version["id"]))]


def table(output: str) -> list[list[str]]:
    lines = output.splitlines()
    rule = next(index for index, line in enumerate(lines) if re.fullmatch(r"[- ]+", line))
    rows = [re.split(r"\s{2,}", lines[rule - 1].strip())]
    for line in lines[rule + 1 :]:
        if not line.strip():
            break
        rows.append(re.split(r"\s{2,}", line.strip()))
    return rows


def value(
    kind: str, *, text: str | None = None, items: Sequence[str] = (), reason: str | None = None
) -> dict[str, object]:
    return {"kind": kind, "text": text, "items": list(items), "reason": reason}


def observation(
    key: str,
    shown: dict[str, object],
    *,
    status: str = "MODEL_INFERRED",
    validation: str = "REQUIRED",
    sources: Sequence[str] = (),
    rationale: str | None = None,
) -> dict[str, object]:
    return {
        "observation_key": f"user_twin.{key}",
        "value": shown,
        "epistemic_status": status,
        "confidence": 0.6,
        "provenance": [
            {
                "source_kind": kind,
                "source_id": f"source-{index}",
                "source_version": 1,
                "content_hash": None,
                "locator": key,
                "summary": None,
            }
            for index, kind in enumerate(sources, start=1)
        ],
        "human_validation": validation,
        "rationale": rationale,
    }


RICH_TWIN = {
    "id": "version-12",
    "twin_id": "twin-1",
    "version_number": 2,
    "profile": {
        "name": "Marta Twin",
        "observations": [
            observation(
                "role", value("TEXT", text="Cameriera del turno serale"), sources=["PROJECT_BRIEF"]
            ),
            observation(
                "goals",
                value("ITEMS", items=["Chiudere il conto in fretta", "Evitare errori di calcolo"]),
                sources=["PROJECT_BRIEF", "MODEL_OUTPUT", "PROJECT_BRIEF"],
                rationale="Dal brief del progetto.",
            ),
            observation(
                "frustrations",
                value("ITEMS", items=["Conti a mente sbagliati"]),
                sources=["MODEL_OUTPUT"],
            ),
            observation(
                "pain_points",
                value("ITEMS", items=["Attesa alla cassa"]),
                status="USER_PROVIDED",
                validation="NOT_REQUIRED",
                sources=["OWNER_INPUT"],
            ),
            observation(
                "context_of_use",
                value("TEXT", text="Al tavolo, dal telefono, con poca luce."),
                status="HUMAN_VALIDATED",
                validation="NOT_REQUIRED",
                sources=["HUMAN_REVIEW"],
            ),
            observation("trust_concerns", value("UNKNOWN"), status="UNSUPPORTED_ASSUMPTION"),
            observation(
                "accessibility_needs",
                value("ABSTAINED", reason="Il brief tace."),
                sources=["SYSTEM_ARTIFACT", "MODEL_OUTPUT"],
                rationale="Nessuna prova.",
            ),
            observation(
                "favourite_colour",
                value("TEXT", text="Blu"),
                status="EMPIRICALLY_SUPPORTED",
                sources=["EMPIRICAL_RESEARCH", "NEW_SOURCE"],
            ),
            observation(
                "mood", value("TEXT", text="Calma"), status="NEW_STATUS", validation="NOT_REQUIRED"
            ),
        ],
    },
}
ABSTAINING_TWIN = {
    "id": "version-13",
    "twin_id": "twin-2",
    "version_number": 1,
    "profile": {
        "name": "Cassiere del bar Twin",
        "observations": [
            observation("role", value("TEXT", text="Cassiere del bar"), sources=["PROJECT_BRIEF"]),
            observation(
                "goals",
                value("ABSTAINED", reason="The brief gives no goal."),
                sources=["MODEL_OUTPUT"],
            ),
        ],
    },
}


def scripted_twins(twins: Sequence[Mapping[str, object]], *, runs: int) -> ScriptedTransport:
    transport = ScriptedTransport()
    for _ in range(runs):
        transport.expect(
            "GET",
            f"{BASE}/user-modeling/readiness",
            body={"snapshot_exists": True, "approved_current_snapshot": True},
        )
        transport.expect(
            "GET",
            f"{BASE}/user-modeling/snapshots/current",
            body={"id": "snapshot-2", "snapshot": {"twin_versions": list(twins)}},
        )
    return transport


def test_the_list_in_italian_follows_the_order_of_the_studio(tmp_path: Path) -> None:
    with FakeStudio(language="it", twins=3) as studio:
        project = seeded(tmp_path, studio)
        run = ut(tmp_path, "--lang", "it", "twins", "list")
        rows = listed(project)
        assert studio.errors == []

    assert len(rows) == 3
    assert (run.status, run.errors) == (0, "")
    assert run.output.splitlines()[:2] == ["User Twin di «Calcolo mancia»", "=" * 29]
    assert table(run.output) == [["N.", "Nome", "Ruolo", "Che cosa vuole"], *rows]
    assert run.output.splitlines()[-2:] == [
        "Per vedere un twin per intero: `ut twins show 1`.",
        "Per fargli una domanda: `ut twins ask 1`.",
    ]


def test_without_an_action_the_twins_are_listed_in_english(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=2) as studio:
        project = seeded(tmp_path, studio)
        run = ut(tmp_path, "twins")
        rows = listed(project)

    assert run.status == 0
    assert run.output.splitlines()[0] == 'User Twins of "Calcolo mancia"'
    assert table(run.output) == [["No.", "Name", "Role", "What they want"], *rows]
    assert "To ask it a question: `ut twins ask 1`." in run.output


def test_show_prints_the_twin_of_the_studio_with_every_observation(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=2) as studio:
        project = seeded(tmp_path, studio)
        run = ut(tmp_path, "twins", "show", "2")
        version = versions(project)[1]

    name = str(version["profile"]["name"])
    role = role_of(version)
    assert role is not None
    sections: list[str] = []
    for title, fields in SECTIONS:
        values = [item for field in fields for item in observed(version, field)]
        if values:
            sections.extend(["", title, *(f"- {item}" for item in values)])
    head = [name, "=" * len(name), *([] if role == name else [f"Role: {role}"]), *sections]
    lines = run.output.splitlines()
    assert run.status == 0
    assert lines[: len(head) + 2] == [*head, "", "Every observation, with its origin"]
    observations = version["profile"]["observations"]
    items = observation_items(run.output)
    assert len(items) == len(observations)
    for item, found in zip(items, observations, strict=True):
        label = LABELS[str(found["observation_key"]).removeprefix("user_twin.")]
        assert item.startswith(f"- {label}: {value_text(found)} (origin: ")


def test_show_prints_every_part_of_a_twin_and_the_origin_of_each_observation(
    tmp_path: Path,
) -> None:
    transport = scripted_twins([RICH_TWIN, ABSTAINING_TWIN], runs=3)
    store_session(tmp_path)
    link_folder(tmp_path / "project")

    english = run_ut(["twins", "show", "marta"], tmp_path, transport=transport, variables=WIDE)
    italian = run_ut(
        ["--lang", "it", "twins", "show", "1"], tmp_path, transport=transport, variables=WIDE
    )
    both = run_ut(["twins"], tmp_path, transport=transport, variables=WIDE)

    assert (english.status, english.errors) == (0, "")
    assert english.output.splitlines() == [
        "Marta Twin",
        "==========",
        "Role: Cameriera del turno serale",
        "",
        "Goals",
        "- Chiudere il conto in fretta",
        "- Evitare errori di calcolo",
        "",
        "What holds them back",
        "- Conti a mente sbagliati",
        "- Attesa alla cassa",
        "",
        "Context of use",
        "- Al tavolo, dal telefono, con poca luce.",
        "",
        "Every observation, with its origin",
        "- Role: Cameriera del turno serale (origin: model suggestion, to be checked; sources: "
        "project brief)",
        "- Goals: Chiudere il conto in fretta; Evitare errori di calcolo (origin: model "
        "suggestion, to be checked; sources: project brief, model proposal). Why: Dal brief del "
        "progetto.",
        "- Frustrations: Conti a mente sbagliati (origin: model suggestion, to be checked; "
        "sources: model proposal)",
        "- Pain points: Attesa alla cassa (origin: provided by a person; sources: your input)",
        "- Context of use: Al tavolo, dal telefono, con poca luce. (origin: reviewed by a person; "
        "sources: review by a person)",
        "- Trust concerns: not known (origin: unverified assumption, to be checked)",
        "- Accessibility needs: the model gave no answer (Il brief tace.) (origin: model "
        "suggestion, to be checked; sources: document of the Studio, model proposal). Why: "
        "Nessuna prova.",
        "- Favourite colour: Blu (origin: supported by real observations, to be checked; "
        "sources: research with real users, NEW_SOURCE)",
        "- Mood: Calma (origin: NEW_STATUS)",
    ]
    assert italian.status == 0
    assert italian.output.splitlines() == [
        "Marta Twin",
        "==========",
        "Ruolo: Cameriera del turno serale",
        "",
        "Obiettivi",
        "- Chiudere il conto in fretta",
        "- Evitare errori di calcolo",
        "",
        "Che cosa è di ostacolo",
        "- Conti a mente sbagliati",
        "- Attesa alla cassa",
        "",
        "Contesto d'uso",
        "- Al tavolo, dal telefono, con poca luce.",
        "",
        "Tutte le osservazioni, con la loro origine",
        "- Ruolo: Cameriera del turno serale (origine: ipotesi del modello, da verificare; fonti: "
        "brief del progetto)",
        "- Obiettivi: Chiudere il conto in fretta; Evitare errori di calcolo (origine: ipotesi "
        "del modello, da verificare; fonti: brief del progetto, proposta del modello). Perché: "
        "Dal brief del progetto.",
        "- Frustrazioni: Conti a mente sbagliati (origine: ipotesi del modello, da verificare; "
        "fonti: proposta del modello)",
        "- Difficoltà: Attesa alla cassa (origine: informazione data da una persona; fonti: "
        "indicazioni tue)",
        "- Contesto d'uso: Al tavolo, dal telefono, con poca luce. (origine: verificato da una "
        "persona; fonti: revisione di una persona)",
        "- Preoccupazioni sulla fiducia: non noto (origine: ipotesi non confermata, da verificare)",
        "- Esigenze di accessibilità: il modello non si è pronunciato (Il brief tace.) (origine: "
        "ipotesi del modello, da verificare; fonti: documento dello Studio, proposta del "
        "modello). Perché: Nessuna prova.",
        "- Favourite colour: Blu (origine: supportato da osservazioni reali, da verificare; "
        "fonti: ricerca con utenti reali, NEW_SOURCE)",
        "- Mood: Calma (origine: NEW_STATUS)",
    ]
    assert table(both.output) == [
        ["No.", "Name", "Role", "What they want"],
        ["1", "Marta Twin", "Cameriera del turno serale", "Chiudere il conto in fretta"],
        ["2", "Cassiere del bar Twin", "Cassiere del bar", "-"],
    ]
    transport.assert_done()


def test_a_twin_is_found_by_the_beginning_of_its_name_without_accents(tmp_path: Path) -> None:
    with FakeStudio(language="it", twins=2) as studio:
        project = seeded(tmp_path, studio)
        names = twin_names(project)
        typed = beginning(names[0], names).upper().translate(ACCENTED)
        run = ut(tmp_path, "--lang", "it", "twins", "show", typed)
        role = role_of(versions(project)[0])

    assert typed != names[0][: len(typed)]
    assert set(typed) & set("ÀÈÌÒÙ")
    assert run.status == 0
    assert run.output.splitlines()[:2] == [names[0], "=" * len(names[0])]
    assert f"- Ruolo: {role} (origine: " in run.output
    assert "Tutte le osservazioni, con la loro origine" in run.output


def test_an_ambiguous_name_asks_which_twin(tmp_path: Path) -> None:
    with FakeStudio(language="it", twins=3) as studio:
        project = seeded(tmp_path, studio)
        initials = [name[:1].casefold() for name in twin_names(project)]
        shared = next((initial for initial in initials if initials.count(initial) > 1), None)
        assert shared is not None
        run = ut(tmp_path, "--lang", "it", "twins", "show", shared, answers=["2"])
        matches = [
            version
            for version in versions(project)
            if str(version["profile"]["name"]).casefold().startswith(shared)
        ]

    lines = run.output.splitlines()
    assert run.status == 0
    assert lines[: len(matches) + 2] == [
        f"Più twin corrispondono a «{shared}»: quale intendi?",
        *(f"  {number}. {choice(version)}" for number, version in enumerate(matches, start=1)),
        "Scrivi il numero della tua scelta: ",
    ]
    assert lines[len(matches) + 2] == matches[1]["profile"]["name"]


def test_a_name_that_matches_nothing_lists_the_twins(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=2) as studio:
        project = seeded(tmp_path, studio)
        names = twin_names(project)
        run = ut(tmp_path, "twins", "show", "Zeta")
        numbered = ut(tmp_path, "--lang", "it", "twins", "ask", "7", "Ciao?")
        assert studio.project(project.id).spent_microusd == 0

    assert not any(plain(name).startswith(("zeta", "7")) for name in names)
    assert run.status == 1
    assert run.errors == 'No twin matches "Zeta". These are the twins of the project:\n'
    assert [row[1] for row in table(run.output)[1:]] == names
    assert numbered.status == 1
    assert numbered.errors == "Nessun twin corrisponde a «7». Ecco i twin del progetto:\n"
    assert "Per fargli una domanda: `ut twins ask 1`." in numbered.output


def test_one_question_prints_the_answer_after_the_name_of_the_twin(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=2) as studio:
        project = seeded(tmp_path, studio)
        run = ut(tmp_path, "twins", "ask", "1", "How", "do", "you", "work?")
        spent = studio.project(project.id).spent_microusd
        conversation = [
            request
            for request in studio.requests
            if request.method == "POST" and request.path.endswith("/conversation/turns")
        ]
        version = versions(project)[0]
        replies = recorded_replies(tmp_path, project, version)

    name = str(version["profile"]["name"])
    assert len(replies) == 1
    assert replies[0].strip()
    assert run.status == 0
    assert run.output == (
        f"{SIMULATED['en']}\n"
        "Estimate: 0.02-0.05 USD, about 1 min. Credit left in the Studio: 60.00 USD.\n"
        f"{name}:\n"
        f"{replies[0]}\n"
    )
    assert spent == 30_000
    assert len(conversation) == 1
    assert b'"question": "How do you work?"' in conversation[0].body
    assert b'"expected_turn_count": 0' in conversation[0].body


def test_a_conversation_goes_on_until_the_word_to_leave(tmp_path: Path) -> None:
    with FakeStudio(language="it", twins=2) as studio:
        project = seeded(tmp_path, studio)
        first = ut(
            tmp_path,
            "--lang",
            "it",
            "twins",
            "ask",
            "1",
            answers=["Come lavori?", "", "E di sera?", "/ESCI", "Mai inviata"],
        )
        second = ut(tmp_path, "twins", "ask", "1", answers=["Third?", "/quit"])
        spent = studio.project(project.id).spent_microusd
        version = versions(project)[0]
        replies = recorded_replies(tmp_path, project, version)

    name = str(version["profile"]["name"])
    assert len(replies) == 3
    assert first.status == 0
    assert first.output.splitlines() == [
        SIMULATED["it"],
        HINT["it"],
        "Stima: 0,02-0,05 USD, circa 1 min. Credito rimasto nello Studio: 60,00 USD.",
        "Tu: ",
        f"{name}:",
        replies[0],
        "",
        "Tu: ",
        "Serve una risposta per andare avanti.",
        "Tu: ",
        f"{name}:",
        replies[1],
        "",
        "Tu: ",
        END["it"],
    ]
    assert second.status == 0
    assert second.output.splitlines() == [
        f"Earlier conversation with {name} (questions shown: 2):",
        "You: Come lavori?",
        f"{name}:",
        replies[0],
        "You: E di sera?",
        f"{name}:",
        replies[1],
        "",
        SIMULATED["en"],
        HINT["en"],
        "Estimate: 0.02-0.05 USD, about 1 min. Credit left in the Studio: 59.94 USD.",
        "You: ",
        f"{name}:",
        replies[2],
        "",
        "You: ",
        END["en"],
    ]
    assert spent == 90_000


def test_a_conversation_ends_when_the_input_closes(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=1) as studio:
        seeded(tmp_path, studio)
        run = ut(tmp_path, "twins", "ask", "1", answers=["Why?"])

    assert (run.status, run.errors) == (0, "")
    assert run.output.splitlines()[-2:] == ["You: ", END["en"]]


def test_twins_not_approved_yet_name_the_command_that_approves_them(tmp_path: Path) -> None:
    with FakeStudio(language="it") as studio:
        seeded(tmp_path, studio, through="team")
        italian = ut(tmp_path, "--lang", "it", "twins")
        english = ut(tmp_path, "twins", "ask", "1", "Hello?")

    assert italian.status == 1
    assert italian.output == ""
    assert italian.errors == (
        "I twin di questo progetto non sono ancora approvati, oppure vanno approvati di nuovo "
        "dopo un cambiamento del brief o della squadra. Confermali con `ut init`, poi riprova.\n"
    )
    assert english.status == 1
    assert "Confirm them with `ut init`, then try again." in english.errors


def test_without_sign_in_the_twins_come_from_the_knowledge_folder(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    knowledge.unpack(valid_archive(), project.knowledge)

    listed_run = run_ut(["--lang", "it", "twins"], tmp_path, transport=NoNetwork(), variables=WIDE)
    shown = run_ut(["twins", "show", "org"], tmp_path, transport=NoNetwork(), variables=WIDE)

    assert listed_run.status == 0
    assert listed_run.output.splitlines()[0] == (
        "Non hai eseguito l'accesso allo Studio http://127.0.0.1:8000: ecco i twin salvati "
        "nella cartella di conoscenza orchestwin/ (versione 1). Per parlare con loro accedi "
        "con `ut login`."
    )
    assert table(listed_run.output) == [
        ["N.", "Nome", "Ruolo", "Che cosa vuole"],
        [
            "1",
            "Addetti all'accoglienza",
            "Addetti all'accoglienza",
            "Verificare la presenza degli ospiti",
        ],
        ["2", "Organizzatori volontari", "Organizzatori volontari", "Aggiungere ospiti per nome"],
    ]
    assert "Per fargli una domanda" not in listed_run.output
    assert shown.status == 0
    assert shown.output.splitlines()[0] == (
        "You are not signed in to the Studio http://127.0.0.1:8000: here are the twins saved "
        "in the knowledge folder orchestwin/ (version 1). To talk to them, sign in with "
        "`ut login`."
    )
    assert shown.output.splitlines()[1] == "Organizzatori volontari"
    text = " ".join(line.strip() for line in shown.output.splitlines())
    assert (
        "- Goals: Aggiungere ospiti per nome; Vedere la lista aggiornata; Evitare nomi vuoti "
        "(origin: model suggestion, to be checked; sources: document of the Studio, project "
        "brief, model proposal). Why: Directly extracted from the project brief goals"
    ) in text


def test_a_studio_out_of_reach_gives_the_twins_of_the_saved_step(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=2) as studio:
        seeded_project = studio_project(studio)
        version = seeded_project.current("twins")
        gate = seeded_project.gate("twins")
    assert version is not None
    store_session(tmp_path)
    project = link_folder(tmp_path / "project")
    project.save_step("twins", version, gate, START)

    run = run_ut(["twins", "list"], tmp_path, transport=Offline(), variables=WIDE)
    italian = run_ut(
        ["--lang", "it", "twins", "show", "1"], tmp_path, transport=Offline(), variables=WIDE
    )

    names = [str(twin["profile"]["name"]) for twin in version["snapshot"]["twin_versions"]]
    assert run.status == 0
    assert run.output.splitlines()[0] == (
        "The Studio http://127.0.0.1:8000 does not answer: here are the twins saved in the "
        "approved step .orchestwin/steps/twins.json."
    )
    assert [row[1] for row in table(run.output)[1:]] == names
    assert run.slept == 4.0
    assert italian.status == 0
    assert italian.output.splitlines()[0] == (
        "Lo Studio http://127.0.0.1:8000 non risponde: ecco i twin salvati nel passo approvato "
        ".orchestwin/steps/twins.json."
    )
    assert italian.output.splitlines()[1] == names[0]


def studio_project(studio: FakeStudio) -> FakeProject:
    studio.add_account(EMAIL, TEST_PASSWORD)
    return studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="twins")


def test_a_studio_out_of_reach_without_saved_twins_says_so(tmp_path: Path) -> None:
    store_session(tmp_path)
    link_folder(tmp_path / "project")

    listed_run = run_ut(["twins"], tmp_path, transport=Offline())
    asked = run_ut(["--lang", "it", "twins", "ask", "1", "Ciao?"], tmp_path, transport=Offline())

    assert listed_run.status == 4
    assert listed_run.errors == (
        "The Studio at http://127.0.0.1:8000 does not answer. Check that it is running, then "
        "try again.\n"
    )
    assert asked.status == 4
    assert asked.errors.startswith("Lo Studio all'indirizzo http://127.0.0.1:8000 non risponde.")


def test_the_ceiling_of_spending_stops_the_question(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=1, budget_usd=1.0, spent_usd=1.0) as studio:
        seeded(tmp_path, studio)
        run = ut(tmp_path, "twins", "ask", "1", "How much?")
        italian = ut(tmp_path, "--lang", "it", "twins", "ask", "1", answers=["Quanto?"])
        spent = studio.spent_microusd

    assert run.status == 5
    assert "Credit left in the Studio: 0.00 USD." in run.output
    assert "The estimate is above the credit left" in run.output
    assert run.errors == (
        "The Studio refused the request to the twins because it would go over a spending "
        "ceiling. Whoever runs the Studio can raise it; then you can try again.\n"
    )
    assert italian.status == 5
    assert italian.errors.startswith("Lo Studio ha rifiutato la richiesta ai twin perché")
    assert spent == 1_000_000


def test_a_failed_answer_can_be_asked_again_with_a_new_estimate(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=1) as studio:
        project = seeded(tmp_path, studio)
        studio.fail_next("POST", TURNS, status=502, body=MODEL_FAILURE)
        single = ut(tmp_path, "twins", "ask", "1", "Why?")
        studio.fail_next("POST", TURNS, status=502, body=MODEL_FAILURE)
        talk = ut(tmp_path, "--lang", "it", "twins", "ask", "1", answers=["Perché?", "Perché?"])
        version = versions(project)[0]
        replies = recorded_replies(tmp_path, project, version)

    name = str(version["profile"]["name"])
    assert single.status == 1
    assert single.output.count("Estimate: 0.02-0.05 USD") == 1
    assert single.errors == (
        f"{name} could not answer: the model gave no valid answer or could not be reached "
        "(INVALID_TWIN_CHAT_OUTPUT). You can ask the question again by launching the command "
        "again: it is a new spending, and the estimate is shown again first.\n"
    )
    assert talk.status == 0
    assert talk.errors == (
        f"{name} non ha potuto rispondere: il modello non ha dato una risposta valida oppure "
        "non era raggiungibile (INVALID_TWIN_CHAT_OUTPUT). Puoi fare di nuovo la domanda: è "
        "una nuova spesa, e prima ti mostro di nuovo la stima.\n"
    )
    assert talk.output.count("Stima: 0,02-0,05 USD") == 2
    assert len(replies) == 1
    assert talk.output.count(replies[0]) == 1


def test_asking_needs_the_studio_and_the_sign_in(tmp_path: Path) -> None:
    link_folder(tmp_path / "project")

    run = run_ut(["twins", "ask", "1", "Hello?"], tmp_path, transport=NoNetwork())

    assert run.status == 3
    assert run.errors == (
        "You are not signed in to the Studio http://127.0.0.1:8000. Sign in with `ut login`.\n"
    )


def test_review_runs_the_twin_review_and_returns_its_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, Path]] = []

    def review_stub(context: object, client: object, project: ProjectFolder) -> int:
        calls.append((client.studio.origin, project.root))
        return 5

    monkeypatch.setattr("orchestwin.cli.flows.review.run_review", review_stub)
    link_folder(tmp_path / "project")

    run = run_ut(["twins", "review"], tmp_path, transport=NoNetwork())

    assert run.status == 5
    assert calls == [("http://127.0.0.1:8000", tmp_path / "project")]


def test_twins_outside_a_linked_folder_is_not_linked(tmp_path: Path) -> None:
    run = run_ut(["twins", "list"], tmp_path, transport=NoNetwork())

    assert run.status == 6
    assert "This folder is not linked to a project of the Studio." in run.errors
