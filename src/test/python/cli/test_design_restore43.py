from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestwin.cli.api import design as design_api
from orchestwin.cli.messages import text

from .support.terminal import run_ut
from .support.transports import NoNetwork
from .test_api_design import Session, design_session
from .test_design_change import chosen

RESTORE = "/design/revisions/restore"
ROUTE = "/projects/{project_id}/design/revisions/restore"
NOTES = {"en": "Restored from version 2", "it": "Ripristino della versione 2"}
LOCALES = {"en": "en-US", "it": "it-IT"}


def said(key: str, language: str = "en", **values: object) -> str:
    return text(key, language, **values)


def bodies(session: Session) -> list[dict[str, object]]:
    return [json.loads(item.body) for item in session.requests("POST", RESTORE)]


def three_versions(session: Session) -> None:
    chosen(session)
    client = session.client()
    current = design_api.current(client, session.project.id)
    assert current is not None
    package = dict(current["package"])
    package["open_questions"] = [*package["open_questions"], "Should the total stay on top?"]
    answer = design_api.propose_revision(client, session.project.id, package)
    design_api.decide_revision(client, session.project.id, str(answer["diff"]["id"]))
    assert [item["version_number"] for item in session.project.designs] == [1, 2, 3]


def numbers(session: Session) -> list[int]:
    return [int(item["version_number"]) for item in session.project.designs]


@pytest.mark.parametrize("language", ["en", "it"])
def test_restore_asks_and_creates_a_new_version_equal_to_the_past_one(
    tmp_path: Path, language: str
) -> None:
    with design_session(tmp_path, language=language) as session:
        three_versions(session)
        spent = len(session.project.usage)
        run = session.ut("design", "restore", "2", answers=[""], language=language)
        sent = bodies(session)
        designs = list(session.project.designs)
        diff = session.project.design_diffs[-1]
        generations = len(session.project.usage)
        index = session.previews / "index.html"

    assert run.status == 0, run.errors
    assert sent == [{"version_number": 2, "locale": LOCALES[language]}]
    assert [item["version_number"] for item in designs] == [1, 2, 3, 4]
    assert designs[3]["based_on_version_number"] == 3
    assert designs[3]["package"] == designs[1]["package"]
    assert designs[3]["content_hash"] == designs[1]["content_hash"]
    assert (diff["status"], diff["decision_reason"]) == ("APPROVED", NOTES[language])
    assert diff["applied_version_id"] == designs[3]["id"]
    assert generations == spent
    about = said("design.restore_about", language, version=2, next=4)
    question = said("design.restore_confirm", language, version=2)
    assert about in run.output
    assert run.output.index(about) < run.output.index(question)
    assert said("costs.confirm", language) not in run.output
    assert said("design.previews_written", language, path=str(index.parent)) in run.output
    assert index.is_file()
    assert run.output.endswith(said("design.restored", language, version=4, restored=2) + "\n")


def test_yes_skips_the_question_and_a_version_without_a_choice_asks_for_one(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path) as session:
        three_versions(session)
        run = session.ut("--yes", "design", "restore", "1")
        designs = list(session.project.designs)

    assert run.status == 0, run.errors
    assert said("design.restore_confirm", version=1) not in run.output
    assert designs[3]["package"]["owner_selected_alternative_id"] is None
    assert designs[3]["content_hash"] == designs[0]["content_hash"]
    assert run.output.endswith(said("design.restored_choose", version=4, restored=1) + "\n")


def test_no_keeps_the_design_as_it_is(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        three_versions(session)
        run = session.ut("design", "restore", "2", answers=["n"])
        sent = bodies(session)
        versions = numbers(session)

    assert run.status == 1
    assert sent == []
    assert versions == [1, 2, 3]
    assert run.output.endswith(said("design.restore_cancelled", version=2) + "\n")


@pytest.mark.parametrize(
    ("number", "key", "values"),
    [
        ("3", "design.errors.DESIGN_RESTORE_CURRENT", {"version": 3}),
        ("9", "design.errors.DESIGN_VERSION_NOT_FOUND", {"version": 9, "versions": "1, 2, 3"}),
    ],
    ids=["current", "missing"],
)
def test_the_current_version_and_a_missing_one_are_refused_before_asking(
    tmp_path: Path, number: str, key: str, values: dict[str, object]
) -> None:
    with design_session(tmp_path) as session:
        three_versions(session)
        run = session.ut("design", "restore", number)
        sent = bodies(session)
        versions = numbers(session)

    assert run.status == 1
    assert run.errors == said(key, **values) + "\n"
    assert said("design.restore_confirm", version=int(number)) not in run.output
    assert sent == []
    assert versions == [1, 2, 3]


@pytest.mark.parametrize(
    ("status", "code", "key", "values"),
    [
        (409, "DESIGN_RESTORE_CURRENT", "design.errors.DESIGN_RESTORE_CURRENT", {"version": 2}),
        (
            404,
            "DESIGN_VERSION_NOT_FOUND",
            "design.errors.DESIGN_VERSION_NOT_FOUND",
            {"version": 2, "versions": "1, 2, 3"},
        ),
        (
            409,
            "REQUIREMENT_NO_LONGER_AVAILABLE",
            "design.errors.DESIGN_RESTORE_BLOCKED.REQUIREMENT_NO_LONGER_AVAILABLE",
            {"version": 2},
        ),
        (
            409,
            "TWIN_SET_CHANGED",
            "design.errors.DESIGN_RESTORE_BLOCKED.TWIN_SET_CHANGED",
            {"version": 2},
        ),
        (409, "DIFF_ALREADY_PENDING", "design.errors.DIFF_ALREADY_PENDING", {}),
    ],
    ids=["current", "missing", "requirements", "twins", "pending"],
)
def test_a_refusal_of_the_studio_is_explained_with_the_version(
    tmp_path: Path, status: int, code: str, key: str, values: dict[str, object]
) -> None:
    with design_session(tmp_path) as session:
        three_versions(session)
        session.studio.fail_next("POST", ROUTE, status=status, body={"detail": {"code": code}})
        run = session.ut("--yes", "design", "restore", "2")
        versions = numbers(session)

    assert run.status == 1
    assert run.errors == said(key, **values) + "\n"
    assert versions == [1, 2, 3]


def test_a_change_waiting_in_the_studio_blocks_the_restore(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        three_versions(session)
        client = session.client()
        current = design_api.current(client, session.project.id)
        assert current is not None
        package = dict(current["package"])
        package["open_questions"] = ["Is the tip visible on the small screen?"]
        design_api.propose_revision(client, session.project.id, package)
        run = session.ut("--yes", "design", "restore", "2")
        versions = numbers(session)
        pending = [item["status"] for item in session.project.design_diffs]

    assert run.status == 1
    assert run.errors == said("design.errors.DIFF_ALREADY_PENDING") + "\n"
    assert versions == [1, 2, 3]
    assert pending.count("PROPOSED") == 1


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["restore"], said("design.usage_restore")),
        (["restore", "abc"], said("design.errors.DESIGN_RESTORE_NUMBER_INVALID", value="abc")),
        (["restore", "0"], said("design.errors.DESIGN_RESTORE_NUMBER_INVALID", value="0")),
        (["restore", "2.5"], said("design.errors.DESIGN_RESTORE_NUMBER_INVALID", value="2.5")),
        (["restore", "v2"], said("design.errors.DESIGN_RESTORE_NUMBER_INVALID", value="v2")),
        (["restore", "2", "--rule", "x"], said("design.usage_rule")),
        (["restore", "2", "--screen", "SCR-001"], said("design.usage_target")),
    ],
    ids=["missing", "text", "zero", "fraction", "prefixed", "rule", "screen"],
)
def test_a_wrong_restore_is_refused_without_the_network(
    tmp_path: Path, arguments: list[str], message: str
) -> None:
    run = run_ut(["--lang", "en", "design", *arguments], tmp_path, transport=NoNetwork())

    assert run.status == 2
    assert run.errors == message + "\n"


@pytest.mark.parametrize(
    ("language", "phrases"),
    [
        ("en", ("restore N (go back to version N", "or the number of a version (for restore)")),
        (
            "it",
            ("restore N (torna alla versione N", "oppure il numero di una versione (per restore)"),
        ),
    ],
)
def test_the_help_names_the_restore_action(
    tmp_path: Path, language: str, phrases: tuple[str, str]
) -> None:
    run = run_ut(["--lang", language, "design", "--help"], tmp_path, transport=NoNetwork())
    flat = " ".join(run.output.split())

    assert run.status == 0
    for phrase in phrases:
        assert phrase in flat
