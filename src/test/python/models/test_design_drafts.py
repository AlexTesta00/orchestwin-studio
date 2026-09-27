from __future__ import annotations

import asyncio
import json
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
    CATALOG_IDS,
    CRITIQUE_DOMAIN_FIELDS,
    CRITIQUE_TEXT_LISTS,
    LANGUAGE_GROUPS,
    TEXT_LENGTH,
    TITLE_LENGTH,
    UNCHOSEN_CATALOG_VALUES,
    AlternativeDraft,
    ConcernDraft,
    CritiqueDraft,
    DesignDraft,
    TwinFitDraft,
    VisualLanguageDraft,
    WorkflowDraft,
    bind_design,
    catalog_ids,
    chosen_catalog_ids,
    consistent_draft,
    consistent_text,
    design_context,
    requirements_language,
    schema_minimum,
)
from orchestwin.models.model_proposals import (
    DESIGN_NAMES_INSTRUCTION,
    DESIGN_VISUAL_INSTRUCTION,
    ModelDesignAdapter,
    design_instruction,
)
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.projects.requirements_primitives import canonical_json
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
        "visual_rationale": "Occasional receptionists need one decision at a time in a calm palette.",
    }
    values.update(overrides)
    return VisualLanguageDraft(**values)


def second_visual(**overrides) -> VisualLanguageDraft:
    values = {
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
        "visual_rationale": "Managers scan the day at a glance, so a dark dashboard with vivid tiles.",
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
                    as_twin=twin_key,
                    observation_keys=(next(iter(twin["observations"])),),
                    strengths=("Clear.",),
                    concerns=("Dense.",),
                    unmet_needs=(),
                    on_accessibility=(),
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
    wire = json.loads(canonical_json(schema))["$defs"]["VisualLanguageDraft"]["properties"]
    assert list(wire)[-3:] == ["twin_fit", "type_scale", "visual_rationale"]
    assert "approach_rationale" not in properties
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
    assert "two different products" in DESIGN_VISUAL_INSTRUCTION
    assert "approach_rationale" not in DESIGN_VISUAL_INSTRUCTION
    assert (
        "Choose the values of visual first: the archetype follows the shape of the task and its "
        "flows, the colours and typography follow the domain, the tone and the twins' age, "
        "context of use, accessibility needs and vocabulary. visual_rationale comes last and "
        "explains the values you chose. A text names a catalog id only when it is a value chosen "
        "by the alternative the text talks about; summary, rationale and the lists of an "
        "alternative describe the approach, the flows and the content. product_name is"
    ) in DESIGN_VISUAL_INSTRUCTION
    assert (
        "and on_accessibility must address it whenever the twin has accessibility needs. Every "
        "critique judges only the alternative named in its alternative field, from the point of "
        "view of the twin named in as_twin. The two alternatives"
    ) in DESIGN_VISUAL_INSTRUCTION
    assert DESIGN_NAMES_INSTRUCTION.endswith(
        "keys appear only in the twin, as_twin and twins fields."
    )
    for language in (None, {"code": "it", "name": "Italian"}):
        instruction = design_instruction("T1/T2", language)
        assert DESIGN_VISUAL_INSTRUCTION in instruction
        assert DESIGN_NAMES_INSTRUCTION in instruction
        assert "approach_rationale" not in instruction
        assert "accessibility_observations" not in instruction
        assert "on_accessibility" in instruction
    assert "concerns, visual_rationale and twin_fit statements" in design_instruction(
        "T1/T2", {"code": "it", "name": "Italian"}
    )


def test_a_critique_names_its_alternative_and_its_twin_before_its_content():
    wire = json.loads(canonical_json(DesignDraft.model_json_schema()))["$defs"]["CritiqueDraft"]
    assert list(wire["properties"]) == [
        "alternative",
        "as_twin",
        "code",
        "concerns",
        "confidence",
        "observation_keys",
        "on_accessibility",
        "questions",
        "rationale",
        "strengths",
        "suggested_changes",
        "trust_concerns",
        "unmet_needs",
    ]
    assert CRITIQUE_DOMAIN_FIELDS == {"on_accessibility": "accessibility_observations"}
    assert "twin" in json.loads(canonical_json(TwinFitDraft.model_json_schema()))["properties"]
    request = proposal_request()
    context, _ = design_context(request)
    renamed = with_critique(
        draft(context), 1, on_accessibility=("Labels stay visible for T2 at the desk.",)
    )
    package = bind(request, renamed)
    references = [twin.reference for twin in request.user_modeling.user_twins]
    assert [item.user_twin_reference for item in package.critiques] == references * 2
    assert package.critiques[1].accessibility_observations == (
        f"Labels stay visible for {NAMES['T2']} at the desk.",
    )
    assert package.critiques[0].accessibility_observations == ()
    with pytest.raises(ValidationError):
        CritiqueDraft.model_validate({**renamed.critiques[0].model_dump(mode="json"), "twin": "T1"})


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
    assert result.provider_version == 6
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
    "visual_rationale": "Una palette calma e un passo per schermata servono a chi lavora al banco.",
    "fit_one": "I controlli grandi e la palette calma aiutano T1 durante il turno di notte.",
    "fit_two": "Le schede compatte permettono a T2 di controllare la giornata con uno sguardo.",
    "critique": "Il flusso è chiaro per me, ma la ricerca della prenotazione è lenta.",
}
ENGLISH = {
    "summary": "The guided flow walks T1 through every step of the booking.",
    "rationale": "The receptionist works with a queue at the desk and needs one step at a time.",
    "visual_rationale": "A calm palette and one step per screen serve the people who work at "
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
        visual(visual_rationale=first_words["visual_rationale"], twin_fit=fits(first_words)),
    )
    second = alternative(
        "DES-002",
        second_visual(
            visual_rationale=second_words["visual_rationale"], twin_fit=fits(second_words)
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
        visual_rationale=f"Look of {product_name} for T1 and T2.",
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
            yield from getattr(item, CRITIQUE_DOMAIN_FIELDS.get(key, key))
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
        "concerns, visual_rationale and twin_fit statements; only codes and catalog ids stay "
        "as they are. Use DES-001 codes"
    )
    assert known.endswith(
        DESIGN_VISUAL_INSTRUCTION + " In every text call the twins by their names in twins, "
        "never by their keys: keys appear only in the twin, as_twin and twins fields. Every "
        "text is written in English."
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


def with_alternative(design_draft, index, **update) -> DesignDraft:
    alternatives = list(design_draft.alternatives)
    alternatives[index] = alternatives[index].model_copy(update=update)
    return design_draft.model_copy(update={"alternatives": tuple(alternatives)})


def with_critique(design_draft, index, **update) -> DesignDraft:
    items = list(design_draft.critiques)
    items[index] = items[index].model_copy(update=update)
    return design_draft.model_copy(update={"critiques": tuple(items)})


def with_workflow(design_draft, **update) -> DesignDraft:
    workflow = design_draft.alternatives[0].workflows[0].model_copy(update=update)
    return with_alternative(design_draft, 0, workflows=(workflow,))


def with_visual(design_draft, index, **update) -> DesignDraft:
    visual_draft = design_draft.alternatives[index].visual.model_copy(update=update)
    return with_alternative(design_draft, index, visual=visual_draft)


def with_first_fit(design_draft, statement: str) -> DesignDraft:
    fits = design_draft.alternatives[0].visual.twin_fit
    first = fits[0].model_copy(update={"statement": statement})
    return with_visual(design_draft, 0, twin_fit=(first, *fits[1:]))


def with_concern(design_draft, summary: str, mitigation: str, alternatives) -> DesignDraft:
    concern = ConcernDraft(
        code="DRK-001",
        summary=summary,
        mitigation=mitigation,
        requirements=("REQ-001",),
        alternatives=alternatives,
    )
    return design_draft.model_copy(update={"concerns": (concern,)})


def test_catalog_ids_are_the_upper_case_values_of_the_visual_dimensions():
    assert {"GUIDED_STEPS", "HIGH_CONTRAST_DARK", "OLD_STYLE_SERIF", "NONE"} <= CATALOG_IDS
    assert not {"PDF", "SMS", "DES", "OK", "HIGH_CONTRAST"} & CATALOG_IDS
    assert catalog_ids(
        "OLD_STYLE_SERIF titles, a HIGH_CONTRAST mode, HIGH_CONTRAST_DARK colours, the PDF by "
        "SMS, DES-001, Dashboard, dashboard and T1."
    ) == {"OLD_STYLE_SERIF", "HIGH_CONTRAST_DARK"}
    request = proposal_request()
    context, _ = design_context(request)
    chosen = chosen_catalog_ids(draft(context))
    assert set(chosen) == {"DES-001", "DES-002"}
    assert {"GUIDED_STEPS", "COBALT", "LIGHT", "FILLED", "HUMANIST_SANS"} <= chosen["DES-001"]
    assert {"DASHBOARD", "TEAL", "DARK", "SIDE_RAIL"} <= chosen["DES-002"]
    assert "DASHBOARD" not in chosen["DES-001"]
    minimums = {
        field: schema_minimum(model, field)
        for model, field in (
            (AlternativeDraft, "advantages"),
            (AlternativeDraft, "assumptions"),
            (CritiqueDraft, "strengths"),
            (CritiqueDraft, "questions"),
            (DesignDraft, "open_questions"),
        )
    }
    assert minimums == {
        "advantages": 1,
        "assumptions": 0,
        "strengths": 1,
        "questions": 0,
        "open_questions": 0,
    }


def test_consistent_text_removes_only_the_sentences_with_values_that_were_not_chosen():
    chosen = {"DES-001": frozenset({"GUIDED_STEPS", "FILLED"}), "DES-002": frozenset({"DASHBOARD"})}
    text = "Short steps help.  The DASHBOARD hides them!\nFILLED buttons guide me? Maybe… Fine"
    assert consistent_text(text, ("DES-001",), chosen) == (
        "Short steps help. FILLED buttons guide me? Maybe… Fine"
    )
    assert consistent_text(text, ("DES-001", "DES-002"), chosen) == text
    assert consistent_text("The DASHBOARD of DES-002 is busy.", ("DES-001",), chosen) == (
        "The DASHBOARD of DES-002 is busy."
    )
    assert consistent_text("The DASHBOARD of DES-009 is busy.", ("DES-001",), chosen) == ""
    assert consistent_text("The DASHBOARD is busy.", ("DES-009",), chosen) == ""
    untouched = "Send the PDF by SMS to the guest. It is OK for DES-001."
    assert consistent_text(untouched, ("DES-001",), chosen) is untouched


def test_bind_design_removes_the_sentence_that_names_a_value_the_alternative_did_not_choose():
    request = proposal_request()
    context, _ = design_context(request)
    rationale = (
        "A calm palette guides the receptionist. The typography pairs OLD_STYLE_SERIF headings "
        "with GROTESQUE_SANS text. FILLED buttons make the next step obvious."
    )
    first = alternative(
        "DES-001", visual(heading_family="MODERN_SERIF", visual_rationale=rationale)
    )
    package = bind(request, draft(context, first=first))
    assert package.alternatives[0].visual_language.choices.heading_family.value == "MODERN_SERIF"
    assert package.alternatives[0].visual_language.rationale == (
        "A calm palette guides the receptionist. FILLED buttons make the next step obvious."
    )


def test_a_critique_keeps_the_values_of_the_alternative_it_names_and_loses_the_others():
    request = proposal_request()
    context, _ = design_context(request)
    base = draft(context)
    critique = (
        "The DASHBOARD layout of DES-001 hides the steps from me. "
        "The DASHBOARD approach in DES-002 may overwhelm me."
    )
    keyed = with_critique(
        base,
        0,
        rationale=critique,
        concerns=("Dense.", "The LIST_DETAIL approach in DES-001 splits my attention."),
        questions=("Will the KANBAN_BOARD come back?",),
    )
    keyed = with_alternative(
        keyed,
        0,
        advantages=("Clear.", "The DARK mode rests the eyes."),
        assumptions=("Receptionists like the GUIDED_STEPS flow.",),
    )
    keyed = keyed.model_copy(
        update={
            "open_questions": (
                "Should the DASHBOARD also show the GUIDED_STEPS?",
                "Should the KANBAN_BOARD come back?",
            )
        }
    )
    package = bind(request, keyed)
    first = package.critiques[0]
    assert first.rationale == "The DASHBOARD approach in DES-002 may overwhelm me."
    assert first.concerns == ("Dense.",)
    assert first.questions == ()
    assert package.alternatives[0].advantages == ("Clear.",)
    assert package.alternatives[0].assumptions == ("Receptionists like the GUIDED_STEPS flow.",)
    assert package.open_questions == ("Should the DASHBOARD also show the GUIDED_STEPS?",)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: with_alternative(d, 0, title="The KANBAN_BOARD desk"),
        lambda d: with_alternative(d, 0, summary="The DASHBOARD shows everything at once."),
        lambda d: with_alternative(d, 1, rationale="Managers like GUIDED_STEPS."),
        lambda d: with_alternative(d, 0, advantages=("The DARK mode rests the eyes.",)),
        lambda d: with_workflow(d, steps=("Open the booking.", "Pick a SIDE_RAIL entry.", "Save.")),
        lambda d: with_workflow(d, title="TABS flow"),
        lambda d: with_visual(d, 1, visual_rationale="A COBALT palette calms the desk."),
        lambda d: with_first_fit(d, "The TEAL tiles suit T1."),
        lambda d: with_critique(d, 2, rationale="The GUIDED_STEPS of this design slow me."),
        lambda d: with_critique(d, 1, strengths=("The DARK mode is restful.",)),
        lambda d: with_concern(
            d, "The DASHBOARD crowds the screen.", "Keep fewer tiles.", ("DES-001",)
        ),
        lambda d: with_concern(
            d, "Too many tiles.", "Use the KANBAN_BOARD.", ("DES-001", "DES-002")
        ),
    ],
)
def test_bind_design_rejects_a_required_text_left_without_sentences(change):
    request = proposal_request()
    context, _ = design_context(request)
    with pytest.raises(ValueError, match=UNCHOSEN_CATALOG_VALUES):
        bind(request, change(draft(context)))


def test_a_concern_may_name_the_values_of_its_linked_alternatives():
    request = proposal_request()
    context, _ = design_context(request)
    summary = "The DASHBOARD crowds the screen of the manager."
    mitigation = "Keep the GUIDED_STEPS for occasional receptionists."
    linked = with_concern(draft(context), summary, mitigation, ("DES-001", "DES-002"))
    package = bind(request, linked)
    assert (package.concerns[0].summary, package.concerns[0].mitigation) == (summary, mitigation)


def test_a_draft_without_inconsistent_mentions_is_returned_unchanged():
    request = proposal_request()
    context, _ = design_context(request)
    consistent = with_critique(
        with_alternative(
            draft(context),
            0,
            summary="The GUIDED_STEPS flow uses FILLED buttons. The PDF receipt goes out by SMS.",
        ),
        0,
        rationale="The DASHBOARD of DES-002 is busier than these GUIDED_STEPS.",
    )
    assert consistent_draft(consistent) == consistent
    package = bind(request, consistent)
    assert package.alternatives[0].summary == consistent.alternatives[0].summary
    assert package.critiques[0].rationale == consistent.critiques[0].rationale
