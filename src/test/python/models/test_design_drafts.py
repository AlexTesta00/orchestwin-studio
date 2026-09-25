from __future__ import annotations

import asyncio

import pytest

from orchestwin.artifacts.visual_catalog import (
    LayoutArchetype,
    NavigationPattern,
    visual_catalog_summary,
)
from orchestwin.models.design import DesignProposalStatus
from orchestwin.models.design_drafts import (
    AlternativeDraft,
    CritiqueDraft,
    DesignDraft,
    VisualLanguageDraft,
    WorkflowDraft,
    bind_design,
    design_context,
)
from orchestwin.models.model_proposals import DESIGN_VISUAL_INSTRUCTION, ModelDesignAdapter
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.twins.epistemics import EvidenceReference, EvidenceSourceKind

from .test_fake_design import proposal_request

THREE_STEPS = ("Open the reservation.", "Edit the dates.", "Confirm the change.")


def visual(**overrides) -> VisualLanguageDraft:
    values = {
        "approach_rationale": "Occasional receptionists need one decision at a time in a calm palette.",
        "archetype": "GUIDED_STEPS",
        "background": "PLAIN",
        "body_family": "SYSTEM_UI",
        "borders": "HAIRLINE",
        "buttons": "FILLED",
        "color_mode": "LIGHT",
        "color_scheme": "NEUTRAL_ACCENT",
        "corners": "SOFT",
        "density": "COMFORTABLE",
        "elevation": "SUBTLE",
        "emphasis": "BALANCED",
        "header": "COMPACT_BAR",
        "heading_case": "SENTENCE",
        "heading_family": "HUMANIST_SANS",
        "heading_weight": "SEMIBOLD",
        "hue_family": "COBALT",
        "inputs": "BOXED",
        "navigation": "TOP_BAR",
        "product_name": "Reservation steps",
        "saturation": "BALANCED",
        "surface_tone": "TINTED",
        "tone": "INSTITUTIONAL",
        "type_scale": "REGULAR",
    }
    values.update(overrides)
    return VisualLanguageDraft(**values)


def second_visual(**overrides) -> VisualLanguageDraft:
    values = {
        "approach_rationale": "Managers scan the day at a glance, so a dark dashboard with vivid tiles.",
        "archetype": "DASHBOARD",
        "hue_family": "TEAL",
        "color_mode": "DARK",
        "color_scheme": "ANALOGOUS",
        "surface_tone": "COOL",
        "navigation": "SIDE_RAIL",
        "density": "COMPACT",
        "heading_family": "GEOMETRIC_SANS",
        "product_name": "Reservation desk",
        "tone": "TECHNICAL",
    }
    values.update(overrides)
    return visual(**values)


def alternative(
    code: str,
    visual_draft: VisualLanguageDraft,
    *,
    steps=THREE_STEPS,
    areas=("Reservation list", "Reservation detail"),
) -> AlternativeDraft:
    return AlternativeDraft(
        code=code,
        approach="GUIDED_WORKFLOW" if code == "DES-001" else "DASHBOARD_FIRST",
        title=f"Alternative {code}",
        summary="One direction.",
        rationale="Because.",
        requirements=("REQ-001",),
        stories=("USR-001",),
        criteria=("AC-001",),
        twins=("T1", "T2"),
        workflows=(
            WorkflowDraft(
                code=f"FLOW-{code[-3:]}",
                title="Update a reservation",
                steps=steps,
                requirements=("REQ-001",),
                stories=("USR-001",),
            ),
        ),
        information_architecture=areas,
        accessibility_considerations=("Labels persist.",),
        security_considerations=("Guest data is minimized.",),
        advantages=("Clear.",),
        trade_offs=("Slower.",),
        assumptions=(),
        open_questions=(),
        visual=visual_draft,
    )


def critiques(context) -> tuple[CritiqueDraft, ...]:
    items = []
    for code in ("DES-001", "DES-002"):
        for twin_key, twin in context["twins"].items():
            items.append(
                CritiqueDraft(
                    code=f"CRQ-{len(items) + 1:03d}",
                    alternative=code,
                    twin=twin_key,
                    observation_keys=(next(iter(twin["observations"])),),
                    strengths=("Clear.",),
                    concerns=("Dense.",),
                    unmet_needs=(),
                    accessibility_observations=(),
                    trust_concerns=(),
                    questions=(),
                    suggested_changes=(),
                    confidence=0.6,
                    rationale="Simulated view.",
                )
            )
    return tuple(items)


def draft(context, first: AlternativeDraft | None = None, second=None) -> DesignDraft:
    return DesignDraft(
        alternatives=(
            first or alternative("DES-001", visual()),
            second or alternative("DES-002", second_visual()),
        ),
        critiques=critiques(context),
        recommendation="DES-001",
        concerns=(),
        open_questions=(),
    )


def reference(code: str) -> EvidenceReference:
    return EvidenceReference(
        source_kind=EvidenceSourceKind.MODEL_OUTPUT,
        source_id="stub-provider",
        source_version=1,
        locator=code,
        content_hash=None,
    )


def bind(request, design_draft):
    _, twins = design_context(request)
    return bind_design(design_draft, request, twins, reference)


def test_bind_design_attaches_a_resolved_visual_language_to_each_alternative():
    request = proposal_request()
    context, _ = design_context(request)
    package = bind(request, draft(context))
    first, second = package.alternatives
    assert first.visual_language.choices.archetype is LayoutArchetype.GUIDED_STEPS
    assert second.visual_language.choices.archetype is LayoutArchetype.DASHBOARD
    assert first.visual_language.product_name == "Reservation steps"
    assert first.visual_language.rationale.startswith("Occasional receptionists")
    assert first.visual_language.palette_roles["on_primary"] == "#ffffff"
    assert (
        second.visual_language.palette_roles["background"]
        != first.visual_language.palette_roles["background"]
    )
    assert first.to_snapshot()["visual_language"]["choices"]["hue_family"] == "COBALT"


@pytest.mark.parametrize(
    ("second", "message"),
    [
        (
            lambda: second_visual(archetype="GUIDED_STEPS", navigation="TOP_BAR"),
            "different layout archetypes",
        ),
        (lambda: second_visual(hue_family="INDIGO"), "clearly different hue families"),
        (
            lambda: visual(archetype="DASHBOARD", hue_family="TEAL", navigation="SIDE_RAIL"),
            "further visual dimensions",
        ),
    ],
)
def test_bind_design_rejects_alternatives_that_look_alike(second, message):
    request = proposal_request()
    context, _ = design_context(request)
    with pytest.raises(ValueError, match=message):
        bind(request, draft(context, second=alternative("DES-002", second())))


def test_bind_design_rejects_navigation_and_flow_mismatches():
    request = proposal_request()
    context, _ = design_context(request)
    with pytest.raises(ValueError, match="navigation SIDE_RAIL is not available"):
        bind(request, draft(context, first=alternative("DES-001", visual(navigation="SIDE_RAIL"))))
    with pytest.raises(ValueError, match="workflow with at least 3 steps"):
        bind(request, draft(context, first=alternative("DES-001", visual(), steps=THREE_STEPS[:2])))
    with pytest.raises(ValueError, match="at least 2 information architecture areas"):
        bind(
            request,
            draft(context, second=alternative("DES-002", second_visual(), areas=("Overview",))),
        )


def test_alternative_schema_exposes_the_visual_language_through_catalog_enums():
    schema = DesignDraft.model_json_schema()
    properties = schema["$defs"]["VisualLanguageDraft"]["properties"]
    assert sorted(properties)[0] == "approach_rationale"
    assert schema["$defs"]["AlternativeDraft"]["properties"]["visual"]["$ref"].endswith(
        "VisualLanguageDraft"
    )
    archetypes = schema["$defs"]["LayoutArchetype"]["enum"]
    assert len(archetypes) == len(LayoutArchetype)
    assert schema["$defs"]["NavigationPattern"]["enum"] == [
        item.value for item in NavigationPattern
    ]
    assert properties["product_name"]["maxLength"] == 80


def test_design_instruction_carries_the_whole_catalog():
    assert visual_catalog_summary() in DESIGN_VISUAL_INSTRUCTION
    assert "approach_rationale" in DESIGN_VISUAL_INSTRUCTION
    assert "two different products" in DESIGN_VISUAL_INSTRUCTION


class _StubConfiguration:
    max_output_tokens = 8192


class _StubGenerator:
    provider_id = "stub-provider"
    configuration = _StubConfiguration()

    def __init__(self, output):
        self.output = output
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.output


def test_model_adapter_binds_the_visual_language_and_rejects_incoherent_output():
    request = proposal_request()
    context, _ = design_context(request)
    generator = _StubGenerator(draft(context))
    result = asyncio.run(ModelDesignAdapter(generator).propose(request))
    assert result.status is DesignProposalStatus.PROPOSED
    assert result.provider_version == 2
    assert all(item.visual_language is not None for item in result.package.alternatives)
    instruction = generator.calls[0]["instruction"]
    assert DESIGN_VISUAL_INSTRUCTION in instruction
    assert generator.calls[0]["output_type"] is DesignDraft
    assert generator.calls[0]["max_output_tokens"] == 6144
    incoherent = _StubGenerator(
        draft(
            context,
            second=alternative(
                "DES-002", second_visual(archetype="GUIDED_STEPS", navigation="TOP_BAR")
            ),
        )
    )
    with pytest.raises(ProposalGenerationError) as failure:
        asyncio.run(ModelDesignAdapter(incoherent).propose(request))
    assert failure.value.code == "INVALID_PROVIDER_OUTPUT"
