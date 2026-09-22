import hashlib
import io
import zipfile
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from orchestwin.api.finalization import (
    CreateFinalExportCommand,
    DecideFinalApprovalCommand,
    FinalizationApiStatus,
    SubmitFinalReviewCommand,
)
from orchestwin.api.finalization_runtime import SqlAlchemyFinalizationApiService
from orchestwin.artifacts.web_source_persistence import (
    SqlAlchemyWebSourceRevisionRepository,
    WebSourceRevisionAppendStatus,
)
from orchestwin.artifacts.web_source_plans import FileSystemWebSourceContentStore
from orchestwin.artifacts.web_sources import (
    WebSourceOrigin,
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
    create_web_source_revision,
)
from orchestwin.persistence import create_database_runtime
from orchestwin.projects.briefs import ProjectBrief
from orchestwin.projects.persistence.briefs import SqlAlchemyProjectBriefRepository
from orchestwin.projects.repository import BriefVersionCreationStatus
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.attempt_persistence import SqlAlchemyWebExecutionAttemptRepository
from orchestwin.web_execution.attempts import WebExecutionAttempt, WebExecutionAttemptTrigger
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.reports import (
    WebExecutionReport,
    WebPhaseResult,
    WebPhaseResultStatus,
)
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebProjectLayout,
)
from orchestwin.workflow.gates import HumanGateAction
from src.test.python.integration.test_model_source_generation_postgres import artifacts, seed
from src.test.python.integration.test_proposal_evidence_postgres import database, run

__all__ = ["database"]

pytestmark = pytest.mark.integration

FILES = (
    ("index.html", b"<!doctype html><html><body><h1>Tip</h1></body></html>", "text/html"),
    (
        "app.js",
        b"function tip(a) { return a * 0.1; }\nmodule.exports = { tip };\n",
        "text/javascript",
    ),
    ("app.test.cjs", b"const test = require('node:test');\n", "text/javascript"),
)


def passed_report(revision):
    now = datetime.now(UTC)
    return WebExecutionReport(
        source_revision_content_hash=revision.content_hash,
        source_tree_hash=revision.source_tree_hash,
        profile_id="web.static",
        profile_version="1.0.0",
        runner_image_digest="c" * 64,
        policy_content_hash="d" * 64,
        phase_results=tuple(
            WebPhaseResult(
                phase=phase,
                status=WebPhaseResultStatus.PASSED,
                command_plan_hashes=(),
                started_at=now,
                completed_at=now,
                exit_codes=(0,),
                stdout_refs=(),
                stderr_refs=(),
                artifact_refs=(),
                findings=(),
                failure_category=None,
                failure_code=None,
                normalized_summary="Phase passed.",
            )
            for phase in WebExecutionPhase
        ),
    )


async def complete_project(runtime, content_root, versions):
    owner, project = await seed(runtime, versions)
    architecture = versions[2]
    now = datetime.now(UTC)
    store = FileSystemWebSourceContentStore(content_root)
    async with runtime.session_factory() as session, session.begin():
        created = await SqlAlchemyProjectBriefRepository(session).create_owned_version(
            project_id=project,
            owner_user_id=owner,
            created_by_user_id=owner,
            brief=ProjectBrief(
                name="Tip calculator",
                problem="Guests need the tip and the total at a glance.",
                goals=("Compute the tip in one step",),
                definition_of_done=("Automated tests pass in the sandbox",),
            ),
        )
        assert created.status is BriefVersionCreationStatus.CREATED
        revision = create_web_source_revision(
            revision_id=uuid4(),
            project_id=project,
            created_by_user_id=owner,
            version_number=1,
            based_on=None,
            target=ExecutionTarget.WEB_STATIC,
            language_configuration=WebLanguageConfiguration(
                frontend=WebImplementationLanguage.STATIC_ASSETS, backend=None
            ),
            layout=WebProjectLayout.SINGLE_ROOT,
            origin=WebSourceOrigin.GENERATED_PLAN,
            files=tuple(
                store.store(normalized_path=path, content=content, media_type=media_type)
                for path, content, media_type in sorted(FILES)
            ),
            provenance_references=(
                WebSourceProvenanceReference(
                    kind=WebSourceProvenanceKind.ARCHITECTURE,
                    reference_id=f"architecture:{architecture.id}",
                    version_number=architecture.version_number,
                    content_hash=architecture.content_hash,
                ),
            ),
            created_at=now,
        )
        appended = await SqlAlchemyWebSourceRevisionRepository(session, owner_user_id=owner).append(
            revision
        )
        assert appended.status is WebSourceRevisionAppendStatus.APPENDED
        attempt = WebExecutionAttempt(
            id=uuid4(),
            project_id=project,
            created_by_user_id=owner,
            attempt_number=1,
            previous_attempt_id=None,
            source_revision=revision.reference,
            profile_validation_content_hash="a" * 64,
            execution_plan_content_hash="b" * 64,
            trigger=WebExecutionAttemptTrigger.INITIAL,
            executed_phases=tuple(WebExecutionPhase),
            report=passed_report(revision),
            started_at=now,
            completed_at=now,
        )
        stored = await SqlAlchemyWebExecutionAttemptRepository(session, owner_user_id=owner).append(
            attempt
        )
        assert stored.status.value == "APPENDED"
    return owner, project


async def finalization_scenario(database, tmp_path, versions):
    runtime = create_database_runtime(database)
    try:
        content_root = tmp_path / "objects"
        owner, project = await complete_project(runtime, content_root, versions)
        service = SqlAlchemyFinalizationApiService(
            runtime.session_factory,
            content_root=content_root,
            export_root=tmp_path / "exports",
        )
        now = datetime.now(UTC)
        reviews = await service.final_reviews(owner_user_id=owner, project_id=project)
        assert len(reviews) == 1
        review = reviews[0]
        assert review["ready_for_gate8"] is True, review["blocking_check_ids"]
        assert review["version_number"] == 1
        assert len(await service.final_reviews(owner_user_id=owner, project_id=project)) == 1
        assert await service.final_reviews(owner_user_id=uuid4(), project_id=project) == ()

        submitted = await service.submit_final_review(
            owner_user_id=owner,
            command=SubmitFinalReviewCommand(
                review_id=UUID(review["review_id"]),
                expected_version=1,
                expected_content_hash=review["content_hash"],
                gate_id=uuid4(),
                event_id=uuid4(),
                occurred_at=now,
            ),
        )
        assert submitted.status is FinalizationApiStatus.APPLIED, submitted.message
        assert submitted.snapshot["status"] == "PENDING_APPROVAL"
        gate_id = UUID(submitted.snapshot["gate_id"])

        stale = await service.submit_final_review(
            owner_user_id=owner,
            command=SubmitFinalReviewCommand(
                review_id=UUID(review["review_id"]),
                expected_version=1,
                expected_content_hash="0" * 64,
                gate_id=uuid4(),
                event_id=uuid4(),
                occurred_at=now,
            ),
        )
        assert stale.status is FinalizationApiStatus.STALE_REVIEW

        decided = await service.decide_final_approval(
            owner_user_id=owner,
            command=DecideFinalApprovalCommand(
                gate_id=gate_id,
                action=HumanGateAction.APPROVE,
                expected_review_id=UUID(review["review_id"]),
                expected_review_version=1,
                expected_review_hash=review["content_hash"],
                event_id=uuid4(),
                occurred_at=now,
                reason=None,
            ),
        )
        assert decided.status is FinalizationApiStatus.APPLIED, decided.message
        assert decided.snapshot["status"] == "APPROVED"
        approval_event_id = UUID(decided.snapshot["approval_event_id"])

        exported = await service.create_export(
            owner_user_id=owner,
            project_id=project,
            command=CreateFinalExportCommand(
                export_id=uuid4(),
                final_review_id=UUID(review["review_id"]),
                expected_review_version=1,
                expected_review_hash=review["content_hash"],
                final_approval_gate_id=gate_id,
                final_approval_event_id=approval_event_id,
                occurred_at=now,
            ),
        )
        assert exported.status is FinalizationApiStatus.CREATED, exported.message
        bundle = exported.snapshot
        categories = {entry["category"] for entry in bundle["manifest"]["entries"]}
        assert categories >= {
            "PROJECT_BRIEF",
            "REQUIREMENTS",
            "DESIGN",
            "ARCHITECTURE",
            "TEST_PLAN",
            "SOURCE",
            "TESTS",
            "EXECUTION_EVIDENCE",
            "HUMAN_DECISIONS",
            "FINAL_REVIEW",
        }

        export_id = UUID(bundle["id"])
        assert (await service.export(owner_user_id=owner, export_id=export_id))["archive_hash"] == (
            bundle["archive_hash"]
        )
        assert await service.export(owner_user_id=uuid4(), export_id=export_id) is None
        download = await service.download_export(owner_user_id=owner, export_id=export_id)
        assert download is not None
        assert hashlib.sha256(download.content).hexdigest() == bundle["archive_hash"]
        names = set(zipfile.ZipFile(io.BytesIO(download.content)).namelist())
        assert {"manifest.json", "sources/index.html", "sources/app.test.cjs"} <= names
        assert "reports/final-review.json" in names

        repeated = await service.create_export(
            owner_user_id=owner,
            project_id=project,
            command=CreateFinalExportCommand(
                export_id=export_id,
                final_review_id=UUID(review["review_id"]),
                expected_review_version=1,
                expected_review_hash=review["content_hash"],
                final_approval_gate_id=gate_id,
                final_approval_event_id=approval_event_id,
                occurred_at=now,
            ),
        )
        assert repeated.status is FinalizationApiStatus.ALREADY_PRESENT
    finally:
        await runtime.dispose()


def test_finalization_service_reviews_gates_and_exports_a_completed_project(database, tmp_path):
    run(finalization_scenario(database, tmp_path, artifacts()))
