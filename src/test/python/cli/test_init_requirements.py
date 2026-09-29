from __future__ import annotations

import json
from pathlib import Path

from .support.fake_studio import FakeStudio
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
    twins_answers,
    ut,
)

BEFORE_REQUIREMENTS = [*start(), *brief_answers(), "1", *twins_answers()]
REQUEST = "Add a page with the history of the bills."


def revision_decisions(studio: FakeStudio) -> list[object]:
    return [
        json.loads(request.body.decode("utf-8"))
        for request in studio.requests
        if request.method == "POST"
        and "/requirements/revisions/" in request.path
        and request.path.endswith("/decision")
    ]


def test_a_change_is_applied_and_the_new_version_is_approved(tmp_path: Path) -> None:
    answers = [*BEFORE_REQUIREMENTS, "3", REQUEST, "", "y", "1"]
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, answers=answers)

        assert run.status == 0, run.errors
        assert posted(studio, "/change-requests") == [{"request": REQUEST}]
        assert revision_decisions(studio) == [{"decision": "APPROVE"}]
        version = fake_project(studio, tmp_path).current("requirements")
        assert version["version_number"] == 2
        assert len(version["specification"]["requirements"]) == 5
        assert saved_step(tmp_path, "requirements")["version"] == version
    lines = run.output.splitlines()
    assert "Estimate: 0.30 USD, about 2 min. Credit left in the Studio: 59.42 USD." in lines
    assert "The proposed change. Changes: 1." in lines
    assert "  + adds the requirement REQ-005: Owner request: " + REQUEST in lines
    assert "Change applied: the requirements are at version 2." in lines
    assert (
        'Step "Requirements" approved (version 2). Saved in .orchestwin/steps/requirements.json.'
        in lines
    )


def test_a_change_is_discarded_with_a_reason(tmp_path: Path) -> None:
    answers = [*BEFORE_REQUIREMENTS, "3", REQUEST, "", "n", "1"]
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, answers=answers)

        assert run.status == 0, run.errors
        assert revision_decisions(studio) == [
            {"decision": "REJECT", "reason": "Discarded by the owner of the project with ut init."}
        ]
        assert fake_project(studio, tmp_path).current("requirements")["version_number"] == 1
    assert "Change discarded: the requirements stay at version 1." in run.output


def test_an_empty_change_request_changes_nothing(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, answers=[*BEFORE_REQUIREMENTS, "3", "", "1"])

        assert run.status == 0, run.errors
        assert posted(studio, "/change-requests") == []
    assert "No change asked." in run.output


def test_everything_is_read_in_full(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, answers=[*BEFORE_REQUIREMENTS, "2", "1"])

    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert (
        "The requirements (version 1). Requirements: 4; user stories: 2; acceptance criteria: 4."
        in lines
    )
    assert "REQ-001 Amount entry (must have, function)" in lines
    assert "  The system lets people enter the bill in euros." in lines
    assert "REQ-004 Immediate answer (must have, quality)" in lines
    assert any(
        line.endswith(
            "wants to work out the tip without mental maths, so as to settle the bill quickly."
        )
        for line in lines
    )
    assert "AC-001 With 30 euros and 15 percent the tip is 4.50 euros." in lines
    assert "  checked by an automated test" in lines


def test_the_requirements_in_italian_show_priorities_in_plain_words(tmp_path: Path) -> None:
    answers = [*start("s"), *brief_answers(), "1", *twins_answers("s"), "2", "1"]
    with FakeStudio(language="it") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, answers=answers, language="it")

    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert "REQ-003 Divisione del conto (importante, funzione)" in lines
    assert "  si verifica con un test automatico" in lines
    assert any(line.endswith("per chiudere il conto in fretta.") for line in lines)


def test_a_lost_requirements_generation_is_made_again_on_the_next_launch(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        studio.lose_job("REQUIREMENTS_PROPOSAL")

        first = ut(tmp_path, answers=BEFORE_REQUIREMENTS)
        second = ut(tmp_path, answers=["1"])

        assert first.status == 1
        assert second.status == 0, second.errors
        assert len(posted(studio, "/requirements/proposals")) == 2
        assert saved_stages(tmp_path) == ["brief", "team", "twins", "requirements"]
    assert "Writing the requirements: the generation was lost" in first.errors


def test_a_ceiling_reached_inside_the_job_stops_the_path(tmp_path: Path) -> None:
    with FakeStudio(language="en", budget_usd=0.4) as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, answers=BEFORE_REQUIREMENTS)

        assert run.status == 5
        assert saved_stages(tmp_path) == ["brief", "team", "twins"]
    assert (
        "The Studio reached its overall spending ceiling (0.40 USD): the generation did not "
        "start." in run.errors
    )


def test_changes_from_the_answers_file_are_applied(tmp_path: Path) -> None:
    script = tmp_path / "answers.json"
    script.write_text(
        json.dumps(
            {
                "name": NAME,
                "idea": IDEA,
                "requirements": {"changes": [REQUEST], "decision": "APPROVE"},
            }
        ),
        encoding="utf-8",
    )
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, "--answers", str(script), yes=True)

        assert run.status == 0, run.errors
        assert posted(studio, "/change-requests") == [{"request": REQUEST}]
        assert saved_step(tmp_path, "requirements")["version"]["version_number"] == 2
    lines = run.output.splitlines()
    assert "Estimate: 0.78-1.02 USD, about 7 min. Credit left in the Studio: 60.00 USD." in lines
    assert "Change asked by the file: " + REQUEST in lines
    assert "Change applied: the requirements are at version 2." in lines


def test_a_change_left_undecided_is_decided_on_the_next_launch(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        first = ut(tmp_path, answers=[*BEFORE_REQUIREMENTS, "3", REQUEST, ""])
        second = ut(tmp_path, answers=["y", "1"])

        assert first.status == 1
        assert second.status == 0, second.errors
        assert posted(studio, "/change-requests") == [{"request": REQUEST}]
        assert saved_step(tmp_path, "requirements")["version"]["version_number"] == 2
    assert (
        "There is a proposed change to the requirements that is not decided yet: here it is."
        in second.output
    )
