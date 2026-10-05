from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import twin_chat
from orchestwin.cli.http import Reply, UrlTransport, unreachable
from orchestwin.cli.messages import known, text
from orchestwin.cli.project import ProjectFolder
from orchestwin.knowledge.state import ProjectStateSources
from src.test.python.knowledge.knowledge_fixtures import files_before_learning

from .support.fake_studio import FakeProject, FakeStudio, RecordedRequest
from .support.folders import learned_entries, state_archive, valid_archive, valid_files
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
    "description": "Description",
    "represents": "Represents",
    "does_not_represent": "Does not represent",
    "evidence_gaps": "Evidence gaps",
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
    "en": "Write a question and press Enter. To finish write /quit. Each answer means a little "
    "spending on the model.",
}
END = {
    "it": "Conversazione finita: domande e risposte restano salvate nello Studio.",
    "en": "Conversation ended: questions and answers stay saved in the Studio.",
}
LEARNING = "/projects/{project_id}/twin-learning"
OBSERVATIONS = "/projects/{project_id}/user-twins/{twin_id}/observations"
NOT_FOUND = {"detail": "Not Found"}
UPDATE_ID = "6b8f0f5e-0000-4000-8000-0000000000a1"


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
    labels = [str(entry["label"]) for entry in project.twin_learning()]
    for number, version in enumerate(versions(project), start=1):
        goals = observed(version, "goals")
        rows.append(
            [
                str(number),
                str(version["profile"]["name"]),
                role_of(version) or "-",
                goals[0] if goals else "-",
                labels[number - 1],
            ]
        )
    return rows


def say(key: str, language: str = "en", /, **values: object) -> str:
    assert known(key), key
    return text(key, language, **values)


def posted(studio: FakeStudio, suffix: str) -> list[RecordedRequest]:
    return [
        request
        for request in studio.requests
        if request.method == "POST" and request.path.endswith(suffix)
    ]


def publication(version: int, language: str = "en") -> list[str]:
    lines: list[str] = []
    for key in ("common.folder_publishing", "common.folder_downloading"):
        label = say(key, language)
        lines.extend(
            [
                say("common.progress_started", language, label=label),
                say("common.progress_done", language, label=label, elapsed="0 s"),
            ]
        )
    return [*lines, say("twins.folder_updated", language, version=version)]


def learned_section(output: str) -> list[str]:
    lines = output.splitlines()
    start = next(
        index
        for index, line in enumerate(lines)
        if line.startswith(("Learned during the development", "Appreso durante lo sviluppo"))
    )
    section: list[str] = []
    for line in lines[start:]:
        if line.startswith("  ") and section:
            section[-1] = f"{section[-1]} {line.strip()}"
        else:
            section.append(line)
    return section


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


def scripted_twins(
    twins: Sequence[Mapping[str, object]],
    *,
    runs: int,
    learning: Mapping[str, object] | None = None,
) -> ScriptedTransport:
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
        transport.expect(
            "GET",
            f"{BASE}/twin-learning",
            status=404 if learning is None else 200,
            body=NOT_FOUND if learning is None else learning,
        )
    return transport


def test_the_list_in_italian_follows_the_order_of_the_studio(tmp_path: Path) -> None:
    with FakeStudio(language="it", twins=3) as studio:
        project = seeded(tmp_path, studio)
        run = ut(tmp_path, "--lang", "it", "twins", "list")
        rows = listed(project)
        assert studio.errors == []

    assert len(rows) == 3
    assert [row[-1] for row in rows] == ["1.0", "1.0", "1.0"]
    assert (run.status, run.errors) == (0, "")
    assert run.output.splitlines()[:2] == ["User Twin di «Calcolo mancia»", "=" * 29]
    assert table(run.output) == [["N.", "Nome", "Ruolo", "Che cosa vuole", "Versione"], *rows]
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
    assert table(run.output) == [["No.", "Name", "Role", "What they want", "Version"], *rows]
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
    assert "Basis: Provisional" in lines
    assert "Does not represent: Unknown [Unknown]" in lines
    assert "Evidence gaps: Unknown [Unknown]" in lines
    lines = lines[:2] + lines[9:]
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
    assert english.output.splitlines()[:2] + english.output.splitlines()[9:] == [
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
    assert italian.output.splitlines()[:2] + italian.output.splitlines()[9:] == [
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
        ["No.", "Name", "Role", "What they want", "Version"],
        ["1", "Marta Twin", "Cameriera del turno serale", "Chiudere il conto in fretta", "2"],
        ["2", "Cassiere del bar Twin", "Cassiere del bar", "-", "1"],
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
        "I twin di questo progetto non sono ancora approvati, oppure sono rimasti indietro dopo "
        "un cambiamento del brief o delle prospettive. Se sono indietro aggiornali con "
        "`ut sections update`, altrimenti confermali con `ut init`; poi riprova.\n"
    )
    assert english.status == 1
    assert "otherwise confirm them with `ut init`. Then try again." in english.errors


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
        ["N.", "Nome", "Ruolo", "Che cosa vuole", "Versione"],
        [
            "1",
            "Addetti all'accoglienza",
            "Addetti all'accoglienza",
            "Verificare la presenza degli ospiti",
            "1.0",
        ],
        [
            "2",
            "Organizzatori volontari",
            "Organizzatori volontari",
            "Aggiungere ospiti per nome",
            "1.0",
        ],
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
        "again: it means new spending, and the estimate is shown again first.\n"
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


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_help_names_the_actions_that_follow_what_the_twins_learn(
    tmp_path: Path, language: str
) -> None:
    def helped(*arguments: str) -> str:
        run = run_ut(
            ["--lang", language, "twins", *arguments, "--help"],
            tmp_path,
            transport=NoNetwork(),
            variables=WIDE,
        )
        assert (run.status, run.errors) == (0, "")
        return " ".join(run.output.split())

    whole = helped()
    update = helped("update")
    learn = helped("learn")
    forget = helped("forget")

    for key in (
        "twins.help",
        "twins.option_action",
        "twins.help_update",
        "twins.help_learn",
        "twins.help_forget",
    ):
        assert say(key, language) in whole, key
    assert say("twins.option_update_twin", language) in update
    assert say("twins.option_text", language) in learn
    assert say("twins.option_code", language) in forget
    assert say("twins.option_reason", language) in forget


def learned_observation(
    code: str,
    statement: str,
    source: str,
    approved_at: str,
    *,
    contradicts: str | None = None,
) -> dict[str, object]:
    return {
        "code": code,
        "statement": statement,
        "basis": "A finding on the acceptance tests." if source == "TWIN_CRITIQUE" else None,
        "source": source,
        "about": {"requirement": None, "screen": None},
        "contradicts_profile": contradicts,
        "added_in_version": 1,
        "approved_at": approved_at,
        "update_id": UPDATE_ID if source == "TWIN_CRITIQUE" else None,
    }


def retired_observation(code: str) -> dict[str, object]:
    return {
        "code": code,
        "statement": f"Statement of {code}.",
        "retired_in_version": 4,
        "retired_at": "2026-09-30T09:00:00+00:00",
        "reason": None,
    }


CONTRADICTION = "The profile says they read it up close."
MARTA_LEARNING = {
    "twin_id": "twin-1",
    "twin_name": "Marta Twin",
    "profile_version_number": 2,
    "development_version_number": 5,
    "label": "2.5",
    "observations": [
        learned_observation(
            "OBS-001",
            "Waiters read the total from a distance.",
            "TWIN_CRITIQUE",
            "2026-09-29T23:30:00-02:00",
            contradicts=CONTRADICTION,
        ),
        learned_observation(
            "OBS-004", "Waiters split the bill by seat.", "OWNER", "2026-09-30T08:00:00+00:00"
        ),
        learned_observation("OBS-005", "Waiters work in pairs.", "IMPORTED", "not a date"),
    ],
    "retired": [retired_observation("OBS-002"), retired_observation("OBS-003")],
    "pending_update": {"id": UPDATE_ID, "status": "PROPOSED"},
    "new_material": {"changes": 0, "tests": 0},
}
CASHIER_LEARNING = {
    "twin_id": "twin-2",
    "twin_name": "Cassiere del bar Twin",
    "profile_version_number": 1,
    "development_version_number": 0,
    "label": "1.0",
    "observations": [],
    "retired": [],
    "pending_update": None,
    "new_material": {"changes": 1, "tests": 0},
}
LEARNING_DOCUMENT = {
    "project_id": PROJECT_ID,
    "update_available": True,
    "twins": [MARTA_LEARNING, CASHIER_LEARNING],
}


def test_the_list_gives_the_label_and_the_learned_observations_of_every_twin(
    tmp_path: Path,
) -> None:
    transport = scripted_twins([RICH_TWIN, ABSTAINING_TWIN], runs=2, learning=LEARNING_DOCUMENT)
    store_session(tmp_path)
    link_folder(tmp_path / "project")

    english = run_ut(["twins"], tmp_path, transport=transport, variables=WIDE)
    italian = run_ut(["--lang", "it", "twins"], tmp_path, transport=transport, variables=WIDE)

    assert table(english.output) == [
        ["No.", "Name", "Role", "What they want", "Version", "Learned"],
        [
            "1",
            "Marta Twin",
            "Cameriera del turno serale",
            "Chiudere il conto in fretta",
            "2.5",
            "3",
        ],
        ["2", "Cassiere del bar Twin", "Cassiere del bar", "-", "1.0", "0"],
    ]
    assert english.output.splitlines()[-3:] == [
        say("twins.hint_pending", name="Marta Twin", number=1),
        say("twins.hint_show", number=1),
        say("twins.hint_ask", number=1),
    ]
    assert table(italian.output)[0] == [
        "N.",
        "Nome",
        "Ruolo",
        "Che cosa vuole",
        "Versione",
        "Apprese",
    ]
    assert say("twins.hint_pending", "it", name="Marta Twin", number=1) in italian.output
    transport.assert_done()


@pytest.mark.parametrize("language", ["en", "it"])
def test_show_ends_with_what_the_twin_learned_during_the_development(
    tmp_path: Path, language: str
) -> None:
    transport = scripted_twins([RICH_TWIN, ABSTAINING_TWIN], runs=1, learning=LEARNING_DOCUMENT)
    store_session(tmp_path)
    link_folder(tmp_path / "project")

    run = run_ut(
        ["--lang", language, "twins", "show", "1"], tmp_path, transport=transport, variables=WIDE
    )

    first = say(
        "twins.learned_observation",
        language,
        code="OBS-001",
        statement="Waiters read the total from a distance.",
        origin=say("twins.learned_from_critiques", language, date="2026-09-30"),
    )
    assert run.status == 0
    assert learned_section(run.output) == [
        say("twins.section_learned", language, label="2.5"),
        "- " + say("twins.learned_contradiction", language, line=first, text=CONTRADICTION),
        "- "
        + say(
            "twins.learned_observation",
            language,
            code="OBS-004",
            statement="Waiters split the bill by seat.",
            origin=say("twins.learned_from_owner", language, date="2026-09-30"),
        ),
        "- "
        + say(
            "twins.learned_observation",
            language,
            code="OBS-005",
            statement="Waiters work in pairs.",
            origin=say("twins.learned_on", language, date="not a date"),
        ),
        say("twins.learned_retired", language, count=2),
        say("twins.learned_pending", language, number=1),
    ]
    transport.assert_done()


def test_with_the_studio_the_list_and_show_follow_what_the_twins_learned(tmp_path: Path) -> None:
    owner = "Owners count the tips at closing time."
    with FakeStudio(language="en", twins=2) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        project.seed_learning(0)
        project.seed_learning(1, [owner], source="OWNER")
        project.seed_change()
        project.seed_update(0)
        entries = project.twin_learning()
        listing = ut(tmp_path, "twins")
        first = ut(tmp_path, "twins", "show", "1")
        second = ut(tmp_path, "--lang", "it", "twins", "show", "2")

    names = [str(entry["twin_name"]) for entry in entries]
    statements = [str(item["statement"]) for item in entries[0]["observations"]]
    assert [row[4:] for row in table(listing.output)] == [
        ["Version", "Learned"],
        ["1.1", "2"],
        ["1.1", "1"],
    ]
    assert say("twins.hint_pending", name=names[0], number=1) in listing.output
    assert learned_section(first.output) == [
        say("twins.section_learned", label="1.1"),
        *(
            "- "
            + say(
                "twins.learned_observation",
                code=code,
                statement=statement,
                origin=say("twins.learned_from_critiques", date="2026-09-29"),
            )
            for code, statement in zip(("OBS-001", "OBS-002"), statements, strict=True)
        ),
        say("twins.learned_pending", number=1),
    ]
    assert learned_section(second.output) == [
        say("twins.section_learned", "it", label="1.1"),
        "- "
        + say(
            "twins.learned_observation",
            "it",
            code="OBS-003",
            statement=owner,
            origin=say("twins.learned_from_owner", "it", date="2026-09-29"),
        ),
    ]


def test_a_twin_that_learned_nothing_names_the_commands_that_teach_it(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=1) as studio:
        seeded(tmp_path, studio)
        run = ut(tmp_path, "twins", "show", "1")
        italian = ut(tmp_path, "--lang", "it", "twins", "show", "1")

    assert run.output.splitlines()[-3:] == [
        "",
        say("twins.section_learned", label="1.0"),
        say("twins.learned_none"),
    ]
    assert italian.output.splitlines()[-1] == say("twins.learned_none", "it")


def test_a_studio_older_than_the_twin_learning_shows_the_profile_version_alone(
    tmp_path: Path,
) -> None:
    with FakeStudio(language="en", twins=2) as studio:
        project = seeded(tmp_path, studio)
        studio.fail_next("GET", LEARNING, status=404, body=NOT_FOUND)
        listing = ut(tmp_path, "twins")
        studio.fail_next("GET", LEARNING, status=405, body={"detail": "Method Not Allowed"})
        shown = ut(tmp_path, "twins", "show", "1")
        rows = listed(project)

    assert table(listing.output) == [
        ["No.", "Name", "Role", "What they want", "Version"],
        *([*row[:4], "1"] for row in rows),
    ]
    assert shown.status == 0
    assert say("twins.section_learned", label="1.0") not in shown.output
    assert "Learned during the development" not in shown.output


def test_offline_the_labels_and_what_the_twins_learned_come_from_the_folder(
    tmp_path: Path,
) -> None:
    project = link_folder(tmp_path / "project")
    archive = state_archive(state=ProjectStateSources(learning=learned_entries()))
    knowledge.unpack(archive, project.knowledge)
    reception = learned_entries()[0]

    listing = run_ut(["--lang", "it", "twins"], tmp_path, transport=NoNetwork(), variables=WIDE)
    shown = run_ut(["twins", "show", "1"], tmp_path, transport=NoNetwork(), variables=WIDE)

    assert listing.status == 0
    assert [row[4:] for row in table(listing.output)] == [
        ["Versione", "Apprese"],
        ["1.3", "2"],
        ["1.0", "0"],
    ]
    assert "ut twins update" not in listing.output
    assert shown.status == 0
    observations = reception["observations"]
    assert learned_section(shown.output) == [
        say("twins.section_learned", label="1.3"),
        "- "
        + say(
            "twins.learned_observation",
            code="OBS-001",
            statement=observations[0]["statement"],
            origin=say("twins.learned_from_critiques", date="2026-09-29"),
        ),
        "- "
        + say(
            "twins.learned_observation",
            code="OBS-003",
            statement=observations[1]["statement"],
            origin=say("twins.learned_from_owner", date="2026-09-29"),
        ),
        say("twins.learned_retired", count=1),
    ]


def test_offline_a_folder_without_the_learning_gives_the_profile_version_alone(
    tmp_path: Path,
) -> None:
    project = link_folder(tmp_path / "project")
    for name, content in files_before_learning(valid_files()).items():
        target = project.knowledge.joinpath(*name.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))

    listing = run_ut(["twins"], tmp_path, transport=NoNetwork(), variables=WIDE)
    shown = run_ut(["twins", "show", "2"], tmp_path, transport=NoNetwork(), variables=WIDE)

    assert listing.status == 0
    assert [row[4:] for row in table(listing.output)] == [["Version"], ["1"], ["1"]]
    assert shown.status == 0
    assert shown.output.splitlines()[1] == "Organizzatori volontari"
    assert "Learned during the development" not in shown.output


def test_learn_and_forget_change_the_label_and_publish_the_folder(tmp_path: Path) -> None:
    statement = "People read the bill standing up."
    with FakeStudio(language="en", twins=2) as studio:
        project = seeded(tmp_path, studio)
        twin = str(project.twin_learning()[0]["twin_name"])
        learned = ut(tmp_path, "twins", "learn", "1", "People", "read the bill", "standing up.")
        forgotten = ut(tmp_path, "twins", "forget", "1", "obs-001", "--reason", " Not at  night. ")
        shown = ut(tmp_path, "twins", "show", "1")
        entries = project.twin_learning()
        bodies = [json.loads(request.body) for request in posted(studio, "/observations")]
        retirements = [json.loads(request.body) for request in posted(studio, "/retire")]
        paths = [request.path for request in posted(studio, "/retire")]

    assert (learned.status, learned.errors) == (0, "")
    assert learned.output.splitlines() == [
        say("twins.learn_done", name=twin, code="OBS-001", label="1.1"),
        "",
        *publication(1),
    ]
    assert (forgotten.status, forgotten.errors) == (0, "")
    assert forgotten.output.splitlines() == [
        say("twins.forget_done", name=twin, code="OBS-001", label="1.2"),
        "",
        *publication(2),
    ]
    assert bodies == [{"statement": statement, "about": None}]
    assert retirements == [{"reason": "Not at night."}]
    assert paths[0].endswith("/observations/OBS-001/retire")
    assert entries[0]["retired"][0]["reason"] == "Not at night."
    assert learned_section(shown.output) == [
        say("twins.section_learned", label="1.2"),
        say("twins.learned_none_active"),
        say("twins.learned_retired", count=1),
    ]


def test_learn_and_forget_speak_italian_and_publish_the_folder(tmp_path: Path) -> None:
    with FakeStudio(language="it", twins=1) as studio:
        project = seeded(tmp_path, studio)
        twin = str(project.twin_learning()[0]["twin_name"])
        run = ut(tmp_path, "--lang", "it", "twins", "learn", twin[:8], "Chi paga", "sta in piedi.")
        forgotten = ut(tmp_path, "--lang", "it", "twins", "forget", "1", "OBS-001")
        shown = ut(tmp_path, "--lang", "it", "twins", "show", "1")
        retirements = [json.loads(request.body) for request in posted(studio, "/retire")]

    assert (run.status, run.errors) == (0, "")
    assert run.output.splitlines() == [
        say("twins.learn_done", "it", name=twin, code="OBS-001", label="1.1"),
        "",
        *publication(1, "it"),
    ]
    assert (forgotten.status, forgotten.errors) == (0, "")
    assert forgotten.output.splitlines() == [
        say("twins.forget_done", "it", name=twin, code="OBS-001", label="1.2"),
        "",
        *publication(2, "it"),
    ]
    assert retirements == [{"reason": None}]
    assert learned_section(shown.output) == [
        say("twins.section_learned", "it", label="1.2"),
        say("twins.learned_none_active", "it"),
        say("twins.learned_retired", "it", count=1),
    ]


def many_statements(count: int) -> list[str]:
    return [f"Observation written by the owner, number {number}." for number in range(count)]


@pytest.mark.parametrize(
    ("arguments", "code", "values"),
    [
        (("learn", "1", "One more thing."), "TWIN_OBSERVATIONS_LIMIT", {}),
        (("learn", "1", "One more thing."), "TWIN_UPDATE_PENDING", {}),
        (("forget", "1", "OBS-001"), "TWIN_UPDATE_PENDING", {}),
        (("forget", "1", "OBS-999"), "TWIN_OBSERVATION_NOT_FOUND", {"observation": "OBS-999"}),
    ],
)
@pytest.mark.parametrize("language", ["en", "it"])
def test_the_refusals_of_learn_and_forget_become_sentences(
    tmp_path: Path,
    arguments: tuple[str, ...],
    code: str,
    values: dict[str, object],
    language: str,
) -> None:
    with FakeStudio(language=language, twins=1) as studio:
        project = seeded(tmp_path, studio)
        if code == "TWIN_OBSERVATIONS_LIMIT":
            project.seed_learning(0, many_statements(20), source="OWNER")
        if code == "TWIN_UPDATE_PENDING":
            project.seed_change()
            project.seed_learning(0)
            project.seed_change()
            project.seed_update(0)
        twin = str(project.twin_learning()[0]["twin_name"])
        before = project.twin_learning()
        run = ut(tmp_path, "--lang", language, "twins", *arguments)
        after = project.twin_learning()
        publications = posted(studio, "/knowledge-packages")

    sentence = say(f"twins.errors.{code}", language, name=twin, number=1, limit=20, **values)
    assert (run.status, run.output) == (1, "")
    assert run.errors == sentence + "\n"
    assert (before, publications) == (after, [])


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_limit_names_the_observation_with_the_word_of_the_usage(
    tmp_path: Path, language: str
) -> None:
    run = run_ut(
        ["--lang", language, "twins", "forget", "--help"],
        tmp_path,
        transport=NoNetwork(),
        variables=WIDE,
    )
    sentence = say("twins.errors.TWIN_OBSERVATIONS_LIMIT", language, name="Ada", number=1, limit=20)

    usage = run.output.splitlines()[0]
    assert run.status == 0
    assert usage.startswith("usage: ut twins forget ")
    assert usage.endswith(" TWIN CODE")
    assert "`ut twins forget 1 CODE`" in sentence


@pytest.mark.parametrize(
    ("status", "code"), [(404, "USER_TWIN_NOT_FOUND"), (409, "USER_MODELING_APPROVAL_REQUIRED")]
)
@pytest.mark.parametrize("language", ["en", "it"])
def test_a_twin_the_studio_no_longer_takes_is_named(
    tmp_path: Path, status: int, code: str, language: str
) -> None:
    with FakeStudio(language=language, twins=1) as studio:
        seeded(tmp_path, studio)
        studio.fail_next("POST", OBSERVATIONS, status=status, body={"detail": {"code": code}})
        run = ut(tmp_path, "--lang", language, "twins", "learn", "1", "Chi paga sta in piedi.")

    assert (run.status, run.output) == (1, "")
    assert run.errors == say(f"twins.errors.{code}", language) + "\n"


@pytest.mark.parametrize(
    ("arguments", "code", "values"),
    [
        (("learn", "1"), "TWINS_TEXT_EMPTY", {}),
        (("learn", "1", "  ", "\t"), "TWINS_TEXT_EMPTY", {}),
        (("learn", "1", "x" * 401), "TWINS_TEXT_TOO_LONG", {"limit": 400}),
        (("forget", "1", "OBS-1"), "TWINS_CODE_INVALID", {"observation": "OBS-1"}),
        (("forget", "1", "TSK-001"), "TWINS_CODE_INVALID", {"observation": "TSK-001"}),
        (
            ("forget", "1", "OBS-001", "--reason", "y" * 301),
            "TWINS_REASON_TOO_LONG",
            {"limit": 300},
        ),
    ],
)
@pytest.mark.parametrize("language", ["en", "it"])
def test_a_wrong_text_or_code_is_refused_before_any_request(
    tmp_path: Path, arguments: tuple[str, ...], code: str, values: dict[str, object], language: str
) -> None:
    run = run_ut(["--lang", language, "twins", *arguments], tmp_path, transport=NoNetwork())

    assert (run.status, run.output) == (2, "")
    assert run.errors == say(f"twins.errors.{code}", language, **values) + "\n"


def test_learn_and_forget_need_a_studio_that_keeps_the_learning(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=1) as studio:
        seeded(tmp_path, studio)
        studio.fail_next("GET", LEARNING, status=404, body=NOT_FOUND, times=2)
        learned = ut(tmp_path, "twins", "learn", "1", "People stand.")
        forgotten = ut(tmp_path, "twins", "forget", "1", "OBS-001")
        publications = posted(studio, "/knowledge-packages")

    for run in (learned, forgotten):
        assert (run.status, run.output) == (1, "")
        assert run.errors == say("twins.update_unsupported") + "\n"
    assert posted(studio, "/observations") == []
    assert publications == []


def test_learn_names_a_twin_that_matches_nothing(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=2) as studio:
        seeded(tmp_path, studio)
        run = ut(tmp_path, "twins", "learn", "Zeta", "People stand.")

    assert run.status == 1
    assert run.errors == say("twins.no_match", value="Zeta") + "\n"
    assert posted(studio, "/observations") == []


def test_learning_needs_the_sign_in(tmp_path: Path) -> None:
    link_folder(tmp_path / "project")

    run = run_ut(["twins", "learn", "1", "People stand."], tmp_path, transport=NoNetwork())
    update = run_ut(["twins", "update"], tmp_path, transport=NoNetwork())

    assert (run.status, update.status) == (3, 3)
    assert run.errors == say("errors.NOT_SIGNED_IN", studio="http://127.0.0.1:8000") + "\n"
