"""Synthetic contract checks for grounded visual drafts and immutable review state."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from orchestwin.api.design_mockups import (
    DEFAULT_MOCKUP_RECIPE,
    MockupRequest,
    ModelMockupApplication,
    _alternative_view,
    _mockup_instruction,
    _payload,
)
from orchestwin.artifacts.visual_catalog import ARCHETYPES, LayoutArchetype, NavigationPattern
from orchestwin.models.design_drafts import requirements_view
from orchestwin.models.design_mockups import MockupDraft, MockupElementDraft, bind_mockup
from orchestwin.models.planning_schema import constrain_planning_schema

from ..artifacts import design_fixtures as fixtures
from .test_model_proposals import make_generator


def element(kind, content, **kwargs):
    return {
        "kind": kind,
        "content": content,
        "requirements": ["REQ-001"],
        "field_name": None,
        "required": False,
        "options": [],
        "target_screen": None,
        **kwargs,
    }


def draft_value():
    return {
        "title": "Prenotazione",
        "screens": [
            {
                "code": "SCR-001",
                "title": "Richiesta",
                "state": "DEFAULT",
                "elements": [
                    element("TEXT_INPUT", "Nome", field_name="name", required=True),
                    element("BUTTON", "Continua", target_screen="SCR-002"),
                ],
            },
            {
                "code": "SCR-002",
                "title": "Riepilogo",
                "state": "SUCCESS",
                "elements": [
                    element("STATUS", "Esempio di prenotazione confermata"),
                    element("LINK", "Indietro", target_screen="SCR-001"),
                ],
            },
        ],
    }


def test_mockup_has_accessible_controls_valid_transitions_and_exact_requirements():
    version = fixtures.design_version()
    prototype = bind_mockup(
        MockupDraft.model_validate(draft_value()),
        version.package.alternatives[0],
        fixtures.requirements_version(),
    )
    assert len(prototype.screens) == 2
    assert prototype.screens[0].elements[0].accessible_name == "Nome"
    assert prototype.screens[0].elements[0].required
    assert prototype.screens[0].elements[0].requirement_ids == (fixtures.REQUIREMENT_ID,)
    assert len(prototype.transitions) == 2
    assert version.package.prototype.id == fixtures.PROTOTYPE_ID


@pytest.mark.parametrize(
    "mutation",
    ["foreign_requirement", "unknown_target", "unreachable", "narrative", "invalid_field"],
)
def test_rejects_invalid_visual_drafts(mutation):
    value = draft_value()
    control = value["screens"][0]["elements"][1]
    if mutation == "foreign_requirement":
        control["requirements"] = ["REQ-999"]
    elif mutation == "unknown_target":
        control["target_screen"] = "SCR-999"
    elif mutation == "unreachable":
        control["target_screen"] = "SCR-001"
    elif mutation == "narrative":
        for screen in value["screens"]:
            screen["elements"][1] = element("TEXT", "Description only")
    else:
        control["field_name"] = "not-a-field"
    with pytest.raises(ValueError):
        bind_mockup(
            MockupDraft.model_validate(value),
            fixtures.design_version().package.alternatives[0],
            fixtures.requirements_version(),
        )


def test_mockup_schema_constrains_only_known_requirement_codes():
    schema = MockupDraft.model_json_schema()
    constrain_planning_schema(
        schema,
        {
            "purpose": "DESIGN_MOCKUP",
            "requirements": requirements_view(fixtures.requirements_version()),
        },
        "design",
    )
    assert schema["$defs"]["MockupElementDraft"]["properties"]["requirements"]["items"]["enum"] == [
        "REQ-001"
    ]


@pytest.mark.parametrize(
    "value, reason",
    [
        (element("SELECT", "Operation", options=["Add"]), "require a field name"),
        (
            element("SELECT", "Operation", field_name="  ", options=["Add"]),
            "require a field name",
        ),
        (element("TEXT_INPUT", "Operand"), "require a field name"),
        (element("SELECT", "Operation", field_name="operation"), "require options"),
        (element("TEXT", "Help", field_name="help"), "must not define a field name"),
        (element("TEXT", "Help", required=True), "only prototype input elements"),
        (element("TEXT", "Help", options=["One"]), "only SELECT"),
        (element("TEXT_INPUT", "Operand", field_name="operand", options=["One"]), "only SELECT"),
        (element("BUTTON", "Continue"), "declared destination"),
        (element("LINK", "Return"), "declared destination"),
        (element("TEXT", "Help", target_screen="SCR-002"), "declared destination"),
        (
            element(
                "SELECT",
                "Operation",
                field_name="operation",
                options=["Add"],
                target_screen="SCR-002",
            ),
            "declared destination",
        ),
    ],
)
def test_primitive_inconsistencies_are_rejected_at_draft_boundary(value, reason):
    with pytest.raises(ValueError, match=reason):
        MockupElementDraft.model_validate(value)


@pytest.mark.parametrize(
    "kind, fields",
    [
        ("HEADING", {}),
        ("TEXT", {}),
        ("LIST", {}),
        ("CARD", {}),
        ("STATUS", {}),
        ("TEXT_INPUT", {"field_name": "operand", "required": True}),
        ("SELECT", {"field_name": "operation", "required": True, "options": ["Add", "Subtract"]}),
        ("BUTTON", {"target_screen": "SCR-002"}),
        ("LINK", {"target_screen": "SCR-001"}),
    ],
)
def test_valid_primitive_kinds_preserve_model_authored_values(kind, fields):
    value = element(kind, "Visible content", **fields)
    assert MockupElementDraft.model_validate(value).model_dump(mode="json") == value


def test_decoder_schema_correlates_fields_with_primitive_kind():
    schema = MockupDraft.model_json_schema()["$defs"]["MockupElementDraft"]
    branches = {
        branch["properties"]["kind"]["const"]: branch["properties"] for branch in schema["anyOf"]
    }
    assert len(branches) == 9
    assert branches["SELECT"]["field_name"] == {"type": "string", "pattern": r"\S"}
    assert branches["SELECT"]["options"] == {"minItems": 1}
    assert branches["SELECT"]["target_screen"] == {"type": "null"}
    assert branches["TEXT_INPUT"]["options"] == {"maxItems": 0}
    for kind in ("BUTTON", "LINK"):
        assert branches[kind]["target_screen"] == {"type": "string"}
        assert branches[kind]["field_name"] == {"type": "null"}
        assert branches[kind]["required"] == {"const": False}
    for kind in ("HEADING", "TEXT", "LIST", "CARD", "STATUS"):
        assert branches[kind]["field_name"] == {"type": "null"}
        assert branches[kind]["target_screen"] == {"type": "null"}
        assert branches[kind]["options"] == {"maxItems": 0}
        assert branches[kind]["required"] == {"const": False}


def test_success_mockup_does_not_mix_in_an_error_state():
    value = draft_value()
    value["screens"][1]["elements"][0]["content"] = "Errore: divisione per zero"
    with pytest.raises(ValueError, match="success screen"):
        bind_mockup(
            MockupDraft.model_validate(value),
            fixtures.design_version().package.alternatives[0],
            fixtures.requirements_version(),
        )


class MemoryEvidence:
    def __init__(self):
        self.events = []

    async def begin(self, **kwargs):
        self.request = kwargs["request"]

    async def append(self, **kwargs):
        self.events.append(kwargs)


def application(tmp_path, *, missing=False, stale=False):
    version = fixtures.design_version()
    generator, transport = make_generator(tmp_path, draft_value())
    evidence = MemoryEvidence()
    calls = 0

    async def current(**kwargs):
        nonlocal calls
        assert kwargs["owner_user_id"] == fixtures.OWNER_ID
        calls += 1
        if missing:
            return None
        return (
            fixtures.design_version(
                version_number=2,
                package=replace(version.package, open_questions=("Changed during inference",)),
            )
            if stale and calls > 1
            else version
        )

    async def requirements(**kwargs):
        return fixtures.requirements_version()

    runtime = SimpleNamespace(
        proposal_evidence_store=evidence,
        real_model_runtime=SimpleNamespace(
            design=SimpleNamespace(proposal_port=SimpleNamespace(generator=generator))
        ),
        design_query_service=SimpleNamespace(current=current),
        requirements_query_service=SimpleNamespace(current=requirements),
    )
    body = MockupRequest(
        design_version_id=version.id,
        design_content_hash=version.content_hash,
        alternative_id=version.package.alternatives[0].id,
    )
    return ModelMockupApplication(runtime), body, evidence, transport


def test_generation_retains_model_evidence_without_publishing_or_changing_gates(tmp_path):
    app, body, evidence, transport = application(tmp_path)
    result = asyncio.run(
        app.generate(owner_user_id=fixtures.OWNER_ID, project_id=fixtures.PROJECT_ID, body=body)
    )
    assert len(transport.calls) == 1
    assert result.package.prototype.screens[0].elements[0].content == "Nome"
    accepted = next(x for x in evidence.events if x["kind"] == "ADAPTER_ACCEPTED")
    assert accepted["payload"]["result"] == _payload(result)
    assert accepted["payload"]["result"]["package"]["schema_version"] == 1
    assert evidence.events[-1]["payload"]["status"] == "MOCKUP_GENERATED"
    assert evidence.request.output_schema.version_number == 7
    assert "one moment" in evidence.request.system_instruction
    assert "error examples are omitted" in evidence.request.system_instruction


def test_missing_owner_project_does_not_call_model(tmp_path):
    app, body, _evidence, transport = application(tmp_path, missing=True)
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            app.generate(owner_user_id=fixtures.OWNER_ID, project_id=fixtures.PROJECT_ID, body=body)
        )
    assert error.value.status_code == 404
    assert not transport.calls


def test_design_changed_during_generation_is_not_accepted(tmp_path):
    app, body, evidence, transport = application(tmp_path, stale=True)
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            app.generate(owner_user_id=fixtures.OWNER_ID, project_id=fixtures.PROJECT_ID, body=body)
        )
    assert error.value.status_code == 409
    assert len(transport.calls) == 1
    assert not any(x["kind"] == "ADAPTER_ACCEPTED" for x in evidence.events)


def guided_alternative():
    alternative = fixtures.design_version().package.alternatives[1]
    language = alternative.visual_language
    choices = replace(
        language.choices,
        archetype=LayoutArchetype.GUIDED_STEPS,
        navigation=NavigationPattern.TOP_BAR,
    )
    return replace(alternative, visual_language=replace(language, choices=choices))


def test_mockup_screen_count_follows_the_archetype_of_the_alternative():
    dashboard = fixtures.design_version().package.alternatives[1]
    prototype = bind_mockup(
        MockupDraft.model_validate(draft_value()), dashboard, fixtures.requirements_version()
    )
    assert len(prototype.screens) == 2
    with pytest.raises(ValueError, match="screen count does not fit"):
        bind_mockup(
            MockupDraft.model_validate(draft_value()),
            guided_alternative(),
            fixtures.requirements_version(),
        )


def test_mockup_instruction_and_context_follow_the_visual_language():
    plain = fixtures.design_version().package.alternatives[0]
    assert _mockup_instruction(plain).endswith(DEFAULT_MOCKUP_RECIPE)
    guided = guided_alternative()
    instruction = _mockup_instruction(guided)
    assert ARCHETYPES[LayoutArchetype.GUIDED_STEPS].recipe in instruction
    assert "'Reservation desk'" in instruction
    assert "between 3 and 4 screens" in instruction
    view = _alternative_view(guided)
    assert set(view["visual_language"]) == {"choices", "product_name", "rationale"}
    assert "tokens" not in view["visual_language"]
    assert (
        "visual_language" not in _alternative_view(plain)
        or _alternative_view(plain)["visual_language"] is None
    )
