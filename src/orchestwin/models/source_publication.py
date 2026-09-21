"""Link accepted model bytes in the existing source/repair transaction."""

from orchestwin.models.proposal_evidence import ProposalEvidenceError, current_proposal_evidence
from orchestwin.models.proposal_evidence_persistence import SqlAlchemyProposalEvidenceBindings


async def bind_source_publication(session, kind, artifact):
    scope = current_proposal_evidence()
    if scope is None or scope.request is None:
        return
    if (
        scope.request.task_id != f"proposal-{kind.lower().replace('_', '-')}-v1"
        or kind not in scope.accepted_hashes
    ):
        raise ProposalEvidenceError("SOURCE_GENERATION_BINDING_REQUIRED")
    owner = artifact.owner_user_id if kind.endswith("REPAIR") else artifact.created_by_user_id
    if artifact.project_id != scope.project_id or owner != scope.owner_user_id:
        raise ProposalEvidenceError("SOURCE_GENERATION_OWNER_MISMATCH")
    await SqlAlchemyProposalEvidenceBindings(session).bind(
        scope,
        [
            {
                "kind": kind,
                "version_id": str(artifact.id),
                "version_number": 1 if kind.endswith("REPAIR") else artifact.version_number,
                "content_hash": artifact.content_hash,
                "relation": "SOURCE_GENERATED" if kind.endswith("SOURCE") else "REPAIR_PROPOSED",
            }
        ],
    )
