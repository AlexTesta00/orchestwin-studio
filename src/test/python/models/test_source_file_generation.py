"""Synthetic multi-call responses test lineage and failure boundaries, not code quality."""

import asyncio
import hashlib
import json
from copy import deepcopy
from uuid import UUID, uuid4

import pytest

from orchestwin.models.proposal_evidence import ProposalEvidenceError
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.source_assembly import assemble_static_module
from orchestwin.models.source_file_generation import (
    FILE_BUDGET,
    MANIFEST_BUDGET,
    MANIFEST_CONTRACT,
    STATIC_RUNTIME_CONTRACT,
    SYNTAX_EXCERPT_CHARACTERS,
    _file_instruction,
    _manifest_observation_instruction,
    _syntax_retry_feedback,
    _syntax_retry_instruction,
)
from orchestwin.models.source_proposals import ModelSourceProposalAdapter
from orchestwin.models.source_syntax import SourceSyntaxError
from src.test.python.models.test_proposal_evidence import Command, MemoryEvidence, audited_generator
from src.test.python.models.test_source_proposals import context, output

APP_PARTS = {
    "shared_state": [],
    "private_helpers": "",
    "functions": [{"name": "value", "parameters": "", "body": "  return 3;"}],
    "browser_setup": "  document.title = String(value());",
}


def app_file(**overrides):
    parts = {**deepcopy(APP_PARTS), **overrides}
    return {
        "normalized_path": "app.js",
        "media_type": "text/javascript",
        "parts": parts,
        "content": assemble_static_module(parts),
    }


def broken(value, text):
    if "functions" in value:
        return {**value, "private_helpers": text}
    return {"content": text}


def source_sequence_generator(tmp_path, payload, *, mutate=None):
    generator, transport = audited_generator(tmp_path, {})
    post = transport.post_json

    async def sequential(**kwargs):
        ctx = json.loads(kwargs["payload"]["messages"][1]["content"])["context"]
        step = ctx.get("source_step")
        dom_first = "dom_reference" in ctx
        if step:
            item = next(
                f
                for f in payload["files"]
                if f["normalized_path"] == step["file"]["normalized_path"]
            )
            value = deepcopy(item["parts"]) if "parts" in item else {"content": item["content"]}
        else:
            planned_files = (
                sorted(
                    payload["files"],
                    key=lambda f: {"index.html": 0, "app.js": 1, "app.test.cjs": 2}[
                        f["normalized_path"]
                    ],
                )
                if dom_first
                else payload["files"]
            )
            value = {
                "acceptance_checks": [
                    {
                        "source": statement["source"],
                        "public_interface": "value(): object",
                        "observable_postcondition": "Return the synthetic fixture value.",
                    }
                    for statement in ctx["work_order"]["statements"]
                ],
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
                        "depends_on": (
                            {
                                "index.html": [],
                                "app.js": ["index.html"],
                                "app.test.cjs": ["app.js"],
                            }[f["normalized_path"]]
                            if dom_first
                            else [
                                item["normalized_path"]
                                for item in payload["files"][:index]
                                if f["normalized_path"] not in {"app.test.cjs", "index.html"}
                                or item["normalized_path"] == "app.js"
                            ]
                        ),
                    }
                    for index, f in enumerate(planned_files)
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
            app_file(),
            {
                "normalized_path": "app.test.cjs",
                "media_type": "text/javascript",
                "content": (
                    "const test = require('node:test');\n"
                    "const assert = require('node:assert/strict');\n"
                    "test('value', () => { assert.equal(require('./app.js').value(), 3); });"
                ),
            },
        ]
    )
    payload["files"] = payload["files"][1:] + payload["files"][:1]
    return payload


def test_files_have_separate_requests_exact_bytes_and_parent_links(tmp_path):
    ctx, payload, store = context(), complete_output(), MemoryEvidence()
    payload["files"][0] = app_file(
        shared_state=[
            {"kind": "const", "name": "label", "initializer": "'è'"},
            {"kind": "const", "name": "s", "initializer": "'-'"},
        ],
        functions=[{"name": "value", "parameters": "", "body": "  return label + s;"}],
    )
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
    assert (
        json.loads(store.requests[parent][0].input_payload_json)["context"]["runtime_contract"]
        == STATIC_RUNTIME_CONTRACT
    )
    assert [s["generation_id"] for s in result.generation_steps] == list(map(str, children))
    for ordinal, child in enumerate(children, 1):
        request = store.requests[child][0]
        child_ctx = json.loads(request.input_payload_json)["context"]
        assert child_ctx["runtime_contract"] == STATIC_RUNTIME_CONTRACT
        assert child_ctx["manifest"]["behavior_plan"]["observable_outputs"] == (
            "Return the fixture value."
        )
        assert child_ctx["source_step"]["parent_generation_id"] == str(parent)
        assert child_ctx["source_step"]["ordinal"] == ordinal
        assert [f["normalized_path"] for f in child_ctx["completed_files"]] == (
            [] if ordinal == 1 else ["app.js"]
        )
        assert store.events[child][-1][1]["status"] == "SOURCE_FILE_GENERATED"
    assert store.events[parent][-1][0] == "APPLICATION_RESULT"


def test_syntax_retry_retains_rejected_file_and_accepts_only_new_audited_bytes(tmp_path):
    ctx, payload, store = context(), complete_output(), MemoryEvidence()

    def mutate(child_context, value):
        if (
            child_context.get("source_step", {}).get("ordinal") == 2
            and "syntax_retry" not in child_context
        ):
            return {"content": "assert.equal(result, \\\n"}
        return value

    generator, transport = source_sequence_generator(tmp_path, payload, mutate=mutate)
    result = execute(generator, ctx, store)
    parent, core, rejected, accepted, html = store.requests
    assert len(transport.calls) == 5
    failed_events = store.events[rejected]
    assert [
        (kind, data.get("code"))
        for kind, data, _ in failed_events
        if kind in {"ADAPTER_REJECTED", "APPLICATION_RESULT"}
    ] == [
        ("ADAPTER_REJECTED", "SOURCE_JAVASCRIPT_SYNTAX_INVALID"),
        ("APPLICATION_RESULT", "SOURCE_JAVASCRIPT_SYNTAX_INVALID"),
    ]
    assert not any(kind == "ADAPTER_ACCEPTED" for kind, _, _ in failed_events)
    assert any(kind == "HTTP_RESPONSE" and raw for kind, _, raw in failed_events)
    before = json.loads(store.requests[rejected][0].input_payload_json)["context"]
    retried = json.loads(store.requests[accepted][0].input_payload_json)["context"]
    retry = retried.pop("syntax_retry")
    assert retried == before
    assert retry == {
        "attempt": 2,
        "previous_generation_id": str(rejected),
        "previous_request_hash": store.requests[rejected][0].content_hash,
        "code": "SOURCE_JAVASCRIPT_SYNTAX_INVALID",
    }
    feedback = json.loads(
        store.requests[accepted][0].system_instruction.split("SYNTAX_RETRY_FEEDBACK_JSON=", 1)[1]
    )
    previous_content = "assert.equal(result, \\\n"
    assert (
        feedback["previous_source_sha256"] == hashlib.sha256(previous_content.encode()).hexdigest()
    )
    assert feedback["source_excerpt"]["text"] == previous_content
    assert feedback["source_excerpt"]["truncated"] is False
    assert feedback["diagnostic"]["reason"] == "INVALID_OR_UNEXPECTED_TOKEN"
    assert feedback["diagnostic"]["line"] == 1
    assert [step["generation_id"] for step in result.generation_steps] == list(
        map(str, (core, accepted, html))
    )
    assert result.output.files[1].content == payload["files"][1]["content"]
    assert any(kind == "ADAPTER_ACCEPTED" for kind, _, _ in store.events[parent])


@pytest.mark.parametrize(
    "interface",
    [
        "export const calculate = (a, b) => { ... };",
        "import calculate from './app.js';",
        "function calculate(a, b) { return a + b; }",
    ],
)
def test_static_manifest_cannot_carry_module_declarations_or_implementation_bodies(
    tmp_path, interface
):
    def mutate(ctx, value):
        if "source_step" not in ctx:
            value["files"][0]["interface"] = interface
        return value

    store = MemoryEvidence()
    generator, transport = source_sequence_generator(tmp_path, complete_output(), mutate=mutate)
    with pytest.raises(ProposalGenerationError):
        execute(generator, context(), store)
    assert len(transport.calls) == 1
    assert not any(
        kind == "ADAPTER_ACCEPTED" for events in store.events.values() for kind, _, _ in events
    )


def test_module_mismatch_retry_receives_original_excerpt_and_exact_diagnostic(tmp_path):
    previous = "// Original Unicode: è\n\nexport const calculate = (a, b) => a + b;"
    assembled = assemble_static_module(broken(APP_PARTS, previous))

    def mutate(ctx, value):
        if ctx.get("source_step", {}).get("ordinal") == 1 and "syntax_retry" not in ctx:
            return broken(value, previous)
        return value

    store = MemoryEvidence()
    generator, _ = source_sequence_generator(tmp_path, complete_output(), mutate=mutate)
    execute(generator, context(), store)
    _parent, rejected, accepted, *_ = store.requests
    prompt = store.requests[accepted][0].system_instruction
    feedback = json.loads(prompt.split("SYNTAX_RETRY_FEEDBACK_JSON=", 1)[1])
    assert feedback["diagnostic"]["reason"] == "ES_MODULE_EXPORT_IN_CLASSIC_SCRIPT"
    assert feedback["diagnostic"]["line"] == 3
    assert feedback["source_excerpt"]["text"] == assembled
    assert feedback["previous_source_sha256"] == hashlib.sha256(assembled.encode()).hexdigest()
    assert "no ES-module import/export declarations" in prompt
    assert "SYNTAX_RETRY_FEEDBACK_JSON=" not in store.requests[rejected][0].system_instruction


def test_indented_unicode_source_feedback_roundtrips_in_a_valid_audited_retry_request(tmp_path):
    previous = (
        "// Original source with Unicode whitespace: \u00a0\n"
        "const test = require('node:test');\n"
        "const assert = require('node:assert/strict');\n"
        "test('sample', () => {\n"
        "    assert.equal(1, 1, 'L''errore');\n"
        "});\n"
    )

    def mutate(ctx, value):
        if ctx.get("source_step", {}).get("ordinal") == 2 and "syntax_retry" not in ctx:
            return {"content": previous}
        return value

    store = MemoryEvidence()
    generator, _ = source_sequence_generator(tmp_path, complete_output(), mutate=mutate)
    execute(generator, context(), store)
    _parent, _core, rejected, accepted, _html = store.requests
    prompt = store.requests[accepted][0].system_instruction
    assert " ".join(prompt.split()) == prompt
    feedback = json.loads(prompt.split("SYNTAX_RETRY_FEEDBACK_JSON=", 1)[1])
    assert feedback["source_excerpt"]["text"] == previous
    assert feedback["previous_source_sha256"] == hashlib.sha256(previous.encode()).hexdigest()
    assert feedback["diagnostic"]["line"] == 5
    assert feedback["source_excerpt"]["truncated"] is False
    assert store.events[rejected][-1][1]["status"] == "FAILED"
    assert store.events[accepted][-1][1]["status"] == "SOURCE_FILE_GENERATED"


def test_observable_browser_witnesses_do_not_require_fake_quality_functions(tmp_path):
    def mutate(ctx, value):
        if "source_step" not in ctx:
            for check in value["acceptance_checks"]:
                check["public_interface"] = (
                    "BROWSER: focus actual controls and inspect rendered state"
                )
        return value

    store = MemoryEvidence()
    generator, _ = source_sequence_generator(tmp_path, complete_output(), mutate=mutate)
    execute(generator, context(), store)
    parent, core, tests, _html = store.requests
    planning_prompt = store.requests[parent][0].system_instruction
    core_prompt = store.requests[core][0].system_instruction
    test_prompt = store.requests[tests][0].system_instruction
    assert "do not invent one callable per requirement" in planning_prompt
    assert "DOM control/event/visible property prefixed BROWSER:" in planning_prompt
    for prompt in (planning_prompt, core_prompt, test_prompt):
        assert "must come from real HTML, CSS" in prompt
        assert "independent browser observations" in prompt
        assert "isAccessible/isOffline-style functions returning true" in prompt
        assert "actual core and CLI behavior" not in prompt
    assert "switch the approved screen containers and preserve input state" in core_prompt
    assert "never SQL-style doubled apostrophes" in test_prompt
    assert "must remain unverified by this Node-only test" in test_prompt
    assert "callable public interface and observable postcondition" not in planning_prompt
    assert any(kind == "ADAPTER_ACCEPTED" for kind, _, _ in store.events[parent])


@pytest.mark.parametrize(
    "target", ["WEB_STATIC", "WEB_VUE", "WEB_NODE_EXPRESS", "WEB_PHP", "WEB_VUE_NODE"]
)
def test_all_web_profiles_preserve_browser_observation_scope(target):
    from types import SimpleNamespace

    planning = _manifest_observation_instruction(target)
    implementation = _file_instruction(
        SimpleNamespace(normalized_path="app.js", media_type="text/javascript"), target
    )
    assert "BROWSER:" in planning
    for prompt in (planning, implementation):
        assert "must come from real HTML, CSS" in prompt
        assert "independent browser observations" in prompt
        assert "isAccessible/isOffline-style functions returning true" in prompt
        assert "actual core and CLI behavior" not in prompt
        # CommonJS restrictions belong to the WEB_STATIC-specific instruction;
        # the general Web quality contract must not impose them on other stacks.
        assert "no ES-module import/export" not in prompt


def test_escaped_unicode_feedback_respects_the_normalized_request_text_budget(tmp_path):
    previous = "const value = (" + "\U0001f600" * 1000
    assembled = assemble_static_module(broken(APP_PARTS, previous))

    def mutate(ctx, value):
        if ctx.get("source_step", {}).get("ordinal") == 1 and "syntax_retry" not in ctx:
            return broken(value, previous)
        return value

    store = MemoryEvidence()
    generator, _ = source_sequence_generator(tmp_path, complete_output(), mutate=mutate)
    execute(generator, context(), store)
    _parent, _rejected, accepted, *_ = store.requests
    prompt = store.requests[accepted][0].system_instruction
    assert len(prompt) <= 16000 and " ".join(prompt.split()) == prompt
    feedback = json.loads(prompt.split("SYNTAX_RETRY_FEEDBACK_JSON=", 1)[1])
    excerpt = feedback["source_excerpt"]
    assert excerpt["text"] == assembled[excerpt["start_character"] : excerpt["end_character"]]
    assert excerpt["truncated"] and len(excerpt["text"]) <= SYNTAX_EXCERPT_CHARACTERS


def test_retry_excerpt_is_bounded_and_is_an_exact_slice_around_the_reported_line():
    from types import SimpleNamespace

    content = "// header è\n" * 100 + "export const value = 1;\n" + "// tail\n" * 2000
    feedback = _syntax_retry_feedback(
        SimpleNamespace(normalized_path="app.js", content=content),
        SourceSyntaxError(reason="ES_MODULE_EXPORT_IN_CLASSIC_SCRIPT", line=101),
    )
    excerpt = feedback["source_excerpt"]
    assert len(excerpt["text"]) <= SYNTAX_EXCERPT_CHARACTERS
    assert excerpt["text"] == content[excerpt["start_character"] : excerpt["end_character"]]
    assert "export const value" in excerpt["text"] and excerpt["truncated"]
    assert feedback["previous_source_characters"] == len(content)
    assert feedback["previous_source_sha256"] == hashlib.sha256(content.encode()).hexdigest()


def test_long_preceding_line_does_not_hide_the_actual_failure_from_retry_excerpt():
    from types import SimpleNamespace

    content = "//" + "x" * 8000 + "\nexport const value = 1;\n"
    feedback = _syntax_retry_feedback(
        SimpleNamespace(normalized_path="app.js", content=content),
        SourceSyntaxError(reason="ES_MODULE_EXPORT_IN_CLASSIC_SCRIPT", line=2),
    )
    excerpt = feedback["source_excerpt"]
    assert "export const value" in excerpt["text"]
    assert len(excerpt["text"]) <= SYNTAX_EXCERPT_CHARACTERS and excerpt["truncated"]
    assert excerpt["text"] == content[excerpt["start_character"] : excerpt["end_character"]]


def test_retry_guidance_preserves_es_modules_for_other_execution_targets():
    feedback = {"diagnostic": {"input_type": "module", "reason": "UNEXPECTED_END_OF_INPUT"}}
    instruction = _syntax_retry_instruction(feedback, "WEB_VITE")
    assert "no ES-module import/export declarations" not in instruction
    assert "valid ES-module declarations remain allowed" in instruction
    assert json.loads(instruction.split("SYNTAX_RETRY_FEEDBACK_JSON=", 1)[1]) == feedback
    assert "no ES-module import/export declarations" in _syntax_retry_instruction(
        feedback, "WEB_STATIC"
    )


def test_different_mockup_structure_is_rejected_before_file_acceptance(tmp_path):
    from src.test.python.models.test_source_design_contract import PROTOTYPE

    ctx, payload, store = context(), complete_output(), MemoryEvidence()
    ctx["design"] = {"content": {"prototype": PROTOTYPE}}
    generator, _ = source_sequence_generator(tmp_path, payload)
    with pytest.raises(ProposalGenerationError, match="SOURCE_DESIGN_STRUCTURE_MISMATCH"):
        execute(generator, ctx, store)
    html = list(store.requests)[-1]
    assert not any(kind == "ADAPTER_ACCEPTED" for kind, _, _ in store.events[html])
    assert any(
        kind == "ADAPTER_REJECTED" and data["code"] == "SOURCE_DESIGN_STRUCTURE_MISMATCH"
        for kind, data, _ in store.events[html]
    )


def test_repeated_syntax_failure_stops_after_one_retry_and_never_accepts_parent(tmp_path):
    store = MemoryEvidence()

    def mutate(child_context, value):
        return broken(value, "const value = (") if child_context.get("source_step") else value

    generator, transport = source_sequence_generator(tmp_path, complete_output(), mutate=mutate)
    with pytest.raises(ProposalGenerationError, match="SOURCE_JAVASCRIPT_SYNTAX_INVALID"):
        execute(generator, context(), store)
    assert len(transport.calls) == len(store.requests) == 3
    for events in store.events.values():
        assert not any(kind == "ADAPTER_ACCEPTED" for kind, _, _ in events)
        assert events[-1][0] == "APPLICATION_RESULT" and events[-1][1]["status"] == "FAILED"


@pytest.mark.parametrize(
    "code", ["SOURCE_JAVASCRIPT_PARSER_UNAVAILABLE", "GENERATION_EVIDENCE_WRITE_FAILED"]
)
def test_syntax_retry_does_not_retry_parser_or_audit_failure(tmp_path, monkeypatch, code):
    from orchestwin.models import source_file_generation

    failure = (
        ProposalEvidenceError(code)
        if code == "GENERATION_EVIDENCE_WRITE_FAILED"
        else ProposalGenerationError(code)
    )

    def checker(_):
        raise failure

    monkeypatch.setattr(source_file_generation, "validate_source_syntax", checker)
    store = MemoryEvidence()
    generator, transport = source_sequence_generator(tmp_path, complete_output())
    with pytest.raises(type(failure), match=code):
        execute(generator, context(), store)
    assert len(transport.calls) == 2


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
        "manifest_nul",
        "coverage_omitted",
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
            if failure == "manifest_nul":
                value["files"][2]["interface"] = "DOM: field\x00"
            if failure == "coverage_omitted":
                del value["acceptance_checks"]
        elif failure == "carriage_return":
            value = broken(value, "one\rtwo")
        elif failure == "line_control":
            value = broken(value, "\x01")
        elif failure == "content_large":
            value = broken(value, "x" * 32769)
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
    html = "<!DOCTYPE html><html></html>"
    payload["files"].append(
        {**app_file(private_helpers=html), "media_type": "text/plain"}
        if path == "app.js"
        else {"normalized_path": path, "media_type": "text/plain", "content": html}
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
    assert (
        parent_context["manifest_contract"]
        == MANIFEST_CONTRACT
        == ("SOURCE_MANIFEST_V16_APPROVED_DOM_FIRST")
    )
    # The actual audited manifest and both source requests must agree with the
    # JVM console profile, while retaining the shared ban on self-certification.
    for call in transport.calls:
        prompt = call["payload"]["messages"][0]["content"]
        assert "BROWSER:" not in prompt
        assert "must come from real HTML, CSS" not in prompt
        assert "independent browser observations" not in prompt
        assert "isAccessible/isOffline-style functions returning true" in prompt
        assert "actual core and CLI behavior" in prompt
    assert (
        "observable console input/output" in transport.calls[0]["payload"]["messages"][0]["content"]
    )
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


@pytest.mark.parametrize(
    "interface,kept,removed",
    [
        (
            "addGuest(name: string): object; listGuests(): object[]",
            ["addGuest(name: string): object", "listGuests(): object[]"],
            [],
        ),
        (
            "addGuest(name: string): object; displayGuestList(): void; getGuestInputField(): object",
            ["addGuest(name: string): object"],
            ["displayGuestList", "getGuestInputField"],
        ),
        (
            "calculateTip(amount: number, tipPercentage: number): object; "
            "updateResultDisplay(tipAmount: number, totalAmount: number): void; "
            "validateAndShowErrorForAmount(inputValue: string): void; "
            "toggleScreen(screenId: string): void; hideError(): void; "
            "processCalculation(): void; resetApplication(): void; resetItems(): void; "
            "getGuestCount(): number",
            [
                "calculateTip(amount: number, tipPercentage: number): object",
                "resetItems(): void",
                "getGuestCount(): number",
            ],
            [
                "updateResultDisplay",
                "validateAndShowErrorForAmount",
                "toggleScreen",
                "hideError",
                "processCalculation",
                "resetApplication",
            ],
        ),
        ("isUserRegistrationRequired(): boolean", None, None),
        ("hasExternalDependencies(): boolean; saveGuestsToStorage(): void", None, None),
        ("DOM: ELM-001, ELM-002", None, None),
    ],
)
def test_static_interface_keeps_only_pure_business_functions(interface, kept, removed):
    from orchestwin.models.source_file_generation import _validate_static_interface

    if kept is None:
        with pytest.raises(ValueError):
            _validate_static_interface(interface)
        return
    kept_signatures, removed_names, names = _validate_static_interface(interface)
    assert (kept_signatures, removed_names) == (kept, removed)
    assert names == list(dict.fromkeys(signature.split("(")[0] for signature in kept))
