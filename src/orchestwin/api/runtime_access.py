from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from orchestwin.api.refusals import refusal
from orchestwin.artifacts.design_gate import design_gate_is_currently_approved
from orchestwin.models.generation_budget import provider_result_cost_microusd
from orchestwin.models.proposal_evidence import ProposalEvidenceError
from orchestwin.projects.requirements_gate import requirements_gate_is_currently_approved

PROJECT_NOT_FOUND: Final = "PROJECT_NOT_FOUND"
REQUIREMENTS_APPROVAL_REQUIRED: Final = "REQUIREMENTS_APPROVAL_REQUIRED"
DESIGN_APPROVAL_REQUIRED: Final = "DESIGN_APPROVAL_REQUIRED"


@dataclass(frozen=True)
class ChangeReference:
    requirements: object | None = None
    design: object | None = None

    @property
    def alternative_code(self) -> str | None:
        if self.design is None:
            return None
        package = self.design.package
        return next(
            (
                item.code
                for item in package.alternatives
                if item.id == package.owner_selected_alternative_id
            ),
            None,
        )

    @property
    def version_numbers(self) -> tuple[int | None, int | None]:
        return (
            None if self.requirements is None else self.requirements.version_number,
            None if self.design is None else self.design.version_number,
        )

    def current_versions(self) -> dict[str, object] | None:
        if self.requirements is None or self.design is None:
            return None
        return {
            "requirements_version_number": self.requirements.version_number,
            "design_version_number": self.design.version_number,
            "alternative_code": self.alternative_code,
        }

    def to_snapshot(self) -> dict[str, object]:
        requirements = self.requirements
        design = self.design
        return {
            "requirements": None
            if requirements is None
            else {
                "version_id": str(requirements.id),
                "version_number": requirements.version_number,
                "content_hash": requirements.content_hash,
            },
            "design": None
            if design is None
            else {
                "version_id": str(design.id),
                "version_number": design.version_number,
                "content_hash": design.content_hash,
                "alternative_code": self.alternative_code,
            },
        }


def database_sessions(runtime):
    database = getattr(runtime, "database_runtime", None)
    if database is None:
        raise refusal(503, "DATABASE_UNAVAILABLE")
    return database.session_factory


def runtime_service(runtime, name: str, code: str):
    service = getattr(runtime, name, None)
    if service is None:
        raise refusal(503, code)
    return service


def proposal_generator(runtime, store):
    real = getattr(runtime, "real_model_runtime", None)
    if real is None or store is None:
        return None
    return real.user_modeling.proposal_port.generator


async def require_project(repository, project_id: UUID) -> None:
    if not await repository.project_exists(project_id):
        raise refusal(404, PROJECT_NOT_FOUND)


async def approved_reference(runtime, owner_user_id: UUID, project_id: UUID) -> ChangeReference:
    scope = {"owner_user_id": owner_user_id, "project_id": project_id}
    requirements = await runtime_service(
        runtime, "requirements_query_service", "REQUIREMENTS_QUERY_UNAVAILABLE"
    ).current(**scope)
    requirements_gate = await runtime_service(
        runtime, "requirements_gate_service", "REQUIREMENTS_GATE_UNAVAILABLE"
    ).current_gate(**scope)
    design = await runtime_service(
        runtime, "design_query_service", "DESIGN_QUERY_UNAVAILABLE"
    ).current(**scope)
    design_gate = await runtime_service(
        runtime, "design_gate_service", "DESIGN_GATE_UNAVAILABLE"
    ).current_gate(**scope)
    return ChangeReference(
        requirements=requirements
        if requirements_gate_is_currently_approved(requirements_gate, requirements)
        else None,
        design=design if design_gate_is_currently_approved(design_gate, design) else None,
    )


async def require_approved(runtime, owner_user_id: UUID, project_id: UUID) -> ChangeReference:
    reference = await approved_reference(runtime, owner_user_id, project_id)
    if reference.requirements is None:
        raise refusal(409, REQUIREMENTS_APPROVAL_REQUIRED)
    if reference.design is None:
        raise refusal(409, DESIGN_APPROVAL_REQUIRED)
    return reference


async def current_brief(runtime, owner_user_id: UUID, project_id: UUID):
    version = await runtime_service(
        runtime, "project_service", "PROJECT_QUERY_UNAVAILABLE"
    ).current_brief(project_id=project_id, owner_user_id=owner_user_id)
    if version is None:
        raise refusal(404, PROJECT_NOT_FOUND)
    return version.brief


async def generation_cost(
    store, owner_user_id: UUID, project_id: UUID, generation_ids: Sequence[UUID]
) -> int:
    reader = getattr(store, "get_owned", None)
    if reader is None:
        return 0
    total = 0
    for generation_id in generation_ids:
        try:
            record = await reader(
                owner_user_id=owner_user_id,
                project_id=project_id,
                generation_id=generation_id,
            )
        except ProposalEvidenceError:
            continue
        if record is None:
            continue
        total += sum(
            provider_result_cost_microusd(item["payload"])
            for item in record["observations"]
            if item.get("kind") == "PROVIDER_RESULT" and isinstance(item.get("payload"), Mapping)
        )
    return total
