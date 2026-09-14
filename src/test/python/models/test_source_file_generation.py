"""Synthetic multi-call responses test lineage and failure boundaries, not code quality."""

import asyncio
import json
from uuid import UUID, uuid4

import pytest

from orchestwin.models.proposal_evidence import ProposalEvidenceError
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.source_file_generation import FILE_BUDGET, MANIFEST_BUDGET
from orchestwin.models.source_proposals import ModelSourceProposalAdapter
from src.test.python.models.test_proposal_evidence import Command, MemoryEvidence, audited_generator
from src.test.python.models.test_source_proposals import context, output


def source_sequence_generator(tmp_path, payload, *, mutate=None):
    generator, transport = audited_generator(tmp_path, {})
    post = transport.post_json

    async def sequential(**kwargs):
        ctx = json.loads(kwargs["payload"]["messages"][1]["content"])["context"]
        step = ctx.get("source_step")
        if step:
            item = payload["files"][step["ordinal"] - 1]
            value = {"content": item["content"]}
        else:
            value = {
                "behavior_plan": {
                    "inputs_and_validation": "Use the synthetic fixture input.",
                    "state_and_lifetime": "The synthetic fixture has no mutable state.",
                    "observable_outputs": "Return the fixture value.",
                },
                "rationale": payload["rationale"],
                "files": [
                    {
                        "normalized_path": f["normalized_path"],
                        "media_type": f["media_type"],
                        "purpose": "Synthetic file purpose.",
                        "interface": "value(): object",
                        "depends_on": [
                            item["normalized_path"]
                            for item in payload["files"][:index]
                            if f["normalized_path"] not in {"app.test.cjs", "index.html"}
                            or item["normalized_path"] == "app.js"
                        ],
                    }
                    for index, f in enumerate(payload["files"])
                ],
            }
        transport.output = mutate(ctx, value) if mutate else value
        return await post(**kwargs)

    transport.post_json = sequential
    return generator, transport


def execute(generator, ctx, store):
    adapter = ModelSourceProposalAdapter(generator)
    task = "jvm-source" if ctx["target_selection"]["target"].startswith("JVM") else "web-source"
    return asyncio.run(
        Command(store, lambda: adapter.propose_files(task=task, context=ctx)).run(
            owner_user_id=uuid4(), project_id=UUID(ctx["project_id"])
        )
    )


def complete_output():
    payload = output()
    payload["files"].extend(
        [
            {
                "normalized_path": "app.js",
                "media_type": "text/javascript",
                "content": "exports.value = 3;",
            },
            {
                "normalized_path": "app.test.cjs",
                "media_type": "text/javascript",
                "content": "require('node:assert/strict').equal(require('./app.js').value, 3);",
            },
        ]
    )
    payload["files"] = payload["files"][1:] + payload["files"][:1]
    return payload


def test_files_have_separate_requests_exact_bytes_and_parent_links(tmp_path):
    ctx, payload, store = context(), complete_output(), MemoryEvidence()
    payload["files"][0]["content"] = 'const label = "è";\nconst s = "\\n";'
    generator, transport = source_sequence_generator(tmp_path, payload)
    result = execute(generator, ctx, store)
    assert len(transport.calls) == len(store.requests) == 4
    parent, *children = store.requests
    assert [c["payload"]["max_tokens"] for c in transport.calls] == [
        MANIFEST_BUDGET,
        FILE_BUDGET,
        FILE_BUDGET,
        FILE_BUDGET,
    ]
    assert result.output.files[0].content == payload["files"][0]["content"]
    assert [s["generation_id"] for s in result.generation_steps] == list(map(str, children))
    for ordinal, child in enumerate(children, 1):
        request = store.requests[child][0]
        child_ctx = json.loads(request.input_payload_json)["context"]
        assert child_ctx["manifest"]["behavior_plan"]["observable_outputs"] == (
            "Return the fixture value."
        )
        assert child_ctx["source_step"]["parent_generation_id"] == str(parent)
        assert child_ctx["source_step"]["ordinal"] == ordinal
        assert len(child_ctx["completed_files"]) == ordinal - 1
        assert store.events[child][-1][1]["status"] == "SOURCE_FILE_GENERATED"
    assert store.events[parent][-1][0] == "APPLICATION_RESULT"


@pytest.mark.parametrize(
    "failure",
    [
        "manifest_path",
        "too_many",
        "carriage_return",
        "line_control",
        "content_large",
        "extra",
        "second_file",
    ],
)
def test_failed_manifest_or_file_never_produces_accepted_parent(tmp_path, failure):
    ctx, payload, store = context(), complete_output(), MemoryEvidence()

    def mutate(ctx, value):
        step = ctx.get("source_step")
        if not step:
            if failure == "manifest_path":
                value["files"][0]["normalized_path"] = "../index.html"
            if failure == "too_many":
                value["files"] *= 5
        elif failure == "carriage_return":
            value["content"] = "one\rtwo"
        elif failure == "line_control":
            value["content"] = "\x01"
        elif failure == "content_large":
            value["content"] = "x" * 32769
        elif failure == "extra":
            value["approved"] = True
        elif failure == "second_file" and step["ordinal"] == 2:
            value["content"] = ""
        return value

    generator, _ = source_sequence_generator(tmp_path, payload, mutate=mutate)
    with pytest.raises(ProposalGenerationError):
        execute(generator, ctx, store)
    parent = next(iter(store.requests))
    kinds = [kind for kind, _, _ in store.events[parent]]
    assert "ADAPTER_REJECTED" in kinds and "ADAPTER_ACCEPTED" not in kinds
    assert store.events[parent][-1][1]["status"] == "FAILED"
    if failure == "second_file":
        assert len(store.requests) == 3
        assert store.events[list(store.requests)[1]][-1][1]["status"] == "SOURCE_FILE_GENERATED"


def test_file_generation_requires_auditing(tmp_path):
    generator, _ = source_sequence_generator(tmp_path, output())
    with pytest.raises(ProposalEvidenceError):
        asyncio.run(
            ModelSourceProposalAdapter(generator).propose_files(
                task="web-source", context=context()
            )
        )


@pytest.mark.parametrize("path", ["app.js", "app.test.cjs", "data.json"])
def test_html_is_not_accepted_as_javascript_or_json(tmp_path, path):
    payload = complete_output()
    payload["files"] = [f for f in payload["files"] if f["normalized_path"] != path]
    payload["files"].append(
        {
            "normalized_path": path,
            "media_type": "text/plain",
            "content": "<!DOCTYPE html><html></html>",
        }
    )
    store = MemoryEvidence()
    generator, _ = source_sequence_generator(tmp_path, payload)
    with pytest.raises(ProposalGenerationError):
        execute(generator, context(), store)
    parent = next(iter(store.requests))
    assert "ADAPTER_ACCEPTED" not in {kind for kind, _, _ in store.events[parent]}


@pytest.mark.parametrize(
    "target,recipe,path,package",
    [
        ("JVM_JAVA", 'mainClass = "org.example.Main"', "java/org/example/Main.java", "org.example"),
        (
            "JVM_KOTLIN",
            'mainClass = "org.example.MainKt"',
            "kotlin/org/example/Main.kt",
            "org.example",
        ),
        (
            "JVM_SCALA",
            'mainClass := Some("org.example.Main")',
            "scala/org/example/Main.scala",
            "org.example",
        ),
    ],
)
def test_pinned_entrypoint_is_required_before_file_calls(tmp_path, target, recipe, path, package):
    ctx = context("jvm-source", target)
    ctx["build_recipes"] = {"synthetic-build": recipe}
    payload = output("jvm-source", "src/main/" + path)
    payload["files"].append(
        {
            "normalized_path": "src/test/" + path.replace("Main.", "MainTest."),
            "media_type": "text/plain",
            "content": "// Synthetic test source.",
        }
    )
    store = MemoryEvidence()
    generator, transport = source_sequence_generator(tmp_path, payload)
    execute(generator, ctx, store)
    parent_context = json.loads(transport.calls[0]["payload"]["messages"][1]["content"])["context"]
    assert parent_context["entrypoint_contract"]["package"] == package
    assert parent_context["entrypoint_contract"]["normalized_path"] == "src/main/" + path
    child_call = transport.calls[1]["payload"]["messages"]
    assert "src/main/" + path in child_call[0]["content"]
    assert (
        json.loads(child_call[1]["content"])["context"]["entrypoint_contract"]
        == parent_context["entrypoint_contract"]
    )

    payload["files"][0]["normalized_path"] = "src/main/" + path.replace("Main.", "Other.")
    rejected_directory = tmp_path / "rejected"
    rejected_directory.mkdir()
    generator, transport = source_sequence_generator(rejected_directory, payload)
    with pytest.raises(ProposalGenerationError):
        execute(generator, ctx, MemoryEvidence())
    assert len(transport.calls) == 1


@pytest.mark.parametrize("path", ["app.js", "app.test.cjs", "index.html"])
def test_incomplete_static_manifest_is_rejected_before_file_calls(tmp_path, path):
    payload = complete_output()
    payload["files"] = [f for f in payload["files"] if f["normalized_path"] != path]
    generator, transport = source_sequence_generator(tmp_path, payload)
    with pytest.raises(ProposalGenerationError):
        execute(generator, context(), MemoryEvidence())
    assert len(transport.calls) == 1


@pytest.mark.parametrize("failure", ["unknown", "self", "forward", "duplicate", "omitted"])
def test_invalid_dependency_plan_is_rejected_before_any_file_call(tmp_path, failure):
    def mutate(ctx, value):
        if ctx.get("source_step"):
            raise AssertionError("Invalid dependency plan reached file generation")
        files = value["files"]
        if failure == "unknown":
            files[0]["depends_on"] = ["absent.js"]
        elif failure == "self":
            files[0]["depends_on"] = [files[0]["normalized_path"]]
        elif failure == "forward":
            files[0]["depends_on"] = [files[-1]["normalized_path"]]
        elif failure == "duplicate":
            files[1]["depends_on"] *= 2
        else:
            files[1]["depends_on"] = []
        return value

    generator, transport = source_sequence_generator(tmp_path, complete_output(), mutate=mutate)
    with pytest.raises(ProposalGenerationError):
        execute(generator, context(), MemoryEvidence())
    assert len(transport.calls) == 1


@pytest.mark.parametrize("failure", ["duplicate_entrypoint", "test_before_implementation"])
def test_jvm_manifest_cannot_use_both_slots_for_main_or_reverse_them(tmp_path, failure):
    ctx = context("jvm-source", "JVM_JAVA")
    ctx["build_recipes"] = {"synthetic-build": 'mainClass = "org.example.Main"'}
    payload = output("jvm-source", "src/main/java/org/example/Main.java")
    payload["files"].append(
        {
            "normalized_path": "src/test/java/org/example/MainTest.java",
            "media_type": "text/plain",
            "content": "// Synthetic persistence test.",
        }
    )
    if failure == "duplicate_entrypoint":
        payload["files"][1]["normalized_path"] = payload["files"][0]["normalized_path"]
    else:
        payload["files"].reverse()
    generator, transport = source_sequence_generator(tmp_path, payload)
    with pytest.raises(ProposalGenerationError):
        execute(generator, ctx, MemoryEvidence())
    assert len(transport.calls) == 1
