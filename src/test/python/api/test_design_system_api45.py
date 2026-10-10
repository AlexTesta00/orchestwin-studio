from __future__ import annotations

import os
from dataclasses import replace

import pytest

from orchestwin.api.app import create_app
from orchestwin.api.runtime_configuration import RuntimeConfigurationError
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import (
    DESIGN_SYSTEM_DEFAULT,
    DESIGN_SYSTEM_OFF,
    DESIGN_SYSTEM_VARIABLE,
    ApplicationSettings,
    load_settings,
)
from orchestwin.models.design_systems import (
    APPLE_HIG,
    DESIGN_SYSTEM_ENV,
    DESIGN_SYSTEMS,
    design_system,
    design_system_view,
)
from orchestwin.models.generated_mockup_instructions import ITERATION_SENTENCE
from src.test.python.api.test_design_iterations_api import BROKEN, applied_versions, iterate
from src.test.python.api.test_generated_mockup_api import client_for, generated, wired_runtime
from src.test.python.models.test_generated_mockup_support import (
    GUIDED_ID,
    DesignVersions,
    ScriptedMockupGenerator,
    answer,
    draft_payload,
    iteration_payload,
    package,
    runtime,
    with_markup,
)

APPLE = "apple-hig"
UNKNOWN = "material-you"
OFF_VALUES = ("", " ", "none", "NONE", " None ")
SECTION = "Design system: "
BROKEN_MOCKUP = with_markup(draft_payload(), "<h1>", "<h1>Lorem ipsum ")


@pytest.fixture
def studio(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    directory = tmp_path / "studio"
    directory.mkdir()
    monkeypatch.chdir(directory)
    return directory


def created(settings=None, **options):
    return create_app(settings, **options).state.application_runtime.design_system


def with_system(value, case):
    if case != "not in the runtime":
        value.design_system = None if case == "turned off" else APPLE_HIG
    return value


def followed(value):
    return replace(
        value,
        alternatives=tuple(
            replace(item, visual_language=replace(item.visual_language, design_system=APPLE))
            if item.id == GUIDED_ID
            else item
            for item in value.alternatives
        ),
    )


def drawn_alternative(versions):
    current = versions.versions[-1].package
    return next(item for item in current.alternatives if item.id == GUIDED_ID)


def mockup(generator, case="apple", follows=False):
    versions = DesignVersions(followed(package()) if follows else package())
    assert drawn_alternative(versions).visual_language.design_system == (APPLE if follows else None)
    client, registry = client_for(with_system(runtime(generator, versions=versions), case))
    with client:
        return generated(client, registry, versions)


def iteration(generator, case="apple", follows=False):
    versions = applied_versions()
    if follows:
        versions = DesignVersions(*(followed(item.package) for item in versions.versions))
    assert drawn_alternative(versions).visual_language.design_system == (APPLE if follows else None)
    client, registry = client_for(with_system(runtime(generator, versions=versions), case))
    with client:
        return iterate(client, registry, versions)[1]


def assert_asked_with_the_system(call):
    assert call["context"]["design_system"] == design_system_view(APPLE_HIG)
    assert call["instruction"].count(APPLE_HIG.instruction) == 1
    assert f"{SECTION}{APPLE_HIG.name}" in call["instruction"]


def assert_asked_as_before(call):
    assert "design_system" not in call["context"]
    assert APPLE_HIG.instruction not in call["instruction"]
    assert SECTION not in call["instruction"]


def test_every_test_starts_with_the_design_system_turned_off():
    assert os.environ[DESIGN_SYSTEM_VARIABLE] == ""
    assert load_settings(env_file=None).design_system is None


def test_without_the_variable_the_studio_uses_the_apple_system(studio):
    assert DESIGN_SYSTEM_VARIABLE == DESIGN_SYSTEM_ENV
    assert DESIGN_SYSTEM_VARIABLE not in os.environ
    assert DESIGN_SYSTEM_DEFAULT == APPLE == APPLE_HIG.identifier
    assert DESIGN_SYSTEM_DEFAULT in DESIGN_SYSTEMS
    assert load_settings(env_file=None).design_system == APPLE
    assert load_settings().design_system == APPLE
    assert ApplicationSettings(_env_file=None).design_system == APPLE


def test_the_design_system_is_a_setting_of_the_studio(studio, monkeypatch):
    assert DESIGN_SYSTEM_OFF == "none"
    (studio / ".env").write_text(f"{DESIGN_SYSTEM_VARIABLE}={APPLE}\n", encoding="utf-8")
    assert load_settings().design_system == APPLE
    monkeypatch.setenv(DESIGN_SYSTEM_VARIABLE, f"  {APPLE} ")
    assert load_settings().design_system == APPLE
    monkeypatch.setenv(DESIGN_SYSTEM_VARIABLE, " ")
    assert load_settings().design_system is None
    assert ApplicationSettings(design_system=APPLE, _env_file=None).design_system == APPLE
    assert ApplicationSettings(design_system="", _env_file=None).design_system is None
    assert ApplicationSettings(design_system=None, _env_file=None).design_system is None


@pytest.mark.parametrize("value", OFF_VALUES)
@pytest.mark.parametrize("source", ["settings", "variable", "dotenv"])
def test_an_empty_value_or_none_turns_the_design_system_off(studio, monkeypatch, source, value):
    settings = None
    if source == "settings":
        settings = ApplicationSettings(design_system=value, _env_file=None)
    elif source == "variable":
        monkeypatch.setenv(DESIGN_SYSTEM_VARIABLE, value)
    else:
        (studio / ".env").write_text(f"{DESIGN_SYSTEM_VARIABLE}={value}\n", encoding="utf-8")

    chosen = load_settings() if settings is None else settings

    assert chosen.design_system is None
    assert created(settings) is None


def test_the_application_resolves_the_design_system_when_it_is_created(studio, monkeypatch):
    assert created() == APPLE_HIG == design_system(APPLE) == DESIGN_SYSTEMS[APPLE]
    assert created(ApplicationSettings(_env_file=None)) == APPLE_HIG
    assert created(ApplicationSettings(design_system=APPLE, _env_file=None)) == APPLE_HIG
    assert created(ApplicationSettings(design_system=None, _env_file=None)) is None
    explicit = ApplicationSettings(design_system=APPLE, _env_file=None)
    assert created(explicit, runtime=ApplicationRuntime()) is None
    monkeypatch.setenv(DESIGN_SYSTEM_VARIABLE, DESIGN_SYSTEM_OFF)
    assert created() is None
    monkeypatch.setenv(DESIGN_SYSTEM_VARIABLE, APPLE)
    assert created() == APPLE_HIG
    assert ApplicationRuntime().design_system is None


@pytest.mark.parametrize("source", ["settings", "variable", "dotenv"])
def test_an_unknown_design_system_stops_the_studio_when_it_starts(studio, monkeypatch, source):
    settings = None
    if source == "settings":
        settings = ApplicationSettings(design_system=UNKNOWN, _env_file=None)
    elif source == "variable":
        monkeypatch.setenv(DESIGN_SYSTEM_VARIABLE, UNKNOWN)
    else:
        (studio / ".env").write_text(f"{DESIGN_SYSTEM_VARIABLE}={UNKNOWN}\n", encoding="utf-8")

    with pytest.raises(RuntimeConfigurationError) as raised:
        create_app(settings)

    message = str(raised.value)
    assert message.startswith("DESIGN_SYSTEM_UNKNOWN")
    assert DESIGN_SYSTEM_VARIABLE in message
    assert all(identifier in message for identifier in DESIGN_SYSTEMS)
    assert f"or be {DESIGN_SYSTEM_OFF} to turn it off" in message
    assert UNKNOWN not in message
    assert raised.value.__cause__ is None


def test_the_variable_chooses_the_design_system_of_the_mockups(studio, monkeypatch):
    monkeypatch.setenv(DESIGN_SYSTEM_VARIABLE, APPLE)
    versions = DesignVersions(followed(package()))
    assert drawn_alternative(versions).visual_language.design_system == APPLE
    generator = ScriptedMockupGenerator(answer(draft_payload()))
    value, _team = wired_runtime(generator, versions)
    value.design_system = created()
    client, registry = client_for(value)

    with client:
        done = generated(client, registry, versions)

    assert done["status"] == "SUCCEEDED", done["failure"]
    [call] = generator.calls
    assert_asked_with_the_system(call)


def test_a_mockup_keeps_the_design_system_on_its_second_attempt():
    generator = ScriptedMockupGenerator(answer(BROKEN_MOCKUP), answer(draft_payload()))

    done = mockup(generator, follows=True)

    assert done["status"] == "SUCCEEDED", done["failure"]
    first, second = generator.calls
    assert "rejection" in second["context"]
    for call in (first, second):
        assert_asked_with_the_system(call)


def test_an_iteration_carries_the_design_system_on_every_attempt():
    generator = ScriptedMockupGenerator(answer(BROKEN), answer(iteration_payload()))

    done = iteration(generator, follows=True)

    assert done["status"] == "SUCCEEDED", done["failure"]
    first, second = generator.calls
    assert "rejection" in second["context"]
    for call in (first, second):
        assert "current_mockup" in call["context"]
        assert ITERATION_SENTENCE in call["instruction"]
        assert_asked_with_the_system(call)


@pytest.mark.parametrize("case", ["not in the runtime", "turned off"])
def test_without_a_design_system_the_mockups_and_the_iterations_are_asked_as_before(case):
    drawn = ScriptedMockupGenerator(answer(draft_payload()))
    changed = ScriptedMockupGenerator(answer(iteration_payload()))

    done = mockup(drawn, case), iteration(changed, case)

    assert [item["status"] for item in done] == ["SUCCEEDED", "SUCCEEDED"]
    [first] = drawn.calls
    [second] = changed.calls
    assert_asked_as_before(first)
    assert_asked_as_before(second)
    assert ITERATION_SENTENCE in second["instruction"]


def test_an_alternative_without_the_design_system_is_asked_as_before_with_the_system_on():
    drawn = ScriptedMockupGenerator(answer(draft_payload()))
    changed = ScriptedMockupGenerator(answer(iteration_payload()))

    done = mockup(drawn, "apple"), iteration(changed, "apple")

    assert [item["status"] for item in done] == ["SUCCEEDED", "SUCCEEDED"]
    [first] = drawn.calls
    [second] = changed.calls
    assert_asked_as_before(first)
    assert_asked_as_before(second)
    assert ITERATION_SENTENCE in second["instruction"]
