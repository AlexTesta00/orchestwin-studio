from __future__ import annotations

import asyncio
import re

import pytest
from pydantic import ValidationError

from orchestwin.artifacts.visual_catalog import (
    LayoutArchetype,
    NavigationPattern,
    visual_catalog_summary,
)
from orchestwin.artifacts.visual_language import MAX_TWIN_FIT_LENGTH
from orchestwin.models import design_drafts
from orchestwin.models.design import DesignProposalStatus
from orchestwin.models.design_drafts import (
    ALTERNATIVE_TEXT_LISTS,
    CRITIQUE_TEXT_LISTS,
    LANGUAGE_GROUPS,
    TEXT_LENGTH,
    TITLE_LENGTH,
    AlternativeDraft,
    ConcernDraft,
    CritiqueDraft,
    DesignDraft,
    VisualLanguageDraft,
    WorkflowDraft,
    bind_design,
    design_context,
    requirements_language,
)
from orchestwin.models.model_proposals import (
    DESIGN_NAMES_INSTRUCTION,
    DESIGN_VISUAL_INSTRUCTION,
    ModelDesignAdapter,
    design_instruction,
)
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.twins.epistemics import EvidenceReference, EvidenceSourceKind

from .draft_fixtures import italian_requirements
from .test_fake_design import proposal_request

THREE_STEPS = ("Open the reservation.", "Edit the dates.", "Confirm the change.")


@pytest.fixture(autouse=True)
def unrestricted_exploration(monkeypatch):
    from orchestwin.models import design_drafts

    monkeypatch.setattr(design_drafts, "visual_exploration", lambda project_id: {})


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
        "twin_fit": (
            {"twin": "T1", "statement": "Large controls and a calm palette suit the receptionist."},
            {"twin": "T2", "statement": "Compact tiles let the manager scan the day at a glance."},
        ),
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


def test_bind_design_requires_one_twin_fit_per_twin():
    request = proposal_request()
    context, _ = design_context(request)
    partial = visual(twin_fit=({"twin": "T1", "statement": "Only one twin covered."},))
    with pytest.raises(ValueError, match="cover every twin exactly once"):
        bind(request, draft(context, first=alternative("DES-001", partial)))
    doubled = visual(
        twin_fit=(
            {"twin": "T1", "statement": "First."},
            {"twin": "T1", "statement": "Again."},
        )
    )
    with pytest.raises(ValueError, match="cover every twin exactly once"):
        bind(request, draft(context, first=alternative("DES-001", doubled)))
    package = bind(request, draft(context))
    fits = package.alternatives[0].visual_language.twin_fit
    assert [item.name for item in fits] == [
        twin.reference.name for twin in request.user_modeling.user_twins
    ]
    assert fits[0].statement.startswith("Large controls")


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


def test_alternative_draft_no_longer_asks_for_an_approach():
    schema = DesignDraft.model_json_schema()
    assert "approach" not in schema["$defs"]["AlternativeDraft"]["properties"]
    assert "DesignApproach" not in schema["$defs"]
    payload = alternative("DES-001", visual()).model_dump(mode="json")
    with pytest.raises(ValidationError, match="approach"):
        AlternativeDraft.model_validate({**payload, "approach": "GUIDED_WORKFLOW"})
    request = proposal_request()
    context, _ = design_context(request)
    package = bind(request, draft(context))
    assert [item.approach for item in package.alternatives] == [None, None]
    assert all("approach" not in item.to_snapshot() for item in package.alternatives)


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
    assert result.provider_version == 4
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


KEY = re.compile(r"\bT[12]\b")
NAMES = {"T1": "Hotel Receptionist Twin", "T2": "Hotel Manager Twin"}
ITALIAN = {
    "summary": "Il flusso guidato accompagna T1 in ogni passo della prenotazione.",
    "rationale": "La receptionist lavora con la coda allo sportello e ha bisogno di un passo "
    "alla volta.",
    "approach_rationale": "Una palette calma e un passo per schermata servono a chi lavora al "
    "banco.",
    "fit_one": "I controlli grandi e la palette calma aiutano T1 durante il turno di notte.",
    "fit_two": "Le schede compatte permettono a T2 di controllare la giornata con uno sguardo.",
    "critique": "Il flusso è chiaro per me, ma la ricerca della prenotazione è lenta.",
}
ENGLISH = {
    "summary": "The guided flow walks T1 through every step of the booking.",
    "rationale": "The receptionist works with a queue at the desk and needs one step at a time.",
    "approach_rationale": "A calm palette and one step per screen serve the people who work at "
    "the desk.",
    "fit_one": "Large controls and the calm palette help T1 during the night shift.",
    "fit_two": "Compact tiles let T2 check the day at a glance from the dashboard.",
    "critique": "The flow is clear for me, but the search for the booking is slow.",
}


def worded_draft(context, first_words, second_words, critique_texts) -> DesignDraft:
    def fits(words):
        return (
            {"twin": "T1", "statement": words["fit_one"]},
            {"twin": "T2", "statement": words["fit_two"]},
        )

    first = alternative(
        "DES-001",
        visual(approach_rationale=first_words["approach_rationale"], twin_fit=fits(first_words)),
    )
    second = alternative(
        "DES-002",
        second_visual(
            approach_rationale=second_words["approach_rationale"], twin_fit=fits(second_words)
        ),
    )
    base = draft(context, first=first, second=second)
    return base.model_copy(
        update={
            "alternatives": tuple(
                item.model_copy(
                    update={"summary": words["summary"], "rationale": words["rationale"]}
                )
                for item, words in zip(base.alternatives, (first_words, second_words), strict=True)
            ),
            "critiques": tuple(
                item.model_copy(update={"rationale": text})
                for item, text in zip(base.critiques, critique_texts, strict=True)
            ),
        }
    )


def keyed_alternative(code: str, visual_draft: VisualLanguageDraft) -> AlternativeDraft:
    def keyed(label):
        return f"{label} of {code} for T1 and T2."

    return AlternativeDraft(
        code=code,
        title=keyed("Title"),
        summary=keyed("Summary"),
        rationale=keyed("Rationale"),
        requirements=("REQ-001",),
        stories=("USR-001",),
        criteria=("AC-001",),
        twins=("T1", "T2"),
        workflows=(
            WorkflowDraft(
                code=f"FLOW-{code[-3:]}",
                title=keyed("Workflow"),
                steps=tuple(keyed(f"Step {index}") for index in range(1, 4)),
                requirements=("REQ-001",),
                stories=("USR-001",),
            ),
        ),
        **{key: (keyed(f"{key} one"), keyed(f"{key} two")) for key in ALTERNATIVE_TEXT_LISTS},
        visual=visual_draft,
    )


def keyed_visual(base, product_name: str) -> VisualLanguageDraft:
    return base(
        approach_rationale=f"Look of {product_name} for T1 and T2.",
        product_name=product_name,
        twin_fit=(
            {"twin": "T1", "statement": f"Fit of {product_name} for T1 next to T2."},
            {"twin": "T2", "statement": f"Fit of {product_name} for T2 next to T1."},
        ),
    )


def keyed_draft(context) -> DesignDraft:
    return DesignDraft(
        alternatives=(
            keyed_alternative("DES-001", keyed_visual(visual, "Desk T1")),
            keyed_alternative("DES-002", keyed_visual(second_visual, "Board T2")),
        ),
        critiques=tuple(
            item.model_copy(
                update={
                    "rationale": f"Rationale of {item.code} for T1 and T2.",
                    **{
                        key: (f"{key} of {item.code} for T1 and T2.",)
                        for key in CRITIQUE_TEXT_LISTS
                    },
                }
            )
            for item in critiques(context)
        ),
        recommendation="DES-001",
        concerns=(
            ConcernDraft(
                code="DRK-001",
                summary="Summary of the concern for T1 and T2.",
                mitigation="Mitigation of the concern for T1 and T2.",
                requirements=("REQ-001",),
                alternatives=("DES-001",),
            ),
        ),
        open_questions=("Open question for T1 and T2.",),
    )


def package_texts(package):
    for item in package.alternatives:
        yield item.title
        yield item.summary
        yield item.rationale
        for key in ALTERNATIVE_TEXT_LISTS:
            yield from getattr(item, key)
        for workflow in item.workflows:
            yield workflow.title
            yield from workflow.steps
        yield item.visual_language.rationale
        yield from (fit.statement for fit in item.visual_language.twin_fit)
    for item in package.critiques:
        yield item.rationale
        for key in CRITIQUE_TEXT_LISTS:
            yield from getattr(item, key)
    for item in package.concerns:
        yield item.summary
        yield item.mitigation
    yield from package.open_questions


def test_design_context_carries_the_language_of_the_requirements_and_the_twin_names():
    english, twins = design_context(proposal_request())
    italian, _ = design_context(italian_requirements(proposal_request()))
    assert english["language"] == {"code": "en", "name": "English"}
    assert italian["language"] == {"code": "it", "name": "Italian"}
    assert {key: twin["name"] for key, twin in english["twins"].items()} == NAMES
    assert all(english["twins"][key]["name"] == twin.reference.name for key, twin in twins.items())
    assert italian["twins"] == english["twins"]
    empty = {group: [] for group in LANGUAGE_GROUPS}
    assert requirements_language(empty) is None
    assert requirements_language({**empty, "stories": [{"goal": "il la di che per"}]}) == {
        "code": "it",
        "name": "Italian",
    }
    assert (
        requirements_language({**empty, "stories": [{"goal": "il la di", "code": "che"}]}) is None
    )
    assert (
        requirements_language({**empty, "risks": [{"statement": "the and with that this for"}]})
        is None
    )
    assert (
        requirements_language(
            {
                **empty,
                "requirements": [{"statement": "il la di che per il la"}],
                "scenarios": [{"steps": ["the and with that this for"]}],
            }
        )
        is None
    )


def test_the_design_instruction_names_the_language_of_the_requirements_and_the_twins(
    monkeypatch,
):
    request = proposal_request()
    context, _ = design_context(request)
    generator = _StubGenerator(draft(context))
    asyncio.run(ModelDesignAdapter(generator).propose(request))
    known = generator.calls[0]["instruction"]
    assert generator.calls[0]["context"]["language"] == {"code": "en", "name": "English"}
    assert known == design_instruction("T1/T2", {"code": "en", "name": "English"})
    assert known.startswith(
        "Propose exactly two distinct design approaches. Write every text in English, the "
        "language of the requirements: titles, summaries, rationales, workflow titles and "
        "steps, considerations, advantages, trade-offs, assumptions, questions, critiques, "
        "concerns, approach_rationale and twin_fit statements; only codes and catalog ids stay "
        "as they are. Use DES-001 codes"
    )
    assert known.endswith(
        DESIGN_VISUAL_INSTRUCTION + " In every text call the twins by their names in twins, "
        "never by their keys: keys appear only in the twin and twins fields. Every text is "
        "written in English."
    )
    assert "T1/T2 twin keys" in known
    italian = design_instruction("T1/T2", {"code": "it", "name": "Italian"})
    assert "Write every text in Italian, the language of the requirements" in italian
    assert italian.endswith("Every text is written in Italian.")
    monkeypatch.setattr(design_drafts, "requirements_language", lambda view: None)
    unknown = _StubGenerator(draft(context))
    asyncio.run(ModelDesignAdapter(unknown).propose(request))
    instruction = unknown.calls[0]["instruction"]
    assert unknown.calls[0]["context"]["language"] is None
    assert instruction == design_instruction("T1/T2", None)
    assert instruction.startswith(
        "Propose exactly two distinct design approaches in the requirements' language. Use "
        "DES-001 codes"
    )
    assert instruction.endswith(DESIGN_VISUAL_INSTRUCTION + " " + DESIGN_NAMES_INSTRUCTION)
    assert "Every text is written in" not in instruction


def test_bind_design_names_the_twins_in_every_text_of_the_design():
    request = proposal_request()
    context, _ = design_context(request)
    package = bind(request, keyed_draft(context))
    texts = list(package_texts(package))
    assert len(texts) == 83
    assert not [text for text in texts if KEY.search(text)]
    assert all(NAMES["T1"] in text and NAMES["T2"] in text for text in texts)
    assert package.alternatives[0].title == f"Title of DES-001 for {NAMES['T1']} and {NAMES['T2']}."
    assert [item.visual_language.product_name for item in package.alternatives] == [
        "Desk T1",
        "Board T2",
    ]
    assert [item.code for item in package.alternatives] == ["DES-001", "DES-002"]
    assert all(
        item.user_twin_references == package.grounding.user_twin_references
        for item in package.alternatives
    )
    assert [fit.name for fit in package.alternatives[0].visual_language.twin_fit] == [
        NAMES["T1"],
        NAMES["T2"],
    ]


def test_bind_design_keeps_the_keys_where_the_names_would_not_fit():
    request = proposal_request()
    context, _ = design_context(request)
    long_title = "T1 " + "a" * (TITLE_LENGTH - 3)
    fitting_title = "T1 " + "b" * (TITLE_LENGTH - len(NAMES["T1"]) - 1)
    long_text = "T2 " + "c" * (TEXT_LENGTH - 3)
    long_fit = "T1 " + "d" * (MAX_TWIN_FIT_LENGTH - 3)
    first = alternative(
        "DES-001",
        visual(
            twin_fit=(
                {"twin": "T1", "statement": long_fit},
                {"twin": "T2", "statement": "Compact tiles suit T2."},
            )
        ),
    ).model_copy(update={"title": long_title, "summary": long_text})
    second = alternative("DES-002", second_visual()).model_copy(
        update={"title": fitting_title, "summary": "Summary for T1."}
    )
    base = draft(context, first=first, second=second)
    keyed = base.model_copy(
        update={
            "critiques": (
                base.critiques[0].model_copy(update={"rationale": long_text}),
                *base.critiques[1:],
            )
        }
    )
    package = bind(request, keyed)
    one, two = package.alternatives
    assert (one.title, one.summary) == (long_title, long_text)
    assert one.visual_language.twin_fit[0].statement == long_fit
    assert one.visual_language.twin_fit[1].statement == f"Compact tiles suit {NAMES['T2']}."
    assert package.critiques[0].rationale == long_text
    assert two.title == NAMES["T1"] + fitting_title[2:]
    assert len(two.title) == TITLE_LENGTH
    assert two.summary == f"Summary for {NAMES['T1']}."


def test_bind_design_rejects_a_design_mostly_in_another_language_than_the_requirements(
    monkeypatch,
):
    english_request = proposal_request()
    italian_request = italian_requirements(english_request)
    context, _ = design_context(italian_request)
    english = worded_draft(context, ENGLISH, ENGLISH, (ENGLISH["critique"],) * 4)
    italian = worded_draft(context, ITALIAN, ITALIAN, (ITALIAN["critique"],) * 4)
    with pytest.raises(ValueError, match="not written in the language of the requirements"):
        bind(italian_request, english)
    with pytest.raises(ValueError, match="not written in the language of the requirements"):
        bind(english_request, italian)
    accepted = bind(english_request, english)
    assert accepted.alternatives[0].summary == (
        f"The guided flow walks {NAMES['T1']} through every step of the booking."
    )
    assert bind(italian_request, italian).alternatives[0].summary == (
        f"Il flusso guidato accompagna {NAMES['T1']} in ogni passo della prenotazione."
    )
    monkeypatch.setattr(design_drafts, "requirements_language", lambda view: None)
    assert (
        bind(italian_request, english).alternatives[0].summary == accepted.alternatives[0].summary
    )


def test_bind_design_accepts_a_minority_of_texts_in_another_language():
    request = italian_requirements(proposal_request())
    context, _ = design_context(request)
    english, italian = ENGLISH["critique"], ITALIAN["critique"]
    minority = worded_draft(context, ITALIAN, ITALIAN, (english,) * 4)
    half = worded_draft(context, ENGLISH, ITALIAN, (english, english, italian, italian))
    more = worded_draft(context, ENGLISH, ITALIAN, (english, english, english, italian))
    assert bind(request, minority).critiques[0].rationale == english
    assert bind(request, half).alternatives[1].rationale == ITALIAN["rationale"]
    with pytest.raises(ValueError, match="not written in the language of the requirements"):
        bind(request, more)


def test_design_model_adapter_turns_a_design_in_another_language_into_invalid_output():
    request = italian_requirements(proposal_request())
    context, _ = design_context(request)
    generator = _StubGenerator(worded_draft(context, ENGLISH, ENGLISH, (ENGLISH["critique"],) * 4))
    with pytest.raises(ProposalGenerationError) as failure:
        asyncio.run(ModelDesignAdapter(generator).propose(request))
    assert failure.value.code == "INVALID_PROVIDER_OUTPUT"
    assert "not written in the language of the requirements" in str(failure.value.__cause__)
    assert generator.calls[0]["instruction"] == design_instruction(
        "T1/T2", {"code": "it", "name": "Italian"}
    )
