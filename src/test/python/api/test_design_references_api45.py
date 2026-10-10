from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from orchestwin.api import design_iterations, design_mockups
from orchestwin.api.app import create_app
from orchestwin.api.services import ApplicationRuntime
from orchestwin.artifacts.design_references import DEFAULT_REFERENCES_DIR
from orchestwin.artifacts.visual_icons import mockup_resources
from orchestwin.config import DESIGN_REFERENCES_VARIABLE, ApplicationSettings, load_settings
from orchestwin.models.generated_mockup_instructions import ITERATION_SENTENCE, REFERENCE_SENTENCE
from orchestwin.models.proposal_generation import ProposalGenerator
from orchestwin.models.structured_generation import MAX_ATTACHMENTS
from src.test.python.api.test_design_iterations_api import applied_versions, iterate
from src.test.python.api.test_design_redraw44 import (
    REDRAW_REQUEST,
    Attaching,
    CritiqueDatabase,
    MemoryCritiques,
    SubscriptionPort,
    page_source,
    redraw_runtime,
)
from src.test.python.api.test_generated_mockup_api import client_for, generated
from src.test.python.artifacts.test_design_critique44 import jpeg, png
from src.test.python.models.test_generated_mockup_support import (
    DesignVersions,
    MemoryMockupStore,
    answer,
    draft_payload,
    iteration_payload,
    package,
    runtime,
)
from src.test.python.models.test_hosted_support import claude_code_document, providers

LOGGER = "orchestwin.artifacts.design_references"
HOME = png(64, 48)
BOARD = jpeg(390, 844)
SPARE = png(32, 32)
NOTE = b"Mi piace il ritmo\n delle card  e i numeri grandi"
NORMALIZED_NOTE = "Mi piace il ritmo delle card e i numeri grandi"
SCREENS = [
    {"code": "REF-001", "file": "reference-001.png", "label": "a-home.png"},
    {"code": "REF-002", "file": "reference-002.jpg", "label": "b-board.jpg"},
]
BOTH = [
    ("reference-001.png", "image/png", HOME),
    ("reference-002.jpg", "image/jpeg", BOARD),
]


class Subscribed(Attaching):
    def __init__(self, *outcomes):
        super().__init__(*outcomes)
        self.configuration = providers(claude_code_document()).hosted_model("design")


@pytest.fixture
def studio(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    directory = tmp_path / "studio"
    directory.mkdir()
    monkeypatch.chdir(directory)
    return directory


@pytest.fixture
def critiques(monkeypatch):
    monkeypatch.setattr(design_iterations, "SqlAlchemyDesignCritiqueRepository", MemoryCritiques)


def folder(path: Path, files: dict[str, bytes]) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (path / name).write_bytes(content)
    return path


def references(tmp_path, files=None) -> Path:
    files = {"b-board.jpg": BOARD, "a-home.png": HOME, "note.txt": NOTE} if files is None else files
    return folder(tmp_path / "examples", files)


def sent(options) -> list[tuple[str, str, bytes]]:
    return [(item.name, item.media_type, item.content) for item in options["attachments"]]


def mockup(generator, store=None, **runtime_values):
    versions = DesignVersions(package())
    value = runtime(generator, store, versions)
    for name, item in runtime_values.items():
        setattr(value, name, item)
    client, registry = client_for(value)
    with client:
        return generated(client, registry, versions)


def created(settings=None, **options):
    return create_app(settings, **options).state.application_runtime.design_references_dir


def test_every_test_starts_with_the_references_turned_off():
    assert os.environ[DESIGN_REFERENCES_VARIABLE] == ""
    assert load_settings(env_file=None).design_references_dir is None


def test_the_folder_of_the_references_is_a_setting_of_the_studio(studio, tmp_path, monkeypatch):
    assert load_settings(env_file=None).design_references_dir == Path(DEFAULT_REFERENCES_DIR)
    (studio / ".env").write_text(
        f"{DESIGN_REFERENCES_VARIABLE}=shared/examples\n", encoding="utf-8"
    )
    assert load_settings().design_references_dir == Path("shared/examples")
    monkeypatch.setenv(DESIGN_REFERENCES_VARIABLE, str(tmp_path / "examples"))
    assert load_settings().design_references_dir == tmp_path / "examples"
    monkeypatch.setenv(DESIGN_REFERENCES_VARIABLE, " ")
    assert load_settings().design_references_dir is None
    chosen = ApplicationSettings(design_references_dir=tmp_path, _env_file=None)
    assert chosen.design_references_dir == tmp_path


def test_the_application_decides_the_folder_when_it_is_created(studio, tmp_path):
    directory = references(tmp_path)

    assert created(ApplicationSettings(_env_file=None)) == studio / DEFAULT_REFERENCES_DIR
    assert created(ApplicationSettings(design_references_dir="shared", _env_file=None)) == (
        studio / "shared"
    )
    assert created(ApplicationSettings(design_references_dir=directory, _env_file=None)) == (
        directory
    )
    assert created(ApplicationSettings(design_references_dir=None, _env_file=None)) is None
    explicit = ApplicationSettings(design_references_dir=directory, _env_file=None)
    assert created(explicit, runtime=ApplicationRuntime()) is None


def test_the_variable_chooses_the_folder_and_its_images_reach_the_model(
    studio, tmp_path, monkeypatch
):
    directory = references(tmp_path)
    monkeypatch.setenv(DESIGN_REFERENCES_VARIABLE, str(directory))
    chosen = created()
    generator = Subscribed(answer(draft_payload()))

    done = mockup(generator, design_references_dir=chosen)

    assert chosen == directory
    assert done["status"] == "SUCCEEDED", done["failure"]
    [options] = generator.options
    assert sent(options) == BOTH
    [call] = generator.calls
    assert call["context"]["reference"] == {"note": NORMALIZED_NOTE, "screens": SCREENS}
    assert call["context"]["resources"] == mockup_resources()
    assert call["instruction"].count(REFERENCE_SENTENCE) == 1


def test_only_two_valid_references_reach_the_model_and_a_broken_one_is_logged(tmp_path, caplog):
    directory = references(
        tmp_path,
        {"1-broken.png": b"broken", "2-home.png": HOME, "3-board.jpg": BOARD, "4-spare.png": SPARE},
    )
    generator = Subscribed(answer(draft_payload()))

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        done = mockup(generator, design_references_dir=directory)

    assert done["status"] == "SUCCEEDED", done["failure"]
    [options] = generator.options
    assert sent(options) == BOTH
    reference = generator.calls[0]["context"]["reference"]
    assert reference["note"] is None
    assert [screen["label"] for screen in reference["screens"]] == ["2-home.png", "3-board.jpg"]
    [warning] = [record.getMessage() for record in caplog.records if record.name == LOGGER]
    assert "1-broken.png" in warning
    assert str(directory) not in caplog.text


@pytest.mark.parametrize(
    "case", ["not in the runtime", "turned off", "missing", "empty", "only a note"]
)
def test_without_references_the_mockup_is_generated_as_before(case, tmp_path):
    if case == "not in the runtime":
        values = {}
    elif case == "turned off":
        values = {"design_references_dir": None}
    elif case == "missing":
        values = {"design_references_dir": tmp_path / "missing"}
    else:
        files = {} if case == "empty" else {"note.txt": NOTE, "logo.gif": b"GIF"}
        values = {"design_references_dir": references(tmp_path, files)}
    generator = Subscribed(answer(draft_payload()))

    done = mockup(generator, **values)

    assert done["status"] == "SUCCEEDED", done["failure"]
    [options] = generator.options
    assert "attachments" not in options
    [call] = generator.calls
    assert "reference" not in call["context"]
    assert call["context"]["resources"] == mockup_resources()
    assert REFERENCE_SENTENCE not in call["instruction"]


def test_a_route_without_claude_code_never_reads_the_folder(tmp_path, monkeypatch):
    def unexpected(*_arguments, **_options):
        raise AssertionError("the folder of the references was read")

    monkeypatch.setattr(design_mockups, "load_design_references", unexpected)
    generator = Attaching(answer(draft_payload()))

    done = mockup(generator, design_references_dir=references(tmp_path))

    assert done["status"] == "SUCCEEDED", done["failure"]
    [options] = generator.options
    assert "attachments" not in options
    [call] = generator.calls
    assert "reference" not in call["context"]
    assert call["context"]["resources"] == mockup_resources()
    assert REFERENCE_SENTENCE not in call["instruction"]


def test_an_iteration_on_claude_code_carries_the_references(tmp_path):
    versions = applied_versions()
    generator = Subscribed(answer(iteration_payload()))
    value = runtime(generator, versions=versions)
    value.design_references_dir = references(tmp_path)
    client, registry = client_for(value)

    with client:
        _started, done = iterate(client, registry, versions)

    assert done["status"] == "SUCCEEDED", done["failure"]
    [options] = generator.options
    assert sent(options) == BOTH
    [call] = generator.calls
    assert "current_mockup" in call["context"]
    assert call["context"]["reference"] == {"note": NORMALIZED_NOTE, "screens": SCREENS}
    assert call["context"]["resources"] == mockup_resources()
    assert call["instruction"].count(REFERENCE_SENTENCE) == 1
    assert ITERATION_SENTENCE in call["instruction"]


def test_a_redraw_on_claude_code_sends_the_screenshots_first_and_the_references_after(
    critiques, tmp_path
):
    source, contents = page_source()
    versions = applied_versions()
    generator = Subscribed(answer(iteration_payload()))
    value = redraw_runtime(generator, versions, CritiqueDatabase((source, contents)))
    value.design_references_dir = references(
        tmp_path, {"a-home.png": HOME, "b-board.jpg": BOARD, "c.png": SPARE}
    )
    client, registry = client_for(value)

    with client:
        _started, done = iterate(
            client, registry, versions, request=REDRAW_REQUEST, critique_source_id=str(source.id)
        )

    assert done["status"] == "SUCCEEDED", done["failure"]
    [options] = generator.options
    assert sent(options) == [
        ("screenshot-001.png", "image/png", contents["SCR-001"]),
        ("screenshot-002.jpg", "image/jpeg", contents["SCR-002"]),
        *BOTH,
    ]
    assert len(options["attachments"]) == MAX_ATTACHMENTS
    context = generator.calls[0]["context"]
    assert [screen["file"] for screen in context["redraw"]["screens"]] == [
        "screenshot-001.png",
        "screenshot-002.jpg",
    ]
    assert context["reference"] == {"note": None, "screens": SCREENS}


def test_the_real_generator_sends_the_references_and_the_evidence_keeps_their_references(
    tmp_path,
):
    port = SubscriptionPort(draft_payload())
    generator = ProposalGenerator(providers(claude_code_document()).hosted_model("design"), port)
    store = MemoryMockupStore()
    directory = references(tmp_path, {"a-home.png": HOME, "note.txt": NOTE})

    done = mockup(generator, store, design_references_dir=directory)

    assert done["status"] == "SUCCEEDED", done["failure"]
    [request] = port.requests
    [attachment] = request.attachments
    assert (attachment.name, attachment.media_type, attachment.content) == BOTH[0]
    assert request.to_snapshot()["attachments"] == [attachment.reference()]
    context = json.loads(request.input_payload_json)["context"]
    assert context["reference"] == {"note": NORMALIZED_NOTE, "screens": SCREENS[:1]}
    assert context["resources"] == json.loads(json.dumps(mockup_resources()))
    assert REFERENCE_SENTENCE in request.system_instruction
    [generation_id] = store.order
    assert store.requests[generation_id][0].attachments == request.attachments
