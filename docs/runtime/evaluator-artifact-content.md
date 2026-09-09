# Verified artifact contents for the evaluator — S12 C77–C80

Base: `72e66c17661d717230e08bd028fe9275542a45a9`.
One coherent commit candidate: content-addressed artifact text -> model request
-> existing strict response validation and artifact-specific citations.

## Acceptance criteria

1. Explicitly selected content is read through a trusted application-owned port,
   bounded and checked against the immutable artifact byte count and SHA-256.
2. Actual DOM text or a documented deterministic axe view reaches the model;
   a screenshot identifier is never presented as observed image content.
3. Content, bundle, full evaluation request and evidence citations remain bound.
4. Every returned finding concerns a supplied artifact and cites that artifact.
5. The default metadata-only R2 request and prompt remain byte-for-byte unchanged.
6. Unsupported, corrupt and oversized content stops before generation, without
   silent truncation, repair, external URL fetching or a fallback provider.

## Core API

Use an already owner-authorized `UserTwinEvaluationRequest` and an explicit
selection of `(artifact_id, version_number)` pairs:

```python
prepared = prepare_artifact_content(
    request,
    selected=((artifact.artifact_id, artifact.version_number),),
    read_content=ContentAddressedArtifactReader(authorized_store_root),
)
evaluator = runtime.final_evaluator_runtime.create_evaluator(
    verified_content=prepared.content,
)
response = await evaluator.evaluate(prepared.request)
```

`read_content(key, maximum_bytes)` is a trusted internal port, not a callback,
filesystem path or URL accepted from an HTTP body. The store adapter rejects
non-content-addressed keys, links/junctions and oversized reads. It is not an
ownership resolver. A digest binds bytes to a reference; it is not proof that an
unauthorized caller owns the artifact or that the underlying report is true.

The prepared request adds exact PROJECT_ARTIFACT (DOM) or DETERMINISTIC_TEST (axe)
references. It does not create owner approval, empirical research or validation
records. The original request is left unchanged. The immutable context is bound
to the resulting full request, including twin, bundle, task, time and references.

No database writes, public evaluation endpoint, owner authorization adapter,
User Twin selection UI, workflow node or evaluation persistence are added here.
Those callers must enforce owner scope before invoking this internal API.

## Representations and limits

- DOM_SNAPSHOT / text/html: complete UTF-8 text, not executed and not rendered by
  the evaluator. The byte digest is preserved. It is not a visual layout claim.
- AXE_REPORT / application/json: verify the full original bytes, then keep the
  engine version, outcome rule counts, full violation rule list, and each
  violation node's target, HTML and failureSummary. Keep incomplete rule IDs.
  Explicitly omit detailed passes/inapplicable/incomplete nodes, environment
  metadata and check-level `any`/`all`/`none` details.
- Screenshots and other unselected kinds remain marked metadata-only. Selecting
  an unsupported kind raises an error; no image caption is fabricated.

The axe projection has its own SHA-256, distinct from the source report hash.
It is a deliberately scoped view, not a claim that every source field was sent.
No list is silently cut to fit: limits fail explicitly. Current limits are four
selected artifacts, 2 MiB per source read, 8 KiB per DOM/view and 12 KiB for the
serialized context. Up to 16 violated rules / 32 violation nodes are admitted.
A byte budget is not a tokenizer budget; the serving runtime still enforces its
actual sequence limit. Oversized real projects need explicit context selection,
not an undocumented truncation fallback.

Source text and report strings are untrusted data in the prompt. They grant no
tools or network permissions. This is not a claim of complete prompt-injection
resistance. Structural citation validation is not semantic entailment checking.

## Prompt and compatibility

Explicit content uses `s12-verified-artifact-content-v1`. It extends the observed
field-scope instruction with content, data-trust and modality boundaries. It is
not relabelled as the earlier R2 prompt or an ablation result.

Calling `create_evaluator()` without `verified_content` retains
`s12-local-inference-contract-v2-field-scope` and the same metadata-only payload.
The gateway admits only the two explicit prompt contracts and rejects a content
payload labelled with the old contract. Output schema, JSON field rejection,
identity checks, prompt hash checks, no-repair policy and no-retry policy remain.

## One optional observed content control

After committing and enabling the final evaluator with the existing ready file:

```powershell
python -B scripts/sprint12_verify_artifact_content_evaluator.py --repo-root . --runner-manifest <successful-C63-manifest.json> --output-root <new-external-directory> --run-one-content-evaluation
```

This verifies all files/recipes in the exact successful C63 observation and reads
its real `negative-control.axe.json`. The core resolver has no fixture-specific
branch. Only this explicit operator constructs a synthetic Proto-UT technical
request from that stored report. It performs one live inference through the
normal factory and saves the unmodified request/response privately. It runs no
Docker command or benchmark and performs no SQL query. The server generation
count must rise by one; no retry is attempted on failure or interruption.

A passing control requires domain/schema validation, at least one accessibility
finding, source-specific citations, and explicit model-inferred/unsupported
status with human validation required. It is a contract and transport check,
not an independent quality score, a real-user finding or a formal case result.
Abstention here is preserved as an observed failed positive control, not replaced
by a fabricated finding. The recorded R2 abstention control is untouched.

The new directory may contain client/source text in `*.private.json`; do not
publish it casually. Tokens are not copied into requests or manifests. The safe
manifest is sufficient for reporting a pass or a failure code.

## Verification and state

The applicator runs Ruff, the new tests, existing R2/gateway tests and the full
non-integration Python suite. It isolates ORCHESTWIN_* process overrides in test
subprocesses, without modifying the parent terminal or dotenv files. It performs
no live inference. PostgreSQL/Docker/model tests remain separate observations.

After reported green tests, commit as:
`feat(evaluation): supply verified artifact contents to the final evaluator`.
Record the actual user-provided hash and any live-control outcome in the handoff;
do not mark Sprint 12 or the formal cases complete. The serving process may
remain at its original observed commit. Its old exact-HEAD launcher has not been
changed; do not remove its restart guard.

Primary references: Python JSON decoder/size precautions
https://docs.python.org/3.13/library/json.html ; axe result array semantics
https://www.deque.com/axe/core-documentation/api-documentation/ .
