"""Bounded manifest then one audited, schema-constrained model call per file."""

import json
import re
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, create_model

from orchestwin.models.proposal_evidence import (
    ProposalEvidenceError,
    child_proposal_evidence,
    current_proposal_evidence,
)
from orchestwin.models.proposal_generation import ProposalGenerationError, wire_value
from orchestwin.models.source_context import (
    IMPLEMENTATION_VIEW,
    implementation_contract,
    implementation_work_order,
)
from orchestwin.models.source_proposals import (
    MAX_CONTEXT_BYTES,
    SourceFile,
    SourceOutput,
    SourceProposal,
    _Output,
    _validate_files,
    build_source_binding,
    file_entry,
)
from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash

PROTOCOL = "SOURCE_FILES_V2_TEXT"
MANIFEST_BUDGET = 3200
FILE_BUDGET = 4096
MAX_FILES = 8
MANIFEST_CONTRACT = "SOURCE_MANIFEST_V9_ACCEPTANCE_INPUTS"


class PlannedFile(_Output):
    normalized_path: str = Field(
        min_length=1, max_length=240, pattern=r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$"
    )
    media_type: Literal[
        "application/javascript",
        "application/json",
        "application/sql",
        "application/typescript",
        "application/xml",
        "image/svg+xml",
        "text/css",
        "text/html",
        "text/javascript",
        "text/plain",
        "text/x-php",
        "text/xml",
    ]
    purpose: str = Field(min_length=1, max_length=120, pattern=r"^[^\x00-\x1f\x7f]*$")
    interface: str = Field(
        min_length=1, max_length=400, pattern=r"^[^\x00-\x1f\x7f]*[(:][^\x00-\x1f\x7f]*$"
    )
    depends_on: list[Annotated[str, Field(min_length=1, max_length=240)]] = Field(
        max_length=MAX_FILES - 1
    )


class BehaviorPlan(_Output):
    """A model-authored implementation plan, never proof of implemented behavior."""

    inputs_and_validation: str = Field(min_length=1, max_length=300, pattern=r"^[^\x00-\x1f\x7f]*$")
    state_and_lifetime: str = Field(min_length=1, max_length=300, pattern=r"^[^\x00-\x1f\x7f]*$")
    observable_outputs: str = Field(min_length=1, max_length=300, pattern=r"^[^\x00-\x1f\x7f]*$")


class SourceManifest(_Output):
    behavior_plan: BehaviorPlan
    rationale: str = Field(
        min_length=1, max_length=160, pattern=r"^[^\x00-\x20\x7f]+( [^\x00-\x20\x7f]+)*$"
    )
    files: list[PlannedFile] = Field(min_length=1, max_length=MAX_FILES)


class AcceptanceCheck(_Output):
    """Model-authored witness plan; execution must independently verify it."""

    source: str
    public_interface: str = Field(min_length=3, max_length=300, pattern=r"^[^\x00-\x1f\x7f]*$")
    observable_postcondition: str = Field(
        min_length=3, max_length=400, pattern=r"^[^\x00-\x1f\x7f]*$"
    )


def _coverage_manifest_type(target, entrypoint, work_order):
    checks = tuple(
        create_model(
            f"ApprovedStatementCheck{ordinal}",
            __base__=AcceptanceCheck,
            source=(Literal[statement["source"]], ...),
        )
        for ordinal, statement in enumerate(work_order["statements"])
    )
    return create_model(
        "CoveredSourceManifest",
        __base__=_manifest_type(target, entrypoint),
        acceptance_checks=(tuple[checks], ...),
    )


class SourceText(_Output):
    """A complete file, preserved byte-for-byte after UTF-8 encoding."""

    content: str = Field(min_length=1, max_length=32768, pattern=r"^[^\x00-\x08\x0b-\x1f\x7f]*$")


class CallablePlannedFile(PlannedFile):
    interface: str = Field(
        min_length=3,
        max_length=400,
        pattern=r"^[^\x00-\x1f\x7f]*\([^\x00-\x1f\x7f]*\)[^\x00-\x1f\x7f]*$",
    )


def _selected_file(name, path, *, dependencies=(), media_types=("text/plain",), dom=False):
    """Pin policy-owned paths and dependency order in the provider's schema."""
    dependency_type = list[Literal[dependencies]] if dependencies else list[str]
    return create_model(
        name,
        __base__=PlannedFile if dom else CallablePlannedFile,
        normalized_path=(Literal[path], ...),
        media_type=(Literal[media_types], ...),
        depends_on=(
            dependency_type,
            Field(min_length=len(dependencies), max_length=len(dependencies)),
        ),
    )


def _manifest_type(target, entrypoint):
    if target == "WEB_STATIC":
        javascript = ("text/javascript", "application/javascript")
        core = _selected_file("StaticCore", "app.js", media_types=javascript)
        tests = _selected_file(
            "StaticTests", "app.test.cjs", dependencies=("app.js",), media_types=javascript
        )
        page = _selected_file(
            "StaticPage",
            "index.html",
            dependencies=("app.js",),
            media_types=("text/html",),
            dom=True,
        )
        return create_model(
            "StaticSourceManifest", __base__=SourceManifest, files=(tuple[core, tests, page], ...)
        )
    if not entrypoint:
        return SourceManifest
    main_path = entrypoint["normalized_path"]
    test_name = PurePosixPath(main_path).stem + "Test" + PurePosixPath(main_path).suffix
    test_path = str(
        PurePosixPath(main_path.replace("src/main/", "src/test/", 1)).with_name(test_name)
    )
    main = _selected_file("JvmMain", main_path)
    tests = _selected_file(
        "JvmTests",
        test_path,
        dependencies=(main_path,),
    )
    return create_model(
        "JvmSourceManifest",
        __base__=SourceManifest,
        files=(tuple[main, tests], ...),
    )


def _jvm_entrypoint(context):
    target = context["target_selection"]["target"]
    if not target.startswith("JVM_") or not context.get("build_recipes"):
        return None
    text = "\n".join(context["build_recipes"].values())
    match = re.search(r'mainClass\s*(?::=\s*Some\(|=)\s*"([A-Za-z0-9_.]+)"', text)
    if match is None:
        raise ValueError("pinned JVM main class required")
    qualified = match.group(1)
    language, extension = {
        "JVM_JAVA": ("java", "java"),
        "JVM_KOTLIN": ("kotlin", "kt"),
        "JVM_SCALA": ("scala", "scala"),
    }[target]
    source_class = qualified.removesuffix("Kt") if language == "kotlin" else qualified
    return {
        "main_class": qualified,
        "package": source_class.rpartition(".")[0],
        "normalized_path": f"src/main/{language}/{source_class.replace('.', '/')}.{extension}",
    }


def _validate_dependencies(manifest):
    """Reject incomplete or forward dependencies before any source-file call."""
    paths = {file.normalized_path for file in manifest.files}
    completed = set()
    for file in manifest.files:
        dependencies = set(file.depends_on)
        if len(dependencies) != len(file.depends_on):
            raise ValueError("duplicate source dependency")
        if file.normalized_path in dependencies or not dependencies <= paths:
            raise ValueError("unknown or self-referential source dependency")
        if not dependencies <= completed:
            raise ValueError("source dependencies must precede their consumers")
        if (
            file.normalized_path in {"index.html", "app.test.cjs"}
            and "app.js" in paths
            and "app.js" not in dependencies
        ):
            raise ValueError("static consumers must depend on app.js")
        if file.normalized_path.startswith("src/test/") and not any(
            dependency.startswith("src/main/") for dependency in dependencies
        ):
            raise ValueError("JVM tests must depend on their implementation")
        completed.add(file.normalized_path)


def _validate_manifest(context, manifest):
    _validate_dependencies(manifest)
    placeholders = [
        SourceFile(normalized_path=f.normalized_path, content="", media_type=f.media_type)
        for f in manifest.files
    ]
    _validate_files(placeholders)
    # Reuse all path, pinned-file, language-root and entry-file checks before inference.
    build_source_binding(
        "jvm-source" if context["target_selection"]["target"].startswith("JVM") else "web-source",
        context,
        SourceOutput(rationale=manifest.rationale, files=placeholders),
    )
    if any(f.normalized_path.lower().endswith((".md", ".markdown")) for f in manifest.files):
        raise ValueError("documentation is outside source generation scope")
    entrypoint = _jvm_entrypoint(context)
    if entrypoint and entrypoint["normalized_path"] not in {
        f.normalized_path for f in manifest.files
    }:
        raise ValueError("manifest omits the pinned JVM entrypoint")
    paths = {f.normalized_path for f in manifest.files}
    target = context["target_selection"]["target"]
    if target == "WEB_STATIC" and not {"index.html", "app.js", "app.test.cjs"} <= paths:
        raise ValueError("static manifest requires entry, implementation and Node tests")
    if target.startswith("JVM_"):
        language, extension = {
            "JVM_JAVA": ("java", ".java"),
            "JVM_KOTLIN": ("kotlin", ".kt"),
            "JVM_SCALA": ("scala", ".scala"),
        }[target]
        if not any(p.startswith(f"src/test/{language}/") and p.endswith(extension) for p in paths):
            raise ValueError("JVM manifest requires tests in the selected language test root")


def _file_instruction(planned):
    suffix = PurePosixPath(planned.normalized_path).suffix.lower()
    language = {
        ".html": "HTML",
        ".js": "JavaScript",
        ".mjs": "JavaScript ES module",
        ".cjs": "CommonJS JavaScript",
        ".css": "CSS",
        ".json": "JSON",
        ".java": "Java",
        ".kt": "Kotlin",
        ".scala": "Scala",
        ".ts": "TypeScript",
    }.get(suffix, planned.media_type)
    instruction = (
        f"Write the file {planned.normalized_path} in {language}. "
        "The source_step.file in the input is the ONLY file to write; completed_files are read-only context. "
        "Do not repeat the HTML page when writing scripts, tests, JSON, CSS or JVM code. "
        "Implement the approved business statements repeated in work_order; read the complete implementation_contract for all remaining conditions and relationships. "
        "Implement every observable_postcondition in manifest.acceptance_checks through its public interface. "
        "A scenario's expected_outcome is required behavior, including any read-back or retrieval operation; returning an identifier alone does not implement retrieval. "
        "The example names in pinned build paths do not define the business requirements. "
    )
    if planned.normalized_path.startswith("src/test/") or ".test." in planned.normalized_path:
        instruction += (
            "Import the actual implementation, call its public interface and assert behavior. "
            "Exercise two successive valid operations on one service plus an invalid input; "
            "verify retained data, distinct identifiers when required, and rejection without corrupting prior state. "
        )
    return instruction


def _static_file_instruction(planned):
    suffix = PurePosixPath(planned.normalized_path).suffix.lower()
    if suffix == ".html":
        return (
            "Link app.js with a script src element so the actual page executes the implementation. "
            "Match its actual element IDs, field names and event bindings. "
        )
    if planned.normalized_path.endswith(".test.cjs"):
        return (
            "Use only require('node:test'), require('node:assert/strict') and require('./app.js'). "
            "Test exported pure functions. No DOM, jsdom, npm, eval or external library. "
        )
    if suffix in {".js", ".cjs"}:
        return (
            "Implement a testable business core with explicit state ownership, input validation and unique identifiers when required. Keep records across successive operations on the same service. A factory can return methods sharing one private store. Wire the browser to the same core. "
            "Export the public functions inside if (typeof module !== 'undefined') for Node tests. "
            "Use module.exports = { ... } in that guard. This is a classic browser script: never use import or export statements. "
            "Put every document/window reference inside if (typeof document !== 'undefined') for the browser. "
        )
    return ""


def _jvm_file_instruction(planned, entrypoint, target):
    if not entrypoint:
        return ""
    instruction = (
        f"Declare package {entrypoint['package']} in this file, including test files. "
        "Keep this program small and self-contained. Define every referenced domain type in a planned file. "
        "Implement the requirements, including observable state changes and return values. Keep stored domain records across successive operations on the same service. Derive returned identifiers from those records. Validate required inputs before changing state. No empty methods or TODO placeholders. "
        "Names in build_recipes identify the launcher only, not the requested business behavior. "
        "Implement dependencies before files which import them. Do not duplicate class/object declarations. "
        "Put mutable domain state in a service instance; tests create a fresh instance instead of sharing global state. "
        "Expose data needed by callers through accessible public return types and methods. Tests must not access private fields or private nested types. "
        "This profile runs a console program: express the selected interaction through the CLI, without HTML rendering. "
    )
    if planned.normalized_path == entrypoint["normalized_path"]:
        instruction += (
            "The launcher supplies no command-line arguments. Demonstrate the use case with a valid sample input, "
            "print the result and terminate successfully. Do not read interactive input or start a server. "
        )
        if target == "JVM_KOTLIN":
            instruction += (
                "In Main.kt define a top-level fun main() in the exact package. "
                "Do not declare a class or object named MainKt: the compiler generates that name. "
            )
        elif target == "JVM_SCALA":
            instruction += "Define object Main with def main(args: Array[String]): Unit. Do not use extends App. "
        elif target == "JVM_JAVA":
            instruction += (
                "Define public class Main with public static void main(String[] args). "
                "Supporting types belong in this file as nested types of Main or package-private types. "
            )
    elif planned.normalized_path.startswith("src/test/"):
        instruction += "Write two compact behavioral tests: one successful input and one invalid input. Assert actual return values or changed state, never a constant or assertTrue(true). Include every required assertion import. "
        if target == "JVM_SCALA":
            instruction += "The exact test import is import munit.FunSuite, never org.scalameta.munit.FunSuite. Extend FunSuite and use test blocks, assertEquals and intercept. "
        elif target == "JVM_KOTLIN":
            instruction += "Use kotlin.test.Test, kotlin.test.assertEquals and kotlin.test.assertFailsWith. println is built in and needs no import. "
        elif target == "JVM_JAVA":
            instruction += "Use import org.junit.jupiter.api.Test; and import static org.junit.jupiter.api.Assertions.*; for the pinned JUnit 5 API. "
    return instruction


def _validate_file_language(item):
    if len(item.content.encode("utf-8")) > 32768:
        raise ValueError("source file exceeds the UTF-8 byte budget")
    suffix = PurePosixPath(item.normalized_path).suffix.lower()
    if suffix == ".json":
        json.loads(item.content)
    if suffix in {
        ".js",
        ".cjs",
        ".mjs",
        ".ts",
        ".java",
        ".kt",
        ".scala",
        ".css",
    } and item.content.lstrip().lower().startswith(("<!doctype html", "<html")):
        raise ValueError("HTML supplied for a non-HTML source file")


async def generate_source_files(generator, *, task, context):
    if task not in {"web-source", "jvm-source"}:
        raise ValueError("initial source task required")
    parent = current_proposal_evidence()
    if parent is None:
        raise ProposalEvidenceError("SOURCE_PARENT_EVIDENCE_REQUIRED")
    semantic = implementation_contract(context)
    work_order = implementation_work_order(semantic)
    root_context = {
        **context,
        "generation_protocol": PROTOCOL,
        "manifest_contract": MANIFEST_CONTRACT,
        "work_order": work_order,
    }
    for name, content in semantic["content"].items():
        root_context[name] = {
            **context[name],
            "view": IMPLEMENTATION_VIEW,
            "content": content,
        }
    target = context["target_selection"]["target"]
    entrypoint = _jvm_entrypoint(context)
    if entrypoint:
        root_context["entrypoint_contract"] = entrypoint
    if len(canonical_json(wire_value(root_context)).encode()) > MAX_CONTEXT_BYTES:
        raise ProposalGenerationError("SOURCE_CONTEXT_LIMIT_EXCEEDED")
    stack = (
        "Use the exact JVM package and main class from build_recipes; plan a small implementation and a test using only pinned dependencies."
        if task.startswith("jvm")
        else "For WEB_STATIC plan root index.html, app.js and a Node test file, optionally styles.css. Use vanilla browser APIs and no external dependencies. Other Web targets must include consistent package.json and package-lock.json in their required roots."
    )
    if target == "WEB_STATIC":
        stack = (
            "This request selects WEB_STATIC. The HTML entry MUST be exactly index.html at the project root. "
            "Never public/index.html or src/index.html. Use app.js with a pure CommonJS-exportable core and "
            "a document-existence guard for browser bindings, plus app.test.cjs using node:test and node:assert/strict. "
            "Plan exactly three files: app.js first, app.test.cjs second and index.html last. Put any CSS in the HTML. "
            "The HTML must load app.js with a script src element. No npm, jsdom, browser-only test framework, or external dependencies."
        )
    elif entrypoint:
        stack += (
            f" The manifest MUST include {entrypoint['normalized_path']} with package {entrypoint['package']}. "
            f"The pinned launcher invokes {entrypoint['main_class']}. Implement a finite CLI demonstration "
            "of the core use case, then exit; do not wait for interactive input or start a server. "
            "Use text/plain media_type for every JVM file. Plan exactly two files from the schema: "
            "the main file containing the entrypoint and the complete business service, then its test file. "
            "Put related domain types in the main file. Do not create extra command, query, UI or repository files."
        )
    manifest = await generator.generate(
        task=task,
        context=root_context,
        output_type=_coverage_manifest_type(target, entrypoint, work_order),
        max_output_tokens=MANIFEST_BUDGET,
        instruction="Plan the business behavior in work_order, using the complete approved artifacts for all conditions. Pinned example package names are launcher metadata, not the requested application. "
        "First fill behavior_plan with the actual inputs and validation, state ownership and lifetime, and observable outputs required by work_order. A plan is a proposal, not evidence that behavior exists. "
        "For EACH work_order statement, fill the corresponding acceptance_checks entry with the callable public interface and observable postcondition that satisfies it. "
        "Include scenario expected_outcome as well as acceptance criteria. If an outcome requires retrieval, expose a read method returning the stored data, not just an identifier. "
        "A required field in the approved design requires validation before changing state; include its invalid-input postcondition. "
        "Then plan file names, responsibilities and exact public interfaces that implement that behavior. No source code. "
        "Rationale and each purpose must be one short sentence, preferably under 80 characters. "
        "Define exact callable signatures, return types and shared state ownership in interface, not file names. List project files imported or consumed in depends_on; use [] for independent files. Order dependencies before consumers. Tests depend on their actual implementation, and HTML depends on its script. "
        "For executable files interface contains real function or constructor signatures with parentheses; for HTML list concrete DOM IDs after DOM:. Never copy architecture labels as interfaces. Every normalized_path is a relative POSIX path, without a leading slash, drive letter or parent traversal. "
        "Use at most 8 small files, normally 3 or 4. Keep each file compact and complete, normally 25-70 readable lines. "
        "Include an independently executable test. Never generate fixed_files or documentation. "
        + stack,
    )
    _validate_manifest(context, manifest)
    # Tuple schemas constrain each position; the evidence protocol remains a JSON array.
    manifest_snapshot = manifest.model_dump(mode="json")
    manifest_hash = snapshot_content_hash(manifest_snapshot)
    files, steps = [], []
    for ordinal, planned in enumerate(manifest.files, 1):
        step = {
            "parent_generation_id": str(parent.request.request_id),
            "parent_request_hash": parent.request.content_hash,
            "ordinal": ordinal,
            "manifest_hash": manifest_hash,
            "file": planned.model_dump(),
        }
        child_context = {
            "project_id": context["project_id"],
            "generation_protocol": PROTOCOL,
            "source_step": step,
            "target_selection": context["target_selection"],
            "implementation_contract": semantic,
            "manifest": manifest_snapshot,
            "build_recipes": context.get("build_recipes", {}),
            "entrypoint_contract": entrypoint,
            "completed_files": [
                {"normalized_path": f.normalized_path, "content": f.content} for f in files
            ],
            "work_order": work_order,
        }
        if len(canonical_json(wire_value(child_context)).encode()) > MAX_CONTEXT_BYTES:
            raise ProposalGenerationError("SOURCE_FILE_CONTEXT_LIMIT_EXCEEDED")
        with child_proposal_evidence() as child:
            try:
                output = await generator.generate(
                    task=task,
                    context=child_context,
                    output_type=SourceText,
                    max_output_tokens=FILE_BUDGET,
                    instruction=_file_instruction(planned)
                    + (_static_file_instruction(planned) if target == "WEB_STATIC" else "")
                    + _jvm_file_instruction(planned, entrypoint, target)
                    + "Return one JSON object with a content string containing the complete source file. "
                    "Use escaped newline characters inside that JSON string. Keep every source-language comma, "
                    "semicolon, quote and brace in the content. Preserve readable source formatting. "
                    "Match the actual exported methods and types in completed_files; never invent an import. "
                    "Write only this file. No Markdown fences, prose or placeholders. "
                    "Use only pinned dependencies and check actual behavior in tests.",
                )
                item = SourceFile(
                    normalized_path=planned.normalized_path,
                    media_type=planned.media_type,
                    content=output.content,
                )
                _validate_files([item], task=task)
                _validate_file_language(item)
                await child.event("ADAPTER_ACCEPTED", {"source_file": item.model_dump()})
                await child.event("APPLICATION_RESULT", {"status": "SOURCE_FILE_GENERATED"})
                steps.append(
                    {
                        "generation_id": str(child.request.request_id),
                        "request_hash": child.request.content_hash,
                        "ordinal": ordinal,
                        "file": file_entry(
                            item.normalized_path, item.content.encode(), item.media_type
                        ),
                    }
                )
                files.append(item)
            except BaseException as error:
                if not isinstance(error, ProposalEvidenceError):
                    if "ADAPTER_ACCEPTED" not in child.observed_events:
                        await child.event(
                            "ADAPTER_REJECTED",
                            {"code": getattr(error, "code", type(error).__name__)},
                        )
                    await child.event(
                        "APPLICATION_RESULT",
                        {"status": "FAILED", "code": getattr(error, "code", type(error).__name__)},
                    )
                raise
    output = SourceOutput(rationale=manifest.rationale, files=files)
    return SourceProposal(
        kind=task.upper().replace("-", "_"),
        output=output,
        source_binding=build_source_binding(task, context, output),
        generation_steps=tuple(steps),
    )
