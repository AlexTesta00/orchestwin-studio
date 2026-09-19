"""Two real-call contracts preserve lineage and fail closed before publication."""

import asyncio
import json
from uuid import uuid4

import pytest

from orchestwin.models.architecture_drafts import ArchitectureDetailsDraft, architecture_context
from orchestwin.models.openai_compatible import OpenAICompatibleTimeoutError
from orchestwin.models.planning_schema import constrain_planning_schema
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.projects.requirements_primitives import snapshot_content_hash

from .test_proposal_evidence import Command, MemoryEvidence, audited_generator, stage_case


@pytest.mark.parametrize("count", [1, 2])
def test_details_use_declared_components_without_self_connections(count):
    request, output, _, _, _ = stage_case("architecture")
    context = {
        **architecture_context(request),
        "structure": {
            "components": [{"code": f"CMP-{n:03d}"} for n in range(1, count + 1)],
            "environments": output["environments"],
        },
    }
    schema = ArchitectureDetailsDraft.model_json_schema()
    constrain_planning_schema(schema, context, "architecture")
    known = [x["code"] for x in context["structure"]["components"]]
    assert (
        schema["$defs"]["TestCaseDraft"]["properties"]["architecture_component_ids"]["items"][
            "enum"
        ]
        == known
    )
    if count == 1:
        assert schema["properties"]["connections"]["maxItems"] == 0
    else:
        for option in schema["$defs"]["ConnectionDraft"]["anyOf"]:
            properties = option["properties"]
            assert (
                properties["source_component_id"]["const"]
                not in properties["target_component_id"]["enum"]
            )


@pytest.mark.parametrize("fail_details", [False, True])
def test_child_evidence_is_bound_to_exact_structure_and_failure_cannot_publish(
    tmp_path, fail_details
):
    request, output, adapter, method, _ = stage_case("architecture")
    generator, transport = audited_generator(tmp_path, output)
    post = transport.post_json
    if fail_details:

        async def fail_second(**kwargs):
            if transport.calls:
                raise OpenAICompatibleTimeoutError("details unavailable")
            return await post(**kwargs)

        transport.post_json = fail_second
    store = MemoryEvidence()
    command = Command(store, lambda: getattr(adapter(generator), method)(request))
    call = command.run(owner_user_id=uuid4(), project_id=uuid4())
    if fail_details:
        with pytest.raises(ProposalGenerationError, match="TIMEOUT"):
            asyncio.run(call)
        assert all(
            "ADAPTER_ACCEPTED" not in [e[0] for e in events] for events in store.events.values()
        )
        assert all(events[-1][1]["status"] == "FAILED" for events in store.events.values())
    else:
        result = asyncio.run(call)
        parent_id, child_id = store.requests
        parent_events = store.events[parent_id]
        structure = json.loads(parent_events[2][1]["success"]["payload_json"])
        context = json.loads(transport.calls[1]["payload"]["messages"][1]["content"])["context"]
        assert context["structure"] == structure
        assert context["architecture_step"]["structure_hash"] == snapshot_content_hash(structure)
        assert context["architecture_step"]["parent_generation_id"] == str(parent_id)
        related = parent_events[3][1]["related_generations"][0]
        assert related["generation_id"] == str(child_id)
        assert related["request_hash"] == store.requests[child_id][0].content_hash
        assert related["package_content_hash"] == result.package.content_hash
        assert store.requests[parent_id][1] == store.requests[child_id][1]
        assert store.events[child_id][-1][1]["status"] == "ARCHITECTURE_DETAILS_GENERATED"
