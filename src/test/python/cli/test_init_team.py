from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from orchestwin.cli.api import team as team_api
from orchestwin.cli.commands.init import Journey
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows import init_team

from .support.fake_studio import FakeStudio
from .support.terminal import (
    PROJECT_ID,
    Run,
    command_context,
    link_folder,
    run_ut,
    store_session,
    terminal,
)
from .support.transports import API, ScriptedTransport
from .test_init_command import (
    IDEA,
    NAME,
    brief_answers,
    fake_project,
    posted,
    saved_stages,
    saved_step,
    sign_in,
    start,
    ut,
)

UNTIL_TEAM = ("--until", "team")
BEFORE_TEAM = [*start()[:-1], *brief_answers()]
PROPOSALS = "/projects/{project_id}/team-proposals"
BASE = f"{API}/projects/{PROJECT_ID}"
STEP_FILE = ".orchestwin/steps/team.json"
DESIGNER = "UX_UI_DESIGNER"
SECURITY = "SECURITY_REVIEWER"
PLATFORM = [
    "WORKFLOW_ORCHESTRATOR",
    "INTAKE_CLARIFICATION_AGENT",
    "TEAM_SELECTOR",
    "HUMAN_GATE_CONTROLLER",
    "ARTIFACT_MANAGER",
    "SANDBOX_CONTROLLER",
]
CORE = [
    "REQUIREMENTS_ANALYST",
    "UX_RESEARCHER_USER_MODELER",
    DESIGNER,
    "SOFTWARE_ARCHITECT",
    "QA_TEST_ENGINEER",
    "ACCESSIBILITY_REVIEWER",
]
WITHOUT_DESIGNER = [agent for agent in CORE if agent != DESIGNER]
ASPECTS = {
    "WEB": "FRONTEND_ENGINEER",
    "SERVICES": "BACKEND_ENGINEER",
    "MOBILE": "MOBILE_ENGINEER",
    "INTEGRATIONS": "INTEGRATION_ENGINEER",
}
FORBIDDEN = frozenset(
    {
        "squadra",
        "team",
        "agente",
        "agenti",
        "agent",
        "agents",
        "assistente",
        "assistenti",
        "assistant",
        "assistants",
        "specialista",
        "specialisti",
        "specialist",
        "specialists",
        "ruolo",
        "ruoli",
        "role",
        "roles",
        "membro",
        "membri",
        "member",
        "members",
    }
)
NOTE = (
    "Note: in the approved perspectives of this project User experience (UX) is not fully "
    "applied, so the design alternatives cannot be prepared."
)
ALWAYS_MISSING = {
    "en": "This version was prepared before this perspective became always applied: prepare the "
    "perspectives again in the web Studio.",
    "it": "Questa versione è stata preparata prima che questa prospettiva diventasse sempre "
    "applicata: prepara di nuovo le prospettive nel web.",
}

Evidence = dict[str, list[str]]
Words = Mapping[str, tuple[Evidence, Evidence]]


def evidence(fields: Sequence[str] = (), terms: Sequence[str] = ()) -> Evidence:
    return {"fields": list(fields), "terms": list(terms)}


WORDS: Words = {
    "WEB": (
        evidence(["description", "technical_constraints"], ["browser", "responsive"]),
        evidence(),
    ),
    "SERVICES": (
        evidence(["technical_constraints"], ["api"]),
        evidence(["description"], ["senza server"]),
    ),
    "INTEGRATIONS": (evidence(), evidence(["description"], ["no integrations"])),
}
STANDINGS = {
    "WEB": "REQUIRED",
    "SERVICES": "CONTESTED",
    "MOBILE": "OPTIONAL",
    "INTEGRATIONS": "EXCLUDED",
    "SECURITY": "OPTIONAL",
}
MIXED = [*CORE, "FRONTEND_ENGINEER", "MOBILE_ENGINEER"]


def forbidden(text: str) -> list[str]:
    found = re.findall(r"[^\W\d_]+", text.replace(STEP_FILE, "").lower())
    return sorted({word for word in found if word in FORBIDDEN})


def unit(key: str, agent: str | None, standing: str, applied: bool, words: Words) -> dict:
    requested, excluded = words.get(key, (evidence(), evidence()))
    return {
        "key": key,
        "agent_id": agent,
        "standing": standing,
        "applied": applied,
        "editable": standing in {"OPTIONAL", "CONTESTED"},
        "requested": requested,
        "excluded": excluded,
    }


def views(
    selected: Sequence[str], standings: Mapping[str, str], words: Words
) -> list[dict[str, object]]:
    found = {key: "OPTIONAL" for key in [*ASPECTS, "SECURITY"]} | dict(standings)

    def always(key: str, agents: Sequence[str]) -> dict[str, object]:
        applied = all(agent in selected for agent in agents)
        return {**unit(key, None, "ALWAYS", applied, words), "aspects": []}

    engineering = always("SOFTWARE_ENGINEERING", ["SOFTWARE_ARCHITECT", "QA_TEST_ENGINEER"])
    engineering["aspects"] = [
        unit(key, agent, found[key], agent in selected, words) for key, agent in ASPECTS.items()
    ]
    security = unit("SECURITY", SECURITY, found["SECURITY"], SECURITY in selected, words)
    return [
        always("UX", ["UX_RESEARCHER_USER_MODELER", DESIGNER]),
        always("ACCESSIBILITY", ["ACCESSIBILITY_REVIEWER"]),
        engineering,
        always("PRODUCT", ["REQUIREMENTS_ANALYST"]),
        {**security, "aspects": []},
    ]


def team_version(
    number: int,
    specialists: Sequence[str] = CORE,
    *,
    standings: Mapping[str, str] | None = None,
    words: Words | None = None,
    perspectives: bool = True,
) -> dict[str, object]:
    selected = team_api.ordered([*PLATFORM, *specialists])
    version: dict[str, object] = {
        "id": f"team-{number}",
        "version_number": number,
        "content_hash": f"team-hash-{number}",
        "selected_agent_ids": selected,
        "role_constraints": [],
        "constraint_issues": [],
        "members": [{"agent_id": agent, "justifications": []} for agent in selected],
    }
    if perspectives:
        version["perspectives"] = views(selected, standings or {}, words or {})
    return version


def gate(version: Mapping[str, object], status: str) -> dict[str, object]:
    return {
        "id": f"gate-{version['id']}",
        "status": status,
        "artifact": {"artifact_id": version["id"], "content_hash": version["content_hash"]},
    }


def expect_approval(transport: ScriptedTransport, version: Mapping[str, object]) -> None:
    transport.expect(
        "POST",
        f"{BASE}/gates/agent-team/submit",
        status=201,
        body={"status": "SUBMITTED", "gate": gate(version, "PENDING_APPROVAL"), "events": []},
    )
    transport.expect(
        "POST",
        f"{BASE}/gates/agent-team/decisions",
        body={"status": "APPLIED", "gate": gate(version, "APPROVED"), "event": None},
    )


def expect_edit(
    transport: ScriptedTransport,
    version: Mapping[str, object] | None,
    *,
    status: int = 201,
    body: object = None,
) -> None:
    answer = {"status": "UPDATED", "version": version, "issues": [], "events": []}
    transport.expect(
        "PATCH",
        f"{BASE}/team-proposals/current",
        status=status,
        body=answer if body is None else body,
    )


def team_step(
    tmp_path: Path,
    transport: ScriptedTransport,
    answers: list[str],
    version: dict[str, object],
    *,
    language: str = "en",
) -> tuple[bool, Journey]:
    store_session(tmp_path)
    folder = link_folder(tmp_path / "project")
    bundle = terminal(tmp_path, transport=transport, answers=answers)
    context = command_context(bundle.environment, language=language)
    journey = Journey(context, context.client(), folder, script=None, until=None, idea=None)
    state = init_team.TeamState(
        approved=False, readiness="TEAM_APPROVAL_REQUIRED", version=version, gate=None
    )
    return init_team.run(journey, state), journey


def printed(journey: Journey) -> str:
    return journey.console.environment.stdout.getvalue()


def patches(transport: ScriptedTransport) -> list[object]:
    return [request.json() for request in transport.requests("PATCH")]


def following(lines: list[str], first: str, count: int) -> list[str]:
    start_at = lines.index(first)
    return lines[start_at : start_at + count]


NO_SIGNALS = {
    "en": [
        "Perspectives (version 1)",
        "The competences through which the project is looked at: each one adds its "
        "considerations when the requirements and the design are written.",
        "  [x] User experience (UX): Always applied",
        "  [x] Accessibility: Always applied",
        "  [x] Software engineering: Always applied",
        "      [ ] Web interface: Your choice",
        "      [ ] Services and data: Your choice",
        "      [ ] Mobile: Your choice",
        "      [ ] Connections to other systems: Your choice",
        "  [x] Product: Always applied",
        "  [ ] Security: Your choice",
        "What do you do with the perspectives?",
        "  1. Approve them and go on",
        "  2. Change the perspectives",
        "  3. Stop here",
    ],
    "it": [
        "Prospettive (versione 1)",
        "Le competenze con cui guardare il progetto: ognuna porta le sue considerazioni quando "
        "si scrivono requisiti e design.",
        "  [x] Esperienza d'uso (UX): Sempre applicata",
        "  [x] Accessibilità: Sempre applicata",
        "  [x] Ingegneria del software: Sempre applicata",
        "      [ ] Interfaccia web: A scelta",
        "      [ ] Servizi e dati: A scelta",
        "      [ ] Mobile: A scelta",
        "      [ ] Collegamenti con altri sistemi: A scelta",
        "  [x] Prodotto: Sempre applicata",
        "  [ ] Sicurezza: A scelta",
        "Che cosa fai con le prospettive?",
        "  1. Le approvo e vado avanti",
        "  2. Cambio le prospettive",
        "  3. Mi fermo qui",
    ],
}
APPROVED = {
    "en": 'Step "Perspectives" approved (version 1). Saved in .orchestwin/steps/team.json.',
    "it": 'Passo "Prospettive" approvato (versione 1). Salvato in .orchestwin/steps/team.json.',
}


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_five_perspectives_of_a_brief_without_signals(tmp_path: Path, language: str) -> None:
    version = team_version(1)
    transport = ScriptedTransport()
    expect_approval(transport, version)

    approved, journey = team_step(tmp_path, transport, ["1"], version, language=language)

    assert approved
    output = printed(journey)
    lines = output.splitlines()
    expected = NO_SIGNALS[language]
    assert lines[0] == ""
    assert lines[1 : 1 + len(expected)] == expected
    assert APPROVED[language] in lines
    assert [agent for agent in team_api.AGENTS if agent in output] == []
    assert forbidden(output) == []
    assert journey.versions["team"] == 1
    transport.assert_done()


STANDING_LINES = {
    "en": [
        "  [x] Software engineering: Always applied",
        "      [x] Web interface: The brief asks for it («browser», «responsive» in The idea, "
        "Technical constraints)",
        "      [ ] Services and data: The brief says two different things: you decide (asks for "
        "it with «api» in Technical constraints; rules it out with «senza server» in The idea)",
        "      [x] Mobile: Applied, your choice",
        "      [ ] Connections to other systems: The brief rules it out («no integrations» in "
        "The idea)",
        "  [x] Product: Always applied",
        "  [ ] Security: Your choice",
    ],
    "it": [
        "  [x] Ingegneria del software: Sempre applicata",
        "      [x] Interfaccia web: La chiede il brief («browser», «responsive» in L'idea, "
        "Vincoli tecnici)",
        "      [ ] Servizi e dati: Il brief dice due cose diverse: decidi tu (la chiede con «api» "
        "in Vincoli tecnici; la esclude con «senza server» in L'idea)",
        "      [x] Mobile: Applicata, a tua scelta",
        "      [ ] Collegamenti con altri sistemi: Il brief la esclude («no integrations» in "
        "L'idea)",
        "  [x] Prodotto: Sempre applicata",
        "  [ ] Sicurezza: A scelta",
    ],
}


@pytest.mark.parametrize("language", ["en", "it"])
def test_each_standing_is_said_in_words_with_the_words_of_the_brief(
    tmp_path: Path, language: str
) -> None:
    version = team_version(1, MIXED, standings=STANDINGS, words=WORDS)
    transport = ScriptedTransport()
    expect_approval(transport, version)

    approved, journey = team_step(tmp_path, transport, ["1"], version, language=language)

    assert approved
    lines = printed(journey).splitlines()
    expected = STANDING_LINES[language]
    assert following(lines, expected[0], len(expected)) == expected
    assert forbidden(printed(journey)) == []
    transport.assert_done()


def test_a_required_unit_without_words_and_an_unknown_one_are_still_shown(
    tmp_path: Path,
) -> None:
    version = team_version(1, [*CORE, SECURITY], standings={"SECURITY": "REQUIRED"})
    views_of = version["perspectives"]
    assert isinstance(views_of, list)
    views_of.append(
        {
            **unit("DATA_SCIENCE", None, "SOMETHING_NEW", True, {}),
            "aspects": [unit("CHARTS", "CHART_ENGINEER", "OPTIONAL", False, {}), "broken"],
        }
    )
    transport = ScriptedTransport()
    expect_approval(transport, version)

    approved, journey = team_step(tmp_path, transport, ["2", "", "1"], version)

    assert approved
    lines = printed(journey).splitlines()
    assert "  [x] Security: The brief asks for it" in lines
    assert "  [x] data science: something new" in lines
    assert "      [ ] charts: Your choice" in lines
    assert "  5. [ ] charts" in lines
    transport.assert_done()


def test_security_is_switched_on_with_one_number_and_no_reason(tmp_path: Path) -> None:
    first = team_version(1)
    second = team_version(2, [*CORE, SECURITY])
    transport = ScriptedTransport()
    expect_edit(transport, second)
    expect_approval(transport, second)

    approved, journey = team_step(tmp_path, transport, ["2", "5", "1"], first)

    assert approved
    assert patches(transport) == [
        {
            "selected_agent_ids": [
                *PLATFORM,
                "REQUIREMENTS_ANALYST",
                "UX_RESEARCHER_USER_MODELER",
                DESIGNER,
                "SOFTWARE_ARCHITECT",
                "QA_TEST_ENGINEER",
                SECURITY,
                "ACCESSIBILITY_REVIEWER",
            ]
        }
    ]
    lines = printed(journey).splitlines()
    assert following(lines, "Perspectives and aspects you can switch on [ ] or off [x]:", 6) == [
        "Perspectives and aspects you can switch on [ ] or off [x]:",
        "  1. [ ] Web interface: Works in the browser, from phone to desktop.",
        "  2. [ ] Services and data: Data and logic that live on a server.",
        "  3. [ ] Mobile: Use on phones and tablets.",
        "  4. [ ] Connections to other systems: Data exchanged with outside services.",
        "  5. [ ] Security: Protects data and access: who may see and do what.",
    ]
    updated = lines.index("Perspectives updated (version 2).")
    assert "  [ ] Security: Your choice" in lines[:updated]
    assert lines[updated + 2] == "Perspectives (version 2)"
    assert "  [x] Security: Applied, your choice" in lines[updated:]
    assert (
        'Step "Perspectives" approved (version 2). Saved in .orchestwin/steps/team.json.' in lines
    )
    assert journey.versions["team"] == 2
    assert forbidden(printed(journey)) == []
    transport.assert_done()


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_contested_aspect_starts_off_and_is_switched_on_without_a_reason(
    tmp_path: Path, language: str
) -> None:
    first = team_version(1, MIXED, standings=STANDINGS, words=WORDS)
    second = team_version(2, [*MIXED, "BACKEND_ENGINEER"], standings=STANDINGS, words=WORDS)
    transport = ScriptedTransport()
    expect_edit(transport, second)
    expect_approval(transport, second)

    approved, journey = team_step(tmp_path, transport, ["2", "1", "1"], first, language=language)

    assert approved
    assert patches(transport) == [
        {
            "selected_agent_ids": [
                *PLATFORM,
                "REQUIREMENTS_ANALYST",
                "UX_RESEARCHER_USER_MODELER",
                DESIGNER,
                "SOFTWARE_ARCHITECT",
                "FRONTEND_ENGINEER",
                "BACKEND_ENGINEER",
                "MOBILE_ENGINEER",
                "QA_TEST_ENGINEER",
                "ACCESSIBILITY_REVIEWER",
            ]
        }
    ]
    lines = printed(journey).splitlines()
    expected = {
        "en": [
            "  1. [ ] Services and data: Data and logic that live on a server.",
            "  2. [x] Mobile: Use on phones and tablets.",
            "  3. [ ] Security: Protects data and access: who may see and do what.",
            "Perspectives updated (version 2).",
            "      [x] Services and data: The brief says two different things: you decide (asks "
            "for it with «api» in Technical constraints; rules it out with «senza server» in "
            "The idea)",
        ],
        "it": [
            "  1. [ ] Servizi e dati: Dati e funzioni che stanno su un server.",
            "  2. [x] Mobile: Uso su telefono e tablet.",
            "  3. [ ] Sicurezza: Protegge dati e accessi: chi può vedere e fare che cosa.",
            "Prospettive aggiornate (versione 2).",
            "      [x] Servizi e dati: Il brief dice due cose diverse: decidi tu (la chiede con "
            "«api» in Vincoli tecnici; la esclude con «senza server» in L'idea)",
        ],
    }
    assert [line for line in expected[language] if line not in lines] == []
    assert following(lines, expected[language][0], 3) == expected[language][:3]
    assert forbidden(printed(journey)) == []
    transport.assert_done()


def test_several_units_are_switched_at_once_on_and_off(tmp_path: Path) -> None:
    first = team_version(1, [*CORE, "MOBILE_ENGINEER", SECURITY])
    second = team_version(2, [*CORE, "BACKEND_ENGINEER"])
    transport = ScriptedTransport()
    expect_edit(transport, second)
    expect_approval(transport, second)

    approved, journey = team_step(tmp_path, transport, ["2", "5, 3 2 5", "1"], first)

    assert approved
    assert patches(transport) == [
        {
            "selected_agent_ids": [
                *PLATFORM,
                "REQUIREMENTS_ANALYST",
                "UX_RESEARCHER_USER_MODELER",
                DESIGNER,
                "SOFTWARE_ARCHITECT",
                "BACKEND_ENGINEER",
                "QA_TEST_ENGINEER",
                "ACCESSIBILITY_REVIEWER",
            ]
        }
    ]
    lines = printed(journey).splitlines()
    assert "  3. [x] Mobile: Use on phones and tablets." in lines
    assert "  5. [x] Security: Protects data and access: who may see and do what." in lines
    transport.assert_done()


def test_a_change_the_studio_finds_equal_keeps_the_version(tmp_path: Path) -> None:
    version = team_version(1)
    transport = ScriptedTransport()
    unchanged = {"status": "UNCHANGED", "version": version, "issues": [], "events": []}
    expect_edit(transport, None, status=200, body=unchanged)
    expect_approval(transport, version)

    approved, journey = team_step(tmp_path, transport, ["2", "2", "1"], version)

    assert approved
    lines = printed(journey).splitlines()
    assert "The perspectives do not change." in lines
    assert "Perspectives updated (version 1)." not in lines
    assert journey.versions["team"] == 1
    transport.assert_done()


def test_numbers_that_are_not_valid_are_asked_again(tmp_path: Path) -> None:
    version = team_version(1)
    transport = ScriptedTransport()
    expect_approval(transport, version)

    approved, journey = team_step(tmp_path, transport, ["2", "99", "two", "", "1"], version)

    assert approved
    assert patches(transport) == []
    output = printed(journey)
    assert output.count("Write only numbers from 1 to 5, separated by spaces.") == 2
    assert "The perspectives do not change." in output.splitlines()
    transport.assert_done()


REFUSALS = {
    "en": [
        "Software engineering: it cannot be switched off in this project.",
        "Connections to other systems: it cannot be switched on, because the brief rules it out.",
        "Security: this Studio asks for a reason to switch it on, so switch it on in the web "
        "Studio.",
        "Mobile: the change is not accepted (BRAND_NEW_ISSUE).",
    ],
    "it": [
        "Ingegneria del software: non si può togliere in questo progetto.",
        "Collegamenti con altri sistemi: non si può attivare, perché il brief la esclude.",
        "Sicurezza: per attivarla questo Studio chiede una motivazione, quindi attivala nello "
        "Studio web.",
        "Mobile: il cambio non è accettato (BRAND_NEW_ISSUE).",
    ],
}


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_change_refused_by_the_studio_names_the_perspectives(
    tmp_path: Path, language: str
) -> None:
    version = team_version(1)
    refusal = {
        "status": "REJECTED",
        "version": None,
        "issues": [
            {"code": "MANDATORY_AGENT_MISSING", "agent_id": "QA_TEST_ENGINEER"},
            {"code": "AGENT_NOT_SELECTABLE", "agent_id": "INTEGRATION_ENGINEER"},
            {"code": "RATIONALE_REQUIRED", "agent_id": SECURITY},
            {"code": "BRAND_NEW_ISSUE", "agent_id": "MOBILE_ENGINEER"},
        ],
        "events": [],
    }
    transport = ScriptedTransport()
    expect_edit(transport, None, status=422, body=refusal)
    expect_approval(transport, version)

    approved, journey = team_step(
        tmp_path, transport, ["2", "4 5", "1"], version, language=language
    )

    assert approved
    assert patches(transport) == [
        {
            "selected_agent_ids": [
                *PLATFORM,
                "REQUIREMENTS_ANALYST",
                "UX_RESEARCHER_USER_MODELER",
                DESIGNER,
                "SOFTWARE_ARCHITECT",
                "QA_TEST_ENGINEER",
                SECURITY,
                "ACCESSIBILITY_REVIEWER",
                "INTEGRATION_ENGINEER",
            ]
        }
    ]
    lines = printed(journey).splitlines()
    expected = REFUSALS[language]
    assert following(lines, expected[0], len(expected)) == expected
    assert journey.versions["team"] == 1
    transport.assert_done()


def test_when_nothing_can_be_switched_one_sentence_says_so(tmp_path: Path) -> None:
    standings = {
        "WEB": "REQUIRED",
        "SERVICES": "EXCLUDED",
        "MOBILE": "EXCLUDED",
        "INTEGRATIONS": "REQUIRED",
        "SECURITY": "REQUIRED",
    }
    specialists = [*CORE, "FRONTEND_ENGINEER", "INTEGRATION_ENGINEER", SECURITY]
    version = team_version(1, specialists, standings=standings)
    transport = ScriptedTransport()
    expect_approval(transport, version)

    approved, journey = team_step(tmp_path, transport, ["2", "1"], version)

    assert approved
    assert patches(transport) == []
    lines = printed(journey).splitlines()
    assert "In this project no perspective and no aspect can be switched on or off." in lines
    assert "      [ ] Services and data: The brief rules it out" in lines
    transport.assert_done()


OUTDATED = {
    "en": "This Studio does not give the perspectives yet: update it to see and change them. "
    "You can still approve this step.",
    "it": "Questo Studio non dà ancora le prospettive: aggiornalo per vederle e cambiarle. "
    "Puoi comunque approvare questo passo.",
}


CHOICES_WITHOUT_CHANGE = {
    "en": ["  1. Approve them and go on", "  2. Stop here"],
    "it": ["  1. Le approvo e vado avanti", "  2. Mi fermo qui"],
}


@pytest.mark.parametrize("language", ["en", "it"])
def test_an_older_studio_without_perspectives_can_still_be_approved(
    tmp_path: Path, language: str
) -> None:
    version = team_version(1, perspectives=False)
    transport = ScriptedTransport()
    expect_approval(transport, version)

    approved, journey = team_step(tmp_path, transport, ["3", "1"], version, language=language)

    assert approved
    assert patches(transport) == []
    output = printed(journey)
    lines = output.splitlines()
    assert lines[1:3] == NO_SIGNALS[language][:2]
    assert lines[3:5] == [OUTDATED[language], NO_SIGNALS[language][11]]
    assert lines[5:7] == CHOICES_WITHOUT_CHANGE[language]
    assert lines.count(OUTDATED[language]) == 1
    assert APPROVED[language] in lines
    assert [agent for agent in team_api.AGENTS if agent in output] == []
    assert forbidden(output) == []
    transport.assert_done()


def test_an_older_studio_without_perspectives_can_be_left_for_later(tmp_path: Path) -> None:
    version = team_version(1, perspectives=False)
    transport = ScriptedTransport()

    approved, journey = team_step(tmp_path, transport, ["2"], version)

    assert not approved
    assert "The perspectives stay waiting for your approval." in printed(journey)
    assert transport.sent == []


@pytest.mark.parametrize("language", ["en", "it"])
def test_no_word_of_a_team_is_used_in_step_two(tmp_path: Path, language: str) -> None:
    first = team_version(1, MIXED, standings=STANDINGS, words=WORDS)
    second = team_version(2, [*MIXED, "BACKEND_ENGINEER", SECURITY], standings=STANDINGS)
    codes = [*team_api.EDIT_ISSUES, "OTHER"]
    agents = [
        "QA_TEST_ENGINEER",
        "BACKEND_ENGINEER",
        "MOBILE_ENGINEER",
        SECURITY,
        DESIGNER,
        "INTEGRATION_ENGINEER",
        "FRONTEND_ENGINEER",
    ]
    refusal = {
        "status": "REJECTED",
        "version": None,
        "issues": [
            {"code": code, "agent_id": agent} for code, agent in zip(codes, agents, strict=True)
        ],
        "events": [],
    }
    transport = ScriptedTransport()
    expect_edit(transport, None, status=422, body=refusal)
    expect_edit(transport, second)
    expect_approval(transport, second)
    answers = ["2", "1", "2", "1 3", "1"]

    approved, journey = team_step(tmp_path, transport, answers, first, language=language)

    assert approved
    output = printed(journey)
    assert len(output.splitlines()) > 50
    assert forbidden(output) == []
    assert [agent for agent in team_api.AGENTS if agent in output] == []
    transport.assert_done()


def proposed_team(studio: FakeStudio, tmp_path: Path, language: str) -> Mapping[str, object]:
    run = ut(tmp_path, *UNTIL_TEAM, answers=[*BEFORE_TEAM, "3"], language=language)
    assert run.status == 0, run.errors
    team = fake_project(studio, tmp_path).current("team")
    assert team is not None
    return team


@pytest.mark.parametrize(
    ("language", "updated", "line", "approved"),
    [
        (
            "en",
            "Perspectives updated (version 2).",
            "  [x] Security: Applied, your choice",
            'Step "Perspectives" approved (version 2). Saved in .orchestwin/steps/team.json.',
        ),
        (
            "it",
            "Prospettive aggiornate (versione 2).",
            "  [x] Sicurezza: Applicata, a tua scelta",
            'Passo "Prospettive" approvato (versione 2). Salvato in .orchestwin/steps/team.json.',
        ),
    ],
)
def test_security_is_switched_on_and_approved_in_the_studio(
    tmp_path: Path, language: str, updated: str, line: str, approved: str
) -> None:
    with FakeStudio(language=language) as studio:
        sign_in(studio, tmp_path)
        team = proposed_team(studio, tmp_path, language)
        units = team_api.switchable(team_api.perspectives(team) or [])
        number = next(
            index for index, item in enumerate(units, start=1) if item["agent_id"] == SECURITY
        )
        chosen = team_api.selected(team)

        run = ut(tmp_path, *UNTIL_TEAM, answers=["2", str(number), "1"], language=language)

        assert run.status == 0, run.errors
        assert posted(studio, "/team-proposals/current") == [
            {"selected_agent_ids": team_api.ordered([*chosen, SECURITY])}
        ]
        current = fake_project(studio, tmp_path).current("team")
        assert current["version_number"] == 2
        assert SECURITY in current["selected_agent_ids"]
        assert saved_step(tmp_path, "team")["version"] == current
    lines = run.output.splitlines()
    assert updated in lines
    assert line in lines
    assert approved in lines
    assert [agent for agent in team_api.AGENTS if agent in run.output] == []
    assert forbidden(run.output) == []


def test_a_brief_that_contradicts_itself_goes_on_and_the_aspect_can_be_switched_on(
    tmp_path: Path,
) -> None:
    idea = "Una app con database ma senza backend."
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        first = ut(tmp_path, *UNTIL_TEAM, answers=["1", idea, "", NAME, *brief_answers(), "3"])
        team = fake_project(studio, tmp_path).current("team")
        units = team_api.switchable(team_api.perspectives(team) or [])
        number = next(
            index
            for index, item in enumerate(units, start=1)
            if item["agent_id"] == "BACKEND_ENGINEER"
        )

        second = ut(tmp_path, *UNTIL_TEAM, answers=["2", str(number), "1"])

        assert (first.status, second.status) == (0, 0), first.errors + second.errors
        assert posted(studio, "/team-proposals/current") == [
            {"selected_agent_ids": team_api.ordered([*team_api.selected(team), "BACKEND_ENGINEER"])}
        ]
        current = fake_project(studio, tmp_path).current("team")
        assert current["version_number"] == 2
        assert saved_step(tmp_path, "team")["version"] == current
    contested = (
        "      [ ] Services and data: The brief says two different things: you decide (asks for it "
        "with «database» in The idea; rules it out with «senza backend» in The idea)"
    )
    assert contested in first.output.splitlines()
    assert contested.replace("[ ]", "[x]", 1) in second.output.splitlines()
    assert first.errors == ""
    assert forbidden(first.output[first.output.index("Step 2 of 4") :]) == []


def test_a_failed_team_proposal_is_tried_again_after_asking(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        studio.fail_next("POST", PROPOSALS, status=502, body={"detail": "invalid_team_proposal"})

        run = ut(tmp_path, *UNTIL_TEAM, answers=[*BEFORE_TEAM, "y", "1"])

        assert run.status == 0, run.errors
        assert fake_project(studio, tmp_path).approved("team")
    assert (
        "Preparing the perspectives: the model did not give a valid result "
        "(invalid_team_proposal)." in run.output
    )
    assert "Try once more? It is a new generation, about 0.02-0.03 USD. [Y/n]" in run.output


def test_a_failed_team_proposal_without_a_second_try(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        studio.fail_next("POST", PROPOSALS, status=502, body={"detail": "invalid_team_proposal"})

        run = ut(tmp_path, *UNTIL_TEAM, answers=[*BEFORE_TEAM, "n"])

        assert run.status == 1
        assert saved_stages(tmp_path) == ["brief"]
    assert (
        "Preparing the perspectives: the generation did not succeed (invalid_team_proposal)."
        in run.errors
    )


def test_a_spending_ceiling_reached_names_the_ceiling(tmp_path: Path) -> None:
    with FakeStudio(language="en", budget_usd=0.1) as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, answers=[*start(), *brief_answers()])

        assert run.status == 5
        assert saved_stages(tmp_path) == ["brief"]
        assert fake_project(studio, tmp_path).current("team") is None
    assert "The estimate is above the credit left" in run.output
    assert (
        "The Studio reached its overall spending ceiling (0.10 USD): the generation did not "
        "start. Whoever runs the Studio can raise it" in run.errors
    )


def cause(code: str, fields: Sequence[str] = (), terms: Sequence[str] = ()) -> dict[str, object]:
    return {"code": code, "evidence": {"fields": list(fields), "terms": list(terms)}}


def conflict(
    agent: str, required: list[dict[str, object]], excluded: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "code": "CONTRADICTORY_ROLE_SIGNALS",
        "agent_id": agent,
        "mandatory_reasons": required,
        "impossible_reasons": excluded,
    }


SERVERLESS = conflict(
    "BACKEND_ENGINEER",
    required=[cause("BACKEND_DELIVERY_SIGNAL", ["budget"], ["server"])],
    excluded=[
        cause(
            "EXPLICIT_SCOPE_EXCLUSION", ["description", "technical_constraints"], ["senza server"]
        )
    ],
)


def blocked_run(tmp_path: Path, *issues: Mapping[str, object], language: str = "en") -> Run:
    body = {"status": "BLOCKED_BY_CONSTRAINTS", "version": None, "issues": list(issues)}
    with FakeStudio(language=language) as studio:
        sign_in(studio, tmp_path)
        studio.fail_next("POST", PROPOSALS, status=409, body=body)
        return ut(tmp_path, *UNTIL_TEAM, answers=BEFORE_TEAM, language=language)


def test_an_older_studio_that_blocks_names_the_words_of_the_brief(tmp_path: Path) -> None:
    run = blocked_run(tmp_path, SERVERLESS)

    assert run.status == 1
    assert (
        "The perspectives cannot be prepared: the brief both asks for and rules out Services "
        "and data. Services and data: the brief rules it out («senza server» in The idea, "
        "Technical constraints) and also asks for it («server» in Budget). Correct the brief in "
        "the web Studio (step Brief, «Edit the brief yourself»), then launch `ut init` again."
        in run.errors.splitlines()
    )
    assert saved_stages(tmp_path) == ["brief"]
    assert forbidden(run.errors) == []


def test_an_older_studio_that_blocks_says_in_italian_where_to_correct_the_brief(
    tmp_path: Path,
) -> None:
    run = blocked_run(tmp_path, SERVERLESS, language="it")

    assert run.status == 1
    assert (
        "Le prospettive non si possono preparare: il brief chiede ed esclude insieme Servizi e "
        "dati. Servizi e dati: il brief la esclude («senza server» in L'idea, Vincoli tecnici) e "
        "insieme la chiede («server» in Budget). Correggi il brief nello Studio web (passo "
        "Brief, «Modifica il brief di persona»), poi rilancia `ut init`." in run.errors.splitlines()
    )
    assert forbidden(run.errors) == []


def test_a_blocked_unit_without_words_of_the_brief_is_only_named(tmp_path: Path) -> None:
    mobile = conflict(
        "MOBILE_ENGINEER",
        required=[cause("MOBILE_DELIVERY_SIGNAL"), cause("MOBILE_DELIVERY_SIGNAL")],
        excluded=[cause("CATALOG_MODE_INCOMPATIBLE"), {"code": "BRAND_NEW_RULE"}],
    )

    run = blocked_run(tmp_path, mobile, conflict("BACKEND_ENGINEER", [], []))

    assert run.status == 1
    assert (
        "The perspectives cannot be prepared: the brief both asks for and rules out Mobile, "
        "Services and data. Correct the brief in the web Studio (step Brief, «Edit the brief "
        "yourself»), then launch `ut init` again." in run.errors.splitlines()
    )


def test_the_words_of_several_reasons_and_units_are_merged_in_order(tmp_path: Path) -> None:
    backend = conflict(
        "BACKEND_ENGINEER",
        required=[
            cause("BACKEND_DELIVERY_SIGNAL", ["description", "budget"], ["database", "server"]),
            cause("EXTERNAL_INTEGRATION_SIGNAL", ["budget", "risks"], ["server", "api"]),
        ],
        excluded=[cause("EXPLICIT_SCOPE_EXCLUSION", ["technical_constraints"], ["senza server"])],
    )
    mobile = conflict(
        "MOBILE_ENGINEER",
        required=[cause("MOBILE_DELIVERY_SIGNAL", ["description"], ["iphone"])],
        excluded=[cause("EXPLICIT_SCOPE_EXCLUSION", ["technical_constraints"], ["web only"])],
    )

    run = blocked_run(tmp_path, backend, mobile)

    assert run.status == 1
    assert (
        "The perspectives cannot be prepared: the brief both asks for and rules out Services "
        "and data, Mobile. Services and data: the brief rules it out («senza server» in "
        "Technical constraints) and also asks for it («database», «server», «api» in The idea, "
        "Budget, Risks). Mobile: the brief rules it out («web only» in Technical constraints) "
        "and also asks for it («iphone» in The idea). Correct the brief in the web Studio (step "
        "Brief, «Edit the brief yourself»), then launch `ut init` again." in run.errors.splitlines()
    )


def test_an_answers_file_can_stop_at_the_perspectives(tmp_path: Path) -> None:
    script = tmp_path / "answers.json"
    script.write_text(json.dumps({"name": NAME, "idea": IDEA, "team": "STOP"}), encoding="utf-8")
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, "--answers", str(script), yes=True)

        assert run.status == 0, run.errors
        assert saved_stages(tmp_path) == ["brief"]
        assert fake_project(studio, tmp_path).current("team")["version_number"] == 1
    assert "The perspectives stay waiting for your approval." in run.output


@pytest.mark.parametrize(("specialists", "noted"), [(WITHOUT_DESIGNER, True), (CORE, False)])
def test_approving_the_perspectives_remembers_whether_the_designer_is_there(
    tmp_path: Path, specialists: list[str], noted: bool
) -> None:
    version = team_version(1, specialists)
    transport = ScriptedTransport()
    expect_approval(transport, version)

    approved, journey = team_step(tmp_path, transport, ["1"], version)

    assert approved
    assert journey.designer_note is noted
    assert NOTE not in printed(journey)
    line = (
        f"  [ ] User experience (UX): {ALWAYS_MISSING['en']}"
        if noted
        else "  [x] User experience (UX): Always applied"
    )
    assert line in printed(journey).splitlines()
    transport.assert_done()


ACCESSIBILITY_MISSING = {
    "en": [
        "  [x] User experience (UX): Always applied",
        f"  [ ] Accessibility: {ALWAYS_MISSING['en']}",
        "  [x] Software engineering: Always applied",
    ],
    "it": [
        "  [x] Esperienza d'uso (UX): Sempre applicata",
        f"  [ ] Accessibilità: {ALWAYS_MISSING['it']}",
        "  [x] Ingegneria del software: Sempre applicata",
    ],
}


@pytest.mark.parametrize("language", ["en", "it"])
def test_an_always_applied_perspective_missing_from_an_older_version_is_prepared_again_in_the_web(
    tmp_path: Path, language: str
) -> None:
    older = [agent for agent in CORE if agent != "ACCESSIBILITY_REVIEWER"]
    version = team_version(1, older)
    transport = ScriptedTransport()
    expect_approval(transport, version)

    approved, journey = team_step(tmp_path, transport, ["1"], version, language=language)

    assert approved
    output = printed(journey)
    expected = ACCESSIBILITY_MISSING[language]
    assert following(output.splitlines(), expected[0], len(expected)) == expected
    assert output.count(ALWAYS_MISSING[language]) == 1
    assert forbidden(output) == []
    transport.assert_done()


def test_a_failed_team_proposal_ends_its_progress_as_not_completed(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect(
        "POST", f"{BASE}/team-proposals", status=502, body={"detail": "invalid_team_proposal"}
    )
    transport.expect(
        "GET",
        f"{API}/model-runtime/budget",
        status=503,
        body={"detail": {"code": "GENERATION_BUDGET_NOT_CONFIGURED"}},
    )
    store_session(tmp_path)
    folder = link_folder(tmp_path / "project")
    bundle = terminal(tmp_path, transport=transport, answers=["n"])
    context = command_context(bundle.environment)
    journey = Journey(context, context.client(), folder, script=None, until=None, idea=None)
    state = init_team.TeamState(
        approved=False, readiness="TEAM_PROPOSAL_REQUIRED", version=None, gate=None
    )

    with pytest.raises(CliError) as caught:
        init_team.run(journey, state)

    assert caught.value.code == "GENERATION_FAILED"
    lines = printed(journey).splitlines()
    ended = lines.index("Preparing the perspectives: not completed after 0 s.")
    assert lines[ended - 1] == "Preparing the perspectives..."
    assert lines[ended + 1] == (
        "Preparing the perspectives: the model did not give a valid result (invalid_team_proposal)."
    )
    assert "Preparing the perspectives: done in" not in printed(journey)
    transport.assert_done()


def expect_approved_path(transport: ScriptedTransport, team: Mapping[str, object]) -> None:
    brief = {"id": "brief-1", "version_number": 1, "content_hash": "brief-hash", "brief": {}}
    snapshot = {"id": "snapshot-1", "version_number": 1, "content_hash": "snapshot-hash"}
    requirements = {"id": "spec-1", "version_number": 1, "content_hash": "spec-hash"}
    transport.expect(
        "GET", BASE, body={"id": PROJECT_ID, "display_name": NAME, "current_stage": "DESIGN"}
    )
    transport.expect("GET", f"{BASE}/brief-versions/current", body=brief)
    transport.expect("GET", f"{BASE}/gates/project-brief/current", body=gate(brief, "APPROVED"))
    transport.expect("GET", f"{BASE}/team-proposals/current", body=team)
    transport.expect("GET", f"{BASE}/readiness", body={"status": "READY_FOR_MAIN_WORKFLOW"})
    transport.expect("GET", f"{BASE}/gates/agent-team/current", body=gate(team, "APPROVED"))
    transport.expect(
        "GET",
        f"{BASE}/user-modeling/readiness",
        body={
            "workflow_state": "READY_FOR_REQUIREMENTS_DEFINITION",
            "approved_current_snapshot": True,
            "snapshot_version_number": 1,
        },
    )
    transport.expect("GET", f"{BASE}/user-modeling/snapshots/current", body=snapshot)
    transport.expect("GET", f"{BASE}/user-modeling/gate", body=gate(snapshot, "APPROVED"))
    transport.expect(
        "GET",
        f"{BASE}/requirements/readiness",
        body={
            "status": "READY_FOR_DESIGN_EXPLORATION",
            "version": requirements,
            "gate": gate(requirements, "APPROVED"),
        },
    )
    transport.expect(
        "POST",
        f"{BASE}/knowledge-packages",
        status=409,
        body={"detail": {"code": "DESIGN_APPROVAL_REQUIRED"}},
    )


@pytest.mark.parametrize(("specialists", "noted"), [(WITHOUT_DESIGNER, True), (CORE, False)])
def test_perspectives_approved_before_without_the_designer_are_noted_once_at_the_end(
    tmp_path: Path, specialists: list[str], noted: bool
) -> None:
    store_session(tmp_path)
    link_folder(tmp_path / "project")
    transport = ScriptedTransport()
    expect_approved_path(transport, team_version(1, specialists))

    run = run_ut(["init"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    assert run.output.count(NOTE) == (1 if noted else 0)
    lines = run.output.splitlines()
    if noted:
        design = next(index for index, line in enumerate(lines) if "`ut design`: it" in line)
        assert lines[design + 1].startswith(NOTE)
        assert lines[design + 1].endswith(
            "Prepare the perspectives again and approve them in the web Studio."
        )
        assert forbidden(lines[design + 1]) == []
    transport.assert_done()


def test_a_contradiction_is_written_only_with_something_to_say_on_both_sides(
    tmp_path: Path,
) -> None:
    store_session(tmp_path)
    folder = link_folder(tmp_path / "project")
    transport = ScriptedTransport()
    context = command_context(terminal(tmp_path, transport=transport).environment)
    journey = Journey(context, context.client(), folder, script=None, until=None, idea=None)
    words_only = conflict(
        "MOBILE_ENGINEER",
        required=[cause("MOBILE_DELIVERY_SIGNAL", [], ["iphone"])],
        excluded=[cause("EXPLICIT_SCOPE_EXCLUSION", ["delivery_channel"], ["web only", " "])],
    )
    one_sided = conflict("MOBILE_ENGINEER", [], [cause("CATALOG_MODE_INCOMPATIBLE")])
    broken = {
        "agent_id": "MOBILE_ENGINEER",
        "mandatory_reasons": "MOBILE_DELIVERY_SIGNAL",
        "impossible_reasons": [cause("EXPLICIT_SCOPE_EXCLUSION", ["budget"], ["web only"])],
    }
    unknown = conflict(
        "CHART_ENGINEER",
        required=[cause("CHART_SIGNAL", ["goals"], ["grafici"])],
        excluded=[cause("EXPLICIT_SCOPE_EXCLUSION", ["goals"], ["senza grafici"])],
    )

    assert init_team.contradiction(journey, words_only) == (
        "Mobile: the brief rules it out («web only» in delivery channel) and also asks for it "
        "(«iphone»)."
    )
    assert init_team.contradiction(journey, one_sided) is None
    assert init_team.contradiction(journey, broken) is None
    assert init_team.contradiction(journey, unknown) == (
        "chart engineer: the brief rules it out («senza grafici» in Goals) and also asks for it "
        "(«grafici» in Goals)."
    )
    transport.assert_done()
