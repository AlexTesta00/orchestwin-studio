from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from orchestwin.models.generation_routing import RoutingProposalGenerator
from orchestwin.models.hosted_configuration import ModelRoutes
from orchestwin.models.proposal_generation import ProposalGenerator
from src.test.python.models.test_hosted_support import providers

ROUTES = ModelRoutes(
    default="general",
    tasks={"design": "design", "user-twin-evaluation": "review"},
    purposes={"DESIGN_MOCKUP": "mockups", "TWIN_CHAT": "general"},
)


class NamedGenerator:
    def __init__(self, name):
        self.name = name
        self.configuration = SimpleNamespace(name=name, max_output_tokens=1000)
        self.provider_id = f"model-proposals-{name}"
        self.port = SimpleNamespace(name=name)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.name


def routing():
    generators = {name: NamedGenerator(name) for name in ("general", "design", "review", "mockups")}
    return RoutingProposalGenerator(generators, ROUTES), generators


@pytest.mark.parametrize(
    "task,purpose,expected",
    [
        ("design", "DESIGN_MOCKUP", "mockups"),
        ("requirements", "DESIGN_MOCKUP", "mockups"),
        ("design", None, "design"),
        ("design", "UNKNOWN_PURPOSE", "design"),
        ("user-twin-evaluation", "DESIGN_TWIN_REVIEW", "review"),
        ("twin-chat", "TWIN_CHAT", "general"),
        ("requirements", None, "general"),
        ("team", None, "general"),
    ],
)
def test_routes_resolve_purpose_then_task_then_default(task, purpose, expected):
    router, generators = routing()
    assert ROUTES.resolve(task, purpose) == expected
    assert router.route(task, purpose) is generators[expected]


def test_generation_reads_the_purpose_from_a_mapping_context():
    router, generators = routing()
    context = {"project_id": "p", "purpose": "DESIGN_MOCKUP"}
    assert (
        asyncio.run(router.generate(task="design", context=context, instruction="x")) == "mockups"
    )
    assert generators["mockups"].calls == [
        {"task": "design", "context": context, "instruction": "x"}
    ]
    assert asyncio.run(router.generate(task="design", context={"purpose": 7})) == "design"
    request = SimpleNamespace(purpose="DESIGN_MOCKUP")
    assert asyncio.run(router.generate(task="team", context=request)) == "general"


def test_the_public_surface_answers_for_the_default_route():
    router, generators = routing()
    default = generators["general"]
    assert router.configuration is default.configuration
    assert router.provider_id == default.provider_id
    assert router.port is default.port
    assert router.default is default
    assert dict(router.generators) == generators
    assert router.routes is ROUTES
    with pytest.raises(TypeError):
        router.generators["extra"] = default


def test_every_route_needs_a_generator():
    with pytest.raises(ValueError, match="every route requires a generator"):
        RoutingProposalGenerator({"general": NamedGenerator("general")}, ROUTES)


def test_a_single_generator_routes_to_itself(tmp_path):
    from src.test.python.models.test_model_proposals import make_generator

    generator, _ = make_generator(tmp_path, {})
    assert generator.route("design") is generator
    assert generator.route("design", "DESIGN_MOCKUP") is generator
    assert isinstance(generator, ProposalGenerator)


def test_the_configuration_file_drives_the_same_resolution():
    configuration = providers()
    assert configuration.routes.resolve("design", "DESIGN_TWIN_REVIEW") == "review"
    assert configuration.routes.targets() == frozenset({"general", "design", "review"})
