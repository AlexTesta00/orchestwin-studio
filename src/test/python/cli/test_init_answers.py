from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestwin.cli.errors import CliError
from orchestwin.cli.flows import answers

from .support.fake_studio import FakeStudio
from .support.terminal import run_ut
from .support.transports import NoNetwork
from .test_init_command import IDEA, NAME, fake_project, link_document, posted, sign_in, ut

KEYS = "mode, name, idea, answers, proposals, team, profiles, twins, requirements"


def write(tmp_path: Path, content: object, *, name: str = "answers.json") -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else json.dumps(content)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_short_file_takes_the_defaults(tmp_path: Path) -> None:
    found = answers.load(write(tmp_path, {"name": " Calcolo mancia ", "idea": IDEA}))

    assert (found.name, found.idea, found.mode) == (NAME, IDEA, None)
    assert (found.proposals, found.team, found.profiles, found.twins) == (
        "ACCEPT_ALL",
        "APPROVE",
        "CONFIRM_ALL",
        "APPROVE",
    )
    assert (found.changes, found.requirements) == ((), "APPROVE")
    assert dict(found.answers) == {}


def test_a_complete_file_is_read_as_it_is(tmp_path: Path) -> None:
    path = tmp_path / "answers.json"
    path.write_bytes(
        b"\xef\xbb\xbf"
        + json.dumps(
            {
                "mode": "DESIGN_AND_CODE",
                "name": NAME,
                "idea": IDEA,
                "answers": {"problem": "Troppi conti", "goals": ["Fare presto"], "risks": None},
                "proposals": "ACCEPT_NONE",
                "team": "STOP",
                "profiles": "CONFIRM_ALL",
                "twins": "STOP",
                "requirements": {"changes": [" Una storia in più "], "decision": "STOP"},
            }
        ).encode("utf-8")
    )

    found = answers.load(path)

    assert found.mode == "DESIGN_AND_CODE"
    assert dict(found.answers) == {"problem": "Troppi conti", "goals": ("Fare presto",)}
    assert (found.proposals, found.team, found.twins) == ("ACCEPT_NONE", "STOP", "STOP")
    assert (found.changes, found.requirements) == (("Una storia in più",), "STOP")


def test_the_reply_follows_the_type_of_the_question(tmp_path: Path) -> None:
    found = answers.load(
        write(
            tmp_path,
            {"answers": {"problem": ["Uno", "Due"], "goals": "Fare presto", "domain": "Bar"}},
        )
    )

    assert found.reply({"field": "problem", "answer_type": "TEXT"}) == {
        "kind": "TEXT",
        "text": "Uno; Due",
    }
    assert found.reply({"field": "goals", "answer_type": "ITEM_LIST"}) == {
        "kind": "ITEM_LIST",
        "items": ["Fare presto"],
    }
    assert found.reply({"field": "target_users", "answer_type": "ITEM_LIST"}) == {"kind": "UNKNOWN"}
    assert found.reply({"field": None, "answer_type": "TEXT"}) == {"kind": "UNKNOWN"}


WRONG = [
    ({"color": "blue"}, "the key `color` does not exist. The possible keys here are: " + KEYS),
    ({"answers": {"problems": "x"}}, "the key `answers.problems` does not exist."),
    (
        {"team": "YES"},
        'the key `team` is "YES", but it must be one of these values: APPROVE, STOP.',
    ),
    ({"mode": "CODE_ONLY"}, "must be one of these values: DESIGN_ONLY, DESIGN_AND_CODE."),
    ({"profiles": "REJECT_ALL"}, "the key `profiles` is"),
    ({"name": ""}, "the key `name` must be a text that is not empty, of at most 120 characters."),
    ({"idea": 42}, "the key `idea` must be a text that is not empty, of at most 2000 characters."),
    ({"answers": {"goals": []}}, "the key `answers.goals` must be a text or a list of texts"),
    ({"answers": {"goals": [1, 2]}}, "the key `answers.goals` must be a text or a list of texts"),
    ({"answers": ["x"]}, "the key `answers` must be a JSON object"),
    (
        {"requirements": {"changes": ["ok", " "]}},
        "the key `requirements.changes[2]` must be a text that is not empty",
    ),
    ({"requirements": {"decision": "LATER"}}, "the key `requirements.decision` is"),
    ({"requirements": {"order": 1}}, "the key `requirements.order` does not exist."),
    ({"requirements": "APPROVE"}, "the key `requirements` must be a JSON object"),
    ([1, 2], "must hold a JSON object, between curly brackets."),
    ("{not json", "is not a valid JSON document in UTF-8."),
]


@pytest.mark.parametrize(("content", "words"), WRONG)
def test_a_wrong_file_is_a_usage_error_that_names_the_key(
    tmp_path: Path, content: object, words: str
) -> None:
    path = write(tmp_path, content)

    run = run_ut(["init", "--answers", str(path)], tmp_path, transport=NoNetwork())

    assert run.status == 2
    assert f"answers file {path}" in run.errors
    assert words in run.errors
    assert run.output == ""


def test_a_missing_file_is_a_usage_error(tmp_path: Path) -> None:
    run = run_ut(["init", "--answers", "missing.json"], tmp_path, transport=NoNetwork())

    assert run.status == 2
    assert "The answers file" in run.errors
    assert "missing.json cannot be read" in run.errors


@pytest.mark.parametrize(("content", "key"), [({"idea": IDEA}, "name"), ({"name": NAME}, "idea")])
def test_a_new_project_needs_a_name_and_an_idea(
    tmp_path: Path, content: dict[str, str], key: str
) -> None:
    path = write(tmp_path, content)

    run = run_ut(["init", "--answers", str(path)], tmp_path, transport=NoNetwork())

    assert run.status == 2
    assert f"lacks the key `{key}`, which is needed to create a new project" in run.errors
    assert f"use the option --{key}" in run.errors


def test_the_options_win_over_the_file(tmp_path: Path) -> None:
    path = write(
        tmp_path, {"name": "Altro nome", "idea": "Un'altra idea", "mode": "DESIGN_AND_CODE"}
    )
    options = ["--answers", str(path), "--name", NAME, "--idea", IDEA, "--mode", "design"]
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, *options, "--until", "brief")

        assert run.status == 0, run.errors
        assert fake_project(studio, tmp_path).name == NAME
        assert posted(studio, "/brief-dialogue") == [{"statement": IDEA}]
        assert link_document(tmp_path)["mode"] == "DESIGN_ONLY"


def test_without_yes_the_spending_of_the_whole_path_is_refused(tmp_path: Path) -> None:
    path = write(tmp_path, {"name": NAME, "idea": IDEA})
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, "--answers", str(path))

        assert run.status == 5
        assert posted(studio, "/projects") == []
        assert not (tmp_path / "project" / ".orchestwin").exists()
    assert "Estimate: 0.48-0.72 USD, about 5 min." in run.output
    assert "With --answers no question is asked, so the spending must be confirmed with --yes" in (
        run.errors
    )


def test_below_the_threshold_a_file_in_the_working_folder_needs_no_yes(tmp_path: Path) -> None:
    write(tmp_path / "project", {"name": NAME, "idea": IDEA}, name="path.json")
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, "--answers", "path.json", "--until", "brief")

        assert run.status == 0, run.errors
        assert fake_project(studio, tmp_path).approved("brief")
    assert "Estimate: 0.09 USD, about 1 min." in run.output


def test_the_missing_key_error_is_raised_with_the_values_of_the_sentence(tmp_path: Path) -> None:
    found = answers.load(write(tmp_path, {}))

    error = found.missing("idea")

    assert isinstance(error, CliError)
    assert (error.code, error.status) == ("ANSWERS_FILE_INVALID", 2)
    assert dict(error.values) == {"path": found.path, "entry": "idea", "reason": "missing"}
