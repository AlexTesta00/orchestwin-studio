from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa

from orchestwin.projects.persistence.research_evidence import (
    CHANGES,
    SqlAlchemyResearchEvidenceRepository,
)
from orchestwin.projects.research_evidence import (
    EvidenceChange,
    EvidenceEffect,
    EvidenceVersion,
    ResearchEvidenceError,
)
from orchestwin.projects.twin_learning import KeptObservation, TwinUpdate
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
    ObservationValue,
    ObservationValueKind,
    ProfileObservation,
)
from orchestwin.twins.lifecycle import (
    UserTwinOwnerApprovalStatus,
    assess_empirical_grounding,
    promote_user_twin_lifecycle,
)
from orchestwin.twins.persistence.repositories import (
    SqlAlchemyUserModelingSnapshotRepository,
    SqlAlchemyUserTwinVersionRepository,
    VersionAppendStatus,
)
from orchestwin.twins.persistence.snapshots import _profile_observation_from_snapshot
from orchestwin.twins.user_modeling_gate import (
    user_modeling_artifact_reference,
    user_modeling_gate_is_currently_approved,
)
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinField,
    UserTwinLifecycleStatus,
    UserTwinProfile,
    UserTwinProfileVersion,
)
from orchestwin.workflow.gates import (
    DEFAULT_GATE_ITERATION_LIMIT,
    HumanGateAction,
    HumanGateStatus,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    mark_human_gate_stale,
    next_human_gate_iteration,
    transition_human_gate,
)
from orchestwin.workflow.persistence.repositories import SqlAlchemyHumanGateRepository


def apply_evidence_change(
    current: ProfileObservation | None,
    change: EvidenceChange,
    source: EvidenceVersion,
    *,
    statement: str | None = None,
    rationale: str,
) -> ProfileObservation:
    value = change.value
    if change.effect in (EvidenceEffect.SUPPORTS, EvidenceEffect.CONTRADICTS):
        if current is None or current.value != change.value:
            raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
        value = current.value
    if statement is not None and change.effect is EvidenceEffect.ADDS:
        if value.kind is ObservationValueKind.TEXT:
            value = ObservationValue.from_text(statement)
        else:
            value = ObservationValue.from_items((statement,))
    if (
        change.effect is EvidenceEffect.ADDS
        and current is not None
        and current.value.kind is ObservationValueKind.ITEMS
        and value.kind is ObservationValueKind.ITEMS
    ):
        value = ObservationValue.from_items(dict.fromkeys((*current.value.items, *value.items)))
    citation = change.citation
    reference = EvidenceReference(
        source_kind=source.source_kind,
        source_id=str(source.id),
        source_version=source.version,
        content_hash=source.content_hash,
        locator=f"characters {citation.start}:{citation.end}; lines {citation.start_line}:{citation.end_line}",
        summary=source.title,
    )
    references = () if current is None else current.provenance.references
    provenance = ObservationProvenance.from_references(dict.fromkeys((*references, reference)))
    fully_covered = value.kind is ObservationValueKind.TEXT or all(
        item in citation.quote for item in value.items
    )
    status = (
        EpistemicStatus.CONTESTED
        if change.effect is EvidenceEffect.CONTRADICTS
        else EpistemicStatus.EMPIRICALLY_SUPPORTED
        if source.empirical and fully_covered and statement is None
        else EpistemicStatus.MODEL_INFERRED
    )
    preserved_human_review = (
        current is not None
        and current.epistemic_status is EpistemicStatus.HUMAN_VALIDATED
        and change.effect is EvidenceEffect.SUPPORTS
        and statement is None
        and any(
            item.source_kind is EvidenceSourceKind.HUMAN_REVIEW and item.source_id != str(source.id)
            for item in current.provenance.references
        )
    )
    if current is not None and current.epistemic_status is EpistemicStatus.CONTESTED:
        status = EpistemicStatus.CONTESTED
    elif preserved_human_review:
        status = EpistemicStatus.HUMAN_VALIDATED
    elif (
        current is not None
        and change.effect is EvidenceEffect.SUPPORTS
        and statement is None
        and current.epistemic_status is EpistemicStatus.EMPIRICALLY_SUPPORTED
    ):
        status = EpistemicStatus.EMPIRICALLY_SUPPORTED
    return ProfileObservation(
        observation_key=change.field.observation_key,
        value=value,
        epistemic_status=status,
        confidence=ConfidenceScore(0.5) if current is None else current.confidence,
        provenance=provenance,
        human_validation=current.human_validation
        if preserved_human_review
        else HumanValidationRequirement.REQUIRED,
        rationale=" ".join((statement or rationale).split())
        or (
            "Existing independent human validation retained for the unchanged claim."
            if preserved_human_review
            else "Evidence interpretation approved by the owner; human validation remains required."
        ),
    )


def evidence_profile(
    profile: UserTwinProfile, observations: Iterable[ProfileObservation]
) -> UserTwinProfile:
    replacements = {item.observation_key: item for item in observations}
    all_observations = {item.observation_key: item for item in profile.observations}
    all_observations.update(replacements)
    ordered = tuple(
        all_observations[field.observation_key]
        for field in UserTwinField
        if field.observation_key in all_observations
    )
    updated = replace(
        profile, observations=ordered, validation_status=UserTwinLifecycleStatus.PROJECT_GROUNDED_UT
    )
    assessment = assess_empirical_grounding(updated)
    if assessment.has_empirical_support and not assessment.has_evidence_mismatch:
        updated = promote_user_twin_lifecycle(
            updated,
            target_status=UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT,
            owner_approval=UserTwinOwnerApprovalStatus.APPROVED,
        ).profile
    return updated


def withdrawn_observation(
    current: ProfileObservation, records: Iterable[Mapping[str, object]], *, source_id: UUID
) -> ProfileObservation:
    records = tuple(records)
    remaining = [
        row for row in records if row["retired_at"] is None and row["source_id"] != source_id
    ]
    references = tuple(
        reference
        for reference in current.provenance.references
        if reference.source_id != str(source_id)
    )
    base = next((row["before"] for row in records if row["before"] is not None), None)
    previous = None if base is None else _profile_observation_from_snapshot(base)
    validated = next(
        (
            observation
            for observation in (current, previous)
            if observation is not None
            and observation.value == current.value
            and observation.epistemic_status is EpistemicStatus.HUMAN_VALIDATED
            and any(
                reference.source_kind is EvidenceSourceKind.HUMAN_REVIEW
                and reference.source_id != str(source_id)
                for reference in observation.provenance.references
            )
        ),
        None,
    )
    if not references:
        references = (
            EvidenceReference(
                source_kind=EvidenceSourceKind.OWNER_INPUT,
                source_id="withdrawn-evidence",
                summary="Original supporting evidence was withdrawn.",
            ),
        )
    if any(row["change"]["effect"] == EvidenceEffect.CONTRADICTS.value for row in remaining):
        status = EpistemicStatus.CONTESTED
    elif validated is not None:
        status = EpistemicStatus.HUMAN_VALIDATED
    elif remaining:
        empirical = []
        for row in remaining:
            after = _profile_observation_from_snapshot(row["after"])
            if any(
                reference.source_id == str(row["source_id"])
                and reference.source_kind is EvidenceSourceKind.EMPIRICAL_RESEARCH
                for reference in after.provenance.references
            ) and row["change"].get(
                "empirical_interpretation",
                after.epistemic_status is EpistemicStatus.EMPIRICALLY_SUPPORTED,
            ):
                empirical.append((row, after))
        if current.value.kind is ObservationValueKind.ITEMS:
            covered = all(
                any(
                    item in row["change"]["citation"]["quote"] and item in after.value.items
                    for row, after in empirical
                )
                for item in current.value.items
            )
        else:
            covered = any(
                after.value == current.value
                and EvidenceChange.from_snapshot(row["change"]).value == after.value
                for row, after in empirical
            )
        status = (
            EpistemicStatus.EMPIRICALLY_SUPPORTED if covered else EpistemicStatus.MODEL_INFERRED
        )
    elif (
        previous is not None
        and current.value == previous.value
        and previous.epistemic_status
        in (EpistemicStatus.EMPIRICALLY_SUPPORTED, EpistemicStatus.HUMAN_VALIDATED)
        and any(
            reference.source_kind
            in (EvidenceSourceKind.EMPIRICAL_RESEARCH, EvidenceSourceKind.HUMAN_REVIEW)
            and reference.source_id != str(source_id)
            for reference in previous.provenance.references
        )
    ):
        status = previous.epistemic_status
    else:
        status = EpistemicStatus.UNSUPPORTED_ASSUMPTION
    return replace(
        current,
        epistemic_status=status,
        provenance=ObservationProvenance.from_references(references),
        human_validation=validated.human_validation
        if status is EpistemicStatus.HUMAN_VALIDATED and validated is not None
        else HumanValidationRequirement.REQUIRED,
        rationale="Evidence was withdrawn; remaining independent sources and uncovered claims require review.",
    )


async def current_approved_snapshot(
    session, *, owner_user_id: UUID, project_id: UUID
) -> UserModelingSnapshotVersion:
    snapshot = await SqlAlchemyUserModelingSnapshotRepository(
        session, owner_user_id=owner_user_id
    ).current(project_id=project_id)
    gate = await SqlAlchemyHumanGateRepository(session).get_latest_owned_for_update(
        project_id=project_id, owner_user_id=owner_user_id, gate_type=HumanGateType.USER_MODELING
    )
    if snapshot is None or not user_modeling_gate_is_currently_approved(gate, snapshot):
        raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
    return snapshot


async def append_evidence_profiles(
    session,
    *,
    owner_user_id: UUID,
    current: UserModelingSnapshotVersion,
    profiles: Mapping[UUID, UserTwinProfile],
    occurred_at: datetime,
    approve: bool = True,
) -> UserModelingSnapshotVersion:
    twins = SqlAlchemyUserTwinVersionRepository(session, owner_user_id=owner_user_id)
    updated_twins = []
    for base in current.snapshot.twin_versions:
        profile = profiles.get(base.twin_id)
        if profile is None:
            updated_twins.append(base)
            continue
        version = UserTwinProfileVersion(
            id=uuid4(),
            project_id=current.project_id,
            twin_id=base.twin_id,
            version_number=base.version_number + 1,
            profile=profile,
            content_hash=profile.content_hash,
            created_by_user_id=owner_user_id,
            created_at=occurred_at,
            based_on_version_number=base.version_number,
        )
        if await twins.append(version) is not VersionAppendStatus.APPENDED:
            raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
        updated_twins.append(version)
    snapshot = replace(current.snapshot, twin_versions=tuple(updated_twins))
    version = UserModelingSnapshotVersion(
        id=uuid4(),
        project_id=current.project_id,
        version_number=current.version_number + 1,
        snapshot=snapshot,
        content_hash=snapshot.content_hash,
        created_by_user_id=owner_user_id,
        created_at=occurred_at,
        based_on_version_number=current.version_number,
    )
    if (
        await SqlAlchemyUserModelingSnapshotRepository(session, owner_user_id=owner_user_id).append(
            version
        )
        is not VersionAppendStatus.APPENDED
    ):
        raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
    if not approve:
        return version
    gates = SqlAlchemyHumanGateRepository(session)
    latest = await gates.get_latest_owned_for_update(
        project_id=current.project_id,
        owner_user_id=owner_user_id,
        gate_type=HumanGateType.USER_MODELING,
    )
    artifact = user_modeling_artifact_reference(version)
    if latest is not None and latest.status is not HumanGateStatus.STALE:
        stale = mark_human_gate_stale(
            latest, current_artifact=artifact, occurred_at=occurred_at, event_id=uuid4()
        )
        if stale.status is not HumanGateTransitionStatus.APPLIED or stale.event is None:
            raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
        await gates.save_transition(
            previous_gate=latest, updated_gate=stale.gate, event=stale.event
        )
        latest = stale.gate
    if latest is None:
        iteration, max_iterations = 1, DEFAULT_GATE_ITERATION_LIMIT
    else:
        budget = next_human_gate_iteration(
            latest,
            await gates.list_events_owned(
                project_id=current.project_id, owner_user_id=owner_user_id, gate_id=latest.id
            ),
        )
        if budget is None:
            raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
        iteration, max_iterations = budget
    draft = create_human_gate(
        gate_id=uuid4(),
        project_id=current.project_id,
        owner_user_id=owner_user_id,
        gate_type=HumanGateType.USER_MODELING,
        artifact=artifact,
        iteration=iteration,
        max_iterations=max_iterations,
        created_at=occurred_at,
    )
    submitted = transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=owner_user_id,
        occurred_at=occurred_at,
        event_id=uuid4(),
    )
    if submitted.event is None:
        raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
    await gates.add_with_event(gate=submitted.gate, event=submitted.event)
    approved = transition_human_gate(
        submitted.gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=owner_user_id,
        occurred_at=occurred_at,
        event_id=uuid4(),
    )
    if approved.event is None:
        raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
    await gates.save_transition(
        previous_gate=submitted.gate, updated_gate=approved.gate, event=approved.event
    )
    return version


async def apply_update_changes(
    session,
    *,
    owner_user_id: UUID,
    project_id: UUID,
    update: TwinUpdate,
    kept: Iterable[KeptObservation],
    occurred_at: datetime,
) -> UserModelingSnapshotVersion:
    repository = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=owner_user_id)
    source = await repository.get(
        project_id, update.evidence.source_id, update.evidence.source_version
    )
    if source is None or source.status.value != "ACTIVE":
        raise ResearchEvidenceError("EVIDENCE_RETIRED")
    text = await repository.text(project_id, source.id, source.version)
    if text is None:
        raise ResearchEvidenceError("EVIDENCE_TEXT_UNAVAILABLE")
    if source.content_hash != update.evidence.content_hash:
        raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
    latest = await repository.get(project_id, source.id)
    if latest is None or latest.version != source.version:
        raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
    snapshot = await current_approved_snapshot(
        session, owner_user_id=owner_user_id, project_id=project_id
    )
    twin = next(
        (item for item in snapshot.snapshot.twin_versions if item.twin_id == update.twin_id), None
    )
    if twin is None or twin.version_number != update.base_profile_version:
        raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
    base = await SqlAlchemyUserTwinVersionRepository(session, owner_user_id=owner_user_id).get(
        project_id=project_id, twin_id=update.twin_id, version_number=update.base_profile_version
    )
    if base is None or base.id != twin.id or base.content_hash != twin.content_hash:
        raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
    observations = []
    fields = set()
    for item in kept:
        proposal = update.observations[item.index]
        change = proposal.evidence
        if (
            change is None
            or change.field in fields
            or change.citation.source_id != source.id
            or change.citation.source_version != source.version
            or not change.citation.verify(text)
        ):
            raise ResearchEvidenceError("EVIDENCE_CONTEXT_CHANGED")
        fields.add(change.field)
        before = twin.profile.observation_for(change.field)
        after = apply_evidence_change(
            before, change, source, statement=item.statement, rationale=proposal.basis
        )
        observations.append(after)
        await session.execute(
            sa.insert(CHANGES).values(
                id=uuid4(),
                project_id=project_id,
                owner_user_id=owner_user_id,
                twin_id=twin.twin_id,
                twin_version=twin.version_number + 1,
                update_id=update.id,
                source_id=source.id,
                source_version=source.version,
                field=change.field.value,
                change={
                    **change.to_snapshot(),
                    "empirical_interpretation": source.empirical
                    and item.statement is None
                    and change.effect is not EvidenceEffect.CONTRADICTS,
                },
                before=None if before is None else before.to_snapshot(),
                after=after.to_snapshot(),
            )
        )
    profile = evidence_profile(twin.profile, observations)
    return await append_evidence_profiles(
        session,
        owner_user_id=owner_user_id,
        current=snapshot,
        profiles={twin.twin_id: profile},
        occurred_at=occurred_at,
    )
