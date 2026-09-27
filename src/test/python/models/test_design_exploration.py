from __future__ import annotations

import asyncio

import pytest
from pydantic import TypeAdapter

from orchestwin.artifacts.visual_exploration import EXPLORED_ALTERNATIVES, visual_exploration
from orchestwin.models.design_drafts import DesignDraft, bind_design, design_context
from orchestwin.models.fake_design import FakeDeterministicDesignAdapter
from orchestwin.models.model_proposals import DESIGN_VISUAL_INSTRUCTION
from orchestwin.models.planning_schema import constrain_planning_schema
from orchestwin.models.proposal_generation import wire_value
from orchestwin.twins.epistemics import EvidenceReference, EvidenceSourceKind

from .draft_fixtures import proposal_draft
from .test_fake_design import proposal_request


def reference(code: str) -> EvidenceReference:
    return EvidenceReference(
        source_kind=EvidenceSourceKind.MODEL_OUTPUT,
        source_id="stub-provider",
        source_version=1,
        locator=code,
        content_hash=None,
    )


def design_draft(request) -> DesignDraft:
    expected = asyncio.run(FakeDeterministicDesignAdapter().propose(request)).package
    payload = proposal_draft("design", expected, request)
    payload["alternatives"] = payload["alternatives"][:2]
    codes = {item["code"] for item in payload["alternatives"]}
    payload["critiques"] = [item for item in payload["critiques"] if item["alternative"] in codes]
    payload["concerns"] = [
        {**item, "alternatives": [code for code in item["alternatives"] if code in codes]}
        for item in payload["concerns"]
        if set(item["alternatives"]) & codes
    ]
    if payload["recommendation"] not in codes:
        payload["recommendation"] = payload["alternatives"][0]["code"]
    return DesignDraft.model_validate(payload)


def test_design_context_and_schema_carry_the_exploration_of_the_project():
    request = proposal_request()
    context, _ = design_context(request)
    exploration = visual_exploration(request.project_id)
    assert context["visual_exploration"] == {
        code: {name: list(values) for name, values in dimensions.items()}
        for code, dimensions in exploration.items()
    }
    schema = TypeAdapter(DesignDraft).json_schema()
    constrain_planning_schema(schema, wire_value(context), "design")
    items = schema["properties"]["alternatives"]["prefixItems"]
    for code, item in zip(EXPLORED_ALTERNATIVES, items, strict=True):
        binding = item["allOf"][1]["properties"]
        assert binding["code"] == {"const": code}
        assert binding["visual"]["properties"]["hue_family"] == {
            "enum": list(exploration[code]["hue_family"])
        }
        assert set(binding["visual"]["properties"]) == set(exploration[code])
    assert "visual_exploration" in DESIGN_VISUAL_INSTRUCTION


def test_bind_design_accepts_explored_choices_and_rejects_the_others():
    request = proposal_request()
    _, twins = design_context(request)
    draft = design_draft(request)
    package = bind_design(draft, request, twins, reference)
    exploration = visual_exploration(request.project_id)
    for alternative in package.alternatives:
        choices = alternative.visual_language.choices.to_snapshot()
        for name, allowed in exploration[alternative.code].items():
            assert choices[name] in allowed
    first = draft.alternatives[0]
    outside = next(
        value
        for value in ("CRIMSON", "TEAL", "COBALT", "AMBER", "VIOLET", "FOREST")
        if value not in exploration[first.code]["hue_family"]
        and value not in exploration[draft.alternatives[1].code]["hue_family"]
    )
    payload = draft.model_dump(mode="json")
    payload["alternatives"][0]["visual"]["hue_family"] = outside
    with pytest.raises(ValueError, match="must choose hue_family inside the visual exploration"):
        bind_design(DesignDraft.model_validate(payload), request, twins, reference)
