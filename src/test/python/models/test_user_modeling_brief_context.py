"""Approved business context is exact; references cannot substitute for content."""

import asyncio
import json
from dataclasses import FrozenInstanceError, replace
from uuid import uuid4

import pytest

from orchestwin.models.model_proposals import ModelUserModelingAdapter
from orchestwin.models.proposal_generation import ProposalGenerationError, wire_value
from orchestwin.models.user_modeling import UserModelingBriefInput
from orchestwin.projects.briefs import BriefField
from src.test.python.models import test_model_proposals as fixtures


def business_version():
    version = fixtures.user_fixtures.brief_version()
    brief = replace(
        version.brief,
        description="Confrontare durate e distanze durante la pianificazione dei turni.",
        problem="Gli operatori devono ripetere calcoli semplici senza errori di trascrizione.",
        goals=("Ridurre la trascrizione manuale dei risultati.",),
        unknown_fields=version.brief.unknown_fields
        - {BriefField.DESCRIPTION, BriefField.PROBLEM, BriefField.GOALS},
    )
    return replace(version, brief=brief, content_hash=brief.content_hash)


def grounded_request(stage):
    version = business_version()
    if stage == "personas":
        return fixtures.persona_input_output(version)
    request, output = fixtures.twin_input_output()
    brief = UserModelingBriefInput.from_version(version)
    return replace(request, project_brief=brief, project_brief_reference=brief.reference), output


@pytest.mark.parametrize("stage", ["personas", "user_twins"])
def test_real_provider_receives_actual_approved_goals_and_description(tmp_path, stage):
    request, output = grounded_request(stage)
    generator, transport = fixtures.make_generator(tmp_path, output)
    result = asyncio.run(getattr(ModelUserModelingAdapter(generator), "propose_" + stage)(request))
    call = transport.calls[0]["payload"]
    context = json.loads(call["messages"][1]["content"])["context"]
    received = context["project_brief"]
    assert set(received) == {"project_id", "reference", "brief"}
    assert received == wire_value(request.project_brief)
    assert received["reference"]["content_hash"] == request.project_brief.brief.content_hash
    assert received["brief"]["description"] == business_version().brief.description
    assert received["brief"]["goals"] == list(business_version().brief.goals)
    assert received["brief"]["unknown_fields"] == sorted(
        field.value for field in business_version().brief.unknown_fields
    )
    assert "created_by_user_id" not in json.dumps(received)
    assert "created_at" not in json.dumps(received)
    task = "personas" if stage == "personas" else "user-twins"
    assert call["metadata"]["orchestwin_prompt_version_ref"] == f"proposal-{task}-v4"
    observations = result.proposals[0].profile.observations
    for observation in observations[1:] if stage == "personas" else observations:
        reference = next(
            item for item in observation.provenance.references if item.locator == "brief"
        )
        assert reference.source_kind.value == "PROJECT_BRIEF"
        assert reference.source_id == str(request.project_brief.reference.artifact_id)
        assert reference.source_version == request.project_brief.reference.version_number
        assert reference.content_hash == request.project_brief.brief.content_hash
        assert observation.epistemic_status.value == "MODEL_INFERRED"
        assert observation.human_validation.value == "REQUIRED"
    if stage == "user_twins":
        assert (
            result.proposals[0].profile.project_brief_reference == request.project_brief.reference
        )
    else:
        # Synthetic completion retains uncertainty despite known project goals:
        # application plumbing never manufactures the model's semantic output.
        assert observations[2].value.kind.value in {"UNKNOWN", "ABSTAINED"}
        assert (
            wire_value(observations[2].value) == output["proposals"][0]["observations"][1]["value"]
        )


@pytest.mark.parametrize("stage", ["personas", "user_twins"])
@pytest.mark.parametrize("change", ["project", "version_id", "version_number", "hash", "content"])
def test_mismatched_approved_brief_is_rejected_at_request_construction(stage, change):
    request, _ = grounded_request(stage)
    brief = request.project_brief
    with pytest.raises(ValueError, match="Project Brief"):
        if change == "project":
            changed = replace(brief, project_id=uuid4())
        elif change == "version_id":
            changed = replace(brief, reference=replace(brief.reference, artifact_id=uuid4()))
        elif change == "version_number":
            changed = replace(brief, reference=replace(brief.reference, version_number=99))
        elif change == "hash":
            changed = replace(brief, reference=replace(brief.reference, content_hash="f" * 64))
        else:
            changed = replace(brief, brief=replace(brief.brief, description="Different content"))
        replace(request, project_brief=changed)


@pytest.mark.parametrize("stage", ["personas", "user_twins"])
@pytest.mark.parametrize("change", ["absent", "project", "version", "content"])
def test_real_adapter_rechecks_context_before_any_model_call(tmp_path, stage, change):
    request, output = grounded_request(stage)
    if change == "absent":
        request = replace(request, project_brief=None)
    elif change == "project":
        object.__setattr__(request, "project_id", uuid4())
    elif change == "version":
        object.__setattr__(
            request.project_brief,
            "reference",
            replace(request.project_brief.reference, version_number=99),
        )
    else:
        object.__setattr__(request.project_brief.brief, "description", "Changed after construction")
    generator, transport = fixtures.make_generator(tmp_path, output)
    with pytest.raises(ProposalGenerationError):
        asyncio.run(getattr(ModelUserModelingAdapter(generator), "propose_" + stage)(request))
    assert transport.calls == []


def test_business_context_and_nested_brief_are_immutable():
    request, _ = grounded_request("personas")
    with pytest.raises(FrozenInstanceError):
        request.project_brief.reference = None
    with pytest.raises(FrozenInstanceError):
        request.project_brief.brief.goals = ("Changed",)
    assert isinstance(request.project_brief.brief.goals, tuple)
    assert isinstance(request.project_brief.brief.unknown_fields, frozenset)
