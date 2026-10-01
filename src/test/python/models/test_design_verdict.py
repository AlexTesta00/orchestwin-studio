from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from orchestwin.agents.perspectives import GuidanceStage, perspective_guidance
from orchestwin.artifacts.visual_catalog import SCRIPT_TONES, DesignTone
from orchestwin.models import design_drafts
from orchestwin.models.anthropic_hosted import build_anthropic_adapter
from orchestwin.models.design_drafts import (
    HOSTED_DESIGN_CONTRACT_VERSION,
    HOSTED_DESIGN_PURPOSE,
    DesignDraft,
    HostedCritiqueDraft,
    HostedDesignDraft,
    design_context,
    hosted_design_context,
)
from orchestwin.models.generation_routing import RoutingProposalGenerator
from orchestwin.models.hosted_configuration import ModelRoutes
from orchestwin.models.hosted_schema import hosted_output_schema
from orchestwin.models.model_proposals import (
    CRITIQUE_LIST_INSTRUCTIONS,
    HOSTED_DESIGN_OUTPUT_TOKENS,
    HOSTED_SCHEMA_INSTRUCTION,
    ModelDesignAdapter,
    ModelRequirementsAdapter,
    ModelTeamProposalAdapter,
    ModelUserModelingAdapter,
    design_instruction,
    design_output_tokens,
    hosted_design_instruction,
)
from orchestwin.models.planning_schema import CRITIQUE_LISTS, constrain_planning_schema
from orchestwin.models.proposal_generation import ProposalGenerationError, ProposalGenerator
from orchestwin.models.structured_generation import StructuredGenerationProviderKind
from orchestwin.projects.requirements_primitives import canonical_json

from . import test_fake_requirements as requirements_fixtures
from . import test_fake_team_proposal_adapter as team_fixtures
from .draft_fixtures import proposal_draft
from .test_design_drafts import NAMES, bind, draft
from .test_fake_design import proposal_request
from .test_hosted_schema import CapturePort
from .test_hosted_support import TEST_KEY, FakeAnthropicClient, message, providers
from .test_model_proposals import make_generator, persona_input_output, twin_input_output

LOCAL = StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL
ANTHROPIC = StructuredGenerationProviderKind.ANTHROPIC_HOSTED
LOCAL_DRAFT_SCHEMA = "7e22f08912cef240348325b86b72281a44147117a98efb6d0db3c02c8e1cf057"
LOCAL_REQUEST_SCHEMA = "e48f94f8876ffd5bc0a876a19bc472b3e54436d0fe41c02a331bfb66a53a8228"
LOCAL_REQUEST_INSTRUCTION = "fd3ba57cc0ca0b209dde7f7a270cacf7b27fb32e05678de3813bf6d7aea79a91"
LOCAL_INSTRUCTIONS = {
    ("T1/T2", None): "12361a0fb583eaf1827695c781b4fd2006154cfe9df857179fbf9e508be7d8e8",
    ("T1/T2/T3", "Italian"): "6ddd239c03bf1de23b0822dab12f2e020283f5637c06954eb4ada5975a6ec347",
}
LOCAL_BUDGETS = (6144, 6144, 8192, 10240, 12288, 14336, 16384, 18432)
VERDICTS = (
    ("Utile, con riserve", "Trovo subito la prenotazione, ma il riepilogo mi rallenta."),
    ("Chiara per il turno", "Vedo lo stato del giorno senza aprire altre schermate."),
    ("Troppo densa al banco", "Con la coda davanti fatico a trovare il pulsante giusto."),
    ("Non la usa direttamente", "Io controllo i totali, questa schermata non mi serve."),
)
THREE_TWINS = {
    "T1": ("Receptionist", ("user_twin.goals", "user_twin.context_of_use")),
    "T2": ("Manager", ("user_twin.information_needs",)),
    "T3": ("Night auditor", ("user_twin.frustrations", "user_twin.accessibility_needs")),
}
EXPLORATION = {
    "DES-001": {
        "hue_family": ["COBALT", "TEAL", "FOREST", "OCHRE", "ROSE"],
        "heading_family": ["HUMANIST_SANS", "SLAB_SERIF", "GEOMETRIC_SANS"],
        "body_family": ["SYSTEM_UI", "OLD_STYLE_SERIF"],
        "color_scheme": ["ANALOGOUS", "MONOCHROME"],
        "background": ["PLAIN", "TINTED"],
        "corners": ["SOFT", "ROUND"],
        "header": ["COMPACT_BAR", "MINIMAL"],
    },
    "DES-002": {
        "hue_family": ["CORAL", "VIOLET", "SLATE", "AMBER", "OCEAN"],
        "heading_family": ["SCRIPT", "MONOSPACE", "NARROW_SANS"],
        "body_family": ["HUMANIST_SANS", "TRANSITIONAL_SERIF"],
        "color_scheme": ["SPLIT_COMPLEMENTARY", "NEUTRAL_ACCENT"],
        "background": ["GRID", "STRIPES"],
        "corners": ["SHARP", "PILL"],
        "header": ["HERO_BAND", "CENTERED_TITLE"],
        "color_mode": ["DARK", "HIGH_CONTRAST_LIGHT", "HIGH_CONTRAST_DARK"],
    },
}


@pytest.fixture
def unrestricted(monkeypatch):
    monkeypatch.setattr(design_drafts, "visual_exploration", lambda project_id: {})


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hosted_draft(design_draft, verdicts=VERDICTS) -> HostedDesignDraft:
    critiques = tuple(
        HostedCritiqueDraft(**item.model_dump(), verdict=verdict, quote=quote)
        for item, (verdict, quote) in zip(design_draft.critiques, verdicts, strict=True)
    )
    return HostedDesignDraft(**{**design_draft.model_dump(), "critiques": critiques})


def three_twin_context():
    context, _ = design_context(proposal_request())
    template = next(iter(context["twins"].values()))
    value = next(iter(template["observations"].values()))
    twins = {
        key: {
            "name": name,
            "reference": template["reference"],
            "observations": dict.fromkeys(keys, value),
        }
        for key, (name, keys) in THREE_TWINS.items()
    }
    return {
        **context,
        "language": {"code": "it", "name": "Italian"},
        "twins": twins,
        "visual_exploration": EXPLORATION,
    }


class RouteGenerator:
    def __init__(self, name, kind, ceiling, output=None):
        self.name = name
        self.provider_id = f"model-proposals-{name}"
        self.configuration = SimpleNamespace(
            provider_kind=kind,
            max_output_tokens=ceiling,
            identity=SimpleNamespace(content_hash=digest(name)),
        )
        self.output = output
        self.calls = []

    def route(self, task, purpose=None):
        return self

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.output, BaseModel):
            return self.output
        return kwargs["output_type"].model_validate(self.output)


def routing(routes, **generators):
    return RoutingProposalGenerator(generators, ModelRoutes(**routes))


def captured_local_request(tmp_path):
    base, _ = make_generator(tmp_path, {})
    port = CapturePort()
    with pytest.raises(ProposalGenerationError):
        asyncio.run(
            ModelDesignAdapter(ProposalGenerator(base.configuration, port)).propose(
                proposal_request()
            )
        )
    [request] = port.requests
    return request


def test_the_local_design_draft_its_instruction_and_its_budgets_stay_byte_identical(tmp_path):
    assert digest(canonical_json(DesignDraft.model_json_schema())) == LOCAL_DRAFT_SCHEMA
    request = captured_local_request(tmp_path)
    assert digest(request.output_schema.canonical_schema_json) == LOCAL_REQUEST_SCHEMA
    assert digest(request.system_instruction) == LOCAL_REQUEST_INSTRUCTION
    assert request.max_output_tokens == 6144
    assert request.prompt_version_ref == "proposal-design-v11"
    assert "verdict" not in request.output_schema.canonical_schema_json
    for (keys, language), expected in LOCAL_INSTRUCTIONS.items():
        named = None if language is None else {"code": "it", "name": language}
        assert digest(design_instruction(keys, named)) == expected
    assert tuple(design_output_tokens(count) for count in range(1, 9)) == LOCAL_BUDGETS


def test_the_hosted_contract_has_its_own_version_and_purpose():
    request = proposal_request()
    context, _ = design_context(request)
    team = request.team.selected_agent_ids
    marked = hosted_design_context(context, team)
    assert HOSTED_DESIGN_CONTRACT_VERSION == 104
    assert HOSTED_DESIGN_PURPOSE == "DESIGN_ALTERNATIVES_HOSTED"
    assert marked == {
        **context,
        "purpose": HOSTED_DESIGN_PURPOSE,
        "perspectives": perspective_guidance(team, GuidanceStage.DESIGN),
    }
    assert "purpose" not in context
    assert "perspectives" not in context
    assert HOSTED_DESIGN_OUTPUT_TOKENS == 24000


def test_every_hosted_critique_asks_for_a_verdict_and_a_quote():
    schema = HostedDesignDraft.model_json_schema()
    critique = schema["$defs"]["HostedCritiqueDraft"]
    assert "CritiqueDraft" not in schema["$defs"]
    assert schema["properties"]["critiques"]["items"]["$ref"] == "#/$defs/HostedCritiqueDraft"
    assert {"verdict", "quote"} <= set(critique["required"])
    assert (
        critique["properties"]["verdict"]["minLength"],
        critique["properties"]["verdict"]["maxLength"],
    ) == (1, 60)
    assert (
        critique["properties"]["quote"]["minLength"],
        critique["properties"]["quote"]["maxLength"],
    ) == (1, 240)
    wire = json.loads(canonical_json(schema))["$defs"]["HostedCritiqueDraft"]["properties"]
    assert list(wire)[-1] == "verdict"
    assert list(wire).index("quote") == list(wire).index("questions") + 1


@pytest.mark.parametrize("count", [2, 3, 5, 8])
def test_the_hosted_schema_keeps_the_positions_and_the_list_limits_of_two_twins(count):
    request = proposal_request()
    context = hosted_design_context(design_context(request)[0], request.team.selected_agent_ids)
    template = next(iter(context["twins"].values()))
    context["twins"] = {f"T{index}": template for index in range(1, count + 1)}
    schema = HostedDesignDraft.model_json_schema()
    constrain_planning_schema(schema, context, "design")
    critique = schema["$defs"]["HostedCritiqueDraft"]["properties"]
    assert all("maxItems" not in critique[name] for name in CRITIQUE_LISTS)
    branches = schema["properties"]["critiques"]["prefixItems"]
    assert len(branches) == 2 * count
    assert {item["allOf"][0]["$ref"] for item in branches} == {"#/$defs/HostedCritiqueDraft"}
    assert [item["allOf"][1]["properties"]["code"]["const"] for item in branches] == [
        f"CRQ-{index:03d}" for index in range(1, 2 * count + 1)
    ]
    fits = schema["$defs"]["VisualLanguageDraft"]["properties"]["twin_fit"]["prefixItems"]
    assert len(fits) == count
    local = DesignDraft.model_json_schema()
    constrain_planning_schema(
        local, {key: value for key, value in context.items() if key != "purpose"}, "design"
    )
    limits = {
        local["$defs"]["CritiqueDraft"]["properties"][name].get("maxItems")
        for name in CRITIQUE_LISTS
    }
    assert limits == {None if count <= 2 else (2 if count <= 4 else 1)}


def test_a_hosted_provider_loses_the_positions_so_the_instruction_states_them():
    context = hosted_design_context(
        three_twin_context(), proposal_request().team.selected_agent_ids
    )
    schema = HostedDesignDraft.model_json_schema()
    constrain_planning_schema(schema, context, "design")
    hosted = json.dumps(hosted_output_schema(schema, ANTHROPIC))
    assert "prefixItems" not in hosted
    assert "CRQ-001" not in hosted and "SCRIPT" in hosted
    instruction = hosted_design_instruction(context)
    assert "CRQ-006 judges DES-002 as T3" in instruction


def test_the_hosted_instruction_names_the_actual_values_of_every_rule_with_three_twins():
    context = three_twin_context()
    instruction = hosted_design_instruction(context)
    assert instruction.startswith(
        design_instruction("T1/T2/T3", context["language"]).split("Keep the lists")[0]
    )
    assert CRITIQUE_LIST_INSTRUCTIONS[None] in instruction
    assert CRITIQUE_LIST_INSTRUCTIONS[2] not in instruction
    assert "written in Italian, specific to what the twin would experience" in instruction
    assert "'Utile, con riserve', 'Troppo complessa per un turno', 'Non la usa direttamente'" in (
        instruction
    )
    assert "never a generic label repeated for every twin" in instruction
    assert "without quotation marks" in instruction
    assert HOSTED_SCHEMA_INSTRUCTION in instruction
    assert "alternatives has exactly 2 items, in this order: DES-001, DES-002." in instruction
    assert (
        "critiques has exactly 6 items, one for each pair of alternative and twin, in the order "
        "of the alternatives and, inside one alternative, in the order of the twins T1, T2, T3: "
        "CRQ-001 judges DES-001 as T1; CRQ-002 judges DES-001 as T2; CRQ-003 judges DES-001 as "
        "T3; CRQ-004 judges DES-002 as T1; CRQ-005 judges DES-002 as T2; CRQ-006 judges DES-002 "
        "as T3."
    ) in instruction
    assert (
        "The observation_keys of a critique name only observations of its twin: T1 cites only "
        "user_twin.goals, user_twin.context_of_use; T2 cites only user_twin.information_needs; "
        "T3 cites only user_twin.frustrations, user_twin.accessibility_needs."
    ) in instruction
    assert (
        "The twin_fit of every alternative has exactly 3 statements, one per twin, in the order "
        "T1, T2, T3."
    ) in instruction
    assert (
        "In visual, DES-001 chooses hue_family among COBALT, TEAL, FOREST, OCHRE, ROSE; "
        "heading_family among HUMANIST_SANS, SLAB_SERIF, GEOMETRIC_SANS; body_family among "
        "SYSTEM_UI, OLD_STYLE_SERIF; color_scheme among ANALOGOUS, MONOCHROME; background among "
        "PLAIN, TINTED; corners among SOFT, ROUND; header among COMPACT_BAR, MINIMAL."
    ) in instruction
    assert (
        "In visual, DES-002 chooses hue_family among CORAL, VIOLET, SLATE, AMBER, OCEAN; "
        "heading_family among SCRIPT, MONOSPACE, NARROW_SANS;"
    ) in instruction
    assert "color_mode among DARK, HIGH_CONTRAST_LIGHT, HIGH_CONTRAST_DARK." in instruction
    tones = ", ".join(tone.value for tone in DesignTone if tone in SCRIPT_TONES)
    assert (
        f"DES-002 may choose heading_family SCRIPT only with tone among {tones}, heading_case "
        "SENTENCE and color_mode among DARK."
    ) in instruction
    assert "DES-001 may choose heading_family SCRIPT" not in instruction
    unknown = hosted_design_instruction({**context, "language": None, "visual_exploration": {}})
    assert "written in the language of the requirements" in unknown
    assert "In visual," not in unknown


def test_binding_passes_the_verdict_and_the_quote_to_every_critique(unrestricted):
    request = proposal_request()
    context, _ = design_context(request)
    quote = "Come {twin} vedo lo stato del giorno senza aprire altre schermate."
    keyed = (VERDICTS[0], ("Chiara per il turno", quote.format(twin="T2")), *VERDICTS[2:])
    package = bind(request, hosted_draft(draft(context), keyed))
    assert [(item.verdict, item.quote) for item in package.critiques] == [
        VERDICTS[0],
        ("Chiara per il turno", quote.format(twin=NAMES["T2"])),
        *VERDICTS[2:],
    ]
    assert all({"verdict", "quote"} <= set(item.to_snapshot()) for item in package.critiques)
    local = bind(request, draft(context))
    assert all((item.verdict, item.quote) == (None, None) for item in local.critiques)
    assert all({"verdict", "quote"}.isdisjoint(item.to_snapshot()) for item in local.critiques)


def test_a_repeated_verdict_is_accepted_and_an_empty_one_is_not(unrestricted):
    request = proposal_request()
    context, _ = design_context(request)
    repeated = tuple(("Utile, con riserve", quote) for _verdict, quote in VERDICTS)
    package = bind(request, hosted_draft(draft(context), repeated))
    assert {item.verdict for item in package.critiques} == {"Utile, con riserve"}
    for blank in (("   ", VERDICTS[0][1]), (VERDICTS[0][0], "  ")):
        with pytest.raises(ValueError, match="must not be empty"):
            bind(request, hosted_draft(draft(context), (blank, *VERDICTS[1:])))
    unchosen = (("Troppo DASHBOARD per me", VERDICTS[0][1]), *VERDICTS[1:])
    with pytest.raises(ValueError, match="catalog values that were not chosen"):
        bind(request, hosted_draft(draft(context), unchosen))


def test_the_design_adapter_asks_the_design_route_for_the_hosted_draft(unrestricted):
    request = proposal_request()
    context, _ = design_context(request)
    output = hosted_draft(draft(context))
    local = RouteGenerator("local", LOCAL, 8192)
    hosted = RouteGenerator("hosted", ANTHROPIC, 64000, output)
    router = routing(
        {"default": "local", "tasks": {"design": "hosted"}}, local=local, hosted=hosted
    )
    result = asyncio.run(ModelDesignAdapter(router).propose(request))
    [call] = hosted.calls
    assert local.calls == []
    assert call["task"] == "design"
    assert call["output_type"] is HostedDesignDraft
    assert call["context"] == hosted_design_context(context, request.team.selected_agent_ids)
    assert call["max_output_tokens"] == HOSTED_DESIGN_OUTPUT_TOKENS
    assert call["instruction"] == hosted_design_instruction(call["context"])
    assert result.provider_id == hosted.provider_id
    assert [(item.verdict, item.quote) for item in result.package.critiques] == list(VERDICTS)
    assert all(
        any(ref.source_id == hosted.provider_id for ref in item.provenance.references)
        for item in result.package.critiques
    )
    capped = RouteGenerator("hosted", ANTHROPIC, 16000, output)
    asyncio.run(
        ModelDesignAdapter(
            routing({"default": "local", "tasks": {"design": "hosted"}}, local=local, hosted=capped)
        ).propose(request)
    )
    assert capped.calls[0]["max_output_tokens"] == 16000


def test_the_route_of_the_hosted_purpose_serves_the_design_when_it_is_configured(unrestricted):
    request = proposal_request()
    context, _ = design_context(request)
    local = RouteGenerator("local", LOCAL, 8192)
    hosted = RouteGenerator("hosted", ANTHROPIC, 64000)
    special = RouteGenerator("special", ANTHROPIC, 20000, hosted_draft(draft(context)))
    router = routing(
        {
            "default": "local",
            "tasks": {"design": "hosted"},
            "purposes": {HOSTED_DESIGN_PURPOSE: "special"},
        },
        local=local,
        hosted=hosted,
        special=special,
    )
    result = asyncio.run(ModelDesignAdapter(router).propose(request))
    assert hosted.calls == [] and local.calls == []
    assert special.calls[0]["max_output_tokens"] == 20000
    assert result.provider_id == special.provider_id


def test_a_local_design_route_keeps_the_local_draft_when_the_default_is_hosted(unrestricted):
    request = proposal_request()
    context, twins = design_context(request)
    local = RouteGenerator("local", LOCAL, 8192, draft(context))
    hosted = RouteGenerator("hosted", ANTHROPIC, 64000)
    router = routing(
        {"default": "hosted", "tasks": {"design": "local"}}, local=local, hosted=hosted
    )
    result = asyncio.run(ModelDesignAdapter(router).propose(request))
    [call] = local.calls
    assert hosted.calls == []
    assert call["output_type"] is DesignDraft
    assert "purpose" not in call["context"]
    assert call["max_output_tokens"] == design_output_tokens(len(twins))
    assert call["instruction"] == design_instruction("/".join(twins), context["language"])
    assert result.provider_id == local.provider_id
    assert all(item.verdict is None for item in result.package.critiques)


def test_an_empty_verdict_from_a_hosted_model_is_invalid_output(unrestricted):
    request = proposal_request()
    context, _ = design_context(request)
    blank = hosted_draft(draft(context), (("  ", VERDICTS[0][1]), *VERDICTS[1:]))
    hosted = RouteGenerator("hosted", ANTHROPIC, 64000, blank)
    with pytest.raises(ProposalGenerationError) as failure:
        asyncio.run(ModelDesignAdapter(hosted).propose(request))
    assert failure.value.code == "INVALID_PROVIDER_OUTPUT"


def test_every_adapter_names_the_provider_of_the_route_that_serves_it():
    general = RouteGenerator("general", LOCAL, 8192)
    team = RouteGenerator(
        "team", ANTHROPIC, 32000, {"rationale": "A compact team fits.", "suggestions": []}
    )
    router = routing({"default": "general", "tasks": {"team": "team"}}, general=general, team=team)
    result = asyncio.run(ModelTeamProposalAdapter(router).propose(team_fixtures.build_request()))
    assert result.proposal.provider_id == team.provider_id
    assert general.calls == []

    requirements_request = requirements_fixtures.proposal_request()
    expected = asyncio.run(
        requirements_fixtures.FakeDeterministicRequirementsAdapter().propose(requirements_request)
    ).specification
    analyst = RouteGenerator(
        "analyst",
        ANTHROPIC,
        32000,
        proposal_draft("requirements", expected, requirements_request),
    )
    router = routing(
        {"default": "general", "tasks": {"requirements": "analyst"}},
        general=general,
        analyst=analyst,
    )
    result = asyncio.run(ModelRequirementsAdapter(router).propose(requirements_request))
    assert result.provider_id == analyst.provider_id

    persona_request, persona_output = persona_input_output()
    people = RouteGenerator("people", ANTHROPIC, 32000, persona_output)
    router = routing(
        {"default": "general", "tasks": {"personas": "people"}}, general=general, people=people
    )
    result = asyncio.run(ModelUserModelingAdapter(router).propose_personas(persona_request))
    assert result.provider_id == people.provider_id
    assert result.proposals[0].profile.observations[-1].provenance.references[-1].source_id == (
        people.provider_id
    )

    twin_request, twin_output = twin_input_output()
    twins = RouteGenerator("twins", ANTHROPIC, 32000, twin_output)
    router = routing(
        {"default": "general", "tasks": {"user-twins": "twins"}}, general=general, twins=twins
    )
    result = asyncio.run(ModelUserModelingAdapter(router).propose_user_twins(twin_request))
    assert result.provider_id == twins.provider_id
    assert general.calls == []


def test_a_hosted_design_answer_out_of_position_fails_the_full_schema(unrestricted):
    request = proposal_request()
    context, _ = design_context(request)
    answer = hosted_draft(draft(context)).model_dump(mode="json")
    critiques = answer["critiques"]
    swapped = {**answer, "critiques": [critiques[1], critiques[0], *critiques[2:]]}
    configuration = providers().hosted_model("design")
    client = FakeAnthropicClient(message(swapped), message(answer))
    generator = ProposalGenerator(
        configuration, build_anthropic_adapter(configuration, client=client, api_key=TEST_KEY)
    )
    result = asyncio.run(ModelDesignAdapter(generator).propose(request))
    assert [(item.verdict, item.quote) for item in result.package.critiques] == list(VERDICTS)
    first, second = client.messages.calls
    allowance = configuration.reasoning_allowance_tokens
    assert first["max_tokens"] == HOSTED_DESIGN_OUTPUT_TOKENS + allowance
    sent = json.dumps(first["output_config"]["format"]["schema"])
    assert "verdict" in sent and "quote" in sent and "CRQ-001" not in sent
    assert "CRQ-001 judges DES-001 as T1; CRQ-002 judges DES-001 as T2" in first["system"]
    content = json.loads(
        first["messages"][0]["content"].removeprefix("<input>\n").split("\n</input>")[0]
    )
    assert content["context"]["purpose"] == HOSTED_DESIGN_PURPOSE
    assert "did not follow output_schema at $.critiques[0]" in second["messages"][0]["content"]
