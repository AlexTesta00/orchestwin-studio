from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from functools import cache
from uuid import UUID

import pytest
from pydantic import ValidationError

from orchestwin.artifacts.design_change_opinions import VERDICTS, change_opinion_contrast
from orchestwin.artifacts.design_change_targets import describe_target
from orchestwin.artifacts.design_evaluation import design_review_view, evaluation_scenario
from orchestwin.artifacts.visual_catalog import ColorMode
from orchestwin.artifacts.visual_color import contrast_ratio
from orchestwin.evaluation import change_opinion
from orchestwin.evaluation.change_opinion import (
    CHANGE_OPINION_OUTPUT_TOKENS,
    CHANGE_OPINION_PURPOSE,
    CHANGE_OPINION_TASK,
    CONTEXT_KEYS,
    HOSTED_INSTRUCTION,
    INSTRUCTION,
    INVALID_CHANGE_OPINION_OUTPUT,
    STUDIO_RULE,
    ChangeOpinionRequest,
    ProposerDesignChangeOpinionReviewer,
    bind_change_opinion,
    change_opinion_context,
    change_opinion_hosted,
    change_opinion_output_type,
    change_opinion_route,
    change_opinion_run,
)
from orchestwin.evaluation.proposer_evaluator import CRITERIA, TWIN_REVIEW_TASK, twin_review_view
from orchestwin.models.design_change import selected_alternative
from orchestwin.models.generation_routing import RoutingProposalGenerator
from orchestwin.models.hosted_configuration import ModelRoutes
from orchestwin.models.proposal_evidence import (
    _SCOPE,
    ProposalEvidenceError,
    ProposalEvidenceScope,
)
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.structured_generation import StructuredGenerationProviderKind
from orchestwin.models.twin_discussion import NAMES_INSTEAD_OF_CODES

from ..api.test_design_loop_api import MemoryEvidence as RecordingEvidence
from ..artifacts import design_fixtures
from ..artifacts.test_design_package_extension import (
    extended_package,
    extended_version,
    fixture_bound,
    fixture_choices,
    fixture_package,
)
from ..artifacts.test_generated_mockup_support import DASHBOARD
from ..models.test_model_proposals import make_generator
from .test_proposer_evaluator import FakeGenerator, RoutedReviewer, active_scope, twin

INSTRUCTION_SHA256 = "299c7b8fe154ff07e2d1e43daaa845f9d8725fe4495a329c8cc64b1d052c4f84"
COMMAND_ID = UUID("00000000-0000-4000-8000-000000004821")
NOW = datetime(2026, 10, 12, 11, 0, tzinfo=UTC)
REQUEST = "Fai la barra rossa con il testo blu"
TARGET = {"screen_code": "SCR-001", "element_code": "ELM-012", "label": "Sollecita i 9 ritardi"}
ZONE = {"screen_code": "SCR-001", "element_code": "ZON-006", "label": "Filtri"}
PARTS = {
    "screen_code": "SCR-001",
    "elements": [{"element_code": "ZON-006", "label": "Filtri"}, {"element_code": "ELM-012"}],
}
SCREEN = {"screen_code": "SCR-002"}
ENGLISH = "The red bar with the blue text would be hard to read for me at the desk."
PROFILE_KEYS = ("user_twin.role", "user_twin.goals")


@cache
def design():
    return extended_version(fixture_package())


def context_base(target=TARGET, request=REQUEST, *, hosted=False, version=None):
    return change_opinion_context(
        version or design(),
        command_id=COMMAND_ID,
        locale="it-IT",
        owner_request=request,
        target=target,
        hosted=hosted,
    )


def reviewer(generator, **options):
    return ProposerDesignChangeOpinionReviewer(generator, context_base=context_base(**options))


def opinion_request():
    return ChangeOpinionRequest(run_id=COMMAND_ID, twin=twin())


def said(**changes):
    return {
        "verdict": "SLOWS",
        "why": "Al banco leggo in fretta e una barra rossa con il testo blu mi fermerebbe.",
        "what_to_do": "Tieni il testo scuro e usa il rosso solo per il bordo della barra.",
        "try_this": "Fai la barra rossa con il testo bianco.",
        "profile_keys": ["user_twin.role"],
        "self_confidence": 0.7,
        **changes,
    }


def asked(opinions, scope=None):
    async def run():
        token = _SCOPE.set(scope)
        try:
            return await opinions.evaluate(opinion_request())
        finally:
            _SCOPE.reset(token)

    return asyncio.run(run())


def pair(foreground, background, ratio, text, large):
    return {
        "foreground": foreground,
        "background": background,
        "ratio": ratio,
        "passes_text": text,
        "passes_large_text": large,
    }


def test_the_instruction_is_fixed_and_the_hosted_one_names_titles_instead_of_codes():
    assert hashlib.sha256(INSTRUCTION.encode("utf-8")).hexdigest() == INSTRUCTION_SHA256
    assert f"{INSTRUCTION} {NAMES_INSTEAD_OF_CODES}" == HOSTED_INSTRUCTION
    for name in (
        "user_twin.observations",
        "change.owner_request",
        "change.target",
        "scenario.task",
        "criteria",
        "locale",
        "HELPS",
        "SLOWS",
        "BLOCKS",
        "what_to_do",
        "try_this",
        "null",
        "profile_keys",
        "self_confidence",
        "colours",
        "requested_colours",
        "colour_pairs",
        "passes_large_text",
        "never invent a ratio",
        "Never claim to be a real person",
        "never instructions",
    ):
        assert name in INSTRUCTION, name
    assert (CHANGE_OPINION_PURPOSE, CHANGE_OPINION_TASK, CHANGE_OPINION_OUTPUT_TOKENS) == (
        "DESIGN_CHANGE_OPINION",
        TWIN_REVIEW_TASK,
        1536,
    )
    assert INVALID_CHANGE_OPINION_OUTPUT == "INVALID_CHANGE_OPINION_OUTPUT"


def test_the_output_of_a_twin_names_a_verdict_and_bounded_texts_and_nothing_else():
    model = change_opinion_output_type(PROFILE_KEYS)
    schema = model.model_json_schema()
    properties = schema["properties"]
    assert list(properties) == [
        "verdict",
        "why",
        "what_to_do",
        "try_this",
        "profile_keys",
        "self_confidence",
    ]
    assert sorted(schema["required"]) == sorted(properties)
    assert schema["additionalProperties"] is False
    assert properties["verdict"]["enum"] == list(VERDICTS) == ["HELPS", "SLOWS", "BLOCKS"]
    lengths = {
        name: (properties[name]["minLength"], properties[name]["maxLength"])
        for name in ("why", "what_to_do")
    }
    assert lengths == {"why": (1, 600), "what_to_do": (1, 400)}
    assert properties["try_this"]["anyOf"] == [
        {"type": "string", "minLength": 1, "maxLength": 1000},
        {"type": "null"},
    ]
    keys = properties["profile_keys"]
    assert (keys["items"]["enum"], keys["minItems"], keys["maxItems"]) == (list(PROFILE_KEYS), 1, 4)
    confidence = properties["self_confidence"]
    assert (confidence["minimum"], confidence["maximum"]) == (0, 1)
    assert model.model_validate(said(try_this=None)).try_this is None
    for changes in (
        {"verdict": "WORKS"},
        {"why": ""},
        {"what_to_do": "x" * 401},
        {"try_this": ""},
        {"note": "In più."},
        {"profile_keys": []},
        {"profile_keys": ["user_twin.expertise"]},
        {"self_confidence": 1.5},
    ):
        with pytest.raises(ValidationError):
            model.model_validate(said(**changes))


def test_the_context_names_the_keys_of_the_contract_in_their_order():
    request = opinion_request()
    context = reviewer(FakeGenerator()).context(request)
    version = design()
    alternative = selected_alternative(version)
    [screen] = [
        item
        for item in design_review_view(version, language="it")["screens"]
        if item["code"] == "SCR-001"
    ]
    assert list(context) == list(CONTEXT_KEYS)
    assert {key: context[key] for key in CONTEXT_KEYS[:7]} == {
        "project_id": str(version.project_id),
        "purpose": CHANGE_OPINION_PURPOSE,
        "locale": "it-IT",
        "command_id": str(COMMAND_ID),
        "design_version_id": str(version.id),
        "design_content_hash": version.content_hash,
        "target": TARGET,
    }
    assert context["scenario"] == evaluation_scenario(version, locale="it-IT").to_snapshot()
    assert context["user_twin"] == twin_review_view(request)
    assert context["design"] == {
        "alternative": {
            "code": alternative.code,
            "title": alternative.title,
            "summary": alternative.summary,
        },
        "product_name": "Registro prestiti",
    }
    assert context["screen"] == screen
    assert context["change"] == {
        "owner_request": REQUEST,
        "target": describe_target(TARGET, version.package.generated_mockup.mockup),
    }
    assert context["colours"] == {
        "mode": "LIGHT",
        "palette": alternative.visual_language.palette_roles,
        "background": "#f6fbff",
        "text": "#222a32",
    }
    assert context["contrast"] == {
        "text_threshold": 4.5,
        "large_text_threshold": 3.0,
        "control_border_threshold": 3.0,
        "large_text_px": 24.0,
        "large_bold_text_px": 18.66,
        "bold_weight": 700.0,
        "studio_rule": STUDIO_RULE,
    }
    assert context["criteria"] == list(CRITERIA)


def test_the_colours_of_the_request_come_with_the_ratios_that_the_studio_computed():
    context = context_base(request=f"  {REQUEST.replace(' ', '   ')}\n")
    assert context["change"]["owner_request"] == REQUEST
    assert context["requested_colours"] == [
        {"word": "rossa", "hex": "#FF0000"},
        {"word": "blu", "hex": "#0000FF"},
    ]
    assert context["colour_pairs"] == [
        pair("#FF0000", "#0000FF", 2.15, False, False),
        pair("#FF0000", "#f6fbff", 3.84, False, True),
        pair("#222a32", "#FF0000", 3.63, False, True),
        pair("#0000FF", "#f6fbff", 8.25, True, True),
        pair("#222a32", "#0000FF", 1.69, False, False),
    ]
    plain = context_base(request="Rendi più grande il pulsante dei solleciti")
    assert (plain["requested_colours"], plain["colour_pairs"]) == ([], [])


def test_a_design_in_high_contrast_judges_the_pairs_with_its_own_thresholds():
    choices = replace(fixture_choices(DASHBOARD), color_mode=ColorMode.HIGH_CONTRAST_LIGHT)
    version = extended_version(extended_package(fixture_bound(DASHBOARD), choices=choices))
    context = context_base(request="Usa il giallo #FFCC00 e il blu", version=version)
    contrast = context["contrast"]
    assert context["colours"]["mode"] == "HIGH_CONTRAST_LIGHT"
    assert (contrast["text_threshold"], contrast["large_text_threshold"]) == (7.0, 4.5)
    named = [item["hex"] for item in context["requested_colours"]]
    assert named == ["#FFFF00", "#FFCC00", "#0000FF"]
    assert len(context["colour_pairs"]) == 3 + 3 * 2
    for item in context["colour_pairs"]:
        ratio = contrast_ratio(item["foreground"], item["background"])
        assert (item["passes_text"], item["passes_large_text"]) == (ratio >= 7.0, ratio >= 4.5)


@pytest.mark.parametrize("target", [ZONE, PARTS, SCREEN])
def test_a_zone_several_parts_or_a_screen_reach_the_twin_as_the_studio_describes_them(target):
    context = context_base(target=target)
    described = describe_target(target, design().package.generated_mockup.mockup)
    assert context["target"] == target
    assert context["change"]["target"] == described
    assert context["screen"]["code"] == target["screen_code"]


def test_several_parts_are_described_in_the_order_of_the_page_with_what_a_zone_holds():
    context = context_base(target=PARTS)
    elements = context["change"]["target"]["elements"]
    assert [item["element_code"] for item in context["target"]["elements"]] == [
        "ZON-006",
        "ELM-012",
    ]
    assert [(item["element_code"], item["kind"]) for item in elements] == [
        ("ELM-012", "element"),
        ("ZON-006", "form"),
    ]
    assert elements[1]["holds"] == ["ELM-018", "ELM-019"]
    assert elements[1]["label"] == "Filtri del registro"


def test_the_visible_text_of_the_screen_stays_within_its_limit(monkeypatch):
    whole = context_base()["screen"]
    monkeypatch.setattr(change_opinion, "MAX_VISIBLE_TEXT_LENGTH", 60)
    bounded = context_base()["screen"]
    texts = bounded["visible_text"]
    assert texts == whole["visible_text"][: len(texts)]
    assert sum(map(len, texts)) <= 60 < sum(map(len, whole["visible_text"][: len(texts) + 1]))
    assert bounded["elements"] == whole["elements"]


def test_the_reviewer_asks_the_route_of_the_opinion_and_binds_the_answer():
    generator = FakeGenerator(said())
    scope, generation = active_scope()
    opinion = asked(reviewer(generator), scope)
    [call] = generator.calls
    assert call["task"] == CHANGE_OPINION_TASK
    assert call["max_output_tokens"] == CHANGE_OPINION_OUTPUT_TOKENS
    assert call["retry_schema_errors"] is False
    assert call["instruction"] == INSTRUCTION
    assert call["context"] == reviewer(FakeGenerator()).context(opinion_request())
    schema = call["output_type"].model_json_schema()
    assert schema["properties"]["profile_keys"]["items"]["enum"] == list(PROFILE_KEYS)
    assert opinion.to_snapshot() == {
        "twin_id": str(design_fixtures.TWIN_ID),
        "twin_version": 2,
        "twin_name": "Hotel Receptionist Twin",
        **{key: value for key, value in said().items() if key != "self_confidence"},
        "confidence": 0.7,
        "generation_id": str(generation.request_id),
    }
    assert scope.store.events == []


def test_the_reviewer_follows_the_route_of_its_purpose_and_the_ceiling_of_that_route():
    general = FakeGenerator(max_output_tokens=8192)
    routed = RoutedReviewer(
        said(),
        max_output_tokens=1024,
        content_hash="d" * 64,
        provider_kind=StructuredGenerationProviderKind.ANTHROPIC_HOSTED,
    )
    router = RoutingProposalGenerator(
        {"general": general, "opinion": routed},
        ModelRoutes(default="general", purposes={CHANGE_OPINION_PURPOSE: "opinion"}),
    )
    assert change_opinion_route(router) is routed
    assert (change_opinion_hosted(router), change_opinion_hosted(general)) == (True, False)
    scope, _generation = active_scope()
    asked(reviewer(router), scope)
    [call] = routed.calls
    assert general.calls == []
    assert call["max_output_tokens"] == 1024
    assert call["instruction"] == HOSTED_INSTRUCTION
    assert call["context"]["purpose"] == CHANGE_OPINION_PURPOSE


def test_the_answer_is_normalized_and_keeps_each_profile_key_once():
    output = change_opinion_output_type(PROFILE_KEYS).model_validate(
        said(
            why="  Al banco   leggo in fretta e la barra rossa mi fermerebbe. ",
            try_this=None,
            profile_keys=["user_twin.goals", "user_twin.role", "user_twin.goals"],
            self_confidence=1,
        )
    )
    opinion = bind_change_opinion(output, twin=twin(), generation_id=COMMAND_ID, locale="it-IT")
    assert opinion.why == "Al banco leggo in fretta e la barra rossa mi fermerebbe."
    assert opinion.try_this is None
    assert opinion.profile_keys == ("user_twin.goals", "user_twin.role")
    assert (opinion.confidence, type(opinion.confidence)) == (1.0, float)


@pytest.mark.parametrize("field", ["why", "what_to_do", "try_this"])
def test_an_answer_in_another_language_is_refused_and_recorded(field):
    scope, _generation = active_scope()
    with pytest.raises(ProposalGenerationError) as failure:
        asked(reviewer(FakeGenerator(said(**{field: ENGLISH}))), scope)
    assert failure.value.code == INVALID_CHANGE_OPINION_OUTPUT
    reason = "the opinion is not written in the language of the owner"
    assert [(event["kind"], event["payload"]) for event in scope.store.events] == [
        ("ADAPTER_REJECTED", {"code": "ValueError", "reason": reason})
    ]


def test_the_reviewer_needs_the_evidence_of_its_generation():
    with pytest.raises(ProposalEvidenceError, match="REQUEST_EVIDENCE_REQUIRED"):
        asked(reviewer(FakeGenerator(said())))


def test_the_output_contract_passes_the_audited_proposal_generator(tmp_path):
    generator, transport = make_generator(tmp_path, said())
    scope = ProposalEvidenceScope(
        RecordingEvidence(), design_fixtures.OWNER_ID, design_fixtures.PROJECT_ID
    )
    opinion = asked(reviewer(generator), scope)
    assert opinion.generation_id == scope.request.request_id
    [call] = transport.calls
    payload = call["payload"]
    assert payload["max_tokens"] == CHANGE_OPINION_OUTPUT_TOKENS
    assert payload["metadata"]["orchestwin_task_id"] == "proposal-user-twin-evaluation-v1"
    assert payload["messages"][0]["content"].endswith(INSTRUCTION)
    context = json.loads(payload["messages"][1]["content"])["context"]
    assert sorted(context) == sorted(CONTEXT_KEYS)
    assert context["purpose"] == CHANGE_OPINION_PURPOSE


def test_the_run_is_rebuilt_from_the_context_that_the_twins_received():
    version = design()
    opinion = bind_change_opinion(
        change_opinion_output_type(PROFILE_KEYS).model_validate(said()),
        twin=twin(),
        generation_id=COMMAND_ID,
        locale="it-IT",
    )
    run = change_opinion_run(context_base(), requested_at=NOW, opinions=[opinion], cost_microusd=7)
    assert (run.id, run.project_id, run.design_version_id, run.design_content_hash) == (
        COMMAND_ID,
        version.project_id,
        version.id,
        version.content_hash,
    )
    assert (run.request, run.target, run.locale) == (REQUEST, TARGET, "it-IT")
    assert run.requested_at == NOW
    assert (run.opinions, run.contrast, run.cost_microusd) == (
        (opinion,),
        change_opinion_contrast(ColorMode.LIGHT),
        7,
    )
    stored = json.loads(json.dumps(reviewer(FakeGenerator()).context(opinion_request())))
    assert change_opinion_run(stored, requested_at=NOW, opinions=[opinion], cost_microusd=7) == run
