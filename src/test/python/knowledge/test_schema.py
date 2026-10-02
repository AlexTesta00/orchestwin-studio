from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import cache
from types import SimpleNamespace
from typing import Any, Final
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from orchestwin.agents.team_gate import agent_team_artifact_reference
from orchestwin.artifacts.design_discussion import DesignDiscussion, DiscussionStatus
from orchestwin.artifacts.design_evaluation import DesignEvaluationRun
from orchestwin.artifacts.design_finding_validations import (
    FindingDecision,
    FindingValidation,
    create_finding_validation,
)
from orchestwin.artifacts.design_gate import design_artifact_reference
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.prototypes import PrototypeElementKind
from orchestwin.knowledge import schema as schema_module
from orchestwin.knowledge.folder import KnowledgeFolder, build_knowledge_folder, text_digest
from orchestwin.knowledge.layout import (
    FEEDBACK_CHANGES,
    FEEDBACK_DISCUSSIONS,
    FEEDBACK_INSIGHTS,
    FEEDBACK_LEARNING,
    FEEDBACK_REVIEWS,
    FEEDBACK_TESTS,
    KNOWLEDGE_MANIFEST,
    STAGES,
    STATE_DOCUMENT,
    STATE_TEXT,
    schema_document,
    stage_document,
)
from orchestwin.knowledge.schema import (
    MAX_DOCUMENT_DEPTH,
    SCHEMA_DIALECT,
    SCHEMA_NAMES,
    KnowledgeSchemaError,
    knowledge_schemas,
    schema_files,
    schema_name_for_path,
    validate_document,
    validate_files,
)
from orchestwin.knowledge.sources import KnowledgeFeedback, KnowledgeSources, knowledge_feedback
from orchestwin.knowledge.state import (
    MAX_BASIS_LENGTH,
    MAX_FINDING_LENGTH,
    MAX_FOLDER_TEST_RUNS,
    MAX_LEARNED_OBSERVATIONS,
    MAX_OBSERVATION_LENGTH,
    MAX_TASK_NOTE_LENGTH,
)
from orchestwin.knowledge.state_documents import learning_document, state_document
from orchestwin.projects.brief_gate import project_brief_artifact_reference
from orchestwin.projects.briefs import BriefField
from orchestwin.projects.insight_applications import (
    InsightApplication,
    InsightSourceKind,
    InsightTarget,
)
from orchestwin.projects.requirements import RequirementKind, RequirementPriority
from orchestwin.projects.requirements_gate import requirements_artifact_reference
from orchestwin.projects.requirements_quality import VerificationMethod
from orchestwin.twins.epistemics import EpistemicStatus
from orchestwin.twins.user_modeling_gate import user_modeling_artifact_reference
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGate,
    HumanGateAction,
    create_human_gate,
    transition_human_gate,
)
from src.test.python.artifacts.design_fixtures import (
    OWNER_ID,
    PROJECT_ID,
    design_version,
    requirements_version,
)
from src.test.python.artifacts.test_design_discussion import (
    BRUNO,
    discussion,
    discussion_round,
    reacting_round,
    statement,
)
from src.test.python.artifacts.test_design_evaluation import TWIN_A, TWIN_B, evaluate, template
from src.test.python.projects.test_insight_applications import application
from src.test.python.twins.test_user_modeling_gate import snapshot_version
from src.test.python.workflow.test_governed_project_setup import build_ready_project

from .knowledge_fixtures import development_sources, files_before_learning, real_sources
from .knowledge_fixtures import test_run as acceptance_run

NOW: Final = datetime(2026, 9, 27, 18, 0, tzinfo=UTC)
PUBLISHED_AT: Final = datetime(2026, 9, 27, 20, 0, tzinfo=UTC)
PROJECT_NAME: Final = "Prenotazioni del ristorante"
RUN_ID: Final = UUID("00000000-0000-4000-8000-000000000e01")
DISCUSSION_ID: Final = UUID("00000000-0000-4000-8000-000000000e02")
REMOVED: Final = object()
FRESH_PROCESS_DIGEST: Final = (
    "import hashlib, json\n"
    "from orchestwin.knowledge.schema import schema_files\n"
    "print(hashlib.sha256(json.dumps(schema_files(), sort_keys=True).encode()).hexdigest())\n"
)
NESTED_TOO_DEEPLY: Final = (
    "DOCUMENT_INVALID",
    "team",
    "team/team.json",
    "the document is nested too deeply",
)


def approved_gate(reference: GateArtifactReference, base: int) -> HumanGate:
    draft = create_human_gate(
        gate_id=UUID(int=base),
        project_id=reference.project_id,
        owner_user_id=OWNER_ID,
        gate_type=reference.gate_type,
        artifact=reference,
        created_at=NOW,
    )
    submitted = transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=NOW + timedelta(minutes=1),
        event_id=UUID(int=base + 1),
    )
    approved = transition_human_gate(
        submitted.gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=NOW + timedelta(minutes=2),
        event_id=UUID(int=base + 2),
    )
    return approved.gate


def review_runs() -> tuple[DesignEvaluationRun, ...]:
    return (
        evaluate(
            design_version(),
            {
                TWIN_A: (
                    template("UTF-001", "SCR-001 Guest name", "The field lacks help."),
                    template("UTF-002", "SCR-001 Save", "The action is unclear."),
                ),
                TWIN_B: (template("UTF-001", "SCR-001 Save", "The button is small."),),
            },
            run_id=RUN_ID,
            clock=NOW,
        ),
    )


def owner_decisions() -> tuple[FindingValidation, ...]:
    common = {"evaluation_run_id": RUN_ID, "project_id": PROJECT_ID, "owner_user_id": OWNER_ID}
    return (
        create_finding_validation(
            twin_id=TWIN_A,
            finding_id="UTF-001",
            sequence_number=1,
            decision=FindingDecision.OWNER_CONFIRMED,
            note="Il campo ha davvero bisogno di un aiuto.",
            decided_at=NOW + timedelta(minutes=10),
            **common,
        ),
        create_finding_validation(
            twin_id=TWIN_B,
            finding_id="UTF-001",
            sequence_number=1,
            decision=FindingDecision.OWNER_DISMISSED,
            note=None,
            decided_at=NOW + timedelta(minutes=20),
            **common,
        ),
    )


def approved_discussion(design: DesignPackageVersion) -> DesignDiscussion:
    answered = discussion_round(
        note="Il riepilogo vi basta?",
        statements=(
            statement(generation=101, owner_answer="Sì, il riepilogo mi basta."),
            statement(BRUNO, "Bruno", generation=102),
        ),
    )
    opened = discussion(
        id=DISCUSSION_ID,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        design_version_id=design.id,
        design_version_number=design.version_number,
        design_content_hash=design.content_hash,
        rounds=(answered, reacting_round()),
    )
    return opened.decided(DiscussionStatus.APPROVED, NOW)


def applied_insights() -> tuple[InsightApplication, ...]:
    return (
        application(
            application_id=UUID(int=8001),
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            source_twin_id=TWIN_A,
        ),
        application(
            application_id=UUID(int=8002),
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            source_kind=InsightSourceKind.TWIN_DISCUSSION,
            source_id=str(DISCUSSION_ID),
            source_twin_id=None,
            target=InsightTarget.BRIEF,
            target_field=BriefField.GOALS,
            target_code=None,
        ),
    )


def twin_feedback(design: DesignPackageVersion) -> KnowledgeFeedback:
    return knowledge_feedback(
        runs=review_runs(),
        validations=owner_decisions(),
        discussions=(approved_discussion(design),),
        applications=applied_insights(),
    )


def knowledge_sources() -> KnowledgeSources:
    scenario = build_ready_project()
    modeling = snapshot_version()
    requirements = requirements_version()
    design = design_version(version_number=2)
    return KnowledgeSources(
        project_id=PROJECT_ID,
        project_name=PROJECT_NAME,
        brief=scenario.brief_version,
        brief_gate=approved_gate(project_brief_artifact_reference(scenario.brief_version), 1000),
        team=scenario.team_version,
        team_gate=approved_gate(agent_team_artifact_reference(scenario.team_version), 2000),
        modeling=modeling,
        modeling_gate=approved_gate(user_modeling_artifact_reference(modeling), 3000),
        requirements=requirements,
        requirements_gate=approved_gate(requirements_artifact_reference(requirements), 4000),
        design=design,
        design_gate=approved_gate(design_artifact_reference(design), 5000),
        feedback=twin_feedback(design),
    )


@cache
def built_folder() -> KnowledgeFolder:
    return build_knowledge_folder(knowledge_sources(), version_number=1, created_at=PUBLISHED_AT)


def json_documents(files: Mapping[str, str]) -> dict[str, str]:
    return {
        path: name for path in sorted(files) if (name := schema_name_for_path(path)) is not None
    }


def document_path(files: Mapping[str, str], name: str) -> str:
    return next(path for path, kind in json_documents(files).items() if kind == name)


def changed(document: dict[str, Any], keys: tuple[str | int, ...], value: object) -> Any:
    result = deepcopy(document)
    target: Any = result
    for key in keys[:-1]:
        target = target[key]
    if value is REMOVED:
        del target[keys[-1]]
    else:
        target[keys[-1]] = value
    return result


def nested_value(depth: int) -> object:
    value: object = 0
    for _ in range(depth):
        value = {"a": value}
    return value


def team_failure(text: str) -> tuple[str, str, str | None, str]:
    with pytest.raises(KnowledgeSchemaError) as caught:
        validate_files({stage_document("team"): text})
    return (caught.value.code, caught.value.document, caught.value.path, caught.value.message)


def test_schema_files_publish_one_valid_json_schema_for_every_document_kind() -> None:
    files = schema_files()
    schemas = knowledge_schemas()
    fresh = subprocess.run(
        [sys.executable, "-c", FRESH_PROCESS_DIGEST],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": "7"},
    )

    assert list(files) == [schema_document(name) for name in SCHEMA_NAMES]
    assert len(files) == 14
    assert SCHEMA_NAMES[-4:] == ("state", "changes", "tests", "learning")
    assert list(files)[-1] == "schema/learned.schema.json"
    assert schema_files() == files
    assert fresh.stdout.strip() == (
        hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    )
    for name in SCHEMA_NAMES:
        text = files[schema_document(name)]
        schema = json.loads(text)
        Draft202012Validator.check_schema(schema)
        assert text == json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        assert schema == schemas[name]
        assert schema["$schema"] == SCHEMA_DIALECT == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"] == f"urn:orchestwin:knowledge-folder:3:{name}"
        assert schema["title"].strip()
        assert schema["description"].strip()


def test_every_json_document_of_an_exported_folder_matches_its_published_schema() -> None:
    folder = built_folder()
    documents = json_documents(folder.files)
    design = json.loads(folder.files[stage_document("design")])
    statements = [
        item
        for entry in json.loads(folder.files[FEEDBACK_DISCUSSIONS])["discussions"]
        for turn in entry["rounds"]
        for item in turn["statements"]
    ]

    assert set(documents.values()) == {*SCHEMA_NAMES, "why"}
    assert design["based_on_version_number"] == 1
    assert {"visual_language" in item for item in design["package"]["alternatives"]} == {
        True,
        False,
    }
    assert any("reactions" in item for item in statements)
    assert any("answer_to_owner" in item for item in statements)
    for path, name in documents.items():
        payload = json.loads(folder.files[path])
        published = Draft202012Validator(json.loads(folder.files[schema_document(name)]))
        assert [error.message for error in published.iter_errors(payload)] == [], path
        validate_document(name, payload)
    validate_files(folder.files)


def test_the_folder_carries_its_own_schemas_and_lists_them_in_the_manifest() -> None:
    folder = built_folder()
    manifest = json.loads(folder.files[KNOWLEDGE_MANIFEST])

    assert manifest["schemas"] == {name: schema_document(name) for name in (*SCHEMA_NAMES, "why")}
    for path, text in schema_files().items():
        assert folder.files[path] == text
        assert manifest["files"][path] == text_digest(text)


def test_schema_names_are_found_for_every_json_document_and_for_nothing_else() -> None:
    folder = built_folder()
    names = {path: schema_name_for_path(path) for path in folder.files}
    twins = [path for path, name in names.items() if name == "twin"]

    assert names[KNOWLEDGE_MANIFEST] == "manifest"
    for stage in STAGES:
        assert names[stage_document(stage)] == stage
    assert names[FEEDBACK_REVIEWS] == "reviews"
    assert names[FEEDBACK_DISCUSSIONS] == "discussions"
    assert names[FEEDBACK_INSIGHTS] == "insights"
    assert names[STATE_DOCUMENT] == "state"
    assert names[FEEDBACK_CHANGES] == "changes"
    assert names[FEEDBACK_TESTS] == "tests"
    assert names[FEEDBACK_LEARNING] == "learning"
    assert names[STATE_TEXT] is None
    assert twins == [path for path in folder.files if path.endswith("/twin.json")]
    assert len(twins) == 1
    for path, name in names.items():
        assert (name is not None) == (path.endswith(".json") and not path.startswith("schema/"))
    assert {path.rsplit(".", 1)[1] for path, name in names.items() if name is None} == {
        "csv",
        "html",
        "json",
        "md",
        "mmd",
    }
    for path in (
        "twins/feedback/feedback.md",
        "twins/feedback/twin.json",
        "twins/twin.json",
        "twins//twin.json",
        "twins/ada-3fe4f1ad/nested/twin.json",
        "schema/twin.schema.json",
        "notes/brief.json",
    ):
        assert schema_name_for_path(path) is None


@pytest.mark.parametrize(
    ("name", "keys", "value", "location"),
    [
        ("manifest", ("package",), REMOVED, "package"),
        (
            "requirements",
            ("specification", "requirements", 0, "kind"),
            "WISH",
            "specification.requirements[0].kind",
        ),
        (
            "requirements",
            ("specification", "requirements", 0, "code"),
            "REQ-1",
            "specification.requirements[0].code",
        ),
        ("twin", ("kind",), "orchestwin.persona", "kind"),
        ("twins", ("content_hash",), "A" * 64, "content_hash"),
        ("manifest", ("stages", "brief", "version_number"), "1", "stages.brief.version_number"),
        (
            "design",
            ("package", "alternatives", 0, "approach"),
            None,
            "package.alternatives[0].approach",
        ),
        ("manifest", ("progress",), REMOVED, ""),
        ("manifest", ("state",), REMOVED, ""),
        ("manifest", ("feedback", "changes"), REMOVED, ""),
        ("manifest", ("state",), None, "state"),
        ("manifest", ("stages", "team"), REMOVED, "stages"),
        ("manifest", ("stages", "requirements"), None, "stages.requirements"),
        ("manifest", ("schema_version",), 1, "schema_version"),
        ("manifest", ("progress", "pending"), "roadmap", "progress.pending"),
        ("manifest", ("state", "aligned_commit"), "ABC1234", "state.aligned_commit"),
        ("manifest", ("feedback", "test_runs"), REMOVED, "feedback"),
        ("manifest", ("feedback", "tests"), REMOVED, "feedback"),
        ("manifest", ("feedback", "tests"), "twins/feedback/runs.json", "feedback.tests"),
        ("manifest", ("feedback", "test_runs"), None, "feedback.test_runs"),
        ("manifest", ("feedback", "test_runs"), -1, "feedback.test_runs"),
        ("manifest", ("feedback", "learned"), REMOVED, "feedback"),
        ("manifest", ("feedback", "learned_observations"), REMOVED, "feedback"),
        ("manifest", ("feedback", "learned"), "twins/feedback/learning.json", "feedback.learned"),
        ("manifest", ("feedback", "learned_observations"), -1, "feedback.learned_observations"),
        ("manifest", ("state", "stale_reviews"), None, "state.stale_reviews"),
        ("manifest", ("state", "stale_reviews"), "1", "state.stale_reviews"),
        ("learning", ("schema_version",), 2, "schema_version"),
        ("learning", ("kind",), "orchestwin.test-reviews", "kind"),
        (
            "learning",
            ("twins", 0, "profile_version_number"),
            0,
            "twins[0].profile_version_number",
        ),
        ("tests", ("schema_version",), 2, "schema_version"),
        ("tests", ("kind",), "orchestwin.change-reviews", "kind"),
        ("state", ("schema_version",), 2, "schema_version"),
        (
            "state",
            ("reference", "design", "alternative_code"),
            "DES-2",
            "reference.design.alternative_code",
        ),
        ("changes", ("kind",), "orchestwin.project-state", "kind"),
    ],
)
def test_both_validators_reject_a_document_that_breaks_its_schema(
    name: str, keys: tuple[str | int, ...], value: object, location: str
) -> None:
    files = built_folder().files
    document = changed(json.loads(files[document_path(files, name)]), keys, value)

    with pytest.raises(KnowledgeSchemaError) as caught:
        validate_document(name, document)

    assert not Draft202012Validator(knowledge_schemas()[name]).is_valid(document)
    assert caught.value.code == "DOCUMENT_INVALID"
    assert caught.value.document == name
    assert caught.value.location == location
    assert caught.value.message


def acceptance_document() -> dict[str, Any]:
    return {
        "schema_version": 3,
        "kind": "orchestwin.test-reviews",
        "project_id": str(PROJECT_ID),
        "runs": [acceptance_run()],
    }


def test_both_validators_accept_a_run_of_the_acceptance_tests() -> None:
    document = acceptance_document()
    unreviewed = changed(
        changed(document, ("runs", 0, "critiques"), []), ("runs", 0, "reviewed_at"), None
    )
    many = changed(document, ("runs",), [acceptance_run()] * MAX_FOLDER_TEST_RUNS)
    published = Draft202012Validator(knowledge_schemas()["tests"])

    for payload in (document, unreviewed, many):
        validate_document("tests", payload)
        assert [error.message for error in published.iter_errors(payload)] == []


@pytest.mark.parametrize(
    ("keys", "value", "location"),
    [
        (("application", "kind"), "FOLDER", "application.kind"),
        (("application", "address"), "", "application.address"),
        (("browsers",), [], "browsers"),
        (("browsers", 0, "name"), "safari", "browsers[0].name"),
        (("browsers", 0, "version"), "1" * 81, "browsers[0].version"),
        (("reference", "alternative_code"), "DES-2", "reference.alternative_code"),
        (("summary", "not_run"), REMOVED, "summary.not_run"),
        (("criteria", 0, "status"), "SKIPPED", "criteria[0].status"),
        (("criteria", 0, "paths", 0), "TP-1", "criteria[0].paths[0]"),
        (("not_covered", 0, "reason"), "x" * 301, "not_covered[0].reason"),
        (("results", 0, "path", "criteria"), [], "results[0].path.criteria"),
        (("results", 0, "path", "heading"), "x" * 121, "results[0].path.heading"),
        (("results", 0, "path", "steps"), [], "results[0].path.steps"),
        (("results", 0, "path", "steps", 0, "action"), "SCROLL", "results[0].path.steps[0].action"),
        (
            ("results", 0, "path", "steps", 1, "target", "role"),
            "paragraph",
            "results[0].path.steps[1].target.role",
        ),
        (
            ("results", 0, "path", "steps", 1, "target", "name"),
            "",
            "results[0].path.steps[1].target.name",
        ),
        (
            ("results", 0, "path", "steps", 1, "value"),
            "x" * 201,
            "results[0].path.steps[1].value",
        ),
        (
            ("results", 0, "path", "steps", 2, "expect", "kind"),
            "TEXT_EQUALS",
            "results[0].path.steps[2].expect.kind",
        ),
        (("results", 0, "status"), "SKIPPED", "results[0].status"),
        (("results", 0, "seconds"), -1, "results[0].seconds"),
        (("results", 0, "steps", 0, "index"), 0, "results[0].steps[0].index"),
        (("results", 0, "steps", 0, "status"), "PASSED", "results[0].steps[0].status"),
        (("results", 0, "steps", 0, "detail"), "x" * 301, "results[0].steps[0].detail"),
        (
            ("results", 0, "steps", 0, "screenshot"),
            "TP-001\\chrome\\01.png",
            "results[0].steps[0].screenshot",
        ),
        (("results", 0, "steps", 0, "screenshot"), "..", "results[0].steps[0].screenshot"),
        (("results", 0, "page_text"), "x" * 1501, "results[0].page_text"),
        (("critiques", 0, "verdict"), "ALIGNED", "critiques[0].verdict"),
        (("critiques", 0, "twin_name"), "", "critiques[0].twin_name"),
        (
            ("critiques", 0, "findings", 0, "about", "screen"),
            "SCR-2",
            "critiques[0].findings[0].about.screen",
        ),
        (
            ("critiques", 0, "findings", 0, "severity"),
            "CRITICAL",
            "critiques[0].findings[0].severity",
        ),
        (("reviewed_at",), "2026-09-29 10:20", "reviewed_at"),
        (("cost_microusd",), -1, "cost_microusd"),
    ],
)
def test_both_validators_reject_a_run_that_breaks_its_schema(
    keys: tuple[str | int, ...], value: object, location: str
) -> None:
    document = changed(acceptance_document(), ("runs", 0, *keys), value)

    with pytest.raises(KnowledgeSchemaError) as caught:
        validate_document("tests", document)

    assert not Draft202012Validator(knowledge_schemas()["tests"]).is_valid(document)
    assert caught.value.code == "DOCUMENT_INVALID"
    assert caught.value.location == f"runs[0].{location}"


def test_the_folder_keeps_at_most_twenty_runs_and_the_manifest_their_count() -> None:
    document = changed(acceptance_document(), ("runs",), [acceptance_run()] * 21)
    feedback = knowledge_schemas()["manifest"]["$defs"]["FeedbackSummary"]

    with pytest.raises(KnowledgeSchemaError) as caught:
        validate_document("tests", document)

    assert MAX_FOLDER_TEST_RUNS == 20
    assert caught.value.location == "runs"
    assert not Draft202012Validator(knowledge_schemas()["tests"]).is_valid(document)
    assert feedback["dependentRequired"] == {
        "tests": ["test_runs"],
        "test_runs": ["tests"],
        "learned": ["learned_observations"],
        "learned_observations": ["learned"],
    }
    assert feedback["properties"]["tests"]["const"] == FEEDBACK_TESTS
    assert feedback["properties"]["learned"]["const"] == FEEDBACK_LEARNING


def development_document(name: str) -> dict[str, Any]:
    package = real_sources(state=development_sources())
    document = state_document(package) if name == "state" else learning_document(package)
    return json.loads(json.dumps(document))


def located(keys: tuple[str | int, ...]) -> str:
    location = ""
    for key in keys:
        location += f"[{key}]" if isinstance(key, int) else (f".{key}" if location else key)
    return location


@pytest.mark.parametrize("name", ["state", "learning"])
def test_both_validators_accept_the_tasks_the_reviews_and_what_the_twins_learned(
    name: str,
) -> None:
    document = development_document(name)
    published = Draft202012Validator(knowledge_schemas()[name])

    validate_document(name, document)

    assert [error.message for error in published.iter_errors(document)] == []


def test_both_validators_accept_the_documents_of_a_folder_published_before_learning() -> None:
    folder = build_knowledge_folder(
        real_sources(state=development_sources()), version_number=1, created_at=PUBLISHED_AT
    )
    files = files_before_learning(folder.files)

    for path, name in ((STATE_DOCUMENT, "state"), (KNOWLEDGE_MANIFEST, "manifest")):
        payload = json.loads(files[path])
        validate_document(name, payload)
        assert Draft202012Validator(knowledge_schemas()[name]).is_valid(payload), path
    assert "origin" not in json.loads(files[STATE_DOCUMENT])["tasks"][0]


@pytest.mark.parametrize(
    ("name", "keys", "value"),
    [
        ("state", ("tasks", 0, "status"), "CLOSED"),
        ("state", ("tasks", 1, "origin", "kind"), "COMMIT"),
        ("state", ("tasks", 1, "origin"), None),
        ("state", ("tasks", 1, "origin", "twin_id"), "twin"),
        ("state", ("tasks", 1, "origin", "twin_name"), ""),
        ("state", ("tasks", 1, "origin", "test_run_id"), REMOVED),
        ("state", ("tasks", 2, "about", "criteria", 0), "REQ-003"),
        ("state", ("tasks", 2, "about", "criteria"), None),
        ("state", ("tasks", 2, "from_commit"), "not-a-commit"),
        ("state", ("tasks", 2, "from_commit"), REMOVED),
        ("state", ("tasks", 4, "closed_at"), "2026-09-29 12:00"),
        ("state", ("changes", 1, "review", "reference", "design_version_number"), 0),
        ("state", ("changes", 1, "review", "reference", "alternative_code"), "DES-2"),
        ("state", ("changes", 1, "review", "stale"), None),
        ("state", ("changes", 1, "review", "stale"), "yes"),
        ("learning", ("twins", 0, "label"), "1"),
        ("learning", ("twins", 0, "label"), "1.03"),
        ("learning", ("twins", 0, "label"), "0.1"),
        ("learning", ("twins", 0, "twin_name"), ""),
        ("learning", ("twins", 0, "development_version_number"), -1),
        ("learning", ("twins", 0, "observations", 0, "code"), "TSK-001"),
        ("learning", ("twins", 0, "observations", 0, "code"), "OBS-01"),
        ("learning", ("twins", 0, "observations", 0, "source"), "MODEL"),
        ("learning", ("twins", 0, "observations", 0, "statement"), ""),
        ("learning", ("twins", 0, "observations", 0, "basis"), ""),
        ("learning", ("twins", 0, "observations", 0, "contradicts_profile"), ""),
        ("learning", ("twins", 0, "observations", 0, "about", "requirement"), "SCR-001"),
        ("learning", ("twins", 0, "observations", 0, "added_in_version"), 0),
        ("learning", ("twins", 0, "observations", 0, "approved_at"), "ieri"),
        ("learning", ("twins", 0, "observations", 0, "update_id"), "update"),
        ("learning", ("twins", 0, "observations", 1, "basis"), REMOVED),
        ("learning", ("twins", 0, "retired", 0, "code"), "OBS-2"),
        ("learning", ("twins", 0, "retired", 0, "retired_in_version"), 0),
        ("learning", ("twins", 0, "retired"), REMOVED),
    ],
)
def test_both_validators_reject_a_task_a_review_or_a_learned_observation_out_of_the_contract(
    name: str, keys: tuple[str | int, ...], value: object
) -> None:
    document = changed(development_document(name), keys, value)

    with pytest.raises(KnowledgeSchemaError) as caught:
        validate_document(name, document)

    assert not Draft202012Validator(knowledge_schemas()[name]).is_valid(document)
    assert caught.value.code == "DOCUMENT_INVALID"
    assert caught.value.location == located(keys)


@pytest.mark.parametrize(
    ("name", "keys", "limit"),
    [
        ("learning", ("twins", 0, "observations", 0, "statement"), MAX_OBSERVATION_LENGTH),
        ("learning", ("twins", 0, "observations", 0, "basis"), MAX_BASIS_LENGTH),
        ("learning", ("twins", 0, "observations", 0, "contradicts_profile"), MAX_BASIS_LENGTH),
        ("learning", ("twins", 0, "retired", 0, "statement"), MAX_OBSERVATION_LENGTH),
        ("learning", ("twins", 0, "retired", 0, "reason"), MAX_TASK_NOTE_LENGTH),
        ("state", ("tasks", 5, "note"), MAX_TASK_NOTE_LENGTH),
        ("state", ("tasks", 2, "origin", "finding"), MAX_FINDING_LENGTH),
    ],
)
def test_both_validators_hold_the_text_limits_of_the_contract(
    name: str, keys: tuple[str | int, ...], limit: int
) -> None:
    document = development_document(name)
    at_limit = changed(document, keys, "x" * limit)
    beyond = changed(document, keys, "x" * (limit + 1))
    published = Draft202012Validator(knowledge_schemas()[name])

    validate_document(name, at_limit)
    with pytest.raises(KnowledgeSchemaError) as caught:
        validate_document(name, beyond)

    assert published.is_valid(at_limit)
    assert not published.is_valid(beyond)
    assert caught.value.location == located(keys)


def test_a_twin_keeps_at_most_twenty_active_learned_observations() -> None:
    document = development_document("learning")
    observation = document["twins"][0]["observations"][0]
    most = changed(document, ("twins", 0, "observations"), [observation] * MAX_LEARNED_OBSERVATIONS)
    beyond = changed(
        document, ("twins", 0, "observations"), [observation] * (MAX_LEARNED_OBSERVATIONS + 1)
    )
    retired = changed(document, ("twins", 0, "retired"), document["twins"][0]["retired"] * 30)
    published = Draft202012Validator(knowledge_schemas()["learning"])

    validate_document("learning", most)
    validate_document("learning", retired)
    with pytest.raises(KnowledgeSchemaError) as caught:
        validate_document("learning", beyond)

    assert MAX_LEARNED_OBSERVATIONS == 20
    assert published.is_valid(most) and published.is_valid(retired)
    assert not published.is_valid(beyond)
    assert caught.value.location == "twins[0].observations"


def test_the_published_schemas_leave_the_new_keys_optional() -> None:
    schemas = knowledge_schemas()
    state = schemas["state"]["$defs"]
    manifest = schemas["manifest"]["$defs"]

    assert state["CodeTask"]["required"] == [
        "code",
        "text",
        "about",
        "from_commit",
        "created_at",
        "status",
    ]
    assert state["TaskSubjects"]["required"] == ["requirements", "screens"]
    assert state["ChangeReviewSummary"]["required"] == [
        "run_id",
        "reviewed_at",
        "verdict",
        "summary",
    ]
    assert {"type": "null"} in state["CodeTask"]["properties"]["closed_at"]["anyOf"]
    assert {"type": "null"} in state["CodeTask"]["properties"]["note"]["anyOf"]
    assert {"type": "null"} in state["ChangeReviewSummary"]["properties"]["reference"]["anyOf"]
    assert state["CodeTask"]["properties"]["origin"]["$ref"] == "#/$defs/TaskOrigin"
    assert state["ChangeReviewSummary"]["properties"]["stale"]["type"] == "boolean"
    assert state["CodeTask"]["properties"]["status"]["enum"] == ["OPEN", "DONE", "DROPPED"]
    assert state["TaskOrigin"]["properties"]["kind"]["enum"] == ["CODE_CHANGE", "TEST_RUN", "OWNER"]
    assert "stale_reviews" not in manifest["StateEntry"]["required"]
    assert "learned" not in manifest["FeedbackSummary"]["required"]
    assert schemas["learning"]["$id"] == "urn:orchestwin:knowledge-folder:3:learning"
    assert schemas["learning"]["$defs"]["LearnedObservation"]["properties"]["source"]["enum"] == [
        "TWIN_CRITIQUE",
        "OWNER",
    ]


def test_unknown_properties_are_accepted_at_the_top_level_and_in_nested_objects() -> None:
    files = built_folder().files
    manifest = json.loads(files[KNOWLEDGE_MANIFEST])
    manifest["exported_by"] = {"tool": "a later Studio release"}
    design = json.loads(files[stage_document("design")])
    design["package"]["alternatives"][0]["mood_board"] = ["warm", "calm"]
    design["package"]["prototype"]["screens"][0]["elements"][0]["tooltip"] = "Help"

    validate_document("manifest", manifest)
    validate_document("design", design)

    assert Draft202012Validator(knowledge_schemas()["manifest"]).is_valid(manifest)
    assert Draft202012Validator(knowledge_schemas()["design"]).is_valid(design)


def test_validate_files_reports_broken_json_and_ignores_files_without_a_schema() -> None:
    files = built_folder().files
    twin = document_path(files, "twin")

    with pytest.raises(KnowledgeSchemaError) as broken:
        validate_files({**files, stage_document("team"): '{"id": '})
    with pytest.raises(KnowledgeSchemaError) as invalid:
        validate_files({**files, twin: json.dumps({**json.loads(files[twin]), "kind": "x"})})
    validate_files(
        {
            "notes.md": "{",
            "design/tables/screens.csv": "{",
            "twins/feedback/feedback.md": "{",
            schema_document("design"): "{",
        }
    )

    assert (broken.value.code, broken.value.document, broken.value.path) == (
        "DOCUMENT_NOT_JSON",
        "team",
        "team/team.json",
    )
    assert (invalid.value.code, invalid.value.document, invalid.value.path) == (
        "DOCUMENT_INVALID",
        "twin",
        twin,
    )
    assert invalid.value.location == "kind"


def test_validate_files_reports_a_document_nested_beyond_the_depth_limit_as_invalid() -> None:
    team = json.loads(built_folder().files[stage_document("team")])
    within = json.dumps({**team, "x": nested_value(MAX_DOCUMENT_DEPTH // 2)})
    beyond = json.dumps({**team, "x": nested_value(MAX_DOCUMENT_DEPTH + 30)})

    validate_files({stage_document("team"): within})

    assert team_failure(beyond) == NESTED_TOO_DEEPLY


def test_validate_files_reports_json_the_parser_cannot_nest_as_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def too_deep(text: str) -> object:
        raise RecursionError("maximum recursion depth exceeded while decoding a JSON array")

    monkeypatch.setattr(schema_module, "json", SimpleNamespace(loads=too_deep))

    assert team_failure("[]") == NESTED_TOO_DEEPLY


@pytest.mark.parametrize("text", ['{"id": ', "", "[" * (MAX_DOCUMENT_DEPTH + 30)])
def test_validate_files_still_reports_a_text_that_is_not_json_as_not_json(text: str) -> None:
    assert team_failure(text)[:3] == ("DOCUMENT_NOT_JSON", "team", "team/team.json")


def test_validate_files_reports_json_nested_beyond_the_parser_limit_as_invalid() -> None:
    assert team_failure("[" * 100_000 + "]" * 100_000) == NESTED_TOO_DEEPLY


def test_validate_document_rejects_an_unknown_schema_name() -> None:
    with pytest.raises(KnowledgeSchemaError) as caught:
        validate_document("roadmap", {})

    assert caught.value.code == "UNKNOWN_SCHEMA"
    assert caught.value.document == "roadmap"


@pytest.mark.parametrize(
    ("name", "enumeration"),
    [
        ("requirements", RequirementKind),
        ("requirements", RequirementPriority),
        ("requirements", VerificationMethod),
        ("twins", EpistemicStatus),
        ("twin", EpistemicStatus),
        ("design", PrototypeElementKind),
        ("reviews", FindingDecision),
        ("discussions", DiscussionStatus),
        ("brief", BriefField),
    ],
)
def test_published_enumerations_are_the_domain_enumerations(
    name: str, enumeration: type[StrEnum]
) -> None:
    definition = knowledge_schemas()[name]["$defs"][enumeration.__name__]

    assert definition["type"] == "string"
    assert definition["enum"] == [member.value for member in enumeration]


def test_every_published_enumeration_is_a_domain_enumeration() -> None:
    published = {
        name: definition
        for schema in knowledge_schemas().values()
        for name, definition in schema["$defs"].items()
        if "enum" in definition
    }

    assert {"BriefField", "HumanGateType", "DiagramKind", "ReactionVerdict"} <= set(published)
    for name, definition in published.items():
        enumeration = getattr(schema_module, name)
        assert issubclass(enumeration, StrEnum)
        assert enumeration.__module__ != schema_module.__name__
        assert definition["enum"] == [member.value for member in enumeration]


def test_the_brief_schema_describes_every_brief_field() -> None:
    fields = knowledge_schemas()["brief"]["$defs"]["BriefFieldValues"]

    assert list(fields["properties"]) == [field.value for field in BriefField]
    assert fields["required"] == [field.value for field in BriefField]


__all__ = [
    "applied_insights",
    "approved_discussion",
    "approved_gate",
    "built_folder",
    "knowledge_sources",
    "owner_decisions",
    "review_runs",
    "twin_feedback",
]
