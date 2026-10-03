from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import uuid4

from orchestwin.agents.persistence.repositories import SqlAlchemyTeamProposalVersionRepository
from orchestwin.api.clarification import HumanGateResponse
from orchestwin.artifacts.generated_mockup_document import mockup_document
from orchestwin.artifacts.provided_prototypes import provided_prototype_from_payload
from orchestwin.artifacts.visual_catalog import VisualChoices, resolve_visual_tokens
from orchestwin.artifacts.workflow_inputs_persistence import SqlAlchemyWorkflowInputsRepository
from orchestwin.projects.persistence.briefs import SqlAlchemyProjectBriefRepository
from orchestwin.projects.requirements_persistence import (
    SqlAlchemyRequirementsSpecificationRepository,
)
from orchestwin.twins.persistence.repositories import (
    SqlAlchemyPersonaVersionRepository,
    SqlAlchemyUserModelingSnapshotRepository,
)
from orchestwin.twins.representation import snapshot_matches_archetypes
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGateAction,
    HumanGateStatus,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    mark_human_gate_stale,
    next_human_gate_iteration,
    transition_human_gate,
)
from orchestwin.workflow.persistence.repositories import (
    SqlAlchemyHumanGateRepository,
    gate_record_to_domain,
    latest_owned_gate_statement,
)
from orchestwin.workflow_inputs import (
    PROVIDED_PROTOTYPE_LIMITS,
    WorkflowInputError,
    create_workflow_decision,
    validate_workflow_reference,
)


def reference(version):
    return {
        "artifact_id": str(version.id),
        "version_number": version.version_number,
        "content_hash": version.content_hash,
    }


async def latest_gate(session, *, project_id, owner_user_id, gate_type):
    row = await session.scalar(
        latest_owned_gate_statement(
            project_id=project_id,
            owner_user_id=owner_user_id,
            gate_type=gate_type,
        )
    )
    return None if row is None else gate_record_to_domain(row)


def prototype_artifact(prototype):
    return GateArtifactReference(
        project_id=prototype.project_id,
        gate_type=HumanGateType.DESIGN,
        artifact_id=prototype.id,
        version=prototype.version_number,
        content_hash=prototype.content_hash,
    )


async def current_inputs(session, *, owner_user_id, project_id):
    scope = {"owner_user_id": owner_user_id, "project_id": project_id}
    brief = await SqlAlchemyProjectBriefRepository(session).get_current_owned(**scope)
    team = await SqlAlchemyTeamProposalVersionRepository(session).get_current_owned(**scope)
    twins = await SqlAlchemyUserModelingSnapshotRepository(
        session, owner_user_id=owner_user_id
    ).current(project_id=project_id)
    definition = await SqlAlchemyRequirementsSpecificationRepository(
        session, owner_user_id=owner_user_id
    ).current(project_id=project_id)
    return {"BRIEF": brief, "TEAM": team, "USER_TWINS": twins, "REQUIREMENTS": definition}


async def ready_definition(session, *, owner_user_id, project_id):
    values = await current_inputs(session, owner_user_id=owner_user_id, project_id=project_id)
    for target, kind in (
        ("BRIEF", HumanGateType.PROJECT_BRIEF),
        ("TEAM", HumanGateType.AGENT_TEAM),
        ("USER_TWINS", HumanGateType.USER_MODELING),
        ("REQUIREMENTS", HumanGateType.REQUIREMENTS),
    ):
        version = values[target]
        gate = await latest_gate(
            session, owner_user_id=owner_user_id, project_id=project_id, gate_type=kind
        )
        if (
            version is None
            or gate is None
            or gate.status is not HumanGateStatus.APPROVED
            or (
                gate.artifact.artifact_id != version.id
                or gate.artifact.version != version.version_number
                or gate.artifact.content_hash != version.content_hash
            )
        ):
            raise WorkflowInputError("REQUIREMENTS_APPROVAL_REQUIRED")
    definition = values["REQUIREMENTS"]
    spec = definition.specification
    proposal = values["TEAM"].proposal
    if reference(values["BRIEF"]) != {
        "artifact_id": str(proposal.brief_version_id),
        "version_number": proposal.brief_version_number,
        "content_hash": proposal.brief_content_hash,
    }:
        raise WorkflowInputError("WORKFLOW_CONTEXT_CHANGED")
    snapshot = values["USER_TWINS"].snapshot
    for target, expected in (
        ("BRIEF", snapshot.project_brief_reference),
        ("TEAM", snapshot.agent_team_reference),
    ):
        if reference(values[target]) != {
            "artifact_id": str(expected.artifact_id),
            "version_number": expected.version_number,
            "content_hash": expected.content_hash,
        }:
            raise WorkflowInputError("WORKFLOW_CONTEXT_CHANGED")
    personas = await SqlAlchemyPersonaVersionRepository(
        session, owner_user_id=owner_user_id
    ).list_current(project_id=project_id)
    if not snapshot_matches_archetypes(values["USER_TWINS"], personas):
        raise WorkflowInputError("WORKFLOW_CONTEXT_CHANGED")
    for target, expected in (
        ("BRIEF", spec.project_brief_reference),
        ("TEAM", spec.agent_team_reference),
        ("USER_TWINS", spec.user_modeling_reference),
    ):
        if reference(values[target]) != {
            "artifact_id": str(expected.artifact_id),
            "version_number": expected.version_number,
            "content_hash": expected.content_hash,
        }:
            raise WorkflowInputError("WORKFLOW_CONTEXT_CHANGED")
    twins = values["USER_TWINS"].snapshot
    current_twins = {
        (item.twin_id, item.version_number, item.content_hash) for item in twins.twin_versions
    }
    if any(
        (item.twin_id, item.version_number, item.content_hash) not in current_twins
        for item in spec.user_twin_references
    ):
        raise WorkflowInputError("WORKFLOW_CONTEXT_CHANGED")
    return definition


class SqlAlchemyWorkflowInputsService:
    def __init__(self, session_factory, *, clock=None):
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def records(self, *, owner_user_id, project_id):
        async with self._session_factory() as session:
            repository = SqlAlchemyWorkflowInputsRepository(session, owner_user_id=owner_user_id)
            if not await repository.owned(project_id):
                return None
            return await repository.records(project_id)

    async def declare(self, *, owner_user_id, project_id, request):
        if not isinstance(request, Mapping) or set(request) - {
            "target",
            "action",
            "reason",
            "base_context",
        }:
            raise WorkflowInputError("WORKFLOW_RECORDS_INVALID")
        async with self._session_factory() as session, session.begin():
            repository = SqlAlchemyWorkflowInputsRepository(session, owner_user_id=owner_user_id)
            if not await repository.owned(project_id, lock=True):
                raise WorkflowInputError("PROJECT_NOT_FOUND")
            values = await current_inputs(
                session, owner_user_id=owner_user_id, project_id=project_id
            )
            context = {key: reference(value) for key, value in values.items() if value is not None}
            current_prototype = await repository.current(project_id)
            if current_prototype is not None:
                context["DESIGN"] = reference(current_prototype)
            supplied = request.get("base_context", {})
            if not isinstance(supplied, Mapping):
                raise WorkflowInputError("WORKFLOW_REFERENCE_INVALID")
            for target, item in supplied.items():
                checked = validate_workflow_reference(item)
                checked.pop("kind", None)
                if context.get(target) != checked:
                    raise WorkflowInputError("WORKFLOW_CONTEXT_CHANGED")
            records = await repository.records(project_id)
            record = create_workflow_decision(
                decision_id=uuid4(),
                project_id=project_id,
                sequence=len(records["decisions"]) + 1,
                target=request.get("target"),
                action=request.get("action"),
                reason=request.get("reason"),
                base_context=context,
                recorded_at=self._clock(),
            )
            await repository.append_decision(record)
            return record

    async def current(self, *, owner_user_id, project_id):
        async with self._session_factory() as session:
            repository = SqlAlchemyWorkflowInputsRepository(session, owner_user_id=owner_user_id)
            if not await repository.owned(project_id):
                raise WorkflowInputError("PROJECT_NOT_FOUND")
            version = await repository.current(project_id)
            return None if version is None else version.to_snapshot()

    async def save_prototype(self, *, owner_user_id, project_id, request):
        if not isinstance(request, Mapping):
            raise WorkflowInputError("PROVIDED_PROTOTYPE_INPUT_INVALID")
        async with self._session_factory() as session, session.begin():
            repository = SqlAlchemyWorkflowInputsRepository(session, owner_user_id=owner_user_id)
            if not await repository.owned(project_id, lock=True):
                raise WorkflowInputError("PROJECT_NOT_FOUND")
            definition = await ready_definition(
                session, owner_user_id=owner_user_id, project_id=project_id
            )
            expected = validate_workflow_reference(request.get("expected_definition_reference"))
            expected.pop("kind", None)
            if reference(definition) != expected:
                raise WorkflowInputError("WORKFLOW_CONTEXT_CHANGED")
            previous = await repository.current(project_id)
            number = request.get("expected_version_number")
            if type(number) is not int or number != (
                0 if previous is None else previous.version_number
            ):
                raise WorkflowInputError("PROVIDED_PROTOTYPE_VERSION_CONFLICT")
            payload = {
                key: value
                for key, value in request.items()
                if key not in {"expected_definition_reference", "expected_version_number"}
            }
            prototype = provided_prototype_from_payload(
                payload,
                prototype_id=uuid4() if previous is None else previous.id,
                code="PRT-001" if previous is None else previous.code,
                project_id=project_id,
                version_number=number + 1,
                based_on_version_number=None if previous is None else number,
                definition_reference=reference(definition),
                requirement_ids_by_code={
                    item.code: item.id for item in definition.specification.requirements
                },
                created_at=self._clock(),
            )
            await repository.append_prototype(prototype)
            gates = SqlAlchemyHumanGateRepository(session)
            gate = await gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.DESIGN,
            )
            if gate is not None:
                result = mark_human_gate_stale(
                    gate, current_artifact=prototype_artifact(prototype), occurred_at=self._clock()
                )
                if result.status is HumanGateTransitionStatus.APPLIED:
                    await gates.save_transition(
                        previous_gate=gate, updated_gate=result.gate, event=result.event
                    )
            return prototype.to_snapshot()

    async def state(self, *, owner_user_id, project_id):
        async with self._session_factory() as session:
            repository = SqlAlchemyWorkflowInputsRepository(session, owner_user_id=owner_user_id)
            if not await repository.owned(project_id):
                raise WorkflowInputError("PROJECT_NOT_FOUND")
            prototype = await repository.current(project_id)
            gate = await latest_gate(
                session,
                owner_user_id=owner_user_id,
                project_id=project_id,
                gate_type=HumanGateType.DESIGN,
            )
            exact = (
                prototype is not None
                and gate is not None
                and gate.artifact == prototype_artifact(prototype)
            )
            context_current = False
            if prototype is not None:
                try:
                    definition = await ready_definition(
                        session, owner_user_id=owner_user_id, project_id=project_id
                    )
                    context_current = dict(prototype.definition_reference) == reference(definition)
                except WorkflowInputError:
                    pass
            return {
                "source": "PROVIDED_PROTOTYPE"
                if prototype is not None
                and (exact or gate is None or gate.status is HumanGateStatus.STALE)
                else "EXPLORATION"
                if gate is not None
                else "NONE",
                "prototype": None if prototype is None else prototype.to_snapshot(),
                "gate": None
                if gate is None
                else HumanGateResponse.from_domain(gate).model_dump(mode="json"),
                "context_current": context_current,
                "approved": exact and context_current and gate.status is HumanGateStatus.APPROVED,
                "limits": list(PROVIDED_PROTOTYPE_LIMITS if prototype is not None else ()),
            }

    async def gate_current(self, *, owner_user_id, project_id):
        state = await self.state(owner_user_id=owner_user_id, project_id=project_id)
        return state["gate"] if state["source"] == "PROVIDED_PROTOTYPE" else None

    async def gate_action(self, *, owner_user_id, project_id, action, reason=None):
        async with self._session_factory() as session, session.begin():
            repository = SqlAlchemyWorkflowInputsRepository(session, owner_user_id=owner_user_id)
            if not await repository.owned(project_id, lock=True):
                raise WorkflowInputError("PROJECT_NOT_FOUND")
            prototype = await repository.current(project_id)
            if prototype is None:
                raise WorkflowInputError("PROVIDED_PROTOTYPE_NOT_FOUND")
            definition = await ready_definition(
                session, owner_user_id=owner_user_id, project_id=project_id
            )
            if dict(prototype.definition_reference) != reference(definition):
                raise WorkflowInputError("WORKFLOW_CONTEXT_CHANGED")
            try:
                action = HumanGateAction(action)
            except (TypeError, ValueError):
                raise WorkflowInputError("INVALID_TRANSITION") from None
            if reason is not None and not isinstance(reason, str):
                raise WorkflowInputError("WORKFLOW_REASON_INVALID")
            if action not in {
                HumanGateAction.SUBMIT,
                HumanGateAction.APPROVE,
                HumanGateAction.REJECT,
                HumanGateAction.REQUEST_REVISION,
            }:
                raise WorkflowInputError("INVALID_TRANSITION")
            gates = SqlAlchemyHumanGateRepository(session)
            previous = await gates.get_latest_owned_for_update(
                owner_user_id=owner_user_id,
                project_id=project_id,
                gate_type=HumanGateType.DESIGN,
            )
            artifact = prototype_artifact(prototype)
            if action is HumanGateAction.SUBMIT:
                if (
                    previous is not None
                    and previous.artifact == artifact
                    and previous.status
                    in {HumanGateStatus.PENDING_APPROVAL, HumanGateStatus.APPROVED}
                ):
                    return HumanGateResponse.from_domain(previous).model_dump(mode="json")
                iteration = (
                    (1, 3)
                    if previous is None
                    else next_human_gate_iteration(
                        previous,
                        await gates.list_events_owned(
                            project_id=project_id, owner_user_id=owner_user_id, gate_id=previous.id
                        ),
                    )
                )
                if iteration is None:
                    raise WorkflowInputError("GATE_ITERATION_LIMIT")
                gate = create_human_gate(
                    project_id=project_id,
                    owner_user_id=owner_user_id,
                    gate_type=HumanGateType.DESIGN,
                    artifact=artifact,
                    iteration=iteration[0],
                    max_iterations=iteration[1],
                    created_at=self._clock(),
                )
            else:
                if previous is None or previous.artifact != artifact:
                    raise WorkflowInputError("WORKFLOW_CONTEXT_CHANGED")
                gate = previous
            result = transition_human_gate(
                gate,
                action=action,
                actor_user_id=owner_user_id,
                reason=reason,
                occurred_at=self._clock(),
            )
            if result.status is not HumanGateTransitionStatus.APPLIED:
                raise WorkflowInputError(
                    result.issue.value if result.issue else "INVALID_TRANSITION"
                )
            if action is HumanGateAction.SUBMIT:
                await gates.add_with_event(gate=result.gate, event=result.event)
            else:
                await gates.save_transition(
                    previous_gate=gate, updated_gate=result.gate, event=result.event
                )
            return HumanGateResponse.from_domain(result.gate).model_dump(mode="json")

    async def document(
        self, *, owner_user_id, project_id, prototype_id, entry_screen=None, language="it"
    ):
        async with self._session_factory() as session:
            repository = SqlAlchemyWorkflowInputsRepository(session, owner_user_id=owner_user_id)
            if not await repository.owned(project_id):
                raise WorkflowInputError("PROJECT_NOT_FOUND")
            record = await repository.current(project_id)
            if record is None or record.id != prototype_id:
                raise WorkflowInputError("PROVIDED_PROTOTYPE_NOT_FOUND")
            html = mockup_document(
                record.mockup.mockup,
                tokens=resolve_visual_tokens(VisualChoices.from_snapshot(record.visual_choices)),
                language=language,
                entry_screen=entry_screen,
            )
            return {"html": html, "title": record.title}
