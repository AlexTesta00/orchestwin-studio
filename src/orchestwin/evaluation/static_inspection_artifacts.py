"""Publish evaluator inputs only from fully verified static browser evidence."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid5

from orchestwin.evaluation.artifact_content_registry import (
    ArtifactContentRegistryStoreStatus,
    AuthorizedEvaluationArtifactRecord,
    AuthorizedEvaluationArtifactRegistry,
)
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    EvaluationArtifactReference,
)
from orchestwin.web_execution.static_browser_jobs import VIEWPORTS
from orchestwin.web_execution.static_inspection_backend import (
    verify_inspection_result_with_contents,
)
from orchestwin.web_execution.static_inspections import (
    Inspection,
    InspectionState,
)


class StaticInspectionArtifactRegistrationError(RuntimeError):
    """Stable registration failure without exposing evidence bytes."""

    def __init__(self, code: str) -> None:
        if (
            re.fullmatch(
                r"[A-Z][A-Z0-9_]{0,99}",
                code,
            )
            is None
        ):
            raise ValueError("invalid static inspection artifact error code")

        self.code = code
        super().__init__(code)


class StaticInspectionArtifactRegistrationService:
    """Register exact evaluator-readable outputs from verified evidence."""

    def __init__(
        self,
        *,
        registry: AuthorizedEvaluationArtifactRegistry,
        write_content: Callable[[bytes], str],
    ) -> None:
        self._registry = registry
        self._write_content = write_content

    async def register(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        workflow_run_id: UUID,
        inspection: Inspection,
        evidence_directory: Path,
    ) -> tuple[EvaluationArtifactReference, ...]:
        """Verify everything first, then publish DOM and axe objects."""
        if (
            inspection.plan.job.owner_user_id != owner_user_id
            or inspection.plan.job.project_id != project_id
        ):
            raise StaticInspectionArtifactRegistrationError(
                "STATIC_INSPECTION_ARTIFACT_OWNER_MISMATCH"
            )

        if inspection.state is not InspectionState.COMPLETED:
            raise StaticInspectionArtifactRegistrationError(
                "STATIC_INSPECTION_ARTIFACTS_REQUIRE_COMPLETED"
            )

        # This reads and verifies the complete evidence set before
        # any content-addressed write or registry mutation occurs.
        result, verified_contents = verify_inspection_result_with_contents(
            Path(evidence_directory),
            inspection,
        )

        if result.get("execution_status") != "COMPLETED":
            raise StaticInspectionArtifactRegistrationError(
                "STATIC_INSPECTION_ARTIFACTS_REQUIRE_COMPLETED"
            )

        references = self._build_references(
            inspection=inspection,
            verified_contents=verified_contents,
        )

        # Fail closed on any pre-existing conflicting identity before
        # performing the first byte write.
        for reference in references:
            existing = await self._registry.resolve_owned(
                owner_user_id=owner_user_id,
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                artifact_id=reference.artifact_id,
                version_number=reference.version_number,
            )

            if existing is not None and existing != reference:
                raise StaticInspectionArtifactRegistrationError(
                    "STATIC_INSPECTION_ARTIFACT_METADATA_CONFLICT"
                )

        # All source bytes and registry identities have now passed
        # verification. Publish the exact verified byte objects.
        for reference in references:
            body = verified_contents[
                self._path_from_location(
                    inspection.id,
                    reference.location,
                )
            ]

            observed_key = self._write_content(body)

            if observed_key != reference.storage_key:
                raise StaticInspectionArtifactRegistrationError(
                    "STATIC_INSPECTION_ARTIFACT_STORAGE_MISMATCH"
                )

        # Register metadata only after every verified object has been
        # accepted by the content-addressed writer.
        for reference in references:
            status = await self._registry.append(
                AuthorizedEvaluationArtifactRecord(
                    owner_user_id=owner_user_id,
                    project_id=project_id,
                    workflow_run_id=workflow_run_id,
                    reference=reference,
                )
            )

            if status not in {
                ArtifactContentRegistryStoreStatus.CREATED,
                ArtifactContentRegistryStoreStatus.ALREADY_PRESENT,
            }:
                raise StaticInspectionArtifactRegistrationError(
                    "STATIC_INSPECTION_ARTIFACT_METADATA_CONFLICT"
                )

        return references

    @staticmethod
    def _build_references(
        *,
        inspection: Inspection,
        verified_contents: dict[str, bytes],
    ) -> tuple[EvaluationArtifactReference, ...]:
        references: list[EvaluationArtifactReference] = []

        for scenario in inspection.plan.job.scenarios:
            for viewport_name, _, _ in VIEWPORTS:
                prefix = f"{scenario.scenario_id}.{viewport_name}"

                for path, kind, media_type in (
                    (
                        f"{prefix}.html",
                        EvaluationArtifactKind.DOM_SNAPSHOT,
                        "text/html",
                    ),
                    (
                        f"{prefix}.axe.json",
                        EvaluationArtifactKind.AXE_REPORT,
                        "application/json",
                    ),
                ):
                    body = verified_contents.get(path)

                    if not isinstance(body, bytes) or not body:
                        raise StaticInspectionArtifactRegistrationError(
                            "STATIC_INSPECTION_EVALUATOR_ARTIFACT_MISSING"
                        )

                    digest = hashlib.sha256(body).hexdigest()

                    references.append(
                        EvaluationArtifactReference(
                            artifact_id=uuid5(
                                inspection.id,
                                path,
                            ),
                            version_number=1,
                            kind=kind,
                            media_type=media_type,
                            sha256_digest=digest,
                            size_bytes=len(body),
                            storage_key=(f"sha256/{digest[:2]}/{digest}"),
                            location=(f"static-inspection:{inspection.id}:{path}"),
                        )
                    )

        return tuple(
            sorted(
                references,
                key=lambda item: item.sort_key,
            )
        )

    @staticmethod
    def _path_from_location(
        inspection_id: UUID,
        location: str,
    ) -> str:
        prefix = f"static-inspection:{inspection_id}:"

        if not location.startswith(prefix):
            raise StaticInspectionArtifactRegistrationError(
                "STATIC_INSPECTION_ARTIFACT_LOCATION_INVALID"
            )

        path = location[len(prefix) :]

        if not path:
            raise StaticInspectionArtifactRegistrationError(
                "STATIC_INSPECTION_ARTIFACT_LOCATION_INVALID"
            )

        return path


__all__ = [
    "StaticInspectionArtifactRegistrationError",
    "StaticInspectionArtifactRegistrationService",
]
