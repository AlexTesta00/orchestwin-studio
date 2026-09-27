"""Reference grammars reject fabricated links before model output is accepted."""

import re

from orchestwin.models.design_drafts import DesignDraft, design_context
from orchestwin.models.planning_schema import constrain_planning_schema
from orchestwin.models.requirements_drafts import RequirementsDraft, requirements_context

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
    for index, branch in enumerate(branches, 1):
        fields = branch["allOf"][1]["properties"]
        assert sorted(fields) == ["alternative", "as_twin", "code", "observation_keys"]
        assert fields["code"] == {"const": f"CRQ-{index:03d}"}
        pairs.add((fields["alternative"]["const"], fields["as_twin"]["const"]))
        twin = fields["as_twin"]["const"]
        assert fields["observation_keys"]["items"]["enum"] == list(
            context["twins"][twin]["observations"]
        )

    assert pairs == {(alt, twin) for alt in ("DES-001", "DES-002") for twin in context["twins"]}
    critique = schema["$defs"]["CritiqueDraft"]["properties"]
    assert critique["as_twin"]["enum"] == list(context["twins"])
    assert "twin" not in critique
    fits = schema["$defs"]["VisualLanguageDraft"]["properties"]["twin_fit"]["prefixItems"]
    assert [item["allOf"][1]["properties"] for item in fits] == [
        {"twin": {"const": key}} for key in context["twins"]
    ]
