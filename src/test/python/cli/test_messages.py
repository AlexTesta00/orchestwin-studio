from __future__ import annotations

import ast
import re
import string
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

import orchestwin.cli
from orchestwin.cli import messages as messages_module
from orchestwin.cli.api.projects import NEXT_COMMANDS, STAGES
from orchestwin.cli.commands import COMMANDS
from orchestwin.cli.commands.status import MODE_KEYS, REASONS, STATE_KEYS
from orchestwin.cli.console import OUTCOME_KEYS, Console
from orchestwin.cli.errors import STATUSES
from orchestwin.cli.jobs import STAGE_KEYS
from orchestwin.cli.messages import (
    FILES,
    LANGUAGES,
    MESSAGES,
    known,
    resolve_language,
    template,
    text,
)
from orchestwin.projects.progress import ProjectNextAction

from .support.terminal import environment
from .support.transports import NoNetwork

PACKAGE = Path(orchestwin.cli.__file__).parent
STUDIO = PACKAGE.parent
MESSAGES_FOLDER = "messages"
RUNTIME_FILES = ("common", "costs", "errors", "jobs", "login", "logout", "status")
KEY_CALLS = frozenset({"say", "error", "ask", "ask_text", "confirm", "choose", "secret", "text"})
ERROR_TYPES = frozenset({"CliError", "ApiFailure"})
KEY_PATTERN = re.compile(r"^[a-z][a-z_]*\.[A-Za-z0-9_.]+$")


def placeholders(sentence: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(sentence) if name is not None}


def calls() -> Iterator[tuple[Path, ast.Call]]:
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                yield path, node


def called(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def literal(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def used_keys() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path, node in calls():
        candidates = []
        if called(node) in KEY_CALLS and node.args:
            candidates.append(literal(node.args[0]))
        candidates.extend(literal(item.value) for item in node.keywords if item.arg == "help")
        for candidate in candidates:
            if candidate is not None and KEY_PATTERN.match(candidate):
                found.add((path.relative_to(PACKAGE).as_posix(), candidate))
    return found


def raised_codes() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path, node in calls():
        if called(node) in ERROR_TYPES and node.args:
            code = literal(node.args[0])
            if code is not None:
                found.add((path.relative_to(PACKAGE).as_posix(), code))
    return found


def has_error_message(code: str) -> bool:
    return known(f"errors.{code}") or any(key.endswith(f".errors.{code}") for key in MESSAGES)


def code_strings() -> tuple[set[str], set[str]]:
    literals: set[str] = set()
    prefixes: set[str] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        if MESSAGES_FOLDER in path.relative_to(PACKAGE).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.add(node.value)
            elif isinstance(node, ast.JoinedStr) and node.values:
                first = literal(node.values[0])
                if first is not None and first.endswith("_"):
                    prefixes.add(first)
    return literals, prefixes


def studio_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(STUDIO.rglob("*.py"))
        if PACKAGE not in path.parents
    )


def key_used(
    key: str, literals: set[str], prefixes: set[str], raised: set[str], studio: str
) -> bool:
    if key in literals:
        return True
    name, _, rest = key.partition(".")
    if name == "errors":
        code, _, reason = rest.partition(".")
        if reason and reason not in literals:
            return False
        return code in STATUSES or code in raised or f'"{code}"' in studio
    if rest == "help":
        return any(name == module.NAME for module in COMMANDS)
    return any(key.startswith(prefix) for prefix in prefixes)


def test_every_key_has_both_languages_and_the_same_placeholders() -> None:
    for key, entry in MESSAGES.items():
        assert set(entry) == set(LANGUAGES), key
        assert all(isinstance(entry[language], str) and entry[language] for language in LANGUAGES)
        assert placeholders(entry["it"]) == placeholders(entry["en"]), key


def test_the_keys_of_a_file_start_with_its_name_and_are_never_repeated() -> None:
    for name, catalogue in FILES.items():
        assert all(key.startswith(f"{name}.") for key in catalogue), name
    assert sum(len(catalogue) for catalogue in FILES.values()) == len(MESSAGES)


def test_every_key_used_in_the_code_exists() -> None:
    keys = used_keys()

    assert len(keys) > 40
    assert [f"{path}: {key}" for path, key in sorted(keys) if not known(key)] == []


def test_every_error_raised_in_the_code_has_a_sentence() -> None:
    codes = raised_codes()

    assert {"STUDIO_UNREACHABLE", "INPUT_CLOSED", "FOLDER_NOT_VERIFIED"} <= {
        code for _, code in codes
    }
    assert [f"{path}: {code}" for path, code in sorted(codes) if not has_error_message(code)] == []


def test_every_fixed_code_has_a_sentence() -> None:
    assert [code for code in STATUSES if not known(f"errors.{code}")] == []
    assert known("errors.UNKNOWN")
    assert known("errors.UNEXPECTED")
    assert known("errors.FOLDER_NOT_VERIFIED.LINE_ENDINGS")


def test_every_command_with_its_own_messages_has_a_help_text() -> None:
    for module in COMMANDS:
        own = [key for key in MESSAGES if key.startswith(f"{module.NAME}.")]
        if own:
            assert known(f"{module.NAME}.help"), module.NAME
    assert all(known(f"{name}.help") for name in ("login", "logout", "status"))


def test_keys_built_at_run_time_exist() -> None:
    expected = [
        *(f"common.next_{action.value.lower()}" for action in ProjectNextAction),
        *(f"common.stage_{stage}" for stage in STAGES),
        *STATE_KEYS.values(),
        *MODE_KEYS.values(),
        *(f"status.offline_{reason}" for reason in REASONS),
        *STAGE_KEYS.values(),
        *OUTCOME_KEYS.values(),
        "jobs.stage_waiting",
        "common.next_unknown",
    ]

    assert [key for key in expected if not known(key)] == []


def test_no_key_of_the_runtime_files_is_unused() -> None:
    literals, prefixes = code_strings()
    raised = {code for _, code in raised_codes()}
    studio = studio_source()

    unused = [
        key
        for name in RUNTIME_FILES
        for key in FILES[name]
        if not key_used(key, literals, prefixes, raised, studio)
    ]

    assert unused == []
    assert {"common.next_", "common.stage_", "status.offline_"} <= prefixes
    for missing in (
        "common.never_used",
        "errors.NO_SUCH_CODE",
        "errors.FOLDER_NOT_VERIFIED.NO_SUCH_REASON",
        "status.help_text",
    ):
        assert not key_used(missing, literals, prefixes, raised, studio), missing


def test_every_next_action_of_the_studio_names_a_command() -> None:
    assert set(NEXT_COMMANDS) == {action.value for action in ProjectNextAction}
    for action, command in NEXT_COMMANDS.items():
        for language in LANGUAGES:
            assert f"`{command}`" in text(f"common.next_{action.lower()}", language)


def test_text_fills_the_placeholders_and_survives_mistakes() -> None:
    assert text("login.done", "it", email="a@example.test", studio="http://127.0.0.1:9") == (
        "Accesso eseguito come a@example.test sullo Studio http://127.0.0.1:9."
    )
    assert text("login.done", "en", email="a@example.test") == (
        "Signed in as a@example.test to the Studio {studio}."
    )
    assert text("no.such_key", "it") == "no.such_key"
    assert text("common.interrupted", "fr") == "Interrupted."


def test_placeholders_may_be_called_key_and_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = {"it": "chiave {key}, lingua {language}", "en": "key {key}, language {language}"}
    catalogue = MappingProxyType({**MESSAGES, "sample.values": sample})
    monkeypatch.setattr(messages_module, "MESSAGES", catalogue)
    console = Console(environment(tmp_path, transport=NoNetwork()), language="en", color=False)

    assert text("sample.values", "it", key="brief", language="fr") == "chiave brief, lingua fr"
    console.say("sample.values", key="team", language="de")
    console.error("sample.values", key="twins", language="es")
    assert console.environment.stdout.getvalue() == "key team, language de\n"
    assert console.environment.stderr.getvalue() == "key twins, language es\n"
    with pytest.raises(TypeError):
        text(key="sample.values", language="en")


def test_a_template_is_the_raw_sentence() -> None:
    assert template("login.done", "it") == "Accesso eseguito come {email} sullo Studio {studio}."
    assert template("login.done", "fr") == "Signed in as {email} to the Studio {studio}."
    assert template("no.such_key", "en") is None


@pytest.mark.parametrize(
    ("option", "variable", "system", "expected"),
    [
        ("it", "en", "en_US", "it"),
        (None, "it", "en_US", "it"),
        (None, None, "it_IT", "it"),
        (None, None, "en_GB", "en"),
        (None, None, "fr_FR", "en"),
        (None, None, None, "en"),
        ("en", "it", "it_IT", "en"),
        (None, "  ", "it_CH", "it"),
    ],
)
def test_the_language_comes_from_option_then_variable_then_machine(
    tmp_path: Path, option: str | None, variable: str | None, system: str | None, expected: str
) -> None:
    base = environment(tmp_path, transport=NoNetwork(), language=system)
    variables = dict(base.variables)
    if variable is not None:
        variables["ORCHESTWIN_LANG"] = variable

    assert resolve_language(option, replace(base, variables=variables)) == expected
