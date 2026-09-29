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
    FEEDBACK_REVIEWS,
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

    assert list(files) == [f"schema/{name}.schema.json" for name in SCHEMA_NAMES]
    assert len(files) == 12
    assert SCHEMA_NAMES[-2:] == ("state", "changes")
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

    assert set(documents.values()) == set(SCHEMA_NAMES)
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

    assert manifest["schemas"] == {name: schema_document(name) for name in SCHEMA_NAMES}
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
