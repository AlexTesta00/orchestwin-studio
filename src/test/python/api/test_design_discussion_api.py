from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from orchestwin.api import design_discussion, design_loop
from orchestwin.api.app import create_app
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.design_discussion import (
    DesignDiscussionApplication,
    DesignDiscussionCommandStatus,
    DesignDiscussionRequest,
    DiscussionAction,
    DiscussionDecisionRequest,
    DiscussionRoundRequest,
)
from orchestwin.api.services import ApplicationRuntime
from orchestwin.artifacts.design_discussion import MAX_DISCUSSION_ROUNDS, DiscussionStatus
from orchestwin.artifacts.design_discussion_persistence import DiscussionWriteStatus
from orchestwin.artifacts.design_evaluation import design_review_view
from orchestwin.artifacts.design_finding_validations import (
    FindingDecision,
    create_finding_validation,
)
from orchestwin.config import ApplicationSettings, LogLevel, RuntimeEnvironment
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.models.proposal_evidence import begin_model_generation
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.projects.requirements_primitives import (
    UserTwinVersionReference,
    canonical_user_twin_references,
)
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
    ObservationValue,
    ProfileObservation,
)
from src.test.python.artifacts import design_fixtures

OWNER_ID = design_fixtures.OWNER_ID
PROJECT_ID = design_fixtures.PROJECT_ID
TWIN_ID = design_fixtures.TWIN_ID
SECOND_TWIN_ID = UUID("00000000-0000-4000-8000-000000000061")
RUN_ID = UUID("00000000-0000-4000-8000-000000000901")
OLDER_RUN_ID = UUID("00000000-0000-4000-8000-000000000902")
NOW = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


class FakeSession:
    def begin(self):
        return FakeTransaction()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


def observed(key, value):
    return ProfileObservation(
        observation_key=key,
        value=value,
        epistemic_status=EpistemicStatus.USER_PROVIDED,
        confidence=ConfidenceScore(0.9),
        provenance=ObservationProvenance.from_references(
            (EvidenceReference(source_kind=EvidenceSourceKind.PROJECT_BRIEF, source_id="brief"),)
        ),
        human_validation=HumanValidationRequirement.NOT_REQUIRED,
    )


OBSERVATIONS = (
    observed("user_twin.role", ObservationValue.from_text("Hotel receptionist")),
    observed("user_twin.goals", ObservationValue.from_items(("Register guests quickly",))),
    observed("user_twin.frustrations", ObservationValue.unknown()),
)


class MemoryTwins:
    references: ClassVar[dict[UUID, UserTwinVersionReference]] = {}
    changed: ClassVar[set[UUID]] = set()

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def get(self, *, project_id, twin_id, version_number):
        reference = MemoryTwins.references.get(twin_id)
        if reference is None:
            return None
        return SimpleNamespace(
            twin_id=twin_id,
            version_number=version_number,
            content_hash="0" * 64 if twin_id in MemoryTwins.changed else reference.content_hash,
            profile=SimpleNamespace(name=reference.name, observations=OBSERVATIONS),
        )


class MemoryRuns:
    runs: ClassVar[list] = []

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def list(self, *, project_id, limit=50):
        return tuple(MemoryRuns.runs)[:limit]


class MemoryValidations:
    items: ClassVar[list] = []

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def current(self, *, project_id):
        return tuple(
            item
            for item in MemoryValidations.items
            if item.project_id == project_id and item.owner_user_id == self.owner_user_id
        )


class MemoryDiscussions:
    items: ClassVar[dict] = {}

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    def _owned(self, project_id, discussion_id):
        item = MemoryDiscussions.items.get(discussion_id)
        if item is None or (item.project_id, item.owner_user_id) != (
            project_id,
            self.owner_user_id,
        ):
            return None
        return item

    async def create(self, discussion):
        if any(
            item.status is DiscussionStatus.OPEN
            and item.design_version_id == discussion.design_version_id
            for item in MemoryDiscussions.items.values()
        ):
            return DiscussionWriteStatus.DISCUSSION_OPEN
        MemoryDiscussions.items[discussion.id] = discussion
        return DiscussionWriteStatus.WRITTEN

    async def append_round(self, *, project_id, discussion_id, round, expected_round_count):
        current = self._owned(project_id, discussion_id)
        if current is None:
            return DiscussionWriteStatus.DISCUSSION_NOT_FOUND
        if current.status is not DiscussionStatus.OPEN:
            return DiscussionWriteStatus.DISCUSSION_CLOSED
        if len(current.rounds) != expected_round_count:
            return DiscussionWriteStatus.DISCUSSION_CHANGED
        if len(current.rounds) >= MAX_DISCUSSION_ROUNDS:
            return DiscussionWriteStatus.DISCUSSION_FULL
        MemoryDiscussions.items[discussion_id] = current.with_round(round)
        return DiscussionWriteStatus.WRITTEN

    async def decide(self, *, project_id, discussion_id, status, decided_at):
        current = self._owned(project_id, discussion_id)
        if current is None:
            return DiscussionWriteStatus.DISCUSSION_NOT_FOUND
        if current.status is not DiscussionStatus.OPEN:
            return DiscussionWriteStatus.DISCUSSION_CLOSED
        MemoryDiscussions.items[discussion_id] = current.decided(status, decided_at)
        return DiscussionWriteStatus.WRITTEN

    async def get(self, *, project_id, discussion_id):
        return self._owned(project_id, discussion_id)

    async def list(self, *, project_id, limit=50):
        owned = [
            item
            for item in MemoryDiscussions.items.values()
            if self._owned(project_id, item.id) is not None
        ]
        return tuple(sorted(owned, key=lambda item: (item.created_at, str(item.id)), reverse=True))[
            :limit
        ]

    async def open_for_version(self, *, project_id, design_version_id):
        return next(
            (
                item
                for item in MemoryDiscussions.items.values()
                if self._owned(project_id, item.id) is not None
                and item.status is DiscussionStatus.OPEN
                and item.design_version_id == design_version_id
            ),
            None,
        )


class MemoryEvidence:
    def __init__(self):
        self.generations = []
        self.events = []

    async def begin(self, *, owner_user_id, project_id, request):
        self.generations.append(request.request_id)

    async def append(self, *, generation_id, kind, payload, **_):
        self.events.append((self.generations.index(generation_id), kind, payload))

    def kinds(self):
        return [(index, kind) for index, kind, _ in self.events]

    def payloads(self, kind):
        return [payload for _, name, payload in self.events if name == kind]


class FakeGenerator:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.configuration = SimpleNamespace(max_output_tokens=8192)

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        await begin_model_generation(SimpleNamespace(request_id=uuid4(), content_hash="d" * 64))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        try:
            return kwargs["output_type"].model_validate_json(json.dumps(outcome))
        except ValidationError as error:
            raise ProposalGenerationError("INVALID_PROVIDER_OUTPUT") from error


class DesignQuery:
    def __init__(self, *versions):
        self.versions = list(versions)

    async def current(self, *, owner_user_id, project_id):
        assert owner_user_id == OWNER_ID
        if len(self.versions) > 1:
            return self.versions.pop(0)
        return self.versions[0]


def two_twin_version(version_number=1):
    package = design_fixtures.design_package()
    second = UserTwinVersionReference(
        twin_id=SECOND_TWIN_ID, version_number=1, content_hash="c" * 64, name="Night Auditor Twin"
    )
    critiques = tuple(
        replace(
            item, id=UUID(int=210 + index), code=f"CRQ-{index + 3:03d}", user_twin_reference=second
        )
        for index, item in enumerate(package.critiques)
    )
    return design_fixtures.design_version(
        version_number=version_number,
        package=replace(
            package,
            grounding=replace(
                package.grounding,
                user_twin_references=canonical_user_twin_references(
                    (*package.grounding.user_twin_references, second), require_items=True
                ),
            ),
            critiques=tuple(sorted((*package.critiques, *critiques), key=lambda item: item.code)),
        ),
    )


def statement(argument, *, replies=(), stance="CONCERN", proposals=("Show the date format.",)):
    return {
        "argument": argument,
        "confidence": 0.7,
        "grounded_on": ["user_twin.goals"],
        "proposals": list(proposals),
        "replies_to": list(replies),
        "stance": stance,
    }


def conflict(first="The form is too long.", second="The form is fine."):
    return {
        "positions": [
            {"position": first, "twin": "T1"},
            {"position": second, "twin": "T2"},
        ],
        "topic": "Length of the form",
    }


def synthesis(keys=("T1", "T2"), **changes):
    return {
        "agreements": ["The reservation flow is clear."],
        "conflicts": [] if len(keys) < 2 else [conflict()],
        "proposals": [
            {"supported_by": list(keys), "target": "DESIGN", "text": "Show the date format."}
        ],
        "questions_for_owner": ["Should expert mode ship first?"],
        **changes,
    }


LONE_POSITION = synthesis(conflicts=[conflict(second=None)])
REPEATED_TWIN = synthesis(
    conflicts=[
        {
            "positions": [
                {"position": "The form is too long.", "twin": "T2"},
                {"position": "The form is fine.", "twin": "T2"},
            ],
            "topic": "Length of the form",
        }
    ]
)
DUPLICATED_PROPOSALS = synthesis(proposals=[synthesis()["proposals"][0]] * 2)


def application(
    monkeypatch,
    *,
    version=None,
    versions=None,
    generator=None,
    evidence=None,
    runs=(),
    validations=(),
):
    current = version if version is not None else design_fixtures.design_version()
    MemoryDiscussions.items = {}
    MemoryRuns.runs = list(runs)
    MemoryValidations.items = list(validations)
    MemoryTwins.references = {
        item.twin_id: item for item in current.package.grounding.user_twin_references
    }
    MemoryTwins.changed = set()
    monkeypatch.setattr(design_loop, "SqlAlchemyDesignEvaluationRepository", MemoryRuns)
    monkeypatch.setattr(design_loop, "SqlAlchemyFindingValidationRepository", MemoryValidations)
    monkeypatch.setattr(design_loop, "SqlAlchemyUserTwinVersionRepository", MemoryTwins)
    monkeypatch.setattr(
        design_discussion, "SqlAlchemyDesignDiscussionRepository", MemoryDiscussions
    )
    runtime = SimpleNamespace(
        database_runtime=SimpleNamespace(session_factory=lambda: FakeSession()),
        design_query_service=DesignQuery(*(versions or (current,))),
        proposal_evidence_store=evidence,
        real_model_runtime=None
        if generator is None
        else SimpleNamespace(
            user_modeling=SimpleNamespace(proposal_port=SimpleNamespace(generator=generator))
        ),
    )
    return DesignDiscussionApplication(runtime), current


def discussing(monkeypatch, *outcomes, version=None, **options):
    generator = FakeGenerator(*outcomes)
    evidence = MemoryEvidence()
    app, current = application(
        monkeypatch, version=version, generator=generator, evidence=evidence, **options
    )
    return app, current, generator, evidence


def start(app, version, **changes):
    body = DesignDiscussionRequest(
        design_version_id=version.id, design_content_hash=version.content_hash, **changes
    )
    return asyncio.run(app.start(owner_user_id=OWNER_ID, project_id=PROJECT_ID, body=body))


def continue_discussion(app, discussion_id, expected, note=None):
    body = DiscussionRoundRequest(expected_round_count=expected, owner_note=note)
    return asyncio.run(
        app.next_round(
            owner_user_id=OWNER_ID, project_id=PROJECT_ID, discussion_id=discussion_id, body=body
        )
    )


def decide(app, discussion_id, action):
    return asyncio.run(
        app.decide(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            discussion_id=discussion_id,
            body=DiscussionDecisionRequest(action=action),
        )
    )


def refused(call):
    with pytest.raises(HTTPException) as failure:
        call()
    return failure.value.status_code, failure.value.detail


def finding(finding_id, twin_id, summary):
    return create_synthetic_finding(
        finding_id=finding_id,
        twin_id=twin_id,
        twin_version=1,
        artifact_id=design_fixtures.PROTOTYPE_ID,
        artifact_version=1,
        location="SCR-001 Create reservation",
        summary=summary,
        rationale="Simulated rationale.",
        criterion=SyntheticFindingCriterion.TRUST,
        severity=SyntheticFindingSeverity.MODERATE,
        epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
        evidence_refs=(f"artifact:{design_fixtures.PROTOTYPE_ID}:v1",),
        confidence=0.6,
        recommended_action="Explain the outcome.",
        requires_human_validation=True,
        model_config_ref="config-1",
        prompt_version_ref="prompt-1",
    )


def test_start_records_one_statement_per_twin_a_synthesis_and_the_evidence(monkeypatch):
    version = two_twin_version()
    app, _, generator, evidence = discussing(
        monkeypatch,
        statement("The guided flow works, but the form is long for me."),
        statement("The form is fine at night.", stance="SUPPORT"),
        synthesis(),
        version=version,
    )
    result = start(app, version, owner_note="  Pensate   ai turni di notte. ")
    discussion = result.discussion
    assert result.status is DesignDiscussionCommandStatus.STARTED
    assert MemoryDiscussions.items == {discussion.id: discussion}
    assert discussion.status is DiscussionStatus.OPEN
    assert (discussion.design_version_id, discussion.design_content_hash) == (
        version.id,
        version.content_hash,
    )
    assert (discussion.alternative_id, discussion.alternative_code) == (
        design_fixtures.ALTERNATIVE_ONE_ID,
        "DES-001",
    )
    assert discussion.locale == "it-IT"
    [opening] = discussion.rounds
    assert opening.ordinal == 1
    assert opening.owner_note == "Pensate ai turni di notte."
    assert [item.twin_id for item in opening.statements] == [TWIN_ID, SECOND_TWIN_ID]
    assert [item.twin_name for item in opening.statements] == [
        "Hotel Receptionist Twin",
        "Night Auditor Twin",
    ]
    assert [item.twin_version for item in opening.statements] == [2, 1]
    assert all(item.replies_to == () for item in opening.statements)
    assert opening.synthesis.conflicts[0].twin_ids == (TWIN_ID, SECOND_TWIN_ID)
    assert opening.synthesis.proposals[0].supported_by == (TWIN_ID, SECOND_TWIN_ID)
    assert [
        *(item.model_generation_id for item in opening.statements),
        opening.synthesis.model_generation_id,
    ] == evidence.generations
    contexts = [call["context"] for call in generator.calls]
    assert [item["purpose"] for item in contexts] == [
        "TWIN_STATEMENT",
        "TWIN_STATEMENT",
        "DISCUSSION_SYNTHESIS",
    ]
    assert [item["speaker"] for item in contexts[:2]] == ["T1", "T2"]
    assert contexts[0]["participants"] == {
        "T1": "Hotel Receptionist Twin",
        "T2": "Night Auditor Twin",
    }
    assert contexts[0]["design"] == design_review_view(version)
    assert contexts[0]["owner_note"] == "Pensate ai turni di notte."
    assert (contexts[0]["round"], contexts[0]["locale"]) == (1, "it-IT")
    assert contexts[0]["previous_round"] is None
    assert contexts[0]["findings"] == []
    assert list(contexts[1]["user_twin"]["observations"]) == ["user_twin.role", "user_twin.goals"]
    assert contexts[2]["statements"][1]["argument"] == "The form is fine at night."
    assert contexts[2]["previous_synthesis"] is None
    assert [call["task"] for call in generator.calls] == ["twin-discussion"] * 3
    assert [call["max_output_tokens"] for call in generator.calls] == [1024, 1024, 2048]
    replies = generator.calls[0]["output_type"].model_json_schema()["properties"]["replies_to"]
    assert replies["maxItems"] == 0
    assert evidence.kinds() == [
        (0, "ADAPTER_ACCEPTED"),
        (0, "APPLICATION_RESULT"),
        (1, "ADAPTER_ACCEPTED"),
        (1, "APPLICATION_RESULT"),
        (2, "ADAPTER_ACCEPTED"),
        (2, "APPLICATION_RESULT"),
    ]
    accepted = evidence.payloads("ADAPTER_ACCEPTED")
    for payload, item in zip(accepted, opening.statements, strict=False):
        assert payload == {
            "result": item.to_snapshot(),
            "generated_content_hashes": {"TWIN_STATEMENT": [item.content_hash]},
        }
    assert accepted[2]["result"] == opening.to_snapshot()
    assert accepted[2]["generated_content_hashes"] == {"DISCUSSION_ROUND": [opening.content_hash]}
    assert [
        (item["role"], item["generation_id"], item["code"])
        for item in accepted[2]["related_generations"]
    ] == [
        ("TWIN_DISCUSSION", str(evidence.generations[0]), "TWIN_STATEMENT_RECORDED"),
        ("TWIN_DISCUSSION", str(evidence.generations[1]), "TWIN_STATEMENT_RECORDED"),
    ]
    assert evidence.payloads("APPLICATION_RESULT") == [
        {"status": "TWIN_STATEMENT_RECORDED", "discussion_id": str(discussion.id)},
        {"status": "TWIN_STATEMENT_RECORDED", "discussion_id": str(discussion.id)},
        {"status": "DESIGN_DISCUSSION_STARTED", "issue": None},
    ]


def test_a_later_round_sees_the_previous_round_keeps_the_locale_and_accepts_replies(
    monkeypatch,
):
    version = two_twin_version()
    app, _, generator, evidence = discussing(
        monkeypatch,
        statement("The form is long."),
        statement("The form is fine."),
        synthesis(),
        statement("I disagree with Night Auditor Twin.", replies=("T2",), proposals=()),
        statement("Hotel Receptionist Twin has a point.", replies=("T1",), stance="OBJECTION"),
        synthesis(),
        version=version,
    )
    opened = start(app, version, locale="en-US").discussion
    result = continue_discussion(app, opened.id, 1, note="  Answer each other. ")
    discussion = result.discussion
    assert result.status is DesignDiscussionCommandStatus.ROUND_RECORDED
    assert MemoryDiscussions.items[opened.id] == discussion
    assert [item.ordinal for item in discussion.rounds] == [1, 2]
    later = discussion.rounds[1]
    assert later.owner_note == "Answer each other."
    assert [item.replies_to for item in later.statements] == [(SECOND_TWIN_ID,), (TWIN_ID,)]
    context = generator.calls[3]["context"]
    assert (context["round"], context["locale"], context["owner_note"]) == (
        2,
        "en-US",
        "Answer each other.",
    )
    assert context["previous_round"]["statements"] == [
        {
            "twin": "T1",
            "stance": "CONCERN",
            "statement": "The form is long.",
            "proposals": ["Show the date format."],
        },
        {
            "twin": "T2",
            "stance": "CONCERN",
            "statement": "The form is fine.",
            "proposals": ["Show the date format."],
        },
    ]
    assert context["previous_round"]["synthesis"]["proposals"] == [
        {
            "code": "PRP-001",
            "text": "Show the date format.",
            "target": "DESIGN",
            "supported_by": ["T1", "T2"],
        }
    ]
    replies = generator.calls[3]["output_type"].model_json_schema()["properties"]["replies_to"]
    assert (replies["items"]["const"], replies["maxItems"]) == ("T2", 1)
    moderated = generator.calls[5]["context"]
    assert moderated["previous_synthesis"] == context["previous_round"]["synthesis"]
    assert moderated["statements"][1]["replies_to"] == ["T1"]
    assert evidence.kinds()[6:] == [
        (3, "ADAPTER_ACCEPTED"),
        (3, "APPLICATION_RESULT"),
        (4, "ADAPTER_ACCEPTED"),
        (4, "APPLICATION_RESULT"),
        (5, "ADAPTER_ACCEPTED"),
        (5, "APPLICATION_RESULT"),
    ]
    assert evidence.payloads("APPLICATION_RESULT")[-1] == {
        "status": "DESIGN_DISCUSSION_ROUND_RECORDED",
        "issue": None,
    }
    assert [
        item["generation_id"]
        for item in evidence.payloads("ADAPTER_ACCEPTED")[-1]["related_generations"]
    ] == [str(evidence.generations[3]), str(evidence.generations[4])]


def test_findings_come_from_the_latest_run_of_this_design_without_owner_dismissals(
    monkeypatch,
):
    version = two_twin_version()
    other = SimpleNamespace(
        id=UUID(int=999),
        design_version_id=UUID(int=998),
        findings=(finding("UTF-001", TWIN_ID, "A finding on another design version."),),
    )
    latest = SimpleNamespace(
        id=RUN_ID,
        design_version_id=version.id,
        findings=(
            finding("UTF-001", TWIN_ID, "The confirmation hides the next step."),
            finding("UTF-002", TWIN_ID, "The owner dismissed this one."),
            finding("UTF-001", SECOND_TWIN_ID, "The date format is unclear."),
        ),
    )
    older = SimpleNamespace(
        id=OLDER_RUN_ID,
        design_version_id=version.id,
        findings=(finding("UTF-001", TWIN_ID, "An older finding."),),
    )
    dismissal = create_finding_validation(
        evaluation_run_id=RUN_ID,
        twin_id=TWIN_ID,
        finding_id="UTF-002",
        sequence_number=1,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        decision=FindingDecision.OWNER_DISMISSED,
        note=None,
        decided_at=NOW,
    )
    app, _, generator, _ = discussing(
        monkeypatch,
        statement("One."),
        statement("Two."),
        synthesis(),
        version=version,
        runs=(other, latest, older),
        validations=(dismissal,),
    )
    start(app, version)
    expected = [
        {
            "twin": "T1",
            "location": "SCR-001 Create reservation",
            "summary": "The confirmation hides the next step.",
            "severity": "moderate",
            "criterion": "trust",
        },
        {
            "twin": "T2",
            "location": "SCR-001 Create reservation",
            "summary": "The date format is unclear.",
            "severity": "moderate",
            "criterion": "trust",
        },
    ]
    assert [call["context"]["findings"] for call in generator.calls[:2]] == [expected, expected]
    assert "findings" not in generator.calls[2]["context"]
    unrelated, _, generator, _ = discussing(
        monkeypatch,
        statement("One."),
        statement("Two."),
        synthesis(),
        version=version,
        runs=(other,),
    )
    start(unrelated, version)
    assert generator.calls[0]["context"]["findings"] == []


def test_start_refuses_invalid_notes_missing_models_and_stale_design_context(monkeypatch):
    version = two_twin_version()
    bare = design_fixtures.design_version(
        package=replace(version.package, owner_selected_alternative_id=None, prototype=None)
    )
    cases = [
        ({"owner_note": "   "}, {}, (422, {"code": "DISCUSSION_NOTE_INVALID"})),
        ({"owner_note": "x" * 1001}, {}, (422, {"code": "DISCUSSION_NOTE_INVALID"})),
        ({}, {"generator": None}, (503, {"code": "DESIGN_DISCUSSION_NOT_CONFIGURED"})),
        ({}, {"evidence": None}, (503, {"code": "DESIGN_DISCUSSION_NOT_CONFIGURED"})),
        ({}, {"versions": (None,)}, (404, {"code": "DESIGN_PACKAGE_NOT_FOUND"})),
        (
            {"design_content_hash": "f" * 64},
            {},
            (409, {"code": "DESIGN_CONTEXT_CHANGED"}),
        ),
        ({}, {"version": bare}, (409, {"code": "DESIGN_PROTOTYPE_REQUIRED"})),
    ]
    for changes, options, expected in cases:
        generator = FakeGenerator(statement("One."), statement("Two."), synthesis())
        settings = {"generator": generator, "evidence": MemoryEvidence(), **options}
        target = settings.pop("version", version)
        app, _ = application(monkeypatch, version=target, **settings)
        body = {
            "design_version_id": target.id,
            "design_content_hash": target.content_hash,
            **changes,
        }
        assert (
            refused(
                lambda app=app, body=body: asyncio.run(
                    app.start(
                        owner_user_id=OWNER_ID,
                        project_id=PROJECT_ID,
                        body=DesignDiscussionRequest(**body),
                    )
                )
            )
            == expected
        )
        assert generator.calls == []
        assert MemoryDiscussions.items == {}


def test_start_refuses_changed_twins_and_a_second_open_discussion(monkeypatch):
    version = two_twin_version()
    app, _, generator, _ = discussing(
        monkeypatch, statement("One."), statement("Two."), synthesis(), version=version
    )
    MemoryTwins.changed = {SECOND_TWIN_ID}
    assert refused(lambda: start(app, version)) == (409, {"code": "USER_TWIN_CONTEXT_CHANGED"})
    assert generator.calls == []
    MemoryTwins.changed = set()
    opened = start(app, version).discussion
    assert len(generator.calls) == 3
    assert refused(lambda: start(app, version)) == (409, {"code": "DESIGN_DISCUSSION_OPEN"})
    assert len(generator.calls) == 3
    decide(app, opened.id, DiscussionAction.CLOSE)
    generator.outcomes = [statement("Three."), statement("Four."), synthesis()]
    reopened = start(app, version).discussion
    assert reopened.id != opened.id
    assert set(MemoryDiscussions.items) == {opened.id, reopened.id}


def test_a_design_changed_during_the_discussion_is_not_recorded(monkeypatch):
    version = two_twin_version()
    newer = two_twin_version(version_number=2)
    app, _, _, evidence = discussing(
        monkeypatch,
        statement("One."),
        statement("Two."),
        synthesis(),
        version=version,
        versions=(version, newer),
    )
    assert refused(lambda: start(app, version)) == (409, {"code": "DESIGN_CONTEXT_CHANGED"})
    assert MemoryDiscussions.items == {}
    assert evidence.kinds()[-2:] == [(2, "ADAPTER_ACCEPTED"), (2, "APPLICATION_RESULT")]
    assert evidence.payloads("APPLICATION_RESULT")[-1] == {
        "status": "FAILED",
        "code": "HTTPException",
    }


def test_rounds_refuse_unknown_closed_stale_full_and_outdated_discussions(monkeypatch):
    version = design_fixtures.design_version()
    outcomes = [
        output
        for ordinal in range(MAX_DISCUSSION_ROUNDS)
        for output in (statement(f"Round {ordinal + 1}."), synthesis(("T1",)))
    ]
    app, _, generator, _ = discussing(monkeypatch, *outcomes, version=version)
    opened = start(app, version).discussion
    assert refused(lambda: continue_discussion(app, uuid4(), 1)) == (
        404,
        {"code": "DESIGN_DISCUSSION_NOT_FOUND"},
    )
    assert refused(lambda: continue_discussion(app, opened.id, 2)) == (
        409,
        {"code": "DESIGN_DISCUSSION_CHANGED"},
    )
    assert refused(lambda: continue_discussion(app, opened.id, 1, note=" ")) == (
        422,
        {"code": "DISCUSSION_NOTE_INVALID"},
    )
    for expected in range(1, MAX_DISCUSSION_ROUNDS):
        discussion = continue_discussion(app, opened.id, expected).discussion
    assert len(discussion.rounds) == MAX_DISCUSSION_ROUNDS
    assert len(generator.calls) == 2 * MAX_DISCUSSION_ROUNDS
    assert [
        call["output_type"].model_json_schema()["properties"]["conflicts"]["maxItems"]
        for call in generator.calls[1::2]
    ] == [0] * MAX_DISCUSSION_ROUNDS
    assert refused(lambda: continue_discussion(app, opened.id, MAX_DISCUSSION_ROUNDS)) == (
        409,
        {"code": "DESIGN_DISCUSSION_FULL"},
    )
    decide(app, opened.id, DiscussionAction.APPROVE)
    assert refused(lambda: continue_discussion(app, opened.id, MAX_DISCUSSION_ROUNDS)) == (
        409,
        {"code": "DESIGN_DISCUSSION_CLOSED"},
    )
    assert len(generator.calls) == 2 * MAX_DISCUSSION_ROUNDS


def test_rounds_refuse_a_discussion_of_an_outdated_design_or_without_a_model(monkeypatch):
    version = two_twin_version()
    app, _, generator, _ = discussing(
        monkeypatch, statement("One."), statement("Two."), synthesis(), version=version
    )
    opened = start(app, version).discussion
    app.runtime.design_query_service = DesignQuery(two_twin_version(version_number=2))
    assert refused(lambda: continue_discussion(app, opened.id, 1)) == (
        409,
        {"code": "DESIGN_CONTEXT_CHANGED"},
    )
    assert len(generator.calls) == 3
    unconfigured = DesignDiscussionApplication(
        SimpleNamespace(**{**vars(app.runtime), "real_model_runtime": None})
    )
    assert refused(lambda: continue_discussion(unconfigured, opened.id, 1)) == (
        503,
        {"code": "DESIGN_DISCUSSION_NOT_CONFIGURED"},
    )


def test_decisions_approve_or_close_an_open_discussion_once(monkeypatch):
    version = two_twin_version()
    app, _, generator, _ = discussing(
        monkeypatch, statement("One."), statement("Two."), synthesis(), version=version
    )
    opened = start(app, version).discussion
    approved = decide(app, opened.id, DiscussionAction.APPROVE)
    assert approved.status is DiscussionStatus.APPROVED
    assert approved.decided_at is not None
    assert approved.rounds == opened.rounds
    assert MemoryDiscussions.items[opened.id] == approved
    assert refused(lambda: decide(app, opened.id, DiscussionAction.CLOSE)) == (
        409,
        {"code": "DESIGN_DISCUSSION_CLOSED"},
    )
    assert refused(lambda: decide(app, uuid4(), DiscussionAction.CLOSE)) == (
        404,
        {"code": "DESIGN_DISCUSSION_NOT_FOUND"},
    )
    generator.outcomes = [statement("Three."), statement("Four."), synthesis()]
    second = start(app, version).discussion
    closed = decide(app, second.id, DiscussionAction.CLOSE)
    assert closed.status is DiscussionStatus.CLOSED
    listed = asyncio.run(app.discussions(owner_user_id=OWNER_ID, project_id=PROJECT_ID))
    assert [item.id for item in listed] == [second.id, opened.id]


def test_an_invalid_twin_statement_is_rejected_without_retry(monkeypatch):
    version = two_twin_version()
    app, _, generator, evidence = discussing(
        monkeypatch, statement("   "), statement("Two."), synthesis(), version=version
    )
    with pytest.raises(ProposalGenerationError) as failure:
        start(app, version)
    assert failure.value.code == "INVALID_TWIN_DISCUSSION_OUTPUT"
    assert len(generator.calls) == 1
    assert MemoryDiscussions.items == {}
    assert evidence.kinds() == [(0, "ADAPTER_REJECTED"), (0, "APPLICATION_RESULT")]
    assert evidence.payloads("ADAPTER_REJECTED")[0]["code"] == "ValueError"
    assert evidence.payloads("APPLICATION_RESULT") == [
        {"status": "FAILED", "code": "INVALID_TWIN_DISCUSSION_OUTPUT"}
    ]


@pytest.mark.parametrize(
    ("first", "adapter_rejected"),
    [
        (LONE_POSITION, True),
        (DUPLICATED_PROPOSALS, True),
        (REPEATED_TWIN, False),
        (ProposalGenerationError("INVALID_PROVIDER_OUTPUT"), False),
        (ProposalGenerationError("INCOMPLETE_OUTPUT"), False),
    ],
)
def test_a_rejected_synthesis_is_generated_once_more_and_then_recorded(
    monkeypatch, first, adapter_rejected
):
    version = two_twin_version()
    app, _, generator, evidence = discussing(
        monkeypatch,
        statement("One."),
        statement("Two."),
        first,
        synthesis(),
        version=version,
    )
    result = start(app, version)
    discussion = result.discussion
    assert result.status is DesignDiscussionCommandStatus.STARTED
    assert MemoryDiscussions.items == {discussion.id: discussion}
    assert [call["context"]["purpose"] for call in generator.calls] == [
        "TWIN_STATEMENT",
        "TWIN_STATEMENT",
        "DISCUSSION_SYNTHESIS",
        "DISCUSSION_SYNTHESIS",
    ]
    assert generator.calls[2]["context"] == generator.calls[3]["context"]
    [opening] = discussion.rounds
    assert [item.model_generation_id for item in opening.statements] == evidence.generations[:2]
    assert opening.synthesis.model_generation_id == evidence.generations[3]
    assert opening.synthesis.conflicts[0].twin_ids == (TWIN_ID, SECOND_TWIN_ID)
    rejection = [(2, "ADAPTER_REJECTED")] if adapter_rejected else []
    assert evidence.kinds() == [
        (0, "ADAPTER_ACCEPTED"),
        (0, "APPLICATION_RESULT"),
        (1, "ADAPTER_ACCEPTED"),
        (1, "APPLICATION_RESULT"),
        *rejection,
        (2, "APPLICATION_RESULT"),
        (3, "ADAPTER_ACCEPTED"),
        (3, "APPLICATION_RESULT"),
    ]
    assert evidence.payloads("APPLICATION_RESULT") == [
        {"status": "TWIN_STATEMENT_RECORDED", "discussion_id": str(discussion.id)},
        {"status": "TWIN_STATEMENT_RECORDED", "discussion_id": str(discussion.id)},
        {"status": "DISCUSSION_SYNTHESIS_REJECTED", "discussion_id": str(discussion.id)},
        {"status": "DESIGN_DISCUSSION_STARTED", "issue": None},
    ]
    accepted = evidence.payloads("ADAPTER_ACCEPTED")[-1]
    assert accepted["generated_content_hashes"] == {"DISCUSSION_ROUND": [opening.content_hash]}
    assert [
        (item["role"], item["generation_id"], item["code"])
        for item in accepted["related_generations"]
    ] == [
        ("TWIN_DISCUSSION", str(evidence.generations[0]), "TWIN_STATEMENT_RECORDED"),
        ("TWIN_DISCUSSION", str(evidence.generations[1]), "TWIN_STATEMENT_RECORDED"),
        ("TWIN_DISCUSSION", str(evidence.generations[2]), "DISCUSSION_SYNTHESIS_REJECTED"),
    ]


@pytest.mark.parametrize(
    ("first", "second", "code", "rejected"),
    [
        (LONE_POSITION, DUPLICATED_PROPOSALS, "INVALID_TWIN_DISCUSSION_OUTPUT", [2, 3]),
        (
            ProposalGenerationError("INVALID_PROVIDER_OUTPUT"),
            ProposalGenerationError("INCOMPLETE_OUTPUT"),
            "INCOMPLETE_OUTPUT",
            [],
        ),
        (REPEATED_TWIN, LONE_POSITION, "INVALID_TWIN_DISCUSSION_OUTPUT", [3]),
    ],
)
def test_a_second_rejected_synthesis_returns_the_error(monkeypatch, first, second, code, rejected):
    version = two_twin_version()
    app, _, generator, evidence = discussing(
        monkeypatch,
        statement("One."),
        statement("Two."),
        first,
        second,
        synthesis(),
        version=version,
    )
    with pytest.raises(ProposalGenerationError) as failure:
        start(app, version)
    assert failure.value.code == code
    assert [call["context"]["purpose"] for call in generator.calls] == [
        "TWIN_STATEMENT",
        "TWIN_STATEMENT",
        "DISCUSSION_SYNTHESIS",
        "DISCUSSION_SYNTHESIS",
    ]
    assert MemoryDiscussions.items == {}
    assert [index for index, kind in evidence.kinds() if kind == "ADAPTER_REJECTED"] == rejected
    discussion_id = evidence.payloads("APPLICATION_RESULT")[0]["discussion_id"]
    assert [
        (index, payload)
        for index, kind, payload in evidence.events
        if kind == "APPLICATION_RESULT" and index >= 2
    ] == [
        (2, {"status": "DISCUSSION_SYNTHESIS_REJECTED", "discussion_id": discussion_id}),
        (3, {"status": "FAILED", "code": code}),
    ]
    assert "ADAPTER_ACCEPTED" not in {kind for index, kind, _ in evidence.events if index >= 2}


@pytest.mark.parametrize("code", ["TIMEOUT", "PROVIDER_UNAVAILABLE", "IDENTITY_MISMATCH"])
def test_other_synthesis_failures_are_not_retried(monkeypatch, code):
    version = two_twin_version()
    app, _, generator, evidence = discussing(
        monkeypatch,
        statement("One."),
        statement("Two."),
        ProposalGenerationError(code),
        synthesis(),
        version=version,
    )
    with pytest.raises(ProposalGenerationError) as failure:
        start(app, version)
    assert failure.value.code == code
    assert len(generator.calls) == 3
    assert MemoryDiscussions.items == {}
    assert evidence.kinds()[-1] == (2, "APPLICATION_RESULT")
    assert evidence.payloads("APPLICATION_RESULT")[-1] == {"status": "FAILED", "code": code}


@pytest.mark.parametrize("code", ["TIMEOUT", "INVALID_PROVIDER_OUTPUT", "INCOMPLETE_OUTPUT"])
def test_twin_statement_failures_are_not_retried(monkeypatch, code):
    version = two_twin_version()
    app, _, generator, evidence = discussing(
        monkeypatch,
        statement("One."),
        ProposalGenerationError(code),
        statement("Two."),
        synthesis(),
        version=version,
    )
    with pytest.raises(ProposalGenerationError) as failure:
        start(app, version)
    assert failure.value.code == code
    assert len(generator.calls) == 2
    assert MemoryDiscussions.items == {}
    assert evidence.kinds() == [
        (0, "ADAPTER_ACCEPTED"),
        (0, "APPLICATION_RESULT"),
        (1, "APPLICATION_RESULT"),
    ]
    assert evidence.payloads("APPLICATION_RESULT")[-1] == {"status": "FAILED", "code": code}


def test_router_exposes_the_discussion_routes_with_their_status_codes(monkeypatch):
    version = two_twin_version()
    app, _, _, _ = discussing(
        monkeypatch,
        statement("One."),
        statement("Two."),
        synthesis(),
        statement("Three.", replies=("T2",)),
        statement("Four."),
        synthesis(),
        version=version,
    )
    server = FastAPI()
    server.state.application_runtime = app.runtime
    server.include_router(design_discussion.create_design_discussion_router())
    server.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id=OWNER_ID)
    client = TestClient(server)
    path = f"/projects/{PROJECT_ID}/design/discussions"
    body = {"design_version_id": str(version.id), "design_content_hash": version.content_hash}
    assert client.get(path).json() == []
    for invalid in (
        {**body, "design_content_hash": "F" * 64},
        {**body, "locale": "it IT"},
        {**body, "extra": True},
    ):
        assert client.post(path, json=invalid).status_code == 422
    created = client.post(path, json={**body, "locale": "en-US"})
    assert created.status_code == 201
    snapshot = created.json()
    [discussion] = MemoryDiscussions.items.values()
    assert snapshot == discussion.to_snapshot()
    rounds = f"{path}/{discussion.id}/rounds"
    assert client.post(rounds, json={"expected_round_count": 0}).status_code == 422
    missing = client.post(f"{path}/{uuid4()}/rounds", json={"expected_round_count": 1})
    assert (missing.status_code, missing.json()) == (
        404,
        {"detail": {"code": "DESIGN_DISCUSSION_NOT_FOUND"}},
    )
    extended = client.post(rounds, json={"expected_round_count": 1, "owner_note": "Discutete."})
    assert extended.status_code == 201
    assert [item["ordinal"] for item in extended.json()["rounds"]] == [1, 2]
    assert extended.json()["rounds"][1]["owner_note"] == "Discutete."
    decision = f"{path}/{discussion.id}/decision"
    assert client.post(decision, json={"action": "MAYBE"}).status_code == 422
    approved = client.post(decision, json={"action": "APPROVE"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["decided_at"] is not None
    again = client.post(decision, json={"action": "CLOSE"})
    assert (again.status_code, again.json()) == (
        409,
        {"detail": {"code": "DESIGN_DISCUSSION_CLOSED"}},
    )
    assert client.get(path).json() == [approved.json()]


def test_router_paths_and_application_registration():
    router = design_discussion.create_design_discussion_router()
    assert sorted(route.path for route in router.routes) == [
        "/projects/{project_id}/design/discussions",
        "/projects/{project_id}/design/discussions",
        "/projects/{project_id}/design/discussions/{discussion_id}/decision",
        "/projects/{project_id}/design/discussions/{discussion_id}/rounds",
    ]
    application = create_app(
        ApplicationSettings(
            application_name="OrchesTwin Design Discussion Test",
            environment=RuntimeEnvironment.TEST,
            debug=False,
            log_level=LogLevel.INFO,
            api_prefix="/api/v1",
            _env_file=None,
        ),
        runtime=ApplicationRuntime(),
    )
    paths = application.openapi()["paths"]
    prefix = "/api/v1/projects/{project_id}/design/discussions"
    assert set(paths[prefix]) == {"get", "post"}
    assert set(paths[f"{prefix}/{{discussion_id}}/rounds"]) == {"post"}
    assert set(paths[f"{prefix}/{{discussion_id}}/decision"]) == {"post"}


def test_discussions_need_a_database():
    app = DesignDiscussionApplication(SimpleNamespace(database_runtime=None))
    assert refused(
        lambda: asyncio.run(app.discussions(owner_user_id=OWNER_ID, project_id=PROJECT_ID))
    ) == (503, {"code": "DATABASE_UNAVAILABLE"})
