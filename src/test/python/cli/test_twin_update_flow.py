from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from orchestwin.cli import folder as knowledge
from orchestwin.cli.flows import twin_update
from orchestwin.cli.http import UrlTransport
from orchestwin.cli.messages import known, text
from orchestwin.cli.project import ProjectFolder, read_json

from .support.fake_studio import FakeProject, FakeStudio, RecordedRequest
from .support.folders import valid_archive
from .support.terminal import TEST_PASSWORD, Run, link_folder, run_ut

EMAIL = "owner@example.com"
WIDE = {"COLUMNS": "200"}
UPDATES = "/projects/{project_id}/user-twins/{twin_id}/updates"
DECISION = "/projects/{project_id}/twin-updates/{update_id}/decision"
LEARNING = "/projects/{project_id}/twin-learning"
PUBLISH = "/projects/{project_id}/knowledge-packages"
EDITED = "People split the bill at the table, phone in hand."


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


def say(key: str, language: str = "en", /, **values: object) -> str:
    assert known(key), key
    return text(key, language, **values)


def names(project: FakeProject) -> list[str]:
    return [str(entry["twin_name"]) for entry in project.twin_learning()]


def posted(studio: FakeStudio, suffix: str) -> list[RecordedRequest]:
    return [
        request
        for request in studio.requests
        if request.method == "POST" and request.path.endswith(suffix)
    ]


def asked_budget(studio: FakeStudio) -> bool:
    return any(request.path.endswith("/model-runtime/budget") for request in studio.requests)


def decisions(studio: FakeStudio) -> list[dict[str, object]]:
    return [json.loads(request.body) for request in posted(studio, "/decision")]


def heading(line: str) -> list[str]:
    return [line, "=" * len(line)]


def progress(label: str, elapsed: str, language: str = "en") -> list[str]:
    return [
        say("common.progress_started", language, label=label),
        say("common.progress_done", language, label=label, elapsed=elapsed),
    ]


def publication(version: int, language: str = "en") -> list[str]:
    publishing = say("common.folder_publishing", language)
    downloading = say("common.folder_downloading", language)
    return [
        *progress(publishing, "0 s", language),
        *progress(downloading, "0 s", language),
        say("twins.folder_updated", language, version=version),
    ]


def proposed(update: Mapping[str, object]) -> list[Mapping[str, object]]:
    observations = update["observations"]
    assert isinstance(observations, list)
    return observations


def details(item: Mapping[str, object], about: str, language: str = "en") -> list[str]:
    return [
        "  " + say("twins.update_basis", language, basis=item["basis"]),
        "  " + say("twins.update_about", language, about=about),
    ]


def learned_folder(tmp_path: Path) -> dict[str, object]:
    document = read_json(
        tmp_path / "project" / "orchestwin" / "twins" / "feedback" / "learned.json"
    )
    assert isinstance(document, dict)
    return document


def test_every_twin_with_new_critiques_gets_a_proposal_reviewed_one_by_one(
    tmp_path: Path,
) -> None:
    with FakeStudio(language="en", twins=2) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        run = ut(tmp_path, "twins", "update", answers=["", "e", EDITED, "d", ""])
        updates = {str(item["twin_name"]): item for item in project.twin_updates()}
        entries = project.twin_learning()
        spent = studio.spent_microusd
        proposals = posted(studio, "/updates")
        sent = decisions(studio)
        assert studio.errors == []

    first, second = [str(entry["twin_name"]) for entry in entries]
    one, two = proposed(updates[first]), proposed(updates[second])
    question = say("twins.update_question") + " "
    requirement = say("twins.about_requirement_code", code="REQ-003")
    screen = say("twins.about_screen_code", code="SCR-001")
    assert (run.status, run.errors) == (0, "")
    assert run.output.splitlines() == [
        say("twins.update_to_generate", names=f"{first}, {second}"),
        say("costs.estimate", amount="0.20-0.50", minutes="2 min", remaining="60.00"),
        "",
        *progress(say("twins.update_label", name=first), "9 s"),
        "",
        *heading(say("twins.update_heading", name=first, label="1.0")),
        say("twins.update_material", changes=1, tests=0),
        say("twins.update_comment", name=first, comment=updates[first]["comment"]),
        say("twins.update_how"),
        "",
        say("twins.update_observation", number=1, count=2, statement=one[0]["statement"]),
        *details(one[0], requirement),
        question,
        "",
        say("twins.update_observation", number=2, count=2, statement=one[1]["statement"]),
        *details(one[1], screen),
        question,
        say("twins.update_edit") + " ",
        "",
        say("twins.update_approved", name=first, label="1.1", codes="OBS-001, OBS-002"),
        "",
        *progress(say("twins.update_label", name=second), "9 s"),
        "",
        *heading(say("twins.update_heading", name=second, label="1.0")),
        say("twins.update_material", changes=1, tests=0),
        say("twins.update_comment", name=second, comment=updates[second]["comment"]),
        say("twins.update_how"),
        "",
        say("twins.update_observation", number=1, count=1, statement=two[0]["statement"]),
        *details(two[0], f"{requirement}, {screen}"),
        question,
        "",
        say("twins.update_reason") + " ",
        "",
        say("twins.update_rejected", name=second, label="1.0"),
        "",
        say("twins.update_cost", amount="0.30"),
        "",
        *publication(1),
    ]
    assert [json.loads(request.body) for request in proposals] == [{"locale": "en-US"}] * 2
    assert all(request.headers.get("prefer") == "respond-async" for request in proposals)
    assert sent == [
        {
            "decision": "APPROVE",
            "kept": [{"index": 0, "statement": None}, {"index": 1, "statement": EDITED}],
            "reason": None,
        },
        {"decision": "REJECT", "kept": [], "reason": None},
    ]
    assert [item["statement"] for item in entries[0]["observations"]] == [
        one[0]["statement"],
        EDITED,
    ]
    assert (updates[first]["status"], updates[second]["status"]) == ("APPROVED", "REJECTED")
    assert spent == 300_000
    folder = learned_folder(tmp_path)
    assert folder["twins"][0]["label"] == "1.1"
    assert [item["code"] for item in folder["twins"][0]["observations"]] == ["OBS-001", "OBS-002"]


def test_a_named_twin_is_the_only_one_updated(tmp_path: Path) -> None:
    with FakeStudio(language="it", twins=2) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        twin = names(project)[1]
        run = ut(tmp_path, "--lang", "it", "twins", "update", "2", answers=["t"])
        entries = project.twin_learning()
        proposals = posted(studio, "/updates")

    assert run.status == 0
    assert run.output.splitlines()[:2] == [
        say("twins.update_to_generate", "it", names=twin),
        say("costs.estimate", "it", amount="0,10-0,25", minutes="1 min", remaining="60,00"),
    ]
    assert say("twins.update_approved", "it", name=twin, label="1.1", codes="OBS-001") in (
        run.output
    )
    assert [json.loads(request.body) for request in proposals] == [{"locale": "it-IT"}]
    assert [entry["label"] for entry in entries] == ["1.0", "1.1"]


def test_an_italian_folder_asks_the_studio_for_italian_from_an_english_terminal(
    tmp_path: Path,
) -> None:
    with FakeStudio(language="en", twins=1) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        twin = names(project)[0]
        folder = ProjectFolder(tmp_path / "project")
        folder.update_link(language="en")
        knowledge.unpack(valid_archive(), folder.knowledge)
        run = ut(tmp_path, "twins", "update", answers=["k", "k", "k"])
        proposals = posted(studio, "/updates")

    assert run.output.splitlines()[0] == say("twins.update_to_generate", names=twin)
    assert [json.loads(request.body) for request in proposals] == [{"locale": "it-IT"}]


def test_a_name_that_matches_no_twin_updates_nothing(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=2) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        run = ut(tmp_path, "twins", "update", "Zeta")

    assert run.status == 1
    assert run.errors == say("twins.no_match", value="Zeta") + "\n"
    assert say("twins.column_version") in run.output
    assert posted(studio, "/updates") == []


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_waiting_proposal_is_taken_up_again_without_spending(
    tmp_path: Path, language: str
) -> None:
    with FakeStudio(language=language, twins=1) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        waiting = project.seed_update(0)
        run = ut(tmp_path, "--lang", language, "twins", "update", answers=["k", "k"])
        entries = project.twin_learning()
        budget = asked_budget(studio)
        proposals = posted(studio, "/updates")
        spent = studio.spent_microusd

    twin = str(entries[0]["twin_name"])
    lines = run.output.splitlines()
    assert run.status == 0
    assert lines[:8] == [
        say("twins.update_resumed", language, name=twin),
        "",
        *heading(say("twins.update_heading", language, name=twin, label="1.0")),
        say("twins.update_material", language, changes=1, tests=0),
        say("twins.update_comment", language, name=twin, comment=waiting["comment"]),
        say("twins.update_how", language),
        "",
    ]
    assert say(
        "twins.update_approved", language, name=twin, label="1.1", codes="OBS-001, OBS-002"
    ) in (lines)
    assert say("twins.update_cost", language, amount="0.15") not in run.output
    assert (budget, proposals, spent) == (False, [], 0)


@pytest.mark.parametrize("language", ["en", "it"])
def test_twins_without_new_critiques_are_skipped_with_one_sentence_each(
    tmp_path: Path, language: str
) -> None:
    with FakeStudio(language=language, twins=2) as studio:
        project = seeded(tmp_path, studio)
        twins = names(project)
        run = ut(tmp_path, "--lang", language, "twins", "update")
        budget = asked_budget(studio)

    assert (run.status, run.errors) == (0, "")
    assert run.output.splitlines() == [
        say("twins.update_nothing_new", language, name=twins[0]),
        say("twins.update_nothing_new", language, name=twins[1]),
    ]
    assert (budget, posted(studio, "/updates")) == (False, [])


def test_without_a_model_nothing_is_asked_and_nothing_is_spent(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=2, hosted=False) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        run = ut(tmp_path, "twins", "update", answers=["k"])
        italian = ut(tmp_path, "--lang", "it", "twins", "update")
        budget = asked_budget(studio)

    assert (run.status, run.output) == (1, "")
    assert run.errors == say("twins.update_no_model") + "\n"
    assert (italian.status, italian.errors) == (1, say("twins.update_no_model", "it") + "\n")
    assert (budget, posted(studio, "/updates")) == (False, [])


def test_without_a_model_a_waiting_proposal_is_still_reviewed(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=2, hosted=False) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        project.seed_update(0, [{"statement": "People pay by phone."}])
        twins = names(project)
        run = ut(tmp_path, "twins", "update", answers=[""])
        entries = project.twin_learning()

    assert run.status == 1
    assert run.output.splitlines()[0] == say("twins.update_resumed", name=twins[0])
    assert run.errors == say("twins.update_no_model") + "\n"
    assert say("twins.update_approved", name=twins[0], label="1.1", codes="OBS-001") in run.output
    assert [entry["label"] for entry in entries] == ["1.1", "1.0"]
    assert posted(studio, "/updates") == []


@pytest.mark.parametrize(
    ("status", "body", "language"),
    [(404, {"detail": "Not Found"}, "it"), (405, {"detail": "Method Not Allowed"}, "en")],
)
def test_a_studio_older_than_the_twin_learning_says_so(
    tmp_path: Path, status: int, body: object, language: str
) -> None:
    with FakeStudio(language=language, twins=1) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        studio.fail_next("GET", LEARNING, status=status, body=body)
        run = ut(tmp_path, "--lang", language, "twins", "update")

    assert (run.status, run.output) == (1, "")
    assert run.errors == say("twins.update_unsupported", language) + "\n"
    assert posted(studio, "/updates") == []


@pytest.mark.parametrize(
    ("language", "amount", "remaining"),
    [("en", "0.30-0.75", "60.00"), ("it", "0,30-0,75", "60,00")],
)
def test_the_spending_question_can_be_refused(
    tmp_path: Path, language: str, amount: str, remaining: str
) -> None:
    with FakeStudio(language=language, twins=3) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        twins = names(project)
        run = ut(tmp_path, "--lang", language, "twins", "update", answers=["n"])
        spent = studio.spent_microusd

    confirm = say("costs.confirm", language)
    assert run.status == 5
    assert run.output.splitlines() == [
        say("twins.update_to_generate", language, names=", ".join(twins)),
        say("costs.estimate", language, amount=amount, minutes="3 min", remaining=remaining),
        f"{confirm} {say('common.yes_no_default_yes', language)} ",
    ]
    assert run.errors == say("errors.SPENDING_REFUSED", language) + "\n"
    assert (posted(studio, "/updates"), spent) == ([], 0)


def test_a_refused_spending_still_reviews_the_waiting_proposal(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=4) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        project.seed_update(0, [{"statement": "People pay by phone."}])
        twins = names(project)
        run = ut(tmp_path, "twins", "update", answers=["n", ""])
        entries = project.twin_learning()

    assert run.status == 5
    assert run.errors == say("errors.SPENDING_REFUSED") + "\n"
    assert say("twins.update_approved", name=twins[0], label="1.1", codes="OBS-001") in run.output
    assert [entry["label"] for entry in entries] == ["1.1", "1.0", "1.0", "1.0"]
    assert posted(studio, "/updates") == []
    assert say("twins.folder_updated", version=1) in run.output


def test_yes_skips_only_the_spending_question(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=3) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        twins = names(project)
        run = ut(tmp_path, "--yes", "twins", "update", answers=["", "", "d", ""])
        updates = {str(item["twin_name"]): item for item in project.twin_updates()}

    lines = run.output.splitlines()
    assert (run.status, run.errors) == (0, "")
    assert lines[:3] == [
        say("twins.update_to_generate", names=", ".join(twins)),
        say("costs.estimate", amount="0.30-0.75", minutes="3 min", remaining="60.00"),
        say("costs.assumed"),
    ]
    assert lines.count(say("twins.update_question") + " ") == 3
    assert say("twins.update_empty", name=twins[2]) in lines
    assert [updates[name]["status"] for name in twins] == ["APPROVED", "REJECTED", "EMPTY"]
    assert say("twins.update_cost", amount="0.45") in lines


@pytest.mark.parametrize(
    ("language", "answers"),
    [
        ("en", ["k", "t", "e", "Changed one.", "c", "", "d", "s"]),
        ("it", ["keep", "TIENI", "edit", "Changed one.", "Correggi", "", "drop", "Scarta"]),
    ],
)
def test_each_answer_keeps_edits_or_drops_in_both_languages(
    tmp_path: Path, language: str, answers: list[str]
) -> None:
    statements = [f"Observation number {number}." for number in range(6)]
    with FakeStudio(language=language, twins=1) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        project.seed_update(0, [{"statement": statement} for statement in statements])
        run = ut(tmp_path, "--lang", language, "twins", "update", answers=answers)
        entries = project.twin_learning()
        sent = decisions(studio)

    assert (run.status, run.errors) == (0, "")
    assert run.output.count(say("twins.update_question", language)) == 6
    assert sent == [
        {
            "decision": "APPROVE",
            "kept": [
                {"index": 0, "statement": None},
                {"index": 1, "statement": None},
                {"index": 2, "statement": "Changed one."},
                {"index": 3, "statement": None},
            ],
            "reason": None,
        }
    ]
    assert [item["statement"] for item in entries[0]["observations"]] == [
        statements[0],
        statements[1],
        "Changed one.",
        statements[3],
    ]


@pytest.mark.parametrize("language", ["en", "it"])
def test_an_answer_or_a_reason_that_cannot_be_used_is_asked_again(
    tmp_path: Path, language: str
) -> None:
    answers = ["yes", "maybe", "d", "z" * 301, "Not true here."]
    with FakeStudio(language=language, twins=1) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        project.seed_update(0, [{"statement": "People pay by phone."}])
        run = ut(tmp_path, "--lang", language, "twins", "update", answers=answers)
        sent = decisions(studio)

    assert run.status == 0
    assert run.output.count(say("twins.update_answer_invalid", language)) == 2
    assert run.output.count(say("twins.update_reason_too_long", language, limit=300)) == 1
    assert sent == [{"decision": "REJECT", "kept": [], "reason": "Not true here."}]


@pytest.mark.parametrize("language", ["en", "it"])
def test_an_edit_that_is_too_long_is_asked_again(tmp_path: Path, language: str) -> None:
    long = "word " * 90
    with FakeStudio(language=language, twins=1) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        project.seed_update(0, [{"statement": "People pay by phone."}])
        run = ut(
            tmp_path,
            "--lang",
            language,
            "twins",
            "update",
            answers=["e", long, "People pay by card."],
        )
        sent = decisions(studio)

    assert run.status == 0
    assert say("twins.update_edit_too_long", language, limit=400) in run.output
    assert sent[0]["kept"] == [{"index": 0, "statement": "People pay by card."}]


def test_answers_that_can_never_be_used_leave_the_proposal_waiting(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=1) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        project.seed_update(0, [{"statement": "People pay by phone."}])
        twin = names(project)[0]
        run = ut(tmp_path, "twins", "update", answers=["?"] * 5)
        statuses = [item["status"] for item in project.twin_updates()]

    assert run.status == 1
    assert run.output.count(say("twins.update_answer_invalid")) == 5
    assert run.errors == say("twins.update_left_pending", name=twin) + "\n"
    assert (statuses, decisions(studio)) == (["PROPOSED"], [])


@pytest.mark.parametrize(
    ("language", "answers", "reason"),
    [
        ("en", ["d", "d", "The tables are outside."], "The tables are outside."),
        ("it", ["s", "scarta", "   "], None),
    ],
)
def test_dropping_every_observation_rejects_the_proposal(
    tmp_path: Path, language: str, answers: list[str], reason: str | None
) -> None:
    with FakeStudio(language=language, twins=1) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        project.seed_update(0)
        twin = names(project)[0]
        run = ut(tmp_path, "--lang", language, "twins", "update", answers=answers)
        updates = project.twin_updates()
        entries = project.twin_learning()

    assert (run.status, run.errors) == (0, "")
    assert say("twins.update_reason", language) + " " in run.output.splitlines()
    assert say("twins.update_rejected", language, name=twin, label="1.0") in run.output
    assert updates[0]["status"] == "REJECTED"
    assert updates[0]["decision"]["reason"] == reason
    assert entries[0]["observations"] == []
    assert say("twins.folder_updated", language, version=1) in run.output


@pytest.mark.parametrize(("language", "amount"), [("en", "0.15"), ("it", "0,15")])
def test_an_empty_proposal_needs_no_decision(tmp_path: Path, language: str, amount: str) -> None:
    with FakeStudio(language=language, twins=3) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        twin = names(project)[2]
        run = ut(tmp_path, "--lang", language, "twins", "update", "3")
        updates = project.twin_updates()
        publications = posted(studio, "/knowledge-packages")

    lines = run.output.splitlines()
    assert (run.status, run.errors) == (0, "")
    assert lines[-3:] == [
        say("twins.update_empty", language, name=twin),
        "",
        say("twins.update_cost", language, amount=amount),
    ]
    assert say("twins.update_question", language) not in run.output
    assert [item["status"] for item in updates] == ["EMPTY"]
    assert (decisions(studio), publications) == ([], [])


def test_a_contradiction_of_the_profile_is_announced_with_the_titles_of_the_folder(
    tmp_path: Path,
) -> None:
    contradiction = "The profile says they sit at a desk."
    observation = {
        "statement": "People read the list standing up.",
        "basis": "Two findings on the commits.",
        "about": {"requirement": "REQ-003", "screen": "SCR-001"},
        "contradicts_profile": contradiction,
    }
    with FakeStudio(language="it", twins=1) as studio:
        project = seeded(tmp_path, studio)
        knowledge.unpack(valid_archive(), ProjectFolder(tmp_path / "project").knowledge)
        project.seed_change()
        project.seed_update(0, [observation])
        english = ut(tmp_path, "twins", "update", answers=["d", ""])
        project.seed_change()
        project.seed_update(0, [observation])
        italian = ut(tmp_path, "--lang", "it", "twins", "update", answers=["s", ""])

    about = ", ".join(
        [
            say("twins.about_requirement", code="REQ-003", title="Validazione nome"),
            say("twins.about_screen", code="SCR-001", title="Lista Ospiti"),
        ]
    )
    assert "  " + say("twins.update_about", about=about) in english.output.splitlines()
    assert "  " + say("twins.update_contradiction", text=contradiction) in (
        english.output.splitlines()
    )
    assert "  " + say("twins.update_contradiction", "it", text=contradiction) in (
        italian.output.splitlines()
    )


@pytest.mark.parametrize(
    ("language", "ceiling", "amount"), [("en", "0.20", "0.15"), ("it", "0,20", "0,15")]
)
def test_a_ceiling_on_the_second_twin_leaves_the_first_decided(
    tmp_path: Path, language: str, ceiling: str, amount: str
) -> None:
    key = "twins.update_errors.GENERATION_BUDGET_EXCEEDED.total"
    with FakeStudio(language=language, twins=2, budget_usd=0.2) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        twins = names(project)
        run = ut(tmp_path, "--lang", language, "twins", "update", answers=["", ""])
        entries = project.twin_learning()
        spent = studio.spent_microusd

    label = say("twins.update_label", language, name=twins[1])
    approved = say(
        "twins.update_approved", language, name=twins[0], label="1.1", codes="OBS-001, OBS-002"
    )
    lines = run.output.splitlines()
    assert run.status == 5
    assert run.errors == say(key, language, ceiling=ceiling, name=twins[1]) + "\n"
    assert say("costs.over_credit", language) in lines
    assert approved in lines
    assert say("common.progress_not_completed", language, label=label, elapsed="9 s") in lines
    assert say("twins.update_cost", language, amount=amount) in lines
    assert say("twins.folder_updated", language, version=1) in lines
    assert [entry["label"] for entry in entries] == ["1.1", "1.0"]
    assert spent == 150_000


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_lost_proposal_is_named_and_the_next_twin_goes_on(tmp_path: Path, language: str) -> None:
    with FakeStudio(language=language, twins=2) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        twins = names(project)
        studio.lose_job("TWIN_UPDATE")
        run = ut(tmp_path, "--lang", language, "twins", "update", answers=["k"])
        entries = project.twin_learning()

    assert run.status == 1
    assert run.errors == say("twins.update_errors.GENERATION_LOST", language, name=twins[0]) + "\n"
    approved = say("twins.update_approved", language, name=twins[1], label="1.1", codes="OBS-001")
    assert approved in run.output
    assert [entry["label"] for entry in entries] == ["1.0", "1.1"]


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_proposal_still_being_made_is_left_to_a_later_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    monkeypatch.setattr(twin_update, "LIMIT_SECONDS", 5.0)
    with FakeStudio(language=language, twins=1, job_polls=50) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        twin = names(project)[0]
        run = ut(tmp_path, "--lang", language, "twins", "update")

    key = "twins.update_errors.GENERATION_STILL_RUNNING"
    assert run.status == 1
    assert run.errors == say(key, language, name=twin) + "\n"
    assert say("twins.update_heading", language, name=twin, label="1.0") not in run.output


@pytest.mark.parametrize(
    ("answers", "question"),
    [
        ([], "twins.update_question"),
        (["", "e"], "twins.update_edit"),
        (["d", "d"], "twins.update_reason"),
    ],
)
@pytest.mark.parametrize(("language", "amount"), [("en", "0.15"), ("it", "0,15")])
def test_a_closed_input_leaves_the_proposal_waiting(
    tmp_path: Path, answers: list[str], question: str, language: str, amount: str
) -> None:
    with FakeStudio(language=language, twins=2) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        twins = names(project)
        run = ut(tmp_path, "--lang", language, "twins", "update", answers=answers)
        updates = project.twin_updates()
        proposals = posted(studio, "/updates")

    lines = run.output.splitlines()
    cost = say("twins.update_cost", language, amount=amount)
    assert run.status == 1
    assert lines[-4:] == [say(question, language) + " ", "", "", cost]
    assert run.errors == say("twins.update_left_pending", language, name=twins[0]) + "\n"
    assert [(item["twin_name"], item["status"]) for item in updates] == [(twins[0], "PROPOSED")]
    assert len(proposals) == 1
    assert decisions(studio) == []


def test_a_closed_input_after_one_decision_still_publishes_the_folder(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=2) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        project.seed_update(0, [{"statement": "People pay by phone."}])
        project.seed_update(1, [{"statement": "Owners count the tips."}])
        twins = names(project)
        run = ut(tmp_path, "twins", "update", answers=["k"])
        statuses = [item["status"] for item in project.twin_updates()]

    assert run.status == 1
    assert run.errors == say("twins.update_left_pending", name=twins[1]) + "\n"
    assert run.output.splitlines()[-1] == say("twins.folder_updated", version=1)
    assert statuses == ["PROPOSED", "APPROVED"]


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (503, "TWIN_UPDATE_MODEL_NOT_CONFIGURED"),
        (409, "USER_MODELING_APPROVAL_REQUIRED"),
        (409, "REQUIREMENTS_APPROVAL_REQUIRED"),
        (409, "DESIGN_APPROVAL_REQUIRED"),
        (404, "USER_TWIN_NOT_FOUND"),
        (429, "TOO_MANY_GENERATIONS"),
        (502, "INVALID_PROVIDER_OUTPUT"),
        (503, "GENERATION_BUDGET_UNAVAILABLE"),
    ],
)
@pytest.mark.parametrize("language", ["en", "it"])
def test_a_refusal_of_the_studio_becomes_one_sentence(
    tmp_path: Path, status: int, code: str, language: str
) -> None:
    with FakeStudio(language=language, twins=2) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        twins = names(project)
        studio.fail_next("POST", UPDATES, status=status, body={"detail": {"code": code}})
        run = ut(tmp_path, "--lang", language, "twins", "update", answers=["t"])

    expected = 5 if code == "GENERATION_BUDGET_UNAVAILABLE" else 1
    approved = say("twins.update_approved", language, name=twins[1], label="1.1", codes="OBS-001")
    assert run.status == expected
    assert run.errors == say(f"twins.update_errors.{code}", language, name=twins[0]) + "\n"
    assert approved in run.output


@pytest.mark.parametrize(("language", "ceiling"), [("en", "2.00"), ("it", "2,00")])
def test_a_ceiling_of_one_generation_names_it(tmp_path: Path, language: str, ceiling: str) -> None:
    key = "twins.update_errors.GENERATION_BUDGET_EXCEEDED.generation"
    body = {"detail": {"code": "GENERATION_BUDGET_EXCEEDED", "stage": "MODEL_PROPOSAL"}}
    with FakeStudio(language=language, twins=1) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        twin = names(project)[0]
        studio.fail_next("POST", UPDATES, status=402, body=body)
        run = ut(tmp_path, "--lang", language, "twins", "update")

    assert run.status == 5
    assert run.errors == say(key, language, name=twin, ceiling=ceiling) + "\n"


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_ceiling_that_cannot_be_named_gives_the_general_sentence(
    tmp_path: Path, language: str
) -> None:
    key = "twins.update_errors.GENERATION_BUDGET_EXCEEDED"
    unknown = {"detail": {"code": "GENERATION_BUDGET_NOT_CONFIGURED"}}
    body = {"detail": {"code": "GENERATION_BUDGET_EXCEEDED", "stage": "MODEL_PROPOSAL"}}
    with FakeStudio(language=language, twins=1) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        twin = names(project)[0]
        studio.fail_next("GET", "/model-runtime/budget", status=503, body=unknown, times=2)
        studio.fail_next("POST", UPDATES, status=402, body=body)
        run = ut(tmp_path, "--lang", language, "twins", "update")

    assert run.status == 5
    assert run.output.splitlines()[0] == say("twins.update_to_generate", language, names=twin)
    assert run.errors == say(key, language, name=twin) + "\n"


@pytest.mark.parametrize("language", ["en", "it"])
def test_an_unknown_refusal_names_its_code(tmp_path: Path, language: str) -> None:
    with FakeStudio(language=language, twins=1) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        twin = names(project)[0]
        studio.fail_next("POST", UPDATES, status=500, body={"detail": {"code": "SOMETHING_ELSE"}})
        run = ut(tmp_path, "--lang", language, "twins", "update")

    failed = say("twins.update_failed", language, name=twin, code="SOMETHING_ELSE")
    assert run.status == 1
    assert run.errors == failed + "\n"


def test_nothing_new_found_by_the_studio_is_not_a_failure(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=1) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        twin = names(project)[0]
        body = {"detail": {"code": "TWIN_UPDATE_NOTHING_NEW"}}
        studio.fail_next("POST", UPDATES, status=409, body=body)
        run = ut(tmp_path, "twins", "update")

    assert (run.status, run.errors) == (0, "")
    assert run.output.splitlines()[-1] == say("twins.update_nothing_new", name=twin)


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_proposal_made_meanwhile_is_taken_up_instead(tmp_path: Path, language: str) -> None:
    with FakeStudio(language=language, twins=1) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        project.seed_update(0, [{"statement": "People pay by phone."}])
        twin = names(project)[0]
        stale = {
            "project_id": project.id,
            "update_available": True,
            "twins": [
                {
                    **entry,
                    "pending_update": None,
                    "new_material": {"changes": 1, "tests": 0},
                }
                for entry in project.twin_learning()
            ],
        }
        studio.fail_next("GET", LEARNING, status=200, body=stale)
        run = ut(tmp_path, "--lang", language, "twins", "update", answers=["k"])
        spent = studio.spent_microusd

    approved = say("twins.update_approved", language, name=twin, label="1.1", codes="OBS-001")
    assert run.status == 0
    assert say("twins.update_already_waiting", language, name=twin) in run.output.splitlines()
    assert approved in run.output
    assert spent == 0


@pytest.mark.parametrize(
    ("status", "code", "key"),
    [
        (409, "TWIN_UPDATE_CONTEXT_CHANGED", "twins.update_errors.TWIN_UPDATE_CONTEXT_CHANGED"),
        (409, "TWIN_OBSERVATIONS_LIMIT", "twins.update_errors.TWIN_OBSERVATIONS_LIMIT"),
        (409, "TWIN_UPDATE_ALREADY_DECIDED", "twins.update_errors.TWIN_UPDATE_ALREADY_DECIDED"),
        (404, "TWIN_UPDATE_NOT_FOUND", "twins.update_errors.TWIN_UPDATE_NOT_FOUND"),
        (422, "invalid_request", "twins.update_decision_failed"),
    ],
)
@pytest.mark.parametrize("language", ["en", "it"])
def test_a_refused_decision_becomes_one_sentence(
    tmp_path: Path, status: int, code: str, key: str, language: str
) -> None:
    with FakeStudio(language=language, twins=1) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        project.seed_update(0, [{"statement": "People pay by phone."}])
        twin = names(project)[0]
        body = {"detail": code} if code == "invalid_request" else {"detail": {"code": code}}
        studio.fail_next("POST", DECISION, status=status, body=body)
        run = ut(tmp_path, "--lang", language, "twins", "update", answers=["k"])
        statuses = [item["status"] for item in project.twin_updates()]

    assert run.status == 1
    assert run.errors == say(key, language, name=twin, number=1, limit=20, code=code) + "\n"
    assert statuses == ["PROPOSED"]
    assert posted(studio, "/knowledge-packages") == []


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_folder_that_cannot_be_published_is_one_sentence(tmp_path: Path, language: str) -> None:
    code = "KNOWLEDGE_PACKAGE_SERVICE_UNAVAILABLE"
    with FakeStudio(language=language, twins=1) as studio:
        project = seeded(tmp_path, studio)
        project.seed_change()
        project.seed_update(0, [{"statement": "People pay by phone."}])
        studio.fail_next("POST", PUBLISH, status=503, body={"detail": {"code": code}})
        run = ut(tmp_path, "--lang", language, "twins", "update", answers=["k"])

    assert (run.status, run.errors) == (0, "")
    assert run.output.splitlines()[-1] == say("twins.folder_not_updated", language, code=code)


def test_every_code_of_the_flow_has_its_sentence_in_both_languages() -> None:
    codes = (
        *twin_update.UNFINISHED,
        "GENERATION_BUDGET_EXCEEDED",
        "GENERATION_BUDGET_UNAVAILABLE",
        "TWIN_UPDATE_MODEL_NOT_CONFIGURED",
        "USER_MODELING_APPROVAL_REQUIRED",
        "REQUIREMENTS_APPROVAL_REQUIRED",
        "DESIGN_APPROVAL_REQUIRED",
        "USER_TWIN_NOT_FOUND",
        "TOO_MANY_GENERATIONS",
        "INVALID_PROVIDER_OUTPUT",
        "TWIN_UPDATE_ALREADY_DECIDED",
        "TWIN_UPDATE_CONTEXT_CHANGED",
        "TWIN_OBSERVATIONS_LIMIT",
        "TWIN_UPDATE_NOT_FOUND",
    )
    reasons = ("total", "project", "generation")

    assert [code for code in codes if not known(f"{twin_update.FAILURE_PREFIX}.{code}")] == []
    assert [
        reason
        for reason in reasons
        if not known(f"{twin_update.FAILURE_PREFIX}.GENERATION_BUDGET_EXCEEDED.{reason}")
    ] == []
    assert set(twin_update.ANSWERS.values()) == {
        twin_update.KEEP,
        twin_update.EDIT,
        twin_update.DROP,
    }
