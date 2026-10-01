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
    ut,
)

UNTIL_TWINS = ("--until", "twins")
BEFORE_TWINS = [*start()[:-1], *brief_answers(), "1"]
PERSONAS = "/projects/{project_id}/user-modeling/personas/proposals"
BUSY = {"detail": {"code": "TOO_MANY_GENERATIONS"}}


def decisions(studio: FakeStudio) -> list[object]:
    return posted(studio, "/decision")


def test_interactive_archetype_edit_regenerates_before_approving_without_reproposing(tmp_path):
    answers = [
        *BEFORE_TWINS,
        "y",
        "y",
        "3",
        "3",
        "1",
        "",
        "Updated archetype summary",
        "",
        "",
        "",
        "1",
    ]
    with FakeStudio(language="en", twins=2) as studio:
        sign_in(studio, tmp_path)
        result = ut(tmp_path, *UNTIL_TWINS, answers=answers)
        assert result.status == 0, result.errors
        project = fake_project(studio, tmp_path)
        assert len(project.snapshots) == 2
        assert len(posted(studio, "/personas/proposals")) == 1
        assert len(posted(studio, "/snapshots/generate")) == 2
        assert project.snapshot["version_number"] == 2
        assert project.approved("twins")
        assert "Updated archetype summary" in result.output


def test_a_rejected_profile_is_left_out_of_the_twins(tmp_path: Path) -> None:
    answers = [*BEFORE_TWINS, "y", "n", "Not our users", "1"]
    with FakeStudio(language="en", twins=2) as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, *UNTIL_TWINS, answers=answers)

        assert run.status == 0, run.errors
        assert decisions(studio)[:2] == [
            {"decision": "CONFIRM"},
            {"decision": "REJECT", "reason": "Not our users"},
        ]
        snapshot = fake_project(studio, tmp_path).current("twins")
        assert snapshot["snapshot"]["twin_count"] == 1
        assert saved_step(tmp_path, "twins")["version"] == snapshot
    assert "Archetype 2 of 2: Pizzeria owner" in run.output
    assert "The User Twins (version 1). User Twins created: 1." in run.output
    assert "User Twin 1 of 1: Evening shift waiter" in run.output


def test_a_profile_is_rejected_with_the_offered_reason(tmp_path: Path) -> None:
    answers = [*BEFORE_TWINS, "n", "", "y", "1"]
    with FakeStudio(language="it", twins=2) as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, *UNTIL_TWINS, answers=answers, language="it")

        assert run.status == 0, run.errors
        assert decisions(studio)[0] == {
            "decision": "REJECT",
            "reason": "Non rappresenta gli utenti del progetto.",
        }
    assert "Perché lo scarti? Una riga, resta scritta con l'archetipo:" in run.output


def test_the_last_profile_cannot_be_rejected_when_none_is_confirmed(tmp_path: Path) -> None:
    answers = [*BEFORE_TWINS, "n", "y", "1"]
    with FakeStudio(language="en", twins=1) as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, *UNTIL_TWINS, answers=answers)

        assert run.status == 0, run.errors
        assert decisions(studio)[0] == {"decision": "CONFIRM"}
        assert fake_project(studio, tmp_path).approved("twins")
    assert "At least one confirmed archetype is needed to create the User Twins" in run.output


def test_a_failed_twin_generation_is_tried_again_after_asking(tmp_path: Path) -> None:
    answers = [*BEFORE_TWINS, "y", "y", "y", "1"]
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        studio.fail_job("USER_TWIN_GENERATION", code="TIMEOUT")

        run = ut(tmp_path, *UNTIL_TWINS, answers=answers)

        assert run.status == 0, run.errors
        assert len(posted(studio, "/snapshots/generate")) == 2
        assert fake_project(studio, tmp_path).approved("twins")
    assert (
        "Creating the User Twins from the confirmed archetypes: the model did not give a valid "
        "result (TIMEOUT)." in run.output
    )
    assert "Try once more? It is a new generation, about 0.12-0.18 USD. [Y/n]" in run.output


def test_a_failed_twin_generation_without_a_second_try(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        studio.fail_job("USER_TWIN_GENERATION", code="PROVIDER_UNAVAILABLE")

        run = ut(tmp_path, *UNTIL_TWINS, answers=[*BEFORE_TWINS, "y", "y", "n"])

        assert run.status == 1
        assert len(posted(studio, "/snapshots/generate")) == 1
        assert saved_stages(tmp_path) == ["brief", "team"]
    assert "the generation did not succeed (PROVIDER_UNAVAILABLE)" in run.errors


def test_a_lost_generation_stops_and_the_next_launch_generates_again(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        studio.lose_job("PERSONA_PROPOSAL")

        first = ut(tmp_path, *UNTIL_TWINS, answers=BEFORE_TWINS)
        second = ut(tmp_path, *UNTIL_TWINS, answers=["y", "y", "1"])

        assert first.status == 1
        assert second.status == 0, second.errors
        assert len(posted(studio, "/personas/proposals")) == 2
        assert saved_stages(tmp_path) == ["brief", "team", "twins"]
    assert (
        "Proposing the archetypes: the generation was lost, perhaps because the Studio "
        "restarted." in first.errors
    )


def test_too_many_generations_waits_and_tries_again(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        studio.fail_next("POST", PERSONAS, status=429, body=BUSY, times=2)

        run = ut(tmp_path, *UNTIL_TWINS, answers=[*BEFORE_TWINS, "y", "y", "1"])

        assert run.status == 0, run.errors
        assert len(posted(studio, "/personas/proposals")) == 3
    assert (
        "Too many generations are already running in the Studio: waiting 15 seconds and trying "
        "again (attempt 2 of 8)." in run.output
    )
    assert run.slept >= 30


def test_too_many_generations_gives_up_after_eight_waits(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        studio.fail_next("POST", PERSONAS, status=429, body=BUSY, times=9)

        run = ut(tmp_path, *UNTIL_TWINS, answers=BEFORE_TWINS)

        assert run.status == 1
        assert len(posted(studio, "/personas/proposals")) == 9
    assert run.slept == 120
    assert (
        "Proposing the archetypes: too many generations are still running in the Studio "
        "after eight waits." in run.errors
    )


def test_an_answers_file_can_stop_at_the_twins(tmp_path: Path) -> None:
    script = tmp_path / "answers.json"
    script.write_text(json.dumps({"name": NAME, "idea": IDEA, "twins": "STOP"}), encoding="utf-8")
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, "--answers", str(script), yes=True)

        assert run.status == 0, run.errors
        assert saved_stages(tmp_path) == ["brief", "team"]
        assert decisions(studio) == [{"decision": "CONFIRM"}, {"decision": "CONFIRM"}]
    assert "The User Twins stay waiting for your approval." in run.output
