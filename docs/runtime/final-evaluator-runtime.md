# Final evaluator runtime — S12 C73–C76

This increment integrates the previously observed R2 prompt and metadata bridge
into the repository. The successful R2 technical abstention control is not a
formal case, not empirical user evidence, and not proof of general model quality.
Its original manifest remains unchanged with content hash
`87d7c5ac0a9d64cb392a54c44f80828a2bcea3b05f22a399843b56a00c3511ae`.
The first schema-failing observation remains FAILED.

## Changes

C73: the existing OpenAI-compatible payload builder now transmits the exact
request task ID, prompt version and allowed evidence references. No benchmark
lookup or mutable global current-request slot is introduced.

C74: the observed field-placement instruction is a versioned repository function.
The version remains `s12-local-inference-contract-v2-field-scope` so the observed
prompt is not silently renamed. The default historical evaluator prompt remains
unchanged; the final runtime explicitly selects the observed instruction.

The evaluator now validates all object fields and values against its existing
output schema before domain conversion, and rejects incomplete (LENGTH) output.
Strict JSON parsing rejects duplicate keys and nonfinite numbers. The restricted
schema validator fails on unsupported vocabulary; it is not a general JSON Schema
implementation. No output repair, field removal, coercion or schema widening occurs.

C75: a session-bound port uses direct authenticated loopback HTTP and the existing
OpenAI-compatible adapter. It checks the session before invocation, the returned
identity, exact prompt hash, stop reason, usage and unmodified response. Errors
are not retried and a base-model fallback is never selected. Session tokens are
read from the configured session directory, never from HTTP request bodies, and
are omitted from repr and diagnostics.

C76: the normal ApplicationRuntime and app.state expose a configured evaluator
factory. It constructs a fresh evaluator per invocation rather than a process-wide
instance with accumulating traces. Factory construction performs local file checks
only: no model import, CUDA, HTTP inference, database query or Docker call.

## Explicit opt-in (backend Windows environment)

Set these non-secret variables in the same terminal that launches the backend:

```powershell
$env:ORCHESTWIN_FINAL_EVALUATOR_ENABLED = "true"
$env:ORCHESTWIN_FINAL_EVALUATOR_READY_FILE = "<absolute path to active session ready.json>"
```

Disabled is the default. An enabled configuration with a missing/invalid/terminated
session fails instead of falling back to a fake provider. Do not edit ready.json,
configuration.json or token files. A ready file is not a running server.

The current supported serving contract is the S67 `s67-final-evaluator-serving-v1`
operator at the observed fa9b33e9 base, Qwen/Qwen3-4B-Instruct-2507 at revision
abcc171021d4f320b2e7f47c6f0deca67ded870c and adapter digest
82e051affb54f7fdced4c85780f8724fcc8f47063e27997bb6f5624421422664.
The backend commit may advance independently of the still-running WSL process;
its frozen model configuration identity is not rewritten to the backend commit.
This increment does not port or change the external serving launcher. That launcher
still checks its exact source commit on restart: do not remove that guard to restart
it on a later checkout. Keep the observed session running for the following check;
a maintained restart-compatible serving launcher is separate work.

## Check factory + recorded R2 without another inference

After committing and enabling the settings, run:

```powershell
python -B scripts/sprint12_check_final_evaluator_runtime.py --repo-root . --r2-evidence <original R2 directory>
```

The check constructs the normal application runtime, checks its app-state binding,
queries live authenticated health, verifies all 14 files of the exact R2 observation,
and rebuilds its technical request using repository domain types. A trusted replay
transport returns the recorded raw completion, not a synthetic new model output.
The evaluator factory generates the exact recorded request/prompt/schema/metadata;
strict response and domain validation run again. Request/result trace hashes must
match R2. Live health must show no increase in generation count during the check.
No third-party model library, database query, Docker call or new inference occurs.

The application evaluator ID intentionally differs from the earlier operator-local
probe ID. Semantic output fields and model/prompt identity are compared separately;
the previous evaluation response is not rewritten or re-labelled as application output.

The R2 directory contains private prompt and model-output files. Do not publish it
casually or upload the serving access-token.secret. Only the safe checker JSON is
needed for review. The checker does not change archived evidence or write a new
experimental success record.

## Boundaries still open

There is no new public evaluation endpoint, SQL evaluation persistence, graph
advancement, owner-approved evaluation request, UI artifact-content hydration,
source generation, finalization or full-profile validation here. Consumers must
perform owner-scoped access and assemble actual artifact contents before model
claims about interfaces can be grounded. Metadata alone is not visual evidence.
The evaluator is not the source-code generator. Browser/PostgreSQL validation and
this evaluator integration are separate components, not a complete formal case.

Current host HTTP timeouts and the serving watchdog are not hard GPU preemption.
Loopback HTTP is a local-development boundary, not a production deployment or a
kernel network audit. No independent tokenizer revision observation is added.

## Verification

Native tests in src/test/python cover strict JSON/schema rejection, unchanged
legacy prompt, versioned field scopes, request metadata, final-session integrity,
real local HTTP health/rejection, the port, and factory/app-state composition.
The applicator runs Ruff and the complete non-integration Python suite locally.
No dependency, training lock, database migration or runner image is changed.

Primary protocol references:
- Python JSON decoder hooks: https://docs.python.org/3.13/library/json.html
- Python direct HTTP client: https://docs.python.org/3.13/library/http.client.html
- JSON Schema closed objects: https://json-schema.org/understanding-json-schema/reference/object
