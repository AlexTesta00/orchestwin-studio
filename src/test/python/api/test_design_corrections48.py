from __future__ import annotations

from orchestwin.api.design import DesignPackagePayload
from orchestwin.api.design_iterations import iteration_items
from orchestwin.artifacts.generated_mockup_contrast import (
    CONTROL_BORDER_REPLACED,
    TEXT_COLOUR_REPLACED,
)
from src.test.python.api.test_design_iterations_api import ITERATIONS, applied_versions, iterate
from src.test.python.api.test_generated_mockup_api import MOCKUPS, client_for, generated
from src.test.python.artifacts.test_generated_mockup_corrections48 import WEAK_BORDER
from src.test.python.models.test_generated_mockup_binding import FAINT, bind
from src.test.python.models.test_generated_mockup_support import (
    GUIDED_ID,
    DesignVersions,
    MemoryMockupStore,
    ScriptedMockupGenerator,
    answer,
    draft_payload,
    iteration_payload,
    package,
    runtime,
)

LATEST = {"alternative_id": str(GUIDED_ID)}
REPLACED = [(CONTROL_BORDER_REPLACED, "input"), (TEXT_COLOUR_REPLACED, ".m-faint")]
LATEST_KEYS = [
    "status",
    "generation_id",
    "design_version_id",
    "design_content_hash",
    "package",
    "approach",
    "changes",
    "warnings",
    "corrections",
    "cost_microusd",
    "applied_design_version_number",
]


def repaired(payload):
    return {**payload, "css": payload["css"] + FAINT + WEAK_BORDER}


def summary(corrections):
    return [(item["code"], item["selector"]) for item in corrections]


def test_a_mockup_declares_the_colours_that_the_studio_replaced_beside_its_warnings():
    versions = DesignVersions(package())
    store = MemoryMockupStore()
    generator = ScriptedMockupGenerator(answer(repaired(draft_payload())))
    client, registry = client_for(runtime(generator, store, versions))

    with client:
        result = generated(client, registry, versions)["result"]
        latest = client.get(MOCKUPS, params=LATEST).json()
        versions.apply(DesignPackagePayload.model_validate(result["package"]).to_domain())
        applied = client.get(MOCKUPS, params=LATEST).json()

    binding = bind(repaired(draft_payload()))
    assert result["corrections"] == [dict(item) for item in binding.correction_snapshots()]
    assert result["warnings"] == [dict(item) for item in binding.warning_snapshots()]
    assert summary(result["corrections"]) == REPLACED
    keys = list(result)
    assert keys[keys.index("warnings") + 1] == "corrections"
    [generation] = store.order
    accepted = store.payload(generation, "ADAPTER_ACCEPTED")["result"]
    assert accepted["corrections"] == result["corrections"]
    assert "corrections" not in result["package"]
    assert list(latest) == LATEST_KEYS
    assert latest == {**result, "applied_design_version_number": None}
    assert (applied["corrections"], applied["applied_design_version_number"]) == (
        result["corrections"],
        2,
    )


def test_the_latest_mockup_of_an_older_evidence_declares_no_correction():
    versions = DesignVersions(package())
    store = MemoryMockupStore()
    generator = ScriptedMockupGenerator(answer(draft_payload()))
    client, registry = client_for(runtime(generator, store, versions))

    with client:
        generated(client, registry, versions)
        [generation] = store.order
        del store.payload(generation, "ADAPTER_ACCEPTED")["result"]["corrections"]
        latest = client.get(MOCKUPS, params=LATEST).json()

    assert list(latest) == LATEST_KEYS
    assert latest["corrections"] == []


def test_the_list_of_the_iterations_shows_the_warnings_and_the_corrections_of_each_version():
    versions = applied_versions()
    generator = ScriptedMockupGenerator(answer(repaired(iteration_payload())))
    client, registry = client_for(runtime(generator, MemoryMockupStore(), versions))

    with client:
        _started, done = iterate(client, registry, versions)
        [proposed] = client.get(ITERATIONS).json()["items"]
        versions.apply(DesignPackagePayload.model_validate(done["result"]["package"]).to_domain())
        [applied] = client.get(ITERATIONS).json()["items"]

    result = done["result"]
    assert summary(result["corrections"]) == REPLACED
    assert [item["code"] for item in result["warnings"]] == [
        CONTROL_BORDER_REPLACED,
        TEXT_COLOUR_REPLACED,
    ]
    for item in (proposed, applied):
        assert (item["warnings"], item["corrections"]) == (
            result["warnings"],
            result["corrections"],
        )
    assert (proposed["status"], applied["status"], applied["applied_design_version_number"]) == (
        "PROPOSED",
        "APPLIED",
        3,
    )


def test_an_iteration_recorded_before_the_corrections_lists_none():
    target = {"screen_code": "SCR-001", "element_code": "ELM-012"}
    record = {
        "generation_id": "g-1",
        "recorded_at": "2026-10-08T10:00:00+00:00",
        "context": {
            "command_id": "c-1",
            "design_version_id": "v-1",
            "owner_request": "Mostra la sede di ritiro.",
            "target": target,
        },
        "events": {
            "ADAPTER_ACCEPTED": {
                "result": {"changes": ["La sede di ritiro è nel riepilogo."]},
                "generated_content_hashes": {"DESIGN": ["a" * 64]},
            },
            "APPLICATION_RESULT": {"status": "MOCKUP_GENERATED", "issue": None},
        },
    }

    [item] = iteration_items([record], ())

    assert (item["target"], item["changes"], item["status"]) == (
        target,
        ["La sede di ritiro è nel riepilogo."],
        "PROPOSED",
    )
    assert (item["warnings"], item["corrections"], item["opinion_id"]) == ([], [], None)
    assert list(item)[-3:] == ["warnings", "corrections", "opinion_id"]
