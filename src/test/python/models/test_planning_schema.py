"""Reference grammars reject fabricated links before model output is accepted."""

import re

from orchestwin.models.architecture_drafts import ArchitectureDraft, architecture_context
from orchestwin.models.design_drafts import DesignDraft, design_context
from orchestwin.models.planning_schema import constrain_planning_schema
from orchestwin.models.requirements_drafts import RequirementsDraft, requirements_context

from . import test_fake_architecture as architecture_fixtures
from . import test_fake_design as design_fixtures
from .test_fake_requirements import proposal_request


def test_requirements_sources_are_exact_project_keys_and_links_are_codes():
    context, sources, twins = requirements_context(proposal_request())
    schema = RequirementsDraft.model_json_schema()
    constrain_planning_schema(schema, context, "requirements")
    fields = schema["$defs"]["RequirementDraft"]["properties"]
    assert fields["sources"]["items"]["enum"] == list(sources)
    assert "Invented source text" not in fields["sources"]["items"]["enum"]
    assert fields["twins"]["items"]["enum"] == list(twins)
    criteria = schema["$defs"]["CriterionDraft"]["properties"]
    pattern = criteria["requirements"]["items"]["pattern"]
    assert re.fullmatch(pattern, "REQ-001")
    assert not re.fullmatch(pattern, "USR-001")


def test_design_can_reference_only_approved_requirement_codes():
    context, _ = design_context(design_fixtures.proposal_request())
    schema = DesignDraft.model_json_schema()
    constrain_planning_schema(schema, context, "design")
    field = schema["$defs"]["AlternativeDraft"]["properties"]["requirements"]["items"]
    assert field["enum"] == [x["code"] for x in context["requirements"]["requirements"]]
    assert "REQ-999" not in field["enum"]
    branches = schema["properties"]["critiques"]["prefixItems"]
    assert len(branches) == 2 * len(context["twins"])
    pairs = set()
    for branch in branches:
        fields = branch["allOf"][1]["properties"]
        pairs.add((fields["alternative"]["const"], fields["twin"]["const"]))
        twin = fields["twin"]["const"]
        assert fields["observation_keys"]["items"]["enum"] == list(
            context["twins"][twin]["observations"]
        )

    assert pairs == {(alt, twin) for alt in ("DES-001", "DES-002") for twin in context["twins"]}


def test_architecture_test_slots_preserve_approved_coverage_links():
    context = architecture_context(architecture_fixtures.proposal_request())
    schema = ArchitectureDraft.model_json_schema()
    constrain_planning_schema(schema, context, "architecture")
    slots = [
        item["allOf"][1]["properties"] for item in schema["properties"]["test_cases"]["prefixItems"]
    ]
    for criterion, slot in zip(context["requirements"]["criteria"], slots, strict=False):
        assert slot["acceptance_criterion_ids"]["const"] == [criterion["code"]]
        assert slot["requirement_ids"]["const"] == criterion["requirement_ids"]
    assert {code for slot in slots for code in slot["requirement_ids"]["const"]} == {
        item["code"] for item in context["requirements"]["requirements"]
    }
