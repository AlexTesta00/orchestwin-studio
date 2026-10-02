from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from orchestwin.cli import messages
from orchestwin.cli.api import tasks as tasks_api
from orchestwin.cli.context import CommandContext
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows import task_selection
from orchestwin.cli.flows.task_selection import Candidate

from .support.terminal import Terminal, command_context, terminal
from .support.transports import NoNetwork

RUN_ID = "00000000-0000-4000-8000-00000000e001"
COMMIT = "4F2A9C1E7B3D5A8F0C6E2B9D1A7F3C5E8B0D2A46"
OWNER_TWIN = "00000000-0000-4000-8000-0000000000b1"
WAITER_TWIN = "00000000-0000-4000-8000-0000000000b2"
QUIET_TWIN = "00000000-0000-4000-8000-0000000000b3"
CONCERN = "Criterion AC-001 does not assure me that the application does what I need."
PHONE = "Criterion AC-001 should be tried on a phone too."
TOTAL = "The total is wrong when three people split the bill."
CRITIQUES = [
    {
        "twin_id": OWNER_TWIN,
        "twin_name": "Pizzeria owner",
        "findings": [
            {"severity": "MEDIUM", "text": CONCERN, "action": "Fix the path of AC-001."},
            "noise",
            {"severity": "LOW", "text": f"  {PHONE} ", "action": None},
        ],
    },
    {
        "twin_id": WAITER_TWIN,
        "twin_name": " ",
        "findings": [{"severity": "HIGH", "text": TOTAL, "action": "Fix the total."}],
    },
    "noise",
    {"twin_id": QUIET_TWIN, "twin_name": "Regular customer", "findings": []},
    {"twin_id": "", "twin_name": "Nobody", "findings": [{"severity": "LOW", "text": "Lost."}]},
]
RUN = {"id": RUN_ID, "critiques": CRITIQUES}
EXISTING = {
    "code": "TSK-007",
    "text": PHONE,
    "about": {"requirements": [], "screens": [], "criteria": ["AC-001"]},
    "origin": {
        "kind": "TEST_RUN",
        "commit": None,
        "test_run_id": RUN_ID,
        "twin_id": OWNER_TWIN,
        "twin_name": "Pizzeria owner",
        "finding": PHONE,
    },
    "from_commit": None,
    "created_at": "2026-09-29T16:48:37+00:00",
    "status": "OPEN",
    "closed_at": None,
    "note": None,
}
QUESTION = "tasks.choose_question"


def bench(
    tmp_path: Path, answers: Sequence[str] = (), language: str = "en"
) -> tuple[CommandContext, Terminal]:
    bundle = terminal(
        tmp_path, transport=NoNetwork(), answers=answers, variables={"COLUMNS": "400"}
    )
    return command_context(bundle.environment, language=language), bundle


def said(key: str, language: str = "en", **values: object) -> str:
    return messages.text(key, language, **values)


def candidates() -> tuple[Candidate, ...]:
    return task_selection.candidates_of_run(RUN, [EXISTING])


def test_the_candidates_of_a_test_run_keep_the_positions_of_the_findings() -> None:
    found = candidates()

    assert found == (
        Candidate(
            label="Pizzeria owner",
            text="Fix the path of AC-001.",
            source=tasks_api.run_source(RUN_ID, OWNER_TWIN, 0),
            finding=CONCERN,
            severity="MEDIUM",
        ),
        Candidate(
            label="Pizzeria owner",
            text=PHONE,
            source=tasks_api.run_source(RUN_ID, OWNER_TWIN, 2),
            task_code="TSK-007",
            finding=PHONE,
            severity="LOW",
        ),
        Candidate(
            label=None,
            text="Fix the total.",
            source=tasks_api.run_source(RUN_ID, WAITER_TWIN, 0),
            finding=TOTAL,
            severity="HIGH",
        ),
    )
    assert [item.offered for item in found] == [True, False, True]
    assert not any(item.verdict for item in found)


def test_the_candidates_of_a_review_name_the_commit() -> None:
    change_task = {
        **EXISTING,
        "origin": {
            **EXISTING["origin"],
            "kind": "CODE_CHANGE",
            "commit": COMMIT.lower(),
            "test_run_id": None,
            "finding": CONCERN,
        },
    }
    found = task_selection.candidates_of_review(COMMIT, {"critiques": CRITIQUES}, [change_task])

    assert [item.source for item in found] == [
        tasks_api.change_source(COMMIT.lower(), OWNER_TWIN, 0),
        tasks_api.change_source(COMMIT.lower(), OWNER_TWIN, 2),
        tasks_api.change_source(COMMIT.lower(), WAITER_TWIN, 0),
    ]
    assert [item.task_code for item in found] == ["TSK-007", None, None]
    assert task_selection.candidates_of_run(RUN, [change_task])[0].task_code is None


def test_the_tasks_of_the_verdict_are_candidates_without_a_source() -> None:
    found = task_selection.verdict_candidates(["  Cover  the tip ", " ", "Fix the total."])

    assert found == (
        Candidate(label=None, text="Cover the tip", source=None),
        Candidate(label=None, text="Fix the total.", source=None),
    )
    assert all(item.verdict and item.offered for item in found)


def test_numbers_choose_in_the_order_of_the_list(tmp_path: Path) -> None:
    context, bundle = bench(tmp_path, answers=["2, 1"])
    found = candidates()

    chosen = task_selection.choose(context, found, question_key=QUESTION)

    assert chosen == (found[0], found[2])
    assert bundle.output.splitlines() == [
        "  1. "
        + said(
            "tasks.choice_finding",
            who="Pizzeria owner",
            importance="medium importance",
            finding=CONCERN,
        ),
        "     " + said("tasks.choice_task", text="Fix the path of AC-001."),
        "  -  "
        + said(
            "tasks.choice_existing",
            line=said(
                "tasks.choice_finding",
                who="Pizzeria owner",
                importance="low importance",
                finding=PHONE,
            ),
            code="TSK-007",
        ),
        "  2. "
        + said("tasks.choice_finding", who="A twin", importance="high importance", finding=TOTAL),
        "     " + said("tasks.choice_task", text="Fix the total."),
        said(QUESTION) + " ",
    ]


@pytest.mark.parametrize("answer", ["a", "t", " A ", "T", "tutti", "all"])
def test_a_or_t_chooses_every_candidate_that_is_not_a_task_yet(tmp_path: Path, answer: str) -> None:
    context, _ = bench(tmp_path, answers=[answer])
    found = candidates()

    assert task_selection.choose(context, found, question_key=QUESTION) == (found[0], found[2])


def test_nothing_typed_gives_the_default_of_the_caller(tmp_path: Path) -> None:
    context, _ = bench(tmp_path, answers=["", "", ""])
    verdict = task_selection.verdict_candidates(["Cover the tip."])
    found = (*verdict, *candidates())

    none = task_selection.choose(context, found, question_key=QUESTION)
    default = task_selection.choose(context, found, question_key=QUESTION, default=verdict)
    existing = task_selection.choose(context, found, question_key=QUESTION, default=found[2:3])

    assert none == ()
    assert default == verdict
    assert existing == ()


def test_a_wrong_answer_asks_again_three_times_then_nothing_is_chosen(tmp_path: Path) -> None:
    context, bundle = bench(tmp_path, answers=["3", "1 x", "0", "1"])

    chosen = task_selection.choose(context, candidates(), question_key=QUESTION)

    lines = bundle.output.splitlines()
    assert chosen == ()
    assert lines.count(said("tasks.choice_invalid", count=2)) == 3
    assert lines[-1] == said("tasks.choice_given_up")
    assert bundle.environment.stdin.readline() == "1\n"


def test_a_wrong_answer_and_then_a_right_one(tmp_path: Path) -> None:
    context, bundle = bench(tmp_path, answers=[",", "2"])
    found = candidates()

    assert task_selection.choose(context, found, question_key=QUESTION) == (found[2],)
    assert said("tasks.choice_invalid", count=2) in bundle.output.splitlines()


def test_a_limit_refuses_too_many_candidates(tmp_path: Path) -> None:
    context, bundle = bench(tmp_path, answers=["a", "2"])
    found = candidates()

    assert task_selection.choose(context, found, question_key=QUESTION, limit=1) == (found[2],)
    assert said("tasks.choice_too_many", limit=1) in bundle.output.splitlines()


def test_when_every_finding_is_a_task_nothing_is_asked(tmp_path: Path) -> None:
    context, bundle = bench(tmp_path, answers=["1"])
    tasks = [
        {**EXISTING, "code": f"TSK-00{index}", "origin": {**EXISTING["origin"], **origin}}
        for index, origin in enumerate(
            (
                {"finding": CONCERN},
                {"finding": PHONE},
                {"twin_id": WAITER_TWIN, "finding": TOTAL},
            ),
            start=1,
        )
    ]

    chosen = task_selection.choose(
        context, task_selection.candidates_of_run(RUN, tasks), question_key=QUESTION
    )

    lines = bundle.output.splitlines()
    assert chosen == ()
    assert [line[:11] for line in lines[:4]] == [
        "  -  Pizzer",
        "     Task: ",
        "  -  Pizzer",
        "  -  A twin",
    ]
    assert lines[-1] == said("tasks.choice_all_tasks")
    assert said(QUESTION) + " " not in lines
    assert bundle.environment.stdin.readline() == "1\n"


def test_no_candidate_shows_nothing(tmp_path: Path) -> None:
    context, bundle = bench(tmp_path, answers=["1"])

    assert task_selection.choose(context, (), question_key=QUESTION) == ()
    assert bundle.output == ""


def test_a_closed_input_raises_as_every_question(tmp_path: Path) -> None:
    context, _ = bench(tmp_path)

    with pytest.raises(CliError) as closed:
        task_selection.choose(context, candidates(), question_key=QUESTION)

    assert closed.value.code == "INPUT_CLOSED"


def test_the_verdict_speaks_in_its_own_line(tmp_path: Path) -> None:
    context, bundle = bench(tmp_path, answers=[""])
    verdict = task_selection.verdict_candidates(["Cover requirement REQ-002 with a test."])

    chosen = task_selection.choose(context, verdict, question_key=QUESTION, default=verdict)

    assert chosen == verdict
    assert bundle.output.splitlines()[0] == "  1. " + said(
        "tasks.choice_verdict", text="Cover requirement REQ-002 with a test."
    )


def test_the_choice_in_italian(tmp_path: Path) -> None:
    context, bundle = bench(tmp_path, answers=["t"], language="it")
    found = candidates()

    chosen = task_selection.choose(context, found, question_key=QUESTION)

    lines = bundle.output.splitlines()
    assert chosen == (found[0], found[2])
    assert lines[0] == "  1. " + said(
        "tasks.choice_finding",
        "it",
        who="Pizzeria owner",
        importance="importanza media",
        finding=CONCERN,
    )
    assert lines[1] == "     " + said("tasks.choice_task", "it", text="Fix the path of AC-001.")
    assert lines[3].startswith("  2. Un twin, importanza alta: ")
    assert lines[-1] == said(QUESTION, "it") + " "


def test_an_unknown_importance_is_shown_as_the_studio_writes_it(tmp_path: Path) -> None:
    context, _ = bench(tmp_path)

    assert task_selection.importance_text(context, "CRITICAL") == "critical"
    assert task_selection.importance_text(context, None) == "-"
    assert task_selection.importance_text(context, "LOW") == said("tasks.importance_low")
