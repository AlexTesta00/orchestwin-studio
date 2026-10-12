from __future__ import annotations

import json
from pathlib import Path

import pytest

from .support.fake_studio import OPINION_TEXTS
from .support.terminal import Run
from .test_api_design import Session, design_session
from .test_design_change import ITERATIONS, applied_html, chosen
from .test_design_target43 import LINK, bodies, code_of, flat, said

OPINIONS = "/design/opinions"
COLOURED = {"en": "Make the bar red and the text blue", "it": "Fai la barra rosso e il testo blu"}
PLAIN = "Make the button larger"
LOCALES = {"en": "en-US", "it": "it-IT"}


def aimed(
    session: Session,
    request: str,
    *options: str,
    answers: tuple[str, ...] | list[str] = (),
    language: str = "en",
) -> Run:
    code = code_of(applied_html(session), LINK[language])
    return session.ut(
        *options,
        "design",
        "change",
        request,
        "--screen",
        "SCR-001",
        "--element",
        code,
        "--ask-first",
        answers=answers,
        language=language,
    )


def asked(session: Session) -> list[dict[str, object]]:
    return [json.loads(item.body) for item in session.requests("POST", OPINIONS)]


def twin_lines(session: Session, language: str) -> str:
    texts = OPINION_TEXTS[language]
    lines = []
    for opinion in session.project.opinions[0]["opinions"]:
        verdict = said(f"design.opinion_verdict_{opinion['verdict']}", language)
        lines.append(f"{opinion['twin_name']} · {verdict}")
        lines.append(said("design.opinion_why", language, why=texts[opinion["verdict"]]))
        lines.append(said("design.opinion_what_to_do", language, action=texts["what_to_do"]))
        if opinion["try_this"] is not None:
            lines.append(said("design.opinion_try_this", language, request=texts["try_this"]))
    return flat(" ".join(lines))


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_twins_give_their_opinion_first_and_the_change_is_applied_anyway(
    tmp_path: Path, language: str
) -> None:
    with design_session(tmp_path, language=language) as session:
        chosen(session)
        run = aimed(session, COLOURED[language], answers=["1", "y"], language=language)
        sent = asked(session)
        iterated = bodies(session)
        [opinion] = session.project.opinions
        shown = twin_lines(session, language)

    output = flat(run.output)
    about = said("design.opinion_about", language)
    assert run.status == 0, run.errors
    assert [item["verdict"] for item in opinion["opinions"]] == ["BLOCKS", "HELPS"]
    assert [body["locale"] for body in sent] == [LOCALES[language]]
    assert [body["request"] for body in sent] == [COLOURED[language]]
    assert sent[0]["target"] == iterated[0]["target"]
    assert [body["opinion_id"] for body in iterated] == [opinion["run_id"]]
    assert shown in output
    assert output.index(about) < output.index(shown)
    assert flat(said("design.opinion_simulated", language)) in output
    assert ("0.20-0.35" if language == "en" else "0,20-0,35") in output
    assert output.index(shown) < output.index(flat(said("design.opinion_choice_apply", language)))
    assert output.index(shown) < output.index(
        flat(said("design.about_change", language, request=COLOURED[language]))
    )
    assert said("design.change_applied", language, version=3) in run.output


def test_a_new_request_can_be_written_after_the_opinion(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        run = aimed(session, PLAIN, answers=["2", "Make the button darker", "", "y"])
        sent = asked(session)
        iterated = bodies(session)
        [opinion] = session.project.opinions

    assert run.status == 0, run.errors
    assert [item["verdict"] for item in opinion["opinions"]] == ["SLOWS", "HELPS"]
    assert len(sent) == 1
    assert [(body["request"], body["opinion_id"]) for body in iterated] == [
        ("Make the button darker", opinion["run_id"])
    ]
    assert said("design.about_change", request="Make the button darker") in run.output


@pytest.mark.parametrize("language", ["en", "it"])
def test_cancelling_after_the_opinion_records_it_and_changes_nothing(
    tmp_path: Path, language: str
) -> None:
    with design_session(tmp_path, language=language) as session:
        chosen(session)
        run = aimed(session, PLAIN, answers=["3"], language=language)
        started = session.count("POST", ITERATIONS)
        recorded = len(session.project.opinions)

    assert run.status == 0, run.errors
    assert run.output.endswith(said("design.opinion_cancelled", language) + "\n")
    assert said("design.change_cancelled", language) not in run.output
    assert (started, recorded) == (0, 1)


def test_with_yes_the_opinion_is_shown_and_the_change_applied(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        run = aimed(session, PLAIN, "--yes")
        iterated = bodies(session)
        [opinion] = session.project.opinions
        shown = twin_lines(session, "en")

    assert run.status == 0, run.errors
    assert shown in flat(run.output)
    assert said("design.opinion_choice_apply") not in run.output
    assert [body["opinion_id"] for body in iterated] == [opinion["run_id"]]


def test_the_same_request_on_the_same_version_reuses_the_recorded_opinion(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        first = aimed(session, PLAIN, answers=["3"])
        second = aimed(session, f"  {PLAIN} ", answers=["1", "y"])
        other = aimed(session, "Make the button smaller", answers=["3"])
        sent = asked(session)
        iterated = bodies(session)
        runs = list(session.project.opinions)

    assert (first.status, second.status, other.status) == (0, 0, 0)
    assert said("design.opinion_exists") in second.output
    assert said("design.opinion_about") not in second.output
    assert said("design.opinion_exists") not in other.output
    assert [body["request"] for body in sent] == [PLAIN, "Make the button smaller"]
    assert [body["opinion_id"] for body in iterated] == [runs[-1]["run_id"]]


def test_a_failed_opinion_applies_nothing(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        session.studio.fail_job(
            "DESIGN_CHANGE_OPINION", code="INVALID_CHANGE_OPINION_OUTPUT", status=502
        )
        run = aimed(session, PLAIN)
        started = session.count("POST", ITERATIONS)

    assert run.status == 1
    assert run.errors == (
        said("design.errors.INVALID_CHANGE_OPINION_OUTPUT", code="INVALID_CHANGE_OPINION_OUTPUT")
        + "\n"
    )
    assert said("design.opinion_choice_apply") not in run.output
    assert started == 0


def test_a_studio_without_a_model_for_the_twins_says_so_like_the_review(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        session.studio.fail_next(
            "POST",
            "/projects/{project_id}" + OPINIONS,
            status=503,
            body={"detail": {"code": "DESIGN_REVIEWER_NOT_CONFIGURED"}},
        )
        run = aimed(session, PLAIN)
        started = session.count("POST", ITERATIONS)

    assert run.status == 1
    assert run.errors == (
        said("design.errors.DESIGN_REVIEWER_NOT_CONFIGURED", code="DESIGN_REVIEWER_NOT_CONFIGURED")
        + "\n"
    )
    assert started == 0


def test_a_zone_or_several_parts_are_the_target_of_the_opinion(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        session.studio.landmarks = True
        chosen(session)
        zone = session.ut(
            "design",
            "change",
            PLAIN,
            "--screen",
            "SCR-001",
            "--element",
            "ZON-002",
            "--ask-first",
            answers=["3"],
        )
        parts = session.ut(
            "design",
            "change",
            PLAIN,
            "--screen",
            "SCR-001",
            "--element",
            "ELM-012",
            "--element",
            "ELM-004",
            "--ask-first",
            answers=["3"],
        )
        sent = asked(session)

    assert (zone.status, parts.status) == (0, 0)
    assert [body["target"] for body in sent] == [
        {"screen_code": "SCR-001", "element_code": "ZON-002", "label": "Sections"},
        {
            "screen_code": "SCR-001",
            "elements": [
                {"element_code": "ELM-004", "label": "Bill"},
                {"element_code": "ELM-012", "label": "Split it again"},
            ],
        },
    ]
