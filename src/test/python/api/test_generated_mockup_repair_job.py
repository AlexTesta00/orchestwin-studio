from __future__ import annotations

from src.test.python.api.test_generated_mockup_api import client_for, generated
from src.test.python.models.test_generated_mockup_support import (
    DesignVersions,
    MemoryMockupStore,
    ScriptedMockupGenerator,
    answer,
    draft_payload,
    package,
    runtime,
    with_markup,
)

LOGO = '<img src="https://example.org/logo.png" alt="Logo">'


def test_the_answer_of_a_job_shows_the_notes_of_the_repair_and_needs_one_generation():
    versions = DesignVersions(package())
    store = MemoryMockupStore()
    slipped = with_markup(draft_payload(), "<h1>", LOGO + '<h1 style="color:red">')
    generator = ScriptedMockupGenerator(answer(slipped))
    client, registry = client_for(runtime(generator, store, versions))
    with client:
        done = generated(client, registry, versions)
    assert done["status"] == "SUCCEEDED"
    assert done["attempt"] == 1
    assert len(generator.calls) == 1
    warnings = done["result"]["warnings"]
    for screen in ("SCR-001", "SCR-002", "SCR-003", "SCR-004"):
        assert {"code": "ELEMENT_REMOVED", "screen_code": screen, "detail": "img"} in warnings
        assert {"code": "ATTRIBUTE_REMOVED", "screen_code": screen, "detail": "style"} in warnings
    [generation] = store.order
    assert store.payload(generation, "ADAPTER_ACCEPTED")["result"]["warnings"] == warnings
    screens = done["result"]["package"]["generated_mockup"]["mockup"]["screens"]
    assert not any("<img" in item["markup"] or "style=" in item["markup"] for item in screens)


def test_an_answer_with_nothing_to_repair_reaches_the_job_without_notes():
    versions = DesignVersions(package())
    generator = ScriptedMockupGenerator(answer(draft_payload()))
    client, registry = client_for(runtime(generator, versions=versions))
    with client:
        done = generated(client, registry, versions)
    assert done["status"] == "SUCCEEDED"
    assert done["result"]["warnings"] == []
