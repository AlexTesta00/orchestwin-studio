from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.artifacts.design_change_opinions import (
    MAX_PROFILE_KEYS,
    MAX_TRY_THIS_LENGTH,
    MAX_WHAT_TO_DO_LENGTH,
    MAX_WHY_LENGTH,
    VERDICTS,
    ChangeOpinion,
    ChangeOpinionContrast,
    ChangeOpinionRun,
    change_opinion_contrast,
    normalize_owner_request,
)
from orchestwin.artifacts.visual_catalog import ColorMode
from orchestwin.projects.requirements_primitives import snapshot_content_hash

TWIN_ID = UUID("00000000-0000-4000-8000-000000004801")
OTHER_TWIN_ID = UUID("00000000-0000-4000-8000-000000004802")
GENERATION_ID = UUID("00000000-0000-4000-8000-000000004803")
OTHER_GENERATION_ID = UUID("00000000-0000-4000-8000-000000004804")
RUN_ID = UUID("00000000-0000-4000-8000-000000004805")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000004806")
VERSION_ID = UUID("00000000-0000-4000-8000-000000004807")
REQUESTED_AT = datetime(2026, 10, 12, 11, 0, tzinfo=UTC)
TARGET = {"screen_code": "SCR-001", "element_code": "ELM-012", "label": "Sollecita i 9 ritardi"}
OPINION_KEYS = [
    "twin_id",
    "twin_version",
    "twin_name",
    "verdict",
    "why",
    "what_to_do",
    "try_this",
    "profile_keys",
    "confidence",
    "generation_id",
]
RUN_KEYS = [
    "id",
    "project_id",
    "design_version_id",
    "design_content_hash",
    "request",
    "target",
    "locale",
    "requested_at",
    "opinions",
    "contrast",
    "cost_microusd",
]
OPINION_HASH = "4e813a487a253acc6d9ae510800d94da7b1af25c2789f75ece2733a063bcd009"
RUN_HASH = "9aa62cd38270412c7726001dfbb764fff32d3b234d9a77175825f22bebe81566"


def opinion(**changes: object) -> ChangeOpinion:
    values: dict[str, object] = {
        "twin_id": TWIN_ID,
        "twin_version": 2,
        "twin_name": "Bibliotecaria del banco prestiti",
        "verdict": "SLOWS",
        "why": "Al banco leggo in fretta e una barra rossa con il testo blu mi fermerebbe.",
        "what_to_do": "Tieni il testo scuro e usa il rosso solo per il bordo della barra.",
        "try_this": "Fai la barra rossa con il testo bianco.",
        "profile_keys": ("user_twin.role",),
        "confidence": 0.7,
        "generation_id": GENERATION_ID,
        **changes,
    }
    return ChangeOpinion(**values)


def opinion_run(**changes: object) -> ChangeOpinionRun:
    values: dict[str, object] = {
        "id": RUN_ID,
        "project_id": PROJECT_ID,
        "design_version_id": VERSION_ID,
        "design_content_hash": "a" * 64,
        "request": "Fai la barra rossa con il testo blu",
        "target": TARGET,
        "locale": "it-IT",
        "requested_at": REQUESTED_AT,
        "opinions": (
            opinion(),
            opinion(
                twin_id=OTHER_TWIN_ID,
                verdict="HELPS",
                try_this=None,
                generation_id=OTHER_GENERATION_ID,
            ),
        ),
        "contrast": change_opinion_contrast(ColorMode.LIGHT),
        "cost_microusd": 820_000,
        **changes,
    }
    return ChangeOpinionRun(**values)


def test_an_opinion_keeps_the_order_of_the_payload_and_reads_back_from_its_snapshot():
    sample = opinion()
    snapshot = sample.to_snapshot()
    assert list(snapshot) == OPINION_KEYS
    assert snapshot["profile_keys"] == ["user_twin.role"]
    assert (snapshot["twin_id"], snapshot["generation_id"]) == (str(TWIN_ID), str(GENERATION_ID))
    assert ChangeOpinion.from_snapshot(json.loads(json.dumps(snapshot))) == sample
    assert sample.content_hash == snapshot_content_hash(snapshot) == OPINION_HASH
    assert opinion(try_this=None).to_snapshot()["try_this"] is None
    assert opinion(verdict="BLOCKS").content_hash != sample.content_hash


def test_a_run_holds_its_opinions_and_the_contrast_of_the_design_with_a_stable_hash():
    run = opinion_run()
    snapshot = run.to_snapshot()
    assert list(snapshot) == RUN_KEYS
    assert snapshot["target"] == TARGET
    assert snapshot["requested_at"] == "2026-10-12T11:00:00+00:00"
    assert snapshot["opinions"] == [item.to_snapshot() for item in run.opinions]
    assert snapshot["contrast"] == {
        "mode": "LIGHT",
        "text_threshold": 4.5,
        "large_text_threshold": 3.0,
        "control_border_threshold": 3.0,
    }
    assert run.content_hash == snapshot_content_hash(snapshot) == RUN_HASH
    assert opinion_run(cost_microusd=0).content_hash != run.content_hash


@pytest.mark.parametrize(
    ("mode", "thresholds"),
    [
        (ColorMode.LIGHT, (4.5, 3.0, 3.0)),
        (ColorMode.DARK, (4.5, 3.0, 3.0)),
        (ColorMode.HIGH_CONTRAST_LIGHT, (7.0, 4.5, 3.0)),
        (ColorMode.HIGH_CONTRAST_DARK, (7.0, 4.5, 3.0)),
    ],
)
def test_the_contrast_rules_follow_the_colour_mode_of_the_design(mode, thresholds):
    assert change_opinion_contrast(mode) == ChangeOpinionContrast(mode, *thresholds)


def test_an_opinion_accepts_the_longest_texts_and_the_three_verdicts():
    longest = opinion(
        why="a" * MAX_WHY_LENGTH,
        what_to_do="b" * MAX_WHAT_TO_DO_LENGTH,
        try_this="c" * MAX_TRY_THIS_LENGTH,
        profile_keys=tuple(f"user_twin.key{number}" for number in range(MAX_PROFILE_KEYS)),
        confidence=1.0,
    )
    assert len(longest.profile_keys) == MAX_PROFILE_KEYS
    assert [opinion(verdict=verdict).verdict for verdict in VERDICTS] == [
        "HELPS",
        "SLOWS",
        "BLOCKS",
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"verdict": "WORKS"},
        {"why": ""},
        {"why": "  Al banco leggo in fretta. "},
        {"why": "a" * (MAX_WHY_LENGTH + 1)},
        {"what_to_do": "b" * (MAX_WHAT_TO_DO_LENGTH + 1)},
        {"try_this": ""},
        {"try_this": "c" * (MAX_TRY_THIS_LENGTH + 1)},
        {"profile_keys": ()},
        {"profile_keys": ["user_twin.role"]},
        {"profile_keys": ("user_twin.role", "user_twin.role")},
        {"profile_keys": tuple(f"user_twin.key{n}" for n in range(MAX_PROFILE_KEYS + 1))},
        {"confidence": 1},
        {"confidence": 1.5},
        {"twin_version": 0},
        {"twin_name": ""},
        {"twin_id": str(TWIN_ID)},
        {"generation_id": None},
    ],
)
def test_an_opinion_refuses_what_its_contract_does_not_allow(changes):
    with pytest.raises(ValueError):
        opinion(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"id": str(RUN_ID)},
        {"design_content_hash": "short"},
        {"request": "  Fai la barra rossa "},
        {"request": ""},
        {"target": {"element_code": "ELM-012"}},
        {"target": None},
        {"locale": "x"},
        {"locale": "x" * 21},
        {"requested_at": datetime(2026, 10, 12, 11, 0)},
        {"opinions": ()},
        {"opinions": [opinion()]},
        {"opinions": (opinion(), opinion(generation_id=OTHER_GENERATION_ID))},
        {"contrast": {"mode": "LIGHT"}},
        {"cost_microusd": -1},
        {"cost_microusd": True},
        {"cost_microusd": 1.5},
    ],
)
def test_a_run_refuses_what_its_contract_does_not_allow(changes):
    with pytest.raises(ValueError):
        opinion_run(**changes)


def test_the_request_of_the_owner_is_normalized_like_the_iterations():
    assert normalize_owner_request("  Fai  la barra\nrossa\tcon il testo blu ") == (
        "Fai la barra rossa con il testo blu"
    )
    assert normalize_owner_request("x" * 1000) == "x" * 1000


@pytest.mark.parametrize("value", ["", "   ", "x" * 1001, "Fai la barra\x00 rossa", 7])
def test_an_empty_long_or_controlled_request_is_refused(value):
    with pytest.raises(ValueError):
        normalize_owner_request(value)
