# Owner-governed static browser inspections (C68–C72)

This increment connects the existing static browser executor to the normal
FastAPI factory, owner-scoped PostgreSQL state and explicit HumanGate decisions.
It is not a full Web execution profile, a LangGraph advancement operation, a
formal case result, or a new source generator.

## Scope and configuration

Disabled by default. Enable in the API process with these non-secret settings:

- `ORCHESTWIN_STATIC_BROWSER_ENABLED=true`
- `ORCHESTWIN_STATIC_BROWSER_REPO_ROOT=<absolute repository root>`
- `ORCHESTWIN_STATIC_BROWSER_RUNNER_MANIFEST=<successful C63 manifest.json>`
- `ORCHESTWIN_STATIC_BROWSER_EVIDENCE_ROOT=<absolute directory outside repository>`

The source content store is the existing C55
`brownfield_workspace_root / "web-source-objects"`. It is not replaced.
The runner manifest and its original artifacts must remain together. No build,
image pull, package installation, alternate tag or registry digest synthesis is
performed. The exact observed local image ID is inspected by the executor.

Apply migration `0032_static_browser_inspections` using the existing migration
CLI after committing and testing this increment. The migration adds one table,
its index and immutability trigger; earlier migrations and training tables are
unchanged. Never use `stamp` to substitute for migration execution. Do not run
integration tests that truncate data against a working project database.

## Six authenticated operations

All paths below are relative to the configured API prefix. Authentication is the
existing bearer authentication; the owner ID is never accepted in a request body.

1. `POST /projects/{project_id}/static-browser-inspections`
2. `GET /projects/{project_id}/static-browser-inspections`
3. `GET /projects/{project_id}/static-browser-inspections/{request_id}`
4. `POST /projects/{project_id}/static-browser-inspections/{request_id}/gate`
5. `POST /projects/{project_id}/static-browser-inspections/{request_id}/execute`
6. `POST /projects/{project_id}/static-browser-inspections/{request_id}/recover`

Prepare accepts an explicit new request UUID, a current source revision UUID,
and one or two declarative scenarios. For example, substitute real source and
request UUIDs in this illustrative body (not a pre-approved formal case input):

```json
{
  "request_id": "<new UUID>",
  "source_revision_id": "<persisted revision UUID>",
  "scenarios": [{
    "id": "basic-interaction",
    "route": "/",
    "actions": [
      {"kind": "click", "selector": "#activate", "value": null},
      {"kind": "expect_text", "selector": "#result", "value": "Expected text"}
    ]
  }]
}
```

Preparation requires an active owner-scoped greenfield project, the current
source revision, and the current Architecture Package exactly approved by Gate 6.
Source provenance must resolve to that architecture version and hash. The
compiler still validates WEB_STATIC scope, immutable bytes and path limits.

The plan freezes complete source bytes, scenarios, source and architecture
identities, observed runner manifest/image, harness hash, commit and fixed
inspector policy. Preparation creates a pending Gate 7 and a SUBMIT audit event
in the same database transaction; it never approves or executes anything.
Public summaries omit base64 source files, but the SQL plan contains those
private source bytes. Do not export a real client's database or evidence casually.

For an owner decision, use the *returned* plan hash and gate event sequence:

```json
{
  "expected_plan_content_hash": "<returned plan hash>",
  "expected_gate_event_sequence": 1,
  "action": "APPROVE",
  "reason": null
}
```

Rejection, pause and cancellation remain available for a pending request whose
source has become stale; approval still requires the exact current source.

The domain's existing actions, reasons, state transitions, audit events and
three-iteration Gate 7 limit remain in force. This is a scope-specific Gate 7
adapter using the existing `human_gates` tables and state machine; it does not
relax the legacy high-impact classifier or forge an entry in its registry-image
request table. Its artifact is a `static_browser_inspections` plan, not a legacy
`HighImpactExecutionRequest`. Use these new decision endpoints for this artifact.
The legacy high-impact UI is not updated by this increment.

Execute and recover accept only:

```json
{"expected_plan_content_hash": "<returned plan hash>"}
```

An arbitrary authorization UUID, a caller-supplied owner, host path, launch flag,
Docker command, profile override or image reference is not accepted. The trusted
resolver rereads the exact persisted approved Gate 7 immediately before handing
its receipt to the browser executor. Rejected, paused, stale, unapproved and
superseded gates cannot authorize execution. A changed source, architecture,
runner, harness or platform commit requires a new plan and owner decision.

## Transactions, concurrency and recovery

The store locks the active owned project for each short transaction. Preparing a
plan while another inspection is RUNNING or another Gate 7 is pending is blocked.
An atomic PENDING → RUNNING claim commits *before* Docker begins. Repeated execute
requests while RUNNING conflict; after a terminal result they return that result
without launching a second container. This is a one-shot request claim, not a
claim of universal exactly-once side effects across machine crashes.

No database transaction is held while the container is running. Before terminal
state is stored, the adapter verifies the manifest, every listed artifact, frozen
job bytes, authority reference, runner/commit binding and raw executor output.
Derived screenshots, DOM, axe and scenario summaries must match the raw decoder.
`COMPLETED` means execution/evidence collection completed; assertions can still
be `FAILED`. Infrastructure errors are not converted to failed-assertion controls.

If the API process is interrupted, RUNNING is retained. Explicit `recover` imports
existing verified terminal evidence only; it does not run Docker or retry work.
Missing or corrupt evidence leaves the operation unresolved. A recorded failure
with unconfirmed container cleanup also blocks preparation of a further request;
operator investigation is required and no cleanup-override endpoint is provided. There is no automatic
retry, stale-claim reset, cancellation of arbitrary containers or data deletion.
The shared Gate 7 audit cannot be used as an immediate cancellation mechanism for
a container that has already started; active-run cancellation is separate work.

Filesystem evidence and SQL state are not a distributed transaction. A failed SQL
finalization can leave complete evidence with a RUNNING claim; recovery addresses
that case. A hard crash without terminal evidence needs operator investigation.

The new database trigger forbids deletion, input mutation, rewinding a claim and
rewriting a terminal result. It does not replace authentication or job validation.
PostgreSQL locking/trigger behavior must still be tested on a dedicated migrated
test database; recording-session tests are not database concurrency evidence.

## Local configuration check

```powershell
python -B scripts/sprint12_check_static_inspection_runtime.py --repo-root .
```

This loads the standard factory, checks that the six operations are registered,
validates the existing runner observation, and checks the new table columns and
revision in a read-only database transaction. It does not create users/projects,
approve gates, run Docker or validate all database constraints. It is not a
substitute for an authenticated end-to-end persisted execution test.

## Remaining boundaries

No frontend screen, User Twin result, model provider, LangGraph advancement,
full-profile WebExecutionAttempt, Vue/Express/JVM execution, repair, export or
formal-case completion is introduced here. The static component retains its
narrow HTML/CSS/JavaScript scope and does not promote any Level D profile. The
previously successful three-fixture run remains a technical validation, not an
owner-gated run of Calculator, Hotel or Weather.

Primary implementation references: SQLAlchemy async session transaction contexts,
https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html ; Alembic operations,
https://alembic.sqlalchemy.org/en/latest/ops.html .
