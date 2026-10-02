from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import UUID

from orchestwin.artifacts.design_evaluation import (
    create_design_evaluation_run,
    evaluation_bundle,
    evaluation_document,
)
from orchestwin.artifacts.design_finding_validations import (
    FindingDecision,
    create_finding_validation,
)
from orchestwin.evaluation.evaluator import (
    EvaluationUserTwinProfile,
    FakeUserTwinEvaluator,
    UserTwinEvaluationRequest,
)
from orchestwin.evaluation.validation import EvaluationEvidenceKind, EvaluationEvidenceReference
from orchestwin.knowledge.sources import knowledge_feedback
from src.test.python.artifacts.test_design_evaluation import CONFIGURATION, template
from src.test.python.knowledge.knowledge_fixtures import PUBLISHED_AT, real_sources


def current_feedback_sources(*, claim_reference=False):
    sources = real_sources()
    twin = sources.modeling.snapshot.twin_versions[0]
    version = sources.design
    run_id = UUID("10000000-0000-4000-8000-000000000901")
    document = evaluation_document(version)
    bundle = evaluation_bundle(version, document, locale="it-IT", created_at=PUBLISHED_AT)
    evaluator = FakeUserTwinEvaluator(
        configuration=CONFIGURATION,
        summaries_by_twin={twin.twin_id: "Synthetic review."},
        templates_by_twin={
            twin.twin_id: (
                replace(
                    template("UTF-001", "SCR-001", "Synthetic label needs verification."),
                    evidence_refs=(
                        f"user-twin:{twin.twin_id}:v{twin.version_number}#user_twin.goals",
                    )
                    if claim_reference
                    else (),
                ),
            )
        },
        clock=lambda: PUBLISHED_AT,
    )
    request = UserTwinEvaluationRequest(
        evaluation_run_id=run_id,
        project_id=version.project_id,
        workflow_run_id=version.id,
        artifact_bundle=bundle,
        twin=EvaluationUserTwinProfile.from_version(twin),
        evidence=(
            EvaluationEvidenceReference(
                reference_id=f"user-twin:{twin.twin_id}:v{twin.version_number}#user_twin.goals",
                kind=EvaluationEvidenceKind.USER_TWIN_PROFILE,
                content_hash=twin.content_hash,
                locator="user_twin.goals",
            ),
        )
        if claim_reference
        else (),
        requested_at=PUBLISHED_AT,
    )
    response = asyncio.run(evaluator.evaluate(request))
    run = create_design_evaluation_run(
        run_id=run_id,
        owner_user_id=version.created_by_user_id,
        version=version,
        bundle=bundle,
        responses=(response,),
        started_at=PUBLISHED_AT,
        completed_at=PUBLISHED_AT,
    )
    decision = create_finding_validation(
        evaluation_run_id=run_id,
        twin_id=twin.twin_id,
        finding_id="UTF-001",
        sequence_number=1,
        project_id=version.project_id,
        owner_user_id=version.created_by_user_id,
        decision=FindingDecision.OWNER_CONFIRMED,
        note="Synthetic owner review only.",
        decided_at=PUBLISHED_AT,
    )
    return replace(sources, feedback=knowledge_feedback(runs=(run,), validations=(decision,)))
