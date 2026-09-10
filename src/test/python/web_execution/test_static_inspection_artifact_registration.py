"""Register evaluator inputs only from fully verified browser evidence."""

from __future__ import annotations

import asyncio
import hashlib
from uuid import UUID, uuid4, uuid5

import pytest

from orchestwin.evaluation.artifact_content_registry import (
    InMemoryAuthorizedEvaluationArtifactRegistry,
)
from orchestwin.evaluation.artifacts import EvaluationArtifactKind
from orchestwin.evaluation.static_inspection_artifacts import (
    StaticInspectionArtifactRegistrationError,
    StaticInspectionArtifactRegistrationService,
)
from orchestwin.web_execution.static_browser_jobs import VIEWPORTS
from orchestwin.web_execution.static_inspections import (
    InspectionError,
    InspectionState,
)

from .static_inspection_support import (
    approve,
    prepare,
    setup_service,
)

WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000088001")
OTHER_WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000088002")


def _writer(objects: dict[str, bytes]):
    def write_content(content: bytes) -> str:
        assert isinstance(content, bytes)

        digest = hashlib.sha256(content).hexdigest()
        storage_key = f"sha256/{digest[:2]}/{digest}"

        existing = objects.get(storage_key)

        if existing is not None:
            assert existing == content
        else:
            objects[storage_key] = content

        return storage_key

    return write_content


def _expected_paths(backend) -> tuple[str, ...]:
    paths: list[str] = []

    for scenario in backend.job.scenarios:
        for viewport_name, _, _ in VIEWPORTS:
            prefix = f"{scenario.scenario_id}.{viewport_name}"

            paths.extend(
                (
                    f"{prefix}.html",
                    f"{prefix}.axe.json",
                )
            )

    return tuple(sorted(paths))


def test_completed_verified_inspection_registers_exact_dom_and_axe(
    tmp_path,
) -> None:
    async def scenario() -> None:
        service, store, backend, args = setup_service(tmp_path)

        expected_hash = await approve(
            service,
            backend,
            args,
        )

        result = await service.execute(
            **args,
            expected_hash=expected_hash,
        )

        assert result["state"] == "COMPLETED"

        inspection = store.records[args["request_id"]]

        assert inspection.state is InspectionState.COMPLETED

        objects: dict[str, bytes] = {}

        registry = InMemoryAuthorizedEvaluationArtifactRegistry()

        registrar = StaticInspectionArtifactRegistrationService(
            registry=registry,
            write_content=_writer(objects),
        )

        references = await registrar.register(
            owner_user_id=args["owner_user_id"],
            project_id=args["project_id"],
            workflow_run_id=WORKFLOW_RUN_ID,
            inspection=inspection,
            evidence_directory=(backend.output / inspection.id.hex),
        )

        expected_paths = _expected_paths(backend)

        assert len(references) == len(expected_paths)

        assert references == tuple(
            sorted(
                references,
                key=lambda item: item.sort_key,
            )
        )

        observed_locations = {reference.location for reference in references}

        assert observed_locations == {
            (f"static-inspection:{inspection.id}:{path}") for path in expected_paths
        }

        for path in expected_paths:
            reference = next(
                item
                for item in references
                if item.location == (f"static-inspection:{inspection.id}:{path}")
            )

            assert reference.artifact_id == uuid5(
                inspection.id,
                path,
            )

            assert reference.version_number == 1

            if path.endswith(".axe.json"):
                assert reference.kind is EvaluationArtifactKind.AXE_REPORT
                assert reference.media_type == "application/json"
            else:
                assert reference.kind is EvaluationArtifactKind.DOM_SNAPSHOT
                assert reference.media_type == "text/html"

            stored = objects[reference.storage_key]

            assert len(stored) == reference.size_bytes

            assert hashlib.sha256(stored).hexdigest() == reference.sha256_digest

            assert reference.storage_key == (
                f"sha256/{reference.sha256_digest[:2]}/{reference.sha256_digest}"
            )

            resolved = await registry.resolve_owned(
                owner_user_id=args["owner_user_id"],
                project_id=args["project_id"],
                workflow_run_id=WORKFLOW_RUN_ID,
                artifact_id=reference.artifact_id,
                version_number=1,
            )

            assert resolved == reference

            hidden = await registry.resolve_owned(
                owner_user_id=args["owner_user_id"],
                project_id=args["project_id"],
                workflow_run_id=(OTHER_WORKFLOW_RUN_ID),
                artifact_id=reference.artifact_id,
                version_number=1,
            )

            assert hidden is None

        # Re-harvesting the exact immutable evidence
        # must preserve identities and metadata.
        repeated = await registrar.register(
            owner_user_id=args["owner_user_id"],
            project_id=args["project_id"],
            workflow_run_id=WORKFLOW_RUN_ID,
            inspection=inspection,
            evidence_directory=(backend.output / inspection.id.hex),
        )

        assert repeated == references

    asyncio.run(scenario())


def test_tampered_browser_evidence_is_rejected_before_any_write(
    tmp_path,
) -> None:
    async def scenario() -> None:
        service, store, backend, args = setup_service(tmp_path)

        expected_hash = await approve(
            service,
            backend,
            args,
        )

        await service.execute(
            **args,
            expected_hash=expected_hash,
        )

        inspection = store.records[args["request_id"]]

        evidence_directory = backend.output / inspection.id.hex

        html_path = next(
            path for path in evidence_directory.iterdir() if path.name.endswith(".html")
        )

        html_path.write_bytes(b"<html>tampered-after-execution</html>")

        objects: dict[str, bytes] = {}

        registry = InMemoryAuthorizedEvaluationArtifactRegistry()

        registrar = StaticInspectionArtifactRegistrationService(
            registry=registry,
            write_content=_writer(objects),
        )

        with pytest.raises(InspectionError):
            await registrar.register(
                owner_user_id=args["owner_user_id"],
                project_id=args["project_id"],
                workflow_run_id=WORKFLOW_RUN_ID,
                inspection=inspection,
                evidence_directory=(evidence_directory),
            )

        # Full evidence verification must finish
        # before the first content-addressed write.
        assert objects == {}

    asyncio.run(scenario())


def test_scope_and_terminal_state_fail_before_evidence_read(
    tmp_path,
) -> None:
    async def scenario() -> None:
        service, store, backend, args = setup_service(tmp_path)

        await prepare(
            service,
            backend,
            args,
        )

        inspection = store.records[args["request_id"]]

        assert inspection.state is InspectionState.PENDING

        missing = tmp_path / "must-not-be-read"

        objects: dict[str, bytes] = {}

        registry = InMemoryAuthorizedEvaluationArtifactRegistry()

        registrar = StaticInspectionArtifactRegistrationService(
            registry=registry,
            write_content=_writer(objects),
        )

        with pytest.raises(StaticInspectionArtifactRegistrationError) as wrong_owner:
            await registrar.register(
                owner_user_id=uuid4(),
                project_id=args["project_id"],
                workflow_run_id=WORKFLOW_RUN_ID,
                inspection=inspection,
                evidence_directory=missing,
            )

        assert wrong_owner.value.code == ("STATIC_INSPECTION_ARTIFACT_OWNER_MISMATCH")

        with pytest.raises(StaticInspectionArtifactRegistrationError) as pending:
            await registrar.register(
                owner_user_id=args["owner_user_id"],
                project_id=args["project_id"],
                workflow_run_id=WORKFLOW_RUN_ID,
                inspection=inspection,
                evidence_directory=missing,
            )

        assert pending.value.code == ("STATIC_INSPECTION_ARTIFACTS_REQUIRE_COMPLETED")

        assert objects == {}

    asyncio.run(scenario())
