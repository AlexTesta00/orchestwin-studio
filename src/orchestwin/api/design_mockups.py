"""Audited visual mockups that do not replace an approved Design Package."""

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.design import DesignPackagePayload
from orchestwin.artifacts.design_packages import DesignExplorationPackage
from orchestwin.identity.domain import UserAccount
from orchestwin.models.design_drafts import requirements_view
from orchestwin.models.design_mockups import MockupDraft, bind_mockup
from orchestwin.models.proposal_evidence import (
    current_proposal_evidence,
    evidence_application,
    retain_adapter_result,
)
from orchestwin.models.proposal_generation import ProposalGenerationError, wire_value


class MockupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    design_version_id: UUID
    design_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    alternative_id: UUID


class MockupStatus(StrEnum):
    GENERATED = "MOCKUP_GENERATED"


@dataclass(frozen=True)
class MockupResult:
    status: MockupStatus
    generation_id: UUID
    design_version_id: UUID
    design_content_hash: str
    package: DesignExplorationPackage


class ModelMockupApplication:
    def __init__(self, runtime):
        self.runtime = runtime
        self._proposal_evidence_store = runtime.proposal_evidence_store

    async def current(self, owner_user_id, project_id):
        if self.runtime.design_query_service is None:
            raise HTTPException(503, detail={"code": "DESIGN_QUERY_UNAVAILABLE"})
        current = await self.runtime.design_query_service.current(
            owner_user_id=owner_user_id,
            project_id=project_id,
        )
        if current is None:
            raise HTTPException(404, detail={"code": "DESIGN_PACKAGE_NOT_FOUND"})
        return current

    @evidence_application
    async def generate(self, *, owner_user_id, project_id, body):
        current = await self.current(owner_user_id, project_id)
        if (current.id, current.content_hash) != (body.design_version_id, body.design_content_hash):
            raise HTTPException(409, detail={"code": "DESIGN_CONTEXT_CHANGED"})
        alternative = next(
            (x for x in current.package.alternatives if x.id == body.alternative_id), None
        )
        if alternative is None:
            raise HTTPException(422, detail={"code": "DESIGN_ALTERNATIVE_NOT_FOUND"})
        real = self.runtime.real_model_runtime
        if real is None or self._proposal_evidence_store is None:
            raise HTTPException(503, detail={"code": "REAL_MOCKUP_MODEL_NOT_CONFIGURED"})
        requirements = await self.runtime.requirements_query_service.current(
            owner_user_id=owner_user_id,
            project_id=project_id,
        )
        reference = current.package.grounding.requirements_reference
        if requirements is None or (requirements.id, requirements.content_hash) != (
            reference.artifact_id,
            reference.content_hash,
        ):
            raise HTTPException(409, detail={"code": "DESIGN_CONTEXT_CHANGED"})
        generator = real.design.proposal_port.generator
        draft = await generator.generate(
            task="design",
            output_type=MockupDraft,
            max_output_tokens=min(4096, generator.configuration.max_output_tokens),
            context={
                "project_id": str(project_id),
                "purpose": "DESIGN_MOCKUP",
                "design_version_id": str(current.id),
                "design_content_hash": current.content_hash,
                "alternative": wire_value(alternative),
                "requirements": requirements_view(requirements),
            },
            instruction=(
                "Act as the UX/UI designer. Produce an actual visual mockup of the selected design "
                "in the requirements' language. Prefer two concise screens with up to eight elements "
                "each: the main task with labeled fields/selects/actions and one representative SUCCESS "
                "state with a return action. Never combine a successful result and an error message "
                "on one screen. SUCCESS screens must contain only success content, no error examples. "
                "Each screen depicts one moment. In the two-screen flow, SCR-001 is DEFAULT with "
                "the task inputs and a forward action to SCR-002; SCR-002 is SUCCESS with one "
                "illustrative result and a return action to SCR-001. Do not add a return action "
                "to the entry screen itself. Do not turn every requirement into visible copy: "
                "validation requirements remain binding for implementation but error examples "
                "must be omitted from this success flow. If an additional error scenario is "
                "needed, put it in a separate reachable screen whose state is ERROR. "
                "Use real interface copy, never a narrative about "
                "a screen. For a calculator show operand fields, operation choice, calculate action, "
                "and an illustrative result. This is a click-through mockup, not executing business "
                "logic; begin example results with 'Esempio:' in Italian or 'Example:' in English. "
                "For example 'Esempio: 5 + 3 = 8'. Screen codes SCR-001, SCR-002 in order. "
                "BUTTON/LINK must have target_screen pointing to an existing screen; all other "
                "elements must set target_screen null. Fields TEXT_INPUT/SELECT need a nonempty "
                "field_name (including the operation SELECT, for example 'operation'), "
                "all others null. Only fields may be required. Only SELECT has nonempty options. "
                "Every element cites supplied requirement codes. Every screen must be reachable "
                "from SCR-001. No HTML, JavaScript, approval or empirical claims."
            ),
        )
        try:
            prototype = bind_mockup(draft, alternative, requirements)
            proposed = replace(
                current.package, owner_selected_alternative_id=alternative.id, prototype=prototype
            )
        except (TypeError, ValueError) as error:
            await retain_adapter_result(error=error)
            raise ProposalGenerationError("INVALID_MOCKUP_OUTPUT") from error
        refreshed = await self.current(owner_user_id, project_id)
        if (refreshed.id, refreshed.content_hash) != (current.id, current.content_hash):
            raise HTTPException(409, detail={"code": "DESIGN_CONTEXT_CHANGED"})
        scope = current_proposal_evidence()
        result = MockupResult(
            status=MockupStatus.GENERATED,
            generation_id=scope.request.request_id,
            design_version_id=current.id,
            design_content_hash=current.content_hash,
            package=proposed,
        )
        await scope.event(
            "ADAPTER_ACCEPTED",
            {
                "result": _payload(result),
                "generated_content_hashes": {"DESIGN": [proposed.content_hash]},
            },
        )
        return result


def _payload(result):
    value = wire_value(result)
    value["package"] = DesignPackagePayload.from_domain(result.package).model_dump(mode="json")
    return value


def create_design_mockup_router():
    router = APIRouter(prefix="/projects/{project_id}/design/mockups", tags=["design"])

    @router.post("")
    async def generate(
        project_id: UUID,
        body: MockupRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        result = await ModelMockupApplication(request.app.state.application_runtime).generate(
            owner_user_id=user.id,
            project_id=project_id,
            body=body,
        )
        return _payload(result)

    @router.get("")
    async def current(
        project_id: UUID,
        alternative_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        application = ModelMockupApplication(request.app.state.application_runtime)
        version = await application.current(user.id, project_id)
        if application._proposal_evidence_store is None:
            return None
        result = await application._proposal_evidence_store.latest_design_mockup(
            owner_user_id=user.id,
            project_id=project_id,
            design_content_hash=version.content_hash,
            alternative_id=alternative_id,
        )
        if result is None:
            return None
        # Revalidate the persisted view before passing it to the trusted renderer.
        result["package"] = DesignPackagePayload.from_domain(
            DesignPackagePayload.model_validate(result["package"]).to_domain()
        ).model_dump(mode="json")
        return result

    return router
