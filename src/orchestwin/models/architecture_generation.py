"""Generate architecture structure, then constrain details to that real output."""

from contextlib import nullcontext

from orchestwin.models.architecture_drafts import (
    ArchitectureDetailsDraft,
    ArchitectureDraft,
    ArchitectureStructureDraft,
    architecture_context,
    bind_architecture,
)
from orchestwin.models.proposal_evidence import (
    ProposalEvidenceError,
    child_proposal_evidence,
    current_proposal_evidence,
)
from orchestwin.projects.requirements_primitives import snapshot_content_hash


async def generate_architecture(generator, request):
    context = architecture_context(request)
    structure = await generator.generate(
        task="architecture",
        context={**context, "architecture_phase": "STRUCTURE"},
        output_type=ArchitectureStructureDraft,
        max_output_tokens=min(2400, generator.configuration.max_output_tokens),
        instruction=(
            "Define a compact architecture structure in the requirements' language, preserving the "
            "approved design and technical constraints. Propose components (CMP-001 codes) and "
            "test environments (ENV-001 codes), with unique codes and supplied REQ references. "
            "Choose only components needed for this application; do not add unneeded servers, "
            "databases or external dependencies. Details and tests follow in a separate step."
        ),
    )
    structure_payload = structure.model_dump(mode="json")
    parent = current_proposal_evidence()
    step = {
        "structure_hash": snapshot_content_hash(structure_payload),
        **(
            {
                "parent_generation_id": str(parent.request.request_id),
                "parent_request_hash": parent.request.content_hash,
            }
            if parent
            else {}
        ),
    }
    with child_proposal_evidence() if parent else nullcontext(None) as child:
        try:
            details = await generator.generate(
                task="architecture",
                context={
                    **context,
                    "architecture_phase": "DETAILS",
                    "structure": structure_payload,
                    "architecture_step": step,
                },
                output_type=ArchitectureDetailsDraft,
                instruction=(
                    "Complete the supplied model-proposed structure in the requirements' language. "
                    "Use only its declared CMP component and ENV environment codes. Connections "
                    "link distinct components; with one component use connections=[]. Do not change "
                    "the structure. Use unique CON, ADR, ENT, API, ARK, TST and QGT codes with "
                    "three-digit suffixes. All *_id and *_ids fields reference codes, never UUIDs. "
                    "Each fixed test slot is an approved coverage obligation: provide its concrete "
                    "procedure and expected results. Include concise decisions, risks and deployment "
                    "details. Tests are plans; never claim executed tests or Level D evidence."
                ),
            )
            draft = ArchitectureDraft.model_validate(
                {**structure.model_dump(), **details.model_dump()}
            )
            package = bind_architecture(draft, request)
            if child:
                await child.event(
                    "ADAPTER_ACCEPTED",
                    {
                        "architecture_step": step,
                        "details": details.model_dump(mode="json"),
                        "package_content_hash": package.content_hash,
                    },
                )
                await child.event(
                    "APPLICATION_RESULT", {"status": "ARCHITECTURE_DETAILS_GENERATED"}
                )
                parent.related_generations.append(
                    {
                        "role": "ARCHITECTURE_DETAILS",
                        "generation_id": str(child.request.request_id),
                        "request_hash": child.request.content_hash,
                        "package_content_hash": package.content_hash,
                    }
                )
            return package
        except BaseException as error:
            if child and not isinstance(error, ProposalEvidenceError):
                if "ADAPTER_ACCEPTED" not in child.observed_events:
                    await child.event(
                        "ADAPTER_REJECTED", {"code": getattr(error, "code", type(error).__name__)}
                    )
                await child.event(
                    "APPLICATION_RESULT",
                    {"status": "FAILED", "code": getattr(error, "code", type(error).__name__)},
                )
            raise
