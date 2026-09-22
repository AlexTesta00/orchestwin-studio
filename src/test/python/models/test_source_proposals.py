"""Synthetic completions exercise source boundaries, never model quality."""

import asyncio
import hashlib
import json
from copy import deepcopy
from uuid import UUID, uuid4

import pytest

from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.source_assembly import assemble_static_module
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


@pytest.mark.parametrize("configured", [512, 8192])
def test_repair_reserves_context_without_raising_a_smaller_configured_output_limit(
    tmp_path, configured
):
    from uuid import UUID

    task = "jvm-repair"
    ctx = context(task)
    generator, _ = audited_generator(tmp_path, output(task))
    generator.configuration = generator.configuration.model_copy(
        update={"max_output_tokens": configured}
    )
    store = MemoryEvidence()
    operation = Command(
        store, lambda: ModelSourceProposalAdapter(generator).propose(task=task, context=ctx)
    )
    asyncio.run(operation.run(owner_user_id=uuid4(), project_id=UUID(ctx["project_id"])))
    request = next(iter(store.requests.values()))[0]
    assert request.max_output_tokens == min(4096, configured)
    assert json.loads(request.input_payload_json)["context"] == ctx


@pytest.mark.parametrize("task", ["jvm-repair", "web-repair"])
def test_repository_jvm_mime_is_allowed_only_for_jvm_source_bytes(tmp_path, task):
    payload = output(task)
    payload["changes"][0]["media_type"] = "application/octet-stream"
    if task == "web-repair":
        with pytest.raises(ProposalGenerationError, match="INVALID_PROVIDER_OUTPUT"):
            run_proposal(tmp_path, task, payload)
    else:
        result, _, _ = run_proposal(tmp_path, task, payload)
        assert result.output.changes[0].content == payload["changes"][0]["content"]
        assert result.source_binding["changes"][0]["media_type"] == "application/octet-stream"


@pytest.mark.parametrize("invalid", ["nul", "path", "fixed"])
def test_jvm_octet_stream_metadata_does_not_bypass_source_guards(tmp_path, invalid):
    task = "jvm-repair"
    payload, ctx = output(task), context(task)
    item = payload["changes"][0]
    item["media_type"] = "application/octet-stream"
    if invalid == "nul":
        item["content"] += "\x00"
    elif invalid == "path":
        item["normalized_path"] = "../Main.java"
    else:
        ctx["fixed_files"] = deepcopy(ctx["base_files"])
    with pytest.raises(ProposalGenerationError, match="INVALID_PROVIDER_OUTPUT"):
        run_proposal(tmp_path, task, payload, ctx)


@pytest.mark.parametrize(
    "target,folder,extension",
    [
        ("WEB_STATIC", None, ".cjs"),
        ("JVM_JAVA", "java", ".java"),
        ("JVM_KOTLIN", "kotlin", ".kt"),
        ("JVM_SCALA", "scala", ".scala"),
    ],
)
@pytest.mark.parametrize("replacement", [False, True])
def test_repair_cannot_drop_all_tests_but_can_rename_a_test(
    tmp_path, target, folder, extension, replacement
):
    task = "jvm-repair" if folder else "web-repair"
    ctx = context(task, target)
    if folder:
        ctx["base_files"] = [file_entry(f"src/main/{folder}/Main{extension}", b"old", "text/plain")]
    path = f"src/test/{folder}/OriginalTest{extension}" if folder else "app.test.cjs"
    renamed = f"src/test/{folder}/RenamedTest{extension}" if folder else "renamed.test.cjs"
    ctx["base_files"].append(file_entry(path, b"old tests", "text/plain"))
    changes = [
        {"normalized_path": path, "operation": "DELETE", "content": None, "media_type": None}
    ]
    if replacement:
        changes.append(
            {
                "normalized_path": renamed,
                "operation": "ADD",
                "content": "// Synthetic source; this test verifies proposal admission only.",
                "media_type": "text/plain",
            }
        )
    payload = {"rationale": "Repair the test source.", "changes": changes}
    if replacement:
        result, _, _ = run_proposal(tmp_path, task, payload, ctx)
        assert len(result.source_binding["changes"]) == 2
    else:
        with pytest.raises(ProposalGenerationError, match="INVALID_PROVIDER_OUTPUT"):
            run_proposal(tmp_path, task, payload, ctx)


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
    ctx["unexpectedly_large_artifact"] = "x" * 131073
    with pytest.raises(ProposalGenerationError, match="SOURCE_CONTEXT_LIMIT_EXCEEDED"):
        run_proposal(tmp_path, "web-source", output(), ctx)


def test_unchanged_replacement_beside_a_real_change_is_dropped_not_rejected(tmp_path):
    task = "web-repair"
    ctx = context(task)
    ctx["base_files"].append(file_entry("app.test.cjs", b"old tests", "text/plain"))
    payload = output(task)
    payload["changes"].append(
        {
            "normalized_path": "app.test.cjs",
            "operation": "REPLACE",
            "content": "old tests",
            "media_type": "text/plain",
        }
    )
    result, _, _ = run_proposal(tmp_path, task, payload, ctx)
    assert [item["normalized_path"] for item in result.source_binding["changes"]] == ["index.html"]


STATEFUL_PARTS = {
    "shared_state": [{"kind": "const", "name": "items", "initializer": "[]"}],
    "private_helpers": "",
    "functions": [
        {
            "name": "addItem",
            "parameters": "name",
            "body": "  items.push(name);\n  return { ok: true, count: items.length };",
        }
    ],
    "browser_setup": "    document.title = String(addItem('x').count);",
}
BASE_APP = assemble_static_module(STATEFUL_PARTS)
BASE_TEST = (
    "const test = require('node:test');\n"
    "const assert = require('node:assert/strict');\n"
    "const { addItem, resetSharedState } = require('./app.js');\n"
    "test.beforeEach(resetSharedState);\n"
    "test('adds', () => { assert.equal(addItem('a').count, 1); });\n"
)


def app_with(body):
    return assemble_static_module(
        {**STATEFUL_PARTS, "functions": [{**STATEFUL_PARTS["functions"][0], "body": body}]}
    )


def static_repair_context():
    ctx = context("web-repair")
    files = [
        ("index.html", "<h1>Base</h1>", "text/html"),
        ("app.js", BASE_APP, "text/javascript"),
        ("app.test.cjs", BASE_TEST, "text/javascript"),
    ]
    ctx["base_files"] = [file_entry(p, content.encode(), media) for p, content, media in files]
    ctx["source_files"] = [
        {"normalized_path": p, "content": content, "media_type": media}
        for p, content, media in files
    ]
    return ctx


def repair_change(path, content, media_type="text/javascript"):
    return {
        "rationale": "Repair the recorded failure.",
        "changes": [
            {
                "normalized_path": path,
                "operation": "REPLACE",
                "content": content,
                "media_type": media_type,
            }
        ],
    }


def sequence_generator(tmp_path, payloads):
    generator, transport = audited_generator(tmp_path, payloads[0])
    post = transport.post_json

    async def sequential(**kwargs):
        transport.output = payloads[min(len(transport.calls), len(payloads) - 1)]
        return await post(**kwargs)

    transport.post_json = sequential
    return generator, transport


def run_static_repair(tmp_path, ctx, payloads):
    generator, transport = sequence_generator(tmp_path, payloads)
    adapter = ModelSourceProposalAdapter(generator)
    store = MemoryEvidence()
    operation = Command(store, lambda: adapter.propose(task="web-repair", context=ctx))
    result = asyncio.run(operation.run(owner_user_id=uuid4(), project_id=UUID(ctx["project_id"])))
    return result, store, transport


def outcome_events(store, generation_id):
    return [
        (kind, data.get("code"))
        for kind, data, _ in store.events[generation_id]
        if kind in {"ADAPTER_REJECTED", "ADAPTER_ACCEPTED", "APPLICATION_RESULT"}
    ]


def test_static_repair_is_validated_and_retried_once_with_the_diagnostic(tmp_path):
    ctx = static_repair_context()
    broken = app_with("  document.title = name;\n  items.push(name);\n  return { ok: true };")
    fixed = app_with(
        "  items.push(String(name).trim());\n  return { ok: true, count: items.length };"
    )
    result, store, transport = run_static_repair(
        tmp_path, ctx, [repair_change("app.js", broken), repair_change("app.js", fixed)]
    )
    assert len(transport.calls) == 2
    rejected, accepted = store.requests
    assert outcome_events(store, rejected) == [
        ("ADAPTER_REJECTED", "SOURCE_JAVASCRIPT_SYNTAX_INVALID"),
        ("APPLICATION_RESULT", "SOURCE_JAVASCRIPT_SYNTAX_INVALID"),
    ]
    before = json.loads(store.requests[rejected][0].input_payload_json)["context"]
    retried = json.loads(store.requests[accepted][0].input_payload_json)["context"]
    assert retried.pop("repair_retry") == {
        "attempt": 2,
        "previous_generation_id": str(rejected),
        "previous_request_hash": store.requests[rejected][0].content_hash,
        "code": "SOURCE_JAVASCRIPT_SYNTAX_INVALID",
    }
    assert retried == before
    feedback = json.loads(
        store.requests[accepted][0].system_instruction.split("SYNTAX_RETRY_FEEDBACK_JSON=", 1)[1]
    )
    assert feedback["diagnostic"]["reason"] == "MODULE_FUNCTION_TOUCHES_DOM"
    assert feedback["diagnostic"]["detail"] == "addItem uses document"
    assert "Return the complete file" in store.requests[accepted][0].system_instruction
    assert "never move page statements to module scope" in (
        store.requests[accepted][0].system_instruction
    )
    assert feedback["previous_source_sha256"] == hashlib.sha256(broken.encode()).hexdigest()
    assert outcome_events(store, accepted) == [
        ("ADAPTER_ACCEPTED", None),
        ("APPLICATION_RESULT", None),
    ]
    accepted_payload = next(
        data for kind, data, _ in store.events[accepted] if kind == "ADAPTER_ACCEPTED"
    )
    assert accepted_payload["related_generations"] == [
        {
            "role": "REJECTED_REPAIR_ATTEMPT",
            "generation_id": str(rejected),
            "request_hash": store.requests[rejected][0].content_hash,
            "code": "SOURCE_JAVASCRIPT_SYNTAX_INVALID",
        }
    ]
    assert result.source_binding["changes"][0]["content_sha256"] == (
        hashlib.sha256(fixed.encode()).hexdigest()
    )


def test_repeated_static_repair_failure_stops_after_one_retry(tmp_path):
    ctx = static_repair_context()
    broken = app_with("  document.title = name;\n  items.push(name);\n  return { ok: true };")
    generator, transport = sequence_generator(tmp_path, [repair_change("app.js", broken)])
    adapter = ModelSourceProposalAdapter(generator)
    store = MemoryEvidence()
    operation = Command(store, lambda: adapter.propose(task="web-repair", context=ctx))
    with pytest.raises(ProposalGenerationError, match="SOURCE_JAVASCRIPT_SYNTAX_INVALID"):
        asyncio.run(operation.run(owner_user_id=uuid4(), project_id=UUID(ctx["project_id"])))
    assert len(transport.calls) == 2
    assert len(store.requests) == 2
    for generation_id in store.requests:
        assert outcome_events(store, generation_id) == [
            ("ADAPTER_REJECTED", "SOURCE_JAVASCRIPT_SYNTAX_INVALID"),
            ("APPLICATION_RESULT", "SOURCE_JAVASCRIPT_SYNTAX_INVALID"),
        ]


@pytest.mark.parametrize(
    "path,content,reason,detail",
    [
        (
            "app.test.cjs",
            BASE_TEST.replace("test.beforeEach(resetSharedState);\n", ""),
            "NODE_TEST_MISSING_STATE_RESET",
            "resetSharedState",
        ),
        (
            "app.js",
            BASE_APP.replace(", resetSharedState };", " };"),
            "EXPORTS_REMOVED",
            "resetSharedState",
        ),
        (
            "app.js",
            BASE_APP[: -len("}\n")],
            "UNEXPECTED_END_OF_INPUT",
            None,
        ),
    ],
)
def test_static_repair_rejections_reach_the_retry_prompt(tmp_path, path, content, reason, detail):
    ctx = static_repair_context()
    generator, transport = sequence_generator(tmp_path, [repair_change(path, content)])
    adapter = ModelSourceProposalAdapter(generator)
    store = MemoryEvidence()
    operation = Command(store, lambda: adapter.propose(task="web-repair", context=ctx))
    with pytest.raises(ProposalGenerationError, match="SOURCE_JAVASCRIPT_SYNTAX_INVALID"):
        asyncio.run(operation.run(owner_user_id=uuid4(), project_id=UUID(ctx["project_id"])))
    assert len(transport.calls) == 2
    retry_request = list(store.requests.values())[1][0]
    feedback = json.loads(
        retry_request.system_instruction.split("SYNTAX_RETRY_FEEDBACK_JSON=", 1)[1]
    )
    assert feedback["diagnostic"]["reason"] == reason
    assert feedback["diagnostic"].get("detail") == detail


def test_stateless_repairs_and_other_files_need_no_reset_registration(tmp_path):
    ctx = static_repair_context()
    stateless = assemble_static_module({**STATEFUL_PARTS, "shared_state": []})
    ctx["source_files"][1]["content"] = stateless
    ctx["base_files"][1] = file_entry("app.js", stateless.encode(), "text/javascript")
    tests = BASE_TEST.replace("test.beforeEach(resetSharedState);\n", "")
    result, store, transport = run_static_repair(
        tmp_path, ctx, [repair_change("app.test.cjs", tests)]
    )
    assert len(transport.calls) == 1
    assert [item["normalized_path"] for item in result.source_binding["changes"]] == [
        "app.test.cjs"
    ]
    assert "related_generations" not in next(
        data
        for kind, data, _ in store.events[next(iter(store.requests))]
        if kind == "ADAPTER_ACCEPTED"
    )
