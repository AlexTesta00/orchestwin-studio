"""Synthetic completions exercise source boundaries, never model quality."""

import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.source_proposals import ModelSourceProposalAdapter, file_entry
from src.test.python.models.test_proposal_evidence import Command, MemoryEvidence, audited_generator


def context(task="web-source", target="JVM_JAVA"):
    project = uuid4()
    jvm = task.startswith("jvm")
    path = "src/main/java/Main.java" if jvm else "index.html"
    return {
        "project_id": str(project),
        "target_selection": {"target": target if jvm else "WEB_STATIC"},
        "fixed_files": [],
        "provenance_references": [
            {
                "kind": "ARCHITECTURE",
                "reference_id": "architecture:synthetic",
                "version_number": 1,
                "content_hash": "a" * 64,
            }
        ],
        "execution_id": str(uuid4()),
        "execution_content_hash": "b" * 64,
        "base_revision": {"revision_id": str(uuid4()), "content_hash": "c" * 64},
        "failure_signature": {"digest": "d" * 64},
        "base_files": [file_entry(path, b"old", "text/plain" if jvm else "text/html")],
    }


def output(task="web-source", path=None):
    path = path or ("src/main/java/Main.java" if task.startswith("jvm") else "index.html")
    item = {
        "normalized_path": path,
        "content": "public class Main {}" if task.startswith("jvm") else "<h1>Updated</h1>",
        "media_type": "text/plain" if task.startswith("jvm") else "text/html",
    }
    if task.endswith("repair"):
        item["operation"] = "REPLACE"
    return {
        "rationale": "Implement the approved behavior.",
        "changes" if task.endswith("repair") else "files": [item],
    }


def run_proposal(tmp_path, task, payload, ctx=None):
    from uuid import UUID

    ctx = ctx or context(task)
    generator, transport = audited_generator(tmp_path, payload)
    adapter = ModelSourceProposalAdapter(generator)
    store = MemoryEvidence()
    operation = Command(store, lambda: adapter.propose(task=task, context=ctx))
    result = asyncio.run(operation.run(owner_user_id=uuid4(), project_id=UUID(ctx["project_id"])))
    return result, store, transport


@pytest.mark.parametrize("task", ["web-source", "web-repair", "jvm-source", "jvm-repair"])
def test_source_and_repair_use_real_transport_contract_and_record_exact_bytes(tmp_path, task):
    result, store, _ = run_proposal(tmp_path, task, output(task))
    request_id = next(iter(store.requests))
    request = store.requests[request_id][0]
    assert request.task_id == "proposal-" + task + "-v1" and request.temperature > 0
    events = {kind: payload for kind, payload, _ in store.events[request_id]}
    assert events["ADAPTER_ACCEPTED"]["source_binding"] == result.source_binding
    assert any(kind == "HTTP_RESPONSE" and raw for kind, _, raw in store.events[request_id])
    assert result.kind == task.upper().replace("-", "_")
    assert result.source_binding["changes" if task.endswith("repair") else "files"]


@pytest.mark.parametrize(
    "scenario",
    [
        "traversal",
        "credential",
        "collision",
        "ancestor",
        "nul",
        "extra",
        "empty",
        "fixed",
        "unknown_operation",
        "unchanged",
        "missing_base",
        "delete_content",
        "noncanonical_rationale",
        "wrong_entrypoint",
    ],
)
def test_invalid_source_output_is_rejected_without_fallback(tmp_path, scenario):
    task = (
        "web-repair"
        if scenario in {"unknown_operation", "unchanged", "missing_base", "delete_content"}
        else "web-source"
    )
    payload, ctx = output(task), context(task)
    key = "changes" if task.endswith("repair") else "files"
    if scenario == "traversal":
        payload[key][0]["normalized_path"] = "../escape.html"
    elif scenario == "credential":
        payload[key][0]["normalized_path"] = ".env"
    elif scenario == "collision":
        payload[key].append({**payload[key][0], "normalized_path": "INDEX.HTML"})
    elif scenario == "ancestor":
        payload[key].append({**payload[key][0], "normalized_path": "index.html/child"})
    elif scenario == "nul":
        payload[key][0]["content"] = "\x00"
    elif scenario == "extra":
        payload["approval_granted"] = True
    elif scenario == "empty":
        payload[key] = []
    elif scenario == "fixed":
        ctx["fixed_files"] = deepcopy(ctx["base_files"])
    elif scenario == "unknown_operation":
        payload[key][0]["operation"] = "EXECUTE"
    elif scenario == "unchanged":
        payload[key][0]["content"] = "old"
    elif scenario == "missing_base":
        payload[key][0]["normalized_path"] = "absent.html"
    elif scenario == "delete_content":
        payload[key][0]["operation"] = "DELETE"
    elif scenario == "noncanonical_rationale":
        payload["rationale"] = "multiline\nreason"
    elif scenario == "wrong_entrypoint":
        payload[key][0]["normalized_path"] = "src/main/resources/index.html"
    with pytest.raises(ProposalGenerationError, match="INVALID_PROVIDER_OUTPUT"):
        run_proposal(tmp_path, task, payload, ctx)


@pytest.mark.parametrize(
    "target,language", [("JVM_JAVA", "java"), ("JVM_KOTLIN", "kotlin"), ("JVM_SCALA", "scala")]
)
def test_jvm_generates_only_selected_language_roots_and_preserves_fixed_manifest(
    tmp_path, target, language
):
    ctx = context("jvm-source", target)
    ctx["fixed_files"] = [
        file_entry("wrapper.jar", b"verified-binary-fixture", "application/octet-stream")
    ]
    extension = {"java": "java", "kotlin": "kt", "scala": "scala"}[language]
    result, _, _ = run_proposal(
        tmp_path, "jvm-source", output("jvm-source", f"src/main/{language}/Main.{extension}"), ctx
    )
    assert ctx["fixed_files"][0] in result.source_binding["files"]
    other = tmp_path / "rejected"
    other.mkdir()
    with pytest.raises(ProposalGenerationError):
        run_proposal(other, "jvm-source", output("jvm-source", "build.gradle.kts"), ctx)


def test_oversized_context_never_calls_provider(tmp_path):
    ctx = context()
    ctx["unexpectedly_large_artifact"] = "x" * 32769
    with pytest.raises(ProposalGenerationError, match="SOURCE_CONTEXT_LIMIT_EXCEEDED"):
        run_proposal(tmp_path, "web-source", output(), ctx)
