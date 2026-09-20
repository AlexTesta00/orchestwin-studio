"""A synthetic provider supplies both HTML attempts; the application edits neither."""

import hashlib
import json

import pytest

from orchestwin.models.proposal_evidence import ProposalEvidenceError
from orchestwin.models.proposal_generation import ProposalGenerationError
from src.test.python.models.test_proposal_evidence import MemoryEvidence
from src.test.python.models.test_source_design_contract import HTML, PROTOTYPE
from src.test.python.models.test_source_file_generation import (
    complete_output,
    execute,
    source_sequence_generator,
)
from src.test.python.models.test_source_proposals import context


def setup(tmp_path, mutate):
    ctx, payload, store = context(), complete_output(), MemoryEvidence()
    ctx["design"] = {"content": {"prototype": PROTOTYPE}}
    payload["files"][-1]["content"] = HTML
    generator, transport = source_sequence_generator(tmp_path, payload, mutate=mutate)
    return ctx, store, generator, transport


def test_approved_html_is_generated_before_its_consumers_without_rewriting_native_bytes(tmp_path):
    ctx, store, generator, _ = setup(tmp_path, None)
    result = execute(generator, ctx, store)
    parent, html, script, tests = [request for request, _ in store.requests.values()]
    contexts = [
        json.loads(request.input_payload_json)["context"] for request in (html, script, tests)
    ]
    assert [c["source_step"]["file"]["normalized_path"] for c in contexts] == [
        "index.html",
        "app.js",
        "app.test.cjs",
    ]
    assert [c["source_step"]["file"]["depends_on"] for c in contexts] == [
        [],
        ["index.html"],
        ["app.js"],
    ]
    assert contexts[0]["completed_files"] == []
    assert contexts[1]["completed_files"] == [{"normalized_path": "index.html", "content": HTML}]
    assert [f["normalized_path"] for f in contexts[2]["completed_files"]] == [
        "index.html",
        "app.js",
    ]
    assert result.output.files[0].content == HTML
    # The generated HTML is different from prompt guidance and is never substituted.
    assert contexts[0]["dom_reference"]["html"] != HTML
    assert (
        json.loads(parent.input_payload_json)["context"]["dom_reference"]
        == contexts[0]["dom_reference"]
    )
    assert "module.exports" in script.system_instruction
    assert "assert.throws only" in tests.system_instruction


@pytest.mark.parametrize("second_failure", [None, "design", "syntax"])
def test_one_html_retry_preserves_native_bytes_and_exact_structural_feedback(
    tmp_path, second_failure
):
    bad = HTML.replace("data-design-", "data-omitted-")

    def mutate(ctx, output):
        if ctx.get("source_step", {}).get("file", {}).get("normalized_path") == "index.html":
            if "design_retry" not in ctx or second_failure == "design":
                return {"content": bad}
            if second_failure == "syntax":
                return {"content": HTML + "<script>const invalid = (</script>"}
        return output

    ctx, store, generator, transport = setup(tmp_path, mutate)
    if second_failure:
        with pytest.raises(ProposalGenerationError):
            execute(generator, ctx, store)
    else:
        result = execute(generator, ctx, store)
        assert result.output.files[0].content == HTML
    assert len(transport.calls) == len(store.requests) == (3 if second_failure else 5)
    parent, failed, retried, *_remaining = store.requests
    original = json.loads(store.requests[failed][0].input_payload_json)["context"]
    repeat = json.loads(store.requests[retried][0].input_payload_json)["context"]
    retry = repeat.pop("design_retry")
    assert repeat == original and "syntax_retry" not in repeat
    assert retry["previous_generation_id"] == str(failed)
    assert retry["previous_request_hash"] == store.requests[failed][0].content_hash
    assert retry["previous_source_sha256"] == hashlib.sha256(bad.encode()).hexdigest()
    feedback = retry["feedback"]
    assert feedback["source_excerpt"]["text"] == bad[:768]
    assert feedback["diagnostic"] == {
        "reason": "EXACTLY_ONE_MARKER_REQUIRED",
        "attribute": "data-design-screen",
        "value": "SCR-001",
        "actual_count": 0,
    }
    controls = feedback["required_screens"][0]["ordered_elements"]
    assert controls[0]["field_name"] == "number" and controls[0]["required"] is True
    assert controls[1]["options"] == ["Addizione", "Sottrazione"]
    assert controls[2]["data-design-target"] == "SCR-002"
    events = {kind: data for kind, data, _ in store.events[failed]}
    assert events["ADAPTER_REJECTED"]["design_feedback"] == feedback
    assert events["APPLICATION_RESULT"]["status"] == "FAILED"
    assert "ADAPTER_ACCEPTED" not in events
    assert json.loads(events["PROVIDER_RESULT"]["success"]["payload_json"])["content"] == bad
    assert any(kind == "HTTP_RESPONSE" and raw for kind, _, raw in store.events[failed])
    if second_failure:
        assert not any(kind == "ADAPTER_ACCEPTED" for kind, _, _ in store.events[parent])
    else:
        assert result.generation_steps[0]["generation_id"] == str(retried)


@pytest.mark.parametrize("failure", ["transport", "audit"])
def test_html_transport_and_audit_failures_never_trigger_design_retry(tmp_path, failure):
    error = (
        ProposalEvidenceError("GENERATION_EVIDENCE_WRITE_FAILED")
        if failure == "audit"
        else ProposalGenerationError("PROVIDER_UNAVAILABLE")
    )

    def mutate(ctx, output):
        if ctx.get("source_step", {}).get("file", {}).get("normalized_path") == "index.html":
            raise error
        return output

    ctx, store, generator, _ = setup(tmp_path, mutate)
    with pytest.raises(type(error), match=str(error)):
        execute(generator, ctx, store)
    assert len(store.requests) == 2
    assert not any(
        "design_retry" in json.loads(request.input_payload_json)["context"]
        for request, _ in store.requests.values()
    )


def test_syntax_then_design_failure_uses_only_two_html_attempts(tmp_path):
    def mutate(ctx, output):
        if ctx.get("source_step", {}).get("file", {}).get("normalized_path") == "index.html":
            if "syntax_retry" not in ctx:
                return {"content": "<script>const unfinished = (</script>"}
            return {"content": "<html><body>No approved controls</body></html>"}
        return output

    ctx, store, generator, transport = setup(tmp_path, mutate)
    with pytest.raises(ProposalGenerationError, match="SOURCE_DESIGN_STRUCTURE_MISMATCH"):
        execute(generator, ctx, store)
    assert len(transport.calls) == len(store.requests) == 3


def test_failed_rejection_audit_prevents_html_retry(tmp_path):
    def mutate(ctx, output):
        if ctx.get("source_step", {}).get("file", {}).get("normalized_path") == "index.html":
            return {"content": "<html><body>Missing markers</body></html>"}
        return output

    ctx, store, generator, transport = setup(tmp_path, mutate)
    store.fail = "ADAPTER_REJECTED"
    with pytest.raises(ProposalEvidenceError, match="GENERATION_EVIDENCE_WRITE_FAILED"):
        execute(generator, ctx, store)
    assert len(transport.calls) == len(store.requests) == 2
