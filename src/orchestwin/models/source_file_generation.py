"""Bounded manifest then one audited, schema-constrained model call per file."""

import json
import re
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import Field

from orchestwin.models.proposal_evidence import (
    ProposalEvidenceError,
    child_proposal_evidence,
    current_proposal_evidence,
)
from orchestwin.models.proposal_generation import ProposalGenerationError, wire_value
from orchestwin.models.source_context import (
    IMPLEMENTATION_VIEW,
    implementation_contract,
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

PROTOCOL = "SOURCE_FILES_V1"
MANIFEST_BUDGET = 1000
FILE_BUDGET = 1100
MAX_FILES = 8
MANIFEST_CONTRACT = "SOURCE_MANIFEST_V2_TEST_REQUIRED"


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
    purpose: str = Field(min_length=1, max_length=120)
    interface: str = Field(min_length=1, max_length=200)


class SourceManifest(_Output):
    rationale: str = Field(min_length=1, max_length=160, pattern=r"^\S+( \S+)*$")
    files: list[PlannedFile] = Field(min_length=1, max_length=MAX_FILES)


class SourceLines(_Output):
    lines: list[Annotated[str, Field(max_length=240, pattern=r"^[^\x00-\x08\x0a-\x1f\x7f]*$")]] = (
        Field(
            min_length=1,
            max_length=60,
        )
    )


class StaticSourceManifest(SourceManifest):
    files: list[PlannedFile] = Field(min_length=1, max_length=4)


class JvmPlannedFile(PlannedFile):
    media_type: Literal["text/plain"]


class JvmSourceManifest(SourceManifest):
    files: list[JvmPlannedFile] = Field(min_length=1, max_length=4)


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


def _validate_manifest(context, manifest):
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
    return (
        f"Write the file {planned.normalized_path} in {language}. "
        "The source_step.file in the input is the ONLY file to write; completed_files are read-only context. "
        "Do not repeat the HTML page when writing scripts, tests, JSON, CSS or JVM code. "
        "For tests import the actual implementation, call its public interface and assert behavior. "
        "For browser scripts guard document access so the pure core can also run in Node. "
        "Use exact package and main class and only test libraries listed in build_recipes for JVM files. "
    )


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
            "Implement the business behavior as pure functions, including input validation and unique identifiers when required. "
            "Export the public functions inside if (typeof module !== 'undefined') for Node tests. "
            "Use module.exports = { ... } in that guard. This is a classic browser script: never use import or export statements. "
            "Put every document/window reference inside if (typeof document !== 'undefined') for the browser. "
        )
    return ""


def _jvm_file_instruction(planned, entrypoint, target):
    if not entrypoint:
        return ""
    instruction = (
        "Keep this program small and self-contained. Define every referenced domain type in a planned file. "
        "Implement the requirements, including observable state changes and return values. No empty methods or TODO placeholders. "
        "Names in build_recipes identify the launcher only, not the requested business behavior. "
        "Implement dependencies before files which import them. Do not duplicate class/object declarations. "
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
            instruction += "Define public class Main with public static void main(String[] args). "
    elif planned.normalized_path.startswith("src/test/"):
        instruction += "Write two compact behavioral tests: one successful input and one invalid input. Assert actual return values or changed state, never a constant or assertTrue(true). Include every required assertion import. "
        if target == "JVM_SCALA":
            instruction += "Use the pinned munit.FunSuite with test blocks, assertEquals and intercept; no ScalaTest imports. "
    return instruction


def _validate_file_language(item):
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
    root_context = {
        **context,
        "generation_protocol": PROTOCOL,
        "manifest_contract": MANIFEST_CONTRACT,
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
            "Plan app.js first, its test second and index.html last so consumers can use the actual implementation. "
            "The HTML must load app.js with a script src element. No npm, jsdom, browser-only test framework, or external dependencies."
        )
    elif entrypoint:
        stack += (
            f" The manifest MUST include {entrypoint['normalized_path']} with package {entrypoint['package']}. "
            f"The pinned launcher invokes {entrypoint['main_class']}. Implement a finite CLI demonstration "
            "of the core use case, then exit; do not wait for interactive input or start a server. "
            "Use text/plain media_type for every JVM file. Reserve one of the four files for unit tests under src/test/ in the selected language. "
            "Use at most four files: put related domain types together in the core file, then the main entry and real unit tests. "
            "Do not spend the file budget on separate command, query, factory or repository wrappers."
        )
    manifest = await generator.generate(
        task=task,
        context=root_context,
        output_type=StaticSourceManifest
        if target == "WEB_STATIC"
        else JvmSourceManifest
        if entrypoint
        else SourceManifest,
        max_output_tokens=MANIFEST_BUDGET,
        instruction="Plan only file names, responsibilities and exact public interfaces. No source code. "
        "Rationale and each purpose must be one short sentence, preferably under 80 characters. "
        "Define exact function signatures in interface, not file names. "
        "Every normalized_path is a relative POSIX path, without a leading slash, drive letter or parent traversal. "
        "Use at most 8 small files, normally 3 or 4. Each file must fit in 60 short lines. "
        "Include an independently executable test. Never generate fixed_files or documentation. "
        + stack,
    )
    _validate_manifest(context, manifest)
    manifest_hash = snapshot_content_hash(manifest.model_dump())
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
            "manifest": manifest.model_dump(),
            "build_recipes": context.get("build_recipes", {}),
            "entrypoint_contract": entrypoint,
            "completed_files": [
                {"normalized_path": f.normalized_path, "content": f.content} for f in files
            ],
        }
        if len(canonical_json(wire_value(child_context)).encode()) > MAX_CONTEXT_BYTES:
            raise ProposalGenerationError("SOURCE_FILE_CONTEXT_LIMIT_EXCEEDED")
        with child_proposal_evidence() as child:
            try:
                output = await generator.generate(
                    task=task,
                    context=child_context,
                    output_type=SourceLines,
                    max_output_tokens=FILE_BUDGET,
                    instruction=_file_instruction(planned)
                    + (_static_file_instruction(planned) if target == "WEB_STATIC" else "")
                    + _jvm_file_instruction(planned, entrypoint, target)
                    + "Return a JSON object with a lines array. Each element is one real source line, "
                    "without a newline character. Escape JSON once; do not put literal backslash-n between source statements. "
                    "The application joins lines with LF and adds one final LF. Write complete compact code, at most 60 lines, "
                    "prefer 10-35 lines. Match the manifest interfaces and completed files exactly. No prose or Markdown. "
                    "Use only pinned dependencies. Tests must check behavior, including at least one failure/edge case.",
                )
                item = SourceFile(
                    normalized_path=planned.normalized_path,
                    media_type=planned.media_type,
                    content="\n".join(output.lines) + "\n",
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
