from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from orchestwin.artifacts.mockup_html import MOCKUP_HTML_FILE, mockup_html
from orchestwin.knowledge.diagrams import (
    DEFAULT_DIAGRAM_LOCALE,
    MERMAID_VERSION,
    Diagram,
    DiagramStage,
    project_diagrams,
)
from orchestwin.knowledge.documents import (
    brief_markdown,
    code_index,
    critiques_markdown,
    design_markdown,
    index_markdown,
    mockups_markdown,
    overview_lines,
    requirements_markdown,
    team_markdown,
    twin_markdown,
    twins_markdown,
    views_markdown,
)
from orchestwin.knowledge.feedback import (
    feedback_documents,
    feedback_markdown,
    feedback_summary,
)
from orchestwin.knowledge.layout import (
    FEEDBACK_CHANGES,
    FEEDBACK_DISCUSSIONS,
    FEEDBACK_FOLDER,
    FEEDBACK_INSIGHTS,
    FEEDBACK_LEARNING,
    FEEDBACK_REVIEWS,
    FEEDBACK_TESTS,
    FEEDBACK_TEXT,
    KNOWLEDGE_FOLDER_KIND,
    KNOWLEDGE_INDEX,
    KNOWLEDGE_MANIFEST,
    KNOWLEDGE_SCHEMA_VERSION,
    STAGE_LABELS,
    STAGE_PAYLOAD_KEYS,
    STATE_DOCUMENT,
    STATE_TEXT,
    VIEW_STAGES,
    schema_document,
    stage_document,
    stage_text,
)
from orchestwin.knowledge.research_evidence import (
    EVIDENCE_DOCUMENT,
    EVIDENCE_TEXT,
    evidence_markdown,
)
from orchestwin.knowledge.research_evidence import present as has_evidence
from orchestwin.knowledge.schema import (
    SCHEMA_NAMES,
    has_design_additions,
    has_direction_additions,
    schema_files,
)
from orchestwin.knowledge.sources import KnowledgeSources
from orchestwin.knowledge.state_documents import (
    acceptance_runs,
    change_reviews_document,
    development_lines,
    learned_observations,
    learning_document,
    learning_lines,
    stale_reviews,
    state_document,
    state_language,
    state_markdown,
    test_lines,
    test_reviews_document,
)
from orchestwin.knowledge.tables import knowledge_tables
from orchestwin.knowledge.twins import PortableTwin, portable_twins
from orchestwin.knowledge.validation_records import VALIDATION_DOCUMENT, portable_records
from orchestwin.knowledge.why import WHY_DOCUMENT, folder_why
from orchestwin.knowledge.workflow_inputs import export_workflow_files, workflow_manifest
from orchestwin.models.output_language import dominant_language
from orchestwin.workflow.gates import HumanGate

GENERATOR_NAME: Final = "OrchesTwin Studio"
DESIGN_CRITIQUES_TEXT: Final = "design/critiques.md"
DESIGN_MOCKUPS_TEXT: Final = "design/mockups.md"
_ENTRY_DATE_TIME: Final = (1980, 1, 1, 0, 0, 0)
_DERIVED_FILES: Final = frozenset({KNOWLEDGE_INDEX, KNOWLEDGE_MANIFEST})
_REQUIREMENT_KINDS: Final = (
    ("needs", "NEED"),
    ("journeys", "JOURNEY"),
    ("requirements", "REQUIREMENT"),
    ("user_stories", "USER_STORY"),
    ("acceptance_criteria", "ACCEPTANCE_CRITERION"),
    ("scenarios", "SCENARIO"),
    ("risks", "PROJECT_RISK"),
    ("definition_of_done", "DEFINITION_OF_DONE"),
)


class KnowledgeFolderError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code if detail is None else f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class KnowledgeFolder:
    project_id: UUID
    project_name: str
    version_number: int
    created_at: datetime
    content_hash: str
    manifest: dict[str, object]
    files: dict[str, str]

    @property
    def entries(self) -> tuple[str, ...]:
        return tuple(sorted(self.files))

    @property
    def file_name(self) -> str:
        return f"orchestwin-{self.project_id}-knowledge-v{self.version_number}.zip"


@dataclass(frozen=True, slots=True)
class KnowledgeArchive:
    project_id: UUID
    version_number: int
    file_name: str
    content: bytes
    archive_hash: str
    content_hash: str
    entries: tuple[str, ...]


def json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def text_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def file_digests(files: Mapping[str, str]) -> dict[str, str]:
    return {path: text_digest(files[path]) for path in sorted(files)}


def folder_content_hash(files: Mapping[str, str]) -> str:
    digests = file_digests(
        {path: content for path, content in files.items() if path not in _DERIVED_FILES}
    )
    return text_digest(json.dumps(digests, sort_keys=True, separators=(",", ":")))


def stage_document_payload(sources: KnowledgeSources, stage: str) -> dict[str, object]:
    version = sources.version(stage)
    document: dict[str, object] = {
        "id": str(version.id),
        "project_id": str(version.project_id),
        "version_number": version.version_number,
        "content_hash": version.content_hash,
        "created_by_user_id": str(version.created_by_user_id),
        "created_at": version.created_at.isoformat(),
    }
    based_on = getattr(version, "based_on_version_number", None)
    if based_on is not None:
        document["based_on_version_number"] = based_on
    revision_kind = getattr(version, "revision_kind", None)
    if revision_kind is not None:
        document["revision_kind"] = getattr(revision_kind, "value", revision_kind)
    document[STAGE_PAYLOAD_KEYS[stage]] = sources.payload(stage)
    return document


def gate_document(gate: HumanGate) -> dict[str, object]:
    return {
        "id": str(gate.id),
        "gate_type": gate.gate_type.value,
        "status": gate.status.value,
        "iteration": gate.iteration,
        "updated_at": gate.updated_at.isoformat(),
        "artifact": {
            "artifact_id": str(gate.artifact.artifact_id),
            "version": gate.artifact.version,
            "content_hash": gate.artifact.content_hash,
        },
    }


def project_language(specification: Mapping[str, object]) -> str | None:
    texts = [
        *(str(item["statement"]) for item in specification["requirements"]),
        *(str(item["goal"]) for item in specification["user_stories"]),
        *(str(item["statement"]) for item in specification["acceptance_criteria"]),
    ]
    return dominant_language(texts)


def brief_language(brief: Mapping[str, object]) -> str | None:
    texts: list[str] = []
    for value in brief["fields"].values():
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, list):
            texts.extend(str(item) for item in value)
    return dominant_language(texts)


def folder_language(sources: KnowledgeSources) -> str | None:
    language = None
    if "requirements" in sources.present_stages:
        language = project_language(sources.payload("requirements"))
    return language or brief_language(sources.payload("brief"))


def _design_payload(sources: KnowledgeSources) -> dict[str, object] | None:
    return sources.payload("design") if "design" in sources.present_stages else None


def folder_diagrams(sources: KnowledgeSources) -> tuple[Diagram, ...]:
    if "requirements" not in sources.present_stages:
        return ()
    return project_diagrams(
        specification=sources.payload("requirements"),
        package=_design_payload(sources),
        system_name=sources.project_name,
        locale=DEFAULT_DIAGRAM_LOCALE,
    )


def _relative(path: str, stage: str) -> str:
    return path.removeprefix(f"{stage}/")


def _views(
    stage: DiagramStage,
    tables: Iterable[str],
    diagrams: Iterable[Diagram],
) -> str:
    return views_markdown(
        tables=[
            {"title": _table_title(path), "path": _relative(path, stage.value)}
            for path in tables
            if path.startswith(stage.value)
        ],
        diagrams=[
            {"title": diagram.title, "path": _relative(diagram.path, stage.value)}
            for diagram in diagrams
            if diagram.stage is stage
        ],
        mermaid_version=MERMAID_VERSION,
    )


def identifiers(sources: KnowledgeSources) -> list[dict[str, object]]:
    if "requirements" not in sources.present_stages:
        return []
    specification = sources.payload("requirements")
    package = _design_payload(sources)
    entries: list[dict[str, object]] = []

    def add(stage: str, kind: str, item: Mapping[str, object], scope: str | None = None) -> None:
        entries.append(
            {
                "stage": stage,
                "kind": kind,
                "scope": scope,
                "code": item["code"],
                "id": item["id"],
            }
        )

    for key, kind in _REQUIREMENT_KINDS:
        for item in specification.get(key, ()):
            add("requirements", kind, item)
    if package is None:
        return entries
    for alternative in package["alternatives"]:
        add("design", "DESIGN_ALTERNATIVE", alternative)
        for workflow in alternative["workflows"]:
            add("design", "DESIGN_WORKFLOW", workflow, str(alternative["code"]))
    for critique in package["critiques"]:
        add("design", "SYNTHETIC_DESIGN_CRITIQUE", critique)
    for concern in package["concerns"]:
        add("design", "DESIGN_CONCERN", concern)
    prototype = package["prototype"]
    if prototype is not None:
        add("design", "DECLARATIVE_PROTOTYPE", prototype)
        for screen in prototype["screens"]:
            add("design", "PROTOTYPE_SCREEN", screen, str(prototype["code"]))
            for element in screen["elements"]:
                add("design", "PROTOTYPE_ELEMENT", element, str(screen["code"]))
        for transition in prototype["transitions"]:
            add("design", "PROTOTYPE_TRANSITION", transition, str(prototype["code"]))
    return entries


def _requirement_files(
    sources: KnowledgeSources, package: Mapping[str, object] | None
) -> dict[str, str]:
    specification = sources.payload("requirements")
    diagrams = folder_diagrams(sources)
    tables = knowledge_tables(specification=specification, package=package)
    files = {
        stage_text("requirements"): requirements_markdown(
            sources.requirements, sources.requirements_gate, locale=folder_language(sources) or "en"
        )
        + _views(DiagramStage.REQUIREMENTS, tables, diagrams),
    }
    if package is not None:
        files.update(
            {
                stage_text("design"): design_markdown(
                    sources.design, sources.design_gate, code_index(specification)
                )
                + _views(DiagramStage.DESIGN, tables, diagrams),
                DESIGN_CRITIQUES_TEXT: critiques_markdown(sources.design),
                DESIGN_MOCKUPS_TEXT: mockups_markdown(sources.design),
                MOCKUP_HTML_FILE: mockup_html(
                    sources.design, language=project_language(specification)
                ),
                FEEDBACK_TEXT: feedback_markdown(sources),
            }
        )
        for path, document in feedback_documents(sources).items():
            files[path] = json_text(document)
    files.update(tables)
    files.update({diagram.path: diagram.source for diagram in diagrams})
    return files


def content_files(sources: KnowledgeSources) -> dict[str, str]:
    present = sources.present_stages
    package = _design_payload(sources)
    files = {
        stage_text("brief"): brief_markdown(sources.brief, sources.brief_gate),
        STATE_DOCUMENT: json_text(state_document(sources)),
        STATE_TEXT: state_markdown(sources, language=folder_language(sources)),
        FEEDBACK_CHANGES: json_text(change_reviews_document(sources)),
        FEEDBACK_TESTS: json_text(test_reviews_document(sources)),
    }
    if "team" in present:
        files[stage_text("team")] = team_markdown(sources.team, sources.team_gate)
    if "twins" in present:
        files[stage_text("twins")] = twins_markdown(
            sources.modeling, sources.modeling_gate, language=folder_language(sources)
        )
        files[FEEDBACK_LEARNING] = json_text(learning_document(sources))
    if "requirements" in present:
        files.update(_requirement_files(sources, package))
    for stage in present:
        files[stage_document(stage)] = json_text(stage_document_payload(sources, stage))
    for twin in portable_twins(sources):
        files[twin.document_path] = json_text(twin.document)
        files[twin.text_path] = twin_markdown(twin.document, language=folder_language(sources))
    files.update(
        schema_files(
            design_additions=package is not None and has_design_additions(package),
            direction_additions=package is not None and has_direction_additions(package),
        )
    )
    if has_evidence(sources.research_evidence):
        files[EVIDENCE_DOCUMENT] = json_text(sources.research_evidence)
        files[EVIDENCE_TEXT] = evidence_markdown(
            sources.research_evidence, language=folder_language(sources)
        )
        files.update(schema_files(research_evidence=True, only_evidence=True))
    files.update(export_workflow_files(sources))
    document = folder_why(
        project_id=str(sources.project_id),
        documents={stage: stage_document_payload(sources, stage) for stage in present},
        files=files,
    )
    from orchestwin.knowledge.validation_records import has_validation_records

    if has_validation_records(sources.validation_records):
        files[VALIDATION_DOCUMENT] = json_text(
            portable_records(
                document=document,
                records=sources.validation_records,
                evidence=sources.research_evidence,
            )
        )
        files.update(schema_files(only_validation=True))
        document = folder_why(
            project_id=str(sources.project_id),
            documents={stage: stage_document_payload(sources, stage) for stage in present},
            files=files,
        )
    files[WHY_DOCUMENT] = json_text(document)
    workflow_additions = bool(
        sources.workflow_inputs.get("decisions") or sources.workflow_inputs.get("prototypes")
    ) or (sources.team is not None and sources.team.revision_kind.value == "OWNER_PROVIDED")
    if workflow_additions:
        files.update(
            {
                path: text
                for path, text in schema_files(
                    design_additions=package is not None and has_design_additions(package),
                    workflow_additions=True,
                ).items()
                if path in {"schema/manifest.schema.json", "schema/team.schema.json"}
            }
        )
    files.update(
        schema_files(
            only_why=True,
            validation_additions=VALIDATION_DOCUMENT in files,
            workflow_additions=workflow_additions,
        )
    )
    return files


def _stage_entries(sources: KnowledgeSources) -> dict[str, dict[str, object]]:
    return {
        stage: {
            "label": STAGE_LABELS[stage],
            "version_id": str(sources.version(stage).id),
            "version_number": sources.version(stage).version_number,
            "content_hash": sources.version(stage).content_hash,
            "document": stage_document(stage),
            "text": stage_text(stage),
            "gate": gate_document(sources.gate(stage)),
        }
        for stage in sources.present_stages
    }


def _table_title(path: str) -> str:
    name = path.rsplit("/", 1)[-1].removesuffix(".csv")
    return name.replace("-", " ").capitalize()


def _view_entries(
    files: Mapping[str, str], diagrams: Iterable[Diagram], stages: Iterable[str]
) -> dict[str, object]:
    drawn = tuple(diagrams)
    present = set(stages)
    texts = {
        "requirements": [(stage_text("requirements"), STAGE_LABELS["requirements"])],
        "design": [
            (stage_text("design"), STAGE_LABELS["design"]),
            (DESIGN_CRITIQUES_TEXT, "Twin critiques of the design alternatives"),
            (DESIGN_MOCKUPS_TEXT, "Screens and transitions of the mockup"),
        ],
    }
    mockups = {
        "requirements": [],
        "design": [(MOCKUP_HTML_FILE, "Static mockup of the selected alternative")],
    }
    return {
        stage: {
            "text": [{"path": path, "title": title} for path, title in texts[stage]],
            "tables": [
                {"path": path, "title": _table_title(path)}
                for path in sorted(files)
                if path.startswith(f"{stage}/tables/") and path.endswith(".csv")
            ],
            "diagrams": [
                {
                    "key": diagram.key,
                    "kind": diagram.kind.value,
                    "subject": diagram.subject,
                    "title": diagram.title,
                    "path": diagram.path,
                }
                for diagram in drawn
                if diagram.stage.value == stage
            ],
            "mockups": [{"path": path, "title": title} for path, title in mockups[stage]],
        }
        for stage in VIEW_STAGES
        if stage in present
    }


def _progress_entry(sources: KnowledgeSources) -> dict[str, object]:
    return {
        "approved": list(sources.present_stages),
        "pending": sources.pending_stage,
        "complete": sources.complete,
    }


def _state_entry(sources: KnowledgeSources) -> dict[str, object]:
    state = sources.state
    commit = None if state.aligned is None else state.aligned.get("commit")
    return {
        "document": STATE_DOCUMENT,
        "text": STATE_TEXT,
        "changes": len(state.changes),
        "pending_changes": state.pending_changes,
        "stale_reviews": stale_reviews(sources),
        "aligned_commit": None if commit is None else str(commit),
        "open_tasks": state.open_tasks,
    }


def _feedback_entry(sources: KnowledgeSources) -> dict[str, object]:
    exported = "design" in sources.present_stages
    entry: dict[str, object] = {
        "folder": FEEDBACK_FOLDER,
        "text": FEEDBACK_TEXT if exported else None,
        "reviews_document": FEEDBACK_REVIEWS if exported else None,
        "discussions_document": FEEDBACK_DISCUSSIONS if exported else None,
        "insights_document": FEEDBACK_INSIGHTS if exported else None,
        **feedback_summary(sources),
        "changes": FEEDBACK_CHANGES,
        "change_reviews": len(sources.state.runs),
        "tests": FEEDBACK_TESTS,
        "test_runs": len(acceptance_runs(sources)),
    }
    if "twins" in sources.present_stages:
        entry["learned"] = FEEDBACK_LEARNING
        entry["learned_observations"] = learned_observations(sources)
    return entry


def folder_manifest(
    sources: KnowledgeSources,
    files: Mapping[str, str],
    twins: Iterable[PortableTwin],
    *,
    version_number: int,
    created_at: datetime,
) -> dict[str, object]:
    result = {
        "schema_version": KNOWLEDGE_SCHEMA_VERSION,
        "kind": KNOWLEDGE_FOLDER_KIND,
        "manifest": KNOWLEDGE_MANIFEST,
        "index": KNOWLEDGE_INDEX,
        "generator": {"name": GENERATOR_NAME, "mermaid_version": MERMAID_VERSION},
        "package": {
            "version_number": version_number,
            "content_hash": folder_content_hash(files),
            "created_at": created_at.isoformat(),
        },
        "project": {
            "id": str(sources.project_id),
            "name": sources.project_name,
            "language": folder_language(sources),
        },
        "stages": _stage_entries(sources),
        "progress": _progress_entry(sources),
        "state": _state_entry(sources),
        "twins": [twin.summary() for twin in twins],
        "views": _view_entries(files, folder_diagrams(sources), sources.present_stages),
        "feedback": _feedback_entry(sources),
        "identifiers": identifiers(sources),
        "schemas": {
            name: schema_document(name)
            for name in (
                *SCHEMA_NAMES,
                "why",
                *(("evidence",) if has_evidence(sources.research_evidence) else ()),
            )
        },
        "files": file_digests(files),
        "why": {"document": WHY_DOCUMENT, "schema_version": 1},
    }
    if has_evidence(sources.research_evidence):
        result["research_evidence"] = {
            "document": EVIDENCE_DOCUMENT,
            "text": EVIDENCE_TEXT,
            "sources": len(sources.research_evidence.get("evidence", ())),
            "citations": len(sources.research_evidence.get("citations", ())),
        }
    if VALIDATION_DOCUMENT in files:
        validation = json.loads(files[VALIDATION_DOCUMENT])
        result["validation"] = {
            "document": VALIDATION_DOCUMENT,
            "schema_version": 1,
            "hypotheses": len(validation["hypotheses"]),
            "outcomes": len(validation["outcomes"]),
        }
        result["schemas"]["validation"] = schema_document("validation")
    workflow = workflow_manifest(files)
    if workflow is not None:
        result["workflow_inputs"] = workflow
    return result


def folder_overview(sources: KnowledgeSources) -> list[str]:
    present = sources.present_stages
    return overview_lines(
        language=state_language(folder_language(sources)),
        project_name=sources.project_name,
        brief=sources.payload("brief"),
        twins=sources.payload("twins") if "twins" in present else None,
        specification=sources.payload("requirements") if "requirements" in present else None,
        package=_design_payload(sources),
    )


def build_knowledge_folder(
    sources: KnowledgeSources,
    *,
    version_number: int,
    created_at: datetime,
    content: Mapping[str, str] | None = None,
) -> KnowledgeFolder:
    if version_number < 1:
        raise KnowledgeFolderError("INVALID_PACKAGE_VERSION")
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise KnowledgeFolderError("INVALID_PACKAGE_TIMESTAMP")
    files = dict(content_files(sources) if content is None else content)
    manifest = folder_manifest(
        sources,
        files,
        portable_twins(sources),
        version_number=version_number,
        created_at=created_at,
    )
    files[KNOWLEDGE_MANIFEST] = json_text(manifest)
    files[KNOWLEDGE_INDEX] = index_markdown(
        manifest,
        overview=folder_overview(sources),
        development=[
            *development_lines(sources),
            *test_lines(sources),
            *learning_lines(sources),
        ],
    )
    return KnowledgeFolder(
        project_id=sources.project_id,
        project_name=sources.project_name,
        version_number=version_number,
        created_at=created_at,
        content_hash=manifest["package"]["content_hash"],
        manifest=manifest,
        files={path: files[path] for path in sorted(files)},
    )


def folder_archive(folder: KnowledgeFolder) -> KnowledgeArchive:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in folder.entries:
            info = zipfile.ZipInfo(path, date_time=_ENTRY_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, folder.files[path].encode("utf-8"))
    content = buffer.getvalue()
    return KnowledgeArchive(
        project_id=folder.project_id,
        version_number=folder.version_number,
        file_name=folder.file_name,
        content=content,
        archive_hash=hashlib.sha256(content).hexdigest(),
        content_hash=folder.content_hash,
        entries=folder.entries,
    )


__all__ = [
    "DESIGN_CRITIQUES_TEXT",
    "DESIGN_MOCKUPS_TEXT",
    "GENERATOR_NAME",
    "KNOWLEDGE_FOLDER_KIND",
    "KnowledgeArchive",
    "KnowledgeFolder",
    "KnowledgeFolderError",
    "brief_language",
    "build_knowledge_folder",
    "content_files",
    "file_digests",
    "folder_archive",
    "folder_content_hash",
    "folder_diagrams",
    "folder_language",
    "folder_manifest",
    "folder_overview",
    "gate_document",
    "identifiers",
    "json_text",
    "project_language",
    "stage_document_payload",
    "text_digest",
]
